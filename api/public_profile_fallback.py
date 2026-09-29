"""
Deterministic fallback profile generator for M34-05.

Generates a dataset public profile (contracts/dataset-public-profile.schema.json)
for a dataset that has no authored draft, composing only registry/resolve.py's
active-release resolver together with the two existing public loaders whose
output actually maps onto a profile schema field: public_metrics_loader (for
home_card.primary_metric_key) and public_model_card_loader (for
result_card.model_label). public_contract_loader and public_visualizations_loader
are not composed here: no field in contracts/dataset-public-profile.schema.json
is derived from contract or visualization data, and neither currently seeded
release even declares a visualizations manifest artifact.

Every derivation is deterministic: identical registry/release state and the
same dataset_slug always produce identical output. A missing or invalid
optional artifact (metrics, model card) results in the corresponding profile
field being omitted entirely -- this module never raises for an unavailable
optional artifact and never invents a placeholder value. Dataset/release
resolution failure (registry/resolve.py's own exceptions) is not treated as
an optional-artifact omission and is left to propagate, since there is no
dataset to generate a fallback profile for in that case.

inference_presentation.bound_predict_view_id is never set by this module --
auto-binding a predict view remains an authored-draft decision made through
the admin surface (M34-04).

This module never persists anything: it has no filesystem write path and
never imports or calls registry/dataset_public_profile_store.py's
create_draft or update_draft. The generated profile is always run through
validate_profile_draft (the same schema-and-reference validation authored
drafts must pass) before being returned.
"""

import json
from pathlib import Path

from registry.dataset_public_profile_store import validate_profile_draft
from registry.resolve import resolve_dataset

from registry.metric_identity import public_metric_key
from public_metrics_loader import (
    PublicMetricsUnavailableError,
    load_public_metrics,
)
from public_model_card_loader import (
    PublicModelCardUnavailableError,
    load_public_model_card,
)

_REPO_ROOT = Path(__file__).parent.parent

# home_card.primary_metric_key is never chosen from a fixed preference list:
# it is the active release's own primary metric -- the execution contract's
# primary_metric, which training records into the release model card
# (evaluation.primary_metric_name) and, for forecasting, into the metrics
# artifact's evaluation_policy (surfaced by public_metrics_loader as
# primary_metric_id) -- mapped to its published key through the canonical
# metric identity registry (registry/metric_identity.py).

# Kept in lockstep with web/src/lib/datasetPresentation.ts's getDatasetIcon
# keyword rule, so the backend fallback and the frontend's own existing
# deterministic fallback never diverge for the same field. This list is not
# exhaustive of Atlas's full curated icon bank (see
# contracts/dataset-public-profile.schema.json's home_card.icon enum) -- it
# only covers domains this module can confidently infer automatically from
# registry/datasets.json's public_metadata.domain/tags. A domain matching
# none of these keyword families deterministically falls back to "generic",
# which is itself a normal, renderable icon value, not a rejection -- this
# fallback never requires telecom or bank to exist in the registry to
# produce a valid, schema-conformant result for any dataset domain. An
# authoring curator may still hand-select any other icon from the full
# bank for a given dataset via web/src/pages/admin/DatasetAdminPage.tsx.
_DOMAIN_ICON_RULES = [
    ("telecom", ["telecom", "telco"]),
    ("bank", ["bank", "financ"]),
    ("heart", ["health", "medical", "clinic", "hospital"]),
    ("shopping-cart", ["retail", "commerce", "shop"]),
    ("education-cap", ["education", "school", "university"]),
    ("energy-bolt", ["energy", "utility", "power"]),
    ("logistics-truck", ["logistics", "shipping", "freight"]),
    ("shield", ["insurance", "security"]),
]


def _resolve_repo_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return _REPO_ROOT
    return Path(repo_root)


def _derive_icon(domain: str | None, tags: list) -> str:
    haystack = " ".join([domain or "", *[str(tag) for tag in tags]]).lower()
    for icon, keywords in _DOMAIN_ICON_RULES:
        if any(keyword in haystack for keyword in keywords):
            return icon
    return "generic"


def _dataset_public_metadata(dataset_slug: str, repo_root: Path) -> dict:
    registry_path = repo_root / "registry" / "datasets.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(registry, dict):
        return {}
    for entry in registry.get("datasets", []):
        if isinstance(entry, dict) and entry.get("dataset_slug") == dataset_slug:
            metadata = entry.get("public_metadata")
            return metadata if isinstance(metadata, dict) else {}
    return {}


