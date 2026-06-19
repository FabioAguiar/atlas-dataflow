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
    suffix = "json" if role in {
        "contracts",
        "metrics",
        "model_card",
        "manifest_input",
        "candidate_metadata",
    } else "txt"
    return f"artifacts/{role}.{suffix}"


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
        if role_path.endswith(".json"):
            artifact_path.write_text(
                json.dumps({"role": role, "fixture": True}),
                encoding="utf-8",
            )
        else:
            artifact_path.write_text(f"{role} fixture\n", encoding="utf-8")

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
