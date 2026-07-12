import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DatasetAdminPage from "./DatasetAdminPage";

// DatasetAdminPage's Home card preview renders the shared DatasetCard
// component, which uses react-router-dom's <Link> -- it needs a Router
// ancestor the same way HomePage/DatasetPage tests already provide one.
function renderAdminPage() {
  return render(
    <MemoryRouter>
      <DatasetAdminPage />
    </MemoryRouter>,
  );
}

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

// Project Spec S0060: the exact internal-implementation phrases the spec
// forbids from normal operator-facing load/save/publish feedback. A
// case-insensitive full-document scan catches these regardless of which
// panel/status line they might otherwise have leaked into.
const FORBIDDEN_DRAFT_TERMS = ["draft endpoint", "profile draft model", "private/admin draft endpoint"];

function forbiddenDraftTermsPresent(): string[] {
  const text = document.body.textContent?.toLowerCase() ?? "";
  return FORBIDDEN_DRAFT_TERMS.filter((term) => text.includes(term));
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
    release_date_label: "2026-06-19",
    release_date_mode: "auto",
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

function installFetchMock(
  options: {
    rejectProfileSave?: boolean;
    rejectPublish?: boolean;
    rejectVisibility?: boolean;
    // Both overrides below exist only to make Live Preview reactivity
    // genuinely observable for fields whose shared-fixture defaults would
    // otherwise round-trip to an identical rendered value after an edit --
    // see the "updates each Live Preview mode's rendered output..." test.
    themePresetOverride?: string;
    metricsOverride?: Record<string, number>;
    // Marks one named contract feature as optional: false (required), used
    // only by the required-field-hiding-prevention test below. The shared
    // default fixture keeps both features optional: true so no other test's
    // rendered output changes.
    requiredFieldOverride?: string;
    // Opt-in only (default false). When true, profile-draft saves and
    // publishes echo the active profile so tests can observe saved-draft-
    // dependent publishing state without changing the shared stateless
    // default.
    trackProfileDraftSaves?: boolean;
    // Opt-in only (default false). When true, the customization PUT handler
    // stores the received body and both the PUT response and any subsequent
    // customization GET response echo that stored value instead of the
    // static default fixture -- used only by the group persistence-through-
    // reload test below. Every other test keeps the stateless default.
    trackCustomizationSaves?: boolean;
    // Opt-in only (default false). When true, the profile-draft GET reports
    // no existing backend draft/profile at all (draft_exists: false, profile:
    // null) instead of the shared publicProfile fixture -- used only by tests
    // that exercise the S0056 blank-authoring-form baseline. Project Spec
    // S0058 auto-loads the profile draft as soon as a Dataset Detail is
    // selected (there is no more manual "Load draft" step), so every other
    // test's default publicProfile fixture is now what the operator sees
    // immediately rather than only after an explicit load.
    noExistingDraft?: boolean;
    lastUpdated?: string;
    releaseDate?: string;
    releaseDateMode?: "auto" | "manual";
  } = {},
) {
  let savedProfileDraft: typeof publicProfile | null = null;
  let savedCustomization: typeof customization | null = null;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    // Checked before the generic "/datasets" endsWith check below, since
    // "/admin/datasets" also satisfies url.endsWith("/datasets").
    if (url.endsWith("/admin/datasets")) {
      return jsonResponse({
        datasets: [
          {
            dataset_slug: datasetSlug,
            title: "Telco Customer Churn",
            display_title: options.noExistingDraft ? null : publicProfile.display.title,
            summary: "Customer churn prediction dataset",
            domain: "telecom",
            tags: ["telecom"],
            active_release: "release-20260619-001",
            publication_status: "ready",
            last_updated: options.lastUpdated ?? "2026-06-19T12:00:00Z",
          },
        ],
      });
    }
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
            {
              name: "tenure",
              label: "Tenure",
              input_type: "number",
              optional: options.requiredFieldOverride === "tenure" ? false : true,
              display_order: 1,
            },
            {
              name: "MonthlyCharges",
              label: "Monthly charges",
              input_type: "number",
              optional: options.requiredFieldOverride === "MonthlyCharges" ? false : true,
              display_order: 2,
            },
          ],
        },
      });
    }
    if (url.includes("/metrics")) {
      return jsonResponse({
        metrics: { evaluation: { metrics: options.metricsOverride ?? { auc_roc: 0.93, accuracy: 0.86 } } },
      });
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
      // Project Spec S0061: the direct publish boundary echoes back exactly
      // the payload it received in the request body, matching the real
      // backend's publish_snapshot_from_payload behavior -- the published
      // snapshot must reflect exactly the current form payload submitted by
      // Publish changes, not a stale stored draft.
      const profile =
        typeof init.body === "string"
          ? (JSON.parse(init.body) as typeof publicProfile)
          : options.trackProfileDraftSaves
          ? savedProfileDraft ?? publicProfile
          : publicProfile;
      return jsonResponse({
        published: true,
        snapshot: {
          source_draft_schema_version: profile.schema_version,
          published_at: "2026-07-03T17:30:00Z",
          profile,
        },
        display_title: profile.display.title,
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
      if (options.trackProfileDraftSaves) {
        const body = typeof init.body === "string" ? JSON.parse(init.body) : publicProfile;
        savedProfileDraft = body;
        return jsonResponse({ saved: true, profile: body });
      }
      return jsonResponse({ saved: true, profile: publicProfile });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`)) {
      if (options.noExistingDraft) {
        return jsonResponse({ draft_exists: false, profile: null });
      }
      const profile = {
        ...publicProfile,
        display: {
          ...publicProfile.display,
          release_date_label: options.releaseDate ?? publicProfile.display.release_date_label,
          release_date_mode: options.releaseDateMode ?? publicProfile.display.release_date_mode,
        },
        ...(options.themePresetOverride ? { theme: { preset: options.themePresetOverride } } : {}),
      };
      if (options.trackProfileDraftSaves) {
        savedProfileDraft = profile;
      }
      return jsonResponse({ draft_exists: true, profile });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) && init?.method === "PUT") {
      if (options.trackCustomizationSaves) {
        const body = typeof init.body === "string" ? (JSON.parse(init.body) as typeof customization) : customization;
        savedCustomization = body;
        return jsonResponse({ saved: true, customization: body });
      }
      return jsonResponse({ saved: true, customization });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`)) {
      if (options.trackCustomizationSaves && savedCustomization) {
        return jsonResponse({ customization_exists: true, customization: savedCustomization });
      }
      return jsonResponse({ customization_exists: true, customization });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function loadDraftOnly() {
  expect(screen.queryByLabelText(["Operator", "token"].join(" "))).not.toBeInTheDocument();
  expect(await screen.findByTestId("dataset-admin-draft-ready")).toBeInTheDocument();
  expect(screen.queryByText("Content loaded")).not.toBeInTheDocument();
  expect(screen.queryByText("Editable fields were populated from your last saved content.")).not.toBeInTheDocument();
}

async function loadDraftAndCustomization() {
  await loadDraftOnly();
  fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
  fireEvent.click(screen.getByRole("button", { name: "Load customization" }));
  // Same fix as loadDraftOnly above: CustomizationStatusPanel's "ready"
  // branch renders "Customization loaded" with no trailing period (see
  // DatasetAdminPage.tsx line ~1551).
  expect(await screen.findByText("Customization loaded")).toBeInTheDocument();
}

describe("DatasetAdminPage", () => {
  beforeEach(() => {
    Element.prototype.setPointerCapture = vi.fn();
    // jsdom does not implement elementFromPoint at all -- finishDrag()
    // calls it unconditionally on pointer up/cancel, so every drag test
    // needs a stub, not just the ones asserting a specific drop target.
    document.elementFromPoint = vi.fn(() => null);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("wires Publishing tab actions and derives lifecycle labels from saved, published, and visibility state", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    expect(screen.getByRole("heading", { name: "Dataset — Curated churn profile" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Public Content",
      "Metadata & Card",
      "Theme Preset",
      "Inference Form",
      "Result Card",
      "Documentation",
      "Publishing",
      "Live Preview",
    ]);
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(screen.getByRole("checkbox", { name: "Visible Publicly" })).toBeDisabled();
    expect(screen.getByText("Not published in this session")).toBeInTheDocument();

    await loadDraftOnly();
    expect(within(screen.getByRole("tabpanel")).getByText("Loaded private draft.")).toBeInTheDocument();

    const callsBeforePreview = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("heading", { name: "Curated churn profile" })).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(callsBeforePreview);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`))).toHaveLength(0);

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    // Save draft/Publish changes only exist inside the Publishing tab's own
    // panel now that the top-level workspace-shell button has been removed
    // (S0055) and a separate, differently-scoped Publish changes button now
    // lives in the workspace toolbar (S0058) -- scope to the tabpanel so
    // these queries never collide with the toolbar's own button.
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Save draft" }));
    expect(await screen.findByTestId("dataset-admin-draft-saved")).toBeInTheDocument();
    expect(screen.queryByText("Changes saved.")).not.toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel")).getByText("Saved and matches public snapshot.")).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByText("Published at 2026-07-03T17:30:00Z. Public content is live.")).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: "Visible Publicly" })).not.toBeDisabled();
    expect(screen.getByText("2026-07-03T17:30:00Z (this session)")).toBeInTheDocument();

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`));
    // Project Spec S0061: Publish changes sends the current form payload
    // directly in the request body -- no persisted profile-draft is read by
    // the backend along this path.
    expect(publishCall?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(String((publishCall?.[1] as RequestInit).body)).dataset_slug).toBe(datasetSlug);

    fireEvent.click(screen.getByRole("checkbox", { name: "Visible Publicly" }));
    await waitFor(() => expect(screen.getByText("Latest published snapshot is hidden publicly.")).toBeInTheDocument());
    expect(screen.getByText("2026-07-03T17:30:00Z (this session)")).toBeInTheDocument();

    const visibilityCalls = fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`));
    expect(visibilityCalls).toHaveLength(1);
    expect(visibilityCalls[0]?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible: false }),
    });
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(1);

    fireEvent.click(screen.getByRole("checkbox", { name: "Visible Publicly" }));
    await waitFor(() => expect(screen.getByText("Latest published snapshot is visible publicly.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Display title"), { target: { value: "Edited churn profile" } });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    // The edit differs from the last saved backend draft (still tracked for
    // status-line wording), but Project Spec S0061 no longer requires that
    // draft to be saved before Publish changes is available again.
    expect(within(screen.getByRole("tabpanel")).getByText("Unsaved local changes.")).toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" })).toBeEnabled();
    expect(screen.queryByText(/Save Draft before publishing/)).not.toBeInTheDocument();
  });

  it("marks the active workspace tab as selected via aria-selected and updates it when switching tabs", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });

    expect(screen.getByRole("tab", { name: "Public Content", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Publishing", selected: false })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));

    expect(screen.getByRole("tab", { name: "Publishing", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Public Content", selected: false })).toBeInTheDocument();
  });

  it("aligns the upper shell with the design reference: no Read-only Atlas context card, no obsolete instructional copy, no top-level Save draft button, a single header status tag, and no Load draft action anywhere (Project Spec S0058)", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });

    // Obsolete scaffolding elements must be gone.
    expect(screen.queryByRole("region", { name: "Read-only Atlas values" })).not.toBeInTheDocument();
    expect(screen.queryByText("Read-only Atlas context")).not.toBeInTheDocument();
    expect(screen.queryByText("Load the private/admin draft before saving profile edits.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Saves only the schema-backed draft; publishing controls are in the Publishing tab."),
    ).not.toBeInTheDocument();
    // The top-level workspace-shell "Save draft" button is gone while
    // Public Content (the default tab) is selected; only the Publishing
    // tab's own Save draft action remains, and it is not rendered here.
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
    // The manual "Load draft" action is gone entirely (Project Spec S0058) --
    // the private/admin profile draft loads automatically instead.
    expect(screen.queryByRole("button", { name: "Load draft" })).not.toBeInTheDocument();

    // Design-aligned header: title/subtitle on the left, a single
    // publication/private status tag, and an icon-style public-open action
    // on the right. The Dataset Detail selector and Publish changes button
    // now live in the workspace toolbar below (asserted separately).
    expect(screen.getByRole("heading", { name: "Dataset — Curated churn profile" })).toBeInTheDocument();
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Published");
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveClass(
      "dataset-admin-registry-visibility-pill",
    );
    // Only one publication/private status tag renders in the header -- the
    // old session-local "Publication status" pill (Draft/Unpublished
    // Changes/Hidden/Not Published) is gone.
    expect(screen.queryByLabelText("Publication status")).not.toBeInTheDocument();
    const publicPageButton = screen.getByRole("button", { name: "Open public Dataset Detail page" });
    expect(publicPageButton).toBeEnabled();
    expect(publicPageButton).toHaveClass("dataset-admin-public-page-action");
    // The public-page action is icon-style: no visible "Open public page"
    // text remains, only an accessible label and a decorative icon.
    expect(publicPageButton).not.toHaveTextContent("Open public page");
    expect(publicPageButton.querySelector("svg")).not.toBeNull();

    // The Dataset Detail selector/filter and Publish changes button sit
    // together in the workspace toolbar, positioned above the tabs.
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    expect(within(toolbar).getByRole("button", { name: "Dataset" })).toBeInTheDocument();
    expect(within(toolbar).queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeInTheDocument();

    // Existing tab navigation remains available.
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Public Content",
      "Metadata & Card",
      "Theme Preset",
      "Inference Form",
      "Result Card",
      "Documentation",
      "Publishing",
      "Live Preview",
    ]);

    // The Publishing tab's own Save draft/Publish changes actions are
    // preserved, distinct from the workspace toolbar's own Publish changes.
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Save draft" })).toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" })).toBeInTheDocument();
  });

  it("keeps the full desktop tab bar, dataset selector, and status/action controls present and interactive at the compact 1360x768 desktop viewport baseline (Project Spec S0057)", async () => {
    // jsdom has no CSS layout engine, so this cannot assert pixel-level
    // overflow -- it asserts the acceptance criterion that matters at the
    // DOM level: at the compact desktop baseline the page still renders as
    // the same eight-tab desktop structure (no mobile/tablet fallback
    // markup, no collapsed overflow menu), matching how the compact-desktop
    // CSS in App.css narrows spacing without changing structure.
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    window.innerWidth = 1360;
    window.innerHeight = 768;

    try {
      installFetchMock();
      renderAdminPage();

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
      });

      expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Public Content",
        "Metadata & Card",
        "Theme Preset",
        "Inference Form",
        "Result Card",
        "Documentation",
        "Publishing",
        "Live Preview",
      ]);
      expect(screen.getByLabelText("Dataset Detail visibility")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeInTheDocument();
      expect(
        within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
          name: "Publish changes",
        }),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
      expect(screen.getByRole("tab", { name: "Result Card", selected: true })).toBeInTheDocument();
    } finally {
      window.innerWidth = originalWidth;
      window.innerHeight = originalHeight;
    }
  });

  it("opens the public Dataset Detail page in a new tab only while the selected dataset is publicly reachable", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Published"));

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).toHaveBeenCalledWith(`/dataset/${datasetSlug}`, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("keeps the workspace toolbar's Publish changes button disabled with no changes, enables it when a Public Content field is edited, and disables it again when the edit is reverted to the loaded snapshot (Project Spec S0058)", async () => {
    installFetchMock();
    renderAdminPage();

    // The profile draft now auto-loads (no manual "Load draft" step), so the
    // Public Content form starts already populated from the backend draft --
    // that loaded state is the snapshot the toolbar's dirty check compares
    // against.
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const toolbarPublishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(toolbarPublishButton).toBeDisabled();

    const originalSubtitle = (screen.getByLabelText("Subtitle") as HTMLInputElement).value;
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: `${originalSubtitle} edited` } });
    expect(toolbarPublishButton).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: originalSubtitle } });
    expect(toolbarPublishButton).toBeDisabled();
  });

  it("renders Release date label as a normalized date input seeded from Dashboard Last updated (Project Spec S0064)", async () => {
    installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "auto", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-06-21"));
    expect(input).toHaveAttribute("type", "date");
    expect(within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", { name: "Publish changes" })).toBeEnabled();
  });

  it("preserves a manual release date and publishes its override metadata with normal dirty-state reset (Project Spec S0064)", async () => {
    const fetchMock = installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "manual", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-05-01"));
    const publishButton = within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    fireEvent.change(input, { target: { value: "2026-05-12" } });
    expect(publishButton).toBeEnabled();
    fireEvent.click(publishButton);
    await waitFor(() => expect(publishButton).toBeDisabled());

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`),
    );
    const body = JSON.parse(String((publishCall?.[1] as RequestInit).body));
    expect(body.display).toMatchObject({ release_date_label: "2026-05-12", release_date_mode: "manual" });
  });

  it("treats clearing the release date as a reset to automatic Last updated seeding (Project Spec S0064)", async () => {
    installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "manual", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-05-01"));
    fireEvent.change(input, { target: { value: "" } });
    await waitFor(() => expect(input).toHaveValue("2026-06-21"));
  });

  it("keeps the workspace toolbar's Publish changes button disabled for a Dataset Detail with no saved draft until the seeded Display title is actually edited (Project Spec S0058)", async () => {
    installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Telco Customer Churn"));

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const toolbarPublishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(toolbarPublishButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "New public subtitle" } });
    expect(toolbarPublishButton).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "" } });
    expect(toolbarPublishButton).toBeDisabled();
  });

  it("publishes Public Content changes from the workspace toolbar directly, with no profile-draft save required, resetting the dirty state on success (Project Spec S0061)", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    const subtitleInput = screen.getByLabelText("Subtitle");
    fireEvent.change(subtitleInput, { target: { value: "Toolbar-edited subtitle" } });
    subtitleInput.focus();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const toolbarPublishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(toolbarPublishButton).toBeEnabled();

    fireEvent.click(toolbarPublishButton);

    // A successful publish updates the snapshot, so the button disables
    // again without any further operator action.
    await waitFor(() => expect(toolbarPublishButton).toBeDisabled());
    expect(screen.getByLabelText("Subtitle")).toBe(subtitleInput);
    expect(subtitleInput).toHaveFocus();

    // No profile-draft save happens as part of this click -- Publish changes
    // sends the current form payload directly.
    const saveCall = fetchMock.mock.calls.find(
      (call: unknown[]) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(saveCall).toBeUndefined();

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`),
    );
    expect(publishCall).toBeDefined();
    expect(publishCall?.[1]).toMatchObject({ method: "PUT", headers: { "Content-Type": "application/json" } });
    expect(JSON.parse(String((publishCall?.[1] as RequestInit).body)).display?.subtitle).toBe("Toolbar-edited subtitle");

    // The Publishing tab's own status reflects the same successful publish,
    // using the existing frontend/backend boundary rather than a new one.
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(await screen.findByText(/^Published at /)).toBeInTheDocument();
  });

  it("surfaces a safe error message from the workspace toolbar when publishing Public Content changes fails, without exposing raw internals (Project Spec S0061)", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Toolbar-edited subtitle" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));

    expect(
      await screen.findByText("Public Content changes could not be published. Open the Publishing tab for details."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Subtitle")).toHaveValue("Toolbar-edited subtitle");
    expect(screen.queryByText(/PROFILE_PUBLISH_FAILED/)).not.toBeInTheDocument();
  });

  it("removes manual refresh and loaded-content copy, and selects Documentation without persisting data (Project Spec S0066)", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();

    const subtitleInput = await screen.findByLabelText("Subtitle");
    await waitFor(() => expect(subtitleInput).toHaveValue("Operator-authored public subtitle"));
    const mutationCallsBefore = fetchMock.mock.calls.filter(([, init]) => init?.method && init.method !== "GET").length;

    expect(within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();
    expect(screen.queryByText("Content loaded")).not.toBeInTheDocument();
    expect(screen.queryByText("Editable fields were populated from your last saved content.")).not.toBeInTheDocument();
    expect(screen.queryByText("Controls public date label rendering only.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
    expect(screen.getByRole("tab", { name: "Documentation", selected: true })).toBeInTheDocument();
    expect(screen.getByLabelText("Documentation placeholder")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method && init.method !== "GET")).toHaveLength(mutationCallsBefore);
  });

  it("surfaces backend profile validation feedback without publishing side effects", async () => {
    installFetchMock({ rejectProfileSave: true });
    renderAdminPage();

    await loadDraftAndCustomization();

    // Save draft only exists inside the Publishing tab's own panel now that
    // the top-level workspace-shell button has been removed (S0055).
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("Profile draft rejected by backend validation")).toBeInTheDocument();
    expect(screen.getByText(/display.title - TITLE_REQUIRED - Title is required./)).toBeInTheDocument();
  });

  it("surfaces publish validation feedback without changing visibility state", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();

    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));

    expect(await screen.findByText("Publishing action rejected by backend validation.")).toBeInTheDocument();
    expect(screen.getByText(/profile - PROFILE_PUBLISH_FAILED - Snapshot validation failed./)).toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel")).getByText("Loaded private draft.")).toBeInTheDocument();
  });

  it("surfaces visibility validation feedback without changing public exposure", async () => {
    installFetchMock({ rejectVisibility: true });
    renderAdminPage();

    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByText("Published at 2026-07-03T17:30:00Z. Public content is live.")).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: "Visible Publicly" })).toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: "Visible Publicly" }));

    expect(await screen.findByText("Publishing action rejected by backend validation.")).toBeInTheDocument();
    expect(screen.getByText(/PROFILE_VISIBILITY_PAYLOAD_INVALID - Visibility payload is invalid./)).toBeInTheDocument();
    // The rejected visibility change never touched publicationState.visible,
    // so the Current state card's Visibility row still reads "Public." even
    // while the status article above shows the rejection message.
    expect(within(screen.getByRole("tabpanel")).getByText("Public.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Visible Publicly" })).toBeChecked();
  });

  it("observes a Theme Preset edit in Publishing's derived status and re-enables Publish changes without requiring a save (Project Spec S0061)", async () => {
    installFetchMock({ themePresetOverride: "ocean-blue", trackProfileDraftSaves: true });
    renderAdminPage();

    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByText("Published at 2026-07-03T17:30:00Z. Public content is live.")).toBeInTheDocument());
    // A successful publish becomes the new baseline, so with nothing changed
    // since, Publish changes disables again immediately.
    expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" })).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.change(screen.getByLabelText("Theme preset"), { target: { value: "atlas-green" } });

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    // Differs from the last saved backend draft (ocean-blue), which takes
    // precedence over the also-true unpublished-relative-to-published
    // comparison in draftStateSummary -- but Project Spec S0061 no longer
    // requires a Save draft click before Publish changes is available again.
    expect(within(screen.getByRole("tabpanel")).getByText("Unsaved local changes.")).toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" })).toBeEnabled();

    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" })).toBeDisabled());
    expect(within(screen.getByRole("tabpanel")).getByText("Saved and matches public snapshot.")).toBeInTheDocument();
  });

  it("saves a schema-valid profile-draft payload for supported icon, primary metric, theme preset, and result-card values", async () => {
    // contracts/dataset-public-profile.schema.json's closed enums: home_card.icon, theme.preset,
    // and result_card.badge_preset. Asserting membership here proves the saved payload stays
    // inside the schema's supported values (acceptance-01).
    const SCHEMA_SUPPORTED_ICONS = [
      "telecom",
      "bank",
      "generic",
      "telecom-users",
      "bank-building",
      "chart-line",
      "heart",
      "shopping-cart",
      "airplane",
      "shield",
      "education-cap",
      "energy-bolt",
      "home-house",
      "agro-leaf",
      "logistics-truck",
      "factory",
      "weather-cloud",
      "database",
    ];
    const SCHEMA_SUPPORTED_THEME_PRESETS = ["atlas-green"];
    const SCHEMA_SUPPORTED_BADGE_PRESETS = ["risk"];

    const fetchMock = installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
    fireEvent.change(screen.getByLabelText("Home card icon"), { target: { value: "chart-line" } });
    fireEvent.change(screen.getByLabelText("Primary metric key"), { target: { value: "accuracy" } });

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.change(screen.getByLabelText("Theme preset"), { target: { value: "atlas-green" } });

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    fireEvent.change(screen.getByLabelText("Badge preset"), { target: { value: "risk" } });
    fireEvent.change(screen.getByLabelText("High badge label"), { target: { value: "Severe risk" } });

    // Save draft only exists inside the Publishing tab's own panel now that
    // the top-level workspace-shell button has been removed (S0055).
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Save draft" }));
    await screen.findByTestId("dataset-admin-draft-saved");
    expect(screen.queryByText("Changes saved.")).not.toBeInTheDocument();

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
    expect(saveCall?.[1]).toMatchObject({
      headers: { "Content-Type": "application/json" },
    });
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      home_card?: { icon?: string; primary_metric_key?: string | null };
      theme?: { preset?: string };
      result_card?: { badge_preset?: string; badge_labels?: { high?: string } };
    };

    expect(body.home_card?.icon).toBe("chart-line");
    expect(SCHEMA_SUPPORTED_ICONS).toContain(body.home_card?.icon);
    expect(body.home_card?.primary_metric_key).toBe("accuracy");
    expect(body.theme?.preset).toBe("atlas-green");
    expect(SCHEMA_SUPPORTED_THEME_PRESETS).toContain(body.theme?.preset);
    expect(body.result_card?.badge_preset).toBe("risk");
    expect(SCHEMA_SUPPORTED_BADGE_PRESETS).toContain(body.result_card?.badge_preset);
    expect(body.result_card?.badge_labels?.high).toBe("Severe risk");
  });

  it("cannot select or persist theme/result-card preset values outside the schema-supported set", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    const themeSelect = screen.getByLabelText("Theme preset") as HTMLSelectElement;
    const themeOptionValues = Array.from(themeSelect.options).map((option) => option.value);
    expect(themeOptionValues).toEqual(["", "atlas-green"]);
    expect(screen.getByRole("button", { name: /Atlas Green/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Ocean Blue/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Neutral Light/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    const badgeSelect = screen.getByLabelText("Badge preset") as HTMLSelectElement;
    const badgeOptionValues = Array.from(badgeSelect.options).map((option) => option.value);
    expect(badgeOptionValues).toEqual(["", "risk"]);
    expect(screen.getByRole("button", { name: /Risk/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Value band/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Severity/ })).toBeDisabled();

    // The 13 additional design-proposed theme presets and 4 additional design-proposed
    // result-card badge presets are visible only as disabled cards; they are not rendered
    // as select options at all. There is no DOM control path through which a user could
    // select them, and DraftForm's
    // theme_preset/badge_preset fields are typed as closed unions ("" | "atlas-green" and
    // "" | "risk"), so setField can never be called with an out-of-schema value from these
    // controls. profileFromForm only ever writes profile.theme/result_card.badge_preset from
    // these same two closed-union fields, so an unsupported preset can never reach a save
    // payload through this form.
  });

  it("renders the Home card background-image field as a plain text input with no file-upload affordance anywhere on the page", async () => {
    // docs/design-prototype-behavior-inventory.md classifies the prototype's uploaded
    // Home card background image as `deferred`: no upload/storage/reference schema owner
    // exists yet. background_image_ref is only an operator-entered reference string, not
    // a file upload -- this test proves that boundary stays true rather than silently
    // regressing into an unreviewed upload affordance.
    installFetchMock();
    const { container } = renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const backgroundImageField = screen.getByLabelText("Background image reference") as HTMLInputElement;
    expect(backgroundImageField).toHaveAttribute("type", "text");
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  it("renders the model-derived problem type as an ordered, locked radio group beside the Home card preview", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    expect(screen.getByRole("heading", { name: "Home card preview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Short Home card description")).toBeInTheDocument();

    const problemTypeGroup = screen.getByRole("radiogroup", { name: "Problem type display" });
    const options = within(problemTypeGroup).getAllByRole("radio") as HTMLInputElement[];
    expect(options.map((option) => option.value)).toEqual([
      "binary-classification",
      "regression",
      "multiclass-classification",
      "time-series",
    ]);
    expect(options[0]).toBeChecked();
    options.forEach((option) => expect(option).toBeDisabled());

    fireEvent.click(within(problemTypeGroup).getByText("Regression"));
    expect(options[0]).toBeChecked();
    expect(options[1]).not.toBeChecked();
    expect(screen.getByText(/derived from the Atlas dataset and model contract/i)).toBeInTheDocument();
  });

  it("renders Live Preview subviews from real public components and the loaded customization", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    // Level-scoped heading role proves DatasetDetailHeader's real <h1>, not
    // just coincidentally matching text from a divergent mockup.
    expect(screen.getByRole("heading", { level: 1, name: "Curated churn profile" })).toBeInTheDocument();

    expect(screen.getByRole("tab", { name: "Dataset Detail", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Result" })).toBeInTheDocument();
    expect(screen.getByLabelText("Tenure")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Home Card" }));
    // Level-scoped heading role proves DatasetCard's real <h3> title element.
    expect(screen.getByRole("heading", { level: 3, name: "Curated churn profile" })).toBeInTheDocument();
    expect(screen.getByText("Curated home card copy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Dataset Detail" }));
    expect(screen.getByText(/Placeholder preview only, not a real prediction./)).toBeInTheDocument();
    const resultRegion = screen.getByRole("region", { name: "Result" });
    expect(within(resultRegion).getByText("Churn probability")).toBeInTheDocument();
    expect(screen.getByText("Account profile")).toBeInTheDocument();
  });

  it("updates each Live Preview mode's rendered output when a fed draft or customization field is edited", async () => {
    // theme.preset is seeded as "ocean-blue" (a real named preset -- see
    // THEME_PRESET_CARDS -- but not currently selectable through the Theme
    // Preset tab's own controls) and metrics.evaluation.metrics is seeded
    // with a "precision" key (absent from the shared default fixture)
    // specifically so this test can prove genuine reactivity for theme and
    // primary-metric highlighting. DraftForm.theme_preset is typed as a
    // closed "" | "atlas-green" union whose only two values both render the
    // Live Preview stage's data-theme-preset attribute identically (via the
    // `form.theme_preset || "atlas-green"` fallback), and the shared metrics
    // fixture's only alternate key ("accuracy") is not recognized by
    // PerformanceSummary's SCORE_ORDER -- editing to either of those "real"
    // default-fixture alternatives would collapse back to the pre-edit
    // rendered value and prove nothing about reactivity.
    installFetchMock({ themePresetOverride: "ocean-blue", metricsOverride: { auc_roc: 0.93, precision: 0.81 } });
    const { container } = renderAdminPage();

    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Display title"), { target: { value: "Edited home title" } });
    fireEvent.change(screen.getByLabelText("Release date label"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Date format"), { target: { value: "yyyy-mm-dd" } });

    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
    fireEvent.change(screen.getByLabelText("Home card icon"), { target: { value: "bank" } });
    fireEvent.change(screen.getByLabelText("Short Home card description"), {
      target: { value: "Edited home card description" },
    });
    fireEvent.change(screen.getByLabelText("Primary metric key"), { target: { value: "precision" } });

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.change(screen.getByLabelText("Theme preset"), { target: { value: "atlas-green" } });

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    fireEvent.change(screen.getByLabelText("Medium badge label"), { target: { value: "Elevated risk (edited)" } });

    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    fireEvent.change(screen.getAllByLabelText("Display label")[0], { target: { value: "Tenure (edited)" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

    // data-theme-preset now reflects the just-edited "atlas-green" selection,
    // not the "ocean-blue" value the draft was originally seeded with --
    // proving the attribute is live-bound to form.theme_preset rather than a
    // static initial prop.
    expect(container.querySelector(".dataset-admin-preview-stage")).toHaveAttribute(
      "data-theme-preset",
      "atlas-green",
    );

    // Detail preview sub-tabs (e.g. separating this Theme/token view from the
    // Result Card and Inference Form sub-panels rendered below it) remain a
    // documented deferral per docs/design-prototype-behavior-inventory.md's
    // "deferred" classification; not implemented by this issue.

    fireEvent.click(screen.getByRole("tab", { name: "Home Card" }));
    expect(screen.getByRole("heading", { level: 3, name: "Edited home title" })).toBeInTheDocument();
    expect(screen.getByText("Edited home card description")).toBeInTheDocument();
    // Icon reactivity is asserted via the rendered SVG's own path geometry
    // (not a role/label query) because DatasetCard wraps every curated icon
    // in an aria-hidden span with no distinguishing accessible name.
    expect(screen.getByRole("article", { name: "Home Card preview" }).querySelector("svg path")).toHaveAttribute(
      "d",
      "M4 10h16L12 5 4 10Zm2 0v8m4-8v8m4-8v8m4-8v8M4 19h16",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Dataset Detail" }));
    expect(screen.getByRole("heading", { level: 1, name: "Edited home title" })).toBeInTheDocument();
    expect(screen.getByText("2026-08-01")).toBeInTheDocument();
    // Release hint stays fixed at "Format: dd/mm/yyyy" regardless of the
    // edited date_format, matching what the public Dataset Detail page
    // currently and always renders (decision-02).
    expect(screen.getByText("Format: dd/mm/yyyy")).toBeInTheDocument();

    // 0.72 fixed placeholder confidence resolves to the "warning" tone,
    // which maps to the medium badge label.
    expect(screen.getByText("Elevated risk (edited)")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenure (edited)")).toBeInTheDocument();

    // primary_metric_key now resolves to "precision" (present in this test's
    // overridden metrics fixture and recognized by PerformanceSummary's
    // SCORE_ORDER) -- the "Highlighted" badge moves off its default AUC ROC
    // row onto Precision.
    expect(screen.getByText("Highlighted").closest("dt")).toHaveTextContent("Precision");
  });

  it("shows pointer-following drag overlay activity for fields and groups", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    const groupsPanel = screen.getByLabelText("Groups");
    const groupDragHandle = within(groupsPanel).getByRole("button", { name: "Drag group Account profile" });
    fireEvent.pointerDown(groupDragHandle, { pointerId: 1, clientX: 12, clientY: 16 });
    // "Account profile" also appears as a per-field group <option>, so the
    // drag ghost (a plain aria-hidden div, not an <option>) needs filtering
    // out from those to be found unambiguously.
    const groupGhost = screen.getAllByText("Account profile").find((el) => el.tagName !== "OPTION");
    expect(groupGhost).toBeInTheDocument();
    fireEvent.pointerUp(groupDragHandle, { pointerId: 1, clientX: 18, clientY: 24 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(1);
    });

    const fieldsPanel = screen.getByLabelText("Field presentation");
    const fieldDragHandle = within(fieldsPanel).getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });
    const fieldGhost = screen.getAllByText("Tenure").find((el) => el.tagName !== "OPTION");
    expect(fieldGhost).toBeInTheDocument();
    fireEvent.pointerCancel(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(2);
    });
  });

  it("persists group create/edit/remove/reorder through customization save and reload", async () => {
    installFetchMock({ trackCustomizationSaves: true });
    renderAdminPage();

    await loadDraftAndCustomization();

    const groupsPanel = screen.getByLabelText("Groups");
    const fieldsPanel = screen.getByLabelText("Field presentation");

    fireEvent.click(screen.getByRole("button", { name: "Add group" }));
    const removeButtonsAfterAdd = within(groupsPanel).getAllByRole("button", { name: "Remove" });
    const newGroupCard = removeButtonsAfterAdd[removeButtonsAfterAdd.length - 1].closest(
      ".dataset-admin-builder-card",
    ) as HTMLElement;

    fireEvent.change(within(newGroupCard).getByLabelText("Label"), { target: { value: "Support tier" } });
    fireEvent.change(within(newGroupCard).getByLabelText("Description"), {
      target: { value: "Support-related attributes" },
    });

    // The new group's group_id is deterministically "group-3"
    // (addGroup: `group-${current.groups.length + 1}` with 2 pre-existing groups).
    const tenureCard = within(fieldsPanel).getByText("tenure").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.change(within(tenureCard).getByLabelText("Group"), { target: { value: "group-3" } });

    // Move down on the first group ("Account profile") swaps it with its
    // neighbor ("Charges").
    fireEvent.click(within(groupsPanel).getAllByRole("button", { name: "Move down" })[0]);

    // Remove a different pre-existing group ("Account profile") than the one
    // just created/edited/assigned ("Support tier").
    const accountCard = within(groupsPanel)
      .getByDisplayValue("Account profile")
      .closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(accountCard).getByRole("button", { name: "Remove" }));

    fireEvent.click(screen.getByRole("button", { name: "Save customization" }));
    await screen.findByText("Customization saved.");

    // A real reload, not just a payload assertion: click "Load customization"
    // again and verify the re-rendered editor reflects all five edits.
    fireEvent.click(screen.getByRole("button", { name: "Load customization" }));
    await screen.findByText("Customization loaded");

    const reloadedGroupsPanel = screen.getByLabelText("Groups");
    const reloadedLabels = within(reloadedGroupsPanel).getAllByLabelText("Label") as HTMLInputElement[];
    expect(reloadedLabels.map((input) => input.value)).toEqual(["Charges", "Support tier"]);
    const reloadedDescriptions = within(reloadedGroupsPanel).getAllByLabelText("Description") as HTMLInputElement[];
    expect(reloadedDescriptions.map((input) => input.value)).toEqual([
      "Billing attributes",
      "Support-related attributes",
    ]);

    const reloadedFieldsPanel = screen.getByLabelText("Field presentation");
    const reloadedTenureCard = within(reloadedFieldsPanel)
      .getByText("tenure")
      .closest(".dataset-admin-builder-card") as HTMLElement;
    expect(within(reloadedTenureCard).getByLabelText("Group")).toHaveValue("group-3");
    const reloadedChargesCard = within(reloadedFieldsPanel)
      .getByText("MonthlyCharges")
      .closest(".dataset-admin-builder-card") as HTMLElement;
    expect(within(reloadedChargesCard).getByLabelText("Group")).toHaveValue("charges");
  });

  it("isolates the group collapse affordance from the saved customization", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    const groupsPanel = screen.getByLabelText("Groups");
    const accountCard = within(groupsPanel)
      .getByDisplayValue("Account profile")
      .closest(".dataset-admin-builder-card") as HTMLElement;

    const collapseButton = within(accountCard).getByRole("button", { name: "Collapse" });
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");
    expect(within(accountCard).getByLabelText("Group ID")).toBeInTheDocument();
    expect(within(accountCard).getByLabelText("Label")).toBeInTheDocument();
    expect(within(accountCard).getByLabelText("Description")).toBeInTheDocument();

    fireEvent.click(collapseButton);

    const expandButton = within(accountCard).getByRole("button", { name: "Expand" });
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    expect(within(accountCard).queryByLabelText("Group ID")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Label")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Description")).not.toBeInTheDocument();

    // The header row (drag, move, remove, field count, collapse/expand)
    // must remain visible and functional regardless of collapsed state.
    expect(within(accountCard).getByRole("button", { name: /^Drag group/ })).toBeInTheDocument();
    expect(within(accountCard).getByRole("button", { name: "Move down" })).toBeInTheDocument();
    expect(within(accountCard).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(within(accountCard).getByText(/fields$/)).toBeInTheDocument();

    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Save customization" }));
    await screen.findByText("Customization saved.");

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
    expect(saveCall?.[1]).toMatchObject({
      headers: { "Content-Type": "application/json" },
    });
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      groups: Array<{ group_id: string; label: string }>;
    };
    expect(body.groups.map((group) => ({ group_id: group.group_id, label: group.label }))).toEqual([
      { group_id: "account", label: "Account profile" },
      { group_id: "charges", label: "Charges" },
    ]);
  });

  it("disables the hide checkbox for a required field and never saves it as hidden", async () => {
    const fetchMock = installFetchMock({ requiredFieldOverride: "tenure" });
    renderAdminPage();

    await loadDraftAndCustomization();

    const fieldsPanel = screen.getByLabelText("Field presentation");
    const tenureCard = within(fieldsPanel).getByText("tenure").closest(".dataset-admin-builder-card") as HTMLElement;
    expect(within(tenureCard).getByText("required")).toBeInTheDocument();

    const hideCheckbox = within(tenureCard).getByRole("checkbox");
    expect(hideCheckbox).toBeDisabled();
    expect(hideCheckbox).not.toBeChecked();

    // Disabled inputs should not respond to interaction; attempting the click
    // anyway (rather than only asserting the disabled attribute) guards
    // against a regression that removes `disabled` without preserving the
    // required-cannot-be-hidden guarantee itself.
    fireEvent.click(hideCheckbox);
    expect(hideCheckbox).not.toBeChecked();

    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Save customization" }));
    await screen.findByText("Customization saved.");

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      field_hints: Array<{ field_name: string; hidden?: boolean }>;
    };
    const tenureHint = body.field_hints.find((hint) => hint.field_name === "tenure");
    expect(tenureHint?.hidden).toBeUndefined();
  });

  it("saves identical field order and display_order_hint via a button reorder and an equivalent drag reorder", async () => {
    // jsdom does not implement elementFromPoint at all (the property is
    // absent, not just unimplemented), so it must be assigned directly
    // rather than wrapped with vi.spyOn, which requires the property to
    // already exist.
    document.elementFromPoint = vi.fn((_x: number, y: number) =>
      document.querySelector<HTMLElement>(`[data-customization-drag-kind="field"][data-customization-drag-index="${y}"]`),
    );

    function extractSavedFieldOrder(fetchMock: ReturnType<typeof installFetchMock>, callsBeforeSave: number) {
      const saveCall = fetchMock.mock.calls
        .slice(callsBeforeSave)
        .find(
          (call: unknown[]) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        );
      const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
        field_hints: Array<{ field_name: string; display_order_hint: number }>;
      };
      return body.field_hints.map((hint) => ({ field_name: hint.field_name, display_order_hint: hint.display_order_hint }));
    }

    const buttonFetchMock = installFetchMock();
    const { unmount } = renderAdminPage();
    await loadDraftAndCustomization();

    const buttonFieldsPanel = screen.getByLabelText("Field presentation");
    const moveDownButtons = within(buttonFieldsPanel).getAllByRole("button", { name: "Move down" });
    const callsBeforeButtonSave = buttonFetchMock.mock.calls.length;
    fireEvent.click(moveDownButtons[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save customization" }));
    await screen.findByText("Customization saved.");
    const buttonOrder = extractSavedFieldOrder(buttonFetchMock, callsBeforeButtonSave);

    unmount();

    const dragFetchMock = installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const dragFieldsPanel = screen.getByLabelText("Field presentation");
    const tenureDragHandle = within(dragFieldsPanel).getByRole("button", { name: "Drag field Tenure" });
    const callsBeforeDragSave = dragFetchMock.mock.calls.length;
    fireEvent.pointerDown(tenureDragHandle, { pointerId: 3, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureDragHandle, { pointerId: 3, clientX: 0, clientY: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Save customization" }));
    await screen.findByText("Customization saved.");
    const dragOrder = extractSavedFieldOrder(dragFetchMock, callsBeforeDragSave);

    expect(dragOrder).toEqual(buttonOrder);
    expect(dragOrder.map((entry) => entry.field_name)).toEqual(["MonthlyCharges", "tenure"]);
  });

  it("shows a disabled selector, no selected dataset, and a disabled public-open action when no datasets are registered", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [] });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [] });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toBeDisabled());
    expect(selector).toHaveTextContent("No datasets available");

    expect(screen.getByRole("heading", { name: "Dataset — No dataset selected" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Read-only Atlas values" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("No dataset selected");
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
  });

  it("populates the filterable Admin dataset selector for a multi-dataset listing including a synthetic non-Telco/Bank dataset and updates the header on selection change", async () => {
    // AdminDatasetListing shape (GET /admin/datasets, registry/list.py's
    // list_admin_datasets) -- distinct from the public DatasetListing shape
    // (visibility, no active_release/publication_status) used by the
    // separate GET /datasets fetch below.
    const adminDatasetOne = {
      dataset_slug: "synthetic-retail-forecast",
      title: "Synthetic Retail Forecast",
      display_title: "Retail Demand Display",
      summary: "Synthetic retail demand forecasting dataset",
      domain: "retail",
      tags: ["retail"],
      active_release: "release-20260701-001",
      publication_status: "ready",
    };
    const adminDatasetTwo = {
      dataset_slug: "synthetic-energy-usage",
      title: "Synthetic Energy Usage",
      display_title: "Energy Usage Display",
      summary: "Synthetic household energy usage dataset",
      domain: "energy",
      tags: ["energy"],
      active_release: "release-20260701-002",
      publication_status: "needs_review",
    };
    const adminDatasetThree = {
      dataset_slug: "synthetic-agri-yield",
      title: "Synthetic Agricultural Yield",
      display_title: "Agricultural Yield Display",
      summary: "Synthetic crop yield dataset",
      domain: "agriculture",
      tags: ["agriculture"],
      active_release: "release-20260701-003",
      publication_status: "ready",
    };
    // Only datasetOne and datasetThree are publicly reachable (present in
    // GET /datasets); datasetTwo is Admin-visible only (needs_review),
    // exercising the header's Published/Private distinction.
    const publicDatasetOne = { ...adminDatasetOne, visibility: "public" };
    const publicDatasetThree = { ...adminDatasetThree, visibility: "public" };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [adminDatasetOne, adminDatasetTwo, adminDatasetThree] });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [publicDatasetOne, publicDatasetThree] });
      }
      if (url.endsWith(`/datasets/${adminDatasetOne.dataset_slug}`)) {
        return jsonResponse(publicDatasetOne);
      }
      if (url.endsWith(`/datasets/${adminDatasetTwo.dataset_slug}`)) {
        return jsonResponse({}, 404);
      }
      if (url.endsWith(`/datasets/${adminDatasetThree.dataset_slug}`)) {
        return jsonResponse(publicDatasetThree);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() =>
      expect(selector).toHaveTextContent(adminDatasetOne.display_title),
    );
    expect(selector).not.toHaveTextContent(adminDatasetOne.dataset_slug);
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Published"));

    fireEvent.click(selector);
    const listbox = screen.getByRole("listbox", { name: "Available datasets" });
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual([
      adminDatasetOne.display_title,
      adminDatasetTwo.display_title,
      adminDatasetThree.display_title,
    ]);
    expect(listbox).not.toHaveTextContent(adminDatasetOne.dataset_slug);

    const filter = screen.getByLabelText("Filter datasets");
    fireEvent.change(filter, { target: { value: adminDatasetTwo.dataset_slug } });
    fireEvent.click(
      within(listbox).getByRole("option", { name: adminDatasetTwo.display_title }),
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: `Dataset — ${adminDatasetTwo.display_title}` })).toBeInTheDocument(),
    );
    // datasetTwo is needs_review and absent from the public listing, so the
    // header must show it as Private and keep the public-open action disabled.
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    fireEvent.click(selector);
    fireEvent.click(
      within(screen.getByRole("listbox", { name: "Available datasets" })).getByRole("option", {
        name: adminDatasetThree.display_title,
      }),
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: `Dataset — ${adminDatasetThree.display_title}` })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Published"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
  });

  it("moves an ARIA active-option indicator through the filtered listbox with ArrowDown/ArrowUp and selects it on Enter", async () => {
    const adminDatasetOne = {
      dataset_slug: "synthetic-retail-forecast",
      title: "Synthetic Retail Forecast",
      summary: "Synthetic retail demand forecasting dataset",
      domain: "retail",
      tags: ["retail"],
      active_release: "release-20260701-001",
      publication_status: "ready",
    };
    const adminDatasetTwo = {
      dataset_slug: "synthetic-energy-usage",
      title: "Synthetic Energy Usage",
      summary: "Synthetic household energy usage dataset",
      domain: "energy",
      tags: ["energy"],
      active_release: "release-20260701-002",
      publication_status: "ready",
    };
    const adminDatasetThree = {
      dataset_slug: "synthetic-agri-yield",
      title: "Synthetic Agricultural Yield",
      summary: "Synthetic crop yield dataset",
      domain: "agriculture",
      tags: ["agriculture"],
      active_release: "release-20260701-003",
      publication_status: "ready",
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [adminDatasetOne, adminDatasetTwo, adminDatasetThree] });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [adminDatasetOne, adminDatasetTwo, adminDatasetThree].map((dataset) => ({
            ...dataset,
            visibility: "public",
          })),
        });
      }
      return jsonResponse({ ...adminDatasetOne, visibility: "public" });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() =>
      expect(selector).toHaveTextContent(adminDatasetOne.title),
    );
    expect(selector).not.toHaveTextContent(adminDatasetOne.dataset_slug);

    fireEvent.click(selector);
    const filter = screen.getByLabelText("Filter datasets");

    expect(filter).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(filter, { key: "ArrowDown" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${adminDatasetOne.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowDown" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${adminDatasetTwo.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowUp" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${adminDatasetOne.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowUp" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${adminDatasetThree.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "Enter" });

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: `Dataset — ${adminDatasetThree.title}` })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("listbox", { name: "Available datasets" })).not.toBeInTheDocument();
  });

  it("recomposes the Public Content tab as a blank authoring form seeded only with the Dataset Detail title (Project Spec S0056)", async () => {
    // Project Spec S0058 auto-loads the profile draft as soon as a Dataset
    // Detail is selected -- this test's blank-authoring-form baseline only
    // still applies when no backend draft/profile genuinely exists yet, so
    // it explicitly simulates that (noExistingDraft) rather than relying on
    // the draft endpoint never being fetched (it always is now).
    installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    // Wait for the Admin/Dashboard dataset listing to resolve -- Display
    // title is seeded from that title, not typed by the operator, and not
    // loaded from the (genuinely empty) private draft/profile endpoint. The
    // seed itself lands one effect-flush after the listing resolves, so it
    // is awaited separately from the header text.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Telco Customer Churn");
    });
    expect(screen.getByRole("button", { name: "Dataset" })).not.toHaveTextContent(datasetSlug);
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Telco Customer Churn"));

    // Every other Public Content authoring field starts genuinely blank --
    // none of them auto-fill from the dataset's technical context/summary
    // fallback content, even though that data is already fetched and
    // available (GET /datasets/{slug}/context, seeded above).
    expect(screen.getByLabelText("Subtitle")).toHaveValue("");
    expect(screen.getByLabelText("Problem summary title")).toHaveValue("");
    expect(screen.getByLabelText("Problem summary body")).toHaveValue("");
    expect(screen.getByLabelText("Source name")).toHaveValue("");
    expect(screen.getByLabelText("Source URL")).toHaveValue("");
    // S0064 adds the sole second deterministic seed: Dashboard Last updated.
    expect(screen.getByLabelText("Release date label")).toHaveValue("2026-06-19");
    expect(screen.getByLabelText("Date format")).toHaveValue("");

    // Required markers render inline beside each field's own label rather
    // than on a separate row.
    for (const label of [
      "Display title",
      "Subtitle",
      "Problem summary title",
      "Problem summary body",
      "Source name",
      "Source URL",
      "Release date label",
      "Date format",
    ]) {
      expect(screen.getByLabelText(label).closest("label")?.textContent).toContain("*");
    }
  });

  it("renders Public Content character counters that reflect the correct schema/field-contract maximums and update live as the operator types", async () => {
    // Same reasoning as the blank-authoring-form test above: the seeded
    // "20 / 80" baseline below assumes no backend draft/profile exists yet.
    installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Telco Customer Churn");
    });
    expect(screen.getByRole("button", { name: "Dataset" })).not.toHaveTextContent(datasetSlug);
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Telco Customer Churn"));

    // "Telco Customer Churn" (the seeded Display title) is 20 characters.
    expect(screen.getByText("20 / 80")).toBeInTheDocument();
    expect(screen.getByText("0 / 120")).toBeInTheDocument();
    expect(screen.getByText("0 / 60")).toBeInTheDocument();
    expect(screen.getByText("0 / 300")).toBeInTheDocument();

    const subtitleValue = "Predicao de churn";
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: subtitleValue } });
    expect(screen.getByText(`${subtitleValue.length} / 120`)).toBeInTheDocument();
    expect(screen.queryByText("0 / 120")).not.toBeInTheDocument();

    const summaryBodyValue = "Explains churn.";
    fireEvent.change(screen.getByLabelText("Problem summary body"), { target: { value: summaryBodyValue } });
    expect(screen.getByText(`${summaryBodyValue.length} / 300`)).toBeInTheDocument();
  });

  it("cleans up the Public Content tab body by removing the duplicate internal heading, helper copy, and Canonical fallback control while keeping the field layout and counters intact (Project Spec S0059)", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftOnly();

    // Public Content is the default tab; scope every assertion to its own
    // tabpanel so the "Public Content" tab-navigation button itself (which
    // legitimately keeps that label) can't make a removed-heading assertion
    // pass by accident.
    const panel = screen.getByRole("tabpanel", { name: "Public Content tab panel" });

    expect(within(panel).queryByText("Public Content")).not.toBeInTheDocument();
    expect(
      within(panel).queryByText(
        "Edit only schema-backed presentation copy. Canonical dataset values remain read-only.",
      ),
    ).not.toBeInTheDocument();
    expect(within(panel).queryByText("Canonical fallback")).not.toBeInTheDocument();
    expect(
      within(panel).queryByText("Use Telco Customer Churn when no curated title is set."),
    ).not.toBeInTheDocument();
    expect(within(panel).queryByRole("checkbox")).not.toBeInTheDocument();

    // The Public copy / Source and release subgroup concepts, field order,
    // counters, and required markers all remain in place.
    expect(within(panel).getByRole("heading", { level: 2, name: "Public copy" })).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { level: 2, name: "Source and release" })).toBeInTheDocument();
    const displayTitleField = within(panel).getByLabelText("Display title") as HTMLInputElement;
    expect(within(panel).getByText(`${displayTitleField.value.length} / 80`)).toBeInTheDocument();
    expect(within(panel).getByLabelText("Source URL")).toBeInTheDocument();
  });

  it("removes internal draft terminology from Dataset Admin's operator-facing load, save, and publish feedback (Project Spec S0060)", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    expect(screen.queryByText("Draft loaded")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Editable fields were populated from the private/admin draft endpoint."),
    ).not.toBeInTheDocument();
    expect(forbiddenDraftTermsPresent()).toEqual([]);

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Save draft" }));
    expect(await screen.findByTestId("dataset-admin-draft-saved")).toBeInTheDocument();
    expect(screen.queryByText("Changes saved.")).not.toBeInTheDocument();
    expect(screen.queryByText("Draft saved through the profile draft model.")).not.toBeInTheDocument();
    expect(forbiddenDraftTermsPresent()).toEqual([]);

    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByText(/^Published at /)).toBeInTheDocument());
    expect(forbiddenDraftTermsPresent()).toEqual([]);
  });

  it("shows compact success feedback beside Publish changes, removes the long success copy, and resets dirty state after each successful publish (Project Spec S0063)", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const toolbarPublishButton = within(toolbar).getByRole("button", { name: "Publish changes" });

    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "First publish-first edit" } });
    expect(toolbarPublishButton).toBeEnabled();
    fireEvent.click(toolbarPublishButton);

    const firstSuccess = await within(toolbar).findByText("Changes saved.");
    expect(firstSuccess).toHaveClass("dataset-admin-toolbar-success");
    expect(firstSuccess.tagName).toBe("SPAN");
    expect(screen.queryByText("Public content published. The public page is ready to view.")).not.toBeInTheDocument();
    await waitFor(() => expect(toolbarPublishButton).toBeDisabled());

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Visible Publicly" }));
    await waitFor(() => expect(screen.getByText("Latest published snapshot is hidden publicly.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Second publish-first edit" } });
    expect(toolbarPublishButton).toBeEnabled();
    fireEvent.click(toolbarPublishButton);

    expect(await within(toolbar).findByText("Changes saved.")).toBeInTheDocument();
    expect(screen.queryByText("Changes published. Public visibility is currently off.")).not.toBeInTheDocument();
    await waitFor(() => expect(toolbarPublishButton).toBeDisabled());
  });

  it("updates the selected Dataset Admin title and selector label after publishing a changed Display title", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    const selector = screen.getByRole("button", { name: "Dataset" });
    expect(selector).toHaveTextContent("Curated churn profile");

    fireEvent.change(screen.getByLabelText("Display title"), { target: { value: "Published renamed profile" } });
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Dataset — Published renamed profile" })).toBeInTheDocument(),
    );
    expect(selector).toHaveTextContent("Published renamed profile");
    expect(selector).not.toHaveTextContent(datasetSlug);
  });

  it("keeps Publish changes failure feedback safe and free of internal draft/endpoint terminology (Project Spec S0060)", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Edited subtitle" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));

    expect(
      await screen.findByText("Public Content changes could not be published. Open the Publishing tab for details."),
    ).toBeInTheDocument();
    expect(forbiddenDraftTermsPresent()).toEqual([]);
  });
});
