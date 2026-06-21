import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "predict-view.schema.json"
VALID_EXAMPLE_PATH = REPO_ROOT / "contracts" / "examples" / "predict-view.example.json"
INVALID_CONTRACT_DUPLICATION_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-predict-view-contract-duplication.example.json"
)
INVALID_MISSING_BINDING_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-predict-view-missing-binding.example.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_valid_predict_view_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_EXAMPLE_PATH)

    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(example, schema)


def test_predict_view_rejects_contract_duplication():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_CONTRACT_DUPLICATION_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "features" in error.schema.get("required", [])
        or "validation_rules" in error.schema.get("required", [])
        or "Additional properties are not allowed" in error.message
        for error in errors
    )


def test_predict_view_requires_binding_reference():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_MISSING_BINDING_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any("binding" in error.message for error in errors)
