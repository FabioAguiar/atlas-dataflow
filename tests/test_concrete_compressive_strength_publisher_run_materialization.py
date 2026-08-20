"""
Project Spec S0233: end-to-end Publisher Run materialization -> validated
terminal handoff -> Admin run listing visibility regression for the first
native continuous-regression dataset, `concrete-compressive-strength`.

Mirrors tests/test_dry_bean_publisher_run_materialization.py's architecture
(Project Spec S0217), but builds a temporary Atlas repository fixture with a
valid native continuous-regression release candidate (dataset_slug
"concrete-compressive-strength", model_family "hist_gradient_boosting",
model_provenance_origin "atlas_internal_training", inference bundle
"inference-bundle.v1" carrying "continuous-regression-result.v1" result
semantics, visualizations "analytical-visualizations.v3"), then exercises,
against that fixture only -- never the real repository run directory:

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


DATASET_SLUG = "concrete-compressive-strength"
RELEASE_ID = "release-20260820-001"
RELEASE_VERSION = "1.0.0-rc.1"

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

# Project Spec S0234: the single native Concrete Predict View declaration,
# matching the shape the real notebook now authors in
# notebooks/datasets/concrete-compressive-strength/dataset_integration.ipynb
# Stage 9 -- presentation/intent metadata only, no feature/domain/runtime
# validation semantics.
CONCRETE_PREDICT_VIEW = {
    "schema_version": "1.0.0",
    "view_id": "concrete-compressive-strength-regression",
    "dataset_slug": DATASET_SLUG,
    "display": {
        "title": "Concrete Compressive Strength",
        "summary": "Predict concrete compressive strength from mixture composition and curing age.",
        "description": "A continuous-regression prediction experience using the governed Concrete Compressive Strength input contract.",
        "tags": ["concrete", "regression", "continuous"],
    },
    "intent": {
        "prediction_goal": "Predict concrete compressive strength from the canonical dataset contract inputs.",
        "audience": "Users exploring Concrete Compressive Strength continuous-regression inference.",
        "usage_notes": "Use the canonical dataset contracts for required fields, numeric input semantics, and runtime validation.",
    },
    "binding": {
        "dataset_slug": DATASET_SLUG,
        "release": {"mode": "active"},
    },
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "view_metadata_defines_runtime_validation": False,
        "view_metadata_duplicates_contract": False,
    },
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
    if role == "visualizations":
        return "visualizations/visualizations.json"
    return f"artifacts/{role}.json"


def _visualizations_payload() -> dict:
    """Atlas-owned analytical-visualizations.v3 evidence for a native
    hist_gradient_boosting continuous-regression candidate (Project Specs
    S0228/S0231), mirroring the reference shape validated by
    tests/test_native_continuous_regression_training.py and
    tests/test_continuous_regression_candidate_publisher.py."""
    return {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-20T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260820T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260820T000000Z/",
        },
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "Concrete compressive strength", "y_label": "Rows",
                "data": [{"name": "0 to 20", "value": 3}, {"name": "20 to 40", "value": 1}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "Cement", "value": 1.0}],
            },
        ],
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 4,
            "target_column": "Concrete compressive strength",
            "bin_count": 2,
            "min_value": 5.0,
            "max_value": 35.0,
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "sklearn.inspection.permutation_importance",
            "method": "permutation_importance",
            "population_kind": "final_fit_train_plus_validation",
            "scoring": "neg_mean_absolute_error",
            "n_repeats": 5,
            "random_seed": 42,
            "total_source_feature_count": 8,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test",
            "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width_actual_bins",
            "reference_line": "identity",
            "points": [{"actual_mean": 25.0, "predicted_mean": 24.2, "count": 4}],
        },
        "residual_distribution": {
            "partition_role": "test",
            "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [{"label": "-2 to 2", "lower_bound": -2.0, "upper_bound": 2.0, "count": 4}],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }


def _predictive_bundle_payload() -> dict:
    """Atlas-owned inference-bundle.v1 shape declaring native
    hist_gradient_boosting continuous-regression provenance (Project Specs
    S0225/S0227/S0232) -- number prediction, no class/probability/threshold
    semantics."""
    return {
        "schema_version": "inference-bundle.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "runtime_execution": {"model_family": "hist_gradient_boosting"},
        "output_schema": {"prediction_key": "prediction", "prediction_type": "number"},
        "result_semantics": {
            "schema_version": "continuous-regression-result-semantics.v1",
            "problem_type": "continuous_regression",
            "result_schema_version": "continuous-regression-result.v1",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
            "model_descriptor": {
                "model_family": "hist_gradient_boosting",
                "display_name": "HistGradientBoosting",
            },
        },
        "model_provenance_origin": "atlas_internal_training",
        "training_evidence": {
            "training_run_identity": {"dataset_slug": DATASET_SLUG, "run_id": "train-20260820T000000Z"},
        },
        "model_id": "concrete-compressive-strength-model-001",
        "runtime_contract_ref": "artifacts/contracts.json",
        "model_artifact": {"path": MODEL_ARTIFACT_PATH, "sha256": MODEL_ARTIFACT_SHA256},
        "availability_status": "real_dataflow_artifact",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
    }


def _metrics_payload() -> dict:
    """Atlas-owned training-metrics.v3 continuous-regression evidence
    (Project Spec S0224/S0228)."""
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
        "model_id": "concrete-compressive-strength-model-001",
        "schema_version": "training-metrics.v3",
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "final_test_evaluation": {
            "partition_role": "test",
            "completed": True,
            "row_count": 4,
            "metrics": [
                {"name": "mae", "value": 2.58},
                {"name": "rmse", "value": 4.21},
                {"name": "r2", "value": 0.9387},
            ],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "metrics": [
                {"name": "mae", "value": 2.74},
                {"name": "rmse", "value": 4.09},
                {"name": "r2", "value": 0.9336},
            ],
        },
    }


def _artifact_payload(role: str) -> dict:
    if role == "public_contract":
        return {
            "schema_version": "1.0.0",
            "features": [
                {
                    "name": "Cement",
                    "label": "Cement",
                    "input_type": "number",
                    "optional": False,
                    "display_order": 1,
                }
            ],
        }
    if role == "visualizations":
        return _visualizations_payload()
    if role == "predictive_bundle":
        return _predictive_bundle_payload()
    if role == "metrics":
        return _metrics_payload()
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
    if role == "model_card":
        payload["model_id"] = "concrete-compressive-strength-model-001"
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
        # Project Spec S0234: the candidate/public-context fixture must now
        # preserve the real notebook's declared Concrete Predict View,
        # mirroring the dataset_context.predict_views shape written by Stage
        # 9 (candidate role "public_context" resolves to
        # dataset_context_relative_path in the real notebook).
        payload["predict_views"] = [CONCRETE_PREDICT_VIEW]
    return payload


def _write_native_continuous_regression_candidate(tmp_repo: Path) -> Path:
    """A valid native continuous-regression release candidate,
    self-contained in tmp_repo -- never the real repository run/candidate
    directories."""
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
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Concrete Compressive Strength"},
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-08-20T00:00:00Z",
        },
        "source_run": {
            "run_id": "train-20260820T000000Z", "producer": "pytest", "created_at": "2026-08-20T00:00:00Z",
        },
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-08-20T00:00:00Z",
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


def test_concrete_publisher_run_materialization_is_visible_in_admin_listing(tmp_path, monkeypatch):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    registry_path = tmp_repo / "registry" / "datasets.json"
    registry_before = registry_path.read_text(encoding="utf-8")

    candidate_dir = _write_native_continuous_regression_candidate(tmp_repo)
    inference_bundle_relative_path = _write_inference_bundle(tmp_repo)

    # Project Spec S0234 AC8: the candidate/public-context fixture preserves
    # the Concrete Predict View declaration going into Publisher Run
    # materialization.
    public_context_payload = json.loads(
        (candidate_dir / _role_path("public_context")).read_text(encoding="utf-8")
    )
    assert public_context_payload["predict_views"] == [CONCRETE_PREDICT_VIEW]

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
        run_id="train-20260820T000000Z",
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
