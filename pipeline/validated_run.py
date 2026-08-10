"""
Generic validated-run terminal-result producer for atlas-dataflow (Project Spec S0181).

Materializes one durable, schema-backed terminal artifact recording
orchestration completion/block/failure for a dataset-integration run, from
explicit durable artifact references only. Never inspects notebook cells,
hidden globals, runtime services, registry state, or external project
directories -- every reference this module reasons about is an explicit
caller-supplied {path, sha256} pair, and every supplied reference is
re-hashed against the actual file bytes before this module trusts it.

Structural validation acceptance (publisher.validate's validation_outcome)
and operational promotion eligibility are always kept distinct, matching
the same separation Project Spec S0180 already established in
publisher/validate.py and publisher/manifest.py: an accepted structural
validation never forces promotion_eligibility true on its own. For a
validated_external_fitted_model run, promotion_eligibility can become true
only when structural validation is accepted AND operational_validity is
confirmed AND operational_threshold.status is resolved AND
operational_prediction_available is true -- fail closed on every other
combination, including when any of the four signals is simply absent. For
every other model_source_mode (the historical atlas_internal_training
path), promotion_eligibility mirrors the unchanged historical behavior:
structural acceptance alone is sufficient, matching
publisher.validate._build_validation_result's non-external branch.

This module never calls publisher.promote.run, never writes registry
state, and never turns an educational threshold into an operational
threshold -- it does not accept or touch an educational threshold at all.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "validated-run-terminal-result.v1"
ARTIFACT_KIND = "validated_run_terminal_result"

_STATUSES = ("completed", "blocked", "failed")
_MODEL_SOURCE_MODES = ("atlas_internal_training", "validated_external_fitted_model")
_EXTERNAL_MODEL_SOURCE_MODE = "validated_external_fitted_model"
_DURABLE_REFERENCE_ROLES = (
    "materialization_result",
    "inference_bundle",
    "release_candidate",
    "publisher_validation_result",
    "manifest",
    "operational_readiness_source",
)

DATASET_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class TerminalResultBlocked(Exception):
    """Internal control-flow signal that short-circuits to a blocked terminal result."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reason(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    reason: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        reason["field"] = field
    return reason


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _boundary_confirmations() -> dict[str, bool]:
    return {
        "publisher_promotion_invoked": False,
        "registry_state_written": False,
        "educational_threshold_reinterpreted_as_operational": False,
    }


def _verify_durable_references(
    durable_references: dict[str, Any] | None, repo_root: Path
) -> dict[str, dict[str, str] | None]:
    """Verify and normalize every supplied durable artifact reference.

    Returns the normalized {role: {"path", "sha256"} | None} mapping for
    all six known roles. Raises TerminalResultBlocked if any *supplied*
    reference is malformed, unreadable, or its declared sha256 does not
    match the actual file bytes. A role that the caller omits (or sets to
    None) is not required -- "as applicable" per Project Spec S0181 -- and
    is normalized to None.
    """
    raw = durable_references if isinstance(durable_references, dict) else {}
    normalized: dict[str, dict[str, str] | None] = {}
    for role in _DURABLE_REFERENCE_ROLES:
        entry = raw.get(role)
        if entry is None:
            normalized[role] = None
            continue
        if not isinstance(entry, dict):
            raise TerminalResultBlocked(
                "malformed_durable_reference", f"durable_references.{role} must be an object or null.", role
            )
        path_value = entry.get("path")
        sha256_value = entry.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            raise TerminalResultBlocked(
                "missing_required_reference",
                f"durable_references.{role}.path must be a non-empty string.",
                f"{role}.path",
            )
        if not isinstance(sha256_value, str) or not SHA256_RE.fullmatch(sha256_value):
            raise TerminalResultBlocked(
                "invalid_hash",
                f"durable_references.{role}.sha256 must be a lowercase SHA-256 hex digest.",
                f"{role}.sha256",
            )
        resolved_path = Path(path_value)
        if resolved_path.is_absolute() or ".." in resolved_path.parts:
            raise TerminalResultBlocked(
                "unsafe_durable_reference",
                f"durable_references.{role}.path must be a safe repository-relative path.",
                f"{role}.path",
            )
        actual_sha256 = _sha256_file(repo_root / resolved_path)
        if actual_sha256 is None:
            raise TerminalResultBlocked(
                "durable_reference_missing",
                f"durable_references.{role} could not be read at the declared path.",
                f"{role}.path",
            )
        if actual_sha256 != sha256_value:
            raise TerminalResultBlocked(
                "durable_reference_hash_mismatch",
                f"durable_references.{role} bytes do not match the declared sha256.",
                f"{role}.sha256",
            )
        normalized[role] = {"path": path_value, "sha256": sha256_value}
    return normalized


