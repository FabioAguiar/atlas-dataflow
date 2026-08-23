"""
Admin predict-view-customization route tests for M35-05 validation evidence.

Exercises api/admin_predict_view_customizations.py's read/save service
functions and api/main.py's GET/PUT
/admin/datasets/{dataset_slug}/views/{view_id}/customization access-control
and behavior boundary. Tests use direct function/Request-object calls (no
httpx/TestClient dependency, matching tests/api/test_admin_run_listing.py and
tests/api/test_admin_profile_drafts.py) and configure ATLAS_ADMIN_ENABLED and the
persistence module's repo_root exclusively through monkeypatched module
attributes or temporary os.environ entries -- never through a .env file or
the real repository's registry/predict-view-customizations.json.

resolve_dataset and load_public_contract are also monkeypatched to a fixed
in-memory public contract, so these tests exercise the admin write path's own
validation/persistence behavior without depending on real registry/releases
data.

Run from the repository root:
    python -m pytest tests/api/test_admin_predict_view_customizations.py -v
or directly:
    python tests/api/test_admin_predict_view_customizations.py
"""

import functools
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import admin_predict_view_customizations  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.predict_view_customization_store import (  # noqa: E402
    create_customization as _real_create_customization,
    get_customization as _real_get_customization,
    update_customization as _real_update_customization,
)
from registry.resolve import ResolvedDataset  # noqa: E402


_PUBLIC_CONTRACT = {
    "features": [
        {"name": "tenure", "optional": True},
        {"name": "senior_citizen", "optional": False},
    ]
}

_VALID_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
    "field_hints": [{"field_name": "tenure", "display_order_hint": 1}],
    "groups": [],
}


def _make_request(
    headers: dict[str, str],
    method: str = "GET",
    path: str = "/admin/datasets/telco-customer-churn/views/churn-risk-overview/customization",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _install_isolated_store(fake_repo: Path) -> tuple:
    """Monkeypatch admin_predict_view_customizations' persistence and
    contract-resolution calls onto fake_repo / a fixed public contract.

    Returns the originals so the caller can restore them in a finally block.
    """
    originals = (
        admin_predict_view_customizations.get_customization,
        admin_predict_view_customizations.create_customization,
        admin_predict_view_customizations.update_customization,
        admin_predict_view_customizations.resolve_dataset,
        admin_predict_view_customizations.load_public_contract,
    )
    admin_predict_view_customizations.get_customization = functools.partial(
        _real_get_customization, repo_root=fake_repo
    )
    admin_predict_view_customizations.create_customization = functools.partial(
        _real_create_customization, repo_root=fake_repo
    )
    admin_predict_view_customizations.update_customization = functools.partial(
        _real_update_customization, repo_root=fake_repo
    )
    admin_predict_view_customizations.resolve_dataset = lambda dataset_slug: ResolvedDataset(
        dataset_slug=dataset_slug, active_release="release-test-001"
    )
    admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT
    return originals


def _restore_store(originals: tuple) -> None:
    (
        admin_predict_view_customizations.get_customization,
        admin_predict_view_customizations.create_customization,
        admin_predict_view_customizations.update_customization,
        admin_predict_view_customizations.resolve_dataset,
        admin_predict_view_customizations.load_public_contract,
    ) = originals


# ---------------------------------------------------------------------------
# admin_predict_view_customizations.read_predict_view_customization /
# save_predict_view_customization: direct calls
# ---------------------------------------------------------------------------

def test_read_missing_customization_returns_deterministic_absence():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result == {
            "dataset_slug": "telco-customer-churn",
            "view_id": "churn-risk-overview",
            "customization_exists": False,
            "compatibility_status": "absent",
            "customization": None,
            "errors": [],
        }


def test_read_compatible_customization_returns_compatibility_status_compatible():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", dict(_VALID_CUSTOMIZATION)
            )
            result = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result["customization_exists"] is True
        assert result["compatibility_status"] == "compatible"
        assert result["customization"] == _VALID_CUSTOMIZATION
        assert result["errors"] == []


