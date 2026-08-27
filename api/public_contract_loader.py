"""
Public contract loader for M6-05.

Loads the public contract from a distinct active-release manifest artifact.
This module intentionally does not use the runtime contract loader: the public
contract is an interface projection, not the validation source.
"""

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent

_PUBLIC_CONTRACT_ROLE = "public_contract"
_RUNTIME_CONTRACT_ROLE = "contracts"
_RUNTIME_ONLY_KEYS = {
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


class PublicContractUnavailableError(Exception):
    """The public contract projection is absent from the active release package."""

    code = "PUBLIC_CONTRACT_UNAVAILABLE"


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


def _extract_public_contract_reference(manifest: dict) -> str:
    public_ref = _artifact_reference(manifest, _PUBLIC_CONTRACT_ROLE)
    runtime_ref = _artifact_reference(manifest, _RUNTIME_CONTRACT_ROLE)
    if public_ref is None:
        raise PublicContractUnavailableError(
            "Public contract is not available for this release."
        )
    if runtime_ref is not None and public_ref == runtime_ref:
        raise PublicContractUnavailableError(
            "Public contract must be distinct from the runtime contract."
        )
    return public_ref


def _safe_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_projection(nested)
            for key, nested in value.items()
            if key not in _RUNTIME_ONLY_KEYS
        }
    if isinstance(value, list):
        return [_safe_projection(item) for item in value]
    return value


def load_public_contract(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the public contract projection from the active release package.

    The manifest must declare a public_contract artifact that is distinct from
    the runtime contracts artifact. The path is release-package-relative and is
    checked before reading. A final defensive projection removes known
    runtime-only validation and artifact metadata keys before API exposure.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicContractUnavailableError(
            "Public contract is not available for this release."
        )

    public_ref = _extract_public_contract_reference(manifest)

    contract_path = (release_dir / public_ref).resolve()
    if not contract_path.is_relative_to(release_dir.resolve()):
        raise PublicContractUnavailableError(
            "Public contract is not available for this release."
        )

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublicContractUnavailableError(
            "Public contract is not available for this release."
        )

    projection = _safe_projection(contract)
    if not isinstance(projection, dict):
        raise PublicContractUnavailableError(
            "Public contract is not available for this release."
        )
    return projection


def public_prediction_surface_available(public_contract: dict) -> bool:
    """
    Project Spec S0271: interpret an already-loaded, schema-valid public
    contract to decide whether public prediction surfaces (the Dataset Detail
    Inference tab, public Predict View routes, and the public inference POST)
    are available for the active release.

    This consumes only the S0269 release-bound public applicability
    projection. It never inspects problem type, model family/name, dataset
    slug, Predict View registry/profile state, ``required_anchor``,
    ``frequency``, or ``history_target_values.affect_forecast``.

    Compatibility rule (identical to the frontend helper):

      * ``predictive_interaction`` absent (scalar or historical forecasting
        v2 contract) -> ``True``
      * ``predictive_interaction.public_prediction.applicability`` is
        ``"available"`` -> ``True``
      * ``applicability`` is ``"not_applicable"`` -> ``False``

    A present-but-malformed ``predictive_interaction`` shape fails closed
    (``False``) rather than silently resolving to available.
    """
    if not isinstance(public_contract, dict):
        return False

    projection = public_contract.get("predictive_interaction")
    if projection is None:
        return True
    if not isinstance(projection, dict):
        return False

    public_prediction = projection.get("public_prediction")
    if not isinstance(public_prediction, dict):
        return False

    applicability = public_prediction.get("applicability")
    if applicability == "available":
        return True
    if applicability == "not_applicable":
        return False
    return False
