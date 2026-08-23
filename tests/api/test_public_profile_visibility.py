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
    SNAPSHOT_STATUS_CURRENT_RELEASE,
    SNAPSHOT_STATUS_INVALID,
    SNAPSHOT_STATUS_MISSING,
    SNAPSHOT_STATUS_STALE_RELEASE,
    resolve_dataset_snapshot_readiness,
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
from registry.update import (  # noqa: E402
    ACTIVE_RELEASE_MISMATCH_ERROR,
    approve_dataset_detail_review,
)

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
        performance_focus_id="overall_discrimination",
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


_CURRENT_RELEASE_SNAPSHOT = {"status": "current_release", "matches_active_release": True}


def _stub_snapshot_current(monkeypatch) -> None:
    """
    Project Spec S0125: isolate the shared access guard's new snapshot-
    alignment dimension from real registry/profile-snapshots content, so
    tests exercising only the visibility/review dimensions are unaffected by
    whether a real published snapshot happens to exist.
    """
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _dataset_slug, _active_release: dict(_CURRENT_RELEASE_SNAPSHOT),
    )


def _make_fixture_publicly_eligible(monkeypatch) -> None:
    """Isolate success paths from every real public eligibility gate."""
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    _stub_snapshot_current(monkeypatch)


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


def test_list_datasets_endpoint_excludes_hidden_dataset(monkeypatch):
    original_visibility = api_main.resolve_dataset_visibility
    original_list_datasets = api_main.list_datasets
    api_main.resolve_dataset_visibility = lambda dataset_slug: dataset_slug != _TARGET_SLUG
    api_main.list_datasets = _fixture_two_dataset_listing
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    _stub_snapshot_current(monkeypatch)
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
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    _stub_snapshot_current(monkeypatch)
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.list_datasets = original_list_datasets

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert set(_SEEDED_DATASET_SLUGS) <= slugs
    telco = next(entry for entry in response["datasets"] if entry["dataset_slug"] == "telco-customer-churn")
    assert telco["performance_focus_id"] == "overall_discrimination"
    assert "highlighted_score_id" not in telco
    assert "visible_scores" not in telco


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

    Project Spec S0125: a missing published snapshot always blocks public
    reachability now, so snapshot_missing moved from a non-blocking
    observation into blockers alongside visibility_disabled.
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
    assert state["public_access"]["blockers"] == ["visibility_disabled", "snapshot_missing"]
    assert state["public_access"]["observations"] == []
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
    assert "snapshot_missing" in state["public_access"]["blockers"]
    assert "configured_hidden_but_effectively_visible_without_snapshot" not in state["public_access"]["observations"]


def test_publication_state_integration_visible_no_snapshot_is_unreachable(monkeypatch, tmp_path):
    """
    Project Spec S0125: a visible, reviewed dataset with no published
    snapshot yet is no longer publicly reachable -- reachability now also
    requires a current-release snapshot. This replaces the pre-S0125
    "visible + no snapshot is reachable" expectation.
    """
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

    assert state["public_access"]["reachable"] is False
    assert state["public_access"]["blockers"] == ["snapshot_missing"]


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
        "blockers": ["visibility_disabled", "review_pending", "snapshot_stale"],
        "observations": [
            "visibility_default_applied",
            "visibility_record_invalid",
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
# Project Spec S0204: registry/list.py's _snapshot_overlay_fields now also
# projects performance_focus_id (never reused by
# resolve_public_presentation_overlay's own, separate superset assertions
# below, which never gains this key).
_EMPTY_OVERLAY_WITH_FOCUS = {**_EMPTY_OVERLAY, "performance_focus_id": None}
_CURATED_OVERLAY_WITH_FOCUS = {**_CURATED_OVERLAY, "performance_focus_id": "positive_class_detection"}
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
    "documentation": None,
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
    "documentation": {"format": "markdown", "content": "# Curated docs\n\nPublished body."},
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
    api_main.resolve_public_presentation_overlay = lambda dataset_slug, expected_problem_type=None: dict(_EMPTY_PUBLIC_PROFILE_OVERLAY)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda dataset_slug: False)
    _stub_snapshot_current(monkeypatch)
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
    _stub_snapshot_current(monkeypatch)
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug, expected_problem_type=None: dict(_EMPTY_PUBLIC_PROFILE_OVERLAY)
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
    _stub_snapshot_current(monkeypatch)
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug, expected_problem_type=None: dict(_CURATED_PUBLIC_PROFILE_OVERLAY)
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
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == _EMPTY_OVERLAY_WITH_FOCUS
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
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == _EMPTY_OVERLAY_WITH_FOCUS
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
                        "documentation": _CURATED_PUBLIC_PROFILE_OVERLAY["documentation"],
                    },
                }
            ),
            encoding="utf-8",
        )

        # registry/list.py's _snapshot_overlay_fields only ever reads its own
        # known overlay keys (Project Spec S0204 adds performance_focus_id to
        # that set), so it must still return exactly _CURATED_OVERLAY_WITH_FOCUS
        # even though the snapshot on disk also carries the other
        # public-profile-only fields.
        assert _snapshot_overlay_fields(_TARGET_SLUG, fake_repo) == dict(_CURATED_OVERLAY_WITH_FOCUS)
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
# Project Spec S0196: published Markdown documentation projection. Proves
# the overlay reads documentation only from the published snapshot, never
# from the private Admin draft store (this module never imports
# registry/dataset_public_profile_store.py at all), and bounds malformed
# documentation shapes to None rather than leaking raw content.
# ---------------------------------------------------------------------------


