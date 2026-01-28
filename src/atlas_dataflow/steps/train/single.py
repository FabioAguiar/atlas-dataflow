"""Step canônico: train.single (v1).

Treinamento simples e determinístico de um único modelo (sem search).

Responsabilidades (M5):
- Receber `model_id` (ModelRegistry) e `seed` explícita via config.
- Carregar/consumir o preprocess persistido (PreprocessStore) e aplicá-lo:
  - fit no treino
  - transform no treino e no teste
- Instanciar o modelo com default params (sem tuning).
- Treinar no conjunto de treino e avaliar no conjunto de teste.
- Produzir métricas padrão: accuracy, precision, recall, f1.
- Registrar rastreabilidade via StepResult (métricas + referência de artefatos).

Princípios do Atlas:
- Sem inferência de modelo, métricas ou parâmetros.
- Seed explícita para determinismo quando suportado.
- Sem persistência do modelo treinado (fora de escopo v1).

Config esperada (exemplo):

steps:
  train.single:
    enabled: true
    model_id: logistic_regression
    seed: 42

Artifacts esperados (entrada):
- data.train: list[dict]
- data.test: list[dict]
- preprocess.joblib persistido no run_dir (ctx.meta[run_dir]/artifacts/preprocess.joblib)

Artifacts produzidos (saída):
- model.trained: estimador treinado (não serializável; guardado apenas no RunContext)

Referências:
- docs/spec/train.single.v1.md
- docs/spec/model_registry.v1.md
- docs/spec/representation.preprocess.v1.md
- docs/traceability.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.modeling.model_registry import ModelRegistry
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _require_int(cfg: Dict[str, Any], key: str) -> int:
    v = cfg.get(key)
    if v is None:
        raise ValueError(f"Invalid config: {key} is required")
    if not isinstance(v, int):
        raise ValueError(f"Invalid config: {key} must be an int")
    return int(v)


def _require_str(cfg: Dict[str, Any], key: str) -> str:
    v = cfg.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Invalid config: {key} is required")
    return v.strip()


def _get_run_dir(ctx: RunContext) -> str:
    # Convenção atual do projeto: testes e harness usam tmp_path.
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    run_dir = md.get("run_dir") or md.get("tmp_path")
    if run_dir is None:
        raise ValueError("Missing required meta: run_dir (or tmp_path)")
    return str(run_dir)


def _get_dataset_parts(ctx: RunContext) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not ctx.has_artifact("data.train"):
        raise ValueError("Missing required artifact: data.train")
    if not ctx.has_artifact("data.test"):
        raise ValueError("Missing required artifact: data.test")

    train_rows = ctx.get_artifact("data.train")
    test_rows = ctx.get_artifact("data.test")
    if not isinstance(train_rows, list) or not all(isinstance(r, dict) for r in train_rows):
        raise ValueError("Invalid artifact: data.train must be a list[dict]")
    if not isinstance(test_rows, list) or not all(isinstance(r, dict) for r in test_rows):
        raise ValueError("Invalid artifact: data.test must be a list[dict]")
    return train_rows, test_rows


def _json_safe(obj: Any) -> Any:
    # Evita falhas de serialização em params.
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    return str(obj)


def _apply_seed_if_supported(estimator: Any, seed: int) -> Any:
    """Aplica seed explicitamente quando o estimador expõe random_state."""
    try:
        params = estimator.get_params(deep=False)
    except Exception:
        return estimator

    if "random_state" in params:
        try:
            estimator.set_params(random_state=seed)
        except Exception:
            # Se o estimador expõe o param mas rejeita valores, falha explicitamente.
            raise ValueError("Estimator does not accept random_state seed")
    return estimator


def _select_pos_label(cfg: Dict[str, Any], y_true: Any) -> Any:
    """Escolhe pos_label de forma determinística.

    Motivação:
    - ingest.load (CSV) produz strings (ex.: '0'/'1')
    - sklearn precision/recall/f1 default usa pos_label=1 (int), o que falha com labels string

    Regras:
    - Se config informar `pos_label`, usa exatamente esse valor
    - Caso contrário:
      - Se labels contêm '1' (string) e NÃO contêm 1 (int), usa '1'
      - Senão usa 1 (default histórico)
    """
    if isinstance(cfg, dict) and "pos_label" in cfg:
        return cfg.get("pos_label")

    try:
        # pandas Series -> unique()
        labels = set(getattr(y_true, "unique")())
    except Exception:
        try:
            labels = set(y_true)
        except Exception:
            labels = set()

    if "1" in labels and 1 not in labels:
        return "1"
    return 1


@dataclass
class TrainSingleStep(Step):
    """Treino simples (baseline) com seed explícita e métricas padrão."""

    id: str = "train.single"
    kind: StepKind = StepKind.TRAIN
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # Dependências semânticas mínimas do M4.
            self.depends_on = [
                "split.train_test",
            ]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            if cfg.get("enabled") is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="train.single skipped (disabled in config)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"skipped": True},
                )

            model_id = _require_str(cfg, "model_id")
            seed = _require_int(cfg, "seed")

            # ---- inputs ----
            train_rows, test_rows = _get_dataset_parts(ctx)
            run_dir = _get_run_dir(ctx)

            # ---- contract / target ----
            contract = ctx.contract or {}
            target = contract.get("target") if isinstance(contract, dict) else None
            if not isinstance(target, dict):
                raise ValueError("Invalid contract: target must be a mapping")
            target_name = target.get("name")
            if not isinstance(target_name, str) or not target_name.strip():
                raise ValueError("Invalid contract: target.name is required")
            target_col = target_name.strip()

            # ---- pandas ----
            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for train.single") from e

            df_train = pd.DataFrame(train_rows)
            df_test = pd.DataFrame(test_rows)

            if target_col not in df_train.columns:
                raise ValueError(f"Target column not found in train data: {target_col}")
            if target_col not in df_test.columns:
                raise ValueError(f"Target column not found in test data: {target_col}")

            y_train = df_train[target_col]
            y_test = df_test[target_col]
            X_train = df_train.drop(columns=[target_col])
            X_test = df_test.drop(columns=[target_col])

            # ---- preprocess ----
            store = PreprocessStore(run_dir=run_dir)
            preprocess = store.load()

            # fit only on train
            preprocess.fit(X_train)
            # Persist fitted preprocess so downstream steps (e.g., evaluate.metrics) can transform deterministically
            store.save(preprocess=preprocess)
            Xtr = preprocess.transform(X_train)
            Xte = preprocess.transform(X_test)

            # ---- model ----
            registry = ModelRegistry.v1()
            try:
                estimator = registry.build(model_id)
            except KeyError as e:
                raise ValueError(str(e).replace("'", ""))

            estimator = _apply_seed_if_supported(estimator, seed)

            estimator.fit(Xtr, y_train)
            y_pred = estimator.predict(Xte)

            # ---- metrics ----
            try:
                from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("scikit-learn is required for train.single") from e

            acc = float(accuracy_score(y_test, y_pred))
            pos_label = _select_pos_label(cfg, y_test)
            prec = float(precision_score(y_test, y_pred, pos_label=pos_label, zero_division=0))
            rec = float(recall_score(y_test, y_pred, pos_label=pos_label, zero_division=0))
            f1 = float(f1_score(y_test, y_pred, pos_label=pos_label, zero_division=0))

            # ---- artifacts ----
            ctx.set_artifact("model.trained", estimator)

            # Params devem ser serializáveis.
            try:
                params = estimator.get_params(deep=False)
            except Exception:
                params = {}

            payload = {
                "model_id": model_id,
                "seed": seed,
                "params": _json_safe(params),
                "metrics": {
                    "accuracy": acc,
                    "precision": prec,
                    "recall": rec,
                    "f1": f1,
                },
            }

            ctx.log(
                step_id=self.id,
                level="info",
                message="train.single completed",
                model_id=model_id,
                seed=seed,
                accuracy=acc,
                precision=prec,
                recall=rec,
                f1=f1,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="train.single completed",
                metrics={
                    "accuracy": acc,
                    "precision": prec,
                    "recall": rec,
                    "f1": f1,
                },
                warnings=[],
                artifacts={
                    "model.trained": "model.trained",
                },
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="train.single failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "train.single failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["TrainSingleStep"]
