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
from types import SimpleNamespace

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from public_context_loader import PublicContextUnavailableError  # noqa: E402
from public_profile_visibility import (  # noqa: E402
    resolve_dataset_visibility,
    resolve_public_presentation_overlay,
)
from registry.dataset_public_profile_publication_store import (  # noqa: E402
    get_visibility,
    set_visibility,
)
from registry.list import ListedDataset, _snapshot_overlay_fields, is_dataset_needs_review  # noqa: E402
from registry.resolve import ReleaseUnavailableError  # noqa: E402

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


def test_list_datasets_endpoint_includes_all_when_all_visible():
    original_visibility = api_main.resolve_dataset_visibility
    original_list_datasets = api_main.list_datasets
    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.list_datasets = _fixture_two_dataset_listing
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.list_datasets = original_list_datasets

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
    "source_name": None,
    "source_url": None,
    "release_date_label": None,
    "date_format": None,
    "primary_metric_key": None,
    "performance_focus": None,
}
_CURATED_PUBLIC_PROFILE_OVERLAY = {
    **_CURATED_OVERLAY,
    "home_card_media_ref": None,
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
}


def test_get_public_context_returns_dataset_not_found_shape_when_hidden():
    original = api_main.resolve_dataset_visibility
    api_main.resolve_dataset_visibility = lambda dataset_slug: False
    try:
        hidden_response = api_main.get_public_context(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original

    nonexistent_response = api_main.get_public_context("dataset-that-does-not-exist")

    assert hidden_response.status_code == nonexistent_response.status_code
    assert (
        json.loads(hidden_response.body.decode("utf-8"))
        == json.loads(nonexistent_response.body.decode("utf-8"))
    )


def test_get_public_context_returns_context_when_visible():
    original_visibility = api_main.resolve_dataset_visibility
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.load_public_context = lambda active_release: dict(_FAKE_CONTEXT)
    api_main.resolve_public_presentation_overlay = lambda dataset_slug: dict(_EMPTY_PUBLIC_PROFILE_OVERLAY)
    try:
        response = api_main.get_public_context(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.load_public_context = original_loader
        api_main.resolve_public_presentation_overlay = original_overlay

    assert response["dataset_slug"] == _TARGET_SLUG
    assert response["context"]["title"] == "Fake Title"
    assert response["context"]["summary"] == "Fake summary."


def test_get_public_context_overlay_fields_none_when_no_snapshot_published():
    original_visibility = api_main.resolve_dataset_visibility
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
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


def test_get_public_context_includes_curated_overlay_fields_when_published():
    original_visibility = api_main.resolve_dataset_visibility
    original_loader = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
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


# ---------------------------------------------------------------------------
# problem_type resolution for M39-02: GET /datasets and GET /datasets/{slug}
# must include a real, fail-open problem_type sourced from each dataset's
# active-release public context (api/public_context_loader.py), the same
# source GET /datasets/{slug}/context already uses. Unlike the M39-04 overlay
# fields above (which come from the published snapshot store), problem_type
# has no snapshot-path equivalent, so it is resolved directly in api/main.py's
# _resolve_problem_type helper.
# ---------------------------------------------------------------------------


def test_resolve_problem_type_returns_value_when_context_available():
    original_load_public_context = api_main.load_public_context
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


def test_list_datasets_endpoint_includes_problem_type_for_every_visible_dataset():
    original_visibility = api_main.resolve_dataset_visibility
    original_load_public_context = api_main.load_public_context
    original_list_datasets = api_main.list_datasets
    original_resolve_dataset = api_main.resolve_dataset

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.load_public_context = lambda active_release: {"problem_type": "binary_classification"}
    api_main.list_datasets = _fixture_two_dataset_listing
    api_main.resolve_dataset = _fixture_resolve_dataset
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


def test_list_datasets_endpoint_problem_type_fails_open_per_dataset_without_excluding_it():
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


def test_get_dataset_includes_problem_type_when_available():
    original_visibility = api_main.resolve_dataset_visibility
    original_load_public_context = api_main.load_public_context

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
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


def test_list_datasets_endpoint_includes_dataset_when_not_needs_review():
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: False
    try:
        response = api_main.list_datasets_endpoint()
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    slugs = {entry["dataset_slug"] for entry in response["datasets"]}
    assert _TARGET_SLUG in slugs


def test_get_dataset_returns_dataset_not_found_shape_when_needs_review():
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: True
    try:
        needs_review_response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    nonexistent_response = api_main.get_dataset("dataset-that-does-not-exist")

    assert needs_review_response.status_code == nonexistent_response.status_code
    assert (
        json.loads(needs_review_response.body.decode("utf-8"))
        == json.loads(nonexistent_response.body.decode("utf-8"))
    )


def test_get_dataset_returns_data_when_visible_and_not_needs_review():
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review

    api_main.resolve_dataset_visibility = lambda dataset_slug: True
    api_main.is_dataset_needs_review = lambda dataset_slug: False
    try:
        response = api_main.get_dataset(_TARGET_SLUG)
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review

    assert response["dataset_slug"] == _TARGET_SLUG


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