def test_public_presentation_overlay_projects_published_documentation():
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
                        "documentation": {
                            "format": "markdown",
                            "content": "# Heading\n\n| A | B |\n| - | - |\n| 1 | 2 |\n",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
        assert overlay["documentation"] == {
            "format": "markdown",
            "content": "# Heading\n\n| A | B |\n| - | - |\n| 1 | 2 |\n",
        }


def test_public_presentation_overlay_documentation_none_when_no_snapshot_published():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
        assert overlay["documentation"] is None


def test_public_presentation_overlay_documentation_none_when_snapshot_omits_it():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        _write_fake_snapshot(fake_repo, _TARGET_SLUG)
        overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
        assert overlay["documentation"] is None


def test_public_presentation_overlay_documentation_none_when_malformed():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        snapshots_dir = fake_repo / "registry" / "profile-snapshots"
        snapshots_dir.mkdir(parents=True)
        for malformed in (
            {"format": "html", "content": "<p>nope</p>"},
            {"format": "markdown", "content": 12345},
            ["not", "an", "object"],
        ):
            (snapshots_dir / f"{_TARGET_SLUG}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "dataset_slug": _TARGET_SLUG,
                        "published_at": "2026-07-01T00:00:00Z",
                        "active_release_at_publish_time": "release-20260101-001",
                        "profile": {"documentation": malformed},
                    }
                ),
                encoding="utf-8",
            )
            overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
            assert overlay["documentation"] is None


# ---------------------------------------------------------------------------
# Project Spec S0229: continuous-regression result_card normalization
# dispatch through resolve_public_presentation_overlay's expected_problem_type
# parameter, exercising the real (non-monkeypatched) chain into
# registry.dataset_public_profile_validate.normalize_result_presentation.
# ---------------------------------------------------------------------------


def test_public_presentation_overlay_defaults_continuous_regression_card_when_no_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="continuous_regression"
        )
        assert overlay["result_card"] == {
            "schema_version": "continuous-regression-result-presentation.v1",
            "predicted_value_label": "Predicted value",
            "model_section_label": "Model",
            "decimal_places": 2,
        }


def test_public_presentation_overlay_preserves_published_continuous_regression_card():
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
                        "result_card": {
                            "schema_version": "continuous-regression-result-presentation.v1",
                            "predicted_value_label": "Predicted compressive strength",
                            "model_section_label": "Model",
                            "decimal_places": 1,
                            "value_unit_label": "MPa",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="continuous_regression"
        )
        assert overlay["result_card"] == {
            "schema_version": "continuous-regression-result-presentation.v1",
            "predicted_value_label": "Predicted compressive strength",
            "model_section_label": "Model",
            "decimal_places": 1,
            "value_unit_label": "MPa",
        }


def test_public_presentation_overlay_expected_binary_problem_type_ignores_continuous_source():
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
                        "result_card": {
                            "schema_version": "continuous-regression-result-presentation.v1",
                            "predicted_value_label": "Predicted compressive strength",
                            "model_section_label": "Model",
                            "decimal_places": 1,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="binary_classification"
        )
        assert overlay["result_card"]["schema_version"] == "binary-result-presentation.v1"


# ---------------------------------------------------------------------------
# Project Spec S0249: univariate-forecasting result_card normalization
# dispatch through resolve_public_presentation_overlay's expected_problem_type
# parameter, exercising the real (non-monkeypatched) chain into
# registry.dataset_public_profile_validate.normalize_result_presentation.
# ---------------------------------------------------------------------------


def test_public_presentation_overlay_defaults_univariate_forecasting_card_when_no_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="univariate_forecasting"
        )
        assert overlay["result_card"] == {
            "schema_version": "univariate-forecasting-result-presentation.v1",
            "forecast_series_label": "Forecast",
            "future_time_index_label": "Period",
            "forecast_value_label": "Forecast",
            "model_section_label": "Model",
            "decimal_places": 2,
        }


