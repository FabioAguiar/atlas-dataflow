import copy
import json
import math
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.contract_derivation import (
    _build_execution_contract,
    _unresolved_review_columns,
    _validate_categorical_domain_declaration,
    materialize_execution_contract,
)

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "execution-contract.schema.json"
TELCO_EXECUTION_CONTRACT_PATH = (
    REPO_ROOT / "contracts" / "telco-customer-churn" / "execution-contract.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_error_messages(errors) -> list[str]:
    """Flatten top-level jsonschema error messages together with every
    nested sub-error message from a oneOf branch's own context (Project
    Spec S0243: the schema's top level is now a v1/v2 oneOf, so a single
    missing-field failure surfaces as one top-level "not valid under any of
    the given schemas" error whose per-branch detail lives in
    error.context, not in error.message itself)."""
    messages = []
    for error in errors:
        messages.append(error.message)
        for sub_error in getattr(error, "context", None) or []:
            messages.extend(_all_error_messages([sub_error]))
    return messages


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
    assert any("target_column" in message for message in _all_error_messages(errors))


def test_missing_contract_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    del contract["contract_version"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for missing contract_version"
    assert any("contract_version" in message for message in _all_error_messages(errors))


def test_missing_modeling_constraints_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    del contract["modeling_constraints"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for missing modeling_constraints"
    assert any("modeling_constraints" in message for message in _all_error_messages(errors))


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
    contract["primary_metric"] = "not_a_real_metric"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))

    assert errors, "Expected validation error for invalid primary_metric"
    assert any("not_a_real_metric" in error.message for error in errors)


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


# ---------------------------------------------------------------------------
# result_semantics closed binary/multiclass union (Project Spec S0207)
#
# Direct contract-level JSON-Schema coverage for the S0207 union, plus one
# fixture materialized through the real dispatcher (mirrors
# tests/test_contract_derivation.py's own coverage, checked here at the raw
# schema level since this module owns contracts/execution-contract.schema.json
# directly).
# ---------------------------------------------------------------------------


def _valid_binary_result_semantics() -> dict:
    return {
        "schema_version": "binary-result-semantics.v1",
        "problem_type": "binary_classification",
        "positive_class": {"class_id": "Yes", "event_label": "Churn"},
        "primary_output": "positive_class_probability",
        "decision": {"threshold": 0.5},
        "interpretation": {
            "preset": "risk",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
    }


def _valid_multiclass_result_semantics() -> dict:
    return {
        "schema_version": "multiclass-result-semantics.v1",
        "problem_type": "multiclass_classification",
        "classes": [
            {"class_id": "low_risk", "display_label": "Low Risk"},
            {"class_id": "medium_risk", "display_label": "Medium Risk"},
            {"class_id": "high_risk", "display_label": "High Risk"},
        ],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
    }


def test_existing_binary_result_semantics_still_validate():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["result_semantics"] = _valid_binary_result_semantics()
    jsonschema.validate(contract, schema)


def test_valid_multiclass_result_semantics_validate():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["result_semantics"] = _valid_multiclass_result_semantics()
    jsonschema.validate(contract, schema)


def test_multiclass_classes_require_at_least_three_entries():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["classes"] = result_semantics["classes"][:2]
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_class_entries_reject_extra_properties():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["classes"][0]["extra_field"] = "not allowed"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_positive_class_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["positive_class"] = {"class_id": "Yes", "event_label": "Churn"}
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_threshold_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["decision"] = {"strategy": "argmax", "threshold": 0.5}
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_interpretation_risk_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["interpretation"] = _valid_binary_result_semantics()["interpretation"]
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_wrong_primary_output_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["primary_output"] = "positive_class_probability"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_wrong_probability_output_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["probability_output"] = "positive_class_probability"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_multiclass_non_argmax_decision_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_multiclass_result_semantics()
    result_semantics["decision"] = {"strategy": "max_probability"}
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_binary_contract_containing_multiclass_only_fields_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_binary_result_semantics()
    result_semantics["classes"] = _valid_multiclass_result_semantics()["classes"]
    result_semantics["probability_output"] = "class_probabilities"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def _valid_continuous_regression_result_semantics() -> dict:
    return {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
    }


def test_valid_continuous_regression_result_semantics_validate():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["result_semantics"] = _valid_continuous_regression_result_semantics()
    jsonschema.validate(contract, schema)


def test_continuous_regression_extra_properties_are_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["unit"] = "MPa"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_positive_class_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["positive_class"] = {"class_id": "Yes", "event_label": "Churn"}
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_classes_are_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["classes"] = _valid_multiclass_result_semantics()["classes"]
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_probability_output_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["probability_output"] = "class_probabilities"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_threshold_decision_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["decision"] = {"threshold": 0.5}
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_interpretation_risk_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["interpretation"] = _valid_binary_result_semantics()["interpretation"]
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_wrong_primary_output_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["primary_output"] = "predicted_class"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_wrong_output_value_kind_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["output_value_kind"] = "categorical"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_wrong_problem_type_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["problem_type"] = "multiclass_classification"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_continuous_regression_wrong_schema_version_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    result_semantics = _valid_continuous_regression_result_semantics()
    result_semantics["schema_version"] = "continuous-regression-result-semantics.v2"
    contract["result_semantics"] = result_semantics

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_r2_is_accepted_as_a_metric_identifier():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["primary_metric"] = "r2"
    jsonschema.validate(contract, schema)


def test_mae_is_accepted_as_a_metric_identifier():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["secondary_metrics"] = ["mae"]
    jsonschema.validate(contract, schema)


def test_rmse_is_accepted_as_a_metric_identifier():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["secondary_metrics"] = ["rmse"]
    jsonschema.validate(contract, schema)


def test_legacy_metric_identifiers_remain_accepted():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["primary_metric"] = "roc_auc"
    contract["secondary_metrics"] = ["f1", "pr_auc", "f1_macro", "precision_macro"]
    jsonschema.validate(contract, schema)


def _synthetic_multiclass_modeling_intent() -> dict:
    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "synthetic-triage",
            "dataset_source_ref": "data/raw/synthetic-triage.csv",
        },
        "target_intent": {
            "target_column": "risk_tier",
            "task_type": "multiclass_classification",
            "observed_labels": ["low_risk", "medium_risk", "high_risk"],
            "positive_label_candidate": None,
            "observed_target_distribution": {"low_risk": 500, "medium_risk": 300, "high_risk": 200},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": "record_ref", "reason": "identifier_candidate_excluded_from_features"}
        ],
        "initial_feature_candidates": ["age", "tenure_months"],
        "categorical_domain_intent": [],
        "binary_result_semantics_intent": None,
        "multiclass_result_semantics_intent": {
            "schema_version": "multiclass_result_semantics_intent.v1",
            "review_status": "approved",
            "problem_type": "multiclass_classification",
            "primary_output": "predicted_class",
            "probability_output": "class_probabilities",
            "decision_strategy": "argmax",
            "review_notes": "Reviewed for S0207 schema-level fixture coverage.",
        },
    }


def _synthetic_multiclass_discovery_evidence() -> dict:
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "field_observations": [
            {
                "name": "age", "inferred_type": "integer", "null_count": 0, "null_rate": 0.0,
                "cardinality": 40, "sample_min": 18, "sample_max": 90,
            },
            {
                "name": "tenure_months", "inferred_type": "integer", "null_count": 0, "null_rate": 0.0,
                "cardinality": 60, "sample_min": 0, "sample_max": 72,
            },
        ],
        "generation_settings": {"seed": 0, "generator_version": "discovery-evidence.v1"},
    }


def _synthetic_semantic_intent_v2() -> dict:
    return {
        "schema_version": "dataset-semantic-intent.v2",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": "synthetic-triage"},
        "authoring_generation_id": "gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": "multiclass-predictive-classification",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": [
            {"field_name": "risk_tier", "role": "target", "include_in_features": False},
        ],
        "target_semantics": {
            "target_field_name": "risk_tier",
            "task_type": "multiclass_classification",
            "classes": [
                {"class_id": "low_risk", "display_label": "Low Risk"},
                {"class_id": "medium_risk", "display_label": "Medium Risk"},
                {"class_id": "high_risk", "display_label": "High Risk"},
            ],
            "is_final_training_configuration": False,
        },
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-16T00:00:00+00:00",
    }


def test_normalized_multiclass_contract_from_approved_fixtures_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _build_execution_contract(
        _synthetic_multiclass_modeling_intent(),
        _synthetic_multiclass_discovery_evidence(),
        None,
        semantic_intent=_synthetic_semantic_intent_v2(),
    )
    assert "result_semantics" in contract
    jsonschema.validate(contract, schema)


