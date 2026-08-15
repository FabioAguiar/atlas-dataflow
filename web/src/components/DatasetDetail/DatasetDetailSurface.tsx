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
  metadata: DatasetDetailMetadataItem[];
  problemSummaryTitle?: string;
  problemSummaryBody?: string | null;
  performanceContent: ReactNode;
  targetDistributionContent: ReactNode;
  featureImportanceContent: ReactNode;
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
  metadata,
  problemSummaryTitle,
  problemSummaryBody,
  performanceContent,
  targetDistributionContent,
  featureImportanceContent,
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
      </div>
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
