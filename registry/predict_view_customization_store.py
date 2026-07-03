"""
Predict view customization file-based persistence for M35-05.

Provides get, create, and update operations for predict-view-customization
records (contracts/predict-view-customization.schema.json), all persisted
together in the single registry/predict-view-customizations.json array that
api/public_predict_view_customization_loader.py already reads, matched by
(view_id, dataset_slug) -- mirroring that loader's own matching logic rather
than introducing a per-view file layout.

Every create_customization and update_customization call validates the
candidate customization via registry.predict_view_customization_validate's
validate_customization(customization, public_contract) before anything is
written. A write that fails validation is never persisted. Consistent with
that validator's own convention, this module does not load the public
contract itself; the caller must load and inject it (see
api/admin_predict_view_customizations.py).

get_customization performs no validation and returns whatever record is
currently stored, so an admin caller can inspect and correct an existing
record that may have become invalid relative to a since-changed contract --
unlike the public read path, which treats an invalid record as absent.

This module never writes to, or reads for writing purposes, releases/ or any
published-snapshot artifact path. It has no HTTP caller; endpoint wiring is
explicit scope for api/admin_predict_view_customizations.py.
"""

import json
import re
import shutil
from pathlib import Path

from registry.predict_view_customization_validate import validate_customization

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_DEFAULT_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-view-customizations.v1",
    "predict_view_customizations": [],
}


class CustomizationNotFoundError(Exception):
    """No customization record exists for the given view_id and dataset_slug."""

    code = "CUSTOMIZATION_NOT_FOUND"


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).parent.parent
    return Path(repo_root)


def _registry_path(repo_root: Path) -> Path:
    return repo_root / "registry" / "predict-view-customizations.json"


def _load_registry(repo_root: Path) -> dict:
    path = _registry_path(repo_root)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return dict(_DEFAULT_REGISTRY, predict_view_customizations=[])

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        return dict(_DEFAULT_REGISTRY, predict_view_customizations=[])

    if not isinstance(registry, dict):
        return dict(_DEFAULT_REGISTRY, predict_view_customizations=[])

    entries = registry.get("predict_view_customizations")
    if not isinstance(entries, list):
        registry = dict(registry, predict_view_customizations=[])

    return registry


def validate_identifiers(view_id: str, dataset_slug: str) -> None:
    """Raise ValueError if view_id or dataset_slug is missing or malformed.

    Exposed (not underscore-prefixed) so callers such as
    api/admin_predict_view_customizations.py can fail fast on malformed
    identifiers before doing any other work, matching this module's own
    validate-before-anything-else discipline.
    """
    if not isinstance(view_id, str) or not _SLUG_PATTERN.match(view_id):
        raise ValueError("view_id is missing or invalid.")
    if not isinstance(dataset_slug, str) or not _SLUG_PATTERN.match(dataset_slug):
        raise ValueError("dataset_slug is missing or invalid.")


def _find_index(entries: list, view_id: str, dataset_slug: str) -> int | None:
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("view_id") == view_id and entry.get("dataset_slug") == dataset_slug:
            return index
    return None


