"""
Dataset public profile draft file-based persistence for M34-03.

Provides create, read, update, and validate operations for dataset public
profile drafts (contracts/dataset-public-profile.schema.json), each persisted
as its own file at registry/profile-drafts/<dataset_slug>.json. Draft storage
is deterministic and scoped to dataset identity; no draft path is ever built
from an unvalidated caller-supplied string.

Every create_draft and update_draft call validates the candidate profile
against contracts/dataset-public-profile.schema.json (jsonschema.Draft7Validator)
and against registry/dataset_public_profile_validate.py's
validate_profile_references before anything is written. A write that fails
either check is never persisted.

On read, a missing draft file and a draft file that fails schema or reference
validation are both treated as one deterministic absence condition
(ProfileDraftNotFoundError) -- mirroring
api/public_predict_view_customization_loader.py's CustomizationNotFoundError
precedent. This module never assembles or returns a fallback profile from
release/public-artifact data.

This module never writes to, or reads for writing purposes, releases/ or any
published-snapshot artifact path. It has no HTTP caller; endpoint wiring is
explicit scope for a later issue.
"""

import json
import re
import shutil
from pathlib import Path

from registry.dataset_public_profile_validate import validate_profile_references

DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProfileDraftNotFoundError(Exception):
    """No valid persisted draft exists for the given dataset_slug."""

    code = "PROFILE_DRAFT_NOT_FOUND"


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).parent.parent
    return Path(repo_root)


def _drafts_root(repo_root: Path) -> Path:
    return repo_root / "registry" / "profile-drafts"


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _draft_path(dataset_slug: str, repo_root: Path) -> Path:
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        raise ValueError("dataset_slug is missing or invalid.")

    drafts_root = _drafts_root(repo_root)
    candidate = drafts_root / f"{dataset_slug}.json"

    if not _is_within_root(candidate, drafts_root):
        raise ValueError("dataset_slug resolves outside the profile drafts directory.")

    return candidate


def _load_schema(repo_root: Path) -> dict:
    schema_path = repo_root / "contracts" / "dataset-public-profile.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _load_predict_views_registry(repo_root: Path) -> dict:
    path = repo_root / "registry" / "predict-views.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"predict_views": []}
    return data if isinstance(data, dict) else {"predict_views": []}


