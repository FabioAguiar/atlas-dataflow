import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "admin-run-summary.schema.json"
# Project Spec S0045 repurposed this file to demonstrate the 'promoted'
# state (it was previously a plain 'available' example); basic 'available'
# schema coverage now lives in _INLINE_AVAILABLE_INSTANCE below instead.
VALID_PROMOTED_EXAMPLE_PATH = (
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

_INLINE_AVAILABLE_INSTANCE = {
    "schema_version": "admin-run-summary.v1",
    "run_id": "run-20260701-010",
    "status": "available",
    "dataset_candidate": "example-dataset",
    "created_at": "2026-07-01T00:00:00Z",
    "trace_reference": "releases/candidates/example-dataset/release-20260701-001",
    "validation_summary": {"outcome": "accepted"},
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_admin_run_summary_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)

    jsonschema.Draft7Validator.check_schema(schema)


def test_inline_available_instance_without_promotion_summary_matches_schema():
    schema = _load_json(SCHEMA_PATH)

    jsonschema.validate(_INLINE_AVAILABLE_INSTANCE, schema)


def test_valid_promoted_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_PROMOTED_EXAMPLE_PATH)

    jsonschema.validate(example, schema)


def test_promoted_example_reflects_promoted_status_and_sanitized_promotion_fields():
    example = _load_json(VALID_PROMOTED_EXAMPLE_PATH)

    assert example["status"] == "promoted"
    promotion_summary = example["promotion_summary"]
    assert promotion_summary["promotion_outcome"] == "promoted"
    assert promotion_summary["release_id"]
    assert promotion_summary["dataset_slug"]
    assert promotion_summary["public_dataset_slug"]
    assert promotion_summary["registry_action"] == "reused"
    assert promotion_summary["registry_bound"] is True
    assert promotion_summary["can_promote"] is False
    assert promotion_summary["can_remove"] is True
    assert promotion_summary["reason"]


def test_promoted_status_requires_promotion_summary():
    schema = _load_json(SCHEMA_PATH)
    example = dict(_load_json(VALID_PROMOTED_EXAMPLE_PATH))
    del example["promotion_summary"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any("promotion_summary" in error.message for error in errors)


def test_promotion_summary_without_public_dataset_slug_or_registry_action_is_valid():
    # Project Spec S0048: omitting public_dataset_slug/registry_action is only
    # valid alongside registry_bound: false/can_promote: true -- a
    # 'promotion_result_orphaned' (registry-missing, re-promotable) instance.
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    del example["promotion_summary"]["public_dataset_slug"]
    del example["promotion_summary"]["registry_action"]
    example["promotion_summary"]["registry_bound"] = False
    example["promotion_summary"]["can_promote"] = True

    jsonschema.validate(example, schema)


def test_promotion_summary_registry_bound_requires_public_dataset_slug_and_registry_action():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    del example["promotion_summary"]["public_dataset_slug"]
    del example["promotion_summary"]["registry_action"]

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors


def test_promotion_summary_rejects_can_promote_true_when_registry_bound():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    example["promotion_summary"]["can_promote"] = True

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors


def test_promotion_summary_rejects_can_promote_false_when_registry_missing():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    del example["promotion_summary"]["public_dataset_slug"]
    del example["promotion_summary"]["registry_action"]
    example["promotion_summary"]["registry_bound"] = False
    example["promotion_summary"]["can_promote"] = False

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors


def test_promotion_summary_rejects_can_remove_false():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    example["promotion_summary"]["can_remove"] = False

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors


def test_registry_missing_repromotable_promotion_summary_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    del example["promotion_summary"]["public_dataset_slug"]
    del example["promotion_summary"]["registry_action"]
    example["promotion_summary"]["registry_bound"] = False
    example["promotion_summary"]["can_promote"] = True
    example["promotion_summary"]["reason"] = (
        "The Dataset Detail associated with this run's promoted release is "
        "no longer in the registry, so this run can be promoted again."
    )

    jsonschema.validate(example, schema)


def test_promotion_summary_rejects_unsafe_additional_field():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    example["promotion_summary"]["raw_release_directory"] = (
        "/workspace/projects/atlas-dataflow/releases/release-20260620-001"
    )

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "raw_release_directory" in error.message
        or "Additional properties are not allowed" in error.message
        for error in errors
    )


def test_promotion_summary_rejects_unrecognized_registry_action():
    schema = _load_json(SCHEMA_PATH)
    example = json.loads(json.dumps(_load_json(VALID_PROMOTED_EXAMPLE_PATH)))
    example["promotion_summary"]["registry_action"] = "not_a_real_action"

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors


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
