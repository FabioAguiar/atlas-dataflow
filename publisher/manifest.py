"""
Publisher release manifest generator.

Reads a validation result from publisher/runs/{run_id}/validation-result.json,
gates on validation_outcome: accepted (Project Spec S0180 -- structural
acceptance, independent of operational promotion eligibility), calculates
SHA-256 hashes for all required artifact role files in the validated
release candidate (9 or 10, depending on provenance -- Project Spec S0188),
assembles a release manifest conforming to
publisher/release-manifest.schema.json, and writes it to
publisher/runs/{run_id}/manifest.json (same run directory).

Does NOT read or modify registry/datasets.json.
Does NOT modify any candidate artifact.
Does NOT write to releases/{release_id}/.
Does NOT generate a new run_id.
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_CANDIDATE_FILENAME = "release-candidate.json"

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

# Project Spec S0188: mandatory in every manifest regardless of provenance.
# visualizations is packaged when the already-validated candidate legitimately
# declares it (any provenance) and cleanly omitted when it does not -- this
# module trusts publisher.validate's prior structural acceptance rather than
# re-deriving provenance itself.
_ALWAYS_REQUIRED_ROLES = tuple(role for role in _REQUIRED_ROLES if role != "visualizations")
_OPTIONAL_ROLES = ("visualizations",)


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _load_json_file(path: Path, label: str) -> tuple:
    """Load a JSON file. Returns (data, errors) where data is None on failure."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None, [_err(f"{label.upper()}_UNREADABLE", None, f"{label} could not be read.")]
    try:
        return json.loads(content), []
    except json.JSONDecodeError:
        return None, [_err(f"{label.upper()}_INVALID_JSON", None, f"{label} is not valid JSON.")]


def _load_operational_note(repo_root: Path) -> tuple:
    note_path = repo_root / "publisher" / "release-candidate.operational-note.json"
    return _load_json_file(note_path, "operational_note")


def _check_promotion_gate(validation_result: dict) -> tuple:
    """Return (allowed, errors). Halts if validation_outcome is not 'accepted'
    (Project Spec S0180: structural acceptance, not operational promotion
    eligibility, gates manifest generation -- a structurally accepted
    candidate may still have promotion_gate.promotion_allowed: false, e.g. an
    external fitted-model candidate with unresolved operational readiness,
    and manifest generation must still succeed for it)."""
    outcome = validation_result.get("validation_outcome")
    if outcome != "accepted":
        return False, [_err(
            "VALIDATION_NOT_ACCEPTED",
            "validation_outcome",
            "Manifest generation halted: validation_outcome is not 'accepted'.",
        )]
    pg = validation_result.get("promotion_gate")
    if not isinstance(pg, dict):
        return False, [_err(
            "PROMOTION_GATE_MISSING",
            "promotion_gate",
            "Validation result is missing the 'promotion_gate' field.",
        )]
    return True, []


def _resolve_candidate_dir(validation_result: dict, repo_root: Path, note: dict) -> tuple:
    """Resolve the candidate directory using the validation result and operational note."""
    candidate_identity = validation_result.get("candidate_identity") or {}
    dataset_slug = candidate_identity.get("dataset_slug", "")
    release_id = candidate_identity.get("release_id", "")

    if not dataset_slug or not release_id:
        return None, [_err(
            "CANDIDATE_IDENTITY_MISSING",
            "candidate_identity",
            "Validation result candidate_identity is missing dataset_slug or release_id.",
        )]

    convention = note.get("candidate_directory_convention") or {}
    pattern = convention.get("pattern", "releases/candidates/{dataset_slug}/{release_id}/")
    candidate_dir_rel = (
        pattern
        .replace("{dataset_slug}", dataset_slug)
        .replace("{release_id}", release_id)
        .rstrip("/")
    )
    candidate_dir = repo_root / candidate_dir_rel

    if not candidate_dir.is_dir():
        return None, [_err(
            "CANDIDATE_DIR_NOT_FOUND",
            None,
            "Release candidate directory could not be located.",
        )]
    return candidate_dir, []


def _sha256_file(path: Path) -> tuple:
    """Compute SHA-256 hash of a file. Returns (hex_digest, errors)."""
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest(), []
    except OSError:
        return None, [_err(
            "ARTIFACT_FILE_UNREADABLE",
            None,
            "An artifact role file could not be read during hash calculation.",
        )]


def _unsafe_role_reference(role_path_str: str, candidate_dir: Path) -> bool:
    """True when role_path_str is absolute, contains parent-traversal
    segments, or resolves outside candidate_dir (Project Spec S0099)."""
    path = Path(role_path_str)
    if path.is_absolute() or ".." in path.parts:
        return True
    resolved = (candidate_dir / path).resolve()
    return not resolved.is_relative_to(candidate_dir.resolve())


