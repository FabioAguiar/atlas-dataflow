import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BinaryClassificationResult from "./BinaryClassificationResult";
import { GENERIC_RESULT_PRESENTATION } from "./types";
import type { BinaryClassificationResult as BinaryClassificationResultData, BinaryResultPresentation } from "./types";

const bands = [
  { band_id: "low", lower_bound: 0, upper_bound: 0.35 },
  { band_id: "medium", lower_bound: 0.35, upper_bound: 0.65 },
  { band_id: "high", lower_bound: 0.65, upper_bound: 1.0 },
];

function buildResult(overrides: Partial<BinaryClassificationResultData> = {}): BinaryClassificationResultData {
  return {
    schema_version: "binary-classification-result.v1",
    problem_type: "binary_classification",
    predicted_class: { class_id: "Yes" },
    positive_class: { class_id: "Yes", event_label: "Churn" },
    positive_class_probability: 0.68,
    class_probabilities: [
      { class_id: "No", probability: 0.32 },
      { class_id: "Yes", probability: 0.68 },
    ],
    decision: { threshold: 0.5, predicted_positive: true },
    interpretation: { preset: "risk", band_id: "high", bands },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
    ...overrides,
  };
}

const presentation: BinaryResultPresentation = {
  schema_version: "binary-result-presentation.v1",
  positive_class_probability_label: "Churn probability",
  predicted_outcome_label: "Predicted outcome",
  positive_outcome_copy: "Likely to churn",
  negative_outcome_copy: "Unlikely to churn",
  model_section_label: "Model",
  interpretation: {
    preset: "risk",
    labels: { high: "High risk", medium: "Medium risk", low: "Low risk" },
  },
};

describe("BinaryClassificationResult semantic rendering", () => {
  it("renders the positive outcome copy, technical class, and event meaning from decision.predicted_positive", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.getByText("Likely to churn")).toBeInTheDocument();
    expect(screen.queryByText("Unlikely to churn")).not.toBeInTheDocument();
    expect(screen.getAllByText("Yes", { selector: ".binary-classification-result__technical span" })).toHaveLength(2);
    expect(
      screen.getByText(/Churn/, {
        selector: ".binary-classification-result__probability .binary-classification-result__technical",
      }),
    ).toBeInTheDocument();
  });

  it("renders the negative outcome copy when decision.predicted_positive is false, without deriving it from probability", () => {
    const result = buildResult({
      predicted_class: { class_id: "No" },
      positive_class_probability: 0.9,
      decision: { threshold: 0.5, predicted_positive: false },
      interpretation: { preset: "risk", band_id: "high", bands },
    });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.getByText("Unlikely to churn")).toBeInTheDocument();
    expect(screen.queryByText("Likely to churn")).not.toBeInTheDocument();
  });

  it("displays threshold equality outcomes exactly as resolved by the backend result", () => {
    const result = buildResult({ positive_class_probability: 0.5, decision: { threshold: 0.5, predicted_positive: true } });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.getByText("Decision threshold: 50%")).toBeInTheDocument();
    expect(screen.getByText("Likely to churn")).toBeInTheDocument();
  });

  it.each([
    ["low", "Low risk"],
    ["medium", "Medium risk"],
    ["high", "High risk"],
  ])("renders the interpretation label for a returned %s band ID without recomputing the band", (bandId, label) => {
    const result = buildResult({ interpretation: { preset: "risk", band_id: bandId, bands } });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it.each([
    [0.68, "68%"],
    [0.655, "65.5%"],
    [1.0, "100%"],
    [0.0, "0%"],
  ])("formats probability %s as %s", (probability, expected) => {
    const result = buildResult({ positive_class_probability: probability });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.getByText(expected, { selector: ".binary-classification-result__probability-value" })).toBeInTheDocument();
  });

  it("renders the textual decision threshold and band range alongside the probability meter", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.getByText("Decision threshold: 50%")).toBeInTheDocument();
    expect(screen.getByText("Range: 65%–100%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Positive class probability 68%/ })).toBeInTheDocument();
  });

  it("renders the technical model descriptor's display name under the model section label", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting")).toBeInTheDocument();
  });

  it("renders the positive technical class id in a secondary traceable presentation distinct from event meaning", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    const positiveClassLine = screen.getByText(/Churn/, {
      selector: ".binary-classification-result__probability .binary-classification-result__technical",
    });
    expect(positiveClassLine.textContent).toContain("Yes");
  });

  it("falls back to the bounded generic presentation without inventing technical identity", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={GENERIC_RESULT_PRESENTATION} />);

    expect(screen.getByText("Positive class probability")).toBeInTheDocument();
    expect(screen.getByText("Predicted outcome")).toBeInTheDocument();
    expect(screen.getByText("Positive outcome")).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    // Technical identity still comes from the result, never the fallback copy.
    expect(screen.getByText("Gradient Boosting")).toBeInTheDocument();
  });

  it("never renders legacy confidence copy", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });
});
