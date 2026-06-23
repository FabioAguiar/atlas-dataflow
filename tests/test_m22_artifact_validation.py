"""
Tests for the M22-05 artifact validation and hash recording pipeline.

Validates hash computation, candidate hash conditionality, discovery evidence
completeness, contract draft non-executable status, preparation recipe
traceability, boundary confirmations, and validation record structure.

Uses synthetic fixture inputs only; does not depend on live dataset output or
the data/ directory.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.validate_artifacts import (
    validate_artifacts,
    write_artifact_validation_record,
)

REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

FIXTURE_COLUMNS = ["age", "job", "balance", "label"]
FIXTURE_ROWS = [
    {"age": "25", "job": "admin",   "balance": "1000", "label": "yes"},
    {"age": "30", "job": "tech",    "balance": "2500", "label": "no"},
    {"age": "17", "job": "student", "balance": "0",    "label": "no"},
    {"age": "45", "job": "admin",   "balance": "",     "label": "yes"},
    {"age": "60", "job": "retired", "balance": "5000", "label": "no"},
]

FIXTURE_DISCOVERY_EVIDENCE = {
    "schema_version": "dataset-discovery-evidence.v1",
    "producer": "pipeline/discovery_evidence.py",
    "dataset_metadata": {
        "name": "fixture",
        "row_count": len(FIXTURE_ROWS),
        "column_count": len(FIXTURE_COLUMNS),
        "source_path": "fixture.csv",
    },
    "field_observations": [
        {"name": "age",     "inferred_type": "integer", "null_count": 0, "null_rate": 0.0, "cardinality": 5, "sample_min": 17, "sample_max": 60},
        {"name": "job",     "inferred_type": "string",  "null_count": 0, "null_rate": 0.0, "cardinality": 4, "sample_min": "admin", "sample_max": "tech"},
        {"name": "balance", "inferred_type": "integer", "null_count": 1, "null_rate": 0.2, "cardinality": 4, "sample_min": 0, "sample_max": 5000},
        {"name": "label",   "inferred_type": "string",  "null_count": 0, "null_rate": 0.0, "cardinality": 2, "sample_min": "no", "sample_max": "yes"},
    ],
    "duplicated_rows_count": 0,
    "candidate_categorical_fields": ["job", "label"],
    "candidate_target_columns": [
        {"name": "job",   "is_authoritative": False, "candidate_reason": "low_cardinality_categorical_candidate"},
        {"name": "label", "is_authoritative": False, "candidate_reason": "low_cardinality_categorical_candidate"},
    ],
    "generation_settings": {"seed": 0, "generator_version": "discovery-evidence.v1"},
    "generated_at": "2026-06-23T17:00:00+00:00",
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

FIXTURE_RECIPE_CANDIDATE_PRODUCED = {
    "schema_version": "candidate-preparation-recipe.v1",
    "producer": "pipeline/prepare_candidate.py",
    "dataset_identity": {
        "name": "fixture",
        "row_count_before": 5,
        "column_count_before": 4,
    },
    "discovery_evidence_ref": {
        "path": "discovery-evidence.json",
        "schema_version": "dataset-discovery-evidence.v1",
    },
    "transformations": [
        {
            "transformation_type": "column_selection",
            "description": "Select columns: ['age', 'label']",
            "source_columns": ["age", "label"],
            "target_columns": ["age", "label"],
            "reason": "Declared by preparation rules.",
            "review_status": "explicit",
        }
    ],
    "candidate_output": {
        "produced": True,
        "reason_not_produced": None,
        "row_count_after": 5,
        "column_count_after": 2,
    },
    "candidate_status": {
        "is_final_training_input": False,
        "requires_m23_validation": True,
        "authorized_for": "candidate_only",
    },
    "generation_settings": {
        "generator_version": "prepare-candidate.v1",
        "preparation_rules_source": "rules.json",
    },
    "generated_at": "2026-06-23T18:00:00+00:00",
    "preparation_boundary_confirmations": {
        "complex_feature_engineering_performed": False,
        "model_training_performed": False,
        "release_publication_performed": False,
        "hidden_notebook_transformations": False,
        "inferred_rules_applied_without_approval": False,
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

FIXTURE_RECIPE_NO_CANDIDATE = {
    **{k: v for k, v in FIXTURE_RECIPE_CANDIDATE_PRODUCED.items()},
    "candidate_output": {
        "produced": False,
        "reason_not_produced": "No transformation rules with review_status 'explicit' or 'inferred_approved' were found.",
        "row_count_after": None,
        "column_count_after": None,
    },
    "transformations": [],
}

FIXTURE_CONTRACT_DRAFT = {
    "schema_version": "source-contract-input.v1",
    "dataset_slug": "fixture-dataset",
    "release_id": "release-20260623-001",
    "source_contract_ref": "contracts/runtime-contract.schema.json",
    "source_data_ref": "datasets/fixture/v1",
}


def _write_csv(path: Path, columns: list, rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


@pytest.fixture
def fixture_dataset(tmp_path):
    p = tmp_path / "fixture.csv"
    _write_csv(p, FIXTURE_COLUMNS, FIXTURE_ROWS)
    return p


@pytest.fixture
def fixture_candidate(tmp_path):
    p = tmp_path / "candidate.csv"
    _write_csv(p, ["age", "label"], [{"age": r["age"], "label": r["label"]} for r in FIXTURE_ROWS])
    return p


@pytest.fixture
def fixture_discovery_evidence(tmp_path):
    p = tmp_path / "discovery-evidence.json"
    _write_json(p, FIXTURE_DISCOVERY_EVIDENCE)
    return p


@pytest.fixture
def fixture_recipe_produced(tmp_path):
    p = tmp_path / "recipe-produced.json"
    _write_json(p, FIXTURE_RECIPE_CANDIDATE_PRODUCED)
    return p


@pytest.fixture
def fixture_recipe_no_candidate(tmp_path):
    p = tmp_path / "recipe-no-candidate.json"
    _write_json(p, FIXTURE_RECIPE_NO_CANDIDATE)
    return p


@pytest.fixture
def fixture_contract_draft(tmp_path):
    p = tmp_path / "contract-draft.json"
    _write_json(p, FIXTURE_CONTRACT_DRAFT)
    return p


# ---------------------------------------------------------------------------
# Raw input hash computation (AC-01)
# ---------------------------------------------------------------------------

def test_raw_input_hash_is_recorded(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    assert "raw_input_hash" in record["hash_records"]
    rh = record["hash_records"]["raw_input_hash"]
    assert rh["algorithm"] == "sha256"
    assert rh["hash"] is not None
    assert len(rh["hash"]) == 64


def test_raw_input_hash_is_sha256(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    rh = record["hash_records"]["raw_input_hash"]
    expected = hashlib.sha256(fixture_dataset.read_bytes()).hexdigest()
    assert rh["hash"] == expected


def test_raw_input_hash_path_is_not_absolute(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    rh = record["hash_records"]["raw_input_hash"]
    assert not rh["path"].startswith("/")


def test_missing_raw_dataset_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_artifacts(dataset_path=tmp_path / "nonexistent.csv")


# ---------------------------------------------------------------------------
# Conditional prepared output hash (AC-02)
# ---------------------------------------------------------------------------

def test_prepared_hash_recorded_when_candidate_produced(fixture_candidate, fixture_recipe_produced):
    record = validate_artifacts(
        recipe_path=fixture_recipe_produced,
        candidate_path=fixture_candidate,
    )
    assert "prepared_output_hash" in record["hash_records"]
    ph = record["hash_records"]["prepared_output_hash"]
    assert ph is not None
    assert ph["algorithm"] == "sha256"
    assert len(ph["hash"]) == 64


def test_prepared_hash_is_sha256(fixture_candidate, fixture_recipe_produced):
    record = validate_artifacts(
        recipe_path=fixture_recipe_produced,
        candidate_path=fixture_candidate,
    )
    ph = record["hash_records"]["prepared_output_hash"]
    expected = hashlib.sha256(fixture_candidate.read_bytes()).hexdigest()
    assert ph["hash"] == expected


def test_prepared_hash_absent_when_candidate_not_produced(fixture_candidate, fixture_recipe_no_candidate):
    record = validate_artifacts(
        recipe_path=fixture_recipe_no_candidate,
        candidate_path=fixture_candidate,
    )
    assert record["hash_records"]["prepared_output_hash"] is None
    assert "prepared_output_hash_absent_reason" in record["hash_records"]
    assert record["hash_records"]["prepared_output_hash_absent_reason"]


def test_prepared_hash_absent_when_no_candidate_arg_and_not_produced(fixture_recipe_no_candidate):
    record = validate_artifacts(recipe_path=fixture_recipe_no_candidate)
    assert record["hash_records"].get("prepared_output_hash") is None
    assert "prepared_output_hash_absent_reason" in record["hash_records"]


def test_null_hash_reason_is_informative(fixture_recipe_no_candidate):
    record = validate_artifacts(recipe_path=fixture_recipe_no_candidate)
    reason = record["hash_records"]["prepared_output_hash_absent_reason"]
    assert "produced" in reason.lower() or "false" in reason.lower()


# ---------------------------------------------------------------------------
# Discovery evidence completeness validation (AC-03)
# ---------------------------------------------------------------------------

def test_discovery_evidence_validation_result_present(fixture_discovery_evidence):
    record = validate_artifacts(discovery_evidence_path=fixture_discovery_evidence)
    assert "discovery_evidence" in record["validation_results"]


def test_discovery_evidence_schema_validation_passes(fixture_discovery_evidence):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    record = validate_artifacts(
        discovery_evidence_path=fixture_discovery_evidence,
        repo_root=REPO_ROOT,
    )
    result = record["validation_results"]["discovery_evidence"]
    assert result["schema_validation"]["valid"] is True


def test_discovery_evidence_required_fields_present(fixture_discovery_evidence):
    record = validate_artifacts(discovery_evidence_path=fixture_discovery_evidence)
    result = record["validation_results"]["discovery_evidence"]
    assert result["required_fields_present"] is True


def test_discovery_evidence_dataset_identity_recorded(fixture_discovery_evidence):
    record = validate_artifacts(discovery_evidence_path=fixture_discovery_evidence)
    result = record["validation_results"]["discovery_evidence"]
    identity = result["dataset_identity"]
    assert identity["row_count"] == len(FIXTURE_ROWS)
    assert identity["column_count"] == len(FIXTURE_COLUMNS)


def test_discovery_evidence_boundary_confirmations_all_false(fixture_discovery_evidence):
    record = validate_artifacts(discovery_evidence_path=fixture_discovery_evidence)
    result = record["validation_results"]["discovery_evidence"]
    assert result["discovery_boundary_confirmations_all_false"] is True


def test_missing_discovery_evidence_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_artifacts(discovery_evidence_path=tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# Contract draft non-executable status validation (AC-04)
# ---------------------------------------------------------------------------

def test_contract_draft_validation_result_present(fixture_contract_draft):
    record = validate_artifacts(contract_draft_path=fixture_contract_draft)
    assert "contract_draft" in record["validation_results"]


def test_contract_draft_schema_validation_passes(fixture_contract_draft):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    record = validate_artifacts(
        contract_draft_path=fixture_contract_draft,
        repo_root=REPO_ROOT,
    )
    result = record["validation_results"]["contract_draft"]
    assert result["schema_validation"]["valid"] is True


def test_contract_draft_required_fields_present(fixture_contract_draft):
    record = validate_artifacts(contract_draft_path=fixture_contract_draft)
    result = record["validation_results"]["contract_draft"]
    assert result["required_fields_present"] is True


def test_contract_draft_non_executable_status_confirmed(fixture_contract_draft):
    record = validate_artifacts(contract_draft_path=fixture_contract_draft)
    result = record["validation_results"]["contract_draft"]
    assert result["contract_draft_non_executable_status_confirmed"] is True


def test_contract_draft_non_executable_basis_is_informative(fixture_contract_draft):
    record = validate_artifacts(contract_draft_path=fixture_contract_draft)
    result = record["validation_results"]["contract_draft"]
    assert result["non_executable_status_basis"]
    assert len(result["non_executable_status_basis"]) > 10


def test_contract_draft_missing_field_detected(tmp_path):
    incomplete = {k: v for k, v in FIXTURE_CONTRACT_DRAFT.items() if k != "release_id"}
    p = tmp_path / "incomplete-draft.json"
    _write_json(p, incomplete)
    record = validate_artifacts(contract_draft_path=p)
    result = record["validation_results"]["contract_draft"]
    assert result["required_fields_present"] is False
    assert "release_id" in result["missing_required_fields"]


# ---------------------------------------------------------------------------
# Preparation recipe traceability validation (AC-05)
# ---------------------------------------------------------------------------

def test_recipe_validation_result_present(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    assert "recipe" in record["validation_results"]


def test_recipe_schema_validation_passes(fixture_recipe_produced):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    record = validate_artifacts(recipe_path=fixture_recipe_produced, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is True


def test_recipe_discovery_evidence_ref_path_present(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["traceability"]["discovery_evidence_ref_path_present"] is True
    assert result["traceability"]["discovery_evidence_ref_path"]


def test_recipe_all_transformations_have_review_status(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["traceability"]["all_transformations_have_review_status"] is True


def test_recipe_candidate_status_present(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["traceability"]["candidate_status_present"] is True
    assert result["traceability"]["candidate_status_fields_present"] is True


def test_recipe_transformation_count_recorded(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["traceability"]["transformation_count"] == 1


def test_recipe_no_candidate_traceability_valid(fixture_recipe_no_candidate):
    record = validate_artifacts(recipe_path=fixture_recipe_no_candidate)
    result = record["validation_results"]["recipe"]
    assert result["traceability"]["discovery_evidence_ref_path_present"] is True
    assert result["traceability"]["candidate_status_present"] is True
    assert result["traceability"]["transformation_count"] == 0


# ---------------------------------------------------------------------------
# Boundary confirmations (AC-06)
# ---------------------------------------------------------------------------

def test_recipe_preparation_boundary_confirmations_all_false(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["preparation_boundary_confirmations_all_false"] is True


def test_recipe_preparation_boundary_no_missing_fields(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced)
    result = record["validation_results"]["recipe"]
    assert result["preparation_boundary_confirmations_missing_fields"] == []


def test_recipe_validation_detects_boundary_violation(tmp_path):
    bad_recipe = {
        **FIXTURE_RECIPE_CANDIDATE_PRODUCED,
        "preparation_boundary_confirmations": {
            **FIXTURE_RECIPE_CANDIDATE_PRODUCED["preparation_boundary_confirmations"],
            "model_training_performed": True,
        },
    }
    p = tmp_path / "bad-recipe.json"
    _write_json(p, bad_recipe)
    record = validate_artifacts(recipe_path=p)
    result = record["validation_results"]["recipe"]
    assert result["preparation_boundary_confirmations_all_false"] is False


# ---------------------------------------------------------------------------
# Validation record structure
# ---------------------------------------------------------------------------

def test_validation_record_has_required_top_level_fields(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    for field in [
        "schema_version", "producer", "generated_at", "generator_version",
        "hash_records", "validation_results",
        "preparation_boundary_confirmations", "evidence_policy",
    ]:
        assert field in record, f"Required top-level field missing: {field}"


def test_validation_record_schema_version(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    assert record["schema_version"] == "artifact-validation-record.v1"


def test_validation_record_preparation_boundary_confirmations_all_false(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    bc = record["preparation_boundary_confirmations"]
    for key in [
        "complex_feature_engineering_performed",
        "model_training_performed",
        "release_publication_performed",
        "hidden_notebook_transformations",
        "inferred_rules_applied_without_approval",
    ]:
        assert bc[key] is False, f"preparation_boundary_confirmations.{key} must be False"


def test_validation_record_evidence_policy_all_set(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    policy = record["evidence_policy"]
    for key in [
        "raw_logs_prohibited",
        "raw_runtime_prohibited",
        "raw_api_payloads_prohibited",
        "secrets_prohibited",
        "private_source_paths_prohibited",
        "reduced_and_sanitized",
    ]:
        assert policy[key] is True, f"evidence_policy.{key} must be True"


def test_validation_record_producer_field(fixture_dataset):
    record = validate_artifacts(dataset_path=fixture_dataset)
    assert record["producer"] == "pipeline/validate_artifacts.py"


# ---------------------------------------------------------------------------
# Full combined validation run
# ---------------------------------------------------------------------------

def test_full_run_with_candidate_produced(
    fixture_dataset, fixture_discovery_evidence, fixture_recipe_produced, fixture_candidate
):
    record = validate_artifacts(
        dataset_path=fixture_dataset,
        discovery_evidence_path=fixture_discovery_evidence,
        recipe_path=fixture_recipe_produced,
        candidate_path=fixture_candidate,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    assert record["hash_records"]["raw_input_hash"]["hash"] is not None
    assert record["hash_records"]["prepared_output_hash"]["hash"] is not None
    assert "discovery_evidence" in record["validation_results"]
    assert "recipe" in record["validation_results"]
    assert record["preparation_boundary_confirmations"]["model_training_performed"] is False


def test_full_run_with_no_candidate(
    fixture_dataset, fixture_discovery_evidence, fixture_recipe_no_candidate
):
    record = validate_artifacts(
        dataset_path=fixture_dataset,
        discovery_evidence_path=fixture_discovery_evidence,
        recipe_path=fixture_recipe_no_candidate,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    assert record["hash_records"]["raw_input_hash"]["hash"] is not None
    assert record["hash_records"]["prepared_output_hash"] is None
    assert record["hash_records"]["prepared_output_hash_absent_reason"]


def test_full_run_with_contract_draft(
    fixture_dataset, fixture_discovery_evidence,
    fixture_recipe_produced, fixture_candidate, fixture_contract_draft
):
    record = validate_artifacts(
        dataset_path=fixture_dataset,
        discovery_evidence_path=fixture_discovery_evidence,
        recipe_path=fixture_recipe_produced,
        candidate_path=fixture_candidate,
        contract_draft_path=fixture_contract_draft,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    assert "contract_draft" in record["validation_results"]
    assert record["validation_results"]["contract_draft"]["contract_draft_non_executable_status_confirmed"] is True


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_output_same_inputs(fixture_dataset):
    fixed_ts = "2026-06-23T23:00:00+00:00"
    r1 = validate_artifacts(dataset_path=fixture_dataset, generated_at=fixed_ts)
    r2 = validate_artifacts(dataset_path=fixture_dataset, generated_at=fixed_ts)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# ---------------------------------------------------------------------------
# Write helper
# ---------------------------------------------------------------------------

def test_write_artifact_validation_record(tmp_path, fixture_dataset):
    record = validate_artifacts(
        dataset_path=fixture_dataset,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    out = tmp_path / "validation-record.json"
    write_artifact_validation_record(out, record)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "artifact-validation-record.v1"
    assert loaded["hash_records"]["raw_input_hash"]["hash"] is not None
