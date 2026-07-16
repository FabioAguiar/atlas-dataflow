import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training_module  # noqa: E402
from pipeline.generate_inference_bundle import (  # noqa: E402
    BundleGenerationError,
    _build_bundle,
    _build_parser,
    materialize_governed_inference_bundle,
)
from runtime.inference import (  # noqa: E402
    BundleReferenceError,
    BundleUnavailableError,
    BundleValidationError,
    load_runtime_bundle_adapter,
)


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_declaration(
    *,
    model_path: str = "models/model.json",
    model_sha256: str | None = None,
    loader_strategy: str = "json_threshold_classifier",
    serialization_format: str = "json",
    feature_order: list[str] | None = None,
    runtime_contract_version: str = "runtime-contract.v1",
    include_training_evidence: bool = True,
) -> dict[str, Any]:
    if model_sha256 is None:
        model_sha256 = _sha256(b'{"threshold": 40}')
    bundle: dict[str, Any] = {
        "contract_version": "inference_bundle.v1",
        "bundle_identity": {
            "bundle_id": "invalid-bundle-test-inference-bundle-20260626T000000Z",
            "artifact_kind": "inference_bundle",
            "created_at": "2026-06-26T00:00:00Z",
        },
        "release_context": {
            "release_id": "release-20260626-001",
            "release_package_reference": "predictions/bundle.json",
        },
        "contract_references": {
            "execution_contract": {
                "path": "contracts/execution-contract.json",
                "sha256": "1" * 64,
                "contract_version": "execution_contract.v1",
            },
            "runtime_contract": {
                "path": "contracts/runtime-contract.json",
                "sha256": "2" * 64,
                "contract_version": runtime_contract_version,
            },
            "public_contract": {
                "path": "contracts/public-contract.json",
                "sha256": "3" * 64,
                "contract_version": "public-contract.v1",
            },
        },
        "model_artifact": {
            "path": model_path,
            "sha256": model_sha256,
            "source_training_parameter_record_path": "training/training-parameter-record.json",
        },
        "runtime_execution": {
            "loader_strategy": loader_strategy,
            "serialization_format": serialization_format,
            "prediction_interface": "predict",
            "model_family": "logistic_regression",
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_features_object",
        },
        "feature_order": feature_order or ["age"],
        "preprocessing": {
            "source": "execution_contract_and_training_parameter_record",
        },
        "output_schema": {
            "prediction_key": "prediction",
            "prediction_type": "boolean",
        },
        "compatibility_constraints": {
            "requires_contract_versions": {
                "execution_contract": "execution_contract.v1",
                "runtime_contract": "runtime-contract.v1",
                "public_contract": "public-contract.v1",
            },
            "requires_hash_match": True,
            "requires_feature_order_match": True,
            "requires_supported_loader": True,
            "requires_supported_serialization": True,
        },
    }
    if include_training_evidence:
        bundle["training_evidence"] = {
            "training_parameter_record": {
                "path": "training/training-parameter-record.json",
                "sha256": "4" * 64,
                "contract_version": "training-parameter-record.v1",
            },
            "training_metrics": {
                "path": "training/metrics.json",
                "sha256": "5" * 64,
                "contract_version": "training-metrics.v1",
            },
        }
    return bundle


def _write_release(tmp_path: Path, declaration: Mapping[str, Any]) -> Path:
    release_root = tmp_path / "release"
    _write_json(release_root / "predictions" / "bundle.json", declaration)
    _write_json(release_root / "models" / "model.json", {"threshold": 40})
    return release_root


