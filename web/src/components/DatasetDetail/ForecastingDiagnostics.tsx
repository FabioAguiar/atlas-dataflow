import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, EmptyState } from "../ui";
import { getPerformanceMetricMetadata } from "../../lib/performanceMetricMetadata";
import {
  datasetChartTooltipProps,
  formatTooltipCount,
  useChartInteractionMode,
  type DatasetChartTooltipModel,
} from "./DatasetChartTooltip";
import type { VisualizationsPayload } from "./TargetDistribution";

type ForecastingDiagnosticsProps = {
  visualizations: VisualizationsPayload | null;
  /**
   * Project Spec S0275: the already-projected, already-validated forecasting
   * highlighted score id. Presentation-selection input only -- the caller
   * (public DatasetPage / Admin Live Preview) is responsible for supplying it
   * only for a valid `forecasting_performance` focus whose highlighted id is
   * one of the published/projected visible scores. This component never reads
   * a raw profile field, score value, dataset slug, or model name, and never
   * computes a metric.
   */
  highlightedScoreId?: string | null;
};

type RawSeasonalPoint = { season_position?: number; mean_target?: number; observation_count?: number };
type RawFoldPoint = { fold_index?: number; forecast_origin?: string; value?: number };
type RawHorizonPoint = { horizon_step?: number; mae?: number };

// Project Spec S0274 diagnostic vocabulary: the closed set of governed
// forecasting metric ids an S0274 metric_diagnostics entry may carry. Kept in
// sync with api/public_visualizations_loader.py::_FORECASTING_SUPPORTED_METRIC_IDS
// and pipeline/analytical-visualizations.schema.json's forecasting metric enum.
const FORECASTING_DIAGNOSTIC_METRIC_IDS: ReadonlySet<string> = new Set(["mae", "rmse", "seasonal_mase"]);

type RawMetricDiagnosticEntry = {
  metric_id?: string;
  direction?: string;
  backtesting_by_origin?: {
    points?: Array<{ fold_index?: number; forecast_origin?: string; value?: number }>;
  };
  by_horizon?: {
    points?: Array<{ horizon_step?: number; value?: number; observation_count?: number }>;
  };
};

type ValidSelectedMetric = {
  metricId: string;
  label: string;
  byOrigin: Array<{ label: string; value: number }>;
  // Project Spec S0277: the already-public, already-validated per-horizon
  // observation_count is preserved on each by-horizon point so the tooltip can
  // expose it. It is never fabricated -- a v7 metric_diagnostics entry always
  // carries it (getValidSelectedMetric fails closed without it).
  byHorizon: Array<{ label: string; value: number; observationCount: number }>;
};

type MetricSelection =
  // No S0274 metric_diagnostics block -> historical v4/v6 legacy rendering.
  | { kind: "legacy" }
  // Exactly one governed, coherent v7 metric entry drives both cards.
  | { kind: "selected"; metric: ValidSelectedMetric }
  // v7 metric_diagnostics present but the selected metric could not be
  // resolved coherently -> fail closed, never substitute another metric.
  | { kind: "unavailable" };

type ValidSeasonalProfile = {
  // Project Spec S0277: the already-public seasonal-profile observation_count
  // is preserved through validation when present (and valid) so the tooltip
  // can expose it. A historical point without it renders without it -- the
  // count is never inferred.
  points: Array<{ label: string; mean_target: number; observationCount?: number }>;
};

type ValidFoldMetric = {
  metricId: string;
  points: Array<{ label: string; value: number }>;
};

type ValidHorizonMae = {
  points: Array<{ label: string; mae: number }>;
};

const EMPTY_MESSAGE = "This visualization has not been generated yet for this release.";
const CHART_PRIMARY = "var(--dataset-theme-chart-primary)";
const CHART_SECONDARY = "var(--dataset-theme-chart-secondary)";
const CHART_GRID = "var(--dataset-theme-chart-grid)";

