import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.contract_derivation import (
    EXECUTION_CONTRACT_DRAFT_CONTRACT_VERSION,
    EXECUTION_CONTRACT_V2_CONTRACT_VERSION,
    ExecutionContractV2ValidationError,
    TrainingPolicyValidationError,
    _build_execution_contract,
    _build_execution_contract_materialization_evidence,
    _build_execution_contract_v2_materialization_evidence,
    _check_safety,
    _derive_public_contract,
    _derive_public_feature,
    _derive_public_options,
    _fresh_label,
    _materialize_training_policy_fields,
    _validate_hgb_regression_hyperparameters,
    _validate_training_policy_intent,
    categorical_known_values,
    categorical_scalar_type,
    categorical_validation_behavior,
    condition_value_type_compatible,
    conditional_policy_errors,
    materialize_execution_contract,
    project_execution_contract_draft,
)
from pipeline.discovery_evidence import (
    build_binary_result_semantics_intent,
    build_continuous_regression_result_semantics_intent,
    build_multiclass_result_semantics_intent,
    build_univariate_forecasting_evaluation_policy_intent,
    build_univariate_forecasting_result_semantics_intent,
    build_univariate_forecasting_training_policy_intent,
)


def _categorical_feature(values=("admin", "blue-collar", "technician"), **overrides):
    feature = {
        "name": "job",
        "type": "categorical",
        "required": True,
        "description": "Type of job held by the client.",
        "domain_constraints": {"values": list(values)},
    }
    feature.update(overrides)
    return feature


def test_categorical_feature_with_values_produces_safe_options() -> None:
    feature = _categorical_feature(values=("admin", "blue-collar", "technician"))
    public = _derive_public_feature(feature, display_order=1)
    assert public["options"] == [
        {"value": "admin", "label": _fresh_label("admin")},
        {"value": "blue-collar", "label": _fresh_label("blue-collar")},
        {"value": "technician", "label": _fresh_label("technician")},
    ]


def test_options_preserve_source_declaration_order() -> None:
    feature = _categorical_feature(values=("zeta", "alpha", "mu"))
    public = _derive_public_feature(feature, display_order=1)
    assert [option["value"] for option in public["options"]] == ["zeta", "alpha", "mu"]


def test_options_entries_carry_only_value_and_label_keys() -> None:
    feature = _categorical_feature()
    public = _derive_public_feature(feature, display_order=1)
    for option in public["options"]:
        assert set(option.keys()) == {"value", "label"}


def test_categorical_feature_without_domain_constraints_has_no_options_key() -> None:
    feature = _categorical_feature()
    del feature["domain_constraints"]
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_categorical_feature_with_empty_values_has_no_options_key() -> None:
    feature = _categorical_feature(values=())
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_numeric_feature_never_has_options_key() -> None:
    feature = {
        "name": "age",
        "type": "numeric",
        "required": True,
        "domain_constraints": {"min": 18, "max": 95},
    }
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_boolean_feature_never_has_options_key() -> None:
    feature = {"name": "employed", "type": "boolean", "required": False}
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_derive_public_options_returns_none_for_non_categorical_feature() -> None:
    feature = {"name": "age", "type": "numeric", "domain_constraints": {"min": 0, "max": 1}}
    assert _derive_public_options(feature) is None


# ---------------------------------------------------------------------------
# Project Spec S0156: categorical/conditional-policy helpers and their
# effect on public projection.
# ---------------------------------------------------------------------------


def test_open_categorical_known_values_produce_typed_options_with_select_value_type():
    feature = {
        "name": "account_id_flag",
        "type": "categorical",
        "required": True,
        "domain_constraints": {
            "known_values": [0, 1],
            "categorical_value_type": "integer",
            "validation_behavior": "reject_unknown",
        },
    }
    public = _derive_public_feature(feature, display_order=1)
    assert public["options"] == [{"value": 0, "label": "0"}, {"value": 1, "label": "1"}]
    assert public["select_value_type"] == "integer"


def test_string_open_categorical_projects_string_select_value_type():
    feature = {
        "name": "plan_type",
        "type": "categorical",
        "required": True,
        "domain_constraints": {
            "known_values": ["basic", "pro"],
            "categorical_value_type": "string",
            "validation_behavior": "ignore_and_report",
        },
    }
    public = _derive_public_feature(feature, display_order=1)
    assert public["options"] == [
        {"value": "basic", "label": "Basic"},
        {"value": "pro", "label": "Pro"},
    ]
    assert public["select_value_type"] == "string"


def test_legacy_categorical_feature_projects_string_select_value_type():
    feature = _categorical_feature()
    public = _derive_public_feature(feature, display_order=1)
    assert public["select_value_type"] == "string"


def test_numeric_and_boolean_features_never_carry_select_value_type():
    numeric = {"name": "age", "type": "numeric", "required": True, "domain_constraints": {"min": 0, "max": 1}}
    boolean = {"name": "employed", "type": "boolean", "required": False}
    assert "select_value_type" not in _derive_public_feature(numeric, display_order=1)
    assert "select_value_type" not in _derive_public_feature(boolean, display_order=1)


def test_conditional_blank_policy_projects_presentation_metadata_only():
    feature = {
        "name": "total_amount",
        "type": "numeric",
        "required": True,
        "input_policy": {
            "conditional_blank_normalization": {
                "accepted_representation": "blank_string_after_trim",
                "when": {"field": "tenure_months", "operator": "equals", "value": 0},
                "materialized_value": 0.0,
                "otherwise": "reject",
                "null_behavior": "reject",
            }
        },
    }
    public = _derive_public_feature(feature, display_order=1)
    assert public["conditional_blank_policy"] == {"accepted_representation": "blank_string_after_trim"}
    # The condition field/operator/comparison value and the materialized
    # value must never leak into the public projection.
    assert "when" not in public["conditional_blank_policy"]
    assert "materialized_value" not in public["conditional_blank_policy"]


def test_feature_without_input_policy_has_no_conditional_blank_policy_key():
    feature = {"name": "age", "type": "numeric", "required": True}
    public = _derive_public_feature(feature, display_order=1)
    assert "conditional_blank_policy" not in public


def test_categorical_scalar_type_defaults_to_string_when_undeclared():
    assert categorical_scalar_type(None) == "string"
    assert categorical_scalar_type({"values": ["a", "b"]}) == "string"
    assert categorical_scalar_type({"categorical_value_type": "integer"}) == "integer"


def test_categorical_known_values_falls_back_to_legacy_values():
    assert categorical_known_values({"values": ["a", "b"]}) == ["a", "b"]
    assert categorical_known_values({"known_values": [1, 2]}) == [1, 2]
    assert categorical_known_values({}) is None


def test_categorical_validation_behavior_defaults_to_reject_unknown():
    assert categorical_validation_behavior(None) == "reject_unknown"
    assert categorical_validation_behavior({"values": ["a"]}) == "reject_unknown"
    assert categorical_validation_behavior({"validation_behavior": "ignore_and_report"}) == "ignore_and_report"


def test_condition_value_type_compatible_across_feature_types():
    assert condition_value_type_compatible(0, "numeric", {}) is True
    assert condition_value_type_compatible(True, "numeric", {}) is False
    assert condition_value_type_compatible(True, "boolean", {}) is True
    assert condition_value_type_compatible(0, "boolean", {}) is False
    assert condition_value_type_compatible(
        "basic", "categorical", {"domain_constraints": {"categorical_value_type": "string"}}
    ) is True
    assert condition_value_type_compatible(
        1, "categorical", {"domain_constraints": {"categorical_value_type": "integer"}}
    ) is True
    assert condition_value_type_compatible(
        True, "categorical", {"domain_constraints": {"categorical_value_type": "integer"}}
    ) is False


def test_conditional_policy_errors_detects_self_reference_and_unknown_field():
    feature_columns = ["total_amount", "tenure_months"]
    feature_definitions = {
        "total_amount": {
            "type": "numeric",
            "input_policy": {
                "conditional_blank_normalization": {
                    "accepted_representation": "blank_string_after_trim",
                    "when": {"field": "total_amount", "operator": "equals", "value": 0},
                    "materialized_value": 0.0,
                    "otherwise": "reject",
                    "null_behavior": "reject",
                }
            },
        },
        "tenure_months": {"type": "numeric"},
    }
    errors = conditional_policy_errors(feature_columns, feature_definitions)
    assert any("reference itself" in e for e in errors)

    feature_definitions["total_amount"]["input_policy"]["conditional_blank_normalization"]["when"][
        "field"
    ] = "not_a_real_field"
    errors = conditional_policy_errors(feature_columns, feature_definitions)
    assert any("not a declared feature column" in e for e in errors)


def test_conditional_policy_errors_detects_type_incompatible_comparison_value():
    feature_columns = ["total_amount", "plan_type"]
    feature_definitions = {
        "total_amount": {
            "type": "numeric",
            "input_policy": {
                "conditional_blank_normalization": {
                    "accepted_representation": "blank_string_after_trim",
                    "when": {"field": "plan_type", "operator": "equals", "value": 0},
                    "materialized_value": 0.0,
                    "otherwise": "reject",
                    "null_behavior": "reject",
                }
            },
        },
        "plan_type": {
            "type": "categorical",
            "domain_constraints": {"categorical_value_type": "string", "known_values": ["basic"]},
        },
    }
    errors = conditional_policy_errors(feature_columns, feature_definitions)
    assert any("incompatible" in e for e in errors)


def test_conditional_policy_errors_empty_for_valid_condition():
    feature_columns = ["total_amount", "tenure_months"]
    feature_definitions = {
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
    }
    assert conditional_policy_errors(feature_columns, feature_definitions) == []


def test_derived_contract_with_options_passes_safety_check() -> None:
    runtime_contract = {
        "schema_version": "1.0.0",
        "features": [
            {"name": "age", "type": "numeric", "required": True, "domain_constraints": {"min": 17, "max": 98}},
            _categorical_feature(),
            {"name": "employed", "type": "boolean", "required": False},
        ],
    }
    public_contract = _derive_public_contract(runtime_contract)
    assert _check_safety(public_contract) == []
    job_feature = next(f for f in public_contract["features"] if f["name"] == "job")
    assert job_feature["options"]
    age_feature = next(f for f in public_contract["features"] if f["name"] == "age")
    assert "options" not in age_feature


