import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./DatasetPage";

/**
 * Project Spec S0216 Desired Change AL: proves the existing generic public
 * dataset UI (InferenceForm, the shared Multiclass Result Card, PerformanceSummary,
 * and the shared ConfusionMatrix component) renders a Dry Bean-shaped native
 * multiclass response correctly, using only a synthetic fixture consistent
 * with the real native Atlas contracts this project spec introduces
 * (multiclass-result-semantics.v1, multiclass-classification-result.v1,
 * training-metrics.v2-derived public projection shape,
 * analytical-visualizations.v2-derived public projection shape). No
 * production frontend file is modified by this test.
 */

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

const slug = "dry-bean";

const DRY_BEAN_CLASS_IDS = ["BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SEKER", "SIRA"];

const datasetMetadata = {
  dataset_slug: slug,
  title: "Dry Bean",
  summary: "Estimate dry bean variety from reviewed geometric shape measurements.",
  domain: "agriculture",
  visibility: "public",
  tags: ["multiclass", "dry-bean"],
};

const contextPayload = {
  title: "Dry Bean",
  summary: "Estimate dry bean variety from reviewed geometric shape measurements.",
  domain: "agriculture",
  tags: ["multiclass", "dry-bean"],
  use_case: "Dry bean variety classification.",
  prediction_target_description: "Which of seven governed dry bean varieties a sample most likely belongs to.",
  problem_type: "multiclass_classification",
};

const contractPayload = {
  schema_version: "1.0.0",
  features: [
    { name: "Area", label: "Area", input_type: "number" as const, optional: false, display_order: 1 },
    { name: "Perimeter", label: "Perimeter", input_type: "number" as const, optional: false, display_order: 2 },
  ],
};

const multiclassResultContractAvailable = {
  status: "available" as const,
  semantics: {
    schema_version: "multiclass-result-semantics.v1" as const,
    problem_type: "multiclass_classification" as const,
    result_schema_version: "multiclass-classification-result.v1" as const,
    classes: DRY_BEAN_CLASS_IDS.map((class_id) => ({ class_id, display_label: class_id })),
    primary_output: "predicted_class" as const,
    probability_output: "class_probabilities" as const,
    decision: { strategy: "argmax" as const },
    model_descriptor: { model_family: "hist_gradient_boosting", display_name: "HistGradientBoosting" },
  },
};

const dryBeanMetricsPayload = {
  evaluation: {
    split_name: "test",
    sample_size: 2042,
    metrics: {
      f1_macro: 0.92,
      balanced_accuracy: 0.91,
      accuracy: 0.93,
    },
    metric_order: ["f1_macro", "balanced_accuracy", "accuracy"],
  },
};

const dryBeanVisualizationsPayload = {
  charts: [
    {
      id: "target_distribution",
      title: "Target Distribution",
      type: "bar",
      x_label: "Class",
      y_label: "Rows",
      data: DRY_BEAN_CLASS_IDS.map((name, index) => ({ name, value: 1000 + index })),
    },
    {
      id: "feature_importance",
      title: "HGB Feature Importance",
      type: "bar",
      x_label: "Feature",
      y_label: "Importance",
      data: [
        { name: "Area", value: 0.4 },
        { name: "Perimeter", value: 0.3 },
      ],
    },
  ],
  confusion_matrix: {
    ordered_class_ids: DRY_BEAN_CLASS_IDS,
    matrix: DRY_BEAN_CLASS_IDS.map((_, rowIndex) =>
      DRY_BEAN_CLASS_IDS.map((_, columnIndex) => (rowIndex === columnIndex ? 0.9 : 0.1 / 6)),
    ),
    row_axis: "true_class",
    column_axis: "predicted_class",
  },
  dataset_statistics: { instance_count: 13611 },
};

const dryBeanPredictionResult = {
  schema_version: "multiclass-classification-result.v1",
  problem_type: "multiclass_classification",
  predicted_class: { class_id: "SEKER", display_label: "SEKER" },
  class_probabilities: DRY_BEAN_CLASS_IDS.map((class_id) => ({
    class_id,
    display_label: class_id,
    probability: class_id === "SEKER" ? 0.7 : 0.05,
  })),
  decision: { strategy: "argmax" },
  model_descriptor: { model_family: "hist_gradient_boosting", display_name: "HistGradientBoosting" },
};

function installDryBeanFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (init?.method === "POST" && url.endsWith(`/datasets/${slug}/inference`)) {
      return jsonResponse({ dataset_slug: slug, result: dryBeanPredictionResult });
    }
    if (url.endsWith(`/datasets/${slug}/context`)) {
      return jsonResponse({ dataset_slug: slug, context: contextPayload });
    }
    if (url.endsWith(`/datasets/${slug}/metrics`)) {
      return jsonResponse({ dataset_slug: slug, metrics: dryBeanMetricsPayload });
    }
    if (url.endsWith(`/datasets/${slug}/visualizations`)) {
      return jsonResponse({ dataset_slug: slug, visualizations: dryBeanVisualizationsPayload });
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

describe("DatasetPage Dry Bean native multiclass integration (Project Spec S0216)", () => {
  it("renders the Multiclass Classification problem type on Overview", async () => {
    installDryBeanFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Dry Bean", level: 1 });
    expect(await screen.findByText("Multiclass Classification")).toBeInTheDocument();
  });

  function fillRequiredFeatureFields() {
    fireEvent.change(screen.getByRole("spinbutton", { name: /Area/ }), { target: { value: "15000" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Perimeter/ }), { target: { value: "450" } });
  }

  it("submits from the shared InferenceForm and renders the shared Multiclass Result Card with all seven class probabilities", async () => {
    const fetchMock = installDryBeanFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Dry Bean", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByRole("spinbutton", { name: /Area/ });
    fillRequiredFeatureFields();

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => {
      expect(container.querySelector(".multiclass-classification-result")).toBeInTheDocument();
    });
    const resultElement = container.querySelector(".multiclass-classification-result") as HTMLElement;

    // The predicted class is rendered twice within the result card: once
    // in the headline prediction section, once inside the full
    // distribution list.
    expect(within(resultElement).getAllByText("SEKER").length).toBeGreaterThanOrEqual(2);
    expect(within(resultElement).getAllByText("70%").length).toBeGreaterThanOrEqual(2);
    expect(within(resultElement).getByText("HistGradientBoosting")).toBeInTheDocument();

    // All seven governed class probabilities are rendered, not just the
    // predicted class.
    for (const classId of DRY_BEAN_CLASS_IDS) {
      expect(within(resultElement).getAllByText(classId).length).toBeGreaterThan(0);
    }
    expect(within(resultElement).getAllByRole("progressbar")).toHaveLength(7);

    const postCalls = fetchMock.mock.calls.filter(
      (call) => call[1]?.method === "POST" && String(call[0]).endsWith(`/datasets/${slug}/inference`),
    );
    expect(postCalls).toHaveLength(1);
  });

  it("renders explicit F1 Macro / Balanced Accuracy metrics, never a binary threshold or risk label", async () => {
    installDryBeanFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Dry Bean", level: 1 });
    expect(await screen.findByText("F1 Macro")).toBeInTheDocument();
    expect(screen.getByText("Balanced Accuracy")).toBeInTheDocument();

    expect(container).not.toHaveTextContent(/\bthreshold\b/i);
    expect(container).not.toHaveTextContent(/\brisk\b/i);
    expect(container).not.toHaveTextContent(/confidence/i);
  });

  it("renders the shared Normalized Confusion Matrix for all seven governed classes", async () => {
    installDryBeanFetchMock();
    renderDatasetPage();

    await screen.findByRole("heading", { name: "Dry Bean", level: 1 });
    const heading = await screen.findByRole("heading", { name: "Confusion Matrix" });
    expect(heading).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "Confusion matrix" });
    for (const classId of DRY_BEAN_CLASS_IDS) {
      expect(within(table).getAllByText(classId).length).toBeGreaterThan(0);
    }
    expect(within(table).getAllByText("90.0%").length).toBeGreaterThan(0);
  });

  it("submitting the form fires no binary-only threshold/interpretation UI in the Inference panel", async () => {
    installDryBeanFetchMock();
    const { container } = renderDatasetPage();

    await screen.findByRole("heading", { name: "Dry Bean", level: 1 });
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    await screen.findByRole("spinbutton", { name: /Area/ });
    fillRequiredFeatureFields();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    const inferencePanel = Array.from(
      container.querySelectorAll<HTMLElement>(".dataset-detail-tabs__panel"),
    ).find((panel) => panel.getAttribute("hidden") === null)!;
    await waitFor(() => {
      expect(inferencePanel.querySelector(".multiclass-classification-result")).toBeInTheDocument();
    });
    expect(inferencePanel.querySelector(".binary-classification-result")).not.toBeInTheDocument();
  });
});
