"""Focused tests for publisher/operational_readiness.py (Project Spec S0189).

Uses synthetic candidate/run fixtures under tmp_path only. Never touches the
real repository's publisher/runs, releases/candidates, or releases/ trees.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from publisher import operational_readiness, validate  # noqa: E402


DATASET_SLUG = "example-dataset"
RELEASE_ID = "release-20260619-001"
RELEASE_VERSION = "2026.06.19"

MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-not-a-real-model"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()
MODEL_ARTIFACT_PATH = "models/model.pkl"

REQUIRED_ROLES = (
    "contracts",
    "public_contract",
    "predictive_bundle",
    "model_artifact",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)

VALID_OPERATOR_DECISION = {
    "operational_validity": "confirmed",
    "operational_threshold": {"status": "resolved", "value": 0.31, "selection_basis": "reviewed on holdout set"},
    "operational_prediction_available": True,
    "decision_basis": "Operator reviewed the external evaluation evidence and confirmed operational validity.",
}

UNRESOLVED_OPERATOR_DECISION = {
    "operational_validity": "unconfirmed",
    "operational_threshold": {"status": "unresolved", "value": None, "selection_basis": None},
    "operational_prediction_available": False,
    "decision_basis": "Operator has not yet completed the operational review.",
}


def _copy_publisher_contracts(tmp_repo: Path) -> None:
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/operational-readiness-decision.schema.json",
        "publisher/validation/release-candidate-validation.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
    ):
        src = REPO_ROOT / relative
        dst = tmp_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _candidate_dir(tmp_repo: Path) -> Path:
    return tmp_repo / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _artifact_payload(role: str) -> dict:
    if role == "public_contract":
        return {
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


def _external_predictive_bundle_payload(
    *,
    operational_validity: str = "unconfirmed",
    threshold_status: str = "unresolved",
    threshold_value: float | None = None,
    prediction_available: bool = False,
    provenance: str = "validated_external_fitted_model",
) -> dict:
    payload = _artifact_payload("predictive_bundle")
    payload["model_provenance_origin"] = provenance
    payload["external_model_evidence"] = {
        "origin": provenance,
        # A deliberately distinct educational threshold, retained purely as
        # scientific evidence -- proves the governed operational decision
        # (never this value) is what flows through the review.
        "educational_threshold": {"value": 0.99, "label": "educational", "scenario": "not_the_operational_value"},
        "readiness": {
            "operational_validity": operational_validity,
            "operational_threshold": {"status": threshold_status, "value": threshold_value},
            "operational_prediction_available": prediction_available,
        },
    }
    return payload


def _visualizations_payload() -> dict:
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-06-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260619T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260619T000000Z/",
        },
        "charts": [
            {
                "id": "target_distribution",
                "title": "Target Distribution",
                "type": "bar",
                "x_label": "Target",
                "y_label": "Rows",
                "data": [{"name": "No", "value": 6}, {"name": "Yes", "value": 4}],
            },
            {
                "id": "feature_importance",
                "title": "Feature Importance",
                "type": "bar",
                "x_label": "Feature",
                "y_label": "Importance",
                "data": [{"name": "example_feature", "value": 1.0}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset",
            "row_count": 10,
            "target_column": "target",
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "feature_importances_aggregated_to_source_features",
            "total_source_feature_count": 1,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False,
            "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


def _write_candidate(
    tmp_repo: Path,
    *,
    predictive_bundle_payload: dict | None = None,
    include_visualizations: bool = False,
) -> Path:
    candidate_dir = _candidate_dir(tmp_repo)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    roles = REQUIRED_ROLES + (("visualizations",) if include_visualizations else ())

    artifact_roles = {}
    for role in roles:
        role_path = "visualizations/visualizations.json" if role == "visualizations" else _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        artifact_path = candidate_dir / role_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_artifact":
            artifact_path.write_bytes(MODEL_ARTIFACT_BYTES)
        elif role == "visualizations":
            artifact_path.write_text(json.dumps(_visualizations_payload(), indent=2), encoding="utf-8")
        else:
            payload = (
                predictive_bundle_payload
                if role == "predictive_bundle" and predictive_bundle_payload is not None
                else _artifact_payload(role)
            )
            artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Example Dataset"},
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-06-19T00:00:00Z",
        },
        "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-06-19T00:00:00Z"},
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-06-19T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": list(roles),
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


def _latest_run_dir(tmp_repo: Path) -> Path:
    runs_dir = tmp_repo / "publisher" / "runs"
    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    assert run_dirs
    return run_dirs[-1]


def _write_terminal_result(run_dir: Path, *, model_source_mode: str = "validated_external_fitted_model") -> None:
    terminal_result = {
        "artifact_kind": "validated_run_terminal_result",
        "schema_version": "validated-run-terminal-result.v1",
        "status": "completed",
        "model_source_mode": model_source_mode,
        "run_identity": {"run_id": "source-materialization-run", "dataset_slug": DATASET_SLUG},
    }
    (run_dir / "validated-run-terminal-result.json").write_text(
        json.dumps(terminal_result, indent=2), encoding="utf-8"
    )


def _prepare_source_run(
    tmp_repo: Path,
    *,
    predictive_bundle_payload: dict | None = None,
    model_source_mode: str = "validated_external_fitted_model",
    include_visualizations: bool = False,
) -> tuple[Path, Path]:
    """Prepare a tmp_repo, write a synthetic external-provenance candidate,
    structurally validate it (producing a real publisher run), and attach a
    synthetic validated-run-terminal-result.json to that run -- the "source
    run" a review is performed against. Returns (candidate_dir, source_run_dir).
    """
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(
        tmp_repo,
        predictive_bundle_payload=predictive_bundle_payload,
        include_visualizations=include_visualizations,
    )
    result = validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert result["validation_outcome"] == "accepted"
    source_run_dir = _latest_run_dir(tmp_repo)
    _write_terminal_result(source_run_dir, model_source_mode=model_source_mode)
    return candidate_dir, source_run_dir


def _hash_tree(paths: list) -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_valid_decision_creates_new_accepted_run_with_promotion_eligible(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "reviewed"
    assert result["validation_outcome"] == "accepted"
    assert result["promotion_eligible"] is True
    assert result["new_run_id"] != source_run_dir.name
    assert result["manifest_generated"] is True

    new_run_dir = tmp_repo / result["new_run_dir"]
    new_validation_result = json.loads((new_run_dir / "validation-result.json").read_text())
    evaluation = new_validation_result["operational_readiness_evaluation"]
    assert evaluation["source"] == "governed_decision"
    assert evaluation["decision_valid"] is True
    assert new_validation_result["promotion_gate"] == {"promotion_allowed": True, "registry_update_allowed": True}

    decision_on_disk = json.loads((new_run_dir / "operational-readiness-decision.json").read_text())
    # The threshold actually bound into the decision is the operator's own
    # value, never the bundle's distinct educational_threshold (0.99).
    assert decision_on_disk["decision"]["operational_threshold"]["value"] == 0.31


def test_unresolved_decision_remains_promotion_ineligible(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, UNRESOLVED_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "reviewed"
    assert result["promotion_eligible"] is False


def test_source_run_candidate_and_bundle_remain_byte_identical(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    predictive_bundle_path = candidate_dir / "artifacts" / "predictive_bundle.json"

    watched_paths = [
        source_run_dir / "validation-result.json",
        source_run_dir / "validated-run-terminal-result.json",
        candidate_dir / "release-candidate.json",
        predictive_bundle_path,
    ]
    before = _hash_tree(watched_paths)

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )
    assert result["review_status"] == "reviewed"

    after = _hash_tree(watched_paths)
    assert before == after


def test_source_bindings_are_computed_by_atlas_not_the_operator(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    predictive_bundle_path = candidate_dir / "artifacts" / "predictive_bundle.json"
    expected_rc_sha256 = hashlib.sha256((candidate_dir / "release-candidate.json").read_bytes()).hexdigest()
    expected_pb_sha256 = hashlib.sha256(predictive_bundle_path.read_bytes()).hexdigest()

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )
    new_run_dir = tmp_repo / result["new_run_dir"]
    decision_on_disk = json.loads((new_run_dir / "operational-readiness-decision.json").read_text())

    assert decision_on_disk["source_bindings"]["release_candidate"]["sha256"] == expected_rc_sha256
    assert decision_on_disk["source_bindings"]["predictive_bundle"]["sha256"] == expected_pb_sha256
    # operator_decision never carried a sha256/promotion_allowed field at all
    # (VALID_OPERATOR_DECISION has no such keys) -- these bindings could only
    # have come from Atlas's own filesystem reads.


def test_malformed_run_id_blocks(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    (tmp_repo / "publisher" / "runs").mkdir(parents=True, exist_ok=True)

    result = operational_readiness.review_operational_readiness(
        "../../etc/passwd", VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "unsafe_run_reference"


def test_unknown_run_id_blocks(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    (tmp_repo / "publisher" / "runs").mkdir(parents=True, exist_ok=True)

    result = operational_readiness.review_operational_readiness(
        "validate-does-not-exist", VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "source_run_not_found"


def test_internal_provenance_blocks_review(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo,
        predictive_bundle_payload=_artifact_payload("predictive_bundle"),
        model_source_mode="atlas_internal_training",
        include_visualizations=True,
    )

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "non_external_provenance_rejected"


def test_operator_cannot_supply_promotion_allowed(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    tampered_decision = dict(VALID_OPERATOR_DECISION)
    tampered_decision["promotion_allowed"] = True

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, tampered_decision, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "operator_supplied_forbidden_field"


def test_operator_cannot_supply_sha256_binding(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    tampered_decision = dict(VALID_OPERATOR_DECISION)
    tampered_decision["sha256"] = "0" * 64

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, tampered_decision, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "operator_supplied_forbidden_field"


def test_empty_decision_basis_blocks(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    empty_basis_decision = dict(VALID_OPERATOR_DECISION)
    empty_basis_decision["decision_basis"] = "   "

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, empty_basis_decision, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "decision_basis_empty"


def test_resolved_threshold_outside_range_blocks(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )
    out_of_range_decision = dict(VALID_OPERATOR_DECISION)
    out_of_range_decision["operational_threshold"] = {
        "status": "resolved",
        "value": 1.5,
        "selection_basis": "invalid",
    }

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, out_of_range_decision, repo_root=tmp_repo
    )

    assert result["review_status"] == "blocked"
    assert result["reason_code"] == "operational_threshold_out_of_range"


def test_stale_decision_binding_is_rejected_by_validate(tmp_path):
    """A hand-crafted decision whose source_bindings do not match the
    current candidate files (simulating reuse of a stale decision) must be
    rejected by publisher.validate's own independent hash verification --
    the decision_valid/promotion_gate must fail closed even though every
    decision field otherwise looks confirmed/resolved/available."""
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )

    stale_decision = {
        "schema_version": "operational-readiness-decision.v1",
        "artifact_kind": "operational_readiness_decision",
        "created_at": "2026-01-01T00:00:00Z",
        "source_run": {"run_id": source_run_dir.name},
        "candidate_identity": {
            "dataset_slug": DATASET_SLUG,
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
        },
        "source_bindings": {
            "release_candidate": {"path": "release-candidate.json", "sha256": "0" * 64},
            "predictive_bundle": {"path": "artifacts/predictive_bundle.json", "sha256": "1" * 64},
            "validated_run_terminal_result": {
                "path": f"publisher/runs/{source_run_dir.name}/validated-run-terminal-result.json",
                "sha256": "2" * 64,
            },
        },
        "source_readiness": {
            "operational_validity": "unconfirmed",
            "operational_threshold": {"status": "unresolved", "value": None},
            "operational_prediction_available": False,
        },
        "decision": {
            "operational_validity": "confirmed",
            "operational_threshold": {"status": "resolved", "value": 0.5, "selection_basis": "stale"},
            "operational_prediction_available": True,
            "decision_basis": "Stale decision replay attempt.",
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

    result = validate.run(str(candidate_dir), repo_root=tmp_repo, operational_readiness_decision=stale_decision)

    assert result["validation_outcome"] == "accepted"
    assert result["operational_readiness_evaluation"]["decision_valid"] is False
    assert result["promotion_gate"] == {"promotion_allowed": False, "registry_update_allowed": False}


def test_review_never_promotes_or_updates_registry(tmp_path):
    tmp_repo = tmp_path / "repo"
    candidate_dir, source_run_dir = _prepare_source_run(
        tmp_repo, predictive_bundle_payload=_external_predictive_bundle_payload()
    )

    result = operational_readiness.review_operational_readiness(
        source_run_dir.name, VALID_OPERATOR_DECISION, repo_root=tmp_repo
    )

    assert result["review_status"] == "reviewed"
    assert result["boundary_confirmations"]["promotion_invoked"] is False
    assert result["boundary_confirmations"]["registry_update_invoked"] is False
    assert not (tmp_repo / "releases" / RELEASE_ID).exists()
    assert not (tmp_repo / "registry").exists()