# ---------------------------------------------------------------------------
# Execution contract draft projection (Project Spec S0014)
#
# All fixtures below are small, synthetic in-memory objects — none of these
# tests depend on the real Telco CSV.
# ---------------------------------------------------------------------------


def _telco_like_modeling_intent(**overrides):
    """A synthetic `dataset_modeling_intent.v1`-shaped object, Telco-flavored
    but built entirely from literal values (no CSV, no notebook execution)."""
    intent = {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "telco-customer-churn",
            "dataset_source_ref": "data/raw/telco-customer-churn.csv",
        },
        "authoring_source": {
            "authoring_notebook_ref": (
                "notebooks/datasets/telco-customer-churn/dataset_integration.ipynb"
            ),
            "reduced_discovery_evidence_ref": None,
        },
        "target_intent": {
            "target_column": "Churn",
            "task_type": "binary_classification",
            "observed_labels": ["No", "Yes"],
            "positive_label_candidate": "Yes",
            "observed_target_distribution": {"No": 5174, "Yes": 1869},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": "customerID", "reason": "identifier_candidate_excluded_from_features"}
        ],
        "initial_feature_candidates": ["gender", "SeniorCitizen", "MonthlyCharges", "TotalCharges"],
        "feature_review_notes": {
            "TotalCharges": (
                "Raw blank string values observed; requires explicit blank-value "
                "handling before execution-contract projection."
            ),
            "SeniorCitizen": (
                "Raw representation is numeric (0/1) but the semantic domain is "
                "binary; requires explicit type intent before encoding."
            ),
        },
        "feature_type_intent": [
            {"name": "gender", "type_intent": "requires_review"},
            {"name": "SeniorCitizen", "type_intent": "requires_review"},
            {"name": "MonthlyCharges", "type_intent": "requires_review"},
            {"name": "TotalCharges", "type_intent": "requires_review"},
        ],
        "blank_value_policy_candidates": {"TotalCharges": "unresolved_pending_review"},
        "metric_candidates": [],
        "split_policy_candidate": None,
        "open_questions": [
            "Final 'TotalCharges' blank-value handling policy is not yet decided.",
        ],
        "modeling_intent_boundary_confirmations": {
            "is_execution_contract": False,
            "is_runtime_contract": False,
            "is_public_contract": False,
            "is_release_candidate_input": False,
            "is_publisher_input": False,
            "is_registry_artifact": False,
            "is_api_fixture": False,
            "is_ui_fixture": False,
            "model_training_performed": False,
        },
        "generated_at": "2026-07-09T00:00:00+00:00",
    }
    intent.update(overrides)
    return intent


def test_draft_projection_has_distinct_artifact_identity_from_execution_contract() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["artifact_type"] == "execution_contract_draft"
    assert draft["contract_version"] == EXECUTION_CONTRACT_DRAFT_CONTRACT_VERSION
    assert draft["contract_version"] != "execution_contract.v1"
    assert draft["draft_status"] == "not_execution_ready"


def test_draft_projection_records_dataset_identity() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["dataset_identity"]["dataset_slug"] == "telco-customer-churn"
    assert draft["dataset_identity"]["dataset_source_ref"] == "data/raw/telco-customer-churn.csv"


def test_draft_projection_records_authoring_notebook_traceability() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["authoring_traceability"]["authoring_notebook_ref"] == (
        "notebooks/datasets/telco-customer-churn/dataset_integration.ipynb"
    )
    assert draft["authoring_traceability"]["source_modeling_intent_contract_version"] == (
        "dataset_modeling_intent.v1"
    )


def test_draft_projection_records_target_intent() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["target_column"] == "Churn"
    assert draft["target_intent"]["target_column"] == "Churn"
    assert draft["target_intent"]["observed_labels"] == ["No", "Yes"]
    assert draft["target_intent"]["observed_target_distribution"] == {"No": 5174, "Yes": 1869}
    assert draft["target_intent"]["positive_label_candidate"] == "Yes"


def test_draft_projection_excludes_identifier_from_feature_columns() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert "customerID" not in draft["feature_columns"]
    assert draft["ignored_columns"] == ["customerID"]
    assert draft["identifier_and_ignored_columns"] == [
        {"name": "customerID", "reason": "identifier_candidate_excluded_from_features"}
    ]


def test_draft_projection_feature_columns_match_initial_feature_candidates_order() -> None:
    intent = _telco_like_modeling_intent()
    draft = project_execution_contract_draft(intent)
    assert draft["feature_columns"] == intent["initial_feature_candidates"]


def test_draft_projection_flags_total_charges_as_blocking() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert "TotalCharges" in draft["blank_value_policy_candidates"]
    assert any(
        "TotalCharges" in reason and "blank-value" in reason
        for reason in draft["execution_readiness"]["blocking_reasons"]
    )


def test_draft_projection_flags_senior_citizen_as_requiring_review() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["feature_definitions"]["SeniorCitizen"]["type_intent"] == "requires_review"
    assert any(
        "SeniorCitizen" in reason and "requires explicit review" in reason
        for reason in draft["execution_readiness"]["blocking_reasons"]
    )


def test_draft_projection_is_never_execution_ready() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert draft["execution_readiness"]["is_execution_ready"] is False
    assert len(draft["execution_readiness"]["blocking_reasons"]) > 0


def test_draft_projection_unresolved_review_items_are_not_silently_resolved() -> None:
    intent = _telco_like_modeling_intent()
    draft = project_execution_contract_draft(intent)
    # The unresolved TotalCharges/SeniorCitizen review items must still be
    # visible verbatim in the draft, not converted into accepted policy.
    assert draft["blank_value_policy_candidates"] == intent["blank_value_policy_candidates"]
    assert draft["feature_review_notes"] == intent["feature_review_notes"]


def test_draft_projection_boundary_confirmations_all_false() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    assert not any(draft["execution_contract_draft_boundary_confirmations"].values())


def test_draft_projection_does_not_populate_execution_only_policy_fields() -> None:
    draft = project_execution_contract_draft(_telco_like_modeling_intent())
    for field in (
        "missing_value_policy",
        "categorical_encoding_policy",
        "numeric_handling",
        "allowed_transformations",
        "split_policy",
        "random_seed",
        "primary_metric",
        "secondary_metrics",
        "modeling_constraints",
    ):
        assert field not in draft
        assert any(reason.startswith(f"{field}:") for reason in draft["execution_readiness"]["blocking_reasons"])


def test_draft_projection_generated_at_defaults_when_absent() -> None:
    intent = _telco_like_modeling_intent()
    del intent["generated_at"]
    draft = project_execution_contract_draft(intent)
    assert draft["generated_at"]
    assert draft["authoring_traceability"]["source_modeling_intent_generated_at"] is None


def test_draft_projection_accepts_explicit_generated_at() -> None:
    draft = project_execution_contract_draft(
        _telco_like_modeling_intent(), generated_at="2026-07-09T12:00:00+00:00"
    )
    assert draft["generated_at"] == "2026-07-09T12:00:00+00:00"


def test_draft_projection_is_dataset_agnostic() -> None:
    """A non-Telco synthetic modeling intent projects cleanly too."""
    intent = _telco_like_modeling_intent(
        dataset_identity={
            "dataset_slug": "bank-marketing",
            "dataset_source_ref": "data/raw/bank-marketing.csv",
        },
        target_intent={
            "target_column": "y",
            "task_type": "binary_classification",
            "observed_labels": ["no", "yes"],
            "positive_label_candidate": "yes",
            "observed_target_distribution": {"no": 800, "yes": 200},
            "is_final_training_configuration": False,
        },
        identifier_and_ignored_columns=[],
        initial_feature_candidates=["age", "job"],
        feature_review_notes={},
        feature_type_intent=[
            {"name": "age", "type_intent": "numeric"},
            {"name": "job", "type_intent": "categorical"},
        ],
        blank_value_policy_candidates={},
    )
    draft = project_execution_contract_draft(intent)
    assert draft["dataset_identity"]["dataset_slug"] == "bank-marketing"
    assert draft["target_column"] == "y"
    assert draft["feature_columns"] == ["age", "job"]
    assert draft["ignored_columns"] == []
    # No feature-level review items this time, but the standing
    # execution-only policy fields are still unresolved.
    assert draft["execution_readiness"]["is_execution_ready"] is False
    assert len(draft["execution_readiness"]["blocking_reasons"]) == 9


def test_draft_projection_is_deterministic_for_same_input() -> None:
    intent = _telco_like_modeling_intent()
    first = project_execution_contract_draft(intent, generated_at="2026-07-09T00:00:00+00:00")
    second = project_execution_contract_draft(intent, generated_at="2026-07-09T00:00:00+00:00")
    assert first == second


# --- binary result semantics materialization (Project Spec S0108) ---
# A small, dataset-agnostic "campaign-response" fixture, matching the
# established S0014 dataset-agnosticism precedent (mirrors
# tests/test_execution_contract_schema.py's own local fixture shape, since
# that file is not part of this Project Spec's allowed edit paths).

VALID_RESULT_SEMANTICS_BANDS = [
    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
]


def _approved_binary_result_semantics_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        problem_type="binary_classification",
        positive_class_id="Yes",
        event_label="Responded",
        primary_output="positive_class_probability",
        threshold=0.5,
        preset="risk",
        bands=VALID_RESULT_SEMANTICS_BANDS,
    )
    kwargs.update(overrides)
    return build_binary_result_semantics_intent(**kwargs)


def _modeling_intent_for_result_semantics(binary_result_semantics_intent=None) -> dict:
    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "campaign-response",
            "dataset_source_ref": "data/raw/campaign-response.csv",
        },
        "target_intent": {
            "target_column": "responded",
            "task_type": "binary_classification",
            "observed_labels": ["No", "Yes"],
            "positive_label_candidate": "Yes",
            "observed_target_distribution": {"No": 800, "Yes": 200},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": "customer_ref", "reason": "identifier_candidate_excluded_from_features"}
        ],
        "initial_feature_candidates": ["age", "channel", "opted_in"],
        "categorical_domain_intent": [],
        "binary_result_semantics_intent": binary_result_semantics_intent,
    }


