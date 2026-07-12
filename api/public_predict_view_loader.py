"""
Predict view runtime loader for M18-03.

Loads and resolves a predict view record from the authoritative registry
(registry/predict-views.json) for a given dataset slug and view identifier.
Returns a safe public projection excluding internal binding details,
contract_precedence, schema_version, and registry metadata.
"""

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_PREDICT_VIEWS_PATH = _REPO_ROOT / "registry" / "predict-views.json"
_DEFAULT_DATASETS_PATH = _REPO_ROOT / "registry" / "datasets.json"


class ViewNotFoundError(Exception):
    """No predict view record matching the given view_id and dataset_slug exists."""

    code = "VIEW_NOT_FOUND"


class ViewBindingInvalidError(Exception):
    """A predict view record was found but its binding is internally inconsistent."""

    code = "VIEW_BINDING_INVALID"


def _dataset_is_registered(dataset_slug: str, datasets_path: Path | None) -> bool:
    if datasets_path is None:
        return True
    try:
        registry = json.loads(datasets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    datasets = registry.get("datasets") if isinstance(registry, dict) else None
    return isinstance(datasets, list) and any(
        isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug
        for entry in datasets
    )


def _datasets_path_for(predict_views_path: Path, datasets_path: Path | None) -> Path | None:
    if datasets_path is not None:
        return datasets_path
    sibling = predict_views_path.parent / "datasets.json"
    return sibling if sibling.is_file() else None


def load_public_predict_view(
    dataset_slug: str,
    view_id: str,
    predict_views_path: Path | None = None,
    datasets_path: Path | None = None,
) -> dict:
    """
    Load a safe public projection of a predict view record.

    Resolution steps:
    1. Read registry/predict-views.json.
    2. Find the record where top-level view_id and top-level dataset_slug both
       match the requested values.
    3. Validate that binding.dataset_slug, if present, is consistent with the
       record's top-level dataset_slug.
    4. Return a projection containing only: view_id, dataset_slug, display,
       intent, and release_mode (derived from binding.release.mode).

    Raises ViewNotFoundError if no matching record exists or if the registry
    is unavailable.
    Raises ViewBindingInvalidError if a binding inconsistency is detected.
    """
    path = predict_views_path if predict_views_path is not None else _DEFAULT_PREDICT_VIEWS_PATH
    datasets_path = _datasets_path_for(path, datasets_path or (_DEFAULT_DATASETS_PATH if predict_views_path is None else None))

    if not _dataset_is_registered(dataset_slug, datasets_path):
        raise ViewNotFoundError("The requested predict view is not available for this dataset.")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise ViewNotFoundError("Predict view registry is not available.")

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        raise ViewNotFoundError("Predict view registry is not available.")

    predict_views = registry.get("predict_views")
    if not isinstance(predict_views, list):
        raise ViewNotFoundError("Predict view registry is not available.")

    matched = None
    for record in predict_views:
        if not isinstance(record, dict):
            continue
        if record.get("view_id") == view_id and record.get("dataset_slug") == dataset_slug:
            matched = record
            break

    if matched is None:
        raise ViewNotFoundError(
            "The requested predict view is not available for this dataset."
        )

    binding = matched.get("binding")
    if isinstance(binding, dict):
        binding_slug = binding.get("dataset_slug")
        if binding_slug is not None and binding_slug != dataset_slug:
            raise ViewBindingInvalidError(
                "The predict view binding is not valid for this dataset."
            )

    release_mode = None
    if isinstance(binding, dict):
        release = binding.get("release")
        if isinstance(release, dict):
            release_mode = release.get("mode")

    display = matched.get("display")
    intent = matched.get("intent")

    return {
        "view_id": view_id,
        "dataset_slug": dataset_slug,
        "display": display if isinstance(display, dict) else {},
        "intent": intent if isinstance(intent, dict) else {},
        "release_mode": release_mode,
    }


def load_public_predict_view_list(
    dataset_slug: str,
    predict_views_path: Path | None = None,
    datasets_path: Path | None = None,
) -> list[dict]:
    """
    Return safe public projections for all valid predict views bound to dataset_slug.

    Reads registry/predict-views.json, filters to records whose top-level
    dataset_slug matches the requested slug, silently excludes records with
    a binding.dataset_slug inconsistency, and returns the list. An empty list
    is a valid result when no views exist for the dataset.

    Raises ViewNotFoundError if the registry is unreadable or malformed.
    """
    path = predict_views_path if predict_views_path is not None else _DEFAULT_PREDICT_VIEWS_PATH
    datasets_path = _datasets_path_for(path, datasets_path or (_DEFAULT_DATASETS_PATH if predict_views_path is None else None))

    if not _dataset_is_registered(dataset_slug, datasets_path):
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise ViewNotFoundError("Predict view registry is not available.")

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        raise ViewNotFoundError("Predict view registry is not available.")

    predict_views = registry.get("predict_views")
    if not isinstance(predict_views, list):
        raise ViewNotFoundError("Predict view registry is not available.")

    results = []
    for record in predict_views:
        if not isinstance(record, dict):
            continue
        if record.get("dataset_slug") != dataset_slug:
            continue

        binding = record.get("binding")
        if isinstance(binding, dict):
            binding_slug = binding.get("dataset_slug")
            if binding_slug is not None and binding_slug != dataset_slug:
                continue

        release_mode = None
        if isinstance(binding, dict):
            release = binding.get("release")
            if isinstance(release, dict):
                release_mode = release.get("mode")

        display = record.get("display")
        intent = record.get("intent")

        safe_display: dict = {}
        if isinstance(display, dict):
            if "title" in display:
                safe_display["title"] = display["title"]
            if "summary" in display:
                safe_display["summary"] = display["summary"]

        safe_intent: dict = {}
        if isinstance(intent, dict):
            if "prediction_goal" in intent:
                safe_intent["prediction_goal"] = intent["prediction_goal"]
            if "audience" in intent:
                safe_intent["audience"] = intent["audience"]
            if "usage_notes" in intent:
                safe_intent["usage_notes"] = intent["usage_notes"]

        results.append({
            "view_id": record.get("view_id"),
            "dataset_slug": dataset_slug,
            "display": safe_display,
            "intent": safe_intent,
            "release_mode": release_mode,
        })

    return results
