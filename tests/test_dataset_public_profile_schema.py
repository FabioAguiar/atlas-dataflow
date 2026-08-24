import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
SNAPSHOT_SCHEMA_PATH = (
    REPO_ROOT / "contracts" / "dataset-public-profile-snapshot.schema.json"
)
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

THEME_PRESET_IDS = [
    "atlas-green", "ocean-blue", "violet-insight", "amber-signal", "slate-ops",
    "rose-review", "teal-flow", "indigo-lab", "graphite", "citrus", "coral",
    "skyline", "plum", "neutral-light", "midnight-cyan", "emerald-noir",
    "solar-flare", "electric-magenta", "neon-lime", "aurora", "deep-sea",
    "desert-sand", "forest-moss", "ice-blue", "crimson-night", "copper-circuit",
    "lavender-mist", "monochrome-dark", "retro-terminal", "cyber-neon",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)

    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(snapshot_schema)


def test_draft_and_snapshot_theme_catalogs_are_exact_and_accept_every_preset():
    draft_schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    draft_enum = draft_schema["definitions"]["theme"]["properties"]["preset"]["enum"]
    snapshot_enum = snapshot_schema["definitions"]["theme"]["properties"]["preset"]["enum"]

    assert draft_enum == THEME_PRESET_IDS
    assert snapshot_enum == THEME_PRESET_IDS

    for preset_id in THEME_PRESET_IDS:
        jsonschema.validate(
            {"schema_version": "0.1.0", "dataset_slug": "example-dataset", "theme": {"preset": preset_id}},
            draft_schema,
        )
        jsonschema.validate(
            {
                "schema_version": "0.1.0",
                "dataset_slug": "example-dataset",
                "published_at": "2026-07-13T12:00:00Z",
                "active_release_at_publish_time": "release-20260713-001",
                "profile": {"theme": {"preset": preset_id}},
            },
            snapshot_schema,
        )


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
        "is not one of" in error.message or "custom-rainbow" in error.message
        for error in errors
    )

    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    invalid_snapshot = {
        "schema_version": "0.1.0",
        "dataset_slug": "telco-customer-churn",
        "published_at": "2026-07-13T12:00:00Z",
        "active_release_at_publish_time": "release-20260713-001",
        "profile": {"theme": example["theme"]},
    }
    assert list(jsonschema.Draft7Validator(snapshot_schema).iter_errors(invalid_snapshot))


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


# ---------------------------------------------------------------------------
# Project Spec S0196: optional Markdown documentation on the draft profile
# and on the published snapshot profile, sharing the exact same bounded
# {format, content} shape.
# ---------------------------------------------------------------------------


def _base_profile(**overrides):
    profile = {"schema_version": "0.1.0", "dataset_slug": "example-dataset"}
    profile.update(overrides)
    return profile


def _base_snapshot(profile_overrides=None):
    return {
        "schema_version": "0.1.0",
        "dataset_slug": "telco-customer-churn",
        "published_at": "2026-07-13T12:00:00Z",
        "active_release_at_publish_time": "release-20260713-001",
        "profile": profile_overrides or {},
    }


def test_valid_markdown_documentation_is_accepted_in_draft_and_snapshot():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": "# Heading\n\nSome **body** text."}

    jsonschema.validate(_base_profile(documentation=documentation), schema)
    jsonschema.validate(_base_snapshot({"documentation": documentation}), snapshot_schema)


def test_blank_documentation_content_is_accepted_as_unauthored_state():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": ""}

    jsonschema.validate(_base_profile(documentation=documentation), schema)
    jsonschema.validate(_base_snapshot({"documentation": documentation}), snapshot_schema)


def test_profiles_and_snapshots_without_documentation_remain_valid():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)

    jsonschema.validate(_base_profile(), schema)
    jsonschema.validate(_base_snapshot(), snapshot_schema)


def test_documentation_rejects_unsupported_format():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "html", "content": "<p>not markdown</p>"}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_rejects_non_string_content():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": 12345}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_rejects_unknown_properties():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": "Body", "rendered_html": "<p>Body</p>"}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_enforces_max_length():
    schema = _load_json(SCHEMA_PATH)
    max_length = schema["definitions"]["documentation"]["properties"]["content"]["maxLength"]
    documentation = {"format": "markdown", "content": "a" * (max_length + 1)}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))


def test_documentation_does_not_bypass_technical_field_rejection():
    schema = _load_json(SCHEMA_PATH)
    profile = _base_profile(documentation={"format": "markdown", "content": "Body"})
    profile["metrics"] = {"accuracy": 0.9}

    errors = list(jsonschema.Draft7Validator(schema).iter_errors(profile))
    assert errors


# ---------------------------------------------------------------------------
# Project Spec S0249: univariate-forecasting-result-presentation.v1 Result
# Card union branch on both the draft profile and published snapshot schemas.
# ---------------------------------------------------------------------------


def _forecasting_result_card(**overrides) -> dict:
    base = {
        "schema_version": "univariate-forecasting-result-presentation.v1",
        "forecast_series_label": "Forecast",
        "future_time_index_label": "Period",
        "forecast_value_label": "Forecast",
        "model_section_label": "Model",
        "decimal_places": 2,
    }
    base.update(overrides)
    return base


def test_valid_forecasting_result_card_accepted_in_draft_and_snapshot():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    result_card = _forecasting_result_card(value_unit_label="units")

    jsonschema.validate(_base_profile(result_card=result_card), schema)
    jsonschema.validate(_base_snapshot({"result_card": result_card}), snapshot_schema)


def test_forecasting_result_card_value_unit_label_is_optional():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    result_card = _forecasting_result_card()

    jsonschema.validate(_base_profile(result_card=result_card), schema)
    jsonschema.validate(_base_snapshot({"result_card": result_card}), snapshot_schema)


