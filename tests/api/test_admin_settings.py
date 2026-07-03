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

import admin_settings  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.admin_settings_store import (  # noqa: E402
    get_admin_settings as _real_get_admin_settings,
    save_admin_settings as _real_save_admin_settings,
)


def _make_request(
    headers: dict[str, str],
    method: str = "GET",
    path: str = "/admin/settings",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _build_fake_repo(tmp_root: Path) -> Path:
    schema_src = REPO_ROOT / "contracts" / "admin-settings.schema.json"
    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir(parents=True)
    shutil.copy2(schema_src, contracts_dir / "admin-settings.schema.json")
    (tmp_root / "registry").mkdir()
    return tmp_root


def _install_isolated_store(fake_repo: Path) -> tuple:
    originals = (
        admin_settings.get_admin_settings,
        admin_settings.save_admin_settings,
    )
    admin_settings.get_admin_settings = functools.partial(_real_get_admin_settings, repo_root=fake_repo)
    admin_settings.save_admin_settings = functools.partial(_real_save_admin_settings, repo_root=fake_repo)
    return originals


def _restore_store(originals: tuple) -> None:
    (
        admin_settings.get_admin_settings,
        admin_settings.save_admin_settings,
    ) = originals


def test_read_service_returns_default_display_name_only():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_settings.read_admin_settings()
        finally:
            _restore_store(originals)

    assert result == {"settings": {"display_name": "Internal operator"}}


def test_write_service_persists_display_name_only_settings():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            result = admin_settings.write_admin_settings({"display_name": "Operations lead"})
            read_back = admin_settings.read_admin_settings()
        finally:
            _restore_store(originals)

    assert result["saved"] is True
    assert result["settings"] == {"display_name": "Operations lead"}
    assert read_back == {"settings": {"display_name": "Operations lead"}}


def test_get_route_returns_generic_not_found_when_token_env_unset():
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({"X-Admin-Token": "irrelevant"})
    response = api_main.get_admin_settings_route(request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_put_route_returns_generic_not_found_when_token_incorrect():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"}, method="PUT")
        response = api_main.put_admin_settings_route(
            request, {"display_name": "Operations lead"}
        )
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_get_route_returns_settings_with_valid_token():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            request = _make_request({"X-Admin-Token": "correct-token"})
            response = api_main.get_admin_settings_route(request)
        finally:
            _restore_store(originals)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response == {"settings": {"display_name": "Internal operator"}}


def test_put_route_rejects_unsupported_field_with_valid_token():
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        originals = _install_isolated_store(fake_repo)
        try:
            request = _make_request({"X-Admin-Token": "correct-token"}, method="PUT")
            response = api_main.put_admin_settings_route(
                request,
                {"display_name": "Operations lead", "email": "operator@example.com"},
            )
        finally:
            _restore_store(originals)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "ADMIN_SETTINGS_INVALID"
    assert any(error["code"] == "SCHEMA_VALIDATION_ERROR" for error in body["errors"])