def test_public_presentation_overlay_preserves_published_univariate_forecasting_card():
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
                        "result_card": {
                            "schema_version": "univariate-forecasting-result-presentation.v1",
                            "forecast_series_label": "Monthly demand forecast",
                            "future_time_index_label": "Month",
                            "forecast_value_label": "Forecasted demand",
                            "model_section_label": "Model",
                            "decimal_places": 1,
                            "value_unit_label": "units",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="univariate_forecasting"
        )
        assert overlay["result_card"] == {
            "schema_version": "univariate-forecasting-result-presentation.v1",
            "forecast_series_label": "Monthly demand forecast",
            "future_time_index_label": "Month",
            "forecast_value_label": "Forecasted demand",
            "model_section_label": "Model",
            "decimal_places": 1,
            "value_unit_label": "units",
        }


def test_public_presentation_overlay_expected_non_forecasting_problem_type_ignores_forecasting_source():
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
                        "result_card": {
                            "schema_version": "univariate-forecasting-result-presentation.v1",
                            "forecast_series_label": "Monthly demand forecast",
                            "future_time_index_label": "Month",
                            "forecast_value_label": "Forecasted demand",
                            "model_section_label": "Model",
                            "decimal_places": 1,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        overlay = resolve_public_presentation_overlay(
            _TARGET_SLUG, repo_root=fake_repo, expected_problem_type="binary_classification"
        )
        assert overlay["result_card"]["schema_version"] == "binary-result-presentation.v1"


def test_public_presentation_overlay_never_reads_private_draft_documentation():
    """
    A private, unpublished draft's documentation must never leak through
    this read-only public overlay -- it is never read at all, matching the
    existing pre-S0196 unpublished-draft isolation proven above for every
    other curated field.
    """
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        drafts_dir = fake_repo / "registry" / "profile-drafts"
        drafts_dir.mkdir(parents=True)
        (drafts_dir / f"{_TARGET_SLUG}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "documentation": {
                        "format": "markdown",
                        "content": "Private draft body never public.",
                    },
                }
            ),
            encoding="utf-8",
        )

        overlay = resolve_public_presentation_overlay(_TARGET_SLUG, repo_root=fake_repo)
        assert overlay["documentation"] is None
        assert "Private draft body never public." not in json.dumps(overlay)


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
    original_project = api_main._project_result_contract_safely

    def raise_context_unavailable(_active_release):
        raise PublicContextUnavailableError("unavailable")

    api_main.load_public_context = raise_context_unavailable
    api_main._project_result_contract_safely = lambda _release: {"status": "unavailable"}
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) is None
    finally:
        api_main.load_public_context = original_load_public_context
        api_main._project_result_contract_safely = original_project


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
    original_project = api_main._project_result_contract_safely
    api_main.load_public_context = lambda active_release: {"problem_type": 123}
    api_main._project_result_contract_safely = lambda _release: {"status": "unavailable"}
    try:
        assert api_main._resolve_problem_type(_TARGET_SLUG) is None
    finally:
        api_main.load_public_context = original_load_public_context
        api_main._project_result_contract_safely = original_project


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
    _stub_snapshot_current(monkeypatch)
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
    _stub_snapshot_current(monkeypatch)
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
    _stub_snapshot_current(monkeypatch)
    api_main.load_public_context = lambda active_release: {"problem_type": "regression"}
    try:
        response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_load_public_context

    assert response["problem_type"] == "regression"


# ---------------------------------------------------------------------------
# Project Spec S0238: release-bound model_display_name projection and
# continuous_regression accepted directly from active-release result
# semantics (api/main.py's _resolve_model_display_name and the extended
# _resolve_problem_type), proven at both the resolver level and the GET
# /datasets listing level.
# ---------------------------------------------------------------------------


def _fake_available_result_contract(
    problem_type="continuous_regression",
    model_family="hist_gradient_boosting",
    display_name="HistGradientBoosting",
):
    return {
        "status": "available",
        "semantics": {
            "problem_type": problem_type,
            "model_descriptor": {"model_family": model_family, "display_name": display_name},
        },
    }


