import json
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
