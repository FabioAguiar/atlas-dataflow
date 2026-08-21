import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ContinuousRegressionResult from "./ContinuousRegressionResult";
import { GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION, type ContinuousRegressionResult as ResultData } from "./types";

const result: ResultData = {
  schema_version: "continuous-regression-result.v1",
  problem_type: "continuous_regression",
  predicted_value: 42.7345,
  model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
};

describe("ContinuousRegressionResult", () => {
  it("renders the predicted value at the configured decimal places, the model name, and no unit label when absent", () => {
    const { container } = render(
      <ContinuousRegressionResult result={result} presentation={GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION} />,
    );
    expect(screen.getByText("Predicted value")).toBeInTheDocument();
    expect(screen.getByText("42.73")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting Regressor")).toBeInTheDocument();
    expect(container.querySelector(".continuous-regression-result__unit")).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent(/confidence|probability|threshold|risk|residual/i);
  });

  it("renders the optional presentation-only unit label as display copy without mutating the raw predicted value", () => {
    const presentation = {
      schema_version: "continuous-regression-result-presentation.v1" as const,
      predicted_value_label: "Predicted compressive strength",
      model_section_label: "Model",
      decimal_places: 1,
      value_unit_label: "MPa",
    };
    render(<ContinuousRegressionResult result={result} presentation={presentation} />);
    expect(screen.getByText("Predicted compressive strength")).toBeInTheDocument();
    expect(screen.getByText("42.7")).toBeInTheDocument();
    expect(screen.getByText("MPa")).toBeInTheDocument();
    expect(result.predicted_value).toBe(42.7345);
  });

  it("formats decimal_places at the bounded extremes without throwing", () => {
    const zeroPlaces = { ...GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION, decimal_places: 0 };
    const { rerender } = render(<ContinuousRegressionResult result={result} presentation={zeroPlaces} />);
    expect(screen.getByText("43")).toBeInTheDocument();

    const sixPlaces = { ...GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION, decimal_places: 6 };
    rerender(<ContinuousRegressionResult result={result} presentation={sixPlaces} />);
    expect(screen.getByText("42.734500")).toBeInTheDocument();
  });

  it("always renders the fixed 'Model' heading, never a legacy/custom presentation model_section_label (Project Spec S0239)", () => {
    const customPresentation = { ...GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION, model_section_label: "Custom model heading" };
    render(<ContinuousRegressionResult result={result} presentation={customPresentation} />);

    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.queryByText("Custom model heading")).not.toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting Regressor")).toBeInTheDocument();
  });
});
