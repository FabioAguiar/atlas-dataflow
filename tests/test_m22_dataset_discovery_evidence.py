"""
Tests for the M22-02 dataset discovery evidence generator.

Validates evidence completeness, field presence, candidate non-authoritativeness,
determinism, and boundary enforcement. Uses synthetic fixture data only;
does not depend on the data/ directory or a real dataset path.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.discovery_evidence import generate_discovery_evidence


REPO_ROOT = Path(__file__).parent.parent

FIXTURE_ROWS = [
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "5.1", "target": "0"},
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "4.9", "target": "0"},
    {"species": "versicolor", "petal_length": "4.7", "petal_width": "1.4", "sepal_length": "7.0", "target": "1"},
    {"species": "versicolor", "petal_length": "4.5", "petal_width": "1.5", "sepal_length": "6.4", "target": "1"},
    {"species": "virginica",  "petal_length": "6.0", "petal_width": "2.5", "sepal_length": "6.3", "target": "2"},
    {"species": "setosa",     "petal_length": "",    "petal_width": "0.3", "sepal_length": "4.7", "target": "0"},
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "5.1", "target": "0"},
]
FIXTURE_COLUMNS = ["species", "petal_length", "petal_width", "sepal_length", "target"]


def _write_fixture_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIXTURE_COLUMNS)
        writer.writeheader()
        writer.writerows(FIXTURE_ROWS)


@pytest.fixture
def fixture_csv(tmp_path):
    csv_path = tmp_path / "fixture_dataset.csv"
    _write_fixture_csv(csv_path)
    return csv_path


# --- input validation ---

def test_rejects_none_input_path():
    with pytest.raises((ValueError, TypeError)):
        generate_discovery_evidence(None)


def test_rejects_empty_string_input_path():
    with pytest.raises((ValueError, TypeError)):
        generate_discovery_evidence("")


def test_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        generate_discovery_evidence("/nonexistent/does-not-exist/dataset.csv")


# --- required top-level fields ---

def test_all_required_top_level_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    required = [
        "schema_version", "producer", "dataset_metadata", "field_observations",
        "duplicated_rows_count", "candidate_categorical_fields", "candidate_target_columns",
        "generation_settings", "generated_at", "discovery_boundary_confirmations",
        "evidence_policy",
    ]
    for field in required:
        assert field in evidence, f"Required field missing: {field}"


def test_schema_version_is_correct(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["schema_version"] == "dataset-discovery-evidence.v1"


def test_dataset_metadata_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    meta = evidence["dataset_metadata"]
    for key in ["name", "row_count", "column_count", "source_path"]:
        assert key in meta, f"dataset_metadata missing: {key}"


def test_field_observations_required_fields(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for obs in evidence["field_observations"]:
        for key in ["name", "inferred_type", "null_count", "null_rate", "cardinality", "sample_min", "sample_max"]:
            assert key in obs, f"field_observation missing key: {key}"


def test_generation_settings_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    settings = evidence["generation_settings"]
    assert "seed" in settings
    assert "generator_version" in settings


# --- observation correctness ---

def test_row_count_matches_fixture(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["dataset_metadata"]["row_count"] == len(FIXTURE_ROWS)


def test_column_count_matches_fixture(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["dataset_metadata"]["column_count"] == len(FIXTURE_COLUMNS)


def test_null_count_for_petal_length(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "petal_length")
    assert obs["null_count"] == 1


def test_duplicated_rows_count(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    # row 0 and row 6 are identical
    assert evidence["duplicated_rows_count"] == 1


def test_species_is_categorical_candidate(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    # species has 3 unique string values — below the categorical threshold
    assert "species" in evidence["candidate_categorical_fields"]


def test_inferred_type_integer_for_target(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "target")
    assert obs["inferred_type"] == "integer"


def test_inferred_type_float_for_sepal_length(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "sepal_length")
    assert obs["inferred_type"] == "float"


def test_inferred_type_string_for_species(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "species")
    assert obs["inferred_type"] == "string"


def test_null_rate_is_fraction(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "petal_length")
    expected = round(1 / len(FIXTURE_ROWS), 6)
    assert obs["null_rate"] == pytest.approx(expected)


def test_source_path_is_not_absolute(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    source_path = evidence["dataset_metadata"]["source_path"]
    assert not source_path.startswith("/"), "source_path must not be an absolute path"


# --- candidate target columns are non-authoritative ---

def test_all_candidate_target_columns_are_non_authoritative(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for candidate in evidence["candidate_target_columns"]:
        assert candidate["is_authoritative"] is False, (
            f"Candidate '{candidate['name']}' must have is_authoritative: false"
        )


def test_candidate_target_columns_have_name_field(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for candidate in evidence["candidate_target_columns"]:
        assert "name" in candidate


# --- determinism ---

def test_deterministic_output_same_seed(fixture_csv):
    fixed_ts = "2026-06-23T17:00:00+00:00"
    ev1 = generate_discovery_evidence(fixture_csv, seed=42, generated_at=fixed_ts)
    ev2 = generate_discovery_evidence(fixture_csv, seed=42, generated_at=fixed_ts)
    assert json.dumps(ev1, sort_keys=True) == json.dumps(ev2, sort_keys=True)


def test_field_observations_order_is_stable(fixture_csv):
    ev1 = generate_discovery_evidence(fixture_csv, seed=0)
    ev2 = generate_discovery_evidence(fixture_csv, seed=0)
    names1 = [o["name"] for o in ev1["field_observations"]]
    names2 = [o["name"] for o in ev2["field_observations"]]
    assert names1 == names2


# --- boundary confirmations ---

def test_discovery_boundary_confirmations(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    bc = evidence["discovery_boundary_confirmations"]
    assert bc["contract_promotion_occurred"] is False
    assert bc["model_training_occurred"] is False
    assert bc["release_publication_occurred"] is False


def test_evidence_policy_all_flags_set(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    policy = evidence["evidence_policy"]
    for key in [
        "raw_logs_prohibited", "raw_runtime_prohibited", "raw_api_payloads_prohibited",
        "secrets_prohibited", "private_source_paths_prohibited", "reduced_and_sanitized",
    ]:
        assert policy[key] is True, f"evidence_policy.{key} must be True"


# --- schema validation ---

def test_evidence_validates_against_schema(fixture_csv):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = REPO_ROOT / "pipeline" / "dataset-discovery-evidence.schema.json"
    assert schema_path.exists(), f"Schema not found: {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    evidence = generate_discovery_evidence(
        fixture_csv,
        seed=0,
        generated_at="2026-06-23T17:00:00+00:00",
    )
    jsonschema.validate(evidence, schema)
