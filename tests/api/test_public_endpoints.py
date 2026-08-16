"""
Public endpoint tests for M3-04.

Exercises the public API response shape for dataset listing and single-dataset
metadata. Tests use direct function calls (registry/list.py and registry/resolve.py)
because httpx is not a declared dependency. Tests confirm safe-field projection,
predictable error codes, and the absence of internal fields in responses.

Run from the repository root:
    python -m pytest tests/api/test_public_endpoints.py -v
or directly:
    python tests/api/test_public_endpoints.py
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
import public_predict_view_customization_loader as customization_loader_module  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.list import AdminListedDataset, ListedDataset, list_admin_datasets, list_datasets  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

_VALID_ENTRY = {
    "dataset_slug": "example-dataset",
    "active_release": "release-20260616-001",
    "public_metadata": {
        "title": "Example Dataset",
        "summary": "Fixture for public endpoint tests.",
        "domain": "example",
        "visibility": "public",
        "tags": ["example", "fixture"],
    },
}

_BASE_REGISTRY = {
    "schema_version": "atlas.dataflow.registry.v1",
    "conventions": {
        "dataset_slug": {"pattern": "x", "description": "x"},
        "release_id": {"pattern": "x", "description": "x"},
        "active_release": {"description": "x"},
    },
    "datasets": [_VALID_ENTRY],
}

_PUBLIC_LISTING_KEYS = {
    "dataset_slug",
    "title",
    "summary",
    "domain",
    "visibility",
    "tags",
    "display_title",
    "display_subtitle",
    "home_card_icon",
    "home_card_media_ref",
    "short_description",
    "theme_preset",
    "performance_focus_id",
}

_EMPTY_PUBLIC_CONTEXT_OVERLAY = {
    "display_title": None,
    "display_subtitle": None,
    "problem_summary_title": None,
    "problem_summary_body": None,
    "canonical_name_fallback": None,
    "home_card_icon": None,
    "short_description": None,
    "theme_preset": None,
    "source_name": None,
    "source_url": None,
    "release_date_label": None,
    "date_format": None,
    "primary_metric_key": None,
}


def _write_registry(tmp_dir: Path, content: dict) -> Path:
    path = tmp_dir / "datasets.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def _write_repo_registry(tmp_dir: Path, content: dict) -> Path:
    registry_dir = tmp_dir / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / "datasets.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# list_datasets: safe field projection
# ---------------------------------------------------------------------------

def test_list_datasets_returns_list():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        assert isinstance(result, list)
        assert len(result) == 1


def test_list_datasets_returns_named_tuples():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        assert all(isinstance(d, ListedDataset) for d in result)


def test_list_datasets_safe_fields_present():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        d = result[0]
        assert d.dataset_slug == "example-dataset"
        assert d.title == "Example Dataset"
        assert d.summary == "Fixture for public endpoint tests."
        assert d.domain == "example"
        assert d.visibility == "public"
        assert d.tags == ["example", "fixture"]


def test_list_datasets_no_active_release_in_result():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert "active_release" not in as_dict


def test_list_datasets_no_conventions_in_result():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert "conventions" not in as_dict
        assert "$schema" not in as_dict
        assert "schema_version" not in as_dict


def test_list_datasets_asdict_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert set(as_dict.keys()) == _PUBLIC_LISTING_KEYS


def _write_profile_snapshot(repo_root: Path, background_image_ref: object) -> None:
    snapshots_root = repo_root / "registry" / "profile-snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    snapshots_root.joinpath("example-dataset.json").write_text(
        json.dumps({
            "schema_version": "1.0.0",
            "dataset_slug": "example-dataset",
            "published_at": "2026-07-12T00:00:00Z",
            "active_release_at_publish_time": "release-20260616-001",
            "profile": {
                "home_card": {"background_image_ref": background_image_ref},
            },
        }),
        encoding="utf-8",
    )


def test_list_datasets_projects_bounded_home_card_media_reference():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        _write_profile_snapshot(repo_root, "/media/home-cards/generated_file-01.webp")

        result = list_datasets(registry_path=path)

        assert result[0].home_card_media_ref == "/media/home-cards/generated_file-01.webp"


def test_list_datasets_normalizes_empty_or_unsafe_home_card_media_references():
    unsafe_values = [
        None,
        "",
        "/home/operator/private.png",
        "/workspace/project-support/evidence/private.png",
        "/tmp/runtime-private.png",
        "file:///home/operator/private.png",
        "https://example.com/card.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "/media/private/card.png",
        "/media/home-cards/nested/card.png",
        "/media/home-cards/../private.png",
        "/media/home-cards/card.png?token=private",
        [137, 80, 78, 71],
    ]

    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        for unsafe_value in unsafe_values:
            _write_profile_snapshot(repo_root, unsafe_value)
            result = list_datasets(registry_path=path)
            assert result[0].home_card_media_ref is None


def test_admin_dataset_listing_prefers_latest_snapshot_display_title_over_registry_title():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        snapshots_root = repo_root / "registry" / "profile-snapshots"
        snapshots_root.mkdir(parents=True)
        snapshots_root.joinpath("example-dataset.json").write_text(
            json.dumps({
                "schema_version": "1.0.0",
                "dataset_slug": "example-dataset",
                "published_at": "2026-07-11T00:00:00Z",
                "active_release_at_publish_time": "release-20260616-001",
                "profile": {"display": {"title": "Published Admin Title"}},
            }),
            encoding="utf-8",
        )

        result = list_admin_datasets(registry_path=path)

        assert len(result) == 1
        assert result[0].dataset_slug == "example-dataset"
        assert result[0].title == "Example Dataset"
        assert result[0].display_title == "Published Admin Title"


def test_admin_dataset_listing_falls_back_to_registry_title_without_snapshot_title():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_repo_registry(Path(tmp), _BASE_REGISTRY)

        result = list_admin_datasets(registry_path=path)

        assert len(result) == 1
        assert result[0].dataset_slug == "example-dataset"
        assert result[0].display_title == "Example Dataset"


# ---------------------------------------------------------------------------
# list_datasets: performance_focus_id projection (Project Spec S0204)
# ---------------------------------------------------------------------------

def _write_profile_snapshot_performance_focus(repo_root: Path, performance_focus: object) -> None:
    snapshots_root = repo_root / "registry" / "profile-snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    profile: dict = {}
    if performance_focus is not None:
        profile["performance_focus"] = performance_focus
    snapshots_root.joinpath("example-dataset.json").write_text(
        json.dumps({
            "schema_version": "1.0.0",
            "dataset_slug": "example-dataset",
            "published_at": "2026-07-12T00:00:00Z",
            "active_release_at_publish_time": "release-20260616-001",
            "profile": profile,
        }),
        encoding="utf-8",
    )


def test_list_datasets_performance_focus_id_none_without_published_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_repo_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        assert result[0].performance_focus_id is None


def test_list_datasets_performance_focus_id_none_with_snapshot_but_no_focus():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        _write_profile_snapshot_performance_focus(repo_root, None)

        result = list_datasets(registry_path=path)

        assert result[0].performance_focus_id is None


def test_list_datasets_projects_published_performance_focus_id():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        _write_profile_snapshot_performance_focus(
            repo_root,
            {
                "focus_id": "overall_discrimination",
                "highlighted_score_id": "roc_auc",
                "visible_scores": [
                    {"score_id": "roc_auc", "display_label": "ROC-AUC", "value": "0.9", "value_source": "manual", "order": 0},
                ],
            },
        )

        result = list_datasets(registry_path=path)

        assert result[0].performance_focus_id == "overall_discrimination"


def test_list_datasets_performance_focus_id_invalid_shapes_yield_none():
    invalid_performance_focus_values = [
        {},
        {"not_focus_id": "x"},
        {"focus_id": ""},
        {"focus_id": 42},
        {"focus_id": []},
        {"focus_id": None},
        "not_an_object",
        42,
        [],
    ]
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        for invalid_performance_focus in invalid_performance_focus_values:
            _write_profile_snapshot_performance_focus(repo_root, invalid_performance_focus)
            result = list_datasets(registry_path=path)
            assert result[0].performance_focus_id is None


def test_list_datasets_performance_focus_id_does_not_expose_highlighted_score_id_or_visible_scores():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        path = _write_repo_registry(repo_root, _BASE_REGISTRY)
        _write_profile_snapshot_performance_focus(
            repo_root,
            {
                "focus_id": "positive_class_detection",
                "highlighted_score_id": "recall",
                "visible_scores": [
                    {"score_id": "recall", "display_label": "Recall", "value": "0.8", "value_source": "manual", "order": 0},
                ],
            },
        )

        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()

        assert as_dict["performance_focus_id"] == "positive_class_detection"
        assert "highlighted_score_id" not in as_dict
        assert "visible_scores" not in as_dict
        assert set(as_dict.keys()) == _PUBLIC_LISTING_KEYS


# ---------------------------------------------------------------------------
# list_datasets: registry unavailable
# ---------------------------------------------------------------------------

def test_list_datasets_raises_registry_invalid_on_bad_registry():
    invalid = {**_BASE_REGISTRY, "schema_version": "bad-version"}
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), invalid)
        raised = False
        try:
            list_datasets(registry_path=path)
        except RegistryInvalidError:
            raised = True
        assert raised, "Expected RegistryInvalidError for invalid registry"


def test_list_datasets_raises_registry_invalid_on_missing_file():
    path = Path("/nonexistent/path/datasets.json")
    raised = False
    try:
        list_datasets(registry_path=path)
    except RegistryInvalidError:
        raised = True
    assert raised, "Expected RegistryInvalidError for missing registry file"


# ---------------------------------------------------------------------------
# resolve_dataset: used by single-dataset endpoint
# ---------------------------------------------------------------------------

def test_resolve_dataset_confirms_slug_exists():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolved = resolve_dataset("example-dataset", registry_path=path)
        assert resolved.dataset_slug == "example-dataset"


def test_resolve_dataset_unknown_slug_raises_dataset_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("unknown-slug", registry_path=path)
        except DatasetUnavailableError:
            raised = True
        assert raised, "Expected DatasetUnavailableError for unknown slug"


def test_resolve_dataset_does_not_return_active_release_in_public_flow():
    """
    After resolve_dataset confirms the slug, list_datasets extracts safe fields.
    Confirm no active_release appears in the projected fields.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolve_dataset("example-dataset", registry_path=path)
        all_listed = list_datasets(registry_path=path)
        for listed in all_listed:
            if listed.dataset_slug == "example-dataset":
                as_dict = listed._asdict()
                assert "active_release" not in as_dict
                return
        assert False, "example-dataset not found in list_datasets result"


# ---------------------------------------------------------------------------
# Combined: single-dataset safe field projection via resolve + list
# ---------------------------------------------------------------------------

def test_single_dataset_response_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolve_dataset("example-dataset", registry_path=path)
        all_listed = list_datasets(registry_path=path)
        matched = next((d for d in all_listed if d.dataset_slug == "example-dataset"), None)
        assert matched is not None
        response = matched._asdict()
        assert set(response.keys()) == _PUBLIC_LISTING_KEYS
        assert "active_release" not in response
        assert "conventions" not in response
        assert "$schema" not in response


def test_listing_response_datasets_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        datasets = list_datasets(registry_path=path)
        response = {"datasets": [d._asdict() for d in datasets]}
        assert "datasets" in response
        assert isinstance(response["datasets"], list)
        assert len(response["datasets"]) == 1


def test_listing_each_item_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        datasets = list_datasets(registry_path=path)
        for item in [d._asdict() for d in datasets]:
            assert set(item.keys()) == _PUBLIC_LISTING_KEYS
            assert "active_release" not in item
            assert "conventions" not in item
            assert "$schema" not in item


# ---------------------------------------------------------------------------
# Context endpoint: safe public runtime projection
# ---------------------------------------------------------------------------

def _response_json(response):
    return json.loads(response.body.decode("utf-8"))


def _install_snapshot_ready_stub():
    """
    Project Spec S0125: isolate the shared access guard's new snapshot-
    alignment dimension from real registry/profile-snapshots content for
    tests that mock resolve_dataset (or don't isolate visibility/review at
    all) and only care about a route's own resource-loading behavior.
    Returns the original resolve_dataset_snapshot_readiness for restoration.
    """
    original = api_main.resolve_dataset_snapshot_readiness
    api_main.resolve_dataset_snapshot_readiness = lambda *_a, **_k: {
        "status": "current_release",
        "matches_active_release": True,
    }
    return original


def _restore_snapshot_ready_stub(original) -> None:
    api_main.resolve_dataset_snapshot_readiness = original


def test_context_endpoint_returns_public_context_response():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay
    original_snapshot_readiness = _install_snapshot_ready_stub()
    context = {
        "schema_version": "public-context.v1",
        "dataset_slug": "example-dataset",
        "release_id": "release-20260616-001",
        "title": "Example Dataset",
        "summary": "Fixture for public context endpoint tests.",
        "domain": "example",
        "problem_type": "classification",
        "prediction_target_description": "Example target.",
        "use_case": "Example use case.",
        "visibility": "public",
        "tags": ["example", "fixture"],
    }
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260616-001",
        )
        api_main.load_public_context = lambda active_release: context
        api_main.resolve_public_presentation_overlay = lambda dataset_slug: dict(_EMPTY_PUBLIC_CONTEXT_OVERLAY)
        response = api_main.get_public_context("example-dataset")
        assert response == {
            "dataset_slug": "example-dataset",
            "context": {**context, **_EMPTY_PUBLIC_CONTEXT_OVERLAY},
        }
        assert "run_id" not in response["context"]
        assert "raw_metrics" not in response["context"]
        assert all(not key.startswith("_") for key in response["context"])
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_context = original_load_public_context
        api_main.resolve_public_presentation_overlay = original_overlay
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_context_endpoint_unknown_dataset_returns_dataset_not_found():
    original_resolve_dataset = api_main.resolve_dataset
    try:
        def raise_dataset_unavailable(_dataset_slug):
            raise DatasetUnavailableError("missing")

        api_main.resolve_dataset = raise_dataset_unavailable
        response = api_main.get_public_context("unknown-slug")
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve_dataset


