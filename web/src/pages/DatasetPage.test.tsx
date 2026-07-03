import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
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
  render(
    <MemoryRouter initialEntries={[`/dataset/${slug}`]}>
      <Routes>
        <Route path="/dataset/:slug" element={<DatasetPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
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
});
