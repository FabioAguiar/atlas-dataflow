# src/atlas_dataflow/core/engine/engine.py
"""
Engine de execução do pipeline do Atlas DataFlow.

Correção (compatibilidade com StepResult frozen dataclass):
- O Engine **não** muta instâncias de StepResult in-place.
- Qualquer enriquecimento (warnings/impact/payload_meta) é feito via
  criação de uma **nova** instância (dataclasses.replace).

Ajustes (M1):
- Aceitar payloads maiores em Steps `transform` (sem truncamento).
- Garantir rastreabilidade correta para o Manifest via StepResult:
    - merge de warnings do RunContext
    - incorporação de `impact` (quando presente no RunContext) no payload
    - metadados leves do payload (bytes + sha256) em artifacts

Ajustes (M9-02 — Quality/Guardrails):
- Capturar falhas e converter exceções em AtlasErrorPayload (serializável e acionável).
- Persistir erro (via StepResult.payload["error"]) para consumo de manifest/reports.
- Retornar FAILED com payload estruturado (sem stack trace cru para o operador).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Sequence

import hashlib
import json

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus

from atlas_dataflow.core.errors import (
    AtlasErrorPayload,
    ENGINE_CONFIGURATION_ERROR,
    ENGINE_EXECUTION_ERROR,
)
from atlas_dataflow.core.exceptions import AtlasException

from .planner import plan_execution


@dataclass(frozen=True)
class RunResult:
    """Resultado agregado de uma execução de pipeline (RunResult v1)."""

    steps: Dict[str, StepResult] = field(default_factory=dict)


class Engine:
    """Engine canônico do Atlas DataFlow (planner + executor)."""

    def __init__(self, *, steps: Sequence[Step], ctx: RunContext):
        self.steps: List[Step] = list(steps)
        self.ctx: RunContext = ctx

    def _is_enabled(self, step_id: str) -> bool:
        steps_cfg = (self.ctx.config or {}).get("steps", {}) or {}
        step_cfg = steps_cfg.get(step_id, {}) or {}
        enabled = step_cfg.get("enabled", True)
        return bool(enabled)

    def _fail_fast(self) -> bool:
        engine_cfg = (self.ctx.config or {}).get("engine", {}) or {}
        return bool(engine_cfg.get("fail_fast", True))

    # ------------------------------------------------------------------
    # Guardrails (M9-02): exceção -> AtlasErrorPayload
    # ------------------------------------------------------------------

    def _exception_to_error(self, exc: Exception) -> AtlasErrorPayload:
        """Converte exceções em AtlasErrorPayload (serializável, acionável).

        Regras:
        - AtlasException: já vem com message/details/hint/decision_required.
        - Outras exceções: encapsular como ENGINE_EXECUTION_ERROR sem expor stack trace.
        """
        if isinstance(exc, AtlasException):
            # O tipo do erro é responsabilidade do chamador/mapeador externo.
            # Aqui, por padrão, usamos o nome da classe como código estável.
            return AtlasErrorPayload(
                type=exc.__class__.__name__,
                message=str(exc) or "Erro de execução",
                details=dict(getattr(exc, "details", {}) or {}),
                hint=getattr(exc, "hint", None),
                decision_required=bool(getattr(exc, "decision_required", False)),
            )

        # Fallback genérico
        return AtlasErrorPayload(
            type=ENGINE_EXECUTION_ERROR,
            message=str(exc) or "Erro inesperado durante execução",
            details={
                "exception_class": exc.__class__.__name__,
            },
            hint="Verifique o log técnico e a configuração do pipeline",
            decision_required=False,
        )

    def _persist_step_result_for_manifest(self, step_result: StepResult) -> None:
        """Persistência best-effort para Manifest.

        O Engine não é dono do schema do Manifest aqui, mas garante que:
        - StepResult carregue payload["error"] quando houver falha
        - Caso o RunContext ofereça um writer/registrador de manifest, o Engine tenta usá-lo

        Importante: a persistência é *best-effort* para não quebrar compatibilidade.
        """
        # Padrões comuns no projeto (tentativas seguras)
        try:
            manifest = getattr(self.ctx, "manifest", None)
            if manifest is not None:
                if hasattr(manifest, "record_step_result"):
                    manifest.record_step_result(step_result)  # type: ignore[attr-defined]
                    return
                if hasattr(manifest, "add_step_result"):
                    manifest.add_step_result(step_result)  # type: ignore[attr-defined]
                    return
                if hasattr(manifest, "update_step"):
                    manifest.update_step(step_result.step_id, step_result)  # type: ignore[attr-defined]
                    return

            store = getattr(self.ctx, "store", None)
            if store is not None:
                m = getattr(store, "manifest", None)
                if m is not None:
                    if hasattr(m, "record_step_result"):
                        m.record_step_result(step_result)  # type: ignore[attr-defined]
                        return
                    if hasattr(m, "save_step_result"):
                        m.save_step_result(step_result)  # type: ignore[attr-defined]
                        return
        except Exception:
            # Nunca deixar persistência de manifest quebrar execução
            return

    # ------------------------------------------------------------------
    # Rastreamento (forense): helpers para enriquecer StepResult
    # ------------------------------------------------------------------
    def _ctx_warnings_for(self, step_id: str) -> List[str]:
        warnings_map = getattr(self.ctx, "warnings", {}) or {}
        w = warnings_map.get(step_id, []) or []
        return list(w)

    def _ctx_impact_for(self, step_id: str) -> Any | None:
        impacts = getattr(self.ctx, "impacts", None)
        if not isinstance(impacts, dict):
            return None
        return impacts.get(step_id)

    def _payload_meta(self, payload: Any) -> Dict[str, Any]:
        """Gera metadados leves para rastreabilidade do payload (sem truncar)."""
        try:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except Exception:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")

        return {
            "payload_bytes": int(len(raw)),
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def _enrich_step_result(self, *, step_id: str, step: Step, result: StepResult) -> StepResult:
        """Retorna uma NOVA instância StepResult enriquecida para rastreabilidade.

        Importante: StepResult é frozen. Não mutar campos.
        """
        desired_kind = getattr(result, "kind", None) or getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC

        # warnings (ctx + result) — sem duplicatas
        existing = list(getattr(result, "warnings", []) or [])
        ctx_w = self._ctx_warnings_for(step_id)
        merged_w: List[str] = []
        seen = set()
        for msg in existing + ctx_w:
            if msg not in seen:
                merged_w.append(msg)
                seen.add(msg)

        # payload + impact
        payload = dict(getattr(result, "payload", {}) or {})
        impact = self._ctx_impact_for(step_id)
        if impact is not None and "impact" not in payload:
            payload["impact"] = impact

        # artifacts + payload_meta
        artifacts = dict(getattr(result, "artifacts", {}) or {})
        artifacts.setdefault("payload_meta", self._payload_meta(payload))

        return replace(
            result,
            step_id=step_id,
            kind=desired_kind,
            warnings=merged_w,
            payload=payload,
            artifacts=artifacts,
        )

    def _mk_result(
        self,
        *,
        step_id: str,
        step: Step,
        status: StepStatus,
        summary: str,
        metrics: Dict[str, Any] | None = None,
        artifacts: Dict[str, Any] | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> StepResult:
        kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
        r = StepResult(
            step_id=step_id,
            kind=kind,
            status=status,
            summary=summary,
            metrics=dict(metrics or {}),
            warnings=[],
            artifacts=dict(artifacts or {}),
            payload=dict(payload or {}),
        )
        enriched = self._enrich_step_result(step_id=step_id, step=step, result=r)
        # best-effort persistência para manifest
        self._persist_step_result_for_manifest(enriched)
        return enriched

    def run(self) -> RunResult:
        ordered = plan_execution(self.steps)

        results: Dict[str, StepResult] = {}
        for step in ordered:
            sid = step.id

            if not self._is_enabled(sid):
                results[sid] = self._mk_result(
                    step_id=sid,
                    step=step,
                    status=StepStatus.SKIPPED,
                    summary="skipped by config",
                )
                continue

            deps = list(getattr(step, "depends_on", []) or [])
            if any(results.get(d) and results[d].status == StepStatus.FAILED for d in deps):
                results[sid] = self._mk_result(
                    step_id=sid,
                    step=step,
                    status=StepStatus.SKIPPED,
                    summary="skipped due to failed dependency",
                )
                continue

            try:
                step_result = step.run(self.ctx)
                if not isinstance(step_result, StepResult):
                    raise TypeError("Step.run(ctx) must return StepResult")

                enriched = self._enrich_step_result(step_id=sid, step=step, result=step_result)
                results[sid] = enriched
                self._persist_step_result_for_manifest(enriched)

            except Exception as e:
                atlas_error = self._exception_to_error(e)

                # Se for erro de configuração do próprio Engine (ex.: Step.run retornou tipo errado),
                # marcamos com código estável de configuração/execução do engine.
                if isinstance(e, TypeError) and "must return StepResult" in (str(e) or ""):
                    atlas_error = AtlasErrorPayload(
                        type=ENGINE_CONFIGURATION_ERROR,
                        message="Step retornou tipo inválido",
                        details={
                            "step_id": sid,
                            "expected": "StepResult",
                            "received": e.__class__.__name__,
                        },
                        hint="Ajuste o Step para retornar StepResult",
                        decision_required=False,
                    )

                failed = self._mk_result(
                    step_id=sid,
                    step=step,
                    status=StepStatus.FAILED,
                    summary=atlas_error.message,
                    payload={
                        "error": atlas_error.to_dict(),
                    },
                )
                results[sid] = failed

                if self._fail_fast():
                    break

        return RunResult(steps=results)
