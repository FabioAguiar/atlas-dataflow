"""
Public metrics loader for M7-02.

Loads model performance metrics from the active release package and returns
a safe projection for public consumption. Internal field names, artifact
paths, and model internals are filtered before API exposure.
"""

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_METRICS_ROLE = "metrics"

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


def load_public_metrics(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the public metrics projection from the active release package.

    The manifest must declare a metrics artifact. The artifact path is
    release-package-relative and is path-checked before reading. A final
    defensive projection removes known internal keys before API exposure.
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
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )

    projection = _safe_projection(metrics)
    if not isinstance(projection, dict):
        raise PublicMetricsUnavailableError(
            "Metrics are not available for this release."
        )
    return projection
