"""
Public visualizations loader for M7-03.

Loads pre-computed chart data from the active release package and returns
a safe projection for public consumption. Internal field names, artifact
paths, and publisher-internal keys are filtered before API exposure.
"""

import json
import math
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_VISUALIZATIONS_ROLE = "visualizations"

# Project Spec S0128: canonical artifact identity and bounded chart
# structure the public loader requires before it will ever return a
# projection. Any artifact that fails these checks is treated exactly like a
# missing artifact -- the loader never exposes internal validation details,
# it only raises the existing PublicVisualizationsUnavailableError.
#
# Project Spec S0193: the validated external fitted-model profile
# (analytical-visualizations.external-fitted-model.v1) is accepted
# alongside the historical v1 identity below -- both project the identical
# bounded public chart shape, so the UI needs no changes. Only the
# artifact's own identity/chart-list validity is checked here; provenance,
# hashes, and other external-only fields are never read into the public
# projection.
_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION = "analytical-visualizations.v1"
_ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION = "analytical-visualizations.external-fitted-model.v1"
# Project Spec S0215: the multiclass v2 external profile projects the same
# bounded Target Distribution/Feature Importance charts as v1, plus an
# additional bounded confusion_matrix (see _bounded_confusion_matrix below).
_ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION_V2 = "analytical-visualizations.external-fitted-model.v2"
# Project Spec S0216: the internal (Atlas-native) multiclass fixed-
# configuration visualizations profile projects the identical bounded
# Target Distribution/Feature Importance charts as v1, plus the same
# bounded confusion_matrix shape as the external v2 profile.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V2 = "analytical-visualizations.v2"
# Project Spec S0228: the internal (Atlas-native) continuous-regression
# fixed-configuration visualizations profile projects the same bounded
# Target Distribution/Feature Importance charts as v1/v2, plus a bounded
# regression_diagnostics projection (actual_vs_predicted/
# residual_distribution) and an explicit continuous target-distribution
# discriminator -- never a confusion_matrix.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V3 = "analytical-visualizations.v3"
# Project Spec S0279: the internal (Atlas-native) binary fixed-configuration
# visualizations profile (Project Specs S0258/S0259). It deliberately
# preserves the identical bounded Target Distribution / Feature Importance
# canonical chart shape as v1/v2/v3, so it is admitted to the canonical chart
# projector below and reuses the existing S0205 prepared-dataset
# dataset-statistics derivation unchanged. Its extra classification_evidence /
# feature_importance_method / target_distribution_method blocks are provenance
# authorities only and are never read into the public projection. It never
# gains a confusion_matrix, regression_diagnostics, or any forecasting field.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V5 = "analytical-visualizations.v5"
# Project Spec S0248: the internal (Atlas-native) univariate-forecasting
# fixed-configuration visualizations profile. Unlike v1/v2/v3, it carries no
# `charts`/`target_distribution_method`/`feature_importance_method` at all --
# it is handled by its own early branch in load_public_visualizations below,
# never through _canonical_public_charts.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V4 = "analytical-visualizations.v4"
# Project Spec S0270: the governed native univariate-forecasting final-holdout
# visual-evidence evolution of v4. v6 projects the same bounded
# dataset_statistics/forecasting_diagnostics as v4 (identical shape and rules)
# and additionally adds one bounded `forecasting_evaluation` projection
# suitable for a later Forecast-vs-Actual renderer. It is handled by the same
# early forecasting branch in load_public_visualizations below. A historical
# v4 release is unchanged and never gains a `forecasting_evaluation` field.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V6 = "analytical-visualizations.v6"
# Project Spec S0274: the governed native univariate-forecasting multi-metric
# backtesting/horizon diagnostic evolution of v6. v7 projects everything v6
# projects (dataset_statistics, forecasting_diagnostics legacy fields,
# forecasting_evaluation) and additionally projects a bounded
# forecasting_diagnostics.metric_diagnostics block -- metric identity/direction
# plus bounded by-origin (fold_index/forecast_origin/value) and by-horizon
# (horizon_step/value/observation_count) points only. Never validation
# observations, seasonal scales, raw fold errors, or a recomputed metric. A
# historical v4/v6 release is unchanged and never gains metric_diagnostics.
_ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V7 = "analytical-visualizations.v7"
_FORECASTING_SCHEMA_VERSIONS = (
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V4,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V6,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V7,
)
_FORECASTING_SUPPORTED_METRIC_IDS = ("mae", "rmse", "seasonal_mase")
_MAX_FORECASTING_METRIC_DIAGNOSTICS = 3
_ACCEPTED_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSIONS = (
    _ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION,
    _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION,
    _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION_V2,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V2,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V3,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V5,
)
_MAX_FORECASTING_SEASONAL_POINTS = 64
_MAX_FORECASTING_FOLD_POINTS = 64
_MAX_FORECASTING_HORIZON_POINTS = 64
_MAX_FORECASTING_FINAL_HOLDOUT_POINTS = 64
_FORECASTING_INDEX_VALUE_KINDS = ("calendar_period", "timestamp", "ordinal_time")
_CONFUSION_MATRIX_SCHEMA_VERSIONS = (
    _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION_V2,
    _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V2,
)
_MAX_REGRESSION_DIAGNOSTIC_POINTS = 32
_ANALYTICAL_VISUALIZATIONS_ARTIFACT_KIND = "analytical_visualizations"
_REQUIRED_CHART_IDS = ("target_distribution", "feature_importance")
_MAX_CHART_DATA_POINTS = 64
_TARGET_DISTRIBUTION_CHART_ID = "target_distribution"
_CONFUSION_MATRIX_ROW_SUM_TOLERANCE = 1e-6

