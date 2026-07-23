import json
import sys
from pathlib import Path
from typing import Any, Mapping


sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime import (  # noqa: E402
    BundleReferenceError,
    BundleUnavailableError,
    load_inference_bundle,
    load_runtime_bundle_adapter,
)
from runtime.inference import (  # noqa: E402
    BundleValidationError,
    DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
    DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
    DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
    DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
    DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT,
    JOBLIB_SKLEARN_PREDICT_STRATEGY,
    _build_ordered_row,
    load_joblib_sklearn_model,
    validate_binary_classification_result,
)


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _bundle_declaration(model_path: str = "models/model.json") -> dict[str, Any]:
    return {
        "contract_version": "inference_bundle.v1",
        "model_artifact": {
            "path": model_path,
            "sha256": "adapter-test-placeholder",
        },
        "runtime_execution": {
            "loader_strategy": "json_threshold_classifier",
            "serialization_format": "json",
            "prediction_interface": "predict",
            "model_family": "logistic_regression",
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_features_object",
        },
        "feature_order": ["age"],
        "preprocessing": {
            "source": "execution_contract_and_training_parameter_record",
        },
        "output_schema": {
            "prediction_key": "prediction",
            "prediction_type": "boolean",
        },
    }


def test_runtime_bundle_adapter_uses_bundle_metadata_and_release_relative_model(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    declaration = _bundle_declaration()
    _write_json(release_root / "predictions" / "bundle.json", declaration)
    _write_json(release_root / "models" / "model.json", {"threshold": 40})

    loaded_model_paths: list[Path] = []

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def load_model(path: Path, _declaration: Mapping[str, Any]) -> Mapping[str, Any]:
        loaded_model_paths.append(path)
        return json.loads(path.read_text(encoding="utf-8"))

    adapter = load_runtime_bundle_adapter(
        {
            "release_root": str(release_root),
            "artifacts": {
                "inference_bundle": {
                    "path": "predictions/bundle.json",
                },
            },
        },
        bundle_loader=load_declaration,
        loader_strategies={"json_threshold_classifier": load_model},
        prediction_executor=lambda model, payload: payload["age"] >= model["threshold"],
        compatibility_status={"status": "compatible"},
    )

    assert loaded_model_paths == [release_root / "models" / "model.json"]
    assert adapter.metadata.runtime_execution["loader_strategy"] == "json_threshold_classifier"
    assert adapter.metadata.input_schema["payload_shape"] == "runtime_contract_features_object"
    assert adapter.metadata.feature_order == ("age",)
    assert adapter.metadata.output_schema["prediction_type"] == "boolean"
    assert adapter.predict({"age": 41}) is True


def test_runtime_bundle_adapter_rejects_unsupported_loader_strategy(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    declaration = _bundle_declaration()
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {
                    "inference_bundle": {
                        "path": "predictions/bundle.json",
                    },
                },
            },
            bundle_loader=load_declaration,
            loader_strategies={},
            compatibility_status={"status": "compatible"},
        )
    except BundleUnavailableError as exc:
        assert str(exc) == "Inference bundle loader strategy is unsupported."
    else:
        raise AssertionError("unsupported loader strategy was accepted")


def test_runtime_bundle_adapter_rejects_absolute_model_reference_without_leaking_path(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    declaration = _bundle_declaration(str(tmp_path / "outside-model.json"))
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {
                    "inference_bundle": {
                        "path": "predictions/bundle.json",
                    },
                },
            },
            bundle_loader=load_declaration,
            loader_strategies={"json_threshold_classifier": lambda path, declaration: None},
            compatibility_status={"status": "compatible"},
        )
    except BundleReferenceError as exc:
        message = str(exc)
        assert message == "Inference bundle reference must be release-relative."
        assert str(tmp_path) not in message
    else:
        raise AssertionError("absolute model reference was accepted")


def test_runtime_bundle_adapter_preserves_compatibility_prerequisite(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    _write_json(release_root / "predictions" / "bundle.json", _bundle_declaration())

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {
                    "inference_bundle": {
                        "path": "predictions/bundle.json",
                    },
                },
            },
            bundle_loader=load_declaration,
            loader_strategies={},
            compatibility_status={"status": "incompatible"},
        )
    except BundleReferenceError as exc:
        assert str(exc) == "Inference bundle has not passed compatibility validation."
    else:
        raise AssertionError("incompatible bundle status was accepted")


