"""
Tests for the M22-04 dataset preparation pipeline.

Validates recipe completeness, transformation traceability, candidate conditionality,
no-safe-candidate handling, inferred-rule non-application, boundary confirmations,
and schema conformance. Uses synthetic fixture data only; does not depend on the
data/ directory or a real dataset path.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.prepare_candidate import prepare_candidate, write_candidate_output, write_preparation_recipe


REPO_ROOT = Path(__file__).parent.parent

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


def _write_fixture_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIXTURE_COLUMNS)
        writer.writeheader()
        writer.writerows(FIXTURE_ROWS)


def _write_fixture_discovery_evidence(path: Path) -> None:
    path.write_text(json.dumps(FIXTURE_DISCOVERY_EVIDENCE, indent=2), encoding="utf-8")


def _write_rules(path: Path, rules: dict) -> None:
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")


@pytest.fixture
def fixture_csv(tmp_path):
    p = tmp_path / "fixture.csv"
    _write_fixture_csv(p)
    return p


@pytest.fixture
def fixture_evidence(tmp_path):
    p = tmp_path / "discovery-evidence.json"
    _write_fixture_discovery_evidence(p)
    return p


@pytest.fixture
def rules_file(tmp_path):
    def _make(rules: dict):
        p = tmp_path / "rules.json"
        _write_rules(p, rules)
        return p
    return _make


# --- input validation ---

def test_rejects_missing_discovery_evidence(tmp_path, fixture_csv, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    with pytest.raises(FileNotFoundError):
        prepare_candidate(
            tmp_path / "nonexistent-evidence.json",
            fixture_csv,
            rules,
        )


def test_rejects_missing_dataset(tmp_path, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    with pytest.raises(FileNotFoundError):
        prepare_candidate(
            fixture_evidence,
            tmp_path / "nonexistent.csv",
            rules,
        )


def test_rejects_missing_rules_file(tmp_path, fixture_csv, fixture_evidence):
    with pytest.raises(FileNotFoundError):
        prepare_candidate(
            fixture_evidence,
            fixture_csv,
            tmp_path / "nonexistent-rules.json",
        )


# --- recipe completeness ---

def test_recipe_has_all_required_top_level_fields(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    required = [
        "schema_version", "producer", "dataset_identity", "discovery_evidence_ref",
        "transformations", "candidate_output", "candidate_status", "generation_settings",
        "generated_at", "preparation_boundary_confirmations", "evidence_policy",
    ]
    for field in required:
        assert field in recipe, f"Required recipe field missing: {field}"


def test_recipe_schema_version_is_correct(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["schema_version"] == "candidate-preparation-recipe.v1"


def test_recipe_records_dataset_identity(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    di = recipe["dataset_identity"]
    assert "name" in di
    assert di["row_count_before"] == len(FIXTURE_ROWS)
    assert di["column_count_before"] == len(FIXTURE_COLUMNS)


def test_recipe_records_discovery_evidence_ref(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    ref = recipe["discovery_evidence_ref"]
    assert "path" in ref
    assert ref["schema_version"] == "dataset-discovery-evidence.v1"


def test_recipe_records_all_declared_transformations(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "column_selection": ["age", "balance", "label"],
        "missing_value_rules": [
            {"column": "balance", "action": "drop_row", "reason": "balance required"}
        ],
    })
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    types = [t["transformation_type"] for t in recipe["transformations"]]
    assert "column_selection" in types
    assert "missing_value_handling" in types


def test_recipe_each_transformation_has_required_fields(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "column_selection": ["age", "label"],
        "row_filters": [{"column": "age", "operator": "gte", "value": 18, "reason": "adults only"}],
    })
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    for t in recipe["transformations"]:
        for key in ["transformation_type", "description", "source_columns", "target_columns", "reason", "review_status"]:
            assert key in t, f"Transformation missing required field: {key}"


def test_recipe_generation_settings_fields_present(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    gs = recipe["generation_settings"]
    assert "generator_version" in gs
    assert "preparation_rules_source" in gs


# --- transformation traceability ---

def test_source_path_in_dataset_identity_is_not_absolute(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert not recipe["dataset_identity"]["name"].startswith("/")


def test_discovery_evidence_ref_path_is_not_absolute(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert not recipe["discovery_evidence_ref"]["path"].startswith("/")


def test_rules_source_in_generation_settings_is_not_absolute(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert not recipe["generation_settings"]["preparation_rules_source"].startswith("/")


# --- candidate conditionality ---

def test_candidate_produced_when_rules_declared(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    recipe, columns, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_output"]["produced"] is True
    assert columns is not None
    assert rows is not None


def test_column_selection_keeps_only_selected_columns(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    _, columns, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert set(columns) == {"age", "label"}
    for row in rows:
        assert set(row.keys()) == {"age", "label"}


def test_row_filter_removes_rows_below_threshold(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "row_filters": [
            {"column": "age", "operator": "gte", "value": 18, "reason": "adult rows only"}
        ]
    })
    _, _, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    ages = [int(r["age"]) for r in rows]
    assert all(a >= 18 for a in ages), f"Expected all ages >= 18, got: {ages}"
    assert len(rows) < len(FIXTURE_ROWS)


def test_missing_value_drop_row_removes_rows_with_empty_column(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "missing_value_rules": [
            {"column": "balance", "action": "drop_row", "reason": "balance required"}
        ]
    })
    _, _, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert all(r["balance"] != "" for r in rows)
    assert len(rows) == len(FIXTURE_ROWS) - 1


def test_missing_value_fill_replaces_empty_with_fill_value(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "missing_value_rules": [
            {"column": "balance", "action": "fill_value", "fill_value": "0", "reason": "default balance"}
        ]
    })
    _, _, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert all(r["balance"] != "" for r in rows)
    assert len(rows) == len(FIXTURE_ROWS)


def test_type_normalization_converts_integer_column(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "type_normalizations": [
            {"column": "age", "target_type": "integer", "reason": "age is integer"}
        ]
    })
    _, _, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    for row in rows:
        assert row["age"].lstrip("-").isdigit(), f"Expected integer string, got: {row['age']}"


def test_categorical_treatment_recorded_in_recipe(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "categorical_columns": [
            {"column": "job", "reason": "job is nominal category"}
        ]
    })
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    types = [t["transformation_type"] for t in recipe["transformations"]]
    assert "categorical_treatment" in types


# --- no-safe-candidate case ---

def test_no_candidate_produced_when_no_rules(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({})
    recipe, columns, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_output"]["produced"] is False
    assert columns is None
    assert rows is None


def test_no_candidate_reason_recorded_when_no_rules(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_output"]["reason_not_produced"] is not None
    assert len(recipe["candidate_output"]["reason_not_produced"]) > 0


def test_row_count_after_is_none_when_no_candidate(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_output"]["row_count_after"] is None
    assert recipe["candidate_output"]["column_count_after"] is None


# --- inferred rules are not applied ---

def test_inferred_pending_review_rules_not_applied(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "row_filters": [
            {
                "column": "age",
                "operator": "gte",
                "value": 18,
                "review_status": "inferred_pending_review",
                "reason": "inferred from discovery evidence",
            }
        ]
    })
    recipe, columns, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_output"]["produced"] is False, (
        "No candidate should be produced when the only rules are inferred_pending_review"
    )


def test_inferred_pending_review_rules_recorded_in_recipe(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({
        "row_filters": [
            {
                "column": "age",
                "operator": "gte",
                "value": 18,
                "review_status": "inferred_pending_review",
                "reason": "inferred from discovery evidence",
            }
        ]
    })
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    pending = [t for t in recipe["transformations"] if t["review_status"] == "inferred_pending_review"]
    assert len(pending) == 1, "Inferred pending-review rule must be recorded in the recipe"


# --- candidate status ---

def test_candidate_status_is_never_final_training_input(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_status"]["is_final_training_input"] is False


def test_candidate_status_requires_m23_validation(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_status"]["requires_m23_validation"] is True


def test_candidate_status_authorized_for_is_candidate_only(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    assert recipe["candidate_status"]["authorized_for"] == "candidate_only"


# --- boundary confirmations ---

def test_preparation_boundary_confirmations_all_false(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    bc = recipe["preparation_boundary_confirmations"]
    for key in [
        "complex_feature_engineering_performed",
        "model_training_performed",
        "release_publication_performed",
        "hidden_notebook_transformations",
        "inferred_rules_applied_without_approval",
    ]:
        assert bc[key] is False, f"preparation_boundary_confirmations.{key} must be False"


def test_evidence_policy_all_flags_set(fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    policy = recipe["evidence_policy"]
    for key in [
        "raw_logs_prohibited",
        "raw_runtime_prohibited",
        "raw_api_payloads_prohibited",
        "secrets_prohibited",
        "private_source_paths_prohibited",
        "reduced_and_sanitized",
    ]:
        assert policy[key] is True, f"evidence_policy.{key} must be True"


# --- determinism ---

def test_deterministic_output_same_rules(fixture_csv, fixture_evidence, rules_file):
    fixed_ts = "2026-06-23T23:00:00+00:00"
    rules = rules_file({
        "column_selection": ["age", "label"],
        "row_filters": [{"column": "age", "operator": "gte", "value": 18, "reason": "adult"}],
    })
    r1, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules, generated_at=fixed_ts)
    r2, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules, generated_at=fixed_ts)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# --- write helpers ---

def test_write_candidate_output_produces_valid_csv(tmp_path, fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    _, columns, rows = prepare_candidate(fixture_evidence, fixture_csv, rules)
    out = tmp_path / "candidate.csv"
    write_candidate_output(out, columns, rows)
    assert out.exists()
    with out.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        written_rows = list(reader)
    assert set(reader.fieldnames or []) == {"age", "label"}
    assert len(written_rows) == len(FIXTURE_ROWS)


def test_write_preparation_recipe_produces_valid_json(tmp_path, fixture_csv, fixture_evidence, rules_file):
    rules = rules_file({"column_selection": ["age", "label"]})
    recipe, _, _ = prepare_candidate(fixture_evidence, fixture_csv, rules)
    out = tmp_path / "recipe.json"
    write_preparation_recipe(out, recipe, REPO_ROOT)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "candidate-preparation-recipe.v1"


# --- schema validation ---

def test_recipe_validates_against_schema(fixture_csv, fixture_evidence, rules_file):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = REPO_ROOT / "pipeline" / "candidate-preparation-recipe.schema.json"
    assert schema_path.exists(), f"Recipe schema not found: {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    rules = rules_file({
        "column_selection": ["age", "label"],
        "row_filters": [
            {"column": "age", "operator": "gte", "value": 18, "reason": "adult rows only"}
        ],
        "missing_value_rules": [
            {"column": "balance", "action": "drop_row", "reason": "balance required"}
        ],
        "categorical_columns": [
            {"column": "job", "reason": "nominal category"}
        ],
    })
    recipe, _, _ = prepare_candidate(
        fixture_evidence,
        fixture_csv,
        rules,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    jsonschema.validate(recipe, schema)


def test_no_candidate_recipe_validates_against_schema(fixture_csv, fixture_evidence, rules_file):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = REPO_ROOT / "pipeline" / "candidate-preparation-recipe.schema.json"
    assert schema_path.exists(), f"Recipe schema not found: {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    rules = rules_file({})
    recipe, _, _ = prepare_candidate(
        fixture_evidence,
        fixture_csv,
        rules,
        generated_at="2026-06-23T23:00:00+00:00",
    )
    jsonschema.validate(recipe, schema)
