import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "admin-run-summary.schema.json"
VALID_AVAILABLE_EXAMPLE_PATH = (
    REPO_ROOT / "contracts" / "examples" / "admin-run-summary.example.json"
)
VALID_UNAVAILABLE_EXAMPLE_PATH = (
    REPO_ROOT / "contracts" / "examples" / "admin-run-summary-unavailable.example.json"
)
INVALID_UNSAFE_FIELD_EXAMPLE_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-admin-run-summary-unsafe-field.example.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_admin_run_summary_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)

    jsonschema.Draft7Validator.check_schema(schema)


def test_valid_available_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_AVAILABLE_EXAMPLE_PATH)

    jsonschema.validate(example, schema)


def test_valid_unavailable_example_matches_schema_and_nulls_projection_fields():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_UNAVAILABLE_EXAMPLE_PATH)

    jsonschema.validate(example, schema)

    assert example["status"] == "unavailable"
    assert example["dataset_candidate"] is None
    assert example["created_at"] is None
    assert example["trace_reference"] is None
    assert example["validation_summary"] is None
    assert example["unavailable_reason"]


def test_admin_run_summary_rejects_unsafe_additional_field():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSAFE_FIELD_EXAMPLE_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "raw_absolute_path" in error.message
        or "Additional properties are not allowed" in error.message
        for error in errors
    )


def test_unavailable_status_requires_unavailable_reason():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_UNAVAILABLE_EXAMPLE_PATH)
    example = dict(example)
    del example["unavailable_reason"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any("unavailable_reason" in error.message for error in errors)


def test_available_status_forbids_populated_dataset_candidate_when_marked_unavailable():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_UNAVAILABLE_EXAMPLE_PATH)
    example = dict(example)
    example["dataset_candidate"] = "telco-customer-churn"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
