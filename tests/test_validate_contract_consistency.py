import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.derive_projections import derive
from pipeline.validate_contract_consistency import (
    ConsistencyCheckFailed,
    check,
    check_contract_layer_consistency,
)

REPO_ROOT = Path(__file__).parent.parent


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_evidence(
    row_count: int = 10000,
    fields: list | None = None,
) -> dict:
    """Minimal valid discovery evidence dict conforming to dataset-discovery-evidence.v1."""
    if fields is None:
        fields = [
            {
                "name": "age",
                "inferred_type": "integer",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 50,
                "sample_min": 18,
                "sample_max": 95,
            },
            {
                "name": "category",
                "inferred_type": "string",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 3,
                "sample_min": "a",
                "sample_max": "c",
            },
            {
                "name": "flag",
                "inferred_type": "boolean",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 2,
                "sample_min": False,
                "sample_max": True,
            },
            {
                "name": "outcome",
                "inferred_type": "integer",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 2,
                "sample_min": 0,
                "sample_max": 1,
            },
        ]
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "producer": "pipeline/discovery_evidence.py",
        "dataset_metadata": {
            "name": "test-dataset",
            "row_count": row_count,
            "column_count": len(fields),
            "source_path": "data/test.csv",
        },
        "field_observations": fields,
        "duplicated_rows_count": 0,
        "candidate_categorical_fields": ["category"],
        "candidate_target_columns": [
            {"name": "outcome", "is_authoritative": False}
        ],
        "generation_settings": {"seed": 42, "generator_version": "1.0.0"},
        "generated_at": "2026-06-24T00:00:00Z",
        "discovery_boundary_confirmations": {
            "contract_promotion_occurred": False,
            "model_training_occurred": False,
            "release_publication_occurred": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }


def _valid_contract(
    feature_columns: list | None = None,
    feature_definitions: dict | None = None,
    target_column: str = "outcome",
    train_ratio: float = 0.7,
) -> dict:
    """Minimal valid execution contract dict conforming to execution_contract.v1."""
    if feature_columns is None:
        feature_columns = ["age", "category", "flag"]
    if feature_definitions is None:
        feature_definitions = {
            "age": {"type": "numeric"},
            "category": {"type": "categorical"},
            "flag": {"type": "boolean"},
        }
    missing_value_policy = {
        col: "median"
        if feature_definitions.get(col, {}).get("type") == "numeric"
        else "mode"
        for col in feature_columns
    }
    val_ratio = (1.0 - train_ratio) / 2
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "test-dataset",
        "target_column": target_column,
        "feature_columns": feature_columns,
        "ignored_columns": [],
        "required_columns": feature_columns,
        "optional_columns": [],
        "feature_definitions": feature_definitions,
        "missing_value_policy": missing_value_policy,
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "test_ratio": val_ratio,
        },
        "random_seed": None,
        "primary_metric": "roc_auc",
        "secondary_metrics": [],
        "modeling_constraints": {
            "allowed_model_families": ["logistic_regression", "gradient_boosting"],
            "no_automl": True,
            "max_training_time_seconds": None,
        },
    }


def test_consistent_contract_passes(tmp_path):
    """A contract with compatible types, all columns present, and sufficient rows passes."""
    contract_path = _write_json(tmp_path, "contract.json", _valid_contract())
    evidence_path = _write_json(tmp_path, "evidence.json", _valid_evidence())
    check(contract_path, evidence_path, repo_root=REPO_ROOT)  # must not raise


