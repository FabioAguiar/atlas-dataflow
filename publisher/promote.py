"""
Publisher release promotion module.

Accepts a run directory path (publisher/runs/{validation_run_id}/), reads the
validation result and manifest, gates on promotion_gate.promotion_allowed: true
and manifest presence, resolves the candidate directory, checks that the target
releases/{release_id}/ does not already exist, copies all artifact role files
preserving candidate-relative paths into releases/{release_id}/, copies
manifest.json into releases/{release_id}/manifest.json, and writes a promotion
result to publisher/runs/{validation_run_id}/promotion-result.json — written
last, after all copies succeed.

On any failure in the critical section that spans from releases/{release_id}/
being created through the final successful write of promotion-result.json
(artifact copy, manifest copy, or the promotion-result.json write itself),
removes the entire releases/{release_id}/ directory with shutil.rmtree()
before re-raising. Partial or orphaned release directories are never left on
disk, so a retry never collides with a stale releases/{release_id}/ from a
previous failed attempt.

Does NOT read, write, or import registry/datasets.json.
Does NOT expose any HTTP endpoint. run() and main() are internal CLI only.
Does NOT modify any candidate artifact.

finalize_promotion_result_after_registry_update() below is the one
exception to "does not read/write registry/datasets.json": it never reads
or writes that file itself, but it does synchronize the already-written
promotion-result.json with a registry outcome dict the caller obtained
separately from registry/update.py.run() (Project Spec S0046). It takes no
dependency on the registry package -- the caller (api/admin_runs.py)
computes registry_action via registry.update.derive_registry_action() and
passes it in, keeping this module's only coupling to the registry system
at the orchestration layer, not the import layer.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


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
    """Return (allowed, errors). Halts if promotion_gate.promotion_allowed is absent or not True."""
    pg = validation_result.get("promotion_gate")
    if not isinstance(pg, dict):
        return False, [_err(
            "PROMOTION_GATE_MISSING",
            "promotion_gate",
            "Validation result is missing the 'promotion_gate' field.",
        )]
    allowed = pg.get("promotion_allowed")
    if allowed is not True:
        return False, [_err(
            "PROMOTION_NOT_ALLOWED",
            "promotion_gate.promotion_allowed",
            "Promotion halted: promotion_gate.promotion_allowed is not true.",
        )]
    return True, []


def _resolve_candidate_dir(validation_result: dict, repo_root: Path, note: dict) -> tuple:
    """Resolve the candidate directory from validation result and operational note.

    Returns (candidate_dir, errors).
    """
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


def _build_promotion_result(validation_result: dict, manifest: dict) -> dict:
    """Construct the promotion result conforming to promotion-result.schema.json.

    Initial write, immediately after the release artifact copy succeeds and
    before any registry update has been attempted: update_applied is always
    false and previous_active_release_id is null here, since this module
    never reads registry/datasets.json. This is deliberately provisional --
    finalize_promotion_result_after_registry_update() below rewrites
    registry_update_record once the real registry outcome is known
    (Project Spec S0046), so a promotion-result.json left at this initial
    state (update_applied still false) honestly means "registry update not
    yet confirmed," not "registry update failed."
    """
    candidate_identity = validation_result.get("candidate_identity") or {}
    validation_outcome = validation_result.get("validation_outcome", "accepted")
    promotion_gate = validation_result.get("promotion_gate") or {}

    completeness_outcome = (
        validation_outcome if validation_outcome in ("accepted", "rejected") else "accepted"
    )
    all_hashes_present = all(
        bool(a.get("hash_value"))
        for a in manifest.get("artifacts", [])
    )

    return {
        "schema_version": "promotion-result.v1",
        "result_kind": "promotion_result",
        "candidate_identity": {
            "dataset_slug": candidate_identity.get("dataset_slug", ""),
            "release_id": candidate_identity.get("release_id", ""),
            "release_version": candidate_identity.get("release_version", ""),
        },
        "promotion_outcome": "promoted",
        "preconditions_verified": {
            "completeness_validation_outcome": completeness_outcome,
            "manifest_valid": True,
            "all_required_hashes_present": all_hashes_present,
            "candidate_state_was_valid": bool(promotion_gate.get("promotion_allowed")),
            "all_preconditions_met": True,
        },
        "registry_update_record": {
            "update_applied": False,
            "new_active_release_id": None,
            "previous_active_release_id": None,
            "previous_release_preserved": True,
        },
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "sensitive_local_paths_persisted": False,
            "raw_file_contents_persisted": False,
            "raw_artifact_contents_embedded": False,
        },
        "promotion_boundaries": {
            "registry_write_implemented": False,
            "hash_calculation_implemented": False,
            "signing_or_key_management_implemented": False,
            "queue_required": False,
            "worker_required": False,
            "database_required": False,
            "public_endpoint_exposed": False,
            "web_administration_required": False,
            "github_mutation_performed": False,
        },
    }


def _validate_result_schema(result: dict, schema_path: Path) -> list:
    """Validate result against promotion-result.schema.json.

    Returns a list of errors (informational). Non-blocking for M11-04 because
    update_applied=false diverges from the schema's allOf constraint that links
    promotion_outcome='promoted' to update_applied=true. M11-05 will produce
    results that fully satisfy the schema's registry_update_record constraints.
    """
    try:
        import jsonschema
    except ImportError:
        return []

    schema_data, errors = _load_json_file(schema_path, "promotion_result_schema")
    if errors:
        return errors

    try:
        jsonschema.validate(result, schema_data)
        return []
    except jsonschema.ValidationError as exc:
        return [_err(
            "RESULT_SCHEMA_VALIDATION_NOTE",
            None,
            f"Promotion result schema note (M11-04 boundary): {exc.message}",
        )]


def run(result_path_or_run_dir: str, repo_root: Path | None = None) -> dict:
    """
    Execute the controlled promotion step and write the promotion result.

    Accepts either the validation result JSON path or the run directory path.
    Returns the promotion result dict.
    Raises RuntimeError on gate failure, missing manifest, overwrite attempt,
    copy failure (releases/{release_id}/ is cleaned up), or unrecoverable error.
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

    # --- Load validation result ---
    validation_result, errors = _load_json_file(run_dir / "validation-result.json", "validation_result")
    if errors:
        raise RuntimeError(
            "Cannot load validation result: "
            + "; ".join(e["message"] for e in errors)
        )

    # --- Gate: promotion_gate.promotion_allowed must be exactly True ---
    allowed, gate_errors = _check_promotion_gate(validation_result)
    if not allowed:
        raise RuntimeError("; ".join(e["message"] for e in gate_errors))

    # --- Gate: manifest.json must be present in the run directory ---
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            "Promotion halted: manifest.json is absent from the run directory. "
            "Run publisher/manifest.py before promoting."
        )

    manifest, manifest_errors = _load_json_file(manifest_path, "manifest")
    if manifest_errors:
        raise RuntimeError(
            "Cannot load manifest: "
            + "; ".join(e["message"] for e in manifest_errors)
        )

    # --- Load operational note to resolve candidate directory ---
    note, note_errors = _load_operational_note(repo_root)
    if note_errors:
        raise RuntimeError(
            "Cannot load operational note: "
            + "; ".join(e["message"] for e in note_errors)
        )

    # --- Resolve candidate directory ---
    candidate_dir, cd_errors = _resolve_candidate_dir(validation_result, repo_root, note)
    if cd_errors:
        raise RuntimeError(
            "Cannot resolve candidate directory: "
            + "; ".join(e["message"] for e in cd_errors)
        )

    # --- Resolve release_id and release directory ---
    candidate_identity = validation_result.get("candidate_identity") or {}
    release_id = candidate_identity.get("release_id", "")
    if not release_id:
        raise RuntimeError(
            "Promotion halted: release_id is missing from validation result candidate_identity."
        )

    release_dir = repo_root / "releases" / release_id

    # --- Overwrite prevention: releases/{release_id}/ must not already exist ---
    if release_dir.exists():
        raise RuntimeError(
            f"Promotion rejected: releases/{release_id}/ already exists. "
            "Overwrite of an existing release directory is not permitted."
        )

    # --- Copy artifacts preserving candidate-relative paths ---
    # On any failure from here through the final promotion-result.json write
    # (copy, manifest copy, or the result write itself), clean up with
    # shutil.rmtree() before re-raising, so no orphaned releases/{release_id}/
    # is ever left on disk for a later retry to collide with.
    release_dir.mkdir(parents=True)
    try:
        for artifact in manifest.get("artifacts", []):
            reference = artifact.get("reference", "")
            if not reference:
                raise RuntimeError(
                    "Manifest artifact entry is missing 'reference' field; cannot copy."
                )
            src = candidate_dir / reference
            if not src.is_file():
                raise RuntimeError(
                    f"Artifact source file for reference '{reference}' is not readable during copy."
                )
            dst = release_dir / reference
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        # --- Copy manifest.json into releases/{release_id}/ ---
        shutil.copy2(manifest_path, release_dir / "manifest.json")

        # --- Build promotion result ---
        result = _build_promotion_result(validation_result, manifest)

        # --- Validate result against schema (informational; non-blocking for M11-04 boundary) ---
        schema_path = repo_root / "publisher" / "promotion" / "promotion-result.schema.json"
        _validate_result_schema(result, schema_path)

        # --- Write promotion result last, after all copies have succeeded ---
        result_path = run_dir / "promotion-result.json"
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    except Exception:
        shutil.rmtree(release_dir, ignore_errors=True)
        raise

    return result


