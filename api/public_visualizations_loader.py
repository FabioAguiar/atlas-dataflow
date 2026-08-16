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
_ACCEPTED_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSIONS = (
    _ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION,
    _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION,
    _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION_V2,
)
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
    analytical-visualizations.v1 (Project Spec S0128) or
    analytical-visualizations.external-fitted-model.v1 (Project Spec
    S0193) document. Both profiles project the identical bounded shape."""
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
    if visualizations.get("schema_version") != _ANALYTICAL_VISUALIZATIONS_EXTERNAL_SCHEMA_VERSION_V2:
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

    projection = _safe_projection(payload)
    if not isinstance(projection, dict):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )
    return projection