def test_runtime_bundle_adapter_executes_public_descriptor_bundle(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    descriptor = {
        "schema_version": "predictive-bundle.v1",
        "dataset_slug": "bank-marketing",
        "release_id": "release-20260620-002",
        "bundle_kind": "inference_descriptor",
        "problem_type": "binary_classification",
        "prediction_target": "subscribed",
        "output_type": "binary",
        "positive_class": True,
        "positive_class_meaning": "client subscribes to a term deposit",
        "threshold": 0.5,
        "runtime_contract_reference": "contracts/runtime-contract.json",
    }
    _write_json(release_root / "predictions" / "bundle.json", descriptor)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    adapter = load_runtime_bundle_adapter(
        {
            "release_root": str(release_root),
            "artifacts": {
                "predictive_bundle": {
                    "reference": "predictions/bundle.json",
                },
            },
        },
        bundle_loader=load_declaration,
    )

    prediction = adapter.predict({"age": 42})
    assert prediction == {
        "label": "client subscribes to a term deposit",
        "confidence": 0.5,
    }


# ---------------------------------------------------------------------------
# Project Spec S0109: joblib_sklearn_predict loader strategy allowlist.
# ---------------------------------------------------------------------------


def test_joblib_sklearn_predict_loader_accepts_joblib_serialization_format(tmp_path: Path) -> None:
    import joblib

    model_path = tmp_path / "model.pkl"
    joblib.dump({"marker": "a-real-joblib-object"}, model_path)

    loaded = load_joblib_sklearn_model(
        model_path,
        {"runtime_execution": {"serialization_format": "joblib"}},
    )
    assert loaded == {"marker": "a-real-joblib-object"}


def test_joblib_sklearn_predict_loader_rejects_unsupported_serialization_format(tmp_path: Path) -> None:
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"irrelevant")

    try:
        load_joblib_sklearn_model(
            model_path,
            {"runtime_execution": {"serialization_format": "pickle"}},
        )
    except BundleUnavailableError as exc:
        assert str(exc) == "Inference model serialization format is unsupported."
    else:
        raise AssertionError("unsupported serialization format was accepted")


def test_joblib_sklearn_predict_loader_maps_corrupt_file_to_sanitized_error(tmp_path: Path) -> None:
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"not-a-real-joblib-pickle-stream")

    try:
        load_joblib_sklearn_model(
            model_path,
            {"runtime_execution": {"serialization_format": "joblib"}},
        )
    except BundleUnavailableError as exc:
        message = str(exc)
        assert message == "Inference model artifact could not be loaded."
        assert str(tmp_path) not in message
        assert "Traceback" not in message
        # Project Spec S0151: a genuine deserialization failure (real joblib,
        # bad bytes) classifies through the typed boundary, never string
        # matching.
        assert exc.diagnostic_code == DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED
    else:
        raise AssertionError("corrupt joblib file was accepted")


# ---------------------------------------------------------------------------
# Project Spec S0151: the closed runtime diagnostic vocabulary. Every case
# below asserts the sanitized message is unchanged (or newly generic/safe)
# and that diagnostic_code is the correct allowlisted value -- proving
# classification happens at controlled typed boundaries, never by matching
# substrings of str(exc).
# ---------------------------------------------------------------------------


def test_load_joblib_sklearn_model_classifies_missing_dependency_without_naming_the_package(
    tmp_path: Path, monkeypatch
) -> None:
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"irrelevant")

    # Forces the loader's own `import joblib` to raise ImportError without
    # actually uninstalling joblib from this environment.
    monkeypatch.setitem(sys.modules, "joblib", None)

    try:
        load_joblib_sklearn_model(
            model_path,
            {"runtime_execution": {"serialization_format": "joblib"}},
        )
    except BundleUnavailableError as exc:
        message = str(exc)
        assert exc.diagnostic_code == DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE
        assert "joblib" not in message.lower()
        assert str(tmp_path) not in message
    else:
        raise AssertionError("missing joblib dependency was accepted")


def test_runtime_bundle_adapter_classifies_missing_model_artifact(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    declaration = {
        "feature_order": ["age"],
        "runtime_execution": {
            "loader_strategy": JOBLIB_SKLEARN_PREDICT_STRATEGY,
            "serialization_format": "joblib",
        },
        "model_artifact": {"path": "models/model.pkl"},
        "output_schema": {"class_labels": ["No", "Yes"]},
    }
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
            },
            bundle_loader=load_declaration,
            loader_strategies={JOBLIB_SKLEARN_PREDICT_STRATEGY: load_joblib_sklearn_model},
            supported_serialization_formats=["joblib"],
        )
    except BundleUnavailableError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE
    else:
        raise AssertionError("missing model artifact was accepted")


