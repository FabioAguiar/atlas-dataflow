"""
Generic external analytical-visualization materializer for atlas-dataflow (Project Spec S0193).

Given an already-materialized ``external_fitted_model_materialization_result``
(status: "materialized", produced by
``pipeline.materialize_external_fitted_model``) and one already
hash-verified external visual-evidence payload (the canonical notebook's own
safe-relative-path + SHA-256 verification boundary against
``external-evidence-index.v1`` has already run before this module is ever
called -- see ``pipeline.materialize_external_candidate_support`` for the
same evidence-boundary convention), produces a release-candidate-compatible
``analytical-visualizations.external-fitted-model.v1`` artifact (Target
Distribution and Feature Importance).

This module is generic Atlas core: it contains no dataset-slug conditional
anywhere. It never loads or deserializes model bytes (joblib/pickle/sklearn
estimator state), never imports scikit-learn, never computes or recomputes
feature importance or permutation importance, never trains, never performs
model selection, never performs inference, and never performs EDA. It never
reads the external project independently of the caller's already-verified
evidence boundary -- ``external_visual_evidence`` is a parsed dict handed in
by the caller, not a path this module resolves itself. The only filesystem
writes this module performs are the single governed output artifact beneath
the caller-supplied ``output_visualizations_path``, and it never reads or
reuses a historical release's ``visualizations.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_SOURCE_MODE = "validated_external_fitted_model"
VISUALIZATIONS_SCHEMA_VERSION = "analytical-visualizations.external-fitted-model.v1"
ARTIFACT_KIND = "analytical_visualizations"

_MODEL_FAMILIES = ("hist_gradient_boosting", "gradient_boosting", "random_forest", "logistic_regression")
_PUBLIC_ROW_LIMIT = 10


class VisualizationsMaterializationBlocked(Exception):
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
        "feature_importance_computed_by_atlas": False,
        "permutation_importance_computed": False,
        "atlas_training_invoked": False,
        "model_selection_performed": False,
        "eda_performed": False,
        "historical_visualization_reused": False,
        "external_project_root_retained": False,
    }


def _blocked_result(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    reason: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        reason["field"] = field
    return {
        "status": "blocked",
        "created_at": _utc_now_iso(),
        "blocking_reasons": [reason],
        "boundary_confirmations": _boundary_confirmations(),
    }


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be present as an object.", field
        )
    return data


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be a non-empty string.", field
        )
    return value


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be a positive integer.", field
        )
    return value


def _require_non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be a non-negative integer.", field
        )
    return value


def _safe_repo_relative_path(value: Any, field: str, repo_root: Path) -> Path:
    """Resolve a caller-supplied repository-relative path and prove
    repo_root containment. Rejects absolute paths and parent traversal
    before ever touching the filesystem."""
    if not isinstance(value, str) or not value:
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be a non-empty string.", field
        )
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise VisualizationsMaterializationBlocked(
            "unsafe_path",
            f"{field} must be a safe, repository-relative path (no absolute path or parent "
            "traversal).",
            field,
        )
    resolved = (repo_root / path).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise VisualizationsMaterializationBlocked(
            "unsafe_path", f"{field} resolves outside repo_root.", field
        )
    return resolved


def _safe_external_evidence_reference(value: Any, field: str) -> str:
    """Structurally validate the already-verified external-evidence
    reference string this module embeds into the output artifact. This
    module never resolves or reads this reference itself -- the notebook's
    own external evidence boundary already did -- but it never trusts an
    unsafe string into a durable artifact either."""
    if not isinstance(value, str) or not value:
        raise VisualizationsMaterializationBlocked(
            "unsafe_path", f"{field} must be a non-empty string.", field
        )
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or value.startswith(("/", "file://", "//"))
    ):
        raise VisualizationsMaterializationBlocked(
            "unsafe_path",
            f"{field} must be a safe relative reference (no absolute path, parent traversal, "
            "or backslashes).",
            field,
        )
    return value


def _lowercase_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VisualizationsMaterializationBlocked(
            "invalid_hash", f"{field} must be a lowercase SHA-256 hex digest.", field
        )
    return value


def _finite_non_negative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _chart_data_points(rows: Any, field: str, *, max_items: int | None = None) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise VisualizationsMaterializationBlocked(
            "missing_required_field", f"{field} must be a non-empty array.", field
        )
    if max_items is not None and len(rows) > max_items:
        raise VisualizationsMaterializationBlocked(
            "chart_data_not_bounded",
            f"{field} has {len(rows)} entries, exceeding the public row limit of {max_items}.",
            field,
        )
    points: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise VisualizationsMaterializationBlocked(
                "invalid_chart_data", f"{field}[{index}] must be an object.", field
            )
        name = row.get("name")
        value = row.get("value")
        if not isinstance(name, str) or not name:
            raise VisualizationsMaterializationBlocked(
                "invalid_chart_data", f"{field}[{index}].name must be a non-empty string.", field
            )
        if not _finite_non_negative(value):
            raise VisualizationsMaterializationBlocked(
                "invalid_chart_data",
                f"{field}[{index}].value must be a finite, non-negative number.",
                field,
            )
        points.append({"name": name, "value": value})
    return points


def materialize_external_analytical_visualizations(
    *,
    dataset_slug: str,
    materialization_result: dict[str, Any],
    external_visual_evidence: dict[str, Any],
    external_evidence_reference: str,
    external_evidence_sha256: str,
    output_visualizations_path: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize a reduced, truthful external analytical-visualizations artifact.

    ``materialization_result`` must be a ``status: "materialized"``
    ``external_fitted_model_materialization_result`` (produced by
    ``pipeline.materialize_external_fitted_model``); its own
    ``evidence_references``/``evidence_hashes`` are the sole source this
    function reads to bind the artifact's ``model_family`` to the already
    hash-verified, governed ``training_parameter_record`` -- never a second,
    independently supplied value. ``external_visual_evidence`` is the
    already parsed, already hash-verified external visual-evidence payload
    (the caller's evidence-index verification boundary already ran);
    ``external_evidence_reference``/``external_evidence_sha256`` are the
    same relative-path/hash pair from that verification, embedded into the
    output artifact's provenance -- never the absolute external project
    root. Writes exactly one runtime artifact,
    ``output_visualizations_path`` (repository-relative, resolved beneath
    ``repo_root``), only on success; writes nothing on any validation
    failure.

    Returns ``{"status": "materialized", ..., "visualizations_path": ...,
    "visualizations_sha256": ...}`` or ``{"status": "blocked",
    "blocking_reasons": [...]}``. Never raises to the caller.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _repo_root()

    try:
        dataset_slug = _require_nonempty_string(dataset_slug, "dataset_slug")

        materialization_result = _require_mapping(materialization_result, "materialization_result")
        if materialization_result.get("status") != "materialized":
            raise VisualizationsMaterializationBlocked(
                "materialization_not_materialized",
                "materialization_result.status must be 'materialized'.",
                "materialization_result.status",
            )
        if materialization_result.get("model_source_mode") != MODEL_SOURCE_MODE:
            raise VisualizationsMaterializationBlocked(
                "invalid_model_source_mode",
                f"materialization_result.model_source_mode must be {MODEL_SOURCE_MODE!r}.",
                "materialization_result.model_source_mode",
            )

        materialization_dataset_slug = _require_mapping(
            materialization_result.get("dataset_identity"), "materialization_result.dataset_identity"
        ).get("dataset_slug")
        if materialization_dataset_slug != dataset_slug:
            raise VisualizationsMaterializationBlocked(
                "dataset_identity_mismatch",
                "materialization_result.dataset_identity.dataset_slug does not match dataset_slug.",
                "materialization_result.dataset_identity.dataset_slug",
            )

        # Re-verify and read the training_parameter_record referenced by the
        # materialization result -- exactly the same evidence re-verification
        # convention as pipeline.materialize_external_candidate_support --
        # to bind model_family to real, already-governed Atlas evidence
        # rather than a value invented for this call.
        evidence_references = _require_mapping(
            materialization_result.get("evidence_references"), "materialization_result.evidence_references"
        )
        evidence_hashes = _require_mapping(
            materialization_result.get("evidence_hashes"), "materialization_result.evidence_hashes"
        )
        record_path_value = evidence_references.get("training_parameter_record_path")
        record_expected_hash = evidence_hashes.get("training_parameter_record_sha256")
        if not isinstance(record_expected_hash, str) or not record_expected_hash:
            raise VisualizationsMaterializationBlocked(
                "missing_required_field",
                "materialization_result.evidence_hashes.training_parameter_record_sha256 must be "
                "a non-empty string.",
                "evidence_hashes.training_parameter_record_sha256",
            )
        record_resolved = _safe_repo_relative_path(
            record_path_value, "evidence_references.training_parameter_record_path", resolved_repo_root
        )
        actual_record_hash = _sha256_file(record_resolved)
        if actual_record_hash is None:
            raise VisualizationsMaterializationBlocked(
                "missing_referenced_evidence",
                "training_parameter_record could not be read.",
                "training_parameter_record",
            )
        if actual_record_hash != record_expected_hash:
            raise VisualizationsMaterializationBlocked(
                "referenced_evidence_hash_mismatch",
                "training_parameter_record bytes do not match "
                "materialization_result.evidence_hashes.training_parameter_record_sha256.",
                "training_parameter_record",
            )
        try:
            training_record = json.loads(record_resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VisualizationsMaterializationBlocked(
                "invalid_referenced_evidence_json",
                "training_parameter_record is not valid JSON.",
                "training_parameter_record",
            ) from exc
        if not isinstance(training_record, dict):
            raise VisualizationsMaterializationBlocked(
                "invalid_referenced_evidence_json",
                "training_parameter_record must be a JSON object.",
                "training_parameter_record",
            )
        record_model_family = training_record.get("model_family")
        if record_model_family not in _MODEL_FAMILIES:
            raise VisualizationsMaterializationBlocked(
                "invalid_model_family",
                f"training_parameter_record.model_family must be one of {list(_MODEL_FAMILIES)!r}.",
                "training_parameter_record.model_family",
            )

        external_visual_evidence = _require_mapping(external_visual_evidence, "external_visual_evidence")
        evidence_dataset_slug = external_visual_evidence.get("dataset_slug")
        if evidence_dataset_slug is not None and evidence_dataset_slug != dataset_slug:
            raise VisualizationsMaterializationBlocked(
                "dataset_identity_mismatch",
                "external_visual_evidence.dataset_slug does not match dataset_slug.",
                "external_visual_evidence.dataset_slug",
            )
        evidence_model_family = external_visual_evidence.get("model_family")
        if evidence_model_family is not None and evidence_model_family != record_model_family:
            raise VisualizationsMaterializationBlocked(
                "model_identity_mismatch",
                "external_visual_evidence.model_family does not match the governed "
                "training_parameter_record.model_family.",
                "external_visual_evidence.model_family",
            )

        external_evidence_reference = _safe_external_evidence_reference(
            external_evidence_reference, "external_evidence_reference"
        )
        external_evidence_sha256 = _lowercase_sha256(external_evidence_sha256, "external_evidence_sha256")

        target_distribution = _require_mapping(
            external_visual_evidence.get("target_distribution"),
            "external_visual_evidence.target_distribution",
        )
        target_column = _require_nonempty_string(
            target_distribution.get("target_column"),
            "external_visual_evidence.target_distribution.target_column",
        )
        target_distribution_source = _require_nonempty_string(
            target_distribution.get("source"), "external_visual_evidence.target_distribution.source"
        )
        target_distribution_points = _chart_data_points(
            target_distribution.get("counts"), "external_visual_evidence.target_distribution.counts"
        )

        feature_importance = _require_mapping(
            external_visual_evidence.get("feature_importance"),
            "external_visual_evidence.feature_importance",
        )
        feature_importance_source = _require_nonempty_string(
            feature_importance.get("source"), "external_visual_evidence.feature_importance.source"
        )
        feature_importance_method = _require_nonempty_string(
            external_visual_evidence.get("feature_importance_method"),
            "external_visual_evidence.feature_importance_method",
        )
        total_source_feature_count = _require_positive_int(
            feature_importance.get("total_source_feature_count"),
            "external_visual_evidence.feature_importance.total_source_feature_count",
        )
        omitted_source_feature_count = _require_non_negative_int(
            feature_importance.get("omitted_source_feature_count"),
            "external_visual_evidence.feature_importance.omitted_source_feature_count",
        )
        feature_importance_points = _chart_data_points(
            feature_importance.get("rows"),
            "external_visual_evidence.feature_importance.rows",
            max_items=_PUBLIC_ROW_LIMIT,
        )

        output_resolved = _safe_repo_relative_path(
            output_visualizations_path, "output_visualizations_path", resolved_repo_root
        )

        now = _utc_now_iso()
        artifact: dict[str, Any] = {
            "schema_version": VISUALIZATIONS_SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "model_source_mode": MODEL_SOURCE_MODE,
            "created_at": now,
            "dataset_identity": {"dataset_slug": dataset_slug},
            "external_materialization_provenance": {
                "model_family": record_model_family,
                "external_evidence_reference": external_evidence_reference,
                "external_evidence_sha256": external_evidence_sha256,
            },
            "charts": [
                {
                    "id": "target_distribution",
                    "title": "Target Distribution",
                    "type": "bar",
                    "x_label": target_column,
                    "y_label": "Count",
                    "data": target_distribution_points,
                },
                {
                    "id": "feature_importance",
                    "title": "Feature Importance",
                    "type": "bar",
                    "x_label": "Feature",
                    "y_label": "Importance",
                    "data": feature_importance_points,
                },
            ],
            "target_distribution_method": {
                "population_kind": "external_prepared_dataset",
                "source": target_distribution_source,
                "target_column": target_column,
            },
            "feature_importance_method": {
                "model_family": record_model_family,
                "source": feature_importance_source,
                "method": feature_importance_method,
                "total_source_feature_count": total_source_feature_count,
                "omitted_source_feature_count": omitted_source_feature_count,
                "public_row_limit": _PUBLIC_ROW_LIMIT,
            },
            "evidence_policy": {
                "raw_logs_prohibited": True,
                "raw_runtime_prohibited": True,
                "raw_api_payloads_prohibited": True,
                "secrets_prohibited": True,
                "raw_dataset_embedded": False,
                "model_bytes_embedded": False,
                "serialized_estimator_state_embedded": False,
                "raw_transformed_matrices_embedded": False,
                "notebook_state_embedded": False,
                "reduced_and_sanitized": True,
            },
        }

        output_resolved.parent.mkdir(parents=True, exist_ok=True)
        output_resolved.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        visualizations_sha256 = _sha256_file(output_resolved)

        return {
            "status": "materialized",
            "created_at": now,
            "dataset_slug": dataset_slug,
            "visualizations_path": output_visualizations_path,
            "visualizations_sha256": visualizations_sha256,
            "boundary_confirmations": _boundary_confirmations(),
        }

    except VisualizationsMaterializationBlocked as exc:
        return _blocked_result(exc.code, exc.message, exc.field)
