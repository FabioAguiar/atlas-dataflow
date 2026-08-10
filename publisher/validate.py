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
_DEFAULT_REPO_ROOT = Path(__file__).parent.parent
_PUBLIC_CONTRACT_ROLE = "public_contract"
_MODEL_ARTIFACT_ROLE = "model_artifact"

_VISUALIZATIONS_ROLE = "visualizations"

_REQUIRED_ROLES = (
    "contracts",
    "public_contract",
    "predictive_bundle",
    "model_artifact",
    "metrics",
    "model_card",
    "public_context",
    "visualizations",
    "manifest_input",
    "candidate_metadata",
)

_SCHEMA_COMPAT_ROLES = frozenset({
    "contracts",
    "public_contract",
    "manifest_input",
    "metrics",
    "model_card",
    "visualizations",
    "candidate_metadata",
})

_MISSING_ROLE_CODE = {
    "contracts": "missing_runtime_contract",
    "public_contract": "missing_public_contract",
    "predictive_bundle": "missing_predictive_bundle",
    "model_artifact": "missing_model_artifact",
    "metrics": "missing_metrics",
    "model_card": "missing_model_card",
    "public_context": "missing_public_context",
    "visualizations": "missing_visualizations",
    "manifest_input": "missing_manifest_input",
    "candidate_metadata": "missing_candidate_metadata",
}

# Project Spec S0107: roles that need path-safety enforcement (absolute,
# traversal, or candidate-root-escaping references rejected) before the file
# is even looked up. public_contract already had this; model_artifact is a
# private binary and gets its own distinct rejection code. Project Spec
# S0128 extends this to visualizations.
_UNSAFE_REFERENCE_CODE = {
    _PUBLIC_CONTRACT_ROLE: "unsafe_candidate_artifact",
    _MODEL_ARTIFACT_ROLE: "unsafe_model_reference",
    _VISUALIZATIONS_ROLE: "unsafe_visualizations_reference",
}
_PATH_SAFETY_CHECKED_ROLES = frozenset(_UNSAFE_REFERENCE_CODE)

_SCHEMA_INCOMPAT_CODE = {
    "contracts": "contract_schema_incompatible",
    "public_contract": "public_contract_schema_incompatible",
    "manifest_input": "manifest_input_schema_incompatible",
    "metrics": "metrics_schema_incompatible",
    "model_card": "model_card_schema_incompatible",
    "visualizations": "visualizations_schema_incompatible",
    "candidate_metadata": "candidate_metadata_schema_incompatible",
}

_JSON_COMPAT_ROLES = (
    "contracts",
    "predictive_bundle",
    "metrics",
    "model_card",
    "public_context",
    "visualizations",
    "manifest_input",
    "candidate_metadata",
)

