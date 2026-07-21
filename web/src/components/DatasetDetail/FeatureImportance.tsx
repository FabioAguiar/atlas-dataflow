import { Card, EmptyState } from "../ui";
import type { VisualizationChart, VisualizationsPayload } from "./TargetDistribution";

type FeatureImportanceProps = {
  visualizations: VisualizationsPayload | null;
};

type RankedFeatureRow = {
  name: string;
  value: number;
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

function formatFeatureValue(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * Presentation-only ranking: rows are re-sorted by descending magnitude for
 * the visual ranking (stable on ties, by original position), but every
 * label/value shown is still the source artifact's own.
 */
function getRankedFeatureRows(chart: VisualizationChart | null): RankedFeatureRow[] | null {
  if (!chart?.data?.length) {
    return null;
  }

  const finite = chart.data
    .map((point, index) => ({ point, index }))
    .filter(({ point }) => typeof point.value === "number" && Number.isFinite(point.value));

  if (finite.length === 0) {
    return null;
  }

  return finite
    .sort((a, b) => Math.abs(b.point.value) - Math.abs(a.point.value) || a.index - b.index)
    .map(({ point }) => point);
}

export default function FeatureImportance({ visualizations }: FeatureImportanceProps) {
  const chart = visualizations?.charts?.find(matchesFeatureImportance) ?? null;
  const rows = getRankedFeatureRows(chart);
  const maxMagnitude = rows ? Math.max(0, ...rows.map((row) => Math.abs(row.value))) : 0;

  return (
    <Card className="dataset-detail-visualization dataset-detail-visualization--ranked">
      <h3>Feature Importance</h3>
      {rows && rows.length > 0 ? (
        <div
          className="dataset-detail-visualization__chart"
          aria-label={chart!.title ?? "Feature Importance"}
          data-chart-grid={CHART_GRID}
          data-chart-primary={CHART_PRIMARY}
          data-chart-secondary={CHART_SECONDARY}
        >
          <ul className="feature-importance__rows">
            {rows.map((row) => {
              const widthPercent = maxMagnitude > 0 ? (Math.abs(row.value) / maxMagnitude) * 100 : 0;
              return (
                <li
                  aria-label={`${row.name}: ${formatFeatureValue(row.value)}`}
                  className="feature-importance__row"
                  key={row.name}
                >
                  <span aria-hidden="true" className="feature-importance__label">
                    {row.name}
                  </span>
                  <span aria-hidden="true" className="feature-importance__track">
                    <span className="feature-importance__bar" style={{ width: `${widthPercent}%` }} />
                  </span>
                  <span aria-hidden="true" className="feature-importance__value">
                    {formatFeatureValue(row.value)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <EmptyState message={EMPTY_MESSAGE} title="Visualization not generated" />
      )}
    </Card>
  );
}
