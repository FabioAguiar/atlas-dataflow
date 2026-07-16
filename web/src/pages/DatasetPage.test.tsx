import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./DatasetPage";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

function jsonResponse(body: unknown, status = 200): MockResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

// Synthetic, non-Telco/Bank dataset_slug proving DatasetPage's rendering
// does not depend on the seeded telco-customer-churn/bank-marketing
// examples (decision-05).
const slug = "synthetic-demo-dataset";

const datasetMetadata = {
  dataset_slug: slug,
  title: "Synthetic Demo Dataset",
  summary: "A synthetic, non-Telco/Bank dataset used only for this proof test.",
  domain: "synthetic",
  visibility: "public",
  tags: ["synthetic"],
};

// Project Spec S0112: shared fixtures for the real /contract result_contract
// and /context result_card projections, used across this file's mocks so
// InferenceForm always receives a real (available) binary result contract.
const resultContractAvailable = {
  status: "available" as const,
  semantics: {
    schema_version: "binary-result-semantics.v1",
    problem_type: "binary_classification" as const,
    result_schema_version: "binary-classification-result.v1" as const,
    primary_output: "positive_class_probability" as const,
    positive_class: { class_id: "Yes", event_label: "Churn" },
    negative_class: { class_id: "No" },
    decision: { threshold: 0.5 },
    interpretation: {
      preset: "risk",
      bands: [
        { band_id: "low", lower_bound: 0, upper_bound: 0.35 },
        { band_id: "medium", lower_bound: 0.35, upper_bound: 0.65 },
        { band_id: "high", lower_bound: 0.65, upper_bound: 1.0 },
      ],
    },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
  },
};

const resultCardPresentation = {
  schema_version: "binary-result-presentation.v1",
  positive_class_probability_label: "Churn probability",
  predicted_outcome_label: "Predicted outcome",
  positive_outcome_copy: "Likely to churn",
  negative_outcome_copy: "Unlikely to churn",
  model_section_label: "Model",
  interpretation: {
    preset: "risk",
    labels: { high: "High risk", medium: "Medium risk", low: "Low risk" },
  },
};

const contextPayload = {
  title: "Synthetic Demo Dataset",
  summary: "Synthetic public-safe context summary.",
  domain: "synthetic",
  tags: ["synthetic"],
  use_case: "Synthetic use case",
  problem_type: "binary_classification",
  prediction_target_description: "Whether the synthetic target event occurs.",
  result_card: resultCardPresentation,
};

type ContextPayloadFixture = typeof contextPayload & {
  theme_preset?: string | null;
  performance_focus?: {
    focus_id: "overall_discrimination" | "positive_class_detection" | "balanced_classification" | "probability_quality" | "operational_decision";
    highlighted_score_id: string;
    visible_scores: Array<{
      score_id: string;
      display_label: string;
      value: string;
      value_source: "canonical" | "manual";
      order: number;
    }>;
  } | null;
};

const metricsPayload = {
  auc_roc: 0.87,
  precision: 0.8,
  recall: 0.75,
  f1_score: 0.77,
  evaluation: { sample_size: 1234 },
};

const modelCardPayload = {
  content: "# Synthetic Model Card\n\nDescribes the synthetic demo model.",
  format: "markdown" as const,
};

const visualizationsPayload = {
  charts: [],
};

const contractPayload = {
  schema_version: "1.0.0",
  features: [
    {
      name: "synthetic_feature",
      label: "Synthetic Feature",
      input_type: "number" as const,
      optional: true,
      display_order: 1,
    },
  ],
};

const viewsPayload = {
  dataset_slug: slug,
  views: [],
};

