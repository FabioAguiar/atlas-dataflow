"""
Public metrics loader for M7-02, realigned by Project Spec S0127.

Loads model performance metrics from the active release package and returns
a stable, bounded public evaluation projection: internal field names,
artifact paths, training-run identity, and model internals are never
exposed, and every recognized source shape (the current training-metrics.v1
artifact and older evaluation-wrapped/flat release fixtures) is normalized
into the exact same public shape:

    {
        "evaluation": {
            "split_name": str | None,
            "sample_size": int | None,
            "primary_metric_id": str | None,
            "metrics": {<public_metric_id>: float, ...},
            "metric_order": [<public_metric_id>, ...],
        }
    }
"""

import json
import math
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_METRICS_ROLE = "metrics"

# Bounded, explicit alias table (S0127): unknown metric identifiers are
# never silently renamed into a supported metric and are simply omitted
# from the public projection.
_METRIC_ALIASES: dict[str, str] = {
    "roc_auc": "roc_auc",
    "auc_roc": "roc_auc",
    "auc": "roc_auc",
    "f1": "f1_score",
    "f1_score": "f1_score",
    "pr_auc": "pr_auc",
    "average_precision": "pr_auc",
    "precision": "precision",
    "recall": "recall",
    "accuracy": "accuracy",
    "log_loss": "log_loss",
    # Project Spec S0215: explicit multiclass aggregate metric ids, each
    # projected 1:1 -- never aliased into the ambiguous binary-era
    # f1_score/precision/recall ids, since those erase averaging semantics.
    "balanced_accuracy": "balanced_accuracy",
    "f1_macro": "f1_macro",
    "f1_weighted": "f1_weighted",
    "precision_macro": "precision_macro",
    "recall_macro": "recall_macro",
    # Project Spec S0227: bounded explicit continuous-regression metric ids,
    # each projected 1:1 -- never aliased into a classification metric id.
    "r2": "r2",
    "mae": "mae",
    "rmse": "rmse",
    # Project Spec S0247: bounded explicit univariate-forecasting metric id,
    # projected 1:1 -- shares the mae/rmse identity above (never a duplicate
    # alias with different semantics).
    "seasonal_mase": "seasonal_mase",
}

# Project Spec S0191: schema_version discriminator for the external
# fitted-model training-metrics profile, dispatched on explicitly (never by
# loose shape matching).
_EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION = "training-metrics.external-fitted-model.v1"
# Project Spec S0215: the multiclass (v2) external fitted-model
# training-metrics profile, dispatched on explicitly alongside v1.
_EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION_V2 = "training-metrics.external-fitted-model.v2"
# Project Spec S0216: the internal (Atlas-native) multiclass fixed-
# configuration training-metrics profile, dispatched on explicitly.
_INTERNAL_MULTICLASS_METRICS_SCHEMA_VERSION_V2 = "training-metrics.v2"
# Project Spec S0227: the internal (Atlas-native) continuous-regression
# fixed-configuration training-metrics profile, dispatched on explicitly.
_INTERNAL_CONTINUOUS_REGRESSION_METRICS_SCHEMA_VERSION_V3 = "training-metrics.v3"
# Project Spec S0247: the internal (Atlas-native) univariate-forecasting
# fixed-configuration training-metrics profile, dispatched on explicitly.
_INTERNAL_FORECASTING_METRICS_SCHEMA_VERSION_V4 = "training-metrics.v4"
# Project Spec S0279: the internal (Atlas-native) binary fixed-configuration
# training-metrics profile (Project Specs S0258/S0259), dispatched on
# explicitly -- never inferred from loose field detection.
_INTERNAL_NATIVE_BINARY_METRICS_SCHEMA_VERSION_V5 = "training-metrics.v5"

