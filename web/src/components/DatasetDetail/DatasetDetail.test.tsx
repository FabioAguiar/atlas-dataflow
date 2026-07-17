import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DatasetDetailHeader, DatasetDetailTabs, PerformanceSummary, type DatasetDetailMetadataItem } from ".";
import FeatureImportance from "./FeatureImportance";
import TargetDistribution from "./TargetDistribution";
import { presentDatasetDateOnly, safePublicSourceUrl } from "../../lib/datasetPresentation";

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

  it("renders an approved source URL as a safely isolated link", () => {
    renderHeader([
      { label: "Source", value: "Example Org", href: "https://example.org/data" },
      { label: "Release", value: null },
    ]);

    expect(screen.getByRole("link", { name: "Example Org" })).toHaveAttribute("href", "https://example.org/data");
    expect(screen.getByRole("link", { name: "Example Org" })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Example Org" })).toHaveAttribute("rel", "noreferrer noopener");
  });
});

describe("Dataset Detail bounded presentation helpers (S0118)", () => {
  it.each([
    ["dd/mm/yyyy", "12/07/2026"],
    ["mm/dd/yyyy", "07/12/2026"],
    ["yyyy-mm-dd", "2026-07-12"],
    [null, "12/07/2026"],
  ] as const)("formats canonical date-only content as %s", (format, expected) => {
    expect(presentDatasetDateOnly("2026-07-12", format)?.value).toBe(expected);
  });

  it("validates date-only calendar values, including leap days", () => {
    expect(presentDatasetDateOnly("2024-02-29", "dd/mm/yyyy")?.value).toBe("29/02/2024");
    for (const value of ["2026-02-30", "2026-13-01", "not-a-date", ""]) {
      expect(presentDatasetDateOnly(value, "dd/mm/yyyy")).toBeNull();
    }
  });

  it.each([
    ["https://example.org/data", "https://example.org/data"],
    ["http://example.org/data", "http://example.org/data"],
    ["javascript:alert(1)", null],
    ["data:text/plain,bad", null],
    ["file:///tmp/data", null],
    ["/relative", null],
    ["not a url", null],
  ])("bounds public source URL %s", (value, expected) => {
    expect(safePublicSourceUrl(value)).toBe(expected);
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

describe("DatasetDetailTabs tab switching (M42-04)", () => {
  it("updates selected tab state and visible panel content", () => {
    render(
      <DatasetDetailTabs
        overviewContent={<div>Overview panel content</div>}
        inferenceContent={<div>Inference panel content</div>}
      />,
    );

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const inferenceTab = screen.getByRole("tab", { name: "Inference" });
    const overviewPanel = screen.getByText("Overview panel content").closest('[role="tabpanel"]');
    const inferencePanel = screen.getByText("Inference panel content").closest('[role="tabpanel"]');

    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    expect(inferenceTab).toHaveAttribute("aria-selected", "false");
    expect(overviewPanel).not.toHaveAttribute("hidden");
    expect(inferencePanel).toHaveAttribute("hidden");

    fireEvent.click(inferenceTab);

    expect(overviewTab).toHaveAttribute("aria-selected", "false");
    expect(inferenceTab).toHaveAttribute("aria-selected", "true");
    expect(overviewPanel).toHaveAttribute("hidden");
    expect(inferencePanel).not.toHaveAttribute("hidden");
  });
});

describe("Dataset Detail semantic chart colors", () => {
  it("passes scoped primary, secondary, and grid variables to both active chart surfaces", () => {
    const visualizations = {
      charts: [
        { id: "target_distribution", type: "bar" as const, data: [{ name: "No", value: 10 }] },
        { id: "feature_importance", type: "line" as const, data: [{ name: "tenure", value: 0.7 }] },
      ],
    };

    render(
      <>
        <TargetDistribution visualizations={visualizations} />
        <FeatureImportance visualizations={visualizations} />
      </>,
    );

    for (const name of ["Target Distribution", "Feature Importance"]) {
      const chart = screen.getByLabelText(name);
      expect(chart).toHaveAttribute("data-chart-primary", "var(--dataset-theme-chart-primary)");
      expect(chart).toHaveAttribute("data-chart-secondary", "var(--dataset-theme-chart-secondary)");
      expect(chart).toHaveAttribute("data-chart-grid", "var(--dataset-theme-chart-grid)");
    }
  });
});
