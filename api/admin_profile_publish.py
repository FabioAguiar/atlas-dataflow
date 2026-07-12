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

from registry.dataset_public_profile_snapshot_store import (
    publish_snapshot,
    publish_snapshot_from_payload,
)

HOME_CARD_IMAGE_MAX_BYTES = 5 * 1024 * 1024
_SAFE_UPLOAD_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IMAGE_TYPES = {
    "image/png": ("png",),
    "image/jpeg": ("jpg", "jpeg"),
    "image/webp": ("webp",),
    "image/avif": ("avif",),
}


def _media_root(repo_root: Path) -> Path:
    configured = os.environ.get("ATLAS_MEDIA_ROOT")
    return Path(configured) if configured else repo_root / "media"


def _matches_image_signature(content_type: str, content: bytes) -> bool:
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if content_type == "image/avif":
        return len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in {b"avif", b"avis"}
    return False


def store_home_card_image(
    filename: str | None,
    content_type: str | None,
    content: bytes,
    repo_root: Path | None = None,
) -> dict:
    """Validate and store one Home-card image, returning only its public reference."""
    if not isinstance(filename, str) or not _SAFE_UPLOAD_FILENAME.fullmatch(filename):
        return {"uploaded": False, "media_ref": None, "error": "Choose an image with a safe filename."}
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    extensions = _IMAGE_TYPES.get(normalized_type)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not extensions or extension not in extensions:
        return {"uploaded": False, "media_ref": None, "error": "Choose a PNG, JPEG, WebP, or AVIF image."}
    if len(content) > HOME_CARD_IMAGE_MAX_BYTES:
        return {"uploaded": False, "media_ref": None, "error": "Choose an image smaller than 5 MB."}
    if not content or not _matches_image_signature(normalized_type, content):
        return {"uploaded": False, "media_ref": None, "error": "The selected file is not a valid supported image."}

    root = _media_root(Path(repo_root) if repo_root else Path(__file__).parent.parent)
    destination_root = root / "home-cards"
    stored_name = f"{uuid.uuid4().hex}.{extensions[0]}"
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
