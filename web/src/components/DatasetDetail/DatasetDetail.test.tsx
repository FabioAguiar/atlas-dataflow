import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DatasetDetailHeader, PerformanceSummary, type DatasetDetailMetadataItem } from ".";

function renderHeader(metadata: DatasetDetailMetadataItem[]) {
  return render(
    <MemoryRouter>
      <DatasetDetailHeader
        analysisType="Classificacao binaria"
        datasetTitle="Synthetic Demo Dataset"
        metadata={metadata}
        subtitle="Synthetic public-safe detail subtitle."
      />
    </MemoryRouter>,
  );
}

describe("DatasetDetailHeader metadata rendering (M39-03)", () => {
  it("shows Pending for Source and Release when curated metadata is unavailable", () => {
    renderHeader([
      { label: "Source", value: null },
      { label: "Instances", value: "1,234" },
      { label: "Features", value: "8" },
      { label: "Target", value: "Synthetic target" },
      { label: "Release", value: null },
    ]);

    const metadataSummary = document.querySelector(".dataset-detail-header__metadata");
    expect(metadataSummary).toHaveAccessibleName("Dataset metadata summary");
    expect(screen.getByRole("heading", { level: 1, name: "Synthetic Demo Dataset" })).toBeInTheDocument();
    expect(screen.getByText("Classificacao binaria")).toBeInTheDocument();
    expect(screen.getAllByText("Pending")).toHaveLength(2);
  });

  it("renders curated Source and Release metadata with the release format hint", () => {
    renderHeader([
      { label: "Source", value: "Original Source Org" },
      { label: "Instances", value: "1,234" },
      { label: "Features", value: "8" },
      { label: "Target", value: "Synthetic target" },
      { label: "Release", value: "01/07/2026", hint: "Format: dd/mm/yyyy" },
    ]);

    expect(screen.getByText("Original Source Org")).toBeInTheDocument();
    expect(screen.getByText("01/07/2026")).toBeInTheDocument();
    expect(screen.getByText("Format: dd/mm/yyyy")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
  });
});

describe("PerformanceSummary curated metric highlight (M39-03)", () => {
  it("highlights the curated primary metric instead of the default score", () => {
    render(
      <PerformanceSummary
        emphasizedMetricKey="precision"
        metrics={{
          auc_roc: 0.87,
          precision: 0.8,
          recall: 0.75,
          f1_score: 0.77,
        }}
      />,
    );

    const precisionScore = screen.getByText("Precision").closest(".performance-summary__score");
    const aucScore = screen.getByText("AUC ROC").closest(".performance-summary__score");

    expect(precisionScore).not.toBeNull();
    expect(aucScore).not.toBeNull();
    expect(within(precisionScore as HTMLElement).getByText("Highlighted")).toBeInTheDocument();
    expect(aucScore).not.toHaveTextContent("Highlighted");
  });
});