def test_runtime_bundle_adapter_classifies_model_artifact_hash_mismatch(tmp_path: Path) -> None:
    import joblib

    release_root = tmp_path / "release"
    (release_root / "models").mkdir(parents=True)
    joblib.dump({"marker": "real-model"}, release_root / "models" / "model.pkl")
    declaration = {
        "feature_order": ["age"],
        "runtime_execution": {
            "loader_strategy": JOBLIB_SKLEARN_PREDICT_STRATEGY,
            "serialization_format": "joblib",
        },
        "model_artifact": {"path": "models/model.pkl", "sha256": "0" * 64},
        "output_schema": {"class_labels": ["No", "Yes"]},
    }
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
            },
            bundle_loader=load_declaration,
            loader_strategies={JOBLIB_SKLEARN_PREDICT_STRATEGY: load_joblib_sklearn_model},
            supported_serialization_formats=["joblib"],
        )
    except BundleValidationError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH
        assert "0" * 64 not in str(exc)
    else:
        raise AssertionError("model artifact hash mismatch was accepted")


def test_load_inference_bundle_classifies_missing_bundle_as_inference_bundle_unavailable(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    release_root.mkdir()

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_inference_bundle(
            {
                "release_root": str(release_root),
                "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
            },
            bundle_loader=load_declaration,
        )
    except BundleUnavailableError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE
    else:
        raise AssertionError("missing bundle file was accepted")


def test_validate_binary_classification_result_classifies_schema_failure(tmp_path: Path) -> None:
    try:
        validate_binary_classification_result({"schema_version": "binary-classification-result.v1"})
    except BundleValidationError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_RESULT_VALIDATION_FAILED
    else:
        raise AssertionError("invalid binary classification result was accepted")


def test_unclassified_bundle_failure_carries_no_diagnostic_code(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    _write_json(release_root / "predictions" / "bundle.json", _bundle_declaration())

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
            },
            bundle_loader=load_declaration,
            loader_strategies={},
            compatibility_status={"status": "compatible"},
        )
    except BundleUnavailableError as exc:
        # Project Spec S0151: an unsupported loader strategy name is a
        # configuration/allowlist issue, not one of the seven closed runtime
        # diagnostic codes -- it must stay unclassified so the caller keeps
        # the fully generic INFERENCE_FAILURE response.
        assert exc.diagnostic_code is None
    else:
        raise AssertionError("unsupported loader strategy was accepted")


def test_runtime_bundle_adapter_loads_via_joblib_sklearn_predict_allowlist(tmp_path: Path) -> None:
    import joblib

    release_root = tmp_path / "release"
    (release_root / "models").mkdir(parents=True)
    joblib.dump({"marker": "real-model"}, release_root / "models" / "model.pkl")
    declaration = {
        "feature_order": ["age"],
        "runtime_execution": {
            "loader_strategy": JOBLIB_SKLEARN_PREDICT_STRATEGY,
            "serialization_format": "joblib",
        },
        "model_artifact": {"path": "models/model.pkl"},
        "output_schema": {"class_labels": ["No", "Yes"]},
    }
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    adapter = load_runtime_bundle_adapter(
        {
            "release_root": str(release_root),
            "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
        },
        bundle_loader=load_declaration,
        loader_strategies={JOBLIB_SKLEARN_PREDICT_STRATEGY: load_joblib_sklearn_model},
        supported_serialization_formats=["joblib"],
    )

    assert adapter.bundle == {"marker": "real-model"}
    assert adapter.model_artifact_path == release_root / "models" / "model.pkl"


