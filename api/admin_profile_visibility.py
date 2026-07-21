"""
Private/admin service module for dataset Visible Publicly publishing (M36-05).

Wraps registry/dataset_public_profile_publication_store.py's set_visibility
for the private/admin HTTP surface in api/main.py. This module has no
public caller; the route that uses it is gated by api/main.py's existing
ADMIN_API_TOKEN convention, mirroring api/admin_profile_publish.py.

Project Spec S0125 adds approve_dataset_review(): the private service
boundary for the explicit, deterministic review-approval lifecycle
(needs_review -> ready). It never publishes a snapshot, writes a visibility
record, or creates a draft -- it only requires an already-current published
snapshot and delegates the actual review_status mutation to
registry.update.approve_dataset_detail_review().
"""

import re
from datetime import datetime
from pathlib import Path

from public_profile_visibility import SNAPSHOT_STATUS_CURRENT_RELEASE, resolve_dataset_visibility
from registry.dataset_public_profile_publication_store import (
    get_visibility_record,
    set_visibility,
)
from registry.dataset_public_profile_snapshot_store import SnapshotNotFoundError, get_snapshot
from registry.list import is_dataset_needs_review
from registry.resolve import resolve_dataset
from registry.update import approve_dataset_detail_review

_RELEASE_PATTERN = re.compile(r"^release-(?:[0-9]{8}-[0-9]{3}|[0-9]{8}t[0-9]{6}z)$")

REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
REVIEW_STATUS_READY = "ready"

# Project Spec S0125: reduced, sanitized error for the private approval
# service boundary -- never exposes storage paths, raw registry errors, or
# which specific snapshot/registry precondition failed.
REVIEW_APPROVAL_BLOCKED_ERROR = {
    "code": "DATASET_REVIEW_APPROVAL_BLOCKED",
    "field": None,
    "message": "The Dataset Detail is not currently eligible for review approval.",
}


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
    review_status = REVIEW_STATUS_NEEDS_REVIEW if needs_review else REVIEW_STATUS_READY
    snapshot = _snapshot_projection(dataset_slug, resolved.active_release, repo_root)
    snapshot_current = snapshot["status"] == SNAPSHOT_STATUS_CURRENT_RELEASE

    # Project Spec S0125: a missing/stale/invalid published snapshot now
    # always blocks public reachability (previously these were only
    # non-blocking observations, back when reachability never considered the
    # snapshot at all) -- so they move from `observations` into `blockers`
    # whenever they apply. `observations` keeps only the non-blocking
    # visibility-source/invalid-record notes that remain applicable.
    blockers = []
    if not effective_visible:
        blockers.append("visibility_disabled")
    if needs_review:
        blockers.append("review_pending")
    if snapshot["status"] == "missing":
        blockers.append("snapshot_missing")
    elif snapshot["status"] == "stale_release":
        blockers.append("snapshot_stale")
    elif snapshot["status"] == "invalid":
        blockers.append("snapshot_invalid")

    observations = []
    if visibility_record["source"] == "default_visible":
        observations.append("visibility_default_applied")
    if visibility_record["record_status"] not in {"valid", "missing"}:
        observations.append("visibility_record_invalid")
    # Project Spec S0117: resolve_dataset_visibility() no longer treats a
    # missing snapshot as an override of an explicit configured-hidden
    # preference, so effective_visible now always agrees with
    # visibility_record["visible"] for a valid record -- the prior
    # "configured_hidden_but_effectively_visible_without_snapshot"
    # discrepancy can no longer occur and has been removed.

    # Project Spec S0125: bounded review-approval projection so the frontend
    # never has to recreate this backend policy. Visibility is deliberately
    # never a factor here -- approval eligibility is independent of the
    # configured "Visible publicly" preference. A dataset already "ready" is
    # never represented as approval-eligible again (no reverse-action
    # invitation); its approval_blockers stay empty since there is nothing
    # actionable to report.
    if needs_review:
        approval_allowed = snapshot_current
        approval_blockers = [] if snapshot_current else [
            code for code in (
                "snapshot_missing" if snapshot["status"] == "missing" else None,
                "snapshot_stale" if snapshot["status"] == "stale_release" else None,
                "snapshot_invalid" if snapshot["status"] == "invalid" else None,
            )
            if code is not None
        ]
    else:
        approval_allowed = False
        approval_blockers = []

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
        "review": {
            "status": review_status,
            "approval_allowed": approval_allowed,
            "approval_blockers": approval_blockers,
        },
        "snapshot": snapshot,
        "public_access": {
            "reachable": effective_visible and not needs_review and snapshot_current,
            "blockers": blockers,
            "observations": observations,
        },
    }


def approve_dataset_review(
    dataset_slug: str,
    repo_root: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """
    Private service boundary for the explicit review-approval lifecycle
    (Project Spec S0125): transitions dataset_slug's review_status from
    needs_review to ready through registry.update.approve_dataset_detail_review(),
    using the resolved active_release as the expected release so a release
    that changes between readiness inspection and mutation is rejected
    rather than silently approved.

    Requires review.status == "needs_review" and a current-release snapshot
    (snapshot.status == "current_release" and matches_active_release is
    True); treats review.status == "ready" with a still-current snapshot as
    idempotent success. Rejects (without any registry mutation) a missing,
    stale, or invalid snapshot, or a release that cannot be resolved --
    approval is always independent of the configured "Visible publicly"
    preference, and never publishes a snapshot, writes a visibility record,
    or creates a draft.

    Returns {"approved": bool, "dataset_slug": str, "changed": bool,
    "review_status": str, "publication_state": dict | None, "errors": [...]}.
    Propagates registry.resolve's DatasetUnavailableError/
    ReleaseUnavailableError/RegistryInvalidError so callers can preserve the
    existing bounded not-found/release-unavailable/registry-unavailable
    semantics; never raises for an approval-readiness conflict, which is
    reported as a non-approved result with a reduced, sanitized error
    instead.
    """
    state = get_dataset_publication_state(dataset_slug, repo_root=repo_root, registry_path=registry_path)

    review_status = state["review"]["status"]
    snapshot_status = state["snapshot"]["status"]
    matches_release = state["snapshot"].get("matches_active_release")
    eligible = snapshot_status == SNAPSHOT_STATUS_CURRENT_RELEASE and matches_release is True

    if not eligible:
        return {
            "approved": False,
            "dataset_slug": dataset_slug,
            "changed": False,
            "review_status": review_status,
            "publication_state": None,
            "errors": [REVIEW_APPROVAL_BLOCKED_ERROR],
        }

    registry_result = approve_dataset_detail_review(
        dataset_slug,
        expected_active_release=state["active_release"],
        repo_root=repo_root,
    )
    if registry_result["errors"]:
        return {
            "approved": False,
            "dataset_slug": dataset_slug,
            "changed": False,
            "review_status": review_status,
            "publication_state": None,
            "errors": [REVIEW_APPROVAL_BLOCKED_ERROR],
        }

    refreshed_state = get_dataset_publication_state(dataset_slug, repo_root=repo_root, registry_path=registry_path)
    return {
        "approved": True,
        "dataset_slug": dataset_slug,
        "changed": registry_result["changed"],
        "review_status": refreshed_state["review"]["status"],
        "publication_state": refreshed_state,
        "errors": [],
    }
