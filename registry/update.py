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

Project Spec S0051 adds rename_dataset_slug(); S0088 extends it into a safe
all-or-nothing rebinding boundary for the matching dataset registry entry,
slug-keyed profile artifacts, predict views, and predict-view customizations.
It preserves active_release and metadata and never touches media, releases/,
publisher/runs/, contracts, notebooks, model artifacts, or support-root files.
Invalid/colliding slugs and existing target artifacts are rejected before any
write, while write failures trigger best-effort restoration of every involved
file.
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from registry.predict_view_validate import validate_predict_views
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

# Project Spec S0051: reduced, sanitized errors for rename_dataset_slug().
NEW_DATASET_SLUG_INVALID_ERROR = {
    "code": "NEW_DATASET_SLUG_INVALID",
    "field": "new_dataset_slug",
    "message": "The new_dataset_slug is missing or does not match the required pattern.",
}
DATASET_SLUG_UNCHANGED_ERROR = {
    "code": "DATASET_SLUG_UNCHANGED",
    "field": "new_dataset_slug",
    "message": "The new_dataset_slug must differ from the current dataset_slug.",
}
DATASET_SLUG_ALREADY_EXISTS_ERROR = {
    "code": "DATASET_SLUG_ALREADY_EXISTS",
    "field": "new_dataset_slug",
    "message": "Another Dataset Detail already uses this dataset_slug.",
}
ARTIFACT_TARGET_ALREADY_EXISTS_ERROR = {
    "code": "DATASET_SLUG_ARTIFACT_TARGET_EXISTS",
    "field": "new_dataset_slug",
    "message": "Stored state already exists for the new_dataset_slug.",
}
ARTIFACT_REBIND_FAILED_ERROR = {
    "code": "DATASET_SLUG_ARTIFACT_REBIND_FAILED",
    "field": None,
    "message": "Stored Dataset Detail state could not be rebound safely.",
}

_SLUG_KEYED_ARTIFACTS = (
    ("profile-drafts", ".json"),
    ("profile-drafts", ".json.previous"),
    ("profile-snapshots", ".json"),
    ("profile-snapshots", ".json.previous"),
    ("profile-snapshots", ".evidence.json"),
    ("profile-publications", ".json"),
)


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


def _rewrite_dataset_slug_fields(value: object, old_slug: str, new_slug: str) -> object:
    """Return a deep copy with explicit dataset_slug bindings rebound."""
    if isinstance(value, dict):
        rewritten = {}
        for key, item in value.items():
            if key == "dataset_slug" and item == old_slug:
                rewritten[key] = new_slug
            else:
                rewritten[key] = _rewrite_dataset_slug_fields(item, old_slug, new_slug)
        # Snapshot evidence contains two reduced references derived from the slug.
        identifier = rewritten.get("snapshot_identifier")
        if isinstance(identifier, str) and identifier.startswith(f"{old_slug}@"):
            rewritten["snapshot_identifier"] = f"{new_slug}@{identifier.split('@', 1)[1]}"
        source = rewritten.get("draft_source_reference")
        if isinstance(source, dict) and source.get("path") == f"registry/profile-drafts/{old_slug}.json":
            source["path"] = f"registry/profile-drafts/{new_slug}.json"
        return rewritten
    if isinstance(value, list):
        return [_rewrite_dataset_slug_fields(item, old_slug, new_slug) for item in value]
    return value


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8")