def _synthetic_continuous_regression_training_policy_intent() -> dict:
    return {
        "review_status": "approved",
        "numeric_handling": "standardize",
        "categorical_encoding_policy": "onehot",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "primary_metric": "r2",
        "secondary_metrics": ["mae", "rmse"],
        "modeling_constraints": {
            "allowed_model_families": ["gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "gradient_boosting",
                "hyperparameters": {
                    "n_estimators": 200,
                    "learning_rate": 0.05,
                    "max_depth": 3,
                    "min_samples_leaf": 20,
                    "subsample": 0.9,
                    "loss": "squared_error",
                },
            },
        },
    }


def _synthetic_continuous_regression_modeling_intent(*, with_training_policy: bool = True) -> dict:
    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "synthetic-strength",
            "dataset_source_ref": "data/raw/synthetic-strength.csv",
        },
        "target_intent": {
            "target_column": "strength_value",
            "task_type": "continuous_regression",
            "observed_labels": [],
            "positive_label_candidate": None,
            "observed_target_distribution": {},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": "record_ref", "reason": "identifier_candidate_excluded_from_features"}
        ],
        "initial_feature_candidates": ["cement", "water"],
        "categorical_domain_intent": [],
        "binary_result_semantics_intent": None,
        "multiclass_result_semantics_intent": None,
        "continuous_regression_result_semantics_intent": {
            "schema_version": "continuous_regression_result_semantics_intent.v1",
            "review_status": "approved",
            "problem_type": "continuous_regression",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
            "review_notes": "Reviewed for S0223 schema-level fixture coverage.",
        },
        "training_policy_intent": (
            _synthetic_continuous_regression_training_policy_intent()
            if with_training_policy
            else None
        ),
    }


def _synthetic_continuous_regression_discovery_evidence() -> dict:
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "field_observations": [
            {
                "name": "cement", "inferred_type": "float", "null_count": 0, "null_rate": 0.0,
                "cardinality": 120, "sample_min": 100.0, "sample_max": 540.0,
            },
            {
                "name": "water", "inferred_type": "float", "null_count": 0, "null_rate": 0.0,
                "cardinality": 90, "sample_min": 120.0, "sample_max": 250.0,
            },
        ],
        "generation_settings": {"seed": 0, "generator_version": "discovery-evidence.v1"},
    }


def _synthetic_semantic_intent_v3() -> dict:
    return {
        "schema_version": "dataset-semantic-intent.v3",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": "synthetic-strength"},
        "authoring_generation_id": "gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": "continuous-predictive-regression",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": [
            {"field_name": "strength_value", "role": "target", "include_in_features": False},
        ],
        "target_semantics": {
            "target_field_name": "strength_value",
            "task_type": "continuous_regression",
            "target_value_kind": "continuous_numeric",
            "is_final_training_configuration": False,
        },
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-19T00:00:00+00:00",
    }


def test_normalized_continuous_regression_contract_from_approved_fixtures_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _build_execution_contract(
        _synthetic_continuous_regression_modeling_intent(),
        _synthetic_continuous_regression_discovery_evidence(),
        None,
        semantic_intent=_synthetic_semantic_intent_v3(),
    )
    assert "result_semantics" in contract
    assert contract["result_semantics"] == _valid_continuous_regression_result_semantics()
    jsonschema.validate(contract, schema)


def test_execution_contract_v1_identity_remains_unchanged():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    jsonschema.validate(contract, schema)
    assert contract["contract_version"] == "execution_contract.v1"


# ---------------------------------------------------------------------------
# Execution contract materialization tests (Project Spec S0024)
#
# Exercise pipeline.contract_derivation.materialize_execution_contract /
# _build_execution_contract against synthetic upstream artifacts (a small,
# deliberately non-Telco "campaign-response" fixture, matching the
# S0014-established dataset-agnosticism precedent), plus the real
# materialized Telco artifact when present on disk.
# ---------------------------------------------------------------------------


def _modeling_intent(
    dataset_slug: str = "campaign-response",
    initial_feature_candidates: list | None = None,
    identifier_and_ignored_columns: list | None = None,
    categorical_domain_intent: list | None = None,
) -> dict:
    if initial_feature_candidates is None:
        initial_feature_candidates = ["age", "channel", "opted_in", "last_contact_days"]
    if identifier_and_ignored_columns is None:
        identifier_and_ignored_columns = [
            {"name": "customer_ref", "reason": "identifier_candidate_excluded_from_features"}
        ]
    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": dataset_slug,
            "dataset_source_ref": f"data/raw/{dataset_slug}.csv",
        },
        "target_intent": {
            "target_column": "responded",
            "task_type": "binary_classification",
            "observed_labels": ["No", "Yes"],
            "positive_label_candidate": "Yes",
            "observed_target_distribution": {"No": 800, "Yes": 200},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": identifier_and_ignored_columns,
        "initial_feature_candidates": initial_feature_candidates,
        "categorical_domain_intent": list(categorical_domain_intent or []),
    }


def _discovery_evidence(seed: int = 0) -> dict:
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "field_observations": [
            {
                "name": "age",
                "inferred_type": "integer",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 40,
                "sample_min": 18,
                "sample_max": 90,
            },
            {
                "name": "channel",
                "inferred_type": "string",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 3,
                "sample_min": "email",
                "sample_max": "sms",
            },
            {
                "name": "opted_in",
                "inferred_type": "boolean",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 2,
                "sample_min": "0",
                "sample_max": "1",
            },
            {
                "name": "last_contact_days",
                "inferred_type": "float",
                "null_count": 5,
                "null_rate": 0.005,
                "cardinality": 300,
                "sample_min": 0.0,
                "sample_max": 365.0,
            },
        ],
        "generation_settings": {"seed": seed, "generator_version": "discovery-evidence.v1"},
    }


def _preparation_recipe(review_status: str = "inferred_pending_review") -> dict:
    return {
        "schema_version": "candidate-preparation-recipe.v1",
        "transformations": [
            {
                "transformation_type": "missing_value_handling",
                "source_columns": ["last_contact_days"],
                "target_columns": ["last_contact_days"],
                "reason": "blank values observed",
                "review_status": review_status,
            }
        ],
    }


def test_materialized_contract_excludes_identifier_and_unresolved_review_column():
    modeling_intent = _modeling_intent()
    discovery_evidence = _discovery_evidence()
    preparation_recipe = _preparation_recipe()

    contract = _build_execution_contract(modeling_intent, discovery_evidence, preparation_recipe)

    assert "customer_ref" not in contract["feature_columns"]
    assert "customer_ref" in contract["ignored_columns"]
    assert "last_contact_days" not in contract["feature_columns"], (
        "a column with an unresolved (not explicit/inferred_approved) "
        "missing-value review_status must never be silently approved into "
        "feature_columns"
    )
    assert "last_contact_days" in contract["ignored_columns"]
    assert contract["feature_columns"] == ["age", "channel", "opted_in"]


def test_materialized_contract_includes_column_with_approved_review_status():
    modeling_intent = _modeling_intent()
    discovery_evidence = _discovery_evidence()
    preparation_recipe = _preparation_recipe(review_status="inferred_approved")

    contract = _build_execution_contract(modeling_intent, discovery_evidence, preparation_recipe)

    assert "last_contact_days" in contract["feature_columns"], (
        "an explicitly approved review_status must be honored, not treated "
        "the same as an unresolved one"
    )
    assert "last_contact_days" in contract["optional_columns"], (
        "a feature with null_rate > 0 belongs in optional_columns, not required_columns"
    )


def test_materialized_contract_preserves_boolean_feature_type():
    contract = _build_execution_contract(_modeling_intent(), _discovery_evidence(), None)
    assert contract["feature_definitions"]["opted_in"]["type"] == "boolean"
    assert "domain_constraints" not in contract["feature_definitions"]["opted_in"]


def test_materialized_contract_numeric_domain_constraints_grounded_in_discovery_evidence():
    contract = _build_execution_contract(_modeling_intent(), _discovery_evidence(), None)
    assert contract["feature_definitions"]["age"]["domain_constraints"] == {"min": 18, "max": 90}


def test_materialized_contract_validates_against_schema():
    schema = _load_json(SCHEMA_PATH)
    contract = _build_execution_contract(_modeling_intent(), _discovery_evidence(), None)
    jsonschema.validate(contract, schema)


