"""Release-bound inference bundle loading and prediction execution.

This module deliberately accepts active release metadata and a bundle loader
from the caller. Dataset resolution, runtime contract loading, payload
validation, API response serialization, and public error mapping live outside
this runtime boundary.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import jsonschema


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

# S0109: the single explicit, allowlisted production loader strategy name.
# The allowlist itself (which strategy names are actually accepted) is
# selected by the caller (api/main.py); this module only implements the
# strategy's loading behavior.
JOBLIB_SKLEARN_PREDICT_STRATEGY = "joblib_sklearn_predict"

# S0151: the closed runtime diagnostic vocabulary. Every diagnostic_code
# ever attached to an InferenceRuntimeError (or left unset -- meaning
# "unclassified, generic fallback") is one of these seven values. Callers
# must never invent, derive, or accept any other code -- see
# api/main.py's RUNTIME_DIAGNOSTIC_CODES membership check before this value
# is ever surfaced to a private response.
DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE = "INFERENCE_BUNDLE_UNAVAILABLE"
DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE = "MODEL_ARTIFACT_UNAVAILABLE"
DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH = "MODEL_ARTIFACT_HASH_MISMATCH"
DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE = "RUNTIME_DEPENDENCY_UNAVAILABLE"
DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED = "MODEL_DESERIALIZATION_FAILED"
DIAGNOSTIC_PREDICTION_EXECUTION_FAILED = "PREDICTION_EXECUTION_FAILED"
DIAGNOSTIC_RESULT_VALIDATION_FAILED = "RESULT_VALIDATION_FAILED"

RUNTIME_DIAGNOSTIC_CODES = frozenset(
    {
        DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
        DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
        DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    }
)

# Strict tolerance for "two probabilities sum to 1.0".
_PROBABILITY_SUM_TOLERANCE = 1e-6

_RISK_BAND_IDS = ("low", "medium", "high")

# In-memory JSON Schema for binary-classification-result.v1. Deliberately not
# persisted as contracts/binary-classification-result.schema.json: that path
# is a candidate_edit_paths entry only, never promoted into this request's
# repository_context.allowed_edit_paths, so creating it would exceed this
# implementation's authorized edit scope. This inline schema still gives real,
# strict, versioned validation via jsonschema.validate before any result is
# serialized -- see implementation-evidence.json warnings for the same note.
_BINARY_CLASSIFICATION_RESULT_SCHEMA: dict[str, Any] = {
    "$id": "urn:atlas-dataflow:binary-classification-result.v1",
    "title": "binary-classification-result.v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "problem_type",
        "predicted_class",
        "positive_class",
        "positive_class_probability",
        "class_probabilities",
        "decision",
        "interpretation",
        "model_descriptor",
    ],
    "properties": {
        "schema_version": {"const": "binary-classification-result.v1"},
        "problem_type": {"const": "binary_classification"},
        "predicted_class": {
            "type": "object",
            "additionalProperties": False,
            "required": ["class_id"],
            "properties": {"class_id": {"type": "string", "minLength": 1}},
        },
        "positive_class": {
            "type": "object",
            "additionalProperties": False,
            "required": ["class_id", "event_label"],
            "properties": {
                "class_id": {"type": "string", "minLength": 1},
                "event_label": {"type": "string", "minLength": 1},
            },
        },
        "positive_class_probability": {"type": "number", "minimum": 0, "maximum": 1},
        "class_probabilities": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["class_id", "probability"],
                "properties": {
                    "class_id": {"type": "string", "minLength": 1},
                    "probability": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "decision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["threshold", "predicted_positive"],
            "properties": {
                "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "predicted_positive": {"type": "boolean"},
            },
        },
        "interpretation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["preset", "band_id", "bands"],
            "properties": {
                "preset": {"const": "risk"},
                "band_id": {"type": "string", "enum": list(_RISK_BAND_IDS)},
                "bands": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["band_id", "lower_bound", "upper_bound"],
                        "properties": {
                            "band_id": {"type": "string", "enum": list(_RISK_BAND_IDS)},
                            "lower_bound": {"type": "number", "minimum": 0, "maximum": 1},
                            "upper_bound": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                    },
                },
            },
        },
        "model_descriptor": {
            "type": "object",
            "additionalProperties": False,
            "required": ["model_family", "display_name"],
            "properties": {
                "model_family": {
                    "type": "string",
                    "enum": ["logistic_regression", "gradient_boosting", "random_forest"],
                },
                "display_name": {"type": "string", "minLength": 1},
            },
        },
    },
}


class InferenceRuntimeError(Exception):
    """Base exception for sanitized inference runtime failures.

    S0151: every instance carries a ``diagnostic_code`` -- one of the closed
    ``RUNTIME_DIAGNOSTIC_CODES`` vocabulary, or ``None`` when the failure
    cannot be classified through a controlled typed boundary (the caller must
    then keep the generic response with no runtime diagnostic).
    """

    def __init__(self, message: str, *, diagnostic_code: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code


class BundleReferenceError(InferenceRuntimeError):
    """Raised when active release metadata cannot identify a safe bundle."""


class BundleUnavailableError(InferenceRuntimeError):
    """Raised when the release-bound bundle cannot be loaded."""


class BundleExecutionError(InferenceRuntimeError):
    """Raised when prediction execution fails."""


class BundleValidationError(InferenceRuntimeError):
    """Raised when bundle metadata is invalid before runtime loading."""

    def __init__(self, code: str, message: str, *, field: str, diagnostic_code: str | None = None) -> None:
        super().__init__(message, diagnostic_code=diagnostic_code)
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
        raise BundleUnavailableError(
            "Inference bundle is unavailable.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )

    try:
        bundle = bundle_loader(bundle_path)
    except InferenceRuntimeError:
        raise
    except ImportError as exc:
        raise BundleUnavailableError(
            "Inference runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleUnavailableError(
            "Inference bundle could not be loaded.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        ) from exc

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
            raise BundleUnavailableError(
                "Inference model artifact is unavailable.",
                diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
            )
        _verify_model_artifact_hash(model_artifact_path, declaration)
        try:
            bundle = loader_strategies[strategy](model_artifact_path, declaration)
        except InferenceRuntimeError:
            raise
        except ImportError as exc:
            raise BundleUnavailableError(
                "Inference runtime dependency is unavailable.",
                diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
            ) from exc
        except Exception as exc:  # pragma: no cover - message is intentionally generic
            raise BundleUnavailableError(
                "Inference model artifact could not be loaded.",
                diagnostic_code=DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
            ) from exc

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
    loader_strategies: Mapping[str, LoaderStrategy] | None = None,
    supported_serialization_formats: Sequence[str] | None = None,
    compatibility_status: Mapping[str, Any] | None = None,
    prediction_executor: PredictionExecutor | None = None,
) -> dict[str, Any]:
    """Load the active release bundle and execute prediction.

    When ``loader_strategies`` is supplied and no test-only
    ``prediction_executor`` override is given, this is the real production
    path: the bundle-declared loader strategy is used to deserialize the
    release-local model, and a full S0108/S0109 binary-classification result
    is resolved and returned under ``{"result": ...}``.

    A caller-supplied ``prediction_executor`` always takes precedence and
    preserves the original generic/legacy envelope (``{"prediction": ...}``),
    regardless of whether ``loader_strategies`` was also supplied -- this
    keeps every existing test-only injected-executor call site working
    unchanged.

    With neither ``loader_strategies`` nor ``prediction_executor``, the
    original generic bundle-execution behavior (including the historical
    JSON-descriptor fallback) is unchanged.
    """

    adapter = load_runtime_bundle_adapter(
        active_release,
        manifest=manifest,
        bundle_loader=bundle_loader,
        loader_strategies=loader_strategies,
        supported_serialization_formats=supported_serialization_formats,
        prediction_executor=prediction_executor,
        compatibility_status=compatibility_status,
    )

    if loader_strategies is not None and prediction_executor is None:
        return {"result": _execute_binary_prediction(adapter, validated_payload)}

    try:
        prediction = adapter.predict(validated_payload)
    except InferenceRuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        ) from exc

    return {"prediction": prediction}


def validate_binary_classification_result(result: Mapping[str, Any]) -> None:
    """Strictly validate a serialized result against binary-classification-result.v1.

    Exposed so API-layer callers can perform a defense-in-depth re-validation
    pass on the exact same in-memory schema used internally, without
    duplicating the schema definition.
    """

    try:
        jsonschema.validate(result, _BINARY_CLASSIFICATION_RESULT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise BundleValidationError(
            "invalid_binary_classification_result",
            "Binary classification result failed schema validation.",
            field="result",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        ) from exc


def load_joblib_sklearn_model(model_path: Path, declaration: Mapping[str, Any]) -> Any:
    """The single explicit ``joblib_sklearn_predict`` production loader strategy.

    Loads only the already-resolved, release-local, hash-verified model path
    via the repository-supported joblib interface. Never resolves a path from
    model content, never imports arbitrary modules declared by the bundle,
    never calls ``pickle.loads()`` on network/request data.
    """

    runtime_execution = declaration.get("runtime_execution")
    serialization_format = (
        runtime_execution.get("serialization_format") if isinstance(runtime_execution, Mapping) else None
    )
    if serialization_format != "joblib":
        raise BundleUnavailableError("Inference model serialization format is unsupported.")

    try:
        import joblib  # local import: keep this dependency scoped to the loader strategy
    except ImportError as exc:
        raise BundleUnavailableError(
            "Inference runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    try:
        return joblib.load(model_path)
    except InferenceRuntimeError:
        raise
    except ImportError as exc:
        # A missing/incompatible transitive dependency (e.g. scikit-learn)
        # needed to unpickle the model surfaces here too -- never expose the
        # package name, only the closed diagnostic code.
        raise BundleUnavailableError(
            "Inference runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleUnavailableError(
            "Inference model artifact could not be loaded.",
            diagnostic_code=DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
        ) from exc


def project_result_contract(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only result-contract projection for GET /datasets/{slug}/contract.

    Never deserializes the model and never executes inference -- only
    validates already-loaded bundle JSON metadata. Returns either
    ``{"status": "available", "semantics": {...}}`` or
    ``{"status": "unavailable", "reason": "binary_result_semantics_unavailable"}``.
    Historical/incompatible bundles never receive invented defaults.
    """

    try:
        semantics = _validate_result_semantics(declaration)
    except BundleValidationError:
        return {"status": "unavailable", "reason": "binary_result_semantics_unavailable"}

    return {
        "status": "available",
        "semantics": {
            "schema_version": semantics["schema_version"],
            "problem_type": semantics["problem_type"],
            "result_schema_version": semantics["result_schema_version"],
            "primary_output": semantics["primary_output"],
            "positive_class": dict(semantics["positive_class"]),
            "negative_class": dict(semantics["negative_class"]),
            "decision": dict(semantics["decision"]),
            "interpretation": {
                "preset": semantics["interpretation"]["preset"],
                "bands": [dict(band) for band in semantics["interpretation"]["bands"]],
            },
            "model_descriptor": dict(semantics["model_descriptor"]),
        },
    }


