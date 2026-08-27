import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./DatasetPage";
import type { ResultPresentation } from "../components/ResultCard/types";

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

// S0214 regression fixture: DatasetPage forwards this available multiclass
// contract to the shared InferenceForm instead of adapting it to unavailable.
const multiclassResultContractAvailable = {
  status: "available" as const,
  semantics: {
    schema_version: "multiclass-result-semantics.v1" as const,
    problem_type: "multiclass_classification" as const,
    result_schema_version: "multiclass-classification-result.v1" as const,
    classes: ["a", "b", "c"].map((class_id) => ({ class_id, display_label: class_id.toUpperCase() })),
    primary_output: "predicted_class" as const,
    probability_output: "class_probabilities" as const,
    decision: { strategy: "argmax" as const },
    model_descriptor: { model_family: "random_forest", display_name: "Forest" },
  },
};

describe("DatasetPage multiclass contract fixture (S0214)", () => {
  it("retains release-derived multiclass identity and governed class order", () => {
    expect(multiclassResultContractAvailable.semantics.problem_type).toBe("multiclass_classification");
    expect(multiclassResultContractAvailable.semantics.classes.map((entry) => entry.class_id)).toEqual(["a", "b", "c"]);
  });
});

const resultCardPresentation = {
  schema_version: "binary-result-presentation.v1" as const,
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

// Project Spec S0250: result_card is omitted from the typeof-contextPayload
// base and re-declared below as the full ResultPresentation union so a
// forecasting test fixture can override it with a forecasting presentation
// shape instead of being pinned to contextPayload's own binary shape.
type ContextPayloadFixture = Omit<typeof contextPayload, "result_card"> & {
  result_card?: ResultPresentation | null;
  description?: string;
  display_title?: string | null;
  display_subtitle?: string | null;
  short_description?: string | null;
  problem_summary_title?: string | null;
  problem_summary_body?: string | null;
  source_name?: string | null;
  source_url?: string | null;
  release_date_label?: string | null;
  date_format?: "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd" | null;
  canonical_name_fallback?: boolean | null;
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
  documentation?: { format: "markdown"; content: string } | null;
};

const metricsPayload = {
  auc_roc: 0.87,
  precision: 0.8,
  recall: 0.75,
  f1_score: 0.77,
  evaluation: { sample_size: 1234 },
};

// Project Spec S0205: dataset_statistics.instance_count is the bounded
// public visualizations projection's own Instances authority -- kept on
// this shared fixture so every existing test using it still renders a
// stable Instances value without individually opting in.
const visualizationsPayload = {
  charts: [],
  dataset_statistics: { instance_count: 1234 },
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

// Mirrors DatasetPage.tsx's own five independent per-section fetches
// (/datasets/{slug}, /context, /metrics, /visualizations, /contract) --
// Project Spec S0119 removed the default route's /model-card and /views
// list requests entirely.
function installDatasetPageFetchMock(
  context: ContextPayloadFixture = contextPayload,
  metadata: typeof datasetMetadata & {
    display_title?: string | null;
    display_subtitle?: string | null;
    short_description?: string | null;
  } = datasetMetadata,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith(`/datasets/${slug}/context`)) {
      return jsonResponse({ dataset_slug: slug, context });
    }
    if (url.endsWith(`/datasets/${slug}/metrics`)) {
      return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
    }
    if (url.endsWith(`/datasets/${slug}/visualizations`)) {
      return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
    }
    if (url.endsWith(`/datasets/${slug}/contract`)) {
      return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
    }
    if (url.endsWith(`/datasets/${slug}`)) {
      return jsonResponse(metadata);
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

// Mocks only the primary /datasets/{slug} route with the given error
// envelope; any other request is treated as a bug (an auxiliary request
// fired even though the primary route never reached "ready").
function installDatasetPageErrorFetchMock(errorBody: unknown, status: number) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith(`/datasets/${slug}`)) {
      return jsonResponse(errorBody, status);
    }
    throw new Error(`unexpected auxiliary fetch for a non-ready primary state: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DatasetPage access states (Project Spec S0117)", () => {
  it("renders the shared maintenance state and fires no auxiliary requests", async () => {
    const fetchMock = installDatasetPageErrorFetchMock(
      {
        error_type: "dataset_maintenance",
        error_code: "DATASET_MAINTENANCE",
        message: "The requested dataset page is temporarily unavailable.",
      },
      503,
    );

    renderDatasetPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset page under maintenance" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("This dataset page is temporarily unavailable. Please try again later."),
    ).toBeInTheDocument();
    // Maintenance must expose no dataset title/summary.
    expect(screen.queryByText(datasetMetadata.title)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders the shared not-found state and fires no auxiliary requests", async () => {
    const fetchMock = installDatasetPageErrorFetchMock(
      { error_type: "dataset_not_found", error_code: "DATASET_NOT_FOUND", message: "The requested dataset is not available." },
      404,
    );

    renderDatasetPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Dataset not found" })).toBeInTheDocument();
    expect(
      screen.getByText("The dataset or link you tried to access does not exist."),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("classifies a registry/release failure as unavailable using error_code, never status alone", async () => {
    const fetchMock = installDatasetPageErrorFetchMock(
      { error_type: "registry_unavailable", error_code: "REGISTRY_UNAVAILABLE", message: "The registry is not currently available." },
      503,
    );

    renderDatasetPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders unavailable for a malformed (non-JSON) error body instead of crashing or misclassifying", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}`)) {
        return {
          ok: false,
          status: 503,
          json: async () => {
            throw new Error("not valid json");
          },
        };
      }
      throw new Error(`unexpected auxiliary fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).toBeInTheDocument();
  });

  it("fires auxiliary requests only after the primary route reaches ready", async () => {
    const fetchMock = installDatasetPageFetchMock();

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/context`)),
      ).toBe(true);
    });
  });

  it("clears prior content immediately on a slug switch and never flashes a not-found state", async () => {
    const slugA = slug;
    const slugB = "another-synthetic-dataset";
    const datasetBMetadata = { ...datasetMetadata, dataset_slug: slugB, title: "Another Synthetic Dataset" };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const s of [slugA, slugB]) {
        // Give each slug's context a distinct title so the assertions below
        // can tell whether the primary payload's own title (state.data.title)
        // is what's rendering, not a stale/shared context fixture.
        if (url.endsWith(`/datasets/${s}/context`))
          return jsonResponse({ dataset_slug: s, context: { ...contextPayload, title: s === slugA ? datasetMetadata.title : datasetBMetadata.title } });
        if (url.endsWith(`/datasets/${s}/metrics`)) return jsonResponse({ dataset_slug: s, metrics: metricsPayload });
        if (url.endsWith(`/datasets/${s}/visualizations`))
          return jsonResponse({ dataset_slug: s, visualizations: visualizationsPayload });
        if (url.endsWith(`/datasets/${s}/contract`))
          return jsonResponse({ dataset_slug: s, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slugA}`)) return jsonResponse(datasetMetadata);
      if (url.endsWith(`/datasets/${slugB}`)) return jsonResponse(datasetBMetadata);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/dataset/${slugA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug"
            element={
              <>
                <Link to={`/dataset/${slugB}`}>Go to B</Link>
                <DatasetPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("link", { name: "Go to B" }));

    // Immediately after the switch (before the new response resolves) the
    // page must not show the old dataset's heading or flash a false
    // not-found state.
    expect(screen.queryByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dataset not found" })).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Another Synthetic Dataset", level: 1 })).toBeInTheDocument();
  });

  it("aborts the stale primary request when the slug changes before it resolves", async () => {
    const slugA = slug;
    const slugB = "another-synthetic-dataset";
    let slugASignal: AbortSignal | undefined;

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slugA}`)) {
        slugASignal = init?.signal ?? undefined;
        return new Promise(() => {
          /* never resolves -- this request must be aborted, not raced */
        });
      }
      if (url.endsWith(`/datasets/${slugB}`)) {
        return Promise.resolve(
          jsonResponse({ ...datasetMetadata, dataset_slug: slugB, title: "Another Synthetic Dataset" }),
        );
      }
      for (const s of [slugB]) {
        if (url.endsWith(`/datasets/${s}/context`)) return Promise.resolve(jsonResponse({ dataset_slug: s, context: contextPayload }));
        if (url.endsWith(`/datasets/${s}/metrics`)) return Promise.resolve(jsonResponse({ dataset_slug: s, metrics: metricsPayload }));
        if (url.endsWith(`/datasets/${s}/visualizations`))
          return Promise.resolve(jsonResponse({ dataset_slug: s, visualizations: visualizationsPayload }));
        if (url.endsWith(`/datasets/${s}/contract`))
          return Promise.resolve(
            jsonResponse({ dataset_slug: s, contract: contractPayload, result_contract: resultContractAvailable }),
          );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/dataset/${slugA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug"
            element={
              <>
                <Link to={`/dataset/${slugB}`}>Go to B</Link>
                <DatasetPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(slugASignal).toBeDefined());
    expect(slugASignal?.aborted).toBe(false);

    fireEvent.click(screen.getByRole("link", { name: "Go to B" }));

    expect(await screen.findByRole("heading", { name: "Another Synthetic Dataset", level: 1 })).toBeInTheDocument();
    expect(slugASignal?.aborted).toBe(true);
  });
});

