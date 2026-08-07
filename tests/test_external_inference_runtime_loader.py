"""S0161: controlled fixture/monkeypatch coverage for the isolated service's
fourteen-step load-safe gate (external-inference/runtime_loader.py).

Mirrors this repository's established real-pipeline-training technique
(tests/api/test_admin_live_preview_inference.py's _s0150_train_real_pipeline)
rather than mocking scikit-learn itself, but never deserializes the real
Telco Joblib -- every fixture model here is trained from scratch on tiny
synthetic data.
"""

import hashlib
import json
import sys
import types
import warnings
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


_FEATURE_ORDER = list(rl._FEATURE_ORDER)
_BUNDLE_ID = "telco-customer-churn-external-inference-bundle-test"
_MANIFEST_FINGERPRINT = "f" * 64


def _train_fixture_pipeline() -> Pipeline:
    """A tiny, from-scratch pipeline -- never the real Telco Joblib."""

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


def _build_request(*, bundle_id: str = _BUNDLE_ID, expected_runtime: dict | None = None) -> dict:
    return {
        "contract_version": "external_inference_request.v1",
        "bundle_identity": {"bundle_id": bundle_id, "dataset_slug": "telco-customer-churn"},
        "expected_runtime": expected_runtime
        or {"python_major_minor": "3.11", "joblib": "1.5.3", "pandas": "3.0.3", "scikit_learn": "1.9.0"},
        "feature_payload": _feature_payload(),
    }


