"""
Controlled registry update after release promotion.

Accepts a promotion result path or publisher run directory, gates on
promotion_outcome == "promoted", verifies the promoted release manifest exists,
updates the matching dataset active_release in registry/datasets.json, validates
the updated in-memory registry, backs up the previous registry, and writes the
updated registry.

If no dataset entry exists yet for the promoted dataset_slug (Project Spec
S0036), a new safe public entry is created from the promoted release's
public-context.json rather than raising -- this is what makes a first-time
promotion resolvable at GET /datasets/{slug} without a manual registry edit.

Project Spec S0042 adds an explicit `mode` boundary so a promotion whose
candidate/base dataset_slug collides with an already-registered entry can
either intentionally update that existing entry (the historical default,
`MODE_UPDATE_EXISTING_OR_CREATE`) or deterministically allocate a new,
numbered public slug for a genuinely new Dataset Detail
(`MODE_CREATE_NEW_DATASET_DETAIL`) without ever silently choosing between the
two. `allocate_unique_dataset_slug()` is the reusable allocation boundary:
smallest available `base`, `base1`, `base2`, ... considering only current
registry entries, so removed/absent entries never reserve their old slug.

Does NOT modify promotion-result.json -- api/admin_runs.py orchestrates that
separately, via publisher.promote.finalize_promotion_result_after_registry_update(),
only after this module's run() has returned successfully (Project Spec
S0046). derive_registry_action() below is a pure classification helper
reused by both that finalize step and api/admin_runs.py's own operator-facing
response, so the two never derive "created"/"updated"/"reused" differently
from the same run() outcome.
Does NOT produce a separate promotion-update document.
Does NOT expose any HTTP endpoint. run() and main() are internal CLI only.

Project Spec S0049 adds remove_dataset_entry(): a safe Dataset Detail
removal boundary that deletes only the matching entry from
registry/datasets.json (the same backup/validate/write sequence run() uses),
never touching releases/, publisher/runs/, contracts, notebooks, model
artifacts, profile artifacts, evidence, or support-root files -- those live
entirely outside registry/datasets.json. Once an entry is absent from the
registry, allocate_unique_dataset_slug() naturally offers its slug again to
a future MODE_CREATE_NEW_DATASET_DETAIL promotion, and
api/admin_runs.py's _promotion_summary_from() naturally re-derives
registry_bound: false for any run that was promoted to the removed release
(Project Spec S0048), making that run promotable again without either
module needing to know about the other's removal-specific logic.
"""

import json
import re
import shutil
import sys
from pathlib import Path

from registry.validate import RELEASE_ID_PATTERN, validate_registry


DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

MODE_UPDATE_EXISTING_OR_CREATE = "update_existing_or_create"
MODE_CREATE_NEW_DATASET_DETAIL = "create_new_dataset_detail"
_VALID_MODES = (MODE_UPDATE_EXISTING_OR_CREATE, MODE_CREATE_NEW_DATASET_DETAIL)

# Project Spec S0049: reduced, sanitized errors for remove_dataset_entry(),
# mirroring the {"code", "field", "message"} shape used throughout
# registry/validate.py and api/admin_runs.py's own run-removal errors.
DATASET_SLUG_INVALID_ERROR = {
    "code": "DATASET_SLUG_INVALID",
    "field": "dataset_slug",
    "message": "The dataset_slug is missing or does not match the required pattern.",
}
DATASET_DETAIL_NOT_FOUND_ERROR = {
    "code": "DATASET_DETAIL_NOT_FOUND",
    "field": "dataset_slug",
    "message": "No Dataset Detail was found for the given dataset_slug.",
}
REGISTRY_UNAVAILABLE_ERROR = {
    "code": "REGISTRY_UNAVAILABLE",
    "field": None,
    "message": "The registry could not be read.",
}
REGISTRY_VALIDATION_FAILED_ERROR = {
    "code": "REGISTRY_VALIDATION_FAILED",
    "field": None,
    "message": "The registry could not be validated after removal.",
}
REGISTRY_WRITE_FAILED_ERROR = {
    "code": "REGISTRY_WRITE_FAILED",
    "field": None,
    "message": "The registry could not be written.",
}


