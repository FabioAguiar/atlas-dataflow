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

import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import unquote

from registry.dataset_public_profile_snapshot_store import (
    SnapshotNotFoundError,
    get_snapshot,
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
_HOME_CARD_MEDIA_REF_PATTERN = re.compile(
    r"^/media/home-cards/([0-9a-f]{32}\.(?:avif|jpg|png|webp))$"
)
_DATASET_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DOCUMENTATION_MEDIA_FILENAME_PATTERN = re.compile(r"[0-9a-f]{32}\.(?:avif|jpg|png|webp)")


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


def store_documentation_image(
    dataset_slug: str,
    original_filename: str | None,
    content_type: str | None,
    content: bytes,
    repo_root: Path | None = None,
) -> dict:
    """Validate and store one dataset's Documentation image, returning only its public reference.

    Reuses the same signature/MIME policy and 10 MB bound as Home-card
    images (S0197); the original filename is validation/display input only
    and is never used as the durable stored filename.
    """
    if not re.fullmatch(_DATASET_SLUG_PATTERN, dataset_slug or ""):
        return {"uploaded": False, "media_ref": None, "error": "The dataset_slug is missing or invalid."}
    if not _is_file_name(original_filename):
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
    destination_root = root / "documentation" / dataset_slug
    stored_name = f"{uuid.uuid4().hex}.{_IMAGE_EXTENSIONS[detected_type]}"
    destination = destination_root / stored_name
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    except OSError:
        return {"uploaded": False, "media_ref": None, "error": "The image could not be stored. Try again."}
    return {
        "uploaded": True,
        "media_ref": f"/media/documentation/{dataset_slug}/{stored_name}",
        "error": None,
    }


def resolve_documentation_media_path(
    dataset_slug: str, filename: str, repo_root: Path | None = None
) -> Path | None:
    """Resolve only generated Documentation filenames inside one dataset's media directory."""
    if not re.fullmatch(_DATASET_SLUG_PATTERN, dataset_slug or ""):
        return None
    if not re.fullmatch(_DOCUMENTATION_MEDIA_FILENAME_PATTERN, filename or ""):
        return None
    dataset_root = (
        _media_root(Path(repo_root) if repo_root else Path(__file__).parent.parent)
        / "documentation"
        / dataset_slug
    ).resolve()
    candidate = (dataset_root / filename).resolve()
    try:
        candidate.relative_to(dataset_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _profile_artifact_paths(dataset_slug: str, repo_root: Path) -> tuple[Path, ...]:
    """Return the complete, bounded set of mutable profile artifacts for a slug."""
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_slug):
        raise ValueError("dataset_slug is missing or invalid.")
    registry_root = repo_root / "registry"
    return (
        registry_root / "profile-drafts" / f"{dataset_slug}.json",
        registry_root / "profile-drafts" / f"{dataset_slug}.json.previous",
        registry_root / "profile-snapshots" / f"{dataset_slug}.json",
        registry_root / "profile-snapshots" / f"{dataset_slug}.json.previous",
        registry_root / "profile-snapshots" / f"{dataset_slug}.evidence.json",
        registry_root / "profile-publications" / f"{dataset_slug}.json",
    )


def _media_references_in_json(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()

    references: set[str] = set()

    def visit(candidate: object) -> None:
        if isinstance(candidate, dict):
            for item in candidate.values():
                visit(item)
        elif isinstance(candidate, list):
            for item in candidate:
                visit(item)
        elif isinstance(candidate, str):
            match = _HOME_CARD_MEDIA_REF_PATTERN.fullmatch(candidate)
            if match:
                references.add(match.group(1))

    visit(value)
    return references


def _live_dataset_slugs(repo_root: Path) -> list[str]:
    try:
        registry = json.loads(
            (repo_root / "registry" / "datasets.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    datasets = registry.get("datasets") if isinstance(registry, dict) else None
    if not isinstance(datasets, list):
        return []
    return [
        entry["dataset_slug"]
        for entry in datasets
        if isinstance(entry, dict)
        and isinstance(entry.get("dataset_slug"), str)
        and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry["dataset_slug"])
    ]


def remove_profile_artifacts(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """Remove one deleted Dataset Detail's mutable profile lifecycle safely.

    The registry entry must already have been removed by the caller. Missing
    artifacts are successful no-ops. Only generated Home-card media owned by
    the removed artifacts and unreferenced by every live Dataset Detail is
    eligible for deletion; run and release trees are never inspected. The
    deleted dataset's whole generated Documentation media directory (S0197)
    is also removed -- unlike Home-card media, Documentation images are
    never shared across datasets, so no cross-dataset reference scan applies.
    """
    root = Path(repo_root) if repo_root else Path(__file__).parent.parent
    try:
        artifact_paths = _profile_artifact_paths(dataset_slug, root)
    except ValueError:
        return {
            "completed": False,
            "artifacts_removed": 0,
            "media_removed": 0,
            "errors": [{
                "code": "PROFILE_CLEANUP_SLUG_INVALID",
                "field": "dataset_slug",
                "message": "The Dataset Detail profile cleanup identifier is invalid.",
            }],
        }

    owned_media: set[str] = set()
    for path in artifact_paths[:4]:
        owned_media.update(_media_references_in_json(path))

    live_media: set[str] = set()
    for live_slug in _live_dataset_slugs(root):
        live_paths = _profile_artifact_paths(live_slug, root)
        for path in live_paths[:4]:
            live_media.update(_media_references_in_json(path))

    artifacts_removed = 0
    media_removed = 0
    try:
        for path in artifact_paths:
            try:
                path.unlink()
                artifacts_removed += 1
            except FileNotFoundError:
                pass

        media_root = (_media_root(root) / "home-cards").resolve()
        for filename in sorted(owned_media - live_media):
            candidate = (media_root / filename).resolve()
            try:
                candidate.relative_to(media_root)
            except ValueError:
                continue
            try:
                candidate.unlink()
                media_removed += 1
            except FileNotFoundError:
                pass

        documentation_root = (_media_root(root) / "documentation").resolve()
        dataset_documentation_dir = documentation_root / dataset_slug
        if dataset_documentation_dir.is_dir() and not dataset_documentation_dir.is_symlink():
            resolved_dataset_dir = dataset_documentation_dir.resolve()
            try:
                resolved_dataset_dir.relative_to(documentation_root)
            except ValueError:
                resolved_dataset_dir = None
            if resolved_dataset_dir is not None:
                for entry in sorted(dataset_documentation_dir.iterdir()):
                    if entry.is_symlink() or not entry.is_file():
                        continue
                    if not re.fullmatch(_DOCUMENTATION_MEDIA_FILENAME_PATTERN, entry.name):
                        continue
                    try:
                        entry.unlink()
                        media_removed += 1
                    except FileNotFoundError:
                        pass
                try:
                    dataset_documentation_dir.rmdir()
                except OSError:
                    pass
    except OSError:
        return {
            "completed": False,
            "artifacts_removed": artifacts_removed,
            "media_removed": media_removed,
            "errors": [{
                "code": "PROFILE_CLEANUP_FAILED",
                "field": None,
                "message": "Associated public profile artifacts could not be fully removed.",
            }],
        }

    return {
        "completed": True,
        "artifacts_removed": artifacts_removed,
        "media_removed": media_removed,
        "errors": [],
    }


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
    # Dataset Admin sends the browser's IANA timezone as transient mutation
    # context. It is removed before schema validation/persistence, so it can
    # never become another profile field or date authority.
    candidate = dict(profile)
    time_zone = candidate.pop("dataset_detail_time_zone", None)
    result = publish_snapshot_from_payload(
        dataset_slug,
        candidate,
        time_zone=time_zone if isinstance(time_zone, str) else None,
    )

    return {
        "dataset_slug": dataset_slug,
        "display_title": _display_title_from_snapshot(result["snapshot"]),
        "published": result["published"],
        "snapshot": result["snapshot"],
        "errors": result["errors"],
    }


def read_published_profile_snapshot(dataset_slug: str) -> dict | None:
    """Return the latest published snapshot, or None when none exists."""
    try:
        return get_snapshot(dataset_slug)
    except SnapshotNotFoundError:
        return None
