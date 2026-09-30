"""Scientific univariate-forecasting family adapters.

One stateless adapter per forecasting family registered in
``pipeline.model_families`` (``forecasting_family_names``). An adapter fits a
declared specification *from scratch* on one training history and returns the
full multi-step forecast vector for the requested future periods. It never
receives target values of those periods, never keeps a fitted object between
calls, and never chooses a parameter a study did not declare: every
constructor argument comes from the contract's ``fixed_params``.

The adapters are the scientific reproduction's executable capability only.
They do not make a family natively trainable or release-governed; native
forecasting training keeps its own implementation in ``pipeline.training``.

Failure semantics (the executor in ``pipeline.scientific_forecasting``
applies them):

* ``ForecastingSpecificationFailure`` -- a legitimate scientific failure of a
  specification on one fold: explicit optimizer non-convergence, or a forecast
  vector with the wrong length or non-finite values. It makes the fold (and
  therefore the specification) incomplete.
* any other exception raised by a fit/forecast is also a specification failure
  unless its type is one the contract declares a programming error (for
  example ``TypeError`` or ``ImportError``), which aborts the backtest.

statsmodels is imported lazily; it is required only by the adapters that call
a statsmodels constructor, and only when the scientific reproduction runs.
"""

from __future__ import annotations

import importlib
import inspect
import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

CATEGORY_EXPLICIT_NON_CONVERGENCE = "explicit_optimizer_non_convergence"
CATEGORY_INVALID_FORECAST_OUTPUT = "invalid_forecast_output"
CATEGORY_FIT_OR_FORECAST_EXCEPTION = "fit_or_forecast_exception"
GUARD_CATEGORIES = (CATEGORY_EXPLICIT_NON_CONVERGENCE, CATEGORY_INVALID_FORECAST_OUTPUT)

_CALENDAR_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
                    "September", "October", "November", "December")


class ForecastingAdapterError(ValueError):
    """A specification the adapter cannot represent (raised before any fit)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ForecastingSpecificationFailure(RuntimeError):
    """A legitimate fit/forecast failure of one specification on one fold."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ForecastOutput:
    values: tuple[float, ...]
    converged: bool | None
    constructor_arguments: Mapping[str, Any]


def _constructor(path: str) -> Callable[..., Any]:
    """The constructor an adapter calls (a single seam, replaceable in tests)."""
    return _resolve(path)


def _resolve(path: str) -> Callable[..., Any]:
    module_name, name = path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ForecastingAdapterError("missing_forecasting_dependency", f"{module_name} is required for {path}") from exc
    return getattr(module, name)


def _series(training: Any) -> Any:
    """The training history as a float Series on a monthly-or-other PeriodIndex (copied)."""
    import pandas as pd

    if not isinstance(training, pd.Series) or not isinstance(training.index, pd.PeriodIndex):
        raise ForecastingAdapterError("invalid_training_history", "training history must be a Series on a PeriodIndex")
    return pd.Series(training.to_numpy(dtype=float), index=training.index.copy(), name=training.name)


def _check_future(training: Any, future: Any) -> None:
    import pandas as pd

    if not isinstance(future, pd.PeriodIndex) or not len(future):
        raise ForecastingAdapterError("invalid_future_periods", "future periods must be a non-empty PeriodIndex")
    expected = pd.period_range(training.index[-1] + 1, periods=len(future), freq=training.index.freq)
    if not future.equals(expected):
        raise ForecastingAdapterError("non_contiguous_future", "future periods must directly follow the training history")


def validate_output(values: Sequence[float], horizon: int) -> tuple[float, ...]:
    output = tuple(float(v) for v in values)
    if len(output) != horizon:
        raise ForecastingSpecificationFailure(CATEGORY_INVALID_FORECAST_OUTPUT,
                                              f"forecast has {len(output)} values, expected {horizon}")
    if not all(math.isfinite(v) for v in output):
        raise ForecastingSpecificationFailure(CATEGORY_INVALID_FORECAST_OUTPUT, "forecast contains non-finite values")
    return output


