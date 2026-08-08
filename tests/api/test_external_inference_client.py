"""S0161: coverage for api/external_inference_client.py -- the sole HTTP
client from the Atlas api service to the isolated external-inference
service. Mocks only the network boundary (urllib.request.urlopen); never
mocks jsonschema/runtime.inference validation itself.
"""

import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import external_inference_client as client  # noqa: E402
from runtime.inference import InferenceRuntimeError  # noqa: E402

_RELEASE_ID = "release-20260726t200101z"
_BUNDLE_IDENTITY = {"bundle_id": "bundle-test", "dataset_slug": "telco-customer-churn"}
_RUNTIME_PROFILE = {
    "required_consumer_runtime": {
        "python_major_minor": "3.11",
        "dependencies": {"joblib": "1.5.3", "pandas": "3.0.3", "scikit_learn": "1.9.0"},
    }
}


def _execute(feature_payload):
    return client.execute_external_inference(
        feature_payload,
        release_id=_RELEASE_ID,
        bundle_identity=_BUNDLE_IDENTITY,
        runtime_profile=_RUNTIME_PROFILE,
    )


def _valid_result() -> dict:
    return {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": "No"},
        "positive_class": {"class_id": "Yes", "event_label": "Churn"},
        "positive_class_probability": 0.2,
        "class_probabilities": [
            {"class_id": "No", "probability": 0.8},
            {"class_id": "Yes", "probability": 0.2},
        ],
        "decision": {"threshold": 0.2577809673219062, "predicted_positive": False},
        "interpretation": {
            "preset": "risk",
            "band_id": "low",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "External Telco Gradient Boosting"},
    }


def _install_urlopen(monkeypatch, *, response_body: bytes | None = None, raises: Exception | None = None):
    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _fake_urlopen(request, timeout=None):
        if raises is not None:
            raise raises
        return _FakeResponse(response_body)

    monkeypatch.setattr(client.urllib.request, "urlopen", _fake_urlopen)


