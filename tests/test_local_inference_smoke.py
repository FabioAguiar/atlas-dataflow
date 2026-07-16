import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training_module
from pipeline.generate_inference_bundle import (
    BundleGenerationError,
    _build_bundle,
    _build_parser,
    materialize_governed_inference_bundle,
)
from runtime import execute_prediction
from runtime.inference import (
    BundleUnavailableError,
    BundleValidationError,
    load_joblib_sklearn_model,
    load_runtime_bundle_adapter,
    validate_binary_classification_result,
)

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


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


TELCO_FEATURE_COLUMNS = [
    "gender",
    "SeniorCitizen",
    "Partner",
    "tenure",
    "InternetService",
    "MonthlyCharges",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _synthetic_execution_contract() -> dict[str, Any]:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "telco-customer-churn",
        "target_column": "Churn",
        "feature_columns": list(TELCO_FEATURE_COLUMNS),
        "ignored_columns": ["customerID", "TotalCharges"],
        "required_columns": list(TELCO_FEATURE_COLUMNS),
        "optional_columns": [],
        "feature_definitions": {
            "gender": {"type": "categorical"},
            "SeniorCitizen": {"type": "boolean"},
            "Partner": {"type": "boolean"},
            "tenure": {"type": "numeric", "domain_constraints": {"min": 0, "max": 72}},
            "InternetService": {"type": "categorical"},
            "MonthlyCharges": {
                "type": "numeric",
                "domain_constraints": {"min": 18.25, "max": 118.75},
            },
        },
        # The real Telco execution contract declares no per-feature missing-value
        # handling because the only column with blanks (TotalCharges) is ignored;
        # an empty policy must remain generation-valid, not be treated as absent.
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
    }


def _synthetic_runtime_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "features": [{"name": name, "required": True} for name in TELCO_FEATURE_COLUMNS],
    }


def _synthetic_public_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "features": [{"name": name, "label": name} for name in TELCO_FEATURE_COLUMNS],
    }


def _synthetic_prepared_dataset_metadata() -> dict[str, Any]:
    return {
        "schema_version": "prepared-data-metadata.v1",
        "dataset_identity": {"dataset_slug": "telco-customer-churn"},
    }


