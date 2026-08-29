import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, EmptyState } from "../ui";
import {
  datasetChartTooltipProps,
  formatTooltipCount,
  useChartInteractionMode,
  type ChartTooltipContext,
  type DatasetChartTooltipModel,
} from "./DatasetChartTooltip";
import type { VisualizationsPayload } from "./TargetDistribution";

type RegressionDiagnosticsProps = {
  visualizations: VisualizationsPayload | null;
};

type RawPoint = { actual_mean?: number; predicted_mean?: number; count?: number };
type RawBin = { label?: string; count?: number };

type ValidActualVsPredicted = {
  points: Array<{ actual: number; predicted: number; count: number }>;
  domainMin: number;
  domainMax: number;
};

type ValidResidualDistribution = {
  bins: Array<{ label: string; count: number }>;
};

const EMPTY_MESSAGE = "This visualization has not been generated yet for this release.";
const CHART_PRIMARY = "var(--dataset-theme-chart-primary)";
const CHART_SECONDARY = "var(--dataset-theme-chart-secondary)";
const CHART_GRID = "var(--dataset-theme-chart-grid)";

function formatValue(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * Project Spec S0277: bounded tooltip content for the active Actual vs
 * Predicted scatter observation. It scans the active payload for the entry
 * that carries an aggregate `count` -- the identity reference line datum
 * carries none, so it never produces a misleading "observation" tooltip. Only
 * the already-validated actual/predicted/count presentation points are shown;
 * no new statistic is computed.
 */
export function buildActualVsPredictedTooltipModel(
  context: Pick<ChartTooltipContext, "datum" | "items">,
): DatasetChartTooltipModel | null {
  const candidates: unknown[] = [context.datum, ...context.items.map((item) => item.payload)];
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") {
      continue;
    }
    const row = candidate as Record<string, unknown>;
    const actual = typeof row.actual === "number" && Number.isFinite(row.actual) ? row.actual : null;
    const predicted = typeof row.predicted === "number" && Number.isFinite(row.predicted) ? row.predicted : null;
    const count = typeof row.count === "number" && Number.isInteger(row.count) && row.count >= 1 ? row.count : null;
    if (actual === null || predicted === null || count === null) {
      continue;
    }
    return {
      title: "Observation",
      rows: [
        { label: "Actual", value: formatValue(actual) },
        { label: "Predicted", value: formatValue(predicted) },
        { label: "Observations", value: formatTooltipCount(count) },
      ],
    };
  }
  return null;
}

/**
 * Project Spec S0277: bounded tooltip content for the active Residual
 * Distribution bar -- the already-validated bin label and its count only. No
 * residual statistic is recalculated.
 */
export function buildResidualTooltipModel(
  datum: Record<string, unknown>,
): DatasetChartTooltipModel | null {
  const label = typeof datum.label === "string" && datum.label ? datum.label : null;
  const count =
    typeof datum.count === "number" && Number.isInteger(datum.count) && datum.count >= 0 ? datum.count : null;
  if (label === null || count === null) {
    return null;
  }
  return {
    title: "Residual bin",
    rows: [
      { label: "Residual bin", value: label },
      { label: "Count", value: formatTooltipCount(count) },
    ],
  };
}

/**
 * Actual vs Predicted only renders when every aggregate point carries
 * finite actual_mean/predicted_mean values and a strictly positive integer
 * count -- anything malformed degrades to the bounded empty state instead
 * of a misleading or fabricated scatter. This never derives points from raw
 * predictions -- it only re-validates the already-bounded projection.
 */
function getValidActualVsPredicted(points: RawPoint[] | undefined): ValidActualVsPredicted | null {
  if (!points || points.length === 0) {
    return null;
  }

  const validated: Array<{ actual: number; predicted: number; count: number }> = [];
  for (const point of points) {
    const { actual_mean: actual, predicted_mean: predicted, count } = point;
    if (
      typeof actual !== "number" ||
      !Number.isFinite(actual) ||
      typeof predicted !== "number" ||
      !Number.isFinite(predicted) ||
      typeof count !== "number" ||
      !Number.isInteger(count) ||
      count < 1
    ) {
      return null;
    }
    validated.push({ actual, predicted, count });
  }

  const values = validated.flatMap((point) => [point.actual, point.predicted]);
  return { points: validated, domainMin: Math.min(...values), domainMax: Math.max(...values) };
}

/**
 * Residual Distribution only renders when every bin carries a non-empty
 * label and a finite non-negative integer count -- anything malformed
 * degrades to the bounded empty state instead of a misleading histogram.
 */
