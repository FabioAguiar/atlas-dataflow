import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DatasetAdminPage from "./DatasetAdminPage";

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

const datasetSlug = "telco-customer-churn";
const viewId = "churn-risk-overview";

const publicProfile = {
  schema_version: "0.1.0",
  dataset_slug: datasetSlug,
  display: {
    title: "Curated churn profile",
    subtitle: "Operator-authored public subtitle",
    problem_summary_title: "Churn context",
    problem_summary_body: "Explains customer churn for a public audience.",
  },
  home_card: {
    icon: "telecom",
    short_description: "Curated home card copy",
    primary_metric_key: "auc_roc",
  },
  theme: {
    preset: "atlas-green",
  },
  inference_presentation: {
    bound_predict_view_id: viewId,
  },
  result_card: {
    probability_label: "Churn probability",
    submit_button_label: "Run prediction",
    model_label: "Retention model",
    badge_preset: "risk",
    badge_labels: {
      high: "High risk",
      medium: "Medium risk",
      low: "Low risk",
    },
  },
};

const customization = {
  schema_version: "1.0.0",
  dataset_slug: datasetSlug,
  view_id: viewId,
  field_hints: [
    {
      field_name: "tenure",
      display_label: "Tenure",
      explanatory_copy: "Customer tenure in months",
      display_order_hint: 1,
      group: "account",
    },
    {
      field_name: "MonthlyCharges",
      display_label: "Monthly charges",
      explanatory_copy: "Monthly bill amount",
      display_order_hint: 2,
      group: "charges",
    },
  ],
  groups: [
    { group_id: "account", label: "Account profile", description: "Account attributes" },
    { group_id: "charges", label: "Charges", description: "Billing attributes" },
  ],
  contract_precedence: {
    canonical_contracts_are_source_of_truth: true,
    customization_defines_runtime_validation: false,
    customization_duplicates_contract: false,
  },
};

function installFetchMock(options: { rejectProfileSave?: boolean; rejectPublish?: boolean; rejectVisibility?: boolean } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url.endsWith("/datasets")) {
      return jsonResponse({
        datasets: [
          {
            dataset_slug: datasetSlug,
            title: "Telco Customer Churn",
            summary: "Customer churn prediction dataset",
            domain: "telecom",
            visibility: "public",
            tags: ["telecom"],
            problem_type: "binary_classification",
          },
        ],
      });
    }
    if (url.includes("/context")) {
      return jsonResponse({
        context: {
          title: "Telco Customer Churn",
          summary: "Baseline churn problem summary",
          domain: "telecom",
          tags: ["telecom"],
          problem_type: "binary_classification",
          prediction_target_description: "Customer churn",
        },
      });
    }
    if (url.includes("/contract")) {
      return jsonResponse({
        contract: {
          schema_version: "1.0.0",
          features: [
            { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
            { name: "MonthlyCharges", label: "Monthly charges", input_type: "number", optional: true, display_order: 2 },
          ],
        },
      });
    }
    if (url.includes("/metrics")) {
      return jsonResponse({ metrics: { evaluation: { metrics: { auc_roc: 0.93, accuracy: 0.86 } } } });
    }
    if (url.includes("/model-card")) {
      return jsonResponse({ model_card: { content: JSON.stringify({ model_summary: "Validation model" }) } });
    }
    if (url.includes("/visualizations")) {
      return jsonResponse({ visualizations: {} });
    }
    if (url.endsWith(`/datasets/${datasetSlug}/views`)) {
      return jsonResponse({ views: [{ view_id: viewId, display: { title: "Churn risk overview" } }] });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/publish`) && init?.method === "PUT") {
      if (options.rejectPublish) {
        return jsonResponse(
          {
            published: false,
            errors: [{ field: "profile", code: "PROFILE_PUBLISH_FAILED", message: "Snapshot validation failed." }],
          },
          422,
        );
      }
      return jsonResponse({
        published: true,
        snapshot: {
          source_draft_schema_version: publicProfile.schema_version,
          published_at: "2026-07-03T17:30:00Z",
          profile: publicProfile,
        },
        errors: [],
      });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/visibility`) && init?.method === "PUT") {
      if (options.rejectVisibility) {
        return jsonResponse(
          {
            error_code: "PROFILE_VISIBILITY_PAYLOAD_INVALID",
            message: "Visibility payload is invalid.",
          },
          400,
        );
      }
      const body = typeof init.body === "string" ? (JSON.parse(init.body) as { visible?: boolean }) : {};
      return jsonResponse({
        dataset_slug: datasetSlug,
        visible: body.visible ?? true,
        updated_at: "2026-07-03T17:35:00Z",
      });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) && init?.method === "PUT") {
      if (options.rejectProfileSave) {
        return jsonResponse(
          {
            saved: false,
            errors: [{ field: "display.title", code: "TITLE_REQUIRED", message: "Title is required." }],
          },
          422,
        );
      }
      return jsonResponse({ saved: true, profile: publicProfile });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`)) {
      return jsonResponse({ draft_exists: true, profile: publicProfile });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) && init?.method === "PUT") {
      return jsonResponse({ saved: true, customization });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`)) {
      return jsonResponse({ customization_exists: true, customization });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function loadDraftOnly() {
  fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "operator-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Load draft" }));
  expect(await screen.findByText("Draft loaded.")).toBeInTheDocument();
}

