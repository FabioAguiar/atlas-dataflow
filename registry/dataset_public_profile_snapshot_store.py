"""
Dataset published profile snapshot persistence for M36-03.

Provides publish_snapshot and get_snapshot for the Publish Changes backend
behavior: creating or replacing a single deterministic published profile
snapshot per dataset_slug, persisted at
registry/profile-snapshots/<dataset_slug>.json
(contracts/dataset-public-profile-snapshot.schema.json), from the current
private draft profile (registry/dataset_public_profile_store.py).

publish_snapshot validates the current draft against the active release's
data (contracts/dataset-public-profile-snapshot.schema.json plus
registry/dataset_public_profile_validate.py's validate_profile_references,
resolved against the dataset's current active_release) before writing
anything. A candidate that fails validation, has no draft to publish, or
has no resolvable active_release is never persisted. This mirrors
dataset_public_profile_store.py's validate-before-write convention and
publisher/promote.py's gate-then-write convention.

Storage is a single current file per dataset_slug, replaced deterministically
on each publish; the previous snapshot content, if any, is backed up to
registry/profile-snapshots/<dataset_slug>.json.previous before replace,
mirroring update_draft's backup-before-write convention. This module does
not implement multi-version history; database-backed history is out of
scope for this issue.

This module never reads from or writes to releases/ or publisher/'s own
output directories, and never mutates registry/datasets.json. It has no
HTTP caller; endpoint wiring is explicit scope for
api/admin_profile_publish.py.

Every successful publish also writes a reduced, deterministic traceability
evidence file (registry/dataset_public_profile_snapshot_evidence.py) to
registry/profile-snapshots/<dataset_slug>.evidence.json, alongside the
snapshot itself, for M36-04. This is wired here rather than left as a
decoupled step (unlike publisher/evidence.py's own external-caller
invocation) because this module's publish flow is a single synchronous
call with no separate caller to supply the equivalent of a registry-update
result. No evidence file is created or replaced on a rejected publish.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from registry.dataset_public_profile_snapshot_evidence import write_snapshot_evidence
from registry.dataset_public_profile_store import ProfileDraftNotFoundError, get_draft
from registry.dataset_public_profile_validate import validate_profile_references

DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SNAPSHOT_SCHEMA_VERSION = "1.0.0"

_PROFILE_FIELDS = ("display", "home_card", "theme", "inference_presentation", "result_card")


class SnapshotNotFoundError(Exception):
    """No published snapshot exists for the given dataset_slug."""

    code = "PROFILE_SNAPSHOT_NOT_FOUND"


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).parent.parent
    return Path(repo_root)


def _snapshots_root(repo_root: Path) -> Path:
    return repo_root / "registry" / "profile-snapshots"


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _snapshot_path(dataset_slug: str, repo_root: Path) -> Path:
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        raise ValueError("dataset_slug is missing or invalid.")

    snapshots_root = _snapshots_root(repo_root)
    candidate = snapshots_root / f"{dataset_slug}.json"

    if not _is_within_root(candidate, snapshots_root):
        raise ValueError("dataset_slug resolves outside the profile snapshots directory.")

    return candidate


def _load_snapshot_schema(repo_root: Path) -> dict:
    schema_path = repo_root / "contracts" / "dataset-public-profile-snapshot.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _load_predict_views_registry(repo_root: Path) -> dict:
    path = repo_root / "registry" / "predict-views.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"predict_views": []}
    return data if isinstance(data, dict) else {"predict_views": []}


def _resolve_active_release(dataset_slug: str, repo_root: Path) -> str | None:
    datasets_path = repo_root / "registry" / "datasets.json"
    try:
        registry = json.loads(datasets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(registry, dict):
        return None

    for entry in registry.get("datasets", []):
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            active_release = entry.get("active_release")
            return active_release if isinstance(active_release, str) and active_release else None

    return None


def _resolve_visibility(dataset_slug: str, repo_root: Path) -> str | None:
    datasets_path = repo_root / "registry" / "datasets.json"
    try:
        registry = json.loads(datasets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(registry, dict):
        return None

    for entry in registry.get("datasets", []):
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            public_metadata = entry.get("public_metadata")
            if not isinstance(public_metadata, dict):
                return None
            visibility = public_metadata.get("visibility")
            return visibility if isinstance(visibility, str) and visibility else None

    return None


def _load_release_metrics(dataset_slug: str, active_release: str, repo_root: Path) -> dict:
    metrics_path = repo_root / "releases" / active_release / "metrics" / "metrics.json"
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return metrics if isinstance(metrics, dict) else {}


def _build_snapshot_candidate(
    draft: dict, dataset_slug: str, active_release: str, published_at: str
) -> dict:
    profile = {field: draft[field] for field in _PROFILE_FIELDS if field in draft}
    candidate = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "dataset_slug": dataset_slug,
        "published_at": published_at,
        "active_release_at_publish_time": active_release,
        "profile": profile,
    }
    draft_schema_version = draft.get("schema_version")
    if isinstance(draft_schema_version, str) and draft_schema_version:
        candidate["source_draft_schema_version"] = draft_schema_version
    return candidate


def _validate_snapshot_candidate(candidate: dict, repo_root: Path) -> list:
    errors: list[dict] = []

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
        schema = _load_snapshot_schema(repo_root)
        validator = _jss.Draft7Validator(schema)
        for schema_error in validator.iter_errors(candidate):
            field = ".".join(str(part) for part in schema_error.path) or None
            errors.append(_err("SCHEMA_VALIDATION_ERROR", field, schema_error.message))

    dataset_slug = candidate.get("dataset_slug")
    active_release = candidate.get("active_release_at_publish_time")
    repo_root_resolved = _resolve_repo_root(repo_root)
    predict_views_registry = _load_predict_views_registry(repo_root_resolved)
    release_metrics = (
        _load_release_metrics(dataset_slug, active_release, repo_root_resolved)
        if isinstance(dataset_slug, str) and isinstance(active_release, str)
        else {}
    )

    profile = candidate.get("profile")
    reference_check_target = {"dataset_slug": dataset_slug}
    if isinstance(profile, dict):
        reference_check_target.update(profile)
    reference_result = validate_profile_references(
        reference_check_target, predict_views_registry, release_metrics
    )
    errors.extend(reference_result["errors"])

    return errors


def publish_snapshot(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Validate the current draft profile and publish it as a deterministic
    published profile snapshot.

    Returns {"published": bool, "path": str|None, "snapshot": dict|None,
    "errors": [...]}. Raises ValueError if dataset_slug is missing or does
    not match the required pattern. Rejects deterministically (no snapshot
    created or replaced) if no draft currently exists for this dataset_slug,
    if no active_release is resolvable for this dataset_slug, or if the
    candidate snapshot fails schema/reference validation.

    On a successful publish, also writes a reduced traceability evidence
    file alongside the snapshot (see
    registry.dataset_public_profile_snapshot_evidence.write_snapshot_evidence).
    No evidence file is created or replaced on a rejected publish.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _snapshot_path(dataset_slug, repo_root)

    try:
        draft = get_draft(dataset_slug, repo_root=repo_root)
    except ProfileDraftNotFoundError:
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": [_err(
                "NO_DRAFT_TO_PUBLISH",
                None,
                "No draft exists for this dataset_slug; there is nothing to publish.",
            )],
        }

    active_release = _resolve_active_release(dataset_slug, repo_root)
    if active_release is None:
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": [_err(
                "ACTIVE_RELEASE_NOT_FOUND",
                None,
                "No active_release is registered for this dataset_slug.",
            )],
        }

    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = _build_snapshot_candidate(draft, dataset_slug, active_release, published_at)

    errors = _validate_snapshot_candidate(candidate, repo_root)
    if errors:
        return {"published": False, "path": None, "snapshot": None, "errors": errors}

    if path.is_file():
        backup_path = path.parent / f"{path.name}.previous"
        shutil.copy2(path, backup_path)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")

    visibility_value = _resolve_visibility(dataset_slug, repo_root)
    write_snapshot_evidence(candidate, errors, visibility_value, repo_root)

    return {
        "published": True,
        "path": str(path.relative_to(repo_root)),
        "snapshot": candidate,
        "errors": [],
    }


def get_snapshot(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Read the currently published profile snapshot for a dataset_slug.

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern. Raises SnapshotNotFoundError if no snapshot file
    exists, the file is not readable or not valid JSON, or the file is not
    a JSON object. Never synthesizes or returns a fallback snapshot.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _snapshot_path(dataset_slug, repo_root)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise SnapshotNotFoundError("No published snapshot exists for this dataset_slug.")

    try:
        snapshot = json.loads(content)
    except json.JSONDecodeError:
        raise SnapshotNotFoundError("Snapshot file is not valid JSON.")

    if not isinstance(snapshot, dict):
        raise SnapshotNotFoundError("Snapshot file is not a JSON object.")

    return snapshot
