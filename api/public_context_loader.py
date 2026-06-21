"""
Public context loader for M16-04.

Loads the public dataset context from the active release package and returns
a safe projection for public consumption. The runtime loader reads only the
release artifact referenced by the manifest role public_context.
"""

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_PUBLIC_CONTEXT_ROLE = "public_context"

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


class PublicContextUnavailableError(Exception):
    """The public context projection is absent from or unreadable in the active release package."""

    code = "PUBLIC_CONTEXT_UNAVAILABLE"


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


def load_public_context(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the public context projection from the active release package.

    The manifest must declare a public_context artifact. The artifact path is
    release-package-relative and is path-checked before reading. A final
    defensive projection removes known internal keys before API exposure.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicContextUnavailableError(
            "Context is not available for this release."
        )

    context_ref = _artifact_reference(manifest, _PUBLIC_CONTEXT_ROLE)
    if context_ref is None:
        raise PublicContextUnavailableError(
            "Context is not available for this release."
        )

    context_path = (release_dir / context_ref).resolve()
    if not context_path.is_relative_to(release_dir.resolve()):
        raise PublicContextUnavailableError(
            "Context is not available for this release."
        )

    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicContextUnavailableError(
            "Context is not available for this release."
        )

    projection = _safe_projection(context)
    if not isinstance(projection, dict):
        raise PublicContextUnavailableError(
            "Context is not available for this release."
        )
    return projection
