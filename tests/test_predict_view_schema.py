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


# ---------------------------------------------------------------------------
# contracts/dataset-context.schema.json's optional `predict_views` declaration
# (Project Spec S0098)
# ---------------------------------------------------------------------------

DATASET_CONTEXT_SCHEMA_PATH = REPO_ROOT / "contracts" / "dataset-context.schema.json"
DATASET_CONTEXT_EXAMPLE_PATH = REPO_ROOT / "contracts" / "examples" / "dataset-context.example.json"
TELCO_DATASET_CONTEXT_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "dataset-context.json"


def _minimal_dataset_context(**overrides) -> dict:
    context = {
        "schema_version": "1.0.0",
        "dataset_slug": "fixture-dataset",
        "title": "Fixture Dataset",
        "description": "A fixture dataset context.",
        "domain": "general",
    }
    context.update(overrides)
    return context


def test_dataset_context_schema_is_backward_compatible_without_predict_views():
    schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(_minimal_dataset_context(), schema)


def test_dataset_context_schema_accepts_explicit_empty_predict_views():
    schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    jsonschema.validate(_minimal_dataset_context(predict_views=[]), schema)


def test_dataset_context_schema_accepts_populated_predict_views():
    schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    declared_view = _load_json(VALID_EXAMPLE_PATH)
    declared_view.pop("_example_note", None)
    jsonschema.validate(_minimal_dataset_context(predict_views=[declared_view]), schema)


def test_dataset_context_schema_rejects_malformed_predict_view_item():
    schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    malformed = _minimal_dataset_context(predict_views=[{"view_id": "missing-required-fields"}])
    errors = list(validator.iter_errors(malformed))
    assert errors


def test_dataset_context_schema_rejects_predict_view_duplicating_runtime_features():
    schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    declared_view = _load_json(VALID_EXAMPLE_PATH)
    declared_view.pop("_example_note", None)
    declared_view["features"] = [{"name": "tenure"}]
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(_minimal_dataset_context(predict_views=[declared_view])))
    assert errors


def test_dataset_context_example_and_telco_context_declare_valid_churn_risk_overview_view():
    context_schema = _load_json(DATASET_CONTEXT_SCHEMA_PATH)
    predict_view_schema = _load_json(SCHEMA_PATH)

    for context_path in (DATASET_CONTEXT_EXAMPLE_PATH, TELCO_DATASET_CONTEXT_PATH):
        context = _load_json(context_path)
        jsonschema.validate(context, context_schema)

        declared_views = context.get("predict_views")
        assert declared_views, f"{context_path} must declare at least one predict view"
        assert any(view.get("view_id") == "churn-risk-overview" for view in declared_views)
        for view in declared_views:
            jsonschema.validate(view, predict_view_schema)
            # Declaration is presentation/intent metadata only -- it must not
            # duplicate runtime feature/validation semantics.
            assert "features" not in view
            assert "validation_rules" not in view