def test_resolve_problem_type_accepts_continuous_regression_directly_from_result_semantics(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(
        api_main, "_project_result_contract_safely", lambda _release: _fake_available_result_contract()
    )

    def fail_if_called(_active_release):
        raise AssertionError("continuous_regression must resolve directly from result semantics")

    monkeypatch.setattr(api_main, "load_public_context", fail_if_called)

    assert api_main._resolve_problem_type(_TARGET_SLUG) == "continuous_regression"


def test_resolve_model_display_name_returns_value_from_active_release_result_semantics(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(
        api_main, "_project_result_contract_safely", lambda _release: _fake_available_result_contract()
    )

    assert api_main._resolve_model_display_name(_TARGET_SLUG) == "HistGradientBoosting"


def test_resolve_model_display_name_none_when_result_contract_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "_project_result_contract_safely", lambda _release: {"status": "unavailable"})

    assert api_main._resolve_model_display_name(_TARGET_SLUG) is None


def test_resolve_model_display_name_none_when_model_descriptor_missing(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(
        api_main,
        "_project_result_contract_safely",
        lambda _release: {"status": "available", "semantics": {"problem_type": "binary_classification"}},
    )

    assert api_main._resolve_model_display_name(_TARGET_SLUG) is None


def test_resolve_model_display_name_none_when_display_name_blank_or_non_string(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    for malformed_display_name in ("", "   ", 123, None):
        monkeypatch.setattr(
            api_main,
            "_project_result_contract_safely",
            lambda _release, value=malformed_display_name: _fake_available_result_contract(display_name=value),
        )
        assert api_main._resolve_model_display_name(_TARGET_SLUG) is None


def test_resolve_model_display_name_trims_surrounding_whitespace(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(
        api_main,
        "_project_result_contract_safely",
        lambda _release: _fake_available_result_contract(display_name="  HistGradientBoosting  "),
    )

    assert api_main._resolve_model_display_name(_TARGET_SLUG) == "HistGradientBoosting"


def test_resolve_model_display_name_none_when_dataset_unknown():
    assert api_main._resolve_model_display_name("dataset-that-does-not-exist") is None


def test_resolve_model_display_name_none_when_release_unavailable(monkeypatch):
    def raise_release_unavailable(_dataset_slug):
        raise ReleaseUnavailableError("missing release")

    monkeypatch.setattr(api_main, "resolve_dataset", raise_release_unavailable)

    assert api_main._resolve_model_display_name(_TARGET_SLUG) is None


def test_list_datasets_endpoint_includes_model_display_name_and_continuous_regression_problem_type(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    monkeypatch.setattr(
        api_main, "_project_result_contract_safely", lambda _release: _fake_available_result_contract()
    )
    _stub_snapshot_current(monkeypatch)

    response = api_main.list_datasets_endpoint()

    assert set(_SEEDED_DATASET_SLUGS) <= {entry["dataset_slug"] for entry in response["datasets"]}
    for entry in response["datasets"]:
        assert entry["problem_type"] == "continuous_regression"
        assert entry["model_display_name"] == "HistGradientBoosting"
        # AC4: no model internals beyond the bounded display_name projection.
        assert "model_family" not in entry
        assert "model_path" not in entry
        assert "hyperparameters" not in entry
        assert "hashes" not in entry


def test_list_datasets_endpoint_model_display_name_fails_open_per_dataset_without_excluding_it(monkeypatch):
    """
    A malformed/unavailable model descriptor must omit only that dataset's
    Model badge -- the dataset itself must remain listed, mirroring the
    problem_type fail-open precedent above.
    """
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    monkeypatch.setattr(
        api_main,
        "_project_result_contract_safely",
        lambda _release: {"status": "available", "semantics": {"problem_type": "binary_classification"}},
    )
    _stub_snapshot_current(monkeypatch)

    response = api_main.list_datasets_endpoint()

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert set(_SEEDED_DATASET_SLUGS) <= slugs
    for entry in response["datasets"]:
        assert entry["model_display_name"] is None


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
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    _stub_snapshot_current(monkeypatch)
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
    _stub_snapshot_current(monkeypatch)
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
    _stub_snapshot_current(monkeypatch)

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
    _stub_snapshot_current(monkeypatch)

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
    _stub_snapshot_current(monkeypatch)
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


# ---------------------------------------------------------------------------
# Project Spec S0125: Dataset Detail review-approval and public publication
# readiness contract. Covers registry.update.approve_dataset_detail_review
# (the controlled registry transition), api.public_profile_visibility.
# resolve_dataset_snapshot_readiness (the shared snapshot-alignment
# classifier), admin_profile_visibility.get_dataset_publication_state's new
# review.approval_allowed/approval_blockers projection and blocker/observation
# restructuring, admin_profile_visibility.approve_dataset_review (the private
# service boundary), and the new PUT /admin/datasets/{slug}/review-status
# route -- all isolated from the real repository via tmp_path fixtures.
# ---------------------------------------------------------------------------

_S0125_RELEASE_ID = "release-20260701-001"


def _s0125_write_registry(
    fake_repo: Path,
    dataset_slug: str = _TARGET_SLUG,
    active_release: str = _S0125_RELEASE_ID,
    review_status: str | None = "needs_review",
) -> None:
    registry_dir = fake_repo / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset_slug": dataset_slug,
        "active_release": active_release,
        "public_metadata": {
            "title": "Fixture Dataset",
            "summary": "Fixture.",
            "domain": "general",
            "visibility": "public",
            "tags": [],
        },
        "dataset_detail_updated_at": "2026-07-01T00:00:00Z",
    }
    if review_status is not None:
        entry["review_status"] = review_status
    (registry_dir / "datasets.json").write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.registry.v1",
                "datasets": [entry],
            }
        ),
        encoding="utf-8",
    )


def _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path: Path) -> None:
    """
    approve_dataset_review's own get_dataset_publication_state() calls
    registry.list.is_dataset_needs_review with an explicit registry_path
    keyword (independent from repo_root, defaulting to None/real-repo when
    the caller doesn't override it) -- force it to the tmp_path fixture
    registry regardless of what registry_path the caller passes through, so
    review-state re-checks after a registry mutation observe that mutation
    instead of the real repository.
    """
    fixed_registry_path = tmp_path / "registry" / "datasets.json"
    monkeypatch.setattr(
        admin_profile_visibility,
        "is_dataset_needs_review",
        lambda dataset_slug, registry_path=None: is_dataset_needs_review(
            dataset_slug, registry_path=fixed_registry_path
        ),
    )


