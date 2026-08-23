import type { ReactNode } from "react";
import DatasetDetailHeader, { type DatasetDetailMetadataItem } from "./DatasetDetailHeader";
import DatasetDetailTabs from "./DatasetDetailTabs";
import { Card } from "../ui";
import { datasetThemeStyle, resolveDatasetThemePreset } from "../../lib/datasetPresentation";

export type { DatasetDetailMetadataItem };

export type DatasetDetailSurfaceProps = {
  themePresetId?: string | null;
  datasetTitle: string;
  datasetSubtitle?: string;
  analysisType?: string;
  performanceFocusId?: string | null;
  modelDisplayName?: string | null;
  metadata: DatasetDetailMetadataItem[];
  problemSummaryTitle?: string;
  problemSummaryBody?: string | null;
  performanceContent: ReactNode;
  targetDistributionContent: ReactNode;
  featureImportanceContent: ReactNode;
  // Project Spec S0215: an optional, bounded normalized confusion matrix
  // surface, rendered only for a multiclass release -- omitted entirely
  // (never a placeholder) keeps binary Dataset Detail visually unchanged.
  confusionMatrixContent?: ReactNode;
  // Project Spec S0228: an optional, bounded continuous-regression
  // diagnostics section (Actual vs Predicted + Residual Distribution),
  // rendered below the primary analytics grid for a regression release --
  // omitted entirely (never a placeholder) keeps classification Dataset
  // Detail layouts, including S0221's full-width Confusion Matrix, visually
  // unchanged.
  regressionDiagnosticsContent?: ReactNode;
  // Project Spec S0248: an optional, bounded univariate-forecasting
  // diagnostics section (Seasonal Profile + Backtesting by Origin + Horizon
  // MAE), rendered below the primary analytics grid for a forecasting
  // release -- omitted entirely (never a placeholder) keeps classification/
  // regression Dataset Detail layouts visually unchanged. A forecasting
  // release never renders regressionDiagnosticsContent/confusionMatrixContent
  // alongside this, and its own targetDistributionContent/
  // featureImportanceContent are omitted by the caller.
  forecastingDiagnosticsContent?: ReactNode;
  inferenceContent: ReactNode;
  documentationContent?: ReactNode;
};

// Project Spec S0119: the single reusable presentational Dataset Detail
// composition shared today by /dataset/:slug (DatasetPage.tsx) and later by
// Dataset Admin Live Preview (S0120). Every value arrives as a prop -- no
// fetch, route param, or Admin/private-draft access happens here.
export default function DatasetDetailSurface({
  themePresetId,
  datasetTitle,
  datasetSubtitle,
  analysisType,
  performanceFocusId,
  modelDisplayName,
  metadata,
  problemSummaryTitle,
  problemSummaryBody,
  performanceContent,
  targetDistributionContent,
  featureImportanceContent,
  confusionMatrixContent,
  regressionDiagnosticsContent,
  forecastingDiagnosticsContent,
  inferenceContent,
  documentationContent,
}: DatasetDetailSurfaceProps) {
  const resolvedTheme = resolveDatasetThemePreset(themePresetId);

  const overviewContent = (
    <div className="dataset-detail-overview">
      {problemSummaryBody && (
        <Card className="dataset-detail-overview__problem-summary">
          <h3>{problemSummaryTitle?.trim() || "Problem summary"}</h3>
          <p>{problemSummaryBody}</p>
        </Card>
      )}

      <div className="dataset-detail-overview__analytics">
        {performanceContent}
        {targetDistributionContent}
        {featureImportanceContent}
        {confusionMatrixContent}
      </div>

      {regressionDiagnosticsContent && (
        <div className="dataset-detail-overview__regression-diagnostics">{regressionDiagnosticsContent}</div>
      )}

      {forecastingDiagnosticsContent && (
        <div className="dataset-detail-overview__forecasting-diagnostics">{forecastingDiagnosticsContent}</div>
      )}
    </div>
  );

  return (
    <div
      className="dataset-detail-surface dataset-theme-scope"
      data-theme-preset={resolvedTheme.id}
      style={datasetThemeStyle(themePresetId)}
    >
      <DatasetDetailHeader
        analysisType={analysisType}
        datasetTitle={datasetTitle}
        metadata={metadata}
        modelDisplayName={modelDisplayName}
        performanceFocusId={performanceFocusId}
        subtitle={datasetSubtitle}
      />

      <DatasetDetailTabs
        documentationContent={documentationContent}
        inferenceContent={inferenceContent}
        overviewContent={overviewContent}
      />
    </div>
  );
}
