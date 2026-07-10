import json
import os
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from publisher import promote as publisher_promote  # noqa: E402
from registry import update as registry_update  # noqa: E402
from registry.validate import RELEASE_ID_PATTERN  # noqa: E402

_RUN_ARTIFACT_MANIFEST = "manifest.json"
_RUN_ARTIFACT_VALIDATION_RESULT = "validation-result.json"
_RUN_ARTIFACT_PROMOTION_RESULT = "promotion-result.json"

_DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_WINDOWS_DRIVE_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")

_RUN_ID_INVALID_ERROR = {
    "code": "RUN_ID_INVALID",
    "field": "run_id",
    "message": "The run id is missing or does not match the required pattern.",
}
_RUN_NOT_FOUND_ERROR = {
    "code": "RUN_NOT_FOUND",
    "field": None,
    "message": "No run was found for the given run id under the configured runs root.",
}
_RUN_REMOVAL_FAILED_ERROR = {
    "code": "RUN_REMOVAL_FAILED",
    "field": None,
    "message": "The run could not be removed.",
}
_RUN_VALIDATION_MISSING_ERROR = {
    "code": "RUN_VALIDATION_MISSING",
    "field": None,
    "message": "No validation result was found for the given run id.",
}
_PROMOTION_NOT_ALLOWED_ERROR = {
    "code": "PROMOTION_NOT_ALLOWED",
    "field": "promotion_gate.promotion_allowed",
    "message": "This run is not eligible for promotion.",
}
_PROMOTION_FAILED_ERROR = {
    "code": "PROMOTION_FAILED",
    "field": None,
    "message": "The run could not be promoted.",
}
_REGISTRY_UPDATE_FAILED_ERROR = {
    "code": "REGISTRY_UPDATE_FAILED",
    "field": None,
    "message": "The dataset registry could not be updated after promotion.",
}
_PROMOTION_MODE_INVALID_ERROR = {
    "code": "PROMOTION_MODE_INVALID",
    "field": "mode",
    "message": "The requested promotion mode is not recognized.",
}

# Project Spec S0042: an explicit mode is always required so a colliding base
# dataset_slug never silently decides between updating the existing Dataset
# Detail and allocating a new one. Defaults to the historical
# update-or-create behavior so existing callers/tests are unaffected.
_VALID_PROMOTION_MODES = (
    registry_update.MODE_UPDATE_EXISTING_OR_CREATE,
    registry_update.MODE_CREATE_NEW_DATASET_DETAIL,
)

# contracts/admin-run-summary.schema.json's validation_summary.outcome enum.
_VALIDATION_OUTCOME_MAP = {
    "accepted": "accepted",
    "rejected": "rejected",
}
_PROMOTION_OUTCOME_MAP = {
    "promoted": "accepted",
    "rejected": "rejected",
}


