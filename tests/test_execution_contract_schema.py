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
