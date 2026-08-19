"""Project Spec S0226: API defense-in-depth dispatch for continuous
regression, dedicated so Concrete/regression-specific fixtures never mix
into the existing binary/multiclass suite
(tests/api/test_inference_result_dispatch.py, left unchanged and still
covering AC-27..AC-32 for those two families end to end)."""

import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import inference_result_dispatch as dispatch  # noqa: E402
from runtime.inference import (  # noqa: E402
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    InferenceRuntimeError,
)


BINARY_EXPECTED = {
    "schema_version": "binary-result-semantics.v1",
    "problem_type": "binary_classification",
    "result_schema_version": "binary-classification-result.v1",
}
MULTICLASS_EXPECTED = {
    "schema_version": "multiclass-result-semantics.v1",
    "problem_type": "multiclass_classification",
    "result_schema_version": "multiclass-classification-result.v1",
}
CONTINUOUS_EXPECTED = {
    "schema_version": "continuous-regression-result-semantics.v1",
    "problem_type": "continuous_regression",
    "result_schema_version": "continuous-regression-result.v1",
}
BINARY_RESULT = {
    "schema_version": "binary-classification-result.v1",
    "problem_type": "binary_classification",
    "predicted_class": {"class_id": "No"},
    "positive_class": {"class_id": "Yes", "event_label": "Churn"},
    "positive_class_probability": 0.2,
    "class_probabilities": [
        {"class_id": "No", "probability": 0.8},
        {"class_id": "Yes", "probability": 0.2},
    ],
    "decision": {"threshold": 0.5, "predicted_positive": False},
    "interpretation": {
        "preset": "risk",
        "band_id": "low",
        "bands": [
            {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
            {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
            {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
        ],
    },
    "model_descriptor": {"model_family": "gradient_boosting", "display_name": "GB"},
}
MULTICLASS_RESULT = {
    "schema_version": "multiclass-classification-result.v1",
    "problem_type": "multiclass_classification",
    "predicted_class": {"class_id": "b", "display_label": "B"},
    "class_probabilities": [
        {"class_id": "a", "display_label": "A", "probability": 0.1},
        {"class_id": "b", "display_label": "B", "probability": 0.7},
        {"class_id": "c", "display_label": "C", "probability": 0.2},
    ],
    "decision": {"strategy": "argmax"},
    "model_descriptor": {"model_family": "decision_tree", "display_name": "Tree"},
}
CONTINUOUS_RESULT = {
    "schema_version": "continuous-regression-result.v1",
    "problem_type": "continuous_regression",
    "predicted_value": 37.25,
    "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
}


def _assert_rejected(result, expected):
    with pytest.raises(InferenceRuntimeError) as caught:
        dispatch.validate_inference_result(result, expected)
    assert caught.value.diagnostic_code == DIAGNOSTIC_RESULT_VALIDATION_FAILED


def test_dispatch_accepts_exact_continuous_expected_and_result_pair():
    dispatch.validate_inference_result(CONTINUOUS_RESULT, CONTINUOUS_EXPECTED)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (CONTINUOUS_RESULT, BINARY_EXPECTED),
        (CONTINUOUS_RESULT, MULTICLASS_EXPECTED),
    ],
)
def test_dispatch_rejects_continuous_result_against_binary_or_multiclass_expected(result, expected):
    _assert_rejected(result, expected)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (BINARY_RESULT, CONTINUOUS_EXPECTED),
        (MULTICLASS_RESULT, CONTINUOUS_EXPECTED),
    ],
)
def test_dispatch_rejects_binary_or_multiclass_result_against_continuous_expected(result, expected):
    _assert_rejected(result, expected)


@pytest.mark.parametrize(
    "expected",
    [
        None,
        {},
        {**CONTINUOUS_EXPECTED, "schema_version": "unknown.v1"},
        {**CONTINUOUS_EXPECTED, "problem_type": "binary_classification"},
        {**CONTINUOUS_EXPECTED, "result_schema_version": "binary-classification-result.v1"},
    ],
)
def test_dispatch_rejects_missing_unknown_or_mixed_continuous_semantics(expected):
    _assert_rejected(CONTINUOUS_RESULT, expected)


def test_dispatch_uses_only_the_selected_continuous_validator(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatch, "validate_binary_classification_result", lambda result: calls.append("binary"))
    monkeypatch.setattr(dispatch, "validate_multiclass_classification_result", lambda result: calls.append("multiclass"))
    monkeypatch.setattr(dispatch, "validate_continuous_regression_result", lambda result: calls.append("continuous_regression"))

    dispatch.validate_inference_result(BINARY_RESULT, BINARY_EXPECTED)
    dispatch.validate_inference_result(MULTICLASS_RESULT, MULTICLASS_EXPECTED)
    dispatch.validate_inference_result(CONTINUOUS_RESULT, CONTINUOUS_EXPECTED)

    assert calls == ["binary", "multiclass", "continuous_regression"]


def test_dispatch_rejects_malformed_selected_continuous_result():
    _assert_rejected({**CONTINUOUS_RESULT, "unexpected": True}, CONTINUOUS_EXPECTED)


def test_dispatch_binary_and_multiclass_behavior_remains_unchanged():
    dispatch.validate_inference_result(BINARY_RESULT, BINARY_EXPECTED)
    dispatch.validate_inference_result(MULTICLASS_RESULT, MULTICLASS_EXPECTED)
    _assert_rejected(MULTICLASS_RESULT, BINARY_EXPECTED)
    _assert_rejected(BINARY_RESULT, MULTICLASS_EXPECTED)
