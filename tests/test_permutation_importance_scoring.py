"""Permutation Feature Importance is scored by the execution contract's own
primary metric (resolved through the canonical metric identity registry),
never by a fixed per-problem-type scorer."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import metric_identity, training  # noqa: E402
from pipeline.training import TrainingInputError  # noqa: E402


@pytest.mark.parametrize(
    ("problem_type", "primary_metric", "expected_scorer"),
    [
        ("binary_classification", "roc_auc", "roc_auc"),
        ("binary_classification", "pr_auc", "average_precision"),
        ("binary_classification", "f1", "f1"),
        ("multiclass_classification", "f1_macro", "f1_macro"),
        ("multiclass_classification", "balanced_accuracy", "balanced_accuracy"),
        ("multiclass_classification", "recall_macro", "recall_macro"),
        ("continuous_regression", "mae", "neg_mean_absolute_error"),
        ("continuous_regression", "rmse", "neg_root_mean_squared_error"),
        ("continuous_regression", "r2", "r2"),
    ],
)
def test_scorer_derives_from_contract_primary_metric(problem_type, primary_metric, expected_scorer):
    metric, scorer = training._permutation_importance_scoring({"primary_metric": primary_metric}, problem_type)
    assert (metric, scorer) == (primary_metric, expected_scorer)


@pytest.mark.parametrize(
    ("problem_type", "primary_metric"),
    [
        ("multiclass_classification", "roc_auc"),  # binary-only metric
        ("continuous_regression", "f1_macro"),  # classification metric
        ("binary_classification", "f2"),  # no built-in scikit-learn scorer
    ],
)
def test_inapplicable_primary_metric_fails_closed(problem_type, primary_metric):
    with pytest.raises(TrainingInputError) as exc:
        training._permutation_importance_scoring({"primary_metric": primary_metric}, problem_type)
    assert exc.value.code == "unsupported_permutation_importance_metric"


def test_no_fixed_permutation_scorer_constants_remain():
    for name in (
        "NATIVE_MULTICLASS_PERMUTATION_IMPORTANCE_SCORING",
        "NATIVE_CONTINUOUS_REGRESSION_HGB_PERMUTATION_IMPORTANCE_SCORING",
        "NATIVE_BINARY_FIXED_HGB_PERMUTATION_IMPORTANCE_SCORING",
    ):
        assert not hasattr(training, name)


def test_positive_class_bound_scorers_cover_every_sensitive_metric():
    for identity in metric_identity.metric_identities().values():
        if identity.positive_class_sensitive and identity.sklearn_scorer is not None:
            assert identity.sklearn_scorer in training._POSITIVE_CLASS_BOUND_SCORER_FUNCTIONS


def test_label_agnostic_metric_keeps_plain_scorer_name():
    assert training._positive_class_bound_scorer("roc_auc", "roc_auc", "Yes") == "roc_auc"
    assert training._positive_class_bound_scorer("accuracy", "accuracy", "Yes") == "accuracy"


def test_schema_scorer_enums_match_registry_scorers():
    record_schema = json.loads((REPO_ROOT / "pipeline" / "training-parameter-record.schema.json").read_text())
    defs = record_schema["$defs"]
    for record_def, metric_def in (
        ("internal_run_record_v2", "multiclass_metric_name_v2"),
        ("internal_run_record_v3", "continuous_regression_metric_name_v3"),
        ("internal_run_record_v5", "binary_metric_name_v5"),
    ):
        scorer_enum = defs[record_def]["properties"]["training_parameters"]["properties"][
            "permutation_importance_scorer"
        ]["enum"]
        expected = {
            metric_identity.resolve_training_metric(name).sklearn_scorer
            for name in defs[metric_def]["enum"]
        }
        assert set(scorer_enum) == expected, record_def

    viz_schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    regression_scoring = viz_schema["$defs"]["regression_permutation_feature_importance_method_v3"]["properties"][
        "scoring"
    ]["enum"]
    assert set(regression_scoring) == set(
        defs["internal_run_record_v3"]["properties"]["training_parameters"]["properties"][
            "permutation_importance_scorer"
        ]["enum"]
    )
    binary_scoring = viz_schema["$defs"]["native_binary_fixed_v5"]["properties"]["feature_importance_method"][
        "properties"
    ]["scoring"]["enum"]
    assert set(binary_scoring) == set(
        defs["internal_run_record_v5"]["properties"]["training_parameters"]["properties"][
            "permutation_importance_scorer"
        ]["enum"]
    )
