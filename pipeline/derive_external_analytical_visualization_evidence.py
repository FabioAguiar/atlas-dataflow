"""
Atlas-owned authoring-time analytical-visualization derivation for
atlas-dataflow (Project Spec S0194).

Completes the fallback boundary S0193 never installed a producer for: when
the external producer's own ``analytical_visualizations`` evidence role is
absent (but every governed derivation prerequisite is present and valid),
this module performs the one explicitly authorized post-fit authoring
calculation -- permutation importance on the governed validation partition,
using the already Atlas-owned, byte-identical copy of the external fitted
model produced by ``pipeline.materialize_external_fitted_model`` -- and
returns a reduced, S0193-compatible payload plus a durable, hash-bound Atlas
evidence artifact.

This module is generic Atlas core: it contains no dataset-slug conditional
beyond validating a caller-supplied slug. It never discovers the external
project by hardcoded host path, environment-specific absolute path, glob, or
sibling-directory inference -- every governed input is caller-supplied and
explicit. It never opens the test partition. It never calls
fit/fit_transform/partial_fit, never mutates estimator parameters, never
performs model selection or threshold optimization, and never persists the
absolute external root, raw dataset rows, a raw transformed matrix,
serialized estimator state, or model bytes. Any precondition or integrity
failure returns a ``status: "blocked"`` result with concrete, stable-coded
blocking reasons and writes no partial durable evidence, instead of raising
to the caller.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "atlas-derived-analytical-visualization-evidence.v1"
ARTIFACT_TYPE = "atlas_derived_analytical_visualization_evidence"
DERIVATION_ORIGIN = "external_reference_authoring"
MODEL_SOURCE_MODE = "validated_external_fitted_model"
FEATURE_IMPORTANCE_METHOD = "permutation_importance"
# Project Spec S0215: the multiclass (v2) external fitted-model
# materialization profile. This module's permutation-importance fallback
# uses binary Average Precision scoring, which has no valid multiclass
# meaning -- a v2 materialization result must block before any further
# processing, never silently substitute a different scorer.
_MATERIALIZATION_SCHEMA_VERSION_V2 = "external-fitted-model-materialization.v2"

_MODEL_FAMILIES = ("hist_gradient_boosting", "gradient_boosting", "random_forest", "logistic_regression")
_PUBLIC_ROW_LIMIT = 10
_PERMUTATION_SCORING = "average_precision"
_PERMUTATION_N_REPEATS = 30
_PERMUTATION_RANDOM_STATE = 42
_PERMUTATION_N_JOBS = 1
_RUNTIME_KEYS = ("python", "pandas", "scikit_learn", "joblib")

DATASET_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class DerivationBlocked(Exception):
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
        "raw_validation_rows_persisted": False,
        "raw_transformed_matrix_persisted": False,
        "serialized_estimator_state_persisted": False,
        "model_bytes_persisted": False,
        "absolute_external_root_persisted": False,
        "test_partition_accessed": False,
        "model_fit_or_refit_performed": False,
        "model_selection_performed": False,
        "threshold_recalculated": False,
        "final_test_metric_recalculated": False,
        "historical_visualization_reused": False,
    }


def _blocked_result(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    return {
        "status": "blocked",
        "created_at": _utc_now_iso(),
        "blocking_reasons": [
            {"code": code, "message": message, **({"field": field} if field is not None else {})}
        ],
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


def _require_mapping(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DerivationBlocked("missing_required_field", f"{field} must be present as an object.", field)
    return data


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DerivationBlocked("missing_required_field", f"{field} must be a non-empty string.", field)
    return value


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise DerivationBlocked("invalid_hash", f"{field} must be a lowercase SHA-256 hex digest.", field)
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise DerivationBlocked(
            "missing_required_field", f"{field} must be a non-empty array of non-empty strings.", field
        )
    return value


def _safe_relative_reference(value: Any, field: str) -> str:
    """Structurally validate a caller-supplied relative reference string
    (either an external-project-relative provenance reference this module
    never resolves itself, or a governed relative filesystem path this
    module does resolve beneath an explicit root). Rejects absolute paths,
    parent traversal, and backslashes before ever touching the filesystem."""
    if not isinstance(value, str) or not value:
        raise DerivationBlocked("missing_required_field", f"{field} must be a non-empty string.", field)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or value.startswith(("/", "file://", "//")):
        raise DerivationBlocked(
            "unsafe_path",
            f"{field} must be a safe relative reference (no absolute path, parent traversal, or backslashes).",
            field,
        )
    return value


def _resolve_confined_path(root: Path, relative: str, field: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise DerivationBlocked("unsafe_path", f"{field} resolves outside its governed root.", field)
    return candidate


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DerivationBlocked("non_finite_value", f"{field} must be a finite number.", field)
    return float(value)


def _load_and_verify_json(path: Path, expected_sha256: str, field: str) -> dict[str, Any]:
    actual_hash = _sha256_file(path)
    if actual_hash is None:
        raise DerivationBlocked("missing_referenced_evidence", f"{field} could not be read.", field)
    if actual_hash != expected_sha256:
        raise DerivationBlocked(
            "referenced_evidence_hash_mismatch", f"{field} bytes do not match the governed SHA-256.", field
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DerivationBlocked("invalid_referenced_evidence_json", f"{field} is not valid JSON.", field) from exc
    if not isinstance(data, dict):
        raise DerivationBlocked("invalid_referenced_evidence_json", f"{field} must be a JSON object.", field)
    return data


def derive_external_analytical_visualization_evidence(
    *,
    dataset_slug: str,
    external_root: str | Path,
    split_manifest: dict[str, Any],
    split_manifest_reference: str,
    split_manifest_sha256: str,
    final_model_manifest: dict[str, Any],
    final_model_manifest_reference: str,
    final_model_manifest_sha256: str,
    materialization_result: dict[str, Any],
    output_derivation_evidence_path: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Derive a reduced, S0193-compatible analytical-visualization payload
    from governed, already hash-verified external evidence, using only the
    Atlas-owned byte-identical model copy from a successful
    ``external_fitted_model_materialization_result``.

    ``external_root`` is a session-only ``Path`` used only to resolve and
    hash-verify the governed validation partition beneath it; it is never
    written into the returned payload or the durable evidence artifact.
    ``split_manifest``/``final_model_manifest`` are already parsed,
    already hash-verified external evidence payloads (the caller's
    external-evidence-index verification boundary already ran); their
    ``*_reference``/``*_sha256`` pairs are the same relative-path/hash pairs
    from that verification, embedded into the durable evidence artifact's
    provenance -- never the absolute external project root.

    Returns ``{"status": "derived", "target_distribution": ...,
    "feature_importance": ..., "feature_importance_method": ...,
    "derivation_evidence_path": ..., "derivation_evidence_sha256": ...,
    ...}`` or ``{"status": "blocked", "blocking_reasons": [...]}``. Never
    raises to the caller. Writes exactly one durable artifact
    (``output_derivation_evidence_path``, repository-relative, resolved
    beneath ``repo_root``), only on success.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _repo_root()
    resolved_external_root = Path(external_root).expanduser().resolve()

    try:
        if not isinstance(dataset_slug, str) or not DATASET_SLUG_RE.fullmatch(dataset_slug):
            raise DerivationBlocked("invalid_dataset_identity", "dataset_slug is not a valid dataset slug.", "dataset_slug")

        # -- Materialization result: the sole authorized model source. --
        materialization_result = _require_mapping(materialization_result, "materialization_result")
        if materialization_result.get("status") != "materialized":
            raise DerivationBlocked(
                "materialization_not_materialized",
                "materialization_result.status must be 'materialized'.",
                "materialization_result.status",
            )
        if materialization_result.get("model_source_mode") != MODEL_SOURCE_MODE:
            raise DerivationBlocked(
                "invalid_model_source_mode",
                f"materialization_result.model_source_mode must be {MODEL_SOURCE_MODE!r}.",
                "materialization_result.model_source_mode",
            )
        if materialization_result.get("schema_version") == _MATERIALIZATION_SCHEMA_VERSION_V2:
            raise DerivationBlocked(
                "multiclass_fallback_derivation_not_supported",
                "Atlas's authoring-time permutation-importance fallback derivation is not "
                "supported for a multiclass (v2) external fitted-model materialization -- "
                "binary Average Precision scoring has no valid multiclass meaning. Supply the "
                "external producer's own analytical-visualizations evidence instead.",
                "materialization_result.schema_version",
            )
        materialization_dataset_slug = _require_mapping(
            materialization_result.get("dataset_identity"), "materialization_result.dataset_identity"
        ).get("dataset_slug")
        if materialization_dataset_slug != dataset_slug:
            raise DerivationBlocked(
                "dataset_identity_mismatch",
                "materialization_result.dataset_identity.dataset_slug does not match dataset_slug.",
                "materialization_result.dataset_identity.dataset_slug",
            )

        evidence_references = _require_mapping(
            materialization_result.get("evidence_references"), "materialization_result.evidence_references"
        )
        evidence_hashes = _require_mapping(
            materialization_result.get("evidence_hashes"), "materialization_result.evidence_hashes"
        )
        record_relative = _safe_relative_reference(
            evidence_references.get("training_parameter_record_path"),
            "evidence_references.training_parameter_record_path",
        )
        record_expected_hash = _require_sha256(
            evidence_hashes.get("training_parameter_record_sha256"),
            "evidence_hashes.training_parameter_record_sha256",
        )
        record_full_path = _resolve_confined_path(
            resolved_repo_root, record_relative, "evidence_references.training_parameter_record_path"
        )
        training_record = _load_and_verify_json(record_full_path, record_expected_hash, "training_parameter_record")
        governed_model_family = training_record.get("model_family")
        if governed_model_family not in _MODEL_FAMILIES:
            raise DerivationBlocked(
                "invalid_model_family",
                f"training_parameter_record.model_family must be one of {list(_MODEL_FAMILIES)!r}.",
                "training_parameter_record.model_family",
            )

        model_relative = _safe_relative_reference(
            materialization_result.get("model_artifact_path"), "materialization_result.model_artifact_path"
        )
        model_expected_hash = _require_sha256(
            materialization_result.get("model_artifact_sha256"), "materialization_result.model_artifact_sha256"
        )
        model_full_path = _resolve_confined_path(
            resolved_repo_root, model_relative, "materialization_result.model_artifact_path"
        )
        actual_model_hash = _sha256_file(model_full_path)
        if actual_model_hash is None:
            raise DerivationBlocked(
                "missing_referenced_evidence", "The materialized model artifact could not be read.", "model_artifact_path"
            )
        if actual_model_hash != model_expected_hash:
            raise DerivationBlocked(
                "referenced_evidence_hash_mismatch",
                "The materialized model artifact bytes do not match materialization_result.model_artifact_sha256.",
                "model_artifact_path",
            )

        # -- Final-model manifest: governed feature order, target encoding,
        # runtime expectation, and expected estimator family. --
        final_model_manifest = _require_mapping(final_model_manifest, "final_model_manifest")
        final_model_manifest_reference = _safe_relative_reference(
            final_model_manifest_reference, "final_model_manifest_reference"
        )
        final_model_manifest_sha256 = _require_sha256(final_model_manifest_sha256, "final_model_manifest_sha256")
        if final_model_manifest.get("dataset_slug") != dataset_slug:
            raise DerivationBlocked(
                "dataset_identity_mismatch",
                "final_model_manifest.dataset_slug does not match dataset_slug.",
                "final_model_manifest.dataset_slug",
            )
        selected_model_id = final_model_manifest.get("selected_model_id")
        if selected_model_id not in _MODEL_FAMILIES:
            raise DerivationBlocked(
                "invalid_model_family",
                f"final_model_manifest.selected_model_id must be one of {list(_MODEL_FAMILIES)!r}.",
                "final_model_manifest.selected_model_id",
            )
        if selected_model_id != governed_model_family:
            raise DerivationBlocked(
                "model_identity_mismatch",
                "final_model_manifest.selected_model_id does not match the governed "
                "training_parameter_record.model_family.",
                "final_model_manifest.selected_model_id",
            )
        expected_estimator_class_name = _require_nonempty_string(
            final_model_manifest.get("selected_model_family"), "final_model_manifest.selected_model_family"
        )
        source_feature_order = _require_string_list(
            final_model_manifest.get("feature_columns"), "final_model_manifest.feature_columns"
        )
        target_column = _require_nonempty_string(
            final_model_manifest.get("target_column"), "final_model_manifest.target_column"
        )
        target_encoding = _require_mapping(final_model_manifest.get("target_encoding"), "final_model_manifest.target_encoding")
        if len(target_encoding) < 2 or not all(
            isinstance(label, str) and label and isinstance(code, int) and not isinstance(code, bool)
            for label, code in target_encoding.items()
        ):
            raise DerivationBlocked(
                "invalid_target_encoding",
                "final_model_manifest.target_encoding must map at least two non-empty labels to integer codes.",
                "final_model_manifest.target_encoding",
            )
        expected_runtime = _require_mapping(final_model_manifest.get("runtime_versions"), "final_model_manifest.runtime_versions")
        for key in _RUNTIME_KEYS:
            _require_nonempty_string(expected_runtime.get(key), f"final_model_manifest.runtime_versions.{key}")

        # -- Split manifest: governed target-distribution and validation-partition identity. --
        split_manifest = _require_mapping(split_manifest, "split_manifest")
        split_manifest_reference = _safe_relative_reference(split_manifest_reference, "split_manifest_reference")
        split_manifest_sha256 = _require_sha256(split_manifest_sha256, "split_manifest_sha256")
        if split_manifest.get("dataset_slug") != dataset_slug:
            raise DerivationBlocked(
                "dataset_identity_mismatch",
                "split_manifest.dataset_slug does not match dataset_slug.",
                "split_manifest.dataset_slug",
            )
        stratify_by = _require_nonempty_string(split_manifest.get("stratify_by"), "split_manifest.stratify_by")
        if stratify_by != target_column:
            raise DerivationBlocked(
                "target_column_mismatch",
                "split_manifest.stratify_by does not match final_model_manifest.target_column.",
                "split_manifest.stratify_by",
            )

        class_counts = _require_mapping(split_manifest.get("class_counts"), "split_manifest.class_counts")
        row_counts = _require_mapping(split_manifest.get("row_counts"), "split_manifest.row_counts")
        aggregated_counts: dict[str, int] = {}
        for partition_name, partition_row_count in row_counts.items():
            partition_class_counts = _require_mapping(
                class_counts.get(partition_name), f"split_manifest.class_counts.{partition_name}"
            )
            if not isinstance(partition_row_count, int) or isinstance(partition_row_count, bool) or partition_row_count < 0:
                raise DerivationBlocked(
                    "invalid_row_count", f"split_manifest.row_counts.{partition_name} must be a non-negative integer.",
                    f"split_manifest.row_counts.{partition_name}",
                )
            partition_total = 0
            for label, count in partition_class_counts.items():
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise DerivationBlocked(
                        "invalid_class_count",
                        f"split_manifest.class_counts.{partition_name}.{label} must be a non-negative integer.",
                        f"split_manifest.class_counts.{partition_name}.{label}",
                    )
                partition_total += count
                aggregated_counts[label] = aggregated_counts.get(label, 0) + count
            if partition_total != partition_row_count:
                raise DerivationBlocked(
                    "row_count_inconsistent",
                    f"split_manifest.class_counts.{partition_name} does not sum to "
                    f"split_manifest.row_counts.{partition_name}.",
                    f"split_manifest.class_counts.{partition_name}",
                )
        if not aggregated_counts:
            raise DerivationBlocked(
                "missing_required_field", "split_manifest.class_counts produced no target distribution.", "split_manifest.class_counts"
            )

        partition_paths = _require_mapping(split_manifest.get("partition_paths"), "split_manifest.partition_paths")
        partition_sha256 = _require_mapping(split_manifest.get("partition_sha256"), "split_manifest.partition_sha256")
        validation_relative = _safe_relative_reference(
            partition_paths.get("validation"), "split_manifest.partition_paths.validation"
        )
        validation_expected_sha256 = _require_sha256(
            partition_sha256.get("validation"), "split_manifest.partition_sha256.validation"
        )
        validation_full_path = _resolve_confined_path(
            resolved_external_root, validation_relative, "split_manifest.partition_paths.validation"
        )
        if not validation_full_path.is_file():
            raise DerivationBlocked(
                "missing_validation_partition", "The governed validation partition file does not exist.", "validation_partition"
            )
        actual_validation_sha256 = _sha256_file(validation_full_path)
        if actual_validation_sha256 != validation_expected_sha256:
            raise DerivationBlocked(
                "validation_hash_mismatch",
                "The validation partition bytes do not match split_manifest.partition_sha256.validation.",
                "validation_partition",
            )

        # -- Runtime compatibility gate: before any deserialization. --
        import pandas

        observed_pandas = pandas.__version__
        try:
            import sklearn
        except ImportError as exc:
            raise DerivationBlocked(
                "runtime_dependency_unavailable", "scikit-learn is not available in the authoring runtime.", "runtime.scikit_learn"
            ) from exc
        try:
            import joblib
        except ImportError as exc:
            raise DerivationBlocked(
                "runtime_dependency_unavailable", "joblib is not available in the authoring runtime.", "runtime.joblib"
            ) from exc

        observed_runtime = {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "pandas": observed_pandas,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        }
        for key in ("pandas", "scikit_learn", "joblib"):
            if observed_runtime[key] != expected_runtime[key]:
                raise DerivationBlocked(
                    "runtime_incompatible",
                    f"Authoring runtime {key} {observed_runtime[key]!r} does not match the governed expected "
                    f"runtime {expected_runtime[key]!r}.",
                    f"runtime.{key}",
                )
        expected_python_major_minor = ".".join(expected_runtime["python"].split(".")[:2])
        observed_python_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        if expected_python_major_minor != observed_python_major_minor:
            raise DerivationBlocked(
                "runtime_incompatible",
                f"Authoring runtime python {observed_python_major_minor!r} does not match the governed expected "
                f"runtime major.minor {expected_python_major_minor!r}.",
                "runtime.python",
            )

        # -- Load the governed validation partition and prepare source features/target. --
        validation_frame = pandas.read_csv(validation_full_path)
        missing_columns = [column for column in (*source_feature_order, target_column) if column not in validation_frame.columns]
        if missing_columns:
            raise DerivationBlocked(
                "validation_columns_missing",
                f"The validation partition is missing governed columns: {missing_columns}.",
                "validation_partition",
            )
        x_validation = validation_frame[list(source_feature_order)]
        y_validation_raw = validation_frame[target_column]
        y_validation_encoded = y_validation_raw.map(target_encoding)
        if y_validation_encoded.isna().any():
            raise DerivationBlocked(
                "target_encoding_incomplete",
                "The validation partition target column contains a label not covered by the governed "
                "target_encoding.",
                "final_model_manifest.target_encoding",
            )
        y_validation_encoded = y_validation_encoded.astype(int)

        # -- Trusted, frozen Pipeline load: authorized only here, only after
        # every prior gate has passed. --
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            try:
                model = joblib.load(model_full_path)
            except Exception as exc:
                raise DerivationBlocked(
                    "model_deserialization_failed", "The governed model artifact could not be deserialized.", "model_artifact_path"
                ) from exc
            try:
                from sklearn.exceptions import InconsistentVersionWarning
            except ImportError as exc:
                raise DerivationBlocked(
                    "runtime_dependency_unavailable", "scikit-learn is not available in the authoring runtime.", "runtime.scikit_learn"
                ) from exc
            for warning in caught_warnings:
                if issubclass(warning.category, InconsistentVersionWarning):
                    raise DerivationBlocked(
                        "inconsistent_version_warning_emitted",
                        "Model deserialization emitted sklearn.exceptions.InconsistentVersionWarning; the "
                        "authoring runtime is not trusted to be compatible.",
                        "model_artifact_path",
                    )

        from sklearn.pipeline import Pipeline

        if not isinstance(model, Pipeline) or not getattr(model, "steps", None):
            raise DerivationBlocked(
                "untrusted_model_object", "The deserialized model artifact is not a fitted sklearn Pipeline.", "model_artifact_path"
            )
        final_estimator = model.steps[-1][1]
        if type(final_estimator).__name__ != expected_estimator_class_name:
            raise DerivationBlocked(
                "model_family_mismatch_after_load",
                "The deserialized Pipeline's final estimator does not match "
                "final_model_manifest.selected_model_family.",
                "model_artifact_path",
            )

        # -- Permutation importance over the complete pipeline and original
        # source features, governed parameters, never fit/refit. --
        from sklearn.inspection import permutation_importance

        permutation_result = permutation_importance(
            model,
            x_validation,
            y_validation_encoded,
            scoring=_PERMUTATION_SCORING,
            n_repeats=_PERMUTATION_N_REPEATS,
            random_state=_PERMUTATION_RANDOM_STATE,
            n_jobs=_PERMUTATION_N_JOBS,
        )

        feature_importance_evidence: list[dict[str, Any]] = []
        for index, feature_name in enumerate(source_feature_order):
            mean_value = _finite_float(permutation_result.importances_mean[index], f"feature_importance.{feature_name}.mean")
            std_value = _finite_float(permutation_result.importances_std[index], f"feature_importance.{feature_name}.std")
            feature_importance_evidence.append({"name": feature_name, "mean": mean_value, "std": std_value})

        positive_rows = sorted(
            (
                {"name": entry["name"], "value": entry["mean"]}
                for entry in feature_importance_evidence
                if entry["mean"] > 0
            ),
            key=lambda row: row["value"],
            reverse=True,
        )[:_PUBLIC_ROW_LIMIT]
        if not positive_rows:
            raise DerivationBlocked(
                "zero_positive_importance_rows",
                "No source feature had a strictly positive permutation-importance mean.",
                "feature_importance",
            )

        total_source_feature_count = len(source_feature_order)
        omitted_source_feature_count = total_source_feature_count - len(positive_rows)

        target_distribution = {
            "target_column": target_column,
            "source": split_manifest_reference,
            "counts": [{"name": label, "value": value} for label, value in aggregated_counts.items()],
        }
        feature_importance = {
            "source": final_model_manifest_reference,
            "total_source_feature_count": total_source_feature_count,
            "omitted_source_feature_count": omitted_source_feature_count,
            "rows": positive_rows,
        }

        output_relative = _safe_relative_reference(output_derivation_evidence_path, "output_derivation_evidence_path")
        output_full_path = _resolve_confined_path(resolved_repo_root, output_relative, "output_derivation_evidence_path")

        now = _utc_now_iso()
        evidence_artifact: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": ARTIFACT_TYPE,
            "dataset_slug": dataset_slug,
            "model_family": selected_model_id,
            "derivation_origin": DERIVATION_ORIGIN,
            "created_at": now,
            "target_distribution": target_distribution,
            "feature_importance": feature_importance,
            "feature_importance_method": FEATURE_IMPORTANCE_METHOD,
            "feature_importance_evidence": feature_importance_evidence,
            "source_references": {
                "split_manifest_reference": split_manifest_reference,
                "split_manifest_sha256": split_manifest_sha256,
                "final_model_manifest_reference": final_model_manifest_reference,
                "final_model_manifest_sha256": final_model_manifest_sha256,
                "model_artifact_path": model_relative,
                "model_artifact_sha256": model_expected_hash,
                "training_parameter_record_path": record_relative,
                "training_parameter_record_sha256": record_expected_hash,
            },
            "method_details": {
                "method": FEATURE_IMPORTANCE_METHOD,
                "scoring": _PERMUTATION_SCORING,
                "n_repeats": _PERMUTATION_N_REPEATS,
                "random_state": _PERMUTATION_RANDOM_STATE,
                "n_jobs": _PERMUTATION_N_JOBS,
                "source_feature_order": list(source_feature_order),
                "target_encoding": dict(target_encoding),
                "expected_runtime": dict(expected_runtime),
                "observed_runtime": observed_runtime,
            },
            "boundary_confirmations": _boundary_confirmations(),
        }

        output_full_path.parent.mkdir(parents=True, exist_ok=True)
        output_full_path.write_text(json.dumps(evidence_artifact, indent=2, sort_keys=True), encoding="utf-8")
        derivation_evidence_sha256 = _sha256_file(output_full_path)

        return {
            "status": "derived",
            "created_at": now,
            "dataset_slug": dataset_slug,
            "model_family": selected_model_id,
            "derivation_evidence_path": output_relative,
            "derivation_evidence_sha256": derivation_evidence_sha256,
            "target_distribution": target_distribution,
            "feature_importance": feature_importance,
            "feature_importance_method": FEATURE_IMPORTANCE_METHOD,
            "boundary_confirmations": _boundary_confirmations(),
        }

    except DerivationBlocked as exc:
        return _blocked_result(exc.code, exc.message, exc.field)
