"""
Private/admin service module for dataset public profile publishing (M36-03).

Wraps registry/dataset_public_profile_snapshot_store.py's publish_snapshot
and publish_snapshot_from_payload (Project Spec S0061) for the private/admin
HTTP surface in api/main.py. This module has no public caller; the route
that uses it is gated by api/main.py's existing ADMIN_API_TOKEN convention,
mirroring api/admin_profile_drafts.py.

On failure (no draft to publish, no resolvable active_release, an invalid
payload, or a schema/reference validation error), no snapshot is created or
replaced; the persistence module's own {code, field, message} error list is
propagated unchanged to the calling route.
"""

import os
import re
import uuid
from pathlib import Path
from urllib.parse import unquote

from registry.dataset_public_profile_snapshot_store import (
    publish_snapshot,
    publish_snapshot_from_payload,
)

HOME_CARD_IMAGE_MAX_BYTES = 10 * 1024 * 1024
_GENERIC_IMAGE_TYPES = {"", "application/octet-stream"}
_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/avif": "avif",
}


def _media_root(repo_root: Path) -> Path:
    configured = os.environ.get("ATLAS_MEDIA_ROOT")
    return Path(configured) if configured else repo_root / "media"


def _image_type_from_signature(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    return None


def _is_file_name(filename: str | None) -> bool:
    """Reject empty/directory-like names without using the name for storage."""
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 512:
        return False
    decoded = unquote(filename)
    return not any(separator in decoded for separator in ("/", "\\", "\u2044", "\u2215", "\u29f8"))


def store_home_card_image(
    filename: str | None,
    content_type: str | None,
    content: bytes,
    repo_root: Path | None = None,
) -> dict:
    """Validate and store one Home-card image, returning only its public reference."""
    if not _is_file_name(filename):
        return {"uploaded": False, "media_ref": None, "error": "Choose an image file, not a folder."}
    if len(content) > HOME_CARD_IMAGE_MAX_BYTES:
        return {"uploaded": False, "media_ref": None, "error": "Choose an image smaller than 10 MB."}
    if not content:
        return {"uploaded": False, "media_ref": None, "error": "The selected image is empty or corrupt."}

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type not in _GENERIC_IMAGE_TYPES and normalized_type not in _IMAGE_EXTENSIONS:
        return {"uploaded": False, "media_ref": None, "error": "Choose a PNG, JPEG, WebP, or AVIF image."}
    detected_type = _image_type_from_signature(content)
    if detected_type is None or (normalized_type not in _GENERIC_IMAGE_TYPES and normalized_type != detected_type):
        return {"uploaded": False, "media_ref": None, "error": "The selected image is invalid or corrupt."}

    root = _media_root(Path(repo_root) if repo_root else Path(__file__).parent.parent)
    destination_root = root / "home-cards"
    stored_name = f"{uuid.uuid4().hex}.{_IMAGE_EXTENSIONS[detected_type]}"
    destination = destination_root / stored_name
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    except OSError:
        return {"uploaded": False, "media_ref": None, "error": "The image could not be stored. Try again."}
    return {"uploaded": True, "media_ref": f"/media/home-cards/{stored_name}", "error": None}


def resolve_home_card_media_path(filename: str, repo_root: Path | None = None) -> Path | None:
    """Resolve only generated Home-card filenames inside Atlas's media root."""
    if not re.fullmatch(r"[0-9a-f]{32}\.(?:avif|jpg|png|webp)", filename):
        return None
    root = (_media_root(Path(repo_root) if repo_root else Path(__file__).parent.parent) / "home-cards").resolve()
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _display_title_from_snapshot(snapshot: dict | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    profile = snapshot.get("profile")
    display = profile.get("display") if isinstance(profile, dict) else None
    title = display.get("title") if isinstance(display, dict) else None
    if not isinstance(title, str):
        return None
    normalized = title.strip()
    return normalized or None


def publish_profile(dataset_slug: str) -> dict:
    """
    Publish the current private draft profile as a published profile snapshot.

    Retained for backward compatibility; Dataset Admin's normal Publish
    Changes flow uses publish_profile_payload instead.

    Returns {"dataset_slug": str, "published": bool, "snapshot": dict|None,
    "errors": [...]}. Raises ValueError if dataset_slug is missing or does
    not match the required pattern.
    """
    result = publish_snapshot(dataset_slug)

    return {
        "dataset_slug": dataset_slug,
        "display_title": _display_title_from_snapshot(result["snapshot"]),
        "published": result["published"],
        "snapshot": result["snapshot"],
        "errors": result["errors"],
    }


def publish_profile_payload(dataset_slug: str, profile: dict) -> dict:
    """
    Publish an admin-submitted profile payload directly as a published
    profile snapshot, without reading or requiring a persisted draft.

    Returns {"dataset_slug": str, "published": bool, "snapshot": dict|None,
    "errors": [...]}. Raises ValueError if dataset_slug is missing or does
    not match the required pattern.
    """
    result = publish_snapshot_from_payload(dataset_slug, profile)

    return {
        "dataset_slug": dataset_slug,
        "display_title": _display_title_from_snapshot(result["snapshot"]),
        "published": result["published"],
        "snapshot": result["snapshot"],
        "errors": result["errors"],
    }
