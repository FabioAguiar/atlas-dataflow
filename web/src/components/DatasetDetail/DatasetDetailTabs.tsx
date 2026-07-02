import { useState, type ReactNode } from "react";
import { Tabs } from "../ui";
import type { TabItem } from "../ui";

const TAB_ITEMS: TabItem[] = [
  { id: "overview", label: "Overview" },
  { id: "inference", label: "Inference" },
  { id: "documentation", label: "Documentation" },
];

type DatasetDetailTabsProps = {
  inferenceContent: ReactNode;
};

export default function DatasetDetailTabs({ inferenceContent }: DatasetDetailTabsProps) {
  const [selectedId, setSelectedId] = useState<string>("overview");

  return (
    <div className="dataset-detail-tabs">
      <Tabs
        ariaLabel="Dataset detail sections"
        items={TAB_ITEMS}
        onSelect={setSelectedId}
        selectedId={selectedId}
      />

      <div className="dataset-detail-tabs__panel" hidden={selectedId !== "overview"} role="tabpanel">
        <p className="dataset-detail-tabs__placeholder">Overview content is coming soon.</p>
      </div>

      <div className="dataset-detail-tabs__panel" hidden={selectedId !== "inference"} role="tabpanel">
        {inferenceContent}
      </div>

      <div className="dataset-detail-tabs__panel" hidden={selectedId !== "documentation"} role="tabpanel" />
    </div>
  );
}
