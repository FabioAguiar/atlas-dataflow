"""Focused end-to-end tests for the Atlas-native univariate forecasting
public/Admin inference endpoints (Project Spec S0246).

All fixtures are synthetic, dataset-neutral, and use only temporary
repository paths -- no UCI/GitHub fetch, no dataset-study-* path, no
external model bytes, and no Nottingham-specific slug/path/target/frequency/
horizon/seasonal-period constant, matching the boundary already established
by tests/test_univariate_forecasting_inference_bundle.py.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest
from sklearn.linear_model import LinearRegression

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402


SEASONAL_PERIOD = 4
REFERENCE_SEASON_POSITION = 0
DEV_OBSERVATIONS = 20
FORECAST_HORIZON = 4
SEASONAL_EFFECT = [0.0, 2.0, -1.0, 3.0]
DATASET_SLUG = "fixture-forecasting-dataset"
RELEASE_ID = "release-forecasting-fixture"


def _series_value(index: int) -> float:
    return 10.0 + 0.5 * index + SEASONAL_EFFECT[index % SEASONAL_PERIOD]


def _design_row(position: int) -> list[float]:
    row = [1.0, float(position)]
    season = position % SEASONAL_PERIOD
    for candidate_season in range(SEASONAL_PERIOD):
        if candidate_season == REFERENCE_SEASON_POSITION:
            continue
        row.append(1.0 if season == candidate_season else 0.0)
    return row


def _runtime_contract() -> dict:
    return {
        "schema_version": "2.0.0",
        "problem_type": "univariate_forecasting",
        "payload_shape": "history_series",
        "history_series": {
            "container_key": "history",
            "time_index_field_name": "period",
            "target_field_name": "value",
            "index_value_kind": "ordinal_time",
            "frequency": "synthetic-step",
            "source_exogenous_predictors": "forbidden",
            "row_field_policy": "exact_time_index_and_target",
            "minimum_observation_count": 1,
            "minimum_history_required_through": "19",
            "ordering": "strictly_increasing",
            "uniqueness_required": True,
            "frequency_contiguous_required": True,
            "missing_time_index_allowed": False,
            "missing_target_allowed": False,
            "target_value_kind": "continuous_numeric",
        },
        "forecast": {
            "forecast_horizon": FORECAST_HORIZON,
            "horizon_source": "execution_contract.v2",
            "caller_overridable": False,
            "forecast_origin_source": "last_validated_history_index",
            "future_index_policy": "advance_by_governed_frequency",
        },
    }


def _write_synthetic_forecasting_release(tmp_path: Path) -> Path:
    positions = list(range(DEV_OBSERVATIONS))
    design_matrix = [_design_row(position) for position in positions]
    targets = [_series_value(position) for position in positions]
    model = LinearRegression(fit_intercept=False)
    model.fit(design_matrix, targets)

    release_dir = tmp_path / "releases" / RELEASE_ID
    models_dir = release_dir / "models"
    models_dir.mkdir(parents=True)
    model_path = models_dir / "model.pkl"
    joblib.dump(model, model_path)
    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

    declaration = {
        "contract_version": "inference_bundle.v2",
        "bundle_identity": {
            "bundle_id": f"{DATASET_SLUG}-inference-bundle-20260101T000000Z",
            "artifact_kind": "inference_bundle",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "dataset_context": {
            "dataset_slug": DATASET_SLUG,
            "dataset_context_reference": {"path": "context.json", "sha256": "a" * 64},
        },
        "release_context": {
            "release_id": RELEASE_ID,
            "release_package_reference": "predictions/bundle.json",
        },
        "contract_references": {
            "execution_contract": {"path": "ec.json", "sha256": "a" * 64, "contract_version": "execution_contract.v2"},
            "runtime_contract": {"path": "rc.json", "sha256": "a" * 64, "contract_version": "runtime_contract.v1"},
            "public_contract": {"path": "pc.json", "sha256": "a" * 64, "contract_version": "public_contract.v1"},
        },
        "prepared_dataset": {
            "prepared_dataset_reference": {"path": "series.csv", "sha256": "a" * 64},
            "prepared_dataset_sha256": "a" * 64,
        },
        "preparation_evidence": {
            "preparation_recipe": {
                "path": "recipe.json", "sha256": "a" * 64, "contract_version": "candidate-preparation-recipe.v2",
            }
        },
        "training_evidence": {
            "training_run_identity": {"dataset_slug": DATASET_SLUG, "run_id": "train-20260101T000000Z"},
            "training_parameter_record": {
                "path": "tpr.json", "sha256": "a" * 64, "contract_version": "training-parameter-record.v4",
            },
            "training_metrics": {
                "path": "metrics.json", "sha256": "a" * 64, "contract_version": "training-metrics.v4",
            },
        },
        "frozen_model": {
            "state": "frozen",
            "model_artifact": {
                "path": "models/model.pkl",
                "sha256": model_sha256,
                "source_training_parameter_record_path": "tpr.json",
            },
            "model_family": "deterministic_seasonal_trend_ols",
            "training_policy_schema_version": "univariate-forecasting-training-policy.v1",
            "fixed_model_configuration": {
                "include_intercept": True,
                "linear_time_trend": True,
                "seasonal_effects": "additive_indicators",
                "seasonal_period": SEASONAL_PERIOD,
                "reference_season_position": REFERENCE_SEASON_POSITION,
                "trend_origin": "development_start",
            },
            "temporal_identity": {
                "target_column": "value",
                "time_index_column": "period",
                "index_value_kind": "ordinal_time",
                "frequency": "synthetic-step",
                "source_exogenous_predictors": "forbidden",
                "forecast_horizon": FORECAST_HORIZON,
            },
            "training_scope": {"start": "0", "end": "19", "observation_count": DEV_OBSERVATIONS},
            "finalization": {
                "selection_mode": "fixed_configuration",
                "model_selection_performed": False,
                "final_fit_scope": "full_development",
                "frozen_before_final_holdout_open": True,
                "final_holdout_evaluation_count": 1,
                "final_holdout_used_for_adjustment": False,
                "final_holdout_used_for_model_selection": False,
                "no_retuning_after_final_holdout": True,
            },
        },
        "runtime_execution": {
            "execution_strategy": "in_process",
            "serialization_format": "joblib",
            "loader_strategy": "joblib_sklearn_forecasting_adapter",
            "prediction_interface": "forecast_series",
            "model_family": "deterministic_seasonal_trend_ols",
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_history_series",
            "input_policy_source": "runtime_contract",
        },
        "output_schema": {
            "result_schema_version": "univariate-forecasting-result.v1",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
        },
        "compatibility_constraints": {
            "requires_contract_versions": {
                "execution_contract": "execution_contract.v2",
                "runtime_contract": "runtime_contract.v1",
                "public_contract": "public_contract.v1",
            },
            "requires_hash_match": True,
            "requires_release_relative_paths": True,
            "requires_supported_loader": True,
            "requires_supported_serialization": True,
            "requires_temporal_identity_match": True,
            "requires_frozen_model_specification_match": True,
            "requires_forecast_horizon_match": True,
        },
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1",
            "problem_type": "univariate_forecasting",
            "result_schema_version": "univariate-forecasting-result.v1",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
            "model_descriptor": {
                "model_family": "deterministic_seasonal_trend_ols",
                "display_name": "Deterministic Seasonal-Trend OLS",
            },
        },
        "model_provenance_origin": "atlas_internal_training",
        "boundary_confirmations": {
            "release_relative_paths_only": True,
            "absolute_paths_embedded": False,
            "parent_traversal_embedded": False,
            "notebook_state_embedded": False,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "runtime_payload_validation_duplicated": False,
            "training_internals_required_at_runtime": False,
            "external_scientific_project_dependency": False,
            "external_model_artifact_used": False,
            "model_selection_performed": False,
            "final_model_frozen": True,
            "final_holdout_used_for_adjustment": False,
        },
    }

    predictions_dir = release_dir / "predictions"
    predictions_dir.mkdir(parents=True)
    (predictions_dir / "bundle.json").write_text(json.dumps(declaration), encoding="utf-8")
    (release_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [{"role": "inference_bundle", "reference": "predictions/bundle.json"}]}),
        encoding="utf-8",
    )
    return release_dir


def _install_public_dependencies(monkeypatch, releases_root: Path) -> None:
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=RELEASE_ID),
    )
    monkeypatch.setattr(api_main, "load_contract", lambda _active_release: _runtime_contract())
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _dataset_slug, _active_release: {"status": "current_release", "matches_active_release": True},
    )
    monkeypatch.setattr(api_main, "_inference_releases_root", lambda: releases_root)


def test_public_inference_success_envelope_and_finite_exact_horizon_forecast(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    _install_public_dependencies(monkeypatch, releases_root)

    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    response = api_main.validate_dataset_inference_payload(DATASET_SLUG, payload=payload)

    assert not hasattr(response, "status_code")
    assert set(response.keys()) == {"dataset_slug", "result"}
    result = response["result"]
    assert result["schema_version"] == "univariate-forecasting-result.v1"
    assert result["problem_type"] == "univariate_forecasting"
    assert result["forecast_origin"] == 19
    assert result["forecast_horizon"] == FORECAST_HORIZON
    assert len(result["forecast_points"]) == FORECAST_HORIZON
    assert [p["horizon_step"] for p in result["forecast_points"]] == [1, 2, 3, 4]
    assert [p["future_time_index"] for p in result["forecast_points"]] == [20, 21, 22, 23]

    expected = [_series_value(20 + h) for h in range(FORECAST_HORIZON)]
    actual = [p["forecast"] for p in result["forecast_points"]]
    for expected_value, actual_value in zip(expected, actual):
        assert isinstance(actual_value, float)
        assert abs(expected_value - actual_value) < 1e-9

    # No observed target/history rows or interval contract leak into the result.
    serialized = json.dumps(result)
    for forbidden in ("history", "confidence_interval", "prediction_interval", "residual"):
        assert forbidden not in serialized


def test_public_inference_forecasts_beyond_training_end_using_post_training_offset(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    _install_public_dependencies(monkeypatch, releases_root)

    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS + 2)]}
    response = api_main.validate_dataset_inference_payload(DATASET_SLUG, payload=payload)

    result = response["result"]
    assert result["forecast_origin"] == DEV_OBSERVATIONS + 1
    expected = [_series_value(DEV_OBSERVATIONS + 2 + h) for h in range(FORECAST_HORIZON)]
    actual = [p["forecast"] for p in result["forecast_points"]]
    for expected_value, actual_value in zip(expected, actual):
        assert abs(expected_value - actual_value) < 1e-9


def test_admin_inference_success_envelope_matches_public(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    monkeypatch.setattr(api_main, "load_contract", lambda _active_release: _runtime_contract())
    monkeypatch.setattr(api_main, "_inference_releases_root", lambda: releases_root)

    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    response = api_main._execute_governed_inference(
        DATASET_SLUG, RELEASE_ID, payload, include_runtime_diagnostic=True
    )

    assert set(response.keys()) == {"dataset_slug", "result"}
    assert response["result"]["schema_version"] == "univariate-forecasting-result.v1"


def test_public_inference_rejects_user_supplied_horizon(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    _install_public_dependencies(monkeypatch, releases_root)

    payload = {
        "history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)],
        "forecast_horizon": 99,
    }
    response = api_main.validate_dataset_inference_payload(DATASET_SLUG, payload=payload)
    assert response.status_code == 422


def test_public_inference_rejects_insufficient_history(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    _install_public_dependencies(monkeypatch, releases_root)

    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(10)]}
    response = api_main.validate_dataset_inference_payload(DATASET_SLUG, payload=payload)
    assert response.status_code == 422


def test_public_inference_rejects_history_after_boundary_without_boundary_itself(tmp_path, monkeypatch):
    """Project Spec S0265: a normal caller history that reaches past the
    governed boundary but never actually contains it must now be rejected
    during payload validation (422 INVALID_PAYLOAD) instead of reaching
    runtime execution and failing with a 503 INFERENCE_FAILURE -- contrast
    with test_public_inference_history_missing_training_end_anchor_fails_closed
    below, which exercises the runtime's own defense-in-depth anchor check
    against a deliberately lenient/inconsistent runtime contract, not this
    normal user-input path."""
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)
    _install_public_dependencies(monkeypatch, releases_root)

    payload = {"history": [{"period": 20, "value": _series_value(20)}]}
    response = api_main.validate_dataset_inference_payload(DATASET_SLUG, payload=payload)
    assert response.status_code == 422


def test_public_inference_history_missing_training_end_anchor_fails_closed(tmp_path, monkeypatch):
    releases_root = tmp_path / "releases"
    _write_synthetic_forecasting_release(tmp_path)

    # A runtime contract whose declared minimum boundary is earlier than the
    # frozen bundle's actual training_scope.end lets otherwise-valid, minimum
    # -history-satisfying payloads reach execution without containing row
    # period=19 -- the runtime's own independent anchor check must still
    # reject this at execution time (Section B: "The runtime adapter still
    # independently requires the supplied history to contain the frozen
    # training-end anchor").
    lenient_contract = _runtime_contract()
    lenient_contract["history_series"] = dict(lenient_contract["history_series"])
    lenient_contract["history_series"]["minimum_history_required_through"] = "14"

    monkeypatch.setattr(api_main, "load_contract", lambda _active_release: lenient_contract)
    monkeypatch.setattr(api_main, "_inference_releases_root", lambda: releases_root)

    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(15)]}
    response = api_main._execute_governed_inference(DATASET_SLUG, RELEASE_ID, payload)
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Historical binary/multiclass/continuous-regression regression: the shared
# _execute_governed_inference dispatch must remain unaffected by the
# forecasting addition. Mirrors tests/api/test_public_browser_flow.py's
# established monkeypatched-execute_prediction envelope-shape pattern.
# ---------------------------------------------------------------------------

_HISTORICAL_DECLARATIONS = {
    "binary": {
        "runtime_execution": {"execution_strategy": "in_process"},
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "result_schema_version": "binary-classification-result.v1",
            "primary_output": "positive_class_probability",
            "positive_class": {"class_id": "Yes", "event_label": "Churn"},
            "decision": {"threshold": 0.5},
            "interpretation": {
                "preset": "risk",
                "bands": [
                    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
                ],
            },
            "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
        },
        "output_schema": {"class_labels": ["No", "Yes"], "prediction_key": "prediction", "prediction_type": "number"},
    },
    "continuous_regression": {
        "runtime_execution": {"execution_strategy": "in_process"},
        "result_semantics": {
            "schema_version": "continuous-regression-result-semantics.v1",
            "problem_type": "continuous_regression",
            "result_schema_version": "continuous-regression-result.v1",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
            "model_descriptor": {"model_family": "random_forest", "display_name": "Random Forest"},
        },
        "output_schema": {"prediction_type": "number"},
    },
}

_HISTORICAL_RESULTS = {
    "binary": {
        "schema_version": "binary-classification-result.v1",
        "problem_type": "binary_classification",
        "predicted_class": {"class_id": "Yes"},
        "positive_class": {"class_id": "Yes", "event_label": "Churn"},
        "positive_class_probability": 0.68,
        "class_probabilities": [
            {"class_id": "No", "probability": 0.32},
            {"class_id": "Yes", "probability": 0.68},
        ],
        "decision": {"threshold": 0.5, "predicted_positive": True},
        "interpretation": {
            "preset": "risk",
            "band_id": "high",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    },
    "continuous_regression": {
        "schema_version": "continuous-regression-result.v1",
        "problem_type": "continuous_regression",
        "predicted_value": 42.5,
        "model_descriptor": {"model_family": "random_forest", "display_name": "Random Forest"},
    },
}


@pytest.mark.parametrize("variant", ["binary", "continuous_regression"])
def test_public_inference_historical_envelope_unaffected_by_forecasting_dispatch(tmp_path, monkeypatch, variant):
    releases_root = tmp_path / "releases"
    release_dir = releases_root / "release-historical-fixture"
    predictions_dir = release_dir / "predictions"
    predictions_dir.mkdir(parents=True)
    (predictions_dir / "bundle.json").write_text(
        json.dumps(_HISTORICAL_DECLARATIONS[variant]), encoding="utf-8"
    )
    (release_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [{"role": "inference_bundle", "reference": "predictions/bundle.json"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release="release-historical-fixture"),
    )
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda _active_release: {
            "schema_version": "1.0.0",
            "features": [{"name": "age", "type": "numeric", "required": True}],
        },
    )
    monkeypatch.setattr(api_main, "resolve_dataset_visibility", lambda _dataset_slug: True)
    monkeypatch.setattr(api_main, "is_dataset_needs_review", lambda _dataset_slug: False)
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_snapshot_readiness",
        lambda _dataset_slug, _active_release: {"status": "current_release", "matches_active_release": True},
    )
    monkeypatch.setattr(api_main, "_inference_releases_root", lambda: releases_root)
    monkeypatch.setattr(api_main, "execute_prediction", lambda *_a, **_k: {"result": _HISTORICAL_RESULTS[variant]})

    response = api_main.validate_dataset_inference_payload("fixture-historical-dataset", payload={"age": 41})

    assert not hasattr(response, "status_code")
    assert set(response.keys()) == {"dataset_slug", "result"}
    assert response["result"] == _HISTORICAL_RESULTS[variant]