def _load_json_file(path: Path, label: str) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"{label} could not be read.") from exc

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object.")

    return data


def _resolve_run_dir(result_path_or_run_dir: str) -> Path:
    input_path = Path(result_path_or_run_dir)
    if input_path.is_file():
        return input_path.parent
    if input_path.is_dir():
        return input_path
    raise ValueError(f"Input path does not exist: {result_path_or_run_dir}")


def _extract_candidate_identity(promotion_result: dict) -> tuple[str, str]:
    candidate_identity = promotion_result.get("candidate_identity")
    if not isinstance(candidate_identity, dict):
        raise RuntimeError("Promotion result is missing 'candidate_identity'.")

    dataset_slug = candidate_identity.get("dataset_slug")
    release_id = candidate_identity.get("release_id")

    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        raise RuntimeError(
            "Promotion result candidate_identity.dataset_slug is missing or invalid."
        )
    if not isinstance(release_id, str) or not RELEASE_ID_PATTERN.match(release_id):
        raise RuntimeError(
            "Promotion result candidate_identity.release_id is missing or invalid."
        )

    return dataset_slug, release_id


def _safe_metadata_string(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _safe_metadata_tags(value: object) -> list:
    if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
        return value
    return []


def _fallback_title(dataset_slug: str) -> str:
    return " ".join(part.capitalize() for part in dataset_slug.split("-") if part)


def _derive_public_metadata(dataset_slug: str, release_dir: Path) -> dict:
    """Derive a schema-safe public_metadata object for a first-time dataset_slug.

    Reads only the already-promoted, immutable
    releases/{release_id}/public-context.json (never the mutable candidate
    directory) so the derived metadata matches what was actually promoted.
    Any missing/unreadable/malformed field falls back to a safe generic
    value instead of raising -- a new registry entry must never block a
    promotion that otherwise satisfied every precondition.
    """
    context = _read_optional_json_object(release_dir / "public-context.json")
    fallback_title = _fallback_title(dataset_slug)

    return {
        "title": _safe_metadata_string(context.get("title"), fallback_title),
        "summary": _safe_metadata_string(
            context.get("description"), f"Published dataset: {fallback_title}."
        ),
        "domain": _safe_metadata_string(context.get("domain"), "general"),
        "visibility": "public",
        "tags": _safe_metadata_tags(context.get("tags")),
    }


def _read_optional_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def allocate_unique_dataset_slug(base_slug: str, registry: dict) -> str:
    """Return the smallest available public dataset_slug for base_slug.

    Considers only the current `registry['datasets']` entries -- a removed or
    absent entry never reserves its previous slug, so gaps are always reused
    deterministically. Returns base_slug unchanged when it is not already
    present; otherwise returns base_slug with the lowest unused numeric
    suffix and no separator (base1, base2, base3, ...).
    """
    datasets = registry.get("datasets")
    existing_slugs = {
        entry.get("dataset_slug")
        for entry in (datasets if isinstance(datasets, list) else [])
        if isinstance(entry, dict)
    }

    if base_slug not in existing_slugs:
        return base_slug

    suffix = 1
    while f"{base_slug}{suffix}" in existing_slugs:
        suffix += 1
    return f"{base_slug}{suffix}"


def derive_registry_action(registry_result: dict) -> str:
    """Classify a successful run() outcome as "created", "updated", or "reused".

    "created" when a new dataset entry was appended (dataset_entry_created
    is True). "reused" when the matched entry already had this exact
    release active before this call (previous_active_release_id ==
    release_id) -- a repeated promotion of the same run/mode is a safe
    no-op. "updated" otherwise: an existing entry's active_release
    genuinely changed to a different release.

    Only meaningful for a run() result where update_applied is True; the
    caller is responsible for not calling this after a failed/raised
    registry update.
    """
    if registry_result.get("dataset_entry_created"):
        return "created"
    if registry_result.get("previous_active_release_id") == registry_result.get("release_id"):
        return "reused"
    return "updated"


def _find_dataset_entry(registry: dict, dataset_slug: str) -> dict | None:
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise RuntimeError("Registry is missing required list field 'datasets'.")
    for entry in datasets:
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            return entry
    return None


def _find_entry_by_active_release(registry: dict, release_id: str) -> dict | None:
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        return None
    for entry in datasets:
        if isinstance(entry, dict) and entry.get("active_release") == release_id:
            return entry
    return None


def _append_dataset_entry(registry: dict, dataset_slug: str, release_dir: Path) -> dict:
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise RuntimeError("Registry is missing required list field 'datasets'.")

    new_entry = {
        "dataset_slug": dataset_slug,
        "active_release": None,
        "public_metadata": _derive_public_metadata(dataset_slug, release_dir),
    }
    datasets.append(new_entry)
    return new_entry


def _find_or_create_dataset_entry(
    registry: dict, dataset_slug: str, release_dir: Path
) -> tuple[dict, bool]:
    """Return (entry, created) for dataset_slug, creating a safe new entry if absent."""
    entry = _find_dataset_entry(registry, dataset_slug)
    if entry is not None:
        return entry, False
    return _append_dataset_entry(registry, dataset_slug, release_dir), True


def _apply_create_new_dataset_detail(
    registry: dict, base_slug: str, release_id: str, release_dir: Path
) -> tuple[dict, bool, str]:
    """Apply MODE_CREATE_NEW_DATASET_DETAIL and return (entry, created, allocated_slug).

    Idempotent for a repeated promotion of the same release: if a registry
    entry already has active_release == release_id (this exact release was
    already registered by a prior call), that entry is reused unchanged
    instead of allocating a new suffix. Otherwise base_slug is allocated via
    allocate_unique_dataset_slug() and a brand-new entry is appended --
    an existing colliding entry's active_release is never touched.
    """
    existing_for_release = _find_entry_by_active_release(registry, release_id)
    if existing_for_release is not None:
        return existing_for_release, False, existing_for_release["dataset_slug"]

    allocated_slug = allocate_unique_dataset_slug(base_slug, registry)
    entry = _append_dataset_entry(registry, allocated_slug, release_dir)
    return entry, True, allocated_slug


def run(
    result_path_or_run_dir: str,
    repo_root: Path | None = None,
    mode: str = MODE_UPDATE_EXISTING_OR_CREATE,
) -> dict:
    """
    Apply the controlled registry active_release update.

    Accepts either a path to promotion-result.json or the containing run
    directory. Returns an informational dict and writes no artifact other than
    registry/datasets.json.previous and registry/datasets.json.

    `mode` must be explicit -- MODE_UPDATE_EXISTING_OR_CREATE (default,
    preserves the historical behavior: a colliding base dataset_slug updates
    that existing entry's active_release) or MODE_CREATE_NEW_DATASET_DETAIL
    (a colliding base dataset_slug never touches the existing entry; instead
    allocate_unique_dataset_slug() allocates the next available numbered
    public slug for a brand-new entry, idempotently for repeated promotions
    of the same release). Any other value raises RuntimeError rather than
    silently choosing between the two behaviors.
    """
    if mode not in _VALID_MODES:
        raise RuntimeError(f"Registry update halted: unknown mode {mode!r}.")

    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    else:
        repo_root = Path(repo_root)

    run_dir = _resolve_run_dir(result_path_or_run_dir)
    promotion_result = _load_json_file(run_dir / "promotion-result.json", "promotion result")

    if promotion_result.get("promotion_outcome") != "promoted":
        raise RuntimeError("Registry update halted: promotion_outcome is not 'promoted'.")

    dataset_slug, release_id = _extract_candidate_identity(promotion_result)

    release_dir = repo_root / "releases" / release_id
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"Registry update halted: releases/{release_id}/manifest.json is absent."
        )

    registry_path = repo_root / "registry" / "datasets.json"
    backup_path = repo_root / "registry" / "datasets.json.previous"

    registry = _load_json_file(registry_path, "registry")

    if mode == MODE_CREATE_NEW_DATASET_DETAIL:
        entry, created, allocated_slug = _apply_create_new_dataset_detail(
            registry, dataset_slug, release_id, release_dir
        )
        previous_active_release_id = entry.get("active_release")
        entry["active_release"] = release_id
    else:
        entry, created = _find_or_create_dataset_entry(registry, dataset_slug, release_dir)
        allocated_slug = dataset_slug
        previous_active_release_id = entry.get("active_release")
        entry["active_release"] = release_id

    validation = validate_registry(registry)
    if validation.get("valid") is not True:
        errors = validation.get("errors") or []
        first_error = errors[0] if errors else {}
        message = first_error.get("message") or "Updated registry is not valid."
        raise RuntimeError(message)

    shutil.copy2(registry_path, backup_path)
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    previous_display = previous_active_release_id if previous_active_release_id else "none"
    print(f"previous_active_release: {previous_display}")
    print(f"new_active_release: {release_id}")
    print(f"dataset_slug: {dataset_slug}")
    print(f"allocated_dataset_slug: {allocated_slug}")

    return {
        "dataset_slug": dataset_slug,
        "allocated_dataset_slug": allocated_slug,
        "release_id": release_id,
        "previous_active_release_id": previous_active_release_id,
        "update_applied": True,
        "backup_path": str(backup_path),
        "dataset_entry_created": created,
    }