def test_materialize_execution_contract_writes_valid_contract(tmp_path):
    schema_dir = tmp_path / "contracts"
    schema_dir.mkdir()
    (schema_dir / "execution-contract.schema.json").write_text(
        SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

    result = materialize_execution_contract(
        _modeling_intent(),
        _discovery_evidence(),
        output_relative_path="contracts/campaign-response/execution-contract.json",
        repo_root=tmp_path,
        preparation_recipe=_preparation_recipe(),
        evidence_output_relative_path=(
            "pipeline/evidence/campaign-response/execution-contract-materialization-evidence.json"
        ),
    )

    written_contract = _load_json(tmp_path / "contracts" / "campaign-response" / "execution-contract.json")
    assert written_contract == result["execution_contract"]
    jsonschema.validate(written_contract, _load_json(SCHEMA_PATH))

    written_evidence = _load_json(
        tmp_path
        / "pipeline"
        / "evidence"
        / "campaign-response"
        / "execution-contract-materialization-evidence.json"
    )
    assert written_evidence["contract_version"] == "execution_contract_materialization_evidence.v1"
    assert written_evidence["positive_label_policy"]["positive_label_candidate"] == "Yes"
    assert written_evidence["identifier_exclusion_policy"][0]["name"] == "customer_ref"
    assert any(
        entry["name"] == "last_contact_days"
        for entry in written_evidence["unresolved_feature_exclusions"]
    )
    assert not any(written_evidence["execution_contract_boundary_confirmations"].values())


def test_unresolved_review_columns_ignores_resolved_transformations():
    resolved = _unresolved_review_columns(_preparation_recipe(review_status="explicit"))
    assert resolved == {}
    pending = _unresolved_review_columns(_preparation_recipe(review_status="inferred_pending_review"))
    assert pending == {"last_contact_days": "inferred_pending_review"}


# ---------------------------------------------------------------------------
# Categorical-domain materialization (Project Spec S0102)
# ---------------------------------------------------------------------------


def _approved_channel_declaration(values=("email", "sms", "call")) -> dict:
    return {
        "name": "channel",
        "accepted_values": list(values),
        "review_status": "approved",
        "source_basis": "Reviewed authoring basis; bounded cardinality.",
        "closed_for_inference": True,
    }


def test_approved_categorical_domain_is_materialized_into_domain_constraints():
    modeling_intent = _modeling_intent(
        categorical_domain_intent=[_approved_channel_declaration()]
    )
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert contract["feature_definitions"]["channel"]["domain_constraints"] == {
        "values": ["email", "sms", "call"]
    }


def test_pending_review_categorical_domain_is_not_materialized():
    pending = _approved_channel_declaration()
    pending["review_status"] = "pending_review"
    modeling_intent = _modeling_intent(categorical_domain_intent=[pending])
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "domain_constraints" not in contract["feature_definitions"]["channel"]


def test_duplicate_accepted_values_are_rejected_not_materialized():
    duplicated = _approved_channel_declaration(values=("email", "email", "sms"))
    modeling_intent = _modeling_intent(categorical_domain_intent=[duplicated])
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "domain_constraints" not in contract["feature_definitions"]["channel"]


def test_blank_accepted_value_is_rejected_not_materialized():
    blank = _approved_channel_declaration(values=("email", "  "))
    modeling_intent = _modeling_intent(categorical_domain_intent=[blank])
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "domain_constraints" not in contract["feature_definitions"]["channel"]


def test_declaration_for_unknown_feature_is_rejected():
    unknown = _approved_channel_declaration()
    unknown["name"] = "not_a_real_column"
    modeling_intent = _modeling_intent(categorical_domain_intent=[unknown])
    # Must not raise -- an unknown-feature declaration is a normal rejected outcome.
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "not_a_real_column" not in contract["feature_definitions"]


def test_declaration_for_numeric_feature_is_rejected_as_type_incompatible():
    type_incompatible = _approved_channel_declaration()
    type_incompatible["name"] = "age"  # age is numeric, not categorical
    modeling_intent = _modeling_intent(categorical_domain_intent=[type_incompatible])
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "domain_constraints" not in contract["feature_definitions"]["age"] or (
        set(contract["feature_definitions"]["age"]["domain_constraints"].keys()) == {"min", "max"}
    )


def test_declaration_for_boolean_feature_is_rejected_as_type_incompatible():
    type_incompatible = _approved_channel_declaration()
    type_incompatible["name"] = "opted_in"  # opted_in is boolean, not categorical
    modeling_intent = _modeling_intent(categorical_domain_intent=[type_incompatible])
    contract = _build_execution_contract(modeling_intent, _discovery_evidence(), None)
    assert "domain_constraints" not in contract["feature_definitions"]["opted_in"]


def test_validate_categorical_domain_declaration_accepts_approved_categorical():
    feature_columns = ["channel"]
    feature_definitions = {"channel": {"type": "categorical"}}
    values, reason = _validate_categorical_domain_declaration(
        _approved_channel_declaration(), feature_columns, feature_definitions
    )
    assert values == ["email", "sms", "call"]
    assert reason is None


def test_validate_categorical_domain_declaration_names_rejection_reason():
    feature_columns = ["channel"]
    feature_definitions = {"channel": {"type": "categorical"}}
    pending = _approved_channel_declaration()
    pending["review_status"] = "pending_review"
    values, reason = _validate_categorical_domain_declaration(
        pending, feature_columns, feature_definitions
    )
    assert values is None
    assert "channel" in reason


def test_materialize_execution_contract_evidence_reports_categorical_domain_coverage(tmp_path):
    schema_dir = tmp_path / "contracts"
    schema_dir.mkdir()
    (schema_dir / "execution-contract.schema.json").write_text(
        SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

    pending = _approved_channel_declaration()
    modeling_intent = _modeling_intent(categorical_domain_intent=[pending])

    result = materialize_execution_contract(
        modeling_intent,
        _discovery_evidence(),
        output_relative_path="contracts/campaign-response/execution-contract.json",
        repo_root=tmp_path,
        preparation_recipe=_preparation_recipe(),
    )
    evidence = result["execution_contract_materialization_evidence"]
    coverage = evidence["categorical_domain_materialization"]
    assert coverage["approved_categorical_domains"] == ["channel"]
    assert coverage["unresolved_categorical_features"] == []
    assert coverage["rejected_categorical_domain_declarations"] == []
    assert coverage["values_inferred_during_materialization"] is False


def test_materialize_execution_contract_evidence_names_unresolved_categorical_feature(tmp_path):
    schema_dir = tmp_path / "contracts"
    schema_dir.mkdir()
    (schema_dir / "execution-contract.schema.json").write_text(
        SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

    result = materialize_execution_contract(
        _modeling_intent(),
        _discovery_evidence(),
        output_relative_path="contracts/campaign-response/execution-contract.json",
        repo_root=tmp_path,
        preparation_recipe=_preparation_recipe(),
    )
    coverage = result["execution_contract_materialization_evidence"]["categorical_domain_materialization"]
    assert coverage["approved_categorical_domains"] == []
    assert coverage["unresolved_categorical_features"] == ["channel"]


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_PATH.exists(),
    reason="Telco execution contract not yet materialized on disk",
)
def test_real_telco_execution_contract_validates_and_excludes_identifier_column():
    schema = _load_json(SCHEMA_PATH)
    contract = _load_json(TELCO_EXECUTION_CONTRACT_PATH)

    jsonschema.validate(contract, schema)
    assert contract["dataset_id"] == "telco-customer-churn"
    assert contract["target_column"] == "Churn"
    assert "customerID" not in contract["feature_columns"], (
        "customerID is a per-row identifier candidate, not a modeling feature, "
        "and must never be silently approved into feature_columns"
    )
    assert "customerID" in contract["ignored_columns"]
    assert contract["feature_definitions"]["SeniorCitizen"]["type"] == "boolean"


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_PATH.exists(),
    reason="Telco execution contract not yet materialized on disk",
)
def test_real_telco_execution_contract_includes_total_charges_once_approved():
    """TotalCharges' blank-value preparation policy was resolved and approved
    by Project Spec S0028 (recorded as review_status 'inferred_approved' in
    pipeline/evidence/telco-customer-churn/preparation-recipe.json), so the
    real, on-disk contract must now include it as a feature rather than
    excluding it. This is a direct consequence of the reusable, generic rule
    exercised by test_unresolved_review_columns_ignores_resolved_transformations
    above -- a column is only ever excluded while its own recipe entry is
    NOT 'explicit'/'inferred_approved', regardless of dataset."""
    schema = _load_json(SCHEMA_PATH)
    contract = _load_json(TELCO_EXECUTION_CONTRACT_PATH)
    recipe = _load_json(
        REPO_ROOT / "pipeline" / "evidence" / "telco-customer-churn" / "preparation-recipe.json"
    )
    total_charges_review_status = next(
        t["review_status"]
        for t in recipe["transformations"]
        if t["transformation_type"] == "missing_value_handling"
        and "TotalCharges" in t["target_columns"]
    )

    jsonschema.validate(contract, schema)
    if total_charges_review_status in ("explicit", "inferred_approved"):
        assert "TotalCharges" in contract["feature_columns"], (
            "TotalCharges blank-value handling is approved "
            f"({total_charges_review_status!r}) but was excluded from the "
            "official contract's feature_columns"
        )
        assert "TotalCharges" not in contract["ignored_columns"]
        assert contract["feature_definitions"]["TotalCharges"]["type"] == "numeric"
    else:
        assert "TotalCharges" not in contract["feature_columns"], (
            "TotalCharges blank-value handling is still "
            f"{total_charges_review_status!r} and must not be silently "
            "approved into the official contract"
        )
        assert "TotalCharges" in contract["ignored_columns"]


TELCO_EXECUTION_CONTRACT_MATERIALIZATION_EVIDENCE_PATH = (
    REPO_ROOT
    / "pipeline"
    / "evidence"
    / "telco-customer-churn"
    / "execution-contract-materialization-evidence.json"
)

# Project Spec S0102: the real, active Telco categorical feature set, as
# determined from the current execution contract rather than trusted
# blindly from the spec's own illustrative list.
_TELCO_CATEGORICAL_FEATURE_NAMES = sorted(
    name
    for name, defn in _load_json(TELCO_EXECUTION_CONTRACT_PATH)["feature_definitions"].items()
    if defn.get("type") == "categorical"
) if TELCO_EXECUTION_CONTRACT_PATH.exists() else []


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_PATH.exists(),
    reason="Telco execution contract not yet materialized on disk",
)
def test_real_telco_execution_contract_every_active_categorical_feature_has_approved_domain():
    """Project Spec S0102: every active Telco categorical feature must carry
    a reviewed, approved, non-empty domain_constraints.values list on the
    real, materialized execution contract -- no unresolved closed selects
    remain."""
    contract = _load_json(TELCO_EXECUTION_CONTRACT_PATH)
    assert _TELCO_CATEGORICAL_FEATURE_NAMES, "expected at least one real Telco categorical feature"
    for name in _TELCO_CATEGORICAL_FEATURE_NAMES:
        values = contract["feature_definitions"][name].get("domain_constraints", {}).get("values")
        assert values, f"{name}: expected a non-empty domain_constraints.values list"
        assert len(set(values)) == len(values), f"{name}: accepted values must not contain duplicates"


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_MATERIALIZATION_EVIDENCE_PATH.exists(),
    reason="Telco execution contract materialization evidence not yet written to disk",
)
def test_real_telco_execution_contract_materialization_evidence_reports_full_categorical_coverage():
    """Project Spec S0102: the real materialization evidence must name every
    active Telco categorical feature as approved, with no unresolved
    categorical features and no rejected declarations, and must confirm no
    values were inferred during materialization."""
    evidence = _load_json(TELCO_EXECUTION_CONTRACT_MATERIALIZATION_EVIDENCE_PATH)
    coverage = evidence["categorical_domain_materialization"]
    assert sorted(coverage["approved_categorical_domains"]) == _TELCO_CATEGORICAL_FEATURE_NAMES
    assert coverage["unresolved_categorical_features"] == []
    assert coverage["values_inferred_during_materialization"] is False


