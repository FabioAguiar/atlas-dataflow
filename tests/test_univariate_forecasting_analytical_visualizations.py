"""Dedicated Project Spec S0248 / S0270 tests for the Atlas-native univariate-
forecasting `analytical-visualizations.v4` (historical) and
`analytical-visualizations.v6` (governed final-holdout evolution) profiles.

Covers, using only synthetic Atlas-owned fixtures (never a real dataset/model
file, never `dataset-study-*`, and never a write under the real repository
`releases/`, `publisher/runs/`, or `pipeline/training-runs/` trees):

  * `analytical-visualizations.v4` schema validity is preserved unchanged for
    a directly constructed, fully-formed historical document -- v4 stays
    aggregate-only and rejects the v6-only final-holdout block;
  * `analytical-visualizations.v6` schema validity for a fully synthetic,
    directly constructed document that retains every v4 aggregate diagnostic
    and adds exactly one bounded `final_holdout_forecast_evaluation` block;
  * negative schema cases for both branches: wrong problem type, wrong
    result-semantics version, wrong training-metrics version, non-positive
    forecast_horizon, seasonal_period < 2, non-finite/negative values,
    invalid dataset_statistics counts, classification/regression-only field
    injection (additionalProperties: false), and, for v6, wrong
    partition/evaluation/freeze/pre-target flags plus invalid
    boundary/count/point structures;
  * `_native_forecasting_seasonal_profile`,
    `_native_forecasting_final_holdout_forecast_evaluation`, and
    `_build_native_univariate_forecasting_analytical_visualizations_artifact`
    (pipeline/training.py) exercised directly, in isolation from
    `train_from_paths`, proving the pure builder now emits v6 with exact
    aligned synthetic evaluation points, never carries the development
    history vector or unrelated row data, and is deterministic for identical
    inputs.

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
    NATIVE_UNIVARIATE_FORECASTING_FINAL_HOLDOUT_MAX_POINTS,
    TrainingInputError,
    _build_native_univariate_forecasting_analytical_visualizations_artifact,
    _native_forecasting_final_holdout_forecast_evaluation,
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


def _v6_final_holdout_evaluation(**overrides) -> dict:
    block = {
        "partition_role": "final_holdout",
        "evaluation_count": 1,
        "model_frozen_before_open": True,
        "forecast_generated_before_target_open": True,
        "index_value_kind": "ordinal_time",
        "frequency": "synthetic-step",
        "development_boundary": {
            "start_index": "0", "end_index": "19", "observation_count": 20,
        },
        "final_holdout_boundary": {
            "start_index": "20", "end_index": "23", "observation_count": 4,
        },
        "points": [
            {"time_index": "20", "actual": 14.0, "forecast": 13.6},
            {"time_index": "21", "actual": 12.0, "forecast": 12.3},
            {"time_index": "22", "actual": 9.5, "forecast": 9.9},
            {"time_index": "23", "actual": 15.0, "forecast": 14.4},
        ],
    }
    block.update(overrides)
    return block


def _valid_v6_document(**overrides) -> dict:
    payload = _valid_v4_document()
    payload["schema_version"] = "analytical-visualizations.v6"
    payload["final_holdout_forecast_evaluation"] = _v6_final_holdout_evaluation()
    payload.update(overrides)
    return payload


def _metric_diagnostics(*, metric_ids=("mae", "rmse", "seasonal_mase"), forecast_horizon: int = 4) -> dict:
    return {
        "metrics": [
            {
                "metric_id": metric_id,
                "direction": "lower_is_better",
                "backtesting_by_origin": {
                    "fold_count": 2,
                    "points": [
                        {"fold_index": 1, "forecast_origin": "11", "value": 1.2, "validation_observations": 4},
                        {"fold_index": 2, "forecast_origin": "15", "value": 0.9, "validation_observations": 4},
                    ],
                },
                "by_horizon": {
                    "points": [
                        {"horizon_step": step, "value": round(0.3 * step, 4), "observation_count": 2}
                        for step in range(1, forecast_horizon + 1)
                    ],
                },
            }
            for metric_id in metric_ids
        ],
    }


def _valid_v7_document(**overrides) -> dict:
    payload = _valid_v6_document()
    payload["schema_version"] = "analytical-visualizations.v7"
    payload["forecasting_metric_diagnostics"] = _metric_diagnostics()
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Direct schema validity
# ---------------------------------------------------------------------------


def test_directly_constructed_v4_document_validates():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _schema_validator().validate(_valid_v4_document())


def test_directly_constructed_v6_document_validates():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _schema_validator().validate(_valid_v6_document())


def test_producer_identity_is_now_v7_and_v4_v6_remain_historical_branches():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    assert NATIVE_UNIVARIATE_FORECASTING_ANALYTICAL_VISUALIZATIONS_VERSION == "analytical-visualizations.v7"
    # v4 and v6 stay accepted, unchanged, as historical forecasting evidence.
    _schema_validator().validate(_valid_v4_document())
    _schema_validator().validate(_valid_v6_document())
    assert _valid_v7_document()["schema_version"] == NATIVE_UNIVARIATE_FORECASTING_ANALYTICAL_VISUALIZATIONS_VERSION


def test_v4_remains_aggregate_only_and_rejects_the_v6_only_final_holdout_block():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v4_document()
    document["final_holdout_forecast_evaluation"] = _v6_final_holdout_evaluation()
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v6_requires_the_final_holdout_forecast_evaluation_block():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v6_document()
    del document["final_holdout_forecast_evaluation"]
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v6_retains_every_v4_aggregate_diagnostic():
    document = _valid_v6_document()
    for key in ("forecasting_evidence", "dataset_statistics", "seasonal_profile",
                "backtesting_fold_metric", "horizon_mae", "evidence_policy"):
        assert key in document
    assert document["forecasting_evidence"] == _valid_v4_document()["forecasting_evidence"]


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("partition_role", "test"),
        ("partition_role", "development"),
        ("evaluation_count", 0),
        ("evaluation_count", 2),
        ("model_frozen_before_open", False),
        ("forecast_generated_before_target_open", False),
        ("index_value_kind", "slug_inferred"),
        ("frequency", ""),
    ],
)
def test_v6_rejects_wrong_partition_evaluation_freeze_or_pre_target_flags(field, bad_value):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v6_document(
        final_holdout_forecast_evaluation=_v6_final_holdout_evaluation(**{field: bad_value})
    )
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.__setitem__("points", []),
        lambda b: b["points"].append({"time_index": "24", "actual": 1.0, "forecast": 2.0, "residual": -1.0}),
        lambda b: b["points"][0].__setitem__("actual", True),
        lambda b: b["points"][0].__setitem__("time_index", ""),
        lambda b: b["points"][0].pop("forecast"),
        lambda b: b["development_boundary"].__setitem__("observation_count", 0),
        lambda b: b["final_holdout_boundary"].pop("end_index"),
        lambda b: b.__setitem__("unexpected_field", "x"),
    ],
)
def test_v6_rejects_invalid_boundary_count_or_point_structures(mutation):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    block = _v6_final_holdout_evaluation()
    mutation(block)
    document = _valid_v6_document(final_holdout_forecast_evaluation=block)
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


# ---------------------------------------------------------------------------
# Project Spec S0274: analytical-visualizations.v7 governed multi-metric
# backtesting/horizon diagnostic profile
# ---------------------------------------------------------------------------


def test_directly_constructed_v7_document_validates():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _schema_validator().validate(_valid_v7_document())


def test_v7_requires_the_forecasting_metric_diagnostics_block():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v7_document()
    del document["forecasting_metric_diagnostics"]
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v7_still_requires_every_v6_field_including_final_holdout_block():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    for removed in (
        "final_holdout_forecast_evaluation", "seasonal_profile", "backtesting_fold_metric",
        "horizon_mae", "dataset_statistics",
    ):
        document = _valid_v7_document()
        del document[removed]
        with pytest.raises(jsonschema.ValidationError):
            _schema_validator().validate(document)


def test_v7_retains_every_v6_diagnostic_unchanged():
    document = _valid_v7_document()
    v6 = _valid_v6_document()
    for key in ("forecasting_evidence", "dataset_statistics", "seasonal_profile",
                "backtesting_fold_metric", "horizon_mae", "final_holdout_forecast_evaluation",
                "evidence_policy"):
        assert document[key] == v6[key]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b["metrics"][0].__setitem__("metric_id", "mape"),
        lambda b: b["metrics"][0].__setitem__("direction", "higher_is_better"),
        lambda b: b["metrics"][0].__setitem__("unexpected", "x"),
        lambda b: b.__setitem__("metrics", []),
        lambda b: b.__setitem__("metrics", b["metrics"] + b["metrics"]),  # 6 entries > maxItems 3
        lambda b: b["metrics"][0]["backtesting_by_origin"]["points"][0].__setitem__("fold_index", -1),
        lambda b: b["metrics"][0]["backtesting_by_origin"]["points"][0].__setitem__("forecast_origin", ""),
        lambda b: b["metrics"][0]["backtesting_by_origin"]["points"][0].pop("validation_observations"),
        lambda b: b["metrics"][0]["backtesting_by_origin"]["points"][0].__setitem__("validation_observations", 0),
        lambda b: b["metrics"][0]["backtesting_by_origin"].pop("fold_count"),
        lambda b: b["metrics"][0]["by_horizon"]["points"][0].__setitem__("horizon_step", 0),
        lambda b: b["metrics"][0]["by_horizon"]["points"][0].__setitem__("value", -1.0),
        lambda b: b["metrics"][0]["by_horizon"]["points"][0].__setitem__("observation_count", 0),
        lambda b: b["metrics"][0]["by_horizon"]["points"][0].pop("value"),
    ],
)
def test_v7_rejects_malformed_metric_diagnostics(mutation):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    block = _metric_diagnostics()
    mutation(block)
    document = _valid_v7_document(forecasting_metric_diagnostics=block)
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v7_duplicate_metric_id_is_enforced_by_producer_not_structural_schema():
    # JSON Schema cannot express array-item uniqueness on a nested key; the
    # producer (_native_forecasting_metric_diagnostics) and publisher validation
    # enforce "no duplicate metric_id" -- see
    # tests/test_native_univariate_forecasting_training.py and
    # tests/test_univariate_forecasting_candidate_publisher.py.
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    block = _metric_diagnostics(metric_ids=("mae", "mae"))
    _schema_validator().validate(_valid_v7_document(forecasting_metric_diagnostics=block))


def test_v6_remains_valid_without_the_v7_only_field():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v6_document()
    assert "forecasting_metric_diagnostics" not in document
    _schema_validator().validate(document)


def test_v6_rejects_a_silently_injected_v7_only_field_because_it_remains_closed():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    document = _valid_v6_document()
    document["forecasting_metric_diagnostics"] = _metric_diagnostics()
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v4_remains_historical_and_rejects_the_v7_only_field():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    _schema_validator().validate(_valid_v4_document())
    document = _valid_v4_document()
    document["forecasting_metric_diagnostics"] = _metric_diagnostics()
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(document)


def test_v7_document_is_the_only_branch_that_matches_its_own_schema_version():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    for other_version in ("analytical-visualizations.v1", "analytical-visualizations.v2",
                          "analytical-visualizations.v3", "analytical-visualizations.v4",
                          "analytical-visualizations.v5", "analytical-visualizations.v6"):
        document = _valid_v7_document(schema_version=other_version)
        with pytest.raises(jsonschema.ValidationError):
            _schema_validator().validate(document)


def test_v6_document_is_the_only_branch_that_matches_its_own_schema_version():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    for other_version in ("analytical-visualizations.v1", "analytical-visualizations.v2",
                          "analytical-visualizations.v3", "analytical-visualizations.v4",
                          "analytical-visualizations.v5"):
        document = _valid_v6_document(schema_version=other_version)
        with pytest.raises(jsonschema.ValidationError):
            _schema_validator().validate(document)


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
        forecasting_metric_diagnostics=_metric_diagnostics(metric_ids=("mae", "rmse")),
        primary_metric_id="mae",
        final_holdout_labels=["20", "21", "22", "23"],
        y_true_holdout=[14.0, 12.0, 9.5, 15.0],
        holdout_forecast_vector=[13.6, 12.3, 9.9, 14.4],
        index_value_kind="ordinal_time",
        development_start_label="0",
        development_end_label="19",
        final_holdout_start_label="20",
        final_holdout_end_label="23",
        output_directory=Path(f"pipeline/training-runs/{DATASET_SLUG}/train-20260823T000000Z"),
        training_timestamp="2026-08-23T00:00:00Z",
    )
    kwargs.update(overrides)
    return _build_native_univariate_forecasting_analytical_visualizations_artifact(**kwargs)


def test_builder_emits_v7_and_validates_against_real_schema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    artifact = _build_artifact()
    assert artifact["schema_version"] == "analytical-visualizations.v7"
    _schema_validator().validate(artifact)


def test_builder_embeds_supplied_metric_diagnostics_verbatim():
    block = _metric_diagnostics(metric_ids=("mae", "rmse"))
    artifact = _build_artifact(forecasting_metric_diagnostics=block)
    assert artifact["forecasting_metric_diagnostics"] is block
    assert [entry["metric_id"] for entry in artifact["forecasting_metric_diagnostics"]["metrics"]] == [
        "mae", "rmse",
    ]


def test_builder_emits_exact_aligned_synthetic_evaluation_points():
    artifact = _build_artifact()
    block = artifact["final_holdout_forecast_evaluation"]
    assert block["partition_role"] == "final_holdout"
    assert block["evaluation_count"] == 1
    assert block["model_frozen_before_open"] is True
    assert block["forecast_generated_before_target_open"] is True
    assert block["index_value_kind"] == "ordinal_time"
    assert [point["time_index"] for point in block["points"]] == ["20", "21", "22", "23"]
    assert [point["actual"] for point in block["points"]] == [14.0, 12.0, 9.5, 15.0]
    assert [point["forecast"] for point in block["points"]] == [13.6, 12.3, 9.9, 14.4]
    assert block["final_holdout_boundary"] == {"start_index": "20", "end_index": "23", "observation_count": 4}
    assert block["development_boundary"] == {"start_index": "0", "end_index": "19", "observation_count": 20}
    for point in block["points"]:
        assert set(point) == {"time_index", "actual", "forecast"}


def test_builder_final_holdout_block_is_deterministic_for_identical_inputs():
    assert _build_artifact()["final_holdout_forecast_evaluation"] == (
        _build_artifact()["final_holdout_forecast_evaluation"]
    )


@pytest.mark.parametrize(
    "overrides,expected_code",
    [
        ({"final_holdout_labels": ["20", "21", "22"]}, "invalid_preparation_recipe"),
        ({"y_true_holdout": [1.0, 2.0, 3.0]}, "invalid_preparation_recipe"),
        ({"holdout_forecast_vector": [1.0, 2.0, 3.0, 4.0, 5.0]}, "invalid_preparation_recipe"),
        ({"final_holdout_labels": ["20", "20", "22", "23"]}, "invalid_prepared_dataset"),
        ({"final_holdout_start_label": "99"}, "invalid_prepared_dataset"),
        ({"final_holdout_end_label": "99"}, "invalid_prepared_dataset"),
    ],
)
def test_builder_fails_closed_on_inconsistent_final_holdout_inputs(overrides, expected_code):
    with pytest.raises(TrainingInputError) as excinfo:
        _build_artifact(**overrides)
    assert excinfo.value.code == expected_code


def test_final_holdout_evaluation_helper_rejects_more_than_max_points():
    n = NATIVE_UNIVARIATE_FORECASTING_FINAL_HOLDOUT_MAX_POINTS + 1
    with pytest.raises(TrainingInputError):
        _native_forecasting_final_holdout_forecast_evaluation(
            final_holdout_labels=[str(i) for i in range(n)],
            y_true_holdout=[float(i) for i in range(n)],
            holdout_forecast_vector=[float(i) for i in range(n)],
            forecast_horizon=n,
            development_observation_count=10,
            final_holdout_observation_count=n,
            index_value_kind="ordinal_time",
            frequency="synthetic-step",
            development_start_label="a",
            development_end_label="b",
            final_holdout_start_label="0",
            final_holdout_end_label=str(n - 1),
        )


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


def test_builder_never_embeds_raw_development_history_or_unrelated_row_data():
    artifact = _build_artifact()
    serialized = json.dumps(artifact)
    for forbidden_key in (
        "final_development_history", "y_true", "y_pred", "y_true_holdout", "y_pred_holdout",
        "rows", "holdout_positions", "holdout_design_matrix", "preparation_recipe", "contract",
    ):
        assert forbidden_key not in serialized
    # The only exact per-observation values v6 carries are the bounded
    # final-holdout points -- never the full development history vector.
    block = artifact["final_holdout_forecast_evaluation"]
    assert len(block["points"]) == 4
    # A development-history-only value (10.5, present in the
    # final_development_history fixture but never in the holdout
    # actual/forecast vectors) must not leak into the bounded points.
    point_values = {v for point in block["points"] for v in (point["actual"], point["forecast"])}
    assert 10.5 not in point_values
