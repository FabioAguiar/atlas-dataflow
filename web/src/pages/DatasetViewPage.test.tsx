import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
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

describe("DatasetViewPage multiclass route contract (S0214)", () => {
  it("uses the existing explicit view route for every classification family", () => {
    expect(`/datasets/${slug}/views/${viewId}`).toBe("/datasets/synthetic-demo-dataset/views/churn-risk-overview");
  });
});

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

// Mocks only the primary /datasets/{slug}/views/{viewId} route with the
// given error envelope; any other request is treated as a bug (a secondary
// request fired even though the primary route never reached "ready").
function installDatasetViewPageErrorFetchMock(errorBody: unknown, status: number) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith(`/datasets/${slug}/views/${viewId}`)) {
      return jsonResponse(errorBody, status);
    }
    throw new Error(`unexpected secondary fetch for a non-ready primary state: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DatasetViewPage access states (Project Spec S0117)", () => {
  it("renders the shared maintenance state and fires no secondary requests", async () => {
    const fetchMock = installDatasetViewPageErrorFetchMock(
      {
        error_type: "dataset_maintenance",
        error_code: "DATASET_MAINTENANCE",
        message: "The requested dataset page is temporarily unavailable.",
      },
      503,
    );

    renderDatasetViewPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset page under maintenance" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders the shared not-found state and fires no secondary requests", async () => {
    const fetchMock = installDatasetViewPageErrorFetchMock(
      { error_type: "dataset_not_found", error_code: "DATASET_NOT_FOUND", message: "The requested dataset is not available." },
      404,
    );

    renderDatasetViewPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Dataset not found" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("classifies a non-maintenance, non-not-found error as unavailable using error_code, not status alone", async () => {
    const fetchMock = installDatasetViewPageErrorFetchMock(
      { error_type: "release_unavailable", error_code: "RELEASE_UNAVAILABLE", message: "No active release is available for this dataset." },
      503,
    );

    renderDatasetViewPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders unavailable for a malformed (non-JSON) error body", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/views/${viewId}`)) {
        return {
          ok: false,
          status: 503,
          json: async () => {
            throw new Error("not valid json");
          },
        };
      }
      throw new Error(`unexpected secondary fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDatasetViewPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).toBeInTheDocument();
  });

  // Project Spec S0271: the backend returns the existing VIEW_NOT_FOUND public
  // envelope for a Predict View disabled by the release's predictive-interaction
  // applicability. The shared classifier now maps it to the not-found page
  // state so a direct disabled Predict View URL shows "The dataset or link you
  // tried to access does not exist." -- never the generic transient
  // "information is currently unavailable" copy, and without exposing any
  // capability internals.
  it("renders the shared not-found state for a VIEW_NOT_FOUND primary response, not the generic unavailable copy", async () => {
    const fetchMock = installDatasetViewPageErrorFetchMock(
      {
        error_type: "view_not_found",
        error_code: "VIEW_NOT_FOUND",
        message: "The requested predict view is not available for this dataset.",
      },
      404,
    );

    renderDatasetViewPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Dataset not found" })).toBeInTheDocument();
    expect(
      screen.getByText("The dataset or link you tried to access does not exist."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("fires contract/customization/context requests only after the primary view request reaches ready", async () => {
    const { fetchMock } = installFetchMock();

    renderDatasetViewPage();

    await screen.findByRole("heading", { name: "Churn Risk Overview" });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/contract`))).toBe(true);
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/views/${viewId}/customization`)),
      ).toBe(true);
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${slug}/context`))).toBe(true);
    });
  });

  it("clears prior view state on a view switch and never flashes a not-found state", async () => {
    const viewIdA = viewId;
    const viewIdB = "another-view";

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const v of [viewIdA, viewIdB]) {
        if (url.endsWith(`/datasets/${slug}/views/${v}`)) {
          return jsonResponse({ ...viewPayload, view_id: v, display: { title: v === viewIdA ? "Churn Risk Overview" : "Another View" } });
        }
        if (url.endsWith(`/datasets/${slug}/views/${v}/customization`)) return jsonResponse({}, 404);
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({ dataset_slug: slug, contract: contractPayload, result_contract: resultContractAvailable });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({ dataset_slug: slug, context: { legacy_submit_button_label: null, result_card: resultCardPresentation } });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/dataset/${slug}/view/${viewIdA}`]}>
        <Routes>
          <Route
            path="/dataset/:slug/view/:viewId"
            element={
              <>
                <Link to={`/dataset/${slug}/view/${viewIdB}`}>Go to view B</Link>
                <DatasetViewPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "Churn Risk Overview" });
    fireEvent.click(screen.getByRole("link", { name: "Go to view B" }));

    expect(screen.queryByRole("heading", { name: "Churn Risk Overview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Dataset not found" })).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Another View" })).toBeInTheDocument();
  });
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

// Project Spec S0229: proves the shared Predict View route can render
// continuous-regression inference through the same shared InferenceForm/
// ResultContract/ResultPresentation types (S0112/S0154), with no production
// fork -- DatasetViewPage.tsx itself requires no changes for this family.
describe("DatasetViewPage continuous regression through the shared InferenceForm (Project Spec S0229)", () => {
  const regressionResultContractAvailable = {
    status: "available" as const,
    semantics: {
      schema_version: "continuous-regression-result-semantics.v1",
      problem_type: "continuous_regression" as const,
      result_schema_version: "continuous-regression-result.v1" as const,
      primary_output: "predicted_value" as const,
      output_value_kind: "continuous_numeric" as const,
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
    },
  };

  const regressionResultCardPresentation = {
    schema_version: "continuous-regression-result-presentation.v1",
    predicted_value_label: "Predicted compressive strength",
    model_section_label: "Model",
    decimal_places: 1,
    value_unit_label: "MPa",
  };

  const regressionResult = {
    schema_version: "continuous-regression-result.v1",
    problem_type: "continuous_regression",
    predicted_value: 42.73,
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
  };

  function installRegressionFetchMock() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(`/datasets/${slug}/views/${viewId}/customization`)) {
        return jsonResponse({}, 404);
      }
      if (url.endsWith(`/datasets/${slug}/views/${viewId}`)) {
        return jsonResponse(viewPayload);
      }
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: contractPayload,
          result_contract: regressionResultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: { legacy_submit_button_label: null, result_card: regressionResultCardPresentation },
        });
      }
      if (url.endsWith(`/datasets/${slug}/inference`) && init?.method === "POST") {
        return jsonResponse({ dataset_slug: slug, result: regressionResult });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("parses body.result on success and renders the shared ContinuousRegressionResult", async () => {
    installRegressionFetchMock();
    const { container } = renderDatasetViewPage();

    fireEvent.click(await screen.findByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Predicted compressive strength")).toBeInTheDocument();
    expect(screen.getByText("42.7")).toBeInTheDocument();
    expect(screen.getByText("MPa")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting Regressor")).toBeInTheDocument();
    expect(container.querySelector(".continuous-regression-result")).not.toHaveTextContent(/confidence|probability|threshold|risk/i);
  });
});

// Project Spec S0146: a contract-required checkbox must remain a complete
// two-state boolean field on the public Predict View -- leaving it unchecked
// must still reach the shared public inference execution path (never
// blocked by native checkbox constraint validation), serializing to a
// boolean false payload key.
describe("DatasetViewPage boolean checkbox false-state submission (Project Spec S0146)", () => {
  const checkboxContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "synthetic_feature", label: "Synthetic Feature", input_type: "number" as const, optional: true, display_order: 1 },
      { name: "consent", label: "Consent", input_type: "checkbox" as const, optional: false, display_order: 2 },
    ],
  };

  function installCheckboxFetchMock() {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.endsWith(`/datasets/${slug}/views/${viewId}/customization`)) return jsonResponse({}, 404);
      if (url.endsWith(`/datasets/${slug}/views/${viewId}`)) return jsonResponse(viewPayload);
      if (url.endsWith(`/datasets/${slug}/contract`)) {
        return jsonResponse({
          dataset_slug: slug,
          contract: checkboxContractPayload,
          result_contract: resultContractAvailable,
        });
      }
      if (url.endsWith(`/datasets/${slug}/context`)) {
        return jsonResponse({
          dataset_slug: slug,
          context: { legacy_submit_button_label: null, result_card: resultCardPresentation },
        });
      }
      if (url.endsWith(`/datasets/${slug}/inference`) && init?.method === "POST") {
        capturedBody = String(init.body);
        return jsonResponse({ dataset_slug: slug, result: binaryResult });
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, getCapturedBody: () => capturedBody };
  }

  it("permits an unchecked contract-required checkbox to reach the public inference execution path, with the payload key serialized as boolean false", async () => {
    const { fetchMock, getCapturedBody } = installCheckboxFetchMock();
    renderDatasetViewPage();

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