# ---------------------------------------------------------------------------
# Conditional missing-value and open-categorical input contract evolution
# (Project Spec S0156). Every fixture below is dataset-agnostic -- no
# Telco-specific name or slug is used as a branching key.
# ---------------------------------------------------------------------------


def _synthetic_contract_with_new_vocabulary() -> dict:
    contract = _valid_contract()
    contract["feature_columns"] = [
        "total_amount",
        "tenure_months",
        "plan_type",
        "account_id_flag",
        "is_active",
        "legacy_optional",
    ]
    contract["required_columns"] = [
        "total_amount",
        "tenure_months",
        "plan_type",
        "account_id_flag",
        "is_active",
    ]
    contract["optional_columns"] = ["legacy_optional"]
    contract["feature_definitions"] = {
        "total_amount": {
            "type": "numeric",
            "input_policy": {
                "conditional_blank_normalization": {
                    "accepted_representation": "blank_string_after_trim",
                    "when": {"field": "tenure_months", "operator": "equals", "value": 0},
                    "materialized_value": 0.0,
                    "otherwise": "reject",
                    "null_behavior": "reject",
                }
            },
        },
        "tenure_months": {"type": "numeric"},
        "plan_type": {
            "type": "categorical",
            "domain_constraints": {
                "known_values": ["basic", "pro"],
                "categorical_value_type": "string",
                "validation_behavior": "ignore_and_report",
            },
        },
        "account_id_flag": {
            "type": "categorical",
            "domain_constraints": {
                "known_values": [0, 1],
                "categorical_value_type": "integer",
                "validation_behavior": "reject_unknown",
            },
        },
        "is_active": {"type": "boolean"},
        "legacy_optional": {
            "type": "categorical",
            "domain_constraints": {"values": ["x", "y"]},
        },
    }
    contract["missing_value_policy"] = {}
    return contract


def test_synthetic_contract_with_new_vocabulary_passes_schema():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(_synthetic_contract_with_new_vocabulary(), schema)


def test_conditional_policy_rejects_arbitrary_operator():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    when = contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["when"]
    when["operator"] = "greater_than"
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_conditional_policy_rejects_non_scalar_comparison_value():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    when = contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["when"]
    when["value"] = {"$eval": "os.system('echo pwned')"}
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_conditional_policy_rejects_null_as_accepted_representation():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    policy = contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]
    policy["null_behavior"] = "accept"
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_conditional_policy_requires_every_declared_field():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    del contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["otherwise"]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_categorical_known_values_and_validation_behavior_independent_of_legacy_values():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    jsonschema.validate(contract, schema)
    plan_type_domain = contract["feature_definitions"]["plan_type"]["domain_constraints"]
    assert "values" not in plan_type_domain
    assert plan_type_domain["known_values"] == ["basic", "pro"]
    assert plan_type_domain["validation_behavior"] == "ignore_and_report"


def test_contradictory_legacy_and_new_categorical_declarations_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    contract["feature_definitions"]["plan_type"]["domain_constraints"]["values"] = ["basic", "pro"]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_integer_categorical_known_values_reject_boolean_items():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    contract["feature_definitions"]["account_id_flag"]["domain_constraints"]["known_values"] = [
        True,
        False,
    ]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_known_values_requires_categorical_value_type():
    schema = _load_json(SCHEMA_PATH)
    contract = _synthetic_contract_with_new_vocabulary()
    del contract["feature_definitions"]["plan_type"]["domain_constraints"]["categorical_value_type"]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_legacy_categorical_definitions_remain_valid_without_new_vocabulary():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    jsonschema.validate(contract, schema)
    assert "known_values" not in contract["feature_definitions"]["job"]["domain_constraints"]


# ---------------------------------------------------------------------------
# External Model Evidence, Sealed-Test, and Educational Readiness Contract
# Evolution (Project Spec S0157).
#
# This spec's own implementation-request.md/context-pack authorizes editing
# tests/test_execution_contract_schema.py and tests/test_training_pipeline.py
# but authorizes creating no new file at all (repository_context.
# allowed_create_paths is an empty array; tests/pipeline/
# test_external_model_evidence_contracts.py only appears in
# candidate_create_paths, which is informative scope discovery, not
# authorization -- promoting it requires a later, separately-authorized
# implementation request). The pure JSON-Schema validation coverage for all
# five evolved schemas therefore lives here rather than in a dedicated new
# test module; pipeline/training.py's fail-closed training-boundary coverage
# lives in tests/test_training_pipeline.py instead. Every fixture below is
# synthetic and uses inert digest strings -- no model is loaded, fit, or
# used for prediction, and no train/validation/test data is read.
# ---------------------------------------------------------------------------

MODEL_SELECTION_EVIDENCE_SCHEMA_PATH = REPO_ROOT / "pipeline" / "model-selection-evidence.schema.json"
TRAINING_METRICS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-metrics.schema.json"
TRAINING_PARAMETER_RECORD_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-parameter-record.schema.json"
INFERENCE_BUNDLE_SCHEMA_PATH = REPO_ROOT / "contracts" / "inference-bundle.schema.json"
TELCO_INFERENCE_BUNDLE_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "inference-bundle.json"
_TELCO_TRAINING_RUN_DIR = (
    REPO_ROOT
    / "pipeline"
    / "training-runs"
    / "telco-customer-churn"
    / "train-20260721T124721Z"
)
TELCO_HISTORICAL_METRICS_PATH = _TELCO_TRAINING_RUN_DIR / "metrics.json"
TELCO_HISTORICAL_MODEL_SELECTION_EVIDENCE_PATH = _TELCO_TRAINING_RUN_DIR / "model-selection-evidence.json"
TELCO_HISTORICAL_TRAINING_PARAMETER_RECORD_PATH = _TELCO_TRAINING_RUN_DIR / "training-parameter-record.json"

_INERT_FINGERPRINT_A = "a" * 64
_INERT_FINGERPRINT_B = "b" * 64
_INERT_SHA_MODEL = "c" * 64


def _reduced_evidence_policy() -> dict:
    return {
        "raw_logs_prohibited": True,
        "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True,
        "secrets_prohibited": True,
        "raw_dataset_embedded": False,
        "model_bytes_embedded": False,
        "notebook_state_embedded": False,
        "reduced_and_sanitized": True,
    }


