"""
Public dataset visibility resolution for M36-05.

Provides the single entry point the public HTTP routes use to determine
whether a dataset_slug's published profile snapshot may currently be
exposed publicly: resolve_dataset_visibility composes
registry/dataset_public_profile_snapshot_store.py's get_snapshot with
registry/dataset_public_profile_publication_store.py's get_visibility.

A dataset with no published snapshot yet (SnapshotNotFoundError) is always
treated as visible: "no snapshot exists yet" is a distinct case from "a
snapshot exists but Visible Publicly is off", and the existing generated
fallback profile behavior for a dataset with no snapshot is unaffected by
this issue.

This module is deliberately separate from api/public_profile_loader.py,
whose load_dataset_profile composes the PRIVATE draft store
(registry/dataset_public_profile_store.py) with the generated fallback for
an unrelated concern (authored draft preview composition); reusing or
redirecting that function here would have broken its own existing
authored_draft/generated_fallback contract (see
tests/api/test_public_profile_fallback.py). This module never imports or
calls registry/dataset_public_profile_store.py.

This module never persists anything; it only reads.
"""

from pathlib import Path

from registry.dataset_public_profile_publication_store import get_visibility
from registry.dataset_public_profile_snapshot_store import (
    SnapshotNotFoundError,
    get_snapshot,
)
from registry.dataset_public_profile_validate import normalize_binary_result_presentation


def resolve_dataset_visibility(dataset_slug: str, repo_root: Path | None = None) -> bool:
    """
    Return whether dataset_slug is currently publicly visible.

    Returns True when no published snapshot exists yet for dataset_slug
    (SnapshotNotFoundError), regardless of any publication record --
    absence of a snapshot is not the same as being hidden. Otherwise
    returns the publication record's visible value (defaulting to True
    when no publication record exists yet).

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern, propagated from get_snapshot/get_visibility.
    """
    try:
        get_snapshot(dataset_slug, repo_root=repo_root)
    except SnapshotNotFoundError:
        return True

    return get_visibility(dataset_slug, repo_root=repo_root)


def resolve_public_presentation_overlay(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Return the published snapshot's curated presentation fields for
    dataset_slug (display_title, display_subtitle, home_card_icon,
    short_description, theme_preset, source_name, source_url,
    release_date_label, date_format, primary_metric_key, bound_predict_view_id,
    legacy_submit_button_label), each None when no snapshot has been
    published yet. Used to overlay curated fields on top of a public route's
    existing default field source (e.g. the release-context projection);
    never raises for a missing snapshot or invalid slug, since both are
    normal "nothing curated yet" states for this read-only overlay.

    Project Spec S0110: bound_predict_view_id and legacy_submit_button_label
    are minimum transitional fields DatasetPage.tsx needs to resolve its
    bound predict view's customization and fall back to the legacy,
    deprecated result_card.submit_button_label when no customization value
    exists yet. bound_predict_view_id comes only from the published
    inference_presentation binding; legacy_submit_button_label comes only
    from the published result_card -- neither is treated as new authority,
    and no private draft is exposed by this read-only overlay.
    """
    defaults = {
        "display_title": None,
        "display_subtitle": None,
        "home_card_icon": None,
        "short_description": None,
        "home_card_media_ref": None,
        "theme_preset": None,
        "source_name": None,
        "source_url": None,
        "release_date_label": None,
        "date_format": None,
        "primary_metric_key": None,
        "performance_focus": None,
        "bound_predict_view_id": None,
        "legacy_submit_button_label": None,
        "result_card": normalize_binary_result_presentation(None),
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
    performance_focus = profile.get("performance_focus")
    inference_presentation = profile.get("inference_presentation")
    result_card = profile.get("result_card")

    return {
        "display_title": display.get("title") if isinstance(display, dict) else None,
        "display_subtitle": display.get("subtitle") if isinstance(display, dict) else None,
        "home_card_icon": home_card.get("icon") if isinstance(home_card, dict) else None,
        "short_description": home_card.get("short_description") if isinstance(home_card, dict) else None,
        "home_card_media_ref": home_card.get("background_image_ref") if isinstance(home_card, dict) else None,
        "theme_preset": theme.get("preset") if isinstance(theme, dict) else None,
        "source_name": display.get("source_name") if isinstance(display, dict) else None,
        "source_url": display.get("source_url") if isinstance(display, dict) else None,
        "release_date_label": display.get("release_date_label") if isinstance(display, dict) else None,
        "date_format": display.get("date_format") if isinstance(display, dict) else None,
        "primary_metric_key": home_card.get("primary_metric_key") if isinstance(home_card, dict) else None,
        "performance_focus": performance_focus if isinstance(performance_focus, dict) else None,
        "bound_predict_view_id": (
            inference_presentation.get("bound_predict_view_id")
            if isinstance(inference_presentation, dict)
            else None
        ),
        "legacy_submit_button_label": (
            result_card.get("submit_button_label") if isinstance(result_card, dict) else None
        ),
        "result_card": normalize_binary_result_presentation(result_card),
    }