# Project Spec S0205: population_kind identities the bounded dataset-
# population derivation accepts as an instance-count authority. Any other
# (or missing) population_kind never produces dataset_statistics.
_HISTORICAL_POPULATION_KIND = "prepared_dataset"
_EXTERNAL_POPULATION_KIND = "external_prepared_dataset"

_INTERNAL_KEYS = {
    "artifact",
    "artifacts",
    "constraints",
    "domain_constraints",
    "hidden_constraints",
    "implementation",
    "internal",
    "path",
    "reference",
    "release",
    "required",
    "schema",
    "validation",
    "validators",
}


class PublicVisualizationsUnavailableError(Exception):
    """The public visualizations data is absent from or unreadable in the active release package."""

    code = "PUBLIC_VISUALIZATIONS_UNAVAILABLE"


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


def _is_finite_non_negative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _bounded_chart_data(chart: Any) -> list[dict[str, Any]] | None:
    if not isinstance(chart, dict):
        return None
    data = chart.get("data")
    if not isinstance(data, list) or not data or len(data) > _MAX_CHART_DATA_POINTS:
        return None
    points: list[dict[str, Any]] = []
    for point in data:
        if not isinstance(point, dict):
            return None
        name = point.get("name")
        value = point.get("value")
        if not isinstance(name, str) or not name:
            return None
        if not _is_finite_non_negative_number(value):
            return None
        points.append({"name": name, "value": value})
    return points


def _canonical_public_charts(visualizations: Any) -> list[dict[str, Any]] | None:
    """Require the canonical artifact identity and a bounded, well-formed
    chart structure before any projection is built. Returns exactly the
    two required charts (target_distribution, feature_importance), in that
    order, or None when the artifact is not a valid, canonical
    analytical-visualizations document whose schema_version is in
    _ACCEPTED_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSIONS -- the historical
    v1 (Project Spec S0128), the external fitted-model v1 (Project Spec
    S0193), external v2 / internal v2 / internal v3, and the Atlas-native
    binary fixed-configuration v5 (Project Spec S0279). Every accepted
    profile projects the identical bounded public chart shape."""
    if not isinstance(visualizations, dict):
        return None
    if visualizations.get("schema_version") not in _ACCEPTED_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSIONS:
        return None
    if visualizations.get("artifact_kind") != _ANALYTICAL_VISUALIZATIONS_ARTIFACT_KIND:
        return None

    charts = visualizations.get("charts")
    if not isinstance(charts, list):
        return None

    charts_by_id: dict[str, dict] = {}
    for chart in charts:
        if not isinstance(chart, dict):
            return None
        chart_id = chart.get("id")
        if not isinstance(chart_id, str) or chart_id in charts_by_id:
            return None
        charts_by_id[chart_id] = chart

    canonical_charts: list[dict[str, Any]] = []
    for required_id in _REQUIRED_CHART_IDS:
        chart = charts_by_id.get(required_id)
        data_points = _bounded_chart_data(chart)
        if data_points is None:
            return None
        title = chart.get("title")
        chart_type = chart.get("type")
        x_label = chart.get("x_label")
        y_label = chart.get("y_label")
        if not all(isinstance(field, str) and field for field in (title, chart_type, x_label, y_label)):
            return None
        canonical_charts.append({
            "id": required_id,
            "title": title,
            "type": chart_type,
            "x_label": x_label,
            "y_label": y_label,
            "data": data_points,
        })
    return canonical_charts


