"""
Generic external fitted-model materializer for atlas-dataflow (Project Spec S0181).

Completes the boundary S0180 already consumes but never installed a producer
for: given an already-validated, already-fitted external model
(Project Spec S0157, model_source_mode: validated_external_fitted_model) and
its governed S0157 evidence documents, produces a schema-valid
external_fitted_model_materialization_result -- directly consumable by
pipeline.generate_inference_bundle.materialize_governed_inference_bundle's
external branch (Project Spec S0180) -- by:

  1. verifying the source model bytes and every source evidence document
     against caller-supplied SHA-256 hashes before touching their contents;
  2. structurally validating the three governed source evidence documents
     against the existing pipeline/training-parameter-record.schema.json,
     pipeline/training-metrics.schema.json, and
     pipeline/model-selection-evidence.schema.json (all read-only, unmodified
     by this module) and requiring their exact S0157 external-profile
     schema_version constants;
  3. cross-checking dataset identity and model-state fingerprint consistency
     across all three evidence documents;
  4. copying the model bytes opaquely (never imported, never deserialized)
     and the evidence JSON verbatim into explicit, caller-supplied
     Atlas-owned repository-relative output paths, re-verifying every
     destination hash after the copy;
  5. returning a schema-valid external-fitted-model-materialization.v1
     result.

This module is generic Atlas core: it contains no dataset-slug conditional
anywhere. It never constructs an estimator, never calls fit/fit_transform,
never performs model selection or threshold optimization, never performs
inference, never imports or deserializes model bytes, never fabricates an
Atlas training-run identity or pipeline/training-runs/ path, and never
creates or recreates external-models/. Any precondition or integrity
failure returns a status: "blocked" result with a stable reason code
instead of raising to the caller or emitting a partial/inconsistent result.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "external-fitted-model-materialization.v1"
ARTIFACT_KIND = "external_fitted_model_materialization_result"
MODEL_SOURCE_MODE = "validated_external_fitted_model"

_TRAINING_PARAMETER_RECORD_EXTERNAL_VERSION = "training-parameter-record.external-fitted-model.v1"
_TRAINING_METRICS_EXTERNAL_VERSION = "training-metrics.external-fitted-model.v1"
_MODEL_SELECTION_EVIDENCE_EXTERNAL_VERSION = "model-selection-evidence.external-fitted-model.v1"

DATASET_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_RELATIVE_PATH_RE = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*//)(?!.*\\)(?![A-Za-z]:)"
    r"(?!pipeline/training-runs/)(?!external-models/)[A-Za-z0-9][A-Za-z0-9._/-]*[^/]$"
)

_EVIDENCE_ROLES = ("training_parameter_record", "training_metrics", "model_selection_evidence")


class MaterializationBlocked(Exception):
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


def _blocked_reason(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    reason: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        reason["field"] = field
    return reason


def _boundary_confirmations() -> dict[str, bool]:
    return {
        "atlas_training_invoked": False,
        "estimator_fit_or_fit_transform_called": False,
        "model_selection_performed": False,
        "threshold_optimized": False,
        "inference_performed": False,
        "model_bytes_imported_or_deserialized": False,
        "training_run_identity_fabricated": False,
        "external_models_created_or_recreated": False,
        "external_project_root_retained": False,
    }


def _blocked_result(reasons: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "blocked",
        "created_at": _utc_now_iso(),
        "blocking_reasons": reasons,
        "boundary_confirmations": _boundary_confirmations(),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MaterializationBlocked(
            "invalid_hash", f"{field} must be a lowercase SHA-256 hex digest.", field
        )
    return value


def _safe_relative_output_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_RELATIVE_PATH_RE.fullmatch(value):
        raise MaterializationBlocked(
            "unsafe_output_path",
            f"{field} must be a safe, repository-relative output path (no absolute path, parent "
            "traversal, pipeline/training-runs/, or external-models/ prefix).",
            field,
        )
    return value


def _load_source_json(path: Path, field: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MaterializationBlocked(
            "missing_source_evidence", f"{field} could not be read.", field
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MaterializationBlocked(
            "invalid_source_evidence_json", f"{field} is not valid JSON.", field
        ) from exc
    if not isinstance(data, dict):
        raise MaterializationBlocked(
            "invalid_source_evidence_json", f"{field} must be a JSON object.", field
        )
    return data


def _validate_against_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise MaterializationBlocked(
            "schema_validation_unavailable", "jsonschema is required for materialization.", label
        ) from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MaterializationBlocked(
            "missing_schema", f"{label} schema file could not be read.", label
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise MaterializationBlocked(
            "source_evidence_schema_invalid", f"{label}.{path}: {first.message}", f"{label}.{path}"
        )


def _require_mapping(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MaterializationBlocked(
            "missing_required_field", f"{field} must be present as an object.", field
        )
    return data


def materialize_external_fitted_model(
    *,
    dataset_slug: str,
    materialization_id: str,
    producer: str,
    source_model_path: str | Path,
    expected_source_model_sha256: str,
    source_training_parameter_record_path: str | Path,
    source_training_metrics_path: str | Path,
    source_model_selection_evidence_path: str | Path,
    expected_evidence_hashes: dict[str, str],
    runtime_compatibility: dict[str, Any],
    educational_threshold: dict[str, Any],
    final_test_completion: dict[str, Any],
    operational_readiness: dict[str, Any],
    output_model_artifact_path: str,
    output_training_parameter_record_path: str,
    output_training_metrics_path: str,
    output_model_selection_evidence_path: str,
    model_source_mode: str = MODEL_SOURCE_MODE,
    expected_model_state_fingerprint: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize a governed external fitted-model result from explicit governed inputs.

    Every path argument is caller-supplied and explicit; nothing is inferred
    from a notebook variable, hidden global, or glob. ``source_*`` paths may
    point anywhere readable (typically outside the repository, in the
    validated external handoff/projection lineage); ``output_*`` paths are
    always repository-relative and are the only locations this function
    writes to, under ``repo_root`` (defaults to the real repository root).

    Returns a dict conforming to
    ``pipeline/external-fitted-model-materialization.schema.json``: either a
    ``status: "materialized"`` result, or a ``status: "blocked"`` result
    carrying concrete, stable-coded ``blocking_reasons`` and never a partial
    or inconsistent materialization.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _repo_root()

    try:
        if model_source_mode != MODEL_SOURCE_MODE:
            raise MaterializationBlocked(
                "invalid_model_source_mode",
                f"model_source_mode must be {MODEL_SOURCE_MODE!r}.",
                "model_source_mode",
            )
        if not isinstance(dataset_slug, str) or not DATASET_SLUG_RE.fullmatch(dataset_slug):
            raise MaterializationBlocked(
                "invalid_dataset_identity", "dataset_slug is not a valid dataset slug.", "dataset_slug"
            )
        if not isinstance(materialization_id, str) or not materialization_id:
            raise MaterializationBlocked(
                "missing_required_field",
                "materialization_id must be a non-empty string.",
                "materialization_id",
            )
        if not isinstance(producer, str) or not producer:
            raise MaterializationBlocked(
                "missing_required_field", "producer must be a non-empty string.", "producer"
            )

        output_model_artifact_path = _safe_relative_output_path(
            output_model_artifact_path, "output_model_artifact_path"
        )
        output_training_parameter_record_path = _safe_relative_output_path(
            output_training_parameter_record_path, "output_training_parameter_record_path"
        )
        output_training_metrics_path = _safe_relative_output_path(
            output_training_metrics_path, "output_training_metrics_path"
        )
        output_model_selection_evidence_path = _safe_relative_output_path(
            output_model_selection_evidence_path, "output_model_selection_evidence_path"
        )

        resolved_source_model_path = Path(source_model_path)
        resolved_source_paths = {
            "training_parameter_record": Path(source_training_parameter_record_path),
            "training_metrics": Path(source_training_metrics_path),
            "model_selection_evidence": Path(source_model_selection_evidence_path),
        }

        # -- Verify source model bytes before any copy. --
        expected_source_model_sha256 = _require_sha256(
            expected_source_model_sha256, "expected_source_model_sha256"
        )
        actual_source_model_sha256 = _sha256_file(resolved_source_model_path)
        if actual_source_model_sha256 is None:
            raise MaterializationBlocked(
                "missing_source_model", "source_model_path could not be read.", "source_model_path"
            )
        if actual_source_model_sha256 != expected_source_model_sha256:
            raise MaterializationBlocked(
                "source_model_hash_mismatch",
                "Source model bytes do not match expected_source_model_sha256.",
                "source_model_path",
            )

        # -- Verify every source evidence document's bytes before projection. --
        if not isinstance(expected_evidence_hashes, dict):
            raise MaterializationBlocked(
                "missing_required_field",
                "expected_evidence_hashes must be an object keyed by evidence role.",
                "expected_evidence_hashes",
            )
        for role in _EVIDENCE_ROLES:
            expected_hash = _require_sha256(
                expected_evidence_hashes.get(role), f"expected_evidence_hashes.{role}"
            )
            actual_hash = _sha256_file(resolved_source_paths[role])
            if actual_hash is None:
                raise MaterializationBlocked(
                    "missing_source_evidence", f"{role} source file could not be read.", role
                )
            if actual_hash != expected_hash:
                raise MaterializationBlocked(
                    "source_evidence_hash_mismatch",
                    f"{role} bytes do not match expected_evidence_hashes.{role}.",
                    role,
                )

        training_record = _load_source_json(
            resolved_source_paths["training_parameter_record"], "training_parameter_record"
        )
        training_metrics = _load_source_json(
            resolved_source_paths["training_metrics"], "training_metrics"
        )
        model_selection = _load_source_json(
            resolved_source_paths["model_selection_evidence"], "model_selection_evidence"
        )

        _validate_against_schema(
            training_record,
            resolved_repo_root / "pipeline" / "training-parameter-record.schema.json",
            "training_parameter_record",
        )
        _validate_against_schema(
            training_metrics,
            resolved_repo_root / "pipeline" / "training-metrics.schema.json",
            "training_metrics",
        )
        _validate_against_schema(
            model_selection,
            resolved_repo_root / "pipeline" / "model-selection-evidence.schema.json",
            "model_selection_evidence",
        )

        if training_record.get("schema_version") != _TRAINING_PARAMETER_RECORD_EXTERNAL_VERSION:
            raise MaterializationBlocked(
                "invalid_external_evidence_profile",
                f"training_parameter_record must declare {_TRAINING_PARAMETER_RECORD_EXTERNAL_VERSION!r}.",
                "training_parameter_record.schema_version",
            )
        if training_metrics.get("schema_version") != _TRAINING_METRICS_EXTERNAL_VERSION:
            raise MaterializationBlocked(
                "invalid_external_evidence_profile",
                f"training_metrics must declare {_TRAINING_METRICS_EXTERNAL_VERSION!r}.",
                "training_metrics.schema_version",
            )
        if model_selection.get("schema_version") != _MODEL_SELECTION_EVIDENCE_EXTERNAL_VERSION:
            raise MaterializationBlocked(
                "invalid_external_evidence_profile",
                f"model_selection_evidence must declare {_MODEL_SELECTION_EVIDENCE_EXTERNAL_VERSION!r}.",
                "model_selection_evidence.schema_version",
            )

        record_slug = _require_mapping(
            training_record.get("dataset_identity"), "training_parameter_record.dataset_identity"
        ).get("dataset_slug")
        metrics_slug = _require_mapping(
            training_metrics.get("evidence_identity"), "training_metrics.evidence_identity"
        ).get("dataset_slug")
        selection_slug = _require_mapping(
            model_selection.get("dataset_identity"), "model_selection_evidence.dataset_identity"
        ).get("dataset_slug")
        for label, slug in (
            ("training_parameter_record", record_slug),
            ("training_metrics", metrics_slug),
            ("model_selection_evidence", selection_slug),
        ):
            if slug != dataset_slug:
                raise MaterializationBlocked(
                    "dataset_identity_mismatch",
                    f"{label} dataset_slug does not match the requested dataset_slug.",
                    f"{label}.dataset_slug",
                )

        record_fingerprint = _require_sha256(
            training_record.get("model_state_fingerprint"),
            "training_parameter_record.model_state_fingerprint",
        )
        selection_fingerprint = _require_mapping(
            model_selection.get("hashes"), "model_selection_evidence.hashes"
        ).get("model_state_fingerprint")
        if selection_fingerprint != record_fingerprint:
            raise MaterializationBlocked(
                "model_state_fingerprint_mismatch",
                "model_selection_evidence.hashes.model_state_fingerprint does not match "
                "training_parameter_record.model_state_fingerprint.",
                "model_selection_evidence.hashes.model_state_fingerprint",
            )
        if (
            expected_model_state_fingerprint is not None
            and expected_model_state_fingerprint != record_fingerprint
        ):
            raise MaterializationBlocked(
                "model_state_fingerprint_mismatch",
                "expected_model_state_fingerprint does not match "
                "training_parameter_record.model_state_fingerprint.",
                "expected_model_state_fingerprint",
            )

        record_model_ref = _require_mapping(
            training_record.get("model_artifact_reference"),
            "training_parameter_record.model_artifact_reference",
        )
        if record_model_ref.get("sha256") != actual_source_model_sha256:
            raise MaterializationBlocked(
                "stale_or_inconsistent_artifact",
                "training_parameter_record.model_artifact_reference.sha256 does not match the "
                "source model bytes.",
                "training_parameter_record.model_artifact_reference.sha256",
            )

        educational_threshold = _require_mapping(educational_threshold, "educational_threshold")
        threshold_value = educational_threshold.get("value")
        if isinstance(threshold_value, bool) or not isinstance(threshold_value, (int, float)):
            raise MaterializationBlocked(
                "missing_required_field", "educational_threshold.value must be a number.", "educational_threshold.value"
            )
        threshold_scenario = educational_threshold.get("scenario")
        if not isinstance(threshold_scenario, str) or not threshold_scenario:
            raise MaterializationBlocked(
                "missing_required_field",
                "educational_threshold.scenario must be a non-empty string.",
                "educational_threshold.scenario",
            )

        final_test_completion = _require_mapping(final_test_completion, "final_test_completion")
        for key in ("used_for_threshold_selection", "evaluation_count"):
            if key not in final_test_completion:
                raise MaterializationBlocked(
                    "missing_required_field",
                    f"final_test_completion.{key} is required.",
                    f"final_test_completion.{key}",
                )
        # Matches contracts/inference-bundle.schema.json's external_model_evidence
        # .final_test_completion const constraints exactly (used_for_threshold_selection:
        # false, evaluation_count: 1) -- checked here, before any bytes are written, so a
        # non-conforming caller input blocks deterministically instead of leaving copied
        # output files behind for a result that will fail its own schema self-validation.
        if final_test_completion.get("used_for_threshold_selection") is not False:
            raise MaterializationBlocked(
                "final_test_completion_not_eligible",
                "final_test_completion.used_for_threshold_selection must be false for a "
                "materialized result.",
                "final_test_completion.used_for_threshold_selection",
            )
        if final_test_completion.get("evaluation_count") != 1:
            raise MaterializationBlocked(
                "final_test_completion_not_eligible",
                "final_test_completion.evaluation_count must be exactly 1 for a materialized "
                "result.",
                "final_test_completion.evaluation_count",
            )

        operational_readiness = _require_mapping(operational_readiness, "operational_readiness")
        for key in (
            "educational_final_model_complete",
            "educational_inference_demo_ready",
            "operational_validity",
            "operational_threshold",
            "operational_prediction_available",
        ):
            if key not in operational_readiness:
                raise MaterializationBlocked(
                    "missing_required_field",
                    f"operational_readiness.{key} is required.",
                    f"operational_readiness.{key}",
                )

        runtime_compatibility = _require_mapping(runtime_compatibility, "runtime_compatibility")
        for key in ("serialization_format", "loader_strategy", "load_safety_confirmed"):
            if key not in runtime_compatibility:
                raise MaterializationBlocked(
                    "missing_required_field",
                    f"runtime_compatibility.{key} is required.",
                    f"runtime_compatibility.{key}",
                )

        # -- Copy governed bytes opaquely into the explicit Atlas-owned output paths. --
        # The model is never opened, imported, or deserialized here: it is
        # read and written as raw bytes only.
        output_model_full = resolved_repo_root / output_model_artifact_path
        source_model_bytes = resolved_source_model_path.read_bytes()
        output_model_full.parent.mkdir(parents=True, exist_ok=True)
        output_model_full.write_bytes(source_model_bytes)
        destination_model_sha256 = _sha256_file(output_model_full)
        if destination_model_sha256 != actual_source_model_sha256:
            raise MaterializationBlocked(
                "destination_model_hash_mismatch",
                "Copied model bytes do not match the source model bytes.",
                "output_model_artifact_path",
            )

        output_record_full = resolved_repo_root / output_training_parameter_record_path
        output_record_full.parent.mkdir(parents=True, exist_ok=True)
        output_record_full.write_text(
            json.dumps(training_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        output_metrics_full = resolved_repo_root / output_training_metrics_path
        output_metrics_full.parent.mkdir(parents=True, exist_ok=True)
        output_metrics_full.write_text(
            json.dumps(training_metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        output_selection_full = resolved_repo_root / output_model_selection_evidence_path
        output_selection_full.parent.mkdir(parents=True, exist_ok=True)
        output_selection_full.write_text(
            json.dumps(model_selection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "status": "materialized",
            "created_at": _utc_now_iso(),
            "materialization_identity": {
                "materialization_id": materialization_id,
                "producer": producer,
            },
            "model_source_mode": MODEL_SOURCE_MODE,
            "dataset_identity": {"dataset_slug": dataset_slug},
            "evidence_references": {
                "training_parameter_record_path": output_training_parameter_record_path,
                "training_metrics_path": output_training_metrics_path,
                "model_selection_evidence_path": output_model_selection_evidence_path,
            },
            "evidence_hashes": {
                "training_parameter_record_sha256": _sha256_file(output_record_full),
                "training_metrics_sha256": _sha256_file(output_metrics_full),
                "model_selection_evidence_sha256": _sha256_file(output_selection_full),
            },
            "model_artifact_path": output_model_artifact_path,
            "model_artifact_sha256": destination_model_sha256,
            "model_state_fingerprint": record_fingerprint,
            "runtime_compatibility": {
                "serialization_format": runtime_compatibility["serialization_format"],
                "loader_strategy": runtime_compatibility["loader_strategy"],
                "load_safety_confirmed": bool(runtime_compatibility["load_safety_confirmed"]),
            },
            "educational_threshold": {
                "value": threshold_value,
                "scenario": threshold_scenario,
            },
            "final_test_completion": {
                "used_for_threshold_selection": bool(
                    final_test_completion["used_for_threshold_selection"]
                ),
                "evaluation_count": final_test_completion["evaluation_count"],
            },
            "operational_readiness": {
                "educational_final_model_complete": bool(
                    operational_readiness["educational_final_model_complete"]
                ),
                "educational_inference_demo_ready": bool(
                    operational_readiness["educational_inference_demo_ready"]
                ),
                "operational_validity": operational_readiness["operational_validity"],
                "operational_threshold": operational_readiness["operational_threshold"],
                "operational_prediction_available": bool(
                    operational_readiness["operational_prediction_available"]
                ),
            },
            "boundary_confirmations": _boundary_confirmations(),
        }

        _validate_against_schema(
            result,
            resolved_repo_root / "pipeline" / "external-fitted-model-materialization.schema.json",
            "external_fitted_model_materialization_result",
        )
        return result

    except MaterializationBlocked as exc:
        return _blocked_result([_blocked_reason(exc.code, exc.message, exc.field)])