def _normalize_structural_validation(structural_validation: Any) -> dict[str, Any] | None:
    if structural_validation is None:
        return None
    if not isinstance(structural_validation, dict):
        raise TerminalResultBlocked(
            "malformed_structural_validation", "structural_validation must be an object or null."
        )
    outcome = structural_validation.get("validation_outcome")
    if outcome not in ("accepted", "rejected"):
        raise TerminalResultBlocked(
            "malformed_structural_validation",
            "structural_validation.validation_outcome must be 'accepted' or 'rejected'.",
            "structural_validation.validation_outcome",
        )
    return {"checked": True, "validation_outcome": outcome}


def _normalize_manifest_outcome(manifest_outcome: Any) -> dict[str, Any] | None:
    if manifest_outcome is None:
        return None
    if not isinstance(manifest_outcome, dict) or not isinstance(
        manifest_outcome.get("manifest_generated"), bool
    ):
        raise TerminalResultBlocked(
            "malformed_manifest_outcome",
            "manifest_outcome.manifest_generated must be a boolean when manifest_outcome is present.",
            "manifest_outcome.manifest_generated",
        )
    manifest_path = manifest_outcome.get("manifest_path")
    if manifest_path is not None and not isinstance(manifest_path, str):
        raise TerminalResultBlocked(
            "malformed_manifest_outcome",
            "manifest_outcome.manifest_path must be a string or null.",
            "manifest_outcome.manifest_path",
        )
    return {
        "manifest_generated": manifest_outcome["manifest_generated"],
        "manifest_path": manifest_path,
    }


def _normalize_operational_readiness(operational_readiness: Any) -> dict[str, Any]:
    if not isinstance(operational_readiness, dict):
        raise TerminalResultBlocked(
            "missing_required_field", "operational_readiness must be an object.", "operational_readiness"
        )
    operational_validity = operational_readiness.get("operational_validity")
    if operational_validity not in ("confirmed", "unconfirmed", "not_applicable"):
        raise TerminalResultBlocked(
            "malformed_operational_readiness",
            "operational_readiness.operational_validity must be 'confirmed', 'unconfirmed', or "
            "'not_applicable'.",
            "operational_readiness.operational_validity",
        )
    operational_threshold = operational_readiness.get("operational_threshold")
    if not isinstance(operational_threshold, dict) or operational_threshold.get("status") not in (
        "resolved",
        "unresolved",
        "not_applicable",
    ):
        raise TerminalResultBlocked(
            "malformed_operational_readiness",
            "operational_readiness.operational_threshold.status must be 'resolved', 'unresolved', or "
            "'not_applicable'.",
            "operational_readiness.operational_threshold.status",
        )
    threshold_value = operational_threshold.get("value")
    if threshold_value is not None and (
        isinstance(threshold_value, bool) or not isinstance(threshold_value, (int, float))
    ):
        raise TerminalResultBlocked(
            "malformed_operational_readiness",
            "operational_readiness.operational_threshold.value must be a number or null.",
            "operational_readiness.operational_threshold.value",
        )
    operational_prediction_available = operational_readiness.get("operational_prediction_available")
    if not isinstance(operational_prediction_available, bool):
        raise TerminalResultBlocked(
            "missing_required_field",
            "operational_readiness.operational_prediction_available must be a boolean.",
            "operational_readiness.operational_prediction_available",
        )
    return {
        "operational_validity": operational_validity,
        "operational_threshold": {"status": operational_threshold["status"], "value": threshold_value},
        "operational_prediction_available": operational_prediction_available,
    }


def _compute_promotion_eligibility(
    model_source_mode: str,
    structural_validation: dict[str, Any] | None,
    operational_readiness: dict[str, Any],
) -> bool:
    """Fail-closed promotion-eligibility computation (Project Spec S0181).

    Never returns True unless structural validation is explicitly accepted.
    For validated_external_fitted_model, additionally requires all three
    operational-readiness signals to be explicitly favorable. Every other
    model_source_mode keeps the unchanged historical behavior already
    established by publisher.validate._build_validation_result: structural
    acceptance alone is sufficient.
    """
    if structural_validation is None or structural_validation.get("validation_outcome") != "accepted":
        return False
    if model_source_mode != _EXTERNAL_MODEL_SOURCE_MODE:
        return True
    return (
        operational_readiness.get("operational_validity") == "confirmed"
        and operational_readiness.get("operational_threshold", {}).get("status") == "resolved"
        and operational_readiness.get("operational_prediction_available") is True
    )