def _s0125_write_snapshot(fake_repo: Path, dataset_slug: str, active_release: str) -> None:
    snapshots_dir = fake_repo / "registry" / "profile-snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    (snapshots_dir / f"{dataset_slug}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset_slug": dataset_slug,
                "published_at": "2026-07-01T00:00:00Z",
                "active_release_at_publish_time": active_release,
                "profile": {},
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# registry.update.approve_dataset_detail_review: the controlled registry
# transition itself.
# ---------------------------------------------------------------------------


def test_approve_dataset_detail_review_transitions_needs_review_to_ready(tmp_path):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    result = approve_dataset_detail_review(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)

    assert result == {
        "dataset_slug": _TARGET_SLUG,
        "review_status": "ready",
        "changed": True,
        "errors": [],
    }
    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    entry = registry["datasets"][0]
    assert entry["review_status"] == "ready"
    # Only review_status changed -- identity, active_release, metadata, and
    # the S0089/S0092 display-date authority are all preserved untouched.
    assert entry["dataset_slug"] == _TARGET_SLUG
    assert entry["active_release"] == _S0125_RELEASE_ID
    assert entry["dataset_detail_updated_at"] == "2026-07-01T00:00:00Z"
    assert entry["public_metadata"]["title"] == "Fixture Dataset"


def test_approve_dataset_detail_review_writes_previous_registry_backup(tmp_path):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    original_bytes = (tmp_path / "registry" / "datasets.json").read_bytes()

    approve_dataset_detail_review(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)

    assert (tmp_path / "registry" / "datasets.json.previous").read_bytes() == original_bytes


def test_approve_dataset_detail_review_idempotent_when_already_ready(tmp_path):
    _s0125_write_registry(tmp_path, review_status="ready")
    before = (tmp_path / "registry" / "datasets.json").read_bytes()

    result = approve_dataset_detail_review(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)

    assert result == {
        "dataset_slug": _TARGET_SLUG,
        "review_status": "ready",
        "changed": False,
        "errors": [],
    }
    # No rewrite occurred -- byte-for-byte identical, no backup created.
    assert (tmp_path / "registry" / "datasets.json").read_bytes() == before
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_approve_dataset_detail_review_rejects_active_release_mismatch(tmp_path):
    _s0125_write_registry(tmp_path, active_release=_S0125_RELEASE_ID, review_status="needs_review")
    before = (tmp_path / "registry" / "datasets.json").read_bytes()

    result = approve_dataset_detail_review(_TARGET_SLUG, "release-20260601-001", repo_root=tmp_path)

    assert result["changed"] is False
    assert result["errors"] == [ACTIVE_RELEASE_MISMATCH_ERROR]
    assert result["review_status"] == "needs_review"
    assert (tmp_path / "registry" / "datasets.json").read_bytes() == before
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_approve_dataset_detail_review_rejects_unknown_dataset(tmp_path):
    _s0125_write_registry(tmp_path, dataset_slug="other-dataset")

    result = approve_dataset_detail_review(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)

    assert result["changed"] is False
    assert result["errors"][0]["code"] == "DATASET_DETAIL_NOT_FOUND"


