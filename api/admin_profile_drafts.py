"""
Private/admin service module for dataset public profile drafts (M34-04).

Wraps registry/dataset_public_profile_store.py's create_draft/get_draft/
update_draft for the private/admin HTTP surface in api/main.py. This module
has no public caller; the routes that use it are gated by api/main.py's
existing ADMIN_API_TOKEN convention.

On read, a missing or invalid draft is reported as a deterministic absence
signal (draft_exists: false, profile: None) -- never a synthesized fallback
profile, and never HTTP 404, which api/main.py reserves for admin-auth
denial. On update, when no draft exists yet for the dataset_slug, this
module transparently creates one instead of surfacing the persistence
module's create/update distinction to the admin caller.

Both functions propagate ValueError from the persistence module's
dataset_slug validation unchanged; the calling route is responsible for
translating it into a sanitized HTTP response.
"""

from registry.dataset_public_profile_store import (
    ProfileDraftNotFoundError,
    create_draft,
    get_draft,
    update_draft,
)

_UPDATE_NOT_FOUND_FOR_UPDATE_CODE = "PROFILE_DRAFT_NOT_FOUND_FOR_UPDATE"


def read_profile_draft(dataset_slug: str) -> dict:
    """
    Return {"dataset_slug": str, "draft_exists": bool, "profile": dict|None}.

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern.
    """
    try:
        profile = get_draft(dataset_slug)
    except ProfileDraftNotFoundError:
        return {"dataset_slug": dataset_slug, "draft_exists": False, "profile": None}

    return {"dataset_slug": dataset_slug, "draft_exists": True, "profile": profile}


def save_profile_draft(dataset_slug: str, profile: dict) -> dict:
    """
    Persist a dataset public profile draft, creating it transparently if
    none exists yet for this dataset_slug.

    Returns {"dataset_slug": str, "saved": bool, "profile": dict|None,
    "errors": [...]}, where errors is the persistence module's own
    {code, field, message} list, passed through unmodified. Raises
    ValueError if dataset_slug is missing or does not match the required
    pattern.
    """
    result = update_draft(dataset_slug, profile)

    update_rejected_for_missing_draft = not result["updated"] and any(
        error.get("code") == _UPDATE_NOT_FOUND_FOR_UPDATE_CODE
        for error in result["errors"]
    )
    if update_rejected_for_missing_draft:
        result = create_draft(dataset_slug, profile)
        saved = result["created"]
    else:
        saved = result["updated"]

    return {
        "dataset_slug": dataset_slug,
        "saved": saved,
        "profile": profile if saved else None,
        "errors": result["errors"],
    }
