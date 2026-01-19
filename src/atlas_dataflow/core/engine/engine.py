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
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Sequence

import hashlib
import json

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus

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
        return self._enrich_step_result(step_id=step_id, step=step, result=r)

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

                results[sid] = self._enrich_step_result(step_id=sid, step=step, result=step_result)

            except Exception as e:
                results[sid] = self._mk_result(
                    step_id=sid,
                    step=step,
                    status=StepStatus.FAILED,
                    summary=str(e) or "failed",
                )
                if self._fail_fast():
                    break

        return RunResult(steps=results)
