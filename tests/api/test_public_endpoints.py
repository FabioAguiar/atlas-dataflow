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
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from registry.list import ListedDataset, list_admin_datasets, list_datasets  # noqa: E402
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
}

_EMPTY_PUBLIC_CONTEXT_OVERLAY = {
    "display_title": None,
    "display_subtitle": None,
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


def test_context_endpoint_returns_public_context_response():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    original_overlay = api_main.resolve_public_presentation_overlay
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


def test_customization_endpoint_returns_200_with_payload():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )
        api_main.load_public_predict_view_customization = (
            lambda dataset_slug, view_id: _VALID_CUSTOMIZATION
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


def test_customization_endpoint_returns_customization_not_found_when_absent():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )

        def raise_not_found(dataset_slug, view_id):
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


def test_customization_response_structure_matches_expected_fields():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view_customization
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260622-001",
        )
        api_main.load_public_predict_view_customization = (
            lambda dataset_slug, view_id: _VALID_CUSTOMIZATION
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
        assert response["metrics"].get("dataset_slug") == resolved.dataset_slug
        assert isinstance(response["metrics"].get("release_id"), str)
        assert response["metrics"]["release_id"]
        evaluation = response["metrics"].get("evaluation")
        assert isinstance(evaluation, dict)
        assert isinstance(evaluation.get("split"), str)
        assert isinstance(evaluation.get("sample_size"), int)
        assert evaluation["sample_size"] > 0
        values = evaluation.get("metrics")
        assert isinstance(values, dict)
        for metric_name in ("accuracy", "precision", "recall", "f1_score", "auc_roc"):
            assert isinstance(values.get(metric_name), (int, float))
        _assert_no_internal_public_exposure(response)


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


def test_real_release_dataset_home_visualizations_degrade_safely():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_visualizations = api_main.load_public_visualizations
    try:
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


def test_real_route_non_object_prediction_payload_fails_before_runtime_resolution():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    try:
        api_main.resolve_dataset = (
            lambda _dataset_slug: (_ for _ in ()).throw(
                AssertionError("non-object payload should fail before dataset resolution")
            )
        )
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


def test_real_route_contract_invalid_prediction_payloads_fail_before_prediction_execution():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
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
    original_releases_root = api_main._inference_releases_root
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m32-03-select-path-fixture",
        )
        api_main.load_contract = lambda _active_release: _M32_SELECT_PATH_RUNTIME_CONTRACT

        with tempfile.TemporaryDirectory() as releases_root:
            release_dir = Path(releases_root) / "release-m32-03-select-path-fixture"
            release_dir.mkdir(parents=True)
            (release_dir / "manifest.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8"
            )
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
        api_main._inference_releases_root = original_releases_root


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
            api_main._inference_releases_root = original_releases_root


def test_result_contract_unavailable_for_historical_bundle_without_result_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        release_dir = releases_root / "release-s0109-historical"
        _s0109_write_release_with_bundle(release_dir, {"feature_order": ["age"]})

        original_resolve_dataset = api_main.resolve_dataset
        original_load_public_contract = api_main.load_public_contract
        original_releases_root = api_main._inference_releases_root
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
            api_main._inference_releases_root = original_releases_root
            api_main._INFERENCE_LOADER_STRATEGIES["joblib_sklearn_predict"] = original_loader


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
