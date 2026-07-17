"""
Private/admin service module for dataset Visible Publicly publishing (M36-05).

Wraps registry/dataset_public_profile_publication_store.py's set_visibility
for the private/admin HTTP surface in api/main.py. This module has no
public caller; the route that uses it is gated by api/main.py's existing
ADMIN_API_TOKEN convention, mirroring api/admin_profile_publish.py.
"""

import re
from datetime import datetime
from pathlib import Path

from public_profile_visibility import resolve_dataset_visibility
from registry.dataset_public_profile_publication_store import (
    get_visibility_record,
    set_visibility,
)
from registry.dataset_public_profile_snapshot_store import SnapshotNotFoundError, get_snapshot
from registry.list import is_dataset_needs_review
from registry.resolve import resolve_dataset

_RELEASE_PATTERN = re.compile(r"^release-(?:[0-9]{8}-[0-9]{3}|[0-9]{8}t[0-9]{6}z)$")


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


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _snapshot_projection(dataset_slug: str, active_release: str, repo_root: Path | None) -> dict:
    missing = {
        "status": "missing",
        "exists": False,
        "published_at": None,
        "active_release_at_publish_time": None,
        "matches_active_release": None,
    }
    try:
        snapshot = get_snapshot(dataset_slug, repo_root=repo_root)
    except SnapshotNotFoundError:
        return missing

    published_at = snapshot.get("published_at") if isinstance(snapshot, dict) else None
    bound_release = (
        snapshot.get("active_release_at_publish_time") if isinstance(snapshot, dict) else None
    )
    valid = (
        isinstance(snapshot, dict)
        and snapshot.get("dataset_slug") == dataset_slug
        and _valid_timestamp(published_at)
        and isinstance(bound_release, str)
        and _RELEASE_PATTERN.fullmatch(bound_release) is not None
    )
    if not valid:
        return {
            "status": "invalid",
            "exists": True,
            "published_at": published_at if _valid_timestamp(published_at) else None,
            "active_release_at_publish_time": (
                bound_release
                if isinstance(bound_release, str) and _RELEASE_PATTERN.fullmatch(bound_release)
                else None
            ),
            "matches_active_release": None,
        }

    matches = bound_release == active_release
    return {
        "status": "current_release" if matches else "stale_release",
        "exists": True,
        "published_at": published_at,
        "active_release_at_publish_time": bound_release,
        "matches_active_release": matches,
    }


def get_dataset_publication_state(
    dataset_slug: str,
    repo_root: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """Project the private, read-only publication and public reachability state."""
    resolved = resolve_dataset(dataset_slug, registry_path=registry_path)
    visibility_record = get_visibility_record(dataset_slug, repo_root=repo_root)
    effective_visible = resolve_dataset_visibility(dataset_slug, repo_root=repo_root)
    needs_review = is_dataset_needs_review(dataset_slug, registry_path=registry_path)
    review_status = "needs_review" if needs_review else "ready"
    snapshot = _snapshot_projection(dataset_slug, resolved.active_release, repo_root)

    blockers = []
    if not effective_visible:
        blockers.append("visibility_disabled")
    if needs_review:
        blockers.append("review_pending")

    observations = []
    if visibility_record["source"] == "default_visible":
        observations.append("visibility_default_applied")
    if visibility_record["record_status"] not in {"valid", "missing"}:
        observations.append("visibility_record_invalid")
    if snapshot["status"] == "missing":
        observations.append("snapshot_missing")
    elif snapshot["status"] == "stale_release":
        observations.append("snapshot_stale")
    elif snapshot["status"] == "invalid":
        observations.append("snapshot_invalid")
    if (
        visibility_record["visible"] is False
        and snapshot["status"] == "missing"
        and effective_visible
    ):
        observations.append("configured_hidden_but_effectively_visible_without_snapshot")

    return {
        "dataset_slug": resolved.dataset_slug,
        "active_release": resolved.active_release,
        "visibility": {
            "configured_visible": visibility_record["visible"],
            "source": visibility_record["source"],
            "record_status": visibility_record["record_status"],
            "updated_at": visibility_record["updated_at"],
            "effective_visible": effective_visible,
        },
        "review": {"status": review_status},
        "snapshot": snapshot,
        "public_access": {
            "reachable": effective_visible and not needs_review,
            "blockers": blockers,
            "observations": observations,
        },
    }
