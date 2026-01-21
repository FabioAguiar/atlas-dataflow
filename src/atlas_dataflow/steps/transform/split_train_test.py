"""
Step canônico: split.train_test (v1).

Responsabilidades (M3):
- Consumir dataset no artifact `data.raw_rows` (lista de dicts).
- Realizar split reprodutível em treino/teste:
  - `test_size` configurável
  - `seed` explícita (determinismo obrigatório)
  - estratificação opcional (quando configurada)
- Produzir artifacts derivados:
  - `data.train`
  - `data.test`
- Produzir auditoria (payload) com impacto do split.

Princípios:
- Decisão declarada: split nunca é implícito.
- Reprodutibilidade total: seed sempre exigida.
- Auditoria obrigatória: parâmetros e shapes registrados no payload/manifest.

Payload mínimo esperado:
payload:
  impact:
    rows_total: int
    rows_train: int
    rows_test: int
    test_size: float
    stratified: bool
    stratify_column: string | null
    seed: int

Referências:
- docs/spec/split.train_test.v1.md
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


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _validate_test_size(test_size: Any) -> float:
    if not isinstance(test_size, (int, float)):
        raise ValueError("Invalid config: test_size must be a number")
    ts = float(test_size)
    if not (0.0 < ts < 1.0):
        raise ValueError("Invalid config: test_size must be between 0 and 1 (exclusive)")
    return ts


def _validate_seed(seed: Any) -> int:
    if seed is None:
        raise ValueError("Invalid config: seed is required for determinism")
    if not isinstance(seed, int):
        raise ValueError("Invalid config: seed must be an int")
    return int(seed)


def _parse_stratify(cfg: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    stratify_cfg = cfg.get("stratify", {})
    if not isinstance(stratify_cfg, dict):
        return False, None
    enabled = bool(stratify_cfg.get("enabled", False))
    col = stratify_cfg.get("column")
    if enabled:
        if not isinstance(col, str) or not col.strip():
            raise ValueError("Invalid config: stratify.column is required when stratify.enabled=true")
        return True, col.strip()
    return False, None


@dataclass
class SplitTrainTestStep(Step):
    """Split reprodutível e auditável de treino/teste (sem heurísticas)."""

    id: str = "split.train_test"
    kind: StepKind = StepKind.TRANSFORM
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # M3 começa após o bloco de ingest/qualidade estrutural.
            self.depends_on = ["transform.deduplicate"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            # ---- dataset ----
            if not ctx.has_artifact("data.raw_rows"):
                raise ValueError("Missing required artifact: data.raw_rows")

            rows = ctx.get_artifact("data.raw_rows")
            if rows is None:
                raise ValueError("Artifact data.raw_rows is None")
            if not isinstance(rows, list):
                raise ValueError("Invalid artifact: data.raw_rows must be a list of rows (dict)")

            # ---- config ----
            cfg = _get_step_cfg(ctx, self.id)

            # Se alguém rodar o Step manualmente com enabled=false, mantém comportamento seguro.
            if cfg.get("enabled") is False:
                payload = {
                    "impact": {
                        "rows_total": int(len(rows)),
                        "rows_train": int(len(rows)),
                        "rows_test": 0,
                        "test_size": 0.0,
                        "stratified": False,
                        "stratify_column": None,
                        "seed": 0,
                        "skipped": True,
                    }
                }
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="split.train_test skipped (disabled in config)",
                    metrics={"rows_total": int(len(rows))},
                    warnings=[],
                    artifacts={},
                    payload=payload,
                )

            test_size = _validate_test_size(cfg.get("test_size", 0.2))
            seed = _validate_seed(cfg.get("seed"))
            stratified, stratify_col = _parse_stratify(cfg)

            # ---- split ----
            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for split.train_test") from e

            try:
                from sklearn.model_selection import train_test_split  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("scikit-learn is required for split.train_test") from e

            df = pd.DataFrame(rows)
            n_total = int(df.shape[0])

            if stratified:
                if stratify_col not in df.columns:
                    raise ValueError(f"Stratify column not found: {stratify_col}")
                y = df[stratify_col]
            else:
                y = None

            try:
                train_df, test_df = train_test_split(
                    df,
                    test_size=test_size,
                    random_state=seed,
                    shuffle=True,
                    stratify=y,
                )
            except Exception as e:
                # Mensagem explícita e orientada ao domínio
                if stratified:
                    raise ValueError(f"Stratified split not possible: {e}") from e
                raise

            # ---- artifacts ----
            # Mantemos formato serializável (list[dict]) para compatibilidade com o core do Atlas.
            train_rows = train_df.to_dict(orient="records")
            test_rows = test_df.to_dict(orient="records")

            ctx.set_artifact("data.train", train_rows)
            ctx.set_artifact("data.test", test_rows)

            payload = {
                "impact": {
                    "rows_total": n_total,
                    "rows_train": int(len(train_rows)),
                    "rows_test": int(len(test_rows)),
                    "test_size": float(test_size),
                    "stratified": bool(stratified),
                    "stratify_column": str(stratify_col) if stratify_col else None,
                    "seed": int(seed),
                }
            }

            ctx.log(
                step_id=self.id,
                level="info",
                message="train/test split completed",
                rows_total=n_total,
                rows_train=int(len(train_rows)),
                rows_test=int(len(test_rows)),
                test_size=float(test_size),
                stratified=bool(stratified),
                stratify_column=str(stratify_col) if stratify_col else None,
                seed=int(seed),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="train/test split completed",
                metrics={
                    "rows_total": n_total,
                    "rows_train": int(len(train_rows)),
                    "rows_test": int(len(test_rows)),
                },
                warnings=[],
                artifacts={"data.train": "data.train", "data.test": "data.test"},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="split.train_test failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "split.train_test failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
