"""
Registry listing for M3-04.

Provides safe public dataset listing from the validated file-based registry.
Returns only the declared safe public metadata fields — no raw registry entry
dicts, no active_release, no conventions, no $schema, no internal fields.

Listing is read-only and does not execute inference, load model bundles,
access a database, or produce side effects.

For M39-04, each listing is additionally overlaid with the dataset's
published profile snapshot (registry/dataset_public_profile_snapshot_store.py),
when one exists, so publish/visibility actions taken in Dataset Admin are
reflected in the public listing. A dataset with no published snapshot yet
gets None for every overlay field, preserving the pre-existing raw
public_metadata-only behavior exactly.
"""

import json
from pathlib import Path
from typing import NamedTuple

from registry.validate import validate_registry_file
from registry.resolve import RegistryInvalidError
from registry.dataset_public_profile_snapshot_store import (
    SnapshotNotFoundError,
    get_snapshot,
)

REGISTRY_PATH = Path(__file__).parent / "datasets.json"


class ListedDataset(NamedTuple):
    dataset_slug: str
    title: str
    summary: str
    domain: str
    visibility: str
    tags: list
    display_title: str | None = None
    display_subtitle: str | None = None
    home_card_icon: str | None = None
    short_description: str | None = None
    theme_preset: str | None = None


def _snapshot_overlay_fields(dataset_slug: str, repo_root: Path) -> dict:
    """
    Return the published snapshot's curated presentation fields for
    dataset_slug, or all-None defaults when no snapshot has been published
    yet. Never raises: absence of a snapshot is a normal, expected state
    (the dataset simply has no curated overrides yet), not an error.
    """
    defaults = {
        "display_title": None,
        "display_subtitle": None,
        "home_card_icon": None,
        "short_description": None,
        "theme_preset": None,
    }

    try:
        snapshot = get_snapshot(dataset_slug, repo_root=repo_root)
    except (SnapshotNotFoundError, ValueError):
        return defaults

    profile = snapshot.get("profile") if isinstance(snapshot, dict) else None
    if not isinstance(profile, dict):
        return defaults

    display = profile.get("display")
    home_card = profile.get("home_card")
    theme = profile.get("theme")

    return {
        "display_title": display.get("title") if isinstance(display, dict) else None,
        "display_subtitle": display.get("subtitle") if isinstance(display, dict) else None,
        "home_card_icon": home_card.get("icon") if isinstance(home_card, dict) else None,
        "short_description": home_card.get("short_description") if isinstance(home_card, dict) else None,
        "theme_preset": theme.get("preset") if isinstance(theme, dict) else None,
    }


def list_datasets(registry_path: Path | None = None) -> list[ListedDataset]:
    """
    Return a list of safe-field-only dataset records from the validated registry.

    Invokes the M3-02 validator before reading registry content.
    Raises RegistryInvalidError if validation fails or the registry is unreadable.

    Each returned ListedDataset contains the safe public fields
    (dataset_slug, title, summary, domain, visibility, tags) plus the
    published profile snapshot's curated overlay fields (display_title,
    display_subtitle, home_card_icon, short_description, theme_preset),
    all None when no snapshot has been published for that dataset yet.
    """
    path = registry_path if registry_path is not None else REGISTRY_PATH
    repo_root = path.parent.parent

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
        dataset_slug = entry.get("dataset_slug", "")
        overlay = _snapshot_overlay_fields(dataset_slug, repo_root)
        result.append(ListedDataset(
            dataset_slug=dataset_slug,
            title=metadata.get("title", ""),
            summary=metadata.get("summary", ""),
            domain=metadata.get("domain", ""),
            visibility=metadata.get("visibility", ""),
            tags=metadata.get("tags", []),
            display_title=overlay["display_title"],
            display_subtitle=overlay["display_subtitle"],
            home_card_icon=overlay["home_card_icon"],
            short_description=overlay["short_description"],
            theme_preset=overlay["theme_preset"],
        ))
    return result
