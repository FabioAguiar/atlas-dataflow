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
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_CANDIDATE_ARTIFACT_MAPPINGS = [
    ("promoted_contracts.runtime_contract", "contracts/runtime-contract.json"),
    ("promoted_contracts.public_contract", "contracts/public-contract.json"),
    ("training_metrics", "metrics/metrics.json"),
    ("inference_bundle", "predictions/bundle.json"),
    ("model_card", "model-card.json"),
    ("public_context", "public-context.json"),
    # Project Spec S0128: the release-bound, deterministic analytical
    # visualizations artifact (Target Distribution and Feature Importance).
    ("visualizations", "visualizations/visualizations.json"),
    # Project Spec S0107: the release-bound governed model artifact. Unlike
    # every other entry above, this is a private binary, not a public JSON
    # artifact -- the mapping only decides where candidate assembly copies
    # it, not its publisher visibility (declared separately in
    # _build_release_candidate()'s artifact_roles.model_artifact below).
    ("model_artifact", "models/model.pkl"),
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
    "visualizations",
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
    "visualizations",
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

    resolved = repo_root.resolve() / path
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
    resolved_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()
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


# Training handoff reference normalization (Project Spec S0031). Maps each
# training-related release-candidate-input.v1 role to the training_result
# summary field (produced by pipeline.training.TrainingResult.to_summary())
# that reports its explicit, repository-relative path.
_TRAINING_HANDOFF_ROLE_TO_RESULT_FIELD = {
    "training_parameter_record": "training_parameter_record_path",
    "model_artifact": "serialized_model_path",
    "training_metrics": "metrics_path",
    "model_card": "model_card_path",
    # Project Spec S0128.
    "visualizations": "analytical_visualizations_path",
}


def normalize_training_handoff_references(
    training_run_materialization_result: Any,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Derive the four training-related handoff roles from a governed
    `training_run_materialization_result.v1` object (Project Spec S0026).

    Reads only the result's own `status` and `training_result` summary
    fields — never the raw dataset, notebook memory, hidden variables, a
    glob over `pipeline/training-runs/`, or publisher/registry state. A
    role is included in the returned `role_paths` only when its result
    field is an explicit repository-relative path string that passes the
    same path-safety/placeholder checks used by
    `build_release_candidate_handoff_readiness` (never missing, absolute,
    parent-traversal, fixture-only, or placeholder-only). A role missing
    from `role_paths` means the caller must keep its own pre-training
    placeholder for that role and must never report it as ready.
    """
    resolved_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()

    if not isinstance(training_run_materialization_result, dict):
        return {"source_status": "malformed_training_result", "role_paths": {}, "rejected_roles": {}}

    status = training_run_materialization_result.get("status")
    if status != "trained":
        return {
            "source_status": status if isinstance(status, str) else "malformed_training_result",
            "role_paths": {},
            "rejected_roles": {},
        }

    training_result = training_run_materialization_result.get("training_result")
    if not isinstance(training_result, dict):
        return {
            "source_status": "trained_without_training_result",
            "role_paths": {},
            "rejected_roles": {},
        }

    role_paths: dict[str, str] = {}
    rejected_roles: dict[str, str] = {}
    for role, result_field in _TRAINING_HANDOFF_ROLE_TO_RESULT_FIELD.items():
        path_value = training_result.get(result_field)
        classification = _classify_handoff_reference(role, path_value, resolved_repo_root)
        if classification["ready"]:
            role_paths[role] = path_value
        else:
            rejected_roles[role] = classification["reason"]

    return {"source_status": "trained", "role_paths": role_paths, "rejected_roles": rejected_roles}


# Release-candidate input assembly (Project Spec S0032). Fixed governance
# metadata for each release-candidate-input.v1 artifact role, matching the
# consts required by pipeline/release-candidate-input.schema.json and the
# values demonstrated by pipeline/examples/release-candidate-input.example.json.
# A `contract_version` of None means the role has no schema-mandated const --
# it is instead read from the real artifact's own `contract_version` or
# `schema_version` field, so the input document reports the artifact's real
# declared version rather than a fabricated one.
_ARTIFACT_INPUT_ROLE_GOVERNANCE: dict[str, dict[str, str | None]] = {
    "discovery_evidence": {
        "source_stage": "M22",
        "contract_version": "dataset-discovery-evidence.v1",
        "public_projection": "internal_only",
        "evidence_classification": "internal_evidence",
    },
    "execution_contract": {
        "source_stage": "M23",
        "contract_version": None,
        "public_projection": "internal_only",
        "evidence_classification": "not_evidence",
    },
    "runtime_contract": {
        "source_stage": "M23",
        "contract_version": None,
        "public_projection": "internal_only",
        "evidence_classification": "not_evidence",
    },
    "public_contract": {
        "source_stage": "M23",
        "contract_version": None,
        "public_projection": "public_artifact",
        "evidence_classification": "public_artifact",
    },
    "preparation_recipe": {
        "source_stage": "M22",
        "contract_version": "candidate-preparation-recipe.v1",
        "public_projection": "internal_only",
        "evidence_classification": "internal_evidence",
    },
    "prepared_data_metadata": {
        "source_stage": "M23",
        "contract_version": None,
        "public_projection": "internal_only",
        "evidence_classification": "internal_traceability_reference",
    },
    "training_parameter_record": {
        "source_stage": "M24",
        "contract_version": "training-parameter-record.v1",
        "public_projection": "internal_only",
        "evidence_classification": "internal_traceability_reference",
    },
    "model_artifact": {
        "source_stage": "M24",
        "contract_version": "model_artifact_reference",
        "public_projection": "public_reference_only",
        "evidence_classification": "not_evidence",
    },
    "training_metrics": {
        "source_stage": "M24",
        "contract_version": "training-metrics.v1",
        "public_projection": "public_artifact",
        "evidence_classification": "public_artifact",
    },
    "model_card": {
        "source_stage": "M24",
        "contract_version": None,
        "public_projection": "public_artifact",
        "evidence_classification": "public_artifact",
    },
    "public_context": {
        "source_stage": "M23",
        "contract_version": None,
        "public_projection": "public_artifact",
        "evidence_classification": "public_artifact",
    },
    "visualizations": {
        "source_stage": "M24",
        "contract_version": "analytical-visualizations.v1",
        "public_projection": "public_artifact",
        "evidence_classification": "public_artifact",
    },
    "inference_bundle": {
        "source_stage": "M25",
        "contract_version": "inference_bundle.v1",
        "public_projection": "public_reference_only",
        "evidence_classification": "not_evidence",
    },
}

# Dataset-independent sections of release-candidate-input.v1: identical for
# every dataset, so they are declared once here rather than rebuilt per call.
_CANDIDATE_INPUT_CANDIDATE_MAPPING = {
    "candidate_layout_schema": "pipeline/candidate-layout.schema.json",
    "publisher_release_candidate_schema": "publisher/release-candidate.schema.json",
    "publisher_release_manifest_schema": "publisher/release-manifest.schema.json",
    "publisher_validation_schema": "publisher/validation/release-candidate-validation.schema.json",
    "role_mappings": [
        {
            "input_role": "promoted_contracts",
            "candidate_role": "contracts",
            "publisher_role": "contracts",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "training_metrics",
            "candidate_role": "metrics",
            "publisher_role": "metrics",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "model_card",
            "candidate_role": "model_card",
            "publisher_role": "model_card",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "public_context",
            "candidate_role": "public_context",
            "publisher_role": "public_context",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "inference_bundle",
            "candidate_role": "predictive_bundle",
            "publisher_role": "predictive_bundle",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "prepared_data_metadata",
            "candidate_role": "candidate_metadata",
            "publisher_role": "candidate_metadata",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "visualizations",
            "candidate_role": "visualizations",
            "publisher_role": "visualizations",
            "mapping_requirement": "must_map_to_candidate_artifact_role",
        },
        {
            "input_role": "internal_evidence_references",
            "candidate_role": "build_evidence",
            "publisher_role": None,
            "mapping_requirement": "must_remain_internal_evidence",
        },
    ],
}

_CANDIDATE_INPUT_CLASSIFICATION_POLICY = {
    "missing_required_input": "reject",
    "fixture_only_required_input": "reject",
    "placeholder_only_required_input": "reject",
    "unsafe_public_projection": "reject",
    "internal_absolute_path_in_public_reference": "reject",
}

_CANDIDATE_INPUT_BOUNDARY_CONFIRMATIONS = {
    "candidate_assembly_performed": False,
    "publisher_validation_performed": False,
    "manifest_generation_performed": False,
    "promotion_performed": False,
    "registry_activation_performed": False,
    "runtime_inference_performed": False,
    "model_training_performed": False,
    "raw_artifact_contents_embedded": False,
    "raw_logs_persisted": False,
    "raw_runtime_persisted": False,
    "raw_api_payloads_persisted": False,
    "secrets_persisted": False,
    "public_artifacts_include_internal_evidence": False,
}

_TRAINING_RUN_ID_PATTERN = re.compile(r"^train-(?P<timestamp>[0-9]{8}T[0-9]{6}Z)$")


def derive_deterministic_release_id(training_run_id: str) -> str:
    """Derive a schema-safe `release_id` from a governed `train-<timestamp>Z`
    training run id (Project Spec S0032).

    Never invents a release_id from a milestone tag, notebook counter, or a
    reused static fixture value -- the id is always literally traceable back
    to the training run timestamp that produced its model artifact,
    lowercased to satisfy `release-candidate-input.schema.json`'s
    `release_id` pattern (lowercase alphanumerics and `-._` separators only).
    """
    match = _TRAINING_RUN_ID_PATTERN.match(training_run_id)
    if not match:
        raise ValueError(
            f"training_run_id must match train-<timestamp>Z, got: {training_run_id!r}"
        )
    return f"release-{match.group('timestamp').lower()}"


def _read_declared_contract_version(resolved_path: Path) -> str:
    content = json.loads(resolved_path.read_text(encoding="utf-8"))
    for key in ("contract_version", "schema_version"):
        value = content.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError(
        f"{resolved_path} has no string 'contract_version' or 'schema_version' field"
    )


def _build_artifact_input(role: str, path_value: str, repo_root: Path) -> dict[str, Any]:
    governance = _ARTIFACT_INPUT_ROLE_GOVERNANCE[role]
    resolved = repo_root / path_value
    contract_version = governance["contract_version"] or _read_declared_contract_version(resolved)
    return {
        "role": role,
        "required": True,
        "source_stage": governance["source_stage"],
        "path": path_value,
        "contract_version": contract_version,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "hash_policy": "sha256_required",
        "public_projection": governance["public_projection"],
        "evidence_classification": governance["evidence_classification"],
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
        "availability_status": "real_dataflow_artifact",
    }


def build_release_candidate_input(
    *,
    dataset_slug: str,
    release_id: str,
    source_run_id: str,
    artifact_references: dict[str, str],
    repo_root: Path | str | None = None,
    release_version: str = "1.0.0-rc.1",
    producer: str = "pipeline/assemble_candidate.py",
    dataset_title: str | None = None,
) -> dict[str, Any]:
    """Build a `release-candidate-input.v1` payload conforming to
    `pipeline/release-candidate-input.schema.json` from explicit,
    repository-relative artifact references (Project Spec S0032).

    `artifact_references` must map every role in `_HANDOFF_REQUIRED_ROLES` to
    an explicit path string -- the same shape accepted by
    `build_release_candidate_handoff_readiness`. This function re-runs that
    same readiness check itself and raises `ValueError` if any role is not
    ready, so it can never build an input document from a missing,
    fixture-only, or placeholder-only artifact even if a caller forgot to
    check readiness first. It never infers a path from a notebook variable,
    raw dataset, hidden state, or a glob over `pipeline/training-runs/`.
    """
    resolved_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()
    readiness = build_release_candidate_handoff_readiness(
        artifact_references, repo_root=resolved_repo_root
    )
    if not readiness["is_release_candidate_input_ready"]:
        raise ValueError(
            "release-candidate-input cannot be built: handoff readiness is not "
            f"satisfied ({readiness['blocking_reasons']})"
        )

    discovery_evidence_input = _build_artifact_input(
        "discovery_evidence", artifact_references["discovery_evidence"], resolved_repo_root
    )
    training_parameter_record_input = _build_artifact_input(
        "training_parameter_record",
        artifact_references["training_parameter_record"],
        resolved_repo_root,
    )

    artifact_inputs = {
        "discovery_evidence": discovery_evidence_input,
        "promoted_contracts": {
            "execution_contract": _build_artifact_input(
                "execution_contract", artifact_references["execution_contract"], resolved_repo_root
            ),
            "runtime_contract": _build_artifact_input(
                "runtime_contract", artifact_references["runtime_contract"], resolved_repo_root
            ),
            "public_contract": _build_artifact_input(
                "public_contract", artifact_references["public_contract"], resolved_repo_root
            ),
        },
        "preparation_recipe": _build_artifact_input(
            "preparation_recipe", artifact_references["preparation_recipe"], resolved_repo_root
        ),
        "prepared_data_metadata": _build_artifact_input(
            "prepared_data_metadata",
            artifact_references["prepared_data_metadata"],
            resolved_repo_root,
        ),
        "training_parameter_record": training_parameter_record_input,
        "model_artifact": _build_artifact_input(
            "model_artifact", artifact_references["model_artifact"], resolved_repo_root
        ),
        "training_metrics": _build_artifact_input(
            "training_metrics", artifact_references["training_metrics"], resolved_repo_root
        ),
        "model_card": _build_artifact_input(
            "model_card", artifact_references["model_card"], resolved_repo_root
        ),
        "public_context": _build_artifact_input(
            "public_context", artifact_references["public_context"], resolved_repo_root
        ),
        "visualizations": _build_artifact_input(
            "visualizations", artifact_references["visualizations"], resolved_repo_root
        ),
        "inference_bundle": _build_artifact_input(
            "inference_bundle", artifact_references["inference_bundle"], resolved_repo_root
        ),
        "internal_evidence_references": [
            {
                "role": "discovery_evidence",
                "path": discovery_evidence_input["path"],
                "sha256": discovery_evidence_input["sha256"],
                "source_stage": "M22",
                "evidence_classification": "internal_evidence",
                "public_projection": "internal_only",
            },
            {
                "role": "training_evidence",
                "path": training_parameter_record_input["path"],
                "sha256": training_parameter_record_input["sha256"],
                "source_stage": "M24",
                "evidence_classification": "internal_evidence",
                "public_projection": "internal_only",
            },
        ],
    }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "contract_version": "release-candidate-input.v1",
        "input_kind": "release_candidate_input",
        "dataset_identity": {
            "dataset_slug": dataset_slug,
            "dataset_title": dataset_title or dataset_slug.replace("-", " ").title(),
        },
        "release_identity": {
            "release_id": release_id,
            "release_version": release_version,
            "created_at": now,
        },
        "source_run": {
            "run_id": source_run_id,
            "producer": producer,
            "created_at": now,
        },
        "artifact_inputs": artifact_inputs,
        "candidate_mapping": _CANDIDATE_INPUT_CANDIDATE_MAPPING,
        "classification_policy": _CANDIDATE_INPUT_CLASSIFICATION_POLICY,
        "boundary_confirmations": _CANDIDATE_INPUT_BOUNDARY_CONFIRMATIONS,
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
            # Project Spec S0099: a distinct manifest-visible role for the
            # public contract, separate from the "contracts" (runtime) role
            # above -- previously the physical file was copied into the
            # candidate directory (_CANDIDATE_ARTIFACT_MAPPINGS) but never
            # declared as its own artifact_roles entry, so
            # publisher/manifest.py had no role to read it from and the
            # active release manifest never carried a public_contract
            # artifact at all.
            "public_contract": {
                "role": "public_contract",
                "path": "contracts/public-contract.json",
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
            # Project Spec S0128: the release-bound, deterministic analytical
            # visualizations artifact (Target Distribution and Feature
            # Importance), produced during governed training.
            "visualizations": {
                "role": "visualizations",
                "path": "visualizations/visualizations.json",
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
            # Project Spec S0107: the release-bound governed model artifact,
            # distinct from predictive_bundle (a JSON descriptor), model_card
            # (public documentation), and training evidence (not a runtime
            # model). Binary; excluded from publisher JSON-schema
            # compatibility checks.
            "model_artifact": {
                "role": "model_artifact",
                "path": "models/model.pkl",
                "required": True,
                "media_type": "application/octet-stream",
            },
        },
        "candidate_metadata": {
            "assembled_by": "pipeline/assemble_candidate.py",
            "assembled_at": now,
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": [
                    "contracts",
                    "public_contract",
                    "predictive_bundle",
                    "metrics",
                    "model_card",
                    "public_context",
                    "visualizations",
                    "manifest_input",
                    "candidate_metadata",
                    "model_artifact",
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
    for input_path, output_path in _CANDIDATE_ARTIFACT_MAPPINGS:
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


def assemble_release_candidate(
    candidate_input: dict[str, Any],
    output_dir: str | Path,
    *,
    repo_root: Path | str | None = None,
    source_input_label: str = "release-candidate-input",
) -> dict[str, Any]:
    """Assemble a publisher-compatible candidate from an in-memory
    `release-candidate-input.v1` dict.

    Shared by `main()`'s CLI path (which loads the input from a JSON file
    first) and any other governed in-process caller, for example a dataset
    authoring notebook, so both paths run identical validation, copy, and
    publisher-validation logic. Never reads `candidate_input` from anywhere
    other than the argument passed in.
    """
    resolved_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()

    # Step 1: Extract stable identity and validate the release-candidate-input.
    dataset_slug, release_id = _input_identity(candidate_input)
    input_errors = _validate_candidate_input(candidate_input)
    if input_errors:
        return _rejection(
            "candidate_input_parse",
            "release-candidate-input JSON failed required assembly checks",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=None,
            validation_errors=input_errors,
        )

    # Step 2: Construct candidate_dir and assert it is under releases/candidates/.
    candidate_dir = (Path(output_dir) / dataset_slug / release_id).resolve()
    staging_prefix = (resolved_repo_root / _CANDIDATE_STAGING_PREFIX).resolve()
    if not candidate_dir.is_relative_to(staging_prefix):
        return _rejection(
            "staging_path_violation",
            f"candidate_dir must be under {_CANDIDATE_STAGING_PREFIX}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
        )

    # Step 3: Verify all required governed artifacts are present.
    missing = _missing_required_artifacts(candidate_input, resolved_repo_root)
    if missing:
        return _rejection(
            "candidate_artifact_missing",
            f"required governed artifacts missing: {missing}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
            missing_paths=missing,
        )

    # Step 4: Create candidate_dir and necessary subdirectories.
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Step 5: Copy each publisher-visible governed artifact to the candidate directory.
    assembled = []
    for artifact, output_path in _required_public_artifacts(candidate_input):
        dst = candidate_dir / output_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_resolve_repo_relative(artifact["path"], resolved_repo_root), dst)
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
    sys.path.insert(0, str(resolved_repo_root))
    from publisher import validate  # noqa: PLC0415
    result = validate.validate_candidate_file(candidate_dir)

    # Step 8: Write reduced build-evidence.json (pipeline-internal; NOT in artifact_roles).
    build_evidence = _build_assembly_evidence(
        candidate_input,
        source_input_label,
        result,
        assembled,
    )
    (candidate_dir / "build-evidence.json").write_text(
        json.dumps(build_evidence, indent=2), encoding="utf-8"
    )

    # Steps 9-10: Return acceptance or rejection result.
    if result.get("valid"):
        return _acceptance(dataset_slug, release_id, candidate_dir, result)

    return _rejection(
        "publisher_validation",
        "publisher validation rejected the assembled candidate",
        dataset_slug=dataset_slug,
        release_id=release_id,
        candidate_dir=str(candidate_dir),
        publisher_validation=result,
    )


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

    # Load release-candidate-input JSON before delegating to the shared
    # in-process assembly path.
    candidate_input, load_err = _load_candidate_input(args.candidate_input)
    if load_err:
        phase = "candidate_input_read" if "not found" in load_err else "candidate_input_parse"
        print(json.dumps(_rejection(
            phase, load_err,
            dataset_slug=None, release_id=None, candidate_dir=None,
        ), indent=2))
        return 1

    result = assemble_release_candidate(
        candidate_input,
        args.output_dir,
        repo_root=_REPO_ROOT,
        source_input_label=args.candidate_input,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