// Mirrors DatasetPage.tsx's own seven independent per-section fetches
// (/datasets/{slug}, /context, /metrics, /model-card, /visualizations,
// /contract, /views); each endpoint's mocked shape mirrors this handoff's
// grounding of the page's own response-parsing code.
function installDatasetPageFetchMock(context: ContextPayloadFixture = contextPayload) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith(`/datasets/${slug}/context`)) {
      return jsonResponse({ dataset_slug: slug, context });
    }
    if (url.endsWith(`/datasets/${slug}/metrics`)) {
      return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
    }
    if (url.endsWith(`/datasets/${slug}/model-card`)) {
      return jsonResponse({ dataset_slug: slug, model_card: modelCardPayload });
    }
    if (url.endsWith(`/datasets/${slug}/visualizations`)) {
      return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
    }
    if (url.endsWith(`/datasets/${slug}/contract`)) {
      return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
    }
    if (url.endsWith(`/datasets/${slug}/views`)) {
      return jsonResponse(viewsPayload);
    }
    if (url.endsWith(`/datasets/${slug}`)) {
      return jsonResponse(datasetMetadata);
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderDatasetPage() {
  return render(
    <MemoryRouter initialEntries={[`/dataset/${slug}`]}>
      <Routes>
        <Route path="/dataset/:slug" element={<DatasetPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DatasetPage synthetic-slug rendering", () => {
  it("hydrates the published detail theme and falls back for an unsupported context value", async () => {
    installDatasetPageFetchMock({ ...contextPayload, theme_preset: "crimson-night" });
    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    const detail = container.querySelector<HTMLElement>(".dataset-detail")!;
    expect(detail).toHaveAttribute("data-theme-preset", "crimson-night");
    expect(detail.style.getPropertyValue("--dataset-theme-canvas")).toBe("#160b17");

    cleanup();
    installDatasetPageFetchMock({ ...contextPayload, theme_preset: "custom-rainbow" });
    const fallbackRender = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(fallbackRender.container.querySelector(".dataset-detail")).toHaveAttribute("data-theme-preset", "atlas-green");
  });

  it("renders the correct title, metadata, and badge for a synthetic, non-Telco/Bank dataset_slug", async () => {
    installDatasetPageFetchMock();

    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("binary_classification")).toBeInTheDocument();
    expect(screen.getByText("Whether the synthetic target event occurs.")).toBeInTheDocument();
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    expect(screen.queryByText(/telco/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/bank/i)).not.toBeInTheDocument();
  });

  it("shows 'Pending' for Source and Release when context has no curated values (M39-03)", async () => {
    installDatasetPageFetchMock();

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    const pendingValues = screen.getAllByText("Pending");
    expect(pendingValues.length).toBeGreaterThanOrEqual(2);
  });

  it("renders published Performance focus scores in configured order and highlight", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      performance_focus: {
        focus_id: "positive_class_detection" as const,
        highlighted_score_id: "recall",
        visible_scores: [
          { score_id: "precision", display_label: "Precision", value: "0.679", value_source: "canonical" as const, order: 2 },
          { score_id: "recall", display_label: "Recall", value: "57.4%", value_source: "manual" as const, order: 1 },
        ],
      },
    });

    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(screen.getByText("Positive-class detection")).toBeInTheDocument();
    expect(screen.getByText("57.4%")).toBeInTheDocument();
    expect(screen.queryByText("AUC ROC")).not.toBeInTheDocument();
    const scores = Array.from(container.querySelectorAll(".performance-summary__score dt"));
    expect(scores.map((score) => score.textContent)).toEqual(["RecallHighlighted", "Precision"]);
  });

  it("switches from Overview to Inference and renders the split inference layout", async () => {
    installDatasetPageFetchMock();

    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const inferenceTab = screen.getByRole("tab", { name: "Inference" });

    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Synthetic public-safe context summary.")).toBeInTheDocument();

    fireEvent.click(inferenceTab);

    expect(inferenceTab).toHaveAttribute("aria-selected", "true");
    expect(overviewTab).toHaveAttribute("aria-selected", "false");
    expect(await screen.findByText("Synthetic Feature")).toBeInTheDocument();

    // Project Spec S0112: the shared public inference surface (form panel +
    // Result Card) is now owned by InferenceForm itself, not a page-specific
    // sticky/resize DOM heuristic.
    const inferenceSurface = container.querySelector(".public-inference-surface");
    expect(inferenceSurface).toBeInTheDocument();
    expect(inferenceSurface?.querySelector("form")).toBeInTheDocument();
    expect(screen.getByLabelText("Prediction result")).toBeInTheDocument();
  });
});