def test_read_incompatible_customization_returns_compatibility_status_incompatible_without_deleting_it():
    # Project Spec S0099: simulates the active release public contract
    # changing after the customization was saved -- the stored record still
    # references "tenure", which no longer exists in the new contract.
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", dict(_VALID_CUSTOMIZATION)
            )
            admin_predict_view_customizations.load_public_contract = (
                lambda active_release: {"features": [{"name": "MonthlyCharges", "optional": True}]}
            )
            result = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
            registry_file = fake_repo / "registry" / "predict-view-customizations.json"
            stored = json.loads(registry_file.read_text())
        finally:
            _restore_store(originals)

        assert result["customization_exists"] is True
        assert result["compatibility_status"] == "incompatible"
        assert result["customization"] is None
        assert any(error["code"] == "UNKNOWN_FIELD_REFERENCE" for error in result["errors"])
        # The stored record itself must remain untouched -- an incompatible
        # classification never deletes, rewrites, or migrates it.
        assert stored["predict_view_customizations"][0]["field_hints"][0]["field_name"] == "tenure"


def test_read_returns_incompatible_when_public_contract_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", dict(_VALID_CUSTOMIZATION)
            )

            def _raise(active_release):
                raise admin_predict_view_customizations.PublicContractUnavailableError("unavailable")

            admin_predict_view_customizations.load_public_contract = _raise
            result = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result["compatibility_status"] == "incompatible"
        assert result["customization"] is None
        assert any(error["code"] == "PUBLIC_CONTRACT_UNAVAILABLE" for error in result["errors"])


def test_save_creates_customization_transparently_when_none_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", dict(_VALID_CUSTOMIZATION)
            )
            read_back = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["customization"] == _VALID_CUSTOMIZATION
        assert result["errors"] == []
        assert read_back["customization_exists"] is True
        assert read_back["customization"] == _VALID_CUSTOMIZATION


def test_save_updates_existing_customization_in_place():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", dict(_VALID_CUSTOMIZATION)
            )
            updated = dict(_VALID_CUSTOMIZATION, groups=[{"group_id": "g1", "label": "Group 1"}])
            result = admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", updated
            )
            read_back = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["customization"]["groups"] == [{"group_id": "g1", "label": "Group 1"}]
        assert read_back["customization"]["groups"] == [{"group_id": "g1", "label": "Group 1"}]


def test_save_round_trips_view_copy_submit_button_label():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            customization = dict(
                _VALID_CUSTOMIZATION,
                view_copy={
                    "heading": "Churn Risk Assessment",
                    "submit_button_label": "Estimate Churn Risk",
                },
            )
            result = admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", customization
            )
            read_back = admin_predict_view_customizations.read_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview"
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["customization"]["view_copy"]["submit_button_label"] == "Estimate Churn Risk"
        assert read_back["customization"]["view_copy"]["heading"] == "Churn Risk Assessment"
        assert read_back["customization"]["view_copy"]["submit_button_label"] == "Estimate Churn Risk"


def test_save_rejects_unknown_field_reference_without_saving():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            invalid = dict(
                _VALID_CUSTOMIZATION,
                field_hints=[{"field_name": "not_a_real_field"}],
            )
            result = admin_predict_view_customizations.save_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", invalid
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is False
        assert result["customization"] is None
        assert any(error["code"] == "UNKNOWN_FIELD_REFERENCE" for error in result["errors"])


# ---------------------------------------------------------------------------
# Project Spec S0250: public-contract v2 (univariate-forecasting
# history-series) customization compatibility through the same admin
# read/save service functions.
# ---------------------------------------------------------------------------

_PUBLIC_CONTRACT_V2 = {
    "schema_version": "2.0.0",
    "problem_type": "univariate_forecasting",
    "input_kind": "history_series",
    "history_series": {
        "time_index_field": {"name": "period", "label": "Period", "value_kind": "calendar_period", "display_order": 1},
        "target_field": {"name": "value", "label": "Value", "value_kind": "number", "display_order": 2},
        "frequency": "Monthly",
    },
    "forecast": {"forecast_horizon": 12, "horizon_user_editable": False},
}

