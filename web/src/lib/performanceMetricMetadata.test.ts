import { describe, expect, it } from "vitest";

import {
  PERFORMANCE_FOCUS_CATALOG,
  getApplicablePerformanceFocusIds,
  getApplicableScoresForFocus,
  getPerformanceFocusLabel,
  getPerformanceMetricMetadata,
  isPerformanceFocusApplicable,
  isPerformanceScoreApplicable,
} from "./performanceMetricMetadata";

const HIGHER_IS_BETTER_IDS = [
  "roc_auc",
  "pr_auc",
  "average_precision",
  "gini_coefficient",
  "ks_statistic",
  "recall",
  "precision",
  "f1_score",
  "f_beta_score",
  "balanced_accuracy",
  "mcc",
  "accuracy",
  "specificity",
  "cohens_kappa",
  "g_mean",
  "precision_at_k",
  "recall_at_k",
  "lift_at_k",
  "gain_at_k",
  "expected_profit",
  "net_benefit",
  // Project Spec S0215: explicit multiclass aggregate score ids.
  "f1_macro",
  "f1_weighted",
  "precision_macro",
  "recall_macro",
  "r2",
];

const LOWER_IS_BETTER_IDS = [
  "false_negative_rate",
  "log_loss",
  "brier_score",
  "calibration_error",
  "expected_calibration_error",
  "expected_cost",
  "cost_per_correct_detection",
  "false_positives_at_k",
  "false_negatives_at_k",
  "mae",
  "rmse",
];

describe("performanceMetricMetadata classification (Project Spec S0200)", () => {
  it("gives every current selectable Admin score deterministic metadata", () => {
    for (const entries of Object.values(PERFORMANCE_FOCUS_CATALOG)) {
      for (const [scoreId] of entries) {
        expect(getPerformanceMetricMetadata(scoreId), `expected metadata for ${scoreId}`).toBeDefined();
      }
    }
  });

  it.each(HIGHER_IS_BETTER_IDS)("classifies %s as higher_is_better", (scoreId) => {
    expect(getPerformanceMetricMetadata(scoreId)?.optimization).toEqual({ kind: "higher_is_better" });
  });

  it.each(LOWER_IS_BETTER_IDS)("classifies %s as lower_is_better", (scoreId) => {
    expect(getPerformanceMetricMetadata(scoreId)?.optimization).toEqual({ kind: "lower_is_better" });
  });

  it("targets calibration_slope at 1", () => {
    expect(getPerformanceMetricMetadata("calibration_slope")?.optimization).toEqual({
      kind: "target_is_better",
      target: 1,
    });
  });

  it("targets calibration_intercept at 0", () => {
    expect(getPerformanceMetricMetadata("calibration_intercept")?.optimization).toEqual({
      kind: "target_is_better",
      target: 0,
    });
  });

  it("recognizes average_precision as a metadata-only higher-is-better alias, not a duplicate selectable Admin score", () => {
    const metadata = getPerformanceMetricMetadata("average_precision");
    expect(metadata?.optimization).toEqual({ kind: "higher_is_better" });
    expect(metadata?.display_label).toBe("Average Precision");

    for (const entries of Object.values(PERFORMANCE_FOCUS_CATALOG)) {
      expect(entries.some(([scoreId]) => (scoreId as string) === "average_precision")).toBe(false);
    }
    // pr_auc remains the sole selectable Admin score for this presentation
    // concept -- average_precision must never appear alongside it.
    expect(PERFORMANCE_FOCUS_CATALOG.overall_discrimination.some(([scoreId]) => scoreId === "pr_auc")).toBe(true);
  });

  it("returns undefined for an unknown score id", () => {
    expect(getPerformanceMetricMetadata("not_a_real_metric")).toBeUndefined();
    expect(getPerformanceMetricMetadata("")).toBeUndefined();
  });

  it("keeps focus/catalog labels deterministic across repeated lookups", () => {
    expect(getPerformanceMetricMetadata("roc_auc")?.display_label).toBe("ROC-AUC");
    expect(getPerformanceMetricMetadata("roc_auc")?.display_label).toBe("ROC-AUC");
    expect(getPerformanceMetricMetadata("brier_score")?.display_label).toBe("Brier Score");
    expect(PERFORMANCE_FOCUS_CATALOG.probability_quality).toEqual(
      PERFORMANCE_FOCUS_CATALOG.probability_quality,
    );
  });
});