// Project Spec S0110: DatasetPage resolves the published bound predict
// view's customization submit label using
// customization -> legacy published profile -> "Submit" precedence, and
// never auto-selects an arbitrary view when no binding exists.
describe("DatasetPage bound predict view submit-label resolution (Project Spec S0110)", () => {
  const boundViewId = "churn-risk-overview";

  function installBoundViewFetchMock(
    options: {
      boundPredictViewId?: string | null;
      legacySubmitButtonLabel?: string | null;
      customizationSubmitButtonLabel?: string;
      customizationStatus?: number;
    } = {},
  ) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: {
            ...contextPayload,
            bound_predict_view_id: options.boundPredictViewId ?? null,
            legacy_submit_button_label: options.legacySubmitButtonLabel ?? null,
          },
        });
      }
      if (url.endsWith(`/datasets/${slug}/views/${boundViewId}/customization`)) {
        if (options.customizationStatus) {
          return jsonResponse({}, options.customizationStatus);
        }
        if (options.customizationSubmitButtonLabel === undefined) {
          return jsonResponse({}, 404);
        }
        return jsonResponse({
          schema_version: "1.0.0",
          view_id: boundViewId,
          dataset_slug: slug,
          field_hints: [],
          groups: [],
          view_copy: { submit_button_label: options.customizationSubmitButtonLabel },
        });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/model-card`)) {
        return jsonResponse({ dataset_slug: slug, model_card: modelCardPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}/views`)) {
        return jsonResponse(viewsPayload);
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  async function openInferenceTab() {
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");
  }

  it("renders the bound view's customization submit label when both customization and legacy copy exist", async () => {
    installBoundViewFetchMock({
      boundPredictViewId: boundViewId,
      legacySubmitButtonLabel: "Legacy Run",
      customizationSubmitButtonLabel: "Estimate Churn Risk",
    });
    renderDatasetPage();
    await openInferenceTab();

    expect(screen.getByRole("button", { name: "Estimate Churn Risk" })).toBeInTheDocument();
  });

  it("falls back to the legacy published label when the bound view has no customization value yet", async () => {
    installBoundViewFetchMock({
      boundPredictViewId: boundViewId,
      legacySubmitButtonLabel: "Legacy Run",
      customizationSubmitButtonLabel: "",
    });
    renderDatasetPage();
    await openInferenceTab();

    expect(screen.getByRole("button", { name: "Legacy Run" })).toBeInTheDocument();
  });

  it('falls back to "Submit" when no bound view, customization, or legacy copy exists', async () => {
    installBoundViewFetchMock();
    renderDatasetPage();
    await openInferenceTab();

    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
  });

  it("does not select an arbitrary view when no bound view is published, even though eligible views exist", async () => {
    const fetchMock = installBoundViewFetchMock({ legacySubmitButtonLabel: "Legacy Run" });
    renderDatasetPage();
    await openInferenceTab();

    // Falls back straight to the legacy label -- no
    // /views/{id}/customization request is ever sent for an unbound
    // dataset, proving no arbitrary first view was silently selected.
    expect(screen.getByRole("button", { name: "Legacy Run" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/customization"))).toBe(false);
  });

  it("keeps the form usable and falls back to legacy copy when the bound view's customization transport fails", async () => {
    installBoundViewFetchMock({
      boundPredictViewId: boundViewId,
      legacySubmitButtonLabel: "Legacy Run",
      customizationStatus: 503,
    });
    renderDatasetPage();
    await openInferenceTab();

    expect(screen.getByRole("button", { name: "Legacy Run" })).toBeInTheDocument();
  });
});

describe("DatasetPage curated Source/Release/highlight rendering (M39-03)", () => {
  it("renders real Source/Release metadata and the curated metric highlight when context provides them", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: {
            ...contextPayload,
            source_name: "Original Source Org",
            release_date_label: "01/07/2026",
            primary_metric_key: "precision",
          },
        });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/model-card`)) {
        return jsonResponse({ dataset_slug: slug, model_card: modelCardPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}/views`)) {
        return jsonResponse(viewsPayload);
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Original Source Org")).toBeInTheDocument();
    expect(screen.getByText("01/07/2026")).toBeInTheDocument();

    // PerformanceSummary emphasizes "Precision" (primary_metric_key)
    // instead of its own default (AUC ROC) when context provides it.
    const precisionRow = screen.getByText("Precision").closest("div");
    expect(precisionRow).not.toBeNull();
    expect(precisionRow?.textContent).toContain("Highlighted");

    const aucRocRow = screen.getByText("AUC ROC").closest("div");
    expect(aucRocRow?.textContent).not.toContain("Highlighted");
  });
});

