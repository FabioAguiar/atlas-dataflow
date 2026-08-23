"""Project Spec S0247: univariate-forecasting candidate assembly and
publisher verification.

Covers, using only synthetic Atlas-owned fixtures under `tmp_path` (never a
real dataset/model file, never `dataset-study-*`, and never any write under
the real repository `releases/candidates/` or `publisher/runs/` trees):

  * native `training-parameter-record.v4` provenance recognition in
    `pipeline/assemble_candidate.py` (source_stage stays M24, never external,
    requires paired `training-metrics.v4`, `analytical-visualizations.v4`
    reservation fails closed against a v1/v2/v3 substitution);
  * `pipeline/release-candidate-input.schema.json`'s additive vocabulary
    extension (v4 admitted, v1/v2/v3/external vocabulary untouched);
  * `univariate-predictive-forecasting` recognition by the candidate
    release-layer policy and by publisher capability verification, while the
    real committed capability profile stays `requires_future_contract_evolution`
    and therefore still blocked (never flipped by this spec);
  * `publisher/validate.py`'s new native forecasting predictive-bundle,
    `training-metrics.v4`, and `analytical-visualizations.v4`-reservation
    compatibility checks;
  * that S0247 does not define real `analytical-visualizations.v4` schema
    content, so a real forecasting candidate remains blocked end to end even
    when its bundle/metrics are otherwise fully compliant;
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

DATASET_SLUG = "example-forecasting-dataset"
RELEASE_ID = "release-20260823-001"
RELEASE_VERSION = "2026.08.23"

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
    REPO_ROOT / "pipeline" / "capabilities" / "univariate-predictive-forecasting.v1.json"
)
RELEASE_CANDIDATE_INPUT_SCHEMA_PATH = (
    REPO_ROOT / "pipeline" / "release-candidate-input.schema.json"
)
ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = (
    REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"
)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# Section A: native training-parameter-record.v4 candidate provenance
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


def _write_v4_forecasting_governed_artifacts(
    repo_root: Path,
    *,
    training_metrics_version: str = "training-metrics.v4",
    visualizations_version: str = "analytical-visualizations.v4",
) -> dict:
    paths = _write_handoff_governed_artifacts(repo_root)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(repo_root / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    _write_json(repo_root / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v4",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "training_policy_schema_version": "univariate-forecasting-training-policy.v1",
        },
    })
    _write_json(repo_root / paths["training_metrics"], {
        "schema_version": training_metrics_version,
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "forecast_horizon": 6,
        },
    })
    _write_json(repo_root / paths["model_card"], {"schema_version": "model-card-input.v4"})
    _write_json(repo_root / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(repo_root / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(repo_root / paths["visualizations"], {"schema_version": visualizations_version})
    _finish_inference_bundle_reference(repo_root, paths)
    return paths


def _build_v4_candidate_input(tmp_path: Path, **overrides):
    tmp_repo = tmp_path / "repo"
    paths = _write_v4_forecasting_governed_artifacts(tmp_repo, **overrides)
    return assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="native-forecasting-run-20260823T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )


def test_native_v4_provenance_recognized_explicitly(tmp_path):
    candidate_input = _build_v4_candidate_input(tmp_path)

    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["contract_version"] == "training-parameter-record.v4"
    tm = candidate_input["artifact_inputs"]["training_metrics"]
    assert tm["contract_version"] == "training-metrics.v4"


def test_native_v4_provenance_keeps_source_stage_m24(tmp_path):
    candidate_input = _build_v4_candidate_input(tmp_path)

    assert candidate_input["artifact_inputs"]["training_parameter_record"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["training_metrics"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_card"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_artifact"]["source_stage"] == "M24"


def test_native_v4_provenance_never_external_or_manual_governed_input(tmp_path):
    candidate_input = _build_v4_candidate_input(tmp_path)

    for artifact_input in candidate_input["artifact_inputs"]["internal_evidence_references"]:
        assert artifact_input["source_stage"] != "manual_governed_input"
        assert artifact_input["role"] != "external_model_evidence"


def test_native_v4_carries_real_v4_visualizations_version_when_reserved(tmp_path):
    candidate_input = _build_v4_candidate_input(tmp_path)

    assert (
        candidate_input["artifact_inputs"]["visualizations"]["contract_version"]
        == "analytical-visualizations.v4"
    )


@pytest.mark.parametrize(
    "training_metrics_version",
    ["training-metrics.v1", "training-metrics.v2", "training-metrics.v3"],
)
def test_v4_record_requires_paired_v4_metrics_cross_version_pairing_rejects(tmp_path, training_metrics_version):
    with pytest.raises(ValueError, match="training_metrics"):
        _build_v4_candidate_input(tmp_path, training_metrics_version=training_metrics_version)


@pytest.mark.parametrize(
    "visualizations_version",
    ["analytical-visualizations.v1", "analytical-visualizations.v2", "analytical-visualizations.v3"],
)
def test_v4_visualization_reservation_fails_closed_against_substitution(tmp_path, visualizations_version):
    with pytest.raises(ValueError, match="visualizations"):
        _build_v4_candidate_input(tmp_path, visualizations_version=visualizations_version)


def test_legacy_internal_v1_provenance_remains_unchanged(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_v1_internal_governed_artifacts(tmp_repo)
    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="internal-run-20260823T000000Z",
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
        source_run_id="native-multiclass-run-20260823T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )
    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["source_stage"] == "M24"
    assert tpr["contract_version"] == "training-parameter-record.v2"
    assert candidate_input["artifact_inputs"]["visualizations"]["contract_version"] == "analytical-visualizations.v2"


def test_native_continuous_regression_v3_provenance_remains_unchanged(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(tmp_repo / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    regression_evidence = {
        "problem_type": "continuous_regression",
        "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
        "output_value_kind": "continuous_numeric",
    }
    _write_json(tmp_repo / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v3",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "regression_evidence": regression_evidence,
    })
    _write_json(tmp_repo / paths["training_metrics"], {
        "schema_version": "training-metrics.v3",
        "regression_evidence": regression_evidence,
    })
    _write_json(tmp_repo / paths["model_card"], {"schema_version": "model-card-input.v3"})
    _write_json(tmp_repo / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(tmp_repo / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(tmp_repo / paths["visualizations"], {"schema_version": "analytical-visualizations.v3"})
    _finish_inference_bundle_reference(tmp_repo, paths)

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="native-regression-run-20260823T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )
    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["source_stage"] == "M24"
    assert tpr["contract_version"] == "training-parameter-record.v3"
    assert candidate_input["artifact_inputs"]["visualizations"]["contract_version"] == "analytical-visualizations.v3"


# ===========================================================================
# Section B: release-candidate-input.schema.json additive vocabulary
# ===========================================================================


def test_schema_admits_v4_training_record_and_metrics_and_reserved_visualization(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())

    candidate_input = _build_v4_candidate_input(tmp_path)

    jsonschema.validate(candidate_input, schema)


def test_schema_remains_backward_compatible_with_v1_legacy_instance(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())

    tmp_repo = tmp_path / "repo"
    paths = _write_v1_internal_governed_artifacts(tmp_repo)
    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=RELEASE_ID,
        source_run_id="internal-run-20260823T000000Z",
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
    assert "training-parameter-record.v4" in record_enum
    assert "training-parameter-record.external-fitted-model.v1" in record_enum
    assert "training-parameter-record.external-fitted-model.v2" not in record_enum

    assert "training-metrics.v1" in metrics_enum
    assert "training-metrics.v2" in metrics_enum
    assert "training-metrics.v3" in metrics_enum
    assert "training-metrics.v4" in metrics_enum
    assert "training-metrics.external-fitted-model.v1" in metrics_enum
    assert "training-metrics.external-fitted-model.v2" not in metrics_enum


def test_schema_reserves_analytical_visualizations_v4_vocabulary_only():
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text())
    visualizations_prop = schema["properties"]["artifact_inputs"]["properties"]["visualizations"][
        "allOf"
    ][1]["properties"]["contract_version"]
    assert visualizations_prop["enum"] == [
        "analytical-visualizations.v1",
        "analytical-visualizations.v2",
        "analytical-visualizations.v3",
        "analytical-visualizations.v4",
    ]


def test_no_real_v4_visualization_schema_content_is_fabricated():
    # S0247 must not define analytical-visualizations.v4 content -- the real
    # pipeline/analytical-visualizations.schema.json file must remain
    # unmodified by this spec, so a v4-declared document still fails real
    # schema validation (proven end to end by
    # test_forecasting_candidate_remains_blocked_pending_visualizations_v4_schema
    # below).
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    validator_cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    with pytest.raises(jsonschema.ValidationError):
        validator_cls(schema).validate({"schema_version": "analytical-visualizations.v4"})


# ===========================================================================
# Section C: univariate-predictive-forecasting recognized by candidate
# release-layer identity set, while the real committed profile remains
# blocked (support_status stays requires_future_contract_evolution -- never
# flipped by this spec, unlike multiclass/continuous-regression in later
# specs).
# ===========================================================================


def _load_real_forecasting_profile() -> dict:
    return json.loads(CAPABILITY_PROFILE_PATH.read_text(encoding="utf-8"))


def test_real_forecasting_capability_profile_support_status_remains_requires_future_contract_evolution():
    profile = _load_real_forecasting_profile()
    assert profile["capability_profile_id"] == "univariate-predictive-forecasting"
    assert profile["support_status"] == "requires_future_contract_evolution"


def test_forecasting_capability_identity_is_a_recognized_release_layer_identity():
    assert (
        "univariate-predictive-forecasting"
        in assemble_candidate.RELEASE_LAYER_SUPPORTED_CAPABILITY_PROFILE_IDS
    )


def test_real_forecasting_profile_still_rejected_by_release_policy():
    profile = _load_real_forecasting_profile()
    capability_binding = {
        "capability_profile_id": profile["capability_profile_id"],
        "capability_profile_version": profile["capability_profile_version"],
        "resolved_role_policy": [],
    }

    result = assemble_candidate.resolve_capability_release_policy(capability_binding, profile)

    assert result.status == "rejected"
    assert result.rejection_phase == assemble_candidate.CAPABILITY_REJECTION_PHASE_UNSUPPORTED


def test_synthetic_current_supported_forecasting_profile_accepted_by_release_policy():
    profile = dict(_load_real_forecasting_profile())
    profile["support_status"] = "current_supported"
    capability_binding = {
        "capability_profile_id": profile["capability_profile_id"],
        "capability_profile_version": profile["capability_profile_version"],
        "resolved_role_policy": [],
    }

    result = assemble_candidate.resolve_capability_release_policy(capability_binding, profile)

    assert result.status == "accepted"
    assert result.capability_profile_id == "univariate-predictive-forecasting"


# ===========================================================================
# Section D: publisher capability/problem-type map and independent capability
# binding verification (publisher/validate.py).
# ===========================================================================


def test_publisher_recognizes_univariate_predictive_forecasting_identity():
    assert "univariate-predictive-forecasting" in validate._SUPPORTED_CAPABILITY_IDENTITIES


def test_publisher_capability_map_maps_exactly_to_univariate_forecasting():
    assert (
        validate._CAPABILITY_EXPECTED_RESULT_PROBLEM_TYPE["univariate-predictive-forecasting"]
        == "univariate_forecasting"
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


def test_verify_capability_binding_accepts_synthetic_current_supported_forecasting_profile(tmp_path):
    profile = dict(_load_real_forecasting_profile())
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "univariate_forecasting"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert reasons == []


def test_verify_capability_binding_rejects_real_unsupported_status(tmp_path):
    # The real, unmodified profile still declares
    # requires_future_contract_evolution, so a matching problem type still
    # produces an unsupported-status rejection reason (never accepted).
    profile = _load_real_forecasting_profile()
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "univariate_forecasting"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert len(reasons) == 1
    assert reasons[0]["code"] == validate._CAPABILITY_BINDING_UNSUPPORTED_STATUS_CODE


def test_verify_capability_binding_rejects_problem_type_mismatch(tmp_path):
    profile = dict(_load_real_forecasting_profile())
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}
    predictive_bundle_data = {"result_semantics": {"problem_type": "binary_classification"}}

    reasons = validate._verify_capability_binding(candidate, tmp_path, predictive_bundle_data)

    assert len(reasons) == 1
    assert reasons[0]["code"] == validate._CAPABILITY_BINDING_RESULT_PROBLEM_TYPE_MISMATCH_CODE


def test_verify_capability_binding_rejects_unknown_identity(tmp_path):
    profile = dict(_load_real_forecasting_profile())
    profile["capability_profile_id"] = "unknown-future-capability"
    profile["support_status"] = "current_supported"
    capability_binding = _write_capability_profile_and_binding(tmp_path, profile)
    candidate = {"capability_binding": capability_binding}

    reasons = validate._verify_capability_binding(candidate, tmp_path, None)

    assert len(reasons) == 1
    assert reasons[0]["code"] == validate._CAPABILITY_BINDING_UNSUPPORTED_CAPABILITY_CODE


# ===========================================================================
# Section E/F/G: native forecasting predictive-bundle, training-metrics.v4,
# and analytical-visualizations.v4-reservation publisher compatibility
# (publisher/validate.py). Exercised as direct unit calls against the
# compatibility functions themselves (never through a full end-to-end
# `valid: True` candidate) because S0247 deliberately does not define real
# analytical-visualizations.v4 schema content -- see Section H below for the
# end-to-end blocked-release proof.
# ===========================================================================


def _forecasting_result_semantics(**overrides) -> dict:
    semantics = {
        "schema_version": "univariate-forecasting-result-semantics.v1",
        "problem_type": "univariate_forecasting",
        "result_schema_version": "univariate-forecasting-result.v1",
        "primary_output": "forecast_series",
        "output_structure": "ordered_forecast_points",
        "forecast_value_kind": "continuous_numeric",
        "forecast_count_source": "forecast_horizon",
        "model_descriptor": {
            "model_family": "deterministic_seasonal_trend_ols",
            "display_name": "Seasonal Trend Model",
        },
    }
    semantics.update(overrides)
    return semantics


def _forecasting_runtime_execution(**overrides) -> dict:
    runtime_execution = {
        "execution_strategy": "in_process",
        "serialization_format": "joblib",
        "loader_strategy": "joblib_sklearn_forecasting_adapter",
        "prediction_interface": "forecast_series",
        "model_family": "deterministic_seasonal_trend_ols",
    }
    runtime_execution.update(overrides)
    return runtime_execution


def _forecasting_frozen_model(*, forecast_horizon: int = 6, **overrides) -> dict:
    frozen_model = {
        "state": "frozen",
        "model_family": "deterministic_seasonal_trend_ols",
        "temporal_identity": {
            "target_column": "example_target",
            "time_index_column": "period",
            "index_value_kind": "calendar_period",
            "frequency": "monthly",
            "source_exogenous_predictors": "forbidden",
            "forecast_horizon": forecast_horizon,
        },
    }
    frozen_model.update(overrides)
    return frozen_model


def _forecasting_predictive_bundle_overrides(
    *,
    result_semantics_overrides: dict | None = None,
    runtime_execution_overrides: dict | None = None,
    output_schema_overrides: dict | None = None,
    frozen_model_overrides: dict | None = None,
    model_provenance_origin: str = "atlas_internal_training",
    forecast_horizon: int = 6,
    extra_top_level: dict | None = None,
) -> dict:
    result_semantics = _forecasting_result_semantics(**(result_semantics_overrides or {}))
    runtime_execution = _forecasting_runtime_execution(**(runtime_execution_overrides or {}))
    output_schema = {
        "result_schema_version": "univariate-forecasting-result.v1",
        "primary_output": "forecast_series",
        "output_structure": "ordered_forecast_points",
        "forecast_value_kind": "continuous_numeric",
        "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
    }
    output_schema.update(output_schema_overrides or {})
    frozen_model = _forecasting_frozen_model(forecast_horizon=forecast_horizon, **(frozen_model_overrides or {}))
    overrides = {
        "result_semantics": result_semantics,
        "runtime_execution": runtime_execution,
        "output_schema": output_schema,
        "frozen_model": frozen_model,
        "model_provenance_origin": model_provenance_origin,
        "training_evidence": {"training_run_identity": {"dataset_slug": DATASET_SLUG}},
    }
    if extra_top_level:
        overrides.update(extra_top_level)
    return overrides


def _forecasting_metrics_overrides(
    *,
    schema_version: str = "training-metrics.v4",
    forecasting_evidence_overrides: dict | None = None,
    final_holdout_metrics: list | None = None,
    final_holdout_overrides: dict | None = None,
    forecast_horizon: int = 6,
) -> dict:
    forecasting_evidence = {
        "problem_type": "univariate_forecasting",
        "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
        "forecast_horizon": forecast_horizon,
    }
    forecasting_evidence.update(forecasting_evidence_overrides or {})
    if final_holdout_metrics is None:
        final_holdout_metrics = [{"name": "mae", "value": 3.1}, {"name": "rmse", "value": 4.2}]
    final_holdout = {
        "evaluation_count": 1,
        "observation_count": 12,
        "metrics": final_holdout_metrics,
        "model_frozen_before_open": True,
        "used_for_adjustment": False,
        "used_for_retuning": False,
        "used_for_model_selection": False,
    }
    final_holdout.update(final_holdout_overrides or {})
    return {
        "schema_version": schema_version,
        "forecasting_evidence": forecasting_evidence,
        "final_holdout_evaluation": final_holdout,
    }


def _safe_details(reasons: list[dict]) -> set:
    return {reason["safe_detail"] for reason in reasons if "safe_detail" in reason}


def test_native_forecasting_bundle_accepts_bounded_semantics():
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(
        _forecasting_predictive_bundle_overrides()
    )
    assert reasons == []


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
        ("predicted_value", 4.2),
    ],
)
def test_native_forecasting_bundle_rejects_non_forecasting_semantics(result_semantics_field, value):
    bundle = _forecasting_predictive_bundle_overrides(
        result_semantics_overrides={result_semantics_field: value}
    )
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_non_forecasting_semantics_present" in _safe_details(reasons)


@pytest.mark.parametrize("threshold_field", ["educational_threshold", "operational_threshold"])
def test_native_forecasting_bundle_rejects_top_level_threshold_fields(threshold_field):
    bundle = _forecasting_predictive_bundle_overrides(extra_top_level={threshold_field: {"value": 0.5}})
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_non_forecasting_semantics_present" in _safe_details(reasons)


def test_native_forecasting_bundle_rejects_external_model_evidence_present():
    bundle = _forecasting_predictive_bundle_overrides(
        extra_top_level={"external_model_evidence": {"readiness": {}}}
    )
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_non_forecasting_semantics_present" in _safe_details(reasons)


def test_native_forecasting_bundle_wrong_result_schema_version_rejects():
    bundle = _forecasting_predictive_bundle_overrides(
        result_semantics_overrides={"schema_version": "univariate-forecasting-result-semantics.v0"}
    )
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_result_semantics_missing" in _safe_details(reasons)


def test_native_forecasting_bundle_wrong_runtime_execution_rejects():
    bundle = _forecasting_predictive_bundle_overrides(
        runtime_execution_overrides={"loader_strategy": "joblib_generic_adapter"}
    )
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_runtime_execution_mismatch" in _safe_details(reasons)


def test_native_forecasting_bundle_wrong_provenance_rejects():
    bundle = _forecasting_predictive_bundle_overrides(model_provenance_origin="unspecified_training_origin")
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_provenance_mismatch" in _safe_details(reasons)


def test_native_forecasting_bundle_external_provenance_rejects_no_carve_out(tmp_path):
    # S0247 adds no external fitted-model forecasting branch: a bundle
    # declaring validated_external_fitted_model provenance is rejected by
    # this native check's own provenance requirement, never accepted through
    # a new forecasting external carve-out.
    bundle = _forecasting_predictive_bundle_overrides(model_provenance_origin="validated_external_fitted_model")
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_provenance_mismatch" in _safe_details(reasons)


def test_no_external_fitted_model_forecasting_branch_exists():
    assert not hasattr(validate, "_external_forecasting_predictive_bundle_compatibility")


def test_native_forecasting_bundle_missing_forecast_horizon_rejects():
    bundle = _forecasting_predictive_bundle_overrides(
        frozen_model_overrides={
            "temporal_identity": {
                "target_column": "example_target",
                "time_index_column": "period",
                "index_value_kind": "calendar_period",
                "frequency": "monthly",
                "source_exogenous_predictors": "forbidden",
                "forecast_horizon": 0,
            }
        }
    )
    reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(bundle)
    assert "native_forecasting_horizon_missing" in _safe_details(reasons)


def test_native_forecasting_metrics_v4_accepted():
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(),
        _forecasting_predictive_bundle_overrides(),
    )
    assert reasons == []


def test_native_forecasting_metrics_wrong_schema_version_rejects():
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(schema_version="training-metrics.v3"),
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_metrics_schema_version_missing" in _safe_details(reasons)


@pytest.mark.parametrize(
    "forecasting_evidence_overrides",
    [
        {"problem_type": "continuous_regression"},
        {"result_semantics_schema_version": "univariate-forecasting-result-semantics.v0"},
    ],
)
def test_native_forecasting_metrics_wrong_forecasting_evidence_rejects(forecasting_evidence_overrides):
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(forecasting_evidence_overrides=forecasting_evidence_overrides),
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_metrics_evidence_mismatch" in _safe_details(reasons)


def test_native_forecasting_metrics_horizon_mismatch_rejects():
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(forecast_horizon=6),
        _forecasting_predictive_bundle_overrides(forecast_horizon=12),
    )
    assert "native_forecasting_horizon_mismatch" in _safe_details(reasons)


@pytest.mark.parametrize(
    "final_holdout_overrides",
    [
        {"evaluation_count": 2},
        {"model_frozen_before_open": False},
        {"used_for_adjustment": True},
        {"used_for_retuning": True},
        {"used_for_model_selection": True},
        {"observation_count": 0},
    ],
)
def test_native_forecasting_metrics_final_holdout_policy_violation_rejects(final_holdout_overrides):
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(final_holdout_overrides=final_holdout_overrides),
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_final_holdout_policy_violation" in _safe_details(reasons)


def test_native_forecasting_metrics_no_projectable_metric_rejects():
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(
            final_holdout_metrics=[{"name": "mape", "value": 12.0}, {"name": "smape", "value": 8.0}],
        ),
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_metrics_no_public_metric" in _safe_details(reasons)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf"), True])
def test_native_forecasting_metrics_non_finite_or_boolean_metric_rejects(bad_value):
    reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(final_holdout_metrics=[{"name": "mae", "value": bad_value}]),
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_metrics_no_public_metric" in _safe_details(reasons)


def test_native_forecasting_visualizations_accepts_reserved_v4_schema_version():
    reasons = validate._internal_native_forecasting_visualizations_compatibility(
        {"schema_version": "analytical-visualizations.v4"},
        _forecasting_predictive_bundle_overrides(),
    )
    assert reasons == []


@pytest.mark.parametrize(
    "visualizations_version",
    ["analytical-visualizations.v1", "analytical-visualizations.v2", "analytical-visualizations.v3"],
)
def test_native_forecasting_visualizations_rejects_v1_v2_v3_substitution(visualizations_version):
    reasons = validate._internal_native_forecasting_visualizations_compatibility(
        {"schema_version": visualizations_version},
        _forecasting_predictive_bundle_overrides(),
    )
    assert "native_forecasting_visualizations_version_mismatch" in _safe_details(reasons)


def test_native_forecasting_never_confused_with_external_or_other_native_provenance_checks():
    bundle_reasons = validate._internal_native_forecasting_predictive_bundle_compatibility(
        _forecasting_predictive_bundle_overrides()
    )
    metrics_reasons = validate._internal_native_forecasting_metrics_public_projection_check(
        _forecasting_metrics_overrides(), _forecasting_predictive_bundle_overrides()
    )
    all_details = _safe_details(bundle_reasons) | _safe_details(metrics_reasons)
    assert not any(detail.startswith("external_") for detail in all_details)
    assert not any(detail.startswith("native_multiclass") for detail in all_details)
    assert not any(detail.startswith("native_regression") for detail in all_details)


# ===========================================================================
# Section H: end-to-end confirmation that a real forecasting candidate
# remains blocked until analytical-visualizations.v4 exists, even when its
# bundle/metrics are otherwise fully compliant with the S0247 native
# forecasting compatibility checks above.
# ===========================================================================


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _candidate_dir(tmp_path: Path) -> Path:
    return tmp_path / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID


def _base_artifact_payload(role: str) -> dict:
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
    return payload


def _write_forecasting_candidate(
    tmp_path: Path,
    *,
    predictive_bundle: dict,
    metrics: dict,
    visualizations: dict,
) -> Path:
    candidate_dir = _candidate_dir(tmp_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    role_payloads = {
        "contracts": _base_artifact_payload("contracts"),
        "public_contract": dict(_VALID_PUBLIC_CONTRACT),
        "predictive_bundle": {**_base_artifact_payload("predictive_bundle"), **predictive_bundle},
        "metrics": {**_base_artifact_payload("metrics"), **metrics},
        "model_card": _base_artifact_payload("model_card"),
        "public_context": _base_artifact_payload("public_context"),
        # visualizations is real-schema-validated against
        # pipeline/analytical-visualizations.schema.json
        # (additionalProperties: false) -- unlike metrics/model_card/etc.,
        # it must never be wrapped with the generic base envelope fields.
        "visualizations": dict(visualizations),
        "manifest_input": _base_artifact_payload("manifest_input"),
        "candidate_metadata": _base_artifact_payload("candidate_metadata"),
    }

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        if role == "model_artifact":
            (candidate_dir / role_path).parent.mkdir(parents=True, exist_ok=True)
            (candidate_dir / role_path).write_bytes(MODEL_ARTIFACT_BYTES)
            continue
        _write_json(candidate_dir / role_path, role_payloads[role])

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Example Forecasting Dataset"},
        "release_identity": {
            "release_id": RELEASE_ID, "release_version": RELEASE_VERSION, "created_at": "2026-08-23T00:00:00Z",
        },
        "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-08-23T00:00:00Z"},
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-08-23T00:00:00Z",
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


def test_forecasting_candidate_remains_blocked_pending_visualizations_v4_schema(tmp_path):
    candidate_dir = _write_forecasting_candidate(
        tmp_path,
        predictive_bundle=_forecasting_predictive_bundle_overrides(),
        metrics=_forecasting_metrics_overrides(),
        visualizations={"schema_version": "analytical-visualizations.v4"},
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert result["schema_compatibility"]["visualizations"]["compatible"] is False
    # The bundle/metrics compatibility checks themselves pass -- only the
    # real (unmodified) analytical-visualizations schema blocks release.
    safe_details = _safe_details(result["rejection_reasons"])
    assert "native_forecasting_result_semantics_missing" not in safe_details
    assert "native_forecasting_non_forecasting_semantics_present" not in safe_details
    assert "native_forecasting_metrics_schema_version_missing" not in safe_details
    assert "native_forecasting_metrics_no_public_metric" not in safe_details


# ===========================================================================
# Existing binary candidate/publisher behavior remains unaffected by the
# S0247 additions above. (Multiclass/continuous-regression coverage remains
# owned by their own dedicated test modules, run alongside this one per the
# S0247 request's Expected Validation regression command.)
# ===========================================================================


def test_existing_binary_candidate_accepted_unchanged(tmp_path):
    visualizations_payload = {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-23T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260823T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z/",
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
    binary_predictive_bundle = {
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1",
            "primary_output": "positive_class_probability",
            "positive_class": {"class_id": "yes", "event_label": "Yes"},
            "negative_class": {"class_id": "no"},
            "decision": {"threshold": 0.5},
            "interpretation": {"preset": "risk", "bands": []},
            "model_descriptor": {"model_family": "logistic_regression", "display_name": "Logistic Regression"},
        },
        "model_provenance_origin": "atlas_internal_training",
        "training_evidence": {"training_run_identity": {"dataset_slug": DATASET_SLUG}},
    }
    candidate_dir = _write_forecasting_candidate(
        tmp_path,
        predictive_bundle=binary_predictive_bundle,
        metrics={"schema_version": "training-metrics.v1"},
        visualizations=visualizations_payload,
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]


# ===========================================================================
# No real candidate/release/publisher run is written to disk by this module.
# ===========================================================================


def test_no_real_candidate_directory_created_under_real_repository_tree():
    assert not (REPO_ROOT / "releases" / "candidates" / DATASET_SLUG).exists()
