import builtins
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate, generate_inference_bundle  # noqa: E402
from publisher import evidence, manifest, promote, validate  # noqa: E402
from registry import update as registry_update  # noqa: E402


DATASET_SLUG = "example-dataset"
RELEASE_ID = "release-20260619-001"
PREVIOUS_RELEASE_ID = "release-20260618-001"
RELEASE_VERSION = "2026.06.19"

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

# Project Spec S0107: the model artifact is a private binary, never JSON --
# a fixed fixture payload with its precomputed hash, reused everywhere a
# release candidate needs a real, hashable model_artifact role file.
MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-not-a-real-model"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()
MODEL_ARTIFACT_PATH = "models/model.pkl"


def _copy_publisher_contracts(tmp_repo: Path) -> None:
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/validation/release-candidate-validation.schema.json",
        "publisher/evidence/publication-validation-evidence.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
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
            "dataset_slug": {
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "description": "Stable dataset identifier.",
            },
            "release_id": {
                "pattern": "^release-[0-9]{8}-[0-9]{3}$",
                "description": "Stable release identifier.",
            },
            "active_release": {
                "description": "Release currently served for the dataset.",
            },
        },
        "datasets": [{
            "dataset_slug": DATASET_SLUG,
            "active_release": PREVIOUS_RELEASE_ID,
            "public_metadata": {
                "title": "Example Dataset",
                "summary": "Publisher flow fixture.",
                "domain": "example",
                "visibility": "public",
                "tags": ["example", "publisher"],
            },
        }],
    }
    (registry_dir / "datasets.json").write_text(
        json.dumps(registry, indent=2),
        encoding="utf-8",
    )


def _candidate_dir(tmp_repo: Path, release_id: str = RELEASE_ID) -> Path:
    return tmp_repo / "releases" / "candidates" / DATASET_SLUG / release_id


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    if role == "visualizations":
        return "visualizations/visualizations.json"
    return f"artifacts/{role}.json"


# A minimal analytical-visualizations.v1 fixture (Project Spec S0128/S0133)
# that conforms to pipeline/analytical-visualizations.schema.json.
# training_run_identity.dataset_slug must match the release candidate's own
# dataset_identity.dataset_slug: publisher/validate.py's cross-artifact
# identity check falls back to training_run_identity for a JSON artifact's
# dataset_slug when no other identity shape is present.
def _visualizations_payload(dataset_slug: str, created_at: str, run_id: str) -> dict:
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": created_at,
        "training_run_identity": {
            "dataset_slug": dataset_slug,
            "run_id": run_id,
            "output_directory": f"pipeline/training-runs/{dataset_slug}/{run_id}/",
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


def _artifact_payload(role: str) -> dict:
    if role == "public_contract":
        # A real contracts/public-contract.schema.json instance
        # (additionalProperties: false) -- cannot carry the generic
        # dataset_identity/role/etc keys the other roles use below
        # (Project Spec S0101).
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
    if role == "visualizations":
        # A real pipeline/analytical-visualizations.schema.json instance
        # (additionalProperties: false) -- cannot carry the generic
        # dataset_identity/role/etc keys the other roles use below
        # (Project Spec S0128).
        return _visualizations_payload(DATASET_SLUG, "2026-06-19T00:00:00Z", "train-20260619T000000Z")
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


def _write_candidate(
    tmp_repo: Path,
    missing_role: str | None = None,
    *,
    role_payload_overrides: dict[str, dict] | None = None,
    omit_role: str | None = None,
) -> Path:
    """Write a synthetic release candidate.

    `missing_role` declares the role in `artifact_roles` (and in
    `completeness_validation.required_artifact_roles`) but writes no file for
    it -- simulates a *missing* required artifact. `omit_role` (Project Spec
    S0188) structurally omits the role from `artifact_roles` and from
    `required_artifact_roles` entirely, and writes no file -- simulates a
    role that a validated external fitted-model candidate legitimately never
    declared, distinct from a declared-but-missing role.
    """
    candidate_dir = _candidate_dir(tmp_repo)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        if role == omit_role:
            continue
        role_path = _role_path(role)
        artifact_roles[role] = {
            "role": role,
            "path": role_path,
            "required": True,
        }
        if role == missing_role:
            continue

        artifact_path = candidate_dir / role_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_artifact":
            artifact_path.write_bytes(MODEL_ARTIFACT_BYTES)
        else:
            payload = (
                role_payload_overrides[role]
                if role_payload_overrides and role in role_payload_overrides
                else _artifact_payload(role)
            )
            artifact_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {
            "dataset_slug": DATASET_SLUG,
            "dataset_title": "Example Dataset",
        },
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-06-19T00:00:00Z",
        },
        "source_run": {
            "run_id": "test-run",
            "producer": "pytest",
            "created_at": "2026-06-19T00:00:00Z",
        },
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-06-19T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": [role for role in REQUIRED_ROLES if role != omit_role],
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
    (candidate_dir / "release-candidate.json").write_text(
        json.dumps(candidate, indent=2),
        encoding="utf-8",
    )
    return candidate_dir


def _latest_run_dir(tmp_repo: Path) -> Path:
    runs_dir = tmp_repo / "publisher" / "runs"
    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    assert run_dirs
    return run_dirs[-1]


def _release_tree_hash(release_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in release_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(release_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _prepare_tmp_repo(tmp_path: Path) -> Path:
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(tmp_repo)
    return tmp_repo


def test_valid_publisher_flow_records_publication_evidence(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_dir = _candidate_dir(tmp_repo)

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert validation_result["validation_outcome"] == "accepted"

    run_dir = _latest_run_dir(tmp_repo)
    manifest_result = manifest.run(str(run_dir), repo_root=tmp_repo)
    assert manifest_result["schema_version"] == "release-manifest.v1"

    promotion_result = promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
    assert registry_result["update_applied"] is True

    publication_evidence = evidence.run(
        str(run_dir),
        registry_result,
        repo_root=tmp_repo,
    )

    evidence_path = run_dir / "publication-evidence.json"
    assert evidence_path.is_file()
    assert publication_evidence["evidence_kind"] == "publication_validation_evidence"
    assert publication_evidence["candidate_validation"]["dataset_slug"] == DATASET_SLUG
    assert publication_evidence["promotion_validation"]["promotion_outcome"] == "promoted"
    assert publication_evidence["previous_release_preservation"][
        "previous_active_release_id"
    ] == PREVIOUS_RELEASE_ID
    assert publication_evidence["evidence_safety"]["raw_artifact_contents_embedded"] is False

    registry_after = json.loads((tmp_repo / "registry" / "datasets.json").read_text())
    assert registry_after["datasets"][0]["active_release"] == RELEASE_ID


def test_invalid_candidate_rejection_uses_temporary_candidate(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="metrics")

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert validation_result["promotion_gate"]["promotion_allowed"] is False
    assert (tmp_repo / "publisher" / "runs").is_dir()


def test_second_promotion_for_same_release_is_rejected_without_overwrite(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)
    promote.run(str(run_dir), repo_root=tmp_repo)

    release_dir = tmp_repo / "releases" / RELEASE_ID
    before_hash = _release_tree_hash(release_dir)

    with pytest.raises(RuntimeError, match="already exists"):
        promote.run(str(run_dir), repo_root=tmp_repo)

    assert _release_tree_hash(release_dir) == before_hash


def test_registry_update_uses_temporary_registry_only(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)
    promote.run(str(run_dir), repo_root=tmp_repo)

    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)

    assert registry_result["dataset_slug"] == DATASET_SLUG
    assert registry_result["release_id"] == RELEASE_ID
    assert registry_result["previous_active_release_id"] == PREVIOUS_RELEASE_ID
    assert (tmp_repo / "registry" / "datasets.json.previous").is_file()


# ---------------------------------------------------------------------------
# Project Spec S0043: slug collision/reuse coverage through the full
# validate -> manifest -> promote -> registry_update pipeline. Complements
# the unit-level allocate_unique_dataset_slug() coverage in
# tests/registry/test_registry_validation.py and the admin_runs.py-mocked
# coverage in tests/api/test_admin_run_listing.py by exercising the real
# publisher artifact copy + registry write path end to end.
# ---------------------------------------------------------------------------


def _write_registry_with_datasets(tmp_repo: Path, datasets: list) -> None:
    registry_dir = tmp_repo / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "description": "Stable dataset identifier.",
            },
            "release_id": {
                "pattern": "^release-[0-9]{8}-[0-9]{3}$",
                "description": "Stable release identifier.",
            },
            "active_release": {
                "description": "Release currently served for the dataset.",
            },
        },
        "datasets": datasets,
    }
    (registry_dir / "datasets.json").write_text(
        json.dumps(registry, indent=2),
        encoding="utf-8",
    )


