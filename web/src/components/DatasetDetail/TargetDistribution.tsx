import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { Card, EmptyState } from "../ui";

type ChartDataPoint = {
  name: string;
  value: number;
};

export type VisualizationChart = {
  id?: string;
  title?: string;
  type: "bar" | "line";
  x_label?: string;
  y_label?: string;
  data: ChartDataPoint[];
};

export type VisualizationsPayload = {
  charts?: VisualizationChart[];
  // Project Spec S0205: a bounded dataset-population statistic the public
  // visualizations projection may carry alongside charts. TargetDistribution
  // never reads or derives this itself -- it exists here only because this
  // module owns the shared VisualizationsPayload type both DatasetPage.tsx
  // and livePreviewProjection.ts consume.
  dataset_statistics?: {
    instance_count?: number;
  };
  // Project Spec S0215: a bounded normalized multiclass confusion matrix the
  // public visualizations projection may carry alongside charts, present
  // only for a valid multiclass (v2) release. TargetDistribution never reads
  // this itself -- it lives on the shared payload type (independent of the
  // charts array) so ConfusionMatrix.tsx, DatasetPage.tsx, and
  // livePreviewProjection.ts can all consume it without a competing type.
  confusion_matrix?: {
    ordered_class_ids?: string[];
    matrix?: number[][];
    row_axis?: string;
    column_axis?: string;
  };
};

type TargetDistributionProps = {
  visualizations: VisualizationsPayload | null;
};

const TARGET_DISTRIBUTION_ID = "target_distribution";
const TARGET_DISTRIBUTION_TITLE = "target distribution";
const EMPTY_MESSAGE = "This visualization has not been generated yet for this release.";
const CHART_PRIMARY = "var(--dataset-theme-chart-primary)";
const CHART_SECONDARY = "var(--dataset-theme-chart-secondary)";
const CHART_GRID = "var(--dataset-theme-chart-grid)";

// Cycled by category index rather than tied to a fixed category count.
const DONUT_PALETTE = [
  "var(--dataset-theme-accent)",
  "var(--dataset-theme-chart-secondary)",
  "var(--dataset-theme-accent-strong)",
  "var(--dataset-theme-chart-primary)",
  "var(--dataset-theme-chart-grid)",
];

function matchesTargetDistribution(chart: VisualizationChart): boolean {
  if (chart.id === TARGET_DISTRIBUTION_ID) {
    return true;
  }
  return chart.title?.trim().toLowerCase() === TARGET_DISTRIBUTION_TITLE;
}

type ValidDistribution = {
  data: ChartDataPoint[];
  total: number;
};

/**
 * A donut only renders when every category value is a finite, non-negative
 * number and the total is strictly positive -- anything malformed, negative,
 * non-finite, empty or zero-total falls back to the bounded empty state
 * instead of producing NaN/Infinity arcs or fabricated proportions.
 */
function getValidDistribution(chart: VisualizationChart | null): ValidDistribution | null {
  if (!chart?.data?.length) {
    return null;
  }

  let total = 0;
  for (const point of chart.data) {
    if (typeof point.value !== "number" || !Number.isFinite(point.value) || point.value < 0) {
      return null;
    }
    total += point.value;
  }

  return total > 0 ? { data: chart.data, total } : null;
}

function formatPercent(value: number, total: number): string {
  return `${((value / total) * 100).toFixed(1)}%`;
}

export default function TargetDistribution({ visualizations }: TargetDistributionProps) {
  const chart = visualizations?.charts?.find(matchesTargetDistribution) ?? null;
  const distribution = getValidDistribution(chart);

  return (
    <Card className="dataset-detail-visualization dataset-detail-visualization--donut">
      <h3>Target Distribution</h3>
      {distribution ? (
        <div
          className="dataset-detail-visualization__chart target-distribution__layout"
          aria-label={chart!.title ?? "Target Distribution"}
          data-chart-grid={CHART_GRID}
          data-chart-primary={CHART_PRIMARY}
          data-chart-secondary={CHART_SECONDARY}
        >
          <div className="target-distribution__donut">
            <ResponsiveContainer height="100%" width="100%">
              <PieChart>
                <Pie
                  data={distribution.data}
                  dataKey="value"
                  innerRadius="62%"
                  isAnimationActive={false}
                  nameKey="name"
                  outerRadius="100%"
                  paddingAngle={distribution.data.length > 1 ? 2 : 0}
                >
                  {distribution.data.map((point, index) => (
                    <Cell key={point.name} fill={DONUT_PALETTE[index % DONUT_PALETTE.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="target-distribution__legend">
            {distribution.data.map((point, index) => (
              <li className="target-distribution__legend-row" key={point.name}>
                <span
                  aria-hidden="true"
                  className="target-distribution__legend-marker"
                  style={{ background: DONUT_PALETTE[index % DONUT_PALETTE.length] }}
                />
                <span className="target-distribution__legend-label">{point.name}</span>
                <span className="target-distribution__legend-value">
                  {formatPercent(point.value, distribution.total)}
                  <em className="target-distribution__legend-raw">({point.value.toLocaleString()})</em>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
      )}
    </Card>
  );
}
