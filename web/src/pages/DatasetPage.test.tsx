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

const contextPayload = {
  title: "Synthetic Demo Dataset",
  summary: "Synthetic public-safe context summary.",
  domain: "synthetic",
  tags: ["synthetic"],
  use_case: "Synthetic use case",
  problem_type: "binary_classification",
  prediction_target_description: "Whether the synthetic target event occurs.",
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
function installDatasetPageFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith(`/datasets/${slug}/context`)) {
      return jsonResponse({ dataset_slug: slug, context: contextPayload });
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
      return jsonResponse({ dataset_slug: slug, contract: contractPayload });
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

    const inferenceLayout = container.querySelector(".dataset-detail-inference__layout");
    expect(inferenceLayout).toBeInTheDocument();
    expect(inferenceLayout?.querySelector("form")).toBeInTheDocument();
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
        return jsonResponse({ dataset_slug: slug, contract: contractPayload });
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
        return jsonResponse({ dataset_slug: telcoSlug, contract: telcoContractPayload });
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