_VALID_HISTORY_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "forecast-overview",
    "dataset_slug": "example-forecasting-dataset",
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
    "field_hints": [
        {"field_name": "period", "display_label": "Month", "display_order_hint": 1},
        {"field_name": "value", "display_label": "Sales", "display_order_hint": 2},
    ],
    "groups": [],
}


def test_save_accepts_compatible_v2_history_series_customization():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            result = admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", dict(_VALID_HISTORY_CUSTOMIZATION)
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["customization"] == _VALID_HISTORY_CUSTOMIZATION
        assert result["errors"] == []


def test_read_classifies_compatible_v2_history_series_customization():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", dict(_VALID_HISTORY_CUSTOMIZATION)
            )
            result = admin_predict_view_customizations.read_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview"
            )
        finally:
            _restore_store(originals)

        assert result["customization_exists"] is True
        assert result["compatibility_status"] == "compatible"
        assert result["customization"] == _VALID_HISTORY_CUSTOMIZATION
        assert result["errors"] == []


def test_save_rejects_hidden_required_v2_history_series_field():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            invalid = dict(
                _VALID_HISTORY_CUSTOMIZATION,
                field_hints=[
                    {"field_name": "period", "hidden": True},
                    {"field_name": "value"},
                ],
            )
            result = admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", invalid
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is False
        assert any(error["code"] == "REQUIRED_FIELD_HIDDEN" for error in result["errors"])


def test_save_rejects_grouped_v2_history_series_field():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            invalid = dict(
                _VALID_HISTORY_CUSTOMIZATION,
                groups=[{"group_id": "g1", "label": "Group 1"}],
                field_hints=[
                    {"field_name": "period", "group": "g1"},
                    {"field_name": "value"},
                ],
            )
            result = admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", invalid
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is False
        codes = {error["code"] for error in result["errors"]}
        assert "HISTORY_SERIES_GROUPS_NOT_ALLOWED" in codes
        assert "HISTORY_SERIES_FIELD_GROUP_NOT_ALLOWED" in codes


def test_read_incompatible_v2_history_series_customization_preserved_not_deleted():
    # Simulates the active release public contract renaming the target
    # history-series field after the customization was saved -- the stored
    # record still references the old name, which no longer resolves.
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", dict(_VALID_HISTORY_CUSTOMIZATION)
            )
            renamed_contract = json.loads(json.dumps(_PUBLIC_CONTRACT_V2))
            renamed_contract["history_series"]["target_field"]["name"] = "renamed_value"
            admin_predict_view_customizations.load_public_contract = lambda active_release: renamed_contract
            result = admin_predict_view_customizations.read_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview"
            )
            registry_file = fake_repo / "registry" / "predict-view-customizations.json"
            stored = json.loads(registry_file.read_text())
        finally:
            _restore_store(originals)

        assert result["compatibility_status"] == "incompatible"
        assert result["customization"] is None
        assert any(error["code"] == "UNKNOWN_FIELD_REFERENCE" for error in result["errors"])
        assert stored["predict_view_customizations"][0]["field_hints"][1]["field_name"] == "value"


def test_read_incompatible_when_v2_public_contract_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            admin_predict_view_customizations.load_public_contract = lambda active_release: _PUBLIC_CONTRACT_V2
            admin_predict_view_customizations.save_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview", dict(_VALID_HISTORY_CUSTOMIZATION)
            )

            def _raise(active_release):
                raise admin_predict_view_customizations.PublicContractUnavailableError("unavailable")

            admin_predict_view_customizations.load_public_contract = _raise
            result = admin_predict_view_customizations.read_predict_view_customization(
                "example-forecasting-dataset", "forecast-overview"
            )
        finally:
            _restore_store(originals)

        assert result["compatibility_status"] == "incompatible"
        assert result["customization"] is None
        assert any(error["code"] == "PUBLIC_CONTRACT_UNAVAILABLE" for error in result["errors"])


