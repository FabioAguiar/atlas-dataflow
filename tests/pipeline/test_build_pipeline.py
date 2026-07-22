import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate, training  # noqa: E402
from publisher import validate  # noqa: E402


DATASET_SLUG = "telco-customer-churn"
RELEASE_ID = "release-20260620-001"
RELEASE_VERSION = "2026.06.20"


PUBLIC_CANDIDATE_ARTIFACTS = (
    "contracts/runtime-contract.json",
    "contracts/public-contract.json",
    "metrics/metrics.json",
    "predictions/bundle.json",
    "model-card.json",
    "public-context.json",
    "visualizations/visualizations.json",
    "manifest-input.json",
    "models/model.pkl",
)

# Project Spec S0107: the model artifact is a private binary, never JSON.
MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-for-build-pipeline"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()


# A minimal public_contract fixture that conforms to
# contracts/public-contract.schema.json (Project Spec S0106) -- the generic
# {"role": ..., "governed": True} placeholder used for other roles is not
# schema-valid for public_contract and fails real publisher validation.
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


# A minimal analytical-visualizations.v1 fixture (Project Spec S0128/S0133)
# that conforms to pipeline/analytical-visualizations.schema.json --
# additionalProperties: false, so no generic {"role": ..., "governed": True}
# placeholder can satisfy it. training_run_identity.dataset_slug must match
# DATASET_SLUG: publisher/validate.py's cross-artifact identity check reads
# a JSON artifact's dataset_slug from training_run_identity when no other
# identity shape is present, and rejects a mismatch against the candidate's
# own dataset_identity.dataset_slug.
_VALID_VISUALIZATIONS = {
    "schema_version": "analytical-visualizations.v1",
    "artifact_kind": "analytical_visualizations",
    "created_at": "2026-06-20T00:00:00Z",
    "training_run_identity": {
        "dataset_slug": DATASET_SLUG,
        "run_id": "train-20260620T000000Z",
        "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260620T000000Z/",
    },
    "charts": [
        {
            "id": "target_distribution",
            "title": "Target Distribution",
            "type": "bar",
            "x_label": "Target",
            "y_label": "Rows",
            "data": [
                {"name": "No", "value": 6},
                {"name": "Yes", "value": 4},
            ],
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


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _artifact(path: Path, role: str, *, availability_status: str = "real_dataflow_artifact") -> dict:
    return {
        "role": role,
        "required": True,
        "source_stage": "M26",
        "path": str(path),
        "contract_version": f"{role}.v1",
        "sha256": "0" * 64,
        "hash_policy": "sha256_required",
        "public_projection": "internal_only",
        "evidence_classification": "not_evidence",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
        "availability_status": availability_status,
    }


def _write_governed_artifacts(repo_root: Path, *, missing_role: str | None = None) -> dict:
    source_dir = Path("governed-artifacts")
    paths = {
        "discovery_evidence": source_dir / "m22" / "discovery-evidence.json",
        "execution_contract": source_dir / "m23" / "execution-contract.json",
        "runtime_contract": source_dir / "m23" / "runtime-contract.json",
        "public_contract": source_dir / "m23" / "public-contract.json",
        "preparation_recipe": source_dir / "m22" / "preparation-recipe.json",
        "prepared_data_metadata": source_dir / "m23" / "prepared-data-metadata.json",
        "training_parameter_record": source_dir / "m24" / "training-parameter-record.json",
        "model_artifact": source_dir / "m24" / training.MODEL_ARTIFACT_FILENAME,
        "training_metrics": source_dir / "m24" / "metrics.json",
        "model_card": source_dir / "m24" / "model-card.json",
        "public_context": source_dir / "m23" / "public-context.json",
        "visualizations": source_dir / "m24" / "visualizations.json",
        "inference_bundle": source_dir / "m25" / "bundle.json",
    }
    for role, path in paths.items():
        if role == missing_role:
            continue
        if role == "model_artifact":
            (repo_root / path).parent.mkdir(parents=True, exist_ok=True)
            (repo_root / path).write_bytes(MODEL_ARTIFACT_BYTES)
            continue
        if role == "public_contract":
            payload = _VALID_PUBLIC_CONTRACT
        elif role == "visualizations":
            payload = _VALID_VISUALIZATIONS
        else:
            payload = {"role": role, "governed": True}
        if role == "inference_bundle":
            payload["model_artifact"] = {
                "path": "models/model.pkl",
                "sha256": MODEL_ARTIFACT_SHA256,
            }
        _write_json(repo_root / path, payload)
    return paths


def _write_candidate_input(tmp_path: Path, **overrides) -> Path:
    paths = overrides.pop("artifact_paths", None) or _write_governed_artifacts(tmp_path)
    data = {
        "contract_version": "release-candidate-input.v1",
        "input_kind": "release_candidate_input",
        "dataset_identity": {
            "dataset_slug": DATASET_SLUG,
            "dataset_title": "Telco Customer Churn",
        },
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-06-20T00:00:00Z",
        },
        "source_run": {
            "run_id": "candidate-input-20260620T000000Z",
            "producer": "test-governed-input",
            "created_at": "2026-06-20T00:00:00Z",
        },
        "artifact_inputs": {
            "discovery_evidence": _artifact(paths["discovery_evidence"], "discovery_evidence"),
            "promoted_contracts": {
                "execution_contract": _artifact(paths["execution_contract"], "execution_contract"),
                "runtime_contract": _artifact(paths["runtime_contract"], "runtime_contract"),
                "public_contract": _artifact(
                    paths["public_contract"],
                    "public_contract",
                ) | {
                    "public_projection": "public_artifact",
                    "evidence_classification": "public_artifact",
                },
            },
            "preparation_recipe": _artifact(paths["preparation_recipe"], "preparation_recipe"),
            "prepared_data_metadata": _artifact(
                paths["prepared_data_metadata"],
                "prepared_data_metadata",
            ),
            "training_parameter_record": _artifact(
                paths["training_parameter_record"],
                "training_parameter_record",
            ),
            "model_artifact": _artifact(paths["model_artifact"], "model_artifact"),
            "training_metrics": _artifact(paths["training_metrics"], "training_metrics") | {
                "public_projection": "public_artifact",
                "evidence_classification": "public_artifact",
            },
            "model_card": _artifact(paths["model_card"], "model_card") | {
                "public_projection": "public_artifact",
                "evidence_classification": "public_artifact",
            },
            "public_context": _artifact(paths["public_context"], "public_context") | {
                "public_projection": "public_artifact",
                "evidence_classification": "public_artifact",
            },
            "visualizations": _artifact(paths["visualizations"], "visualizations") | {
                "public_projection": "public_artifact",
                "evidence_classification": "public_artifact",
            },
            "inference_bundle": _artifact(paths["inference_bundle"], "inference_bundle") | {
                "public_projection": "public_reference_only",
            },
            "internal_evidence_references": [
                {
                    "role": "internal_evidence_reference",
                    "path": "evidence/internal-only.json",
                    "public_projection": "internal_only",
                }
            ],
        },
        "candidate_mapping": {
            "candidate_layout_schema": "pipeline/candidate-layout.schema.json",
            "publisher_release_candidate_schema": "publisher/release-candidate.schema.json",
            "publisher_release_manifest_schema": "publisher/release-manifest.schema.json",
            "publisher_validation_schema": "publisher/validation/release-candidate-validation.schema.json",
        },
        "classification_policy": {
            "public_artifacts_exclude_internal_evidence": True,
        },
        "boundary_confirmations": {
            "candidate_assembly_only": True,
            "promotion_not_included": True,
            "registry_activation_not_included": True,
            "model_training_not_included": True,
        },
    }
    data.update(overrides)

    candidate_input = tmp_path / "release-candidate-input.json"
    _write_json(candidate_input, data)
    return candidate_input


def _copy_publisher_operational_note(tmp_repo: Path) -> None:
    src = REPO_ROOT / "publisher" / "release-candidate.operational-note.json"
    dst = tmp_repo / "publisher" / "release-candidate.operational-note.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _assemble_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate_input: Path | None = None,
) -> tuple[int, dict, Path]:
    tmp_repo = tmp_path / "repo"
    output_dir = tmp_repo / "releases" / "candidates"
    candidate_input = candidate_input or _write_candidate_input(
        tmp_path,
        artifact_paths=_write_governed_artifacts(tmp_repo),
    )
    schema_dst = tmp_repo / "pipeline" / "build-evidence.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pipeline" / "build-evidence.schema.json", schema_dst)

    public_contract_schema_dst = tmp_repo / "contracts" / "public-contract.schema.json"
    public_contract_schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "contracts" / "public-contract.schema.json", public_contract_schema_dst)

    visualizations_schema_dst = tmp_repo / "pipeline" / "analytical-visualizations.schema.json"
    visualizations_schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json",
        visualizations_schema_dst,
    )

    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(candidate_input),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = assemble_candidate.main()
    candidate_dir = output_dir / DATASET_SLUG / RELEASE_ID
    return exit_code, json.loads((candidate_dir / "release-candidate.json").read_text()), candidate_dir