def _discovery_evidence_for_result_semantics() -> dict:
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "field_observations": [
            {
                "name": "age", "inferred_type": "integer", "null_count": 0, "null_rate": 0.0,
                "cardinality": 40, "sample_min": 18, "sample_max": 90,
            },
            {
                "name": "channel", "inferred_type": "string", "null_count": 0, "null_rate": 0.0,
                "cardinality": 3, "sample_min": "email", "sample_max": "sms",
            },
            {
                "name": "opted_in", "inferred_type": "boolean", "null_count": 0, "null_rate": 0.0,
                "cardinality": 2, "sample_min": "0", "sample_max": "1",
            },
        ],
        "generation_settings": {"seed": 0, "generator_version": "discovery-evidence.v1"},
    }


def test_execution_contract_omits_result_semantics_when_intent_absent():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract


def test_execution_contract_omits_result_semantics_when_pending_review():
    intent = _approved_binary_result_semantics_intent(review_status="pending_review")
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract, (
        "a pending/unreviewed binary_result_semantics_intent must not materialize "
        "into executable execution-contract policy"
    )


def test_execution_contract_materializes_result_semantics_when_approved():
    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    result_semantics = contract["result_semantics"]
    assert result_semantics["schema_version"] == "binary-result-semantics.v1"
    assert result_semantics["problem_type"] == "binary_classification"
    assert result_semantics["positive_class"] == {"class_id": "Yes", "event_label": "Responded"}
    assert result_semantics["primary_output"] == "positive_class_probability"
    assert result_semantics["decision"] == {"threshold": 0.5}
    assert result_semantics["interpretation"]["preset"] == "risk"
    assert result_semantics["interpretation"]["bands"] == VALID_RESULT_SEMANTICS_BANDS
    # Authoring-only fields must never leak into the executable form.
    assert "review_status" not in result_semantics
    assert "schema_version" in result_semantics and result_semantics["schema_version"] != (
        intent["schema_version"]
    ), "the materialized schema_version must be the execution-form constant, not the authoring intent's own"


def test_execution_contract_still_validates_against_schema_with_result_semantics():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    jsonschema.validate(contract, schema)


def test_execution_contract_rejects_structurally_invalid_intent_without_raising():
    # A hand-crafted, malformed declaration (missing a required band) with a
    # literal review_status of "approved" must still be independently
    # re-validated and rejected -- not trusted just because it claims to be
    # approved.
    malformed_intent = {
        "schema_version": "binary_result_semantics_intent.v1",
        "review_status": "approved",
        "problem_type": "binary_classification",
        "positive_class": {"class_id": "Yes", "event_label": "Responded"},
        "primary_output": "positive_class_probability",
        "decision": {"threshold": 0.5},
        "interpretation": {
            "preset": "risk",
            "bands": VALID_RESULT_SEMANTICS_BANDS[:2],  # missing the "high" band
        },
    }
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=malformed_intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract


def test_execution_contract_materialization_evidence_reports_absence():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(modeling_intent, discovery_evidence, None)
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        generated_at="2026-07-16T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["reviewed_source_intent_present"] is False
    assert materialization["readiness"] == "not_materialized"
    assert materialization["positive_class"] is None
    assert len(materialization["blocking_reasons"]) == 1


def test_execution_contract_materialization_evidence_reports_materialized():
    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(modeling_intent, discovery_evidence, None)
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        generated_at="2026-07-16T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["reviewed_source_intent_present"] is True
    assert materialization["readiness"] == "materialized"
    assert materialization["positive_class"] == {"class_id": "Yes", "event_label": "Responded"}
    assert materialization["threshold"] == 0.5
    assert materialization["bands"] == VALID_RESULT_SEMANTICS_BANDS
    assert materialization["no_defaults_inferred"] is True
    assert materialization["blocking_reasons"] == []


# ---------------------------------------------------------------------------
# Multiclass result semantics materialization (Project Spec S0207).
# Fixtures are synthetic and dataset-neutral, matching the campaign-response
# precedent established above -- no Dry Bean or other real-dataset name.
# ---------------------------------------------------------------------------

VALID_MULTICLASS_CLASSES = [
    {"class_id": "low_risk", "display_label": "Low Risk"},
    {"class_id": "medium_risk", "display_label": "Medium Risk"},
    {"class_id": "high_risk", "display_label": "High Risk"},
]


def _approved_multiclass_result_semantics_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        problem_type="multiclass_classification",
        primary_output="predicted_class",
        probability_output="class_probabilities",
        decision_strategy="argmax",
        review_notes="Reviewed multiclass result semantics.",
    )
    kwargs.update(overrides)
    return build_multiclass_result_semantics_intent(**kwargs)


def _valid_semantic_intent_v2(classes=None) -> dict:
    return {
        "schema_version": "dataset-semantic-intent.v2",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": "campaign-response"},
        "authoring_generation_id": "gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": "multiclass-predictive-classification",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": [
            {"field_name": "responded", "role": "target", "include_in_features": False},
        ],
        "target_semantics": {
            "target_field_name": "responded",
            "task_type": "multiclass_classification",
            "classes": list(classes if classes is not None else VALID_MULTICLASS_CLASSES),
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


def _modeling_intent_for_multiclass_result_semantics(multiclass_result_semantics_intent=None) -> dict:
    intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    intent["multiclass_result_semantics_intent"] = multiclass_result_semantics_intent
    return intent


def test_execution_contract_materializes_multiclass_result_semantics_when_approved():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )

    result_semantics = contract["result_semantics"]
    assert result_semantics["schema_version"] == "multiclass-result-semantics.v1"
    assert result_semantics["problem_type"] == "multiclass_classification"
    assert result_semantics["primary_output"] == "predicted_class"
    assert result_semantics["probability_output"] == "class_probabilities"
    assert result_semantics["decision"] == {"strategy": "argmax"}
    assert result_semantics["classes"] == VALID_MULTICLASS_CLASSES
    for forbidden in ("positive_class", "negative_class", "threshold", "interpretation"):
        assert forbidden not in result_semantics


def test_execution_contract_multiclass_classes_preserve_authored_order_exactly():
    reordered = [
        {"class_id": "high_risk", "display_label": "High Risk"},
        {"class_id": "low_risk", "display_label": "Low Risk"},
        {"class_id": "medium_risk", "display_label": "Medium Risk"},
    ]
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2(classes=reordered)
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert contract["result_semantics"]["classes"] == reordered


def test_execution_contract_multiclass_supports_more_than_three_classes():
    four_classes = VALID_MULTICLASS_CLASSES + [
        {"class_id": "critical_risk", "display_label": "Critical Risk"}
    ]
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2(classes=four_classes)
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert len(contract["result_semantics"]["classes"]) == 4


def test_execution_contract_omits_multiclass_result_semantics_when_pending_review():
    intent = _approved_multiclass_result_semantics_intent(review_status="pending_review")
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_multiclass_result_semantics_when_semantic_intent_missing():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None, semantic_intent=None
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_multiclass_result_semantics_when_semantic_intent_wrong_version():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    semantic_intent["schema_version"] = "dataset-semantic-intent.v1"
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_multiclass_result_semantics_when_wrong_task_type():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    semantic_intent["target_semantics"]["task_type"] = "binary_classification"
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_multiclass_duplicate_class_id_fails_closed():
    duplicated = [
        {"class_id": "low_risk", "display_label": "Low Risk"},
        {"class_id": "low_risk", "display_label": "Low Risk Duplicate"},
        {"class_id": "high_risk", "display_label": "High Risk"},
    ]
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2(classes=duplicated)
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_binary_and_multiclass_intents_together_fail_closed():
    binary_intent = _approved_binary_result_semantics_intent()
    multiclass_intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=binary_intent)
    modeling_intent["multiclass_result_semantics_intent"] = multiclass_intent
    semantic_intent = _valid_semantic_intent_v2()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_binary_intent_still_materializes_exactly_as_before():
    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    result_semantics = contract["result_semantics"]
    assert result_semantics["schema_version"] == "binary-result-semantics.v1"
    assert result_semantics["positive_class"] == {"class_id": "Yes", "event_label": "Responded"}


def test_execution_contract_absence_of_both_intents_still_omits_result_semantics():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract


def test_multiclass_result_semantics_validates_against_execution_contract_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    jsonschema.validate(contract, schema)


def test_materialization_evidence_names_multiclass_variant_deterministically():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(
        modeling_intent, discovery_evidence, None, semantic_intent=semantic_intent
    )
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        semantic_intent=semantic_intent,
        generated_at="2026-08-16T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["requested_variant"] == "multiclass"
    assert materialization["materialized_schema_version"] == "multiclass-result-semantics.v1"
    assert materialization["problem_type"] == "multiclass_classification"
    assert materialization["status"] == "materialized"
    assert materialization["reason"] is None
    assert materialization["class_count"] == 3
    assert materialization["class_ids"] == ["low_risk", "medium_risk", "high_risk"]


def test_materialization_evidence_names_binary_variant_deterministically():
    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(modeling_intent, discovery_evidence, None)
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        generated_at="2026-08-16T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["requested_variant"] == "binary"
    assert materialization["materialized_schema_version"] == "binary-result-semantics.v1"
    assert materialization["problem_type"] == "binary_classification"
    assert materialization["status"] == "materialized"


def test_materialization_evidence_names_absence_of_both_intents_deterministically():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(modeling_intent, discovery_evidence, None)
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        generated_at="2026-08-16T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["requested_variant"] == "none"
    assert materialization["materialized_schema_version"] is None
    assert materialization["problem_type"] is None
    assert materialization["status"] == "omitted"


# ---------------------------------------------------------------------------
# Continuous-regression result semantics materialization (Project Spec S0223).
# Fixtures are synthetic and dataset-neutral, matching the campaign-response
# precedent established above -- no Concrete Compressive Strength or other
# real-dataset name/unit.
# ---------------------------------------------------------------------------


