"""
Project Spec S0251: end-to-end Publisher Run materialization -> validated
terminal handoff -> Admin run listing visibility regression for the first
real Atlas-native univariate-forecasting dataset, `nottem` (Nottingham
Monthly Temperatures).

Mirrors tests/test_concrete_compressive_strength_publisher_run_materialization.py's
architecture (Project Spec S0233), but builds a temporary Atlas repository
fixture with a valid native univariate-forecasting release candidate
(dataset_slug "nottem", model_family "deterministic_seasonal_trend_ols",
model_provenance_origin "atlas_internal_training", inference bundle
"inference_bundle.v2" carrying "univariate-forecasting-result-semantics.v1"
result semantics, metrics "training-metrics.v4", visualizations
"analytical-visualizations.v4"), then exercises, against that fixture
only -- never the real repository run/candidate directories, never the real
raw dataset, never the attached external scientific study:

    publisher.validate.materialize_validation_run (the dataset-generic
    Publisher Run materializer, never materialize_telco_validation_run and
    never a releases/candidates scan)
        -> pipeline.validated_run.materialize_validated_run_terminal_result
           (model_source_mode=atlas_internal_training)
        -> api.admin_runs.list_admin_run_summaries() (read-only)

Proves the generated run is discovered by Admin run listing, structural
validation/manifest/terminal-result artifacts exist, and no promotion,
release, or registry mutation occurred anywhere in the flow.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
API_ROOT = REPO_ROOT / "api"
for _path in (REPO_ROOT, API_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from pipeline import validated_run  # noqa: E402
from publisher import validate  # noqa: E402
import admin_runs  # noqa: E402


DATASET_SLUG = "nottem"
RELEASE_ID = "release-20260823-001"
RELEASE_VERSION = "1.0.0-rc.1"
FORECAST_HORIZON = 12
SEASONAL_PERIOD = 12
DEVELOPMENT_OBSERVATIONS = 228
FINAL_HOLDOUT_OBSERVATIONS = 12

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

MODEL_ARTIFACT_BYTES = b"pytest-fixture-nottem-model-bytes-not-a-real-model"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()
MODEL_ARTIFACT_PATH = "models/model.pkl"

FIXED_MODEL_CONFIGURATION = {
    "include_intercept": True,
    "linear_time_trend": True,
    "seasonal_effects": "additive_indicators",
    "seasonal_period": SEASONAL_PERIOD,
    "reference_season_position": 0,
    "trend_origin": "development_start",
}


def _copy_publisher_contracts(tmp_repo: Path) -> None:
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/validation/release-candidate-validation.schema.json",
        "publisher/evidence/publication-validation-evidence.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
        "pipeline/validated-run-terminal-result.schema.json",
    ):
        src = REPO_ROOT / relative
        dst = tmp_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_registry(tmp_repo: Path) -> None:
    registry_dir = tmp_repo / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "Stable dataset identifier."},
            "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "Stable release identifier."},
            "active_release": {"description": "Release currently served for the dataset."},
        },
        "datasets": [],
    }
    (registry_dir / "datasets.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _fold_summaries() -> list[dict]:
    return [
        {
            "fold_index": index,
            "forecast_origin": f"193{index}-12",
            "validation_observations": FORECAST_HORIZON,
            "metrics": [{"name": "mae", "value": 1.9 + 0.05 * index}],
        }
        for index in range(9)
    ]


def _horizon_mae_points() -> list[dict]:
    return [
        {"horizon_step": step, "mae": round(1.6 + 0.1 * step, 2), "observation_count": 9}
        for step in range(1, FORECAST_HORIZON + 1)
    ]


def _public_contract_payload() -> dict:
    return {
        "schema_version": "2.0.0",
        "problem_type": "univariate_forecasting",
        "input_kind": "history_series",
        "history_series": {
            "time_index_field": {
                "name": "period", "label": "Period", "value_kind": "calendar_period", "display_order": 1,
            },
            "target_field": {
                "name": "temperature", "label": "Temperature", "value_kind": "number", "display_order": 2,
            },
            "frequency": "monthly",
        },
        "forecast": {"forecast_horizon": FORECAST_HORIZON, "horizon_user_editable": False},
    }


def _predictive_bundle_payload() -> dict:
    """Atlas-owned inference-bundle.v2 shape declaring native
    deterministic_seasonal_trend_ols forecasting provenance (Project Specs
    S0245/S0246/S0247) -- forecast-series result semantics, no external
    model evidence, no feature_order/preprocessing."""
    return {
        "schema_version": "inference_bundle.v2",
        "role": "predictive_bundle",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "runtime_contract_ref": "artifacts/contracts.json",
        "model_artifact": {"path": MODEL_ARTIFACT_PATH, "sha256": MODEL_ARTIFACT_SHA256},
        "runtime_execution": {
            "execution_strategy": "in_process",
            "serialization_format": "joblib",
            "loader_strategy": "joblib_sklearn_forecasting_adapter",
            "prediction_interface": "forecast_series",
            "model_family": "deterministic_seasonal_trend_ols",
        },
        "output_schema": {
            "result_schema_version": "univariate-forecasting-result.v1",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
        },
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1",
            "problem_type": "univariate_forecasting",
            "result_schema_version": "univariate-forecasting-result.v1",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
            "model_descriptor": {
                "model_family": "deterministic_seasonal_trend_ols",
                "display_name": "Deterministic Seasonal-Trend OLS",
            },
        },
        "frozen_model": {
            "state": "frozen",
            "model_family": "deterministic_seasonal_trend_ols",
            "fixed_model_configuration": FIXED_MODEL_CONFIGURATION,
            "temporal_identity": {
                "target_column": "temperature",
                "time_index_column": "period",
                "index_value_kind": "calendar_period",
                "frequency": "monthly",
                "source_exogenous_predictors": "forbidden",
                "forecast_horizon": FORECAST_HORIZON,
            },
        },
        "model_provenance_origin": "atlas_internal_training",
        "training_evidence": {
            "training_run_identity": {"dataset_slug": DATASET_SLUG, "run_id": "train-20260823T000000Z"},
        },
    }


def _metrics_payload() -> dict:
    """Atlas-owned training-metrics.v4 univariate-forecasting evidence
    (Project Spec S0244/S0247)."""
    fold_summaries = _fold_summaries()
    return {
        "role": "metrics",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "availability_status": "real_dataflow_artifact",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
        "schema_version": "training-metrics.v4",
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "forecast_horizon": FORECAST_HORIZON,
        },
        "evaluation_policy": {
            "primary_metric": {"metric_id": "mae", "direction": "lower_is_better"},
            "secondary_metrics": [
                {"metric_id": "rmse", "direction": "lower_is_better"},
                {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": SEASONAL_PERIOD},
            ],
        },
        "backtesting_evaluation": {
            "fold_count": len(fold_summaries),
            "forecast_count": sum(entry["validation_observations"] for entry in fold_summaries),
            "pooled_metrics": [{"name": "mae", "value": 1.839438}],
            "fold_summaries": fold_summaries,
            "horizon_mae": _horizon_mae_points(),
        },
        "final_holdout_evaluation": {
            "evaluation_count": 1,
            "observation_count": FINAL_HOLDOUT_OBSERVATIONS,
            "metrics": [
                {"name": "mae", "value": 1.526584},
                {"name": "rmse", "value": 1.859967},
                {"name": "seasonal_mase", "value": 0.555495},
            ],
            "model_frozen_before_open": True,
            "used_for_adjustment": False,
            "used_for_retuning": False,
            "used_for_model_selection": False,
        },
    }


def _visualizations_payload() -> dict:
    """Atlas-owned analytical-visualizations.v4 evidence, fully
    cross-consistent with `_metrics_payload()` and
    `_predictive_bundle_payload()` above (Project Spec S0248)."""
    fold_summaries = _fold_summaries()
    per_position = DEVELOPMENT_OBSERVATIONS // SEASONAL_PERIOD
    remainder = DEVELOPMENT_OBSERVATIONS - per_position * SEASONAL_PERIOD
    return {
        "schema_version": "analytical-visualizations.v4",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-23T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260823T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z/",
        },
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "training_metrics_schema_version": "training-metrics.v4",
            "forecast_horizon": FORECAST_HORIZON,
            "frequency": "monthly",
            "seasonal_period": SEASONAL_PERIOD,
        },
        "dataset_statistics": {
            "instance_count": DEVELOPMENT_OBSERVATIONS + FINAL_HOLDOUT_OBSERVATIONS,
            "development_observations": DEVELOPMENT_OBSERVATIONS,
            "final_holdout_observations": FINAL_HOLDOUT_OBSERVATIONS,
        },
        "seasonal_profile": {
            "population_kind": "full_development",
            "seasonal_period": SEASONAL_PERIOD,
            "points": [
                {
                    "season_position": position,
                    "mean_target": 50.0 + position,
                    "observation_count": per_position + (1 if position < remainder else 0),
                }
                for position in range(SEASONAL_PERIOD)
            ],
        },
        "backtesting_fold_metric": {
            "metric_id": "mae",
            "direction": "lower_is_better",
            "fold_count": len(fold_summaries),
            "points": [
                {
                    "fold_index": summary["fold_index"],
                    "forecast_origin": summary["forecast_origin"],
                    "value": next(entry["value"] for entry in summary["metrics"] if entry["name"] == "mae"),
                    "validation_observations": summary["validation_observations"],
                }
                for summary in fold_summaries
            ],
        },
        "horizon_mae": {"points": _horizon_mae_points()},
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }


def _model_card_payload() -> dict:
    """Truthful, reduced forecasting model card -- no fake tabular
    feature/split semantics (Project Spec S0251 Desired Change O),
    mirroring the real notebook's own authored shape."""
    return {
        "role": "model_card",
        "schema_version": "model-card.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "problem_type": "univariate_forecasting",
        "prediction_target": "temperature",
        "input_features": [],
        "model_family": "deterministic_seasonal_trend_ols",
        "fixed_model_configuration": FIXED_MODEL_CONFIGURATION,
        "evaluation": {
            "partition_role": "final_holdout",
            "metrics": _metrics_payload()["final_holdout_evaluation"]["metrics"],
        },
        "notes": (
            "Univariate forecasting model card. Input is a governed "
            "period|temperature history series, not a tabular feature "
            "vector -- input_features is intentionally empty."
        ),
    }


