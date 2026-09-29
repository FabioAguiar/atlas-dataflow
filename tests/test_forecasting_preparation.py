"""Capability-level forecasting temporal preparation helpers
(pipeline/forecasting_preparation.py). Study-specific geometry is always a
caller parameter."""

import json
import math
import sys
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.forecasting_preparation import (  # noqa: E402
    expanding_window_fold_schedule,
    monthly_period_label,
    temporal_integrity_confirmations,
    translate_fractional_year_monthly_series,
)


def test_monthly_period_label_for_any_start_year():
    assert monthly_period_label(2001, 0) == "2001-01"
    assert monthly_period_label(2001, 11) == "2001-12"
    assert monthly_period_label(2001, 12) == "2002-01"


def test_translation_maps_positions_and_reports_malformed_timestamps_without_rounding():
    rows = [
        {"t": "2010.0", "y": "1.5"},
        {"t": str(2010 + 1 / 12), "y": "2.5"},
        {"t": "2010.5", "y": "3.5"},  # position 2 expects 2010 + 2/12
    ]
    prepared, errors = translate_fractional_year_monthly_series(
        rows, first_year=2010, time_field="t", value_field="y", index_field="month", target_field="sales",
    )
    assert prepared == [{"month": "2010-01", "sales": 1.5}, {"month": "2010-02", "sales": 2.5}]
    assert len(errors) == 1 and errors[0].startswith("row 2:")


def test_expanding_window_schedule_is_parametric():
    label = partial(monthly_period_label, 2000)
    schedule = expanding_window_fold_schedule(
        initial_training_observations=24, origin_step_observations=6, forecast_horizon=3, fold_count=2,
        period_label=label,
    )
    assert schedule == [
        {"fold_index": 1, "training_observations": 24, "forecast_origin": "2001-12",
         "validation_start": "2002-01", "validation_end": "2002-03", "validation_observations": 3},
        {"fold_index": 2, "training_observations": 30, "forecast_origin": "2002-06",
         "validation_start": "2002-07", "validation_end": "2002-09", "validation_observations": 3},
    ]


def test_temporal_integrity_detects_gaps_and_non_finite_targets():
    label = partial(monthly_period_label, 2000)
    assert all(temporal_integrity_confirmations(["2000-01", "2000-02"], [1.0, 2.0], period_label=label).values())
    gap = temporal_integrity_confirmations(["2000-01", "2000-03"], [1.0, math.nan], period_label=label)
    assert gap["frequency_contiguous"] is False
    assert gap["target_values_finite"] is False


def test_helpers_reproduce_the_committed_nottem_recipe_geometry():
    # Regression guard: the Nottem notebook's recipe (committed before the
    # extraction) is reproduced exactly from the Nottem study parameters.
    recipe = json.loads((REPO_ROOT / "pipeline/authoring/nottem/preparation-recipe.json").read_text(encoding="utf-8"))
    label = partial(monthly_period_label, 1920)
    assert recipe["fold_schedule"] == expanding_window_fold_schedule(
        initial_training_observations=120, origin_step_observations=12, forecast_horizon=12, fold_count=9,
        period_label=label,
    )
    periods = [label(i) for i in range(240)]
    assert recipe["temporal_integrity"] == temporal_integrity_confirmations(
        periods, [0.0] * 240, period_label=label
    )