def _approved_continuous_regression_result_semantics_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        problem_type="continuous_regression",
        primary_output="predicted_value",
        output_value_kind="continuous_numeric",
        review_notes="Reviewed continuous-regression result semantics.",
    )
    kwargs.update(overrides)
    return build_continuous_regression_result_semantics_intent(**kwargs)


def _valid_semantic_intent_v3(
    target_field_name="outcome_measure",
    task_type="continuous_regression",
    target_value_kind="continuous_numeric",
) -> dict:
    return {
        "schema_version": "dataset-semantic-intent.v3",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": "campaign-response"},
        "authoring_generation_id": "gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": "continuous-predictive-regression",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": [
            {"field_name": target_field_name, "role": "target", "include_in_features": False},
        ],
        "target_semantics": {
            "target_field_name": target_field_name,
            "task_type": task_type,
            "target_value_kind": target_value_kind,
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


def _approved_continuous_regression_training_policy_intent() -> dict:
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


_MISSING = object()


def _modeling_intent_for_continuous_regression_result_semantics(
    continuous_regression_result_semantics_intent=None,
    target_column="outcome_measure",
    modeling_task_type="continuous_regression",
    training_policy_intent=_MISSING,
) -> dict:
    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "campaign-response",
            "dataset_source_ref": "data/raw/campaign-response.csv",
        },
        "target_intent": {
            "target_column": target_column,
            "task_type": modeling_task_type,
            "observed_labels": [],
            "positive_label_candidate": None,
            "observed_target_distribution": {},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": "customer_ref", "reason": "identifier_candidate_excluded_from_features"}
        ],
        "initial_feature_candidates": ["age", "channel", "opted_in"],
        "categorical_domain_intent": [],
        "binary_result_semantics_intent": None,
        "multiclass_result_semantics_intent": None,
        "continuous_regression_result_semantics_intent": continuous_regression_result_semantics_intent,
        "training_policy_intent": (
            _approved_continuous_regression_training_policy_intent()
            if training_policy_intent is _MISSING
            else training_policy_intent
        ),
    }


def test_execution_contract_materializes_continuous_regression_result_semantics_when_approved():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )

    result_semantics = contract["result_semantics"]
    assert result_semantics == {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
    }
    for forbidden in (
        "positive_class", "negative_class", "classes", "class_order",
        "probability_output", "class_probabilities", "threshold", "decision",
        "interpretation", "risk", "bands", "count_semantics", "exposure",
        "offset", "output_targets", "target_fields", "unit", "minimum", "maximum",
    ):
        assert forbidden not in result_semantics


def test_execution_contract_continuous_regression_no_binary_or_multiclass_fields_appear():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert set(contract["result_semantics"].keys()) == {
        "schema_version", "problem_type", "primary_output", "output_value_kind",
    }


def test_execution_contract_omits_continuous_regression_result_semantics_when_pending_review():
    intent = _approved_continuous_regression_result_semantics_intent(review_status="pending_review")
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_continuous_regression_result_semantics_when_semantic_intent_missing():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None, semantic_intent=None
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_continuous_regression_result_semantics_when_semantic_intent_wrong_version():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    semantic_intent["schema_version"] = "dataset-semantic-intent.v2"
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_continuous_regression_result_semantics_when_wrong_task_type():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3(task_type="multiclass_classification")
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_omits_continuous_regression_result_semantics_when_wrong_target_value_kind():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3(target_value_kind="discrete_count")
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_continuous_regression_blank_target_field_name_fails_closed():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3(target_field_name="")
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_continuous_regression_target_field_name_mismatch_fails_closed():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, target_column="a_different_column"
    )
    semantic_intent = _valid_semantic_intent_v3(target_field_name="outcome_measure")
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_continuous_regression_wrong_modeling_target_task_type_fails_closed():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, modeling_task_type="binary_classification"
    )
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_binary_and_continuous_regression_intents_conflict():
    binary_intent = _approved_binary_result_semantics_intent()
    continuous_intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(continuous_intent)
    modeling_intent["binary_result_semantics_intent"] = binary_intent
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_multiclass_and_continuous_regression_intents_conflict():
    multiclass_intent = _approved_multiclass_result_semantics_intent()
    continuous_intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(continuous_intent)
    modeling_intent["multiclass_result_semantics_intent"] = multiclass_intent
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_binary_multiclass_continuous_regression_intents_all_conflict():
    binary_intent = _approved_binary_result_semantics_intent()
    multiclass_intent = _approved_multiclass_result_semantics_intent()
    continuous_intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(continuous_intent)
    modeling_intent["binary_result_semantics_intent"] = binary_intent
    modeling_intent["multiclass_result_semantics_intent"] = multiclass_intent
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert "result_semantics" not in contract


def test_execution_contract_existing_binary_intent_still_materializes_exactly_as_before_under_closed_dispatcher():
    intent = _approved_binary_result_semantics_intent()
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=intent)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    result_semantics = contract["result_semantics"]
    assert result_semantics["schema_version"] == "binary-result-semantics.v1"
    assert result_semantics["positive_class"] == {"class_id": "Yes", "event_label": "Responded"}


def test_execution_contract_existing_multiclass_intent_still_materializes_exactly_as_before_under_closed_dispatcher():
    intent = _approved_multiclass_result_semantics_intent()
    modeling_intent = _modeling_intent_for_multiclass_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v2()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    result_semantics = contract["result_semantics"]
    assert result_semantics["schema_version"] == "multiclass-result-semantics.v1"
    assert result_semantics["classes"] == VALID_MULTICLASS_CLASSES


def test_execution_contract_absence_of_all_three_result_intents_still_omits_result_semantics():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    modeling_intent["multiclass_result_semantics_intent"] = None
    modeling_intent["continuous_regression_result_semantics_intent"] = None
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract


def test_continuous_regression_result_semantics_validates_against_execution_contract_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    jsonschema.validate(contract, schema)


def test_materialization_evidence_names_continuous_regression_variant_deterministically():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(
        modeling_intent, discovery_evidence, None, semantic_intent=semantic_intent
    )
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/campaign-response/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        semantic_intent=semantic_intent,
        generated_at="2026-08-19T00:00:00+00:00",
    )
    materialization = evidence["result_semantics_materialization"]
    assert materialization["requested_variant"] == "continuous_regression"
    assert materialization["materialized_schema_version"] == "continuous-regression-result-semantics.v1"
    assert materialization["problem_type"] == "continuous_regression"
    assert materialization["status"] == "materialized"
    assert materialization["reason"] is None
    assert materialization["target_field_name"] == "outcome_measure"
    assert materialization["primary_output"] == "predicted_value"
    assert materialization["output_value_kind"] == "continuous_numeric"
    assert materialization["semantic_intent_schema_version"] == "dataset-semantic-intent.v3"
    assert materialization["no_defaults_inferred"] is True
    assert materialization["blocking_reasons"] == []


def test_execution_contract_continuous_regression_intent_without_training_policy_fails_closed_before_classification_defaults():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, training_policy_intent=None
    )
    semantic_intent = _valid_semantic_intent_v3()
    with pytest.raises(TrainingPolicyValidationError):
        _build_execution_contract(
            modeling_intent,
            _discovery_evidence_for_result_semantics(),
            None,
            semantic_intent=semantic_intent,
        )


def test_execution_contract_continuous_regression_pending_intent_without_training_policy_still_fails_closed():
    # Presence alone (even pending_review, not yet approved) is enough to
    # require an explicit training_policy_intent -- the fail-closed check
    # never waits to see whether the intent would actually materialize.
    intent = _approved_continuous_regression_result_semantics_intent(review_status="pending_review")
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, training_policy_intent=None
    )
    with pytest.raises(TrainingPolicyValidationError):
        _build_execution_contract(
            modeling_intent, _discovery_evidence_for_result_semantics(), None, semantic_intent=None
        )


def test_execution_contract_explicit_approved_regression_policy_accepts_r2_mae_rmse_identifiers():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(intent)
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert contract["split_policy"]["strategy"] == "random"
    assert contract["primary_metric"] == "r2"
    assert contract["secondary_metrics"] == ["mae", "rmse"]


# --- Project Spec S0231: continuous-regression hist_gradient_boosting fixed
# policy, discriminated from the S0216 classification HGB shape by
# problem_type_hint = "continuous_regression" ------------------------------


def _hgb_regression_hyperparameters(**overrides) -> dict:
    base = {
        "l2_regularization": 0.0,
        "learning_rate": 0.05,
        "max_iter": 250,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
    }
    base.update(overrides)
    return base


def _approved_hgb_regression_training_policy_intent(**overrides) -> dict:
    policy = {
        "review_status": "approved",
        "numeric_handling": "standardize",
        "categorical_encoding_policy": "onehot",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "primary_metric": "r2",
        "secondary_metrics": ["mae", "rmse"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": _hgb_regression_hyperparameters(),
            },
        },
    }
    policy.update(overrides)
    return policy


def test_validate_hgb_regression_hyperparameters_accepts_bounded_configuration():
    assert _validate_hgb_regression_hyperparameters(_hgb_regression_hyperparameters()) == []


def test_validate_hgb_regression_hyperparameters_accepts_concrete_representative_bounded_configuration():
    # Representative bounded values for a real continuous-regression run --
    # never a Concrete-dataset-slug or dataset-specific special case, only a
    # second, distinct valid combination proving the shape is genuinely
    # validated rather than matched against one hardcoded fixture.
    reasons = _validate_hgb_regression_hyperparameters(
        {
            "l2_regularization": 0.5,
            "learning_rate": 0.08,
            "max_iter": 400,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 20,
            "early_stopping": True,
        }
    )
    assert reasons == []


def test_validate_hgb_regression_hyperparameters_rejects_class_weight():
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["class_weight"] = None
    reasons = _validate_hgb_regression_hyperparameters(hyperparameters)
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_hgb_regression_hyperparameters_rejects_random_state():
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["random_state"] = 7
    reasons = _validate_hgb_regression_hyperparameters(hyperparameters)
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_hgb_regression_hyperparameters_rejects_unknown_field():
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["n_estimators"] = 100
    reasons = _validate_hgb_regression_hyperparameters(hyperparameters)
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_hgb_regression_hyperparameters_rejects_missing_required_field():
    hyperparameters = _hgb_regression_hyperparameters()
    del hyperparameters["learning_rate"]
    reasons = _validate_hgb_regression_hyperparameters(hyperparameters)
    assert any("missing required fields" in reason for reason in reasons)


