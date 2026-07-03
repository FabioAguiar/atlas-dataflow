import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.admin_settings_store import (  # noqa: E402
    get_admin_settings,
    read_admin_settings,
    save_admin_settings,
    validate_admin_settings,
)


def _build_fake_repo(tmp_path: Path) -> Path:
    schema_src = REPO_ROOT / "contracts" / "admin-settings.schema.json"
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    shutil.copy2(schema_src, contracts_dir / "admin-settings.schema.json")
    (tmp_path / "registry").mkdir()
    return tmp_path


def test_get_admin_settings_returns_display_name_only_default_when_missing(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)

    settings = get_admin_settings(repo_root=fake_repo)

    assert settings == {"display_name": "Internal operator"}


def test_save_then_read_admin_settings_round_trip(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)
    candidate = {"display_name": "Operations lead"}

    result = save_admin_settings(candidate, repo_root=fake_repo)
    read_back = read_admin_settings(repo_root=fake_repo)

    assert result["saved"] is True
    assert result["settings"] == candidate
    assert result["errors"] == []
    assert result["path"] == "registry/admin-settings/admin-settings.json"
    assert read_back == candidate


def test_save_rejects_unsupported_fields_without_writing(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)
    candidate = {"display_name": "Operations lead", "email": "operator@example.com"}

    result = save_admin_settings(candidate, repo_root=fake_repo)

    assert result["saved"] is False
    assert result["settings"] is None
    assert any(error["code"] == "SCHEMA_VALIDATION_ERROR" for error in result["errors"])
    assert not (fake_repo / "registry" / "admin-settings" / "admin-settings.json").exists()


def test_save_rejects_blank_display_name_without_writing(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)

    result = save_admin_settings({"display_name": "   "}, repo_root=fake_repo)

    assert result["saved"] is False
    assert any(error["field"] == "display_name" for error in result["errors"])
    assert not (fake_repo / "registry" / "admin-settings" / "admin-settings.json").exists()


def test_invalid_persisted_file_falls_back_to_default(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)
    settings_path = fake_repo / "registry" / "admin-settings" / "admin-settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"display_name": "Ops", "role": "admin"}), encoding="utf-8")

    assert get_admin_settings(repo_root=fake_repo) == {"display_name": "Internal operator"}


def test_validate_admin_settings_rejects_non_object(tmp_path):
    fake_repo = _build_fake_repo(tmp_path)

    result = validate_admin_settings(["not", "an", "object"], repo_root=fake_repo)

    assert result["valid"] is False
    assert any(error["code"] == "ADMIN_SETTINGS_NOT_AN_OBJECT" for error in result["errors"])
