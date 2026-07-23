import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import main as api_main  # noqa: E402
from runtime.inference import (  # noqa: E402
    DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE,
    DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH,
    DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE,
    DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED,
    DIAGNOSTIC_PREDICTION_EXECUTION_FAILED,
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE,
    BundleValidationError,
)


DATASET_SLUG = "controlled-private-dataset"
ACTIVE_RELEASE = "controlled-release"
SUBMITTED_INVALID_VALUE = 424242
SAFE_ISSUE_KEYS = {"error_code", "message", "field", "violation"}
SUPPORTED_VIOLATIONS = {"missing_required_field", "type_mismatch", "domain_violation"}


def _post_json(path: str, payload):
    """Exercise the real FastAPI ASGI router without an optional HTTP client dependency."""
    request_body = json.dumps(payload).encode("utf-8")
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

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(request_body)).encode("ascii"))],
        "client": ("test-client", 50000),
        "server": ("test-server", 80),
    }
    asyncio.run(api_main.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(body), body.decode("utf-8")


def _install_controlled_read_only_dependencies(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=ACTIVE_RELEASE),
    )
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda active_release: {
            "features": [
                {
                    "name": "MonthlyCharges",
                    "type": "numeric",
                    "required": True,
                    "domain_constraints": {"min": 0, "max": 100},
                }
            ]
        },
    )


def test_private_admin_route_returns_bounded_structured_invalid_payload(monkeypatch):
    _install_controlled_read_only_dependencies(monkeypatch)

    status_code, body, response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", {"MonthlyCharges": SUBMITTED_INVALID_VALUE}
    )

    assert status_code == 422
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert isinstance(body["errors"], list) and body["errors"]
    assert all(set(issue) == SAFE_ISSUE_KEYS for issue in body["errors"])
    assert all(issue["field"] == "MonthlyCharges" for issue in body["errors"])
    assert all(issue["violation"] in SUPPORTED_VIOLATIONS for issue in body["errors"])

    serialized = response_text
    assert str(SUBMITTED_INVALID_VALUE) not in serialized
    for forbidden in ("traceback", "exception", "active_release", ACTIVE_RELEASE, "bundle", "credential", "authorization"):
        assert forbidden not in serialized.lower()


def test_private_admin_route_bounds_a_malformed_top_level_payload(monkeypatch):
    _install_controlled_read_only_dependencies(monkeypatch)

    status_code, body, response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", [{"MonthlyCharges": SUBMITTED_INVALID_VALUE}]
    )

    assert status_code == 422
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert body["errors"] == [
        {
            "error_code": "TYPE_MISMATCH",
            "message": "The inference payload must be a JSON object.",
            "field": "payload",
            "violation": "type_mismatch",
        }
    ]
    assert str(SUBMITTED_INVALID_VALUE) not in response_text


def test_private_admin_route_preserves_not_found_concealment_when_unauthorized(monkeypatch):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    resolution_attempted = False

    def fail_if_resolved(_dataset_slug):
        nonlocal resolution_attempted
        resolution_attempted = True
        raise AssertionError("unauthorized requests must not resolve datasets")

    monkeypatch.setattr(api_main, "resolve_dataset", fail_if_resolved)

    status_code, body, _response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", {"MonthlyCharges": SUBMITTED_INVALID_VALUE}
    )

    assert status_code == 404
    assert body == {"detail": "Not Found"}
    assert resolution_attempted is False


# ---------------------------------------------------------------------------
# Project Spec S0150: the private Admin route must reach the real
# joblib/scikit-learn loader and executor with controlled temporary release
# files -- neither execute_prediction nor the model loader may be mocked.
# Mirrors the minimal (not "full") inference_bundle declaration shape and
# real-pipeline-training technique already established by
# tests/test_local_inference_smoke.py's S0109 helpers, exercised here through
# the real HTTP admin route instead of calling execute_prediction directly.
# ---------------------------------------------------------------------------

_S0150_FEATURE_ORDER = ["tenure", "monthly_charges"]


