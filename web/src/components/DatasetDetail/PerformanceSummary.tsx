import { Badge, Card } from "../ui";
import { normalizeEvaluation, type NormalizedMetricKey } from "../../lib/metricsNormalization";
import {
  getPerformanceFocusLabel,
  getPerformanceMetricMetadata,
  isPerformanceScoreApplicable,
  type OptimizationSemantics,
  type ProblemType,
} from "../../lib/performanceMetricMetadata";

type MetricsData = Record<string, unknown>;

export type PerformanceFocus = {
  focus_id: "overall_discrimination" | "positive_class_detection" | "balanced_classification" | "probability_quality" | "operational_decision" | "regression_performance";
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
  /**
   * Project Spec S0215: release-governed problem type. Optional and
   * bounded -- omitted or unrecognized values preserve the historical
   * binary-compatible rendering exactly. Never derived from dataset slug or
   * editable profile fields.
   */
  problemType?: ProblemType | null;
};

const SCORE_LABELS: Record<NormalizedMetricKey, string> = {
  roc_auc: "AUC ROC",
  f1_score: "F1-score",
  pr_auc: "PR AUC",
  precision: "Precision",
  recall: "Recall",
  accuracy: "Accuracy",
  log_loss: "Log Loss",
  // Project Spec S0215: explicit multiclass aggregate labels -- never
  // relabeled as the ambiguous binary-era f1_score/precision/recall above.
  balanced_accuracy: "Balanced Accuracy",
  f1_macro: "F1 Macro",
  f1_weighted: "F1 Weighted",
  precision_macro: "Precision Macro",
  recall_macro: "Recall Macro",
  // Project Spec S0229: continuous-regression score labels.
  r2: "R²",
  mae: "MAE",
  rmse: "RMSE",
};

