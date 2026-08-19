import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DATASET_THEME_PRESETS,
  normalizeDatasetDateOnly,
  presentDatasetOperationalTimestamp,
} from "../../lib/datasetPresentation";
import DatasetAdminPage, {
  emptyLiveInferenceAuditState,
  liveInferenceAuditConsoleLines,
  OPERATIONAL_CONSOLE_BOTTOM_TOLERANCE_PX,
  OperationalConsole,
  reduceLiveInferenceAuditEvent,
} from "./DatasetAdminPage";

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
// S0213: release-governed multiclass semantics are a compatible technical
// state; the page must never recreate a manual problem-type selector.
const MULTICLASS_PROBLEM_TYPE_LABEL = "Multiclass Classification";

describe("Dataset Admin multiclass presentation (S0214)", () => {
  it("keeps the release-derived operator label", () => {
    expect(MULTICLASS_PROBLEM_TYPE_LABEL).toBe("Multiclass Classification");
  });
});

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
    schema_version: "binary-result-presentation.v1",
    positive_class_probability_label: "Churn probability",
    predicted_outcome_label: "Predicted retention status",
    positive_outcome_copy: "Likely to churn",
    negative_outcome_copy: "Likely to stay",
    submit_button_label: "Run prediction",
    model_section_label: "Scoring model",
    interpretation: {
      preset: "risk",
      labels: {
        high: "High risk",
        medium: "Medium risk",
        low: "Low risk",
      },
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
  // Project Spec S0110: absent by default (matching the shared fixture's
  // customization record, which carries no view_copy of its own), typed
  // here so per-test overrides (customizationOverride: { ...customization,
  // view_copy: {...} }) type-check.
  view_copy: undefined as
    | { heading?: string; description?: string; usage_guidance?: string; submit_button_label?: string }
    | undefined,
};