describe("DatasetPage synthetic-slug rendering", () => {
  it("keeps Dataset Detail copy under display and problem-summary ownership", async () => {
    installDatasetPageFetchMock(
      {
        ...contextPayload,
        display_title: "  ",
        display_subtitle: "Published detail subtitle",
        short_description: "Home-card-only context copy",
        problem_summary_title: "Curated question",
        problem_summary_body: "Curated answer",
        canonical_name_fallback: true,
      },
      {
        ...datasetMetadata,
        display_subtitle: "Metadata detail subtitle",
        short_description: "Home-card-only metadata copy",
      },
    );

    renderDatasetPage();

    expect(await screen.findByRole("heading", { level: 1, name: datasetMetadata.title })).toBeInTheDocument();
    expect(await screen.findByText("Published detail subtitle")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Curated question" })).toBeInTheDocument();
    expect(screen.getByText("Curated answer")).toBeInTheDocument();
    expect(screen.queryByText("Home-card-only context copy")).not.toBeInTheDocument();
    expect(screen.queryByText("Home-card-only metadata copy")).not.toBeInTheDocument();
  });

  it("falls back from whitespace curated problem copy to deterministic technical copy", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      description: "Technical description fallback",
      problem_summary_title: "  ",
      problem_summary_body: "\n",
    });
    renderDatasetPage();

    expect(await screen.findByRole("heading", { level: 3, name: "Problem summary" })).toBeInTheDocument();
    expect(screen.getByText("Technical description fallback")).toBeInTheDocument();
  });
  it("hydrates the published detail theme and falls back for an unsupported context value", async () => {
    installDatasetPageFetchMock({ ...contextPayload, theme_preset: "crimson-night" });
    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    // Project Spec S0117: the theme comes from the /context response, which
    // only starts fetching once the primary route is ready -- wait for it
    // rather than asserting synchronously right after the primary heading.
    await waitFor(() => {
      expect(container.querySelector(".dataset-detail-surface")).toHaveAttribute("data-theme-preset", "crimson-night");
    });
    const detail = container.querySelector<HTMLElement>(".dataset-detail-surface")!;
    expect(detail.style.getPropertyValue("--dataset-theme-canvas")).toBe("#160b17");

    cleanup();
    installDatasetPageFetchMock({ ...contextPayload, theme_preset: "custom-rainbow" });
    const fallbackRender = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await waitFor(() => {
      expect(fallbackRender.container.querySelector(".dataset-detail-surface")).toHaveAttribute("data-theme-preset", "atlas-green");
    });
  });

  // Project Spec S0130: the ready route renders exactly one route-level
  // themed canvas (outside the constrained inner content wrapper) resolving
  // the same theme preset/fallback as the shared surface, and exactly one
  // DatasetDetailSurface nested inside it.
  it("renders a single route-level themed canvas wrapping exactly one DatasetDetailSurface, resolving the same theme preset", async () => {
    installDatasetPageFetchMock({ ...contextPayload, theme_preset: "crimson-night" });
    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await waitFor(() => {
      expect(container.querySelectorAll(".dataset-detail-page-canvas")).toHaveLength(1);
    });
    expect(container.querySelectorAll(".dataset-detail-surface")).toHaveLength(1);

    const canvas = container.querySelector<HTMLElement>(".dataset-detail-page-canvas")!;
    expect(canvas).toHaveAttribute("data-theme-preset", "crimson-night");
    expect(canvas.style.getPropertyValue("--dataset-theme-canvas")).toBe("#160b17");

    const surface = container.querySelector<HTMLElement>(".dataset-detail-surface")!;
    expect(canvas.contains(surface)).toBe(true);
    expect(surface).toHaveAttribute("data-theme-preset", "crimson-night");

    const content = container.querySelector(".dataset-detail-page-content");
    expect(content).toBeInTheDocument();
    expect(content?.contains(surface)).toBe(true);
  });

  // Project Spec S0130: loading/maintenance/not_found/unavailable states
  // never render the route-level themed canvas, so a previously-viewed
  // ready dataset's theme can never leak into a non-ready state.
  it("never renders the route-level themed canvas for loading or access states", async () => {
    const errorFetch = installDatasetPageErrorFetchMock(
      { error_type: "dataset_not_found", error_code: "DATASET_NOT_FOUND", message: "The requested dataset is not available." },
      404,
    );
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { level: 1, name: "Dataset not found" });
    expect(container.querySelector(".dataset-detail-page-canvas")).not.toBeInTheDocument();
    expect(errorFetch).toHaveBeenCalledTimes(1);
  });

  it("does not carry a previously-viewed dataset's theme into a stale-then-not-found navigation", async () => {
    const slugA = slug;
    const slugB = "not-found-slug";

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slugA}`)) return jsonResponse(datasetMetadata);
      if (url.endsWith(`/datasets/${slugA}/context`))
        return jsonResponse({ dataset_slug: slugA, context: { ...contextPayload, theme_preset: "crimson-night" } });
      if (url.endsWith(`/datasets/${slugA}/metrics`)) return jsonResponse({ dataset_slug: slugA, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slugA}/visualizations`))
        return jsonResponse({ dataset_slug: slugA, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slugA}/contract`))
        return jsonResponse({ dataset_slug: slugA, contract: contractPayload, result_contract: resultContractAvailable });
      if (url.endsWith(`/datasets/${slugB}`))
        return jsonResponse(
          { error_type: "dataset_not_found", error_code: "DATASET_NOT_FOUND", message: "The requested dataset is not available." },
          404,
        );
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <MemoryRouter initialEntries={[`/dataset/${slugA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug"
            element={
              <>
                <Link to={`/dataset/${slugB}`}>Go to not-found</Link>
                <DatasetPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await waitFor(() => {
      expect(container.querySelector(".dataset-detail-page-canvas")).toHaveAttribute("data-theme-preset", "crimson-night");
    });

    fireEvent.click(screen.getByRole("link", { name: "Go to not-found" }));

    await screen.findByRole("heading", { level: 1, name: "Dataset not found" });
    expect(container.querySelector(".dataset-detail-page-canvas")).not.toBeInTheDocument();
  });

  it("renders the correct title, metadata, and badge for a synthetic, non-Telco/Bank dataset_slug", async () => {
    installDatasetPageFetchMock();

    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    // Project Spec S0117: context/metrics/contract only fetch once the
    // primary route is ready -- await the first auxiliary-derived assertion.
    // Project Spec S0127: the analysis badge is humanized, and Target
    // reflects release-bound class identity (positive_class/negative_class
    // from the /contract result_contract) rather than the raw problem_type
    // or the context's own prediction_target_description.
    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Churn (Yes/No)")).toBeInTheDocument();
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    expect(screen.queryByText(/telco/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/bank/i)).not.toBeInTheDocument();
  });

  // Project Spec S0119: the default route dropped Model Card and Predict
  // View list entirely -- both requests and both components are gone, while
  // the shared three-tab surface (Overview/Inference/Documentation) and the
  // once-only analytical slots remain.
  it("renders the shared three-tab surface without Model Card or Predict View list, and requests only the reduced endpoint set", async () => {
    const fetchMock = installDatasetPageFetchMock();

    const { container } = renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("1,234")).toBeInTheDocument();

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Inference",
      "Documentation",
    ]);
    expect(container.querySelector(".dataset-detail-surface")).toBeInTheDocument();

    expect(container.querySelectorAll(".performance-summary")).toHaveLength(1);
    // Project Spec S0138: Overview restores the donut Target Distribution
    // card alongside the ranked Feature Importance visualization.
    expect(container.querySelectorAll(".dataset-detail-visualization")).toHaveLength(2);
    expect(container.querySelector(".dataset-detail-visualization--ranked")).toBeInTheDocument();
    expect(container.querySelector(".dataset-detail-visualization--donut")).toBeInTheDocument();

    expect(screen.queryByText(/model card/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /model card/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Predict views are temporarily unavailable.")).not.toBeInTheDocument();

    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/model-card"))).toBe(false);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/views`))).toBe(false);
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

    // Project Spec S0117: metrics/context only fetch once the primary route
    // is ready -- await the first auxiliary-derived assertion.
    // Project Spec S0204: the same "Positive-class detection" label now
    // renders twice -- once as the Dataset Detail header's Performance
    // focus badge, once as the Performance Summary subtitle -- both sourced
    // from the same shared focus label authority.
    expect((await screen.findAllByText("Positive-class detection")).length).toBeGreaterThanOrEqual(1);
    expect(container.querySelector(".performance-summary__focus")?.textContent).toBe("Positive-class detection");
    expect(screen.getByText("57.4%")).toBeInTheDocument();
    expect(screen.queryByText("AUC ROC")).not.toBeInTheDocument();
    const scoreTiles = Array.from(container.querySelectorAll(".performance-summary__score"));
    expect(scoreTiles).toHaveLength(2);
    // Project Spec S0201: only the two published scores render -- a third
    // catalog score for the same focus (e.g. F1-score) must never be
    // invented.
    expect(screen.queryByText("F1-score")).not.toBeInTheDocument();
    const scores = scoreTiles.map((tile) => tile.querySelector("dt")?.textContent);
    expect(scores).toEqual(["RecallHighlighted", "Precision"]);
    // Project Spec S0201: both monotonic direction arrows (favorable and
    // unfavorable) render for each higher-is-better public score.
    for (const tile of scoreTiles) {
      expect(tile.querySelector(".performance-summary__score-orientation-arrow--favorable")).toHaveTextContent("↑");
      expect(tile.querySelector(".performance-summary__score-orientation-arrow--unfavorable")).toHaveTextContent("↓");
    }
  });
});

// Project Spec S0204: proves context.performance_focus.focus_id reaches the
// public Dataset Detail header as the Performance focus badge, alongside
// the existing problem-type badge, without altering score rendering.
describe("DatasetPage Performance focus badge (Project Spec S0204)", () => {
  it("renders both the problem-type and Performance focus badges from context", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      problem_type: "binary_classification",
      performance_focus: {
        focus_id: "overall_discrimination",
        highlighted_score_id: "roc_auc",
        visible_scores: [
          { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.87", value_source: "canonical", order: 0 },
        ],
      },
    });

    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    const headerBadges = document.querySelectorAll(".dataset-detail-header__badges .atlas-badge");
    // Project Spec S0238: the header now renders the full problem/focus/model
    // triad -- the release-bound Model badge (from the default fixture's
    // result_contract.semantics.model_descriptor.display_name) joins the
    // problem-type and Performance focus badges this test already covers.
    expect(Array.from(headerBadges).map((badge) => badge.textContent)).toEqual([
      "Binary Classification",
      "Overall discrimination",
      "Gradient Boosting",
    ]);
  });

  it("preserves the current single-badge header when context.performance_focus is missing", async () => {
    installDatasetPageFetchMock({ ...contextPayload, problem_type: "binary_classification", performance_focus: null });

    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    // Project Spec S0238: only the Performance focus badge is omitted here --
    // the problem badge and the release-bound Model badge both still render.
    expect(document.querySelectorAll(".dataset-detail-header__badges .atlas-badge")).toHaveLength(2);
  });

  it("does not change score rendering when a Performance focus badge is added", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      performance_focus: {
        focus_id: "positive_class_detection",
        highlighted_score_id: "recall",
        visible_scores: [
          { score_id: "recall", display_label: "Recall", value: "57.4%", value_source: "manual", order: 0 },
        ],
      },
    });

    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("57.4%")).toBeInTheDocument();
    expect(container.querySelectorAll(".performance-summary__score")).toHaveLength(1);
  });
});

// Project Spec S0238: the Model badge is derived from the already-loaded
// /contract response's result_contract -- never a second /model-card or
// /contract request, and omitted (not invented) when that contract is
// unavailable.
describe("DatasetPage Model badge (Project Spec S0238)", () => {
  it("omits the Model badge, without an extra request, when the result contract is unavailable", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) return jsonResponse({ dataset_slug: slug, context: contextPayload });
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slug}/visualizations`))
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slug}/contract`))
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: { status: "unavailable", reason: "binary_result_semantics_unavailable" },
        });
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByText("Binary Classification");

    const headerBadges = document.querySelectorAll(".dataset-detail-header__badges .atlas-badge");
    expect(Array.from(headerBadges).map((badge) => badge.textContent)).toEqual(["Binary Classification"]);
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith(`/datasets/${slug}/contract`))).toHaveLength(1);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/model-card"))).toBe(false);
  });

  it("renders the release-bound Model badge from the already-loaded /contract response with no additional request", async () => {
    const fetchMock = installDatasetPageFetchMock();

    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Gradient Boosting", { selector: ".dataset-detail-header__badges .atlas-badge" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith(`/datasets/${slug}/contract`))).toHaveLength(1);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/model-card"))).toBe(false);
  });
});