_PUBLIC_ROLES = frozenset({
    "metrics",
    "model_card",
    "public_context",
    "visualizations",
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
            # Project Spec S0128: analytical-visualizations.v1 (and every
            # other training-run-produced artifact) declares its dataset/run
            # identity under training_run_identity, not one of the identity
            # shapes above.
            ("training_run_identity", identity_key),
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


def _unsafe_candidate_reference(role_path_str: str, candidate_dir: Path) -> bool:
    """True when role_path_str is absolute, contains parent-traversal
    segments, or resolves outside candidate_dir. Mirrors
    publisher.manifest._unsafe_role_reference (Project Spec S0101): the
    public_contract role must be rejected at validation time, before
    promotion_gate can ever become true, not only later at manifest
    generation."""
    path = Path(role_path_str)
    if path.is_absolute() or ".." in path.parts:
        return True
    resolved = (candidate_dir / path).resolve()
    return not resolved.is_relative_to(candidate_dir.resolve())


def _public_contract_conforms_to_schema(data: dict, repo_root: Path) -> bool:
    """Validate a parsed public_contract artifact against the
    repository-authoritative contracts/public-contract.schema.json (Project
    Spec S0101). Fails closed on any missing schema, unreadable schema, or
    missing jsonschema dependency -- matching
    pipeline/contract_derivation.py's existing fail-safe convention for this
    same schema, rather than silently skipping the check."""
    try:
        import jsonschema
    except ImportError:
        return False
    schema = _load_json_if_possible(repo_root / "contracts" / "public-contract.schema.json")
    if schema is None:
        return False
    try:
        jsonschema.Draft7Validator(schema).validate(data)
    except (jsonschema.ValidationError, jsonschema.SchemaError):
        return False
    return True


def _visualizations_conforms_to_schema(data: dict, repo_root: Path) -> bool:
    """Validate a parsed visualizations artifact against the
    repository-authoritative pipeline/analytical-visualizations.schema.json
    (Project Spec S0128). Fails closed on any missing schema, unreadable
    schema, or missing jsonschema dependency, matching
    `_public_contract_conforms_to_schema`'s convention. Unlike that helper,
    this selects the JSON Schema validator declared by the schema's own
    `$schema` (draft 2020-12, which the public_contract schema does not use)
    instead of hardcoding Draft7Validator."""
    try:
        import jsonschema
    except ImportError:
        return False
    schema = _load_json_if_possible(
        repo_root / "pipeline" / "analytical-visualizations.schema.json"
    )
    if schema is None:
        return False
    try:
        validator_cls = jsonschema.validators.validator_for(
            schema, default=jsonschema.Draft202012Validator
        )
        validator_cls.check_schema(schema)
        validator_cls(schema).validate(data)
    except (jsonschema.ValidationError, jsonschema.SchemaError):
        return False
    return True


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


# ---------------------------------------------------------------------------
# Capability-conditional validation (Project Spec S0168)
#
# Separates universal release invariants (identity, integrity, hash
# coverage, artifact role uniqueness, relative-path safety, provenance, and
# schema/contract version validity -- all enforced by validate_candidate
# below regardless of capability) from capability-conditional invariants:
# whether a specific artifact role is required, optional, or forbidden for
# the capability profile governing this release. Absent
# candidate["capability_binding"], this check is a no-op and the existing
# binary predictive-classification validation below is completely
# unaffected -- historical candidates remain valid. Never infers a role's
# applicability from dataset_slug, an external project root, or a notebook
# execution: applicability comes only from the candidate's own
# capability_binding.resolved_role_policy, already resolved before
# publisher validation runs.
# ---------------------------------------------------------------------------

_CAPABILITY_DATASET_MISMATCH_CODE = "capability_dataset_identity_mismatch"
_CAPABILITY_FORBIDDEN_ROLE_CODE = "capability_forbidden_role_present"
_CAPABILITY_MISSING_REQUIRED_ROLE_CODE = "capability_missing_required_role"

_EMPTY_CAPABILITY_CONDITIONAL_VALIDATION = {
    "checked": False,
    "capability_gated": False,
    "valid": True,
    "rejection_reasons": [],
}


def validate_capability_conditional_roles(candidate: dict, role_results: dict) -> dict:
    """Validate a release candidate's capability-conditional artifact-role
    invariants, separate from the universal invariants enforced by
    `validate_candidate` below.

    Returns a dict with keys: checked, capability_gated, valid,
    rejection_reasons. When `candidate` has no `capability_binding`, this
    returns a pure pass-through (`checked=False, capability_gated=False,
    valid=True`) that never affects a historical candidate. Never reads a
    file, executes a notebook, or requires an external project root --
    both arguments are already-parsed/computed in-memory structures, and
    applicability is resolved entirely from
    `capability_binding.resolved_role_policy`, never from dataset_slug.
    """
    capability_binding = candidate.get("capability_binding")
    if not isinstance(capability_binding, dict):
        return dict(_EMPTY_CAPABILITY_CONDITIONAL_VALIDATION)

    rejection_reasons: list[dict] = []

    dataset_identity = candidate.get("dataset_identity")
    candidate_dataset_slug = (
        dataset_identity.get("dataset_slug") if isinstance(dataset_identity, dict) else None
    )
    if capability_binding.get("dataset_slug") != candidate_dataset_slug:
        rejection_reasons.append(_rejection_reason(
            _CAPABILITY_DATASET_MISMATCH_CODE,
            "capability_binding.dataset_slug does not match the release candidate's "
            "dataset_identity.dataset_slug.",
        ))

    declared_artifact_roles = candidate.get("artifact_roles")
    declared_role_names = (
        set(declared_artifact_roles) if isinstance(declared_artifact_roles, dict) else set()
    )

    for policy_entry in capability_binding.get("resolved_role_policy") or []:
        if not isinstance(policy_entry, dict):
            continue
        role_name = policy_entry.get("role_name")
        applicability = policy_entry.get("applicability")
        if not role_name:
            continue
        role_result = role_results.get(role_name)
        is_present = (
            role_result.get("status") == "present"
            if isinstance(role_result, dict)
            else role_name in declared_role_names
        )
        if applicability == "forbidden" and is_present:
            rejection_reasons.append(_rejection_reason(
                _CAPABILITY_FORBIDDEN_ROLE_CODE,
                f"Artifact role '{role_name}' is forbidden by the resolved capability "
                "policy but is present in the candidate.",
                role_name,
            ))
        elif applicability == "required" and not is_present:
            rejection_reasons.append(_rejection_reason(
                _CAPABILITY_MISSING_REQUIRED_ROLE_CODE,
                f"Artifact role '{role_name}' is required by the resolved capability "
                "policy but is not present in the candidate.",
                role_name,
            ))

    return {
        "checked": True,
        "capability_gated": True,
        "valid": not rejection_reasons,
        "rejection_reasons": rejection_reasons,
    }


def validate_candidate(candidate: dict, candidate_dir: Path, repo_root: Path | None = None) -> dict:
    """
    Validate a loaded release candidate dict.

    Returns a dict with keys: valid, errors, role_results,
    identifier_consistency, schema_compatibility, rejection_reasons,
    candidate_slug, release_id, release_version.

    Errors are deterministic and sanitized: no filesystem paths, secrets,
    or internal operational details in any message.

    repo_root defaults to the real repository root when not supplied. It is
    used only to locate contracts/public-contract.schema.json for the
    public_contract role's schema-compatibility check (Project Spec S0101).
    """
    resolved_repo_root = Path(repo_root) if repo_root is not None else _DEFAULT_REPO_ROOT
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
    model_role_actual_sha256: str | None = None
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

        if role in _PATH_SAFETY_CHECKED_ROLES and _unsafe_candidate_reference(role_path_str, candidate_dir):
            reason = _rejection_reason(
                _UNSAFE_REFERENCE_CODE[role],
                f"Required artifact role '{role}' has an unsafe reference.",
                role,
            )
            rejection_reasons.append(reason)
            role_results[role] = {
                "role": role,
                "status": "unsafe",
                "required": True,
                "artifact_reference": None,
                "reason": reason,
            }
            continue

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
            if role == _MODEL_ARTIFACT_ROLE:
                model_role_actual_sha256 = actual_sha256
            if role == _MODEL_ARTIFACT_ROLE and actual_sha256 is None:
                reason = _rejection_reason(
                    _MISSING_ROLE_CODE[_MODEL_ARTIFACT_ROLE],
                    f"Required artifact role '{role}' file could not be read.",
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

    # --- Schema compatibility (JSON validity, 7 roles; public_contract and
    # visualizations also get real JSON Schema validation below, not just
    # parseability) ---
    schema_compatibility: dict[str, dict] = {}
    for role in ("contracts", "public_contract", "manifest_input", "metrics", "model_card", "visualizations", "candidate_metadata"):
        rr = role_results.get(role, {})
        if rr.get("status") != "present":
            schema_compatibility[role] = {"checked": False, "compatible": False}
            continue

        artifact_ref = rr.get("artifact_reference", "")
        artifact_file = candidate_dir / artifact_ref
        incompat_code = _SCHEMA_INCOMPAT_CODE.get(role, "contract_schema_incompatible")
        try:
            raw = artifact_file.read_text(encoding="utf-8").strip()
            if not raw:
                raise ValueError("empty file")
            parsed_artifact = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
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
            continue

        if role == _PUBLIC_CONTRACT_ROLE and not isinstance(parsed_artifact, dict):
            parsed_artifact = None
        if role == _PUBLIC_CONTRACT_ROLE and (
            parsed_artifact is None
            or not _public_contract_conforms_to_schema(parsed_artifact, resolved_repo_root)
        ):
            reason = _rejection_reason(
                incompat_code,
                "Artifact for role 'public_contract' does not conform to the public contract schema.",
                role,
            )
            rejection_reasons.append(reason)
            schema_compatibility[role] = {
                "checked": True,
                "compatible": False,
                "reason": reason,
            }
            continue

        if role == _VISUALIZATIONS_ROLE and not isinstance(parsed_artifact, dict):
            parsed_artifact = None
        if role == _VISUALIZATIONS_ROLE and (
            parsed_artifact is None
            or not _visualizations_conforms_to_schema(parsed_artifact, resolved_repo_root)
        ):
            reason = _rejection_reason(
                incompat_code,
                "Artifact for role 'visualizations' does not conform to the "
                "analytical visualizations schema.",
                role,
            )
            rejection_reasons.append(reason)
            schema_compatibility[role] = {
                "checked": True,
                "compatible": False,
                "reason": reason,
            }
            continue

        schema_compatibility[role] = {"checked": True, "compatible": True}

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

    # --- Model artifact / predictive bundle cross-consistency (Project Spec
    # S0107). The model is binary and never JSON-parsed itself; only its
    # already-computed bytes hash and declared candidate path are
    # cross-checked against the JSON-parsed predictive_bundle's own
    # model_artifact.path/.sha256 declarations. ---
    model_role_result = role_results.get(_MODEL_ARTIFACT_ROLE)
    if model_role_result is not None and model_role_result.get("status") == "present":
        predictive_bundle_data = json_artifacts.get("predictive_bundle")
        bundle_model_artifact = (
            predictive_bundle_data.get("model_artifact")
            if isinstance(predictive_bundle_data, dict)
            else None
        )

        if not isinstance(bundle_model_artifact, dict) or not isinstance(
            bundle_model_artifact.get("path"), str
        ):
            reason = _safe_rejection_reason(
                "model_bundle_path_mismatch",
                "Predictive bundle does not declare a model_artifact.path reference.",
                _MODEL_ARTIFACT_ROLE,
                "bundle_model_artifact_path_missing",
            )
            rejection_reasons.append(reason)
            model_role_result["status"] = "contradictory"
            model_role_result["reason"] = reason
        elif bundle_model_artifact["path"] != model_role_result.get("artifact_reference"):
            reason = _safe_rejection_reason(
                "model_bundle_path_mismatch",
                "Predictive bundle model_artifact.path does not match the candidate model role path.",
                _MODEL_ARTIFACT_ROLE,
                "model_path_mismatch",
            )
            rejection_reasons.append(reason)
            model_role_result["status"] = "contradictory"
            model_role_result["reason"] = reason

        if not isinstance(bundle_model_artifact, dict) or not isinstance(
            bundle_model_artifact.get("sha256"), str
        ):
            reason = _safe_rejection_reason(
                "model_bundle_hash_mismatch",
                "Predictive bundle does not declare a model_artifact.sha256 reference.",
                _MODEL_ARTIFACT_ROLE,
                "bundle_model_artifact_sha256_missing",
            )
            rejection_reasons.append(reason)
            model_role_result["status"] = "contradictory"
            model_role_result["reason"] = reason
        elif bundle_model_artifact["sha256"] != model_role_actual_sha256:
            reason = _safe_rejection_reason(
                "model_bundle_hash_mismatch",
                "Predictive bundle model_artifact.sha256 does not match the candidate model bytes.",
                _MODEL_ARTIFACT_ROLE,
                "model_hash_mismatch",
            )
            rejection_reasons.append(reason)
            model_role_result["status"] = "contradictory"
            model_role_result["reason"] = reason

        model_delivery = candidate.get("model_delivery")
        if isinstance(candidate.get("capability_binding"), dict):
            if not isinstance(model_delivery, dict):
                reason = _rejection_reason(
                    "model_delivery_metadata_missing",
                    "Capability-aware predictive candidate lacks governed model delivery metadata.",
                    _MODEL_ARTIFACT_ROLE,
                )
                rejection_reasons.append(reason)
            else:
                checks = (
                    (
                        model_delivery.get("path"),
                        model_role_result.get("artifact_reference"),
                        "model_delivery_path_mismatch",
                    ),
                    (
                        model_delivery.get("sha256"),
                        model_role_actual_sha256,
                        "model_delivery_hash_mismatch",
                    ),
                    (
                        model_delivery.get("inference_bundle_id"),
                        (predictive_bundle_data or {})
                        .get("bundle_identity", {})
                        .get("bundle_id"),
                        "model_bundle_identity_mismatch",
                    ),
                )
                for declared, actual, code in checks:
                    if declared != actual:
                        reason = _rejection_reason(
                            code,
                            "Governed model delivery metadata is inconsistent with the "
                            "candidate bundle or model bytes.",
                            _MODEL_ARTIFACT_ROLE,
                        )
                        rejection_reasons.append(reason)
                        model_role_result["status"] = "contradictory"

    cross_artifact_consistency = _validate_cross_artifact_consistency(
        candidate,
        json_artifacts,
        role_results,
    )
    rejection_reasons.extend(cross_artifact_consistency["rejection_reasons"])

    capability_conditional_validation = validate_capability_conditional_roles(candidate, role_results)
    rejection_reasons.extend(capability_conditional_validation["rejection_reasons"])

    return {
        "valid": len(rejection_reasons) == 0 and len(errors) == 0,
        "errors": errors,
        "role_results": role_results,
        "identifier_consistency": identifier_consistency,
        "schema_compatibility": schema_compatibility,
        "cross_artifact_consistency": cross_artifact_consistency["result"],
        "capability_conditional_validation": capability_conditional_validation,
        "rejection_reasons": rejection_reasons,
        "candidate_slug": dataset_slug,
        "release_id": release_id,
        "release_version": release_version,
        "predictive_bundle_promotion_readiness": _predictive_bundle_promotion_readiness(
            json_artifacts.get("predictive_bundle")
        ),
    }


# Project Spec S0180: fail-closed promotion-eligibility signal extracted from
# the already-parsed predictive_bundle artifact (contracts/inference-bundle.schema.json,
# unmodified). Absent or malformed fields resolve to None, which
# _build_validation_result treats as "not the validated_external_fitted_model
# provenance" -- i.e. unchanged historical internal-training behavior --
# never as an implicit promotion grant.
def _predictive_bundle_promotion_readiness(predictive_bundle_data: dict | None) -> dict:
    if not isinstance(predictive_bundle_data, dict):
        return {
            "model_provenance_origin": None,
            "operational_validity": None,
            "operational_threshold_status": None,
            "operational_prediction_available": None,
        }
    provenance = predictive_bundle_data.get("model_provenance_origin")
    external_evidence = predictive_bundle_data.get("external_model_evidence")
    readiness = external_evidence.get("readiness") if isinstance(external_evidence, dict) else None
    operational_validity = readiness.get("operational_validity") if isinstance(readiness, dict) else None
    operational_threshold = readiness.get("operational_threshold") if isinstance(readiness, dict) else None
    operational_threshold_status = (
        operational_threshold.get("status") if isinstance(operational_threshold, dict) else None
    )
    operational_prediction_available = (
        readiness.get("operational_prediction_available") if isinstance(readiness, dict) else None
    )
    return {
        "model_provenance_origin": provenance if isinstance(provenance, str) else None,
        "operational_validity": (
            operational_validity if isinstance(operational_validity, str) else None
        ),
        "operational_threshold_status": (
            operational_threshold_status if isinstance(operational_threshold_status, str) else None
        ),
        "operational_prediction_available": (
            operational_prediction_available if isinstance(operational_prediction_available, bool) else None
        ),
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
            for role in ("contracts", "public_contract", "manifest_input", "metrics", "model_card", "visualizations", "candidate_metadata")
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
        "capability_conditional_validation": dict(_EMPTY_CAPABILITY_CONDITIONAL_VALIDATION),
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


def validate_candidate_file(candidate_dir: Path, repo_root: Path | None = None) -> dict:
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
    return validate_candidate(candidate, candidate_dir, repo_root=repo_root)


def _build_validation_result(validation: dict) -> dict:
    """Construct the validation result conforming to release-candidate-validation.schema.json."""
    all_pass = validation["valid"]
    rejection_reasons: list[dict] = validation.get("rejection_reasons", [])
    role_results: dict = validation.get("role_results", {})
    identifier_consistency: dict = validation.get("identifier_consistency", {})
    schema_compatibility: dict = validation.get("schema_compatibility", {})
    cross_artifact_consistency: dict = validation.get("cross_artifact_consistency", {})
    capability_conditional_validation: dict = validation.get(
        "capability_conditional_validation", dict(_EMPTY_CAPABILITY_CONDITIONAL_VALIDATION)
    )

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

    for role in ("contracts", "public_contract", "manifest_input", "metrics", "model_card", "visualizations", "candidate_metadata"):
        if role not in schema_compatibility:
            schema_compatibility[role] = {"checked": False, "compatible": False}

    predictive_bundle_promotion_readiness: dict = validation.get(
        "predictive_bundle_promotion_readiness"
    ) or {}

    if all_pass:
        validation_outcome = "accepted"
        rejection_obj: dict = {"rejected": False, "reasons": []}
        # Project Spec S0180: structural acceptance (validation_outcome) and
        # operational promotion eligibility are distinct contracts. A
        # structurally accepted candidate whose predictive bundle declares
        # model_provenance_origin: validated_external_fitted_model derives
        # promotion_gate fail-closed from the bundle's own operational
        # readiness -- never from validation_outcome alone. Every other
        # provenance (absent, or atlas_internal_training) keeps the
        # unchanged historical behavior: structural acceptance implies
        # promotion_allowed.
        if predictive_bundle_promotion_readiness.get("model_provenance_origin") == "validated_external_fitted_model":
            operationally_ready = (
                predictive_bundle_promotion_readiness.get("operational_validity") == "confirmed"
                and predictive_bundle_promotion_readiness.get("operational_threshold_status") == "resolved"
                and predictive_bundle_promotion_readiness.get("operational_prediction_available") is True
            )
            promotion_gate: dict = {
                "promotion_allowed": operationally_ready,
                "registry_update_allowed": operationally_ready,
            }
        else:
            promotion_gate = {"promotion_allowed": True, "registry_update_allowed": True}
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
        "capability_conditional_validation": capability_conditional_validation,
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

    validation = validate_candidate_file(candidate_dir, repo_root=repo_root)
    result = _build_validation_result(validation)

    run_id = "validate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs_dir = repo_root / "publisher" / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    result_path = runs_dir / "validation-result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    return result


_TELCO_DATASET_SLUG = "telco-customer-churn"
_CANDIDATE_STAGING_PREFIX = ("releases", "candidates")
_AMBIGUOUS_PATH_CHARS = frozenset("*?[]")


def _telco_validation_materialization_result(
    *,
    materialization_status: str,
    reason_code: str | None = None,
    message: str | None = None,
    run_id: str | None = None,
    run_dir: str | None = None,
    dataset_slug: str | None = None,
    release_id: str | None = None,
    validation_outcome: str | None = None,
    manifest_generated: bool = False,
    manifest_path: str | None = None,
    manifest_error: str | None = None,
) -> dict:
    return {
        "materialization_status": materialization_status,
        "reason_code": reason_code,
        "message": message,
        "run_id": run_id,
        "run_dir": run_dir,
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "validation_outcome": validation_outcome,
        "manifest_generated": manifest_generated,
        "manifest_path": manifest_path,
        "manifest_error": manifest_error,
        "boundary_confirmations": {
            "publisher_promotion_performed": False,
            "registry_activation_performed": False,
            "release_candidate_artifact_modified": False,
        },
    }


def materialize_telco_validation_run(
    release_candidate_assembly_result: dict | None = None,
    *,
    candidate_dir: str | Path | None = None,
    repo_root: Path | None = None,
) -> dict:
    """
    Materialize a publisher validation run (and manifest, when permitted)
    from an already-assembled Telco release candidate.

    Accepts exactly one candidate reference: either the dict returned by
    `pipeline.assemble_candidate.assemble_release_candidate` (the mode used
    by the Telco notebook, keyed off its own `status`/`candidate_dir`
    fields) or an explicit repository-relative candidate directory path
    string. Never infers a candidate from notebook memory, a glob over
    `releases/candidates/`, or any dataset other than
    `telco-customer-churn`. Calls the existing `run()` validation boundary
    above to write `validation-result.json`, then calls
    `publisher.manifest.run()` to write `manifest.json` in the same run
    directory only when `validation-result.json`'s own
    `promotion_gate.promotion_allowed` is `true`. Never promotes a release,
    never updates the registry, and never modifies any release-candidate
    artifact.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    resolved_repo_root = Path(repo_root).expanduser().resolve()

    if release_candidate_assembly_result is None and candidate_dir is None:
        return _telco_validation_materialization_result(
            materialization_status="blocked",
            reason_code="missing_candidate_reference",
            message="Provide either release_candidate_assembly_result or candidate_dir.",
        )
    if release_candidate_assembly_result is not None and candidate_dir is not None:
        return _telco_validation_materialization_result(
            materialization_status="blocked",
            reason_code="ambiguous_candidate_reference",
            message="Provide exactly one of release_candidate_assembly_result or candidate_dir, not both.",
        )

    if release_candidate_assembly_result is not None:
        if not isinstance(release_candidate_assembly_result, dict):
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="malformed_assembly_result",
                message="release_candidate_assembly_result must be a dict.",
            )
        if release_candidate_assembly_result.get("status") != "accepted":
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="release_candidate_assembly_not_accepted",
                message="Release-candidate assembly result status is not 'accepted'.",
            )
        dataset_slug = release_candidate_assembly_result.get("dataset_slug")
        if not isinstance(dataset_slug, str) or not dataset_slug:
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="malformed_assembly_result",
                message="release_candidate_assembly_result is missing dataset_slug.",
            )
        candidate_dir_value = release_candidate_assembly_result.get("candidate_dir")
        if not isinstance(candidate_dir_value, str) or not candidate_dir_value.strip():
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="missing_candidate_reference",
                message="release_candidate_assembly_result is missing candidate_dir.",
            )
        resolved_candidate_dir = Path(candidate_dir_value).resolve()
    else:
        if not isinstance(candidate_dir, (str, Path)) or not str(candidate_dir).strip():
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="missing_candidate_reference",
                message="candidate_dir must be a non-empty repository-relative path.",
            )
        candidate_dir_str = str(candidate_dir)
        if _AMBIGUOUS_PATH_CHARS.intersection(candidate_dir_str):
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="ambiguous_candidate_reference",
                message="candidate_dir must be a single explicit path, not a glob pattern.",
            )
        raw_path = Path(candidate_dir_str)
        if raw_path.is_absolute():
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="absolute_path_rejected",
                message="candidate_dir must be repository-relative, not absolute.",
            )
        if ".." in raw_path.parts:
            return _telco_validation_materialization_result(
                materialization_status="blocked",
                reason_code="parent_traversal_rejected",
                message="candidate_dir must not contain parent-directory traversal.",
            )
        resolved_candidate_dir = (resolved_repo_root / raw_path).resolve()
        dataset_slug = resolved_candidate_dir.parent.name

    staging_prefix = resolved_repo_root.joinpath(*_CANDIDATE_STAGING_PREFIX).resolve()
    if not resolved_candidate_dir.is_relative_to(staging_prefix):
        return _telco_validation_materialization_result(
            materialization_status="blocked",
            reason_code="unstable_candidate_reference",
            message="Candidate directory must resolve under releases/candidates/ in the repository.",
        )
    if dataset_slug != _TELCO_DATASET_SLUG:
        return _telco_validation_materialization_result(
            materialization_status="blocked",
            reason_code="non_telco_candidate_rejected",
            message=f"Candidate dataset_slug must be {_TELCO_DATASET_SLUG!r}.",
        )
    if not resolved_candidate_dir.is_dir():
        return _telco_validation_materialization_result(
            materialization_status="blocked",
            reason_code="candidate_directory_missing",
            message="Candidate directory does not exist.",
            dataset_slug=dataset_slug,
        )

    runs_root = resolved_repo_root / "publisher" / "runs"
    existing_run_dirs = (
        {p.name for p in runs_root.iterdir() if p.is_dir()} if runs_root.is_dir() else set()
    )

    validation_result = run(str(resolved_candidate_dir), repo_root=resolved_repo_root)

    new_run_dirs = sorted(
        p.name for p in runs_root.iterdir() if p.is_dir() and p.name not in existing_run_dirs
    )
    run_id = new_run_dirs[-1] if new_run_dirs else sorted(p.name for p in runs_root.iterdir() if p.is_dir())[-1]
    run_dir = runs_root / run_id

    manifest_path: str | None = None
    manifest_generated = False
    manifest_error: str | None = None
    # Project Spec S0180: manifest generation follows the generic structural
    # rule (validation_outcome accepted -> manifest may be generated), not
    # promotion eligibility -- a structurally accepted candidate can have
    # promotion_gate.promotion_allowed: false (e.g. an external fitted-model
    # candidate with unresolved operational readiness) and still get a
    # manifest.
    if validation_result.get("validation_outcome") == "accepted":
        from publisher import manifest as manifest_module  # local import: avoid a package-level cross-module dependency

        try:
            manifest_module.run(str(run_dir), repo_root=resolved_repo_root)
        except RuntimeError as exc:
            manifest_error = str(exc)
        else:
            manifest_path = str((run_dir / "manifest.json").relative_to(resolved_repo_root))
            manifest_generated = True

    return _telco_validation_materialization_result(
        materialization_status="materialized",
        run_id=run_id,
        run_dir=str(run_dir.relative_to(resolved_repo_root)),
        dataset_slug=dataset_slug,
        release_id=(validation_result.get("candidate_identity") or {}).get("release_id"),
        validation_outcome=validation_result.get("validation_outcome"),
        manifest_generated=manifest_generated,
        manifest_path=manifest_path,
        manifest_error=manifest_error,
    )


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