class ForecastingAdapter:
    """Base adapter: parameter validation plus the fit-and-forecast contract."""

    family_id: str = ""
    constructor: str | None = None
    parameters: frozenset[str] = frozenset()

    def accepted_parameters(self) -> frozenset[str]:
        return self.parameters

    def validate_parameters(self, params: Mapping[str, Any], seasonal_period: int) -> None:
        unknown = sorted(set(params) - self.accepted_parameters())
        if unknown:
            raise ForecastingAdapterError("unsupported_hyperparameter",
                                          f"{self.family_id} does not accept parameter(s) {unknown}")
        if not isinstance(seasonal_period, int) or isinstance(seasonal_period, bool) or seasonal_period < 1:
            raise ForecastingAdapterError("invalid_seasonal_period", "seasonal_period must be a positive integer")

    def fit_forecast(self, training: Any, future: Any, params: Mapping[str, Any], *,
                     seasonal_period: int) -> ForecastOutput:
        self.validate_parameters(params, seasonal_period)
        history = _series(training)
        _check_future(history, future)
        values, converged, arguments = self._fit_forecast(history, future, dict(params), seasonal_period)
        return ForecastOutput(values=validate_output(values, len(future)), converged=converged,
                              constructor_arguments=arguments)

    def _fit_forecast(self, history: Any, future: Any, params: dict[str, Any],
                      seasonal_period: int) -> tuple[Sequence[float], bool | None, Mapping[str, Any]]:
        raise NotImplementedError


class SeasonalNaiveAdapter(ForecastingAdapter):
    """``y_hat[T+h] = y[T+h-m*ceil(h/m)]``: the last observed season repeated."""

    family_id = "seasonal_naive"

    def _fit_forecast(self, history, future, params, seasonal_period):
        if len(history) < seasonal_period:
            raise ForecastingSpecificationFailure(CATEGORY_INVALID_FORECAST_OUTPUT,
                                                  "seasonal naive needs one full season of history")
        season = history.to_numpy(dtype=float)[-seasonal_period:]
        return [season[h % seasonal_period] for h in range(len(future))], None, {"seasonal_period": seasonal_period}


class NaiveLastValueAdapter(ForecastingAdapter):
    """Every horizon receives the last training value."""

    family_id = "naive_last_value"

    def _fit_forecast(self, history, future, params, seasonal_period):
        return [float(history.iloc[-1])] * len(future), None, {}


def calendar_design(index: Any, start_ordinal: int, *, intercept: bool, linear_time_trend: bool,
                    reference_month: str) -> Any:
    """Deterministic design: [constant] [t] then one dummy per non-reference calendar month.

    ``t`` is the period ordinal minus the first training ordinal, so a future
    period continues the training trend. Dummies follow calendar order
    (January .. December) with the reference month omitted.
    """
    import numpy as np

    columns = []
    if intercept:
        columns.append(np.ones(len(index)))
    if linear_time_trend:
        columns.append(np.asarray(index.asi8 - start_ordinal, dtype=float))
    reference = _CALENDAR_MONTHS.index(reference_month) + 1
    columns.extend((index.month == month).astype(float) for month in range(1, 13) if month != reference)
    return np.column_stack(columns)


