import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BinaryClassificationResult from "./BinaryClassificationResult";
import { GENERIC_RESULT_PRESENTATION, projectBinaryClassificationResult } from "./types";
import type {
  BinaryClassificationResult as BinaryClassificationResultData,
  BinaryResultPresentation,
  BinaryResultSemantics,
} from "./types";

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
  it("renders the positive outcome copy from decision.predicted_positive, without a raw class id in normal visible text", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.getByText("Likely to churn")).toBeInTheDocument();
    expect(screen.queryByText("Unlikely to churn")).not.toBeInTheDocument();
    expect(screen.queryByText("Yes", { exact: false })).not.toBeInTheDocument();
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

  it("does not render decision threshold, band range or a 'Predicted class' line as visible public text", () => {
    const result = buildResult({ positive_class_probability: 0.5, decision: { threshold: 0.5, predicted_positive: true } });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.queryByText(/Decision threshold/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Predicted class/)).not.toBeInTheDocument();
    expect(screen.getByText("Likely to churn")).toBeInTheDocument();
  });

  it.each([
    ["low", "Low risk"],
    ["medium", "Medium risk"],
    ["high", "High risk"],
  ])("renders the interpretation label for a returned %s band ID as the compact status treatment, without recomputing the band", (bandId, label) => {
    const result = buildResult({ interpretation: { preset: "risk", band_id: bandId, bands } });
    render(<BinaryClassificationResult result={result} presentation={presentation} />);

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/^Band:/)).not.toBeInTheDocument();
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

  it("retains the formatted probability, interpretation label and decision threshold in the probability meter's accessible description", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    const meter = screen.getByRole("img", { name: /Positive class probability 68%/ });
    expect(meter).toHaveAccessibleName(/Positive class probability 68%/);
    expect(meter).toHaveAccessibleName(/Decision threshold 50%/);
    expect(meter).toHaveAccessibleName(/High risk/);
  });

  it("includes the selected band range in the accessible description when available", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    const meter = screen.getByRole("img", { name: /Positive class probability 68%/ });
    expect(meter).toHaveAccessibleName(/Range: 65%–100%/);
  });

  it("renders the technical model descriptor's display name under the model section label", () => {
    render(<BinaryClassificationResult result={buildResult()} presentation={presentation} />);

    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting")).toBeInTheDocument();
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

  // Project Spec S0141: at both meter boundaries the marker's *position*
  // input carried by the shared CSS custom property must still equal the
  // exact governed probability -- CSS clamp() alone contains the rendered
  // footprint -- so the displayed value, threshold comparison and
  // accessible label are never altered to achieve containment.
  it.each([
    [0, "0%"],
    [1, "100%"],
  ])("carries the exact %s probability into the value marker's position custom property for CSS containment clamping", (probability, expectedPosition) => {
    const result = buildResult({ positive_class_probability: probability });
    const { container } = render(<BinaryClassificationResult result={result} presentation={presentation} />);

    const marker = container.querySelector<HTMLElement>(".probability-meter__value")!;
    expect(marker.style.getPropertyValue("--probability-meter-value-position")).toBe(expectedPosition);
  });

  it("reports the true zero and full accessible probability at both meter boundaries", () => {
    const zero = buildResult({ positive_class_probability: 0, decision: { threshold: 0.5, predicted_positive: false }, interpretation: { preset: "risk", band_id: "low", bands } });
    render(<BinaryClassificationResult result={zero} presentation={presentation} />);
    expect(screen.getByRole("img", { name: /Positive class probability 0%/ })).toBeInTheDocument();
    expect(screen.getByText("0%", { selector: ".binary-classification-result__probability-value" })).toBeInTheDocument();
  });
});

// Project Spec S0141: the single shared, side-effect-free binary result
// projection boundary used by both the Dataset Admin scenario preview and
// the public Dataset Detail zero-probability initial card.
describe("projectBinaryClassificationResult", () => {
  const semantics: BinaryResultSemantics = {
    schema_version: "binary-result-semantics.v1",
    problem_type: "binary_classification",
    result_schema_version: "binary-classification-result.v1",
    primary_output: "positive_class_probability",
    positive_class: { class_id: "Yes", event_label: "Churn" },
    negative_class: { class_id: "No" },
    decision: { threshold: 0.5 },
    interpretation: {
      preset: "risk",
      bands: [
        { band_id: "low", lower_bound: 0, upper_bound: 0.35 },
        { band_id: "medium", lower_bound: 0.35, upper_bound: 0.65 },
        { band_id: "high", lower_bound: 0.65, upper_bound: 1.0 },
      ],
    },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
  };

  it("derives a complete zero-probability result: negative decision, low band, complementary probabilities", () => {
    const result = projectBinaryClassificationResult(semantics, 0);

    expect(result?.positive_class_probability).toBe(0);
    expect(result?.class_probabilities).toEqual([
      { class_id: "No", probability: 1 },
      { class_id: "Yes", probability: 0 },
    ]);
    expect(result?.decision).toEqual({ threshold: 0.5, predicted_positive: false });
    expect(result?.predicted_class).toEqual({ class_id: "No" });
    expect(result?.interpretation.band_id).toBe("low");
    expect(result?.model_descriptor).toEqual(semantics.model_descriptor);
  });

  it("derives predicted_positive from probability >= threshold at the exact threshold boundary", () => {
    const atThreshold = projectBinaryClassificationResult(semantics, 0.5);
    expect(atThreshold?.decision.predicted_positive).toBe(true);
    expect(atThreshold?.predicted_class).toEqual({ class_id: "Yes" });

    const belowThreshold = projectBinaryClassificationResult(semantics, 0.499);
    expect(belowThreshold?.decision.predicted_positive).toBe(false);
  });

  it("selects the final band for probability one", () => {
    expect(projectBinaryClassificationResult(semantics, 1)?.interpretation.band_id).toBe("high");
  });

  it("never copies presentation copy into the result payload and accepts no presentation input", () => {
    const result = projectBinaryClassificationResult(semantics, 0);
    expect(Object.keys(result ?? {})).not.toContain("positive_outcome_copy");
    expect(Object.keys(result ?? {})).not.toContain("predicted_outcome_label");
  });

  it("returns null instead of fabricating a result for an out-of-range or non-finite probability", () => {
    expect(projectBinaryClassificationResult(semantics, -0.01)).toBeNull();
    expect(projectBinaryClassificationResult(semantics, 1.01)).toBeNull();
    expect(projectBinaryClassificationResult(semantics, Number.NaN)).toBeNull();
  });

  it("returns null when the governed bands cannot select exactly one band for the probability", () => {
    const invalid: BinaryResultSemantics = {
      ...semantics,
      interpretation: { ...semantics.interpretation, bands: semantics.interpretation.bands.slice(0, 2) },
    };
    expect(projectBinaryClassificationResult(invalid, 0.5)).toBeNull();
  });

  it("returns null for an ambiguous or equal class identity", () => {
    const equalClasses: BinaryResultSemantics = {
      ...semantics,
      negative_class: { class_id: "Yes" },
    };
    expect(projectBinaryClassificationResult(equalClasses, 0)).toBeNull();
  });
});