def _assert_finite_metric_values(*sections) -> None:
    """Mirrors pipeline.training._finite_metric_value's finiteness check --
    JSON Schema's plain 'number' type does not, by itself, reject NaN or
    Infinity constructed directly in a Python fixture (only JSON's own
    number grammar excludes them), so finiteness is asserted here."""
    for section in sections:
        if not section:
            continue
        for entry in section.get("metrics", []) or section.get("metric_summaries", []):
            value = entry.get("value", entry.get("mean"))
            assert math.isfinite(value), f"non-finite metric value: {entry!r}"


def _assert_selected_candidate_is_declared(evidence: dict) -> None:
    candidate_ids = {candidate["candidate_id"] for candidate in evidence["candidates"]}
    selected_id = evidence["selected_candidate"]["candidate_id"]
    assert selected_id in candidate_ids, (
        f"selected_candidate.candidate_id {selected_id!r} is not among the declared "
        f"candidates {sorted(candidate_ids)!r}"
    )


def _assert_model_state_fingerprint_consistency(*fingerprints: str) -> None:
    assert len(set(fingerprints)) == 1, f"model_state_fingerprint mismatch across evidence: {fingerprints}"


# --- execution-contract.schema.json: model_source_mode / vocabulary -------


def test_execution_contract_omitting_model_source_mode_is_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    assert "model_source_mode" not in contract
    jsonschema.validate(contract, schema)


def test_execution_contract_explicit_atlas_internal_training_is_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["model_source_mode"] = "atlas_internal_training"
    jsonschema.validate(contract, schema)


def test_execution_contract_validated_external_fitted_model_is_schema_valid():
    """Schema-valid only -- pipeline.training.train_from_paths blocks this
    declaration before estimator construction or fit (see
    tests/test_training_pipeline.py)."""
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["model_source_mode"] = "validated_external_fitted_model"
    contract["modeling_constraints"]["allowed_model_families"] = ["hist_gradient_boosting"]
    jsonschema.validate(contract, schema)


def test_execution_contract_rejects_boolean_model_source_mode():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["model_source_mode"] = True
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_rejects_free_form_model_source_mode():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["model_source_mode"] = "some_other_source"
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_PATH.exists(),
    reason="Telco execution contract not yet materialized on disk",
)
def test_real_telco_execution_contract_explicitly_declares_validated_external_fitted_model():
    """Project Spec S0187: the checked-in Telco execution contract must
    explicitly declare the already-governed external model source -- not
    rely on schema omission -- since the canonical notebook's external
    inference-bundle boundary (pipeline.generate_inference_bundle) and its
    own precondition check both require this explicit declaration before
    calling the external bundle producer."""
    schema = _load_json(SCHEMA_PATH)
    contract = _load_json(TELCO_EXECUTION_CONTRACT_PATH)
    jsonschema.validate(contract, schema)
    assert contract["model_source_mode"] == "validated_external_fitted_model"


def test_execution_contract_hist_gradient_boosting_family_declaration_is_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["modeling_constraints"]["allowed_model_families"] = ["hist_gradient_boosting"]
    jsonschema.validate(contract, schema)


def test_execution_contract_average_precision_and_brier_score_are_valid_and_distinct_from_pr_auc():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["primary_metric"] = "average_precision"
    contract["secondary_metrics"] = ["pr_auc", "brier_score"]
    jsonschema.validate(contract, schema)
    assert contract["primary_metric"] != "pr_auc"
    assert "pr_auc" in contract["secondary_metrics"] and "average_precision" not in contract["secondary_metrics"]


def test_execution_contract_new_metric_identifiers_are_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["secondary_metrics"] = ["precision", "recall", "f2", "balanced_accuracy"]
    jsonschema.validate(contract, schema)


def test_execution_contract_existing_metric_identifiers_remain_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    for metric in ("roc_auc", "f1", "accuracy", "log_loss", "pr_auc"):
        contract["primary_metric"] = metric
        jsonschema.validate(contract, schema)


# --- pipeline/model-selection-evidence.schema.json: external profile ------


def _external_model_selection_evidence() -> dict:
    return {
        "schema_version": "model-selection-evidence.external-fitted-model.v1",
        "artifact_kind": "model_selection_evidence",
        "created_at": "2026-08-01T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "producer": "external-notebook-pipeline",
            "handoff_lineage_reference": "handoff/telco-customer-churn/2026-08-01/lineage.json",
        },
        "dataset_identity": {"dataset_slug": "telco-customer-churn"},
        "selection_protocol": {"protocol_id": "cross_validation_with_practical_tie_break"},
        "selection_policy": {
            "primary_metric": "average_precision",
            "ranking_direction": "higher_is_better",
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "metric_summaries": [
                {"name": "average_precision", "mean": 0.71, "standard_deviation": 0.02},
                {"name": "roc_auc", "mean": 0.84, "standard_deviation": 0.01},
            ],
        },
        "validation_metrics": {
            "partition_role": "validation",
            "metrics": [
                {"name": "average_precision", "value": 0.70},
                {"name": "roc_auc", "value": 0.845},
                {"name": "brier_score", "value": 0.14},
            ],
        },
        "practical_tie": {
            "tolerance": 0.005,
            "tie_detected": True,
            "tie_break_criteria": [
                {
                    "order": 1,
                    "criterion": "brier_score",
                    "observed_values": [
                        {"candidate_id": "hist_gradient_boosting_candidate", "value": 0.14},
                        {"candidate_id": "hist_gradient_boosting_alternate", "value": 0.16},
                    ],
                }
            ],
        },
        "candidates": [
            {
                "candidate_id": "hist_gradient_boosting_candidate",
                "model_family": "hist_gradient_boosting",
                "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
            },
            {
                "candidate_id": "hist_gradient_boosting_alternate",
                "model_family": "hist_gradient_boosting",
                "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
            },
        ],
        "selected_candidate": {"candidate_id": "hist_gradient_boosting_candidate"},
        "selection_rationale": (
            "Highest cross-validated average_precision within practical tie tolerance; "
            "brier_score tie-break favors the selected candidate."
        ),
        "sealed_test_confirmation": {
            "test_partition_role": "test",
            "used_for_model_selection": False,
            "sealed_before_selection": True,
        },
        "path_references": {
            "model_selection_evidence_reference": (
                "external-handoff/telco-customer-churn/model-selection-evidence.json"
            ),
        },
        "hashes": {"algorithm": "sha256", "model_state_fingerprint": _INERT_FINGERPRINT_A},
        "evidence_policy": _reduced_evidence_policy(),
    }


def test_external_model_selection_evidence_valid_cv_validation_tie_and_tie_break():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _external_model_selection_evidence()
    jsonschema.validate(evidence, schema)
    _assert_selected_candidate_is_declared(evidence)
    _assert_finite_metric_values(evidence["cross_validation_summary"], evidence["validation_metrics"])


def test_external_model_selection_evidence_selected_candidate_missing_is_flagged():
    """Selected candidate not present among declared candidates -- schema
    cannot express this cross-referential invariant (no $data support), so
    it is checked by the same deterministic cross-fixture assertion the
    request.md's own validation flow describes."""
    evidence = _external_model_selection_evidence()
    evidence["selected_candidate"] = {"candidate_id": "not_a_declared_candidate"}
    with pytest.raises(AssertionError):
        _assert_selected_candidate_is_declared(evidence)


def test_external_model_selection_evidence_final_test_used_for_selection_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _external_model_selection_evidence()
    evidence["sealed_test_confirmation"]["used_for_model_selection"] = True
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_arbitrary_estimator_import_path_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _external_model_selection_evidence()
    evidence["candidates"][0]["estimator_identity"] = {
        "library": "scikit-learn",
        "class_name": "sklearn.ensemble.HistGradientBoostingClassifier",
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_rejects_fabricated_training_run_path():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _external_model_selection_evidence()
    evidence["path_references"]["model_selection_evidence_reference"] = (
        "pipeline/training-runs/telco-customer-churn/train-20260721T124721Z/model-selection-evidence.json"
    )
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_undeclared_tie_break_criterion_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _external_model_selection_evidence()
    evidence["practical_tie"]["tie_break_criteria"][0]["criterion"] = "coin_flip"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_internal_model_selection_evidence_v1_still_valid_unmodified():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)
    doc = _load_json(TELCO_HISTORICAL_MODEL_SELECTION_EVIDENCE_PATH)
    jsonschema.validate(doc, schema)


# --- Project Spec S0186: bounded external selection-candidate vocabulary --