def _synthetic_training_record(
    *,
    execution_contract_sha256: str,
    prepared_dataset_sha256: str,
    model_artifact_sha256: str,
    metrics_sha256: str,
    model_family: str = "logistic_regression",
    serializer_name: str = "joblib",
    feature_columns: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "training-parameter-record.v1",
        "training_run_identity": {
            "dataset_slug": "telco-customer-churn",
            "run_id": "train-20260709T000000Z",
        },
        "produced_outputs": {
            "serialized_model_path": "models/model.pkl",
            "training_parameter_record_path": "training/training-parameter-record.json",
        },
        "serializer": {"name": serializer_name, "installed_version": "1.4.0"},
        "training_parameters": {
            "model_family": model_family,
            "feature_columns": feature_columns or list(TELCO_FEATURE_COLUMNS),
        },
        "hashes": {
            "execution_contract_sha256": execution_contract_sha256,
            "prepared_dataset_sha256": prepared_dataset_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
    }


def _synthetic_metrics() -> dict[str, Any]:
    return {
        "schema_version": "training-metrics.v1",
        "training_run_identity": {
            "dataset_slug": "telco-customer-churn",
            "run_id": "train-20260709T000000Z",
        },
    }


def _write_governed_fixtures(tmp_path: Path) -> tuple[list[str], dict[str, Path]]:
    """Write a synthetic Telco-shaped governed fixture set (contracts, prepared
    dataset metadata, training parameter record, metrics, model artifact) and
    return the `generate_inference_bundle` CLI argv plus the written file paths.

    All artifacts are explicit repository/release-relative references supplied
    by the caller, matching the real Telco governed artifact shapes without
    depending on real upstream artifacts existing in the repository yet.
    """
    execution_contract_path = _write_json(
        tmp_path / "execution-contract.json", _synthetic_execution_contract()
    )
    runtime_contract_path = _write_json(
        tmp_path / "runtime-contract.json", _synthetic_runtime_contract()
    )
    public_contract_path = _write_json(
        tmp_path / "public-contract.json", _synthetic_public_contract()
    )
    prepared_dataset_path = _write_json(
        tmp_path / "prepared-data-metadata.json", _synthetic_prepared_dataset_metadata()
    )
    model_artifact_path = _write_bytes(tmp_path / "model.pkl", b"synthetic-joblib-model-bytes")
    metrics_path = _write_json(tmp_path / "metrics.json", _synthetic_metrics())

    training_record = _synthetic_training_record(
        execution_contract_sha256=_sha256_bytes(execution_contract_path.read_bytes()),
        prepared_dataset_sha256=_sha256_bytes(prepared_dataset_path.read_bytes()),
        model_artifact_sha256=_sha256_bytes(model_artifact_path.read_bytes()),
        metrics_sha256=_sha256_bytes(metrics_path.read_bytes()),
    )
    training_record_path = _write_json(
        tmp_path / "training-parameter-record.json", training_record
    )

    output_path = tmp_path / "inference-bundle.json"

    argv = [
        "--execution-contract", str(execution_contract_path),
        "--runtime-contract", str(runtime_contract_path),
        "--public-contract", str(public_contract_path),
        "--prepared-dataset", str(prepared_dataset_path),
        "--training-parameter-record", str(training_record_path),
        "--training-metrics", str(metrics_path),
        "--model-artifact", str(model_artifact_path),
        "--output", str(output_path),
        "--release-package-reference", "predictions/bundle.json",
        "--prediction-type", "boolean",
        "--release-id", "release-20260709-001",
        "--dataset-slug", "telco-customer-churn",
        "--class-label", "No",
        "--class-label", "Yes",
        "--execution-contract-ref", "contracts/telco-customer-churn/execution-contract.json",
        "--runtime-contract-ref", "contracts/telco-customer-churn/runtime-contract.json",
        "--public-contract-ref", "contracts/telco-customer-churn/public-contract.json",
        "--prepared-dataset-ref",
        "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        "--dataset-context-ref",
        "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        "--training-parameter-record-ref", "training/training-parameter-record.json",
        "--training-metrics-ref", "training/metrics.json",
        "--model-artifact-ref", "models/model.pkl",
    ]
    paths = {
        "execution_contract": execution_contract_path,
        "runtime_contract": runtime_contract_path,
        "public_contract": public_contract_path,
        "prepared_dataset": prepared_dataset_path,
        "training_record": training_record_path,
        "metrics": metrics_path,
        "model_artifact": model_artifact_path,
        "output": output_path,
    }
    return argv, paths


def test_generate_inference_bundle_produces_schema_valid_telco_descriptor(
    tmp_path: Path,
) -> None:
    argv, _ = _write_governed_fixtures(tmp_path)
    args = _build_parser().parse_args(argv)

    # _build_bundle validates the result against the real
    # contracts/inference-bundle.schema.json before returning; a successful
    # call is itself proof of schema validity (acceptance criterion 7).
    bundle = _build_bundle(args)

    assert bundle["contract_version"] == "inference_bundle.v1"
    assert bundle["feature_order"] == TELCO_FEATURE_COLUMNS
    assert "customerID" not in bundle["feature_order"]
    assert "TotalCharges" not in bundle["feature_order"]
    assert "SeniorCitizen" in bundle["feature_order"]
    assert bundle["preprocessing"]["missing_value_policy"] == {}
    assert bundle["model_artifact"]["path"] == "models/model.pkl"
    assert bundle["boundary_confirmations"] == {
        "release_relative_paths_only": True,
        "absolute_paths_embedded": False,
        "parent_traversal_embedded": False,
        "notebook_state_embedded": False,
        "raw_dataset_embedded": False,
        "model_bytes_embedded": False,
        "runtime_payload_validation_duplicated": False,
        "training_internals_required_at_runtime": False,
    }


def test_generate_inference_bundle_omits_result_semantics_when_execution_contract_lacks_it(
    tmp_path: Path,
) -> None:
    # Historical-compatibility path: no result_semantics on the execution
    # contract means the bundle is generated exactly as before, with no
    # result_semantics key at all (never null, never invented defaults).
    argv, _ = _write_governed_fixtures(tmp_path)
    args = _build_parser().parse_args(argv)
    bundle = _build_bundle(args)
    assert "result_semantics" not in bundle


# --- binary result-semantics release metadata projection (Project Spec S0108) ---

def _binary_result_semantics_contract_block(positive_class_id: str = "Yes") -> dict[str, Any]:
    return {
        "schema_version": "binary-result-semantics.v1",
        "problem_type": "binary_classification",
        "positive_class": {"class_id": positive_class_id, "event_label": "Churn"},
        "primary_output": "positive_class_probability",
        "decision": {"threshold": 0.5},
        "interpretation": {
            "preset": "risk",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
    }


def _write_governed_fixtures_with_result_semantics(
    tmp_path: Path,
    *,
    result_semantics: dict[str, Any] | None,
    binary_classification_evidence: dict[str, Any] | None,
    class_labels: list[str] = ("No", "Yes"),
    probability_output: bool = True,
    model_family: str = "gradient_boosting",
) -> tuple[list[str], dict[str, Path]]:
    execution_contract = _synthetic_execution_contract()
    if result_semantics is not None:
        execution_contract["result_semantics"] = result_semantics
    execution_contract_path = _write_json(tmp_path / "execution-contract.json", execution_contract)

    runtime_contract_path = _write_json(
        tmp_path / "runtime-contract.json", _synthetic_runtime_contract()
    )
    public_contract_path = _write_json(
        tmp_path / "public-contract.json", _synthetic_public_contract()
    )
    prepared_dataset_path = _write_json(
        tmp_path / "prepared-data-metadata.json", _synthetic_prepared_dataset_metadata()
    )
    model_artifact_path = _write_bytes(tmp_path / "model.pkl", b"synthetic-joblib-model-bytes")
    metrics_path = _write_json(tmp_path / "metrics.json", _synthetic_metrics())

    training_record = _synthetic_training_record(
        execution_contract_sha256=_sha256_bytes(execution_contract_path.read_bytes()),
        prepared_dataset_sha256=_sha256_bytes(prepared_dataset_path.read_bytes()),
        model_artifact_sha256=_sha256_bytes(model_artifact_path.read_bytes()),
        metrics_sha256=_sha256_bytes(metrics_path.read_bytes()),
        model_family=model_family,
    )
    if binary_classification_evidence is not None:
        training_record["binary_classification_evidence"] = binary_classification_evidence
    training_record_path = _write_json(
        tmp_path / "training-parameter-record.json", training_record
    )

    output_path = tmp_path / "inference-bundle.json"
    argv = [
        "--execution-contract", str(execution_contract_path),
        "--runtime-contract", str(runtime_contract_path),
        "--public-contract", str(public_contract_path),
        "--prepared-dataset", str(prepared_dataset_path),
        "--training-parameter-record", str(training_record_path),
        "--training-metrics", str(metrics_path),
        "--model-artifact", str(model_artifact_path),
        "--output", str(output_path),
        "--release-package-reference", "predictions/bundle.json",
        "--prediction-type", "string",
        "--release-id", "release-20260709-001",
        "--dataset-slug", "telco-customer-churn",
        "--execution-contract-ref", "contracts/telco-customer-churn/execution-contract.json",
        "--runtime-contract-ref", "contracts/telco-customer-churn/runtime-contract.json",
        "--public-contract-ref", "contracts/telco-customer-churn/public-contract.json",
        "--prepared-dataset-ref",
        "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        "--dataset-context-ref",
        "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        "--training-parameter-record-ref", "training/training-parameter-record.json",
        "--training-metrics-ref", "training/metrics.json",
        "--model-artifact-ref", "models/model.pkl",
        "--probability-output", "true" if probability_output else "false",
    ]
    for label in class_labels:
        argv.extend(["--class-label", label])
    paths = {
        "execution_contract": execution_contract_path,
        "training_record": training_record_path,
        "output": output_path,
    }
    return argv, paths


def test_generate_inference_bundle_projects_result_semantics_when_present(tmp_path: Path) -> None:
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence={
            "problem_type": "binary_classification",
            "ordered_class_labels": ["No", "Yes"],
            "positive_class_id": "Yes",
            "positive_class_probability_index": 1,
        },
        model_family="gradient_boosting",
    )
    args = _build_parser().parse_args(argv)
    bundle = _build_bundle(args)

    out = bundle["result_semantics"]
    assert out["schema_version"] == "binary-result-semantics.v1"
    assert out["problem_type"] == "binary_classification"
    assert out["result_schema_version"] == "binary-classification-result.v1"
    assert out["primary_output"] == "positive_class_probability"
    assert out["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert out["decision"] == {"threshold": 0.5}
    assert out["interpretation"]["preset"] == "risk"
    assert len(out["interpretation"]["bands"]) == 3
    assert out["model_descriptor"] == {
        "model_family": "gradient_boosting",
        "display_name": "Gradient Boosting",
    }


def test_generate_inference_bundle_model_descriptor_follows_actual_selected_family(
    tmp_path: Path,
) -> None:
    # The display name must be looked up from whatever model_family the
    # training evidence actually selected -- never a hardcoded default.
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence={
            "problem_type": "binary_classification",
            "ordered_class_labels": ["No", "Yes"],
            "positive_class_id": "Yes",
            "positive_class_probability_index": 1,
        },
        model_family="random_forest",
    )
    args = _build_parser().parse_args(argv)
    bundle = _build_bundle(args)
    assert bundle["result_semantics"]["model_descriptor"] == {
        "model_family": "random_forest",
        "display_name": "Random Forest",
    }


def test_generate_inference_bundle_blocks_on_positive_class_mismatch_with_training_evidence(
    tmp_path: Path,
) -> None:
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence={
            "problem_type": "binary_classification",
            "ordered_class_labels": ["No", "Yes"],
            "positive_class_id": "No",  # mismatched vs execution contract's "Yes"
            "positive_class_probability_index": 0,
        },
    )
    args = _build_parser().parse_args(argv)
    with pytest.raises(BundleGenerationError):
        _build_bundle(args)


