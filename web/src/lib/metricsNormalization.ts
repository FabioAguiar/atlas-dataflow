export type NormalizedMetricKey = "auc_roc" | "precision" | "recall" | "f1_score";

export type NormalizedMetrics = Record<NormalizedMetricKey, number | null>;

const METRIC_ALIASES: Record<NormalizedMetricKey, string[]> = {
  auc_roc: ["auc_roc", "auc", "roc_auc"],
  precision: ["precision"],
  recall: ["recall"],
  f1_score: ["f1_score", "f1"],
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

/**
 * GET /datasets/{slug}/metrics currently always nests scores under
 * evaluation.metrics (confirmed against every metrics.json fixture in the
 * repository); this falls back to reading a flat top-level shape only if
 * evaluation.metrics is absent, and never invents a value for a score that
 * resolves to neither shape.
 */
export function normalizeMetrics(metrics: Record<string, unknown>): NormalizedMetrics {
  const evaluation = metrics["evaluation"];
  const nestedMetrics =
    evaluation && typeof evaluation === "object"
      ? (evaluation as Record<string, unknown>)["metrics"]
      : undefined;
  const source =
    nestedMetrics && typeof nestedMetrics === "object"
      ? (nestedMetrics as Record<string, unknown>)
      : metrics;

  return {
    auc_roc: readScore(source, METRIC_ALIASES.auc_roc),
    precision: readScore(source, METRIC_ALIASES.precision),
    recall: readScore(source, METRIC_ALIASES.recall),
    f1_score: readScore(source, METRIC_ALIASES.f1_score),
  };
}
