"""
Registry resolver for M3-03.

Provides deterministic dataset slug and active release resolution
against the validated file-based registry.

Resolution is read-only and does not execute inference, load model bundles,
scan directories, use file timestamps, or infer state from local paths.
"""

import json
from pathlib import Path
from typing import NamedTuple

from registry.validate import RELEASE_ID_PATTERN, validate_registry_file

REGISTRY_PATH = Path(__file__).parent / "datasets.json"


class ResolvedDataset(NamedTuple):
    dataset_slug: str
    active_release: str


class DatasetUnavailableError(Exception):
    """No registry entry matches the requested dataset_slug."""

    code = "DATASET_UNAVAILABLE"


class ReleaseUnavailableError(Exception):
    """The matched registry entry has no valid active_release field."""

    code = "RELEASE_UNAVAILABLE"


class RegistryInvalidError(Exception):
    """The registry did not pass M3-02 validation or could not be read."""

    code = "REGISTRY_INVALID"


def _resolve_from_entries(dataset_slug: str, entries: list) -> ResolvedDataset:
    """
    Locate dataset_slug in registry entries and return the resolved dataset.

    Uses exact string matching only — no pattern inference, normalization,
    or partial matching.

    Raises DatasetUnavailableError if no entry matches the slug exactly.
    Raises ReleaseUnavailableError if the matched entry has no valid active_release.
    """
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("dataset_slug") == dataset_slug:
            active_release = entry.get("active_release")
            if not isinstance(active_release, str) or not RELEASE_ID_PATTERN.match(active_release):
                raise ReleaseUnavailableError(
                    "The active release for this dataset is not available."
                )
            return ResolvedDataset(dataset_slug=dataset_slug, active_release=active_release)
    raise DatasetUnavailableError("The requested dataset is not available.")


def resolve_dataset(dataset_slug: str, registry_path: Path | None = None) -> ResolvedDataset:
    """
    Resolve a dataset by exact dataset_slug from the validated registry.

    Invokes the M3-02 validator before reading registry content.
    If validation fails the resolver does not proceed.

    Returns a ResolvedDataset with the declared dataset_slug and active_release.

    Raises RegistryInvalidError if validation fails or the file is unreadable.
    Raises DatasetUnavailableError if no entry matches the requested slug.
    Raises ReleaseUnavailableError if the matched entry has no valid active_release.
    """
    path = registry_path if registry_path is not None else REGISTRY_PATH

    validation = validate_registry_file(path)
    if not validation["valid"]:
        raise RegistryInvalidError("Registry did not pass validation.")

    try:
        content = path.read_text(encoding="utf-8")
        registry = json.loads(content)
    except (OSError, json.JSONDecodeError):
        raise RegistryInvalidError("Registry could not be read.")

    return _resolve_from_entries(dataset_slug, registry.get("datasets", []))
