"""Dedicated Project Spec S0228 tests for the Atlas-native continuous-
regression `analytical-visualizations.v3` profile.

Covers, using only synthetic Atlas-owned fixtures under `tmp_path` (never a
real dataset/model file, never `dataset-study-*`, and never a write under the
real repository `releases/`, `publisher/runs/`, or `pipeline/training-runs/`
trees):

  * `analytical-visualizations.v3` schema validity (both the deterministic
    binning primitives in isolation and a real trained artifact against
    `pipeline/analytical-visualizations.schema.json`);
  * deterministic, bounded, count-complete target-distribution histogram;
  * bounded, truthful feature importance (never permutation, never test
    labels);
  * bounded, count-complete Actual vs Predicted aggregate invariants;
  * bounded, count-complete Residual Distribution aggregate invariants;
  * that visualization generation reuses the single already-computed
    final-test prediction pass -- never a second `predict` call;
  * that no row-level actual/predicted/residual evidence or row identifiers
    ever leak into the artifact;
  * `publisher/validate.py`'s new native continuous-regression visualization
    compatibility dispatch (v3 required, v1/v2 substitution rejected,
    classification evidence rejected, final-test population cross-check).
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training  # noqa: E402
from pipeline.training import (  # noqa: E402
    ANALYTICAL_VISUALIZATIONS_FILENAME,
    NATIVE_CONTINUOUS_REGRESSION_ANALYTICAL_VISUALIZATIONS_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_MAX_HISTOGRAM_BINS,
    NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
    TrainingInputError,
    _continuous_equal_width_histogram,
    _native_continuous_regression_actual_vs_predicted,
    _native_continuous_regression_residual_distribution,
    _native_continuous_regression_target_histogram_chart,
    train_from_paths,
)
from publisher import validate  # noqa: E402

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

try:
    import sklearn  # noqa: F401

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False

REPO_ROOT = Path(__file__).parent.parent
ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"
DATASET_SLUG = "synthetic-visualizations-fixture"


# ---------------------------------------------------------------------------
# Unit-level: the deterministic equal-width histogram primitive
# ---------------------------------------------------------------------------


def test_histogram_is_deterministic_for_identical_inputs():
    values = [round(random.Random(1).uniform(0, 100), 3) for _ in range(200)]
    first = _continuous_equal_width_histogram(
        values, max_bins=15, error_code="invalid_prepared_dataset", error_field="target_column",
    )
    second = _continuous_equal_width_histogram(
        values, max_bins=15, error_code="invalid_prepared_dataset", error_field="target_column",
    )
    assert first == second


def test_histogram_counts_sum_to_population_and_bins_do_not_overlap():
    values = [round(random.Random(2).uniform(-50, 50), 3) for _ in range(137)]
    bins = _continuous_equal_width_histogram(
        values, max_bins=15, error_code="invalid_prepared_dataset", error_field="target_column",
    )
    assert sum(b["count"] for b in bins) == len(values)
    assert len(bins) <= 15
    assert len(bins) >= 1
    for b in bins:
        assert isinstance(b["count"], int)
        assert b["count"] >= 0
        assert math.isfinite(b["lower_bound"])
        assert math.isfinite(b["upper_bound"])
        assert b["lower_bound"] <= b["upper_bound"]
    for earlier, later in zip(bins, bins[1:]):
        assert earlier["upper_bound"] <= later["lower_bound"]


def test_histogram_degenerate_range_emits_one_truthful_bin_never_nan_or_infinite():
    values = [7.5] * 25
    bins = _continuous_equal_width_histogram(
        values, max_bins=15, error_code="invalid_prepared_dataset", error_field="target_column",
    )
    assert len(bins) == 1
    assert bins[0]["count"] == 25
    assert bins[0]["lower_bound"] == bins[0]["upper_bound"] == 7.5


def test_histogram_rejects_non_finite_value():
    with pytest.raises(TrainingInputError):
        _continuous_equal_width_histogram(
            [1.0, float("nan"), 3.0],
            max_bins=15,
            error_code="invalid_prepared_dataset",
            error_field="target_column",
        )


def test_histogram_rejects_empty_population():
    with pytest.raises(TrainingInputError):
        _continuous_equal_width_histogram(
            [], max_bins=15, error_code="invalid_prepared_dataset", error_field="target_column",
        )


def test_target_histogram_chart_carries_no_row_identifiers_or_raw_vector():
    rows = [{"target": float(i)} for i in range(40)]
    chart_data, method = _native_continuous_regression_target_histogram_chart(
        rows, "target", max_bins=NATIVE_CONTINUOUS_REGRESSION_MAX_HISTOGRAM_BINS,
    )
    assert sum(point["value"] for point in chart_data) == 40
    assert all(set(point) == {"name", "value"} for point in chart_data)
    assert method["row_count"] == 40
    assert method["distribution_kind"] == "continuous_histogram"
    assert method["binning_method"] == "deterministic_equal_width"


def test_target_histogram_chart_rejects_missing_target_value():
    rows = [{"target": 1.0}, {"target": None}]
    with pytest.raises(TrainingInputError) as excinfo:
        _native_continuous_regression_target_histogram_chart(rows, "target", max_bins=15)
    assert excinfo.value.code == "missing_target_value_for_visualization"


# ---------------------------------------------------------------------------
# Unit-level: Actual vs Predicted / Residual Distribution aggregates
# ---------------------------------------------------------------------------


def test_actual_vs_predicted_counts_sum_to_population_and_contain_no_row_arrays():
    rng = random.Random(3)
    y_true = [rng.uniform(0, 100) for _ in range(83)]
    y_pred = [value + rng.uniform(-5, 5) for value in y_true]

    result = _native_continuous_regression_actual_vs_predicted(y_true=y_true, y_pred=y_pred, max_bins=15)

    assert result["partition_role"] == "test"
    assert result["evaluation_count"] == 1
    assert result["reference_line"] == "identity"
    assert sum(point["count"] for point in result["points"]) == len(y_true)
    assert len(result["points"]) <= 15
    for point in result["points"]:
        assert set(point) == {"actual_mean", "predicted_mean", "count", "bin_lower", "bin_upper"}
        assert math.isfinite(point["actual_mean"])
        assert math.isfinite(point["predicted_mean"])
        assert point["count"] >= 1


def test_actual_vs_predicted_rejects_non_finite_value():
    with pytest.raises(TrainingInputError):
        _native_continuous_regression_actual_vs_predicted(
            y_true=[1.0, 2.0, 3.0], y_pred=[1.0, float("inf"), 3.0], max_bins=15,
        )


def test_residual_distribution_definition_and_count_completeness():
    rng = random.Random(4)
    y_true = [rng.uniform(0, 20) for _ in range(64)]
    y_pred = [value - 1.0 for value in y_true]  # every residual is exactly +1.0

    result = _native_continuous_regression_residual_distribution(y_true=y_true, y_pred=y_pred, max_bins=15)

    assert result["residual_definition"] == "actual_minus_predicted"
    assert result["partition_role"] == "test"
    assert result["evaluation_count"] == 1
    assert sum(b["count"] for b in result["bins"]) == len(y_true)
    # A constant residual across the whole population is a degenerate range:
    # exactly one truthful bin, not a fabricated spread.
    assert len(result["bins"]) == 1
    assert result["bins"][0]["count"] == len(y_true)


def test_residual_distribution_never_carries_a_raw_residual_vector():
    y_true = [1.0, 2.0, 3.0, 4.0]
    y_pred = [1.1, 1.8, 3.3, 3.9]
    result = _native_continuous_regression_residual_distribution(y_true=y_true, y_pred=y_pred, max_bins=15)
    serialized = json.dumps(result)
    for raw_residual in (-0.1, 0.2, -0.3, 0.1):
        # A coincidental numeric match against a bounded bin boundary is
        # possible but vanishingly unlikely for these fixture values; this
        # guards against accidentally embedding the raw per-row list itself.
        assert "residual_values" not in result
        assert "raw_residuals" not in result
    assert set(result) == {"partition_role", "evaluation_count", "residual_definition", "binning_method", "bins"}
    assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# End-to-end: a real trained artifact, schema validity, no second predict
# ---------------------------------------------------------------------------


def _gbr_hyperparameters() -> dict:
    return {
        "n_estimators": 50,
        "learning_rate": 0.1,
        "max_depth": 3,
        "min_samples_leaf": 5,
        "subsample": 0.9,
        "loss": "squared_error",
    }


def _fixed_continuous_regression_contract() -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": DATASET_SLUG,
        "target_column": "outcome",
        "feature_columns": ["feature_a", "feature_b"],
        "ignored_columns": ["record_ref"],
        "required_columns": ["feature_a", "feature_b"],
        "optional_columns": [],
        "feature_definitions": {
            "feature_a": {"type": "numeric"},
            "feature_b": {"type": "numeric"},
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "random_seed": 99,
        "primary_metric": "r2",
        "secondary_metrics": ["mae", "rmse"],
        "modeling_constraints": {
            "allowed_model_families": ["gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "gradient_boosting",
                "hyperparameters": _gbr_hyperparameters(),
            },
        },
        "result_semantics": {
            "schema_version": NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
            "problem_type": "continuous_regression",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
        },
    }


def _synthetic_regression_dataset(row_count: int = 140, seed: int = 5) -> dict:
    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        feature_a = rng.uniform(0, 60)
        feature_b = rng.uniform(0, 30)
        outcome = 1.5 * feature_a + 0.7 * feature_b + rng.uniform(-3, 3)
        rows.append({
            "dataset_id": DATASET_SLUG,
            "record_ref": f"row-{index:04d}",
            "feature_a": round(feature_a, 4),
            "feature_b": round(feature_b, 4),
            "outcome": round(outcome, 4),
        })
    return {"dataset_id": DATASET_SLUG, "rows": rows}


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    return repo_root


def _run(fixed_training_environment: Path, tmp_path: Path):
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())
    result = train_from_paths(
        contract_path, dataset_path, dataset_slug=DATASET_SLUG, run_id="train-20260819T010000Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    return result, output_directory


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason="scikit-learn not installed")
def test_trained_v3_artifact_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _, output_directory = _run(fixed_training_environment, tmp_path)
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    assert artifact["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_ANALYTICAL_VISUALIZATIONS_VERSION
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    jsonschema.validate(artifact, schema)


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason="scikit-learn not installed")
def test_trained_v3_feature_importance_is_bounded_truthful_and_not_from_test_labels(
    fixed_training_environment: Path, tmp_path: Path,
):
    _, output_directory = _run(fixed_training_environment, tmp_path)
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())

    method = artifact["feature_importance_method"]
    assert method["model_family"] == "gradient_boosting"
    assert method["source"] == "estimator.feature_importances_"
    assert method["public_row_limit"] == 10
    assert method["total_source_feature_count"] == 2

    feature_importance_chart = next(c for c in artifact["charts"] if c["id"] == "feature_importance")
    assert len(feature_importance_chart["data"]) <= 10
    for point in feature_importance_chart["data"]:
        assert math.isfinite(point["value"])
        assert point["value"] >= 0


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason="scikit-learn not installed")
def test_visualization_generation_never_triggers_a_second_final_model_predict_call(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
):
    from sklearn.pipeline import Pipeline

    original_predict = Pipeline.predict
    calls: list[int] = []

    def _counting_predict(self, features):
        calls.append(len(features))
        return original_predict(self, features)

    monkeypatch.setattr(Pipeline, "predict", _counting_predict)

    _run(fixed_training_environment, tmp_path)

    # One predict call for the descriptive validation partition (S0224 Step
    # 1) and one for the sealed final-test partition (S0224 Step 3, whose
    # result is reused for every S0228 visualization) -- never a third call.
    assert len(calls) == 2


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason="scikit-learn not installed")
def test_trained_v3_artifact_contains_no_row_level_evidence(
    fixed_training_environment: Path, tmp_path: Path,
):
    _, output_directory = _run(fixed_training_environment, tmp_path)
    artifact_text = (output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text()
    artifact = json.loads(artifact_text)

    for forbidden_key in ("record_ref", "row_id", "row_ids", "raw_rows", "predictions", "residuals"):
        assert forbidden_key not in artifact_text

    assert "classification_evidence" not in artifact
    assert "confusion_matrix" not in artifact

    for row_id in (f"row-{index:04d}" for index in range(140)):
        assert row_id not in artifact_text


# ---------------------------------------------------------------------------
# publisher/validate.py: native continuous-regression visualization
# compatibility dispatch (Project Spec S0228 Desired Change G)
# ---------------------------------------------------------------------------


def _regression_result_semantics(**overrides) -> dict:
    semantics = {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "result_schema_version": "continuous-regression-result.v1",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
    }
    semantics.update(overrides)
    return semantics


def _valid_v3_visualizations(**overrides) -> dict:
    payload = {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260819T010000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260819T010000Z/",
        },
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "outcome", "y_label": "Rows",
                "data": [{"name": "0 to 10", "value": 3}, {"name": "10 to 20", "value": 1}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "feature_a", "value": 0.8}],
            },
        ],
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 4,
            "target_column": "outcome",
            "bin_count": 2,
            "min_value": 1.0,
            "max_value": 15.0,
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test",
            "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width_actual_bins",
            "reference_line": "identity",
            "points": [{"actual_mean": 5.0, "predicted_mean": 5.2, "count": 4}],
        },
        "residual_distribution": {
            "partition_role": "test",
            "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [{"label": "-1 to 1", "lower_bound": -1.0, "upper_bound": 1.0, "count": 4}],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    payload.update(overrides)
    return payload


def _regression_metrics(*, final_test_row_count: int = 4, completed: bool = True) -> dict:
    return {
        "schema_version": "training-metrics.v3",
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "final_test_evaluation": {
            "partition_role": "test",
            "completed": completed,
            "row_count": final_test_row_count,
            "metrics": [{"name": "r2", "value": 0.8}] if completed else [],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "metrics": [{"name": "r2", "value": 0.7}],
        },
    }


def _regression_predictive_bundle() -> dict:
    return {
        "result_semantics": _regression_result_semantics(),
        "output_schema": {"prediction_key": "prediction", "prediction_type": "number"},
        "model_provenance_origin": "atlas_internal_training",
    }


def test_publisher_accepts_valid_v3_visualizations_for_regression():
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        _valid_v3_visualizations(), _regression_predictive_bundle(), _regression_metrics(),
    )
    assert reasons == []


def test_publisher_rejects_v1_visualizations_substitution_for_regression():
    v1_visualizations = {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
    }
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        v1_visualizations, _regression_predictive_bundle(), _regression_metrics(),
    )
    assert len(reasons) == 1
    assert reasons[0]["safe_detail"] == "native_regression_visualizations_version_mismatch"


def test_publisher_rejects_v2_visualizations_substitution_for_regression():
    v2_visualizations = {
        "schema_version": "analytical-visualizations.v2",
        "artifact_kind": "analytical_visualizations",
    }
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        v2_visualizations, _regression_predictive_bundle(), _regression_metrics(),
    )
    assert len(reasons) == 1
    assert reasons[0]["safe_detail"] == "native_regression_visualizations_version_mismatch"


@pytest.mark.parametrize("forbidden_key", ["classification_evidence", "confusion_matrix"])
def test_publisher_rejects_v3_visualizations_carrying_classification_evidence(forbidden_key):
    visualizations = _valid_v3_visualizations(**{forbidden_key: {"ordered_class_ids": ["a", "b", "c"]}})
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        visualizations, _regression_predictive_bundle(), _regression_metrics(),
    )
    assert len(reasons) == 1
    assert reasons[0]["safe_detail"] == "native_regression_visualizations_classification_evidence_present"


def test_publisher_rejects_diagnostic_population_mismatch_against_completed_final_test():
    visualizations = _valid_v3_visualizations()
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        visualizations, _regression_predictive_bundle(), _regression_metrics(final_test_row_count=999),
    )
    assert len(reasons) == 1
    assert reasons[0]["safe_detail"] == "native_regression_visualizations_population_mismatch"


def test_publisher_skips_population_cross_check_when_final_test_not_completed():
    visualizations = _valid_v3_visualizations()
    reasons = validate._internal_native_continuous_regression_visualizations_compatibility(
        visualizations,
        _regression_predictive_bundle(),
        _regression_metrics(final_test_row_count=999, completed=False),
    )
    assert reasons == []


def test_publisher_visualizations_check_is_a_noop_for_non_dict_inputs():
    assert validate._internal_native_continuous_regression_visualizations_compatibility(None, {}, {}) == []
    assert validate._internal_native_continuous_regression_visualizations_compatibility({}, None, {}) == []
