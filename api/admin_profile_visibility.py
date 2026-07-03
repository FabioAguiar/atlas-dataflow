"""
Private/admin service module for dataset Visible Publicly publishing (M36-05).

Wraps registry/dataset_public_profile_publication_store.py's set_visibility
for the private/admin HTTP surface in api/main.py. This module has no
public caller; the route that uses it is gated by api/main.py's existing
ADMIN_API_TOKEN convention, mirroring api/admin_profile_publish.py.
"""

from registry.dataset_public_profile_publication_store import set_visibility


def set_dataset_visibility(dataset_slug: str, visible: bool) -> dict:
    """
    Store or update whether dataset_slug is currently Visible Publicly.

    Returns {"dataset_slug": str, "visible": bool, "updated_at": str}.
    Raises ValueError if dataset_slug is missing or does not match the
    required pattern, or if visible is not a bool.
    """
    record = set_visibility(dataset_slug, visible)

    return {
        "dataset_slug": record["dataset_slug"],
        "visible": record["visible"],
        "updated_at": record["updated_at"],
    }