def test_validate_training_policy_intent_approved_continuous_regression_accepts_hist_gradient_boosting():
    reasons = _validate_training_policy_intent(
        _approved_hgb_regression_training_policy_intent(), problem_type_hint="continuous_regression",
    )
    assert reasons == []


def test_validate_training_policy_intent_continuous_regression_hgb_rejects_class_weight():
    policy = _approved_hgb_regression_training_policy_intent()
    policy["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["class_weight"] = None
    reasons = _validate_training_policy_intent(policy, problem_type_hint="continuous_regression")
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_training_policy_intent_continuous_regression_hgb_rejects_random_state():
    policy = _approved_hgb_regression_training_policy_intent()
    policy["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["random_state"] = 7
    reasons = _validate_training_policy_intent(policy, problem_type_hint="continuous_regression")
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_training_policy_intent_continuous_regression_hgb_rejects_unknown_field():
    policy = _approved_hgb_regression_training_policy_intent()
    policy["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100
    reasons = _validate_training_policy_intent(policy, problem_type_hint="continuous_regression")
    assert any("unsupported HGB regression hyperparameter" in reason for reason in reasons)


def test_validate_training_policy_intent_continuous_regression_evaluate_allowed_families_remains_rejected():
    policy = _approved_hgb_regression_training_policy_intent()
    del policy["modeling_constraints"]["selection_mode"]
    del policy["modeling_constraints"]["fixed_model_configuration"]
    reasons = _validate_training_policy_intent(policy, problem_type_hint="continuous_regression")
    assert any(
        "requires modeling_constraints.selection_mode = fixed_configuration" in reason for reason in reasons
    )


def test_execution_contract_continuous_regression_accepts_hist_gradient_boosting_fixed_policy():
    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, training_policy_intent=_approved_hgb_regression_training_policy_intent(),
    )
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    assert contract["modeling_constraints"]["allowed_model_families"] == ["hist_gradient_boosting"]
    assert contract["modeling_constraints"]["fixed_model_configuration"]["model_family"] == "hist_gradient_boosting"
    assert contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"] == (
        _hgb_regression_hyperparameters()
    )
    assert "class_weight" not in contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]


def test_execution_contract_continuous_regression_hgb_policy_validates_against_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    intent = _approved_continuous_regression_result_semantics_intent()
    modeling_intent = _modeling_intent_for_continuous_regression_result_semantics(
        intent, training_policy_intent=_approved_hgb_regression_training_policy_intent(),
    )
    semantic_intent = _valid_semantic_intent_v3()
    contract = _build_execution_contract(
        modeling_intent,
        _discovery_evidence_for_result_semantics(),
        None,
        semantic_intent=semantic_intent,
    )
    jsonschema.validate(contract, schema)


def test_execution_contract_binary_multiclass_callers_without_training_policy_retain_historical_defaults_alongside_continuous_regression_addition():
    # Binary/multiclass callers that omit training_policy_intent are
    # unaffected by the new S0223 fail-closed condition, which only fires
    # when a continuous_regression_result_semantics_intent is present.
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    modeling_intent["training_policy_intent"] = None
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert contract["numeric_handling"] == "standardize"
    assert contract["primary_metric"] == "roc_auc"


# --- Project Spec S0216: reviewed native training-policy validation and
# materialization (Desired Changes D/E/F) -----------------------------------


def _approved_fixed_configuration_training_policy_intent(**overrides) -> dict:
    policy = {
        "review_status": "approved",
        "numeric_handling": "passthrough",
        "categorical_encoding_policy": "onehot",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "stratified", "train_ratio": 0.70, "val_ratio": 0.15, "test_ratio": 0.15},
        "primary_metric": "f1_macro",
        "secondary_metrics": ["balanced_accuracy", "f1_weighted", "recall_macro", "accuracy", "log_loss"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": {
                    "class_weight": None,
                    "l2_regularization": 0.0,
                    "learning_rate": 0.05,
                    "max_iter": 250,
                    "max_leaf_nodes": 15,
                    "min_samples_leaf": 40,
                },
            },
        },
    }
    policy.update(overrides)
    return policy


def _modeling_intent_with_training_policy(training_policy_intent=None) -> dict:
    intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    intent["training_policy_intent"] = training_policy_intent
    return intent


def test_validate_training_policy_intent_accepts_complete_approved_policy():
    reasons = _validate_training_policy_intent(_approved_fixed_configuration_training_policy_intent())
    assert reasons == []


def test_validate_training_policy_intent_rejects_unapproved_review_status():
    policy = _approved_fixed_configuration_training_policy_intent(review_status="pending_review")
    reasons = _validate_training_policy_intent(policy)
    assert any("unapproved review status" in reason for reason in reasons)


def test_validate_training_policy_intent_rejects_unknown_metric():
    policy = _approved_fixed_configuration_training_policy_intent(primary_metric="not_a_real_metric")
    reasons = _validate_training_policy_intent(policy)
    assert any("unknown metric" in reason for reason in reasons)


def test_validate_training_policy_intent_rejects_unknown_model_family():
    policy = _approved_fixed_configuration_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["not_a_real_family"]
    policy["modeling_constraints"]["fixed_model_configuration"]["model_family"] = "not_a_real_family"
    reasons = _validate_training_policy_intent(policy)
    assert any("unknown model family" in reason for reason in reasons)


def test_validate_training_policy_intent_rejects_fixed_family_not_in_allowed_families():
    policy = _approved_fixed_configuration_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["gradient_boosting"]
    reasons = _validate_training_policy_intent(policy)
    assert reasons


def test_validate_training_policy_intent_rejects_fixed_configuration_with_multiple_allowed_families():
    policy = _approved_fixed_configuration_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["hist_gradient_boosting", "gradient_boosting"]
    reasons = _validate_training_policy_intent(policy)
    assert reasons


def test_validate_training_policy_intent_rejects_unsupported_hgb_hyperparameter():
    policy = _approved_fixed_configuration_training_policy_intent()
    policy["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100
    reasons = _validate_training_policy_intent(policy)
    assert any("unsupported HGB hyperparameter" in reason for reason in reasons)


def test_validate_training_policy_intent_rejects_invalid_split_ratios():
    policy = _approved_fixed_configuration_training_policy_intent()
    policy["split_policy"] = {"strategy": "stratified", "train_ratio": 0.5, "val_ratio": 0.5, "test_ratio": 0.5}
    reasons = _validate_training_policy_intent(policy)
    assert any("sum to 1.0" in reason for reason in reasons)


def test_materialize_training_policy_fields_returns_none_when_absent():
    modeling_intent = _modeling_intent_with_training_policy(None)
    assert _materialize_training_policy_fields(modeling_intent) is None


def test_materialize_training_policy_fields_raises_for_invalid_present_policy():
    modeling_intent = _modeling_intent_with_training_policy(
        _approved_fixed_configuration_training_policy_intent(review_status="pending_review")
    )
    with pytest.raises(TrainingPolicyValidationError):
        _materialize_training_policy_fields(modeling_intent)


def test_execution_contract_uses_approved_training_policy_wholesale():
    modeling_intent = _modeling_intent_with_training_policy(_approved_fixed_configuration_training_policy_intent())
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    assert contract["numeric_handling"] == "passthrough"
    assert contract["primary_metric"] == "f1_macro"
    assert contract["modeling_constraints"]["selection_mode"] == "fixed_configuration"
    assert contract["modeling_constraints"]["allowed_model_families"] == ["hist_gradient_boosting"]


def test_execution_contract_present_but_invalid_training_policy_raises_not_falls_back():
    modeling_intent = _modeling_intent_with_training_policy(
        _approved_fixed_configuration_training_policy_intent(review_status="pending_review")
    )
    with pytest.raises(TrainingPolicyValidationError):
        _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)


def test_execution_contract_legacy_defaults_unchanged_when_training_policy_absent():
    modeling_intent = _modeling_intent_with_training_policy(None)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    assert contract["numeric_handling"] == "standardize"
    assert contract["primary_metric"] == "roc_auc"
    assert "selection_mode" not in contract["modeling_constraints"]


def test_execution_contract_with_training_policy_still_validates_against_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    modeling_intent = _modeling_intent_with_training_policy(_approved_fixed_configuration_training_policy_intent())
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    jsonschema.validate(contract, schema)


def test_execution_contract_materialization_evidence_reports_training_policy_present():
    modeling_intent = _modeling_intent_with_training_policy(_approved_fixed_configuration_training_policy_intent())
    discovery_evidence = _discovery_evidence_for_result_semantics()
    contract = _build_execution_contract(modeling_intent, discovery_evidence, None)
    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        None,
        contract,
        execution_contract_relative_path="contracts/dry-bean/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        generated_at="2026-08-18T00:00:00+00:00",
    )
    training_policy_materialization = evidence["training_policy_materialization"]
    assert training_policy_materialization["reviewed_source_intent_present"] is True
    assert training_policy_materialization["materialized"] is True
    assert evidence["policy_defaults_requiring_future_review"] == []


# ---------------------------------------------------------------------------
# Project Spec S0258: binary-specific training-policy strictness, corrective
# supersession of the blocked Project Spec S0257 implementation intent.
# Reuses the same S0216 fixed_configuration/hist_gradient_boosting validation
# path as multiclass (problem_type_hint only narrows the accepted metric
# vocabulary -- it never forces fixed_configuration the way
# continuous_regression does), so the historical binary
# evaluate_allowed_families selection_mode remains completely unchanged and
# is proven still reachable below. No dataset-slug branch is introduced --
# every fixture below reuses the same generic synthetic "campaign-response"
# dataset identity already established for the binary result-semantics tests
# above.
# ---------------------------------------------------------------------------