def _load_declaration(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_model(path: Path, _declaration: Mapping[str, Any]) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_adapter(
    release_root: Path,
    *,
    compatibility_status: Mapping[str, Any] | None = None,
):
    return load_runtime_bundle_adapter(
        {
            "release_root": str(release_root),
            "artifacts": {
                "inference_bundle": {
                    "path": "predictions/bundle.json",
                },
            },
        },
        bundle_loader=_load_declaration,
        loader_strategies={"json_threshold_classifier": _load_model},
        supported_serialization_formats=["json"],
        compatibility_status=compatibility_status or {"status": "compatible"},
    )


def _assert_sanitized(exc: Exception, tmp_path: Path) -> None:
    message = str(exc)
    assert str(tmp_path) not in message
    assert "Traceback" not in message
    assert "No such file" not in message


def test_missing_model_file_rejected_with_sanitized_runtime_error(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    _write_json(release_root / "predictions" / "bundle.json", _bundle_declaration())

    try:
        _load_adapter(release_root)
    except BundleUnavailableError as exc:
        assert str(exc) == "Inference model artifact is unavailable."
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("missing model artifact was accepted")


def test_wrong_model_hash_rejected_with_stable_category(tmp_path: Path) -> None:
    declaration = _bundle_declaration(model_sha256="0" * 64)
    release_root = _write_release(tmp_path, declaration)

    try:
        _load_adapter(release_root)
    except BundleValidationError as exc:
        assert exc.code == "model_artifact_hash_mismatch"
        assert exc.field == "model_artifact.sha256"
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("model artifact hash mismatch was accepted")


def test_unsupported_loader_strategy_rejected_with_stable_category(tmp_path: Path) -> None:
    release_root = _write_release(
        tmp_path,
        _bundle_declaration(loader_strategy="not_supported"),
    )

    try:
        _load_adapter(release_root)
    except BundleUnavailableError as exc:
        assert str(exc) == "Inference bundle loader strategy is unsupported."
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("unsupported loader strategy was accepted")


def test_unsupported_serialization_format_rejected_with_stable_category(tmp_path: Path) -> None:
    release_root = _write_release(
        tmp_path,
        _bundle_declaration(serialization_format="pickle_callback"),
    )

    try:
        _load_adapter(release_root)
    except BundleValidationError as exc:
        assert exc.code == "unsupported_serialization_format"
        assert exc.field == "runtime_execution.serialization_format"
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("unsupported serialization format was accepted")


def test_feature_order_incompatibility_rejected_with_stable_category(tmp_path: Path) -> None:
    release_root = _write_release(tmp_path, _bundle_declaration(feature_order=["segment", "age"]))

    try:
        _load_adapter(
            release_root,
            compatibility_status={
                "status": "compatible",
                "checks": {"feature_order_compatible": False},
            },
        )
    except BundleValidationError as exc:
        assert exc.code == "feature_contract_mismatch"
        assert exc.field == "compatibility_status.checks.feature_order_compatible"
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("feature order incompatibility was accepted")


def test_stale_contract_reference_rejected_with_stable_category(tmp_path: Path) -> None:
    release_root = _write_release(
        tmp_path,
        _bundle_declaration(runtime_contract_version="runtime-contract.v0"),
    )

    try:
        _load_adapter(release_root)
    except BundleValidationError as exc:
        assert exc.code == "stale_contract_reference"
        assert exc.field == "contract_references.runtime_contract.contract_version"
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("stale contract reference was accepted")


def test_missing_training_evidence_reference_rejected_with_stable_category(tmp_path: Path) -> None:
    release_root = _write_release(
        tmp_path,
        _bundle_declaration(include_training_evidence=False),
    )

    try:
        _load_adapter(release_root)
    except BundleValidationError as exc:
        assert exc.code == "missing_training_evidence_reference"
        assert exc.field == "training_evidence"
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("missing training evidence reference was accepted")


def test_absolute_model_reference_rejected_without_internal_path_exposure(tmp_path: Path) -> None:
    release_root = _write_release(
        tmp_path,
        _bundle_declaration(model_path=str(tmp_path / "outside-model.json")),
    )

    try:
        _load_adapter(release_root)
    except BundleReferenceError as exc:
        assert str(exc) == "Inference bundle reference must be release-relative."
        _assert_sanitized(exc, tmp_path)
    else:
        raise AssertionError("absolute model reference was accepted")


# ---------------------------------------------------------------------------
# Project Spec S0109: binary-classification execution edge cases. These use a
# fake in-memory model double (not a real sklearn Pipeline -- that path is
# already covered end-to-end in tests/test_local_inference_smoke.py) via
# loader_strategies, to exercise malformed predict()/predict_proba() shapes,
# class-identity mismatches, and probability validation deterministically.
# ---------------------------------------------------------------------------

import runtime.inference as _runtime_inference_module  # noqa: E402
from runtime.inference import BundleExecutionError, execute_prediction  # noqa: E402


class _FakeBinaryModel:
    def __init__(self, classes, predict_return, predict_proba_return):
        self.classes_ = classes
        self._predict_return = predict_return
        self._predict_proba_return = predict_proba_return

    def predict(self, _row):
        return self._predict_return

    def predict_proba(self, _row):
        return self._predict_proba_return


def _s0109_binary_declaration(
    *,
    positive_class_id: str = "Yes",
    class_labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "feature_order": ["age"],
        "runtime_execution": {
            "loader_strategy": "fake_binary_model",
            "serialization_format": "fake",
        },
        "model_artifact": {"path": "models/model.json"},
        "output_schema": {"class_labels": class_labels if class_labels is not None else ["No", "Yes"]},
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1",
            "primary_output": "positive_class_probability",
            "positive_class": {"class_id": positive_class_id, "event_label": "Churn"},
            "decision": {"threshold": 0.5},
            "interpretation": {
                "preset": "risk",
                "bands": [
                    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
                ],
            },
            "model_descriptor": {"model_family": "logistic_regression", "display_name": "Logistic Regression"},
        },
    }


def _s0109_execute(tmp_path: Path, declaration: dict[str, Any], model: _FakeBinaryModel):
    release_root = tmp_path / "release-s0109-edge"
    _write_json(release_root / "predictions" / "bundle.json", declaration)
    _write_json(release_root / "models" / "model.json", {"placeholder": True})

    def _load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_fake_model(_path: Path, _declaration: Mapping[str, Any]):
        return model

    return execute_prediction(
        {"path": str(release_root)},
        {"age": 42},
        manifest={"artifacts": [{"role": "predictive_bundle", "reference": "predictions/bundle.json"}]},
        bundle_loader=_load_declaration,
        loader_strategies={"fake_binary_model": _load_fake_model},
        supported_serialization_formats=["fake"],
    )


def test_s0109_malformed_predict_output_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["Yes", "No"], predict_proba_return=[[0.4, 0.6]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_malformed_predict_proba_output_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["Yes"], predict_proba_return=[[0.2, 0.3, 0.5]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_positive_class_not_found_in_model_classes_rejected(tmp_path: Path) -> None:
    # Model classes and bundle class_labels agree with each other as a set
    # (["No", "Yes"]), but the approved positive_class.class_id names neither.
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[0.6, 0.4]])
    with pytest.raises(BundleValidationError) as exc_info:
        _s0109_execute(tmp_path, _s0109_binary_declaration(positive_class_id="Maybe"), model)
    assert exc_info.value.code == "positive_class_not_found"


def test_s0109_model_class_bundle_class_mismatch_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[0.6, 0.4]])
    with pytest.raises(BundleValidationError) as exc_info:
        _s0109_execute(tmp_path, _s0109_binary_declaration(class_labels=["Alpha", "Beta"]), model)
    assert exc_info.value.code == "model_class_bundle_class_mismatch"