def test_context_endpoint_release_unavailable_returns_release_unavailable():
    original_resolve_dataset = api_main.resolve_dataset
    try:
        def raise_release_unavailable(_dataset_slug):
            raise ReleaseUnavailableError("missing release")

        api_main.resolve_dataset = raise_release_unavailable
        response = api_main.get_public_context("example-dataset")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "RELEASE_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve_dataset


def test_context_endpoint_context_unavailable_returns_context_unavailable():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260616-001",
        )

        def raise_context_unavailable(_active_release):
            raise api_main.PublicContextUnavailableError("missing context")

        api_main.load_public_context = raise_context_unavailable
        response = api_main.get_public_context("example-dataset")
        assert response.status_code == 503
        payload = _response_json(response)
        assert payload["error_type"] == "context_unavailable"
        assert payload["error_code"] == "CONTEXT_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_context = original_load_public_context
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# GET /datasets/{dataset_slug}/views/{view_id}/customization
# ---------------------------------------------------------------------------

_VALID_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "view_copy": {
        "heading": "Churn Risk Assessment",
        "description": "Estimate churn likelihood.",
        "usage_guidance": "Use canonical contracts.",
    },
    "field_hints": [
        {
            "field_name": "tenure",
            "display_label": "Months with Company",
            "explanatory_copy": "How long the customer has been with the provider.",
            "display_order_hint": 1,
            "group": "account-history",
        }
    ],
    "groups": [
        {
            "group_id": "account-history",
            "label": "Account History",
            "description": "Tenure and demographic fields.",
        }
    ],
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
}


def test_customization_endpoint_returns_200_with_payload(monkeypatch):
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )
        # telco-customer-churn's real registry entry is needs_review, which
        # the shared S0117 access guard now enforces on this route too --
        # isolate the loader behavior under test from that access gate.
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )
        api_main.load_public_predict_view_customization = (
            lambda dataset_slug, view_id, active_release: _VALID_CUSTOMIZATION
        )
        response = api_main.get_predict_view_customization("telco-customer-churn", "churn-risk-overview")
        assert not hasattr(response, "status_code") or response.status_code == 200
        if hasattr(response, "status_code"):
            payload = _response_json(response)
        else:
            payload = response
        assert payload["view_id"] == "churn-risk-overview"
        assert payload["dataset_slug"] == "telco-customer-churn"
        assert "view_copy" in payload
        assert "field_hints" in payload
        assert "groups" in payload
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_customization = original_load


def test_customization_endpoint_returns_customization_not_found_when_absent(monkeypatch):
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )

        def raise_not_found(dataset_slug, view_id, active_release):
            raise api_main.CustomizationNotFoundError("No customization for this view.")

        api_main.load_public_predict_view_customization = raise_not_found
        response = api_main.get_predict_view_customization("telco-customer-churn", "no-customization-view")
        assert response.status_code == 404
        payload = _response_json(response)
        assert payload["error_code"] == "CUSTOMIZATION_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_customization = original_load


def test_customization_endpoint_unknown_dataset_returns_dataset_not_found():
    original_resolve = api_main.resolve_dataset
    try:
        def raise_dataset_unavailable(dataset_slug):
            raise DatasetUnavailableError("Unknown dataset")

        api_main.resolve_dataset = raise_dataset_unavailable
        response = api_main.get_predict_view_customization("unknown-dataset", "churn-risk-overview")
        assert response.status_code == 404
        payload = _response_json(response)
        assert payload["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve


def test_customization_response_structure_matches_expected_fields(monkeypatch):
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )
        api_main.load_public_predict_view_customization = (
            lambda dataset_slug, view_id, active_release: _VALID_CUSTOMIZATION
        )
        response = api_main.get_predict_view_customization("telco-customer-churn", "churn-risk-overview")
        if hasattr(response, "status_code"):
            payload = _response_json(response)
        else:
            payload = response
        # view_copy structure
        assert "heading" in payload["view_copy"]
        assert "description" in payload["view_copy"]
        assert "usage_guidance" in payload["view_copy"]
        # field_hints structure
        hint = payload["field_hints"][0]
        assert "field_name" in hint
        assert "display_label" in hint
        assert "group" in hint
        # groups structure
        group = payload["groups"][0]
        assert "group_id" in group
        assert "label" in group
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_customization = original_load


# ---------------------------------------------------------------------------
# Real active-release resolution chain end-to-end (Project Spec S0153): proves
# the endpoint's real (unmocked) load_public_predict_view_customization ->
# load_public_contract chain resolves the registered active_release rather
# than replacing the loader itself with a lambda as the sole endpoint proof.
# ---------------------------------------------------------------------------

def test_customization_endpoint_exercises_real_loader_chain_without_replacing_it(monkeypatch, tmp_path):
    dataset_slug = "fixture-s0153-endpoint-dataset"
    view_id = "fixture-s0153-endpoint-view"
    active_release = "release-s0153-endpoint-001"

    customizations_path = tmp_path / "predict-view-customizations.json"
    customizations_path.write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.predict-view-customizations.v1",
                "predict_view_customizations": [
                    {
                        "schema_version": "1.0.0",
                        "view_id": view_id,
                        "dataset_slug": dataset_slug,
                        "view_copy": {
                            "heading": "Fixture Heading",
                            "description": "Fixture description.",
                            "usage_guidance": "Fixture guidance.",
                        },
                        "field_hints": [],
                        "groups": [],
                        "contract_precedence": {
                            "canonical_contracts_are_source_of_truth": True,
                            "customization_defines_runtime_validation": False,
                            "customization_duplicates_contract": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    releases_root = tmp_path / "releases"
    release_dir = releases_root / active_release
    release_dir.mkdir(parents=True)
    release_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"role": "public_contract", "reference": "public-contract.json"},
                    {"role": "contracts", "reference": "runtime-contract.json"},
                ]
            }
        ),
        encoding="utf-8",
    )
    release_dir.joinpath("public-contract.json").write_text(
        json.dumps({"features": []}), encoding="utf-8"
    )

    monkeypatch.setattr(
        customization_loader_module,
        "_DEFAULT_PREDICT_VIEW_CUSTOMIZATIONS_PATH",
        customizations_path,
    )
    monkeypatch.setenv("RELEASES_ROOT", str(releases_root))
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda _dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=active_release),
    )
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
    )

    # api_main.load_public_predict_view_customization is never replaced here --
    # the real loader (and its real load_public_contract call) runs end to end.
    response = api_main.get_predict_view_customization(dataset_slug, view_id)
    payload = response if not hasattr(response, "status_code") else _response_json(response)

    assert payload["view_id"] == view_id
    assert payload["dataset_slug"] == dataset_slug
    assert payload["view_copy"]["heading"] == "Fixture Heading"


def test_customization_endpoint_real_loader_chain_rejects_slug_named_release_directory(
    monkeypatch, tmp_path
):
    """
    If the endpoint or loader ever regresses to passing dataset_slug where
    active_release is required, this fixture would resolve against the
    slug-named directory below and incorrectly succeed. Only a directory
    named after the real registered active_release exists.
    """
    dataset_slug = "fixture-s0153-endpoint-dataset"
    view_id = "fixture-s0153-endpoint-view"
    registered_active_release = "release-s0153-endpoint-genuine-002"

    customizations_path = tmp_path / "predict-view-customizations.json"
    customizations_path.write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.predict-view-customizations.v1",
                "predict_view_customizations": [
                    {
                        "schema_version": "1.0.0",
                        "view_id": view_id,
                        "dataset_slug": dataset_slug,
                        "view_copy": {
                            "heading": "Fixture Heading",
                            "description": "Fixture description.",
                            "usage_guidance": "Fixture guidance.",
                        },
                        "field_hints": [],
                        "groups": [],
                        "contract_precedence": {
                            "canonical_contracts_are_source_of_truth": True,
                            "customization_defines_runtime_validation": False,
                            "customization_duplicates_contract": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    releases_root = tmp_path / "releases"
    slug_named_dir = releases_root / dataset_slug
    slug_named_dir.mkdir(parents=True)
    slug_named_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"role": "public_contract", "reference": "public-contract.json"},
                    {"role": "contracts", "reference": "runtime-contract.json"},
                ]
            }
        ),
        encoding="utf-8",
    )
    slug_named_dir.joinpath("public-contract.json").write_text(
        json.dumps({"features": []}), encoding="utf-8"
    )

    monkeypatch.setattr(
        customization_loader_module,
        "_DEFAULT_PREDICT_VIEW_CUSTOMIZATIONS_PATH",
        customizations_path,
    )
    monkeypatch.setenv("RELEASES_ROOT", str(releases_root))
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda _dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug, active_release=registered_active_release
        ),
    )
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
    )

    response = api_main.get_predict_view_customization(dataset_slug, view_id)
    assert response.status_code == 404
    payload = _response_json(response)
    assert payload["error_code"] == "CUSTOMIZATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Real-registry regression: M27-01
# ---------------------------------------------------------------------------

_REAL_REGISTRY_PATH = REPO_ROOT / "registry" / "datasets.json"
_REAL_RELEASES_ROOT = REPO_ROOT / "releases"


def test_real_registry_listing_accepts_empty_public_state():
    result = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    assert isinstance(result, list)
    if not result:
        assert result == []


def test_fixture_registry_listing_safe_fields_non_empty():
    with tempfile.TemporaryDirectory() as tmp:
        result = list_datasets(registry_path=_write_registry(Path(tmp), _BASE_REGISTRY))
    entry = result[0]
    assert entry.title
    assert entry.summary
    assert entry.domain
    assert entry.visibility


# Project Spec S0054: bank-marketing is no longer required to exist in the
# real versioned registry/datasets.json. Multi-dataset listing coverage is
# proven with a fixture-local registry instead of depending on a second real
# entry.
_TWO_DATASET_FIXTURE_REGISTRY = {
    **_BASE_REGISTRY,
    "datasets": [
        _VALID_ENTRY,
        {
            "dataset_slug": "second-example-dataset",
            "active_release": "release-20260617-002",
            "public_metadata": {
                "title": "Second Example Dataset",
                "summary": "Second fixture dataset for multi-dataset listing coverage.",
                "domain": "example",
                "visibility": "public",
                "tags": ["example", "second"],
            },
        },
    ],
}


def test_fixture_multi_dataset_registry_listing_includes_both_datasets():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _TWO_DATASET_FIXTURE_REGISTRY)
        result = list_datasets(registry_path=path)
        slugs = {d.dataset_slug for d in result}
        assert slugs == {"example-dataset", "second-example-dataset"}
        second = next(d for d in result if d.dataset_slug == "second-example-dataset")
        assert second.title
        assert second.summary
        assert second.domain
        assert second.visibility


def test_real_registry_listing_no_active_release_in_any_item():
    result = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    for item in result:
        assert "active_release" not in item._asdict()


def test_real_registry_listing_safe_fields_only_on_all_items():
    result = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    for item in result:
        keys = set(item._asdict().keys())
        assert keys == _PUBLIC_LISTING_KEYS


def test_fixture_multi_dataset_registry_resolve_second_dataset_succeeds():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _TWO_DATASET_FIXTURE_REGISTRY)
        resolved = resolve_dataset("second-example-dataset", registry_path=path)
        assert resolved.dataset_slug == "second-example-dataset"
        assert resolved.active_release == "release-20260617-002"


def test_real_registry_listing_envelope_shape():
    result = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    response = {"datasets": [d._asdict() for d in result]}
    assert "datasets" in response
    assert isinstance(response["datasets"], list)
    for item in response["datasets"]:
        assert "dataset_slug" in item
        assert "title" in item
        assert "summary" in item
        assert "domain" in item
        assert "visibility" in item
        assert "tags" in item
        assert "active_release" not in item


# ---------------------------------------------------------------------------
# Real-release dataset home payloads: M27-02
# ---------------------------------------------------------------------------

def _real_release_dataset_pairs():
    """
    Fixed (dataset_slug, active_release) pairs read directly against
    releases/, decoupled from the live registry/datasets.json (Project Spec
    S0054): bank-marketing's release-20260620-002 is preserved as a
    historical release artifact for this payload-shape regression even
    though the dataset itself is no longer a required real-registry entry.
    """
    return [
        SimpleNamespace(dataset_slug="telco-customer-churn", active_release="release-20260619-001"),
        SimpleNamespace(dataset_slug="bank-marketing", active_release="release-20260620-002"),
    ]


def _assert_no_internal_public_exposure(payload):
    serialized = json.dumps(payload, sort_keys=True)
    assert "raw_logs" not in serialized
    assert "raw_api_payload" not in serialized
    assert "evidence/" not in serialized
    assert "/home/" not in serialized
    assert "/workspace/" not in serialized


def test_real_release_dataset_home_context_payload_shape():
    for resolved in _real_release_dataset_pairs():
        context = api_main.load_public_context(
            resolved.active_release,
            releases_root=_REAL_RELEASES_ROOT,
        )
        response = {
            "dataset_slug": resolved.dataset_slug,
            "context": context,
        }

        assert response["dataset_slug"] == resolved.dataset_slug
        assert isinstance(response["context"], dict)
        assert isinstance(response["context"].get("title"), str)
        assert response["context"]["title"]
        assert isinstance(response["context"].get("summary"), str)
        assert response["context"]["summary"]
        assert isinstance(response["context"].get("domain"), str)
        assert response["context"]["domain"]
        assert "active_release" not in response["context"]
        assert "run_id" not in response["context"]
        _assert_no_internal_public_exposure(response)


def test_real_release_dataset_home_metrics_payload_shape():
    """
    Project Spec S0127: both fixed historical (legacy evaluation-wrapped)
    releases must be returned through the exact same stable public
    projection -- no top-level dataset_slug/release_id, split_name (not the
    legacy split key), and alias-normalized metric ids (roc_auc, not
    auc_roc).
    """
    for resolved in _real_release_dataset_pairs():
        metrics = api_main.load_public_metrics(
            resolved.active_release,
            releases_root=_REAL_RELEASES_ROOT,
        )
        response = {
            "dataset_slug": resolved.dataset_slug,
            "metrics": metrics,
        }

        assert response["dataset_slug"] == resolved.dataset_slug
        assert isinstance(response["metrics"], dict)
        assert set(response["metrics"].keys()) == {"evaluation"}
        evaluation = response["metrics"]["evaluation"]
        assert isinstance(evaluation, dict)
        assert isinstance(evaluation.get("split_name"), str)
        assert isinstance(evaluation.get("sample_size"), int)
        assert evaluation["sample_size"] > 0
        values = evaluation.get("metrics")
        assert isinstance(values, dict)
        for metric_name in ("accuracy", "precision", "recall", "f1_score", "roc_auc"):
            assert isinstance(values.get(metric_name), (int, float))
        assert evaluation.get("metric_order") == ["accuracy", "precision", "recall", "f1_score", "roc_auc"]
        _assert_no_internal_public_exposure(response)


