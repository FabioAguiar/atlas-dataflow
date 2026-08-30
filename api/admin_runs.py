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


def _registry_entry_for_dataset_slug(dataset_slug: str) -> dict | None:
    """Project Spec S0282: resolve a live registry entry by *exact* dataset_slug.

    Used to tell whether the Dataset Detail a completed historical promotion
    recorded still exists in the live registry (and, if so, which release it
    now points at). No title matching and no normalization beyond the
    slug-pattern validation already used across this module. The entry is
    returned only when it is well-formed enough to reconcile against: a valid
    dataset_slug and a string active_release matching the registry's
    release-id convention. Registry/release/promotion artifacts stay
    read-only to this projection.
    """
    if not isinstance(dataset_slug, str) or not _DATASET_SLUG_PATTERN.match(dataset_slug):
        return None
    for entry in _registry_dataset_entries():
        if not isinstance(entry, dict) or entry.get("dataset_slug") != dataset_slug:
            continue
        active_release = entry.get("active_release")
        if not isinstance(active_release, str) or not RELEASE_ID_PATTERN.match(active_release):
            return None
        return entry
    return None


def _historical_public_dataset_slug(
    promotion_result: dict, candidate_identity: dict
) -> str | None:
    """Project Spec S0282: the final public slug this promotion actually
    allocated, used only to decide whether the same recorded Dataset Detail
    identity still exists after this run's promoted release is no longer
    active. promotion-result.json's registry_update_record.public_dataset_slug
    is authoritative when present and valid (an older create-new-mode
    promotion may have allocated a numbered slug different from the candidate
    base slug); otherwise the candidate base slug is the historical identity.
    """
    record = promotion_result.get("registry_update_record")
    if isinstance(record, dict):
        recorded = record.get("public_dataset_slug")
        if isinstance(recorded, str) and _DATASET_SLUG_PATTERN.match(recorded):
            return recorded
    fallback = candidate_identity.get("dataset_slug")
    if isinstance(fallback, str) and _DATASET_SLUG_PATTERN.match(fallback):
        return fallback
    return None


_REGISTRY_BOUND_REASON = "This run has already been promoted as a Dataset Detail."
_REGISTRY_ORPHANED_REASON = (
    "The Dataset Detail associated with this run's promoted release is no "
    "longer in the registry, so this run can be promoted again."
)
_REGISTRY_SUPERSEDED_REASON = (
    'This run was promoted to release "{release_id}". That historical release '
    'is preserved; release "{current_active_release_id}" is currently active '
    'for "{public_dataset_slug}". Promote may create a new Dataset Detail for '
    'this historical release without replacing the current binding.'
)


