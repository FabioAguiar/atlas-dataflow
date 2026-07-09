"""
Candidate assembly pipeline for atlas-dataflow.

Assembles a publisher-compatible candidate artifact set from governed
release-candidate-input.v1 artifacts, validates the assembled candidate against
publisher requirements, and returns a JSON result to stdout.

Does NOT call publisher/promote.py.
Does NOT read or modify registry/datasets.json.
Does NOT write to any path outside releases/candidates/.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_PUBLIC_ARTIFACT_MAPPINGS = [
    ("promoted_contracts.runtime_contract", "contracts/runtime-contract.json"),
    ("promoted_contracts.public_contract", "contracts/public-contract.json"),
    ("training_metrics", "metrics/metrics.json"),
    ("inference_bundle", "predictions/bundle.json"),
    ("model_card", "model-card.json"),
    ("public_context", "public-context.json"),
]

_REQUIRED_REAL_INPUTS = [
    "discovery_evidence",
    "promoted_contracts.execution_contract",
    "promoted_contracts.runtime_contract",
    "promoted_contracts.public_contract",
    "preparation_recipe",
    "prepared_data_metadata",
    "training_parameter_record",
    "model_artifact",
    "training_metrics",
    "model_card",
    "public_context",
    "inference_bundle",
]

_CANDIDATE_STAGING_PREFIX = "releases/candidates"

# Release-candidate data handoff boundary (Project Spec S0016). This is a
# pre-assembly readiness check only: it validates explicit, repository-relative
# artifact references for every release-candidate-input.v1 required role
# without executing candidate assembly, publisher validation, publisher
# promotion, registry activation, or any API/UI data fill.
_HANDOFF_REQUIRED_ROLES = [
    "discovery_evidence",
    "execution_contract",
    "runtime_contract",
    "public_contract",
    "preparation_recipe",
    "prepared_data_metadata",
    "training_parameter_record",
    "model_artifact",
    "training_metrics",
    "model_card",
    "public_context",
    "inference_bundle",
]

_HANDOFF_FIXTURE_PATH_MARKERS = ("fixtures/", "pipeline/examples/", "test-fixtures/")


def _handoff_role_result(role: str, path_value: Any, *, ready: bool, reason: str | None) -> dict:
    return {"role": role, "path": path_value, "ready": ready, "reason": reason}


def _classify_handoff_reference(role: str, path_value: Any, repo_root: Path) -> dict:
    """Classify a single explicit artifact reference for handoff readiness.

    Never inspects notebook state — only the repository-relative path
    string passed in by the caller.
    """
    if not isinstance(path_value, str) or not path_value.strip():
        return _handoff_role_result(role, path_value, ready=False, reason="missing_reference")

    path = Path(path_value)
    if path.is_absolute():
        return _handoff_role_result(role, path_value, ready=False, reason="absolute_path_rejected")
    if ".." in path.parts:
        return _handoff_role_result(role, path_value, ready=False, reason="parent_traversal_rejected")

    normalized = path_value.replace("\\", "/")
    if any(marker in normalized for marker in _HANDOFF_FIXTURE_PATH_MARKERS):
        return _handoff_role_result(role, path_value, ready=False, reason="fixture_only_path_rejected")

    resolved = repo_root / path
    if not resolved.is_file():
        return _handoff_role_result(role, path_value, ready=False, reason="missing_reference")

    if resolved.suffix == ".json":
        try:
            content = json.loads(resolved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            content = None
        if isinstance(content, dict):
            example_metadata = content.get("example_metadata")
            if isinstance(example_metadata, dict) and example_metadata.get("example_only") is True:
                return _handoff_role_result(
                    role, path_value, ready=False, reason="placeholder_only_content_rejected"
                )
            if content.get("placeholder_only") is True:
                return _handoff_role_result(
                    role, path_value, ready=False, reason="placeholder_only_content_rejected"
                )

    return _handoff_role_result(role, path_value, ready=True, reason=None)


def build_release_candidate_handoff_readiness(
    artifact_references: dict[str, Any],
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a reduced `release-candidate-handoff-readiness.v1` object.

    `artifact_references` must map each role in `_HANDOFF_REQUIRED_ROLES` to
    an explicit, repository-relative artifact path string — never a
    notebook-held DataFrame, notebook variable, or other in-memory object;
    the function's signature only accepts path strings, so notebook-state
    can never be passed through. This performs read-only static checks
    (existence, path safety, fixture/placeholder detection) and never
    assembles a release candidate, invokes publisher validation, promotes a
    release, activates a registry entry, or fills API/UI data.
    """
    resolved_repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    if not isinstance(artifact_references, dict):
        artifact_references = {}

    role_results = [
        _classify_handoff_reference(role, artifact_references.get(role), resolved_repo_root)
        for role in _HANDOFF_REQUIRED_ROLES
    ]
    not_ready_roles = [result["role"] for result in role_results if not result["ready"]]
    blocking_reasons = [
        f"{result['role']}: {result['reason']}" for result in role_results if not result["ready"]
    ]

    return {
        "schema_version": "release-candidate-handoff-readiness.v1",
        "handoff_kind": "release_candidate_data_handoff",
        "required_roles": list(_HANDOFF_REQUIRED_ROLES),
        "role_results": role_results,
        "not_ready_roles": not_ready_roles,
        "blocking_reasons": blocking_reasons,
        "is_release_candidate_input_ready": not blocking_reasons,
        "handoff_boundary_confirmations": {
            "release_candidate_assembly_performed": False,
            "publisher_validation_performed": False,
            "publisher_promotion_performed": False,
            "registry_activation_performed": False,
            "api_data_available": False,
            "ui_data_available": False,
        },
    }