def test_s0109_reversed_model_class_order_still_resolves_by_identity(tmp_path: Path) -> None:
    """classes_ == ['Yes', 'No'] -- positive class 'Yes' is at index 0, not the
    commonly-assumed index 1 -- must still resolve correctly by identity."""

    model = _FakeBinaryModel(["Yes", "No"], predict_return=["Yes"], predict_proba_return=[[0.9, 0.1]])
    result = _s0109_execute(tmp_path, _s0109_binary_declaration(positive_class_id="Yes"), model)["result"]
    assert result["positive_class_probability"] == 0.9
    assert result["predicted_class"]["class_id"] == "Yes"


def test_s0109_nan_probability_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[float("nan"), 0.5]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_infinite_probability_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[float("inf"), 0.5]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_out_of_range_probability_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[1.5, -0.5]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_probability_sum_mismatch_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[0.5, 0.6]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_predicted_raw_class_outside_governed_set_rejected(tmp_path: Path) -> None:
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["Unknown"], predict_proba_return=[[0.4, 0.6]])
    with pytest.raises(BundleExecutionError):
        _s0109_execute(tmp_path, _s0109_binary_declaration(), model)


def test_s0109_band_boundaries_every_edge(tmp_path: Path) -> None:
    bands = _runtime_inference_module._validate_bands(
        [
            {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
            {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
            {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
        ]
    )
    assert _runtime_inference_module._resolve_band(0.0, bands) == "low"
    assert _runtime_inference_module._resolve_band(0.349999, bands) == "low"
    assert _runtime_inference_module._resolve_band(0.35, bands) == "medium"
    assert _runtime_inference_module._resolve_band(0.649999, bands) == "medium"
    assert _runtime_inference_module._resolve_band(0.65, bands) == "high"
    assert _runtime_inference_module._resolve_band(0.999999, bands) == "high"
    assert _runtime_inference_module._resolve_band(1.0, bands) == "high"


def test_s0109_band_resolution_zero_matches_fails_safely() -> None:
    gapped_bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.3},
        {"band_id": "medium", "lower_bound": 0.4, "upper_bound": 0.6},
        {"band_id": "high", "lower_bound": 0.6, "upper_bound": 1.0},
    ]
    with pytest.raises(BundleValidationError) as exc_info:
        _runtime_inference_module._resolve_band(0.35, gapped_bands)
    assert exc_info.value.code == "invalid_band_resolution"


def test_s0109_band_resolution_multiple_matches_fails_safely() -> None:
    overlapping_bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.5},
        {"band_id": "medium", "lower_bound": 0.3, "upper_bound": 0.7},
        {"band_id": "high", "lower_bound": 0.7, "upper_bound": 1.0},
    ]
    with pytest.raises(BundleValidationError) as exc_info:
        _runtime_inference_module._resolve_band(0.4, overlapping_bands)
    assert exc_info.value.code == "invalid_band_resolution"


