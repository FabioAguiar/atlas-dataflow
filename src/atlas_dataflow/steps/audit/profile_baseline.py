"""Step canônico: audit.profile_baseline (v1).

Responsabilidades (M2):
- Consumir dataset carregado (artifact `data.raw_rows`).
- Produzir um baseline estrutural mínimo (shape, missing, duplicates, cardinality, dtypes).
- Emitir payload determinístico, serializável e rastreável (via StepResult.payload).

Limites explícitos (v1):
- NÃO muta o dataset.
- NÃO corrige dados.
- NÃO aplica defaults/coerções.
- NÃO infere regras de negócio.

Referências:
- docs/spec/audit.profile_baseline.v1.md (ainda não existe)
- docs/traceability.md
- docs/manifest.schema.v1.md
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _is_missing(value: Any) -> bool:
    return value is None or _is_nan(value)


def _collect_columns(rows: List[Dict[str, Any]]) -> List[str]:
    cols: set[str] = set()
    for r in rows:
        if isinstance(r, dict):
            cols.update(r.keys())
    return sorted(cols)


def _jsonable_hash_key(value: Any) -> Any:
    """Converte valores potencialmente não-hashable em algo estável e determinístico."""
    if _is_missing(value):
        return None

    # primitivos já são estáveis
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        # normaliza -0.0
        if value == 0.0:
            return 0.0
        return value
    if isinstance(value, bool):
        return value

    # temporais
    if isinstance(value, datetime):
        # isoformat é determinístico
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()

    # containers
    if isinstance(value, (list, tuple)):
        return [ _jsonable_hash_key(v) for v in value ]
    if isinstance(value, dict):
        # ordena por chave para determinismo
        return { str(k): _jsonable_hash_key(value[k]) for k in sorted(value.keys(), key=lambda x: str(x)) }

    # fallback: repr (determinístico o suficiente para v1)
    return repr(value)


def _row_fingerprint(row: Dict[str, Any]) -> str:
    """Fingerprint determinístico por linha, para detecção de duplicados."""
    if not isinstance(row, dict):
        payload = {"__row__": _jsonable_hash_key(row)}
    else:
        payload = {str(k): _jsonable_hash_key(row.get(k)) for k in sorted(row.keys())}

    # json determinístico
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return dumped


def _missing_profile(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Any]:
    total_rows = len(rows)
    per_col: Dict[str, Any] = {}

    for col in columns:
        miss = 0
        for r in rows:
            v = r.get(col) if isinstance(r, dict) else None
            if _is_missing(v):
                miss += 1

        ratio = (miss / total_rows) if total_rows > 0 else 0.0
        per_col[col] = {
            "count": int(miss),
            "ratio": float(ratio),
            "is_fully_null": bool(total_rows > 0 and miss == total_rows),
        }

    return {"per_column": per_col}


def _duplicates_profile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_rows = len(rows)
    if total_rows == 0:
        return {"rows": 0, "ratio": 0.0}

    seen: set[str] = set()
    dup = 0
    for r in rows:
        fp = _row_fingerprint(r if isinstance(r, dict) else {"__row__": r})
        if fp in seen:
            dup += 1
        else:
            seen.add(fp)

    return {"rows": int(dup), "ratio": float(dup / total_rows)}


def _cardinality_profile(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Any]:
    total_rows = len(rows)
    out: Dict[str, Any] = {}

    for col in columns:
        uniques: set[str] = set()
        for r in rows:
            v = r.get(col) if isinstance(r, dict) else None
            if _is_missing(v):
                continue
            key = json.dumps(_jsonable_hash_key(v), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            uniques.add(key)

        uv = len(uniques)
        high = (total_rows > 0 and uv > (0.5 * total_rows))
        out[col] = {
            "unique_values": int(uv),
            "high_cardinality": bool(high),
        }

    return out


def _dtype_family(value: Any) -> Tuple[str, str]:
    """Retorna (inferred, family)."""
    if _is_missing(value):
        return ("missing", "other")

    if isinstance(value, bool):
        return ("bool", "categorical")
    if isinstance(value, int):
        return ("int", "numeric")
    if isinstance(value, float):
        return ("float", "numeric")
    if isinstance(value, str):
        return ("str", "categorical")
    if isinstance(value, datetime):
        return ("datetime", "temporal")
    if isinstance(value, date):
        return ("date", "temporal")

    return (type(value).__name__, "other")


def _dtypes_profile(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    for col in columns:
        inferred_set: set[str] = set()
        family_set: set[str] = set()

        for r in rows:
            v = r.get(col) if isinstance(r, dict) else None
            if _is_missing(v):
                continue
            inferred, fam = _dtype_family(v)
            inferred_set.add(inferred)
            family_set.add(fam)

        if not inferred_set:
            out[col] = {"inferred": "empty", "family": "other"}
        elif len(inferred_set) == 1 and len(family_set) == 1:
            out[col] = {"inferred": next(iter(inferred_set)), "family": next(iter(family_set))}
        else:
            # mistura de tipos: assume 'other' para evitar decisões implícitas
            out[col] = {"inferred": "mixed", "family": "other"}

    return out


@dataclass
class AuditProfileBaselineStep(Step):
    """Baseline estrutural mínimo do dataset (sem mutações)."""

    id: str = "audit.profile_baseline"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = ["ingest.load"]

    def run(self, ctx: RunContext) -> StepResult:
        cfg = ctx.config or {}
        steps_cfg = cfg.get("steps") if isinstance(cfg, dict) else None
        step_cfg = (
            (steps_cfg.get(self.id) or {})
            if isinstance(steps_cfg, dict)
            else {}
        )

        enabled = step_cfg.get("enabled", True) if isinstance(step_cfg, dict) else True
        if enabled is False:
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

        try:
            if not ctx.has_artifact("data.raw_rows"):
                raise ValueError("Missing required artifact: data.raw_rows")

            raw_rows = ctx.get_artifact("data.raw_rows")
            if not isinstance(raw_rows, list):
                raise ValueError("data.raw_rows must be a list of dicts")

            # NÃO mutar: trabalhar apenas por leitura
            rows: List[Dict[str, Any]] = [r for r in raw_rows if isinstance(r, dict)]

            columns = _collect_columns(rows)
            n_rows = len(rows)
            n_cols = len(columns)

            payload = {
                "shape": {"rows": int(n_rows), "columns": int(n_cols)},
                "missing": _missing_profile(rows, columns),
                "duplicates": _duplicates_profile(rows),
                "cardinality": _cardinality_profile(rows, columns),
                "dtypes": _dtypes_profile(rows, columns),
            }

            ctx.log(
                step_id=self.id,
                level="info",
                message="baseline profile computed",
                rows=n_rows,
                columns=n_cols,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="baseline profile computed",
                metrics={"rows": int(n_rows), "columns": int(n_cols)},
                warnings=[],
                artifacts={},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="audit.profile_baseline failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "audit.profile_baseline failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