def _load_candidate_input(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load and parse the release-candidate-input JSON."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"


def _rejection(phase: str, reason: str, **extra) -> dict:
    return {"status": "rejected", "reason": reason, "rejection_phase": phase, **extra}


def _acceptance(dataset_slug: str, release_id: str, candidate_dir: Path, validation: dict) -> dict:
    return {
        "status": "accepted",
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "candidate_dir": str(candidate_dir),
        "publisher_validation": {
            "valid": validation.get("valid"),
            "role_results": validation.get("role_results"),
            "identifier_consistency": validation.get("identifier_consistency"),
            "schema_compatibility": validation.get("schema_compatibility"),
        },
    }


def _build_release_candidate(
    candidate_input: dict[str, Any], now: str
) -> dict:
    """Build release-candidate.json conforming to publisher/release-candidate.schema.json."""
    dataset_identity = candidate_input["dataset_identity"]
    release_identity = candidate_input["release_identity"]
    source_run = candidate_input["source_run"]
    return {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {
            "dataset_slug": dataset_identity["dataset_slug"],
            "dataset_title": dataset_identity.get(
                "dataset_title",
                dataset_identity["dataset_slug"].replace("-", " ").title(),
            ),
        },
        "release_identity": {
            "release_id": release_identity["release_id"],
            "release_version": release_identity["release_version"],
            "created_at": release_identity.get("created_at", now),
        },
        "source_run": {
            "run_id": source_run["run_id"],
            "producer": source_run["producer"],
            "created_at": source_run.get("created_at", now),
        },
        "artifact_roles": {
            "contracts": {
                "role": "contracts",
                "path": "contracts/runtime-contract.json",
                "required": True,
                "media_type": "application/json",
            },
            "predictive_bundle": {
                "role": "predictive_bundle",
                "path": "predictions/bundle.json",
                "required": True,
                "media_type": "application/json",
            },
            "metrics": {
                "role": "metrics",
                "path": "metrics/metrics.json",
                "required": True,
                "media_type": "application/json",
            },
            "model_card": {
                "role": "model_card",
                "path": "model-card.json",
                "required": True,
                "media_type": "application/json",
            },
            "public_context": {
                "role": "public_context",
                "path": "public-context.json",
                "required": True,
                "media_type": "application/json",
            },
            "manifest_input": {
                "role": "manifest_input",
                "path": "manifest-input.json",
                "required": True,
                "media_type": "application/json",
            },
            "candidate_metadata": {
                "role": "candidate_metadata",
                "path": "release-candidate.json",
                "required": True,
                "media_type": "application/json",
            },
        },
        "candidate_metadata": {
            "assembled_by": "pipeline/assemble_candidate.py",
            "assembled_at": now,
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": [
                    "contracts",
                    "predictive_bundle",
                    "metrics",
                    "model_card",
                    "public_context",
                    "manifest_input",
                    "candidate_metadata",
                ],
                "hash_policy": "publisher_calculates_hashes",
                "manifest_policy": "publisher_generates_manifest",
            },
        },
        "state_boundaries": {
            "pipeline_run_is_publishable": False,
            "candidate_is_published_release": False,
            "promotion_required": True,
            "registry_update_allowed_in_candidate": False,
            "public_upload_required": False,
            "web_administration_required": False,
            "database_publication_management_required": False,
            "runtime_consumes_temporary_pipeline_output": False,
        },
    }


