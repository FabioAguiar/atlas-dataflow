"""Step canônico: audit.schema_types (v1).

Responsabilidades (M2):
- Consumir dataset carregado (artifact `data.raw_rows`).
- Produzir auditoria detalhada por coluna:
  - dtype inferido (pandas dtype)
  - tipo semântico básico (numeric | categorical | temporal | other)
  - nulos (count / ratio)
  - cardinalidade (unique_values / is_constant)
  - exemplos representativos (até 5, serializáveis)

Princípios:
- OBSERVAR sem mutar: este Step NÃO altera o dataset.

Limites explícitos (v1):
- NÃO valida contra contrato.
- NÃO corrige tipos.
- NÃO aplica coerções/defaults.
- NÃO infere regras de negócio.

Payload mínimo esperado:
payload:
  columns:
    <column_name>:
      dtype: string
      semantic_type: string
      nulls:
        count: int
        ratio: float
      cardinality:
        unique_values: int
        is_constant: bool
      examples:
        - any

Referências:
- docs/spec/audit.schema_types.v1.md (ainda não existe)
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _jsonable(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, bool):
        return bool(value)

    if isinstance(value, (int, float, str)):
        if isinstance(value, float) and value == 0.0:
            return 0.0
        return value

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()

    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.integer, np.floating, np.bool_)):
            py = value.item()
            if isinstance(py, float) and py == 0.0:
                return 0.0
            return py
    except Exception:
        pass

    try:
        import pandas as pd  # type: ignore

        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, pd.Timedelta):
            return str(value)
    except Exception:
        pass

    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
        if len(b) > 24:
            return repr(b[:24]) + "...(truncated)"
        return repr(b)

    try:
        return str(value)
    except Exception:
        return repr(value)


def _semantic_type_for_series(series) -> str:
    try:
        import pandas as pd  # type: ignore
        from pandas.api.types import (  # type: ignore
            is_bool_dtype,
            is_datetime64_any_dtype,
            is_numeric_dtype,
            is_object_dtype,
            is_string_dtype,
        )

        dtype = series.dtype

        if is_datetime64_any_dtype(dtype):
            return "temporal"
        if is_numeric_dtype(dtype):
            return "numeric"
        if is_bool_dtype(dtype):
            return "categorical"
        if isinstance(dtype, pd.CategoricalDtype) or is_object_dtype(dtype) or is_string_dtype(dtype):
            return "categorical"

        return "other"
    except Exception:
        return "other"


def _examples_for_series(series, max_examples: int = 5) -> List[Any]:
    examples: List[Any] = []
    seen: set = set()

    for v in series.tolist():
        if v is None:
            continue
        try:
            import pandas as pd  # type: ignore

            if pd.isna(v):
                continue
        except Exception:
            pass

        j = _jsonable(v)
        key = (type(j).__name__, str(j))
        if key in seen:
            continue
        seen.add(key)
        examples.append(j)
        if len(examples) >= max_examples:
            break

    if not examples:
        return []
    return examples


@dataclass
class AuditSchemaTypesStep(Step):
    id: str = "audit.schema_types"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
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
            except Exception as e:
                raise RuntimeError("pandas is required for audit.schema_types") from e

            df = pd.DataFrame(rows)

            n_rows = int(df.shape[0])
            columns_payload: Dict[str, Any] = {}

            for col in df.columns.tolist():
                s = df[col]

                null_count = int(s.isna().sum())
                null_ratio = float(null_count / n_rows) if n_rows > 0 else 0.0

                unique_values = int(s.nunique(dropna=True))
                is_constant = bool(unique_values == 1 and (n_rows - null_count) > 0)

                dtype_str = str(s.dtype)
                sem_type = _semantic_type_for_series(s)

                examples = _examples_for_series(s, max_examples=5)

                columns_payload[str(col)] = {
                    "dtype": dtype_str,
                    "semantic_type": sem_type,
                    "nulls": {"count": null_count, "ratio": null_ratio},
                    "cardinality": {"unique_values": unique_values, "is_constant": is_constant},
                    "examples": examples,
                }

            payload = {"columns": columns_payload}

            ctx.log(
                step_id=self.id,
                level="info",
                message="schema types audit computed",
                rows=n_rows,
                columns=int(df.shape[1]),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="schema types audit computed",
                metrics={"rows": n_rows, "columns": int(df.shape[1])},
                warnings=[],
                artifacts={},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="audit.schema_types failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "audit.schema_types failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
