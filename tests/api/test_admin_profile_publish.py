"""
Admin profile publish route tests for M36-03 validation evidence.

Exercises api/admin_profile_publish.py's publish_profile service function
and api/main.py's PUT /admin/datasets/{dataset_slug}/publish access-control
and behavior boundary. Tests use direct function/Request-object calls (no
httpx/TestClient dependency, matching tests/api/test_admin_profile_drafts.py)
and configure ADMIN_API_TOKEN and the persistence modules' repo_root
exclusively through monkeypatched module attributes or temporary
os.environ entries -- never through a .env file or the real repository's
registry/profile-drafts/ or registry/profile-snapshots/ directories.

Draft and snapshot persistence are isolated onto a fake repository root
(pytest tmp_path) with the real contracts/dataset-public-profile.schema.json,
contracts/dataset-public-profile-snapshot.schema.json, and
registry/evidence/dataset-public-profile-snapshot-evidence.schema.json
copied in, the same isolation convention
tests/registry/test_dataset_public_profile_snapshot_store.py uses for the
M36-03/M36-04 persistence modules directly -- the evidence schema is
required because publish_snapshot's M36-04 write_snapshot_evidence side
effect loads it unconditionally on every successful publish.

Run from the repository root:
    python -m pytest tests/api/test_admin_profile_publish.py -v
or directly:
    python tests/api/test_admin_profile_publish.py
"""

import functools
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

import admin_profile_publish  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.dataset_public_profile_store import create_draft as _real_create_draft  # noqa: E402
from registry.dataset_public_profile_snapshot_store import (  # noqa: E402
    publish_snapshot as _real_publish_snapshot,
)


def _make_request(
    headers: dict[str, str],
    method: str = "PUT",
    path: str = "/admin/datasets/example-dataset/publish",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _build_fake_repo(tmp_root: Path) -> Path:
    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile.schema.json",
        contracts_dir / "dataset-public-profile.schema.json",
    )
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile-snapshot.schema.json",
        contracts_dir / "dataset-public-profile-snapshot.schema.json",
    )

    registry_dir = tmp_root / "registry"
    registry_dir.mkdir(parents=True)

    evidence_schema_dir = registry_dir / "evidence"
    evidence_schema_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "registry" / "evidence" / "dataset-public-profile-snapshot-evidence.schema.json",
        evidence_schema_dir / "dataset-public-profile-snapshot-evidence.schema.json",
    )
    (registry_dir / "datasets.json").write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.registry.v1",
            "datasets": [
                {
                    "dataset_slug": "example-dataset",
                    "active_release": "release-20260101-001",
                    "public_metadata": {
                        "title": "Example Dataset",
                        "summary": "Test dataset for publish route tests.",
                        "domain": "generic",
                        "visibility": "public",
                        "tags": [],
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    metrics_dir = tmp_root / "releases" / "release-20260101-001" / "metrics"
    metrics_dir.mkdir(parents=True)
    metrics_dir.joinpath("metrics.json").write_text(
        json.dumps({
            "schema_version": "metrics.v1",
            "dataset_slug": "example-dataset",
            "release_id": "release-20260101-001",
            "evaluation": {"split": "test", "sample_size": 1, "metrics": {"accuracy": 1.0}},
        }),
        encoding="utf-8",
    )
    return tmp_root


def _install_isolated_publish(fake_repo: Path) -> object:
    original = admin_profile_publish.publish_snapshot
    admin_profile_publish.publish_snapshot = functools.partial(
        _real_publish_snapshot, repo_root=fake_repo
    )
    return original


def _restore_publish(original: object) -> None:
    admin_profile_publish.publish_snapshot = original


_VALID_PROFILE = {
    "schema_version": "0.1.0",
    "dataset_slug": "example-dataset",
}


# ---------------------------------------------------------------------------
# admin_profile_publish.publish_profile: direct calls
# ---------------------------------------------------------------------------


def test_publish_profile_rejects_when_no_draft_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            result = admin_profile_publish.publish_profile("example-dataset")
        finally:
            _restore_publish(original)

        assert result["published"] is False
        assert result["snapshot"] is None
        assert any(error["code"] == "NO_DRAFT_TO_PUBLISH" for error in result["errors"])


def test_publish_profile_succeeds_after_draft_saved():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        _real_create_draft("example-dataset", dict(_VALID_PROFILE), repo_root=fake_repo)
        original = _install_isolated_publish(fake_repo)
        try:
            result = admin_profile_publish.publish_profile("example-dataset")
        finally:
            _restore_publish(original)

        assert result["published"] is True
        assert result["errors"] == []
        assert result["snapshot"]["dataset_slug"] == "example-dataset"
        assert result["snapshot"]["active_release_at_publish_time"] == "release-20260101-001"


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/publish: access-control boundary
# ---------------------------------------------------------------------------


def test_publish_route_returns_generic_not_found_when_token_env_unset():
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({"X-Admin-Token": "irrelevant"})
    response = api_main.put_admin_profile_publish("example-dataset", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_publish_route_returns_generic_not_found_when_token_incorrect():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.put_admin_profile_publish("example-dataset", request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_returns_422_when_no_draft_exists_with_valid_token():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({"X-Admin-Token": "correct-token"})
            response = api_main.put_admin_profile_publish("example-dataset", request)
        finally:
            _restore_publish(original)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "PROFILE_PUBLISH_FAILED"
    assert body["errors"], "expected passthrough validation errors"


def test_publish_route_succeeds_after_draft_saved_with_valid_token():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        _real_create_draft("example-dataset", dict(_VALID_PROFILE), repo_root=fake_repo)
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({"X-Admin-Token": "correct-token"})
            response = api_main.put_admin_profile_publish("example-dataset", request)
        finally:
            _restore_publish(original)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response["published"] is True
    assert response["dataset_slug"] == "example-dataset"
    assert response["snapshot"]["dataset_slug"] == "example-dataset"


def test_publish_route_returns_422_for_invalid_dataset_slug():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request(
            {"X-Admin-Token": "correct-token"},
            path="/admin/datasets/Invalid Slug/publish",
        )
        response = api_main.put_admin_profile_publish("Invalid Slug", request)
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_PUBLISH_DATASET_SLUG_INVALID"
        )
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------


def test_publish_route_registered_only_under_admin_and_public_datasets_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/publish" in paths

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("publish" in path for path in public_paths)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
