"""Controlled fixture/monkeypatch coverage for the isolated service's
governed release-resolution and load-safe gate
(external-inference/runtime_loader.py), including the Project Spec S0190
bundle-governed operational threshold gate.

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


_FEATURE_ORDER = ["account_age", "monthly_spend", "segment"]
_RELEASE_ID = "release-20260619-001"
_DATASET_SLUG = "synthetic-retention"
_BUNDLE_ID = "synthetic-retention-inference-bundle-test"
_BUNDLE_RELATIVE_PATH = "predictions/bundle.json"
_MODEL_RELATIVE_PATH = "models/model.joblib"
_CONTRACT_RELATIVE_PATH = "contracts/runtime-contract.json"


def _train_fixture_pipeline() -> Pipeline:
    """A tiny, from-scratch pipeline -- never the real Telco Joblib."""
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


def _feature_payload(*, monthly_charges: float = 95.0, total_charges: float = 950.0) -> dict:
    return {"account_age": int(total_charges / 50), "monthly_spend": monthly_charges, "segment": "consumer"}


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
    include_external_model_evidence: bool = True,
    educational_threshold_value: object = 0.31,
    feature_order: list[str] | None = None,
    runtime_features: list[dict] | None = None,
    result_semantics: dict | None = None,
) -> Path:
    """Write a real, governed-resolver-shaped release directory. Returns the
    release directory. Every hash embedded in manifest.json's artifacts[]
    is computed from the actual bytes written. Project Spec S0190:
    `educational_threshold_value` is the bundle's own governed operational
    decisioning threshold source (external_model_evidence.educational_threshold.value)
    -- no run-owned operational-readiness decision artifact exists any
    longer."""
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
        "contract_references": {"runtime_contract": {"contract_version": "1.0.0", "path": "source/not/release/path.json"}},
        "input_schema": {"runtime_contract_reference": "contract_references.runtime_contract", "payload_shape": "runtime_contract_features_object"},
        "feature_order": feature_order or list(_FEATURE_ORDER),
        "output_schema": {"class_labels": ["leave", "stay"], "prediction_type": "number", "probability_output": True},
        "result_semantics": result_semantics or {
            "schema_version": "binary-result-semantics.v1", "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1", "primary_output": "positive_class_probability",
            "positive_class": {"class_id": "leave", "event_label": "Attrition"},
            "decision": {"threshold": educational_threshold_value},
            "interpretation": {"preset": "risk", "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.2},
                {"band_id": "medium", "lower_bound": 0.2, "upper_bound": 0.7},
                {"band_id": "high", "lower_bound": 0.7, "upper_bound": 1.0},
            ]},
            "model_descriptor": {"model_family": "logistic_regression", "display_name": "Synthetic retention classifier"},
        },
    }
    if include_external_model_evidence:
        bundle["external_model_evidence"] = {
            "educational_threshold": {"value": educational_threshold_value, "label": "educational"},
        }
    if provenance is not None:
        bundle["model_provenance_origin"] = provenance
    bundle_text = json.dumps(bundle, indent=2)
    bundle_path = release_dir / _BUNDLE_RELATIVE_PATH
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle_text, encoding="utf-8")
    bundle_sha256 = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()

    runtime_contract = {"schema_version": "1.0.0", "features": runtime_features or [
        {"name": "account_age", "required": True},
        {"name": "monthly_spend", "required": True},
        {"name": "segment", "required": False},
    ]}
    contract_text = json.dumps(runtime_contract, indent=2)
    contract_path = release_dir / _CONTRACT_RELATIVE_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(contract_text, encoding="utf-8")
    contract_sha256 = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()

    artifacts = [
        {
            "role": "contracts",
            "reference": _CONTRACT_RELATIVE_PATH,
            "hash_algorithm": "sha256",
            "hash_value": contract_sha256,
        },
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
    assert preflight["prediction_plan"].threshold == 0.31


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
# Project Spec S0190: bundle-governed operational threshold gate (before loader)
# ---------------------------------------------------------------------------


def test_missing_external_model_evidence_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, include_external_model_evidence=False)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_bundle_threshold_value_out_of_range_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, educational_threshold_value=1.5)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_bundle_threshold_value_non_numeric_fails_before_loader(tmp_path, monkeypatch):
    _write_release(tmp_path, educational_threshold_value="not-a-number")
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)
    _install_load_forbidding_joblib(monkeypatch)

    try:
        rl.run_preflight_gate(_build_request(), tmp_path)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_INFERENCE_BUNDLE_UNAVAILABLE


def test_internal_provenance_still_uses_governed_result_semantics(tmp_path, monkeypatch):
    """A release whose predictive bundle is not validated_external_fitted_model
    never requires bundle-governed threshold evidence at all (Project Spec
    S0190 scopes bundle-threshold resolution to 'a governed
    validated_external_fitted_model release'), and this isolated service's
    historical fallback threshold still applies for it, matching
    'internal/legacy provenance: behavior remains unchanged'."""
    _write_release(tmp_path, provenance=None, include_external_model_evidence=False)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    preflight = rl.run_preflight_gate(_build_request(), tmp_path)
    assert preflight["prediction_plan"].threshold == 0.31

    result = rl.execute_governed_external_prediction(_build_request())
    assert result["decision"]["threshold"] == 0.31


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
# Step 14: bounded prediction result and the S0190 bundle-governed threshold
# ---------------------------------------------------------------------------


def test_full_governed_prediction_uses_the_bundle_governed_threshold(tmp_path, monkeypatch):
    _write_release(tmp_path, educational_threshold_value=0.31)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    result = rl.execute_governed_external_prediction(_build_request())

    assert result["schema_version"] == "binary-classification-result.v1"
    assert result["positive_class"] == {"class_id": "leave", "event_label": "Attrition"}
    assert 0.0 <= result["positive_class_probability"] <= 1.0
    assert result["decision"]["threshold"] == 0.31
    rl.validate_bounded_prediction_result(result)


def test_bundle_declared_threshold_value_is_used_exactly(tmp_path, monkeypatch):
    """The result must reflect exactly the bundle's own declared
    educational_threshold.value -- never this isolated service's
    internal/legacy fallback constant."""
    _write_release(tmp_path, educational_threshold_value=0.15)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    result = rl.execute_governed_external_prediction(_build_request())

    assert result["decision"]["threshold"] == 0.15


def test_changing_only_the_operational_threshold_flips_predicted_positive_at_the_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    low_threshold_root = tmp_path / "low"
    _write_release(low_threshold_root, educational_threshold_value=0.01)
    monkeypatch.setattr(rl, "RELEASES_ROOT", low_threshold_root)
    low_result = rl.execute_governed_external_prediction(_build_request())
    boundary_probability = low_result["positive_class_probability"]

    high_threshold_root = tmp_path / "high"
    _write_release(high_threshold_root, educational_threshold_value=min(boundary_probability + 0.20, 1.0))
    monkeypatch.setattr(rl, "RELEASES_ROOT", high_threshold_root)
    high_result = rl.execute_governed_external_prediction(_build_request())

    assert low_result["decision"]["predicted_positive"] is True
    assert high_result["decision"]["predicted_positive"] is False


def test_prediction_execution_failure_maps_to_controlled_diagnostic(tmp_path, monkeypatch):
    _write_release(tmp_path)
    monkeypatch.setattr(rl, "RELEASES_ROOT", tmp_path)
    monkeypatch.setattr(rl, "observe_isolated_runtime", _matching_observed_runtime)

    request = _build_request(feature_payload=_feature_payload())
    del request["feature_payload"]["monthly_spend"]

    try:
        rl.execute_governed_external_prediction(request)
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT


class _SyntheticMulticlassModel:
    classes_ = ["alpha", "beta", "gamma"]

    def __init__(self, prediction="beta", probabilities=None):
        self.prediction = prediction
        self.probabilities = probabilities or [0.2, 0.6, 0.2]
        self.frame = None

    def predict(self, frame):
        self.frame = frame
        return [self.prediction]

    def predict_proba(self, frame):
        self.frame = frame
        return [self.probabilities]


def _multiclass_plan() -> rl.PredictionPlan:
    classes = (
        {"class_id": "alpha", "display_label": "Alpha"},
        {"class_id": "beta", "display_label": "Beta"},
        {"class_id": "gamma", "display_label": "Gamma"},
    )
    return rl.PredictionPlan(
        result_variant="multiclass",
        feature_order=("zeta", "alpha_feature"),
        required_features=frozenset({"zeta"}),
        output_classes=("alpha", "beta", "gamma"),
        multiclass_classes=classes,
        model_descriptor={"model_family": "decision_tree", "display_name": "Synthetic three-class model"},
    )


def test_multiclass_execution_preserves_governed_order_and_optional_nan():
    model = _SyntheticMulticlassModel()
    result = rl.execute_prediction(model, {"zeta": 4}, _multiclass_plan())

    assert list(model.frame.columns) == ["zeta", "alpha_feature"]
    assert pd.isna(model.frame.iloc[0]["alpha_feature"])
    assert result["predicted_class"] == {"class_id": "beta", "display_label": "Beta"}
    assert [item["class_id"] for item in result["class_probabilities"]] == ["alpha", "beta", "gamma"]
    assert "confidence" not in result and "threshold" not in result and "interpretation" not in result


def test_multiclass_argmax_tie_uses_first_governed_class():
    model = _SyntheticMulticlassModel(prediction="alpha", probabilities=[0.45, 0.45, 0.1])
    result = rl.execute_prediction(model, {"zeta": 4}, _multiclass_plan())
    assert result["predicted_class"]["class_id"] == "alpha"


def test_multiclass_predict_argmax_disagreement_fails_closed():
    model = _SyntheticMulticlassModel(prediction="gamma")
    try:
        rl.execute_prediction(model, {"zeta": 4}, _multiclass_plan())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_PREDICTION_EXECUTION_FAILED


def test_multiclass_model_class_order_is_exact_and_case_sensitive():
    model = _SyntheticMulticlassModel()
    model.classes_ = ["alpha", "Gamma", "beta"]
    try:
        rl.execute_prediction(model, {"zeta": 4}, _multiclass_plan())
        raise AssertionError("expected LoadSafeGateError")
    except rl.LoadSafeGateError as exc:
        assert exc.diagnostic_code == rl.DIAGNOSTIC_PREDICTION_EXECUTION_FAILED
