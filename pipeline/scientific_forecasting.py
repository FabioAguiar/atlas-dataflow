"""Univariate-forecasting protocol runner of the Atlas scientific reproduction.

``pipeline.scientific_reproduction`` holds the infrastructure every problem
type shares -- dataset byte identity, environment classification, the
expected-evidence comparison and its tolerance handling, the reproduction
status, lineage labels, and the write-once report. Its tabular runner
(``Reproduction``) executes holdout splits, cross-validation, candidate search
and a train+validation refit. Forecasting has a different geometry, so it is
executed here, by ``ForecastingReproduction``:

1. the SHA-verified source is translated into a governed monthly
   ``PeriodIndex`` (no sorting, filling or shuffling);
2. the series is cut into a development window and a *sealed* final holdout
   whose values stay inaccessible until the frozen final forecast exists;
3. an expanding-window backtest executes every frozen candidate specification,
   fitted from scratch on each fold's training history; the full multi-step
   forecast vector is produced before any target of that fold is read, and no
   validation target is fed back within a fold;
4. candidates are scored with fold-local seasonal scales, made eligible or
   ineligible by the contract's failure semantics, and selected by the
   contract's pooled-metric practical-tie rule;
5. the selected specification is refitted once on the whole development
   window, forecasts the holdout periods once, and only then is the holdout
   opened and evaluated -- exactly once.

Everything study-specific (periods, counts, horizon, catalog, parameters,
tolerances) comes from the Scientific Study Contract; nothing here branches
on a dataset.
"""

from __future__ import annotations

import builtins
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pipeline import forecasting_models, metric_identity, model_families, scientific_environment
from pipeline.forecasting_preparation import expanding_window_fold_schedule
from pipeline.scientific_study_contract import ScientificStudyContract, study_problem_identity

# Shared infrastructure (imported, never duplicated).
from pipeline.scientific_reproduction import (
    ENGINE_ID,
    ENGINE_VERSION,
    NATIVE_TRAINING_RUN_KIND,
    RELEASE_KIND,
    RUN_KIND,
    STUDY_RUN_KIND,
    ScientificReproductionError,
    _jsonable,
    _sha256_file,
    compare_with_expected_evidence,
    compute_reproduction_status,
    evidence_tiers,
    load_dataset,
    not_applicable,
    partition_csv_sha256,
    verify_dataset_identity,
)

REPORT_SCHEMA_VERSION_V4 = "scientific-reproduction-report.v4"
PROBLEM_TYPE = model_families.UNIVARIATE_FORECASTING

SCOPE_CANDIDATE_BACKTEST = "candidate_expanding_window_backtest"
SCOPE_FINAL_HOLDOUT = "scientific_final_holdout"
SCOPE_PRIMARY_BASELINE_HOLDOUT = "primary_baseline_holdout_reference"

NOT_APPLICABLE_REASON = "univariate_forecasting_point_forecast"


# --------------------------------------------------------------------------
# temporal source and partitions
# --------------------------------------------------------------------------