def _write_registry(registry: dict, repo_root: Path) -> None:
    path = _registry_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def get_customization(view_id: str, dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Read the currently stored customization record for (view_id, dataset_slug).

    Raises ValueError if view_id or dataset_slug is missing or does not match
    the required pattern. Raises CustomizationNotFoundError if no matching
    record exists. Performs no validation against a public contract -- the
    caller is responsible for validating the returned record if needed.
    """
    validate_identifiers(view_id, dataset_slug)
    repo_root = _resolve_repo_root(repo_root)
    registry = _load_registry(repo_root)
    entries = registry.get("predict_view_customizations", [])

    index = _find_index(entries, view_id, dataset_slug)
    if index is None:
        raise CustomizationNotFoundError(
            "No customization record exists for this view_id and dataset_slug."
        )

    return entries[index]


def create_customization(
    view_id: str,
    dataset_slug: str,
    customization: dict,
    public_contract: dict,
    repo_root: Path | None = None,
) -> dict:
    """
    Create a new predict-view-customization record.

    Returns {"created": bool, "path": str|None, "errors": [...]}. Raises
    ValueError if view_id or dataset_slug is missing or does not match the
    required pattern. Rejects deterministically (no write) if a record
    already exists for this (view_id, dataset_slug), if customization.view_id
    does not match view_id, if customization.dataset_slug is present and does
    not match dataset_slug, or if the customization fails
    validate_customization(customization, public_contract).
    """
    validate_identifiers(view_id, dataset_slug)
    repo_root = _resolve_repo_root(repo_root)
    registry = _load_registry(repo_root)
    entries = registry.get("predict_view_customizations", [])

    errors: list[dict] = []

    if not isinstance(customization, dict):
        errors.append(_err("CUSTOMIZATION_NOT_AN_OBJECT", None, "Customization must be a JSON object."))
    else:
        if customization.get("view_id") != view_id:
            errors.append(_err(
                "VIEW_ID_MISMATCH",
                "view_id",
                "Customization view_id does not match the requested view_id.",
            ))
        declared_dataset_slug = customization.get("dataset_slug")
        if declared_dataset_slug is not None and declared_dataset_slug != dataset_slug:
            errors.append(_err(
                "DATASET_SLUG_MISMATCH",
                "dataset_slug",
                "Customization dataset_slug does not match the requested dataset_slug.",
            ))

    if _find_index(entries, view_id, dataset_slug) is not None:
        errors.append(_err(
            "CUSTOMIZATION_ALREADY_EXISTS",
            None,
            "A customization record already exists for this view_id and dataset_slug; use update_customization instead.",
        ))

    if isinstance(customization, dict):
        validation = validate_customization(customization, public_contract)
        errors.extend(validation["errors"])

    if errors:
        return {"created": False, "path": None, "errors": errors}

    entries.append(customization)
    registry = dict(registry, predict_view_customizations=entries)
    _write_registry(registry, repo_root)

    return {"created": True, "path": str(_registry_path(repo_root).relative_to(repo_root)), "errors": []}


def update_customization(
    view_id: str,
    dataset_slug: str,
    customization: dict,
    public_contract: dict,
    repo_root: Path | None = None,
) -> dict:
    """
    Replace an existing predict-view-customization record in full.

    Returns {"updated": bool, "path": str|None, "errors": [...]}. Raises
    ValueError if view_id or dataset_slug is missing or does not match the
    required pattern. Rejects deterministically (no write) if no record
    currently exists for this (view_id, dataset_slug), if
    customization.view_id does not match view_id, if customization.dataset_slug
    is present and does not match dataset_slug, or if the customization fails
    validate_customization(customization, public_contract). This is a
    full-object replace; there is no partial/merge update.

    On success, the previous registry file content is backed up to
    registry/predict-view-customizations.json.previous before the new content
    is written, mirroring registry/dataset_public_profile_store.py's
    backup-before-write convention.
    """
    validate_identifiers(view_id, dataset_slug)
    repo_root = _resolve_repo_root(repo_root)
    registry = _load_registry(repo_root)
    entries = registry.get("predict_view_customizations", [])

    errors: list[dict] = []

    existing_index = _find_index(entries, view_id, dataset_slug)
    if existing_index is None:
        errors.append(_err(
            "CUSTOMIZATION_NOT_FOUND_FOR_UPDATE",
            None,
            "No existing customization record to update for this view_id and dataset_slug; use create_customization instead.",
        ))

    if not isinstance(customization, dict):
        errors.append(_err("CUSTOMIZATION_NOT_AN_OBJECT", None, "Customization must be a JSON object."))
    else:
        if customization.get("view_id") != view_id:
            errors.append(_err(
                "VIEW_ID_MISMATCH",
                "view_id",
                "Customization view_id does not match the requested view_id.",
            ))
        declared_dataset_slug = customization.get("dataset_slug")
        if declared_dataset_slug is not None and declared_dataset_slug != dataset_slug:
            errors.append(_err(
                "DATASET_SLUG_MISMATCH",
                "dataset_slug",
                "Customization dataset_slug does not match the requested dataset_slug.",
            ))

    if isinstance(customization, dict):
        validation = validate_customization(customization, public_contract)
        errors.extend(validation["errors"])

    if errors:
        return {"updated": False, "path": None, "errors": errors}

    registry_path = _registry_path(repo_root)
    if registry_path.is_file():
        backup_path = registry_path.parent / f"{registry_path.name}.previous"
        shutil.copy2(registry_path, backup_path)

    entries[existing_index] = customization
    registry = dict(registry, predict_view_customizations=entries)
    _write_registry(registry, repo_root)

    return {"updated": True, "path": str(registry_path.relative_to(repo_root)), "errors": []}
