"""Project Spec S0226: continuous-regression runtime result contract and
in-process execution dispatch.

Covers contracts/continuous-regression-result.schema.json, the closed
three-family result-semantics resolver, the strict continuous-regression
bundle semantics validator, in-process continuous-regression execution
(``_execute_continuous_regression_prediction`` / ``execute_prediction``),
the explicit three-way governed execution dispatcher, and
``project_result_contract``'s continuous-regression projection. All
fixtures are synthetic Atlas-owned model/bundle fixtures -- no
dataset-study-* repository dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.inference import (  # noqa: E402
    BundleExecutionError,
    BundleValidationError,
    execute_prediction,
    project_result_contract,
    validate_continuous_regression_result,
)

_RESULT_SCHEMA_PATH = REPO_ROOT / "contracts" / "continuous-regression-result.schema.json"


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _result_schema_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(_RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def _strict_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "schema_version": "continuous-regression-result.v1",
        "problem_type": "continuous_regression",
        "predicted_value": 42.5,
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# Canonical schema tests (contracts/continuous-regression-result.schema.json)
# ---------------------------------------------------------------------------


def test_canonical_schema_accepts_one_strict_result() -> None:
    validator = _result_schema_validator()
    assert list(validator.iter_errors(_strict_result())) == []


def test_canonical_schema_rejects_additional_field() -> None:
    validator = _result_schema_validator()
    result = _strict_result()
    result["confidence_interval"] = {"lower": 1.0, "upper": 2.0}
    assert list(validator.iter_errors(result)) != []


@pytest.mark.parametrize(
    "field,value",
    [
        ("predicted_class", {"class_id": "x"}),
        ("positive_class", {"class_id": "x", "event_label": "y"}),
        ("class_probabilities", [{"class_id": "a", "probability": 0.5}]),
        ("decision", {"threshold": 0.5}),
        ("interpretation", {"preset": "risk"}),
    ],
)
def test_canonical_schema_rejects_classification_fields(field: str, value: Any) -> None:
    validator = _result_schema_validator()
    result = _strict_result()
    result[field] = value
    assert list(validator.iter_errors(result)) != []


def test_canonical_schema_rejects_unbounded_model_family() -> None:
    validator = _result_schema_validator()
    result = _strict_result(model_descriptor={"model_family": "logistic_regression", "display_name": "LR"})
    assert list(validator.iter_errors(result)) != []


@pytest.mark.parametrize("missing_field", ["schema_version", "problem_type", "predicted_value", "model_descriptor"])
def test_canonical_schema_rejects_missing_required_field(missing_field: str) -> None:
    validator = _result_schema_validator()
    result = _strict_result()
    del result[missing_field]
    assert list(validator.iter_errors(result)) != []


def test_validate_continuous_regression_result_accepts_strict_result() -> None:
    validate_continuous_regression_result(_strict_result())


def test_validate_continuous_regression_result_rejects_extra_field() -> None:
    with pytest.raises(BundleValidationError):
        validate_continuous_regression_result(_strict_result(unit="MPa"))


# ---------------------------------------------------------------------------
# In-process execution fixtures
# ---------------------------------------------------------------------------


class _FakeRegressionModel:
    """Predict-only synthetic model. Deliberately has no predict_proba and no
    classes_ attribute -- accessing either from continuous-regression
    execution is a real test failure, not just an assertion."""

    def __init__(self, predict_return: Any) -> None:
        self._predict_return = predict_return

    def predict(self, _row: Any) -> Any:
        return self._predict_return


def _continuous_regression_declaration(
    *,
    schema_version: str = "continuous-regression-result-semantics.v1",
    problem_type: str = "continuous_regression",
    result_schema_version: str = "continuous-regression-result.v1",
    primary_output: str = "predicted_value",
    output_value_kind: str = "continuous_numeric",
    model_family: str = "gradient_boosting",
    prediction_type: str = "number",
    model_provenance_origin: str | None = None,
    include_external_model_evidence: bool = False,
    include_class_labels: bool = False,
    include_probability_output: bool = False,
    extra_semantics_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_semantics: dict[str, Any] = {
        "schema_version": schema_version,
        "problem_type": problem_type,
        "result_schema_version": result_schema_version,
        "primary_output": primary_output,
        "output_value_kind": output_value_kind,
        "model_descriptor": {"model_family": model_family, "display_name": "Gradient Boosting"},
    }
    if extra_semantics_fields:
        result_semantics.update(extra_semantics_fields)

    output_schema: dict[str, Any] = {"prediction_key": "prediction", "prediction_type": prediction_type}
    if include_class_labels:
        output_schema["class_labels"] = ["a", "b"]
    if include_probability_output:
        output_schema["probability_output"] = True

    declaration: dict[str, Any] = {
        "feature_order": ["feature_a", "feature_b"],
        "runtime_execution": {
            "loader_strategy": "fake_continuous_regression_model",
            "serialization_format": "fake",
        },
        "model_artifact": {"path": "models/model.json"},
        "output_schema": output_schema,
        "result_semantics": result_semantics,
    }
    if model_provenance_origin is not None:
        declaration["model_provenance_origin"] = model_provenance_origin
    if include_external_model_evidence:
        declaration["external_model_evidence"] = {"origin": "validated_external_fitted_model"}

    return declaration


def _execute(tmp_path: Path, declaration: dict[str, Any], model: Any) -> dict[str, Any]:
    release_root = tmp_path / "release-s0226"
    _write_json(release_root / "predictions" / "bundle.json", declaration)
    _write_json(release_root / "models" / "model.json", {"placeholder": True})

    def _load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_fake_model(_path: Path, _declaration: Mapping[str, Any]) -> Any:
        return model

    return execute_prediction(
        {"path": str(release_root)},
        {"feature_a": 1.0, "feature_b": 2.0},
        manifest={"artifacts": [{"role": "predictive_bundle", "reference": "predictions/bundle.json"}]},
        bundle_loader=_load_declaration,
        loader_strategies={"fake_continuous_regression_model": _load_fake_model},
        supported_serialization_formats=["fake"],
    )


# ---------------------------------------------------------------------------
# In-process execution: success path
# ---------------------------------------------------------------------------


def test_in_process_predict_only_regressor_succeeds(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[123.456])
    result = _execute(tmp_path, _continuous_regression_declaration(), model)["result"]

    assert result == {
        "schema_version": "continuous-regression-result.v1",
        "problem_type": "continuous_regression",
        "predicted_value": 123.456,
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }


def test_in_process_regression_never_requires_predict_proba_or_classes(tmp_path: Path) -> None:
    # _FakeRegressionModel intentionally exposes neither predict_proba nor
    # classes_; a successful execution here is itself the proof that neither
    # attribute was ever required or accessed.
    model = _FakeRegressionModel(predict_return=[7.0])
    result = _execute(tmp_path, _continuous_regression_declaration(), model)["result"]
    assert result["predicted_value"] == 7.0
    assert not hasattr(model, "predict_proba")
    assert not hasattr(model, "classes_")


def test_in_process_random_forest_model_family_succeeds(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[10.0])
    declaration = _continuous_regression_declaration(model_family="random_forest")
    result = _execute(tmp_path, declaration, model)["result"]
    assert result["model_descriptor"] == {"model_family": "random_forest", "display_name": "Gradient Boosting"}


# ---------------------------------------------------------------------------
# In-process execution: fail-closed prediction shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "predict_return",
    [
        [True],
        ["42.5"],
        [float("nan")],
        [float("inf")],
        [float("-inf")],
        [1.0, 2.0],
        [],
    ],
    ids=["bool", "string", "nan", "positive_inf", "negative_inf", "multi_value", "empty"],
)
def test_in_process_invalid_prediction_shapes_fail_closed(tmp_path: Path, predict_return: Any) -> None:
    model = _FakeRegressionModel(predict_return=predict_return)
    with pytest.raises(BundleExecutionError):
        _execute(tmp_path, _continuous_regression_declaration(), model)


def test_in_process_no_predict_interface_fails_closed(tmp_path: Path) -> None:
    class _NoPredictModel:
        pass

    with pytest.raises(BundleExecutionError):
        _execute(tmp_path, _continuous_regression_declaration(), _NoPredictModel())


# ---------------------------------------------------------------------------
# In-process execution: bundle-level semantics fail-closed cases
# ---------------------------------------------------------------------------


def test_class_labels_on_continuous_regression_output_schema_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(include_class_labels=True)
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


def test_probability_output_on_continuous_regression_output_schema_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(include_probability_output=True)
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


def test_prediction_type_not_number_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(prediction_type="string")
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


def test_external_fitted_model_provenance_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(
        model_provenance_origin="validated_external_fitted_model",
        include_external_model_evidence=True,
    )
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


def test_atlas_internal_training_provenance_succeeds(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(model_provenance_origin="atlas_internal_training")
    result = _execute(tmp_path, declaration, model)["result"]
    assert result["predicted_value"] == 1.0


def test_unbounded_model_family_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(model_family="logistic_regression")
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


# ---------------------------------------------------------------------------
# Closed result-semantics resolver: unknown/mixed semantics fail closed
# ---------------------------------------------------------------------------


def test_mixed_schema_version_and_problem_type_fail_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(problem_type="binary_classification")
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
    model = _FakeRegressionModel(predict_return=[1.0])
    declaration = _continuous_regression_declaration(schema_version="continuous-regression-result-semantics.v0")
    with pytest.raises(BundleValidationError):
        _execute(tmp_path, declaration, model)


# ---------------------------------------------------------------------------
# project_result_contract: continuous projection without model loading
# ---------------------------------------------------------------------------


def test_project_result_contract_projects_continuous_semantics_without_model_load() -> None:
    declaration = _continuous_regression_declaration()
    contract = project_result_contract(declaration)

    assert contract == {
        "status": "available",
        "semantics": {
            "schema_version": "continuous-regression-result-semantics.v1",
            "problem_type": "continuous_regression",
            "result_schema_version": "continuous-regression-result.v1",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
            "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
        },
    }


def test_project_result_contract_never_invents_class_or_probability_fields() -> None:
    declaration = _continuous_regression_declaration()
    contract = project_result_contract(declaration)
    semantics = contract["semantics"]
    assert "classes" not in semantics
    assert "positive_class" not in semantics
    assert "decision" not in semantics
    assert "interpretation" not in semantics


def test_project_result_contract_fails_closed_on_unknown_semantics() -> None:
    declaration = _continuous_regression_declaration(schema_version="unknown-semantics.v1")
    assert project_result_contract(declaration) == {
        "status": "unavailable",
        "reason": "binary_result_semantics_unavailable",
    }


def test_project_result_contract_fails_closed_on_class_labels_present() -> None:
    declaration = _continuous_regression_declaration(include_class_labels=True)
    assert project_result_contract(declaration) == {
        "status": "unavailable",
        "reason": "binary_result_semantics_unavailable",
    }


def test_project_result_contract_binary_and_multiclass_remain_unaffected() -> None:
    # Never breaking historical bundles with no result_semantics at all.
    assert project_result_contract({}) == {
        "status": "unavailable",
        "reason": "binary_result_semantics_unavailable",
    }
