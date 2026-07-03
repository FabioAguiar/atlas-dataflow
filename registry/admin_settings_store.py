"""
Private/admin settings file-based persistence for M38-01.

Stores the minimal Admin Settings object at registry/admin-settings/admin-settings.json
under the active repository root. The persisted shape is validated against
contracts/admin-settings.schema.json before every write and contains only the
presentation-oriented display_name setting.

This module does not model accounts, authentication, authorization, ownership,
audit identity, secrets, deployment settings, model settings, or broad profile
behavior.
"""

import json
from pathlib import Path

DEFAULT_ADMIN_SETTINGS = {"display_name": "Internal operator"}


class AdminSettingsNotFoundError(Exception):
    """No valid persisted admin settings file exists."""

    code = "ADMIN_SETTINGS_NOT_FOUND"


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).parent.parent
    return Path(repo_root)


def _settings_root(repo_root: Path) -> Path:
    return repo_root / "registry" / "admin-settings"


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _settings_path(repo_root: Path) -> Path:
    settings_root = _settings_root(repo_root)
    candidate = settings_root / "admin-settings.json"
    if not _is_within_root(candidate, settings_root):
        raise ValueError("admin settings path resolves outside the admin settings directory.")
    return candidate


def _load_schema(repo_root: Path) -> dict:
    schema_path = repo_root / "contracts" / "admin-settings.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_admin_settings(settings: dict, repo_root: Path | None = None) -> dict:
    """
    Validate a candidate Admin Settings object.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    """
    repo_root = _resolve_repo_root(repo_root)
    errors: list[dict] = []

    if not isinstance(settings, dict):
        errors.append(_err("ADMIN_SETTINGS_NOT_AN_OBJECT", None, "Admin settings must be a JSON object."))
        return {"valid": False, "errors": errors}

    try:
        import jsonschema as _jss
    except ImportError:
        _jss = None

    if _jss is None:
        errors.append(_err(
            "SCHEMA_VALIDATOR_UNAVAILABLE",
            None,
            "jsonschema is not installed; schema validation could not run.",
        ))
    else:
        schema = _load_schema(repo_root)
        validator = _jss.Draft7Validator(schema)
        for schema_error in validator.iter_errors(settings):
            field = ".".join(str(part) for part in schema_error.path) or None
            errors.append(_err("SCHEMA_VALIDATION_ERROR", field, schema_error.message))

    return {"valid": len(errors) == 0, "errors": errors}


def get_default_admin_settings() -> dict:
    """Return a fresh copy of the deterministic default settings object."""
    return dict(DEFAULT_ADMIN_SETTINGS)


def read_admin_settings(repo_root: Path | None = None) -> dict:
    """
    Read a valid persisted Admin Settings object.

    Raises AdminSettingsNotFoundError when no valid persisted settings exist.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _settings_path(repo_root)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise AdminSettingsNotFoundError("No admin settings file exists.")

    try:
        settings = json.loads(content)
    except json.JSONDecodeError:
        raise AdminSettingsNotFoundError("Admin settings file is not valid JSON.")

    if not isinstance(settings, dict):
        raise AdminSettingsNotFoundError("Admin settings file is not a JSON object.")

    validation = validate_admin_settings(settings, repo_root)
    if not validation["valid"]:
        raise AdminSettingsNotFoundError("Admin settings file failed validation.")

    return settings


def get_admin_settings(repo_root: Path | None = None) -> dict:
    """
    Return persisted settings when valid, otherwise the deterministic default.

    This never synthesizes account or identity fields; the returned object is
    always display-name-only.
    """
    try:
        return read_admin_settings(repo_root=repo_root)
    except AdminSettingsNotFoundError:
        return get_default_admin_settings()


def save_admin_settings(settings: dict, repo_root: Path | None = None) -> dict:
    """
    Validate and persist the full Admin Settings object.

    Returns {"saved": bool, "path": str|None, "settings": dict|None, "errors": [...]}.
    Invalid settings are rejected without writing.
    """
    repo_root = _resolve_repo_root(repo_root)
    validation = validate_admin_settings(settings, repo_root)
    if not validation["valid"]:
        return {"saved": False, "path": None, "settings": None, "errors": validation["errors"]}

    path = _settings_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "saved": True,
        "path": str(path.relative_to(repo_root)),
        "settings": settings,
        "errors": [],
    }