def test_successful_build_creates_candidate_layout_and_required_artifacts(tmp_path, monkeypatch):
    exit_code, release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)

    assert exit_code == 0
    assert candidate_dir.is_dir()
    assert release_candidate["dataset_identity"]["dataset_slug"] == DATASET_SLUG
    assert release_candidate["release_identity"]["release_id"] == RELEASE_ID
    assert release_candidate["release_identity"]["release_version"] == RELEASE_VERSION

    for relative in PUBLIC_CANDIDATE_ARTIFACTS:
        assert (candidate_dir / relative).is_file()

    assert (candidate_dir / "release-candidate.json").is_file()
    assert (candidate_dir / "build-evidence.json").is_file()
    assert "build-evidence.json" not in {
        role["path"] for role in release_candidate["artifact_roles"].values()
    }
    assert set(
        release_candidate["candidate_metadata"]["completeness_validation"]["required_artifact_roles"]
    ) == {
        "contracts",
        "public_contract",
        "predictive_bundle",
        "metrics",
        "model_card",
        "public_context",
        "visualizations",
        "manifest_input",
        "candidate_metadata",
        "model_artifact",
    }


# --- S0107: release-bound model artifact packaging ---


def test_successful_build_copies_model_artifact_and_declares_role(tmp_path, monkeypatch):
    tmp_repo = tmp_path / "repo"
    artifact_paths = _write_governed_artifacts(tmp_repo)
    exit_code, release_candidate, candidate_dir = _assemble_candidate(
        tmp_path,
        monkeypatch,
        candidate_input=_write_candidate_input(tmp_path, artifact_paths=artifact_paths),
    )

    assert exit_code == 0
    model_role = release_candidate["artifact_roles"]["model_artifact"]
    assert model_role == {
        "role": "model_artifact",
        "path": "models/model.pkl",
        "required": True,
        "media_type": "application/octet-stream",
    }
    assert release_candidate["candidate_metadata"]["completeness_validation"][
        "required_artifact_roles"
    ].count("model_artifact") == 1
    assert len(
        release_candidate["candidate_metadata"]["completeness_validation"]["required_artifact_roles"]
    ) == 10

    packaged_model = candidate_dir / "models" / "model.pkl"
    assert packaged_model.is_file()
    source_model = tmp_repo / artifact_paths["model_artifact"]
    assert packaged_model.read_bytes() == source_model.read_bytes()