describe("DatasetPage Overview tabs (Project Spec S0117)", () => {
  it("switches from Overview to Inference and renders the split inference layout", async () => {
    installDatasetPageFetchMock();

    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const inferenceTab = screen.getByRole("tab", { name: "Inference" });

    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    // Project Spec S0117: context only fetches once the primary route is
    // ready -- await it rather than asserting synchronously.
    expect(await screen.findByText("Synthetic public-safe context summary.")).toBeInTheDocument();

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
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
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

// Project Spec S0134: the route already fetched the published bound view's
// customization for the submit-button label (S0110) -- these tests prove
// the *complete* fetched PredictViewCustomization object is now passed to
// InferenceForm itself, driving the public field/group projection, and that
// absent/failed/stale customization never leaks or hides the form.
describe("DatasetPage bound predict view customization application (Project Spec S0134)", () => {
  const boundViewId = "synthetic-risk-view";

  const customizationContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "feature_a", label: "Feature A", input_type: "number" as const, optional: true, display_order: 1 },
      { name: "feature_b", label: "Feature B Original Label", input_type: "number" as const, optional: true, display_order: 2 },
      { name: "feature_c", label: "Feature C", input_type: "number" as const, optional: true, display_order: 3 },
      { name: "feature_d", label: "Feature D Hidden", input_type: "number" as const, optional: true, display_order: 4 },
    ],
  };

  const syntheticCustomization = {
    schema_version: "1.0.0",
    view_id: boundViewId,
    dataset_slug: slug,
    field_hints: [
      { field_name: "feature_b", group: "primary", display_order_hint: 1, display_label: "Renamed B Label" },
      { field_name: "feature_a", group: "primary", display_order_hint: 2 },
      { field_name: "feature_c", group: "secondary", display_order_hint: 3, explanatory_copy: "Helper text for feature C" },
      { field_name: "feature_d", hidden: true },
    ],
    groups: [
      { group_id: "secondary", label: "Secondary Group" },
      { group_id: "primary", label: "Primary Group" },
    ],
    view_copy: { submit_button_label: "Run Synthetic Prediction" },
  };

  function installCustomizationFetchMock(
    options: {
      boundPredictViewId?: string | null;
      customization?: typeof syntheticCustomization | null;
      customizationStatus?: number;
      contract?: typeof customizationContractPayload;
    } = {},
  ) {
    const contract = options.contract ?? customizationContractPayload;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: { ...contextPayload, bound_predict_view_id: options.boundPredictViewId ?? null },
        });
      }
      if (url.endsWith(`/datasets/${slug}/views/${boundViewId}/customization`)) {
        if (options.customizationStatus) {
          return jsonResponse({}, options.customizationStatus);
        }
        if (options.customization === null) {
          return jsonResponse({}, 404);
        }
        return jsonResponse(options.customization ?? syntheticCustomization);
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }

      throw new Error(`unexpected fetch for a synthetic customization-projection test: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  async function openInferenceTab() {
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
  }

  it("projects the complete published customization: group order, field order, renamed label, helper text, hidden field and submit-button label", async () => {
    const fetchMock = installCustomizationFetchMock({ boundPredictViewId: boundViewId });
    const { container } = renderDatasetPage();
    await openInferenceTab();

    await screen.findByRole("button", { name: "Run Synthetic Prediction" });

    const legends = Array.from(container.querySelectorAll("fieldset legend")).map((el) => el.textContent);
    expect(legends).toEqual(["Secondary Group", "Primary Group"]);

    const fieldsets = Array.from(container.querySelectorAll("fieldset"));
    const primaryFieldset = fieldsets.find((fs) => fs.querySelector("legend")?.textContent === "Primary Group")!;
    const primaryLabels = Array.from(primaryFieldset.querySelectorAll("label")).map((el) => el.textContent);
    expect(primaryLabels).toEqual(["Renamed B Label", "Feature A"]);

    const secondaryFieldset = fieldsets.find((fs) => fs.querySelector("legend")?.textContent === "Secondary Group")!;
    expect(secondaryFieldset.textContent).toContain("Feature C");
    expect(secondaryFieldset.textContent).toContain("Helper text for feature C");

    expect(screen.queryByText("Feature D Hidden")).not.toBeInTheDocument();

    // Exactly the bound view's customization endpoint is requested -- never
    // a views list, an Admin endpoint, or another view id.
    const calledUrls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(calledUrls.some((url) => url.endsWith(`/datasets/${slug}/views/${boundViewId}/customization`))).toBe(true);
    expect(calledUrls.some((url) => url.endsWith(`/datasets/${slug}/views`))).toBe(false);
    expect(calledUrls.some((url) => url.includes("/admin"))).toBe(false);
    expect(calledUrls.some((url) => url.includes("/customization") && !url.includes(boundViewId))).toBe(false);
  });

  it("falls back to ungrouped contract fields in display_order, without hiding any field, when no bound view is published", async () => {
    const fetchMock = installCustomizationFetchMock({ boundPredictViewId: null });
    const { container } = renderDatasetPage();
    await openInferenceTab();

    await screen.findByText("Feature A");
    expect(container.querySelectorAll("fieldset")).toHaveLength(0);
    const labels = Array.from(container.querySelectorAll(".public-inference-surface label")).map((el) => el.textContent);
    expect(labels).toEqual(["Feature A", "Feature B Original Label", "Feature C", "Feature D Hidden"]);

    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/customization"))).toBe(false);
  });

  it("falls back to the ungrouped contract form when the bound view's customization returns 404", async () => {
    installCustomizationFetchMock({ boundPredictViewId: boundViewId, customization: null });
    const { container } = renderDatasetPage();
    await openInferenceTab();

    await screen.findByText("Feature A");
    expect(container.querySelectorAll("fieldset")).toHaveLength(0);
    expect(screen.getByText("Feature D Hidden")).toBeInTheDocument();
  });

  it("ignores a stale customization response after switching to a dataset with a different bound-view identity", async () => {
    const slugA = slug;
    const slugB = "another-synthetic-dataset";
    let slugASignal: AbortSignal | undefined;

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${slugA}/views/${boundViewId}/customization`)) {
        slugASignal = init?.signal ?? undefined;
        return new Promise(() => {
          /* never resolves -- must be aborted on slug switch, not raced */
        });
      }
      if (url.endsWith(`/datasets/${slugA}/context`)) {
        return Promise.resolve(
          jsonResponse({ dataset_slug: slugA, context: { ...contextPayload, bound_predict_view_id: boundViewId } }),
        );
      }
      if (url.endsWith(`/datasets/${slugA}/metrics`))
        return Promise.resolve(jsonResponse({ dataset_slug: slugA, metrics: metricsPayload }));
      if (url.endsWith(`/datasets/${slugA}/visualizations`))
        return Promise.resolve(jsonResponse({ dataset_slug: slugA, visualizations: visualizationsPayload }));
      if (url.endsWith(`/datasets/${slugA}/contract`))
        return Promise.resolve(
          jsonResponse({ dataset_slug: slugA, contract: customizationContractPayload, result_contract: resultContractAvailable }),
        );
      if (url.endsWith(`/datasets/${slugA}`)) return Promise.resolve(jsonResponse(datasetMetadata));

      if (url.endsWith(`/datasets/${slugB}`))
        return Promise.resolve(jsonResponse({ ...datasetMetadata, dataset_slug: slugB, title: "Another Synthetic Dataset" }));
      if (url.endsWith(`/datasets/${slugB}/context`))
        return Promise.resolve(
          jsonResponse({
            dataset_slug: slugB,
            // Published context.title takes precedence over the primary
            // route payload's own title (see the datasetTitle precedence
            // chain in DatasetPage.tsx) -- blank it here so this assertion
            // proves the *primary* route data, not a copy-pasted fixture.
            context: { ...contextPayload, title: "", bound_predict_view_id: null },
          }),
        );
      if (url.endsWith(`/datasets/${slugB}/metrics`))
        return Promise.resolve(jsonResponse({ dataset_slug: slugB, metrics: metricsPayload }));
      if (url.endsWith(`/datasets/${slugB}/visualizations`))
        return Promise.resolve(jsonResponse({ dataset_slug: slugB, visualizations: visualizationsPayload }));
      if (url.endsWith(`/datasets/${slugB}/contract`))
        return Promise.resolve(
          jsonResponse({ dataset_slug: slugB, contract: contractPayload, result_contract: resultContractAvailable }),
        );

      return Promise.resolve(jsonResponse({}, 404));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/dataset/${slugA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug"
            element={
              <>
                <Link to={`/dataset/${slugB}`}>Go to B</Link>
                <DatasetPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await waitFor(() => expect(slugASignal).toBeDefined());
    expect(slugASignal?.aborted).toBe(false);

    fireEvent.click(screen.getByRole("link", { name: "Go to B" }));

    expect(await screen.findByRole("heading", { name: "Another Synthetic Dataset", level: 1 })).toBeInTheDocument();
    expect(slugASignal?.aborted).toBe(true);

    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");
    // slugB has no bound view: the stale slugA customization must never be
    // reused, so the form falls all the way through to InferenceForm's own
    // "Submit" default rather than any label/grouping from slugA.
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
  });
});

