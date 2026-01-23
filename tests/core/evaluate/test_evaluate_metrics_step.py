from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.persistence.preprocess_store import PreprocessStore
from atlas_dataflow.steps.evaluate.metrics import EvaluateMetricsStep


def _contract_minimal() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "demo", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "int", "required": True, "allowed_null": False},
            {"name": "income", "role": "numerical", "dtype": "float", "required": True, "allowed_null": False},
            {"name": "country", "role": "categorical", "dtype": "category", "required": True, "allowed_null": False},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }


def _config_base() -> dict:
    return {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["age", "income"], "scaler": "standard"},
                "categorical": {"columns": ["country"], "encoder": "onehot", "handle_unknown": "ignore", "drop": None},
            }
        },
        "steps": {"evaluate.metrics": {"enabled": True}},
    }


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [10, 12, 14, 16, 20, 22, 24, 26, 30, 32, 34, 36],
            "income": [100.0, 110.0, 120.0, 130.0, 200.0, 210.0, 220.0, 230.0, 150.0, 160.0, 170.0, 180.0],
            "country": ["BR", "BR", "US", "US", "BR", "US", "BR", "US", "BR", "US", "BR", "US"],
            "y": [0, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        }
    )


def _split_train_test(df: pd.DataFrame):
    train_df = df.iloc[:8].reset_index(drop=True)
    test_df = df.iloc[8:].reset_index(drop=True)
    return train_df, test_df


def _persist_fitted_preprocess(*, tmp_path, contract: dict, config: dict, train_df: pd.DataFrame) -> None:
    pre = build_representation_preprocess(contract=contract, config=config)
    target = contract["target"]["name"]
    X_train = train_df.drop(columns=[target])

    # Fit explícito antes de persistir.
    pre.fit(X_train)
    PreprocessStore(run_dir=tmp_path).save(preprocess=pre, manifest=None)


def _fit_model_with_preprocess(*, tmp_path, contract: dict, train_df: pd.DataFrame) -> LogisticRegression:
    target = contract["target"]["name"]
    X_train = train_df.drop(columns=[target])
    y_train = train_df[target]

    pre = PreprocessStore(run_dir=tmp_path).load()
    Xtr = pre.transform(X_train)

    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(Xtr, y_train)
    return model


def _mk_ctx(*, tmp_path, contract: dict, config: dict, model, train_df: pd.DataFrame, test_df: pd.DataFrame) -> RunContext:
    ctx = RunContext(
        run_id="r-eval-1",
        created_at=datetime.now(timezone.utc),
        config=config,
        contract=contract,
        meta={"tmp_path": tmp_path},
    )

    ctx.set_artifact("data.test", test_df.to_dict(orient="records"))
    ctx.set_artifact("data.train", train_df.to_dict(orient="records"))
    ctx.set_artifact("model.best_estimator", model)
    return ctx


def test_evaluate_metrics_basic_and_payload_shape(tmp_path):
    contract = _contract_minimal()
    config = _config_base()
    df = _dataset()
    train_df, test_df = _split_train_test(df)

    _persist_fitted_preprocess(tmp_path=tmp_path, contract=contract, config=config, train_df=train_df)
    model = _fit_model_with_preprocess(tmp_path=tmp_path, contract=contract, train_df=train_df)

    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, model=model, train_df=train_df, test_df=test_df)

    step = EvaluateMetricsStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    payload = result.payload

    assert payload["model_artifact"] in ("model.best_estimator", "model.trained")
    assert "metrics" in payload
    for k in ["accuracy", "precision", "recall", "f1"]:
        assert k in payload["metrics"]

    assert "confusion_matrix" in payload
    assert "labels" in payload["confusion_matrix"]
    assert "matrix" in payload["confusion_matrix"]
    assert isinstance(payload["confusion_matrix"]["matrix"], list)

    assert ctx.has_artifact("eval.metrics")


def test_evaluate_metrics_includes_roc_auc_when_applicable(tmp_path):
    contract = _contract_minimal()
    config = _config_base()
    df = _dataset()
    train_df, test_df = _split_train_test(df)

    _persist_fitted_preprocess(tmp_path=tmp_path, contract=contract, config=config, train_df=train_df)
    model = _fit_model_with_preprocess(tmp_path=tmp_path, contract=contract, train_df=train_df)

    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, model=model, train_df=train_df, test_df=test_df)

    step = EvaluateMetricsStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert "roc_auc" in result.payload["metrics"]


def test_evaluate_metrics_omits_roc_auc_when_not_available(tmp_path):
    class NoScoreModel:
        def predict(self, X):
            n = getattr(X, "shape", (len(X),))[0]
            return [0] * n

    contract = _contract_minimal()
    config = _config_base()
    df = _dataset()
    train_df, test_df = _split_train_test(df)

    _persist_fitted_preprocess(tmp_path=tmp_path, contract=contract, config=config, train_df=train_df)

    ctx = _mk_ctx(
        tmp_path=tmp_path,
        contract=contract,
        config=config,
        model=NoScoreModel(),
        train_df=train_df,
        test_df=test_df,
    )

    step = EvaluateMetricsStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert "roc_auc" not in result.payload["metrics"]


def test_evaluate_metrics_fails_without_model(tmp_path):
    contract = _contract_minimal()
    config = _config_base()
    df = _dataset()
    train_df, test_df = _split_train_test(df)

    _persist_fitted_preprocess(tmp_path=tmp_path, contract=contract, config=config, train_df=train_df)

    ctx = RunContext(
        run_id="r-eval-2",
        created_at=datetime.now(timezone.utc),
        config=config,
        contract=contract,
        meta={"tmp_path": tmp_path},
    )
    ctx.set_artifact("data.test", test_df.to_dict(orient="records"))

    step = EvaluateMetricsStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
