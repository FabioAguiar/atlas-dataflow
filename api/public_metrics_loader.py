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
}

# Project Spec S0191: schema_version discriminator for the external
# fitted-model training-metrics profile, dispatched on explicitly (never by
# loose shape matching).
_EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION = "training-metrics.external-fitted-model.v1"

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


def _project_public_metrics(payload: dict) -> dict:
    if payload.get("schema_version") == _EXTERNAL_FITTED_MODEL_METRICS_SCHEMA_VERSION:
        return _project_external_fitted_model_metrics(payload)
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