def test_missing_feature_column_fails(tmp_path):
    """A feature column absent from discovery raises ConsistencyCheckFailed with a field-level error."""
    contract = _valid_contract(
        feature_columns=["age", "missing_col"],
        feature_definitions={
            "age": {"type": "numeric"},
            "missing_col": {"type": "categorical"},
        },
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    evidence_path = _write_json(tmp_path, "evidence.json", _valid_evidence())
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("missing_col" in e for e in errors)
    assert any("absent from discovery" in e for e in errors)


def test_missing_target_column_fails(tmp_path):
    """A target_column absent from discovery raises ConsistencyCheckFailed with a field-level error."""
    contract = _valid_contract(target_column="missing_target")
    contract_path = _write_json(tmp_path, "contract.json", contract)
    evidence_path = _write_json(tmp_path, "evidence.json", _valid_evidence())
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("missing_target" in e for e in errors)
    assert any("target_column" in e for e in errors)


def test_type_incompatible_feature_fails(tmp_path):
    """A feature whose declared type is incompatible with discovery inferred_type raises ConsistencyCheckFailed."""
    # 'age' is inferred as 'integer' (numeric family) but declared as 'categorical' — incompatible.
    contract = _valid_contract(
        feature_columns=["age", "category", "flag"],
        feature_definitions={
            "age": {"type": "categorical"},  # wrong: integer is not in categorical's compat set
            "category": {"type": "categorical"},
            "flag": {"type": "boolean"},
        },
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    evidence_path = _write_json(tmp_path, "evidence.json", _valid_evidence())
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("age" in e and "categorical" in e and "integer" in e for e in errors)


def test_split_policy_too_small_fails(tmp_path):
    """floor(row_count * train_ratio) < 50 raises ConsistencyCheckFailed."""
    # row_count=60, train_ratio=0.7 -> floor(42.0) = 42 < 50
    contract = _valid_contract(train_ratio=0.7)
    evidence = _valid_evidence(row_count=60)
    contract_path = _write_json(tmp_path, "contract.json", contract)
    evidence_path = _write_json(tmp_path, "evidence.json", evidence)
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("split policy" in e for e in errors)
    assert any("42" in e for e in errors)


def test_invalid_contract_schema_fails(tmp_path):
    """A structurally invalid execution contract raises ConsistencyCheckFailed before consistency checks."""
    invalid_contract = {"contract_version": "execution_contract.v1"}  # missing required fields
    contract_path = _write_json(tmp_path, "contract.json", invalid_contract)
    evidence_path = _write_json(tmp_path, "evidence.json", _valid_evidence())
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    assert any("contract schema validation failed" in e for e in exc_info.value.errors)


def test_invalid_evidence_schema_fails(tmp_path):
    """A structurally invalid discovery evidence JSON raises ConsistencyCheckFailed before consistency checks."""
    invalid_evidence = {"schema_version": "dataset-discovery-evidence.v1"}  # missing required fields
    contract_path = _write_json(tmp_path, "contract.json", _valid_contract())
    evidence_path = _write_json(tmp_path, "evidence.json", invalid_evidence)
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check(contract_path, evidence_path, repo_root=REPO_ROOT)
    assert any("evidence schema validation failed" in e for e in exc_info.value.errors)


def test_empty_inferred_type_passes(tmp_path):
    """A field with inferred_type 'empty' passes type compatibility for any declared type."""
    # 'age' is 100% null — no non-null values observed, so no empirical contradiction.
    evidence = _valid_evidence(
        fields=[
            {
                "name": "age",
                "inferred_type": "empty",
                "null_count": 10000,
                "null_rate": 1.0,
                "cardinality": 0,
                "sample_min": None,
                "sample_max": None,
            },
            {
                "name": "outcome",
                "inferred_type": "integer",
                "null_count": 0,
                "null_rate": 0.0,
                "cardinality": 2,
                "sample_min": 0,
                "sample_max": 1,
            },
        ]
    )
    contract = _valid_contract(
        feature_columns=["age"],
        feature_definitions={"age": {"type": "numeric"}},
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    evidence_path = _write_json(tmp_path, "evidence.json", evidence)
    check(contract_path, evidence_path, repo_root=REPO_ROOT)  # must not raise


# ---------------------------------------------------------------------------
# Real materialized Telco artifact consistency check (Project Spec S0024).
#
# Cross-checks the actual, on-disk materialized Telco execution contract
# against the actual, on-disk Telco discovery evidence -- proving the
# materialization flow produces a contract consistent with real discovery
# evidence, not just synthetic fixtures.
# ---------------------------------------------------------------------------

TELCO_EXECUTION_CONTRACT_PATH = (
    REPO_ROOT / "contracts" / "telco-customer-churn" / "execution-contract.json"
)
TELCO_DISCOVERY_EVIDENCE_PATH = (
    REPO_ROOT / "pipeline" / "evidence" / "telco-customer-churn" / "discovery-evidence.json"
)


@pytest.mark.skipif(
    not (TELCO_EXECUTION_CONTRACT_PATH.exists() and TELCO_DISCOVERY_EVIDENCE_PATH.exists()),
    reason="Telco execution contract and/or discovery evidence not yet materialized on disk",
)
def test_real_telco_execution_contract_is_consistent_with_real_discovery_evidence():
    check(TELCO_EXECUTION_CONTRACT_PATH, TELCO_DISCOVERY_EVIDENCE_PATH, repo_root=REPO_ROOT)


# ---------------------------------------------------------------------------
# Cross-contract layer consistency (Project Spec S0156): categorical
# scalar-type/known-value/validation-behavior/conditional-policy divergence
# across the execution, runtime, public, and inference-bundle layers of the
# *same* dataset. Distinct from check() above (execution vs. discovery
# evidence). Every fixture is dataset-agnostic.
# ---------------------------------------------------------------------------


def _s0156_execution_contract() -> dict:
    return _valid_contract(
        feature_columns=["total_amount", "tenure_months", "plan_type", "account_id_flag"],
        feature_definitions={
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
        },
    )


def _s0156_projected(tmp_path: Path):
    contract = _s0156_execution_contract()
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    public = json.loads((out_dir / "public-contract.json").read_text())
    return contract, runtime, public


def test_layer_consistency_passes_for_a_correctly_projected_contract(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    check_contract_layer_consistency(contract, runtime, public)  # must not raise


def test_layer_consistency_detects_categorical_scalar_type_mismatch(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    for feature in runtime["features"]:
        if feature["name"] == "account_id_flag":
            feature["domain_constraints"]["categorical_value_type"] = "string"
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("scalar type mismatch" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_known_value_divergence(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    for feature in runtime["features"]:
        if feature["name"] == "plan_type":
            feature["domain_constraints"]["known_values"] = ["pro", "basic"]
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("known-value" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_validation_behavior_mismatch(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    for feature in runtime["features"]:
        if feature["name"] == "plan_type":
            feature["domain_constraints"]["validation_behavior"] = "reject_unknown"
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("validation_behavior mismatch" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_conditional_policy_missing_from_runtime(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    runtime["features"] = [f for f in runtime["features"] if f["name"] != "total_amount"] + [
        {"name": "total_amount", "type": "numeric", "required": True}
    ]
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("missing from the runtime projection" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_condition_reference_to_unknown_field(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["when"]["field"] = "not_a_real_field"
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("unknown field" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_condition_self_reference():
    contract = _s0156_execution_contract()
    contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["when"]["field"] = "total_amount"
    runtime = {
        "schema_version": "1.0.0",
        "features": [
            {
                "name": "total_amount",
                "type": "numeric",
                "required": True,
                "input_policy": contract["feature_definitions"]["total_amount"]["input_policy"],
            },
        ],
    }
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, {"schema_version": "1.0.0", "features": []})
    assert any("references itself" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_condition_comparison_type_mismatch():
    contract = _s0156_execution_contract()
    contract["feature_definitions"]["total_amount"]["input_policy"][
        "conditional_blank_normalization"
    ]["when"] = {"field": "plan_type", "operator": "equals", "value": 0}
    runtime = {
        "schema_version": "1.0.0",
        "features": [
            {
                "name": "total_amount",
                "type": "numeric",
                "required": True,
                "input_policy": contract["feature_definitions"]["total_amount"]["input_policy"],
            },
            {"name": "plan_type", "type": "categorical", "required": True},
        ],
    }
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, {"schema_version": "1.0.0", "features": []})
    assert any("incompatible" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_public_select_serialization_hint_mismatch(tmp_path):
    contract, runtime, public = _s0156_projected(tmp_path)
    for feature in public["features"]:
        if feature["name"] == "account_id_flag":
            feature["select_value_type"] = "string"
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, runtime, public)
    assert any("select_value_type" in e for e in exc_info.value.errors)


def test_layer_consistency_detects_inference_bundle_claim_without_matching_runtime_contract():
    contract = _s0156_execution_contract()
    bundle = {"input_schema": {"input_policy_source": "runtime_contract"}}
    empty_runtime = {"schema_version": "1.0.0", "features": []}
    empty_public = {"schema_version": "1.0.0", "features": []}
    with pytest.raises(ConsistencyCheckFailed) as exc_info:
        check_contract_layer_consistency(contract, empty_runtime, empty_public, bundle)
    assert any("inference bundle claims" in e for e in exc_info.value.errors)


def test_layer_consistency_rejects_legacy_and_new_categorical_contradiction_at_schema_layer():
    """Project Spec S0156: the execution schema itself (oneOf values/
    known_values) is where a contradictory dual categorical declaration is
    rejected -- confirmed here as a schema-level failure, not a layer-
    consistency-level one, so this is deliberately a schema assertion."""
    import jsonschema

    schema = json.loads((REPO_ROOT / "contracts" / "execution-contract.schema.json").read_text())
    contract = _s0156_execution_contract()
    contract["feature_definitions"]["plan_type"]["domain_constraints"]["values"] = ["basic", "pro"]
    validator = jsonschema.Draft7Validator(schema)
    assert list(validator.iter_errors(contract))
