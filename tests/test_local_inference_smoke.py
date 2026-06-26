import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime import execute_prediction


@dataclass(frozen=True)
class _SmokeBundle:
    descriptor: dict[str, Any]
    model_artifact: dict[str, Any]


def _write_json(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _valid_bundle_descriptor() -> dict[str, Any]:
    return {
        "contract_version": "inference_bundle.v1",
        "bundle_identity": {
            "bundle_id": "local-smoke-bundle",
            "artifact_kind": "inference_bundle",
        },
        "model_artifact": {
            "path": "models/model.json",
            "sha256": "smoke-test-placeholder",
        },
        "loader": {
            "loader_strategy": "json_threshold_classifier",
            "serialization_format": "json",
            "prediction_interface": "predict",
        },
        "input_schema": {
            "feature_order": ["age", "segment", "balance"],
            "features": [
                {
                    "name": "age",
                    "type": "numeric",
                    "required": True,
                    "minimum": 18,
                    "maximum": 80,
                    "example": 41,
                },
                {
                    "name": "segment",
                    "type": "categorical",
                    "required": True,
                    "allowed_values": ["retail", "smb", "enterprise"],
                    "example": "smb",
                },
                {
                    "name": "balance",
                    "type": "numeric",
                    "required": False,
                    "minimum": 0,
                    "maximum": 100000,
                    "default": 0,
                },
            ],
        },
        "preprocessing": {
            "numeric_missing_value_strategy": "default",
            "categorical_missing_value_strategy": "error",
        },
        "output_schema": {
            "prediction_key": "prediction",
            "prediction_type": "boolean",
        },
    }


def _write_release_package(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    release_root = tmp_path / "release"
    bundle = _valid_bundle_descriptor()
    model = {
        "model_type": "threshold_classifier",
        "numeric_feature": "age",
        "threshold": 40,
    }
    _write_json(release_root / "predictions" / "bundle.json", bundle)
    _write_json(release_root / "models" / "model.json", model)
    compatibility = _write_json(
        release_root / "compatibility-validation.json",
        {
            "status": "compatible",
            "validated_bundle": "predictions/bundle.json",
            "checks": {
                "loader_strategy_supported": True,
                "feature_order_compatible": True,
                "output_schema_compatible": True,
            },
        },
    )
    active_release = {
        "release_root": str(release_root),
        "artifacts": {
            "inference_bundle": {
                "role": "inference_bundle",
                "path": "predictions/bundle.json",
            },
        },
    }
    return active_release, bundle, compatibility


def _require_compatible_bundle(compatibility_path: Path) -> None:
    compatibility = json.loads(compatibility_path.read_text(encoding="utf-8"))
    checks = compatibility.get("checks", {})
    assert compatibility["status"] == "compatible"
    assert checks["loader_strategy_supported"] is True
    assert checks["feature_order_compatible"] is True
    assert checks["output_schema_compatible"] is True


def _valid_payload_from_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    features = {
        feature["name"]: feature
        for feature in bundle["input_schema"]["features"]
    }
    payload = {}
    for feature_name in bundle["input_schema"]["feature_order"]:
        feature = features[feature_name]
        if "example" in feature:
            payload[feature_name] = feature["example"]
        elif "default" in feature:
            payload[feature_name] = feature["default"]
        else:
            raise AssertionError(f"Feature {feature_name} has no contract value")
    return payload


def _load_smoke_bundle(bundle_path: Path) -> _SmokeBundle:
    descriptor = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert descriptor["loader"]["loader_strategy"] == "json_threshold_classifier"
    assert descriptor["loader"]["serialization_format"] == "json"

    model_reference = Path(descriptor["model_artifact"]["path"])
    assert not model_reference.is_absolute()
    model_path = (bundle_path.parent.parent / model_reference).resolve(strict=False)
    model_path.relative_to(bundle_path.parent.parent.resolve())
    model_artifact = json.loads(model_path.read_text(encoding="utf-8"))
    return _SmokeBundle(descriptor=descriptor, model_artifact=model_artifact)


def _execute_smoke_prediction(
    bundle: _SmokeBundle,
    payload: Mapping[str, Any],
) -> bool:
    descriptor = bundle.descriptor
    preprocessing = descriptor["preprocessing"]
    assert preprocessing["numeric_missing_value_strategy"] == "default"
    assert preprocessing["categorical_missing_value_strategy"] == "error"

    features = {
        feature["name"]: feature
        for feature in descriptor["input_schema"]["features"]
    }
    ordered_values = []
    for feature_name in descriptor["input_schema"]["feature_order"]:
        feature = features[feature_name]
        value = payload.get(feature_name, feature.get("default"))
        if value is None and feature.get("required", True):
            raise AssertionError(f"Missing required feature: {feature_name}")
        if feature["type"] == "categorical":
            assert value in feature["allowed_values"]
        if feature["type"] == "numeric":
            assert feature["minimum"] <= value <= feature["maximum"]
        ordered_values.append(value)

    model = bundle.model_artifact
    feature_index = descriptor["input_schema"]["feature_order"].index(model["numeric_feature"])
    prediction = ordered_values[feature_index] >= model["threshold"]
    assert isinstance(prediction, bool)
    return prediction


def _validate_output(result: Mapping[str, Any], bundle: Mapping[str, Any]) -> None:
    output_schema = bundle["output_schema"]
    prediction_key = output_schema["prediction_key"]
    assert prediction_key in result
    if output_schema["prediction_type"] == "boolean":
        assert isinstance(result[prediction_key], bool)


def _reduced_smoke_evidence(result: Mapping[str, Any]) -> dict[str, Any]:
    assert isinstance(result["prediction"], bool)
    return {
        "load": "succeeded",
        "payload_validation": "succeeded",
        "prediction_execution": "succeeded",
        "output_validation": "succeeded",
        "raw_payload_persisted": False,
        "raw_runtime_persisted": False,
    }


def test_local_inference_smoke_uses_bundle_contract(tmp_path: Path) -> None:
    active_release, bundle, compatibility_path = _write_release_package(tmp_path)
    _require_compatible_bundle(compatibility_path)

    valid_payload = _valid_payload_from_bundle(bundle)
    result = execute_prediction(
        active_release,
        valid_payload,
        bundle_loader=_load_smoke_bundle,
        prediction_executor=_execute_smoke_prediction,
    )

    _validate_output(result, bundle)
    evidence = _reduced_smoke_evidence(result)
    assert result == {"prediction": True}
    assert evidence == {
        "load": "succeeded",
        "payload_validation": "succeeded",
        "prediction_execution": "succeeded",
        "output_validation": "succeeded",
        "raw_payload_persisted": False,
        "raw_runtime_persisted": False,
    }
    assert "age" not in evidence
    assert "segment" not in evidence
    assert "balance" not in evidence
