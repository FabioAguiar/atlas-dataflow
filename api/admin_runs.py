import json
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_RUN_ARTIFACT_MANIFEST = "manifest.json"
_RUN_ARTIFACT_VALIDATION_RESULT = "validation-result.json"
_RUN_ARTIFACT_PROMOTION_RESULT = "promotion-result.json"

_DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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

    return {
        "schema_version": "admin-run-summary.v1",
        "run_id": run_id,
        "status": "available",
        "dataset_candidate": dataset_candidate,
        "created_at": created_at,
        "trace_reference": _trace_reference_for(run_dir),
        "validation_summary": validation_summary,
    }


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
