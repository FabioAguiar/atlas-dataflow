import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UnivariateForecastingResult from "./UnivariateForecastingResult";
import {
  GENERIC_UNIVARIATE_FORECASTING_RESULT_PRESENTATION,
  isUnivariateForecastingResult,
  resultForContract,
} from "./types";
import type {
  AvailableContinuousRegressionResultContract,
  AvailableForecastingResultContract,
  UnivariateForecastingResult as ResultData,
  UnivariateForecastingResultPresentation,
} from "./types";

function buildResult(overrides: Partial<ResultData> = {}): ResultData {
  return {
    schema_version: "univariate-forecasting-result.v1",
    problem_type: "univariate_forecasting",
    forecast_origin: "2026-07",
    frequency: "monthly",
    forecast_horizon: 3,
    forecast_points: [
      { horizon_step: 1, future_time_index: "2026-08", forecast: 101.2 },
      { horizon_step: 2, future_time_index: "2026-09", forecast: 108.75 },
      { horizon_step: 3, future_time_index: "2026-10", forecast: 112.4 },
    ],
    model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend OLS" },
    ...overrides,
  };
}

const presentation: UnivariateForecastingResultPresentation = {
  schema_version: "univariate-forecasting-result-presentation.v1",
  forecast_series_label: "Monthly demand forecast",
  future_time_index_label: "Month",
  forecast_value_label: "Forecasted demand",
  model_section_label: "Model",
  decimal_places: 1,
};

const forecastingContract: AvailableForecastingResultContract = {
  status: "available",
  semantics: {
    schema_version: "univariate-forecasting-result-semantics.v1",
    problem_type: "univariate_forecasting",
    result_schema_version: "univariate-forecasting-result.v1",
    primary_output: "forecast_series",
    output_structure: "ordered_forecast_points",
    forecast_value_kind: "continuous_numeric",
    forecast_count_source: "forecast_horizon",
    model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend OLS" },
  },
};

describe("isUnivariateForecastingResult", () => {
  it("accepts a valid result", () => {
    expect(isUnivariateForecastingResult(buildResult())).toBe(true);
  });

  it("rejects the wrong schema_version or problem_type", () => {
    expect(isUnivariateForecastingResult({ ...buildResult(), schema_version: "continuous-regression-result.v1" })).toBe(false);
    expect(isUnivariateForecastingResult({ ...buildResult(), problem_type: "continuous_regression" })).toBe(false);
  });

  it("rejects an extra top-level key", () => {
    expect(isUnivariateForecastingResult({ ...buildResult(), extra_field: "not allowed" })).toBe(false);
  });

  it("rejects a non-positive or boolean forecast_horizon", () => {
    expect(isUnivariateForecastingResult({ ...buildResult(), forecast_horizon: 0 })).toBe(false);
    expect(isUnivariateForecastingResult({ ...buildResult(), forecast_horizon: -1 })).toBe(false);
    expect(isUnivariateForecastingResult({ ...buildResult(), forecast_horizon: true })).toBe(false);
  });

  it("rejects a forecast_points cardinality mismatch against forecast_horizon", () => {
    const result = buildResult();
    expect(isUnivariateForecastingResult({ ...result, forecast_points: result.forecast_points.slice(0, 2) })).toBe(false);
  });

  it("rejects non-sequential horizon_step values", () => {
    const result = buildResult();
    const reordered = [...result.forecast_points];
    [reordered[0], reordered[1]] = [reordered[1], reordered[0]];
    expect(isUnivariateForecastingResult({ ...result, forecast_points: reordered })).toBe(false);
  });

  it("rejects a boolean or otherwise invalid future_time_index", () => {
    const result = buildResult();
    const invalidPoints = [{ ...result.forecast_points[0], future_time_index: true }, ...result.forecast_points.slice(1)];
    expect(isUnivariateForecastingResult({ ...result, forecast_points: invalidPoints })).toBe(false);
  });

  it("accepts an integer future_time_index and rejects a boolean forecast_origin", () => {
    const result = buildResult({ forecast_origin: 7 });
    expect(isUnivariateForecastingResult(result)).toBe(true);
    expect(isUnivariateForecastingResult({ ...result, forecast_origin: true })).toBe(false);
  });

  it("rejects a non-finite forecast value", () => {
    const result = buildResult();
    const invalidPoints = [{ ...result.forecast_points[0], forecast: Number.NaN }, ...result.forecast_points.slice(1)];
    expect(isUnivariateForecastingResult({ ...result, forecast_points: invalidPoints })).toBe(false);
    const infinitePoints = [{ ...result.forecast_points[0], forecast: Number.POSITIVE_INFINITY }, ...result.forecast_points.slice(1)];
    expect(isUnivariateForecastingResult({ ...result, forecast_points: infinitePoints })).toBe(false);
  });

  it("rejects a malformed model descriptor", () => {
    expect(isUnivariateForecastingResult({ ...buildResult(), model_descriptor: { display_name: "Missing family" } })).toBe(false);
    expect(isUnivariateForecastingResult({ ...buildResult(), model_descriptor: { model_family: "x", display_name: "" } })).toBe(false);
  });

  it("rejects a blank frequency", () => {
    expect(isUnivariateForecastingResult({ ...buildResult(), frequency: "" })).toBe(false);
  });
});

