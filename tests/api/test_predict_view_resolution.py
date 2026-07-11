"""
Predict view resolution endpoint tests for M18-03.

Exercises the GET /datasets/{dataset_slug}/views/{view_id} endpoint handler
via direct function calls and monkey-patching of api/main.py module-level
references. Tests confirm:
  - Valid dataset/view pair returns the expected safe public response.
  - Unknown dataset returns DATASET_NOT_FOUND (404).
  - Unknown view_id returns VIEW_NOT_FOUND (404).
  - View bound to a different dataset returns VIEW_NOT_FOUND (404).
  - View binding inconsistency returns VIEW_BINDING_INVALID (422).
  - Release unavailable returns RELEASE_UNAVAILABLE (503).
  - Registry unavailable returns REGISTRY_UNAVAILABLE (503).
  - Response never contains active_release, binding internals,
    contract_precedence, schema_version, or internal registry keys.
  - A synthetic, non-Telco/Bank dataset_slug/view_id pair resolves through
    load_public_predict_view via an isolated fixture registry file (M37-03),
    proving predict-view resolution is not hardcoded to the two seeded
    example datasets.

Run from the repository root:
    python -m pytest tests/api/test_predict_view_resolution.py -v
or directly:
    python tests/api/test_predict_view_resolution.py
"""

import json
import sys
import tempfile
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
from public_predict_view_loader import (  # noqa: E402
    ViewNotFoundError,
    ViewBindingInvalidError,
)

_VALID_VIEW_RESPONSE = {
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "display": {
        "title": "Churn Risk Overview",
        "summary": "Estimate whether a telecommunications customer is likely to churn.",
        "description": "A public prediction experience focused on customer churn risk interpretation.",
        "tags": ["churn", "retention"],
    },
    "intent": {
        "prediction_goal": "Estimate customer churn likelihood from the canonical dataset contract inputs.",
        "audience": "Public visitors evaluating churn risk examples.",
        "usage_notes": "Use the canonical dataset contracts for required fields, accepted values, and runtime validation.",
    },
    "release_mode": "active",
}


def _resolved(dataset_slug: str):
    from types import SimpleNamespace
    return SimpleNamespace(dataset_slug=dataset_slug, active_release="release-20260619-001")


