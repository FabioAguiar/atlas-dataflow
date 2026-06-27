"""
Publisher release candidate consistency validator.

Reads a candidate directory path, loads the release candidate JSON,
validates it structurally, checks artifact role file presence,
validates identifier consistency, checks declared hashes when present,
checks reduced cross-artifact references, checks public projection safety,
and writes a conformant validation result to
publisher/runs/{run_id}/validation-result.json.

Does NOT read or modify registry/datasets.json.
Does NOT modify any candidate artifact.
"""

import hashlib
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

_JSON_COMPAT_ROLES = (
    "contracts",
    "predictive_bundle",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)

_PUBLIC_ROLES = frozenset({
    "metrics",
    "model_card",
    "public_context",
})

_UNSAFE_PUBLIC_KEYS = frozenset({
    "internal_evidence",
    "internal_evidence_references",
    "private_source_path",
    "raw_api_payload",
    "raw_api_payloads",
    "raw_logs",
    "raw_runtime",
    "runtime_dump",
    "secret",
    "secrets",
    "unsafe_payload",
})

def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _rejection_reason(code: str, message: str, artifact_role: str | None = None) -> dict:
    r: dict = {"code": code, "message": message}
    if artifact_role is not None:
        r["artifact_role"] = artifact_role
    return r


def _safe_rejection_reason(
    code: str,
    message: str,
    artifact_role: str | None = None,
    safe_detail: str | None = None,
) -> dict:
    reason = _rejection_reason(code, message, artifact_role)
    if safe_detail:
        reason["safe_detail"] = safe_detail
    return reason


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _load_json_if_possible(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_nested(data: dict, paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if isinstance(current, str) and current:
            return current
    return None


def _artifact_declares_non_real(data: dict) -> str | None:
    availability = data.get("availability_status")
    if availability in {"fixture_only", "placeholder_only"}:
        return availability

    if data.get("fixture") is True or data.get("fixture_only") is True:
        return "fixture_only"
    if data.get("placeholder") is True or data.get("placeholder_only") is True:
        return "placeholder_only"

    policy = data.get("placeholder_policy")
    if isinstance(policy, dict):
        if policy.get("fixtures_allowed") is True:
            return "fixture_only"
        if policy.get("placeholders_allowed") is True:
            return "placeholder_only"

    return None


def _has_unsafe_public_projection(data: dict) -> bool:
    for item in _walk_dicts(data):
        if _UNSAFE_PUBLIC_KEYS.intersection(item):
            return True
    return False


def _identity_value(data: dict, identity_key: str) -> str | None:
    return _first_nested(
        data,
        (
            ("dataset_identity", identity_key),
            ("release_identity", identity_key),
            ("candidate_identity", identity_key),
            ("source_input", identity_key),
            ("bundle_identity", identity_key),
            ("model_identity", identity_key),
            (identity_key,),
        ),
    )


def _reference_value(data: dict, reference_key: str) -> str | None:
    return _first_nested(
        data,
        (
            ("references", reference_key),
            ("artifact_references", reference_key),
            ("source_references", reference_key),
            ("training_evidence", reference_key),
            ("model_metadata", reference_key),
            ("model_identity", reference_key),
            ("bundle_identity", reference_key),
            (reference_key,),
        ),
    )


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
    hash_policy = ""
    candidate_metadata = candidate.get("candidate_metadata")
    if isinstance(candidate_metadata, dict):
        completeness = candidate_metadata.get("completeness_validation")
        if isinstance(completeness, dict):
            hash_policy = completeness.get("hash_policy", "")

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
            declared_sha256 = role_def.get("sha256")
            actual_sha256 = _sha256_file(artifact_file)
            role_results[role] = {
                "role": role,
                "status": "present",
                "required": True,
                "artifact_reference": role_path_str,
                "declared_sha256_present": isinstance(declared_sha256, str),
            }
            if isinstance(declared_sha256, str) and declared_sha256 != actual_sha256:
                reason = _safe_rejection_reason(
                    "hash_mismatch",
                    "Declared artifact hash does not match the candidate artifact.",
                    role,
                    "sha256_mismatch",
                )
                rejection_reasons.append(reason)
                role_results[role]["status"] = "contradictory"
                role_results[role]["reason"] = reason
            elif (
                hash_policy == "publisher_verifies_declared_hashes"
                and not isinstance(declared_sha256, str)
            ):
                reason = _safe_rejection_reason(
                    "declared_hash_missing",
                    "Candidate hash policy requires declared artifact hashes.",
                    role,
                    "declared_sha256_missing",
                )
                rejection_reasons.append(reason)
                role_results[role]["status"] = "incomplete"
                role_results[role]["reason"] = reason

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

    json_artifacts: dict[str, dict] = {}
    for role in _JSON_COMPAT_ROLES:
        rr = role_results.get(role, {})
        if rr.get("status") not in {"present", "contradictory", "unsafe", "incomplete"}:
            continue
        artifact_ref = rr.get("artifact_reference")
        if not isinstance(artifact_ref, str):
            continue
        data = _load_json_if_possible(candidate_dir / artifact_ref)
        if data is not None:
            json_artifacts[role] = data

    cross_artifact_consistency = _validate_cross_artifact_consistency(
        candidate,
        json_artifacts,
        role_results,
    )
    rejection_reasons.extend(cross_artifact_consistency["rejection_reasons"])

    return {
        "valid": len(rejection_reasons) == 0 and len(errors) == 0,
        "errors": errors,
        "role_results": role_results,
        "identifier_consistency": identifier_consistency,
        "schema_compatibility": schema_compatibility,
        "cross_artifact_consistency": cross_artifact_consistency["result"],
        "rejection_reasons": rejection_reasons,
        "candidate_slug": dataset_slug,
        "release_id": release_id,
        "release_version": release_version,
    }


def _validate_cross_artifact_consistency(
    candidate: dict,
    json_artifacts: dict[str, dict],
    role_results: dict[str, dict],
) -> dict:
    rejection_reasons: list[dict] = []
    candidate_dataset_slug = _identity_value(candidate, "dataset_slug")
    candidate_release_id = _identity_value(candidate, "release_id")

    identity_checks: list[dict] = []
    for role, data in json_artifacts.items():
        dataset_slug = _identity_value(data, "dataset_slug")
        release_id = _identity_value(data, "release_id")
        if dataset_slug is not None:
            consistent = dataset_slug == candidate_dataset_slug
            identity_checks.append({
                "artifact_role": role,
                "identity": "dataset_slug",
                "consistent": consistent,
            })
            if not consistent:
                reason = _safe_rejection_reason(
                    "dataset_identifier_mismatch",
                    "Artifact dataset identity does not match the release candidate.",
                    role,
                    "dataset_slug_mismatch",
                )
                rejection_reasons.append(reason)
        if release_id is not None:
            consistent = release_id == candidate_release_id
            identity_checks.append({
                "artifact_role": role,
                "identity": "release_id",
                "consistent": consistent,
            })
            if not consistent:
                reason = _safe_rejection_reason(
                    "release_identifier_mismatch",
                    "Artifact release identity does not match the release candidate.",
                    role,
                    "release_id_mismatch",
                )
                rejection_reasons.append(reason)

    reference_checks: list[dict] = []
    runtime_contract_ref = _reference_value(
        json_artifacts.get("predictive_bundle", {}),
        "runtime_contract_ref",
    )
    model_card_model = _reference_value(json_artifacts.get("model_card", {}), "model_id")
    metrics_model = _reference_value(json_artifacts.get("metrics", {}), "model_id")
    bundle_model = _reference_value(json_artifacts.get("predictive_bundle", {}), "model_id")

    if runtime_contract_ref:
        reference_checks.append({
            "reference": "runtime_contract_ref",
            "artifact_role": "predictive_bundle",
            "consistent": bool(runtime_contract_ref),
        })
    if model_card_model and metrics_model:
        consistent = model_card_model == metrics_model
        reference_checks.append({
            "reference": "model_card_metrics_model_id",
            "artifact_role": "model_card",
            "consistent": consistent,
        })
        if not consistent:
            rejection_reasons.append(_safe_rejection_reason(
                "model_bundle_mismatch",
                "Model card and metrics model references do not match.",
                "model_card",
                "model_id_mismatch",
            ))
    if bundle_model and model_card_model:
        consistent = bundle_model == model_card_model
        reference_checks.append({
            "reference": "bundle_model_card_model_id",
            "artifact_role": "predictive_bundle",
            "consistent": consistent,
        })
        if not consistent:
            rejection_reasons.append(_safe_rejection_reason(
                "model_bundle_mismatch",
                "Inference bundle and model card model references do not match.",
                "predictive_bundle",
                "model_id_mismatch",
            ))

    public_projection_checks: list[dict] = []
    for role in sorted(_PUBLIC_ROLES):
        data = json_artifacts.get(role)
        if data is None:
            continue
        unsafe = _has_unsafe_public_projection(data)
        public_projection_checks.append({
            "artifact_role": role,
            "safe_for_public_projection": not unsafe,
        })
        if unsafe:
            reason = _safe_rejection_reason(
                "public_projection_unsafe",
                "Public artifact contains internal or unsafe projection fields.",
                role,
                "unsafe_public_projection",
            )
            rejection_reasons.append(reason)
            if role in role_results:
                role_results[role]["status"] = "unsafe"
                role_results[role]["reason"] = reason

    real_artifact_checks: list[dict] = []
    for role, data in json_artifacts.items():
        non_real = _artifact_declares_non_real(data)
        if non_real is None:
            continue
        reason_code = (
            "placeholder_only_artifact"
            if non_real == "placeholder_only"
            else "fixture_only_artifact"
        )
        reason = _safe_rejection_reason(
            reason_code,
            "Required artifact is not declared as a real dataflow artifact.",
            role,
            non_real,
        )
        rejection_reasons.append(reason)
        real_artifact_checks.append({
            "artifact_role": role,
            "real_dataflow_artifact": False,
            "reason_code": reason_code,
        })
        if role in role_results:
            role_results[role]["status"] = "incomplete"
            role_results[role]["reason"] = reason

    evidence_link_checks = []
    for role, data in json_artifacts.items():
        if "evidence_links" in data or "evidence_references" in data:
            unsafe = _has_unsafe_public_projection(data)
            evidence_link_checks.append({
                "artifact_role": role,
                "safe_evidence_links": not unsafe,
            })

    hash_checks = [
        {
            "artifact_role": role,
            "declared_sha256_present": bool(role_result.get("declared_sha256_present")),
            "status": role_result.get("status"),
        }
        for role, role_result in role_results.items()
    ]

    result = {
        "checked": True,
        "identity_checks": identity_checks,
        "hash_checks": hash_checks,
        "reference_checks": reference_checks,
        "public_projection_checks": public_projection_checks,
        "real_artifact_checks": real_artifact_checks,
        "evidence_link_checks": evidence_link_checks,
        "valid": not rejection_reasons and all(
            check["status"] == "present" for check in hash_checks
        ),
    }
    return {"result": result, "rejection_reasons": rejection_reasons}


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
        "cross_artifact_consistency": {
            "checked": False,
            "identity_checks": [],
            "hash_checks": [],
            "reference_checks": [],
            "public_projection_checks": [],
            "real_artifact_checks": [],
            "evidence_link_checks": [],
            "valid": False,
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
    cross_artifact_consistency: dict = validation.get("cross_artifact_consistency", {})

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
        "validation_kind": "release_candidate_cross_artifact_consistency",
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
        "cross_artifact_consistency": cross_artifact_consistency,
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
