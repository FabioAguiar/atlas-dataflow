import "@testing-library/jest-dom/vitest";
import type { ComponentProps } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

// This project has no @types/node dependency; both resolve fine at test
// runtime via Node/Vite, so the missing ambient types are suppressed here
// rather than pulling in a new devDependency for one CSS-contract test.
// @ts-expect-error -- no @types/node in this project
import { readFileSync } from "node:fs";
declare const process: { cwd(): string };

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

  // Project Spec S0140: proves the inactive panel is hidden in place rather
  // than recreated -- an uncontrolled input's live DOM value only survives a
  // tab switch if the panel stays mounted, and a remount (or an unmount) would
  // reset it.
  it("keeps inactive panel content mounted -- not recreated -- across a tab switch", () => {
    render(
      <DatasetDetailTabs
        inferenceContent={<input aria-label="Inference note" defaultValue="" />}
        overviewContent={<div>Overview panel content</div>}
      />,
    );

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const inferenceTab = screen.getByRole("tab", { name: "Inference" });

    fireEvent.click(inferenceTab);
    const input = screen.getByLabelText("Inference note") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "kept across tabs" } });
    expect(input.value).toBe("kept across tabs");

    fireEvent.click(overviewTab);
    fireEvent.click(inferenceTab);

    const sameInput = screen.getByLabelText("Inference note") as HTMLInputElement;
    expect(sameInput).toBe(input);
    expect(sameInput.value).toBe("kept across tabs");
  });

  // Project Spec S0140: repeated switching must never leave two panels
  // simultaneously active, and must never lose the invariant that exactly
  // one tab is selected and exactly one panel lacks `hidden`.
  it("keeps exactly one panel active and unhidden through a repeated switching sequence", () => {
    render(
      <DatasetDetailTabs
        documentationContent={<div>Documentation panel content</div>}
        inferenceContent={<div>Inference panel content</div>}
        overviewContent={<div>Overview panel content</div>}
      />,
    );

    const sequence = ["Overview", "Inference", "Documentation", "Overview", "Inference"];

    for (const tabName of sequence) {
      fireEvent.click(screen.getByRole("tab", { name: tabName }));

      const tabs = screen.getAllByRole("tab");
      const selectedTabs = tabs.filter((tab) => tab.getAttribute("aria-selected") === "true");
      expect(selectedTabs).toHaveLength(1);
      expect(selectedTabs[0]).toHaveAccessibleName(tabName);

      const panels = document.querySelectorAll(".dataset-detail-tabs__panel");
      const unhiddenPanels = Array.from(panels).filter((panel) => panel.getAttribute("hidden") === null);
      expect(unhiddenPanels).toHaveLength(1);
      expect(unhiddenPanels[0].textContent).toBe(`${tabName} panel content`);
    }
  });
});