def _promotion_summary_from(run_dir: Path) -> dict | None:
    """Sanitized promoted-state projection from this run's promotion-result.json.

    Project Spec S0262: promotion_outcome == "promoted" alone is no longer
    sufficient evidence of a *completed* Admin promotion -- publisher/promote.py
    writes promotion_outcome: promoted for the provisional
    release-materialized / registry-unapplied substate too (before any
    registry activation has been attempted). Completion evidence is resolved
    conservatively from two sources, checked in order:

      1. current live evidence: registry/datasets.json has an entry whose
         active_release == release_id (re-derived below via
         _public_dataset_slug_for_release, unchanged from before S0262);
      2. historical persisted evidence: registry_update_record.update_applied
         is true and registry_update_record.new_active_release_id equals
         this run's own release_id -- proof a registry activation completed
         at some point in the past, even if the live registry entry was
         later removed (preserves S0048's re-promotable orphan semantics).

    A run with neither -- update_applied is false/missing, or no live
    binding and no matching historical record -- is a never-completed
    registry activation, not a completed promotion: this function returns
    None so the run keeps surfacing in its existing retryable Admin state
    (see _derive_run_summary below) instead of being misreported as
    "promoted".

    public_dataset_slug/registry_action are populated only when the live
    registry (registry/datasets.json) confirms this release is still the
    dataset's current active_release: a freshly re-derived idempotence signal
    rather than a persisted claim, and required by S0045 to remain accurate
    across repeated Promote clicks regardless of what promotion-result.json
    itself says.

    Project Spec S0048 adds registry_bound/can_promote/can_remove/reason so
    the Dashboard no longer has to infer button behavior from the presence of
    public_dataset_slug alone. can_remove is always true here: removing a run
    only ever deletes its run artifact/directory (see remove_admin_run, which
    never inspects promotion state at all) and never mutates the registry,
    releases, or Dataset Details.

    Project Spec S0282 reconciles a completed historical promotion against the
    live registry into an explicit registry_state, so a promotion whose
    release is no longer active is no longer collapsed with a promotion whose
    Dataset Detail is gone:

      - "active": the live registry still binds this exact release
        (_public_dataset_slug_for_release). This stays authoritative even when
        the Dataset Detail slug was renamed after promotion. registry_bound
        true, can_promote false, public_dataset_slug + registry_action="reused".
      - "superseded": the release is not currently active, but historical
        applied evidence proves completion, and the recorded final public slug
        still resolves to a live registry entry whose active_release is a
        different (valid) release. registry_bound false, public_dataset_slug +
        current_active_release_id. The historical release is preserved and the
        current binding is never replaced, but (Project Spec S0283) can_promote
        is true: the generic Admin Promote route creates a new numbered Dataset
        Detail for this historical release via MODE_CREATE_NEW_DATASET_DETAIL.
      - "missing": historical applied evidence proves completion, the release
        is not currently active, and the recorded final public slug has no
        live registry entry -- preserves S0048: registry_bound false,
        can_promote true.

    A run with no live binding and no matching historical applied evidence is
    a never-completed registry activation (Project Spec S0262), not a
    completed promotion: this function returns None so the run keeps surfacing
    in its existing retryable Admin state instead of being misreported.
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
        "can_remove": True,
    }

    # --- active: the live registry still binds this exact release ---
    live_public_slug = _public_dataset_slug_for_release(release_id)
    if live_public_slug is not None:
        summary.update(
            {
                "registry_state": "active",
                "registry_bound": True,
                "can_promote": False,
                "public_dataset_slug": live_public_slug,
                "registry_action": "reused",
                "reason": _REGISTRY_BOUND_REASON,
            }
        )
        return summary

    # --- not live-bound: require proven historical applied evidence (S0262) ---
    registry_update_record = promotion_result.get("registry_update_record")
    historically_applied = (
        isinstance(registry_update_record, dict)
        and registry_update_record.get("update_applied") is True
        and registry_update_record.get("new_active_release_id") == release_id
    )
    if not historically_applied:
        return None

    historical_slug = _historical_public_dataset_slug(promotion_result, candidate_identity)
    registry_entry = (
        _registry_entry_for_dataset_slug(historical_slug) if historical_slug else None
    )

    if registry_entry is not None:
        current_active_release_id = registry_entry.get("active_release")
        if current_active_release_id != release_id:
            # --- superseded: Dataset Detail still exists, newer release active ---
            # Project Spec S0283: the historical release is preserved and the
            # current binding is never touched, but this run is eligible for
            # safe create-new recovery -- the generic Admin Promote route
            # (MODE_CREATE_NEW_DATASET_DETAIL) allocates a new numbered Dataset
            # Detail for it. registry_bound stays false; can_promote is now
            # true. Active runs stay can_promote false; missing runs stay
            # can_promote true (S0048), and S0262 never-completed promotions
            # still return None above.
            summary.update(
                {
                    "registry_state": "superseded",
                    "registry_bound": False,
                    "can_promote": True,
                    "public_dataset_slug": historical_slug,
                    "current_active_release_id": current_active_release_id,
                    "reason": _REGISTRY_SUPERSEDED_REASON.format(
                        release_id=release_id,
                        current_active_release_id=current_active_release_id,
                        public_dataset_slug=historical_slug,
                    ),
                }
            )
            return summary

    # --- missing: historically promoted, Dataset Detail no longer in registry ---
    summary.update(
        {
            "registry_state": "missing",
            "registry_bound": False,
            "can_promote": True,
            "reason": _REGISTRY_ORPHANED_REASON,
        }
    )
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

    # Project Spec S0045 (refined by S0262): a well-formed run whose
    # promotion has genuine completion evidence (live registry binding or
    # historical applied evidence) must never continue to be reflected as an
    # available/pending promotion target. A run whose registry activation
    # never completed stays "available"/retryable -- see
    # _promotion_summary_from's completion-evidence resolution above.
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
    """Project Spec S0190: promotion eligibility derives from the run's own
    immutable validation_outcome, not a persisted promotion_gate.promotion_allowed
    flag -- a structurally accepted validated_external_fitted_model run
    produced before S0190 may still carry promotion_gate.promotion_allowed:
    false from the retired operational-readiness gate; that stale flag no
    longer blocks promotion. promotion_gate must still be present as a
    well-formed object (every real publisher/validate.py output has always
    produced one), but its promotion_allowed boolean is no longer
    authoritative -- matches publisher/promote.py's own _check_promotion_gate.
    """
    if validation_result.get("validation_outcome") != "accepted":
        return False
    promotion_gate = validation_result.get("promotion_gate")
    return isinstance(promotion_gate, dict)


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
