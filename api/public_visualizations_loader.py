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
_ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION = "analytical-visualizations.v1"
_ANALYTICAL_VISUALIZATIONS_ARTIFACT_KIND = "analytical_visualizations"
_REQUIRED_CHART_IDS = ("target_distribution", "feature_importance")
_MAX_CHART_DATA_POINTS = 64

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
    order, or None when the artifact is not a valid, canonical,
    analytical-visualizations.v1 document."""
    if not isinstance(visualizations, dict):
        return None
    if visualizations.get("schema_version") != _ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION:
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

    projection = _safe_projection({"charts": canonical_charts})
    if not isinstance(projection, dict):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )
    return projection
