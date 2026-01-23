from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.persistence.preprocess_store import PreprocessStore
from atlas_dataflow.steps.train.search import TrainSearchStep


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


def _dataset(n: int = 30) -> pd.DataFrame:
    # Dataset maior para suportar CV default (n_splits=5) com estratificação.
    ages = list(range(10, 10 + n))
    income = [float(100 + (i * 7) % 250) for i in range(n)]
    countries = ["BR", "US", "CA"]
    country = [countries[i % len(countries)] for i in range(n)]
    y = [i % 2 for i in range(n)]  # 0/1 balanceado

    return pd.DataFrame({"age": ages, "income": income, "country": country, "y": y})


def _split_train_test(df: pd.DataFrame, train_size: int = 24) -> tuple[list[dict], list[dict]]:
    assert train_size < len(df)
    train_rows = df.iloc[:train_size].to_dict(orient="records")
    test_rows = df.iloc[train_size:].to_dict(orient="records")
    return train_rows, test_rows


def _config_base(*, seed: int) -> dict:
    return {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["age", "income"], "scaler": "standard"},
                "categorical": {"columns": ["country"], "encoder": "onehot", "handle_unknown": "ignore", "drop": None},
            }
        },
        "steps": {"train.search": {"enabled": True, "seed": seed}},
    }


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


def _persist_preprocess(*, tmp_path, contract: dict, config: dict) -> None:
    pre = build_representation_preprocess(contract=contract, config=config)
    PreprocessStore(run_dir=tmp_path).save(preprocess=pre, manifest=None)


def test_train_search_grid_default_smoke(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    config = _config_base(seed=42)
    config["steps"]["train.search"].update(
        {"model_id": "logistic_regression", "search_type": "grid", "grid_source": "default"}
    )

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert result.payload["model_id"] == "logistic_regression"
    assert result.payload["search_type"] == "grid"
    assert result.payload["grid_source"] == "default"
    assert "best_params" in result.payload
    assert "best_score" in result.payload
    assert "cv_results" in result.payload
    assert isinstance(result.payload["cv_results"], list)
    assert len(result.payload["cv_results"]) > 0
    assert ctx.has_artifact("model.best_estimator")


def test_train_search_is_deterministic_with_fixed_seed(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    config = _config_base(seed=123)
    config["steps"]["train.search"].update(
        {"model_id": "random_forest", "search_type": "random", "grid_source": "default", "n_iter": 5}
    )

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)

    ctx1 = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)
    ctx2 = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    r1 = step.run(ctx1)
    r2 = step.run(ctx2)

    assert r1.status.value == "success", r1.summary
    assert r2.status.value == "success", r2.summary
    assert r1.payload["best_params"] == r2.payload["best_params"]
    assert r1.payload["best_score"] == r2.payload["best_score"]


def test_train_search_grid_via_paste(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    config = _config_base(seed=7)
    config["steps"]["train.search"].update(
        {
            "model_id": "knn",
            "search_type": "grid",
            "grid_source": "paste",
            "grid_paste": {"n_neighbors": [3, 5], "weights": ["uniform", "distance"]},
        }
    )

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert result.payload["grid_source"] == "paste"
    assert ctx.has_artifact("model.best_estimator")


def test_train_search_grid_via_bank(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    # GridBank: root_dir explícito, sem descoberta automática.
    bank_root = Path(tmp_path) / "grids"
    model_id = "random_forest"
    (bank_root / model_id).mkdir(parents=True, exist_ok=True)

    grid_name = "rf_small_v1.yaml"
    grid_path = bank_root / model_id / grid_name
    grid_obj = {"n_estimators": [10, 20], "max_depth": [None, 5]}
    grid_path.write_text(yaml.safe_dump(grid_obj, sort_keys=True), encoding="utf-8")

    config = _config_base(seed=42)
    config["steps"]["train.search"].update(
        {
            "model_id": model_id,
            "search_type": "grid",
            "grid_source": "bank",
            "grid_bank": {"root_dir": str(bank_root), "grid_name": grid_name},
        }
    )

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert result.payload["grid_source"] == "bank"
    assert ctx.has_artifact("model.best_estimator")


def test_train_search_fails_for_invalid_model_id(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    config = _config_base(seed=1)
    config["steps"]["train.search"].update({"model_id": "not_a_model", "search_type": "grid", "grid_source": "default"})

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "unknown" in (result.summary or "").lower() or "model" in (result.summary or "").lower()


def test_train_search_fails_for_invalid_grid_param(tmp_path):
    contract = _contract_minimal()
    df = _dataset()

    config = _config_base(seed=2)
    config["steps"]["train.search"].update(
        {
            "model_id": "logistic_regression",
            "search_type": "grid",
            "grid_source": "paste",
            "grid_paste": {"param_inexistente": [1, 2]},
        }
    )

    _persist_preprocess(tmp_path=tmp_path, contract=contract, config=config)

    train_rows, test_rows = _split_train_test(df)
    ctx = _mk_ctx(tmp_path=tmp_path, contract=contract, config=config, train_rows=train_rows, test_rows=test_rows)

    step = TrainSearchStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "grid param" in (result.summary or "").lower() or "param" in (result.summary or "").lower()
