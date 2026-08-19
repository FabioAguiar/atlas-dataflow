"""Project Spec S0226: isolated Atlas-owned external-inference service
support for continuous regression (external-inference/runtime_loader.py and
external-inference/contracts/external-inference-result.schema.json).

Mirrors the existing multiclass edge-case technique in
tests/test_external_inference_runtime_loader.py (direct ``PredictionPlan``
construction plus ``execute_prediction``, and direct
``_build_prediction_plan``/``validate_bounded_prediction_result`` calls)
rather than building a full governed release fixture for every case. All
fixtures are synthetic Atlas-owned model/bundle fixtures -- no
dataset-study-* repository dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_INFERENCE_DIR = REPO_ROOT / "external-inference"
if str(EXTERNAL_INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_INFERENCE_DIR))

import runtime_loader as rl  # noqa: E402

_ENVELOPE_SCHEMA_PATH = (
    REPO_ROOT / "external-inference" / "contracts" / "external-inference-result.schema.json"
)

_CONTINUOUS_MODEL_DESCRIPTOR = {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"}


# ---------------------------------------------------------------------------
# Isolated prediction-plan selection (_build_prediction_plan)
# ---------------------------------------------------------------------------


def _continuous_bundle(
    *,
    schema_version: str = "continuous-regression-result-semantics.v1",
    problem_type: str = "continuous_regression",
    result_schema_version: str = "continuous-regression-result.v1",
    primary_output: str = "predicted_value",
    output_value_kind: str = "continuous_numeric",
    model_family: str = "gradient_boosting",
    prediction_type: str = "number",
    include_class_labels: bool = False,
    include_probability_output: bool = False,
    model_provenance_origin: str | None = None,
    include_external_model_evidence: bool = False,
) -> dict[str, Any]:
    output_schema: dict[str, Any] = {"prediction_type": prediction_type}
    if include_class_labels:
        output_schema["class_labels"] = ["a", "b"]
    if include_probability_output:
        output_schema["probability_output"] = True

    bundle: dict[str, Any] = {
        "input_schema": {"runtime_contract_reference": "contract_references.runtime_contract"},
        "contract_references": {"runtime_contract": {"contract_version": "runtime-contract.v1"}},
        "feature_order": ["feature_a", "feature_b"],
        "result_semantics": {
            "schema_version": schema_version,
            "problem_type": problem_type,
            "result_schema_version": result_schema_version,
            "primary_output": primary_output,
            "output_value_kind": output_value_kind,
            "model_descriptor": {"model_family": model_family, "display_name": "Gradient Boosting"},
        },
        "output_schema": output_schema,
    }
    if model_provenance_origin is not None:
        bundle["model_provenance_origin"] = model_provenance_origin
    if include_external_model_evidence:
        bundle["external_model_evidence"] = {"origin": "validated_external_fitted_model"}
    return bundle


def _runtime_contract() -> dict[str, Any]:
    return {
        "schema_version": "runtime-contract.v1",
        "features": [
            {"name": "feature_a", "required": True},
            {"name": "feature_b", "required": False},
        ],
    }


def test_isolated_plan_selects_continuous_regression_explicitly():
    plan = rl._build_prediction_plan(_continuous_bundle(), _runtime_contract())
    assert plan.result_variant == "continuous_regression"
    assert plan.model_descriptor == _CONTINUOUS_MODEL_DESCRIPTOR
    assert plan.feature_order == ("feature_a", "feature_b")
    assert plan.required_features == frozenset({"feature_a"})
    assert plan.output_classes == ()


def test_isolated_plan_validates_bounded_model_descriptor():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(model_family="logistic_regression"), _runtime_contract()
        )


def test_isolated_plan_rejects_non_number_prediction_type():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(prediction_type="string"), _runtime_contract()
        )


def test_isolated_plan_rejects_class_labels_present():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(include_class_labels=True), _runtime_contract()
        )


def test_isolated_plan_rejects_probability_output_present():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(include_probability_output=True), _runtime_contract()
        )


def test_isolated_plan_requires_atlas_owned_provenance():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(
                model_provenance_origin="validated_external_fitted_model",
                include_external_model_evidence=True,
            ),
            _runtime_contract(),
        )


def test_isolated_plan_accepts_explicit_atlas_internal_training_provenance():
    plan = rl._build_prediction_plan(
        _continuous_bundle(model_provenance_origin="atlas_internal_training"), _runtime_contract()
    )
    assert plan.result_variant == "continuous_regression"


def test_isolated_plan_unknown_result_semantics_fail_closed():
    with pytest.raises(rl.LoadSafeGateError):
        rl._build_prediction_plan(
            _continuous_bundle(schema_version="unknown-semantics.v1"), _runtime_contract()
        )


# ---------------------------------------------------------------------------
# Isolated prediction execution (execute_prediction)
# ---------------------------------------------------------------------------


class _SyntheticContinuousRegressionModel:
    """Predict-only synthetic model -- deliberately no predict_proba and no
    classes_ attribute."""

    def __init__(self, predict_return: Any) -> None:
        self._predict_return = predict_return
        self.frame = None

    def predict(self, frame):
        self.frame = frame
        return self._predict_return


def _continuous_plan() -> rl.PredictionPlan:
    return rl.PredictionPlan(
        result_variant="continuous_regression",
        feature_order=("zeta", "alpha_feature"),
        required_features=frozenset({"zeta"}),
        output_classes=(),
        model_descriptor=dict(_CONTINUOUS_MODEL_DESCRIPTOR),
    )


def test_isolated_predict_only_regressor_succeeds():
    model = _SyntheticContinuousRegressionModel([56.75])
    result = rl.execute_prediction(model, {"zeta": 4}, _continuous_plan())

    assert list(model.frame.columns) == ["zeta", "alpha_feature"]
    assert result == {
        "schema_version": "continuous-regression-result.v1",
        "problem_type": "continuous_regression",
        "predicted_value": 56.75,
        "model_descriptor": _CONTINUOUS_MODEL_DESCRIPTOR,
    }


def test_isolated_runtime_never_requires_predict_proba_or_classes_for_continuous_regression():
    model = _SyntheticContinuousRegressionModel([1.0])
    rl.execute_prediction(model, {"zeta": 4}, _continuous_plan())
    assert not hasattr(model, "predict_proba")
    assert not hasattr(model, "classes_")


@pytest.mark.parametrize(
    "predict_return",
    [[True], ["not-a-number"], [float("nan")], [float("inf")], [float("-inf")], [1.0, 2.0], []],
    ids=["bool", "string", "nan", "positive_inf", "negative_inf", "multi_value", "empty"],
)
def test_isolated_invalid_or_non_finite_prediction_outputs_fail_closed(predict_return):
    model = _SyntheticContinuousRegressionModel(predict_return)
    with pytest.raises(rl.LoadSafeGateError) as caught:
        rl.execute_prediction(model, {"zeta": 4}, _continuous_plan())
    assert caught.value.diagnostic_code == rl.DIAGNOSTIC_PREDICTION_EXECUTION_FAILED


def test_isolated_no_predict_interface_fails_closed():
    class _NoPredictModel:
        pass

    with pytest.raises(rl.LoadSafeGateError):
        rl.execute_prediction(_NoPredictModel(), {"zeta": 4}, _continuous_plan())


# ---------------------------------------------------------------------------
# Isolated bounded-result validation: closed three-family dispatch
# ---------------------------------------------------------------------------


def _bounded_continuous_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "schema_version": "continuous-regression-result.v1",
        "problem_type": "continuous_regression",
        "predicted_value": 12.5,
        "model_descriptor": dict(_CONTINUOUS_MODEL_DESCRIPTOR),
    }
    result.update(overrides)
    return result


def test_isolated_bounded_result_validation_accepts_strict_continuous_result():
    rl.validate_bounded_prediction_result(_bounded_continuous_result())


def test_isolated_bounded_result_validation_rejects_extra_field():
    with pytest.raises(rl.LoadSafeGateError):
        rl.validate_bounded_prediction_result(_bounded_continuous_result(unit="MPa"))


def test_isolated_bounded_result_validation_rejects_missing_field():
    result = _bounded_continuous_result()
    del result["predicted_value"]
    with pytest.raises(rl.LoadSafeGateError):
        rl.validate_bounded_prediction_result(result)


def test_isolated_bounded_result_validation_rejects_unbounded_model_family():
    with pytest.raises(rl.LoadSafeGateError):
        rl.validate_bounded_prediction_result(
            _bounded_continuous_result(model_descriptor={"model_family": "decision_tree", "display_name": "Tree"})
        )


def test_isolated_bounded_result_validation_fails_closed_on_unknown_problem_type():
    with pytest.raises(rl.LoadSafeGateError):
        rl.validate_bounded_prediction_result(
            _bounded_continuous_result(problem_type="count_regression")
        )


def test_isolated_bounded_result_validation_binary_and_multiclass_remain_unchanged():
    binary_result = {
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
    multiclass_result = {
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
    rl.validate_bounded_prediction_result(binary_result)
    rl.validate_bounded_prediction_result(multiclass_result)


# ---------------------------------------------------------------------------
# external_inference_result.v1 envelope
# ---------------------------------------------------------------------------


def _envelope_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def test_envelope_contract_version_is_unchanged():
    schema = json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["contract_version"]["const"] == "external_inference_result.v1"


def test_envelope_accepts_successful_continuous_regression_result():
    validator = _envelope_validator()
    envelope = {
        "contract_version": "external_inference_result.v1",
        "status": "ok",
        "runtime_compatibility_status": "compatible",
        "diagnostic_code": None,
        "result": _bounded_continuous_result(),
    }
    assert list(validator.iter_errors(envelope)) == []


def test_envelope_failed_response_requires_null_result():
    validator = _envelope_validator()
    failed_envelope = {
        "contract_version": "external_inference_result.v1",
        "status": "failed",
        "runtime_compatibility_status": "incompatible",
        "diagnostic_code": "PREDICTION_EXECUTION_FAILED",
        "result": None,
    }
    assert list(validator.iter_errors(failed_envelope)) == []

    invalid_failed_envelope = dict(failed_envelope, result=_bounded_continuous_result())
    assert list(validator.iter_errors(invalid_failed_envelope)) != []
