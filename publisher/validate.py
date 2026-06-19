"""
Publisher release candidate completeness validator.

Reads a candidate directory path, loads the release candidate JSON,
validates it structurally, checks artifact role file presence,
validates identifier consistency (dataset_slug and release_id against
candidate directory path segments), checks schema compatibility via JSON
validity for the 5 applicable roles, and writes a conformant validation
result to publisher/runs/{run_id}/validation-result.json.

Does NOT compute sha256 hashes (deferred to M11-03).
Does NOT read or modify registry/datasets.json.
Does NOT modify any candidate artifact.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_CANDIDATE_FILENAME = "release-candidate.json"

_REQUIRED_ROLES = (
    "contracts",
    "predictive_bundle",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)

_SCHEMA_COMPAT_ROLES = frozenset({
    "contracts",
    "manifest_input",
    "metrics",
    "model_card",
    "candidate_metadata",
})

_MISSING_ROLE_CODE = {
    "contracts": "missing_runtime_contract",
    "predictive_bundle": "missing_predictive_bundle",
    "metrics": "missing_metrics",
    "model_card": "missing_model_card",
    "public_context": "missing_public_context",
    "manifest_input": "missing_manifest_input",
    "candidate_metadata": "missing_candidate_metadata",
}

_SCHEMA_INCOMPAT_CODE = {
    "contracts": "contract_schema_incompatible",
    "manifest_input": "manifest_input_schema_incompatible",
    "metrics": "metrics_schema_incompatible",
    "model_card": "model_card_schema_incompatible",
    "candidate_metadata": "candidate_metadata_schema_incompatible",
}


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _rejection_reason(code: str, message: str, artifact_role: str | None = None) -> dict:
    r: dict = {"code": code, "message": message}
    if artifact_role is not None:
        r["artifact_role"] = artifact_role
    return r


def _load_operational_note(repo_root: Path) -> dict:
    note_path = repo_root / "publisher" / "release-candidate.operational-note.json"
    try:
        content = note_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "valid": False,
            "errors": [_err(
                "OPERATIONAL_NOTE_UNREADABLE",
                None,
                "publisher/release-candidate.operational-note.json could not be read.",
            )],
        }
    try:
        return {"valid": True, "data": json.loads(content)}
    except json.JSONDecodeError:
        return {
            "valid": False,
            "errors": [_err(
                "OPERATIONAL_NOTE_INVALID_JSON",
                None,
                "publisher/release-candidate.operational-note.json is not valid JSON.",
            )],
        }


def validate_candidate(candidate: dict, candidate_dir: Path) -> dict:
    """
    Validate a loaded release candidate dict.

    Returns a dict with keys: valid, errors, role_results,
    identifier_consistency, schema_compatibility, rejection_reasons,
    candidate_slug, release_id, release_version.

    Errors are deterministic and sanitized: no filesystem paths, secrets,
    or internal operational details in any message.
    """
    errors: list[dict] = []
    rejection_reasons: list[dict] = []

    if not isinstance(candidate, dict):
        errors.append(_err("CANDIDATE_NOT_AN_OBJECT", None, "Release candidate must be a JSON object."))
        return _empty_validation_result(errors, candidate_dir)

    schema_version = candidate.get("schema_version")
    if schema_version != "release-candidate.v1":
        errors.append(_err(
            "INVALID_CANDIDATE_SCHEMA_VERSION",
            "schema_version",
            "Candidate 'schema_version' must be 'release-candidate.v1'.",
        ))

    candidate_kind = candidate.get("candidate_kind")
    if candidate_kind != "release_candidate":
        errors.append(_err(
            "INVALID_CANDIDATE_KIND",
            "candidate_kind",
            "Candidate 'candidate_kind' must be 'release_candidate'.",
        ))

    dataset_identity = candidate.get("dataset_identity") or {}
    release_identity = candidate.get("release_identity") or {}
    artifact_roles_decl = candidate.get("artifact_roles") or {}

    dataset_slug = (
        dataset_identity.get("dataset_slug", "")
        if isinstance(dataset_identity, dict)
        else ""
    )
    release_id = (
        release_identity.get("release_id", "")
        if isinstance(release_identity, dict)
        else ""
    )
    release_version = (
        release_identity.get("release_version", "")
        if isinstance(release_identity, dict)
        else ""
    )

    # --- Artifact role presence ---
    role_results: dict[str, dict] = {}
    for role in _REQUIRED_ROLES:
        role_def = (
            artifact_roles_decl.get(role)
            if isinstance(artifact_roles_decl, dict)
            else None
        )
        if not isinstance(role_def, dict) or not role_def.get("path"):
            reason = _rejection_reason(
                _MISSING_ROLE_CODE.get(role, "missing_required_artifact"),
                f"Required artifact role '{role}' is not declared or has no path in the candidate.",
                role,
            )
            rejection_reasons.append(reason)
            role_results[role] = {
                "role": role,
                "status": "missing",
                "required": True,
                "artifact_reference": None,
                "reason": reason,
            }
            continue

        role_path_str: str = role_def["path"]
        artifact_file = candidate_dir / role_path_str
        if not artifact_file.is_file():
            reason = _rejection_reason(
                _MISSING_ROLE_CODE.get(role, "missing_required_artifact"),
                f"Required artifact role '{role}' file is not present in the candidate directory.",
                role,
            )
            rejection_reasons.append(reason)
            role_results[role] = {
                "role": role,
                "status": "missing",
                "required": True,
                "artifact_reference": None,
                "reason": reason,
            }
        else:
            role_results[role] = {
                "role": role,
                "status": "present",
                "required": True,
                "artifact_reference": role_path_str,
            }

    # --- Identifier consistency ---
    dir_release_id = candidate_dir.name
    dir_dataset_slug = candidate_dir.parent.name

    dataset_id_consistent = bool(dataset_slug) and dataset_slug == dir_dataset_slug
    release_id_consistent = bool(release_id) and release_id == dir_release_id

    id_mismatch_reasons: list[dict] = []
    if not dataset_id_consistent:
        r = _rejection_reason(
            "dataset_identifier_mismatch",
            "Candidate dataset_slug does not match the candidate directory path segment.",
        )
        id_mismatch_reasons.append(r)
        rejection_reasons.append(r)
    if not release_id_consistent:
        r = _rejection_reason(
            "release_identifier_mismatch",
            "Candidate release_id does not match the candidate directory path segment.",
        )
        id_mismatch_reasons.append(r)
        rejection_reasons.append(r)

    identifier_consistency: dict = {
        "dataset_identifier_consistent": dataset_id_consistent,
        "release_identifier_consistent": release_id_consistent,
        "checked_sources": [
            "release_candidate.dataset_identity",
            "release_candidate.release_identity",
        ],
    }
    if id_mismatch_reasons:
        identifier_consistency["mismatch_reasons"] = id_mismatch_reasons

    # --- Schema compatibility (JSON validity, 5 roles) ---
    schema_compatibility: dict[str, dict] = {}
    for role in ("contracts", "manifest_input", "metrics", "model_card", "candidate_metadata"):
        rr = role_results.get(role, {})
        if rr.get("status") != "present":
            schema_compatibility[role] = {"checked": False, "compatible": False}
            continue

        artifact_ref = rr.get("artifact_reference", "")
        artifact_file = candidate_dir / artifact_ref
        try:
            raw = artifact_file.read_text(encoding="utf-8").strip()
            if not raw:
                raise ValueError("empty file")
            json.loads(raw)
            schema_compatibility[role] = {"checked": True, "compatible": True}
        except (OSError, ValueError, json.JSONDecodeError):
            incompat_code = _SCHEMA_INCOMPAT_CODE.get(role, "contract_schema_incompatible")
            reason = _rejection_reason(
                incompat_code,
                f"Artifact file for role '{role}' is not parseable as valid non-empty JSON.",
                role,
            )
            rejection_reasons.append(reason)
            schema_compatibility[role] = {
                "checked": True,
                "compatible": False,
                "reason": reason,
            }

    return {
        "valid": len(rejection_reasons) == 0 and len(errors) == 0,
        "errors": errors,
        "role_results": role_results,
        "identifier_consistency": identifier_consistency,
        "schema_compatibility": schema_compatibility,
        "rejection_reasons": rejection_reasons,
        "candidate_slug": dataset_slug,
        "release_id": release_id,
        "release_version": release_version,
    }


def _empty_validation_result(errors: list[dict], candidate_dir: Path) -> dict:
    """Return a minimal failed validation result when the candidate object is unusable."""
    dir_release_id = candidate_dir.name
    dir_dataset_slug = candidate_dir.parent.name
    return {
        "valid": False,
        "errors": errors,
        "role_results": {},
        "identifier_consistency": {
            "dataset_identifier_consistent": False,
            "release_identifier_consistent": False,
            "checked_sources": [
                "release_candidate.dataset_identity",
                "release_candidate.release_identity",
            ],
            "mismatch_reasons": [
                _rejection_reason(
                    "dataset_identifier_mismatch",
                    "Candidate could not be loaded; dataset identity unverifiable.",
                ),
                _rejection_reason(
                    "release_identifier_mismatch",
                    "Candidate could not be loaded; release identity unverifiable.",
                ),
            ],
        },
        "schema_compatibility": {
            role: {"checked": False, "compatible": False}
            for role in ("contracts", "manifest_input", "metrics", "model_card", "candidate_metadata")
        },
        "rejection_reasons": [
            _rejection_reason(
                "missing_required_artifact",
                "Candidate JSON could not be loaded; all checks failed.",
            )
        ],
        "candidate_slug": dir_dataset_slug,
        "release_id": dir_release_id,
        "release_version": "",
    }


def validate_candidate_file(candidate_dir: Path) -> dict:
    """Load the release candidate JSON from a candidate directory and validate it."""
    candidate_json_path = candidate_dir / _CANDIDATE_FILENAME
    try:
        content = candidate_json_path.read_text(encoding="utf-8")
    except OSError:
        return _empty_validation_result(
            [_err(
                "CANDIDATE_FILE_UNREADABLE",
                None,
                f"Candidate JSON file '{_CANDIDATE_FILENAME}' could not be read from the candidate directory.",
            )],
            candidate_dir,
        )
    try:
        candidate = json.loads(content)
    except json.JSONDecodeError:
        return _empty_validation_result(
            [_err(
                "CANDIDATE_INVALID_JSON",
                None,
                f"Candidate JSON file '{_CANDIDATE_FILENAME}' is not valid JSON.",
            )],
            candidate_dir,
        )
    return validate_candidate(candidate, candidate_dir)


def _build_validation_result(validation: dict) -> dict:
    """Construct the validation result conforming to release-candidate-validation.schema.json."""
    all_pass = validation["valid"]
    rejection_reasons: list[dict] = validation.get("rejection_reasons", [])
    role_results: dict = validation.get("role_results", {})
    identifier_consistency: dict = validation.get("identifier_consistency", {})
    schema_compatibility: dict = validation.get("schema_compatibility", {})

    dataset_slug: str = validation.get("candidate_slug", "")
    release_id: str = validation.get("release_id", "")
    release_version: str = validation.get("release_version", "")

    required_artifact_role_results: dict = {}
    for role in _REQUIRED_ROLES:
        if role in role_results:
            required_artifact_role_results[role] = role_results[role]
        else:
            required_artifact_role_results[role] = {
                "role": role,
                "status": "missing",
                "required": True,
                "artifact_reference": None,
            }

    for role in ("contracts", "manifest_input", "metrics", "model_card", "candidate_metadata"):
        if role not in schema_compatibility:
            schema_compatibility[role] = {"checked": False, "compatible": False}

    if all_pass:
        validation_outcome = "accepted"
        rejection_obj: dict = {"rejected": False, "reasons": []}
        promotion_gate: dict = {"promotion_allowed": True, "registry_update_allowed": True}
    else:
        validation_outcome = "rejected"
        rejection_obj = {"rejected": True, "reasons": rejection_reasons}
        promotion_gate = {"promotion_allowed": False, "registry_update_allowed": False}

    if not identifier_consistency.get("checked_sources"):
        identifier_consistency["checked_sources"] = [
            "release_candidate.dataset_identity",
            "release_candidate.release_identity",
        ]

    return {
        "schema_version": "release-candidate-validation.v1",
        "validation_kind": "release_candidate_completeness",
        "candidate_identity": {
            "dataset_slug": dataset_slug or "unknown",
            "release_id": release_id or "unknown",
            "release_version": release_version or "unknown",
        },
        "source_candidate": {
            "schema_version": "release-candidate.v1",
            "candidate_kind": "release_candidate",
            "required_artifact_roles_observed": list(_REQUIRED_ROLES),
            "candidate_reference": f"release-candidate-v1:{dataset_slug}/{release_id}",
        },
        "validation_outcome": validation_outcome,
        "required_artifact_role_results": required_artifact_role_results,
        "identifier_consistency": identifier_consistency,
        "schema_compatibility": schema_compatibility,
        "rejection": rejection_obj,
        "promotion_gate": promotion_gate,
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "sensitive_local_paths_persisted": False,
            "raw_file_contents_persisted": False,
        },
        "publisher_boundaries": {
            "training_executed": False,
            "notebooks_executed": False,
            "artifacts_regenerated": False,
            "candidate_rebuilt": False,
            "runtime_payload_validation_performed": False,
            "public_api_errors_implemented": False,
            "public_endpoint_exposed": False,
            "release_promoted": False,
            "registry_updated": False,
        },
    }


def run(candidate_dir_path: str, repo_root: Path | None = None) -> dict:
    """
    Validate a release candidate directory and write the result.

    Reads publisher/release-candidate.operational-note.json at runtime
    to confirm the candidate directory convention. The caller supplies the
    full candidate directory path — no path inference is performed here.

    Returns the validation result dict.
    Raises RuntimeError if the operational note cannot be loaded.
    Raises ValueError if the candidate directory does not exist.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent

    note_result = _load_operational_note(repo_root)
    if not note_result["valid"]:
        raise RuntimeError(
            "Cannot load publisher/release-candidate.operational-note.json: "
            + "; ".join(e["message"] for e in note_result["errors"])
        )

    note = note_result["data"]
    convention = note.get("candidate_directory_convention") or {}
    if not convention.get("pattern"):
        raise RuntimeError(
            "publisher/release-candidate.operational-note.json is missing "
            "candidate_directory_convention.pattern."
        )

    candidate_dir = Path(candidate_dir_path).resolve()
    if not candidate_dir.is_dir():
        raise ValueError("Candidate directory does not exist or is not a directory.")

    validation = validate_candidate_file(candidate_dir)
    result = _build_validation_result(validation)

    run_id = "validate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs_dir = repo_root / "publisher" / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    result_path = runs_dir / "validation-result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    return result


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m publisher.validate <candidate-directory>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = run(sys.argv[1])
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    outcome = result.get("validation_outcome", "unknown")
    allowed = result.get("promotion_gate", {}).get("promotion_allowed", False)
    print(f"validation_outcome: {outcome}")
    print(f"promotion_gate.promotion_allowed: {allowed}")
    sys.exit(0 if outcome == "accepted" else 1)


if __name__ == "__main__":
    main()