def _s0150_train_real_pipeline() -> Pipeline:
    X = pd.DataFrame(
        {
            "tenure": [1, 2, 3, 4, 60, 61, 62, 63, 64, 65],
            "monthly_charges": [95.0, 98.0, 90.0, 92.0, 20.0, 22.0, 18.0, 25.0, 19.0, 21.0],
        }
    )
    y = ["Yes", "Yes", "Yes", "Yes", "No", "No", "No", "No", "No", "No"]
    pipeline = Pipeline([("clf", LogisticRegression())])
    pipeline.fit(X, y)
    return pipeline


def _s0150_write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _s0150_write_real_release(releases_root: Path) -> None:
    release_root = releases_root / ACTIVE_RELEASE
    models_dir = release_root / "models"
    predictions_dir = release_root / "predictions"
    models_dir.mkdir(parents=True)
    predictions_dir.mkdir(parents=True)

    pipeline = _s0150_train_real_pipeline()
    model_path = models_dir / "model.pkl"
    joblib.dump(pipeline, model_path)
    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

    bundle = {
        "contract_version": "inference_bundle.v1",
        "feature_order": list(_S0150_FEATURE_ORDER),
        "runtime_execution": {
            "loader_strategy": "joblib_sklearn_predict",
            "serialization_format": "joblib",
            "prediction_interface": "predict",
            "model_family": "logistic_regression",
        },
        "model_artifact": {"path": "models/model.pkl", "sha256": model_sha256},
        "output_schema": {
            "class_labels": ["No", "Yes"],
            "prediction_key": "prediction",
            "prediction_type": "string",
            "probability_output": True,
        },
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1",
            "primary_output": "positive_class_probability",
            "positive_class": {"class_id": "Yes", "event_label": "Churn"},
            "decision": {"threshold": 0.5},
            "interpretation": {
                "preset": "risk",
                "bands": [
                    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
                ],
            },
            "model_descriptor": {
                "model_family": "logistic_regression",
                "display_name": "Logistic Regression",
            },
        },
    }
    _s0150_write_json(predictions_dir / "bundle.json", bundle)

    _s0150_write_json(
        release_root / "manifest.json",
        {
            "schema_version": "release-manifest.v1",
            "artifacts": [
                {"role": "predictive_bundle", "reference": "predictions/bundle.json"},
            ],
        },
    )


def _install_real_model_dependencies(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("RELEASES_ROOT", str(tmp_path))
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=ACTIVE_RELEASE),
    )
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda active_release: {
            "features": [
                {"name": "tenure", "type": "numeric", "required": True, "domain_constraints": {"min": 0, "max": 72}},
                {
                    "name": "monthly_charges",
                    "type": "numeric",
                    "required": True,
                    "domain_constraints": {"min": 0, "max": 150},
                },
            ]
        },
    )
    _s0150_write_real_release(tmp_path)