def _get_nested(data: dict[str, Any], dotted_path: str) -> Any:
    value: Any = data
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _input_identity(candidate_input: dict[str, Any]) -> tuple[str | None, str | None]:
    dataset_slug = _get_nested(candidate_input, "dataset_identity.dataset_slug")
    release_id = _get_nested(candidate_input, "release_identity.release_id")
    return dataset_slug, release_id


def _validate_candidate_input(candidate_input: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate_input.get("contract_version") != "release-candidate-input.v1":
        errors.append("contract_version must be release-candidate-input.v1")
    if candidate_input.get("input_kind") != "release_candidate_input":
        errors.append("input_kind must be release_candidate_input")

    dataset_slug, release_id = _input_identity(candidate_input)
    release_version = _get_nested(candidate_input, "release_identity.release_version")
    if not dataset_slug:
        errors.append("dataset_identity.dataset_slug is required")
    if not release_id:
        errors.append("release_identity.release_id is required")
    if not release_version:
        errors.append("release_identity.release_version is required")
    if not _get_nested(candidate_input, "source_run.run_id"):
        errors.append("source_run.run_id is required")
    if not _get_nested(candidate_input, "source_run.producer"):
        errors.append("source_run.producer is required")

    artifact_inputs = candidate_input.get("artifact_inputs")
    if not isinstance(artifact_inputs, dict):
        errors.append("artifact_inputs must be an object")
        return errors

    for input_path in _REQUIRED_REAL_INPUTS:
        artifact = _get_nested(artifact_inputs, input_path)
        if not isinstance(artifact, dict):
            errors.append(f"artifact_inputs.{input_path} is required")
            continue
        if artifact.get("required") is not True:
            errors.append(f"artifact_inputs.{input_path}.required must be true")
        if artifact.get("availability_status") != "real_dataflow_artifact":
            errors.append(
                f"artifact_inputs.{input_path}.availability_status must be real_dataflow_artifact"
            )
        placeholder_policy = artifact.get("placeholder_policy")
        if not isinstance(placeholder_policy, dict):
            errors.append(f"artifact_inputs.{input_path}.placeholder_policy is required")
            continue
        if placeholder_policy.get("fixtures_allowed") is not False:
            errors.append(f"artifact_inputs.{input_path} must reject fixture-only artifacts")
        if placeholder_policy.get("placeholders_allowed") is not False:
            errors.append(f"artifact_inputs.{input_path} must reject placeholder-only artifacts")
        if placeholder_policy.get("missing_required_behavior") != "reject":
            errors.append(f"artifact_inputs.{input_path} must reject missing required artifacts")
    return errors


def _resolve_repo_relative(path_value: str, repo_root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        raise ValueError(f"artifact path must be repository-relative: {path_value}")
    if ".." in path.parts:
        raise ValueError(f"artifact path must not contain parent traversal: {path_value}")
    return repo_root / path


def _required_public_artifacts(candidate_input: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    artifact_inputs = candidate_input["artifact_inputs"]
    artifacts: list[tuple[dict[str, Any], str]] = []
    for input_path, output_path in _PUBLIC_ARTIFACT_MAPPINGS:
        artifacts.append((_get_nested(artifact_inputs, input_path), output_path))
    return artifacts


def _missing_required_artifacts(candidate_input: dict[str, Any], repo_root: Path) -> list[str]:
    missing = []
    artifact_inputs = candidate_input["artifact_inputs"]
    for input_path in _REQUIRED_REAL_INPUTS:
        artifact = _get_nested(artifact_inputs, input_path)
        source_path = artifact.get("path")
        try:
            source_file_missing = (
                not source_path or not _resolve_repo_relative(source_path, repo_root).is_file()
            )
        except ValueError:
            source_file_missing = True
        if source_file_missing:
            missing.append(source_path or artifact["role"])
    return missing


def _write_manifest_input(candidate_dir: Path, candidate_input: dict[str, Any]) -> None:
    manifest_input = {
        "schema_version": "manifest-input.v1",
        "dataset_identity": candidate_input["dataset_identity"],
        "release_identity": candidate_input["release_identity"],
        "source_run": candidate_input["source_run"],
        "candidate_mapping": candidate_input.get("candidate_mapping", {}),
        "generated_by": "pipeline/assemble_candidate.py",
    }
    (candidate_dir / "manifest-input.json").write_text(
        json.dumps(manifest_input, indent=2), encoding="utf-8"
    )


def _build_assembly_evidence(
    candidate_input: dict[str, Any],
    source_input_path: str,
    validation: dict[str, Any],
    assembled: list[str],
) -> dict[str, Any]:
    dataset_slug, release_id = _input_identity(candidate_input)
    return {
        "schema_version": "build-evidence.v1",
        "source_input": {
            "path": str(Path(source_input_path).name),
            "contract_version": candidate_input.get("contract_version"),
            "dataset_slug": dataset_slug,
            "release_id": release_id,
        },
        "assembled_artifacts": assembled,
        "publisher_validation": {
            "valid": validation.get("valid"),
            "validation_outcome": "accepted" if validation.get("valid") else "rejected",
            "validated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a publisher-compatible candidate from a release-candidate-input."
    )
    parser.add_argument(
        "candidate_input",
        help="Path to the release-candidate-input JSON file",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Candidate staging base directory (e.g. releases/candidates/)",
    )
    args = parser.parse_args()

    # Step 1: Load release-candidate-input JSON; extract stable identity.
    candidate_input, load_err = _load_candidate_input(args.candidate_input)
    if load_err:
        phase = "candidate_input_read" if "not found" in load_err else "candidate_input_parse"
        print(json.dumps(_rejection(
            phase, load_err,
            dataset_slug=None, release_id=None, candidate_dir=None,
        ), indent=2))
        return 1

    dataset_slug, release_id = _input_identity(candidate_input)
    input_errors = _validate_candidate_input(candidate_input)
    if input_errors:
        print(json.dumps(_rejection(
            "candidate_input_parse",
            "release-candidate-input JSON failed required assembly checks",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=None,
            validation_errors=input_errors,
        ), indent=2))
        return 1

    # Step 2: Construct candidate_dir and assert it is under releases/candidates/.
    candidate_dir = (Path(args.output_dir) / dataset_slug / release_id).resolve()
    staging_prefix = Path(_CANDIDATE_STAGING_PREFIX).resolve()
    if not candidate_dir.is_relative_to(staging_prefix):
        print(json.dumps(_rejection(
            "staging_path_violation",
            f"candidate_dir must be under {_CANDIDATE_STAGING_PREFIX}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
        ), indent=2))
        return 1

    # Step 3: Verify all required governed artifacts are present.
    missing = _missing_required_artifacts(candidate_input, _REPO_ROOT)
    if missing:
        print(json.dumps(_rejection(
            "candidate_artifact_missing",
            f"required governed artifacts missing: {missing}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
            missing_paths=missing,
        ), indent=2))
        return 1

    # Step 4: Create candidate_dir and necessary subdirectories.
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Step 5: Copy each publisher-visible governed artifact to the candidate directory.
    assembled = []
    for artifact, output_path in _required_public_artifacts(candidate_input):
        dst = candidate_dir / output_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_resolve_repo_relative(artifact["path"], _REPO_ROOT), dst)
        assembled.append(output_path)
    _write_manifest_input(candidate_dir, candidate_input)
    assembled.append("manifest-input.json")

    # Step 6: Write release-candidate.json (publisher/release-candidate.schema.json).
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    release_candidate = _build_release_candidate(candidate_input, now)
    (candidate_dir / "release-candidate.json").write_text(
        json.dumps(release_candidate, indent=2), encoding="utf-8"
    )
    assembled.append("release-candidate.json")

    # Step 7: Invoke publisher.validate.validate_candidate_file() via Python import.
    sys.path.insert(0, str(_REPO_ROOT))
    from publisher import validate  # noqa: PLC0415
    result = validate.validate_candidate_file(candidate_dir)

    # Step 8: Write reduced build-evidence.json (pipeline-internal; NOT in artifact_roles).
    build_evidence = _build_assembly_evidence(
        candidate_input,
        args.candidate_input,
        result,
        assembled,
    )
    (candidate_dir / "build-evidence.json").write_text(
        json.dumps(build_evidence, indent=2), encoding="utf-8"
    )

    # Steps 9-10: Emit result JSON and exit.
    if result.get("valid"):
        print(json.dumps(_acceptance(dataset_slug, release_id, candidate_dir, result), indent=2))
        return 0

    print(json.dumps(_rejection(
        "publisher_validation",
        "publisher validation rejected the assembled candidate",
        dataset_slug=dataset_slug,
        release_id=release_id,
        candidate_dir=str(candidate_dir),
        publisher_validation=result,
    ), indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