class DeterministicSeasonalTrendOLSAdapter(ForecastingAdapter):
    """statsmodels OLS on an intercept, a linear time trend and calendar-month dummies."""

    family_id = "deterministic_seasonal_trend_ols"
    constructor = "statsmodels.regression.linear_model.OLS"
    parameters = frozenset({"intercept", "linear_time_trend", "calendar_month_dummies", "reference_month"})

    def validate_parameters(self, params, seasonal_period):
        super().validate_parameters(params, seasonal_period)
        if seasonal_period != 12:
            raise ForecastingAdapterError("unsupported_seasonal_period",
                                          "calendar-month dummies require a monthly seasonal period of 12")
        if params.get("reference_month") not in _CALENDAR_MONTHS:
            raise ForecastingAdapterError("invalid_reference_month", "reference_month must be a calendar month name")
        if params.get("calendar_month_dummies") != seasonal_period - 1:
            raise ForecastingAdapterError("invalid_calendar_month_dummies",
                                          "calendar_month_dummies must equal seasonal_period - 1")
        for flag in ("intercept", "linear_time_trend"):
            if not isinstance(params.get(flag), bool):
                raise ForecastingAdapterError("invalid_design_flag", f"{flag} must be declared as a boolean")

    def _fit_forecast(self, history, future, params, seasonal_period):
        if history.index.freqstr not in ("M", "ME"):
            raise ForecastingAdapterError("unsupported_frequency", "calendar-month dummies require a monthly PeriodIndex")
        ols = _constructor(self.constructor)
        start = int(history.index[0].ordinal)
        design = {key: params[key] for key in ("intercept", "linear_time_trend", "reference_month")}
        fit = ols(history.to_numpy(dtype=float), calendar_design(history.index, start, **design)).fit()
        predictions = fit.predict(calendar_design(future, start, **design))
        return list(predictions), None, {**design, "calendar_month_dummies": params["calendar_month_dummies"],
                                         "exog_columns": int(fit.params.shape[0])}


class _StatsmodelsAdapter(ForecastingAdapter):
    """A statsmodels constructor fed the declared parameters verbatim."""

    list_to_tuple: tuple[str, ...] = ()

    def accepted_parameters(self) -> frozenset[str]:
        signature = inspect.signature(_resolve(self.constructor))
        return frozenset(name for name in signature.parameters if name not in ("self", "endog", "exog", "kwargs"))

    def constructor_arguments(self, params: Mapping[str, Any]) -> dict[str, Any]:
        arguments = dict(params)
        for name in self.list_to_tuple:
            if name in arguments and isinstance(arguments[name], list):
                arguments[name] = tuple(arguments[name])
        return arguments


class ExponentialSmoothingAdapter(_StatsmodelsAdapter):
    family_id = "exponential_smoothing"
    constructor = "statsmodels.tsa.holtwinters.ExponentialSmoothing"

    def _fit_forecast(self, history, future, params, seasonal_period):
        arguments = self.constructor_arguments(params)
        fitted = _constructor(self.constructor)(history, **arguments).fit(optimized=True)
        return list(fitted.forecast(len(future))), None, arguments


class AutoRegAdapter(_StatsmodelsAdapter):
    family_id = "autoreg"
    constructor = "statsmodels.tsa.ar_model.AutoReg"

    def _fit_forecast(self, history, future, params, seasonal_period):
        arguments = self.constructor_arguments(params)
        fitted = _constructor(self.constructor)(history, **arguments).fit()
        start = len(history)
        return list(fitted.predict(start=start, end=start + len(future) - 1, dynamic=False)), None, arguments


class SARIMAXAdapter(_StatsmodelsAdapter):
    family_id = "sarimax"
    constructor = "statsmodels.tsa.statespace.sarimax.SARIMAX"
    list_to_tuple = ("order", "seasonal_order")

    def _fit_forecast(self, history, future, params, seasonal_period):
        arguments = self.constructor_arguments(params)
        fitted = _constructor(self.constructor)(history, **arguments).fit(disp=False)
        converged = bool(fitted.mle_retvals.get("converged", False))
        if not converged:
            raise ForecastingSpecificationFailure(CATEGORY_EXPLICIT_NON_CONVERGENCE,
                                                  "explicit optimizer non-convergence")
        return list(fitted.get_forecast(steps=len(future)).predicted_mean), converged, arguments


ADAPTERS: Mapping[str, ForecastingAdapter] = {
    adapter.family_id: adapter
    for adapter in (
        SeasonalNaiveAdapter(), NaiveLastValueAdapter(), DeterministicSeasonalTrendOLSAdapter(),
        ExponentialSmoothingAdapter(), AutoRegAdapter(), SARIMAXAdapter(),
    )
}


def get_adapter(family_id: str) -> ForecastingAdapter:
    adapter = ADAPTERS.get(family_id)
    if adapter is None:
        raise ForecastingAdapterError("unsupported_forecasting_family",
                                      f"no scientific forecasting adapter for family {family_id!r}")
    return adapter