def _write_fixture_bundle(
    model_root: Path,
    *,
    monkeypatch,
    model_relative_path: str = "models/model.joblib",
    expected_runtime: dict | None = None,
    fingerprint: str | None = _MANIFEST_FINGERPRINT,
    bundle_id: str = _BUNDLE_ID,
    corrupt_after_hash: bool = False,
) -> None:
    bundle_dir = model_root / rl.BUNDLE_DIRECTORY_NAME
    models_dir = bundle_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    model_path = bundle_dir / model_relative_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(_train_fixture_pipeline(), model_path)
    byte_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

    manifest = {
        "artifact_type": "external_inference_model_manifest",
        "contract_version": rl.MANIFEST_CONTRACT_VERSION,
        "dataset_slug": "telco-customer-churn",
        "bundle_identity": {"bundle_id": bundle_id, "dataset_slug": "telco-customer-churn"},
        "model_artifact": {
            "relative_path": model_relative_path,
            "byte_sha256": byte_sha256,
            "model_state_fingerprint": fingerprint,
        },
        "expected_runtime": expected_runtime
        or {
            "python_major_minor": "3.11",
            "python_patch": "15",
            "joblib": "1.5.3",
            "pandas": "3.0.3",
            "scikit_learn": "1.9.0",
        },
        "trusted_source": {"producer_repository": "dataset-study-telco-customer-churn"},
    }
    (bundle_dir / rl.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(rl, "MODEL_ROOT", model_root)
    monkeypatch.setattr(rl, "SEALED_MODEL_BYTE_SHA256", byte_sha256)
    if fingerprint is not None:
        monkeypatch.setattr(rl, "SEALED_MODEL_STATE_FINGERPRINT", fingerprint)

    if corrupt_after_hash:
        with model_path.open("ab") as handle:
            handle.write(b"corruption")


def _install_load_forbidding_joblib(monkeypatch) -> None:
    """Proves a code path never reaches joblib.load: replaces the cached
    joblib module (import joblib picks up sys.modules) with a stub whose
    .load raises, while keeping __version__ for observe_isolated_runtime."""

    stub = types.SimpleNamespace(__version__=joblib.__version__)

    def _forbidden_load(*_args, **_kwargs):
        raise AssertionError("joblib.load must not be called")

    stub.load = _forbidden_load
    monkeypatch.setitem(sys.modules, "joblib", stub)


def _matching_observed_runtime() -> dict:
    return {
        "python_major_minor": "3.11",
        "python_patch": "15",
        "joblib": "1.5.3",
        "pandas": "3.0.3",
        "scikit_learn": "1.9.0",
    }


# ---------------------------------------------------------------------------
# Steps 1-10: preflight gate / compatibility policy
# ---------------------------------------------------------------------------


def test_exact_runtime_match_is_compatible_with_no_warning(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    preflight = rl.run_preflight_gate(_build_request())

    assert preflight["compatibility"] == {"status": "compatible", "python_patch_warning": False}


def test_python_patch_only_difference_is_compatible_with_warning(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    observed = _matching_observed_runtime()
    observed["python_patch"] = "9"
    monkeypatch.setattr(rl, "observe_isolated_runtime", lambda: observed)

    preflight = rl.run_preflight_gate(_build_request())

    assert preflight["compatibility"] == {"status": "compatible", "python_patch_warning": True}


def test_python_major_minor_mismatch_is_incompatible_and_never_loads(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    observed = _matching_observed_runtime()
    observed["python_major_minor"] = "3.12"
    monkeypatch.setattr(rl, "observe_isolated_runtime", lambda: observed)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.runtime_compatibility_status == "incompatible"
        assert exc.diagnostic_code == rl.DIAGNOSTIC_RUNTIME_DEPENDENCY_UNAVAILABLE


def test_dependency_version_mismatch_is_incompatible_and_never_loads(tmp_path, monkeypatch):
    for dependency in ("joblib", "pandas", "scikit_learn"):
        _write_fixture_bundle(tmp_path / dependency, monkeypatch=monkeypatch)
        observed = _matching_observed_runtime()
        observed[dependency] = "0.0.0"
        monkeypatch.setattr(rl, "observe_isolated_runtime", lambda observed=observed: observed)
        _install_load_forbidding_joblib(monkeypatch)

        try:
            rl.run_preflight_gate(_build_request())
            raise AssertionError(f"expected LoadSafeGateError for {dependency}")
        except rl.LoadSafeGateError as exc:
            assert exc.runtime_compatibility_status == "incompatible"


def test_stale_bundle_reference_from_mismatched_expected_runtime(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    stale_request = _build_request(expected_runtime={"python_major_minor": "3.11", "joblib": "9.9.9", "pandas": "3.0.3", "scikit_learn": "1.9.0"})

    try:
        rl.run_preflight_gate(stale_request)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.runtime_compatibility_status == "stale_bundle_reference"
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_stale_bundle_reference_from_mismatched_bundle_id(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    stale_request = _build_request(bundle_id="a-different-bundle-id")

    try:
        rl.run_preflight_gate(stale_request)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.runtime_compatibility_status == "stale_bundle_reference"


def test_absolute_model_path_rejected_before_any_file_access(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch, model_relative_path="models/model.joblib")
    manifest = rl.load_manifest(tmp_path)
    manifest = dict(manifest)
    manifest["model_artifact"] = dict(manifest["model_artifact"])
    manifest["model_artifact"]["relative_path"] = "/etc/passwd"

    try:
        rl.resolve_model_path(manifest, tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE


def test_traversal_model_path_rejected_before_any_file_access(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    manifest = rl.load_manifest(tmp_path)
    manifest = dict(manifest)
    manifest["model_artifact"] = dict(manifest["model_artifact"])
    manifest["model_artifact"]["relative_path"] = "../../../etc/passwd"

    try:
        rl.resolve_model_path(manifest, tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE


def test_symlink_model_path_rejected_as_non_regular_file(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    bundle_dir = tmp_path / rl.BUNDLE_DIRECTORY_NAME
    real_model = bundle_dir / "models" / "model.joblib"
    symlink_path = bundle_dir / "models" / "model-link.joblib"
    symlink_path.symlink_to(real_model)

    manifest = rl.load_manifest(tmp_path)
    manifest = dict(manifest)
    manifest["model_artifact"] = dict(manifest["model_artifact"])
    manifest["model_artifact"]["relative_path"] = "models/model-link.joblib"

    try:
        rl.resolve_model_path(manifest, tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE


def test_missing_model_artifact_fails_before_deserialization(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)
    (tmp_path / rl.BUNDLE_DIRECTORY_NAME / "models" / "model.joblib").unlink()

    try:
        rl.run_preflight_gate(_build_request())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE


def test_model_byte_hash_mismatch_fails_before_deserialization(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch, corrupt_after_hash=True)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH


def test_model_state_fingerprint_mismatch_fails_before_deserialization(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch, fingerprint="a" * 64)
    # Sealed reference is set to the manifest's own declared value by the
    # fixture helper; simulate later drift/corruption of the sealed
    # reference constant itself (independent from the on-disk manifest).
    monkeypatch.setattr(rl, "SEALED_MODEL_STATE_FINGERPRINT", "b" * 64)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH


def test_readiness_gate_never_calls_the_loader_on_success(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    preflight = rl.run_preflight_gate(request=None)

    assert preflight["compatibility"]["status"] == "compatible"


# ---------------------------------------------------------------------------
# Steps 11-13: allowlisted loader + InconsistentVersionWarning conversion
# ---------------------------------------------------------------------------


def test_inconsistent_version_warning_is_converted_to_controlled_failure(tmp_path, monkeypatch):
    from sklearn.exceptions import InconsistentVersionWarning

    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    model_path = tmp_path / rl.BUNDLE_DIRECTORY_NAME / "models" / "model.joblib"
    real_load = joblib.load

    def _load_with_warning(path):
        warnings.warn("simulated version drift", InconsistentVersionWarning)
        return real_load(path)

    monkeypatch.setattr(joblib, "load", _load_with_warning)

    try:
        rl.invoke_allowlisted_loader(model_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED


def test_deserialization_exception_maps_to_controlled_failure(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    model_path = tmp_path / rl.BUNDLE_DIRECTORY_NAME / "models" / "model.joblib"

    def _raise(_path):
        raise ValueError("corrupt pickle stream")

    monkeypatch.setattr(joblib, "load", _raise)

    try:
        rl.invoke_allowlisted_loader(model_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_DESERIALIZATION_FAILED
        assert "corrupt pickle stream" not in str(exc)


# ---------------------------------------------------------------------------
# Step 14: bounded prediction result
# ---------------------------------------------------------------------------


def test_full_governed_prediction_returns_a_valid_bounded_result(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    result = rl.execute_governed_external_prediction(_build_request())

    assert result["schema_version"] == "binary-classification-result.v1"
    assert result["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert 0.0 <= result["positive_class_probability"] <= 1.0
    assert result["interpretation"]["band_id"] in {"low", "medium", "high"}
    assert result["model_descriptor"]["model_family"] == "gradient_boosting"
    rl.validate_bounded_prediction_result(result)


def test_prediction_execution_failure_maps_to_controlled_diagnostic(tmp_path, monkeypatch):
    _write_fixture_bundle(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    request = _build_request()
    del request["feature_payload"]["MonthlyCharges"]

    try:
        rl.execute_governed_external_prediction(request)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_PREDICTION_EXECUTION_FAILED
