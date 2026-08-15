import { Badge, Card } from "../ui";
import { normalizeEvaluation, type NormalizedMetricKey } from "../../lib/metricsNormalization";
import { getPerformanceMetricMetadata } from "../../lib/performanceMetricMetadata";

type MetricsData = Record<string, unknown>;

export type PerformanceFocus = {
  focus_id: "overall_discrimination" | "positive_class_detection" | "balanced_classification" | "probability_quality" | "operational_decision";
  highlighted_score_id: string;
  visible_scores: Array<{
    score_id: string;
    display_label: string;
    value: string;
    value_source: "canonical" | "manual";
    order: number;
  }>;
};

type PerformanceSummaryProps = {
  metrics: MetricsData;
  emphasizedMetricKey?: string | null;
  performanceFocus?: PerformanceFocus | null;
};

const SCORE_LABELS: Record<NormalizedMetricKey, string> = {
  roc_auc: "AUC ROC",
  f1_score: "F1-score",
  pr_auc: "PR AUC",
  precision: "Precision",
  recall: "Recall",
  accuracy: "Accuracy",
  log_loss: "Log Loss",
};

const FOCUS_LABELS: Record<PerformanceFocus["focus_id"], string> = {
  overall_discrimination: "Overall discrimination",
  positive_class_detection: "Positive-class detection",
  balanced_classification: "Balanced classification",
  probability_quality: "Probability quality",
  operational_decision: "Operational decision",
};

function formatScore(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * Project Spec S0200: the explanatory-only orientation for a score tile --
 * sourced exclusively from the shared performanceMetricMetadata module, so
 * public rendering can never diverge from Admin's. Renders nothing for an
 * unknown score id (no invented default direction), and never shows an
 * opposing favorable/unfavorable arrow pair for a target-based metric.
 *
 * Project Spec S0201: for a monotonic (higher/lower-is-better) score, both
 * directions render together -- an "↑ favorable"/"↓ unfavorable" pair (or
 * the reverse for lower-is-better) plus the existing "Higher/Lower is
 * better" explanatory text, so direction is never implied by a single arrow
 * or by color alone.
 */
function ScoreOrientation({ scoreId }: { scoreId: string }) {
  const metadata = getPerformanceMetricMetadata(scoreId);
  if (!metadata) {
    return null;
  }

  if (metadata.optimization.kind === "target_is_better") {
    return (
      <p className="performance-summary__score-orientation performance-summary__score-orientation--target">
        <span aria-hidden="true">◎</span> Closer to {metadata.optimization.target} is better
      </p>
    );
  }

  const higherIsBetter = metadata.optimization.kind === "higher_is_better";
  const favorableArrow = higherIsBetter ? "↑" : "↓";
  const unfavorableArrow = higherIsBetter ? "↓" : "↑";
  return (
    <div className="performance-summary__score-orientation performance-summary__score-orientation--monotonic">
      <span className="performance-summary__score-orientation-arrow performance-summary__score-orientation-arrow--favorable">
        <span aria-hidden="true">{favorableArrow}</span> favorable
      </span>
      <span className="performance-summary__score-orientation-arrow performance-summary__score-orientation-arrow--unfavorable">
        <span aria-hidden="true">{unfavorableArrow}</span> unfavorable
      </span>
      <span className="performance-summary__score-orientation-label">
        {higherIsBetter ? "Higher is better" : "Lower is better"}
      </span>
    </div>
  );
}

/**
 * primary_metric_key is free-text admin input, unlike the closed
 * NormalizedMetricKey set this component actually computes -- an
 * unrecognized value falls back to the backend-resolved canonical primary
 * metric (Project Spec S0127), and only falls back further to the first
 * available score when no canonical primary metric was resolved either.
 */
function resolveEmphasizedScore(
  emphasizedMetricKey: string | null | undefined,
  order: NormalizedMetricKey[],
  primaryMetricId: NormalizedMetricKey | null,
): NormalizedMetricKey | null {
  const candidate = emphasizedMetricKey?.trim();
  if (candidate && (order as string[]).includes(candidate)) {
    return candidate as NormalizedMetricKey;
  }
  return primaryMetricId ?? order[0] ?? null;
}

export default function PerformanceSummary({ metrics, emphasizedMetricKey, performanceFocus }: PerformanceSummaryProps) {
  const evaluation = normalizeEvaluation(metrics);
  const publishedScores = performanceFocus?.visible_scores
    .slice()
    .sort((left, right) => left.order - right.order || left.score_id.localeCompare(right.score_id));
  const hasPublishedFocus = Boolean(performanceFocus && publishedScores?.length);
  const hasAnyScore = evaluation.order.length > 0;

  if (!hasPublishedFocus && !hasAnyScore) {
    return null;
  }

  const resolvedEmphasis = resolveEmphasizedScore(emphasizedMetricKey, evaluation.order, evaluation.primaryMetricId);

  return (
    <Card className="performance-summary">
      <h3>Performance Summary</h3>
      {hasPublishedFocus && performanceFocus && (
        <p className="performance-summary__focus">{FOCUS_LABELS[performanceFocus.focus_id]}</p>
      )}
      <dl className="performance-summary__scores">
        {hasPublishedFocus && performanceFocus ? publishedScores!.map((score) => {
          const emphasized = score.score_id === performanceFocus.highlighted_score_id;
          return (
            <div
              key={score.score_id}
              className={`performance-summary__score${emphasized ? " performance-summary__score--emphasized" : ""}`}
            >
              <div className="performance-summary__score-primary">
                <dt>{score.display_label}{emphasized && <Badge>Highlighted</Badge>}</dt>
                <dd>{score.value}</dd>
              </div>
              <ScoreOrientation scoreId={score.score_id} />
              <span className="performance-summary__score-rail" aria-hidden="true" />
            </div>
          );
        }) : evaluation.order.map((key) => {
          const value = evaluation.scores[key];
          if (value === undefined) {
            return null;
          }
          const emphasized = key === resolvedEmphasis;
          const itemClasses = [
            "performance-summary__score",
            emphasized ? "performance-summary__score--emphasized" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <div key={key} className={itemClasses}>
              <div className="performance-summary__score-primary">
                <dt>
                  {SCORE_LABELS[key]}
                  {emphasized && <Badge>Highlighted</Badge>}
                </dt>
                <dd>{formatScore(value)}</dd>
              </div>
              <ScoreOrientation scoreId={key} />
              <span className="performance-summary__score-rail" aria-hidden="true" />
            </div>
          );
        })}
      </dl>
    </Card>
  );
}