def _approved_fixed_binary_training_policy_intent(**overrides) -> dict:
    policy = {
        "review_status": "approved",
        "numeric_handling": "standardize",
        "categorical_encoding_policy": "onehot",
        "allowed_transformations": [],
        "split_policy": {"strategy": "stratified", "train_ratio": 0.70, "val_ratio": 0.15, "test_ratio": 0.15},
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "accuracy", "log_loss", "pr_auc"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": {
                    "class_weight": None,
                    "l2_regularization": 0.0,
                    "learning_rate": 0.05,
                    "max_iter": 250,
                    "max_leaf_nodes": 15,
                    "min_samples_leaf": 40,
                },
            },
        },
    }
    policy.update(overrides)
    return policy


def _modeling_intent_with_binary_training_policy(
    training_policy_intent=_MISSING, binary_result_semantics_intent=_MISSING,
) -> dict:
    intent = _modeling_intent_for_result_semantics(
        binary_result_semantics_intent=(
            _approved_binary_result_semantics_intent()
            if binary_result_semantics_intent is _MISSING
            else binary_result_semantics_intent
        )
    )
    intent["training_policy_intent"] = (
        _approved_fixed_binary_training_policy_intent()
        if training_policy_intent is _MISSING
        else training_policy_intent
    )
    return intent


def test_validate_training_policy_intent_accepts_complete_approved_binary_policy():
    reasons = _validate_training_policy_intent(
        _approved_fixed_binary_training_policy_intent(), problem_type_hint="binary_classification",
    )
    assert reasons == []


def test_validate_training_policy_intent_binary_rejects_multiclass_only_metric():
    """Project Spec S0258: the binary-specific metric vocabulary must never
    accept a multiclass-only aggregate metric id such as f1_macro, even
    though it is schema-valid vocabulary generically."""
    policy = _approved_fixed_binary_training_policy_intent(primary_metric="f1_macro")
    reasons = _validate_training_policy_intent(policy, problem_type_hint="binary_classification")
    assert any("unknown metric" in reason for reason in reasons)


def test_validate_training_policy_intent_binary_rejects_continuous_regression_only_metric():
    policy = _approved_fixed_binary_training_policy_intent(primary_metric="r2")
    reasons = _validate_training_policy_intent(policy, problem_type_hint="binary_classification")
    assert any("unknown metric" in reason for reason in reasons)


def test_validate_training_policy_intent_binary_rejects_fixed_family_not_in_allowed_families():
    policy = _approved_fixed_binary_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["gradient_boosting"]
    reasons = _validate_training_policy_intent(policy, problem_type_hint="binary_classification")
    assert reasons


def test_validate_training_policy_intent_binary_rejects_fixed_configuration_with_multiple_allowed_families():
    policy = _approved_fixed_binary_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["hist_gradient_boosting", "gradient_boosting"]
    reasons = _validate_training_policy_intent(policy, problem_type_hint="binary_classification")
    assert reasons


def test_validate_training_policy_intent_binary_rejects_unsupported_hgb_hyperparameter():
    policy = _approved_fixed_binary_training_policy_intent()
    policy["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100
    reasons = _validate_training_policy_intent(policy, problem_type_hint="binary_classification")
    assert any("unsupported HGB hyperparameter" in reason for reason in reasons)


def test_execution_contract_approved_binary_fixed_policy_materializes_exactly_one_hgb_fixed_configuration():
    modeling_intent = _modeling_intent_with_binary_training_policy()
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    assert contract["modeling_constraints"]["selection_mode"] == "fixed_configuration"
    assert contract["modeling_constraints"]["allowed_model_families"] == ["hist_gradient_boosting"]
    assert (
        contract["modeling_constraints"]["fixed_model_configuration"]["model_family"]
        == "hist_gradient_boosting"
    )
    assert contract["primary_metric"] == "roc_auc"


def test_execution_contract_binary_fixed_policy_positive_class_and_result_semantics_remain_authoritative():
    """Desired Change I/tests J: the governed positive-class/result-semantics
    claim must survive alongside a fixed_configuration training policy on the
    same execution contract -- neither materializer overwrites the other."""
    modeling_intent = _modeling_intent_with_binary_training_policy()
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    assert contract["result_semantics"]["schema_version"] == "binary-result-semantics.v1"
    assert contract["result_semantics"]["positive_class"] == {"class_id": "Yes", "event_label": "Responded"}
    assert contract["result_semantics"]["decision"] == {"threshold": 0.5}
    assert contract["modeling_constraints"]["selection_mode"] == "fixed_configuration"


def test_execution_contract_binary_pending_training_policy_fails_closed_not_silently_falls_back():
    modeling_intent = _modeling_intent_with_binary_training_policy(
        training_policy_intent=_approved_fixed_binary_training_policy_intent(review_status="pending_review"),
    )
    with pytest.raises(TrainingPolicyValidationError):
        _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)


def test_execution_contract_binary_invalid_fixed_family_fails_closed():
    policy = _approved_fixed_binary_training_policy_intent()
    policy["modeling_constraints"]["allowed_model_families"] = ["gradient_boosting"]
    modeling_intent = _modeling_intent_with_binary_training_policy(training_policy_intent=policy)
    with pytest.raises(TrainingPolicyValidationError):
        _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)


def test_execution_contract_binary_fixed_policy_still_validates_against_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    modeling_intent = _modeling_intent_with_binary_training_policy()
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    jsonschema.validate(contract, schema)


def test_historical_binary_evaluate_allowed_families_selection_behavior_unchanged():
    """Acceptance criterion: the historical binary evaluate_allowed_families
    path (no training_policy_intent supplied at all) remains completely
    unchanged even though binary_result_semantics_intent is present and
    approved -- fixed_configuration is never forced onto binary the way it
    is for continuous_regression."""
    modeling_intent = _modeling_intent_with_binary_training_policy(training_policy_intent=None)
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)

    assert contract["numeric_handling"] == "standardize"
    assert contract["primary_metric"] == "roc_auc"
    assert "selection_mode" not in contract["modeling_constraints"]
    assert contract["result_semantics"]["schema_version"] == "binary-result-semantics.v1"


# ---------------------------------------------------------------------------
# execution_contract.v2 -- strict univariate-forecasting materialization
# (Project Spec S0243). Fixtures are synthetic and dataset-neutral, matching
# the "campaign-response" precedent established above -- no Nottingham-
# specific slug/path/field/cadence/horizon/seasonal period.
# ---------------------------------------------------------------------------


def _approved_forecasting_result_semantics_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        problem_type="univariate_forecasting",
        primary_output="forecast_series",
        output_structure="ordered_forecast_points",
        forecast_value_kind="continuous_numeric",
        review_notes="Reviewed univariate-forecasting result semantics.",
    )
    kwargs.update(overrides)
    return build_univariate_forecasting_result_semantics_intent(**kwargs)


def _approved_forecasting_evaluation_policy_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        primary_metric={"metric_id": "mae"},
        secondary_metrics=[{"metric_id": "seasonal_mase", "seasonal_period": 7}],
        review_notes="Reviewed forecasting evaluation policy.",
    )
    kwargs.update(overrides)
    return build_univariate_forecasting_evaluation_policy_intent(**kwargs)


def _forecasting_fixed_model_configuration(**overrides) -> dict:
    base = dict(
        include_intercept=True,
        linear_time_trend=True,
        seasonal_effects="additive_indicators",
        seasonal_period=7,
        reference_season_position=0,
        trend_origin="development_start",
    )
    base.update(overrides)
    return base


def _forecasting_finalization_policy(**overrides) -> dict:
    base = dict(
        backtesting_refit_each_fold=True,
        final_fit_scope="full_development",
        freeze_before_final_holdout_open=True,
        final_holdout_evaluation_count=1,
        final_holdout_used_for_adjustment=False,
        final_holdout_used_for_model_selection=False,
        no_retuning_after_final_holdout=True,
    )
    base.update(overrides)
    return base


def _approved_forecasting_training_policy_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        selection_mode="fixed_configuration",
        model_selection_performed=False,
        model_family="deterministic_seasonal_trend_ols",
        fixed_model_configuration=_forecasting_fixed_model_configuration(),
        finalization_policy=_forecasting_finalization_policy(),
        review_notes="Reviewed frozen forecasting specification.",
    )
    kwargs.update(overrides)
    return build_univariate_forecasting_training_policy_intent(**kwargs)


def _valid_semantic_intent_v4(
    target_field_name="demand",
    time_index_field_name="period",
    task_type="univariate_forecasting",
    target_value_kind="numeric",
    forecasting_mode="univariate",
    source_exogenous_predictors="forbidden",
    index_value_kind="calendar_period",
    frequency="monthly",
) -> dict:
    return {
        "schema_version": "dataset-semantic-intent.v4",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": "synthetic-series"},
        "authoring_generation_id": "gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": "univariate-predictive-forecasting",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": [
            {"field_name": time_index_field_name, "role": "temporal_index", "include_in_features": False},
            {"field_name": target_field_name, "role": "target", "include_in_features": False},
        ],
        "temporal_semantics": {
            "time_index_field_name": time_index_field_name,
            "index_value_kind": index_value_kind,
            "frequency": frequency,
            "source_exogenous_predictors": source_exogenous_predictors,
        },
        "target_semantics": {
            "target_field_name": target_field_name,
            "task_type": task_type,
            "target_value_kind": target_value_kind,
            "forecasting_mode": forecasting_mode,
            "is_final_training_configuration": False,
        },
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-22T00:00:00+00:00",
    }


