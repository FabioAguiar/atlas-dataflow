"""Dedicated Project Spec S0258 tests for the Atlas-native binary fixed-
configuration `analytical-visualizations.v5` profile.

Corrective supersession of the blocked Project Spec S0257 implementation
intent: `analytical-visualizations.v1`'s closed `feature_importance_method
.model_family` enum structurally excludes `hist_gradient_boosting` and
carries no truthful `method` discriminator, so a native binary fixed
`HistGradientBoostingClassifier` run cannot emit a schema-valid v1 artifact.
`analytical-visualizations.v5` is the corrected, strict, independent branch.

This module tests direct JSON Schema behavior only, using hand-built
representative fixtures -- it never trains a model and never imports
`pipeline.training`. Covers:

  * a representative `analytical-visualizations.v5` artifact validates;
  * `model_family = hist_gradient_boosting` is required;
  * `method = permutation_importance` is required;
  * a missing `method`, wrong `model_family`, wrong `problem_type`, wrong
    `result_semantics_schema_version`, invalid `positive_class_id`, wrong
    `population_kind`, wrong `scoring`, wrong `n_repeats`, and wrong
    `random_seed_source` are each rejected;
  * extra/raw prediction/row/model-byte fields are rejected
    (`additionalProperties: false` throughout, and `evidence_policy`
    structurally forbids raw dataset/model/estimator/matrix embedding);
  * representative legacy v1 and v2/v3/v4 artifacts remain valid unchanged
    alongside the new v5 branch.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"

pytestmark = pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator() -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(_schema())


def _evidence_policy() -> dict:
    return {
        "raw_logs_prohibited": True,
        "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True,
        "secrets_prohibited": True,
        "raw_dataset_embedded": False,
        "model_bytes_embedded": False,
        "serialized_estimator_state_embedded": False,
        "raw_transformed_matrices_embedded": False,
        "notebook_state_embedded": False,
        "reduced_and_sanitized": True,
    }


def _training_run_identity(dataset_slug: str = "synthetic-binary-fixture") -> dict:
    return {
        "dataset_slug": dataset_slug,
        "run_id": "train-20260819T000000Z",
        "output_directory": f"pipeline/training-runs/{dataset_slug}/train-20260819T000000Z/",
    }


def _charts() -> list[dict]:
    return [
        {
            "id": "target_distribution",
            "title": "Target Distribution",
            "type": "bar",
            "x_label": "Churn",
            "y_label": "Rows",
            "data": [{"name": "Yes", "value": 40}, {"name": "No", "value": 160}],
        },
        {
            "id": "feature_importance",
            "title": "Feature Importance",
            "type": "bar",
            "x_label": "Feature",
            "y_label": "Importance",
            "data": [{"name": "tenure", "value": 0.7}, {"name": "monthly_charges", "value": 0.3}],
        },
    ]


def _representative_v5() -> dict:
    return {
        "schema_version": "analytical-visualizations.v5",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": _training_run_identity(),
        "classification_evidence": {
            "problem_type": "binary_classification",
            "result_semantics_schema_version": "binary-result-semantics.v1",
            "positive_class_id": "Yes",
        },
        "charts": _charts(),
        "target_distribution_method": {
            "population_kind": "prepared_dataset",
            "row_count": 200,
            "target_column": "Churn",
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "sklearn.inspection.permutation_importance",
            "method": "permutation_importance",
            "population_kind": "finalized_fit_population",
            "scoring": "roc_auc",
            "n_repeats": 5,
            "random_seed_source": "execution_contract.random_seed",
            "total_source_feature_count": 2,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "evidence_policy": _evidence_policy(),
    }


def _assert_invalid(instance: dict) -> None:
    errors = list(_validator().iter_errors(instance))
    assert errors, "expected schema validation to reject this instance"


def test_representative_v5_validates():
    jsonschema.validate(_representative_v5(), _schema())


def test_v5_requires_hist_gradient_boosting_model_family():
    instance = _representative_v5()
    instance["feature_importance_method"]["model_family"] = "gradient_boosting"
    _assert_invalid(instance)


def test_v5_wrong_model_family_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["model_family"] = "random_forest"
    _assert_invalid(instance)


def test_v5_requires_permutation_importance_method():
    instance = _representative_v5()
    instance["feature_importance_method"]["method"] = "feature_importances_"
    _assert_invalid(instance)


def test_v5_missing_method_rejected():
    instance = _representative_v5()
    del instance["feature_importance_method"]["method"]
    _assert_invalid(instance)


def test_v5_wrong_problem_type_rejected():
    instance = _representative_v5()
    instance["classification_evidence"]["problem_type"] = "multiclass_classification"
    _assert_invalid(instance)


def test_v5_wrong_result_semantics_version_rejected():
    instance = _representative_v5()
    instance["classification_evidence"]["result_semantics_schema_version"] = "binary-result-semantics.v2"
    _assert_invalid(instance)


def test_v5_invalid_positive_class_rejected():
    instance = _representative_v5()
    instance["classification_evidence"]["positive_class_id"] = ""
    _assert_invalid(instance)


def test_v5_missing_positive_class_rejected():
    instance = _representative_v5()
    del instance["classification_evidence"]["positive_class_id"]
    _assert_invalid(instance)


def test_v5_wrong_population_kind_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["population_kind"] = "final_fit_train_plus_validation"
    _assert_invalid(instance)


def test_v5_wrong_scoring_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["scoring"] = "neg_mean_absolute_error"
    _assert_invalid(instance)


def test_v5_wrong_repeat_count_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["n_repeats"] = 10
    _assert_invalid(instance)


def test_v5_wrong_random_seed_provenance_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["random_seed_source"] = 42
    _assert_invalid(instance)


def test_v5_missing_random_seed_provenance_rejected():
    instance = _representative_v5()
    del instance["feature_importance_method"]["random_seed_source"]
    _assert_invalid(instance)


def test_v5_extra_top_level_property_rejected():
    instance = _representative_v5()
    instance["extra_field"] = "unexpected"
    _assert_invalid(instance)


def test_v5_extra_feature_importance_method_property_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["extra"] = "unexpected"
    _assert_invalid(instance)


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_predictions", [0.1, 0.9]),
        ("raw_rows", [{"tenure": 1}]),
        ("model_bytes", "deadbeef"),
        ("model_path", "/private/model.pkl"),
    ],
)
def test_v5_raw_prediction_row_or_model_fields_rejected(field, value):
    instance = _representative_v5()
    instance[field] = value
    _assert_invalid(instance)


def test_v5_evidence_policy_structurally_forbids_raw_embedding():
    instance = _representative_v5()
    for key in (
        "raw_dataset_embedded",
        "model_bytes_embedded",
        "serialized_estimator_state_embedded",
        "raw_transformed_matrices_embedded",
        "notebook_state_embedded",
    ):
        bad = copy.deepcopy(instance)
        bad["evidence_policy"][key] = True
        _assert_invalid(bad)


def test_v5_wrong_public_row_limit_rejected():
    instance = _representative_v5()
    instance["feature_importance_method"]["public_row_limit"] = 25
    _assert_invalid(instance)


def test_v5_charts_still_bounded_to_two_public_entries():
    instance = _representative_v5()
    instance["charts"].append(dict(instance["charts"][0]))
    _assert_invalid(instance)


# ---------------------------------------------------------------------------
# Legacy v1 and v2/v3/v4 must remain valid, unchanged, alongside the new v5
# branch (acceptance criteria 8-10).
# ---------------------------------------------------------------------------


def _representative_v1() -> dict:
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": _training_run_identity(),
        "charts": _charts(),
        "target_distribution_method": {
            "population_kind": "prepared_dataset",
            "row_count": 200,
            "target_column": "Churn",
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 2,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "evidence_policy": _evidence_policy(),
    }


def test_representative_legacy_v1_still_validates_unchanged():
    jsonschema.validate(_representative_v1(), _schema())


def test_v1_never_accepts_hist_gradient_boosting_model_family():
    """S0258 must never widen legacy v1's model_family enum."""
    instance = _representative_v1()
    instance["feature_importance_method"]["model_family"] = "hist_gradient_boosting"
    _assert_invalid(instance)