// Project Spec S0140: jsdom cannot calculate the cascade of an external
// stylesheet imported via `import "./App.css"`, so the hidden-panel
// display-none contract and the visible-panel grid scoping are asserted
// directly against the stylesheet source here, alongside the component-level
// hidden-attribute assertions above and the browser validation recorded in
// the implementation evidence.
describe("Dataset Detail tab panel hidden-state CSS contract (S0140)", () => {
  const appCss = readFileSync(`${process.cwd()}/src/App.css`, "utf8");

  function ruleBody(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = appCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for selector "${selector}"`).not.toBeNull();
    return match![1];
  }

  it("declares an explicit hidden-panel display-none rule", () => {
    expect(ruleBody(".dataset-detail-tabs__panel[hidden]")).toMatch(/display:\s*none/);
  });

  it("scopes the grid layout to the visible panel only", () => {
    expect(ruleBody(".dataset-detail-tabs__panel:not([hidden])")).toMatch(/display:\s*grid/);

    // The bare, unqualified selector must not itself assign a visible
    // display mode -- that was the S0140 regression (every panel, hidden or
    // not, received `display: grid`).
    expect(ruleBody(".dataset-detail-tabs__panel")).not.toMatch(/display:/);
  });

  it("does not rely on !important to resolve the panel visibility cascade", () => {
    expect(ruleBody(".dataset-detail-tabs__panel[hidden]")).not.toMatch(/!important/);
    expect(ruleBody(".dataset-detail-tabs__panel:not([hidden])")).not.toMatch(/!important/);
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
          targetDistributionContent={<div data-testid="target-distribution-slot">Target distribution content</div>}
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
    expect(screen.getAllByTestId("target-distribution-slot")).toHaveLength(1);
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

// Project Spec S0138: the shared surface's public presentation contract
// restores the Target Distribution slot removed by S0136, and each tab's
// visible tabpanel owns exactly its authorized cards -- Overview now owns
// four cards (including the donut), never a fifth card, an Inference-owned
// surface leaking into Overview, or the reverse. Every assertion below is
// scoped to screen.getByRole("tabpanel"), which testing-library resolves to
// the one panel currently lacking `hidden` -- never a raw whole-container
// query that would also see the other two tabs' mounted-but-hidden content.
describe("DatasetDetailSurface exact tab card ownership (S0138)", () => {
  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: "Example Org", href: "https://example.org/data" },
    { label: "Instances", value: "500" },
    { label: "Features", value: "4" },
    { label: "Target", value: "Synthetic target" },
    { label: "Release", value: "01/07/2026", hint: "Format: dd/mm/yyyy" },
  ];

  const readyVisualizations = {
    charts: [
      { id: "target_distribution", type: "bar" as const, data: [{ name: "No", value: 30 }, { name: "Yes", value: 10 }] },
      { id: "feature_importance", type: "bar" as const, data: [{ name: "tenure", value: 0.7 }] },
    ],
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
          targetDistributionContent={<TargetDistribution visualizations={readyVisualizations} />}
          themePresetId="ocean-blue"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("Overview exposes exactly the four authorized cards, one donut and one ranked visualization, and no Inference surface", () => {
    renderReadySurface();

    const panel = screen.getByRole("tabpanel");
    const cards = panel.querySelectorAll(".atlas-card");
    expect(cards).toHaveLength(4);
    expect(panel.querySelector(".atlas-card.dataset-detail-overview__problem-summary")).toBeInTheDocument();
    expect(panel.querySelector(".atlas-card.performance-summary")).toBeInTheDocument();
    expect(
      panel.querySelector(".atlas-card.dataset-detail-visualization.dataset-detail-visualization--donut"),
    ).toBeInTheDocument();
    expect(
      panel.querySelector(".atlas-card.dataset-detail-visualization.dataset-detail-visualization--ranked"),
    ).toBeInTheDocument();
    expect(panel.querySelectorAll(".dataset-detail-visualization--donut")).toHaveLength(1);
    expect(panel.querySelectorAll(".dataset-detail-visualization--ranked")).toHaveLength(1);

    // Target Distribution renders the fixture's own authoritative labels and
    // counts -- never a fabricated demonstration value.
    const donutChart = within(panel).getByLabelText("Target Distribution");
    expect(within(donutChart).getByText("No")).toBeInTheDocument();
    expect(within(donutChart).getByText("Yes")).toBeInTheDocument();
    expect(within(donutChart).getByText("(30)")).toBeInTheDocument();
    expect(within(donutChart).getByText("(10)")).toBeInTheDocument();

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

// Project Spec S0200: PerformanceSummary consumes the shared
// performanceMetricMetadata module for both its performance_focus.visible_scores
// path and its normalizeEvaluation(metrics) fallback path, rendering a
// single-line, explanatory-only optimization orientation that never becomes
// a second independent direction map, never persists into public profiles
// (this component receives only presentation props), and never invents a
// direction for an unknown score.
describe("PerformanceSummary optimization orientation (Project Spec S0200)", () => {
  it("renders only the favorable-direction hint for a higher-is-better score (ROC-AUC 0.8402)", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.8402", value_source: "canonical", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("ROC-AUC").closest(".performance-summary__score") as HTMLElement;
    expect(within(score).getByText("Higher is better")).toBeInTheDocument();
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(score).toHaveTextContent("0.8402");
  });

  it("renders only the favorable-direction hint for a lower-is-better score (Brier Score 0.1394)", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "probability_quality",
          highlighted_score_id: "brier_score",
          visible_scores: [
            { score_id: "brier_score", display_label: "Brier Score", value: "0.1394", value_source: "canonical", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("Brier Score").closest(".performance-summary__score") as HTMLElement;
    expect(within(score).getByText("Lower is better")).toBeInTheDocument();
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(score).toHaveTextContent("0.1394");
  });

  it("renders a neutral closer-to-1 message for Calibration Slope, never a monotonic arrow pair", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "probability_quality",
          highlighted_score_id: "calibration_slope",
          visible_scores: [
            { score_id: "calibration_slope", display_label: "Calibration Slope", value: "0.97", value_source: "canonical", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("Calibration Slope").closest(".performance-summary__score") as HTMLElement;
    expect(within(score).getByText("Closer to 1 is better")).toBeInTheDocument();
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
  });

  it("renders a neutral closer-to-0 message for Calibration Intercept, never a monotonic arrow pair", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "probability_quality",
          highlighted_score_id: "calibration_intercept",
          visible_scores: [
            { score_id: "calibration_intercept", display_label: "Calibration Intercept", value: "-0.03", value_source: "canonical", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("Calibration Intercept").closest(".performance-summary__score") as HTMLElement;
    expect(within(score).getByText("Closer to 0 is better")).toBeInTheDocument();
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
  });

  it("renders no direction hint for an unknown score id, without throwing, while still showing label and value", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "operational_decision",
          highlighted_score_id: "not_a_real_metric",
          visible_scores: [
            { score_id: "not_a_real_metric", display_label: "Mystery Metric", value: "1.0", value_source: "manual", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("Mystery Metric").closest(".performance-summary__score") as HTMLElement;
    expect(score.querySelector(".performance-summary__score-orientation")).not.toBeInTheDocument();
    expect(score).toHaveTextContent("1.0");
  });

  it("preserves Highlighted and score value alongside the orientation for real Telco-style examples (pr_auc 0.6413, roc_auc 0.8402)", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "overall_discrimination",
          highlighted_score_id: "pr_auc",
          visible_scores: [
            { score_id: "pr_auc", display_label: "PR-AUC", value: "0.6413", value_source: "canonical", order: 0 },
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.8402", value_source: "canonical", order: 1 },
          ],
        }}
      />,
    );

    const prAucScore = screen.getByText("PR-AUC").closest(".performance-summary__score") as HTMLElement;
    expect(within(prAucScore).getByText("Highlighted")).toBeInTheDocument();
    expect(prAucScore).toHaveTextContent("0.6413");
    expect(within(prAucScore).getByText("Higher is better")).toBeInTheDocument();

    const rocAucScore = screen.getByText("ROC-AUC").closest(".performance-summary__score") as HTMLElement;
    expect(within(rocAucScore).queryByText("Highlighted")).not.toBeInTheDocument();
    expect(rocAucScore).toHaveTextContent("0.8402");
  });

  it("expresses direction as visible accessible text, with the arrow glyph aria-hidden rather than color-only (log_loss 0.4207)", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "probability_quality",
          highlighted_score_id: "log_loss",
          visible_scores: [
            { score_id: "log_loss", display_label: "Log Loss", value: "0.4207", value_source: "canonical", order: 0 },
          ],
        }}
      />,
    );

    const score = screen.getByText("Log Loss").closest(".performance-summary__score") as HTMLElement;
    const arrow = within(score).getByText("↓");
    expect(arrow).toHaveAttribute("aria-hidden", "true");
    expect(score).toHaveTextContent("Lower is better");
  });

  it("also applies the shared optimization metadata when rendering from normalizeEvaluation(metrics) directly, preserving existing normalized labels/values", () => {
    render(<PerformanceSummary metrics={{ auc_roc: 0.87, log_loss: 0.42 }} />);

    const rocScore = screen.getByText("AUC ROC").closest(".performance-summary__score") as HTMLElement;
    expect(within(rocScore).getByText("Higher is better")).toBeInTheDocument();

    const logLossScore = screen.getByText("Log Loss").closest(".performance-summary__score") as HTMLElement;
    expect(within(logLossScore).getByText("Lower is better")).toBeInTheDocument();
  });
});
