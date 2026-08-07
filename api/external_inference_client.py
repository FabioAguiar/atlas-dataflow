"""Sole private HTTP client from the Atlas api service to the isolated
external-inference service (http://external-inference:8100).

Constructs requests only from Atlas-controlled bundle/runtime identity
(module-level constants below, mirroring the sealed S0158/G0004, S0159/G0002
and S0160/G0001 values -- this image never mounts external-models/, so these
values are embedded here rather than read from that directory) plus an
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

# Mirrors external-models/telco-customer-churn/manifest.json's
# bundle_identity/expected_runtime -- duplicated deliberately, since the api
# image never mounts or copies external-models/ (only the isolated service's
# own image does). Both are independently traceable to the same sealed
# S0158/G0004 + S0159/G0002 + S0160/G0001 values.
_BUNDLE_IDENTITY = {
    "bundle_id": "telco-customer-churn-external-inference-bundle",
    "dataset_slug": "telco-customer-churn",
}
_EXPECTED_RUNTIME = {
    "python_major_minor": "3.11",
    "joblib": "1.5.3",
    "pandas": "3.0.3",
    "scikit_learn": "1.9.0",
}


class ExternalInferenceClientError(InferenceRuntimeError):
    """Raised when the isolated external-inference service call fails.

    Always carries a diagnostic_code drawn from the closed
    RUNTIME_DIAGNOSTIC_CODES vocabulary -- never a new code, never raw
    package/version/path/traceback detail.
    """


def _build_request_payload(feature_payload: Mapping[str, Any]) -> dict:
    return {
        "contract_version": _REQUEST_CONTRACT_VERSION,
        "bundle_identity": dict(_BUNDLE_IDENTITY),
        "expected_runtime": dict(_EXPECTED_RUNTIME),
        "feature_payload": dict(feature_payload),
    }


def execute_external_inference(
    feature_payload: Mapping[str, Any],
    *,
    base_url: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Calls the isolated service's POST /predict and returns its validated result.

    Returns the binary-classification-result.v1 object on success. Raises
    ExternalInferenceClientError on any failure -- connection/timeout,
    malformed response, or a runtime-incompatible/failed result reported by
    the isolated service itself.
    """

    request_body = _build_request_payload(feature_payload)
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
