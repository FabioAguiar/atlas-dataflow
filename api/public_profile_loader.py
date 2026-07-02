"""
Profile-loading integration function for M34-05.

Provides the single entry point a future caller uses to obtain a dataset's
public profile regardless of whether an authored draft exists yet:
load_dataset_profile attempts registry/dataset_public_profile_store.py's
get_draft first, and falls back to public_profile_fallback.py's
generate_fallback_profile only when get_draft raises
ProfileDraftNotFoundError.

The returned envelope always carries an explicit profile_source marker
("authored_draft" or "generated_fallback") distinguishing curated admin
content from generated content, kept outside the profile object itself
since contracts/dataset-public-profile.schema.json is additionalProperties:
false and cannot carry a new marker field. This module adds no HTTP route;
it is internal, directly-callable composition logic only.

This module never persists anything: it never calls create_draft or
update_draft.
"""

from pathlib import Path

from registry.dataset_public_profile_store import ProfileDraftNotFoundError, get_draft

from public_profile_fallback import generate_fallback_profile


def load_dataset_profile(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Return {"dataset_slug": str, "profile_source": "authored_draft"|"generated_fallback",
    "profile": dict, "sources_used": dict|None}.

    profile_source is "authored_draft" and sources_used is None when a valid
    draft exists. profile_source is "generated_fallback" and sources_used is
    the per-loader availability dict from generate_fallback_profile when no
    valid draft exists.

    Raises ValueError if dataset_slug is missing or does not match the
    required pattern (propagated from get_draft). Raises whatever
    generate_fallback_profile raises when dataset/release resolution itself
    fails while assembling the fallback.
    """
    try:
        profile = get_draft(dataset_slug, repo_root=repo_root)
    except ProfileDraftNotFoundError:
        fallback = generate_fallback_profile(dataset_slug, repo_root=repo_root)
        return {
            "dataset_slug": dataset_slug,
            "profile_source": "generated_fallback",
            "profile": fallback["profile"],
            "sources_used": fallback["sources_used"],
        }

    return {
        "dataset_slug": dataset_slug,
        "profile_source": "authored_draft",
        "profile": profile,
        "sources_used": None,
    }