def _dataset_entry(slug: str, active_release: str) -> dict:
    return {
        "dataset_slug": slug,
        "active_release": active_release,
        "public_metadata": {
            "title": "Example Dataset",
            "summary": "Publisher flow fixture.",
            "domain": "example",
            "visibility": "public",
            "tags": ["example", "publisher"],
        },
    }


def _validate_manifest_promote(tmp_repo: Path) -> Path:
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)
    promote.run(str(run_dir), repo_root=tmp_repo)
    return run_dir


def test_create_new_dataset_detail_mode_allocates_numbered_slug_and_preserves_existing_entry(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry_with_datasets(tmp_repo, [_dataset_entry(DATASET_SLUG, PREVIOUS_RELEASE_ID)])
    _write_candidate(tmp_repo)

    run_dir = _validate_manifest_promote(tmp_repo)
    registry_result = registry_update.run(
        str(run_dir), repo_root=tmp_repo, mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
    )

    assert registry_result["dataset_slug"] == DATASET_SLUG
    assert registry_result["allocated_dataset_slug"] == f"{DATASET_SLUG}1"

    registry_after = json.loads((tmp_repo / "registry" / "datasets.json").read_text())
    assert len(registry_after["datasets"]) == 2
    original = next(e for e in registry_after["datasets"] if e["dataset_slug"] == DATASET_SLUG)
    assert original["active_release"] == PREVIOUS_RELEASE_ID
    created = next(e for e in registry_after["datasets"] if e["dataset_slug"] == f"{DATASET_SLUG}1")
    assert created["active_release"] == RELEASE_ID


def test_create_new_dataset_detail_mode_retry_reuses_same_allocated_slug(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry_with_datasets(tmp_repo, [_dataset_entry(DATASET_SLUG, PREVIOUS_RELEASE_ID)])
    _write_candidate(tmp_repo)

    run_dir = _validate_manifest_promote(tmp_repo)

    first = registry_update.run(
        str(run_dir), repo_root=tmp_repo, mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
    )
    second = registry_update.run(
        str(run_dir), repo_root=tmp_repo, mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
    )

    assert first["allocated_dataset_slug"] == f"{DATASET_SLUG}1"
    assert second["allocated_dataset_slug"] == f"{DATASET_SLUG}1"

    registry_after = json.loads((tmp_repo / "registry" / "datasets.json").read_text())
    matching = [e for e in registry_after["datasets"] if e["dataset_slug"] == f"{DATASET_SLUG}1"]
    assert len(matching) == 1


def test_create_new_dataset_detail_mode_reuses_slug_absent_from_current_registry(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    # Simulates a Dataset Detail whose slug was previously used and later
    # removed from the registry: DATASET_SLUG itself is absent from the
    # current fixture even though a numbered sibling remains, so history
    # must not reserve it -- it must allocate like a never-used slug.
    _write_registry_with_datasets(
        tmp_repo, [_dataset_entry(f"{DATASET_SLUG}2", "release-20260610-001")]
    )
    _write_candidate(tmp_repo)

    run_dir = _validate_manifest_promote(tmp_repo)
    registry_result = registry_update.run(
        str(run_dir), repo_root=tmp_repo, mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
    )

    assert registry_result["allocated_dataset_slug"] == DATASET_SLUG

    registry_after = json.loads((tmp_repo / "registry" / "datasets.json").read_text())
    slugs = {e["dataset_slug"] for e in registry_after["datasets"]}
    assert slugs == {DATASET_SLUG, f"{DATASET_SLUG}2"}


# ---------------------------------------------------------------------------
# Project Spec S0046: promotion-result.json registry_update_record
# synchronization, through the real validate -> manifest -> promote ->
# registry_update -> finalize pipeline.
# ---------------------------------------------------------------------------


def _read_promotion_result(run_dir: Path) -> dict:
    return json.loads((run_dir / "promotion-result.json").read_text(encoding="utf-8"))


def test_finalize_syncs_registry_update_record_matching_fixture_registry_after_update_existing(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    run_dir = _validate_manifest_promote(tmp_repo)

    before = _read_promotion_result(run_dir)
    assert before["registry_update_record"]["update_applied"] is False

    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
    registry_action = registry_update.derive_registry_action(registry_result)
    assert registry_action == "updated"

    promote.finalize_promotion_result_after_registry_update(
        str(run_dir), registry_result, registry_action, repo_root=tmp_repo
    )

    after = _read_promotion_result(run_dir)
    record = after["registry_update_record"]

    registry_after = json.loads((tmp_repo / "registry" / "datasets.json").read_text())
    live_entry = next(e for e in registry_after["datasets"] if e["dataset_slug"] == DATASET_SLUG)

    assert record["update_applied"] is True
    assert record["new_active_release_id"] == RELEASE_ID == live_entry["active_release"]
    assert record["previous_active_release_id"] == PREVIOUS_RELEASE_ID
    assert record["registry_action"] == "updated"
    assert "public_dataset_slug" not in record
    assert "promoted_at" in record


def test_finalize_is_idempotent_and_never_rewrites_previous_active_release_id_to_current(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    run_dir = _validate_manifest_promote(tmp_repo)

    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
    registry_action = registry_update.derive_registry_action(registry_result)
    promote.finalize_promotion_result_after_registry_update(
        str(run_dir), registry_result, registry_action, repo_root=tmp_repo
    )
    first = _read_promotion_result(run_dir)

    # A second registry_update.run() call for the same already-promoted
    # release reports previous_active_release_id == release_id (the
    # registry's current, already-updated state) -- feeding that raw value
    # into a second finalize() call must never overwrite the correct,
    # already-recorded previous_active_release_id from the real prior
    # release with this self-referential, contradictory value.
    second_registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
    assert second_registry_result["previous_active_release_id"] == RELEASE_ID
    second_registry_action = registry_update.derive_registry_action(second_registry_result)
    assert second_registry_action == "reused"

    promote.finalize_promotion_result_after_registry_update(
        str(run_dir), second_registry_result, second_registry_action, repo_root=tmp_repo
    )
    second = _read_promotion_result(run_dir)

    assert second == first
    assert second["registry_update_record"]["previous_active_release_id"] == PREVIOUS_RELEASE_ID


def test_finalize_records_public_dataset_slug_and_created_action_when_slug_is_allocated(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry_with_datasets(tmp_repo, [_dataset_entry(DATASET_SLUG, PREVIOUS_RELEASE_ID)])
    _write_candidate(tmp_repo)

    run_dir = _validate_manifest_promote(tmp_repo)
    registry_result = registry_update.run(
        str(run_dir), repo_root=tmp_repo, mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
    )
    registry_action = registry_update.derive_registry_action(registry_result)
    assert registry_action == "created"
    assert registry_result["allocated_dataset_slug"] == f"{DATASET_SLUG}1"

    promote.finalize_promotion_result_after_registry_update(
        str(run_dir), registry_result, registry_action, repo_root=tmp_repo
    )

    record = _read_promotion_result(run_dir)["registry_update_record"]
    assert record["registry_action"] == "created"
    assert record["public_dataset_slug"] == f"{DATASET_SLUG}1"
    assert record["previous_active_release_id"] is None
    assert record["new_active_release_id"] == RELEASE_ID


def test_finalize_leaves_registry_update_record_unsynchronized_when_registry_update_fails(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    run_dir = _validate_manifest_promote(tmp_repo)

    # Corrupt the registry after promote.run() so registry_update.run()
    # raises -- exactly the "release published, registry update failed"
    # window this spec requires to never read as a misleading success.
    (tmp_repo / "registry" / "datasets.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(RuntimeError):
        registry_update.run(str(run_dir), repo_root=tmp_repo)

    result = _read_promotion_result(run_dir)
    assert result["promotion_outcome"] == "promoted"
    assert result["registry_update_record"]["update_applied"] is False
    assert result["registry_update_record"]["new_active_release_id"] is None
    assert "registry_action" not in result["registry_update_record"]


def test_finalize_rejects_a_rejected_promotion_result(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="metrics")
    validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    (run_dir / "promotion-result.json").write_text(
        json.dumps({"promotion_outcome": "rejected"}), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="promotion_outcome is not 'promoted'"):
        promote.finalize_promotion_result_after_registry_update(
            str(run_dir),
            {"release_id": RELEASE_ID, "dataset_slug": DATASET_SLUG},
            "updated",
            repo_root=tmp_repo,
        )


def test_synchronized_promotion_result_validates_against_schema_for_both_release_id_formats(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (REPO_ROOT / "publisher" / "promotion" / "promotion-result.schema.json").read_text()
    )

    for release_id in (RELEASE_ID, "release-20260710t101438z"):
        tmp_repo = tmp_path / f"repo-{release_id}"
        _copy_publisher_contracts(tmp_repo)
        _write_registry(tmp_repo)
        candidate_dir = _candidate_dir(tmp_repo, release_id=release_id)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        for role in REQUIRED_ROLES:
            artifact_path = candidate_dir / _role_path(role)
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            if role == "model_artifact":
                artifact_path.write_bytes(MODEL_ARTIFACT_BYTES)
                continue
            payload = _artifact_payload(role)
            if role not in {"public_contract", "visualizations"}:
                # The real public-contract and analytical-visualizations
                # schemas are additionalProperties: false and cannot carry
                # this override key (Project Specs S0101, S0128).
                payload["release_identity"] = {"release_id": release_id}
            artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        candidate = {
            "schema_version": "release-candidate.v1",
            "candidate_kind": "release_candidate",
            "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Example Dataset"},
            "release_identity": {
                "release_id": release_id,
                "release_version": RELEASE_VERSION,
                "created_at": "2026-06-19T00:00:00Z",
            },
            "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-06-19T00:00:00Z"},
            "artifact_roles": {
                role: {"role": role, "path": _role_path(role), "required": True} for role in REQUIRED_ROLES
            },
            "candidate_metadata": {
                "assembled_by": "pytest",
                "assembled_at": "2026-06-19T00:00:00Z",
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

        validate.run(str(candidate_dir), repo_root=tmp_repo)
        run_dir = _latest_run_dir(tmp_repo)
        manifest.run(str(run_dir), repo_root=tmp_repo)
        promote.run(str(run_dir), repo_root=tmp_repo)
        registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
        registry_action = registry_update.derive_registry_action(registry_result)
        result = promote.finalize_promotion_result_after_registry_update(
            str(run_dir), registry_result, registry_action, repo_root=tmp_repo
        )

        jsonschema.validate(result, schema)
        assert result["registry_update_record"]["new_active_release_id"] == release_id


def test_evidence_requires_schema_validation_before_write(tmp_path, monkeypatch):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)
    promote.run(str(run_dir), repo_root=tmp_repo)
    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)

    real_import = builtins.__import__

    def import_without_jsonschema(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("jsonschema unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_jsonschema)

    with pytest.raises(RuntimeError, match="jsonschema is required"):
        evidence.run(str(run_dir), registry_result, repo_root=tmp_repo)

    assert not (run_dir / "publication-evidence.json").exists()


# --- M26-04: isolated manifest generation and verification tests ---


def test_manifest_generates_all_required_roles_with_hashes(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    result = manifest.run(str(run_dir), repo_root=tmp_repo)

    assert result["schema_version"] == "release-manifest.v1"
    assert result["manifest_kind"] == "release_manifest"
    assert result["dataset_identity"]["dataset_slug"] == DATASET_SLUG
    assert result["release_identity"]["release_id"] == RELEASE_ID

    artifacts = result["artifacts"]
    assert len(artifacts) == len(REQUIRED_ROLES)
    assert {a["role"] for a in artifacts} == set(REQUIRED_ROLES)
    for entry in artifacts:
        assert entry["hash_algorithm"] == "sha256"
        assert len(entry["hash_value"]) == 64
        assert all(c in "0123456789abcdef" for c in entry["hash_value"])

    assert result["safety_boundaries"]["registry_updated"] is False
    assert result["safety_boundaries"]["release_promoted"] is False
    assert not (tmp_repo / "registry" / "datasets.json.previous").exists()


def test_manifest_halted_by_rejected_validation_outcome(tmp_path):
    # Project Spec S0180: manifest generation now gates on validation_outcome
    # (structural acceptance), not promotion_gate.promotion_allowed --
    # renamed from test_manifest_halted_by_failed_promotion_gate to match.
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="metrics")
    validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    with pytest.raises(RuntimeError, match="validation_outcome"):
        manifest.run(str(run_dir), repo_root=tmp_repo)

    assert not (run_dir / "manifest.json").exists()


def test_manifest_halted_when_artifact_unreadable_during_hash(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    (_candidate_dir(tmp_repo) / _role_path("metrics")).unlink()

    with pytest.raises(RuntimeError, match="Manifest generation failed"):
        manifest.run(str(run_dir), repo_root=tmp_repo)

    assert not (run_dir / "manifest.json").exists()


def test_manifest_verify_detects_hash_mismatch(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)

    manifest_path = run_dir / "manifest.json"
    candidate_dir = _candidate_dir(tmp_repo)

    valid, errors = manifest.verify(manifest_path, candidate_dir)
    assert valid is True
    assert errors == []

    (candidate_dir / _role_path("metrics")).write_text(
        json.dumps({"tampered": True}), encoding="utf-8"
    )
    valid, errors = manifest.verify(manifest_path, candidate_dir)
    assert valid is False
    assert any(e["code"] == "MANIFEST_HASH_MISMATCH" for e in errors)


# --- S0190: an accepted candidate is directly promotion-eligible regardless
# of provenance ---
#
# publisher/validate.py's promotion_gate is now derived purely from
# structural acceptance -- the S0180/S0189 fail-closed derivation from an
# accepted candidate's own predictive_bundle.model_provenance_origin /
# external_model_evidence.readiness (contracts/inference-bundle.schema.json,
# unmodified) or a governed operational-readiness decision has been
# retired. Every fixture here is synthetic/temporary -- no real Telco model
# or bytes are loaded.


def _external_predictive_bundle_payload(
    *,
    operational_validity: str = "unconfirmed",
    threshold_status: str = "unresolved",
    threshold_value: float | None = None,
    prediction_available: bool = False,
    include_result_semantics: bool = True,
    result_semantics_threshold: float = 0.5,
) -> dict:
    payload = _artifact_payload("predictive_bundle")
    payload["model_provenance_origin"] = "validated_external_fitted_model"
    payload["external_model_evidence"] = {
        "origin": "validated_external_fitted_model",
        "readiness": {
            "operational_validity": operational_validity,
            "operational_threshold": {"status": threshold_status, "value": threshold_value},
            "operational_prediction_available": prediction_available,
        },
        # Project Spec S0191: the governed external threshold evidence a
        # compatible predictive bundle's result_semantics.decision.threshold
        # must match.
        "educational_threshold": {"value": result_semantics_threshold},
    }
    if include_result_semantics:
        # Project Spec S0191: minimal compatible binary result_semantics --
        # the publisher only structurally checks problem_type and
        # decision.threshold consistency, never the full inference-bundle
        # schema shape (predictive_bundle is not one of the roles the
        # publisher runs real JSON Schema validation against).
        payload["result_semantics"] = {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "decision": {"threshold": result_semantics_threshold},
        }
    return payload


def _external_metrics_payload() -> dict:
    """A schema-shaped training-metrics.external-fitted-model.v1 artifact
    (Project Spec S0191) carrying one supported public metric on its
    validation_evaluation partition, for a validated_external_fitted_model
    candidate's metrics role."""
    return {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-06-19T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "dataset_slug": DATASET_SLUG,
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "used_for_fitting": True,
            "used_for_model_selection": True,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.81}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "used_for_fitting": False,
            "used_for_model_selection": True,
            "used_for_threshold_selection": True,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.80}],
        },
    }


def test_external_provenance_accepted_candidate_is_directly_promotion_eligible(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "metrics": _external_metrics_payload(),
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "accepted"
    assert result["promotion_gate"] == {
        "promotion_allowed": True,
        "registry_update_allowed": True,
    }
    # Informational only -- the operational-readiness evaluation no longer
    # controls promotion_gate.
    assert result["operational_readiness_evaluation"]["source"] == "bundle_only"


def test_external_provenance_rejected_candidate_keeps_promotion_gate_false(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        missing_role="metrics",
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(
                operational_validity="confirmed",
                threshold_status="resolved",
                threshold_value=0.5,
                prediction_available=True,
            )
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert result["promotion_gate"] == {
        "promotion_allowed": False,
        "registry_update_allowed": False,
    }


def test_manifest_generates_for_accepted_external_candidate(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "metrics": _external_metrics_payload(),
        },
    )
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    result = manifest.run(str(run_dir), repo_root=tmp_repo)

    assert result["schema_version"] == "release-manifest.v1"
    assert (run_dir / "manifest.json").is_file()
    assert result["safety_boundaries"]["registry_updated"] is False
    assert result["safety_boundaries"]["release_promoted"] is False
    # Project Spec S0190: manifest generation never injects a run-owned
    # operational_readiness supplemental artifact.
    assert "operational_readiness" not in {a["role"] for a in result["artifacts"]}


def test_promotion_succeeds_for_accepted_run_with_stale_promotion_gate_false(tmp_path):
    """Project Spec S0190 Section D compatibility: an existing run's
    validation-result.json produced before S0190 may still carry a stale
    promotion_gate.promotion_allowed: false (from the retired
    operational-readiness gate) even though validation_outcome is
    "accepted". Promotion must succeed without editing that file."""
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)
    manifest.run(str(run_dir), repo_root=tmp_repo)

    validation_result_path = run_dir / "validation-result.json"
    validation_result = json.loads(validation_result_path.read_text())
    assert validation_result["validation_outcome"] == "accepted"
    validation_result["promotion_gate"] = {"promotion_allowed": False, "registry_update_allowed": False}
    validation_result_path.write_text(json.dumps(validation_result, indent=2), encoding="utf-8")

    result = promote.run(str(run_dir), repo_root=tmp_repo)

    assert result["promotion_outcome"] == "promoted"


# --- S0193 restored visualizations as mandatory for a validated external
# fitted-model candidate (reversing the Project Spec S0188 visualization-
# optional exception). omit_role="visualizations" simulates the real
# assemble_candidate.py output shape for a candidate structurally missing
# the role from artifact_roles, distinct from a declared-but-missing role.


def test_external_provenance_candidate_without_visualizations_role_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        omit_role="visualizations",
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "metrics": _external_metrics_payload(),
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert any(r["code"] == "missing_visualizations" for r in result["rejection"]["reasons"])
    assert "visualizations" in result["required_artifact_role_results"]
    assert len(result["required_artifact_role_results"]) == 10


def test_internal_candidate_without_visualizations_role_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(tmp_repo, omit_role="visualizations")

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert any(r["code"] == "missing_visualizations" for r in result["rejection"]["reasons"])


def test_external_provenance_candidate_with_present_visualizations_still_validates_it(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "visualizations": {"not": "schema-valid"},
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert any(r["code"] == "visualizations_schema_incompatible" for r in result["rejection"]["reasons"])


# --- S0193: publisher rejects an external candidate whose visualizations
# artifact declares dataset/model provenance conflicting with the
# predictive bundle it is packaged with.


def _external_visualizations_payload(dataset_slug: str, model_family: str = "hist_gradient_boosting") -> dict:
    return {
        "schema_version": "analytical-visualizations.external-fitted-model.v1",
        "artifact_kind": "analytical_visualizations",
        "model_source_mode": "validated_external_fitted_model",
        "created_at": "2026-06-19T00:00:00Z",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "external_materialization_provenance": {
            "model_family": model_family,
            "external_evidence_reference": "artifacts/telco-customer-churn/analytical-visual-evidence.json",
            "external_evidence_sha256": "a" * 64,
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
            "population_kind": "external_prepared_dataset",
            "source": "external_prepared_evaluation_population",
            "target_column": "target",
        },
        "feature_importance_method": {
            "model_family": model_family,
            "source": "external_validated_fitted_model",
            "method": "permutation_importance",
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


def _external_predictive_bundle_payload_with_identity(model_family: str = "hist_gradient_boosting") -> dict:
    payload = _external_predictive_bundle_payload()
    payload["dataset_context"] = {"dataset_slug": DATASET_SLUG}
    payload["result_semantics"]["model_descriptor"] = {"model_family": model_family}
    return payload


def test_external_provenance_visualizations_dataset_mismatch_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload_with_identity(),
            "metrics": _external_metrics_payload(),
            "visualizations": _external_visualizations_payload("a-different-dataset"),
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "visualizations_provenance_mismatch" for r in result["rejection"]["reasons"]
    )


def test_external_provenance_visualizations_model_family_mismatch_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload_with_identity(
                model_family="hist_gradient_boosting"
            ),
            "metrics": _external_metrics_payload(),
            "visualizations": _external_visualizations_payload(
                DATASET_SLUG, model_family="logistic_regression"
            ),
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "visualizations_provenance_mismatch" for r in result["rejection"]["reasons"]
    )


def test_external_provenance_visualizations_matching_provenance_is_accepted(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload_with_identity(),
            "metrics": _external_metrics_payload(),
            "visualizations": _external_visualizations_payload(DATASET_SLUG),
        },
    )

    result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert result["validation_outcome"] == "accepted", result["rejection"]


def test_manifest_for_external_candidate_with_visualizations_contains_ten_artifacts(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_registry(tmp_repo)
    _write_candidate(
        tmp_repo,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "metrics": _external_metrics_payload(),
        },
    )
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    result = manifest.run(str(run_dir), repo_root=tmp_repo)

    assert len(result["artifacts"]) == 10
    assert "visualizations" in {a["role"] for a in result["artifacts"]}
    assert "visualizations" in result["required_hash_coverage"]["required_artifact_roles"]


def test_manifest_for_internal_candidate_still_contains_ten_artifacts_including_visualizations(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    result = manifest.run(str(run_dir), repo_root=tmp_repo)

    assert len(result["artifacts"]) == 10
    assert "visualizations" in {a["role"] for a in result["artifacts"]}


def test_validation_result_and_manifest_schemas_validate_ten_role_shape_for_internal_and_external(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    validation_schema = json.loads(
        (REPO_ROOT / "publisher" / "validation" / "release-candidate-validation.schema.json").read_text()
    )
    manifest_schema = json.loads((REPO_ROOT / "publisher" / "release-manifest.schema.json").read_text())

    def _without_pre_existing_unrelated_drift(validation_result: dict) -> dict:
        # capability_conditional_validation (Project Spec S0168) is a real
        # top-level key validate.py always emits, but it predates and is
        # unrelated to the S0193 10-role shape concern and was never wired
        # into this schema (additionalProperties: false rejects it
        # regardless of role count) -- out of scope here; strip it so this
        # test isolates the role-count shape this schema is responsible for.
        return {k: v for k, v in validation_result.items() if k != "capability_conditional_validation"}

    # Internal (10-role) shape.
    tmp_repo_internal = tmp_path / "internal"
    _copy_publisher_contracts(tmp_repo_internal)
    _write_registry(tmp_repo_internal)
    _write_candidate(tmp_repo_internal)
    internal_validation = validate.run(str(_candidate_dir(tmp_repo_internal)), repo_root=tmp_repo_internal)
    jsonschema.validate(_without_pre_existing_unrelated_drift(internal_validation), validation_schema)
    internal_run_dir = _latest_run_dir(tmp_repo_internal)
    internal_manifest = manifest.run(str(internal_run_dir), repo_root=tmp_repo_internal)
    jsonschema.validate(internal_manifest, manifest_schema)

    # External (10-role) shape -- visualizations is mandatory here too
    # (Project Spec S0193).
    tmp_repo_external = tmp_path / "external"
    _copy_publisher_contracts(tmp_repo_external)
    _write_registry(tmp_repo_external)
    _write_candidate(
        tmp_repo_external,
        role_payload_overrides={
            "predictive_bundle": _external_predictive_bundle_payload(),
            "metrics": _external_metrics_payload(),
        },
    )
    external_validation = validate.run(str(_candidate_dir(tmp_repo_external)), repo_root=tmp_repo_external)
    jsonschema.validate(_without_pre_existing_unrelated_drift(external_validation), validation_schema)
    external_run_dir = _latest_run_dir(tmp_repo_external)
    external_manifest = manifest.run(str(external_run_dir), repo_root=tmp_repo_external)
    jsonschema.validate(external_manifest, manifest_schema)


# --- S0180: release-candidate-input external fitted-model provenance
# discrimination (pipeline/assemble_candidate.py) ---
#
# _resolve_training_provenance discriminates internal-vs-external purely
# from the training_parameter_record artifact's own declared schema_version
# -- never a dataset-slug conditional -- and is backward-compatible: any
# value other than the real S0157 external constant (including generic
# fixture placeholders used by other, unrelated tests) falls back to the
# historical M24/training-parameter-record.v1 behavior unchanged.

EXTERNAL_PROVENANCE_DATASET_SLUG = "external-fitted-example"


def _write_training_provenance_fixture(
    tmp_repo: Path,
    *,
    record_schema_version: str,
    metrics_schema_version: str,
) -> dict:
    record_path = tmp_repo / "pipeline" / "external-evidence" / "training-parameter-record.json"
    metrics_path = tmp_repo / "pipeline" / "external-evidence" / "training-metrics.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"schema_version": record_schema_version}), encoding="utf-8"
    )
    metrics_path.write_text(
        json.dumps({"schema_version": metrics_schema_version}), encoding="utf-8"
    )
    return {
        "training_parameter_record": str(record_path.relative_to(tmp_repo)),
        "training_metrics": str(metrics_path.relative_to(tmp_repo)),
    }


def test_resolve_training_provenance_defaults_to_internal_for_any_non_external_value(tmp_path):
    tmp_repo = tmp_path / "repo"
    references = _write_training_provenance_fixture(
        tmp_repo,
        # A generic placeholder value, matching what several pre-existing
        # unrelated test fixtures declare for this role (never the real
        # training-parameter-record.v1 constant either) -- must still
        # resolve to the historical internal defaults, not raise.
        record_schema_version="training_parameter_record.v1",
        metrics_schema_version="training_metrics.v1",
    )

    source_stage, is_external, record_override, metrics_override = (
        assemble_candidate._resolve_training_provenance(references, tmp_repo)
    )

    assert source_stage == "M24"
    assert is_external is False
    assert record_override is None
    assert metrics_override is None


def test_resolve_training_provenance_detects_real_external_profile(tmp_path):
    tmp_repo = tmp_path / "repo"
    references = _write_training_provenance_fixture(
        tmp_repo,
        record_schema_version="training-parameter-record.external-fitted-model.v1",
        metrics_schema_version="training-metrics.external-fitted-model.v1",
    )

    source_stage, is_external, record_override, metrics_override = (
        assemble_candidate._resolve_training_provenance(references, tmp_repo)
    )

    assert source_stage == "manual_governed_input"
    assert is_external is True
    assert record_override == "training-parameter-record.external-fitted-model.v1"
    assert metrics_override == "training-metrics.external-fitted-model.v1"


def test_resolve_training_provenance_rejects_disagreeing_external_metrics_profile(tmp_path):
    tmp_repo = tmp_path / "repo"
    references = _write_training_provenance_fixture(
        tmp_repo,
        record_schema_version="training-parameter-record.external-fitted-model.v1",
        # Metrics still declares the internal profile -- inconsistent with
        # the record's external declaration.
        metrics_schema_version="training-metrics.v1",
    )

    with pytest.raises(ValueError, match="training_metrics contract_version"):
        assemble_candidate._resolve_training_provenance(references, tmp_repo)


# --- S0180: generalized governed inference-bundle materialization
# (pipeline/generate_inference_bundle.py) ---

EXTERNAL_BUNDLE_MODEL_ARTIFACT_BYTES = b"pytest-external-fixture-model-bytes-not-a-real-model"
EXTERNAL_BUNDLE_MODEL_ARTIFACT_SHA256 = hashlib.sha256(EXTERNAL_BUNDLE_MODEL_ARTIFACT_BYTES).hexdigest()
EXTERNAL_BUNDLE_MODEL_STATE_FINGERPRINT = hashlib.sha256(
    b"pytest-external-model-state-fingerprint"
).hexdigest()


def _write_external_bundle_fixtures(tmp_repo: Path) -> dict:
    for relative in (
        "pipeline/training-parameter-record.schema.json",
        "pipeline/training-metrics.schema.json",
        "pipeline/model-selection-evidence.schema.json",
    ):
        src = REPO_ROOT / relative
        dst = tmp_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    training_record_path = tmp_repo / "pipeline" / "external-evidence" / "training-parameter-record.json"
    training_metrics_path = tmp_repo / "pipeline" / "external-evidence" / "training-metrics.json"
    model_selection_path = tmp_repo / "pipeline" / "external-evidence" / "model-selection-evidence.json"
    model_artifact_path = tmp_repo / "pipeline" / "external-evidence" / "model.bin"
    execution_contract_path = tmp_repo / "contracts" / EXTERNAL_PROVENANCE_DATASET_SLUG / "execution-contract.json"
    runtime_contract_path = tmp_repo / "contracts" / EXTERNAL_PROVENANCE_DATASET_SLUG / "runtime-contract.json"
    public_contract_path = tmp_repo / "contracts" / EXTERNAL_PROVENANCE_DATASET_SLUG / "public-contract.json"
    prepared_dataset_path = tmp_repo / "pipeline" / "prepared" / EXTERNAL_PROVENANCE_DATASET_SLUG / "prepared-dataset.json"

    for path in (
        training_record_path,
        training_metrics_path,
        model_selection_path,
        model_artifact_path,
        execution_contract_path,
        runtime_contract_path,
        public_contract_path,
        prepared_dataset_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    training_record_path.write_text(json.dumps({
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "record_kind": "training_parameter_record",
        "origin": "validated_external_fitted_model",
        "producer": "pytest-external-producer",
        "handoff_lineage_reference": "external-handoff/pytest-lineage-001",
        "dataset_identity": {"dataset_slug": EXTERNAL_PROVENANCE_DATASET_SLUG},
        "selected_model_id": "candidate-001",
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
        "hyperparameters": {"max_depth": 3},
        "feature_order": ["feature_a"],
        "preprocessing_evidence_reference": "external-handoff/pytest-preprocessing-evidence",
        "serializer_metadata_reference": "external-handoff/pytest-serializer-metadata",
        "model_artifact_reference": {
            "path": "pipeline/external-evidence/model.bin",
            "sha256": EXTERNAL_BUNDLE_MODEL_ARTIFACT_SHA256,
        },
        "model_state_fingerprint": EXTERNAL_BUNDLE_MODEL_STATE_FINGERPRINT,
        "atlas_fit_confirmation": {
            "atlas_fit": False,
            "atlas_tuned": False,
            "atlas_recalibrated": False,
            "atlas_altered": False,
        },
        "raw_partition_confirmation": {"raw_partitions_embedded": False},
    }), encoding="utf-8")

    training_metrics_path.write_text(json.dumps({
        "schema_version": "training-metrics.external-fitted-model.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-10T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "dataset_slug": EXTERNAL_PROVENANCE_DATASET_SLUG,
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "used_for_fitting": True,
            "used_for_model_selection": True,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.9}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "used_for_fitting": False,
            "used_for_model_selection": True,
            "used_for_threshold_selection": True,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.88}],
        },
    }), encoding="utf-8")

    model_selection_path.write_text(json.dumps({
        "schema_version": "model-selection-evidence.external-fitted-model.v1",
        "artifact_kind": "model_selection_evidence",
        "created_at": "2026-08-10T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "producer": "pytest-external-producer",
            "handoff_lineage_reference": "external-handoff/pytest-lineage-001",
        },
        "dataset_identity": {"dataset_slug": EXTERNAL_PROVENANCE_DATASET_SLUG},
        "selection_protocol": {"protocol_id": "cross_validation_with_practical_tie_break"},
        "selection_policy": {"primary_metric": "roc_auc", "ranking_direction": "higher_is_better"},
        "cross_validation_summary": {
            "partition_role": "train",
            "metric_summaries": [{"name": "roc_auc", "mean": 0.9, "standard_deviation": 0.01}],
        },
        "validation_metrics": {
            "partition_role": "validation",
            "metrics": [{"name": "roc_auc", "value": 0.88}],
        },
        "practical_tie": {"tolerance": 0.01, "tie_detected": False, "tie_break_criteria": []},
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "model_family": "hist_gradient_boosting",
                "estimator_identity": {
                    "library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"
                },
            }
        ],
        "selected_candidate": {"candidate_id": "candidate-001"},
        "selection_rationale": "Highest validation roc_auc.",
        "sealed_test_confirmation": {
            "test_partition_role": "test",
            "used_for_model_selection": False,
            "sealed_before_selection": True,
        },
        "path_references": {
            "model_selection_evidence_reference": "external-handoff/pytest-model-selection-evidence",
        },
        "hashes": {"algorithm": "sha256", "model_state_fingerprint": EXTERNAL_BUNDLE_MODEL_STATE_FINGERPRINT},
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }), encoding="utf-8")

    model_artifact_path.write_bytes(EXTERNAL_BUNDLE_MODEL_ARTIFACT_BYTES)

    execution_contract_path.write_text(json.dumps({
        "contract_version": "execution_contract.v1",
        "dataset_id": EXTERNAL_PROVENANCE_DATASET_SLUG,
        "model_source_mode": "validated_external_fitted_model",
        "feature_columns": ["feature_a"],
        "missing_value_policy": {"feature_a": "mean"},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
    }), encoding="utf-8")
    runtime_contract_path.write_text(json.dumps({"contract_version": "runtime_contract.v1"}), encoding="utf-8")
    public_contract_path.write_text(json.dumps({"contract_version": "public_contract.v1"}), encoding="utf-8")
    prepared_dataset_path.write_text(json.dumps({"prepared": True}), encoding="utf-8")

    return {
        "training_parameter_record_path": str(training_record_path.relative_to(tmp_repo)),
        "training_metrics_path": str(training_metrics_path.relative_to(tmp_repo)),
        "model_selection_evidence_path": str(model_selection_path.relative_to(tmp_repo)),
        "model_artifact_path": str(model_artifact_path.relative_to(tmp_repo)),
        "execution_contract_path": str(execution_contract_path.relative_to(tmp_repo)),
        "runtime_contract_path": str(runtime_contract_path.relative_to(tmp_repo)),
        "public_contract_path": str(public_contract_path.relative_to(tmp_repo)),
        "prepared_dataset_path": str(prepared_dataset_path.relative_to(tmp_repo)),
    }


