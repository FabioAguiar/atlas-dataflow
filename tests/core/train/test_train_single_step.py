from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.traceability.manifest import create_manifest, step_started, step_finished
from atlas_dataflow.persistence.preprocess_store import PreprocessStore
from atlas_dataflow.steps.train.single import TrainSingleStep


def _contract_minimal() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "demo", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "int", "required": True, "allowed_null": False},
            {"name": "income", "role": "numerical", "dtype": "float", "required": True, "allowed_null": False},
            {
                "name": "country",
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


def _config_minimal(*, model_id: str, seed: int) -> dict:
    return {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["age", "income"], "scaler": "standard"},
                "categorical": {"columns": ["country"], "encoder": "onehot", "handle_unknown": "ignore", "drop": None},
            }
        },
        "steps": {
            "train.single": {
                "enabled": True,
                "model_id": model_id,
                "seed": seed,
            }
        },
    }


def _dataset() -> pd.DataFrame:
    # Pequeno dataset binário determinístico
    return pd.DataFrame(
        {
            "age": [10, 20, 30, 40, 50, 60],
            "income": [100.0, 200.0, 150.0, 300.0, 120.0, 500.0],
            "country": ["BR", "US", "BR", "CA", "US", "BR"],
            "y": [0, 1, 0, 1, 0, 1],
        }
    )


def _mk_ctx(*, tmp_path, contract: dict, config: dict, train_rows, test_rows) -> RunContext:
    ctx = RunContext(
        run_id="r1",
        created_at=datetime.now(timezone.utc),
        config=config,
        contract=contract,
        meta={"tmp_path": tmp_path},
    )
    ctx.set_artifact("data.train", train_rows)
    ctx.set_artifact("data.test", test_rows)
    return ctx


def test_train_single_smoke_and_manifest_metrics(tmp_path):
    contract = _contract_minimal()
    config = _config_minimal(model_id="logistic_regression", seed=42)
    df = _dataset()

    # Persistimos preprocess (não fitado) para o Step consumir
    pre = build_representation_preprocess(contract=contract, config=config)
    PreprocessStore(run_dir=tmp_path).save(preprocess=pre, manifest=None)

    train_rows = df.iloc[:4].to_dict(orient="records")
    test_rows = df.iloc[4:].to_dict(orient="records")
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSingleStep()
    result = step.run(ctx)

    assert result.status.value == "success"
    assert "accuracy" in result.metrics
    assert "f1" in result.metrics
    assert ctx.has_artifact("model.trained")

    # Manifest: métricas precisam estar registradas via StepResult
    manifest = create_manifest(
        run_id=ctx.run_id,
        started_at=ctx.created_at,
        atlas_version="0.0",
        config_hash="",
        contract_hash="",
    )
    step_started(manifest, step_id=step.id, kind=result.kind.value, ts=datetime.now(timezone.utc))
    step_finished(manifest, step_id=step.id, ts=datetime.now(timezone.utc), result=result)

    assert step.id in manifest.steps
    assert "metrics" in manifest.steps[step.id]
    assert "accuracy" in manifest.steps[step.id]["metrics"]


def test_train_single_is_deterministic_with_fixed_seed(tmp_path):
    contract = _contract_minimal()
    config = _config_minimal(model_id="random_forest", seed=123)
    df = _dataset()

    pre = build_representation_preprocess(contract=contract, config=config)
    PreprocessStore(run_dir=tmp_path).save(preprocess=pre, manifest=None)

    train_rows = df.iloc[:4].to_dict(orient="records")
    test_rows = df.iloc[4:].to_dict(orient="records")

    ctx1 = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)
    ctx2 = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSingleStep()
    r1 = step.run(ctx1)
    r2 = step.run(ctx2)

    assert r1.status.value == "success"
    assert r2.status.value == "success"
    assert r1.metrics == r2.metrics


def test_train_single_fails_for_invalid_model_id(tmp_path):
    contract = _contract_minimal()
    config = _config_minimal(model_id="not_a_model", seed=1)
    df = _dataset()

    pre = build_representation_preprocess(contract=contract, config=config)
    PreprocessStore(run_dir=tmp_path).save(preprocess=pre, manifest=None)

    train_rows = df.iloc[:4].to_dict(orient="records")
    test_rows = df.iloc[4:].to_dict(orient="records")
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSingleStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "unknown model_id" in (result.summary or "") or "unknown" in (result.summary or "")


def test_train_single_with_string_labels(tmp_path):
    """Regression: CSV ingest produces string labels ('0'/'1'); train.single must not fail on metrics."""
    from atlas_dataflow.core.pipeline.context import RunContext
    from atlas_dataflow.steps.train.single import TrainSingleStep
    from atlas_dataflow.persistence.preprocess_store import PreprocessStore

    # Minimal config
    cfg = {
        "steps": {
            "train.single": {"enabled": True, "model_id": "logistic_regression", "seed": 42},
        }
    }
    contract = {
        "target": {"name": "churn"},
    }
    ctx = RunContext(
        run_id="t1",
        created_at="2020-01-01T00:00:00Z",
        config=cfg,
        contract=contract,
        meta={"run_dir": str(tmp_path)},
    )

    # Minimal preprocess persisted (identity-like) using representation.preprocess builder API
    # Use the same builder the project exposes to avoid inventing objects.
    from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess

    cfg_rep = {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["tenure", "monthly_charges"], "scaler": "standard"},
                "categorical": {"columns": ["contract_type"], "encoder": "onehot", "handle_unknown": "ignore"},
            }
        }
    }
    # merge into ctx.config for builder
    ctx.config.update(cfg_rep)

    preprocess = build_representation_preprocess(
        contract={
            "target": {"name": "churn"},
            "features": [
                {"name": "tenure", "role": "numerical"},
                {"name": "monthly_charges", "role": "numerical"},
                {"name": "contract_type", "role": "categorical"},
            ],
        },
        config=ctx.config,
    )
    PreprocessStore(run_dir=str(tmp_path)).save(preprocess=preprocess)

    # Provide artifacts expected by train.single (already split)
    ctx.set_artifact(
        "data.train",
        [
            {"tenure": 1, "monthly_charges": 51.0, "contract_type": "a", "churn": "0"},
            {"tenure": 2, "monthly_charges": 52.0, "contract_type": "b", "churn": "1"},
            {"tenure": 3, "monthly_charges": 53.0, "contract_type": "a", "churn": "0"},
            {"tenure": 4, "monthly_charges": 54.0, "contract_type": "b", "churn": "1"},
        ],
    )
    ctx.set_artifact(
        "data.test",
        [
            {"tenure": 5, "monthly_charges": 55.0, "contract_type": "a", "churn": "0"},
            {"tenure": 6, "monthly_charges": 56.0, "contract_type": "b", "churn": "1"},
        ],
    )

    sr = TrainSingleStep().run(ctx)
    assert sr.status.value == "success", sr.summary
