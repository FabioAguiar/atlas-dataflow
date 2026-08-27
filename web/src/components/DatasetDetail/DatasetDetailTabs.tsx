import { useEffect, useState, type ReactNode } from "react";
import { Tabs } from "../ui";
import type { TabItem } from "../ui";

const OVERVIEW_TAB: TabItem = { id: "overview", label: "Overview" };
const INFERENCE_TAB: TabItem = { id: "inference", label: "Inference" };
const DOCUMENTATION_TAB: TabItem = { id: "documentation", label: "Documentation" };

type DatasetDetailTabsProps = {
  overviewContent: ReactNode;
  inferenceContent: ReactNode;
  documentationContent?: ReactNode;
  // Project Spec S0271: whether the shared surface exposes the Inference tab.
  // Defaults to the historical behavior (true) so every existing caller and
  // test stays source-compatible unless it intentionally opts out. When
  // false the Inference tab is omitted and its tabpanel is never mounted --
  // Overview/Documentation are unaffected.
  inferenceAvailable?: boolean;
};

export default function DatasetDetailTabs({
  overviewContent,
  inferenceContent,
  documentationContent,
  inferenceAvailable = true,
}: DatasetDetailTabsProps) {
  const [selectedId, setSelectedId] = useState<string>("overview");

  // Project Spec S0271: the public contract can resolve to not_applicable
  // after the user has already selected Inference (the surface renders before
  // the contract request settles). Reset deterministically to Overview so no
  // hidden orphan Inference panel remains and the selected tab always exists.
  useEffect(() => {
    if (!inferenceAvailable && selectedId === "inference") {
      setSelectedId("overview");
    }
  }, [inferenceAvailable, selectedId]);

  const effectiveSelectedId =
    !inferenceAvailable && selectedId === "inference" ? "overview" : selectedId;

  const tabItems: TabItem[] = inferenceAvailable
    ? [OVERVIEW_TAB, INFERENCE_TAB, DOCUMENTATION_TAB]
    : [OVERVIEW_TAB, DOCUMENTATION_TAB];

  return (
    <div className="dataset-detail-tabs">
      <Tabs
        ariaLabel="Dataset detail sections"
        items={tabItems}
        onSelect={setSelectedId}
        selectedId={effectiveSelectedId}
      />

      <div className="dataset-detail-tabs__panel" hidden={effectiveSelectedId !== "overview"} role="tabpanel">
        {overviewContent}
      </div>

      {inferenceAvailable && (
        <div className="dataset-detail-tabs__panel" hidden={effectiveSelectedId !== "inference"} role="tabpanel">
          {inferenceContent}
        </div>
      )}

      <div className="dataset-detail-tabs__panel" hidden={effectiveSelectedId !== "documentation"} role="tabpanel">
        {documentationContent ?? null}
      </div>
    </div>
  );
}
