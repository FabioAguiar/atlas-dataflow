"""Step canônico: evaluate.metrics (v1).

Avaliação padronizada e rastreável de um modelo treinado.

Responsabilidades (M5):
- Consumir um modelo treinado produzido por:
  - train.single  -> artifact: model.trained
  - train.search  -> artifact: model.best_estimator
- Consumir dados de avaliação (data.test) do RunContext.
- Carregar o preprocess persistido (PreprocessStore) e aplicá-lo somente para
  transformar X (não recalcula / não altera preprocess).
- Calcular métricas padronizadas:
  - accuracy, precision, recall, f1 (sempre)
  - roc_auc (apenas quando aplicável: classificação binária + score/probabilidade)
- Gerar confusion matrix completa em formato serializável.
- Produzir StepResult com payload estável e serializável.

Princípios do Atlas:
- Avaliação é um Step explícito (não efeito colateral do treino).
- Sem inferência silenciosa de métricas adicionais.
- Sem treino ou retreino; sem recálculo de preprocess.
- Estruturas determinísticas e serializáveis.

Config esperada (exemplo):

steps:
  evaluate.metrics:
    enabled: true

Artifacts esperados (entrada):
- data.test: list[dict]
- preprocess.joblib persistido no run_dir (ctx.meta[run_dir]/artifacts/preprocess.joblib)
- modelo treinado em memória no RunContext:
  - model.best_estimator (preferencial, se existir)
  - model.trained (fallback)

Artifacts produzidos (saída):
- eval.metrics: payload serializável com métricas + confusion matrix

Referências:
- docs/spec/evaluate.metrics.v1.md
- docs/traceability.md
- docs/manifest.schema.v1.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _get_run_dir(ctx: RunContext) -> str:
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    run_dir = md.get("run_dir") or md.get("tmp_path")
    if run_dir is None:
        raise ValueError("Missing required meta: run_dir (or tmp_path)")
    return str(run_dir)


def _require_test_rows(ctx: RunContext) -> List[Dict[str, Any]]:
    if not ctx.has_artifact("data.test"):
        raise ValueError("Missing required artifact: data.test")
    test_rows = ctx.get_artifact("data.test")
    if not isinstance(test_rows, list) or not all(isinstance(r, dict) for r in test_rows):
        raise ValueError("Invalid artifact: data.test must be a list[dict]")
    return test_rows


def _require_model(ctx: RunContext) -> Tuple[str, Any]:
    """Retorna (artifact_key, model). Prefere best_estimator quando disponível."""
    if ctx.has_artifact("model.best_estimator"):
        return "model.best_estimator", ctx.get_artifact("model.best_estimator")
    if ctx.has_artifact("model.trained"):
        return "model.trained", ctx.get_artifact("model.trained")
    raise ValueError("Missing required model artifact: model.best_estimator or model.trained")


def _json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    return str(obj)


def _target_col_from_contract(contract: Dict[str, Any]) -> str:
    target = contract.get("target") if isinstance(contract, dict) else None
    if not isinstance(target, dict):
        raise ValueError("Invalid contract: target must be a mapping")
    name = target.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Invalid contract: target.name is required")
    return name.strip()


def _binary_roc_auc_if_applicable(estimator: Any, Xte: Any, y_true: Any) -> Optional[float]:
    """Calcula ROC AUC apenas quando aplicável (binário + score/prob)."""
    try:
        import numpy as np  # type: ignore
        from sklearn.metrics import roc_auc_score  # type: ignore
    except Exception:  # pragma: no cover
        return None

    # Precisamos de exatamente 2 classes.
    try:
        classes = np.unique(y_true)
    except Exception:
        return None
    if getattr(classes, "shape", None) is None or len(classes) != 2:
        return None

    y_score = None

    # Preferencial: predict_proba -> prob da classe positiva (classes_[1])
    if hasattr(estimator, "predict_proba"):
        try:
            proba = estimator.predict_proba(Xte)
            # proba: (n, 2)
            if hasattr(estimator, "classes_") and len(getattr(estimator, "classes_", [])) == 2:
                # índice da classe positiva (segunda na ordem classes_)
                pos_idx = 1
                y_score = proba[:, pos_idx]
            else:
                # fallback: assume coluna 1 como positiva
                y_score = proba[:, 1] if getattr(proba, "ndim", 0) == 2 and proba.shape[1] >= 2 else None
        except Exception:
            y_score = None

    # Alternativa: decision_function
    if y_score is None and hasattr(estimator, "decision_function"):
        try:
            scores = estimator.decision_function(Xte)
            # scores pode ser (n,) no binário
            y_score = scores
        except Exception:
            y_score = None

    if y_score is None:
        return None

    try:
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return None


@dataclass
class EvaluateMetricsStep(Step):
    """Avaliação padronizada (métricas + confusion matrix)."""

    id: str = "evaluate.metrics"
    kind: StepKind = StepKind.EVALUATE
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # Semântica: requer treino concluído antes.
            self.depends_on = [
                "train.single",
            ]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            if cfg.get("enabled") is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="evaluate.metrics skipped (disabled in config)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"skipped": True},
                )

            # ---- inputs ----
            test_rows = _require_test_rows(ctx)
            run_dir = _get_run_dir(ctx)
            contract = ctx.contract or {}
            target_col = _target_col_from_contract(contract)

            model_key, estimator = _require_model(ctx)

            # ---- pandas ----
            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for evaluate.metrics") from e

            df_test = pd.DataFrame(test_rows)
            if target_col not in df_test.columns:
                raise ValueError(f"Target column not found in test data: {target_col}")

            y_true = df_test[target_col]
            X_test = df_test.drop(columns=[target_col])

            # ---- preprocess ----
            preprocess = PreprocessStore(run_dir=run_dir).load()
            Xte = preprocess.transform(X_test)

            # ---- predictions ----
            if not hasattr(estimator, "predict"):
                raise ValueError("Invalid model: estimator has no predict()")

            y_pred = estimator.predict(Xte)

            # ---- metrics ----
            try:
                from sklearn.metrics import (
                    accuracy_score,
                    precision_score,
                    recall_score,
                    f1_score,
                    confusion_matrix,
                )  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("scikit-learn is required for evaluate.metrics") from e

            acc = float(accuracy_score(y_true, y_pred))
            prec = float(precision_score(y_true, y_pred, zero_division=0))
            rec = float(recall_score(y_true, y_pred, zero_division=0))
            f1 = float(f1_score(y_true, y_pred, zero_division=0))

            # labels explícitos e estáveis
            try:
                import numpy as np  # type: ignore
                labels_arr = np.unique(y_true)
                labels = [ _json_safe(x) for x in labels_arr.tolist() ]
            except Exception:
                labels = sorted(set([str(x) for x in list(y_true)]))

            cm = confusion_matrix(y_true, y_pred, labels=labels)
            cm_serializable = [[int(x) for x in row] for row in cm.tolist()]

            roc_auc = _binary_roc_auc_if_applicable(estimator, Xte, y_true)

            metrics: Dict[str, Any] = {
                "accuracy": acc,
                "precision": prec,
                "recall": rec,
                "f1": f1,
            }
            if roc_auc is not None:
                metrics["roc_auc"] = roc_auc

            payload: Dict[str, Any] = {
                "model_artifact": model_key,
                "metrics": metrics,
                "confusion_matrix": {
                    "labels": labels,
                    "matrix": cm_serializable,
                },
            }

            ctx.set_artifact("eval.metrics", payload)

            ctx.log(
                step_id=self.id,
                level="info",
                message="evaluate.metrics completed",
                model_artifact=model_key,
                accuracy=acc,
                precision=prec,
                recall=rec,
                f1=f1,
                roc_auc=roc_auc,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="evaluate.metrics completed",
                metrics=metrics,
                warnings=[],
                artifacts={"eval.metrics": "eval.metrics"},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="evaluate.metrics failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "evaluate.metrics failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["EvaluateMetricsStep"]
