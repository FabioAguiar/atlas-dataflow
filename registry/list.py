"""
Registry listing for M3-04.

Provides safe public dataset listing from the validated file-based registry.
Returns only the declared safe public metadata fields — no raw registry entry
dicts, no active_release, no conventions, no $schema, no internal fields.

Listing is read-only and does not execute inference, load model bundles,
access a database, or produce side effects.
"""

import json
from pathlib import Path
from typing import NamedTuple

from registry.validate import validate_registry_file
from registry.resolve import RegistryInvalidError

REGISTRY_PATH = Path(__file__).parent / "datasets.json"


class ListedDataset(NamedTuple):
    dataset_slug: str
    title: str
    summary: str
    domain: str
    visibility: str
    tags: list


def list_datasets(registry_path: Path | None = None) -> list[ListedDataset]:
    """
    Return a list of safe-field-only dataset records from the validated registry.

    Invokes the M3-02 validator before reading registry content.
    Raises RegistryInvalidError if validation fails or the registry is unreadable.

    Each returned ListedDataset contains only the safe public fields:
    dataset_slug, title, summary, domain, visibility, tags.
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

    result = []
    for entry in registry.get("datasets", []):
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("public_metadata", {})
        result.append(ListedDataset(
            dataset_slug=entry.get("dataset_slug", ""),
            title=metadata.get("title", ""),
            summary=metadata.get("summary", ""),
            domain=metadata.get("domain", ""),
            visibility=metadata.get("visibility", ""),
            tags=metadata.get("tags", []),
        ))
    return result