# --- S0128/S0133: release-bound visualizations artifact packaging ---


def test_successful_build_copies_visualizations_artifact_and_declares_role(tmp_path, monkeypatch):
    tmp_repo = tmp_path / "repo"
    artifact_paths = _write_governed_artifacts(tmp_repo)
    exit_code, release_candidate, candidate_dir = _assemble_candidate(
        tmp_path,
        monkeypatch,
        candidate_input=_write_candidate_input(tmp_path, artifact_paths=artifact_paths),
    )

    assert exit_code == 0
    visualizations_role = release_candidate["artifact_roles"]["visualizations"]
    assert visualizations_role == {
        "role": "visualizations",
        "path": "visualizations/visualizations.json",
        "required": True,
        "media_type": "application/json",
    }
    assert release_candidate["candidate_metadata"]["completeness_validation"][
        "required_artifact_roles"
    ].count("visualizations") == 1
    assert len(
        release_candidate["candidate_metadata"]["completeness_validation"]["required_artifact_roles"]
    ) == 10

    packaged_visualizations = candidate_dir / "visualizations" / "visualizations.json"
    assert packaged_visualizations.is_file()
    source_visualizations = tmp_repo / artifact_paths["visualizations"]
    assert packaged_visualizations.read_bytes() == source_visualizations.read_bytes()