def _artifact_payload(role: str) -> dict:
    if role == "public_contract":
        return _public_contract_payload()
    if role == "visualizations":
        return _visualizations_payload()
    if role == "predictive_bundle":
        return _predictive_bundle_payload()
    if role == "metrics":
        return _metrics_payload()
    if role == "model_card":
        return _model_card_payload()
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
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
        # Project Spec S0251: Nottingham declares no Predict View -- S0252
        # remains responsible for that after a promoted release exists.
        payload["predict_views"] = []
    return payload


def _write_native_forecasting_candidate(tmp_repo: Path) -> Path:
    """A valid native univariate-forecasting release candidate,
    self-contained in tmp_repo -- never the real repository run/candidate
    directories, never the real raw dataset, never the attached external
    scientific study."""
    candidate_dir = tmp_repo / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        artifact_path = candidate_dir / role_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_artifact":
            artifact_path.write_bytes(MODEL_ARTIFACT_BYTES)
        else:
            artifact_path.write_text(json.dumps(_artifact_payload(role), indent=2), encoding="utf-8")

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Nottingham Monthly Temperatures"},
        "release_identity": {
            "release_id": RELEASE_ID, "release_version": RELEASE_VERSION, "created_at": "2026-08-23T00:00:00Z",
        },
        "source_run": {
            "run_id": "train-20260823T000000Z", "producer": "pytest", "created_at": "2026-08-23T00:00:00Z",
        },
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
    (candidate_dir / "release-candidate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    return candidate_dir


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_inference_bundle(tmp_repo: Path) -> str:
    relative_path = f"pipeline/inference-bundles/{DATASET_SLUG}/inference-bundle.json"
    path = tmp_repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_predictive_bundle_payload(), indent=2), encoding="utf-8")
    return relative_path


