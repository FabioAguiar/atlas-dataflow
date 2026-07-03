import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "admin-settings.schema.json"
VALID_EXAMPLE_PATH = REPO_ROOT / "contracts" / "examples" / "admin-settings.example.json"
INVALID_UNSUPPORTED_FIELD_PATH = (
    REPO_ROOT / "contracts" / "examples" / "invalid-admin-settings-unsupported-field.example.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_admin_settings_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)


def test_valid_admin_settings_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_EXAMPLE_PATH)

    jsonschema.validate(example, schema)


def test_admin_settings_rejects_unsupported_account_field():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSUPPORTED_FIELD_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "Additional properties are not allowed" in error.message
        or "email" in error.message
        for error in errors
    )


def test_admin_settings_requires_display_name_only():
    schema = _load_json(SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors({}))

    assert errors
    assert any("display_name" in error.message for error in errors)
