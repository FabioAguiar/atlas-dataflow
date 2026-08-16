export type NormalizedMetricKey =
  | "roc_auc"
  | "f1_score"
  | "pr_auc"
  | "precision"
  | "recall"
  | "accuracy"
  | "log_loss"
  // Project Spec S0215: explicit multiclass aggregate ids -- distinct from
  // the binary-era f1_score/precision/recall above, never collapsed into
  // them.
  | "balanced_accuracy"
  | "f1_macro"
  | "f1_weighted"
  | "precision_macro"
  | "recall_macro";

export type NormalizedMetrics = Partial<Record<NormalizedMetricKey, number>>;

export type NormalizedEvaluation = {
  scores: NormalizedMetrics;
  /** Available metric ids only, in deterministic display order (primary first). */
  order: NormalizedMetricKey[];
  primaryMetricId: NormalizedMetricKey | null;
};

const KNOWN_METRIC_KEYS: NormalizedMetricKey[] = [
  "roc_auc",
  "f1_score",
  "pr_auc",
  "precision",
  "recall",
  "accuracy",
  "log_loss",
  "balanced_accuracy",
  "f1_macro",
  "f1_weighted",
  "precision_macro",
  "recall_macro",
];

const METRIC_ALIASES: Record<NormalizedMetricKey, string[]> = {
  roc_auc: ["roc_auc", "auc_roc", "auc"],
  f1_score: ["f1_score", "f1"],
  pr_auc: ["pr_auc"],
  precision: ["precision"],
  recall: ["recall"],
  accuracy: ["accuracy"],
  log_loss: ["log_loss"],
  // Project Spec S0215: each explicit multiclass aggregate id is projected
  // 1:1 -- never aliased into an ambiguous binary-era id.
  balanced_accuracy: ["balanced_accuracy"],
  f1_macro: ["f1_macro"],
  f1_weighted: ["f1_weighted"],
  precision_macro: ["precision_macro"],
  recall_macro: ["recall_macro"],
};

function readScore(source: Record<string, unknown>, aliases: string[]): number | null {
  for (const key of aliases) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return null;
}

function isKnownMetricKey(value: string): value is NormalizedMetricKey {
  return (KNOWN_METRIC_KEYS as string[]).includes(value);
}

/**
 * GET /datasets/{slug}/metrics (Project Spec S0127) returns a stable
 * evaluation projection: evaluation.metrics holds alias-normalized public
 * metric ids, evaluation.metric_order is the backend's declared display
 * order, and evaluation.primary_metric_id names the canonical primary
 * metric when the backend resolved one. A bounded flat top-level fallback
 * (no evaluation wrapper at all) is retained for pre-S0127 fixtures/tests
 * that still pass raw flat metric objects directly -- it never becomes an
 * unbounded search, since only the closed KNOWN_METRIC_KEYS set is read.
 */
export function normalizeEvaluation(metrics: Record<string, unknown>): NormalizedEvaluation {
  const evaluation = metrics["evaluation"];
  const evaluationObject =
    evaluation && typeof evaluation === "object" ? (evaluation as Record<string, unknown>) : null;

  const nestedMetrics = evaluationObject?.["metrics"];
  const source =
    nestedMetrics && typeof nestedMetrics === "object"
      ? (nestedMetrics as Record<string, unknown>)
      : metrics;

  const scores: NormalizedMetrics = {};
  for (const key of KNOWN_METRIC_KEYS) {
    const value = readScore(source, METRIC_ALIASES[key]);
    if (value !== null) {
      scores[key] = value;
    }
  }

  const declaredOrder = evaluationObject?.["metric_order"];
  const orderCandidates = Array.isArray(declaredOrder)
    ? declaredOrder.filter((id): id is NormalizedMetricKey => typeof id === "string" && isKnownMetricKey(id))
    : KNOWN_METRIC_KEYS;

  const primaryCandidate = evaluationObject?.["primary_metric_id"];
  const primaryMetricId =
    typeof primaryCandidate === "string" &&
    isKnownMetricKey(primaryCandidate) &&
    scores[primaryCandidate] !== undefined
      ? primaryCandidate
      : null;

  const order: NormalizedMetricKey[] = [];
  if (primaryMetricId) {
    order.push(primaryMetricId);
  }
  for (const key of orderCandidates) {
    if (scores[key] !== undefined && !order.includes(key)) {
      order.push(key);
    }
  }
  for (const key of KNOWN_METRIC_KEYS) {
    if (scores[key] !== undefined && !order.includes(key)) {
      order.push(key);
    }
  }

  return { scores, order, primaryMetricId };
}
