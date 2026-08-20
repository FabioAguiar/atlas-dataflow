"""Project Spec S0227: continuous-regression candidate assembly and publisher
verification.

Covers, using only synthetic Atlas-owned fixtures under `tmp_path` (never a
real dataset/model file, never `dataset-study-*`, and never any write under
the real repository `releases/candidates/` or `publisher/runs/` trees):

  * native `training-parameter-record.v3` provenance recognition in
    `pipeline/assemble_candidate.py` (source_stage stays M24, never external,
    requires paired `training-metrics.v3`, `analytical-visualizations.v3`
    reservation fails closed against a v1/v2 substitution);
  * `pipeline/release-candidate-input.schema.json`'s additive vocabulary
    extension (v3 admitted, v1/v2/external vocabulary untouched);
  * `continuous-predictive-regression` recognition by the candidate
    release-layer policy and by publisher capability verification, while the
    real committed capability profile stays `requires_future_contract_evolution`
    and therefore still blocked;
  * `publisher/validate.py`'s new native continuous-regression predictive-
    bundle and `training-metrics.v3` compatibility checks;
  * that existing binary/multiclass candidate and publisher behavior is
    unaffected.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate  # noqa: E402
from publisher import validate  # noqa: E402

DATASET_SLUG = "example-continuous-regression-dataset"
RELEASE_ID = "release-20260819-001"
RELEASE_VERSION = "2026.08.19"

REQUIRED_ROLES = (
    "contracts",
    "public_contract",
    "predictive_bundle",
    "model_artifact",
    "metrics",
    "model_card",
    "public_context",
    "visualizations",
    "manifest_input",
    "candidate_metadata",
)

MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-not-a-real-model"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()
MODEL_ARTIFACT_PATH = "models/model.pkl"

CAPABILITY_PROFILE_PATH = (
    REPO_ROOT / "pipeline" / "capabilities" / "continuous-predictive-regression.v1.json"
)
RELEASE_CANDIDATE_INPUT_SCHEMA_PATH = (
    REPO_ROOT / "pipeline" / "release-candidate-input.schema.json"
)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# Section A: native training-parameter-record.v3 candidate provenance
# recognition (pipeline/assemble_candidate.py)
# ===========================================================================


def _write_handoff_governed_artifacts(repo_root: Path) -> dict:
    paths = {
        "discovery_evidence": "governed-artifacts/m22/discovery-evidence.json",
        "execution_contract": "governed-artifacts/m23/execution-contract.json",
        "runtime_contract": "governed-artifacts/m23/runtime-contract.json",
        "public_contract": "governed-artifacts/m23/public-contract.json",
        "preparation_recipe": "governed-artifacts/m22/preparation-recipe.json",
        "prepared_data_metadata": "governed-artifacts/m23/prepared-data-metadata.json",
        "training_parameter_record": "governed-artifacts/m24/training-parameter-record.json",
        "model_artifact": "governed-artifacts/m24/model.pkl",
        "training_metrics": "governed-artifacts/m24/metrics.json",
        "model_card": "governed-artifacts/m24/model-card.json",
        "public_context": "governed-artifacts/m23/public-context.json",
        "visualizations": "governed-artifacts/m24/visualizations.json",
        "inference_bundle": "governed-artifacts/m25/bundle.json",
    }
    for role, relative in paths.items():
        _write_json(repo_root / relative, {"role": role, "governed": True})
    return paths


_VALID_PUBLIC_CONTRACT = {
    "schema_version": "1.0.0",
    "features": [
        {
            "name": "example_feature",
            "label": "Example Feature",
            "input_type": "number",
            "optional": False,
            "display_order": 1,
        }
    ],
}


def _finish_inference_bundle_reference(repo_root: Path, paths: dict) -> None:
    model_artifact_sha256 = hashlib.sha256((repo_root / paths["model_artifact"]).read_bytes()).hexdigest()
    _write_json(repo_root / paths["inference_bundle"], {
        "role": "inference_bundle",
        "schema_version": "inference_bundle.v1",
        "model_artifact": {"path": "models/model.pkl", "sha256": model_artifact_sha256},
    })


def _write_v1_internal_governed_artifacts(repo_root: Path) -> dict:
    paths = _write_handoff_governed_artifacts(repo_root)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(repo_root / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    _write_json(repo_root / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
    })
    _write_json(repo_root / paths["training_metrics"], {"schema_version": "training-metrics.v1"})
    _write_json(repo_root / paths["model_card"], {"schema_version": "model-card.v1"})
    _write_json(repo_root / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(repo_root / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(repo_root / paths["visualizations"], {"schema_version": "analytical-visualizations.v1"})
    _finish_inference_bundle_reference(repo_root, paths)
    return paths


def _write_v3_regression_governed_artifacts(
    repo_root: Path,
    *,
    training_metrics_version: str = "training-metrics.v3",
    visualizations_version: str = "analytical-visualizations.v3",
) -> dict:
    paths = _write_handoff_governed_artifacts(repo_root)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(repo_root / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    _write_json(repo_root / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v3",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
    })
    _write_json(repo_root / paths["training_metrics"], {
        "schema_version": training_metrics_version,
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
    })
    _write_json(repo_root / paths["model_card"], {"schema_version": "model-card-input.v3"})
    _write_json(repo_root / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(repo_root / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(repo_root / paths["visualizations"], {"schema_version": visualizations_version})
    _finish_inference_bundle_reference(repo_root, paths)
    return paths


def _build_v3_candidate_input(tmp_path: Path, **overrides):
    tmp_repo = tmp_path / "repo"
    paths = _write_v3_regression_governed_artifacts(tmp_repo, **overrides)
    return assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="native-regression-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )


def test_native_v3_provenance_recognized_explicitly(tmp_path):
    candidate_input = _build_v3_candidate_input(tmp_path)

    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["contract_version"] == "training-parameter-record.v3"
    tm = candidate_input["artifact_inputs"]["training_metrics"]
    assert tm["contract_version"] == "training-metrics.v3"


def test_native_v3_provenance_keeps_source_stage_m24(tmp_path):
    candidate_input = _build_v3_candidate_input(tmp_path)

    assert candidate_input["artifact_inputs"]["training_parameter_record"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["training_metrics"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_card"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_artifact"]["source_stage"] == "M24"


def test_native_v3_provenance_never_external_or_manual_governed_input(tmp_path):
    candidate_input = _build_v3_candidate_input(tmp_path)

    for artifact_input in candidate_input["artifact_inputs"]["internal_evidence_references"]:
        assert artifact_input["source_stage"] != "manual_governed_input"
        assert artifact_input["role"] != "external_model_evidence"


def test_native_v3_carries_real_v3_visualizations_version_when_reserved(tmp_path):
    candidate_input = _build_v3_candidate_input(tmp_path)

    assert (
        candidate_input["artifact_inputs"]["visualizations"]["contract_version"]
        == "analytical-visualizations.v3"
    )


def test_v3_record_requires_paired_v3_metrics_v1_pairing_rejects(tmp_path):
    with pytest.raises(ValueError, match="training_metrics"):
        _build_v3_candidate_input(tmp_path, training_metrics_version="training-metrics.v1")


def test_v3_record_requires_paired_v3_metrics_v2_pairing_rejects(tmp_path):
    with pytest.raises(ValueError, match="training_metrics"):
        _build_v3_candidate_input(tmp_path, training_metrics_version="training-metrics.v2")


def test_v3_visualization_reservation_fails_closed_against_v1_substitution(tmp_path):
    with pytest.raises(ValueError, match="visualizations"):
        _build_v3_candidate_input(tmp_path, visualizations_version="analytical-visualizations.v1")


def test_v3_visualization_reservation_fails_closed_against_v2_substitution(tmp_path):
    with pytest.raises(ValueError, match="visualizations"):
        _build_v3_candidate_input(tmp_path, visualizations_version="analytical-visualizations.v2")


def test_legacy_internal_v1_provenance_remains_unchanged(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_v1_internal_governed_artifacts(tmp_repo)
    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="internal-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )
    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["source_stage"] == "M24"
    assert tpr["contract_version"] == "training-parameter-record.v1"
    tm = candidate_input["artifact_inputs"]["training_metrics"]
    assert tm["contract_version"] == "training-metrics.v1"


def test_native_multiclass_v2_provenance_remains_unchanged(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(tmp_repo / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    ordered_class_ids = ["a", "b", "c"]
    _write_json(tmp_repo / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v2",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": ordered_class_ids,
        },
    })
    _write_json(tmp_repo / paths["training_metrics"], {
        "schema_version": "training-metrics.v2",
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": ordered_class_ids,
        },
    })
    _write_json(tmp_repo / paths["model_card"], {"schema_version": "model-card-input.v2"})
    _write_json(tmp_repo / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(tmp_repo / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(tmp_repo / paths["visualizations"], {"schema_version": "analytical-visualizations.v2"})
    _finish_inference_bundle_reference(tmp_repo, paths)

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="native-multiclass-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )
    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["source_stage"] == "M24"
    assert tpr["contract_version"] == "training-parameter-record.v2"
    assert candidate_input["artifact_inputs"]["visualizations"]["contract_version"] == "analytical-visualizations.v2"


# ===========================================================================
# Section B: release-candidate-input.schema.json additive vocabulary
# ===========================================================================


def test_schema_admits_v3_training_record_and_metrics_and_reserved_visualization(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())

    candidate_input = _build_v3_candidate_input(tmp_path)

    jsonschema.validate(candidate_input, schema)


def test_schema_remains_backward_compatible_with_v1_legacy_instance(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())

    tmp_repo = tmp_path / "repo"
    paths = _write_v1_internal_governed_artifacts(tmp_repo)
    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="internal-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )

    jsonschema.validate(candidate_input, schema)


def test_schema_does_not_remove_or_expand_external_fitted_model_vocabulary():
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())
    record_enum = schema["properties"]["artifact_inputs"]["properties"]["training_parameter_record"][
        "allOf"
    ][1]["properties"]["contract_version"]["enum"]
    metrics_enum = schema["properties"]["artifact_inputs"]["properties"]["training_metrics"]["allOf"][1][
        "properties"
    ]["contract_version"]["enum"]

    assert "training-parameter-record.v1" in record_enum
    assert "training-parameter-record.v2" in record_enum
    assert "training-parameter-record.v3" in record_enum
    assert "training-parameter-record.external-fitted-model.v1" in record_enum
    assert "training-parameter-record.external-fitted-model.v2" not in record_enum

    assert "training-metrics.v1" in metrics_enum
    assert "training-metrics.v2" in metrics_enum
    assert "training-metrics.v3" in metrics_enum
    assert "training-metrics.external-fitted-model.v1" in metrics_enum
    assert "training-metrics.external-fitted-model.v2" not in metrics_enum


def test_schema_reserves_analytical_visualizations_v3_vocabulary_only():
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())
    visualizations_prop = schema["properties"]["artifact_inputs"]["properties"]["visualizations"][
        "allOf"
    ][1]["properties"]["contract_version"]
    assert visualizations_prop["enum"] == [
        "analytical-visualizations.v1",
        "analytical-visualizations.v2",
        "analytical-visualizations.v3",
    ]


# ===========================================================================
# Section C: continuous-predictive-regression recognized by candidate
# release-layer identity set, while the real committed profile remains
# blocked (support_status unchanged).
# ===========================================================================


def _load_real_continuous_regression_profile() -> dict:
    return json.loads(CAPABILITY_PROFILE_PATH.read_text(encoding="utf-8"))


def test_real_continuous_regression_capability_profile_support_status_is_current_supported():
    # Project Spec S0229: flipped from requires_future_contract_evolution to
    # current_supported -- the Result Card/Inference Form/public metrics/
    # publisher-compatibility boundaries S0222/S0227 deferred are now complete.
    profile = _load_real_continuous_regression_profile()
    assert profile["capability_profile_id"] == "continuous-predictive-regression"
    assert profile["support_status"] == "current_supported"


def test_continuous_capability_identity_is_a_recognized_release_layer_identity():
    assert (
        "continuous-predictive-regression"
        in assemble_candidate.RELEASE_LAYER_SUPPORTED_CAPABILITY_PROFILE_IDS
    )


def test_real_continuous_regression_profile_now_accepted_by_release_policy():
    # Project Spec S0229: the real, unmodified profile file on disk now
    # proves release-layer identity+support-status acceptance directly --
    # no synthetic current-supported clone is needed for this gate anymore.
    profile = _load_real_continuous_regression_profile()
    capability_binding = {
        "capability_profile_id": profile["capability_profile_id"],
        "capability_profile_version": profile["capability_profile_version"],
        "resolved_role_policy": [],
    }

    result = assemble_candidate.resolve_capability_release_policy(capability_binding, profile)

    assert result.status == "accepted"
    assert result.capability_profile_id == "continuous-predictive-regression"


# ===========================================================================
# Section D: publisher capability/problem-type map and independent capability
# binding verification (publisher/validate.py).
# ===========================================================================


def test_publisher_recognizes_continuous_predictive_regression_identity():
    assert "continuous-predictive-regression" in validate._SUPPORTED_CAPABILITY_IDENTITIES


def test_publisher_capability_map_maps_exactly_to_continuous_regression():
    assert (
        validate._CAPABILITY_EXPECTED_RESULT_PROBLEM_TYPE["continuous-predictive-regression"]
        == "continuous_regression"
    )


def _write_capability_profile_and_binding(
    tmp_path: Path, profile: dict, *, resolved_role_policy=None
) -> dict:
    profile_path = tmp_path / "governed" / "capability-profile.json"
    _write_json(profile_path, profile)
    profile_sha256 = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    return {
        "capability_profile_id": profile["capability_profile_id"],
        "capability_profile_version": profile["capability_profile_version"],
        "capability_profile_ref": {
            "path": "governed/capability-profile.json",
            "sha256": profile_sha256,
        },
        "resolved_role_policy": resolved_role_policy or [],
    }


def test_verify_capability_binding_accepts_synthetic_current_supported_regression_profile(tmp_path):
    profile = dict(_load_real_continuous_regression_profile())
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "continuous_regression"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert reasons == []


def test_verify_capability_binding_accepts_real_regression_support_status(tmp_path):
    # Project Spec S0229: the real, unmodified profile is now
    # current_supported, so a matching problem type no longer produces an
    # unsupported-status rejection reason.
    profile = _load_real_continuous_regression_profile()
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "continuous_regression"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert reasons == []


def test_verify_capability_binding_rejects_problem_type_mismatch(tmp_path):
    profile = dict(_load_real_continuous_regression_profile())
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "binary_classification"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert len(reasons) == 1
    assert reasons[0]["code"] == validate._CAPABILITY_BINDING_RESULT_PROBLEM_TYPE_MISMATCH_CODE


def test_verify_capability_binding_rejects_unknown_identity(tmp_path):
    profile = dict(_load_real_continuous_regression_profile())
    profile["capability_profile_id"] = "unknown-future-capability"
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}

    reasons = validate._verify_capability_binding(candidate, tmp_path, None)

    assert len(reasons) == 1
    assert reasons[0]["code"] == validate._CAPABILITY_BINDING_UNSUPPORTED_CAPABILITY_CODE


# ===========================================================================
# Section E/F: native continuous-regression predictive-bundle and
# training-metrics.v3 publisher compatibility (publisher/validate.py).
# ===========================================================================


def _valid_visualizations_payload(**overrides) -> dict:
    payload = {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260819T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260819T000000Z/",
        },
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "Value", "y_label": "Rows",
                "data": [{"name": "bucket-1", "value": 3}, {"name": "bucket-2", "value": 1}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "example_feature", "value": 1.0}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset", "row_count": 4, "target_column": "example_target",
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    payload.update(overrides)
    return payload


def _valid_v3_regression_visualizations_payload(**overrides) -> dict:
    """Synthetic, Atlas-owned analytical-visualizations.v3 evidence for a
    native continuous-regression candidate, mirroring the reference fixture
    shape validated by the dedicated S0228 analytical-visualizations test
    module (schema_version, regression_evidence identity, and bounded
    actual_vs_predicted/residual_distribution diagnostics sourced from the
    sealed test partition, both summing to row_count=4)."""
    payload = {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260819T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260819T000000Z/",
        },
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "outcome", "y_label": "Rows",
                "data": [{"name": "0 to 10", "value": 3}, {"name": "10 to 20", "value": 1}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "example_feature", "value": 1.0}],
            },
        ],
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 4,
            "target_column": "example_target",
            "bin_count": 2,
            "min_value": 1.0,
            "max_value": 15.0,
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test",
            "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width_actual_bins",
            "reference_line": "identity",
            "points": [{"actual_mean": 5.0, "predicted_mean": 5.2, "count": 4}],
        },
        "residual_distribution": {
            "partition_role": "test",
            "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [{"label": "-1 to 1", "lower_bound": -1.0, "upper_bound": 1.0, "count": 4}],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    payload.update(overrides)
    return payload


def _artifact_payload(role: str, **overrides) -> dict:
    if role == "public_contract":
        payload = dict(_VALID_PUBLIC_CONTRACT)
        payload.update(overrides)
        return payload
    if role == "visualizations":
        # Explicit, deterministic dispatch on the caller's own declared
        # schema_version -- never inferred from dataset slug. Binary/
        # multiclass candidates keep the legitimate v1 default (or an
        # explicit v2 override); native continuous-regression candidates
        # pass an explicit analytical-visualizations.v3 payload.
        if overrides.get("schema_version") == "analytical-visualizations.v3":
            return _valid_v3_regression_visualizations_payload(**overrides)
        return _valid_visualizations_payload(**overrides)
    payload = {
        "role": role,
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "availability_status": "real_dataflow_artifact",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
    }
    if role in {"metrics", "model_card", "predictive_bundle"}:
        payload["model_id"] = "model-example-001"
    if role == "predictive_bundle":
        payload["runtime_contract_ref"] = "artifacts/contracts.json"
        payload["model_artifact"] = {"path": MODEL_ARTIFACT_PATH, "sha256": MODEL_ARTIFACT_SHA256}
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
    payload.update(overrides)
    return payload


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _candidate_dir(tmp_path: Path) -> Path:
    return tmp_path / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID


def _write_candidate(tmp_path: Path, *, artifact_overrides: dict | None = None) -> Path:
    artifact_overrides = artifact_overrides or {}
    candidate_dir = _candidate_dir(tmp_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        if role == "model_artifact":
            (candidate_dir / role_path).parent.mkdir(parents=True, exist_ok=True)
            (candidate_dir / role_path).write_bytes(MODEL_ARTIFACT_BYTES)
            continue
        _write_json(candidate_dir / role_path, _artifact_payload(role, **artifact_overrides.get(role, {})))

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Example Continuous Dataset"},
        "release_identity": {
            "release_id": RELEASE_ID, "release_version": RELEASE_VERSION, "created_at": "2026-08-19T00:00:00Z",
        },
        "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-08-19T00:00:00Z"},
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-08-19T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": list(REQUIRED_ROLES),
                "hash_policy": "publisher_calculates_hashes",
                "manifest_policy": "publisher_generates_manifest",
            },
        },
        "state_boundaries": {
            "pipeline_run_is_publishable": False,
            "candidate_is_published_release": False,
            "promotion_required": True,
            "registry_update_allowed_in_candidate": False,
            "public_upload_required": False,
            "web_administration_required": False,
            "database_publication_management_required": False,
            "runtime_consumes_temporary_pipeline_output": False,
        },
    }
    _write_json(candidate_dir / "release-candidate.json", candidate)
    return candidate_dir


def _rejection_safe_details(result: dict) -> set:
    return {reason["safe_detail"] for reason in result["rejection_reasons"] if "safe_detail" in reason}


def _regression_result_semantics(**overrides) -> dict:
    semantics = {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "result_schema_version": "continuous-regression-result.v1",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }
    semantics.update(overrides)
    return semantics


def _regression_predictive_bundle_overrides(
    *,
    result_semantics_overrides: dict | None = None,
    output_schema_overrides: dict | None = None,
    model_provenance_origin: str = "atlas_internal_training",
    extra_top_level: dict | None = None,
) -> dict:
    result_semantics = _regression_result_semantics(**(result_semantics_overrides or {}))
    output_schema = {"prediction_key": "prediction", "prediction_type": "number"}
    output_schema.update(output_schema_overrides or {})
    overrides = {
        "result_semantics": result_semantics,
        "output_schema": output_schema,
        "model_provenance_origin": model_provenance_origin,
        "training_evidence": {"training_run_identity": {"dataset_slug": DATASET_SLUG}},
    }
    if extra_top_level:
        overrides.update(extra_top_level)
    return overrides


def _regression_metrics_overrides(
    *,
    schema_version: str = "training-metrics.v3",
    regression_evidence_overrides: dict | None = None,
    final_test_metrics: list | None = None,
    final_test_completed: bool = True,
    final_test_row_count: int = 4,
    validation_metrics: list | None = None,
) -> dict:
    regression_evidence = {
        "problem_type": "continuous_regression",
        "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
        "output_value_kind": "continuous_numeric",
    }
    regression_evidence.update(regression_evidence_overrides or {})
    if final_test_metrics is None:
        final_test_metrics = [{"name": "r2", "value": 0.8}, {"name": "mae", "value": 2.1}]
    if validation_metrics is None:
        validation_metrics = [{"name": "r2", "value": 0.7}, {"name": "mae", "value": 2.5}]
    return {
        "schema_version": schema_version,
        "regression_evidence": regression_evidence,
        "final_test_evaluation": {
            "partition_role": "test",
            "completed": final_test_completed,
            # Matches _valid_v3_regression_visualizations_payload()'s
            # actual_vs_predicted/residual_distribution aggregate population
            # (points/bins summing to 4) so the publisher's diagnostic
            # population cross-check agrees when a completed final-test
            # evaluation is present.
            "row_count": final_test_row_count,
            "metrics": final_test_metrics if final_test_completed else [],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "metrics": validation_metrics,
        },
    }


def test_native_continuous_regression_bundle_accepts_bounded_semantics(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(),
            "visualizations": _valid_v3_regression_visualizations_payload(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]
    assert "native_continuous_regression_result_semantics_missing" not in _rejection_safe_details(result)
    assert "native_continuous_regression_classification_semantics_present" not in _rejection_safe_details(result)


@pytest.mark.parametrize(
    "result_semantics_field,value",
    [
        ("positive_class", {"class_id": "x", "event_label": "y"}),
        ("negative_class", {"class_id": "x", "event_label": "y"}),
        ("classes", [{"class_id": "a"}, {"class_id": "b"}]),
        ("class_probabilities", "class_a_probability"),
        ("probability_output", True),
        ("decision", {"strategy": "argmax"}),
        ("decision", {"threshold": 0.5}),
    ],
)
def test_native_continuous_regression_bundle_rejects_classification_only_fields(
    tmp_path, result_semantics_field, value
):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={result_semantics_field: value}
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_continuous_regression_classification_semantics_present" in _rejection_safe_details(result)


@pytest.mark.parametrize("threshold_field", ["educational_threshold", "operational_threshold"])
def test_native_continuous_regression_bundle_rejects_top_level_threshold_fields(tmp_path, threshold_field):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                extra_top_level={threshold_field: {"value": 0.5}}
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_continuous_regression_classification_semantics_present" in _rejection_safe_details(result)


def test_native_continuous_regression_bundle_wrong_result_schema_version_rejects(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={"schema_version": "continuous-regression-result-semantics.v0"}
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_continuous_regression_result_semantics_missing" in _rejection_safe_details(result)


def test_native_continuous_regression_bundle_wrong_output_prediction_type_rejects(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                output_schema_overrides={"prediction_type": "string"}
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_continuous_regression_prediction_type_mismatch" in _rejection_safe_details(result)


def test_native_continuous_regression_bundle_wrong_provenance_rejects(tmp_path):
    # A provenance value other than "atlas_internal_training" and other than
    # "validated_external_fitted_model" (which would instead reroute this
    # candidate to the entirely separate external compatibility path) still
    # exercises the native path's own provenance requirement.
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                model_provenance_origin="unspecified_training_origin"
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_continuous_regression_provenance_mismatch" in _rejection_safe_details(result)


def test_native_continuous_regression_bundle_external_provenance_reroutes_to_external_checks(tmp_path):
    # Explicit confirmation that S0227 adds no external fitted-model
    # regression branch: a regression bundle declaring
    # validated_external_fitted_model provenance is rejected by the
    # existing external compatibility checks (which require binary/
    # multiclass result_semantics), never accepted through a new regression
    # carve-out.
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                model_provenance_origin="validated_external_fitted_model"
            ),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    safe_details = _rejection_safe_details(result)
    assert "external_result_semantics_missing" in safe_details
    assert not any(detail.startswith("native_continuous_regression") for detail in safe_details)


def test_no_external_fitted_model_regression_branch_exists():
    # Project Spec S0227 desired change E: no external fitted-model
    # regression compatibility function is added.
    assert not hasattr(validate, "_external_continuous_regression_predictive_bundle_compatibility")


# ===========================================================================
# Section F/J (Project Spec S0232): native HGB continuous-regression bundle
# acceptance and bundle <-> visualizations model-family agreement.
# ===========================================================================


def _hgb_model_descriptor() -> dict:
    return {"model_family": "hist_gradient_boosting", "display_name": "HistGradientBoosting"}


def _hgb_permutation_feature_importance_method(**overrides) -> dict:
    method = {
        "model_family": "hist_gradient_boosting",
        "source": "sklearn.inspection.permutation_importance",
        "method": "permutation_importance",
        "population_kind": "final_fit_train_plus_validation",
        "scoring": "neg_mean_absolute_error",
        "n_repeats": 5,
        "random_seed": 42,
        "total_source_feature_count": 1,
        "omitted_source_feature_count": 0,
        "public_row_limit": 10,
    }
    method.update(overrides)
    return method


def test_native_hist_gradient_boosting_candidate_accepted(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={"model_descriptor": _hgb_model_descriptor()}
            ),
            "metrics": _regression_metrics_overrides(),
            "visualizations": _valid_v3_regression_visualizations_payload(
                feature_importance_method=_hgb_permutation_feature_importance_method()
            ),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]
    assert "native_regression_model_family_mismatch" not in _rejection_safe_details(result)


def test_native_regression_model_family_mismatch_hgb_bundle_gradient_boosting_visualizations_rejected(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={"model_descriptor": _hgb_model_descriptor()}
            ),
            "metrics": _regression_metrics_overrides(),
            # Default v3 visualizations declare feature_importance_method.model_family
            # = gradient_boosting.
            "visualizations": _valid_v3_regression_visualizations_payload(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_model_family_mismatch" in _rejection_safe_details(result)


@pytest.mark.parametrize("bundle_model_family", ["gradient_boosting", "random_forest"])
def test_native_regression_model_family_mismatch_direct_bundle_hgb_visualizations_rejected(
    tmp_path, bundle_model_family
):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={
                    "model_descriptor": {
                        "model_family": bundle_model_family,
                        "display_name": bundle_model_family.replace("_", " ").title(),
                    }
                }
            ),
            "metrics": _regression_metrics_overrides(),
            "visualizations": _valid_v3_regression_visualizations_payload(
                feature_importance_method=_hgb_permutation_feature_importance_method()
            ),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_model_family_mismatch" in _rejection_safe_details(result)


def test_native_hist_gradient_boosting_candidate_rejects_v1_visualizations(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(
                result_semantics_overrides={"model_descriptor": _hgb_model_descriptor()}
            ),
            "metrics": _regression_metrics_overrides(),
            # No "visualizations" override -> defaults to the legacy v1 payload.
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_visualizations_version_mismatch" in _rejection_safe_details(result)


def test_native_continuous_regression_metrics_v3_accepted(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(),
            "visualizations": _valid_v3_regression_visualizations_payload(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]
    assert "native_regression_metrics_schema_version_missing" not in _rejection_safe_details(result)
    assert "native_regression_metrics_no_public_metric" not in _rejection_safe_details(result)


def test_native_continuous_regression_metrics_wrong_schema_version_rejects(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(schema_version="training-metrics.v2"),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_metrics_schema_version_missing" in _rejection_safe_details(result)


@pytest.mark.parametrize(
    "regression_evidence_overrides",
    [
        {"problem_type": "binary_classification"},
        {"result_semantics_schema_version": "continuous-regression-result-semantics.v0"},
        {"output_value_kind": "discrete_count"},
    ],
)
def test_native_continuous_regression_metrics_wrong_regression_evidence_rejects(
    tmp_path, regression_evidence_overrides
):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(
                regression_evidence_overrides=regression_evidence_overrides
            ),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_metrics_evidence_mismatch" in _rejection_safe_details(result)


def test_native_continuous_regression_metrics_no_projectable_metric_rejects(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(
                final_test_metrics=[{"name": "mape", "value": 12.0}, {"name": "explained_variance", "value": 0.5}],
                validation_metrics=[{"name": "mape", "value": 15.0}],
            ),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_metrics_no_public_metric" in _rejection_safe_details(result)


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf"), True],
)
def test_native_continuous_regression_metrics_non_finite_or_boolean_metric_rejects(tmp_path, bad_value):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(
                final_test_metrics=[{"name": "r2", "value": bad_value}],
                validation_metrics=[{"name": "r2", "value": bad_value}],
            ),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "native_regression_metrics_no_public_metric" in _rejection_safe_details(result)


def test_native_continuous_regression_metrics_prefers_completed_final_test(tmp_path):
    # Only the final-test partition carries a projectable metric; validation
    # carries none -- acceptance proves final_test_evaluation was selected.
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(
                final_test_metrics=[{"name": "r2", "value": 0.9}],
                validation_metrics=[{"name": "mape", "value": 99.0}],
            ),
            "visualizations": _valid_v3_regression_visualizations_payload(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]


def test_native_continuous_regression_metrics_falls_back_to_validation_when_incomplete(tmp_path):
    # final_test_evaluation.completed is False -- only validation carries a
    # projectable metric; acceptance proves validation_evaluation was
    # selected instead of an incomplete/empty final test.
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(
                final_test_completed=False,
                validation_metrics=[{"name": "rmse", "value": 3.3}],
            ),
            "visualizations": _valid_v3_regression_visualizations_payload(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]


def test_native_continuous_regression_never_confused_with_external_provenance_checks(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": _regression_predictive_bundle_overrides(),
            "metrics": _regression_metrics_overrides(),
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    safe_details = _rejection_safe_details(result)
    assert not any(detail.startswith("external_") for detail in safe_details)
    assert not any(detail.startswith("native_multiclass") for detail in safe_details)


# ===========================================================================
# Existing binary/multiclass targeted candidate/publisher behavior remains
# unaffected by the S0227 additions above.
# ===========================================================================


def test_existing_binary_candidate_accepted_unchanged(tmp_path):
    candidate_dir = _write_candidate(tmp_path)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]


MULTICLASS_ORDERED_CLASS_IDS = ["class-a", "class-b", "class-c"]


def test_existing_native_multiclass_candidate_accepted_unchanged(tmp_path):
    predictive_bundle_overrides = {
        "result_semantics": {
            "schema_version": "multiclass-result-semantics.v1",
            "problem_type": "multiclass_classification",
            "classes": [{"class_id": cid, "display_label": cid} for cid in MULTICLASS_ORDERED_CLASS_IDS],
            "primary_output": "predicted_class",
            "probability_output": "class_probabilities",
            "decision": {"strategy": "argmax"},
        },
        "training_evidence": {"training_run_identity": {"dataset_slug": DATASET_SLUG}},
        "output_schema": {
            "prediction_key": "prediction",
            "prediction_type": "string",
            "class_labels": MULTICLASS_ORDERED_CLASS_IDS,
            "probability_output": True,
        },
    }
    metrics_overrides = {
        "schema_version": "training-metrics.v2",
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": MULTICLASS_ORDERED_CLASS_IDS,
        },
        "final_test_evaluation": {
            "partition_role": "test", "completed": True, "metrics": [{"name": "f1_macro", "value": 0.9}],
        },
    }
    visualizations_overrides = {
        "schema_version": "analytical-visualizations.v2",
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": MULTICLASS_ORDERED_CLASS_IDS,
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "sklearn.inspection.permutation_importance",
            "method": "permutation_importance",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "confusion_matrix": {
            "ordered_class_ids": MULTICLASS_ORDERED_CLASS_IDS,
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "row_axis": "true_class", "column_axis": "predicted_class",
        },
    }
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "predictive_bundle": predictive_bundle_overrides,
            "metrics": metrics_overrides,
            "visualizations": visualizations_overrides,
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]


# ===========================================================================
# No real candidate/release/publisher run is written to disk by this module.
# ===========================================================================


def test_no_real_candidate_directory_created_under_real_repository_tree():
    assert not (REPO_ROOT / "releases" / "candidates" / DATASET_SLUG).exists()