def test_generate_inference_bundle_external_branch_succeeds_with_hist_gradient_boosting(tmp_path):
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()
    paths = _write_external_bundle_fixtures(tmp_repo)

    materialization_result = {
        "status": "materialized",
        "dataset_identity": {"dataset_slug": EXTERNAL_PROVENANCE_DATASET_SLUG},
        "model_source_mode": "validated_external_fitted_model",
        "evidence_references": {
            "training_parameter_record_path": paths["training_parameter_record_path"],
            "training_metrics_path": paths["training_metrics_path"],
            "model_selection_evidence_path": paths["model_selection_evidence_path"],
        },
        "model_artifact_path": paths["model_artifact_path"],
        "educational_threshold": {"value": 0.5, "scenario": "pytest-scenario"},
        "operational_readiness": {
            "educational_final_model_complete": True,
            "educational_inference_demo_ready": True,
            "operational_validity": "unconfirmed",
            "operational_threshold": {"status": "unresolved", "value": None},
            "operational_prediction_available": False,
        },
        "final_test_completion": {"used_for_threshold_selection": False, "evaluation_count": 1},
    }

    result = generate_inference_bundle.materialize_governed_inference_bundle(
        external_fitted_model_materialization_result=materialization_result,
        execution_contract_path=str(tmp_repo / paths["execution_contract_path"]),
        runtime_contract_path=str(tmp_repo / paths["runtime_contract_path"]),
        public_contract_path=str(tmp_repo / paths["public_contract_path"]),
        dataset_context_path=str(tmp_repo / paths["prepared_dataset_path"]),
        prepared_dataset_path=str(tmp_repo / paths["prepared_dataset_path"]),
        output_path=str(tmp_repo / "predictions" / "bundle.json"),
        prediction_type="number",
        release_id="release-20260810-001",
        repo_root=tmp_repo,
        dataset_slug=EXTERNAL_PROVENANCE_DATASET_SLUG,
        # Explicit release-relative refs: the tmp_repo fixture root differs
        # from generate_inference_bundle's own module-relative _repo_root(),
        # which _reference_for_path falls back to when no explicit ref is
        # given (identical requirement for the pre-existing internal path).
        execution_contract_ref=paths["execution_contract_path"],
        runtime_contract_ref=paths["runtime_contract_path"],
        public_contract_ref=paths["public_contract_path"],
        dataset_context_ref=paths["prepared_dataset_path"],
        prepared_dataset_ref=paths["prepared_dataset_path"],
    )

    assert result["status"] == "generated"
    assert result["model_provenance_origin"] == "validated_external_fitted_model"

    bundle_path = tmp_repo / "predictions" / "bundle.json"
    assert bundle_path.is_file()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["model_provenance_origin"] == "validated_external_fitted_model"
    assert bundle["external_model_evidence"]["model_family"] == "hist_gradient_boosting"
    assert bundle["runtime_execution"]["model_family"] == "hist_gradient_boosting"
    assert "training_evidence" not in bundle
    assert bundle["external_model_evidence"]["readiness"]["operational_validity"] == "unconfirmed"
    assert bundle["external_model_evidence"]["readiness"]["operational_threshold"] == {
        "status": "unresolved",
        "value": None,
    }
    assert bundle["external_model_evidence"]["readiness"]["operational_prediction_available"] is False