def test_request_is_constructed_only_from_atlas_controlled_identity(monkeypatch):
    captured = {}

    class _FakeResponse:
        def read(self):
            return json.dumps(
                {
                    "contract_version": "external_inference_result.v1",
                    "status": "ok",
                    "runtime_compatibility_status": "compatible",
                    "diagnostic_code": None,
                    "result": _valid_result(),
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(client.urllib.request, "urlopen", _fake_urlopen)

    feature_payload = {"MonthlyCharges": 95.0, "TotalCharges": 950.0}
    # A caller-supplied filesystem path/loader name in the feature payload
    # itself is not something this client can reject (it only forwards the
    # already-validated feature payload it's given), but the constructed
    # wire request must never surface anything beyond the fixed contract
    # fields -- proven below.
    result = _execute(feature_payload)

    assert result == _valid_result()
    assert captured["url"] == "http://external-inference:8100/predict"
    body = captured["body"]
    assert set(body.keys()) == {"contract_version", "release_identity", "bundle_identity", "expected_runtime", "feature_payload"}
    assert body["contract_version"] == "external_inference_request.v1"
    assert body["release_identity"] == {"release_id": _RELEASE_ID}
    assert body["bundle_identity"] == _BUNDLE_IDENTITY
    assert body["feature_payload"] == feature_payload
    assert captured["timeout"] == client._DEFAULT_TIMEOUT_SECONDS


def test_connection_failure_maps_to_runtime_dependency_unavailable(monkeypatch):
    _install_urlopen(monkeypatch, raises=urllib.error.URLError("connection refused"))

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == client.DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE
        assert "connection refused" not in str(exc)


def test_timeout_maps_to_runtime_dependency_unavailable(monkeypatch):
    _install_urlopen(monkeypatch, raises=TimeoutError("timed out"))

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == client.DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE


def test_malformed_json_response_maps_to_result_validation_failed(monkeypatch):
    _install_urlopen(monkeypatch, response_body=b"not json")

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == client.DIAGNOSTIC_RESULT_VALIDATION_FAILED


def test_failed_status_forwards_the_isolated_services_own_diagnostic_code(monkeypatch):
    _install_urlopen(
        monkeypatch,
        response_body=json.dumps(
            {
                "contract_version": "external_inference_result.v1",
                "status": "failed",
                "runtime_compatibility_status": "incompatible",
                "diagnostic_code": "RUNTIME_DEPENDENCY_UNAVAILABLE",
                "result": None,
            }
        ).encode("utf-8"),
    )

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == "RUNTIME_DEPENDENCY_UNAVAILABLE"


def test_unrecognized_diagnostic_code_is_rejected(monkeypatch):
    _install_urlopen(
        monkeypatch,
        response_body=json.dumps(
            {
                "contract_version": "external_inference_result.v1",
                "status": "failed",
                "runtime_compatibility_status": "incompatible",
                "diagnostic_code": "A_NEW_MADE_UP_CODE",
                "result": None,
            }
        ).encode("utf-8"),
    )

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == client.DIAGNOSTIC_RESULT_VALIDATION_FAILED


def test_ok_status_with_invalid_result_shape_is_rejected(monkeypatch):
    _install_urlopen(
        monkeypatch,
        response_body=json.dumps(
            {
                "contract_version": "external_inference_result.v1",
                "status": "ok",
                "runtime_compatibility_status": "compatible",
                "diagnostic_code": None,
                "result": {"not": "a valid binary classification result"},
            }
        ).encode("utf-8"),
    )

    try:
        _execute({})
        raise AssertionError("expected InferenceRuntimeError")
    except InferenceRuntimeError as exc:
        # runtime.inference.validate_binary_classification_result raises its
        # own BundleValidationError (not ExternalInferenceClientError) here
        # -- both share the InferenceRuntimeError base api/main.py catches.
        assert exc.diagnostic_code == client.DIAGNOSTIC_RESULT_VALIDATION_FAILED


def test_ok_status_without_compatible_runtime_status_is_rejected(monkeypatch):
    _install_urlopen(
        monkeypatch,
        response_body=json.dumps(
            {
                "contract_version": "external_inference_result.v1",
                "status": "ok",
                "runtime_compatibility_status": "incompatible",
                "diagnostic_code": None,
                "result": _valid_result(),
            }
        ).encode("utf-8"),
    )

    try:
        _execute({})
        raise AssertionError("expected ExternalInferenceClientError")
    except client.ExternalInferenceClientError as exc:
        assert exc.diagnostic_code == client.DIAGNOSTIC_RESULT_VALIDATION_FAILED


def test_api_main_delegates_to_the_external_client_for_the_isolated_loader_strategy(monkeypatch):
    import main as api_main

    calls = []

    def _fake_execute(feature_payload, **kwargs):
        calls.append((feature_payload, kwargs))
        return _valid_result()

    monkeypatch.setattr(api_main, "execute_external_inference", _fake_execute)
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda active_release: {"features": []},
    )
    monkeypatch.setattr(
        api_main,
        "validate_and_normalize_payload",
        lambda payload, runtime_contract: SimpleNamespace(failures=[], normalized_payload={"MonthlyCharges": 10.0}),
    )
    monkeypatch.setattr(
        api_main,
        "_read_active_release_manifest",
        lambda active_release: (
            "unused-release-dir",
            {"runtime_execution": {"loader_strategy": api_main.EXTERNAL_INFERENCE_LOADER_STRATEGY}},
        ),
    )

    response = api_main._execute_via_external_inference_service(
        "telco-customer-churn",
        "release-controlled",
        {"MonthlyCharges": 10.0},
        bundle_identity=_BUNDLE_IDENTITY,
        runtime_profile=_RUNTIME_PROFILE,
        include_runtime_diagnostic=False,
    )

    assert response == {"dataset_slug": "telco-customer-churn", "result": _valid_result()}
    assert calls[0][0] == {"MonthlyCharges": 10.0}
    assert calls[0][1]["release_id"] == "release-controlled"
