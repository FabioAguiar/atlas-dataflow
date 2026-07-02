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
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey="value" fill="#4f46e5" />
      </BarChart>
    );
  }

  return (
    <LineChart data={chart.data}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="name" />
      <YAxis />
      <Tooltip />
      <Line type="monotone" dataKey="value" stroke="#4f46e5" dot={false} />
    </LineChart>
  );
}

export default function FeatureImportance({ visualizations }: FeatureImportanceProps) {
  const chart = visualizations?.charts?.find(matchesFeatureImportance) ?? null;

  return (
    <Card className="dataset-detail-visualization">
      <h3>Feature Importance</h3>
      {chart ? (
        <div className="dataset-detail-visualization__chart" aria-label={chart.title ?? "Feature Importance"}>
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
