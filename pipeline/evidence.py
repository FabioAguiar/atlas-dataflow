"""
Reduced build evidence writer for candidate artifact generation.

This module is pipeline-side only. It does not import promotion logic, does not
read or write the registry, and writes evidence only to the supplied candidate
directory after schema validation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CANDIDATE_STAGING_PREFIX = Path("releases/candidates")
_BUILD_EVIDENCE_FILENAME = "build-evidence.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path_reference(path: str | Path) -> str:
    value = Path(path)
    if value.is_absolute():
        return value.name
    return value.as_posix()


def build_build_evidence(
    dataset_slug: str,
    release_id: str,
    source_input_path: str | Path,
    validation_result: dict[str, Any],
    assembled_artifacts: list[str],
) -> dict[str, Any]:
    valid = bool(validation_result.get("valid"))
    return {
        "schema_version": "build-evidence.v1",
        "producer": "pipeline/evidence.py",
        "source_input": {
            "dataset_slug": dataset_slug,
            "release_id": release_id,
            "path": _reduced_path_reference(source_input_path),
        },
        "publisher_validation": {
            "valid": valid,
            "validation_outcome": "accepted" if valid else "rejected",
            "validated_at": _utc_now_iso(),
        },
        "build_boundary_confirmations": {
            "promotion_occurred": False,
            "registry_mutation_occurred": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
        "assembled_artifacts": list(assembled_artifacts),
    }


def _validate_evidence_schema(evidence: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema is required to validate build evidence before writing."
        ) from exc

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Build evidence schema is missing: {schema_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Build evidence schema is invalid JSON: {schema_path}") from exc

    try:
        jsonschema.validate(evidence, schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(f"Build evidence failed schema validation: {exc.message}") from exc


def _assert_candidate_dir(candidate_dir: Path, repo_root: Path) -> Path:
    resolved_repo_root = repo_root.resolve()
    candidate_base = candidate_dir if candidate_dir.is_absolute() else resolved_repo_root / candidate_dir
    resolved_candidate_dir = candidate_base.resolve()
    staging_prefix = (resolved_repo_root / _CANDIDATE_STAGING_PREFIX).resolve()
    if not resolved_candidate_dir.is_relative_to(staging_prefix):
        raise RuntimeError(
            "Build evidence must be written under releases/candidates/."
        )
    return resolved_candidate_dir


def write_build_evidence(
    candidate_dir: str | Path,
    evidence: dict[str, Any],
    repo_root: str | Path,
) -> dict[str, Any]:
    repo_root_path = Path(repo_root)
    candidate_dir_path = _assert_candidate_dir(Path(candidate_dir), repo_root_path)
    schema_path = repo_root_path / "pipeline" / "build-evidence.schema.json"

    _validate_evidence_schema(evidence, schema_path)

    evidence_path = candidate_dir_path / _BUILD_EVIDENCE_FILENAME
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return evidence
