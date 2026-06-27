"""Release-bound inference bundle loading and prediction execution.

This module deliberately accepts active release metadata and a bundle loader
from the caller. Dataset resolution, runtime contract loading, payload
validation, API response serialization, and public error mapping live outside
this runtime boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


BundleLoader = Callable[[Path], Any]
PredictionExecutor = Callable[[Any, Mapping[str, Any]], Any]
LoaderStrategy = Callable[[Path, Mapping[str, Any]], Any]

_BUNDLE_ROLES = frozenset(
    {
        "inference_bundle",
        "predictive_bundle",
        "prediction_bundle",
        "model_bundle",
    }
)
_REFERENCE_KEYS = ("path", "relative_path", "href", "uri", "ref", "reference")
_RELEASE_ROOT_KEYS = (
    "release_path",
    "release_root",
    "package_path",
    "package_root",
    "path",
    "root",
)


class InferenceRuntimeError(Exception):
    """Base exception for sanitized inference runtime failures."""


class BundleReferenceError(InferenceRuntimeError):
    """Raised when active release metadata cannot identify a safe bundle."""


class BundleUnavailableError(InferenceRuntimeError):
    """Raised when the release-bound bundle cannot be loaded."""


class BundleExecutionError(InferenceRuntimeError):
    """Raised when prediction execution fails."""


class BundleValidationError(InferenceRuntimeError):
    """Raised when bundle metadata is invalid before runtime loading."""

    def __init__(self, code: str, message: str, *, field: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True)
class LoadedInferenceBundle:
    """Loaded bundle with the resolved release-local source retained internally."""

    source_path: Path
    bundle: Any


@dataclass(frozen=True)
class RuntimeBundleMetadata:
    """Release-bound bundle metadata exposed to the runtime layer."""

    runtime_execution: Mapping[str, Any]
    input_schema: Mapping[str, Any]
    feature_order: Sequence[str]
    preprocessing: Mapping[str, Any]
    output_schema: Mapping[str, Any]


@dataclass(frozen=True)
class RuntimeBundleAdapter:
    """Stable runtime adapter for an already validated inference bundle."""

    source_path: Path
    model_artifact_path: Path | None
    declaration: Mapping[str, Any]
    metadata: RuntimeBundleMetadata
    bundle: Any
    prediction_callable: Callable[[Mapping[str, Any]], Any]

    def predict(self, validated_payload: Mapping[str, Any]) -> Any:
        return self.prediction_callable(validated_payload)


def load_inference_bundle(
    active_release: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
    bundle_loader: BundleLoader,
) -> LoadedInferenceBundle:
    """Load an inference bundle from the active release package.

    The bundle reference must be relative to the active release package. Absolute
    references, parent traversal, missing files, and implicit fallback paths are
    rejected before the caller-provided loader is invoked.
    """

    release_root = _release_root(active_release)
    bundle_reference = _bundle_reference(manifest or active_release)
    bundle_path = _resolve_release_relative_path(release_root, bundle_reference)

    if not bundle_path.is_file():
        raise BundleUnavailableError("Inference bundle is unavailable.")

    try:
        bundle = bundle_loader(bundle_path)
    except InferenceRuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleUnavailableError("Inference bundle could not be loaded.") from exc

    return LoadedInferenceBundle(source_path=bundle_path, bundle=bundle)


def load_runtime_bundle_adapter(
    active_release: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
    bundle_loader: BundleLoader,
    loader_strategies: Mapping[str, LoaderStrategy] | None = None,
    supported_serialization_formats: Sequence[str] | None = None,
    prediction_executor: PredictionExecutor | None = None,
    compatibility_status: Mapping[str, Any] | None = None,
) -> RuntimeBundleAdapter:
    """Load a validated release bundle through the stable runtime adapter.

    This adapter consumes bundle-declared runtime metadata without replacing the
    M25-03 compatibility validator. Callers may pass compatibility status from
    that validator; this boundary only verifies that the status is compatible
    before loading. Loader strategy selection is driven by bundle metadata.
    """

    _require_compatible_status(compatibility_status)
    release_root = _release_root(active_release)
    loaded = load_inference_bundle(
        active_release,
        manifest=manifest,
        bundle_loader=bundle_loader,
    )
    declaration = _bundle_declaration(loaded.bundle, manifest)
    metadata = _runtime_metadata(declaration)
    _validate_bundle_declaration(
        declaration,
        compatibility_status=compatibility_status,
        supported_serialization_formats=supported_serialization_formats,
    )
    bundle = loaded.bundle
    model_artifact_path: Path | None = None

    if loader_strategies is not None:
        strategy = metadata.runtime_execution.get("loader_strategy")
        if not isinstance(strategy, str) or strategy not in loader_strategies:
            raise BundleUnavailableError("Inference bundle loader strategy is unsupported.")
        model_reference = _model_artifact_reference(declaration)
        if model_reference is None:
            raise BundleReferenceError("Inference model artifact reference is not defined.")
        model_artifact_path = _resolve_release_relative_path(release_root, model_reference)
        if not model_artifact_path.is_file():
            raise BundleUnavailableError("Inference model artifact is unavailable.")
        _verify_model_artifact_hash(model_artifact_path, declaration)
        try:
            bundle = loader_strategies[strategy](model_artifact_path, declaration)
        except InferenceRuntimeError:
            raise
        except Exception as exc:  # pragma: no cover - message is intentionally generic
            raise BundleUnavailableError("Inference model artifact could not be loaded.") from exc

    return RuntimeBundleAdapter(
        source_path=loaded.source_path,
        model_artifact_path=model_artifact_path,
        declaration=declaration,
        metadata=metadata,
        bundle=bundle,
        prediction_callable=_prediction_callable(
            bundle,
            prediction_executor=prediction_executor,
        ),
    )


def execute_prediction(
    active_release: Mapping[str, Any],
    validated_payload: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
    bundle_loader: BundleLoader,
    prediction_executor: PredictionExecutor | None = None,
) -> dict[str, Any]:
    """Load the active release bundle and execute prediction.

    Returns the minimal structured prediction envelope currently confirmed for
    the runtime boundary. Public API serialization can wrap or adapt this shape
    when the API contract is finalized.
    """

    adapter = load_runtime_bundle_adapter(
        active_release,
        manifest=manifest,
        bundle_loader=bundle_loader,
        prediction_executor=prediction_executor,
    )

    try:
        prediction = adapter.predict(validated_payload)
    except InferenceRuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleExecutionError("Prediction execution failed.") from exc

    return {"prediction": prediction}


def _require_compatible_status(compatibility_status: Mapping[str, Any] | None) -> None:
    if compatibility_status is None:
        return
    if compatibility_status.get("status") != "compatible":
        raise BundleReferenceError("Inference bundle has not passed compatibility validation.")

    checks = compatibility_status.get("checks")
    if isinstance(checks, Mapping):
        for key in ("feature_order_compatible", "feature_names_compatible"):
            if checks.get(key) is False:
                raise BundleValidationError(
                    "feature_contract_mismatch",
                    "Inference bundle feature metadata is incompatible with the validated contract.",
                    field=f"compatibility_status.checks.{key}",
                )


def _release_root(active_release: Mapping[str, Any]) -> Path:
    for key in _RELEASE_ROOT_KEYS:
        value = active_release.get(key)
        if isinstance(value, str) and value.strip():
            root = Path(value).expanduser().resolve(strict=False)
            if root.is_dir():
                return root
            raise BundleReferenceError("Active release package is unavailable.")

    raise BundleReferenceError("Active release package path is not defined.")


def _bundle_reference(source: Mapping[str, Any]) -> str:
    artifact = _find_bundle_artifact(source)
    if artifact is None:
        raise BundleReferenceError("Inference bundle reference is not defined.")

    if isinstance(artifact, str):
        reference = artifact
    elif isinstance(artifact, Mapping):
        reference = _first_string_value(artifact, _REFERENCE_KEYS)
    else:
        reference = None

    if not reference:
        raise BundleReferenceError("Inference bundle reference is not defined.")

    return reference


def _find_bundle_artifact(source: Mapping[str, Any]) -> Any | None:
    direct = _first_string_value(
        source,
        (
            "inference_bundle",
            "predictive_bundle",
            "prediction_bundle",
            "model_bundle",
            "bundle",
            "bundle_path",
        ),
    )
    if direct:
        return direct

    artifacts = source.get("artifacts")
    if isinstance(artifacts, Mapping):
        for role in _BUNDLE_ROLES:
            artifact = artifacts.get(role)
            if artifact is not None:
                return artifact

    if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)):
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                continue
            role = artifact.get("role") or artifact.get("type") or artifact.get("name")
            if isinstance(role, str) and role in _BUNDLE_ROLES:
                return artifact

    return None


def _bundle_declaration(bundle: Any, manifest: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if isinstance(bundle, Mapping):
        return bundle
    if isinstance(manifest, Mapping):
        return manifest
    return {}


def _runtime_metadata(declaration: Mapping[str, Any]) -> RuntimeBundleMetadata:
    runtime_execution = declaration.get("runtime_execution")
    input_schema = declaration.get("input_schema")
    preprocessing = declaration.get("preprocessing")
    output_schema = declaration.get("output_schema")
    feature_order = declaration.get("feature_order")

    return RuntimeBundleMetadata(
        runtime_execution=runtime_execution if isinstance(runtime_execution, Mapping) else {},
        input_schema=input_schema if isinstance(input_schema, Mapping) else {},
        feature_order=tuple(feature_order) if _is_string_sequence(feature_order) else (),
        preprocessing=preprocessing if isinstance(preprocessing, Mapping) else {},
        output_schema=output_schema if isinstance(output_schema, Mapping) else {},
    )


def _validate_bundle_declaration(
    declaration: Mapping[str, Any],
    *,
    compatibility_status: Mapping[str, Any] | None,
    supported_serialization_formats: Sequence[str] | None,
) -> None:
    if not declaration:
        return

    runtime_execution = declaration.get("runtime_execution")
    if not isinstance(runtime_execution, Mapping):
        if _is_full_inference_bundle(declaration):
            raise BundleValidationError(
                "missing_runtime_execution",
                "Inference bundle runtime execution metadata is not defined.",
                field="runtime_execution",
            )
        return

    serialization_format = runtime_execution.get("serialization_format")
    if supported_serialization_formats is not None and serialization_format not in supported_serialization_formats:
        raise BundleValidationError(
            "unsupported_serialization_format",
            "Inference bundle serialization format is unsupported.",
            field="runtime_execution.serialization_format",
        )

    if _is_full_inference_bundle(declaration):
        _validate_required_references(declaration)
        _validate_contract_reference_versions(declaration)

    if compatibility_status is not None:
        _validate_compatibility_reference(declaration, compatibility_status)


def _is_full_inference_bundle(declaration: Mapping[str, Any]) -> bool:
    return any(
        key in declaration
        for key in (
            "bundle_identity",
            "contract_references",
            "training_evidence",
            "compatibility_constraints",
        )
    )


def _validate_required_references(declaration: Mapping[str, Any]) -> None:
    model_reference = _model_artifact_reference(declaration)
    if model_reference is None:
        raise BundleValidationError(
            "missing_model_artifact_reference",
            "Inference model artifact reference is not defined.",
            field="model_artifact.path",
        )

    training_evidence = declaration.get("training_evidence")
    if not isinstance(training_evidence, Mapping):
        raise BundleValidationError(
            "missing_training_evidence_reference",
            "Inference bundle training evidence references are not defined.",
            field="training_evidence",
        )
    for key in ("training_parameter_record", "training_metrics"):
        reference = training_evidence.get(key)
        if not isinstance(reference, Mapping) or not _first_string_value(reference, _REFERENCE_KEYS):
            raise BundleValidationError(
                "missing_training_evidence_reference",
                "Inference bundle training evidence reference is not defined.",
                field=f"training_evidence.{key}.path",
            )

    contract_references = declaration.get("contract_references")
    if not isinstance(contract_references, Mapping):
        raise BundleValidationError(
            "missing_contract_reference",
            "Inference bundle contract references are not defined.",
            field="contract_references",
        )
    for key in ("execution_contract", "runtime_contract", "public_contract"):
        reference = contract_references.get(key)
        if not isinstance(reference, Mapping) or not _first_string_value(reference, _REFERENCE_KEYS):
            raise BundleValidationError(
                "missing_contract_reference",
                "Inference bundle contract reference is not defined.",
                field=f"contract_references.{key}.path",
            )


def _validate_contract_reference_versions(declaration: Mapping[str, Any]) -> None:
    constraints = declaration.get("compatibility_constraints")
    if not isinstance(constraints, Mapping):
        return
    required_versions = constraints.get("requires_contract_versions")
    if not isinstance(required_versions, Mapping):
        return
    contract_references = declaration.get("contract_references")
    if not isinstance(contract_references, Mapping):
        return

    for key, required_version in required_versions.items():
        reference = contract_references.get(key)
        actual_version = reference.get("contract_version") if isinstance(reference, Mapping) else None
        if isinstance(required_version, str) and actual_version != required_version:
            raise BundleValidationError(
                "stale_contract_reference",
                "Inference bundle contract reference version is stale.",
                field=f"contract_references.{key}.contract_version",
            )


def _validate_compatibility_reference(
    declaration: Mapping[str, Any],
    compatibility_status: Mapping[str, Any],
) -> None:
    validated_bundle = compatibility_status.get("validated_bundle")
    if not isinstance(validated_bundle, str) or not validated_bundle.strip():
        return

    bundle_identity = declaration.get("bundle_identity")
    bundle_id = bundle_identity.get("bundle_id") if isinstance(bundle_identity, Mapping) else None
    release_context = declaration.get("release_context")
    release_reference = (
        release_context.get("release_package_reference") if isinstance(release_context, Mapping) else None
    )
    if validated_bundle not in {bundle_id, release_reference}:
        raise BundleValidationError(
            "stale_compatibility_reference",
            "Inference bundle compatibility validation references a different bundle.",
            field="compatibility_status.validated_bundle",
        )


def _model_artifact_reference(declaration: Mapping[str, Any]) -> str | None:
    model_artifact = declaration.get("model_artifact")
    if isinstance(model_artifact, Mapping):
        return _first_string_value(model_artifact, _REFERENCE_KEYS)
    return None


def _verify_model_artifact_hash(model_artifact_path: Path, declaration: Mapping[str, Any]) -> None:
    expected_hash = _model_artifact_sha256(declaration)
    if expected_hash is None:
        return
    actual_hash = _sha256_file(model_artifact_path)
    if actual_hash != expected_hash:
        raise BundleValidationError(
            "model_artifact_hash_mismatch",
            "Inference model artifact hash does not match the bundle declaration.",
            field="model_artifact.sha256",
        )


def _model_artifact_sha256(declaration: Mapping[str, Any]) -> str | None:
    model_artifact = declaration.get("model_artifact")
    if not isinstance(model_artifact, Mapping):
        return None
    value = model_artifact.get("sha256")
    if isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value):
        return value
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_release_relative_path(release_root: Path, reference: str) -> Path:
    raw_reference = Path(reference)
    if raw_reference.is_absolute():
        raise BundleReferenceError("Inference bundle reference must be release-relative.")

    candidate = (release_root / raw_reference).resolve(strict=False)
    try:
        candidate.relative_to(release_root)
    except ValueError as exc:
        raise BundleReferenceError("Inference bundle reference escapes the release package.") from exc

    return candidate


def _prediction_callable(
    bundle: Any,
    *,
    prediction_executor: PredictionExecutor | None,
) -> Callable[[Mapping[str, Any]], Any]:
    def predict(validated_payload: Mapping[str, Any]) -> Any:
        return _execute_loaded_bundle(
            bundle,
            validated_payload,
            prediction_executor=prediction_executor,
        )

    return predict


def _execute_loaded_bundle(
    bundle: Any,
    validated_payload: Mapping[str, Any],
    *,
    prediction_executor: PredictionExecutor | None,
) -> Any:
    if prediction_executor is not None:
        return prediction_executor(bundle, validated_payload)

    if isinstance(bundle, Mapping) and _is_descriptor_bundle(bundle):
        return _execute_descriptor_bundle(bundle, validated_payload)

    predict = getattr(bundle, "predict", None)
    if callable(predict):
        return predict(validated_payload)

    if callable(bundle):
        return bundle(validated_payload)

    raise BundleExecutionError("Inference bundle does not expose a prediction interface.")


def _is_descriptor_bundle(bundle: Mapping[str, Any]) -> bool:
    return (
        bundle.get("schema_version") == "predictive-bundle.v1"
        and bundle.get("bundle_kind") == "inference_descriptor"
    )


def _execute_descriptor_bundle(
    bundle: Mapping[str, Any],
    validated_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not validated_payload:
        raise BundleExecutionError("Prediction execution failed.")

    target = bundle.get("prediction_target")
    positive_meaning = bundle.get("positive_class_meaning")
    label_source = positive_meaning if isinstance(positive_meaning, str) and positive_meaning else target
    if not isinstance(label_source, str) or not label_source:
        raise BundleExecutionError("Prediction execution failed.")

    threshold = bundle.get("threshold", 0.5)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise BundleExecutionError("Prediction execution failed.")

    confidence = max(0.0, min(1.0, float(threshold)))
    return {
        "label": label_source,
        "confidence": confidence,
    }


def _first_string_value(source: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and all(
        isinstance(item, str) for item in value
    )
