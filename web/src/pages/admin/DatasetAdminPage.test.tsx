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
  } = {},
) {
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
      const profile = options.themePresetOverride
        ? { ...publicProfile, theme: { preset: options.themePresetOverride } }
        : publicProfile;
      return jsonResponse({ draft_exists: true, profile });
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
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent(`Telco Customer Churn -- ${datasetSlug}`);
    });
    expect(screen.getByRole("heading", { name: "Dataset -- Telco Customer Churn" })).toBeInTheDocument();
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Not Published");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Public Content",
      "Metadata & Card",
      "Theme Preset",
      "Inference Form",
      "Result Card",
      "Publishing",
      "Live Preview",
    ]);
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Not Published");
    expect(screen.getByLabelText("Visible Publicly")).toBeDisabled();
    expect(screen.getByText("Not published in this session")).toBeInTheDocument();

    await loadDraftOnly();
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Draft");

    const callsBeforePreview = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("heading", { name: "Curated churn profile" })).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(callsBeforePreview);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`))).toHaveLength(0);

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Draft");

    fireEvent.click(screen.getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByLabelText("Publication status")).toHaveTextContent("Published"));
    expect(screen.getByText("Published at 2026-07-03T17:30:00Z.")).toBeInTheDocument();
    expect(screen.getByLabelText("Visible Publicly")).not.toBeDisabled();
    expect(screen.getByText("2026-07-03T17:30:00Z (this session)")).toBeInTheDocument();

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`));
    expect(publishCall?.[1]).toMatchObject({
      method: "PUT",
      headers: { "X-Admin-Token": "operator-token" },
    });

    fireEvent.click(screen.getByLabelText("Visible Publicly"));
    await waitFor(() => expect(screen.getByLabelText("Publication status")).toHaveTextContent("Hidden"));
    expect(screen.getByText("Latest published snapshot is hidden publicly.")).toBeInTheDocument();
    expect(screen.getByText("2026-07-03T17:30:00Z (this session)")).toBeInTheDocument();

    const visibilityCalls = fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`));
    expect(visibilityCalls).toHaveLength(1);
    expect(visibilityCalls[0]?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Token": "operator-token" },
      body: JSON.stringify({ visible: false }),
    });
    expect(fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toHaveLength(1);

    fireEvent.click(screen.getByLabelText("Visible Publicly"));
    await waitFor(() => expect(screen.getByLabelText("Publication status")).toHaveTextContent("Published"));

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Display title"), { target: { value: "Edited churn profile" } });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Unpublished Changes");
    expect(screen.getByRole("button", { name: "Publish changes" })).toBeDisabled();
    expect(screen.getByText(/Save Draft before publishing/)).toBeInTheDocument();
  });

  it("marks the active workspace tab as selected via aria-selected and updates it when switching tabs", async () => {
    installFetchMock();
    render(<DatasetAdminPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent(`Telco Customer Churn -- ${datasetSlug}`);
    });

    expect(screen.getByRole("tab", { name: "Public Content", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Publishing", selected: false })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));

    expect(screen.getByRole("tab", { name: "Publishing", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Public Content", selected: false })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Publish changes" }));

    expect(await screen.findByText("Publishing action rejected by backend validation.")).toBeInTheDocument();
    expect(screen.getByText(/profile - PROFILE_PUBLISH_FAILED - Snapshot validation failed./)).toBeInTheDocument();
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Draft");
  });

  it("surfaces visibility validation feedback without changing public exposure", async () => {
    installFetchMock({ rejectVisibility: true });
    render(<DatasetAdminPage />);

    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(screen.getByLabelText("Publication status")).toHaveTextContent("Published"));
    expect(screen.getByLabelText("Visible Publicly")).toBeChecked();

    fireEvent.click(screen.getByLabelText("Visible Publicly"));

    expect(await screen.findByText("Publishing action rejected by backend validation.")).toBeInTheDocument();
    expect(screen.getByText(/PROFILE_VISIBILITY_PAYLOAD_INVALID - Visibility payload is invalid./)).toBeInTheDocument();
    expect(screen.getByLabelText("Publication status")).toHaveTextContent("Published");
    expect(screen.getByLabelText("Visible Publicly")).toBeChecked();
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
    render(<DatasetAdminPage />);

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "operator-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Load draft" }));
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
    fireEvent.change(screen.getByLabelText("Home card icon"), { target: { value: "chart-line" } });
    fireEvent.change(screen.getByLabelText("Primary metric key"), { target: { value: "accuracy" } });

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.change(screen.getByLabelText("Theme preset"), { target: { value: "atlas-green" } });

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    fireEvent.change(screen.getByLabelText("Badge preset"), { target: { value: "risk" } });
    fireEvent.change(screen.getByLabelText("High badge label"), { target: { value: "Severe risk" } });

    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved through the profile draft model.");

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
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
    render(<DatasetAdminPage />);

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "operator-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Load draft" }));
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
    const { container } = render(<DatasetAdminPage />);

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const backgroundImageField = screen.getByLabelText("Background image reference") as HTMLInputElement;
    expect(backgroundImageField).toHaveAttribute("type", "text");
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  it("renders Live Preview subviews from real public components and the loaded customization", async () => {
    installFetchMock();
    render(<DatasetAdminPage />);

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
    const { container } = render(<DatasetAdminPage />);

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

  it("disables the hide checkbox for a required field and never saves it as hidden", async () => {
    const fetchMock = installFetchMock({ requiredFieldOverride: "tenure" });
    render(<DatasetAdminPage />);

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
    vi.spyOn(document, "elementFromPoint").mockImplementation((_x: number, y: number) =>
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
    const { unmount } = render(<DatasetAdminPage />);
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
    render(<DatasetAdminPage />);
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

  it("shows a disabled selector and a blank read-only panel when no datasets are registered", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [] });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DatasetAdminPage />);

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toBeDisabled());
    expect(selector).toHaveTextContent("No datasets available");

    const panel = screen.getByRole("region", { name: "Read-only Atlas values" });
    expect(within(panel).getAllByText("Not provided")).toHaveLength(6);
  });

  it("populates the filterable selector for a multi-dataset listing including a synthetic non-Telco/Bank dataset and updates the read-only panel on selection change", async () => {
    const datasetOne = {
      dataset_slug: "synthetic-retail-forecast",
      title: "Synthetic Retail Forecast",
      summary: "Synthetic retail demand forecasting dataset",
      domain: "retail",
      visibility: "public",
      tags: ["retail"],
    };
    const datasetTwo = {
      dataset_slug: "synthetic-energy-usage",
      title: "Synthetic Energy Usage",
      summary: "Synthetic household energy usage dataset",
      domain: "energy",
      visibility: "public",
      tags: ["energy"],
    };
    const datasetThree = {
      dataset_slug: "synthetic-agri-yield",
      title: "Synthetic Agricultural Yield",
      summary: "Synthetic crop yield dataset",
      domain: "agriculture",
      visibility: "internal",
      tags: ["agriculture"],
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [datasetOne, datasetTwo, datasetThree] });
      }
      if (url.endsWith(`/datasets/${datasetOne.dataset_slug}`)) {
        return jsonResponse(datasetOne);
      }
      if (url.endsWith(`/datasets/${datasetTwo.dataset_slug}`)) {
        return jsonResponse(datasetTwo);
      }
      if (url.endsWith(`/datasets/${datasetThree.dataset_slug}`)) {
        return jsonResponse(datasetThree);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DatasetAdminPage />);

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toHaveTextContent(`${datasetOne.title} -- ${datasetOne.dataset_slug}`));

    fireEvent.click(selector);
    const listbox = screen.getByRole("listbox", { name: "Available datasets" });
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual([
      `${datasetOne.title} -- ${datasetOne.dataset_slug}`,
      `${datasetTwo.title} -- ${datasetTwo.dataset_slug}`,
      `${datasetThree.title} -- ${datasetThree.dataset_slug}`,
    ]);

    const panel = screen.getByRole("region", { name: "Read-only Atlas values" });
    await waitFor(() => {
      expect(within(panel).getByText(datasetOne.dataset_slug)).toBeInTheDocument();
    });
    expect(within(panel).getByText(datasetOne.title)).toBeInTheDocument();
    expect(within(panel).getByText(datasetOne.domain)).toBeInTheDocument();

    const filter = screen.getByLabelText("Filter datasets");
    fireEvent.change(filter, { target: { value: datasetTwo.dataset_slug } });
    fireEvent.click(within(listbox).getByRole("option", { name: `${datasetTwo.title} -- ${datasetTwo.dataset_slug}` }));

    await waitFor(() => {
      expect(within(panel).getByText(datasetTwo.dataset_slug)).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: `Dataset -- ${datasetTwo.title}` })).toBeInTheDocument();
    expect(within(panel).getByText(datasetTwo.title)).toBeInTheDocument();
    expect(within(panel).getByText(datasetTwo.domain)).toBeInTheDocument();
  });

  it("moves an ARIA active-option indicator through the filtered listbox with ArrowDown/ArrowUp and selects it on Enter", async () => {
    const datasetOne = {
      dataset_slug: "synthetic-retail-forecast",
      title: "Synthetic Retail Forecast",
      summary: "Synthetic retail demand forecasting dataset",
      domain: "retail",
      visibility: "public",
      tags: ["retail"],
    };
    const datasetTwo = {
      dataset_slug: "synthetic-energy-usage",
      title: "Synthetic Energy Usage",
      summary: "Synthetic household energy usage dataset",
      domain: "energy",
      visibility: "public",
      tags: ["energy"],
    };
    const datasetThree = {
      dataset_slug: "synthetic-agri-yield",
      title: "Synthetic Agricultural Yield",
      summary: "Synthetic crop yield dataset",
      domain: "agriculture",
      visibility: "internal",
      tags: ["agriculture"],
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [datasetOne, datasetTwo, datasetThree] });
      }
      if (url.endsWith(`/datasets/${datasetOne.dataset_slug}`)) {
        return jsonResponse(datasetOne);
      }
      if (url.endsWith(`/datasets/${datasetTwo.dataset_slug}`)) {
        return jsonResponse(datasetTwo);
      }
      if (url.endsWith(`/datasets/${datasetThree.dataset_slug}`)) {
        return jsonResponse(datasetThree);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DatasetAdminPage />);

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toHaveTextContent(`${datasetOne.title} -- ${datasetOne.dataset_slug}`));

    fireEvent.click(selector);
    const filter = screen.getByLabelText("Filter datasets");

    expect(filter).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(filter, { key: "ArrowDown" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${datasetOne.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowDown" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${datasetTwo.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowUp" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${datasetOne.dataset_slug}`);

    fireEvent.keyDown(filter, { key: "ArrowUp" });
    expect(filter).toHaveAttribute("aria-activedescendant", `dataset-admin-option-${datasetThree.dataset_slug}`);

    const panel = screen.getByRole("region", { name: "Read-only Atlas values" });
    await waitFor(() => {
      expect(within(panel).getByText(datasetOne.dataset_slug)).toBeInTheDocument();
    });

    fireEvent.keyDown(filter, { key: "Enter" });

    await waitFor(() => {
      expect(within(panel).getByText(datasetThree.dataset_slug)).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: `Dataset -- ${datasetThree.title}` })).toBeInTheDocument();
    expect(within(panel).getByText(datasetThree.title)).toBeInTheDocument();
    expect(within(panel).getByText(datasetThree.domain)).toBeInTheDocument();
    expect(screen.queryByRole("listbox", { name: "Available datasets" })).not.toBeInTheDocument();
  });
});
