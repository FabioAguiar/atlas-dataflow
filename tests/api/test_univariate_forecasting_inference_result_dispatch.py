"""Focused tests for the forecasting branch of api/inference_result_dispatch.py
(Project Spec S0246). Mirrors tests/api/test_continuous_regression_inference_result_dispatch.py's
discipline: the expected result family comes only from the active release's
normalized project_result_contract semantics; the returned result must never
select its own validator."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from inference_result_dispatch import validate_inference_result  # noqa: E402
from runtime.inference import InferenceRuntimeError  # noqa: E402


_EXPECTED_FORECASTING_CONTRACT = {
    "schema_version": "univariate-forecasting-result-semantics.v1",
    "problem_type": "univariate_forecasting",
    "result_schema_version": "univariate-forecasting-result.v1",
}

_VALID_FORECASTING_RESULT = {
    "schema_version": "univariate-forecasting-result.v1",
    "problem_type": "univariate_forecasting",
    "forecast_origin": 19,
    "frequency": "synthetic-step",
    "forecast_horizon": 2,
    "forecast_points": [
        {"horizon_step": 1, "future_time_index": 20, "forecast": 1.5},
        {"horizon_step": 2, "future_time_index": 21, "forecast": 2.5},
    ],
    "model_descriptor": {
        "model_family": "deterministic_seasonal_trend_ols",
        "display_name": "Deterministic Seasonal-Trend OLS",
    },
}


def test_valid_forecasting_result_accepted():
    validate_inference_result(_VALID_FORECASTING_RESULT, _EXPECTED_FORECASTING_CONTRACT)


def test_result_cannot_select_its_own_validator_via_mismatched_schema_version():
    forged = dict(_VALID_FORECASTING_RESULT)
    forged["schema_version"] = "binary-classification-result.v1"
    try:
        validate_inference_result(forged, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_result_cannot_select_its_own_validator_via_mismatched_problem_type():
    forged = dict(_VALID_FORECASTING_RESULT)
    forged["problem_type"] = "continuous_regression"
    try:
        validate_inference_result(forged, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_malformed_forecasting_result_rejected_by_schema():
    malformed = dict(_VALID_FORECASTING_RESULT)
    malformed["forecast_points"] = []
    try:
        validate_inference_result(malformed, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_forecast_horizon_cardinality_mismatch_rejected():
    malformed = dict(_VALID_FORECASTING_RESULT)
    malformed["forecast_points"] = [_VALID_FORECASTING_RESULT["forecast_points"][0]]
    try:
        validate_inference_result(malformed, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_non_finite_forecast_value_rejected():
    malformed = {
        **_VALID_FORECASTING_RESULT,
        "forecast_points": [
            {"horizon_step": 1, "future_time_index": 20, "forecast": float("nan")},
            {"horizon_step": 2, "future_time_index": 21, "forecast": 2.5},
        ],
    }
    try:
        validate_inference_result(malformed, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_gapped_future_time_index_rejected():
    malformed = {
        **_VALID_FORECASTING_RESULT,
        "forecast_points": [
            {"horizon_step": 1, "future_time_index": 20, "forecast": 1.5},
            {"horizon_step": 2, "future_time_index": 30, "forecast": 2.5},
        ],
    }
    try:
        validate_inference_result(malformed, _EXPECTED_FORECASTING_CONTRACT)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


def test_unknown_expected_contract_discriminator_rejected():
    unknown_contract = {
        "schema_version": "some-other-result-semantics.v1",
        "problem_type": "some_other_problem",
        "result_schema_version": "some-other-result.v1",
    }
    try:
        validate_inference_result(_VALID_FORECASTING_RESULT, unknown_contract)
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError:
        pass


# ---------------------------------------------------------------------------
# Historical regression: binary/multiclass/continuous_regression dispatch
# behavior must remain unaffected by the forecasting addition.
# ---------------------------------------------------------------------------


def test_binary_dispatch_unaffected_by_forecasting_addition():
    expected_contract = {
        "schema_version": "binary-result-semantics.v1",
        "problem_type": "binary_classification",
        "result_schema_version": "binary-classification-result.v1",
    }
    valid_binary_result = {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": "Yes"},
        "positive_class": {"class_id": "Yes", "event_label": "Churn"},
        "positive_class_probability": 0.68,
        "class_probabilities": [
            {"class_id": "No", "probability": 0.32},
            {"class_id": "Yes", "probability": 0.68},
        ],
        "decision": {"threshold": 0.5, "predicted_positive": True},
        "interpretation": {
            "preset": "risk",
            "band_id": "high",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }
    validate_inference_result(valid_binary_result, expected_contract)
