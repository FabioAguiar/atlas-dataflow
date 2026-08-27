"""Focused tests for the Atlas-native univariate forecasting runtime/contract
layer (Project Spec S0246): runtime/public contract schema family, the
execution_contract.v2 + preparation-recipe.v2 -> runtime/public 2.0.0
projection, the API forecasting payload validator, inference_bundle.v2
model-artifact resolution, the four-way result-semantics dispatch,
deterministic frozen forecasting execution, and the persisted
univariate-forecasting-result.v1 schema.

All fixtures are synthetic, dataset-neutral, and use only temporary
repository paths -- no UCI/GitHub fetch, no dataset-study-* path, no
external model bytes, and no Nottingham-specific slug/path/target/frequency/
horizon/seasonal-period constant, matching the boundary already established
by tests/test_univariate_forecasting_inference_bundle.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest
from sklearn.linear_model import LinearRegression

REPO_ROOT = Path(__file__).parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from pipeline.derive_projections import derive, DerivationFailed  # noqa: E402
from payload_validator import validate_and_normalize_payload  # noqa: E402
import runtime.inference as ri  # noqa: E402


RUNTIME_SCHEMA_PATH = REPO_ROOT / "contracts" / "runtime-contract.schema.json"
PUBLIC_SCHEMA_PATH = REPO_ROOT / "contracts" / "public-contract.schema.json"
FORECASTING_RESULT_SCHEMA_PATH = REPO_ROOT / "contracts" / "univariate-forecasting-result.schema.json"

SEASONAL_PERIOD = 4
REFERENCE_SEASON_POSITION = 0
DEV_OBSERVATIONS = 20
FORECAST_HORIZON = 4
SEASONAL_EFFECT = [0.0, 2.0, -1.0, 3.0]


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


# ---------------------------------------------------------------------------
# Section A/B/C/D: runtime/public contract schema family
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_validator():
    return jsonschema.Draft7Validator(json.loads(RUNTIME_SCHEMA_PATH.read_text()))


@pytest.fixture(scope="module")
def public_validator():
    return jsonschema.Draft7Validator(json.loads(PUBLIC_SCHEMA_PATH.read_text()))


def _valid_runtime_v2_document() -> dict:
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


def _valid_runtime_v1_document() -> dict:
    return {
        "schema_version": "1.0.0",
        "features": [{"name": "age", "type": "numeric", "required": True}],
    }


def _valid_public_v2_document() -> dict:
    return {
        "schema_version": "2.0.0",
        "problem_type": "univariate_forecasting",
        "input_kind": "history_series",
        "history_series": {
            "time_index_field": {"name": "period", "label": "Period", "value_kind": "ordinal_time", "display_order": 1},
            "target_field": {"name": "value", "label": "Value", "value_kind": "number", "display_order": 2},
            "frequency": "synthetic-step",
        },
        "forecast": {"forecast_horizon": FORECAST_HORIZON, "horizon_user_editable": False},
    }


def _valid_public_v1_document() -> dict:
    return {
        "schema_version": "1.0.0",
        "features": [{"name": "age", "label": "Age", "input_type": "number", "optional": False, "display_order": 1}],
    }


def test_runtime_contract_v1_regression_remains_valid(runtime_validator):
    assert not list(runtime_validator.iter_errors(_valid_runtime_v1_document()))


def test_public_contract_v1_regression_remains_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v1_document()))


def test_runtime_contract_v2_schema_valid(runtime_validator):
    assert not list(runtime_validator.iter_errors(_valid_runtime_v2_document()))


def test_public_contract_v2_schema_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v2_document()))


def test_runtime_contract_mixed_v1_v2_document_rejected(runtime_validator):
    mixed = _valid_runtime_v1_document()
    mixed.update(_valid_runtime_v2_document())
    assert list(runtime_validator.iter_errors(mixed))


def test_runtime_contract_unknown_schema_version_rejected(runtime_validator):
    doc = _valid_runtime_v2_document()
    doc["schema_version"] = "3.0.0"
    assert list(runtime_validator.iter_errors(doc))


def test_public_contract_mixed_v1_v2_document_rejected(public_validator):
    mixed = _valid_public_v1_document()
    mixed.update(_valid_public_v2_document())
    assert list(public_validator.iter_errors(mixed))


def test_public_contract_unknown_schema_version_rejected(public_validator):
    doc = _valid_public_v2_document()
    doc["schema_version"] = "3.0.0"
    assert list(public_validator.iter_errors(doc))


def test_runtime_v2_forbids_source_exogenous_predictors_override(runtime_validator):
    doc = _valid_runtime_v2_document()
    doc["history_series"] = dict(doc["history_series"])
    doc["history_series"]["source_exogenous_predictors"] = "allowed"
    assert list(runtime_validator.iter_errors(doc))


def test_runtime_v2_forecast_horizon_not_caller_overridable(runtime_validator):
    doc = _valid_runtime_v2_document()
    doc["forecast"] = dict(doc["forecast"])
    doc["forecast"]["caller_overridable"] = True
    assert list(runtime_validator.iter_errors(doc))


def test_runtime_v2_contains_no_raw_history_or_fold_schedule_fields(runtime_validator):
    doc = _valid_runtime_v2_document()
    doc["history_series"] = dict(doc["history_series"])
    doc["history_series"]["fold_schedule"] = []
    assert list(runtime_validator.iter_errors(doc))
    doc2 = _valid_runtime_v2_document()
    doc2["history"] = [{"period": 0, "value": 1.0}]
    assert list(runtime_validator.iter_errors(doc2))


def test_public_v2_does_not_expose_model_path_or_coefficients(public_validator):
    doc = _valid_public_v2_document()
    doc["model_artifact_path"] = "models/model.pkl"
    assert list(public_validator.iter_errors(doc))


# ---------------------------------------------------------------------------
# Section E/F: execution_contract.v2 + preparation-recipe.v2 -> runtime/public
# projection
# ---------------------------------------------------------------------------


def _execution_contract_v2(**overrides) -> dict:
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
            "primary_metric": {"metric_id": "mae", "direction": "lower_is_better"},
            "secondary_metrics": [],
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
            "fixed_model_configuration": {
                "include_intercept": True,
                "linear_time_trend": True,
                "seasonal_effects": "additive_indicators",
                "seasonal_period": SEASONAL_PERIOD,
                "reference_season_position": REFERENCE_SEASON_POSITION,
                "trend_origin": "development_start",
            },
            "finalization_policy": {
                "backtesting_refit_each_fold": True,
                "final_fit_scope": "full_development",
                "freeze_before_final_holdout_open": True,
                "final_holdout_evaluation_count": 1,
                "final_holdout_used_for_adjustment": False,
                "final_holdout_used_for_model_selection": False,
                "no_retuning_after_final_holdout": True,
            },
        },
        "random_seed": None,
    }
    contract.update(overrides)
    return contract


def _preparation_recipe_v2(**overrides) -> dict:
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
        "partitions": {
            "development": {"start_index_value": "0", "end_index_value": "19", "observation_count": DEV_OBSERVATIONS},
            "sealed_final_holdout": {
                "start_index_value": "20", "end_index_value": "23", "observation_count": 4,
                "prospectively_sealed": True, "used_for_backtesting": False, "used_for_model_selection": False,
            },
        },
        "backtesting": {
            "mode": "expanding_window", "initial_training_observations": 12,
            "forecast_horizon": FORECAST_HORIZON, "origin_step_observations": 4, "fold_count": 2,
            "validation_targets_overlap": False,
        },
        "fold_schedule": [
            {"fold_index": 1, "training_observations": 12, "forecast_origin": "11",
             "validation_start": "12", "validation_end": "15", "validation_observations": 4},
        ],
        "leakage_controls": {
            "random_shuffle_performed": False, "future_targets_used_for_fold_fit": False,
            "final_holdout_used_for_backtesting": False, "final_holdout_used_for_model_selection": False,
            "validation_targets_fed_back_within_fold": False, "preprocessing_fit_on_validation_or_future": False,
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


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_v2_projection_from_execution_and_preparation(tmp_path):
    contract_path = _write_json(tmp_path / "execution-contract.json", _execution_contract_v2())
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    evidence = json.loads((out_dir / "projection-evidence.json").read_text())

    assert runtime_contract["schema_version"] == "2.0.0"
    assert runtime_contract["history_series"]["minimum_history_required_through"] == "19"
    assert runtime_contract["forecast"]["forecast_horizon"] == FORECAST_HORIZON
    assert public_contract["schema_version"] == "2.0.0"
    assert public_contract["forecast"]["horizon_user_editable"] is False
    assert evidence["execution_contract_version"] == "execution_contract.v2"
    for forbidden in ("fold_schedule", "target_values", "predictions", "history_series", "forecast_points"):
        assert forbidden not in json.dumps(evidence)


def test_v2_projection_fails_without_preparation_recipe(tmp_path):
    contract_path = _write_json(tmp_path / "execution-contract.json", _execution_contract_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda c: c.__setitem__("target_column", "other"),
        lambda c: c.__setitem__("time_index_column", "other"),
        lambda c: c.__setitem__("frequency", "other-frequency"),
        lambda c: c.__setitem__("forecast_horizon", 99),
    ],
)
def test_v2_projection_identity_mismatch_fails(tmp_path, mutator):
    contract = _execution_contract_v2()
    mutator(contract)
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def _history_input_policy(**overrides) -> dict:
    policy = {
        "schema_version": "univariate-forecasting-history-input-policy.v1",
        "minimum_observation_count": 1,
        "required_anchor": {"presence": "required", "source": "development_end"},
        "forecast_origin_source": "last_validated_history_index",
    }
    policy.update(overrides)
    return policy


# ---------------------------------------------------------------------------
# Project Spec S0265: history_input_policy-governed projection
# ---------------------------------------------------------------------------


def test_v2_projection_without_history_input_policy_defaults_unchanged(tmp_path):
    """Historical execution_contract.v2 documents materialized before
    Project Spec S0265 never carry history_input_policy -- projection must
    preserve the exact pre-S0265 minimum_observation_count=1 default."""
    assert "history_input_policy" not in _execution_contract_v2()
    contract_path = _write_json(tmp_path / "execution-contract.json", _execution_contract_v2())
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    evidence = json.loads((out_dir / "projection-evidence.json").read_text())
    assert runtime_contract["history_series"]["minimum_observation_count"] == 1
    assert evidence["minimum_observation_count"] == 1
    assert evidence["minimum_observation_count_source"] == "default"


def test_v2_projection_sources_minimum_observation_count_from_history_input_policy(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(minimum_observation_count=3)
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    evidence = json.loads((out_dir / "projection-evidence.json").read_text())
    assert runtime_contract["history_series"]["minimum_observation_count"] == 3
    assert evidence["minimum_observation_count"] == 3
    assert evidence["minimum_observation_count_source"] == "execution_contract.history_input_policy"
    # The governed development-end boundary resolution is unchanged by the
    # policy's presence.
    assert runtime_contract["history_series"]["minimum_history_required_through"] == "19"


def test_v2_projection_history_input_policy_wrong_schema_version_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(
            schema_version="univariate-forecasting-history-input-policy.v2"
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_history_input_policy_non_positive_minimum_observation_count_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(minimum_observation_count=0)
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_history_input_policy_not_required_anchor_presence_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(
            required_anchor={"presence": "not_required", "source": "development_end"}
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_history_input_policy_alternate_anchor_source_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(
            required_anchor={"presence": "required", "source": "rolling_context_window"}
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_history_input_policy_wrong_forecast_origin_source_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(forecast_origin_source="rolling_origin")
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


# ---------------------------------------------------------------------------
# Project Spec S0266: public-contract history-guidance/origin-behavior
# projection
# ---------------------------------------------------------------------------


def _valid_public_v2_document_with_guidance() -> dict:
    doc = _valid_public_v2_document()
    doc["history_series"] = dict(doc["history_series"])
    doc["history_series"]["input_guidance"] = {
        "minimum_observation_count": 1,
        "required_anchor": {"display_value": "19"},
        "continuity": "consecutive_by_frequency",
    }
    doc["forecast"] = dict(doc["forecast"])
    doc["forecast"]["origin_behavior"] = "starts_after_last_history_observation"
    return doc


def test_public_contract_v2_historical_without_guidance_remains_valid(public_validator):
    """Acceptance criterion 5: historical public-contract 2.0.0 without
    input_guidance/origin_behavior remains valid."""
    assert not list(public_validator.iter_errors(_valid_public_v2_document()))


def test_public_contract_v2_with_valid_guidance_is_schema_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v2_document_with_guidance()))


def test_public_contract_v2_guidance_rejects_unknown_property(public_validator):
    doc = _valid_public_v2_document_with_guidance()
    doc["history_series"]["input_guidance"]["extra_property"] = "x"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_required_anchor_rejects_source_property(public_validator):
    doc = _valid_public_v2_document_with_guidance()
    doc["history_series"]["input_guidance"]["required_anchor"]["source"] = "development_end"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_guidance_rejects_non_positive_minimum_observation_count(public_validator):
    doc = _valid_public_v2_document_with_guidance()
    doc["history_series"]["input_guidance"]["minimum_observation_count"] = 0
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_guidance_rejects_non_governed_continuity_value(public_validator):
    doc = _valid_public_v2_document_with_guidance()
    doc["history_series"]["input_guidance"]["continuity"] = "gap_filled"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_forecast_rejects_non_governed_origin_behavior(public_validator):
    doc = _valid_public_v2_document_with_guidance()
    doc["forecast"]["origin_behavior"] = "starts_at_first_history_observation"
    assert list(public_validator.iter_errors(doc))


# ---------------------------------------------------------------------------
# Project Spec S0267: public-contract temporal_interaction machine-actionable
# projection
# ---------------------------------------------------------------------------


def _valid_public_v2_document_with_temporal_interaction() -> dict:
    doc = _valid_public_v2_document_with_guidance()
    doc["history_series"] = dict(doc["history_series"])
    doc["history_series"]["temporal_interaction"] = {
        "control_kind": "month",
        "required_anchor": {"value": "2020-06", "inclusion": "required"},
        "sequence": {"step_kind": "calendar_month", "continuity": "required"},
    }
    return doc


def test_public_contract_v2_historical_without_temporal_interaction_remains_valid(public_validator):
    """Acceptance criterion 6: historical public-contract v2 without
    temporal_interaction remains valid, whether or not S0266 input_guidance
    is present."""
    assert not list(public_validator.iter_errors(_valid_public_v2_document()))
    assert not list(public_validator.iter_errors(_valid_public_v2_document_with_guidance()))


def test_public_contract_v2_with_valid_temporal_interaction_is_schema_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v2_document_with_temporal_interaction()))


def test_public_contract_v2_temporal_interaction_rejects_unknown_property(public_validator):
    doc = _valid_public_v2_document_with_temporal_interaction()
    doc["history_series"]["temporal_interaction"]["extra_property"] = "x"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_temporal_interaction_rejects_non_month_control_kind(public_validator):
    doc = _valid_public_v2_document_with_temporal_interaction()
    doc["history_series"]["temporal_interaction"]["control_kind"] = "day"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_temporal_interaction_anchor_rejects_non_canonical_value(public_validator):
    for bad_value in ("1938-13", "38-12", "1938/12", "1938-1"):
        doc = _valid_public_v2_document_with_temporal_interaction()
        doc["history_series"]["temporal_interaction"]["required_anchor"]["value"] = bad_value
        assert list(public_validator.iter_errors(doc)), bad_value


def test_public_contract_v2_temporal_interaction_rejects_non_required_inclusion(public_validator):
    doc = _valid_public_v2_document_with_temporal_interaction()
    doc["history_series"]["temporal_interaction"]["required_anchor"]["inclusion"] = "minimum"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_temporal_interaction_rejects_non_calendar_month_step_kind(public_validator):
    doc = _valid_public_v2_document_with_temporal_interaction()
    doc["history_series"]["temporal_interaction"]["sequence"]["step_kind"] = "calendar_day"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_temporal_interaction_rejects_non_required_continuity(public_validator):
    doc = _valid_public_v2_document_with_temporal_interaction()
    doc["history_series"]["temporal_interaction"]["sequence"]["continuity"] = "best_effort"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_temporal_interaction_rejects_min_max_style_properties(public_validator):
    for forbidden_key in ("min", "max", "minimum_date", "maximum_date", "development_end", "training_scope"):
        doc = _valid_public_v2_document_with_temporal_interaction()
        doc["history_series"]["temporal_interaction"][forbidden_key] = "x"
        assert list(public_validator.iter_errors(doc)), forbidden_key


def test_v2_projection_without_history_input_policy_emits_no_public_guidance(tmp_path):
    """Historical execution_contract.v2 without history_input_policy must
    preserve the existing public-contract v2 output shape -- no
    input_guidance, no origin_behavior."""
    contract_path = _write_json(tmp_path / "execution-contract.json", _execution_contract_v2())
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert "input_guidance" not in public_contract["history_series"]
    assert "origin_behavior" not in public_contract["forecast"]


def test_v2_projection_with_history_input_policy_emits_public_guidance(tmp_path):
    contract = _execution_contract_v2(
        history_input_policy=_history_input_policy(minimum_observation_count=3)
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert public_contract["history_series"]["input_guidance"] == {
        "minimum_observation_count": 3,
        "required_anchor": {"display_value": "19"},
        "continuity": "consecutive_by_frequency",
    }
    assert public_contract["forecast"]["origin_behavior"] == "starts_after_last_history_observation"


def test_v2_projection_public_guidance_never_copies_execution_policy_verbatim(tmp_path):
    contract = _execution_contract_v2(history_input_policy=_history_input_policy())
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    guidance = public_contract["history_series"]["input_guidance"]
    assert "source" not in guidance["required_anchor"]
    assert "presence" not in guidance["required_anchor"]
    assert "forecast_origin_source" not in public_contract["forecast"]
    assert "schema_version" not in guidance
    serialized = json.dumps(public_contract)
    for forbidden in (
        "development_end",
        "required_anchor.source",
        "training_scope",
        "minimum_history_required_through",
        "frequency_contiguous_required",
        "uniqueness_required",
        "ordering",
    ):
        assert forbidden not in serialized


def _execution_contract_v2_calendar_monthly(**overrides) -> dict:
    contract = _execution_contract_v2(index_value_kind="calendar_period", frequency="monthly")
    contract.update(overrides)
    return contract


def _preparation_recipe_v2_calendar_monthly(end_index_value: str = "2020-06", **overrides) -> dict:
    recipe = _preparation_recipe_v2()
    recipe["semantic_identity_mirror"] = dict(recipe["semantic_identity_mirror"])
    recipe["semantic_identity_mirror"]["index_value_kind"] = "calendar_period"
    recipe["semantic_identity_mirror"]["frequency"] = "monthly"
    recipe["partitions"] = {
        "development": dict(recipe["partitions"]["development"]),
        "sealed_final_holdout": dict(recipe["partitions"]["sealed_final_holdout"]),
    }
    recipe["partitions"]["development"]["end_index_value"] = end_index_value
    recipe.update(overrides)
    return recipe


def test_v2_projection_calendar_period_monthly_emits_temporal_interaction(tmp_path):
    """Current governed calendar_period/monthly policy emits the exact
    bounded machine interaction profile, with the emitted anchor equal to
    the governed resolved anchor."""
    contract = _execution_contract_v2_calendar_monthly(history_input_policy=_history_input_policy())
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2_calendar_monthly())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    temporal_interaction = public_contract["history_series"]["temporal_interaction"]
    assert temporal_interaction == {
        "control_kind": "month",
        "required_anchor": {"value": "2020-06", "inclusion": "required"},
        "sequence": {"step_kind": "calendar_month", "continuity": "required"},
    }
    assert temporal_interaction["required_anchor"]["value"] == runtime_contract["history_series"][
        "minimum_history_required_through"
    ]


def test_v2_projection_temporal_interaction_anchor_distinct_from_display_value(tmp_path):
    """The machine anchor lives at a distinct path from S0266's
    input_guidance.required_anchor.display_value even when the current
    canonical string is identical."""
    contract = _execution_contract_v2_calendar_monthly(history_input_policy=_history_input_policy())
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2_calendar_monthly())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    history_series = public_contract["history_series"]
    assert history_series["input_guidance"]["required_anchor"]["display_value"] == "2020-06"
    assert history_series["temporal_interaction"]["required_anchor"]["value"] == "2020-06"
    assert "value" not in history_series["input_guidance"]["required_anchor"]
    assert "display_value" not in history_series["temporal_interaction"]["required_anchor"]


def test_v2_projection_temporal_interaction_never_leaks_min_max_or_training_terminology(tmp_path):
    contract = _execution_contract_v2_calendar_monthly(history_input_policy=_history_input_policy())
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2_calendar_monthly())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    serialized = json.dumps(public_contract["history_series"]["temporal_interaction"])
    for forbidden in (
        "min", "max", "minimum_date", "maximum_date",
        "development_end", "training_scope", "training_end",
        "minimum_history_required_through", "source",
    ):
        assert forbidden not in serialized


def test_v2_projection_calendar_period_monthly_malformed_anchor_fails_closed(tmp_path):
    """For the explicitly supported calendar_period + monthly profile, a
    non-canonical resolved anchor must fail derivation closed rather than
    emit ambiguous machine metadata."""
    contract = _execution_contract_v2_calendar_monthly(history_input_policy=_history_input_policy())
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(
        tmp_path / "preparation-recipe.json",
        _preparation_recipe_v2_calendar_monthly(end_index_value="2020-6"),
    )
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)
    assert not (tmp_path / "out" / "public-contract.json").exists()


def test_v2_projection_unsupported_temporal_profile_omits_temporal_interaction_keeps_guidance(tmp_path):
    """An otherwise-valid unsupported temporal-kind/frequency combination
    (ordinal_time/synthetic-step) keeps the S0266 display guidance and
    omits temporal_interaction rather than guessing a stepping profile."""
    contract = _execution_contract_v2(history_input_policy=_history_input_policy(minimum_observation_count=3))
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert "temporal_interaction" not in public_contract["history_series"]
    assert public_contract["history_series"]["input_guidance"]["minimum_observation_count"] == 3


# ---------------------------------------------------------------------------
# Project Spec S0269: public-contract predictive_interaction projection
# ---------------------------------------------------------------------------


def _predictive_interaction_policy(**overrides) -> dict:
    policy = {
        "schema_version": "univariate-forecasting-predictive-interaction-policy.v1",
        "history_target_values_affect_forecast": False,
        "refit_on_input": False,
        "model_parameters_updated_on_input": False,
        "public_prediction_interaction_applicability": "not_applicable",
    }
    policy.update(overrides)
    return policy


def _valid_public_v2_document_with_predictive_interaction() -> dict:
    doc = _valid_public_v2_document()
    doc["predictive_interaction"] = {
        "history_target_values": {"affect_forecast": False},
        "public_prediction": {"applicability": "not_applicable"},
    }
    return doc


def test_public_contract_v2_historical_without_predictive_interaction_remains_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v2_document()))


def test_public_contract_v2_with_valid_predictive_interaction_is_schema_valid(public_validator):
    assert not list(public_validator.iter_errors(_valid_public_v2_document_with_predictive_interaction()))


def test_public_contract_v2_predictive_interaction_available_is_schema_valid(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["history_target_values"]["affect_forecast"] = True
    doc["predictive_interaction"]["public_prediction"]["applicability"] = "available"
    assert not list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_unknown_top_level_property(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["extra_property"] = "x"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_missing_history_target_values(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    del doc["predictive_interaction"]["history_target_values"]
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_missing_public_prediction(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    del doc["predictive_interaction"]["public_prediction"]
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_non_boolean_affect_forecast(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["history_target_values"]["affect_forecast"] = "false"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_unknown_applicability(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["public_prediction"]["applicability"] = "sometimes"
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_refit_flag_exposed(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["refit_on_input"] = False
    assert list(public_validator.iter_errors(doc))


def test_public_contract_v2_predictive_interaction_rejects_model_update_flag_exposed(public_validator):
    doc = _valid_public_v2_document_with_predictive_interaction()
    doc["predictive_interaction"]["model_parameters_updated_on_input"] = False
    assert list(public_validator.iter_errors(doc))


def test_v2_projection_without_predictive_interaction_policy_emits_no_public_field(tmp_path):
    """Historical execution_contract.v2 documents materialized before
    Project Spec S0269 never carry predictive_interaction_policy --
    projection must omit predictive_interaction entirely rather than
    inventing one."""
    assert "predictive_interaction_policy" not in _execution_contract_v2()
    contract_path = _write_json(tmp_path / "execution-contract.json", _execution_contract_v2())
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert "predictive_interaction" not in public_contract


def test_v2_projection_emits_predictive_interaction_from_policy(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            history_target_values_affect_forecast=True,
            public_prediction_interaction_applicability="available",
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert public_contract["predictive_interaction"] == {
        "history_target_values": {"affect_forecast": True},
        "public_prediction": {"applicability": "available"},
    }


def test_v2_projection_predictive_interaction_never_exposes_refit_or_model_update_flags(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            history_target_values_affect_forecast=True,
            refit_on_input=True,
            model_parameters_updated_on_input=True,
            public_prediction_interaction_applicability="available",
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    public_contract = json.loads((out_dir / "public-contract.json").read_text())
    assert set(public_contract["predictive_interaction"]["public_prediction"].keys()) == {"applicability"}
    assert set(public_contract["predictive_interaction"]["history_target_values"].keys()) == {"affect_forecast"}
    serialized = json.dumps(public_contract["predictive_interaction"])
    assert "refit_on_input" not in serialized
    assert "model_parameters_updated_on_input" not in serialized


def test_v2_projection_predictive_interaction_policy_unknown_schema_version_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            schema_version="univariate-forecasting-predictive-interaction-policy.v2"
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_predictive_interaction_policy_malformed_affect_forecast_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            history_target_values_affect_forecast="false"
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_predictive_interaction_policy_unknown_applicability_fails_closed(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            public_prediction_interaction_applicability="sometimes"
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    with pytest.raises(DerivationFailed):
        derive(contract_path, tmp_path / "out", repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)


def test_v2_projection_predictive_interaction_does_not_affect_runtime_contract(tmp_path):
    contract = _execution_contract_v2(
        predictive_interaction_policy=_predictive_interaction_policy(
            history_target_values_affect_forecast=True,
            public_prediction_interaction_applicability="available",
        )
    )
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    recipe_path = _write_json(tmp_path / "preparation-recipe.json", _preparation_recipe_v2())
    out_dir = tmp_path / "out"

    derive(contract_path, out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    baseline_contract_path = _write_json(
        tmp_path / "baseline-execution-contract.json", _execution_contract_v2()
    )
    baseline_out_dir = tmp_path / "baseline-out"
    derive(baseline_contract_path, baseline_out_dir, repo_root=REPO_ROOT, preparation_recipe_path=recipe_path)

    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    baseline_runtime_contract = json.loads((baseline_out_dir / "runtime-contract.json").read_text())
    assert runtime_contract == baseline_runtime_contract


def test_historical_v1_projection_does_not_require_preparation_recipe(tmp_path):
    execution_contract_v1 = {
        "contract_version": "execution_contract.v1",
        "dataset_id": "bank-marketing",
        "target_column": "target",
        "feature_columns": ["age"],
        "ignored_columns": [],
        "required_columns": ["age"],
        "optional_columns": [],
        "feature_definitions": {"age": {"type": "numeric", "domain_constraints": {"min": 0, "max": 120}}},
        "missing_value_policy": {"age": "mean"},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.8, "val_ratio": 0.0, "test_ratio": 0.2},
        "random_seed": None,
        "primary_metric": "roc_auc",
        "secondary_metrics": [],
        "modeling_constraints": {"allowed_model_families": ["logistic_regression"]},
    }
    contract_path = _write_json(tmp_path / "execution-contract.json", execution_contract_v1)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime_contract = json.loads((out_dir / "runtime-contract.json").read_text())
    assert runtime_contract["schema_version"] == "1.0.0"


# ---------------------------------------------------------------------------
# Section G: API forecasting payload validation
# ---------------------------------------------------------------------------


def _forecasting_runtime_contract(**history_overrides) -> dict:
    history_series = {
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
    }
    history_series.update(history_overrides)
    return {
        "schema_version": "2.0.0",
        "problem_type": "univariate_forecasting",
        "payload_shape": "history_series",
        "history_series": history_series,
        "forecast": {
            "forecast_horizon": FORECAST_HORIZON,
            "horizon_source": "execution_contract.v2",
            "caller_overridable": False,
            "forecast_origin_source": "last_validated_history_index",
            "future_index_policy": "advance_by_governed_frequency",
        },
    }


def test_forecasting_payload_valid_history_accepted():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    report = validate_and_normalize_payload(payload, contract)
    assert not report.failures


def test_forecasting_payload_rejects_user_supplied_horizon():
    contract = _forecasting_runtime_contract()
    payload = {
        "history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)],
        "forecast_horizon": 99,
    }
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures
    assert report.failures[0].error_code == "FORECASTING_UNKNOWN_TOP_LEVEL_FIELD"


def test_forecasting_payload_requires_exact_row_fields():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 0, "value": 1.0, "extra_column": 5}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_HISTORY_ROW"


def test_forecasting_payload_requires_non_empty_history():
    contract = _forecasting_runtime_contract()
    report = validate_and_normalize_payload({"history": []}, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_HISTORY_SHAPE"


@pytest.mark.parametrize(
    "history",
    [
        [{"period": 0, "value": 1.0}, {"period": 0, "value": 2.0}],  # duplicate
        [{"period": 1, "value": 1.0}, {"period": 0, "value": 2.0}],  # out of order
        [{"period": 0, "value": 1.0}, {"period": 2, "value": 2.0}],  # gapped
    ],
)
def test_forecasting_payload_rejects_malformed_ordering(history):
    contract = _forecasting_runtime_contract()
    report = validate_and_normalize_payload({"history": history}, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TIME_INDEX"


def test_forecasting_payload_rejects_non_finite_target():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 0, "value": float("nan")}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TARGET_VALUE"


def test_forecasting_payload_rejects_boolean_target():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 0, "value": True}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TARGET_VALUE"


def test_forecasting_payload_rejects_non_numeric_target():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 0, "value": "not-a-number"}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TARGET_VALUE"


def test_forecasting_payload_rejects_below_minimum_history_boundary():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(10)]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_MINIMUM_HISTORY_NOT_MET"


# ---------------------------------------------------------------------------
# Project Spec S0265: minimum_history_required_through boundary membership
# ---------------------------------------------------------------------------


def test_forecasting_payload_boundary_only_row_accepted():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 19, "value": _series_value(19)}]}
    report = validate_and_normalize_payload(payload, contract)
    assert not report.failures


def test_forecasting_payload_boundary_plus_contiguous_later_period_accepted():
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS + 1)]}
    report = validate_and_normalize_payload(payload, contract)
    assert not report.failures


def test_forecasting_payload_rejects_later_period_without_boundary_itself():
    """Project Spec S0265: a history whose final index is after the
    governed boundary but which never actually contains the boundary value
    itself must be rejected -- the pre-S0265 check only compared the final
    supplied index against the boundary and missed this case."""
    contract = _forecasting_runtime_contract()
    payload = {"history": [{"period": 20, "value": _series_value(20)}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_MINIMUM_HISTORY_NOT_MET"


def test_forecasting_payload_calendar_period_later_period_without_boundary_rejected():
    contract = _forecasting_runtime_contract(
        index_value_kind="calendar_period", frequency="monthly", minimum_history_required_through="2020-03",
    )
    payload = {"history": [{"period": "2020-04", "value": 1.0}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_MINIMUM_HISTORY_NOT_MET"


def test_forecasting_payload_timestamp_later_period_without_boundary_rejected():
    contract = _forecasting_runtime_contract(
        index_value_kind="timestamp", frequency="daily", minimum_history_required_through="2020-01-02",
    )
    payload = {"history": [{"period": "2020-01-03", "value": 1.0}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_MINIMUM_HISTORY_NOT_MET"


def test_forecasting_payload_calendar_period_index_helper():
    contract = _forecasting_runtime_contract(
        index_value_kind="calendar_period", frequency="monthly", minimum_history_required_through="2020-03",
    )
    payload = {
        "history": [
            {"period": "2020-01", "value": 1.0},
            {"period": "2020-02", "value": 2.0},
            {"period": "2020-03", "value": 3.0},
        ]
    }
    report = validate_and_normalize_payload(payload, contract)
    assert not report.failures
    assert report.normalized_payload["history"][0]["period"] == "2020-01"


def test_forecasting_payload_calendar_period_gap_rejected():
    contract = _forecasting_runtime_contract(index_value_kind="calendar_period", frequency="monthly")
    payload = {"history": [{"period": "2020-01", "value": 1.0}, {"period": "2020-03", "value": 2.0}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TIME_INDEX"


def test_forecasting_payload_timestamp_index_helper():
    contract = _forecasting_runtime_contract(
        index_value_kind="timestamp", frequency="daily", minimum_history_required_through="2020-01-02",
    )
    payload = {"history": [{"period": "2020-01-01", "value": 1.0}, {"period": "2020-01-02", "value": 2.0}]}
    report = validate_and_normalize_payload(payload, contract)
    assert not report.failures
    assert report.normalized_payload["history"][0]["period"] == "2020-01-01T00:00:00"


def test_forecasting_payload_unresolvable_frequency_fails_closed():
    contract = _forecasting_runtime_contract(index_value_kind="calendar_period", frequency="not-a-known-frequency")
    payload = {"history": [{"period": "2020-01", "value": 1.0}]}
    report = validate_and_normalize_payload(payload, contract)
    assert report.failures[0].error_code == "FORECASTING_INVALID_TIME_INDEX"


def test_scalar_feature_payload_validation_still_dispatches_for_v1_contract():
    contract = {"schema_version": "1.0.0", "features": [{"name": "age", "type": "numeric", "required": True}]}
    report = validate_and_normalize_payload({"age": 41}, contract)
    assert not report.failures


# ---------------------------------------------------------------------------
# Section J/K: inference_bundle.v2 model-artifact resolution and loader
# strategy allowlist
# ---------------------------------------------------------------------------


def test_v2_model_artifact_resolves_from_frozen_model_only():
    declaration = {
        "contract_version": "inference_bundle.v2",
        "frozen_model": {
            "model_artifact": {
                "path": "models/model.pkl", "sha256": "b" * 64, "source_training_parameter_record_path": "tpr.json",
            }
        },
    }
    assert ri._model_artifact_reference(declaration) == "models/model.pkl"
    assert ri._model_artifact_sha256(declaration) == "b" * 64


def test_v2_never_falls_back_to_v1_top_level_model_artifact():
    declaration = {
        "contract_version": "inference_bundle.v2",
        "model_artifact": {"path": "wrong/path.pkl", "sha256": "c" * 64},
        "frozen_model": {},
    }
    assert ri._model_artifact_reference(declaration) is None


def test_v1_model_artifact_resolution_unchanged():
    declaration = {"model_artifact": {"path": "models/model.pkl", "sha256": "d" * 64}}
    assert ri._model_artifact_reference(declaration) == "models/model.pkl"


def test_forecasting_loader_strategy_identity_is_controlled():
    assert ri.JOBLIB_SKLEARN_FORECASTING_ADAPTER_STRATEGY == "joblib_sklearn_forecasting_adapter"
    assert ri.JOBLIB_SKLEARN_FORECASTING_ADAPTER_STRATEGY != ri.JOBLIB_SKLEARN_PREDICT_STRATEGY


# ---------------------------------------------------------------------------
# Section L: result-semantics four-way dispatch
# ---------------------------------------------------------------------------


def test_result_semantics_dispatch_resolves_forecasting():
    declaration = {
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1",
            "problem_type": "univariate_forecasting",
        }
    }
    assert ri._resolve_result_semantics_variant(declaration) == "forecasting"


def test_result_semantics_dispatch_still_resolves_binary_multiclass_continuous():
    assert ri._resolve_result_semantics_variant(
        {"result_semantics": {"schema_version": "binary-result-semantics.v1", "problem_type": "binary_classification"}}
    ) == "binary"
    assert ri._resolve_result_semantics_variant(
        {"result_semantics": {"schema_version": "multiclass-result-semantics.v1", "problem_type": "multiclass_classification"}}
    ) == "multiclass"
    assert ri._resolve_result_semantics_variant(
        {"result_semantics": {"schema_version": "continuous-regression-result-semantics.v1", "problem_type": "continuous_regression"}}
    ) == "continuous_regression"


def test_result_semantics_dispatch_unknown_variant_fails_closed():
    with pytest.raises(ri.BundleValidationError):
        ri._resolve_result_semantics_variant({"result_semantics": {"schema_version": "x", "problem_type": "y"}})


def test_result_semantics_dispatch_mixed_variant_fails_closed():
    with pytest.raises(ri.BundleValidationError):
        ri._resolve_result_semantics_variant(
            {"result_semantics": {"schema_version": "binary-result-semantics.v1", "problem_type": "univariate_forecasting"}}
        )


# ---------------------------------------------------------------------------
# Section M/N/O: strict bundle/runtime cross-checks and deterministic
# frozen forecasting execution
# ---------------------------------------------------------------------------


def _fixed_model_configuration() -> dict:
    return {
        "include_intercept": True,
        "linear_time_trend": True,
        "seasonal_effects": "additive_indicators",
        "seasonal_period": SEASONAL_PERIOD,
        "reference_season_position": REFERENCE_SEASON_POSITION,
        "trend_origin": "development_start",
    }


def _forecasting_declaration(**overrides) -> dict:
    declaration = {
        "contract_version": "inference_bundle.v2",
        "runtime_execution": {
            "execution_strategy": "in_process",
            "serialization_format": "joblib",
            "loader_strategy": "joblib_sklearn_forecasting_adapter",
            "prediction_interface": "forecast_series",
            "model_family": "deterministic_seasonal_trend_ols",
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
        "output_schema": {
            "result_schema_version": "univariate-forecasting-result.v1",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
        },
        "frozen_model": {
            "state": "frozen",
            "model_artifact": {"path": "models/model.pkl", "sha256": "a" * 64, "source_training_parameter_record_path": "tpr.json"},
            "model_family": "deterministic_seasonal_trend_ols",
            "fixed_model_configuration": _fixed_model_configuration(),
            "temporal_identity": {
                "target_column": "value", "time_index_column": "period", "index_value_kind": "ordinal_time",
                "frequency": "synthetic-step", "source_exogenous_predictors": "forbidden",
                "forecast_horizon": FORECAST_HORIZON,
            },
            "training_scope": {"start": "0", "end": "19", "observation_count": DEV_OBSERVATIONS},
            "finalization": {
                "selection_mode": "fixed_configuration", "model_selection_performed": False,
                "final_fit_scope": "full_development", "frozen_before_final_holdout_open": True,
                "final_holdout_evaluation_count": 1, "final_holdout_used_for_adjustment": False,
                "final_holdout_used_for_model_selection": False, "no_retuning_after_final_holdout": True,
            },
        },
    }
    declaration.update(overrides)
    return declaration


class _FakeAdapter:
    def __init__(self, declaration, bundle):
        self.declaration = declaration
        self.bundle = bundle


@pytest.fixture(scope="module")
def frozen_model_and_adapter():
    positions = list(range(DEV_OBSERVATIONS))
    design_matrix = [_design_row(position) for position in positions]
    targets = [_series_value(position) for position in positions]
    model = LinearRegression(fit_intercept=False)
    model.fit(design_matrix, targets)
    declaration = _forecasting_declaration()
    runtime_contract = _forecasting_runtime_contract()
    return _FakeAdapter(declaration, model), runtime_contract


def test_deterministic_design_matrix_continuation_and_exact_horizon_forecast(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}

    result = ri._execute_forecasting_prediction(adapter, payload, runtime_contract)

    expected = [_series_value(DEV_OBSERVATIONS + h) for h in range(FORECAST_HORIZON)]
    actual = [point["forecast"] for point in result["forecast_points"]]
    for expected_value, actual_value in zip(expected, actual):
        assert abs(expected_value - actual_value) < 1e-9
    assert result["forecast_origin"] == DEV_OBSERVATIONS - 1
    assert [point["future_time_index"] for point in result["forecast_points"]] == [20, 21, 22, 23]
    assert len(result["forecast_points"]) == FORECAST_HORIZON


def test_post_training_history_offset_continues_design_matrix_correctly(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    extra_offset = 3
    payload = {
        "history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS + extra_offset)]
    }

    result = ri._execute_forecasting_prediction(adapter, payload, runtime_contract)

    expected = [_series_value(DEV_OBSERVATIONS + extra_offset + h) for h in range(FORECAST_HORIZON)]
    actual = [point["forecast"] for point in result["forecast_points"]]
    for expected_value, actual_value in zip(expected, actual):
        assert abs(expected_value - actual_value) < 1e-9


def test_history_missing_training_end_anchor_fails_closed(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(0, 15)]}
    with pytest.raises(ri.BundleExecutionError):
        ri._execute_forecasting_prediction(adapter, payload, runtime_contract)


def test_no_fit_or_refit_or_model_selection_in_executor_source():
    import inspect

    source = inspect.getsource(ri._execute_forecasting_prediction)
    assert ".fit(" not in source
    assert ".partial_fit(" not in source
    validation_source = inspect.getsource(ri._validate_forecasting_bundle_for_execution)
    assert ".fit(" not in validation_source


def test_bundle_runtime_contract_identity_mismatch_fails_before_prediction(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    mismatched_contract = json.loads(json.dumps(runtime_contract))
    mismatched_contract["forecast"]["forecast_horizon"] = 99
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    with pytest.raises(ri.BundleValidationError):
        ri._execute_forecasting_prediction(adapter, payload, mismatched_contract)


def test_missing_runtime_contract_fails_closed(frozen_model_and_adapter):
    adapter, _runtime_contract = frozen_model_and_adapter
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    with pytest.raises(ri.BundleValidationError):
        ri._execute_forecasting_prediction(adapter, payload, None)


def test_wrong_bundle_contract_version_fails_closed(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    bad_declaration = dict(adapter.declaration)
    bad_declaration["contract_version"] = "inference_bundle.v1"
    bad_adapter = _FakeAdapter(bad_declaration, adapter.bundle)
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    with pytest.raises(ri.BundleValidationError):
        ri._execute_forecasting_prediction(bad_adapter, payload, runtime_contract)


def test_wrong_loader_strategy_fails_closed(frozen_model_and_adapter):
    adapter, runtime_contract = frozen_model_and_adapter
    bad_declaration = json.loads(json.dumps(adapter.declaration))
    bad_declaration["runtime_execution"]["loader_strategy"] = "joblib_sklearn_predict"
    bad_adapter = _FakeAdapter(bad_declaration, adapter.bundle)
    payload = {"history": [{"period": i, "value": _series_value(i)} for i in range(DEV_OBSERVATIONS)]}
    with pytest.raises(ri.BundleValidationError):
        ri._execute_forecasting_prediction(bad_adapter, payload, runtime_contract)


# ---------------------------------------------------------------------------
# Section I/H: univariate-forecasting-result.v1 schema + runtime validation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def forecasting_result_validator():
    return jsonschema.Draft202012Validator(json.loads(FORECASTING_RESULT_SCHEMA_PATH.read_text()))


def _valid_forecasting_result() -> dict:
    return {
        "schema_version": "univariate-forecasting-result.v1",
        "problem_type": "univariate_forecasting",
        "forecast_origin": 19,
        "frequency": "synthetic-step",
        "forecast_horizon": 2,
        "forecast_points": [
            {"horizon_step": 1, "future_time_index": 20, "forecast": 1.5},
            {"horizon_step": 2, "future_time_index": 21, "forecast": 2.5},
        ],
        "model_descriptor": {
            "model_family": "deterministic_seasonal_trend_ols",
            "display_name": "Deterministic Seasonal-Trend OLS",
        },
    }


def test_forecasting_result_schema_valid(forecasting_result_validator):
    assert not list(forecasting_result_validator.iter_errors(_valid_forecasting_result()))


def test_forecasting_result_schema_rejects_history_or_interval_fields(forecasting_result_validator):
    doc = _valid_forecasting_result()
    doc["history"] = []
    assert list(forecasting_result_validator.iter_errors(doc))
    doc2 = _valid_forecasting_result()
    doc2["confidence_interval"] = {"lower": 1.0, "upper": 2.0}
    assert list(forecasting_result_validator.iter_errors(doc2))


def test_forecasting_result_schema_rejects_non_positive_horizon(forecasting_result_validator):
    doc = _valid_forecasting_result()
    doc["forecast_horizon"] = 0
    assert list(forecasting_result_validator.iter_errors(doc))


def test_forecasting_result_schema_rejects_boolean_future_time_index(forecasting_result_validator):
    doc = _valid_forecasting_result()
    doc["forecast_points"][0]["future_time_index"] = True
    assert list(forecasting_result_validator.iter_errors(doc))


def test_validate_univariate_forecasting_result_accepts_valid_result():
    ri.validate_univariate_forecasting_result(_valid_forecasting_result())


def test_validate_univariate_forecasting_result_rejects_cardinality_mismatch():
    doc = _valid_forecasting_result()
    doc["forecast_points"] = [doc["forecast_points"][0]]
    with pytest.raises(ri.BundleValidationError):
        ri.validate_univariate_forecasting_result(doc)


def test_validate_univariate_forecasting_result_rejects_non_finite_forecast():
    doc = _valid_forecasting_result()
    doc["forecast_points"][0]["forecast"] = float("inf")
    with pytest.raises(ri.BundleValidationError):
        ri.validate_univariate_forecasting_result(doc)


def test_validate_univariate_forecasting_result_rejects_wrong_horizon_step_sequence():
    doc = _valid_forecasting_result()
    doc["forecast_points"][0]["horizon_step"] = 2
    doc["forecast_points"][1]["horizon_step"] = 1
    with pytest.raises(ri.BundleValidationError):
        ri.validate_univariate_forecasting_result(doc)


def test_validate_univariate_forecasting_result_rejects_non_contiguous_future_index():
    doc = _valid_forecasting_result()
    doc["forecast_points"][1]["future_time_index"] = 99
    with pytest.raises(ri.BundleValidationError):
        ri.validate_univariate_forecasting_result(doc)