def _execute_binary_prediction(
    adapter: RuntimeBundleAdapter,
    validated_payload: Mapping[str, Any],
) -> dict[str, Any]:
    semantics = _validate_result_semantics(adapter.declaration)

    row = _build_ordered_row(adapter.metadata.feature_order, validated_payload)

    model = adapter.bundle
    predict = getattr(model, "predict", None)
    predict_proba = getattr(model, "predict_proba", None)
    if not callable(predict) or not callable(predict_proba):
        raise BundleExecutionError(
            "Inference model does not expose a binary prediction interface.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    try:
        raw_prediction = predict(row)
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        ) from exc
    predicted_values = _as_flat_list(raw_prediction)
    if len(predicted_values) != 1:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    try:
        raw_proba = predict_proba(row)
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        ) from exc
    proba_rows = _as_matrix(raw_proba)
    if len(proba_rows) != 1 or len(proba_rows[0]) != 2:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )
    proba_row = proba_rows[0]

    model_classes = _resolve_model_classes(model)
    unique_model_classes = list(dict.fromkeys(_normalize_class_id(c) for c in model_classes))
    if len(unique_model_classes) != 2:
        raise BundleExecutionError("Inference model does not expose exactly two classes.")

    if _normalize_class_id(predicted_values[0]) not in unique_model_classes:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    positive_class_id = semantics["positive_class"]["class_id"]
    positive_normalized = _normalize_class_id(positive_class_id)

    bundle_class_labels = list(adapter.metadata.output_schema.get("class_labels") or ())
    bundle_normalized = list(dict.fromkeys(_normalize_class_id(c) for c in bundle_class_labels))
    if set(bundle_normalized) != set(unique_model_classes):
        raise BundleValidationError(
            "model_class_bundle_class_mismatch",
            "Inference model classes are inconsistent with bundle class labels.",
            field="output_schema.class_labels",
        )

    if positive_normalized not in unique_model_classes:
        raise BundleValidationError(
            "positive_class_not_found",
            "Approved positive class was not found in the model's actual classes.",
            field="result_semantics.positive_class.class_id",
        )

    positive_index = [_normalize_class_id(c) for c in model_classes].index(positive_normalized)
    class_probabilities = _validate_probabilities(proba_row)
    positive_class_probability = class_probabilities[positive_index]

    threshold = semantics["decision"]["threshold"]
    predicted_positive = positive_class_probability >= threshold
    predicted_class_id = (
        positive_class_id if predicted_positive else semantics["negative_class"]["class_id"]
    )

    band_id = _resolve_band(positive_class_probability, semantics["interpretation"]["bands"])

    result: dict[str, Any] = {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": predicted_class_id},
        "positive_class": {
            "class_id": positive_class_id,
            "event_label": semantics["positive_class"]["event_label"],
        },
        "positive_class_probability": positive_class_probability,
        "class_probabilities": [
            {"class_id": str(model_classes[0]), "probability": class_probabilities[0]},
            {"class_id": str(model_classes[1]), "probability": class_probabilities[1]},
        ],
        "decision": {
            "threshold": threshold,
            "predicted_positive": bool(predicted_positive),
        },
        "interpretation": {
            "preset": semantics["interpretation"]["preset"],
            "band_id": band_id,
            "bands": [dict(band) for band in semantics["interpretation"]["bands"]],
        },
        "model_descriptor": dict(semantics["model_descriptor"]),
    }

    validate_binary_classification_result(result)
    return result


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
            raise BundleReferenceError(
                "Active release package is unavailable.",
                diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            )

    raise BundleReferenceError(
        "Active release package path is not defined.",
        diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
    )


