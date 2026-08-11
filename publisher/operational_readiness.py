"""
Publisher operational-readiness review orchestration (Project Spec S0189).

Reviews a single completed, structurally-accepted, validated_external_fitted_model
publisher run and, given an operator-entered decision, materializes a governed
publisher/operational-readiness-decision.schema.json artifact bound to that
run's exact release candidate, predictive bundle, and terminal result hashes.
It then invokes publisher.validate in its operational-decision mode to produce
a brand-new publisher run (never mutating the source run) whose
validation-result.json records the decision reference/hash and derived
promotion eligibility, and generates a manifest for that new run when it is
structurally accepted.

Never calls publisher.promote or registry.update. Never edits the source run,
the source release candidate, or the source predictive bundle. Never infers
dataset/release identity from a glob or a "newest run" scan -- identity comes
only from the named source run's own already-written validation-result.json.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_ALLOWED_OPERATOR_DECISION_KEYS = frozenset({
    "operational_validity",
    "operational_threshold",
    "operational_prediction_available",
    "decision_basis",
})
_ALLOWED_THRESHOLD_KEYS = frozenset({"status", "value", "selection_basis"})


def _load_json_file(path: Path) -> tuple[Any, str | None]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None, f"{path.name} could not be read."
    try:
        return json.loads(content), None
    except json.JSONDecodeError:
        return None, f"{path.name} is not valid JSON."


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _load_operational_note(repo_root: Path) -> tuple[dict | None, str | None]:
    return _load_json_file(repo_root / "publisher" / "release-candidate.operational-note.json")


def _unsafe_reference(reference: str, base_dir: Path) -> bool:
    path = Path(reference)
    if path.is_absolute() or ".." in path.parts:
        return True
    resolved = (base_dir / path).resolve()
    return not resolved.is_relative_to(base_dir.resolve())


def _validate_run_id(run_id: Any) -> tuple[bool, str | None]:
    if not isinstance(run_id, str) or not run_id:
        return False, "source_run_id must be a non-empty string."
    if "/" in run_id or "\\" in run_id or ".." in run_id or not _RUN_ID_PATTERN.match(run_id):
        return False, "source_run_id contains unsafe characters."
    return True, None


def _resolve_candidate_dir(
    dataset_slug: str, release_id: str, repo_root: Path, note: dict
) -> tuple[Path | None, str | None]:
    convention = note.get("candidate_directory_convention") or {}
    pattern = convention.get("pattern", "releases/candidates/{dataset_slug}/{release_id}/")
    candidate_dir_rel = (
        pattern.replace("{dataset_slug}", dataset_slug).replace("{release_id}", release_id).rstrip("/")
    )
    staging_root = (repo_root / "releases" / "candidates").resolve()
    candidate_dir = (repo_root / candidate_dir_rel).resolve()
    try:
        candidate_dir.relative_to(staging_root)
    except ValueError:
        return None, "Resolved candidate directory escapes releases/candidates/."
    if not candidate_dir.is_dir():
        return None, "Release candidate directory could not be located."
    return candidate_dir, None


def _validate_operator_decision(operator_decision: Any) -> dict:
    """Validate the operator-entered decision payload against a strict
    allow-list of fields. Rejects (fails closed on) any unexpected key --
    in particular, this is the enforcement point for "the caller cannot
    supply SHA-256 bindings or promotion_allowed"."""
    if not isinstance(operator_decision, dict):
        return {"error": True, "reason_code": "operator_decision_not_an_object", "message": "operator_decision must be a JSON object."}

    extra_keys = set(operator_decision) - _ALLOWED_OPERATOR_DECISION_KEYS
    if extra_keys:
        return {
            "error": True,
            "reason_code": "operator_supplied_forbidden_field",
            "message": f"operator_decision must not include: {sorted(extra_keys)}.",
        }
    missing_keys = _ALLOWED_OPERATOR_DECISION_KEYS - set(operator_decision)
    if missing_keys:
        return {
            "error": True,
            "reason_code": "operator_decision_incomplete",
            "message": f"operator_decision is missing required fields: {sorted(missing_keys)}.",
        }

    operational_validity = operator_decision.get("operational_validity")
    if operational_validity not in ("confirmed", "unconfirmed"):
        return {
            "error": True,
            "reason_code": "operational_validity_invalid",
            "message": "operational_validity must be 'confirmed' or 'unconfirmed'.",
        }

    threshold = operator_decision.get("operational_threshold")
    if not isinstance(threshold, dict):
        return {"error": True, "reason_code": "operational_threshold_invalid", "message": "operational_threshold must be an object."}
    extra_threshold_keys = set(threshold) - _ALLOWED_THRESHOLD_KEYS
    if extra_threshold_keys:
        return {
            "error": True,
            "reason_code": "operator_supplied_forbidden_field",
            "message": f"operational_threshold must not include: {sorted(extra_threshold_keys)}.",
        }

    status = threshold.get("status")
    value = threshold.get("value")
    selection_basis = threshold.get("selection_basis")
    if status == "resolved":
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0 <= value <= 1):
            return {
                "error": True,
                "reason_code": "operational_threshold_out_of_range",
                "message": "A resolved operational_threshold.value must be numeric in [0, 1].",
            }
        if not isinstance(selection_basis, str) or not selection_basis.strip():
            return {
                "error": True,
                "reason_code": "operational_threshold_selection_basis_missing",
                "message": "A resolved operational_threshold requires a non-empty selection_basis.",
            }
        value = float(value)
    elif status == "unresolved":
        if value is not None or selection_basis is not None:
            return {
                "error": True,
                "reason_code": "operational_threshold_invalid",
                "message": "An unresolved operational_threshold must have value and selection_basis both null.",
            }
    else:
        return {
            "error": True,
            "reason_code": "operational_threshold_invalid",
            "message": "operational_threshold.status must be 'resolved' or 'unresolved'.",
        }

    operational_prediction_available = operator_decision.get("operational_prediction_available")
    if not isinstance(operational_prediction_available, bool):
        return {
            "error": True,
            "reason_code": "operational_prediction_available_invalid",
            "message": "operational_prediction_available must be a boolean.",
        }

    decision_basis = operator_decision.get("decision_basis")
    if not isinstance(decision_basis, str) or not decision_basis.strip():
        return {"error": True, "reason_code": "decision_basis_empty", "message": "decision_basis must be a non-empty string."}

    return {
        "error": False,
        "decision": {
            "operational_validity": operational_validity,
            "operational_threshold": {"status": status, "value": value, "selection_basis": selection_basis},
            "operational_prediction_available": operational_prediction_available,
            "decision_basis": decision_basis,
        },
    }