function formatValue(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * The Seasonal Profile only renders when every point carries a finite,
 * non-negative integer season position and a finite mean target -- anything
 * malformed degrades to the bounded empty state. The x-axis label is a
 * generic seasonal position, never an inferred calendar-month name.
 */
function getValidSeasonalProfile(points: RawSeasonalPoint[] | undefined): ValidSeasonalProfile | null {
  if (!points || points.length === 0) {
    return null;
  }
  const validated: Array<{ label: string; mean_target: number; observationCount?: number }> = [];
  for (const point of points) {
    const { season_position: position, mean_target: meanTarget, observation_count: observationCount } = point;
    if (
      typeof position !== "number" ||
      !Number.isInteger(position) ||
      position < 0 ||
      typeof meanTarget !== "number" ||
      !Number.isFinite(meanTarget)
    ) {
      return null;
    }
    if (
      observationCount !== undefined &&
      (typeof observationCount !== "number" || !Number.isInteger(observationCount) || observationCount < 1)
    ) {
      return null;
    }
    validated.push({
      label: `Position ${position}`,
      mean_target: meanTarget,
      ...(observationCount !== undefined ? { observationCount } : {}),
    });
  }
  return { points: validated };
}

/**
 * Backtesting by Origin only renders when every point carries a non-empty
 * forecast origin label and a finite metric value -- points are already
 * ordered by fold as projected by the API, never re-sorted here.
 */
function getValidFoldMetric(
  metricId: string | undefined,
  points: RawFoldPoint[] | undefined,
): ValidFoldMetric | null {
  if (!metricId || !points || points.length === 0) {
    return null;
  }
  const validated: Array<{ label: string; value: number }> = [];
  for (const point of points) {
    const { forecast_origin: origin, value } = point;
    if (typeof origin !== "string" || !origin || typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    validated.push({ label: origin, value });
  }
  return { metricId, points: validated };
}

/**
 * Horizon MAE only renders when every point carries a positive integer
 * horizon step and a finite, non-negative MAE value.
 */
function getValidHorizonMae(points: RawHorizonPoint[] | undefined): ValidHorizonMae | null {
  if (!points || points.length === 0) {
    return null;
  }
  const validated: Array<{ label: string; mae: number }> = [];
  for (const point of points) {
    const { horizon_step: step, mae } = point;
    if (
      typeof step !== "number" ||
      !Number.isInteger(step) ||
      step < 1 ||
      typeof mae !== "number" ||
      !Number.isFinite(mae) ||
      mae < 0
    ) {
      return null;
    }
    validated.push({ label: `h+${step}`, mae });
  }
  return { points: validated };
}

// ---------------------------------------------------------------------------
// Project Spec S0275: highlighted-score-driven selection of one governed
// S0274 metric-diagnostic entry. This block adds no metric formula -- it only
// validates the shape of an already-projected v7 entry and picks the single
// coherent match for the caller's highlighted score. A legacy MAE series is
// never relabeled, and an explicit highlighted metric absent from the v7
// evidence fails closed rather than silently falling back to another metric.
// ---------------------------------------------------------------------------

/**
 * Whether a score id names a forecasting-compatible, lower-is-better metric
 * that the S0274 diagnostic vocabulary represents. The shared performance
 * metric metadata module stays the single label/direction authority -- this
 * component never declares a local forecasting metric map.
 */
function isForecastingDiagnosticMetricId(scoreId: string): boolean {
  if (!FORECASTING_DIAGNOSTIC_METRIC_IDS.has(scoreId)) {
    return false;
  }
  return getPerformanceMetricMetadata(scoreId)?.optimization.kind === "lower_is_better";
}

/**
 * Bounded validation of one projected S0274 metric-diagnostic entry. Returns
 * null (so the caller fails closed) on any missing/malformed leaf -- a
 * malformed selected entry is never handed to Recharts, and no fold or
 * horizon value is recomputed. Point order is preserved as projected by the
 * API (already fold/step ordered); it is not re-sorted here.
 */
function getValidSelectedMetric(entry: RawMetricDiagnosticEntry | undefined): ValidSelectedMetric | null {
  if (!entry || typeof entry !== "object") {
    return null;
  }
  const metricId = entry.metric_id;
  if (typeof metricId !== "string" || !isForecastingDiagnosticMetricId(metricId)) {
    return null;
  }
  if (entry.direction !== "lower_is_better") {
    return null;
  }
  const label = getPerformanceMetricMetadata(metricId)?.display_label;
  if (!label) {
    return null;
  }

  const originPoints = entry.backtesting_by_origin?.points;
  if (!Array.isArray(originPoints) || originPoints.length === 0) {
    return null;
  }
  const byOrigin: Array<{ label: string; value: number }> = [];
  const seenFolds = new Set<number>();
  for (const point of originPoints) {
    if (!point || typeof point !== "object") {
      return null;
    }
    const { fold_index: fold, forecast_origin: origin, value } = point;
    if (typeof fold !== "number" || !Number.isInteger(fold) || fold < 0 || seenFolds.has(fold)) {
      return null;
    }
    seenFolds.add(fold);
    if (typeof origin !== "string" || !origin) {
      return null;
    }
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return null;
    }
    byOrigin.push({ label: origin, value });
  }

  const horizonPoints = entry.by_horizon?.points;
  if (!Array.isArray(horizonPoints) || horizonPoints.length === 0) {
    return null;
  }
  const byHorizon: Array<{ label: string; value: number; observationCount: number }> = [];
  const seenSteps = new Set<number>();
  for (const point of horizonPoints) {
    if (!point || typeof point !== "object") {
      return null;
    }
    const { horizon_step: step, value, observation_count: observationCount } = point;
    if (typeof step !== "number" || !Number.isInteger(step) || step < 1 || seenSteps.has(step)) {
      return null;
    }
    seenSteps.add(step);
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return null;
    }
    if (typeof observationCount !== "number" || !Number.isInteger(observationCount) || observationCount < 1) {
      return null;
    }
    byHorizon.push({ label: `h+${step}`, value, observationCount });
  }

  return { metricId, label, byOrigin, byHorizon };
}

