"""Focused tests for Atlas-native univariate forecasting training
(Project Spec S0244).

All fixtures are synthetic, dataset-neutral, and use only temporary
repository paths -- no UCI/GitHub fetch, no dataset-study-* path, no
external model bytes, and no Nottingham-specific slug/path/target/frequency/
horizon/metric value, matching the boundary already established by
tests/test_native_multiclass_training.py and
tests/test_native_continuous_regression_training.py.
"""

from __future__ import annotations

import csv
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training
from pipeline.training import (
    METRICS_ARTIFACT_FILENAME,
    MODEL_ARTIFACT_FILENAME,
    MODEL_SELECTION_EVIDENCE_FILENAME,
    NATIVE_UNIVARIATE_FORECASTING_TRAINING_METRICS_VERSION,
    NATIVE_UNIVARIATE_FORECASTING_TRAINING_PARAMETER_RECORD_VERSION,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _deterministic_seasonal_trend_design_matrix,
    _forecast_mae,
    _forecast_rmse,
    _forecast_seasonal_mase,
    _seasonal_mase_scale,
    train_from_paths,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REPO_ROOT = Path(__file__).parent.parent
TRAINING_PARAMETER_RECORD_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-parameter-record.schema.json"
TRAINING_METRICS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-metrics.schema.json"

SEASONAL_PERIOD = 4
DEV_OBSERVATIONS = 20
HOLDOUT_OBSERVATIONS = 4
FORECAST_HORIZON = 4
SEASONAL_EFFECT = [0.0, 2.0, -1.0, 3.0]


# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------


def _series_value(index: int, *, seasonal_period: int = SEASONAL_PERIOD) -> float:
    return 10.0 + 0.5 * index + SEASONAL_EFFECT[index % seasonal_period]


def _synthetic_rows(
    *,
    total: int = DEV_OBSERVATIONS + HOLDOUT_OBSERVATIONS,
    seasonal_period: int = SEASONAL_PERIOD,
) -> list[dict]:
    return [
        {"period": str(i), "value": f"{_series_value(i, seasonal_period=seasonal_period):.6f}"}
        for i in range(total)
    ]


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["period", "value"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixed_model_configuration(**overrides) -> dict:
    base = dict(
        include_intercept=True,
        linear_time_trend=True,
        seasonal_effects="additive_indicators",
        seasonal_period=SEASONAL_PERIOD,
        reference_season_position=0,
        trend_origin="development_start",
    )
    base.update(overrides)
    return base


def _finalization_policy(**overrides) -> dict:
    base = dict(
        backtesting_refit_each_fold=True,
        final_fit_scope="full_development",
        freeze_before_final_holdout_open=True,
        final_holdout_evaluation_count=1,
        final_holdout_used_for_adjustment=False,
        final_holdout_used_for_model_selection=False,
        no_retuning_after_final_holdout=True,
    )
    base.update(overrides)
    return base


def _fold_schedule() -> list[dict]:
    return [
        {
            "fold_index": 1, "training_observations": 12, "forecast_origin": "11",
            "validation_start": "12", "validation_end": "15", "validation_observations": 4,
        },
        {
            "fold_index": 2, "training_observations": 16, "forecast_origin": "15",
            "validation_start": "16", "validation_end": "19", "validation_observations": 4,
        },
    ]


def _execution_contract(**overrides) -> dict:
    primary_metric = overrides.pop(
        "primary_metric", {"metric_id": "mae", "direction": "lower_is_better"}
    )
    secondary_metrics = overrides.pop(
        "secondary_metrics",
        [
            {"metric_id": "rmse", "direction": "lower_is_better"},
            {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": SEASONAL_PERIOD},
        ],
    )
    fixed_model_configuration = overrides.pop("fixed_model_configuration", _fixed_model_configuration())
    contract = {
        "contract_version": "execution_contract.v2",
        "dataset_id": "synth-series",
        "problem_type": "univariate_forecasting",
        "target_column": "value",
        "time_index_column": "period",
        "index_value_kind": "ordinal_time",
        "frequency": "synthetic-step",
        "source_exogenous_predictors": "forbidden",
        "forecast_horizon": FORECAST_HORIZON,
        "temporal_evaluation": {
            "preparation_schema_version": "candidate-preparation-recipe.v2",
            "backtesting_mode": "expanding_window",
            "fold_count": 2,
            "final_holdout_prospectively_sealed": True,
            "final_holdout_used_for_backtesting": False,
            "final_holdout_used_for_model_selection": False,
            "random_shuffle_performed": False,
            "future_targets_used_for_fold_fit": False,
            "validation_targets_fed_back_within_fold": False,
            "preprocessing_fit_on_validation_or_future": False,
        },
        "evaluation_policy": {
            "primary_metric": primary_metric,
            "secondary_metrics": secondary_metrics,
        },
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1",
            "problem_type": "univariate_forecasting",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
        },
        "training_policy": {
            "schema_version": "univariate-forecasting-training-policy.v1",
            "selection_mode": "fixed_configuration",
            "model_selection_performed": False,
            "model_family": "deterministic_seasonal_trend_ols",
            "fixed_model_configuration": fixed_model_configuration,
            "finalization_policy": _finalization_policy(),
        },
        "random_seed": None,
    }
    contract.update(overrides)
    return contract


def _preparation_recipe(**overrides) -> dict:
    fold_schedule = overrides.pop("fold_schedule", _fold_schedule())
    partitions = overrides.pop(
        "partitions",
        {
            "development": {
                "start_index_value": "0", "end_index_value": "19", "observation_count": DEV_OBSERVATIONS,
            },
            "sealed_final_holdout": {
                "start_index_value": "20", "end_index_value": "23",
                "observation_count": HOLDOUT_OBSERVATIONS,
                "prospectively_sealed": True, "used_for_backtesting": False,
                "used_for_model_selection": False,
            },
        },
    )
    recipe = {
        "schema_version": "candidate-preparation-recipe.v2",
        "producer": "test-fixture",
        "problem_type": "univariate_forecasting",
        "discovery_evidence_ref": {"path": "discovery.json", "schema_version": "dataset-discovery-evidence.v1"},
        "semantic_intent_ref": {
            "path": "semantic-intent.json", "schema_version": "dataset-semantic-intent.v4", "sha256": "a" * 64,
        },
        "semantic_identity_mirror": {
            "time_index_field_name": "period", "target_field_name": "value",
            "index_value_kind": "ordinal_time", "frequency": "synthetic-step",
        },
        "temporal_integrity": {
            "strictly_increasing_index": True, "unique_index": True, "frequency_contiguous": True,
            "target_missing_values_absent": True, "target_values_finite": True,
        },
        "forecast_horizon": FORECAST_HORIZON,
        "partitions": partitions,
        "backtesting": {
            "mode": "expanding_window", "initial_training_observations": 12,
            "forecast_horizon": FORECAST_HORIZON, "origin_step_observations": 4,
            "fold_count": 2, "validation_targets_overlap": False,
        },
        "fold_schedule": fold_schedule,
        "leakage_controls": {
            "random_shuffle_performed": False, "future_targets_used_for_fold_fit": False,
            "final_holdout_used_for_backtesting": False, "final_holdout_used_for_model_selection": False,
            "validation_targets_fed_back_within_fold": False,
            "preprocessing_fit_on_validation_or_future": False,
        },
        "preparation_boundary_confirmations": {
            "model_training_performed": False, "release_publication_performed": False,
            "hidden_notebook_transformations": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True, "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True, "private_source_paths_prohibited": True, "reduced_and_sanitized": True,
        },
        "generated_at": "2026-01-01T00:00:00Z",
    }
    recipe.update(overrides)
    return recipe


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    return repo_root


def _write_valid_inputs(
    tmp_path: Path,
    *,
    rows: list[dict] | None = None,
    contract_overrides: dict | None = None,
    recipe_overrides: dict | None = None,
) -> tuple[Path, Path, Path]:
    dataset_path = _write_csv(tmp_path / "series.csv", rows if rows is not None else _synthetic_rows())
    contract_path = _write_json(
        tmp_path / "execution-contract.json", _execution_contract(**(contract_overrides or {}))
    )
    recipe_path = _write_json(
        tmp_path / "preparation-recipe.json", _preparation_recipe(**(recipe_overrides or {}))
    )
    return contract_path, recipe_path, dataset_path


def _run(
    fixed_training_environment: Path,
    tmp_path: Path,
    *,
    rows: list[dict] | None = None,
    contract_overrides: dict | None = None,
    recipe_overrides: dict | None = None,
    run_id: str = "train-20260101T000000Z",
):
    contract_path, recipe_path, dataset_path = _write_valid_inputs(
        tmp_path, rows=rows, contract_overrides=contract_overrides, recipe_overrides=recipe_overrides
    )
    result = train_from_paths(
        contract_path,
        dataset_path,
        preparation_recipe_path=recipe_path,
        dataset_slug="synth-series",
        run_id=run_id,
    )
    output_directory = fixed_training_environment / result.output_directory
    return result, output_directory


# ---------------------------------------------------------------------------
# End-to-end valid training run
# ---------------------------------------------------------------------------


def test_valid_deterministic_seasonal_trend_ols_training_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    assert result.status == "trained"
    assert result.model_family == "deterministic_seasonal_trend_ols"
    assert result.task_type == "univariate_forecasting"
    assert result.feature_columns == []
    assert (output_directory / MODEL_ARTIFACT_FILENAME).exists()
    assert (output_directory / METRICS_ARTIFACT_FILENAME).exists()
    assert (output_directory / TRAINING_PARAMETER_RECORD_FILENAME).exists()
    assert not (output_directory / MODEL_SELECTION_EVIDENCE_FILENAME).exists()
    for metric_name in ("mae", "rmse", "seasonal_mase"):
        assert result.metrics[metric_name] == pytest.approx(0.0, abs=1e-6)


def test_explicit_preparation_recipe_path_required(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract_path, _recipe_path, dataset_path = _write_valid_inputs(tmp_path)
    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(
            contract_path, dataset_path, dataset_slug="synth-series", run_id="train-20260101T000000Z",
        )
    assert excinfo.value.code == "missing_required_input"
    assert excinfo.value.field == "preparation_recipe_path"


@pytest.mark.parametrize(
    "contract_field,value",
    [
        ("target_column", "other_value"),
        ("time_index_column", "other_period"),
        ("frequency", "other-frequency"),
        ("forecast_horizon", 3),
    ],
)
def test_execution_preparation_identity_mismatch_fails_before_fit(
    fixed_training_environment: Path, tmp_path: Path, contract_field, value,
) -> None:
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract_overrides={contract_field: value})
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists() or not any(
        (fixed_training_environment / "pipeline" / "training-runs").rglob(MODEL_ARTIFACT_FILENAME)
    )


def test_time_index_missing_value_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[5]["period"] = ""
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_time_index_duplicate_value_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[5]["period"] = rows[4]["period"]
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_time_index_out_of_order_fails_and_is_never_auto_sorted(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    rows = _synthetic_rows()
    rows[3], rows[4] = rows[4], rows[3]
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_target_missing_value_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[2]["value"] = ""
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_target_non_numeric_value_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[2]["value"] = "not-a-number"
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_target_non_finite_value_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[2]["value"] = "nan"
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, rows=rows)


def test_development_holdout_boundary_mismatch_fails(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    bad_partitions = {
        "development": {"start_index_value": "0", "end_index_value": "18", "observation_count": 19},
        "sealed_final_holdout": {
            "start_index_value": "19", "end_index_value": "23", "observation_count": 5,
            "prospectively_sealed": True, "used_for_backtesting": False, "used_for_model_selection": False,
        },
    }
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, recipe_overrides={"partitions": bad_partitions})


def test_fold_schedule_mismatch_fails(fixed_training_environment: Path, tmp_path: Path) -> None:
    bad_schedule = _fold_schedule()
    bad_schedule[0]["forecast_origin"] = "999"
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, recipe_overrides={"fold_schedule": bad_schedule})


def test_no_shuffle_deterministic_repeatability(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result_a, output_a = _run(fixed_training_environment, tmp_path, run_id="train-20260101T000000Z")
    result_b, output_b = _run(fixed_training_environment, tmp_path, run_id="train-20260101T000001Z")
    assert result_a.metrics == result_b.metrics
    metrics_a = json.loads((output_a / METRICS_ARTIFACT_FILENAME).read_text())
    metrics_b = json.loads((output_b / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_a["backtesting_evaluation"]["fold_summaries"] == metrics_b["backtesting_evaluation"]["fold_summaries"]


def test_fresh_fit_per_fold_and_final_fit_estimator_count(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
) -> None:
    from sklearn.linear_model import LinearRegression

    fit_calls = []
    original_fit = LinearRegression.fit

    def _counting_fit(self, X, y):
        fit_calls.append(id(self))
        return original_fit(self, X, y)

    monkeypatch.setattr(LinearRegression, "fit", _counting_fit)
    _run(fixed_training_environment, tmp_path)
    # 2 folds + 1 final development fit = 3 fit calls, on 3 distinct estimator instances.
    assert len(fit_calls) == 3
    assert len(set(fit_calls)) == 3


def test_no_retune_or_refit_after_holdout(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
) -> None:
    from sklearn.linear_model import LinearRegression

    fit_call_count = {"n": 0}
    original_fit = LinearRegression.fit

    def _counting_fit(self, X, y):
        fit_call_count["n"] += 1
        return original_fit(self, X, y)

    monkeypatch.setattr(LinearRegression, "fit", _counting_fit)
    result, _output_directory = _run(fixed_training_environment, tmp_path)
    assert result.metrics
    # Fit is called exactly 3 times total (2 folds + 1 final) -- reading
    # holdout metrics afterward never triggers a fourth call.
    assert fit_call_count["n"] == 3


def test_no_model_selection_only_one_family_ever_constructed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, _output_directory = _run(fixed_training_environment, tmp_path)
    assert result.model_selection_evidence_produced is False
    assert result.model_selection_evidence_path is None


def test_forecast_computed_before_validation_target_access_source_order() -> None:
    source = inspect.getsource(
        training._train_native_univariate_forecasting_fixed_configuration
    )
    fold_loop_start = source.index("for fold in ordered_fold_schedule:")
    predict_call_index = source.index(
        "fold_model.predict(forecast_design_matrix)", fold_loop_start
    )
    validation_target_read_index = source.index(
        "y_true = [float(rows[i][target_column]) for i in validation_positions]", fold_loop_start
    )
    assert predict_call_index < validation_target_read_index

    holdout_predict_index = source.index(
        "final_model.predict(holdout_design_matrix)", fold_loop_start
    )
    holdout_target_read_index = source.index(
        "y_true_holdout = [float(rows[i][target_column]) for i in holdout_positions]",
        fold_loop_start,
    )
    assert holdout_predict_index < holdout_target_read_index


def test_no_validation_feedback_within_fold_design_matrix_independent_of_targets() -> None:
    source = inspect.getsource(_deterministic_seasonal_trend_design_matrix)
    # The design matrix builder takes only integer positions -- never a
    # target/value array -- so it structurally cannot read validation
    # targets while constructing a forecast's inputs.
    assert "positions" in source
    assert "target" not in source


def test_final_holdout_never_used_during_backtesting(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    # A recipe that (incorrectly) lets a fold's window reach into the
    # holdout partition must fail closed before any fit.
    bad_schedule = _fold_schedule()
    bad_schedule[1]["training_observations"] = 18
    bad_schedule[1]["validation_start"] = "18"
    bad_schedule[1]["forecast_origin"] = "17"
    bad_schedule[1]["validation_observations"] = 6
    bad_schedule[1]["validation_end"] = "23"
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, recipe_overrides={"fold_schedule": bad_schedule})


# ---------------------------------------------------------------------------
# Metric correctness
# ---------------------------------------------------------------------------


def test_mae_correctness() -> None:
    assert _forecast_mae([10.0, 20.0, 30.0], [12.0, 18.0, 33.0]) == pytest.approx((2 + 2 + 3) / 3)


def test_rmse_correctness() -> None:
    import math

    value = _forecast_rmse([10.0, 20.0], [13.0, 16.0])
    assert value == pytest.approx(math.sqrt((9 + 16) / 2))


def test_seasonal_mase_fold_local_denominator() -> None:
    training_history = [10.0, 11.0, 9.5, 12.0, 10.4, 11.7, 9.1, 12.9]
    value, scale = _forecast_seasonal_mase([10.5], [11.0], training_history, seasonal_period=4)
    expected_scale = _seasonal_mase_scale(training_history, 4)
    assert scale == pytest.approx(expected_scale)
    assert value == pytest.approx(abs(10.5 - 11.0) / expected_scale)


def test_seasonal_mase_final_development_denominator_differs_from_fold_local() -> None:
    # An irregular (non-constant-diff) history: the fold-local window
    # (first 12 points) and the full final-development window (all 20
    # points) cover different seasonal-difference samples, so their
    # seasonal_mase scales are provably distinct for this fixture.
    irregular_history = [
        10.0, 11.0, 9.0, 12.5, 10.4, 11.9, 9.3, 12.1, 10.9, 11.2, 9.6, 12.8,
        10.2, 11.6, 9.9, 12.3, 10.7, 11.1, 9.4, 12.6,
    ]
    fold_scale = _seasonal_mase_scale(irregular_history[:12], SEASONAL_PERIOD)
    final_scale = _seasonal_mase_scale(irregular_history[:DEV_OBSERVATIONS], SEASONAL_PERIOD)
    assert fold_scale != pytest.approx(final_scale)


def test_invalid_mase_denominator_fails_closed() -> None:
    with pytest.raises(TrainingInputError):
        _seasonal_mase_scale([1.0, 2.0, 3.0], seasonal_period=4)


def test_horizon_wise_mae_ordered_by_horizon_step(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_doc = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    horizon_mae = metrics_doc["backtesting_evaluation"]["horizon_mae"]
    steps = [entry["horizon_step"] for entry in horizon_mae]
    assert steps == sorted(steps)
    assert steps == [1, 2, 3, 4]
    for entry in horizon_mae:
        assert entry["observation_count"] == 2  # one point per fold at this horizon step


def test_pooled_backtesting_metrics_computed_from_all_forecast_points(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_doc = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    backtesting_evaluation = metrics_doc["backtesting_evaluation"]
    assert backtesting_evaluation["forecast_count"] == 8  # 2 folds x 4 validation observations


# ---------------------------------------------------------------------------
# Final fit / holdout
# ---------------------------------------------------------------------------


def test_fresh_final_development_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    result, _output_directory = _run(fixed_training_environment, tmp_path)
    assert result.train_indices == list(range(DEV_OBSERVATIONS))


def test_final_holdout_evaluated_exactly_once(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_doc = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    final_holdout = metrics_doc["final_holdout_evaluation"]
    assert final_holdout["evaluation_count"] == 1
    assert final_holdout["observation_count"] == HOLDOUT_OBSERVATIONS
    assert final_holdout["model_frozen_before_open"] is True
    assert final_holdout["used_for_adjustment"] is False
    assert final_holdout["used_for_retuning"] is False
    assert final_holdout["used_for_model_selection"] is False


def test_final_forecast_has_exactly_forecast_horizon_finite_values(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, _output_directory = _run(fixed_training_environment, tmp_path)
    assert result.final_holdout_observations == FORECAST_HORIZON
    assert result.forecast_horizon == FORECAST_HORIZON


def test_model_artifact_is_atlas_owned_and_serialized(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    import joblib

    model_path = output_directory / MODEL_ARTIFACT_FILENAME
    assert model_path.exists()
    loaded = joblib.load(model_path)
    from sklearn.linear_model import LinearRegression

    assert isinstance(loaded, LinearRegression)


# ---------------------------------------------------------------------------
# Evidence schema validation
# ---------------------------------------------------------------------------


def test_training_parameter_record_v4_schema_valid(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    result, output_directory = _run(fixed_training_environment, tmp_path)
    record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert record["schema_version"] == NATIVE_UNIVARIATE_FORECASTING_TRAINING_PARAMETER_RECORD_VERSION
    schema = json.loads(TRAINING_PARAMETER_RECORD_SCHEMA_PATH.read_text())
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema).validate(record)
    assert record["training_parameters"]["model_selection_performed"] is False
    assert record["training_parameters"]["selection_mode"] == "fixed_configuration"


def test_training_metrics_v4_schema_valid(fixed_training_environment: Path, tmp_path: Path) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_doc = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_doc["schema_version"] == NATIVE_UNIVARIATE_FORECASTING_TRAINING_METRICS_VERSION
    schema = json.loads(TRAINING_METRICS_SCHEMA_PATH.read_text())
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema).validate(metrics_doc)


def test_no_model_selection_evidence_written(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _result, output_directory = _run(fixed_training_environment, tmp_path)
    assert not (output_directory / MODEL_SELECTION_EVIDENCE_FILENAME).exists()


def test_no_analytical_visualizations_written(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    assert result.analytical_visualizations_path is None
    assert result.model_card_path is None
    assert result.model_card_input_path is None
    assert not (output_directory / "analytical-visualizations.json").exists()
    assert not (output_directory / "model-card.json").exists()
    assert not (output_directory / "model-card-input.json").exists()


def test_no_external_study_access(fixed_training_environment: Path, tmp_path: Path) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    record_text = (output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text()
    metrics_text = (output_directory / METRICS_ARTIFACT_FILENAME).read_text()
    for forbidden in ("nottem", "nottingham", "dataset-study", "statsmodels"):
        assert forbidden not in record_text.lower()
        assert forbidden not in metrics_text.lower()


def test_historical_training_result_construction_remains_compatible() -> None:
    """A light backward-compat smoke check: a non-forecasting TrainingResult
    still constructs and summarizes exactly as before S0244."""
    result = training.TrainingResult(
        status="trained",
        model=None,
        model_family="logistic_regression",
        task_type="classification",
        train_indices=[0, 1],
        evaluation_indices=[2, 3],
        dataset_id="legacy-fixture",
        target_column="target",
        feature_columns=["a", "b"],
        primary_metric="roc_auc",
        output_directory="pipeline/training-runs/legacy-fixture/train-20260101T000000Z/",
        serialized_model_path="model.pkl",
        training_parameter_record_path="training-parameter-record.json",
        metrics_path="metrics.json",
        model_selection_evidence_path=None,
        model_card_input_path="model-card-input.json",
        model_card_path="model-card.json",
        analytical_visualizations_path="analytical-visualizations.json",
        serializer_name="joblib",
        serializer_version="1.0.0",
        serialization_format_version="joblib-1.0.0",
        training_timestamp="2026-01-01T00:00:00Z",
        hashes={},
        metrics={"roc_auc": 0.9},
        model_selection_evidence_produced=False,
    )
    summary = result.to_summary()
    assert summary["model_card_input_produced"] is True
    assert summary["model_card_produced"] is True
    assert "forecasting_evidence" not in summary
