"""S0161: FastAPI-router-level coverage for external-inference/service_app.py.

Exercises the real ASGI app directly (no httpx/TestClient dependency --
neither api/pyproject.toml nor external-inference/pyproject.toml pins one),
mirroring tests/api/test_admin_live_preview_inference.py's _post_json
convention for this repository.
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

EXTERNAL_INFERENCE_DIR = Path(__file__).resolve().parent.parent / "external-inference"
if str(EXTERNAL_INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_INFERENCE_DIR))

import runtime_loader as rl  # noqa: E402
import service_app  # noqa: E402


_FEATURE_ORDER = list(rl._FEATURE_ORDER)
_BUNDLE_ID = "telco-customer-churn-external-inference-bundle-test"


def _train_fixture_pipeline() -> Pipeline:
    rows = []
    labels = []
    for monthly, total, label in [
        (95.0, 950.0, "Yes"),
        (98.0, 980.0, "Yes"),
        (90.0, 900.0, "Yes"),
        (92.0, 920.0, "Yes"),
        (20.0, 200.0, "No"),
        (22.0, 220.0, "No"),
        (18.0, 180.0, "No"),
        (25.0, 250.0, "No"),
        (19.0, 190.0, "No"),
        (21.0, 210.0, "No"),
    ]:
        row = {name: "placeholder" for name in _FEATURE_ORDER}
        row["MonthlyCharges"] = monthly
        row["TotalCharges"] = total
        row["SeniorCitizen"] = 0
        row["tenure"] = 1
        rows.append(row)
        labels.append(label)

    frame = pd.DataFrame(rows, columns=_FEATURE_ORDER)
    preprocessor = ColumnTransformer(
        [("numeric", "passthrough", ["MonthlyCharges", "TotalCharges"])],
        remainder="drop",
    )
    pipeline = Pipeline([("pre", preprocessor), ("clf", LogisticRegression())])
    pipeline.fit(frame, labels)
    return pipeline


def _feature_payload() -> dict:
    return {
        "gender": "Female",
        "SeniorCitizen": 0,
        "Partner": "Yes",
        "Dependents": "No",
        "tenure": 12,
        "PhoneService": "Yes",
        "MultipleLines": "No",
        "InternetService": "DSL",
        "OnlineSecurity": "No",
        "OnlineBackup": "Yes",
        "DeviceProtection": "No",
        "TechSupport": "No",
        "StreamingTV": "No",
        "StreamingMovies": "No",
        "Contract": "Month-to-month",
        "PaperlessBilling": "Yes",
        "PaymentMethod": "Electronic check",
        "MonthlyCharges": 95.0,
        "TotalCharges": 950.0,
    }


def _write_fixture_bundle(tmp_path: Path, monkeypatch) -> None:
    bundle_dir = tmp_path / rl.BUNDLE_DIRECTORY_NAME
    models_dir = bundle_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    model_path = models_dir / "model.joblib"
    joblib.dump(_train_fixture_pipeline(), model_path)
    byte_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

    manifest = {
        "artifact_type": "external_inference_model_manifest",
        "contract_version": rl.MANIFEST_CONTRACT_VERSION,
        "dataset_slug": "telco-customer-churn",
        "bundle_identity": {"bundle_id": _BUNDLE_ID, "dataset_slug": "telco-customer-churn"},
        "model_artifact": {
            "relative_path": "models/model.joblib",
            "byte_sha256": byte_sha256,
            "model_state_fingerprint": "f" * 64,
        },
        "expected_runtime": {
            "python_major_minor": "3.11",
            "python_patch": "15",
            "joblib": "1.5.3",
            "pandas": "3.0.3",
            "scikit_learn": "1.9.0",
        },
        "trusted_source": {"producer_repository": "dataset-study-telco-customer-churn"},
    }
    (bundle_dir / rl.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(rl, "MODEL_ROOT", tmp_path)
    monkeypatch.setattr(rl, "SEALED_MODEL_BYTE_SHA256", byte_sha256)
    monkeypatch.setattr(rl, "SEALED_MODEL_STATE_FINGERPRINT", "f" * 64)
    monkeypatch.setattr(
        rl,
        "observe_isolated_runtime",
        lambda: {
            "python_major_minor": "3.11",
            "python_patch": "15",
            "joblib": "1.5.3",
            "pandas": "3.0.3",
            "scikit_learn": "1.9.0",
        },
    )


def _request_body(**overrides) -> dict:
    body = {
        "contract_version": "external_inference_request.v1",
        "bundle_identity": {"bundle_id": _BUNDLE_ID, "dataset_slug": "telco-customer-churn"},
        "expected_runtime": {"python_major_minor": "3.11", "joblib": "1.5.3", "pandas": "3.0.3", "scikit_learn": "1.9.0"},
        "feature_payload": _feature_payload(),
    }
    body.update(overrides)
    return body


def _call_asgi(method: str, path: str, payload=None):
    """Exercises the real FastAPI ASGI router without an optional HTTP client dependency."""

    request_body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": request_body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    headers = [(b"content-length", str(len(request_body)).encode("ascii"))]
    if payload is not None:
        headers.append((b"content-type", b"application/json"))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("test-client", 50000),
        "server": ("test-server", 80),
    }
    asyncio.run(service_app.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(body)


def test_live_is_static_and_does_not_touch_the_loader(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("GET /live must never invoke the loader")

    monkeypatch.setattr(rl, "load_manifest", _forbidden)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _forbidden)

    status_code, body = _call_asgi("GET", "/live")

    assert status_code == 200
    assert body == {"status": "ok"}


def test_ready_reports_ready_when_compatible(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    status_code, body = _call_asgi("GET", "/ready")

    assert status_code == 200
    assert body["status"] == "ready"
    assert body["runtime_compatibility_status"] == "compatible"
    assert body["diagnostic_code"] is None


def test_ready_never_calls_the_loader(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("GET /ready must never invoke the loader")

    monkeypatch.setattr(rl, "invoke_allowlisted_loader", _forbidden)

    status_code, body = _call_asgi("GET", "/ready")

    assert status_code == 200
    assert body["status"] == "ready"


def test_ready_reports_not_ready_on_incompatible_runtime(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rl,
        "observe_isolated_runtime",
        lambda: {"python_major_minor": "3.12", "python_patch": "0", "joblib": "1.5.3", "pandas": "3.0.3", "scikit_learn": "1.9.0"},
    )

    status_code, body = _call_asgi("GET", "/ready")

    assert status_code == 200
    assert body["status"] == "not_ready"
    assert body["runtime_compatibility_status"] == "incompatible"


def test_predict_rejects_a_request_with_additional_properties(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    status_code, body = _call_asgi("POST", "/predict", _request_body(unexpected_field="not allowed"))

    assert status_code == 422
    assert body["status"] == "failed"
    assert body["result"] is None


def test_predict_rejects_a_request_with_a_filesystem_path_field(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)
    body_with_path = _request_body()
    body_with_path["model_path"] = "/app/external-models/telco-customer-churn/models/model.joblib"

    status_code, body = _call_asgi("POST", "/predict", body_with_path)

    assert status_code == 422
    assert body["status"] == "failed"


def test_predict_returns_a_valid_bounded_result_on_success(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    status_code, body = _call_asgi("POST", "/predict", _request_body())

    assert status_code == 200
    assert body["status"] == "ok"
    assert body["diagnostic_code"] is None
    assert body["runtime_compatibility_status"] == "compatible"
    assert body["result"]["schema_version"] == "binary-classification-result.v1"
    assert 0.0 <= body["result"]["positive_class_probability"] <= 1.0


def test_predict_never_forwards_raw_exception_detail(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    def _raise(_path):
        raise ValueError("a secret internal detail that must never leak")

    monkeypatch.setattr(joblib, "load", _raise)

    status_code, body = _call_asgi("POST", "/predict", _request_body())

    assert status_code == 200
    assert body["status"] == "failed"
    assert body["diagnostic_code"] == rl.DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED
    assert "secret internal detail" not in json.dumps(body)


def test_predict_maps_stale_bundle_reference_and_never_loads(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a stale request must never reach the loader")

    monkeypatch.setattr(rl, "invoke_allowlisted_loader", _forbidden)

    stale_body = _request_body(bundle_identity={"bundle_id": "a-different-bundle", "dataset_slug": "telco-customer-churn"})

    status_code, body = _call_asgi("POST", "/predict", stale_body)

    assert status_code == 200
    assert body["status"] == "failed"
    assert body["runtime_compatibility_status"] == "stale_bundle_reference"
