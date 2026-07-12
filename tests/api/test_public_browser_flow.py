"""
M27-05 public browser/API flow compatibility tests.

These tests exercise the public route matrix through API handler boundaries and
frontend-consumed response shapes. They intentionally avoid reusing M27-01
through M27-04 test files as edit targets.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from registry.list import list_datasets  # noqa: E402
from registry.resolve import resolve_dataset  # noqa: E402

_REAL_REGISTRY_PATH = REPO_ROOT / "registry" / "datasets.json"
_REAL_RELEASES_ROOT = REPO_ROOT / "releases"

_PUBLIC_HOME_LISTING_KEYS = {
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


def _response_json(response):
    return json.loads(response.body.decode("utf-8"))


def _assert_no_public_exposure(payload):
    serialized = json.dumps(payload, sort_keys=True).lower()
    forbidden_fragments = [
        "raw_logs",
        "raw_api_payload",
        "raw_runtime",
        "traceback",
        "stack trace",
        "/home/",
        "/workspace/",
        "evidence/",
        "runtime internals",
        "secret",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in serialized


def _first_view_for_dataset(dataset_slug):
    response = api_main.list_predict_views(dataset_slug)
    assert isinstance(response, dict)
    assert response["dataset_slug"] == dataset_slug
    assert isinstance(response["views"], list)
    return response["views"][0] if response["views"] else None


def test_public_listing_shape_matches_frontend_home_route_contract():
    datasets = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    response = {"datasets": [dataset._asdict() for dataset in datasets]}

    assert set(response.keys()) == {"datasets"}
    assert isinstance(response["datasets"], list)
    for item in response["datasets"]:
        assert set(item.keys()) == _PUBLIC_HOME_LISTING_KEYS
        assert isinstance(item["dataset_slug"], str)
        assert isinstance(item["tags"], list)
        media_ref = item["home_card_media_ref"]
        assert media_ref is None or media_ref.startswith("/media/home-cards/")
    _assert_no_public_exposure(response)


def test_public_dataset_home_route_dependencies_are_frontend_compatible():
    datasets = list_datasets(registry_path=_REAL_REGISTRY_PATH)
    if not datasets:
        pytest.skip("real registry is empty; non-empty dependency compatibility is fixture-covered elsewhere")
    dataset_slug = datasets[0].dataset_slug
    resolved = resolve_dataset(dataset_slug, registry_path=_REAL_REGISTRY_PATH)

    dataset_response = api_main.get_dataset(dataset_slug)
    context = api_main.load_public_context(
        resolved.active_release,
        releases_root=_REAL_RELEASES_ROOT,
    )
    metrics = api_main.load_public_metrics(
        resolved.active_release,
        releases_root=_REAL_RELEASES_ROOT,
    )
    model_card = api_main.load_public_model_card(
        resolved.active_release,
        releases_root=_REAL_RELEASES_ROOT,
    )
    contract = api_main.load_public_contract(
        resolved.active_release,
        releases_root=_REAL_RELEASES_ROOT,
    )
    views_response = api_main.list_predict_views(dataset_slug)

    assert isinstance(dataset_response, dict)
    assert dataset_response["dataset_slug"] == dataset_slug
    assert {"title", "summary", "domain", "visibility", "tags"} <= set(dataset_response)
    assert isinstance(context, dict)
    assert isinstance(metrics, dict)
    assert set(model_card.keys()) == {"content", "format"}
    assert isinstance(contract.get("features"), list)
    assert views_response["dataset_slug"] == dataset_slug
    assert isinstance(views_response["views"], list)

    _assert_no_public_exposure(
        {
            "dataset": dataset_response,
            "context": context,
            "metrics": metrics,
            "model_card": model_card,
            "contract": contract,
            "views": views_response,
        }
    )


def test_public_predict_view_route_dependencies_are_frontend_compatible():
    dataset_slug = "telco-customer-churn"
    if not any(d.dataset_slug == dataset_slug for d in list_datasets(registry_path=_REAL_REGISTRY_PATH)):
        pytest.skip("real registry has no Telco dataset; predict-view orphan cleanup belongs to S0082")
    view = _first_view_for_dataset(dataset_slug)
    assert view is not None

    view_response = api_main.get_predict_view(dataset_slug, view["view_id"])
    customization_response = api_main.get_predict_view_customization(
        dataset_slug,
        view["view_id"],
    )

    assert isinstance(view_response, dict)
    assert view_response["dataset_slug"] == dataset_slug
    assert view_response["view_id"] == view["view_id"]
    assert "display" in view_response
    assert "intent" in view_response
    assert "release_mode" in view_response
    assert "binding" not in view_response
    assert "contract_precedence" not in view_response
    assert "schema_version" not in view_response

    if hasattr(customization_response, "status_code"):
        payload = _response_json(customization_response)
        assert customization_response.status_code == 404
        assert payload["error_code"] == "CUSTOMIZATION_NOT_FOUND"
        _assert_no_public_exposure(payload)
    else:
        assert customization_response["dataset_slug"] == dataset_slug
        assert customization_response["view_id"] == view["view_id"]
        assert "field_hints" in customization_response
        assert "groups" in customization_response
        _assert_no_public_exposure(customization_response)

    _assert_no_public_exposure(view_response)


def test_public_inference_errors_remain_safe_for_browser_consumers():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m27-05-fixture",
        )
        api_main.load_contract = lambda _active_release: {
            "schema_version": "atlas.dataflow.runtime_contract.v1",
            "features": [
                {
                    "name": "age",
                    "type": "numeric",
                    "required": True,
                    "domain_constraints": {"min": 0, "max": 120},
                }
            ],
        }
        api_main.execute_prediction = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("invalid public payload must not execute prediction")
            )
        )

        response = api_main.validate_dataset_inference_payload(
            "fixture-dataset",
            payload={"age": "not-a-number"},
        )

        assert response.status_code == 422
        payload = _response_json(response)
        assert payload["error_type"] == "invalid_payload"
        assert payload["error_code"] == "INVALID_PAYLOAD"
        assert isinstance(payload["message"], str)
        assert isinstance(payload["errors"], list)
        assert payload["errors"]
        assert set(payload["errors"][0].keys()) == {
            "error_code",
            "message",
            "field",
            "violation",
        }
        _assert_no_public_exposure(payload)
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