def translate_fractional_year_monthly(frame: Any, spec: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Translate a fractional-year time column into a monthly ``PeriodIndex``.

    ``year = floor(t)``, ``month = rint((t - year) * 12) + 1``; a coordinate
    farther than ``tolerance`` from an integer month fails closed (it is never
    rounded into a valid month). Rows are neither sorted nor filled: the index
    must already be strictly increasing, unique and contiguous at the declared
    frequency and span exactly the declared start/end/observations.
    """
    import numpy as np
    import pandas as pd

    time_column, value_column = spec["time_column"], spec["value_column"]
    times = pd.to_numeric(frame[time_column], errors="coerce").to_numpy(dtype=float)
    values = pd.to_numeric(frame[value_column], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(times).all() or not np.isfinite(values).all():
        raise ScientificReproductionError("non_finite_temporal_source", "time and value columns must be finite numbers")
    years = np.floor(times).astype(int)
    positions = (times - years) * 12.0
    rounded = np.rint(positions)
    if not np.all(np.abs(positions - rounded) <= float(spec["tolerance"])):
        raise ScientificReproductionError("ambiguous_monthly_coordinate",
                                          "a fractional-year coordinate is not an integer month within tolerance")
    months = rounded.astype(int)
    if not np.all((months >= 0) & (months <= 11)):
        raise ScientificReproductionError("ambiguous_monthly_coordinate", "a fractional-year month is outside 0..11")
    index = pd.PeriodIndex([f"{y:04d}-{m + 1:02d}" for y, m in zip(years, months)], freq=spec["frequency"],
                           name=spec["period_column"])
    evidence = {
        "kind": spec["kind"],
        "strictly_increasing": bool(index.is_monotonic_increasing and index.is_unique),
        "unique": bool(index.is_unique),
        "contiguous": bool(index.equals(pd.period_range(index[0], index[-1], freq=spec["frequency"]))),
        "start": str(index[0]),
        "end": str(index[-1]),
        "observations": int(len(index)),
        "rows_sorted_or_filled": False,
        "shuffled": False,
    }
    for check in ("strictly_increasing", "unique", "contiguous"):
        if not evidence[check]:
            raise ScientificReproductionError("invalid_temporal_index", f"translated index is not {check}")
    declared = (spec["start"], spec["end"], int(spec["observations"]))
    if (evidence["start"], evidence["end"], evidence["observations"]) != declared:
        raise ScientificReproductionError("temporal_coverage_mismatch",
                                          f"translated coverage {evidence['start']}..{evidence['end']} "
                                          f"({evidence['observations']}) differs from the declared {declared}")
    return pd.Series(values, index=index, name=spec["target_column"]), evidence


def period_value_frame(series: Any, period_column: str) -> Any:
    import pandas as pd

    return pd.DataFrame({period_column: series.index.astype(str), series.name: series.to_numpy()})


def seasonal_scale(training: Any, seasonal_period: int) -> float:
    """``mean(|y_t - y_{t-m}|)`` over the given training history only."""
    scale = float(training.diff(seasonal_period).dropna().abs().mean())
    if not math.isfinite(scale) or scale <= 0.0:
        raise ScientificReproductionError("invalid_seasonal_scale",
                                          "the seasonal MASE denominator must be finite and positive")
    return scale


class SealedHoldout:
    """The final holdout: metadata is readable, values open once, after the freeze."""

    def __init__(self, series: Any, fingerprint: str) -> None:
        self._series = series
        self.periods = series.index.copy()
        self.sha256 = fingerprint
        self.open_count = 0

    def metadata(self) -> dict[str, Any]:
        return {"start": str(self.periods[0]), "end": str(self.periods[-1]), "observations": int(len(self.periods)),
                "sha256": self.sha256, "sealed": self.open_count == 0}

    def open(self, guard: "FinalizationGuard") -> Any:
        guard.authorize_holdout_open()
        self.open_count += 1
        return self._series.copy()


class FinalizationGuard:
    """Enforces fit -> freeze -> forecast -> open holdout -> evaluate, each once."""

    def __init__(self) -> None:
        self.fit_count = 0
        self.forecast_count = 0
        self.holdout_open_count = 0
        self.evaluation_count = 0
        self.frozen = False
        self.log: list[str] = []

    def register_fit(self) -> None:
        if self.frozen or self.holdout_open_count:
            raise ScientificReproductionError("fit_after_freeze", "the final model cannot be refitted after the freeze")
        self.fit_count += 1
        self.log.append("final fit on the development window")

    def freeze(self) -> None:
        if self.fit_count != 1:
            raise ScientificReproductionError("freeze_without_single_fit", "exactly one final fit must precede the freeze")
        self.frozen = True
        self.log.append("model frozen")

    def register_forecast(self) -> None:
        if not self.frozen or self.forecast_count or self.holdout_open_count:
            raise ScientificReproductionError("forecast_order_violation",
                                              "the final forecast is produced once, after the freeze, before the holdout opens")
        self.forecast_count += 1
        self.log.append("final forecast produced")

    def authorize_holdout_open(self) -> None:
        if not self.frozen or self.forecast_count != 1 or self.holdout_open_count:
            raise ScientificReproductionError("holdout_open_violation",
                                              "the holdout opens once, after the frozen final forecast exists")
        self.holdout_open_count += 1
        self.log.append("final holdout opened")

    def register_evaluation(self) -> None:
        if self.holdout_open_count != 1 or self.evaluation_count:
            raise ScientificReproductionError("duplicate_final_evaluation", "the final holdout is evaluated exactly once")
        self.evaluation_count += 1
        self.log.append("final holdout evaluated")


def fold_schedule(development: Any, backtesting: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expanding-window folds (``pipeline.forecasting_preparation``) labelled by development periods."""
    periods = [str(p) for p in development.index]
    schedule = expanding_window_fold_schedule(
        initial_training_observations=int(backtesting["initial_training_observations"]),
        origin_step_observations=int(backtesting["origin_step_observations"]),
        forecast_horizon=int(backtesting["forecast_horizon"]),
        fold_count=int(backtesting["fold_count"]),
        period_label=lambda position: periods[position] if 0 <= position < len(periods) else "outside_development",
    )
    return [{"fold": row["fold_index"], "train_start": periods[0], "training_observations": row["training_observations"],
             "forecast_origin": row["forecast_origin"], "validation_start": row["validation_start"],
             "validation_end": row["validation_end"], "validation_observations": row["validation_observations"]}
            for row in schedule]


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------


# Pooled metric formula per canonical metric identity, over forecast rows.
def _pooled(frame: Any, metric_id: str) -> float:
    import numpy as np

    if metric_id == "mae":
        return float(frame.abs_error.mean())
    if metric_id == "rmse":
        return float(np.sqrt(frame.squared_error.mean()))
    if metric_id == "seasonal_mase":
        return float(frame.scaled_abs_error.mean())
    raise ScientificReproductionError("unsupported_forecasting_metric", metric_id)


def _point_metrics(rows: Sequence[Mapping[str, Any]], metric_ids: Sequence[str]) -> dict[str, float]:
    import numpy as np

    formulas = {
        "mae": lambda: float(np.mean([r["abs_error"] for r in rows])),
        "rmse": lambda: float(np.sqrt(np.mean([r["squared_error"] for r in rows]))),
        "seasonal_mase": lambda: float(np.mean([r["scaled_abs_error"] for r in rows])),
    }
    return {metric_id: formulas[metric_id]() for metric_id in metric_ids}


def error_rows(periods: Sequence[Any], truth: Sequence[float], forecast: Sequence[float], scale: float) -> list[dict[str, Any]]:
    rows = []
    for horizon, (period, y_true, y_pred) in enumerate(zip(periods, truth, forecast), 1):
        error = float(y_pred) - float(y_true)
        rows.append({"horizon": horizon, "forecast_period": str(period), "y_true": float(y_true), "y_pred": float(y_pred),
                     "error": error, "abs_error": abs(error), "squared_error": error * error,
                     "seasonal_mase_scale": scale, "scaled_abs_error": abs(error) / scale})
    return rows


def aggregate_candidate(rows: Sequence[Mapping[str, Any]], *, complete: bool, metric_ids: Sequence[str],
                        diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled metrics, fold summaries, horizon MAE and declared diagnostics of one candidate."""
    import numpy as np
    import pandas as pd

    if not complete:
        return {}
    frame = pd.DataFrame(list(rows))
    folds = []
    for fold, group in frame.groupby("fold", sort=True):
        folds.append({"fold": int(fold), **{f"fold_{m}": _pooled(group, m) for m in metric_ids}})
    result: dict[str, Any] = {f"pooled_{m}": _pooled(frame, m) for m in metric_ids}
    result["fold_summaries"] = folds
    result["horizon_mae"] = {str(int(h)): float(g.abs_error.mean()) for h, g in frame.groupby("horizon", sort=True)}
    for diagnostic in diagnostics:
        if diagnostic["kind"] == "fold_metric_population_std":
            result[diagnostic["field"]] = float(np.std([f[f"fold_{diagnostic['metric']}"] for f in folds], ddof=0))
        elif diagnostic["kind"] == "horizon_window_metric":
            low, high = diagnostic["horizons"]
            window = frame[(frame.horizon >= low) & (frame.horizon <= high)]
            result[diagnostic["field"]] = _pooled(window, diagnostic["metric"])
        else:
            raise ScientificReproductionError("unsupported_forecasting_diagnostic", diagnostic["kind"])
    return result


# --------------------------------------------------------------------------
# failure semantics and backtest
# --------------------------------------------------------------------------


def programming_error_types(names: Sequence[str]) -> tuple[type[BaseException], ...]:
    types = []
    for name in names:
        candidate = getattr(builtins, name, None)
        if not (isinstance(candidate, type) and issubclass(candidate, BaseException)):
            raise ScientificReproductionError("unknown_programming_error_type", name)
        types.append(candidate)
    return tuple(types)


def failure_kind(failure: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    """A failure in the study's vocabulary: the study's guard label for a guard
    category (non-convergence, invalid output), otherwise the exception type."""
    if failure["category"] in forecasting_models.GUARD_CATEGORIES:
        return policy["study_guard_failure_kind"]
    return failure["exception_type"]


def backtest_candidate(candidate: Mapping[str, Any], development: Any, schedule: Sequence[Mapping[str, Any]], *,
                       seasonal_period: int, horizon: int, abort_on: tuple[type[BaseException], ...],
                       adapter: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one specification over every fold; returns (forecast rows, fold audits).

    The adapter sees only the fold's training history and the future periods;
    targets are read after the whole forecast vector exists. A contract-declared
    programming-error type (and an adapter capability error) propagates and
    aborts the backtest; any other fit/forecast exception is a recorded
    specification failure on that fold.
    """
    import pandas as pd

    adapter = adapter or forecasting_models.get_adapter(candidate["family"])
    rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for fold in schedule:
        size = int(fold["training_observations"])
        training = development.iloc[:size].copy()
        future = pd.period_range(training.index[-1] + 1, periods=horizon, freq=development.index.freq)
        scale = seasonal_scale(training, seasonal_period)
        audit: dict[str, Any] = {"fold": int(fold["fold"]), "training_observations": size,
                                 "forecast_origin": str(training.index[-1]), "status": "not_run", "failure": None,
                                 "warnings": [], "target_access_after_full_forecast": None}
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                output = adapter.fit_forecast(training, future, candidate["fixed_params"],
                                              seasonal_period=seasonal_period)
            audit["warnings"] = sorted({f"{type(w.message).__name__}: {w.message}" for w in caught})
        except forecasting_models.ForecastingAdapterError:
            raise
        except abort_on:
            raise
        except forecasting_models.ForecastingSpecificationFailure as exc:
            audit.update(status="failed", failure={"category": exc.category, "exception_type": type(exc).__name__,
                                                   "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - a legitimate specification failure by contract
            audit.update(status="failed", failure={"category": forecasting_models.CATEGORY_FIT_OR_FORECAST_EXCEPTION,
                                                   "exception_type": type(exc).__name__, "message": str(exc)})
        else:
            # Targets are read only now, after the full vector was produced.
            truth = development.loc[future]
            audit.update(status="success", target_access_after_full_forecast=True, converged=output.converged)
            for row in error_rows(future, truth.to_numpy(dtype=float), output.values, scale):
                rows.append({"candidate_id": candidate["candidate_id"], "fold": int(fold["fold"]),
                             "forecast_origin": str(training.index[-1]), **row})
        audit["warning_count"] = len(audit["warnings"])
        audit["seasonal_mase_scale"] = scale
        audits.append(audit)
    return rows, audits


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------


def _sort_key(record: Mapping[str, Any], breakers: Sequence[Mapping[str, Any]]) -> tuple:
    key = []
    for breaker in breakers:
        value = record[breaker["field"]]
        if breaker["direction"] == "min":
            key.append(float(value))
        elif breaker["direction"] == "max":
            key.append(-float(value))
        elif breaker["direction"] == "lexical_min":
            key.append(str(value))
        else:
            raise ScientificReproductionError("unsupported_tie_breaker_direction", breaker["direction"])
    return tuple(key)


def select_forecasting_practical_tie(records: Sequence[Mapping[str, Any]], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Pooled-metric leader, leader-anchored practical tie, lexicographic tie-break.

    Eligibility is the backtest's (complete, failure-free, finite required
    fields); there is no margin over a baseline, and baselines are rankable.
    Finalists are sorted by the ordered tie-breakers as one lexicographic key;
    the ranking lists the selected specification first, then every other
    eligible one by the leader metric and candidate id.
    """
    eligibility = rule["eligibility"]
    required = list(eligibility["required_finite_fields"])
    eligible = [dict(r) for r in records if r["eligible"]
                and all(r.get(f) is not None and math.isfinite(float(r[f])) for f in required)]
    if not eligible:
        return {"outcome": "no_eligible_candidate", "eligible_candidate_ids": [], "finalists": [], "ranking": [],
                "selected_candidate_id": None}
    leader_field = rule["leader"]["field"]
    if rule["leader"].get("direction", "min") != "min":
        raise ScientificReproductionError("unsupported_leader_direction", "the forecasting leader metric is minimized")
    best = min(float(r[leader_field]) for r in eligible)
    leader = min(eligible, key=lambda r: (float(r[leader_field]), r["candidate_id"]))
    tie = rule["practical_tie"]
    if tie["bound"] == "leader_plus_tolerance":
        finalists = [r for r in eligible if float(r[tie["field"]]) <= best + float(tie["tolerance"])]
    elif tie["bound"] == "absolute_difference":
        finalists = [r for r in eligible if abs(float(r[tie["field"]]) - best) <= float(tie["tolerance"])]
    else:
        raise ScientificReproductionError("unsupported_practical_tie_bound", tie["bound"])
    breakers = rule["tie_breakers"]
    ranked = sorted(finalists, key=lambda r: _sort_key(r, breakers))
    winner = ranked[0]
    trace = []
    if len(ranked) > 1:
        runner_up = ranked[1]
        for breaker in breakers:
            values = {r["candidate_id"]: _jsonable(r[breaker["field"]]) for r in ranked}
            decided = _sort_key(winner, [breaker]) != _sort_key(runner_up, [breaker])
            trace.append({"criterion": breaker["field"], "direction": breaker["direction"], "values": values,
                          "decides_winner_over_runner_up": decided})
            if decided:
                break
    ranking_rule = rule["ranking"]
    if ranking_rule["kind"] != "selected_first_then_leader_field_then_candidate_id":
        raise ScientificReproductionError("unsupported_ranking_rule", ranking_rule["kind"])
    ranking = sorted(eligible, key=lambda r: (0 if r["candidate_id"] == winner["candidate_id"] else 1,
                                              float(r[leader_field]), r["candidate_id"]))
    return {
        "outcome": "selected",
        "eligible_candidate_ids": [r["candidate_id"] for r in eligible],
        "leader_candidate_id": leader["candidate_id"],
        "best_leader_value": best,
        "practical_tie_tolerance": float(tie["tolerance"]),
        "practical_tie_bound": tie["bound"],
        "finalists": [r["candidate_id"] for r in ranked],
        "practical_tie": len(ranked) > 1,
        "tie_break_mode": rule["tie_break_mode"],
        "tie_break_trace": trace,
        "deciding_criterion": next((t["criterion"] for t in trace if t["decides_winner_over_runner_up"]),
                                   "lowest_leader_metric"),
        "selected_candidate_id": winner["candidate_id"],
        "ranking": [r["candidate_id"] for r in ranking],
    }


FORECASTING_SELECTION_RULES = {"forecasting_pooled_metric_practical_tie": select_forecasting_practical_tie}


def study_specification(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """A contract candidate rendered in the study's specification vocabulary."""
    return {
        "candidate_id": candidate["candidate_id"],
        "role": candidate["role"],
        "family": candidate["study_family"],
        "complexity_rank": candidate["complexity_rank"],
        "constructor": candidate["constructor"],
        "fixed_hyperparameters": dict(candidate["fixed_params"]),
        "seasonal_period": candidate["seasonal_period"],
        "multi_step_strategy": candidate["multi_step_strategy"],
        **dict(candidate["policies"]),
    }


# --------------------------------------------------------------------------
# result and report
# --------------------------------------------------------------------------


_DIVERGING = ("outside_tolerance", "mismatch")


def divergence_scope(comparison: Mapping[str, Any] | None, selection: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Descriptive map of *where* a comparison diverges (the status is never relaxed by it).

    Groups diverging quantities by specification and states whether the
    selection decisions, the selected specification's backtest metrics and the
    final-holdout evidence agree.
    """
    if comparison is None:
        return None
    compared = list(comparison["values"]) + list(comparison["decisions"])
    diverging = [c["quantity"] for c in compared if c["outcome"] in _DIVERGING]
    by_candidate: dict[str, list[str]] = {}
    for quantity in diverging:
        parts = quantity.split(".")
        if quantity.startswith("model_selection.candidates.") and len(parts) > 3:
            by_candidate.setdefault(parts[2], []).append(parts[3])
    selected = (selection or {}).get("selected_candidate_id")

    def agrees(prefixes: tuple[str, ...]) -> bool | None:
        items = [c for c in compared if c["quantity"].startswith(prefixes)]
        return all(c["outcome"] not in _DIVERGING for c in items) if items else None

    return {
        "diverging_quantity_count": len(diverging),
        "diverging_quantities_by_specification": by_candidate,
        "other_diverging_quantities": [q for q in diverging if not q.startswith("model_selection.candidates.")],
        "selection_decisions_agree": agrees(("model_selection.finalists", "model_selection.ranking",
                                             "model_selection.selected_", "model_selection.catalog")),
        "selected_specification_evidence_agrees": agrees(
            (f"model_selection.candidates.{selected}.", "selected_backtest.")) if selected else None,
        "final_holdout_evidence_agrees": agrees(("final_holdout.", "final_model.")),
        "interpretation": "descriptive only: the reproduction status is computed from the full comparison and is "
                          "never relaxed by this summary",
    }


@dataclass
class ForecastingReproductionResult:
    plan: "ForecastingReproduction"
    run_id: str
    created_at: str
    dataset_verification: dict[str, Any]
    executed: bool
    actuals: dict[str, Any] = field(default_factory=dict)
    metric_sets: list[dict[str, Any]] = field(default_factory=list)
    backtest_forecasts: dict[str, Any] = field(default_factory=dict)
    execution_notes: list[str] = field(default_factory=list)
    gate_failures: list[dict[str, Any]] = field(default_factory=list)
    gate_checks: list[dict[str, Any]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)

    # The tabular writer's sidecar slot; forecasting persists backtest forecasts instead.
    search_results: dict[str, Any] = field(default_factory=dict)

    def compare_with_reference(self) -> dict[str, Any] | None:
        if not self.executed:
            return None
        payload = self.plan.contract.payload
        return compare_with_expected_evidence(payload["expected_evidence"], self.actuals, payload["tolerance_policy"])

    def build_report(self) -> dict[str, Any]:
        contract = self.plan.contract
        payload = contract.payload
        comparison = self.compare_with_reference()
        status = compute_reproduction_status(
            protocol_gaps=self.plan.protocol_gaps,
            environment_classification=self.plan.environment["classification"],
            dataset_verified=self.dataset_verification["verified"],
            executed=self.executed,
            comparison=comparison,
            evidence_gaps=payload["evidence_gaps"],
            gate_failures=self.gate_failures,
        )
        status["evidence_tiers"] = evidence_tiers(comparison, self.plan.environment["classification"],
                                                  self.plan.protocol_gaps)
        problem = payload["problem"]
        protocol = payload["temporal_protocol"]
        integrity = payload["protocol_integrity"]
        return {
            "schema_version": REPORT_SCHEMA_VERSION_V4,
            "artifact_kind": "scientific_reproduction_report",
            "run_identity": {"run_kind": RUN_KIND, "run_id": self.run_id, "dataset_slug": contract.dataset_slug,
                             "created_at": self.created_at, "producer": ENGINE_ID, "engine_version": ENGINE_VERSION,
                             "protocol_runner": "pipeline/scientific_forecasting.py"},
            "evidence_lineage": {
                STUDY_RUN_KIND: {"role": "reference_evidence", "study_id": payload["study_identity"]["study_id"],
                                 "source_repository": payload["source_repository"]["url"],
                                 "study_revision": contract.study_revision, "study_contract": contract.reference(),
                                 "canonical_run": payload.get("canonical_run")},
                RUN_KIND: {"role": "independent_atlas_reproduction", "run_id": self.run_id},
                NATIVE_TRAINING_RUN_KIND: {"role": "separate_lineage", "referenced": False,
                                           "relationship": "not an input to and not an output of this reproduction"},
                RELEASE_KIND: {"role": "separate_lineage", "referenced": False,
                               "relationship": "a scientific reproduction never creates, modifies, replaces, "
                                               "or activates an Atlas release"},
            },
            "dataset": {"dataset_slug": contract.dataset_slug,
                        "atlas_local_path": payload["dataset_identity"]["atlas_local_path"],
                        **self.dataset_verification},
            "environment": {
                "scientific_reference": {key: payload["scientific_environment"].get(key)
                                         for key in ("python", "platform", "core_packages", "lock")},
                "reproduction_runtime": self.plan.runtime,
                "compatibility": self.plan.environment,
                "interpretation": ("'same scientific protocol' is established by the comparison; 'byte-identical "
                                   "runtime' only by an exact environment and matching runtime-identity evidence."),
            },
            "protocol_support": {"status": "fully_supported" if not self.plan.protocol_gaps
                                 else "unsupported_elements_present", "gaps": self.plan.protocol_gaps},
            "source_verification": self.plan.source_verification,
            "problem": {
                "problem_type": problem["problem_type"],
                "study_problem_identity": dict(problem["study_problem_identity"]),
                "forecasting_mode": problem["forecasting_mode"],
                "target": dict(problem["target"]),
                "frequency": payload["forecast"]["frequency"],
                "forecast_horizon": payload["forecast"]["horizon"],
                "seasonal_period": payload["forecast"]["seasonal_period"],
                "exogenous_predictors": problem["exogenous_predictors"],
                "classification_concepts": dict(problem["classification_concepts"]),
                "threshold": not_applicable(NOT_APPLICABLE_REASON),
            },
            "temporal_protocol": {
                "source_translation": self.stages.get("source_translation"),
                "declared": {"development": dict(protocol["development"]),
                             "final_holdout": dict(protocol["final_holdout"]),
                             "backtesting": {k: v for k, v in protocol["backtesting"].items() if k != "fold_schedule"}},
                "observed": self.actuals.get("protocol"),
                "fold_schedule": self.stages.get("fold_schedule"),
                "leakage_controls": self.stages.get("leakage_controls"),
            },
            "candidate_catalog": [
                {"candidate_id": c["candidate_id"], "role": c["role"], "family": c["family"],
                 "study_family": c["study_family"], "constructor": c["constructor"],
                 "complexity_rank": c["complexity_rank"], "seasonal_period": c["seasonal_period"],
                 "fixed_params": c["fixed_params"], "multi_step_strategy": c["multi_step_strategy"],
                 "policies": c["policies"]}
                for c in payload["candidates"]
            ],
            "backtesting_execution": self.stages.get("backtesting_execution"),
            "candidate_results": self.stages.get("candidate_results"),
            "selection": {"rule": payload["selection"], "executed": self.stages.get("selection")},
            "final_fit": self.stages.get("final_fit"),
            "final_forecast": self.stages.get("final_forecast"),
            "final_evaluation": self.stages.get("final_evaluation"),
            "metric_sets": self.metric_sets,
            "comparison": comparison,
            "divergence_scope": divergence_scope(comparison, self.stages.get("selection")),
            "gate_checks": self.gate_checks,
            "evidence_gaps": payload["evidence_gaps"],
            "study_observations": payload.get("study_observations", []),
            "protocol_integrity": integrity,
            "holdout_exposure": {
                **dict(integrity["holdout_exposure"]),
                "provenance": "scientific_study_run (inherited study fact, verified against the pinned canonical "
                              "run; not something a reproduction can re-establish)",
                "reproduction_consequence": "the reproduction evaluates the same holdout once and never uses it "
                                            "for selection or adjustment, but it inherits the study's exploration "
                                            "visibility: the holdout is not an exploration-blind external test set",
            },
            "superseded_reference": payload.get("superseded_reference"),
            "execution_notes": self.execution_notes,
            "limitations": payload["limitations"],
            "reproduction_status": status,
            "immutability": {"write_once": True, "historical_artifacts_modified": False, "supersedes": None},
        }


@dataclass
class ForecastingReproduction:
    """Forecasting protocol runner (the tabular one is ``scientific_reproduction.Reproduction``)."""

    contract: ScientificStudyContract
    repo_root: Path
    dataset_path: Path
    runtime: dict[str, Any]
    environment: dict[str, Any]
    protocol_gaps: list[dict[str, Any]]
    source_verification: dict[str, Any]
    adapters: Mapping[str, Any] | None = None

    def run(self, *, run_id: str | None = None, n_jobs: int | None = None,
            allow_incompatible_environment: bool = False) -> ForecastingReproductionResult:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = run_id or "repro-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload = self.contract.payload
        verification = verify_dataset_identity(self.dataset_path, payload["dataset_identity"])
        result = ForecastingReproductionResult(plan=self, run_id=run_id, created_at=created_at,
                                               dataset_verification=verification, executed=False)
        if not verification["verified"]:
            return result
        if self.protocol_gaps:
            result.execution_notes.append("not executed: the protocol contains elements Atlas cannot execute")
            return result
        if self.environment["classification"] == scientific_environment.INCOMPATIBLE and not allow_incompatible_environment:
            result.execution_notes.append("not executed: incompatible environment")
            return result
        if n_jobs not in (None, 1):
            result.execution_notes.append(f"n_jobs={n_jobs} ignored: the forecasting backtest executes sequentially")
        result.executed = bool(self._execute(result))
        return result

    def _adapter(self, family: str) -> Any:
        if self.adapters and family in self.adapters:
            return self.adapters[family]
        return forecasting_models.get_adapter(family)

    def _gate(self, result: ForecastingReproductionResult, gate: str, expected: Any, observed: Any,
              provenance: str) -> bool:
        passed = _jsonable(expected) == _jsonable(observed)
        result.gate_checks.append({"gate": gate, "expected": _jsonable(expected), "observed": _jsonable(observed),
                                   "passed": passed, "expected_provenance": provenance})
        if not passed:
            result.gate_failures.append({"gate": gate, "detail": f"expected {expected!r}, observed {observed!r}"})
            result.execution_notes.append(f"stopped: protocol gate {gate} failed; no later stage was executed")
        return passed

    def _metric_set(self, result: ForecastingReproductionResult, *, metric_set_id: str, scope: str, partition: str,
                    fingerprint: str | None, candidate: Mapping[str, Any], fit_scope: str, scale_policy: str,
                    metrics: Mapping[str, Any]) -> dict[str, Any]:
        payload = self.contract.payload
        return {
            "metric_set_id": metric_set_id,
            "provenance": {
                "producer_lineage": RUN_KIND,
                "metric_scope": scope,
                "problem_type": PROBLEM_TYPE,
                "run_id": result.run_id,
                "study_revision": self.contract.study_revision,
                "study_contract_sha256": self.contract.sha256,
                "dataset_sha256": payload["dataset_identity"]["sha256"],
                "partition": partition,
                "partition_temporal_fingerprint": fingerprint,
                "candidate_id": candidate["candidate_id"],
                "family": candidate["family"],
                "fit_scope": fit_scope,
                "seasonal_mase_scale_policy": scale_policy,
                "seasonal_period": payload["forecast"]["seasonal_period"],
                "threshold": not_applicable(NOT_APPLICABLE_REASON),
                "class_order": None,
                "protocol_kind": payload["study_identity"]["protocol_kind"],
            },
            "metrics": _jsonable(dict(metrics)),
        }

    def _execute(self, result: ForecastingReproductionResult) -> bool:
        import pandas as pd

        payload = self.contract.payload
        actuals = result.actuals
        source_spec = payload["temporal_source"]
        protocol = payload["temporal_protocol"]
        backtesting = protocol["backtesting"]
        forecast = payload["forecast"]
        horizon, seasonal_period = int(forecast["horizon"]), int(forecast["seasonal_period"])
        metric_ids = [m["metric_id"] for m in payload["metrics"]["evaluated"]]
        fingerprint_spec = protocol["partition_fingerprint"]
        policy = payload["failure_policy"]
        abort_on = programming_error_types(policy["programming_error_types"])

        # 1. Source identity and temporal translation.
        raw = load_dataset(self.dataset_path, payload["dataset_identity"])
        columns = list(raw.columns)
        actuals["dataset"] = {"sha256": result.dataset_verification["observed_sha256"], "rows": int(raw.shape[0]),
                              "columns": int(raw.shape[1]), "source_columns": columns}
        if not self._gate(result, "dataset.source_columns", payload["dataset_identity"]["source_columns"], columns,
                          "scientific_study_contract.dataset_identity"):
            return False
        series, translation = translate_fractional_year_monthly(raw, source_spec)
        result.stages["source_translation"] = translation
        target = payload["problem"]["target"]
        study_identity = study_problem_identity(PROBLEM_TYPE)
        actuals["target"] = {"column": series.name, "unit": target["unit"], "semantics": target["semantics"],
                             "frequency": source_spec["frequency"], "forecast_horizon": horizon, **study_identity}

        # 2. Development window and sealed final holdout.
        development = series.loc[protocol["development"]["start"]:protocol["development"]["end"]].copy()
        holdout_series = series.loc[protocol["final_holdout"]["start"]:protocol["final_holdout"]["end"]].copy()
        # From here on the holdout values exist only inside the SealedHoldout.
        del series
        period_column = source_spec["period_column"]
        development_sha = partition_csv_sha256(period_value_frame(development, period_column),
                                               fingerprint_spec["float_format"])
        holdout = SealedHoldout(holdout_series, partition_csv_sha256(period_value_frame(holdout_series, period_column),
                                                                     fingerprint_spec["float_format"]))
        del holdout_series
        adjacent = bool(len(development) and len(holdout.periods) and development.index[-1] + 1 == holdout.periods[0])
        observed_protocol = {
            "development": {"start": str(development.index[0]), "end": str(development.index[-1]),
                            "observations": int(len(development)), "sha256": development_sha},
            "final_holdout": {key: value for key, value in holdout.metadata().items() if key != "sealed"},
            "development_holdout_adjacent": adjacent,
            "development_holdout_overlap": bool(len(development.index.intersection(holdout.periods))),
        }
        actuals["protocol"] = observed_protocol
        if not self._gate(result, "temporal_protocol.partitions",
                          {"development": {k: protocol["development"][k] for k in ("start", "end", "observations", "sha256")},
                           "final_holdout": {k: protocol["final_holdout"][k] for k in ("start", "end", "observations", "sha256")},
                           "development_holdout_adjacent": True, "development_holdout_overlap": False},
                          observed_protocol, "scientific_study_contract.temporal_protocol (verified against the "
                                             "study's canonical run by protocol_parameter_sources)"):
            return False

        # 3. Expanding-window schedule.
        schedule = fold_schedule(development, backtesting)
        validation_periods = [p for f in schedule for p in
                              pd.period_range(f["validation_start"], f["validation_end"], freq=development.index.freq)]
        observed_backtesting = {
            "mode": backtesting["mode"],
            "initial_training_observations": schedule[0]["training_observations"] if schedule else None,
            "forecast_horizon": horizon,
            "origin_step_observations": (schedule[1]["training_observations"] - schedule[0]["training_observations"]
                                         if len(schedule) > 1 else backtesting["origin_step_observations"]),
            "fold_count": len(schedule),
            "validation_forecast_count": len(validation_periods),
            "validation_targets_overlap": len(set(validation_periods)) != len(validation_periods),
            "max_validation_period": str(max(validation_periods)) if validation_periods else None,
            "validation_within_development": bool(validation_periods)
            and max(validation_periods) <= development.index[-1],
        }
        observed_protocol["backtesting"] = observed_backtesting
        declared_schedule = backtesting["fold_schedule"]
        if not self._gate(result, "temporal_protocol.backtesting.fold_schedule", declared_schedule, schedule,
                          "scientific_study_contract (derived from the pinned backtesting parameters)"):
            return False
        if not self._gate(result, "temporal_protocol.backtesting.validation_forecast_count",
                          backtesting["validation_forecast_count"], observed_backtesting["validation_forecast_count"],
                          "scientific_study_contract.temporal_protocol.backtesting"):
            return False
        scales = {f["fold"]: seasonal_scale(development.iloc[:f["training_observations"]], seasonal_period)
                  for f in schedule}
        result.stages["fold_schedule"] = [{**f, "seasonal_mase_scale": scales[f["fold"]]} for f in schedule]
        result.stages["leakage_controls"] = {
            "shuffle": False,
            "fit_from_scratch_per_fold": True,
            "full_forecast_vector_before_target_access": True,
            "validation_target_feedback_within_fold": False,
            "seasonal_scale_from_fold_training_history_only": True,
            "final_holdout_values_read_during_backtest": False,
            "max_validation_period": observed_backtesting["max_validation_period"],
            "final_holdout_start": holdout.metadata()["start"],
        }

        # 4. Backtest every frozen specification.
        diagnostics = payload["metrics"]["diagnostics"]
        expected_rows = int(backtesting["validation_forecast_count"])
        records: list[dict[str, Any]] = []
        execution: list[dict[str, Any]] = []
        for candidate in payload["candidates"]:
            rows, audits = backtest_candidate(candidate, development, schedule, seasonal_period=seasonal_period,
                                              horizon=horizon, abort_on=abort_on,
                                              adapter=self._adapter(candidate["family"]))
            failures = [a["failure"] for a in audits if a["failure"]]
            complete = len(rows) == expected_rows and not failures
            if candidate["role"].endswith("baseline") and not complete:
                self._gate(result, f"backtest.baseline_complete.{candidate['candidate_id']}", True, False,
                           "scientific_study_contract.failure_policy.baseline_failure_action")
                return False
            aggregate = aggregate_candidate(rows, complete=complete, metric_ids=metric_ids, diagnostics=diagnostics)
            kinds = sorted({failure_kind(f, policy) for f in failures})
            record = {"candidate_id": candidate["candidate_id"], "role": candidate["role"],
                      "family": candidate["family"], "study_family": candidate["study_family"],
                      "complexity_rank": candidate["complexity_rank"], "complete": complete, "eligible": complete,
                      "forecast_rows": len(rows), "folds_completed": sum(a["status"] == "success" for a in audits),
                      "failure_count": len(failures), "failure_kinds": kinds,
                      "failure_categories": sorted({f["category"] for f in failures}),
                      "warning_count": sum(a["warning_count"] for a in audits), **aggregate}
            records.append(record)
            execution.append({"candidate_id": candidate["candidate_id"], "family": candidate["family"],
                              "constructor": candidate["constructor"], "folds": audits})
            result.backtest_forecasts[candidate["candidate_id"]] = rows
            if complete:
                result.metric_sets.append(self._metric_set(
                    result, metric_set_id=f"backtest.{candidate['candidate_id']}", scope=SCOPE_CANDIDATE_BACKTEST,
                    partition="expanding_window_backtest", fingerprint=development_sha, candidate=candidate,
                    fit_scope="fold_local_expanding_window", scale_policy="fold_training_history_only",
                    metrics={k: v for k, v in aggregate.items() if k != "fold_summaries"}))
        result.stages["backtesting_execution"] = execution
        result.stages["candidate_results"] = records

        # 5. Selection.
        rule = payload["selection"]
        selection = FORECASTING_SELECTION_RULES[rule["kind"]](records, rule)
        result.stages["selection"] = selection
        catalog = {c["candidate_id"]: c for c in payload["candidates"]}
        leader_field = rule["leader"]["field"]
        actuals["model_selection"] = {
            "catalog": list(catalog),
            "primary_metric": payload["metrics"]["primary"],
            "practical_tie_tolerance": float(rule["practical_tie"]["tolerance"]),
            "tie_break_order": [b.get("study_name", b["field"]) for b in rule["tie_breakers"]],
            "best_leader_value": selection.get("best_leader_value"),
            "finalists": selection["finalists"],
            "ranking": selection["ranking"],
            "selected_candidate_id": selection["selected_candidate_id"],
            "candidates": {
                r["candidate_id"]: {
                    "role": r["role"], "family": r["study_family"], "complexity_rank": r["complexity_rank"],
                    "eligible": r["eligible"], "failure_count": r["failure_count"], "failure_kinds": r["failure_kinds"],
                    **{key: r[key] for key in [f"pooled_{m}" for m in metric_ids] + [d["field"] for d in diagnostics]
                       if key in r},
                }
                for r in records
            },
            "specifications": {cid: {"constructor": c["constructor"], "fixed_params": dict(c["fixed_params"])}
                               for cid, c in catalog.items()},
        }
        selected_id = selection["selected_candidate_id"]
        if selected_id is None:
            result.execution_notes.append("no specification satisfied the eligibility rule")
            return True
        selected = catalog[selected_id]
        selected_record = next(r for r in records if r["candidate_id"] == selected_id)
        actuals["model_selection"]["selected_family"] = selected["study_family"]
        actuals["model_selection"]["selected_specification"] = study_specification(selected)
        actuals["selected_backtest"] = {m: selected_record[f"pooled_{m}"] for m in metric_ids}
        actuals["selected_backtest"]["leader_field"] = selected_record[leader_field]

        # 6. Finalization: fit once on development, freeze, forecast once, open once, evaluate once.
        finalization = payload["finalization"]
        guard = FinalizationGuard()
        adapter = self._adapter(selected["family"])
        guard.register_fit()
        try:
            output = adapter.fit_forecast(development.copy(), holdout.periods, selected["fixed_params"],
                                          seasonal_period=seasonal_period)
        except forecasting_models.ForecastingSpecificationFailure as exc:
            self._gate(result, "finalization.selected_specification_fits", True, False, str(exc))
            return False
        guard.freeze()
        guard.register_forecast()
        forecast_origin = str(development.index[-1])
        result.stages["final_fit"] = {
            "candidate_id": selected_id, "family": selected["family"], "study_family": selected["study_family"],
            "constructor": selected["constructor"], "constructor_arguments": _jsonable(dict(output.constructor_arguments)),
            "fit_scope": finalization["fit_scope"], "start": str(development.index[0]), "end": forecast_origin,
            "observations": int(len(development)), "development_sha256": development_sha, "fit_count": guard.fit_count,
            "frozen_before_holdout_open": guard.frozen and guard.holdout_open_count == 0,
            "selected_on": "expanding_window_backtest", "retuned_after_selection": False,
        }
        result.stages["final_forecast"] = {
            "forecast_origin": forecast_origin, "forecast_call_count": guard.forecast_count,
            "periods": [str(p) for p in holdout.periods], "values": list(output.values),
            "generated_before_holdout_open": holdout.open_count == 0,
        }
        truth = holdout.open(guard)
        guard.register_evaluation()
        scale = seasonal_scale(development, seasonal_period)
        rows = error_rows(holdout.periods, truth.to_numpy(dtype=float), output.values, scale)
        final_metrics = _point_metrics(rows, metric_ids)
        # Primary-baseline reference: computed after the single final evaluation, never fed back.
        baseline = next(c for c in payload["candidates"] if c["role"] == finalization["primary_baseline_reference"]["role"])
        baseline_output = self._adapter(baseline["family"]).fit_forecast(
            development.copy(), holdout.periods, baseline["fixed_params"], seasonal_period=seasonal_period)
        baseline_rows = error_rows(holdout.periods, truth.to_numpy(dtype=float), baseline_output.values, scale)
        baseline_metrics = _point_metrics(baseline_rows, metric_ids)
        result.stages["final_evaluation"] = {
            "evaluation_count": guard.evaluation_count, "holdout_open_count": holdout.open_count,
            "holdout_sha256": holdout.sha256, "seasonal_mase_scale": scale,
            "seasonal_mase_scale_policy": finalization["seasonal_mase_scale"],
            "metrics": final_metrics, "points": rows,
            "model_frozen_before_holdout_open": True, "holdout_used_for_adjustment": False,
            "holdout_used_in_selection": False, "retuned_after_holdout": False,
            "guard_log": list(guard.log),
            "primary_baseline_reference": {
                "candidate_id": baseline["candidate_id"], "role": baseline["role"], "metrics": baseline_metrics,
                "forecasts": [{"forecast_period": r["forecast_period"], "y_pred": r["y_pred"]} for r in baseline_rows],
                "model_minus_baseline": {m: final_metrics[m] - baseline_metrics[m] for m in metric_ids},
                "computed_after_final_evaluation": True, "used_for_adjustment": False,
            },
        }
        result.metric_sets.append(self._metric_set(
            result, metric_set_id=f"final_holdout.{selected_id}", scope=SCOPE_FINAL_HOLDOUT, partition="final_holdout",
            fingerprint=holdout.sha256, candidate=selected, fit_scope="full_development",
            scale_policy=finalization["seasonal_mase_scale"], metrics=final_metrics))
        result.metric_sets.append(self._metric_set(
            result, metric_set_id=f"final_holdout_reference.{baseline['candidate_id']}",
            scope=SCOPE_PRIMARY_BASELINE_HOLDOUT, partition="final_holdout", fingerprint=holdout.sha256,
            candidate=baseline, fit_scope="full_development", scale_policy=finalization["seasonal_mase_scale"],
            metrics=baseline_metrics))
        observed_protocol.update({
            "holdout_used_in_selection": False,
            "holdout_used_for_adjustment": False,
            "model_frozen_before_holdout_open": bool(result.stages["final_fit"]["frozen_before_holdout_open"]),
            "holdout_evaluation_count": guard.evaluation_count,
        })
        actuals["final_holdout"] = {
            "forecast_origin": forecast_origin,
            "metrics": final_metrics,
            "primary_baseline_metrics": baseline_metrics,
            "forecasts": {f"h{r['horizon']:02d}": {"forecast_period": r["forecast_period"], "y_pred": r["y_pred"]}
                          for r in rows},
        }
        actuals["final_model"] = {"training_observations": int(len(development))}
        return True


# --------------------------------------------------------------------------
# answers and lineage view
# --------------------------------------------------------------------------


def answer_forecasting_questions(report: Mapping[str, Any]) -> dict[str, Any]:
    selection = (report.get("selection") or {}).get("executed") or {}
    temporal = report.get("temporal_protocol") or {}
    final = report.get("final_evaluation") or {}
    comparison = report.get("comparison") or {"values": [], "decisions": []}
    compared = comparison["values"] + comparison["decisions"]
    forecast_items = [c for c in compared if c["quantity"].startswith("final_holdout.forecasts.")]
    return {
        "problem_type": (report.get("problem") or {}).get("problem_type"),
        "study_problem_identity": (report.get("problem") or {}).get("study_problem_identity"),
        "fold_schedule": temporal.get("fold_schedule"),
        "which_specifications_were_executed": [c["candidate_id"] for c in report.get("candidate_results") or []],
        "which_specifications_were_ineligible": {
            c["candidate_id"]: {"failure_count": c["failure_count"], "failure_kinds": c["failure_kinds"],
                                "failure_categories": c["failure_categories"]}
            for c in report.get("candidate_results") or [] if not c["eligible"]},
        "finalists": selection.get("finalists"),
        "ranking": selection.get("ranking"),
        "tie_break_trace": selection.get("tie_break_trace"),
        "which_model_was_selected": selection.get("selected_candidate_id"),
        "final_fit": report.get("final_fit"),
        "final_holdout_evaluation_count": final.get("evaluation_count"),
        "final_metrics": final.get("metrics"),
        "did_all_forecast_points_match": (all(c["outcome"] in ("exact_at_reported_precision", "within_tolerance")
                                              for c in forecast_items) if forecast_items else None),
        "holdout_exposure": report.get("holdout_exposure"),
        "evidence_tiers": (report.get("reproduction_status") or {}).get("evidence_tiers"),
    }


def describe_forecasting_lineage_separation(report: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Read-only side-by-side view of the scientific reproduction and the native lineage.

    Reads the dataset's native execution contract and the active release's
    metrics; writes nothing. The two lineages may share geometry and even the
    model form, yet remain different experiments: native training fixes one
    configuration, the reproduction independently selects among the catalog.
    """
    import json

    root = Path(repo_root)
    slug = report["run_identity"]["dataset_slug"]
    registry = json.loads((root / "registry/datasets.json").read_text(encoding="utf-8"))
    entry = next((d for d in registry["datasets"] if d["dataset_slug"] == slug), None)
    contract_path = root / "contracts" / slug / "execution-contract.json"
    native_contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else None
    release_metrics = None
    if entry is not None:
        metrics_path = root / "releases" / entry["active_release"] / "metrics" / "metrics.json"
        if metrics_path.is_file():
            release_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    selection = (report.get("selection") or {}).get("executed") or {}
    selected = selection.get("selected_candidate_id")
    records = {r["candidate_id"]: r for r in report.get("candidate_results") or []}
    final = report.get("final_evaluation") or {}
    rows = []
    if release_metrics is not None:
        native_backtest = {m["name"]: m["value"] for m in
                           (release_metrics.get("backtesting_evaluation") or {}).get("pooled_metrics", [])}
        native_holdout = {m["name"]: m["value"] for m in
                          (release_metrics.get("final_holdout_evaluation") or {}).get("metrics", [])}
        for scope, native_values, scientific_values in (
                ("expanding_window_backtest", native_backtest,
                 {k.removeprefix("pooled_"): v for k, v in (records.get(selected) or {}).items() if k.startswith("pooled_")}),
                ("final_holdout", native_holdout, final.get("metrics") or {})):
            for name, value in native_values.items():
                canonical = metric_identity.resolve_training_metric(name).metric_id
                reproduced = scientific_values.get(canonical)
                rows.append({
                    "canonical_metric": canonical, "scope": scope,
                    "atlas_native_release": {"value": value, "provenance": {
                        "lineage": RELEASE_KIND, "release_id": entry["active_release"],
                        "training_run_id": (release_metrics.get("training_run_identity") or {}).get("run_id")}},
                    "scientific_reproduction": {"value": reproduced, "provenance": {
                        "lineage": RUN_KIND, "run_id": report["run_identity"]["run_id"], "candidate_id": selected}},
                    "absolute_difference": abs(value - reproduced) if reproduced is not None else None,
                    "directly_comparable": False,
                })
    policy = (native_contract or {}).get("training_policy") or (native_contract or {}).get("modeling_constraints") or {}
    differences = [
        {"fact": "model_selection",
         "atlas_native": "fixed_configuration: one assumed specification, model_selection_performed = false",
         "scientific_reproduction": f"{(report.get('selection') or {}).get('rule', {}).get('kind')}: "
                                    f"{len(report.get('candidate_catalog') or [])} frozen specifications executed "
                                    f"and ranked; selected {selected}"},
        {"fact": "native_policy_declared", "atlas_native": _jsonable(policy) or None, "scientific_reproduction": None},
        {"fact": "implementation",
         "atlas_native": "pipeline.training native deterministic seasonal-trend OLS",
         "scientific_reproduction": (report.get("final_fit") or {}).get("constructor")},
        {"fact": "source_identity",
         "atlas_native": "native raw boundary (row count / column order checks)",
         "scientific_reproduction": f"pinned bytes SHA-256 {report['dataset'].get('observed_sha256')}"},
    ]
    return {
        "dataset_slug": slug,
        "active_release": entry["active_release"] if entry else None,
        "native_execution_contract_sha256": _sha256_file(contract_path) if native_contract else None,
        "rows": rows,
        "protocol_differences": differences,
        "interpretation": (
            "Both lineages use the same development/holdout geometry and expanding-window schedule, and the native "
            "fixed model has the same form as the specification the reproduction selected, so their numbers can "
            "nearly coincide. They are still different experiments: native training assumes the specification, "
            "the scientific reproduction independently evaluates the frozen catalog and selects it. Neither "
            "replaces the other."
        ),
    }