def test_approve_dataset_detail_review_rejects_invalid_dataset_slug(tmp_path):
    result = approve_dataset_detail_review("Invalid Slug", _S0125_RELEASE_ID, repo_root=tmp_path)

    assert result["changed"] is False
    assert result["errors"][0]["code"] == "DATASET_SLUG_INVALID"


def test_approve_dataset_detail_review_has_no_reverse_transition():
    """The controlled transition function itself has exactly one write site
    for review_status, and it is always the literal "ready" -- there is no
    parameter or code path that can set review_status back to
    needs_review; it is a one-directional approval boundary by
    construction."""
    import inspect

    source = inspect.getsource(approve_dataset_detail_review)
    assert source.count('entry["review_status"] =') == 1
    assert 'entry["review_status"] = _REVIEW_STATUS_READY' in source


# ---------------------------------------------------------------------------
# api.public_profile_visibility.resolve_dataset_snapshot_readiness
# ---------------------------------------------------------------------------


def test_snapshot_readiness_missing_when_no_snapshot_published(tmp_path):
    result = resolve_dataset_snapshot_readiness(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)
    assert result == {"status": SNAPSHOT_STATUS_MISSING, "matches_active_release": None}


def test_snapshot_readiness_current_release_when_bound_release_matches(tmp_path):
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, _S0125_RELEASE_ID)
    result = resolve_dataset_snapshot_readiness(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)
    assert result == {"status": SNAPSHOT_STATUS_CURRENT_RELEASE, "matches_active_release": True}


def test_snapshot_readiness_stale_release_when_bound_release_differs(tmp_path):
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, "release-20260601-001")
    result = resolve_dataset_snapshot_readiness(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)
    assert result == {"status": SNAPSHOT_STATUS_STALE_RELEASE, "matches_active_release": False}


def test_snapshot_readiness_invalid_when_bound_release_malformed(tmp_path):
    snapshots_dir = tmp_path / "registry" / "profile-snapshots"
    snapshots_dir.mkdir(parents=True)
    (snapshots_dir / f"{_TARGET_SLUG}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset_slug": _TARGET_SLUG,
                "published_at": "2026-07-01T00:00:00Z",
                "active_release_at_publish_time": "not-a-release-id",
                "profile": {},
            }
        ),
        encoding="utf-8",
    )
    result = resolve_dataset_snapshot_readiness(_TARGET_SLUG, _S0125_RELEASE_ID, repo_root=tmp_path)
    assert result == {"status": SNAPSHOT_STATUS_INVALID, "matches_active_release": None}


# ---------------------------------------------------------------------------
# admin_profile_visibility.get_dataset_publication_state: review.approval_
# allowed / review.approval_blockers projection (Project Spec S0125).
# ---------------------------------------------------------------------------


def test_publication_state_review_approval_allowed_true_when_needs_review_and_current_snapshot(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=True,
        review=True,
        snapshot={
            "dataset_slug": _TARGET_SLUG,
            "published_at": "2026-07-16T20:30:00Z",
            "active_release_at_publish_time": "release-20260716-001",
        },
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["review"] == {
        "status": "needs_review",
        "approval_allowed": True,
        "approval_blockers": [],
    }


def test_publication_state_review_approval_blocked_when_snapshot_missing(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=True,
        review=True,
        snapshot=None,
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["review"] == {
        "status": "needs_review",
        "approval_allowed": False,
        "approval_blockers": ["snapshot_missing"],
    }


def test_publication_state_review_approval_blocked_when_snapshot_stale(monkeypatch):
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": True,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=True,
        review=True,
        snapshot={
            "dataset_slug": _TARGET_SLUG,
            "published_at": "2026-07-16T20:30:00Z",
            "active_release_at_publish_time": "release-20260601-001",
        },
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["review"]["approval_allowed"] is False
    assert state["review"]["approval_blockers"] == ["snapshot_stale"]


def test_publication_state_review_approval_not_allowed_again_when_already_ready(monkeypatch):
    """A dataset already "ready" is never represented as approval-eligible
    again, regardless of snapshot state -- no reverse-action invitation."""
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
    assert state["review"] == {"status": "ready", "approval_allowed": False, "approval_blockers": []}


def test_publication_state_review_approval_independent_of_visibility(monkeypatch):
    """Visibility state must not be an approval blocker: a hidden dataset
    with a current snapshot and needs_review is still approval-eligible."""
    _publication_state_dependencies(
        monkeypatch,
        configured={
            "visible": False,
            "source": "explicit_record",
            "record_status": "valid",
            "updated_at": "2026-07-16T21:00:00Z",
        },
        effective=False,
        review=True,
        snapshot={
            "dataset_slug": _TARGET_SLUG,
            "published_at": "2026-07-16T20:30:00Z",
            "active_release_at_publish_time": "release-20260716-001",
        },
    )
    state = admin_profile_visibility.get_dataset_publication_state(_TARGET_SLUG)
    assert state["review"]["approval_allowed"] is True
    assert state["public_access"]["reachable"] is False
    assert "visibility_disabled" in state["public_access"]["blockers"]


# ---------------------------------------------------------------------------
# admin_profile_visibility.approve_dataset_review: the private service
# boundary. Isolated end-to-end against a tmp_path fixture repository (real
# resolve_dataset/is_dataset_needs_review/registry mutation), never touching
# the real repository's registry/profile/publication artifacts.
# ---------------------------------------------------------------------------


def test_approve_dataset_review_succeeds_when_needs_review_and_current_snapshot(tmp_path, monkeypatch):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, _S0125_RELEASE_ID)
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)

    result = admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert result["approved"] is True
    assert result["changed"] is True
    assert result["review_status"] == "ready"
    assert result["publication_state"]["review"]["status"] == "ready"
    assert result["errors"] == []
    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    assert registry["datasets"][0]["review_status"] == "ready"


