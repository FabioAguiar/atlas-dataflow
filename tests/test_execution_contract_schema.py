import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "execution-contract.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_contract() -> dict:
    """Minimal well-formed execution contract based on bank-marketing dataset structure."""
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "bank-marketing",
        "target_column": "y",
        "feature_columns": ["age", "job", "balance"],
        "ignored_columns": ["duration"],
        "required_columns": ["age", "job"],
        "optional_columns": ["balance"],
        "feature_definitions": {
            "age": {
                "type": "numeric",
                "domain_constraints": {"min": 17, "max": 98}
            },
            "job": {
                "type": "categorical",
                "domain_constraints": {"values": ["admin.", "blue-collar", "technician"]}
            },
            "balance": {
                "type": "numeric",
                "domain_constraints": {"min": -8000, "max": 100000}
            }
        },
        "missing_value_policy": {
            "age": "mean",
            "job": "mode",
            "balance": "median"
        },
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["log1p", "passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15
        },
        "random_seed": 42,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "pr_auc"],
        "modeling_constraints": {
            "allowed_model_families": ["logistic_regression", "gradient_boosting"],
            "no_automl": True,
            "max_training_time_seconds": 3600
        }
    }


def test_schema_is_well_formed():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)


def test_valid_execution_contract_passes():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    jsonschema.validate(contract, schema)


def test_missing_target_column_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    del contract["target_column"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for missing target_column"
    assert any("target_column" in error.message for error in errors)


def test_missing_contract_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    del contract["contract_version"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for missing contract_version"
    assert any("contract_version" in error.message for error in errors)


def test_missing_modeling_constraints_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    del contract["modeling_constraints"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for missing modeling_constraints"
    assert any("modeling_constraints" in error.message for error in errors)


def test_invalid_missing_value_policy_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["missing_value_policy"]["age"] = "unknown_policy"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for invalid missing_value_policy value"
    assert any("unknown_policy" in error.message for error in errors)


def test_invalid_primary_metric_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["primary_metric"] = "rmse"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for invalid primary_metric"
    assert any("rmse" in error.message for error in errors)


def test_additional_top_level_property_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["human_facing_description"] = "This unreviewed description must not be here"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for additional top-level property"
    assert any(
        "Additional properties are not allowed" in error.message
        or "human_facing_description" in error.message
        for error in errors
    )


def test_invalid_model_family_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["modeling_constraints"]["allowed_model_families"] = ["neural_network"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for disallowed model family"
    assert any("neural_network" in error.message for error in errors)


def test_wrong_contract_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["contract_version"] = "execution_contract.v2"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for wrong contract_version value"


def test_invalid_split_strategy_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["split_policy"]["strategy"] = "time_series"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for invalid split strategy"
    assert any("time_series" in error.message for error in errors)


def test_empty_allowed_model_families_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["modeling_constraints"]["allowed_model_families"] = []

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for empty allowed_model_families"


def test_null_random_seed_accepted():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["random_seed"] = None

    jsonschema.validate(contract, schema)


def test_empty_secondary_metrics_accepted():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["secondary_metrics"] = []

    jsonschema.validate(contract, schema)


def test_empty_ignored_columns_accepted():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["ignored_columns"] = []

    jsonschema.validate(contract, schema)