def remove_dataset_entry(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """Remove exactly one dataset entry from registry/datasets.json by dataset_slug.

    Removes only the matching entry from the in-memory registry, validates
    the resulting registry with validate_registry() before writing anything,
    backs up the previous registry to registry/datasets.json.previous (the
    same shutil.copy2 backup run() uses) and writes the updated registry.
    Never touches releases/, publisher/runs/, contracts, notebooks, model
    artifacts, profile artifacts, evidence, or support-root files -- this
    function never reads or writes any path other than the registry file and
    its backup.

    Returns {"dataset_slug": str, "removed": bool,
    "previous_active_release": str | None, "errors": [...]}, where errors is
    a list of {"code", "field", "message"} entries. Never raises: an invalid
    dataset_slug, an absent entry, an unreadable registry, a post-removal
    validation failure, or a filesystem write failure are all reported as a
    non-removed result with a reduced, sanitized error instead -- mirroring
    api/admin_runs.py's remove_admin_run() never-raise contract. The registry
    is left byte-for-byte untouched on every non-removed outcome.
    """
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [DATASET_SLUG_INVALID_ERROR],
        }

    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    else:
        repo_root = Path(repo_root)

    registry_path = repo_root / "registry" / "datasets.json"
    backup_path = repo_root / "registry" / "datasets.json.previous"

    try:
        registry = _load_json_file(registry_path, "registry")
    except RuntimeError:
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [REGISTRY_UNAVAILABLE_ERROR],
        }

    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [DATASET_DETAIL_NOT_FOUND_ERROR],
        }

    removed_entry = None
    remaining_entries = []
    for entry in datasets:
        if removed_entry is None and isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            removed_entry = entry
            continue
        remaining_entries.append(entry)

    if removed_entry is None:
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [DATASET_DETAIL_NOT_FOUND_ERROR],
        }

    registry["datasets"] = remaining_entries

    validation = validate_registry(registry)
    if validation.get("valid") is not True:
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [REGISTRY_VALIDATION_FAILED_ERROR],
        }

    try:
        shutil.copy2(registry_path, backup_path)
        registry_path.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        return {
            "dataset_slug": dataset_slug,
            "removed": False,
            "previous_active_release": None,
            "errors": [REGISTRY_WRITE_FAILED_ERROR],
        }

    previous_active_release = removed_entry.get("active_release")

    return {
        "dataset_slug": dataset_slug,
        "removed": True,
        "previous_active_release": previous_active_release if isinstance(previous_active_release, str) else None,
        "errors": [],
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m registry.update <promotion-result-path-or-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        run(sys.argv[1])
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
