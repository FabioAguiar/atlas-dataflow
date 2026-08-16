import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

_SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "multiclass-classification-result.schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _valid_three_class_result() -> dict[str, Any]:
    return {
        "schema_version": "multiclass-classification-result.v1",
        "problem_type": "multiclass_classification",
        "predicted_class": {"class_id": "setosa", "display_label": "Setosa"},
        "class_probabilities": [
            {"class_id": "setosa", "display_label": "Setosa", "probability": 0.7},
            {"class_id": "versicolor", "display_label": "Versicolor", "probability": 0.2},
            {"class_id": "virginica", "display_label": "Virginica", "probability": 0.1},
        ],
        "decision": {"strategy": "argmax"},
        "model_descriptor": {"model_family": "logistic_regression", "display_name": "Logistic Regression"},
    }


def _valid_seven_class_result() -> dict[str, Any]:
    class_ids = ["a", "b", "c", "d", "e", "f", "g"]
    probability = 1 / len(class_ids)
    return {
        "schema_version": "multiclass-classification-result.v1",
        "problem_type": "multiclass_classification",
        "predicted_class": {"class_id": "a", "display_label": "A"},
        "class_probabilities": [
            {"class_id": class_id, "display_label": class_id.upper(), "probability": probability}
            for class_id in class_ids
        ],
        "decision": {"strategy": "argmax"},
        "model_descriptor": {"model_family": "random_forest", "display_name": "Random Forest"},
    }


def test_schema_itself_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(_load_schema())


def test_valid_3_class_result_accepted() -> None:
    jsonschema.validate(_valid_three_class_result(), _load_schema())


def test_valid_7_class_result_accepted() -> None:
    jsonschema.validate(_valid_seven_class_result(), _load_schema())


def test_wrong_schema_version_rejected() -> None:
    result = _valid_three_class_result()
    result["schema_version"] = "multiclass-classification-result.v2"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_wrong_problem_type_rejected() -> None:
    result = _valid_three_class_result()
    result["problem_type"] = "binary_classification"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_fewer_than_3_class_probabilities_rejected() -> None:
    result = _valid_three_class_result()
    result["class_probabilities"] = result["class_probabilities"][:2]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_probability_outside_0_1_rejected() -> None:
    result = _valid_three_class_result()
    result["class_probabilities"][0]["probability"] = 1.5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_decision_other_than_argmax_rejected() -> None:
    result = _valid_three_class_result()
    result["decision"] = {"strategy": "max_margin"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_unknown_model_family_rejected() -> None:
    result = _valid_three_class_result()
    result["model_descriptor"]["model_family"] = "xgboost"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_extra_top_level_property_rejected() -> None:
    result = _valid_three_class_result()
    result["extra_unexpected_field"] = "unexpected"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_positive_class_rejected() -> None:
    result = _valid_three_class_result()
    result["positive_class"] = {"class_id": "setosa", "event_label": "Setosa"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_threshold_rejected() -> None:
    result = _valid_three_class_result()
    result["threshold"] = 0.5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_risk_interpretation_rejected() -> None:
    result = _valid_three_class_result()
    result["interpretation"] = {"preset": "risk", "band_id": "high", "bands": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())


def test_confidence_rejected() -> None:
    result = _valid_three_class_result()
    result["confidence"] = 0.99
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, _load_schema())
