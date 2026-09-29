import { describe, expect, it } from "vitest";
import { getDatasetIcon, getProblemTypeLabel } from "./datasetPresentation";

describe("getProblemTypeLabel", () => {
  it("labels every governed Atlas problem type", () => {
    expect(getProblemTypeLabel("binary_classification")).toBe("Binary Classification");
    expect(getProblemTypeLabel("multiclass_classification")).toBe("Multiclass Classification");
    expect(getProblemTypeLabel("continuous_regression")).toBe("Continuous Regression");
    expect(getProblemTypeLabel("univariate_forecasting")).toBe("Univariate Forecasting");
  });

  it("never carries dead vocabulary that is not a governed problem type", () => {
    expect(getProblemTypeLabel("time_series_forecasting")).toBe("Predictive Analysis");
    expect(getProblemTypeLabel("clustering")).toBe("Predictive Analysis");
  });

  it("falls back to the caller's label for absent or unknown values", () => {
    expect(getProblemTypeLabel(undefined)).toBe("Predictive Analysis");
    expect(getProblemTypeLabel(null, "Unavailable")).toBe("Unavailable");
    expect(getProblemTypeLabel("unknown_type", "Unavailable")).toBe("Unavailable");
  });
});

describe("getDatasetIcon domain taxonomy", () => {
  it("resolves a telecommunications domain through the telecom keyword family", () => {
    expect(getDatasetIcon("telecommunications", [])).toBe("telecom");
    expect(getDatasetIcon("telecom", [])).toBe("telecom");
  });

  it("does not treat a dataset abbreviation as a domain keyword", () => {
    expect(getDatasetIcon("telco", [])).toBe("generic");
  });

  it("gives a brand-new dataset in an unknown domain the generic icon", () => {
    expect(getDatasetIcon("aerospace", ["example"])).toBe("generic");
  });
});