def _valid_preparation_recipe_v2(
    target_field_name="demand",
    time_index_field_name="period",
    index_value_kind="calendar_period",
    frequency="monthly",
    forecast_horizon=6,
    backtesting_forecast_horizon=6,
    backtesting_mode="expanding_window",
    fold_count=5,
    temporal_integrity_overrides=None,
    leakage_control_overrides=None,
    sealed_final_holdout_overrides=None,
    problem_type="univariate_forecasting",
    schema_version="candidate-preparation-recipe.v2",
    semantic_intent_ref_schema_version="dataset-semantic-intent.v4",
) -> dict:
    temporal_integrity = {
        "strictly_increasing_index": True,
        "unique_index": True,
        "frequency_contiguous": True,
        "target_missing_values_absent": True,
        "target_values_finite": True,
    }
    temporal_integrity.update(temporal_integrity_overrides or {})

    leakage_controls = {
        "random_shuffle_performed": False,
        "future_targets_used_for_fold_fit": False,
        "final_holdout_used_for_backtesting": False,
        "final_holdout_used_for_model_selection": False,
        "validation_targets_fed_back_within_fold": False,
        "preprocessing_fit_on_validation_or_future": False,
    }
    leakage_controls.update(leakage_control_overrides or {})

    sealed_final_holdout = {
        "start_index_value": "2025-07",
        "end_index_value": "2025-12",
        "observation_count": 6,
        "prospectively_sealed": True,
        "used_for_backtesting": False,
        "used_for_model_selection": False,
    }
    sealed_final_holdout.update(sealed_final_holdout_overrides or {})

    return {
        "schema_version": schema_version,
        "producer": "pipeline/prepare_candidate.py",
        "problem_type": problem_type,
        "discovery_evidence_ref": {
            "path": "evidence/discovery/synthetic-series.json",
            "schema_version": "dataset-discovery-evidence.v1",
        },
        "semantic_intent_ref": {
            "path": "pipeline/dataset-semantic-intent-instances/synthetic-series.json",
            "schema_version": semantic_intent_ref_schema_version,
            "sha256": "a" * 64,
        },
        "semantic_identity_mirror": {
            "time_index_field_name": time_index_field_name,
            "target_field_name": target_field_name,
            "index_value_kind": index_value_kind,
            "frequency": frequency,
        },
        "temporal_integrity": temporal_integrity,
        "forecast_horizon": forecast_horizon,
        "partitions": {
            "development": {
                "start_index_value": "2020-01", "end_index_value": "2025-06", "observation_count": 66,
            },
            "sealed_final_holdout": sealed_final_holdout,
        },
        "backtesting": {
            "mode": backtesting_mode,
            "initial_training_observations": 36,
            "forecast_horizon": backtesting_forecast_horizon,
            "origin_step_observations": 1,
            "fold_count": fold_count,
            "validation_targets_overlap": False,
        },
        "fold_schedule": [
            {
                "fold_index": 1, "training_observations": 36, "forecast_origin": "2023-01",
                "validation_start": "2023-02", "validation_end": "2023-07", "validation_observations": 6,
            }
        ],
        "leakage_controls": leakage_controls,
        "preparation_boundary_confirmations": {
            "model_training_performed": False,
            "release_publication_performed": False,
            "hidden_notebook_transformations": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
        "generated_at": "2026-08-22T00:00:00+00:00",
    }


def _modeling_intent_for_forecasting(
    forecasting_result_semantics_intent=_MISSING,
    forecasting_evaluation_policy_intent=_MISSING,
    forecasting_training_policy_intent=_MISSING,
    binary_result_semantics_intent=None,
    multiclass_result_semantics_intent=None,
    continuous_regression_result_semantics_intent=None,
) -> dict:
    training_policy_intent = (
        _approved_continuous_regression_training_policy_intent()
        if continuous_regression_result_semantics_intent is not None
        else None
    )
    return {
        "training_policy_intent": training_policy_intent,
        "artifact_type": "dataset_modeling_intent",
        "contract_version": "dataset_modeling_intent.v1",
        "dataset_identity": {
            "dataset_slug": "synthetic-series",
            "dataset_source_ref": "data/raw/synthetic-series.csv",
        },
        "target_intent": {
            "target_column": "demand",
            "task_type": "univariate_forecasting",
            "observed_labels": [],
            "positive_label_candidate": None,
            "observed_target_distribution": {},
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [],
        "initial_feature_candidates": ["age", "channel", "opted_in"],
        "categorical_domain_intent": [],
        "binary_result_semantics_intent": binary_result_semantics_intent,
        "multiclass_result_semantics_intent": multiclass_result_semantics_intent,
        "continuous_regression_result_semantics_intent": continuous_regression_result_semantics_intent,
        "univariate_forecasting_result_semantics_intent": (
            _approved_forecasting_result_semantics_intent()
            if forecasting_result_semantics_intent is _MISSING
            else forecasting_result_semantics_intent
        ),
        "univariate_forecasting_evaluation_policy_intent": (
            _approved_forecasting_evaluation_policy_intent()
            if forecasting_evaluation_policy_intent is _MISSING
            else forecasting_evaluation_policy_intent
        ),
        "univariate_forecasting_training_policy_intent": (
            _approved_forecasting_training_policy_intent()
            if forecasting_training_policy_intent is _MISSING
            else forecasting_training_policy_intent
        ),
    }


def test_execution_contract_v2_materializes_from_approved_fixtures():
    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent,
        {"generation_settings": {"seed": 0}},
        _valid_preparation_recipe_v2(),
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert contract["contract_version"] == EXECUTION_CONTRACT_V2_CONTRACT_VERSION
    assert contract["problem_type"] == "univariate_forecasting"
    assert contract["result_semantics"]["schema_version"] == "univariate-forecasting-result-semantics.v1"
    assert contract["result_semantics"]["primary_output"] == "forecast_series"
    assert contract["result_semantics"]["output_structure"] == "ordered_forecast_points"
    assert contract["result_semantics"]["forecast_value_kind"] == "continuous_numeric"
    assert contract["result_semantics"]["forecast_count_source"] == "forecast_horizon"
    assert contract["training_policy"] == {
        "schema_version": "univariate-forecasting-training-policy.v1",
        "selection_mode": "fixed_configuration",
        "model_selection_performed": False,
        "model_family": "deterministic_seasonal_trend_ols",
        "fixed_model_configuration": _forecasting_fixed_model_configuration(),
        "finalization_policy": _forecasting_finalization_policy(),
    }


def test_execution_contract_v2_forecast_horizon_sourced_from_preparation():
    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent,
        {},
        _valid_preparation_recipe_v2(forecast_horizon=9, backtesting_forecast_horizon=9),
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert contract["forecast_horizon"] == 9


def test_execution_contract_v2_identities_sourced_from_semantic_intent():
    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent,
        {},
        _valid_preparation_recipe_v2(
            target_field_name="units_sold", time_index_field_name="week", frequency="weekly",
        ),
        semantic_intent=_valid_semantic_intent_v4(
            target_field_name="units_sold", time_index_field_name="week", frequency="weekly",
        ),
    )
    assert contract["target_column"] == "units_sold"
    assert contract["time_index_column"] == "week"
    assert contract["frequency"] == "weekly"


def test_execution_contract_v2_carries_no_feature_columns():
    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
    )
    assert "feature_columns" not in contract
    assert "split_policy" not in contract
    assert "modeling_constraints" not in contract


def test_execution_contract_v2_carries_no_full_fold_schedule_or_future_forecast_points():
    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
    )
    assert "fold_schedule" not in contract["temporal_evaluation"]
    for forbidden in ("period", "timestamp", "forecast", "forecast_points", "predicted_value"):
        assert forbidden not in contract["result_semantics"]


def test_execution_contract_v2_pending_result_intent_does_not_materialize():
    modeling_intent = _modeling_intent_for_forecasting(
        forecasting_result_semantics_intent=_approved_forecasting_result_semantics_intent(
            review_status="pending_review"
        )
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_pending_evaluation_policy_does_not_materialize():
    modeling_intent = _modeling_intent_for_forecasting(
        forecasting_evaluation_policy_intent=_approved_forecasting_evaluation_policy_intent(
            review_status="pending_review"
        )
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_missing_evaluation_policy_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting(forecasting_evaluation_policy_intent=None)
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_missing_semantic_intent_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=None
        )


def test_execution_contract_v2_wrong_semantic_intent_version_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    semantic_intent = _valid_semantic_intent_v4()
    semantic_intent["schema_version"] = "dataset-semantic-intent.v3"
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=semantic_intent
        )


def test_execution_contract_v2_wrong_semantic_task_type_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    semantic_intent = _valid_semantic_intent_v4(task_type="multiclass_classification")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=semantic_intent
        )


def test_execution_contract_v2_wrong_forecasting_mode_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    semantic_intent = _valid_semantic_intent_v4(forecasting_mode="multivariate")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=semantic_intent
        )


def test_execution_contract_v2_wrong_target_value_kind_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    semantic_intent = _valid_semantic_intent_v4(target_value_kind="continuous_numeric")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=semantic_intent
        )


def test_execution_contract_v2_source_exogenous_predictors_mismatch_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    semantic_intent = _valid_semantic_intent_v4(source_exogenous_predictors="allowed")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=semantic_intent
        )


def test_execution_contract_v2_missing_preparation_recipe_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, None, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_wrong_preparation_recipe_version_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(schema_version="candidate-preparation-recipe.v1")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_wrong_preparation_recipe_problem_type_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(problem_type="continuous_regression")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_target_identity_mismatch_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(target_field_name="other_target")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_time_index_identity_mismatch_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(time_index_field_name="other_period")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_frequency_mismatch_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(frequency="weekly")
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_horizon_backtesting_mismatch_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(forecast_horizon=6, backtesting_forecast_horizon=12)
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


@pytest.mark.parametrize(
    "key",
    [
        "strictly_increasing_index", "unique_index", "frequency_contiguous",
        "target_missing_values_absent", "target_values_finite",
    ],
)
def test_execution_contract_v2_invalid_temporal_integrity_fails_closed(key):
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(temporal_integrity_overrides={key: False})
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