def _model_card_content(model_card_payload: dict | None) -> dict | None:
    content = (
        model_card_payload.get("content")
        if isinstance(model_card_payload, dict)
        else None
    )
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _release_primary_metric_name(metrics: dict, model_card: dict | None) -> str | None:
    """The release's execution-contract primary metric, as recorded by the
    release's own artifacts (never inferred from which metrics exist)."""
    primary_metric_id = metrics.get("primary_metric_id") if isinstance(metrics, dict) else None
    if isinstance(primary_metric_id, str) and primary_metric_id:
        return primary_metric_id
    evaluation = model_card.get("evaluation") if isinstance(model_card, dict) else None
    primary_metric_name = (
        evaluation.get("primary_metric_name") if isinstance(evaluation, dict) else None
    )
    if isinstance(primary_metric_name, str) and primary_metric_name:
        return primary_metric_name
    return None


def _select_primary_metric_key(metrics: dict, model_card: dict | None = None) -> str | None:
    """Select home_card.primary_metric_key.

    1. The release's contract primary metric, mapped to its public key via
       the canonical metric identity registry, when the release publishes it.
    2. Only when that primary metric is genuinely unavailable (not recorded,
       unknown, or not among the published metrics): the first published
       metric in the release's own metric order -- a generic, dataset- and
       problem-type-neutral fallback.
    """
    evaluation = metrics.get("evaluation") if isinstance(metrics, dict) else None
    available = evaluation.get("metrics") if isinstance(evaluation, dict) else None
    if not isinstance(available, dict) or not available:
        return None

    primary_key = public_metric_key(_release_primary_metric_name(metrics, model_card))
    if primary_key is not None and primary_key in available:
        return primary_key

    metric_order = metrics.get("metric_order") if isinstance(metrics, dict) else None
    ordered = [key for key in metric_order if key in available] if isinstance(metric_order, list) else []
    if ordered:
        return ordered[0]
    return next(iter(available))


def _model_label_from_model_card(model_card_payload: dict) -> str | None:
    parsed = _model_card_content(model_card_payload)
    if parsed is None:
        return None

    problem_type = parsed.get("problem_type")
    prediction_target = parsed.get("prediction_target")
    if not isinstance(problem_type, str) or not problem_type:
        return None
    if not isinstance(prediction_target, str) or not prediction_target:
        return None

    return f"{problem_type.replace('_', ' ').title()}: {prediction_target}"


def generate_fallback_profile(dataset_slug: str, repo_root: Path | None = None) -> dict:
    """
    Generate a deterministic fallback profile for dataset_slug.

    Returns {"profile": dict, "sources_used": {"metrics": bool, "model_card": bool}}.
    profile always conforms to contracts/dataset-public-profile.schema.json and
    has already passed validate_profile_draft's schema-and-reference validation.
    sources_used records whether each composed loader succeeded, independent
    of whether its data actually produced a profile field.

    Raises whatever registry/resolve.py's resolve_dataset raises
    (RegistryInvalidError, DatasetUnavailableError, ReleaseUnavailableError)
    when the dataset itself cannot be resolved -- this is not a per-artifact
    omission case.

    Raises RuntimeError if the generated profile unexpectedly fails
    validate_profile_draft; this would indicate a bug in this generator's
    own deterministic derivation logic, not a normal missing-artifact case.
    """
    repo_root = _resolve_repo_root(repo_root)

    resolved = resolve_dataset(
        dataset_slug, registry_path=repo_root / "registry" / "datasets.json"
    )
    active_release = resolved.active_release
    releases_root = repo_root / "releases"

    sources_used = {"metrics": False, "model_card": False}

    public_metadata = _dataset_public_metadata(dataset_slug, repo_root)
    tags = public_metadata.get("tags")
    home_card = {
        "icon": _derive_icon(public_metadata.get("domain"), tags if isinstance(tags, list) else []),
    }

    try:
        metrics = load_public_metrics(active_release, releases_root=releases_root)
    except PublicMetricsUnavailableError:
        metrics = None
    else:
        sources_used["metrics"] = True

    try:
        model_card_payload = load_public_model_card(active_release, releases_root=releases_root)
    except PublicModelCardUnavailableError:
        model_card_payload = None
    else:
        sources_used["model_card"] = True

    if metrics is not None:
        primary_metric_key = _select_primary_metric_key(
            metrics, _model_card_content(model_card_payload)
        )
        if primary_metric_key is not None:
            home_card["primary_metric_key"] = primary_metric_key

    # Result Card fallback copy is deliberately dataset-neutral. Model-card
    # content is technical identity and must not become editable section copy.
    from registry.dataset_public_profile_validate import normalize_binary_result_presentation
    result_card = normalize_binary_result_presentation(None)

    profile: dict = {
        "schema_version": "1.0.0",
        "dataset_slug": dataset_slug,
    }
    if home_card:
        profile["home_card"] = home_card
    profile["result_card"] = result_card

    validation = validate_profile_draft(profile, repo_root=repo_root)
    if not validation["valid"]:
        raise RuntimeError(
            f"generate_fallback_profile produced an invalid profile for "
            f"dataset_slug={dataset_slug!r}: {validation['errors']!r}"
        )

    return {"profile": profile, "sources_used": sources_used}
