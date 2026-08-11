"""
Admin run listing tests for M33-02 and M33-05 validation evidence.

Exercises api/admin_runs.py's safe run-summary derivation and api/main.py's
GET /admin/runs access-control boundary. Tests use direct function/module
calls (no httpx/TestClient dependency, matching tests/api/test_public_endpoints.py)
and configure ADMIN_RUNS_ROOT/ATLAS_ADMIN_ENABLED exclusively
through monkeypatched module attributes or temporary os.environ entries -- never
through a .env file.

Run from the repository root:
    python -m pytest tests/api/test_admin_run_listing.py -v
or directly:
    python tests/api/test_admin_run_listing.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import admin_runs  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry import update as registry_update  # noqa: E402
from registry.resolve import resolve_dataset  # noqa: E402
from registry.validate import validate_registry  # noqa: E402


def _make_request(headers: dict[str, str]) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": "GET", "path": "/admin/runs", "headers": encoded_headers}
    return Request(scope)


def _write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content), encoding="utf-8")


_VALID_MANIFEST = {
    "schema_version": "release-manifest.v1",
    "dataset_identity": {"dataset_slug": "example-dataset", "dataset_title": "Example Dataset"},
    "release_identity": {
        "release_id": "release-20260701-001",
        "release_version": "1.0.0-rc.1",
        "created_at": "2026-07-01T00:00:00Z",
    },
}

_ACCEPTED_VALIDATION_RESULT = {
    "schema_version": "release-candidate-validation.v1",
    "validation_outcome": "accepted",
    "rejection": {"rejected": False, "reasons": []},
}

_REJECTED_VALIDATION_RESULT = {
    "schema_version": "release-candidate-validation.v1",
    "validation_outcome": "rejected",
    "rejection": {
        "rejected": True,
        "reasons": [{"code": "missing_role", "field": None, "message": "metrics artifact missing"}],
    },
}

_SAFE_RUN_SUMMARY_KEYS = {
    "schema_version",
    "run_id",
    "status",
    "dataset_candidate",
    "created_at",
    "trace_reference",
    "validation_summary",
    "unavailable_reason",
    "invalid_reason",
}

_PRIVATE_MARKERS = (
    "/private/generated-runs",
    "/tmp/",
    "C:\\",
    "secret",
    "token",
    "raw_log",
    "raw_runtime",
    "database.sqlite",
)


def _write_run_dir(root: Path, run_id: str, manifest: dict | None, validation_result: dict | None) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    if manifest is not None:
        _write_json(run_dir / "manifest.json", manifest)
    if validation_result is not None:
        _write_json(run_dir / "validation-result.json", validation_result)
    return run_dir


def _assert_no_private_markers(value: object) -> None:
    serialized = json.dumps(value, sort_keys=True)
    for marker in _PRIVATE_MARKERS:
        assert marker not in serialized


def _write_registry(repo_root: Path, datasets: list) -> None:
    registry_dir = repo_root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        registry_dir / "datasets.json",
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": datasets,
        },
    )
    _write_json(
        registry_dir / "predict-views.json",
        {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []},
    )


_PROMOTED_PROMOTION_RESULT = {
    "schema_version": "promotion-result.v1",
    "result_kind": "promotion_result",
    "candidate_identity": {
        "dataset_slug": "example-dataset",
        "release_id": "release-20260701-001",
        "release_version": "1.0.0-rc.1",
    },
    "promotion_outcome": "promoted",
    "preconditions_verified": {
        "completeness_validation_outcome": "accepted",
        "manifest_valid": True,
        "all_required_hashes_present": True,
        "candidate_state_was_valid": True,
        "all_preconditions_met": True,
    },
    "registry_update_record": {
        "update_applied": False,
        "new_active_release_id": None,
        "previous_active_release_id": None,
        "previous_release_preserved": True,
    },
    "evidence_safety": {
        "reduced_evidence_only": True,
        "raw_logs_persisted": False,
        "raw_runtime_persisted": False,
        "raw_api_payloads_persisted": False,
        "secrets_persisted": False,
        "sensitive_local_paths_persisted": False,
        "raw_file_contents_persisted": False,
        "raw_artifact_contents_embedded": False,
    },
    "promotion_boundaries": {
        "registry_write_implemented": False,
        "hash_calculation_implemented": False,
        "signing_or_key_management_implemented": False,
        "queue_required": False,
        "worker_required": False,
        "database_required": False,
        "public_endpoint_exposed": False,
        "web_administration_required": False,
        "github_mutation_performed": False,
    },
}


# ---------------------------------------------------------------------------
# list_admin_run_summaries: happy path and boundary states
# ---------------------------------------------------------------------------

def test_happy_path_returns_available_entry_conformant_to_schema():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "validate-20260701T000000Z", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        assert result["runs_root_status"] == "available"
        assert len(result["runs"]) == 1
        entry = result["runs"][0]
        assert entry["schema_version"] == "admin-run-summary.v1"
        assert entry["run_id"] == "validate-20260701T000000Z"
        assert entry["status"] == "available"
        assert entry["dataset_candidate"] == "example-dataset"
        assert entry["created_at"] == "2026-07-01T00:00:00Z"
        assert entry["trace_reference"] is not None
        assert not entry["trace_reference"].startswith("/")
        assert entry["validation_summary"] == {"outcome": "accepted"}
        assert "unavailable_reason" not in entry
        assert "invalid_reason" not in entry


def test_available_entry_exposes_only_safe_projection_fields():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = json.loads(json.dumps(_VALID_MANIFEST))
        manifest["private_path"] = "/private/generated-runs/validate-safe"
        manifest["secret_token"] = "secret-token-value"
        manifest["raw_runtime_payload"] = {"database": "database.sqlite"}
        manifest["raw_logs"] = ["raw_log line"]
        validation_result = json.loads(json.dumps(_REJECTED_VALIDATION_RESULT))
        validation_result["private_diagnostics"] = {
            "raw_path": "/tmp/private/generated-runs/validate-safe",
            "credential_hint": "token",
        }
        _write_run_dir(root, "validate-safe", manifest, validation_result)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert set(entry) <= _SAFE_RUN_SUMMARY_KEYS
        assert entry["schema_version"] == "admin-run-summary.v1"
        assert entry["run_id"] == "validate-safe"
        assert entry["dataset_candidate"] == "example-dataset"
        assert entry["validation_summary"] == {
            "outcome": "rejected",
            "reason": "metrics artifact missing",
        }
        assert entry["trace_reference"] is not None
        assert not entry["trace_reference"].startswith("/")
        _assert_no_private_markers(entry)


def test_rejected_validation_result_carries_reduced_reason():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "validate-rejected", _VALID_MANIFEST, _REJECTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "available"
        assert entry["validation_summary"]["outcome"] == "rejected"
        assert entry["validation_summary"]["reason"] == "metrics artifact missing"


def test_empty_but_existing_runs_root_is_available_with_no_runs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        assert result == {"runs_root_status": "available", "runs": []}


def test_missing_runs_root_is_unavailable_not_empty():
    with tempfile.TemporaryDirectory() as tmp:
        missing_root = Path(tmp) / "does-not-exist"
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: missing_root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        assert result == {"runs_root_status": "unavailable", "runs": []}


def test_run_directory_missing_manifest_is_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "no-manifest", None, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "unavailable"
        assert entry["unavailable_reason"] == "source_run_evidence_missing"
        assert entry["dataset_candidate"] is None
        assert entry["created_at"] is None
        assert entry["trace_reference"] is None
        assert entry["validation_summary"] is None


def test_run_directory_malformed_manifest_json_is_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "malformed"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")
        _write_json(run_dir / "validation-result.json", _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "unavailable"
        assert entry["unavailable_reason"] == "source_run_evidence_missing"


def test_run_directory_incomplete_manifest_is_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        incomplete_manifest = {"schema_version": "release-manifest.v1"}
        _write_run_dir(root, "incomplete", incomplete_manifest, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "invalid"
        assert entry["invalid_reason"] == "source_run_evidence_incomplete"


def test_symlink_escaping_runs_root_is_never_followed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        outside = Path(tmp) / "outside"
        root.mkdir()
        _write_run_dir(outside, "secret-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        escaping_link = root / "escaping-link"
        escaping_link.symlink_to(outside / "secret-run", target_is_directory=True)

        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["run_id"] == "escaping-link"
        assert entry["status"] == "unavailable"
        assert entry["unavailable_reason"] == "source_run_evidence_unreadable"
        assert entry["dataset_candidate"] is None


def test_dataset_candidate_null_when_slug_does_not_match_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad_manifest = json.loads(json.dumps(_VALID_MANIFEST))
        bad_manifest["dataset_identity"]["dataset_slug"] = "Not A Valid Slug!"
        _write_run_dir(root, "bad-slug", bad_manifest, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "available"
        assert entry["dataset_candidate"] is None


def test_run_id_does_not_allow_path_traversal_to_private_details():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "safe-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        nested = root / "nested"
        nested.mkdir()
        _write_run_dir(nested, "private-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        run_ids = [entry["run_id"] for entry in result["runs"]]
        assert "safe-run" in run_ids
        assert "private-run" not in run_ids
        _assert_no_private_markers(result)


# ---------------------------------------------------------------------------
# list_admin_run_summaries: promoted-state reflection (Project Spec S0045)
# ---------------------------------------------------------------------------

def test_run_with_valid_promoted_promotion_result_is_summarized_as_promoted(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_run_dir(root, "promoted-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    _write_json(run_dir / "promotion-result.json", _PROMOTED_PROMOTION_RESULT)
    _write_registry(
        repo_root,
        [
            {
                "dataset_slug": "example-dataset",
                "active_release": "release-20260701-001",
                "public_metadata": {
                    "title": "Example Dataset",
                    "summary": "Published dataset.",
                    "domain": "general",
                    "visibility": "public",
                    "tags": [],
                },
            }
        ],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    entry = result["runs"][0]
    assert entry["status"] == "promoted"
    assert entry["dataset_candidate"] == "example-dataset"
    assert entry["validation_summary"] == {"outcome": "accepted"}
    assert entry["promotion_summary"] == {
        "promotion_outcome": "promoted",
        "release_id": "release-20260701-001",
        "dataset_slug": "example-dataset",
        "public_dataset_slug": "example-dataset",
        "registry_action": "reused",
        "registry_bound": True,
        "can_promote": False,
        "can_remove": True,
        "reason": admin_runs._REGISTRY_BOUND_REASON,
    }
    _assert_no_private_markers(entry)


def test_run_with_valid_promoted_promotion_result_but_no_registry_match_omits_registry_fields(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_run_dir(root, "promoted-unmatched", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    _write_json(run_dir / "promotion-result.json", _PROMOTED_PROMOTION_RESULT)
    _write_registry(repo_root, [])

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    entry = result["runs"][0]
    assert entry["status"] == "promoted"
    assert entry["promotion_summary"] == {
        "promotion_outcome": "promoted",
        "release_id": "release-20260701-001",
        "dataset_slug": "example-dataset",
        "registry_bound": False,
        "can_promote": True,
        "can_remove": True,
        "reason": admin_runs._REGISTRY_ORPHANED_REASON,
    }
    assert "public_dataset_slug" not in entry["promotion_summary"]
    assert "registry_action" not in entry["promotion_summary"]


def test_run_without_promotion_result_remains_available(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    _write_run_dir(root, "not-promoted", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)

    original = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original

    entry = result["runs"][0]
    assert entry["status"] == "available"
    assert "promotion_summary" not in entry


def test_run_with_malformed_promotion_result_remains_available(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    run_dir = _write_run_dir(root, "malformed-promotion", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    (run_dir / "promotion-result.json").write_text("{not valid json", encoding="utf-8")

    original = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original

    entry = result["runs"][0]
    assert entry["status"] == "available"
    assert "promotion_summary" not in entry


def test_run_with_rejected_promotion_result_remains_available(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    run_dir = _write_run_dir(root, "rejected-promotion", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    rejected_result = json.loads(json.dumps(_PROMOTED_PROMOTION_RESULT))
    rejected_result["promotion_outcome"] = "rejected"
    _write_json(run_dir / "promotion-result.json", rejected_result)

    original = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original

    entry = result["runs"][0]
    assert entry["status"] == "available"
    assert "promotion_summary" not in entry


def test_run_with_missing_candidate_identity_in_promotion_result_remains_available(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    run_dir = _write_run_dir(root, "incomplete-promotion", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    incomplete_result = json.loads(json.dumps(_PROMOTED_PROMOTION_RESULT))
    del incomplete_result["candidate_identity"]
    _write_json(run_dir / "promotion-result.json", incomplete_result)

    original = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original

    entry = result["runs"][0]
    assert entry["status"] == "available"
    assert "promotion_summary" not in entry


# ---------------------------------------------------------------------------
# list_admin_run_summaries / promote_admin_run / remove_admin_run: registry-
# bound promoted vs. registry-missing re-promotable action semantics
# (Project Spec S0048)
# ---------------------------------------------------------------------------

def test_fresh_promotion_ready_run_has_no_promotion_summary_and_stays_available(tmp_path):
    # A newly created, not-yet-promoted eligible run: functional Promote and
    # Remove actions are driven entirely by status == "available" plus
    # validation_summary.outcome == "accepted", with no promotion_summary at
    # all -- distinct from both S0048 promoted sub-states below.
    root = tmp_path / "runs"
    root.mkdir()
    _write_run_dir(root, "fresh-eligible", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)

    original = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.list_admin_run_summaries()
    finally:
        admin_runs._admin_runs_root = original

    entry = result["runs"][0]
    assert entry["status"] == "available"
    assert entry["validation_summary"] == {"outcome": "accepted"}
    assert "promotion_summary" not in entry


def test_remove_admin_run_on_registry_bound_promoted_run_only_deletes_run_directory(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_run_dir(root, "promoted-removable", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
    _write_json(run_dir / "promotion-result.json", _PROMOTED_PROMOTION_RESULT)
    _write_registry(
        repo_root,
        [
            {
                "dataset_slug": "example-dataset",
                "active_release": "release-20260701-001",
                "public_metadata": {
                    "title": "Example Dataset",
                    "summary": "Published dataset.",
                    "domain": "general",
                    "visibility": "public",
                    "tags": [],
                },
            }
        ],
    )
    release_dir = repo_root / "releases" / "release-20260701-001"
    release_dir.mkdir(parents=True)
    _write_json(release_dir / "manifest.json", _VALID_MANIFEST)
    registry_before = (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8")

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        # Sanity-check this run really is registry-bound promoted before
        # removing it, so the test actually exercises the intended state.
        before = admin_runs.list_admin_run_summaries()
        assert before["runs"][0]["promotion_summary"]["registry_bound"] is True

        result = admin_runs.remove_admin_run("promoted-removable")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result == {"run_id": "promoted-removable", "removed": True, "errors": []}
    assert not run_dir.exists()
    # Removal must delete only the run artifact/directory -- the registry and
    # the release directory/manifest it points at are untouched.
    assert (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8") == registry_before
    assert release_dir.exists()
    assert (release_dir / "manifest.json").is_file()


def test_promoted_run_becomes_repromotable_after_registry_entry_removed(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-then-orphan", "orphan-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root

        first = admin_runs.promote_admin_run("promote-then-orphan")
        assert first["promoted"] is True

        bound = admin_runs.list_admin_run_summaries()
        bound_entry = bound["runs"][0]
        assert bound_entry["promotion_summary"]["registry_bound"] is True
        assert bound_entry["promotion_summary"]["can_promote"] is False

        # The Dataset Detail is removed from the registry independently of
        # this run, via the real Project Spec S0049 removal boundary rather
        # than a raw registry rewrite.
        remove_result = registry_update.remove_dataset_entry("orphan-dataset", repo_root=repo_root)
        assert remove_result["removed"] is True

        orphaned = admin_runs.list_admin_run_summaries()
        orphaned_entry = orphaned["runs"][0]
        assert orphaned_entry["status"] == "promoted"
        assert orphaned_entry["promotion_summary"]["registry_bound"] is False
        assert orphaned_entry["promotion_summary"]["can_promote"] is True
        assert orphaned_entry["promotion_summary"]["can_remove"] is True
        assert "public_dataset_slug" not in orphaned_entry["promotion_summary"]
        assert "registry_action" not in orphaned_entry["promotion_summary"]

        second = admin_runs.promote_admin_run("promote-then-orphan")
        assert second["promoted"] is True
        assert second["registry_action"] == "created"

        registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
        assert any(entry["dataset_slug"] == "orphan-dataset" for entry in registry["datasets"])
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_admin_run_materializes_declared_predict_views_and_restores_after_dataset_deletion(tmp_path):
    """Project Spec S0098: registry/update.py's existing activation transaction
    (invoked by promote_admin_run(), not a second promotion endpoint) must
    materialize a promoted release's declared predict views, preserve an
    unrelated dataset's views, and restore them after the S0082 deletion
    cascade removes the Dataset Detail and its owned views without touching
    the release artifact.
    """
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    dataset_slug = "predict-view-dataset"
    release_id = "release-20260710t120000z"
    run_dir = _write_promotable_run(
        root,
        repo_root,
        "promote-with-view",
        dataset_slug,
        release_id,
        registry_entries=[
            {
                "dataset_slug": "unrelated-dataset",
                "active_release": "release-20260101-001",
                "public_metadata": {
                    "title": "Unrelated", "summary": "s", "domain": "general", "visibility": "public", "tags": [],
                },
            }
        ],
    )

    candidate_context_path = (
        repo_root / "releases" / "candidates" / dataset_slug / release_id / "public-context.json"
    )
    candidate_context = json.loads(candidate_context_path.read_text(encoding="utf-8"))
    candidate_context["predict_views"] = [
        {
            "schema_version": "1.0.0",
            "view_id": "fixture-view",
            "dataset_slug": dataset_slug,
            "display": {"title": "Fixture View", "summary": "A fixture predict view."},
            "intent": {"prediction_goal": "Demonstrate materialization.", "audience": "Fixture."},
            "binding": {"dataset_slug": dataset_slug, "release": {"mode": "active"}},
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "view_metadata_defines_runtime_validation": False,
                "view_metadata_duplicates_contract": False,
            },
        }
    ]
    _write_json(candidate_context_path, candidate_context)

    unrelated_view = {
        "schema_version": "1.0.0",
        "view_id": "unrelated-view",
        "dataset_slug": "unrelated-dataset",
        "display": {"title": "T", "summary": "S"},
        "intent": {"prediction_goal": "G", "audience": "A"},
        "binding": {"dataset_slug": "unrelated-dataset", "release": {"mode": "active"}},
        "contract_precedence": {
            "canonical_contracts_are_source_of_truth": True,
            "view_metadata_defines_runtime_validation": False,
            "view_metadata_duplicates_contract": False,
        },
    }
    predict_views_path = repo_root / "registry" / "predict-views.json"
    _write_json(
        predict_views_path,
        {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": [unrelated_view]},
    )
    _write_json(
        repo_root / "registry" / "predict-view-customizations.json",
        {"schema_version": "atlas.dataflow.predict-view-customizations.v1", "predict_view_customizations": []},
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root

        first = admin_runs.promote_admin_run("promote-with-view")
        assert first["promoted"] is True

        materialized = json.loads(predict_views_path.read_text())
        view_ids = {v["view_id"] for v in materialized["predict_views"]}
        assert view_ids == {"unrelated-view", "fixture-view"}
        fixture_view = next(v for v in materialized["predict_views"] if v["view_id"] == "fixture-view")
        assert fixture_view["dataset_slug"] == dataset_slug
        assert unrelated_view in materialized["predict_views"]

        # Simulate api/main.py's S0082 deletion cascade (owned by that route,
        # not registry/update.py): remove this dataset's predict views, then
        # remove its registry entry.
        retained = [v for v in materialized["predict_views"] if v.get("dataset_slug") != dataset_slug]
        _write_json(
            predict_views_path,
            {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": retained},
        )
        remove_result = registry_update.remove_dataset_entry(dataset_slug, repo_root=repo_root)
        assert remove_result["removed"] is True
        after_delete = json.loads(predict_views_path.read_text())
        assert {v["view_id"] for v in after_delete["predict_views"]} == {"unrelated-view"}

        second = admin_runs.promote_admin_run("promote-with-view")
        assert second["promoted"] is True
        assert second["registry_action"] == "created"

        restored = json.loads(predict_views_path.read_text())
        assert {v["view_id"] for v in restored["predict_views"]} == {"unrelated-view", "fixture-view"}
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


# ---------------------------------------------------------------------------
# remove_admin_run: happy path and rejection states
# ---------------------------------------------------------------------------

def test_remove_admin_run_deletes_existing_run_directory():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = _write_run_dir(root, "removable-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.remove_admin_run("removable-run")
        finally:
            admin_runs._admin_runs_root = original

        assert result == {"run_id": "removable-run", "removed": True, "errors": []}
        assert not run_dir.exists()


def test_remove_admin_run_rejects_empty_id():
    result = admin_runs.remove_admin_run("")
    assert result["removed"] is False
    assert result["errors"][0]["code"] == "RUN_ID_INVALID"


def test_remove_admin_run_rejects_ids_with_path_separators():
    for candidate in ("nested/run", "nested\\run"):
        result = admin_runs.remove_admin_run(candidate)
        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_ID_INVALID"


def test_remove_admin_run_rejects_dot_dot_traversal():
    for candidate in ("..", "../escape", "run..id"):
        result = admin_runs.remove_admin_run(candidate)
        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_ID_INVALID"


def test_remove_admin_run_rejects_absolute_paths():
    for candidate in ("/etc/passwd", "C:\\Windows"):
        result = admin_runs.remove_admin_run(candidate)
        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_ID_INVALID"


def test_remove_admin_run_reports_not_found_for_missing_run_directory():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.remove_admin_run("does-not-exist")
        finally:
            admin_runs._admin_runs_root = original

        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_NOT_FOUND"


def test_remove_admin_run_reports_not_found_for_non_directory_target():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "not-a-directory").write_text("not a run", encoding="utf-8")
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.remove_admin_run("not-a-directory")
        finally:
            admin_runs._admin_runs_root = original

        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_NOT_FOUND"
        assert (root / "not-a-directory").exists()


def test_remove_admin_run_rejects_symlink_escaping_runs_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        outside = Path(tmp) / "outside"
        root.mkdir()
        _write_run_dir(outside, "secret-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        escaping_link = root / "escaping-link"
        escaping_link.symlink_to(outside / "secret-run", target_is_directory=True)

        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.remove_admin_run("escaping-link")
        finally:
            admin_runs._admin_runs_root = original

        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_NOT_FOUND"
        assert (outside / "secret-run").exists()


# ---------------------------------------------------------------------------
# promote_admin_run: happy path, registry create/update, and rejection states
# ---------------------------------------------------------------------------

def _write_promotable_run(
    root: Path,
    repo_root: Path,
    run_id: str,
    dataset_slug: str,
    release_id: str,
    *,
    registry_entries: list | None = None,
    create_candidate_dir: bool = True,
) -> Path:
    """Build a self-contained repo_root (release candidate, operational note,
    registry) plus a run_dir under root with an accepted, promotion-eligible
    validation result -- everything promote_admin_run() needs end to end,
    without touching the real target repository.

    create_candidate_dir=False omits releases/candidates/{dataset_slug}/{release_id}/
    entirely, for simulating a validation result whose referenced release_id
    has no matching candidate directory in the fixture repository root.
    """
    if create_candidate_dir:
        candidate_dir = repo_root / "releases" / "candidates" / dataset_slug / release_id
        candidate_dir.mkdir(parents=True)
        _write_json(
            candidate_dir / "public-context.json",
            {
                "schema_version": "1.0.0",
                "dataset_slug": dataset_slug,
                "title": "Promotable Dataset",
                "description": "Fixture dataset used to validate the promotion flow.",
                "domain": "testing",
                "tags": ["fixture", "promotion"],
            },
        )

    manifest = {
        "schema_version": "release-manifest.v1",
        "manifest_kind": "release_manifest",
        "dataset_identity": {"dataset_slug": dataset_slug, "dataset_title": "Promotable Dataset"},
        "release_identity": {
            "release_id": release_id,
            "release_version": "1.0.0-rc.1",
            "created_at": "2026-07-10T10:00:00Z",
        },
        "artifacts": [
            {
                "role": "public_context",
                "reference": "public-context.json",
                "hash_algorithm": "sha256",
                "hash_value": "0" * 64,
            },
        ],
    }

    validation_result = {
        "schema_version": "release-candidate-validation.v1",
        "candidate_identity": {
            "dataset_slug": dataset_slug,
            "release_id": release_id,
            "release_version": "1.0.0-rc.1",
        },
        "validation_outcome": "accepted",
        "rejection": {"rejected": False, "reasons": []},
        "promotion_gate": {"promotion_allowed": True, "registry_update_allowed": True},
    }

    run_dir = _write_run_dir(root, run_id, manifest, validation_result)

    note_dst = repo_root / "publisher" / "release-candidate.operational-note.json"
    note_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "publisher" / "release-candidate.operational-note.json", note_dst)

    registry_dir = repo_root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
            "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
            "active_release": {"description": "x"},
        },
        "datasets": registry_entries if registry_entries is not None else [],
    }
    _write_json(registry_dir / "datasets.json", registry)

    return run_dir


def test_publisher_promote_cleans_up_release_dir_after_result_write_failure(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "promote-write-fail", "write-fail-dataset", "release-20260710t101438z"
    )
    release_dir = repo_root / "releases" / "release-20260710t101438z"

    original_write_text = Path.write_text

    def flaky_write_text(self, *args, **kwargs):
        if self.name == "promotion-result.json":
            raise OSError("simulated disk failure")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    raised = False
    try:
        admin_runs.publisher_promote.run(str(run_dir), repo_root=repo_root)
    except OSError:
        raised = True

    assert raised
    assert not release_dir.exists()


def test_promote_admin_run_retry_succeeds_after_simulated_post_copy_failure(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-retry", "retry-dataset", "release-20260710t101438z"
    )
    release_dir = repo_root / "releases" / "release-20260710t101438z"

    should_fail = {"value": True}
    original_write_text = Path.write_text

    def flaky_write_text(self, *args, **kwargs):
        if self.name == "promotion-result.json" and should_fail["value"]:
            raise OSError("simulated disk failure")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root

        first = admin_runs.promote_admin_run("promote-retry")
        assert first["promoted"] is False
        assert first["errors"][0]["code"] == "PROMOTION_FAILED"
        assert not release_dir.exists()

        should_fail["value"] = False
        second = admin_runs.promote_admin_run("promote-retry")
        assert second["promoted"] is True
        assert second["release_id"] == "release-20260710t101438z"
        assert release_dir.exists()
        assert (release_dir / "manifest.json").is_file()
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_admin_run_maps_filesystem_failure_to_structured_error(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-fs-fail", "fs-fail-dataset", "release-20260710t101438z"
    )

    def raising_run(*args, **kwargs):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(admin_runs.publisher_promote, "run", raising_run)

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-fs-fail")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "PROMOTION_FAILED"


def test_remove_admin_run_maps_filesystem_failure_to_structured_error(tmp_path, monkeypatch):
    root = tmp_path
    run_dir = _write_run_dir(root, "removal-fs-fail", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)

    def raising_rmtree(*args, **kwargs):
        raise OSError("simulated permission failure")

    monkeypatch.setattr(admin_runs.shutil, "rmtree", raising_rmtree)

    original_root = admin_runs._admin_runs_root
    try:
        admin_runs._admin_runs_root = lambda: root
        result = admin_runs.remove_admin_run("removal-fs-fail")
    finally:
        admin_runs._admin_runs_root = original_root

    assert result["removed"] is False
    assert result["errors"][0]["code"] == "RUN_REMOVAL_FAILED"
    assert run_dir.exists()


def test_promote_admin_run_rejects_invalid_run_id():
    result = admin_runs.promote_admin_run("../escape")
    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "RUN_ID_INVALID"


def test_promote_admin_run_reports_not_found_for_missing_run_directory():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.promote_admin_run("does-not-exist")
        finally:
            admin_runs._admin_runs_root = original

        assert result["promoted"] is False
        assert result["errors"][0]["code"] == "RUN_NOT_FOUND"


def test_promote_admin_run_rejects_run_missing_validation_result():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "no-validation", _VALID_MANIFEST, None)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.promote_admin_run("no-validation")
        finally:
            admin_runs._admin_runs_root = original

        assert result["promoted"] is False
        assert result["errors"][0]["code"] == "RUN_VALIDATION_MISSING"


def test_promote_admin_run_rejects_rejected_run():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "rejected-run", _VALID_MANIFEST, _REJECTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.promote_admin_run("rejected-run")
        finally:
            admin_runs._admin_runs_root = original

        assert result["promoted"] is False
        assert result["errors"][0]["code"] == "PROMOTION_NOT_ALLOWED"


def test_promote_admin_run_rejects_accepted_run_without_promotion_gate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "no-gate", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.promote_admin_run("no-gate")
        finally:
            admin_runs._admin_runs_root = original

        assert result["promoted"] is False
        assert result["errors"][0]["code"] == "PROMOTION_NOT_ALLOWED"


def test_promote_admin_run_creates_new_registry_entry_from_public_context(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "promote-new", "new-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-new")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result == {
        "run_id": "promote-new",
        "promoted": True,
        "dataset_slug": "new-dataset",
        "release_id": "release-20260710t101438z",
        "registry_action": "created",
        "public_dataset_slug": "new-dataset",
        "errors": [],
    }

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "new-dataset")
    assert entry["active_release"] == "release-20260710t101438z"
    assert entry["public_metadata"] == {
        "title": "Promotable Dataset",
        "summary": "Fixture dataset used to validate the promotion flow.",
        "domain": "testing",
        "visibility": "public",
        "tags": ["fixture", "promotion"],
    }
    assert (repo_root / "releases" / "release-20260710t101438z" / "public-context.json").is_file()
    assert (run_dir / "promotion-result.json").is_file()
    _assert_no_private_markers(entry)

    promotion_result = json.loads((run_dir / "promotion-result.json").read_text())
    record = promotion_result["registry_update_record"]
    assert record["update_applied"] is True
    assert record["new_active_release_id"] == "release-20260710t101438z"
    assert record["previous_active_release_id"] is None
    assert record["registry_action"] == "created"
    assert "public_dataset_slug" not in record


# ---------------------------------------------------------------------------
# promote_admin_run: promotion-result.json registry_update_record
# synchronization (Project Spec S0046)
# ---------------------------------------------------------------------------

def test_promote_admin_run_finalizes_registry_update_record_for_updated_action(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "sync-dataset",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Sync Dataset",
            "summary": "Already published.",
            "domain": "example",
            "visibility": "public",
            "tags": [],
        },
    }
    run_dir = _write_promotable_run(
        root,
        repo_root,
        "promote-sync-update",
        "sync-dataset",
        "release-20260710t101438z",
        registry_entries=[existing_entry],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-sync-update")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["registry_action"] == "updated"

    record = json.loads((run_dir / "promotion-result.json").read_text())["registry_update_record"]
    assert record["update_applied"] is True
    assert record["new_active_release_id"] == "release-20260710t101438z"
    assert record["previous_active_release_id"] == "release-20260601-001"
    assert record["registry_action"] == "updated"
    assert "public_dataset_slug" not in record


def test_promote_admin_run_repeated_call_does_not_rewrite_previous_active_release_id(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-sync-retry", "sync-retry-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        run_dir = root / "promote-sync-retry"

        first = admin_runs.promote_admin_run("promote-sync-retry")
        first_record = json.loads((run_dir / "promotion-result.json").read_text())["registry_update_record"]

        second = admin_runs.promote_admin_run("promote-sync-retry")
        second_record = json.loads((run_dir / "promotion-result.json").read_text())["registry_update_record"]
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert first["registry_action"] == "created"
    assert second["registry_action"] == "reused"

    # The API response's own idempotence signal (re-derived fresh each call,
    # per registry.update.derive_registry_action) correctly flips from
    # "created" to "reused" -- but the persisted promotion-result.json must
    # not be rewritten with previous_active_release_id re-derived as the
    # release's own id (which a second raw registry_update.run() call would
    # report), since that would read as a contradictory regression.
    assert first_record == second_record
    assert first_record["previous_active_release_id"] is None
    assert first_record["registry_action"] == "created"


def test_promote_admin_run_registry_update_failure_leaves_promotion_result_unsynchronized(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "promote-registry-fail", "registry-fail-dataset", "release-20260710t101438z"
    )

    def raising_run(*args, **kwargs):
        raise RuntimeError("simulated registry update failure")

    monkeypatch.setattr(admin_runs.registry_update, "run", raising_run)

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-registry-fail")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "REGISTRY_UPDATE_FAILED"

    # The release copy itself already succeeded (publisher_promote.run() ran
    # before the simulated registry failure), so promotion-result.json
    # exists -- but it must never be finalized into a false "registry
    # activated" claim when the registry update that would justify that
    # claim never actually succeeded.
    promotion_result = json.loads((run_dir / "promotion-result.json").read_text())
    assert promotion_result["promotion_outcome"] == "promoted"
    record = promotion_result["registry_update_record"]
    assert record["update_applied"] is False
    assert record["new_active_release_id"] is None
    assert "registry_action" not in record


def test_promote_admin_run_updates_existing_registry_entry(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "existing-dataset",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Existing Dataset",
            "summary": "Already published.",
            "domain": "existing",
            "visibility": "public",
            "tags": ["existing"],
        },
    }
    _write_promotable_run(
        root,
        repo_root,
        "promote-existing",
        "existing-dataset",
        "release-20260710t101438z",
        registry_entries=[existing_entry],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-existing")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is True
    assert result["registry_action"] == "updated"

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    assert len(registry["datasets"]) == 1
    entry = registry["datasets"][0]
    assert entry["active_release"] == "release-20260710t101438z"
    assert entry["public_metadata"]["title"] == "Existing Dataset"


def test_promote_admin_run_create_new_mode_allocates_numbered_slug_and_preserves_existing_entry(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "telco-customer-churn",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Telco Customer Churn",
            "summary": "Already published.",
            "domain": "telco",
            "visibility": "public",
            "tags": ["telco"],
        },
    }
    _write_promotable_run(
        root,
        repo_root,
        "promote-new-detail",
        "telco-customer-churn",
        "release-20260710t101438z",
        registry_entries=[existing_entry],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run(
            "promote-new-detail", mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
        )
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is True
    assert result["dataset_slug"] == "telco-customer-churn"
    assert result["registry_action"] == "created"
    assert result["public_dataset_slug"] == "telco-customer-churn1"

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    assert len(registry["datasets"]) == 2
    original_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn")
    assert original_entry["active_release"] == "release-20260601-001"
    new_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn1")
    assert new_entry["active_release"] == "release-20260710t101438z"
    _assert_no_private_markers(result)
    _assert_no_private_markers(new_entry)


def test_promote_admin_run_create_new_mode_is_idempotent_on_retry(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "telco-customer-churn",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Telco Customer Churn",
            "summary": "Already published.",
            "domain": "telco",
            "visibility": "public",
            "tags": ["telco"],
        },
    }
    _write_promotable_run(
        root,
        repo_root,
        "promote-new-detail-retry",
        "telco-customer-churn",
        "release-20260710t101438z",
        registry_entries=[existing_entry],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        first = admin_runs.promote_admin_run(
            "promote-new-detail-retry", mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
        )
        second = admin_runs.promote_admin_run(
            "promote-new-detail-retry", mode=registry_update.MODE_CREATE_NEW_DATASET_DETAIL
        )
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert first["public_dataset_slug"] == "telco-customer-churn1"
    assert first["registry_action"] == "created"
    assert second["public_dataset_slug"] == "telco-customer-churn1"
    # Same S0044 no-op-versus-genuine-update distinction as the default-mode
    # repeated-call test above, exercised here for MODE_CREATE_NEW_DATASET_DETAIL.
    assert second["registry_action"] == "reused"

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    matching = [e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn1"]
    assert len(matching) == 1


def test_promote_admin_run_rejects_unrecognized_mode():
    result = admin_runs.promote_admin_run("any-run", mode="not_a_real_mode")
    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "PROMOTION_MODE_INVALID"
    assert result["public_dataset_slug"] is None


def test_promote_admin_run_repeated_call_reuses_existing_promotion_safely(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "promote-twice", "twice-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        first = admin_runs.promote_admin_run("promote-twice")
        promotion_result_after_first = json.loads((run_dir / "promotion-result.json").read_text())
        second = admin_runs.promote_admin_run("promote-twice")
        promotion_result_after_second = json.loads((run_dir / "promotion-result.json").read_text())
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert first["promoted"] is True
    assert first["registry_action"] == "created"
    assert second["promoted"] is True
    assert second["dataset_slug"] == "twice-dataset"
    assert second["release_id"] == "release-20260710t101438z"
    # Project Spec S0044: a repeated Promote click for the same run (and
    # mode) that ends up with the exact same active_release already set is a
    # safe no-op, distinguishable from a genuine "updated" outcome where an
    # existing entry's active_release actually changes to a different
    # release (see test_promote_admin_run_updates_existing_registry_entry).
    assert second["registry_action"] == "reused"
    assert promotion_result_after_first == promotion_result_after_second


def test_promote_then_list_reflects_promoted_state_end_to_end(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-then-list", "before-and-after-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root

        before = admin_runs.list_admin_run_summaries()
        before_entry = before["runs"][0]
        assert before_entry["status"] == "available"
        assert "promotion_summary" not in before_entry

        promotion = admin_runs.promote_admin_run("promote-then-list")
        assert promotion["promoted"] is True

        after = admin_runs.list_admin_run_summaries()
        after_entry = after["runs"][0]
        assert after_entry["status"] == "promoted"
        assert after_entry["promotion_summary"] == {
            "promotion_outcome": "promoted",
            "release_id": "release-20260710t101438z",
            "dataset_slug": "before-and-after-dataset",
            "public_dataset_slug": "before-and-after-dataset",
            "registry_action": "reused",
            "registry_bound": True,
            "can_promote": False,
            "can_remove": True,
            "reason": admin_runs._REGISTRY_BOUND_REASON,
        }
        _assert_no_private_markers(after_entry)

        # A repeated Promote click on an already-promoted run must remain a
        # safe, idempotent no-op: no new release directory, no new slug.
        repeated = admin_runs.promote_admin_run("promote-then-list")
        assert repeated["promoted"] is True
        assert repeated["registry_action"] == "reused"
        assert repeated["public_dataset_slug"] == "before-and-after-dataset"
        release_dirs = [entry for entry in (repo_root / "releases").iterdir() if entry.name.startswith("release-")]
        assert len(release_dirs) == 1
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_admin_run_rejects_removed_run_directory_between_check_and_promotion():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "not-a-directory").write_text("not a run", encoding="utf-8")
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.promote_admin_run("not-a-directory")
        finally:
            admin_runs._admin_runs_root = original

        assert result["promoted"] is False
        assert result["errors"][0]["code"] == "RUN_NOT_FOUND"


def test_promoted_dataset_slug_resolves_through_registry_resolver(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "resolve-check", "resolve-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("resolve-check")
        assert result["promoted"] is True

        resolved = resolve_dataset(
            "resolve-dataset", registry_path=repo_root / "registry" / "datasets.json"
        )
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert resolved.dataset_slug == "resolve-dataset"
    assert resolved.active_release == "release-20260710t101438z"


def test_registry_validate_accepts_deterministic_release_id_format():
    registry = {
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "x", "description": "x"},
            "release_id": {"pattern": "x", "description": "x"},
            "active_release": {"description": "x"},
        },
        "datasets": [
            {
                "dataset_slug": "deterministic-dataset",
                "active_release": "release-20260710t101438z",
                "public_metadata": {
                    "title": "T",
                    "summary": "S",
                    "domain": "D",
                    "visibility": "public",
                    "tags": [],
                },
            },
            {
                "dataset_slug": "historical-dataset",
                "active_release": "release-20260619-001",
                "public_metadata": {
                    "title": "T2",
                    "summary": "S2",
                    "domain": "D2",
                    "visibility": "public",
                    "tags": [],
                },
            },
        ],
    }
    result = validate_registry(registry)
    assert result["valid"] is True
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Runtime-boundary simulation (S0040): real chmod-based filesystem
# boundaries, distinct from the monkeypatch-simulated failures above --
# these reproduce the class of failure a genuinely read-only or
# copy-then-fails runtime mount produces (see S0038/S0039), rather than an
# internal function being made to raise on demand.
# ---------------------------------------------------------------------------

def test_remove_admin_run_reports_structured_failure_when_runs_root_is_effectively_read_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = _write_run_dir(root, "readonly-boundary-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original_root_mode = root.stat().st_mode & 0o777
        # read+execute only on the runs root: no write permission means the
        # run directory entry itself cannot be unlinked, mirroring a
        # read-only publisher/runs mount boundary.
        os.chmod(root, 0o500)
        try:
            original = admin_runs._admin_runs_root
            try:
                admin_runs._admin_runs_root = lambda: root
                result = admin_runs.remove_admin_run("readonly-boundary-run")
            finally:
                admin_runs._admin_runs_root = original
        finally:
            os.chmod(root, original_root_mode)

        assert result["run_id"] == "readonly-boundary-run"
        assert result["removed"] is False
        assert result["errors"][0]["code"] == "RUN_REMOVAL_FAILED"
        assert run_dir.exists()


def test_promote_admin_run_reports_structured_failure_and_leaves_no_release_residue_when_run_directory_is_effectively_read_only(
    tmp_path,
):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "promote-readonly-run-dir", "readonly-run-dir-dataset", "release-20260710t101438z"
    )
    release_dir = repo_root / "releases" / "release-20260710t101438z"
    original_run_dir_mode = run_dir.stat().st_mode & 0o777
    # read+execute only on the run directory, applied only after its fixture
    # files (manifest.json, validation-result.json) already exist: the
    # release artifact copy into releases/{release_id}/ can still succeed,
    # but the run directory can no longer accept the new
    # promotion-result.json file -- exactly the boundary a real read-only
    # runs mount would produce mid-promotion.
    os.chmod(run_dir, 0o500)
    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-readonly-run-dir")
    finally:
        os.chmod(run_dir, original_run_dir_mode)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "PROMOTION_FAILED"
    assert result["release_id"] is None
    # No unhandled exception propagated (a structured failure was returned
    # above) and no orphaned releases/{release_id}/ directory was left
    # behind by the failed post-copy write.
    assert not release_dir.exists()
    assert not (run_dir / "promotion-result.json").exists()


def test_promote_admin_run_reports_structured_failure_when_release_candidate_directory_is_absent(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root,
        repo_root,
        "promote-missing-candidate",
        "missing-candidate-dataset",
        "release-20260710t101438z",
        create_candidate_dir=False,
    )
    release_dir = repo_root / "releases" / "release-20260710t101438z"

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-missing-candidate")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is False
    assert result["errors"][0]["code"] == "PROMOTION_FAILED"
    assert not release_dir.exists()
    assert not (run_dir / "promotion-result.json").exists()


# ---------------------------------------------------------------------------
# POST /admin/runs/{run_id}/promote: access-control boundary
# ---------------------------------------------------------------------------

def _make_promote_request(run_id: str, headers: dict[str, str]) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/admin/runs/{run_id}/promote",
        "headers": encoded_headers,
    }
    return Request(scope)


def test_promote_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_promote_request("any-run", {})
    response = api_main.promote_admin_run_route("any-run", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_promote_route_promotes_run_when_admin_runtime_enabled(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "route-promote", "route-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        request = _make_promote_request("route-promote", {})
        response = api_main.promote_admin_run_route("route-promote", request)

        assert response["promoted"] is True
        assert response["dataset_slug"] == "route-dataset"
        assert response["registry_action"] == "created"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_route_returns_sanitized_422_when_run_not_found():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            admin_runs._admin_runs_root = lambda: root
            request = _make_promote_request("does-not-exist", {})
            response = api_main.promote_admin_run_route("does-not-exist", request)

            assert response.status_code == 422
            body = json.loads(response.body.decode("utf-8"))
            assert body["error_code"] == "ADMIN_RUN_PROMOTION_FAILED"
            assert body["errors"][0]["code"] == "RUN_NOT_FOUND"
            _assert_no_private_markers(body)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_promote_route_maps_filesystem_failure_to_structured_error(tmp_path, monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "route-promote-fs-fail", "route-fs-fail-dataset", "release-20260710t101438z"
    )

    def raising_run(*args, **kwargs):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(admin_runs.publisher_promote, "run", raising_run)

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        request = _make_promote_request("route-promote-fs-fail", {})
        response = api_main.promote_admin_run_route("route-promote-fs-fail", request)

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_RUN_PROMOTION_FAILED"
        assert body["errors"][0]["code"] == "PROMOTION_FAILED"
        _assert_no_private_markers(body)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_route_always_creates_new_dataset_detail_regardless_of_request_body_mode(tmp_path):
    # Project Spec S0047: the Admin route never forwards a request-body mode
    # -- it always promotes with MODE_CREATE_NEW_DATASET_DETAIL, so a
    # colliding base dataset_slug always allocates a new numbered public
    # slug and never touches the existing entry, regardless of what (if
    # anything, including the historical or an unrecognized mode) the
    # request body contains.
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "telco-customer-churn",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Telco Customer Churn",
            "summary": "Already published.",
            "domain": "telco",
            "visibility": "public",
            "tags": ["telco"],
        },
    }

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        for run_id, payload in (
            ("route-promote-no-body", None),
            ("route-promote-explicit-create-new", {"mode": registry_update.MODE_CREATE_NEW_DATASET_DETAIL}),
            ("route-promote-legacy-update-mode", {"mode": registry_update.MODE_UPDATE_EXISTING_OR_CREATE}),
            ("route-promote-unknown-mode", {"mode": "not_a_real_mode"}),
        ):
            run_root = root / run_id
            run_repo_root = repo_root / run_id
            run_root.mkdir()
            _write_promotable_run(
                run_root,
                run_repo_root,
                run_id,
                "telco-customer-churn",
                "release-20260710t101438z",
                registry_entries=[dict(existing_entry)],
            )

            admin_runs._admin_runs_root = lambda run_root=run_root: run_root
            admin_runs._REPO_ROOT = run_repo_root
            request = _make_promote_request(run_id, {})
            response = api_main.promote_admin_run_route(run_id, request, payload)

            assert response["promoted"] is True, payload
            assert response["registry_action"] == "created", payload
            assert response["public_dataset_slug"] == "telco-customer-churn1", payload

            registry = json.loads((run_repo_root / "registry" / "datasets.json").read_text())
            original_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn")
            assert original_entry["active_release"] == "release-20260601-001", payload
            new_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn1")
            assert new_entry["active_release"] == "release-20260710t101438z", payload
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


def test_promote_route_returns_sanitized_422_for_rejected_run():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_dir(root, "rejected-route-run", _VALID_MANIFEST, _REJECTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_promote_request("rejected-route-run", {})
            response = api_main.promote_admin_run_route("rejected-route-run", request)

            assert response.status_code == 422
            body = json.loads(response.body.decode("utf-8"))
            assert body["error_code"] == "ADMIN_RUN_PROMOTION_FAILED"
            assert body["errors"][0]["code"] == "PROMOTION_NOT_ALLOWED"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


# ---------------------------------------------------------------------------
# GET /admin/runs: access-control boundary
# ---------------------------------------------------------------------------

def test_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({})
    response = api_main.list_admin_runs(request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_route_returns_listing_when_header_missing_in_private_runtime():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_dir(root, "validate-tokenless", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_request({})
            response = api_main.list_admin_runs(request)
            assert response["runs_root_status"] == "available"
            assert len(response["runs"]) == 1
            assert response["runs"][0]["run_id"] == "validate-tokenless"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_route_returns_generic_not_found_when_admin_runtime_false_even_with_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.list_admin_runs(request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_route_returns_generic_not_found_when_admin_runtime_unset_even_with_token_header():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "correct-token"})
        response = api_main.list_admin_runs(request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_route_returns_generic_not_found_when_admin_runtime_false_even_with_matching_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "correct-token"})
        response = api_main.list_admin_runs(request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_route_returns_listing_in_private_runtime_without_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_dir(root, "validate-ok", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_request({})
            response = api_main.list_admin_runs(request)

            assert response["runs_root_status"] == "available"
            assert len(response["runs"]) == 1
            entry = response["runs"][0]
            trace_reference = entry.pop("trace_reference")
            assert trace_reference is not None
            assert not trace_reference.startswith("/")
            assert trace_reference.endswith("validate-ok")
            assert entry == {
                "schema_version": "admin-run-summary.v1",
                "run_id": "validate-ok",
                "status": "available",
                "dataset_candidate": "example-dataset",
                "created_at": "2026-07-01T00:00:00Z",
                "validation_summary": {"outcome": "accepted"},
            }
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_route_listing_is_sanitized_even_when_source_contains_private_fields():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = json.loads(json.dumps(_VALID_MANIFEST))
            manifest["private_file"] = "/private/generated-runs/validate-route/manifest.json"
            manifest["secret"] = "secret-token-value"
            _write_run_dir(root, "validate-route", manifest, _REJECTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_request({})
            response = api_main.list_admin_runs(request)

            assert response["runs_root_status"] == "available"
            assert len(response["runs"]) == 1
            entry = response["runs"][0]
            assert set(entry) <= _SAFE_RUN_SUMMARY_KEYS
            assert entry["validation_summary"] == {
                "outcome": "rejected",
                "reason": "metrics artifact missing",
            }
            _assert_no_private_markers(response)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_route_listing_reflects_promoted_run_state():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            repo_root = Path(tmp) / "repo"
            root.mkdir()
            run_dir = _write_run_dir(root, "route-promoted", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            _write_json(run_dir / "promotion-result.json", _PROMOTED_PROMOTION_RESULT)
            _write_registry(
                repo_root,
                [
                    {
                        "dataset_slug": "example-dataset",
                        "active_release": "release-20260701-001",
                        "public_metadata": {
                            "title": "Example Dataset",
                            "summary": "Published dataset.",
                            "domain": "general",
                            "visibility": "public",
                            "tags": [],
                        },
                    }
                ],
            )
            admin_runs._admin_runs_root = lambda: root
            admin_runs._REPO_ROOT = repo_root
            request = _make_request({})
            response = api_main.list_admin_runs(request)

            assert response["runs_root_status"] == "available"
            entry = response["runs"][0]
            assert entry["status"] == "promoted"
            assert entry["promotion_summary"]["release_id"] == "release-20260701-001"
            _assert_no_private_markers(response)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root


# ---------------------------------------------------------------------------
# DELETE /admin/runs/{run_id}: access-control boundary
# ---------------------------------------------------------------------------

def _make_delete_request(run_id: str, headers: dict[str, str]) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": f"/admin/runs/{run_id}",
        "headers": encoded_headers,
    }
    return Request(scope)


def test_delete_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_delete_request("any-run", {})
    response = api_main.delete_admin_run("any-run", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_delete_route_removes_run_when_admin_runtime_enabled():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = _write_run_dir(root, "removable-route-run", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_delete_request("removable-route-run", {})
            response = api_main.delete_admin_run("removable-route-run", request)

            assert response == {"run_id": "removable-route-run", "removed": True, "errors": []}
            assert not run_dir.exists()
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_delete_route_returns_sanitized_422_when_run_not_found():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            admin_runs._admin_runs_root = lambda: root
            request = _make_delete_request("does-not-exist", {})
            response = api_main.delete_admin_run("does-not-exist", request)

            assert response.status_code == 422
            body = json.loads(response.body.decode("utf-8"))
            assert body["error_code"] == "ADMIN_RUN_REMOVAL_FAILED"
            assert body["errors"][0]["code"] == "RUN_NOT_FOUND"
            _assert_no_private_markers(body)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_delete_route_maps_filesystem_removal_failure_to_structured_error(monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_dir(root, "removal-route-fs-fail", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root

            def raising_rmtree(*args, **kwargs):
                raise OSError("simulated permission failure")

            # Scoped to a `with` block (rather than the outer monkeypatch
            # fixture) so the patch is undone before tempfile.TemporaryDirectory's
            # own __exit__ cleanup below tries to call the real shutil.rmtree.
            with monkeypatch.context() as m:
                m.setattr(admin_runs.shutil, "rmtree", raising_rmtree)
                request = _make_delete_request("removal-route-fs-fail", {})
                response = api_main.delete_admin_run("removal-route-fs-fail", request)

            assert response.status_code == 422
            body = json.loads(response.body.decode("utf-8"))
            assert body["error_code"] == "ADMIN_RUN_REMOVAL_FAILED"
            assert body["errors"][0]["code"] == "RUN_REMOVAL_FAILED"
            _assert_no_private_markers(body)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_delete_route_returns_sanitized_422_for_traversal_attempt():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    try:
        request = _make_delete_request("..%2Fescape", {})
        response = api_main.delete_admin_run("../escape", request)

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_RUN_REMOVAL_FAILED"
        assert body["errors"][0]["code"] == "RUN_ID_INVALID"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# DELETE /admin/datasets/{dataset_slug}: access-control boundary and safe
# Dataset Detail removal lifecycle (Project Spec S0049)
# ---------------------------------------------------------------------------

def _make_dataset_delete_request(dataset_slug: str, headers: dict[str, str]) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": f"/admin/datasets/{dataset_slug}",
        "headers": encoded_headers,
    }
    return Request(scope)


_TELCO_REGISTRY_ENTRY = {
    "dataset_slug": "telco-customer-churn",
    "active_release": "release-20260616-001",
    "public_metadata": {
        "title": "Telco Customer Churn",
        "summary": "Published dataset.",
        "domain": "telco",
        "visibility": "public",
        "tags": [],
    },
}

_BANK_REGISTRY_ENTRY = {
    "dataset_slug": "bank-marketing",
    "active_release": "release-20260617-001",
    "public_metadata": {
        "title": "Bank Marketing",
        "summary": "Published dataset.",
        "domain": "finance",
        "visibility": "public",
        "tags": [],
    },
}


def test_delete_dataset_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_dataset_delete_request("telco-customer-churn", {})
    response = api_main.delete_admin_dataset_detail("telco-customer-churn", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_delete_dataset_route_removes_only_matching_registry_entry(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY), dict(_BANK_REGISTRY_ENTRY)])
    _write_json(
        repo_root / "registry" / "predict-views.json",
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [
                {"view_id": "telco-view", "dataset_slug": "telco-customer-churn"},
                {"view_id": "bank-view", "dataset_slug": "bank-marketing"},
            ],
        },
    )
    release_dir = repo_root / "releases" / "release-20260616-001"
    release_dir.mkdir(parents=True)
    _write_json(release_dir / "manifest.json", _VALID_MANIFEST)
    run_dir = repo_root / "publisher" / "runs" / "some-run"
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "manifest.json", _VALID_MANIFEST)
    media_name = "a" * 32 + ".png"
    media_file = repo_root / "media" / "home-cards" / media_name
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"profile image")
    profile_artifacts = [
        repo_root / "registry" / "profile-drafts" / "telco-customer-churn.json",
        repo_root / "registry" / "profile-drafts" / "telco-customer-churn.json.previous",
        repo_root / "registry" / "profile-snapshots" / "telco-customer-churn.json",
        repo_root / "registry" / "profile-snapshots" / "telco-customer-churn.json.previous",
        repo_root / "registry" / "profile-snapshots" / "telco-customer-churn.evidence.json",
        repo_root / "registry" / "profile-publications" / "telco-customer-churn.json",
    ]
    for artifact in profile_artifacts:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        _write_json(artifact, {
            "profile": {"home_card": {"background_image_ref": f"/media/home-cards/{media_name}"}},
        })

    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        request = _make_dataset_delete_request("telco-customer-churn", {})
        response = api_main.delete_admin_dataset_detail("telco-customer-churn", request)

        assert response == {
            "dataset_slug": "telco-customer-churn",
            "removed": True,
            "previous_active_release": "release-20260616-001",
            "errors": [],
            "profile_cleanup": {
                "completed": True,
                "artifacts_removed": 6,
                "media_removed": 1,
            },
        }

        registry = json.loads((repo_root / "registry" / "datasets.json").read_text(encoding="utf-8"))
        slugs = [entry["dataset_slug"] for entry in registry["datasets"]]
        assert slugs == ["bank-marketing"]
        predict_views = json.loads(
            (repo_root / "registry" / "predict-views.json").read_text(encoding="utf-8")
        )["predict_views"]
        assert predict_views == [{"view_id": "bank-view", "dataset_slug": "bank-marketing"}]

        # Removal must never touch releases/ or publisher/runs/.
        assert (release_dir / "manifest.json").is_file()
        assert (run_dir / "manifest.json").is_file()
        assert all(not artifact.exists() for artifact in profile_artifacts)
        assert not media_file.exists()
        _assert_no_private_markers(response)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_delete_dataset_route_returns_sanitized_422_when_slug_not_found(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY)])

    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        request = _make_dataset_delete_request("does-not-exist", {})
        response = api_main.delete_admin_dataset_detail("does-not-exist", request)

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_DATASET_DETAIL_REMOVAL_FAILED"
        assert body["errors"][0]["code"] == "DATASET_DETAIL_NOT_FOUND"
        _assert_no_private_markers(body)

        registry = json.loads((repo_root / "registry" / "datasets.json").read_text(encoding="utf-8"))
        assert [entry["dataset_slug"] for entry in registry["datasets"]] == ["telco-customer-churn"]
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_delete_dataset_route_frees_slug_for_create_new_promotion(tmp_path):
    # End-to-end proof of the S0049 acceptance criterion tying this route to
    # S0048/S0042 promotion semantics: once a Dataset Detail is removed from
    # the registry, its slug is no longer occupied, so a fresh promotion of
    # a run that shares the same base dataset_slug allocates the bare base
    # slug again instead of a numbered suffix.
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root,
        repo_root,
        "reallocate-run",
        "telco-customer-churn",
        "release-20260710t101438z",
        registry_entries=[dict(_TELCO_REGISTRY_ENTRY)],
    )
    _write_json(
        repo_root / "registry" / "predict-views.json",
        {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []},
    )

    original_root = admin_runs._admin_runs_root
    original_admin_repo_root = admin_runs._REPO_ROOT
    original_api_repo_root = api_main._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        api_main._REPO_ROOT = repo_root

        delete_request = _make_dataset_delete_request("telco-customer-churn", {})
        delete_response = api_main.delete_admin_dataset_detail("telco-customer-churn", delete_request)
        assert delete_response["removed"] is True

        promote_request = _make_promote_request("reallocate-run", {})
        promote_response = api_main.promote_admin_run_route("reallocate-run", promote_request)

        assert promote_response["promoted"] is True
        assert promote_response["registry_action"] == "created"
        assert promote_response["public_dataset_slug"] == "telco-customer-churn"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_admin_repo_root
        api_main._REPO_ROOT = original_api_repo_root


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/slug: access-control boundary and safe
# Dataset Detail slug rename lifecycle (Project Spec S0051)
# ---------------------------------------------------------------------------

def _make_dataset_slug_put_request(dataset_slug: str, headers: dict[str, str]) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "PUT",
        "path": f"/admin/datasets/{dataset_slug}/slug",
        "headers": encoded_headers,
    }
    return Request(scope)


def test_put_dataset_slug_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_dataset_slug_put_request("telco-customer-churn", {})
    response = api_main.put_admin_dataset_detail_slug(
        "telco-customer-churn", request, {"new_dataset_slug": "telco-churn-renamed"}
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_put_dataset_slug_route_renames_only_matching_registry_entry(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY), dict(_BANK_REGISTRY_ENTRY)])
    release_dir = repo_root / "releases" / "release-20260616-001"
    release_dir.mkdir(parents=True)
    _write_json(release_dir / "manifest.json", _VALID_MANIFEST)
    run_dir = repo_root / "publisher" / "runs" / "some-run"
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "manifest.json", _VALID_MANIFEST)

    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        request = _make_dataset_slug_put_request("telco-customer-churn", {})
        response = api_main.put_admin_dataset_detail_slug(
            "telco-customer-churn", request, {"new_dataset_slug": "telco-churn-renamed"}
        )

        assert response == {
            "dataset_slug": "telco-customer-churn",
            "new_dataset_slug": "telco-churn-renamed",
            "renamed": True,
            "errors": [],
        }

        registry = json.loads((repo_root / "registry" / "datasets.json").read_text(encoding="utf-8"))
        slugs = {entry["dataset_slug"] for entry in registry["datasets"]}
        assert slugs == {"telco-churn-renamed", "bank-marketing"}

        renamed_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-churn-renamed")
        assert renamed_entry["active_release"] == _TELCO_REGISTRY_ENTRY["active_release"]
        assert renamed_entry["public_metadata"] == _TELCO_REGISTRY_ENTRY["public_metadata"]

        # Rename must never touch releases/ or publisher/runs/.
        assert (release_dir / "manifest.json").is_file()
        assert (run_dir / "manifest.json").is_file()
        _assert_no_private_markers(response)
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_put_dataset_slug_route_returns_sanitized_422_for_duplicate_target_and_does_not_mutate(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY), dict(_BANK_REGISTRY_ENTRY)])
    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        original_content = (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8")

        request = _make_dataset_slug_put_request("telco-customer-churn", {})
        response = api_main.put_admin_dataset_detail_slug(
            "telco-customer-churn", request, {"new_dataset_slug": "bank-marketing"}
        )

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED"
        assert body["errors"][0]["code"] == "DATASET_SLUG_ALREADY_EXISTS"
        _assert_no_private_markers(body)

        assert (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_put_dataset_slug_route_returns_sanitized_422_for_invalid_target_and_does_not_mutate(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY)])
    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        original_content = (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8")

        request = _make_dataset_slug_put_request("telco-customer-churn", {})
        response = api_main.put_admin_dataset_detail_slug(
            "telco-customer-churn", request, {"new_dataset_slug": "Not A Valid Slug!"}
        )

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED"
        assert body["errors"][0]["code"] == "NEW_DATASET_SLUG_INVALID"
        _assert_no_private_markers(body)

        assert (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_put_dataset_slug_route_returns_sanitized_422_when_source_slug_not_found(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    repo_root = tmp_path / "repo"
    _write_registry(repo_root, [dict(_TELCO_REGISTRY_ENTRY)])
    original_repo_root = api_main._REPO_ROOT
    try:
        api_main._REPO_ROOT = repo_root
        original_content = (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8")

        request = _make_dataset_slug_put_request("does-not-exist", {})
        response = api_main.put_admin_dataset_detail_slug(
            "does-not-exist", request, {"new_dataset_slug": "does-not-exist-renamed"}
        )

        assert response.status_code == 422
        body = json.loads(response.body.decode("utf-8"))
        assert body["error_code"] == "ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED"
        assert body["errors"][0]["code"] == "DATASET_DETAIL_NOT_FOUND"
        _assert_no_private_markers(body)

        assert (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)
        api_main._REPO_ROOT = original_repo_root


def test_admin_dataset_slug_route_registered():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/slug" in paths


# ---------------------------------------------------------------------------
# list_admin_datasets / GET /admin/datasets / promotion draft default
# (Project Spec S0052)
# ---------------------------------------------------------------------------

_DRAFT_PROMOTED_ENTRY = {
    "dataset_slug": "fresh-promoted-dataset",
    "active_release": "release-20260710t101438z",
    "public_metadata": {
        "title": "Fresh Promoted Dataset",
        "summary": "Just promoted.",
        "domain": "general",
        "visibility": "public",
        "tags": [],
    },
    "review_status": "needs_review",
}

_LEGACY_SEEDED_ENTRY = {
    "dataset_slug": "legacy-seeded-dataset",
    "active_release": "release-20260601-001",
    "public_metadata": {
        "title": "Legacy Seeded Dataset",
        "summary": "Seeded before this issue, no review_status field.",
        "domain": "general",
        "visibility": "public",
        "tags": [],
    },
}

_EXPLICITLY_READY_ENTRY = {
    "dataset_slug": "explicitly-ready-dataset",
    "active_release": "release-20260601-002",
    "public_metadata": {
        "title": "Explicitly Ready Dataset",
        "summary": "Already reviewed and marked ready.",
        "domain": "general",
        "visibility": "public",
        "tags": [],
    },
    "review_status": "ready",
}


def test_list_admin_datasets_includes_both_draft_and_published_entries(tmp_path):
    registry_path = tmp_path / "datasets.json"
    _write_json(
        registry_path,
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": [_DRAFT_PROMOTED_ENTRY, _LEGACY_SEEDED_ENTRY, _EXPLICITLY_READY_ENTRY],
        },
    )

    from registry.list import list_admin_datasets

    result = list_admin_datasets(registry_path=registry_path)
    by_slug = {entry.dataset_slug: entry for entry in result}

    assert len(result) == 3
    assert by_slug["fresh-promoted-dataset"].publication_status == "needs_review"
    # No review_status field at all (every dataset seeded before this issue)
    # defaults to "ready", preserving existing public listing behavior.
    assert by_slug["legacy-seeded-dataset"].publication_status == "ready"
    assert by_slug["explicitly-ready-dataset"].publication_status == "ready"


def test_is_dataset_needs_review_reflects_registry_entry_state(tmp_path):
    registry_path = tmp_path / "datasets.json"
    _write_json(
        registry_path,
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": [_DRAFT_PROMOTED_ENTRY, _LEGACY_SEEDED_ENTRY],
        },
    )

    from registry.list import is_dataset_needs_review

    assert is_dataset_needs_review("fresh-promoted-dataset", registry_path=registry_path) is True
    assert is_dataset_needs_review("legacy-seeded-dataset", registry_path=registry_path) is False
    # A dataset_slug absent from the registry entirely is not "needs_review"
    # -- not-found handling is the caller's own responsibility.
    assert is_dataset_needs_review("does-not-exist", registry_path=registry_path) is False


def test_promote_admin_run_new_dataset_detail_defaults_to_needs_review(tmp_path):
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    _write_promotable_run(
        root, repo_root, "promote-draft-default", "draft-default-dataset", "release-20260710t101438z"
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-draft-default")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is True

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "draft-default-dataset")
    assert entry["review_status"] == "needs_review"

    from registry.list import is_dataset_needs_review

    assert is_dataset_needs_review(
        "draft-default-dataset", registry_path=repo_root / "registry" / "datasets.json"
    ) is True


def test_promote_admin_run_updating_existing_entry_never_touches_its_review_status(tmp_path):
    # An update to an already-existing entry (MODE_UPDATE_EXISTING_OR_CREATE
    # against a colliding base dataset_slug) must never retroactively mark
    # that pre-existing entry as needs_review -- only brand-new entry
    # creation defaults to draft.
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    existing_entry = {
        "dataset_slug": "already-ready-dataset",
        "active_release": "release-20260601-001",
        "public_metadata": {
            "title": "Already Ready Dataset",
            "summary": "Already published.",
            "domain": "general",
            "visibility": "public",
            "tags": [],
        },
        "review_status": "ready",
    }
    _write_promotable_run(
        root,
        repo_root,
        "promote-update-keeps-ready",
        "already-ready-dataset",
        "release-20260710t101438z",
        registry_entries=[existing_entry],
    )

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("promote-update-keeps-ready")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is True
    assert result["registry_action"] == "updated"

    registry = json.loads((repo_root / "registry" / "datasets.json").read_text())
    entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "already-ready-dataset")
    assert entry["review_status"] == "ready"


def test_admin_datasets_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({})
    response = api_main.list_admin_datasets_route(request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_admin_datasets_route_returns_draft_and_published_entries_in_private_runtime(tmp_path):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    registry_path = tmp_path / "datasets.json"
    _write_json(
        registry_path,
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": [_DRAFT_PROMOTED_ENTRY, _LEGACY_SEEDED_ENTRY],
        },
    )

    from registry import list as registry_list

    original_registry_path = registry_list.REGISTRY_PATH
    try:
        registry_list.REGISTRY_PATH = registry_path
        request = _make_request({})
        response = api_main.list_admin_datasets_route(request)
    finally:
        registry_list.REGISTRY_PATH = original_registry_path
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)

    by_slug = {entry["dataset_slug"]: entry for entry in response["datasets"]}
    assert by_slug["fresh-promoted-dataset"]["publication_status"] == "needs_review"
    assert by_slug["legacy-seeded-dataset"]["publication_status"] == "ready"
    _assert_no_private_markers(response)


def test_admin_datasets_does_not_use_manual_release_label_as_operational_fallback(tmp_path, monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    registry_path = tmp_path / "datasets.json"
    renamed = {
        **_EXPLICITLY_READY_ENTRY,
        "dataset_slug": "renamed-dataset",
        "active_release": "release-20260601-002",
    }
    _write_json(
        registry_path,
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": [renamed],
        },
    )
    from registry import list as registry_list

    original_registry_path = registry_list.REGISTRY_PATH
    monkeypatch.setattr(api_main, "list_admin_run_summaries", lambda: {"runs": [{
        "dataset_candidate": "old-dataset", "created_at": "2026-07-10T10:00:00Z"
    }]})
    monkeypatch.setattr(api_main, "read_published_profile_snapshot", lambda slug: {
        "active_release_at_publish_time": "release-20260601-002",
        "profile": {"display": {"release_date_label": "2026-05-12", "release_date_mode": "manual"}},
    })
    try:
        registry_list.REGISTRY_PATH = registry_path
        response = api_main.list_admin_datasets_route(_make_request({}))
    finally:
        registry_list.REGISTRY_PATH = original_registry_path
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    assert response["datasets"][0]["last_updated"] == "2026-06-01"


def test_admin_datasets_prefers_canonical_detail_timestamp_over_profile_and_run(tmp_path, monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    registry_path = tmp_path / "datasets.json"
    entry = {
        **_EXPLICITLY_READY_ENTRY,
        "dataset_detail_updated_at": "2026-07-12T21:30:00Z",
    }
    _write_json(registry_path, {
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [entry],
    })
    from registry import list as registry_list

    original_registry_path = registry_list.REGISTRY_PATH
    monkeypatch.setattr(api_main, "list_admin_run_summaries", lambda: {"runs": [{
        "dataset_candidate": entry["dataset_slug"], "created_at": "2026-07-13T10:00:00Z"
    }]})
    monkeypatch.setattr(api_main, "read_published_profile_snapshot", lambda slug: {
        "active_release_at_publish_time": entry["active_release"],
        "profile": {"display": {"release_date_label": "2026-05-12", "release_date_mode": "manual"}},
    })
    try:
        registry_list.REGISTRY_PATH = registry_path
        response = api_main.list_admin_datasets_route(_make_request({}))
    finally:
        registry_list.REGISTRY_PATH = original_registry_path
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    assert response["datasets"][0]["last_updated"] == "2026-07-12T21:30:00Z"


def test_admin_datasets_derives_date_from_active_release_without_profile_or_matching_run(tmp_path, monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    registry_path = tmp_path / "datasets.json"
    _write_json(
        registry_path,
        {
            "schema_version": "atlas.dataflow.registry.v1",
            "conventions": {
                "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                "active_release": {"description": "x"},
            },
            "datasets": [_DRAFT_PROMOTED_ENTRY],
        },
    )
    from registry import list as registry_list

    original_registry_path = registry_list.REGISTRY_PATH
    monkeypatch.setattr(api_main, "list_admin_run_summaries", lambda: {"runs": []})
    monkeypatch.setattr(api_main, "read_published_profile_snapshot", lambda slug: None)
    try:
        registry_list.REGISTRY_PATH = registry_path
        response = api_main.list_admin_datasets_route(_make_request({}))
    finally:
        registry_list.REGISTRY_PATH = original_registry_path
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    assert response["datasets"][0]["last_updated"] == "2026-07-10"


def test_admin_datasets_route_registered_and_distinct_from_public_datasets_route():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets" in paths
    assert "/datasets" in paths
    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert "/admin/datasets" not in public_paths


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------

_EXPECTED_PUBLIC_DATASET_PATHS = {
    "/datasets",
    "/datasets/{dataset_slug}",
    "/datasets/{dataset_slug}/contract",
    "/datasets/{dataset_slug}/inference",
    "/datasets/{dataset_slug}/metrics",
    "/datasets/{dataset_slug}/context",
    "/datasets/{dataset_slug}/model-card",
    "/datasets/{dataset_slug}/visualizations",
    "/datasets/{dataset_slug}/views",
    "/datasets/{dataset_slug}/views/{view_id}",
    "/datasets/{dataset_slug}/views/{view_id}/customization",
}


def test_admin_route_registered_and_public_dataset_routes_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/runs" in paths
    assert "/admin/runs/{run_id}/promote" in paths
    assert "/admin/datasets/{dataset_slug}" in paths

    dataset_paths = {path for path in paths if path.startswith("/datasets")}
    assert dataset_paths == _EXPECTED_PUBLIC_DATASET_PATHS

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("runs" in path for path in public_paths)


def test_public_health_remains_available_when_admin_runtime_disabled():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        assert api_main.health() == {"status": "ok"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# Project Spec S0190: operational-readiness review removal, direct promotion
# for a stale promotion_gate, and unavailable-run removal.
# ---------------------------------------------------------------------------


def test_operational_readiness_review_route_is_absent():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/runs/{run_id}/operational-readiness" not in paths
    assert not any("operational-readiness" in path for path in paths)

    dataset_paths = {path for path in paths if path.startswith("/datasets")}
    assert dataset_paths == _EXPECTED_PUBLIC_DATASET_PATHS


def test_review_admin_run_operational_readiness_function_is_absent():
    assert not hasattr(admin_runs, "review_admin_run_operational_readiness")
    assert not hasattr(api_main, "review_admin_run_operational_readiness_route")
    assert not hasattr(api_main, "ADMIN_RUN_OPERATIONAL_READINESS_REVIEW_FAILED")


def test_admin_run_summary_never_projects_operational_readiness_summary():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Simulate a historical S0189-era validation-result.json that still
        # carries operational_readiness_evaluation -- the Admin summary must
        # never project it as operational_readiness_summary any longer.
        legacy_validation_result = {
            **_ACCEPTED_VALIDATION_RESULT,
            "promotion_gate": {"promotion_allowed": False, "registry_update_allowed": False},
            "operational_readiness_evaluation": {
                "source": "bundle_only",
                "decision_reference": None,
                "sha256": None,
                "operational_validity": "unconfirmed",
                "operational_threshold_status": "unresolved",
                "operational_prediction_available": False,
                "decision_valid": False,
            },
        }
        _write_run_dir(root, "validate-legacy-external", _VALID_MANIFEST, legacy_validation_result)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            result = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        entry = result["runs"][0]
        assert entry["status"] == "available"
        assert "operational_readiness_summary" not in entry


def test_promote_admin_run_promotes_accepted_run_with_stale_promotion_gate_false(tmp_path):
    """Project Spec S0190 Section D compatibility: an existing accepted run
    whose validation-result.json still carries a stale
    promotion_gate.promotion_allowed: false (from the retired
    operational-readiness gate) must be directly promotable through the
    Admin API without editing that file."""
    root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    root.mkdir()
    run_dir = _write_promotable_run(
        root, repo_root, "validate-stale-gate", "stale-gate-dataset", "release-20260811t214424z"
    )
    validation_result_path = run_dir / "validation-result.json"
    validation_result = json.loads(validation_result_path.read_text())
    assert validation_result["validation_outcome"] == "accepted"
    validation_result["promotion_gate"] = {"promotion_allowed": False, "registry_update_allowed": False}
    validation_result_path.write_text(json.dumps(validation_result), encoding="utf-8")

    original_root = admin_runs._admin_runs_root
    original_repo_root = admin_runs._REPO_ROOT
    try:
        admin_runs._admin_runs_root = lambda: root
        admin_runs._REPO_ROOT = repo_root
        result = admin_runs.promote_admin_run("validate-stale-gate")
    finally:
        admin_runs._admin_runs_root = original_root
        admin_runs._REPO_ROOT = original_repo_root

    assert result["promoted"] is True
    assert result["errors"] == []


def test_remove_admin_run_removes_an_unavailable_run_and_leaves_others_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_run_dir(root, "validate-unavailable", None, None)
        _write_run_dir(root, "validate-untouched", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
        original = admin_runs._admin_runs_root
        try:
            admin_runs._admin_runs_root = lambda: root
            listing_before = admin_runs.list_admin_run_summaries()
            unavailable_entry = next(e for e in listing_before["runs"] if e["run_id"] == "validate-unavailable")
            assert unavailable_entry["status"] == "unavailable"

            result = admin_runs.remove_admin_run("validate-unavailable")

            listing_after = admin_runs.list_admin_run_summaries()
        finally:
            admin_runs._admin_runs_root = original

        assert result == {"run_id": "validate-unavailable", "removed": True, "errors": []}
        remaining_run_ids = {e["run_id"] for e in listing_after["runs"]}
        assert remaining_run_ids == {"validate-untouched"}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
