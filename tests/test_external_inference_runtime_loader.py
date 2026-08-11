"""Controlled fixture/monkeypatch coverage for the isolated service's
governed release-resolution and load-safe gate
(external-inference/runtime_loader.py), including the Project Spec S0189
operational-readiness threshold gate.

Mirrors this repository's established real-pipeline-training technique
rather than mocking scikit-learn itself, but never deserializes the real
Telco Joblib -- every fixture model here is trained from scratch on tiny
synthetic data. Every fixture release is built directly against the
current release-governed resolver shape (releases/{release_id}/manifest.json
+ artifacts[] with role/reference/hash_algorithm/hash_value), not the
legacy bundle-directory shape this module no longer uses.
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
_RELEASE_ID = "release-20260619-001"
_DATASET_SLUG = "telco-customer-churn"
_BUNDLE_ID = "telco-customer-churn-inference-bundle-test"
_BUNDLE_RELATIVE_PATH = "predictions/bundle.json"
_MODEL_RELATIVE_PATH = "models/model.joblib"
_DECISION_RELATIVE_PATH = "operational-readiness-decision.json"


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


def _feature_payload(*, monthly_charges: float = 95.0, total_charges: float = 950.0) -> dict:
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
        "MonthlyCharges": monthly_charges,
        "TotalCharges": total_charges,
    }


def _build_request(
    *,
    release_id: str = _RELEASE_ID,
    bundle_id: str = _BUNDLE_ID,
    dataset_slug: str = _DATASET_SLUG,
    expected_runtime: dict | None = None,
    feature_payload: dict | None = None,
) -> dict:
    return {
        "contract_version": rl.REQUEST_CONTRACT_VERSION,
        "release_identity": {"release_id": release_id},
        "bundle_identity": {"bundle_id": bundle_id, "dataset_slug": dataset_slug},
        "expected_runtime": expected_runtime or dict(rl.PACKAGED_RUNTIME),
        "feature_payload": feature_payload if feature_payload is not None else _feature_payload(),
    }


def _matching_observed_runtime() -> dict:
    return {
        "python_major_minor": rl.PACKAGED_RUNTIME["python_major_minor"],
        "python_patch": "15",
        "joblib": rl.PACKAGED_RUNTIME["joblib"],
        "pandas": rl.PACKAGED_RUNTIME["pandas"],
        "scikit_learn": rl.PACKAGED_RUNTIME["scikit_learn"],
    }


def _write_release(
    releases_root: Path,
    *,
    release_id: str = _RELEASE_ID,
    dataset_slug: str = _DATASET_SLUG,
    bundle_id: str = _BUNDLE_ID,
    model_relative_path: str = _MODEL_RELATIVE_PATH,
    corrupt_model_after_hash: bool = False,
    provenance: str | None = "validated_external_fitted_model",
    include_operational_readiness: bool = True,
    operational_validity: str = "confirmed",
    threshold_status: str = "resolved",
    threshold_value: float | None = 0.31,
    prediction_available: bool = True,
    decision_hash_override: str | None = None,
    decision_bundle_sha_override: str | None = None,
    decision_release_id_override: str | None = None,
    decision_dataset_slug_override: str | None = None,
    write_decision_file: bool = True,
    write_decision_artifact_entry: bool = True,
) -> Path:
    """Write a real, governed-resolver-shaped release directory. Returns the
    release directory. Every hash embedded in manifest.json's artifacts[]
    is computed from the actual bytes written, unless an *_override is
    supplied to simulate a stale/corrupted declaration."""
    release_dir = releases_root / release_id
    release_dir.mkdir(parents=True, exist_ok=True)

    model_path = release_dir / model_relative_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(_train_fixture_pipeline(), model_path)
    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if corrupt_model_after_hash:
        with model_path.open("ab") as handle:
            handle.write(b"corruption")

    bundle: dict = {
        "bundle_identity": {"bundle_id": bundle_id, "dataset_slug": dataset_slug},
        "dataset_context": {"dataset_slug": dataset_slug},
        "model_artifact": {"path": model_relative_path, "sha256": model_sha256},
        "external_model_evidence": {
            "educational_threshold": {"value": 0.99, "label": "educational"},
        },
    }
    if provenance is not None:
        bundle["model_provenance_origin"] = provenance
    bundle_text = json.dumps(bundle, indent=2)
    bundle_path = release_dir / _BUNDLE_RELATIVE_PATH
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle_text, encoding="utf-8")
    bundle_sha256 = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()

    artifacts = [
        {
            "role": "predictive_bundle",
            "reference": _BUNDLE_RELATIVE_PATH,
            "hash_algorithm": "sha256",
            "hash_value": bundle_sha256,
        },
        {
            "role": "model_artifact",
            "reference": model_relative_path,
            "hash_algorithm": "sha256",
            "hash_value": model_sha256,
        },
    ]

    if include_operational_readiness:
        decision = {
            "schema_version": "operational-readiness-decision.v1",
            "artifact_kind": "operational_readiness_decision",
            "created_at": "2026-06-19T00:00:00Z",
            "source_run": {"run_id": "validate-20260619T000000Z"},
            "candidate_identity": {
                "dataset_slug": decision_dataset_slug_override or dataset_slug,
                "release_id": decision_release_id_override or release_id,
                "release_version": "1.0.0",
            },
            "source_bindings": {
                "release_candidate": {"path": "release-candidate.json", "sha256": "a" * 64},
                "predictive_bundle": {
                    "path": _BUNDLE_RELATIVE_PATH,
                    "sha256": decision_bundle_sha_override or bundle_sha256,
                },
                "validated_run_terminal_result": {
                    "path": "publisher/runs/validate-20260619T000000Z/validated-run-terminal-result.json",
                    "sha256": "b" * 64,
                },
            },
            "source_readiness": {
                "operational_validity": "unconfirmed",
                "operational_threshold": {"status": "unresolved", "value": None},
                "operational_prediction_available": False,
            },
            "decision": {
                "operational_validity": operational_validity,
                "operational_threshold": {
                    "status": threshold_status,
                    "value": threshold_value if threshold_status == "resolved" else None,
                    "selection_basis": "test selection basis" if threshold_status == "resolved" else None,
                },
                "operational_prediction_available": prediction_available,
                "decision_basis": "Operator reviewed the external evaluation evidence.",
            },
            "boundary_confirmations": {
                "educational_threshold_automatically_promoted": False,
                "model_retrained": False,
                "model_reselected": False,
                "threshold_reoptimized_by_atlas": False,
                "source_run_mutated": False,
                "source_candidate_mutated": False,
                "source_inference_bundle_mutated": False,
                "promotion_invoked": False,
                "registry_mutated": False,
            },
        }
        decision_text = json.dumps(decision, indent=2)
        if write_decision_file:
            (release_dir / _DECISION_RELATIVE_PATH).write_text(decision_text, encoding="utf-8")
        if write_decision_artifact_entry:
            actual_hash = hashlib.sha256(decision_text.encode("utf-8")).hexdigest()
            artifacts.append({
                "role": "operational_readiness",
                "reference": _DECISION_RELATIVE_PATH,
                "hash_algorithm": "sha256",
                "hash_value": decision_hash_override or actual_hash,
            })

    manifest = {
        "release_identity": {"release_id": release_id},
        "dataset_identity": {"dataset_slug": dataset_slug},
        "artifacts": artifacts,
    }
    (release_dir / rl.MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return release_dir


def _install_load_forbidding_joblib(monkeypatch) -> None:
    """Proves a code path never reaches joblib.load: replaces the cached
    joblib module (import joblib picks up sys.modules) with a stub whose
    .load raises, while keeping __version__ for observe_isolated_runtime."""
    stub = types.SimpleNamespace(__version__=joblib.__version__)

    def _forbidden_load(*_args, **_kwargs):
        raise AssertionError("joblib.load must not be called")

    stub.load = _forbidden_load
    monkeypatch.setitem(sys.modules, "joblib", stub)


# ---------------------------------------------------------------------------
# Runtime compatibility (steps 1-10 preflight)
# ---------------------------------------------------------------------------


def test_exact_runtime_match_is_compatible(tmp_path, monkeypatch):
    _write_release(tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    preflight = rl.run_preflight_gate(_build_request(), tmp_path)

    assert preflight["compatibility"] == {"status": "compatible", "python_patch_warning": False}
    assert preflight["operational_threshold"] == 0.31


def test_dependency_version_mismatch_is_incompatible_and_never_loads(tmp_path, monkeypatch):
    _write_release(tmp_path)
    observed = _matching_observed_runtime()
    observed["joblib"] = "0.0.0"
    monkeypatch.setattr(rl, "observe_isolated_runtime", lambda: observed)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.runtime_compatibility_status == "incompatible"


def test_missing_release_directory_fails_before_loader(tmp_path, monkeypatch):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_traversal_release_id_rejected_before_any_file_access(tmp_path, monkeypatch):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _install_load_forbidding_joblib(monkeypatch)
    request = _build_request(release_id="../../etc")

    try:
        rl.run_preflight_gate(request, tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_missing_model_artifact_fails_before_deserialization(tmp_path, monkeypatch):
    release_dir = _write_release(tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)
    (release_dir / _MODEL_RELATIVE_PATH).unlink()

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_UNAVAILABLE


def test_model_byte_hash_mismatch_fails_before_deserialization(tmp_path, monkeypatch):
    _write_release(tmp_path, corrupt_model_after_hash=True)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH


def test_stale_bundle_identity_rejected(tmp_path, monkeypatch):
    _write_release(tmp_path, bundle_id="a-different-bundle-id-in-the-release")
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(bundle_id=_BUNDLE_ID), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.runtime_compatibility_status == "stale_bundle_reference"


# ---------------------------------------------------------------------------
# Project Spec S0189: operational-readiness decision gate (before loader)
# ---------------------------------------------------------------------------


def test_missing_operational_readiness_decision_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, include_operational_readiness=False)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_decision_hash_mismatch_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, decision_hash_override="f" * 64)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH


def test_decision_bundle_binding_mismatch_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, decision_bundle_sha_override="c" * 64)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_MODEL_ARTIFACT_HASH_MISMATCH


def test_decision_release_identity_mismatch_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, decision_release_id_override="release-20260101-999")
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_unconfirmed_operational_validity_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, operational_validity="unconfirmed")
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_unresolved_operational_threshold_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, threshold_status="unresolved", threshold_value=None)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_prediction_unavailable_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, prediction_available=False)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_internal_provenance_skips_operational_readiness_requirement(tmp_path, monkeypatch):
    """A release whose predictive bundle is not validated_external_fitted_model
    never requires an operational-readiness decision (Project Spec S0189
    scopes that gate to 'an external governed release'), and this isolated
    service's pre-S0189 historical threshold still applies for it, matching
    'internal/legacy provenance: behavior remains unchanged'."""
    _write_release(tmp_path, provenance=None, include_operational_readiness=False)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    preflight = rl.run_preflight_gate(_build_request(), tmp_path)
    assert preflight["operational_threshold"] is None

    result = rl.execute_governed_external_prediction(_build_request())
    assert result["decision"]["threshold"] == rl._DECISION_THRESHOLD


# ---------------------------------------------------------------------------
# Steps 11-13: allowlisted loader + InconsistentVersionWarning conversion
# ---------------------------------------------------------------------------


def test_inconsistent_version_warning_is_converted_to_controlled_failure(tmp_path, monkeypatch):
    from sklearn.exceptions import InconsistentVersionWarning

    release_dir = _write_release(tmp_path)
    model_path = release_dir / _MODEL_RELATIVE_PATH
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
    release_dir = _write_release(tmp_path)
    model_path = release_dir / _MODEL_RELATIVE_PATH

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
# Step 14: bounded prediction result and the S0189 operational threshold
# ---------------------------------------------------------------------------


def test_full_governed_prediction_uses_the_resolved_decision_threshold(tmp_path, monkeypatch):
    _write_release(tmp_path, threshold_value=0.31)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    result = rl.execute_governed_external_prediction(_build_request())

    assert result["schema_version"] == "binary-classification-result.v1"
    assert result["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert 0.0 <= result["positive_class_probability"] <= 1.0
    assert result["decision"]["threshold"] == 0.31
    rl.validate_bounded_prediction_result(result)


def test_educational_threshold_never_overrides_operational_threshold(tmp_path, monkeypatch):
    """The fixture bundle's educational_threshold is fixed at 0.99
    (see _write_release); the governed operational threshold below is a
    completely different value. The result must reflect only the governed
    value."""
    _write_release(tmp_path, threshold_value=0.15)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    result = rl.execute_governed_external_prediction(_build_request())

    assert result["decision"]["threshold"] == 0.15
    assert result["decision"]["threshold"] != 0.99


def test_changing_only_the_operational_threshold_flips_predicted_positive_at_the_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    low_threshold_root = tmp_path / "low"
    _write_release(low_threshold_root, threshold_value=0.01)
    monkeypatch.setattr(rl, "RELEASES_ROOT", low_threshold_root)
    low_result = rl.execute_governed_external_prediction(_build_request())
    boundary_probability = low_result["positive_class_probability"]

    high_threshold_root = tmp_path / "high"
    _write_release(high_threshold_root, threshold_value=min(boundary_probability + 0.20, 1.0))
    monkeypatch.setattr(rl, "RELEASES_ROOT", high_threshold_root)
    high_result = rl.execute_governed_external_prediction(_build_request())

    assert low_result["decision"]["predicted_positive"] is True
    assert high_result["decision"]["predicted_positive"] is False


def test_prediction_execution_failure_maps_to_controlled_diagnostic(tmp_path, monkeypatch):
    _write_release(tmp_path)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    request = _build_request(feature_payload=_feature_payload())
    del request["feature_payload"]["MonthlyCharges"]

    try:
        rl.execute_governed_external_prediction(request)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_PREDICTION_EXECUTION_FAILED