/**
 * Resolves which metric drives Backtesting by Origin + Horizon:
 *   - no metric_diagnostics block            -> legacy v4/v6 rendering
 *   - valid explicit highlighted id + match  -> that metric (both cards)
 *   - valid explicit highlighted id, no match/malformed -> unavailable (fail
 *     closed; never substitute legacy MAE or the primary metric)
 *   - no valid explicit highlighted id       -> deterministic governed
 *     fallback to backtesting_fold_metric.metric_id, requiring a coherent
 *     matching v7 entry; otherwise unavailable
 */
export function resolveMetricSelection(
  diagnostics: NonNullable<VisualizationsPayload["forecasting_diagnostics"]> | null,
  highlightedScoreId: string | null | undefined,
): MetricSelection {
  const metricDiagnostics = diagnostics?.metric_diagnostics;
  if (metricDiagnostics === undefined || metricDiagnostics === null) {
    return { kind: "legacy" };
  }
  const metrics = metricDiagnostics.metrics;
  if (!Array.isArray(metrics) || metrics.length === 0) {
    return { kind: "unavailable" };
  }

  const explicitId = typeof highlightedScoreId === "string" ? highlightedScoreId.trim() : "";
  if (explicitId && isForecastingDiagnosticMetricId(explicitId)) {
    const match = getValidSelectedMetric(metrics.find((metric) => metric?.metric_id === explicitId));
    return match ? { kind: "selected", metric: match } : { kind: "unavailable" };
  }

  const fallbackId = diagnostics?.backtesting_fold_metric?.metric_id;
  if (typeof fallbackId === "string" && isForecastingDiagnosticMetricId(fallbackId)) {
    const match = getValidSelectedMetric(metrics.find((metric) => metric?.metric_id === fallbackId));
    if (match) {
      return { kind: "selected", metric: match };
    }
  }
  return { kind: "unavailable" };
}

// ---------------------------------------------------------------------------
// Project Spec S0277: bounded device-adaptive tooltip content for the
// forecasting diagnostic charts. Each builder consumes only an
// already-validated chart datum plus the currently rendered metric identity
// -- it selects no metric, relabels nothing, computes no MAE/RMSE/Seasonal-MASE
// (or any error statistic), and never fabricates an observation count.
// ---------------------------------------------------------------------------

export function buildForecastVsActualTooltipModel(
  datum: Record<string, unknown>,
): DatasetChartTooltipModel | null {
  const label = typeof datum.label === "string" && datum.label ? datum.label : null;
  const actual = typeof datum.actual === "number" && Number.isFinite(datum.actual) ? datum.actual : null;
  const forecast = typeof datum.forecast === "number" && Number.isFinite(datum.forecast) ? datum.forecast : null;
  if (label === null || actual === null || forecast === null) {
    return null;
  }
  return {
    title: label,
    rows: [
      { label: "Period", value: label },
      { label: "Actual", value: formatValue(actual) },
      { label: "Forecast", value: formatValue(forecast) },
    ],
  };
}

