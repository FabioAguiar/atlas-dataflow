"""
Generic external candidate-support materializer for atlas-dataflow (Project Spec S0188).

Given an already-materialized ``external_fitted_model_materialization_result``
(status: "materialized", produced by
``pipeline.materialize_external_fitted_model``) and the Atlas-owned governed
execution contract / dataset context for the dataset it belongs to, produces
a reduced, truthful model-card artifact for a
``model_source_mode: validated_external_fitted_model`` release candidate.

This module is generic Atlas core: it contains no dataset-slug conditional
anywhere. It never loads or deserializes model bytes (joblib/pickle/sklearn
estimator state), never trains, never selects a model, never optimizes a
threshold, and never performs inference. It reads only the Atlas-owned
governed evidence already referenced by the materialization result --
``evidence_references``/``evidence_hashes`` -- re-verifying every referenced
file's current bytes against the materialization result's own hash bindings
before trusting its content. The produced model card carries explicit
external fitted-model provenance (``model_source_mode``) rather than a
fabricated Atlas ``training_run_identity``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_SOURCE_MODE = "validated_external_fitted_model"
MODEL_CARD_SCHEMA_VERSION = "model-card.v1"

_EVIDENCE_ROLES = ("training_parameter_record", "training_metrics", "model_selection_evidence")


class CandidateSupportBlocked(Exception):
    """Internal control-flow signal that short-circuits to a blocked result."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _boundary_confirmations() -> dict[str, bool]:
    return {
        "model_bytes_imported_or_deserialized": False,
        "atlas_training_invoked": False,
        "model_selection_performed": False,
        "threshold_optimized": False,
        "inference_performed": False,
        "atlas_training_run_identity_fabricated": False,
        "public_context_artifact_created": False,
        "visualizations_artifact_created": False,
        "external_project_root_retained": False,
    }