def test_approve_dataset_review_idempotent_when_already_ready_and_snapshot_current(tmp_path, monkeypatch):
    _s0125_write_registry(tmp_path, review_status="ready")
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, _S0125_RELEASE_ID)
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)

    result = admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert result["approved"] is True
    assert result["changed"] is False
    assert result["review_status"] == "ready"


def test_approve_dataset_review_blocked_when_snapshot_missing(tmp_path, monkeypatch):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)

    result = admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert result["approved"] is False
    assert result["errors"] == [admin_profile_visibility.REVIEW_APPROVAL_BLOCKED_ERROR]
    assert result["publication_state"] is None
    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    assert registry["datasets"][0]["review_status"] == "needs_review"


def test_approve_dataset_review_blocked_when_snapshot_stale(tmp_path, monkeypatch):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, "release-20260601-001")
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)

    result = admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert result["approved"] is False
    assert result["errors"] == [admin_profile_visibility.REVIEW_APPROVAL_BLOCKED_ERROR]


def test_approve_dataset_review_does_not_require_visibility(tmp_path, monkeypatch):
    _s0125_write_registry(tmp_path, review_status="needs_review")
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, _S0125_RELEASE_ID)
    set_visibility(_TARGET_SLUG, False, repo_root=tmp_path)
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)

    result = admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert result["approved"] is True
    assert result["publication_state"]["visibility"]["effective_visible"] is False
    assert result["publication_state"]["public_access"]["reachable"] is False


def test_approve_dataset_review_never_writes_visibility_or_snapshot(tmp_path, monkeypatch):
    """Approval must not publish a snapshot, write a visibility record, or
    create a draft -- only registry/datasets.json (+ its backup) changes."""
    _s0125_write_registry(tmp_path, review_status="needs_review")
    _s0125_write_snapshot(tmp_path, _TARGET_SLUG, _S0125_RELEASE_ID)
    monkeypatch.setattr(
        admin_profile_visibility, "resolve_dataset", lambda slug, registry_path=None: SimpleNamespace(
            dataset_slug=slug, active_release=_S0125_RELEASE_ID
        )
    )
    _mock_needs_review_from_tmp_registry(monkeypatch, tmp_path)
    snapshot_before = (tmp_path / "registry" / "profile-snapshots" / f"{_TARGET_SLUG}.json").read_bytes()
    assert not (tmp_path / "registry" / "profile-publications").exists()
    assert not (tmp_path / "registry" / "profile-drafts").exists()

    admin_profile_visibility.approve_dataset_review(_TARGET_SLUG, repo_root=tmp_path)

    assert (tmp_path / "registry" / "profile-snapshots" / f"{_TARGET_SLUG}.json").read_bytes() == snapshot_before
    assert not (tmp_path / "registry" / "profile-publications").exists()
    assert not (tmp_path / "registry" / "profile-drafts").exists()


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/review-status route
# ---------------------------------------------------------------------------


