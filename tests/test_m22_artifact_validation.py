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


# ---------------------------------------------------------------------------
# S0242 -- governed temporal preparation and backtesting (candidate-preparation-recipe.v2)
# ---------------------------------------------------------------------------
#
# Synthetic-only fixtures. No live dataset or external scientific artifact is
# used. These tests prove: (1) v1 fixtures/behavior above are untouched by
# this section; (2) validate_artifacts() dispatches recipe validation by
# explicit schema_version; (3) a valid synthetic v2 temporal recipe validates
# end to end; (4) each governed v2 arithmetic/state rejection is enforced
# (schema-level or cross-field validator-level); (5) unknown/missing recipe
# schema_version fails closed rather than silently being treated as v1.

def _v2_fold(index, initial_training, origin_step, horizon):
    training = initial_training + (index - 1) * origin_step
    origin = training
    return {
        "fold_index": index,
        "training_observations": training,
        "forecast_origin": str(origin),
        "validation_start": str(origin + 1),
        "validation_end": str(origin + horizon),
        "validation_observations": horizon,
    }


def _v2_recipe(
    horizon=6,
    initial_training=60,
    origin_step=6,
    fold_count=5,
    **overrides,
):
    development_count = initial_training + (fold_count - 1) * origin_step + horizon
    fold_schedule = overrides.pop("fold_schedule", None)
    if fold_schedule is None:
        fold_schedule = [
            _v2_fold(i, initial_training, origin_step, horizon)
            for i in range(1, fold_count + 1)
        ]

    recipe = {
        "schema_version": "candidate-preparation-recipe.v2",
        "producer": "pipeline/prepare_temporal_candidate.py",
        "problem_type": "univariate_forecasting",
        "discovery_evidence_ref": {
            "path": "discovery-evidence.json",
            "schema_version": "dataset-discovery-evidence.v1",
        },
        "semantic_intent_ref": {
            "path": "semantic-intent.json",
            "schema_version": "dataset-semantic-intent.v4",
            "sha256": "a" * 64,
        },
        "semantic_identity_mirror": {
            "time_index_field_name": "period",
            "target_field_name": "value",
            "index_value_kind": "calendar_period",
            "frequency": "monthly",
        },
        "temporal_integrity": {
            "strictly_increasing_index": True,
            "unique_index": True,
            "frequency_contiguous": True,
            "target_missing_values_absent": True,
            "target_values_finite": True,
        },
        "forecast_horizon": horizon,
        "partitions": {
            "development": {
                "start_index_value": "1",
                "end_index_value": str(development_count),
                "observation_count": development_count,
            },
            "sealed_final_holdout": {
                "start_index_value": str(development_count + 1),
                "end_index_value": str(development_count + horizon),
                "observation_count": horizon,
                "prospectively_sealed": True,
                "used_for_backtesting": False,
                "used_for_model_selection": False,
            },
        },
        "backtesting": {
            "mode": "expanding_window",
            "initial_training_observations": initial_training,
            "forecast_horizon": horizon,
            "origin_step_observations": origin_step,
            "fold_count": fold_count,
            "validation_targets_overlap": False,
        },
        "fold_schedule": fold_schedule,
        "leakage_controls": {
            "random_shuffle_performed": False,
            "future_targets_used_for_fold_fit": False,
            "final_holdout_used_for_backtesting": False,
            "final_holdout_used_for_model_selection": False,
            "validation_targets_fed_back_within_fold": False,
            "preprocessing_fit_on_validation_or_future": False,
        },
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
    recipe.update(overrides)
    return recipe


def _deep_merge(base: dict, patch: dict) -> dict:
    out = json.loads(json.dumps(base))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@pytest.fixture
def fixture_recipe_v2(tmp_path):
    p = tmp_path / "recipe-v2.json"
    _write_json(p, _v2_recipe())
    return p


def _require_jsonschema():
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        pytest.skip("jsonschema not installed")


# --- schema_version dispatch ---

def test_v1_fixture_still_dispatches_to_v1_validation(fixture_recipe_produced):
    record = validate_artifacts(recipe_path=fixture_recipe_produced, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["recipe_schema_version"] == "candidate-preparation-recipe.v1"
    assert result["temporal_validation"] is None
    # v1 reduced fields are unchanged (Q section).
    assert result["traceability"]["discovery_evidence_ref_path_present"] is True
    assert result["traceability"]["all_transformations_have_review_status"] is True
    assert result["traceability"]["candidate_status_present"] is True
    assert result["preparation_boundary_confirmations_all_false"] is True
    assert result["candidate_output_produced"] is True


def test_valid_synthetic_v2_recipe_validates(fixture_recipe_v2):
    _require_jsonschema()
    record = validate_artifacts(recipe_path=fixture_recipe_v2, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["recipe_schema_version"] == "candidate-preparation-recipe.v2"
    assert result["schema_validation"]["valid"] is True
    assert result["temporal_validation"]["valid"] is True
    assert result["temporal_validation"]["failed_checks"] == []


def test_unknown_recipe_schema_version_fails_closed(tmp_path):
    bad = _v2_recipe()
    bad["schema_version"] = "candidate-preparation-recipe.v3"
    p = tmp_path / "unknown-version-recipe.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False
    assert result["temporal_validation"] is None
    # never silently treated as v1
    assert result["preparation_boundary_confirmations_all_false"] is False


def test_missing_recipe_schema_version_fails_closed(tmp_path):
    bad = _v2_recipe()
    del bad["schema_version"]
    p = tmp_path / "missing-version-recipe.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False
    assert result["temporal_validation"] is None


def test_mixed_v1_v2_document_is_rejected(tmp_path):
    _require_jsonschema()
    mixed = _v2_recipe()
    mixed["candidate_status"] = {
        "is_final_training_input": False,
        "requires_m23_validation": True,
        "authorized_for": "candidate_only",
    }
    p = tmp_path / "mixed-recipe.json"
    _write_json(p, mixed)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False


# --- schema-level v2 rejections ---

def test_v2_rejects_unknown_extra_properties(tmp_path):
    _require_jsonschema()
    bad = _v2_recipe()
    bad["unexpected_field"] = "not allowed"
    p = tmp_path / "extra-prop.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False


def test_v2_rejects_wrong_problem_type(tmp_path):
    _require_jsonschema()
    bad = _v2_recipe(problem_type="time_series_forecasting")
    p = tmp_path / "wrong-problem-type.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False


def test_v2_rejects_semantic_intent_version_other_than_v4(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"semantic_intent_ref": {"schema_version": "dataset-semantic-intent.v3"}})
    p = tmp_path / "wrong-semantic-version.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False


def test_v2_rejects_horizon_le_zero(tmp_path):
    _require_jsonschema()
    bad = _v2_recipe()
    bad["forecast_horizon"] = 0
    p = tmp_path / "zero-horizon.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False


def test_v2_rejects_non_expanding_backtesting_mode(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"backtesting": {"mode": "kfold"}})
    p = tmp_path / "non-expanding-mode.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False


def test_v2_rejects_zero_initial_training_size(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"backtesting": {"initial_training_observations": 0}})
    p = tmp_path / "zero-initial-training.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False