def test_s0109_invalid_threshold_rejected(tmp_path: Path) -> None:
    declaration = _s0109_binary_declaration()
    declaration["result_semantics"]["decision"]["threshold"] = 1.5
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[0.6, 0.4]])
    with pytest.raises(BundleValidationError) as exc_info:
        _s0109_execute(tmp_path, declaration, model)
    assert exc_info.value.code == "invalid_decision_threshold"


def test_s0109_missing_positive_class_block_rejected(tmp_path: Path) -> None:
    declaration = _s0109_binary_declaration()
    del declaration["result_semantics"]["positive_class"]
    model = _FakeBinaryModel(["No", "Yes"], predict_return=["No"], predict_proba_return=[[0.6, 0.4]])
    with pytest.raises(BundleValidationError) as exc_info:
        _s0109_execute(tmp_path, declaration, model)
    assert exc_info.value.code == "missing_positive_class"


# Generation-time invalid-input errors from pipeline.generate_inference_bundle,
# distinct from the runtime load-time errors above. These synthetic Telco-shaped
# governed fixtures cover the negative paths required before real Telco bundle
# generation can proceed: missing upstream inputs, invalid path references,
# stale/inconsistent hashes, and unsupported loader/serialization declarations.

_TELCO_FEATURE_COLUMNS = ["gender", "SeniorCitizen", "tenure", "MonthlyCharges"]


def _generation_execution_contract(*, contract_version: str = "execution_contract.v1") -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "dataset_id": "telco-customer-churn",
        "target_column": "Churn",
        "feature_columns": list(_TELCO_FEATURE_COLUMNS),
        "ignored_columns": ["customerID", "TotalCharges"],
        "required_columns": list(_TELCO_FEATURE_COLUMNS),
        "optional_columns": [],
        "feature_definitions": {
            "gender": {"type": "categorical"},
            "SeniorCitizen": {"type": "boolean"},
            "tenure": {"type": "numeric", "domain_constraints": {"min": 0, "max": 72}},
            "MonthlyCharges": {
                "type": "numeric",
                "domain_constraints": {"min": 18.25, "max": 118.75},
            },
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
    }


def _generation_training_record(
    *,
    execution_contract_sha256: str,
    prepared_dataset_sha256: str,
    model_artifact_sha256: str,
    metrics_sha256: str,
    model_family: str = "logistic_regression",
    serializer_name: str = "joblib",
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
            "feature_columns": list(_TELCO_FEATURE_COLUMNS),
        },
        "hashes": {
            "execution_contract_sha256": execution_contract_sha256,
            "prepared_dataset_sha256": prepared_dataset_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
    }