describe("resultForContract for univariate_forecasting", () => {
  it("accepts a valid forecast result under an available forecasting result contract with a matching model descriptor", () => {
    expect(resultForContract(forecastingContract, buildResult())).toEqual(buildResult());
  });

  it("rejects a model descriptor mismatch", () => {
    const mismatched = buildResult({ model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Different Model" } });
    expect(resultForContract(forecastingContract, mismatched)).toBeNull();
  });

  it("rejects a forecast result under a non-forecasting contract", () => {
    const continuousContract: AvailableContinuousRegressionResultContract = {
      status: "available",
      semantics: {
        schema_version: "continuous-regression-result-semantics.v1",
        problem_type: "continuous_regression",
        result_schema_version: "continuous-regression-result.v1",
        primary_output: "predicted_value",
        output_value_kind: "continuous_numeric",
        model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend OLS" },
      },
    };
    expect(resultForContract(continuousContract, buildResult())).toBeNull();
  });
});

describe("UnivariateForecastingResult renderer", () => {
  it("preserves all forecast rows and their runtime order", () => {
    render(<UnivariateForecastingResult result={buildResult()} presentation={presentation} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("2026-08");
    expect(rows[1]).toHaveTextContent("2026-09");
    expect(rows[2]).toHaveTextContent("2026-10");
  });

  it("formats decimal_places without mutating the source result", () => {
    const result = buildResult();
    render(<UnivariateForecastingResult result={result} presentation={presentation} />);
    expect(screen.getByText("101.2")).toBeInTheDocument();
    expect(screen.getByText("108.8")).toBeInTheDocument();
    expect(result.forecast_points[1].forecast).toBe(108.75);
  });

  it("renders the optional unit label as display copy only", () => {
    const withUnit = { ...presentation, value_unit_label: "units" };
    const { container } = render(<UnivariateForecastingResult result={buildResult()} presentation={withUnit} />);
    expect(container.querySelectorAll(".univariate-forecasting-result__unit").length).toBe(3);

    const { container: withoutUnitContainer } = render(<UnivariateForecastingResult result={buildResult()} presentation={presentation} />);
    expect(withoutUnitContainer.querySelector(".univariate-forecasting-result__unit")).not.toBeInTheDocument();
  });

  it("always renders the fixed 'Model' heading and the governed display_name", () => {
    render(<UnivariateForecastingResult result={buildResult()} presentation={GENERIC_UNIVARIATE_FORECASTING_RESULT_PRESENTATION} />);
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Seasonal Trend OLS")).toBeInTheDocument();
    expect(screen.getAllByText("Forecast").length).toBeGreaterThan(0);
  });

  it("renders no observed target, residual, interval, or metric content", () => {
    const { container } = render(<UnivariateForecastingResult result={buildResult()} presentation={presentation} />);
    expect(container).not.toHaveTextContent(/observed|residual|confidence|interval|threshold|mae|rmse/i);
  });
});
