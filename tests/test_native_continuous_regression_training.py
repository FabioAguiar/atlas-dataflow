"""Focused tests for Atlas-native fixed-configuration continuous-regression
training (Project Spec S0224).

All fixtures are synthetic and dataset-neutral -- no UCI fetch, no GitHub
access, no dataset-study-* path, no external model bytes, and no
Concrete-specific names/values, matching the boundary already established by
tests/test_native_multiclass_training.py and
tests/test_contract_derivation.py's continuous-regression fixtures.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training
from pipeline.training import (
    ANALYTICAL_VISUALIZATIONS_FILENAME,
    MODEL_ARTIFACT_FILENAME,
    MODEL_CARD_FILENAME,
    MODEL_CARD_INPUT_FILENAME,
    METRICS_ARTIFACT_FILENAME,
    NATIVE_CONTINUOUS_REGRESSION_ANALYTICAL_VISUALIZATIONS_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_HGB_PERMUTATION_IMPORTANCE_N_REPEATS,
    NATIVE_CONTINUOUS_REGRESSION_HGB_PERMUTATION_IMPORTANCE_SCORING,
    NATIVE_CONTINUOUS_REGRESSION_METRIC_NAMES,
    NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_TRAINING_METRICS_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_TRAINING_PARAMETER_RECORD_VERSION,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _continuous_regression_random_three_way_split_indices,
    _native_continuous_regression_feature_importance,
    _native_continuous_regression_metric_values,
    _validate_fixed_continuous_regression_configuration,
    train_from_paths,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REPO_ROOT = Path(__file__).parent.parent
TRAINING_PARAMETER_RECORD_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-parameter-record.schema.json"
TRAINING_METRICS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-metrics.schema.json"
ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"


# ---------------------------------------------------------------------------
# Fixtures -- synthetic dataset-neutral continuous-regression contract/rows
# ---------------------------------------------------------------------------


def _gbr_hyperparameters(**overrides) -> dict:
    base = {
        "n_estimators": 60,
        "learning_rate": 0.1,
        "max_depth": 3,
        "min_samples_leaf": 5,
        "subsample": 0.9,
        "loss": "squared_error",
    }
    base.update(overrides)
    return base


def _rfr_hyperparameters(**overrides) -> dict:
    base = {
        "n_estimators": 60,
        "max_depth": 4,
        "min_samples_leaf": 5,
        "max_features": "sqrt",
        "bootstrap": True,
    }
    base.update(overrides)
    return base


def _hgb_regression_hyperparameters(**overrides) -> dict:
    base = {
        "l2_regularization": 0.0,
        "learning_rate": 0.1,
        "max_iter": 60,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 5,
    }
    base.update(overrides)
    return base


def _default_hyperparameters_for_family(model_family: str) -> dict:
    if model_family == "gradient_boosting":
        return _gbr_hyperparameters()
    if model_family == "random_forest":
        return _rfr_hyperparameters()
    return _hgb_regression_hyperparameters()


def _fixed_continuous_regression_contract(
    *, model_family: str = "gradient_boosting", hyperparameters: dict | None = None,
) -> dict:
    if hyperparameters is None:
        hyperparameters = _default_hyperparameters_for_family(model_family)
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "synthetic-regression-fixture",
        "target_column": "outcome_measure",
        "feature_columns": ["input_a", "input_b"],
        "ignored_columns": ["record_ref"],
        "required_columns": ["input_a", "input_b"],
        "optional_columns": [],
        "feature_definitions": {
            "input_a": {"type": "numeric"},
            "input_b": {"type": "numeric"},
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "random_seed": 13,
        "primary_metric": "r2",
        "secondary_metrics": ["mae", "rmse"],
        "modeling_constraints": {
            "allowed_model_families": [model_family],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": model_family,
                "hyperparameters": hyperparameters,
            },
        },
        "result_semantics": {
            "schema_version": NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
            "problem_type": "continuous_regression",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
        },
    }


def _synthetic_regression_dataset(row_count: int = 150, seed: int = 0) -> dict:
    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        input_a = rng.uniform(0, 100)
        input_b = rng.uniform(0, 50)
        noise = rng.uniform(-2, 2)
        outcome = 2.0 * input_a - 1.5 * input_b + 10.0 + noise
        rows.append(
            {
                "dataset_id": "synthetic-regression-fixture",
                "record_ref": f"row-{index:04d}",
                "input_a": round(input_a, 4),
                "input_b": round(input_b, 4),
                "outcome_measure": round(outcome, 4),
            }
        )
    return {"dataset_id": "synthetic-regression-fixture", "rows": rows}


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    return repo_root


def _write_valid_inputs(tmp_path: Path, *, model_family: str = "gradient_boosting") -> tuple[Path, Path]:
    contract_path = _write_json(
        tmp_path / "execution-contract.json", _fixed_continuous_regression_contract(model_family=model_family)
    )
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())
    return contract_path, dataset_path


def _run(fixed_training_environment: Path, tmp_path: Path, *, model_family: str = "gradient_boosting"):
    contract_path, dataset_path = _write_valid_inputs(tmp_path, model_family=model_family)
    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="synthetic-regression-fixture",
        run_id="train-20260819T000000Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    return result, output_directory


# ---------------------------------------------------------------------------
# End-to-end fixed-configuration continuous-regression runs
# ---------------------------------------------------------------------------


def test_gradient_boosting_fixed_configuration_trains_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="gradient_boosting")

    assert result.status == "trained"
    assert result.model_family == "gradient_boosting"
    assert result.task_type == "continuous_regression"
    for artifact_name in (
        MODEL_ARTIFACT_FILENAME,
        TRAINING_PARAMETER_RECORD_FILENAME,
        METRICS_ARTIFACT_FILENAME,
        MODEL_CARD_INPUT_FILENAME,
        MODEL_CARD_FILENAME,
    ):
        artifact_path = output_directory / artifact_name
        assert artifact_path.exists(), artifact_name
        assert artifact_path.stat().st_size > 0, artifact_name


def test_random_forest_fixed_configuration_trains_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="random_forest")

    assert result.status == "trained"
    assert result.model_family == "random_forest"
    assert result.task_type == "continuous_regression"
    assert (output_directory / MODEL_ARTIFACT_FILENAME).exists()


def test_hist_gradient_boosting_fixed_configuration_trains_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    """Project Spec S0231: hist_gradient_boosting is a third bounded fixed
    continuous-regression family, using sklearn.ensemble.HistGradientBoostingRegressor
    (never HistGradientBoostingClassifier)."""
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="hist_gradient_boosting")

    assert result.status == "trained"
    assert result.model_family == "hist_gradient_boosting"
    assert result.task_type == "continuous_regression"
    for artifact_name in (
        MODEL_ARTIFACT_FILENAME,
        TRAINING_PARAMETER_RECORD_FILENAME,
        METRICS_ARTIFACT_FILENAME,
        MODEL_CARD_INPUT_FILENAME,
        MODEL_CARD_FILENAME,
        ANALYTICAL_VISUALIZATIONS_FILENAME,
    ):
        artifact_path = output_directory / artifact_name
        assert artifact_path.exists(), artifact_name
        assert artifact_path.stat().st_size > 0, artifact_name

    estimator = result.model.named_steps["model"]
    assert type(estimator).__name__ == "HistGradientBoostingRegressor"
    assert estimator.random_state == 13  # governed by execution-contract random_seed, not a hyperparameter
    assert not hasattr(estimator, "class_weight")

    assert set(result.metrics) == {"r2", "mae", "rmse"}
    for value in result.metrics.values():
        assert value == value  # not NaN
        assert value not in (float("inf"), float("-inf"))

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_artifact["final_test_evaluation"]["evaluation_count"] == 1
    assert metrics_artifact["final_test_evaluation"]["sealed_before_finalization"] is True
    assert metrics_artifact["final_test_evaluation"]["used_for_fitting"] is False

    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert parameter_record["training_parameters"]["model_family"] == "hist_gradient_boosting"
    assert parameter_record["training_parameters"]["hyperparameters"] == _hgb_regression_hyperparameters()
    assert parameter_record["training_parameters"]["random_seed"] == 13
    assert parameter_record["training_parameters"]["selection_mode"] == "fixed_configuration"
    assert parameter_record["training_parameters"]["model_selection_performed"] is False


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_hist_gradient_boosting_training_parameter_record_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="hist_gradient_boosting")
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    schema = json.loads(TRAINING_PARAMETER_RECORD_SCHEMA_PATH.read_text())
    jsonschema.validate(parameter_record, schema)


def test_hist_gradient_boosting_feature_importance_uses_permutation_importance(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="hist_gradient_boosting")
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())

    method = artifact["feature_importance_method"]
    assert method["model_family"] == "hist_gradient_boosting"
    assert method["source"] == "sklearn.inspection.permutation_importance"
    assert method["method"] == "permutation_importance"
    assert method["population_kind"] == "final_fit_train_plus_validation"
    assert method["scoring"] == NATIVE_CONTINUOUS_REGRESSION_HGB_PERMUTATION_IMPORTANCE_SCORING
    assert method["scoring"] == "neg_mean_absolute_error"
    assert method["n_repeats"] == NATIVE_CONTINUOUS_REGRESSION_HGB_PERMUTATION_IMPORTANCE_N_REPEATS
    assert method["n_repeats"] == 5
    assert method["random_seed"] == 13

    feature_importance_chart = next(c for c in artifact["charts"] if c["id"] == "feature_importance")
    values = [point["value"] for point in feature_importance_chart["data"]]
    assert len(values) <= 10
    assert all(value >= 0 for value in values)
    assert abs(sum(values) - 1.0) < 1e-9


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_hist_gradient_boosting_analytical_visualizations_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="hist_gradient_boosting")
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    jsonschema.validate(artifact, schema)


def test_hist_gradient_boosting_permutation_importance_population_is_train_plus_validation_only(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
) -> None:
    """Desired Change H/Acceptance criteria 25/26: permutation importance
    must receive only the final-fit (train+validation) population -- never
    the sealed final-test partition -- and must be called with the governed
    deterministic scoring/n_repeats/random_state/n_jobs."""
    captured: dict = {}
    from sklearn.inspection import permutation_importance as real_permutation_importance

    def _capturing_permutation_importance(estimator, X, y, **kwargs):
        captured["row_count"] = len(X)
        captured["kwargs"] = kwargs
        return real_permutation_importance(estimator, X, y, **kwargs)

    monkeypatch.setattr(
        "sklearn.inspection.permutation_importance", _capturing_permutation_importance
    )

    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="hist_gradient_boosting")
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    split_sizes = parameter_record["training_parameters"]["split_sizes"]

    assert captured["row_count"] == split_sizes["final_fit_rows"]
    assert captured["row_count"] != split_sizes["test_rows"]
    assert captured["row_count"] < 150  # never the full 150-row prepared dataset either

    kwargs = captured["kwargs"]
    assert kwargs["scoring"] == "neg_mean_absolute_error"
    assert kwargs["n_repeats"] == 5
    assert kwargs["random_state"] == 13
    assert kwargs["n_jobs"] == 1


def test_hist_gradient_boosting_permutation_importance_negative_means_clamp_to_zero(monkeypatch) -> None:
    class _FakeResult:
        importances_mean = [-0.4, 0.6]

    monkeypatch.setattr(
        "sklearn.inspection.permutation_importance", lambda *a, **k: _FakeResult()
    )
    data, total, omitted = _native_continuous_regression_feature_importance(
        model_family="hist_gradient_boosting",
        final_pipeline=object(),
        feature_columns=["input_a", "input_b"],
        final_fit_features=object(),
        final_fit_target=object(),
        random_seed=13,
    )
    assert total == 2
    assert omitted == 0
    by_name = {entry["name"]: entry["value"] for entry in data}
    assert by_name["input_a"] == 0.0  # negative mean clamped to zero, not made absolute
    assert by_name["input_b"] == 1.0


def test_hist_gradient_boosting_permutation_importance_zero_total_fails_closed(monkeypatch) -> None:
    class _FakeResult:
        importances_mean = [-0.1, -0.2]

    monkeypatch.setattr(
        "sklearn.inspection.permutation_importance", lambda *a, **k: _FakeResult()
    )
    with pytest.raises(TrainingInputError) as excinfo:
        _native_continuous_regression_feature_importance(
            model_family="hist_gradient_boosting",
            final_pipeline=object(),
            feature_columns=["input_a", "input_b"],
            final_fit_features=object(),
            final_fit_target=object(),
            random_seed=13,
        )
    assert excinfo.value.code == "zero_total_feature_importance"


def test_gradient_boosting_and_random_forest_feature_importance_still_direct_not_permutation(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    """Desired Change I: direct-importance families must never be converted
    to permutation importance by the S0231 HGB addition."""
    for model_family in ("gradient_boosting", "random_forest"):
        _, output_directory = _run(fixed_training_environment, tmp_path, model_family=model_family)
        artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
        method = artifact["feature_importance_method"]
        assert method["model_family"] == model_family
        assert method["source"] == "estimator.feature_importances_"
        assert "method" not in method
        assert "population_kind" not in method
        assert "scoring" not in method
        assert "n_repeats" not in method
        assert "random_seed" not in method


def test_analytical_visualizations_v3_artifact_is_produced(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    """Project Spec S0228: native continuous-regression training now
    materializes a real analytical-visualizations.v3 artifact and returns
    its repo-relative path/hash in TrainingResult -- superseding S0224's
    "no analytical visualizations" expectation."""
    result, output_directory = _run(fixed_training_environment, tmp_path)

    artifact_path = output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME
    assert artifact_path.exists()
    assert artifact_path.stat().st_size > 0
    assert result.analytical_visualizations_path == training._repo_relative_path(artifact_path)
    assert result.hashes["analytical_visualizations_sha256"] is not None
    assert result.hashes["analytical_visualizations_sha256"] == training._sha256_file(artifact_path)

    artifact = json.loads(artifact_path.read_text())
    assert artifact["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_ANALYTICAL_VISUALIZATIONS_VERSION
    assert artifact["artifact_kind"] == "analytical_visualizations"
    assert artifact["regression_evidence"] == {
        "problem_type": "continuous_regression",
        "result_semantics_schema_version": NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
        "output_value_kind": "continuous_numeric",
    }
    assert "classification_evidence" not in artifact
    assert "confusion_matrix" not in artifact

    chart_ids = {chart["id"] for chart in artifact["charts"]}
    assert chart_ids == {"target_distribution", "feature_importance"}

    target_distribution_method = artifact["target_distribution_method"]
    assert target_distribution_method["distribution_kind"] == "continuous_histogram"
    assert target_distribution_method["population_kind"] == "prepared_dataset"
    assert target_distribution_method["binning_method"] == "deterministic_equal_width"
    assert target_distribution_method["row_count"] == 150
    target_distribution_chart = next(c for c in artifact["charts"] if c["id"] == "target_distribution")
    assert sum(point["value"] for point in target_distribution_chart["data"]) == 150

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    final_test_row_count = metrics_artifact["final_test_evaluation"]["row_count"]

    actual_vs_predicted = artifact["actual_vs_predicted"]
    assert actual_vs_predicted["partition_role"] == "test"
    assert actual_vs_predicted["evaluation_count"] == 1
    assert actual_vs_predicted["reference_line"] == "identity"
    assert sum(point["count"] for point in actual_vs_predicted["points"]) == final_test_row_count
    for point in actual_vs_predicted["points"]:
        assert point["count"] >= 1
        for key in ("actual_mean", "predicted_mean"):
            assert point[key] == point[key]
            assert point[key] not in (float("inf"), float("-inf"))

    residual_distribution = artifact["residual_distribution"]
    assert residual_distribution["partition_role"] == "test"
    assert residual_distribution["evaluation_count"] == 1
    assert residual_distribution["residual_definition"] == "actual_minus_predicted"
    assert residual_distribution["binning_method"] == "deterministic_equal_width"
    assert sum(bin_["count"] for bin_ in residual_distribution["bins"]) == final_test_row_count
    for bin_ in residual_distribution["bins"]:
        assert bin_["count"] >= 0


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_analytical_visualizations_v3_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    jsonschema.validate(artifact, schema)


def test_analytical_visualizations_reuses_already_computed_final_test_predictions(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
) -> None:
    """Project Spec S0228: visualization generation must never call
    final_pipeline.predict a second time -- it reuses the single final-test
    prediction pass S0224 already performs."""
    from sklearn.pipeline import Pipeline

    original_predict = Pipeline.predict
    call_count = {"count": 0}

    def _counting_predict(self, features):
        call_count["count"] += 1
        return original_predict(self, features)

    monkeypatch.setattr(Pipeline, "predict", _counting_predict)

    _run(fixed_training_environment, tmp_path)

    # Exactly one predict call for the sealed final-test partition, plus one
    # for the descriptive validation-partition predict in Step 1 (S0224's
    # existing protocol) -- two total, never three.
    assert call_count["count"] == 2


def test_no_model_selection_evidence_artifact_is_produced(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    assert result.model_selection_evidence_path is None
    assert result.model_selection_evidence_produced is False
    assert result.hashes["model_selection_evidence_sha256"] is None
    assert not (output_directory / "model-selection-evidence.json").exists()


def test_r2_mae_rmse_are_finite_and_metrics_bounded_to_the_three(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, _ = _run(fixed_training_environment, tmp_path)

    assert set(result.metrics) == {"r2", "mae", "rmse"}
    for name, value in result.metrics.items():
        assert value == value  # not NaN
        assert value not in (float("inf"), float("-inf"))
        assert isinstance(value, float)


def test_final_fit_uses_train_plus_validation_and_test_evaluated_exactly_once(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    split_sizes = parameter_record["training_parameters"]["split_sizes"]
    assert split_sizes["final_fit_rows"] == split_sizes["training_rows"] + split_sizes["validation_rows"]
    assert parameter_record["training_parameters"]["validation_evaluation"]["used_for_model_selection"] is False
    assert (
        parameter_record["training_parameters"]["validation_evaluation"]["used_for_hyperparameter_selection"]
        is False
    )
    assert parameter_record["training_parameters"]["final_test"]["used_for_fitting"] is False
    assert parameter_record["training_parameters"]["final_test"]["used_for_model_selection"] is False
    assert parameter_record["training_parameters"]["final_test"]["evaluation_count"] == 1

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    final_test = metrics_artifact["final_test_evaluation"]
    assert final_test["sealed_before_finalization"] is True
    assert final_test["completed"] is True
    assert final_test["evaluation_count"] == 1
    assert final_test["used_for_fitting"] is False
    assert final_test["used_for_model_selection"] is False
    assert final_test["used_for_decision_rule_selection"] is False
    assert final_test["used_for_adjustment"] is False

    validation = metrics_artifact["validation_evaluation"]
    assert validation["used_for_model_selection"] is False
    assert validation["used_for_hyperparameter_selection"] is False
    assert validation["sealed_before_finalization"] is False


def test_no_classification_probability_or_threshold_fields_present(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    for forbidden in (
        "classification_evidence", "per_class_metrics", "confusion_matrix",
        "probability_columns", "threshold", "ordered_class_ids",
    ):
        assert forbidden not in metrics_artifact
        assert forbidden not in parameter_record
        assert forbidden not in metrics_artifact["validation_evaluation"]
        assert forbidden not in metrics_artifact["final_test_evaluation"]

    model_card_input = json.loads((output_directory / MODEL_CARD_INPUT_FILENAME).read_text())
    assert "class_distribution" not in model_card_input["dataset"]
    assert model_card_input["model"]["task_type"] == "continuous_regression"
    model_card = json.loads((output_directory / MODEL_CARD_FILENAME).read_text())
    assert model_card["problem_type"] == "continuous_regression"


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_parameter_record_v3_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert parameter_record["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_TRAINING_PARAMETER_RECORD_VERSION
    schema = json.loads(TRAINING_PARAMETER_RECORD_SCHEMA_PATH.read_text())
    jsonschema.validate(parameter_record, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_metrics_v3_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_artifact["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_TRAINING_METRICS_VERSION
    schema = json.loads(TRAINING_METRICS_SCHEMA_PATH.read_text())
    jsonschema.validate(metrics_artifact, schema)


def test_same_inputs_and_seed_produce_deterministic_split_and_hashes(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    first = train_from_paths(
        contract_path, dataset_path, dataset_slug="synthetic-regression-fixture", run_id="train-20260819T000000Z",
    )
    second = train_from_paths(
        contract_path, dataset_path, dataset_slug="synthetic-regression-fixture", run_id="train-20260819T000001Z",
    )
    assert first.train_indices == second.train_indices
    assert first.evaluation_indices == second.evaluation_indices
    assert first.hashes["model_artifact_sha256"] == second.hashes["model_artifact_sha256"]
    assert first.metrics == second.metrics


# ---------------------------------------------------------------------------
# Unit-level split/metric helper coverage
# ---------------------------------------------------------------------------


def test_random_three_way_split_partitions_are_disjoint_and_cover_all_rows() -> None:
    train, val, test = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    assert set(train) & set(val) == set()
    assert set(train) & set(test) == set()
    assert set(val) & set(test) == set()
    assert set(train) | set(val) | set(test) == set(range(150))
    assert train and val and test


def test_random_three_way_split_is_deterministic_under_seed() -> None:
    first = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    second = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    assert first == second


def test_native_continuous_regression_metric_names_are_the_bounded_three() -> None:
    assert set(NATIVE_CONTINUOUS_REGRESSION_METRIC_NAMES) == {"r2", "mae", "rmse"}


def test_native_continuous_regression_metric_values_computes_finite_r2_mae_rmse() -> None:
    y_true = [1.0, 2.0, 3.0, 4.0, 5.0]
    y_pred = [1.1, 1.9, 3.2, 3.8, 5.3]
    values = _native_continuous_regression_metric_values(
        y_true=y_true, y_pred=y_pred, metric_names=["r2", "mae", "rmse"],
    )
    assert set(values) == {"r2", "mae", "rmse"}
    for value in values.values():
        assert value == value and value not in (float("inf"), float("-inf"))


def test_native_continuous_regression_metric_values_never_calls_predict_proba(monkeypatch) -> None:
    class _NoProbaModel:
        def predict(self, _features):
            return [1.0, 2.0, 3.0]

    model = _NoProbaModel()
    assert not hasattr(model, "predict_proba")
    values = _native_continuous_regression_metric_values(
        y_true=[1.0, 2.0, 3.0], y_pred=model.predict(None), metric_names=["r2", "mae", "rmse"],
    )
    assert set(values) == {"r2", "mae", "rmse"}


def test_native_continuous_regression_metric_values_rejects_non_finite_predictions() -> None:
    with pytest.raises(TrainingInputError):
        _native_continuous_regression_metric_values(
            y_true=[1.0, 2.0, 3.0],
            y_pred=[1.0, float("nan"), 3.0],
            metric_names=["r2"],
        )


def test_validate_fixed_continuous_regression_configuration_accepts_gradient_boosting() -> None:
    model_family, hyperparameters = _validate_fixed_continuous_regression_configuration(
        {
            "allowed_model_families": ["gradient_boosting"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "gradient_boosting",
                "hyperparameters": _gbr_hyperparameters(),
            },
        }
    )
    assert model_family == "gradient_boosting"
    assert hyperparameters["n_estimators"] == 60


def test_validate_fixed_continuous_regression_configuration_accepts_random_forest() -> None:
    model_family, hyperparameters = _validate_fixed_continuous_regression_configuration(
        {
            "allowed_model_families": ["random_forest"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "random_forest",
                "hyperparameters": _rfr_hyperparameters(),
            },
        }
    )
    assert model_family == "random_forest"


def test_validate_fixed_continuous_regression_configuration_accepts_hist_gradient_boosting() -> None:
    model_family, hyperparameters = _validate_fixed_continuous_regression_configuration(
        {
            "allowed_model_families": ["hist_gradient_boosting"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": _hgb_regression_hyperparameters(),
            },
        }
    )
    assert model_family == "hist_gradient_boosting"
    assert hyperparameters["max_iter"] == 60
    assert "class_weight" not in hyperparameters
    assert "random_state" not in hyperparameters


def test_validate_fixed_continuous_regression_configuration_rejects_class_weight_for_hgb() -> None:
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["class_weight"] = None
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["hist_gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "hist_gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_validate_fixed_continuous_regression_configuration_rejects_random_state_for_hgb() -> None:
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["random_state"] = 7
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["hist_gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "hist_gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_validate_fixed_continuous_regression_configuration_rejects_missing_required_hgb_field() -> None:
    hyperparameters = _hgb_regression_hyperparameters()
    del hyperparameters["learning_rate"]
    with pytest.raises(TrainingInputError):
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["hist_gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "hist_gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )


def test_validate_fixed_continuous_regression_configuration_rejects_unsupported_family() -> None:
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["logistic_regression"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "logistic_regression",
                    "hyperparameters": {},
                },
            }
        )
    assert excinfo.value.code == "unsupported_model_family"


def test_validate_fixed_continuous_regression_configuration_rejects_unknown_hyperparameter() -> None:
    hyperparameters = _gbr_hyperparameters()
    hyperparameters["random_state"] = 1
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_validate_fixed_continuous_regression_configuration_rejects_missing_required_field() -> None:
    hyperparameters = _gbr_hyperparameters()
    del hyperparameters["learning_rate"]
    with pytest.raises(TrainingInputError):
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )


# ---------------------------------------------------------------------------
# Fail-closed coverage
# ---------------------------------------------------------------------------


def test_unsupported_result_semantics_fails_closed_for_fixed_configuration(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    del contract["result_semantics"]
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_fixed_configuration_result_semantics"


def test_evaluate_allowed_families_continuous_regression_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["modeling_constraints"] = {
        "allowed_model_families": ["gradient_boosting"],
        "no_automl": True,
    }
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_continuous_regression_model_selection"


def test_validated_external_fitted_model_fails_before_fitting(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["model_source_mode"] = "validated_external_fitted_model"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "external_fitted_model_not_trainable_by_atlas"


def test_non_numeric_target_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = "not-a-number"
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_missing_target_value_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = None
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_non_finite_target_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = float("inf")
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_unknown_regression_hyperparameter_fails_closed_end_to_end(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    hyperparameters = _gbr_hyperparameters()
    hyperparameters["random_state"] = 5
    contract = _fixed_continuous_regression_contract(hyperparameters=hyperparameters)
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_hist_gradient_boosting_class_weight_fails_closed_end_to_end(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    hyperparameters = _hgb_regression_hyperparameters()
    hyperparameters["class_weight"] = None
    contract = _fixed_continuous_regression_contract(
        model_family="hist_gradient_boosting", hyperparameters=hyperparameters,
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_zero_val_ratio_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["split_policy"] = {"strategy": "random", "train_ratio": 0.85, "val_ratio": 0.0, "test_ratio": 0.15}
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_split_policy"


def test_stratified_split_strategy_fails_closed_for_continuous_regression(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["split_policy"] = {"strategy": "stratified", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15}
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_split_policy"
