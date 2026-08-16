// Project Spec S0200: the single frontend authority for performance-score
// identity (score_id/display_label) and optimization semantics (whether a
// higher, lower, or target-bound value is favorable). Consumed by both
// Admin's score authoring (DatasetAdminPage.tsx) and the shared public
// PerformanceSummary so the two surfaces can never drift into independent
// direction maps. Optimization semantics are presentation-only metadata --
// they are never persisted into a dataset's public profile and are never
// operator-editable.

export type OptimizationSemantics =
  | { kind: "higher_is_better" }
  | { kind: "lower_is_better" }
  | { kind: "target_is_better"; target: number };

export type PerformanceMetricMetadata = {
  score_id: string;
  display_label: string;
  optimization: OptimizationSemantics;
};

// The current bounded Admin selectable score catalog, grouped by
// performance focus -- the same shape DatasetAdminPage.tsx's
// PerformanceFocusBuilder renders and persists. This is the single source
// for score ids and display labels; DatasetAdminPage.tsx consumes this
// object directly rather than declaring a competing local literal.
export const PERFORMANCE_FOCUS_CATALOG = {
  overall_discrimination: [
    ["roc_auc", "ROC-AUC"],
    ["pr_auc", "PR-AUC"],
    ["gini_coefficient", "Gini coefficient"],
    ["ks_statistic", "KS statistic"],
  ],
  positive_class_detection: [
    ["recall", "Recall"],
    ["precision", "Precision"],
    ["f1_score", "F1-score"],
    ["f_beta_score", "F-beta score"],
    ["pr_auc", "PR-AUC"],
    ["false_negative_rate", "False Negative Rate"],
  ],
  balanced_classification: [
    ["balanced_accuracy", "Balanced Accuracy"],
    ["mcc", "MCC"],
    ["f1_score", "F1-score"],
    ["accuracy", "Accuracy"],
    ["recall", "Recall"],
    ["specificity", "Specificity"],
    ["cohens_kappa", "Cohen's Kappa"],
    ["g_mean", "G-Mean"],
    // Project Spec S0215: explicit multiclass aggregate score ids -- distinct
    // from f1_score/recall above, never collapsed into them.
    ["f1_macro", "F1 Macro"],
    ["f1_weighted", "F1 Weighted"],
    ["precision_macro", "Precision Macro"],
    ["recall_macro", "Recall Macro"],
  ],
  probability_quality: [
    ["log_loss", "Log Loss"],
    ["brier_score", "Brier Score"],
    ["calibration_error", "Calibration Error"],
    ["calibration_slope", "Calibration Slope"],
    ["calibration_intercept", "Calibration Intercept"],
    ["expected_calibration_error", "Expected Calibration Error"],
  ],
  operational_decision: [
    ["precision_at_k", "Precision@K"],
    ["recall_at_k", "Recall@K"],
    ["lift_at_k", "Lift@K"],
    ["gain_at_k", "Gain@K"],
    ["expected_cost", "Expected Cost"],
    ["expected_profit", "Expected Profit"],
    ["net_benefit", "Net Benefit"],
    ["cost_per_correct_detection", "Cost per Correct Detection"],
    ["false_positives_at_k", "False Positives at K"],
    ["false_negatives_at_k", "False Negatives at K"],
  ],
} as const;

export type PerformanceFocusId = keyof typeof PERFORMANCE_FOCUS_CATALOG;

// Project Spec S0204: the single frontend authority for Performance focus
// human labels -- consumed by DatasetAdminPage.tsx's focus selector,
// PerformanceSummary.tsx, DatasetCard.tsx, and DatasetDetailHeader.tsx, so
// none of them may declare a competing local focus-label map.
const PERFORMANCE_FOCUS_LABELS: Readonly<Record<PerformanceFocusId, string>> = {
  overall_discrimination: "Overall discrimination",
  positive_class_detection: "Positive-class detection",
  balanced_classification: "Balanced classification",
  probability_quality: "Probability quality",
  operational_decision: "Operational decision",
};

/**
 * Looks up the deterministic human label for a known Performance focus id.
 * Returns undefined for any id outside the closed catalog above -- an
 * unknown/missing focus id must never receive an invented label.
 */
export function getPerformanceFocusLabel(focusId: string | null | undefined): string | undefined {
  if (!focusId) {
    return undefined;
  }
  return (PERFORMANCE_FOCUS_LABELS as Record<string, string>)[focusId];
}

const HIGHER_IS_BETTER_IDS: readonly string[] = [
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
  // Project Spec S0215: explicit multiclass aggregate scores are all
  // higher-is-better.
  "f1_macro",
  "f1_weighted",
  "precision_macro",
  "recall_macro",
];