def test_successful_build_writes_reduced_evidence_and_boundary_confirmations(tmp_path, monkeypatch):
    exit_code, _release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)

    assert exit_code == 0
    evidence = json.loads((candidate_dir / "build-evidence.json").read_text())
    assert evidence["schema_version"] == "build-evidence.v1"
    assert evidence["source_input"]["dataset_slug"] == DATASET_SLUG
    assert evidence["source_input"]["release_id"] == RELEASE_ID
    assert evidence["source_input"]["contract_version"] == "release-candidate-input.v1"
    assert evidence["publisher_validation"] == {
        "valid": True,
        "validation_outcome": "accepted",
        "validated_at": evidence["publisher_validation"]["validated_at"],
    }
    assert evidence["build_boundary_confirmations"] == {
        "promotion_occurred": False,
        "registry_mutation_occurred": False,
    }
    assert evidence["evidence_policy"] == {
        "raw_logs_prohibited": True,
        "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True,
        "secrets_prohibited": True,
        "private_source_paths_prohibited": True,
        "reduced_and_sanitized": True,
    }
    assert "build-evidence.json" not in evidence["assembled_artifacts"]
    assert "role_results" not in evidence["publisher_validation"]
    assert "schema_compatibility" not in evidence["publisher_validation"]


def test_missing_required_artifact_rejects_without_publishable_candidate(
    tmp_path,
    monkeypatch,
    capsys,
):
    tmp_repo = tmp_path / "repo"
    artifact_paths = _write_governed_artifacts(tmp_repo, missing_role="public_contract")
    candidate_input = _write_candidate_input(tmp_path, artifact_paths=artifact_paths)

    output_dir = tmp_repo / "releases" / "candidates"
    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(candidate_input),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "candidate_artifact_missing"
    assert str(artifact_paths["public_contract"]) in result["missing_paths"]
    assert not (output_dir / DATASET_SLUG / RELEASE_ID / "release-candidate.json").exists()


def test_missing_required_candidate_input_field_rejects_before_candidate_creation(
    tmp_path,
    monkeypatch,
    capsys,
):
    tmp_repo = tmp_path / "repo"
    candidate_input = _write_candidate_input(
        tmp_path,
        artifact_paths=_write_governed_artifacts(tmp_repo),
    )
    data = json.loads(candidate_input.read_text())
    del data["release_identity"]["release_id"]
    candidate_input.write_text(json.dumps(data, indent=2), encoding="utf-8")

    output_dir = tmp_repo / "releases" / "candidates"
    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(candidate_input),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "candidate_input_parse"
    assert result["release_id"] is None
    assert not output_dir.exists()


def test_placeholder_only_required_artifact_rejects_before_candidate_creation(
    tmp_path,
    monkeypatch,
    capsys,
):
    tmp_repo = tmp_path / "repo"
    candidate_input = _write_candidate_input(
        tmp_path,
        artifact_paths=_write_governed_artifacts(tmp_repo),
    )
    data = json.loads(candidate_input.read_text())
    artifact = data["artifact_inputs"]["training_metrics"]
    artifact["availability_status"] = "placeholder_only"
    artifact["placeholder_policy"]["placeholders_allowed"] = True
    candidate_input.write_text(json.dumps(data, indent=2), encoding="utf-8")

    output_dir = tmp_repo / "releases" / "candidates"
    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(candidate_input),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "candidate_input_parse"
    assert any("placeholder" in error for error in result["validation_errors"])
    assert not output_dir.exists()