def test_nottingham_forecasting_candidate_reaches_valid_true_at_publisher_structural_layer(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    candidate_dir = _write_native_forecasting_candidate(tmp_repo)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True, result["rejection_reasons"]
    assert result["schema_compatibility"]["public_contract"]["compatible"] is True
    assert result["schema_compatibility"]["visualizations"]["compatible"] is True


def test_nottingham_publisher_run_materialization_is_visible_in_admin_listing(tmp_path, monkeypatch):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    registry_path = tmp_repo / "registry" / "datasets.json"
    registry_before = registry_path.read_text(encoding="utf-8")

    candidate_dir = _write_native_forecasting_candidate(tmp_repo)
    inference_bundle_relative_path = _write_inference_bundle(tmp_repo)

    # Project Spec S0251: the candidate/public-context fixture declares no
    # Predict View -- S0252 remains responsible for that after a promoted
    # release exists.
    public_context_payload = json.loads(
        (candidate_dir / _role_path("public_context")).read_text(encoding="utf-8")
    )
    assert public_context_payload["predict_views"] == []

    # Generic Publisher Run materializer only, dispatched by explicit
    # candidate identity -- never materialize_telco_validation_run, never a
    # releases/candidates scan.
    release_candidate_assembly_result = {
        "status": "accepted",
        "dataset_slug": DATASET_SLUG,
        "release_id": RELEASE_ID,
        "candidate_dir": str(candidate_dir),
    }
    materialization_result = validate.materialize_validation_run(
        release_candidate_assembly_result, repo_root=tmp_repo,
    )

    assert materialization_result["materialization_status"] == "materialized"
    assert materialization_result["validation_outcome"] == "accepted", materialization_result
    assert materialization_result["manifest_generated"] is True
    assert materialization_result["boundary_confirmations"] == {
        "publisher_promotion_performed": False,
        "registry_activation_performed": False,
        "release_candidate_artifact_modified": False,
    }

    run_dir = tmp_repo / materialization_result["run_dir"]
    assert (run_dir / "validation-result.json").is_file()
    assert (run_dir / "manifest.json").is_file()

    def _durable_ref(relative_path):
        return {"path": relative_path, "sha256": _sha256_file(tmp_repo / relative_path)}

    release_candidate_relative_path = str(candidate_dir.relative_to(tmp_repo) / "release-candidate.json")
    validation_result_relative_path = f"{materialization_result['run_dir']}/validation-result.json"
    manifest_relative_path = materialization_result["manifest_path"]

    terminal_result = validated_run.materialize_validated_run_terminal_result(
        run_id="train-20260823T000000Z",
        dataset_slug=DATASET_SLUG,
        model_source_mode="atlas_internal_training",
        status="completed",
        durable_references={
            "materialization_result": None,
            "inference_bundle": _durable_ref(inference_bundle_relative_path),
            "release_candidate": _durable_ref(release_candidate_relative_path),
            "publisher_validation_result": _durable_ref(validation_result_relative_path),
            "manifest": _durable_ref(manifest_relative_path),
            "operational_readiness_source": None,
        },
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": manifest_relative_path},
        operational_readiness={
            "operational_validity": "not_applicable",
            "operational_threshold": {"status": "not_applicable", "value": None},
            "operational_prediction_available": False,
        },
        repo_root=tmp_repo,
    )

    assert terminal_result["status"] == "completed"
    assert terminal_result["promotion_eligibility"] is True
    assert terminal_result["model_source_mode"] == "atlas_internal_training"

    terminal_result_path = run_dir / "validated-run-terminal-result.json"
    terminal_result_path.write_text(json.dumps(terminal_result, indent=2), encoding="utf-8")

    # api.admin_runs.list_admin_run_summaries() read only, pointed at this
    # tmp_repo's Publisher Run root -- never the real repository runs root.
    monkeypatch.setenv("ADMIN_RUNS_ROOT", str(tmp_repo / "publisher" / "runs"))

    listing = admin_runs.list_admin_run_summaries()

    assert listing["runs_root_status"] == "available"
    matching_runs = [entry for entry in listing["runs"] if entry["run_id"] == run_dir.name]
    assert len(matching_runs) == 1
    entry = matching_runs[0]

    assert entry["status"] == "available"
    assert entry["dataset_candidate"] == DATASET_SLUG
    assert entry["validation_summary"]["outcome"] == "accepted"
    assert entry["trace_reference"] is not None
    assert not entry["trace_reference"].startswith("/")
    assert entry["trace_reference"].endswith(run_dir.name)

    # No promotion, no release, no registry mutation anywhere in this flow.
    assert not (run_dir / "promotion-result.json").exists()
    assert not (tmp_repo / "releases" / RELEASE_ID).exists()
    assert registry_path.read_text(encoding="utf-8") == registry_before
    assert (candidate_dir / "release-candidate.json").is_file()


def test_no_real_nottem_candidate_directory_created_under_real_repository_tree():
    assert not (REPO_ROOT / "releases" / "candidates" / DATASET_SLUG).exists()