def _blocked_result(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    return {
        "status": "blocked",
        "created_at": _utc_now_iso(),
        "blocking_reasons": [
            {"code": code, "message": message, "field": field}
        ],
        "boundary_confirmations": _boundary_confirmations(),
    }


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CandidateSupportBlocked(
            "missing_required_field", f"{field} must be present as an object.", field
        )
    return data


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateSupportBlocked(
            "missing_required_field", f"{field} must be a non-empty string.", field
        )
    return value


def _safe_repo_relative_path(value: Any, field: str, repo_root: Path) -> Path:
    """Resolve a caller-supplied repository-relative path and prove
    repo_root containment. Rejects absolute paths and parent traversal
    before ever touching the filesystem."""
    if not isinstance(value, str) or not value:
        raise CandidateSupportBlocked(
            "missing_required_field", f"{field} must be a non-empty string.", field
        )
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CandidateSupportBlocked(
            "unsafe_path",
            f"{field} must be a safe, repository-relative path (no absolute path or parent "
            "traversal).",
            field,
        )
    resolved = (repo_root / path).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise CandidateSupportBlocked(
            "unsafe_path", f"{field} resolves outside repo_root.", field
        )
    return resolved


def _load_evidence_json(resolved_path: Path, role: str) -> dict[str, Any]:
    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CandidateSupportBlocked(
            "missing_referenced_evidence", f"{role} could not be read.", role
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CandidateSupportBlocked(
            "invalid_referenced_evidence_json", f"{role} is not valid JSON.", role
        ) from exc
    if not isinstance(data, dict):
        raise CandidateSupportBlocked(
            "invalid_referenced_evidence_json", f"{role} must be a JSON object.", role
        )
    return data


def materialize_external_candidate_support(
    *,
    dataset_slug: str,
    materialization_result: dict[str, Any],
    execution_contract: dict[str, Any],
    dataset_context: dict[str, Any],
    output_model_card_path: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize a reduced, truthful external candidate-support model card.

    ``materialization_result`` must be a ``status: "materialized"``
    ``external_fitted_model_materialization_result`` (produced by
    ``pipeline.materialize_external_fitted_model``); its own
    ``evidence_references``/``evidence_hashes`` are the sole source of the
    referenced training-parameter-record/training-metrics/model-selection
    evidence this function reads -- never a second, independently supplied
    raw external path. ``execution_contract``/``dataset_context`` are
    already-parsed Atlas-owned governed documents (not file paths). Writes
    exactly one runtime artifact, ``output_model_card_path`` (repository-
    relative, resolved beneath ``repo_root``), only on success; writes
    nothing on any validation failure.

    Returns ``{"status": "materialized", ..., "model_card_path": ...,
    "model_card_sha256": ...}`` or ``{"status": "blocked",
    "blocking_reasons": [...]}``. Never raises to the caller.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _repo_root()

    try:
        dataset_slug = _require_nonempty_string(dataset_slug, "dataset_slug")

        materialization_result = _require_mapping(materialization_result, "materialization_result")
        if materialization_result.get("status") != "materialized":
            raise CandidateSupportBlocked(
                "materialization_not_materialized",
                "materialization_result.status must be 'materialized'.",
                "materialization_result.status",
            )
        if materialization_result.get("model_source_mode") != MODEL_SOURCE_MODE:
            raise CandidateSupportBlocked(
                "invalid_model_source_mode",
                f"materialization_result.model_source_mode must be {MODEL_SOURCE_MODE!r}.",
                "materialization_result.model_source_mode",
            )

        materialization_dataset_slug = _require_mapping(
            materialization_result.get("dataset_identity"), "materialization_result.dataset_identity"
        ).get("dataset_slug")
        if materialization_dataset_slug != dataset_slug:
            raise CandidateSupportBlocked(
                "dataset_identity_mismatch",
                "materialization_result.dataset_identity.dataset_slug does not match dataset_slug.",
                "materialization_result.dataset_identity.dataset_slug",
            )

        execution_contract = _require_mapping(execution_contract, "execution_contract")
        if execution_contract.get("model_source_mode") != MODEL_SOURCE_MODE:
            raise CandidateSupportBlocked(
                "execution_contract_model_source_mode_invalid",
                f"execution_contract.model_source_mode must explicitly declare {MODEL_SOURCE_MODE!r}.",
                "execution_contract.model_source_mode",
            )
        execution_contract_dataset_id = execution_contract.get("dataset_id")
        if execution_contract_dataset_id != dataset_slug:
            raise CandidateSupportBlocked(
                "dataset_identity_mismatch",
                "execution_contract.dataset_id does not match dataset_slug.",
                "execution_contract.dataset_id",
            )

        dataset_context = _require_mapping(dataset_context, "dataset_context")
        dataset_context_slug = dataset_context.get("dataset_slug")
        if dataset_context_slug != dataset_slug:
            raise CandidateSupportBlocked(
                "dataset_identity_mismatch",
                "dataset_context.dataset_slug does not match dataset_slug.",
                "dataset_context.dataset_slug",
            )

        evidence_references = _require_mapping(
            materialization_result.get("evidence_references"), "materialization_result.evidence_references"
        )
        evidence_hashes = _require_mapping(
            materialization_result.get("evidence_hashes"), "materialization_result.evidence_hashes"
        )

        evidence_documents: dict[str, dict[str, Any]] = {}
        evidence_resolved_paths: dict[str, Path] = {}
        for role in _EVIDENCE_ROLES:
            path_field = f"{role}_path"
            hash_field = f"{role}_sha256"
            declared_path = evidence_references.get(path_field)
            expected_hash = evidence_hashes.get(hash_field)
            if not isinstance(expected_hash, str) or not expected_hash:
                raise CandidateSupportBlocked(
                    "missing_required_field",
                    f"materialization_result.evidence_hashes.{hash_field} must be a non-empty string.",
                    f"evidence_hashes.{hash_field}",
                )
            resolved = _safe_repo_relative_path(
                declared_path, f"evidence_references.{path_field}", resolved_repo_root
            )
            actual_hash = _sha256_file(resolved)
            if actual_hash is None:
                raise CandidateSupportBlocked(
                    "missing_referenced_evidence", f"{role} could not be read.", role
                )
            if actual_hash != expected_hash:
                raise CandidateSupportBlocked(
                    "referenced_evidence_hash_mismatch",
                    f"{role} bytes do not match materialization_result.evidence_hashes.{hash_field}.",
                    role,
                )
            evidence_resolved_paths[role] = resolved
            evidence_documents[role] = _load_evidence_json(resolved, role)

        training_record = evidence_documents["training_parameter_record"]
        training_record_slug = _require_mapping(
            training_record.get("dataset_identity"), "training_parameter_record.dataset_identity"
        ).get("dataset_slug")
        if training_record_slug != dataset_slug:
            raise CandidateSupportBlocked(
                "dataset_identity_mismatch",
                "training_parameter_record.dataset_identity.dataset_slug does not match dataset_slug.",
                "training_parameter_record.dataset_identity.dataset_slug",
            )

        model_family = training_record.get("model_family")
        estimator_identity = training_record.get("estimator_identity")
        model_state_fingerprint = materialization_result.get("model_state_fingerprint")

        output_resolved = _safe_repo_relative_path(
            output_model_card_path, "output_model_card_path", resolved_repo_root
        )

        now = _utc_now_iso()
        target_column = execution_contract.get("target_column")
        feature_columns = execution_contract.get("feature_columns")
        operational_readiness = materialization_result.get("operational_readiness")
        if not isinstance(operational_readiness, dict):
            operational_readiness = {}

        model_card: dict[str, Any] = {
            "schema_version": MODEL_CARD_SCHEMA_VERSION,
            "artifact_kind": "model_card",
            "created_at": now,
            "model_source_mode": MODEL_SOURCE_MODE,
            "dataset_identity": {"dataset_slug": dataset_slug},
            "model_summary": (
                f"{model_family or 'externally fitted'} model, validated outside Atlas and "
                f"materialized as governed evidence, for dataset {dataset_slug}"
                + (f" to predict {target_column}." if target_column else ".")
            ),
            "problem_type": "classification",
            "prediction_target": target_column,
            "input_features": feature_columns if isinstance(feature_columns, list) else [],
            "external_model_identity": {
                "model_family": model_family,
                "estimator_identity": estimator_identity,
                "model_state_fingerprint": model_state_fingerprint,
            },
            "intended_use": (
                "Governed external fitted-model candidate support, materialized for internal "
                "review from Atlas-owned governed evidence. Not yet reviewed or approved for "
                "public release, profile publication, or production decisioning."
            ),
            "limitations": [
                "The model was fitted outside Atlas; Atlas never trained, selected, or tuned it.",
                "Generated from governed external evidence only; independent validation is "
                "required before any downstream use.",
                f"Operational validity: {operational_readiness.get('operational_validity', 'unconfirmed')}.",
                (
                    "Operational threshold status: "
                    f"{(operational_readiness.get('operational_threshold') or {}).get('status', 'unresolved')}."
                ),
            ],
            "path_references": {
                "model_card_path": output_model_card_path,
                "training_parameter_record_reference": {
                    "path": evidence_references["training_parameter_record_path"],
                    "sha256": evidence_hashes["training_parameter_record_sha256"],
                },
                "training_metrics_reference": {
                    "path": evidence_references["training_metrics_path"],
                    "sha256": evidence_hashes["training_metrics_sha256"],
                },
                "model_selection_evidence_reference": {
                    "path": evidence_references["model_selection_evidence_path"],
                    "sha256": evidence_hashes["model_selection_evidence_sha256"],
                },
            },
            "hashes": {"algorithm": "sha256"},
            "data_notes": (
                "Reduced, deterministic external candidate-support model card. No raw dataset "
                "rows, model bytes, raw logs, raw runtime data, secrets, or notebook state are "
                "included."
            ),
            "evidence_policy": {
                "raw_api_payloads_prohibited": True,
                "raw_logs_prohibited": True,
                "raw_runtime_prohibited": True,
                "reduced_and_sanitized": True,
                "secrets_prohibited": True,
            },
            "model_card_boundary_confirmations": {
                "model_bytes_embedded": False,
                "notebook_state_embedded": False,
                "profile_publication_performed": False,
                "raw_dataset_embedded": False,
                "release_publication_performed": False,
                "atlas_training_run_identity_fabricated": False,
            },
        }

        output_resolved.parent.mkdir(parents=True, exist_ok=True)
        output_resolved.write_text(json.dumps(model_card, indent=2, sort_keys=True), encoding="utf-8")
        model_card_sha256 = _sha256_file(output_resolved)

        return {
            "status": "materialized",
            "created_at": now,
            "dataset_slug": dataset_slug,
            "model_card_path": output_model_card_path,
            "model_card_sha256": model_card_sha256,
            "boundary_confirmations": _boundary_confirmations(),
        }

    except CandidateSupportBlocked as exc:
        return _blocked_result(exc.code, exc.message, exc.field)