def test_generate_inference_bundle_blocks_when_class_labels_not_exactly_two(
    tmp_path: Path,
) -> None:
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence={
            "problem_type": "binary_classification",
            "ordered_class_labels": ["No", "Yes"],
            "positive_class_id": "Yes",
            "positive_class_probability_index": 1,
        },
        class_labels=["Yes"],
    )
    args = _build_parser().parse_args(argv)
    with pytest.raises(BundleGenerationError):
        _build_bundle(args)


def test_generate_inference_bundle_blocks_when_probability_output_not_true(
    tmp_path: Path,
) -> None:
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence={
            "problem_type": "binary_classification",
            "ordered_class_labels": ["No", "Yes"],
            "positive_class_id": "Yes",
            "positive_class_probability_index": 1,
        },
        probability_output=False,
    )
    args = _build_parser().parse_args(argv)
    with pytest.raises(BundleGenerationError):
        _build_bundle(args)


def test_generate_inference_bundle_blocks_when_binary_classification_evidence_missing(
    tmp_path: Path,
) -> None:
    result_semantics = _binary_result_semantics_contract_block(positive_class_id="Yes")
    argv, _ = _write_governed_fixtures_with_result_semantics(
        tmp_path,
        result_semantics=result_semantics,
        binary_classification_evidence=None,
    )
    args = _build_parser().parse_args(argv)
    with pytest.raises(BundleGenerationError):
        _build_bundle(args)