def _generation_argv(
    tmp_path: Path,
    *,
    execution_contract_version: str = "execution_contract.v1",
    execution_contract_ref: str = "contracts/telco-customer-churn/execution-contract.json",
    release_package_reference: str = "predictions/bundle.json",
    model_family: str = "logistic_regression",
    serializer_name: str = "joblib",
    write_model_artifact: bool = True,
    corrupt_execution_contract_hash: bool = False,
) -> list[str]:
    execution_contract_path = tmp_path / "execution-contract.json"
    _write_json(
        execution_contract_path,
        _generation_execution_contract(contract_version=execution_contract_version),
    )
    runtime_contract_path = tmp_path / "runtime-contract.json"
    _write_json(runtime_contract_path, {"schema_version": "1.0.0"})
    public_contract_path = tmp_path / "public-contract.json"
    _write_json(public_contract_path, {"schema_version": "1.0.0"})
    prepared_dataset_path = tmp_path / "prepared-data-metadata.json"
    _write_json(prepared_dataset_path, {"schema_version": "prepared-data-metadata.v1"})
    model_artifact_path = tmp_path / "model.pkl"
    if write_model_artifact:
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        model_artifact_path.write_bytes(b"synthetic-joblib-model-bytes")
    metrics_path = tmp_path / "metrics.json"
    _write_json(metrics_path, {"schema_version": "training-metrics.v1"})

    execution_contract_sha256 = hashlib.sha256(execution_contract_path.read_bytes()).hexdigest()
    if corrupt_execution_contract_hash:
        execution_contract_sha256 = "0" * 64
    model_artifact_sha256 = (
        hashlib.sha256(model_artifact_path.read_bytes()).hexdigest()
        if write_model_artifact
        else "1" * 64
    )

    training_record = _generation_training_record(
        execution_contract_sha256=execution_contract_sha256,
        prepared_dataset_sha256=hashlib.sha256(prepared_dataset_path.read_bytes()).hexdigest(),
        model_artifact_sha256=model_artifact_sha256,
        metrics_sha256=hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
        model_family=model_family,
        serializer_name=serializer_name,
    )
    training_record_path = tmp_path / "training-parameter-record.json"
    _write_json(training_record_path, training_record)

    return [
        "--execution-contract", str(execution_contract_path),
        "--runtime-contract", str(runtime_contract_path),
        "--public-contract", str(public_contract_path),
        "--prepared-dataset", str(prepared_dataset_path),
        "--training-parameter-record", str(training_record_path),
        "--training-metrics", str(metrics_path),
        "--model-artifact", str(model_artifact_path),
        "--output", str(tmp_path / "inference-bundle.json"),
        "--release-package-reference", release_package_reference,
        "--prediction-type", "boolean",
        "--release-id", "release-20260709-001",
        "--dataset-slug", "telco-customer-churn",
        "--execution-contract-ref", execution_contract_ref,
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


def _build_from_argv(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    argv = _generation_argv(tmp_path, **overrides)
    args = _build_parser().parse_args(argv)
    return _build_bundle(args)


def test_generation_rejects_missing_upstream_model_artifact(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, write_model_artifact=False)
    assert exc_info.value.code == "missing_required_artifact"


def test_generation_rejects_absolute_path_reference(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path,
            execution_contract_ref=str(tmp_path / "outside-execution-contract.json"),
        )
    assert exc_info.value.code == "invalid_release_reference"


def test_generation_rejects_parent_traversal_reference(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path,
            release_package_reference="../escape/bundle.json",
        )
    assert exc_info.value.code == "invalid_release_reference"


def test_generation_rejects_stale_execution_contract_hash(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, corrupt_execution_contract_hash=True)
    assert exc_info.value.code == "stale_or_inconsistent_artifact"
    assert exc_info.value.field == "hashes.execution_contract_sha256"


def test_generation_rejects_unsupported_model_family(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, model_family="xgboost")
    assert exc_info.value.code == "unsupported_model_family"


def test_generation_rejects_unsupported_serializer(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, serializer_name="pickle")
    assert exc_info.value.code == "unsupported_serializer"


def test_generation_rejects_draft_only_execution_contract(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, execution_contract_version="execution_contract.draft")
    assert exc_info.value.code == "invalid_contract_version"


# Project Spec S0033: rejection paths for the governed inference-bundle
# materialization boundary (`materialize_governed_inference_bundle`), which
# never generates a bundle from a hardcoded train-pending placeholder or an
# ungoverned prepared-dataset reference.


def _minimal_governed_bundle_kwargs(tmp_path: Path, repo_root: Path) -> dict[str, Any]:
    execution_contract_path = repo_root / "contracts/telco-customer-churn/execution-contract.json"
    _write_json(execution_contract_path, _generation_execution_contract())
    runtime_contract_path = repo_root / "contracts/telco-customer-churn/runtime-contract.json"
    _write_json(runtime_contract_path, {"schema_version": "1.0.0"})
    public_contract_path = repo_root / "contracts/telco-customer-churn/public-contract.json"
    _write_json(public_contract_path, {"schema_version": "1.0.0"})
    dataset_context_path = repo_root / "contracts/telco-customer-churn/dataset-context.json"
    _write_json(dataset_context_path, {"schema_version": "dataset-context.v1"})
    return {
        "execution_contract_path": execution_contract_path,
        "runtime_contract_path": runtime_contract_path,
        "public_contract_path": public_contract_path,
        "dataset_context_path": dataset_context_path,
        "output_path": repo_root / "contracts/telco-customer-churn/inference-bundle.json",
        "prediction_type": "boolean",
        "repo_root": repo_root,
        "execution_contract_ref": "contracts/telco-customer-churn/execution-contract.json",
        "runtime_contract_ref": "contracts/telco-customer-churn/runtime-contract.json",
        "public_contract_ref": "contracts/telco-customer-churn/public-contract.json",
        "dataset_context_ref": "contracts/telco-customer-churn/dataset-context.json",
    }


def test_governed_inference_bundle_blocked_when_training_run_not_trained(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training_module, "_repo_root", lambda: repo_root)

    prepared_metadata_path = repo_root / "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json"
    _write_json(
        prepared_metadata_path,
        {
            "schema_version": "prepared-data-metadata.v1",
            "dataset_identity": {"dataset_slug": "telco-customer-churn"},
            "prepared_candidate": {"produced": False, "reason_not_produced": "pending review"},
            "training_readiness": {"is_training_ready": False},
        },
    )

    # This is the pre-training blocked-state result the notebook's own
    # `materialize_training_run_from_prepared_metadata` call reports before a
    # governed training run exists -- never a `train-pending` path glob.
    training_run_materialization_result = {
        "status": "blocked",
        "blocking_reasons": ["execution_contract_path does not reference an execution-ready contract."],
    }

    result = materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        prepared_data_metadata_path=prepared_metadata_path,
        **_minimal_governed_bundle_kwargs(tmp_path, repo_root),
    )

    assert result["status"] == "blocked"
    assert any("status is not 'trained'" in reason for reason in result["blocking_reasons"])
    assert not (repo_root / "contracts/telco-customer-churn/inference-bundle.json").exists()


def test_governed_inference_bundle_blocked_when_prepared_candidate_not_produced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training_module, "_repo_root", lambda: repo_root)

    prepared_metadata_path = repo_root / "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json"
    _write_json(
        prepared_metadata_path,
        {
            "schema_version": "prepared-data-metadata.v1",
            "dataset_identity": {"dataset_slug": "telco-customer-churn"},
            "prepared_candidate": {
                "produced": False,
                "reason_not_produced": "unresolved TotalCharges review",
            },
            "training_readiness": {"is_training_ready": False},
        },
    )

    training_run_relative_dir = "pipeline/training-runs/telco-customer-churn/train-20260709T120000Z"
    training_run_materialization_result = {
        "status": "trained",
        "training_result": {
            "output_directory": f"{training_run_relative_dir}/",
            "serialized_model_path": f"{training_run_relative_dir}/model.pkl",
            "training_parameter_record_path": (
                f"{training_run_relative_dir}/training-parameter-record.json"
            ),
            "metrics_path": f"{training_run_relative_dir}/metrics.json",
            "model_selection_evidence_path": None,
        },
    }

    result = materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        prepared_data_metadata_path=prepared_metadata_path,
        **_minimal_governed_bundle_kwargs(tmp_path, repo_root),
    )

    assert result["status"] == "blocked"
    assert any("prepared_candidate.produced" in reason for reason in result["blocking_reasons"])
    assert not (repo_root / "contracts/telco-customer-churn/inference-bundle.json").exists()