def test_public_metrics_endpoint_projects_current_active_release_training_metrics_v1_shape():
    """
    Project Spec S0127's own "Current active release regression" acceptance
    criterion: the real active release's training-metrics.v1 artifact
    (releases/release-20260721t124721z/metrics/metrics.json) must project
    to the exact documented stable shape, with no Precision/Recall
    fabricated and internal training fields absent.
    """
    resolved = SimpleNamespace(
        dataset_slug="telco-customer-churn", active_release="release-20260721t124721z"
    )
    metrics = api_main.load_public_metrics(
        resolved.active_release,
        releases_root=_REAL_RELEASES_ROOT,
    )
    response = {"dataset_slug": resolved.dataset_slug, "metrics": metrics}

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "evaluation"
    assert evaluation["sample_size"] == 2114
    assert evaluation["primary_metric_id"] == "roc_auc"
    assert evaluation["metrics"] == {
        "roc_auc": 0.8435590708800057,
        "f1_score": 0.7939456048600292,
        "pr_auc": 0.6656143652383235,
    }
    assert evaluation["metric_order"] == ["roc_auc", "f1_score", "pr_auc"]
    assert "precision" not in evaluation["metrics"]
    assert "recall" not in evaluation["metrics"]
    _assert_no_internal_public_exposure(response)


def _s0127_write_metrics_release(releases_root: Path, release_id: str, metrics_payload: dict) -> None:
    release_dir = releases_root / release_id
    _s0101_write_release(
        release_dir,
        artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
    )
    _s0101_write_artifact_file(release_dir, "metrics/metrics.json", metrics_payload)


def test_public_metrics_loader_omits_internal_training_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-001",
            {
                "artifact_kind": "training_metrics",
                "created_at": "2026-07-21T12:47:21.660429Z",
                "evidence_policy": {"secrets_prohibited": True},
                "hashes": {"algorithm": "sha256", "execution_contract_sha256": "deadbeef"},
                "metric_source": {
                    "split_name": "evaluation",
                    "split_size": 500,
                    "random_seed": 0,
                },
                "metrics": {
                    "primary_metric": {"name": "roc_auc", "value": 0.9},
                    "secondary_metrics": [],
                },
                "path_references": {"dataset_path": "pipeline/prepared/x/prepared-data.csv"},
                "schema_version": "training-metrics.v1",
                "training_run_identity": {"run_id": "train-20260101T000000Z"},
            },
        )
        metrics = api_main.load_public_metrics("release-s0127-001", releases_root=releases_root)
        serialized = json.dumps(metrics)
        for internal_marker in (
            "artifact_kind",
            "created_at",
            "hashes",
            "evidence_policy",
            "path_references",
            "training_run_identity",
            "random_seed",
            "prepared-data.csv",
            "train-20260101T000000Z",
        ):
            assert internal_marker not in serialized
        assert metrics == {
            "evaluation": {
                "split_name": "evaluation",
                "sample_size": 500,
                "primary_metric_id": "roc_auc",
                "metrics": {"roc_auc": 0.9},
                "metric_order": ["roc_auc"],
            }
        }


def test_public_metrics_loader_f1_alias_resolves_to_f1_score():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-002",
            {"evaluation": {"split_name": "evaluation", "sample_size": 10, "metrics": {"f1": 0.5}}},
        )
        metrics = api_main.load_public_metrics("release-s0127-002", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"] == {"f1_score": 0.5}


def test_public_metrics_loader_auc_roc_alias_distinguishes_from_pr_auc():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-003",
            {
                "evaluation": {
                    "split_name": "evaluation",
                    "sample_size": 10,
                    "metrics": {"auc_roc": 0.81, "pr_auc": 0.62},
                }
            },
        )
        metrics = api_main.load_public_metrics("release-s0127-003", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"] == {"roc_auc": 0.81, "pr_auc": 0.62}


def test_public_metrics_loader_preserves_valid_zero_metric_value():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-004",
            {"evaluation": {"split_name": "evaluation", "sample_size": 10, "metrics": {"precision": 0.0}}},
        )
        metrics = api_main.load_public_metrics("release-s0127-004", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"]["precision"] == 0.0
        assert "precision" in metrics["evaluation"]["metric_order"]


def test_public_metrics_loader_rejects_non_finite_and_malformed_metric_values():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0127-005"
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
        )
        metrics_path = release_dir / "metrics" / "metrics.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        # Written directly (not via json.dumps) since NaN/Infinity are not
        # standard JSON but Python's json module both emits and parses them
        # by default -- this exercises the exact malformed-value boundary a
        # hand-authored or buggy upstream artifact could still produce.
        metrics_path.write_text(
            json.dumps(
                {
                    "evaluation": {
                        "split_name": "evaluation",
                        "sample_size": 10,
                        "metrics": {
                            "roc_auc": float("nan"),
                            "f1_score": float("inf"),
                            "pr_auc": float("-inf"),
                            "precision": True,
                            "recall": "0.9",
                            "accuracy": {"nested": 1},
                            "log_loss": [0.1],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        metrics = api_main.load_public_metrics("release-s0127-005", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"] == {}
        assert metrics["evaluation"]["metric_order"] == []


def test_public_metrics_loader_duplicate_alias_primary_wins_over_secondary():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-006",
            {
                "metric_source": {"split_name": "evaluation", "split_size": 10},
                "metrics": {
                    "primary_metric": {"name": "auc_roc", "value": 0.75},
                    "secondary_metrics": [{"name": "roc_auc", "value": 0.11}],
                },
            },
        )
        metrics = api_main.load_public_metrics("release-s0127-006", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"]["roc_auc"] == 0.75
        assert metrics["evaluation"]["primary_metric_id"] == "roc_auc"


def test_public_metrics_loader_duplicate_alias_first_valid_wins_without_primary():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0127-007",
            {
                "evaluation": {
                    "split_name": "evaluation",
                    "sample_size": 10,
                    "metrics": {"auc_roc": 0.2, "roc_auc": 0.3},
                }
            },
        )
        metrics = api_main.load_public_metrics("release-s0127-007", releases_root=releases_root)
        # "auc_roc" and "roc_auc" are distinct JSON keys (no dict-overwrite
        # collision happens during parsing) -- with no primary_metric in
        # play, the loader's own first-valid-declared-value-wins policy
        # must pick the first declared entry (auc_roc = 0.2), not the
        # second (roc_auc = 0.3).
        assert metrics["evaluation"]["metrics"]["roc_auc"] == 0.2


def test_public_metrics_loader_rejects_reference_escaping_release_directory():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0127-008"
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "metrics", "reference": "../../etc/passwd"}],
        )
        raised = False
        try:
            api_main.load_public_metrics("release-s0127-008", releases_root=releases_root)
        except api_main.PublicMetricsUnavailableError:
            raised = True
        assert raised, "Expected PublicMetricsUnavailableError for an escaping reference"


def test_public_metrics_loader_missing_metrics_role_returns_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0127-009"
        _s0101_write_release(release_dir, artifacts=[])
        raised = False
        try:
            api_main.load_public_metrics("release-s0127-009", releases_root=releases_root)
        except api_main.PublicMetricsUnavailableError:
            raised = True
        assert raised, "Expected PublicMetricsUnavailableError when no metrics role is declared"


def test_public_metrics_loader_invalid_non_dict_artifact_returns_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0127-010"
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
        )
        metrics_path = release_dir / "metrics" / "metrics.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        raised = False
        try:
            api_main.load_public_metrics("release-s0127-010", releases_root=releases_root)
        except api_main.PublicMetricsUnavailableError:
            raised = True
        assert raised, "Expected PublicMetricsUnavailableError for a non-object metrics artifact"


def test_public_metrics_loader_flat_top_level_shape_never_raises():
    """
    A bare release fixture that declares scores directly at the metrics
    artifact's top level, with no evaluation/metric_source wrapper at all
    (the shape tests/api/test_public_browser_flow.py's fixture release
    already uses), must still project successfully rather than being
    treated as a malformed artifact.
    """
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(releases_root, "release-s0127-011", {"accuracy": 0.9})
        metrics = api_main.load_public_metrics("release-s0127-011", releases_root=releases_root)
        assert metrics["evaluation"]["metrics"] == {"accuracy": 0.9}


# --- Project Spec S0191: explicit training-metrics.external-fitted-model.v1
# public projector -----------------------------------------------------------


def _s0191_external_metrics_payload(
    *,
    include_final_test: bool = False,
    final_test_completed: bool = True,
    validation_metrics: list | None = None,
    final_test_metrics: list | None = None,
    validation_row_count: int | None = 500,
) -> dict:
    payload: dict = {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-01T00:00:00Z",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "dataset_slug": "sample-dataset",
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "used_for_fitting": True,
            "used_for_model_selection": True,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            # Never the public holdout evaluation -- distinct value from
            # validation/test below so a leak is caught deterministically.
            "metrics": [{"name": "roc_auc", "value": 0.99}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "used_for_fitting": False,
            "used_for_model_selection": True,
            "used_for_threshold_selection": True,
            "sealed_before_finalization": False,
            "metrics": (
                validation_metrics
                if validation_metrics is not None
                else [
                    {"name": "roc_auc", "value": 0.80},
                    {"name": "average_precision", "value": 0.62},
                ]
            ),
        },
    }
    if validation_row_count is not None:
        payload["validation_evaluation"]["row_count"] = validation_row_count
    if include_final_test:
        payload["final_test_evaluation"] = {
            "partition_role": "test",
            "used_for_fitting": False,
            "used_for_model_selection": False,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": True,
            "completed": final_test_completed,
            "evaluation_count": 1 if final_test_completed else 0,
            "metrics": (
                (final_test_metrics if final_test_metrics is not None else [{"name": "roc_auc", "value": 0.77}])
                if final_test_completed
                else []
            ),
        }
        if final_test_completed:
            payload["final_test_evaluation"]["row_count"] = 300
    return payload


def test_public_metrics_loader_external_fitted_model_uses_validation_when_final_test_absent():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(releases_root, "release-s0191-001", _s0191_external_metrics_payload())
        metrics = api_main.load_public_metrics("release-s0191-001", releases_root=releases_root)
        evaluation = metrics["evaluation"]
        assert evaluation["split_name"] == "validation"
        assert evaluation["sample_size"] == 500
        assert evaluation["primary_metric_id"] is None
        assert evaluation["metrics"] == {"roc_auc": 0.80, "pr_auc": 0.62}


def test_public_metrics_loader_external_fitted_model_prefers_completed_final_test():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0191-002",
            _s0191_external_metrics_payload(
                include_final_test=True,
                final_test_completed=True,
                final_test_metrics=[{"name": "roc_auc", "value": 0.77}],
            ),
        )
        metrics = api_main.load_public_metrics("release-s0191-002", releases_root=releases_root)
        evaluation = metrics["evaluation"]
        assert evaluation["split_name"] == "test"
        assert evaluation["sample_size"] == 300
        assert evaluation["metrics"] == {"roc_auc": 0.77}


def test_public_metrics_loader_external_fitted_model_ignores_incomplete_final_test():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0191-003",
            _s0191_external_metrics_payload(include_final_test=True, final_test_completed=False),
        )
        metrics = api_main.load_public_metrics("release-s0191-003", releases_root=releases_root)
        assert metrics["evaluation"]["split_name"] == "validation"


def test_public_metrics_loader_external_fitted_model_cross_validation_never_exposed():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(releases_root, "release-s0191-004", _s0191_external_metrics_payload())
        metrics = api_main.load_public_metrics("release-s0191-004", releases_root=releases_root)
        # cross_validation_summary's roc_auc value (0.99) must never surface
        # as the projected public metric -- only validation_evaluation's
        # (0.80) may.
        assert metrics["evaluation"]["metrics"]["roc_auc"] == 0.80


def test_public_metrics_loader_external_fitted_model_unsupported_metric_omitted():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(
            releases_root,
            "release-s0191-005",
            _s0191_external_metrics_payload(
                validation_metrics=[
                    {"name": "roc_auc", "value": 0.80},
                    {"name": "brier_score", "value": 0.1},
                    {"name": "f2", "value": 0.5},
                ]
            ),
        )
        metrics = api_main.load_public_metrics("release-s0191-005", releases_root=releases_root)
        assert set(metrics["evaluation"]["metrics"]) == {"roc_auc"}


def test_public_metrics_loader_external_fitted_model_omits_internal_evidence_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0127_write_metrics_release(releases_root, "release-s0191-006", _s0191_external_metrics_payload())
        metrics = api_main.load_public_metrics("release-s0191-006", releases_root=releases_root)
        serialized = json.dumps(metrics)
        for internal_marker in (
            "evidence_identity",
            "cross_validation_summary",
            "used_for_fitting",
            "sealed_before_finalization",
            "artifact_kind",
            "created_at",
            "sample-dataset",
        ):
            assert internal_marker not in serialized


def test_real_release_dataset_home_model_card_payload_shape():
    for resolved in _real_release_dataset_pairs():
        model_card = api_main.load_public_model_card(
            resolved.active_release,
            releases_root=_REAL_RELEASES_ROOT,
        )
        response = {
            "dataset_slug": resolved.dataset_slug,
            "model_card": model_card,
        }

        assert response["dataset_slug"] == resolved.dataset_slug
        assert set(response["model_card"].keys()) == {"content", "format"}
        assert response["model_card"]["format"] == "markdown"
        assert isinstance(response["model_card"]["content"], str)
        assert response["model_card"]["content"].strip()
        _assert_no_internal_public_exposure(response)


