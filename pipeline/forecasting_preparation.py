"""Capability-level helpers for univariate-forecasting temporal preparation.

These implement the generic parts of preparing a single monthly series for
``candidate-preparation-recipe.v2`` / ``execution_contract.v2``: translating a
fractional-year time index into governed monthly calendar periods, computing
an expanding-window backtesting fold schedule, and the temporal-integrity
confirmations the recipe records.

Every study-specific value -- the first year, series length, holdout size,
initial window, origin step, horizon, fold count, and field names -- is a
caller parameter taken from the dataset's own study/recipe; nothing here
knows a dataset.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Mapping, Sequence

MONTHS_PER_YEAR = 12
FRACTIONAL_YEAR_TOLERANCE = 1e-6


def monthly_period_label(first_year: int, position: int) -> str:
    """``YYYY-MM`` calendar period of the ``position``-th month (0-based) of a
    monthly series starting in January of ``first_year``."""
    year = first_year + position // MONTHS_PER_YEAR
    month = position % MONTHS_PER_YEAR + 1
    return f"{year:04d}-{month:02d}"


def translate_fractional_year_monthly_series(
    raw_rows: Iterable[Mapping[str, Any]],
    *,
    first_year: int,
    time_field: str,
    value_field: str,
    index_field: str,
    target_field: str,
    tolerance: float = FRACTIONAL_YEAR_TOLERANCE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Translate a fractional-year ``time_field`` into monthly periods.

    Each row must sit exactly (within ``tolerance``) at its expected monthly
    sequence position ``first_year + position / 12`` -- a malformed timestamp
    is reported, never rounded into a valid month, and rows are never sorted
    or filled. Returns ``(prepared_rows, translation_errors)``; the caller
    decides how to block on errors.
    """
    prepared_rows: list[dict[str, Any]] = []
    translation_errors: list[str] = []
    for position, row in enumerate(raw_rows):
        raw_time_value = float(row[time_field])
        raw_target_value = float(row[value_field])
        expected_fractional_year = first_year + position / float(MONTHS_PER_YEAR)
        if abs(raw_time_value - expected_fractional_year) > tolerance:
            translation_errors.append(
                f"row {position}: raw time value {raw_time_value!r} does not map "
                f"unambiguously to the expected monthly sequence position {position} "
                f"(expected approximately {expected_fractional_year!r})."
            )
            continue
        prepared_rows.append({
            index_field: monthly_period_label(first_year, position),
            target_field: raw_target_value,
        })
    return prepared_rows, translation_errors


def expanding_window_fold_schedule(
    *,
    initial_training_observations: int,
    origin_step_observations: int,
    forecast_horizon: int,
    fold_count: int,
    period_label: Callable[[int], str],
) -> list[dict[str, Any]]:
    """Expanding-window backtesting folds: fold ``k`` trains on the first
    ``initial + (k - 1) * step`` observations and validates the next
    ``forecast_horizon`` observations. ``period_label`` maps a 0-based series
    position to its index value."""
    fold_schedule: list[dict[str, Any]] = []
    for fold_index in range(1, fold_count + 1):
        training_observations = initial_training_observations + (fold_index - 1) * origin_step_observations
        validation_start_position = training_observations
        validation_end_position = training_observations + forecast_horizon - 1
        fold_schedule.append({
            "fold_index": fold_index,
            "training_observations": training_observations,
            "forecast_origin": period_label(training_observations - 1),
            "validation_start": period_label(validation_start_position),
            "validation_end": period_label(validation_end_position),
            "validation_observations": forecast_horizon,
        })
    return fold_schedule


def temporal_integrity_confirmations(
    periods: Sequence[str],
    target_values: Sequence[Any],
    *,
    period_label: Callable[[int], str],
) -> dict[str, bool]:
    """The recipe's ``temporal_integrity`` confirmations for a prepared series."""
    return {
        "strictly_increasing_index": list(periods) == sorted(periods),
        "unique_index": len(set(periods)) == len(periods),
        "frequency_contiguous": list(periods) == [period_label(i) for i in range(len(periods))],
        "target_missing_values_absent": all(value is not None for value in target_values),
        "target_values_finite": all(math.isfinite(value) for value in target_values),
    }