// Project Spec S0134: submitting the customized public form still uses the
// shared InferenceForm/ResultCardShell execution path -- the route never
// introduces a second Result Card state machine, and a rendered result is
// confined to the Inference panel even though every tab panel stays mounted
// (hidden, not unmounted) for tab switching.
describe("DatasetPage inference result execution (Project Spec S0134)", () => {
  const validResult = {
    schema_version: "binary-classification-result.v1",
    problem_type: "binary_classification",
    predicted_class: { class_id: "Yes" },
    positive_class: { class_id: "Yes", event_label: "Churn" },
    positive_class_probability: 0.68,
    class_probabilities: [
      { class_id: "No", probability: 0.32 },
      { class_id: "Yes", probability: 0.68 },
    ],
    decision: { threshold: 0.5, predicted_positive: true },
    interpretation: {
      preset: "risk" as const,
      band_id: "high",
      bands: resultContractAvailable.semantics.interpretation.bands,
    },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
  };

  function getVisiblePanel(container: HTMLElement) {
    return Array.from(container.querySelectorAll<HTMLElement>(".dataset-detail-tabs__panel")).find(
      (panel) => panel.getAttribute("hidden") === null,
    )!;
  }

  function installResultExecutionFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (init?.method === "POST" && url.endsWith(`/datasets/${slug}/inference`)) {
        return jsonResponse({ dataset_slug: slug, result: validResult });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) return jsonResponse({ dataset_slug: slug, context: contextPayload });
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slug}/visualizations`))
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slug}/contract`))
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("submits from the Inference tab, updates the published Result Card exactly once, and never leaks the result into Overview", async () => {
    const fetchMock = installResultExecutionFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();

    const postCalls = fetchMock.mock.calls.filter(
      (call) => call[1]?.method === "POST" && String(call[0]).endsWith(`/datasets/${slug}/inference`),
    );
    expect(postCalls).toHaveLength(1);

    const inferencePanel = getVisiblePanel(container);
    expect(inferencePanel.textContent).toContain("Likely to churn");

    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    const overviewPanel = getVisiblePanel(container);
    expect(overviewPanel.textContent).not.toContain("Likely to churn");
    expect(overviewPanel.querySelector('[aria-label="Prediction result"]')).not.toBeInTheDocument();

    // Still mounted exactly once (hidden, not unmounted, inside Inference).
    expect(screen.getAllByLabelText("Prediction result")).toHaveLength(1);
  });

  // Project Spec S0140: state-retention validation -- fill a real form
  // field, leave the Inference tab, return, and prove both the field's live
  // value and the underlying DOM node survived. A remount (rather than a
  // CSS-only hide) would reset the uncontrolled input and hand back a new
  // node, so identity plus value together prove the panel was hidden in
  // place, not recreated.
  it("keeps entered Inference field values mounted when switching away and back to the tab", async () => {
    installResultExecutionFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    const featureInput = (await screen.findByLabelText("Synthetic Feature")) as HTMLInputElement;

    fireEvent.change(featureInput, { target: { value: "42" } });
    expect(featureInput.value).toBe("42");

    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));

    const sameFeatureInput = screen.getByLabelText("Synthetic Feature") as HTMLInputElement;
    expect(sameFeatureInput).toBe(featureInput);
    expect(sameFeatureInput.value).toBe("42");
  });
});

// Project Spec S0146: a contract-required checkbox must remain a complete
// two-state boolean field on public Dataset Detail -- leaving it unchecked
// must still reach the shared public inference execution path (never
// blocked by native checkbox constraint validation), serializing to a
// boolean false payload key.
describe("DatasetPage boolean checkbox false-state submission (Project Spec S0146)", () => {
  const checkboxContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "synthetic_feature", label: "Synthetic Feature", input_type: "number" as const, optional: true, display_order: 1 },
      { name: "consent", label: "Consent", input_type: "checkbox" as const, optional: false, display_order: 2 },
    ],
  };

  const validResult = {
    schema_version: "binary-classification-result.v1",
    problem_type: "binary_classification",
    predicted_class: { class_id: "Yes" },
    positive_class: { class_id: "Yes", event_label: "Churn" },
    positive_class_probability: 0.68,
    class_probabilities: [
      { class_id: "No", probability: 0.32 },
      { class_id: "Yes", probability: 0.68 },
    ],
    decision: { threshold: 0.5, predicted_positive: true },
    interpretation: {
      preset: "risk" as const,
      band_id: "high",
      bands: resultContractAvailable.semantics.interpretation.bands,
    },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
  };

  function installCheckboxFetchMock() {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (init?.method === "POST" && url.endsWith(`/datasets/${slug}/inference`)) {
        capturedBody = String(init.body);
        return jsonResponse({ dataset_slug: slug, result: validResult });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) return jsonResponse({ dataset_slug: slug, context: contextPayload });
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slug}/visualizations`))
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slug}/contract`))
        return jsonResponse({ dataset_slug: slug, contract: checkboxContractPayload, result_contract: resultContractAvailable });
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, getCapturedBody: () => capturedBody };
  }

  it("permits an unchecked contract-required checkbox to reach the public inference execution path, with the payload key serialized as boolean false", async () => {
    const { fetchMock, getCapturedBody } = installCheckboxFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));

    const checkbox = await screen.findByLabelText("Consent");
    expect(checkbox).not.toBeChecked();
    expect(checkbox).not.toHaveAttribute("required");

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        (call) => String(call[0]).endsWith(`/datasets/${slug}/inference`) && call[1]?.method === "POST",
      ),
    ).toBe(true);

    const body = JSON.parse(getCapturedBody()!);
    expect(body.consent).toBe(false);
    expect(typeof body.consent).toBe("boolean");
  });
});

// Project Spec S0141: before any submission, the public Dataset Detail
// Inference tab must render exactly one complete Result Card at the local
// zero-probability initial projection -- never the idle placeholder -- and
// must never fire the inference POST request until the form is explicitly
// submitted.
describe("DatasetPage public Result Card zero-probability initial projection (Project Spec S0141)", () => {
  it("renders exactly one complete Result Card at 0% before submission and issues no inference POST request", async () => {
    const fetchMock = installDatasetPageFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");

    expect(screen.queryByText("Submit the form to see the prediction.")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".inference-result")).toHaveLength(1);
    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
    // Project Spec S0238: "Gradient Boosting" now also renders in the shared
    // header Model badge, so this assertion is scoped to the Result Card's
    // own model-value element specifically.
    expect(
      screen.getByText("Gradient Boosting", { selector: ".binary-classification-result__model-value" }),
    ).toBeInTheDocument();
    expect(container.querySelector(".result-panel--initial")).toBeInTheDocument();

    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/inference`))).toBe(false);
  });

  it("does not fabricate a zero-probability card and keeps submission disabled when the result contract is unavailable", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) return jsonResponse({ dataset_slug: slug, context: contextPayload });
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slug}/visualizations`))
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slug}/contract`))
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: { status: "unavailable", reason: "binary_result_semantics_unavailable" },
        });
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");

    expect(screen.queryByText("0%", { selector: ".binary-classification-result__probability-value" })).not.toBeInTheDocument();
    expect(
      screen.getByText("This active release does not currently expose a compatible result."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/inference`))).toBe(false);
  });

  it("keeps a real successful result visible (never reverts to the zero projection) across a same-slug tab-switch re-render", async () => {
    const validResult = {
      schema_version: "binary-classification-result.v1",
      problem_type: "binary_classification",
      predicted_class: { class_id: "Yes" },
      positive_class: { class_id: "Yes", event_label: "Churn" },
      positive_class_probability: 0.68,
      class_probabilities: [
        { class_id: "No", probability: 0.32 },
        { class_id: "Yes", probability: 0.68 },
      ],
      decision: { threshold: 0.5, predicted_positive: true },
      interpretation: {
        preset: "risk" as const,
        band_id: "high",
        bands: resultContractAvailable.semantics.interpretation.bands,
      },
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith(`/datasets/${slug}/inference`)) {
        return jsonResponse({ dataset_slug: slug, result: validResult });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) return jsonResponse({ dataset_slug: slug, context: contextPayload });
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slug}/visualizations`))
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slug}/contract`))
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();

    // A same-slug re-render driven by leaving and returning to the tab must
    // never overwrite the real result with a fresh zero projection.
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));

    expect(screen.getByText("Likely to churn")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.queryByText("0%", { selector: ".binary-classification-result__probability-value" })).not.toBeInTheDocument();
  });

  it("shows the new dataset's own zero-probability projection (not the prior dataset's real result) after navigating to a different Dataset Detail identity", async () => {
    const slugA = slug;
    const slugB = "another-synthetic-dataset";
    const datasetBMetadata = { ...datasetMetadata, dataset_slug: slugB, title: "Another Synthetic Dataset" };
    const resultContractB = {
      status: "available" as const,
      semantics: {
        ...resultContractAvailable.semantics,
        model_descriptor: { model_family: "logistic_regression", display_name: "Dataset B Model" },
      },
    };

    const validResultA = {
      schema_version: "binary-classification-result.v1",
      problem_type: "binary_classification",
      predicted_class: { class_id: "Yes" },
      positive_class: { class_id: "Yes", event_label: "Churn" },
      positive_class_probability: 0.68,
      class_probabilities: [
        { class_id: "No", probability: 0.32 },
        { class_id: "Yes", probability: 0.68 },
      ],
      decision: { threshold: 0.5, predicted_positive: true },
      interpretation: {
        preset: "risk" as const,
        band_id: "high",
        bands: resultContractAvailable.semantics.interpretation.bands,
      },
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith(`/datasets/${slugA}/inference`)) {
        return jsonResponse({ dataset_slug: slugA, result: validResultA });
      }
      if (url.endsWith(`/datasets/${slugA}/context`)) return jsonResponse({ dataset_slug: slugA, context: contextPayload });
      if (url.endsWith(`/datasets/${slugA}/metrics`)) return jsonResponse({ dataset_slug: slugA, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slugA}/visualizations`))
        return jsonResponse({ dataset_slug: slugA, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slugA}/contract`))
        return jsonResponse({ dataset_slug: slugA, contract: contractPayload, result_contract: resultContractAvailable });
      if (url.endsWith(`/datasets/${slugA}`)) return jsonResponse(datasetMetadata);

      if (url.endsWith(`/datasets/${slugB}/context`))
        return jsonResponse({ dataset_slug: slugB, context: { ...contextPayload, title: datasetBMetadata.title } });
      if (url.endsWith(`/datasets/${slugB}/metrics`)) return jsonResponse({ dataset_slug: slugB, metrics: metricsPayload });
      if (url.endsWith(`/datasets/${slugB}/visualizations`))
        return jsonResponse({ dataset_slug: slugB, visualizations: visualizationsPayload });
      if (url.endsWith(`/datasets/${slugB}/contract`))
        return jsonResponse({ dataset_slug: slugB, contract: contractPayload, result_contract: resultContractB });
      if (url.endsWith(`/datasets/${slugB}`)) return jsonResponse(datasetBMetadata);

      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/dataset/${slugA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug"
            element={
              <>
                <Link to={`/dataset/${slugB}`}>Go to B</Link>
                <DatasetPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "Go to B" }));
    await screen.findByRole("heading", { name: "Another Synthetic Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");

    expect(screen.queryByText("Likely to churn")).not.toBeInTheDocument();
    expect(screen.queryByText("68%")).not.toBeInTheDocument();
    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
    // Project Spec S0238: "Dataset B Model" now also renders in the shared
    // header Model badge, so this assertion is scoped to the Result Card's
    // own model-value element specifically.
    expect(
      screen.getByText("Dataset B Model", { selector: ".binary-classification-result__model-value" }),
    ).toBeInTheDocument();
  });
});