def test_generate_inference_bundle_requires_exactly_one_materialization_family():
    result = generate_inference_bundle.materialize_governed_inference_bundle(
        execution_contract_path="unused",
        runtime_contract_path="unused",
        public_contract_path="unused",
        dataset_context_path="unused",
        output_path="unused",
        prediction_type="number",
    )
    assert result["status"] == "blocked"
    assert "exactly one of" in result["blocking_reasons"][0]


# --- S0099: manifest role reference safety ---
#
# publisher/manifest.py's own required_hash_coverage.validation_policy has
# always declared unsafe_reference_rejects: true, but generate_manifest()
# never actually enforced it until now.


def test_manifest_rejects_unsafe_role_reference(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    candidate_json_path = _candidate_dir(tmp_repo) / "release-candidate.json"
    candidate = json.loads(candidate_json_path.read_text())
    candidate["artifact_roles"]["contracts"]["path"] = "../../../etc/passwd"
    candidate_json_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Manifest generation failed"):
        manifest.run(str(run_dir), repo_root=tmp_repo)

    assert not (run_dir / "manifest.json").exists()


def test_manifest_rejects_absolute_role_reference(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    candidate_json_path = _candidate_dir(tmp_repo) / "release-candidate.json"
    candidate = json.loads(candidate_json_path.read_text())
    candidate["artifact_roles"]["metrics"]["path"] = "/etc/passwd"
    candidate_json_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Manifest generation failed"):
        manifest.run(str(run_dir), repo_root=tmp_repo)

    assert not (run_dir / "manifest.json").exists()


# --- S0101: public_contract as the eighth required publisher artifact role ---


def test_public_contract_is_manifest_hashed_and_promoted_distinctly_from_contracts(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_dir = _candidate_dir(tmp_repo)

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["required_artifact_role_results"]["public_contract"]["status"] == "present"
    assert validation_result["schema_compatibility"]["public_contract"]["compatible"] is True

    run_dir = _latest_run_dir(tmp_repo)
    manifest_result = manifest.run(str(run_dir), repo_root=tmp_repo)
    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}
    assert "public_contract" in manifest_roles
    assert manifest_roles["public_contract"]["reference"] != manifest_roles["contracts"]["reference"]
    assert "public_contract" in manifest_result["required_hash_coverage"]["required_artifact_roles"]

    promotion_result = promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / RELEASE_ID
    promoted_public_contract = release_dir / manifest_roles["public_contract"]["reference"]
    promoted_runtime_contract = release_dir / manifest_roles["contracts"]["reference"]
    assert promoted_public_contract.is_file()
    assert promoted_runtime_contract.is_file()
    assert promoted_public_contract != promoted_runtime_contract

    valid, errors = manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []


def test_candidate_missing_public_contract_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="public_contract")

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert validation_result["promotion_gate"]["promotion_allowed"] is False
    assert any(
        r["code"] == "missing_public_contract"
        for r in validation_result["rejection"]["reasons"]
    )


# --- S0107: model_artifact as the ninth required publisher artifact role ---


def test_model_artifact_is_manifest_hashed_and_promoted_generically(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_dir = _candidate_dir(tmp_repo)

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["required_artifact_role_results"]["model_artifact"]["status"] == "present"

    run_dir = _latest_run_dir(tmp_repo)
    manifest_result = manifest.run(str(run_dir), repo_root=tmp_repo)
    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}
    assert manifest_roles["model_artifact"]["reference"] == MODEL_ARTIFACT_PATH
    assert manifest_roles["model_artifact"]["hash_value"] == MODEL_ARTIFACT_SHA256
    assert "model_artifact" in manifest_result["required_hash_coverage"]["required_artifact_roles"]

    promotion_result = promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / RELEASE_ID
    promoted_model = release_dir / manifest_roles["model_artifact"]["reference"]
    assert promoted_model.is_file()
    assert promoted_model.read_bytes() == MODEL_ARTIFACT_BYTES
    assert hashlib.sha256(promoted_model.read_bytes()).hexdigest() == MODEL_ARTIFACT_SHA256

    valid, errors = manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []


def test_candidate_missing_model_artifact_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="model_artifact")

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert validation_result["promotion_gate"]["promotion_allowed"] is False
    assert any(
        r["code"] == "missing_model_artifact"
        for r in validation_result["rejection"]["reasons"]
    )