def _restore_files(originals: dict[Path, bytes | None]) -> None:
    """Best-effort rollback of every file participating in a rename."""
    for path, content in originals.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        except OSError:
            pass


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

    # Project Spec S0052: a brand-new Dataset Detail created through Admin
    # run promotion defaults to draft/needs_review rather than being treated
    # as published -- review_status lives as a top-level entry field (never
    # inside public_metadata, which registry/validate.py's
    # UNSAFE_METADATA_FIELDS check rejects extra keys on) and is read by
    # registry/list.py's is_dataset_needs_review()/list_admin_datasets(). An
    # entry that already exists (the update path in run(), not this
    # creation path) never has its review_status touched here.
    new_entry = {
        "dataset_slug": dataset_slug,
        "active_release": None,
        "public_metadata": _derive_public_metadata(dataset_slug, release_dir),
        "review_status": "needs_review",
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


def rename_dataset_slug(
    dataset_slug: str,
    new_dataset_slug: str,
    repo_root: Path | None = None,
    updated_at: str | None = None,
) -> dict:
    """Rename exactly one dataset entry's dataset_slug in registry/datasets.json.

    Changes the matching entry's dataset_slug and rebinds optional slug-keyed
    profile artifacts plus explicit predict-view/customization references.
    Active release, public metadata, media references, and unrelated entries
    are preserved. Releases, publisher runs, contracts, notebooks, model
    artifacts, and support-root files are never read or written.

    Returns {"dataset_slug": str, "new_dataset_slug": str, "renamed": bool,
    "errors": [...]}, where errors is a list of {"code", "field", "message"}
    entries. Never raises: an invalid source or target slug format, a target
    slug that duplicates another entry, a no-op (unchanged) rename, an
    absent source entry, an unreadable registry, a post-rename validation
    failure, or a filesystem write failure are all reported as a
    non-renamed result with a reduced, sanitized error instead. The
    registry is left byte-for-byte untouched on every non-renamed outcome.
    """
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [DATASET_SLUG_INVALID_ERROR],
        }

    if not isinstance(new_dataset_slug, str) or not DATASET_SLUG_PATTERN.match(new_dataset_slug):
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [NEW_DATASET_SLUG_INVALID_ERROR],
        }

    if new_dataset_slug == dataset_slug:
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [DATASET_SLUG_UNCHANGED_ERROR],
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
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [REGISTRY_UNAVAILABLE_ERROR],
        }

    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [DATASET_DETAIL_NOT_FOUND_ERROR],
        }

    target_entry = None
    duplicate_exists = False
    for entry in datasets:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("dataset_slug")
        if slug == dataset_slug:
            target_entry = entry
        elif slug == new_dataset_slug:
            duplicate_exists = True

    if target_entry is None:
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [DATASET_DETAIL_NOT_FOUND_ERROR],
        }

    if duplicate_exists:
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [DATASET_SLUG_ALREADY_EXISTS_ERROR],
        }

    mutation_timestamp = updated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    target_entry["dataset_slug"] = new_dataset_slug
    target_entry["dataset_detail_updated_at"] = mutation_timestamp

    validation = validate_registry(registry)
    if validation.get("valid") is not True:
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [REGISTRY_VALIDATION_FAILED_ERROR],
        }

    # Discover and fully parse every optional artifact before the first write.
    # Slugs have already passed the strict pattern above, so these paths cannot
    # escape their fixed registry directories.
    artifact_moves: list[tuple[Path, Path, dict]] = []
    try:
        for directory, suffix in _SLUG_KEYED_ARTIFACTS:
            source = repo_root / "registry" / directory / f"{dataset_slug}{suffix}"
            target = repo_root / "registry" / directory / f"{new_dataset_slug}{suffix}"
            if target.exists():
                return {
                    "dataset_slug": dataset_slug,
                    "new_dataset_slug": new_dataset_slug,
                    "renamed": False,
                    "errors": [ARTIFACT_TARGET_ALREADY_EXISTS_ERROR],
                }
            if source.exists():
                artifact = _load_json_file(source, "stored Dataset Detail state")
                artifact_moves.append(
                    (source, target, _rewrite_dataset_slug_fields(artifact, dataset_slug, new_dataset_slug))
                )

        predict_updates: list[tuple[Path, dict]] = []
        predict_views_path = repo_root / "registry" / "predict-views.json"
        if predict_views_path.exists():
            predict_views = _load_json_file(predict_views_path, "predict views registry")
            rewritten_views = _rewrite_dataset_slug_fields(
                predict_views, dataset_slug, new_dataset_slug
            )
            if rewritten_views != predict_views:
                known_slugs = {
                    entry.get("dataset_slug")
                    for entry in registry.get("datasets", [])
                    if isinstance(entry, dict) and isinstance(entry.get("dataset_slug"), str)
                }
                if validate_predict_views(rewritten_views, known_dataset_slugs=known_slugs)["valid"] is not True:
                    raise RuntimeError("rewritten predict views are invalid")
                predict_updates.append((predict_views_path, rewritten_views))

        customizations_path = repo_root / "registry" / "predict-view-customizations.json"
        if customizations_path.exists():
            customizations = _load_json_file(customizations_path, "predict view customizations registry")
            entries = customizations.get("predict_view_customizations", [])
            if not isinstance(entries, list):
                raise RuntimeError("predict view customizations are invalid")
            old_keys = {
                (entry.get("view_id"), new_dataset_slug)
                for entry in entries
                if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug
            }
            if any(
                isinstance(entry, dict)
                and entry.get("dataset_slug") == new_dataset_slug
                and (entry.get("view_id"), new_dataset_slug) in old_keys
                for entry in entries
            ):
                return {
                    "dataset_slug": dataset_slug,
                    "new_dataset_slug": new_dataset_slug,
                    "renamed": False,
                    "errors": [ARTIFACT_TARGET_ALREADY_EXISTS_ERROR],
                }
            rewritten_customizations = _rewrite_dataset_slug_fields(
                customizations, dataset_slug, new_dataset_slug
            )
            if rewritten_customizations != customizations:
                predict_updates.append((customizations_path, rewritten_customizations))
    except (OSError, RuntimeError, json.JSONDecodeError):
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [ARTIFACT_REBIND_FAILED_ERROR],
        }

    touched_paths = {registry_path, backup_path}
    for source, target, _ in artifact_moves:
        touched_paths.update((source, target))
    touched_paths.update(path for path, _ in predict_updates)
    originals = {path: path.read_bytes() if path.exists() else None for path in touched_paths}

    try:
        backup_path.write_bytes(originals[registry_path] or b"")
        for source, target, artifact in artifact_moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_json_bytes(artifact))
        for path, value in predict_updates:
            path.write_bytes(_json_bytes(value))
        registry_path.write_bytes(_json_bytes(registry))
        for source, _, _ in artifact_moves:
            source.unlink()
    except OSError:
        _restore_files(originals)
        return {
            "dataset_slug": dataset_slug,
            "new_dataset_slug": new_dataset_slug,
            "renamed": False,
            "errors": [ARTIFACT_REBIND_FAILED_ERROR],
        }

    return {
        "dataset_slug": dataset_slug,
        "new_dataset_slug": new_dataset_slug,
        "renamed": True,
        "errors": [],
    }