def test_generated_bundle_is_consumable_by_runtime_adapter(tmp_path: Path) -> None:
    argv, paths = _write_governed_fixtures(tmp_path)
    args = _build_parser().parse_args(argv)
    bundle = _build_bundle(args)

    release_root = tmp_path / "release"
    _write_json(release_root / "predictions" / "bundle.json", bundle)
    _write_bytes(release_root / "models" / "model.pkl", paths["model_artifact"].read_bytes())

    def _load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_model(path: Path, _declaration: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"loaded_from": path.name}

    adapter = load_runtime_bundle_adapter(
        {
            "release_root": str(release_root),
            "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
        },
        bundle_loader=_load_declaration,
        loader_strategies={"joblib_sklearn_predict": _load_model},
        supported_serialization_formats=["joblib"],
        prediction_executor=lambda model, payload: payload["SeniorCitizen"] is False,
        compatibility_status={"status": "compatible"},
    )

    assert adapter.metadata.feature_order == tuple(TELCO_FEATURE_COLUMNS)
    assert adapter.metadata.runtime_execution["loader_strategy"] == "joblib_sklearn_predict"
    assert adapter.predict({"SeniorCitizen": False}) is True


# Project Spec S0033: the governed inference-bundle materialization boundary
# that bridges a governed training run materialization result (never a
# hardcoded train-pending placeholder or notebook-held state) and a
# prepared-data-metadata.v1 artifact to the generation boundary exercised
# above. `_repo_root` is monkeypatched on `pipeline.training` (the same
# established pattern used by tests/test_training_pipeline.py) so the
# reused `_prepared_dataset_metadata_blocking_reasons` boundary resolves the
# prepared dataset reference against an isolated tmp_path repository rather
# than the real repository.


