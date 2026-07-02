"""
Admin run listing tests for M33-02 and M33-05 validation evidence.

Exercises api/admin_runs.py's safe run-summary derivation and api/main.py's
GET /admin/runs access-control boundary. Tests use direct function/module
calls (no httpx/TestClient dependency, matching tests/api/test_public_endpoints.py)
and configure ADMIN_RUNS_ROOT/ADMIN_API_TOKEN exclusively through monkeypatched
module attributes or temporary os.environ entries -- never through a .env file.

Run from the repository root:
    python -m pytest tests/api/test_admin_run_listing.py -v
or directly:
    python tests/api/test_admin_run_listing.py
"""

import json
import os
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
# GET /admin/runs: access-control boundary
# ---------------------------------------------------------------------------

def test_route_returns_generic_not_found_when_token_env_unset():
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({"X-Admin-Token": "irrelevant"})
    response = api_main.list_admin_runs(request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_route_returns_generic_not_found_when_header_missing():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({})
        response = api_main.list_admin_runs(request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_route_returns_generic_not_found_when_token_incorrect():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.list_admin_runs(request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_route_returns_listing_when_token_correct():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_dir(root, "validate-ok", _VALID_MANIFEST, _ACCEPTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_request({"X-Admin-Token": "correct-token"})
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
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


def test_route_listing_is_sanitized_even_when_source_contains_private_fields():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    original_root = admin_runs._admin_runs_root
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = json.loads(json.dumps(_VALID_MANIFEST))
            manifest["private_file"] = "/private/generated-runs/validate-route/manifest.json"
            manifest["secret"] = "secret-token-value"
            _write_run_dir(root, "validate-route", manifest, _REJECTED_VALIDATION_RESULT)
            admin_runs._admin_runs_root = lambda: root
            request = _make_request({"X-Admin-Token": "correct-token"})
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
        os.environ.pop("ADMIN_API_TOKEN", None)
        admin_runs._admin_runs_root = original_root


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

    dataset_paths = {path for path in paths if path.startswith("/datasets")}
    assert dataset_paths == _EXPECTED_PUBLIC_DATASET_PATHS

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("runs" in path for path in public_paths)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