def update_dataset_detail_timestamp(
    dataset_slug: str, updated_at: str, repo_root: Path | None = None
) -> dict:
    """Persist the canonical Dataset Detail display timestamp safely."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).parent.parent
    registry_path = root / "registry" / "datasets.json"
    backup_path = root / "registry" / "datasets.json.previous"
    try:
        registry = _load_json_file(registry_path, "registry")
    except RuntimeError:
        return {"updated": False, "errors": [REGISTRY_UNAVAILABLE_ERROR]}

    entry = _find_dataset_entry(registry, dataset_slug)
    if entry is None:
        return {"updated": False, "errors": [DATASET_DETAIL_NOT_FOUND_ERROR]}
    entry["dataset_detail_updated_at"] = updated_at
    if validate_registry(registry).get("valid") is not True:
        return {"updated": False, "errors": [REGISTRY_VALIDATION_FAILED_ERROR]}

    try:
        original = registry_path.read_bytes()
        backup_path.write_bytes(original)
        registry_path.write_bytes(_json_bytes(registry))
    except OSError:
        try:
            registry_path.write_bytes(original)
        except (OSError, UnboundLocalError):
            pass
        return {"updated": False, "errors": [REGISTRY_WRITE_FAILED_ERROR]}
    return {"updated": True, "dataset_detail_updated_at": updated_at, "errors": []}


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