def test_private_admin_route_executes_real_governed_model_success(monkeypatch, tmp_path):
    _install_real_model_dependencies(monkeypatch, tmp_path)

    status_code, body, response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference",
        {"tenure": 63, "monthly_charges": 19.0},
    )

    assert status_code == 200
    assert body["dataset_slug"] == DATASET_SLUG
    result = body["result"]
    assert result["schema_version"] == "binary-classification-result.v1"
    assert result["predicted_class"]["class_id"] in {"No", "Yes"}
    assert result["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert 0.0 <= result["positive_class_probability"] <= 1.0
    assert {p["class_id"] for p in result["class_probabilities"]} == {"No", "Yes"}
    assert result["interpretation"]["band_id"] in {"low", "medium", "high"}
    assert result["model_descriptor"] == {
        "model_family": "logistic_regression",
        "display_name": "Logistic Regression",
    }

    # Private route success is independent of public visibility/review-readiness
    # gates (this test never mocks resolve_dataset_visibility or
    # resolve_dataset_snapshot_readiness, matching the route's own real
    # resolve_dataset()-only access resolution), and no raw payload, model
    # bytes or stack trace ever appear in the response body.
    for forbidden in ("traceback", "exception", "credential", "authorization"):
        assert forbidden not in response_text.lower()


# ---------------------------------------------------------------------------
# Project Spec S0151: private Admin runtime failure diagnostics and public
# non-leakage, exercised through the real HTTP admin route with real
# joblib/scikit-learn artifacts (never mocking execute_prediction or the
# model loader), mirroring the S0150 real-model technique above.
# ---------------------------------------------------------------------------


class _S0151BrokenPredictModel:
    """A real, joblib-picklable model whose predict/predict_proba raise.

    Deliberately module-level (not a lambda/closure) so joblib/pickle can
    actually serialize and deserialize it -- this exercises a real
    load-then-execute failure, not a mocked one.
    """

    def predict(self, _payload):
        raise RuntimeError("synthetic prediction failure for S0151 coverage")

    def predict_proba(self, _payload):
        raise RuntimeError("synthetic prediction failure for S0151 coverage")


def _s0151_write_release(
    releases_root: Path,
    *,
    model: object | None = None,
    model_bytes: bytes | None = None,
    sha256_override: str | None = None,
    write_model: bool = True,
    write_bundle: bool = True,
    loader_strategy: str = "joblib_sklearn_predict",
) -> None:
    release_root = releases_root / ACTIVE_RELEASE
    models_dir = release_root / "models"
    predictions_dir = release_root / "predictions"
    models_dir.mkdir(parents=True)
    predictions_dir.mkdir(parents=True)

    model_path = models_dir / "model.pkl"
    if write_model:
        if model_bytes is not None:
            model_path.write_bytes(model_bytes)
        else:
            joblib.dump(model if model is not None else _s0150_train_real_pipeline(), model_path)
        model_sha256 = sha256_override or hashlib.sha256(model_path.read_bytes()).hexdigest()
    else:
        model_sha256 = sha256_override or "0" * 64

    if write_bundle:
        bundle = {
            "contract_version": "inference_bundle.v1",
            "feature_order": list(_S0150_FEATURE_ORDER),
            "runtime_execution": {
                "loader_strategy": loader_strategy,
                "serialization_format": "joblib",
                "prediction_interface": "predict",
                "model_family": "logistic_regression",
            },
            "model_artifact": {"path": "models/model.pkl", "sha256": model_sha256},
            "output_schema": {
                "class_labels": ["No", "Yes"],
                "prediction_key": "prediction",
                "prediction_type": "string",
                "probability_output": True,
            },
            "result_semantics": {
                "schema_version": "binary-result-semantics.v1",
                "problem_type": "binary_classification",
                "result_schema_version": "binary-classification-result.v1",
                "primary_output": "positive_class_probability",
                "positive_class": {"class_id": "Yes", "event_label": "Churn"},
                "decision": {"threshold": 0.5},
                "interpretation": {
                    "preset": "risk",
                    "bands": [
                        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
                    ],
                },
                "model_descriptor": {
                    "model_family": "logistic_regression",
                    "display_name": "Logistic Regression",
                },
            },
        }
        _s0150_write_json(predictions_dir / "bundle.json", bundle)
        _s0150_write_json(
            release_root / "manifest.json",
            {
                "schema_version": "release-manifest.v1",
                "artifacts": [{"role": "predictive_bundle", "reference": "predictions/bundle.json"}],
            },
        )
    else:
        _s0150_write_json(
            release_root / "manifest.json",
            {"schema_version": "release-manifest.v1", "artifacts": []},
        )


def _install_broken_release_dependencies(monkeypatch, tmp_path: Path, **release_kwargs) -> None:
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("RELEASES_ROOT", str(tmp_path))
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=ACTIVE_RELEASE),
    )
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda active_release: {
            "features": [
                {"name": "tenure", "type": "numeric", "required": True, "domain_constraints": {"min": 0, "max": 72}},
                {
                    "name": "monthly_charges",
                    "type": "numeric",
                    "required": True,
                    "domain_constraints": {"min": 0, "max": 150},
                },
            ]
        },
    )
    _s0151_write_release(tmp_path, **release_kwargs)


