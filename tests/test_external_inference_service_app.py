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


_FEATURE_ORDER = ["account_age", "monthly_spend", "segment"]
_BUNDLE_ID = "synthetic-retention-external-inference-bundle-test"


def _train_fixture_pipeline() -> Pipeline:
    rows = []
    labels = []
    for monthly, age, label in [
        (95.0, 12, "leave"), (98.0, 10, "leave"), (90.0, 8, "leave"), (92.0, 6, "leave"),
        (20.0, 30, "stay"), (22.0, 36, "stay"), (18.0, 40, "stay"),
        (25.0, 24, "stay"), (19.0, 48, "stay"), (21.0, 60, "stay"),
    ]:
        row = {"account_age": age, "monthly_spend": monthly, "segment": "consumer"}
        rows.append(row)
        labels.append(label)

    frame = pd.DataFrame(rows, columns=_FEATURE_ORDER)
    preprocessor = ColumnTransformer(
        [("numeric", "passthrough", ["monthly_spend", "account_age"])],
        remainder="drop",
    )
    pipeline = Pipeline([("pre", preprocessor), ("clf", LogisticRegression())])
    pipeline.fit(frame, labels)
    return pipeline


def _feature_payload() -> dict:
    return {"account_age": 12, "monthly_spend": 95.0, "segment": "consumer"}


def _write_fixture_bundle(tmp_path: Path, monkeypatch) -> None:
    release_id = "release-test"
    release_dir = tmp_path / release_id
    models_dir = release_dir / "models"
    predictions_dir = release_dir / "predictions"
    contracts_dir = release_dir / "contracts"
    models_dir.mkdir(parents=True, exist_ok=True)
    predictions_dir.mkdir(parents=True, exist_ok=True)
    contracts_dir.mkdir(parents=True, exist_ok=True)

    model_path = models_dir / "model.pkl"
    joblib.dump(_train_fixture_pipeline(), model_path)
    byte_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

    bundle = {
        "contract_version": "inference_bundle.v1",
        "bundle_identity": {"bundle_id": _BUNDLE_ID},
        "dataset_context": {"dataset_slug": "synthetic-retention"},
        "model_artifact": {"path": "models/model.pkl", "sha256": byte_sha256},
        "contract_references": {"runtime_contract": {"contract_version": "1.0.0", "path": "source/runtime-contract.json"}},
        "input_schema": {"runtime_contract_reference": "contract_references.runtime_contract", "payload_shape": "runtime_contract_features_object"},
        "feature_order": list(_FEATURE_ORDER),
        "output_schema": {"class_labels": ["leave", "stay"], "prediction_type": "number", "probability_output": True},
        "model_provenance_origin": "validated_external_fitted_model",
        "external_model_evidence": {"educational_threshold": {"value": 0.4}},
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1", "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1", "primary_output": "positive_class_probability",
            "positive_class": {"class_id": "leave", "event_label": "Attrition"},
            "decision": {"threshold": 0.4},
            "interpretation": {"preset": "risk", "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.2},
                {"band_id": "medium", "lower_bound": 0.2, "upper_bound": 0.7},
                {"band_id": "high", "lower_bound": 0.7, "upper_bound": 1.0},
            ]},
            "model_descriptor": {"model_family": "logistic_regression", "display_name": "Synthetic retention classifier"},
        },
    }
    bundle_path = predictions_dir / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    bundle_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    contract_path = contracts_dir / "runtime-contract.json"
    contract_path.write_text(json.dumps({"schema_version": "1.0.0", "features": [
        {"name": "account_age", "required": True}, {"name": "monthly_spend", "required": True}, {"name": "segment", "required": False},
    ]}), encoding="utf-8")
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "release-manifest.v1",
        "release_identity": {"release_id": release_id},
        "dataset_identity": {"dataset_slug": "synthetic-retention"},
        "artifacts": [
            {"role": "contracts", "reference": "contracts/runtime-contract.json", "hash_algorithm": "sha256", "hash_value": contract_sha256},
            {"role": "predictive_bundle", "reference": "predictions/bundle.json", "hash_algorithm": "sha256", "hash_value": bundle_sha256},
            {"role": "model_artifact", "reference": "models/model.pkl", "hash_algorithm": "sha256", "hash_value": byte_sha256},
        ],
    }
    (release_dir / rl.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
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
        "release_identity": {"release_id": "release-test"},
        "bundle_identity": {"bundle_id": _BUNDLE_ID, "dataset_slug": "synthetic-retention"},
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


def test_request_contract_accepts_arbitrary_scalar_features_for_non_telco_slug(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)
    body = _request_body()
    body["feature_payload"] = {"arbitrary_text": "value", "arbitrary_number": 3.5, "arbitrary_flag": True}

    status_code, response = _call_asgi("POST", "/predict", body)

    assert status_code == 200
    assert response["diagnostic_code"] == rl.DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT
    assert response["result"] is None


def test_request_contract_rejects_nested_array_and_null_feature_values(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)
    for invalid_value in ({"nested": "value"}, [1, 2], None):
        body = _request_body()
        body["feature_payload"] = {"arbitrary": invalid_value}
        status_code, response = _call_asgi("POST", "/predict", body)
        assert status_code == 422
        assert response["status"] == "failed"
        assert response["result"] is None


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


def test_predict_accepts_strict_multiclass_success_envelope(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)
    multiclass_result = {
        "schema_version": "multiclass-classification-result.v1",
        "problem_type": "multiclass_classification",
        "predicted_class": {"class_id": "beta", "display_label": "Beta"},
        "class_probabilities": [
            {"class_id": "alpha", "display_label": "Alpha", "probability": 0.2},
            {"class_id": "beta", "display_label": "Beta", "probability": 0.6},
            {"class_id": "gamma", "display_label": "Gamma", "probability": 0.2},
        ],
        "decision": {"strategy": "argmax"},
        "model_descriptor": {"model_family": "decision_tree", "display_name": "Synthetic multiclass model"},
    }
    monkeypatch.setattr(rl, "execute_governed_external_prediction", lambda _request: multiclass_result)

    status_code, body = _call_asgi("POST", "/predict", _request_body())

    assert status_code == 200
    assert body["contract_version"] == "external_inference_result.v1"
    assert body["status"] == "ok"
    assert body["runtime_compatibility_status"] == "compatible"
    assert body["diagnostic_code"] is None
    assert body["result"] == multiclass_result


def test_predict_maps_stale_bundle_reference_and_never_loads(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a stale request must never reach the loader")

    monkeypatch.setattr(rl, "invoke_allowlisted_loader", _forbidden)

    stale_body = _request_body(bundle_identity={"bundle_id": "a-different-bundle", "dataset_slug": "synthetic-retention"})

    status_code, body = _call_asgi("POST", "/predict", stale_body)

    assert status_code == 200
    assert body["status"] == "failed"
    assert body["runtime_compatibility_status"] == "stale_bundle_reference"
