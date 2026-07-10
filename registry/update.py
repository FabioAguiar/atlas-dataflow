"""
Controlled registry update after release promotion.

Accepts a promotion result path or publisher run directory, gates on
promotion_outcome == "promoted", verifies the promoted release manifest exists,
updates the matching dataset active_release in registry/datasets.json, validates
the updated in-memory registry, backs up the previous registry, and writes the
updated registry.

If no dataset entry exists yet for the promoted dataset_slug (Project Spec
S0036), a new safe public entry is created from the promoted release's
public-context.json rather than raising -- this is what makes a first-time
promotion resolvable at GET /datasets/{slug} without a manual registry edit.

Does NOT modify promotion-result.json.
Does NOT produce a separate promotion-update document.
Does NOT expose any HTTP endpoint. run() and main() are internal CLI only.
"""

import json
import re
import shutil
import sys
from pathlib import Path

from registry.validate import RELEASE_ID_PATTERN, validate_registry


DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _load_json_file(path: Path, label: str) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"{label} could not be read.") from exc

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object.")

    return data


def _resolve_run_dir(result_path_or_run_dir: str) -> Path:
    input_path = Path(result_path_or_run_dir)
    if input_path.is_file():
        return input_path.parent
    if input_path.is_dir():
        return input_path
    raise ValueError(f"Input path does not exist: {result_path_or_run_dir}")


def _extract_candidate_identity(promotion_result: dict) -> tuple[str, str]:
    candidate_identity = promotion_result.get("candidate_identity")
    if not isinstance(candidate_identity, dict):
        raise RuntimeError("Promotion result is missing 'candidate_identity'.")

    dataset_slug = candidate_identity.get("dataset_slug")
    release_id = candidate_identity.get("release_id")

    if not isinstance(dataset_slug, str) or not DATASET_SLUG_PATTERN.match(dataset_slug):
        raise RuntimeError(
            "Promotion result candidate_identity.dataset_slug is missing or invalid."
        )
    if not isinstance(release_id, str) or not RELEASE_ID_PATTERN.match(release_id):
        raise RuntimeError(
            "Promotion result candidate_identity.release_id is missing or invalid."
        )

    return dataset_slug, release_id


def _safe_metadata_string(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _safe_metadata_tags(value: object) -> list:
    if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
        return value
    return []


def _fallback_title(dataset_slug: str) -> str:
    return " ".join(part.capitalize() for part in dataset_slug.split("-") if part)


def _derive_public_metadata(dataset_slug: str, release_dir: Path) -> dict:
    """Derive a schema-safe public_metadata object for a first-time dataset_slug.

    Reads only the already-promoted, immutable
    releases/{release_id}/public-context.json (never the mutable candidate
    directory) so the derived metadata matches what was actually promoted.
    Any missing/unreadable/malformed field falls back to a safe generic
    value instead of raising -- a new registry entry must never block a
    promotion that otherwise satisfied every precondition.
    """
    context = _read_optional_json_object(release_dir / "public-context.json")
    fallback_title = _fallback_title(dataset_slug)

    return {
        "title": _safe_metadata_string(context.get("title"), fallback_title),
        "summary": _safe_metadata_string(
            context.get("description"), f"Published dataset: {fallback_title}."
        ),
        "domain": _safe_metadata_string(context.get("domain"), "general"),
        "visibility": "public",
        "tags": _safe_metadata_tags(context.get("tags")),
    }


def _read_optional_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_or_create_dataset_entry(
    registry: dict, dataset_slug: str, release_dir: Path
) -> tuple[dict, bool]:
    """Return (entry, created) for dataset_slug, creating a safe new entry if absent."""
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise RuntimeError("Registry is missing required list field 'datasets'.")

    for entry in datasets:
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            return entry, False

    new_entry = {
        "dataset_slug": dataset_slug,
        "active_release": None,
        "public_metadata": _derive_public_metadata(dataset_slug, release_dir),
    }
    datasets.append(new_entry)
    return new_entry, True


def run(result_path_or_run_dir: str, repo_root: Path | None = None) -> dict:
    """
    Apply the controlled registry active_release update.

    Accepts either a path to promotion-result.json or the containing run
    directory. Returns an informational dict and writes no artifact other than
    registry/datasets.json.previous and registry/datasets.json.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    else:
        repo_root = Path(repo_root)

    run_dir = _resolve_run_dir(result_path_or_run_dir)
    promotion_result = _load_json_file(run_dir / "promotion-result.json", "promotion result")

    if promotion_result.get("promotion_outcome") != "promoted":
        raise RuntimeError("Registry update halted: promotion_outcome is not 'promoted'.")

    dataset_slug, release_id = _extract_candidate_identity(promotion_result)

    release_dir = repo_root / "releases" / release_id
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"Registry update halted: releases/{release_id}/manifest.json is absent."
        )

    registry_path = repo_root / "registry" / "datasets.json"
    backup_path = repo_root / "registry" / "datasets.json.previous"

    registry = _load_json_file(registry_path, "registry")
    entry, created = _find_or_create_dataset_entry(registry, dataset_slug, release_dir)
    previous_active_release_id = entry.get("active_release")
    entry["active_release"] = release_id

    validation = validate_registry(registry)
    if validation.get("valid") is not True:
        errors = validation.get("errors") or []
        first_error = errors[0] if errors else {}
        message = first_error.get("message") or "Updated registry is not valid."
        raise RuntimeError(message)

    shutil.copy2(registry_path, backup_path)
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    previous_display = previous_active_release_id if previous_active_release_id else "none"
    print(f"previous_active_release: {previous_display}")
    print(f"new_active_release: {release_id}")
    print(f"dataset_slug: {dataset_slug}")

    return {
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "previous_active_release_id": previous_active_release_id,
        "update_applied": True,
        "backup_path": str(backup_path),
        "dataset_entry_created": created,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m registry.update <promotion-result-path-or-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        run(sys.argv[1])
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