async function loadDraftAndCustomization() {
  await loadDraftOnly();
  fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
  fireEvent.click(screen.getByRole("button", { name: "Load customization" }));
  expect(await screen.findByText("Customization loaded.")).toBeInTheDocument();
}

describe("DatasetAdminPage", () => {
  beforeEach(() => {
    Element.prototype.setPointerCapture = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("wires Publishing tab actions and derives lifecycle labels from saved, published, and visibility state", async () => {
    const fetchMock = installFetchMock();
    render(<DatasetAdminPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Dataset")).toHaveValue(datasetSlug);
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(screen.getByText("Not Published")).toBeInTheDocument();

    await loadDraftOnly();
    expect(screen.getByText("Draft")).toBeInTheDocument();

    const callsBeforePreview = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Preview Draft" }));
    expect(screen.getByRole("heading", { name: "Curated churn profile" })).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(callsBeforePreview);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`))).toHaveLength(0);

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(screen.getByRole("button", { name: "Save Draft" }));
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Publish Changes" }));
    expect(await screen.findByText("Published")).toBeInTheDocument();
    expect(screen.getByText("Published at 2026-07-03T17:30:00Z.")).toBeInTheDocument();

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`));
    expect(publishCall?.[1]).toMatchObject({
      method: "PUT",
      headers: { "X-Admin-Token": "operator-token" },
    });

    fireEvent.click(screen.getByLabelText("Visible Publicly"));
    expect(await screen.findByText("Hidden")).toBeInTheDocument();
    expect(screen.getByText("Latest published snapshot is hidden publicly.")).toBeInTheDocument();

    const visibilityCalls = fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`));
    expect(visibilityCalls).toHaveLength(1);
    expect(visibilityCalls[0]?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Token": "operator-token" },
      body: JSON.stringify({ visible: false }),
    });
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(1);

    fireEvent.click(screen.getByLabelText("Visible Publicly"));
    expect(await screen.findByText("Published")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Display title"), { target: { value: "Edited churn profile" } });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(screen.getByText("Unpublished Changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish Changes" })).toBeDisabled();
    expect(screen.getByText(/Save Draft before publishing/)).toBeInTheDocument();
  });

  it("surfaces backend profile validation feedback without publishing side effects", async () => {
    installFetchMock({ rejectProfileSave: true });
    render(<DatasetAdminPage />);

    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("Draft rejected by backend validation")).toBeInTheDocument();
    expect(screen.getByText(/display.title - TITLE_REQUIRED - Title is required./)).toBeInTheDocument();
  });

  it("surfaces publish validation feedback without changing visibility state", async () => {
    installFetchMock({ rejectPublish: true });
    render(<DatasetAdminPage />);

    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish Changes" }));

    expect(await screen.findByText("Publishing action rejected by backend validation.")).toBeInTheDocument();
    expect(screen.getByText(/profile - PROFILE_PUBLISH_FAILED - Snapshot validation failed./)).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("renders all Live Preview modes from the loaded draft and customization", async () => {
    installFetchMock();
    render(<DatasetAdminPage />);

    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    expect(screen.getByRole("heading", { name: "Curated churn profile" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Home card" }));
    expect(screen.getByText("Curated home card copy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Result card" }));
    expect(screen.getByText(/Placeholder preview only, not a real prediction./)).toBeInTheDocument();
    expect(screen.getByText("Churn probability")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inference form layout" }));
    expect(screen.getByText("Account profile")).toBeInTheDocument();
    expect(screen.getByText("Tenure")).toBeInTheDocument();
  });

  it("shows pointer-following drag overlay activity for fields and groups", async () => {
    installFetchMock();
    render(<DatasetAdminPage />);

    await loadDraftAndCustomization();

    const groupsPanel = screen.getByLabelText("Groups");
    const groupDragHandle = within(groupsPanel).getByRole("button", { name: "Drag group Account profile" });
    fireEvent.pointerDown(groupDragHandle, { pointerId: 1, clientX: 12, clientY: 16 });
    expect(screen.getByText("Account profile")).toBeInTheDocument();
    fireEvent.pointerUp(groupDragHandle, { pointerId: 1, clientX: 18, clientY: 24 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(1);
    });

    const fieldsPanel = screen.getByLabelText("Field presentation");
    const fieldDragHandle = within(fieldsPanel).getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });
    expect(screen.getByText("Tenure")).toBeInTheDocument();
    fireEvent.pointerCancel(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(2);
    });
  });
});