def test_real_release_dataset_home_visualizations_degrade_safely(monkeypatch):
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_visualizations = api_main.load_public_visualizations
    try:
        # telco-customer-churn's real registry entry is needs_review; the
        # shared S0117 access guard would otherwise return DATASET_MAINTENANCE
        # before this test's loader-degradation behavior is ever exercised.
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )

        for resolved in _real_release_dataset_pairs():
            api_main.resolve_dataset = lambda dataset_slug, resolved=resolved: SimpleNamespace(
                dataset_slug=dataset_slug,
                active_release=resolved.active_release,
            )
            api_main.load_public_visualizations = (
                lambda active_release: original_load_public_visualizations(
                    active_release,
                    releases_root=_REAL_RELEASES_ROOT,
                )
            )

            response = api_main.get_public_visualizations(resolved.dataset_slug)
            assert response.status_code == 503
            payload = _response_json(response)
            assert payload["error_type"] == "visualizations_unavailable"
            assert payload["error_code"] == "VISUALIZATIONS_UNAVAILABLE"
            _assert_no_internal_public_exposure(payload)
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_visualizations = original_load_public_visualizations


# ---------------------------------------------------------------------------
# S0128: analytical visualizations generation and release packaging
# ---------------------------------------------------------------------------

_S0128_VALID_ARTIFACT = {
    "schema_version": "analytical-visualizations.v1",
    "artifact_kind": "analytical_visualizations",
    "created_at": "2026-07-21T12:47:21Z",
    "training_run_identity": {
        "dataset_slug": "telco-customer-churn",
        "run_id": "train-20260721T124721Z",
        "output_directory": "pipeline/training-runs/telco-customer-churn/train-20260721T124721Z/",
    },
    "charts": [
        {
            "id": "target_distribution",
            "title": "Target Distribution",
            "type": "bar",
            "x_label": "Churn",
            "y_label": "Rows",
            "data": [{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
        },
        {
            "id": "feature_importance",
            "title": "Feature Importance",
            "type": "bar",
            "x_label": "Feature",
            "y_label": "Importance",
            "data": [{"name": "tenure", "value": 0.4}, {"name": "Contract", "value": 0.3}],
        },
    ],
    "target_distribution_method": {
        "population_kind": "prepared_dataset",
        "row_count": 7043,
        "target_column": "Churn",
    },
    "feature_importance_method": {
        "model_family": "gradient_boosting",
        "source": "estimator.feature_importances_",
        "total_source_feature_count": 19,
        "omitted_source_feature_count": 9,
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


def test_public_visualizations_endpoint_returns_ready_payload_for_new_promoted_release(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0128-001"
        _s0101_write_artifact_file(
            release_dir, "visualizations/visualizations.json", _S0128_VALID_ARTIFACT
        )
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )
        monkeypatch.setattr(
            api_main,
            "resolve_dataset",
            lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0128-001"
            ),
        )
        monkeypatch.setattr(
            api_main,
            "load_public_visualizations",
            lambda active_release: _load_public_visualizations_real(active_release, releases_root),
        )

        response = api_main.get_public_visualizations("example-dataset")

        # Project Spec S0205: the historical prepared_dataset row_count
        # (7043) agrees with the artifact's own Target Distribution total
        # (5174 + 1869), so the bounded dataset_statistics.instance_count
        # projection now accompanies the unchanged canonical charts.
        assert response == {
            "dataset_slug": "example-dataset",
            "visualizations": {
                "charts": _S0128_VALID_ARTIFACT["charts"],
                "dataset_statistics": {"instance_count": 7043},
            },
        }


def _load_public_visualizations_real(active_release, releases_root):
    import public_visualizations_loader

    return public_visualizations_loader.load_public_visualizations(
        active_release, releases_root=releases_root
    )


# --- S0193: analytical-visualizations.external-fitted-model.v1 profile
# projects the identical bounded public shape as the historical v1 profile.
_S0193_VALID_EXTERNAL_ARTIFACT = {
    "schema_version": "analytical-visualizations.external-fitted-model.v1",
    "artifact_kind": "analytical_visualizations",
    "model_source_mode": "validated_external_fitted_model",
    "created_at": "2026-08-12T12:00:00Z",
    "dataset_identity": {"dataset_slug": "telco-customer-churn"},
    "external_materialization_provenance": {
        "model_family": "hist_gradient_boosting",
        "external_evidence_reference": "artifacts/telco-customer-churn/analytical-visual-evidence.json",
        "external_evidence_sha256": "a" * 64,
    },
    "charts": [
        {
            "id": "target_distribution",
            "title": "Target Distribution",
            "type": "bar",
            "x_label": "Churn",
            "y_label": "Rows",
            "data": [{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
        },
        {
            "id": "feature_importance",
            "title": "Feature Importance",
            "type": "bar",
            "x_label": "Feature",
            "y_label": "Importance",
            "data": [{"name": "tenure", "value": 0.4}, {"name": "Contract", "value": 0.3}],
        },
    ],
    "target_distribution_method": {
        "population_kind": "external_prepared_dataset",
        "source": "external_prepared_evaluation_population",
        "target_column": "Churn",
    },
    "feature_importance_method": {
        "model_family": "hist_gradient_boosting",
        "source": "external_validated_fitted_model",
        "method": "permutation_importance",
        "total_source_feature_count": 19,
        "omitted_source_feature_count": 9,
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


def test_public_visualizations_endpoint_returns_ready_payload_for_external_fitted_model_release(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0193-001"
        _s0101_write_artifact_file(
            release_dir, "visualizations/visualizations.json", _S0193_VALID_EXTERNAL_ARTIFACT
        )
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )
        monkeypatch.setattr(
            api_main,
            "resolve_dataset",
            lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0193-001"
            ),
        )
        monkeypatch.setattr(
            api_main,
            "load_public_visualizations",
            lambda active_release: _load_public_visualizations_real(active_release, releases_root),
        )

        response = api_main.get_public_visualizations("example-dataset")

        # Project Spec S0205: the current Telco-style external_prepared_dataset
        # profile derives instance_count by summing its own validated Target
        # Distribution counts (5174 + 1869 = 7043) -- the canonical charts
        # remain byte-identical to the pre-S0205 projection.
        assert response == {
            "dataset_slug": "example-dataset",
            "visualizations": {
                "charts": _S0193_VALID_EXTERNAL_ARTIFACT["charts"],
                "dataset_statistics": {"instance_count": 7043},
            },
        }


def test_public_visualizations_loader_external_profile_never_exposes_provenance_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0193-002"
        _s0101_write_artifact_file(
            release_dir, "visualizations/visualizations.json", _S0193_VALID_EXTERNAL_ARTIFACT
        )
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )

        projection = api_main.load_public_visualizations(
            "release-s0193-002", releases_root=releases_root
        )

        serialized = json.dumps(projection)
        assert "external_materialization_provenance" not in serialized
        assert "external_evidence_reference" not in serialized
        assert "external_evidence_sha256" not in serialized
        assert "hist_gradient_boosting" not in serialized
        assert "dataset_identity" not in serialized


# ---------------------------------------------------------------------------
# S0205: dataset instances public authority and projection -- the bounded
# dataset_statistics.instance_count derivation added to the public
# visualizations loader.
# ---------------------------------------------------------------------------


def _s0205_write_visualizations(releases_root: Path, release_name: str, artifact: dict) -> Path:
    release_dir = releases_root / release_name
    _s0101_write_artifact_file(release_dir, "visualizations/visualizations.json", artifact)
    _s0101_write_release(
        release_dir,
        artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
    )
    return release_dir


def _s0205_historical_artifact(*, row_count, target_distribution_data) -> dict:
    method = {"population_kind": "prepared_dataset", "target_column": "Churn"}
    if row_count is not None:
        method["row_count"] = row_count
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-07-21T12:47:21Z",
        "charts": [
            {
                "id": "target_distribution",
                "title": "Target Distribution",
                "type": "bar",
                "x_label": "Churn",
                "y_label": "Rows",
                "data": target_distribution_data,
            },
            {
                "id": "feature_importance",
                "title": "Feature Importance",
                "type": "bar",
                "x_label": "Feature",
                "y_label": "Importance",
                "data": [{"name": "tenure", "value": 0.4}, {"name": "Contract", "value": 0.3}],
            },
        ],
        "target_distribution_method": method,
    }


def _s0205_external_artifact(*, target_distribution_data, method_override=None) -> dict:
    method = (
        method_override
        if method_override is not None
        else {"population_kind": "external_prepared_dataset", "target_column": "Churn"}
    )
    artifact = {
        "schema_version": "analytical-visualizations.external-fitted-model.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-12T12:00:00Z",
        "charts": [
            {
                "id": "target_distribution",
                "title": "Target Distribution",
                "type": "bar",
                "x_label": "Churn",
                "y_label": "Rows",
                "data": target_distribution_data,
            },
            {
                "id": "feature_importance",
                "title": "Feature Importance",
                "type": "bar",
                "x_label": "Feature",
                "y_label": "Importance",
                "data": [{"name": "tenure", "value": 0.4}, {"name": "Contract", "value": 0.3}],
            },
        ],
    }
    if method is not None:
        artifact["target_distribution_method"] = method
    return artifact


def test_public_visualizations_loader_historical_matching_row_count_projects_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-001",
            _s0205_historical_artifact(
                row_count=7043,
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-001", releases_root=releases_root)

        assert projection["dataset_statistics"] == {"instance_count": 7043}


def test_public_visualizations_loader_historical_row_count_chart_mismatch_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-002",
            _s0205_historical_artifact(
                # Declared row_count disagrees with the chart's own total
                # (5174 + 1869 = 7043) -- the disagreement itself is the
                # blocking condition, never resolved by trusting either side.
                row_count=9999,
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-002", releases_root=releases_root)

        assert "dataset_statistics" not in projection
        assert projection["charts"]


def test_public_visualizations_loader_historical_zero_row_count_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-003",
            _s0205_historical_artifact(
                row_count=0,
                target_distribution_data=[{"name": "No", "value": 0}, {"name": "Yes", "value": 0}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-003", releases_root=releases_root)

        assert "dataset_statistics" not in projection


def test_public_visualizations_loader_historical_non_integer_row_count_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-004",
            _s0205_historical_artifact(
                row_count=7043.5,
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-004", releases_root=releases_root)

        assert "dataset_statistics" not in projection
        assert projection["charts"]


def test_public_visualizations_loader_external_valid_counts_projects_summed_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-005",
            _s0205_external_artifact(
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-005", releases_root=releases_root)

        assert projection["dataset_statistics"] == {"instance_count": 7043}


def test_public_visualizations_loader_external_fractional_count_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-006",
            _s0205_external_artifact(
                # Finite and non-negative (so the canonical chart itself
                # stays valid and keeps rendering) but not integer-like --
                # never an authority for a whole-number population count.
                target_distribution_data=[{"name": "No", "value": 5174.5}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-006", releases_root=releases_root)

        assert "dataset_statistics" not in projection
        assert projection["charts"]


def test_public_visualizations_loader_missing_population_kind_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-007",
            _s0205_external_artifact(
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
                method_override={"target_column": "Churn"},
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-007", releases_root=releases_root)

        assert "dataset_statistics" not in projection
        assert projection["charts"]


def test_public_visualizations_loader_wrong_population_kind_no_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-008",
            _s0205_external_artifact(
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
                method_override={"population_kind": "synthetic_sample", "target_column": "Churn"},
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-008", releases_root=releases_root)

        assert "dataset_statistics" not in projection
        assert projection["charts"]


def test_public_visualizations_loader_negative_target_distribution_value_degrades_to_unavailable():
    # A negative Target Distribution value already fails the pre-existing
    # canonical chart validation (Project Spec S0128) -- the whole artifact
    # degrades to unavailable exactly as before, so no instance_count is
    # ever produced from it.
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-009",
            _s0205_external_artifact(
                target_distribution_data=[{"name": "No", "value": -5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        raised = False
        try:
            api_main.load_public_visualizations("release-s0205-009", releases_root=releases_root)
        except api_main.PublicVisualizationsUnavailableError:
            raised = True
        assert raised


def test_public_visualizations_loader_non_finite_target_distribution_value_degrades_to_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-010",
            _s0205_external_artifact(
                target_distribution_data=[
                    {"name": "No", "value": float("inf")},
                    {"name": "Yes", "value": 1869},
                ],
            ),
        )

        raised = False
        try:
            api_main.load_public_visualizations("release-s0205-010", releases_root=releases_root)
        except api_main.PublicVisualizationsUnavailableError:
            raised = True
        assert raised


def test_public_visualizations_loader_feature_importance_never_affects_instance_count():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        artifact = _s0205_external_artifact(
            target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
        )
        # A large, unrelated feature_importance total must never leak into
        # or influence the derived dataset population count.
        artifact["charts"][1]["data"] = [{"name": "tenure", "value": 999999}]
        _s0205_write_visualizations(releases_root, "release-s0205-011", artifact)

        projection = api_main.load_public_visualizations("release-s0205-011", releases_root=releases_root)

        assert projection["dataset_statistics"] == {"instance_count": 7043}


def test_public_visualizations_loader_dataset_statistics_never_exposes_internal_method_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _s0205_write_visualizations(
            releases_root,
            "release-s0205-012",
            _s0205_historical_artifact(
                row_count=7043,
                target_distribution_data=[{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            ),
        )

        projection = api_main.load_public_visualizations("release-s0205-012", releases_root=releases_root)

        assert set(projection["dataset_statistics"].keys()) == {"instance_count"}
        serialized = json.dumps(projection)
        assert "target_distribution_method" not in serialized
        assert "population_kind" not in serialized
        assert "prepared_dataset" not in serialized


def test_public_visualizations_endpoint_invalid_artifact_degrades_to_bounded_unavailable(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0128-002"
        malformed = {**_S0128_VALID_ARTIFACT, "schema_version": "analytical-visualizations.v0"}
        _s0101_write_artifact_file(release_dir, "visualizations/visualizations.json", malformed)
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )
        monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
        monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
        monkeypatch.setattr(
            api_main,
            "resolve_dataset_snapshot_readiness",
            lambda *_a, **_k: {"status": "current_release", "matches_active_release": True},
        )
        monkeypatch.setattr(
            api_main,
            "resolve_dataset",
            lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0128-002"
            ),
        )
        monkeypatch.setattr(
            api_main,
            "load_public_visualizations",
            lambda active_release: _load_public_visualizations_real(active_release, releases_root),
        )

        response = api_main.get_public_visualizations("example-dataset")

        assert response.status_code == 503
        payload = _response_json(response)
        assert payload["error_code"] == "VISUALIZATIONS_UNAVAILABLE"
        _assert_no_internal_public_exposure(payload)


def test_public_visualizations_loader_rejects_path_traversal_reference():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0128-003"
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "../../etc/passwd"}],
        )
        raised = False
        try:
            api_main.load_public_visualizations("release-s0128-003", releases_root=releases_root)
        except api_main.PublicVisualizationsUnavailableError:
            raised = True
        assert raised, "Expected PublicVisualizationsUnavailableError for an escaping reference"


def test_public_visualizations_loader_filters_internal_keys():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0128-004"
        artifact_with_internal_key = dict(_S0128_VALID_ARTIFACT)
        artifact_with_internal_key["internal"] = {"leaked": "should not appear"}
        _s0101_write_artifact_file(
            release_dir, "visualizations/visualizations.json", artifact_with_internal_key
        )
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )

        projection = api_main.load_public_visualizations(
            "release-s0128-004", releases_root=releases_root
        )

        assert set(projection.keys()) == {"charts", "dataset_statistics"}
        assert projection["charts"] == _S0128_VALID_ARTIFACT["charts"]


def test_public_visualizations_endpoint_never_loads_model_or_executes_inference():
    """The release directory declares no model_artifact role and contains no
    model bytes at all -- the loader must still succeed, proving it never
    needs to load a model or execute inference to build the projection."""
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0128-005"
        _s0101_write_artifact_file(
            release_dir, "visualizations/visualizations.json", _S0128_VALID_ARTIFACT
        )
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
        )
        assert not any((release_dir).rglob("*.pkl"))

        projection = api_main.load_public_visualizations(
            "release-s0128-005", releases_root=releases_root
        )
        assert projection["charts"]


def test_public_visualizations_endpoint_hidden_dataset_returns_maintenance(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: False)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release="irrelevant"),
    )

    response = api_main.get_public_visualizations("example-dataset")

    assert response.status_code == 503
    assert _response_json(response)["error_code"] == "DATASET_MAINTENANCE"


def test_public_visualizations_endpoint_needs_review_dataset_returns_maintenance(monkeypatch):
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: True)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release="irrelevant"),
    )

    response = api_main.get_public_visualizations("example-dataset")

    assert response.status_code == 503
    assert _response_json(response)["error_code"] == "DATASET_MAINTENANCE"


def test_public_visualizations_endpoint_not_found_dataset(monkeypatch):
    def _raise(_dataset_slug):
        raise DatasetUnavailableError("no such dataset")

    monkeypatch.setattr(api_main, "resolve_dataset", _raise)

    response = api_main.get_public_visualizations("does-not-exist")

    assert response.status_code == 404
    assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"


def test_authoring_context_visualizations_ready_reports_canonical_charts():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_visualizations = api_main.load_public_visualizations
    try:
        api_main.load_public_visualizations = lambda _release: {
            "charts": _S0128_VALID_ARTIFACT["charts"]
        }
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["visualizations"]["status"] == "ready"
        assert response["visualizations"]["data"]["charts"] == _S0128_VALID_ARTIFACT["charts"]
        assert response["contract"]["status"] == "ready"
        assert response["views"]["status"] == "ready"
    finally:
        api_main.load_public_visualizations = original_visualizations
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


# ---------------------------------------------------------------------------
# Real-release valid prediction flow: M27-03
# ---------------------------------------------------------------------------

def _valid_payload_from_contracts(public_contract, runtime_contract):
    public_feature_names = [
        feature["name"]
        for feature in public_contract["features"]
        if isinstance(feature, dict) and isinstance(feature.get("name"), str)
    ]
    runtime_features = {
        feature["name"]: feature
        for feature in runtime_contract["features"]
        if isinstance(feature, dict) and isinstance(feature.get("name"), str)
    }

    payload = {}
    for feature_name in public_feature_names:
        feature = runtime_features[feature_name]
        feature_type = feature["type"]
        constraints = feature.get("domain_constraints", {})
        if feature_type == "numeric":
            minimum = constraints.get("min", 0)
            maximum = constraints.get("max", minimum)
            payload[feature_name] = (minimum + maximum) / 2
        elif feature_type == "categorical":
            payload[feature_name] = constraints["values"][0]
        elif feature_type == "boolean":
            payload[feature_name] = False
        else:
            raise AssertionError(f"Unsupported runtime feature type: {feature_type}")
    return payload


def test_real_release_historical_bundle_without_binary_semantics_fails_safely():
    """
    Project Spec S0109: the real bank-marketing release (release-20260620-002)
    predates both S0107 (release-relative packaged model) and S0108
    (result_semantics) -- its bundle has no runtime_execution.loader_strategy
    and no result_semantics block at all. Hitting the real public inference
    route for this historical release must now fail safely (no legacy
    label/confidence fallback, no invented binary semantics), exercising the
    "historical bundles lacking S0108 semantics fail safely without fallback"
    acceptance criterion against a real, non-synthetic release.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        # Project Spec S0054: bank-marketing's release is read directly by
        # release_id, decoupled from the live registry (see
        # _real_release_dataset_pairs above).
        resolved = SimpleNamespace(
            dataset_slug="bank-marketing", active_release="release-20260620-002"
        )
        public_contract = api_main.load_public_contract(
            resolved.active_release,
            releases_root=_REAL_RELEASES_ROOT,
        )
        runtime_contract = original_load_contract(
            resolved.active_release,
            releases_root=_REAL_RELEASES_ROOT,
        )
        payload = _valid_payload_from_contracts(public_contract, runtime_contract)

        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=resolved.dataset_slug,
            active_release=resolved.active_release,
        )
        api_main.load_contract = (
            lambda active_release: original_load_contract(
                active_release,
                releases_root=_REAL_RELEASES_ROOT,
            )
        )
        api_main._inference_releases_root = lambda: _REAL_RELEASES_ROOT

        response = api_main.validate_dataset_inference_payload(
            resolved.dataset_slug,
            payload=payload,
        )

        assert response.status_code == 503
        payload_body = _response_json(response)
        assert payload_body["error_code"] == "INFERENCE_FAILURE"
        _assert_no_internal_public_exposure(payload_body)
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# Real-route invalid prediction payload failures: M27-04
# ---------------------------------------------------------------------------

_M27_INVALID_PAYLOAD_RUNTIME_CONTRACT = {
    "schema_version": "atlas.dataflow.runtime_contract.v1",
    "features": [
        {
            "name": "account_age_months",
            "type": "numeric",
            "required": True,
            "domain_constraints": {"min": 0, "max": 120},
        },
        {
            "name": "customer_segment",
            "type": "categorical",
            "required": True,
            "domain_constraints": {"values": ["standard", "premium"]},
        },
        {
            "name": "has_support_plan",
            "type": "boolean",
            "required": True,
        },
    ],
}

_M27_VALID_FIXTURE_PAYLOAD = {
    "account_age_months": 24,
    "customer_segment": "standard",
    "has_support_plan": False,
}


def _m27_invalid_case_payloads():
    missing_required = dict(_M27_VALID_FIXTURE_PAYLOAD)
    del missing_required["account_age_months"]

    numeric_type_mismatch = dict(_M27_VALID_FIXTURE_PAYLOAD)
    numeric_type_mismatch["account_age_months"] = "twenty-four"

    categorical_type_mismatch = dict(_M27_VALID_FIXTURE_PAYLOAD)
    categorical_type_mismatch["customer_segment"] = 10

    boolean_type_mismatch = dict(_M27_VALID_FIXTURE_PAYLOAD)
    boolean_type_mismatch["has_support_plan"] = "false"

    numeric_domain_violation = dict(_M27_VALID_FIXTURE_PAYLOAD)
    numeric_domain_violation["account_age_months"] = 121

    categorical_domain_violation = dict(_M27_VALID_FIXTURE_PAYLOAD)
    categorical_domain_violation["customer_segment"] = "unsupported"

    return [
        (
            missing_required,
            "account_age_months",
            "MISSING_REQUIRED_FIELD",
            "missing_required_field",
        ),
        (
            numeric_type_mismatch,
            "account_age_months",
            "TYPE_MISMATCH",
            "type_mismatch",
        ),
        (
            categorical_type_mismatch,
            "customer_segment",
            "TYPE_MISMATCH",
            "type_mismatch",
        ),
        (
            boolean_type_mismatch,
            "has_support_plan",
            "TYPE_MISMATCH",
            "type_mismatch",
        ),
        (
            numeric_domain_violation,
            "account_age_months",
            "DOMAIN_VIOLATION",
            "domain_violation",
        ),
        (
            categorical_domain_violation,
            "customer_segment",
            "DOMAIN_VIOLATION",
            "domain_violation",
        ),
    ]


def _assert_invalid_payload_response(response, expected_field, expected_code, expected_violation):
    assert response.status_code == 422
    payload = _response_json(response)
    assert payload["error_type"] == "invalid_payload"
    assert payload["error_code"] == "INVALID_PAYLOAD"
    assert isinstance(payload["message"], str)
    assert payload["message"]
    assert isinstance(payload["errors"], list)
    assert payload["errors"]

    error = payload["errors"][0]
    assert set(error.keys()) == {"error_code", "message", "field", "violation"}
    assert error["error_code"] == expected_code
    assert isinstance(error["message"], str)
    assert error["message"]
    assert error["field"] == expected_field
    assert error["violation"] == expected_violation
    _assert_no_internal_public_exposure(payload)


def test_real_route_non_object_prediction_payload_fails_before_contract_and_prediction():
    """
    Project Spec S0117: access classification now runs before payload
    validation, so dataset resolution genuinely happens for a malformed
    payload on a ready dataset -- but contract loading, bundle loading, and
    prediction execution still must never run for an invalid payload.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_visibility = api_main.resolve_dataset_visibility
    original_needs_review = api_main.is_dataset_needs_review
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m27-fixture",
        )
        api_main.resolve_dataset_visibility = lambda _dataset_slug: True
        api_main.is_dataset_needs_review = lambda _dataset_slug: False
        api_main.load_contract = (
            lambda _active_release: (_ for _ in ()).throw(
                AssertionError("non-object payload should fail before contract loading")
            )
        )
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("non-object payload should fail before prediction execution")
            )
        )

        response = api_main.validate_dataset_inference_payload(
            "fixture-dataset",
            payload=["not", "an", "object"],
        )

        _assert_invalid_payload_response(
            response,
            "payload",
            "TYPE_MISMATCH",
            "type_mismatch",
        )
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main.resolve_dataset_visibility = original_visibility
        api_main.is_dataset_needs_review = original_needs_review
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_real_route_non_object_prediction_payload_returns_not_found_for_unknown_dataset():
    """
    Project Spec S0117 required precedence: unknown dataset + malformed
    body returns DATASET_NOT_FOUND, never a payload-validation error --
    access classification happens first.
    """
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    try:
        api_main.load_contract = (
            lambda _active_release: (_ for _ in ()).throw(
                AssertionError("unknown dataset should never reach contract loading")
            )
        )
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("unknown dataset should never reach prediction execution")
            )
        )

        response = api_main.validate_dataset_inference_payload(
            "dataset-that-does-not-exist",
            payload=["not", "an", "object"],
        )

        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction


def test_real_route_contract_invalid_prediction_payloads_fail_before_prediction_execution():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m27-invalid-fixture",
        )
        api_main.load_contract = lambda _active_release: _M27_INVALID_PAYLOAD_RUNTIME_CONTRACT
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("invalid payload should fail before prediction execution")
            )
        )

        for payload, expected_field, expected_code, expected_violation in _m27_invalid_case_payloads():
            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload=payload,
            )

            _assert_invalid_payload_response(
                response,
                expected_field,
                expected_code,
                expected_violation,
            )
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# Project Spec S0109: a schema-valid binary-classification-result.v1 example,
# reused wherever a test mocks api_main.execute_prediction's new return shape.
# ---------------------------------------------------------------------------