// Project Spec S0143: a valid binary-classification-result.v1 shape
// conformant to the shared authoringContextEnvelope() result_contract
// fixture below (threshold 0.6, churn/retained classes, low/medium/high
// bands) -- the default POST /admin/datasets/{slug}/inference success body.
const DEFAULT_ADMIN_INFERENCE_RESULT = {
  schema_version: "binary-classification-result.v1",
  problem_type: "binary_classification",
  predicted_class: { class_id: "churn" },
  positive_class: { class_id: "churn", event_label: "Customer churn" },
  positive_class_probability: 0.82,
  class_probabilities: [
    { class_id: "retained", probability: 0.18 },
    { class_id: "churn", probability: 0.82 },
  ],
  decision: { threshold: 0.6, predicted_positive: true },
  interpretation: {
    preset: "risk",
    band_id: "high",
    bands: [
      { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
      { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
      { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
    ],
  },
  model_descriptor: { model_family: "linear", display_name: "Retention model" },
};

function installFetchMock(
  options: {
    rejectProfileSave?: boolean;
    rejectPublish?: boolean;
    rejectVisibility?: boolean;
    // Project Spec S0103: forces the predict-view customization PUT to fail
    // backend validation, for exercising the shared Publish changes
    // orchestrator's "customization request fails" path.
    rejectCustomizationSave?: boolean;
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
    publishedSnapshotProfile?: typeof publicProfile;
    freshPromotionHydration?: boolean;
    lastUpdated?: string;
    lastUpdatedAfterPublish?: string;
    releaseDate?: string;
    releaseDateMode?: "auto" | "manual";
    // Project Spec S0098: overrides the dataset-owned eligible predict views
    // GET /datasets/{slug}/views returns. Defaults to the shared single-view
    // fixture ([{ view_id: viewId, ... }]) every other test relies on.
    viewsOverride?: Array<{ view_id: string; display?: { title?: string } }>;
    // Project Spec S0121: GET /admin/datasets/{slug}/authoring-context.
    // authoringContextTransportFailureOnce fails the first request only
    // (non-ok response), auto-clearing so a subsequent automatic
    // reload/Retry succeeds normally -- mirrors customizationLoadFailsOnce's
    // established pattern. viewsResourceUnavailable/contractResourceUnavailable
    // make just that one resource within an otherwise-200 envelope carry a
    // bounded unavailable state, exercising per-resource availability
    // separation. authoringContextDeferredOnce leaves the first request
    // unresolved until the returned fetch mock's
    // releaseDeferredAuthoringContext() is called, for exercising late-
    // response-after-dataset-switch protection.
    authoringContextTransportFailureOnce?: boolean;
    viewsResourceUnavailable?: boolean;
    contractResourceUnavailable?: boolean;
    authoringContextDeferredOnce?: boolean;
    // Project Spec S0098: overrides the profile draft's
    // inference_presentation.bound_predict_view_id independently of the
    // shared publicProfile fixture (which always carries the valid viewId),
    // for exercising a stale-binding rebind scenario. Only applied when an
    // existing draft/profile is returned (ignored with noExistingDraft).
    boundPredictViewIdOverride?: string;
    // Project Spec S0099: the customization GET endpoint reports absence
    // (no stored record) instead of the shared compatible customization
    // fixture.
    customizationAbsent?: boolean;
    // Project Spec S0099: the customization GET endpoint reports the shared
    // customization fixture as incompatible with the current public
    // contract (a historical record that no longer matches), instead of
    // applying it as a compatible overlay.
    customizationIncompatible?: boolean;
    // Project Spec S0099: the customization GET endpoint responds with a
    // transport failure (non-ok response) once, to exercise the
    // unavailable-state Retry control. Automatically cleared after the
    // first GET so a subsequent automatic reload (triggered by Retry)
    // succeeds normally.
    customizationLoadFailsOnce?: boolean;
    // Project Spec S0099: the first customization GET response never
    // resolves on its own -- the caller must invoke the resolver function
    // exposed on the returned fetch mock's releaseDeferredCustomizationLoad
    // property to let it settle. Exercises stale-request protection when
    // the request identity changes while a request is still in flight.
    customizationLoadDeferredOnce?: boolean;
    // Project Spec S0104: replaces the shared compatible `customization`
    // fixture's groups/field_hints entirely for the customization GET
    // response, for tests that need a specific historical shape (a blank
    // group label, a "group-1"/"group-3" collision gap, etc.) without
    // affecting every other test's default fixture.
    customizationOverride?: typeof customization;
    // Project Spec S0104: appended to the /contract response's features
    // array, deliberately never referenced by the shared `customization`
    // fixture's field_hints -- simulates a contract field added after a
    // compatible customization was last saved, to exercise the
    // required/optional default rule applied only to a field the loaded
    // overlay never covered.
    extraContractFields?: Array<{
      name: string;
      label: string;
      optional: boolean;
      // Project Spec S0146: defaults to "number" (every pre-existing caller
      // of this option), letting a test append a checkbox field to exercise
      // the boolean false-state submission contract alongside it.
      input_type?: "number" | "checkbox";
    }>;
    // Project Spec S0116: GET /admin/datasets/{slug}/publication-state.
    // publicationStateUnavailable simulates the private route returning 404
    // (Admin runtime disabled/unreachable). publicationStateMalformed
    // returns valid JSON that fails the frontend's bounded shape validation.
    // publicationStateDeferredOnce leaves the first GET unresolved until the
    // returned fetch mock's releaseDeferredPublicationState() is called, for
    // exercising the "Checking..." loading state deterministically.
    // initialConfiguredVisible seeds the mutable configured-visibility value
    // the mock tracks across visibility PUT writes (default true).
    // publicationStateBuilder fully overrides the projection shape (blockers,
    // observations, snapshot/review state, discrepancies) -- receives the
    // mock's current mutable configured-visibility value.
    publicationStateUnavailable?: boolean;
    publicationStateMalformed?: boolean;
    publicationStateDeferredOnce?: boolean;
    initialConfiguredVisible?: boolean;
    publicationStateBuilder?: (configuredVisible: boolean) => Record<string, unknown>;
    // Project Spec S0143: POST /admin/datasets/{slug}/inference. Defaults to
    // a valid binary result so tests that submit the Live Preview Inference
    // form without opting into a specific outcome still get a bounded
    // success response. adminInferenceErrorCode overrides that with a
    // bounded error response instead. adminInferenceDeferredOnce leaves the
    // first request unresolved until the returned fetch mock's
    // releaseDeferredAdminInference() is called, for exercising the
    // stale-response identity-change guard deterministically.
    adminInferenceResult?: Record<string, unknown>;
    adminInferenceErrorCode?: string;
    adminInferenceDeferredOnce?: boolean;
    inferenceGuidance?: unknown;
    // Project Spec S0147: raw `errors` array entries included alongside
    // adminInferenceErrorCode in the bounded INVALID_PAYLOAD response, for
    // exercising the frontend normalizer/filter/label-resolution pipeline
    // with safe structured validation detail (and, in malformed-entry
    // tests, with entries the normalizer must safely ignore).
    adminInferenceErrors?: unknown[];
    // Project Spec S0151: a raw `runtime_diagnostic` value included alongside
    // adminInferenceErrorCode, for exercising the frontend normalizer and
    // Publishing console line pipeline with both allowlisted and
    // malformed/unknown values.
    adminInferenceRuntimeDiagnostic?: unknown;
    // Project Spec S0154: overrides the authoring-context contract
    // resource's result_contract field for the Dataset Detail Live Preview
    // Target metadata parity contract. Defaults to the shared available
    // churn/retained semantics every other test relies on.
    resultContractOverride?: Record<string, unknown>;
    // Project Spec S0154: overrides the authoring-context context
    // resource's prediction_target_description independently of the shared
    // default ("Customer churn"). Pass null to omit the field entirely.
    predictionTargetDescriptionOverride?: string | null;
    // Project Spec S0205: overrides the authoring-context visualizations
    // resource's data payload independently of the shared stateless default
    // ({}, which carries no dataset_statistics and no charts) -- used only
    // by the Dataset Detail Live Preview Instances metadata contract below.
    visualizationsOverride?: Record<string, unknown>;
  } = {},
) {
  let savedProfileDraft: typeof publicProfile | null = null;
  let savedCustomization: typeof customization | null = null;
  let publishedProfile: typeof publicProfile | null = null;
  let canonicalTimestampAfterPublish: string | null = null;
  let customizationLoadFailurePending = options.customizationLoadFailsOnce ?? false;
  let customizationLoadDeferredPending = options.customizationLoadDeferredOnce ?? false;
  let releaseDeferredCustomizationLoad: (() => void) | null = null;
  let configuredVisible = options.initialConfiguredVisible ?? true;
  let publicationStateDeferredPending = options.publicationStateDeferredOnce ?? false;
  let releaseDeferredPublicationState: (() => void) | null = null;
  let authoringContextTransportFailurePending = options.authoringContextTransportFailureOnce ?? false;
  let authoringContextDeferredPending = options.authoringContextDeferredOnce ?? false;
  let releaseDeferredAuthoringContext: (() => void) | null = null;
  let adminInferenceDeferredPending = options.adminInferenceDeferredOnce ?? false;
  let releaseDeferredAdminInference: (() => void) | null = null;

  // Project Spec S0121: the single GET /admin/datasets/{slug}/authoring-context
  // envelope Dataset Admin now loads its entire technical ReadOnlyData from,
  // replacing the six separate public-technical-read fixtures below (kept in
  // place, but no longer requested by the app -- see the boundary test
  // asserting they are never called). Resource content mirrors those retired
  // fixtures exactly so every existing assertion about rendered contract
  // fields, context copy, metrics, or eligible views keeps passing unchanged.
  function authoringContextEnvelope(): Record<string, unknown> {
    return {
      dataset_slug: datasetSlug,
      active_release: "release-20260619-001",
      dataset: {
        status: "ready",
        data: {
          dataset_slug: datasetSlug,
          title: "Telco Customer Churn",
          display_title: options.noExistingDraft
            ? null
            : publishedProfile?.display.title ?? publicProfile.display.title,
          summary: "Customer churn prediction dataset",
          domain: "telecom",
          tags: ["telecom"],
          active_release: "release-20260619-001",
          publication_status: "ready",
        },
      },
      context: {
        status: "ready",
        data: {
          title: "Telco Customer Churn",
          summary: "Baseline churn problem summary",
          domain: "telecom",
          tags: ["telecom"],
          problem_type: "binary_classification",
          prediction_target_description:
            options.predictionTargetDescriptionOverride === null
              ? undefined
              : options.predictionTargetDescriptionOverride ?? "Customer churn",
        },
      },
      contract: options.contractResourceUnavailable
        ? {
            status: "unavailable",
            error: {
              type: "contract_unavailable",
              code: "PUBLIC_CONTRACT_UNAVAILABLE",
              message: "The public contract for this dataset is temporarily unavailable.",
            },
          }
        : {
            status: "ready",
            data: {
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
                  ...(options.extraContractFields ?? []).map((field, index) => ({
                    name: field.name,
                    label: field.label,
                    input_type: field.input_type ?? ("number" as const),
                    optional: field.optional,
                    display_order: 3 + index,
                  })),
                ],
              },
              result_contract: options.resultContractOverride ?? {
                status: "available",
                semantics: {
                  schema_version: "binary-result-semantics.v1",
                  problem_type: "binary_classification",
                  result_schema_version: "binary-classification-result.v1",
                  primary_output: "positive_class_probability",
                  positive_class: { class_id: "churn", event_label: "Customer churn" },
                  negative_class: { class_id: "retained" },
                  decision: { threshold: 0.6 },
                  interpretation: {
                    preset: "risk",
                    bands: [
                      { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
                      { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
                      { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
                    ],
                  },
                  model_descriptor: { model_family: "linear", display_name: "Retention model" },
                },
              },
            },
          },
      inference_guidance: {
        status: "ready",
        data: options.inferenceGuidance ?? [],
      },
      metrics: {
        status: "ready",
        data: { evaluation: { metrics: options.metricsOverride ?? { auc_roc: 0.93, accuracy: 0.86 } } },
      },
      visualizations: { status: "ready", data: options.visualizationsOverride ?? {} },
      views: options.viewsResourceUnavailable
        ? {
            status: "unavailable",
            error: {
              type: "predict_view_registry_unavailable",
              code: "PREDICT_VIEW_REGISTRY_UNAVAILABLE",
              message: "The Predict View registry is temporarily unavailable.",
            },
          }
        : {
            status: "ready",
            data: options.viewsOverride ?? [{ view_id: viewId, display: { title: "Churn risk overview" } }],
          },
    };
  }

  function defaultPublicationState(visible: boolean): Record<string, unknown> {
    return {
      dataset_slug: datasetSlug,
      active_release: "release-20260619-001",
      visibility: {
        configured_visible: visible,
        source: "explicit_record",
        record_status: "valid",
        updated_at: "2026-07-03T17:35:00Z",
        effective_visible: visible,
      },
      review: { status: "ready", approval_allowed: false, approval_blockers: [] },
      snapshot: {
        status: "current_release",
        exists: true,
        published_at: "2026-07-11T14:00:00Z",
        active_release_at_publish_time: "release-20260619-001",
        matches_active_release: true,
      },
      public_access: {
        reachable: visible,
        blockers: visible ? [] : ["visibility_disabled"],
        observations: [],
      },
    };
  }
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
            display_title: options.noExistingDraft
              ? null
              : publishedProfile?.display.title ?? publicProfile.display.title,
            summary: "Customer churn prediction dataset",
            domain: "telecom",
            tags: ["telecom"],
            active_release: "release-20260619-001",
            publication_status: "ready",
            last_updated:
              canonicalTimestampAfterPublish
                ? canonicalTimestampAfterPublish
                : publishedProfile && options.lastUpdatedAfterPublish
                ? options.lastUpdatedAfterPublish
                : options.lastUpdated ?? "2026-06-19T12:00:00Z",
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
    if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
      if (authoringContextDeferredPending) {
        authoringContextDeferredPending = false;
        return new Promise<MockResponse>((resolve) => {
          releaseDeferredAuthoringContext = () => resolve(jsonResponse(authoringContextEnvelope()));
        });
      }
      if (authoringContextTransportFailurePending) {
        authoringContextTransportFailurePending = false;
        return jsonResponse({}, 503);
      }
      return jsonResponse(authoringContextEnvelope());
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
            ...(options.extraContractFields ?? []).map((field, index) => ({
              name: field.name,
              label: field.label,
              input_type: "number" as const,
              optional: field.optional,
              display_order: 3 + index,
            })),
          ],
        },
        result_contract: {
          status: "available",
          semantics: {
            schema_version: "binary-result-semantics.v1",
            problem_type: "binary_classification",
            result_schema_version: "binary-classification-result.v1",
            primary_output: "positive_class_probability",
            positive_class: { class_id: "churn", event_label: "Customer churn" },
            negative_class: { class_id: "retained" },
            decision: { threshold: 0.6 },
            interpretation: {
              preset: "risk",
              bands: [
                { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
                { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
                { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
              ],
            },
            model_descriptor: { model_family: "linear", display_name: "Retention model" },
          },
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
      return jsonResponse({
        views: options.viewsOverride ?? [{ view_id: viewId, display: { title: "Churn risk overview" } }],
      });
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
      const submittedProfile = (
        typeof init.body === "string"
          ? JSON.parse(init.body)
          : options.trackProfileDraftSaves
          ? savedProfileDraft ?? publicProfile
          : publicProfile
      ) as typeof publicProfile & { dataset_detail_time_zone?: string };
      const { dataset_detail_time_zone: _timeZone, ...profile } = submittedProfile;
      publishedProfile = profile;
      if (profile.display.release_date_label) {
        canonicalTimestampAfterPublish = `${profile.display.release_date_label}T03:00:00Z`;
      }
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
      configuredVisible = body.visible ?? true;
      return jsonResponse({
        dataset_slug: datasetSlug,
        visible: body.visible ?? true,
        updated_at: "2026-07-03T17:35:00Z",
      });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`)) {
      if (options.publicationStateUnavailable) {
        return jsonResponse({}, 404);
      }
      if (publicationStateDeferredPending) {
        publicationStateDeferredPending = false;
        return new Promise<MockResponse>((resolve) => {
          releaseDeferredPublicationState = () =>
            resolve(jsonResponse((options.publicationStateBuilder ?? defaultPublicationState)(configuredVisible)));
        });
      }
      if (options.publicationStateMalformed) {
        return jsonResponse({ dataset_slug: datasetSlug });
      }
      return jsonResponse((options.publicationStateBuilder ?? defaultPublicationState)(configuredVisible));
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
    if (url.endsWith(`/admin/datasets/${datasetSlug}/home-card-image`) && init?.method === "POST") {
      const headers = init.headers as Record<string, string>;
      if (decodeURIComponent(headers["X-File-Name"]).includes("fail") || headers["Content-Type"] === "image/svg+xml") {
        return jsonResponse({ errors: [{ message: "Choose a PNG, JPEG, WebP, or AVIF image." }] }, 422);
      }
      return jsonResponse({ uploaded: true, media_ref: "/media/home-cards/0123456789abcdef0123456789abcdef.png" });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`)) {
      if (options.noExistingDraft) {
        return jsonResponse({ draft_exists: false, profile: null });
      }
      const profile =
        publishedProfile ?? {
          ...publicProfile,
          display: {
            ...publicProfile.display,
            release_date_label: options.releaseDate ?? publicProfile.display.release_date_label,
            release_date_mode: options.releaseDateMode ?? publicProfile.display.release_date_mode,
          },
          ...(options.themePresetOverride ? { theme: { preset: options.themePresetOverride } } : {}),
          ...(options.boundPredictViewIdOverride !== undefined
            ? { inference_presentation: { bound_predict_view_id: options.boundPredictViewIdOverride } }
            : {}),
        };
      if (options.trackProfileDraftSaves) {
        savedProfileDraft = profile;
      }
      return jsonResponse({
        draft_exists: true,
        profile,
        profile_hydration: options.freshPromotionHydration
          ? { source: "fresh_promotion_baseline", active_release: "release-20260619-001" }
          : options.publishedSnapshotProfile
          ? { source: "current_release_snapshot", active_release: "release-20260619-001" }
          : undefined,
        published_snapshot: options.publishedSnapshotProfile
          ? {
              source_draft_schema_version: options.publishedSnapshotProfile.schema_version,
              published_at: "2026-07-11T14:00:00Z",
              active_release_at_publish_time: "release-20260619-001",
              profile: options.publishedSnapshotProfile,
            }
          : null,
      });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) && init?.method === "PUT") {
      if (options.rejectCustomizationSave) {
        return jsonResponse(
          {
            saved: false,
            errors: [{ field: "field_hints", code: "CUSTOMIZATION_REJECTED", message: "Customization failed validation." }],
          },
          422,
        );
      }
      if (options.trackCustomizationSaves) {
        const body = typeof init.body === "string" ? (JSON.parse(init.body) as typeof customization) : customization;
        savedCustomization = body;
        return jsonResponse({ saved: true, customization: body });
      }
      return jsonResponse({ saved: true, customization });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`)) {
      if (customizationLoadDeferredPending) {
        customizationLoadDeferredPending = false;
        return new Promise<MockResponse>((resolve) => {
          releaseDeferredCustomizationLoad = () =>
            resolve(
              jsonResponse({
                customization_exists: true,
                compatibility_status: "compatible",
                customization,
                errors: [],
              }),
            );
        });
      }
      if (customizationLoadFailurePending) {
        customizationLoadFailurePending = false;
        return jsonResponse({}, 500);
      }
      // A locally tracked save (trackCustomizationSaves) always reflects
      // the most current persisted state, so it takes precedence over the
      // static customizationAbsent/customizationIncompatible fixtures,
      // which describe the state only before any save happens this test.
      if (options.trackCustomizationSaves && savedCustomization) {
        return jsonResponse({
          customization_exists: true,
          compatibility_status: "compatible",
          customization: savedCustomization,
          errors: [],
        });
      }
      if (options.customizationOverride) {
        return jsonResponse({
          customization_exists: true,
          compatibility_status: "compatible",
          customization: options.customizationOverride,
          errors: [],
        });
      }
      if (options.customizationAbsent) {
        return jsonResponse({
          customization_exists: false,
          compatibility_status: "absent",
          customization: null,
          errors: [],
        });
      }
      if (options.customizationIncompatible) {
        return jsonResponse({
          customization_exists: true,
          compatibility_status: "incompatible",
          customization: null,
          errors: [{ code: "UNKNOWN_FIELD_REFERENCE", field: "field_hints[0].field_name", message: "Unknown field." }],
        });
      }
      return jsonResponse({
        customization_exists: true,
        compatibility_status: "compatible",
        customization,
        errors: [],
      });
    }
    if (url.endsWith(`/admin/datasets/${datasetSlug}/inference`) && init?.method === "POST") {
      if (adminInferenceDeferredPending) {
        adminInferenceDeferredPending = false;
        return new Promise<MockResponse>((resolve) => {
          releaseDeferredAdminInference = () =>
            resolve(
              options.adminInferenceErrorCode
                ? jsonResponse(
                    {
                      error_code: options.adminInferenceErrorCode,
                      ...(options.adminInferenceErrors ? { errors: options.adminInferenceErrors } : {}),
                      ...(options.adminInferenceRuntimeDiagnostic !== undefined
                        ? { runtime_diagnostic: options.adminInferenceRuntimeDiagnostic }
                        : {}),
                    },
                    422,
                  )
                : jsonResponse({
                    dataset_slug: datasetSlug,
                    result: options.adminInferenceResult ?? DEFAULT_ADMIN_INFERENCE_RESULT,
                  }),
            );
        });
      }
      if (options.adminInferenceErrorCode) {
        return jsonResponse(
          {
            error_code: options.adminInferenceErrorCode,
            ...(options.adminInferenceErrors ? { errors: options.adminInferenceErrors } : {}),
            ...(options.adminInferenceRuntimeDiagnostic !== undefined
              ? { runtime_diagnostic: options.adminInferenceRuntimeDiagnostic }
              : {}),
          },
          422,
        );
      }
      return jsonResponse({
        dataset_slug: datasetSlug,
        result: options.adminInferenceResult ?? DEFAULT_ADMIN_INFERENCE_RESULT,
      });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return Object.assign(fetchMock, {
    releaseDeferredCustomizationLoad: () => releaseDeferredCustomizationLoad?.(),
    releaseDeferredPublicationState: () => releaseDeferredPublicationState?.(),
    releaseDeferredAuthoringContext: () => releaseDeferredAuthoringContext?.(),
    releaseDeferredAdminInference: () => releaseDeferredAdminInference?.(),
  });
}

async function loadDraftOnly() {
  expect(screen.queryByLabelText(["Operator", "token"].join(" "))).not.toBeInTheDocument();
  expect(await screen.findByTestId("dataset-admin-draft-ready")).toBeInTheDocument();
  expect(screen.queryByText("Content loaded")).not.toBeInTheDocument();
  expect(screen.queryByText("Editable fields were populated from your last saved content.")).not.toBeInTheDocument();
}

async function loadDraftAndCustomization() {
  // Project Spec S0099: the Inference Form builder now bootstraps
  // automatically once a dataset, bound predict view, and public contract
  // are all ready -- no "Load customization" click is required or exists
  // in the normal path. Project Spec S0103 removes the normal
  // "Customization loaded"/"No customization yet" lifecycle panels, so this
  // waits on the builder's own Field bank region (present for every
  // draft-bearing customization state) instead of that removed copy.
  await loadDraftOnly();
  fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
  expect(await screen.findByLabelText("Field bank")).toBeInTheDocument();
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
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("reduces the Publishing tab to exactly the Visible publicly switch and the operational console (Project Spec S0116)", async () => {
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
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");

    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeInTheDocument();
    expect(within(panel).getByRole("log", { name: "Dataset publication operational status" })).toBeInTheDocument();

    expect(within(panel).queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Publish changes" })).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Publishing rule summary")).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Current publication state")).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Documented publication states")).not.toBeInTheDocument();
    expect(within(panel).queryByText("Last published")).not.toBeInTheDocument();

    // The global workspace toolbar's own Publish changes action remains.
    expect(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    ).toBeInTheDocument();
  });

  it("hydrates the switch from configured_visible, saves a PUT on toggle, and reconciles via re-fetch on success (Project Spec S0116; Project Spec S0123 saving/reconciliation action-state coverage)", async () => {
    const fetchMock = installFetchMock({ initialConfiguredVisible: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    // Confirmed ready + configured_visible = true: the public-page action
    // starts enabled.
    await waitFor(() => expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled());
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());
    expect(switchInput).not.toBeDisabled();

    const callsBeforeToggle = fetchMock.mock.calls.length;
    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).toBeDisabled());
    // Project Spec S0123: while the write is unresolved ("saving"), the
    // action must be disabled -- the retained prior confirmed projection
    // must not be used to keep it interactive.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
    await waitFor(() => expect(switchInput).not.toBeChecked());
    await waitFor(() => expect(switchInput).not.toBeDisabled());
    // Reconciled to a confirmed configured_visible = false: the action is
    // disabled again, this time because the confirmed value is genuinely
    // hidden, not merely because a write is in flight.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    const visibilityCalls = fetchMock.mock.calls
      .slice(callsBeforeToggle)
      .filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/visibility`));
    expect(visibilityCalls).toHaveLength(1);
    expect(visibilityCalls[0]?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible: false }),
    });
    // Successful PUT triggers an authoritative re-fetch of publication-state.
    const publicationStateCallsAfter = fetchMock.mock.calls
      .slice(callsBeforeToggle)
      .filter((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publication-state`));
    expect(publicationStateCallsAfter.length).toBeGreaterThanOrEqual(1);
  });

  it("keeps the public-page action disabled throughout an unresolved visibility write and enables it only once the write reconciles to a confirmed configured_visible = true (Project Spec S0123)", async () => {
    // This mock's own fetch mocks (installFetchMock's default PUT+re-fetch
    // chain) resolve too fast for the transient "saving" window to be
    // reliably observed via waitFor -- by the time an awaited assertion
    // settles, the reconciliation may have already completed. This test
    // instead deterministically holds the visibility PUT unresolved (same
    // releaseDeferred* pattern already used for publication-state above)
    // so the mid-flight disabled state can be asserted with certainty.
    const putHolder: { release: (() => void) | null } = { release: null };
    let configuredVisible = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: datasetSlug,
              title: "Telco Customer Churn",
              display_title: null,
              summary: "s",
              domain: "telecom",
              tags: [],
              active_release: "release-20260619-001",
              publication_status: "ready",
              last_updated: "2026-06-19T12:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "private", tags: [] }],
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/visibility`) && init?.method === "PUT") {
        return new Promise<MockResponse>((resolve) => {
          putHolder.release = () =>
            resolve(jsonResponse({ dataset_slug: datasetSlug, visible: true, updated_at: "2026-07-03T17:35:00Z" }));
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`)) {
        return jsonResponse({
          dataset_slug: datasetSlug,
          active_release: "release-20260619-001",
          visibility: {
            configured_visible: configuredVisible,
            source: "explicit_record",
            record_status: "valid",
            updated_at: "2026-07-03T17:35:00Z",
            effective_visible: configuredVisible,
          },
          review: { status: "ready", approval_allowed: false, approval_blockers: [] },
          snapshot: {
            status: "current_release",
            exists: true,
            published_at: "2026-07-11T14:00:00Z",
            active_release_at_publish_time: "release-20260619-001",
            matches_active_release: true,
          },
          public_access: {
            reachable: configuredVisible,
            blockers: configuredVisible ? [] : ["visibility_disabled"],
            observations: [],
          },
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Telco Customer Churn");
    });
    // Confirmed ready + configured_visible = false: starts disabled.
    await waitFor(() => expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled());

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).not.toBeChecked());

    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).toBeDisabled());
    // The PUT is deliberately held unresolved here -- this is a
    // deterministic, not merely likely, mid-flight observation. Optimistic
    // pending value (checked) does not enable the action while unresolved.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    configuredVisible = true;
    putHolder.release?.();
    await waitFor(() => expect(switchInput).not.toBeDisabled());
    // Reconciled to a confirmed configured_visible = true: now enabled.
    await waitFor(() => expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled());
  });

  it("toggles false to true and restores the previous authoritative value with a safe console error on PUT failure, without touching the header badge (Project Spec S0116)", async () => {
    installFetchMock({ initialConfiguredVisible: false, rejectVisibility: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    // A configured-hidden, effective-hidden dataset is not publicly
    // reachable under this mock's default builder.
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).not.toBeChecked());

    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).toBeChecked());
    await waitFor(() => expect(switchInput).not.toBeChecked());
    expect(switchInput).not.toBeDisabled();

    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("Configured visibility could not be saved. The previous confirmed value remains active.", {
        exact: false,
      }),
    ).toBeInTheDocument();
    // The header badge is never altered from unverified local state on a
    // failed write -- it still reflects the last authoritative (hidden,
    // unreachable) projection.
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private");
    // Project Spec S0123: the failed write's rollback restores the same
    // confirmed (disabled) action state that was active before the attempt.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
  });

  it("preserves the last confirmed enabled public-page action state when a visibility write fails (Project Spec S0123)", async () => {
    // Same deterministic deferred-PUT technique as the test above -- this
    // repo's default mock PUT+re-fetch chain resolves too fast to reliably
    // observe the mid-flight "saving" window via waitFor alone.
    const putHolder: { release: (() => void) | null } = { release: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: datasetSlug,
              title: "Telco Customer Churn",
              display_title: null,
              summary: "s",
              domain: "telecom",
              tags: [],
              active_release: "release-20260619-001",
              publication_status: "ready",
              last_updated: "2026-06-19T12:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/visibility`) && init?.method === "PUT") {
        return new Promise<MockResponse>((resolve) => {
          putHolder.release = () =>
            resolve(
              jsonResponse(
                { error_code: "PROFILE_VISIBILITY_PAYLOAD_INVALID", message: "Visibility payload is invalid." },
                400,
              ),
            );
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`)) {
        return jsonResponse({
          dataset_slug: datasetSlug,
          active_release: "release-20260619-001",
          visibility: {
            configured_visible: true,
            source: "explicit_record",
            record_status: "valid",
            updated_at: "2026-07-03T17:35:00Z",
            effective_visible: true,
          },
          review: { status: "ready", approval_allowed: false, approval_blockers: [] },
          snapshot: {
            status: "current_release",
            exists: true,
            published_at: "2026-07-11T14:00:00Z",
            active_release_at_publish_time: "release-20260619-001",
            matches_active_release: true,
          },
          public_access: { reachable: true, blockers: [], observations: [] },
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Telco Customer Churn");
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled());

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());

    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).toBeDisabled());
    // The PUT is deliberately held unresolved -- deterministic mid-flight
    // observation, not a race against the mock's own resolution speed.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    putHolder.release?.();
    await waitFor(() => expect(switchInput).not.toBeDisabled());

    // The failed write rolled back to the last confirmed
    // configured_visible = true projection, so the action is enabled again,
    // exactly as it was before the failed attempt.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
  });

  it("does not dirty the profile workspace or enable the global Publish changes button when only the visibility switch is toggled (Project Spec S0116)", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());

    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).not.toBeDisabled());

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();
  });

  it("does not disable the switch when the published snapshot is missing or stale (Project Spec S0116)", async () => {
    installFetchMock({
      publicationStateBuilder: (visible) => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: visible,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: true,
        },
        review: { status: "ready", approval_allowed: false, approval_blockers: [] },
        snapshot: {
          status: "missing",
          exists: false,
          published_at: null,
          active_release_at_publish_time: null,
          matches_active_release: null,
        },
        public_access: { reachable: true, blockers: [], observations: ["snapshot_missing"] },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).not.toBeDisabled());
  });

  it("shows Checking... while loading and reports a safe error when the private publication-state API is unavailable (Project Spec S0116)", async () => {
    installFetchMock({ publicationStateUnavailable: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");

    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    expect(
      within(panel).getByText("Publication state could not be loaded from the private Admin API.", { exact: false }),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeDisabled();
    // Project Spec S0123: an unavailable projection carries no confirmed
    // configured_visible value, so the public-page action stays disabled too.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
  });

  it("treats an invalid/malformed publication-state response as unavailable rather than partially rendering it (Project Spec S0116)", async () => {
    installFetchMock({ publicationStateMalformed: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");

    await waitFor(() =>
      expect(within(panel).getByText(/Publication state (could not be loaded|response was not in the expected shape)/)).toBeInTheDocument(),
    );
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeDisabled();
    // Project Spec S0123: same as the unavailable case above -- no confirmed
    // projection means the action cannot be enabled.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
  });

  it("shows a Checking... loading line and header while the publication-state request is in flight (Project Spec S0116)", async () => {
    const fetchMock = installFetchMock({ publicationStateDeferredOnce: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");

    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Checking...");
    expect(within(panel).getByText("Checking publication state...", { exact: false })).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeDisabled();
    // Project Spec S0123: loading carries no confirmed value either.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    fetchMock.releaseDeferredPublicationState();
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    // Once the deferred response resolves to a ready, configured-visible
    // projection, the action becomes enabled.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
  });

  it("reports the review-pending blocker, marks the route not reachable when review status is needs_review, and keeps the public-page action enabled since it follows configured visibility, not reachability (Project Spec S0116; principal regression contract for Project Spec S0123)", async () => {
    installFetchMock({
      publicationStateBuilder: (visible) => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: visible,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: true,
        },
        review: { status: "needs_review", approval_allowed: true, approval_blockers: [] },
        snapshot: {
          status: "current_release",
          exists: true,
          published_at: "2026-07-11T14:00:00Z",
          active_release_at_publish_time: "release-20260619-001",
          matches_active_release: true,
        },
        public_access: { reachable: false, blockers: ["review_pending"], observations: [] },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("Dataset review state prevents public access.", { exact: false }),
    ).toBeInTheDocument();
    // The switch still follows configured_visible (true here) even while
    // the route is not reachable -- the frontend never forces these to
    // match.
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeChecked();
    // Project Spec S0123 principal regression contract: a confirmed
    // configured_visible = true projection keeps the "Open public Dataset
    // Detail page" action enabled even though public_access.reachable is
    // false (review_pending) and the header badge reads Private -- the
    // action follows configured visibility, not effective reachability.
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private");
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(`/dataset/${datasetSlug}`, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("reports both the visibility_disabled and review_pending blockers together, in deterministic order (Project Spec S0116)", async () => {
    installFetchMock({
      publicationStateBuilder: () => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: false,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: false,
        },
        review: { status: "needs_review", approval_allowed: true, approval_blockers: [] },
        snapshot: {
          status: "current_release",
          exists: true,
          published_at: "2026-07-11T14:00:00Z",
          active_release_at_publish_time: "release-20260619-001",
          matches_active_release: true,
        },
        public_access: {
          reachable: false,
          blockers: ["visibility_disabled", "review_pending"],
          observations: [],
        },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
    await waitFor(() =>
      expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).not.toBeDisabled(),
    );
    const lineTexts = Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line")).map(
      (el) => el.textContent ?? "",
    );
    const disabledIndex = lineTexts.findIndex((text) => text.includes("disabled by the effective visibility policy"));
    const reviewIndex = lineTexts.findIndex((text) => text.includes("review state prevents public access"));
    expect(disabledIndex).toBeGreaterThanOrEqual(0);
    expect(reviewIndex).toBeGreaterThan(disabledIndex);
  });

  it("renders an unrecognized blocker/observation code as a bounded generic line without exposing the raw code (Project Spec S0116)", async () => {
    installFetchMock({
      publicationStateBuilder: () => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: true,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: true,
        },
        review: { status: "ready", approval_allowed: false, approval_blockers: [] },
        snapshot: {
          status: "current_release",
          exists: true,
          published_at: "2026-07-11T14:00:00Z",
          active_release_at_publish_time: "release-20260619-001",
          matches_active_release: true,
        },
        public_access: {
          reachable: true,
          blockers: ["some_future_backend_blocker_code"],
          observations: ["some_future_backend_observation_code"],
        },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    await waitFor(() =>
      expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).not.toBeDisabled(),
    );
    expect(
      within(panel).getByText("Public access is blocked by an unrecognized backend condition.", { exact: false }),
    ).toBeInTheDocument();
    expect(within(panel).getByText("An additional backend operational observation is present.", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("some_future_backend_blocker_code")).not.toBeInTheDocument();
    expect(screen.queryByText("some_future_backend_observation_code")).not.toBeInTheDocument();
  });

  it("shows the configured-hidden/effectively-visible discrepancy as a warning without forcing the values to match, and keeps the public-page action disabled even though the badge reads Public (Project Spec S0116; Project Spec S0123)", async () => {
    installFetchMock({
      publicationStateBuilder: () => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: false,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: true,
        },
        review: { status: "ready", approval_allowed: false, approval_blockers: [] },
        snapshot: {
          status: "missing",
          exists: false,
          published_at: null,
          active_release_at_publish_time: null,
          matches_active_release: null,
        },
        public_access: {
          reachable: true,
          blockers: [],
          // Project Spec S0125: snapshot_missing is no longer ever emitted as
          // a non-blocking observation (it always blocks reachability when
          // it applies) -- only the legacy, backend-dead-since-S0117
          // configured_hidden_but_effectively_visible_without_snapshot
          // observation code remains exercised here, purely as a rendering
          // resilience check for an unrecognized/legacy code.
          observations: ["configured_hidden_but_effectively_visible_without_snapshot"],
        },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    // The badge follows public_access.reachable (true) even though the
    // switch (configured_visible) is unchecked -- two distinct facts.
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    // Project Spec S0123: the public-page action follows configured
    // visibility, never reachability -- it must stay disabled here even
    // though a synthetic fixture reports public_access.reachable = true and
    // the header badge reads Public.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).not.toBeChecked();
    expect(
      within(panel).getByText(
        "Configured visibility is hidden, but current no-snapshot policy still leaves the public route effectively visible.",
        { exact: false },
      ),
    ).toBeInTheDocument();
  });

  it("reports a stale snapshot and a visibility-record observation without disabling the switch (Project Spec S0116)", async () => {
    installFetchMock({
      publicationStateBuilder: (visible) => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260701-001",
        visibility: {
          configured_visible: visible,
          source: "default_visible",
          record_status: "invalid_json",
          updated_at: null,
          effective_visible: true,
        },
        review: { status: "ready", approval_allowed: false, approval_blockers: [] },
        snapshot: {
          status: "stale_release",
          exists: true,
          published_at: "2026-06-01T00:00:00Z",
          active_release_at_publish_time: "release-20260619-001",
          matches_active_release: false,
        },
        public_access: {
          // Project Spec S0125: a stale snapshot always blocks reachability
          // now, so snapshot_stale moved from a non-blocking observation
          // into blockers -- reachable is no longer true here.
          reachable: false,
          blockers: ["snapshot_stale"],
          observations: ["visibility_record_invalid"],
        },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    await waitFor(() => expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).not.toBeDisabled());
    expect(
      within(panel).getByText("Visibility record is invalid; the backend fallback is active.", { exact: false }),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("Published snapshot belongs to a different active release.", { exact: false }),
    ).toBeInTheDocument();
  });

  it("resets the previous dataset's publication projection immediately and ignores a superseded response on dataset switch (Project Spec S0116; Project Spec S0123 stale-response action-guard coverage)", async () => {
    const otherSlug = "energy-consumption-forecast";
    const firstSlugResponseHolder: { release: (() => void) | null } = { release: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: datasetSlug,
              title: "Telco Customer Churn",
              display_title: null,
              summary: "s",
              domain: "telecom",
              tags: [],
              active_release: "release-20260619-001",
              publication_status: "ready",
              last_updated: "2026-06-19T12:00:00Z",
            },
            {
              dataset_slug: otherSlug,
              title: "Energy Consumption Forecast",
              display_title: null,
              summary: "s",
              domain: "energy",
              tags: [],
              active_release: "release-20260701-001",
              publication_status: "ready",
              last_updated: "2026-07-01T12:00:00Z",
            },
          ],
        });
      }
      // The public /datasets listing seeds the initial selectedSlug; it is
      // unrelated to the header badge authority under test here.
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`)) {
        // Deliberately slow/deferred: resolves only after the operator has
        // already switched to otherSlug below, so this response must never
        // be allowed to overwrite otherSlug's own projection.
        return new Promise((resolve) => {
          firstSlugResponseHolder.release = () =>
            resolve(
              jsonResponse({
                dataset_slug: datasetSlug,
                active_release: "release-20260619-001",
                visibility: {
                  configured_visible: true,
                  source: "explicit_record",
                  record_status: "valid",
                  updated_at: "2026-07-03T17:35:00Z",
                  effective_visible: true,
                },
                review: { status: "ready", approval_allowed: false, approval_blockers: [] },
                snapshot: {
                  status: "current_release",
                  exists: true,
                  published_at: "2026-07-11T14:00:00Z",
                  active_release_at_publish_time: "release-20260619-001",
                  matches_active_release: true,
                },
                public_access: { reachable: true, blockers: [], observations: [] },
              }),
            );
        });
      }
      if (url.endsWith(`/admin/datasets/${otherSlug}/publication-state`)) {
        return jsonResponse({
          dataset_slug: otherSlug,
          active_release: "release-20260701-001",
          visibility: {
            configured_visible: false,
            source: "explicit_record",
            record_status: "valid",
            updated_at: "2026-07-01T00:00:00Z",
            effective_visible: false,
          },
          review: { status: "ready", approval_allowed: false, approval_blockers: [] },
          snapshot: {
            status: "missing",
            exists: false,
            published_at: null,
            active_release_at_publish_time: null,
            matches_active_release: null,
          },
          public_access: { reachable: false, blockers: ["visibility_disabled"], observations: [] },
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

    fireEvent.click(selector);
    fireEvent.click(screen.getByRole("option", { name: "Energy Consumption Forecast" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Dataset — Energy Consumption Forecast" })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    // Project Spec S0123: otherSlug's own confirmed configured_visible =
    // false keeps the action disabled, and the destination it would open
    // (if enabled) is otherSlug's own route -- never the previously
    // selected dataset's.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    // Now let the superseded first-dataset response resolve -- it must be
    // rejected (its own dataset_slug no longer matches the current
    // selection) and must not flip the header back to Public.
    firstSlugResponseHolder.release?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private");
    // Project Spec S0123: the stale telco response (configured_visible =
    // true) must not enable the action for the now-selected otherSlug.
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("reconciles the publication-state projection after a successful global Publish changes (Project Spec S0116)", async () => {
    let reviewStatus: "ready" | "needs_review" = "needs_review";
    const fetchMock = installFetchMock({
      publicationStateBuilder: () => ({
        dataset_slug: datasetSlug,
        active_release: "release-20260619-001",
        visibility: {
          configured_visible: true,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-03T17:35:00Z",
          effective_visible: true,
        },
        review: {
          status: reviewStatus,
          approval_allowed: false,
          approval_blockers: reviewStatus === "needs_review" ? ["snapshot_missing"] : [],
        },
        snapshot: {
          status: reviewStatus === "ready" ? "current_release" : "missing",
          exists: reviewStatus === "ready",
          published_at: reviewStatus === "ready" ? "2026-07-03T17:30:00Z" : null,
          active_release_at_publish_time: reviewStatus === "ready" ? "release-20260619-001" : null,
          matches_active_release: reviewStatus === "ready" ? true : null,
        },
        public_access: {
          reachable: reviewStatus === "ready",
          blockers: reviewStatus === "ready" ? [] : ["review_pending", "snapshot_missing"],
          observations: [],
        },
      }),
    });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));

    // A successful publish (the mock always reports review ready afterward)
    // must reconcile review/snapshot/reachability through a fresh
    // publication-state fetch, not just the profile-publish response.
    reviewStatus = "ready";
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Publish-triggers-reconciliation" } });
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));

    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();
    void fetchMock;
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
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
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

    // The Publishing tab itself renders only the switch and the operational
    // console (Project Spec S0116) -- no tab-local publish/save actions.
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("checkbox", { name: "Visible Publicly" })).toBeInTheDocument();
    expect(within(panel).getByRole("log", { name: "Dataset publication operational status" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Publish changes" })).not.toBeInTheDocument();
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

  it("opens the public Dataset Detail page in a new tab, with noopener/noreferrer isolation, only while the selected dataset is confirmed configured-visible (Project Spec S0123)", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(`/dataset/${datasetSlug}`, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("encodes a destination slug containing reserved/non-ASCII characters with encodeURIComponent when opening the public Dataset Detail page (Project Spec S0123)", async () => {
    const specialSlug = "conjunto-de-dados-são-paulo";
    const encodedSlug = encodeURIComponent(specialSlug);
    // Confirms the fixture slug actually needs encoding -- otherwise this
    // test would pass even if the production code stopped encoding.
    expect(encodedSlug).not.toBe(specialSlug);

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const adminDataset = {
        dataset_slug: specialSlug,
        title: "Conjunto de Dados São Paulo",
        display_title: "São Paulo Dataset Display",
        summary: "Synthetic non-ASCII slug dataset",
        domain: "retail",
        tags: ["retail"],
        active_release: "release-20260701-001",
        publication_status: "ready",
      };
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [adminDataset] });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [{ ...adminDataset, visibility: "public" }],
        });
      }
      if (url.endsWith(`/admin/datasets/${encodedSlug}/publication-state`)) {
        return jsonResponse({
          dataset_slug: specialSlug,
          active_release: "release-20260701-001",
          visibility: {
            configured_visible: true,
            source: "explicit_record",
            record_status: "valid",
            updated_at: "2026-07-01T00:00:00Z",
            effective_visible: true,
          },
          review: { status: "ready", approval_allowed: false, approval_blockers: [] },
          snapshot: {
            status: "current_release",
            exists: true,
            published_at: "2026-07-01T00:00:00Z",
            active_release_at_publish_time: "release-20260701-001",
            matches_active_release: true,
          },
          public_access: { reachable: true, blockers: [], observations: [] },
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).toHaveBeenCalledWith(`/dataset/${encodedSlug}`, "_blank", "noopener,noreferrer");
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

  it("hydrates Metadata & Card from the published snapshot ahead of a stale profile draft and tracks every owned field as dirty (Project Spec S0077)", async () => {
    const publishedProfile = {
      ...publicProfile,
      home_card: {
        icon: "weather-cloud",
        background_image_ref: "/media/home-cards/0123456789abcdef0123456789abcdef.png",
        short_description: "Latest published card copy",
        primary_metric_key: "balanced_accuracy",
      },
      performance_focus: {
        focus_id: "balanced_classification",
        highlighted_score_id: "balanced_accuracy",
        visible_scores: [
          { score_id: "balanced_accuracy", display_label: "Balanced Accuracy", value: "0.91", value_source: "manual", order: 0 },
          { score_id: "mcc", display_label: "MCC", value: "0.72", value_source: "manual", order: 1 },
        ],
      },
    } as typeof publicProfile;
    installFetchMock({ publishedSnapshotProfile: publishedProfile });
    renderAdminPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Metadata & Card" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Weather cloud" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button", { name: "Remove image" })).toBeInTheDocument();
    expect(screen.getByLabelText("Home card description")).toHaveValue("Latest published card copy");
    expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification");
    expect(screen.getByLabelText("Balanced Accuracy value")).toHaveValue("0.91");

    const publishButton = within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" }))
      .getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Chart line" }));
    expect(publishButton).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Weather cloud" }));
    expect(publishButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Home card description"), { target: { value: "Edited copy" } });
    expect(publishButton).toBeEnabled();
  });

  it("uses a clean baseline when the backend rejects same-slug profile state for the current release (Project Spec S0084)", async () => {
    installFetchMock({ freshPromotionHydration: true });
    renderAdminPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Metadata & Card" }));
    await waitFor(() => expect(screen.getByLabelText("Home card description")).toHaveValue(""));
    expect(screen.queryByRole("button", { name: "Remove image" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Telecom users" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("Performance focus")).toHaveValue("positive_class_detection");
  });

  it("renders Release date label as a normalized date input seeded from Dashboard Last updated (Project Spec S0064)", async () => {
    installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "auto", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-06-21"));
    expect(input).toHaveAttribute("type", "date");
    expect(within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", { name: "Publish changes" })).toBeDisabled();
  });

  it("uses the shared local calendar projection and keeps date-only editorial values stable (Project Spec S0092)", async () => {
    vi.stubEnv("TZ", "America/Recife");
    installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "auto", lastUpdated: "2026-07-13T00:41:21Z" });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Release date label")).toHaveValue("2026-07-12"));
    expect(
      presentDatasetOperationalTimestamp("2026-07-13T00:41:21Z", { timeZone: "America/Recife" })?.localCalendarDate,
    ).toBe("2026-07-12");
    expect(normalizeDatasetDateOnly("2026-07-12")).toBe("2026-07-12");
    expect(normalizeDatasetDateOnly("2026-02-30")).toBe("");
  });

  it("ignores a legacy manual mode and publishes the canonical date without override metadata (Project Spec S0093)", async () => {
    const fetchMock = installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "manual", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-06-21"));
    await screen.findByTestId("dataset-admin-draft-ready");
    expect(screen.queryByText(/Editorial override/)).not.toBeInTheDocument();
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
    expect(body.display).toMatchObject({ release_date_label: "2026-05-12" });
    expect(body.display).not.toHaveProperty("release_date_mode");
    expect(body).not.toHaveProperty("dataset_detail_updated_at");
    expect(body.dataset_detail_time_zone).toEqual(expect.any(String));
  });

  it("refetches the canonical projection after a release-date mutation (Project Spec S0093)", async () => {
    vi.stubEnv("TZ", "America/Recife");
    installFetchMock({
      releaseDate: "2026-05-01",
      releaseDateMode: "auto",
      lastUpdated: "2026-07-13T00:41:21Z",
    });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-07-12"));
    fireEvent.change(input, { target: { value: "2026-07-10" } });
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    );
    await waitFor(() => expect(input).toHaveValue("2026-07-10"));
    expect(screen.queryByText(/Editorial override/)).not.toBeInTheDocument();
  });

  it("keeps a cleared date as an invalid pending edit instead of inventing a browser timestamp (Project Spec S0093)", async () => {
    installFetchMock({ releaseDate: "2026-05-01", releaseDateMode: "manual", lastUpdated: "2026-06-21T23:15:00Z" });
    renderAdminPage();

    const input = await screen.findByLabelText("Release date label");
    await waitFor(() => expect(input).toHaveValue("2026-06-21"));
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue("");
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
  });

  it("surfaces a safe error message from the workspace toolbar when publishing Public Content changes fails, without exposing raw internals (Project Spec S0061)", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Toolbar-edited subtitle" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));

    // Project Spec S0110: the shared fixture profile carries a legacy
    // result_card.submit_button_label with no equivalent customization
    // value yet, so this otherwise-unrelated Subtitle-only publish also
    // carries a pending legacy migration -- the Inference Form
    // customization persists successfully first, then the Public Content
    // profile publish itself fails, producing the combined-outcome message
    // rather than the profile-only failure text.
    expect(
      await screen.findByText("Inference Form saved; Dataset Detail publication failed."),
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
    // The shared publicProfile fixture never publishes documentation, so the
    // blank initial state shows the editor -- merely viewing the tab must
    // never itself persist anything.
    expect(screen.getByLabelText("Documentation Markdown")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method && init.method !== "GET")).toHaveLength(mutationCallsBefore);
  });

  // Project Spec S0196: the Admin Documentation tab's Save/Edit Markdown
  // authoring workflow -- a committed workspace value (ProfileDraft.
  // documentation) separate from a transient, local editing buffer.
  //
  // Project Spec S0202: adds a second Save/Edit action in the Documentation
  // heading row that invokes the exact same handleSave/handleEdit as the
  // original lower action; both action locations are exercised below.
  describe("Documentation Markdown authoring (Project Spec S0196)", () => {
    function openDocumentationTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Documentation" }));
    }

    function documentationHeader() {
      return document.querySelector(".dataset-admin-documentation-header") as HTMLElement;
    }

    function documentationFooter() {
      return document.querySelector(".dataset-admin-documentation-actions") as HTMLElement;
    }

    it("shows the Documentation title, no instructional paragraph, and two Save controls (header + lower action area) when no documentation has been committed yet -- no Edit control is present (Project Spec S0202)", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      expect(screen.getByRole("heading", { name: "Documentation" })).toBeInTheDocument();
      expect(screen.queryByText(/Author Markdown documentation for this Dataset Detail/)).not.toBeInTheDocument();
      expect(screen.getByLabelText("Documentation Markdown")).toHaveValue("");

      expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2);
      expect(within(documentationHeader()).getByRole("button", { name: "Save" })).toBeInTheDocument();
      expect(within(documentationFooter()).getByRole("button", { name: "Save" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    });

    it("keeps typed content in the editor buffer only -- Live Preview still shows the bounded empty state until Save", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: "# Unsaved heading" },
      });

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      const detailTabs = within(screen.getByRole("tablist", { name: "Dataset detail sections" }));
      fireEvent.click(detailTabs.getByRole("tab", { name: "Documentation" }));

      expect(screen.queryByRole("heading", { name: "Unsaved heading" })).not.toBeInTheDocument();
      expect(screen.getByText("No documentation has been published yet.")).toBeInTheDocument();
    });

    it("Save from the header: commits the buffer, hides the textarea, renders the preview, flips both actions to Edit, and never calls the publish endpoint (Project Spec S0202)", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      const textarea = screen.getByLabelText("Documentation Markdown");
      fireEvent.change(textarea, { target: { value: "# First heading\n\nFirst body." } });

      const callsBeforeSave = fetchMock.mock.calls.length;
      fireEvent.click(within(documentationHeader()).getByRole("button", { name: "Save" }));

      expect(screen.queryByLabelText("Documentation Markdown")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "First heading" })).toBeInTheDocument();
      expect(screen.getByText("First body.")).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

      expect(
        fetchMock.mock.calls
          .slice(callsBeforeSave)
          .some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
      ).toBe(false);
    });

    it("Save from the lower action area: preserves the original S0196 round trip -- commits the buffer, flips to Edit, and a second Save updates the preview", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      const textarea = screen.getByLabelText("Documentation Markdown");
      fireEvent.change(textarea, { target: { value: "# First heading\n\nFirst body." } });
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));

      expect(screen.queryByLabelText("Documentation Markdown")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "First heading" })).toBeInTheDocument();
      expect(screen.getByText("First body.")).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Edit" }));
      const reopenedTextarea = screen.getByLabelText("Documentation Markdown") as HTMLTextAreaElement;
      expect(reopenedTextarea).toHaveValue("# First heading\n\nFirst body.");
      expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2);

      fireEvent.change(reopenedTextarea, { target: { value: "# Second heading\n\nSecond body." } });
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));

      expect(screen.getByRole("heading", { name: "Second heading" })).toBeInTheDocument();
      expect(screen.getByText("Second body.")).toBeInTheDocument();
      expect(screen.queryByText("First body.")).not.toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    it("both the header and lower Edit controls restore the exact committed Markdown source and return to the same edit-mode state (Project Spec S0202)", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      const committedMarkdown = "# Committed heading\n\nCommitted body.";

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), { target: { value: committedMarkdown } });
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);

      fireEvent.click(within(documentationHeader()).getByRole("button", { name: "Edit" }));
      expect(screen.getByLabelText("Documentation Markdown")).toHaveValue(committedMarkdown);
      expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2);

      // Re-save the unmodified buffer to return to preview mode, then prove
      // the lower Edit control restores the exact same committed source and
      // lands in the exact same observable edit-mode state as the header one.
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Edit" }));
      expect(screen.getByLabelText("Documentation Markdown")).toHaveValue(committedMarkdown);
      expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2);
    });

    it("Save alone never calls the publish endpoint -- Publish changes remains the sole publication action", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: "Body only." },
      });
      const callsBeforeSave = fetchMock.mock.calls.length;
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));

      expect(
        fetchMock.mock.calls
          .slice(callsBeforeSave)
          .some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
      ).toBe(false);

      const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
      expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeEnabled();
    });

    it("participates in the workspace dirty-state and is carried in the Publish changes payload", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
      await waitFor(() => expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled());

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: "# Published body\n\nCarried in the payload." },
      });
      fireEvent.click(within(documentationFooter()).getByRole("button", { name: "Save" }));

      expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeEnabled();

      const callsBeforePublish = fetchMock.mock.calls.length;
      fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
      await waitFor(() => expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled());

      const publishCall = fetchMock.mock.calls
        .slice(callsBeforePublish)
        .find(
          (call: unknown[]) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        );
      expect(publishCall).toBeDefined();
      const body = JSON.parse(String((publishCall?.[1] as RequestInit).body)) as {
        documentation?: { format?: string; content?: string };
      };
      expect(body.documentation).toEqual({
        format: "markdown",
        content: "# Published body\n\nCarried in the payload.",
      });
    });

    it("feeds Live Preview with the saved documentation, never the unsaved buffer", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: "# Live preview body" },
      });
      fireEvent.click(within(documentationHeader()).getByRole("button", { name: "Save" }));

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      const detailTabs = within(screen.getByRole("tablist", { name: "Dataset detail sections" }));
      fireEvent.click(detailTabs.getByRole("tab", { name: "Documentation" }));

      expect(screen.getByRole("heading", { name: "Live preview body" })).toBeInTheDocument();
    });

    it("restores committed documentation from backend draft hydration, and a dataset switch never leaks the prior dataset's unsaved buffer", async () => {
      const otherSlug = "energy-consumption-forecast";

      function minimalAuthoringContext(slug: string, title: string) {
        return jsonResponse({
          dataset_slug: slug,
          active_release: "release-20260701-001",
          dataset: { status: "ready", data: { dataset_slug: slug, title, summary: "s", domain: "d", tags: [] } },
          context: { status: "ready", data: {} },
          contract: {
            status: "ready",
            data: { contract: { schema_version: "1.0.0", features: [] }, result_contract: { status: "unavailable" } },
          },
          metrics: { status: "ready", data: {} },
          visualizations: { status: "ready", data: {} },
          views: { status: "ready", data: [] },
        });
      }

      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: datasetSlug,
                title: "Telco Customer Churn",
                display_title: "Telco Customer Churn",
                summary: "s",
                domain: "telecom",
                tags: [],
                active_release: "release-20260619-001",
                publication_status: "ready",
                last_updated: "2026-06-19T12:00:00Z",
              },
              {
                dataset_slug: otherSlug,
                title: "Energy Consumption Forecast",
                display_title: "Energy Consumption Forecast",
                summary: "s",
                domain: "energy",
                tags: [],
                active_release: "release-20260701-001",
                publication_status: "ready",
                last_updated: "2026-07-01T12:00:00Z",
              },
            ],
          });
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({
            datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
          });
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
          return minimalAuthoringContext(datasetSlug, "Telco Customer Churn");
        }
        if (url.endsWith(`/admin/datasets/${otherSlug}/authoring-context`)) {
          return minimalAuthoringContext(otherSlug, "Energy Consumption Forecast");
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`)) {
          return jsonResponse({
            draft_exists: true,
            profile: {
              schema_version: "1.0.0",
              dataset_slug: datasetSlug,
              documentation: { format: "markdown", content: "# Telco hydrated documentation" },
            },
          });
        }
        if (url.endsWith(`/admin/datasets/${otherSlug}/profile-draft`)) {
          return jsonResponse({ draft_exists: false, profile: null });
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`) || url.endsWith(`/admin/datasets/${otherSlug}/publication-state`)) {
          return jsonResponse({}, 404);
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);

      renderAdminPage();

      const selector = await screen.findByRole("button", { name: "Dataset" });
      await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

      openDocumentationTab();
      // Published draft hydration restores documentation into the preview,
      // not the blank editor state.
      expect(await screen.findByRole("heading", { name: "Telco hydrated documentation" })).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);

      fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: "# Unsaved edit never persisted" },
      });

      fireEvent.click(selector);
      fireEvent.click(screen.getByRole("option", { name: "Energy Consumption Forecast" }));
      await waitFor(() => expect(selector).toHaveTextContent("Energy Consumption Forecast"));

      openDocumentationTab();
      // The other dataset has no documentation and no unsaved buffer leaked
      // in from the previously selected dataset.
      expect(screen.getByLabelText("Documentation Markdown")).toHaveValue("");
      expect(screen.queryByText("Unsaved edit never persisted")).not.toBeInTheDocument();

      fireEvent.click(selector);
      fireEvent.click(screen.getByRole("option", { name: "Telco Customer Churn" }));
      await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

      openDocumentationTab();
      // Switching back reloads Telco's own committed documentation, not the
      // discarded in-progress edit from before the switch away.
      expect(await screen.findByRole("heading", { name: "Telco hydrated documentation" })).toBeInTheDocument();
      expect(screen.queryByText("Unsaved edit never persisted")).not.toBeInTheDocument();
    });

    it("survives a successful Publish changes round trip: preview stays populated, Edit restores the exact source, and Publish changes disables again until another change (Project Spec S0198)", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
      const publishedMarkdown = "# S0198 published heading\n\nS0198 published body.";

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: publishedMarkdown },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
      expect(screen.getByRole("heading", { name: "S0198 published heading" })).toBeInTheDocument();

      expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeEnabled();
      fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
      await waitFor(() => expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled());

      // The successfully published documentation remains visible -- the
      // textarea/preview must not go blank after a successful publish.
      expect(screen.getByRole("heading", { name: "S0198 published heading" })).toBeInTheDocument();
      expect(screen.getByText("S0198 published body.")).toBeInTheDocument();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
      const reopenedTextarea = screen.getByLabelText("Documentation Markdown") as HTMLTextAreaElement;
      expect(reopenedTextarea).toHaveValue(publishedMarkdown);

      // The successfully published profile is now the dirty-state baseline:
      // re-saving the identical, unmodified content leaves Publish changes
      // disabled until a real edit occurs.
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
      expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();

      fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: `${publishedMarkdown}\n\nOne more paragraph.` },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
      expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeEnabled();
    });
  });

  // Project Spec S0199: local Documentation image upload/storage (S0197) is
  // retired. Authors reference externally hosted raw.githubusercontent.com
  // images directly in the Markdown source; Admin/Live Preview both render
  // them through the shared DatasetDocumentation external-image policy, and
  // no Documentation-image upload fetch is ever issued.
  describe("Documentation external GitHub image authoring (Project Spec S0199)", () => {
    const allowedImageSrc =
      "https://raw.githubusercontent.com/FabioAguiar/dataset-study-telco-customer-churn/main/docs/images/chart.png";
    const arbitraryHostImageSrc = "https://example.org/chart.png";

    function openDocumentationTab() {
      const adminTabs = within(screen.getByRole("tablist", { name: "Dataset admin tabs" }));
      fireEvent.click(adminTabs.getByRole("tab", { name: "Documentation" }));
    }

    function openLivePreviewDocumentationTab() {
      const adminTabs = within(screen.getByRole("tablist", { name: "Dataset admin tabs" }));
      fireEvent.click(adminTabs.getByRole("tab", { name: "Live Preview" }));
      const detailTabs = within(screen.getByRole("tablist", { name: "Dataset detail sections" }));
      fireEvent.click(detailTabs.getByRole("tab", { name: "Documentation" }));
    }

    it("shows no Add image control and no Documentation image file input in edit mode", async () => {
      installFetchMock();
      const { container } = renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      expect(screen.queryByText("Add image")).not.toBeInTheDocument();
      expect(container.querySelector(".dataset-admin-documentation-toolbar")).toBeNull();
      expect(container.querySelector(".dataset-admin-documentation-add-image")).toBeNull();
      expect(container.querySelectorAll('input[type="file"]')).toHaveLength(0);
    });

    it("saving Markdown with an allowed raw.githubusercontent.com image renders it in the Documentation preview", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: `# Docs\n\n![Chart](${allowedImageSrc})` },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

      const img = screen.getByRole("img", { name: "Chart" });
      expect(img).toHaveAttribute("src", allowedImageSrc);
    });

    it("Live Preview uses the same saved Markdown and renders the same allowed image", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: `# Docs\n\n![Chart](${allowedImageSrc})` },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

      openLivePreviewDocumentationTab();
      const img = screen.getByRole("img", { name: "Chart" });
      expect(img).toHaveAttribute("src", allowedImageSrc);
    });

    it("an arbitrary external image host remains absent from Documentation rendering", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: `# Docs\n\n![Chart](${arbitraryHostImageSrc})` },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

      expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
      expect(screen.queryByRole("img", { name: "Chart" })).not.toBeInTheDocument();
    });

    it("never mocks or calls the retired Documentation image upload endpoint", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      openDocumentationTab();
      fireEvent.change(screen.getByLabelText("Documentation Markdown"), {
        target: { value: `# Docs\n\n![Chart](${allowedImageSrc})` },
      });
      fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith(`/admin/datasets/${datasetSlug}/documentation-image`)),
      ).toBe(false);
    });

    it("leaves Home card upload behavior unchanged", async () => {
      const fetchMock = installFetchMock();
      const { container } = renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(within(screen.getByRole("tablist", { name: "Dataset admin tabs" })).getByRole("tab", { name: "Metadata & Card" }));

      const upload = container.querySelector('input[type="file"]')!;
      fireEvent.change(upload, { target: { files: [new File(["png"], "Home card.png", { type: "image/png" })] } });

      await waitFor(() => expect(container.querySelector(".dataset-admin-preview-card .dataset-card__media")).toBeInTheDocument());
      const uploadCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith(`/admin/datasets/${datasetSlug}/home-card-image`));
      expect(uploadCall).toBeDefined();
    });
  });

  it("surfaces publish validation feedback from the workspace toolbar without changing the visibility switch (Project Spec S0116)", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Toolbar-edited subtitle" } });
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    );
    expect(
      await screen.findByText("Inference Form saved; Dataset Detail publication failed."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());
  });

  it("surfaces a safe visibility validation error and keeps the switch checked when the write is rejected (Project Spec S0116)", async () => {
    installFetchMock({ rejectVisibility: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Curated churn profile");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());

    fireEvent.click(switchInput);

    await waitFor(() => expect(switchInput).toBeChecked());
    expect(switchInput).not.toBeDisabled();
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("Configured visibility could not be saved. The previous confirmed value remains active.", {
        exact: false,
      }),
    ).toBeInTheDocument();
    // No raw backend error code is ever shown.
    expect(screen.queryByText(/PROFILE_VISIBILITY_PAYLOAD_INVALID/)).not.toBeInTheDocument();
  });

  it("saves a schema-valid profile-draft payload for supported icon, performance focus, theme preset, and result-card values", async () => {
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
      "money-dollar",
      "globe",
      "flask",
      "cpu-chip",
    ];
    const SCHEMA_SUPPORTED_THEME_PRESETS = DATASET_THEME_PRESETS.map((preset) => preset.id);
    const SCHEMA_SUPPORTED_BADGE_PRESETS = ["risk"];

    const fetchMock = installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
    fireEvent.click(screen.getByRole("button", { name: "Chart line" }));
    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "balanced_classification" } });
    fireEvent.change(screen.getByLabelText("Balanced Accuracy value"), { target: { value: "0.81" } });

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.click(screen.getByRole("button", { name: "Cyber Neon" }));

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    fireEvent.change(screen.getByLabelText("Badge preset"), { target: { value: "risk" } });
    fireEvent.change(screen.getByLabelText("High label"), { target: { value: "Severe risk" } });

    // Project Spec S0116 removes the tab-local Save draft action -- the
    // global workspace toolbar's Publish changes button is now the only UI
    // path that sends the accumulated form edits, via the same
    // profileFromForm serialization the old profile-draft PUT used.
    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
          name: "Publish changes",
        }),
      ).toBeDisabled(),
    );

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
    expect(saveCall?.[1]).toMatchObject({
      headers: { "Content-Type": "application/json" },
    });
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      home_card?: { icon?: string; primary_metric_key?: string | null };
      performance_focus?: { focus_id?: string; highlighted_score_id?: string; visible_scores?: Array<{ score_id: string; value: string }> };
      theme?: { preset?: string };
      result_card?: { schema_version?: string; interpretation?: { preset?: string; labels?: { high?: string } } };
    };

    expect(body.home_card?.icon).toBe("chart-line");
    expect(SCHEMA_SUPPORTED_ICONS).toContain(body.home_card?.icon);
    expect(body.performance_focus).toMatchObject({
      focus_id: "balanced_classification",
      highlighted_score_id: "balanced_accuracy",
    });
    expect(body.performance_focus?.visible_scores?.[0]).toMatchObject({ score_id: "balanced_accuracy", value: "0.81" });
    expect(body.theme?.preset).toBe("cyber-neon");
    expect(SCHEMA_SUPPORTED_THEME_PRESETS).toContain(body.theme?.preset);
    expect(body.result_card?.schema_version).toBe("binary-result-presentation.v1");
    expect(SCHEMA_SUPPORTED_BADGE_PRESETS).toContain(body.result_card?.interpretation?.preset);
    expect(body.result_card?.interpretation?.labels?.high).toBe("Severe risk");
  });

  it("renders the exact enabled card-only theme catalog while preserving Result Card locks", async () => {
    installFetchMock();
    renderAdminPage();

    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    const themePanel = screen.getByRole("tabpanel");
    const themeWorkspace = themePanel.querySelector(".dataset-admin-tab-workspace");
    expect(themeWorkspace).toBeInTheDocument();
    expect(themeWorkspace?.querySelector(":scope > .dataset-admin-theme-grid")).toBeInTheDocument();
    expect(themeWorkspace?.querySelector(".dataset-admin-config-card")).not.toBeInTheDocument();
    const themeButtons = within(themePanel).getAllByRole("button");
    expect(themeButtons).toHaveLength(30);
    expect(themeButtons.map((button) => button.textContent)).toEqual(
      DATASET_THEME_PRESETS.map((preset) => preset.label),
    );
    themeButtons.forEach((button) => {
      expect(button).toBeEnabled();
      expect(button).toHaveAttribute("aria-pressed");
      expect(button).not.toHaveAttribute("aria-disabled");
    });
    expect(within(themePanel).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(themePanel).queryByText("Theme Preset")).not.toBeInTheDocument();
    expect(within(themePanel).queryByText("Selectable schema preset")).not.toBeInTheDocument();
    expect(within(themePanel).queryByText("Locked until schema support exists")).not.toBeInTheDocument();
    expect(within(themePanel).queryByText("Locked")).not.toBeInTheDocument();

    for (const preset of DATASET_THEME_PRESETS) {
      fireEvent.click(within(themePanel).getByRole("button", { name: preset.label }));
      const selected = themeButtons.filter((button) => button.getAttribute("aria-pressed") === "true");
      expect(selected).toHaveLength(1);
      expect(selected[0]).toHaveAccessibleName(preset.label);
    }

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    const badgeSelect = screen.getByLabelText("Badge preset") as HTMLSelectElement;
    const badgeOptionValues = Array.from(badgeSelect.options).map((option) => option.value);
    expect(badgeOptionValues).toEqual(["", "risk"]);
    expect(screen.getByRole("button", { name: /Risk/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Value band/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Severity/ })).toBeDisabled();

  });

  it("tracks Theme Preset selection in the workspace toolbar and publishes it directly", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();
    await loadDraftOnly();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    let atlasGreen = screen.getByRole("button", { name: "Atlas Green" });
    let oceanBlue = screen.getByRole("button", { name: "Ocean Blue" });
    fireEvent.click(oceanBlue);
    expect(oceanBlue).toHaveAttribute("aria-pressed", "true");
    expect(publishButton).toBeEnabled();

    fireEvent.click(atlasGreen);
    expect(publishButton).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Another workspace edit" } });
    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    atlasGreen = screen.getByRole("button", { name: "Atlas Green" });
    oceanBlue = screen.getByRole("button", { name: "Ocean Blue" });
    fireEvent.click(oceanBlue);
    fireEvent.click(atlasGreen);
    expect(publishButton).toBeEnabled();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: publicProfile.display.subtitle } });
    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    oceanBlue = screen.getByRole("button", { name: "Ocean Blue" });
    fireEvent.click(oceanBlue);
    fireEvent.click(publishButton);

    await waitFor(() => expect(publishButton).toBeDisabled());
    expect(oceanBlue).toHaveAttribute("aria-pressed", "true");

    const publishCall = fetchMock.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`),
    );
    const body = JSON.parse(String((publishCall?.[1] as RequestInit).body)) as { theme?: { preset?: string } };
    expect(body.theme?.preset).toBe("ocean-blue");
    expect(
      fetchMock.mock.calls.find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      ),
    ).toBeUndefined();
  });

  it("keeps a failed Theme Preset publication selected and actionable in the workspace toolbar", async () => {
    installFetchMock({ rejectPublish: true });
    renderAdminPage();
    await loadDraftOnly();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    const oceanBlue = screen.getByRole("button", { name: "Ocean Blue" });
    fireEvent.click(oceanBlue);
    fireEvent.click(publishButton);

    // Project Spec S0110: same pending-legacy-migration combined outcome as
    // the Subtitle-only publish-failure test above.
    await screen.findByText("Inference Form saved; Dataset Detail publication failed.");
    expect(oceanBlue).toHaveAttribute("aria-pressed", "true");
    expect(publishButton).toBeEnabled();
  });

  it.each([
    ["Ocean Blue", "ocean-blue"],
    ["Ice Blue", "ice-blue"],
    ["Monochrome Dark", "monochrome-dark"],
    ["Cyber Neon", "cyber-neon"],
  ])("saves %s through the generic profile.theme.preset payload", async (label, presetId) => {
    const fetchMock = installFetchMock({ trackProfileDraftSaves: true });
    renderAdminPage();
    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.click(screen.getByRole("button", { name: label }));
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled());

    const saveCall = fetchMock.mock.calls.slice(callsBeforeSave).find(
      (call: unknown[]) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as { theme?: { preset?: string } };
    expect(body.theme?.preset).toBe(presetId);
  });

  it("rehydrates a supported saved preset as the single selected card", async () => {
    installFetchMock({ themePresetOverride: "ice-blue" });
    renderAdminPage();
    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    expect(screen.getByRole("button", { name: "Ice Blue" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(1);
  });

  it.each([
    ["missing", { noExistingDraft: true }],
    ["unknown", { themePresetOverride: "custom-rainbow" }],
  ])("falls back an %s profile preset to Atlas Green", async (_case, options) => {
    installFetchMock(options);
    renderAdminPage();
    await loadDraftOnly();

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    expect(screen.getByRole("button", { name: "Atlas Green" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "custom-rainbow" })).not.toBeInTheDocument();
  });

  it("replaces the obsolete image-reference control with a controlled upload tile", async () => {
    installFetchMock();
    const { container } = renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    expect(screen.queryByRole("heading", { name: "Home card controls" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Background image reference")).not.toBeInTheDocument();
    const upload = container.querySelector('input[type="file"]');
    expect(upload).toBeInTheDocument();
    expect(upload).toHaveAttribute("accept", "image/png,image/jpeg,image/webp,image/avif");
    expect(screen.getByText("Upload image")).toBeInTheDocument();
  });

  it("rejects unsupported uploads safely without clearing the selected icon", async () => {
    installFetchMock();
    const { container } = renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const iconButton = screen.getByRole("button", { name: "CPU chip" });
    fireEvent.click(iconButton);
    const upload = container.querySelector('input[type="file"]')!;
    fireEvent.change(upload, { target: { files: [new File(["unsafe"], "card.svg", { type: "image/svg+xml" })] } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a PNG, JPEG, WebP, or AVIF image.");
    expect(iconButton).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector(".dataset-admin-preview-card .dataset-card__icon")).toBeInTheDocument();
  });

  it("uploads ordinary accented filenames without frontend filename or MIME blocking", async () => {
    const fetchMock = installFetchMock();
    const { container } = renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const upload = container.querySelector('input[type="file"]')!;
    fireEvent.change(upload, { target: { files: [new File(["png"], "Visão geral (final).png")] } });

    await waitFor(() => expect(container.querySelector(".dataset-admin-preview-card .dataset-card__media")).toBeInTheDocument());
    const previewCard = container.querySelector(".dataset-admin-preview-card .dataset-card");
    expect(previewCard).toHaveClass("dataset-card--image");
    expect(previewCard?.querySelector(".dataset-card__media-gradient")).toBeInTheDocument();
    expect(previewCard?.querySelector(".dataset-card__frame")).toBeInTheDocument();
    const uploadCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith(`/admin/datasets/${datasetSlug}/home-card-image`));
    expect(uploadCall).toBeDefined();
    expect(uploadCall?.[1]?.headers).toMatchObject({ "X-File-Name": encodeURIComponent("Visão geral (final).png") });
    expect(uploadCall?.[1]?.headers).not.toHaveProperty("Content-Type");
  });

  it("preserves Home card and Performance focus edits when an upload fails", async () => {
    installFetchMock();
    const { container } = renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const iconButton = screen.getByRole("button", { name: "CPU chip" });
    fireEvent.click(iconButton);
    fireEvent.change(screen.getByLabelText("Home card description"), { target: { value: "Unsaved card copy" } });
    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "balanced_classification" } });
    const upload = container.querySelector('input[type="file"]')!;
    fireEvent.change(upload, { target: { files: [new File(["png"], "first image.png", { type: "image/png" })] } });
    await waitFor(() => expect(container.querySelector(".dataset-admin-preview-card .dataset-card__media")).toBeInTheDocument());
    fireEvent.change(upload, { target: { files: [new File(["bad"], "fail image.png", { type: "image/png" })] } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a PNG, JPEG, WebP, or AVIF image.");
    expect(iconButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Home card description")).toHaveValue("Unsaved card copy");
    expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification");
    expect(container.querySelector(".dataset-admin-preview-card .dataset-card__media")).toBeInTheDocument();
    expect(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    ).toBeEnabled();
  });

  it("binds controlled icon and short-description textarea to the local preview", async () => {
    installFetchMock();
    const { container } = renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const iconButton = screen.getByRole("button", { name: "Weather cloud" });
    fireEvent.click(iconButton);
    expect(iconButton).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector(".dataset-admin-preview-card .dataset-card__icon")).toBeInTheDocument();

    const description = screen.getByLabelText("Home card description");
    expect(description.tagName).toBe("TEXTAREA");
    fireEvent.change(description, { target: { value: "Live preview copy" } });
    expect(within(screen.getByText("Home card preview").closest(".dataset-admin-preview-card")!).getByText("Live preview copy", { selector: "p" })).toBeInTheDocument();
    fireEvent.change(description, { target: { value: "" } });
    expect(within(screen.getByText("Home card preview").closest(".dataset-admin-preview-card")!).queryByText("Live preview copy")).not.toBeInTheDocument();
    expect(screen.queryByText("Customer churn prediction dataset")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Short Home card description")).not.toBeInTheDocument();
  });

  it("offers 19 controlled icons and selects every icon in the new final row", async () => {
    installFetchMock();
    const { container } = renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const iconBank = screen.getByRole("group", { name: "Home card icon" });
    const iconButtons = within(iconBank).getAllByRole("button");
    expect(iconButtons).toHaveLength(19);
    expect(iconButtons.map((button) => button.textContent)).toEqual([
      "Telecom users", "Bank building", "Chart line", "Heart", "Shopping cart",
      "Airplane", "Shield", "Education cap", "Energy bolt", "Home house",
      "Agro leaf", "Logistics truck", "Factory", "Weather cloud", "Database",
      "Money dollar", "Globe", "Flask", "CPU chip",
    ]);
    expect(iconButtons.every((button) => !button.textContent?.includes("-"))).toBe(true);

    for (const label of ["Money dollar", "Globe", "Flask", "CPU chip"]) {
      const button = within(iconBank).getByRole("button", { name: label });
      fireEvent.click(button);
      expect(button).toHaveAttribute("aria-pressed", "true");
      expect(container.querySelector(".dataset-admin-preview-card .dataset-card__icon svg")).toBeInTheDocument();
    }

    expect(
      within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
        name: "Publish changes",
      }),
    ).toBeEnabled();
  });

  it("renders the tightened Metadata & Card copy and English public-card labels", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    expect(screen.queryByText("Editable Home card fields store references and presentation copy only.")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Metadata & Card" })).not.toBeInTheDocument();
    expect(screen.queryByText("Icon bank")).not.toBeInTheDocument();
    expect(screen.queryByText("Select a controlled icon for the public Home card.")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Home card icon" })).not.toBeInTheDocument();
    expect(screen.queryByText("Uses the same shared card projection as Live Preview.")).not.toBeInTheDocument();
    expect(screen.getAllByText("Binary Classification")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Explore dataset/ })).toBeInTheDocument();
    expect(screen.queryByText("Explorar dataset")).not.toBeInTheDocument();
    expect(screen.queryByText("The focus controls the bounded score catalog below.")).not.toBeInTheDocument();
    expect(screen.queryByText(/Unchecked values stay in this edit session/)).not.toBeInTheDocument();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  it("renders problem type as one read-only release-governed value beside the Home card preview", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    expect(screen.getByRole("heading", { name: "Home card preview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Home card description")).toBeInTheDocument();
    expect(screen.queryByLabelText("Short Home card description")).not.toBeInTheDocument();

    const problemTypeDisplay = screen.getByLabelText("Problem type display");
    expect(within(problemTypeDisplay).queryByRole("radio")).not.toBeInTheDocument();

    const previewCard = screen.getByRole("heading", { name: "Home card preview" }).closest<HTMLElement>(".dataset-admin-preview-card")!;
    expect(within(previewCard).getByText("Binary Classification")).toBeInTheDocument();
    expect(within(previewCard).queryByText("Predictive Analysis")).not.toBeInTheDocument();
    expect(within(problemTypeDisplay).getByText("Binary Classification")).toBeInTheDocument();
    expect(within(problemTypeDisplay).getByText("Release-governed")).toBeInTheDocument();
    expect(within(problemTypeDisplay).queryByText("Regression")).not.toBeInTheDocument();
  });

  // Project Spec S0204: the same draft Performance focus selection projects
  // into all three preview surfaces (Metadata & Card Home card preview,
  // Live Preview Home Card, Live Preview Dataset Detail header) without
  // requiring Publish changes, alongside the unchanged problem-type badge.
  describe("Performance focus badge across preview surfaces (Project Spec S0204)", () => {
    it("renders the selected Performance focus badge in the Metadata & Card Home card preview, alongside the problem-type badge", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      const previewCard = screen.getByRole("heading", { name: "Home card preview" }).closest<HTMLElement>(".dataset-admin-preview-card")!;
      expect(within(previewCard).getByText("Binary Classification")).toBeInTheDocument();
      expect(within(previewCard).getByText("Positive-class detection")).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "balanced_classification" } });
      expect(within(previewCard).getByText("Balanced classification")).toBeInTheDocument();
      expect(within(previewCard).queryByText("Positive-class detection")).not.toBeInTheDocument();
      expect(within(previewCard).getByText("Binary Classification")).toBeInTheDocument();
    });

    it("renders the selected Performance focus badge in Live Preview's Home Card", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
      fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "balanced_classification" } });

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(screen.getByRole("tab", { name: "Home Card" }));

      const homeCardPanel = screen.getByRole("article", { name: "Home Card preview" });
      expect(within(homeCardPanel).getByText("Balanced classification")).toBeInTheDocument();
      expect(within(homeCardPanel).getByText("Binary Classification")).toBeInTheDocument();
    });

    it("renders the selected Performance focus badge in Live Preview's Dataset Detail header", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
      fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "balanced_classification" } });

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      expect(screen.getByRole("tab", { name: "Dataset Detail", selected: true })).toBeInTheDocument();

      const headerBadges = document.querySelector(".dataset-detail-header__badges") as HTMLElement;
      expect(within(headerBadges).getByText("Balanced classification")).toBeInTheDocument();
    });

    it("updates all three preview surfaces immediately when Performance focus changes, without requiring Publish changes", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "probability_quality" } });

      const metadataPreviewCard = screen.getByRole("heading", { name: "Home card preview" }).closest<HTMLElement>(".dataset-admin-preview-card")!;
      expect(within(metadataPreviewCard).getByText("Probability quality")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(screen.getByRole("tab", { name: "Home Card" }));
      expect(within(screen.getByRole("article", { name: "Home Card preview" })).getByText("Probability quality")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Dataset Detail" }));
      const headerBadges = document.querySelector(".dataset-detail-header__badges") as HTMLElement;
      expect(within(headerBadges).getByText("Probability quality")).toBeInTheDocument();

      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        ),
      ).toBe(false);
    });
  });

  // Project Spec S0215: multiclass Performance focus authoring must never
  // default to or offer positive_class_detection, and must filter the
  // selectable score catalog to the multiclass-compatible subset.
  describe("multiclass Performance focus authoring (Project Spec S0215)", () => {
    const multiclassResultContract = {
      status: "available",
      semantics: {
        schema_version: "multiclass-result-semantics.v1",
        problem_type: "multiclass_classification",
        result_schema_version: "multiclass-classification-result.v1",
        primary_output: "predicted_class",
        probability_output: "class_probabilities",
        classes: [
          { class_id: "class-a", display_label: "Class A" },
          { class_id: "class-b", display_label: "Class B" },
          { class_id: "class-c", display_label: "Class C" },
        ],
        decision: { strategy: "argmax" },
        model_descriptor: { model_family: "model", display_name: "Model" },
      },
    };

    it("defaults to balanced_classification, not positive_class_detection, for a multiclass release", async () => {
      installFetchMock({ resultContractOverride: multiclassResultContract });
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification"));
    });

    it("does not offer overall_discrimination, positive_class_detection, or operational_decision in the selector for a multiclass release", async () => {
      installFetchMock({ resultContractOverride: multiclassResultContract });
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      const select = await screen.findByLabelText("Performance focus");
      await waitFor(() => expect(select).toHaveValue("balanced_classification"));
      const optionLabels = within(select)
        .getAllByRole("option")
        .map((option) => option.textContent);
      expect(optionLabels).toEqual(["Balanced classification", "Probability quality"]);
      expect(optionLabels).not.toContain("Positive-class detection");
      expect(optionLabels).not.toContain("Overall discrimination");
      expect(optionLabels).not.toContain("Operational decision");
    });

    it("only shows multiclass-applicable scores for balanced_classification, never f1_score/recall/etc.", async () => {
      installFetchMock({ resultContractOverride: multiclassResultContract });
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification"));
      expect(screen.getByLabelText("Show Balanced Accuracy")).toBeInTheDocument();
      expect(screen.getByLabelText("Show F1 Macro")).toBeInTheDocument();
      expect(screen.getByLabelText("Show F1 Weighted")).toBeInTheDocument();
      expect(screen.getByLabelText("Show Precision Macro")).toBeInTheDocument();
      expect(screen.getByLabelText("Show Recall Macro")).toBeInTheDocument();
      expect(screen.getByLabelText("Show Accuracy")).toBeInTheDocument();
      expect(screen.queryByLabelText("Show F1-score")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show Recall")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show Specificity")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show Cohen's Kappa")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show G-Mean")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show MCC")).not.toBeInTheDocument();
    });

    it("only shows log_loss for probability_quality when switched to for a multiclass release", async () => {
      installFetchMock({ resultContractOverride: multiclassResultContract });
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification"));
      fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "probability_quality" } });

      expect(screen.getByLabelText("Show Log Loss")).toBeInTheDocument();
      expect(screen.queryByLabelText("Show Brier Score")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Show Calibration Error")).not.toBeInTheDocument();
    });

    it("preserves the full binary catalog and default when the release is binary", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();
      fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

      expect(screen.getByLabelText("Performance focus")).toHaveValue("positive_class_detection");
      const optionLabels = within(screen.getByLabelText("Performance focus"))
        .getAllByRole("option")
        .map((option) => option.textContent);
      expect(optionLabels).toEqual([
        "Overall discrimination",
        "Positive-class detection",
        "Balanced classification",
        "Probability quality",
        "Operational decision",
      ]);
      expect(screen.getByLabelText("Show F1-score")).toBeInTheDocument();
    });
  });

  // Project Spec S0228: Dataset Detail Live Preview gates RegressionDiagnostics
  // from the same private, dataset-bound result-contract authority as
  // Performance Summary, and reuses the exact same shared renderer/already-
  // loaded visualizations payload the public route consumes -- no
  // synthesized diagnostics from draft form data, and no additional request.
  describe("Dataset Detail Live Preview continuous-regression diagnostics (Project Spec S0228)", () => {
    const regressionResultContract = {
      status: "available",
      semantics: {
        schema_version: "continuous-regression-result-semantics.v1",
        problem_type: "continuous_regression",
        result_schema_version: "continuous-regression-result.v1",
        primary_output: "predicted_value",
        output_value_kind: "continuous_numeric",
        model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
      },
    };

    const regressionVisualizations = {
      charts: [
        {
          id: "target_distribution", title: "Target Distribution", type: "bar" as const,
          x_label: "Strength", y_label: "Rows",
          data: [
            { name: "10 to 20", value: 6 },
            { name: "20 to 30", value: 4 },
          ],
        },
        {
          id: "feature_importance", title: "Feature Importance", type: "bar" as const,
          x_label: "Feature", y_label: "Importance",
          data: [
            { name: "cement", value: 0.6 },
            { name: "water", value: 0.4 },
          ],
        },
      ],
      dataset_statistics: { instance_count: 10 },
      target_distribution_kind: "continuous_histogram",
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

    it("renders Actual vs Predicted and Residual Distribution for a continuous-regression release", async () => {
      installFetchMock({
        resultContractOverride: regressionResultContract,
        visualizationsOverride: regressionVisualizations,
      });
      const { container } = renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      expect(await screen.findByRole("heading", { name: "Actual vs Predicted" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Residual Distribution" })).toBeInTheDocument();

      const overviewPanel = container.querySelector(".dataset-detail-tabs__panel:not([hidden])")!;
      expect(overviewPanel.querySelector(".dataset-detail-overview__regression-diagnostics")).toBeInTheDocument();
      expect(screen.getByText("Actual 15.5 vs Predicted 16.1")).toBeInTheDocument();
      expect(screen.getByText("n=6")).toBeInTheDocument();
      expect(screen.getByText("-2 to 0")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Confusion Matrix" })).not.toBeInTheDocument();
    });

    it("renders continuous Target Distribution as a histogram, not the classification donut, in Live Preview", async () => {
      installFetchMock({
        resultContractOverride: regressionResultContract,
        visualizationsOverride: regressionVisualizations,
      });
      const { container } = renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      const targetDistributionHeading = await screen.findByRole("heading", { name: "Target Distribution" });
      expect(targetDistributionHeading.closest(".atlas-card")).toHaveClass("dataset-detail-visualization--histogram");
      expect(container.querySelector(".dataset-detail-visualization--donut")).not.toBeInTheDocument();
    });

    it("renders no regression diagnostics for the default binary release", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      await screen.findByRole("heading", { name: "Target Distribution" });
      expect(screen.queryByRole("heading", { name: "Actual vs Predicted" })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Residual Distribution" })).not.toBeInTheDocument();
    });

    it("renders no regression diagnostics for a multiclass release, and does not synthesize diagnostics from draft form data", async () => {
      const multiclassResultContract = {
        status: "available",
        semantics: {
          schema_version: "multiclass-result-semantics.v1",
          problem_type: "multiclass_classification",
          result_schema_version: "multiclass-classification-result.v1",
          primary_output: "predicted_class",
          probability_output: "class_probabilities",
          classes: [
            { class_id: "class-a", display_label: "Class A" },
            { class_id: "class-b", display_label: "Class B" },
            { class_id: "class-c", display_label: "Class C" },
          ],
          decision: { strategy: "argmax" },
          model_descriptor: { model_family: "model", display_name: "Model" },
        },
      };
      installFetchMock({ resultContractOverride: multiclassResultContract });
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      await screen.findByRole("heading", { name: "Target Distribution" });
      expect(screen.queryByRole("heading", { name: "Actual vs Predicted" })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Residual Distribution" })).not.toBeInTheDocument();
    });

    it("does not issue an additional request for Live Preview regression diagnostics", async () => {
      const fetchMock = installFetchMock({
        resultContractOverride: regressionResultContract,
        visualizationsOverride: regressionVisualizations,
      });
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      await screen.findByRole("heading", { name: "Actual vs Predicted" });

      const authoringContextCalls = fetchMock.mock.calls.filter((call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/authoring-context`),
      );
      expect(authoringContextCalls.length).toBe(1);
    });
  });

  // Project Spec S0229: continuous-regression Result Card authoring --
  // release-derived family (never operator-selectable), read-only technical
  // summary, editable fields limited to predicted-value label/decimal
  // places/unit label/model-section label, Value band remains locked, the
  // illustrative preview executes no inference and persists no synthetic
  // sample, and the real Live Preview InferenceForm accepts/renders a real
  // continuous-regression inference result.
  describe("Dataset Admin continuous-regression Result Card authoring and Live Preview (Project Spec S0229)", () => {
    const regressionResultContract = {
      status: "available",
      semantics: {
        schema_version: "continuous-regression-result-semantics.v1",
        problem_type: "continuous_regression",
        result_schema_version: "continuous-regression-result.v1",
        primary_output: "predicted_value",
        output_value_kind: "continuous_numeric",
        model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
      },
    };

    it("shows the read-only technical summary, limits editable fields, and keeps Value band locked", async () => {
      installFetchMock({ resultContractOverride: regressionResultContract });
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));

      expect(screen.getByText("continuous_regression")).toBeInTheDocument();
      expect(screen.getByText("predicted_value")).toBeInTheDocument();
      expect(screen.getByText("continuous_numeric")).toBeInTheDocument();
      expect(screen.getByText(/Gradient Boosting Regressor \(gradient_boosting\)/)).toBeInTheDocument();

      expect(screen.getByLabelText("Predicted value label")).toBeInTheDocument();
      expect(screen.getByLabelText("Decimal places")).toBeInTheDocument();
      expect(screen.getByLabelText("Optional unit label")).toBeInTheDocument();
      expect(screen.getByLabelText("Model section label")).toBeInTheDocument();

      // No binary/multiclass editable fields leak into the regression form.
      expect(screen.queryByLabelText("Positive-class probability label")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Predicted class label")).not.toBeInTheDocument();
      // Value band (badge preset) remains unavailable -- no governed band
      // contract exists for continuous_regression, so the preset selector
      // never renders at all (never shown as a clickable-but-locked option).
      expect(screen.queryByLabelText("Badge preset")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Value band/ })).not.toBeInTheDocument();
    });

    it("round-trips exactly the continuous-regression presentation on Publish changes, with no hybrid keys", async () => {
      const fetchMock = installFetchMock({ resultContractOverride: regressionResultContract });
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
      fireEvent.change(screen.getByLabelText("Predicted value label"), { target: { value: "Predicted compressive strength" } });
      fireEvent.change(screen.getByLabelText("Decimal places"), { target: { value: "1" } });
      fireEvent.change(screen.getByLabelText("Optional unit label"), { target: { value: "MPa" } });
      fireEvent.change(screen.getByLabelText("Model section label"), { target: { value: "Model" } });

      const callsBeforeSave = fetchMock.mock.calls.length;
      fireEvent.click(
        within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
          name: "Publish changes",
        }),
      );
      await waitFor(() =>
        expect(
          within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", {
            name: "Publish changes",
          }),
        ).toBeDisabled(),
      );

      const saveCall = fetchMock.mock.calls
        .slice(callsBeforeSave)
        .find(
          (call: unknown[]) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        );
      expect(saveCall).toBeDefined();
      const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
        result_card?: Record<string, unknown>;
      };
      expect(body.result_card).toEqual({
        schema_version: "continuous-regression-result-presentation.v1",
        predicted_value_label: "Predicted compressive strength",
        model_section_label: "Model",
        decimal_places: 1,
        value_unit_label: "MPa",
      });
    });

    it("renders an illustrative preview using the shared renderer, executing no inference request and persisting no sample value", async () => {
      const fetchMock = installFetchMock({ resultContractOverride: regressionResultContract });
      renderAdminPage();
      await loadDraftOnly();

      fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));

      expect(screen.getByText(/Illustrative preview only/)).toBeInTheDocument();
      expect(screen.getByText("42.73")).toBeInTheDocument();
      expect(screen.getByText("Gradient Boosting Regressor")).toBeInTheDocument();

      const inferenceCalls = fetchMock.mock.calls.filter((call) =>
        String(call[0]).includes("/inference"),
      );
      expect(inferenceCalls.length).toBe(0);

      // The illustrative sample predicted_value (42.73) is synthesized only
      // for the preview render -- profileFromForm never carries a
      // predicted_value/predicted_class/positive_class_probability field for
      // any presentation variant (round-tripped explicitly by the sibling
      // "round-trips exactly the continuous-regression presentation" test),
      // so it can never be persisted into the profile.
    });

    it("Live Preview's real InferenceForm accepts and renders a real continuous-regression inference result", async () => {
      installFetchMock({
        resultContractOverride: regressionResultContract,
        adminInferenceResult: {
          schema_version: "continuous-regression-result.v1",
          problem_type: "continuous_regression",
          predicted_value: 55.12,
          model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
        },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(within(await screen.findByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", { name: "Inference" }));
      fireEvent.click(screen.getByRole("button", { name: "Run prediction" }));

      expect(await screen.findByText("55.12")).toBeInTheDocument();
    });
  });

  // Project Spec S0120: Dataset Detail Live Preview now renders the exact
  // shared DatasetDetailSurface (S0119) used by /dataset/:slug -- one
  // instance, its own real three-tab system (Overview/Inference/
  // Documentation, Overview selected initially), no duplicated Admin
  // markup, and no Model Card (dropped entirely from this surface).
  //
  // Project Spec S0145: the shared surface renders directly inside
  // `.dataset-admin-preview-panel--detail`, itself sitting flush against
  // `.dataset-admin-preview-stage`'s inner border via the stage's own
  // `--detail` mode -- no Admin-only frame/page wrapper, and no simulated
  // public navigation rail, menu toggle or nav labels.
  it("renders Live Preview subviews from real public components and the loaded customization", async () => {
    const fetchMock = installFetchMock();
    const { container } = renderAdminPage();

    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    // Level-scoped heading role proves DatasetDetailHeader's real <h1>, not
    // just coincidentally matching text from a divergent mockup.
    expect(screen.getByRole("heading", { level: 1, name: "Curated churn profile" })).toBeInTheDocument();
    // The dedicated draft display_subtitle owns the Dataset Detail subtitle
    // -- the Home Card's own short_description ("Curated home card copy")
    // never leaks into it.
    expect(screen.getByText("Operator-authored public subtitle")).toBeInTheDocument();
    expect(screen.queryByText("Curated home card copy")).not.toBeInTheDocument();

    expect(screen.getByRole("tab", { name: "Dataset Detail", selected: true })).toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-admin-preview-stage")).toHaveLength(1);
    expect(container.querySelector(".dataset-admin-preview-stage")).toHaveClass("dataset-admin-preview-stage--detail");
    expect(container.querySelectorAll(".dataset-admin-preview-panel--detail")).toHaveLength(1);
    expect(container.querySelectorAll(".dataset-detail-surface")).toHaveLength(1);

    // The shared surface is the Dataset Detail panel's only content -- no
    // Admin-only frame/page wrapper, and no simulated public navigation
    // rail, menu toggle or nav labels.
    const detailPanel = container.querySelector(".dataset-admin-preview-panel--detail")!;
    expect(detailPanel.children).toHaveLength(1);
    expect(detailPanel.firstElementChild).toHaveClass("dataset-detail-surface");
    expect(container.querySelector(".dataset-admin-detail-preview-frame")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-admin-detail-preview-page")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-admin-detail-preview-rail")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-admin-detail-preview-menu")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-admin-detail-preview-nav")).not.toBeInTheDocument();
    expect(container.querySelector("aside")).not.toBeInTheDocument();
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(screen.queryByText("Projetos")).not.toBeInTheDocument();
    expect(screen.queryByText("GitHub")).not.toBeInTheDocument();
    expect(screen.queryByText("Contato")).not.toBeInTheDocument();

    // Exactly three internal public tabs, Overview selected by default, and
    // its Problem Summary/analytical slots render from the loaded draft.
    // Scoped to the shared surface's own tablist -- the outer Admin tab bar
    // has an unrelated "Documentation" tab of its own.
    const detailTabs = within(screen.getByRole("tablist", { name: "Dataset detail sections" }));
    expect(detailTabs.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Inference",
      "Documentation",
    ]);
    expect(detailTabs.getByRole("tab", { name: "Overview", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Churn context" })).toBeInTheDocument();
    expect(screen.getByText("Explains customer churn for a public audience.")).toBeInTheDocument();

    // Exactly one Live Preview Dataset Detail panel is effectively visible
    // at a time (Project Spec S0142 acceptance criteria 10/28).
    expect(container.querySelectorAll(".dataset-detail-tabs__panel:not([hidden])")).toHaveLength(1);

    // Project Spec S0138: the Live Preview Overview owns exactly the same
    // four authorized cards as the public route -- Problem Summary,
    // Performance Summary, the donut Target Distribution and the ranked
    // Feature Importance -- and no route-specific CSS/duplicate composition
    // is used to achieve that parity (both routes share DatasetDetailSurface).
    const overviewPanel = container.querySelector(".dataset-detail-tabs__panel:not([hidden])")!;
    expect(overviewPanel.querySelectorAll(".atlas-card")).toHaveLength(4);
    expect(overviewPanel.querySelector(".dataset-detail-overview__problem-summary")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".performance-summary")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".dataset-detail-visualization--donut")).toBeInTheDocument();
    expect(overviewPanel.querySelector(".dataset-detail-visualization--ranked")).toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-detail-visualization")).toHaveLength(2);

    fireEvent.click(detailTabs.getByRole("tab", { name: "Inference" }));
    expect(container.querySelectorAll(".dataset-detail-tabs__panel:not([hidden])")).toHaveLength(1);
    // Project Spec S0143: the functional Live Preview Inference panel is one
    // real, executable InferenceForm lifecycle -- no "Preview only" notice,
    // and the shared Result Card starts at its complete 0% projection
    // instead of the old synthetic scenario-driven preview.
    expect(screen.queryByText(/Preview only — no inference request is executed./)).not.toBeInTheDocument();
    const resultRegion = screen.getByRole("region", { name: "Prediction result" });
    expect(within(resultRegion).getByText("Churn probability")).toBeInTheDocument();
    expect(
      within(resultRegion).getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Account profile")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenure")).toBeInTheDocument();
    // The active release's result contract is available, so submission is
    // enabled as soon as Live Preview loads -- never the previous
    // unconditionally-disabled preview-mode button.
    expect(screen.getByRole("button", { name: /Run prediction/ })).toBeEnabled();

    const inferencePanel = container.querySelector(".dataset-detail-tabs__panel:not([hidden])")!;
    expect(inferencePanel.querySelector(".dataset-detail-overview__problem-summary")).not.toBeInTheDocument();
    expect(inferencePanel.querySelector(".performance-summary")).not.toBeInTheDocument();
    expect(inferencePanel.querySelector(".dataset-detail-visualization")).not.toBeInTheDocument();

    fireEvent.click(detailTabs.getByRole("tab", { name: "Documentation" }));
    expect(container.querySelectorAll(".dataset-detail-tabs__panel:not([hidden])")).toHaveLength(1);
    const documentationPanel = container.querySelector(".dataset-detail-tabs__panel:not([hidden])");
    expect(documentationPanel!.querySelectorAll(".atlas-card")).toHaveLength(0);
    // The shared publicProfile fixture never publishes documentation, so
    // Live Preview renders the shared renderer's bounded empty state.
    expect(documentationPanel).toHaveTextContent("No documentation has been published yet.");

    fireEvent.click(detailTabs.getByRole("tab", { name: "Overview" }));
    // Returning to Overview restores the same four-card composition without
    // duplication and without mounting a second Dataset Detail surface.
    expect(container.querySelectorAll(".dataset-detail-surface")).toHaveLength(1);
    expect(container.querySelectorAll(".dataset-detail-tabs__panel:not([hidden])")).toHaveLength(1);
    const restoredOverviewPanel = container.querySelector(".dataset-detail-tabs__panel:not([hidden])")!;
    expect(restoredOverviewPanel.querySelectorAll(".atlas-card")).toHaveLength(4);

    // No Model Card anywhere in the Dataset Detail preview, and the Admin
    // read-only load never requests the technical Model Card endpoint.
    expect(screen.queryByText(/model card/i)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/model-card"))).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "Home Card" }));
    // Level-scoped heading role proves DatasetCard's real <h3> title element.
    expect(screen.getByRole("heading", { level: 3, name: "Curated churn profile" })).toBeInTheDocument();
    expect(screen.getByText("Curated home card copy")).toBeInTheDocument();
    // Switching to Home Card removes the Dataset Detail stage modifier, the
    // Home Card panel remains present with its existing bounded layout, the
    // Dataset Detail surface is not mounted, and the obsolete wrappers stay
    // absent.
    expect(container.querySelector(".dataset-admin-preview-stage")).not.toHaveClass("dataset-admin-preview-stage--detail");
    expect(container.querySelectorAll(".dataset-admin-preview-panel--card")).toHaveLength(1);
    expect(container.querySelectorAll(".dataset-admin-preview-panel--detail")).toHaveLength(0);
    expect(container.querySelectorAll(".dataset-detail-surface")).toHaveLength(0);
    expect(container.querySelector(".dataset-admin-detail-preview-frame")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-admin-detail-preview-page")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Dataset Detail" }));
    expect(container.querySelectorAll(".dataset-detail-surface")).toHaveLength(1);
    // Switching back to Dataset Detail restores the edge-to-edge stage
    // modifier without retaining stale Home Card geometry.
    expect(container.querySelector(".dataset-admin-preview-stage")).toHaveClass("dataset-admin-preview-stage--detail");
    expect(container.querySelectorAll(".dataset-admin-preview-panel--card")).toHaveLength(0);
    // Remounting the shared surface resets its internal tab state back to
    // Overview, matching a fresh visit to /dataset/:slug.
    expect(screen.getByRole("tab", { name: "Overview", selected: true })).toBeInTheDocument();
  });

  // Project Spec S0120: the Dataset Detail preview reuses the same
  // safePublicSourceUrl safety contract the public page applies -- a safe
  // http(s) URL links the Source name, an unsafe/missing URL still shows the
  // plain Source name, and a missing Source name renders Pending even when a
  // URL is present, never an invented label.
  it("projects Source name/URL safety into the Dataset Detail preview", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    // The shared publicProfile fixture never curates a Source name.
    const sourceRow = screen.getByText("Source").nextElementSibling;
    expect(sourceRow).toHaveTextContent("Pending");

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Atlas Release Registry" } });
    fireEvent.change(screen.getByLabelText("Source URL"), { target: { value: "https://example.org/registry" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    const safeLink = screen.getByRole("link", { name: "Atlas Release Registry" });
    expect(safeLink).toHaveAttribute("href", "https://example.org/registry");

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Source URL"), { target: { value: "javascript:alert(1)" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    expect(screen.queryByRole("link", { name: "Atlas Release Registry" })).not.toBeInTheDocument();
    expect(screen.getByText("Atlas Release Registry")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    expect(screen.queryByText("Atlas Release Registry")).not.toBeInTheDocument();
    expect(screen.getByText("Source").nextElementSibling).toHaveTextContent("Pending");
  });

  // Project Spec S0154: the Dataset Detail Live Preview Target metadata now
  // comes from the same shared datasetPresentation.resolveDatasetTargetDescription
  // helper the public Dataset Detail calls, fed from the currently loaded
  // private authoring-context result-contract state (readOnlyData.resultContract)
  // -- never a second, independently-maintained Admin formatter, and never
  // an additional request.
  describe("Dataset Detail Live Preview Target metadata parity (Project Spec S0154)", () => {
    it("renders the shared helper's exact formatted output when the active release's result semantics are available, no longer showing Pending", async () => {
      const fetchMock = installFetchMock();
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      // The shared fixture's result semantics (positive_class.event_label
      // "Customer churn", class_id "churn"; negative_class.class_id
      // "retained") take precedence over the also-present context
      // prediction_target_description ("Customer churn" alone), proving
      // this is genuinely the shared-helper's formatted output and not a
      // coincidental match with the unformatted context description.
      expect(screen.getByText("Target").nextElementSibling).toHaveTextContent("Customer churn (churn/retained)");
      expect(screen.queryByText("Pending", { selector: ".dataset-detail-header__metadata-item dd" })).not.toBeInTheDocument();

      // This preview never triggers a second, public-endpoint request for
      // its own Target projection -- the private authoring-context read is
      // the only source.
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${datasetSlug}/contract`))).toBe(
        false,
      );
    });

    it("falls back to the nonblank published context description when the result contract is unavailable", async () => {
      installFetchMock({ resultContractOverride: { status: "unavailable", reason: "n/a" } });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      expect(screen.getByText("Target").nextElementSibling).toHaveTextContent("Customer churn");
      expect(screen.getByText("Target").nextElementSibling).not.toHaveTextContent("Customer churn (churn/retained)");
    });

    it("shows Pending (a null value) only when both result semantics and a context description are unavailable, never falling back to problem_type", async () => {
      installFetchMock({
        resultContractOverride: { status: "incompatible", reason: "n/a" },
        predictionTargetDescriptionOverride: null,
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      // The shared context fixture still carries problem_type
      // "binary_classification" -- it must never leak into the Target row
      // specifically (the separate, out-of-scope analysis badge is allowed
      // to keep showing it elsewhere on the page).
      const targetValue = screen.getByText("Target").nextElementSibling;
      expect(targetValue).toHaveTextContent("Pending");
      expect(targetValue).not.toHaveTextContent("binary_classification");
      expect(targetValue).not.toHaveTextContent("Binary Classification");
    });

    it("never retains the previous dataset's Target metadata while the newly selected dataset's result contract is loading or unavailable", async () => {
      const otherSlug = "energy-consumption-forecast";
      const otherViewId = "demand-forecast-overview";
      const firstSlugAuthoringContextHolder: { release: (() => void) | null } = { release: null };

      function availableResultContract(
        positiveClassId: string,
        positiveLabel: string,
        negativeClassId: string,
      ) {
        return {
          status: "available",
          semantics: {
            schema_version: "binary-result-semantics.v1",
            problem_type: "binary_classification",
            result_schema_version: "binary-classification-result.v1",
            primary_output: "positive_class_probability",
            positive_class: { class_id: positiveClassId, event_label: positiveLabel },
            negative_class: { class_id: negativeClassId },
            decision: { threshold: 0.5 },
            interpretation: {
              preset: "risk",
              bands: [
                { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
                { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
                { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
              ],
            },
            model_descriptor: { model_family: "model", display_name: "Model" },
          },
        };
      }

      function authoringContextFor(
        slug: string,
        title: string,
        resolvedViewId: string,
        resultContract: unknown,
        predictionTargetDescription: string | undefined,
      ) {
        return jsonResponse({
          dataset_slug: slug,
          active_release: "release-20260619-001",
          dataset: { status: "ready", data: { dataset_slug: slug, title, summary: "s", domain: "d", tags: [] } },
          context: { status: "ready", data: { prediction_target_description: predictionTargetDescription } },
          contract: {
            status: "ready",
            data: { contract: { schema_version: "1.0.0", features: [] }, result_contract: resultContract },
          },
          metrics: { status: "ready", data: {} },
          visualizations: { status: "ready", data: {} },
          views: { status: "ready", data: [{ view_id: resolvedViewId, display: { title } }] },
        });
      }

      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: datasetSlug,
                title: "Telco Customer Churn",
                display_title: null,
                summary: "s",
                domain: "telecom",
                tags: [],
                active_release: "release-20260619-001",
                publication_status: "ready",
                last_updated: "2026-06-19T12:00:00Z",
              },
              {
                dataset_slug: otherSlug,
                title: "Energy Consumption Forecast",
                display_title: null,
                summary: "s",
                domain: "energy",
                tags: [],
                active_release: "release-20260701-001",
                publication_status: "ready",
                last_updated: "2026-07-01T12:00:00Z",
              },
            ],
          });
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({
            datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
          });
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
          return new Promise((resolve) => {
            firstSlugAuthoringContextHolder.release = () =>
              resolve(
                authoringContextFor(
                  datasetSlug,
                  "Telco Customer Churn",
                  viewId,
                  availableResultContract("churn", "Customer churn", "retained"),
                  "Customer churn",
                ),
              );
          });
        }
        if (url.endsWith(`/admin/datasets/${otherSlug}/authoring-context`)) {
          // Deliberately no usable Target source at all for the newly
          // selected dataset (unavailable result contract, no context
          // description) -- any leaked Telco text would be unambiguous.
          return authoringContextFor(otherSlug, "Energy Consumption Forecast", otherViewId, { status: "unavailable" }, undefined);
        }
        if (
          url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) ||
          url.endsWith(`/admin/datasets/${otherSlug}/profile-draft`)
        ) {
          return jsonResponse({ draft_exists: false, profile: null });
        }
        if (
          url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`) ||
          url.endsWith(`/admin/datasets/${otherSlug}/publication-state`)
        ) {
          return jsonResponse({}, 404);
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);

      renderAdminPage();

      const selector = await screen.findByRole("button", { name: "Dataset" });
      await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

      // Let Telco's own authoring-context resolve first, so the Live
      // Preview genuinely has a rendered churn/retained Target to switch
      // away from (proving this is a real reset, not merely a first-paint
      // absence).
      firstSlugAuthoringContextHolder.release?.();
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      await waitFor(() =>
        expect(screen.getByText("Target").nextElementSibling).toHaveTextContent("Customer churn (churn/retained)"),
      );

      fireEvent.click(selector);
      fireEvent.click(screen.getByRole("option", { name: "Energy Consumption Forecast" }));

      // The moment the dataset switches, readOnlyData resets to "loading"
      // synchronously (before otherSlug's own response even arrives) -- the
      // previous dataset's Target text must never still be on screen here.
      expect(screen.queryByText("Customer churn (churn/retained)")).not.toBeInTheDocument();
      expect(screen.queryByText(/churn/i)).not.toBeInTheDocument();

      await waitFor(() => expect(screen.getByText("Target").nextElementSibling).toHaveTextContent("Pending"));
      expect(screen.queryByText("Customer churn (churn/retained)")).not.toBeInTheDocument();
    });
  });

  // Project Spec S0205: the Dataset Detail Live Preview Instances metadata
  // now reads the same already-loaded, bounded authoring-context
  // visualizations resource TargetDistribution/FeatureImportance already
  // render from (readOnlyData.visualizations, converted through
  // toVisualizationsPayload) -- never metrics, never a second request, and
  // never a manual authoring input.
  describe("Dataset Detail Live Preview Instances metadata (Project Spec S0205)", () => {
    it("renders Instances from the current visualizations resource's dataset_statistics.instance_count without an Evaluation split hint, needing no publish action", async () => {
      const fetchMock = installFetchMock({
        visualizationsOverride: { charts: [], dataset_statistics: { instance_count: 7043 } },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      const instancesRow = screen.getByText("Instances").closest(".dataset-detail-header__metadata-item");
      expect(instancesRow).not.toBeNull();
      expect(within(instancesRow as HTMLElement).getByText("7,043")).toBeInTheDocument();
      expect(within(instancesRow as HTMLElement).queryByText("Evaluation split")).not.toBeInTheDocument();
      expect(screen.queryByText("Evaluation split")).not.toBeInTheDocument();

      // No additional request beyond the single authoring-context envelope
      // this preview already loads everything from.
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).endsWith(`/datasets/${datasetSlug}/visualizations`)),
      ).toBe(false);
    });

    it("renders Pending (a null value) when the visualizations resource carries no dataset_statistics", async () => {
      installFetchMock({ visualizationsOverride: { charts: [] } });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      const instancesRow = screen.getByText("Instances").closest(".dataset-detail-header__metadata-item");
      expect(instancesRow).not.toBeNull();
      expect(within(instancesRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
    });

    it("never sums Target Distribution chart values into Instances", async () => {
      installFetchMock({
        visualizationsOverride: {
          charts: [
            {
              id: "target_distribution",
              title: "target distribution",
              type: "bar",
              data: [
                { name: "No", value: 5174 },
                { name: "Yes", value: 1869 },
              ],
            },
          ],
        },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

      const instancesRow = screen.getByText("Instances").closest(".dataset-detail-header__metadata-item");
      expect(instancesRow).not.toBeNull();
      expect(within(instancesRow as HTMLElement).getByText("Pending")).toBeInTheDocument();
      expect(screen.queryByText("7,043")).not.toBeInTheDocument();
    });
  });

  it("updates each Live Preview mode's rendered output when a fed draft or customization field is edited", async () => {
    // theme.preset is seeded as "ocean-blue" and metrics.evaluation.metrics is seeded
    // with a "precision" key (absent from the shared default fixture)
    // specifically so this test can prove genuine reactivity for theme and
    // primary-metric highlighting. The shared metrics
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
    expect(container.querySelector(".dataset-admin-preview-card .dataset-card")).toHaveAttribute(
      "data-theme-preset",
      "ocean-blue",
    );
    fireEvent.click(screen.getByRole("button", { name: "Bank building" }));
    fireEvent.change(screen.getByLabelText("Home card description"), {
      target: { value: "Edited home card description" },
    });
    fireEvent.change(screen.getByLabelText("Highlighted score"), { target: { value: "precision" } });
    fireEvent.change(screen.getByLabelText("Highlighted score value"), { target: { value: "0.81" } });

    fireEvent.click(screen.getByRole("tab", { name: "Theme Preset" }));
    fireEvent.click(screen.getByRole("button", { name: "Atlas Green" }));

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    fireEvent.change(screen.getByLabelText("Low label"), { target: { value: "Minimal risk (edited)" } });

    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    fireEvent.doubleClick(screen.getByText("tenure"));
    const fieldModal = await screen.findByRole("dialog", { name: "Edit field" });
    fireEvent.change(within(fieldModal).getByLabelText("Display label"), { target: { value: "Tenure (edited)" } });
    fireEvent.click(within(fieldModal).getByRole("button", { name: "Save field" }));

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

    // data-theme-preset now reflects the just-edited "atlas-green" selection,
    // not the "ocean-blue" value the draft was originally seeded with --
    // proving the attribute is live-bound to form.theme_preset rather than a
    // static initial prop. Project Spec S0120: the shared DatasetDetailSurface
    // owns Dataset Detail theme identity directly (not the outer Admin
    // preview stage), matching the same theme-scope contract DatasetPage.tsx
    // relies on.
    expect(container.querySelector(".dataset-detail-surface")).toHaveAttribute(
      "data-theme-preset",
      "atlas-green",
    );
    expect((container.querySelector(".dataset-detail-surface") as HTMLElement).style.getPropertyValue("--dataset-theme-accent"))
      .toBe("#2f6f4e");

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
    // Project Spec S0120: the Admin workaround that forced the Release hint
    // to a fixed "dd/mm/yyyy" wording is removed -- the hint now reflects
    // the actually-edited date_format, reusing the same shared
    // presentDatasetDateOnly contract the public Dataset Detail page uses.
    expect(screen.getByText("yyyy-mm-dd")).toBeInTheDocument();

    // The draft performance-focus projection moves the highlight and public
    // presentation value before publish. This lives in the Overview tab,
    // which is selected by default.
    expect(screen.getByText("Highlighted").closest("dt")).toHaveTextContent("Precision");
    expect(screen.getByText("Highlighted").closest("div")?.querySelector("dd")).toHaveTextContent("0.81");

    // Project Spec S0143: the functional Inference tab starts at the 0%
    // initial projection, which selects the governed low band (threshold
    // 0.6) and its edited presentation copy. Both live in the shared
    // surface's Inference tab.
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    expect(screen.getByText("Minimal risk (edited)")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenure (edited)")).toBeInTheDocument();
  });

  it("constrains highlighted scores to visible rows and synchronizes values", async () => {
    installFetchMock();
    renderAdminPage();
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));

    const toolbarPublish = within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole("button", { name: "Publish changes" });
    fireEvent.change(screen.getByLabelText("Highlighted score"), { target: { value: "precision" } });
    expect(toolbarPublish).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Highlighted score value"), { target: { value: "0.68" } });
    expect(screen.getByLabelText("Precision value")).toHaveValue("0.68");
    fireEvent.change(screen.getByLabelText("Precision value"), { target: { value: "0.69" } });
    expect(screen.getByLabelText("Highlighted score value")).toHaveValue("0.69");

    fireEvent.click(screen.getByLabelText("Show Precision"));
    expect(screen.getByLabelText("Precision value")).toBeDisabled();
    expect(screen.getByLabelText("Highlighted score")).toHaveValue("recall");
    expect(within(screen.getByLabelText("Highlighted score")).queryByRole("option", { name: "Precision" })).not.toBeInTheDocument();
  });

  it("shows pointer-following drag overlay activity for fields and groups", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    const layoutPanel = screen.getByLabelText("Public form layout");
    const groupDragHandle = within(layoutPanel).getByRole("button", { name: "Drag group Account profile" });
    fireEvent.pointerDown(groupDragHandle, { pointerId: 1, clientX: 12, clientY: 16 });
    const groupGhost = screen.getAllByText("Account profile").find((el) => el.tagName !== "OPTION");
    expect(groupGhost).toBeInTheDocument();
    fireEvent.pointerUp(groupDragHandle, { pointerId: 1, clientX: 18, clientY: 24 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(1);
    });

    const fieldDragHandle = within(layoutPanel).getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });
    const fieldGhost = screen.getAllByText("Tenure").find((el) => el.tagName !== "OPTION");
    expect(fieldGhost).toBeInTheDocument();
    fireEvent.pointerCancel(fieldDragHandle, { pointerId: 2, clientX: 20, clientY: 28 });

    await waitFor(() => {
      expect(Element.prototype.setPointerCapture).toHaveBeenCalledWith(2);
    });
  });

  it("persists group create/edit/remove/reorder through customization save and reload", async () => {
    // Route every drop onto the newly created "group-1" zone -- this test
    // only ever drags one field (tenure), into that one destination. Project
    // Spec S0104: the collision-safe generator looks at the highest existing
    // "group-N" numeric suffix, and the two pre-existing groups here
    // ("account", "charges") don't match that pattern, so the first
    // generated id is "group-1", not the old array-length-based "group-3".
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="group-1"]'),
    );

    // A second eligible view keeps the S0100 governed multi-view select
    // available -- used only as the mechanism to force a genuine reload
    // (unbind/rebind) below, proving the reload reflects real persisted
    // state rather than only the in-memory draft.
    installFetchMock({
      trackCustomizationSaves: true,
      viewsOverride: [
        { view_id: viewId, display: { title: "Churn risk overview" } },
        { view_id: "retention-outlook", display: { title: "Retention Outlook" } },
      ],
    });
    renderAdminPage();

    await loadDraftAndCustomization();

    const layoutPanel = screen.getByLabelText("Public form layout");

    // Project Spec S0100: "Add group" is now "Add subgroup", and the new
    // card's metadata (Label/Description/Remove) is hidden until its
    // on-demand "Edit" panel is opened -- no "Remove" button exists in the
    // normal collapsed header to locate the new card by anymore.
    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    const cardsAfterAdd = layoutPanel.querySelectorAll(".dataset-admin-builder-card");
    const newGroupCard = cardsAfterAdd[cardsAfterAdd.length - 1] as HTMLElement;

    fireEvent.click(within(newGroupCard).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(newGroupCard).getByLabelText("Label"), { target: { value: "Support tier" } });
    fireEvent.change(within(newGroupCard).getByLabelText("Description"), {
      target: { value: "Support-related attributes" },
    });
    fireEvent.click(within(newGroupCard).getByRole("button", { name: "Save subgroup" }));

    // The new group's group_id is deterministically "group-1" (see the
    // collision-safe generator note above). Drag "tenure" out of Account
    // profile into the newly created group.
    const tenureDragHandle = screen.getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(tenureDragHandle, { pointerId: 5, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureDragHandle, { pointerId: 5, clientX: 0, clientY: 0 });

    // Project Spec S0100: Save subgroup commits the label/description into
    // the shared draft immediately, so Live Preview (fed from that same
    // draft) reflects it before the overall "Save customization" persists
    // anything to the backend (InferenceForm only renders a subgroup once it
    // has a member, so this check comes after the drag above).
    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    expect(screen.getByText("Support tier")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    // The stacked down control on the first subgroup ("Account profile")
    // swaps it with its neighbor ("Charges").
    fireEvent.click(screen.getByRole("button", { name: "Move subgroup Account profile down" }));

    // Remove a different pre-existing group ("Account profile") than the one
    // just created/edited/assigned ("Support tier"). "Remove subgroup" is a
    // secondary action inside that card's own Edit panel.
    const accountCard = screen.getByText("Account profile").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(accountCard).getByRole("button", { name: "Edit" }));
    fireEvent.click(within(accountCard).getByRole("button", { name: "Remove subgroup" }));

    // Project Spec S0103: "Save customization" no longer exists -- editing
    // the Inference Form customization enables the shared workspace toolbar
    // Publish changes button, which persists it through the same
    // customization endpoint.
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    // A real reload, not just a payload assertion: unbind and rebind the
    // predict view via the (still-available, multi-view) select, which
    // re-triggers the automatic bootstrap fetch (there is no manual "Load
    // customization" control), and verify the re-rendered editor reflects
    // all five edits.
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: viewId } });

    await waitFor(() => {
      const reloadedLayoutPanel = screen.getByLabelText("Public form layout");
      const reloadedCards = Array.from(reloadedLayoutPanel.querySelectorAll(".dataset-admin-builder-card"));
      expect(reloadedCards.map((card) => card.querySelector("strong")?.textContent)).toEqual([
        "Charges",
        "Support tier",
      ]);
    });
    const reloadedLayoutPanel = screen.getByLabelText("Public form layout");
    const reloadedCards = Array.from(reloadedLayoutPanel.querySelectorAll(".dataset-admin-builder-card"));
    expect(
      reloadedCards.map((card) => card.querySelector(".dataset-admin-subgroup-header__helper")?.textContent),
    ).toEqual(["Billing attributes", "Support-related attributes"]);

    expect(within(screen.getByLabelText("Support tier")).getByText("tenure")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Charges")).getByText("MonthlyCharges")).toBeInTheDocument();
  });

  it("isolates the group collapse affordance from the saved customization", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    const accountCard = screen.getByText("Account profile").closest(".dataset-admin-builder-card") as HTMLElement;

    // Project Spec S0100: the subgroup metadata edit panel is closed by
    // default and independent of collapse/expand -- Label/Description are
    // never shown until "Edit" is activated. Project Spec S0104: there is no
    // Group ID input at all -- group_id is internal and never editable.
    const collapseButton = within(accountCard).getByRole("button", { name: "Collapse" });
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");
    expect(within(accountCard).queryByLabelText("Group ID")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Label")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Description")).not.toBeInTheDocument();
    expect(within(accountCard).getByText("tenure")).toBeInTheDocument();

    // Activating Edit reveals the metadata fields seeded from the current
    // group; Cancel discards any local change without mutating the draft.
    fireEvent.click(within(accountCard).getByRole("button", { name: "Edit" }));
    expect(within(accountCard).queryByLabelText("Group ID")).not.toBeInTheDocument();
    expect(within(accountCard).getByLabelText("Label")).toHaveValue("Account profile");
    expect(within(accountCard).getByLabelText("Description")).toHaveValue("Account attributes");
    fireEvent.change(within(accountCard).getByLabelText("Label"), { target: { value: "Should not persist" } });
    fireEvent.click(within(accountCard).getByRole("button", { name: "Cancel" }));
    expect(within(accountCard).queryByLabelText("Label")).not.toBeInTheDocument();
    expect(screen.getByText("Account profile")).toBeInTheDocument();
    expect(screen.queryByText("Should not persist")).not.toBeInTheDocument();

    fireEvent.click(collapseButton);

    const expandButton = within(accountCard).getByRole("button", { name: "Expand" });
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    expect(within(accountCard).queryByLabelText("Group ID")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Label")).not.toBeInTheDocument();
    expect(within(accountCard).queryByLabelText("Description")).not.toBeInTheDocument();
    expect(within(accountCard).queryByText("tenure")).not.toBeInTheDocument();

    // The header row (stacked up/down, drag, field count, edit,
    // collapse/expand) must remain visible and functional regardless of
    // collapsed state. "Remove subgroup" is a secondary action inside the
    // Edit panel now, not the collapsed header.
    expect(within(accountCard).getByRole("button", { name: /^Drag group/ })).toBeInTheDocument();
    expect(within(accountCard).getByRole("button", { name: "Move subgroup Account profile down" })).toBeInTheDocument();
    expect(within(accountCard).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(accountCard).getByText(/fields$/)).toBeInTheDocument();

    fireEvent.click(expandButton);

    // Project Spec S0103: collapse/expand and a cancelled Edit panel change
    // are transient editor state, never persisted customization data, so
    // neither dirties the shared workspace toolbar Publish changes button --
    // the direct proof that the underlying draft was never mutated by them.
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Project Spec S0104: group identity is internal/stable, historical blank
  // labels get a deterministic fallback, and new group identity generation
  // is collision-safe
  // -------------------------------------------------------------------------

  it("gives a historical group with a blank label a deterministic generic display label, never the raw group_id, and seeds it into the active draft", async () => {
    installFetchMock({
      customizationOverride: {
        ...customization,
        groups: [
          { group_id: "account", label: "", description: "Account attributes" },
          { group_id: "charges", label: "Charges", description: "Billing attributes" },
        ],
      },
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    // The raw group_id ("account") is never rendered as the visible title.
    expect(screen.queryByText("account")).not.toBeInTheDocument();
    expect(screen.getByText("Group 1")).toBeInTheDocument();
    expect(screen.getByText("Charges")).toBeInTheDocument();

    const blankLabelCard = screen.getByText("Group 1").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(blankLabelCard).getByRole("button", { name: "Edit" }));
    expect(within(blankLabelCard).queryByLabelText("Group ID")).not.toBeInTheDocument();
    // The generated fallback is seeded directly into the editable Label
    // field, not left blank, so the operator can edit and persist it
    // intentionally the next time they publish.
    expect(within(blankLabelCard).getByLabelText("Label")).toHaveValue("Group 1");
  });

  it("generates a collision-safe new group identity after a deletion gap, and repeated activations produce distinct ids/labels", async () => {
    const fetchMock = installFetchMock({
      trackCustomizationSaves: true,
      customizationOverride: {
        ...customization,
        groups: [
          { group_id: "group-1", label: "Group 1", description: "" },
          { group_id: "group-3", label: "Group 3", description: "" },
        ],
      },
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    // [group-1, group-3] must produce group-4, never a reused "group-3"
    // merely because the array length is two.
    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    expect(screen.getByText("Group 4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    expect(screen.getByText("Group 5")).toBeInTheDocument();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const saveCall = fetchMock.mock.calls.find(
      (call: unknown[]) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      groups: Array<{ group_id: string; label: string }>;
    };
    expect(body.groups.map((group) => group.group_id)).toEqual(["group-1", "group-3", "group-4", "group-5"]);
    expect(body.groups.map((group) => group.label)).toEqual(["Group 1", "Group 3", "Group 4", "Group 5"]);
  });

  it("editing a group's label does not change its internal group_id or the field group references assigned to it", async () => {
    const fetchMock = installFetchMock({ trackCustomizationSaves: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    const accountCard = screen.getByText("Account profile").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(accountCard).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(accountCard).getByLabelText("Label"), { target: { value: "Account profile renamed" } });
    fireEvent.click(within(accountCard).getByRole("button", { name: "Save subgroup" }));

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const saveCall = fetchMock.mock.calls.find(
      (call: unknown[]) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      groups: Array<{ group_id: string; label: string }>;
      field_hints: Array<{ field_name: string; group?: string }>;
    };
    const renamedGroup = body.groups.find((group) => group.label === "Account profile renamed");
    expect(renamedGroup?.group_id).toBe("account");
    const tenureHint = body.field_hints.find((hint) => hint.field_name === "tenure");
    expect(tenureHint?.group).toBe("account");
  });

  it("shows a visible attention state for a required field left in the bank, blocks saving, and never persists it as hidden", async () => {
    document.elementFromPoint = vi.fn(() => null);
    const fetchMock = installFetchMock({ requiredFieldOverride: "tenure" });
    renderAdminPage();

    await loadDraftAndCustomization();

    const bankZone = document.querySelector<HTMLElement>('[data-customization-drop-zone="bank"]');
    document.elementFromPoint = vi.fn(() => bankZone);

    const tenureDragHandle = screen.getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(tenureDragHandle, { pointerId: 7, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureDragHandle, { pointerId: 7, clientX: 0, clientY: 0 });

    const bankPanel = screen.getByLabelText("Field bank");
    const tenureChip = within(bankPanel).getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    expect(tenureChip).toHaveClass("is-required-attention");
    expect(within(tenureChip).getByText("Required")).toBeInTheDocument();
    expect(screen.getByText(/1 required field still in the bank/i)).toBeInTheDocument();

    // Project Spec S0103: "Save customization" no longer exists. Moving a
    // required field into the bank dirties the shared workspace toolbar
    // Publish changes button (like any other persisted customization edit),
    // but clicking it while a required field is hidden is blocked entirely
    // by the same local guard, with an actionable message beside the
    // toolbar action -- the button itself stays enabled rather than
    // pre-emptively disabling like the removed dedicated save button did.
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeEnabled();

    const callsBeforeBlockedAttempt = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    expect(
      await screen.findByText("Move every required field out of the field bank before saving."),
    ).toBeInTheDocument();
    expect(publishButton).toBeEnabled();
    expect(
      fetchMock.mock.calls
        .slice(callsBeforeBlockedAttempt)
        .some(
          (call: unknown[]) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        ),
    ).toBe(false);
    // Local validation blocks both requests, not just the customization one.
    expect(
      fetchMock.mock.calls
        .slice(callsBeforeBlockedAttempt)
        .some((call: unknown[]) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
    ).toBe(false);

    // Drag tenure back out into the public form layout's No subgroup zone --
    // required fields return to the standard chip treatment and the block
    // clears once no required field remains in the bank.
    const noSubgroupZone = document.querySelector<HTMLElement>('[data-customization-drop-zone="no-subgroup"]');
    document.elementFromPoint = vi.fn(() => noSubgroupZone);
    const tenureDragHandleAgain = within(bankPanel).getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(tenureDragHandleAgain, { pointerId: 8, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureDragHandleAgain, { pointerId: 8, clientX: 0, clientY: 0 });

    expect(screen.queryByText(/required field.*still in the bank/i)).not.toBeInTheDocument();
    expect(publishButton).toBeEnabled();

    const callsBeforeSave = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const saveCall = fetchMock.mock.calls
      .slice(callsBeforeSave)
      .find(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    expect(saveCall).toBeDefined();
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      field_hints: Array<{ field_name: string; hidden?: boolean; group?: string }>;
    };
    const tenureHint = body.field_hints.find((hint) => hint.field_name === "tenure");
    expect(tenureHint?.hidden).toBeUndefined();
    expect(tenureHint?.group).toBeUndefined();
  });

  it("saves identical subgroup order via a stacked up/down control reorder and an equivalent drag reorder", async () => {
    function extractSavedGroupOrder(fetchMock: ReturnType<typeof installFetchMock>, callsBeforeSave: number) {
      const saveCall = fetchMock.mock.calls
        .slice(callsBeforeSave)
        .find(
          (call: unknown[]) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        );
      const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
        groups: Array<{ group_id: string }>;
      };
      return body.groups.map((group) => group.group_id);
    }

    document.elementFromPoint = vi.fn(() => null);

    const buttonFetchMock = installFetchMock();
    const { unmount } = renderAdminPage();
    await loadDraftAndCustomization();

    const callsBeforeButtonSave = buttonFetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Move subgroup Account profile down" }));
    const buttonToolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(buttonToolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(buttonToolbar).getByText("Changes saved.")).toBeInTheDocument());
    const buttonOrder = extractSavedGroupOrder(buttonFetchMock, callsBeforeButtonSave);

    unmount();

    // jsdom does not implement elementFromPoint at all (the property is
    // absent, not just unimplemented), so it must be assigned directly
    // rather than wrapped with vi.spyOn, which requires the property to
    // already exist.
    document.elementFromPoint = vi.fn((_x: number, y: number) =>
      document.querySelector<HTMLElement>(`[data-customization-group-index="${y}"]`),
    );

    const dragFetchMock = installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const accountDragHandle = screen.getByRole("button", { name: "Drag group Account profile" });
    const callsBeforeDragSave = dragFetchMock.mock.calls.length;
    fireEvent.pointerDown(accountDragHandle, { pointerId: 3, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(accountDragHandle, { pointerId: 3, clientX: 0, clientY: 1 });
    const dragToolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(dragToolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(dragToolbar).getByText("Changes saved.")).toBeInTheDocument());
    const dragOrder = extractSavedGroupOrder(dragFetchMock, callsBeforeDragSave);

    expect(dragOrder).toEqual(buttonOrder);
    expect(dragOrder).toEqual(["charges", "account"]);
  });

  it("moves fields across every zone via drag and drop, keeping each field visible exactly once with a deterministic saved order", async () => {
    function dropOn(zone: string) {
      document.elementFromPoint = vi.fn(() =>
        document.querySelector<HTMLElement>(`[data-customization-drop-zone="${zone}"]`),
      );
    }

    const fetchMock = installFetchMock({ trackCustomizationSaves: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    // tenure: Account profile subgroup -> Field bank (optional field, so this
    // is an allowed pending state, not a blocked one).
    dropOn("bank");
    let handle = screen.getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(handle, { pointerId: 10, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(handle, { pointerId: 10, clientX: 0, clientY: 0 });

    const bankPanel = screen.getByLabelText("Field bank");
    expect(within(bankPanel).getByText("tenure")).toBeInTheDocument();

    // MonthlyCharges: Charges subgroup -> No subgroup.
    dropOn("no-subgroup");
    handle = screen.getByRole("button", { name: "Drag field Monthly charges" });
    fireEvent.pointerDown(handle, { pointerId: 11, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(handle, { pointerId: 11, clientX: 0, clientY: 0 });

    expect(within(screen.getByLabelText("No subgroup fields")).getByText("MonthlyCharges")).toBeInTheDocument();

    // tenure: Field bank -> back into the Account profile subgroup.
    dropOn("account");
    handle = within(bankPanel).getByRole("button", { name: "Drag field Tenure" });
    fireEvent.pointerDown(handle, { pointerId: 12, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(handle, { pointerId: 12, clientX: 0, clientY: 0 });

    expect(within(screen.getByLabelText("Account profile")).getByText("tenure")).toBeInTheDocument();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const saveCall = fetchMock.mock.calls.find(
      (call: unknown[]) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    const body = JSON.parse(String((saveCall?.[1] as RequestInit).body)) as {
      field_hints: Array<{ field_name: string; group?: string; hidden?: boolean; display_order_hint: number }>;
    };
    expect(body.field_hints).toHaveLength(2);
    const tenureHint = body.field_hints.find((hint) => hint.field_name === "tenure");
    const chargesHint = body.field_hints.find((hint) => hint.field_name === "MonthlyCharges");
    expect(tenureHint?.group).toBe("account");
    expect(tenureHint?.hidden).toBeUndefined();
    expect(chargesHint?.group).toBeUndefined();
    expect(chargesHint?.hidden).toBeUndefined();
    const orderHints = body.field_hints.map((hint) => hint.display_order_hint).sort((a, b) => a - b);
    expect(orderHints).toEqual([1, 2]);
  });

  it("renders Field bank before Public form layout in DOM order", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const bankSection = screen.getByLabelText("Field bank");
    const layoutSection = screen.getByLabelText("Public form layout");
    expect(
      bankSection.compareDocumentPosition(layoutSection) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("starts the Inference Form tab directly with a compact action row and no repeated tab shell or extra outer card (Project Spec S0100)", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tabPanel = screen.getByRole("tabpanel");
    // No repeated tab-level eyebrow/title/subtitle/scope badge above the
    // builder (unlike tabs that still use the TabWorkspace eyebrow wrapper).
    expect(within(tabPanel).queryByText("Inference Form")).not.toBeInTheDocument();
    expect(
      within(tabPanel).queryByText(
        "Organize presentation for the bound predict view while contract fields and validation stay authoritative.",
      ),
    ).not.toBeInTheDocument();

    // Project Spec S0104: there is no separate top action row anymore --
    // "Add subgroup" lives inside the Public form layout header, aligned
    // right beside the visible-field counter, and the old bound-view badge
    // is gone without any replacement tag/pill/card/status label.
    expect(document.querySelector(".dataset-admin-builder-actions")).toBeNull();
    const layoutSectionForHeading = screen.getByLabelText("Public form layout");
    const layoutHeading = layoutSectionForHeading.querySelector(".dataset-admin-builder__heading") as HTMLElement;
    expect(within(layoutHeading).getByRole("button", { name: "Add subgroup" })).toBeInTheDocument();
    expect(within(layoutHeading).getByText(/visible$/)).toBeInTheDocument();

    // The builder is not wrapped in an additional full card around the two
    // columns (no atlas-card ancestor between the Public form layout section
    // and the tab panel root).
    expect(layoutSectionForHeading.closest(".atlas-card")).toBeNull();

    // No visible text node "Drag" anywhere in a subgroup header -- only the
    // accessible name carries that word; the visible glyph is an icon.
    const subgroupHead = document.querySelector(".dataset-admin-builder-card__head") as HTMLElement;
    expect(subgroupHead.textContent).not.toContain("Drag");
    expect(within(subgroupHead).getByRole("button", { name: /^Drag group/ })).toBeInTheDocument();
  });

  it("edits a field's presentation through the double-click modal, supporting cancel, Escape, and focus restore", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.doubleClick(tenureChip);

    let dialog = await screen.findByRole("dialog", { name: "Edit field" });
    expect(document.activeElement).toBe(within(dialog).getByLabelText("Display label"));
    expect(within(dialog).getByText("tenure")).toBeInTheDocument();
    expect(within(dialog).getByText("number")).toBeInTheDocument();
    expect(within(dialog).getByText("Optional")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Group")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Display label"), { target: { value: "Should not persist" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: "Edit field" })).not.toBeInTheDocument();
    expect(screen.queryByText("Should not persist")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(tenureChip);

    fireEvent.doubleClick(tenureChip);
    await screen.findByRole("dialog", { name: "Edit field" });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Edit field" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(tenureChip);

    fireEvent.doubleClick(tenureChip);
    dialog = await screen.findByRole("dialog", { name: "Edit field" });
    fireEvent.change(within(dialog).getByLabelText("Display label"), { target: { value: "Tenure (renamed)" } });
    fireEvent.change(within(dialog).getByLabelText("Explanatory copy"), { target: { value: "Updated copy" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save field" }));

    expect(screen.queryByRole("dialog", { name: "Edit field" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(tenureChip);
  });

  // -------------------------------------------------------------------------
  // Project Spec S0104: the whole field chip is the drag hitbox, not just
  // the six-dot handle, and a completed drag never opens the edit modal
  // -------------------------------------------------------------------------

  it("starts a field drag from the field name, not just the six-dot handle", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="bank"]'),
    );
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureName = within(screen.getByLabelText("Account profile")).getByText("tenure");
    fireEvent.pointerDown(tenureName, { pointerId: 20, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureName, { pointerId: 20, clientX: 0, clientY: 50 });

    expect(within(screen.getByLabelText("Field bank")).getByText("tenure")).toBeInTheDocument();
  });

  it("starts a field drag from empty chip space", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="no-subgroup"]'),
    );
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.pointerDown(tenureChip, { pointerId: 21, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureChip, { pointerId: 21, clientX: 0, clientY: 50 });

    expect(within(screen.getByLabelText("No subgroup fields")).getByText("tenure")).toBeInTheDocument();
  });

  it("starts a field drag from the Required tag", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="no-subgroup"]'),
    );
    installFetchMock({ requiredFieldOverride: "tenure" });
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    const requiredTag = within(tenureChip).getByText("Required");
    fireEvent.pointerDown(requiredTag, { pointerId: 22, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(requiredTag, { pointerId: 22, clientX: 0, clientY: 50 });

    expect(within(screen.getByLabelText("No subgroup fields")).getByText("tenure")).toBeInTheDocument();
  });

  it("suppresses the double-click-to-edit modal immediately after a completed drag with real pointer movement, but not the next genuine double click", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="bank"]'),
    );
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.pointerDown(tenureChip, { pointerId: 23, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(tenureChip, { pointerId: 23, clientX: 0, clientY: 40 });
    fireEvent.pointerUp(tenureChip, { pointerId: 23, clientX: 0, clientY: 40 });

    // The field actually moved -- proof a real drag happened, not a click.
    expect(within(screen.getByLabelText("Field bank")).getByText("tenure")).toBeInTheDocument();

    const movedChip = within(screen.getByLabelText("Field bank"))
      .getByText("tenure")
      .closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.doubleClick(movedChip);
    expect(screen.queryByRole("dialog", { name: "Edit field" })).not.toBeInTheDocument();

    // The suppression is consumed by that one double click -- a later,
    // genuine double click (with no drag before it) still opens the modal.
    fireEvent.doubleClick(movedChip);
    expect(await screen.findByRole("dialog", { name: "Edit field" })).toBeInTheDocument();
  });

  it("does not suppress the double-click modal after a pointer down/up with no real movement", async () => {
    document.elementFromPoint = vi.fn(() => null);
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.pointerDown(tenureChip, { pointerId: 24, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(tenureChip, { pointerId: 24, clientX: 0, clientY: 0 });

    fireEvent.doubleClick(tenureChip);
    expect(await screen.findByRole("dialog", { name: "Edit field" })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Project Spec S0105: No subgroup redundant copy removal and full-chip
  // grab/grabbing cursor contract
  // -------------------------------------------------------------------------

  it("removes the redundant No subgroup description sentence while keeping the title, counter, drop zone, and empty-state copy", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const noSubgroupZone = screen.getByLabelText("No subgroup");
    expect(
      within(noSubgroupZone).queryByText("Visible fields with no subgroup render here, below every subgroup card."),
    ).not.toBeInTheDocument();

    const heading = within(noSubgroupZone)
      .getByText("No subgroup")
      .closest(".dataset-admin-builder__heading") as HTMLElement;
    expect(within(heading).getByText(/fields$/)).toBeInTheDocument();

    const dropZone = screen.getByLabelText("No subgroup fields");
    expect(within(dropZone).getByText("Drag fields here to show them without a subgroup.")).toBeInTheDocument();
    expect(dropZone).toHaveAttribute("data-customization-drop-zone", "no-subgroup");
  });

  it("applies the is-dragging class to the source chip while dragging and clears it after a completed drop", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="no-subgroup"]'),
    );
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    expect(tenureChip).not.toHaveClass("is-dragging");

    fireEvent.pointerDown(tenureChip, { pointerId: 30, clientX: 0, clientY: 0 });
    expect(tenureChip).toHaveClass("is-dragging");

    fireEvent.pointerUp(tenureChip, { pointerId: 30, clientX: 0, clientY: 50 });

    const movedChip = within(screen.getByLabelText("No subgroup fields"))
      .getByText("tenure")
      .closest(".dataset-admin-field-chip") as HTMLElement;
    expect(movedChip).not.toHaveClass("is-dragging");
  });

  it("clears the is-dragging state after pointer cancellation without moving the field", async () => {
    document.elementFromPoint = vi.fn(() => null);
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.pointerDown(tenureChip, { pointerId: 31, clientX: 0, clientY: 0 });
    expect(tenureChip).toHaveClass("is-dragging");

    fireEvent.pointerCancel(tenureChip, { pointerId: 31, clientX: 0, clientY: 40 });
    expect(tenureChip).not.toHaveClass("is-dragging");
    expect(within(screen.getByLabelText("Account profile")).getByText("tenure")).toBeInTheDocument();
  });

  it("clears the is-dragging state after lost pointer capture without moving the field", async () => {
    document.elementFromPoint = vi.fn(() => null);
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    fireEvent.pointerDown(tenureChip, { pointerId: 32, clientX: 0, clientY: 0 });
    expect(tenureChip).toHaveClass("is-dragging");

    fireEvent.lostPointerCapture(tenureChip, { pointerId: 32 });
    expect(tenureChip).not.toHaveClass("is-dragging");
    expect(within(screen.getByLabelText("Account profile")).getByText("tenure")).toBeInTheDocument();
  });

  it("does not apply the is-dragging class to a chip that is not the active drag source", async () => {
    document.elementFromPoint = vi.fn(() => null);
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const tenureChip = screen.getByText("tenure").closest(".dataset-admin-field-chip") as HTMLElement;
    const chargesChip = screen.getByText("MonthlyCharges").closest(".dataset-admin-field-chip") as HTMLElement;

    fireEvent.pointerDown(tenureChip, { pointerId: 33, clientX: 0, clientY: 0 });
    expect(tenureChip).toHaveClass("is-dragging");
    expect(chargesChip).not.toHaveClass("is-dragging");

    fireEvent.pointerUp(tenureChip, { pointerId: 33, clientX: 0, clientY: 0 });
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

  it("populates the filterable Admin dataset selector for a multi-dataset listing including a synthetic non-Telco/Bank dataset and updates the header from publication-state on selection change (Project Spec S0116; Project Spec S0123 configured-visibility action authority)", async () => {
    // AdminDatasetListing shape (GET /admin/datasets, registry/list.py's
    // list_admin_datasets) -- distinct from the public DatasetListing shape
    // used by the separate GET /datasets fetch below.
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
    // Project Spec S0116: the header badge is driven exclusively by each
    // dataset's own publication-state public_access.reachable value, never
    // by public-listing membership -- datasetOne and datasetThree are
    // reachable, datasetTwo (needs_review) is not, exercising the header's
    // Public/Private distinction through the new authority.
    function publicationStateFor(slug: string, reachable: boolean) {
      return jsonResponse({
        dataset_slug: slug,
        active_release: "release-20260701-001",
        visibility: {
          configured_visible: true,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-01T00:00:00Z",
          effective_visible: true,
        },
        review: {
          status: reachable ? "ready" : "needs_review",
          approval_allowed: !reachable,
          approval_blockers: [],
        },
        snapshot: {
          status: "current_release",
          exists: true,
          published_at: "2026-07-01T00:00:00Z",
          active_release_at_publish_time: "release-20260701-001",
          matches_active_release: true,
        },
        public_access: { reachable, blockers: reachable ? [] : ["review_pending"], observations: [] },
      });
    }

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [adminDatasetOne, adminDatasetTwo, adminDatasetThree] });
      }
      // The public /datasets listing still seeds the initial selectedSlug
      // (unrelated to the header badge authority under test here), so it
      // must include at least the first dataset for auto-selection to occur.
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [{ ...adminDatasetOne, visibility: "public" }] });
      }
      if (url.endsWith(`/admin/datasets/${adminDatasetOne.dataset_slug}/publication-state`)) {
        return publicationStateFor(adminDatasetOne.dataset_slug, true);
      }
      if (url.endsWith(`/admin/datasets/${adminDatasetTwo.dataset_slug}/publication-state`)) {
        return publicationStateFor(adminDatasetTwo.dataset_slug, false);
      }
      if (url.endsWith(`/admin/datasets/${adminDatasetThree.dataset_slug}/publication-state`)) {
        return publicationStateFor(adminDatasetThree.dataset_slug, true);
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
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));

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
    // datasetTwo's publication-state reports not reachable (needs_review),
    // so the header must show it as Private. Project Spec S0123: the
    // public-open action itself is still enabled, since every fixture here
    // keeps configured_visible = true and the action follows that value,
    // never public_access.reachable.
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();

    fireEvent.click(selector);
    fireEvent.click(
      within(screen.getByRole("listbox", { name: "Available datasets" })).getByRole("option", {
        name: adminDatasetThree.display_title,
      }),
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: `Dataset — ${adminDatasetThree.display_title}` })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Public"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
  });

  it("disables the public-page action after switching to a configured-hidden dataset, then enables it (while the badge stays Private) after switching to a visible-but-review-blocked dataset (Project Spec S0123)", async () => {
    const hiddenSlug = "synthetic-hidden-dataset";
    const reviewBlockedSlug = "synthetic-review-blocked-dataset";
    const adminHidden = {
      dataset_slug: hiddenSlug,
      title: "Synthetic Hidden Dataset",
      display_title: "Hidden Dataset Display",
      summary: "Synthetic hidden dataset",
      domain: "retail",
      tags: ["retail"],
      active_release: "release-20260701-004",
      publication_status: "ready",
    };
    const adminReviewBlocked = {
      dataset_slug: reviewBlockedSlug,
      title: "Synthetic Review-Blocked Dataset",
      display_title: "Review-Blocked Dataset Display",
      summary: "Synthetic visible-but-review-blocked dataset",
      domain: "energy",
      tags: ["energy"],
      active_release: "release-20260701-005",
      publication_status: "ready",
    };

    function publicationStateFor(slug: string, configuredVisible: boolean, reachable: boolean) {
      return jsonResponse({
        dataset_slug: slug,
        active_release: "release-20260701-001",
        visibility: {
          configured_visible: configuredVisible,
          source: "explicit_record",
          record_status: "valid",
          updated_at: "2026-07-01T00:00:00Z",
          effective_visible: reachable,
        },
        review: {
          status: reachable ? "ready" : "needs_review",
          approval_allowed: !reachable,
          approval_blockers: [],
        },
        snapshot: {
          status: "current_release",
          exists: true,
          published_at: "2026-07-01T00:00:00Z",
          active_release_at_publish_time: "release-20260701-001",
          matches_active_release: true,
        },
        public_access: {
          reachable,
          blockers: reachable ? [] : configuredVisible ? ["review_pending"] : ["visibility_disabled"],
          observations: [],
        },
      });
    }

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({ datasets: [adminHidden, adminReviewBlocked] });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({ datasets: [{ ...adminHidden, visibility: "private" }] });
      }
      if (url.endsWith(`/admin/datasets/${hiddenSlug}/publication-state`)) {
        return publicationStateFor(hiddenSlug, false, false);
      }
      if (url.endsWith(`/admin/datasets/${reviewBlockedSlug}/publication-state`)) {
        return publicationStateFor(reviewBlockedSlug, true, false);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toHaveTextContent(adminHidden.display_title));
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeDisabled();

    fireEvent.click(selector);
    fireEvent.click(
      within(screen.getByRole("listbox", { name: "Available datasets" })).getByRole("option", {
        name: adminReviewBlocked.display_title,
      }),
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: `Dataset — ${adminReviewBlocked.display_title}` })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByLabelText("Dataset Detail visibility")).toHaveTextContent("Private"));
    // Project Spec S0123: reviewBlockedSlug's confirmed configured_visible
    // = true enables the action even though the badge still reads Private
    // (public_access.reachable = false, review_pending).
    expect(screen.getByRole("button", { name: "Open public Dataset Detail page" })).toBeEnabled();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open public Dataset Detail page" }));
    expect(openSpy).toHaveBeenCalledWith(`/dataset/${encodeURIComponent(reviewBlockedSlug)}`, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
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
    expect(screen.getByText("0 / 600")).toBeInTheDocument();

    const subtitleValue = "Predicao de churn";
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: subtitleValue } });
    expect(screen.getByText(`${subtitleValue.length} / 120`)).toBeInTheDocument();
    expect(screen.queryByText("0 / 120")).not.toBeInTheDocument();

    const summaryBodyValue = "Explains churn.";
    fireEvent.change(screen.getByLabelText("Problem summary body"), { target: { value: summaryBodyValue } });
    expect(screen.getByText(`${summaryBodyValue.length} / 600`)).toBeInTheDocument();
  });

  it("exposes Problem summary body maxLength=600 and accepts a value beyond the old 300-character limit, up to the new limit, while preserving field serialization (Project Spec S0202)", async () => {
    installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dataset" })).toHaveTextContent("Telco Customer Churn");
    });
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Telco Customer Churn"));

    const summaryBodyField = screen.getByLabelText("Problem summary body") as HTMLTextAreaElement;
    expect(summaryBodyField).toHaveAttribute("maxLength", "600");
    expect(summaryBodyField).not.toHaveAttribute("maxLength", "300");

    const beyondOldLimitValue = "x".repeat(450);
    fireEvent.change(summaryBodyField, { target: { value: beyondOldLimitValue } });
    expect(summaryBodyField).toHaveValue(beyondOldLimitValue);
    expect(screen.getByText(`${beyondOldLimitValue.length} / 600`)).toBeInTheDocument();

    const atNewLimitValue = "y".repeat(600);
    fireEvent.change(summaryBodyField, { target: { value: atNewLimitValue } });
    expect(summaryBodyField).toHaveValue(atNewLimitValue);
    expect(screen.getByText(`600 / 600`)).toBeInTheDocument();
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

  it("removes internal draft terminology from Dataset Admin's operator-facing load and publish feedback (Project Spec S0060)", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    expect(screen.queryByText("Draft loaded")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Editable fields were populated from the private/admin draft endpoint."),
    ).not.toBeInTheDocument();
    expect(forbiddenDraftTermsPresent()).toEqual([]);

    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Edited subtitle" } });
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled());
    expect(screen.queryByText("Draft saved through the profile draft model.")).not.toBeInTheDocument();
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
    const switchInput = await screen.findByRole("checkbox", { name: "Visible Publicly" });
    await waitFor(() => expect(switchInput).toBeChecked());
    fireEvent.click(switchInput);
    await waitFor(() => expect(switchInput).not.toBeChecked());

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

    // Project Spec S0110: same pending-legacy-migration combined outcome as
    // the other Subtitle-only publish-failure tests above -- still safe,
    // internal-terminology-free feedback.
    expect(
      await screen.findByText("Inference Form saved; Dataset Detail publication failed."),
    ).toBeInTheDocument();
    expect(forbiddenDraftTermsPresent()).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Project Spec S0098: deterministic predict-view authoring rebinding
  // -------------------------------------------------------------------------

  it("preserves a currently valid bound_predict_view_id instead of overriding it", async () => {
    // Project Spec S0100: the normal (single-eligible-view) path never shows
    // the manual "Bound predict view" select. Project Spec S0104 also
    // removes the read-only badge that used to confirm the resolved view --
    // proving the correct view was silently bound now requires observing
    // that the customization bootstrap actually succeeds, since the fetch
    // mock only serves that endpoint for the exact real viewId.
    const fetchMock = installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Field bank")).toBeInTheDocument();
    expect(screen.queryByText("Churn risk overview")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`),
      ),
    ).toBe(true);
  });

  it("deterministically selects the sole eligible predict view when no binding exists yet", async () => {
    const fetchMock = installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    await waitFor(() => expect(screen.getByLabelText("Field bank")).toBeInTheDocument());
    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    expect(screen.queryByText("Churn risk overview")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`),
      ),
    ).toBe(true);
  });

  it("repairs a stale bound_predict_view_id by selecting the sole eligible view", async () => {
    // A stale id can legitimately be another dataset's view_id left behind by
    // an earlier rename/rebind -- GET /datasets/{slug}/views already scopes
    // eligible views to this dataset server-side, so it is simply absent
    // from the eligible list either way, and the rebind default must repair
    // it the same as any other stale reference (never select it, never
    // leave it bound). The now-hidden normal-path select can no longer be
    // inspected for the stale option directly, and Project Spec S0104 also
    // removed the badge that used to show the resolved view -- the
    // customization bootstrap succeeding (it can only succeed for the real
    // sole eligible viewId) proves the stale id was never selected.
    const fetchMock = installFetchMock({ boundPredictViewIdOverride: "some-other-datasets-view" });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    await waitFor(() => expect(screen.getByLabelText("Field bank")).toBeInTheDocument());
    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`),
      ),
    ).toBe(true);
  });

  it("keeps the predict view unbound when zero eligible views exist", async () => {
    installFetchMock({ noExistingDraft: true, viewsOverride: [] });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    // Project Spec S0100: with zero eligible predict views, there is no
    // select to render at all -- an explicit governed blocked state instead
    // of a visible-but-empty selector.
    expect(await screen.findByText("No predict view bound")).toBeInTheDocument();
    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    // Project Spec S0103: with no bound view there is no customization draft
    // to persist at all, so the shared workspace toolbar Publish changes
    // button has nothing customization-related to enable it either.
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();
  });

  it("requires an explicit user choice when multiple eligible views exist and no valid binding exists", async () => {
    installFetchMock({
      noExistingDraft: true,
      viewsOverride: [
        { view_id: "churn-risk-overview", display: { title: "Churn Risk Overview" } },
        { view_id: "retention-outlook", display: { title: "Retention Outlook" } },
      ],
    });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    await screen.findByLabelText("Bound predict view");
    expect(screen.getByLabelText("Bound predict view")).toHaveValue("");
  });

  it("applies the deterministic rebind as a draft-only default that never implicitly enables or triggers a publish", async () => {
    // resolvedBoundPredictViewIdDefault is applied identically to both the
    // current draftForm and the workspace toolbar's own dirty-state
    // baseline (workspacePublishSnapshotForm), so the deterministic-only
    // rebind never by itself enables Publish changes -- only a real operator
    // edit does. This is a page-load-only default, never an implicit
    // mutation of the published snapshot.
    installFetchMock({ noExistingDraft: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    // Field bank only renders once boundPredictViewId resolves (the
    // customization bootstrap effect gates on it), so its presence already
    // confirms the deterministic single-eligible-view rebind applied.
    await waitFor(() => expect(screen.getByLabelText("Field bank")).toBeInTheDocument());

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Project Spec S0099: contract-driven automatic bootstrap and
  // compatibility-aware customization overlay
  // -------------------------------------------------------------------------

  it("automatically reaches a rendered builder on tab entry with no Load customization control anywhere on the page", async () => {
    installFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    expect(screen.queryByRole("button", { name: "Load customization" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Public form layout")).toBeInTheDocument();
  });

  it("builds a clean contract-derived draft when no customization exists (absence bootstrap)", async () => {
    installFetchMock({ customizationAbsent: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    const layoutPanel = await screen.findByLabelText("Public form layout");
    // Project Spec S0104: every canonical contract field with no compatible
    // persisted field-hint decision defaults per required/optional -- the
    // shared contract fixture's fields are both optional (unless overridden
    // by requiredFieldOverride), so a clean base draft places them in the
    // Field bank, not visible in the Public form layout's No subgroup zone.
    const bankZone = document.querySelector('[data-customization-drop-zone="bank"]') as HTMLElement;
    expect(within(bankZone).getByText("tenure")).toBeInTheDocument();
    expect(within(bankZone).getByText("MonthlyCharges")).toBeInTheDocument();
    expect(within(layoutPanel).queryByText("Tenure")).not.toBeInTheDocument();
  });

  it("places a required field in No subgroup and an optional field in the Field bank for a base draft with no compatible customization", async () => {
    installFetchMock({ customizationAbsent: true, requiredFieldOverride: "tenure" });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    await screen.findByLabelText("Public form layout");
    const noSubgroupZone = document.querySelector('[data-customization-drop-zone="no-subgroup"]') as HTMLElement;
    const bankZone = document.querySelector('[data-customization-drop-zone="bank"]') as HTMLElement;
    expect(within(noSubgroupZone).getByText("tenure")).toBeInTheDocument();
    expect(within(bankZone).getByText("MonthlyCharges")).toBeInTheDocument();
    expect(screen.queryByText(/required field.*still in the bank/i)).not.toBeInTheDocument();
  });

  it("applies the required/optional default rule only to contract fields absent from a compatible overlay, preserving the overlay's own placements", async () => {
    installFetchMock({
      extraContractFields: [
        { name: "PaperlessBilling", label: "Paperless billing", optional: false },
        { name: "Contract", label: "Contract type", optional: true },
      ],
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    // The shared compatible customization's own placements (tenure/
    // MonthlyCharges grouped) are untouched by the new fields' defaults.
    expect(within(screen.getByLabelText("Account profile")).getByText("tenure")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Charges")).getByText("MonthlyCharges")).toBeInTheDocument();

    // The overlay never covered either new field, so each follows the
    // required/optional default rule independently of the other fields.
    const noSubgroupZone = document.querySelector('[data-customization-drop-zone="no-subgroup"]') as HTMLElement;
    const bankZone = document.querySelector('[data-customization-drop-zone="bank"]') as HTMLElement;
    expect(within(noSubgroupZone).getByText("PaperlessBilling")).toBeInTheDocument();
    expect(within(bankZone).getByText("Contract")).toBeInTheDocument();
  });

  it("does not persist a customization merely by opening the tab", async () => {
    const fetchMock = installFetchMock({ customizationAbsent: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("Public form layout");

    expect(
      fetchMock.mock.calls.some(
        (call) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("ignores an incompatible historical customization, renders the clean contract-derived builder, and shows a sanitized warning", async () => {
    installFetchMock({ customizationIncompatible: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(await screen.findByText("Historical customization not applied")).toBeInTheDocument();
    // Raw registry error internals (codes, field paths) must never surface
    // verbatim in the operator-facing warning panel.
    expect(screen.queryByText(/UNKNOWN_FIELD_REFERENCE/)).not.toBeInTheDocument();

    const layoutPanel = screen.getByLabelText("Public form layout");
    // Project Spec S0104: the ignored-overlay base draft follows the same
    // required/optional default rule as the absence-bootstrap draft -- both
    // shared contract fields are optional, so they land in the Field bank.
    const bankZone = document.querySelector('[data-customization-drop-zone="bank"]') as HTMLElement;
    expect(within(bankZone).getByText("tenure")).toBeInTheDocument();
    expect(within(layoutPanel).queryByText("Tenure")).not.toBeInTheDocument();

    // Project Spec S0103: the builder is not blocked -- a new customization
    // can still be persisted through the shared workspace toolbar Publish
    // changes action once an actual edit dirties it (nothing is dirty yet
    // immediately after this clean bootstrap).
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    expect(publishButton).toBeEnabled();
  });

  it("shows a Retry control only after an actual load failure, and Retry recovers the builder", async () => {
    installFetchMock({ customizationLoadFailsOnce: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(await screen.findByText("Customization unavailable")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "Retry" });

    fireEvent.click(retryButton);

    expect(await screen.findByLabelText("Field bank")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("ignores a late customization response from a superseded dataset/view selection", async () => {
    // Project Spec S0100 hides the "Bound predict view" select for the
    // normal single-eligible-view path -- keep it visible here (a second
    // eligible view makes this the governed multi-view case) purely as the
    // test mechanism to force the identity change this test needs; the
    // underlying AbortController/monotonic-request-identity behavior being
    // proven is unchanged.
    const fetchMock = installFetchMock({
      customizationLoadDeferredOnce: true,
      viewsOverride: [
        { view_id: viewId, display: { title: "Churn risk overview" } },
        { view_id: "retention-outlook", display: { title: "Retention Outlook" } },
      ],
    });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByText("Loading customization...");

    // Unbind the view while the first request is still pending -- this must
    // become the current, no-longer-loading state; the still-pending
    // response must never resolve into the current draft afterward.
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: "" } });
    expect(await screen.findByText("No predict view bound")).toBeInTheDocument();

    fetchMock.releaseDeferredCustomizationLoad();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByText("No predict view bound")).toBeInTheDocument();
    expect(screen.queryByText("Customization loaded")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------
  // Project Spec S0121: private authoring-context read model availability
  // separation (GET /admin/datasets/{slug}/authoring-context).
  // ---------------------------------------------------------------------

  it("shows a Predict views unavailable message with Retry when the authoring-context request fails, and Retry recovers the tab (Project Spec S0121)", async () => {
    installFetchMock({ authoringContextTransportFailureOnce: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(await screen.findByText("Predict views unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("The private authoring context could not load the eligible Predict Views for this dataset."),
    ).toBeInTheDocument();
    // A transport failure must never render the true empty state.
    expect(screen.queryByText("No predict views are available for this dataset yet.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    // authoringContextTransportFailureOnce auto-clears after the first
    // request, so Retry's re-fetch succeeds and the normal single-view
    // customization builder renders.
    expect(await screen.findByLabelText("Field bank")).toBeInTheDocument();
    expect(screen.queryByText("Predict views unavailable")).not.toBeInTheDocument();
  });

  it("renders a distinct unavailable message, never the true empty state, when only the views resource is bounded-unavailable (Project Spec S0121)", async () => {
    installFetchMock({ viewsResourceUnavailable: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(await screen.findByText("Predict views unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("The private authoring context could not load the eligible Predict Views for this dataset."),
    ).toBeInTheDocument();
    expect(screen.queryByText("No predict views are available for this dataset yet.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add subgroup" })).not.toBeInTheDocument();
  });

  it("keeps a bounded contract-unavailable authoring resource distinct from views availability (Project Spec S0121)", async () => {
    installFetchMock({ contractResourceUnavailable: true });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    // Views stayed ready (one eligible view), so the tab never renders its
    // own views-unavailable branch -- only the pre-existing contract-
    // specific notice fires, proving the two bounded failure identities
    // are never conflated with each other.
    expect(await screen.findByText("Public contract unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Predict views unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText("No predict views are available for this dataset yet.")).not.toBeInTheDocument();
  });

  it("ignores a late authoring-context response from a superseded dataset selection (Project Spec S0121)", async () => {
    const otherSlug = "energy-consumption-forecast";
    const otherViewId = "load-forecast-overview";
    const firstSlugResponseHolder: { release: (() => void) | null } = { release: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: datasetSlug,
              title: "Telco Customer Churn",
              display_title: null,
              summary: "s",
              domain: "telecom",
              tags: [],
              active_release: "release-20260619-001",
              publication_status: "ready",
              last_updated: "2026-06-19T12:00:00Z",
            },
            {
              dataset_slug: otherSlug,
              title: "Energy Consumption Forecast",
              display_title: null,
              summary: "s",
              domain: "energy",
              tags: [],
              active_release: "release-20260701-001",
              publication_status: "ready",
              last_updated: "2026-07-01T12:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
        // Deliberately slow/deferred: resolves only after the operator has
        // already switched to otherSlug below, so this response must never
        // be allowed to overwrite otherSlug's own authoring context.
        return new Promise((resolve) => {
          firstSlugResponseHolder.release = () =>
            resolve(
              jsonResponse({
                dataset_slug: datasetSlug,
                active_release: "release-20260619-001",
                dataset: { status: "ready", data: { dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", tags: [] } },
                context: { status: "ready", data: {} },
                contract: { status: "ready", data: { contract: { schema_version: "1.0.0", features: [] }, result_contract: { status: "unavailable", reason: "n/a" } } },
                metrics: { status: "ready", data: {} },
                visualizations: { status: "ready", data: {} },
                views: { status: "ready", data: [{ view_id: viewId, display: { title: "Churn risk overview" } }] },
              }),
            );
        });
      }
      if (url.endsWith(`/admin/datasets/${otherSlug}/authoring-context`)) {
        return jsonResponse({
          dataset_slug: otherSlug,
          active_release: "release-20260701-001",
          dataset: { status: "ready", data: { dataset_slug: otherSlug, title: "Energy Consumption Forecast", summary: "s", domain: "energy", tags: [] } },
          context: { status: "ready", data: {} },
          contract: { status: "ready", data: { contract: { schema_version: "1.0.0", features: [] }, result_contract: { status: "unavailable", reason: "n/a" } } },
          metrics: { status: "ready", data: {} },
          visualizations: { status: "ready", data: {} },
          views: { status: "ready", data: [{ view_id: otherViewId, display: { title: "Load Forecast Overview" } }] },
        });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) || url.endsWith(`/admin/datasets/${otherSlug}/profile-draft`)) {
        return jsonResponse({ draft_exists: false, profile: null });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`) || url.endsWith(`/admin/datasets/${otherSlug}/publication-state`)) {
        return jsonResponse({}, 404);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdminPage();

    const selector = await screen.findByRole("button", { name: "Dataset" });
    await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

    fireEvent.click(selector);
    fireEvent.click(screen.getByRole("option", { name: "Energy Consumption Forecast" }));

    fireEvent.click(await screen.findByRole("tab", { name: "Inference Form" }));
    await waitFor(() => expect(screen.getByLabelText("Submit button label")).toBeInTheDocument());

    // Now let the superseded first-dataset (telco) authoring-context
    // response resolve -- it must be rejected outright and must never
    // overwrite otherSlug's already-current eligible views.
    firstSlugResponseHolder.release?.();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByText("Predict views unavailable")).not.toBeInTheDocument();
  });

  it("requests only the private authoring-context endpoint for ReadOnlyData, never the six retired public technical read routes (Project Spec S0121)", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("Field bank");

    const calledUrls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(calledUrls.some((url) => url.endsWith(`/datasets/${datasetSlug}`))).toBe(false);
    expect(calledUrls.some((url) => url.includes(`/datasets/${datasetSlug}/context`))).toBe(false);
    expect(calledUrls.some((url) => url.includes(`/datasets/${datasetSlug}/contract`))).toBe(false);
    expect(calledUrls.some((url) => url.includes(`/datasets/${datasetSlug}/metrics`))).toBe(false);
    expect(calledUrls.some((url) => url.includes(`/datasets/${datasetSlug}/visualizations`))).toBe(false);
    expect(calledUrls.some((url) => url.endsWith(`/datasets/${datasetSlug}/views`))).toBe(false);
    expect(calledUrls.some((url) => url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`))).toBe(true);
  });

  it("keeps automatic reload consistent after a successful save", async () => {
    // See the note above -- a second eligible view keeps the governed select
    // available as the mechanism to force a genuine reload.
    const fetchMock = installFetchMock({
      customizationAbsent: true,
      trackCustomizationSaves: true,
      viewsOverride: [
        { view_id: viewId, display: { title: "Churn risk overview" } },
        { view_id: "retention-outlook", display: { title: "Retention Outlook" } },
      ],
    });
    renderAdminPage();

    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("Public form layout");

    // Project Spec S0103: persistence now happens only through the shared
    // workspace toolbar Publish changes action -- add a subgroup so the
    // customization is actually dirty before publishing it.
    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    // Force a genuine reload via identity change (no manual reload control
    // exists) and confirm the automatically reloaded state matches what the
    // save already produced -- a compatible overlay, not an absence.
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: viewId } });
    await waitFor(() =>
      expect(screen.getByLabelText("Public form layout").querySelectorAll(".dataset-admin-builder-card")).toHaveLength(1),
    );

    const putCalls = fetchMock.mock.calls.filter(
      (call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls).toHaveLength(1);
  });

  // -------------------------------------------------------------------------
  // Project Spec S0103: Inference Form customization integrated into the
  // workspace Publish changes dirty-state and orchestration
  // -------------------------------------------------------------------------

  it("enables the workspace toolbar Publish changes button when Inference Form customization is edited, and disables it again when reverted to the loaded baseline", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    const accountCard = screen.getByText("Account profile").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(accountCard).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(accountCard).getByLabelText("Label"), { target: { value: "Account profile edited" } });
    fireEvent.click(within(accountCard).getByRole("button", { name: "Save subgroup" }));

    expect(publishButton).toBeEnabled();

    const editedCard = screen.getByText("Account profile edited").closest(".dataset-admin-builder-card") as HTMLElement;
    fireEvent.click(within(editedCard).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(editedCard).getByLabelText("Label"), { target: { value: "Account profile" } });
    fireEvent.click(within(editedCard).getByRole("button", { name: "Save subgroup" }));

    expect(publishButton).toBeDisabled();
  });

  it("sends only the dirty resource's request when only Inference Form customization, then only Public Content, is dirty", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    expect(publishButton).toBeEnabled();

    const callsBeforeCustomizationOnly = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());
    const customizationOnlyCalls = fetchMock.mock.calls.slice(callsBeforeCustomizationOnly);
    expect(
      customizationOnlyCalls.some(
        (call) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      ),
    ).toBe(true);
    expect(
      customizationOnlyCalls.some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
    ).toBe(false);
    await waitFor(() => expect(publishButton).toBeDisabled());

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Profile-only edit" } });
    expect(publishButton).toBeEnabled();

    const callsBeforeProfileOnly = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());
    const profileOnlyCalls = fetchMock.mock.calls.slice(callsBeforeProfileOnly);
    expect(profileOnlyCalls.some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`))).toBe(
      true,
    );
    expect(
      profileOnlyCalls.some(
        (call) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("persists customization before publishing the profile when both are dirty, and reports a single combined success", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Combined edit" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeEnabled();

    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const relevantCalls = fetchMock.mock.calls
      .slice(callsBefore)
      .filter(
        (call) =>
          (String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT") ||
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`),
      );
    expect(relevantCalls).toHaveLength(2);
    expect(String(relevantCalls[0][0])).toContain("/customization");
    expect(String(relevantCalls[1][0])).toContain("/publish");

    await waitFor(() => expect(publishButton).toBeDisabled());
  });

  it("prevents profile publication when the customization request itself fails, leaving Publish changes enabled", async () => {
    const fetchMock = installFetchMock({ rejectCustomizationSave: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Should not publish" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });

    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);

    expect(await screen.findByText("Inference Form could not be saved.")).toBeInTheDocument();
    expect(publishButton).toBeEnabled();
    expect(
      fetchMock.mock.calls
        .slice(callsBefore)
        .some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
    ).toBe(false);
  });

  it("updates only the customization baseline when customization succeeds but profile publication fails, and a retry sends only the remaining profile request", async () => {
    const fetchMock = installFetchMock({ rejectPublish: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Partial success edit" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });

    const callsBeforeFirst = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);

    expect(await screen.findByText("Inference Form saved; Dataset Detail publication failed.")).toBeInTheDocument();
    expect(publishButton).toBeEnabled();

    const firstAttemptCalls = fetchMock.mock.calls.slice(callsBeforeFirst);
    expect(
      firstAttemptCalls.some(
        (call) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      ),
    ).toBe(true);
    expect(
      firstAttemptCalls.some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
    ).toBe(true);

    // Retry: the customization is no longer dirty (its baseline updated on
    // the earlier success), so only the still-dirty profile request is sent.
    const callsBeforeRetry = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls
          .slice(callsBeforeRetry)
          .some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
      ).toBe(true),
    );
    expect(
      fetchMock.mock.calls
        .slice(callsBeforeRetry)
        .some(
          (call) =>
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
            (call[1] as RequestInit | undefined)?.method === "PUT",
        ),
    ).toBe(false);
  });

  // ---------------------------------------------------------------------
  // Project Spec S0110: submit-action copy ownership moves from the Result
  // Card tab to the Inference Form tab's predict-view customization.
  // ---------------------------------------------------------------------

  it("renders Submit button label on the Inference Form tab, seeded from the legacy profile value, and no longer on the Result Card tab (Project Spec S0110)", async () => {
    installFetchMock();
    renderAdminPage();
    await loadDraftAndCustomization();

    const submitLabelField = screen.getByLabelText("Submit button label") as HTMLInputElement;
    expect(submitLabelField).toBeEnabled();
    // Seeded from the shared fixture's legacy result_card.submit_button_label
    // ("Run prediction") since the shared customization fixture carries no
    // view_copy.submit_button_label of its own yet -- a pending migration
    // candidate, not a storage mutation.
    expect(submitLabelField.value).toBe("Run prediction");

    fireEvent.click(screen.getByRole("tab", { name: "Result Card" }));
    expect(screen.queryByLabelText("Submit button label")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Positive-class probability label")).toBeInTheDocument();
  });

  it("disables Submit button label when no predict view is bound (Project Spec S0110)", async () => {
    // A single eligible view is silently auto-bound (Project Spec S0100), so
    // proving genuinely no-view-bound requires zero eligible views.
    installFetchMock({ viewsOverride: [], boundPredictViewIdOverride: "" });
    renderAdminPage();
    await loadDraftOnly();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    expect(await screen.findByLabelText("Submit button label")).toBeDisabled();
  });

  it("editing Submit button label enables Publish changes, and reverting it disables Publish changes when no other change exists (Project Spec S0110)", async () => {
    // An already-persisted customization value means no migration seed
    // applies, isolating this test to a plain field edit/revert.
    installFetchMock({
      customizationOverride: { ...customization, view_copy: { submit_button_label: "Existing label" } },
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    const submitLabelField = screen.getByLabelText("Submit button label");
    expect(submitLabelField).toHaveValue("Existing label");
    fireEvent.change(submitLabelField, { target: { value: "New label" } });
    expect(publishButton).toBeEnabled();

    fireEvent.change(submitLabelField, { target: { value: "Existing label" } });
    expect(publishButton).toBeDisabled();
  });

  it("publishing customization writes view_copy.submit_button_label while preserving other existing view_copy fields (Project Spec S0110)", async () => {
    const fetchMock = installFetchMock({
      trackCustomizationSaves: true,
      customizationOverride: {
        ...customization,
        view_copy: { heading: "Existing heading", description: "Existing description" },
      },
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.change(screen.getByLabelText("Submit button label"), { target: { value: "Estimate churn risk" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const putCall = fetchMock.mock.calls.find(
      (call) =>
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
        (call[1] as RequestInit | undefined)?.method === "PUT",
    );
    const body = JSON.parse(String((putCall?.[1] as RequestInit).body)) as { view_copy?: Record<string, string> };
    expect(body.view_copy).toEqual({
      heading: "Existing heading",
      description: "Existing description",
      submit_button_label: "Estimate churn risk",
    });
  });

  it("persists the migrated legacy submit label to customization before publishing an unrelated profile edit (Project Spec S0110)", async () => {
    // Shared fixture: publicProfile.result_card.submit_button_label =
    // "Run prediction" (legacy), and the shared customization fixture
    // carries no view_copy.submit_button_label yet -- a pending migration
    // even though only the unrelated Subtitle field is edited below.
    const fetchMock = installFetchMock({ trackCustomizationSaves: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Unrelated edit" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    fireEvent.click(publishButton);

    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const relevantCalls = fetchMock.mock.calls.filter(
      (call) =>
        (String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT") ||
        String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`),
    );
    expect(relevantCalls).toHaveLength(2);
    expect(String(relevantCalls[0][0])).toContain("/customization");
    expect(String(relevantCalls[1][0])).toContain("/publish");

    const customizationBody = JSON.parse(String((relevantCalls[0][1] as RequestInit).body)) as {
      view_copy?: Record<string, string>;
    };
    expect(customizationBody.view_copy?.submit_button_label).toBe("Run prediction");

    const profileBody = JSON.parse(String((relevantCalls[1][1] as RequestInit).body)) as {
      result_card?: Record<string, unknown>;
    };
    // New profile publications never emit the legacy field, even on the
    // very publish that resolves the migration.
    expect(profileBody.result_card?.submit_button_label).toBeUndefined();
  });

  it("blocks profile publication when the pending legacy migration's customization persist fails, leaving legacy copy intact and retry possible (Project Spec S0110)", async () => {
    const fetchMock = installFetchMock({ rejectCustomizationSave: true });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Public Content" }));
    fireEvent.change(screen.getByLabelText("Subtitle"), { target: { value: "Should not publish" } });

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(publishButton);

    expect(await screen.findByText("Inference Form could not be saved.")).toBeInTheDocument();
    expect(publishButton).toBeEnabled();
    expect(
      fetchMock.mock.calls
        .slice(callsBefore)
        .some((call) => String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`)),
    ).toBe(false);
    // Retry remains possible: Publish changes is enabled again (asserted
    // above) and clicking it re-attempts the same customization-first
    // ordering rather than becoming permanently blocked.
  });

  it("Live Preview's Inference Form submit button reflects the customization draft's Submit button label immediately, and stays enabled while the result contract is available (Project Spec S0110, S0143)", async () => {
    installFetchMock({
      customizationOverride: { ...customization, view_copy: { submit_button_label: "Estimate churn risk" } },
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    // Project Spec S0120: the Admin-only Inference Form now lives inside the
    // shared surface's own Inference tab (Overview is selected by default),
    // rather than being flatly visible below the header.
    fireEvent.click(within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", { name: "Inference" }));
    const initialPreviewButton = screen.getByRole("button", { name: "Estimate churn risk" });
    // Project Spec S0143: this is now the real, executable InferenceForm --
    // submission is enabled whenever the active release's result contract
    // is available, never unconditionally disabled the way the old
    // preview-mode composition always was.
    expect(initialPreviewButton).toBeEnabled();

    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    fireEvent.change(screen.getByLabelText("Submit button label"), { target: { value: "Updated live label" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    fireEvent.click(within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", { name: "Inference" }));
    expect(screen.getByRole("button", { name: "Updated live label" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Estimate churn risk" })).not.toBeInTheDocument();
  });

  it("resets the customization baseline on a stale-request-safe reload so a discarded edit does not leave the reloaded view appearing dirty", async () => {
    installFetchMock({
      viewsOverride: [
        { view_id: viewId, display: { title: "Churn risk overview" } },
        { view_id: "retention-outlook", display: { title: "Retention Outlook" } },
      ],
    });
    renderAdminPage();
    await loadDraftAndCustomization();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    expect(publishButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Add subgroup" }));
    expect(publishButton).toBeEnabled();

    // Reload the same view without publishing -- the fresh fetch
    // re-establishes the baseline from the real backend record, discarding
    // the local, unpublished subgroup addition and its dirty flag with it.
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Bound predict view"), { target: { value: viewId } });

    await waitFor(() => expect(publishButton).toBeDisabled());
  });

  // Project Spec S0143: the Dataset Detail Live Preview Inference panel now
  // owns one real, executable InferenceForm lifecycle backed by the private
  // Admin inference route, replacing the previous non-executing preview
  // form plus synthetic scenario-driven Result Card.
  describe("Live Preview private inference execution (Project Spec S0143)", () => {
    function openLivePreviewInference() {
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(
        within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", {
          name: "Inference",
        }),
      );
    }

    it("applies private active-release numeric guidance only to the Live Preview form (Project Spec S0148)", async () => {
      installFetchMock({
        inferenceGuidance: [
          { field_name: "tenure", required: false, numeric_domain: { min: 18.25, max: 118.75 } },
        ],
      });
      renderAdminPage();
      await loadDraftAndCustomization();
      openLivePreviewInference();

      const input = await screen.findByLabelText("Tenure");
      expect(input).toHaveAttribute("min", "18.25");
      expect(input).toHaveAttribute("max", "118.75");
      expect(input).toHaveAttribute("step", "any");
      expect(screen.getByText("Accepted range: 18.25 to 118.75.")).toBeInTheDocument();
    });

    it("submits to the private Admin inference route (never the public route) and renders exactly one shared success Result Card", async () => {
      const fetchMock = installFetchMock();
      const { container } = renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInference();

      // Starts at the complete 0% projection, with no duplicate synthetic
      // Result Card anywhere alongside the functional form.
      expect(container.querySelectorAll(".inference-result")).toHaveLength(1);
      expect(
        screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      const callsBeforeSubmit = fetchMock.mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));

      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();
      expect(container.querySelectorAll(".inference-result")).toHaveLength(1);

      const inferenceCalls = fetchMock.mock.calls
        .slice(callsBeforeSubmit)
        .filter((call) => (call[1] as RequestInit | undefined)?.method === "POST" && String(call[0]).includes("/inference"));
      expect(inferenceCalls).toHaveLength(1);
      expect(String(inferenceCalls[0][0])).toContain(`/admin/datasets/${datasetSlug}/inference`);

      // No call to the public inference route was ever made from Admin.
      expect(
        fetchMock.mock.calls.some(
          (call) => String(call[0]).endsWith(`/datasets/${datasetSlug}/inference`) && !String(call[0]).includes("/admin/"),
        ),
      ).toBe(false);
    });

    it("renders the existing shared submitting state while the private request is in flight", async () => {
      const fetchMock = installFetchMock({ adminInferenceDeferredOnce: true });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInference();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));

      expect(await screen.findByText("Generating prediction…")).toBeInTheDocument();

      fetchMock.releaseDeferredAdminInference();
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();
    });

    it("renders the shared safe error state for a bounded private-route failure and keeps the form usable for retry", async () => {
      installFetchMock({ adminInferenceErrorCode: "INFERENCE_FAILURE" });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInference();

      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The prediction service is temporarily unavailable. Please try again later.",
      );
      expect(screen.getByRole("button", { name: /Run prediction/ })).toBeEnabled();
    });

    it("preserves the result while switching Overview ↔ Inference ↔ Documentation, without a second form or Result Card", async () => {
      installFetchMock();
      const { container } = renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInference();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      const detailTabs = within(screen.getByRole("tablist", { name: "Dataset detail sections" }));
      fireEvent.click(detailTabs.getByRole("tab", { name: "Overview" }));
      fireEvent.click(detailTabs.getByRole("tab", { name: "Inference" }));

      expect(
        screen.getByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();
      expect(container.querySelectorAll(".inference-result")).toHaveLength(1);
      expect(container.querySelectorAll(".public-inference-form__form")).toHaveLength(1);
    });
  });

  // Project Spec S0144: pure unit coverage for the audit correlation/
  // retention/formatting model, exercised directly (no DOM, no network, no
  // wall-clock time) so the attempt-correlation invariants -- including
  // duplicate-terminal and unmatched-terminal suppression, which are not
  // reachable through the real InferenceForm's own serialized-submission UI
  // -- are proven deterministically.
  describe("Publishing console Live Preview inference session audit model (Project Spec S0144)", () => {
    const auditSlug = "audit-model-dataset";

    function successSummary(
      overrides: Partial<{ predictedPositive: boolean; positiveClassProbability: number; modelDisplayName?: string }> = {},
    ) {
      return {
        predictedPositive: true,
        positiveClassProbability: 0.82,
        modelDisplayName: "Retention model",
        ...overrides,
      };
    }

    it("starts with no records and renders no console lines (no-event baseline)", () => {
      const state = emptyLiveInferenceAuditState(auditSlug);
      expect(state.records).toEqual([]);
      expect(liveInferenceAuditConsoleLines(state.records)).toEqual([]);
    });

    it("renders a started -> succeeded lifecycle as one INFO line and one OK line sharing attempt #1", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "succeeded",
        successSummary({ predictedPositive: false, positiveClassProbability: 0.18, modelDisplayName: "Gradient Boosting" }),
      );

      expect(state.records.map((record) => ({ attemptSequence: record.attemptSequence, kind: record.kind }))).toEqual([
        { attemptSequence: 1, kind: "started" },
        { attemptSequence: 1, kind: "succeeded" },
      ]);
      expect(state.activeAttemptSequence).toBeNull();

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines).toEqual([
        { id: expect.any(String), severity: "INFO", text: "Live Preview inference attempt #1 started." },
        {
          id: expect.any(String),
          severity: "OK",
          text: "Live Preview inference attempt #1 completed successfully: negative outcome, positive-class probability 18%, model Gradient Boosting.",
        },
      ]);
    });

    it("renders a started -> validation_failed lifecycle as a bounded generic ERROR line with no raw detail", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed");

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines[1]).toEqual({
        id: expect.any(String),
        severity: "ERROR",
        text: "Live Preview inference attempt #1 was rejected because the submitted fields were invalid.",
      });
    });

    it("renders a started -> execution_failed lifecycle as a bounded generic ERROR line with no raw detail", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "execution_failed");

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines[1]).toEqual({
        id: expect.any(String),
        severity: "ERROR",
        text: "Live Preview inference attempt #1 could not be completed.",
      });
    });

    it("keeps two attempts with identical safe summaries as two distinct lines with different attempt numbers", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());

      const successLines = liveInferenceAuditConsoleLines(state.records).filter((line) => line.severity === "OK");
      expect(successLines).toHaveLength(2);
      expect(successLines[0].text).toBe(
        "Live Preview inference attempt #1 completed successfully: positive outcome, positive-class probability 82%, model Retention model.",
      );
      expect(successLines[1].text).toBe(
        "Live Preview inference attempt #2 completed successfully: positive outcome, positive-class probability 82%, model Retention model.",
      );
      expect(successLines[0].id).not.toBe(successLines[1].id);
    });

    it("ignores a duplicate terminal callback for an attempt already closed instead of creating a second record", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());
      const afterFirstTerminal = state;

      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());

      expect(state).toEqual(afterFirstTerminal);
      expect(state.records).toHaveLength(2);
    });

    it("ignores a terminal callback with no matching active attempt instead of fabricating one", () => {
      const state = emptyLiveInferenceAuditState(auditSlug);
      const afterUnmatchedTerminal = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());

      expect(afterUnmatchedTerminal).toEqual(state);
      expect(afterUnmatchedTerminal.records).toHaveLength(0);
    });

    it("ignores an event captured for a previous dataset once the audit session belongs to a different dataset", () => {
      const currentState = emptyLiveInferenceAuditState("current-dataset");
      const afterStaleEvent = reduceLiveInferenceAuditEvent(currentState, "previous-dataset", "started");

      expect(afterStaleEvent).toEqual(currentState);
      expect(afterStaleEvent.records).toHaveLength(0);
    });

    it("retains at most 50 records, truncating only the oldest, preserving chronological order and monotonic sequencing", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      for (let attempt = 1; attempt <= 26; attempt += 1) {
        state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
        state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", successSummary());
      }

      // 26 attempts * 2 records (one start, one terminal) = 52 raw records;
      // the FIFO limit keeps only the newest 50, so the oldest attempt's
      // pair (attempt #1) is gone but every later attempt survives intact.
      expect(state.records).toHaveLength(50);
      expect(state.records[0]).toMatchObject({ attemptSequence: 2, kind: "started" });
      expect(state.records[state.records.length - 1]).toMatchObject({ attemptSequence: 26, kind: "succeeded" });
      const attemptSequences = state.records.map((record) => record.attemptSequence);
      expect(attemptSequences).toEqual([...attemptSequences].sort((a, b) => a - b));

      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      expect(state.activeAttemptSequence).toBe(27);
    });

    it("omits the probability clause for a non-finite value and the model clause when absent, without ever rendering undefined/NaN", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", {
        predictedPositive: true,
        positiveClassProbability: Number.NaN,
        modelDisplayName: "Retention model",
      });
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "succeeded", {
        predictedPositive: true,
        positiveClassProbability: 0.5,
      });

      const successLines = liveInferenceAuditConsoleLines(state.records).filter((line) => line.severity === "OK");
      expect(successLines[0].text).toBe(
        "Live Preview inference attempt #1 completed successfully: positive outcome, model Retention model.",
      );
      expect(successLines[1].text).toBe(
        "Live Preview inference attempt #2 completed successfully: positive outcome, positive-class probability 50%.",
      );
      expect(successLines.map((line) => line.text).join(" ")).not.toMatch(/undefined|NaN|\[object/);
    });
  });

  describe("Publishing console latest inference visibility boundary (Project Spec S0149)", () => {
    const publicationLine = { id: "publication", severity: "INFO" as const, text: "Dataset selected." };
    const firstInferenceLine = {
      id: "live-inference-audit-2-issue-0",
      severity: "ERROR" as const,
      text: "Monthly charges: the submitted value is outside the accepted domain.",
    };

    function setScrollGeometry(
      consoleElement: HTMLElement,
      geometry: { clientHeight: number; scrollHeight: number; scrollTop: number },
    ) {
      Object.defineProperties(consoleElement, {
        clientHeight: { configurable: true, value: geometry.clientHeight },
        scrollHeight: { configurable: true, value: geometry.scrollHeight },
        scrollTop: { configurable: true, value: geometry.scrollTop, writable: true },
      });
    }

    it("does not reposition a no-history mount", () => {
      const { container } = render(<OperationalConsole latestInferenceLineId={null} lines={[publicationLine]} />);
      const consoleElement = container.querySelector(".dataset-admin-console") as HTMLElement;
      setScrollGeometry(consoleElement, { clientHeight: 100, scrollHeight: 300, scrollTop: 17 });

      expect(consoleElement.scrollTop).toBe(17);
    });

    it("positions a retained-history mount at the last field-level diagnostic without moving focus", () => {
      const focusTarget = document.createElement("button");
      document.body.append(focusTarget);
      focusTarget.focus();

      const scrollHeight = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(300);

      const { container } = render(
        <OperationalConsole
          latestInferenceLineId={firstInferenceLine.id}
          lines={[publicationLine, firstInferenceLine]}
        />,
      );
      const consoleElement = container.querySelector(".dataset-admin-console") as HTMLElement;
      expect(consoleElement.scrollTop).toBe(300);
      expect(document.activeElement).toBe(focusTarget);
      scrollHeight.mockRestore();
    });

    it("follows a new stable inference identity near the bottom but ignores publication-only updates", () => {
      const { container, rerender } = render(
        <OperationalConsole latestInferenceLineId={firstInferenceLine.id} lines={[publicationLine, firstInferenceLine]} />,
      );
      const consoleElement = container.querySelector(".dataset-admin-console") as HTMLElement;
      setScrollGeometry(consoleElement, { clientHeight: 100, scrollHeight: 300, scrollTop: 190 });
      fireEvent.scroll(consoleElement);

      const secondInferenceLine = { ...firstInferenceLine, id: "live-inference-audit-4-issue-0" };
      Object.defineProperty(consoleElement, "scrollHeight", { configurable: true, value: 320 });
      rerender(
        <OperationalConsole
          latestInferenceLineId={secondInferenceLine.id}
          lines={[publicationLine, firstInferenceLine, secondInferenceLine]}
        />,
      );
      expect(consoleElement.scrollTop).toBe(320);

      consoleElement.scrollTop = 123;
      rerender(
        <OperationalConsole
          latestInferenceLineId={secondInferenceLine.id}
          lines={[{ ...publicationLine, text: "Publication state changed." }, firstInferenceLine, secondInferenceLine]}
        />,
      );
      expect(consoleElement.scrollTop).toBe(123);
    });

    it("preserves deliberate historical inspection beyond the documented bottom tolerance", () => {
      const { container, rerender } = render(
        <OperationalConsole latestInferenceLineId={firstInferenceLine.id} lines={[publicationLine, firstInferenceLine]} />,
      );
      const consoleElement = container.querySelector(".dataset-admin-console") as HTMLElement;
      const scrolledUpTop = 300 - 100 - OPERATIONAL_CONSOLE_BOTTOM_TOLERANCE_PX - 1;
      setScrollGeometry(consoleElement, { clientHeight: 100, scrollHeight: 300, scrollTop: scrolledUpTop });
      fireEvent.scroll(consoleElement);

      const repeatedAttemptLine = { ...firstInferenceLine, id: "live-inference-audit-6-issue-0" };
      rerender(
        <OperationalConsole
          latestInferenceLineId={repeatedAttemptLine.id}
          lines={[publicationLine, firstInferenceLine, repeatedAttemptLine]}
        />,
      );
      expect(consoleElement.scrollTop).toBe(scrolledUpTop);
    });
  });

  // Project Spec S0144: DOM-level wiring coverage using the real InferenceForm
  // and the existing fetch-mock infrastructure -- confirms DatasetAdminPage
  // actually owns and renders this audit history in the Publishing console,
  // rather than only exercising the pure model above.
  describe("Publishing console Live Preview inference session audit wiring (Project Spec S0144)", () => {
    function openLivePreviewInferenceTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(
        within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", {
          name: "Inference",
        }),
      );
    }

    function openPublishingTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    }

    function consoleLineTexts(): string[] {
      const panel = screen.getByRole("tabpanel");
      const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
      return Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line")).map((el) => el.textContent ?? "");
    }

    it("shows no Live Preview inference lines in the Publishing console before any inference attempt (no-event baseline)", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftAndCustomization();

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts.some((text) => text.includes("Live Preview inference"))).toBe(false);
      expect(lineTexts.some((text) => text.includes("Dataset selected"))).toBe(true);
    });

    it("appends started + succeeded lines after the existing publication lines, with the required bounded safe result summary", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      const datasetLineIndex = lineTexts.findIndex((text) => text.includes("Dataset selected"));
      const startedIndex = lineTexts.findIndex((text) => text === "[INFO] Live Preview inference attempt #1 started.");
      const succeededIndex = lineTexts.findIndex((text) =>
        text.includes("Live Preview inference attempt #1 completed successfully"),
      );

      expect(datasetLineIndex).toBeGreaterThanOrEqual(0);
      expect(startedIndex).toBeGreaterThan(datasetLineIndex);
      expect(succeededIndex).toBeGreaterThan(startedIndex);
      expect(lineTexts[succeededIndex]).toBe(
        "[OK] Live Preview inference attempt #1 completed successfully: positive outcome, positive-class probability 82%, model Retention model.",
      );
    });

    it("appends a bounded generic ERROR line for a validation-failed attempt, with no raw validation detail", async () => {
      installFetchMock({ adminInferenceErrorCode: "INVALID_PAYLOAD" });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[INFO] Live Preview inference attempt #1 started.");
      expect(lineTexts).toContain(
        "[ERROR] Live Preview inference attempt #1 was rejected because the submitted fields were invalid.",
      );
      expect(lineTexts.some((text) => text.includes("INVALID_PAYLOAD"))).toBe(false);
    });

    it("appends a bounded generic ERROR line for an execution-failed attempt, with no raw backend error", async () => {
      installFetchMock({ adminInferenceErrorCode: "INFERENCE_FAILURE" });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[INFO] Live Preview inference attempt #1 started.");
      expect(lineTexts).toContain("[ERROR] Live Preview inference attempt #1 could not be completed.");
      expect(lineTexts.some((text) => text.includes("INFERENCE_FAILURE"))).toBe(false);
      expect(lineTexts.some((text) => text.includes("The prediction service is temporarily unavailable"))).toBe(false);
    });

    it("keeps the history intact across Live Preview <-> Publishing navigation", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      expect(consoleLineTexts().some((text) => text.includes("attempt #1 completed successfully"))).toBe(true);

      openLivePreviewInferenceTab();
      openPublishingTab();

      expect(consoleLineTexts().some((text) => text.includes("attempt #1 completed successfully"))).toBe(true);
    });

    it("keeps two repeated successful attempts as two distinct console lines rather than collapsing them", async () => {
      installFetchMock();
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" });

      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await waitFor(() => {
        expect(
          screen.getAllByText("82%", { selector: ".binary-classification-result__probability-value" }),
        ).toHaveLength(1);
      });

      openPublishingTab();
      const successLines = consoleLineTexts().filter((text) => text.includes("completed successfully"));
      expect(successLines).toEqual([
        "[OK] Live Preview inference attempt #1 completed successfully: positive outcome, positive-class probability 82%, model Retention model.",
        "[OK] Live Preview inference attempt #2 completed successfully: positive outcome, positive-class probability 82%, model Retention model.",
      ]);
    });

    it("clears the history and restarts attempt numbering after switching to a different dataset, never leaking the previous dataset's lines", async () => {
      const otherSlug = "energy-consumption-forecast";
      const otherViewId = "load-forecast-overview";
      const otherInferenceResult = {
        schema_version: "binary-classification-result.v1",
        problem_type: "binary_classification",
        predicted_class: { class_id: "normal_demand" },
        positive_class: { class_id: "high_demand", event_label: "High demand" },
        positive_class_probability: 0.3,
        class_probabilities: [
          { class_id: "normal_demand", probability: 0.7 },
          { class_id: "high_demand", probability: 0.3 },
        ],
        decision: { threshold: 0.5, predicted_positive: false },
        interpretation: {
          preset: "risk",
          band_id: "low",
          bands: [
            { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
            { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
            { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
          ],
        },
        model_descriptor: { model_family: "gbm", display_name: "Load Forecast Model" },
      };

      function availableResultContract(
        positiveClassId: string,
        positiveLabel: string,
        negativeClassId: string,
        threshold: number,
        modelDisplayName: string,
      ) {
        return {
          status: "available",
          semantics: {
            schema_version: "binary-result-semantics.v1",
            problem_type: "binary_classification",
            result_schema_version: "binary-classification-result.v1",
            primary_output: "positive_class_probability",
            positive_class: { class_id: positiveClassId, event_label: positiveLabel },
            negative_class: { class_id: negativeClassId },
            decision: { threshold },
            interpretation: {
              preset: "risk",
              bands: [
                { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
                { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
                { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
              ],
            },
            model_descriptor: { model_family: "model", display_name: modelDisplayName },
          },
        };
      }

      function authoringContextFor(slug: string, title: string, resolvedViewId: string, resultContract: unknown) {
        return jsonResponse({
          dataset_slug: slug,
          active_release: "release-20260619-001",
          dataset: { status: "ready", data: { dataset_slug: slug, title, summary: "s", domain: "d", tags: [] } },
          context: { status: "ready", data: {} },
          contract: {
            status: "ready",
            data: { contract: { schema_version: "1.0.0", features: [] }, result_contract: resultContract },
          },
          metrics: { status: "ready", data: {} },
          visualizations: { status: "ready", data: {} },
          views: { status: "ready", data: [{ view_id: resolvedViewId, display: { title } }] },
        });
      }

      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: datasetSlug,
                title: "Telco Customer Churn",
                display_title: null,
                summary: "s",
                domain: "telecom",
                tags: [],
                active_release: "release-20260619-001",
                publication_status: "ready",
                last_updated: "2026-06-19T12:00:00Z",
              },
              {
                dataset_slug: otherSlug,
                title: "Energy Consumption Forecast",
                display_title: null,
                summary: "s",
                domain: "energy",
                tags: [],
                active_release: "release-20260701-001",
                publication_status: "ready",
                last_updated: "2026-07-01T12:00:00Z",
              },
            ],
          });
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({
            datasets: [{ dataset_slug: datasetSlug, title: "Telco Customer Churn", summary: "s", domain: "telecom", visibility: "public", tags: [] }],
          });
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
          return authoringContextFor(
            datasetSlug,
            "Telco Customer Churn",
            viewId,
            availableResultContract("churn", "Customer churn", "retained", 0.6, "Retention model"),
          );
        }
        if (url.endsWith(`/admin/datasets/${otherSlug}/authoring-context`)) {
          return authoringContextFor(
            otherSlug,
            "Energy Consumption Forecast",
            otherViewId,
            availableResultContract("high_demand", "High demand", "normal_demand", 0.5, "Load Forecast Model"),
          );
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`) || url.endsWith(`/admin/datasets/${otherSlug}/profile-draft`)) {
          return jsonResponse({ draft_exists: false, profile: null });
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`) || url.endsWith(`/admin/datasets/${otherSlug}/publication-state`)) {
          return jsonResponse({}, 404);
        }
        if (url.endsWith(`/admin/datasets/${datasetSlug}/inference`) && init?.method === "POST") {
          return jsonResponse({ dataset_slug: datasetSlug, result: DEFAULT_ADMIN_INFERENCE_RESULT });
        }
        if (url.endsWith(`/admin/datasets/${otherSlug}/inference`) && init?.method === "POST") {
          return jsonResponse({ dataset_slug: otherSlug, result: otherInferenceResult });
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);

      renderAdminPage();

      const selector = await screen.findByRole("button", { name: "Dataset" });
      await waitFor(() => expect(selector).toHaveTextContent("Telco Customer Churn"));

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: "Submit" }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      expect(consoleLineTexts().some((text) => text.includes("Live Preview inference attempt #1"))).toBe(true);

      fireEvent.click(selector);
      fireEvent.click(screen.getByRole("option", { name: "Energy Consumption Forecast" }));
      await waitFor(() => expect(selector).toHaveTextContent("Energy Consumption Forecast"));

      openPublishingTab();
      expect(consoleLineTexts().some((text) => text.includes("Live Preview inference"))).toBe(false);

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: "Submit" }));
      expect(
        await screen.findByText("30%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[INFO] Live Preview inference attempt #1 started.");
      expect(
        lineTexts.some((text) => text.includes("attempt #2") || text.includes("Telco") || text.includes("Retention model")),
      ).toBe(false);
    });

    it("keeps existing publication-state loading/unavailable status lines while still rendering the current-dataset inference history after them", async () => {
      const fetchMock = installFetchMock({ publicationStateDeferredOnce: true });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      let lineTexts = consoleLineTexts();
      const loadingIndex = lineTexts.findIndex((text) => text.includes("Checking publication state"));
      const startedIndex = lineTexts.findIndex((text) => text.includes("Live Preview inference attempt #1 started"));
      expect(loadingIndex).toBeGreaterThanOrEqual(0);
      expect(startedIndex).toBeGreaterThan(loadingIndex);

      fetchMock.releaseDeferredPublicationState();
      await waitFor(() => {
        lineTexts = consoleLineTexts();
        expect(lineTexts.some((text) => text.includes("Dataset selected"))).toBe(true);
      });
      expect(lineTexts.some((text) => text.includes("Live Preview inference attempt #1 completed successfully"))).toBe(
        true,
      );
    });

    it("keeps rendering the current-dataset inference history when publication state is unavailable", async () => {
      installFetchMock({ publicationStateUnavailable: true });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      const unavailableIndex = lineTexts.findIndex((text) =>
        text.includes("Publication state could not be loaded"),
      );
      const succeededIndex = lineTexts.findIndex((text) => text.includes("completed successfully"));
      expect(unavailableIndex).toBeGreaterThanOrEqual(0);
      expect(succeededIndex).toBeGreaterThan(unavailableIndex);
    });

    it("never exposes a submitted field value or a raw error code in the console DOM", async () => {
      installFetchMock({ adminInferenceErrorCode: "INVALID_PAYLOAD" });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "424242" } });
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const consoleText = consoleLineTexts().join(" ");
      expect(consoleText).not.toContain("424242");
      expect(consoleText).not.toContain("INVALID_PAYLOAD");
    });
  });

  // Project Spec S0147: pure unit coverage for the field-level diagnostics
  // extension to the S0144 audit model -- the console-line projection and
  // the reducer's own independent 20-issue bound, exercised directly (no
  // DOM, no network) alongside the existing S0144 model coverage above.
  describe("Publishing console field-level validation diagnostics model (Project Spec S0147)", () => {
    const auditSlug = "audit-diagnostics-dataset";

    function validationIssue(
      overrides: Partial<{
        field: string;
        fieldLabel: string;
        violation: "missing_required_field" | "type_mismatch" | "domain_violation";
      }> = {},
    ) {
      return { field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" as const, ...overrides };
    }

    it("renders a singular attempt summary followed by one detail line for a single retained issue", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, [
        validationIssue({ field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" }),
      ]);

      expect(liveInferenceAuditConsoleLines(state.records)).toEqual([
        { id: expect.any(String), severity: "INFO", text: "Live Preview inference attempt #1 started." },
        {
          id: expect.any(String),
          severity: "ERROR",
          text: "Live Preview inference attempt #1 was rejected with 1 invalid input.",
        },
        { id: expect.any(String), severity: "ERROR", text: "Tenure: a required value was not submitted." },
      ]);
    });

    it("renders a plural attempt summary with the retained issue count, and one detail line per issue in normalized order", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, [
        validationIssue({ field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" }),
        validationIssue({ field: "MonthlyCharges", fieldLabel: "Monthly charges", violation: "domain_violation" }),
      ]);

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines[1]).toEqual({
        id: expect.any(String),
        severity: "ERROR",
        text: "Live Preview inference attempt #1 was rejected with 2 invalid inputs.",
      });
      expect(lines[2].text).toBe("Tenure: a required value was not submitted.");
      expect(lines[3].text).toBe("Monthly charges: the submitted value is outside the accepted domain.");
    });

    it("renders the required copy for each of the three allowlisted violations", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, [
        validationIssue({ field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" }),
        validationIssue({ field: "MonthlyCharges", fieldLabel: "Monthly charges", violation: "type_mismatch" }),
        validationIssue({ field: "contract_type", fieldLabel: "Contract length", violation: "domain_violation" }),
      ]);

      const detailTexts = liveInferenceAuditConsoleLines(state.records).slice(2).map((line) => line.text);
      expect(detailTexts).toEqual([
        "Tenure: a required value was not submitted.",
        "Monthly charges: the submitted value has the wrong type.",
        "Contract length: the submitted value is outside the accepted domain.",
      ]);
    });

    it("gives every detail line severity ERROR and a unique stable id, distinct across repeated equivalent attempts", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, [validationIssue()]);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, [validationIssue()]);

      const lines = liveInferenceAuditConsoleLines(state.records);
      const detailLines = lines.filter((line) => line.text.startsWith("Tenure:"));
      expect(detailLines).toHaveLength(2);
      expect(detailLines.every((line) => line.severity === "ERROR")).toBe(true);
      expect(detailLines[0].id).not.toBe(detailLines[1].id);

      const summaryLines = lines.filter((line) => line.text.includes("was rejected with"));
      expect(summaryLines[0].text).toContain("attempt #1");
      expect(summaryLines[1].text).toContain("attempt #2");
    });

    it("falls back to the existing generic line when no valid issue remains", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, []);

      expect(liveInferenceAuditConsoleLines(state.records)[1]).toEqual({
        id: expect.any(String),
        severity: "ERROR",
        text: "Live Preview inference attempt #1 was rejected because the submitted fields were invalid.",
      });
    });

    it("bounds a single validation-failure record's nested issue list to 20, independently of the 50-record retention limit", () => {
      const manyIssues = Array.from({ length: 30 }, (_, index) => ({
        field: `field_${index}`,
        fieldLabel: `Field ${index}`,
        violation: "type_mismatch" as const,
      }));
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "validation_failed", undefined, manyIssues);

      const record = state.records.find((r) => r.kind === "validation_failed");
      expect(record?.issues).toHaveLength(20);

      const detailLines = liveInferenceAuditConsoleLines(state.records).filter((line) => line.text.startsWith("Field "));
      expect(detailLines).toHaveLength(20);
    });

    it("never retains validation issues on succeeded or execution_failed records, even if a caller passes them", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "started",
      );
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "succeeded",
        { predictedPositive: true, positiveClassProbability: 0.5 },
        [validationIssue()],
      );
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "execution_failed", undefined, [validationIssue()]);

      const terminalRecords = state.records.filter((record) => record.kind !== "started");
      expect(terminalRecords).toHaveLength(2);
      expect(terminalRecords.every((record) => record.issues === undefined)).toBe(true);
    });
  });

  // Project Spec S0151: pure unit coverage for the runtime-diagnostic
  // extension to the S0144 audit model -- the console-line projection and
  // the reducer's retention rule, exercised directly (no DOM, no network).
  describe("Publishing console runtime diagnostic model (Project Spec S0151)", () => {
    const auditSlug = "audit-runtime-diagnostic-dataset";

    it("renders one additional bounded runtime-diagnostic line immediately after the generic execution_failed line", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "started",
      );
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "execution_failed",
        undefined,
        undefined,
        "RUNTIME_DEPENDENCY_UNAVAILABLE",
      );

      expect(liveInferenceAuditConsoleLines(state.records)).toEqual([
        { id: expect.any(String), severity: "INFO", text: "Live Preview inference attempt #1 started." },
        {
          id: expect.any(String),
          severity: "ERROR",
          text: "Live Preview inference attempt #1 could not be completed.",
        },
        {
          id: expect.any(String),
          severity: "ERROR",
          text: "Runtime diagnostic: a required inference runtime dependency is unavailable.",
        },
      ]);
    });

    it("renders the required deterministic copy for every allowlisted diagnostic code", () => {
      const expectedCopy: Record<string, string> = {
        INFERENCE_BUNDLE_UNAVAILABLE: "Runtime diagnostic: the active release inference bundle is unavailable.",
        MODEL_ARTIFACT_UNAVAILABLE: "Runtime diagnostic: the active release model artifact is unavailable.",
        MODEL_ARTIFACT_HASH_MISMATCH:
          "Runtime diagnostic: the active release model artifact failed integrity verification.",
        RUNTIME_DEPENDENCY_UNAVAILABLE:
          "Runtime diagnostic: a required inference runtime dependency is unavailable.",
        MODEL_DESERIALIZATION_FAILED: "Runtime diagnostic: the active release model could not be loaded.",
        PREDICTION_EXECUTION_FAILED: "Runtime diagnostic: the model could not complete prediction execution.",
        RESULT_VALIDATION_FAILED:
          "Runtime diagnostic: the inference result failed governed result validation.",
        // Project Spec S0152
        RUNTIME_INPUT_CONTRACT_INCONSISTENT:
          "Runtime diagnostic: the active release input contract is inconsistent with the inference bundle.",
      };

      for (const [code, expectedText] of Object.entries(expectedCopy)) {
        let state = emptyLiveInferenceAuditState(auditSlug);
        state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
        state = reduceLiveInferenceAuditEvent(
          state,
          auditSlug,
          "execution_failed",
          undefined,
          undefined,
          code as never,
        );
        const lines = liveInferenceAuditConsoleLines(state.records);
        expect(lines[2].text).toBe(expectedText);
      }
    });

    it("adds no diagnostic line when the executor reports no runtime diagnostic (existing generic-only behavior)", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "execution_failed");

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines).toHaveLength(2);
      expect(lines[1].text).toBe("Live Preview inference attempt #1 could not be completed.");
    });

    it("never retains a runtime diagnostic on succeeded or validation_failed records, even if a caller passes one", () => {
      let state = emptyLiveInferenceAuditState(auditSlug);
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "succeeded",
        { predictedPositive: true, positiveClassProbability: 0.5 },
        undefined,
        "RUNTIME_DEPENDENCY_UNAVAILABLE" as never,
      );
      state = reduceLiveInferenceAuditEvent(state, auditSlug, "started");
      state = reduceLiveInferenceAuditEvent(
        state,
        auditSlug,
        "validation_failed",
        undefined,
        undefined,
        "RUNTIME_DEPENDENCY_UNAVAILABLE" as never,
      );

      const terminalRecords = state.records.filter((record) => record.kind !== "started");
      expect(terminalRecords).toHaveLength(2);
      expect(terminalRecords.every((record) => record.runtimeDiagnosticCode === undefined)).toBe(true);

      const lines = liveInferenceAuditConsoleLines(state.records);
      expect(lines.some((line) => line.text.startsWith("Runtime diagnostic:"))).toBe(false);
    });
  });

  // Project Spec S0147: DOM-level wiring coverage using the real
  // InferenceForm/executeAdminInference path and the fetch-mock's
  // adminInferenceErrors option -- confirms DatasetAdminPage actually
  // normalizes, filters, label-resolves and projects field-level
  // diagnostics into the Publishing console, rather than only exercising
  // the pure model above.
  describe("Publishing console field-level validation diagnostics wiring (Project Spec S0147)", () => {
    function openLivePreviewInferenceTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(
        within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", {
          name: "Inference",
        }),
      );
    }

    function openPublishingTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    }

    function consoleLineTexts(): string[] {
      const panel = screen.getByRole("tabpanel");
      const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
      return Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line")).map((el) => el.textContent ?? "");
    }

    it("renders a bounded attempt summary plus one field-level line per retained issue for a private Admin error response with safe errors[]", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [
          { error_code: "MISSING_REQUIRED_FIELD", field: "tenure", violation: "missing_required_field", message: "raw backend message" },
          { error_code: "DOMAIN_VIOLATION", field: "MonthlyCharges", violation: "domain_violation", message: "raw backend message" },
        ],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[ERROR] Live Preview inference attempt #1 was rejected with 2 invalid inputs.");
      expect(lineTexts).toContain("[ERROR] Tenure: a required value was not submitted.");
      expect(lineTexts).toContain("[ERROR] Monthly charges: the submitted value is outside the accepted domain.");
    });

    it("renders a singular summary for exactly one retained issue", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [{ field: "tenure", violation: "missing_required_field" }],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      expect(consoleLineTexts()).toContain(
        "[ERROR] Live Preview inference attempt #1 was rejected with 1 invalid input.",
      );
    });

    it("prefers a non-blank customization display_label over the contract feature label for a field-level line", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [{ field: "tenure", violation: "domain_violation" }],
        // Overrides the shared fixture's display_label (which happens to
        // equal the contract feature label, "Tenure") with a distinct value,
        // so this test actually distinguishes customization-label
        // precedence from a contract-label fallback rather than passing
        // vacuously.
        customizationOverride: {
          ...customization,
          field_hints: [
            {
              field_name: "tenure",
              display_label: "Customer tenure (yrs)",
              explanatory_copy: "",
              display_order_hint: 1,
              group: "",
            },
          ],
          groups: [],
        },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      expect(consoleLineTexts()).toContain(
        "[ERROR] Customer tenure (yrs): the submitted value is outside the accepted domain.",
      );
    });

    it("falls back to the existing generic line when the reported errors are malformed or unrelated to the active contract", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [
          { field: "", violation: "missing_required_field" },
          { field: "tenure", violation: "some_unknown_violation" },
          { field: "totally_unrelated_field", violation: "type_mismatch" },
        ],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      expect(consoleLineTexts()).toContain(
        "[ERROR] Live Preview inference attempt #1 was rejected because the submitted fields were invalid.",
      );
    });

    it("never exposes a submitted value or a raw backend message in the console DOM alongside field-level diagnostics", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [
          { field: "tenure", violation: "domain_violation", message: "The submitted value 424242 is out of range." },
        ],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.change(screen.getByLabelText(/Tenure/), { target: { value: "424242" } });
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const consoleText = consoleLineTexts().join(" ");
      expect(consoleText).not.toContain("424242");
      expect(consoleText).not.toContain("out of range");
      expect(consoleText).not.toContain("INVALID_PAYLOAD");
    });

    it("keeps repeated attempts with identical field failures distinct through attempt sequence and line ids", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [{ field: "tenure", violation: "missing_required_field" }],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await waitFor(() => {
        expect(screen.getAllByRole("alert")).toHaveLength(1);
      });

      openPublishingTab();
      const detailLines = consoleLineTexts().filter((text) => text.includes("a required value was not submitted."));
      expect(detailLines).toHaveLength(2);
      const summaryLines = consoleLineTexts().filter((text) => text.includes("was rejected with"));
      expect(summaryLines).toEqual([
        "[ERROR] Live Preview inference attempt #1 was rejected with 1 invalid input.",
        "[ERROR] Live Preview inference attempt #2 was rejected with 1 invalid input.",
      ]);
    });

    it("appends field-level diagnostic lines after existing publication lines, in started -> summary -> detail order", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceErrors: [{ field: "tenure", violation: "missing_required_field" }],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      const datasetLineIndex = lineTexts.findIndex((text) => text.includes("Dataset selected"));
      const startedIndex = lineTexts.findIndex((text) => text === "[INFO] Live Preview inference attempt #1 started.");
      const summaryIndex = lineTexts.findIndex((text) => text.includes("was rejected with"));
      const detailIndex = lineTexts.findIndex((text) => text.includes("a required value was not submitted."));

      expect(datasetLineIndex).toBeGreaterThanOrEqual(0);
      expect(startedIndex).toBeGreaterThan(datasetLineIndex);
      expect(summaryIndex).toBeGreaterThan(startedIndex);
      expect(detailIndex).toBeGreaterThan(summaryIndex);
    });
  });

  // Project Spec S0151: DOM-level wiring coverage using the real
  // InferenceForm/executeAdminInference path and the fetch-mock's
  // adminInferenceRuntimeDiagnostic option -- confirms DatasetAdminPage
  // actually normalizes and projects the private runtime diagnostic into the
  // Publishing console, rather than only exercising the pure model above.
  describe("Publishing console runtime diagnostic wiring (Project Spec S0151)", () => {
    function openLivePreviewInferenceTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(
        within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", {
          name: "Inference",
        }),
      );
    }

    function openPublishingTab() {
      fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
    }

    function consoleLineTexts(): string[] {
      const panel = screen.getByRole("tabpanel");
      const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
      return Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line")).map((el) => el.textContent ?? "");
    }

    it("renders the generic execution-failed line plus one bounded runtime-diagnostic line for an allowlisted code", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INFERENCE_FAILURE",
        adminInferenceRuntimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[ERROR] Live Preview inference attempt #1 could not be completed.");
      expect(lineTexts).toContain(
        "[ERROR] Runtime diagnostic: a required inference runtime dependency is unavailable.",
      );
    });

    it("renders the required deterministic copy for each remaining allowlisted diagnostic code", async () => {
      const cases: Array<[string, string]> = [
        [
          "INFERENCE_BUNDLE_UNAVAILABLE",
          "[ERROR] Runtime diagnostic: the active release inference bundle is unavailable.",
        ],
        [
          "MODEL_ARTIFACT_UNAVAILABLE",
          "[ERROR] Runtime diagnostic: the active release model artifact is unavailable.",
        ],
        [
          "MODEL_ARTIFACT_HASH_MISMATCH",
          "[ERROR] Runtime diagnostic: the active release model artifact failed integrity verification.",
        ],
        [
          "MODEL_DESERIALIZATION_FAILED",
          "[ERROR] Runtime diagnostic: the active release model could not be loaded.",
        ],
        [
          "PREDICTION_EXECUTION_FAILED",
          "[ERROR] Runtime diagnostic: the model could not complete prediction execution.",
        ],
        [
          "RESULT_VALIDATION_FAILED",
          "[ERROR] Runtime diagnostic: the inference result failed governed result validation.",
        ],
        // Project Spec S0152
        [
          "RUNTIME_INPUT_CONTRACT_INCONSISTENT",
          "[ERROR] Runtime diagnostic: the active release input contract is inconsistent with the inference bundle.",
        ],
      ];

      for (const [code, expectedLine] of cases) {
        cleanup();
        installFetchMock({
          adminInferenceErrorCode: "INFERENCE_FAILURE",
          adminInferenceRuntimeDiagnostic: { code },
        });
        renderAdminPage();
        await loadDraftAndCustomization();

        openLivePreviewInferenceTab();
        fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
        await screen.findByRole("alert");

        openPublishingTab();
        expect(consoleLineTexts()).toContain(expectedLine);
      }
    });

    it("adds no runtime-diagnostic line when the backend omits it, preserving the existing generic-only line", async () => {
      installFetchMock({ adminInferenceErrorCode: "INFERENCE_FAILURE" });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[ERROR] Live Preview inference attempt #1 could not be completed.");
      expect(lineTexts.some((text) => text.includes("Runtime diagnostic:"))).toBe(false);
    });

    it("drops an unknown or malformed runtime diagnostic value, never rendering a diagnostic line for it", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INFERENCE_FAILURE",
        adminInferenceRuntimeDiagnostic: { code: "SOME_UNKNOWN_CODE" },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const lineTexts = consoleLineTexts();
      expect(lineTexts).toContain("[ERROR] Live Preview inference attempt #1 could not be completed.");
      expect(lineTexts.some((text) => text.includes("Runtime diagnostic:"))).toBe(false);
      expect(lineTexts.some((text) => text.includes("SOME_UNKNOWN_CODE"))).toBe(false);
    });

    it("never carries a runtime diagnostic line for an INVALID_PAYLOAD response, even if the backend attaches one", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INVALID_PAYLOAD",
        adminInferenceRuntimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      expect(consoleLineTexts().some((text) => text.includes("Runtime diagnostic:"))).toBe(false);
    });

    it("never exposes the raw backend error_code or any additional runtime_diagnostic property in the console DOM", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INFERENCE_FAILURE",
        adminInferenceRuntimeDiagnostic: {
          code: "RUNTIME_DEPENDENCY_UNAVAILABLE",
          message: "joblib==1.5.3 is not installed",
          package: "joblib",
        },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const consoleText = consoleLineTexts().join(" ");
      expect(consoleText).not.toContain("INFERENCE_FAILURE");
      expect(consoleText).not.toContain("joblib");
      expect(consoleText).not.toContain("1.5.3");
    });

    it("renders the runtime-diagnostic line as the newest console line, so it becomes the S0149 latest-line target", async () => {
      installFetchMock({
        adminInferenceErrorCode: "INFERENCE_FAILURE",
        adminInferenceRuntimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInferenceTab();
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));
      await screen.findByRole("alert");

      openPublishingTab();
      const panel = screen.getByRole("tabpanel");
      const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
      const lines = Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line"));
      const lastLine = lines[lines.length - 1];
      expect(lastLine.textContent).toBe(
        "[ERROR] Runtime diagnostic: a required inference runtime dependency is unavailable.",
      );
    });
  });

  // Project Spec S0146: a contract-required checkbox must remain a complete
  // two-state boolean field in the Dataset Admin Live Preview too -- leaving
  // it unchecked must still reach the private Admin inference executor
  // (never blocked by native checkbox constraint validation), and the
  // existing S0144 lifecycle/Publishing-console wiring must keep recording
  // the attempt.
  describe("Live Preview boolean checkbox false-state submission (Project Spec S0146)", () => {
    function openLivePreviewInference() {
      fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
      fireEvent.click(
        within(screen.getByRole("tablist", { name: "Dataset detail sections" })).getByRole("tab", {
          name: "Inference",
        }),
      );
    }

    it("permits an unchecked contract-required checkbox to reach the private Admin inference executor, with the payload key serialized as boolean false, and still records the attempt in the Publishing console", async () => {
      const fetchMock = installFetchMock({
        extraContractFields: [{ name: "consent", label: "Consent", optional: false, input_type: "checkbox" }],
      });
      renderAdminPage();
      await loadDraftAndCustomization();

      openLivePreviewInference();

      const checkbox = screen.getByLabelText("Consent") as HTMLInputElement;
      expect(checkbox).not.toBeChecked();
      expect(checkbox).not.toHaveAttribute("required");

      const callsBeforeSubmit = fetchMock.mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: /Run prediction/ }));

      expect(
        await screen.findByText("82%", { selector: ".binary-classification-result__probability-value" }),
      ).toBeInTheDocument();

      const inferenceCall = fetchMock.mock.calls
        .slice(callsBeforeSubmit)
        .find(
          (call) =>
            (call[1] as RequestInit | undefined)?.method === "POST" &&
            String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/inference`),
        );
      expect(inferenceCall).toBeDefined();
      const body = JSON.parse(String((inferenceCall![1] as RequestInit).body));
      expect(body.consent).toBe(false);
      expect(typeof body.consent).toBe("boolean");

      fireEvent.click(screen.getByRole("tab", { name: "Publishing" }));
      const panel = screen.getByRole("tabpanel");
      const consoleEl = within(panel).getByRole("log", { name: "Dataset publication operational status" });
      const lineTexts = Array.from(consoleEl.querySelectorAll(".dataset-admin-console-line")).map(
        (el) => el.textContent ?? "",
      );
      expect(lineTexts).toContain("[INFO] Live Preview inference attempt #1 started.");
      expect(lineTexts.some((text) => text.includes("attempt #1 completed successfully"))).toBe(true);
    });
  });
});