def test_candidate_unsafe_model_artifact_path_is_rejected(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_json_path = _candidate_dir(tmp_repo) / "release-candidate.json"
    candidate = json.loads(candidate_json_path.read_text())
    candidate["artifact_roles"]["model_artifact"]["path"] = "../../../etc/passwd"
    candidate_json_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "unsafe_model_reference"
        for r in validation_result["rejection"]["reasons"]
    )
    assert validation_result["required_artifact_role_results"]["model_artifact"]["status"] == "unsafe"


def test_candidate_model_path_mismatch_with_bundle_declaration_is_rejected(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    bundle_path = _candidate_dir(tmp_repo) / _role_path("predictive_bundle")
    bundle = json.loads(bundle_path.read_text())
    bundle["model_artifact"]["path"] = "models/a-different-model.pkl"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "model_bundle_path_mismatch"
        for r in validation_result["rejection"]["reasons"]
    )
    assert (
        validation_result["required_artifact_role_results"]["model_artifact"]["status"]
        == "contradictory"
    )


def test_candidate_model_hash_mismatch_with_bundle_declaration_is_rejected(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    bundle_path = _candidate_dir(tmp_repo) / _role_path("predictive_bundle")
    bundle = json.loads(bundle_path.read_text())
    bundle["model_artifact"]["sha256"] = "f" * 64
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "model_bundle_hash_mismatch"
        for r in validation_result["rejection"]["reasons"]
    )
    assert (
        validation_result["required_artifact_role_results"]["model_artifact"]["status"]
        == "contradictory"
    )