def _bundle_reference(source: Mapping[str, Any]) -> str:
    artifact = _find_bundle_artifact(source)
    if artifact is None:
        raise BundleReferenceError(
            "Inference bundle reference is not defined.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )

    if isinstance(artifact, str):
        reference = artifact
    elif isinstance(artifact, Mapping):
        reference = _first_string_value(artifact, _REFERENCE_KEYS)
    else:
        reference = None

    if not reference:
        raise BundleReferenceError(
            "Inference bundle reference is not defined.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )

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
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
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


def _validate_result_semantics(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate the S0108 result_semantics block. Never invents defaults."""

    semantics = declaration.get("result_semantics")
    if not isinstance(semantics, Mapping):
        raise BundleValidationError(
            "missing_result_semantics",
            "Inference bundle binary result semantics are not defined.",
            field="result_semantics",
        )

    if semantics.get("schema_version") != "binary-result-semantics.v1":
        raise BundleValidationError(
            "invalid_result_semantics_schema_version",
            "Inference bundle result semantics schema version is unsupported.",
            field="result_semantics.schema_version",
        )
    if semantics.get("problem_type") != "binary_classification":
        raise BundleValidationError(
            "invalid_result_semantics_problem_type",
            "Inference bundle problem type is not binary classification.",
            field="result_semantics.problem_type",
        )
    if semantics.get("result_schema_version") != "binary-classification-result.v1":
        raise BundleValidationError(
            "invalid_result_semantics_result_schema_version",
            "Inference bundle result schema version is unsupported.",
            field="result_semantics.result_schema_version",
        )
    if semantics.get("primary_output") != "positive_class_probability":
        raise BundleValidationError(
            "invalid_result_semantics_primary_output",
            "Inference bundle primary output is not positive_class_probability.",
            field="result_semantics.primary_output",
        )

    positive_class = semantics.get("positive_class")
    if not isinstance(positive_class, Mapping):
        raise BundleValidationError(
            "missing_positive_class",
            "Inference bundle positive class is not defined.",
            field="result_semantics.positive_class",
        )
    class_id = positive_class.get("class_id")
    event_label = positive_class.get("event_label")
    if not isinstance(class_id, str) or not class_id.strip():
        raise BundleValidationError(
            "invalid_positive_class_id",
            "Inference bundle positive class id is not defined.",
            field="result_semantics.positive_class.class_id",
        )
    if not isinstance(event_label, str) or not event_label.strip():
        raise BundleValidationError(
            "invalid_positive_class_event_label",
            "Inference bundle positive class event label is not defined.",
            field="result_semantics.positive_class.event_label",
        )

    class_identities = _resolve_binary_class_identities(declaration, positive_class)

    decision = semantics.get("decision")
    threshold = decision.get("threshold") if isinstance(decision, Mapping) else None
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0.0 <= threshold <= 1.0
    ):
        raise BundleValidationError(
            "invalid_decision_threshold",
            "Inference bundle decision threshold is invalid.",
            field="result_semantics.decision.threshold",
        )

    interpretation = semantics.get("interpretation")
    if not isinstance(interpretation, Mapping) or interpretation.get("preset") != "risk":
        raise BundleValidationError(
            "invalid_interpretation_preset",
            "Inference bundle interpretation preset is invalid.",
            field="result_semantics.interpretation.preset",
        )
    bands = _validate_bands(interpretation.get("bands"))

    model_descriptor = semantics.get("model_descriptor")
    if not isinstance(model_descriptor, Mapping):
        raise BundleValidationError(
            "missing_model_descriptor",
            "Inference bundle model descriptor is not defined.",
            field="result_semantics.model_descriptor",
        )
    model_family = model_descriptor.get("model_family")
    display_name = model_descriptor.get("display_name")
    if model_family not in ("logistic_regression", "gradient_boosting", "random_forest"):
        raise BundleValidationError(
            "invalid_model_family",
            "Inference bundle model family is invalid.",
            field="result_semantics.model_descriptor.model_family",
        )
    if not isinstance(display_name, str) or not display_name.strip():
        raise BundleValidationError(
            "invalid_model_display_name",
            "Inference bundle model display name is not defined.",
            field="result_semantics.model_descriptor.display_name",
        )

    return {
        "schema_version": semantics["schema_version"],
        "problem_type": semantics["problem_type"],
        "result_schema_version": semantics["result_schema_version"],
        "primary_output": semantics["primary_output"],
        "positive_class": {
            "class_id": class_identities["positive_class"]["class_id"],
            "event_label": event_label,
        },
        "negative_class": class_identities["negative_class"],
        "decision": {"threshold": float(threshold)},
        "interpretation": {"preset": "risk", "bands": bands},
        "model_descriptor": {"model_family": model_family, "display_name": display_name},
    }


def _validate_bands(bands: Any) -> list[dict[str, Any]]:
    if not isinstance(bands, Sequence) or isinstance(bands, (str, bytes)) or len(bands) != 3:
        raise BundleValidationError(
            "invalid_interpretation_bands",
            "Inference bundle interpretation bands are invalid.",
            field="result_semantics.interpretation.bands",
        )

    parsed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for band in bands:
        if not isinstance(band, Mapping):
            raise BundleValidationError(
                "invalid_interpretation_bands",
                "Inference bundle interpretation bands are invalid.",
                field="result_semantics.interpretation.bands",
            )
        band_id = band.get("band_id")
        lower_bound = band.get("lower_bound")
        upper_bound = band.get("upper_bound")
        if band_id not in _RISK_BAND_IDS or band_id in seen_ids:
            raise BundleValidationError(
                "invalid_interpretation_bands",
                "Inference bundle interpretation bands are invalid.",
                field="result_semantics.interpretation.bands",
            )
        for bound in (lower_bound, upper_bound):
            if (
                not isinstance(bound, (int, float))
                or isinstance(bound, bool)
                or not math.isfinite(bound)
                or not 0.0 <= bound <= 1.0
            ):
                raise BundleValidationError(
                    "invalid_interpretation_bands",
                    "Inference bundle interpretation bands are invalid.",
                    field="result_semantics.interpretation.bands",
                )
        if lower_bound >= upper_bound:
            raise BundleValidationError(
                "invalid_interpretation_bands",
                "Inference bundle interpretation bands are invalid.",
                field="result_semantics.interpretation.bands",
            )
        seen_ids.add(band_id)
        parsed.append({"band_id": band_id, "lower_bound": float(lower_bound), "upper_bound": float(upper_bound)})

    parsed.sort(key=lambda b: b["lower_bound"])
    if [b["band_id"] for b in parsed] != list(_RISK_BAND_IDS):
        raise BundleValidationError(
            "invalid_interpretation_bands",
            "Inference bundle interpretation bands are invalid.",
            field="result_semantics.interpretation.bands",
        )
    if parsed[0]["lower_bound"] != 0.0 or parsed[-1]["upper_bound"] != 1.0:
        raise BundleValidationError(
            "invalid_interpretation_bands",
            "Inference bundle interpretation bands are invalid.",
            field="result_semantics.interpretation.bands",
        )
    for previous, current in zip(parsed, parsed[1:]):
        if previous["upper_bound"] != current["lower_bound"]:
            raise BundleValidationError(
                "invalid_interpretation_bands",
                "Inference bundle interpretation bands are invalid.",
                field="result_semantics.interpretation.bands",
            )

    return parsed


def _resolve_binary_class_identities(
    declaration: Mapping[str, Any], positive_class: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    """Resolve the governed binary identities without loading a model."""

    output_schema = declaration.get("output_schema")
    class_labels = output_schema.get("class_labels") if isinstance(output_schema, Mapping) else None
    if not isinstance(class_labels, Sequence) or isinstance(class_labels, (str, bytes)) or len(class_labels) != 2:
        raise BundleValidationError(
            "invalid_output_schema_class_labels",
            "Inference bundle output schema must define exactly two class labels.",
            field="output_schema.class_labels",
        )

    projected_labels = [str(label).strip() for label in class_labels]
    normalized_labels = [_normalize_class_id(label) for label in class_labels]
    if any(not label for label in normalized_labels):
        raise BundleValidationError(
            "invalid_output_schema_class_labels",
            "Inference bundle output schema class labels must be non-empty.",
            field="output_schema.class_labels",
        )
    if len(set(normalized_labels)) != 2:
        raise BundleValidationError(
            "binary_class_labels_not_unique",
            "Inference bundle output schema class labels are not unique after normalization.",
            field="output_schema.class_labels",
        )

    positive_id = str(positive_class.get("class_id", "")).strip()
    positive_normalized = _normalize_class_id(positive_id)
    matches = [index for index, label in enumerate(normalized_labels) if label == positive_normalized]
    if len(matches) != 1:
        raise BundleValidationError(
            "positive_class_not_in_bundle_class_labels",
            "Inference bundle positive class does not match exactly one output schema class label.",
            field="result_semantics.positive_class.class_id",
        )

    negative_index = 1 - matches[0]
    return {
        "positive_class": {"class_id": positive_id},
        "negative_class": {"class_id": projected_labels[negative_index]},
    }


def _build_ordered_row(feature_order: Sequence[str], validated_payload: Mapping[str, Any]) -> Any:
    if not feature_order:
        raise BundleValidationError(
            "missing_feature_order",
            "Inference bundle feature order is not defined.",
            field="feature_order",
        )
    if len(set(feature_order)) != len(feature_order):
        raise BundleValidationError(
            "duplicate_feature_order_entry",
            "Inference bundle feature order contains a duplicate entry.",
            field="feature_order",
        )

    row: dict[str, Any] = {}
    for feature_name in feature_order:
        if feature_name not in validated_payload:
            raise BundleValidationError(
                "missing_feature_value",
                "Validated payload is missing a required feature-order value.",
                field=f"feature_order.{feature_name}",
            )
        row[feature_name] = validated_payload[feature_name]

    try:
        import pandas as pd  # local import: keep this dependency scoped to the binary flow
    except ImportError as exc:
        raise BundleUnavailableError(
            "Inference runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    return pd.DataFrame([row], columns=list(feature_order))


def _resolve_model_classes(model: Any) -> list[Any]:
    classes = getattr(model, "classes_", None)
    if classes is None:
        steps = getattr(model, "steps", None)
        if isinstance(steps, Sequence) and steps:
            final_estimator = steps[-1][1]
            classes = getattr(final_estimator, "classes_", None)
    if classes is None:
        raise BundleExecutionError("Inference model does not expose class labels.")
    return list(classes)


def _normalize_class_id(value: Any) -> str:
    return str(value).strip().lower()


def _as_flat_list(value: Any) -> list[Any]:
    try:
        return list(value)
    except TypeError:
        return [value]


def _as_matrix(value: Any) -> list[list[Any]]:
    try:
        rows = list(value)
    except TypeError:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )
    matrix: list[list[Any]] = []
    for row in rows:
        try:
            matrix.append(list(row))
        except TypeError:
            raise BundleExecutionError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
    return matrix


def _validate_probabilities(proba_row: Sequence[Any]) -> list[float]:
    if len(proba_row) != 2:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    values: list[float] = []
    for value in proba_row:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BundleExecutionError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise BundleExecutionError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        values.append(numeric)

    if abs(sum(values) - 1.0) > _PROBABILITY_SUM_TOLERANCE:
        raise BundleExecutionError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    return values


def _resolve_band(probability: float, bands: Sequence[Mapping[str, Any]]) -> str:
    matches = [
        band["band_id"]
        for band in bands
        if (
            band["lower_bound"] <= probability < band["upper_bound"]
            or (band["upper_bound"] == 1.0 and probability == 1.0)
        )
    ]
    if len(matches) != 1:
        raise BundleValidationError(
            "invalid_band_resolution",
            "Inference bundle interpretation bands did not resolve to exactly one band.",
            field="result_semantics.interpretation.bands",
        )
    return matches[0]