def test_invalid_public_projection_rejects_in_publisher_validation(tmp_path, monkeypatch, capsys):
    tmp_repo = tmp_path / "repo"
    artifact_paths = _write_governed_artifacts(tmp_repo)
    (tmp_repo / artifact_paths["model_card"]).write_text("not json", encoding="utf-8")
    candidate_input = _write_candidate_input(tmp_path, artifact_paths=artifact_paths)

    output_dir = tmp_repo / "releases" / "candidates"
    schema_dst = tmp_repo / "pipeline" / "build-evidence.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pipeline" / "build-evidence.schema.json", schema_dst)
    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(candidate_input),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "publisher_validation"
    rejection_codes = {
        reason["code"]
        for reason in result["publisher_validation"]["rejection_reasons"]
    }
    assert "model_card_schema_incompatible" in rejection_codes


def test_assembled_candidate_is_publisher_validation_compatible_without_promotion(
    tmp_path,
    monkeypatch,
):
    exit_code, _release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)
    assert exit_code == 0

    tmp_repo = tmp_path / "repo"
    _copy_publisher_operational_note(tmp_repo)
    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["promotion_gate"] == {
        "promotion_allowed": True,
        "registry_update_allowed": True,
    }
    assert validation_result["publisher_boundaries"]["release_promoted"] is False
    assert validation_result["publisher_boundaries"]["registry_updated"] is False
    assert (tmp_repo / "publisher" / "runs").is_dir()
    assert not (tmp_repo / "releases" / RELEASE_ID).exists()
    assert not (tmp_repo / "registry" / "datasets.json").exists()


# --- release-candidate data handoff readiness (Project Spec S0016) ---


def _write_handoff_governed_artifacts(repo_root: Path) -> dict[str, str]:
    paths = {
        "discovery_evidence": "governed-artifacts/m22/discovery-evidence.json",
        "execution_contract": "governed-artifacts/m23/execution-contract.json",
        "runtime_contract": "governed-artifacts/m23/runtime-contract.json",
        "public_contract": "governed-artifacts/m23/public-contract.json",
        "preparation_recipe": "governed-artifacts/m22/preparation-recipe.json",
        "prepared_data_metadata": "governed-artifacts/m23/prepared-data-metadata.json",
        "training_parameter_record": "governed-artifacts/m24/training-parameter-record.json",
        "model_artifact": f"governed-artifacts/m24/{training.MODEL_ARTIFACT_FILENAME}",
        "training_metrics": "governed-artifacts/m24/metrics.json",
        "model_card": "governed-artifacts/m24/model-card.json",
        "public_context": "governed-artifacts/m23/public-context.json",
        "visualizations": "governed-artifacts/m24/visualizations.json",
        "inference_bundle": "governed-artifacts/m25/bundle.json",
    }
    for role, relative in paths.items():
        _write_json(repo_root / relative, {"role": role, "governed": True})
    return paths


