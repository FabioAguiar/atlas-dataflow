"""
Reduced, deterministic publication traceability evidence for M36-04.

Builds and writes registry/profile-snapshots/<dataset_slug>.evidence.json
alongside a published profile snapshot produced by
registry/dataset_public_profile_snapshot_store.py's publish_snapshot. Mirrors
publisher/evidence.py's and pipeline/evidence.py's established convention: a
dedicated, schema-validated, reduced evidence writer built from an
already-produced result, validated against a colocated schema
(registry/evidence/dataset-public-profile-snapshot-evidence.schema.json)
before being written alongside the result it summarizes rather than embedded
into it.

This module never mutates the snapshot it summarizes,
contracts/dataset-public-profile-snapshot.schema.json, or
registry/datasets.json. The visibility value it records is a read-only
capture of registry/datasets.json's existing public_metadata.visibility
field at publish time, never a new authoritative source or a redefinition
of that field.
"""

import json
from pathlib import Path

EVIDENCE_SCHEMA_VERSION = "dataset-public-profile-snapshot-evidence.v1"


def _load_evidence_schema(repo_root: Path) -> dict:
    schema_path = (
        repo_root / "registry" / "evidence" / "dataset-public-profile-snapshot-evidence.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _snapshot_identifier(dataset_slug: str, published_at: str) -> str:
    return f"{dataset_slug}@{published_at}"


def build_snapshot_evidence(
    candidate: dict,
    validation_errors: list,
    visibility_value: str | None,
) -> dict:
    """
    Build the reduced traceability evidence dict for a published snapshot
    candidate. Does not validate against the schema or write anything; call
    write_snapshot_evidence to validate and persist it.
    """
    dataset_slug = candidate["dataset_slug"]
    published_at = candidate["published_at"]
    active_release = candidate["active_release_at_publish_time"]

    draft_source_reference = {
        "path": f"registry/profile-drafts/{dataset_slug}.json",
        "source_draft_schema_version": candidate.get("source_draft_schema_version"),
    }

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": "profile_publication_evidence",
        "dataset_slug": dataset_slug,
        "snapshot_identifier": _snapshot_identifier(dataset_slug, published_at),
        "published_at": published_at,
        "active_release_at_publish_time": active_release,
        "draft_source_reference": draft_source_reference,
        "candidate_validation": {
            "validation_outcome": "accepted" if not validation_errors else "rejected",
            "errors": list(validation_errors),
            "validated_at": published_at,
        },
        "visibility_at_publish_time": {
            "value": visibility_value,
            "source_field": "registry/datasets.json:public_metadata.visibility",
            "read_only_snapshot": True,
            "captured_at": published_at,
        },
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "raw_artifact_contents_embedded": False,
        },
    }


def _validate_evidence_schema(evidence: dict, repo_root: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema is required to validate profile publication evidence before writing."
        ) from exc

    schema = _load_evidence_schema(repo_root)
    try:
        jsonschema.validate(evidence, schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"Profile publication evidence failed schema validation: {exc.message}"
        ) from exc


def _evidence_path(dataset_slug: str, repo_root: Path) -> Path:
    return repo_root / "registry" / "profile-snapshots" / f"{dataset_slug}.evidence.json"


def write_snapshot_evidence(
    candidate: dict,
    validation_errors: list,
    visibility_value: str | None,
    repo_root: Path,
) -> dict:
    """
    Build, validate, and write the reduced publication evidence for a
    successfully published snapshot candidate, alongside its snapshot file.

    Callers must only invoke this after the snapshot file itself has already
    been durably written, and only for a successful publish; this module
    does not decide whether a publish should be rejected. Raises
    RuntimeError if the built evidence fails schema validation.
    """
    evidence = build_snapshot_evidence(candidate, validation_errors, visibility_value)
    _validate_evidence_schema(evidence, repo_root)

    path = _evidence_path(candidate["dataset_slug"], repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    return evidence
