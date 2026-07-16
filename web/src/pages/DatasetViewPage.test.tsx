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

// Project Spec S0112: real result_contract/result_card/inference result
// fixtures -- the legacy { prediction: { label, confidence } } shape is
// never used in these public tests.
const resultContractAvailable = {
  status: "available" as const,
  semantics: {
    schema_version: "binary-result-semantics.v1",
    problem_type: "binary_classification" as const,
    result_schema_version: "binary-classification-result.v1" as const,
    primary_output: "positive_class_probability" as const,
    positive_class: { class_id: "Yes", event_label: "Churn" },
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

const resultContractUnavailable = {
  status: "unavailable" as const,
  reason: "binary_result_semantics_unavailable",
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

const binaryResult = {
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
  interpretation: { preset: "risk", band_id: "high", bands: resultContractAvailable.semantics.interpretation.bands },
  model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
};

function installFetchMock(
  options: {
    customizationSubmitButtonLabel?: string;
    customizationStatus?: number;
    legacySubmitButtonLabel?: string | null;
    contextStatus?: number;
    deferInference?: boolean;
    resultContractStatus?: "available" | "unavailable";
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
      return jsonResponse({
        dataset_slug: slug,
        contract: contractPayload,
        result_contract: options.resultContractStatus === "unavailable" ? resultContractUnavailable : resultContractAvailable,
      });
    }
    if (url.endsWith(`/datasets/${slug}/context`)) {
      if (options.contextStatus) {
        return jsonResponse({}, options.contextStatus);
      }
      return jsonResponse({
        dataset_slug: slug,
        context: {
          legacy_submit_button_label: options.legacySubmitButtonLabel ?? null,
          result_card: resultCardPresentation,
        },
      });
    }
    if (url.endsWith(`/datasets/${slug}/inference`) && init?.method === "POST") {
      if (options.deferInference) {
        return new Promise<MockResponse>((resolve) => {
          releaseInference = resolve;
        });
      }
      return jsonResponse({ dataset_slug: slug, result: binaryResult });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    releaseInference: () => releaseInference?.(jsonResponse({ dataset_slug: slug, result: binaryResult })),
  };
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

// Project Spec S0112: DatasetViewPage renders the same shared Result Card
// surface as DatasetPage, parses body.result (never body.prediction), and
// respects the result_contract availability gate.
describe("DatasetViewPage shared Result Card surface (Project Spec S0112)", () => {
  it("renders the idle Result Card shell before submission when the result contract is available", async () => {
    installFetchMock();
    renderDatasetViewPage();

    expect(await screen.findByText("Submit the form to see the prediction.")).toBeInTheDocument();
  });

  it("disables submission and explains capability when the result contract is unavailable, without removing the form", async () => {
    installFetchMock({ resultContractStatus: "unavailable" });
    renderDatasetViewPage();

    expect(
      await screen.findByText("This active release does not currently expose a compatible result."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("parses body.result on success and renders the shared BinaryClassificationResult", async () => {
    installFetchMock();
    renderDatasetViewPage();

    fireEvent.click(await screen.findByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });
});