def _admin_runs_root() -> Path:
    env_root = os.environ.get("ADMIN_RUNS_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT / "publisher" / "runs"


def _read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _run_id_validation_error(run_id: str) -> dict | None:
    if not isinstance(run_id, str) or not run_id:
        return _RUN_ID_INVALID_ERROR
    if run_id in (".", ".."):
        return _RUN_ID_INVALID_ERROR
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        return _RUN_ID_INVALID_ERROR
    if os.path.isabs(run_id) or _WINDOWS_DRIVE_ABSOLUTE_PATTERN.match(run_id):
        return _RUN_ID_INVALID_ERROR
    return None


def _unavailable_entry(run_id: str, reason: str) -> dict:
    return {
        "schema_version": "admin-run-summary.v1",
        "run_id": run_id,
        "status": "unavailable",
        "dataset_candidate": None,
        "created_at": None,
        "trace_reference": None,
        "validation_summary": None,
        "unavailable_reason": reason,
    }


def _invalid_entry(run_id: str, reason: str) -> dict:
    return {
        "schema_version": "admin-run-summary.v1",
        "run_id": run_id,
        "status": "invalid",
        "dataset_candidate": None,
        "created_at": None,
        "trace_reference": None,
        "validation_summary": None,
        "invalid_reason": reason,
    }


def _trace_reference_for(run_dir: Path) -> str:
    # Never an absolute path: prefer a path relative to the repository root
    # (matches decision-002's "repository-relative path"); fall back to the
    # bare run directory name if ADMIN_RUNS_ROOT points outside the repo.
    try:
        return str(run_dir.resolve().relative_to(_REPO_ROOT.resolve()))
    except ValueError:
        return run_dir.name


def _validation_summary_from(run_dir: Path) -> dict | None:
    validation_result = _read_json_object(run_dir / _RUN_ARTIFACT_VALIDATION_RESULT)
    if validation_result is None:
        return None

    outcome = _VALIDATION_OUTCOME_MAP.get(validation_result.get("validation_outcome"))
    if outcome is None:
        promotion_result = _read_json_object(run_dir / _RUN_ARTIFACT_PROMOTION_RESULT)
        promotion_outcome = (
            promotion_result.get("promotion_outcome") if promotion_result else None
        )
        outcome = _PROMOTION_OUTCOME_MAP.get(promotion_outcome, "unknown")

    summary: dict = {"outcome": outcome}

    rejection = validation_result.get("rejection")
    if isinstance(rejection, dict) and rejection.get("rejected"):
        reasons = rejection.get("reasons")
        if isinstance(reasons, list) and reasons:
            first = reasons[0]
            message = first.get("message") if isinstance(first, dict) else None
            if isinstance(message, str) and message:
                summary["reason"] = message

    return summary


def _registry_dataset_entries() -> list:
    registry = _read_json_object(_REPO_ROOT / "registry" / "datasets.json")
    if registry is None:
        return []
    datasets = registry.get("datasets")
    return datasets if isinstance(datasets, list) else []


def _public_dataset_slug_for_release(release_id: str) -> str | None:
    for entry in _registry_dataset_entries():
        if not isinstance(entry, dict) or entry.get("active_release") != release_id:
            continue
        slug = entry.get("dataset_slug")
        if isinstance(slug, str) and _DATASET_SLUG_PATTERN.match(slug):
            return slug
    return None


def _promotion_summary_from(run_dir: Path) -> dict | None:
    """Sanitized promoted-state projection from this run's promotion-result.json.

    Only candidate_identity/promotion_outcome are ever trusted from the
    persisted file. promote_admin_run() below does synchronize
    registry_update_record onto promotion-result.json once a registry update
    is confirmed (Project Spec S0046), but this function deliberately still
    never reads that nested object: this projection must also stay accurate
    when a run was promoted by some other path (a monkeypatched test fixture,
    a hand-authored promotion-result.json, a future caller) that never went
    through finalize_promotion_result_after_registry_update() at all.
    public_dataset_slug/registry_action are populated only when the live
    registry (registry/datasets.json) confirms this release is still the
    dataset's current active_release: a freshly re-derived idempotence signal
    rather than a persisted claim, and required by S0045 to remain accurate
    across repeated Promote clicks regardless of what promotion-result.json
    itself says.
    """
    promotion_result = _read_json_object(run_dir / _RUN_ARTIFACT_PROMOTION_RESULT)
    if promotion_result is None or promotion_result.get("promotion_outcome") != "promoted":
        return None

    candidate_identity = promotion_result.get("candidate_identity")
    if not isinstance(candidate_identity, dict):
        return None

    dataset_slug = candidate_identity.get("dataset_slug")
    release_id = candidate_identity.get("release_id")
    if not isinstance(dataset_slug, str) or not _DATASET_SLUG_PATTERN.match(dataset_slug):
        return None
    if not isinstance(release_id, str) or not RELEASE_ID_PATTERN.match(release_id):
        return None

    summary = {
        "promotion_outcome": "promoted",
        "release_id": release_id,
        "dataset_slug": dataset_slug,
    }

    public_dataset_slug = _public_dataset_slug_for_release(release_id)
    if public_dataset_slug is not None:
        summary["public_dataset_slug"] = public_dataset_slug
        summary["registry_action"] = "reused"

    return summary


def _derive_run_summary(run_dir: Path, runs_root: Path) -> dict:
    run_id = run_dir.name

    # A symlink (or any path) resolving outside the configured runs root is
    # never followed; it is reported as unavailable instead.
    if not _is_within_root(run_dir, runs_root):
        return _unavailable_entry(run_id, "source_run_evidence_unreadable")

    manifest = _read_json_object(run_dir / _RUN_ARTIFACT_MANIFEST)
    if manifest is None:
        return _unavailable_entry(run_id, "source_run_evidence_missing")

    validation_summary = _validation_summary_from(run_dir)
    if validation_summary is None:
        return _unavailable_entry(run_id, "source_run_evidence_missing")

    dataset_identity = manifest.get("dataset_identity")
    release_identity = manifest.get("release_identity")
    if not isinstance(dataset_identity, dict) or not isinstance(release_identity, dict):
        return _invalid_entry(run_id, "source_run_evidence_incomplete")

    dataset_candidate = None
    dataset_slug = dataset_identity.get("dataset_slug")
    if isinstance(dataset_slug, str) and _DATASET_SLUG_PATTERN.match(dataset_slug):
        dataset_candidate = dataset_slug

    created_at = release_identity.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        created_at = None

    entry = {
        "schema_version": "admin-run-summary.v1",
        "run_id": run_id,
        "status": "available",
        "dataset_candidate": dataset_candidate,
        "created_at": created_at,
        "trace_reference": _trace_reference_for(run_dir),
        "validation_summary": validation_summary,
    }

    # Project Spec S0045: a well-formed, promoted run must never continue to
    # be reflected as an available/pending promotion target once
    # promotion-result.json records promotion_outcome: promoted.
    promotion_summary = _promotion_summary_from(run_dir)
    if promotion_summary is not None:
        entry["status"] = "promoted"
        entry["promotion_summary"] = promotion_summary

    return entry


def list_admin_run_summaries() -> dict:
    """Enumerate the configured runs root and derive safe run summaries.

    Returns a dict with two top-level fields so a missing/unreadable runs
    root and a genuinely empty runs root remain two distinct, separately
    observable outcomes (never collapsed into one generic empty result):

        {"runs_root_status": "available" | "unavailable", "runs": [...]}
    """
    runs_root = _admin_runs_root()

    if not runs_root.is_dir():
        return {"runs_root_status": "unavailable", "runs": []}

    try:
        run_dirs = sorted(
            (entry for entry in runs_root.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name,
        )
    except OSError:
        return {"runs_root_status": "unavailable", "runs": []}

    return {
        "runs_root_status": "available",
        "runs": [_derive_run_summary(run_dir, runs_root) for run_dir in run_dirs],
    }


def remove_admin_run(run_id: str) -> dict:
    """Remove exactly one run directory identified by run_id.

    Returns {"run_id": str, "removed": bool, "errors": [...]}, where errors
    is a list of {"code", "field", "message"} entries (mirrors the
    admin_profile_publish.py/admin_predict_view_customizations.py result
    shape). Never raises for an invalid, missing, or non-directory run_id --
    those are reported as a non-removed result with a reduced error instead.

    A run_id containing a path separator, "..", or an absolute path is
    rejected before any filesystem lookup. Resolution is always checked
    against the configured runs root (never following a symlink outside it,
    matching list_admin_run_summaries' own boundary), so only a run
    directory that genuinely resolves under the configured runs root can
    ever be removed.
    """
    validity_error = _run_id_validation_error(run_id)
    if validity_error is not None:
        return {"run_id": run_id, "removed": False, "errors": [validity_error]}

    runs_root = _admin_runs_root()
    run_dir = runs_root / run_id

    if not _is_within_root(run_dir, runs_root):
        return {"run_id": run_id, "removed": False, "errors": [_RUN_NOT_FOUND_ERROR]}

    try:
        is_directory = run_dir.is_dir()
    except OSError:
        is_directory = False
    if not is_directory:
        return {"run_id": run_id, "removed": False, "errors": [_RUN_NOT_FOUND_ERROR]}

    try:
        shutil.rmtree(run_dir)
    except OSError:
        return {"run_id": run_id, "removed": False, "errors": [_RUN_REMOVAL_FAILED_ERROR]}

    return {"run_id": run_id, "removed": True, "errors": []}


def _promotion_gate_allows(validation_result: dict) -> bool:
    if validation_result.get("validation_outcome") != "accepted":
        return False
    promotion_gate = validation_result.get("promotion_gate")
    if not isinstance(promotion_gate, dict):
        return False
    return promotion_gate.get("promotion_allowed") is True


def _promotion_matches_promoted_release(run_dir: Path, release_id: str) -> bool:
    """Validate idempotence before reusing an already-promoted release.

    Compares this run's own manifest.json against the manifest.json that was
    copied into releases/{release_id}/ by the original promotion. A stale or
    mismatched prior promotion-result.json is never reused silently.
    """
    run_manifest = _read_json_object(run_dir / _RUN_ARTIFACT_MANIFEST)
    release_manifest = _read_json_object(_REPO_ROOT / "releases" / release_id / "manifest.json")
    if run_manifest is None or release_manifest is None:
        return False
    return run_manifest == release_manifest


def _promotion_failure_result(run_id: str, error: dict) -> dict:
    return {
        "run_id": run_id,
        "promoted": False,
        "dataset_slug": None,
        "release_id": None,
        "registry_action": None,
        "public_dataset_slug": None,
        "errors": [error],
    }


def promote_admin_run(
    run_id: str, mode: str = registry_update.MODE_UPDATE_EXISTING_OR_CREATE
) -> dict:
    """Promote exactly one accepted, promotion-eligible run into a public release.

    Returns {"run_id", "promoted": bool, "dataset_slug": str|None,
    "release_id": str|None, "registry_action": "created"|"updated"|None,
    "public_dataset_slug": str|None, "errors": [...]}.

    Gates on the run's own validation-result.json: validation_outcome must be
    "accepted" and promotion_gate.promotion_allowed must be exactly True --
    the same gate publisher/promote.py enforces internally, not just the
    reduced admin-run-summary projection. Reuses (never re-copies) an
    already-promoted run's existing promotion-result.json once its manifest is
    confirmed to still match the promoted release, so a repeated Promote click
    is a safe no-op instead of publisher/promote.py's "already exists"
    failure.

    `mode` (Project Spec S0042) is forwarded to registry/update.py and defaults
    to the historical update-or-create behavior: if the base dataset_slug is
    not yet in the registry, a safe public entry is created from the promoted
    release's public context; otherwise the existing entry's active_release is
    updated. Passing registry_update.MODE_CREATE_NEW_DATASET_DETAIL instead
    treats a colliding base dataset_slug as a brand-new Dataset Detail and
    allocates the next available numbered public slug without touching the
    existing entry. An unrecognized mode is rejected with a structured
    failure rather than silently choosing a behavior. `public_dataset_slug`
    always reports the final allocated registry slug (equal to `dataset_slug`
    unless a numbered slug was allocated), so callers can distinguish the
    candidate/base slug from the actual public one. Never raises for an
    invalid run id, missing run, ineligible run, invalid mode, or a downstream
    promotion/registry failure -- those are reported as a non-promoted result
    with a reduced error instead.

    `registry_action` (Project Spec S0044) distinguishes three outcomes so the
    Admin Dashboard can show an accurate message: "created" (a brand-new
    registry entry was appended), "updated" (an existing entry's
    active_release genuinely changed to a different release), or "reused"
    (the entry already had this exact release active -- a repeated Promote
    click for the same run/mode combination, safely idempotent and applying
    no real change). This is derived from registry/update.py's own
    `previous_active_release_id`/`dataset_entry_created` fields; no slug
    allocation or registry-update internals are changed to support it.
    """
    if mode not in _VALID_PROMOTION_MODES:
        return _promotion_failure_result(run_id, _PROMOTION_MODE_INVALID_ERROR)

    validity_error = _run_id_validation_error(run_id)
    if validity_error is not None:
        return _promotion_failure_result(run_id, validity_error)

    runs_root = _admin_runs_root()
    run_dir = runs_root / run_id

    if not _is_within_root(run_dir, runs_root):
        return _promotion_failure_result(run_id, _RUN_NOT_FOUND_ERROR)

    try:
        is_directory = run_dir.is_dir()
    except OSError:
        is_directory = False
    if not is_directory:
        return _promotion_failure_result(run_id, _RUN_NOT_FOUND_ERROR)

    validation_result = _read_json_object(run_dir / _RUN_ARTIFACT_VALIDATION_RESULT)
    if validation_result is None:
        return _promotion_failure_result(run_id, _RUN_VALIDATION_MISSING_ERROR)

    if not _promotion_gate_allows(validation_result):
        return _promotion_failure_result(run_id, _PROMOTION_NOT_ALLOWED_ERROR)

    existing_promotion = _read_json_object(run_dir / _RUN_ARTIFACT_PROMOTION_RESULT)
    promotion_result = None
    if existing_promotion is not None and existing_promotion.get("promotion_outcome") == "promoted":
        candidate_identity = existing_promotion.get("candidate_identity") or {}
        release_id = candidate_identity.get("release_id")
        if isinstance(release_id, str) and _promotion_matches_promoted_release(run_dir, release_id):
            promotion_result = existing_promotion
        else:
            return _promotion_failure_result(run_id, _PROMOTION_FAILED_ERROR)

    if promotion_result is None:
        try:
            promotion_result = publisher_promote.run(str(run_dir), repo_root=_REPO_ROOT)
        except (RuntimeError, ValueError, OSError):
            return _promotion_failure_result(run_id, _PROMOTION_FAILED_ERROR)

    try:
        registry_result = registry_update.run(str(run_dir), repo_root=_REPO_ROOT, mode=mode)
    except (RuntimeError, ValueError):
        return _promotion_failure_result(run_id, _REGISTRY_UPDATE_FAILED_ERROR)

    candidate_identity = promotion_result.get("candidate_identity") or {}
    registry_action = registry_update.derive_registry_action(registry_result)

    # Project Spec S0046: persist the now-confirmed registry outcome back
    # into promotion-result.json so it no longer contradicts the real
    # registry state. Only reached after registry_update.run() above has
    # already returned successfully -- never after it raised -- so this can
    # only ever move registry_update_record from "not yet applied" to an
    # accurate "applied" record, never fabricate a success. A failure to
    # persist this synchronized evidence does not unwind or invalidate the
    # registry mutation that already genuinely happened, and this function's
    # own contract (like every other branch here) is to never raise for a
    # downstream failure -- it is disclosed only by the on-disk evidence
    # lagging, not by failing the whole promotion.
    try:
        publisher_promote.finalize_promotion_result_after_registry_update(
            str(run_dir), registry_result, registry_action, repo_root=_REPO_ROOT
        )
    except (RuntimeError, ValueError, OSError):
        pass

    return {
        "run_id": run_id,
        "promoted": True,
        "dataset_slug": candidate_identity.get("dataset_slug"),
        "release_id": candidate_identity.get("release_id"),
        "registry_action": registry_action,
        "public_dataset_slug": registry_result.get("allocated_dataset_slug"),
        "errors": [],
    }