def materialize_validated_run_terminal_result(
    *,
    run_id: str,
    dataset_slug: str,
    model_source_mode: str,
    status: str,
    durable_references: dict[str, dict[str, str] | None] | None = None,
    structural_validation: dict[str, Any] | None = None,
    manifest_outcome: dict[str, Any] | None = None,
    operational_readiness: dict[str, Any] | None = None,
    reasons: list[dict[str, Any]] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize a durable validated-run terminal result from explicit references only.

    ``status`` reflects the caller's own already-determined orchestration
    outcome (``completed``, ``blocked``, or ``failed``) -- this module does
    not itself decide whether an orchestration succeeded, only whether the
    supplied durable evidence for that outcome is internally consistent.
    Every non-null entry in ``durable_references`` is re-hashed against its
    actual file bytes; any mismatch or unreadable reference overrides the
    caller's declared ``status`` and returns a ``status: "blocked"`` result
    instead, since an unverifiable reference can never be trusted as
    evidence for any terminal outcome.

    Never calls ``publisher.promote.run``, never writes registry state, and
    never inspects notebook cells, hidden globals, runtime services, the
    registry, or an external project directory -- only the explicit
    references supplied by the caller.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _repo_root()

    try:
        if status not in _STATUSES:
            raise TerminalResultBlocked(
                "invalid_status", f"status must be one of {_STATUSES}.", "status"
            )
        if model_source_mode not in _MODEL_SOURCE_MODES:
            raise TerminalResultBlocked(
                "invalid_model_source_mode",
                f"model_source_mode must be one of {_MODEL_SOURCE_MODES}.",
                "model_source_mode",
            )
        if not isinstance(run_id, str) or not run_id:
            raise TerminalResultBlocked(
                "missing_required_field", "run_id must be a non-empty string.", "run_id"
            )
        if not isinstance(dataset_slug, str) or not DATASET_SLUG_RE.fullmatch(dataset_slug):
            raise TerminalResultBlocked(
                "invalid_dataset_identity", "dataset_slug is not a valid dataset slug.", "dataset_slug"
            )

        normalized_references = _verify_durable_references(durable_references, resolved_repo_root)
        normalized_structural_validation = _normalize_structural_validation(structural_validation)
        normalized_manifest_outcome = _normalize_manifest_outcome(manifest_outcome)
        normalized_operational_readiness = _normalize_operational_readiness(operational_readiness)

        normalized_reasons = list(reasons) if reasons else []
        if status != "completed" and not normalized_reasons:
            raise TerminalResultBlocked(
                "missing_required_field",
                "reasons must be a non-empty array when status is not 'completed'.",
                "reasons",
            )
        for entry in normalized_reasons:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("code"), str)
                or not entry.get("code")
                or not isinstance(entry.get("message"), str)
                or not entry.get("message")
            ):
                raise TerminalResultBlocked(
                    "malformed_reason", "each reasons[] entry must declare a non-empty code and message.", "reasons"
                )

        if status == "completed":
            promotion_eligibility = _compute_promotion_eligibility(
                model_source_mode, normalized_structural_validation, normalized_operational_readiness
            )
            result_reasons: list[dict[str, Any]] = []
        else:
            promotion_eligibility = False
            result_reasons = normalized_reasons

        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "run_identity": {
                "run_id": run_id,
                "dataset_slug": dataset_slug,
                "created_at": _utc_now_iso(),
            },
            "status": status,
            "model_source_mode": model_source_mode,
            "durable_references": normalized_references,
            "structural_validation": normalized_structural_validation,
            "manifest_outcome": normalized_manifest_outcome,
            "operational_readiness": normalized_operational_readiness,
            "promotion_eligibility": promotion_eligibility,
            "reasons": result_reasons,
            "boundary_confirmations": _boundary_confirmations(),
        }

        _validate_against_schema(
            result,
            resolved_repo_root / "pipeline" / "validated-run-terminal-result.schema.json",
        )
        return result

    except TerminalResultBlocked as exc:
        blocked_references: dict[str, dict[str, str] | None] = {
            role: None for role in _DURABLE_REFERENCE_ROLES
        }
        blocked_operational_readiness = {
            "operational_validity": "not_applicable",
            "operational_threshold": {"status": "not_applicable", "value": None},
            "operational_prediction_available": False,
        }
        result = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "run_identity": {
                "run_id": run_id if isinstance(run_id, str) and run_id else "unknown",
                "dataset_slug": dataset_slug
                if isinstance(dataset_slug, str) and DATASET_SLUG_RE.fullmatch(dataset_slug or "")
                else "unknown-dataset",
                "created_at": _utc_now_iso(),
            },
            "status": "blocked",
            "model_source_mode": model_source_mode
            if model_source_mode in _MODEL_SOURCE_MODES
            else "atlas_internal_training",
            "durable_references": blocked_references,
            "structural_validation": None,
            "manifest_outcome": None,
            "operational_readiness": blocked_operational_readiness,
            "promotion_eligibility": False,
            "reasons": [_reason(exc.code, exc.message, exc.field)],
            "boundary_confirmations": _boundary_confirmations(),
        }
        return result


def _validate_against_schema(instance: dict[str, Any], schema_path: Path) -> None:
    import json

    try:
        import jsonschema
    except ImportError as exc:
        raise TerminalResultBlocked(
            "schema_validation_unavailable", "jsonschema is required for terminal-result materialization."
        ) from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TerminalResultBlocked(
            "missing_schema", "validated-run-terminal-result schema file could not be read."
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise TerminalResultBlocked(
            "terminal_result_schema_invalid", f"{path}: {first.message}", path
        )