// Project Spec S0140: repeated switching must never leave two panels
// simultaneously active at the full DatasetPage level (not just the isolated
// DatasetDetailTabs unit), and must never duplicate an authorized card.
describe("DatasetPage repeated tab switching (Project Spec S0140)", () => {
  function getUnhiddenPanels(container: HTMLElement) {
    return Array.from(container.querySelectorAll<HTMLElement>(".dataset-detail-tabs__panel")).filter(
      (panel) => panel.getAttribute("hidden") === null,
    );
  }

  it("keeps exactly one panel active and unhidden through Overview -> Inference -> Documentation -> Overview -> Inference", async () => {
    installDatasetPageFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    // Let the auxiliary context/metrics/visualizations fetches settle before
    // the sequence starts, so an in-flight request can't be mistaken for a
    // missing card on the first Overview step.
    await screen.findByText("Synthetic public-safe context summary.");
    expect(container.querySelectorAll(".performance-summary")).toHaveLength(1);

    const sequence = ["Overview", "Inference", "Documentation", "Overview", "Inference"];

    for (const tabName of sequence) {
      fireEvent.click(screen.getByRole("tab", { name: tabName }));
      if (tabName === "Inference") {
        await screen.findByText("Synthetic Feature");
      }

      const tabs = screen.getAllByRole("tab");
      const selectedTabs = tabs.filter((tab) => tab.getAttribute("aria-selected") === "true");
      expect(selectedTabs).toHaveLength(1);
      expect(selectedTabs[0]).toHaveAccessibleName(tabName);

      const unhiddenPanels = getUnhiddenPanels(container);
      expect(unhiddenPanels).toHaveLength(1);
      // Mounted-but-hidden, never duplicated: the once-only card stays at
      // exactly one no matter which panel is currently visible.
      expect(container.querySelectorAll(".performance-summary")).toHaveLength(1);
    }
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
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
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

// Project Spec S0203: the public Release hint drops its "Format: " prefix,
// and a monotonic public score renders its value and ↑/↓ arrow pair in one
// compact composition, with no visible "favorable"/"unfavorable" word.
describe("DatasetPage Release hint and monotonic score presentation (Project Spec S0203)", () => {
  it("shows the Release hint as exactly the effective date format, and the score value followed by ↑ then ↓ with no visible favorable/unfavorable word", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      source_name: "Original Source Org",
      release_date_label: "2026-07-01",
      date_format: "dd/mm/yyyy",
      performance_focus: {
        focus_id: "overall_discrimination" as const,
        highlighted_score_id: "roc_auc",
        visible_scores: [
          { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.8402", value_source: "canonical" as const, order: 0 },
        ],
      },
    });

    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("01/07/2026")).toBeInTheDocument();
    expect(screen.getByText("dd/mm/yyyy")).toBeInTheDocument();
    expect(screen.queryByText(/^Format:/)).not.toBeInTheDocument();

    const score = screen.getByText("ROC-AUC").closest(".performance-summary__score") as HTMLElement;
    const valueRow = score.querySelector("dd") as HTMLElement;
    expect(within(valueRow).getByText("0.8402")).toBeInTheDocument();
    const ddText = valueRow.textContent ?? "";
    expect(ddText.indexOf("0.8402")).toBeLessThan(ddText.indexOf("↑"));
    expect(ddText.indexOf("↑")).toBeLessThan(ddText.indexOf("↓"));

    expect(within(score).getByText("Highlighted")).toBeInTheDocument();
    expect(within(score).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(score.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );
    // "unfavorable" contains "favorable" as a substring, so this single
    // assertion proves neither visible word is rendered.
    expect(score).not.toHaveTextContent("favorable");
  });
});

// Project Spec S0127: metrics/metadata projection alignment -- the stable
// evaluation shape drives the Performance Summary fallback tiles, and
// release-bound result semantics (not the raw problem_type) drive the
// analysis badge and Target metadata, with documented fallbacks when result
// semantics are unavailable.
describe("DatasetPage metrics/analysis/target projection (Project Spec S0127)", () => {
  // Mirrors the real active release's training-metrics.v1 projection
  // (releases/release-20260721t124721z/metrics/metrics.json) as returned by
  // GET /datasets/{slug}/metrics after api/public_metrics_loader.py's S0127
  // normalization.
  const s0127MetricsPayload = {
    evaluation: {
      split_name: "evaluation",
      sample_size: 2114,
      primary_metric_id: "roc_auc",
      metrics: {
        roc_auc: 0.8435590708800057,
        f1_score: 0.7939456048600292,
        pr_auc: 0.6656143652383235,
      },
      metric_order: ["roc_auc", "f1_score", "pr_auc"],
    },
  };

  function installS0127FetchMock(
    options: { resultContractUnavailable?: boolean; withPredictionTargetDescription?: boolean } = {},
  ) {
    const context = {
      ...contextPayload,
      prediction_target_description: options.withPredictionTargetDescription
        ? "Whether the synthetic target event occurs."
        : undefined,
    };
    const resultContract = options.resultContractUnavailable
      ? { status: "unavailable" as const, reason: "binary_result_semantics_unavailable" }
      : resultContractAvailable;

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: s0127MetricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContract });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("renders AUC ROC/F1-score/PR AUC canonical fallback tiles with AUC ROC highlighted, and never fabricates Precision or Recall", async () => {
    installS0127FetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("AUC ROC")).toBeInTheDocument();
    expect(screen.getByText("F1-score")).toBeInTheDocument();
    expect(screen.getByText("PR AUC")).toBeInTheDocument();
    expect(screen.queryByText("Precision")).not.toBeInTheDocument();
    expect(screen.queryByText("Recall")).not.toBeInTheDocument();

    const aucRow = screen.getByText("AUC ROC").closest(".performance-summary__score");
    expect(aucRow).not.toBeNull();
    expect(within(aucRow as HTMLElement).getByText("Highlighted")).toBeInTheDocument();

    const scoreLabels = Array.from(
      container.querySelectorAll(".performance-summary__score dt"),
    ).map((dt) => dt.textContent);
    expect(scoreLabels).toEqual(["AUC ROCHighlighted", "F1-score", "PR AUC"]);
  });

  it("resolves the analysis badge and Target from release-bound result semantics when available", async () => {
    installS0127FetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Churn (Yes/No)")).toBeInTheDocument();
  });

  it("falls back to the published context problem_type/target description when result semantics are unavailable", async () => {
    installS0127FetchMock({ resultContractUnavailable: true, withPredictionTargetDescription: true });
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Whether the synthetic target event occurs.")).toBeInTheDocument();
    expect(screen.queryByText("Churn (Yes/No)")).not.toBeInTheDocument();
  });

  it("shows no analysis badge and a Pending Target when neither result semantics nor a context problem_type/target description are available", async () => {
    installS0127FetchMock({ resultContractUnavailable: true, withPredictionTargetDescription: false });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: { ...contextPayload, problem_type: undefined, prediction_target_description: undefined },
        });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: s0127MetricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: visualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: { status: "unavailable", reason: "binary_result_semantics_unavailable" },
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    // Metrics only fetch once the primary route is ready (Project Spec
    // S0117); await an auxiliary-derived assertion before checking the
    // metadata rendered from the same render pass.
    await screen.findByText("AUC ROC");

    expect(screen.queryByText("Binary Classification")).not.toBeInTheDocument();
    expect(screen.queryByText(/classification/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Churn (Yes/No)")).not.toBeInTheDocument();

    const targetRow = screen.getByText("Target").closest(".dataset-detail-header__metadata-item");
    expect(targetRow).not.toBeNull();
    expect(within(targetRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
  });

  // Project Spec S0205: Instances now reads the bounded public
  // visualizations projection's dataset_statistics.instance_count -- never
  // metrics.evaluation.sample_size (a held-out evaluation split size, not
  // the dataset population) -- and never shows an "Evaluation split" hint.
  it("renders the Instances metadata from visualizations.dataset_statistics, ignoring metrics.evaluation.sample_size entirely", async () => {
    const irrelevantZeroSampleMetrics = {
      evaluation: {
        split_name: "evaluation",
        sample_size: 0,
        primary_metric_id: "roc_auc",
        metrics: { roc_auc: 0.5 },
        metric_order: ["roc_auc"],
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: irrelevantZeroSampleMetrics });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({
          dataset_slug: slug,
          visualizations: { charts: [], dataset_statistics: { instance_count: 2500 } },
        });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByText("2,500")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText("Evaluation split")).not.toBeInTheDocument();
  });

  it("degrades Instances to Pending when visualizations carries no dataset_statistics, even when metrics has a sample size", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: s0127MetricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: { charts: [] } });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByText("AUC ROC");

    const instancesRow = screen.getByText("Instances").closest(".dataset-detail-header__metadata-item");
    expect(instancesRow).not.toBeNull();
    expect(within(instancesRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText("2,114")).not.toBeInTheDocument();
    expect(screen.queryByText("Evaluation split")).not.toBeInTheDocument();
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
    // Project Spec S0205: the bounded dataset-population derivation the real
    // Telco release's Target Distribution (5,174 + 1,869) projects.
    dataset_statistics: { instance_count: 7043 },
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

  function installTelcoFetchMock(
    overrides: {
      visualizationsStatus?: number;
      visualizationsPayload?: Partial<typeof telcoVisualizationsPayload>;
    } = {},
  ) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${telcoSlug}/context`)) {
        return jsonResponse({ dataset_slug: telcoSlug, context: telcoContextPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/metrics`)) {
        return jsonResponse({ dataset_slug: telcoSlug, metrics: telcoMetricsPayload });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/visualizations`)) {
        if (overrides.visualizationsStatus) {
          return jsonResponse({}, overrides.visualizationsStatus);
        }
        return jsonResponse({
          dataset_slug: telcoSlug,
          visualizations: overrides.visualizationsPayload ?? telcoVisualizationsPayload,
        });
      }
      if (url.endsWith(`/datasets/${telcoSlug}/contract`)) {
        return jsonResponse({
          dataset_slug: telcoSlug,
          contract: telcoContractPayload,
          result_contract: resultContractAvailable,
        });
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

  it("renders public context, metrics, contract, and target distribution/feature importance from real-shaped API payloads, without requesting model-card or views", async () => {
    const fetchMock = installTelcoFetchMock();

    renderTelcoDatasetPage();

    expect(await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 })).toBeInTheDocument();
    // Project Spec S0117: context/metrics/contract only fetch once the
    // primary route is ready -- await the first auxiliary-derived assertion.
    // Project Spec S0127: humanized analysis badge and release-bound Target
    // (see the synthetic-slug test above for the same rule).
    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Churn (Yes/No)")).toBeInTheDocument();
    // Project Spec S0205: Instances reads the bounded public visualizations
    // projection's dataset_statistics.instance_count (the full dataset
    // population), never metrics.evaluation.sample_size (the held-out test
    // split size, 1,408 in this fixture, which must never appear here).
    expect(await screen.findByText("7,043")).toBeInTheDocument();
    expect(screen.queryByText("1,408")).not.toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    // Project Spec S0138: the ready Overview tabpanel owns exactly its four
    // authorized cards -- Problem Summary, Performance Summary, the donut
    // Target Distribution and the ranked Feature Importance -- restored from
    // the same governed /visualizations projection.
    const overviewPanel = screen.getByRole("tabpanel");
    expect(overviewPanel.querySelectorAll(".atlas-card")).toHaveLength(4);
    expect(overviewPanel.querySelector(".dataset-detail-overview__problem-summary")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".performance-summary")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".dataset-detail-visualization--donut")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".dataset-detail-visualization--ranked")).toBeInTheDocument();

    // recharts' PieChart itself never resolves a non-zero width in jsdom (no
    // real layout engine), so its internal SVG has no assertable text, but
    // both components render their real values/labels as plain DOM outside
    // the chart (TargetDistribution's legend list, FeatureImportance's row
    // list) -- Project Spec S0128 asserts on those directly rather than
    // treating the endpoint payload's presence as the only provable fact.
    const targetDistributionChart = await screen.findByLabelText("target distribution");
    expect(targetDistributionChart).toBeInTheDocument();
    // Target Distribution values render from the endpoint payload (the
    // spec's own governed Telco counts), not a hardcoded production value.
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("(5,174)")).toBeInTheDocument();
    expect(screen.getByText("(1,869)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    expect(await screen.findByText("Tenure (months)")).toBeInTheDocument();
    expect(screen.getByText("Total Charges (USD)")).toBeInTheDocument();

    const featureImportanceChart = screen.getByLabelText("feature importance");
    expect(featureImportanceChart).toBeInTheDocument();
    // Feature Importance rows use the endpoint payload's own source feature
    // names -- never a transformed/one-hot internal name.
    expect(screen.getByLabelText("tenure: 0.31")).toBeInTheDocument();
    expect(screen.getByLabelText("TotalCharges: 0.22")).toBeInTheDocument();
    expect(screen.getByLabelText("Contract: 0.18")).toBeInTheDocument();

    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/model-card"))).toBe(false);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${telcoSlug}/views`))).toBe(false);
  });

  it("does not render a misleading chart for a malformed visualizations projection (negative count, non-finite importance)", async () => {
    // A structurally-present but malformed payload (the shape a bug or a
    // partially-written artifact could produce) must still degrade to the
    // same bounded empty state as a missing artifact -- never a fabricated
    // or misleading chart. TargetDistribution.getValidDistribution and
    // FeatureImportance.getRankedFeatureRows already enforce this in
    // production; this proves it end to end through the real page.
    installTelcoFetchMock({
      visualizationsPayload: {
        charts: [
          {
            id: "target_distribution",
            title: "target distribution",
            type: "bar" as const,
            x_label: "Churn",
            y_label: "Customers",
            data: [
              { name: "No", value: -5174 },
              { name: "Yes", value: 1869 },
            ],
          },
          {
            id: "feature_importance",
            title: "feature importance",
            type: "bar" as const,
            x_label: "Feature",
            y_label: "Importance",
            data: [{ name: "tenure", value: Number.POSITIVE_INFINITY }],
          },
        ],
      },
    });

    renderTelcoDatasetPage();

    expect(await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 })).toBeInTheDocument();
    // Project Spec S0205: this malformed payload carries no dataset_statistics
    // at all, so Instances safely degrades to Pending -- it never falls back
    // to metrics.evaluation.sample_size (1,408 in this fixture).
    const instancesRow = (await screen.findByText("Instances")).closest(
      ".dataset-detail-header__metadata-item",
    );
    expect(instancesRow).not.toBeNull();
    expect(within(instancesRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText("1,408")).not.toBeInTheDocument();

    expect((await screen.findAllByText("Visualization not generated")).length).toBe(2);
    expect(screen.getAllByText("This visualization has not been generated yet for this release.")).toHaveLength(2);
    expect(screen.queryByLabelText("target distribution")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("feature importance")).not.toBeInTheDocument();
    expect(screen.queryByText("No")).not.toBeInTheDocument();
    expect(screen.queryByText("tenure")).not.toBeInTheDocument();
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
    // must not block the rest of the page. Metrics only fetches once the
    // primary route is ready (Project Spec S0117).
    expect(await screen.findByText("Accuracy")).toBeInTheDocument();

    // Project Spec S0205: Instances is now itself sourced from the failed
    // visualizations resource, so it safely degrades to Pending rather than
    // falling back to metrics.evaluation.sample_size (1,408 in this fixture).
    const instancesRow = screen.getByText("Instances").closest(".dataset-detail-header__metadata-item");
    expect(instancesRow).not.toBeNull();
    expect(within(instancesRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText("1,408")).not.toBeInTheDocument();

    expect((await screen.findAllByText("Visualization not generated")).length).toBe(2);
    expect(screen.getAllByText("This visualization has not been generated yet for this release.")).toHaveLength(2);
    expect(screen.queryByLabelText("target distribution")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("feature importance")).not.toBeInTheDocument();
  });
});

