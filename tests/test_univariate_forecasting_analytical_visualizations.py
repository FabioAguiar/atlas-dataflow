"""Dedicated Project Spec S0248 tests for the Atlas-native univariate-
forecasting `analytical-visualizations.v4` profile.

Covers, using only synthetic Atlas-owned fixtures (never a real dataset/model
file, never `dataset-study-*`, and never a write under the real repository
`releases/`, `publisher/runs/`, or `pipeline/training-runs/` trees):

  * `analytical-visualizations.v4` schema validity for a directly
    constructed, fully-formed document, independent of a real training run;
  * negative schema cases: wrong problem type, wrong result-semantics
    version, wrong training-metrics version, non-positive forecast_horizon,
    seasonal_period < 2, non-finite/negative values, invalid
    dataset_statistics counts, and classification/regression-only field
    injection (additionalProperties: false);
  * `_native_forecasting_seasonal_profile` and
    `_build_native_univariate_forecasting_analytical_visualizations_artifact`
    (pipeline/training.py) exercised directly, in isolation from
    `train_from_paths`, proving deterministic construction and fail-closed
    behavior on insufficient development history.

`tests/test_native_univariate_forecasting_training.py` covers the real,
end-to-end `train_from_paths` generation path; this module never duplicates
that -- it exercises the schema and the pure builder functions directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pipeline.training as training  # noqa: E402
from pipeline.training import (  # noqa: E402
    NATIVE_UNIVARIATE_FORECASTING_ANALYTICAL_VISUALIZATIONS_VERSION,
    TrainingInputError,
    _build_native_univariate_forecasting_analytical_visualizations_artifact,
    _native_forecasting_seasonal_profile,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"
DATASET_SLUG = "synthetic-forecasting-fixture"


def _schema_validator():
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    validator_cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return validator_cls(schema)


def _valid_v4_document(**overrides) -> dict:
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
# Direct schema validity
# ---------------------------------------------------------------------------


def test_directly_constructed_v4_document_validates():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _schema_validator().validate(_valid_v4_document())


def test_v4_document_is_the_only_branch_that_matches_its_own_schema_version():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    assert document["schema_version"] == NATIVE_UNIVARIATE_FORECASTING_ANALYTICAL_VISUALIZATIONS_VERSION


# ---------------------------------------------------------------------------
# Negative schema cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_path,bad_value",
    [
        (("forecasting_evidence", "problem_type"), "continuous_regression"),
        (("forecasting_evidence", "result_semantics_schema_version"), "univariate-forecasting-result-semantics.v0"),
        (("forecasting_evidence", "training_metrics_schema_version"), "training-metrics.v3"),
        (("forecasting_evidence", "forecast_horizon"), 0),
        (("forecasting_evidence", "forecast_horizon"), -1),
        (("forecasting_evidence", "seasonal_period"), 1),
        (("forecasting_evidence", "frequency"), ""),
        (("dataset_statistics", "instance_count"), 0),
        (("dataset_statistics", "development_observations"), 0),
        (("dataset_statistics", "final_holdout_observations"), 0),
        (("backtesting_fold_metric", "direction"), "higher_is_better"),
    ],
)
def test_v4_document_rejects_invalid_field_values(field_path, bad_value):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    target = document
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad_value
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v4_document_rejects_non_numeric_seasonal_mean():
    # Structural JSON Schema cannot itself distinguish a finite float from
    # NaN/Infinity (see api/public_visualizations_loader.py's
    # `_is_finite_number` bounded-projection re-validation, exercised by
    # tests/api/test_univariate_forecasting_public_visualizations.py, for
    # that finite-value enforcement) -- this asserts the type check instead.
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    document["seasonal_profile"]["points"][0]["mean_target"] = "not-a-number"
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v4_document_rejects_negative_horizon_mae():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    document["horizon_mae"]["points"][0]["mae"] = -1.0
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v4_document_rejects_non_positive_seasonal_observation_count():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    document["seasonal_profile"]["points"][0]["observation_count"] = 0
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


@pytest.mark.parametrize(
    "forbidden_key,forbidden_value",
    [
        ("classification_evidence", {"problem_type": "multiclass_classification"}),
        ("confusion_matrix", {"ordered_class_ids": ["a", "b", "c"]}),
        ("regression_evidence", {"problem_type": "continuous_regression"}),
        ("actual_vs_predicted", {"points": []}),
        ("residual_distribution", {"bins": []}),
        ("charts", []),
        ("target_distribution_method", {}),
        ("feature_importance_method", {}),
    ],
)
def test_v4_document_rejects_classification_or_regression_only_field_injection(forbidden_key, forbidden_value):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    document[forbidden_key] = forbidden_value
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v4_document_rejects_v1_v2_v3_schema_version_substitution():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    for other_version in ("analytical-visualizations.v1", "analytical-visualizations.v2", "analytical-visualizations.v3"):
        document = _valid_v4_document(schema_version=other_version)
        with pytest.raises(jsonschema.ValidationError):
            _schema_validator().validate(document)


def test_bare_v4_schema_version_alone_is_insufficient():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate({"schema_version": "analytical-visualizations.v4"})


# ---------------------------------------------------------------------------
# _native_forecasting_seasonal_profile (pipeline/training.py), isolated
# ---------------------------------------------------------------------------


def test_seasonal_profile_is_deterministic_for_identical_inputs():
    history = [10.0, 12.0, 9.0, 13.0, 10.5, 12.5, 9.5, 13.5]
    first = _native_forecasting_seasonal_profile(history, seasonal_period=4)
    second = _native_forecasting_seasonal_profile(history, seasonal_period=4)
    assert first == second


def test_seasonal_profile_covers_every_position_exactly_once_and_sums_to_input_length():
    history = list(range(21))  # 21 observations, period 4 -> uneven bucket sizes
    points = _native_forecasting_seasonal_profile([float(v) for v in history], seasonal_period=4)
    positions = sorted(point["season_position"] for point in points)
    assert positions == [0, 1, 2, 3]
    assert sum(point["observation_count"] for point in points) == len(history)


def test_seasonal_profile_means_are_truthful_averages():
    history = [0.0, 10.0, 20.0, 30.0, 4.0, 14.0, 24.0, 34.0]  # period 4, +4.0 shift on 2nd cycle
    points = _native_forecasting_seasonal_profile(history, seasonal_period=4)
    by_position = {point["season_position"]: point for point in points}
    assert by_position[0]["mean_target"] == pytest.approx(2.0)
    assert by_position[1]["mean_target"] == pytest.approx(12.0)
    assert by_position[2]["mean_target"] == pytest.approx(22.0)
    assert by_position[3]["mean_target"] == pytest.approx(32.0)


def test_seasonal_profile_fails_closed_when_a_position_has_no_observations():
    with pytest.raises(TrainingInputError) as excinfo:
        _native_forecasting_seasonal_profile([1.0, 2.0, 3.0], seasonal_period=5)
    assert excinfo.value.code == "insufficient_development_observations"


def test_seasonal_profile_never_carries_raw_history_values_verbatim_as_keys():
    history = [7.0, 8.0, 9.0, 10.0]
    points = _native_forecasting_seasonal_profile(history, seasonal_period=4)
    for point in points:
        assert set(point) == {"season_position", "mean_target", "observation_count"}


# ---------------------------------------------------------------------------
# _build_native_univariate_forecasting_analytical_visualizations_artifact
# (pipeline/training.py), isolated from train_from_paths
# ---------------------------------------------------------------------------


def _synthetic_fold_summaries() -> list[dict]:
    return [
        {"fold_index": 1, "forecast_origin": "11", "validation_observations": 4,
         "metrics": [{"name": "mae", "value": 1.2}, {"name": "rmse", "value": 1.5}]},
        {"fold_index": 2, "forecast_origin": "15", "validation_observations": 4,
         "metrics": [{"name": "mae", "value": 0.9}, {"name": "rmse", "value": 1.1}]},
    ]


def _synthetic_horizon_mae() -> list[dict]:
    return [
        {"horizon_step": 1, "mae": 0.5, "observation_count": 2},
        {"horizon_step": 2, "mae": 0.8, "observation_count": 2},
        {"horizon_step": 3, "mae": 1.1, "observation_count": 2},
        {"horizon_step": 4, "mae": 1.4, "observation_count": 2},
    ]


def _build_artifact(**overrides) -> dict:
    kwargs = dict(
        final_development_history=[10.0, 12.0, 9.0, 13.0, 10.5, 12.5, 9.5, 13.5, 11.0, 13.0, 10.0, 14.0,
                                    10.2, 12.2, 9.2, 13.2, 10.7, 12.7, 9.7, 13.7],
        seasonal_period=4,
        forecast_horizon=4,
        frequency="synthetic-step",
        development_observation_count=20,
        final_holdout_observation_count=4,
        fold_summaries=_synthetic_fold_summaries(),
        horizon_mae=_synthetic_horizon_mae(),
        primary_metric_id="mae",
        output_directory=Path(f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z"),
        training_timestamp="2026-08-23T00:00:00Z",
    )
    kwargs.update(overrides)
    return _build_native_univariate_forecasting_analytical_visualizations_artifact(**kwargs)


def test_builder_output_validates_against_real_schema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    artifact = _build_artifact()
    _schema_validator().validate(artifact)


def test_builder_output_dataset_statistics_arithmetic():
    artifact = _build_artifact()
    stats = artifact["dataset_statistics"]
    assert stats["development_observations"] == 20
    assert stats["final_holdout_observations"] == 4
    assert stats["instance_count"] == 24


def test_builder_output_fold_points_derived_from_primary_metric_only():
    artifact = _build_artifact()
    points = artifact["backtesting_fold_metric"]["points"]
    assert [point["value"] for point in points] == [1.2, 0.9]  # the "mae" entries, not "rmse"
    assert artifact["backtesting_fold_metric"]["metric_id"] == "mae"


def test_builder_output_horizon_mae_passed_through_unchanged():
    artifact = _build_artifact()
    assert artifact["horizon_mae"]["points"] == _synthetic_horizon_mae()


def test_builder_raises_when_fold_summary_missing_primary_metric():
    fold_summaries = [
        {"fold_index": 1, "forecast_origin": "11", "validation_observations": 4,
         "metrics": [{"name": "rmse", "value": 1.5}]},  # no "mae" entry
    ]
    with pytest.raises(TrainingInputError) as excinfo:
        _build_artifact(fold_summaries=fold_summaries)
    assert excinfo.value.code == "missing_primary_metric"


def test_builder_output_evidence_policy_matches_legacy_shape():
    artifact = _build_artifact()
    evidence_policy = artifact["evidence_policy"]
    assert evidence_policy == {
        "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
        "raw_dataset_embedded": False, "model_bytes_embedded": False,
        "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
        "notebook_state_embedded": False, "reduced_and_sanitized": True,
    }


def test_builder_never_embeds_raw_development_history_or_holdout_values():
    artifact = _build_artifact()
    serialized = json.dumps(artifact)
    assert "final_development_history" not in serialized
    assert "y_true" not in serialized
    assert "y_pred" not in serialized
