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
import type { VisualizationChart, VisualizationsPayload } from "./TargetDistribution";

type FeatureImportanceProps = {
  visualizations: VisualizationsPayload | null;
};

const FEATURE_IMPORTANCE_ID = "feature_importance";
const FEATURE_IMPORTANCE_TITLE = "feature importance";
const EMPTY_MESSAGE = "This visualization has not been generated yet for this release.";
const CHART_PRIMARY = "var(--dataset-theme-chart-primary)";
const CHART_SECONDARY = "var(--dataset-theme-chart-secondary)";
const CHART_GRID = "var(--dataset-theme-chart-grid)";

function matchesFeatureImportance(chart: VisualizationChart): boolean {
  if (chart.id === FEATURE_IMPORTANCE_ID) {
    return true;
  }
  return chart.title?.trim().toLowerCase() === FEATURE_IMPORTANCE_TITLE;
}

function renderChart(chart: VisualizationChart) {
  if (chart.type === "bar") {
    return (
      <BarChart data={chart.data}>
        <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
        <XAxis dataKey="name" stroke={CHART_GRID} tick={{ fill: CHART_PRIMARY }} />
        <YAxis stroke={CHART_GRID} tick={{ fill: CHART_PRIMARY }} />
        <Tooltip contentStyle={{ background: "var(--dataset-theme-surface)", borderColor: CHART_GRID, color: "var(--dataset-theme-text)" }} />
        <Bar dataKey="value" fill={CHART_SECONDARY} />
      </BarChart>
    );
  }

  return (
    <LineChart data={chart.data}>
      <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
      <XAxis dataKey="name" stroke={CHART_GRID} tick={{ fill: CHART_PRIMARY }} />
      <YAxis stroke={CHART_GRID} tick={{ fill: CHART_PRIMARY }} />
      <Tooltip contentStyle={{ background: "var(--dataset-theme-surface)", borderColor: CHART_GRID, color: "var(--dataset-theme-text)" }} />
      <Line type="monotone" dataKey="value" stroke={CHART_SECONDARY} dot={{ fill: CHART_PRIMARY }} />
    </LineChart>
  );
}

export default function FeatureImportance({ visualizations }: FeatureImportanceProps) {
  const chart = visualizations?.charts?.find(matchesFeatureImportance) ?? null;

  return (
    <Card className="dataset-detail-visualization">
      <h3>Feature Importance</h3>
      {chart ? (
        <div
          className="dataset-detail-visualization__chart"
          aria-label={chart.title ?? "Feature Importance"}
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
