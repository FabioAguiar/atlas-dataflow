"""
Dataset published profile snapshot persistence for M36-03.

Provides publish_snapshot, publish_snapshot_from_payload, and get_snapshot
for the Publish Changes backend behavior: creating or replacing a single
deterministic published profile snapshot per dataset_slug, persisted at
registry/profile-snapshots/<dataset_slug>.json
(contracts/dataset-public-profile-snapshot.schema.json).

publish_snapshot reads the current private draft profile
(registry/dataset_public_profile_store.py) as its candidate, mirroring the
original M36-03 behavior. publish_snapshot_from_payload (Project Spec
S0061) instead publishes an admin-submitted profile payload directly,
without reading or requiring a persisted draft, for Dataset Admin's normal
Publish Changes flow; the legacy draft-based publish_snapshot remains only
for backward compatibility (e.g. any caller that still wants "publish
whatever the stored draft currently is").

Both entry points funnel into _publish_profile, which validates the
candidate profile against contracts/dataset-public-profile.schema.json
(dataset_public_profile_store.validate_profile_draft) and then against the
active release's data (contracts/dataset-public-profile-snapshot.schema.json
plus registry/dataset_public_profile_validate.py's
validate_profile_references, resolved against the dataset's current
active_release) before writing anything. A candidate that fails validation,
has no resolvable active_release, or (publish_snapshot only) has no draft to
publish, is never persisted -- the previous published snapshot, if any, is
left untouched. This mirrors dataset_public_profile_store.py's
validate-before-write convention and publisher/promote.py's
gate-then-write convention.

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
from datetime import date, datetime, timezone
from pathlib import Path

from registry.dataset_public_profile_snapshot_evidence import write_snapshot_evidence
from registry.dataset_public_profile_store import (
    ProfileDraftNotFoundError,
    get_draft,
    validate_profile_draft,
)
from registry.dataset_public_profile_validate import validate_profile_references
from registry.update import (
    derive_dataset_detail_timestamp_for_date,
    update_dataset_detail_timestamp,
)

DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SNAPSHOT_SCHEMA_VERSION = "1.0.0"

_PROFILE_FIELDS = (
    "display", "home_card", "performance_focus", "theme",
    "inference_presentation", "result_card",
)


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
    draft: dict,
    dataset_slug: str,
    active_release: str,
    published_at: str,
    release_date_label: str,
) -> dict:
    profile = {field: draft[field] for field in _PROFILE_FIELDS if field in draft}
    display = profile.get("display")
    if isinstance(display, dict):
        display = dict(display)
    else:
        display = {}
    # Legacy artifacts remain schema-readable, but new snapshots never carry
    # release_date_mode and never trust an editorial label as date authority.
    display.pop("release_date_mode", None)
    display["release_date_label"] = release_date_label
    profile["display"] = display
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


def _publish_profile(
    dataset_slug: str,
    profile: dict,
    repo_root: Path,
    time_zone: str | None = None,
) -> dict:
    """
    Shared validate-then-write flow for a candidate profile (either the
    persisted draft, via publish_snapshot, or an admin-submitted payload,
    via publish_snapshot_from_payload). Never writes anything on a rejected
    candidate, leaving any previously published snapshot untouched.
    """
    if not isinstance(profile, dict):
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": [_err("PROFILE_NOT_AN_OBJECT", None, "Profile must be a JSON object.")],
        }

    if profile.get("dataset_slug") != dataset_slug:
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": [_err(
                "DATASET_SLUG_MISMATCH",
                "dataset_slug",
                "Profile dataset_slug does not match the requested dataset_slug.",
            )],
        }

    sanitized_profile = dict(profile)
    display = profile.get("display")
    sanitized_display = dict(display) if isinstance(display, dict) else None
    release_date = sanitized_display.get("release_date_label") if sanitized_display is not None else None
    if sanitized_display is not None:
        sanitized_display.pop("release_date_mode", None)
        sanitized_profile["display"] = sanitized_display
    if release_date is not None:
        try:
            if not isinstance(release_date, str) or date.fromisoformat(release_date).isoformat() != release_date:
                raise ValueError
        except ValueError:
            return {
                "published": False,
                "path": None,
                "snapshot": None,
                "errors": [_err(
                    "RELEASE_DATE_INVALID",
                    "display.release_date_label",
                    "Release date must be a valid calendar date in YYYY-MM-DD format.",
                )],
            }

    draft_validation = validate_profile_draft(sanitized_profile, repo_root)
    if not draft_validation["valid"]:
        return {"published": False, "path": None, "snapshot": None, "errors": draft_validation["errors"]}

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
    timestamp_derivation = derive_dataset_detail_timestamp_for_date(
        dataset_slug,
        release_date,
        repo_root=repo_root,
        fallback_now=datetime.fromisoformat(published_at.replace("Z", "+00:00")),
        time_zone=time_zone,
    )
    if not timestamp_derivation["derived"]:
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": timestamp_derivation["errors"],
        }

    candidate = _build_snapshot_candidate(
        sanitized_profile,
        dataset_slug,
        active_release,
        published_at,
        timestamp_derivation["local_calendar_date"],
    )

    errors = _validate_snapshot_candidate(candidate, repo_root)
    if errors:
        return {"published": False, "path": None, "snapshot": None, "errors": errors}

    # S0093: persist the backend-derived canonical timestamp only after all
    # profile/snapshot validation succeeds. The public label above is merely
    # the local calendar projection of this exact value.
    timestamp_result = update_dataset_detail_timestamp(
        dataset_slug,
        timestamp_derivation["dataset_detail_updated_at"],
        repo_root=repo_root,
    )
    if not timestamp_result["updated"]:
        return {
            "published": False,
            "path": None,
            "snapshot": None,
            "errors": [_err(
                "DATASET_DETAIL_TIMESTAMP_UPDATE_FAILED",
                None,
                "The Dataset Detail operational timestamp could not be updated.",
            )],
        }

    path = _snapshot_path(dataset_slug, repo_root)
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

    Retained for backward compatibility with callers that still want to
    publish whatever profile is currently persisted as the draft; Dataset
    Admin's normal Publish Changes flow uses publish_snapshot_from_payload
    instead (Project Spec S0061).

    On a successful publish, also writes a reduced traceability evidence
    file alongside the snapshot (see
    registry.dataset_public_profile_snapshot_evidence.write_snapshot_evidence).
    No evidence file is created or replaced on a rejected publish.
    """
    repo_root = _resolve_repo_root(repo_root)
    _snapshot_path(dataset_slug, repo_root)

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

    return _publish_profile(dataset_slug, draft, repo_root)


