import "@testing-library/jest-dom/vitest";
import type { ComponentProps } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import {
  DatasetDetailHeader,
  DatasetDetailSurface,
  DatasetDetailTabs,
  PerformanceSummary,
  type DatasetDetailMetadataItem,
} from ".";
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

// Project Spec S0119: DatasetDetailSurface is the pure shared presentational
// composition reused today by DatasetPage.tsx and later (S0120) by Dataset
// Admin Live Preview. These tests exercise it directly, with synthetic
// content -- never fixed Telco values -- passed entirely via props.
describe("DatasetDetailSurface shared composition (S0119)", () => {
  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: "Example Org", href: "https://example.org/data" },
    { label: "Instances", value: "500" },
    { label: "Features", value: "4" },
    { label: "Target", value: "Synthetic target" },
    { label: "Release", value: "01/07/2026", hint: "Format: dd/mm/yyyy" },
  ];

  function renderSurface(overrides: Partial<ComponentProps<typeof DatasetDetailSurface>> = {}) {
    return render(
      <MemoryRouter>
        <DatasetDetailSurface
          analysisType="Binary Classification"
          datasetSubtitle="Synthetic surface subtitle"
          datasetTitle="Synthetic Surface Dataset"
          featureImportanceContent={<div data-testid="feature-importance-slot">Feature importance content</div>}
          inferenceContent={<div data-testid="inference-slot">Inference content</div>}
          metadata={metadata}
          performanceContent={<div data-testid="performance-slot">Performance content</div>}
          problemSummaryBody="Synthetic problem summary body."
          problemSummaryTitle="Problem summary"
          themePresetId="ocean-blue"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("renders exactly one header and applies the selected theme identity/style at a stable root class", () => {
    const { container } = renderSurface();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const root = container.querySelector(".dataset-detail-surface");
    expect(root).toBeInTheDocument();
    expect(root).toHaveAttribute("data-theme-preset", "ocean-blue");
    expect((root as HTMLElement).style.getPropertyValue("--dataset-theme-accent")).toBe("#2563eb");
  });

  it("renders exactly three tabs labeled Overview, Inference and Documentation", () => {
    renderSurface();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Overview", "Inference", "Documentation"]);
  });

  it("defaults the Documentation panel to blank", () => {
    renderSurface();
    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("");
  });

  it("renders provided Documentation content only inside its own panel", () => {
    renderSurface({ documentationContent: <p>Extra guidance</p> });
    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
    const documentationPanel = screen.getByRole("tabpanel");
    expect(documentationPanel).toHaveTextContent("Extra guidance");
    expect(documentationPanel).not.toHaveTextContent("Synthetic problem summary body.");
  });

  it("renders the problem-summary slot before the analytical slots, each exactly once", () => {
    renderSurface();

    expect(screen.getAllByTestId("performance-slot")).toHaveLength(1);
    expect(screen.getAllByTestId("feature-importance-slot")).toHaveLength(1);

    const problemSummary = screen.getByText("Synthetic problem summary body.");
    const performanceSlot = screen.getByTestId("performance-slot");
    expect(
      problemSummary.compareDocumentPosition(performanceSlot) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("switches tabs and preserves accessible panel visibility", () => {
    renderSurface();
    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const inferenceTab = screen.getByRole("tab", { name: "Inference" });

    expect(overviewTab).toHaveAttribute("aria-selected", "true");

    fireEvent.click(inferenceTab);

    expect(inferenceTab).toHaveAttribute("aria-selected", "true");
    expect(overviewTab).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("inference-slot").closest('[role="tabpanel"]')).not.toHaveAttribute("hidden");
  });

  it("still renders safe metadata links and date hints", () => {
    renderSurface();
    expect(screen.getByRole("link", { name: "Example Org" })).toHaveAttribute(
      "href",
      "https://example.org/data",
    );
    expect(screen.getByText("Format: dd/mm/yyyy")).toBeInTheDocument();
  });
});

// Project Spec S0136: the shared surface's public presentation contract no
// longer carries a Target Distribution slot, and each tab's visible
// tabpanel owns exactly its authorized cards -- never a fourth Overview
// card, an Inference-owned surface leaking into Overview, or the reverse.
// Every assertion below is scoped to screen.getByRole("tabpanel"), which
// testing-library resolves to the one panel currently lacking `hidden` --
// never a raw whole-container query that would also see the other two
// tabs' mounted-but-hidden content.
describe("DatasetDetailSurface exact tab card ownership (S0136)", () => {
  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: "Example Org", href: "https://example.org/data" },
    { label: "Instances", value: "500" },
    { label: "Features", value: "4" },
    { label: "Target", value: "Synthetic target" },
    { label: "Release", value: "01/07/2026", hint: "Format: dd/mm/yyyy" },
  ];

  const readyVisualizations = {
    charts: [{ id: "feature_importance", type: "bar" as const, data: [{ name: "tenure", value: 0.7 }] }],
  };

  function renderReadySurface(overrides: Partial<ComponentProps<typeof DatasetDetailSurface>> = {}) {
    return render(
      <MemoryRouter>
        <DatasetDetailSurface
          analysisType="Binary Classification"
          datasetSubtitle="Synthetic surface subtitle"
          datasetTitle="Synthetic Surface Dataset"
          featureImportanceContent={<FeatureImportance visualizations={readyVisualizations} />}
          inferenceContent={
            <>
              <div className="public-inference-surface__form-panel public-inference-form">Form</div>
              <div className="inference-result">Result</div>
            </>
          }
          metadata={metadata}
          performanceContent={<PerformanceSummary metrics={{ auc_roc: 0.87 }} />}
          problemSummaryBody="Synthetic problem summary body."
          problemSummaryTitle="Problem summary"
          themePresetId="ocean-blue"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("Overview exposes exactly the three authorized cards and no Inference surface", () => {
    renderReadySurface();

    const panel = screen.getByRole("tabpanel");
    const cards = panel.querySelectorAll(".atlas-card");
    expect(cards).toHaveLength(3);
    expect(panel.querySelector(".atlas-card.dataset-detail-overview__problem-summary")).toBeInTheDocument();
    expect(panel.querySelector(".atlas-card.performance-summary")).toBeInTheDocument();
    expect(
      panel.querySelector(".atlas-card.dataset-detail-visualization.dataset-detail-visualization--ranked"),
    ).toBeInTheDocument();

    expect(
      panel.querySelector(".dataset-detail-visualization:not(.dataset-detail-visualization--ranked)"),
    ).not.toBeInTheDocument();
    expect(panel.querySelector(".public-inference-form")).not.toBeInTheDocument();
    expect(panel.querySelector(".inference-result")).not.toBeInTheDocument();
  });

  it("Inference exposes exactly one form panel and one result surface, and no Overview cards", () => {
    renderReadySurface();
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));

    const panel = screen.getByRole("tabpanel");
    expect(panel.querySelectorAll(".public-inference-surface__form-panel.public-inference-form")).toHaveLength(1);
    expect(panel.querySelectorAll(".inference-result")).toHaveLength(1);

    expect(panel.querySelector(".dataset-detail-overview__problem-summary")).not.toBeInTheDocument();
    expect(panel.querySelector(".performance-summary")).not.toBeInTheDocument();
    expect(panel.querySelector(".dataset-detail-visualization")).not.toBeInTheDocument();
  });

  it("Documentation stays empty and does not duplicate the hidden Inference surface", () => {
    renderReadySurface();
    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));

    const panel = screen.getByRole("tabpanel");
    expect(panel).toBeEmptyDOMElement();
    expect(panel.querySelectorAll(".atlas-card")).toHaveLength(0);
    expect(panel.querySelector(".public-inference-form")).not.toBeInTheDocument();
    expect(panel.querySelector(".inference-result")).not.toBeInTheDocument();
  });
});
