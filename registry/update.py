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

Project Spec S0098 adds predict-view materialization to this module's own
registry activation transaction, once the final public dataset slug is
known: the promoted release's public-context.json's optional `predict_views`
declaration is read (absent preserves the dataset-owned subset already in
registry/predict-views.json; an explicit empty array removes it; a populated
array replaces it) and, when it changes anything, validated as part of a
complete temporary predict-view registry (validate_predict_views) before
either registry/datasets.json or registry/predict-views.json is written --
both writes share one rollback boundary, so a predict-view validation
failure leaves both files exactly as they were. A best-effort, read-only
classification of this dataset's stored predict-view customizations against
the just-promoted release's public contract (registry/predict_view_
customization_validate.classify_customization_compatibility) is also
returned, without ever rewriting, deleting, or migrating a stored
customization here.
"""

import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from registry.predict_view_customization_validate import classify_customization_compatibility
from registry.predict_view_validate import PREDICT_VIEWS_SCHEMA_VERSION, validate_predict_views
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
DATASET_DETAIL_DATE_INVALID_ERROR = {
    "code": "DATASET_DETAIL_DATE_INVALID",
    "field": "display.release_date_label",
    "message": "Release date must be a valid calendar date in YYYY-MM-DD format.",
}
DATASET_DETAIL_TIMEZONE_INVALID_ERROR = {
    "code": "DATASET_DETAIL_TIMEZONE_INVALID",
    "field": "display.release_date_label",
    "message": "The Dataset Detail date could not be converted safely.",
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

# Project Spec S0125: reduced, sanitized errors for approve_dataset_detail_review().
ACTIVE_RELEASE_MISMATCH_ERROR = {
    "code": "DATASET_ACTIVE_RELEASE_MISMATCH",
    "field": "expected_active_release",
    "message": "The expected active release no longer matches the dataset's current active release.",
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


def _normalize_declared_view(raw_view: object, base_dataset_slug: str, final_dataset_slug: str) -> dict:
    """Return a deep copy of one declared predict view, rebound to final_dataset_slug.

    Rejects (RuntimeError, before any write) a non-object record or a record
    that declares a dataset_slug/binding.dataset_slug other than
    base_dataset_slug -- the promotion's own pre-allocation candidate slug,
    i.e. the identity the declaring dataset-context.json is actually allowed
    to speak for. view_id is never altered here; only dataset_slug and
    binding.dataset_slug are rewritten to final_dataset_slug, so
    MODE_CREATE_NEW_DATASET_DETAIL's numbered slug allocation is reflected
    without ever changing the declared view's stable identity.
    """
    if not isinstance(raw_view, dict):
        raise RuntimeError(
            "Registry update halted: a declared predict view is not an object."
        )

    declared_dataset_slug = raw_view.get("dataset_slug")
    if declared_dataset_slug is not None and declared_dataset_slug != base_dataset_slug:
        raise RuntimeError(
            "Registry update halted: a declared predict view's dataset_slug "
            "does not match the promoted dataset."
        )

    binding = raw_view.get("binding")
    if binding is not None:
        if not isinstance(binding, dict):
            raise RuntimeError(
                "Registry update halted: a declared predict view has an invalid binding."
            )
        declared_binding_slug = binding.get("dataset_slug")
        if declared_binding_slug is not None and declared_binding_slug != base_dataset_slug:
            raise RuntimeError(
                "Registry update halted: a declared predict view binding.dataset_slug "
                "does not match the promoted dataset."
            )

    normalized = json.loads(json.dumps(raw_view))
    normalized["dataset_slug"] = final_dataset_slug
    if isinstance(normalized.get("binding"), dict):
        normalized["binding"]["dataset_slug"] = final_dataset_slug
    return normalized


def _materialize_predict_views(
    repo_root: Path,
    release_dir: Path,
    base_dataset_slug: str,
    final_dataset_slug: str,
    known_dataset_slugs: set,
) -> dict:
    """Resolve this promotion's predict-view materialization in-memory only.

    Reads the promoted release's immutable public-context.json and the
    current registry/predict-views.json, distinguishes absent/empty/populated
    `predict_views`, normalizes and validates a complete temporary merged
    registry (this dataset's declared subset plus every other dataset's
    entries preserved verbatim) with validate_predict_views(), and returns a
    plan -- it never writes anything itself. Raises RuntimeError on any
    malformed declaration, invalid binding, dataset mismatch, duplicate
    view_id, or post-merge validation failure; callers must treat that as a
    full-transaction abort (no write of any kind).

    Returns {"declared_mode": "absent"|"empty"|"populated",
    "action": "not_declared"|"preserved"|"created"|"updated"|"removed",
    "rewrite_needed": bool, "final_registry": dict|None,
    "view_ids_after": set[str]} -- final_registry is populated only when
    rewrite_needed is True, and view_ids_after is always this dataset's
    resulting owned view_id set (unchanged from the current registry when
    declared_mode is "absent").
    """
    public_context = _read_optional_json_object(release_dir / "public-context.json")

    predict_views_path = repo_root / "registry" / "predict-views.json"
    # Tolerant, like the release's own public-context.json read above: a
    # missing/unreadable/malformed registry/predict-views.json is treated as
    # an empty predict-view registry rather than aborting the promotion --
    # this file is expected to always exist in the real repository, but a
    # fixture/test repo_root that has not created it yet must not be forced
    # to just to promote a release with no predict-view concerns at all.
    existing_registry = _read_optional_json_object(predict_views_path)
    existing_views = existing_registry.get("predict_views")
    if not isinstance(existing_views, list):
        existing_views = []

    current_dataset_views = [
        view for view in existing_views
        if isinstance(view, dict) and view.get("dataset_slug") == final_dataset_slug
    ]

    if "predict_views" not in public_context:
        return {
            "declared_mode": "absent",
            "action": "not_declared",
            "rewrite_needed": False,
            "final_registry": None,
            "view_ids_after": {
                view.get("view_id") for view in current_dataset_views if isinstance(view.get("view_id"), str)
            },
        }

    raw_declared = public_context.get("predict_views")
    if not isinstance(raw_declared, list):
        raise RuntimeError(
            "Registry update halted: predict_views must be an array when present."
        )

    declared_mode = "empty" if not raw_declared else "populated"
    normalized_declared = (
        []
        if declared_mode == "empty"
        else [_normalize_declared_view(raw_view, base_dataset_slug, final_dataset_slug) for raw_view in raw_declared]
    )

    other_dataset_views = [
        view for view in existing_views
        if not (isinstance(view, dict) and view.get("dataset_slug") == final_dataset_slug)
    ]
    first_target_index = next(
        (
            i for i, view in enumerate(existing_views)
            if isinstance(view, dict) and view.get("dataset_slug") == final_dataset_slug
        ),
        None,
    )
    if first_target_index is None:
        final_views = other_dataset_views + normalized_declared
    else:
        insert_at = sum(
            1 for view in existing_views[:first_target_index]
            if not (isinstance(view, dict) and view.get("dataset_slug") == final_dataset_slug)
        )
        final_views = other_dataset_views[:insert_at] + normalized_declared + other_dataset_views[insert_at:]

    final_registry = {
        "schema_version": existing_registry.get("schema_version", PREDICT_VIEWS_SCHEMA_VERSION),
        "predict_views": final_views,
    }

    validation = validate_predict_views(final_registry, known_dataset_slugs=known_dataset_slugs)
    if validation.get("valid") is not True:
        errors = validation.get("errors") or []
        first_error = errors[0] if errors else {}
        message = first_error.get("message") or "Materialized predict views registry is not valid."
        raise RuntimeError(message)

    rewrite_needed = final_views != existing_views
    current_ids = {view.get("view_id") for view in current_dataset_views if isinstance(view.get("view_id"), str)}
    new_ids = {view.get("view_id") for view in normalized_declared if isinstance(view.get("view_id"), str)}

    if not rewrite_needed:
        action = "preserved"
    elif not new_ids and current_ids:
        action = "removed"
    elif new_ids and not current_ids:
        action = "created"
    else:
        action = "updated"

    return {
        "declared_mode": declared_mode,
        "action": action,
        "rewrite_needed": rewrite_needed,
        "final_registry": final_registry if rewrite_needed else None,
        "view_ids_after": new_ids,
    }


def _load_public_contract_for_classification(release_id: str, repo_root: Path):
    """Best-effort load of the just-promoted release's public contract.

    Returns None if the api layer or the contract itself is unavailable --
    a matching customization is then classified "incompatible" rather than
    raising, since compatibility can never be confirmed without it. This is
    the only place registry/update.py reaches into the api/ layer, and only
    ever with an already-known release_id it just promoted; it never
    resolves a dataset_slug to a release itself.
    """
    api_root = str(repo_root / "api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    try:
        from public_contract_loader import PublicContractUnavailableError, load_public_contract
    except ImportError:
        return None
    try:
        return load_public_contract(release_id, releases_root=repo_root / "releases")
    except PublicContractUnavailableError:
        return None


def _classify_dataset_customizations(
    repo_root: Path,
    dataset_slug: str,
    materialized_view_ids: set,
    release_id: str,
) -> list:
    """Reduced, read-only classification of dataset_slug's stored predict-view
    customizations against the just-promoted release's active public
    contract (Project Spec S0098). Never mutates
    registry/predict-view-customizations.json.

    Returns a list of {"view_id": str, "status": "absent"|"compatible"|
    "incompatible"|"unmaterialized"} entries: "absent" is a materialized
    view with no stored customization; "unmaterialized" is a stored
    customization whose view_id is not in materialized_view_ids -- excluded
    from automatic binding decisions, never deleted, rewritten, or migrated
    here.
    """
    customizations_data = _read_optional_json_object(
        repo_root / "registry" / "predict-view-customizations.json"
    )
    customizations = customizations_data.get("predict_view_customizations")
    if not isinstance(customizations, list):
        customizations = []

    dataset_customizations = [
        c for c in customizations if isinstance(c, dict) and c.get("dataset_slug") == dataset_slug
    ]

    public_contract = None
    contract_loaded = False
    report: list[dict] = []

    for view_id in sorted(vid for vid in materialized_view_ids if isinstance(vid, str)):
        matching = next((c for c in dataset_customizations if c.get("view_id") == view_id), None)
        if matching is None:
            report.append({"view_id": view_id, "status": "absent"})
            continue
        if not contract_loaded:
            public_contract = _load_public_contract_for_classification(release_id, repo_root)
            contract_loaded = True
        classification = classify_customization_compatibility(
            view_id, dataset_slug, matching, public_contract
        )
        report.append({"view_id": view_id, "status": classification["status"]})

    for customization in dataset_customizations:
        view_id = customization.get("view_id") if isinstance(customization, dict) else None
        if isinstance(view_id, str) and view_id not in materialized_view_ids:
            report.append({"view_id": view_id, "status": "unmaterialized"})

    return report


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

    # Project Spec S0098: resolve predict-view materialization in-memory and
    # validate it as a complete temporary registry before anything is
    # written. A failure here (malformed declaration, invalid binding,
    # dataset mismatch, duplicate view_id, or post-merge validation failure)
    # raises and leaves both registry/datasets.json and
    # registry/predict-views.json byte-for-byte untouched, since neither has
    # been written yet at this point.
    known_dataset_slugs = {
        e.get("dataset_slug")
        for e in registry.get("datasets", [])
        if isinstance(e, dict) and isinstance(e.get("dataset_slug"), str)
    }
    materialization = _materialize_predict_views(
        repo_root=repo_root,
        release_dir=release_dir,
        base_dataset_slug=dataset_slug,
        final_dataset_slug=allocated_slug,
        known_dataset_slugs=known_dataset_slugs,
    )
    customization_classification = _classify_dataset_customizations(
        repo_root=repo_root,
        dataset_slug=allocated_slug,
        materialized_view_ids=materialization["view_ids_after"],
        release_id=release_id,
    )

    predict_views_path = repo_root / "registry" / "predict-views.json"
    predict_views_backup_path = repo_root / "registry" / "predict-views.json.previous"
    predict_views_rewrite = materialization["rewrite_needed"]
    predict_views_existed = predict_views_path.is_file()

    originals: dict[Path, bytes | None] = {registry_path: registry_path.read_bytes()}
    if predict_views_rewrite:
        originals[predict_views_path] = predict_views_path.read_bytes() if predict_views_existed else None

    try:
        shutil.copy2(registry_path, backup_path)
        registry_path.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if predict_views_rewrite:
            if predict_views_existed:
                shutil.copy2(predict_views_path, predict_views_backup_path)
            predict_views_path.write_text(
                json.dumps(materialization["final_registry"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except OSError:
        for path, original in originals.items():
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
            except OSError:
                pass
        raise RuntimeError("Registry update halted: the registry could not be written.")

    previous_display = previous_active_release_id if previous_active_release_id else "none"
    print(f"previous_active_release: {previous_display}")
    print(f"new_active_release: {release_id}")
    print(f"dataset_slug: {dataset_slug}")
    print(f"allocated_dataset_slug: {allocated_slug}")
    print(f"predict_view_materialization_action: {materialization['action']}")

    return {
        "dataset_slug": dataset_slug,
        "allocated_dataset_slug": allocated_slug,
        "release_id": release_id,
        "previous_active_release_id": previous_active_release_id,
        "update_applied": True,
        "backup_path": str(backup_path),
        "dataset_entry_created": created,
        "predict_view_materialization": {
            "declared_mode": materialization["declared_mode"],
            "action": materialization["action"],
        },
        "predict_view_customization_classification": customization_classification,
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


_REVIEW_STATUS_READY = "ready"
_REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
_VALID_REVIEW_STATUSES = {_REVIEW_STATUS_READY, _REVIEW_STATUS_NEEDS_REVIEW}


def _current_review_status(entry: dict) -> str:
    value = entry.get("review_status")
    return value if value in _VALID_REVIEW_STATUSES else _REVIEW_STATUS_READY


def approve_dataset_detail_review(
    dataset_slug: str,
    expected_active_release: str,
    repo_root: Path | None = None,
) -> dict:
    """Transition exactly one registered Dataset Detail's review_status to "ready".

    Project Spec S0125. This is the sole controlled path that may ever set
    review_status = "ready": no reverse transition (ready -> needs_review) is
    supported here or anywhere else. Only the matching entry's top-level
    review_status is changed -- dataset_slug, active_release,
    public_metadata, and dataset_detail_updated_at (the S0089/S0092 display-
    date authority) are left untouched. Never touches public_metadata,
    active_release, predict-views.json, predict-view-customizations.json,
    profile-drafts/**, profile-snapshots/**, profile-publications/**,
    releases/**, or publisher/runs/**.

    expected_active_release must equal the matching entry's current
    active_release at mutation time (re-read fresh from disk here, not
    trusted from an earlier caller-side read) -- this rejects an approval
    whose readiness was inspected against a release that has since changed,
    without ever mutating the registry. A registry entry already in
    review_status "ready" whose active_release still matches is treated as
    an idempotent success and the file is not rewritten.

    Returns {"dataset_slug": str, "review_status": str, "changed": bool,
    "errors": [...]}, where errors is a list of {"code", "field", "message"}
    entries. Never raises: an invalid dataset_slug, an absent entry, an
    active-release mismatch, an unreadable registry, a post-mutation
    validation failure, or a filesystem write failure are all reported as a
    non-changed result with a reduced, sanitized error instead. The registry
    is left byte-for-byte untouched on every non-changed outcome.
    """
    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        return {
            "dataset_slug": dataset_slug,
            "review_status": None,
            "changed": False,
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
            "review_status": None,
            "changed": False,
            "errors": [REGISTRY_UNAVAILABLE_ERROR],
        }

    entry = _find_dataset_entry(registry, dataset_slug)
    if entry is None:
        return {
            "dataset_slug": dataset_slug,
            "review_status": None,
            "changed": False,
            "errors": [DATASET_DETAIL_NOT_FOUND_ERROR],
        }

    if entry.get("active_release") != expected_active_release:
        return {
            "dataset_slug": dataset_slug,
            "review_status": _current_review_status(entry),
            "changed": False,
            "errors": [ACTIVE_RELEASE_MISMATCH_ERROR],
        }

    current_status = _current_review_status(entry)
    if current_status == _REVIEW_STATUS_READY:
        return {
            "dataset_slug": dataset_slug,
            "review_status": _REVIEW_STATUS_READY,
            "changed": False,
            "errors": [],
        }

    entry["review_status"] = _REVIEW_STATUS_READY

    validation = validate_registry(registry)
    if validation.get("valid") is not True:
        return {
            "dataset_slug": dataset_slug,
            "review_status": current_status,
            "changed": False,
            "errors": [REGISTRY_VALIDATION_FAILED_ERROR],
        }

    try:
        original = registry_path.read_bytes()
        backup_path.write_bytes(original)
        registry_path.write_bytes(_json_bytes(registry))
    except OSError:
        try:
            registry_path.write_bytes(original)
        except (OSError, UnboundLocalError):
            pass
        return {
            "dataset_slug": dataset_slug,
            "review_status": current_status,
            "changed": False,
            "errors": [REGISTRY_WRITE_FAILED_ERROR],
        }

    return {
        "dataset_slug": dataset_slug,
        "review_status": _REVIEW_STATUS_READY,
        "changed": True,
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
    validation_before = validate_registry(registry)
    entry["dataset_detail_updated_at"] = updated_at
    validation_after = validate_registry(registry)
    # Some legacy/private fixture registries contain pre-existing validation
    # findings unrelated to this field. A valid timestamp-only mutation must
    # not be blocked by those findings, but it must never introduce a new one.
    errors_before = {
        json.dumps(error, sort_keys=True)
        for error in validation_before.get("errors", [])
        if isinstance(error, dict)
    }
    errors_after = {
        json.dumps(error, sort_keys=True)
        for error in validation_after.get("errors", [])
        if isinstance(error, dict)
    }
    if errors_after - errors_before:
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


def derive_dataset_detail_timestamp_for_date(
    dataset_slug: str,
    selected_date: str | None,
    repo_root: Path | None = None,
    fallback_now: datetime | None = None,
    time_zone: str | None = None,
) -> dict:
    """Derive one canonical UTC timestamp after replacing its local date.

    The registry value supplies the time-of-day. For legacy entries without a
    canonical timestamp, backend current time is the single fallback. The
    timezone is controlled by ATLAS_DATASET_TIME_ZONE/TZ (UTC by default),
    while tests and callers may pass an explicit IANA name.
    """
    root = Path(repo_root) if repo_root is not None else Path(__file__).parent.parent
    try:
        registry = _load_json_file(root / "registry" / "datasets.json", "registry")
    except RuntimeError:
        return {"derived": False, "errors": [REGISTRY_UNAVAILABLE_ERROR]}

    entry = _find_dataset_entry(registry, dataset_slug)
    if entry is None:
        return {"derived": False, "errors": [DATASET_DETAIL_NOT_FOUND_ERROR]}

    if selected_date is not None:
        try:
            parsed_date = date.fromisoformat(selected_date)
            if parsed_date.isoformat() != selected_date:
                raise ValueError
        except (TypeError, ValueError):
            return {"derived": False, "errors": [DATASET_DETAIL_DATE_INVALID_ERROR]}
    else:
        parsed_date = None

    zone_name = time_zone or os.environ.get("ATLAS_DATASET_TIME_ZONE") or os.environ.get("TZ") or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return {"derived": False, "errors": [DATASET_DETAIL_TIMEZONE_INVALID_ERROR]}

    current_value = entry.get("dataset_detail_updated_at")
    try:
        if isinstance(current_value, str) and current_value:
            source = datetime.fromisoformat(current_value.replace("Z", "+00:00"))
            if source.tzinfo is None:
                raise ValueError
            source = source.astimezone(timezone.utc)
        else:
            source = fallback_now or datetime.now(timezone.utc)
            if source.tzinfo is None:
                source = source.replace(tzinfo=timezone.utc)
            source = source.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return {"derived": False, "errors": [DATASET_DETAIL_TIMEZONE_INVALID_ERROR]}

    local_source = source.astimezone(zone)
    target_date = parsed_date or local_source.date()
    components = (
        target_date.year,
        target_date.month,
        target_date.day,
        local_source.hour,
        local_source.minute,
        local_source.second,
        local_source.microsecond,
    )
    candidates = [datetime(*components, tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid_candidates = []
    for candidate in candidates:
        round_trip = candidate.astimezone(timezone.utc).astimezone(zone)
        if (
            round_trip.date() == target_date
            and round_trip.time().replace(tzinfo=None) == candidate.time().replace(tzinfo=None)
        ):
            valid_candidates.append(candidate)

    if not valid_candidates or (
        len(valid_candidates) == 2
        and valid_candidates[0].utcoffset() != valid_candidates[1].utcoffset()
    ):
        return {"derived": False, "errors": [DATASET_DETAIL_TIMEZONE_INVALID_ERROR]}

    canonical = valid_candidates[0].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "derived": True,
        "dataset_detail_updated_at": canonical,
        "local_calendar_date": target_date.isoformat(),
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