def _hash_role_artifact(role: str, role_def: Any, candidate_dir: Path) -> tuple:
    """Return (artifact_entry, errors) for one declared artifact role.

    Returns (None, []) when role_def has no path (caller decides whether
    that is an error, for a mandatory role, or a legitimate omission, for
    an optional role -- Project Spec S0188)."""
    if not isinstance(role_def, dict) or not role_def.get("path"):
        return None, []

    role_path_str: str = role_def["path"]

    if _unsafe_role_reference(role_path_str, candidate_dir):
        return None, [_err(
            "ARTIFACT_ROLE_UNSAFE_REFERENCE",
            f"artifact_roles.{role}.path",
            f"Artifact role '{role}' has an unsafe reference.",
        )]

    artifact_file = candidate_dir / role_path_str

    hash_value, hash_errors = _sha256_file(artifact_file)
    if hash_errors:
        return None, hash_errors

    return {
        "role": role,
        "reference": role_path_str,
        "hash_algorithm": "sha256",
        "hash_value": hash_value,
    }, []


def generate_manifest(candidate_dir: Path) -> tuple:
    """
    Generate a release manifest from a validated candidate directory.

    Returns (manifest, errors). Halts without writing if any mandatory
    artifact file is missing/unreadable during hash calculation, or if any
    role reference is unsafe (Project Spec S0099 -- enforces the manifest's
    own long-declared but previously unenforced
    validation_policy.unsafe_reference_rejects). Project Spec S0188:
    `visualizations` is hashed and included when the already-validated
    candidate declares it, and cleanly omitted -- never an error -- when it
    does not; every other role remains mandatory.

    Project Spec S0190: manifest generation no longer injects a run-owned
    `operational_readiness` supplemental artifact -- the Project Spec S0189
    governed operational-readiness decision gate has been retired.
    """
    candidate_json_path = candidate_dir / _CANDIDATE_FILENAME
    candidate, errors = _load_json_file(candidate_json_path, "candidate_json")
    if errors:
        return None, errors

    if not isinstance(candidate, dict):
        return None, [_err(
            "CANDIDATE_NOT_AN_OBJECT",
            None,
            "Release candidate must be a JSON object.",
        )]

    dataset_identity_raw = candidate.get("dataset_identity") or {}
    release_identity_raw = candidate.get("release_identity") or {}
    artifact_roles = candidate.get("artifact_roles") or {}

    dataset_slug = dataset_identity_raw.get("dataset_slug", "")
    dataset_title = dataset_identity_raw.get("dataset_title")
    release_id = release_identity_raw.get("release_id", "")
    release_version = release_identity_raw.get("release_version", "")
    candidate_created_at = release_identity_raw.get("created_at")

    artifacts = []
    for role in _ALWAYS_REQUIRED_ROLES:
        role_def = artifact_roles.get(role)
        if not isinstance(role_def, dict) or not role_def.get("path"):
            return None, [_err(
                "ARTIFACT_ROLE_PATH_MISSING",
                f"artifact_roles.{role}.path",
                f"Artifact role '{role}' has no path in the candidate.",
            )]
        entry, entry_errors = _hash_role_artifact(role, role_def, candidate_dir)
        if entry_errors:
            return None, entry_errors
        artifacts.append(entry)

    for role in _OPTIONAL_ROLES:
        entry, entry_errors = _hash_role_artifact(role, artifact_roles.get(role), candidate_dir)
        if entry_errors:
            return None, entry_errors
        if entry is not None:
            artifacts.append(entry)

    # required_hash_coverage.required_artifact_roles is the fixed 9-10-role
    # vocabulary only.
    required_hash_coverage_roles = [a["role"] for a in artifacts]

    dataset_identity: dict = {"dataset_slug": dataset_slug}
    if dataset_title:
        dataset_identity["dataset_title"] = dataset_title

    release_identity: dict = {"release_id": release_id, "release_version": release_version}
    if candidate_created_at:
        release_identity["created_at"] = candidate_created_at

    manifest = {
        "schema_version": "release-manifest.v1",
        "manifest_kind": "release_manifest",
        "dataset_identity": dataset_identity,
        "release_identity": release_identity,
        "artifacts": artifacts,
        "required_hash_coverage": {
            "hash_algorithm": "sha256",
            "required_artifact_roles": required_hash_coverage_roles,
            "missing_required_hashes_reject_manifest": True,
        },
        "validation_policy": {
            "missing_schema_version_rejects": True,
            "missing_required_hash_rejects": True,
            "dataset_identity_mismatch_rejects": True,
            "release_identity_mismatch_rejects": True,
            "unsafe_reference_rejects": True,
        },
        "safety_boundaries": {
            "raw_artifact_contents_embedded": False,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "sensitive_local_paths_persisted": False,
            "unstable_temporary_paths_persisted": False,
            "hash_calculation_implemented": False,
            "signing_or_key_management_implemented": False,
            "storage_migration_implemented": False,
            "runtime_loading_implemented": False,
            "public_endpoint_exposed": False,
            "release_promoted": False,
            "registry_updated": False,
            "github_publication_performed": False,
        },
    }

    return manifest, []