def test_v2_rejects_negative_origin_step(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"backtesting": {"origin_step_observations": -1}})
    p = tmp_path / "negative-origin-step.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False


def test_v2_rejects_temporal_integrity_false_state(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"temporal_integrity": {"unique_index": False}})
    p = tmp_path / "temporal-integrity-false.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False


def test_v2_rejects_any_leakage_control_true_state(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"leakage_controls": {"random_shuffle_performed": True}})
    p = tmp_path / "leakage-true.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert result["schema_validation"]["valid"] is False


def test_v2_contains_no_raw_target_or_model_payload(tmp_path):
    _require_jsonschema()
    for forbidden_field in ["target_values", "predictions", "model_coefficients", "metrics"]:
        bad = _v2_recipe()
        bad[forbidden_field] = [1, 2, 3]
        p = tmp_path / f"forbidden-{forbidden_field}.json"
        _write_json(p, bad)
        record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
        assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is False, forbidden_field


# --- cross-field arithmetic rejections (validator-level, section P) ---

def test_v2_rejects_holdout_count_not_equal_horizon(fixture_recipe_v2, tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"partitions": {"sealed_final_holdout": {"observation_count": 7}}})
    p = tmp_path / "holdout-mismatch.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "final_holdout_observation_count_equals_forecast_horizon"
        in result["temporal_validation"]["failed_checks"]
    )
    assert result["temporal_validation"]["valid"] is False