function getValidResidualDistribution(bins: RawBin[] | undefined): ValidResidualDistribution | null {
  if (!bins || bins.length === 0) {
    return null;
  }

  const validated: Array<{ label: string; count: number }> = [];
  for (const bin of bins) {
    const { label, count } = bin;
    if (typeof label !== "string" || !label || typeof count !== "number" || !Number.isInteger(count) || count < 0) {
      return null;
    }
    validated.push({ label, count });
  }
  return { bins: validated };
}

// Project Spec S0228: a single shared renderer for the two bounded
// continuous-regression diagnostic cards -- consumed identically by the
// public Dataset Detail surface and Dataset Admin Live Preview through the
// same DatasetDetailSurface composition, so this component never fetches
// data itself and never carries dataset-specific branching or copy.
export default function RegressionDiagnostics({ visualizations }: RegressionDiagnosticsProps) {
  const diagnostics = visualizations?.regression_diagnostics ?? null;
  const actualVsPredicted = getValidActualVsPredicted(diagnostics?.actual_vs_predicted?.points);
  const residualDistribution = getValidResidualDistribution(diagnostics?.residual_distribution?.bins);
  const interactionMode = useChartInteractionMode();

  const identityLine = actualVsPredicted
    ? [
        { actual: actualVsPredicted.domainMin, predicted: actualVsPredicted.domainMin },
        { actual: actualVsPredicted.domainMax, predicted: actualVsPredicted.domainMax },
      ]
    : [];

  return (
    <>
      <Card className="dataset-detail-visualization dataset-detail-visualization--actual-vs-predicted">
        <h3>Actual vs Predicted</h3>
        {actualVsPredicted ? (
          <div
            aria-label="actual vs predicted"
            className="dataset-detail-visualization__chart regression-diagnostics__scatter-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="regression-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <ComposedChart margin={{ bottom: 8, left: 0, right: 16, top: 8 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
                  <XAxis
                    dataKey="actual"
                    domain={[actualVsPredicted.domainMin, actualVsPredicted.domainMax]}
                    name="Actual"
                    type="number"
                  />
                  <YAxis
                    dataKey="predicted"
                    domain={[actualVsPredicted.domainMin, actualVsPredicted.domainMax]}
                    name="Predicted"
                    type="number"
                  />
                  <Line
                    data={identityLine}
                    dataKey="predicted"
                    dot={false}
                    isAnimationActive={false}
                    legendType="none"
                    stroke={CHART_SECONDARY}
                    strokeDasharray="4 4"
                  />
                  <Tooltip
                    {...datasetChartTooltipProps(interactionMode, (context) =>
                      buildActualVsPredictedTooltipModel(context),
                    )}
                  />
                  <Scatter data={actualVsPredicted.points} dataKey="predicted" fill={CHART_PRIMARY} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <ul className="regression-diagnostics__legend">
              {actualVsPredicted.points.map((point, index) => (
                <li className="regression-diagnostics__legend-row" key={`${point.actual}-${point.predicted}-${index}`}>
                  <span className="regression-diagnostics__legend-label">
                    Actual {formatValue(point.actual)} vs Predicted {formatValue(point.predicted)}
                  </span>
                  <span className="regression-diagnostics__legend-value">n={point.count.toLocaleString()}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
        )}
      </Card>

      <Card className="dataset-detail-visualization dataset-detail-visualization--residual-distribution">
        <h3>Residual Distribution</h3>
        {residualDistribution ? (
          <div
            aria-label="residual distribution"
            className="dataset-detail-visualization__chart regression-diagnostics__bar-layout"
            data-chart-grid={CHART_GRID}
            data-chart-primary={CHART_PRIMARY}
            data-chart-secondary={CHART_SECONDARY}
          >
            <div className="regression-diagnostics__chart">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={residualDistribution.bins} margin={{ bottom: 24 }}>
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis angle={-30} dataKey="label" height={48} interval={0} textAnchor="end" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} width={40} />
                  <Tooltip
                    {...datasetChartTooltipProps(interactionMode, ({ datum }) => buildResidualTooltipModel(datum))}
                  />
                  <Bar dataKey="count" fill={CHART_PRIMARY} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="regression-diagnostics__legend">
              {residualDistribution.bins.map((bin) => (
                <li className="regression-diagnostics__legend-row" key={bin.label}>
                  <span className="regression-diagnostics__legend-label">{bin.label}</span>
                  <span className="regression-diagnostics__legend-value">{bin.count.toLocaleString()}</span>
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