def test_review_status_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    request = _make_request({}, path=f"/admin/datasets/{_TARGET_SLUG}/review-status")
    response = api_main.put_admin_dataset_review_status(_TARGET_SLUG, request, {"status": "ready"})
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_review_status_route_rejects_missing_status():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        request = _make_request({}, path=f"/admin/datasets/{_TARGET_SLUG}/review-status")
        response = api_main.put_admin_dataset_review_status(_TARGET_SLUG, request, {})
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_REVIEW_STATUS_INVALID"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_review_status_route_rejects_reverse_transition_payload():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        request = _make_request({}, path=f"/admin/datasets/{_TARGET_SLUG}/review-status")
        response = api_main.put_admin_dataset_review_status(_TARGET_SLUG, request, {"status": "needs_review"})
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_REVIEW_STATUS_INVALID"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_review_status_route_returns_409_when_approval_blocked(monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    monkeypatch.setattr(
        api_main,
        "approve_dataset_review",
        lambda _slug: {
            "approved": False,
            "dataset_slug": _slug,
            "changed": False,
            "review_status": "needs_review",
            "publication_state": None,
            "errors": [admin_profile_visibility.REVIEW_APPROVAL_BLOCKED_ERROR],
        },
    )
    try:
        request = _make_request({}, path=f"/admin/datasets/{_TARGET_SLUG}/review-status")
        response = api_main.put_admin_dataset_review_status(_TARGET_SLUG, request, {"status": "ready"})
        assert response.status_code == 409
        payload = json.loads(response.body.decode("utf-8"))
        assert payload["error_code"] == "DATASET_REVIEW_APPROVAL_BLOCKED"
        assert payload["errors"] == [admin_profile_visibility.REVIEW_APPROVAL_BLOCKED_ERROR]
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_review_status_route_returns_dataset_not_found(monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"

    def raise_unavailable(_slug):
        raise DatasetUnavailableError("missing")

    monkeypatch.setattr(api_main, "approve_dataset_review", raise_unavailable)
    try:
        request = _make_request({}, path=f"/admin/datasets/unknown-slug/review-status")
        response = api_main.put_admin_dataset_review_status("unknown-slug", request, {"status": "ready"})
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_NOT_FOUND"
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_review_status_route_succeeds_and_returns_bounded_success_body(monkeypatch):
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    fake_publication_state = {
        "dataset_slug": _TARGET_SLUG,
        "review": {"status": "ready", "approval_allowed": False, "approval_blockers": []},
        "public_access": {"reachable": True, "blockers": [], "observations": []},
    }
    monkeypatch.setattr(
        api_main,
        "approve_dataset_review",
        lambda _slug: {
            "approved": True,
            "dataset_slug": _slug,
            "changed": True,
            "review_status": "ready",
            "publication_state": fake_publication_state,
            "errors": [],
        },
    )
    try:
        request = _make_request({}, path=f"/admin/datasets/{_TARGET_SLUG}/review-status")
        response = api_main.put_admin_dataset_review_status(_TARGET_SLUG, request, {"status": "ready"})
        assert response == {
            "dataset_slug": _TARGET_SLUG,
            "review_status": "ready",
            "changed": True,
            "publication_state": fake_publication_state,
        }
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_review_status_route_registered_only_under_admin():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/review-status" in paths
    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("review-status" in path for path in public_paths)


# ---------------------------------------------------------------------------
# Public readiness truth table: snapshot alignment as a public-access blocker
# (Project Spec S0125), exercised directly through the shared access guard.
# ---------------------------------------------------------------------------


def test_access_guard_returns_maintenance_when_snapshot_missing(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _slug, _release: {"status": SNAPSHOT_STATUS_MISSING, "matches_active_release": None},
    )

    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_access_guard_returns_maintenance_when_snapshot_stale(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _slug, _release: {"status": SNAPSHOT_STATUS_STALE_RELEASE, "matches_active_release": False},
    )

    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_access_guard_returns_maintenance_when_snapshot_invalid(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _slug, _release: {"status": SNAPSHOT_STATUS_INVALID, "matches_active_release": None},
    )

    response = api_main._resolve_public_dataset_detail_access(_TARGET_SLUG)

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8"))["error_code"] == "DATASET_MAINTENANCE"


def test_list_datasets_endpoint_excludes_dataset_with_snapshot_missing(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)
    monkeypatch.setattr(api_main, "resolve_dataset", _fixture_resolve_dataset)
    monkeypatch.setattr(api_main, "list_datasets", _fixture_two_dataset_listing)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda slug, _release: {
            "status": SNAPSHOT_STATUS_CURRENT_RELEASE if slug != _TARGET_SLUG else SNAPSHOT_STATUS_MISSING,
            "matches_active_release": slug != _TARGET_SLUG,
        },
    )

    response = api_main.list_datasets_endpoint()

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG not in slugs
    assert "bank-marketing" in slugs


def test_dataset_publicly_ready_false_when_active_release_cannot_be_resolved(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: False)

    def raise_unavailable(_slug):
        raise DatasetUnavailableError("missing")

    monkeypatch.setattr(api_main, "resolve_dataset", raise_unavailable)

    assert api_main._dataset_publicly_ready(_TARGET_SLUG) is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
