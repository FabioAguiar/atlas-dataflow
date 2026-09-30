"""Univariate-forecasting Scientific Reproduction: contract v4, temporal runner, report v4.

Dataset-agnostic. A synthetic monthly series (trend + annual seasonality +
noise, fractional-year time coordinates) is written inside ``tmp_path``; the
contract declares a development window, a sealed 12-month holdout, a 3-fold
expanding-window backtest and a six-specification catalog covering every
scientific forecasting family, so a full run takes seconds.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import forecasting_models, metric_identity, model_families
from pipeline import scientific_environment as env
from pipeline import scientific_forecasting as sf
from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc

pytest.importorskip("statsmodels")

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "fedcba9876543210fedcba9876543210fedcba98"
LABEL = f"study-{REVISION[:12]}"
SLUG = "synthetic-forecasting"
START_YEAR = 2000
TOTAL, DEVELOPMENT, HOLDOUT = 96, 84, 12
INITIAL, STEP, HORIZON, FOLDS = 48, 12, 12, 3
CANONICAL = "reproducibility/canonical-run.json"


# --------------------------------------------------------------------------
# synthetic univariate forecasting study
# --------------------------------------------------------------------------


def _values(n: int = TOTAL) -> list[float]:
    rng = np.random.default_rng(11)
    t = np.arange(n)
    return list(np.round(50 + 0.03 * t + 9 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 1.2, n), 1))


def _csv(path: Path, values: list[float] | None = None, times: list[float] | None = None) -> None:
    values = _values() if values is None else values
    times = [START_YEAR + i / 12 for i in range(len(values))] if times is None else times
    frame = pd.DataFrame({"time": times, "value": values})
    frame.to_csv(path, index=False)


def _month(start: str, offset: int) -> str:
    year, month = (int(p) for p in start.split("-"))
    position = year * 12 + month - 1 + offset
    return f"{position // 12:04d}-{position % 12 + 1:02d}"


def _schedule() -> list[dict]:
    rows = []
    for index in range(FOLDS):
        size = INITIAL + index * STEP
        origin = _month("2000-01", size - 1)
        rows.append({"fold": index + 1, "train_start": "2000-01", "training_observations": size,
                     "forecast_origin": origin, "validation_start": _month(origin, 1),
                     "validation_end": _month(origin, HORIZON), "validation_observations": HORIZON})
    return rows


POLICIES = {"learned_parameter_scope": "fit_from_scratch_on_each_training_fold_only",
            "preprocessing_policy": "original_scale", "differencing_policy": "none", "trend_policy": "none",
            "seasonal_policy": "none", "exogenous_policy": "none"}


def _candidate(cid, role, family, study_family, constructor, rank, params):
    return {"candidate_id": cid, "role": role, "family": family, "study_family": study_family,
            "constructor": constructor, "complexity_rank": rank, "seasonal_period": 12, "fixed_params": params,
            "multi_step_strategy": "full_horizon_vector", "policies": dict(POLICIES)}


CATALOG = [
    _candidate("seasonal_naive", "primary_baseline", "seasonal_naive", "SeasonalNaive", "seasonal_naive_rule", 0, {}),
    _candidate("last_value", "secondary_baseline", "naive_last_value", "NaiveLastValue", "last_value_rule", 1, {}),
    _candidate("trend_ols", "candidate", "deterministic_seasonal_trend_ols", "DeterministicSeasonalTrendOLS",
               "statsmodels.regression.linear_model.OLS", 2,
               {"intercept": True, "linear_time_trend": True, "calendar_month_dummies": 11, "reference_month": "January"}),
    _candidate("hw", "candidate", "exponential_smoothing", "ExponentialSmoothing",
               "statsmodels.tsa.holtwinters.ExponentialSmoothing", 3,
               {"trend": None, "damped_trend": False, "seasonal": "add", "seasonal_periods": 12,
                "initialization_method": "estimated", "use_boxcox": False}),
    _candidate("ar", "candidate", "autoreg", "AutoReg", "statsmodels.tsa.ar_model.AutoReg", 4,
               {"lags": [1, 12], "trend": "ct", "seasonal": False}),
    _candidate("sarima", "candidate", "sarimax", "SARIMAX", "statsmodels.tsa.statespace.sarimax.SARIMAX", 5,
               {"order": [1, 0, 0], "seasonal_order": [0, 1, 1, 12], "trend": "n",
                "enforce_stationarity": True, "enforce_invertibility": True}),
]


def _source(pointer: str = "/x") -> dict:
    return {"path": CANONICAL, "locator": f"json_pointer:{pointer}", "rendered_text": "x"}


def _contract(sha: str, size: int, development_sha: str, holdout_sha: str) -> dict:
    return {
        "schema_version": "scientific-study-contract.v4",
        "artifact_kind": "scientific_study_contract",
        "study_identity": {"study_id": "dataset-study-synthetic-forecasting", "dataset_slug": SLUG,
                           "protocol_kind": "univariate_forecasting_expanding_window_model_selection.v1",
                           "study_revision_label": LABEL},
        "source_repository": {"url": "https://example.invalid/study", "revision": REVISION,
                              "pinned_files": [{"path": CANONICAL, "sha256": "2" * 64, "role": "canonical"}]},
        "canonical_run": {"path": CANONICAL, "sha256": "2" * 64, "schema_version": "canonical-run.v1"},
        "dataset_identity": {"source_provider": "synthetic", "source_repository": "synthetic",
                             "source_reference": "synthetic::series", "dataset_name": "Synthetic monthly series",
                             "file_name": "series.csv", "sha256": sha, "size_bytes": size, "row_count": TOTAL,
                             "column_count": 2, "source_columns": ["time", "value"], "read_format": "csv",
                             "read_options": {}, "atlas_local_path": f"data/scientific-studies/{SLUG}/series.csv",
                             "acquisition_note": "synthetic fixture"},
        "scientific_environment": {"python": "3.13.0", "platform": "linux-aarch64",
                                   "core_packages": {"statsmodels": "0.15.0"},
                                   "lock": {"path": "pylock.toml", "sha256": "1" * 64, "format": "pep751"},
                                   "compatibility_policy": {"python": "same_major", "core_packages": "same_major"}},
        "problem": {"problem_type": "univariate_forecasting",
                    "study_problem_identity": {"problem_type": "time_series_forecasting", "forecasting_mode": "univariate"},
                    "forecasting_mode": "univariate",
                    "target": {"column": "level", "source_column": "value", "semantics": "synthetic level",
                               "unit": "units", "value_representation": "float",
                               "value_validation": "numeric_complete_finite"},
                    "exogenous_predictors": 0,
                    "classification_concepts": {"applicable": False, "reason": "forecasting_has_no_classes"}},
        "temporal_source": {"kind": "fractional_year_monthly", "time_column": "time", "value_column": "value",
                            "period_column": "period", "target_column": "level", "frequency": "M",
                            "tolerance": 1e-08, "start": "2000-01", "end": "2007-12", "observations": TOTAL,
                            "rows_sorted_or_filled": False},
        "forecast": {"horizon": HORIZON, "frequency": "M", "seasonal_period": 12,
                     "output": "full_horizon_point_vector_per_origin", "intervals_required": False},
        "temporal_protocol": {
            "development": {"start": "2000-01", "end": "2006-12", "observations": DEVELOPMENT, "sha256": development_sha},
            "final_holdout": {"start": "2007-01", "end": "2007-12", "observations": HOLDOUT, "sha256": holdout_sha,
                              "sealed": True, "used_for_backtesting": False, "used_for_selection": False,
                              "evaluation_count": 1},
            "partition_fingerprint": {"kind": "period_value_csv_sha256", "columns": ["period", "level"],
                                      "float_format": "%.15g", "line_terminator": "\n"},
            "backtesting": {"mode": "expanding_window", "initial_training_observations": INITIAL,
                            "forecast_horizon": HORIZON, "origin_step_observations": STEP, "fold_count": FOLDS,
                            "validation_forecast_count": FOLDS * HORIZON, "validation_targets_overlap": False,
                            "shuffle": False, "refit_policy": "fit_from_scratch_per_fold",
                            "forecast_vector_before_target_access": True, "validation_feedback_within_fold": False,
                            "final_holdout_in_backtest": False, "fold_schedule": _schedule(),
                            "fold_schedule_provenance": "derived"},
        },
        "metrics": {"primary": "mae",
                    "evaluated": [{"metric_id": "mae", "study_name": "mae"}, {"metric_id": "rmse", "study_name": "rmse"},
                                  {"metric_id": "seasonal_mase", "study_name": "seasonal_mase_12",
                                   "parameters": {"seasonal_period": 12}}],
                    "aggregation": "pooled",
                    "diagnostics": [{"field": "fold_mae_std", "kind": "fold_metric_population_std", "metric": "mae"},
                                    {"field": "long_horizon_mae_h7_h12", "kind": "horizon_window_metric",
                                     "metric": "mae", "horizons": [7, 12]}],
                    "excluded": []},
        "candidates": copy.deepcopy(CATALOG),
        "failure_policy": {"programming_error_types": ["TypeError", "AttributeError", "NameError", "ImportError",
                                                       "KeyError"],
                           "programming_error_action": "abort_backtest", "baseline_failure_action": "abort_backtest",
                           "specification_failure_action": "mark_ineligible",
                           "explicit_non_convergence": "specification_failure",
                           "invalid_forecast_output": "specification_failure",
                           "study_guard_failure_kind": "StudyGuardError", "warnings": "recorded_not_failures"},
        "selection": {"kind": "forecasting_pooled_metric_practical_tie", "partition": "expanding_window_backtest",
                      "eligibility": {"complete_forecast_count": FOLDS * HORIZON, "failure_free": True,
                                      "required_finite_fields": ["pooled_mae", "pooled_rmse", "pooled_seasonal_mase",
                                                                 "fold_mae_std", "long_horizon_mae_h7_h12"],
                                      "baseline_margin_required": False, "baselines_rankable": True},
                      "leader": {"field": "pooled_mae", "direction": "min"},
                      "practical_tie": {"field": "pooled_mae", "tolerance": 0.05, "bound": "leader_plus_tolerance",
                                        "unit": "units"},
                      "tie_breakers": [{"field": f, "direction": "lexical_min" if f == "candidate_id" else "min"}
                                       for f in ("pooled_seasonal_mase", "pooled_rmse", "fold_mae_std",
                                                 "long_horizon_mae_h7_h12", "complexity_rank", "candidate_id")],
                      "tie_break_mode": "lexicographic_tuple",
                      "ranking": {"kind": "selected_first_then_leader_field_then_candidate_id",
                                  "includes": "eligible_only"}},
        "finalization": {"kind": "refit_selected_on_development_single_holdout_forecast", "fit_scope": "development",
                         "forecast_origin": "2006-12", "forecast_periods": HOLDOUT, "holdout_evaluation_count": 1,
                         "model_frozen_before_holdout_open": True, "retuning_after_holdout": False,
                         "seasonal_mase_scale": "full_development_history",
                         "primary_baseline_reference": {"role": "primary_baseline",
                                                        "computed_after_final_evaluation": True,
                                                        "used_for_adjustment": False}},
        "tolerance_policy": {"numeric_absolute": 1e-9, "count_absolute": 0, "rationale": "synthetic"},
        "expected_evidence": {
            "values": [{"quantity": "dataset.rows", "expected": TOTAL, "comparison": "count",
                        "reported_decimal_places": None, "source": _source()},
                       {"quantity": "protocol.development.observations", "expected": DEVELOPMENT,
                        "comparison": "count", "reported_decimal_places": None, "source": _source()}],
            "decisions": [{"quantity": "model_selection.catalog", "expected": [c["candidate_id"] for c in CATALOG],
                           "comparison": "exact", "reported_decimal_places": None, "source": _source()}],
            "runtime_identity": []},
        "protocol_parameter_sources": [],
        "evidence_gaps": [],
        "protocol_integrity": {"holdout_procedurally_isolated": True,
                               "holdout_exposure": {"final_holdout_exploration_blind": False,
                                                    "final_holdout_exposure_review": "REV-X",
                                                    "exposed_before": "exploration",
                                                    "used_for_scoring_tuning_or_selection": False,
                                                    "model_frozen_before_final_evaluation": True,
                                                    "holdout_evaluation_count": 1, "description": "synthetic"},
                               "statement": "synthetic"},
        "study_observations": [],
        "limitations": ["synthetic"],
        "authoring": {"authored_by": "test", "authored_at": "2026-01-01T00:00:00Z", "method": "fixture"},
    }


def _fingerprints(values: list[float]) -> tuple[str, str]:
    index = pd.period_range("2000-01", periods=TOTAL, freq="M")
    series = pd.Series(values, index=index, name="level")

    def sha(part):
        return sr.partition_csv_sha256(sf.period_value_frame(part, "period"), "%.15g")

    return sha(series.iloc[:DEVELOPMENT]), sha(series.iloc[DEVELOPMENT:])


def _materialize(root: Path) -> tuple[dict, Path]:
    dataset = root / f"data/scientific-studies/{SLUG}/series.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    _csv(dataset)
    dev_sha, hold_sha = _fingerprints(_values())
    payload = _contract(hashlib.sha256(dataset.read_bytes()).hexdigest(), dataset.stat().st_size, dev_sha, hold_sha)
    return payload, dataset


def _write(root: Path, payload: dict) -> ssc.ScientificStudyContract:
    path = root / ssc.STUDIES_ROOT_RELATIVE / SLUG / LABEL / ssc.CONTRACT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return ssc.load_scientific_study_contract(path, repo_root=root)


RUNTIME = {"python": "3.13.12", "platform": "linux-x86_64", "core_packages": {"statsmodels": "0.15.0"}}


@pytest.fixture()
def study(tmp_path: Path):
    payload, dataset = _materialize(tmp_path)
    return {"root": tmp_path, "payload": payload, "dataset": dataset, "write": lambda data: _write(tmp_path, data)}


def _plan(study_fixture, payload=None, **kwargs):
    contract = study_fixture["write"](payload or study_fixture["payload"])
    plan = sr.build_reproduction(contract, repo_root=study_fixture["root"], runtime=RUNTIME)
    for key, value in kwargs.items():
        setattr(plan, key, value)
    return plan


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("forecasting")
    payload, dataset = _materialize(root)
    contract = _write(root, payload)
    result = sr.build_reproduction(contract, repo_root=root, runtime=RUNTIME).run(run_id="repro-fc")
    return {"root": root, "result": result, "report": result.build_report(), "payload": payload, "dataset": dataset}


# --------------------------------------------------------------------------
# contract v4 and backward compatibility
# --------------------------------------------------------------------------


def test_forecasting_contract_v4_is_schema_semantic_and_capability_valid(study):
    contract = study["write"](study["payload"])
    assert contract.payload["schema_version"] == ssc.SCHEMA_VERSION_V4
    assert ssc.validate_contract_semantics(study["payload"]) == []
    assert ssc.assess_protocol_support(study["payload"]) == []
    assert isinstance(sr.build_reproduction(contract, repo_root=study["root"], runtime=RUNTIME),
                      sf.ForecastingReproduction)


def test_forecasting_contract_is_not_valid_under_v3(study):
    relabeled = dict(study["payload"], schema_version="scientific-study-contract.v3")
    assert ssc.validate_contract_schema(relabeled) != []


@pytest.mark.parametrize("key", ["features", "split", "cross_validation", "threshold_policy", "preprocessing"])
def test_forecasting_contract_rejects_tabular_semantics(study, key):
    payload = copy.deepcopy(study["payload"])
    payload[key] = {"kind": "anything"}
    assert ssc.validate_contract_schema(payload) != []


@pytest.mark.parametrize("path", [("problem", "target", "positive_class"), ("problem", "target", "classes")])
def test_forecasting_contract_rejects_class_concepts(study, path):
    payload = copy.deepcopy(study["payload"])
    payload[path[0]][path[1]][path[2]] = "x"
    assert ssc.validate_contract_schema(payload) != []


def test_tabular_v3_contracts_relabelled_as_v4_validate_unchanged():
    for path in sorted((REPO_ROOT / "pipeline/scientific-studies").glob("*/*/scientific-study-contract.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["schema_version"] not in ("scientific-study-contract.v2", "scientific-study-contract.v3"):
            continue
        relabeled = dict(payload, schema_version=ssc.SCHEMA_VERSION_V4)
        assert ssc.validate_contract_schema(relabeled) == [], path
        assert ssc.validate_contract_semantics(relabeled) == ssc.validate_contract_semantics(payload)


def test_study_problem_vocabulary_maps_to_one_atlas_capability(study):
    identity = study["payload"]["problem"]["study_problem_identity"]
    assert ssc.atlas_problem_type_for(identity) == "univariate_forecasting"
    assert ssc.study_problem_identity("univariate_forecasting") == identity
    payload = copy.deepcopy(study["payload"])
    payload["problem"]["study_problem_identity"]["forecasting_mode"] = "multivariate"
    assert any("STUDY_PROBLEM_IDENTITIES" in e for e in ssc.validate_contract_semantics(payload))


@pytest.mark.parametrize("mutate, needle", [
    (lambda p: p["temporal_protocol"]["backtesting"]["fold_schedule"][1].update(forecast_origin="2004-06"),
     "fold_schedule[1]"),
    (lambda p: p["temporal_protocol"]["backtesting"].update(fold_count=5), "beyond the development window"),
    (lambda p: p["temporal_protocol"]["backtesting"].update(validation_forecast_count=35), "validation_forecast_count"),
    (lambda p: p["temporal_protocol"]["final_holdout"].update(start="2007-02"), "directly after"),
    (lambda p: p["finalization"].update(forecast_origin="2006-11"), "forecast_origin"),
    (lambda p: p["candidates"][0].update(role="candidate"), "primary_baseline"),
    (lambda p: p["candidates"][1].update(complexity_rank=0), "complexity_rank"),
    (lambda p: p["selection"]["tie_breakers"].append({"field": "validation_auc", "direction": "min"}), "validation_auc"),
    (lambda p: p["metrics"]["evaluated"][2]["parameters"].update(seasonal_period=4), "seasonal_period"),
])
def test_forecasting_contract_semantics(study, mutate, needle):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    assert any(needle in error for error in ssc.validate_contract_semantics(payload)), ssc.validate_contract_semantics(payload)


@pytest.mark.parametrize("mutate, element", [
    (lambda p: p["candidates"][3].update(family="prophet"), "candidates[hw].family"),
    (lambda p: p["candidates"][3].update(study_family="HoltWinters"), "candidates[hw].study_family"),
    (lambda p: p["candidates"][3].update(constructor="statsmodels.tsa.arima.model.ARIMA"), "candidates[hw].constructor"),
    (lambda p: p["candidates"][3]["fixed_params"].update(smoothing_level_guess=0.3), "candidates[hw].fixed_params"),
    (lambda p: p["temporal_protocol"]["backtesting"].update(mode="sliding_window"), "temporal_protocol.backtesting.mode"),
    (lambda p: p["failure_policy"].update(programming_error_types=["NotAnError"]), "failure_policy.programming_error_types"),
    (lambda p: p["metrics"]["evaluated"].append({"metric_id": "mape", "study_name": "mape"}), "metrics.evaluated"),
    (lambda p: p["metrics"]["evaluated"][2].pop("parameters"), "metrics.evaluated"),
])
def test_forecasting_capability_gaps_are_explicit(study, mutate, element):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    assert element in {gap["element"] for gap in ssc.assess_protocol_support(payload)}


# --------------------------------------------------------------------------
# metric identity and forecasting families (single authorities)
# --------------------------------------------------------------------------


def test_seasonal_mase_is_a_parameterized_scientific_identity():
    identity = metric_identity.resolve_parameterized_scientific_metric(
        "seasonal_mase", {"seasonal_period": 12}, problem_type="univariate_forecasting")
    assert identity.metric_id == "seasonal_mase" and identity.lower_is_better
    assert identity.parameters["seasonal_period"]["required"] is True
    for bad in ({}, {"seasonal_period": 0}, {"seasonal_period": True}, {"seasonal_period": 12, "lag": 1}):
        with pytest.raises(metric_identity.MetricIdentityError):
            metric_identity.resolve_parameterized_scientific_metric("seasonal_mase", bad)
    with pytest.raises(metric_identity.MetricIdentityError):
        metric_identity.resolve_parameterized_scientific_metric("seasonal_mase", {"seasonal_period": 12},
                                                                problem_type="continuous_regression")
    with pytest.raises(metric_identity.MetricIdentityError):
        metric_identity.resolve_scientific_metric("seasonal_mase_12")


def test_forecasting_families_and_adapters_are_one_authority():
    families = set(model_families.scientific_forecasting_family_ids())
    assert families == set(forecasting_models.ADAPTERS)
    for family_id in families:
        family = model_families.get_family(family_id)
        assert forecasting_models.get_adapter(family_id).constructor == family.forecasting_constructor
        assert family.estimators == {}
    trainable = model_families.native_trainable_family_ids("univariate_forecasting")
    governed = model_families.governed_result_family_ids("univariate_forecasting")
    assert trainable == ("deterministic_seasonal_trend_ols",)
    assert governed == {"deterministic_seasonal_trend_ols"}
    for scientific_only in families - {"deterministic_seasonal_trend_ols"}:
        assert not model_families.get_family(scientific_only).native_training
        assert not model_families.get_family(scientific_only).governed_result_problem_types


# --------------------------------------------------------------------------
# temporal source, partitions and schedule
# --------------------------------------------------------------------------


def test_dataset_sha_is_fail_closed(study):
    data = study["dataset"].read_bytes()
    study["dataset"].write_bytes(data.replace(b"\n", b"\r\n", 1))
    plan = _plan(study)
    result = plan.run(run_id="repro-bad")
    assert not result.executed and not result.dataset_verification["verified"]
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_DATASET_MISMATCH


def _translate(frame, payload):
    return sf.translate_fractional_year_monthly(frame, payload["temporal_source"])


def test_fractional_year_translation_is_exact_and_never_reorders(study):
    frame = pd.read_csv(study["dataset"])
    series, evidence = _translate(frame, study["payload"])
    assert str(series.index[0]) == "2000-01" and str(series.index[-1]) == "2007-12"
    assert evidence["contiguous"] and evidence["unique"] and not evidence["rows_sorted_or_filled"]
    shuffled = frame.iloc[[1, 0] + list(range(2, len(frame)))].reset_index(drop=True)
    with pytest.raises(sr.ScientificReproductionError):
        _translate(shuffled, study["payload"])
    gap = frame.drop(index=5).reset_index(drop=True)
    with pytest.raises(sr.ScientificReproductionError):
        _translate(gap, study["payload"])
    ambiguous = frame.copy()
    ambiguous.loc[3, "time"] += 0.01
    with pytest.raises(sr.ScientificReproductionError, match="integer month"):
        _translate(ambiguous, study["payload"])
    truncated = frame.iloc[:-1]
    with pytest.raises(sr.ScientificReproductionError, match="coverage"):
        _translate(truncated, study["payload"])


def test_development_and_sealed_holdout_boundaries(run):
    observed = run["report"]["temporal_protocol"]["observed"]
    assert observed["development"]["start"] == "2000-01" and observed["development"]["end"] == "2006-12"
    assert observed["development"]["observations"] == DEVELOPMENT
    assert observed["final_holdout"]["start"] == "2007-01" and observed["final_holdout"]["observations"] == HOLDOUT
    assert observed["development_holdout_adjacent"] is True and observed["development_holdout_overlap"] is False
    assert observed["development"]["sha256"] == run["payload"]["temporal_protocol"]["development"]["sha256"]


def test_partition_hash_gate_stops_before_any_backtest(study):
    payload = copy.deepcopy(study["payload"])
    payload["temporal_protocol"]["development"]["sha256"] = "0" * 64
    result = _plan(study, payload).run(run_id="repro-gate")
    assert result.gate_failures and result.gate_failures[0]["gate"] == "temporal_protocol.partitions"
    assert "backtesting_execution" not in result.stages
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_DIVERGENT


def test_expanding_window_schedule(run):
    schedule = run["report"]["temporal_protocol"]["fold_schedule"]
    assert len(schedule) == FOLDS
    assert [f["training_observations"] for f in schedule] == [INITIAL + i * STEP for i in range(FOLDS)]
    assert all(f["validation_observations"] == HORIZON for f in schedule)
    assert schedule[0]["forecast_origin"] == "2003-12" and schedule[-1]["validation_end"] == "2006-12"
    windows = [set(pd.period_range(f["validation_start"], f["validation_end"], freq="M")) for f in schedule]
    assert sum(len(w) for w in windows) == FOLDS * HORIZON == len(set().union(*windows))
    backtesting = run["report"]["temporal_protocol"]["observed"]["backtesting"]
    assert backtesting["validation_targets_overlap"] is False and backtesting["validation_within_development"] is True
    assert backtesting["max_validation_period"] < "2007-01"
    controls = run["report"]["temporal_protocol"]["leakage_controls"]
    assert controls["shuffle"] is False and controls["final_holdout_values_read_during_backtest"] is False


def test_each_fold_scale_uses_only_its_training_history(run, study):
    series, _ = _translate(pd.read_csv(study["dataset"]), study["payload"])
    for fold in run["report"]["temporal_protocol"]["fold_schedule"]:
        training = series.iloc[:fold["training_observations"]]
        manual = float(np.mean(np.abs(training.to_numpy()[12:] - training.to_numpy()[:-12])))
        assert math.isclose(fold["seasonal_mase_scale"], manual, rel_tol=0, abs_tol=1e-12)


class SpyAdapter(forecasting_models.SeasonalNaiveAdapter):
    """Records what every fit/forecast call receives."""

    def __init__(self):
        self.calls = []

    def fit_forecast(self, training, future, params, *, seasonal_period):
        self.calls.append({"training_end": training.index[-1], "training_size": len(training),
                           "future": list(future), "training_values": training.to_numpy().copy()})
        return super().fit_forecast(training, future, params, seasonal_period=seasonal_period)


def test_no_future_target_no_shuffle_and_no_feedback_within_fold(study):
    spy = SpyAdapter()
    candidate = study["payload"]["candidates"][0]
    series, _ = _translate(pd.read_csv(study["dataset"]), study["payload"])
    development = series.iloc[:DEVELOPMENT]
    schedule = sf.fold_schedule(development, study["payload"]["temporal_protocol"]["backtesting"])
    rows, audits = sf.backtest_candidate(candidate, development, schedule, seasonal_period=12, horizon=HORIZON,
                                         abort_on=(TypeError,), adapter=spy)
    assert len(spy.calls) == FOLDS  # one call per fold: the full vector, never step-by-step with feedback
    for call, fold in zip(spy.calls, schedule):
        assert len(call["future"]) == HORIZON and call["training_size"] == fold["training_observations"]
        assert max(call["future"]) > call["training_end"] and min(call["future"]) == call["training_end"] + 1
        np.testing.assert_array_equal(call["training_values"], development.iloc[:fold["training_observations"]].to_numpy())
    assert all(a["target_access_after_full_forecast"] for a in audits)
    assert len(rows) == FOLDS * HORIZON


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------


def test_metrics_match_their_definitions():
    rows = []
    for fold, (truth, pred, scale) in enumerate([([1.0, 2.0], [2.0, 2.0], 2.0), ([3.0, 5.0], [0.0, 5.0], 4.0)], 1):
        for row in sf.error_rows(pd.period_range("2000-01", periods=2, freq="M"), truth, pred, scale):
            rows.append({"fold": fold, **row})
    diagnostics = [{"field": "fold_mae_std", "kind": "fold_metric_population_std", "metric": "mae"},
                   {"field": "late", "kind": "horizon_window_metric", "metric": "mae", "horizons": [2, 2]}]
    aggregate = sf.aggregate_candidate(rows, complete=True, metric_ids=["mae", "rmse", "seasonal_mase"],
                                       diagnostics=diagnostics)
    assert aggregate["pooled_mae"] == pytest.approx((1 + 0 + 3 + 0) / 4)
    assert aggregate["pooled_rmse"] == pytest.approx(math.sqrt((1 + 0 + 9 + 0) / 4))
    assert aggregate["pooled_seasonal_mase"] == pytest.approx((1 / 2 + 0 + 3 / 4 + 0) / 4)
    assert aggregate["fold_mae_std"] == pytest.approx(float(np.std([0.5, 1.5], ddof=0)))
    assert aggregate["late"] == 0.0
    assert aggregate["horizon_mae"] == {"1": pytest.approx(2.0), "2": 0.0}
    assert sf.aggregate_candidate(rows, complete=False, metric_ids=["mae"], diagnostics=[]) == {}


def test_seasonal_scale_is_positive_and_finite():
    series = pd.Series([1.0] * 24, index=pd.period_range("2000-01", periods=24, freq="M"))
    with pytest.raises(sr.ScientificReproductionError):
        sf.seasonal_scale(series, 12)


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------


def _history(n=48):
    return pd.Series(_values(n), index=pd.period_range("2000-01", periods=n, freq="M"), name="level")


def _future(history, h=HORIZON):
    return pd.period_range(history.index[-1] + 1, periods=h, freq="M")


def test_seasonal_naive_and_last_value():
    history = _history()
    naive = forecasting_models.get_adapter("seasonal_naive").fit_forecast(history, _future(history), {}, seasonal_period=12)
    assert list(naive.values) == list(history.to_numpy()[-12:])
    last = forecasting_models.get_adapter("naive_last_value").fit_forecast(history, _future(history), {}, seasonal_period=12)
    assert set(last.values) == {history.iloc[-1]}


def test_deterministic_seasonal_trend_ols_matches_least_squares():
    history = _history()
    params = CATALOG[2]["fixed_params"]
    output = forecasting_models.get_adapter("deterministic_seasonal_trend_ols").fit_forecast(
        history, _future(history), params, seasonal_period=12)
    start = history.index[0].ordinal
    design = lambda idx: np.column_stack([np.ones(len(idx)), idx.asi8 - start] +  # noqa: E731
                                         [(idx.month == m).astype(float) for m in range(2, 13)])
    coefficients = np.linalg.lstsq(design(history.index), history.to_numpy(), rcond=None)[0]
    np.testing.assert_allclose(output.values, design(_future(history)) @ coefficients, atol=1e-9)
    assert output.constructor_arguments["exog_columns"] == 13


@pytest.mark.parametrize("family, cid", [("exponential_smoothing", "hw"), ("autoreg", "ar"), ("sarimax", "sarima")])
def test_statsmodels_constructors_receive_exactly_the_declared_parameters(monkeypatch, family, cid):
    adapter = forecasting_models.get_adapter(family)
    real = forecasting_models._constructor(adapter.constructor)
    seen = []

    def spy(path):
        assert path == adapter.constructor

        def build(endog, **kwargs):
            seen.append({"n": len(endog), **kwargs})
            return real(endog, **kwargs)
        return build

    monkeypatch.setattr(forecasting_models, "_constructor", spy)
    params = next(c for c in CATALOG if c["candidate_id"] == cid)["fixed_params"]
    history = _history()
    output = adapter.fit_forecast(history, _future(history), params, seasonal_period=12)
    assert len(output.values) == HORIZON and all(math.isfinite(v) for v in output.values)
    expected = {k: tuple(v) if isinstance(v, list) and family == "sarimax" else v for k, v in params.items()}
    assert seen == [{"n": 48, **expected}]


def test_specifications_are_refitted_from_scratch_on_every_fold(monkeypatch, study):
    constructed = []
    adapter = forecasting_models.get_adapter("autoreg")
    real = forecasting_models._constructor(adapter.constructor)
    monkeypatch.setattr(forecasting_models, "_constructor",
                        lambda path: (lambda endog, **kw: constructed.append(len(endog)) or real(endog, **kw)))
    series, _ = _translate(pd.read_csv(study["dataset"]), study["payload"])
    development = series.iloc[:DEVELOPMENT]
    schedule = sf.fold_schedule(development, study["payload"]["temporal_protocol"]["backtesting"])
    sf.backtest_candidate(CATALOG[4], development, schedule, seasonal_period=12, horizon=HORIZON, abort_on=(TypeError,))
    assert constructed == [f["training_observations"] for f in schedule]


def test_adapters_reject_undeclared_or_incoherent_parameters():
    with pytest.raises(forecasting_models.ForecastingAdapterError):
        forecasting_models.get_adapter("exponential_smoothing").validate_parameters({"alpha_guess": 1}, 12)
    with pytest.raises(forecasting_models.ForecastingAdapterError):
        forecasting_models.get_adapter("deterministic_seasonal_trend_ols").validate_parameters(
            {**CATALOG[2]["fixed_params"], "calendar_month_dummies": 12}, 12)
    with pytest.raises(forecasting_models.ForecastingAdapterError):
        forecasting_models.get_adapter("unknown")


# --------------------------------------------------------------------------
# failure and eligibility semantics
# --------------------------------------------------------------------------


class RaisingAdapter(forecasting_models.NaiveLastValueAdapter):
    def __init__(self, exc, folds=None):
        self.exc, self.folds, self.calls = exc, folds, 0

    def fit_forecast(self, training, future, params, *, seasonal_period):
        self.calls += 1
        if self.folds is None or self.calls in self.folds:
            raise self.exc
        # A stand-in forecast for the folds that do not fail (the replaced family's params do not apply).
        return super().fit_forecast(training, future, {}, seasonal_period=seasonal_period)


@pytest.mark.parametrize("exc", [TypeError("bad call"), AttributeError("x"), NameError("y"), ImportError("z"),
                                 KeyError("k")])
def test_programming_errors_abort_the_backtest(study, exc):
    plan = _plan(study, adapters={"exponential_smoothing": RaisingAdapter(exc)})
    with pytest.raises(type(exc)):
        plan.run(run_id="repro-abort")


def test_legitimate_fit_failure_makes_the_specification_ineligible(study):
    plan = _plan(study, adapters={"exponential_smoothing": RaisingAdapter(ValueError("singular"), folds={2})})
    result = plan.run(run_id="repro-fail")
    record = next(r for r in result.stages["candidate_results"] if r["candidate_id"] == "hw")
    assert record["eligible"] is False and record["failure_count"] == 1
    assert record["failure_kinds"] == ["ValueError"]
    assert record["failure_categories"] == [forecasting_models.CATEGORY_FIT_OR_FORECAST_EXCEPTION]
    assert "pooled_mae" not in record
    assert "hw" not in result.stages["selection"]["ranking"]


def test_explicit_non_convergence_is_ineligible_in_the_study_vocabulary(study):
    failure = forecasting_models.ForecastingSpecificationFailure(
        forecasting_models.CATEGORY_EXPLICIT_NON_CONVERGENCE, "explicit optimizer non-convergence")
    result = _plan(study, adapters={"sarimax": RaisingAdapter(failure)}).run(run_id="repro-nc")
    record = next(r for r in result.stages["candidate_results"] if r["candidate_id"] == "sarima")
    assert record["eligible"] is False and record["failure_count"] == FOLDS
    assert record["failure_kinds"] == ["StudyGuardError"]
    assert record["failure_categories"] == [forecasting_models.CATEGORY_EXPLICIT_NON_CONVERGENCE]


def test_invalid_forecast_output_is_a_guard_failure():
    with pytest.raises(forecasting_models.ForecastingSpecificationFailure) as info:
        forecasting_models.validate_output([1.0, float("nan")], 2)
    assert info.value.category == forecasting_models.CATEGORY_INVALID_FORECAST_OUTPUT
    with pytest.raises(forecasting_models.ForecastingSpecificationFailure):
        forecasting_models.validate_output([1.0], 2)


def test_sarimax_non_convergence_is_detected_from_the_fit(monkeypatch):
    adapter = forecasting_models.get_adapter("sarimax")

    class Fitted:
        mle_retvals = {"converged": False}

    class Model:
        def __init__(self, endog, **kwargs):
            pass

        def fit(self, disp=False):
            return Fitted()

    monkeypatch.setattr(forecasting_models, "_constructor", lambda path: Model)
    history = _history()
    with pytest.raises(forecasting_models.ForecastingSpecificationFailure) as info:
        adapter.fit_forecast(history, _future(history), CATALOG[5]["fixed_params"], seasonal_period=12)
    assert info.value.category == forecasting_models.CATEGORY_EXPLICIT_NON_CONVERGENCE


def test_baseline_failure_blocks_the_backtest(study):
    result = _plan(study, adapters={"seasonal_naive": RaisingAdapter(ValueError("no season"), folds={1})}).run(
        run_id="repro-baseline")
    assert result.gate_failures[0]["gate"] == "backtest.baseline_complete.seasonal_naive"
    assert "selection" not in result.stages
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_DIVERGENT


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------


def _record(cid, mae, mase=0.5, rmse=1.0, std=0.1, long=1.0, rank=0, eligible=True):
    return {"candidate_id": cid, "eligible": eligible, "pooled_mae": mae, "pooled_seasonal_mase": mase,
            "pooled_rmse": rmse, "fold_mae_std": std, "long_horizon_mae_h7_h12": long, "complexity_rank": rank}


def _rule(study_fixture):
    return study_fixture["payload"]["selection"]


def test_lowest_pooled_mae_leads_and_ranking_is_selected_first(study):
    records = [_record("b", 2.0, rank=1), _record("a", 1.0, rank=0), _record("c", 3.0, rank=2),
               _record("z", 0.1, eligible=False)]
    selection = sf.select_forecasting_practical_tie(records, _rule(study))
    assert selection["selected_candidate_id"] == "a" and selection["finalists"] == ["a"]
    assert selection["ranking"] == ["a", "b", "c"] and selection["deciding_criterion"] == "lowest_leader_metric"


def test_practical_tie_is_inclusive_and_leader_anchored(study):
    records = [_record("leader", 1.0, mase=0.9), _record("inside", 1.05, mase=0.4),
               _record("outside", 1.0500001, mase=0.1)]
    selection = sf.select_forecasting_practical_tie(records, _rule(study))
    assert selection["finalists"] == ["inside", "leader"]
    assert selection["selected_candidate_id"] == "inside"
    assert selection["ranking"] == ["inside", "leader", "outside"]


@pytest.mark.parametrize("records, winner, criterion", [
    ([_record("a", 1.0, mase=0.6), _record("b", 1.01, mase=0.5)], "b", "pooled_seasonal_mase"),
    ([_record("a", 1.0, rmse=2.0), _record("b", 1.01, rmse=1.5)], "b", "pooled_rmse"),
    ([_record("a", 1.0, std=0.3), _record("b", 1.01, std=0.2)], "b", "fold_mae_std"),
    ([_record("a", 1.0, long=1.3), _record("b", 1.01, long=1.2)], "b", "long_horizon_mae_h7_h12"),
    ([_record("a", 1.0, rank=3), _record("b", 1.01, rank=2)], "b", "complexity_rank"),
    ([_record("b", 1.0), _record("a", 1.0)], "a", "candidate_id"),
])
def test_ordered_forecasting_tie_breakers(study, records, winner, criterion):
    selection = sf.select_forecasting_practical_tie(records, _rule(study))
    assert selection["selected_candidate_id"] == winner and selection["deciding_criterion"] == criterion


def test_no_baseline_margin_is_required(study):
    records = [_record("baseline", 1.0, rank=0), _record("model", 1.2, rank=1)]
    assert sf.select_forecasting_practical_tie(records, _rule(study))["selected_candidate_id"] == "baseline"


def test_non_finite_required_field_is_ineligible(study):
    records = [_record("a", 1.0, std=float("nan")), _record("b", 1.2)]
    assert sf.select_forecasting_practical_tie(records, _rule(study))["eligible_candidate_ids"] == ["b"]


# --------------------------------------------------------------------------
# full run, finalization, report
# --------------------------------------------------------------------------


def test_full_run_executes_every_specification_and_reports_v4(run):
    report = run["report"]
    assert run["result"].executed and sr.validate_report_schema(report) == []
    assert report["schema_version"] == sf.REPORT_SCHEMA_VERSION_V4
    assert [r["candidate_id"] for r in report["candidate_results"]] == [c["candidate_id"] for c in CATALOG]
    assert all(r["forecast_rows"] == FOLDS * HORIZON for r in report["candidate_results"] if r["eligible"])
    assert report["selection"]["executed"]["selected_candidate_id"] in {c["candidate_id"] for c in CATALOG}


def test_final_fit_uses_full_development_and_holdout_is_evaluated_once(run):
    report = run["report"]
    fit, forecast, final = report["final_fit"], report["final_forecast"], report["final_evaluation"]
    assert fit["observations"] == DEVELOPMENT and fit["fit_count"] == 1 and fit["frozen_before_holdout_open"]
    assert forecast["forecast_origin"] == "2006-12" and forecast["forecast_call_count"] == 1
    assert forecast["periods"] == [str(p) for p in pd.period_range("2007-01", periods=HOLDOUT, freq="M")]
    assert len(forecast["values"]) == HOLDOUT and forecast["generated_before_holdout_open"]
    assert final["evaluation_count"] == 1 and final["holdout_open_count"] == 1
    assert final["guard_log"] == ["final fit on the development window", "model frozen", "final forecast produced",
                                  "final holdout opened", "final holdout evaluated"]
    assert final["primary_baseline_reference"]["computed_after_final_evaluation"] is True
    assert final["retuned_after_holdout"] is False and final["holdout_used_for_adjustment"] is False


def test_final_seasonal_scale_uses_the_full_development_history(run, study):
    series, _ = _translate(pd.read_csv(study["dataset"]), study["payload"])
    development = series.iloc[:DEVELOPMENT].to_numpy()
    manual = float(np.mean(np.abs(development[12:] - development[:-12])))
    assert run["report"]["final_evaluation"]["seasonal_mase_scale"] == pytest.approx(manual, abs=1e-12)


def test_finalization_guard_enforces_order_and_single_use():
    guard = sf.FinalizationGuard()
    with pytest.raises(sr.ScientificReproductionError):
        guard.authorize_holdout_open()
    guard.register_fit()
    with pytest.raises(sr.ScientificReproductionError):
        guard.register_forecast()
    guard.freeze()
    guard.register_forecast()
    guard.authorize_holdout_open()
    with pytest.raises(sr.ScientificReproductionError):
        guard.authorize_holdout_open()
    with pytest.raises(sr.ScientificReproductionError):
        guard.register_fit()
    guard.register_evaluation()
    with pytest.raises(sr.ScientificReproductionError):
        guard.register_evaluation()


def test_sealed_holdout_values_open_once():
    series = pd.Series([1.0, 2.0], index=pd.period_range("2000-01", periods=2, freq="M"))
    holdout = sf.SealedHoldout(series, "0" * 64)
    guard = sf.FinalizationGuard()
    assert holdout.metadata()["sealed"] is True
    with pytest.raises(sr.ScientificReproductionError):
        holdout.open(guard)
    guard.register_fit(), guard.freeze(), guard.register_forecast()
    assert list(holdout.open(guard)) == [1.0, 2.0]
    with pytest.raises(sr.ScientificReproductionError):
        holdout.open(guard)


def test_every_metric_set_carries_forecasting_provenance(run):
    for metric_set in run["report"]["metric_sets"]:
        provenance = metric_set["provenance"]
        assert provenance["producer_lineage"] == sr.RUN_KIND and provenance["problem_type"] == "univariate_forecasting"
        assert provenance["threshold"] == {"applicable": False, "reason": sf.NOT_APPLICABLE_REASON}
        assert provenance["class_order"] is None and provenance["seasonal_period"] == 12
    scopes = {m["provenance"]["metric_scope"] for m in run["report"]["metric_sets"]}
    assert scopes == {sf.SCOPE_CANDIDATE_BACKTEST, sf.SCOPE_FINAL_HOLDOUT, sf.SCOPE_PRIMARY_BASELINE_HOLDOUT}


def test_report_invents_no_tabular_or_class_concepts(run):
    report = run["report"]
    for absent in ("split", "family_search", "thresholds", "candidate_models", "feature_policy_stage"):
        assert absent not in report
    assert report["problem"]["classification_concepts"]["applicable"] is False
    assert report["holdout_exposure"]["final_holdout_exploration_blind"] is False


def test_independent_expected_values_and_injected_divergence(study):
    payload = copy.deepcopy(study["payload"])
    series, _ = _translate(pd.read_csv(study["dataset"]), payload)
    development = series.iloc[:DEVELOPMENT]
    errors = []
    for fold in sf.fold_schedule(development, payload["temporal_protocol"]["backtesting"]):
        training = development.iloc[:fold["training_observations"]].to_numpy()
        truth = development.iloc[fold["training_observations"]:fold["training_observations"] + HORIZON].to_numpy()
        errors.extend(np.abs(training[-12:] - truth))
    expected_naive_mae = float(np.mean(errors))
    payload["expected_evidence"]["values"].append({
        "quantity": "model_selection.candidates.seasonal_naive.pooled_mae", "expected": expected_naive_mae,
        "comparison": "numeric", "reported_decimal_places": None, "source": _source()})
    report = _plan(study, payload).run(run_id="repro-ok").build_report()
    item = next(c for c in report["comparison"]["values"] if c["quantity"].endswith("seasonal_naive.pooled_mae"))
    assert item["outcome"] in (sr.OUTCOME_EXACT, sr.OUTCOME_WITHIN)
    assert report["reproduction_status"]["status"] == sr.STATUS_REPRODUCED_WITHIN_TOLERANCE
    payload["expected_evidence"]["values"][-1]["expected"] = expected_naive_mae + 1e-6
    divergent = _plan(study, payload).run(run_id="repro-div").build_report()
    assert divergent["reproduction_status"]["status"] == sr.STATUS_DIVERGENT
    assert divergent["divergence_scope"]["diverging_quantities_by_specification"] == {"seasonal_naive": ["pooled_mae"]}


def test_environment_classification_is_separate_from_agreement(study):
    contract = study["write"](study["payload"])
    compatible = sr.build_reproduction(contract, repo_root=study["root"], runtime=RUNTIME)
    assert compatible.environment["classification"] == env.COMPATIBLE
    assert "platform" in compatible.environment["differences"]
    missing = sr.build_reproduction(contract, repo_root=study["root"],
                                    runtime={**RUNTIME, "core_packages": {"statsmodels": None}})
    assert missing.environment["classification"] == env.INCOMPATIBLE
    result = missing.run(run_id="repro-env")
    assert not result.executed
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_ENVIRONMENT_INCOMPATIBLE


def test_report_is_write_once_with_backtest_sidecar(run, tmp_path):
    written = sr.write_reproduction_report(run["report"], repo_root=tmp_path,
                                           backtest_forecasts=run["result"].backtest_forecasts)
    report = json.loads((tmp_path / written["report_path"]).read_text(encoding="utf-8"))
    sidecar = tmp_path / report["backtest_forecasts_reference"]["path"]
    assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == report["backtest_forecasts_reference"]["sha256"]
    assert sr.validate_report_schema(report) == []
    with pytest.raises(sr.ScientificReproductionError, match="write-once"):
        sr.write_reproduction_report(run["report"], repo_root=tmp_path)


def test_lineage_separation_and_answers(run, tmp_path):
    root = tmp_path
    (root / "registry").mkdir()
    (root / "registry/datasets.json").write_text(json.dumps({"datasets": [
        {"dataset_slug": SLUG, "active_release": "release-x"}]}), encoding="utf-8")
    metrics = root / "releases/release-x/metrics/metrics.json"
    metrics.parent.mkdir(parents=True)
    metrics.write_text(json.dumps({"final_holdout_evaluation": {"metrics": [{"name": "mae", "value": 1.0}]},
                                   "backtesting_evaluation": {"metrics": [{"name": "seasonal_mase", "value": 0.5}]}}),
                       encoding="utf-8")
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    view = sr.describe_lineage_separation(run["report"], repo_root=root)
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
    assert {(r["canonical_metric"], r["scope"]) for r in view["rows"]} == {
        ("mae", "final_holdout"), ("seasonal_mase", "expanding_window_backtest")}
    assert all(r["directly_comparable"] is False for r in view["rows"])
    lineage = run["report"]["evidence_lineage"]
    assert lineage[sr.NATIVE_TRAINING_RUN_KIND]["referenced"] is False and lineage[sr.RELEASE_KIND]["referenced"] is False
    answers = sr.answer_reproduction_questions(run["report"])
    assert answers["problem_type"] == "univariate_forecasting" and answers["threshold"]["applicable"] is False
    assert answers["final_holdout_evaluation_count"] == 1


# --------------------------------------------------------------------------
# historical compatibility and the dataset-agnostic guard
# --------------------------------------------------------------------------


HISTORICAL = sorted(p.relative_to(REPO_ROOT).as_posix() for p in
                    list((REPO_ROOT / "pipeline/scientific-studies").rglob("scientific-study-contract.json"))
                    + list((REPO_ROOT / "pipeline/scientific-reproduction-runs").rglob("reproduction-report.json")))


@pytest.mark.parametrize("relative", HISTORICAL)
def test_every_committed_contract_and_report_validates_under_its_own_version(relative):
    payload = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    if relative.endswith("scientific-study-contract.json"):
        assert ssc.validate_contract_schema(payload) == []
    else:
        assert sr.validate_report_schema(payload) == []


@pytest.mark.parametrize("name", ["scientific-study-contract.schema.json", "scientific-study-contract.v2.schema.json",
                                  "scientific-study-contract.v3.schema.json", "scientific-reproduction-report.schema.json",
                                  "scientific-reproduction-report.v2.schema.json",
                                  "scientific-reproduction-report.v3.schema.json"])
def test_historical_schemas_are_byte_intact(name):
    relative = f"pipeline/{name}"
    committed = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"HEAD:{relative}"], capture_output=True, check=False)
    if committed.returncode != 0:
        pytest.skip("not committed")
    assert (REPO_ROOT / relative).read_bytes() == committed.stdout


GENERIC_MODULES = ["pipeline/scientific_forecasting.py", "pipeline/forecasting_models.py",
                   "pipeline/scientific_reproduction.py", "pipeline/scientific_study_contract.py",
                   "pipeline/scientific_environment.py", "pipeline/model_families.py", "pipeline/metric_identity.py"]


@pytest.mark.parametrize("module", GENERIC_MODULES)
def test_generic_forecasting_engine_has_no_dataset_specific_literals(module):
    text = (REPO_ROOT / module).read_text(encoding="utf-8")
    lowered = text.lower()
    for literal in ("nottem", "nottingham", "castle"):
        assert literal not in lowered, f"{module} contains {literal!r}"
    assert not re.search(r"\bseasonal_trend_ols\b", text)
    for number in ("1920", "1938", "1939", "228", "240"):
        assert not re.search(rf"(?<![\w.]){number}(?![\w.])", text), f"{module} contains {number}"
    assert not re.search(r"dataset_slug\s*==", text)
