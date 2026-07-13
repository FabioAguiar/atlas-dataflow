import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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

function matchesTargetDistribution(chart: VisualizationChart): boolean {
  if (chart.id === TARGET_DISTRIBUTION_ID) {
    return true;
  }
  return chart.title?.trim().toLowerCase() === TARGET_DISTRIBUTION_TITLE;
}

function renderChart(chart: VisualizationChart) {
  if (chart.type === "bar") {
    return (
      <BarChart data={chart.data}>
        <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
        <XAxis dataKey="name" stroke={CHART_GRID} tick={{ fill: CHART_SECONDARY }} />
        <YAxis stroke={CHART_GRID} tick={{ fill: CHART_SECONDARY }} />
        <Tooltip contentStyle={{ background: "var(--dataset-theme-surface)", borderColor: CHART_GRID, color: "var(--dataset-theme-text)" }} />
        <Bar dataKey="value" fill={CHART_PRIMARY} />
      </BarChart>
    );
  }

  return (
    <LineChart data={chart.data}>
      <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
      <XAxis dataKey="name" stroke={CHART_GRID} tick={{ fill: CHART_SECONDARY }} />
      <YAxis stroke={CHART_GRID} tick={{ fill: CHART_SECONDARY }} />
      <Tooltip contentStyle={{ background: "var(--dataset-theme-surface)", borderColor: CHART_GRID, color: "var(--dataset-theme-text)" }} />
      <Line type="monotone" dataKey="value" stroke={CHART_PRIMARY} dot={{ fill: CHART_SECONDARY }} />
    </LineChart>
  );
}

export default function TargetDistribution({ visualizations }: TargetDistributionProps) {
  const chart = visualizations?.charts?.find(matchesTargetDistribution) ?? null;

  return (
    <Card className="dataset-detail-visualization">
      <h3>Target Distribution</h3>
      {chart ? (
        <div
          className="dataset-detail-visualization__chart"
          aria-label={chart.title ?? "Target Distribution"}
          data-chart-grid={CHART_GRID}
          data-chart-primary={CHART_PRIMARY}
          data-chart-secondary={CHART_SECONDARY}
        >
          <ResponsiveContainer width="100%" height={300}>
            {renderChart(chart)}
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyState title="Visualization not generated" message={EMPTY_MESSAGE} />
      )}
    </Card>
  );
}
