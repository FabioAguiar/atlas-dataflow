from __future__ import annotations

import copy

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.transform.impute_missing import TransformImputeMissingStep


def _contract_with_imputation() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "float", "required": True, "allowed_null": True},
            {"name": "country", "role": "categorical", "dtype": "string", "required": False, "allowed_null": True},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {
            "age": {"strategy": "median", "mandatory": True},
            "country": {"strategy": "most_frequent", "mandatory": False},
        },
    }


def test_impute_missing_numeric_and_categorical(dummy_ctx):
    dummy_ctx.contract = _contract_with_imputation()

    rows = [
        {"age": 10.0, "country": "BR", "y": 0},
        {"age": None, "country": "BR", "y": 1},
        {"age": 30.0, "country": None, "y": 0},
    ]
    original = copy.deepcopy(rows)
    dummy_ctx.set_artifact("data.raw_rows", rows)

    step = TransformImputeMissingStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    out = dummy_ctx.get_artifact("data.raw_rows")

    # age median of [10, 30] -> 20
    assert out[1]["age"] == 20.0
    # country most frequent -> BR
    assert out[2]["country"] == "BR"

    impact = result.payload["impact"]
    assert set(impact["columns_affected"]) == {"age", "country"}
    assert impact["strategy_by_column"]["age"] == "median"
    assert impact["strategy_by_column"]["country"] == "most_frequent"
    assert impact["values_imputed"]["age"] == 1
    assert impact["values_imputed"]["country"] == 1

    # não muta lista original por referência
    assert rows == original


def test_impute_missing_constant_strategy(dummy_ctx):
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "segment", "role": "categorical", "dtype": "string", "required": False, "allowed_null": True},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {
            "segment": {"strategy": "constant", "mandatory": False, "value": "UNKNOWN"},
        },
    }
    dummy_ctx.set_artifact("data.raw_rows", [{"segment": None, "y": 0}])

    result = TransformImputeMissingStep().run(dummy_ctx)
    assert result.status == StepStatus.SUCCESS
    assert dummy_ctx.get_artifact("data.raw_rows")[0]["segment"] == "UNKNOWN"


def test_impute_missing_fails_when_mandatory_remains_missing(dummy_ctx):
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "float", "required": True, "allowed_null": True},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {
            "age": {"strategy": "mean", "mandatory": True},
        },
    }

    # todos os valores são missing -> não há como calcular mean
    dummy_ctx.set_artifact("data.raw_rows", [{"age": None, "y": 0}, {"age": None, "y": 1}])

    result = TransformImputeMissingStep().run(dummy_ctx)
    assert result.status == StepStatus.FAILED
    assert "mandatory" in (result.summary or "").lower()


def test_impute_missing_no_rules_is_noop_with_audit(dummy_ctx):
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "float", "required": True, "allowed_null": True},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }
    rows = [{"age": None, "y": 0}]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    result = TransformImputeMissingStep().run(dummy_ctx)
    assert result.status == StepStatus.SUCCESS
    assert result.payload["impact"]["columns_affected"] == []
    assert "note" in result.payload["impact"]
    assert dummy_ctx.get_artifact("data.raw_rows") == rows


def test_impute_missing_applies_to_train_and_test_when_present(dummy_ctx):
    dummy_ctx.contract = _contract_with_imputation()
    train = [{"age": None, "country": "BR", "y": 1}, {"age": 10.0, "country": "BR", "y": 0}]
    test = [{"age": None, "country": "BR", "y": 0}, {"age": 30.0, "country": "BR", "y": 1}]

    dummy_ctx.set_artifact("data.train", copy.deepcopy(train))
    dummy_ctx.set_artifact("data.test", copy.deepcopy(test))

    result = TransformImputeMissingStep().run(dummy_ctx)
    assert result.status == StepStatus.SUCCESS

    # median of [10] in train -> 10; median of [30] in test -> 30
    assert dummy_ctx.get_artifact("data.train")[0]["age"] == 10.0
    assert dummy_ctx.get_artifact("data.test")[0]["age"] == 30.0


def test_impute_missing_missing_artifact_fails(dummy_ctx):
    dummy_ctx.contract = _contract_with_imputation()
    result = TransformImputeMissingStep().run(dummy_ctx)
    assert result.status == StepStatus.FAILED
    assert "data.raw_rows" in (result.summary or "")
