import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "predict-view-customization.schema.json"
VALID_EXAMPLE_PATH = (
    REPO_ROOT / "contracts" / "examples" / "predict-view-customization.example.json"
)
INVALID_VALIDATION_SEMANTICS_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-predict-view-customization-validation-semantics.example.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_valid_predict_view_customization_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_EXAMPLE_PATH)

    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(example, schema)


def test_predict_view_customization_rejects_validation_semantics():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_VALIDATION_SEMANTICS_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "Additional properties are not allowed" in error.message
        or "validation_rules" in error.message
        for error in errors
    )


def test_hidden_optional_field_passes_schema_validation():
    schema = _load_json(SCHEMA_PATH)
    instance = {
        "schema_version": "1.0.0",
        "view_id": "churn-risk-overview",
        "field_hints": [
            {"field_name": "monthly_charges", "hidden": True},
        ],
        "contract_precedence": {
            "canonical_contracts_are_source_of_truth": True,
            "customization_defines_runtime_validation": False,
            "customization_duplicates_contract": False,
        },
    }
    jsonschema.validate(instance, schema)
