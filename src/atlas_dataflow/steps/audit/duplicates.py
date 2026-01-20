"""Step canônico: audit.duplicates (v1).

Responsabilidades (M2):
- Consumir dataset carregado (artifact `data.raw_rows`).
- Diagnosticar duplicidade de linhas (considerando todas as colunas).
- Produzir payload mínimo, determinístico e serializável.

Princípios:
- OBSERVAR sem mutar: este Step NÃO altera o dataset.

Limites explícitos (v1):
- NÃO remove duplicados.
- NÃO marca registros.
- NÃO infere chaves de negócio.
- NÃO aplica regras automáticas de tratamento.

Payload mínimo esperado:
payload:
  duplicates:
    rows: int
    ratio: float
    detected: bool
    treatment_policy: string

Referências:
- docs/spec/audit.duplicates.v1.md (ainda não existe)
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Razão determinística e segura (evita divisão por zero)."""
    if denominator <= 0:
        return 0.0
    r = float(numerator / denominator)
    # estabilidade: evita -0.0
    if r == 0.0:
        return 0.0
    return r


@dataclass
class AuditDuplicatesStep(Step):
    """Diagnóstico observacional de duplicidade (linhas completas)."""

    id: str = "audit.duplicates"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # baseline estrutural deve ter rodado antes
            self.depends_on = ["audit.profile_baseline"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            if not ctx.has_artifact("data.raw_rows"):
                raise ValueError("Missing required artifact: data.raw_rows")

            rows = ctx.get_artifact("data.raw_rows")
            if rows is None:
                raise ValueError("Artifact data.raw_rows is None")

            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for audit.duplicates") from e

            # OBS: não muta rows; DataFrame é derivado
            df = pd.DataFrame(rows)

            n_rows = int(df.shape[0])

            if n_rows == 0:
                dup_rows = 0
            else:
                # duplicated considera todas as colunas por padrão
                # keep="first" evita dupla contagem e é determinístico
                mask = df.duplicated(keep="first")
                dup_rows = int(mask.sum())

            ratio = _safe_ratio(dup_rows, n_rows)
            detected = bool(dup_rows > 0)

            payload: Dict[str, Any] = {
                "duplicates": {
                    "rows": dup_rows,
                    "ratio": ratio,
                    "detected": detected,
                    "treatment_policy": "avaliar deduplicação em etapa posterior",
                }
            }

            ctx.log(
                step_id=self.id,
                level="info",
                message="duplicates audit computed",
                rows=dup_rows,
                total_rows=n_rows,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="duplicates audit computed",
                metrics={"rows": n_rows, "duplicates": dup_rows, "ratio": ratio},
                warnings=[],
                artifacts={},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="audit.duplicates failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "audit.duplicates failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