def test_v1_never_accepts_a_method_field():
    instance = _representative_v1()
    instance["feature_importance_method"]["method"] = "permutation_importance"
    _assert_invalid(instance)


def _representative_v2() -> dict:
    return {
        "schema_version": "analytical-visualizations.v2",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": _training_run_identity("synthetic-multiclass-fixture"),
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": ["low", "medium", "high"],
        },
        "charts": _charts(),
        "target_distribution_method": {
            "population_kind": "prepared_dataset",
            "row_count": 300,
            "target_column": "risk_band",
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "sklearn.inspection.permutation_importance",
            "method": "permutation_importance",
            "total_source_feature_count": 2,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "confusion_matrix": {
            "ordered_class_ids": ["low", "medium", "high"],
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "row_axis": "true_class",
            "column_axis": "predicted_class",
        },
        "evidence_policy": _evidence_policy(),
    }


def test_representative_v2_remains_valid():
    jsonschema.validate(_representative_v2(), _schema())


def _representative_v3() -> dict:
    return {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": _training_run_identity("synthetic-regression-fixture"),
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "charts": _charts(),
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 150,
            "target_column": "outcome_measure",
            "bin_count": 15,
            "min_value": 0.0,
            "max_value": 100.0,
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 2,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test",
            "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width",
            "reference_line": "identity",
            "points": [{"actual_mean": 10.0, "predicted_mean": 11.0, "count": 5}],
        },
        "residual_distribution": {
            "partition_role": "test",
            "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [{"label": "-1 to 1", "lower_bound": -1.0, "upper_bound": 1.0, "count": 5}],
        },
        "evidence_policy": _evidence_policy(),
    }


def test_representative_v3_remains_valid():
    jsonschema.validate(_representative_v3(), _schema())


def _representative_v4() -> dict:
    return {
        "schema_version": "analytical-visualizations.v4",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": _training_run_identity("synthetic-forecasting-fixture"),
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "training_metrics_schema_version": "training-metrics.v4",
            "forecast_horizon": 3,
            "frequency": "monthly",
            "seasonal_period": 12,
        },
        "dataset_statistics": {
            "instance_count": 120,
            "development_observations": 108,
            "final_holdout_observations": 12,
        },
        "seasonal_profile": {
            "population_kind": "full_development",
            "seasonal_period": 12,
            "points": [
                {"season_position": position, "mean_target": float(position), "observation_count": 9}
                for position in range(12)
            ],
        },
        "backtesting_fold_metric": {
            "metric_id": "mae",
            "direction": "lower_is_better",
            "fold_count": 2,
            "points": [
                {"fold_index": 0, "forecast_origin": "2020-01", "value": 1.2, "validation_observations": 3},
                {"fold_index": 1, "forecast_origin": "2020-04", "value": 1.1, "validation_observations": 3},
            ],
        },
        "horizon_mae": {
            "points": [
                {"horizon_step": 1, "mae": 0.9, "observation_count": 2},
                {"horizon_step": 2, "mae": 1.0, "observation_count": 2},
                {"horizon_step": 3, "mae": 1.1, "observation_count": 2},
            ],
        },
        "evidence_policy": _evidence_policy(),
    }


def test_representative_v4_remains_valid():
    jsonschema.validate(_representative_v4(), _schema())