def test_materialize_governed_inference_bundle_from_trained_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training_module, "_repo_root", lambda: repo_root)

    execution_contract_path = _write_json(
        repo_root / "contracts/telco-customer-churn/execution-contract.json",
        _synthetic_execution_contract(),
    )
    runtime_contract_path = _write_json(
        repo_root / "contracts/telco-customer-churn/runtime-contract.json",
        _synthetic_runtime_contract(),
    )
    public_contract_path = _write_json(
        repo_root / "contracts/telco-customer-churn/public-contract.json",
        _synthetic_public_contract(),
    )
    dataset_context_path = _write_json(
        repo_root / "contracts/telco-customer-churn/dataset-context.json",
        {"schema_version": "dataset-context.v1"},
    )

    prepared_dataset_relative = "pipeline/prepared/telco-customer-churn/prepared-data.csv"
    prepared_dataset_bytes = b"dataset_id,gender\ntelco-customer-churn,Female\n"
    prepared_dataset_path = _write_bytes(
        repo_root / prepared_dataset_relative, prepared_dataset_bytes
    )
    prepared_metadata_path = _write_json(
        repo_root / "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        {
            "schema_version": "prepared-data-metadata.v1",
            "dataset_identity": {"dataset_slug": "telco-customer-churn"},
            "prepared_candidate": {
                "produced": True,
                "reference": {
                    "path": prepared_dataset_relative,
                    "content_sha256": _sha256_bytes(prepared_dataset_bytes),
                },
            },
            "training_readiness": {"is_training_ready": True},
        },
    )

    training_run_relative_dir = "pipeline/training-runs/telco-customer-churn/train-20260709T120000Z"
    model_artifact_path = _write_bytes(
        repo_root / training_run_relative_dir / "model.pkl", b"synthetic-governed-model-bytes"
    )
    metrics = _synthetic_metrics()
    metrics["training_run_identity"]["run_id"] = "train-20260709T120000Z"
    metrics_path = _write_json(repo_root / training_run_relative_dir / "metrics.json", metrics)
    training_record = _synthetic_training_record(
        execution_contract_sha256=_sha256_bytes(execution_contract_path.read_bytes()),
        prepared_dataset_sha256=_sha256_bytes(prepared_dataset_bytes),
        model_artifact_sha256=_sha256_bytes(model_artifact_path.read_bytes()),
        metrics_sha256=_sha256_bytes(metrics_path.read_bytes()),
    )
    training_record["training_run_identity"]["run_id"] = "train-20260709T120000Z"
    training_record["produced_outputs"] = {
        "serialized_model_path": f"{training_run_relative_dir}/model.pkl",
        "training_parameter_record_path": f"{training_run_relative_dir}/training-parameter-record.json",
    }
    training_record_path = _write_json(
        repo_root / training_run_relative_dir / "training-parameter-record.json",
        training_record,
    )

    training_run_materialization_result = {
        "artifact_type": "training_run_materialization_result",
        "status": "trained",
        "training_result": {
            "output_directory": f"{training_run_relative_dir}/",
            "serialized_model_path": f"{training_run_relative_dir}/model.pkl",
            "training_parameter_record_path": training_record_path.relative_to(repo_root).as_posix(),
            "metrics_path": metrics_path.relative_to(repo_root).as_posix(),
            "model_selection_evidence_path": None,
        },
    }

    output_path = repo_root / "contracts/telco-customer-churn/inference-bundle.json"

    result = materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        execution_contract_path=execution_contract_path,
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_data_metadata_path=prepared_metadata_path,
        output_path=output_path,
        prediction_type="string",
        repo_root=repo_root,
        class_labels=["No", "Yes"],
        probability_output=True,
        execution_contract_ref="contracts/telco-customer-churn/execution-contract.json",
        runtime_contract_ref="contracts/telco-customer-churn/runtime-contract.json",
        public_contract_ref="contracts/telco-customer-churn/public-contract.json",
        dataset_context_ref="contracts/telco-customer-churn/dataset-context.json",
    )

    assert result["status"] == "generated"
    assert result["training_run_id"] == "train-20260709T120000Z"
    assert result["provisional_release_id"] == "release-20260709-001"
    assert output_path.exists()

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["contract_version"] == "inference_bundle.v1"
    assert generated["release_context"]["release_id"] == "release-20260709-001"
    assert generated["release_context"]["release_package_reference"] == "predictions/bundle.json"
    assert "customerID" not in generated["feature_order"]
    assert "TotalCharges" not in generated["feature_order"]
    assert generated["prepared_dataset"]["prepared_dataset_reference"]["path"] == (
        prepared_dataset_relative
    )


