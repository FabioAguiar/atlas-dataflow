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

from public_metrics_loader import (
    PublicMetricsUnavailableError,
    load_public_metrics,
)
from public_model_card_loader import (
    PublicModelCardUnavailableError,
    load_public_model_card,
)

_REPO_ROOT = Path(__file__).parent.parent

# Fixed, explicit preference order for home_card.primary_metric_key, applied
# identically across all datasets -- never dict iteration order. f1_score is
# preferred first because the currently seeded datasets are all
# binary_classification problems where a single balanced precision/recall
# measure is the most defensible default headline metric; auc_roc next as
# the most common threshold-independent ranking measure; accuracy,
# precision, recall follow as progressively less complete single-number
# summaries.
_METRIC_PREFERENCE_ORDER = ["f1_score", "auc_roc", "accuracy", "precision", "recall"]

# Mirrors web/src/lib/datasetPresentation.ts's getDatasetIcon keyword rule
# exactly, so the backend fallback and the frontend's own existing
# deterministic fallback never diverge for the same field.
_DOMAIN_ICON_RULES = [
    ("telecom", ["telecom", "telco"]),
    ("bank", ["bank", "financ"]),
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


def _select_primary_metric_key(metrics: dict) -> str | None:
    evaluation = metrics.get("evaluation") if isinstance(metrics, dict) else None
    available = evaluation.get("metrics") if isinstance(evaluation, dict) else None
    if not isinstance(available, dict):
        return None
    for key in _METRIC_PREFERENCE_ORDER:
        if key in available:
            return key
    return None


def _model_label_from_model_card(model_card_payload: dict) -> str | None:
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
    if not isinstance(parsed, dict):
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

    if metrics is not None:
        primary_metric_key = _select_primary_metric_key(metrics)
        if primary_metric_key is not None:
            home_card["primary_metric_key"] = primary_metric_key

    result_card = {}
    try:
        model_card_payload = load_public_model_card(active_release, releases_root=releases_root)
    except PublicModelCardUnavailableError:
        model_card_payload = None
    else:
        sources_used["model_card"] = True

    if model_card_payload is not None:
        model_label = _model_label_from_model_card(model_card_payload)
        if model_label is not None:
            result_card["model_label"] = model_label

    profile: dict = {
        "schema_version": "1.0.0",
        "dataset_slug": dataset_slug,
    }
    if home_card:
        profile["home_card"] = home_card
    if result_card:
        profile["result_card"] = result_card

    validation = validate_profile_draft(profile, repo_root=repo_root)
    if not validation["valid"]:
        raise RuntimeError(
            f"generate_fallback_profile produced an invalid profile for "
            f"dataset_slug={dataset_slug!r}: {validation['errors']!r}"
        )

    return {"profile": profile, "sources_used": sources_used}