export function buildBacktestingTooltipModel(
  seriesLabel: string | null,
  datum: Record<string, unknown>,
): DatasetChartTooltipModel | null {
  const label = typeof datum.label === "string" && datum.label ? datum.label : null;
  const value = typeof datum.value === "number" && Number.isFinite(datum.value) ? datum.value : null;
  if (!seriesLabel || label === null || value === null) {
    return null;
  }
  return {
    title: label,
    rows: [
      { label: "Forecast origin", value: label },
      { label: seriesLabel, value: formatValue(value) },
    ],
  };
}

export function buildHorizonTooltipModel(
  seriesLabel: string,
  datum: Record<string, unknown>,
): DatasetChartTooltipModel | null {
  const label = typeof datum.label === "string" && datum.label ? datum.label : null;
  const value = typeof datum.value === "number" && Number.isFinite(datum.value) ? datum.value : null;
  if (!seriesLabel || label === null || value === null) {
    return null;
  }
  const rows = [
    { label: "Horizon step", value: label },
    { label: seriesLabel, value: formatValue(value) },
  ];
  const observationCount = datum.observationCount;
  if (typeof observationCount === "number" && Number.isInteger(observationCount) && observationCount >= 1) {
    rows.push({ label: "Observations", value: formatTooltipCount(observationCount) });
  }
  return { title: label, rows };
}

export function buildSeasonalProfileTooltipModel(
  datum: Record<string, unknown>,
): DatasetChartTooltipModel | null {
  const label = typeof datum.label === "string" && datum.label ? datum.label : null;
  const meanTarget =
    typeof datum.mean_target === "number" && Number.isFinite(datum.mean_target) ? datum.mean_target : null;
  if (label === null || meanTarget === null) {
    return null;
  }
  const rows = [
    { label: "Season position", value: label },
    { label: "Mean target", value: formatValue(meanTarget) },
  ];
  const observationCount = datum.observationCount;
  if (typeof observationCount === "number" && Number.isInteger(observationCount) && observationCount >= 1) {
    rows.push({ label: "Observations", value: formatTooltipCount(observationCount) });
  }
  return { title: label, rows };
}

// ---------------------------------------------------------------------------
// Project Spec S0270 evidence, S0272 presentation: the shared final-holdout
// forecast-evaluation overview. It consumes only the bounded public
// visualizations.forecasting_evaluation projection (plus the already-present
// forecasting_diagnostics.forecast_horizon) -- never a dataset slug, model
// name, raw training/history vector, inference executor, or external study
// data. It performs bounded frontend validation before drawing any chart so a
// malformed present projection never produces misleading partial evidence,
// and it derives no evaluation metric (MAE/RMSE/seasonal-MASE or a
// replacement score) from the projected points -- PerformanceSummary remains
// the independent metric authority.
// ---------------------------------------------------------------------------

type RawEvaluationBoundary = {
  start_index?: string;
  end_index?: string;
  observation_count?: number;
};

type ValidEvaluationBoundary = {
  startIndex: string;
  endIndex: string;
  observationCount: number;
};

type ValidForecastingEvaluation = {
  indexValueKind: string;
  frequency: string;
  development: ValidEvaluationBoundary;
  finalHoldout: ValidEvaluationBoundary;
  forecastHorizon: number | null;
  points: Array<{ timeIndex: string; actual: number; forecast: number }>;
};

