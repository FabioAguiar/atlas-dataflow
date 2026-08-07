"""Load-safe gate and trusted execution for the isolated external-inference service.

Implements the S0159/G0002 fourteen-step load-safe gate order for the single
bounded external Telco Customer Churn model selected by S0158/G0004 and
named/wired by S0160/G0001. This module never accepts a caller-selected
filesystem path, loader/module name, dependency override, or hash bypass --
the on-disk manifest under the hardcoded MODEL_ROOT is the only source of
truth for model identity and expected runtime, cross-checked against sealed
S0158/S0160 reference values.

Deliberately self-contained: this image does not share code with the Atlas
api image (different Python runtime, different dependency pins), so the
binary-classification-result shaping logic here is a bounded, single-model
reimplementation rather than an import from runtime/inference.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any, Mapping

MODEL_ROOT = Path("/app/external-models")
BUNDLE_DIRECTORY_NAME = "telco-customer-churn"
MANIFEST_FILENAME = "manifest.json"

MANIFEST_CONTRACT_VERSION = "external_inference_model_manifest.v1"
REQUEST_CONTRACT_VERSION = "external_inference_request.v1"

# S0158/G0004 + S0160/G0001 sealed identity -- an independent, hardcoded
# cross-check that never trusts the on-disk manifest alone.
SEALED_MODEL_BYTE_SHA256 = "48da4c7aa56d5d08090e808f551f555740d18e791af39c4c3f373467ec296b8c"
SEALED_MODEL_STATE_FINGERPRINT = "c9328311e2ed5953b5aab1abc17b439ff7e90c7c8e4f15b6a31598d05dc771e6"

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

_FEATURE_ORDER = (
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
)

_RISK_BANDS = (
    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
)
_POSITIVE_CLASS = {"class_id": "Yes", "event_label": "Churn"}
_NEGATIVE_CLASS_ID = "No"
# Sourced from the trusted external producer's own declared, explicitly
# non-operational "educational_threshold" (inference-bundle.json,
# threshold_scenario "minimum_recall_0_80", selected on the validation
# partition) -- never fabricated, never presented as an operational
# decision policy.
_DECISION_THRESHOLD = 0.2577809673219062
_MODEL_DESCRIPTOR = {
    "model_family": "gradient_boosting",
    "display_name": "External Telco Gradient Boosting (HistGradientBoostingClassifier)",
}
_PROBABILITY_SUM_TOLERANCE = 1e-6

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


class LoadSafeGateError(Exception):
    """Carries a closed diagnostic code and (when applicable) a runtime_compatibility_status."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_code: str | None = None,
        runtime_compatibility_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.runtime_compatibility_status = runtime_compatibility_status


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Step 1-2: resolve bundle identity, validate trusted source declaration ---


def load_manifest(model_root: Path | None = None) -> dict:
    manifest_path = (model_root if model_root is not None else MODEL_ROOT) / BUNDLE_DIRECTORY_NAME / MANIFEST_FILENAME
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

    bundle_root = (model_root / BUNDLE_DIRECTORY_NAME).resolve(strict=False)
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
    if expected_hash != SEALED_MODEL_BYTE_SHA256:
        raise LoadSafeGateError(
            "External model manifest hash declaration does not match the sealed reference.",
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
    if fingerprint != SEALED_MODEL_STATE_FINGERPRINT:
        raise LoadSafeGateError(
            "External model manifest state fingerprint does not match the sealed reference.",
            diagnostic_code=DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
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

    manifest = load_manifest(model_root)
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
        raise LoadSafeGateError(
            "External inference runtime compatibility gate failed.",
            diagnostic_code=RUNTIME_COMPATIBILITY_DIAGNOSTIC_MAPPING.get(
                compatibility["status"], DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE
            ),
            runtime_compatibility_status=compatibility["status"],
        )

    return {
        "manifest": manifest,
        "model_path": model_path,
        "expected_runtime": expected_runtime,
        "observed_runtime": observed_runtime,
        "compatibility": compatibility,
    }


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


def _resolve_band(probability: float) -> str:
    for band in _RISK_BANDS:
        if band["lower_bound"] <= probability < band["upper_bound"] or (
            band["upper_bound"] == 1.0 and probability == 1.0
        ):
            return band["band_id"]
    raise LoadSafeGateError(
        "Prediction execution failed.",
        diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
    )


def execute_prediction(model: Any, feature_payload: Mapping[str, Any]) -> dict:
    try:
        import pandas as pd
    except ImportError as exc:
        raise LoadSafeGateError(
            "Isolated runtime dependency is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
        ) from exc

    row: dict[str, Any] = {}
    for feature_name in _FEATURE_ORDER:
        if feature_name not in feature_payload:
            raise LoadSafeGateError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        row[feature_name] = feature_payload[feature_name]
    frame = pd.DataFrame([row], columns=list(_FEATURE_ORDER))

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

    if len(predicted_values) != 1 or len(proba_rows) != 1 or len(proba_rows[0]) != 2:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    model_classes = _resolve_model_classes(model)
    unique_model_classes = list(dict.fromkeys(_normalize_class_id(c) for c in model_classes))
    if len(unique_model_classes) != 2:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    positive_normalized = _normalize_class_id(_POSITIVE_CLASS["class_id"])
    if positive_normalized not in unique_model_classes:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )
    positive_index = [_normalize_class_id(c) for c in model_classes].index(positive_normalized)

    proba_row = proba_rows[0]
    class_probabilities: list[float] = []
    for value in proba_row:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise LoadSafeGateError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise LoadSafeGateError(
                "Prediction execution failed.",
                diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
            )
        class_probabilities.append(numeric)
    if abs(sum(class_probabilities) - 1.0) > _PROBABILITY_SUM_TOLERANCE:
        raise LoadSafeGateError(
            "Prediction execution failed.",
            diagnostic_code=DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
        )

    positive_class_probability = class_probabilities[positive_index]
    predicted_positive = positive_class_probability >= _DECISION_THRESHOLD
    predicted_class_id = _POSITIVE_CLASS["class_id"] if predicted_positive else _NEGATIVE_CLASS_ID
    band_id = _resolve_band(positive_class_probability)

    result = {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": predicted_class_id},
        "positive_class": dict(_POSITIVE_CLASS),
        "positive_class_probability": positive_class_probability,
        "class_probabilities": [
            {"class_id": str(model_classes[0]), "probability": class_probabilities[0]},
            {"class_id": str(model_classes[1]), "probability": class_probabilities[1]},
        ],
        "decision": {
            "threshold": _DECISION_THRESHOLD,
            "predicted_positive": bool(predicted_positive),
        },
        "interpretation": {
            "preset": "risk",
            "band_id": band_id,
            "bands": [dict(band) for band in _RISK_BANDS],
        },
        "model_descriptor": dict(_MODEL_DESCRIPTOR),
    }

    validate_bounded_prediction_result(result)
    return result


def validate_bounded_prediction_result(result: Mapping[str, Any]) -> None:
    import jsonschema

    try:
        jsonschema.validate(result, _BINARY_CLASSIFICATION_RESULT_SCHEMA)
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
        return execute_prediction(model, feature_payload)
    except LoadSafeGateError as exc:
        # Steps 11-14 only ever run after the preflight gate (steps 1-10)
        # already established "compatible" -- a failure here is never a
        # compatibility failure, so backfill the status for evidence/response
        # purposes rather than leaving it unset.
        if exc.runtime_compatibility_status is None:
            exc.runtime_compatibility_status = preflight["compatibility"]["status"]
        raise
