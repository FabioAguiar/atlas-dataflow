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