# ---------------------------------------------------------------------------
# Project Spec S0109: release-bound binary prediction execution smoke test.
#
# Builds a fully isolated temporary release (manifest.json,
# predictions/bundle.json, models/model.pkl, contracts/runtime-contract.json)
# containing a small, deterministic, real scikit-learn Pipeline serialized via
# joblib, and exercises it through the real joblib_sklearn_predict loader and
# the real execute_prediction() binary-classification flow end-to-end. Does
# not use the real active release, does not mutate registry state, does not
# execute any notebook, and never reads from pipeline/training-runs/**.
# ---------------------------------------------------------------------------

_S0109_FEATURE_ORDER = ["tenure", "monthly_charges"]


def _s0109_train_pipeline() -> Pipeline:
    X = pd.DataFrame(
        {
            "tenure": [1, 2, 3, 4, 60, 61, 62, 63, 64, 65],
            "monthly_charges": [95.0, 98.0, 90.0, 92.0, 20.0, 22.0, 18.0, 25.0, 19.0, 21.0],
        }
    )
    y = ["Yes", "Yes", "Yes", "Yes", "No", "No", "No", "No", "No", "No"]
    pipeline = Pipeline([("clf", LogisticRegression())])
    pipeline.fit(X, y)
    return pipeline


def _s0109_result_semantics(*, threshold: float = 0.5) -> dict[str, Any]:
    return {
        "schema_version": "binary-result-semantics.v1",
        "problem_type": "binary_classification",
        "result_schema_version": "binary-classification-result.v1",
        "primary_output": "positive_class_probability",
        "positive_class": {"class_id": "Yes", "event_label": "Churn"},
        "decision": {"threshold": threshold},
        "interpretation": {
            "preset": "risk",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
        "model_descriptor": {"model_family": "logistic_regression", "display_name": "Logistic Regression"},
    }


def _s0109_write_isolated_release(
    tmp_path: Path,
    *,
    pipeline: Pipeline,
    result_semantics: dict[str, Any] | None,
    class_labels: list[str] | None = None,
    serialization_format: str = "joblib",
    model_bytes_override: bytes | None = None,
    model_sha256_override: str | None = None,
) -> Path:
    release_root = tmp_path / "release-s0109-smoke"
    models_dir = release_root / "models"
    predictions_dir = release_root / "predictions"
    contracts_dir = release_root / "contracts"
    models_dir.mkdir(parents=True)
    predictions_dir.mkdir(parents=True)
    contracts_dir.mkdir(parents=True)

    model_path = models_dir / "model.pkl"
    if model_bytes_override is not None:
        model_path.write_bytes(model_bytes_override)
    else:
        joblib.dump(pipeline, model_path)
    model_sha256 = model_sha256_override or _sha256_bytes(model_path.read_bytes())

    _write_json(contracts_dir / "runtime-contract.json", {
        "schema_version": "1.0.0",
        "features": [{"name": name, "required": True} for name in _S0109_FEATURE_ORDER],
    })

    bundle: dict[str, Any] = {
        "contract_version": "inference_bundle.v1",
        "feature_order": list(_S0109_FEATURE_ORDER),
        "runtime_execution": {
            "loader_strategy": "joblib_sklearn_predict",
            "serialization_format": serialization_format,
            "prediction_interface": "predict",
            "model_family": "logistic_regression",
        },
        "model_artifact": {"path": "models/model.pkl", "sha256": model_sha256},
        "output_schema": {
            "class_labels": class_labels if class_labels is not None else ["No", "Yes"],
            "prediction_key": "prediction",
            "prediction_type": "string",
            "probability_output": True,
        },
    }
    if result_semantics is not None:
        bundle["result_semantics"] = result_semantics
    _write_json(predictions_dir / "bundle.json", bundle)

    _write_json(release_root / "manifest.json", {
        "schema_version": "release-manifest.v1",
        "artifacts": [
            {"role": "predictive_bundle", "reference": "predictions/bundle.json"},
        ],
    })

    return release_root


def _s0109_bundle_loader(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_S0109_LOADER_STRATEGIES = {"joblib_sklearn_predict": load_joblib_sklearn_model}


def test_s0109_real_joblib_loader_end_to_end_binary_prediction(tmp_path: Path) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path, pipeline=pipeline, result_semantics=_s0109_result_semantics()
    )

    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    # High-tenure, low-charges row: trained pattern predicts "No" (not churned).
    negative_result = execute_prediction(
        {"path": str(release_root), "artifacts": manifest["artifacts"]},
        {"tenure": 63, "monthly_charges": 19.0},
        manifest=manifest,
        bundle_loader=_s0109_bundle_loader,
        loader_strategies=_S0109_LOADER_STRATEGIES,
        supported_serialization_formats=["joblib"],
    )["result"]
    assert negative_result["schema_version"] == "binary-classification-result.v1"
    assert negative_result["predicted_class"]["class_id"] == "No"
    assert negative_result["decision"]["predicted_positive"] is False
    assert negative_result["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert 0.0 <= negative_result["positive_class_probability"] <= 1.0
    assert {p["class_id"] for p in negative_result["class_probabilities"]} == {"No", "Yes"}
    assert negative_result["interpretation"]["band_id"] in {"low", "medium", "high"}
    assert negative_result["model_descriptor"] == {
        "model_family": "logistic_regression",
        "display_name": "Logistic Regression",
    }

    # Low-tenure, high-charges row: trained pattern predicts "Yes" (churned).
    positive_result = execute_prediction(
        {"path": str(release_root), "artifacts": manifest["artifacts"]},
        {"tenure": 2, "monthly_charges": 96.0},
        manifest=manifest,
        bundle_loader=_s0109_bundle_loader,
        loader_strategies=_S0109_LOADER_STRATEGIES,
        supported_serialization_formats=["joblib"],
    )["result"]
    assert positive_result["predicted_class"]["class_id"] == "Yes"
    assert positive_result["decision"]["predicted_positive"] is True
    assert positive_result["interpretation"]["band_id"] == "high"

    # No legacy label/confidence contract anywhere in either result.
    for result in (negative_result, positive_result):
        assert "label" not in result
        assert "confidence" not in result


def test_s0109_reversed_positive_class_resolved_by_identity_not_position(tmp_path: Path) -> None:
    """positive_class.class_id == 'No', which is NOT at classes_ index 1 for
    this model (LogisticRegression sorts classes_ alphabetically: ['No','Yes']),
    proving positive-class lookup is identity-based, never index-based."""

    pipeline = _s0109_train_pipeline()
    assert list(pipeline.named_steps["clf"].classes_) == ["No", "Yes"]

    release_root = _s0109_write_isolated_release(
        tmp_path,
        pipeline=pipeline,
        result_semantics=_s0109_result_semantics(),
    )
    bundle_path = release_root / "predictions" / "bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["result_semantics"]["positive_class"] = {"class_id": "No", "event_label": "Retained"}
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    result = execute_prediction(
        {"path": str(release_root), "artifacts": manifest["artifacts"]},
        {"tenure": 63, "monthly_charges": 19.0},
        manifest=manifest,
        bundle_loader=_s0109_bundle_loader,
        loader_strategies=_S0109_LOADER_STRATEGIES,
        supported_serialization_formats=["joblib"],
    )["result"]

    assert result["positive_class"]["class_id"] == "No"
    # positive_class_probability must be the probability of "No", not classes_[1].
    no_probability = next(p["probability"] for p in result["class_probabilities"] if p["class_id"] == "No")
    assert result["positive_class_probability"] == no_probability


def test_s0109_missing_model_artifact_fails_safely(tmp_path: Path) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path, pipeline=pipeline, result_semantics=_s0109_result_semantics()
    )
    (release_root / "models" / "model.pkl").unlink()
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    with pytest.raises(BundleUnavailableError):
        execute_prediction(
            {"path": str(release_root), "artifacts": manifest["artifacts"]},
            {"tenure": 63, "monthly_charges": 19.0},
            manifest=manifest,
            bundle_loader=_s0109_bundle_loader,
            loader_strategies=_S0109_LOADER_STRATEGIES,
            supported_serialization_formats=["joblib"],
        )


def test_s0109_model_hash_mismatch_fails_safely(tmp_path: Path) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path,
        pipeline=pipeline,
        result_semantics=_s0109_result_semantics(),
        model_sha256_override="0" * 64,
    )
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    with pytest.raises(BundleValidationError) as exc_info:
        execute_prediction(
            {"path": str(release_root), "artifacts": manifest["artifacts"]},
            {"tenure": 63, "monthly_charges": 19.0},
            manifest=manifest,
            bundle_loader=_s0109_bundle_loader,
            loader_strategies=_S0109_LOADER_STRATEGIES,
            supported_serialization_formats=["joblib"],
        )
    assert exc_info.value.code == "model_artifact_hash_mismatch"