@pytest.mark.parametrize(
    "key",
    [
        "random_shuffle_performed", "future_targets_used_for_fold_fit",
        "final_holdout_used_for_backtesting", "final_holdout_used_for_model_selection",
        "validation_targets_fed_back_within_fold", "preprocessing_fit_on_validation_or_future",
    ],
)
def test_execution_contract_v2_invalid_leakage_control_fails_closed(key):
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(leakage_control_overrides={key: True})
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_unsealed_final_holdout_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(
        sealed_final_holdout_overrides={"prospectively_sealed": False}
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_consumed_final_holdout_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2(
        sealed_final_holdout_overrides={"used_for_backtesting": True}
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, preparation_recipe, semantic_intent=_valid_semantic_intent_v4()
        )


# ---------------------------------------------------------------------------
# execution_contract.v2 -- forecasting training-policy materialization
# (Project Spec S0244)
# ---------------------------------------------------------------------------


def test_execution_contract_v2_training_policy_missing_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting(forecasting_training_policy_intent=None)
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_training_policy_pending_fails_closed():
    modeling_intent = _modeling_intent_for_forecasting(
        forecasting_training_policy_intent=_approved_forecasting_training_policy_intent(
            review_status="pending_review"
        )
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_training_policy_malformed_fixed_configuration_fails_closed():
    # A hand-built (not builder-validated) modeling intent, mirroring how
    # test_execution_contract_v2_wrong_semantic_intent_version_fails_closed
    # mutates an already-built object to exercise contract_derivation's own
    # independent re-validation rather than the discovery_evidence builder's.
    training_policy_intent = _approved_forecasting_training_policy_intent()
    del training_policy_intent["fixed_model_configuration"]["seasonal_period"]
    modeling_intent = _modeling_intent_for_forecasting(
        forecasting_training_policy_intent=training_policy_intent
    )
    with pytest.raises(ExecutionContractV2ValidationError):
        _build_execution_contract(
            modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
        )


def test_execution_contract_v2_training_policy_unknown_family_fails_closed():
    with pytest.raises(ValueError):
        _approved_forecasting_training_policy_intent(model_family="seasonal_naive")


def test_execution_contract_v2_training_policy_seasonal_period_reference_mismatch_fails_closed():
    with pytest.raises(ValueError):
        _approved_forecasting_training_policy_intent(
            fixed_model_configuration=_forecasting_fixed_model_configuration(
                seasonal_period=7, reference_season_position=7
            )
        )


def test_execution_contract_v2_training_policy_review_notes_do_not_leak_into_contract():
    modeling_intent = _modeling_intent_for_forecasting(
        forecasting_training_policy_intent=_approved_forecasting_training_policy_intent(
            review_notes="internal reviewer note that must never appear on the execution contract"
        )
    )
    contract = _build_execution_contract(
        modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
    )
    assert "review_status" not in contract["training_policy"]
    assert "review_notes" not in contract["training_policy"]
    assert set(contract["training_policy"].keys()) == {
        "schema_version",
        "selection_mode",
        "model_selection_performed",
        "model_family",
        "fixed_model_configuration",
        "finalization_policy",
    }


def test_execution_contract_v2_training_policy_projection_evidence_reduced_facts():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2()
    semantic_intent = _valid_semantic_intent_v4()
    contract = _build_execution_contract(
        modeling_intent, {}, preparation_recipe, semantic_intent=semantic_intent
    )
    evidence = _build_execution_contract_v2_materialization_evidence(
        modeling_intent,
        preparation_recipe,
        contract,
        execution_contract_relative_path="contracts/synthetic-series/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path=None,
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        semantic_intent=semantic_intent,
        semantic_intent_relative_path=None,
        generated_at="2026-08-22T00:00:00+00:00",
    )
    assert evidence["training_policy_schema_version"] == "univariate-forecasting-training-policy.v1"
    assert evidence["training_policy_selection_mode"] == "fixed_configuration"
    assert evidence["training_policy_model_selection_performed"] is False
    assert evidence["training_policy_model_family"] == "deterministic_seasonal_trend_ols"


def test_execution_contract_v1_tabular_path_unaffected_by_forecasting_training_policy():
    modeling_intent = _modeling_intent_for_result_semantics(
        binary_result_semantics_intent=_approved_binary_result_semantics_intent()
    )
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None
    )
    assert contract["contract_version"] == "execution_contract.v1"
    assert "training_policy" not in contract


def test_execution_contract_v1_never_enters_forecasting_training_policy_intent_path():
    modeling_intent = _modeling_intent_for_result_semantics(
        binary_result_semantics_intent=_approved_binary_result_semantics_intent()
    )
    modeling_intent["univariate_forecasting_training_policy_intent"] = None
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None
    )
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_binary_and_forecasting_intents_conflict():
    modeling_intent = _modeling_intent_for_forecasting(
        binary_result_semantics_intent=_approved_binary_result_semantics_intent()
    )
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None,
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert "result_semantics" not in contract
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_multiclass_and_forecasting_intents_conflict():
    modeling_intent = _modeling_intent_for_forecasting(
        multiclass_result_semantics_intent=_approved_multiclass_result_semantics_intent()
    )
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None,
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert "result_semantics" not in contract
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_continuous_regression_and_forecasting_intents_conflict():
    modeling_intent = _modeling_intent_for_forecasting(
        continuous_regression_result_semantics_intent=_approved_continuous_regression_result_semantics_intent()
    )
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None,
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert "result_semantics" not in contract
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_binary_multiclass_continuous_regression_forecasting_four_way_conflict():
    modeling_intent = _modeling_intent_for_forecasting(
        binary_result_semantics_intent=_approved_binary_result_semantics_intent(),
        multiclass_result_semantics_intent=_approved_multiclass_result_semantics_intent(),
        continuous_regression_result_semantics_intent=_approved_continuous_regression_result_semantics_intent(),
    )
    contract = _build_execution_contract(
        modeling_intent, _discovery_evidence_for_result_semantics(), None,
        semantic_intent=_valid_semantic_intent_v4(),
    )
    assert "result_semantics" not in contract
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_absence_of_all_four_result_intents_still_omits_result_semantics():
    modeling_intent = _modeling_intent_for_result_semantics(binary_result_semantics_intent=None)
    modeling_intent["multiclass_result_semantics_intent"] = None
    modeling_intent["continuous_regression_result_semantics_intent"] = None
    modeling_intent["univariate_forecasting_result_semantics_intent"] = None
    contract = _build_execution_contract(modeling_intent, _discovery_evidence_for_result_semantics(), None)
    assert "result_semantics" not in contract
    assert contract["contract_version"] == "execution_contract.v1"


def test_execution_contract_v2_validates_against_schema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    modeling_intent = _modeling_intent_for_forecasting()
    contract = _build_execution_contract(
        modeling_intent, {}, _valid_preparation_recipe_v2(), semantic_intent=_valid_semantic_intent_v4()
    )
    jsonschema.validate(contract, schema)


def test_execution_contract_v2_materialization_evidence_is_reduced_and_deterministic():
    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2()
    semantic_intent = _valid_semantic_intent_v4()
    contract = _build_execution_contract(
        modeling_intent, {}, preparation_recipe, semantic_intent=semantic_intent
    )
    evidence = _build_execution_contract_v2_materialization_evidence(
        modeling_intent,
        preparation_recipe,
        contract,
        execution_contract_relative_path="contracts/synthetic-series/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path="pipeline/preparation-recipe-instances/synthetic-series.json",
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        semantic_intent=semantic_intent,
        semantic_intent_relative_path="pipeline/dataset-semantic-intent-instances/synthetic-series.json",
        generated_at="2026-08-22T00:00:00+00:00",
    )
    assert evidence["requested_variant"] == "univariate_forecasting"
    assert evidence["execution_contract_version"] == "execution_contract.v2"
    assert evidence["materialized_result_schema_version"] == "univariate-forecasting-result-semantics.v1"
    assert evidence["semantic_intent_schema_version"] == "dataset-semantic-intent.v4"
    assert evidence["preparation_recipe_schema_version"] == "candidate-preparation-recipe.v2"
    assert evidence["forecast_horizon"] == 6
    assert evidence["backtesting_mode"] == "expanding_window"
    assert evidence["fold_count"] == 5
    assert evidence["primary_metric_id"] == "mae"
    assert evidence["secondary_metric_ids"] == ["seasonal_mase"]
    assert evidence["no_defaults_inferred"] is True
    assert evidence["readiness"] == "materialized"
    assert evidence["blocking_reasons"] == []
    for forbidden_key in (
        "raw_target_values", "fold_target_arrays", "future_result_rows", "model_bytes",
        "coefficients", "predictions", "residuals", "external_study_path",
    ):
        assert forbidden_key not in evidence

    second_evidence = _build_execution_contract_v2_materialization_evidence(
        modeling_intent,
        preparation_recipe,
        contract,
        execution_contract_relative_path="contracts/synthetic-series/execution-contract.json",
        discovery_evidence_relative_path=None,
        preparation_recipe_relative_path="pipeline/preparation-recipe-instances/synthetic-series.json",
        prepared_data_metadata_relative_path=None,
        modeling_intent_relative_path=None,
        public_context_relative_path=None,
        raw_dataset_relative_path=None,
        semantic_intent=semantic_intent,
        semantic_intent_relative_path="pipeline/dataset-semantic-intent-instances/synthetic-series.json",
        generated_at="2026-08-22T00:00:00+00:00",
    )
    assert evidence == second_evidence


def test_materialize_execution_contract_writes_v2_and_v2_evidence(tmp_path):
    schema_dir = tmp_path / "contracts"
    schema_dir.mkdir()
    schema_path = Path(__file__).parent.parent / "contracts" / "execution-contract.schema.json"
    (schema_dir / "execution-contract.schema.json").write_text(
        schema_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    modeling_intent = _modeling_intent_for_forecasting()
    preparation_recipe = _valid_preparation_recipe_v2()
    semantic_intent = _valid_semantic_intent_v4()
    result = materialize_execution_contract(
        modeling_intent,
        {},
        "contracts/synthetic-series/execution-contract.json",
        tmp_path,
        preparation_recipe=preparation_recipe,
        evidence_output_relative_path="evidence/synthetic-series/execution-contract-materialization-evidence.json",
        semantic_intent=semantic_intent,
        generated_at="2026-08-22T00:00:00+00:00",
    )
    assert result["execution_contract"]["contract_version"] == "execution_contract.v2"
    assert result["execution_contract_materialization_evidence"]["requested_variant"] == (
        "univariate_forecasting"
    )
    written_contract = json.loads(
        (tmp_path / "contracts/synthetic-series/execution-contract.json").read_text(encoding="utf-8")
    )
    assert written_contract["contract_version"] == "execution_contract.v2"
