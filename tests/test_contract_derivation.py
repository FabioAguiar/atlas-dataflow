import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.contract_derivation import (
    EXECUTION_CONTRACT_DRAFT_CONTRACT_VERSION,
    _check_safety,
    _derive_public_contract,
    _derive_public_feature,
    _derive_public_options,
    _fresh_label,
    project_execution_contract_draft,
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
                "notebooks/datasets/telco-customer-churn/01_dataset_authoring.ipynb"
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
        "notebooks/datasets/telco-customer-churn/01_dataset_authoring.ipynb"
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