def publish_snapshot_from_payload(
    dataset_slug: str,
    profile: dict,
    repo_root: Path | None = None,
    time_zone: str | None = None,
) -> dict:
    """
    Validate an admin-submitted profile payload and publish it directly as
    a deterministic published profile snapshot, without reading or
    requiring a persisted draft (Project Spec S0061). This is the entry
    point Dataset Admin's normal Publish Changes flow uses.

    Returns {"published": bool, "path": str|None, "snapshot": dict|None,
    "errors": [...]}. Raises ValueError if dataset_slug is missing or does
    not match the required pattern. Rejects deterministically (no snapshot
    created or replaced, previous snapshot left untouched) if profile is
    not a JSON object, if profile["dataset_slug"] does not match
    dataset_slug, if profile fails contracts/dataset-public-profile.schema.json
    or reference validation, if no active_release is resolvable for this
    dataset_slug, or if the derived candidate snapshot fails schema/reference
    validation.

    On a successful publish, also writes a reduced traceability evidence
    file alongside the snapshot, exactly like publish_snapshot. No evidence
    file is created or replaced on a rejected publish.
    """
    repo_root = _resolve_repo_root(repo_root)
    _snapshot_path(dataset_slug, repo_root)

    return _publish_profile(dataset_slug, profile, repo_root, time_zone=time_zone)


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