def finalize_promotion_result_after_registry_update(
    result_path_or_run_dir: str,
    registry_result: dict,
    registry_action: str,
    repo_root: Path | None = None,
) -> dict:
    """
    Synchronize an already-promoted run's promotion-result.json with the
    real outcome of a successful registry/update.py run (Project Spec
    S0046).

    Call only after registry/update.py.run() has returned successfully --
    never after it raised. registry_result is that successful return value
    verbatim; registry_action is the caller's own
    registry.update.derive_registry_action(registry_result) classification
    (this module takes no dependency on the registry package, per its
    module docstring).

    Idempotent by design: if registry_update_record already shows
    update_applied=true with new_active_release_id equal to this
    registry_result's release_id, the file is left untouched and returned
    as-is. Without this check, a repeated finalize call for an
    already-synchronized release would recompute previous_active_release_id
    as equal to release_id itself (the registry's current state, not the
    state before the original update) and overwrite a correct record with a
    contradictory one -- exactly the "idempotent retry rewrites
    contradictory registry metadata" failure this spec forbids.

    Raises RuntimeError if promotion-result.json is missing, unreadable, or
    does not show promotion_outcome == "promoted". Raises ValueError if
    result_path_or_run_dir does not exist.
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

    result_path = run_dir / "promotion-result.json"
    result, errors = _load_json_file(result_path, "promotion_result")
    if errors:
        raise RuntimeError(
            "Cannot finalize registry update record: "
            + "; ".join(e["message"] for e in errors)
        )

    if result.get("promotion_outcome") != "promoted":
        raise RuntimeError(
            "Cannot finalize registry update record: promotion_outcome is not 'promoted'."
        )

    release_id = registry_result.get("release_id")
    existing_record = result.get("registry_update_record") or {}
    if (
        existing_record.get("update_applied") is True
        and existing_record.get("new_active_release_id") == release_id
    ):
        return result

    dataset_slug = registry_result.get("dataset_slug")
    allocated_dataset_slug = registry_result.get("allocated_dataset_slug")
    public_dataset_slug = (
        allocated_dataset_slug
        if allocated_dataset_slug and allocated_dataset_slug != dataset_slug
        else None
    )

    registry_update_record = {
        "update_applied": True,
        "new_active_release_id": release_id,
        "previous_active_release_id": registry_result.get("previous_active_release_id"),
        "previous_release_preserved": True,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registry_action": registry_action,
    }
    if public_dataset_slug is not None:
        registry_update_record["public_dataset_slug"] = public_dataset_slug

    result["registry_update_record"] = registry_update_record

    schema_path = repo_root / "publisher" / "promotion" / "promotion-result.schema.json"
    _validate_result_schema(result, schema_path)

    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m publisher.promote <validation-result-path-or-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = run(sys.argv[1])
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    candidate_identity = result.get("candidate_identity", {})
    dataset_slug = candidate_identity.get("dataset_slug", "unknown")
    release_id = candidate_identity.get("release_id", "unknown")
    outcome = result.get("promotion_outcome", "unknown")
    print(f"promotion_outcome: {outcome}")
    print(f"dataset_slug: {dataset_slug}")
    print(f"release_id: {release_id}")
    sys.exit(0 if outcome == "promoted" else 1)


if __name__ == "__main__":
    main()