def _result(
    *,
    status: str,
    source_run_id: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
    new_run_id: str | None = None,
    new_run_dir: str | None = None,
    validation_outcome: str | None = None,
    promotion_eligible: bool = False,
    manifest_generated: bool = False,
    manifest_path: str | None = None,
    manifest_error: str | None = None,
    decision_reference: str | None = None,
) -> dict:
    return {
        "review_status": status,
        "reason_code": reason_code,
        "message": message,
        "source_run_id": source_run_id,
        "new_run_id": new_run_id,
        "new_run_dir": new_run_dir,
        "validation_outcome": validation_outcome,
        "promotion_eligible": promotion_eligible,
        "manifest_generated": manifest_generated,
        "manifest_path": manifest_path,
        "manifest_error": manifest_error,
        "decision_reference": decision_reference,
        "boundary_confirmations": {
            "promotion_invoked": False,
            "registry_update_invoked": False,
            "source_run_mutated": False,
            "source_candidate_mutated": False,
            "source_inference_bundle_mutated": False,
        },
    }


def review_operational_readiness(
    source_run_id: str,
    operator_decision: dict,
    repo_root: Path | None = None,
    runs_root: Path | None = None,
) -> dict:
    """Review operational readiness for one completed source publisher run.

    `runs_root` defaults to `repo_root/publisher/runs` -- the same default
    every other publisher module uses -- but may be supplied explicitly so a
    caller with its own independently configured runs root (e.g. the Admin
    API's ADMIN_RUNS_ROOT) can point this review at the same directory its
    run listing/removal/promotion already use, without changing where
    resolved candidates/releases are read from (still always
    `repo_root`-relative). Still never accepts an arbitrary/glob-derived
    root: the source run must resolve to exactly one confined directory
    under whichever runs_root is in effect.

    Returns a reduced result dict (see `_result` above). Never raises for an
    expected/handled blocking condition -- every failure mode returns
    review_status: "blocked" with a concrete reason_code and message.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    resolved_repo_root = Path(repo_root).expanduser().resolve()

    run_id_ok, run_id_error = _validate_run_id(source_run_id)
    if not run_id_ok:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="unsafe_run_reference", message=run_id_error)

    runs_root = (Path(runs_root) if runs_root is not None else resolved_repo_root / "publisher" / "runs").resolve()
    source_run_dir = (runs_root / source_run_id).resolve()
    try:
        source_run_dir.relative_to(runs_root)
    except ValueError:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="unsafe_run_reference", message="Source run reference escapes publisher/runs/.")
    if not source_run_dir.is_dir():
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_run_not_found", message="Source run directory does not exist.")

    validation_result, err = _load_json_file(source_run_dir / "validation-result.json")
    if err or not isinstance(validation_result, dict):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_validation_result_unreadable", message=err or "validation-result.json is not an object.")

    terminal_result, err = _load_json_file(source_run_dir / "validated-run-terminal-result.json")
    if err or not isinstance(terminal_result, dict):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_terminal_result_unreadable", message=err or "validated-run-terminal-result.json is not an object.")

    if validation_result.get("validation_outcome") != "accepted":
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_validation_not_accepted", message="Source run's structural validation was not accepted.")

    if terminal_result.get("model_source_mode") != "validated_external_fitted_model":
        return _result(status="blocked", source_run_id=source_run_id, reason_code="non_external_provenance_rejected", message="Operational readiness review is available only for validated_external_fitted_model provenance.")

    promotion_result_path = source_run_dir / "promotion-result.json"
    if promotion_result_path.is_file():
        promotion_result, _ = _load_json_file(promotion_result_path)
        if isinstance(promotion_result, dict) and promotion_result.get("promotion_outcome") == "promoted":
            return _result(status="blocked", source_run_id=source_run_id, reason_code="source_run_already_promoted", message="Source run has already been promoted.")

    candidate_identity = validation_result.get("candidate_identity") or {}
    dataset_slug = candidate_identity.get("dataset_slug")
    release_id = candidate_identity.get("release_id")
    release_version = candidate_identity.get("release_version")
    if not dataset_slug or not release_id or not release_version:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_candidate_identity_missing", message="Source validation result is missing candidate identity.")

    note, err = _load_operational_note(resolved_repo_root)
    if err or not isinstance(note, dict):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="operational_note_unreadable", message=err or "Operational note is not an object.")

    candidate_dir, err = _resolve_candidate_dir(dataset_slug, release_id, resolved_repo_root, note)
    if err or candidate_dir is None:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="candidate_directory_missing", message=err)

    candidate, err = _load_json_file(candidate_dir / "release-candidate.json")
    if err or not isinstance(candidate, dict):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="candidate_unreadable", message=err or "release-candidate.json is not an object.")

    artifact_roles = candidate.get("artifact_roles") or {}
    predictive_bundle_role = artifact_roles.get("predictive_bundle") or {}
    pb_relative_path = predictive_bundle_role.get("path")
    if not isinstance(pb_relative_path, str) or not pb_relative_path or _unsafe_reference(pb_relative_path, candidate_dir):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="predictive_bundle_reference_unsafe", message="Candidate predictive_bundle reference is missing or unsafe.")

    predictive_bundle_path = candidate_dir / pb_relative_path
    predictive_bundle, err = _load_json_file(predictive_bundle_path)
    if err or not isinstance(predictive_bundle, dict):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="predictive_bundle_unreadable", message=err or "predictive_bundle artifact is not an object.")

    if predictive_bundle.get("model_provenance_origin") != "validated_external_fitted_model":
        return _result(status="blocked", source_run_id=source_run_id, reason_code="non_external_provenance_rejected", message="Predictive bundle provenance is not validated_external_fitted_model.")

    rc_path = candidate_dir / "release-candidate.json"
    rc_sha256 = _sha256_file(rc_path)
    pb_sha256 = _sha256_file(predictive_bundle_path)
    terminal_result_path = source_run_dir / "validated-run-terminal-result.json"
    terminal_sha256 = _sha256_file(terminal_result_path)
    if rc_sha256 is None or pb_sha256 is None or terminal_sha256 is None:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_binding_unreadable", message="Could not compute a required source binding hash.")

    readiness = (predictive_bundle.get("external_model_evidence") or {}).get("readiness") or {}
    source_operational_validity = readiness.get("operational_validity")
    source_threshold = readiness.get("operational_threshold") or {}
    source_operational_threshold_status = source_threshold.get("status")
    source_operational_threshold_value = source_threshold.get("value")
    source_operational_prediction_available = readiness.get("operational_prediction_available")
    if (
        source_operational_validity not in ("confirmed", "unconfirmed")
        or source_operational_threshold_status not in ("resolved", "unresolved")
        or not isinstance(source_operational_prediction_available, bool)
    ):
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_readiness_malformed", message="Source predictive bundle readiness snapshot is malformed.")

    decision_fields_result = _validate_operator_decision(operator_decision)
    if decision_fields_result["error"]:
        return _result(status="blocked", source_run_id=source_run_id, reason_code=decision_fields_result["reason_code"], message=decision_fields_result["message"])
    decision_fields = decision_fields_result["decision"]

    decision = {
        "schema_version": "operational-readiness-decision.v1",
        "artifact_kind": "operational_readiness_decision",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_run": {"run_id": source_run_id},
        "candidate_identity": {
            "dataset_slug": dataset_slug,
            "release_id": release_id,
            "release_version": release_version,
        },
        "source_bindings": {
            "release_candidate": {"path": "release-candidate.json", "sha256": rc_sha256},
            "predictive_bundle": {"path": pb_relative_path, "sha256": pb_sha256},
            "validated_run_terminal_result": {
                "path": str(terminal_result_path.relative_to(resolved_repo_root)),
                "sha256": terminal_sha256,
            },
        },
        "source_readiness": {
            "operational_validity": source_operational_validity,
            "operational_threshold": {
                "status": source_operational_threshold_status,
                "value": source_operational_threshold_value,
            },
            "operational_prediction_available": source_operational_prediction_available,
        },
        "decision": decision_fields,
        "boundary_confirmations": {
            "educational_threshold_automatically_promoted": False,
            "model_retrained": False,
            "model_reselected": False,
            "threshold_reoptimized_by_atlas": False,
            "source_run_mutated": False,
            "source_candidate_mutated": False,
            "source_inference_bundle_mutated": False,
            "promotion_invoked": False,
            "registry_mutated": False,
        },
    }

    before_rc_bytes = rc_path.read_bytes()
    before_pb_bytes = predictive_bundle_path.read_bytes()

    from publisher import validate as validate_module  # local import: avoid a package-level cross-module dependency

    validation = validate_module.run(
        str(candidate_dir), repo_root=resolved_repo_root, operational_readiness_decision=decision
    )

    if rc_path.read_bytes() != before_rc_bytes or predictive_bundle_path.read_bytes() != before_pb_bytes:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="source_candidate_mutated", message="Source candidate was unexpectedly modified during review.")

    decision_reference = validation.get("operational_readiness_evaluation", {}).get("decision_reference")
    if not decision_reference:
        return _result(status="blocked", source_run_id=source_run_id, reason_code="decision_artifact_not_written", message="Governed decision artifact was not written by the new validation run.")

    new_run_dir = (resolved_repo_root / Path(decision_reference)).parent
    new_run_id = new_run_dir.name

    manifest_generated = False
    manifest_path: str | None = None
    manifest_error: str | None = None
    if validation.get("validation_outcome") == "accepted":
        from publisher import manifest as manifest_module  # local import: avoid a package-level cross-module dependency

        try:
            manifest_module.run(str(new_run_dir), repo_root=resolved_repo_root)
        except RuntimeError as exc:
            manifest_error = str(exc)
        else:
            manifest_generated = True
            manifest_path = str((new_run_dir / "manifest.json").relative_to(resolved_repo_root))

    return _result(
        status="reviewed",
        source_run_id=source_run_id,
        new_run_id=new_run_id,
        new_run_dir=str(new_run_dir.relative_to(resolved_repo_root)),
        validation_outcome=validation.get("validation_outcome"),
        promotion_eligible=bool((validation.get("promotion_gate") or {}).get("promotion_allowed")),
        manifest_generated=manifest_generated,
        manifest_path=manifest_path,
        manifest_error=manifest_error,
        decision_reference=decision_reference,
    )