function formatScore(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * Project Spec S0203/S0221: the monotonic ↑/↓ pair rendered directly beside
 * the score value -- always in ↑-then-↓ order regardless of direction, with
 * only the favorable/unfavorable color class swapped between
 * higher-is-better and lower-is-better; no visible "favorable"/"unfavorable"
 * word is ever rendered. As of S0221 there is no visible "Higher is
 * better"/"Lower is better" line anymore, so the two glyphs stay
 * individually aria-hidden while the wrapping group itself carries the
 * orientation as a single accessible name (role="img" + aria-label) --
 * that keeps the meaning available to assistive technology, never relying
 * on color alone, without the hidden glyphs also being announced and
 * duplicating it. Renders nothing for a target-based metric, which keeps
 * its neutral "Closer to X is better" guidance instead.
 */
function ScoreArrows({ optimization }: { optimization: OptimizationSemantics }) {
  if (optimization.kind === "target_is_better") {
    return null;
  }

  const upIsFavorable = optimization.kind === "higher_is_better";
  const orientationLabel = upIsFavorable ? "Higher is better" : "Lower is better";
  return (
    <span className="performance-summary__score-arrows" role="img" aria-label={orientationLabel}>
      <span
        className={`performance-summary__score-orientation-arrow performance-summary__score-orientation-arrow--${upIsFavorable ? "favorable" : "unfavorable"}`}
        aria-hidden="true"
      >
        ↑
      </span>
      <span
        className={`performance-summary__score-orientation-arrow performance-summary__score-orientation-arrow--${upIsFavorable ? "unfavorable" : "favorable"}`}
        aria-hidden="true"
      >
        ↓
      </span>
    </span>
  );
}

/**
 * Project Spec S0200/S0203/S0221: the explanatory target-based orientation
 * text for a score tile, sourced exclusively from the shared
 * performanceMetricMetadata module so public rendering can never diverge
 * from Admin's. As of S0221, a monotonic (higher/lower-is-better) score no
 * longer renders a visible secondary line here at all -- that orientation
 * is carried only by ScoreArrows' accessible group label above. Only the
 * neutral target-based guidance still renders visibly, never relying on the
 * arrow pair or color alone.
 */
function ScoreDirection({ optimization }: { optimization: OptimizationSemantics }) {
  if (optimization.kind !== "target_is_better") {
    return null;
  }

  return (
    <p className="performance-summary__score-orientation performance-summary__score-orientation--target">
      <span aria-hidden="true">◎</span> Closer to {optimization.target} is better
    </p>
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

export default function PerformanceSummary({
  metrics,
  emphasizedMetricKey,
  performanceFocus,
  problemType,
}: PerformanceSummaryProps) {
  const evaluation = normalizeEvaluation(metrics);
  const isMulticlass = problemType === "multiclass_classification";
  // Project Spec S0229: a continuous-regression release must only ever
  // render the bounded r2/mae/rmse catalog, never a classification score
  // that happens to still be persisted from before the release became
  // continuous_regression.
  const isContinuousRegression = problemType === "continuous_regression";
  // Project Spec S0215: for a multiclass release, never present an
  // ambiguous binary-only published score id (f1_score, precision, recall,
  // specificity, g_mean, ...) as multiclass-compatible -- even if it was
  // persisted by Admin before the release became multiclass. Binary
  // rendering is completely unaffected.
  const publishedScores = performanceFocus?.visible_scores
    .filter((score) => (!isMulticlass && !isContinuousRegression) || isPerformanceScoreApplicable(score.score_id, problemType!))
    .slice()
    .sort((left, right) => left.order - right.order || left.score_id.localeCompare(right.score_id));
  const hasPublishedFocus = Boolean(performanceFocus && publishedScores?.length);
  // Project Spec S0215/S0229: the canonical fallback path also only renders
  // recognized explicit multiclass/regression ids for that release's problem type.
  const fallbackOrder = isMulticlass || isContinuousRegression
    ? evaluation.order.filter((key) => isPerformanceScoreApplicable(key, problemType!))
    : evaluation.order;
  const hasAnyScore = fallbackOrder.length > 0;
  // Project Spec S0204: the shared focus label authority is the single
  // source for this subtitle -- an unknown focus id never invents a label
  // from the raw id, it simply omits the subtitle.
  const focusLabel = performanceFocus ? getPerformanceFocusLabel(performanceFocus.focus_id) : undefined;

  if (!hasPublishedFocus && !hasAnyScore) {
    return null;
  }

  const resolvedEmphasis = resolveEmphasizedScore(emphasizedMetricKey, fallbackOrder, evaluation.primaryMetricId);

  return (
    <Card className="performance-summary">
      <h3>Performance Summary</h3>
      {hasPublishedFocus && focusLabel && (
        <p className="performance-summary__focus">{focusLabel}</p>
      )}
      <dl className="performance-summary__scores">
        {hasPublishedFocus && performanceFocus ? publishedScores!.map((score) => {
          const emphasized = score.score_id === performanceFocus.highlighted_score_id;
          const optimization = getPerformanceMetricMetadata(score.score_id)?.optimization;
          return (
            <div
              key={score.score_id}
              className={`performance-summary__score${emphasized ? " performance-summary__score--emphasized" : ""}`}
            >
              <div className="performance-summary__score-primary">
                <dt>{score.display_label}{emphasized && <Badge>Highlighted</Badge>}</dt>
                <dd>
                  {score.value}
                  {optimization && <ScoreArrows optimization={optimization} />}
                </dd>
              </div>
              {optimization && <ScoreDirection optimization={optimization} />}
              <span className="performance-summary__score-rail" aria-hidden="true" />
            </div>
          );
        }) : fallbackOrder.map((key) => {
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
          const optimization = getPerformanceMetricMetadata(key)?.optimization;

          return (
            <div key={key} className={itemClasses}>
              <div className="performance-summary__score-primary">
                <dt>
                  {SCORE_LABELS[key]}
                  {emphasized && <Badge>Highlighted</Badge>}
                </dt>
                <dd>
                  {formatScore(value)}
                  {optimization && <ScoreArrows optimization={optimization} />}
                </dd>
              </div>
              {optimization && <ScoreDirection optimization={optimization} />}
              <span className="performance-summary__score-rail" aria-hidden="true" />
            </div>
          );
        })}
      </dl>
    </Card>
  );
}