_S0109_VALID_BINARY_RESULT = {
    "schema_version": "binary-classification-result.v1",
    "problem_type": "binary_classification",
    "predicted_class": {"class_id": "Yes"},
    "positive_class": {"class_id": "Yes", "event_label": "Churn"},
    "positive_class_probability": 0.68,
    "class_probabilities": [
        {"class_id": "No", "probability": 0.32},
        {"class_id": "Yes", "probability": 0.68},
    ],
    "decision": {"threshold": 0.5, "predicted_positive": True},
    "interpretation": {
        "preset": "risk",
        "band_id": "high",
        "bands": [
            {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
            {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
            {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
        ],
    },
    "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
}


# ---------------------------------------------------------------------------
# Real-route select-path categorical domain validation: M32-03
# ---------------------------------------------------------------------------

_M32_SELECT_PATH_RUNTIME_CONTRACT = {
    "schema_version": "atlas.dataflow.runtime_contract.v1",
    "features": [
        {
            "name": "customer_segment",
            "type": "categorical",
            "required": True,
            "domain_constraints": {"values": ["standard", "premium", "enterprise"]},
        },
    ],
}


def test_real_route_select_projected_categorical_value_domain_validation():
    """
    Confirms payload_validator's DOMAIN_VIOLATION check governs a categorical
    value shaped like a real M32-01 options projection (contract_derivation's
    _derive_public_options derives {value, label} pairs from
    domain_constraints.values, in declaration order -- the same values a
    real <select> populated from those options would submit) for both an
    accepted in-options value and a rejected out-of-options value, exercised
    through the real inference route.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_project_result_contract = api_main.project_result_contract
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m32-03-select-path-fixture",
        )
        api_main.load_contract = lambda _active_release: _M32_SELECT_PATH_RUNTIME_CONTRACT
        api_main.project_result_contract = lambda _declaration: {
            "status": "available", "semantics": _S0109_RESULT_SEMANTICS
        }

        with tempfile.TemporaryDirectory() as releases_root:
            release_dir = Path(releases_root) / "release-m32-03-select-path-fixture"
            _s0109_write_release_with_bundle(release_dir, _s0212_binary_fixture_manifest())
            api_main._inference_releases_root = lambda: Path(releases_root)
            api_main.execute_prediction = lambda *_args, **_kwargs: {
                "result": _S0109_VALID_BINARY_RESULT
            }

            accepted_response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload={"customer_segment": "premium"},
            )

            assert not hasattr(accepted_response, "status_code")
            assert accepted_response["result"] == _S0109_VALID_BINARY_RESULT
            _assert_no_internal_public_exposure(accepted_response)

        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("out-of-options payload should fail before prediction execution")
            )
        )

        rejected_response = api_main.validate_dataset_inference_payload(
            "fixture-dataset",
            payload={"customer_segment": "unsupported"},
        )

        _assert_invalid_payload_response(
            rejected_response,
            "customer_segment",
            "DOMAIN_VIOLATION",
            "domain_violation",
        )
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main.project_result_contract = original_project_result_contract
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# Project Spec S0152: optional-feature missing-value materialization and the
# new RUNTIME_INPUT_CONTRACT_INCONSISTENT diagnostic, exercised through the
# real public inference route. Mirrors the existing M32-03 style above
# (mocking api_main.execute_prediction directly to prove wiring without
# needing a real model) rather than duplicating the S0150-style real-model
# fixture, which is already covered by the private Admin route tests and by
# tests/test_local_inference_smoke.py's real scikit-learn pipeline coverage.
# ---------------------------------------------------------------------------

_S0152_RUNTIME_CONTRACT = {
    "schema_version": "atlas.dataflow.runtime_contract.v1",
    "features": [
        {
            "name": "tenure",
            "type": "numeric",
            "required": True,
            "domain_constraints": {"min": 0, "max": 72},
        },
        {
            "name": "MonthlyCharges",
            "type": "numeric",
            "required": True,
            "domain_constraints": {"min": 0, "max": 150},
        },
        {
            "name": "TotalCharges",
            "type": "numeric",
            "required": False,
            "domain_constraints": {"min": 0, "max": 10000},
        },
    ],
}

_S0152_VALID_PAYLOAD_WITHOUT_OPTIONAL_FEATURE = {"tenure": 12, "MonthlyCharges": 70.0}


def test_real_route_passes_contract_derived_runtime_feature_metadata_and_omits_optional_feature_safely():
    """
    Project Spec S0152, acceptance criteria 1/3/6/9/27: an omitted
    contractually-optional feature (TotalCharges, required: false) must
    reach execute_prediction rather than being rejected by validate_payload,
    and the caller must derive runtime_feature_metadata from the exact same
    runtime contract used for validation (required True for tenure/
    MonthlyCharges, False for TotalCharges) -- proven here by capturing the
    real kwargs execute_prediction is invoked with, through the real public
    route, without inventing a business value for the omitted feature.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_project_result_contract = api_main.project_result_contract
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    captured_calls = []
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0152-optional-feature-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0152_RUNTIME_CONTRACT
        api_main.project_result_contract = lambda _declaration: {
            "status": "available", "semantics": _S0109_RESULT_SEMANTICS
        }

        with tempfile.TemporaryDirectory() as releases_root:
            release_dir = Path(releases_root) / "release-s0152-optional-feature-fixture"
            _s0109_write_release_with_bundle(release_dir, _s0212_binary_fixture_manifest())
            api_main._inference_releases_root = lambda: Path(releases_root)

            def _capture_execute_prediction(*args, **kwargs):
                captured_calls.append((args, kwargs))
                return {"result": _S0109_VALID_BINARY_RESULT}

            api_main.execute_prediction = _capture_execute_prediction

            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload=dict(_S0152_VALID_PAYLOAD_WITHOUT_OPTIONAL_FEATURE),
            )

        assert not hasattr(response, "status_code")
        assert response["result"] == _S0109_VALID_BINARY_RESULT
        _assert_no_internal_public_exposure(response)

        assert len(captured_calls) == 1
        _, call_kwargs = captured_calls[0]
        assert call_kwargs["runtime_feature_metadata"] == {
            "tenure": {"required": True},
            "MonthlyCharges": {"required": True},
            "TotalCharges": {"required": False},
        }
        # The HTTP request body itself is unchanged -- the client never sent
        # TotalCharges, and no fabricated value was inserted before
        # execute_prediction was called. execute_prediction's second
        # positional argument is the payload dict.
        positional_payload = captured_calls[0][0][1]
        assert "TotalCharges" not in positional_payload
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main.project_result_contract = original_project_result_contract
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_real_route_required_field_omission_still_rejected_before_execution_when_contract_has_optional_feature():
    """
    Project Spec S0152, acceptance criteria 5/18/28: a genuinely required
    field (tenure) omitted from the payload must still be rejected by
    validate_payload with structured MISSING_REQUIRED_FIELD before
    execute_prediction is ever reached, even though this same contract also
    declares one contractually optional feature (TotalCharges).
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0152-required-omission-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0152_RUNTIME_CONTRACT
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("required-field omission should fail before prediction execution")
            )
        )

        missing_required_payload = {"MonthlyCharges": 70.0}
        response = api_main.validate_dataset_inference_payload(
            "fixture-dataset",
            payload=missing_required_payload,
        )

        _assert_invalid_payload_response(
            response,
            "tenure",
            "MISSING_REQUIRED_FIELD",
            "missing_required_field",
        )
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# Project Spec S0156: conditional blank-input normalization and open
# ("ignore_and_report") categorical acceptance, exercised through the real
# public inference route -- proving the governed path uses the *normalized*
# payload (never the raw blank string) for execute_prediction, stops before
# execution on a conditional-missing failure, and that an accepted unknown
# category is observable only through successful route execution (never a
# public response field). Mirrors the existing M32-03/S0152 route-mocking
# style above rather than a real model fixture.
# ---------------------------------------------------------------------------

_S0156_RUNTIME_CONTRACT = {
    "schema_version": "atlas.dataflow.runtime_contract.v1",
    "features": [
        {
            "name": "total_amount",
            "type": "numeric",
            "required": True,
            "input_policy": {
                "conditional_blank_normalization": {
                    "accepted_representation": "blank_string_after_trim",
                    "when": {"field": "tenure_months", "operator": "equals", "value": 0},
                    "materialized_value": 0.0,
                    "otherwise": "reject",
                    "null_behavior": "reject",
                }
            },
        },
        {"name": "tenure_months", "type": "numeric", "required": True},
        {
            "name": "plan_type",
            "type": "categorical",
            "required": True,
            "domain_constraints": {
                "known_values": ["basic", "pro"],
                "categorical_value_type": "string",
                "validation_behavior": "ignore_and_report",
            },
        },
    ],
}


def _s0156_fixture_release(releases_root: str, release_id: str) -> None:
    release_dir = Path(releases_root) / release_id
    _s0109_write_release_with_bundle(release_dir, _s0212_binary_fixture_manifest())


def _s0212_binary_fixture_manifest() -> dict:
    return {
        "artifacts": [],
        "runtime_execution": {"execution_strategy": "in_process"},
        "output_schema": {"class_labels": ["No", "Yes"]},
        "result_semantics": _S0109_RESULT_SEMANTICS,
    }


def test_real_route_conditional_blank_field_materializes_declared_constant_before_execution():
    """
    A blank total_amount submitted while its condition (tenure_months == 0)
    holds is trimmed and normalized to the declared constant, and it is that
    normalized value -- never the raw blank string -- that reaches
    execute_prediction.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_project_result_contract = api_main.project_result_contract
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    captured_calls = []
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0156-conditional-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0156_RUNTIME_CONTRACT
        api_main.project_result_contract = lambda _declaration: {
            "status": "available", "semantics": _S0109_RESULT_SEMANTICS
        }

        with tempfile.TemporaryDirectory() as releases_root:
            _s0156_fixture_release(releases_root, "release-s0156-conditional-fixture")
            api_main._inference_releases_root = lambda: Path(releases_root)

            def _capture_execute_prediction(*args, **kwargs):
                captured_calls.append((args, kwargs))
                return {"result": _S0109_VALID_BINARY_RESULT}

            api_main.execute_prediction = _capture_execute_prediction

            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload={"total_amount": "  ", "tenure_months": 0, "plan_type": "basic"},
            )

        assert not hasattr(response, "status_code")
        assert response["result"] == _S0109_VALID_BINARY_RESULT
        _assert_no_internal_public_exposure(response)

        assert len(captured_calls) == 1
        positional_payload = captured_calls[0][0][1]
        assert positional_payload["total_amount"] == 0.0
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main.project_result_contract = original_project_result_contract
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_real_route_conditional_blank_field_rejected_before_execution_when_condition_false():
    """
    The same blank total_amount, submitted while tenure_months != 0, must be
    rejected with a stable, structured conditional-missing failure before
    execute_prediction is ever reached.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0156-conditional-false-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0156_RUNTIME_CONTRACT
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("conditional-missing payload should fail before prediction execution")
            )
        )

        response = api_main.validate_dataset_inference_payload(
            "fixture-dataset",
            payload={"total_amount": "", "tenure_months": 5, "plan_type": "basic"},
        )

        _assert_invalid_payload_response(
            response,
            "total_amount",
            "CONDITIONAL_BLANK_REJECTED",
            "conditional_blank_rejected",
        )
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_real_route_unknown_open_categorical_value_is_accepted_and_preserved_unchanged():
    """
    An `ignore_and_report` categorical field submitted with a correctly
    typed but unknown value is accepted (observable only through successful
    route execution, per this spec's scope -- the bounded
    UNKNOWN_CATEGORY_ACCEPTED observation is not surfaced publicly) and the
    submitted value reaches execute_prediction unchanged.
    """
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_project_result_contract = api_main.project_result_contract
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    captured_calls = []
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0156-open-categorical-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0156_RUNTIME_CONTRACT
        api_main.project_result_contract = lambda _declaration: {
            "status": "available", "semantics": _S0109_RESULT_SEMANTICS
        }

        with tempfile.TemporaryDirectory() as releases_root:
            _s0156_fixture_release(releases_root, "release-s0156-open-categorical-fixture")
            api_main._inference_releases_root = lambda: Path(releases_root)

            def _capture_execute_prediction(*args, **kwargs):
                captured_calls.append((args, kwargs))
                return {"result": _S0109_VALID_BINARY_RESULT}

            api_main.execute_prediction = _capture_execute_prediction

            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload={"total_amount": 10.0, "tenure_months": 5, "plan_type": "enterprise"},
            )

        assert not hasattr(response, "status_code")
        assert response["result"] == _S0109_VALID_BINARY_RESULT
        _assert_no_internal_public_exposure(response)

        assert len(captured_calls) == 1
        positional_payload = captured_calls[0][0][1]
        assert positional_payload["plan_type"] == "enterprise"
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main.project_result_contract = original_project_result_contract
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_public_route_never_surfaces_runtime_input_contract_inconsistent_diagnostic():
    """
    Project Spec S0152, acceptance criteria 12/17: when the runtime raises
    the new RUNTIME_INPUT_CONTRACT_INCONSISTENT-classified error, the public
    route must still return only the existing generic INFERENCE_FAILURE
    envelope with no runtime_diagnostic property at all -- mirroring the
    pre-existing S0151 public-route-never-leaks tests above for the other
    seven codes.
    """
    from runtime.inference import BundleValidationError, DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT

    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_releases_root = api_main._inference_releases_root
    original_snapshot_readiness = _install_snapshot_ready_stub()
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-s0152-inconsistent-fixture",
        )
        api_main.load_contract = lambda _active_release: _S0152_RUNTIME_CONTRACT

        with tempfile.TemporaryDirectory() as releases_root:
            release_dir = Path(releases_root) / "release-s0152-inconsistent-fixture"
            release_dir.mkdir(parents=True)
            (release_dir / "manifest.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8"
            )
            api_main._inference_releases_root = lambda: Path(releases_root)

            def _raise_inconsistent(*_args, **_kwargs):
                raise BundleValidationError(
                    "runtime_input_contract_inconsistent",
                    "Inference bundle feature order could not be reconciled with the active runtime contract.",
                    field="feature_order.unknown_feature",
                    diagnostic_code=DIAGNOSTIC_RUNTIME_INPUT_CONTRACT_INCONSISTENT,
                )

            api_main.execute_prediction = _raise_inconsistent

            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload=dict(_S0152_VALID_PAYLOAD_WITHOUT_OPTIONAL_FEATURE),
            )

        assert response.status_code == 503
        body = _response_json(response)
        assert body["error_code"] == "INFERENCE_FAILURE"
        assert "runtime_diagnostic" not in body
        _assert_no_internal_public_exposure(body)
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main._inference_releases_root = original_releases_root
        _restore_snapshot_ready_stub(original_snapshot_readiness)


# ---------------------------------------------------------------------------
# S0101: GET /datasets/{dataset_slug}/contract loads the manifest-declared
# public_contract role from a promoted release. api_main.load_public_contract
# and api_main.PublicContractUnavailableError are api/public_contract_loader.py
# re-exports (read-only reference for this spec -- see M27-03 tests above,
# which already exercise this function against the real releases root).
# ---------------------------------------------------------------------------

import hashlib as _s0101_hashlib  # noqa: E402

_S0101_VALID_PUBLIC_CONTRACT = {
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


def _s0101_write_release(release_dir: Path, *, artifacts: list) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "release-manifest.v1", "manifest_kind": "release_manifest", "artifacts": artifacts}
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _s0101_write_artifact_file(release_dir: Path, relative_path: str, data: dict) -> str:
    path = release_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data)
    path.write_text(content, encoding="utf-8")
    return _s0101_hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_public_contract_endpoint_loads_promoted_contract_distinct_from_runtime_contract():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0101-001"
        _s0101_write_artifact_file(release_dir, "contracts/runtime-contract.json", {"runtime": True})
        _s0101_write_artifact_file(release_dir, "contracts/public-contract.json", _S0101_VALID_PUBLIC_CONTRACT)
        _s0101_write_release(
            release_dir,
            artifacts=[
                {"role": "contracts", "reference": "contracts/runtime-contract.json"},
                {"role": "public_contract", "reference": "contracts/public-contract.json"},
            ],
        )

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0101-001"
            )
            api_main.load_public_contract = (
                lambda active_release: original_load_public_contract(active_release, releases_root=releases_root)
            )

            response = api_main.get_public_contract("example-dataset")

            # Project Spec S0109: the release directory here lives under a
            # temp releases_root distinct from api_main's default releases
            # root (unmocked in this test), so the result-contract projection
            # correctly cannot find a manifest and safely reports unavailable
            # rather than inventing binary semantics -- the input contract
            # stays available and independent regardless.
            assert response == {
                "dataset_slug": "example-dataset",
                "contract": _S0101_VALID_PUBLIC_CONTRACT,
                "result_contract": {
                    "status": "unavailable",
                    "reason": "binary_result_semantics_unavailable",
                },
            }
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_public_contract_endpoint_returns_public_contract_unavailable_when_role_absent_from_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0101-002"
        _s0101_write_artifact_file(release_dir, "contracts/runtime-contract.json", {"runtime": True})
        _s0101_write_release(
            release_dir,
            artifacts=[{"role": "contracts", "reference": "contracts/runtime-contract.json"}],
        )

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0101-002"
            )
            api_main.load_public_contract = (
                lambda active_release: original_load_public_contract(active_release, releases_root=releases_root)
            )

            response = api_main.get_public_contract("example-dataset")

            assert response.status_code == 503
            payload = _response_json(response)
            assert payload["error_code"] == "PUBLIC_CONTRACT_UNAVAILABLE"
            _assert_no_internal_public_exposure(payload)
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_public_contract_endpoint_rejects_reference_identical_to_runtime_contract():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0101-003"
        _s0101_write_artifact_file(release_dir, "contracts/runtime-contract.json", {"runtime": True})
        _s0101_write_release(
            release_dir,
            artifacts=[
                {"role": "contracts", "reference": "contracts/runtime-contract.json"},
                {"role": "public_contract", "reference": "contracts/runtime-contract.json"},
            ],
        )

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0101-003"
            )
            api_main.load_public_contract = (
                lambda active_release: original_load_public_contract(active_release, releases_root=releases_root)
            )

            response = api_main.get_public_contract("example-dataset")

            assert response.status_code == 503
            assert _response_json(response)["error_code"] == "PUBLIC_CONTRACT_UNAVAILABLE"
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)


def _s0109_write_release_with_bundle(release_dir: Path, bundle: dict) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "release-manifest.v1",
        "manifest_kind": "release_manifest",
        "artifacts": [{"role": "predictive_bundle", "reference": "predictions/bundle.json"}],
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    bundle_path = release_dir / "predictions" / "bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")


_S0109_RESULT_SEMANTICS = {
    "schema_version": "binary-result-semantics.v1",
    "problem_type": "binary_classification",
    "result_schema_version": "binary-classification-result.v1",
    "primary_output": "positive_class_probability",
    "positive_class": {"class_id": "Yes", "event_label": "Churn"},
    "decision": {"threshold": 0.5},
    "interpretation": {
        "preset": "risk",
        "bands": [
            {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
            {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
            {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
        ],
    },
    "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
}


def test_result_contract_available_when_binary_result_semantics_present():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0109-available"
        _s0109_write_release_with_bundle(
            release_dir,
            {
                "feature_order": ["age"],
                "output_schema": {"class_labels": ["No", "Yes"]},
                "result_semantics": _S0109_RESULT_SEMANTICS,
            },
        )

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_releases_root = api_main._inference_releases_root
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0109-available"
            )
            api_main.load_public_contract = lambda _active_release: {"features": []}
            api_main._inference_releases_root = lambda: releases_root

            response = api_main.get_public_contract("example-dataset")

            assert response["result_contract"]["status"] == "available"
            assert response["result_contract"]["semantics"] == {
                **_S0109_RESULT_SEMANTICS,
                "negative_class": {"class_id": "No"},
            }
            _assert_no_internal_public_exposure(response)
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)
            api_main._inference_releases_root = original_releases_root


def test_result_contract_available_for_external_hist_gradient_boosting_semantics():
    """Project Spec S0192: reconciles the S0191-disclosed gap --
    runtime/inference.py's _validate_result_semantics now accepts
    hist_gradient_boosting (the only external public-result model family;
    contracts/inference-bundle.schema.json and
    pipeline/generate_inference_bundle.py already supported it) in its
    closed model_family allow-list. A newly-generated external bundle
    with schema-valid result_semantics now projects as status=available,
    preserving the governed positive/negative class identities, decision
    threshold, and model descriptor -- with no model deserialization."""
    from runtime.inference import project_result_contract

    external_result_semantics = {
        **_S0109_RESULT_SEMANTICS,
        "model_descriptor": {
            "model_family": "hist_gradient_boosting",
            "display_name": "HistGradientBoosting",
        },
    }
    bundle = {
        "feature_order": ["age"],
        "output_schema": {"class_labels": ["No", "Yes"]},
        "result_semantics": external_result_semantics,
        "model_provenance_origin": "validated_external_fitted_model",
        "external_model_evidence": {
            "origin": "validated_external_fitted_model",
            "model_family": "hist_gradient_boosting",
        },
    }

    result = project_result_contract(bundle)

    assert result["status"] == "available"
    assert result["semantics"] == {
        **external_result_semantics,
        "negative_class": {"class_id": "No"},
    }
    assert result["semantics"]["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert result["semantics"]["decision"]["threshold"] == 0.5
    assert result["semantics"]["model_descriptor"] == {
        "model_family": "hist_gradient_boosting",
        "display_name": "HistGradientBoosting",
    }


def test_result_contract_available_for_every_governed_model_family():
    """Project Spec S0192 acceptance criteria 6-8: internal model families
    remain accepted alongside the newly-added external family."""
    from runtime.inference import project_result_contract

    for model_family, display_name in (
        ("logistic_regression", "Logistic Regression"),
        ("gradient_boosting", "Gradient Boosting"),
        ("random_forest", "Random Forest"),
        ("hist_gradient_boosting", "HistGradientBoosting"),
    ):
        semantics = {
            **_S0109_RESULT_SEMANTICS,
            "model_descriptor": {"model_family": model_family, "display_name": display_name},
        }
        bundle = {
            "feature_order": ["age"],
            "output_schema": {"class_labels": ["No", "Yes"]},
            "result_semantics": semantics,
        }

        result = project_result_contract(bundle)

        assert result["status"] == "available"
        assert result["semantics"]["model_descriptor"]["model_family"] == model_family


def test_result_contract_unavailable_for_unsupported_model_family():
    """Project Spec S0192 acceptance criteria 9-10: an arbitrary
    unsupported model family remains rejected -- the allow-list stays
    closed, never an unconstrained string."""
    from runtime.inference import project_result_contract

    semantics = {
        **_S0109_RESULT_SEMANTICS,
        "model_descriptor": {"model_family": "xgboost", "display_name": "XGBoost"},
    }
    bundle = {
        "feature_order": ["age"],
        "output_schema": {"class_labels": ["No", "Yes"]},
        "result_semantics": semantics,
    }

    result = project_result_contract(bundle)

    assert result == {"status": "unavailable", "reason": "binary_result_semantics_unavailable"}


def test_result_contract_unavailable_for_historical_bundle_without_result_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0109-historical"
        _s0109_write_release_with_bundle(release_dir, {"feature_order": ["age"]})

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_releases_root = api_main._inference_releases_root
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0109-historical"
            )
            api_main.load_public_contract = lambda _active_release: {"features": []}
            api_main._inference_releases_root = lambda: releases_root

            response = api_main.get_public_contract("example-dataset")

            assert response["result_contract"] == {
                "status": "unavailable",
                "reason": "binary_result_semantics_unavailable",
            }
            # Input contract remains available and independent.
            assert response["contract"] == {"features": []}
            _assert_no_internal_public_exposure(response)
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)
            api_main._inference_releases_root = original_releases_root


def test_result_contract_unavailable_when_binary_class_identity_is_not_resolvable():
    invalid_class_sets = [None, [], ["Yes"], ["No", "Yes", "Maybe"], ["Yes", " yes "], ["No", "Maybe"]]
    for class_labels in invalid_class_sets:
        bundle = {
            "feature_order": ["age"],
            "result_semantics": _S0109_RESULT_SEMANTICS,
            "output_schema": {},
        }
        if class_labels is not None:
            bundle["output_schema"]["class_labels"] = class_labels

        from runtime.inference import project_result_contract

        assert project_result_contract(bundle) == {
            "status": "unavailable",
            "reason": "binary_result_semantics_unavailable",
        }


def test_result_contract_projects_order_independent_numeric_and_boolean_negative_identities():
    from runtime.inference import project_result_contract

    numeric_semantics = {**_S0109_RESULT_SEMANTICS, "positive_class": {"class_id": "1", "event_label": "Event"}}
    numeric = project_result_contract({
        "output_schema": {"class_labels": [1, 0]},
        "result_semantics": numeric_semantics,
    })
    assert numeric["semantics"]["negative_class"] == {"class_id": "0"}

    boolean_semantics = {**_S0109_RESULT_SEMANTICS, "positive_class": {"class_id": "True", "event_label": "Event"}}
    boolean = project_result_contract({
        "output_schema": {"class_labels": [False, True]},
        "result_semantics": boolean_semantics,
    })
    assert boolean["semantics"]["negative_class"] == {"class_id": "False"}


def test_result_contract_projection_never_invokes_model_loader():
    """GET /contract must never deserialize the model, even when a real
    loader-strategy allowlist entry exists -- it only reads bundle JSON."""

    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0109-no-model-load"
        _s0109_write_release_with_bundle(
            release_dir,
            {
                "feature_order": ["age"],
                "runtime_execution": {"loader_strategy": "joblib_sklearn_predict", "serialization_format": "joblib"},
                "model_artifact": {"path": "models/model.pkl", "sha256": "0" * 64},
                "output_schema": {"class_labels": ["No", "Yes"]},
                "result_semantics": _S0109_RESULT_SEMANTICS,
            },
        )
        # Deliberately no models/model.pkl file at all -- if the projection
        # ever tried to load it, this would raise/fail rather than silently
        # succeed, proving the model is never touched.

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_releases_root = api_main._inference_releases_root
        original_loader = api_main._INFERENCE_LOADER_STRATEGIES["joblib_sklearn_predict"]
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0109-no-model-load"
            )
            api_main.load_public_contract = lambda _active_release: {"features": []}
            api_main._inference_releases_root = lambda: releases_root

            def _explode_if_invoked(*_args, **_kwargs):
                raise AssertionError("result-contract projection must never invoke the model loader")

            api_main._INFERENCE_LOADER_STRATEGIES["joblib_sklearn_predict"] = _explode_if_invoked

            response = api_main.get_public_contract("example-dataset")

            assert response["result_contract"]["status"] == "available"
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            _restore_snapshot_ready_stub(original_snapshot_readiness)
            api_main._inference_releases_root = original_releases_root
            api_main._INFERENCE_LOADER_STRATEGIES["joblib_sklearn_predict"] = original_loader


def test_get_contract_projects_ordered_multiclass_semantics_without_model_loading():
    semantics = {
        "schema_version": "multiclass-result-semantics.v1",
        "problem_type": "multiclass_classification",
        "result_schema_version": "multiclass-classification-result.v1",
        "classes": [
            {"class_id": "z", "display_label": "Zulu"},
            {"class_id": "a", "display_label": "Alpha"},
            {"class_id": "m", "display_label": "Mike"},
        ],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
        "model_descriptor": {"model_family": "decision_tree", "display_name": "Tree"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0212-multiclass"
        _s0109_write_release_with_bundle(
            release_dir,
            {
                "feature_order": ["age"],
                "output_schema": {
                    "class_labels": ["z", "a", "m"],
                    "prediction_type": "string",
                    "probability_output": True,
                },
                "result_semantics": semantics,
            },
        )

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_releases_root = api_main._inference_releases_root
        original_model_loader = api_main.load_joblib_sklearn_model
        original_snapshot_readiness = _install_snapshot_ready_stub()
        try:
            api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
                dataset_slug=dataset_slug, active_release="release-s0212-multiclass"
            )
            api_main.load_public_contract = lambda _active_release: {"features": []}
            api_main._inference_releases_root = lambda: releases_root
            api_main.load_joblib_sklearn_model = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("GET /contract loaded model bytes")
            )

            response = api_main.get_public_contract("example-dataset")

            assert response["result_contract"] == {"status": "available", "semantics": semantics}
            assert [item["class_id"] for item in response["result_contract"]["semantics"]["classes"]] == [
                "z", "a", "m"
            ]
        finally:
            api_main.resolve_dataset = original_resolve_dataset
            api_main.load_public_contract = original_load_public_contract
            api_main._inference_releases_root = original_releases_root
            api_main.load_joblib_sklearn_model = original_model_loader
            _restore_snapshot_ready_stub(original_snapshot_readiness)


def test_public_contract_loader_rejects_reference_escaping_release_directory():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0101-004"
        _s0101_write_release(
            release_dir,
            artifacts=[
                {"role": "contracts", "reference": "contracts/runtime-contract.json"},
                {"role": "public_contract", "reference": "../../etc/passwd"},
            ],
        )

        raised = False
        try:
            api_main.load_public_contract("release-s0101-004", releases_root=releases_root)
        except api_main.PublicContractUnavailableError:
            raised = True
        assert raised, "Expected PublicContractUnavailableError for an escaping reference"


def test_public_contract_loader_rejects_missing_reference_file():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0101-005"
        _s0101_write_release(
            release_dir,
            artifacts=[
                {"role": "contracts", "reference": "contracts/runtime-contract.json"},
                {"role": "public_contract", "reference": "contracts/public-contract.json"},
            ],
        )

        raised = False
        try:
            api_main.load_public_contract("release-s0101-005", releases_root=releases_root)
        except api_main.PublicContractUnavailableError:
            raised = True
        assert raised, "Expected PublicContractUnavailableError for a missing referenced file"


def test_public_contract_loader_does_not_fall_back_to_repository_level_contract():
    """No fallback to contracts/{dataset_slug}/public-contract.json in the
    repository: only the active release's manifest-declared public_contract
    role is ever consulted (Project Spec S0101)."""
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        # A release manifest with no artifacts at all -- the loader must
        # never reach into REPO_ROOT/contracts/telco-customer-churn/
        # public-contract.json (which is a real, valid file) as a fallback.
        release_dir = releases_root / "release-s0101-006"
        release_dir.mkdir(parents=True, exist_ok=True)
        (release_dir / "manifest.json").write_text(
            json.dumps({"schema_version": "release-manifest.v1", "manifest_kind": "release_manifest", "artifacts": []}),
            encoding="utf-8",
        )

        raised = False
        try:
            api_main.load_public_contract("release-s0101-006", releases_root=releases_root)
        except api_main.PublicContractUnavailableError:
            raised = True
        assert raised, "Expected PublicContractUnavailableError with no repository-level fallback"


# ---------------------------------------------------------------------------
# GET /admin/datasets/{dataset_slug}/authoring-context: Project Spec S0121
# private authoring read model. Uses the real telco-customer-churn registry
# entry/active release wherever possible and monkeypatches only the specific
# loader needed for each bounded-failure scenario, matching this file's
# existing style. Project Spec S0132: the needs_review scenario below is the
# one exception -- it is fully isolated from the mutable real
# telco-customer-churn registry entry (which can legitimately progress past
# needs_review after approval) via a deterministic local fixture instead.
# ---------------------------------------------------------------------------

_AUTHORING_FIXTURE_VIEW = {
    "view_id": "fixture-view",
    "dataset_slug": "fixture-dataset",
    "display": {"title": "Fixture View", "summary": "Fixture summary."},
    "intent": {"prediction_goal": "test", "audience": "test", "usage_notes": "test"},
    "release_mode": "active",
}


def _resolved_authoring_fixture(dataset_slug: str):
    return SimpleNamespace(dataset_slug=dataset_slug, active_release="release-fixture-001")


def _authoring_request(dataset_slug: str = "telco-customer-churn") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/admin/datasets/{dataset_slug}/authoring-context",
            "headers": [],
        }
    )


def test_authoring_context_returns_generic_not_found_when_admin_runtime_disabled():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    response = api_main.get_admin_dataset_authoring_context(
        "telco-customer-churn", _authoring_request()
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_authoring_context_needs_review_dataset_reproduces_spec_scenario(monkeypatch):
    """
    Project Spec S0132: replaces the prior dependency on the real, mutable
    telco-customer-churn registry entry's needs_review status (which can
    legitimately progress to ready after approval) with a deterministic
    local dataset_slug/active_release/publication_status fixture, so this
    scenario stays reproducible regardless of real registry/publication
    state. Controls the private authoring-context loaders and the Predict
    View identity directly; never writes to the real registry, snapshot
    files or publication records.
    """
    dataset_slug = "fixture-needs-review-dataset"
    active_release = "release-fixture-needs-review-001"
    fixture_view = {
        "view_id": "fixture-needs-review-view",
        "dataset_slug": dataset_slug,
        "display": {"title": "Fixture Needs Review View", "summary": "Fixture summary."},
        "intent": {"prediction_goal": "test", "audience": "test", "usage_notes": "test"},
        "release_mode": "active",
    }
    admin_dataset = AdminListedDataset(
        dataset_slug=dataset_slug,
        title="Fixture Needs Review Dataset",
        display_title=None,
        summary="Fixture summary.",
        domain="fixture",
        tags=["fixture"],
        active_release=active_release,
        publication_status="needs_review",
        dataset_detail_updated_at=None,
    )

    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda _slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=active_release),
    )
    monkeypatch.setattr(api_main, "list_admin_datasets", lambda: [admin_dataset])
    monkeypatch.setattr(api_main, "load_public_context", lambda _release: {"problem_type": "binary_classification"})
    monkeypatch.setattr(api_main, "load_public_contract", lambda _release: {"features": []})
    monkeypatch.setattr(api_main, "load_public_metrics", lambda _release: {"accuracy": 0.9})
    monkeypatch.setattr(api_main, "load_public_visualizations", lambda _release: {"charts": []})
    monkeypatch.setattr(api_main, "load_public_predict_view_list", lambda _slug: [dict(fixture_view)])
    # Private authoring context must remain reachable while the exact same
    # dataset_slug is independently blocked from public access below.
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _slug: True)

    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        response = api_main.get_admin_dataset_authoring_context(
            dataset_slug, _authoring_request(dataset_slug)
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    assert response["dataset_slug"] == dataset_slug
    assert response["active_release"] == active_release
    assert response["dataset"]["status"] == "ready"
    assert response["dataset"]["data"]["publication_status"] == "needs_review"
    assert response["context"]["status"] == "ready"
    assert response["contract"]["status"] == "ready"
    assert "result_contract" in response["contract"]["data"]
    assert response["views"] == {
        "status": "ready",
        "data": response["views"]["data"],
    }
    view_ids = [item["view_id"] for item in response["views"]["data"]]
    assert view_ids == [fixture_view["view_id"]]

    # The public S0117 boundary must be completely unaffected by the private
    # read model resolving the very same needs_review dataset above.
    public_response = api_main.get_dataset(dataset_slug)
    assert public_response.status_code == 503
    assert _response_json(public_response)["error_code"] == "DATASET_MAINTENANCE"


def test_authoring_context_never_calls_resolve_public_dataset_detail_access():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original = api_main._resolve_public_dataset_detail_access

    def _fail(*_args, **_kwargs):
        raise AssertionError("must not call _resolve_public_dataset_detail_access")

    api_main._resolve_public_dataset_detail_access = _fail
    try:
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["dataset_slug"] == "telco-customer-churn"
    finally:
        api_main._resolve_public_dataset_detail_access = original
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_hidden_dataset_still_resolves_privately():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_visibility = api_main.resolve_dataset_visibility
    api_main.resolve_dataset_visibility = lambda _dataset_slug: False
    try:
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["views"]["status"] == "ready"
        assert response["views"]["data"][0]["view_id"] == "churn-risk-overview"
    finally:
        api_main.resolve_dataset_visibility = original_visibility
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_ready_public_dataset_still_resolves_privately():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_needs_review = api_main.is_dataset_needs_review
    api_main.is_dataset_needs_review = lambda _dataset_slug: False
    try:
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["views"]["status"] == "ready"
        assert response["views"]["data"][0]["view_id"] == "churn-risk-overview"
    finally:
        api_main.is_dataset_needs_review = original_needs_review
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_zero_eligible_views_returns_ready_empty_list():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    original_views = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved_authoring_fixture(slug)
        api_main.load_public_predict_view_list = lambda slug: []
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        assert response["views"] == {"status": "ready", "data": []}
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_views
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_multiple_eligible_views_returns_every_projection():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    original_views = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved_authoring_fixture(slug)
        api_main.load_public_predict_view_list = lambda slug: [
            dict(_AUTHORING_FIXTURE_VIEW, view_id="view-one"),
            dict(_AUTHORING_FIXTURE_VIEW, view_id="view-two"),
        ]
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        assert response["views"]["status"] == "ready"
        assert [v["view_id"] for v in response["views"]["data"]] == ["view-one", "view-two"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_views
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_unknown_dataset_returns_dataset_not_found():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    try:
        def _raise(_slug):
            raise DatasetUnavailableError("missing")

        api_main.resolve_dataset = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "unknown-dataset", _authoring_request("unknown-dataset")
        )
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_release_unavailable_returns_release_unavailable():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    try:
        def _raise(_slug):
            raise ReleaseUnavailableError("no release")

        api_main.resolve_dataset = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "RELEASE_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_registry_invalid_returns_registry_unavailable():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    try:
        def _raise(_slug):
            raise RegistryInvalidError("bad registry")

        api_main.resolve_dataset = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "REGISTRY_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_predict_view_registry_unavailable_is_bounded_not_empty_list():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    original_views = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved_authoring_fixture(slug)

        def _raise(_slug):
            raise api_main.ViewNotFoundError("registry unavailable")

        api_main.load_public_predict_view_list = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        assert response["views"]["status"] == "unavailable"
        assert response["views"]["error"]["code"] == "PREDICT_VIEW_REGISTRY_UNAVAILABLE"
        assert response["views"] != {"status": "ready", "data": []}
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_views
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_binding_inconsistent_view_is_never_selected(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list as _real_load_list

    registry_data = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {
                "view_id": "valid-view",
                "dataset_slug": "fixture-dataset",
                "display": {"title": "Valid", "summary": "Valid view."},
                "intent": {"prediction_goal": "t", "audience": "t", "usage_notes": "t"},
                "binding": {"dataset_slug": "fixture-dataset", "release": {"mode": "active"}},
            },
            {
                "view_id": "inconsistent-view",
                "dataset_slug": "fixture-dataset",
                "display": {"title": "Inconsistent", "summary": "Mismatch."},
                "intent": {"prediction_goal": "t", "audience": "t", "usage_notes": "t"},
                "binding": {"dataset_slug": "OTHER-DATASET", "release": {"mode": "active"}},
            },
        ],
    }
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_resolve = api_main.resolve_dataset
    original_views = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved_authoring_fixture(slug)
        api_main.load_public_predict_view_list = lambda slug: _real_load_list(
            slug, predict_views_path=registry_path
        )
        response = api_main.get_admin_dataset_authoring_context(
            "fixture-dataset", _authoring_request("fixture-dataset")
        )
        view_ids = [v["view_id"] for v in response["views"]["data"]]
        assert view_ids == ["valid-view"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_views
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_contract_unavailable_does_not_erase_views():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_contract = api_main.load_public_contract
    try:
        def _raise(_release):
            raise api_main.PublicContractUnavailableError("no contract")

        api_main.load_public_contract = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["contract"]["status"] == "unavailable"
        assert response["contract"]["error"]["code"] == "PUBLIC_CONTRACT_UNAVAILABLE"
        assert response["contract"]["error"]["message"]
        assert response["views"]["status"] == "ready"
        assert len(response["views"]["data"]) == 1
    finally:
        api_main.load_public_contract = original_contract
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_metrics_unavailable_does_not_block_contract_or_views():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_metrics = api_main.load_public_metrics
    try:
        def _raise(_release):
            raise api_main.PublicMetricsUnavailableError("no metrics")

        api_main.load_public_metrics = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["metrics"]["status"] == "unavailable"
        assert response["metrics"]["error"]["code"] == "METRICS_UNAVAILABLE"
        assert response["contract"]["status"] == "ready"
        assert response["views"]["status"] == "ready"
    finally:
        api_main.load_public_metrics = original_metrics
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_visualizations_unavailable_does_not_block_contract_or_views():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    original_visualizations = api_main.load_public_visualizations
    try:
        def _raise(_release):
            raise api_main.PublicVisualizationsUnavailableError("no visualizations")

        api_main.load_public_visualizations = _raise
        response = api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
        assert response["visualizations"]["status"] == "unavailable"
        assert response["visualizations"]["error"]["code"] == "VISUALIZATIONS_UNAVAILABLE"
        assert response["contract"]["status"] == "ready"
        assert response["views"]["status"] == "ready"
    finally:
        api_main.load_public_visualizations = original_visualizations
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)


def test_authoring_context_route_never_mutates_registry_or_predict_views_files():
    registry_path = REPO_ROOT / "registry" / "datasets.json"
    predict_views_path = REPO_ROOT / "registry" / "predict-views.json"
    before_registry = registry_path.read_bytes()
    before_predict_views = predict_views_path.read_bytes()

    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        api_main.get_admin_dataset_authoring_context(
            "telco-customer-churn", _authoring_request()
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    assert registry_path.read_bytes() == before_registry
    assert predict_views_path.read_bytes() == before_predict_views


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_list_datasets_returns_list,
        test_list_datasets_returns_named_tuples,
        test_list_datasets_safe_fields_present,
        test_list_datasets_no_active_release_in_result,
        test_list_datasets_no_conventions_in_result,
        test_list_datasets_asdict_safe_fields_only,
        test_list_datasets_raises_registry_invalid_on_bad_registry,
        test_list_datasets_raises_registry_invalid_on_missing_file,
        test_resolve_dataset_confirms_slug_exists,
        test_resolve_dataset_unknown_slug_raises_dataset_unavailable,
        test_resolve_dataset_does_not_return_active_release_in_public_flow,
        test_single_dataset_response_safe_fields_only,
        test_listing_response_datasets_key,
        test_listing_each_item_safe_fields_only,
        test_context_endpoint_returns_public_context_response,
        test_context_endpoint_unknown_dataset_returns_dataset_not_found,
        test_context_endpoint_release_unavailable_returns_release_unavailable,
        test_context_endpoint_context_unavailable_returns_context_unavailable,
        test_customization_endpoint_returns_200_with_payload,
        test_customization_endpoint_returns_customization_not_found_when_absent,
        test_customization_endpoint_unknown_dataset_returns_dataset_not_found,
        test_customization_response_structure_matches_expected_fields,
        test_customization_endpoint_exercises_real_loader_chain_without_replacing_it,
        test_customization_endpoint_real_loader_chain_rejects_slug_named_release_directory,
        test_real_registry_listing_returns_non_empty_list,
        test_real_registry_listing_contains_telco_customer_churn,
        test_real_registry_listing_telco_customer_churn_safe_fields_non_empty,
        test_fixture_multi_dataset_registry_listing_includes_both_datasets,
        test_real_registry_listing_no_active_release_in_any_item,
        test_real_registry_listing_safe_fields_only_on_all_items,
        test_real_registry_resolve_telco_customer_churn_succeeds,
        test_fixture_multi_dataset_registry_resolve_second_dataset_succeeds,
        test_real_registry_listing_envelope_shape,
        test_real_release_dataset_home_context_payload_shape,
        test_real_release_dataset_home_metrics_payload_shape,
        test_real_release_dataset_home_model_card_payload_shape,
        test_real_release_dataset_home_visualizations_degrade_safely,
        test_real_release_valid_prediction_flow_uses_public_route_and_bundle,
        test_real_route_non_object_prediction_payload_fails_before_runtime_resolution,
        test_real_route_contract_invalid_prediction_payloads_fail_before_prediction_execution,
        test_real_route_select_projected_categorical_value_domain_validation,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