// Project Spec S0200: Admin score rows render a compact, explanatory-only
// optimization orientation sourced from the shared performanceMetricMetadata
// module -- never an editable control, never a separate independent
// direction map, and identical to what the shared PerformanceSummary renders
// in Live Preview.
describe("Performance metric optimization semantics (Project Spec S0200)", () => {
  async function openMetadataCardTab() {
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
  }

  function scoreRow(label: string): HTMLElement {
    return screen.getByText(label, { selector: "strong" }).closest(".performance-focus-builder__score") as HTMLElement;
  }

  it("renders favorable-up/unfavorable-down orientation with visible text for a higher-is-better score (ROC-AUC)", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "overall_discrimination" } });

    const row = scoreRow("ROC-AUC");
    expect(within(row).getByText("Higher is better")).toBeInTheDocument();
    const favorable = row.querySelector(".performance-metric-orientation__arrow--favorable")!;
    const unfavorable = row.querySelector(".performance-metric-orientation__arrow--unfavorable")!;
    expect(favorable).toHaveTextContent("↑");
    expect(favorable).toHaveAttribute("aria-hidden", "true");
    expect(unfavorable).toHaveTextContent("↓");
    expect(unfavorable).toHaveAttribute("aria-hidden", "true");
  });

  it("renders unfavorable-up/favorable-down orientation with visible text for a lower-is-better score (Brier Score)", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "probability_quality" } });

    const row = scoreRow("Brier Score");
    expect(within(row).getByText("Lower is better")).toBeInTheDocument();
    const favorable = row.querySelector(".performance-metric-orientation__arrow--favorable")!;
    const unfavorable = row.querySelector(".performance-metric-orientation__arrow--unfavorable")!;
    expect(favorable).toHaveTextContent("↓");
    expect(unfavorable).toHaveTextContent("↑");
  });

  it("renders neutral target-based orientation with no favorable/unfavorable arrow pair for Calibration Slope and Calibration Intercept", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "probability_quality" } });

    const slopeRow = scoreRow("Calibration Slope");
    expect(within(slopeRow).getByText("Closer to 1 is better")).toBeInTheDocument();
    expect(slopeRow.querySelector(".performance-metric-orientation__arrow--favorable")).not.toBeInTheDocument();
    expect(slopeRow.querySelector(".performance-metric-orientation__arrow--unfavorable")).not.toBeInTheDocument();

    const interceptRow = scoreRow("Calibration Intercept");
    expect(within(interceptRow).getByText("Closer to 0 is better")).toBeInTheDocument();
    expect(interceptRow.querySelector(".performance-metric-orientation__arrow--favorable")).not.toBeInTheDocument();
    expect(interceptRow.querySelector(".performance-metric-orientation__arrow--unfavorable")).not.toBeInTheDocument();
  });

  it("keeps the orientation explanatory-only (no editable control inside it) while existing value editing, highlighting, and dirty-state tracking keep working", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    const toolbarPublish = within(screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" })).getByRole(
      "button",
      { name: "Publish changes" },
    );
    expect(toolbarPublish).toBeDisabled();

    const row = scoreRow("Recall");
    const orientation = row.querySelector(".performance-metric-orientation")!;
    expect(orientation).toBeInTheDocument();
    expect(orientation.querySelector("input, button, select, textarea")).toBeNull();

    fireEvent.change(screen.getByLabelText("Highlighted score"), { target: { value: "precision" } });
    expect(toolbarPublish).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Highlighted score value"), { target: { value: "0.77" } });
    expect(screen.getByLabelText("Precision value")).toHaveValue("0.77");
  });

  // Project Spec S0221: Metadata & Card authoring guidance keeps its visible
  // "Lower is better" line (it is a configuration aid, out of this spec's
  // scope), while Live Preview -- rendering the shared, simplified
  // PerformanceSummary -- shows the same orientation only as an accessible
  // group label on its arrow pair, never as visible text.
  it("keeps Admin Metadata & Card authoring guidance visible while Live Preview's shared Performance Summary omits the visible line but keeps the orientation accessible", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "probability_quality" } });
    const adminRow = scoreRow("Log Loss");
    expect(within(adminRow).getByText("Lower is better")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

    const previewScore = screen.getByText("Log Loss").closest(".performance-summary__score") as HTMLElement;
    expect(within(previewScore).queryByText("Lower is better")).not.toBeInTheDocument();
    expect(previewScore.querySelector(".performance-summary__score-arrows")).toHaveAttribute(
      "aria-label",
      "Lower is better",
    );
    // The public shared component never shows an opposing favorable/
    // unfavorable arrow pair -- only the single-arrow public orientation.
    expect(previewScore.querySelectorAll(".performance-metric-orientation__arrow")).toHaveLength(0);
  });
});

