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
import TargetDistribution, { buildDonutTooltipModel, buildHistogramTooltipModel } from "./TargetDistribution";
import RegressionDiagnostics, {
  buildActualVsPredictedTooltipModel,
  buildResidualTooltipModel,
} from "./RegressionDiagnostics";
import ForecastingDiagnostics, {
  ForecastingEvaluationOverview,
  buildBacktestingTooltipModel,
  buildForecastVsActualTooltipModel,
  buildHorizonTooltipModel,
  buildSeasonalProfileTooltipModel,
  resolveMetricSelection,
} from "./ForecastingDiagnostics";
import { resolveChartInteractionMode } from "./DatasetChartTooltip";
import ConfusionMatrix from "./ConfusionMatrix";
import { presentDatasetDateOnly, safePublicSourceUrl } from "../../lib/datasetPresentation";
import { isPerformanceFocusApplicable } from "../../lib/performanceMetricMetadata";

function renderHeader(
  metadata: DatasetDetailMetadataItem[],
  overrides: Partial<ComponentProps<typeof DatasetDetailHeader>> = {},
) {
  return render(
    <MemoryRouter>
      <DatasetDetailHeader
        analysisType="Classificacao binaria"
        datasetTitle="Synthetic Demo Dataset"
        metadata={metadata}
        subtitle="Synthetic public-safe detail subtitle."
        {...overrides}
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

// Project Spec S0204: the Performance focus badge sits beside the existing
// problem-type badge as one responsive badge group.
describe("DatasetDetailHeader Performance focus badge (Project Spec S0204)", () => {
  it("renders both the problem-type and Performance focus badges when the focus id is known", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination" });

    expect(screen.getByText("Classificacao binaria")).toBeInTheDocument();
    expect(screen.getByText("Overall discrimination")).toBeInTheDocument();
    const badgeLabel = screen.getByText("Overall discrimination");
    expect(badgeLabel.closest(".atlas-badge")).toBeInTheDocument();
  });

  it("uses the shared focus label authority, not an invented label from the raw id", () => {
    renderHeader([], { performanceFocusId: "positive_class_detection" });
    expect(screen.getByText("Positive-class detection")).toBeInTheDocument();
    expect(screen.queryByText("positive_class_detection")).not.toBeInTheDocument();
  });

  it("omits the second badge for an unknown focus id, leaving the problem-type badge unchanged", () => {
    renderHeader([], { performanceFocusId: "not_a_real_focus" });
    expect(screen.getByText("Classificacao binaria")).toBeInTheDocument();
    expect(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge")).toHaveLength(1);
  });

  it("omits the second badge when the focus id is missing", () => {
    renderHeader([]);
    expect(screen.getByText("Classificacao binaria")).toBeInTheDocument();
    expect(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge")).toHaveLength(1);
  });

  it("renders the badge group as a responsive container beside the title", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination" });
    const badgeGroup = document.querySelector(".dataset-detail-header__badges");
    expect(badgeGroup).toBeInTheDocument();
    expect(badgeGroup?.closest(".dataset-detail-header__heading")).toBeInTheDocument();
    expect(within(badgeGroup as HTMLElement).getAllByText(/Classificacao binaria|Overall discrimination/)).toHaveLength(2);
  });

  it("renders only the problem-type badge when analysisType is absent but focus is known (no invented problem type)", () => {
    render(
      <MemoryRouter>
        <DatasetDetailHeader
          datasetTitle="Synthetic Demo Dataset"
          metadata={[]}
          performanceFocusId="overall_discrimination"
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Overall discrimination")).toBeInTheDocument();
    expect(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge")).toHaveLength(1);
  });
});

// Project Spec S0238: the release-bound Model badge joins the existing
// problem/focus pair into a fixed three-role triad, shared with Home Card
// through DatasetIdentityBadges, each carrying its own Theme Preset-derived
// color role class.
describe("DatasetDetailHeader Dataset identity badge triad (Project Spec S0238)", () => {
  it("renders the problem, focus, and model badges in that exact order when all three authorities are available", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination", modelDisplayName: "HistGradientBoosting" });

    const badges = Array.from(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual([
      "Classificacao binaria",
      "Overall discrimination",
      "HistGradientBoosting",
    ]);
  });

  it("assigns three distinct Theme Preset-derived role classes to the three badges", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination", modelDisplayName: "HistGradientBoosting" });

    const badges = Array.from(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge"));
    expect(badges.map((badge) => badge.className)).toEqual([
      expect.stringContaining("dataset-identity-badge--problem"),
      expect.stringContaining("dataset-identity-badge--focus"),
      expect.stringContaining("dataset-identity-badge--model"),
    ]);
  });

  it("omits only the Model badge when modelDisplayName is missing, leaving problem and focus intact", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination" });

    const badges = Array.from(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual(["Classificacao binaria", "Overall discrimination"]);
  });

  it("omits only the Model badge when modelDisplayName is blank", () => {
    renderHeader([], { performanceFocusId: "overall_discrimination", modelDisplayName: "   " });

    const badges = Array.from(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual(["Classificacao binaria", "Overall discrimination"]);
  });
});

// Project Spec S0238: badge role colors must trace back to Theme Preset
// tokens only (accent for problem, chart_secondary for focus,
// border_strong/surface for model) -- never a hardcoded hex/rgb/hsl literal
// or a dataset/model-specific color map.
describe("Dataset identity badge role color CSS contract (Project Spec S0238)", () => {
  const appCss = readFileSync(`${process.cwd()}/src/App.css`, "utf8");

  function ruleBody(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = appCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for selector "${selector}"`).not.toBeNull();
    return match![1];
  }

  it("derives the problem role from the accent token family", () => {
    expect(ruleBody(".atlas-badge.dataset-identity-badge--problem")).toMatch(/--atlas-color-accent/);
  });

  it("derives the focus role from the chart_secondary token family", () => {
    expect(ruleBody(".atlas-badge.dataset-identity-badge--focus")).toMatch(/--dataset-theme-chart-secondary/);
  });

  it("derives the model role from the border_strong/structural token family", () => {
    expect(ruleBody(".atlas-badge.dataset-identity-badge--model")).toMatch(/--atlas-color-border-strong/);
  });

  it("never hardcodes a hex/rgb/hsl color literal for any of the three badge roles", () => {
    for (const role of ["problem", "focus", "model"]) {
      const body = ruleBody(`.atlas-badge.dataset-identity-badge--${role}`);
      expect(body).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(body).not.toMatch(/\brgb\(|\brgba\(|\bhsl\(|\bhsla\(/);
    }
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

// Project Spec S0204: PerformanceSummary's focus subtitle resolves through
// the same shared performanceMetricMetadata authority DatasetCard and
// DatasetDetailHeader use -- it no longer owns a local focus-label map.
describe("PerformanceSummary focus subtitle shared label authority (Project Spec S0204)", () => {
  const publishedFocus = {
    focus_id: "overall_discrimination" as const,
    highlighted_score_id: "roc_auc",
    visible_scores: [
      { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.84", value_source: "manual" as const, order: 0 },
    ],
  };

  it("renders the shared label for a known published focus", () => {
    render(<PerformanceSummary metrics={{}} performanceFocus={publishedFocus} />);
    expect(screen.getByText("Overall discrimination")).toBeInTheDocument();
  });

  it("omits the focus subtitle for an unknown focus id rather than inventing a label", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{ ...publishedFocus, focus_id: "not_a_real_focus" as unknown as typeof publishedFocus.focus_id }}
      />,
    );
    expect(document.querySelector(".performance-summary__focus")).not.toBeInTheDocument();
  });
});

// Project Spec S0215: PerformanceSummary never presents ambiguous
// binary-only scores as multiclass-compatible, whether the score list came
// from a published Admin focus or the raw canonical fallback metrics.
describe("PerformanceSummary multiclass problem-type filtering (Project Spec S0215)", () => {
  const staleBinaryFocus = {
    focus_id: "balanced_classification" as const,
    highlighted_score_id: "f1_macro",
    visible_scores: [
      { score_id: "f1_score", display_label: "F1-score", value: "0.77", value_source: "manual" as const, order: 0 },
      { score_id: "recall", display_label: "Recall", value: "0.75", value_source: "manual" as const, order: 1 },
      { score_id: "f1_macro", display_label: "F1 Macro", value: "0.80", value_source: "manual" as const, order: 2 },
    ],
  };

  it("filters an ambiguous binary-only published score id out of a multiclass release", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={staleBinaryFocus}
        problemType="multiclass_classification"
      />,
    );
    expect(screen.getByText("F1 Macro")).toBeInTheDocument();
    expect(screen.queryByText("F1-score")).not.toBeInTheDocument();
    expect(screen.queryByText("Recall")).not.toBeInTheDocument();
  });

  it("preserves every published score id, unfiltered, for a binary release", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={staleBinaryFocus}
        problemType="binary_classification"
      />,
    );
    expect(screen.getByText("F1-score")).toBeInTheDocument();
    expect(screen.getByText("Recall")).toBeInTheDocument();
    expect(screen.getByText("F1 Macro")).toBeInTheDocument();
  });

  it("preserves every published score id, unfiltered, when problemType is omitted", () => {
    render(<PerformanceSummary metrics={{}} performanceFocus={staleBinaryFocus} />);
    expect(screen.getByText("F1-score")).toBeInTheDocument();
    expect(screen.getByText("Recall")).toBeInTheDocument();
  });

  it("renders explicit multiclass aggregate labels from the canonical fallback metrics, never relabeled as generic F1", () => {
    render(
      <PerformanceSummary
        metrics={{ evaluation: { metrics: { f1_macro: 0.75, f1_weighted: 0.76, balanced_accuracy: 0.72 } } }}
        problemType="multiclass_classification"
      />,
    );
    expect(screen.getByText("F1 Macro")).toBeInTheDocument();
    expect(screen.getByText("F1 Weighted")).toBeInTheDocument();
    expect(screen.getByText("Balanced Accuracy")).toBeInTheDocument();
  });

  it("never surfaces an ambiguous binary-only canonical fallback metric for a multiclass release", () => {
    render(
      <PerformanceSummary
        metrics={{ evaluation: { metrics: { f1_score: 0.77, precision: 0.8, recall: 0.75, accuracy: 0.9 } } }}
        problemType="multiclass_classification"
      />,
    );
    expect(screen.getByText("Accuracy")).toBeInTheDocument();
    expect(screen.queryByText("F1-score")).not.toBeInTheDocument();
    expect(screen.queryByText("Precision")).not.toBeInTheDocument();
    expect(screen.queryByText("Recall")).not.toBeInTheDocument();
  });

  it("renders nothing when every canonical fallback metric is binary-only for a multiclass release", () => {
    const { container } = render(
      <PerformanceSummary
        metrics={{ evaluation: { metrics: { f1_score: 0.77, precision: 0.8 } } }}
        problemType="multiclass_classification"
      />,
    );
    expect(container.querySelector(".performance-summary")).not.toBeInTheDocument();
  });
});

// Project Spec S0229: the regression Performance Summary must recognize
// r2/mae/rmse with the correct orientation and never present a classification
// score for a continuous-regression release (or vice versa).
describe("PerformanceSummary continuous-regression problem-type filtering and direction (Project Spec S0229)", () => {
  const regressionFocus = {
    focus_id: "regression_performance" as const,
    highlighted_score_id: "r2",
    visible_scores: [
      { score_id: "r2", display_label: "R²", value: "0.87", value_source: "canonical" as const, order: 0 },
      { score_id: "mae", display_label: "MAE", value: "3.21", value_source: "canonical" as const, order: 1 },
      { score_id: "rmse", display_label: "RMSE", value: "4.55", value_source: "canonical" as const, order: 2 },
    ],
  };

  it("renders r2/mae/rmse with the correct favorable-direction arrow orientation", () => {
    render(<PerformanceSummary metrics={{}} performanceFocus={regressionFocus} problemType="continuous_regression" />);

    const r2 = screen.getByText("R²").closest(".performance-summary__score") as HTMLElement;
    expect(r2.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Higher is better");
    const mae = screen.getByText("MAE").closest(".performance-summary__score") as HTMLElement;
    expect(mae.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Lower is better");
    const rmse = screen.getByText("RMSE").closest(".performance-summary__score") as HTMLElement;
    expect(rmse.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Lower is better");
    // Project Spec S0221: never a visible "Higher/Lower is better" line.
    expect(screen.queryByText("Higher is better")).not.toBeInTheDocument();
    expect(screen.queryByText("Lower is better")).not.toBeInTheDocument();
  });

  it("filters a stale classification score id out of a continuous-regression release", () => {
    const staleClassificationFocus = {
      focus_id: "regression_performance" as const,
      highlighted_score_id: "r2",
      visible_scores: [
        { score_id: "r2", display_label: "R²", value: "0.87", value_source: "canonical" as const, order: 0 },
        { score_id: "accuracy", display_label: "Accuracy", value: "0.9", value_source: "manual" as const, order: 1 },
      ],
    };
    render(<PerformanceSummary metrics={{}} performanceFocus={staleClassificationFocus} problemType="continuous_regression" />);
    expect(screen.getByText("R²")).toBeInTheDocument();
    expect(screen.queryByText("Accuracy")).not.toBeInTheDocument();
  });

  it("renders explicit regression labels from the canonical fallback metrics", () => {
    render(
      <PerformanceSummary
        metrics={{ evaluation: { metrics: { r2: 0.87, mae: 3.21, rmse: 4.55 } } }}
        problemType="continuous_regression"
      />,
    );
    expect(screen.getByText("R²")).toBeInTheDocument();
    expect(screen.getByText("MAE")).toBeInTheDocument();
    expect(screen.getByText("RMSE")).toBeInTheDocument();
  });

  it("never surfaces a classification canonical fallback metric for a continuous-regression release", () => {
    render(
      <PerformanceSummary
        metrics={{ evaluation: { metrics: { accuracy: 0.9, f1_score: 0.77, r2: 0.87 } } }}
        problemType="continuous_regression"
      />,
    );
    expect(screen.getByText("R²")).toBeInTheDocument();
    expect(screen.queryByText("Accuracy")).not.toBeInTheDocument();
    expect(screen.queryByText("F1-score")).not.toBeInTheDocument();
  });

  it("classification focus applicability remains unchanged: regression_performance is never offered as a binary/multiclass focus", () => {
    expect(isPerformanceFocusApplicable("regression_performance", "binary_classification")).toBe(false);
    expect(isPerformanceFocusApplicable("regression_performance", "multiclass_classification")).toBe(false);
    expect(isPerformanceFocusApplicable("overall_discrimination", "continuous_regression")).toBe(false);
  });
});

// Project Spec S0253: the forecasting Performance Summary must recognize
// mae/rmse/seasonal_mase with the correct lower-is-better orientation and
// never present a stale classification-only score for a univariate_forecasting
// release, using the same shared PerformanceFocusId/applicability authority
// multiclass/regression already use above.
describe("PerformanceSummary forecasting problem-type filtering and direction (Project Spec S0253)", () => {
  const forecastingFocus = {
    focus_id: "forecasting_performance" as const,
    highlighted_score_id: "mae",
    visible_scores: [
      { score_id: "mae", display_label: "MAE", value: "3.21", value_source: "canonical" as const, order: 0 },
      { score_id: "rmse", display_label: "RMSE", value: "4.55", value_source: "canonical" as const, order: 1 },
      { score_id: "seasonal_mase", display_label: "Seasonal MASE", value: "1.12", value_source: "canonical" as const, order: 2 },
    ],
  };

  it("renders the shared forecasting_performance focus label", () => {
    render(
      <PerformanceSummary metrics={{}} performanceFocus={forecastingFocus} problemType="univariate_forecasting" />,
    );
    expect(screen.getByText("Forecasting performance")).toBeInTheDocument();
  });

  it("renders mae/rmse/seasonal_mase with the correct lower-is-better arrow orientation", () => {
    render(
      <PerformanceSummary metrics={{}} performanceFocus={forecastingFocus} problemType="univariate_forecasting" />,
    );

    const mae = screen.getByText("MAE").closest(".performance-summary__score") as HTMLElement;
    expect(mae.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Lower is better");
    const rmse = screen.getByText("RMSE").closest(".performance-summary__score") as HTMLElement;
    expect(rmse.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Lower is better");
    const seasonalMase = screen.getByText("Seasonal MASE").closest(".performance-summary__score") as HTMLElement;
    expect(seasonalMase.querySelector(".performance-summary__score-arrows")).toHaveAttribute("aria-label", "Lower is better");
    // Project Spec S0221: never a visible "Higher/Lower is better" line.
    expect(screen.queryByText("Higher is better")).not.toBeInTheDocument();
    expect(screen.queryByText("Lower is better")).not.toBeInTheDocument();
  });

  it("filters a stale classification-only published score id out of a univariate_forecasting release", () => {
    const staleClassificationFocus = {
      focus_id: "forecasting_performance" as const,
      highlighted_score_id: "mae",
      visible_scores: [
        { score_id: "mae", display_label: "MAE", value: "3.21", value_source: "canonical" as const, order: 0 },
        { score_id: "accuracy", display_label: "Accuracy", value: "0.9", value_source: "manual" as const, order: 1 },
      ],
    };
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={staleClassificationFocus}
        problemType="univariate_forecasting"
      />,
    );
    expect(screen.getByText("MAE")).toBeInTheDocument();
    expect(screen.queryByText("Accuracy")).not.toBeInTheDocument();
  });

  it("forecasting focus applicability remains bounded and does not spill into classification/regression foci", () => {
    expect(isPerformanceFocusApplicable("forecasting_performance", "binary_classification")).toBe(false);
    expect(isPerformanceFocusApplicable("forecasting_performance", "multiclass_classification")).toBe(false);
    expect(isPerformanceFocusApplicable("forecasting_performance", "continuous_regression")).toBe(false);
    expect(isPerformanceFocusApplicable("regression_performance", "univariate_forecasting")).toBe(false);
  });
});

// Project Spec S0215: the shared normalized multiclass confusion-matrix
// renderer used by both public Dataset Detail and Admin Live Preview.
describe("ConfusionMatrix (Project Spec S0215)", () => {
  const validVisualizations = {
    confusion_matrix: {
      ordered_class_ids: ["setosa", "versicolor", "virginica"],
      matrix: [
        [0.9, 0.1, 0],
        [0.05, 0.85, 0.1],
        [0, 0.2, 0.8],
      ],
      row_axis: "true_class",
      column_axis: "predicted_class",
    },
  };

  it("renders nothing when visualizations is null", () => {
    const { container } = render(<ConfusionMatrix visualizations={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when confusion_matrix is absent (every binary release)", () => {
    const { container } = render(<ConfusionMatrix visualizations={{ charts: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when ordered_class_ids has fewer than 3 entries", () => {
    const { container } = render(
      <ConfusionMatrix
        visualizations={{
          confusion_matrix: { ordered_class_ids: ["a", "b"], matrix: [[1, 0], [0, 1]] },
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when a cell is out of [0,1] bounds", () => {
    const { container } = render(
      <ConfusionMatrix
        visualizations={{
          confusion_matrix: {
            ordered_class_ids: ["a", "b", "c"],
            matrix: [
              [1.5, 0, 0],
              [0, 1, 0],
              [0, 0, 1],
            ],
          },
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when a row does not sum to 1", () => {
    const { container } = render(
      <ConfusionMatrix
        visualizations={{
          confusion_matrix: {
            ordered_class_ids: ["a", "b", "c"],
            matrix: [
              [0.5, 0.2, 0.2],
              [0, 1, 0],
              [0, 0, 1],
            ],
          },
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the matrix shape is not NxN", () => {
    const { container } = render(
      <ConfusionMatrix
        visualizations={{
          confusion_matrix: {
            ordered_class_ids: ["a", "b", "c"],
            matrix: [
              [1, 0],
              [0, 1],
              [0, 1],
            ],
          },
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a table with governed row/column class order and readable percentages", () => {
    render(<ConfusionMatrix visualizations={validVisualizations} />);

    const table = screen.getByRole("table", { name: "Confusion matrix" });
    const rowHeaders = within(table).getAllByRole("rowheader").map((cell) => cell.textContent);
    expect(rowHeaders).toEqual(["setosa", "versicolor", "virginica"]);

    const columnHeaders = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent)
      .filter((text) => ["setosa", "versicolor", "virginica"].includes(text ?? ""));
    expect(columnHeaders).toEqual(["setosa", "versicolor", "virginica"]);

    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText("85.0%")).toBeInTheDocument();
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("labels rows as actual classes and columns as predicted classes", () => {
    render(<ConfusionMatrix visualizations={validVisualizations} />);
    expect(screen.getByText("Actual class")).toBeInTheDocument();
    expect(screen.getByText("Predicted class")).toBeInTheDocument();
    expect(screen.getByText("Rows are actual classes; columns are predicted classes.")).toBeInTheDocument();
  });

  it("never conveys a cell's value through color alone -- every cell carries readable percentage text", () => {
    render(<ConfusionMatrix visualizations={validVisualizations} />);
    const table = screen.getByRole("table", { name: "Confusion matrix" });
    const dataCells = within(table).getAllByRole("cell");
    expect(dataCells).toHaveLength(9);
    for (const cell of dataCells) {
      expect(cell.textContent).toMatch(/^\d+\.\d%$/);
    }
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

// Project Spec S0221: the Confusion Matrix card must span the complete
// analytics grid row whenever it is rendered, keyed to its own card
// identity -- never to child ordinal/last-child position, dataset slug, or
// class count -- so it applies identically at every grid width without a
// special case.
describe("Confusion Matrix full analytics-grid-row CSS contract (Project Spec S0221)", () => {
  const appCss = readFileSync(`${process.cwd()}/src/App.css`, "utf8");

  function ruleBody(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = appCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for selector "${selector}"`).not.toBeNull();
    return match![1];
  }

  it("spans the confusion matrix card across the full analytics grid row, keyed to the card's own identity class", () => {
    expect(
      ruleBody(".dataset-detail-overview__analytics > .dataset-detail-visualization--confusion-matrix"),
    ).toMatch(/grid-column:\s*1\s*\/\s*-1/);
  });

  it("does not key the full-row rule to child ordinal, last-child position, or a fixed class count", () => {
    expect(appCss).not.toMatch(
      /:last-child:nth-child\(\d+\)\s*\{\s*grid-column:\s*1\s*\/\s*-1[^}]*\}\s*[^{]*confusion-matrix/,
    );
    expect(appCss).not.toContain(".dataset-detail-visualization--confusion-matrix:nth-child");
    expect(appCss).not.toContain(".dataset-detail-visualization--confusion-matrix:last-child");
  });

  it("preserves the confusion matrix's own internal horizontal overflow fallback", () => {
    expect(ruleBody(".confusion-matrix__scroll")).toMatch(/overflow-x:\s*auto/);
    expect(ruleBody(".confusion-matrix__table")).toMatch(/width:\s*100%/);
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

  // Project Spec S0204: DatasetDetailSurface owns no focus label map itself
  // -- it only forwards performanceFocusId to DatasetDetailHeader, which
  // resolves the label through the shared authority.
  it("forwards performanceFocusId to the header, rendering both badges", () => {
    renderSurface({ performanceFocusId: "overall_discrimination" });
    expect(screen.getByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Overall discrimination")).toBeInTheDocument();
  });

  it("renders only the problem-type badge when performanceFocusId is absent", () => {
    renderSurface();
    expect(screen.getByText("Binary Classification")).toBeInTheDocument();
    expect(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge")).toHaveLength(1);
  });

  // Project Spec S0238: forwards modelDisplayName to the header, completing
  // the shared problem/focus/model triad -- DatasetDetailSurface itself
  // performs no result-contract inspection.
  it("forwards modelDisplayName to the header, rendering the full problem/focus/model triad", () => {
    renderSurface({ performanceFocusId: "overall_discrimination", modelDisplayName: "HistGradientBoosting" });
    const badges = Array.from(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual([
      "Binary Classification",
      "Overall discrimination",
      "HistGradientBoosting",
    ]);
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

  // Project Spec S0271: the shared surface accepts a bounded, presentation-only
  // inferenceAvailable input (default true) and never reads a contract itself.
  // These assertions stay dataset-agnostic -- only tab composition, panel
  // mounting, selection reset, and unchanged Overview/Documentation content.
  describe("capability-driven Inference tab (S0271)", () => {
    it("defaults to three tabs when inferenceAvailable is omitted", () => {
      renderSurface();
      expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Overview",
        "Inference",
        "Documentation",
      ]);
    });

    it("renders three tabs when inferenceAvailable is explicitly true", () => {
      renderSurface({ inferenceAvailable: true });
      expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Overview",
        "Inference",
        "Documentation",
      ]);
    });

    it("renders exactly Overview and Documentation when inferenceAvailable is false", () => {
      renderSurface({ inferenceAvailable: false });
      expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Overview",
        "Documentation",
      ]);
      expect(screen.queryByRole("tab", { name: "Inference" })).not.toBeInTheDocument();
    });

    it("does not mount an Inference tabpanel at all when inferenceAvailable is false", () => {
      renderSurface({ inferenceAvailable: false });
      expect(screen.queryByTestId("inference-slot")).not.toBeInTheDocument();
      const panels = document.querySelectorAll(".dataset-detail-tabs__panel");
      expect(panels).toHaveLength(2);
    });

    it("resets the selection to Overview when Inference was selected and availability flips false", () => {
      const { rerender } = renderSurface({ inferenceAvailable: true });
      fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
      expect(screen.getByRole("tab", { name: "Inference" })).toHaveAttribute("aria-selected", "true");

      rerender(
        <MemoryRouter>
          <DatasetDetailSurface
            analysisType="Binary Classification"
            datasetSubtitle="Synthetic surface subtitle"
            datasetTitle="Synthetic Surface Dataset"
            featureImportanceContent={<div data-testid="feature-importance-slot">Feature importance content</div>}
            inferenceAvailable={false}
            inferenceContent={<div data-testid="inference-slot">Inference content</div>}
            metadata={metadata}
            performanceContent={<div data-testid="performance-slot">Performance content</div>}
            problemSummaryBody="Synthetic problem summary body."
            problemSummaryTitle="Problem summary"
            targetDistributionContent={<div data-testid="target-distribution-slot">Target distribution content</div>}
            themePresetId="ocean-blue"
          />
        </MemoryRouter>,
      );

      expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
      expect(screen.queryByRole("tab", { name: "Inference" })).not.toBeInTheDocument();
      expect(screen.queryByTestId("inference-slot")).not.toBeInTheDocument();
    });

    it("keeps Overview and Documentation content unchanged when Inference is unavailable", () => {
      renderSurface({ inferenceAvailable: false, documentationContent: <p>Extra guidance</p> });

      expect(screen.getByTestId("performance-slot")).toBeInTheDocument();
      expect(screen.getByTestId("target-distribution-slot")).toBeInTheDocument();
      expect(screen.getByTestId("feature-importance-slot")).toBeInTheDocument();
      expect(screen.getByText("Synthetic problem summary body.")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
      expect(screen.getByRole("tabpanel")).toHaveTextContent("Extra guidance");
    });
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

  // Project Spec S0215: confusionMatrixContent is an optional fifth Overview
  // slot -- absent (undefined) for every binary composition above, so
  // binary Dataset Detail's exact four-card contract is unaffected. This
  // proves the slot itself when a caller does supply it for a multiclass
  // release.
  it("Overview renders a fifth card for confusionMatrixContent only when supplied with valid multiclass evidence", () => {
    const multiclassVisualizations = {
      charts: readyVisualizations.charts,
      confusion_matrix: {
        ordered_class_ids: ["class-a", "class-b", "class-c"],
        matrix: [
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ],
        row_axis: "true_class",
        column_axis: "predicted_class",
      },
    };
    renderReadySurface({
      confusionMatrixContent: <ConfusionMatrix visualizations={multiclassVisualizations} />,
    });

    const panel = screen.getByRole("tabpanel");
    expect(panel.querySelectorAll(".atlas-card")).toHaveLength(5);
    expect(
      panel.querySelector(".atlas-card.dataset-detail-visualization--confusion-matrix"),
    ).toBeInTheDocument();
  });

  it("Overview stays at exactly four cards when confusionMatrixContent is wired but the visualizations payload carries no matrix (binary release)", () => {
    renderReadySurface({
      confusionMatrixContent: <ConfusionMatrix visualizations={readyVisualizations} />,
    });

    const panel = screen.getByRole("tabpanel");
    expect(panel.querySelectorAll(".atlas-card")).toHaveLength(4);
    expect(
      panel.querySelector(".dataset-detail-visualization--confusion-matrix"),
    ).not.toBeInTheDocument();
  });
});

// Project Spec S0272/S0273: DatasetDetailSurface gains one optional, bounded
// forecasting-evaluation content slot placed after Problem summary and before
// the analytics grid, and (S0273) joins forecastingDiagnosticsContent into
// that same shared analytics grid alongside performanceContent rather than a
// second below-grid section. These tests exercise only the shared surface's
// DOM composition with synthetic nodes -- the real renderer's v4/v6 data
// validation is covered by the DatasetPage / Admin Live Preview integration
// tests using the actual shared component.
describe("DatasetDetailSurface forecasting-evaluation slot (Project Spec S0272/S0273)", () => {
  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: "Example Org", href: "https://example.org/data" },
    { label: "Release", value: "01/07/2026", hint: "Format: dd/mm/yyyy" },
  ];

  function renderSurface(overrides: Partial<ComponentProps<typeof DatasetDetailSurface>> = {}) {
    return render(
      <MemoryRouter>
        <DatasetDetailSurface
          analysisType="Univariate Forecasting"
          datasetSubtitle="Synthetic surface subtitle"
          datasetTitle="Synthetic Surface Dataset"
          featureImportanceContent={null}
          inferenceContent={<div data-testid="inference-slot">Inference content</div>}
          metadata={metadata}
          performanceContent={<div data-testid="performance-slot">Performance content</div>}
          problemSummaryBody="Synthetic problem summary body."
          problemSummaryTitle="Problem summary"
          targetDistributionContent={null}
          themePresetId="ocean-blue"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("renders the forecasting-evaluation node after Problem summary and before the analytics grid / performance content", () => {
    renderSurface({
      forecastingEvaluationContent: <div data-testid="evaluation-slot">Evaluation content</div>,
      forecastingDiagnosticsContent: <div data-testid="diagnostics-slot">Diagnostics content</div>,
    });

    const problemSummary = screen.getByText("Synthetic problem summary body.");
    const evaluationSlot = screen.getByTestId("evaluation-slot");
    const performanceSlot = screen.getByTestId("performance-slot");
    const analytics = document.querySelector(".dataset-detail-overview__analytics")!;

    expect(
      problemSummary.compareDocumentPosition(evaluationSlot) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      evaluationSlot.compareDocumentPosition(performanceSlot) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(analytics.contains(evaluationSlot)).toBe(false);
    expect(
      document.querySelector(".dataset-detail-overview__forecasting-evaluation")!.contains(evaluationSlot),
    ).toBe(true);
  });

  it("joins forecastingDiagnosticsContent into the shared analytics grid rather than a second below-grid section", () => {
    renderSurface({
      forecastingEvaluationContent: <div data-testid="evaluation-slot">Evaluation content</div>,
      forecastingDiagnosticsContent: <div data-testid="diagnostics-slot">Diagnostics content</div>,
    });

    const analytics = document.querySelector(".dataset-detail-overview__analytics")!;
    const diagnosticsSlot = screen.getByTestId("diagnostics-slot");
    expect(analytics.contains(diagnosticsSlot)).toBe(true);
    expect(
      document.querySelector(".dataset-detail-overview__forecasting-diagnostics")!.contains(diagnosticsSlot),
    ).toBe(true);
  });

  it("keeps performanceContent as the first item in the forecasting analytics composition", () => {
    renderSurface({
      forecastingDiagnosticsContent: <div data-testid="diagnostics-slot">Diagnostics content</div>,
    });

    const analytics = document.querySelector(".dataset-detail-overview__analytics")!;
    expect(analytics.firstElementChild).toHaveAttribute("data-testid", "performance-slot");
  });

  it("applies the forecasting analytics modifier only when forecastingDiagnosticsContent is present", () => {
    const { container: withDiagnostics } = renderSurface({
      forecastingDiagnosticsContent: <div data-testid="diagnostics-slot">Diagnostics content</div>,
    });
    expect(withDiagnostics.querySelector(".dataset-detail-overview__analytics--forecasting")).toBeInTheDocument();

    const { container: withoutDiagnostics } = renderSurface();
    expect(
      withoutDiagnostics.querySelector(".dataset-detail-overview__analytics--forecasting"),
    ).not.toBeInTheDocument();
    expect(withoutDiagnostics.querySelector(".dataset-detail-overview__analytics")).toBeInTheDocument();
  });

  it("never renders forecastingDiagnosticsContent twice", () => {
    renderSurface({
      forecastingDiagnosticsContent: <div data-testid="diagnostics-slot">Diagnostics content</div>,
    });
    expect(screen.getAllByTestId("diagnostics-slot")).toHaveLength(1);
  });

  it("classification/regression callers without forecastingDiagnosticsContent retain the historical analytics DOM behavior", () => {
    const { container } = render(
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
        />
      </MemoryRouter>,
    );

    const analytics = container.querySelector(".dataset-detail-overview__analytics")!;
    expect(analytics).not.toHaveClass("dataset-detail-overview__analytics--forecasting");
    expect(container.querySelectorAll(".dataset-detail-overview__forecasting-diagnostics")).toHaveLength(0);
    expect(within(analytics as HTMLElement).getByTestId("performance-slot")).toBeInTheDocument();
    expect(within(analytics as HTMLElement).getByTestId("target-distribution-slot")).toBeInTheDocument();
    expect(within(analytics as HTMLElement).getByTestId("feature-importance-slot")).toBeInTheDocument();
  });

  it("omitting forecastingEvaluationContent preserves the historical Overview DOM composition", () => {
    const { container } = renderSurface();

    expect(container.querySelector(".dataset-detail-overview__forecasting-evaluation")).not.toBeInTheDocument();
    const overview = container.querySelector(".dataset-detail-overview")!;
    const firstChild = overview.firstElementChild;
    expect(firstChild).toHaveClass("dataset-detail-overview__problem-summary");
    expect(firstChild?.nextElementSibling).toHaveClass("dataset-detail-overview__analytics");
  });

  it("renders no evaluation wrapper when the content is falsy", () => {
    const { container } = renderSurface({ forecastingEvaluationContent: null });
    expect(container.querySelector(".dataset-detail-overview__forecasting-evaluation")).not.toBeInTheDocument();
  });

  it("leaves S0271 inferenceAvailable tab behavior unaffected by the new slot", () => {
    renderSurface({
      forecastingEvaluationContent: <div data-testid="evaluation-slot">Evaluation content</div>,
      inferenceAvailable: false,
    });

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Overview", "Documentation"]);
    expect(screen.queryByTestId("inference-slot")).not.toBeInTheDocument();
    expect(screen.getByTestId("evaluation-slot")).toBeInTheDocument();
  });
});

// Project Spec S0200/S0221: PerformanceSummary consumes the shared
// performanceMetricMetadata module for both its performance_focus.visible_scores
// path and its normalizeEvaluation(metrics) fallback path, exposing an
// explanatory-only optimization orientation that never becomes a second
// independent direction map, never persists into public profiles (this
// component receives only presentation props), and never invents a
// direction for an unknown score. As of S0221 a monotonic (higher/lower)
// direction is exposed only as an accessible group label on the arrow pair
// -- never a visible line -- while a target-based direction still renders
// its neutral "Closer to X is better" line visibly.
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
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(score.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );
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
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(score.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Lower is better",
    );
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
    // Project Spec S0201: target-based metrics never show the monotonic
    // favorable/unfavorable arrow pair introduced for higher/lower-is-better
    // scores.
    expect(score.querySelectorAll(".performance-summary__score-orientation-arrow")).toHaveLength(0);
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
    expect(score.querySelectorAll(".performance-summary__score-orientation-arrow")).toHaveLength(0);
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
    expect(within(prAucScore).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(prAucScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );

    const rocAucScore = screen.getByText("ROC-AUC").closest(".performance-summary__score") as HTMLElement;
    expect(within(rocAucScore).queryByText("Highlighted")).not.toBeInTheDocument();
    expect(rocAucScore).toHaveTextContent("0.8402");
  });

  // Project Spec S0221: monotonic direction is expressed only as an
  // accessible group label on the arrow pair -- the individual glyphs stay
  // aria-hidden (so they are never announced a second time), and no visible
  // "Lower is better" text is rendered anywhere in the score tile, never
  // relying on color alone.
  it("expresses direction only as an accessible group label on the arrow pair, with individual glyphs aria-hidden and no visible text (log_loss 0.4207)", () => {
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
    expect(score).not.toHaveTextContent("Lower is better");
    const arrows = score.querySelector(".performance-summary__score-arrows") as HTMLElement;
    expect(arrows).toHaveAttribute("role", "img");
    expect(arrows).toHaveAttribute("aria-label", "Lower is better");
  });

  it("also applies the shared optimization metadata when rendering from normalizeEvaluation(metrics) directly, preserving existing normalized labels/values", () => {
    render(<PerformanceSummary metrics={{ auc_roc: 0.87, log_loss: 0.42 }} />);

    const rocScore = screen.getByText("AUC ROC").closest(".performance-summary__score") as HTMLElement;
    expect(within(rocScore).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(rocScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );

    const logLossScore = screen.getByText("Log Loss").closest(".performance-summary__score") as HTMLElement;
    expect(within(logLossScore).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(logLossScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Lower is better",
    );
  });

  // Project Spec S0201/S0203/S0221: a monotonic public score always shows
  // both the favorable and unfavorable direction, each carrying the correct
  // favorable/unfavorable class -- direction is explained by the arrow
  // pair's accessible group label, never by a visible "Higher/Lower is
  // better" line, a visible "favorable"/"unfavorable" word, or color alone.
  it("shows both up and down arrows, correctly classed favorable/unfavorable, for a higher-is-better score (ROC-AUC)", () => {
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
    const favorable = score.querySelector(".performance-summary__score-orientation-arrow--favorable")!;
    const unfavorable = score.querySelector(".performance-summary__score-orientation-arrow--unfavorable")!;
    expect(favorable).toHaveTextContent("↑");
    expect(unfavorable).toHaveTextContent("↓");
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(score.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );
    // "unfavorable" contains "favorable" as a substring, so this single
    // assertion proves neither visible word is rendered.
    expect(score).not.toHaveTextContent("favorable");
  });

  it("shows both up and down arrows, correctly classed favorable/unfavorable, for a lower-is-better score (Brier Score)", () => {
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
    const favorable = score.querySelector(".performance-summary__score-orientation-arrow--favorable")!;
    const unfavorable = score.querySelector(".performance-summary__score-orientation-arrow--unfavorable")!;
    expect(favorable).toHaveTextContent("↓");
    expect(unfavorable).toHaveTextContent("↑");
    expect(within(score).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(score.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Lower is better",
    );
    expect(score).not.toHaveTextContent("favorable");
  });

  // Project Spec S0203: the ↑/↓ arrow pair renders inside the same value
  // composition (the score's <dd>) as the score value itself, always in
  // ↑-then-↓ order -- not a separate side panel.
  it("renders the value followed by ↑ then ↓ in the same value composition, for both monotonic directions", () => {
    render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.8402", value_source: "canonical", order: 0 },
            { score_id: "brier_score", display_label: "Brier Score", value: "0.1394", value_source: "canonical", order: 1 },
          ],
        }}
      />,
    );

    for (const label of ["ROC-AUC", "Brier Score"]) {
      const score = screen.getByText(label).closest(".performance-summary__score") as HTMLElement;
      const valueRow = score.querySelector("dd") as HTMLElement;
      const arrows = valueRow.querySelectorAll(".performance-summary__score-orientation-arrow");
      expect(arrows).toHaveLength(2);
      const ddText = valueRow.textContent ?? "";
      expect(ddText.indexOf("↑")).toBeLessThan(ddText.indexOf("↓"));
    }
  });

  // Project Spec S0201: the score collection is a flat single-column stack --
  // every score is a direct child of .performance-summary__scores in
  // configured order, never grouped into row-pair wrapper elements.
  it("renders every visible score as a direct child of the scores list, in configured order, for a single-column stack", () => {
    const { container } = render(
      <PerformanceSummary
        metrics={{}}
        performanceFocus={{
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.84", value_source: "canonical", order: 0 },
            { score_id: "pr_auc", display_label: "PR-AUC", value: "0.64", value_source: "canonical", order: 1 },
            { score_id: "gini_coefficient", display_label: "Gini coefficient", value: "0.68", value_source: "canonical", order: 2 },
          ],
        }}
      />,
    );

    const list = container.querySelector(".performance-summary__scores")!;
    const children = Array.from(list.children);
    expect(children).toHaveLength(3);
    expect(children.every((child) => child.classList.contains("performance-summary__score"))).toBe(true);
    expect(children.map((child) => child.querySelector("dt")?.childNodes[0]?.textContent)).toEqual([
      "ROC-AUC",
      "PR-AUC",
      "Gini coefficient",
    ]);
  });
});

// Project Spec S0277: the shared Dataset Detail renderers gain a device-adaptive
// tooltip layer. jsdom cannot exercise real Recharts pointer geometry, so these
// tests assert (1) the persistent value lists / semantics survive S0277 and
// (2) the exported tooltip content builders each derive from the same
// already-validated public chart data the chart itself draws -- never a new
// metric, an inferred bound, a fabricated count, or a color-only signal.
describe("Dataset Detail device-adaptive chart tooltips (Project Spec S0277)", () => {
  const donutVisualizations = {
    charts: [
      {
        id: "target_distribution",
        type: "bar" as const,
        data: [
          { name: "No", value: 30 },
          { name: "Yes", value: 10 },
        ],
      },
    ],
  };

  const histogramVisualizations = {
    target_distribution_kind: "continuous_histogram" as const,
    charts: [
      {
        id: "target_distribution",
        type: "bar" as const,
        data: [
          { name: "[0, 10)", value: 12 },
          { name: "[10, 20)", value: 8 },
        ],
      },
    ],
  };

  const regressionVisualizations = {
    regression_diagnostics: {
      actual_vs_predicted: {
        points: [
          { actual_mean: 1, predicted_mean: 1.2, count: 5 },
          { actual_mean: 3, predicted_mean: 2.7, count: 8 },
        ],
      },
      residual_distribution: {
        bins: [
          { label: "[-1, 0)", count: 4 },
          { label: "[0, 1)", count: 9 },
        ],
      },
    },
  };

  const evaluationVisualizations = {
    forecasting_diagnostics: { forecast_horizon: 3 },
    forecasting_evaluation: {
      index_value_kind: "period",
      frequency: "monthly",
      development_boundary: { start_index: "T-03", end_index: "T-01", observation_count: 3 },
      final_holdout_boundary: { start_index: "H-01", end_index: "H-03", observation_count: 3 },
      evaluation: {
        split_name: "final_holdout",
        evaluation_count: 1,
        model_frozen_before_open: true,
        forecast_generated_before_target_open: true,
      },
      points: [
        { time_index: "H-01", actual: 10, forecast: 9 },
        { time_index: "H-02", actual: 12, forecast: 11 },
        { time_index: "H-03", actual: 11, forecast: 12 },
      ],
    },
  };

  const v7ForecastingDiagnostics = {
    forecasting_diagnostics: {
      forecast_horizon: 2,
      frequency: "monthly",
      seasonal_profile: {
        seasonal_period: 2,
        points: [
          { season_position: 0, mean_target: 5, observation_count: 4 },
          { season_position: 1, mean_target: 7, observation_count: 4 },
        ],
      },
      backtesting_fold_metric: {
        metric_id: "mae",
        direction: "lower_is_better",
        points: [
          { fold_index: 1, forecast_origin: "L-1", value: 8.11 },
          { fold_index: 2, forecast_origin: "L-2", value: 8.22 },
        ],
      },
      horizon_mae: {
        points: [
          { horizon_step: 1, mae: 7.01 },
          { horizon_step: 2, mae: 7.02 },
        ],
      },
      metric_diagnostics: {
        metrics: [
          {
            metric_id: "mae",
            direction: "lower_is_better",
            backtesting_by_origin: {
              points: [
                { fold_index: 0, forecast_origin: "O-1", value: 1.11 },
                { fold_index: 1, forecast_origin: "O-2", value: 1.22 },
              ],
            },
            by_horizon: {
              points: [
                { horizon_step: 1, value: 1.01, observation_count: 3 },
                { horizon_step: 2, value: 1.02, observation_count: 3 },
              ],
            },
          },
          {
            metric_id: "rmse",
            direction: "lower_is_better",
            backtesting_by_origin: {
              points: [
                { fold_index: 0, forecast_origin: "O-1", value: 2.71 },
                { fold_index: 1, forecast_origin: "O-2", value: 2.82 },
              ],
            },
            by_horizon: {
              points: [
                { horizon_step: 1, value: 2.01, observation_count: 3 },
                { horizon_step: 2, value: 2.02, observation_count: 3 },
              ],
            },
          },
        ],
      },
    },
  };

  const legacyForecastingDiagnostics = {
    forecasting_diagnostics: {
      forecast_horizon: 2,
      frequency: "monthly",
      seasonal_profile: {
        seasonal_period: 2,
        points: [
          { season_position: 0, mean_target: 5 },
          { season_position: 1, mean_target: 7 },
        ],
      },
      backtesting_fold_metric: {
        metric_id: "mae",
        direction: "lower_is_better",
        points: [
          { fold_index: 1, forecast_origin: "L-1", value: 8.11 },
          { fold_index: 2, forecast_origin: "L-2", value: 8.22 },
        ],
      },
      horizon_mae: {
        points: [
          { horizon_step: 1, mae: 7.01 },
          { horizon_step: 2, mae: 7.02 },
        ],
      },
    },
  };

  it("keeps the existing persistent value lists rendered for every shared renderer", () => {
    const { unmount: unmountDonut } = render(<TargetDistribution visualizations={donutVisualizations} />);
    expect(screen.getByText("(30)")).toBeInTheDocument();
    expect(screen.getByText("(10)")).toBeInTheDocument();
    unmountDonut();

    const { unmount: unmountRegression } = render(
      <RegressionDiagnostics visualizations={regressionVisualizations} />,
    );
    expect(screen.getByText("n=5")).toBeInTheDocument();
    expect(screen.getByText("[0, 1)")).toBeInTheDocument();
    unmountRegression();

    render(<ForecastingDiagnostics visualizations={v7ForecastingDiagnostics} highlightedScoreId="rmse" />);
    expect(screen.getByText("RMSE: 2.71")).toBeInTheDocument();
    expect(screen.getByText("Position 0")).toBeInTheDocument();
  });

  it("Target Distribution donut tooltip exposes category/count/percentage from the existing percentage authority", () => {
    // 30 / (30 + 10) -> the same formatPercent(value, total) the legend uses.
    expect(buildDonutTooltipModel(40, { name: "No", value: 30 })).toEqual({
      title: "No",
      rows: [
        { label: "Category", value: "No" },
        { label: "Count", value: "30" },
        { label: "Share", value: "75.0%" },
      ],
    });
    expect(buildDonutTooltipModel(0, { name: "No", value: 0 })).toBeNull();
  });

  it("continuous Target Distribution tooltip exposes bin/count without inferring numeric bounds", () => {
    const model = buildHistogramTooltipModel({ name: "[10, 20)", value: 8 });
    expect(model?.rows).toEqual([
      { label: "Bin", value: "[10, 20)" },
      { label: "Count", value: "8" },
    ]);
    // The label is passed through verbatim -- no parsed 10 / 20 bound appears.
    expect(model?.rows.some((row) => row.value === "10" || row.value === "20")).toBe(false);
  });

  it("Actual vs Predicted tooltip exposes actual/predicted/count and never treats the identity line as an observation", () => {
    expect(
      buildActualVsPredictedTooltipModel({ datum: { actual: 1, predicted: 1.2, count: 5 }, items: [] }),
    ).toEqual({
      title: "Observation",
      rows: [
        { label: "Actual", value: "1" },
        { label: "Predicted", value: "1.2" },
        { label: "Observations", value: "5" },
      ],
    });
    // An identity-reference-line datum carries no count -> no tooltip.
    expect(
      buildActualVsPredictedTooltipModel({
        datum: { actual: 2, predicted: 2 },
        items: [{ payload: { actual: 2, predicted: 2 } }],
      }),
    ).toBeNull();
  });

  it("Residual Distribution tooltip exposes residual-bin/count without a new statistic", () => {
    expect(buildResidualTooltipModel({ label: "[0, 1)", count: 9 })).toEqual({
      title: "Residual bin",
      rows: [
        { label: "Residual bin", value: "[0, 1)" },
        { label: "Count", value: "9" },
      ],
    });
  });

  it("Forecast vs Actual tooltip exposes period/actual/forecast and computes no error metric", () => {
    const model = buildForecastVsActualTooltipModel({ label: "H-02", actual: 12, forecast: 11 });
    expect(model?.rows).toEqual([
      { label: "Period", value: "H-02" },
      { label: "Actual", value: "12" },
      { label: "Forecast", value: "11" },
    ]);
    // No absolute/squared error, MAE, or RMSE row is synthesized.
    expect(model?.rows).toHaveLength(3);
    render(<ForecastingEvaluationOverview visualizations={evaluationVisualizations} />);
    expect(screen.getByText("Actual 10 · Forecast 9")).toBeInTheDocument();
  });

  it("v7 highlighted RMSE diagnostics use one selected metric identity for the chart heading, legend, and tooltip", () => {
    render(<ForecastingDiagnostics visualizations={v7ForecastingDiagnostics} highlightedScoreId="rmse" />);
    expect(screen.getByRole("heading", { name: "Backtesting by Origin — RMSE" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Horizon RMSE" })).toBeInTheDocument();

    const selection = resolveMetricSelection(v7ForecastingDiagnostics.forecasting_diagnostics, "rmse");
    expect(selection.kind).toBe("selected");
    if (selection.kind !== "selected") {
      throw new Error("expected a selected metric");
    }
    expect(selection.metric.label).toBe("RMSE");
    expect(selection.metric.byHorizon[0].observationCount).toBe(3);

    expect(buildBacktestingTooltipModel(selection.metric.label, { label: "O-1", value: 2.71 })?.rows).toEqual([
      { label: "Forecast origin", value: "O-1" },
      { label: "RMSE", value: "2.71" },
    ]);
    expect(
      buildHorizonTooltipModel(selection.metric.label, { label: "h+1", value: 2.01, observationCount: 3 })?.rows,
    ).toEqual([
      { label: "Horizon step", value: "h+1" },
      { label: "RMSE", value: "2.01" },
      { label: "Observations", value: "3" },
    ]);
  });

  it("legacy Horizon MAE stays MAE, is not relabeled, and never fabricates an observation count", () => {
    render(<ForecastingDiagnostics visualizations={legacyForecastingDiagnostics} />);
    expect(screen.getByRole("heading", { name: "Horizon MAE" })).toBeInTheDocument();

    const model = buildHorizonTooltipModel("MAE", { label: "h+1", value: 7.01 });
    expect(model?.rows).toEqual([
      { label: "Horizon step", value: "h+1" },
      { label: "MAE", value: "7.01" },
    ]);
    expect(model?.rows.some((row) => row.label === "Observations")).toBe(false);
  });

  it("Seasonal Profile tooltip exposes numeric season position and mean target, with observation count only when public", () => {
    expect(buildSeasonalProfileTooltipModel({ label: "Position 0", mean_target: 5, observationCount: 4 })?.rows).toEqual([
      { label: "Season position", value: "Position 0" },
      { label: "Mean target", value: "5" },
      { label: "Observations", value: "4" },
    ]);
    // A historical seasonal point without a public count renders without one --
    // never an inferred month name, never a fabricated count.
    const withoutCount = buildSeasonalProfileTooltipModel({ label: "Position 0", mean_target: 5 });
    expect(withoutCount?.rows).toHaveLength(2);
    expect(withoutCount?.rows[0].value).toBe("Position 0");
  });

  it("does not turn Feature Importance or Confusion Matrix into tooltip-dependent surfaces", () => {
    const featureVisualizations = {
      charts: [{ id: "feature_importance", type: "bar" as const, data: [{ name: "tenure", value: 0.7 }] }],
    };
    const { unmount } = render(<FeatureImportance visualizations={featureVisualizations} />);
    expect(screen.getByText("tenure")).toBeInTheDocument();
    expect(document.querySelector(".dataset-chart-tooltip")).not.toBeInTheDocument();
    unmount();

    render(
      <ConfusionMatrix
        visualizations={{
          confusion_matrix: {
            ordered_class_ids: ["a", "b", "c"],
            matrix: [
              [1, 0, 0],
              [0, 1, 0],
              [0, 0, 1],
            ],
            row_axis: "true_class",
            column_axis: "predicted_class",
          },
        }}
      />,
    );
    expect(screen.getByRole("table", { name: "Confusion matrix" })).toBeInTheDocument();
    expect(document.querySelector(".dataset-chart-tooltip")).not.toBeInTheDocument();
  });

  it("renders the shared charts without crashing when pointer-capability detection is unavailable", () => {
    const originalMatchMedia = window.matchMedia;
    // @ts-expect-error -- deliberately removing the API to exercise the fallback
    delete window.matchMedia;
    try {
      expect(resolveChartInteractionMode()).toBe("click");
      render(<TargetDistribution visualizations={donutVisualizations} />);
      expect(screen.getByText("(30)")).toBeInTheDocument();
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });
});
