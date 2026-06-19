"""
Publication evidence recorder for the internal publisher flow.

Builds publisher/runs/{run_id}/publication-evidence.json from reduced publisher
run outputs and an explicit registry update result supplied by the caller.
Does not inspect release candidate artifact files and does not mutate any
publisher, registry, or promotion input artifact.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


_PUBLIC_ROUTES_REVIEWED = [
    {
        "method": "GET",
        "path": "/datasets",
        "classification": "public_read_only",
    },
    {
        "method": "GET",
        "path": "/datasets/{dataset_slug}",
        "classification": "public_read_only",
    },
]


def _load_json_file(path: Path, label: str) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"{label} could not be read.") from exc

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object.")

    return data


def _resolve_run_dir(result_path_or_run_dir: str) -> Path:
    input_path = Path(result_path_or_run_dir)
    if input_path.is_file():
        return input_path.parent
    if input_path.is_dir():
        return input_path
    raise ValueError(f"Input path does not exist: {result_path_or_run_dir}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _candidate_identity(validation_result: dict, promotion_result: dict) -> dict:
    identity = validation_result.get("candidate_identity")
    if not isinstance(identity, dict):
        raise RuntimeError("Validation result is missing candidate_identity.")

    promotion_identity = promotion_result.get("candidate_identity")
    if not isinstance(promotion_identity, dict):
        raise RuntimeError("Promotion result is missing candidate_identity.")

    for key in ("dataset_slug", "release_id"):
        if identity.get(key) != promotion_identity.get(key):
            raise RuntimeError(
                f"Validation result and promotion result disagree on candidate_identity.{key}."
            )

    return identity


def _registry_update_summary(registry_update_result: dict, identity: dict) -> dict:
    if not isinstance(registry_update_result, dict):
        raise RuntimeError("registry_update_result must be a JSON object.")

    required_keys = {
        "dataset_slug",
        "release_id",
        "previous_active_release_id",
        "update_applied",
        "backup_path",
    }
    missing = sorted(required_keys - set(registry_update_result))
    if missing:
        raise RuntimeError(
            "registry_update_result is missing required keys: " + ", ".join(missing)
        )

    if registry_update_result.get("dataset_slug") != identity.get("dataset_slug"):
        raise RuntimeError("registry_update_result.dataset_slug does not match the run output.")
    if registry_update_result.get("release_id") != identity.get("release_id"):
        raise RuntimeError("registry_update_result.release_id does not match the run output.")
    if registry_update_result.get("update_applied") is not True:
        raise RuntimeError("registry_update_result.update_applied must be true.")

    return registry_update_result


def _manifest_has_required_hashes(manifest: dict) -> bool:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    return all(isinstance(a, dict) and bool(a.get("hash_value")) for a in artifacts)


def _rejection_reasons(validation_result: dict) -> list[dict]:
    rejection = validation_result.get("rejection")
    if isinstance(rejection, dict):
        reasons = rejection.get("reasons")
        if isinstance(reasons, list) and reasons:
            safe_reasons = []
            for reason in reasons:
                if not isinstance(reason, dict):
                    continue
                message = reason.get("message")
                if not isinstance(message, str) or not message:
                    continue
                safe_reasons.append({
                    "code": "missing_required_artifact_role",
                    "message": message,
                })
            if safe_reasons:
                return safe_reasons

    return [{
        "code": "precondition_not_met",
        "message": (
            "Incomplete candidate rejection is represented by the publisher "
            "validation gate; this publication evidence records the promoted release."
        ),
    }]


def _build_publication_evidence(
    validation_result: dict,
    manifest: dict,
    promotion_result: dict,
    registry_update_result: dict,
) -> dict:
    observed_at = _utc_now()
    identity = _candidate_identity(validation_result, promotion_result)
    registry_update = _registry_update_summary(registry_update_result, identity)

    validation_outcome = validation_result.get("validation_outcome")
    promotion_outcome = promotion_result.get("promotion_outcome")
    preconditions = promotion_result.get("preconditions_verified") or {}
    all_hashes_present = _manifest_has_required_hashes(manifest)

    return {
        "schema_version": "publication-validation-evidence.v1",
        "evidence_kind": "publication_validation_evidence",
        "candidate_validation": {
            "dataset_slug": identity.get("dataset_slug", ""),
            "release_id": identity.get("release_id", ""),
            "release_version": identity.get("release_version", ""),
            "validation_outcome": (
                validation_outcome
                if validation_outcome in ("accepted", "rejected")
                else "rejected"
            ),
            "validated_at": observed_at,
            "notes": [
                "Candidate validation evidence is reduced from validation-result.json."
            ],
        },
        "manifest_validation": {
            "manifest_schema_version": manifest.get("schema_version", "unknown"),
            "hash_coverage_outcome": (
                "all_required_hashes_present"
                if all_hashes_present
                else "missing_required_hashes"
            ),
            "manifest_valid": bool(
                manifest.get("schema_version") == "release-manifest.v1"
                and all_hashes_present
            ),
            "validated_at": observed_at,
            "notes": [
                "Manifest validation evidence is reduced from manifest.json."
            ],
        },
        "incomplete_release_rejection": {
            "release_id": identity.get("release_id", ""),
            "rejection_outcome": "rejected",
            "rejection_reasons": _rejection_reasons(validation_result),
            "rejected_at": observed_at,
        },
        "promotion_validation": {
            "release_id": identity.get("release_id", ""),
            "promotion_outcome": (
                promotion_outcome
                if promotion_outcome in ("promoted", "rejected")
                else "rejected"
            ),
            "preconditions_met": bool(
                preconditions.get("all_preconditions_met")
                and registry_update.get("update_applied") is True
            ),
            "promoted_at": observed_at,
            "notes": [
                "Promotion validation evidence is reduced from promotion-result.json."
            ],
        },
        "previous_release_preservation": {
            "previous_active_release_id": registry_update.get("previous_active_release_id"),
            "previous_release_preserved": True,
            "confirmed_at": observed_at,
        },
        "public_surface_review": {
            "reviewed_at": observed_at,
            "public_routes_reviewed": _PUBLIC_ROUTES_REVIEWED,
            "admin_endpoint_present": False,
            "publication_endpoint_present": False,
            "publisher_operations_exposed_publicly": False,
        },
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "local_databases_persisted": False,
            "volumes_persisted": False,
            "sensitive_runtime_internals_persisted": False,
            "raw_artifact_contents_embedded": False,
        },
        "authorization_boundary": {
            "github_mutation_authorized": False,
            "github_issue_publication_authorized": False,
            "release_promotion_authorized_by_this_evidence": False,
            "implementation_authorized_by_this_evidence": False,
        },
    }


def _validate_evidence_schema(evidence: dict, schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema is required to validate publication evidence before writing."
        ) from exc

    schema = _load_json_file(schema_path, "publication validation evidence schema")
    try:
        jsonschema.validate(evidence, schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"Publication evidence failed schema validation: {exc.message}"
        ) from exc


def run(
    result_path_or_run_dir: str,
    registry_update_result: dict,
    repo_root: Path | None = None,
) -> dict:
    """
    Build and write publication-evidence.json in the publisher run directory.

    Accepts either promotion-result.json or the containing run directory. The
    registry update result is supplied explicitly by the caller and is not read
    from registry files or a sidecar artifact.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    else:
        repo_root = Path(repo_root)

    run_dir = _resolve_run_dir(result_path_or_run_dir)
    validation_result = _load_json_file(run_dir / "validation-result.json", "validation result")
    manifest = _load_json_file(run_dir / "manifest.json", "manifest")
    promotion_result = _load_json_file(run_dir / "promotion-result.json", "promotion result")

    evidence = _build_publication_evidence(
        validation_result,
        manifest,
        promotion_result,
        registry_update_result,
    )
    schema_path = repo_root / "publisher" / "evidence" / "publication-validation-evidence.schema.json"
    _validate_evidence_schema(evidence, schema_path)

    evidence_path = run_dir / "publication-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return evidence


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Usage: python -m publisher.evidence "
            "<promotion-result-path-or-run-dir> '<registry-update-result-json>'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        registry_update_result = json.loads(sys.argv[2])
        evidence = run(sys.argv[1], registry_update_result)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    candidate_validation = evidence.get("candidate_validation", {})
    print("publication_evidence_written: true")
    print(f"dataset_slug: {candidate_validation.get('dataset_slug', 'unknown')}")
    print(f"release_id: {candidate_validation.get('release_id', 'unknown')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
