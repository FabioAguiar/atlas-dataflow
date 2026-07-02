import { Badge, Card } from "../ui";
import { normalizeMetrics, type NormalizedMetricKey } from "../../lib/metricsNormalization";

type MetricsData = Record<string, unknown>;

type PerformanceSummaryProps = {
  metrics: MetricsData;
};

const SCORE_ORDER: NormalizedMetricKey[] = ["auc_roc", "precision", "recall", "f1_score"];

const SCORE_LABELS: Record<NormalizedMetricKey, string> = {
  auc_roc: "AUC ROC",
  precision: "Precision",
  recall: "Recall",
  f1_score: "F1-score",
};

const EMPHASIZED_SCORE: NormalizedMetricKey = "auc_roc";

function formatScore(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export default function PerformanceSummary({ metrics }: PerformanceSummaryProps) {
  const normalized = normalizeMetrics(metrics);
  const hasAnyScore = SCORE_ORDER.some((key) => normalized[key] !== null);

  if (!hasAnyScore) {
    return null;
  }

  return (
    <Card className="performance-summary">
      <h3>Performance Summary</h3>
      <dl className="performance-summary__scores">
        {SCORE_ORDER.map((key) => {
          const value = normalized[key];
          const emphasized = key === EMPHASIZED_SCORE;
          const itemClasses = [
            "performance-summary__score",
            emphasized ? "performance-summary__score--emphasized" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <div key={key} className={itemClasses}>
              <dt>
                {SCORE_LABELS[key]}
                {emphasized && <Badge>Highlighted</Badge>}
              </dt>
              <dd>
                {value === null ? (
                  <span className="performance-summary__score-pending">Not available</span>
                ) : (
                  formatScore(value)
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </Card>
  );
}