def _multi_family_external_candidates() -> list[dict]:
    return [
        {
            "candidate_id": "logistic_regression",
            "model_family": "logistic_regression",
            "estimator_identity": {"library": "scikit-learn", "class_name": "LogisticRegression"},
        },
        {
            "candidate_id": "decision_tree",
            "model_family": "decision_tree",
            "estimator_identity": {"library": "scikit-learn", "class_name": "DecisionTreeClassifier"},
        },
        {
            "candidate_id": "random_forest",
            "model_family": "random_forest",
            "estimator_identity": {"library": "scikit-learn", "class_name": "RandomForestClassifier"},
        },
        {
            "candidate_id": "hist_gradient_boosting",
            "model_family": "hist_gradient_boosting",
            "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
        },
    ]


def _multi_family_external_model_selection_evidence() -> dict:
    evidence = _external_model_selection_evidence()
    evidence["candidates"] = _multi_family_external_candidates()
    evidence["selected_candidate"] = {"candidate_id": "hist_gradient_boosting"}
    evidence["practical_tie"]["tie_break_criteria"][0]["observed_values"] = [
        {"candidate_id": "hist_gradient_boosting", "value": 0.13320337544392163},
        {"candidate_id": "logistic_regression", "value": 0.13389814952096538},
    ]
    return evidence


def test_external_model_selection_evidence_four_bounded_family_pairs_coexist_and_validate():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    jsonschema.validate(evidence, schema)
    _assert_selected_candidate_is_declared(evidence)
    assert {c["model_family"] for c in evidence["candidates"]} == {
        "logistic_regression",
        "decision_tree",
        "random_forest",
        "hist_gradient_boosting",
    }


def test_external_model_selection_evidence_selected_candidate_may_be_hist_gradient_boosting_among_four():
    evidence = _multi_family_external_model_selection_evidence()
    assert evidence["selected_candidate"]["candidate_id"] == "hist_gradient_boosting"
    _assert_selected_candidate_is_declared(evidence)


def test_external_model_selection_evidence_canonical_brier_score_tie_break_with_observed_values_validates():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    jsonschema.validate(evidence, schema)
    criterion = evidence["practical_tie"]["tie_break_criteria"][0]
    assert criterion["criterion"] == "brier_score"
    assert criterion["order"] == 1
    assert {ov["candidate_id"] for ov in criterion["observed_values"]} == {
        "hist_gradient_boosting",
        "logistic_regression",
    }