// Project Spec S0201: a persisted performance_focus must rehydrate with
// exactly its persisted visible_scores checked -- every other catalog score
// for that focus must hydrate unchecked, never contaminated by
// defaultPerformanceFocus's order<3 initial-selection default. Publishing an
// intentionally reduced score selection must never resurrect a previously
// default-visible score on rehydration, including across repeated
// publish/rehydrate cycles.
describe("Performance focus selection round trip and single-column score presentation (Project Spec S0201)", () => {
  async function openMetadataCardTab() {
    await waitFor(() => expect(screen.getByLabelText("Display title")).toHaveValue("Curated churn profile"));
    fireEvent.click(screen.getByRole("tab", { name: "Metadata & Card" }));
  }

  function scoreCheckbox(label: string): HTMLInputElement {
    return screen.getByRole("checkbox", { name: `Show ${label}` }) as HTMLInputElement;
  }

  it("rehydrates a persisted focus with exactly one visible score, leaving every other catalog score unchecked", async () => {
    installFetchMock({
      publishedSnapshotProfile: {
        ...publicProfile,
        performance_focus: {
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [{ score_id: "roc_auc", display_label: "ROC-AUC", value: "0.84", value_source: "manual", order: 0 }],
        },
      } as typeof publicProfile,
    });
    renderAdminPage();
    await openMetadataCardTab();

    await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("overall_discrimination"));
    expect(scoreCheckbox("ROC-AUC")).toBeChecked();
    expect(scoreCheckbox("PR-AUC")).not.toBeChecked();
    expect(scoreCheckbox("Gini coefficient")).not.toBeChecked();
    expect(scoreCheckbox("KS statistic")).not.toBeChecked();
  });

  it("rehydrates a persisted focus with exactly two visible scores, leaving the third default-visible catalog score (Gini) unchecked", async () => {
    installFetchMock({
      publishedSnapshotProfile: {
        ...publicProfile,
        performance_focus: {
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.84", value_source: "manual", order: 0 },
            { score_id: "pr_auc", display_label: "PR-AUC", value: "0.64", value_source: "manual", order: 1 },
          ],
        },
      } as typeof publicProfile,
    });
    renderAdminPage();
    await openMetadataCardTab();

    await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("overall_discrimination"));
    expect(scoreCheckbox("ROC-AUC")).toBeChecked();
    expect(scoreCheckbox("PR-AUC")).toBeChecked();
    expect(scoreCheckbox("Gini coefficient")).not.toBeChecked();
    expect(scoreCheckbox("KS statistic")).not.toBeChecked();
  });

  it("rehydrates a persisted three-score selection that skips catalog entries in between, leaving every unselected score unchecked", async () => {
    installFetchMock({
      publishedSnapshotProfile: {
        ...publicProfile,
        performance_focus: {
          focus_id: "balanced_classification",
          highlighted_score_id: "balanced_accuracy",
          visible_scores: [
            { score_id: "balanced_accuracy", display_label: "Balanced Accuracy", value: "0.79", value_source: "manual", order: 0 },
            { score_id: "f1_score", display_label: "F1-score", value: "0.71", value_source: "manual", order: 1 },
            { score_id: "cohens_kappa", display_label: "Cohen's Kappa", value: "0.55", value_source: "manual", order: 2 },
          ],
        },
      } as typeof publicProfile,
    });
    renderAdminPage();
    await openMetadataCardTab();

    await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("balanced_classification"));
    expect(scoreCheckbox("Balanced Accuracy")).toBeChecked();
    expect(scoreCheckbox("F1-score")).toBeChecked();
    expect(scoreCheckbox("Cohen's Kappa")).toBeChecked();
    expect(scoreCheckbox("MCC")).not.toBeChecked();
    expect(scoreCheckbox("Accuracy")).not.toBeChecked();
    expect(scoreCheckbox("Recall")).not.toBeChecked();
    expect(scoreCheckbox("Specificity")).not.toBeChecked();
    expect(scoreCheckbox("G-Mean")).not.toBeChecked();
  });

  it("a new/unconfigured focus switch still uses the current default top-three visible selection", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "overall_discrimination" } });

    expect(scoreCheckbox("ROC-AUC")).toBeChecked();
    expect(scoreCheckbox("PR-AUC")).toBeChecked();
    expect(scoreCheckbox("Gini coefficient")).toBeChecked();
    expect(scoreCheckbox("KS statistic")).not.toBeChecked();
  });

  it("deselecting the currently highlighted score falls back to another visible score and never publishes an invisible highlighted score", async () => {
    installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "overall_discrimination" } });
    expect(screen.getByLabelText("Highlighted score")).toHaveValue("roc_auc");

    fireEvent.click(scoreCheckbox("ROC-AUC"));

    expect(scoreCheckbox("ROC-AUC")).not.toBeChecked();
    expect(screen.getByLabelText("Highlighted score")).toHaveValue("pr_auc");
    expect(scoreCheckbox("PR-AUC")).toBeChecked();
  });

  it("does not resurrect an unselected default score (Gini) on Publish changes, and keeps it absent across a second Publish changes cycle", async () => {
    const fetchMock = installFetchMock();
    renderAdminPage();
    await openMetadataCardTab();

    fireEvent.change(screen.getByLabelText("Performance focus"), { target: { value: "overall_discrimination" } });
    expect(scoreCheckbox("Gini coefficient")).toBeChecked();
    fireEvent.click(scoreCheckbox("Gini coefficient"));
    expect(scoreCheckbox("Gini coefficient")).not.toBeChecked();
    expect(scoreCheckbox("ROC-AUC")).toBeChecked();
    expect(scoreCheckbox("PR-AUC")).toBeChecked();

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    const publishButton = within(toolbar).getByRole("button", { name: "Publish changes" });
    fireEvent.click(publishButton);
    await waitFor(() => expect(publishButton).toBeDisabled());

    function publishCalls() {
      return fetchMock.mock.calls.filter(
        (call: unknown[]) =>
          String(call[0]).endsWith(`/admin/datasets/${datasetSlug}/publish`) &&
          (call[1] as RequestInit | undefined)?.method === "PUT",
      );
    }

    expect(publishCalls()).toHaveLength(1);
    const firstBody = JSON.parse(String((publishCalls()[0][1] as RequestInit).body)) as {
      performance_focus?: { visible_scores?: Array<{ score_id: string }> };
    };
    expect(firstBody.performance_focus?.visible_scores?.map((score) => score.score_id)).toEqual(["roc_auc", "pr_auc"]);

    await waitFor(() => {
      expect(scoreCheckbox("ROC-AUC")).toBeChecked();
      expect(scoreCheckbox("PR-AUC")).toBeChecked();
      expect(scoreCheckbox("Gini coefficient")).not.toBeChecked();
    });

    fireEvent.change(screen.getByLabelText("Home card description"), { target: { value: "Updated home card copy" } });
    expect(publishButton).toBeEnabled();
    fireEvent.click(publishButton);
    await waitFor(() => expect(publishButton).toBeDisabled());

    expect(publishCalls()).toHaveLength(2);
    const secondBody = JSON.parse(String((publishCalls()[1][1] as RequestInit).body)) as {
      performance_focus?: { visible_scores?: Array<{ score_id: string }> };
    };
    expect(secondBody.performance_focus?.visible_scores?.map((score) => score.score_id)).toEqual(["roc_auc", "pr_auc"]);
    expect(scoreCheckbox("ROC-AUC")).toBeChecked();
    expect(scoreCheckbox("PR-AUC")).toBeChecked();
    expect(scoreCheckbox("Gini coefficient")).not.toBeChecked();
  });

  it("Live Preview renders only the currently committed visible scores, single-column", async () => {
    installFetchMock({
      publishedSnapshotProfile: {
        ...publicProfile,
        performance_focus: {
          focus_id: "overall_discrimination",
          highlighted_score_id: "roc_auc",
          visible_scores: [
            { score_id: "roc_auc", display_label: "ROC-AUC", value: "0.84", value_source: "manual", order: 0 },
            { score_id: "pr_auc", display_label: "PR-AUC", value: "0.64", value_source: "manual", order: 1 },
          ],
        },
      } as typeof publicProfile,
    });
    renderAdminPage();
    await openMetadataCardTab();
    await waitFor(() => expect(screen.getByLabelText("Performance focus")).toHaveValue("overall_discrimination"));

    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));

    const scoreTiles = document.querySelectorAll(".performance-summary__score");
    expect(scoreTiles).toHaveLength(2);
    expect(within(scoreTiles[0] as HTMLElement).getByText("ROC-AUC")).toBeInTheDocument();
    expect(within(scoreTiles[1] as HTMLElement).getByText("PR-AUC")).toBeInTheDocument();
    expect(screen.queryByText("Gini coefficient")).not.toBeInTheDocument();
    expect(screen.queryByText("KS statistic")).not.toBeInTheDocument();
  });
});