def test_handoff_readiness_missing_required_role_rejects(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    del paths["training_metrics"]

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    assert "training_metrics" in readiness["not_ready_roles"]
    metrics_result = next(r for r in readiness["role_results"] if r["role"] == "training_metrics")
    assert metrics_result["reason"] == "missing_reference"


def test_handoff_readiness_missing_visualizations_role_rejects(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    del paths["visualizations"]

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    assert "visualizations" in readiness["not_ready_roles"]
    visualizations_result = next(
        r for r in readiness["role_results"] if r["role"] == "visualizations"
    )
    assert visualizations_result["reason"] == "missing_reference"


def test_handoff_readiness_rejects_absolute_path(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    paths["model_card"] = "/etc/passwd"

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    model_card_result = next(r for r in readiness["role_results"] if r["role"] == "model_card")
    assert model_card_result["reason"] == "absolute_path_rejected"


def test_handoff_readiness_rejects_parent_traversal(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    paths["public_context"] = "../outside-repo/public-context.json"

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    public_context_result = next(
        r for r in readiness["role_results"] if r["role"] == "public_context"
    )
    assert public_context_result["reason"] == "parent_traversal_rejected"


def test_handoff_readiness_rejects_fixture_only_path(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    fixture_relative = "pipeline/examples/release-candidate-input.example.json"
    _write_json(tmp_repo / fixture_relative, {"role": "inference_bundle"})
    paths["inference_bundle"] = fixture_relative

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    bundle_result = next(r for r in readiness["role_results"] if r["role"] == "inference_bundle")
    assert bundle_result["reason"] == "fixture_only_path_rejected"


def test_handoff_readiness_rejects_placeholder_only_content(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    placeholder_relative = "governed-artifacts/m24/model-card.json"
    _write_json(
        tmp_repo / placeholder_relative,
        {"role": "model_card", "placeholder_only": True},
    )

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is False
    model_card_result = next(r for r in readiness["role_results"] if r["role"] == "model_card")
    assert model_card_result["reason"] == "placeholder_only_content_rejected"


def test_handoff_readiness_explicit_real_references_are_ready(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["is_release_candidate_input_ready"] is True
    assert readiness["not_ready_roles"] == []
    assert readiness["blocking_reasons"] == []
    assert set(readiness["required_roles"]) == set(assemble_candidate._HANDOFF_REQUIRED_ROLES)
    assert all(result["ready"] for result in readiness["role_results"])


def test_handoff_readiness_uses_explicit_repo_root_for_public_context(tmp_path, monkeypatch):
    tmp_repo = tmp_path / "repo"
    nested_notebook_dir = tmp_repo / "notebooks" / "datasets" / DATASET_SLUG
    nested_notebook_dir.mkdir(parents=True)
    paths = _write_handoff_governed_artifacts(tmp_repo)
    paths["public_context"] = f"contracts/{DATASET_SLUG}/dataset-context.json"
    _write_json(tmp_repo / paths["public_context"], {"role": "public_context", "governed": True})

    monkeypatch.chdir(nested_notebook_dir)
    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    public_context_result = next(
        r for r in readiness["role_results"] if r["role"] == "public_context"
    )
    assert public_context_result == {
        "role": "public_context",
        "path": f"contracts/{DATASET_SLUG}/dataset-context.json",
        "ready": True,
        "reason": None,
    }


def test_handoff_readiness_model_artifact_uses_training_filename(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)

    assert paths["model_artifact"].endswith(f"/{training.MODEL_ARTIFACT_FILENAME}")

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    model_result = next(r for r in readiness["role_results"] if r["role"] == "model_artifact")
    assert model_result["path"] == f"governed-artifacts/m24/{training.MODEL_ARTIFACT_FILENAME}"
    assert model_result["ready"] is True


def test_handoff_readiness_never_performs_assembly_or_downstream_actions(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    before_entries = sorted(p.relative_to(tmp_repo) for p in tmp_repo.rglob("*") if p.is_file())

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        paths, repo_root=tmp_repo
    )

    assert readiness["handoff_boundary_confirmations"] == {
        "release_candidate_assembly_performed": False,
        "publisher_validation_performed": False,
        "publisher_promotion_performed": False,
        "registry_activation_performed": False,
        "api_data_available": False,
        "ui_data_available": False,
    }
    after_entries = sorted(p.relative_to(tmp_repo) for p in tmp_repo.rglob("*") if p.is_file())
    assert before_entries == after_entries
    assert not (tmp_repo / "releases" / "candidates").exists()


def test_handoff_readiness_defaults_to_empty_references(tmp_path):
    tmp_repo = tmp_path / "repo"
    _write_handoff_governed_artifacts(tmp_repo)

    readiness = assemble_candidate.build_release_candidate_handoff_readiness({}, repo_root=tmp_repo)

    assert readiness["is_release_candidate_input_ready"] is False
    assert len(readiness["not_ready_roles"]) == len(assemble_candidate._HANDOFF_REQUIRED_ROLES)
