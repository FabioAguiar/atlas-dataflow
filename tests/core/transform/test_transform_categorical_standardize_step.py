from __future__ import annotations

import copy

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.transform.categorical_standardize import (
    TransformCategoricalStandardizeStep,
)


def test_categorical_standardize_applies_mappings_and_casing_internal_contract(dummy_ctx):
    # Internal Contract v1 format: categories.normalization
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [{"name": "country", "role": "categorical", "dtype": "string", "required": True, "allowed_null": True}],
        "categories": {
            "country": {
                "allowed": ["BR", "US"],
                "normalization": {
                    "type": "map",
                    "mapping": {"brasil": "BR", "brazil": "BR"},
                },
            }
        },
    }

    rows = [{"country": "brasil", "y": 0}, {"country": "US", "y": 1}, {"country": "canada", "y": 0}]
    original = copy.deepcopy(rows)
    dummy_ctx.set_artifact("data.raw_rows", rows)

    step = TransformCategoricalStandardizeStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    out = dummy_ctx.get_artifact("data.raw_rows")
    assert out[0]["country"] == "BR"
    assert out[1]["country"] == "US"
    # "canada" não está em allowed -> deve aparecer como nova categoria
    assert "canada" in result.payload["impact"]["new_categories"]["country"]

    # auditoria
    impact = result.payload["impact"]
    assert "country" in impact["columns_affected"]
    assert "country" in impact["mappings_applied"]
    assert any(x["from"] == "brasil" and x["to"] == "BR" for x in impact["mappings_applied"]["country"])

    # não muta input list original por referência
    assert rows == original


def test_categorical_standardize_no_rules_is_noop_with_audit(dummy_ctx):
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [{"name": "country", "role": "categorical", "dtype": "string", "required": True, "allowed_null": True}],
        # sem categories e sem categorical_standardization
    }

    rows = [{"country": "brasil", "y": 0}]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    step = TransformCategoricalStandardizeStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    assert result.payload["impact"]["columns_affected"] == []
    assert "note" in result.payload["impact"]
    assert dummy_ctx.get_artifact("data.raw_rows") == rows


def test_categorical_standardize_fails_when_declared_column_missing(dummy_ctx):
    dummy_ctx.contract = {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [{"name": "country", "role": "categorical", "dtype": "string", "required": True, "allowed_null": True}],
        "categories": {"country": {"allowed": ["BR"], "normalization": {"type": "map", "mapping": {"brasil": "BR"}}}},
    }

    dummy_ctx.set_artifact("data.raw_rows", [{"x": 1, "y": 0}])  # sem country

    step = TransformCategoricalStandardizeStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "not found" in (result.summary or "").lower()


def test_categorical_standardize_applies_to_train_and_test_when_present(dummy_ctx):
    # Legacy format fallback
    dummy_ctx.contract = {
        "categorical_standardization": {
            "platform": {
                "casing": "upper",
                "mappings": {"ps5": "PS5"},
            }
        }
    }

    train = [{"platform": "ps5", "y": 1}, {"platform": "pc", "y": 0}]
    test = [{"platform": "ps5", "y": 0}]
    dummy_ctx.set_artifact("data.train", copy.deepcopy(train))
    dummy_ctx.set_artifact("data.test", copy.deepcopy(test))

    step = TransformCategoricalStandardizeStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    assert dummy_ctx.get_artifact("data.train")[0]["platform"] == "PS5"
    assert dummy_ctx.get_artifact("data.test")[0]["platform"] == "PS5"


def test_categorical_standardize_missing_artifact_fails(dummy_ctx):
    dummy_ctx.contract = {
        "categorical_standardization": {
            "country": {"casing": "upper", "mappings": {"brasil": "BR"}}
        }
    }
    step = TransformCategoricalStandardizeStep()
    result = step.run(dummy_ctx)
    assert result.status == StepStatus.FAILED
    assert "data.raw_rows" in (result.summary or "")
