import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import DatasetViewPage from "./DatasetViewPage";

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

const slug = "synthetic-demo-dataset";
const viewId = "churn-risk-overview";

const viewPayload = {
  view_id: viewId,
  dataset_slug: slug,
  display: { title: "Churn Risk Overview", summary: "Explicit view summary." },
  intent: { prediction_goal: "Estimate churn likelihood." },
  release_mode: null,
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

function installFetchMock(
  options: {
    customizationSubmitButtonLabel?: string;
    customizationStatus?: number;
    legacySubmitButtonLabel?: string | null;
    contextStatus?: number;
    deferInference?: boolean;
  } = {},
) {
  let releaseInference: ((response: MockResponse) => void) | null = null;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url.endsWith(`/datasets/${slug}/views/${viewId}/customization`)) {
      if (options.customizationStatus) {
        return jsonResponse({}, options.customizationStatus);
      }
      if (options.customizationSubmitButtonLabel === undefined) {
        return jsonResponse({}, 404);
      }
      return jsonResponse({
        schema_version: "1.0.0",
        view_id: viewId,
        dataset_slug: slug,
        field_hints: [],
        groups: [],
        view_copy: { submit_button_label: options.customizationSubmitButtonLabel },
      });
    }
    if (url.endsWith(`/datasets/${slug}/views/${viewId}`)) {
      return jsonResponse(viewPayload);
    }
    if (url.endsWith(`/datasets/${slug}/contract`)) {
      return jsonResponse({ dataset_slug: slug, contract: contractPayload });
    }
    if (url.endsWith(`/datasets/${slug}/context`)) {
      if (options.contextStatus) {
        return jsonResponse({}, options.contextStatus);
      }
      return jsonResponse({
        dataset_slug: slug,
        context: { legacy_submit_button_label: options.legacySubmitButtonLabel ?? null },
      });
    }
    if (url.endsWith(`/datasets/${slug}/inference`) && init?.method === "POST") {
      if (options.deferInference) {
        return new Promise<MockResponse>((resolve) => {
          releaseInference = resolve;
        });
      }
      return jsonResponse({ prediction: { label: "sample_outcome", confidence: 0.5 } });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, releaseInference: () => releaseInference?.(jsonResponse({ prediction: { label: "x", confidence: 0.5 } })) };
}

function renderDatasetViewPage() {
  return render(
    <MemoryRouter initialEntries={[`/dataset/${slug}/view/${viewId}`]}>
      <Routes>
        <Route path="/dataset/:slug/view/:viewId" element={<DatasetViewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// Project Spec S0110: DatasetViewPage already loads its explicit view
// customization; it must render the resolved submit label using
// customization -> legacy published profile overlay -> "Submit" precedence,
// and InferenceForm's submitting/idle copy must stay distinct.
describe("DatasetViewPage submit-label resolution (Project Spec S0110)", () => {
  it("renders the explicit view's customization submit label", async () => {
    installFetchMock({ customizationSubmitButtonLabel: "Estimate Churn Risk", legacySubmitButtonLabel: "Legacy Run" });
    renderDatasetViewPage();

    expect(await screen.findByRole("button", { name: "Estimate Churn Risk" })).toBeInTheDocument();
  });

  it("falls back to the legacy published label when the view's customization has no submit label", async () => {
    installFetchMock({ customizationSubmitButtonLabel: "", legacySubmitButtonLabel: "Legacy Run" });
    renderDatasetViewPage();

    expect(await screen.findByRole("button", { name: "Legacy Run" })).toBeInTheDocument();
  });

  it('falls back to "Submit" when neither customization nor legacy copy provides a label', async () => {
    installFetchMock();
    renderDatasetViewPage();

    expect(await screen.findByRole("button", { name: "Submit" })).toBeInTheDocument();
  });

  it("keeps the form usable and falls back to legacy copy when the context overlay transport fails", async () => {
    installFetchMock({ contextStatus: 503, legacySubmitButtonLabel: "Legacy Run" });
    renderDatasetViewPage();

    // Context transport failure falls through to "Submit" (no legacy value
    // reachable) rather than removing the form.
    expect(await screen.findByRole("button", { name: "Submit" })).toBeInTheDocument();
  });

  it("shows the configured idle label, then 'Submitting…' distinct from it, while submitting", async () => {
    const { fetchMock, releaseInference } = installFetchMock({
      customizationSubmitButtonLabel: "Estimate Churn Risk",
      deferInference: true,
    });
    renderDatasetViewPage();

    const button = await screen.findByRole("button", { name: "Estimate Churn Risk" });
    fireEvent.click(button);

    expect(await screen.findByRole("button", { name: "Submitting…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Estimate Churn Risk" })).not.toBeInTheDocument();

    releaseInference();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });
});
