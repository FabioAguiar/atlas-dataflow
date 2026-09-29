"""Canonical metric identity authority (contracts/metric-identity-registry.json).

The pipeline reader (pipeline/metric_identity.py) and the API/registry reader
(registry/metric_identity.py) must agree with the one registry, and every
per-layer vocabulary that used to be a hand-maintained table must now be
derived from it (or proven consistent with it).
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api"))

from pipeline import contract_derivation, metric_identity, scientific_reproduction, training  # noqa: E402
from pipeline import scientific_study_contract  # noqa: E402
from registry import metric_identity as registry_metric_identity  # noqa: E402
from registry.dataset_public_profile_validate import release_published_metric_keys  # noqa: E402

import public_metrics_loader  # noqa: E402


REGISTRY = json.loads((REPO_ROOT / "contracts" / "metric-identity-registry.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("training_name", "scientific_name", "public_key", "canonical_id"),
    [
        ("roc_auc", "roc_auc", "roc_auc", "roc_auc"),
        ("pr_auc", "average_precision", "pr_auc", "pr_auc"),
        ("f1", "f1", "f1_score", "f1"),
        ("f1_macro", "macro_f1", "f1_macro", "f1_macro"),
        ("f1_weighted", "weighted_f1", "f1_weighted", "f1_weighted"),
        ("recall_macro", "macro_recall", "recall_macro", "recall_macro"),
        ("mae", None, "mae", "mae"),
        ("rmse", None, "rmse", "rmse"),
        ("r2", None, "r2", "r2"),
    ],
)
def test_canonical_identity_resolves_every_layer_alias(training_name, scientific_name, public_key, canonical_id):
    identity = metric_identity.resolve_training_metric(training_name)
    assert identity.metric_id == canonical_id
    assert identity.public_key == public_key
    assert registry_metric_identity.public_metric_key(training_name) == public_key
    assert registry_metric_identity.public_metric_key(public_key) == public_key
    if scientific_name is not None:
        assert metric_identity.resolve_scientific_metric(scientific_name).metric_id == canonical_id


def test_average_precision_is_the_same_identity_as_pr_auc_everywhere():
    assert metric_identity.resolve_training_metric("average_precision").metric_id == "pr_auc"
    assert metric_identity.resolve_scientific_metric("average_precision").metric_id == "pr_auc"
    assert registry_metric_identity.public_metric_key("average_precision") == "pr_auc"


@pytest.mark.parametrize(
    ("metric", "direction"),
    [("roc_auc", "higher_is_better"), ("f1_macro", "higher_is_better"), ("r2", "higher_is_better"),
     ("mae", "lower_is_better"), ("rmse", "lower_is_better"), ("log_loss", "lower_is_better")],
)
def test_direction(metric, direction):
    assert metric_identity.resolve_training_metric(metric).direction == direction


def test_unknown_metric_fails_closed():
    with pytest.raises(metric_identity.MetricIdentityError):
        metric_identity.resolve_training_metric("not_a_metric")
    assert registry_metric_identity.public_metric_key("not_a_metric") is None


def test_every_declared_sklearn_scorer_exists():
    from sklearn.metrics import get_scorer_names

    valid = set(get_scorer_names())
    for entry in REGISTRY["metrics"]:
        if entry["sklearn_scorer"] is not None:
            assert entry["sklearn_scorer"] in valid, entry["metric_id"]


def test_public_alias_table_is_derived_and_unchanged():
    # The S0127/S0215/S0227/S0247 public alias table, now derived from the
    # registry, keeps exactly its previously published behavior.
    expected = {
        "roc_auc": "roc_auc", "auc_roc": "roc_auc", "auc": "roc_auc",
        "f1": "f1_score", "f1_score": "f1_score",
        "pr_auc": "pr_auc", "average_precision": "pr_auc",
        "precision": "precision", "recall": "recall", "accuracy": "accuracy", "log_loss": "log_loss",
        "balanced_accuracy": "balanced_accuracy", "f1_macro": "f1_macro", "f1_weighted": "f1_weighted",
        "precision_macro": "precision_macro", "recall_macro": "recall_macro",
        "r2": "r2", "mae": "mae", "rmse": "rmse", "seasonal_mase": "seasonal_mase",
    }
    assert public_metrics_loader._METRIC_ALIASES == expected
    assert registry_metric_identity.public_metric_aliases() == expected


def test_scientific_aliases_never_leak_into_public_projection():
    for scientific_only in ("macro_f1", "weighted_f1", "macro_recall", "minimum_per_class_recall"):
        assert registry_metric_identity.public_metric_key(scientific_only) is None


def test_training_policy_metric_vocabulary_is_derived_and_unchanged():
    assert contract_derivation._TRAINING_POLICY_METRIC_VOCABULARY == frozenset({
        "roc_auc", "f1", "accuracy", "log_loss", "pr_auc", "average_precision",
        "precision", "recall", "f2", "balanced_accuracy", "brier_score",
        "f1_macro", "f1_weighted", "precision_macro", "recall_macro",
        "r2", "mae", "rmse",
    })
    assert contract_derivation._CONTINUOUS_REGRESSION_METRIC_VOCABULARY == frozenset({"r2", "mae", "rmse"})
    # Trainer capability subsets must stay within the canonical identities.
    assert contract_derivation._BINARY_CLASSIFICATION_METRIC_VOCABULARY <= metric_identity.training_metric_vocabulary(
        {"binary_classification"}
    )
    assert set(training.NATIVE_MULTICLASS_METRIC_NAMES) <= metric_identity.training_metric_vocabulary(
        {"multiclass_classification"}
    )


def test_native_to_scientific_aliases_are_derived_and_unchanged():
    assert scientific_reproduction.NATIVE_METRIC_ALIASES == {
        "pr_auc": "average_precision",
        "f1_macro": "macro_f1",
        "f1_weighted": "weighted_f1",
        "recall_macro": "macro_recall",
    }


def test_scientific_metric_vocabulary_matches_registry():
    for problem_type, vocabulary in scientific_study_contract.METRICS_BY_PROBLEM_TYPE.items():
        registry_vocabulary = {
            alias
            for entry in REGISTRY["metrics"]
            if problem_type in entry["problem_types"]
            for alias in entry["aliases"]["scientific"]
        }
        assert set(vocabulary) == registry_vocabulary, problem_type


def test_training_lower_is_better_set_comes_from_registry():
    assert training._LOWER_IS_BETTER_METRICS == metric_identity.lower_is_better_training_metrics()
    assert {"log_loss", "mae", "rmse"} <= training._LOWER_IS_BETTER_METRICS
    assert not ({"roc_auc", "f1", "f1_macro", "r2", "accuracy"} & training._LOWER_IS_BETTER_METRICS)


def _registered_active_releases() -> list[tuple[str, str]]:
    registry = json.loads((REPO_ROOT / "registry" / "datasets.json").read_text(encoding="utf-8"))
    return [(entry["dataset_slug"], entry["active_release"]) for entry in registry["datasets"]]


@pytest.mark.parametrize(("dataset_slug", "release_id"), _registered_active_releases())
def test_profile_reference_key_space_matches_public_projection(dataset_slug, release_id):
    raw = json.loads((REPO_ROOT / "releases" / release_id / "metrics" / "metrics.json").read_text(encoding="utf-8"))
    projected = public_metrics_loader.load_public_metrics(release_id, releases_root=REPO_ROOT / "releases")
    projected_keys = set(projected["evaluation"]["metrics"])
    assert projected_keys
    assert projected_keys <= release_published_metric_keys(raw)