def verify(manifest_path: Path, candidate_dir: Path) -> tuple:
    """
    Verify that the SHA-256 hash of each artifact entry in an existing manifest
    matches the corresponding file under candidate_dir.

    Returns (valid, errors). valid is True only when all artifact files are
    readable and every declared hash matches the computed hash.
    """
    manifest_data, load_errors = _load_json_file(manifest_path, "manifest")
    if load_errors:
        return False, load_errors

    if not isinstance(manifest_data, dict):
        return False, [_err("MANIFEST_NOT_AN_OBJECT", None, "Manifest must be a JSON object.")]

    artifacts = manifest_data.get("artifacts") or []
    if not artifacts:
        return False, [_err("MANIFEST_NO_ARTIFACTS", "artifacts", "Manifest contains no artifact entries.")]

    errors = []
    for entry in artifacts:
        role = entry.get("role", "<unknown>")
        reference = entry.get("reference")
        expected_hash = entry.get("hash_value")

        if not reference:
            errors.append(_err(
                "ARTIFACT_REFERENCE_MISSING",
                f"artifacts[{role}].reference",
                f"Artifact entry for role '{role}' is missing a reference.",
            ))
            continue

        artifact_file = candidate_dir / reference
        actual_hash, hash_errors = _sha256_file(artifact_file)
        if hash_errors:
            errors.extend(hash_errors)
            continue

        if actual_hash != expected_hash:
            errors.append(_err(
                "MANIFEST_HASH_MISMATCH",
                f"artifacts[{role}].hash_value",
                f"Hash mismatch for role '{role}': manifest declares {expected_hash!r},"
                f" file computes to {actual_hash!r}.",
            ))

    return len(errors) == 0, errors


def _validate_manifest_schema(manifest: dict, schema_path: Path) -> list:
    """Validate manifest against publisher/release-manifest.schema.json."""
    try:
        import jsonschema
    except ImportError:
        return []

    schema_data, errors = _load_json_file(schema_path, "manifest_schema")
    if errors:
        return errors

    try:
        jsonschema.validate(manifest, schema_data)
        return []
    except jsonschema.ValidationError as exc:
        return [_err(
            "MANIFEST_SCHEMA_INVALID",
            None,
            f"Generated manifest failed schema validation: {exc.message}",
        )]


def run(result_path_or_run_dir: str, repo_root: Path | None = None) -> dict:
    """
    Generate a release manifest and write it to the validation run directory.

    Accepts either the validation result JSON path or the run directory path.
    Reads the operational note at runtime to resolve the candidate directory.
    Returns the manifest dict.
    Raises RuntimeError on gate failure or any unrecoverable error.
    Raises ValueError if the input path does not exist.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent

    input_path = Path(result_path_or_run_dir).resolve()
    if input_path.is_file():
        run_dir = input_path.parent
    elif input_path.is_dir():
        run_dir = input_path
    else:
        raise ValueError(f"Input path does not exist: {result_path_or_run_dir}")

    validation_result, errors = _load_json_file(run_dir / "validation-result.json", "validation_result")
    if errors:
        raise RuntimeError(
            "Cannot load validation result: "
            + "; ".join(e["message"] for e in errors)
        )

    allowed, gate_errors = _check_promotion_gate(validation_result)
    if not allowed:
        raise RuntimeError("; ".join(e["message"] for e in gate_errors))

    note, note_errors = _load_operational_note(repo_root)
    if note_errors:
        raise RuntimeError(
            "Cannot load operational note: "
            + "; ".join(e["message"] for e in note_errors)
        )

    candidate_dir, cd_errors = _resolve_candidate_dir(validation_result, repo_root, note)
    if cd_errors:
        raise RuntimeError(
            "Cannot resolve candidate directory: "
            + "; ".join(e["message"] for e in cd_errors)
        )

    manifest, gen_errors = generate_manifest(candidate_dir)
    if gen_errors:
        raise RuntimeError(
            "Manifest generation failed: "
            + "; ".join(e["message"] for e in gen_errors)
        )

    schema_path = repo_root / "publisher" / "release-manifest.schema.json"
    schema_errors = _validate_manifest_schema(manifest, schema_path)
    if schema_errors:
        raise RuntimeError(
            "Generated manifest failed schema validation: "
            + "; ".join(e["message"] for e in schema_errors)
        )

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return manifest


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m publisher.manifest <validation-result-path-or-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        manifest = run(sys.argv[1])
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    dataset_slug = manifest.get("dataset_identity", {}).get("dataset_slug", "unknown")
    release_id = manifest.get("release_identity", {}).get("release_id", "unknown")
    artifacts_count = len(manifest.get("artifacts", []))
    print(f"manifest_generated: true")
    print(f"dataset_slug: {dataset_slug}")
    print(f"release_id: {release_id}")
    print(f"artifacts_hashed: {artifacts_count}")
    sys.exit(0)


if __name__ == "__main__":
    main()
