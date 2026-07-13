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

Project Spec S0052 adds an Admin-only publication/review state projection,
distinct from the "Visible Publicly" toggle
(registry/dataset_public_profile_publication_store.py) above: a registry
entry's own `review_status` field ("needs_review" or "ready", set on
registry/datasets.json entries -- never inside public_metadata, which
registry/validate.py's UNSAFE_METADATA_FIELDS check rejects extra keys on)
tracks whether a Dataset Detail has ever been curated/published, independent
of whether its published snapshot is currently hidden/shown. An entry with
no review_status (every dataset seeded before this issue, e.g.
telco-customer-churn) defaults to "ready", preserving existing public
listing behavior exactly; only a brand-new entry created by
registry/update.py's promotion-driven entry creation defaults to
"needs_review". is_dataset_needs_review() is the gate api/main.py's public
routes use so a draft Dataset Detail is never publicly reachable even though
it has no published snapshot yet (the pre-existing default-visible-when-no-
snapshot behavior in api/public_profile_visibility.py is unchanged and
composes with this new, separate gate). list_admin_datasets() is the
Admin-only counterpart to list_datasets() above: it returns every
registry-backed Dataset Detail regardless of public visibility or review
state, with a normalized publication_status projection instead of the raw
review_status value.
"""

import json
import re
from pathlib import Path
from typing import NamedTuple

from registry.validate import validate_registry_file
from registry.resolve import RegistryInvalidError
from registry.dataset_public_profile_snapshot_store import (
    SnapshotNotFoundError,
    get_snapshot,
)

REGISTRY_PATH = Path(__file__).parent / "datasets.json"

REVIEW_STATUS_READY = "ready"
REVIEW_STATUS_NEEDS_REVIEW = "needs_review"
_VALID_REVIEW_STATUSES = {REVIEW_STATUS_READY, REVIEW_STATUS_NEEDS_REVIEW}
_PUBLIC_HOME_CARD_MEDIA_REF = re.compile(
    r"^/media/home-cards/[A-Za-z0-9_-]+\.(?:avif|gif|jpeg|jpg|png|webp)$"
)


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
    home_card_media_ref: str | None = None
    short_description: str | None = None
    theme_preset: str | None = None


class AdminListedDataset(NamedTuple):
    dataset_slug: str
    title: str
    display_title: str | None
    summary: str
    domain: str
    tags: list
    active_release: str | None
    publication_status: str
    dataset_detail_updated_at: str | None


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
        "home_card_media_ref": None,
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
        "home_card_media_ref": _safe_home_card_media_ref(
            home_card.get("background_image_ref") if isinstance(home_card, dict) else None
        ),
        "short_description": home_card.get("short_description") if isinstance(home_card, dict) else None,
        "theme_preset": theme.get("preset") if isinstance(theme, dict) else None,
    }


def _safe_home_card_media_ref(value: object) -> str | None:
    """Return only bounded, same-origin Home card image references."""
    if not isinstance(value, str) or not value:
        return None
    return value if _PUBLIC_HOME_CARD_MEDIA_REF.fullmatch(value) else None


def list_datasets(registry_path: Path | None = None) -> list[ListedDataset]:
    """
    Return a list of safe-field-only dataset records from the validated registry.

    Invokes the M3-02 validator before reading registry content.
    Raises RegistryInvalidError if validation fails or the registry is unreadable.

    Each returned ListedDataset contains the safe public fields
    (dataset_slug, title, summary, domain, visibility, tags) plus the
    published profile snapshot's curated overlay fields (display_title,
    display_subtitle, home_card_icon, home_card_media_ref, short_description,
    theme_preset),
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
            home_card_media_ref=overlay["home_card_media_ref"],
            short_description=overlay["short_description"],
            theme_preset=overlay["theme_preset"],
        ))
    return result


def _entry_review_status(entry: dict) -> str:
    value = entry.get("review_status")
    return value if value in _VALID_REVIEW_STATUSES else REVIEW_STATUS_READY


def _safe_display_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def is_dataset_needs_review(dataset_slug: str, registry_path: Path | None = None) -> bool:
    """
    Return True when dataset_slug's registry entry is in the needs_review
    (draft) publication state.

    Returns False (not needs_review) when the registry is unreadable/invalid
    JSON or dataset_slug has no matching entry -- absence-based not-found
    handling stays the caller's responsibility, mirroring
    resolve_dataset_visibility's own default-open failure mode for a
    genuinely unrelated concern.
    """
    path = registry_path if registry_path is not None else REGISTRY_PATH

    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(registry, dict):
        return False

    for entry in registry.get("datasets", []):
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            return _entry_review_status(entry) == REVIEW_STATUS_NEEDS_REVIEW

    return False


def list_admin_datasets(registry_path: Path | None = None) -> list[AdminListedDataset]:
    """
    Return every registry-backed Dataset Detail for Admin, regardless of
    public "Visible Publicly" state or review/publication status.

    Invokes the M3-02 validator before reading registry content, exactly
    like list_datasets(). Raises RegistryInvalidError if validation fails or
    the registry is unreadable.

    The Admin projection uses the same current display-title precedence as
    Dataset Admin and Dashboard: latest published profile snapshot title
    first, then the registry public metadata title when no snapshot title is
    available. It never filters by public visibility -- both draft
    ("needs_review") and published ("ready") Dataset Details are always
    included, so Admin operators can review, edit slug, remove, and later
    publish a draft.
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
        active_release = entry.get("active_release")
        dataset_slug = entry.get("dataset_slug", "")
        registry_title = _safe_display_title(metadata.get("title"))
        overlay = _snapshot_overlay_fields(dataset_slug, repo_root)
        result.append(AdminListedDataset(
            dataset_slug=dataset_slug,
            title=metadata.get("title", ""),
            display_title=_safe_display_title(overlay["display_title"]) or registry_title,
            summary=metadata.get("summary", ""),
            domain=metadata.get("domain", ""),
            tags=metadata.get("tags", []),
            active_release=active_release if isinstance(active_release, str) else None,
            publication_status=_entry_review_status(entry),
            dataset_detail_updated_at=(
                entry.get("dataset_detail_updated_at")
                if isinstance(entry.get("dataset_detail_updated_at"), str)
                else None
            ),
        ))
    return result