// -----------------------------------------------------------------------------
// Project Spec S0218: Dry Bean native Predict View authoring bootstrap.
//
// A first-dataset/native-style regression, deliberately independent of the
// shared Telco `installFetchMock`/`datasetSlug`/`viewId`/`customization`
// fixtures above (its own dataset slug, its own fetch mock) -- it proves the
// existing, unmodified production page correctly bootstraps a governed
// multiclass dataset with one eligible Predict View and no stored
// customization: the sole eligible view auto-binds, all 16 governed Dry Bean
// fields render authorable and ungrouped, Add subgroup/field assignment
// works, Live Preview reflects the unsaved draft, and Publish changes
// persists the customization through the existing shared endpoint shape.
// -----------------------------------------------------------------------------
describe("Dry Bean native Predict View authoring bootstrap (Project Spec S0218)", () => {
  const dryBeanSlug = "dry-bean";
  const dryBeanViewId = "dry-bean-classification";
  // The real 16 governed Dry Bean public-contract feature names (Project
  // Specs S0216/S0218), not a synthetic subset.
  const dryBeanFields = [
    "Area",
    "Perimeter",
    "MajorAxisLength",
    "MinorAxisLength",
    "AspectRatio",
    "Eccentricity",
    "ConvexArea",
    "EquivDiameter",
    "Extent",
    "Solidity",
    "Roundness",
    "Compactness",
    "ShapeFactor1",
    "ShapeFactor2",
    "ShapeFactor3",
    "ShapeFactor4",
  ];

  beforeEach(() => {
    Element.prototype.setPointerCapture = vi.fn();
    // jsdom does not implement elementFromPoint -- finishDrag() calls it
    // unconditionally on pointer up/cancel (same precondition as the shared
    // DatasetAdminPage describe block above).
    document.elementFromPoint = vi.fn(() => null);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function installDryBeanFetchMock() {
    let savedCustomization: Record<string, unknown> | null = null;

    function authoringContextEnvelope(): Record<string, unknown> {
      return {
        dataset_slug: dryBeanSlug,
        active_release: "release-20260818-101",
        dataset: {
          status: "ready",
          data: {
            dataset_slug: dryBeanSlug,
            title: "Dry Bean",
            display_title: null,
            summary: "Predict the Dry Bean class from the governed morphological input features.",
            domain: "general",
            tags: ["dry-bean", "classification", "multiclass"],
            active_release: "release-20260818-101",
            publication_status: "ready",
          },
        },
        context: {
          status: "ready",
          data: {
            title: "Dry Bean",
            summary: "Predict the Dry Bean class from the governed morphological input features.",
            domain: "general",
            tags: ["dry-bean", "classification", "multiclass"],
            problem_type: "multiclass_classification",
            prediction_target_description: "Dry bean class",
          },
        },
        contract: {
          status: "ready",
          data: {
            contract: {
              schema_version: "1.0.0",
              features: dryBeanFields.map((name, index) => ({
                name,
                label: name,
                input_type: "number",
                optional: false,
                display_order: index + 1,
              })),
            },
            result_contract: {
              status: "available",
              semantics: {
                schema_version: "multiclass-result-semantics.v1",
                problem_type: "multiclass_classification",
                result_schema_version: "multiclass-classification-result.v1",
                primary_output: "predicted_class",
                probability_output: "class_probabilities",
                classes: [
                  { class_id: "SEKER", display_label: "Seker" },
                  { class_id: "BARBUNYA", display_label: "Barbunya" },
                  { class_id: "BOMBAY", display_label: "Bombay" },
                  { class_id: "CALI", display_label: "Cali" },
                  { class_id: "DERMASON", display_label: "Dermason" },
                  { class_id: "HOROZ", display_label: "Horoz" },
                  { class_id: "SIRA", display_label: "Sira" },
                ],
                decision: { strategy: "argmax" },
                model_descriptor: { model_family: "hist_gradient_boosting", display_name: "Dry Bean classifier" },
              },
            },
          },
        },
        inference_guidance: { status: "ready", data: [] },
        metrics: { status: "ready", data: { evaluation: { metrics: { f1_macro: 0.91, accuracy: 0.92 } } } },
        visualizations: { status: "ready", data: {} },
        views: {
          status: "ready",
          data: [{ view_id: dryBeanViewId, display: { title: "Dry Bean Classification" } }],
        },
      };
    }

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: dryBeanSlug,
              title: "Dry Bean",
              display_title: null,
              summary: "Predict the Dry Bean class from the governed morphological input features.",
              domain: "general",
              tags: ["dry-bean", "classification", "multiclass"],
              active_release: "release-20260818-101",
              publication_status: "ready",
            },
          ],
        });
      }
      if (url.endsWith("/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: dryBeanSlug,
              title: "Dry Bean",
              summary: "Predict the Dry Bean class from the governed morphological input features.",
              domain: "general",
              visibility: "public",
              tags: ["dry-bean", "classification", "multiclass"],
              problem_type: "multiclass_classification",
            },
          ],
        });
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/authoring-context`)) {
        return jsonResponse(authoringContextEnvelope());
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/publication-state`)) {
        return jsonResponse({
          dataset_slug: dryBeanSlug,
          active_release: "release-20260818-101",
          visibility: {
            configured_visible: true,
            source: "explicit_record",
            record_status: "valid",
            updated_at: "2026-08-18T00:00:00Z",
            effective_visible: true,
          },
          review: { status: "ready", approval_allowed: false, approval_blockers: [] },
          snapshot: { status: "no_snapshot", exists: false },
          public_access: { reachable: true, blockers: [], observations: [] },
        });
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/profile-draft`)) {
        // Project Spec S0218 Section L: no customization is pre-created, and
        // this scenario likewise starts with no saved Dataset Detail draft --
        // proving the bootstrap never depends on one existing already.
        return jsonResponse({ draft_exists: false, profile: null });
      }
      if (
        url.endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`) &&
        init?.method === "PUT"
      ) {
        const body = (typeof init.body === "string" ? JSON.parse(init.body) : null) as Record<string, unknown> | null;
        savedCustomization = body;
        return jsonResponse({ saved: true, customization: body });
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`)) {
        // Project Spec S0218 Section L: the stored customization is absent
        // until the operator authors and publishes one through this page.
        return jsonResponse({
          customization_exists: false,
          compatibility_status: "absent",
          customization: null,
          errors: [],
        });
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, getSavedCustomization: () => savedCustomization };
  }

  it("auto-binds the sole eligible Dry Bean view and renders all 16 governed fields ungrouped with no stored customization", async () => {
    const { fetchMock } = installDryBeanFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    // Project Spec S0100: a single eligible view is silently auto-bound --
    // the manual "Bound predict view" select never renders.
    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`),
      ),
    ).toBe(true);

    const noSubgroupZone = screen.getByLabelText("No subgroup fields");
    for (const fieldName of dryBeanFields) {
      expect(within(noSubgroupZone).getByText(fieldName)).toBeInTheDocument();
    }

    // Every field is required (optional: false in the real Dry Bean public
    // contract), so the Field bank starts empty -- nothing is silently
    // hidden from the initial authoring state.
    expect(
      within(screen.getByLabelText("Field bank fields")).getByText(
        "Drag fields here to remove them from the public form.",
      ),
    ).toBeInTheDocument();

    // Project Spec S0218 Section Q: zero authored subgroups at bootstrap.
    expect(
      screen.getByText("No subgroups defined. Visible fields without a subgroup render in No subgroup below."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add subgroup" })).toBeInTheDocument();
  });

  it("creates a subgroup, assigns two fields, reflects it in Live Preview before persistence, and persists it through the shared Publish changes customization payload", async () => {
    document.elementFromPoint = vi.fn(() =>
      document.querySelector<HTMLElement>('[data-customization-drop-zone="group-1"]'),
    );
    const { getSavedCustomization } = installDryBeanFetchMock();
    renderAdminPage();

    await loadDraftAndCustomization();

    const layoutPanel = screen.getByLabelText("Public form layout");
    fireEvent.click(within(layoutPanel).getByRole("button", { name: "Add subgroup" }));
    const cardsAfterAdd = layoutPanel.querySelectorAll(".dataset-admin-builder-card");
    const newGroupCard = cardsAfterAdd[cardsAfterAdd.length - 1] as HTMLElement;

    fireEvent.click(within(newGroupCard).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(newGroupCard).getByLabelText("Label"), { target: { value: "Shape geometry" } });
    fireEvent.change(within(newGroupCard).getByLabelText("Description"), {
      target: { value: "Shape-derived morphological measurements" },
    });
    fireEvent.click(within(newGroupCard).getByRole("button", { name: "Save subgroup" }));

    // Assign at least two fields (Project Spec S0218 Section O) -- every
    // drop resolves to the newly created "group-1" zone via the mocked
    // elementFromPoint above.
    for (const fieldName of ["Area", "Perimeter"]) {
      const dragHandle = screen.getByRole("button", { name: `Drag field ${fieldName}` });
      fireEvent.pointerDown(dragHandle, { pointerId: 1, clientX: 0, clientY: 0 });
      fireEvent.pointerUp(dragHandle, { pointerId: 1, clientX: 0, clientY: 0 });
    }

    // Live Preview reflects the unsaved draft's subgroup label and field
    // membership before any persistence (Project Spec S0218 Section O).
    fireEvent.click(screen.getByRole("tab", { name: "Live Preview" }));
    fireEvent.click(screen.getByRole("tab", { name: "Inference" }));
    // The live InferenceForm renders each customization group as a
    // <fieldset><legend>{label}</legend>...</fieldset> -- its accessible
    // name comes from the legend, matched via role "group", not the
    // form-control-oriented getByLabelText query.
    const livePreviewSubgroup = screen.getByRole("group", { name: "Shape geometry" });
    // Each field's own <label> carries an aria-hidden " *" required marker
    // appended to its text, so match by prefix rather than the full
    // (whitespace-including) label text.
    expect(within(livePreviewSubgroup).getByLabelText(/^Area\b/)).toBeInTheDocument();
    expect(within(livePreviewSubgroup).getByLabelText(/^Perimeter\b/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));

    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    fireEvent.click(within(toolbar).getByRole("button", { name: "Publish changes" }));
    await waitFor(() => expect(within(toolbar).getByText("Changes saved.")).toBeInTheDocument());

    const saved = getSavedCustomization() as {
      dataset_slug?: string;
      view_id?: string;
      field_hints?: Array<{ field_name: string; group?: string }>;
      groups?: Array<{ group_id: string; label: string; description?: string }>;
      contract_precedence?: Record<string, boolean>;
    };
    expect(saved).not.toBeNull();
    expect(saved!.dataset_slug).toBe(dryBeanSlug);
    expect(saved!.view_id).toBe(dryBeanViewId);
    expect(saved!.field_hints?.map((hint) => hint.field_name).sort()).toEqual([...dryBeanFields].sort());
    expect(saved!.groups).toEqual([
      { group_id: "group-1", label: "Shape geometry", description: "Shape-derived morphological measurements" },
    ]);
    const assignedGroups = new Map(saved!.field_hints?.map((hint) => [hint.field_name, hint.group]));
    expect(assignedGroups.get("Area")).toBe("group-1");
    expect(assignedGroups.get("Perimeter")).toBe("group-1");
    expect(assignedGroups.get("Solidity")).toBeUndefined();
    // Project Spec S0218 Section P: customization introduces no validation
    // semantics of its own -- the same fixed contract-precedence boundary
    // every other dataset's customization carries.
    expect(saved!.contract_precedence).toEqual({
      canonical_contracts_are_source_of_truth: true,
      customization_defines_runtime_validation: false,
      customization_duplicates_contract: false,
    });
  });
});