def test_model_artifact_bytes_are_never_parsed_as_json(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    # MODEL_ARTIFACT_BYTES is not valid JSON; a passing, accepted validation
    # proves the model role is never JSON-parsed or schema-checked.
    with pytest.raises(json.JSONDecodeError):
        json.loads(MODEL_ARTIFACT_BYTES)

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "accepted"
    assert "model_artifact" not in validation_result["schema_compatibility"]


# --- S0128/S0133: visualizations as a required publisher artifact role ---


def test_visualizations_is_manifest_hashed_and_promoted(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_dir = _candidate_dir(tmp_repo)

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["required_artifact_role_results"]["visualizations"]["status"] == "present"
    assert validation_result["schema_compatibility"]["visualizations"]["compatible"] is True

    run_dir = _latest_run_dir(tmp_repo)
    manifest_result = manifest.run(str(run_dir), repo_root=tmp_repo)
    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}
    assert manifest_roles["visualizations"]["reference"] == "visualizations/visualizations.json"
    assert len(manifest_roles["visualizations"]["hash_value"]) == 64
    assert "visualizations" in manifest_result["required_hash_coverage"]["required_artifact_roles"]

    promotion_result = promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / RELEASE_ID
    source_visualizations = candidate_dir / _role_path("visualizations")
    promoted_visualizations = release_dir / manifest_roles["visualizations"]["reference"]
    assert promoted_visualizations.is_file()
    assert promoted_visualizations.read_bytes() == source_visualizations.read_bytes()

    valid, errors = manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []


def test_candidate_missing_visualizations_is_rejected(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="visualizations")

    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert validation_result["promotion_gate"]["promotion_allowed"] is False
    assert any(
        r["code"] == "missing_visualizations"
        for r in validation_result["rejection"]["reasons"]
    )


def test_candidate_unsafe_visualizations_path_is_rejected(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    candidate_json_path = _candidate_dir(tmp_repo) / "release-candidate.json"
    candidate = json.loads(candidate_json_path.read_text())
    candidate["artifact_roles"]["visualizations"]["path"] = "../../../etc/passwd"
    candidate_json_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "unsafe_visualizations_reference"
        for r in validation_result["rejection"]["reasons"]
    )
    assert validation_result["required_artifact_role_results"]["visualizations"]["status"] == "unsafe"


def test_candidate_visualizations_schema_incompatible_is_rejected(tmp_path):
    tmp_repo = _prepare_tmp_repo(tmp_path)
    visualizations_path = _candidate_dir(tmp_repo) / _role_path("visualizations")
    visualizations_path.write_text(json.dumps({"not": "schema-valid"}), encoding="utf-8")

    validation_result = validate.run(str(_candidate_dir(tmp_repo)), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "rejected"
    assert any(
        r["code"] == "visualizations_schema_incompatible"
        for r in validation_result["rejection"]["reasons"]
    )
    assert validation_result["schema_compatibility"]["visualizations"]["compatible"] is False


# --- S0034: Telco publisher-validation run materialization ---

TELCO_DATASET_SLUG = "telco-customer-churn"
TELCO_RELEASE_ID = "release-20260701-001"


def _write_telco_release_candidate(tmp_repo: Path, missing_role: str | None = None) -> Path:
    candidate_dir = tmp_repo / "releases" / "candidates" / TELCO_DATASET_SLUG / TELCO_RELEASE_ID
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        if role == missing_role:
            continue

        if role == "public_contract":
            # A real contracts/public-contract.schema.json instance
            # (additionalProperties: false) -- Project Spec S0101.
            payload = {
                "schema_version": "1.0.0",
                "features": [
                    {
                        "name": "tenure",
                        "label": "Tenure",
                        "input_type": "number",
                        "optional": False,
                        "display_order": 1,
                    }
                ],
            }
        elif role == "model_artifact":
            payload = None
        elif role == "visualizations":
            # A real pipeline/analytical-visualizations.schema.json instance
            # (additionalProperties: false) -- Project Spec S0128.
            payload = _visualizations_payload(
                TELCO_DATASET_SLUG, "2026-07-01T00:00:00Z", "train-20260701T000000Z"
            )
        else:
            payload = {
                "role": role,
                "dataset_identity": {"dataset_slug": TELCO_DATASET_SLUG},
                "release_identity": {"release_id": TELCO_RELEASE_ID},
                "availability_status": "real_dataflow_artifact",
                "placeholder_policy": {
                    "fixtures_allowed": False,
                    "placeholders_allowed": False,
                    "missing_required_behavior": "reject",
                },
            }
            if role in {"metrics", "model_card", "predictive_bundle"}:
                payload["model_id"] = "telco-model-001"
            if role == "predictive_bundle":
                payload["runtime_contract_ref"] = "artifacts/contracts.json"
                payload["model_artifact"] = {
                    "path": MODEL_ARTIFACT_PATH,
                    "sha256": MODEL_ARTIFACT_SHA256,
                }
            if role == "public_context":
                payload["public_projection"] = {"safe_for_public": True}

        artifact_path = candidate_dir / role_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_artifact":
            artifact_path.write_bytes(MODEL_ARTIFACT_BYTES)
        else:
            artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {
            "dataset_slug": TELCO_DATASET_SLUG,
            "dataset_title": "Telco Customer Churn",
        },
        "release_identity": {
            "release_id": TELCO_RELEASE_ID,
            "release_version": "1.0.0-rc.1",
            "created_at": "2026-07-01T00:00:00Z",
        },
        "source_run": {
            "run_id": "train-20260701T000000Z",
            "producer": "pytest",
            "created_at": "2026-07-01T00:00:00Z",
        },
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-07-01T00:00:00Z",
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
    (candidate_dir / "release-candidate.json").write_text(
        json.dumps(candidate, indent=2),
        encoding="utf-8",
    )
    return candidate_dir


def test_materialize_telco_validation_run_accepted_candidate_writes_manifest(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_telco_release_candidate(tmp_repo)

    result = validate.materialize_telco_validation_run(
        candidate_dir=str(candidate_dir.relative_to(tmp_repo)),
        repo_root=tmp_repo,
    )

    assert result["materialization_status"] == "materialized"
    assert result["validation_outcome"] == "accepted"
    assert result["dataset_slug"] == TELCO_DATASET_SLUG
    assert result["release_id"] == TELCO_RELEASE_ID
    assert result["manifest_generated"] is True
    assert result["manifest_path"] is not None

    run_dir = tmp_repo / result["run_dir"]
    assert run_dir.name.startswith("validate-")
    assert (run_dir / "validation-result.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert not (tmp_repo / "registry").exists()
    assert (candidate_dir / "release-candidate.json").is_file()


def test_materialize_telco_validation_run_rejected_candidate_skips_manifest(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_telco_release_candidate(tmp_repo, missing_role="metrics")

    result = validate.materialize_telco_validation_run(
        candidate_dir=f"releases/candidates/{TELCO_DATASET_SLUG}/{TELCO_RELEASE_ID}",
        repo_root=tmp_repo,
    )

    assert result["materialization_status"] == "materialized"
    assert result["validation_outcome"] == "rejected"
    assert result["manifest_generated"] is False
    assert result["manifest_path"] is None

    run_dir = tmp_repo / result["run_dir"]
    assert (run_dir / "validation-result.json").is_file()
    assert not (run_dir / "manifest.json").exists()


def test_materialize_telco_validation_run_blocks_non_telco_candidate(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    _write_candidate(tmp_repo)  # example-dataset, not telco-customer-churn

    result = validate.materialize_telco_validation_run(
        candidate_dir=f"releases/candidates/{DATASET_SLUG}/{RELEASE_ID}",
        repo_root=tmp_repo,
    )

    assert result["materialization_status"] == "blocked"
    assert result["reason_code"] == "non_telco_candidate_rejected"
    runs_dir = tmp_repo / "publisher" / "runs"
    assert not runs_dir.exists() or not any(runs_dir.iterdir())


def test_materialize_telco_validation_run_from_accepted_assembly_result(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_telco_release_candidate(tmp_repo)

    assembly_result = {
        "status": "accepted",
        "dataset_slug": TELCO_DATASET_SLUG,
        "release_id": TELCO_RELEASE_ID,
        "candidate_dir": str(candidate_dir),
    }

    result = validate.materialize_telco_validation_run(assembly_result, repo_root=tmp_repo)

    assert result["materialization_status"] == "materialized"
    assert result["validation_outcome"] == "accepted"
    assert result["manifest_generated"] is True


def test_materialize_telco_validation_run_blocks_rejected_assembly_result(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)

    assembly_result = {
        "status": "rejected",
        "reason": "release-candidate-input JSON failed required assembly checks",
        "rejection_phase": "candidate_input_parse",
    }

    result = validate.materialize_telco_validation_run(assembly_result, repo_root=tmp_repo)

    assert result["materialization_status"] == "blocked"
    assert result["reason_code"] == "release_candidate_assembly_not_accepted"
    assert not (tmp_repo / "publisher" / "runs").exists()


def test_materialize_telco_validation_run_rejects_absolute_candidate_dir(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)

    result = validate.materialize_telco_validation_run(
        candidate_dir="/etc/passwd",
        repo_root=tmp_repo,
    )

    assert result["materialization_status"] == "blocked"
    assert result["reason_code"] == "absolute_path_rejected"
    assert not (tmp_repo / "publisher" / "runs").exists()


def test_materialize_telco_validation_run_rejects_both_references_given(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_telco_release_candidate(tmp_repo)

    result = validate.materialize_telco_validation_run(
        {"status": "accepted", "dataset_slug": TELCO_DATASET_SLUG, "candidate_dir": str(candidate_dir)},
        candidate_dir=str(candidate_dir.relative_to(tmp_repo)),
        repo_root=tmp_repo,
    )

    assert result["materialization_status"] == "blocked"
    assert result["reason_code"] == "ambiguous_candidate_reference"
