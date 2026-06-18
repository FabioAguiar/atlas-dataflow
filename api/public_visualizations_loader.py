"""
Public visualizations loader for M7-03.

Loads pre-computed chart data from the active release package and returns
a safe projection for public consumption. Internal field names, artifact
paths, and publisher-internal keys are filtered before API exposure.
"""

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_VISUALIZATIONS_ROLE = "visualizations"

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

    projection = _safe_projection(visualizations)
    if not isinstance(projection, dict):
        raise PublicVisualizationsUnavailableError(
            "Visualizations are not available for this release."
        )
    return projection