const FORECAST_VS_ACTUAL_TITLE = "Forecast vs Actual — Final Holdout";
const EVALUATION_UNAVAILABLE_MESSAGE =
  "This release does not carry a complete governed final-holdout forecast evaluation.";

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isFiniteNumber(value: unknown): value is number {
  // typeof already excludes booleans; Number.isFinite rejects NaN/Infinity.
  return typeof value === "number" && Number.isFinite(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function getValidEvaluationBoundary(value: RawEvaluationBoundary | undefined): ValidEvaluationBoundary | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const { start_index: startIndex, end_index: endIndex, observation_count: observationCount } = value;
  if (!nonEmptyString(startIndex) || !nonEmptyString(endIndex) || !isPositiveInteger(observationCount)) {
    return null;
  }
  return { startIndex, endIndex, observationCount };
}

/**
 * The final-holdout evaluation renders only when every governed public
 * semantic is coherent. Anything missing, malformed, or internally
 * inconsistent returns null so the caller can fail closed instead of handing
 * partial/incorrect values to Recharts. The projected boundaries and points
 * are used verbatim -- no point is added or dropped, no chronological index is
 * reconstructed, and no metric is computed.
 */
function getValidForecastingEvaluation(
  visualizations: VisualizationsPayload | null,
): ValidForecastingEvaluation | null {
  const evaluation = visualizations?.forecasting_evaluation;
  if (!evaluation || typeof evaluation !== "object") {
    return null;
  }

  if (!nonEmptyString(evaluation.index_value_kind) || !nonEmptyString(evaluation.frequency)) {
    return null;
  }

  const development = getValidEvaluationBoundary(evaluation.development_boundary);
  const finalHoldout = getValidEvaluationBoundary(evaluation.final_holdout_boundary);
  if (!development || !finalHoldout) {
    return null;
  }

  const flags = evaluation.evaluation;
  if (
    !flags ||
    typeof flags !== "object" ||
    flags.split_name !== "final_holdout" ||
    flags.evaluation_count !== 1 ||
    flags.model_frozen_before_open !== true ||
    flags.forecast_generated_before_target_open !== true
  ) {
    return null;
  }

  const { points } = evaluation;
  if (!Array.isArray(points) || points.length === 0) {
    return null;
  }
  if (points.length !== finalHoldout.observationCount) {
    return null;
  }

  // The diagnostics forecast_horizon is optional, but when present it must
  // agree with the projected point count -- a mismatch means the projection is
  // internally inconsistent. A missing horizon never invents a competing one.
  const rawHorizon = visualizations?.forecasting_diagnostics?.forecast_horizon;
  let forecastHorizon: number | null = null;
  if (rawHorizon !== undefined) {
    if (!isPositiveInteger(rawHorizon) || rawHorizon !== points.length) {
      return null;
    }
    forecastHorizon = rawHorizon;
  }

  const seenLabels = new Set<string>();
  const validatedPoints: Array<{ timeIndex: string; actual: number; forecast: number }> = [];
  for (const point of points) {
    if (!point || typeof point !== "object") {
      return null;
    }
    const { time_index: timeIndex, actual, forecast } = point;
    if (!nonEmptyString(timeIndex) || seenLabels.has(timeIndex)) {
      return null;
    }
    seenLabels.add(timeIndex);
    if (!isFiniteNumber(actual) || !isFiniteNumber(forecast)) {
      return null;
    }
    validatedPoints.push({ timeIndex, actual, forecast });
  }

  if (
    validatedPoints[0].timeIndex !== finalHoldout.startIndex ||
    validatedPoints[validatedPoints.length - 1].timeIndex !== finalHoldout.endIndex
  ) {
    return null;
  }

  return {
    indexValueKind: evaluation.index_value_kind,
    frequency: evaluation.frequency,
    development,
    finalHoldout,
    forecastHorizon,
    points: validatedPoints,
  };
}

/**
 * Shared final-holdout forecast-evaluation overview rendered by both the
 * public Dataset Detail route and Admin Live Preview through the same
 * DatasetDetailSurface slot. Returns null when no evaluation projection is
 * present (historical v4 releases keep their exact prior Overview), and a
 * bounded non-chart "evaluation unavailable" surface when a projection is
 * present but fails validation.
 */
export function ForecastingEvaluationOverview({ visualizations }: ForecastingDiagnosticsProps) {
  const interactionMode = useChartInteractionMode();
  const rawEvaluation = visualizations?.forecasting_evaluation;
  if (rawEvaluation === undefined || rawEvaluation === null) {
    return null;
  }

  const evaluation = getValidForecastingEvaluation(visualizations);
  if (!evaluation) {
    return (
      <Card className="dataset-detail-visualization dataset-detail-forecasting-evaluation dataset-detail-forecasting-evaluation--unavailable">
        <h3>{FORECAST_VS_ACTUAL_TITLE}</h3>
        <EmptyState message={EVALUATION_UNAVAILABLE_MESSAGE} title="Evaluation unavailable" />
      </Card>
    );
  }

  const { points } = evaluation;
  const chartData = points.map((point) => ({
    label: point.timeIndex,
    actual: point.actual,
    forecast: point.forecast,
  }));

  return (
    <Card className="dataset-detail-visualization dataset-detail-forecasting-evaluation">
      <h3>{FORECAST_VS_ACTUAL_TITLE}</h3>

      <div
        aria-label={FORECAST_VS_ACTUAL_TITLE}
        className="dataset-detail-visualization__chart dataset-detail-forecasting-evaluation__chart-layout"
        data-chart-grid={CHART_GRID}
        data-chart-primary={CHART_PRIMARY}
        data-chart-secondary={CHART_SECONDARY}
      >
        <ul className="dataset-detail-forecasting-evaluation__series-legend">
          <li className="dataset-detail-forecasting-evaluation__series">
            <span
              aria-hidden="true"
              className="dataset-detail-forecasting-evaluation__series-marker dataset-detail-forecasting-evaluation__series-marker--actual"
            />
            Actual
          </li>
          <li className="dataset-detail-forecasting-evaluation__series">
            <span
              aria-hidden="true"
              className="dataset-detail-forecasting-evaluation__series-marker dataset-detail-forecasting-evaluation__series-marker--forecast"
            />
            Forecast
          </li>
        </ul>
        <div className="dataset-detail-forecasting-evaluation__chart">
          <ResponsiveContainer height="100%" width="100%">
            <LineChart data={chartData} margin={{ bottom: 8 }}>
              <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis width={48} />
              <Tooltip
                {...datasetChartTooltipProps(interactionMode, ({ datum }) =>
                  buildForecastVsActualTooltipModel(datum),
                )}
              />
              <Line
                dataKey="actual"
                dot={{ r: 3 }}
                isAnimationActive={false}
                name="Actual"
                stroke={CHART_PRIMARY}
                strokeWidth={2}
                type="monotone"
              />
              <Line
                dataKey="forecast"
                dot={{ r: 3 }}
                isAnimationActive={false}
                name="Forecast"
                stroke={CHART_SECONDARY}
                strokeDasharray="6 4"
                strokeWidth={2}
                type="monotone"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <ul className="dataset-detail-forecasting-evaluation__points forecasting-diagnostics__legend">
          {chartData.map((point) => (
            <li className="forecasting-diagnostics__legend-row" key={point.label}>
              <span className="forecasting-diagnostics__legend-label">{point.label}</span>
              <span className="forecasting-diagnostics__legend-value">
                {`Actual ${formatValue(point.actual)} · Forecast ${formatValue(point.forecast)}`}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

// Project Spec S0248 / S0275: a single shared renderer for the bounded
// univariate-forecasting diagnostic cards -- consumed identically by the
// public Dataset Detail surface and Dataset Admin Live Preview through the
// same DatasetDetailSurface composition, so this component never fetches
// data itself, never recomputes aggregates, and never carries
// dataset-specific branching or copy. Under S0275 it additionally accepts one
// already-projected highlighted forecasting score id and, when the release
// carries an S0274 metric_diagnostics block, renders Backtesting by Origin
// and Horizon from the single governed metric entry that score selects --
// both cards always the same metric, titled with the shared metadata label.
export default function ForecastingDiagnostics({ visualizations, highlightedScoreId }: ForecastingDiagnosticsProps) {
  const interactionMode = useChartInteractionMode();
  const diagnostics = visualizations?.forecasting_diagnostics ?? null;
  const seasonalProfile = getValidSeasonalProfile(diagnostics?.seasonal_profile?.points);

  const selection = resolveMetricSelection(diagnostics, highlightedScoreId);
  const selectedMetric = selection.kind === "selected" ? selection.metric : null;
  const legacyMode = selection.kind === "legacy";

  const legacyFoldMetric = legacyMode
    ? getValidFoldMetric(
        diagnostics?.backtesting_fold_metric?.metric_id,
        diagnostics?.backtesting_fold_metric?.points,
      )
    : null;
  const legacyHorizonMae = legacyMode ? getValidHorizonMae(diagnostics?.horizon_mae?.points) : null;

  // Backtesting by Origin: the selected v7 metric wins; otherwise the legacy
  // backtesting_fold_metric; otherwise a fail-closed empty state. Legacy and
  // selected points share the same { label, value } shape.
  const backtestingTitle = selectedMetric
    ? `Backtesting by Origin — ${selectedMetric.label}`
    : "Backtesting by Origin";
  const backtestingPoints = selectedMetric?.byOrigin ?? legacyFoldMetric?.points ?? null;
  const backtestingSeriesLabel = selectedMetric?.label ?? legacyFoldMetric?.metricId ?? null;

  // Horizon: the selected v7 metric wins; otherwise legacy Horizon MAE
  // (never relabeled); otherwise a fail-closed empty state.
  const horizonTitle = selectedMetric ? `Horizon ${selectedMetric.label}` : "Horizon MAE";
  // The legacy series is MAE and is never relabeled.
  const horizonSeriesLabel = selectedMetric ? selectedMetric.label : "MAE";
  const horizonPoints = selectedMetric
    ? selectedMetric.byHorizon
    : legacyHorizonMae
      ? legacyHorizonMae.points.map((point) => ({ label: point.label, value: point.mae }))
      : null;

  return (
    <>
      <Card className="dataset-detail-visualization dataset-detail-visualization--backtesting-fold-metric">
        <h3>{backtestingTitle}</h3>
        {backtestingPoints && backtestingSeriesLabel ? (
          <div
            aria-label={backtestingTitle.toLowerCase()}
            className="dataset-detail-visualization__chart forecasting-diagnostics__line-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="forecasting-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <LineChart data={backtestingPoints} margin={{ bottom: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis width={40} />
                  <Tooltip
                    {...datasetChartTooltipProps(interactionMode, ({ datum }) =>
                      buildBacktestingTooltipModel(backtestingSeriesLabel, datum),
                    )}
                  />
                  <Line
                    dataKey="value"
                    dot={{ r: 3 }}
                    isAnimationActive={false}
                    stroke={CHART_PRIMARY}
                    strokeWidth={2}
                    type="monotone"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <ul className="forecasting-diagnostics__legend">
              {backtestingPoints.map((point, index) => (
                <li className="forecasting-diagnostics__legend-row" key={`${point.label}-${index}`}>
                  <span className="forecasting-diagnostics__legend-label">{point.label}</span>
                  <span className="forecasting-diagnostics__legend-value">
                    {backtestingSeriesLabel}: {formatValue(point.value)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
        )}
      </Card>

      <Card className="dataset-detail-visualization dataset-detail-visualization--horizon-mae">
        <h3>{horizonTitle}</h3>
        {horizonPoints ? (
          <div
            aria-label={horizonTitle.toLowerCase()}
            className="dataset-detail-visualization__chart forecasting-diagnostics__bar-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="forecasting-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={horizonPoints} margin={{ bottom: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis width={40} />
                  <Tooltip
                    {...datasetChartTooltipProps(interactionMode, ({ datum }) =>
                      buildHorizonTooltipModel(horizonSeriesLabel, datum),
                    )}
                  />
                  <Bar dataKey="value" fill={CHART_SECONDARY} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="forecasting-diagnostics__legend">
              {horizonPoints.map((point) => (
                <li className="forecasting-diagnostics__legend-row" key={point.label}>
                  <span className="forecasting-diagnostics__legend-label">{point.label}</span>
                  <span className="forecasting-diagnostics__legend-value">{formatValue(point.value)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
        )}
      </Card>

      <Card className="dataset-detail-visualization dataset-detail-visualization--seasonal-profile">
        <h3>Seasonal Profile</h3>
        {seasonalProfile ? (
          <div
            aria-label="seasonal profile"
            className="dataset-detail-visualization__chart forecasting-diagnostics__bar-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="forecasting-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={seasonalProfile.points} margin={{ bottom: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis width={40} />
                  <Tooltip
                    {...datasetChartTooltipProps(interactionMode, ({ datum }) =>
                      buildSeasonalProfileTooltipModel(datum),
                    )}
                  />
                  <Bar dataKey="mean_target" fill={CHART_PRIMARY} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="forecasting-diagnostics__legend">
              {seasonalProfile.points.map((point) => (
                <li className="forecasting-diagnostics__legend-row" key={point.label}>
                  <span className="forecasting-diagnostics__legend-label">{point.label}</span>
                  <span className="forecasting-diagnostics__legend-value">{formatValue(point.mean_target)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
        )}
      </Card>
    </>
  );
}