def _resolve_release_metrics(dataset_slug: str, repo_root: Path) -> dict:
    datasets_path = repo_root / "registry" / "datasets.json"
    try:
        registry = json.loads(datasets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(registry, dict):
        return {}

    active_release = None
    for entry in registry.get("datasets", []):
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            active_release = entry.get("active_release")
            break

    if not isinstance(active_release, str) or not active_release:
        return {}

    metrics_path = repo_root / "releases" / active_release / "metrics" / "metrics.json"
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return metrics if isinstance(metrics, dict) else {}


def validate_profile_draft(profile: dict, repo_root: Path | None = None) -> dict:
    """
    Validate a candidate dataset public profile draft.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    Runs contracts/dataset-public-profile.schema.json schema validation and
    registry/dataset_public_profile_validate.py reference validation, always
    accumulating all errors before returning.
    """
    repo_root = _resolve_repo_root(repo_root)
    errors: list[dict] = []

    if not isinstance(profile, dict):
        errors.append(_err("PROFILE_NOT_AN_OBJECT", None, "Profile must be a JSON object."))
        return {"valid": False, "errors": errors}

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
        schema = _load_schema(repo_root)
        validator = _jss.Draft7Validator(schema)
        for schema_error in validator.iter_errors(profile):
            field = ".".join(str(part) for part in schema_error.path) or None
            errors.append(_err("SCHEMA_VALIDATION_ERROR", field, schema_error.message))

    dataset_slug = profile.get("dataset_slug")
    predict_views_registry = _load_predict_views_registry(repo_root)
    release_metrics = (
        _resolve_release_metrics(dataset_slug, repo_root)
        if isinstance(dataset_slug, str)
        else {}
    )
    reference_result = validate_profile_references(profile, predict_views_registry, release_metrics)
    errors.extend(reference_result["errors"])

    return {"valid": len(errors) == 0, "errors": errors}


def create_draft(dataset_slug: str, profile: dict, repo_root: Path | None = None) -> dict:
    """
    Create a new dataset public profile draft.

    Returns {"created": bool, "path": str|None, "errors": [...]}. Raises
    ValueError if dataset_slug is missing or does not match the required
    pattern. Rejects deterministically (no write) if a draft already exists
    for this dataset_slug, if profile.dataset_slug does not match dataset_slug,
    or if the profile fails validate_profile_draft.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _draft_path(dataset_slug, repo_root)

    errors: list[dict] = []

    if not isinstance(profile, dict):
        errors.append(_err("PROFILE_NOT_AN_OBJECT", None, "Profile must be a JSON object."))
    elif profile.get("dataset_slug") != dataset_slug:
        errors.append(_err(
            "DATASET_SLUG_MISMATCH",
            "dataset_slug",
            "Profile dataset_slug does not match the requested dataset_slug.",
        ))

    if path.is_file():
        errors.append(_err(
            "PROFILE_DRAFT_ALREADY_EXISTS",
            None,
            "A draft already exists for this dataset_slug; use update_draft instead.",
        ))

    if isinstance(profile, dict):
        validation = validate_profile_draft(profile, repo_root)
        errors.extend(validation["errors"])

    if errors:
        return {"created": False, "path": None, "errors": errors}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"created": True, "path": str(path.relative_to(repo_root)), "errors": []}


def update_draft(dataset_slug: str, profile: dict, repo_root: Path | None = None) -> dict:
    """
    Replace an existing dataset public profile draft in full.

    Returns {"updated": bool, "path": str|None, "errors": [...]}. Raises
    ValueError if dataset_slug is missing or does not match the required
    pattern. Rejects deterministically (no write) if no draft currently
    exists for this dataset_slug, if profile.dataset_slug does not match
    dataset_slug, or if the profile fails validate_profile_draft. This is a
    full-object replace; there is no partial/merge update.

    On success, the previous file content is backed up to
    registry/profile-drafts/<dataset_slug>.json.previous before the new
    content is written, mirroring registry/update.py's backup-before-write
    convention.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _draft_path(dataset_slug, repo_root)

    errors: list[dict] = []

    if not path.is_file():
        errors.append(_err(
            "PROFILE_DRAFT_NOT_FOUND_FOR_UPDATE",
            None,
            "No existing draft to update for this dataset_slug; use create_draft instead.",
        ))

    if not isinstance(profile, dict):
        errors.append(_err("PROFILE_NOT_AN_OBJECT", None, "Profile must be a JSON object."))
    elif profile.get("dataset_slug") != dataset_slug:
        errors.append(_err(
            "DATASET_SLUG_MISMATCH",
            "dataset_slug",
            "Profile dataset_slug does not match the requested dataset_slug.",
        ))

    if isinstance(profile, dict):
        validation = validate_profile_draft(profile, repo_root)
        errors.extend(validation["errors"])

    if errors:
        return {"updated": False, "path": None, "errors": errors}

    backup_path = path.parent / f"{path.name}.previous"
    shutil.copy2(path, backup_path)
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"updated": True, "path": str(path.relative_to(repo_root)), "errors": []}


def get_draft(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Read an existing, valid dataset public profile draft.

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern. Raises ProfileDraftNotFoundError if no draft file
    exists, the file is not readable or not valid JSON, the file is not a
    JSON object, or the content fails validate_profile_draft. Never
    synthesizes or returns a fallback profile.
    """
    repo_root = _resolve_repo_root(repo_root)
    path = _draft_path(dataset_slug, repo_root)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise ProfileDraftNotFoundError("No draft exists for this dataset_slug.")

    try:
        profile = json.loads(content)
    except json.JSONDecodeError:
        raise ProfileDraftNotFoundError("Draft file is not valid JSON.")

    if not isinstance(profile, dict):
        raise ProfileDraftNotFoundError("Draft file is not a JSON object.")

    validation = validate_profile_draft(profile, repo_root)
    if not validation["valid"]:
        raise ProfileDraftNotFoundError("Draft file failed validation.")

    return profile