// S0017: real-shaped telco-customer-churn payloads (grounded in the actual
// published releases/release-20260619-001 public-context.json/metrics.json
// content, plus mocked target-distribution/feature-importance chart data
// carrying the spec's reduced Telco facts) must render from the API
// responses alone, with no hardcoded Telco copy in DatasetPage.tsx itself.
describe("DatasetPage Telco-like ready payload rendering (S0017)", () => {
  const telcoSlug = "telco-customer-churn";

  const telcoDatasetMetadata = {
    dataset_slug: telcoSlug,
    title: "Telco Customer Churn",
    summary: "Customer churn prediction dataset for a telecommunications provider.",
    domain: "telco",
    visibility: "public",
    tags: ["telco", "churn", "classification"],
  };

  // Matches releases/release-20260619-001/public-context.json's real
  // published fields for this dataset.
  const telcoContextPayload = {
    title: "Telco Customer Churn",
    summary: "A binary classification dataset for demonstrating customer churn prediction in the Atlas DataFlow first real publication cycle.",
    domain: "telecommunications",
    tags: ["churn", "binary-classification", "telecommunications", "customer-behavior"],
    problem_type: "binary_classification",
    prediction_target_description: "Whether a customer will cancel their service (churn).",
    result_card: resultCardPresentation,
  };

  // Matches releases/release-20260619-001/metrics/metrics.json's real
  // published evaluation block for this dataset.
  const telcoMetricsPayload = {
    accuracy: 0.802,
    precision: 0.679,
    recall: 0.574,
    f1_score: 0.622,
    auc_roc: 0.847,
    evaluation: { sample_size: 1408 },
  };

  const telcoModelCardPayload = {
    content: JSON.stringify({
      model_summary: "Binary classification model predicting customer churn for a telecommunications company.",
      problem_type: "binary_classification",
      prediction_target: "customer_churn",
    }),
    format: "markdown" as const,
  };

  // Reduced Telco target-distribution/feature-importance facts from the
  // spec's own verifiable_objective section (No = 5174, Yes = 1869;
  // TotalCharges blank-value note), delivered as mocked chart data -- these
  // values only ever exist in this test's mocked API payload, never as
  // production constants in DatasetPage.tsx or a committed data artifact.
  const telcoVisualizationsPayload = {
    charts: [
      {
        id: "target_distribution",
        title: "target distribution",
        type: "bar" as const,
        x_label: "Churn",
        y_label: "Customers",
        data: [
          { name: "No", value: 5174 },
          { name: "Yes", value: 1869 },
        ],
      },
      {
        id: "feature_importance",
        title: "feature importance",
        type: "bar" as const,
        x_label: "Feature",
        y_label: "Importance",
        data: [
          { name: "tenure", value: 0.31 },
          { name: "TotalCharges", value: 0.22 },
          { name: "Contract", value: 0.18 },
        ],
      },
    ],
  };

  const telcoContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "tenure", label: "Tenure (months)", input_type: "number" as const, optional: false, display_order: 1 },
      {
        name: "monthly_charges",
        label: "Monthly Charges (USD)",
        input_type: "number" as const,
        optional: false,
        display_order: 2,
      },
      {
        name: "total_charges",
        label: "Total Charges (USD)",
        input_type: "number" as const,
        optional: false,
        display_order: 3,
        // TotalCharges' real, already-observed preparation caveat (11 blank
        // string values in the raw CSV) surfaced as public-safe field
        // guidance rather than silently presented as clean numeric input.
        description: "Total amount charged to the customer in USD. A small number of new accounts may show a blank value.",
      },
    ],
  };

  const telcoViewsPayload = {
    dataset_slug: telcoSlug,
    views: [{ view_id: "churn-risk-overview", display: { title: "Churn risk overview" } }],
  };

  function installTelcoFetchMock(overrides: { visualizationsStatus?: number } = {}) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${telcoSlug}/context`)) {
        return jsonResponse({ dataset_slug: telcoSlug, context: telcoContextPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/metrics`)) {
        return jsonResponse({ dataset_slug: telcoSlug, metrics: telcoMetricsPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/model-card`)) {
        return jsonResponse({ dataset_slug: telcoSlug, model_card: telcoModelCardPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/visualizations`)) {
        if (overrides.visualizationsStatus) {
          return jsonResponse({}, overrides.visualizationsStatus);
        }
        return jsonResponse({ dataset_slug: telcoSlug, visualizations: telcoVisualizationsPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/contract`)) {
        return jsonResponse({
          dataset_slug: telcoSlug,
          contract: telcoContractPayload,
          result_contract: resultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/views`)) {
        return jsonResponse(telcoViewsPayload);
      }
      if (url.endsWith(`/datasets/${telcoSlug}`)) {
        return jsonResponse(telcoDatasetMetadata);
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  function renderTelcoDatasetPage() {
    return render(
      <MemoryRouter initialEntries={[`/dataset/${telcoSlug}`]}>
        <Routes>
          <Route path="/dataset/:slug" element={<DatasetPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("renders public context, metrics, model card, contract, and target distribution/feature importance from real-shaped API payloads", async () => {
    installTelcoFetchMock();

    renderTelcoDatasetPage();

    expect(await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("binary_classification")).toBeInTheDocument();
    expect(screen.getByText("Whether a customer will cancel their service (churn).")).toBeInTheDocument();
    // Instances metadata reads metrics.evaluation.sample_size (the real
    // release's held-out test split size), not the full 7,043-row dataset.
    expect(screen.getByText("1,408")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    expect(await screen.findByText("Tenure (months)")).toBeInTheDocument();
    expect(screen.getByText("Total Charges (USD)")).toBeInTheDocument();

    // recharts' ResponsiveContainer never resolves a non-zero width in jsdom
    // (no real layout engine), so it renders an empty measuring div here --
    // there is no tick/bar text to assert on. This still proves the "ready"
    // branch (real chart present) was chosen over the empty-state branch;
    // the No=5174/Yes=1869 values live in the mocked payload above, per the
    // acceptance criteria's "mocked Telco payloads include realistic reduced
    // values" requirement, not in an unrenderable chart DOM assertion.
    const targetDistributionChart = await screen.findByLabelText("target distribution");
    expect(targetDistributionChart).toBeInTheDocument();
    const featureImportanceChart = screen.getByLabelText("feature importance");
    expect(featureImportanceChart).toBeInTheDocument();
  });

  it("shows an explicit unavailable state for target distribution and feature importance when the visualizations endpoint fails, without blocking the rest of the page", async () => {
    // Grounded in the real repository state: the currently active Telco
    // release (releases/release-20260619-001) has no visualizations
    // artifact declared in its manifest at all, so
    // api/public_visualizations_loader.py's load_public_visualizations
    // genuinely raises PublicVisualizationsUnavailableError for this
    // dataset today -- this is not a hypothetical failure mode.
    installTelcoFetchMock({ visualizationsStatus: 503 });

    renderTelcoDatasetPage();

    expect(await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 })).toBeInTheDocument();
    // Metrics and model card remain available and rendered even though
    // visualizations failed independently -- one section's unavailability
    // must not block the rest of the page.
    expect(screen.getByText("1,408")).toBeInTheDocument();

    expect((await screen.findAllByText("Visualization not generated")).length).toBe(2);
    expect(screen.getAllByText("This visualization has not been generated yet for this release.")).toHaveLength(2);
    expect(screen.queryByLabelText("target distribution")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("feature importance")).not.toBeInTheDocument();
  });
});
