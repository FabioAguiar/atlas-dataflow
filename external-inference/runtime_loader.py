"""Load-safe gate and trusted execution for the isolated external-inference service.

Implements the load-safe gate for a governed release identity. This
module never accepts an absolute caller-selected filesystem path, executable
loader/module name, dependency override, or hash bypass. Bundle-relative
resolution remains confined beneath MODEL_ROOT and deserialization happens
only after release, bundle, trust, integrity, and exact-compatibility gates pass.

Deliberately self-contained: this image does not share code with the Atlas
api image (different Python runtime, different dependency pins), so its
bounded binary/multiclass result shaping remains local rather than importing
from runtime/inference.py.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any, Mapping

RELEASES_ROOT = Path("/app/releases")
MODEL_ROOT = RELEASES_ROOT  # Compatibility alias for callers of the public helpers.
MANIFEST_FILENAME = "manifest.json"

MANIFEST_CONTRACT_VERSION = "external_inference_model_manifest.v1"
REQUEST_CONTRACT_VERSION = "external_inference_request.v1"
PACKAGED_RUNTIME = {
    "python_major_minor": "3.11",
    "joblib": "1.5.3",
    "pandas": "3.0.3",
    "scikit_learn": "1.9.0",
}

RUNTIME_COMPATIBILITY_STATUSES = frozenset(
    {
        "compatible",
        "incompatible",
        "invalid_expected_runtime",
        "invalid_observed_runtime",
        "stale_bundle_reference",
    }
)

# S0160/G0001 naming_vocabulary.failure_diagnostic_mapping: the closed,
# unchanged, eight-value Atlas RUNTIME_DIAGNOSTIC_CODES vocabulary. This
# service never introduces a ninth code.
DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE = "INFERENCE_BUNDLE_UNAVAILABLE"
DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE = "MODEL_ARTIFACT_UNAVAILABLE"
DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH = "MODEL_ARTIFACT_HASH_MISMATCH"
DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE = "RUNTIME_DEPENDENCY_UNAVAILABLE"
DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED = "MODEL_DESERIALIZATION_FAILED"
DIAGNOSTIC_PREDICTION_EXECUTION_FAILED = "PREDICTION_EXECUTION_FAILED"
DIAGNOSTIC_RESULT_VALIDATION_FAILED = "RESULT_VALIDATION_FAILED"
DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT = "RUNTIME_INPUT_CONTRACT_INCONSISTENT"

RUNTIME_DIAGNOSTIC_CODES = frozenset(
    {
        DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
        DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
        DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT,
    }
)

_PROBABILITY_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PredictionPlan:
    result_variant: str
    feature_order: tuple[str, ...]
    required_features: frozenset[str]
    output_classes: tuple[str, ...]
    model_descriptor: Mapping[str, str]
    positive_class: Mapping[str, str] | None = None
    negative_class_id: str | None = None
    threshold: float | None = None
    risk_bands: tuple[Mapping[str, Any], ...] = ()
    multiclass_classes: tuple[Mapping[str, str], ...] = ()

_BINARY_CLASSIFICATION_RESULT_SCHEMA: dict[str, Any] = {
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
                "band_id": {"type": "string", "enum": ["low", "medium", "high"]},
                "bands": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["band_id", "lower_bound", "upper_bound"],
                        "properties": {
                            "band_id": {"type": "string", "enum": ["low", "medium", "high"]},
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
                    "enum": ["logistic_regression", "gradient_boosting", "random_forest", "hist_gradient_boosting"],
                },
                "display_name": {"type": "string", "minLength": 1},
            },
        },
    },
}

_MULTICLASS_CLASSIFICATION_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "problem_type", "predicted_class", "class_probabilities", "decision", "model_descriptor"],
    "properties": {
        "schema_version": {"const": "multiclass-classification-result.v1"},
        "problem_type": {"const": "multiclass_classification"},
        "predicted_class": {
            "type": "object", "additionalProperties": False,
            "required": ["class_id", "display_label"],
            "properties": {"class_id": {"type": "string", "minLength": 1}, "display_label": {"type": "string", "minLength": 1}},
        },
        "class_probabilities": {
            "type": "array", "minItems": 3,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["class_id", "display_label", "probability"],
                "properties": {
                    "class_id": {"type": "string", "minLength": 1},
                    "display_label": {"type": "string", "minLength": 1},
                    "probability": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "decision": {"type": "object", "additionalProperties": False, "required": ["strategy"], "properties": {"strategy": {"const": "argmax"}}},
        "model_descriptor": {
            "type": "object", "additionalProperties": False, "required": ["model_family", "display_name"],
            "properties": {
                "model_family": {"type": "string", "enum": ["logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting"]},
                "display_name": {"type": "string", "minLength": 1},
            },
        },
    },
}


class LoadSafeGateError(Exception):
    """Carries a closed diagnostic code and (when applicable) a runtime_compatibility_status."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_code: str | None = None,
        runtime_compatibility_status: str | None = None,
        category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.runtime_compatibility_status = runtime_compatibility_status
        self.category = category


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Step 1-2: resolve bundle identity, validate trusted source declaration ---


