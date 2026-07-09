import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.validate_contract_consistency import ConsistencyCheckFailed, check

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
