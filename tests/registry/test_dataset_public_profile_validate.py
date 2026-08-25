"""
Dataset public profile reference validator tests for M34-02.

Verifies that validate_profile_references accepts profiles whose reference
fields resolve correctly and rejects profiles whose bound_predict_view_id or
primary_metric_key do not resolve against the injected predict-views registry
and release metrics data, with deterministic, sanitized errors.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_validate.py -v
or directly:
    python tests/registry/test_dataset_public_profile_validate.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_validate import (  # noqa: E402
    normalize_binary_result_presentation,
    normalize_continuous_regression_result_presentation,
    normalize_multiclass_result_presentation,
    normalize_result_presentation,
    normalize_univariate_forecasting_result_presentation,
    validate_profile_references,
)


_MOCK_PREDICT_VIEWS_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-views.v1",
    "predict_views": [
        {"view_id": "churn-risk-overview", "dataset_slug": "telco-customer-churn"},
        {"view_id": "bank-subscription-predictor", "dataset_slug": "bank-marketing"},
    ],
}

_MOCK_RELEASE_METRICS = {
    "schema_version": "metrics.v1",
    "dataset_slug": "telco-customer-churn",
    "release_id": "release-20260101-001",
    "evaluation": {
        "split": "test",
        "sample_size": 1000,
        "metrics": {
            "accuracy": 0.9,
            "precision": 0.8,
            "recall": 0.7,
            "f1_score": 0.75,
            "auc_roc": 0.85,
        },
    },
}


def _codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


def _profile(**overrides) -> dict:
    base = {
        "schema_version": "1.0.0",
        "dataset_slug": "telco-customer-churn",
    }
    base.update(overrides)
    return base


def _performance_focus(**overrides) -> dict:
    focus = {
        "focus_id": "positive_class_detection",
        "highlighted_score_id": "recall",
        "visible_scores": [
            {"score_id": "recall", "display_label": "Recall", "value": "0.574", "value_source": "manual", "order": 0},
            {"score_id": "precision", "display_label": "Precision", "value": "0.679", "value_source": "canonical", "order": 1},
        ],
    }
    focus.update(overrides)
    return focus


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_profile_with_no_references_passes():
    result = validate_profile_references(
        _profile(),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
    assert result["errors"] == []


def test_profile_with_null_references_passes():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": None},
            home_card={"primary_metric_key": None},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_profile_with_valid_bound_predict_view_id_passes():
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "churn-risk-overview"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_composite_bound_predict_view_resolution_is_order_independent():
    """S0261: resolution is the exact composite pair
    (profile.dataset_slug, bound_predict_view_id) -- valid regardless of
    where in the registry array the matching dataset-scoped record sits
    relative to same-view_id records for other datasets."""
    profile = _profile(
        inference_presentation={"bound_predict_view_id": "churn-risk-overview"},
    )
    own_record = {"view_id": "churn-risk-overview", "dataset_slug": "telco-customer-churn"}
    other_record = {"view_id": "churn-risk-overview", "dataset_slug": "bank-marketing"}

    for registry_order in ([own_record, other_record], [other_record, own_record]):
        registry = {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": registry_order,
        }
        result = validate_profile_references(profile, registry, _MOCK_RELEASE_METRICS)
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
        assert result["errors"] == []


def test_bound_predict_view_id_present_only_for_another_dataset_is_mismatch():
    registry = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {"view_id": "churn-risk-overview", "dataset_slug": "bank-marketing"},
        ],
    }
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "churn-risk-overview"}),
        registry,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_DATASET_MISMATCH" in _codes(result)
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" not in _codes(result)


def test_bound_predict_view_id_absent_everywhere_is_not_found():
    registry = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {"view_id": "some-other-view", "dataset_slug": "telco-customer-churn"},
        ],
    }
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "churn-risk-overview"}),
        registry,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in _codes(result)
    assert "BOUND_PREDICT_VIEW_DATASET_MISMATCH" not in _codes(result)


def test_profile_with_valid_primary_metric_key_passes():
    result = validate_profile_references(
        _profile(home_card={"primary_metric_key": "accuracy"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_valid_performance_focus_passes():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus()),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result == {"valid": True, "errors": []}


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------

def test_bound_predict_view_not_found_rejected():
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "nonexistent-view"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in _codes(result)


def test_bound_predict_view_dataset_mismatch_rejected():
    result = validate_profile_references(
        _profile(
            dataset_slug="telco-customer-churn",
            inference_presentation={"bound_predict_view_id": "bank-subscription-predictor"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_DATASET_MISMATCH" in _codes(result)
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" not in _codes(result)


def test_primary_metric_key_not_found_rejected():
    result = validate_profile_references(
        _profile(home_card={"primary_metric_key": "nonexistent_metric"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PRIMARY_METRIC_KEY_NOT_FOUND" in _codes(result)


def test_both_references_invalid_accumulates_both_errors():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": "nonexistent-view"},
            home_card={"primary_metric_key": "nonexistent_metric"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    codes = _codes(result)
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in codes
    assert "PRIMARY_METRIC_KEY_NOT_FOUND" in codes


def test_performance_focus_rejects_unknown_focus_duplicates_and_invisible_highlight():
    duplicate = {"score_id": "recall", "display_label": "Recall", "value": "0.1", "value_source": "manual", "order": 1}
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="unknown_focus",
            highlighted_score_id="precision",
            visible_scores=[duplicate, {**duplicate, "order": 2}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    codes = _codes(result)
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_UNKNOWN" in codes
    assert "PERFORMANCE_SCORE_DUPLICATE" in codes
    assert "PERFORMANCE_HIGHLIGHT_NOT_VISIBLE" in codes


def test_performance_focus_rejects_score_outside_focus_and_unsafe_label():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(visible_scores=[{
            "score_id": "roc_auc", "display_label": "<script>", "value": "0.85",
            "value_source": "manual", "order": 0,
        }], highlighted_score_id="roc_auc")),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def test_error_messages_contain_no_filesystem_paths():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": "nonexistent-view"},
            home_card={"primary_metric_key": "nonexistent_metric"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    for error in result["errors"]:
        msg = error.get("message", "")
        assert "/internal/" not in msg
        assert "/workspace/" not in msg
        assert "/home/" not in msg


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def test_legacy_result_card_normalizes_to_canonical_without_submit_or_technical_fields():
    legacy = {
        "probability_label": "  Event probability  ",
        "submit_button_label": "Run now",
        "model_label": "Estimator",
        "badge_preset": "risk",
        "badge_labels": {"high": "Red", "medium": "Amber", "low": "Green"},
    }
    normalized = normalize_binary_result_presentation(legacy)
    assert normalized["positive_class_probability_label"] == "Event probability"
    # Project Spec S0239: legacy model_label is readable-only compatibility
    # copy -- it never controls the normalized model_section_label output.
    assert normalized["model_section_label"] == "Model"
    assert normalized["predicted_outcome_label"] == "Predicted outcome"
    assert normalized["interpretation"]["labels"] == {
        "high": "Red", "medium": "Amber", "low": "Green"
    }
    assert "submit_button_label" not in normalized
    assert normalize_binary_result_presentation(normalized) == normalized


def test_mixed_result_card_normalization_uses_canonical_precedence():
    normalized = normalize_binary_result_presentation({
        "positive_class_probability_label": "Canonical probability",
        "probability_label": "Legacy probability",
        "interpretation": {"labels": {"high": "Canonical high"}},
        "badge_labels": {"high": "Legacy high", "medium": "Legacy medium"},
    })
    assert normalized["positive_class_probability_label"] == "Canonical probability"
    assert normalized["interpretation"]["labels"] == {
        "high": "Canonical high", "medium": "Legacy medium", "low": "Low"
    }


# ---------------------------------------------------------------------------
# Fixed Model section label (Project Spec S0239)
# ---------------------------------------------------------------------------

def test_binary_result_card_model_section_label_is_fixed_regardless_of_copy():
    assert normalize_binary_result_presentation(
        {"model_section_label": "Scoring model"}
    )["model_section_label"] == "Model"
    assert normalize_binary_result_presentation(
        {"model_label": "Estimator"}
    )["model_section_label"] == "Model"
    assert normalize_binary_result_presentation({})["model_section_label"] == "Model"
    normalized = normalize_binary_result_presentation({"model_section_label": "Scoring model"})
    assert normalize_binary_result_presentation(normalized) == normalized


def test_multiclass_result_card_model_section_label_is_fixed_regardless_of_copy():
    normalized = normalize_multiclass_result_presentation({"model_section_label": "Scoring model"})
    assert normalized["model_section_label"] == "Model"
    assert normalize_multiclass_result_presentation(normalized) == normalized


def test_continuous_regression_result_card_model_section_label_is_fixed_regardless_of_copy():
    normalized = normalize_continuous_regression_result_presentation({"model_section_label": "Scoring model"})
    assert normalized["model_section_label"] == "Model"
    assert normalize_continuous_regression_result_presentation(normalized) == normalized


def test_multiclass_result_card_normalization_is_copy_only_and_idempotent():
    normalized = normalize_multiclass_result_presentation({
        "predicted_class_label": "  Winning class  ",
        "class_probability_distribution_label": " ",
        "classes": [{"class_id": "forbidden"}],
        "threshold": 0.5,
    })
    assert normalized == {
        "schema_version": "multiclass-result-presentation.v1",
        "predicted_class_label": "Winning class",
        "class_probability_distribution_label": "Class probability distribution",
        "model_section_label": "Model",
    }
    assert normalize_result_presentation(normalized) == normalized
    assert normalize_result_presentation(None, "multiclass_classification")["schema_version"] == "multiclass-result-presentation.v1"


# ---------------------------------------------------------------------------
# Continuous regression presentation (Project Spec S0229)
# ---------------------------------------------------------------------------

def test_continuous_regression_result_card_normalization_is_copy_only_and_idempotent():
    normalized = normalize_continuous_regression_result_presentation({
        "predicted_value_label": "  Predicted compressive strength  ",
        "model_section_label": " ",
        "decimal_places": 3,
        "value_unit_label": "  MPa  ",
        "predicted_value": 42.73,
        "threshold": 0.5,
    })
    assert normalized == {
        "schema_version": "continuous-regression-result-presentation.v1",
        "predicted_value_label": "Predicted compressive strength",
        "model_section_label": "Model",
        "decimal_places": 3,
        "value_unit_label": "MPa",
    }
    assert normalize_continuous_regression_result_presentation(normalized) == normalized
    assert normalize_result_presentation(normalized) == normalized
    assert (
        normalize_result_presentation(None, "continuous_regression")["schema_version"]
        == "continuous-regression-result-presentation.v1"
    )


def test_continuous_regression_decimal_places_bounded_and_defaults():
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": 0}
    )["decimal_places"] == 0
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": 6}
    )["decimal_places"] == 6
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": 7}
    )["decimal_places"] == 2
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": -1}
    )["decimal_places"] == 2
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": True}
    )["decimal_places"] == 2
    assert normalize_continuous_regression_result_presentation(
        {"decimal_places": "2"}
    )["decimal_places"] == 2
    assert normalize_continuous_regression_result_presentation({})["decimal_places"] == 2


def test_continuous_regression_value_unit_label_optional_presentation_only():
    without_unit = normalize_continuous_regression_result_presentation({"predicted_value_label": "Predicted value"})
    assert "value_unit_label" not in without_unit
    assert normalize_continuous_regression_result_presentation({"value_unit_label": "   "}).get("value_unit_label") is None


def test_malformed_continuous_regression_result_card_normalizes_deterministically():
    assert normalize_continuous_regression_result_presentation(None) == normalize_continuous_regression_result_presentation({})
    assert normalize_continuous_regression_result_presentation("not-a-dict") == normalize_continuous_regression_result_presentation({})


# ---------------------------------------------------------------------------
# Univariate forecasting presentation (Project Spec S0249)
# ---------------------------------------------------------------------------

def test_univariate_forecasting_result_card_normalization_is_copy_only_and_idempotent():
    normalized = normalize_univariate_forecasting_result_presentation({
        "forecast_series_label": "  Monthly demand forecast  ",
        "future_time_index_label": "  Month  ",
        "forecast_value_label": "  Forecasted demand  ",
        "model_section_label": " ",
        "decimal_places": 1,
        "value_unit_label": "  units  ",
        "forecast_points": [{"horizon_step": 1, "future_time_index": "2026-08", "forecast": 42.0}],
        "forecast_origin": "2026-07",
    })
    assert normalized == {
        "schema_version": "univariate-forecasting-result-presentation.v1",
        "forecast_series_label": "Monthly demand forecast",
        "future_time_index_label": "Month",
        "forecast_value_label": "Forecasted demand",
        "model_section_label": "Model",
        "decimal_places": 1,
        "value_unit_label": "units",
    }
    assert normalize_univariate_forecasting_result_presentation(normalized) == normalized
    assert normalize_result_presentation(normalized) == normalized
    assert (
        normalize_result_presentation(None, "univariate_forecasting")["schema_version"]
        == "univariate-forecasting-result-presentation.v1"
    )


def test_univariate_forecasting_result_card_model_section_label_is_fixed_regardless_of_copy():
    normalized = normalize_univariate_forecasting_result_presentation({"model_section_label": "Forecast model"})
    assert normalized["model_section_label"] == "Model"
    assert normalize_univariate_forecasting_result_presentation(normalized) == normalized


def test_univariate_forecasting_defaults_when_result_card_missing():
    assert normalize_univariate_forecasting_result_presentation({}) == {
        "schema_version": "univariate-forecasting-result-presentation.v1",
        "forecast_series_label": "Forecast",
        "future_time_index_label": "Period",
        "forecast_value_label": "Forecast",
        "model_section_label": "Model",
        "decimal_places": 2,
    }
    assert normalize_result_presentation(None, "univariate_forecasting") == normalize_univariate_forecasting_result_presentation({})


def test_univariate_forecasting_decimal_places_bounded_and_defaults():
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": 0})["decimal_places"] == 0
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": 6})["decimal_places"] == 6
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": 7})["decimal_places"] == 2
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": -1})["decimal_places"] == 2
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": True})["decimal_places"] == 2
    assert normalize_univariate_forecasting_result_presentation({"decimal_places": "2"})["decimal_places"] == 2
    assert normalize_univariate_forecasting_result_presentation({})["decimal_places"] == 2


def test_univariate_forecasting_value_unit_label_optional_presentation_only():
    without_unit = normalize_univariate_forecasting_result_presentation({"forecast_series_label": "Forecast"})
    assert "value_unit_label" not in without_unit
    assert normalize_univariate_forecasting_result_presentation({"value_unit_label": "   "}).get("value_unit_label") is None


def test_malformed_univariate_forecasting_result_card_normalizes_deterministically():
    assert normalize_univariate_forecasting_result_presentation(None) == normalize_univariate_forecasting_result_presentation({})
    assert normalize_univariate_forecasting_result_presentation("not-a-dict") == normalize_univariate_forecasting_result_presentation({})


def test_normalize_result_presentation_trusted_forecasting_dispatch_ignores_other_schema_hint():
    result_card = {
        "schema_version": "multiclass-result-presentation.v1",
        "predicted_class_label": "Predicted class",
        "class_probability_distribution_label": "Class probability distribution",
        "model_section_label": "Model",
    }
    normalized = normalize_result_presentation(result_card, "univariate_forecasting")
    assert normalized["schema_version"] == "univariate-forecasting-result-presentation.v1"


def test_normalize_result_presentation_forecasting_schema_dispatch_without_trusted_type():
    normalized = normalize_univariate_forecasting_result_presentation({"forecast_series_label": "Forecast"})
    assert normalize_result_presentation(normalized) == normalized


def test_normalize_result_presentation_trusted_non_forecasting_type_overrides_forecasting_schema_hint():
    forecasting_card = normalize_univariate_forecasting_result_presentation({"forecast_series_label": "Forecast"})
    assert (
        normalize_result_presentation(forecasting_card, "continuous_regression")["schema_version"]
        == "continuous-regression-result-presentation.v1"
    )
    assert (
        normalize_result_presentation(forecasting_card, "binary_classification")["schema_version"]
        == "binary-result-presentation.v1"
    )
    assert (
        normalize_result_presentation(forecasting_card, "multiclass_classification")["schema_version"]
        == "multiclass-result-presentation.v1"
    )


def test_regression_performance_focus_passes():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="r2",
            visible_scores=[
                {"score_id": "r2", "display_label": "R²", "value": "0.87", "value_source": "canonical", "order": 0},
                {"score_id": "mae", "display_label": "MAE", "value": "3.21", "value_source": "canonical", "order": 1},
                {"score_id": "rmse", "display_label": "RMSE", "value": "4.55", "value_source": "canonical", "order": 2},
            ],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result == {"valid": True, "errors": []}


def test_classification_focus_rejects_regression_score():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="positive_class_detection",
            highlighted_score_id="r2",
            visible_scores=[{"score_id": "r2", "display_label": "R²", "value": "0.87", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


def test_regression_focus_rejects_classification_score():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="accuracy",
            visible_scores=[{"score_id": "accuracy", "display_label": "Accuracy", "value": "0.9", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


# ---------------------------------------------------------------------------
# Project Spec S0240: expected_problem_type applicability guard
# ---------------------------------------------------------------------------

def test_continuous_regression_problem_type_accepts_regression_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.21", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "continuous_regression",
    )
    assert result == {"valid": True, "errors": []}


def test_continuous_regression_problem_type_rejects_positive_class_detection_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus()),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "continuous_regression",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_binary_classification_problem_type_rejects_regression_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.21", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "binary_classification",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_multiclass_classification_problem_type_rejects_regression_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.21", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "multiclass_classification",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_binary_classification_problem_type_accepts_positive_class_detection_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus()),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "binary_classification",
    )
    assert result == {"valid": True, "errors": []}


def test_multiclass_classification_problem_type_accepts_balanced_classification_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="balanced_classification",
            highlighted_score_id="accuracy",
            visible_scores=[{"score_id": "accuracy", "display_label": "Accuracy", "value": "0.9", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "multiclass_classification",
    )
    assert result == {"valid": True, "errors": []}


def test_expected_problem_type_omitted_preserves_existing_behavior():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.21", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result == {"valid": True, "errors": []}
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" not in _codes(result)


def test_unknown_focus_still_reports_unknown_not_mismatch_when_problem_type_supplied():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(focus_id="not_a_real_focus")),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "continuous_regression",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_UNKNOWN" in _codes(result)
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" not in _codes(result)


# ---------------------------------------------------------------------------
# Project Spec S0247: univariate-forecasting Performance focus vocabulary and
# applicability. Mirrors the continuous-regression coverage above.
# ---------------------------------------------------------------------------


def test_forecasting_performance_focus_passes():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="mae",
            visible_scores=[
                {"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0},
                {"score_id": "rmse", "display_label": "RMSE", "value": "4.25", "value_source": "canonical", "order": 1},
                {"score_id": "seasonal_mase", "display_label": "Seasonal MASE", "value": "0.87", "value_source": "canonical", "order": 2},
            ],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result == {"valid": True, "errors": []}


def test_classification_focus_rejects_forecasting_score():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="positive_class_detection",
            highlighted_score_id="seasonal_mase",
            visible_scores=[{"score_id": "seasonal_mase", "display_label": "Seasonal MASE", "value": "0.87", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


def test_regression_focus_rejects_seasonal_mase_score():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="seasonal_mase",
            visible_scores=[{"score_id": "seasonal_mase", "display_label": "Seasonal MASE", "value": "0.87", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


def test_forecasting_focus_rejects_r2_score():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="r2",
            visible_scores=[{"score_id": "r2", "display_label": "R²", "value": "0.87", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


def test_univariate_forecasting_problem_type_accepts_forecasting_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "univariate_forecasting",
    )
    assert result == {"valid": True, "errors": []}


def test_univariate_forecasting_problem_type_rejects_regression_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="regression_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "univariate_forecasting",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_continuous_regression_problem_type_rejects_forecasting_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "continuous_regression",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_binary_classification_problem_type_rejects_forecasting_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "binary_classification",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


def test_multiclass_classification_problem_type_rejects_forecasting_performance_focus():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="forecasting_performance",
            highlighted_score_id="mae",
            visible_scores=[{"score_id": "mae", "display_label": "MAE", "value": "3.10", "value_source": "canonical", "order": 0}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
        "multiclass_classification",
    )
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH" in _codes(result)


if __name__ == "__main__":
    tests = [
        test_profile_with_no_references_passes,
        test_profile_with_null_references_passes,
        test_profile_with_valid_bound_predict_view_id_passes,
        test_composite_bound_predict_view_resolution_is_order_independent,
        test_bound_predict_view_id_present_only_for_another_dataset_is_mismatch,
        test_bound_predict_view_id_absent_everywhere_is_not_found,
        test_profile_with_valid_primary_metric_key_passes,
        test_bound_predict_view_not_found_rejected,
        test_bound_predict_view_dataset_mismatch_rejected,
        test_primary_metric_key_not_found_rejected,
        test_both_references_invalid_accumulates_both_errors,
        test_error_messages_contain_no_filesystem_paths,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