def _response_json(response):
    return json.loads(response.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Golden path: valid dataset/view pair
# ---------------------------------------------------------------------------

def test_valid_view_returns_public_response():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert isinstance(response, dict)
        assert response["view_id"] == "churn-risk-overview"
        assert response["dataset_slug"] == "telco-customer-churn"
        assert "display" in response
        assert "intent" in response
        assert "release_mode" in response
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_valid_view_response_contains_display_fields():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert response["display"]["title"] == "Churn Risk Overview"
        assert "tags" in response["display"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_valid_view_response_contains_intent_fields():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert "prediction_goal" in response["intent"]
        assert "audience" in response["intent"]
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_valid_view_response_release_mode_is_active():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert response["release_mode"] == "active"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


# ---------------------------------------------------------------------------
# Public/private boundary: internal fields must not appear in response
# ---------------------------------------------------------------------------

def test_response_does_not_contain_active_release():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert "active_release" not in response
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_response_does_not_contain_contract_precedence():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert "contract_precedence" not in response
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_response_does_not_contain_schema_version():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert "schema_version" not in response
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_response_does_not_contain_binding_internals():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: dict(_VALID_VIEW_RESPONSE)
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert "binding" not in response
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


# ---------------------------------------------------------------------------
# Error cases: dataset resolution failures
# ---------------------------------------------------------------------------

def test_unknown_dataset_returns_dataset_not_found():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(DatasetUnavailableError("missing"))
        response = api_main.get_predict_view("unknown-dataset", "some-view")
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve


def test_release_unavailable_returns_release_unavailable():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(ReleaseUnavailableError("no release"))
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "RELEASE_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve


def test_registry_unavailable_returns_registry_unavailable():
    original_resolve = api_main.resolve_dataset
    try:
        api_main.resolve_dataset = lambda slug: (_ for _ in ()).throw(RegistryInvalidError("bad registry"))
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "REGISTRY_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve


# ---------------------------------------------------------------------------
# Error cases: view lookup failures
# ---------------------------------------------------------------------------

def test_unknown_view_id_returns_view_not_found():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: (_ for _ in ()).throw(
            ViewNotFoundError("not found")
        )
        response = api_main.get_predict_view("telco-customer-churn", "nonexistent-view")
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "VIEW_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


def test_view_binding_invalid_returns_view_binding_invalid():
    original_resolve = api_main.resolve_dataset
    original_load = api_main.load_public_predict_view
    try:
        api_main.resolve_dataset = lambda slug: _resolved(slug)
        api_main.load_public_predict_view = lambda slug, vid: (_ for _ in ()).throw(
            ViewBindingInvalidError("binding mismatch")
        )
        response = api_main.get_predict_view("telco-customer-churn", "churn-risk-overview")
        assert response.status_code == 422
        assert _response_json(response)["error_code"] == "VIEW_BINDING_INVALID"
    finally:
        api_main.resolve_dataset = original_resolve
        api_main.load_public_predict_view = original_load


# ---------------------------------------------------------------------------
# Loader unit tests: direct calls against registry/predict-views.json
# ---------------------------------------------------------------------------

def test_loader_resolves_valid_view_from_registry():
    from public_predict_view_loader import load_public_predict_view
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    result = load_public_predict_view(
        "telco-customer-churn",
        "churn-risk-overview",
        predict_views_path=registry_path,
    )
    assert result["view_id"] == "churn-risk-overview"
    assert result["dataset_slug"] == "telco-customer-churn"
    assert "display" in result
    assert "intent" in result
    assert result["release_mode"] == "active"


def test_loader_raises_view_not_found_for_unknown_view():
    from public_predict_view_loader import load_public_predict_view
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    raised = False
    try:
        load_public_predict_view(
            "telco-customer-churn",
            "nonexistent-view-id",
            predict_views_path=registry_path,
        )
    except ViewNotFoundError:
        raised = True
    assert raised, "Expected ViewNotFoundError for unknown view_id"


def test_loader_raises_view_not_found_for_wrong_dataset():
    from public_predict_view_loader import load_public_predict_view
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    raised = False
    try:
        load_public_predict_view(
            "bank-marketing",
            "churn-risk-overview",
            predict_views_path=registry_path,
        )
    except ViewNotFoundError:
        raised = True
    assert raised, "Expected ViewNotFoundError when view_id belongs to a different dataset"


def test_loader_result_excludes_binding_internals():
    from public_predict_view_loader import load_public_predict_view
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    result = load_public_predict_view(
        "telco-customer-churn",
        "churn-risk-overview",
        predict_views_path=registry_path,
    )
    assert "binding" not in result
    assert "contract_precedence" not in result
    assert "schema_version" not in result


def test_loader_result_keys_are_public_only():
    from public_predict_view_loader import load_public_predict_view
    registry_path = REPO_ROOT / "registry" / "predict-views.json"
    result = load_public_predict_view(
        "telco-customer-churn",
        "churn-risk-overview",
        predict_views_path=registry_path,
    )
    assert set(result.keys()) == {"view_id", "dataset_slug", "display", "intent", "release_mode"}


_BANK_MARKETING_FIXTURE_PREDICT_VIEWS_REGISTRY = {
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


def test_loader_resolves_bank_marketing_view():
    """
    Project Spec S0054: bank-marketing is no longer a required real-registry
    entry, so this coverage moved to an isolated fixture predict-views.json
    (tempfile.TemporaryDirectory), mirroring the M37-03 synthetic-dataset
    fixture convention below rather than depending on the real
    registry/predict-views.json still carrying this binding.
    """
    from public_predict_view_loader import load_public_predict_view
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "predict-views.json"
        registry_path.write_text(
            json.dumps(_BANK_MARKETING_FIXTURE_PREDICT_VIEWS_REGISTRY),
            encoding="utf-8",
        )
        result = load_public_predict_view(
            "bank-marketing",
            "bank-subscription-predictor",
            predict_views_path=registry_path,
        )
    assert result["view_id"] == "bank-subscription-predictor"
    assert result["dataset_slug"] == "bank-marketing"
    assert result["release_mode"] == "active"


# ---------------------------------------------------------------------------
# Arbitrary-dataset proof (M37-03): synthetic, non-Telco/Bank dataset
# ---------------------------------------------------------------------------
#
# Uses an isolated fixture predict-views.json passed via predict_views_path,
# mirroring the loader-unit-tests above rather than test_public_profile_fallback.py's
# heavier fake-repo-root convention, since load_public_predict_view already
# accepts a direct path override and never touches the real
# registry/predict-views.json.

_FIXTURE_PREDICT_VIEWS_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-views.v1",
    "predict_views": [
        {
            "schema_version": "1.0.0",
            "view_id": "fixture-arbitrary-view",
            "dataset_slug": "fixture-arbitrary-dataset",
            "display": {
                "title": "Fixture Arbitrary View",
                "summary": "Synthetic predict view for a non-Telco/Bank dataset.",
                "description": "Proves predict-view resolution is dataset-agnostic.",
                "tags": ["fixture"],
            },
            "intent": {
                "prediction_goal": "Resolve a synthetic, non-Telco/Bank dataset/view pair.",
                "audience": "Test-only.",
                "usage_notes": "Not a real product-facing predict view.",
            },
            "binding": {
                "dataset_slug": "fixture-arbitrary-dataset",
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


def test_loader_resolves_synthetic_non_telco_bank_dataset():
    from public_predict_view_loader import load_public_predict_view
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "predict-views.json"
        registry_path.write_text(
            json.dumps(_FIXTURE_PREDICT_VIEWS_REGISTRY), encoding="utf-8"
        )
        result = load_public_predict_view(
            "fixture-arbitrary-dataset",
            "fixture-arbitrary-view",
            predict_views_path=registry_path,
        )
    assert result["view_id"] == "fixture-arbitrary-view"
    assert result["dataset_slug"] == "fixture-arbitrary-dataset"
    assert result["release_mode"] == "active"
    assert set(result.keys()) == {"view_id", "dataset_slug", "display", "intent", "release_mode"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_valid_view_returns_public_response,
        test_valid_view_response_contains_display_fields,
        test_valid_view_response_contains_intent_fields,
        test_valid_view_response_release_mode_is_active,
        test_response_does_not_contain_active_release,
        test_response_does_not_contain_contract_precedence,
        test_response_does_not_contain_schema_version,
        test_response_does_not_contain_binding_internals,
        test_unknown_dataset_returns_dataset_not_found,
        test_release_unavailable_returns_release_unavailable,
        test_registry_unavailable_returns_registry_unavailable,
        test_unknown_view_id_returns_view_not_found,
        test_view_binding_invalid_returns_view_binding_invalid,
        test_loader_resolves_valid_view_from_registry,
        test_loader_raises_view_not_found_for_unknown_view,
        test_loader_raises_view_not_found_for_wrong_dataset,
        test_loader_result_excludes_binding_internals,
        test_loader_result_keys_are_public_only,
        test_loader_resolves_bank_marketing_view,
        test_loader_resolves_synthetic_non_telco_bank_dataset,
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