// Project Spec S0196: the public Dataset Detail Documentation tab renders
// only the published snapshot's context.documentation, through the same
// shared DatasetDocumentation renderer the Admin surfaces use -- never a
// second, private Admin request, and never synthesized content when nothing
// has been published.
describe("DatasetPage public Documentation tab (Project Spec S0196)", () => {
  function openDocumentationTab() {
    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
  }

  it("renders published Markdown, including a GFM table, in the Documentation tab", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      documentation: {
        format: "markdown",
        content:
          "# Dataset documentation\n\nCurated public notes.\n\n| Metric | Value |\n| --- | --- |\n| Accuracy | 0.91 |\n",
      },
    });
    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    openDocumentationTab();

    expect(screen.getByRole("heading", { name: "Dataset documentation" })).toBeInTheDocument();
    expect(screen.getByText("Curated public notes.")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(table.querySelector("thead")).toBeInTheDocument();
    expect(table.querySelector("tbody")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Accuracy" })).toBeInTheDocument();
  });

  it("renders the bounded empty state when no documentation has been published", async () => {
    installDatasetPageFetchMock(contextPayload);
    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    openDocumentationTab();

    expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
  });

  it("never synthesizes private/unpublished content -- a malformed documentation payload falls back to the bounded empty state", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      // @ts-expect-error -- deliberately malformed to prove no unsafe fallback rendering.
      documentation: { format: "html", content: "<p>not markdown</p>" },
    });
    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    openDocumentationTab();

    expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
    expect(screen.queryByText("not markdown")).not.toBeInTheDocument();
  });

  it("leaves existing Overview and Inference content unchanged when documentation is published", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      documentation: { format: "markdown", content: "# Docs" },
    });
    renderDatasetPage();

    expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Synthetic use case")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    expect(await screen.findByLabelText("Synthetic Feature")).toBeInTheDocument();
  });

  // Project Spec S0199: the public Documentation tab renders published
  // Markdown through the shared DatasetDocumentation renderer's bounded
  // external raw.githubusercontent.com image policy. Local Documentation
  // media storage (S0197) is retired -- no route slug is passed for image
  // authorization, and no network access occurs.
  describe("bounded external GitHub raw-image rendering (Project Spec S0199)", () => {
    const safeSrc =
      "https://raw.githubusercontent.com/FabioAguiar/dataset-study-telco-customer-churn/main/docs/images/chart.png";

    it("renders a published raw.githubusercontent.com Markdown image", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: { format: "markdown", content: `# Docs\n\n![Overview chart](${safeSrc})` },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      const img = screen.getByRole("img", { name: "Overview chart" });
      expect(img).toHaveAttribute("src", safeSrc);
    });

    it("does not render a github.com blob page URL as an image", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: {
          format: "markdown",
          content: "# Docs\n\n![alt](https://github.com/FabioAguiar/dataset-study-telco-customer-churn/blob/main/docs/images/chart.png)",
        },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.queryByRole("img", { name: "alt" })).not.toBeInTheDocument();
    });

    it("does not render an arbitrary HTTPS image host", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: {
          format: "markdown",
          content: "# Docs\n\n![remote](https://example.org/pic.png)\n\n![data](data:image/png;base64,aGVsbG8=)",
        },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("does not render a legacy /media/documentation reference", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: {
          format: "markdown",
          content: `# Docs\n\n![alt](/media/documentation/${slug}/0123456789abcdef0123456789abcdef.png)`,
        },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.queryByRole("img", { name: "alt" })).not.toBeInTheDocument();
    });

    it("does not break Documentation text rendering when the image reference is missing/invalid", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: {
          format: "markdown",
          content: "# Docs\n\n![broken]()\n\nRemaining paragraph text.",
        },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.getByText("Remaining paragraph text.")).toBeInTheDocument();
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("leaves existing Markdown text/table behavior unchanged", async () => {
      installDatasetPageFetchMock({
        ...contextPayload,
        documentation: {
          format: "markdown",
          content: "# Docs\n\nBody text.\n\n| Metric | Value |\n| --- | --- |\n| Accuracy | 0.91 |",
        },
      });
      renderDatasetPage();

      expect(await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 })).toBeInTheDocument();
      openDocumentationTab();

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.getByText("Body text.")).toBeInTheDocument();
      const table = screen.getByRole("table");
      expect(table.querySelector("thead")).toBeInTheDocument();
      expect(screen.getByRole("cell", { name: "Accuracy" })).toBeInTheDocument();
    });
  });
});

