"""Step canônico: transform.deduplicate (v1).

Responsabilidades (M2):
- Consumir dataset carregado (artifact `data.raw_rows`).
- Remover duplicados **somente** quando explicitamente configurado.
- Suportar modos:
  - full_row: deduplicação por linha completa (todas as colunas)
  - key_based: deduplicação por subset de colunas (chave lógica declarada)
- Produzir auditoria obrigatória de antes/depois.

Princípios:
- Deduplicação é uma decisão declarativa, não correção automática.
- Nenhuma remoção sem auditoria.
- Determinismo: política fixa v1 = manter a primeira ocorrência (keep="first").

Config esperada (exemplo):
steps:
  transform.deduplicate:
    enabled: true
    mode: key_based
    key_columns:
      - id
      - date

Payload mínimo esperado:
payload:
  impact:
    mode: full_row | key_based
    key_columns: [string] | null
    rows_before: int
    rows_after: int
    rows_removed: int

Limites explícitos (v1):
- NÃO decide automaticamente se deve deduplicar.
- NÃO infere chaves.
- NÃO faz deduplicação fuzzy.
- NÃO resolve conflitos ou consolida registros.

Referências:
- docs/spec/transform.deduplicate.v1.md (ainda não existe)
- docs/spec/audit.duplicates.v1.md
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    cfg = ctx.config or {}
    if not isinstance(cfg, dict):
        return {}
    steps_cfg = cfg.get("steps")
    if not isinstance(steps_cfg, dict):
        return {}
    step_cfg = steps_cfg.get(step_id) or {}
    return step_cfg if isinstance(step_cfg, dict) else {}


def _validate_config(step_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Valida config do step.

    Regras v1:
    - enabled deve ser bool (default False)
    - se enabled True:
        - mode obrigatório: 'full_row' | 'key_based'
        - se mode == 'key_based': key_columns obrigatório (list[str] não vazia)
        - se mode == 'full_row': key_columns deve ser ausente/None
    """
    enabled = step_cfg.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("steps.transform.deduplicate.enabled must be a bool")

    if enabled is False:
        return {"enabled": False}

    mode = step_cfg.get("mode")
    if mode not in ("full_row", "key_based"):
        raise ValueError("steps.transform.deduplicate.mode must be 'full_row' or 'key_based'")

    key_columns = step_cfg.get("key_columns", None)

    if mode == "full_row":
        if key_columns not in (None, [], ""):
            # explícito: evita ambiguidade silenciosa
            raise ValueError("key_columns must be null/absent when mode is 'full_row'")
        return {"enabled": True, "mode": "full_row", "key_columns": None}

    # mode == key_based
    if not isinstance(key_columns, list) or not key_columns:
        raise ValueError("key_columns must be a non-empty list when mode is 'key_based'")
    cleaned: List[str] = []
    for c in key_columns:
        if not isinstance(c, str) or not c.strip():
            raise ValueError("key_columns must contain only non-empty strings")
        cleaned.append(c.strip())
    return {"enabled": True, "mode": "key_based", "key_columns": cleaned}


@dataclass
class TransformDeduplicateStep(Step):
    """Deduplicação controlada (config-driven) com auditoria obrigatória."""

    id: str = "transform.deduplicate"
    kind: StepKind = StepKind.TRANSFORM
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = ["audit.duplicates"]

    def run(self, ctx: RunContext) -> StepResult:
        step_cfg = _get_step_cfg(ctx, self.id)

        try:
            parsed = _validate_config(step_cfg)
            if parsed.get("enabled") is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SKIPPED,
                    summary="step disabled by config",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"disabled": True},
                )

            if not ctx.has_artifact("data.raw_rows"):
                raise ValueError("Missing required artifact: data.raw_rows")

            raw_rows = ctx.get_artifact("data.raw_rows")
            if raw_rows is None:
                raise ValueError("Artifact data.raw_rows is None")
            if not isinstance(raw_rows, list):
                raise ValueError("data.raw_rows must be a list of dicts")

            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for transform.deduplicate") from e

            df = pd.DataFrame(raw_rows)
            rows_before = int(df.shape[0])

            mode: str = parsed["mode"]
            key_columns: Optional[List[str]] = parsed.get("key_columns")

            if mode == "full_row":
                df_after = df.drop_duplicates(keep="first")
            else:
                assert key_columns is not None  # for mypy
                # valida que as colunas existem (sem heurística)
                missing = [c for c in key_columns if c not in df.columns]
                if missing:
                    raise ValueError(f"key_columns not found in dataset: {missing}")
                df_after = df.drop_duplicates(subset=key_columns, keep="first")

            rows_after = int(df_after.shape[0])
            rows_removed = int(rows_before - rows_after)

            impact = {
                "mode": mode,
                "key_columns": key_columns if mode == "key_based" else None,
                "rows_before": rows_before,
                "rows_after": rows_after,
                "rows_removed": rows_removed,
            }

            # Atualiza o dataset somente após auditoria calculada
            ctx.set_artifact("data.raw_rows", df_after.to_dict(orient="records"))

            ctx.log(
                step_id=self.id,
                level="info",
                message="deduplicate applied",
                mode=mode,
                rows_before=rows_before,
                rows_after=rows_after,
                rows_removed=rows_removed,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="deduplication applied (config-driven)",
                metrics={
                    "rows_before": rows_before,
                    "rows_after": rows_after,
                    "rows_removed": rows_removed,
                },
                warnings=[],
                artifacts={},
                payload={"impact": impact},
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="transform.deduplicate failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "transform.deduplicate failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
