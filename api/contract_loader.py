"""
Runtime contract loader for M6-02.

Loads the runtime contract from the active release package using
manifest-driven discovery: reads the release manifest to locate the
contracts artifact reference, then loads the contract from that
release-package-relative path.

Loading is read-only. No release artifact is modified.
"""

import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


class ContractUnavailableError(Exception):
    """The runtime contract is absent from the active release package."""

    code = "CONTRACT_UNAVAILABLE"


def _releases_root() -> Path:
    env_root = os.environ.get("RELEASES_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT / "releases"


def _extract_contracts_reference(manifest: dict) -> str:
    """Return the release-package-relative contracts artifact reference."""
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ContractUnavailableError("Runtime contract is not available for this release.")
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("role") == "contracts":
            reference = artifact.get("reference")
            if isinstance(reference, str) and reference:
                return reference
    raise ContractUnavailableError("Runtime contract is not available for this release.")


def load_contract(
    active_release: str,
    releases_root: Path | None = None,
) -> dict:
    """
    Load the runtime contract from the active release package.

    Resolves the release directory from active_release, reads the manifest to
    discover the contracts artifact reference, and loads the contract from the
    declared path. The contract path is confirmed to remain within the release
    directory before reading.

    Raises ContractUnavailableError when the runtime contract is absent
    from the release package for any reason.
    """
    root = releases_root if releases_root is not None else _releases_root()
    release_dir = root / active_release

    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ContractUnavailableError("Runtime contract is not available for this release.")

    contracts_ref = _extract_contracts_reference(manifest)

    contract_path = (release_dir / contracts_ref).resolve()
    if not contract_path.is_relative_to(release_dir.resolve()):
        raise ContractUnavailableError("Runtime contract is not available for this release.")

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ContractUnavailableError("Runtime contract is not available for this release.")

    return contract
