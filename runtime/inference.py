"""Release-bound inference bundle loading and prediction execution.

This module deliberately accepts active release metadata and a bundle loader
from the caller. Dataset resolution, runtime contract loading, payload
validation, API response serialization, and public error mapping live outside
this runtime boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


BundleLoader = Callable[[Path], Any]
PredictionExecutor = Callable[[Any, Mapping[str, Any]], Any]

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


@dataclass(frozen=True)
class LoadedInferenceBundle:
    """Loaded bundle with the resolved release-local source retained internally."""

    source_path: Path
    bundle: Any


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

    loaded = load_inference_bundle(
        active_release,
        manifest=manifest,
        bundle_loader=bundle_loader,
    )

    try:
        prediction = _execute_loaded_bundle(
            loaded.bundle,
            validated_payload,
            prediction_executor=prediction_executor,
        )
    except InferenceRuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise BundleExecutionError("Prediction execution failed.") from exc

    return {"prediction": prediction}


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


def _execute_loaded_bundle(
    bundle: Any,
    validated_payload: Mapping[str, Any],
    *,
    prediction_executor: PredictionExecutor | None,
) -> Any:
    if prediction_executor is not None:
        return prediction_executor(bundle, validated_payload)

    predict = getattr(bundle, "predict", None)
    if callable(predict):
        return predict(validated_payload)

    if callable(bundle):
        return bundle(validated_payload)

    raise BundleExecutionError("Inference bundle does not expose a prediction interface.")


def _first_string_value(source: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
