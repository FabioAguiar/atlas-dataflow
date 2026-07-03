"""
Public dataset visibility resolution for M36-05.

Provides the single entry point the public HTTP routes use to determine
whether a dataset_slug's published profile snapshot may currently be
exposed publicly: resolve_dataset_visibility composes
registry/dataset_public_profile_snapshot_store.py's get_snapshot with
registry/dataset_public_profile_publication_store.py's get_visibility.

A dataset with no published snapshot yet (SnapshotNotFoundError) is always
treated as visible: "no snapshot exists yet" is a distinct case from "a
snapshot exists but Visible Publicly is off", and the existing generated
fallback profile behavior for a dataset with no snapshot is unaffected by
this issue.

This module is deliberately separate from api/public_profile_loader.py,
whose load_dataset_profile composes the PRIVATE draft store
(registry/dataset_public_profile_store.py) with the generated fallback for
an unrelated concern (authored draft preview composition); reusing or
redirecting that function here would have broken its own existing
authored_draft/generated_fallback contract (see
tests/api/test_public_profile_fallback.py). This module never imports or
calls registry/dataset_public_profile_store.py.

This module never persists anything; it only reads.
"""

from pathlib import Path

from registry.dataset_public_profile_publication_store import get_visibility
from registry.dataset_public_profile_snapshot_store import (
    SnapshotNotFoundError,
    get_snapshot,
)


def resolve_dataset_visibility(dataset_slug: str, repo_root: Path | None = None) -> bool:
    """
    Return whether dataset_slug is currently publicly visible.

    Returns True when no published snapshot exists yet for dataset_slug
    (SnapshotNotFoundError), regardless of any publication record --
    absence of a snapshot is not the same as being hidden. Otherwise
    returns the publication record's visible value (defaulting to True
    when no publication record exists yet).

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern, propagated from get_snapshot/get_visibility.
    """
    try:
        get_snapshot(dataset_slug, repo_root=repo_root)
    except SnapshotNotFoundError:
        return True

    return get_visibility(dataset_slug, repo_root=repo_root)
