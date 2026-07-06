"""
Admin profile draft route tests for M34-04 validation evidence.

Exercises api/admin_profile_drafts.py's read/save service functions and
api/main.py's GET/PUT /admin/datasets/{dataset_slug}/profile-draft access-
control and behavior boundary. Tests use direct function/Request-object
calls (no httpx/TestClient dependency, matching tests/api/test_admin_run_listing.py)
and configure ADMIN_API_TOKEN and the persistence module's repo_root
exclusively through monkeypatched module attributes or temporary
os.environ entries -- never through a .env file or the real repository's
registry/profile-drafts/ directory.

Draft persistence is isolated onto a fake repository root (pytest tmp_path)
with the real contracts/dataset-public-profile.schema.json copied in, the
same isolation convention tests/registry/test_dataset_public_profile_store.py
uses for the M34-03 persistence module directly.

Run from the repository root:
    python -m pytest tests/api/test_admin_profile_drafts.py -v
or directly:
    python tests/api/test_admin_profile_drafts.py
"""

import functools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import admin_profile_drafts  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.dataset_public_profile_store import (  # noqa: E402
    create_draft as _real_create_draft,
    get_draft as _real_get_draft,
    update_draft as _real_update_draft,
)


def _make_request(
    headers: dict[str, str],
    method: str = "GET",
    path: str = "/admin/datasets/example-dataset/profile-draft",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _build_fake_repo(tmp_root: Path) -> Path:
    """Build a fake repo root carrying only the real profile schema.

    No registry/predict-views.json or registry/datasets.json is needed:
    the persistence module's own loaders default gracefully (empty
    registry / empty metrics) when those files are absent, and the
    fixtures below never set inference_presentation.bound_predict_view_id
    or home_card.primary_metric_key, so no reference check is exercised.
    """
    schema_src = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir(parents=True)
    shutil.copy2(schema_src, contracts_dir / "dataset-public-profile.schema.json")
    return tmp_root


def _install_isolated_store(fake_repo: Path) -> tuple:
    """Monkeypatch admin_profile_drafts' persistence calls onto fake_repo.

    Returns the (get_draft, create_draft, update_draft) originals so the
    caller can restore them in a finally block.
    """
    originals = (
        admin_profile_drafts.get_draft,
        admin_profile_drafts.create_draft,
        admin_profile_drafts.update_draft,
    )
    admin_profile_drafts.get_draft = functools.partial(_real_get_draft, repo_root=fake_repo)
    admin_profile_drafts.create_draft = functools.partial(_real_create_draft, repo_root=fake_repo)
    admin_profile_drafts.update_draft = functools.partial(_real_update_draft, repo_root=fake_repo)
    return originals


def _restore_store(originals: tuple) -> None:
    (
        admin_profile_drafts.get_draft,
        admin_profile_drafts.create_draft,
        admin_profile_drafts.update_draft,
    ) = originals


_VALID_PROFILE = {
    "schema_version": "0.1.0",
    "dataset_slug": "example-dataset",
}


# ---------------------------------------------------------------------------
# admin_profile_drafts.read_profile_draft / save_profile_draft: direct calls
# ---------------------------------------------------------------------------

def test_read_missing_draft_returns_deterministic_absence():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_profile_drafts.read_profile_draft("example-dataset")
        finally:
            _restore_store(originals)

        assert result == {
            "dataset_slug": "example-dataset",
            "draft_exists": False,
            "profile": None,
        }


def test_save_creates_draft_transparently_when_none_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_profile_drafts.save_profile_draft(
                "example-dataset", dict(_VALID_PROFILE)
            )
            read_back = admin_profile_drafts.read_profile_draft("example-dataset")
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["profile"] == _VALID_PROFILE
        assert result["errors"] == []
        assert read_back == {
            "dataset_slug": "example-dataset",
            "draft_exists": True,
            "profile": _VALID_PROFILE,
        }


def test_save_updates_existing_draft_in_place():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            admin_profile_drafts.save_profile_draft(
                "example-dataset", dict(_VALID_PROFILE)
            )
            updated_profile = dict(_VALID_PROFILE, theme={"preset": "atlas-green"})
            result = admin_profile_drafts.save_profile_draft(
                "example-dataset", updated_profile
            )
            read_back = admin_profile_drafts.read_profile_draft("example-dataset")
        finally:
            _restore_store(originals)

        assert result["saved"] is True
        assert result["profile"] == updated_profile
        assert read_back["profile"] == updated_profile


def test_save_rejects_dataset_slug_mismatch_without_saving():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            mismatched_profile = dict(_VALID_PROFILE, dataset_slug="other-dataset")
            result = admin_profile_drafts.save_profile_draft(
                "example-dataset", mismatched_profile
            )
        finally:
            _restore_store(originals)

        assert result["saved"] is False
        assert result["profile"] is None
        assert any(error["code"] == "DATASET_SLUG_MISMATCH" for error in result["errors"])


def test_read_and_save_raise_value_error_for_invalid_dataset_slug():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            try:
                admin_profile_drafts.read_profile_draft("Invalid Slug")
                assert False, "expected ValueError"
            except ValueError:
                pass

            try:
                admin_profile_drafts.save_profile_draft(
                    "../escape", dict(_VALID_PROFILE, dataset_slug="../escape")
                )
                assert False, "expected ValueError"
            except ValueError:
                pass
        finally:
            _restore_store(originals)


# ---------------------------------------------------------------------------
# GET/PUT /admin/datasets/{dataset_slug}/profile-draft: access-control boundary
# ---------------------------------------------------------------------------

def test_get_route_returns_generic_not_found_when_token_env_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({"X-Admin-Token": "irrelevant"})
    response = api_main.get_admin_profile_draft("example-dataset", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_put_route_returns_generic_not_found_when_token_incorrect():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"}, method="PUT")
        response = api_main.put_admin_profile_draft(
            "example-dataset", request, dict(_VALID_PROFILE)
        )
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_get_route_returns_absence_for_missing_draft_with_valid_token():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            request = _make_request({"X-Admin-Token": "correct-token"})
            response = api_main.get_admin_profile_draft("example-dataset", request)
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response == {
        "dataset_slug": "example-dataset",
        "draft_exists": False,
        "profile": None,
    }


def test_put_then_get_route_round_trip_with_valid_token():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            put_request = _make_request({"X-Admin-Token": "correct-token"}, method="PUT")
            put_response = api_main.put_admin_profile_draft(
                "example-dataset", put_request, dict(_VALID_PROFILE)
            )

            get_request = _make_request({"X-Admin-Token": "correct-token"})
            get_response = api_main.get_admin_profile_draft("example-dataset", get_request)
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert put_response == {
        "dataset_slug": "example-dataset",
        "saved": True,
        "profile": _VALID_PROFILE,
        "errors": [],
    }
    assert get_response == {
        "dataset_slug": "example-dataset",
        "draft_exists": True,
        "profile": _VALID_PROFILE,
    }


def test_put_route_returns_422_with_passthrough_errors_on_invalid_profile():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            invalid_profile = {"dataset_slug": "example-dataset"}  # missing schema_version
            request = _make_request({"X-Admin-Token": "correct-token"}, method="PUT")
            response = api_main.put_admin_profile_draft(
                "example-dataset", request, invalid_profile
            )
        finally:
            _restore_store(originals)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "PROFILE_DRAFT_INVALID"
    assert body["errors"], "expected passthrough validation errors"


def test_get_and_put_route_return_422_for_invalid_dataset_slug():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        get_request = _make_request(
            {"X-Admin-Token": "correct-token"},
            path="/admin/datasets/Invalid Slug/profile-draft",
        )
        get_response = api_main.get_admin_profile_draft("Invalid Slug", get_request)
        assert get_response.status_code == 422
        assert json.loads(get_response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_DRAFT_DATASET_SLUG_INVALID"
        )

        put_request = _make_request(
            {"X-Admin-Token": "correct-token"},
            method="PUT",
            path="/admin/datasets/Invalid Slug/profile-draft",
        )
        put_response = api_main.put_admin_profile_draft(
            "Invalid Slug", put_request, dict(_VALID_PROFILE, dataset_slug="Invalid Slug")
        )
        assert put_response.status_code == 422
        assert json.loads(put_response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_DRAFT_DATASET_SLUG_INVALID"
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------

def test_profile_draft_route_registered_only_under_admin_and_public_datasets_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/profile-draft" in paths

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("profile-draft" in path for path in public_paths)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
