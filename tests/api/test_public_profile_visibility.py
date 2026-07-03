"""
Public dataset visibility tests for M36-05.

Proves the off/on behavior of Visible Publicly for the two public dataset
routes in api/main.py (GET /datasets, GET /datasets/{dataset_slug}) and for
the new admin write route (PUT /admin/datasets/{dataset_slug}/visibility),
plus the underlying resolver (api/public_profile_visibility.py) and
persistence module (registry/dataset_public_profile_publication_store.py)
directly.

GET /datasets must exclude a hidden dataset entirely. GET /datasets/{slug}
must return, for a hidden dataset, a response byte-for-byte identical in
shape to the existing DATASET_NOT_FOUND response already used for a
dataset_slug that does not exist at all -- proving no information about a
hidden dataset's existence leaks publicly.

Route-level visibility filtering is isolated by monkeypatching the
module-level api_main.resolve_dataset_visibility and
api_main.set_dataset_visibility references directly (the same
module-attribute-replacement convention tests/api/test_admin_profile_publish.py
uses for admin_profile_publish.publish_snapshot), never by writing into the
real repository's registry/profile-publications/ directory. Persistence-layer
and resolver-layer tests isolate through the repo_root parameter onto a
temporary directory, mirroring
tests/api/test_public_profile_isolation.py's isolation convention.

Run from the repository root:
    python -m pytest tests/api/test_public_profile_visibility.py -v
or directly:
    python tests/api/test_public_profile_visibility.py
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

import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from public_profile_visibility import resolve_dataset_visibility  # noqa: E402
from registry.dataset_public_profile_publication_store import (  # noqa: E402
    get_visibility,
    set_visibility,
)

_SEEDED_DATASET_SLUGS = ["telco-customer-churn", "bank-marketing"]
_TARGET_SLUG = "telco-customer-churn"


def _make_request(
    headers: dict[str, str],
    method: str = "PUT",
    path: str = "/admin/datasets/telco-customer-churn/visibility",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _write_fake_snapshot(fake_repo: Path, dataset_slug: str) -> None:
    snapshots_dir = fake_repo / "registry" / "profile-snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    (snapshots_dir / f"{dataset_slug}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset_slug": dataset_slug,
                "published_at": "2026-07-01T00:00:00Z",
                "active_release_at_publish_time": "release-20260101-001",
                "profile": {},
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# registry.dataset_public_profile_publication_store: direct calls
# ---------------------------------------------------------------------------


def test_get_visibility_defaults_true_when_no_publication_record_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        assert get_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_set_visibility_then_get_visibility_reflects_false():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        record = set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        assert record["dataset_slug"] == _TARGET_SLUG
        assert record["visible"] is False
        assert get_visibility(_TARGET_SLUG, repo_root=fake_repo) is False


def test_set_visibility_then_get_visibility_reflects_true_again():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        set_visibility(_TARGET_SLUG, True, repo_root=fake_repo)
        assert get_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_set_visibility_rejects_invalid_dataset_slug():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        try:
            set_visibility("Invalid Slug", True, repo_root=fake_repo)
            raise AssertionError("expected ValueError for invalid dataset_slug")
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# api.public_profile_visibility.resolve_dataset_visibility: direct calls
# ---------------------------------------------------------------------------


def test_resolve_visibility_true_when_no_snapshot_exists_regardless_of_publication_record():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_resolve_visibility_true_when_snapshot_exists_and_no_publication_record():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_fake_snapshot(fake_repo, _TARGET_SLUG)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_resolve_visibility_false_when_snapshot_exists_and_hidden():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_fake_snapshot(fake_repo, _TARGET_SLUG)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is False


def test_resolve_visibility_true_when_snapshot_exists_and_explicitly_visible():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_fake_snapshot(fake_repo, _TARGET_SLUG)
        set_visibility(_TARGET_SLUG, True, repo_root=fake_repo)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


# ---------------------------------------------------------------------------
# GET /datasets and GET /datasets/{dataset_slug}: visibility off/on behavior
# ---------------------------------------------------------------------------


def test_list_datasets_endpoint_excludes_hidden_dataset():
    original = api_main.resolve_dataset_visibility
    api_main.resolve_dataset_visibility = lambda dataset_slug: dataset_slug != _TARGET_SLUG
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG not in slugs
    assert set(_SEEDED_DATASET_SLUGS) - {_TARGET_SLUG} <= slugs


def test_list_datasets_endpoint_includes_all_when_all_visible():
    original = api_main.resolve_dataset_visibility
    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert set(_SEEDED_DATASET_SLUGS) <= slugs


def test_get_dataset_returns_dataset_not_found_shape_when_hidden():
    original = api_main.resolve_dataset_visibility

    api_main.resolve_dataset_visibility = lambda dataset_slug: False
    try:
        hidden_response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original

    nonexistent_response = api_main.get_dataset("dataset-that-does-not-exist")

    assert hidden_response.status_code == nonexistent_response.status_code
    assert (
        json.loads(hidden_response.body.decode("utf-8"))
        == json.loads(nonexistent_response.body.decode("utf-8"))
    )


def test_get_dataset_returns_data_when_visible():
    original = api_main.resolve_dataset_visibility
    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    try:
        response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original

    assert response["dataset_slug"] == _TARGET_SLUG


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/visibility: access-control boundary
# ---------------------------------------------------------------------------


def test_visibility_route_returns_generic_not_found_when_token_env_unset():
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({"X-Admin-Token": "irrelevant"})
    response = api_main.put_admin_profile_visibility(
        _TARGET_SLUG, request, {"visible": False}
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_visibility_route_returns_generic_not_found_when_token_incorrect():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.put_admin_profile_visibility(
            _TARGET_SLUG, request, {"visible": False}
        )
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_returns_422_for_non_boolean_payload():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "correct-token"})
        response = api_main.put_admin_profile_visibility(
            _TARGET_SLUG, request, {"visible": "yes"}
        )
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_VISIBILITY_PAYLOAD_INVALID"
        )
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_returns_422_for_invalid_dataset_slug():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request(
            {"X-Admin-Token": "correct-token"},
            path="/admin/datasets/Invalid Slug/visibility",
        )
        response = api_main.put_admin_profile_visibility(
            "Invalid Slug", request, {"visible": False}
        )
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_VISIBILITY_DATASET_SLUG_INVALID"
        )
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_succeeds_with_valid_token_and_isolated_store():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    original = api_main.set_dataset_visibility
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        api_main.set_dataset_visibility = (
            lambda dataset_slug, visible: {
                **set_visibility(dataset_slug, visible, repo_root=fake_repo)
            }
        )
        try:
            request = _make_request({"X-Admin-Token": "correct-token"})
            response = api_main.put_admin_profile_visibility(
                _TARGET_SLUG, request, {"visible": False}
            )
        finally:
            api_main.set_dataset_visibility = original
            os.environ.pop("ADMIN_API_TOKEN", None)

        assert response["dataset_slug"] == _TARGET_SLUG
        assert response["visible"] is False
        assert get_visibility(_TARGET_SLUG, repo_root=fake_repo) is False


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------


def test_visibility_route_registered_only_under_admin():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/visibility" in paths

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("visibility" in path for path in public_paths)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