def test_s0109_unsupported_serialization_format_fails_safely(tmp_path: Path) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path,
        pipeline=pipeline,
        result_semantics=_s0109_result_semantics(),
        serialization_format="pickle",
    )
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    with pytest.raises(BundleValidationError) as exc_info:
        execute_prediction(
            {"path": str(release_root), "artifacts": manifest["artifacts"]},
            {"tenure": 63, "monthly_charges": 19.0},
            manifest=manifest,
            bundle_loader=_s0109_bundle_loader,
            loader_strategies=_S0109_LOADER_STRATEGIES,
            supported_serialization_formats=["joblib"],
        )
    assert exc_info.value.code == "unsupported_serialization_format"


def test_s0109_historical_bundle_without_result_semantics_fails_safely_no_fallback(
    tmp_path: Path,
) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(tmp_path, pipeline=pipeline, result_semantics=None)
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    with pytest.raises(BundleValidationError) as exc_info:
        execute_prediction(
            {"path": str(release_root), "artifacts": manifest["artifacts"]},
            {"tenure": 63, "monthly_charges": 19.0},
            manifest=manifest,
            bundle_loader=_s0109_bundle_loader,
            loader_strategies=_S0109_LOADER_STRATEGIES,
            supported_serialization_formats=["joblib"],
        )
    assert exc_info.value.code == "missing_result_semantics"