# Top-level keys that are never themselves metric declarations, used only
# by the bounded flat top-level fallback (case 3 below) to avoid mistaking
# a structural field for a stray metric.
_STRUCTURAL_KEYS = {
    "schema_version",
    "dataset_slug",
    "release_id",
    "notes",
    "evaluation",
    "metric_source",
    "metrics",
    "artifact_kind",
    "created_at",
    "hashes",
    "path_references",
    "training_run_identity",
    "evidence_policy",
}


class PublicMetricsUnavailableError(Exception):
    """The public metrics projection is absent from or unreadable in the active release package."""

    code = "PUBLIC_METRICS_UNAVAILABLE"


def _releases_root() -> Path:
    env_root = os.environ.get("RELEASES_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT / "releases"


def _artifact_reference(manifest: dict, role: str) -> str | None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("role") != role:
            continue
        reference = artifact.get("reference")
        if isinstance(reference, str) and reference:
            return reference
    return None


def _is_valid_numeric(value: Any) -> bool:
    """A metric score is valid only when it is a finite, non-boolean number. 0/0.0 are valid."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def _normalize_public_metric_id(raw_name: Any) -> str | None:
    if not isinstance(raw_name, str):
        return None
    return _METRIC_ALIASES.get(raw_name.strip().lower())


def _project_metric_entries(
    entries: list[tuple[Any, Any, bool]],
) -> tuple[dict[str, float], list[str]]:
    """
    entries: ordered (raw_name, raw_value, is_primary) declarations.

    Builds the alias-normalized {public_id: value} map and its first-seen
    display order. Duplicate aliases resolve deterministically: the primary
    metric's value wins over a secondary duplicate; otherwise the first
    valid declared value wins. A metric id whose only occurrence(s) are
    invalid/non-finite is omitted entirely -- never coerced to a fallback
    value, and never silently reported as missing-but-zero.
    """
    candidates: dict[str, list[tuple[bool, Any]]] = {}
    order: list[str] = []
    for raw_name, raw_value, is_primary in entries:
        public_id = _normalize_public_metric_id(raw_name)
        if public_id is None:
            continue
        if public_id not in candidates:
            candidates[public_id] = []
            order.append(public_id)
        candidates[public_id].append((is_primary, raw_value))

    metrics: dict[str, float] = {}
    for public_id in order:
        declared = candidates[public_id]
        primary_valid = next(
            (value for is_primary, value in declared if is_primary and _is_valid_numeric(value)),
            None,
        )
        if primary_valid is not None:
            metrics[public_id] = float(primary_valid)
            continue
        first_valid = next(
            (value for _is_primary, value in declared if _is_valid_numeric(value)),
            None,
        )
        if first_valid is not None:
            metrics[public_id] = float(first_valid)

    metric_order = [public_id for public_id in order if public_id in metrics]
    return metrics, metric_order


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _project_training_metrics_v1(payload: dict) -> dict:
    metric_source = payload.get("metric_source")
    split_name = None
    sample_size = None
    if isinstance(metric_source, dict):
        split_name = _optional_str(metric_source.get("split_name"))
        sample_size = _optional_int(metric_source.get("split_size"))

    metrics_block = payload.get("metrics")
    entries: list[tuple[Any, Any, bool]] = []
    primary = metrics_block.get("primary_metric") if isinstance(metrics_block, dict) else None
    if isinstance(primary, dict):
        entries.append((primary.get("name"), primary.get("value"), True))
    secondary = metrics_block.get("secondary_metrics") if isinstance(metrics_block, dict) else None
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, dict):
                entries.append((item.get("name"), item.get("value"), False))

    metrics, metric_order = _project_metric_entries(entries)

    primary_metric_id = None
    if isinstance(primary, dict):
        candidate_id = _normalize_public_metric_id(primary.get("name"))
        if candidate_id is not None and candidate_id in metrics:
            primary_metric_id = candidate_id

    return {
        "evaluation": {
            "split_name": split_name,
            "sample_size": sample_size,
            "primary_metric_id": primary_metric_id,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_legacy_evaluation_shape(payload: dict) -> dict:
    evaluation = payload.get("evaluation")
    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    if isinstance(evaluation, dict):
        split_name = _optional_str(evaluation.get("split_name"))
        if split_name is None:
            split_name = _optional_str(evaluation.get("split"))
        sample_size = _optional_int(evaluation.get("sample_size"))
        raw_metrics = evaluation.get("metrics")
        if isinstance(raw_metrics, dict):
            entries = [(name, value, False) for name, value in raw_metrics.items()]

    metrics, metric_order = _project_metric_entries(entries)

    return {
        "evaluation": {
            "split_name": split_name,
            "sample_size": sample_size,
            "primary_metric_id": None,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_flat_top_level_shape(payload: dict) -> dict:
    """
    Bounded compatibility fallback for a release fixture that declares
    metric scores directly at the artifact's top level, with no
    evaluation/metric_source wrapper at all. Only known structural keys are
    excluded from consideration; unrecognized metric names are still
    dropped by the alias table in _project_metric_entries, so this never
    becomes an unbounded recursive search for numbers anywhere in the
    document.
    """
    entries: list[tuple[Any, Any, bool]] = [
        (name, value, False) for name, value in payload.items() if name not in _STRUCTURAL_KEYS
    ]
    metrics, metric_order = _project_metric_entries(entries)

    return {
        "evaluation": {
            "split_name": None,
            "sample_size": None,
            "primary_metric_id": None,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_external_fitted_model_metrics(payload: dict) -> dict:
    """Project Spec S0191: public projector for
    training-metrics.external-fitted-model.v1.

    Prefers a completed final_test_evaluation when present; otherwise falls
    back to validation_evaluation. cross_validation_summary (the train
    partition) is never selected -- it is not a public holdout evaluation.
    The external schema does not designate a primary metric, so
    primary_metric_id is never fabricated and remains None. Only
    evaluation.split_name (from partition_role), evaluation.sample_size
    (from row_count, when present), and the bounded alias-normalized
    metrics are projected -- no evidence paths, producer ids, raw
    predictions, or partition rows are ever exposed.
    """
    final_test = payload.get("final_test_evaluation")
    validation = payload.get("validation_evaluation")
    selected = (
        final_test
        if isinstance(final_test, dict) and final_test.get("completed") is True
        else validation
    )

    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    if isinstance(selected, dict):
        split_name = _optional_str(selected.get("partition_role"))
        sample_size = _optional_int(selected.get("row_count"))
        raw_metrics = selected.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]

    metrics, metric_order = _project_metric_entries(entries)

    return {
        "evaluation": {
            "split_name": split_name,
            "sample_size": sample_size,
            "primary_metric_id": None,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_bounded_per_class_metrics(per_class_metrics: Any, ordered_class_ids: Any) -> list[dict] | None:
    """Project Spec S0215 Desired Change N: bounded per-class public
    projection for external metrics v2 only. Returns None (omitted from the
    public response entirely) unless every entry is well-typed, every
    numeric bound is satisfied, class ids are unique, and their order/
    coverage agrees exactly with classification_evidence.ordered_class_ids
    -- never evidence paths, producer identity, raw rows, or raw
    probabilities."""
    if not isinstance(per_class_metrics, list) or not isinstance(ordered_class_ids, list):
        return None
    if not ordered_class_ids or len(per_class_metrics) != len(ordered_class_ids):
        return None

    projected: list[dict] = []
    seen_class_ids: set[str] = set()
    for position, entry in enumerate(per_class_metrics):
        if not isinstance(entry, dict):
            return None
        class_id = entry.get("class_id")
        if not isinstance(class_id, str) or not class_id or class_id != ordered_class_ids[position]:
            return None
        if class_id in seen_class_ids:
            return None
        seen_class_ids.add(class_id)

        precision = entry.get("precision")
        recall = entry.get("recall")
        f1 = entry.get("f1")
        support = entry.get("support")
        if not all(_is_valid_numeric(value) and 0.0 <= value <= 1.0 for value in (precision, recall, f1)):
            return None
        if isinstance(support, bool) or not isinstance(support, int) or support < 0:
            return None

        projected.append(
            {
                "class_id": class_id,
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "support": support,
            }
        )
    return projected


def _project_external_fitted_model_metrics_v2(payload: dict) -> dict:
    """Project Spec S0215: public projector for
    training-metrics.external-fitted-model.v2 (multiclass). Mirrors the v1
    partition-selection discipline (completed final_test_evaluation when
    present, otherwise validation_evaluation; cross_validation_summary is
    never selected) and additionally projects a bounded per_class_metrics
    array (Desired Change N) when the selected partition carries one that
    exactly agrees with classification_evidence.ordered_class_ids --
    omitted entirely otherwise, never fabricated. The external schema does
    not designate a primary metric, so primary_metric_id is never
    fabricated and remains None."""
    final_test = payload.get("final_test_evaluation")
    validation = payload.get("validation_evaluation")
    selected = (
        final_test
        if isinstance(final_test, dict) and final_test.get("completed") is True
        else validation
    )

    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    per_class_metrics_source = None
    if isinstance(selected, dict):
        split_name = _optional_str(selected.get("partition_role"))
        sample_size = _optional_int(selected.get("row_count"))
        raw_metrics = selected.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]
        per_class_metrics_source = selected.get("per_class_metrics")

    metrics, metric_order = _project_metric_entries(entries)

    classification_evidence = payload.get("classification_evidence")
    ordered_class_ids = (
        classification_evidence.get("ordered_class_ids") if isinstance(classification_evidence, dict) else None
    )
    projected_per_class_metrics = _project_bounded_per_class_metrics(per_class_metrics_source, ordered_class_ids)

    evaluation: dict[str, Any] = {
        "split_name": split_name,
        "sample_size": sample_size,
        "primary_metric_id": None,
        "metrics": metrics,
        "metric_order": metric_order,
    }
    if projected_per_class_metrics is not None:
        evaluation["per_class_metrics"] = projected_per_class_metrics
    return {"evaluation": evaluation}


def _project_internal_multiclass_metrics_v2(payload: dict) -> dict:
    """Project Spec S0216: public projector for training-metrics.v2
    (internal Atlas-native multiclass fixed-configuration training).
    Mirrors `_project_external_fitted_model_metrics_v2`'s partition-
    selection discipline (completed final_test_evaluation when present,
    otherwise validation_evaluation) and bounded per_class_metrics
    projection -- this internal profile never carries a
    cross_validation_summary at all, so there is no train-partition
    candidate to ever accidentally select. The internal schema does not
    designate a primary metric, so primary_metric_id is never fabricated
    and remains None."""
    final_test = payload.get("final_test_evaluation")
    validation = payload.get("validation_evaluation")
    selected = (
        final_test
        if isinstance(final_test, dict) and final_test.get("completed") is True
        else validation
    )

    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    per_class_metrics_source = None
    if isinstance(selected, dict):
        split_name = _optional_str(selected.get("partition_role"))
        sample_size = _optional_int(selected.get("row_count"))
        raw_metrics = selected.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]
        per_class_metrics_source = selected.get("per_class_metrics")

    metrics, metric_order = _project_metric_entries(entries)

    classification_evidence = payload.get("classification_evidence")
    ordered_class_ids = (
        classification_evidence.get("ordered_class_ids") if isinstance(classification_evidence, dict) else None
    )
    projected_per_class_metrics = _project_bounded_per_class_metrics(per_class_metrics_source, ordered_class_ids)

    evaluation: dict[str, Any] = {
        "split_name": split_name,
        "sample_size": sample_size,
        "primary_metric_id": None,
        "metrics": metrics,
        "metric_order": metric_order,
    }
    if projected_per_class_metrics is not None:
        evaluation["per_class_metrics"] = projected_per_class_metrics
    return {"evaluation": evaluation}


def _project_internal_continuous_regression_metrics_v3(payload: dict) -> dict:
    """Project Spec S0227: public projector for training-metrics.v3
    (internal Atlas-native continuous-regression fixed-configuration
    training). Mirrors `_project_internal_multiclass_metrics_v2`'s
    partition-selection discipline (completed final_test_evaluation when
    present, otherwise validation_evaluation -- this internal profile never
    carries a cross_validation_summary at all, so there is no train-
    partition candidate to ever accidentally select). Only the bounded
    r2/mae/rmse regression metric ids are ever projected -- unknown metric
    names remain omitted, and non-finite/boolean values are never accepted.
    The internal schema does not designate a primary metric, so
    primary_metric_id is never fabricated and remains None. No
    regression_evidence internals, training_run_identity, path/hash
    references, raw predictions, or residual rows are ever projected."""
    final_test = payload.get("final_test_evaluation")
    validation = payload.get("validation_evaluation")
    selected = (
        final_test
        if isinstance(final_test, dict) and final_test.get("completed") is True
        else validation
    )

    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    if isinstance(selected, dict):
        split_name = _optional_str(selected.get("partition_role"))
        sample_size = _optional_int(selected.get("row_count"))
        raw_metrics = selected.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]

    metrics, metric_order = _project_metric_entries(entries)

    return {
        "evaluation": {
            "split_name": split_name,
            "sample_size": sample_size,
            "primary_metric_id": None,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_internal_forecasting_metrics_v4(payload: dict) -> dict:
    """Project Spec S0247: public projector for training-metrics.v4 (internal
    Atlas-native univariate forecasting training). Selects only the sealed
    final_holdout_evaluation -- pooled backtesting metrics are never
    projected. split_name is the deterministic literal "final_holdout";
    sample_size comes from final_holdout_evaluation.observation_count.
    primary_metric_id/metric_order are derived from the governed
    evaluation_policy ordering (primary metric, then declared secondaries in
    order), dropping any metric absent from the projected final-holdout
    metrics -- never derived from dict/declaration order. No
    seasonal_period, backtesting/fold/horizon evidence,
    training_run_identity, path/hash references, or raw arrays are ever
    projected."""
    final_holdout = payload.get("final_holdout_evaluation")
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    if isinstance(final_holdout, dict):
        sample_size = _optional_int(final_holdout.get("observation_count"))
        raw_metrics = final_holdout.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]

    metrics, _first_seen_order = _project_metric_entries(entries)

    evaluation_policy = payload.get("evaluation_policy")
    metric_order: list[str] = []
    primary_metric_id = None
    if isinstance(evaluation_policy, dict):
        primary = evaluation_policy.get("primary_metric")
        if isinstance(primary, dict):
            candidate_id = _normalize_public_metric_id(primary.get("metric_id"))
            if candidate_id is not None and candidate_id in metrics:
                primary_metric_id = candidate_id
                metric_order.append(candidate_id)
        secondaries = evaluation_policy.get("secondary_metrics")
        if isinstance(secondaries, list):
            for item in secondaries:
                if not isinstance(item, dict):
                    continue
                candidate_id = _normalize_public_metric_id(item.get("metric_id"))
                if candidate_id is not None and candidate_id in metrics and candidate_id not in metric_order:
                    metric_order.append(candidate_id)

    return {
        "evaluation": {
            "split_name": "final_holdout",
            "sample_size": sample_size,
            "primary_metric_id": primary_metric_id,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_internal_native_binary_metrics_v5(payload: dict) -> dict:
    """Project Spec S0279: public projector for training-metrics.v5 (internal
    Atlas-native binary fixed-configuration training, Project Specs
    S0258/S0259).

    Partition selection is the same bounded binary discipline already used by
    the external fitted-model v1 / internal multiclass v2 / continuous-
    regression v3 projectors:

        selected =
          final_test_evaluation
            when it is a dict and its `completed` is exactly True
          otherwise validation_evaluation

    This profile carries no cross_validation_summary / train partition at all,
    so a training/fitting partition can never be selected. Validation and
    final-test metrics are never combined and no score is recomputed.

    Only the selected partition's `partition_role` (-> split_name),
    `row_count` (-> sample_size, when a real int), and bounded alias-
    normalized name/value metric entries are projected. The v5 schema
    designates no public primary metric, so `primary_metric_id` is never
    fabricated and remains None. `classification_evidence`, `path_references`,
    `hashes`, `training_run_identity`, and `evidence_policy` are validated
    upstream but are never read into the public projection.
    """
    final_test = payload.get("final_test_evaluation")
    validation = payload.get("validation_evaluation")
    selected = (
        final_test
        if isinstance(final_test, dict) and final_test.get("completed") is True
        else validation
    )

    split_name = None
    sample_size = None
    entries: list[tuple[Any, Any, bool]] = []
    if isinstance(selected, dict):
        split_name = _optional_str(selected.get("partition_role"))
        sample_size = _optional_int(selected.get("row_count"))
        raw_metrics = selected.get("metrics")
        if isinstance(raw_metrics, list):
            entries = [
                (item.get("name"), item.get("value"), False)
                for item in raw_metrics
                if isinstance(item, dict)
            ]

    metrics, metric_order = _project_metric_entries(entries)

    return {
        "evaluation": {
            "split_name": split_name,
            "sample_size": sample_size,
            "primary_metric_id": None,
            "metrics": metrics,
            "metric_order": metric_order,
        }
    }


def _project_public_metrics(payload: dict) -> dict:
    if payload.get("schema_version") == _EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION:
        return _project_external_fitted_model_metrics(payload)
    if payload.get("schema_version") == _EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION_V2:
        return _project_external_fitted_model_metrics_v2(payload)
    if payload.get("schema_version") == _INTERNAL_MULTICLASS_METRICS_SCHEMA_VERSION_V2:
        return _project_internal_multiclass_metrics_v2(payload)
    if payload.get("schema_version") == _INTERNAL_CONTINUOUS_REGRESSION_METRICS_SCHEMA_VERSION_V3:
        return _project_internal_continuous_regression_metrics_v3(payload)
    if payload.get("schema_version") == _INTERNAL_FORECASTING_METRICS_SCHEMA_VERSION_V4:
        return _project_internal_forecasting_metrics_v4(payload)
    if payload.get("schema_version") == _INTERNAL_NATIVE_BINARY_METRICS_SCHEMA_VERSION_V5:
        return _project_internal_native_binary_metrics_v5(payload)
    metrics_block = payload.get("metrics")
    if isinstance(metrics_block, dict) and isinstance(metrics_block.get("primary_metric"), dict):
        return _project_training_metrics_v1(payload)
    if isinstance(payload.get("evaluation"), dict):
        return _project_legacy_evaluation_shape(payload)
    return _project_flat_top_level_shape(payload)


def load_public_metrics(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the public metrics projection from the active release package.

    The manifest must declare a metrics artifact. The artifact path is
    release-package-relative and is path-checked before reading. The raw
    artifact is never returned as-is: it is always normalized into the
    stable evaluation projection documented at module level, regardless of
    which recognized source shape it was written in. No model is loaded and
    no inference is executed by this loader.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    metrics_ref = _artifact_reference(manifest, _METRICS_ROLE)
    if metrics_ref is None:
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    metrics_path = (release_dir / metrics_ref).resolve()
    if not metrics_path.is_relative_to(release_dir.resolve()):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    try:
        raw = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    if not isinstance(raw, dict):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    return _project_public_metrics(raw)
