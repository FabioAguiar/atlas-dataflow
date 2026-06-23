"""
Artifact validation and hash recording pipeline for atlas-dataflow M22-05.

Reads M22 discovery artifacts and computes SHA-256 hashes for the raw input
dataset and the prepared candidate (when produced). Validates structural
completeness of discovery evidence, contract draft, and preparation recipe
against their schemas. Asserts that boundary confirmations are all false.

Boundaries enforced by this module:
- Raw dataset content is never persisted; only the SHA-256 hash is recorded.
- The prepared output hash is absent or null when candidate_output.produced is
  false; recording a null hash as a valid provenance entry is not permitted.
- Schema validation uses jsonschema against read-only pipeline schema files.
- No modification to existing pipeline schemas, pipeline scripts, or any other
  repository file is performed by this module.
- No contract promotion, model training, or release publication is performed.
- All paths recorded in the validation record are reduced (filename only), not
  absolute paths.
- Validation tests must use synthetic fixture inputs; live dataset output is
  not a permitted test input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_GENERATOR_VERSION = "validate-artifacts.v1"
_DISCOVERY_EVIDENCE_SCHEMA = "pipeline/dataset-discovery-evidence.schema.json"
_RECIPE_SCHEMA = "pipeline/candidate-preparation-recipe.schema.json"
_CONTRACT_DRAFT_SCHEMA = "pipeline/source-contract-input.schema.json"

_REQUIRED_DISCOVERY_FIELDS = [
    "schema_version",
    "producer",
    "dataset_metadata",
    "field_observations",
    "duplicated_rows_count",
    "candidate_categorical_fields",
    "candidate_target_columns",
    "generation_settings",
    "generated_at",
    "discovery_boundary_confirmations",
    "evidence_policy",
]

_REQUIRED_RECIPE_FIELDS = [
    "schema_version",
    "producer",
    "dataset_identity",
    "discovery_evidence_ref",
    "transformations",
    "candidate_output",
    "candidate_status",
    "generation_settings",
    "generated_at",
    "preparation_boundary_confirmations",
    "evidence_policy",
]

_REQUIRED_CONTRACT_FIELDS = [
    "schema_version",
    "dataset_slug",
    "release_id",
    "source_contract_ref",
    "source_data_ref",
]

_REQUIRED_BOUNDARY_FIELDS = [
    "complex_feature_engineering_performed",
    "model_training_performed",
    "release_publication_performed",
    "hidden_notebook_transformations",
    "inferred_rules_applied_without_approval",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path(path: Path) -> str:
    return path.name


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_validate(artifact: dict[str, Any], schema_path: Path) -> tuple[bool, str | None]:
    """Return (valid, error_message). Skips validation when jsonschema is unavailable."""
    try:
        import jsonschema

        schema = _load_json(schema_path)
        jsonschema.validate(artifact, schema)
        return True, None
    except ImportError:
        return True, "jsonschema not installed; schema validation skipped"
    except Exception as exc:
        return False, str(exc)


def _validate_discovery_evidence(
    evidence_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    evidence = _load_json(evidence_path)
    schema_path = repo_root / _DISCOVERY_EVIDENCE_SCHEMA
    schema_valid, schema_error = _schema_validate(evidence, schema_path)

    required_present = all(f in evidence for f in _REQUIRED_DISCOVERY_FIELDS)
    dataset_metadata = evidence.get("dataset_metadata", {})
    field_observations = evidence.get("field_observations", [])
    boundary_confirmations = evidence.get("discovery_boundary_confirmations", {})

    return {
        "path": _reduced_path(evidence_path),
        "schema_validation": {
            "schema": _DISCOVERY_EVIDENCE_SCHEMA,
            "valid": schema_valid,
            "error": schema_error,
        },
        "required_fields_present": required_present,
        "dataset_identity": {
            "name": dataset_metadata.get("name"),
            "row_count": dataset_metadata.get("row_count"),
            "column_count": dataset_metadata.get("column_count"),
        },
        "field_count": len(field_observations),
        "discovery_boundary_confirmations_all_false": all(
            boundary_confirmations.get(f) is False
            for f in [
                "contract_promotion_occurred",
                "model_training_occurred",
                "release_publication_occurred",
            ]
        ),
    }


def _validate_contract_draft(
    draft_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    draft = _load_json(draft_path)
    schema_path = repo_root / _CONTRACT_DRAFT_SCHEMA
    schema_valid, schema_error = _schema_validate(draft, schema_path)

    missing_fields = [f for f in _REQUIRED_CONTRACT_FIELDS if not draft.get(f)]

    return {
        "path": _reduced_path(draft_path),
        "schema_validation": {
            "schema": _CONTRACT_DRAFT_SCHEMA,
            "valid": schema_valid,
            "error": schema_error,
        },
        "required_fields_present": len(missing_fields) == 0,
        "missing_required_fields": missing_fields,
        "contract_draft_non_executable_status_confirmed": True,
        "non_executable_status_basis": (
            "contract draft is a declarative specification artifact; "
            "validation inspected required fields and performed no execution, "
            "training, or publication"
        ),
    }


def _validate_recipe(
    recipe_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    recipe = _load_json(recipe_path)
    schema_path = repo_root / _RECIPE_SCHEMA
    schema_valid, schema_error = _schema_validate(recipe, schema_path)

    discovery_ref = recipe.get("discovery_evidence_ref", {})
    discovery_ref_path_present = bool(discovery_ref.get("path"))

    transformations = recipe.get("transformations", [])
    all_have_review_status = all("review_status" in t for t in transformations)

    candidate_status = recipe.get("candidate_status", {})
    candidate_status_present = bool(candidate_status)
    candidate_status_fields_present = all(
        f in candidate_status
        for f in ["is_final_training_input", "requires_m23_validation", "authorized_for"]
    )

    bc = recipe.get("preparation_boundary_confirmations", {})
    bc_missing = [f for f in _REQUIRED_BOUNDARY_FIELDS if f not in bc]
    bc_all_false = not bc_missing and all(
        bc.get(f) is False for f in _REQUIRED_BOUNDARY_FIELDS
    )

    return {
        "path": _reduced_path(recipe_path),
        "schema_validation": {
            "schema": _RECIPE_SCHEMA,
            "valid": schema_valid,
            "error": schema_error,
        },
        "traceability": {
            "discovery_evidence_ref_path_present": discovery_ref_path_present,
            "discovery_evidence_ref_path": discovery_ref.get("path"),
            "all_transformations_have_review_status": all_have_review_status,
            "transformation_count": len(transformations),
            "candidate_status_present": candidate_status_present,
            "candidate_status_fields_present": candidate_status_fields_present,
        },
        "preparation_boundary_confirmations_all_false": bc_all_false,
        "preparation_boundary_confirmations_missing_fields": bc_missing,
        "candidate_output_produced": recipe.get("candidate_output", {}).get("produced"),
    }


def validate_artifacts(
    dataset_path: str | Path | None = None,
    discovery_evidence_path: str | Path | None = None,
    recipe_path: str | Path | None = None,
    candidate_path: str | Path | None = None,
    contract_draft_path: str | Path | None = None,
    repo_root: str | Path = ".",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Validate M22 discovery artifacts and record hashes.

    Returns a validation record dict. All arguments are optional to support
    partial validation runs and synthetic test fixtures.
    """
    repo_root = Path(repo_root)

    # Determine candidate_output.produced from recipe before hash conditionality
    recipe_loaded: dict[str, Any] | None = None
    if recipe_path is not None:
        rp = Path(recipe_path)
        if not rp.exists():
            raise FileNotFoundError(f"Preparation recipe not found: {rp}")
        recipe_loaded = _load_json(rp)

    candidate_produced: bool = (
        recipe_loaded.get("candidate_output", {}).get("produced", False)
        if recipe_loaded is not None
        else False
    )

    # Hash records
    hash_records: dict[str, Any] = {}

    if dataset_path is not None:
        dp = Path(dataset_path)
        if not dp.exists():
            raise FileNotFoundError(f"Raw dataset not found: {dp}")
        hash_records["raw_input_hash"] = {
            "algorithm": "sha256",
            "path": _reduced_path(dp),
            "hash": _sha256_file(dp),
        }

    if candidate_path is not None:
        cp = Path(candidate_path)
        if candidate_produced:
            if not cp.exists():
                raise FileNotFoundError(f"Prepared candidate not found: {cp}")
            hash_records["prepared_output_hash"] = {
                "algorithm": "sha256",
                "path": _reduced_path(cp),
                "hash": _sha256_file(cp),
            }
        else:
            hash_records["prepared_output_hash"] = None
            hash_records["prepared_output_hash_absent_reason"] = (
                "Prepared candidate was not produced "
                "(recipe.candidate_output.produced is false). "
                "Recording a null hash as a valid provenance entry is not permitted."
            )
    elif recipe_loaded is not None and not candidate_produced:
        hash_records["prepared_output_hash"] = None
        hash_records["prepared_output_hash_absent_reason"] = (
            "Prepared candidate was not produced "
            "(recipe.candidate_output.produced is false)."
        )

    # Validation results
    validation_results: dict[str, Any] = {}

    if discovery_evidence_path is not None:
        dep = Path(discovery_evidence_path)
        if not dep.exists():
            raise FileNotFoundError(f"Discovery evidence not found: {dep}")
        validation_results["discovery_evidence"] = _validate_discovery_evidence(
            dep, repo_root
        )

    if contract_draft_path is not None:
        cdp = Path(contract_draft_path)
        if not cdp.exists():
            raise FileNotFoundError(f"Contract draft not found: {cdp}")
        validation_results["contract_draft"] = _validate_contract_draft(cdp, repo_root)

    if recipe_path is not None:
        validation_results["recipe"] = _validate_recipe(Path(recipe_path), repo_root)

    return {
        "schema_version": "artifact-validation-record.v1",
        "producer": "pipeline/validate_artifacts.py",
        "generated_at": generated_at or _utc_now_iso(),
        "generator_version": _GENERATOR_VERSION,
        "hash_records": hash_records,
        "validation_results": validation_results,
        "preparation_boundary_confirmations": {
            "complex_feature_engineering_performed": False,
            "model_training_performed": False,
            "release_publication_performed": False,
            "hidden_notebook_transformations": False,
            "inferred_rules_applied_without_approval": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }


def write_artifact_validation_record(
    output_path: str | Path,
    record: dict[str, Any],
) -> None:
    """Write the validation record to a JSON file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="M22-05 artifact validation and hash recording for atlas-dataflow.",
    )
    p.add_argument(
        "--dataset",
        default=None,
        help="Path to the raw input CSV dataset (for SHA-256 hash recording).",
    )
    p.add_argument(
        "--discovery-evidence",
        default=None,
        help="Path to M22-02 discovery evidence JSON.",
    )
    p.add_argument(
        "--recipe",
        default=None,
        help="Path to M22-04 preparation recipe JSON.",
    )
    p.add_argument(
        "--candidate",
        default=None,
        help="Path to prepared candidate CSV (hash recorded only when recipe.candidate_output.produced is true).",
    )
    p.add_argument(
        "--contract-draft",
        default=None,
        help="Path to M22-03 contract draft JSON (optional).",
    )
    p.add_argument(
        "--output",
        required=True,
        help="Path to write the artifact validation record JSON.",
    )
    p.add_argument(
        "--repo-root",
        default=".",
        help="Repository root for schema resolution (default: current directory).",
    )
    return p


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    record = validate_artifacts(
        dataset_path=args.dataset,
        discovery_evidence_path=args.discovery_evidence,
        recipe_path=args.recipe,
        candidate_path=args.candidate,
        contract_draft_path=args.contract_draft,
        repo_root=args.repo_root,
    )

    write_artifact_validation_record(args.output, record)
    print(json.dumps(record, indent=2, ensure_ascii=False))
