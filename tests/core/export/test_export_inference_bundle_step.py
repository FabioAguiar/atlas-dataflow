from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.steps.export.inference_bundle import ExportInferenceBundleStep
from atlas_dataflow.deployment.inference_bundle import load_inference_bundle

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _minimal_contract_v1() -> dict:
    # contrato pequeno, porém compatível com Internal Contract v1
    return {
        "contract_version": "1.0",
        "problem": {"name": "synthetic", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "x",
                "role": "numerical",
                "dtype": "float",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "category",
                "role": "categorical",
                "dtype": "category",
                "required": True,
                "allowed_null": False,
            },
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }

def _minimal_config() -> dict:
    return {
        "engine": {"fail_fast": True},
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["x"], "scaler": None},
                "categorical": {
                    "columns": ["category"],
                    "encoder": "onehot",
                    "handle_unknown": "ignore",
                    "drop": None,
                },
            }
        },
        "steps": {
            "export.inference_bundle": {"enabled": True, "format": "joblib"},
        },
    }


def _fit_preprocess_and_model(run_dir: Path):
    import pandas as pd
    from sklearn.linear_model import LogisticRegression

    contract = _minimal_contract_v1()
    cfg = _minimal_config()

    preprocess = build_representation_preprocess(contract=contract, config=cfg)

    # dataset pequeno (determinístico)
    df = pd.DataFrame(
        [
            {"x": 1.0, "category": "A", "y": 0},
            {"x": 2.0, "category": "B", "y": 1},
            {"x": 3.0, "category": "A", "y": 1},
            {"x": 0.5, "category": "B", "y": 0},
        ]
    )
    X = df.drop(columns=["y"])
    y = df["y"]

    preprocess.fit(X)
    PreprocessStore(run_dir=run_dir).save(preprocess=preprocess)

    Xt = preprocess.transform(X)
    model = LogisticRegression(max_iter=200, random_state=42)
    model.fit(Xt, y)

    return contract, cfg, model


def test_export_inference_bundle_round_trip_and_predict(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    contract, cfg, model = _fit_preprocess_and_model(run_dir)

    # ctx com outputs necessários
    ctx = RunContext(
        run_id="t-run",
        created_at=datetime.now(timezone.utc),
        config=cfg,
        contract=contract,
        meta={"run_dir": run_dir},
    )

    # model (em memória)
    ctx.set_artifact("model.best_estimator", model)

    # metrics + model_selection (com model_id explícito)
    ctx.set_artifact(
        "eval.metrics",
        [
            {"model_id": "logistic_regression", "metrics": {"accuracy": 0.9, "f1": 0.8}},
        ],
    )
    ctx.set_artifact(
        "eval.model_selection",
        {
            "selection": {
                "metric": "f1",
                "direction": "maximize",
                "champion_model_id": "logistic_regression",
                "champion_score": 0.8,
                "ranking": [{"model_id": "logistic_regression", "score": 0.8}],
            }
        },
    )

    step = ExportInferenceBundleStep()
    result = step.run(ctx)
    assert result.status.value == "success"

    bundle_path = run_dir / "artifacts" / "inference_bundle.joblib"
    assert bundle_path.exists()

    bundle = load_inference_bundle(path=bundle_path)

    # predict ok (payload compatível)
    pred = bundle.predict({"x": 1.5, "category": "A"})
    assert len(pred) == 1

    # predict_proba deve existir para LogisticRegression
    proba = bundle.predict_proba({"x": 1.5, "category": "A"})
    assert len(proba) == 1


def test_export_inference_bundle_invalid_payload_fails(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    contract, cfg, model = _fit_preprocess_and_model(run_dir)

    ctx = RunContext(
        run_id="t-run",
        created_at=datetime.now(timezone.utc),
        config=cfg,
        contract=contract,
        meta={"run_dir": run_dir},
    )
    ctx.set_artifact("model.best_estimator", model)
    ctx.set_artifact(
        "eval.metrics",
        [
            {"model_id": "logistic_regression", "metrics": {"accuracy": 0.9, "f1": 0.8}},
        ],
    )
    ctx.set_artifact(
        "eval.model_selection",
        {
            "selection": {
                "metric": "f1",
                "direction": "maximize",
                "champion_model_id": "logistic_regression",
                "champion_score": 0.8,
                "ranking": [{"model_id": "logistic_regression", "score": 0.8}],
            }
        },
    )

    step = ExportInferenceBundleStep()
    res = step.run(ctx)
    assert res.status.value == "success"

    bundle_path = run_dir / "artifacts" / "inference_bundle.joblib"
    bundle = load_inference_bundle(path=bundle_path)

    # coluna faltante
    with pytest.raises(ValueError):
        bundle.predict({"x": 1.5})

    # coluna extra
    with pytest.raises(ValueError):
        bundle.predict({"x": 1.5, "category": "A", "extra": 1})

    # dtype incompatível (bool no lugar de float)
    with pytest.raises(ValueError):
        bundle.predict({"x": True, "category": "A"})