describe("Dataset-switch-safe Predict View rebinding and inference form bootstrap (Project Spec S0220)", () => {
  const dryBeanSlug = "dry-bean";
  const dryBeanViewId = "dry-bean-classification";
  // The real 16 governed Dry Bean public-contract feature names (Project
  // Specs S0216/S0218), matching the S0218 describe block's own fixture.
  const dryBeanFields = [
    "Area",
    "Perimeter",
    "MajorAxisLength",
    "MinorAxisLength",
    "AspectRatio",
    "Eccentricity",
    "ConvexArea",
    "EquivDiameter",
    "Extent",
    "Solidity",
    "Roundness",
    "Compactness",
    "ShapeFactor1",
    "ShapeFactor2",
    "ShapeFactor3",
    "ShapeFactor4",
  ];

  beforeEach(() => {
    Element.prototype.setPointerCapture = vi.fn();
    document.elementFromPoint = vi.fn(() => null);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function telcoAuthoringContextEnvelope(): Record<string, unknown> {
    return {
      dataset_slug: datasetSlug,
      active_release: "release-20260619-001",
      dataset: {
        status: "ready",
        data: {
          dataset_slug: datasetSlug,
          title: "Telco Customer Churn",
          display_title: null,
          summary: "Customer churn prediction dataset",
          domain: "telecom",
          tags: ["telecom"],
          active_release: "release-20260619-001",
          publication_status: "ready",
        },
      },
      context: {
        status: "ready",
        data: {
          title: "Telco Customer Churn",
          summary: "Baseline churn problem summary",
          domain: "telecom",
          tags: ["telecom"],
          problem_type: "binary_classification",
          prediction_target_description: "Customer churn",
        },
      },
      contract: {
        status: "ready",
        data: {
          contract: {
            schema_version: "1.0.0",
            features: [
              { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
              { name: "MonthlyCharges", label: "Monthly charges", input_type: "number", optional: true, display_order: 2 },
            ],
          },
          result_contract: {
            status: "available",
            semantics: {
              schema_version: "binary-result-semantics.v1",
              problem_type: "binary_classification",
              result_schema_version: "binary-classification-result.v1",
              primary_output: "positive_class_probability",
              positive_class: { class_id: "churn", event_label: "Customer churn" },
              negative_class: { class_id: "retained" },
              decision: { threshold: 0.6 },
              interpretation: {
                preset: "risk",
                bands: [
                  { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
                  { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
                  { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
                ],
              },
              model_descriptor: { model_family: "linear", display_name: "Retention model" },
            },
          },
        },
      },
      inference_guidance: { status: "ready", data: [] },
      metrics: { status: "ready", data: { evaluation: { metrics: { auc_roc: 0.93, accuracy: 0.86 } } } },
      visualizations: { status: "ready", data: {} },
      views: { status: "ready", data: [{ view_id: viewId, display: { title: "Churn risk overview" } }] },
    };
  }

  function dryBeanAuthoringContextEnvelope(): Record<string, unknown> {
    return {
      dataset_slug: dryBeanSlug,
      active_release: "release-20260818-101",
      dataset: {
        status: "ready",
        data: {
          dataset_slug: dryBeanSlug,
          title: "Dry Bean",
          display_title: null,
          summary: "Predict the Dry Bean class from the governed morphological input features.",
          domain: "general",
          tags: ["dry-bean", "classification", "multiclass"],
          active_release: "release-20260818-101",
          publication_status: "needs_review",
        },
      },
      context: {
        status: "ready",
        data: {
          title: "Dry Bean",
          summary: "Predict the Dry Bean class from the governed morphological input features.",
          domain: "general",
          tags: ["dry-bean", "classification", "multiclass"],
          problem_type: "multiclass_classification",
          prediction_target_description: "Dry bean class",
        },
      },
      contract: {
        status: "ready",
        data: {
          contract: {
            schema_version: "1.0.0",
            features: dryBeanFields.map((name, index) => ({
              name,
              label: name,
              input_type: "number",
              optional: false,
              display_order: index + 1,
            })),
          },
          result_contract: {
            status: "available",
            semantics: {
              schema_version: "multiclass-result-semantics.v1",
              problem_type: "multiclass_classification",
              result_schema_version: "multiclass-classification-result.v1",
              primary_output: "predicted_class",
              probability_output: "class_probabilities",
              classes: [
                { class_id: "SEKER", display_label: "Seker" },
                { class_id: "BARBUNYA", display_label: "Barbunya" },
                { class_id: "BOMBAY", display_label: "Bombay" },
                { class_id: "CALI", display_label: "Cali" },
                { class_id: "DERMASON", display_label: "Dermason" },
                { class_id: "HOROZ", display_label: "Horoz" },
                { class_id: "SIRA", display_label: "Sira" },
              ],
              decision: { strategy: "argmax" },
              model_descriptor: { model_family: "hist_gradient_boosting", display_name: "Dry Bean classifier" },
            },
          },
        },
      },
      inference_guidance: { status: "ready", data: [] },
      metrics: { status: "ready", data: { evaluation: { metrics: { f1_macro: 0.91, accuracy: 0.92 } } } },
      visualizations: { status: "ready", data: {} },
      views: { status: "ready", data: [{ view_id: dryBeanViewId, display: { title: "Dry Bean Classification" } }] },
    };
  }

  function telcoPublicationState(): Record<string, unknown> {
    return {
      dataset_slug: datasetSlug,
      active_release: "release-20260619-001",
      visibility: {
        configured_visible: true,
        source: "explicit_record",
        record_status: "valid",
        updated_at: "2026-07-03T17:35:00Z",
        effective_visible: true,
      },
      review: { status: "ready", approval_allowed: false, approval_blockers: [] },
      snapshot: {
        status: "current_release",
        exists: true,
        published_at: "2026-07-11T14:00:00Z",
        active_release_at_publish_time: "release-20260619-001",
        matches_active_release: true,
      },
      public_access: { reachable: true, blockers: [], observations: [] },
    };
  }

  function dryBeanPublicationState(): Record<string, unknown> {
    return {
      dataset_slug: dryBeanSlug,
      active_release: "release-20260818-101",
      visibility: {
        configured_visible: true,
        source: "explicit_record",
        record_status: "valid",
        updated_at: "2026-08-18T00:00:00Z",
        effective_visible: false,
      },
      review: { status: "needs_review", approval_allowed: false, approval_blockers: ["dataset_needs_review"] },
      snapshot: {
        status: "missing",
        exists: false,
        published_at: null,
        active_release_at_publish_time: null,
        matches_active_release: null,
      },
      public_access: { reachable: false, blockers: ["dataset_needs_review"], observations: [] },
    };
  }

  // Real production topology (Project Spec S0220 Section I): the public
  // /datasets listing carries only Telco (Dry Bean is not yet publicly
  // visible), while the private /admin/datasets listing carries both. Both
  // datasets' profile-draft/authoring-context routes can be armed to defer
  // their *second* response (i.e. a later re-selection, never the first
  // load that establishes genuine readiness) so a late-response variant can
  // prove a stale prior-dataset response cannot alter an already-settled
  // later selection.
  function installDatasetSwitchFetchMock() {
    let telcoAuthoringContextVisits = 0;
    let telcoProfileDraftVisits = 0;
    let deferTelcoAuthoringContextOnNextRevisit = false;
    let deferTelcoProfileDraftOnNextRevisit = false;
    let releaseDeferredTelcoAuthoringContext: (() => void) | null = null;
    let releaseDeferredTelcoProfileDraft: (() => void) | null = null;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.endsWith("/admin/datasets")) {
        return jsonResponse({
          datasets: [
            {
              dataset_slug: datasetSlug,
              title: "Telco Customer Churn",
              display_title: null,
              summary: "Customer churn prediction dataset",
              domain: "telecom",
              tags: ["telecom"],
              active_release: "release-20260619-001",
              publication_status: "ready",
              last_updated: "2026-06-19T12:00:00Z",
            },
            {
              dataset_slug: dryBeanSlug,
              title: "Dry Bean",
              display_title: null,
              summary: "Predict the Dry Bean class from the governed morphological input features.",
              domain: "general",
              tags: ["dry-bean", "classification", "multiclass"],
              active_release: "release-20260818-101",
              publication_status: "needs_review",
              last_updated: "2026-08-18T00:00:00Z",
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
      if (url.endsWith(`/admin/datasets/${datasetSlug}/authoring-context`)) {
        telcoAuthoringContextVisits += 1;
        if (deferTelcoAuthoringContextOnNextRevisit && telcoAuthoringContextVisits === 2) {
          return new Promise<MockResponse>((resolve) => {
            releaseDeferredTelcoAuthoringContext = () => resolve(jsonResponse(telcoAuthoringContextEnvelope()));
          });
        }
        return jsonResponse(telcoAuthoringContextEnvelope());
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/authoring-context`)) {
        return jsonResponse(dryBeanAuthoringContextEnvelope());
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/profile-draft`)) {
        telcoProfileDraftVisits += 1;
        if (deferTelcoProfileDraftOnNextRevisit && telcoProfileDraftVisits === 2) {
          return new Promise<MockResponse>((resolve) => {
            releaseDeferredTelcoProfileDraft = () =>
              resolve(jsonResponse({ draft_exists: true, profile: publicProfile }));
          });
        }
        return jsonResponse({ draft_exists: true, profile: publicProfile });
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/profile-draft`)) {
        // Project Spec S0220 Section I: no saved profile binding for Dry
        // Bean yet.
        return jsonResponse({ draft_exists: false, profile: null });
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/publication-state`)) {
        return jsonResponse(telcoPublicationState());
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/publication-state`)) {
        return jsonResponse(dryBeanPublicationState());
      }
      if (url.endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`)) {
        return jsonResponse({
          customization_exists: true,
          compatibility_status: "compatible",
          customization,
          errors: [],
        });
      }
      if (url.endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`)) {
        // Project Spec S0220 Section I: no stored customization for Dry Bean
        // yet -- the absent-customization clean contract-derived draft path.
        return jsonResponse({
          customization_exists: false,
          compatibility_status: "absent",
          customization: null,
          errors: [],
        });
      }

      return jsonResponse({}, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    return Object.assign(fetchMock, {
      armDeferredTelcoRevisit: () => {
        deferTelcoAuthoringContextOnNextRevisit = true;
        deferTelcoProfileDraftOnNextRevisit = true;
      },
      releaseDeferredTelcoResponses: () => {
        releaseDeferredTelcoAuthoringContext?.();
        releaseDeferredTelcoProfileDraft?.();
      },
    });
  }

  async function waitForTelcoReadyAndBound() {
    await loadDraftAndCustomization();
    // Confirms Telco's own compatible churn-risk-overview customization
    // (tenure/MonthlyCharges) actually loaded -- i.e. Telco is genuinely
    // ready and bound, not merely selected -- before any switch below.
    expect(await screen.findByRole("button", { name: "Drag field Tenure" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Drag field Monthly charges" })).toBeInTheDocument();
  }

  async function selectDataset(label: string) {
    const selector = await screen.findByRole("button", { name: "Dataset" });
    fireEvent.click(selector);
    fireEvent.click(screen.getByRole("option", { name: label }));
    await waitFor(() => expect(screen.getByRole("heading", { name: `Dataset — ${label}` })).toBeInTheDocument());
  }

  function assertSettledDryBeanState() {
    // Item J / acceptance 3-16, 19-26: identity-consistent rebinding, no
    // manual selector for one eligible view, and the correct (never
    // churn-risk-overview) Dry Bean customization request.
    expect(screen.queryByLabelText("Bound predict view")).not.toBeInTheDocument();
    expect(screen.queryByText("No predict view bound")).not.toBeInTheDocument();
    const noSubgroupZone = screen.getByLabelText("No subgroup fields");
    for (const fieldName of dryBeanFields) {
      expect(within(noSubgroupZone).getByText(fieldName)).toBeInTheDocument();
    }
    expect(
      screen.getByText("No subgroups defined. Visible fields without a subgroup render in No subgroup below."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add subgroup" })).toBeInTheDocument();
    const toolbar = screen.getByRole("toolbar", { name: "Dataset Detail workspace toolbar" });
    expect(within(toolbar).getByRole("button", { name: "Publish changes" })).toBeDisabled();
  }

  it("rebinds to dry-bean-classification after switching from a fully ready, bound Telco selection, never requesting churn-risk-overview for Dry Bean", async () => {
    const fetchMock = installDatasetSwitchFetchMock();
    renderAdminPage();

    await waitForTelcoReadyAndBound();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith(`/admin/datasets/${datasetSlug}/views/${viewId}/customization`),
      ),
    ).toBe(true);

    await selectDataset("Dry Bean");
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("No subgroup fields");

    assertSettledDryBeanState();

    // Acceptance 15/16: the correct Dry Bean customization GET occurred and
    // the forbidden churn-risk-overview pairing never did.
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`),
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith(`/admin/datasets/${dryBeanSlug}/views/${viewId}/customization`),
      ),
    ).toBe(false);
    // Acceptance 17/18: automatic bootstrap issues no PUT of any kind.
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input).endsWith(`/admin/datasets/${dryBeanSlug}/views/${dryBeanViewId}/customization`) &&
          init?.method === "PUT",
      ),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith(`/admin/datasets/${dryBeanSlug}/publish`)),
    ).toBe(false);
  });

  it("keeps settled Dry Bean state correct when a stale Telco profile-draft/authoring-context response resolves after a later re-selection (late-response variant)", async () => {
    const fetchMock = installDatasetSwitchFetchMock();
    renderAdminPage();

    await waitForTelcoReadyAndBound();
    await selectDataset("Dry Bean");
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("No subgroup fields");
    assertSettledDryBeanState();

    // Re-select Telco -- a genuine new request identity, now armed to defer
    // its *second* profile-draft/authoring-context responses (the first,
    // already-resolved visit is what established genuine readiness above).
    fetchMock.armDeferredTelcoRevisit();
    await selectDataset("Telco Customer Churn");

    // Switch back to Dry Bean before releasing Telco's still-pending second
    // response -- Dry Bean must settle again from its own real data.
    await selectDataset("Dry Bean");
    fireEvent.click(screen.getByRole("tab", { name: "Inference Form" }));
    await screen.findByLabelText("No subgroup fields");
    assertSettledDryBeanState();

    // Now release the stale Telco responses -- Project Spec S0220 Section H:
    // they must never restore Telco's view list, contract, or profile
    // binding under the currently selected Dry Bean identity.
    fetchMock.releaseDeferredTelcoResponses();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByRole("heading", { name: "Dataset — Dry Bean" })).toBeInTheDocument();
    assertSettledDryBeanState();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith(`/admin/datasets/${dryBeanSlug}/views/${viewId}/customization`),
      ),
    ).toBe(false);
  });
});