@pytest.mark.parametrize("decimal_places", [0, 6])
def test_forecasting_result_card_accepts_decimal_places_bounds(decimal_places):
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card(decimal_places=decimal_places)

    jsonschema.validate(_base_profile(result_card=result_card), schema)


@pytest.mark.parametrize("decimal_places", [-1, 7])
def test_forecasting_result_card_rejects_decimal_places_outside_bounds(decimal_places):
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card(decimal_places=decimal_places)

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))


@pytest.mark.parametrize(
    "missing_field",
    ["forecast_series_label", "future_time_index_label", "forecast_value_label", "model_section_label", "decimal_places"],
)
def test_forecasting_result_card_rejects_missing_required_copy_fields(missing_field):
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card()
    del result_card[missing_field]

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))


def test_forecasting_result_card_rejects_unknown_fields():
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card(unexpected_field="not allowed")

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))


def test_forecasting_result_card_rejects_forecast_technical_fields():
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card(
        forecast_points=[{"horizon_step": 1, "future_time_index": "2026-08", "forecast": 42.0}]
    )

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))


def test_forecasting_result_card_rejects_forecast_origin_frequency_and_horizon():
    schema = _load_json(SCHEMA_PATH)
    for technical_field, value in (
        ("forecast_origin", "2026-07"),
        ("frequency", "monthly"),
        ("forecast_horizon", 12),
    ):
        result_card = _forecasting_result_card(**{technical_field: value})
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))
        assert errors, f"expected {technical_field} to be rejected"


def test_forecasting_result_card_rejects_model_descriptor():
    schema = _load_json(SCHEMA_PATH)
    result_card = _forecasting_result_card(
        model_descriptor={"model_family": "deterministic_seasonal_trend_ols", "display_name": "Seasonal Trend"}
    )

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))


def test_forecasting_result_card_rejects_interval_and_history_fields():
    schema = _load_json(SCHEMA_PATH)
    for technical_field, value in (
        ("intervals", {"lower": 1.0, "upper": 2.0}),
        ("threshold", 0.5),
        ("classes", [{"class_id": "forbidden"}]),
        ("history_rows", []),
        ("metrics", {"mae": 1.0}),
    ):
        result_card = _forecasting_result_card(**{technical_field: value})
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(result_card=result_card)))
        assert errors, f"expected {technical_field} to be rejected"


# ---------------------------------------------------------------------------
# Project Spec S0256: forecasting_performance Performance Focus enum
# reconciliation between the draft profile and published snapshot schemas.
# ---------------------------------------------------------------------------

PERFORMANCE_FOCUS_IDS = [
    "overall_discrimination",
    "positive_class_detection",
    "balanced_classification",
    "probability_quality",
    "operational_decision",
    "regression_performance",
    "forecasting_performance",
]


def _forecasting_performance_focus() -> dict:
    return {
        "focus_id": "forecasting_performance",
        "highlighted_score_id": "mae",
        "visible_scores": [
            {"score_id": "mae", "display_label": "MAE", "value": "1.0", "value_source": "manual", "order": 0},
        ],
    }


def test_draft_and_snapshot_performance_focus_enums_are_exactly_equal_and_include_forecasting():
    draft_schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    draft_enum = draft_schema["properties"]["performance_focus"]["properties"]["focus_id"]["enum"]
    snapshot_enum = (
        snapshot_schema["definitions"]["performance_focus"]["properties"]["focus_id"]["enum"]
    )

    assert draft_enum == snapshot_enum
    assert draft_enum.count("forecasting_performance") == 1
    assert snapshot_enum.count("forecasting_performance") == 1
    for historical_focus_id in [
        "overall_discrimination",
        "positive_class_detection",
        "balanced_classification",
        "probability_quality",
        "operational_decision",
        "regression_performance",
    ]:
        assert historical_focus_id in draft_enum
        assert historical_focus_id in snapshot_enum


def test_draft_and_snapshot_accept_forecasting_performance_focus():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    performance_focus = _forecasting_performance_focus()

    jsonschema.validate(_base_profile(performance_focus=performance_focus), schema)
    jsonschema.validate(_base_snapshot({"performance_focus": performance_focus}), snapshot_schema)


def test_draft_and_snapshot_reject_unknown_performance_focus_id():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    performance_focus = _forecasting_performance_focus()
    performance_focus["focus_id"] = "forecast_accuracy"

    assert list(
        jsonschema.Draft7Validator(schema).iter_errors(
            _base_profile(performance_focus=performance_focus)
        )
    )
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"performance_focus": performance_focus})
        )
    )


def test_forecasting_result_card_does_not_disturb_historical_result_card_schema_tests():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    binary_card = {
        "schema_version": "binary-result-presentation.v1",
        "positive_class_probability_label": "Positive class probability",
        "predicted_outcome_label": "Predicted outcome",
        "positive_outcome_copy": "Positive outcome",
        "negative_outcome_copy": "Negative outcome",
        "model_section_label": "Model",
        "interpretation": {"preset": "risk", "labels": {"high": "High", "medium": "Medium", "low": "Low"}},
    }
    multiclass_card = {
        "schema_version": "multiclass-result-presentation.v1",
        "predicted_class_label": "Predicted class",
        "class_probability_distribution_label": "Class probability distribution",
        "model_section_label": "Model",
    }
    regression_card = {
        "schema_version": "continuous-regression-result-presentation.v1",
        "predicted_value_label": "Predicted value",
        "model_section_label": "Model",
        "decimal_places": 2,
    }
    for card in (binary_card, multiclass_card, regression_card):
        jsonschema.validate(_base_profile(result_card=card), schema)
        jsonschema.validate(_base_snapshot({"result_card": card}), snapshot_schema)
