"""
Dataset Visible Publicly publication record persistence for M36-05.

Provides get_visibility and set_visibility for a per-dataset_slug
publication record persisted at
registry/profile-publications/<dataset_slug>.json
(contracts/dataset-public-profile-publication.schema.json), decoupled from
the immutable published profile snapshot
(registry/dataset_public_profile_snapshot_store.py). This module never
reads from or writes to registry/profile-snapshots/, never mutates
registry/datasets.json, and never touches the private draft store
(registry/dataset_public_profile_store.py).

A dataset with no publication record yet is treated as visible=true: this
preserves current observable public availability for every dataset that
existed before this issue shipped, until an admin explicitly hides one.

Storage is a single current file per dataset_slug, replaced deterministically
on each write, mirroring registry/dataset_public_profile_snapshot_store.py's
path-safety and dataset_slug validation conventions.

This module has no HTTP caller; endpoint wiring is explicit scope for
api/admin_profile_visibility.py.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

PUBLICATION_SCHEMA_VERSION = "1.0.0"

DEFAULT_VISIBLE = True


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).parent.parent
    return Path(repo_root)


def _publications_root(repo_root: Path) -> Path:
    return repo_root / "registry" / "profile-publications"


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _publication_path(dataset_slug: str, repo_root: Path) -> Path:
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        raise ValueError("dataset_slug is missing or invalid.")

    publications_root = _publications_root(repo_root)
    candidate = publications_root / f"{dataset_slug}.json"

    if not _is_within_root(candidate, publications_root):
        raise ValueError("dataset_slug resolves outside the profile publications directory.")

    return candidate


def get_visibility(dataset_slug: str, repo_root: Path | None = None) -> bool:
    """
    Return whether dataset_slug is currently set Visible Publicly.

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern. Returns DEFAULT_VISIBLE (True) when no publication
    record exists yet, the file is not readable, is not valid JSON, or is
    not a JSON object -- this module never raises for a missing record.
    """
    return get_visibility_record(dataset_slug, repo_root=repo_root)["visible"]


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def get_visibility_record(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """Return bounded publication-record state without writing or raising on bad data."""
    repo_root = _resolve_repo_root(repo_root)
    path = _publication_path(dataset_slug, repo_root)

    fallback = {
        "visible": DEFAULT_VISIBLE,
        "source": "default_visible",
        "record_status": "missing",
        "updated_at": None,
    }

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback
    except OSError:
        return {**fallback, "record_status": "unreadable"}

    try:
        record = json.loads(content)
    except json.JSONDecodeError:
        return {**fallback, "record_status": "invalid_json"}

    if not isinstance(record, dict):
        return {**fallback, "record_status": "invalid_shape"}

    visible = record.get("visible")
    if not isinstance(visible, bool):
        return {**fallback, "record_status": "invalid_visible"}

    updated_at = record.get("updated_at")
    if not _valid_timestamp(updated_at):
        return {**fallback, "record_status": "invalid_updated_at"}

    return {
        "visible": visible,
        "source": "explicit_record",
        "record_status": "valid",
        "updated_at": updated_at,
    }


def set_visibility(dataset_slug: str, visible: bool, repo_root: Path | None = None) -> dict:
    """
    Store or update the Visible Publicly setting for dataset_slug.

    Returns the written record: {"schema_version": str, "dataset_slug": str,
    "visible": bool, "updated_at": str}. Raises ValueError if dataset_slug is
    missing or does not match the required pattern, or if visible is not a
    bool. Does not require an existing published snapshot; the record may be
    set before or after any snapshot is published.
    """
    if not isinstance(visible, bool):
        raise ValueError("visible must be a bool.")

    repo_root = _resolve_repo_root(repo_root)
    path = _publication_path(dataset_slug, repo_root)

    record = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "dataset_slug": dataset_slug,
        "visible": visible,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    return record
