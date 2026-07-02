import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
VALID_EXAMPLE_PATH = (
    REPO_ROOT / "contracts" / "examples" / "dataset-public-profile.example.json"
)
INVALID_TECHNICAL_FIELD_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-technical-field.example.json"
)
INVALID_UNSUPPORTED_THEME_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-unsupported-theme.example.json"
)
INVALID_UNSUPPORTED_ICON_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-unsupported-icon.example.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)


def test_valid_dataset_public_profile_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_EXAMPLE_PATH)

    jsonschema.validate(example, schema)


def test_dataset_public_profile_rejects_technical_field():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_TECHNICAL_FIELD_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "Additional properties are not allowed" in error.message
        or "metrics" in error.message
        for error in errors
    )


def test_dataset_public_profile_rejects_unsupported_theme():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSUPPORTED_THEME_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "is not one of" in error.message or "midnight-purple" in error.message
        for error in errors
    )


def test_dataset_public_profile_rejects_unsupported_icon():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSUPPORTED_ICON_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "is not one of" in error.message or "satellite" in error.message
        for error in errors
    )