def test_s0109_threshold_equality_boundary_predicts_positive(tmp_path: Path) -> None:
    """probability >= threshold (not strictly >) must predict positive."""

    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path,
        pipeline=pipeline,
        result_semantics=_s0109_result_semantics(threshold=0.0),
    )
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    result = execute_prediction(
        {"path": str(release_root), "artifacts": manifest["artifacts"]},
        {"tenure": 63, "monthly_charges": 19.0},
        manifest=manifest,
        bundle_loader=_s0109_bundle_loader,
        loader_strategies=_S0109_LOADER_STRATEGIES,
        supported_serialization_formats=["joblib"],
    )["result"]
    # threshold 0.0: any probability >= 0.0 is positive.
    assert result["decision"]["predicted_positive"] is True
    assert result["predicted_class"]["class_id"] == "Yes"


def test_s0109_result_matches_binary_classification_result_schema(tmp_path: Path) -> None:
    pipeline = _s0109_train_pipeline()
    release_root = _s0109_write_isolated_release(
        tmp_path, pipeline=pipeline, result_semantics=_s0109_result_semantics()
    )
    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))

    result = execute_prediction(
        {"path": str(release_root), "artifacts": manifest["artifacts"]},
        {"tenure": 63, "monthly_charges": 19.0},
        manifest=manifest,
        bundle_loader=_s0109_bundle_loader,
        loader_strategies=_S0109_LOADER_STRATEGIES,
        supported_serialization_formats=["joblib"],
    )["result"]

    # Re-validating an already-returned result must succeed (defense-in-depth,
    # matches the API layer's own second validation pass).
    validate_binary_classification_result(result)
