"""Step canônico: audit.outliers_numeric (v1).

Responsabilidades (M3):
- Consumir dataset do RunContext (preferencialmente `data.raw_rows`; se existirem `data.train`/`data.test`,
  audita ambos para consistência).
- Detectar outliers em colunas numéricas sem mutar o dataframe.
- Suportar heurísticas explícitas e opcionais:
  - IQR (Interquartile Range)
  - Z-score (threshold configurável)
- Produzir payload determinístico, serializável e rastreável (via StepResult.payload).

Limites explícitos (v1):
- NÃO remove, corrige, imputa ou altera valores.
- NÃO infere colunas numéricas além do dtype.
- NÃO infere thresholds.

Config esperada (exemplo):
steps:
  audit.outliers_numeric:
    enabled: true
    methods:
      iqr: true
      zscore: false
    zscore_threshold: 3.0

Payload mínimo esperado:
payload:
  outliers:
    <column_name>:
      - method: "iqr" | "zscore"
        count: int
        ratio: float
        bounds:
          lower: float | null
          upper: float | null

Referências:
- docs/spec/audit.outliers_numeric.v1.md (ainda não existe)
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _select_artifacts(ctx: RunContext) -> List[str]:
    # Prefer auditar em train/test se existirem (pós split).
    if ctx.has_artifact("data.train") and ctx.has_artifact("data.test"):
        return ["data.train", "data.test"]
    return ["data.raw_rows"]


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    cfg = ctx.config or {}
    steps_cfg = cfg.get("steps") if isinstance(cfg, dict) else None
    step_cfg = (steps_cfg.get(step_id) or {}) if isinstance(steps_cfg, dict) else {}
    return step_cfg if isinstance(step_cfg, dict) else {}


def _is_numeric_dtype(series: Any) -> bool:
    try:
        import pandas as pd  # type: ignore

        return bool(pd.api.types.is_numeric_dtype(series))
    except Exception:
        return False


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        # bool is subclass of int; outliers for bool are not meaningful here
        if isinstance(x, bool):
            return float(int(x))
        return float(x)
    except Exception:
        return None


def _iqr_bounds(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < 2:
        return (None, None)

    try:
        import numpy as np  # type: ignore
    except Exception:
        # Fallback sem numpy (muito improvável no projeto, mas mantém o core robusto)
        values_sorted = sorted(values)
        def _percentile(p: float) -> float:
            k = (len(values_sorted) - 1) * p
            f = int(k)
            c = min(f + 1, len(values_sorted) - 1)
            if f == c:
                return float(values_sorted[f])
            d0 = values_sorted[f] * (c - k)
            d1 = values_sorted[c] * (k - f)
            return float(d0 + d1)

        q1 = _percentile(0.25)
        q3 = _percentile(0.75)
    else:
        arr = np.array(values, dtype=float)
        q1 = float(np.quantile(arr, 0.25))
        q3 = float(np.quantile(arr, 0.75))

    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return (float(lower), float(upper))


def _zscore_bounds(values: List[float], threshold: float) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    # Retorna: (mean, std, lower, upper) — bounds aproximados para zscore (mean ± threshold*std)
    if len(values) < 2:
        return (None, None, None, None)
    try:
        import numpy as np  # type: ignore
    except Exception:
        mean = sum(values) / float(len(values))
        var = sum((v - mean) ** 2 for v in values) / float(len(values))
        std = var ** 0.5
    else:
        arr = np.array(values, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=0))

    if std == 0.0:
        return (float(mean), float(std), None, None)

    lower = mean - threshold * std
    upper = mean + threshold * std
    return (float(mean), float(std), float(lower), float(upper))


def _count_outliers_iqr(series: Any, lower: Optional[float], upper: Optional[float]) -> int:
    if lower is None or upper is None:
        return 0
    try:
        mask = series.notna() & ((series < lower) | (series > upper))
        return int(mask.sum())
    except Exception:
        # Fallback manual (mantém determinismo, mas pode ser mais lento)
        cnt = 0
        for v in list(series):
            fv = _safe_float(v)
            if fv is None:
                continue
            if fv < lower or fv > upper:
                cnt += 1
        return int(cnt)


def _count_outliers_zscore(series: Any, mean: Optional[float], std: Optional[float], threshold: float) -> int:
    if mean is None or std is None or std == 0.0:
        return 0
    try:
        z = (series - mean) / std
        mask = series.notna() & (z.abs() > threshold)
        return int(mask.sum())
    except Exception:
        cnt = 0
        for v in list(series):
            fv = _safe_float(v)
            if fv is None:
                continue
            z = (fv - mean) / std
            if abs(z) > threshold:
                cnt += 1
        return int(cnt)


@dataclass
class AuditOutliersNumericStep(Step):
    """Detecta outliers em colunas numéricas de forma observacional (audit-only)."""

    id: str = "audit.outliers_numeric"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # Após imputação (se existir) e/ou split. Não força split para permitir fallback raw_rows.
            self.depends_on = ["transform.impute_missing"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            step_cfg = _get_step_cfg(ctx, self.id)
            enabled = step_cfg.get("enabled", True) if isinstance(step_cfg, dict) else True
            if enabled is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SKIPPED,
                    summary="audit.outliers_numeric skipped (disabled)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"outliers": {}, "note": "disabled by config"},
                )

            methods_cfg = step_cfg.get("methods") if isinstance(step_cfg, dict) else None
            methods_cfg = methods_cfg if isinstance(methods_cfg, dict) else {}
            use_iqr = bool(methods_cfg.get("iqr", True))
            use_z = bool(methods_cfg.get("zscore", True))

            if (use_iqr is False) and (use_z is False):
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="audit.outliers_numeric completed (no methods enabled)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"outliers": {}, "note": "no methods enabled"},
                )

            z_thr_raw = step_cfg.get("zscore_threshold", 3.0)
            try:
                z_thr = float(z_thr_raw)
            except Exception:
                z_thr = 3.0

            artifact_keys = _select_artifacts(ctx)

            # Para manter o payload simples e compatível com a spec v1,
            # consolidamos estatísticas por coluna somando os artifacts auditados.
            outliers: Dict[str, List[Dict[str, Any]]] = {}

            for art_key in artifact_keys:
                if not ctx.has_artifact(art_key):
                    raise ValueError(f"Missing required artifact: {art_key}")

                df = ctx.get_artifact(art_key)
                if df is None:
                    raise ValueError(f"Artifact {art_key} is None")

                try:
                    import pandas as pd  # type: ignore
                except Exception as e:
                    raise RuntimeError("pandas is required for audit.outliers_numeric") from e

                if not isinstance(df, pd.DataFrame):
                    raise TypeError(f"Artifact {art_key} must be a pandas DataFrame")

                for col in list(df.columns):
                    s = df[col]
                    if not _is_numeric_dtype(s):
                        continue

                    # Evita tratar boolean como numérico aqui (é numérico no pandas, mas semântica é outra)
                    try:
                        if pd.api.types.is_bool_dtype(s):
                            continue
                    except Exception:
                        pass

                    non_null = int(s.notna().sum())
                    if non_null == 0:
                        # Sem dados: ainda assim emitimos registros determinísticos com count 0.
                        if col not in outliers:
                            outliers[col] = []
                        if use_iqr:
                            outliers[col].append(
                                {
                                    "method": "iqr",
                                    "count": 0,
                                    "ratio": 0.0,
                                    "bounds": {"lower": None, "upper": None},
                                }
                            )
                        if use_z:
                            outliers[col].append(
                                {
                                    "method": "zscore",
                                    "count": 0,
                                    "ratio": 0.0,
                                    "bounds": {"lower": None, "upper": None},
                                }
                            )
                        continue

                    # Extrai valores float para cálculo de bounds (determinístico)
                    vals: List[float] = []
                    for v in list(s.dropna().tolist()):
                        fv = _safe_float(v)
                        if fv is not None:
                            vals.append(fv)

                    if col not in outliers:
                        outliers[col] = []

                    if use_iqr:
                        lower, upper = _iqr_bounds(vals)
                        cnt = _count_outliers_iqr(s, lower, upper)
                        ratio = (cnt / non_null) if non_null > 0 else 0.0
                        outliers[col].append(
                            {
                                "method": "iqr",
                                "count": int(cnt),
                                "ratio": float(ratio),
                                "bounds": {"lower": lower, "upper": upper},
                            }
                        )

                    if use_z:
                        mean, std, lower, upper = _zscore_bounds(vals, z_thr)
                        cnt = _count_outliers_zscore(s, mean, std, z_thr)
                        ratio = (cnt / non_null) if non_null > 0 else 0.0
                        outliers[col].append(
                            {
                                "method": "zscore",
                                "count": int(cnt),
                                "ratio": float(ratio),
                                "bounds": {"lower": lower, "upper": upper},
                            }
                        )

            # Ordenação determinística: colunas por nome; métodos iqr antes de zscore.
            ordered: Dict[str, List[Dict[str, Any]]] = {}
            for col in sorted(outliers.keys()):
                records = outliers[col]
                records_sorted = sorted(records, key=lambda r: (0 if r.get("method") == "iqr" else 1))
                ordered[col] = records_sorted

            payload = {"outliers": ordered}

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="audit.outliers_numeric completed",
                metrics={},
                warnings=[],
                artifacts={},
                payload=payload,
            )

        except Exception as e:
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "audit.outliers_numeric failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
