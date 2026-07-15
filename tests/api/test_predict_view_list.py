"""
Predict view listing endpoint tests for M18-04.

Exercises the GET /datasets/{dataset_slug}/views endpoint handler via direct
function calls and monkey-patching of api/main.py module-level references.
Tests confirm:
  - Valid dataset slug with views returns HTTP 200 with dataset_slug and
    non-empty views array.
  - Each item contains view_id, dataset_slug, display, intent, release_mode.
  - Valid dataset slug with no matching views returns HTTP 200 with empty list.
  - Unknown dataset_slug returns DATASET_NOT_FOUND (404).
  - Release unavailable returns RELEASE_UNAVAILABLE (503).
  - Registry unavailable (ViewNotFoundError from loader) returns
    REGISTRY_UNAVAILABLE (503).
  - Response items do not contain binding internals, contract_precedence,
    schema_version, or internal registry fields.
  - Binding-inconsistent views are excluded from the returned list.

Run from the repository root:
    python -m pytest tests/api/test_predict_view_list.py -v
or directly:
    python tests/api/test_predict_view_list.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
)
from public_predict_view_loader import ViewNotFoundError  # noqa: E402

_CHURN_VIEW = {
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "display": {"title": "Churn Risk Overview", "summary": "Estimate churn likelihood."},
    "intent": {
        "prediction_goal": "Estimate churn",
        "audience": "Public visitors",
        "usage_notes": "Use canonical contract inputs.",
    },
    "release_mode": "active",
}


def _resolved(dataset_slug: str):
    from types import SimpleNamespace
    return SimpleNamespace(dataset_slug=dataset_slug, active_release="release-20260619-001")


def _response_json(response):
    return json.loads(response.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Golden path: valid dataset with views
# ---------------------------------------------------------------------------

def test_valid_dataset_returns_views_list():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        assert isinstance(response, dict)
        assert response["dataset_slug"] == "telco-customer-churn"
        assert isinstance(response["views"], list)
        assert len(response["views"]) == 1
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_views_list_item_contains_required_fields():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert item["view_id"] == "churn-risk-overview"
        assert item["dataset_slug"] == "telco-customer-churn"
        assert "display" in item
        assert "intent" in item
        assert "release_mode" in item
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_views_list_item_display_contains_title_and_summary():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert item["display"]["title"] == "Churn Risk Overview"
        assert "summary" in item["display"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_views_list_item_intent_contains_required_fields():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert "prediction_goal" in item["intent"]
        assert "audience" in item["intent"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_views_list_item_release_mode_is_active():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        assert response["views"][0]["release_mode"] == "active"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


# ---------------------------------------------------------------------------
# Valid dataset with no matching views returns empty list
# ---------------------------------------------------------------------------

def test_dataset_with_no_views_returns_empty_list():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: []
        response = api_main.list_predict_views("some-dataset-no-views")
        assert isinstance(response, dict)
        assert response["dataset_slug"] == "some-dataset-no-views"
        assert response["views"] == []
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


# ---------------------------------------------------------------------------
# Public/private boundary: internal fields must not appear in response items
# ---------------------------------------------------------------------------

def test_response_items_do_not_contain_binding():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert "binding" not in item
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_response_items_do_not_contain_contract_precedence():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert "contract_precedence" not in item
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


def test_response_items_do_not_contain_schema_version():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: [dict(_CHURN_VIEW)]
        response = api_main.list_predict_views("telco-customer-churn")
        item = response["views"][0]
        assert "schema_version" not in item
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


# ---------------------------------------------------------------------------
# Error cases: dataset resolution failures
# ---------------------------------------------------------------------------

def test_unknown_dataset_returns_dataset_not_found():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(DatasetUnavailableError("missing"))
        response = api_main.list_predict_views("unknown-dataset")
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve


def test_release_unavailable_returns_release_unavailable():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(ReleaseUnavailableError("no release"))
        response = api_main.list_predict_views("telco-customer-churn")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "RELEASE_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve


def test_registry_unavailable_returns_registry_unavailable():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(RegistryInvalidError("bad registry"))
        response = api_main.list_predict_views("telco-customer-churn")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "REGISTRY_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve


def test_loader_raises_view_not_found_returns_registry_unavailable():
    original_resolve = api_main.resolve_dataset
    original_list = api_main.load_public_predict_view_list
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view_list = lambda slug: (_ for _ in ()).throw(
            ViewNotFoundError("registry unavailable")
        )
        response = api_main.list_predict_views("telco-customer-churn")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "REGISTRY_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view_list = original_list


# ---------------------------------------------------------------------------
# Loader unit tests: direct calls against registry/predict-views.json
# ---------------------------------------------------------------------------

def test_production_loader_returns_no_views_when_registry_is_empty(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(
        json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []}),
        encoding="utf-8",
    )
    results = load_public_predict_view_list("telco-customer-churn", predict_views_path=registry_path)
    assert results == []


def test_loader_returns_views_for_bank_dataset(tmp_path):
    """
    Project Spec S0054: bank-marketing is no longer a required real-registry
    entry, so this coverage moved to a fixture-local predict-views.json
    (tmp_path) instead of registry/predict-views.json. The fixture record
    mirrors the removed real bank-subscription-predictor binding exactly, so
    the loader's multi-dataset behavior stays covered without depending on
    bank-marketing existing in the real registry.
    """
    from public_predict_view_loader import load_public_predict_view_list
    registry_data = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {
                "schema_version": "1.0.0",
                "view_id": "bank-subscription-predictor",
                "dataset_slug": "bank-marketing",
                "display": {
                    "title": "Bank Subscription Predictor",
                    "summary": "Predict whether a bank client will subscribe to a term deposit.",
                },
                "intent": {
                    "prediction_goal": "Predict client subscription to a term deposit from canonical dataset contract inputs.",
                    "audience": "Public visitors evaluating bank marketing campaign outcomes.",
                    "usage_notes": "Use the canonical dataset contracts for required fields, accepted values, and runtime validation.",
                },
                "binding": {
                    "dataset_slug": "bank-marketing",
                    "release": {"mode": "active"},
                },
                "contract_precedence": {
                    "canonical_contracts_are_source_of_truth": True,
                    "view_metadata_defines_runtime_validation": False,
                    "view_metadata_duplicates_contract": False,
                },
            }
        ],
    }
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    results = load_public_predict_view_list("bank-marketing", predict_views_path=registry_path)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["view_id"] == "bank-subscription-predictor"


def test_loader_returns_empty_list_for_unknown_dataset():
    from public_predict_view_loader import load_public_predict_view_list
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    results = load_public_predict_view_list("nonexistent-dataset", predict_views_path=registry_path)
    assert results == []


def test_loader_result_items_exclude_binding_internals(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": [{"view_id": "fixture-view", "dataset_slug": "fixture-dataset", "display": {}, "intent": {}, "binding": {"dataset_slug": "fixture-dataset", "release": {"mode": "active"}}}]}), encoding="utf-8")
    results = load_public_predict_view_list("fixture-dataset", predict_views_path=registry_path)
    item = results[0]
    assert "binding" not in item
    assert "contract_precedence" not in item
    assert "schema_version" not in item


def test_loader_result_items_have_only_public_keys(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": [{"view_id": "fixture-view", "dataset_slug": "fixture-dataset", "display": {}, "intent": {}, "binding": {"dataset_slug": "fixture-dataset", "release": {"mode": "active"}}}]}), encoding="utf-8")
    results = load_public_predict_view_list("fixture-dataset", predict_views_path=registry_path)
    item = results[0]
    assert set(item.keys()) == {"view_id", "dataset_slug", "display", "intent", "release_mode"}


def test_loader_filters_orphan_when_dataset_registry_is_supplied(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    views_path = tmp_path / "predict-views.json"
    datasets_path = tmp_path / "datasets.json"
    views_path.write_text(json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": [{"view_id": "orphan-view", "dataset_slug": "removed-dataset", "binding": {"dataset_slug": "removed-dataset", "release": {"mode": "active"}}}]}), encoding="utf-8")
    datasets_path.write_text(json.dumps({"datasets": []}), encoding="utf-8")
    assert load_public_predict_view_list("removed-dataset", views_path, datasets_path) == []


def test_loader_excludes_binding_inconsistent_views(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    registry_data = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {
                "view_id": "valid-view",
                "dataset_slug": "my-dataset",
                "display": {"title": "Valid View", "summary": "A valid view."},
                "intent": {"prediction_goal": "test", "audience": "public", "usage_notes": "n/a"},
                "binding": {"dataset_slug": "my-dataset", "release": {"mode": "active"}},
                "contract_precedence": {"canonical_contracts_are_source_of_truth": True},
            },
            {
                "view_id": "inconsistent-view",
                "dataset_slug": "my-dataset",
                "display": {"title": "Inconsistent View", "summary": "Binding mismatch."},
                "intent": {"prediction_goal": "test", "audience": "public", "usage_notes": "n/a"},
                "binding": {"dataset_slug": "OTHER-DATASET", "release": {"mode": "active"}},
                "contract_precedence": {"canonical_contracts_are_source_of_truth": True},
            },
        ],
    }
    registry_path = tmp_path / "predict-views.json"
    import json as _json
    registry_path.write_text(_json.dumps(registry_data), encoding="utf-8")

    results = load_public_predict_view_list("my-dataset", predict_views_path=registry_path)
    assert len(results) == 1
    assert results[0]["view_id"] == "valid-view"


def test_loader_display_contains_only_title_and_summary(tmp_path):
    from public_predict_view_loader import load_public_predict_view_list
    registry_path = tmp_path / "predict-views.json"
    registry_path.write_text(json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": [{"view_id": "fixture-view", "dataset_slug": "fixture-dataset", "display": {"title": "Fixture", "summary": "Safe", "description": "private", "tags": ["private"]}, "intent": {}, "binding": {"dataset_slug": "fixture-dataset", "release": {"mode": "active"}}}]}), encoding="utf-8")
    results = load_public_predict_view_list("fixture-dataset", predict_views_path=registry_path)
    display = results[0]["display"]
    assert "title" in display
    assert "summary" in display
    assert "description" not in display
    assert "tags" not in display


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile as _tempfile, pathlib as _pathlib

    tests_no_args = [
        test_valid_dataset_returns_views_list,
        test_views_list_item_contains_required_fields,
        test_views_list_item_display_contains_title_and_summary,
        test_views_list_item_intent_contains_required_fields,
        test_views_list_item_release_mode_is_active,
        test_dataset_with_no_views_returns_empty_list,
        test_response_items_do_not_contain_binding,
        test_response_items_do_not_contain_contract_precedence,
        test_response_items_do_not_contain_schema_version,
        test_unknown_dataset_returns_dataset_not_found,
        test_release_unavailable_returns_release_unavailable,
        test_registry_unavailable_returns_registry_unavailable,
        test_loader_raises_view_not_found_returns_registry_unavailable,
        test_loader_returns_views_for_telco_dataset,
        test_loader_returns_empty_list_for_unknown_dataset,
        test_loader_result_items_exclude_binding_internals,
        test_loader_result_items_have_only_public_keys,
        test_loader_display_contains_only_title_and_summary,
    ]

    passed = 0
    failed = 0

    for t in tests_no_args:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {t.__name__}: {exc}")
            failed += 1

    with _tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_loader_excludes_binding_inconsistent_views(_pathlib.Path(tmpdir))
            print("PASS  test_loader_excludes_binding_inconsistent_views")
            passed += 1
        except Exception as exc:
            print(f"FAIL  test_loader_excludes_binding_inconsistent_views: {exc}")
            failed += 1

    with _tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_loader_returns_views_for_bank_dataset(_pathlib.Path(tmpdir))
            print("PASS  test_loader_returns_views_for_bank_dataset")
            passed += 1
        except Exception as exc:
            print(f"FAIL  test_loader_returns_views_for_bank_dataset: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
