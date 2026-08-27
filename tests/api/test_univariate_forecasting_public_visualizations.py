"""Dedicated Project Spec S0248 tests for the public visualizations loader's
`analytical-visualizations.v4` native univariate-forecasting projection
(`api/public_visualizations_loader.py`).

Covers, using only synthetic temporary release packages (never a real
release, never `dataset-study-*`):

  * a bounded, well-formed public v4 projection -- `dataset_statistics` and
    `forecasting_diagnostics` (forecast_horizon, frequency, seasonal_profile,
    backtesting_fold_metric, horizon_mae), and never a `charts` array with
    content;
  * no internal path/hash/provenance/model leakage;
  * malformed v4 evidence fails closed to the existing bounded unavailable
    state, never a partial/unsafe projection;
  * v1/v2/v3 public projection remains fully backward compatible and never
    carries the v4-only `forecasting_diagnostics` field.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import public_visualizations_loader as loader  # noqa: E402

DATASET_SLUG = "synthetic-forecasting-release"


def _write_release(releases_root: Path, release_name: str, visualizations_artifact: dict) -> Path:
    release_dir = releases_root / release_name
    artifact_path = release_dir / "visualizations" / "visualizations.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(visualizations_artifact), encoding="utf-8")

    manifest = {
        "artifacts": [{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return release_dir


def _valid_v4_artifact(**overrides) -> dict:
    payload = {
        "schema_version": "analytical-visualizations.v4",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-23T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260823T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z/",
        },
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "training_metrics_schema_version": "training-metrics.v4",
            "forecast_horizon": 4,
            "frequency": "synthetic-step",
            "seasonal_period": 4,
        },
        "dataset_statistics": {
            "instance_count": 24,
            "development_observations": 20,
            "final_holdout_observations": 4,
        },
        "seasonal_profile": {
            "population_kind": "full_development",
            "seasonal_period": 4,
            "points": [
                {"season_position": 0, "mean_target": 10.0, "observation_count": 5},
                {"season_position": 1, "mean_target": 12.0, "observation_count": 5},
                {"season_position": 2, "mean_target": 9.0, "observation_count": 5},
                {"season_position": 3, "mean_target": 13.0, "observation_count": 5},
            ],
        },
        "backtesting_fold_metric": {
            "metric_id": "mae",
            "direction": "lower_is_better",
            "fold_count": 2,
            "points": [
                {"fold_index": 1, "forecast_origin": "11", "value": 1.2, "validation_observations": 4},
                {"fold_index": 2, "forecast_origin": "15", "value": 0.9, "validation_observations": 4},
            ],
        },
        "horizon_mae": {
            "points": [
                {"horizon_step": 1, "mae": 0.5, "observation_count": 2},
                {"horizon_step": 2, "mae": 0.8, "observation_count": 2},
                {"horizon_step": 3, "mae": 1.1, "observation_count": 2},
                {"horizon_step": 4, "mae": 1.4, "observation_count": 2},
            ],
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


# ---------------------------------------------------------------------------
# Bounded, well-formed public v4 projection
# ---------------------------------------------------------------------------


def test_v4_projection_contains_dataset_statistics_and_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-001", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-001", releases_root=releases_root)

        assert projection["charts"] == []
        assert projection["dataset_statistics"] == {"instance_count": 24}
        diagnostics = projection["forecasting_diagnostics"]
        assert diagnostics["forecast_horizon"] == 4
        assert diagnostics["frequency"] == "synthetic-step"


def test_v4_seasonal_profile_projection_is_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-002", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-002", releases_root=releases_root)

        seasonal_profile = projection["forecasting_diagnostics"]["seasonal_profile"]
        assert seasonal_profile["seasonal_period"] == 4
        assert [point["season_position"] for point in seasonal_profile["points"]] == [0, 1, 2, 3]
        for point in seasonal_profile["points"]:
            assert set(point) == {"season_position", "mean_target", "observation_count"}


def test_v4_fold_primary_metric_projection_is_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-003", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-003", releases_root=releases_root)

        fold_metric = projection["forecasting_diagnostics"]["backtesting_fold_metric"]
        assert fold_metric["metric_id"] == "mae"
        assert fold_metric["direction"] == "lower_is_better"
        assert [point["fold_index"] for point in fold_metric["points"]] == [1, 2]
        for point in fold_metric["points"]:
            assert set(point) == {"fold_index", "forecast_origin", "value"}


def test_v4_horizon_mae_projection_is_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-004", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-004", releases_root=releases_root)

        horizon_mae = projection["forecasting_diagnostics"]["horizon_mae"]
        assert [point["horizon_step"] for point in horizon_mae["points"]] == [1, 2, 3, 4]
        for point in horizon_mae["points"]:
            assert set(point) == {"horizon_step", "mae"}


def test_v4_projection_never_leaks_internal_path_hash_or_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-005", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-005", releases_root=releases_root)
        serialized = json.dumps(projection)

        for forbidden in (
            "training_run_identity", "output_directory", "run_id", "dataset_slug",
            "result_semantics_schema_version", "training_metrics_schema_version",
            "population_kind", "created_at", "evidence_policy",
        ):
            assert forbidden not in serialized


# ---------------------------------------------------------------------------
# Malformed v4 evidence fails closed
# ---------------------------------------------------------------------------


def test_v4_missing_seasonal_profile_fails_closed():
    artifact = _valid_v4_artifact()
    del artifact["seasonal_profile"]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-006", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-006", releases_root=releases_root)


def test_v4_wrong_problem_type_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["forecasting_evidence"]["problem_type"] = "continuous_regression"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-007", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-007", releases_root=releases_root)


def test_v4_duplicate_season_position_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["seasonal_profile"]["points"][1]["season_position"] = 0
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-008", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-008", releases_root=releases_root)


def test_v4_season_position_out_of_range_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["seasonal_profile"]["points"][0]["season_position"] = 99
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-009", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-009", releases_root=releases_root)


def test_v4_non_finite_seasonal_mean_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["seasonal_profile"]["points"][0]["mean_target"] = float("inf")
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-010", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-010", releases_root=releases_root)


def test_v4_wrong_direction_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["backtesting_fold_metric"]["direction"] = "higher_is_better"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-011", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-011", releases_root=releases_root)


def test_v4_duplicate_fold_index_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["backtesting_fold_metric"]["points"][1]["fold_index"] = 1
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-012", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-012", releases_root=releases_root)


def test_v4_negative_horizon_mae_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["horizon_mae"]["points"][0]["mae"] = -1.0
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-013", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-013", releases_root=releases_root)


def test_v4_duplicate_horizon_step_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["horizon_mae"]["points"][1]["horizon_step"] = 1
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-014", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-014", releases_root=releases_root)


def test_v4_zero_instance_count_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["dataset_statistics"]["instance_count"] = 0
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-015", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-015", releases_root=releases_root)


def test_v4_empty_seasonal_points_fails_closed():
    artifact = _valid_v4_artifact()
    artifact["seasonal_profile"]["points"] = []
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-016", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v4-016", releases_root=releases_root)


# ---------------------------------------------------------------------------
# v1/v2/v3 public projection regression safety
# ---------------------------------------------------------------------------


def _classification_v1_artifact() -> dict:
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-23T00:00:00Z",
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "Churn", "y_label": "Customers",
                "data": [{"name": "No", "value": 7}, {"name": "Yes", "value": 3}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "tenure", "value": 0.5}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset", "row_count": 10, "target_column": "Churn",
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }


def test_v1_projection_never_carries_forecasting_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v1-001", _classification_v1_artifact())

        projection = loader.load_public_visualizations("release-v1-001", releases_root=releases_root)

        assert [chart["id"] for chart in projection["charts"]] == ["target_distribution", "feature_importance"]
        assert "forecasting_diagnostics" not in projection


def test_v3_projection_never_carries_forecasting_diagnostics():
    v3_artifact = {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-23T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260823T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z/",
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
                "data": [{"name": "0 to 10", "value": 6}, {"name": "10 to 20", "value": 4}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "feature_a", "value": 0.9}],
            },
        ],
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 10,
            "target_column": "outcome",
            "bin_count": 2,
            "min_value": 1.0,
            "max_value": 19.0,
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test", "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width_actual_bins",
            "reference_line": "identity",
            "points": [{"actual_mean": 5.0, "predicted_mean": 5.4, "count": 3}],
        },
        "residual_distribution": {
            "partition_role": "test", "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [{"label": "-2 to 0", "lower_bound": -2.0, "upper_bound": 0.0, "count": 2}],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-001", v3_artifact)

        projection = loader.load_public_visualizations("release-v3-001", releases_root=releases_root)

        assert "forecasting_diagnostics" not in projection
        assert projection["target_distribution_kind"] == "continuous_histogram"


# ---------------------------------------------------------------------------
# Project Spec S0270: analytical-visualizations.v6 bounded public
# forecasting_evaluation projection
# ---------------------------------------------------------------------------


def _v6_final_holdout_evaluation(**overrides) -> dict:
    block = {
        "partition_role": "final_holdout",
        "evaluation_count": 1,
        "model_frozen_before_open": True,
        "forecast_generated_before_target_open": True,
        "index_value_kind": "calendar_period",
        "frequency": "synthetic-step",
        "development_boundary": {
            "start_index": "1920-01", "end_index": "1938-12", "observation_count": 20,
        },
        "final_holdout_boundary": {
            "start_index": "1939-01", "end_index": "1939-04", "observation_count": 4,
        },
        "points": [
            {"time_index": "1939-01", "actual": 3.1, "forecast": 3.4},
            {"time_index": "1939-02", "actual": 4.0, "forecast": 3.6},
            {"time_index": "1939-03", "actual": 6.2, "forecast": 6.0},
            {"time_index": "1939-04", "actual": 9.5, "forecast": 9.9},
        ],
    }
    block.update(overrides)
    return block


def _valid_v6_artifact(**overrides) -> dict:
    payload = _valid_v4_artifact()
    payload["schema_version"] = "analytical-visualizations.v6"
    payload["final_holdout_forecast_evaluation"] = _v6_final_holdout_evaluation()
    payload.update(overrides)
    return payload


def test_v6_projection_contains_dataset_statistics_diagnostics_and_evaluation():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v6-001", _valid_v6_artifact())

        projection = loader.load_public_visualizations("release-v6-001", releases_root=releases_root)

        assert projection["charts"] == []
        assert projection["dataset_statistics"] == {"instance_count": 24}
        assert projection["forecasting_diagnostics"]["forecast_horizon"] == 4
        evaluation = projection["forecasting_evaluation"]
        assert evaluation["index_value_kind"] == "calendar_period"
        assert evaluation["frequency"] == "synthetic-step"
        assert evaluation["development_boundary"] == {
            "start_index": "1920-01", "end_index": "1938-12", "observation_count": 20,
        }
        assert evaluation["final_holdout_boundary"] == {
            "start_index": "1939-01", "end_index": "1939-04", "observation_count": 4,
        }
        assert evaluation["evaluation"] == {
            "split_name": "final_holdout",
            "evaluation_count": 1,
            "model_frozen_before_open": True,
            "forecast_generated_before_target_open": True,
        }
        assert [point["time_index"] for point in evaluation["points"]] == [
            "1939-01", "1939-02", "1939-03", "1939-04",
        ]
        assert [point["actual"] for point in evaluation["points"]] == [3.1, 4.0, 6.2, 9.5]
        assert [point["forecast"] for point in evaluation["points"]] == [3.4, 3.6, 6.0, 9.9]
        for point in evaluation["points"]:
            assert set(point) == {"time_index", "actual", "forecast"}


def test_v6_projection_never_duplicates_metric_values_or_leaks_internals():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v6-002", _valid_v6_artifact())

        projection = loader.load_public_visualizations("release-v6-002", releases_root=releases_root)
        serialized = json.dumps(projection)
        for forbidden in (
            "training_run_identity", "output_directory", "run_id", "dataset_slug",
            "result_semantics_schema_version", "training_metrics_schema_version",
            "created_at", "evidence_policy", "final_holdout_forecast_evaluation",
        ):
            assert forbidden not in serialized

        # The bounded forecasting_evaluation block itself never carries a
        # scored metric value (MAE/RMSE/seasonal-MASE are owned by /metrics),
        # internal artifact field names, paths, hashes, or model state.
        evaluation_serialized = json.dumps(projection["forecasting_evaluation"])
        for forbidden in (
            "mae", "rmse", "seasonal_mase", "metrics", "partition_role",
            "training_run_identity", "output_directory", "sha256", "path", "population_kind",
        ):
            assert forbidden not in evaluation_serialized


def test_v4_projection_still_has_no_forecasting_evaluation():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v4-nfe", _valid_v4_artifact())

        projection = loader.load_public_visualizations("release-v4-nfe", releases_root=releases_root)

        assert "forecasting_evaluation" not in projection


@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a["final_holdout_forecast_evaluation"].pop("points"),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("points", a["final_holdout_forecast_evaluation"]["points"][:3]),
        lambda a: a["final_holdout_forecast_evaluation"]["points"][0].__setitem__("time_index", ""),
        lambda a: a["final_holdout_forecast_evaluation"]["points"][1].__setitem__("time_index", "1939-01"),
        lambda a: a["final_holdout_forecast_evaluation"]["points"][0].__setitem__("actual", True),
        lambda a: a["final_holdout_forecast_evaluation"]["points"][0].__setitem__("forecast", float("inf")),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("partition_role", "test"),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("evaluation_count", 2),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("model_frozen_before_open", False),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("forecast_generated_before_target_open", False),
        lambda a: a["final_holdout_forecast_evaluation"].__setitem__("index_value_kind", "slug_inferred"),
        lambda a: a["final_holdout_forecast_evaluation"]["final_holdout_boundary"].__setitem__("end_index", "1999-12"),
        lambda a: a["final_holdout_forecast_evaluation"]["final_holdout_boundary"].__setitem__("observation_count", 5),
        lambda a: a["final_holdout_forecast_evaluation"]["development_boundary"].__setitem__("observation_count", 99),
        lambda a: a.pop("final_holdout_forecast_evaluation"),
    ],
)
def test_v6_malformed_evaluation_fails_closed(mutation):
    artifact = _valid_v6_artifact()
    mutation(artifact)
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v6-bad", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v6-bad", releases_root=releases_root)


def test_v6_malformed_aggregate_diagnostic_still_fails_closed():
    artifact = _valid_v6_artifact()
    del artifact["seasonal_profile"]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v6-aggbad", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v6-aggbad", releases_root=releases_root)
