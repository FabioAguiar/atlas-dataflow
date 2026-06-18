"""
Public model card loader for M7-02.

Loads the model card document from the active release package and returns
it as a JSON-wrapped markdown payload for public consumption.
"""

import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_MODEL_CARD_ROLE = "model_card"


class PublicModelCardUnavailableError(Exception):
    """The model card document is absent from or unreadable in the active release package."""

    code = "PUBLIC_MODEL_CARD_UNAVAILABLE"


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


def load_public_model_card(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the model card from the active release package.

    Returns {"content": "<raw_markdown_string>", "format": "markdown"}.
    The artifact path is release-package-relative and is path-checked before reading.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicModelCardUnavailableError(
            "The model card is not available for this release."
        )

    model_card_ref = _artifact_reference(manifest, _MODEL_CARD_ROLE)
    if model_card_ref is None:
        raise PublicModelCardUnavailableError(
            "The model card is not available for this release."
        )

    model_card_path = (release_dir / model_card_ref).resolve()
    if not model_card_path.is_relative_to(release_dir.resolve()):
        raise PublicModelCardUnavailableError(
            "The model card is not available for this release."
        )

    try:
        content = model_card_path.read_text(encoding="utf-8")
    except OSError:
        raise PublicModelCardUnavailableError(
            "The model card is not available for this release."
        )

    return {"content": content, "format": "markdown"}