def test_v2_rejects_horizon_disagreement_across_sections(tmp_path):
    _require_jsonschema()
    bad = _deep_merge(_v2_recipe(), {"backtesting": {"forecast_horizon": 3}})
    p = tmp_path / "horizon-disagreement.json"
    _write_json(p, bad)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "backtesting_forecast_horizon_equals_governed_horizon"
        in result["temporal_validation"]["failed_checks"]
    )


def test_v2_rejects_fold_count_schedule_length_mismatch(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe(fold_count=6)  # backtesting.fold_count=6 but schedule stays length 5
    recipe["fold_schedule"] = [
        _v2_fold(i, 60, 6, 6) for i in range(1, 6)
    ]
    p = tmp_path / "fold-count-mismatch.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert "fold_count_equals_schedule_length" in result["temporal_validation"]["failed_checks"]


def test_v2_rejects_duplicate_fold_indices(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][-1]["fold_index"] = recipe["fold_schedule"][0]["fold_index"]
    p = tmp_path / "duplicate-fold-index.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert "fold_indices_contiguous_and_unique" in result["temporal_validation"]["failed_checks"]


def test_v2_rejects_gapped_fold_indices(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][-1]["fold_index"] = 99
    p = tmp_path / "gapped-fold-index.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert "fold_indices_contiguous_and_unique" in result["temporal_validation"]["failed_checks"]


def test_v2_rejects_incorrect_first_training_count(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][0]["training_observations"] = 999
    p = tmp_path / "wrong-first-training-count.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "first_fold_training_count_equals_initial_training_count"
        in result["temporal_validation"]["failed_checks"]
    )


def test_v2_rejects_incorrect_expanding_window_growth(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][2]["training_observations"] += 1
    p = tmp_path / "wrong-growth.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "subsequent_training_counts_follow_expanding_window_step"
        in result["temporal_validation"]["failed_checks"]
    )


def test_v2_rejects_validation_window_count_not_equal_horizon(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][1]["validation_observations"] = 99
    p = tmp_path / "wrong-validation-count.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "every_fold_validation_count_equals_forecast_horizon"
        in result["temporal_validation"]["failed_checks"]
    )


def test_v2_rejects_fold_extending_beyond_development(tmp_path):
    _require_jsonschema()
    recipe = _v2_recipe()
    recipe["fold_schedule"][-1]["training_observations"] = recipe["partitions"]["development"]["observation_count"]
    p = tmp_path / "fold-beyond-development.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "every_fold_remains_inside_development_observation_count"
        in result["temporal_validation"]["failed_checks"]
    )


def test_v2_rejects_non_overlap_claim_when_origin_step_less_than_horizon(tmp_path):
    _require_jsonschema()
    # origin_step (3) < horizon (6) while validation_targets_overlap is still
    # (falsely) declared False -- non-overlap claim is not mechanically true.
    recipe = _v2_recipe(origin_step=3)
    p = tmp_path / "origin-step-lt-horizon.json"
    _write_json(p, recipe)
    record = validate_artifacts(recipe_path=p, repo_root=REPO_ROOT)
    result = record["validation_results"]["recipe"]
    assert (
        "origin_step_at_least_horizon_when_overlap_forbidden"
        in result["temporal_validation"]["failed_checks"]
    )


# --- shared writer / write_preparation_recipe compatibility ---

def test_recipe_v2_validates_against_schema_directly(fixture_recipe_v2):
    _require_jsonschema()
    record = validate_artifacts(recipe_path=fixture_recipe_v2, repo_root=REPO_ROOT)
    assert record["validation_results"]["recipe"]["schema_validation"]["valid"] is True