def test_read_and_save_raise_value_error_for_invalid_identifiers():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            try:
                admin_predict_view_customizations.read_predict_view_customization(
                    "Invalid Slug", "churn-risk-overview"
                )
                assert False, "expected ValueError"
            except ValueError:
                pass

            try:
                admin_predict_view_customizations.save_predict_view_customization(
                    "telco-customer-churn", "../escape", dict(_VALID_CUSTOMIZATION)
                )
                assert False, "expected ValueError"
            except ValueError:
                pass
        finally:
            _restore_store(originals)


# ---------------------------------------------------------------------------
# GET/PUT /admin/datasets/{dataset_slug}/views/{view_id}/customization:
# access-control boundary
# ---------------------------------------------------------------------------

def test_get_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({})
    response = api_main.get_admin_predict_view_customization(
        "telco-customer-churn", "churn-risk-overview", request
    )
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_put_route_returns_generic_not_found_when_admin_runtime_false_even_with_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"}, method="PUT")
        response = api_main.put_admin_predict_view_customization(
            "telco-customer-churn", "churn-risk-overview", request, dict(_VALID_CUSTOMIZATION)
        )
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_get_route_returns_absence_for_missing_customization_in_private_runtime_without_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            request = _make_request({})
            response = api_main.get_admin_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", request
            )
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response == {
        "dataset_slug": "telco-customer-churn",
        "view_id": "churn-risk-overview",
        "customization_exists": False,
        "compatibility_status": "absent",
        "customization": None,
        "errors": [],
    }


def test_put_then_get_route_round_trip_in_private_runtime_without_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            put_request = _make_request({}, method="PUT")
            put_response = api_main.put_admin_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", put_request, dict(_VALID_CUSTOMIZATION)
            )

            get_request = _make_request({})
            get_response = api_main.get_admin_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", get_request
            )
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert put_response["saved"] is True
    assert put_response["customization"] == _VALID_CUSTOMIZATION
    assert get_response["customization_exists"] is True
    assert get_response["compatibility_status"] == "compatible"
    assert get_response["customization"] == _VALID_CUSTOMIZATION


def test_put_route_returns_422_with_passthrough_errors_on_invalid_customization():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = Path(tmp)
        (fake_repo / "registry").mkdir()
        originals = _install_isolated_store(fake_repo)
        try:
            invalid = dict(_VALID_CUSTOMIZATION, field_hints=[{"field_name": "not_a_real_field"}])
            request = _make_request({}, method="PUT")
            response = api_main.put_admin_predict_view_customization(
                "telco-customer-churn", "churn-risk-overview", request, invalid
            )
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "PREDICT_VIEW_CUSTOMIZATION_INVALID"
    assert body["errors"], "expected passthrough validation errors"


def test_get_and_put_route_return_422_for_invalid_identifiers():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    try:
        get_request = _make_request(
            {},
            path="/admin/datasets/Invalid Slug/views/churn-risk-overview/customization",
        )
        get_response = api_main.get_admin_predict_view_customization(
            "Invalid Slug", "churn-risk-overview", get_request
        )
        assert get_response.status_code == 422
        assert json.loads(get_response.body.decode("utf-8"))["error_code"] == (
            "PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID"
        )

        put_request = _make_request(
            {},
            method="PUT",
            path="/admin/datasets/telco-customer-churn/views/../escape/customization",
        )
        put_response = api_main.put_admin_predict_view_customization(
            "telco-customer-churn", "../escape", put_request, dict(_VALID_CUSTOMIZATION)
        )
        assert put_response.status_code == 422
        assert json.loads(put_response.body.decode("utf-8"))["error_code"] == (
            "PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID"
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------

def test_customization_admin_route_registered_only_under_admin_and_public_route_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/views/{view_id}/customization" in paths
    assert "/datasets/{dataset_slug}/views/{view_id}/customization" in paths

    public_paths = {path for path in paths if not path.startswith("/admin")}
    admin_only_customization_paths = {
        path for path in public_paths
        if "customization" in path and "views" in path and path.startswith("/admin")
    }
    assert admin_only_customization_paths == set()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
