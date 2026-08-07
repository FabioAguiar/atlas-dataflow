"""Sole private HTTP client from the Atlas api service to the isolated
external-inference service (http://external-inference:8100).

Constructs requests from Atlas-controlled logical bundle identity and the
governed isolated runtime profile in the inference bundle, plus an
already-validated, normalized feature payload supplied by the caller. Uses
only the standard library for HTTP: api/pyproject.toml is the shared API
dependency manifest and must not be edited to accommodate the external
model (S0161 desired_change), so no httpx/requests dependency is available
here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping

from runtime.inference import (
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
    InferenceRuntimeError,
    RUNTIME_DIAGNOSTIC_CODES,
    validate_binary_classification_result,
)

# S0160/G0001 naming_vocabulary: the manifest-declared loader-strategy value
# api/main.py checks for before delegating to this client, instead of the
# local runtime/inference.py loader path.
EXTERNAL_INFERENCE_LOADER_STRATEGY = "isolated_external_inference_service"

_REQUEST_CONTRACT_VERSION = "external_inference_request.v1"
_DEFAULT_BASE_URL = "http://external-inference:8100"
_DEFAULT_TIMEOUT_SECONDS = 5.0

class ExternalInferenceClientError(InferenceRuntimeError):
    """Raised when the isolated external-inference service call fails.

    Always carries a diagnostic_code drawn from the closed
    RUNTIME_DIAGNOSTIC_CODES vocabulary -- never a new code, never raw
    package/version/path/traceback detail.
    """

    def __init__(self, message: str, *, diagnostic_code: str | None, category: str | None = None) -> None:
        super().__init__(message, diagnostic_code=diagnostic_code)
        self.category = category


def _build_request_payload(
    feature_payload: Mapping[str, Any],
    *,
    bundle_identity: Mapping[str, Any],
    runtime_profile: Mapping[str, Any],
) -> dict:
    required_runtime = runtime_profile.get("required_consumer_runtime")
    dependencies = required_runtime.get("dependencies") if isinstance(required_runtime, Mapping) else None
    if (
        not isinstance(bundle_identity.get("bundle_id"), str)
        or not isinstance(bundle_identity.get("dataset_slug"), str)
        or not isinstance(required_runtime, Mapping)
        or not isinstance(dependencies, Mapping)
    ):
        raise ExternalInferenceClientError(
            "Isolated runtime profile is invalid.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
            category="runtime_profile_invalid",
        )

    expected_runtime = {
        "python_major_minor": required_runtime.get("python_major_minor"),
        "joblib": dependencies.get("joblib"),
        "pandas": dependencies.get("pandas"),
        "scikit_learn": dependencies.get("scikit_learn"),
    }
    if "python_patch" in required_runtime:
        expected_runtime["python_patch"] = required_runtime["python_patch"]

    return {
        "contract_version": _REQUEST_CONTRACT_VERSION,
        "bundle_identity": {
            "bundle_id": bundle_identity["bundle_id"],
            "dataset_slug": bundle_identity["dataset_slug"],
        },
        "expected_runtime": expected_runtime,
        "feature_payload": dict(feature_payload),
    }


def execute_external_inference(
    feature_payload: Mapping[str, Any],
    *,
    bundle_identity: Mapping[str, Any],
    runtime_profile: Mapping[str, Any],
    base_url: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Calls the isolated service's POST /predict and returns its validated result.

    Returns the binary-classification-result.v1 object on success. Raises
    ExternalInferenceClientError on any failure -- connection/timeout,
    malformed response, or a runtime-incompatible/failed result reported by
    the isolated service itself.
    """

    request_body = _build_request_payload(
        feature_payload,
        bundle_identity=bundle_identity,
        runtime_profile=runtime_profile,
    )
    url = f"{(base_url or _DEFAULT_BASE_URL).rstrip('/')}/predict"

    http_request = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            raw_body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExternalInferenceClientError(
            "External inference service is unavailable.",
            diagnostic_code=DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
            category="isolated_runtime_unavailable_or_failed",
        ) from exc

    try:
        parsed = json.loads(raw_body)
    except ValueError as exc:
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        ) from exc

    return _interpret_response(parsed)


def _interpret_response(parsed: Any) -> dict:
    if not isinstance(parsed, Mapping) or parsed.get("contract_version") != "external_inference_result.v1":
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    diagnostic_code = parsed.get("diagnostic_code")
    if diagnostic_code is not None and diagnostic_code not in RUNTIME_DIAGNOSTIC_CODES:
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    status = parsed.get("status")
    if status == "failed":
        # S0160/G0001 naming_vocabulary.failure_diagnostic_mapping: the
        # isolated service's own diagnostic_code is already drawn from the
        # closed RUNTIME_DIAGNOSTIC_CODES vocabulary -- forwarded as-is,
        # never re-derived or re-mapped here.
        raise ExternalInferenceClientError(
            "External inference execution failed.",
            diagnostic_code=diagnostic_code,
            category="isolated_runtime_unavailable_or_failed",
        )
    if status != "ok":
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    if parsed.get("runtime_compatibility_status") != "compatible":
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    result = parsed.get("result")
    if not isinstance(result, Mapping):
        raise ExternalInferenceClientError(
            "External inference service response was invalid.",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    # Defense-in-depth: the isolated service already validates this shape
    # before responding; re-validate here against the same Atlas schema
    # before trusting the result any further.
    result_dict = dict(result)
    validate_binary_classification_result(result_dict)
    return result_dict