// Project Spec S0200: proves the shared performanceMetricMetadata
// optimization semantics reach the real public page for published
// performance_focus.visible_scores -- not just the PerformanceSummary unit
// tests -- and that Highlighted plus an unknown score's safe fallback both
// survive alongside the new orientation text.
describe("DatasetPage performance metric optimization orientation (Project Spec S0200)", () => {
  it("renders shared higher/lower orientation semantics, preserves Highlighted, and shows an unknown score without an invented direction", async () => {
    installDatasetPageFetchMock({
      ...contextPayload,
      performance_focus: {
        focus_id: "probability_quality" as const,
        highlighted_score_id: "roc_auc",
        visible_scores: [
          { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.8402", value_source: "canonical" as const, order: 0 },
          { score_id: "log_loss", display_label: "Log Loss", value: "0.4207", value_source: "canonical" as const, order: 1 },
          { score_id: "not_a_real_metric", display_label: "Mystery Metric", value: "1.0", value_source: "manual" as const, order: 2 },
        ],
      },
    });

    const { container } = renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    const rocScore = (await screen.findByText("ROC-AUC")).closest(".performance-summary__score") as HTMLElement;
    expect(within(rocScore).getByText("Highlighted")).toBeInTheDocument();
    expect(within(rocScore).queryByText("Higher is better")).not.toBeInTheDocument();
    expect(rocScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Higher is better",
    );

    const logLossScore = screen.getByText("Log Loss").closest(".performance-summary__score") as HTMLElement;
    expect(within(logLossScore).queryByText("Highlighted")).not.toBeInTheDocument();
    expect(within(logLossScore).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(logLossScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Lower is better",
    );

    const mysteryScore = screen.getByText("Mystery Metric").closest(".performance-summary__score") as HTMLElement;
    expect(mysteryScore.querySelector(".performance-summary__score-orientation")).not.toBeInTheDocument();
    expect(mysteryScore).toHaveTextContent("1.0");

    expect(container.querySelectorAll(".performance-summary__score")).toHaveLength(3);
  });
});

// Project Spec S0215: the public page passes the release-derived problem
// type to PerformanceSummary and renders the shared ConfusionMatrix only
// for a multiclass release with valid matrix evidence -- binary Dataset
// Detail stays visually unchanged.
describe("DatasetPage multiclass confusion matrix and Performance Summary filtering (Project Spec S0215)", () => {
  const multiclassMetricsPayload = {
    evaluation: {
      sample_size: 900,
      metrics: { accuracy: 0.82, f1_macro: 0.79, f1_score: 0.9, precision: 0.85 },
      metric_order: ["accuracy", "f1_macro", "f1_score", "precision"],
    },
  };

  const multiclassVisualizationsPayload = {
    charts: [],
    confusion_matrix: {
      ordered_class_ids: ["class-a", "class-b", "class-c"],
      matrix: [
        [0.9, 0.1, 0],
        [0.05, 0.85, 0.1],
        [0, 0.2, 0.8],
      ],
      row_axis: "true_class",
      column_axis: "predicted_class",
    },
  };

  function installMulticlassFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: multiclassMetricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: multiclassVisualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: multiclassResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("renders the shared ConfusionMatrix table for a multiclass release with valid matrix evidence", async () => {
    installMulticlassFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(await screen.findByRole("heading", { name: "Confusion Matrix" })).toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-detail-visualization")).toHaveLength(3);

    const table = screen.getByRole("table", { name: "Confusion matrix" });
    expect(within(table).getAllByText("class-a").length).toBeGreaterThan(0);
    expect(within(table).getByText("90.0%")).toBeInTheDocument();
  });

  it("filters PerformanceSummary's canonical fallback metrics to the multiclass-compatible subset", async () => {
    installMulticlassFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(await screen.findByText("Accuracy")).toBeInTheDocument();
    expect(screen.getByText("F1 Macro")).toBeInTheDocument();
    expect(screen.queryByText("F1-score")).not.toBeInTheDocument();
    expect(screen.queryByText("Precision")).not.toBeInTheDocument();
  });

  it("renders no confusion matrix, and every canonical metric, for a binary release", async () => {
    installDatasetPageFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByText("Binary Classification");
    expect(screen.queryByRole("heading", { name: "Confusion Matrix" })).not.toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-detail-visualization")).toHaveLength(2);
  });
});

// Project Spec S0228: the public page gates RegressionDiagnostics from the
// same release-bound result contract authority as Performance Summary, and
// renders continuous Target Distribution as a Cartesian histogram instead
// of the classification donut -- binary/multiclass Dataset Detail stays
// visually unchanged.
describe("DatasetPage continuous-regression diagnostics (Project Spec S0228)", () => {
  const regressionResultContractAvailable = {
    status: "available" as const,
    semantics: {
      schema_version: "continuous-regression-result-semantics.v1" as const,
      problem_type: "continuous_regression" as const,
      result_schema_version: "continuous-regression-result.v1" as const,
      primary_output: "predicted_value" as const,
      output_value_kind: "continuous_numeric" as const,
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
    },
  };

  const regressionVisualizationsPayload = {
    charts: [
      {
        id: "target_distribution",
        title: "Target Distribution",
        type: "bar" as const,
        x_label: "Strength",
        y_label: "Rows",
        data: [
          { name: "10 to 20", value: 6 },
          { name: "20 to 30", value: 4 },
        ],
      },
      {
        id: "feature_importance",
        title: "Feature Importance",
        type: "bar" as const,
        x_label: "Feature",
        y_label: "Importance",
        data: [
          { name: "cement", value: 0.6 },
          { name: "water", value: 0.4 },
        ],
      },
    ],
    dataset_statistics: { instance_count: 10 },
    target_distribution_kind: "continuous_histogram" as const,
    regression_diagnostics: {
      actual_vs_predicted: {
        points: [
          { actual_mean: 15.5, predicted_mean: 16.1, count: 6 },
          { actual_mean: 25.5, predicted_mean: 24.3, count: 4 },
        ],
      },
      residual_distribution: {
        bins: [
          { label: "-2 to 0", count: 4 },
          { label: "0 to 2", count: 6 },
        ],
      },
    },
  };

  function installRegressionFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: regressionVisualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: regressionResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}/inference`)) {
        return jsonResponse({
          result: {
            schema_version: "continuous-regression-result.v1",
            problem_type: "continuous_regression",
            predicted_value: 42.73,
            model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
          },
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("uses the shared governed result-family dispatch to render a continuous regression result on the Inference tab (Project Spec S0229)", async () => {
    installRegressionFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByText("Synthetic Feature");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("42.73")).toBeInTheDocument();
    // Project Spec S0238: "Gradient Boosting Regressor" now also renders in
    // the shared header Model badge, so this assertion is scoped to the
    // Result Card's own model-value element specifically.
    expect(
      screen.getByText("Gradient Boosting Regressor", { selector: ".continuous-regression-result__model-value" }),
    ).toBeInTheDocument();
  });

  it("renders Actual vs Predicted and Residual Distribution below the primary analytics grid for a continuous-regression release", async () => {
    installRegressionFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(await screen.findByRole("heading", { name: "Actual vs Predicted" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Residual Distribution" })).toBeInTheDocument();

    const regressionSection = container.querySelector(".dataset-detail-overview__regression-diagnostics");
    expect(regressionSection).toBeInTheDocument();
    expect(regressionSection?.querySelector(".dataset-detail-visualization--actual-vs-predicted")).toBeInTheDocument();
    expect(regressionSection?.querySelector(".dataset-detail-visualization--residual-distribution")).toBeInTheDocument();

    // Bounded aggregate values render from the endpoint payload's own
    // regression_diagnostics -- never fabricated or derived in the browser.
    expect(screen.getByText("Actual 15.5 vs Predicted 16.1")).toBeInTheDocument();
    expect(screen.getByText("n=6")).toBeInTheDocument();
    expect(screen.getByText("-2 to 0")).toBeInTheDocument();
    expect(screen.getByText("0 to 2")).toBeInTheDocument();

    expect(screen.queryByRole("heading", { name: "Confusion Matrix" })).not.toBeInTheDocument();
  });

  it("renders continuous Target Distribution as a Cartesian histogram, not the classification donut", async () => {
    installRegressionFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    const targetDistributionHeading = await screen.findByRole("heading", { name: "Target Distribution" });
    const targetDistributionCard = targetDistributionHeading.closest(".atlas-card");
    expect(targetDistributionCard).toHaveClass("dataset-detail-visualization--histogram");
    expect(container.querySelector(".dataset-detail-visualization--donut")).not.toBeInTheDocument();

    expect(screen.getByText("10 to 20")).toBeInTheDocument();
    expect(screen.getByText("20 to 30")).toBeInTheDocument();
  });

  it("renders no regression diagnostics for a binary release", async () => {
    installDatasetPageFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByText("Binary Classification");
    expect(screen.queryByRole("heading", { name: "Actual vs Predicted" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Residual Distribution" })).not.toBeInTheDocument();
  });

  it("renders no regression diagnostics for a multiclass release, and Confusion Matrix stays intact", async () => {
    const localMulticlassVisualizationsPayload = {
      charts: [],
      confusion_matrix: {
        ordered_class_ids: ["class-a", "class-b", "class-c"],
        matrix: [
          [0.9, 0.1, 0],
          [0.05, 0.85, 0.1],
          [0, 0.2, 0.8],
        ],
        row_axis: "true_class",
        column_axis: "predicted_class",
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: localMulticlassVisualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: multiclassResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(await screen.findByRole("heading", { name: "Confusion Matrix" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Actual vs Predicted" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Residual Distribution" })).not.toBeInTheDocument();
  });

  it("does not send an additional visualizations request for the regression diagnostics section", async () => {
    const fetchMock = installRegressionFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Actual vs Predicted" });
    const visualizationsCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).endsWith(`/datasets/${slug}/visualizations`),
    );
    expect(visualizationsCalls).toHaveLength(1);
  });
});

// Project Spec S0248: the public page gates ForecastingDiagnostics from the
// same release-bound result contract authority as Performance Summary, and
// omits Target Distribution/Feature Importance/Confusion Matrix/Regression
// Diagnostics entirely for a forecasting release.
describe("DatasetPage univariate-forecasting diagnostics (Project Spec S0248)", () => {
  const forecastingResultContractAvailable = {
    status: "available" as const,
    semantics: {
      schema_version: "univariate-forecasting-result-semantics.v1" as const,
      problem_type: "univariate_forecasting" as const,
      result_schema_version: "univariate-forecasting-result.v1" as const,
      primary_output: "forecast_series" as const,
      output_structure: "ordered_forecast_points" as const,
      forecast_value_kind: "continuous_numeric" as const,
      forecast_count_source: "forecast_horizon" as const,
      model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend Model" },
    },
  };

  const forecastingVisualizationsPayload = {
    charts: [],
    dataset_statistics: { instance_count: 24 },
    forecasting_diagnostics: {
      forecast_horizon: 4,
      frequency: "synthetic-step",
      seasonal_profile: {
        seasonal_period: 4,
        points: [
          { season_position: 0, mean_target: 10.0, observation_count: 5 },
          { season_position: 1, mean_target: 12.0, observation_count: 5 },
          { season_position: 2, mean_target: 9.0, observation_count: 5 },
          { season_position: 3, mean_target: 13.0, observation_count: 5 },
        ],
      },
      backtesting_fold_metric: {
        metric_id: "mae",
        direction: "lower_is_better",
        points: [
          { fold_index: 1, forecast_origin: "11", value: 1.2 },
          { fold_index: 2, forecast_origin: "15", value: 0.9 },
        ],
      },
      horizon_mae: {
        points: [
          { horizon_step: 1, mae: 0.5 },
          { horizon_step: 2, mae: 0.8 },
          { horizon_step: 3, mae: 1.1 },
          { horizon_step: 4, mae: 1.4 },
        ],
      },
    },
  };

  function installForecastingFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: contextPayload });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: metricsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: forecastingVisualizationsPayload });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: forecastingResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("renders Seasonal Profile, Backtesting by Origin, and Horizon MAE below the primary analytics grid for a forecasting release", async () => {
    installForecastingFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    expect(await screen.findByRole("heading", { name: "Seasonal Profile" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backtesting by Origin" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Horizon MAE" })).toBeInTheDocument();

    const forecastingSection = container.querySelector(".dataset-detail-overview__forecasting-diagnostics");
    expect(forecastingSection).toBeInTheDocument();
    expect(forecastingSection?.querySelector(".dataset-detail-visualization--seasonal-profile")).toBeInTheDocument();
    expect(
      forecastingSection?.querySelector(".dataset-detail-visualization--backtesting-fold-metric"),
    ).toBeInTheDocument();
    expect(forecastingSection?.querySelector(".dataset-detail-visualization--horizon-mae")).toBeInTheDocument();
  });

  it("omits Target Distribution and Feature Importance for a forecasting release", async () => {
    installForecastingFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByRole("heading", { name: "Seasonal Profile" });
    expect(screen.queryByRole("heading", { name: "Target Distribution" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Feature Importance" })).not.toBeInTheDocument();
  });

  it("omits Confusion Matrix and Regression Diagnostics for a forecasting release", async () => {
    installForecastingFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByRole("heading", { name: "Seasonal Profile" });
    expect(screen.queryByRole("heading", { name: "Confusion Matrix" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Actual vs Predicted" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Residual Distribution" })).not.toBeInTheDocument();
  });

  it("does not send an additional visualizations request for the forecasting diagnostics section", async () => {
    const fetchMock = installForecastingFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Seasonal Profile" });
    const visualizationsCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).endsWith(`/datasets/${slug}/visualizations`),
    );
    expect(visualizationsCalls).toHaveLength(1);
  });

  it("renders no forecasting diagnostics for a binary release", async () => {
    installDatasetPageFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    await screen.findByText("Binary Classification");
    expect(screen.queryByRole("heading", { name: "Seasonal Profile" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Backtesting by Origin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Horizon MAE" })).not.toBeInTheDocument();
  });
});

// Project Spec S0250: the actual public-contract v2 forecasting form
// (HistorySeriesInput wired through the shared InferenceForm), Features
// metadata safety, and real forecasting inference execution -- distinct
// from the S0248 describe block above, which paired a forecasting result
// contract with the unrelated scalar v1 contractPayload fixture purely to
// exercise the diagnostics visualizations section.
describe("DatasetPage univariate-forecasting inference form and metadata (Project Spec S0250)", () => {
  const forecastingContractPayload = {
    schema_version: "2.0.0",
    problem_type: "univariate_forecasting",
    input_kind: "history_series",
    history_series: {
      time_index_field: { name: "period", label: "Period", value_kind: "calendar_period" as const, display_order: 1 },
      target_field: { name: "passengers", label: "Passengers", value_kind: "number" as const, display_order: 2 },
      frequency: "Monthly",
    },
    forecast: { forecast_horizon: 3, horizon_user_editable: false as const },
  };

  const forecastingResultContractAvailable = {
    status: "available" as const,
    semantics: {
      schema_version: "univariate-forecasting-result-semantics.v1" as const,
      problem_type: "univariate_forecasting" as const,
      result_schema_version: "univariate-forecasting-result.v1" as const,
      primary_output: "forecast_series" as const,
      output_structure: "ordered_forecast_points" as const,
      forecast_value_kind: "continuous_numeric" as const,
      forecast_count_source: "forecast_horizon" as const,
      model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
    },
  };

  const forecastingResultCardPresentation = {
    schema_version: "univariate-forecasting-result-presentation.v1" as const,
    forecast_series_label: "Forecast",
    future_time_index_label: "Period",
    forecast_value_label: "Passengers",
    model_section_label: "Model",
    decimal_places: 1,
  };

  const forecastingContext: ContextPayloadFixture = {
    ...contextPayload,
    problem_type: "univariate_forecasting",
    result_card: forecastingResultCardPresentation,
  };

  const validForecastResult = {
    schema_version: "univariate-forecasting-result.v1",
    problem_type: "univariate_forecasting",
    forecast_origin: "2026-01",
    frequency: "Monthly",
    forecast_horizon: 3,
    forecast_points: [
      { horizon_step: 1, future_time_index: "2026-02", forecast: 120.4 },
      { horizon_step: 2, future_time_index: "2026-03", forecast: 121.1 },
      { horizon_step: 3, future_time_index: "2026-04", forecast: 119.8 },
    ],
    model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
  };

  function installForecastingFormFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (init?.method === "POST" && url.endsWith(`/datasets/${slug}/inference`)) {
        return jsonResponse({ dataset_slug: slug, result: validForecastResult });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: forecastingContext });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: {} });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({
          dataset_slug: slug,
          visualizations: { charts: [], dataset_statistics: { instance_count: 48 } },
        });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: forecastingContractPayload,
          result_contract: forecastingResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("does not crash on public-contract v2 metadata and reports Features as 0", async () => {
    installForecastingFormFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await waitFor(() => {
      const featuresItem = screen.getByText("Features").closest(".dataset-detail-header__metadata-item");
      expect(featuresItem).toBeInTheDocument();
      expect(within(featuresItem as HTMLElement).getByText("0")).toBeInTheDocument();
    });
  });

  it("renders the forecasting history-series form with read-only horizon guidance, no editable horizon control", async () => {
    installForecastingFormFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));

    expect(await screen.findByLabelText("Period")).toBeInTheDocument();
    expect(screen.getByLabelText("Passengers")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/not editable/i)).toBeInTheDocument();
    // Exactly the two governed history inputs for the single initial row --
    // never a third, horizon-editing control.
    expect(document.querySelectorAll('input[type="text"], input[type="number"]')).toHaveLength(2);
  });

  it("executes real forecasting inference and renders the shared forecast-series result using the published presentation", async () => {
    const fetchMock = installForecastingFormFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByLabelText("Period");

    fireEvent.change(screen.getByLabelText("Period"), { target: { value: "2026-01" } });
    fireEvent.change(screen.getByLabelText("Passengers"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("120.4")).toBeInTheDocument();
    // "Seasonal Trend" also appears in the header's read-only model badge --
    // assert the result card's own occurrence, not global uniqueness.
    expect(screen.getAllByText("Seasonal Trend").length).toBeGreaterThanOrEqual(1);

    const postCalls = fetchMock.mock.calls.filter(
      (call) => call[1]?.method === "POST" && String(call[0]).endsWith(`/datasets/${slug}/inference`),
    );
    expect(postCalls).toHaveLength(1);
    expect(JSON.parse(String(postCalls[0][1]?.body))).toEqual({
      history: [{ period: "2026-01", passengers: 100 }],
    });
  });
});

// Project Spec S0271: public Dataset Detail Inference-tab availability derives
// only from the active public contract's S0269
// predictive_interaction.public_prediction.applicability -- never dataset
// slug, model family, problem type alone, or a stale bound_predict_view_id.
describe("DatasetPage capability-driven public prediction surface (Project Spec S0271)", () => {
  const forecastingBase = {
    schema_version: "2.0.0",
    problem_type: "univariate_forecasting",
    input_kind: "history_series",
    history_series: {
      time_index_field: { name: "period", label: "Period", value_kind: "calendar_period" as const, display_order: 1 },
      target_field: { name: "passengers", label: "Passengers", value_kind: "number" as const, display_order: 2 },
      frequency: "Monthly",
    },
    forecast: { forecast_horizon: 3, horizon_user_editable: false as const },
  };

  const historicalForecastingContract = { ...forecastingBase };
  const availableForecastingContract = {
    ...forecastingBase,
    predictive_interaction: {
      history_target_values: { affect_forecast: false },
      public_prediction: { applicability: "available" as const },
    },
  };
  const notApplicableForecastingContract = {
    ...forecastingBase,
    predictive_interaction: {
      history_target_values: { affect_forecast: false },
      public_prediction: { applicability: "not_applicable" as const },
    },
  };

  const forecastingResultContract = {
    status: "available" as const,
    semantics: {
      schema_version: "univariate-forecasting-result-semantics.v1" as const,
      problem_type: "univariate_forecasting" as const,
      result_schema_version: "univariate-forecasting-result.v1" as const,
      primary_output: "forecast_series" as const,
      output_structure: "ordered_forecast_points" as const,
      forecast_value_kind: "continuous_numeric" as const,
      forecast_count_source: "forecast_horizon" as const,
      model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
    },
  };

  function installCapabilityFetchMock(options: {
    contract: unknown;
    resultContract?: unknown;
    boundPredictViewId?: string | null;
    documentation?: { format: "markdown"; content: string };
  }) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: {
            ...contextPayload,
            problem_type: "univariate_forecasting",
            bound_predict_view_id: options.boundPredictViewId ?? null,
            documentation: options.documentation ?? { format: "markdown", content: "Synthetic documentation body." },
          },
        });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) {
        return jsonResponse({ dataset_slug: slug, metrics: {} });
      }
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({
          dataset_slug: slug,
          visualizations: { charts: [], dataset_statistics: { instance_count: 48 } },
        });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: options.contract,
          result_contract: options.resultContract ?? forecastingResultContract,
        });
      }
      if (url.endsWith(`/datasets/${slug}`)) {
        return jsonResponse(datasetMetadata);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("keeps the Inference tab for a historical forecasting v2 contract without predictive_interaction", async () => {
    installCapabilityFetchMock({ contract: historicalForecastingContract });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByRole("tab", { name: "Inference" })).toBeInTheDocument();
  });

  it("keeps the Inference tab when applicability is available", async () => {
    installCapabilityFetchMock({ contract: availableForecastingContract });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByRole("tab", { name: "Inference" })).toBeInTheDocument();
  });

  it("keeps the Inference tab for a scalar historical contract", async () => {
    installCapabilityFetchMock({ contract: contractPayload, resultContract: resultContractAvailable });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    expect(await screen.findByRole("tab", { name: "Inference" })).toBeInTheDocument();
  });

  it("hides the Inference tab when applicability is not_applicable", async () => {
    installCapabilityFetchMock({ contract: notApplicableForecastingContract });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("tab", { name: "Inference" })).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("tab").map((tab) => tab.textContent),
    ).toEqual(["Overview", "Documentation"]);
  });

  it("keeps Overview and Documentation usable when Inference is not_applicable", async () => {
    installCapabilityFetchMock({
      contract: notApplicableForecastingContract,
      documentation: { format: "markdown", content: "Capability-independent documentation." },
    });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await screen.findByRole("tab", { name: "Documentation" });
    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
    expect(await screen.findByText("Capability-independent documentation.")).toBeInTheDocument();
  });

  it("does not fetch bound Predict View customization when a stale bound_predict_view_id is present but applicability is not_applicable", async () => {
    const fetchMock = installCapabilityFetchMock({
      contract: notApplicableForecastingContract,
      boundPredictViewId: "stale-bound-view",
    });
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("tab", { name: "Inference" })).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).includes("/customization")),
    ).toBe(false);
  });

  it("still fetches bound Predict View customization when applicability is available", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/views/bound-view/customization`)) {
        return jsonResponse({}, 404);
      }
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: { ...contextPayload, problem_type: "univariate_forecasting", bound_predict_view_id: "bound-view" },
        });
      }
      if (url.endsWith(`/datasets/${slug}/metrics`)) return jsonResponse({ dataset_slug: slug, metrics: {} });
      if (url.endsWith(`/datasets/${slug}/visualizations`)) {
        return jsonResponse({ dataset_slug: slug, visualizations: { charts: [], dataset_statistics: { instance_count: 48 } } });
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: availableForecastingContract, result_contract: forecastingResultContract });
      }
      if (url.endsWith(`/datasets/${slug}`)) return jsonResponse(datasetMetadata);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderDatasetPage();
    await screen.findByRole("heading", { name: "Synthetic Demo Dataset", level: 1 });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).includes(`/views/bound-view/customization`)),
      ).toBe(true);
    });
  });
});
