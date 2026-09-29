"""pipeline/model_families.py is the model-family authority.

Every per-layer closed family set is derived from it or proven equal to it.
Closed sets stay explicit: a family is supported only for the problem types
the authority declares -- nothing is widened to "every family everywhere".
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import contract_derivation, generate_inference_bundle, model_families, training  # noqa: E402
from runtime import inference as runtime_inference  # noqa: E402

BINARY = model_families.BINARY_CLASSIFICATION
MULTICLASS = model_families.MULTICLASS_CLASSIFICATION
REGRESSION = model_families.CONTINUOUS_REGRESSION
FORECASTING = model_families.UNIVARIATE_FORECASTING
# Retired, never-trainable vocabulary kept only so historical artifacts stay
# schema-valid.
HISTORICAL_ONLY_FAMILIES = {"xgboost", "lightgbm"}


def _schema(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def test_closed_support_sets_are_exactly_the_governed_ones():
    # Pinned expectations: consolidation must not widen (or narrow) support.
    assert model_families.native_trainable_family_ids(BINARY, model_families.EVALUATE_ALLOWED_FAMILIES) == (
        "logistic_regression", "gradient_boosting", "random_forest",
    )
    assert model_families.native_trainable_family_ids(BINARY, model_families.FIXED_CONFIGURATION) == (
        "hist_gradient_boosting",
    )
    assert model_families.native_trainable_family_ids(MULTICLASS) == ("hist_gradient_boosting",)
    assert model_families.native_trainable_family_ids(REGRESSION) == (
        "gradient_boosting", "random_forest", "hist_gradient_boosting",
    )
    assert model_families.native_trainable_family_ids(FORECASTING) == ("deterministic_seasonal_trend_ols",)
    assert model_families.governed_result_family_ids(BINARY) == {
        "logistic_regression", "gradient_boosting", "random_forest", "hist_gradient_boosting",
    }
    assert model_families.governed_result_family_ids(MULTICLASS) == {
        "logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting",
    }
    assert model_families.governed_result_family_ids(REGRESSION) == {
        "gradient_boosting", "random_forest", "hist_gradient_boosting",
    }


def test_not_every_family_is_supported_for_every_problem_type():
    assert "logistic_regression" not in model_families.governed_result_family_ids(REGRESSION)
    assert "gradient_boosting" not in model_families.governed_result_family_ids(MULTICLASS)
    assert "decision_tree" not in model_families.native_trainable_family_ids_for_any(
        model_families.TABULAR_PROBLEM_TYPES
    )
    assert not model_families.MODEL_FAMILIES["dummy_prior"].native_training


@pytest.mark.parametrize("family", sorted(HISTORICAL_ONLY_FAMILIES))
def test_untrainable_families_are_absent_from_every_active_authority(family):
    assert family not in model_families.MODEL_FAMILIES
    assert family not in training.SUPPORTED_MODEL_FAMILIES
    assert family not in contract_derivation._TRAINING_POLICY_MODEL_FAMILY_VOCABULARY
    assert family not in generate_inference_bundle.SUPPORTED_MODEL_FAMILIES
    assert family not in generate_inference_bundle.MODEL_FAMILY_DISPLAY_NAMES


def test_training_support_is_derived():
    assert training.SUPPORTED_MODEL_FAMILIES == model_families.native_trainable_family_ids(
        BINARY, model_families.EVALUATE_ALLOWED_FAMILIES
    )


def test_contract_vocabulary_is_derived():
    assert contract_derivation._TRAINING_POLICY_MODEL_FAMILY_VOCABULARY == (
        model_families.native_trainable_family_ids_for_any(model_families.TABULAR_PROBLEM_TYPES)
    )
    assert contract_derivation._CONTINUOUS_REGRESSION_FIXED_FAMILY_VOCABULARY == set(
        model_families.native_trainable_family_ids(REGRESSION, model_families.FIXED_CONFIGURATION)
    )


def test_bundle_generation_support_is_derived():
    assert generate_inference_bundle.SUPPORTED_MODEL_FAMILIES == (
        model_families.native_trainable_family_ids_for_any((BINARY, MULTICLASS))
    )
    assert generate_inference_bundle.CONTINUOUS_REGRESSION_MODEL_FAMILIES == set(
        model_families.native_trainable_family_ids(REGRESSION)
    )
    assert generate_inference_bundle.MODEL_FAMILY_DISPLAY_NAMES == model_families.display_names()


def test_runtime_result_family_sets_match_authority():
    assert set(runtime_inference._GOVERNED_RESULT_MODEL_FAMILIES) == model_families.governed_result_family_ids(BINARY)
    assert set(runtime_inference._GOVERNED_MULTICLASS_MODEL_FAMILIES) == (
        model_families.governed_result_family_ids(MULTICLASS)
    )
    assert set(runtime_inference._GOVERNED_CONTINUOUS_REGRESSION_MODEL_FAMILIES) == (
        model_families.governed_result_family_ids(REGRESSION)
    )


def test_inference_bundle_schema_enums_match_authority():
    defs = _schema("contracts/inference-bundle.schema.json")["$defs"]
    tabular_results = set().union(
        *(model_families.governed_result_family_ids(p) for p in model_families.TABULAR_PROBLEM_TYPES)
    )
    assert set(defs["inference_bundle_v1"]["properties"]["runtime_execution"]["properties"]["model_family"]["enum"]) == (
        tabular_results
    )
    for def_name, problem_type in (
        ("binary_result_semantics", BINARY),
        ("multiclass_result_semantics", MULTICLASS),
        ("continuous_regression_result_semantics", REGRESSION),
    ):
        family_enum = defs[def_name]["properties"]["model_descriptor"]["properties"]["model_family"]["enum"]
        assert set(family_enum) == model_families.governed_result_family_ids(problem_type), def_name
    assert {defs["inference_bundle_v2"]["properties"]["runtime_execution"]["properties"]["model_family"]["const"]} == (
        model_families.governed_result_family_ids(FORECASTING)
    )


def test_result_schema_enums_match_authority():
    multiclass_result = _schema("contracts/multiclass-classification-result.schema.json")
    assert set(multiclass_result["properties"]["model_descriptor"]["properties"]["model_family"]["enum"]) == (
        model_families.governed_result_family_ids(MULTICLASS)
    )


def test_execution_contract_schema_matches_authority_plus_documented_historical_vocabulary():
    definitions = _schema("contracts/execution-contract.schema.json")["definitions"]
    allowed = set(definitions["modeling_constraints"]["properties"]["allowed_model_families"]["items"]["enum"])
    active = set(contract_derivation._TRAINING_POLICY_MODEL_FAMILY_VOCABULARY)
    assert active <= allowed
    assert allowed - active == HISTORICAL_ONLY_FAMILIES
    fixed = set(definitions["fixed_model_configuration"]["properties"]["model_family"]["enum"])
    assert fixed == model_families.native_trainable_family_ids_for_any(
        model_families.TABULAR_PROBLEM_TYPES, model_families.FIXED_CONFIGURATION
    )


def test_training_record_schema_enums_match_authority():
    defs = _schema("pipeline/training-parameter-record.schema.json")["$defs"]
    assert set(defs["internal_run_record_v1"]["properties"]["training_parameters"]["properties"]["model_family"]["enum"]) == (
        set(model_families.native_trainable_family_ids(BINARY, model_families.EVALUATE_ALLOWED_FAMILIES))
    )
    assert set(defs["internal_run_record_v3"]["properties"]["training_parameters"]["properties"]["model_family"]["enum"]) == (
        set(model_families.native_trainable_family_ids(REGRESSION))
    )
    assert {defs["internal_run_record_v2"]["properties"]["training_parameters"]["properties"]["model_family"]["const"]} == (
        set(model_families.native_trainable_family_ids(MULTICLASS))
    )
    assert {defs["internal_run_record_v4"]["properties"]["training_parameters"]["properties"]["model_family"]["const"]} == (
        set(model_families.native_trainable_family_ids(FORECASTING))
    )
    assert {defs["internal_run_record_v5"]["properties"]["training_parameters"]["properties"]["model_family"]["const"]} == (
        set(model_families.native_trainable_family_ids(BINARY, model_families.FIXED_CONFIGURATION))
    )
    model_selection = _schema("pipeline/model-selection-evidence.schema.json")["$defs"]["model_family"]["enum"]
    assert set(model_selection) == set(
        model_families.native_trainable_family_ids(BINARY, model_families.EVALUATE_ALLOWED_FAMILIES)
    )


def test_every_sklearn_family_resolves_its_declared_estimators():
    for family_id, family in model_families.MODEL_FAMILIES.items():
        for task_type in family.estimators:
            assert model_families.estimator_class(family_id, task_type).__name__