describe("getPerformanceFocusLabel (Project Spec S0204)", () => {
  it("gives every Performance focus id a deterministic label", () => {
    expect(getPerformanceFocusLabel("overall_discrimination")).toBe("Overall discrimination");
    expect(getPerformanceFocusLabel("positive_class_detection")).toBe("Positive-class detection");
    expect(getPerformanceFocusLabel("balanced_classification")).toBe("Balanced classification");
    expect(getPerformanceFocusLabel("probability_quality")).toBe("Probability quality");
    expect(getPerformanceFocusLabel("operational_decision")).toBe("Operational decision");
  });

  it("returns undefined for an unknown or missing focus id", () => {
    expect(getPerformanceFocusLabel("not_a_real_focus")).toBeUndefined();
    expect(getPerformanceFocusLabel("")).toBeUndefined();
    expect(getPerformanceFocusLabel(null)).toBeUndefined();
    expect(getPerformanceFocusLabel(undefined)).toBeUndefined();
  });

  it("is deterministic across repeated lookups", () => {
    expect(getPerformanceFocusLabel("overall_discrimination")).toBe("Overall discrimination");
    expect(getPerformanceFocusLabel("overall_discrimination")).toBe("Overall discrimination");
  });

  it("covers every focus id declared in PERFORMANCE_FOCUS_CATALOG, and no others", () => {
    const catalogFocusIds = Object.keys(PERFORMANCE_FOCUS_CATALOG);
    for (const focusId of catalogFocusIds) {
      expect(getPerformanceFocusLabel(focusId)).toBeDefined();
    }
    expect(catalogFocusIds).toHaveLength(6);
  });
});

describe("problem-type applicability (Project Spec S0215)", () => {
  it("marks overall_discrimination, positive_class_detection, and operational_decision binary-only", () => {
    for (const focusId of ["overall_discrimination", "positive_class_detection", "operational_decision"] as const) {
      expect(isPerformanceFocusApplicable(focusId, "binary_classification")).toBe(true);
      expect(isPerformanceFocusApplicable(focusId, "multiclass_classification")).toBe(false);
    }
  });

  it("marks balanced_classification and probability_quality applicable to both problem types", () => {
    for (const focusId of ["balanced_classification", "probability_quality"] as const) {
      expect(isPerformanceFocusApplicable(focusId, "binary_classification")).toBe(true);
      expect(isPerformanceFocusApplicable(focusId, "multiclass_classification")).toBe(true);
    }
  });

  it("returns false for an unknown focus id", () => {
    expect(isPerformanceFocusApplicable("not_a_real_focus", "multiclass_classification")).toBe(false);
  });

  it("every binary-classification score id remains applicable, unchanged", () => {
    for (const [focusId, entries] of Object.entries(PERFORMANCE_FOCUS_CATALOG)) {
      if (focusId === "regression_performance") {
        continue;
      }
      for (const [scoreId] of entries) {
        expect(isPerformanceScoreApplicable(scoreId, "binary_classification")).toBe(true);
      }
    }
  });

  it("marks the explicit multiclass aggregate ids and log_loss multiclass-compatible", () => {
    for (const scoreId of [
      "accuracy",
      "balanced_accuracy",
      "f1_macro",
      "f1_weighted",
      "precision_macro",
      "recall_macro",
      "log_loss",
    ]) {
      expect(isPerformanceScoreApplicable(scoreId, "multiclass_classification")).toBe(true);
    }
  });

  it("never marks the legacy ambiguous binary ids multiclass-compatible", () => {
    for (const scoreId of ["f1_score", "precision", "recall", "specificity", "g_mean", "mcc", "cohens_kappa"]) {
      expect(isPerformanceScoreApplicable(scoreId, "multiclass_classification")).toBe(false);
    }
  });

  it("does not yet mark calibration/Brier metrics multiclass-compatible", () => {
    for (const scoreId of [
      "brier_score",
      "calibration_error",
      "calibration_slope",
      "calibration_intercept",
      "expected_calibration_error",
    ]) {
      expect(isPerformanceScoreApplicable(scoreId, "multiclass_classification")).toBe(false);
    }
  });

  it("getApplicablePerformanceFocusIds returns only balanced_classification and probability_quality for multiclass", () => {
    expect(getApplicablePerformanceFocusIds("multiclass_classification")).toEqual([
      "balanced_classification",
      "probability_quality",
    ]);
  });

  it("getApplicablePerformanceFocusIds returns every classification focus id for binary, excluding regression_performance", () => {
    expect(getApplicablePerformanceFocusIds("binary_classification")).toEqual([
      "overall_discrimination",
      "positive_class_detection",
      "balanced_classification",
      "probability_quality",
      "operational_decision",
    ]);
    expect(getApplicablePerformanceFocusIds("binary_classification")).not.toContain("regression_performance");
  });

  it("getApplicableScoresForFocus filters balanced_classification to the multiclass-compatible subset", () => {
    const scores = getApplicableScoresForFocus("balanced_classification", "multiclass_classification");
    const scoreIds = scores.map(([scoreId]) => scoreId);
    expect(scoreIds).toEqual(["balanced_accuracy", "accuracy", "f1_macro", "f1_weighted", "precision_macro", "recall_macro"]);
    expect(scoreIds).not.toContain("f1_score");
    expect(scoreIds).not.toContain("recall");
  });

  it("getApplicableScoresForFocus returns the full focus catalog entries unchanged for binary", () => {
    expect(getApplicableScoresForFocus("balanced_classification", "binary_classification")).toEqual(
      PERFORMANCE_FOCUS_CATALOG.balanced_classification,
    );
  });
});