def test_runtime_bundle_adapter_rejects_arbitrary_loader_strategy_name(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    declaration = {
        "feature_order": ["age"],
        "runtime_execution": {
            "loader_strategy": "arbitrary_dynamic_import_strategy",
            "serialization_format": "joblib",
        },
        "model_artifact": {"path": "models/model.pkl"},
        "output_schema": {"class_labels": ["No", "Yes"]},
    }
    _write_json(release_root / "predictions" / "bundle.json", declaration)

    def load_declaration(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        load_runtime_bundle_adapter(
            {
                "release_root": str(release_root),
                "artifacts": {"inference_bundle": {"path": "predictions/bundle.json"}},
            },
            bundle_loader=load_declaration,
            loader_strategies={JOBLIB_SKLEARN_PREDICT_STRATEGY: load_joblib_sklearn_model},
            supported_serialization_formats=["joblib"],
        )
    except BundleUnavailableError as exc:
        assert str(exc) == "Inference bundle loader strategy is unsupported."
    else:
        raise AssertionError("arbitrary loader strategy name was accepted")


# ---------------------------------------------------------------------------
# Project Spec S0152: white-box coverage of _build_ordered_row's optional-
# feature materialization and runtime input-contract-inconsistency
# classification. _build_ordered_row is private, but the row-construction
# decision (present / contractually-optional-omitted / inconsistent) has no
# other seam to exercise directly -- the public execute_prediction() path is
# covered end-to-end separately in tests/test_local_inference_smoke.py (real
# scikit-learn pipeline) and tests/api/test_admin_live_preview_inference.py
# (real HTTP route).
# ---------------------------------------------------------------------------


def test_build_ordered_row_preserves_provided_values_unchanged() -> None:
    row = _build_ordered_row(["a", "b"], {"a": 1, "b": 2})
    assert list(row.columns) == ["a", "b"]
    assert row.iloc[0]["a"] == 1
    assert row.iloc[0]["b"] == 2


def test_build_ordered_row_materializes_missing_sentinel_for_declared_optional_feature() -> None:
    row = _build_ordered_row(
        ["a", "b"],
        {"a": 1},
        {"a": {"required": True}, "b": {"required": False}},
    )
    assert list(row.columns) == ["a", "b"]
    assert row.iloc[0]["a"] == 1
    import math

    assert math.isnan(row.iloc[0]["b"])


def test_build_ordered_row_materializes_multiple_optional_omissions_deterministically() -> None:
    metadata = {
        "a": {"required": True},
        "b": {"required": False},
        "c": {"required": False},
    }
    first = _build_ordered_row(["a", "b", "c"], {"a": 5}, metadata)
    second = _build_ordered_row(["a", "b", "c"], {"a": 5}, metadata)

    import math

    for row in (first, second):
        assert list(row.columns) == ["a", "b", "c"]
        assert row.iloc[0]["a"] == 5
        assert math.isnan(row.iloc[0]["b"])
        assert math.isnan(row.iloc[0]["c"])


def test_build_ordered_row_preserves_column_order_and_other_field_values() -> None:
    row = _build_ordered_row(
        ["x", "y", "z"],
        {"x": 10, "z": 30},
        {"x": {"required": True}, "y": {"required": False}, "z": {"required": True}},
    )
    assert list(row.columns) == ["x", "y", "z"]
    assert row.iloc[0]["x"] == 10
    assert row.iloc[0]["z"] == 30
    import math

    assert math.isnan(row.iloc[0]["y"])


def test_build_ordered_row_classifies_required_feature_missing_after_validation_as_runtime_inconsistency() -> None:
    try:
        _build_ordered_row(
            ["a", "b"],
            {"a": 1},
            {"a": {"required": True}, "b": {"required": True}},
        )
    except BundleValidationError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT
        assert exc.code == "runtime_input_contract_inconsistent"
    else:
        raise AssertionError("required feature missing after validation was accepted")


def test_build_ordered_row_classifies_bundle_feature_absent_from_runtime_contract_as_runtime_inconsistency() -> None:
    try:
        _build_ordered_row(
            ["a", "b"],
            {"a": 1},
            {"a": {"required": True}},
        )
    except BundleValidationError as exc:
        assert exc.diagnostic_code == DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT
        assert exc.code == "runtime_input_contract_inconsistent"
    else:
        raise AssertionError("bundle feature absent from runtime contract was accepted")


def test_build_ordered_row_without_metadata_preserves_legacy_missing_feature_value_error() -> None:
    """Backward compatibility: a caller that supplies no runtime_feature_metadata
    at all (runtime_feature_metadata=None, the default) has given no way to
    know a name is contractually optional, so the original strict behavior
    is preserved rather than silently materializing."""
    try:
        _build_ordered_row(["a", "b"], {"a": 1})
    except BundleValidationError as exc:
        assert exc.code == "missing_feature_value"
        assert exc.diagnostic_code is None
    else:
        raise AssertionError("missing feature value without metadata was accepted")


def test_build_ordered_row_diagnostic_code_is_a_member_of_runtime_diagnostic_codes() -> None:
    from runtime.inference import RUNTIME_DIAGNOSTIC_CODES

    assert DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT in RUNTIME_DIAGNOSTIC_CODES