def _is_integer_like_non_negative_number(value: Any) -> bool:
    if not _is_finite_non_negative_number(value):
        return False
    return isinstance(value, int) or value.is_integer()


def _integer_population_total(points: list[dict[str, Any]]) -> int | None:
    """Sums a canonical Target Distribution chart's own point values into a
    single population total, requiring every value to be integer-like and
    non-negative first. Returns None (never a fabricated/partial total) the
    moment any point fails that requirement, or when the total is not
    strictly positive."""
    total = 0
    for point in points:
        value = point.get("value")
        if not _is_integer_like_non_negative_number(value):
            return None
        total += int(value)
    return total if total > 0 else None


def _target_distribution_points(canonical_charts: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    for chart in canonical_charts:
        if chart.get("id") == _TARGET_DISTRIBUTION_CHART_ID:
            return chart.get("data")
    return None


def _dataset_statistics(
    visualizations: dict[str, Any],
    canonical_charts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Project Spec S0205: derives a bounded dataset_statistics.instance_count
    only from the canonical Target Distribution the public chart projection
    already validated -- never from feature_importance, metrics, model-card
    text, or any other field. Returns None whenever the declared population
    kind is missing/unrecognized, or the count inputs cannot be safely
    proven (never a partial/best-guess total)."""
    method = visualizations.get("target_distribution_method")
    if not isinstance(method, dict):
        return None
    population_kind = method.get("population_kind")

    points = _target_distribution_points(canonical_charts)
    if points is None:
        return None

    if population_kind == _HISTORICAL_POPULATION_KIND:
        row_count = method.get("row_count")
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count <= 0:
            return None
        chart_total = _integer_population_total(points)
        if chart_total is None or chart_total != row_count:
            return None
        return {"instance_count": row_count}

    if population_kind == _EXTERNAL_POPULATION_KIND:
        chart_total = _integer_population_total(points)
        if chart_total is None:
            return None
        return {"instance_count": chart_total}

    return None


def _is_finite_unit_interval(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _bounded_confusion_matrix(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0215 Desired Change: bounded public projection of a
    normalized multiclass confusion matrix, only for a valid
    analytical-visualizations.external-fitted-model.v2 artifact. Re-validates
    shape, bounds, and per-row normalization defensively (never trusting the
    materializer's own validation alone) and returns exactly
    ordered_class_ids/matrix/row_axis/column_axis -- no source paths,
    provenance, or other internal fields."""
    if visualizations.get("schema_version") not in _CONFUSION_MATRIX_SCHEMA_VERSIONS:
        return None

    confusion_matrix = visualizations.get("confusion_matrix")
    if not isinstance(confusion_matrix, dict):
        return None
    if confusion_matrix.get("row_axis") != "true_class" or confusion_matrix.get("column_axis") != "predicted_class":
        return None

    ordered_class_ids = confusion_matrix.get("ordered_class_ids")
    if (
        not isinstance(ordered_class_ids, list)
        or len(ordered_class_ids) < 3
        or len(set(ordered_class_ids)) != len(ordered_class_ids)
        or not all(isinstance(class_id, str) and class_id for class_id in ordered_class_ids)
    ):
        return None

    class_count = len(ordered_class_ids)
    rows = confusion_matrix.get("matrix")
    if not isinstance(rows, list) or len(rows) != class_count:
        return None

    normalized_rows: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != class_count:
            return None
        normalized_row: list[float] = []
        row_sum = 0.0
        for cell in row:
            if not _is_finite_unit_interval(cell):
                return None
            normalized_row.append(float(cell))
            row_sum += float(cell)
        if abs(row_sum - 1.0) > _CONFUSION_MATRIX_ROW_SUM_TOLERANCE:
            return None
        normalized_rows.append(normalized_row)

    return {
        "ordered_class_ids": list(ordered_class_ids),
        "matrix": normalized_rows,
        "row_axis": "true_class",
        "column_axis": "predicted_class",
    }


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_non_negative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _bounded_actual_vs_predicted(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0228: bounded public projection of the Actual vs
    Predicted aggregate for a valid analytical-visualizations.v3 artifact.
    Re-validates shape and bounds defensively and returns only the aggregate
    mean points needed to draw the chart -- no method source, training-run
    identity, or other internal fields."""
    data = visualizations.get("actual_vs_predicted")
    if not isinstance(data, dict):
        return None
    if data.get("partition_role") != "test" or data.get("reference_line") != "identity":
        return None
    points = data.get("points")
    if not isinstance(points, list) or not points or len(points) > _MAX_REGRESSION_DIAGNOSTIC_POINTS:
        return None
    bounded_points: list[dict[str, Any]] = []
    for point in points:
        if not isinstance(point, dict):
            return None
        actual_mean = point.get("actual_mean")
        predicted_mean = point.get("predicted_mean")
        count = point.get("count")
        if not _is_finite_number(actual_mean) or not _is_finite_number(predicted_mean):
            return None
        if not _is_positive_integer(count):
            return None
        bounded_points.append({
            "actual_mean": float(actual_mean),
            "predicted_mean": float(predicted_mean),
            "count": count,
        })
    return {"points": bounded_points}


def _bounded_residual_distribution(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0228: bounded public projection of the Residual
    Distribution aggregate for a valid analytical-visualizations.v3
    artifact. Re-validates shape and bounds defensively and returns only
    the already-binned aggregate counts -- never a raw residual vector."""
    data = visualizations.get("residual_distribution")
    if not isinstance(data, dict):
        return None
    if (
        data.get("partition_role") != "test"
        or data.get("residual_definition") != "actual_minus_predicted"
    ):
        return None
    bins = data.get("bins")
    if not isinstance(bins, list) or not bins or len(bins) > _MAX_REGRESSION_DIAGNOSTIC_POINTS:
        return None
    bounded_bins: list[dict[str, Any]] = []
    for bin_entry in bins:
        if not isinstance(bin_entry, dict):
            return None
        label = bin_entry.get("label")
        count = bin_entry.get("count")
        if not isinstance(label, str) or not label:
            return None
        if not _is_non_negative_integer(count):
            return None
        bounded_bins.append({"label": label, "count": count})
    return {"bins": bounded_bins}


def _bounded_regression_diagnostics(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0228: bounded public regression_diagnostics projection,
    only for a valid analytical-visualizations.v3 artifact. Returns None
    (never a partially projected, unverified result) unless both
    actual_vs_predicted and residual_distribution independently re-validate
    -- the caller treats None as fail-closed to the unavailable state."""
    actual_vs_predicted = _bounded_actual_vs_predicted(visualizations)
    residual_distribution = _bounded_residual_distribution(visualizations)
    if actual_vs_predicted is None or residual_distribution is None:
        return None
    return {
        "actual_vs_predicted": actual_vs_predicted,
        "residual_distribution": residual_distribution,
    }


def _forecasting_dataset_statistics(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0248: bounded public dataset_statistics.instance_count
    projection for a valid analytical-visualizations.v4 artifact -- the same
    reduced shape v1/v2/v3 project via _dataset_statistics above, sourced
    here from the v4 artifact's own already-validated dataset_statistics
    block instead of a Target Distribution chart total."""
    data = visualizations.get("dataset_statistics")
    if not isinstance(data, dict):
        return None
    instance_count = data.get("instance_count")
    if not _is_positive_integer(instance_count):
        return None
    return {"instance_count": instance_count}


def _bounded_forecasting_seasonal_profile(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0248: bounded public seasonal_profile projection.
    Re-validates shape and bounds defensively (never trusting the
    materializer's own validation alone) and returns only
    seasonal_period/points -- no population_kind or other internal fields."""
    data = visualizations.get("seasonal_profile")
    if not isinstance(data, dict) or data.get("population_kind") != "full_development":
        return None
    seasonal_period = data.get("seasonal_period")
    if not _is_positive_integer(seasonal_period) or seasonal_period < 2:
        return None
    points = data.get("points")
    if not isinstance(points, list) or not points or len(points) > _MAX_FORECASTING_SEASONAL_POINTS:
        return None

    bounded_points: list[dict[str, Any]] = []
    seen_positions: set[int] = set()
    for point in points:
        if not isinstance(point, dict):
            return None
        season_position = point.get("season_position")
        mean_target = point.get("mean_target")
        observation_count = point.get("observation_count")
        if (
            not isinstance(season_position, int)
            or isinstance(season_position, bool)
            or season_position < 0
            or season_position >= seasonal_period
            or season_position in seen_positions
        ):
            return None
        seen_positions.add(season_position)
        if not _is_finite_number(mean_target):
            return None
        if not _is_positive_integer(observation_count):
            return None
        bounded_points.append({
            "season_position": season_position,
            "mean_target": float(mean_target),
            "observation_count": observation_count,
        })

    bounded_points.sort(key=lambda entry: entry["season_position"])
    return {"seasonal_period": seasonal_period, "points": bounded_points}


def _bounded_forecasting_backtesting_fold_metric(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0248: bounded public backtesting_fold_metric
    projection. Re-validates shape and bounds defensively and returns only
    metric_id/direction/points -- no fold_count or other internal fields."""
    data = visualizations.get("backtesting_fold_metric")
    if not isinstance(data, dict) or data.get("direction") != "lower_is_better":
        return None
    metric_id = data.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id:
        return None
    points = data.get("points")
    if not isinstance(points, list) or not points or len(points) > _MAX_FORECASTING_FOLD_POINTS:
        return None

    bounded_points: list[dict[str, Any]] = []
    seen_fold_indices: set[int] = set()
    for point in points:
        if not isinstance(point, dict):
            return None
        fold_index = point.get("fold_index")
        forecast_origin = point.get("forecast_origin")
        value = point.get("value")
        if (
            not isinstance(fold_index, int)
            or isinstance(fold_index, bool)
            or fold_index < 0
            or fold_index in seen_fold_indices
        ):
            return None
        seen_fold_indices.add(fold_index)
        if not isinstance(forecast_origin, str) or not forecast_origin:
            return None
        if not _is_finite_number(value):
            return None
        bounded_points.append({
            "fold_index": fold_index,
            "forecast_origin": forecast_origin,
            "value": float(value),
        })

    bounded_points.sort(key=lambda entry: entry["fold_index"])
    return {"metric_id": metric_id, "direction": "lower_is_better", "points": bounded_points}


def _bounded_forecasting_horizon_mae(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0248: bounded public horizon_mae projection. Never
    recomputes MAE -- only re-validates the already-computed, already-bounded
    per-horizon-step values."""
    data = visualizations.get("horizon_mae")
    if not isinstance(data, dict):
        return None
    points = data.get("points")
    if not isinstance(points, list) or not points or len(points) > _MAX_FORECASTING_HORIZON_POINTS:
        return None

    bounded_points: list[dict[str, Any]] = []
    seen_steps: set[int] = set()
    for point in points:
        if not isinstance(point, dict):
            return None
        horizon_step = point.get("horizon_step")
        mae = point.get("mae")
        if (
            not isinstance(horizon_step, int)
            or isinstance(horizon_step, bool)
            or horizon_step < 1
            or horizon_step in seen_steps
        ):
            return None
        seen_steps.add(horizon_step)
        if not _is_finite_non_negative_number(mae):
            return None
        bounded_points.append({"horizon_step": horizon_step, "mae": mae})

    bounded_points.sort(key=lambda entry: entry["horizon_step"])
    return {"points": bounded_points}


def _bounded_forecasting_diagnostics(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0248: bounded public forecasting_diagnostics projection
    for a valid analytical-visualizations.v4 artifact. Returns None (never a
    partially projected, unverified result) unless every sub-projection
    independently re-validates."""
    forecasting_evidence = visualizations.get("forecasting_evidence")
    if not isinstance(forecasting_evidence, dict):
        return None
    if forecasting_evidence.get("problem_type") != "univariate_forecasting":
        return None
    forecast_horizon = forecasting_evidence.get("forecast_horizon")
    if not _is_positive_integer(forecast_horizon):
        return None
    frequency = forecasting_evidence.get("frequency")
    if not isinstance(frequency, str) or not frequency:
        return None

    seasonal_profile = _bounded_forecasting_seasonal_profile(visualizations)
    backtesting_fold_metric = _bounded_forecasting_backtesting_fold_metric(visualizations)
    horizon_mae = _bounded_forecasting_horizon_mae(visualizations)
    if seasonal_profile is None or backtesting_fold_metric is None or horizon_mae is None:
        return None

    return {
        "forecast_horizon": forecast_horizon,
        "frequency": frequency,
        "seasonal_profile": seasonal_profile,
        "backtesting_fold_metric": backtesting_fold_metric,
        "horizon_mae": horizon_mae,
    }


def _bounded_public_evaluation_boundary(value: Any) -> dict[str, Any] | None:
    """Project Spec S0270: bounded public projection of one temporal boundary
    (development / final_holdout). Re-validates shape and bounds defensively
    and returns only start_index/end_index/observation_count."""
    if not isinstance(value, dict):
        return None
    start_index = value.get("start_index")
    end_index = value.get("end_index")
    observation_count = value.get("observation_count")
    if not isinstance(start_index, str) or not start_index:
        return None
    if not isinstance(end_index, str) or not end_index:
        return None
    if not _is_positive_integer(observation_count):
        return None
    return {
        "start_index": start_index,
        "end_index": end_index,
        "observation_count": observation_count,
    }


def _bounded_forecasting_evaluation(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0270: bounded public forecasting_evaluation projection
    for a valid analytical-visualizations.v6 artifact. Independently
    re-validates the final_holdout_forecast_evaluation block (never trusting
    the producer's/publisher's own validation alone) and returns only
    presentation-safe temporal context plus the exact aligned points --
    time_index/actual/forecast. Returns None (fail-closed, never a partial
    projection) on any violation. Never duplicates MAE/RMSE/seasonal-MASE, a
    training-run path/hash, the preparation recipe, source column names, or
    model state."""
    forecasting_evidence = visualizations.get("forecasting_evidence")
    if not isinstance(forecasting_evidence, dict):
        return None
    if forecasting_evidence.get("problem_type") != "univariate_forecasting":
        return None
    forecast_horizon = forecasting_evidence.get("forecast_horizon")
    frequency = forecasting_evidence.get("frequency")
    if not _is_positive_integer(forecast_horizon):
        return None
    if not isinstance(frequency, str) or not frequency:
        return None

    dataset_statistics = visualizations.get("dataset_statistics")
    if not isinstance(dataset_statistics, dict):
        return None
    final_holdout_observations = dataset_statistics.get("final_holdout_observations")
    development_observations = dataset_statistics.get("development_observations")
    if not _is_positive_integer(final_holdout_observations) or not _is_positive_integer(development_observations):
        return None

    block = visualizations.get("final_holdout_forecast_evaluation")
    if not isinstance(block, dict):
        return None
    if (
        block.get("partition_role") != "final_holdout"
        or block.get("evaluation_count") != 1
        or block.get("model_frozen_before_open") is not True
        or block.get("forecast_generated_before_target_open") is not True
    ):
        return None
    index_value_kind = block.get("index_value_kind")
    block_frequency = block.get("frequency")
    if index_value_kind not in _FORECASTING_INDEX_VALUE_KINDS:
        return None
    if not isinstance(block_frequency, str) or not block_frequency or block_frequency != frequency:
        return None

    development_boundary = _bounded_public_evaluation_boundary(block.get("development_boundary"))
    final_holdout_boundary = _bounded_public_evaluation_boundary(block.get("final_holdout_boundary"))
    if development_boundary is None or final_holdout_boundary is None:
        return None
    if development_boundary["observation_count"] != development_observations:
        return None
    if final_holdout_boundary["observation_count"] != final_holdout_observations:
        return None

    points = block.get("points")
    if (
        not isinstance(points, list)
        or not points
        or len(points) > _MAX_FORECASTING_FINAL_HOLDOUT_POINTS
    ):
        return None
    if not (len(points) == final_holdout_observations == forecast_horizon):
        return None

    bounded_points: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            return None
        time_index = point.get("time_index")
        actual = point.get("actual")
        forecast = point.get("forecast")
        if not isinstance(time_index, str) or not time_index or time_index in seen_labels:
            return None
        seen_labels.add(time_index)
        if not _is_finite_number(actual) or not _is_finite_number(forecast):
            return None
        bounded_points.append({
            "time_index": time_index,
            "actual": float(actual),
            "forecast": float(forecast),
        })

    if (
        bounded_points[0]["time_index"] != final_holdout_boundary["start_index"]
        or bounded_points[-1]["time_index"] != final_holdout_boundary["end_index"]
    ):
        return None

    return {
        "index_value_kind": index_value_kind,
        "frequency": frequency,
        "development_boundary": development_boundary,
        "final_holdout_boundary": final_holdout_boundary,
        "evaluation": {
            "split_name": "final_holdout",
            "evaluation_count": 1,
            "model_frozen_before_open": True,
            "forecast_generated_before_target_open": True,
        },
        "points": bounded_points,
    }


def _bounded_forecasting_metric_diagnostics(visualizations: dict[str, Any]) -> dict[str, Any] | None:
    """Project Spec S0274: bounded public metric_diagnostics projection for a
    valid analytical-visualizations.v7 artifact. Independently re-validates and
    bounds the forecasting_metric_diagnostics block (never trusting the
    producer's/publisher's validation alone) and returns, for every metric,
    only metric_id/direction plus bounded by-origin (fold_index/forecast_origin/
    value) and by-horizon (horizon_step/value/observation_count) points.
    Returns None (fail-closed, never a partial metric set) on any violation.
    Never exposes validation_observations, fold_count, seasonal scales, raw fold
    errors, or a recomputed metric; the public loader computes no MAE/RMSE/MASE."""
    data = visualizations.get("forecasting_metric_diagnostics")
    if not isinstance(data, dict):
        return None
    metrics = data.get("metrics")
    if (
        not isinstance(metrics, list)
        or not metrics
        or len(metrics) > _MAX_FORECASTING_METRIC_DIAGNOSTICS
    ):
        return None

    bounded_metrics: list[dict[str, Any]] = []
    seen_metric_ids: set[str] = set()
    for entry in metrics:
        if not isinstance(entry, dict):
            return None
        metric_id = entry.get("metric_id")
        if metric_id not in _FORECASTING_SUPPORTED_METRIC_IDS or metric_id in seen_metric_ids:
            return None
        seen_metric_ids.add(metric_id)
        if entry.get("direction") != "lower_is_better":
            return None

        by_origin = entry.get("backtesting_by_origin")
        if not isinstance(by_origin, dict):
            return None
        origin_points = by_origin.get("points")
        if (
            not isinstance(origin_points, list)
            or not origin_points
            or len(origin_points) > _MAX_FORECASTING_FOLD_POINTS
        ):
            return None
        bounded_origin: list[dict[str, Any]] = []
        seen_folds: set[int] = set()
        for point in origin_points:
            if not isinstance(point, dict):
                return None
            fold_index = point.get("fold_index")
            forecast_origin = point.get("forecast_origin")
            value = point.get("value")
            if (
                not isinstance(fold_index, int)
                or isinstance(fold_index, bool)
                or fold_index < 0
                or fold_index in seen_folds
            ):
                return None
            seen_folds.add(fold_index)
            if not isinstance(forecast_origin, str) or not forecast_origin:
                return None
            if not _is_finite_number(value):
                return None
            bounded_origin.append({
                "fold_index": fold_index,
                "forecast_origin": forecast_origin,
                "value": float(value),
            })
        bounded_origin.sort(key=lambda item: item["fold_index"])

        by_horizon = entry.get("by_horizon")
        if not isinstance(by_horizon, dict):
            return None
        horizon_points = by_horizon.get("points")
        if (
            not isinstance(horizon_points, list)
            or not horizon_points
            or len(horizon_points) > _MAX_FORECASTING_HORIZON_POINTS
        ):
            return None
        bounded_horizon: list[dict[str, Any]] = []
        seen_steps: set[int] = set()
        for point in horizon_points:
            if not isinstance(point, dict):
                return None
            horizon_step = point.get("horizon_step")
            value = point.get("value")
            observation_count = point.get("observation_count")
            if (
                not isinstance(horizon_step, int)
                or isinstance(horizon_step, bool)
                or horizon_step < 1
                or horizon_step in seen_steps
            ):
                return None
            seen_steps.add(horizon_step)
            if not _is_finite_non_negative_number(value):
                return None
            if not _is_positive_integer(observation_count):
                return None
            bounded_horizon.append({
                "horizon_step": horizon_step,
                "value": float(value),
                "observation_count": observation_count,
            })
        bounded_horizon.sort(key=lambda item: item["horizon_step"])

        bounded_metrics.append({
            "metric_id": metric_id,
            "direction": "lower_is_better",
            "backtesting_by_origin": {"points": bounded_origin},
            "by_horizon": {"points": bounded_horizon},
        })

    return {"metrics": bounded_metrics}


def _safe_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_projection(nested)
            for key, nested in value.items()
            if key not in _INTERNAL_KEYS and not key.startswith("_")
        }
    if isinstance(value, list):
        return [_safe_projection(item) for item in value]
    return value


def load_public_visualizations(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the public visualizations projection from the active release package.

    The manifest must declare a visualizations artifact. The artifact path is
    release-package-relative and is path-checked before reading. A final
    defensive projection removes known internal keys before API exposure.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )

    viz_ref = _artifact_reference(manifest, _VISUALIZATIONS_ROLE)
    if viz_ref is None:
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )

    viz_path = (release_dir / viz_ref).resolve()
    if not viz_path.is_relative_to(release_dir.resolve()):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )

    try:
        visualizations = json.loads(viz_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )

    # Project Spec S0248 / S0270 / S0274: a v4, v6, or v7 native forecasting
    # artifact carries no charts/target_distribution_method/
    # feature_importance_method at all, so it is handled by its own early branch
    # here rather than through _canonical_public_charts below. A structurally
    # invalid document degrades to the same bounded unavailable response as a
    # missing one. v6 and v7 additionally project one bounded
    # `forecasting_evaluation`; v7 additionally projects one bounded
    # `forecasting_diagnostics.metric_diagnostics`. A historical v4 release is
    # unchanged and never gains either field; a historical v6 release is
    # unchanged and never gains metric_diagnostics.
    if (
        isinstance(visualizations, dict)
        and visualizations.get("schema_version") in _FORECASTING_SCHEMA_VERSIONS
    ):
        schema_version = visualizations.get("schema_version")
        projects_evaluation = schema_version in (
            _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V6,
            _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V7,
        )
        projects_metric_diagnostics = (
            schema_version == _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V7
        )
        if visualizations.get("artifact_kind") != _ANALYTICAL_VISUALIZATIONS_ARTIFACT_KIND:
            raise PublicVisualizationsUnavailableError(
                "Visualizations are not available for this release."
            )
        dataset_statistics = _forecasting_dataset_statistics(visualizations)
        forecasting_diagnostics = _bounded_forecasting_diagnostics(visualizations)
        if dataset_statistics is None or forecasting_diagnostics is None:
            raise PublicVisualizationsUnavailableError(
                "Visualizations are not available for this release."
            )
        if projects_metric_diagnostics:
            metric_diagnostics = _bounded_forecasting_metric_diagnostics(visualizations)
            if metric_diagnostics is None:
                raise PublicVisualizationsUnavailableError(
                    "Visualizations are not available for this release."
                )
            forecasting_diagnostics = {
                **forecasting_diagnostics,
                "metric_diagnostics": metric_diagnostics,
            }
        # `charts: []` keeps this payload compatible with the frontend's
        # `toVisualizationsPayload` guard (web/src/lib/livePreviewProjection.ts,
        # out of this spec's edit scope), which only accepts a payload that
        # carries a `charts` key -- it never exposes any chart content.
        payload: dict[str, Any] = {
            "charts": [],
            "dataset_statistics": dataset_statistics,
            "forecasting_diagnostics": forecasting_diagnostics,
        }
        if projects_evaluation:
            forecasting_evaluation = _bounded_forecasting_evaluation(visualizations)
            if forecasting_evaluation is None:
                raise PublicVisualizationsUnavailableError(
                    "Visualizations are not available for this release."
                )
            payload["forecasting_evaluation"] = forecasting_evaluation
        projection = _safe_projection(payload)
        if not isinstance(projection, dict):
            raise PublicVisualizationsUnavailableError(
                "Visualizations are not available for this release."
            )
        return projection

    # Project Spec S0128: require the canonical artifact identity and a
    # bounded, well-formed chart structure before any projection is
    # returned. A structurally invalid new artifact degrades to the same
    # bounded unavailable response as a missing one -- it never exposes
    # internal validation details.
    canonical_charts = _canonical_public_charts(visualizations)
    if canonical_charts is None:
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )

    # Project Spec S0205: a bounded dataset-population derivation, added only
    # when the governed artifact safely proves the total dataset population
    # through its own canonical Target Distribution. The internal
    # target_distribution_method block itself is never exposed -- only the
    # derived instance_count integer.
    payload: dict[str, Any] = {"charts": canonical_charts}
    dataset_statistics = _dataset_statistics(visualizations, canonical_charts)
    if dataset_statistics is not None:
        payload["dataset_statistics"] = dataset_statistics

    confusion_matrix = _bounded_confusion_matrix(visualizations)
    if confusion_matrix is not None:
        payload["confusion_matrix"] = confusion_matrix

    # Project Spec S0228: a v3 continuous-regression artifact always
    # projects an explicit target_distribution_kind discriminator plus a
    # bounded regression_diagnostics shape. Malformed v3 diagnostic evidence
    # fails closed to the existing bounded unavailable state rather than
    # partially projecting unverified diagnostics.
    if visualizations.get("schema_version") == _ANALYTICAL_VISUALIZATIONS_INTERNAL_SCHEMA_VERSION_V3:
        regression_diagnostics = _bounded_regression_diagnostics(visualizations)
        if regression_diagnostics is None:
            raise PublicVisualizationsUnavailableError(
                "Visualizations are not available for this release."
            )
        payload["target_distribution_kind"] = "continuous_histogram"
        payload["regression_diagnostics"] = regression_diagnostics

    projection = _safe_projection(payload)
    if not isinstance(projection, dict):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )
    return projection
