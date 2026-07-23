"""
M27-05 public browser/API flow compatibility tests.

These tests exercise the public route matrix through API handler boundaries and
frontend-consumed response shapes. They intentionally avoid reusing M27-01
through M27-04 test files as edit targets.
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
from registry.list import ListedDataset, list_datasets  # noqa: E402

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

_REAL_REGISTRY_PATH = REPO_ROOT / "registry" / "datasets.json"

_FIXTURE_DATASET_SLUG = "fixture-public-dataset"
_FIXTURE_RELEASE_ID = "release-fixture-public-001"
_FIXTURE_LISTED_DATASET = ListedDataset(
    dataset_slug=_FIXTURE_DATASET_SLUG,
    title="Fixture Public Dataset",
    summary="Complete fixture for public browser dependency compatibility.",
    domain="testing",
    visibility="public",
    tags=["fixture"],
)

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


def _make_publicly_eligible(monkeypatch) -> None:
    """
    Establish the complete S0117/S0125 public-readiness preconditions checked
    by _resolve_public_dataset_detail_access() (visibility, needs_review, and
    current-release snapshot alignment) for tests intended to exercise
    endpoint behavior after public access is granted, without bypassing the
    guard itself. Restored automatically by monkeypatch after each test.
    """
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _dataset_slug, _active_release: {"status": "current_release", "matches_active_release": True},
    )


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


def _write_complete_public_release(releases_root: Path) -> None:
    release_dir = releases_root / _FIXTURE_RELEASE_ID
    release_dir.mkdir(parents=True)
    release_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"role": "public_context", "reference": "context.json"},
                    {"role": "metrics", "reference": "metrics.json"},
                    {"role": "model_card", "reference": "model-card.md"},
                    {"role": "public_contract", "reference": "public-contract.json"},
                    {"role": "contracts", "reference": "runtime-contract.json"},
                ]
            }
        ),
        encoding="utf-8",
    )
    release_dir.joinpath("context.json").write_text(
        json.dumps({"problem_type": "binary_classification"}), encoding="utf-8"
    )
    release_dir.joinpath("metrics.json").write_text(
        json.dumps({"accuracy": 0.9}), encoding="utf-8"
    )
    release_dir.joinpath("model-card.md").write_text("# Fixture model card\n", encoding="utf-8")
    release_dir.joinpath("public-contract.json").write_text(
        json.dumps({"features": [{"name": "fixture_feature", "type": "numeric"}]}),
        encoding="utf-8",
    )


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


def test_public_dataset_home_route_dependencies_are_frontend_compatible(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_complete_public_release(releases_root)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug, active_release=_FIXTURE_RELEASE_ID
        ),
    )
    monkeypatch.setattr(api_main, "list_datasets", lambda: [_FIXTURE_LISTED_DATASET])
    _make_publicly_eligible(monkeypatch)
    monkeypatch.setattr(api_main, "load_public_predict_view_list", lambda _dataset_slug: [])
    monkeypatch.setenv("RELEASES_ROOT", str(releases_root))

    dataset_response = api_main.get_dataset(_FIXTURE_DATASET_SLUG)
    context = api_main.load_public_context(
        _FIXTURE_RELEASE_ID,
        releases_root=releases_root,
    )
    metrics = api_main.load_public_metrics(
        _FIXTURE_RELEASE_ID,
        releases_root=releases_root,
    )
    model_card = api_main.load_public_model_card(
        _FIXTURE_RELEASE_ID,
        releases_root=releases_root,
    )
    contract = api_main.load_public_contract(
        _FIXTURE_RELEASE_ID,
        releases_root=releases_root,
    )
    views_response = api_main.list_predict_views(_FIXTURE_DATASET_SLUG)

    assert isinstance(dataset_response, dict)
    assert dataset_response["dataset_slug"] == _FIXTURE_DATASET_SLUG
    assert {"title", "summary", "domain", "visibility", "tags"} <= set(dataset_response)
    assert isinstance(context, dict)
    assert isinstance(metrics, dict)
    assert set(model_card.keys()) == {"content", "format"}
    assert isinstance(contract.get("features"), list)
    assert views_response["dataset_slug"] == _FIXTURE_DATASET_SLUG
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


def test_public_predict_view_route_dependencies_are_frontend_compatible(monkeypatch):
    dataset_slug = _FIXTURE_DATASET_SLUG
    fixture_view = {
        "view_id": "fixture-risk-overview",
        "dataset_slug": dataset_slug,
        "display": {"title": "Fixture Risk Overview", "summary": "Fixture view."},
        "intent": {"prediction_goal": "Exercise the public view contract.", "audience": "Tests"},
        "release_mode": "active",
    }
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda slug: SimpleNamespace(dataset_slug=slug, active_release=_FIXTURE_RELEASE_ID),
    )
    _make_publicly_eligible(monkeypatch)
    monkeypatch.setattr(api_main, "load_public_predict_view_list", lambda _slug: [fixture_view])
    monkeypatch.setattr(api_main, "load_public_predict_view", lambda _slug, _view_id: fixture_view)
    monkeypatch.setattr(
        api_main,
        "load_public_predict_view_customization",
        lambda slug, view_id, active_release: {
            "dataset_slug": slug,
            "view_id": view_id,
            "field_hints": {},
            "groups": [],
        },
    )
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


def test_public_inference_errors_remain_safe_for_browser_consumers(monkeypatch):
    _make_publicly_eligible(monkeypatch)
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


def test_public_inference_success_shape_matches_binary_result_contract_for_browser_consumers(monkeypatch):
    """Project Spec S0109: a valid inference response must expose exactly
    dataset_slug + result (binary-classification-result.v1) -- never the
    legacy prediction.label/confidence shape a pre-S0109 frontend consumer
    would have expected."""

    _make_publicly_eligible(monkeypatch)
    original_resolve_dataset = api_main.resolve_dataset
    original_load_contract = api_main.load_contract
    original_execute_prediction = api_main.execute_prediction
    original_releases_root = api_main._inference_releases_root
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-m27-05-success-fixture",
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
        api_main.execute_prediction = lambda *_args, **_kwargs: {"result": _S0109_VALID_BINARY_RESULT}

        with tempfile.TemporaryDirectory() as releases_root:
            release_dir = Path(releases_root) / "release-m27-05-success-fixture"
            release_dir.mkdir(parents=True)
            (release_dir / "manifest.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
            api_main._inference_releases_root = lambda: Path(releases_root)

            response = api_main.validate_dataset_inference_payload(
                "fixture-dataset",
                payload={"age": 41},
            )

        assert not hasattr(response, "status_code")
        assert set(response.keys()) == {"dataset_slug", "result"}
        assert response["result"] == _S0109_VALID_BINARY_RESULT
        assert "prediction" not in response
        _assert_no_public_exposure(response)
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_contract = original_load_contract
        api_main.execute_prediction = original_execute_prediction
        api_main._inference_releases_root = original_releases_root