@pytest.mark.parametrize(
    "model_family,class_name",
    [
        ("logistic_regression", "DecisionTreeClassifier"),
        ("decision_tree", "RandomForestClassifier"),
        ("random_forest", "LogisticRegression"),
        ("hist_gradient_boosting", "LogisticRegression"),
    ],
)
def test_external_model_selection_evidence_cross_paired_family_class_rejected(model_family, class_name):
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    evidence["candidates"][0] = {
        "candidate_id": "cross_paired",
        "model_family": model_family,
        "estimator_identity": {"library": "scikit-learn", "class_name": class_name},
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_arbitrary_family_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    evidence["candidates"][0] = {
        "candidate_id": "svm_candidate",
        "model_family": "support_vector_machine",
        "estimator_identity": {"library": "scikit-learn", "class_name": "SVC"},
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_arbitrary_estimator_class_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    evidence["candidates"][0] = {
        "candidate_id": "xgb_candidate",
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "xgboost", "class_name": "XGBClassifier"},
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


def test_external_model_selection_evidence_producer_criterion_lower_validation_brier_score_rejected():
    schema = _load_json(MODEL_SELECTION_EVIDENCE_SCHEMA_PATH)
    evidence = _multi_family_external_model_selection_evidence()
    evidence["practical_tie"]["tie_break_criteria"][0]["criterion"] = "lower_validation_brier_score"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(evidence))


# --- pipeline/training-metrics.schema.json: partition-role profile --------


def _external_training_metrics(
    *, final_test_completed: bool = True, final_test_evaluation_count: int = 1
) -> dict:
    return {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-01T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "dataset_slug": "telco-customer-churn",
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "row_count": 4225,
            "used_for_fitting": True,
            "used_for_model_selection": True,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "evaluation_count": 5,
            "metrics": [{"name": "average_precision", "value": 0.71}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "row_count": 1056,
            "used_for_fitting": False,
            "used_for_model_selection": True,
            "used_for_threshold_selection": True,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "evaluation_count": 1,
            "metrics": [
                {"name": "average_precision", "value": 0.70},
                {"name": "brier_score", "value": 0.14},
            ],
        },
        "final_test_evaluation": {
            "partition_role": "test",
            "row_count": 1057,
            "used_for_fitting": False,
            "used_for_model_selection": False,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": True,
            "completed": final_test_completed,
            "evaluation_count": final_test_evaluation_count,
            "metrics": [{"name": "average_precision", "value": 0.69}] if final_test_completed else [],
        },
    }


def test_external_training_metrics_train_only_cv_summary_valid():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    doc = _external_training_metrics()
    jsonschema.validate(doc, schema)
    assert doc["cross_validation_summary"]["partition_role"] == "train"


def test_external_training_metrics_validation_used_for_selection_and_threshold_valid():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    doc = _external_training_metrics()
    jsonschema.validate(doc, schema)
    assert doc["validation_evaluation"]["used_for_model_selection"] is True
    assert doc["validation_evaluation"]["used_for_threshold_selection"] is True


def test_external_training_metrics_final_test_sealed_count_one_valid():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    doc = _external_training_metrics(final_test_completed=True, final_test_evaluation_count=1)
    jsonschema.validate(doc, schema)
    _assert_finite_metric_values(
        doc["cross_validation_summary"], doc["validation_evaluation"], doc["final_test_evaluation"]
    )


def test_external_training_metrics_final_test_count_two_rejected():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    doc = _external_training_metrics(final_test_completed=True, final_test_evaluation_count=2)
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_external_training_metrics_final_test_used_for_threshold_rejected():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    doc = _external_training_metrics()
    doc["final_test_evaluation"]["used_for_threshold_selection"] = True
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_external_training_metrics_non_finite_metric_rejected():
    doc = _external_training_metrics()
    doc["validation_evaluation"]["metrics"][0]["value"] = float("nan")
    with pytest.raises(AssertionError):
        _assert_finite_metric_values(doc["validation_evaluation"])


def test_internal_training_metrics_v1_still_valid_unmodified():
    schema = _load_json(TRAINING_METRICS_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)
    doc = _load_json(TELCO_HISTORICAL_METRICS_PATH)
    jsonschema.validate(doc, schema)


# --- pipeline/training-parameter-record.schema.json: external profile -----


def _external_training_parameter_record() -> dict:
    return {
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "record_kind": "training_parameter_record",
        "origin": "validated_external_fitted_model",
        "producer": "external-notebook-pipeline",
        "handoff_lineage_reference": "handoff/telco-customer-churn/2026-08-01/lineage.json",
        "dataset_identity": {"dataset_slug": "telco-customer-churn"},
        "selected_model_id": "hist_gradient_boosting_candidate",
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
        "hyperparameters": {"max_iter": 200, "learning_rate": 0.05, "max_depth": 6},
        "feature_order": ["tenure", "MonthlyCharges", "Contract"],
        "preprocessing_evidence_reference": "external-handoff/telco-customer-churn/preprocessing-evidence.json",
        "positive_class_id": "Yes",
        "serializer_metadata_reference": "external-handoff/telco-customer-churn/serializer-metadata.json",
        "model_artifact_reference": {
            "path": "external-handoff/telco-customer-churn/model.joblib",
            "sha256": _INERT_SHA_MODEL,
        },
        "model_state_fingerprint": _INERT_FINGERPRINT_A,
        "atlas_fit_confirmation": {
            "atlas_fit": False,
            "atlas_tuned": False,
            "atlas_recalibrated": False,
            "atlas_altered": False,
        },
        "raw_partition_confirmation": {"raw_partitions_embedded": False},
    }


def test_external_training_parameter_record_valid_no_atlas_fit():
    schema = _load_json(TRAINING_PARAMETER_RECORD_SCHEMA_PATH)
    doc = _external_training_parameter_record()
    jsonschema.validate(doc, schema)
    assert all(value is False for value in doc["atlas_fit_confirmation"].values())


def test_external_training_parameter_record_does_not_require_atlas_run_id_or_marker():
    doc = _external_training_parameter_record()
    assert "controlled_entrypoint_provenance" not in doc
    assert "training_run_identity" not in doc


def test_external_training_parameter_record_fabricated_atlas_path_rejected():
    schema = _load_json(TRAINING_PARAMETER_RECORD_SCHEMA_PATH)
    doc = _external_training_parameter_record()
    doc["model_artifact_reference"]["path"] = (
        "pipeline/training-runs/telco-customer-churn/train-20260721T124721Z/model.pkl"
    )
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_external_training_parameter_record_missing_fingerprint_rejected():
    schema = _load_json(TRAINING_PARAMETER_RECORD_SCHEMA_PATH)
    doc = _external_training_parameter_record()
    del doc["model_state_fingerprint"]
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_external_training_parameter_record_arbitrary_estimator_callable_rejected():
    schema = _load_json(TRAINING_PARAMETER_RECORD_SCHEMA_PATH)
    doc = _external_training_parameter_record()
    doc["estimator_identity"] = {"library": "scikit-learn", "class_name": "eval('HistGradientBoostingClassifier')"}
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_internal_training_parameter_record_v1_still_valid_unmodified():
    schema = _load_json(TRAINING_PARAMETER_RECORD_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)
    doc = _load_json(TELCO_HISTORICAL_TRAINING_PARAMETER_RECORD_PATH)
    jsonschema.validate(doc, schema)


# --- contracts/inference-bundle.schema.json: external model evidence ------


def _external_inference_bundle() -> dict:
    bundle = copy.deepcopy(_load_json(TELCO_INFERENCE_BUNDLE_PATH))
    del bundle["training_evidence"]
    bundle["model_provenance_origin"] = "validated_external_fitted_model"
    bundle["external_model_evidence"] = {
        "origin": "validated_external_fitted_model",
        "evidence_references": {
            "model_selection_evidence_reference": {
                "path": "external-handoff/telco-customer-churn/model-selection-evidence.json",
                "sha256": _INERT_SHA_MODEL,
                "contract_version": "model-selection-evidence.external-fitted-model.v1",
            },
            "training_parameter_record_reference": {
                "path": "external-handoff/telco-customer-churn/training-parameter-record.json",
                "sha256": _INERT_SHA_MODEL,
                "contract_version": "training-parameter-record.external-fitted-model.v1",
            },
            "training_metrics_reference": {
                "path": "external-handoff/telco-customer-churn/metrics.json",
                "sha256": _INERT_SHA_MODEL,
                "contract_version": "training-metrics.external-fitted-model.v1",
            },
        },
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
        "model_state_fingerprint": _INERT_FINGERPRINT_A,
        "educational_threshold": {
            "value": 0.5,
            "label": "educational",
            "selection_partition": "validation",
            "scenario": "classroom_demo_default_threshold",
        },
        "final_test_completion": {"used_for_threshold_selection": False, "evaluation_count": 1},
        "readiness": {
            "educational_final_model_complete": True,
            "educational_inference_demo_ready": True,
            "operational_modeling_ready": False,
            "operational_validity": "unconfirmed",
            "operational_threshold": {"status": "unresolved", "value": None},
            "operational_prediction_available": False,
        },
    }
    return bundle


def test_external_inference_bundle_educational_ready_operationally_unresolved_valid():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    jsonschema.validate(bundle, schema)
    readiness = bundle["external_model_evidence"]["readiness"]
    assert readiness["educational_final_model_complete"] is True
    assert readiness["educational_inference_demo_ready"] is True
    assert readiness["operational_modeling_ready"] is False
    assert readiness["operational_validity"] == "unconfirmed"
    assert readiness["operational_threshold"] == {"status": "unresolved", "value": None}
    assert readiness["operational_prediction_available"] is False


def test_external_inference_bundle_educational_threshold_selected_on_validation_valid():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    jsonschema.validate(bundle, schema)
    assert bundle["external_model_evidence"]["educational_threshold"]["selection_partition"] == "validation"


def test_external_inference_bundle_operational_prediction_true_while_unconfirmed_rejected():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["external_model_evidence"]["readiness"]["operational_prediction_available"] = True
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_numeric_operational_threshold_while_unresolved_rejected():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["external_model_evidence"]["readiness"]["operational_threshold"] = {
        "status": "unresolved",
        "value": 0.42,
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_educational_threshold_cannot_be_labeled_operational():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["external_model_evidence"]["educational_threshold"]["label"] = "operational"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_test_partition_cannot_be_threshold_selection_partition():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["external_model_evidence"]["educational_threshold"]["selection_partition"] = "test"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_final_test_evaluation_count_above_one_rejected():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["external_model_evidence"]["final_test_completion"]["evaluation_count"] = 2
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_forbids_training_evidence_alongside_external_origin():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    bundle = _external_inference_bundle()
    bundle["training_evidence"] = copy.deepcopy(_load_json(TELCO_INFERENCE_BUNDLE_PATH))["training_evidence"]
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(bundle))


def test_external_inference_bundle_model_state_fingerprint_mismatch_across_evidence_rejected():
    param_record = _external_training_parameter_record()
    param_record["model_state_fingerprint"] = _INERT_FINGERPRINT_B
    bundle = _external_inference_bundle()
    with pytest.raises(AssertionError):
        _assert_model_state_fingerprint_consistency(
            bundle["external_model_evidence"]["model_state_fingerprint"],
            param_record["model_state_fingerprint"],
        )


def test_external_inference_bundle_model_state_fingerprint_consistent_across_evidence():
    param_record = _external_training_parameter_record()
    selection_evidence = _external_model_selection_evidence()
    bundle = _external_inference_bundle()
    _assert_model_state_fingerprint_consistency(
        bundle["external_model_evidence"]["model_state_fingerprint"],
        param_record["model_state_fingerprint"],
        selection_evidence["hashes"]["model_state_fingerprint"],
    )


def test_historical_telco_inference_bundle_still_valid_after_schema_evolution():
    schema = _load_json(INFERENCE_BUNDLE_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)
    doc = _load_json(TELCO_INFERENCE_BUNDLE_PATH)
    jsonschema.validate(doc, schema)
    assert "model_provenance_origin" not in doc
    assert "external_model_evidence" not in doc
    assert "training_evidence" in doc


# --- Project Spec S0216: bounded fixed hist_gradient_boosting configuration
# and explicit multiclass aggregate metric vocabulary -------------------


def _fixed_hgb_hyperparameters(**overrides) -> dict:
    base = {
        "class_weight": None,
        "l2_regularization": 0.0,
        "learning_rate": 0.05,
        "max_iter": 250,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
    }
    base.update(overrides)
    return base


def _fixed_configuration_contract() -> dict:
    contract = _valid_contract()
    contract["primary_metric"] = "f1_macro"
    contract["secondary_metrics"] = ["balanced_accuracy", "f1_weighted", "recall_macro", "accuracy", "log_loss"]
    contract["modeling_constraints"] = {
        "allowed_model_families": ["hist_gradient_boosting"],
        "no_automl": True,
        "selection_mode": "fixed_configuration",
        "fixed_model_configuration": {
            "model_family": "hist_gradient_boosting",
            "hyperparameters": _fixed_hgb_hyperparameters(),
        },
    }
    return contract


def test_fixed_configuration_hgb_contract_is_schema_valid():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(_fixed_configuration_contract(), schema)


def test_multiclass_aggregate_metric_ids_are_schema_valid():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    jsonschema.validate(contract, schema)
    for metric in ("f1_macro", "f1_weighted", "precision_macro", "recall_macro"):
        contract["primary_metric"] = metric
        jsonschema.validate(contract, schema)


def test_selection_mode_evaluate_allowed_families_still_valid_without_fixed_configuration():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["modeling_constraints"]["selection_mode"] = "evaluate_allowed_families"
    jsonschema.validate(contract, schema)


def test_selection_mode_fixed_configuration_requires_fixed_model_configuration():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    del contract["modeling_constraints"]["fixed_model_configuration"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_fixed_model_configuration_without_selection_mode_fixed_configuration_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    contract["modeling_constraints"]["fixed_model_configuration"] = {
        "model_family": "hist_gradient_boosting",
        "hyperparameters": _fixed_hgb_hyperparameters(),
    }

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_hgb_hyperparameters_missing_required_field_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    del contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["learning_rate"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_hgb_hyperparameters_unsupported_field_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_hgb_hyperparameters_never_expose_callable_or_module_strings():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["learning_rate"] = (
        "sklearn.ensemble.HistGradientBoostingClassifier"
    )

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_hgb_fixed_model_configuration_only_accepts_hist_gradient_boosting_family():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["model_family"] = "gradient_boosting"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(contract))
    assert errors


def test_native_multiclass_result_semantics_still_conforms_to_result_semantics_union():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_configuration_contract()
    contract["result_semantics"] = {
        "schema_version": "multiclass-result-semantics.v1",
        "problem_type": "multiclass_classification",
        "classes": [
            {"class_id": "a", "display_label": "A"},
            {"class_id": "b", "display_label": "B"},
            {"class_id": "c", "display_label": "C"},
        ],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
    }
    jsonschema.validate(contract, schema)


# --- Project Spec S0231: continuous-regression hist_gradient_boosting bounded
# fixed configuration, discriminated from the S0216 classification shape by
# result_semantics.problem_type --------------------------------------------


def _fixed_hgb_regression_hyperparameters(**overrides) -> dict:
    base = {
        "l2_regularization": 0.0,
        "learning_rate": 0.05,
        "max_iter": 250,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
    }
    base.update(overrides)
    return base


def _fixed_hgb_regression_contract() -> dict:
    contract = _valid_contract()
    contract["primary_metric"] = "r2"
    contract["secondary_metrics"] = ["mae", "rmse"]
    contract["split_policy"] = {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15}
    contract["modeling_constraints"] = {
        "allowed_model_families": ["hist_gradient_boosting"],
        "no_automl": True,
        "selection_mode": "fixed_configuration",
        "fixed_model_configuration": {
            "model_family": "hist_gradient_boosting",
            "hyperparameters": _fixed_hgb_regression_hyperparameters(),
        },
    }
    contract["result_semantics"] = _valid_continuous_regression_result_semantics()
    return contract


def test_fixed_configuration_hgb_continuous_regression_contract_is_schema_valid():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(_fixed_hgb_regression_contract(), schema)


def test_hgb_continuous_regression_rejects_class_weight():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["class_weight"] = None

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_hgb_continuous_regression_rejects_random_state():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["random_state"] = 7

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_hgb_continuous_regression_missing_required_field_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    del contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["learning_rate"]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_hgb_continuous_regression_unknown_field_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_hgb_continuous_regression_accepts_optional_early_stopping():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["early_stopping"] = "auto"
    jsonschema.validate(contract, schema)


def test_existing_multiclass_hgb_shape_remains_valid_alongside_regression_addition():
    """S0231 must not weaken the existing S0216 multiclass HGB shape: absent
    result_semantics (or a non-continuous_regression result_semantics) still
    requires class_weight, exactly as before."""
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(_fixed_configuration_contract(), schema)

    contract = _fixed_configuration_contract()
    del contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["class_weight"]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_hgb_regression_hyperparameters_never_expose_callable_or_module_strings():
    schema = _load_json(SCHEMA_PATH)
    contract = _fixed_hgb_regression_contract()
    contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["learning_rate"] = (
        "sklearn.ensemble.HistGradientBoostingRegressor"
    )

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


# ---------------------------------------------------------------------------
# execution_contract.v2 -- strict univariate-forecasting branch
# (Project Spec S0243). Fixtures are synthetic and dataset-neutral, matching
# the "campaign-response"/"bank-marketing" precedent established above -- no
# Nottingham-specific slug/path/field/cadence/horizon/seasonal period.
# ---------------------------------------------------------------------------


def _valid_forecasting_result_semantics() -> dict:
    return {
        "schema_version": "univariate-forecasting-result-semantics.v1",
        "problem_type": "univariate_forecasting",
        "primary_output": "forecast_series",
        "output_structure": "ordered_forecast_points",
        "forecast_value_kind": "continuous_numeric",
        "forecast_count_source": "forecast_horizon",
    }


def _valid_forecasting_temporal_evaluation() -> dict:
    return {
        "preparation_schema_version": "candidate-preparation-recipe.v2",
        "backtesting_mode": "expanding_window",
        "fold_count": 5,
        "final_holdout_prospectively_sealed": True,
        "final_holdout_used_for_backtesting": False,
        "final_holdout_used_for_model_selection": False,
        "random_shuffle_performed": False,
        "future_targets_used_for_fold_fit": False,
        "validation_targets_fed_back_within_fold": False,
        "preprocessing_fit_on_validation_or_future": False,
    }


def _valid_forecasting_evaluation_policy() -> dict:
    return {
        "primary_metric": {"metric_id": "mae", "direction": "lower_is_better"},
        "secondary_metrics": [
            {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": 7},
        ],
    }


def _valid_execution_contract_v2() -> dict:
    return {
        "contract_version": "execution_contract.v2",
        "dataset_id": "synthetic-series",
        "problem_type": "univariate_forecasting",
        "target_column": "demand",
        "time_index_column": "period",
        "index_value_kind": "calendar_period",
        "frequency": "monthly",
        "source_exogenous_predictors": "forbidden",
        "forecast_horizon": 6,
        "temporal_evaluation": _valid_forecasting_temporal_evaluation(),
        "evaluation_policy": _valid_forecasting_evaluation_policy(),
        "result_semantics": _valid_forecasting_result_semantics(),
        "random_seed": 0,
    }


def test_valid_execution_contract_v2_forecasting_validates():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(_valid_execution_contract_v2(), schema)


def test_execution_contract_v2_random_seed_null_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["random_seed"] = None
    jsonschema.validate(contract, schema)


def test_execution_contract_v2_wrong_contract_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["contract_version"] = "execution_contract.v3"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_wrong_problem_type_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["problem_type"] = "continuous_regression"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


@pytest.mark.parametrize(
    "field",
    ["target_column", "time_index_column", "frequency", "forecast_horizon", "index_value_kind"],
)
def test_execution_contract_v2_missing_required_identity_field_rejected(field):
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    del contract[field]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_horizon_zero_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["forecast_horizon"] = 0

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_horizon_negative_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["forecast_horizon"] = -3

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_feature_columns_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["feature_columns"] = ["age", "channel"]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_split_policy_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["split_policy"] = {
        "strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15,
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_modeling_constraints_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["modeling_constraints"] = {"allowed_model_families": ["gradient_boosting"]}

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_full_fold_schedule_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["temporal_evaluation"]["fold_schedule"] = [
        {
            "fold_index": 1, "training_observations": 36, "forecast_origin": "2023-01",
            "validation_start": "2023-02", "validation_end": "2023-07", "validation_observations": 6,
        }
    ]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_actual_forecast_points_payload_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["forecast_points"] = [{"period": "2026-01", "forecast": 42.0}]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_scalar_predicted_value_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["predicted_value"] = 42.0

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_classification_only_result_fields_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["positive_class"] = {"class_id": "Yes", "event_label": "Churn"}

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_confidence_interval_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["confidence_interval"] = {"lower": 10.0, "upper": 20.0}

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_model_descriptor_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["model_descriptor"] = {"family": "arima"}

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_wrong_result_semantics_schema_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["result_semantics"]["schema_version"] = "univariate-forecasting-result-semantics.v2"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_source_exogenous_predictors_must_be_forbidden():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["source_exogenous_predictors"] = "allowed"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_temporal_evaluation_wrong_backtesting_mode_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["temporal_evaluation"]["backtesting_mode"] = "k_fold"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_temporal_evaluation_final_holdout_used_for_backtesting_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["temporal_evaluation"]["final_holdout_used_for_backtesting"] = True

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_evaluation_policy_mae_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "mae", "direction": "lower_is_better"},
        "secondary_metrics": [],
    }
    jsonschema.validate(contract, schema)


def test_execution_contract_v2_evaluation_policy_rmse_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "rmse", "direction": "lower_is_better"},
        "secondary_metrics": [],
    }
    jsonschema.validate(contract, schema)