const LOWER_IS_BETTER_IDS: readonly string[] = [
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

// Target-based metrics never derive direction from the current value and
// never calculate/persist distance-to-target -- the target below is fixed
// classification metadata only.
const TARGET_IS_BETTER: Readonly<Record<string, number>> = {
  calibration_slope: 1,
  calibration_intercept: 0,
};

function optimizationFor(scoreId: string): OptimizationSemantics | null {
  if (HIGHER_IS_BETTER_IDS.includes(scoreId)) {
    return { kind: "higher_is_better" };
  }
  if (LOWER_IS_BETTER_IDS.includes(scoreId)) {
    return { kind: "lower_is_better" };
  }
  if (scoreId in TARGET_IS_BETTER) {
    return { kind: "target_is_better", target: TARGET_IS_BETTER[scoreId] };
  }
  return null;
}

const CATALOG_ENTRIES: ReadonlyArray<readonly [string, string]> = Object.values(
  PERFORMANCE_FOCUS_CATALOG,
).flat() as ReadonlyArray<readonly [string, string]>;

const METRIC_METADATA: ReadonlyMap<string, PerformanceMetricMetadata> = (() => {
  const map = new Map<string, PerformanceMetricMetadata>();
  for (const [score_id, display_label] of CATALOG_ENTRIES) {
    if (map.has(score_id)) {
      continue;
    }
    const optimization = optimizationFor(score_id);
    if (optimization) {
      map.set(score_id, { score_id, display_label, optimization });
    }
  }
  // average_precision is a metadata-only higher-is-better alias -- it is
  // never added to PERFORMANCE_FOCUS_CATALOG and must never become a second
  // selectable Admin score beside pr_auc.
  map.set("average_precision", {
    score_id: "average_precision",
    display_label: "Average Precision",
    optimization: { kind: "higher_is_better" },
  });
  return map;
})();

/**
 * Looks up the deterministic optimization metadata for a known score id.
 * Returns undefined for any score id outside the closed catalog above --
 * unknown metrics must never receive an invented default direction.
 */
export function getPerformanceMetricMetadata(scoreId: string): PerformanceMetricMetadata | undefined {
  return METRIC_METADATA.get(scoreId);
}

// Project Spec S0215: problem-type applicability metadata for the first
// governed multiclass score surface. overall_discrimination,
// positive_class_detection, and operational_decision remain binary-only --
// they encode positive-class/ranking/cost semantics that have no governed
// multiclass meaning yet. balanced_classification and probability_quality
// apply to both problem types, but individual scores within them are
// further filtered by MULTICLASS_COMPATIBLE_SCORE_IDS below, since not
// every score in those two foci is multiclass-compatible.

export type ProblemType = "binary_classification" | "multiclass_classification";

const FOCUS_PROBLEM_TYPES: Readonly<Record<PerformanceFocusId, readonly ProblemType[]>> = {
  overall_discrimination: ["binary_classification"],
  positive_class_detection: ["binary_classification"],
  balanced_classification: ["binary_classification", "multiclass_classification"],
  probability_quality: ["binary_classification", "multiclass_classification"],
  operational_decision: ["binary_classification"],
};

// Project Spec S0215: the bounded set of score ids compatible with a
// multiclass problem type. The legacy ambiguous ids (f1_score, precision,
// recall, specificity, g_mean, ...) are never included here, even though
// they belong to a focus that is otherwise multiclass-applicable --
// averaging semantics are erased by those ids under multi-way
// classification. Calibration/Brier metrics are not yet marked
// multiclass-compatible until their multiclass semantics are separately
// governed.
const MULTICLASS_COMPATIBLE_SCORE_IDS: ReadonlySet<string> = new Set([
  "accuracy",
  "balanced_accuracy",
  "f1_macro",
  "f1_weighted",
  "precision_macro",
  "recall_macro",
  "log_loss",
]);

/** Whether a Performance focus applies to the given problem type. */
export function isPerformanceFocusApplicable(focusId: string, problemType: ProblemType): boolean {
  const applicable = (FOCUS_PROBLEM_TYPES as Record<string, readonly ProblemType[]>)[focusId];
  return applicable ? applicable.includes(problemType) : false;
}

/**
 * Whether an individual score id applies to the given problem type. Every
 * binary-classification score id remains applicable unchanged (preserves
 * historical Admin/public behavior exactly); for multiclass_classification
 * only the bounded MULTICLASS_COMPATIBLE_SCORE_IDS set is applicable.
 */
export function isPerformanceScoreApplicable(scoreId: string, problemType: ProblemType): boolean {
  if (problemType === "binary_classification") {
    return true;
  }
  return MULTICLASS_COMPATIBLE_SCORE_IDS.has(scoreId);
}

/** The Performance focus ids applicable to the given problem type, in catalog order. */
export function getApplicablePerformanceFocusIds(problemType: ProblemType): PerformanceFocusId[] {
  return (Object.keys(PERFORMANCE_FOCUS_CATALOG) as PerformanceFocusId[]).filter((focusId) =>
    isPerformanceFocusApplicable(focusId, problemType),
  );
}

/** The [score_id, display_label] entries of a focus applicable to the given problem type, in catalog order. */
export function getApplicableScoresForFocus(
  focusId: PerformanceFocusId,
  problemType: ProblemType,
): ReadonlyArray<readonly [string, string]> {
  return PERFORMANCE_FOCUS_CATALOG[focusId].filter(([scoreId]) =>
    isPerformanceScoreApplicable(scoreId, problemType),
  );
}
