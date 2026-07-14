import builtins
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from publisher import evidence, manifest, promote, validate  # noqa: E402
from registry import update as registry_update  # noqa: E402


DATASET_SLUG = "example-dataset"
RELEASE_ID = "release-20260619-001"
PREVIOUS_RELEASE_ID = "release-20260618-001"
RELEASE_VERSION = "2026.06.19"

REQUIRED_ROLES = (
    "contracts",
    "predictive_bundle",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)


def _copy_publisher_contracts(tmp_repo: Path) -> None:
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/evidence/publication-validation-evidence.schema.json",
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
    return f"artifacts/{role}.json"


def _artifact_payload(role: str) -> dict:
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
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
    return payload


def _write_candidate(tmp_repo: Path, missing_role: str | None = None) -> Path:
    candidate_dir = _candidate_dir(tmp_repo)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
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
        artifact_path.write_text(
            json.dumps(_artifact_payload(role), indent=2),
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
            payload = _artifact_payload(role)
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


def test_manifest_halted_by_failed_promotion_gate(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_publisher_contracts(tmp_repo)
    candidate_dir = _write_candidate(tmp_repo, missing_role="metrics")
    validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dir = _latest_run_dir(tmp_repo)

    with pytest.raises(RuntimeError, match="promotion_gate.promotion_allowed"):
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


# --- S0099: manifest role reference safety ---
#
# publisher/manifest.py's own required_hash_coverage.validation_policy has
# always declared unsafe_reference_rejects: true, but generate_manifest()
# never actually enforced it until now. A distinct "public_contract" manifest
# role (matching api/public_contract_loader.py's already-existing
# _PUBLIC_CONTRACT_ROLE expectation) is a real, disclosed gap this spec
# cannot close here: publisher/release-manifest.schema.json's artifact_role /
# required_artifact_role enums and required_artifact_role_list's fixed
# minItems==maxItems==7 do not include "public_contract", and that schema
# file is outside this implementation's allowed_edit_paths -- adding the role
# to _REQUIRED_ROLES without a schema change would make _validate_manifest_schema
# reject every generated manifest, which is not an acceptable way to "add" the
# role. See pipeline/assemble_candidate.py's own release-candidate.json
# artifact_roles.public_contract entry (tests/test_m22_prepare_candidate.py)
# for the part of this acceptance criterion that could be delivered.


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
        if role == "public_context":
            payload["public_projection"] = {"safe_for_public": True}

        artifact_path = candidate_dir / role_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
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