describe("continuous-regression performance focus (Project Spec S0237)", () => {
  it("adds regression_performance to the catalog with mae, rmse, r2 in that order", () => {
    expect(PERFORMANCE_FOCUS_CATALOG.regression_performance).toEqual([
      ["mae", "MAE"],
      ["rmse", "RMSE"],
      ["r2", "R²"],
    ]);
  });

  it("six total focus ids now exist", () => {
    expect(Object.keys(PERFORMANCE_FOCUS_CATALOG)).toHaveLength(6);
  });

  it("gives regression_performance a deterministic label", () => {
    expect(getPerformanceFocusLabel("regression_performance")).toBe("Regression performance");
  });

  it("makes MAE and RMSE catalog-authorable and lower_is_better, not metadata-only aliases", () => {
    expect(PERFORMANCE_FOCUS_CATALOG.regression_performance.some(([scoreId]) => scoreId === "mae")).toBe(true);
    expect(PERFORMANCE_FOCUS_CATALOG.regression_performance.some(([scoreId]) => scoreId === "rmse")).toBe(true);
    expect(getPerformanceMetricMetadata("mae")).toEqual({
      score_id: "mae",
      display_label: "MAE",
      optimization: { kind: "lower_is_better" },
    });
    expect(getPerformanceMetricMetadata("rmse")).toEqual({
      score_id: "rmse",
      display_label: "RMSE",
      optimization: { kind: "lower_is_better" },
    });
  });

  it("makes R² catalog-authorable and higher_is_better, not a metadata-only alias", () => {
    expect(PERFORMANCE_FOCUS_CATALOG.regression_performance.some(([scoreId]) => scoreId === "r2")).toBe(true);
    expect(getPerformanceMetricMetadata("r2")).toEqual({
      score_id: "r2",
      display_label: "R²",
      optimization: { kind: "higher_is_better" },
    });
  });

  it("marks regression_performance applicable only to continuous_regression", () => {
    expect(isPerformanceFocusApplicable("regression_performance", "continuous_regression")).toBe(true);
    expect(isPerformanceFocusApplicable("regression_performance", "binary_classification")).toBe(false);
    expect(isPerformanceFocusApplicable("regression_performance", "multiclass_classification")).toBe(false);
  });

  it("getApplicablePerformanceFocusIds returns exactly [regression_performance] for continuous_regression", () => {
    expect(getApplicablePerformanceFocusIds("continuous_regression")).toEqual(["regression_performance"]);
  });

  it("getApplicableScoresForFocus returns mae, rmse, r2 in catalog order for continuous_regression", () => {
    const scores = getApplicableScoresForFocus("regression_performance", "continuous_regression");
    expect(scores.map(([scoreId]) => scoreId)).toEqual(["mae", "rmse", "r2"]);
  });

  it("never marks regression scores classification-applicable", () => {
    for (const scoreId of ["mae", "rmse", "r2"]) {
      expect(isPerformanceScoreApplicable(scoreId, "binary_classification")).toBe(false);
      expect(isPerformanceScoreApplicable(scoreId, "multiclass_classification")).toBe(false);
      expect(isPerformanceScoreApplicable(scoreId, "continuous_regression")).toBe(true);
    }
  });

  it("does not include classification-only foci as applicable to continuous_regression", () => {
    const applicable = getApplicablePerformanceFocusIds("continuous_regression");
    for (const focusId of [
      "overall_discrimination",
      "positive_class_detection",
      "balanced_classification",
      "probability_quality",
      "operational_decision",
    ]) {
      expect(applicable).not.toContain(focusId);
    }
  });
});