_VALID_PAYLOAD = {"tenure": 63, "monthly_charges": 19.0}


def _assert_generic_inference_failure_shape(body: dict, response_text: str) -> None:
    assert body["error_type"] == "inference_failure"
    assert body["error_code"] == "INFERENCE_FAILURE"
    assert body["message"] == "Inference is temporarily unavailable."
    for forbidden in ("traceback", "exception", "credential", "authorization"):
        assert forbidden not in response_text.lower()


def test_private_admin_route_surfaces_runtime_dependency_unavailable_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "joblib", None)

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE}
    assert "joblib" not in response_text.lower()
    for forbidden in ("traceback", "exception", str(tmp_path)):
        assert forbidden not in response_text


def test_private_admin_route_surfaces_model_artifact_unavailable_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path, write_model=False)

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE}
    assert str(tmp_path) not in response_text


def test_private_admin_route_surfaces_model_artifact_hash_mismatch_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path, sha256_override="0" * 64)

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH}
    assert ("0" * 64) not in response_text


def test_private_admin_route_surfaces_model_deserialization_failed_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(
        monkeypatch, tmp_path, model_bytes=b"not-a-real-joblib-pickle-stream"
    )

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED}
    assert str(tmp_path) not in response_text


def test_private_admin_route_surfaces_prediction_execution_failed_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path, model=_S0151BrokenPredictModel())

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_PREDICTION_EXECUTION_FAILED}
    assert "synthetic prediction failure" not in response_text


def test_private_admin_route_surfaces_inference_bundle_unavailable_diagnostic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path, write_bundle=False)

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE}


def test_private_admin_route_surfaces_result_validation_failed_diagnostic(monkeypatch, tmp_path):
    _install_real_model_dependencies(monkeypatch, tmp_path)

    def _raise_result_validation_failed(_result):
        raise BundleValidationError(
            "invalid_binary_classification_result",
            "Binary classification result failed schema validation.",
            field="result",
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
        )

    monkeypatch.setattr(api_main, "validate_binary_classification_result", _raise_result_validation_failed)

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert body["runtime_diagnostic"] == {"code": DIAGNOSTIC_RESULT_VALIDATION_FAILED}


def test_private_admin_route_keeps_an_unclassified_failure_fully_generic(monkeypatch, tmp_path):
    _install_broken_release_dependencies(monkeypatch, tmp_path, loader_strategy="totally_unsupported_strategy")

    status_code, body, response_text = _post_json(f"/admin/datasets/{DATASET_SLUG}/inference", _VALID_PAYLOAD)

    assert status_code == 503
    _assert_generic_inference_failure_shape(body, response_text)
    assert "runtime_diagnostic" not in body


def test_private_admin_route_still_rejects_invalid_payload_unchanged(monkeypatch, tmp_path):
    # Project Spec S0151, acceptance criterion 11: INVALID_PAYLOAD and its
    # S0147 structured `errors` contract are untouched by this spec -- this
    # runtime-diagnostic machinery only applies to the runtime execution
    # branch, never to payload validation.
    _install_real_model_dependencies(monkeypatch, tmp_path)

    status_code, body, _response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", {"tenure": "not-a-number", "monthly_charges": 19.0}
    )

    assert status_code == 422
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert "runtime_diagnostic" not in body


def test_public_route_never_surfaces_a_runtime_diagnostic_for_the_same_classified_failure(monkeypatch, tmp_path):
    # Project Spec S0151: the shared execution boundary
    # (_execute_governed_inference) is exercised directly with
    # include_runtime_diagnostic left at its default False, exactly as the
    # public route calls it -- proving the omission is an explicit route-level
    # decision, not a coincidence of which failure occurred.
    _install_broken_release_dependencies(monkeypatch, tmp_path, sha256_override="0" * 64)

    response = api_main._execute_governed_inference(DATASET_SLUG, ACTIVE_RELEASE, dict(_VALID_PAYLOAD))

    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["error_code"] == "INFERENCE_FAILURE"
    assert "runtime_diagnostic" not in body
