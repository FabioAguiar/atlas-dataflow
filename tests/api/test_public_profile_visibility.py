"""
Public dataset visibility tests for M36-05.

Proves the off/on behavior of Visible Publicly for the two public dataset
routes in api/main.py (GET /datasets, GET /datasets/{dataset_slug}) and for
the new admin write route (PUT /admin/datasets/{dataset_slug}/visibility),
plus the underlying resolver (api/public_profile_visibility.py) and
persistence module (registry/dataset_public_profile_publication_store.py)
directly.

GET /datasets must exclude a hidden dataset entirely. GET /datasets/{slug}
must return, for a hidden dataset, the generic DATASET_MAINTENANCE response
(Project Spec S0117) -- distinct from DATASET_NOT_FOUND, which remains
reserved for a dataset_slug that does not exist at all -- proving no
information about a hidden dataset's existence or reason leaks publicly.

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
from types import SimpleNamespace

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
import admin_profile_visibility  # noqa: E402
from fastapi import Request  # noqa: E402
from public_context_loader import PublicContextUnavailableError  # noqa: E402
from public_errors import DATASET_MAINTENANCE  # noqa: E402
from public_predict_view_loader import ViewNotFoundError  # noqa: E402
from public_profile_visibility import (  # noqa: E402
    resolve_dataset_visibility,
    resolve_public_dataset_access,
    resolve_public_presentation_overlay,
)
from registry.dataset_public_profile_publication_store import (  # noqa: E402
    get_visibility_record,
    get_visibility,
    set_visibility,
)
from registry.list import ListedDataset, _snapshot_overlay_fields, is_dataset_needs_review  # noqa: E402
from registry.resolve import DatasetUnavailableError, RegistryInvalidError, ReleaseUnavailableError  # noqa: E402

_SEEDED_DATASET_SLUGS = ["telco-customer-churn", "bank-marketing"]
_TARGET_SLUG = "telco-customer-churn"

# Project Spec S0054: bank-marketing is no longer a required real-registry
# entry. Multi-dataset listing coverage for the /datasets endpoint is proven
# with a fixture-local list_datasets() override instead of depending on the
# live registry/datasets.json containing a second seeded dataset.
_FIXTURE_LISTED_DATASETS = [
    ListedDataset(
        dataset_slug="telco-customer-churn",
        title="Telco Customer Churn",
        summary="Customer churn prediction dataset.",
        domain="telco",
        visibility="public",
        tags=["telco"],
    ),
    ListedDataset(
        dataset_slug="bank-marketing",
        title="Bank Marketing",
        summary="Fixture bank marketing dataset for multi-dataset listing coverage.",
        domain="banking-marketing",
        visibility="public",
        tags=["banking"],
    ),
]


def _fixture_two_dataset_listing():
    return list(_FIXTURE_LISTED_DATASETS)


def _fixture_resolve_dataset(dataset_slug):
    return SimpleNamespace(dataset_slug=dataset_slug, active_release="release-fixture-001")


def _make_fixture_publicly_eligible(monkeypatch) -> None:
    """Isolate success paths from every real public eligibility gate."""
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)


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


def _write_publication_content(fake_repo: Path, content: str) -> Path:
    publications = fake_repo / "registry" / "profile-publications"
    publications.mkdir(parents=True, exist_ok=True)
    path = publications / f"{_TARGET_SLUG}.json"
    path.write_text(content, encoding="utf-8")
    return path


def test_visibility_record_reader_projects_valid_explicit_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        record = set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        state = get_visibility_record(_TARGET_SLUG, repo_root=fake_repo)
        assert state == {
            "visible": False,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": record["updated_at"],
        }


def test_visibility_record_reader_classifies_missing_without_creating_directory():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        state = get_visibility_record(_TARGET_SLUG, repo_root=fake_repo)
        assert state["record_status"] == "missing"
        assert state["source"] == "default_visible"
        assert not (fake_repo / "registry" / "profile-publications").exists()


def test_visibility_record_reader_classifies_malformed_states():
    cases = [
        ("not json", "invalid_json"),
        (json.dumps([]), "invalid_shape"),
        (json.dumps({"visible": "yes", "updated_at": "2026-07-16T21:00:00Z"}), "invalid_visible"),
        (json.dumps({"visible": False, "updated_at": "yesterday"}), "invalid_updated_at"),
    ]
    for content, expected in cases:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp)
            _write_publication_content(fake_repo, content)
            state = get_visibility_record(_TARGET_SLUG, repo_root=fake_repo)
            assert state == {
                "visible": True,
                "source": "default_visible",
                "record_status": expected,
                "updated_at": None,
            }


def test_visibility_record_reader_classifies_unreadable_record():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        path = fake_repo / "registry" / "profile-publications" / f"{_TARGET_SLUG}.json"
        path.mkdir(parents=True)
        assert get_visibility_record(_TARGET_SLUG, repo_root=fake_repo)["record_status"] == "unreadable"


# ---------------------------------------------------------------------------
# api.public_profile_visibility.resolve_dataset_visibility: direct calls
# ---------------------------------------------------------------------------


def test_resolve_visibility_false_when_hidden_and_no_snapshot_exists():
    """
    Project Spec S0117: an explicit hidden ("visible": false) publication
    preference is effective even when no published snapshot exists yet.
    Snapshot absence no longer overrides explicit configured visibility --
    this replaces the pre-S0117 "always visible when no snapshot" behavior.
    """
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is False


def test_resolve_visibility_true_when_explicitly_visible_and_no_snapshot_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, True, repo_root=fake_repo)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_resolve_visibility_true_when_no_publication_record_and_no_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        assert resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo) is True


def test_resolve_visibility_performs_no_write():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        resolve_dataset_visibility(_TARGET_SLUG, repo_root=fake_repo)
        assert not (fake_repo / "registry" / "profile-publications").exists()
        assert not (fake_repo / "registry" / "profile-snapshots").exists()


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
# api.public_profile_visibility.resolve_public_dataset_access: the shared
# bounded public-access resolver combining resolve_dataset_visibility with
# not is_dataset_needs_review. Project Spec S0117.
# ---------------------------------------------------------------------------


def test_resolve_public_dataset_access_ready_when_visible_and_not_needs_review():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        registry_path = fake_repo / "registry" / "datasets.json"
        assert (
            resolve_public_dataset_access(_TARGET_SLUG, repo_root=fake_repo, registry_path=registry_path)
            == "ready"
        )


def test_resolve_public_dataset_access_maintenance_when_hidden():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        registry_path = fake_repo / "registry" / "datasets.json"
        assert (
            resolve_public_dataset_access(_TARGET_SLUG, repo_root=fake_repo, registry_path=registry_path)
            == "maintenance"
        )


def test_resolve_public_dataset_access_maintenance_when_needs_review():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_registry_with_review_status(fake_repo, _TARGET_SLUG, "needs_review")
        registry_path = fake_repo / "registry" / "datasets.json"
        assert (
            resolve_public_dataset_access(_TARGET_SLUG, repo_root=fake_repo, registry_path=registry_path)
            == "maintenance"
        )


def test_resolve_public_dataset_access_maintenance_when_both_hidden_and_needs_review():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        set_visibility(_TARGET_SLUG, False, repo_root=fake_repo)
        _write_registry_with_review_status(fake_repo, _TARGET_SLUG, "needs_review")
        registry_path = fake_repo / "registry" / "datasets.json"
        assert (
            resolve_public_dataset_access(_TARGET_SLUG, repo_root=fake_repo, registry_path=registry_path)
            == "maintenance"
        )


# ---------------------------------------------------------------------------
# GET /datasets and GET /datasets/{dataset_slug}: visibility off/on behavior
# ---------------------------------------------------------------------------


def test_list_datasets_endpoint_excludes_hidden_dataset():
    original_visibility = api_main.resolve_dataset_visibility
    original_list_datasets = api_main.list_datasets
    api_main.resolve_dataset_visibility = lambda dataset_slug: dataset_slug != _TARGET_SLUG
    api_main.list_datasets = _fixture_two_dataset_listing
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.list_datasets = original_list_datasets

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG not in slugs
    assert set(_SEEDED_DATASET_SLUGS) - {_TARGET_SLUG} <= slugs


def test_list_datasets_endpoint_includes_all_when_all_visible(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_list_datasets = api_main.list_datasets
    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.list_datasets = _fixture_two_dataset_listing
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.list_datasets = original_list_datasets

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert set(_SEEDED_DATASET_SLUGS) <= slugs


def test_get_dataset_returns_dataset_maintenance_when_hidden(monkeypatch):
    """
    Project Spec S0117: a registered dataset that is hidden now returns the
    generic DATASET_MAINTENANCE response, distinct from DATASET_NOT_FOUND
    (previously a hidden dataset was made byte-for-byte identical to an
    unknown one; that boundary now lives on DATASET_MAINTENANCE instead).
    """
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: False)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)

    hidden_response = api_main.get_dataset(_TARGET_SLUG)

    assert hidden_response.status_code == 503
    hidden_payload = json.loads(hidden_response.body.decode("utf-8"))
    assert hidden_payload["error_code"] == "DATASET_MAINTENANCE"
    assert hidden_payload["error_type"] == "dataset_maintenance"
    assert _TARGET_SLUG not in json.dumps(hidden_payload)


def test_get_dataset_returns_dataset_not_found_for_unknown_slug():
    nonexistent_response = api_main.get_dataset("dataset-that-does-not-exist")
    assert nonexistent_response.status_code == 404
    assert json.loads(nonexistent_response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"


def test_get_dataset_returns_data_when_visible(monkeypatch):
    _make_fixture_publicly_eligible(monkeypatch)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    response = api_main.get_dataset(_TARGET_SLUG)

    assert response["dataset_slug"] == _TARGET_SLUG


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/visibility: access-control boundary
# ---------------------------------------------------------------------------


def test_visibility_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({})
    response = api_main.put_admin_profile_visibility(
        _TARGET_SLUG, request, {"visible": False}
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_visibility_route_returns_generic_not_found_when_admin_runtime_false_even_with_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.put_admin_profile_visibility(
            _TARGET_SLUG, request, {"visible": False}
        )
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_returns_422_for_non_boolean_payload():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    try:
        request = _make_request({})
        response = api_main.put_admin_profile_visibility(
            _TARGET_SLUG, request, {"visible": "yes"}
        )
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_VISIBILITY_PAYLOAD_INVALID"
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_returns_422_for_invalid_dataset_slug():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    try:
        request = _make_request(
            {},
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
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_visibility_route_succeeds_in_private_runtime_without_token_header_and_isolated_store():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    original = api_main.set_dataset_visibility
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        api_main.set_dataset_visibility = (
            lambda dataset_slug, visible: {
                **set_visibility(dataset_slug, visible, repo_root=fake_repo)
            }
        )
        try:
            request = _make_request({})
            response = api_main.put_admin_profile_visibility(
                _TARGET_SLUG, request, {"visible": False}
            )
        finally:
            api_main.set_dataset_visibility = original
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
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


# ---------------------------------------------------------------------------
# S0115 private publication-state projection
# ---------------------------------------------------------------------------


def _publication_state_dependencies(monkeypatch, *, configured, effective, review, snapshot):
    monkeypatch.setattr(
        admin_profile_visibility,
        "resolve_dataset",
        lambda _slug, registry_path=None: SimpleNamespace(
            dataset_slug=_TARGET_SLUG, active_release="release-20260716-001"
        ),
    )
    monkeypatch.setattr(
        admin_profile_visibility,
        "get_visibility_record",
        lambda _slug, repo_root=None: configured,
    )
    monkeypatch.setattr(
        admin_profile_visibility,
        "resolve_dataset_visibility",
        lambda _slug, repo_root=None: effective,
    )
    monkeypatch.setattr(
        admin_profile_visibility,
        "is_dataset_needs_review",
        lambda _slug, registry_path=None: review,
    )
    if snapshot is None:
        def missing(_slug, repo_root=None):
            from registry.dataset_public_profile_snapshot_store import SnapshotNotFoundError
            raise SnapshotNotFoundError()
        monkeypatch.setattr(admin_profile_visibility, "get_snapshot", missing)
    else:
        monkeypatch.setattr(
            admin_profile_visibility, "get_snapshot", lambda _slug, repo_root=None: snapshot
        )


def test_publication_state_projects_current_snapshot_and_reachable(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=True,
        review=False,
        snapshot={
            "dataset_slug": _TARGET_SLUG,
            "published_at": "2026-07-16T20:30:00Z",
            "active_release_at_publish_time": "release-20260716-001",
        },
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["snapshot"]["status"] == "current_release"
    assert state["public_access"] == {"reachable": True, "blockers": [], "observations": []}


def test_publication_state_hidden_no_snapshot_is_unreachable(monkeypatch):
    """
    Project Spec S0117: resolve_dataset_visibility() no longer treats a
    missing snapshot as an override of an explicit configured-hidden
    preference, so this state is now unreachable -- the prior
    "configured_hidden_but_effectively_visible_without_snapshot"
    discrepancy can no longer occur and is absent from observations.
    snapshot_missing remains a non-blocking observation on its own.
    """
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": False,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=False,
        review=False,
        snapshot=None,
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["visibility"]["effective_visible"] is False
    assert state["public_access"]["reachable"] is False
    assert state["public_access"]["blockers"] == ["visibility_disabled"]
    assert state["public_access"]["observations"] == ["snapshot_missing"]
    assert "configured_hidden_but_effectively_visible_without_snapshot" not in state["public_access"]["observations"]


def test_publication_state_integration_hidden_no_snapshot_real_functions(monkeypatch, tmp_path):
    """
    End-to-end proof, without mocking resolve_dataset_visibility or
    get_visibility_record, that the real store/resolver chain agrees:
    configured hidden + missing snapshot is genuinely unreachable.
    """
    set_visibility(_TARGET_SLUG, False, repo_root=tmp_path)

    monkeypatch.setattr(
        admin_profile_visibility,
        "resolve_dataset",
        lambda _slug, registry_path=None: SimpleNamespace(
            dataset_slug=_TARGET_SLUG, active_release="release-20260716-001"
        ),
    )
    monkeypatch.setattr(admin_profile_visibility, "is_dataset_needs_review", lambda _slug, registry_path=None: False)

    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG, repo_root=tmp_path)

    assert state["visibility"]["effective_visible"] is False
    assert state["public_access"]["reachable"] is False
    assert "visibility_disabled" in state["public_access"]["blockers"]
    assert "snapshot_missing" in state["public_access"]["observations"]
    assert "configured_hidden_but_effectively_visible_without_snapshot" not in state["public_access"]["observations"]


def test_publication_state_integration_visible_no_snapshot_is_reachable(monkeypatch, tmp_path):
    set_visibility(_TARGET_SLUG, True, repo_root=tmp_path)

    monkeypatch.setattr(
        admin_profile_visibility,
        "resolve_dataset",
        lambda _slug, registry_path=None: SimpleNamespace(
            dataset_slug=_TARGET_SLUG, active_release="release-20260716-001"
        ),
    )
    monkeypatch.setattr(admin_profile_visibility, "is_dataset_needs_review", lambda _slug, registry_path=None: False)

    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG, repo_root=tmp_path)

    assert state["public_access"]["reachable"] is True
    assert state["public_access"]["blockers"] == []


def test_publication_state_has_deterministic_blockers_and_observations(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "default_visible",
            "record_status": "invalid_json",
            "updated_at": None,
        },
        effective=False,
        review=True,
        snapshot={
            "dataset_slug": _TARGET_SLUG,
            "published_at": "2026-07-16T20:30:00Z",
            "active_release_at_publish_time": "release-20260715-001",
        },
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["snapshot"]["status"] == "stale_release"
    assert state["public_access"] == {
        "reachable": False,
        "blockers": ["visibility_disabled", "review_pending"],
        "observations": [
            "visibility_default_applied",
            "visibility_record_invalid",
            "snapshot_stale",
        ],
    }


def test_publication_state_projects_invalid_snapshot_without_raw_content(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=True,
        review=False,
        snapshot={"dataset_slug": _TARGET_SLUG, "published_at": "bad", "profile": {"private": True}},
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["snapshot"] == {
        "status": "invalid",
        "exists": True,
        "published_at": None,
        "active_release_at_publish_time": None,
        "matches_active_release": None,
    }
    assert "profile" not in json.dumps(state)


def test_publication_state_route_is_private_and_registered(monkeypatch):
    path = "/admin/datasets/{dataset_slug}/publication-state"
    assert path in {route.path for route in api_main.app.routes}
    assert not any(
        route.path.endswith("/publication-state") and not route.path.startswith("/admin/")
        for route in api_main.app.routes
    )

    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    response = api_main.get_admin_profile_publication_state(
        _TARGET_SLUG, _make_request({}, method="GET", path=path)
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}

    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    monkeypatch.setattr(api_main, "get_dataset_publication_state", lambda slug: {"dataset_slug": slug})
    try:
        assert api_main.get_admin_profile_publication_state(
            _TARGET_SLUG, _make_request({}, method="GET", path=path)
        ) == {"dataset_slug": _TARGET_SLUG}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


# ---------------------------------------------------------------------------
# M39-04: GET /datasets/{dataset_slug}/context visibility gate (net-new;
# this route previously performed no visibility check at all) and curated
# presentation-field overlay for GET /datasets, GET /datasets/{dataset_slug},
# and GET /datasets/{dataset_slug}/context.
# ---------------------------------------------------------------------------

_FAKE_CONTEXT = {"title": "Fake Title", "summary": "Fake summary."}
_EMPTY_OVERLAY = {
    "display_title": None,
    "display_subtitle": None,
    "home_card_icon": None,
    "short_description": None,
    "theme_preset": None,
    "home_card_media_ref": None,
}
_CURATED_OVERLAY = {
    "display_title": "Curated Title",
    "display_subtitle": "Curated subtitle.",
    "home_card_icon": "bank",
    "short_description": "Curated short description.",
    "theme_preset": "atlas-green",
    "home_card_media_ref": None,
}
# M39-03: resolve_public_presentation_overlay's return shape is a superset of
# registry/list.py's own, separate _snapshot_overlay_fields (unchanged by this
# issue) -- these two constants must not be reused for that function's
# assertions above, since equality would otherwise fail once the extra keys
# are added.
_EMPTY_PUBLIC_PROFILE_OVERLAY = {
    **_EMPTY_OVERLAY,
    "home_card_media_ref": None,
    "problem_summary_title": None,
    "problem_summary_body": None,
    "canonical_name_fallback": None,
    "source_name": None,
    "source_url": None,
    "release_date_label": None,
    "date_format": None,
    "primary_metric_key": None,
    "performance_focus": None,
    "bound_predict_view_id": None,
    "legacy_submit_button_label": None,
    "result_card": {
        "schema_version": "binary-result-presentation.v1",
        "positive_class_probability_label": "Positive class probability",
        "predicted_outcome_label": "Predicted outcome",
        "positive_outcome_copy": "Positive outcome",
        "negative_outcome_copy": "Negative outcome",
        "model_section_label": "Model",
        "interpretation": {
            "preset": "risk",
            "labels": {"high": "High", "medium": "Medium", "low": "Low"},
        },
    },
}
_CURATED_PUBLIC_PROFILE_OVERLAY = {
    **_CURATED_OVERLAY,
    "home_card_media_ref": None,
    "problem_summary_title": "Why this matters",
    "problem_summary_body": "Curated public problem summary.",
    "canonical_name_fallback": False,
    "source_name": "Original Source Org",
    "source_url": "https://example.org/dataset",
    "release_date_label": "01/07/2026",
    "date_format": "dd/mm/yyyy",
    "primary_metric_key": "precision",
    "performance_focus": {
        "focus_id": "positive_class_detection",
        "highlighted_score_id": "recall",
        "visible_scores": [
            {"score_id": "recall", "display_label": "Recall", "value": "0.574", "value_source": "manual", "order": 0}
        ],
    },
    "bound_predict_view_id": "churn-risk-overview",
    "legacy_submit_button_label": "Run Prediction",
    "result_card": _EMPTY_PUBLIC_PROFILE_OVERLAY["result_card"],
}


def test_get_public_context_returns_dataset_maintenance_when_hidden(monkeypatch):
    """
    Project Spec S0117: GET /datasets/{slug}/context is now guarded by the
    same shared access resolver as every other Dataset Detail route -- a
    hidden dataset returns DATASET_MAINTENANCE, not DATASET_NOT_FOUND.
    """
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: False)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)

    hidden_response = api_main.get_public_context(_TARGET_SLUG)

    assert hidden_response.status_code == 503
    assert json.loads(hidden_response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_get_public_context_returns_dataset_maintenance_when_needs_review(monkeypatch):
    """
    Project Spec S0117: prior to this spec, GET /datasets/{slug}/context
    performed no needs_review check at all. The shared guard now enforces
    it here too.
    """
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: True)

    response = api_main.get_public_context(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_get_public_context_returns_dataset_not_found_for_unknown_slug():
    nonexistent_response = api_main.get_public_context("dataset-that-does-not-exist")
    assert nonexistent_response.status_code == 404
    assert json.loads(nonexistent_response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"


def test_get_public_context_returns_context_when_visible(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_resolve_dataset = api_main.resolve_dataset
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.resolve_dataset = _fixture_resolve_dataset
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug: dict(_EMPTY_PUBLIC_PROFILE_OVERLAY)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)
    try:
        response = api_main.get_public_context(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.resolve_dataset = original_resolve_dataset
        monkeypatch.undo()
        api_main.load_public_context = original_loader
        api_main.resolve_public_presentation_overlay = original_overlay

    assert response["dataset_slug"] == _TARGET_SLUG
    assert response["context"]["title"] == "Fake Title"
    assert response["context"]["summary"] == "Fake summary."


def test_get_public_context_overlay_fields_none_when_no_snapshot_published(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug: dict(_EMPTY_PUBLIC_PROFILE_OVERLAY)
    try:
        response = api_main.get_public_context(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_loader
        api_main.resolve_public_presentation_overlay = original_overlay

    context = response["context"]
    assert context["display_title"] is None
    assert context["display_subtitle"] is None
    assert context["problem_summary_title"] is None
    assert context["problem_summary_body"] is None
    assert context["canonical_name_fallback"] is None
    assert context["home_card_icon"] is None
    assert context["short_description"] is None
    assert context["theme_preset"] is None
    assert context["source_name"] is None
    assert context["source_url"] is None
    assert context["release_date_label"] is None
    assert context["date_format"] is None
    assert context["primary_metric_key"] is None
    assert context["performance_focus"] is None
    # Base release-context fields are preserved unchanged alongside the overlay.
    assert context["title"] == "Fake Title"
    assert context["summary"] == "Fake summary."


def test_get_public_context_includes_curated_overlay_fields_when_published(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug: dict(_CURATED_PUBLIC_PROFILE_OVERLAY)
    try:
        response = api_main.get_public_context(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_loader
        api_main.resolve_public_presentation_overlay = original_overlay

    context = response["context"]
    assert context["display_title"] == "Curated Title"
    assert context["display_subtitle"] == "Curated subtitle."
    assert context["problem_summary_title"] == "Why this matters"
    assert context["problem_summary_body"] == "Curated public problem summary."
    assert context["canonical_name_fallback"] is False
    assert context["home_card_icon"] == "bank"
    assert context["short_description"] == "Curated short description."
    assert context["theme_preset"] == "atlas-green"
    assert context["source_name"] == "Original Source Org"
    assert context["source_url"] == "https://example.org/dataset"
    assert context["release_date_label"] == "01/07/2026"
    assert context["date_format"] == "dd/mm/yyyy"
    assert context["primary_metric_key"] == "precision"
    assert context["performance_focus"] == _CURATED_PUBLIC_PROFILE_OVERLAY["performance_focus"]
    # Base release-context fields survive the overlay merge unchanged.
    assert context["title"] == "Fake Title"
    assert context["summary"] == "Fake summary."


# ---------------------------------------------------------------------------
# registry.list._snapshot_overlay_fields and
# public_profile_visibility.resolve_public_presentation_overlay: direct,
# repo_root-isolated calls proving the overlay is sourced exclusively from
# the published snapshot store, never from the private draft store.
# ---------------------------------------------------------------------------


def test_snapshot_overlay_fields_all_none_when_no_snapshot_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == _EMPTY_OVERLAY
        assert resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo) == _EMPTY_PUBLIC_PROFILE_OVERLAY


def test_snapshot_overlay_fields_all_none_when_only_an_unpublished_draft_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        drafts_dir = fake_repo / "registry" / "profile-drafts"
        drafts_dir.mkdir(parents=True)
        (drafts_dir / f"{_TARGET_SLUG}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "display": {"title": "Private Draft Title Never Public"},
                    "home_card": {"icon": "bank", "short_description": "Private draft description."},
                }
            ),
            encoding="utf-8",
        )

        # No snapshot has been published (registry/profile-snapshots/ does
        # not exist), so the overlay must be all-None: an unpublished draft
        # is never reachable through this read path, regardless of its
        # content, because it is never read at all (registry/list.py and
        # public_profile_visibility.py only ever call get_snapshot).
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == _EMPTY_OVERLAY
        assert resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo) == _EMPTY_PUBLIC_PROFILE_OVERLAY


def test_snapshot_overlay_fields_returns_curated_values_when_snapshot_published():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        snapshots_dir = fake_repo / "registry" / "profile-snapshots"
        snapshots_dir.mkdir(parents=True)
        (snapshots_dir / f"{_TARGET_SLUG}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "dataset_slug": _TARGET_SLUG,
                    "published_at": "2026-07-01T00:00:00Z",
                    "active_release_at_publish_time": "release-20260101-001",
                    "profile": {
                        "display": {
                            "title": "Curated Title",
                            "subtitle": "Curated subtitle.",
                            "problem_summary_title": "Why this matters",
                            "problem_summary_body": "Curated public problem summary.",
                            "canonical_name_fallback": False,
                            "source_name": "Original Source Org",
                            "source_url": "https://example.org/dataset",
                            "release_date_label": "01/07/2026",
                            "date_format": "dd/mm/yyyy",
                        },
                        "home_card": {
                            "icon": "bank",
                            "short_description": "Curated short description.",
                            "primary_metric_key": "precision",
                        },
                        "theme": {"preset": "atlas-green"},
                        "performance_focus": _CURATED_PUBLIC_PROFILE_OVERLAY["performance_focus"],
                        "inference_presentation": {
                            "bound_predict_view_id": _CURATED_PUBLIC_PROFILE_OVERLAY["bound_predict_view_id"],
                        },
                        "result_card": {
                            "submit_button_label": _CURATED_PUBLIC_PROFILE_OVERLAY["legacy_submit_button_label"],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        # registry/list.py's _snapshot_overlay_fields is unchanged by this
        # issue and only ever reads its own five known keys, so it must still
        # return exactly _CURATED_OVERLAY even though the snapshot on disk
        # now also carries the five new public-profile fields.
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == dict(_CURATED_OVERLAY)
        assert resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo) == dict(
            _CURATED_PUBLIC_PROFILE_OVERLAY
        )


def test_public_presentation_overlay_treats_malformed_display_as_missing():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        snapshots_dir = fake_repo / "registry" / "profile-snapshots"
        snapshots_dir.mkdir(parents=True)
        (snapshots_dir / f"{_TARGET_SLUG}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "dataset_slug": _TARGET_SLUG,
                    "published_at": "2026-07-01T00:00:00Z",
                    "active_release_at_publish_time": "release-20260101-001",
                    "profile": {"display": ["not", "an", "object"]},
                }
            ),
            encoding="utf-8",
        )

        overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
        assert overlay["problem_summary_title"] is None
        assert overlay["problem_summary_body"] is None
        assert overlay["canonical_name_fallback"] is None


# ---------------------------------------------------------------------------
# problem_type resolution for M39-02: GET /datasets and GET /datasets/{slug}
# must include a real, fail-open problem_type sourced from each dataset's
# active-release public context (api/public_context_loader.py), the same
# source GET /datasets/{slug}/context already uses. Unlike the M39-04 overlay
# fields above (which come from the published snapshot store), problem_type
# has no snapshot-path equivalent, so it is resolved directly in api/main.py's
# _resolve_problem_type helper.
# ---------------------------------------------------------------------------


def test_resolve_problem_type_returns_value_when_context_available(monkeypatch):
    original_load_public_context = api_main.load_public_context
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    api_main.load_public_context = lambda active_release: {"problem_type": "binary_classification"}
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) == "binary_classification"
    finally:
        api_main.load_public_context = original_load_public_context


def test_resolve_problem_type_none_when_context_unavailable():
    original_load_public_context = api_main.load_public_context

    def raise_context_unavailable(_active_release):
        raise PublicContextUnavailableError("unavailable")

    api_main.load_public_context = raise_context_unavailable
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) is None
    finally:
        api_main.load_public_context = original_load_public_context


def test_resolve_problem_type_none_when_dataset_unknown():
    assert api_main._resolve_problem_type("dataset-that-does-not-exist") is None


def test_resolve_problem_type_none_when_release_unavailable():
    original_resolve_dataset = api_main.resolve_dataset

    def raise_release_unavailable(_dataset_slug):
        raise ReleaseUnavailableError("missing release")

    api_main.resolve_dataset = raise_release_unavailable
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) is None
    finally:
        api_main.resolve_dataset = original_resolve_dataset


def test_resolve_problem_type_none_when_value_not_a_string():
    original_load_public_context = api_main.load_public_context
    api_main.load_public_context = lambda active_release: {"problem_type": 123}
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) is None
    finally:
        api_main.load_public_context = original_load_public_context


def test_list_datasets_endpoint_includes_problem_type_for_every_visible_dataset(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_load_public_context = api_main.load_public_context
    original_list_datasets = api_main.list_datasets
    original_resolve_dataset = api_main.resolve_dataset

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.load_public_context = lambda active_release: {"problem_type": "binary_classification"}
    api_main.list_datasets = _fixture_two_dataset_listing
    api_main.resolve_dataset = _fixture_resolve_dataset
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_load_public_context
        api_main.list_datasets = original_list_datasets
        api_main.resolve_dataset = original_resolve_dataset

    assert set(_SEEDED_DATASET_SLUGS) <= {entry["dataset_slug"] for entry in response["datasets"]}
    for entry in response["datasets"]:
        assert entry["problem_type"] == "binary_classification"


def test_list_datasets_endpoint_problem_type_fails_open_per_dataset_without_excluding_it(monkeypatch):
    """
    One dataset's release/context lookup failing must not exclude it from the
    listing -- only that dataset's own problem_type resolves to None, and
    every other dataset in the same listing call is unaffected.
    """
    original_visibility = api_main.resolve_dataset_visibility
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    original_list_datasets = api_main.list_datasets

    def fake_resolve_dataset(dataset_slug):
        return SimpleNamespace(dataset_slug=dataset_slug, active_release="release-fake-001")

    def fake_load_public_context(active_release):
        raise PublicContextUnavailableError("unavailable")

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.resolve_dataset = fake_resolve_dataset
    api_main.load_public_context = fake_load_public_context
    api_main.list_datasets = _fixture_two_dataset_listing
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_context = original_load_public_context
        api_main.list_datasets = original_list_datasets

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert set(_SEEDED_DATASET_SLUGS) <= slugs
    for entry in response["datasets"]:
        assert entry["problem_type"] is None


def test_get_dataset_includes_problem_type_when_available(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_load_public_context = api_main.load_public_context

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    api_main.load_public_context = lambda active_release: {"problem_type": "regression"}
    try:
        response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_load_public_context

    assert response["problem_type"] == "regression"


# ---------------------------------------------------------------------------
# Project Spec S0052: promoted Dataset Details default to draft/Needs review
# and must never be publicly reachable through GET /datasets or
# GET /datasets/{dataset_slug} until explicitly published/reviewed. This is a
# distinct gate from Visible Publicly above -- a dataset can be
# resolve_dataset_visibility() == True (no snapshot yet, default-visible)
# and still be excluded here because it is_dataset_needs_review() == True.
# ---------------------------------------------------------------------------


def _write_registry_with_review_status(fake_repo: Path, dataset_slug: str, review_status: str | None) -> None:
    registry_dir = fake_repo / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset_slug": dataset_slug,
        "active_release": "release-20260701-001",
        "public_metadata": {
            "title": "Fixture Dataset",
            "summary": "Fixture.",
            "domain": "general",
            "visibility": "public",
            "tags": [],
        },
    }
    if review_status is not None:
        entry["review_status"] = review_status
    (registry_dir / "datasets.json").write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.registry.v1",
                "conventions": {
                    "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                    "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                    "active_release": {"description": "x"},
                },
                "datasets": [entry],
            }
        ),
        encoding="utf-8",
    )


def test_is_dataset_needs_review_true_when_entry_marked_needs_review():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_registry_with_review_status(fake_repo, _TARGET_SLUG, "needs_review")
        registry_path = fake_repo / "registry" / "datasets.json"
        assert is_dataset_needs_review(_TARGET_SLUG, registry_path=registry_path) is True


def test_is_dataset_needs_review_false_when_entry_has_no_review_status_field():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_registry_with_review_status(fake_repo, _TARGET_SLUG, None)
        registry_path = fake_repo / "registry" / "datasets.json"
        assert is_dataset_needs_review(_TARGET_SLUG, registry_path=registry_path) is False


def test_is_dataset_needs_review_false_when_entry_explicitly_ready():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_registry_with_review_status(fake_repo, _TARGET_SLUG, "ready")
        registry_path = fake_repo / "registry" / "datasets.json"
        assert is_dataset_needs_review(_TARGET_SLUG, registry_path=registry_path) is False


def test_list_datasets_endpoint_excludes_needs_review_dataset_even_when_visible():
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    # Visible Publicly is True for every dataset (the pre-existing
    # default-visible-when-no-snapshot behavior); the needs_review gate must
    # independently exclude the target regardless.
    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: dataset_slug == _TARGET_SLUG
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG not in slugs


def test_list_datasets_endpoint_includes_dataset_when_not_needs_review(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: False
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG in slugs


def test_get_dataset_returns_dataset_maintenance_when_needs_review(monkeypatch):
    """
    Project Spec S0117: a needs_review dataset now returns the same generic
    DATASET_MAINTENANCE response as a hidden dataset -- the public wire
    response never distinguishes which of the two conditions applies.
    """
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: True)

    needs_review_response = api_main.get_dataset(_TARGET_SLUG)

    assert needs_review_response.status_code == 503
    payload = json.loads(needs_review_response.body.decode("utf-8"))
    assert payload["error_code"] == "DATASET_MAINTENANCE"


def test_get_dataset_returns_data_when_visible_and_not_needs_review(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: False
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    try:
        response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    assert response["dataset_slug"] == _TARGET_SLUG


# ---------------------------------------------------------------------------
# Project Spec S0117: the public error contract, the shared route-level
# access guard (api/main.py's _resolve_public_dataset_detail_access), and
# the uniform boundary/precedence rules it enforces across every guarded
# public Dataset Detail route.
# ---------------------------------------------------------------------------


def test_dataset_maintenance_error_contract():
    assert DATASET_MAINTENANCE.status_code == 503
    assert DATASET_MAINTENANCE.error_type == "dataset_maintenance"
    assert DATASET_MAINTENANCE.error_code == "DATASET_MAINTENANCE"

    response = DATASET_MAINTENANCE.response()
    assert response.status_code == 503
    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {
        "error_type": "dataset_maintenance",
        "error_code": "DATASET_MAINTENANCE",
        "message": DATASET_MAINTENANCE.message,
    }
    # Generic message only -- no dataset slug, title, visibility state,
    # review state, active release, or blocker list.
    assert set(payload.keys()) == {"error_type", "error_code", "message"}


def test_access_guard_returns_dataset_not_found_for_unknown_dataset(monkeypatch):
    def raise_unavailable(_slug):
        raise DatasetUnavailableError("missing")

    monkeypatch.setattr(api_main, "resolve_dataset", raise_unavailable)
    response = api_main._resolve_public_dataset_detail_access("unknown-slug")

    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"


def test_access_guard_returns_release_unavailable(monkeypatch):
    def raise_release_unavailable(_slug):
        raise ReleaseUnavailableError("no release")

    monkeypatch.setattr(api_main, "resolve_dataset", raise_release_unavailable)
    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "RELEASE_UNAVAILABLE"


def test_access_guard_returns_registry_unavailable(monkeypatch):
    def raise_registry_invalid(_slug):
        raise RegistryInvalidError("bad registry")

    monkeypatch.setattr(api_main, "resolve_dataset", raise_registry_invalid)
    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "REGISTRY_UNAVAILABLE"


def test_access_guard_returns_dataset_maintenance_when_hidden(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: False)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)

    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error_code"] == "DATASET_MAINTENANCE"
    assert _TARGET_SLUG not in json.dumps(payload)
    assert set(payload.keys()) == {"error_type", "error_code", "message"}


def test_access_guard_returns_dataset_maintenance_when_needs_review(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: True)

    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_access_guard_returns_resolved_dataset_when_ready(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)

    resolved = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert not hasattr(resolved, "status_code")
    assert resolved.dataset_slug == _TARGET_SLUG
    assert resolved.active_release == "release-fixture-001"


def _maintenance_guard_response(_slug):
    return api_main.public_error_response(DATASET_MAINTENANCE)


def test_all_guarded_get_routes_return_maintenance_without_loading_resources(monkeypatch):
    """
    Uniform backend boundary: every guarded GET route delegates to the same
    access guard, and none of them load endpoint-specific resources when
    that guard reports maintenance.
    """
    monkeypatch.setattr(api_main, "_resolve_public_dataset_detail_access", _maintenance_guard_response)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("resource loader must not run when access is maintenance")

    for name in (
        "load_public_contract",
        "load_public_metrics",
        "load_public_context",
        "load_public_model_card",
        "load_public_visualizations",
        "load_public_predict_view_list",
        "load_public_predict_view",
        "load_public_predict_view_customization",
    ):
        monkeypatch.setattr(api_main, name, _forbidden)

    calls = [
        lambda: api_main.get_dataset(_TARGET_SLUG),
        lambda: api_main.get_public_contract(_TARGET_SLUG),
        lambda: api_main.get_public_metrics(_TARGET_SLUG),
        lambda: api_main.get_public_context(_TARGET_SLUG),
        lambda: api_main.get_public_model_card(_TARGET_SLUG),
        lambda: api_main.get_public_visualizations(_TARGET_SLUG),
        lambda: api_main.list_predict_views(_TARGET_SLUG),
        lambda: api_main.get_predict_view(_TARGET_SLUG, "unknown-view"),
        lambda: api_main.get_predict_view_customization(_TARGET_SLUG, "unknown-view"),
    ]

    for call in calls:
        response = call()
        assert response.status_code == 503
        assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_inference_route_returns_maintenance_before_payload_validation(monkeypatch):
    monkeypatch.setattr(api_main, "_resolve_public_dataset_detail_access", _maintenance_guard_response)
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("contract must not load for maintenance")),
    )

    response = api_main.validate_dataset_inference_payload(_TARGET_SLUG, payload="not-a-dict")

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_inference_route_returns_not_found_before_payload_validation_for_unknown_dataset():
    response = api_main.validate_dataset_inference_payload("dataset-that-does-not-exist", payload="not-a-dict")

    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"


def test_inference_route_ready_dataset_malformed_payload_retains_validation_error(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)

    response = api_main.validate_dataset_inference_payload(_TARGET_SLUG, payload="not-a-dict")

    assert response.status_code == 422
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "INVALID_PAYLOAD"


def test_predict_view_route_returns_maintenance_for_unknown_view_when_hidden(monkeypatch):
    monkeypatch.setattr(api_main, "_resolve_public_dataset_detail_access", _maintenance_guard_response)
    monkeypatch.setattr(
        api_main,
        "load_public_predict_view",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("view must not be looked up for maintenance")),
    )

    response = api_main.get_predict_view(_TARGET_SLUG, "unknown-view")

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_predict_view_route_returns_not_found_for_unknown_dataset_regardless_of_view():
    response = api_main.get_predict_view("dataset-that-does-not-exist", "any-view")

    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"


def test_predict_view_route_ready_dataset_unknown_view_retains_view_not_found(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)
    monkeypatch.setattr(
        api_main,
        "load_public_predict_view",
        lambda *_a, **_k: (_ for _ in ()).throw(ViewNotFoundError("no such view")),
    )

    response = api_main.get_predict_view(_TARGET_SLUG, "unknown-view")

    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "VIEW_NOT_FOUND"


def test_predict_view_customization_route_returns_maintenance_for_unknown_view_when_needs_review(monkeypatch):
    monkeypatch.setattr(api_main, "_resolve_public_dataset_detail_access", _maintenance_guard_response)
    monkeypatch.setattr(
        api_main,
        "load_public_predict_view_customization",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("customization must not load for maintenance")),
    )

    response = api_main.get_predict_view_customization(_TARGET_SLUG, "unknown-view")

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
