import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { Card, EmptyState } from "../ui";
import type { VisualizationsPayload } from "./TargetDistribution";

type ForecastingDiagnosticsProps = {
  visualizations: VisualizationsPayload | null;
};

type RawSeasonalPoint = { season_position?: number; mean_target?: number; observation_count?: number };
type RawFoldPoint = { fold_index?: number; forecast_origin?: string; value?: number };
type RawHorizonPoint = { horizon_step?: number; mae?: number };

type ValidSeasonalProfile = {
  points: Array<{ label: string; mean_target: number }>;
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

function formatCount(value: number): string {
  return value.toLocaleString();
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
  const validated: Array<{ label: string; mean_target: number }> = [];
  for (const point of points) {
    const { season_position: position, mean_target: meanTarget } = point;
    if (
      typeof position !== "number" ||
      !Number.isInteger(position) ||
      position < 0 ||
      typeof meanTarget !== "number" ||
      !Number.isFinite(meanTarget)
    ) {
      return null;
    }
    validated.push({ label: `Position ${position}`, mean_target: meanTarget });
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

const EVALUATION_TITLE = "Forecast Evaluation Overview";
const FORECAST_VS_ACTUAL_TITLE = "Forecast vs Actual — Final Holdout";
const EVALUATION_UNAVAILABLE_MESSAGE =
  "This release does not carry a complete governed final-holdout forecast evaluation.";
const EVALUATION_FROZEN_COPY =
  "The evaluated model was frozen before the final holdout was opened. Its forecast for that holdout was generated before the observed targets were revealed.";

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
  const rawEvaluation = visualizations?.forecasting_evaluation;
  if (rawEvaluation === undefined || rawEvaluation === null) {
    return null;
  }

  const evaluation = getValidForecastingEvaluation(visualizations);
  if (!evaluation) {
    return (
      <Card className="dataset-detail-visualization dataset-detail-forecasting-evaluation dataset-detail-forecasting-evaluation--unavailable">
        <h3>{EVALUATION_TITLE}</h3>
        <EmptyState message={EVALUATION_UNAVAILABLE_MESSAGE} title="Evaluation unavailable" />
      </Card>
    );
  }

  const { development, finalHoldout, frequency, forecastHorizon, points } = evaluation;
  const chartData = points.map((point) => ({
    label: point.timeIndex,
    actual: point.actual,
    forecast: point.forecast,
  }));
  const holdoutCountLabel =
    forecastHorizon !== null ? "Final holdout observations / forecast horizon" : "Final holdout observations";
  const developmentRange = `${development.startIndex} → ${development.endIndex}`;
  const finalHoldoutRange = `${finalHoldout.startIndex} → ${finalHoldout.endIndex}`;

  return (
    <Card className="dataset-detail-visualization dataset-detail-forecasting-evaluation">
      <h3>{EVALUATION_TITLE}</h3>

      <p className="dataset-detail-forecasting-evaluation__statement">{EVALUATION_FROZEN_COPY}</p>

      <dl className="dataset-detail-forecasting-evaluation__context">
        <div className="dataset-detail-forecasting-evaluation__context-row">
          <dt>Development / training evidence range</dt>
          <dd>{developmentRange}</dd>
        </div>
        <div className="dataset-detail-forecasting-evaluation__context-row">
          <dt>Development observations</dt>
          <dd>{formatCount(development.observationCount)}</dd>
        </div>
        <div className="dataset-detail-forecasting-evaluation__context-row">
          <dt>Final holdout range</dt>
          <dd>{finalHoldoutRange}</dd>
        </div>
        <div className="dataset-detail-forecasting-evaluation__context-row">
          <dt>{holdoutCountLabel}</dt>
          <dd>{formatCount(finalHoldout.observationCount)}</dd>
        </div>
        <div className="dataset-detail-forecasting-evaluation__context-row">
          <dt>Frequency</dt>
          <dd>{frequency}</dd>
        </div>
      </dl>

      <div
        aria-label={`Development and training evidence from ${development.startIndex} to ${development.endIndex} (${development.observationCount} observations), then the sealed final holdout from ${finalHoldout.startIndex} to ${finalHoldout.endIndex} (${finalHoldout.observationCount} observations).`}
        className="dataset-detail-forecasting-evaluation__boundary"
        role="img"
      >
        <div className="dataset-detail-forecasting-evaluation__boundary-segment dataset-detail-forecasting-evaluation__boundary-segment--development">
          <span className="dataset-detail-forecasting-evaluation__boundary-title">Development / training evidence</span>
          <span className="dataset-detail-forecasting-evaluation__boundary-range">{developmentRange}</span>
          <span className="dataset-detail-forecasting-evaluation__boundary-count">
            {formatCount(development.observationCount)} observations
          </span>
        </div>
        <div className="dataset-detail-forecasting-evaluation__boundary-segment dataset-detail-forecasting-evaluation__boundary-segment--final-holdout">
          <span className="dataset-detail-forecasting-evaluation__boundary-title">Final holdout</span>
          <span className="dataset-detail-forecasting-evaluation__boundary-range">{finalHoldoutRange}</span>
          <span className="dataset-detail-forecasting-evaluation__boundary-count">
            {formatCount(finalHoldout.observationCount)} observations
          </span>
        </div>
      </div>

      <h4 className="dataset-detail-forecasting-evaluation__chart-title">{FORECAST_VS_ACTUAL_TITLE}</h4>
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

// Project Spec S0248: a single shared renderer for the three bounded
// univariate-forecasting diagnostic cards -- consumed identically by the
// public Dataset Detail surface and Dataset Admin Live Preview through the
// same DatasetDetailSurface composition, so this component never fetches
// data itself, never recomputes aggregates, and never carries
// dataset-specific branching or copy.
export default function ForecastingDiagnostics({ visualizations }: ForecastingDiagnosticsProps) {
  const diagnostics = visualizations?.forecasting_diagnostics ?? null;
  const seasonalProfile = getValidSeasonalProfile(diagnostics?.seasonal_profile?.points);
  const foldMetric = getValidFoldMetric(
    diagnostics?.backtesting_fold_metric?.metric_id,
    diagnostics?.backtesting_fold_metric?.points,
  );
  const horizonMae = getValidHorizonMae(diagnostics?.horizon_mae?.points);

  return (
    <>
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

      <Card className="dataset-detail-visualization dataset-detail-visualization--backtesting-fold-metric">
        <h3>Backtesting by Origin</h3>
        {foldMetric ? (
          <div
            aria-label="backtesting by origin"
            className="dataset-detail-visualization__chart forecasting-diagnostics__line-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="forecasting-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <LineChart data={foldMetric.points} margin={{ bottom: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis width={40} />
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
              {foldMetric.points.map((point, index) => (
                <li className="forecasting-diagnostics__legend-row" key={`${point.label}-${index}`}>
                  <span className="forecasting-diagnostics__legend-label">{point.label}</span>
                  <span className="forecasting-diagnostics__legend-value">
                    {foldMetric.metricId}: {formatValue(point.value)}
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
        <h3>Horizon MAE</h3>
        {horizonMae ? (
          <div
            aria-label="horizon mae"
            className="dataset-detail-visualization__chart forecasting-diagnostics__bar-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="forecasting-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={horizonMae.points} margin={{ bottom: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis width={40} />
                  <Bar dataKey="mae" fill={CHART_SECONDARY} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="forecasting-diagnostics__legend">
              {horizonMae.points.map((point) => (
                <li className="forecasting-diagnostics__legend-row" key={point.label}>
                  <span className="forecasting-diagnostics__legend-label">{point.label}</span>
                  <span className="forecasting-diagnostics__legend-value">{formatValue(point.mae)}</span>
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
