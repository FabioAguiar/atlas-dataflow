"""
Private/admin service module for Admin Settings (M38-01).

Wraps registry/admin_settings_store.py for the private/admin HTTP surface.
This module exposes only display-name settings and has no public caller; the
routes that use it are gated by api/main.py's ADMIN_API_TOKEN convention.
"""

from registry.admin_settings_store import get_admin_settings, save_admin_settings


def read_admin_settings() -> dict:
    """
    Return {"settings": {"display_name": str}}.

    The store returns a deterministic display-name-only default when no valid
    persisted settings exist.
    """
    return {"settings": get_admin_settings()}


def write_admin_settings(settings: dict) -> dict:
    """
    Persist display-name-only Admin Settings.

    Returns {"saved": bool, "settings": dict|None, "errors": [...]}. Invalid
    objects are rejected by the store and are not persisted.
    """
    result = save_admin_settings(settings)
    return {
        "saved": result["saved"],
        "settings": result["settings"],
        "errors": result["errors"],
    }
