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

# S0284: the reduced technical prediction-target read only accepts a
# governed model-card.v1 document identifying itself as a model card and
# declaring one of the current capability problem types. Coarse legacy
# aliases (classification/regression/forecasting) are intentionally absent
# so they fail closed rather than being mapped to a specific capability.
_MODEL_CARD_SCHEMA_VERSION = "model-card.v1"
_MODEL_CARD_ARTIFACT_KIND = "model_card"
_SUPPORTED_PREDICTION_TARGET_PROBLEM_TYPES = frozenset(
    {
        "binary_classification",
        "multiclass_classification",
        "continuous_regression",
        "univariate_forecasting",
    }
)
# Small explicit public presentation bound, consistent with the descriptive
# copy limits in contracts/dataset-public-profile.schema.json. The reduced
# reader rejects rather than truncates an over-long technical target name.
_MAX_PREDICTION_TARGET_NAME_LENGTH = 160


class PublicModelCardUnavailableError(Exception):
    """The model card document is absent from or unreadable in the active release package."""

    code = "PUBLIC_MODEL_CARD_UNAVAILABLE"


class PublicPredictionTargetUnavailableError(Exception):
    """The reduced release-bound prediction-target identity cannot be projected."""

    code = "PUBLIC_PREDICTION_TARGET_UNAVAILABLE"


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


def _identifies_as_model_card(document: dict) -> bool:
    """
    A governed model-card.v1 document identifies itself either through
    ``artifact_kind`` (classification/continuous-regression cards) or, for
    the univariate-forecasting card shape, through ``role``. When
    ``artifact_kind`` is present it must be exactly ``model_card``.
    """
    artifact_kind = document.get("artifact_kind")
    if artifact_kind is not None:
        return artifact_kind == _MODEL_CARD_ARTIFACT_KIND
    return document.get("role") == _MODEL_CARD_ARTIFACT_KIND


def load_public_prediction_target(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Reduced release-bound prediction-target projection.

    Resolves the ``model_card`` role through the active release manifest,
    applies the same release-directory path-traversal protection
    ``load_public_model_card`` uses, parses the document as JSON for this
    reduced technical read, and returns only::

        {"problem_type": <supported problem type>, "target_name": <bounded nonblank name>}

    No other model-card field (hashes, path references, model/evaluation/
    provenance, evidence policy, ...) is read or returned. Malformed,
    non-JSON, historically incompatible, or unsupported model cards raise
    ``PublicPredictionTargetUnavailableError`` and never affect the raw
    ``load_public_model_card`` response.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    model_card_ref = _artifact_reference(manifest, _MODEL_CARD_ROLE)
    if model_card_ref is None:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    model_card_path = (release_dir / model_card_ref).resolve()
    if not model_card_path.is_relative_to(release_dir.resolve()):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    try:
        raw = model_card_path.read_text(encoding="utf-8")
    except OSError:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    if not isinstance(document, dict):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    if document.get("schema_version") != _MODEL_CARD_SCHEMA_VERSION:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    if not _identifies_as_model_card(document):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    problem_type = document.get("problem_type")
    if (
        not isinstance(problem_type, str)
        or problem_type not in _SUPPORTED_PREDICTION_TARGET_PROBLEM_TYPES
    ):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    target_name = document.get("prediction_target")
    if not isinstance(target_name, str):
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )
    if len(target_name) > _MAX_PREDICTION_TARGET_NAME_LENGTH:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )
    trimmed_target_name = target_name.strip()
    if not trimmed_target_name:
        raise PublicPredictionTargetUnavailableError(
            "The prediction target is not available for this release."
        )

    return {"problem_type": problem_type, "target_name": trimmed_target_name}