def _resolve_bundle_root(request: Mapping[str, Any] | None, model_root: Path) -> Path:
    identity = request.get("bundle_identity") if isinstance(request, Mapping) else None
    logical_name = identity.get("dataset_slug") if isinstance(identity, Mapping) else None
    if request is None:
        candidates = sorted(path.parent for path in model_root.glob(f"*/{MANIFEST_FILENAME}") if path.is_file())
        if len(candidates) == 1:
            return candidates[0].resolve(strict=False)
    if not isinstance(logical_name, str) or not logical_name or any(
        part in logical_name for part in ("/", "\\", "..")
    ):
        raise LoadSafeGateError(
            "Runtime profile identity is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="runtime_profile_invalid",
        )
    root = model_root.resolve(strict=False)
    bundle_root = (root / logical_name).resolve(strict=False)
    try:
        bundle_root.relative_to(root)
    except ValueError as exc:
        raise LoadSafeGateError(
            "Runtime profile identity is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="runtime_profile_invalid",
        ) from exc
    return bundle_root


def validate_governed_runtime_profile(
    profile: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    """Validate governed profile policy before artifact bytes are loaded."""

    required_runtime = profile.get("required_consumer_runtime")
    dependencies = required_runtime.get("dependencies") if isinstance(required_runtime, Mapping) else None
    integrity = profile.get("artifact_integrity")
    if (
        not isinstance(profile.get("profile_id"), str)
        or not isinstance(profile.get("profile_version"), str)
        or not isinstance(required_runtime, Mapping)
        or not isinstance(dependencies, Mapping)
        or profile.get("compatibility_policy") != "exact"
        or profile.get("artifact_format") != "joblib"
        or profile.get("loader_family") != "joblib_sklearn_predict"
    ):
        raise LoadSafeGateError(
            "Runtime profile is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="runtime_profile_invalid",
        )
    if profile.get("trusted_source_required") is not True or not isinstance(
        manifest.get("trusted_source"), Mapping
    ):
        raise LoadSafeGateError(
            "Artifact trust policy failed.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="untrusted_artifact",
        )
    if not isinstance(integrity, Mapping) or integrity.get("model_sha256") != (
        manifest.get("model_artifact") or {}
    ).get("byte_sha256"):
        raise LoadSafeGateError(
            "Artifact integrity declaration does not match.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
            category="artifact_integrity_mismatch",
        )
    if profile.get("load_safe") is not True:
        raise LoadSafeGateError(
            "Artifact is not declared load-safe.",
            diagnostic_code=DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
            category="load_not_safe",
        )


def load_manifest(model_root: Path | None = None, *, request: Mapping[str, Any] | None = None) -> dict:
    resolved_root = model_root if model_root is not None else MODEL_ROOT
    bundle_root = _resolve_bundle_root(request, resolved_root)
    manifest_path = bundle_root / MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise LoadSafeGateError(
            "External model manifest is unavailable.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        ) from exc

    if not isinstance(manifest, dict):
        raise LoadSafeGateError(
            "External model manifest is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )
    if manifest.get("contract_version") != MANIFEST_CONTRACT_VERSION:
        raise LoadSafeGateError(
            "External model manifest contract version is unsupported.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )

    bundle_identity = manifest.get("bundle_identity")
    trusted_source = manifest.get("trusted_source")
    model_artifact = manifest.get("model_artifact")
    expected_runtime = manifest.get("expected_runtime")
    if (
        not isinstance(bundle_identity, dict)
        or not bundle_identity.get("bundle_id")
        or not bundle_identity.get("dataset_slug")
        or not isinstance(trusted_source, dict)
        or not isinstance(model_artifact, dict)
        or not isinstance(expected_runtime, dict)
    ):
        raise LoadSafeGateError(
            "External model manifest trusted source declaration is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )

    manifest["_resolved_bundle_root"] = bundle_root
    return manifest


# --- Step 3: release-relative path resolution ---


def resolve_model_path(manifest: Mapping[str, Any], model_root: Path | None = None) -> Path:
    model_root = model_root if model_root is not None else MODEL_ROOT
    model_artifact = manifest.get("model_artifact") or {}
    relative_path = model_artifact.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise LoadSafeGateError(
            "External model artifact reference is not defined.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        )

    raw_reference = Path(relative_path)
    if raw_reference.is_absolute():
        raise LoadSafeGateError(
            "External model artifact reference must be bundle-relative.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        )

    declared_bundle_root = manifest.get("_resolved_bundle_root")
    if not isinstance(declared_bundle_root, Path):
        raise LoadSafeGateError(
            "Runtime profile identity is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="runtime_profile_invalid",
        )
    bundle_root = declared_bundle_root.resolve(strict=False)
    unresolved_candidate = bundle_root / raw_reference
    if unresolved_candidate.is_symlink():
        raise LoadSafeGateError(
            "External model artifact reference must not be a symlink.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        )

    candidate = unresolved_candidate.resolve(strict=False)
    try:
        candidate.relative_to(bundle_root)
    except ValueError as exc:
        raise LoadSafeGateError(
            "External model artifact reference escapes the bundle root.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        ) from exc

    return unresolved_candidate


# --- Step 4: contract-version validation ---


def validate_request_contract_version(request: Mapping[str, Any]) -> None:
    if request.get("contract_version") != REQUEST_CONTRACT_VERSION:
        raise LoadSafeGateError(
            "Request contract version is unsupported.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )


# --- Step 5: existence + regular-file-type verification ---


def verify_model_artifact_existence(model_path: Path) -> None:
    if model_path.is_symlink() or not model_path.is_file():
        raise LoadSafeGateError(
            "External model artifact is unavailable.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
        )


# --- Step 6: sha256 verification before any deserialization ---


def verify_model_artifact_hash(manifest: Mapping[str, Any], model_path: Path) -> None:
    model_artifact = manifest.get("model_artifact") or {}
    expected_hash = model_artifact.get("byte_sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise LoadSafeGateError(
            "External model manifest hash declaration is invalid.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
        )
    actual_hash = _sha256_file(model_path)
    if actual_hash != expected_hash:
        raise LoadSafeGateError(
            "External model artifact hash does not match the manifest declaration.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
        )


# --- Step 7: model-state fingerprint reference consistency (never deserializes) ---


def verify_model_state_fingerprint(manifest: Mapping[str, Any]) -> None:
    model_artifact = manifest.get("model_artifact") or {}
    fingerprint = model_artifact.get("model_state_fingerprint")
    if fingerprint is None:
        return
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise LoadSafeGateError(
            "External model manifest state fingerprint is invalid.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
            category="artifact_integrity_mismatch",
        )


# --- Step 8: expected runtime identity from the validated manifest ---


def read_expected_runtime(manifest: Mapping[str, Any]) -> dict:
    expected_runtime = manifest.get("expected_runtime")
    if not isinstance(expected_runtime, dict):
        raise LoadSafeGateError(
            "External model manifest expected runtime is not defined.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
        )
    for key in ("python_major_minor", "joblib", "pandas", "scikit_learn"):
        value = expected_runtime.get(key)
        if not isinstance(value, str) or not value.strip():
            raise LoadSafeGateError(
                "External model manifest expected runtime is invalid.",
                diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            )
    return dict(expected_runtime)


# --- Step 9: observe the isolated runtime's actual identity ---


def observe_isolated_runtime() -> dict:
    try:
        import joblib
        import pandas
        import sklearn
    except ImportError as exc:
        raise LoadSafeGateError(
            "Isolated runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    return {
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_patch": str(sys.version_info.micro),
        "joblib": joblib.__version__,
        "pandas": pandas.__version__,
        "scikit_learn": sklearn.__version__,
    }


# --- Step 10: evaluate the load-safe compatibility policy ---


def evaluate_load_safe_compatibility(
    *,
    request: Mapping[str, Any] | None,
    manifest_bundle_identity: Mapping[str, Any],
    expected_runtime: Mapping[str, Any],
    observed_runtime: Mapping[str, Any],
) -> dict:
    """Returns {"status": <one of RUNTIME_COMPATIBILITY_STATUSES>, "python_patch_warning": bool}.

    ``request`` is optional -- GET /ready has no request body to cross-check
    a caller-declared bundle_identity/expected_runtime against, so it
    evaluates compatibility purely from the manifest's own expected runtime
    versus the observed runtime.
    """

    if request is not None:
        request_bundle_identity = request.get("bundle_identity")
        request_expected_runtime = request.get("expected_runtime")
        if not isinstance(request_bundle_identity, dict) or not isinstance(request_expected_runtime, dict):
            return {"status": "invalid_expected_runtime", "python_patch_warning": False}

        if request_bundle_identity.get("bundle_id") != manifest_bundle_identity.get(
            "bundle_id"
        ) or request_bundle_identity.get("dataset_slug") != manifest_bundle_identity.get("dataset_slug"):
            return {"status": "stale_bundle_reference", "python_patch_warning": False}

        for key in ("python_major_minor", "joblib", "pandas", "scikit_learn"):
            if request_expected_runtime.get(key) != expected_runtime.get(key):
                return {"status": "stale_bundle_reference", "python_patch_warning": False}

    for key in ("joblib", "pandas", "scikit_learn"):
        expected_value = expected_runtime.get(key)
        observed_value = observed_runtime.get(key)
        if not isinstance(expected_value, str) or not expected_value.strip():
            return {"status": "invalid_expected_runtime", "python_patch_warning": False}
        if not isinstance(observed_value, str) or not observed_value.strip():
            return {"status": "invalid_observed_runtime", "python_patch_warning": False}
        if expected_value != observed_value:
            return {"status": "incompatible", "python_patch_warning": False}

    expected_major_minor = expected_runtime.get("python_major_minor")
    observed_major_minor = observed_runtime.get("python_major_minor")
    if not isinstance(expected_major_minor, str) or not expected_major_minor.strip():
        return {"status": "invalid_expected_runtime", "python_patch_warning": False}
    if not isinstance(observed_major_minor, str) or not observed_major_minor.strip():
        return {"status": "invalid_observed_runtime", "python_patch_warning": False}
    if expected_major_minor != observed_major_minor:
        return {"status": "incompatible", "python_patch_warning": False}

    expected_patch = expected_runtime.get("python_patch")
    observed_patch = observed_runtime.get("python_patch")
    python_patch_warning = bool(
        isinstance(expected_patch, str) and isinstance(observed_patch, str) and expected_patch != observed_patch
    )

    # Python major.minor matches exactly and every other dependency matches
    # exactly: compatible, possibly with a non-blocking Python-patch-only
    # warning recorded for private/internal evidence only (S0159/G0002
    # inconsistent_version_warning_policy.python_patch_only_warning_handling).
    return {"status": "compatible", "python_patch_warning": python_patch_warning}


RUNTIME_COMPATIBILITY_DIAGNOSTIC_MAPPING = {
    "incompatible": DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
    "invalid_expected_runtime": DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
    "invalid_observed_runtime": DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
    "stale_bundle_reference": DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
}


def run_preflight_gate(request: Mapping[str, Any] | None, model_root: Path | None = None) -> dict:
    """Steps 1-10. Never imports joblib, never deserializes the model.

    Returns {"manifest", "model_path", "expected_runtime", "observed_runtime",
    "compatibility"} on success. Raises LoadSafeGateError (with both
    diagnostic_code and runtime_compatibility_status set) as soon as any step
    fails, including when compatibility evaluation itself does not resolve
    to "compatible".
    """

    manifest = load_manifest(model_root, request=request)
    model_path = resolve_model_path(manifest, model_root)
    if request is not None:
        validate_request_contract_version(request)
    verify_model_artifact_existence(model_path)
    verify_model_artifact_hash(manifest, model_path)
    verify_model_state_fingerprint(manifest)
    expected_runtime = read_expected_runtime(manifest)
    observed_runtime = observe_isolated_runtime()
    compatibility = evaluate_load_safe_compatibility(
        request=request,
        manifest_bundle_identity=manifest["bundle_identity"],
        expected_runtime=expected_runtime,
        observed_runtime=observed_runtime,
    )

    if compatibility["status"] != "compatible":
        category = (
            "runtime_profile_mismatch"
            if compatibility["status"] in {"stale_bundle_reference", "incompatible"}
            else "runtime_profile_invalid"
        )
        raise LoadSafeGateError(
            "External inference runtime compatibility gate failed.",
            diagnostic_code=RUNTIME_COMPATIBILITY_DIAGNOSTIC_MAPPING.get(
                compatibility["status"], DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE
            ),
            runtime_compatibility_status=compatibility["status"],
            category=category,
        )

    return {
        "manifest": manifest,
        "model_path": model_path,
        "expected_runtime": expected_runtime,
        "observed_runtime": observed_runtime,
        "compatibility": compatibility,
    }


# S0176 release-governed resolver. These definitions intentionally replace
# the legacy bundle-root preflight above while retaining its compatibility,
# loading, prediction, and bounded-result helpers.

def _confined_path(root: Path, parent: Path, reference: str, *, diagnostic_code: str) -> Path:
    if (
        not isinstance(reference, str)
        or not reference
        or "\\" in reference
        or Path(reference).is_absolute()
        or any(part in {"", ".", ".."} for part in reference.split("/"))
    ):
        raise LoadSafeGateError("Governed artifact reference is unsafe.", diagnostic_code=diagnostic_code)
    resolved_root = root.resolve(strict=True)
    candidate = parent.joinpath(*reference.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise LoadSafeGateError("Governed artifact reference is unavailable.", diagnostic_code=diagnostic_code) from exc
    # Reject symlinks at every component, even when their eventual target is
    # still inside the root. Release packaging is immutable and direct.
    current = resolved_root
    try:
        relative = candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise LoadSafeGateError("Governed artifact reference escapes the releases root.", diagnostic_code=diagnostic_code) from exc
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise LoadSafeGateError("Governed artifact reference must not use symlinks.", diagnostic_code=diagnostic_code)
    return resolved


def _release_id_from_request(request: Mapping[str, Any]) -> str:
    identity = request.get("release_identity")
    release_id = identity.get("release_id") if isinstance(identity, Mapping) else None
    if (
        not isinstance(release_id, str)
        or not release_id.startswith("release-")
        or release_id in {"release-", ".", ".."}
        or "/" in release_id
        or "\\" in release_id
        or ".." in release_id
        or Path(release_id).is_absolute()
        or not all(character.isalnum() or character in "._-" for character in release_id)
    ):
        raise LoadSafeGateError(
            "Release identity is invalid.",
            diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
            category="runtime_profile_invalid",
        )
    return release_id


def _artifact_declaration(manifest: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    artifacts = manifest.get("artifacts")
    matches = [item for item in artifacts if isinstance(item, Mapping) and item.get("role") == role] if isinstance(artifacts, list) else []
    if len(matches) != 1:
        raise LoadSafeGateError("Release artifact declaration is invalid.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    declaration = matches[0]
    if declaration.get("hash_algorithm") != "sha256" or not isinstance(declaration.get("hash_value"), str) or len(declaration["hash_value"]) != 64:
        raise LoadSafeGateError("Release artifact hash declaration is invalid.", diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH)
    return declaration


def _load_json(path: Path, *, diagnostic_code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LoadSafeGateError("Governed JSON artifact is unavailable.", diagnostic_code=diagnostic_code) from exc
    if not isinstance(value, dict):
        raise LoadSafeGateError("Governed JSON artifact is invalid.", diagnostic_code=diagnostic_code)
    return value


def _verify_declared_hash(path: Path, declaration: Mapping[str, Any], *, diagnostic_code: str) -> None:
    if _sha256_file(path) != declaration.get("hash_value"):
        raise LoadSafeGateError("Governed artifact hash does not match.", diagnostic_code=diagnostic_code)


def _bundle_error(message: str) -> LoadSafeGateError:
    return LoadSafeGateError(message, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_model_descriptor(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not _nonempty_string(value.get("model_family")) or not _nonempty_string(value.get("display_name")):
        raise _bundle_error("Governed model descriptor is invalid.")
    return {"model_family": value["model_family"], "display_name": value["display_name"]}


def _validate_risk_bands(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or len(value) != 3:
        raise _bundle_error("Governed binary risk bands are invalid.")
    bands: list[Mapping[str, Any]] = []
    expected_ids = ("low", "medium", "high")
    previous_upper = 0.0
    for index, item in enumerate(value):
        lower = item.get("lower_bound") if isinstance(item, Mapping) else None
        upper = item.get("upper_bound") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or item.get("band_id") != expected_ids[index]
            or not isinstance(lower, (int, float)) or isinstance(lower, bool)
            or not isinstance(upper, (int, float)) or isinstance(upper, bool)
            or not math.isfinite(float(lower)) or not math.isfinite(float(upper))
            or float(lower) != previous_upper or not float(lower) < float(upper) <= 1.0
        ):
            raise _bundle_error("Governed binary risk bands are invalid.")
        bands.append({"band_id": expected_ids[index], "lower_bound": float(lower), "upper_bound": float(upper)})
        previous_upper = float(upper)
    if previous_upper != 1.0:
        raise _bundle_error("Governed binary risk bands do not cover the probability range.")
    return tuple(bands)


def _validate_binary_plan(bundle: Mapping[str, Any], common: dict[str, Any]) -> PredictionPlan:
    semantics = bundle.get("result_semantics")
    output = bundle.get("output_schema")
    if (
        not isinstance(semantics, Mapping)
        or semantics.get("schema_version") != "binary-result-semantics.v1"
        or semantics.get("problem_type") != "binary_classification"
        or semantics.get("result_schema_version") != "binary-classification-result.v1"
        or semantics.get("primary_output") != "positive_class_probability"
        or not isinstance(output, Mapping)
        or output.get("probability_output") is not True
    ):
        raise _bundle_error("Governed binary result semantics are invalid.")
    labels = output.get("class_labels")
    positive = semantics.get("positive_class")
    decision = semantics.get("decision")
    interpretation = semantics.get("interpretation")
    threshold = decision.get("threshold") if isinstance(decision, Mapping) else None
    if (
        not isinstance(labels, list) or len(labels) != 2 or len(set(labels)) != 2
        or not all(_nonempty_string(item) for item in labels)
        or not isinstance(positive, Mapping) or not _nonempty_string(positive.get("class_id")) or not _nonempty_string(positive.get("event_label"))
        or positive.get("class_id") not in labels
        or not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0.0 <= float(threshold) <= 1.0
        or not isinstance(interpretation, Mapping) or interpretation.get("preset") != "risk"
    ):
        raise _bundle_error("Governed binary result semantics are invalid.")
    if bundle.get("model_provenance_origin") == "validated_external_fitted_model":
        evidence = bundle.get("external_model_evidence")
        educational = evidence.get("educational_threshold") if isinstance(evidence, Mapping) else None
        if not isinstance(educational, Mapping) or educational.get("value") != threshold:
            raise _bundle_error("External binary threshold evidence disagrees with result semantics.")
    negative = next(label for label in labels if label != positive["class_id"])
    return PredictionPlan(
        result_variant="binary", output_classes=tuple(labels),
        model_descriptor=_validate_model_descriptor(semantics.get("model_descriptor")),
        positive_class={"class_id": positive["class_id"], "event_label": positive["event_label"]},
        negative_class_id=negative, threshold=float(threshold),
        risk_bands=_validate_risk_bands(interpretation.get("bands")), **common,
    )


def _validate_multiclass_plan(bundle: Mapping[str, Any], common: dict[str, Any]) -> PredictionPlan:
    semantics = bundle.get("result_semantics")
    output = bundle.get("output_schema")
    classes = semantics.get("classes") if isinstance(semantics, Mapping) else None
    if (
        not isinstance(semantics, Mapping)
        or semantics.get("schema_version") != "multiclass-result-semantics.v1"
        or semantics.get("problem_type") != "multiclass_classification"
        or semantics.get("result_schema_version") != "multiclass-classification-result.v1"
        or semantics.get("primary_output") != "predicted_class"
        or semantics.get("probability_output") != "class_probabilities"
        or not isinstance(semantics.get("decision"), Mapping) or semantics["decision"].get("strategy") != "argmax"
        or not isinstance(classes, list) or len(classes) < 3
        or not isinstance(output, Mapping) or output.get("prediction_type") != "string" or output.get("probability_output") is not True
    ):
        raise _bundle_error("Governed multiclass result semantics are invalid.")
    normalized_classes: list[Mapping[str, str]] = []
    for item in classes:
        if not isinstance(item, Mapping) or not _nonempty_string(item.get("class_id")) or not _nonempty_string(item.get("display_label")):
            raise _bundle_error("Governed multiclass classes are invalid.")
        normalized_classes.append({"class_id": item["class_id"], "display_label": item["display_label"]})
    class_ids = [item["class_id"] for item in normalized_classes]
    if len(set(class_ids)) != len(class_ids) or output.get("class_labels") != class_ids:
        raise _bundle_error("Governed multiclass class order is inconsistent.")
    if bundle.get("model_provenance_origin") == "validated_external_fitted_model":
        evidence = bundle.get("external_model_evidence")
        classification = evidence.get("classification_evidence") if isinstance(evidence, Mapping) else None
        columns = classification.get("probability_columns") if isinstance(classification, Mapping) else None
        if (
            not isinstance(evidence, Mapping) or "educational_threshold" in evidence or "threshold" in evidence
            or not isinstance(classification, Mapping) or classification.get("problem_type") != "multiclass_classification"
            or classification.get("ordered_class_ids") != class_ids
            or not isinstance(columns, list) or len(columns) != len(class_ids)
            or any(not isinstance(column, Mapping) or column.get("probability_index") != index or column.get("class_id") != class_ids[index] for index, column in enumerate(columns))
            or not isinstance(evidence.get("decision_semantics"), Mapping) or evidence["decision_semantics"].get("strategy") != "argmax"
            or not isinstance(evidence.get("readiness"), Mapping) or evidence["readiness"].get("decision_strategy") != "argmax"
        ):
            raise _bundle_error("External multiclass class evidence is inconsistent.")
    return PredictionPlan(
        result_variant="multiclass", output_classes=tuple(class_ids), multiclass_classes=tuple(normalized_classes),
        model_descriptor=_validate_model_descriptor(semantics.get("model_descriptor")), **common,
    )


def _build_prediction_plan(bundle: Mapping[str, Any], runtime_contract: Mapping[str, Any]) -> PredictionPlan:
    input_schema = bundle.get("input_schema")
    contract_references = bundle.get("contract_references")
    runtime_reference = contract_references.get("runtime_contract") if isinstance(contract_references, Mapping) else None
    features = runtime_contract.get("features")
    feature_order = bundle.get("feature_order")
    if (
        not isinstance(input_schema, Mapping) or input_schema.get("runtime_contract_reference") != "contract_references.runtime_contract"
        or not isinstance(runtime_reference, Mapping) or runtime_contract.get("schema_version") != runtime_reference.get("contract_version")
        or not isinstance(feature_order, list) or not feature_order or not all(_nonempty_string(item) for item in feature_order) or len(set(feature_order)) != len(feature_order)
        or not isinstance(features, list) or not features
    ):
        raise _bundle_error("Bundle input declarations are invalid.")
    required: set[str] = set()
    contract_names: list[str] = []
    for feature in features:
        name = feature.get("name") if isinstance(feature, Mapping) else None
        required_value = feature.get("required", True) if isinstance(feature, Mapping) else None
        if not _nonempty_string(name) or not isinstance(required_value, bool):
            raise _bundle_error("Runtime Contract feature metadata is invalid.")
        contract_names.append(name)
        if required_value:
            required.add(name)
    if len(set(contract_names)) != len(contract_names) or set(feature_order) != set(contract_names):
        raise _bundle_error("Bundle and Runtime Contract feature sets are inconsistent.")
    common = {"feature_order": tuple(feature_order), "required_features": frozenset(required)}
    semantics = bundle.get("result_semantics")
    pair = (semantics.get("schema_version"), semantics.get("problem_type")) if isinstance(semantics, Mapping) else (None, None)
    if pair == ("binary-result-semantics.v1", "binary_classification"):
        return _validate_binary_plan(bundle, common)
    if pair == ("multiclass-result-semantics.v1", "multiclass_classification"):
        return _validate_multiclass_plan(bundle, common)
    raise _bundle_error("Governed result semantics variant is unavailable.")


def load_governed_release(request: Mapping[str, Any], releases_root: Path | None = None) -> dict:
    root = (releases_root or RELEASES_ROOT).resolve(strict=True)
    release_id = _release_id_from_request(request)
    release_dir = _confined_path(root, root, release_id, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    if not release_dir.is_dir():
        raise LoadSafeGateError("Requested release is unavailable.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    manifest_path = _confined_path(root, release_dir, MANIFEST_FILENAME, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    manifest = _load_json(manifest_path, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    request_bundle = request.get("bundle_identity")
    release_identity = manifest.get("release_identity")
    dataset_identity = manifest.get("dataset_identity")
    if not isinstance(request_bundle, Mapping) or not isinstance(release_identity, Mapping) or not isinstance(dataset_identity, Mapping):
        raise LoadSafeGateError("Release identity declarations are invalid.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    if release_identity.get("release_id") != release_id or dataset_identity.get("dataset_slug") != request_bundle.get("dataset_slug"):
        raise LoadSafeGateError("Requested release identity does not match its manifest.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)

    bundle_decl = _artifact_declaration(manifest, "predictive_bundle")
    model_decl = _artifact_declaration(manifest, "model_artifact")
    contract_decl = _artifact_declaration(manifest, "contracts")
    bundle_path = _confined_path(root, release_dir, bundle_decl.get("reference"), diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    model_path = _confined_path(root, release_dir, model_decl.get("reference"), diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE)
    contract_path = _confined_path(root, release_dir, contract_decl.get("reference"), diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    if not bundle_path.is_file() or not model_path.is_file() or not contract_path.is_file():
        raise LoadSafeGateError("Governed release artifact is unavailable.", diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE)
    _verify_declared_hash(bundle_path, bundle_decl, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    bundle = _load_json(bundle_path, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    bundle_identity = bundle.get("bundle_identity")
    dataset_context = bundle.get("dataset_context")
    bundle_model = bundle.get("model_artifact")
    if (
        not isinstance(bundle_identity, Mapping)
        or not isinstance(dataset_context, Mapping)
        or not isinstance(bundle_model, Mapping)
        or bundle_identity.get("bundle_id") != request_bundle.get("bundle_id")
        or dataset_context.get("dataset_slug") != request_bundle.get("dataset_slug")
        or bundle_model.get("path") != model_decl.get("reference")
        or bundle_model.get("sha256") != model_decl.get("hash_value")
    ):
        raise LoadSafeGateError("Predictive bundle identity is stale or inconsistent.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE, runtime_compatibility_status="stale_bundle_reference")
    _verify_declared_hash(contract_path, contract_decl, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    runtime_contract = _load_json(contract_path, diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    prediction_plan = _build_prediction_plan(bundle, runtime_contract)
    _verify_declared_hash(model_path, model_decl, diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH)

    return {
        "manifest": manifest,
        "bundle": bundle,
        "runtime_contract": runtime_contract,
        "model_path": model_path,
        "prediction_plan": prediction_plan,
    }


def check_releases_root_ready(releases_root: Path | None = None) -> None:
    root = (releases_root or RELEASES_ROOT).resolve(strict=True)
    if not root.is_dir():
        raise LoadSafeGateError("Releases root is unavailable.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    manifests = [path for path in root.glob(f"*/{MANIFEST_FILENAME}") if path.is_file() and not path.is_symlink()]
    if not manifests:
        raise LoadSafeGateError("No governed releases are packaged.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    compatibility = evaluate_load_safe_compatibility(
        request=None,
        manifest_bundle_identity={},
        expected_runtime=PACKAGED_RUNTIME,
        observed_runtime=observe_isolated_runtime(),
    )
    if compatibility["status"] != "compatible":
        raise LoadSafeGateError(
            "Packaged runtime is incompatible.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
            runtime_compatibility_status=compatibility["status"],
        )


def run_preflight_gate(request: Mapping[str, Any], model_root: Path | None = None) -> dict:
    """Validate release topology, hashes and exact runtime before deserialization."""
    validate_request_contract_version(request)
    governed = load_governed_release(request, model_root)
    expected_runtime = request.get("expected_runtime")
    if not isinstance(expected_runtime, Mapping):
        raise LoadSafeGateError("Expected runtime is invalid.", diagnostic_code=DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE)
    observed_runtime = observe_isolated_runtime()
    compatibility = evaluate_load_safe_compatibility(
        request=None,
        manifest_bundle_identity=request["bundle_identity"],
        expected_runtime=expected_runtime,
        observed_runtime=observed_runtime,
    )
    if compatibility["status"] != "compatible":
        raise LoadSafeGateError(
            "External inference runtime compatibility gate failed.",
            diagnostic_code=RUNTIME_COMPATIBILITY_DIAGNOSTIC_MAPPING.get(compatibility["status"], DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE),
            runtime_compatibility_status=compatibility["status"],
            category="runtime_profile_mismatch",
        )
    governed.update({"expected_runtime": dict(expected_runtime), "observed_runtime": observed_runtime, "compatibility": compatibility})
    return governed


# --- Steps 11-13: block-before-import, allowlisted loader, warning capture ---


def invoke_allowlisted_loader(model_path: Path) -> Any:
    try:
        import joblib
    except ImportError as exc:
        raise LoadSafeGateError(
            "Isolated runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc
    try:
        from sklearn.exceptions import InconsistentVersionWarning
    except ImportError as exc:
        raise LoadSafeGateError(
            "Isolated runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            model = joblib.load(model_path)
        except Exception as exc:  # pragma: no cover - message is intentionally generic
            raise LoadSafeGateError(
                "External model artifact could not be loaded.",
                diagnostic_code=DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
            ) from exc

        # S0159/G0002 inconsistent_version_warning_policy: never silently
        # ignored, never exposed publicly -- converted to a controlled
        # deserialization compatibility failure.
        for warning in caught:
            if issubclass(warning.category, InconsistentVersionWarning):
                raise LoadSafeGateError(
                    "External model artifact deserialization is incompatible with the isolated runtime.",
                    diagnostic_code=DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
                )

    return model


# --- Step 14: bounded prediction execution + result validation ---


def _resolve_model_classes(model: Any) -> list[Any]:
    classes = getattr(model, "classes_", None)
    if classes is None:
        steps = getattr(model, "steps", None)
        if isinstance(steps, list) and steps:
            final_estimator = steps[-1][1]
            classes = getattr(final_estimator, "classes_", None)
    if classes is None:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )
    return list(classes)


def _normalize_class_id(value: Any) -> str:
    return str(value).strip().lower()


def _resolve_band(probability: float, bands: tuple[Mapping[str, Any], ...]) -> str:
    for band in bands:
        if band["lower_bound"] <= probability < band["upper_bound"] or (
            band["upper_bound"] == 1.0 and probability == 1.0
        ):
            return band["band_id"]
    raise LoadSafeGateError(
        "Prediction execution failed.",
        diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
    )


def _validate_probabilities(raw_row: Any, expected_count: int) -> list[float]:
    try:
        row = list(raw_row)
    except TypeError as exc:
        raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED) from exc
    if expected_count < 2 or len(row) != expected_count:
        raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
    probabilities: list[float] = []
    for value in row:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
        probabilities.append(numeric)
    if abs(sum(probabilities) - 1.0) > _PROBABILITY_SUM_TOLERANCE:
        raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
    return probabilities


def execute_prediction(model: Any, feature_payload: Mapping[str, Any], plan: PredictionPlan) -> dict:
    try:
        import pandas as pd
    except ImportError as exc:
        raise LoadSafeGateError(
            "Isolated runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    if set(feature_payload) - set(plan.feature_order):
        raise LoadSafeGateError(
            "Request payload contains an undeclared feature.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT,
        )
    row: dict[str, Any] = {}
    for feature_name in plan.feature_order:
        if feature_name in feature_payload:
            row[feature_name] = feature_payload[feature_name]
        elif feature_name in plan.required_features:
            raise LoadSafeGateError(
                "Request payload is missing a required feature.",
                diagnostic_code=DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT,
            )
        else:
            row[feature_name] = float("nan")
    frame = pd.DataFrame([row], columns=list(plan.feature_order))

    predict = getattr(model, "predict", None)
    predict_proba = getattr(model, "predict_proba", None)
    if not callable(predict) or not callable(predict_proba):
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    try:
        raw_prediction = predict(frame)
        raw_proba = predict_proba(frame)
    except Exception as exc:  # pragma: no cover - message is intentionally generic
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        ) from exc

    try:
        predicted_values = list(raw_prediction)
        proba_rows = [list(item) for item in raw_proba]
    except TypeError as exc:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        ) from exc

    if len(predicted_values) != 1 or len(proba_rows) != 1:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    model_classes = _resolve_model_classes(model)
    class_probabilities = _validate_probabilities(proba_rows[0], len(plan.output_classes))

    if plan.result_variant == "multiclass":
        actual_classes = [str(value).strip() for value in model_classes]
        if (
            len(actual_classes) != len(plan.output_classes)
            or any(not value for value in actual_classes)
            or len(set(actual_classes)) != len(actual_classes)
            or tuple(actual_classes) != plan.output_classes
        ):
            raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
        argmax_index = max(range(len(class_probabilities)), key=class_probabilities.__getitem__)
        predicted_class_id = str(predicted_values[0]).strip()
        if predicted_class_id != plan.output_classes[argmax_index]:
            raise LoadSafeGateError("Prediction execution failed.", diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED)
        result = {
            "schema_version": "multiclass-classification-result.v1",
            "problem_type": "multiclass_classification",
            "predicted_class": dict(plan.multiclass_classes[argmax_index]),
            "class_probabilities": [
                {**dict(class_metadata), "probability": class_probabilities[index]}
                for index, class_metadata in enumerate(plan.multiclass_classes)
            ],
            "decision": {"strategy": "argmax"},
            "model_descriptor": dict(plan.model_descriptor),
        }
        validate_bounded_prediction_result(result)
        return result

    normalized_model_classes = [_normalize_class_id(value) for value in model_classes]
    normalized_governed_classes = [_normalize_class_id(value) for value in plan.output_classes]
    if len(model_classes) != 2 or len(set(normalized_model_classes)) != 2 or set(normalized_model_classes) != set(normalized_governed_classes):
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )
    assert plan.positive_class is not None and plan.negative_class_id is not None and plan.threshold is not None
    positive_normalized = _normalize_class_id(plan.positive_class["class_id"])
    positive_index = normalized_model_classes.index(positive_normalized)
    positive_class_probability = class_probabilities[positive_index]
    predicted_positive = positive_class_probability >= plan.threshold
    predicted_class_id = plan.positive_class["class_id"] if predicted_positive else plan.negative_class_id
    band_id = _resolve_band(positive_class_probability, plan.risk_bands)

    result = {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": predicted_class_id},
        "positive_class": dict(plan.positive_class),
        "positive_class_probability": positive_class_probability,
        "class_probabilities": [
            {"class_id": str(model_classes[0]), "probability": class_probabilities[0]},
            {"class_id": str(model_classes[1]), "probability": class_probabilities[1]},
        ],
        "decision": {
            "threshold": plan.threshold,
            "predicted_positive": bool(predicted_positive),
        },
        "interpretation": {
            "preset": "risk",
            "band_id": band_id,
            "bands": [dict(band) for band in plan.risk_bands],
        },
        "model_descriptor": dict(plan.model_descriptor),
    }

    validate_bounded_prediction_result(result)
    return result


def validate_bounded_prediction_result(result: Mapping[str, Any]) -> None:
    import jsonschema

    try:
        schema = _MULTICLASS_CLASSIFICATION_RESULT_SCHEMA if result.get("problem_type") == "multiclass_classification" else _BINARY_CLASSIFICATION_RESULT_SCHEMA
        jsonschema.validate(result, schema)
    except jsonschema.ValidationError as exc:
        raise LoadSafeGateError(
            "Bounded prediction result failed schema validation.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        ) from exc


def execute_governed_external_prediction(request: Mapping[str, Any]) -> dict:
    """Runs the full fourteen-step gate for one POST /predict call."""

    preflight = run_preflight_gate(request)
    try:
        model = invoke_allowlisted_loader(preflight["model_path"])
        feature_payload = request.get("feature_payload")
        if not isinstance(feature_payload, dict):
            raise LoadSafeGateError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        return execute_prediction(model, feature_payload, preflight["prediction_plan"])
    except LoadSafeGateError as exc:
        # Steps 11-14 only ever run after the preflight gate (steps 1-10)
        # already established "compatible" -- a failure here is never a
        # compatibility failure, so backfill the status for evidence/response
        # purposes rather than leaving it unset.
        if exc.runtime_compatibility_status is None:
            exc.runtime_compatibility_status = preflight["compatibility"]["status"]
        raise
