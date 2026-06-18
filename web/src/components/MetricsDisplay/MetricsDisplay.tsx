const FRIENDLY_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  precision: "Precision",
  recall: "Recall",
  f1: "F1 Score",
  f1_score: "F1 Score",
  auc: "AUC",
  auc_roc: "AUC-ROC",
  roc_auc: "ROC-AUC",
  mae: "Mean Absolute Error",
  mse: "Mean Squared Error",
  rmse: "Root Mean Squared Error",
  r2: "R²",
  r2_score: "R²",
};

type MetricsData = Record<string, unknown>;

type Props = {
  metrics: MetricsData;
};

function formatValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

function labelFor(key: string): string {
  return FRIENDLY_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function MetricsDisplay({ metrics }: Props) {
  const entries = Object.entries(metrics).filter(
    ([, v]) => v !== null && v !== undefined && typeof v !== "object"
  );

  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="metrics-display">
      <h2>Model Performance</h2>
      <dl>
        {entries.map(([key, value]) => (
          <div key={key} className="metrics-display__item">
            <dt>{labelFor(key)}</dt>
            <dd>{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
