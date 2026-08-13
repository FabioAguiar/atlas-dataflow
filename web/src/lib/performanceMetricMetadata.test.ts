import { describe, expect, it } from "vitest";

import {
  PERFORMANCE_FOCUS_CATALOG,
  getPerformanceMetricMetadata,
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
