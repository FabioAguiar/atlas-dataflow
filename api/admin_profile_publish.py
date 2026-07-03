"""
Private/admin service module for dataset public profile publishing (M36-03).

Wraps registry/dataset_public_profile_snapshot_store.py's publish_snapshot
for the private/admin HTTP surface in api/main.py. This module has no
public caller; the route that uses it is gated by api/main.py's existing
ADMIN_API_TOKEN convention, mirroring api/admin_profile_drafts.py.

On failure (no draft to publish, no resolvable active_release, or a
schema/reference validation error), no snapshot is created or replaced;
the persistence module's own {code, field, message} error list is
propagated unchanged to the calling route.
"""

from registry.dataset_public_profile_snapshot_store import publish_snapshot


def publish_profile(dataset_slug: str) -> dict:
    """
    Publish the current private draft profile as a published profile snapshot.

    Returns {"dataset_slug": str, "published": bool, "snapshot": dict|None,
    "errors": [...]}. Raises ValueError if dataset_slug is missing or does
    not match the required pattern.
    """
    result = publish_snapshot(dataset_slug)

    return {
        "dataset_slug": dataset_slug,
        "published": result["published"],
        "snapshot": result["snapshot"],
        "errors": result["errors"],
    }