def test_execution_contract_v2_evaluation_policy_seasonal_mase_with_positive_period_validates():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": 12},
        "secondary_metrics": [],
    }
    jsonschema.validate(contract, schema)


def test_execution_contract_v2_evaluation_policy_seasonal_mase_without_period_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "seasonal_mase", "direction": "lower_is_better"},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_evaluation_policy_seasonal_mase_zero_period_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": 0},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_evaluation_policy_seasonal_mase_negative_period_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": -1},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_evaluation_policy_mae_with_seasonal_period_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "mae", "direction": "lower_is_better", "seasonal_period": 12},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_evaluation_policy_rmse_with_seasonal_period_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": "rmse", "direction": "lower_is_better", "seasonal_period": 12},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


@pytest.mark.parametrize("unknown_metric_id", ["mape", "smape", "roc_auc", "accuracy", "r2"])
def test_execution_contract_v2_evaluation_policy_unknown_metric_rejected(unknown_metric_id):
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["evaluation_policy"] = {
        "primary_metric": {"metric_id": unknown_metric_id, "direction": "lower_is_better"},
        "secondary_metrics": [],
    }

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_mixed_v1_v2_document_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_contract()
    v2_fields = _valid_execution_contract_v2()
    contract["problem_type"] = v2_fields["problem_type"]
    contract["time_index_column"] = v2_fields["time_index_column"]
    contract["forecast_horizon"] = v2_fields["forecast_horizon"]

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_unknown_execution_contract_version_rejected():
    schema = _load_json(SCHEMA_PATH)
    contract = _valid_execution_contract_v2()
    contract["contract_version"] = "execution_contract.v0"

    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))


def test_execution_contract_v2_and_v1_are_disjoint_branches():
    """A schema-valid v1 document must never also validate as v2, and vice
    versa -- oneOf must select exactly one branch."""
    schema = _load_json(SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    assert not list(validator.iter_errors(_valid_contract()))
    assert not list(validator.iter_errors(_valid_execution_contract_v2()))

    v1_as_v2_candidate = dict(_valid_contract())
    v1_as_v2_candidate["problem_type"] = "univariate_forecasting"
    assert list(validator.iter_errors(v1_as_v2_candidate))
