import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Badge, Card, FormRow, StatusPill, Tabs, type TabItem } from "../../components/ui";
import DatasetCard from "../../components/DatasetCard";
import { DatasetIcon } from "../../components/DatasetCard/DatasetCard";
import DatasetDetailSurface from "../../components/DatasetDetail/DatasetDetailSurface";
import DatasetDocumentation from "../../components/DatasetDetail/DatasetDocumentation";
import PerformanceSummary from "../../components/DatasetDetail/PerformanceSummary";
import TargetDistribution from "../../components/DatasetDetail/TargetDistribution";
import FeatureImportance from "../../components/DatasetDetail/FeatureImportance";
import BinaryClassificationResult from "../../components/ResultCard/BinaryClassificationResult";
import ResultCardShell from "../../components/ResultCard/ResultCardShell";
import {
  GENERIC_RESULT_PRESENTATION,
  isAvailableBinaryResultContract,
  isBinaryClassificationResult,
  type BinaryResultContract,
  type BinaryResultPresentation,
  type BinaryResultSemantics,
} from "../../components/ResultCard/types";
import InferenceForm, {
  normalizeAdminInferenceGuidance,
  normalizeInferenceRuntimeDiagnostic,
  normalizeInferenceValidationIssues,
  type FieldHint,
  type GroupDef,
  type InferenceExecutionResult,
  type InferenceExecutor,
  type InferenceLifecycleEvent,
  type InferenceLifecycleValidationIssue,
  type InferenceRuntimeDiagnosticCode,
  type InferenceValidationViolation,
  type PredictViewCustomization,
} from "../../components/InferenceForm/InferenceForm";
import {
  projectDatasetDetailPreview,
  projectHomeCardPreview,
  projectPerformanceFocusPreview,
  negativeScenarioProbability,
  positiveScenarioProbability,
  projectBinaryResultPreview,
  toVisualizationsPayload,
} from "../../lib/livePreviewProjection";
import {
  DATASET_THEME_PRESETS,
  DEFAULT_DATASET_THEME_PRESET,
  isDatasetThemePresetId,
  normalizeDatasetDateOnly,
  presentDatasetOperationalTimestamp,
  type DatasetIconName,
  type DatasetThemePresetId,
} from "../../lib/datasetPresentation";

// Curator-facing labels for Atlas's full controlled icon bank (see
// contracts/dataset-public-profile.schema.json's home_card.icon enum).
// A curator may hand-select any of these regardless of dataset domain,
// independent of the automatic domain-keyword fallback in
// datasetPresentation.ts's getDatasetIcon.
const HOME_CARD_ICON_OPTIONS: Array<{ value: DatasetIconName; label: string }> = [
  { value: "telecom-users", label: "Telecom users" },
  { value: "bank-building", label: "Bank building" },
  { value: "chart-line", label: "Chart line" },
  { value: "heart", label: "Heart" },
  { value: "shopping-cart", label: "Shopping cart" },
  { value: "airplane", label: "Airplane" },
  { value: "shield", label: "Shield" },
  { value: "education-cap", label: "Education cap" },
  { value: "energy-bolt", label: "Energy bolt" },
  { value: "home-house", label: "Home house" },
  { value: "agro-leaf", label: "Agro leaf" },
  { value: "logistics-truck", label: "Logistics truck" },
  { value: "factory", label: "Factory" },
  { value: "weather-cloud", label: "Weather cloud" },
  { value: "database", label: "Database" },
  { value: "money-dollar", label: "Money dollar" },
  { value: "globe", label: "Globe" },
  { value: "flask", label: "Flask" },
  { value: "cpu-chip", label: "CPU chip" },
];

const RESULT_PRESET_CARDS = [
  { label: "Risk", value: "risk", requirement: "Requires a compatible binary risk result contract" },
  { label: "Value band", value: "value-band", requirement: "Requires regression result contract" },
  { label: "Target status", value: "target-status", requirement: "Requires target-status semantics" },
  { label: "Severity", value: "severity", requirement: "Requires severity semantics" },
  { label: "Custom", value: "custom", requirement: "Requires custom renderer contract" },
] as const;

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetListing = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
};

type DatasetListingResponse = {
  datasets: DatasetListing[];
};

type DatasetState =
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetListing[] }
  | { status: "error"; message: string };

// GET /admin/datasets's AdminListedDataset shape (registry/list.py, Project
// Spec S0052): every registry-backed Dataset Detail regardless of public
// "Visible Publicly" state or review status -- distinct from DatasetListing
// above, which only ever reflects the public, already-filtered /datasets
// listing. Used to power the header's Dataset Detail selector so Admin can
// pick any registry-backed dataset, not only the ones already public.
type AdminDatasetListing = {
  dataset_slug: string;
  title: string;
  display_title?: string | null;
  summary: string;
  domain: string;
  tags: string[];
  active_release: string | null;
  publication_status: string;
  last_updated: string | null;
};

type AdminDatasetListingResponse = {
  datasets: AdminDatasetListing[];
};

type AdminDatasetState =
  | { status: "loading" }
  | { status: "ready"; datasets: AdminDatasetListing[] }
  | { status: "error"; message: string };

// Project Spec S0121: `code` is optional so every pre-existing unavailable
// literal in this file (which never set it) remains valid -- it is only
// populated for resources sourced from the private authoring-context read
// model, so the bounded error identity the backend already computed
// survives into frontend state instead of being discarded.
type SectionState<T> =
  | { status: "idle" | "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable"; message: string; code?: string };

type ProfileDraft = {
  schema_version: string;
  dataset_slug: string;
  display?: {
    title?: string;
    subtitle?: string;
    problem_summary_title?: string;
    problem_summary_body?: string;
    source_name?: string;
    source_url?: string;
    release_date_label?: string;
    release_date_mode?: "auto" | "manual";
    date_format?: "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";
    canonical_name_fallback?: boolean;
  };
  home_card?: {
    icon?: DatasetIconName;
    background_image_ref?: string | null;
    short_description?: string;
    primary_metric_key?: string | null;
  };
  performance_focus?: PerformanceFocus | null;
  theme?: {
    preset?: DatasetThemePresetId;
  };
  inference_presentation?: {
    bound_predict_view_id?: string | null;
  };
  result_card?: {
    schema_version?: "binary-result-presentation.v1";
    positive_class_probability_label?: string;
    predicted_outcome_label?: string;
    positive_outcome_copy?: string;
    negative_outcome_copy?: string;
    model_section_label?: string;
    interpretation?: {
      preset?: "risk";
      labels?: { high?: string; medium?: string; low?: string };
    };
    // Bounded read-only migration input. Never serialized by profileFromForm.
    submit_button_label?: string;
  };
  documentation?: {
    format?: "markdown";
    content?: string;
  };
};

type PerformanceFocus = {
  focus_id: PerformanceFocusId;
  highlighted_score_id: string;
  visible_scores: PerformanceScore[];
};

type PerformanceScore = {
  score_id: string;
  display_label: string;
  value: string;
  value_source: "canonical" | "manual";
  order: number;
};

type PerformanceFocusId = keyof typeof PERFORMANCE_SCORE_CATALOG;
type PerformanceScoreDraft = PerformanceScore & { visible: boolean };
type PerformanceFocusDraft = {
  focus_id: PerformanceFocusId;
  highlighted_score_id: string;
  scores: PerformanceScoreDraft[];
};

const PERFORMANCE_SCORE_CATALOG = {
  overall_discrimination: [["roc_auc", "ROC-AUC"], ["pr_auc", "PR-AUC"], ["gini_coefficient", "Gini coefficient"], ["ks_statistic", "KS statistic"]],
  positive_class_detection: [["recall", "Recall"], ["precision", "Precision"], ["f1_score", "F1-score"], ["f_beta_score", "F-beta score"], ["pr_auc", "PR-AUC"], ["false_negative_rate", "False Negative Rate"]],
  balanced_classification: [["balanced_accuracy", "Balanced Accuracy"], ["mcc", "MCC"], ["f1_score", "F1-score"], ["accuracy", "Accuracy"], ["recall", "Recall"], ["specificity", "Specificity"], ["cohens_kappa", "Cohen's Kappa"], ["g_mean", "G-Mean"]],
  probability_quality: [["log_loss", "Log Loss"], ["brier_score", "Brier Score"], ["calibration_error", "Calibration Error"], ["calibration_slope", "Calibration Slope"], ["calibration_intercept", "Calibration Intercept"], ["expected_calibration_error", "Expected Calibration Error"]],
  operational_decision: [["precision_at_k", "Precision@K"], ["recall_at_k", "Recall@K"], ["lift_at_k", "Lift@K"], ["gain_at_k", "Gain@K"], ["expected_cost", "Expected Cost"], ["expected_profit", "Expected Profit"], ["net_benefit", "Net Benefit"], ["cost_per_correct_detection", "Cost per Correct Detection"], ["false_positives_at_k", "False Positives at K"], ["false_negatives_at_k", "False Negatives at K"]],
} as const;

const PERFORMANCE_FOCUS_OPTIONS: Array<{ value: PerformanceFocusId; label: string }> = [
  { value: "overall_discrimination", label: "Overall discrimination" },
  { value: "positive_class_detection", label: "Positive-class detection" },
  { value: "balanced_classification", label: "Balanced classification" },
  { value: "probability_quality", label: "Probability quality" },
  { value: "operational_decision", label: "Operational decision" },
];

function defaultPerformanceFocus(focus_id: PerformanceFocusId = "positive_class_detection"): PerformanceFocusDraft {
  const scores = PERFORMANCE_SCORE_CATALOG[focus_id].map(([score_id, display_label], order) => ({
    score_id, display_label, value: "0", value_source: "manual" as const, order, visible: order < 3,
  }));
  return { focus_id, highlighted_score_id: scores[0]?.score_id ?? "", scores };
}

type DraftForm = {
  schema_version: string;
  display_title: string;
  display_subtitle: string;
  problem_summary_title: string;
  problem_summary_body: string;
  source_name: string;
  source_url: string;
  release_date_label: string;
  date_format: "" | "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";
  canonical_name_fallback: boolean;
  home_card_icon: "" | DatasetIconName;
  background_image_ref: string;
  short_description: string;
  primary_metric_key: string;
  performance_focus: PerformanceFocusDraft;
  theme_preset: DatasetThemePresetId;
  bound_predict_view_id: string;
  positive_class_probability_label: string;
  predicted_outcome_label: string;
  positive_outcome_copy: string;
  negative_outcome_copy: string;
  // Project Spec S0110: read-only migration context only -- the Result Card
  // tab no longer renders or edits this field, and profileFromForm never
  // writes it back. Populated by formFromProfile purely so the Inference
  // Form tab's customization-loading effect can seed a migration candidate
  // from the currently loaded profile's legacy value.
  legacy_submit_button_label: string;
  model_section_label: string;
  interpretation_preset: "risk";
  interpretation_high: string;
  interpretation_medium: string;
  interpretation_low: string;
  // Project Spec S0196: the committed workspace Markdown source, i.e. the
  // most recent Documentation-tab Save -- never the transient, unsaved
  // editing-buffer text. Participates in the same profileFromForm/
  // formFromProfile round trip and workspace dirty-state as every other
  // field here.
  documentation: string;
};

type DraftError = {
  code?: string;
  field?: string | null;
  message?: string;
};

type PublishSnapshot = {
  schema_version?: string;
  source_draft_schema_version?: string;
  published_at?: string;
  active_release_at_publish_time?: string;
  profile?: Partial<ProfileDraft>;
};

type ProfileHydration = {
  source: "current_release_snapshot" | "fresh_promotion_baseline";
  active_release: string | null;
};

// Project Spec S0116: this state no longer carries a visibility flag -- it
// tracks only the content-publication ("Publish changes") lifecycle for the
// workspace toolbar. Public/private visibility now flows exclusively through
// PublicationProjectionState below, hydrated from the S0115 authority.
type PublicationState =
  | { status: "idle"; publishedProfile: ProfileDraft | null; message: string }
  | { status: "publishing"; publishedProfile: ProfileDraft | null }
  | { status: "published"; publishedProfile: ProfileDraft; publishedAt?: string }
  | { status: "invalid"; publishedProfile: ProfileDraft | null; errors: DraftError[] }
  | { status: "unavailable"; publishedProfile: ProfileDraft | null; message: string };

// Project Spec S0116: strict local type for GET
// /admin/datasets/{slug}/publication-state's response (api/admin_profile_visibility.py's
// get_dataset_publication_state). This is the sole authority for the
// Publishing tab's switch, the header Public/Private badge, the "Open public
// Dataset Detail page" action, and the operational console -- never
// reconstructed from the public dataset listing or from PublicationState.
type AdminPublicationStateProjection = {
  dataset_slug: string;
  active_release: string | null;
  visibility: {
    configured_visible: boolean;
    source: "explicit_record" | "default_visible";
    record_status:
      | "valid"
      | "missing"
      | "unreadable"
      | "invalid_json"
      | "invalid_shape"
      | "invalid_visible"
      | "invalid_updated_at";
    updated_at: string | null;
    effective_visible: boolean;
  };
  review: {
    status: "ready" | "needs_review";
    approval_allowed: boolean;
    approval_blockers: string[];
  };
  snapshot: {
    status: "missing" | "current_release" | "stale_release" | "invalid";
    exists: boolean;
    published_at: string | null;
    active_release_at_publish_time: string | null;
    matches_active_release: boolean | null;
  };
  public_access: {
    reachable: boolean;
    blockers: string[];
    observations: string[];
  };
};

// Bounded request-state machine for the publication-state GET, keyed to the
// selected dataset so a superseded response can never overwrite a newer
// selection (see the publicationProjectionRequestRef guard below).
type PublicationProjectionState =
  | { status: "idle" }
  | { status: "loading"; datasetSlug: string }
  | { status: "ready"; datasetSlug: string; projection: AdminPublicationStateProjection }
  | { status: "saving"; datasetSlug: string; projection: AdminPublicationStateProjection; pendingVisible: boolean }
  // Project Spec S0125: mirrors "saving" for the review-approval write --
  // a distinct status (rather than reusing "saving") so the Publishing tab
  // and console can tell which of the two independent writes is in flight.
  | { status: "approving"; datasetSlug: string; projection: AdminPublicationStateProjection }
  | { status: "unavailable"; datasetSlug: string; message: string };

type DraftState =
  | { status: "idle"; message: string }
  | { status: "loading" }
  | { status: "ready"; draftExists: boolean; profile: ProfileDraft | null }
  | { status: "saved"; profile: ProfileDraft }
  | { status: "invalid"; errors: DraftError[] }
  | { status: "unavailable"; message: string };

type MetricsPayload = {
  evaluation?: {
    metrics?: Record<string, number | string | null>;
    sample_size?: number;
  };
};

// Matches GET /datasets/{slug}/contract's real response shape -- the same
// shape web/src/components/InferenceForm/InferenceForm.tsx's ContractPayload
// requires -- not a speculative {fields|inputs|input_schema} guess.
type ContractField = {
  name: string;
  label: string;
  input_type: "number" | "select" | "checkbox";
  optional: boolean;
  display_order: number;
  description?: string;
  options?: { value: string; label: string }[];
};

type ContractPayload = {
  schema_version: string;
  features: ContractField[];
};

type ContractEnvelope = {
  contract: ContractPayload;
  result_contract?: BinaryResultContract | unknown;
};

type ResultContractState =
  | { status: "idle" | "loading" }
  | { status: "available"; semantics: BinaryResultSemantics }
  | { status: "unavailable"; message: string }
  | { status: "transport_failure"; message: string }
  | { status: "incompatible"; message: string };

type ContextPayload = {
  title?: string;
  summary?: string;
  description?: string;
  domain?: string;
  tags?: string[];
  use_case?: string;
  problem_type?: string;
  prediction_target_description?: string;
};

type PredictView = {
  view_id?: string;
  dataset_slug?: string;
  display?: {
    title?: string;
    summary?: string;
    description?: string;
  };
};

// GET /admin/datasets/{slug}/authoring-context's `dataset` resource
// projection (Project Spec S0121, registry/list.py's AdminListedDataset
// shape) -- deliberately not DatasetListing, which is the *public*
// /datasets/{slug} shape and carries a `visibility` field this private,
// visibility-independent read model has no reason to expose.
type AuthoringDatasetProjection = {
  dataset_slug: string;
  title: string;
  display_title?: string | null;
  summary: string;
  domain: string;
  tags: string[];
  active_release?: string | null;
  publication_status?: string;
};

// Project Spec S0121: the bounded per-resource shape every field of
// GET /admin/datasets/{slug}/authoring-context's envelope uses -- either
// `{status: "ready", data}` or `{status: "unavailable", error}`, never a bare
// null/{}/[] standing in for failure.
type AuthoringResourceEnvelope<T> =
  | { status: "ready"; data: T }
  | { status: "unavailable"; error: { type: string; code: string; message: string } };

type AuthoringContextEnvelope = {
  dataset_slug: string;
  active_release: string;
  dataset: AuthoringResourceEnvelope<AuthoringDatasetProjection>;
  context: AuthoringResourceEnvelope<ContextPayload>;
  contract: AuthoringResourceEnvelope<ContractEnvelope>;
  inference_guidance?: AuthoringResourceEnvelope<unknown>;
  metrics: AuthoringResourceEnvelope<MetricsPayload>;
  visualizations: AuthoringResourceEnvelope<unknown>;
  views: AuthoringResourceEnvelope<PredictView[]>;
};

type ReadOnlyData = {
  dataset: SectionState<AuthoringDatasetProjection>;
  context: SectionState<ContextPayload>;
  contract: SectionState<ContractPayload>;
  inferenceGuidance: SectionState<unknown>;
  resultContract: ResultContractState;
  metrics: SectionState<MetricsPayload>;
  visualizations: SectionState<unknown>;
  views: SectionState<PredictView[]>;
};

// One editable row per contract field. Array order IS the field's
// display_order_hint (index + 1 at save time) -- there is no separate
// order input, only up/down reordering, so ordering always stays a
// coherent, gap-free 1..N sequence as fields are moved.
type FieldHintDraft = {
  field_name: string;
  display_label: string;
  explanatory_copy: string;
  group: string;
  hidden: boolean;
  required: boolean;
};

// Array order IS the rendered group order (contracts/predict-view-customization
// .schema.json's groups[] carries no separate order field; InferenceForm's
// renderGrouped() iterates groups in array order), so group ordering is also
// edited via up/down reordering only.
type GroupDraft = {
  group_id: string;
  label: string;
  description: string;
};

// Project Spec S0110: view-level presentation copy carried by the draft.
// heading/description/usage_guidance are not yet exposed as editable Admin
// UI fields, but must still be preserved byte-for-byte across an unrelated
// field/group edit and round-tripped on save -- see
// customizationDraftFromRecord/customizationDraftToRecord below.
// submit_button_label is the only field this builder currently edits
// (InferenceFormTab).
type ViewCopyDraft = {
  heading: string;
  description: string;
  usage_guidance: string;
  submit_button_label: string;
};

const emptyViewCopyDraft: ViewCopyDraft = {
  heading: "",
  description: "",
  usage_guidance: "",
  submit_button_label: "",
};

type CustomizationEditorDraft = {
  fieldHints: FieldHintDraft[];
  groups: GroupDraft[];
  viewCopy: ViewCopyDraft;
};

type CustomizationError = {
  code?: string;
  field?: string | null;
  message?: string;
};

// Project Spec S0099: the manual "Load customization" gate is replaced by an
// automatic, contract-driven bootstrap keyed on
// (selected dataset slug, resolved bound predict view id, active-release
// public contract readiness). Absence, compatibility, incompatibility, and
// transport failure are distinct, testable states rather than one
// ambiguous "idle" -- "ready_base" (no stored customization, or the public
// contract could not be resolved for compatibility classification) and
// "ready_overlaid" (a compatible stored customization was applied) both
// render the S0097 builder from a real draft; "incompatible_overlay_ignored"
// also renders the builder from a clean contract-derived draft, but carries
// the historical customization's sanitized errors for a concise warning
// instead of applying it.
type CustomizationEditorState =
  | { status: "no_view_bound" }
  | { status: "contract_unavailable" }
  | { status: "loading" }
  | { status: "ready_base"; draft: CustomizationEditorDraft; recordExists: boolean }
  | { status: "ready_overlaid"; draft: CustomizationEditorDraft; recordExists: boolean }
  | {
      status: "incompatible_overlay_ignored";
      draft: CustomizationEditorDraft;
      recordExists: boolean;
      errors: CustomizationError[];
    }
  | { status: "saving"; draft: CustomizationEditorDraft }
  | { status: "saved"; draft: CustomizationEditorDraft }
  | { status: "invalid"; draft: CustomizationEditorDraft; errors: CustomizationError[] }
  | { status: "unavailable"; message: string };

// Every status whose draft the S0097 builder/Live Preview can render.
function customizationDraftOf(state: CustomizationEditorState): CustomizationEditorDraft | null {
  switch (state.status) {
    case "ready_base":
    case "ready_overlaid":
    case "incompatible_overlay_ignored":
    case "saving":
    case "saved":
    case "invalid":
      return state.draft;
    default:
      return null;
  }
}

// Presentation-only derived placement for a field_hint: "bank" (hidden),
// "no-subgroup" (visible, ungrouped/unresolved group), or a literal
// group_id (visible, grouped). Never persisted directly -- always derived
// from FieldHintDraft.hidden/group so it can never drift from the saved
// contract shape.
type FieldZoneKey = string;

const FIELD_BANK_ZONE: FieldZoneKey = "bank";
const NO_SUBGROUP_ZONE: FieldZoneKey = "no-subgroup";

// Subgroup drag-and-drop/reorder state. Field drag-and-drop uses its own
// CustomizationFieldDragState below -- the two are shaped too differently
// (index-only vs. zone+index) to share one discriminated union usefully.
type CustomizationGroupDragState = {
  sourceIndex: number;
  targetIndex: number;
  pointerX: number;
  pointerY: number;
  label: string;
};

type CustomizationFieldDragState = {
  fieldName: string;
  sourceZone: FieldZoneKey;
  targetZone: FieldZoneKey;
  targetIndex: number;
  pointerX: number;
  pointerY: number;
  label: string;
  // Project Spec S0104: origin point and real-movement flag for the
  // full-chip drag threshold -- a pointer down/up with no movement beyond
  // FIELD_DRAG_THRESHOLD_PX is a click, not a drag, and must not suppress
  // the chip's normal double-click-to-edit behavior.
  startX: number;
  startY: number;
  didMove: boolean;
};

const FIELD_DRAG_THRESHOLD_PX = 4;

// Project Spec S0104: opt-out marker for a future interactive chip
// descendant (e.g. a button) that must not start a drag on pointer down.
// No current chip descendant carries this marker -- the six-dot handle,
// field name, and Required tag are all valid drag-start targets.
function isChipDragExcluded(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("[data-chip-drag-exclude]") !== null;
}

const emptyCustomizationEditorState: CustomizationEditorState = { status: "no_view_bound" };

// Project Spec S0104: a field with no compatible persisted field-hint
// decision defaults to hidden = !required (optional fields start in the
// Field bank, required fields start visible in No subgroup) rather than
// always visible -- see customizationDraftFromRecord below for the same
// rule applied only to a contract field the loaded record never covered.
function emptyCustomizationDraft(fields: ContractField[]): CustomizationEditorDraft {
  return {
    fieldHints: fields.map((field) => {
      const required = !field.optional;
      return {
        field_name: field.name,
        display_label: "",
        explanatory_copy: "",
        group: "",
        hidden: !required,
        required,
      };
    }),
    groups: [],
    viewCopy: { ...emptyViewCopyDraft },
  };
}

// Project Spec S0104: deterministic, position-stable fallback for a
// historical group whose label is blank -- never the raw group_id (see
// customizationDraftFromRecord below, which also writes this fallback into
// the active draft so the operator can edit/persist it intentionally).
function deterministicGroupLabel(index: number): string {
  return `Group ${index + 1}`;
}

// Project Spec S0104: the next collision-safe internal group identity.
// Based on the highest existing "group-N" numeric suffix (not array
// length), so a deletion gap (e.g. [group-1, group-3]) never reproduces an
// already-used id (-> group-4, not group-3). Non-standard historical ids
// (e.g. "account") are ignored for the max computation but still checked
// for exact-collision safety.
function nextGroupIdentity(groups: GroupDraft[]): { group_id: string; label: string } {
  const existingIds = new Set(groups.map((group) => group.group_id));
  let highestSuffix = 0;
  for (const group of groups) {
    const match = /^group-(\d+)$/.exec(group.group_id);
    if (match) {
      highestSuffix = Math.max(highestSuffix, Number(match[1]));
    }
  }
  let candidateSuffix = highestSuffix + 1;
  while (existingIds.has(`group-${candidateSuffix}`)) {
    candidateSuffix += 1;
  }
  return { group_id: `group-${candidateSuffix}`, label: `Group ${candidateSuffix}` };
}

function customizationDraftFromRecord(
  record: PredictViewCustomization,
  fields: ContractField[],
): CustomizationEditorDraft {
  const hintMap = new Map(record.field_hints.map((hint) => [hint.field_name, hint]));
  const requiredMap = new Map(fields.map((field) => [field.name, !field.optional]));

  const sortedFields = [...fields].sort((a, b) => {
    const hintA = hintMap.get(a.name);
    const hintB = hintMap.get(b.name);
    const keyA = hintA?.display_order_hint ?? a.display_order;
    const keyB = hintB?.display_order_hint ?? b.display_order;
    return keyA - keyB;
  });

  // Project Spec S0104: a historical group with an empty/blank label gets a
  // deterministic generic label written directly into the active draft
  // (never the raw group_id) so it renders as a real, editable title and
  // can be persisted intentionally the next time the operator publishes.
  const groups = record.groups.map((group, index) => ({
    group_id: group.group_id,
    label: group.label && group.label.trim() ? group.label : deterministicGroupLabel(index),
    description: group.description ?? "",
  }));

  const fieldHints = sortedFields.map((field) => {
    const hint = hintMap.get(field.name);
    const required = requiredMap.get(field.name) ?? false;
    return {
      field_name: field.name,
      display_label: hint?.display_label ?? "",
      explanatory_copy: hint?.explanatory_copy ?? "",
      group: hint?.group ?? "",
      // A field the loaded record never covered (a contract field added
      // since the customization was last saved) follows the same
      // required/optional default as a base draft; a field the record does
      // cover keeps its exact persisted hidden decision, even if that
      // decision predates this default rule.
      hidden: hint ? hint.hidden ?? false : !required,
      required,
    };
  });

  // A previously saved record may not already satisfy the deterministic
  // flattening rule below (e.g. it predates this builder) -- reflow on load
  // so every loaded draft starts from the canonical macro order.
  const viewCopy: ViewCopyDraft = {
    heading: record.view_copy?.heading ?? "",
    description: record.view_copy?.description ?? "",
    usage_guidance: record.view_copy?.usage_guidance ?? "",
    submit_button_label: record.view_copy?.submit_button_label ?? "",
  };

  return { fieldHints: reflowFieldHints(fieldHints, groups), groups, viewCopy };
}

function customizationDraftToRecord(draft: CustomizationEditorDraft): {
  field_hints: FieldHint[];
  groups: GroupDef[];
  view_copy?: NonNullable<PredictViewCustomization["view_copy"]>;
} {
  const viewCopy: NonNullable<PredictViewCustomization["view_copy"]> = {};
  if (draft.viewCopy.heading.trim()) viewCopy.heading = draft.viewCopy.heading.trim();
  if (draft.viewCopy.description.trim()) viewCopy.description = draft.viewCopy.description.trim();
  if (draft.viewCopy.usage_guidance.trim()) viewCopy.usage_guidance = draft.viewCopy.usage_guidance.trim();
  if (draft.viewCopy.submit_button_label.trim()) viewCopy.submit_button_label = draft.viewCopy.submit_button_label.trim();

  return {
    field_hints: draft.fieldHints.map((field, index) => {
      const hint: FieldHint = { field_name: field.field_name, display_order_hint: index + 1 };
      if (field.display_label.trim()) hint.display_label = field.display_label.trim();
      if (field.explanatory_copy.trim()) hint.explanatory_copy = field.explanatory_copy.trim();
      if (field.group) hint.group = field.group;
      if (field.hidden) hint.hidden = true;
      return hint;
    }),
    groups: draft.groups.map((group) => {
      const def: GroupDef = { group_id: group.group_id, label: group.label };
      if (group.description.trim()) def.description = group.description.trim();
      return def;
    }),
    ...(Object.keys(viewCopy).length > 0 ? { view_copy: viewCopy } : {}),
  };
}

// Project Spec S0110: seeds a customization draft's submit_button_label from
// the legacy published profile value only when the draft does not already
// carry one -- a pure local-state seed, never a storage write (see the
// customization-loading effect below, which computes the dirty-state
// baseline from the pre-seed draft so this migration candidate naturally
// participates in the shared Publish changes dirty-state without inventing a
// second dirty-tracking mechanism).
function withMigratedSubmitLabel(draft: CustomizationEditorDraft, legacySubmitButtonLabel: string): CustomizationEditorDraft {
  if (draft.viewCopy.submit_button_label.trim()) {
    return draft;
  }
  const legacy = legacySubmitButtonLabel.trim();
  if (!legacy) {
    return draft;
  }
  return { ...draft, viewCopy: { ...draft.viewCopy, submit_button_label: legacy } };
}

// Project Spec S0103: the workspace dirty-state baseline for the Inference
// Form customization is a deterministic string derived from exactly the
// same persistence projection customizationDraftToRecord already builds for
// the PUT request body -- so a freshly loaded/saved draft and an in-progress
// edited draft are always compared through one shared normalizer, never two
// divergent ones.
function normalizedCustomizationDraft(draft: CustomizationEditorDraft): string {
  return stableJson(customizationDraftToRecord(draft));
}

// A null baseline means no customization draft has been established yet for
// the current dataset/view/contract identity (still loading, no view bound,
// contract unavailable, or load failed) -- in every one of those states
// customizationDraftOf also returns null, so there is nothing to compare and
// this correctly reports "not dirty" rather than inventing a false positive.
function isCustomizationRecordDirty(state: CustomizationEditorState, baseline: string | null): boolean {
  const draft = customizationDraftOf(state);
  if (!draft || baseline === null) {
    return false;
  }
  return normalizedCustomizationDraft(draft) !== baseline;
}

function moveItem<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function moveItemToIndex<T>(items: T[], sourceIndex: number, targetIndex: number): T[] {
  if (
    sourceIndex === targetIndex ||
    sourceIndex < 0 ||
    targetIndex < 0 ||
    sourceIndex >= items.length ||
    targetIndex >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [item] = next.splice(sourceIndex, 1);
  next.splice(targetIndex, 0, item);
  return next;
}

// A field's rendered zone is fully derived from hidden/group -- never a
// separate persisted concept -- so the bank/subgroup/no-subgroup split can
// never drift from what customizationDraftToRecord actually saves.
function fieldZoneKey(field: FieldHintDraft, validGroupIds: Set<string>): FieldZoneKey {
  if (field.hidden) return FIELD_BANK_ZONE;
  if (field.group && validGroupIds.has(field.group)) return field.group;
  return NO_SUBGROUP_ZONE;
}

function zoneFieldEntries(draft: CustomizationEditorDraft, zone: FieldZoneKey): FieldHintDraft[] {
  const validGroupIds = new Set(draft.groups.map((group) => group.group_id));
  return draft.fieldHints.filter((field) => fieldZoneKey(field, validGroupIds) === zone);
}

// Keeps fieldHints ordered as: every subgroup's visible fields (in groups[]
// order), then visible No subgroup fields, then hidden Field bank fields --
// the deterministic flattening rule the saved display_order_hint projection
// relies on (customizationDraftToRecord assigns display_order_hint from
// array index). Preserves each zone's own relative order; only
// re-partitions macro block order, so it is safe to call after every draft
// mutation, including ones (like subgroup reorder) that don't move fields.
function reflowFieldHints(fieldHints: FieldHintDraft[], groups: GroupDraft[]): FieldHintDraft[] {
  const validGroupIds = new Set(groups.map((group) => group.group_id));
  const buckets = new Map<string, FieldHintDraft[]>();
  buckets.set(FIELD_BANK_ZONE, []);
  buckets.set(NO_SUBGROUP_ZONE, []);
  for (const group of groups) buckets.set(group.group_id, []);
  for (const field of fieldHints) {
    const zone = fieldZoneKey(field, validGroupIds);
    buckets.get(zone)!.push(field);
  }
  return [
    ...groups.flatMap((group) => buckets.get(group.group_id) ?? []),
    ...buckets.get(NO_SUBGROUP_ZONE)!,
    ...buckets.get(FIELD_BANK_ZONE)!,
  ];
}

// Bank membership always wins (hidden: true, group cleared): a field
// dropped in the bank is presentation-hidden regardless of any prior group.
// No subgroup / subgroup membership always clears hidden: a field dropped
// into the public layout can never retain a stale hidden flag.
function applyFieldZonePatch(field: FieldHintDraft, zone: FieldZoneKey): FieldHintDraft {
  if (zone === FIELD_BANK_ZONE) {
    return { ...field, hidden: true, group: "" };
  }
  if (zone === NO_SUBGROUP_ZONE) {
    return { ...field, hidden: false, group: "" };
  }
  return { ...field, hidden: false, group: zone };
}

// Moves a single field to a specific position within a destination zone,
// which may be its current zone (a same-zone reorder). Every other zone's
// relative field order is left untouched.
function moveFieldToZone(
  draft: CustomizationEditorDraft,
  fieldName: string,
  destinationZone: FieldZoneKey,
  destinationIndex: number,
): CustomizationEditorDraft {
  const moved = draft.fieldHints.find((field) => field.field_name === fieldName);
  if (!moved) {
    return draft;
  }
  const patched = applyFieldZonePatch(moved, destinationZone);
  const withoutMoved = draft.fieldHints.filter((field) => field.field_name !== fieldName);
  const validGroupIds = new Set(draft.groups.map((group) => group.group_id));
  const destinationZoneFields = withoutMoved.filter(
    (field) => fieldZoneKey(field, validGroupIds) === destinationZone,
  );
  const clampedIndex = Math.max(0, Math.min(destinationIndex, destinationZoneFields.length));
  const anchor = destinationZoneFields[clampedIndex];

  const merged: FieldHintDraft[] = [];
  let inserted = false;
  for (const field of withoutMoved) {
    if (!inserted && anchor && field.field_name === anchor.field_name) {
      merged.push(patched);
      inserted = true;
    }
    merged.push(field);
  }
  if (!inserted) {
    merged.push(patched);
  }

  return { ...draft, fieldHints: reflowFieldHints(merged, draft.groups) };
}

const emptyReadOnlyData: ReadOnlyData = {
  dataset: { status: "idle" },
  context: { status: "idle" },
  contract: { status: "idle" },
  inferenceGuidance: { status: "idle" },
  resultContract: { status: "idle" },
  metrics: { status: "idle" },
  visualizations: { status: "idle" },
  views: { status: "idle" },
};

const emptyPublicationState: PublicationState = {
  status: "idle",
  publishedProfile: null,
  message: "No published snapshot is known in this admin session.",
};

const emptyPublicationProjectionState: PublicationProjectionState = { status: "idle" };

const adminTabs: TabItem[] = [
  {
    id: "public-content",
    label: "Public Content",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M7 3.5h7l3 3V20H7z" />
        <path d="M14 3.5V7h3" />
        <path d="M10 11h4M10 14h5M10 17h3" />
      </svg>
    ),
  },
  {
    id: "metadata-card",
    label: "Metadata & Card",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M12 4.5 20 8v8l-8 3.5L4 16V8l8-3.5Z" />
        <path d="M12 12v7.5M20 8l-8 4-8-4" />
      </svg>
    ),
  },
  {
    id: "theme-preset",
    label: "Theme Preset",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M12 4a8 8 0 0 0 0 16h1.5a1.7 1.7 0 0 0 1.3-2.8 1.7 1.7 0 0 1 1.3-2.8H18A6 6 0 0 0 12 4Z" />
      </svg>
    ),
  },
  {
    id: "inference-form",
    label: "Inference Form",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M6 5h12v14H6z" />
        <path d="M9 9h6M9 13h6M9 17h3" />
      </svg>
    ),
  },
  {
    id: "result-card",
    label: "Result Card",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M5 5h14v14H5z" />
        <path d="M8 15h8M8 11h8M8 8h4" />
      </svg>
    ),
  },
  {
    id: "documentation",
    label: "Documentation",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M5 4.5h10a4 4 0 0 1 4 4V20H9a4 4 0 0 1-4-4Z" />
        <path d="M9 20a4 4 0 0 1 4-4h6M9 8h6M9 11h5" />
      </svg>
    ),
  },
  {
    id: "publishing",
    label: "Publishing",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M20 4 4 11l6 2 2 6 8-15Z" />
      </svg>
    ),
  },
  {
    id: "live-preview",
    label: "Live Preview",
    showIndicator: true,
    icon: (
      <svg viewBox="0 0 24 24">
        <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
        <circle cx="12" cy="12" r="2.7" />
      </svg>
    ),
  },
];

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
};

const headerStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  justifyContent: "space-between",
  gap: "var(--atlas-space-5)",
  alignItems: "flex-start",
};

const fieldStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const labelStyle: CSSProperties = {
  color: "var(--atlas-color-text-subtle)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  textTransform: "uppercase",
};

const inputStyle: CSSProperties = {
  width: "100%",
  minHeight: "2.75rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  background: "var(--atlas-color-surface)",
};

const textareaStyle: CSSProperties = {
  ...inputStyle,
  minHeight: "7rem",
  padding: "var(--atlas-space-3)",
  resize: "vertical",
};

const fieldStyleWithCounter: CSSProperties = {
  ...fieldStyle,
  position: "relative",
};

const fieldLabelRowStyle: CSSProperties = {
  ...labelStyle,
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--atlas-space-1)",
};

const requiredMarkerStyle: CSSProperties = {
  color: "var(--atlas-color-danger)",
};

const counterPaddingStyle: CSSProperties = {
  paddingRight: "3.75rem",
};

const fieldCounterStyle: CSSProperties = {
  position: "absolute",
  right: "var(--atlas-space-3)",
  bottom: "var(--atlas-space-2)",
  color: "var(--atlas-color-text-muted)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 700,
  pointerEvents: "none",
};

const narrowFieldRowStyle: CSSProperties = {
  display: "grid",
  maxWidth: "32rem",
};

const panelStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  background: "var(--atlas-color-surface)",
  boxShadow: "var(--atlas-shadow-sm)",
};

const tabPanelStyle: CSSProperties = {
  ...panelStyle,
  minHeight: "24rem",
  alignContent: "start",
};

const twoColumnGridStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  gridTemplateColumns: "repeat(auto-fit, minmax(18rem, 1fr))",
};

const readOnlyFieldStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-1)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-3)",
  background: "var(--atlas-color-surface-muted)",
};

const readOnlyValueStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text)",
  fontWeight: 700,
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text-muted)",
};

const actionButtonStyle: CSSProperties = {
  minHeight: "2.5rem",
  border: "1px solid var(--atlas-color-accent)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-4)",
  color: "var(--atlas-color-surface)",
  font: "inherit",
  fontWeight: 800,
  background: "var(--atlas-color-accent)",
  cursor: "pointer",
};

const secondaryButtonStyle: CSSProperties = {
  ...actionButtonStyle,
  borderColor: "var(--atlas-color-border-strong)",
  color: "var(--atlas-color-accent-strong)",
  background: "var(--atlas-color-surface)",
};

const disabledButtonStyle: CSSProperties = {
  ...secondaryButtonStyle,
  color: "var(--atlas-color-text-subtle)",
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
};

const iconActionButtonStyle: CSSProperties = {
  ...secondaryButtonStyle,
  width: "2.75rem",
  minWidth: "2.75rem",
  padding: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};

const iconActionButtonDisabledStyle: CSSProperties = {
  ...disabledButtonStyle,
  width: "2.75rem",
  minWidth: "2.75rem",
  padding: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};

const actionIconStyle: CSSProperties = {
  width: "1.15rem",
  height: "1.15rem",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

const workspaceToolbarStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "flex-start",
  gap: "var(--atlas-space-3)",
};

const dragSourceStyle: CSSProperties = {
  opacity: 0.45,
  outline: "2px solid var(--atlas-color-accent)",
  outlineOffset: "2px",
};

const dragTargetStyle: CSSProperties = {
  borderColor: "var(--atlas-color-accent)",
  boxShadow: "0 0 0 2px color-mix(in srgb, var(--atlas-color-accent) 24%, transparent)",
};

const dragGhostStyle: CSSProperties = {
  position: "fixed",
  zIndex: 2000,
  pointerEvents: "none",
  transform: "translate(0.75rem, 0.75rem)",
  maxWidth: "22rem",
  border: "1px solid var(--atlas-color-accent)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  background: "var(--atlas-color-surface)",
  boxShadow: "var(--atlas-shadow-md)",
  fontWeight: 800,
};

const alertStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
  border: "1px solid var(--atlas-color-warning)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  color: "var(--atlas-color-text)",
  background: "var(--atlas-color-warning-muted)",
};

const fieldChipSourceStyle: CSSProperties = {
  opacity: 0.45,
};

const fieldChipInsertionTargetStyle: CSSProperties = {
  boxShadow: "inset 0 2px 0 0 var(--atlas-color-accent)",
};

const fieldZoneActiveStyle: CSSProperties = {
  borderColor: "var(--atlas-color-accent)",
  background: "var(--atlas-color-accent-muted)",
};

const cardTitleStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text)",
  fontSize: "var(--atlas-text-xl)",
  fontWeight: 800,
};

const modalBackdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "var(--atlas-space-5)",
  background: "rgba(15, 23, 42, 0.55)",
  zIndex: 2000,
};

const modalCardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  width: "min(32rem, 100%)",
  maxHeight: "90vh",
  overflowY: "auto",
};

const modalActionsStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "var(--atlas-space-3)",
};

function TabWorkspace({ children, eyebrow, helper }: { children: ReactNode; eyebrow: string; helper?: string }) {
  return (
    <div className="dataset-admin-tab-workspace">
      <div className="dataset-admin-tab-workspace__intro">
        <p className="dataset-admin-tab-workspace__eyebrow">{eyebrow}</p>
        {helper ? <p className="dataset-admin-tab-workspace__helper">{helper}</p> : null}
      </div>
      {children}
    </div>
  );
}

// Shared by both DatasetListing (the public /datasets listing) and
// AdminDatasetListing (the Admin-only /admin/datasets listing) -- both
// structurally satisfy this, and these helpers keep dataset_slug as identity
// while resolving the Admin-visible display title for label rendering.
type DatasetLabelSource = { dataset_slug: string; title: string; display_title?: string | null };

function getDatasetLabel(dataset?: DatasetLabelSource) {
  return dataset?.display_title?.trim() || dataset?.title || dataset?.dataset_slug || "No dataset selected";
}

function getDatasetSelectorValue(dataset?: DatasetLabelSource) {
  return dataset ? getDatasetLabel(dataset) : "";
}

// The header renders exactly one publication/private tag for the selected
// Dataset Detail (Project Spec S0058) -- whether it is actually reachable on
// the public site right now, the same real per-dataset fact the public
// /datasets listing itself uses. The Publishing tab's own in-session
// Draft/Unpublished Changes/Hidden lifecycle labels remain inside that tab's
// own status/current-state elements and are never duplicated in the header.
function registryVisibilityVariant(isPublic: boolean): "published" | "hidden" {
  return isPublic ? "published" : "hidden";
}

function registryVisibilityTone(isPublic: boolean): "success" | "neutral" {
  return isPublic ? "success" : "neutral";
}

type DatasetComboBoxProps = {
  datasets: AdminDatasetListing[];
  disabled: boolean;
  query: string;
  selectedDataset?: AdminDatasetListing;
  stateStatus: AdminDatasetState["status"];
  onNormalize: () => void;
  onQueryChange: (value: string) => void;
};

function DatasetComboBox({
  datasets,
  disabled,
  onNormalize,
  onQueryChange,
  query,
  selectedDataset,
  stateStatus,
}: DatasetComboBoxProps) {
  const [open, setOpen] = useState(false);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const selectedValue = getDatasetSelectorValue(selectedDataset);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredDatasets = normalizedQuery
    ? datasets.filter((dataset) => {
        const selectorValue = getDatasetSelectorValue(dataset).toLowerCase();
        return selectorValue.includes(normalizedQuery) || dataset.dataset_slug.toLowerCase().includes(normalizedQuery);
      })
    : datasets;
  const activeOptionId = filteredDatasets.some((dataset) => dataset.dataset_slug === activeSlug)
    ? `dataset-admin-option-${activeSlug}`
    : undefined;
  const triggerText =
    stateStatus === "loading"
      ? "Loading datasets..."
      : stateStatus === "error"
      ? "Datasets unavailable"
      : selectedValue || "No datasets available";

  function closeAndNormalize() {
    setOpen(false);
    setActiveSlug(null);
    onNormalize();
  }

  function selectDataset(dataset: AdminDatasetListing) {
    onQueryChange(getDatasetSelectorValue(dataset));
    setOpen(false);
    setActiveSlug(null);
  }

  function moveActiveOption(direction: 1 | -1) {
    if (filteredDatasets.length === 0) {
      return;
    }
    const currentIndex = filteredDatasets.findIndex((dataset) => dataset.dataset_slug === activeSlug);
    const nextIndex =
      currentIndex === -1
        ? direction === 1
          ? 0
          : filteredDatasets.length - 1
        : (currentIndex + direction + filteredDatasets.length) % filteredDatasets.length;
    setActiveSlug(filteredDatasets[nextIndex].dataset_slug);
  }

  function handleFilterKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      closeAndNormalize();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActiveOption(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActiveOption(-1);
    } else if (event.key === "Enter") {
      const activeDataset = filteredDatasets.find((dataset) => dataset.dataset_slug === activeSlug);
      if (activeDataset) {
        event.preventDefault();
        selectDataset(activeDataset);
      }
    }
  }

  return (
    <div className={["dataset-combobox", open ? "is-open" : ""].filter(Boolean).join(" ")}>
      <button
        aria-controls="dataset-admin-selector-options"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Dataset"
        className="dataset-combobox__trigger"
        disabled={disabled}
        onClick={() => {
          setOpen((current) => {
            const next = !current;
            // Opening should let the operator browse the full listing, not a
            // filter carried over from the currently selected dataset's own
            // label; closing without picking a new option restores it.
            if (next) {
              onQueryChange("");
            } else {
              onNormalize();
            }
            return next;
          });
          setActiveSlug(null);
        }}
        type="button"
      >
        <span className="dataset-combobox__value">{triggerText}</span>
        <svg aria-hidden="true" className="dataset-combobox__chevron" viewBox="0 0 24 24">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div className="dataset-combobox__menu">
          <label className="sr-only" htmlFor="dataset-admin-filter">
            Filter datasets
          </label>
          <input
            aria-activedescendant={activeOptionId}
            aria-controls="dataset-admin-selector-options"
            autoComplete="off"
            className="dataset-combobox__filter"
            id="dataset-admin-filter"
            onBlur={onNormalize}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={handleFilterKeyDown}
            placeholder="Filter datasets..."
            type="search"
            value={query}
          />
          <div
            aria-label="Available datasets"
            className="dataset-combobox__options"
            id="dataset-admin-selector-options"
            role="listbox"
          >
            {filteredDatasets.map((dataset) => {
              const optionValue = getDatasetSelectorValue(dataset);
              const selected = dataset.dataset_slug === selectedDataset?.dataset_slug;
              return (
                <button
                  aria-selected={selected}
                  className={["dataset-combobox__option", selected ? "is-selected" : ""].filter(Boolean).join(" ")}
                  id={`dataset-admin-option-${dataset.dataset_slug}`}
                  key={dataset.dataset_slug}
                  onClick={() => selectDataset(dataset)}
                  onMouseDown={(event) => event.preventDefault()}
                  role="option"
                  type="button"
                >
                  {optionValue}
                </button>
              );
            })}
          </div>
          {filteredDatasets.length === 0 ? <p className="dataset-combobox__empty">No datasets found.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function emptyDraftForm(datasetSlug = ""): DraftForm {
  return {
    schema_version: "1.0.0",
    display_title: "",
    display_subtitle: "",
    problem_summary_title: "",
    problem_summary_body: "",
    source_name: "",
    source_url: "",
    release_date_label: "",
    date_format: "",
    canonical_name_fallback: true,
    home_card_icon: "",
    background_image_ref: "",
    short_description: "",
    primary_metric_key: "",
    performance_focus: defaultPerformanceFocus(),
    theme_preset: DEFAULT_DATASET_THEME_PRESET,
    bound_predict_view_id: "",
    positive_class_probability_label: GENERIC_RESULT_PRESENTATION.positive_class_probability_label,
    predicted_outcome_label: GENERIC_RESULT_PRESENTATION.predicted_outcome_label,
    positive_outcome_copy: GENERIC_RESULT_PRESENTATION.positive_outcome_copy,
    negative_outcome_copy: GENERIC_RESULT_PRESENTATION.negative_outcome_copy,
    legacy_submit_button_label: "",
    model_section_label: GENERIC_RESULT_PRESENTATION.model_section_label,
    interpretation_preset: "risk",
    interpretation_high: GENERIC_RESULT_PRESENTATION.interpretation.labels.high,
    interpretation_medium: GENERIC_RESULT_PRESENTATION.interpretation.labels.medium,
    interpretation_low: GENERIC_RESULT_PRESENTATION.interpretation.labels.low,
    documentation: "",
  };
}

function formFromProfile(profile: ProfileDraft | null, datasetSlug: string): DraftForm {
  const form = emptyDraftForm(datasetSlug);
  if (!profile) {
    return form;
  }

  const focus = profile.performance_focus;
  const performanceFocus = focus ? defaultPerformanceFocus(focus.focus_id) : form.performance_focus;
  if (focus) {
    const publishedById = new Map(focus.visible_scores.map((score) => [score.score_id, score]));
    performanceFocus.highlighted_score_id = focus.highlighted_score_id;
    performanceFocus.scores = performanceFocus.scores.map((score) => {
      const published = publishedById.get(score.score_id);
      return published ? { ...published, visible: true } : score;
    });
  }
  return {
    ...form,
    schema_version: profile.schema_version || form.schema_version,
    display_title: profile.display?.title ?? "",
    display_subtitle: profile.display?.subtitle ?? "",
    problem_summary_title: profile.display?.problem_summary_title ?? "",
    problem_summary_body: profile.display?.problem_summary_body ?? "",
    source_name: profile.display?.source_name ?? "",
    source_url: profile.display?.source_url ?? "",
    release_date_label: normalizeDatasetDateOnly(profile.display?.release_date_label),
    date_format: profile.display?.date_format ?? "",
    canonical_name_fallback: profile.display?.canonical_name_fallback ?? true,
    home_card_icon: profile.home_card?.icon ?? "",
    background_image_ref: profile.home_card?.background_image_ref ?? "",
    short_description: profile.home_card?.short_description ?? "",
    primary_metric_key: profile.home_card?.primary_metric_key ?? "",
    performance_focus: performanceFocus,
    theme_preset: isDatasetThemePresetId(profile.theme?.preset)
      ? profile.theme.preset
      : DEFAULT_DATASET_THEME_PRESET,
    bound_predict_view_id: profile.inference_presentation?.bound_predict_view_id ?? "",
    positive_class_probability_label: profile.result_card?.positive_class_probability_label ?? form.positive_class_probability_label,
    predicted_outcome_label: profile.result_card?.predicted_outcome_label ?? form.predicted_outcome_label,
    positive_outcome_copy: profile.result_card?.positive_outcome_copy ?? form.positive_outcome_copy,
    negative_outcome_copy: profile.result_card?.negative_outcome_copy ?? form.negative_outcome_copy,
    legacy_submit_button_label: profile.result_card?.submit_button_label ?? "",
    model_section_label: profile.result_card?.model_section_label ?? form.model_section_label,
    interpretation_preset: "risk",
    interpretation_high: profile.result_card?.interpretation?.labels?.high ?? form.interpretation_high,
    interpretation_medium: profile.result_card?.interpretation?.labels?.medium ?? form.interpretation_medium,
    interpretation_low: profile.result_card?.interpretation?.labels?.low ?? form.interpretation_low,
    documentation: profile.documentation?.content ?? "",
  };
}

function textValue(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function dateFromLastUpdated(value: string | null | undefined): string {
  return presentDatasetOperationalTimestamp(value)?.localCalendarDate ?? "";
}

function profileWithCanonicalReleaseDate(profile: ProfileDraft | null, canonicalDate: string): ProfileDraft | null {
  if (!profile || !canonicalDate) {
    return profile;
  }
  const { release_date_mode: _legacyMode, ...display } = profile.display ?? {};
  return {
    ...profile,
    display: { ...display, release_date_label: canonicalDate },
  };
}

function profileFromForm(form: DraftForm, datasetSlug: string): ProfileDraft {
  const profile: ProfileDraft = {
    schema_version: form.schema_version.trim() || "1.0.0",
    dataset_slug: datasetSlug,
  };

  const display: NonNullable<ProfileDraft["display"]> = {};
  display.title = textValue(form.display_title);
  display.subtitle = textValue(form.display_subtitle);
  display.problem_summary_title = textValue(form.problem_summary_title);
  display.problem_summary_body = textValue(form.problem_summary_body);
  display.source_name = textValue(form.source_name);
  display.source_url = textValue(form.source_url);
  display.release_date_label = textValue(form.release_date_label);
  if (form.date_format) {
    display.date_format = form.date_format;
  }
  display.canonical_name_fallback = form.canonical_name_fallback;
  profile.display = display;

  const homeCard: NonNullable<ProfileDraft["home_card"]> = {};
  if (form.home_card_icon) {
    homeCard.icon = form.home_card_icon;
  }
  homeCard.background_image_ref = form.background_image_ref.trim() || null;
  homeCard.short_description = textValue(form.short_description);
  homeCard.primary_metric_key = form.primary_metric_key.trim() || null;
  profile.home_card = homeCard;

  const visibleScores = form.performance_focus.scores.filter((score) => score.visible);
  if (visibleScores.length && visibleScores.some((score) => score.score_id === form.performance_focus.highlighted_score_id)) {
    profile.performance_focus = {
      focus_id: form.performance_focus.focus_id,
      highlighted_score_id: form.performance_focus.highlighted_score_id,
      visible_scores: visibleScores.map(({ visible: _visible, ...score }, order) => ({ ...score, order })),
    };
  }

  if (form.theme_preset) {
    profile.theme = { preset: form.theme_preset };
  }

  profile.inference_presentation = {
    bound_predict_view_id: form.bound_predict_view_id.trim() || null,
  };

  // Project Spec S0110: submit-button copy is no longer Result Card
  // authority -- new profile publications never emit result_card.submit_button_label
  // (see contracts/dataset-public-profile.schema.json's deprecated,
  // read-only compatibility description for that field). The Inference Form
  // tab's predict-view customization is the only writer of submit copy now.
  profile.result_card = {
    schema_version: "binary-result-presentation.v1",
    positive_class_probability_label: textValue(form.positive_class_probability_label),
    predicted_outcome_label: textValue(form.predicted_outcome_label),
    positive_outcome_copy: textValue(form.positive_outcome_copy),
    negative_outcome_copy: textValue(form.negative_outcome_copy),
    model_section_label: textValue(form.model_section_label),
    interpretation: {
      preset: "risk",
      labels: {
        high: textValue(form.interpretation_high),
        medium: textValue(form.interpretation_medium),
        low: textValue(form.interpretation_low),
      },
    },
  };

  if (form.documentation.trim()) {
    profile.documentation = { format: "markdown", content: form.documentation };
  }

  return profile;
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => entry !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sameProfile(left: ProfileDraft | null, right: ProfileDraft | null): boolean {
  if (!left || !right) {
    return left === right;
  }
  const normalizedLeft = profileFromForm(formFromProfile(left, left.dataset_slug), left.dataset_slug);
  const normalizedRight = profileFromForm(formFromProfile(right, right.dataset_slug), right.dataset_slug);
  return stableJson(normalizedLeft) === stableJson(normalizedRight);
}

// Publishable fields observed by the workspace Publish changes action across
// Dataset Detail tabs. This deliberately excludes transient editor state.
// Project Spec S0103: bound_predict_view_id is included here even though it
// reads from the Inference Form tab's selector, because it is itself a
// persisted ProfileDraft.inference_presentation field carried through
// profileFromForm/formFromProfile and published by the same profile publish
// boundary as every other field below -- it was simply missing from this
// projection before, which is why changing it previously left the workspace
// toolbar's Publish changes button unaffected.
type WorkspacePublishFields = Pick<
  DraftForm,
  | "display_title"
  | "display_subtitle"
  | "problem_summary_title"
  | "problem_summary_body"
  | "source_name"
  | "source_url"
  | "release_date_label"
  | "date_format"
  | "canonical_name_fallback"
  | "home_card_icon"
  | "short_description"
  | "primary_metric_key"
  | "performance_focus"
  | "background_image_ref"
  | "theme_preset"
  | "bound_predict_view_id"
  | "positive_class_probability_label"
  | "predicted_outcome_label"
  | "positive_outcome_copy"
  | "negative_outcome_copy"
  | "model_section_label"
  | "interpretation_preset"
  | "interpretation_high"
  | "interpretation_medium"
  | "interpretation_low"
  | "documentation"
>;

function workspacePublishFields(form: DraftForm): WorkspacePublishFields {
  return {
    display_title: form.display_title,
    display_subtitle: form.display_subtitle,
    problem_summary_title: form.problem_summary_title,
    problem_summary_body: form.problem_summary_body,
    source_name: form.source_name,
    source_url: form.source_url,
    release_date_label: form.release_date_label,
    date_format: form.date_format,
    canonical_name_fallback: form.canonical_name_fallback,
    home_card_icon: form.home_card_icon,
    short_description: form.short_description,
    primary_metric_key: form.primary_metric_key,
    performance_focus: form.performance_focus,
    background_image_ref: form.background_image_ref,
    theme_preset: isDatasetThemePresetId(form.theme_preset)
      ? form.theme_preset
      : DEFAULT_DATASET_THEME_PRESET,
    bound_predict_view_id: form.bound_predict_view_id,
    positive_class_probability_label: form.positive_class_probability_label,
    predicted_outcome_label: form.predicted_outcome_label,
    positive_outcome_copy: form.positive_outcome_copy,
    negative_outcome_copy: form.negative_outcome_copy,
    model_section_label: form.model_section_label,
    interpretation_preset: form.interpretation_preset,
    interpretation_high: form.interpretation_high,
    interpretation_medium: form.interpretation_medium,
    interpretation_low: form.interpretation_low,
    documentation: form.documentation,
  };
}

function sameWorkspacePublishFields(left: DraftForm, right: DraftForm): boolean {
  return stableJson(workspacePublishFields(left)) === stableJson(workspacePublishFields(right));
}

function backendDraftProfile(draftState: DraftState): ProfileDraft | null {
  if (draftState.status === "ready") {
    return draftState.profile;
  }
  if (draftState.status === "saved") {
    return draftState.profile;
  }
  return null;
}

function profileFromSnapshot(snapshot: PublishSnapshot | null | undefined, datasetSlug: string): ProfileDraft | null {
  const profile = snapshot?.profile;
  if (!profile || typeof profile !== "object") {
    return null;
  }
  return {
    ...profile,
    schema_version: snapshot?.source_draft_schema_version || profile.schema_version || "1.0.0",
    dataset_slug: datasetSlug,
  };
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div style={readOnlyFieldStyle}>
      <span style={labelStyle}>{label}</span>
      <p style={readOnlyValueStyle}>{value || "Not provided"}</p>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  multiline = false,
  required = false,
  maxLength,
  type = "text",
  rows,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  required?: boolean;
  maxLength?: number;
  type?: "text" | "url" | "date";
  rows?: number;
  disabled?: boolean;
}) {
  const hasCounter = typeof maxLength === "number";
  return (
    <label style={hasCounter ? fieldStyleWithCounter : fieldStyle}>
      <span style={fieldLabelRowStyle}>
        {label}
        {required ? (
          <span aria-hidden="true" style={requiredMarkerStyle}>
            *
          </span>
        ) : null}
      </span>
      {multiline ? (
        <textarea
          aria-label={label}
          disabled={disabled}
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          rows={rows}
          style={hasCounter ? { ...textareaStyle, ...counterPaddingStyle } : textareaStyle}
          value={value}
        />
      ) : (
        <input
          aria-label={label}
          disabled={disabled}
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          style={hasCounter ? { ...inputStyle, ...counterPaddingStyle } : inputStyle}
          type={type}
          value={value}
        />
      )}
      {hasCounter ? (
        <small aria-hidden="true" style={fieldCounterStyle}>
          {value.length} / {maxLength}
        </small>
      ) : null}
    </label>
  );
}

function stateValue<T>(state: SectionState<T>): T | null {
  return state.status === "ready" ? state.data : null;
}

function mapSection<T, U>(state: SectionState<T>, mapper: (data: T) => U): SectionState<U> {
  if (state.status === "ready") {
    return { status: "ready", data: mapper(state.data) };
  }
  return state;
}

// Project Spec S0121: converts one GET /admin/datasets/{slug}/authoring-context
// resource envelope into the shared SectionState shape, preserving the
// backend's bounded error code/message (resource identity is implicit in
// which ReadOnlyData field the caller assigns this into) rather than
// collapsing an unavailable resource into a bare null/[]/{}.
function authoringResourceState<T>(resource: AuthoringResourceEnvelope<T> | undefined): SectionState<T> {
  if (!resource) {
    return { status: "unavailable", message: "This resource was not included in the authoring context response." };
  }
  if (resource.status === "ready") {
    return { status: "ready", data: resource.data };
  }
  return { status: "unavailable", message: resource.error.message, code: resource.error.code };
}

function metricKeys(metrics: MetricsPayload | null): string[] {
  const values = metrics?.evaluation?.metrics;
  return values && typeof values === "object" ? Object.keys(values) : [];
}

function contractFields(contract: ContractPayload | null): ContractField[] {
  return contract?.features ?? [];
}

function classifyResultContract(envelope: ContractEnvelope): ResultContractState {
  const value = envelope.result_contract;
  if (value && typeof value === "object" && "status" in value && value.status === "unavailable") {
    const reason = "reason" in value && typeof value.reason === "string" ? value.reason : "No result semantics are available for this release.";
    return { status: "unavailable", message: reason };
  }
  if (!isAvailableBinaryResultContract(value)) {
    return { status: "incompatible", message: "The active release result contract is missing or incompatible." };
  }
  if (value.semantics.interpretation.bands.length !== 3) {
    return { status: "incompatible", message: "The active release must expose exactly three governed risk bands." };
  }
  return { status: "available", semantics: value.semantics };
}

// Project Spec S0143: adapts the private authoring read model's richer
// ResultContractState (idle/loading/available/unavailable/transport_failure/
// incompatible) down to the shared public component's narrower
// BinaryResultContract (available/unavailable) -- every non-"available"
// authoring state renders as the same "unavailable" contract the public
// InferenceForm already knows how to disable submission and render safely
// for, exactly as the pre-existing synthetic Result Card preview did.
function toInferenceResultContract(state: ResultContractState): BinaryResultContract {
  if (state.status === "available") {
    return { status: "available", semantics: state.semantics };
  }
  return {
    status: "unavailable",
    reason: "message" in state ? state.message : state.status,
  };
}

// Project Spec S0143: the private Admin Live Preview's injected executor --
// the sole difference from the public default is the target route. Reuses
// the same bounded (slug, payload) -> InferenceExecutionResult contract as
// every other InferenceForm caller; never accepts or forwards a raw
// caller-supplied URL.
async function executeAdminInference(
  slug: string,
  payload: Record<string, string | number | boolean>,
): Promise<InferenceExecutionResult> {
  try {
    const res = await fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(slug)}/inference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = (await res.json()) as {
      result?: unknown;
      error_code?: string;
      errors?: unknown;
      runtime_diagnostic?: unknown;
    };
    if (res.ok) {
      return { ok: true, result: body?.result };
    }
    // Project Spec S0147: reuses InferenceForm's shared normalizer so the
    // private executor carries the same bounded, safe validationIssues
    // shape the public executor does -- never the raw backend `errors`
    // value, never a raw message.
    //
    // Project Spec S0151: likewise reuses InferenceForm's shared
    // normalizeInferenceRuntimeDiagnostic, so this private-only executor is
    // the sole place body.runtime_diagnostic is ever read -- the public
    // executor in InferenceForm.tsx never reads this field.
    return {
      ok: false,
      errorCode: body?.error_code,
      validationIssues: normalizeInferenceValidationIssues(body?.errors),
      runtimeDiagnostic: normalizeInferenceRuntimeDiagnostic(body?.runtime_diagnostic),
    };
  } catch {
    return { ok: false };
  }
}

function presentationFromForm(form: DraftForm): BinaryResultPresentation {
  return {
    schema_version: "binary-result-presentation.v1",
    positive_class_probability_label: form.positive_class_probability_label.trim() || GENERIC_RESULT_PRESENTATION.positive_class_probability_label,
    predicted_outcome_label: form.predicted_outcome_label.trim() || GENERIC_RESULT_PRESENTATION.predicted_outcome_label,
    positive_outcome_copy: form.positive_outcome_copy.trim() || GENERIC_RESULT_PRESENTATION.positive_outcome_copy,
    negative_outcome_copy: form.negative_outcome_copy.trim() || GENERIC_RESULT_PRESENTATION.negative_outcome_copy,
    model_section_label: form.model_section_label.trim() || GENERIC_RESULT_PRESENTATION.model_section_label,
    interpretation: {
      preset: "risk",
      labels: {
        high: form.interpretation_high.trim() || GENERIC_RESULT_PRESENTATION.interpretation.labels.high,
        medium: form.interpretation_medium.trim() || GENERIC_RESULT_PRESENTATION.interpretation.labels.medium,
        low: form.interpretation_low.trim() || GENERIC_RESULT_PRESENTATION.interpretation.labels.low,
      },
    },
  };
}

async function fetchJson<T>(path: string, signal: AbortSignal): Promise<SectionState<T>> {
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, { signal });
    if (!response.ok) {
      return { status: "unavailable", message: `Unavailable (${response.status})` };
    }
    const data = (await response.json()) as T;
    return { status: "ready", data };
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      return { status: "unavailable", message: "Request cancelled." };
    }
    return { status: "unavailable", message: "Request failed. Check API reachability." };
  }
}

const VISIBILITY_SOURCE_VALUES = new Set(["explicit_record", "default_visible"]);
const VISIBILITY_RECORD_STATUS_VALUES = new Set([
  "valid",
  "missing",
  "unreadable",
  "invalid_json",
  "invalid_shape",
  "invalid_visible",
  "invalid_updated_at",
]);
const REVIEW_STATUS_VALUES = new Set(["ready", "needs_review"]);
const SNAPSHOT_STATUS_VALUES = new Set(["missing", "current_release", "stale_release", "invalid"]);

// Bounded runtime validation for GET /admin/datasets/{slug}/publication-state
// (Project Spec S0116). A response outside this exact shape is treated as
// unavailable rather than partially trusted -- the frontend must never guess
// at, coerce, or partially render a malformed backend projection.
function parseAdminPublicationStateProjection(body: unknown): AdminPublicationStateProjection | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const root = body as Record<string, unknown>;
  if (typeof root.dataset_slug !== "string" || !root.dataset_slug) {
    return null;
  }
  if (root.active_release !== null && typeof root.active_release !== "string") {
    return null;
  }

  const visibility = root.visibility as Record<string, unknown> | undefined;
  if (
    typeof visibility !== "object" ||
    visibility === null ||
    typeof visibility.configured_visible !== "boolean" ||
    typeof visibility.source !== "string" ||
    !VISIBILITY_SOURCE_VALUES.has(visibility.source) ||
    typeof visibility.record_status !== "string" ||
    !VISIBILITY_RECORD_STATUS_VALUES.has(visibility.record_status) ||
    (visibility.updated_at !== null && typeof visibility.updated_at !== "string") ||
    typeof visibility.effective_visible !== "boolean"
  ) {
    return null;
  }

  const review = root.review as Record<string, unknown> | undefined;
  if (
    typeof review !== "object" ||
    review === null ||
    typeof review.status !== "string" ||
    !REVIEW_STATUS_VALUES.has(review.status) ||
    typeof review.approval_allowed !== "boolean" ||
    !Array.isArray(review.approval_blockers) ||
    !review.approval_blockers.every((code) => typeof code === "string")
  ) {
    return null;
  }

  const snapshot = root.snapshot as Record<string, unknown> | undefined;
  if (
    typeof snapshot !== "object" ||
    snapshot === null ||
    typeof snapshot.status !== "string" ||
    !SNAPSHOT_STATUS_VALUES.has(snapshot.status) ||
    typeof snapshot.exists !== "boolean" ||
    (snapshot.published_at !== null && typeof snapshot.published_at !== "string") ||
    (snapshot.active_release_at_publish_time !== null && typeof snapshot.active_release_at_publish_time !== "string") ||
    (snapshot.matches_active_release !== null && typeof snapshot.matches_active_release !== "boolean")
  ) {
    return null;
  }

  const publicAccess = root.public_access as Record<string, unknown> | undefined;
  if (
    typeof publicAccess !== "object" ||
    publicAccess === null ||
    typeof publicAccess.reachable !== "boolean" ||
    !Array.isArray(publicAccess.blockers) ||
    !publicAccess.blockers.every((code) => typeof code === "string") ||
    !Array.isArray(publicAccess.observations) ||
    !publicAccess.observations.every((code) => typeof code === "string")
  ) {
    return null;
  }

  return {
    dataset_slug: root.dataset_slug,
    active_release: (root.active_release as string | null) ?? null,
    visibility: {
      configured_visible: visibility.configured_visible,
      source: visibility.source as AdminPublicationStateProjection["visibility"]["source"],
      record_status: visibility.record_status as AdminPublicationStateProjection["visibility"]["record_status"],
      updated_at: (visibility.updated_at as string | null) ?? null,
      effective_visible: visibility.effective_visible,
    },
    review: {
      status: review.status as AdminPublicationStateProjection["review"]["status"],
      approval_allowed: review.approval_allowed,
      approval_blockers: review.approval_blockers as string[],
    },
    snapshot: {
      status: snapshot.status as AdminPublicationStateProjection["snapshot"]["status"],
      exists: snapshot.exists,
      published_at: (snapshot.published_at as string | null) ?? null,
      active_release_at_publish_time: (snapshot.active_release_at_publish_time as string | null) ?? null,
      matches_active_release: (snapshot.matches_active_release as boolean | null) ?? null,
    },
    public_access: {
      reachable: publicAccess.reachable,
      blockers: publicAccess.blockers as string[],
      observations: publicAccess.observations as string[],
    },
  };
}

function DraftStatusPanel({ draftState }: { draftState: DraftState }) {
  if (draftState.status === "ready") {
    return <span data-testid="dataset-admin-draft-ready" hidden />;
  }
  if (draftState.status === "saved") {
    return <span data-testid="dataset-admin-draft-saved" hidden />;
  }
  if (draftState.status === "invalid") {
    return (
      <article role="status" style={alertStyle}>
        <strong>Profile draft rejected by backend validation</strong>
        <ul style={{ margin: 0, paddingLeft: "var(--atlas-space-5)" }}>
          {draftState.errors.map((error, index) => (
            <li key={`${error.code ?? "error"}-${error.field ?? "field"}-${index}`}>
              {[error.field, error.code, error.message].filter(Boolean).join(" - ")}
            </li>
          ))}
        </ul>
      </article>
    );
  }
  if (draftState.status === "unavailable") {
    return (
      <article role="status" style={alertStyle}>
        <strong>Content unavailable</strong>
        <p style={mutedTextStyle}>{draftState.message}</p>
      </article>
    );
  }
  if (draftState.status === "loading") {
    return <p style={mutedTextStyle}>Loading content...</p>;
  }
  return <p style={mutedTextStyle}>{draftState.message}</p>;
}

function PublicContentTab({
  form,
  setField,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
}) {
  return (
    <div className="dataset-admin-public-content-form">
      <section className="dataset-admin-public-content-group">
        <h2 className="dataset-admin-public-content-group__title">Public copy</h2>
        <div className="dataset-admin-form-grid">
          <TextField
            label="Display title"
            maxLength={80}
            onChange={(value) => setField("display_title", value)}
            required
            value={form.display_title}
          />
          <TextField
            label="Subtitle"
            maxLength={120}
            onChange={(value) => setField("display_subtitle", value)}
            required
            value={form.display_subtitle}
          />
        </div>
        <div style={narrowFieldRowStyle}>
          <TextField
            label="Problem summary title"
            maxLength={60}
            onChange={(value) => setField("problem_summary_title", value)}
            required
            value={form.problem_summary_title}
          />
        </div>
        <TextField
          label="Problem summary body"
          maxLength={300}
          multiline
          onChange={(value) => setField("problem_summary_body", value)}
          required
          rows={5}
          value={form.problem_summary_body}
        />
      </section>

      <section className="dataset-admin-public-content-group">
        <h2 className="dataset-admin-public-content-group__title">Source and release</h2>
        <div className="dataset-admin-form-grid">
          <TextField label="Source name" onChange={(value) => setField("source_name", value)} required value={form.source_name} />
          <TextField
            label="Source URL"
            onChange={(value) => setField("source_url", value)}
            required
            type="url"
            value={form.source_url}
          />
          <div style={fieldStyle}>
            <TextField
              label="Release date label"
              onChange={(value) => {
                const normalized = normalizeDatasetDateOnly(value);
                setField("release_date_label", normalized);
              }}
              required
              type="date"
              value={form.release_date_label}
            />
          </div>
          <label style={fieldStyle}>
            <span style={fieldLabelRowStyle}>
              Date format
              <span aria-hidden="true" style={requiredMarkerStyle}>
                *
              </span>
            </span>
            <select
              aria-label="Date format"
              id="date-format"
              onChange={(event) => setField("date_format", event.target.value as DraftForm["date_format"])}
              style={inputStyle}
              value={form.date_format}
            >
              <option value="">No curated format</option>
              <option value="dd/mm/yyyy">dd/mm/yyyy</option>
              <option value="mm/dd/yyyy">mm/dd/yyyy</option>
              <option value="yyyy-mm-dd">yyyy-mm-dd</option>
            </select>
          </label>
        </div>
      </section>
    </div>
  );
}

function MetadataCardTab({
  form,
  setField,
  readOnlyData,
  selectedSlug,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
}) {
  const context = stateValue(readOnlyData.context);
  // Project Spec S0121: readOnlyData.dataset is now the private admin dataset
  // projection (AuthoringDatasetProjection), which has no `visibility` field
  // -- projectHomeCardPreview's PreviewDataset shape still declares one
  // (unused by the function body) purely for structural compatibility with
  // its other, public-listing-fed call site, so it is filled with an unused
  // placeholder here rather than widening the shared lib's type.
  const authoringDataset = stateValue(readOnlyData.dataset);
  const previewDataset = authoringDataset ? { ...authoringDataset, visibility: "" } : undefined;
  const lockedProblemType = {
    machineId: "binary_classification",
    optionValue: "binary-classification",
    label: "Binary Classification",
  } as const;
  const [imageUploadState, setImageUploadState] = useState<"idle" | "uploading">("idle");
  const [imageUploadError, setImageUploadError] = useState("");

  function uploadHomeCardImage(file: File | undefined) {
    if (!file) return;
    setImageUploadError("");
    if (file.size > 10 * 1024 * 1024) {
      setImageUploadError("Choose an image smaller than 10 MB.");
      return;
    }
    setImageUploadState("uploading");
    const headers: Record<string, string> = { "X-File-Name": encodeURIComponent(file.name) };
    if (file.type) headers["Content-Type"] = file.type;
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/home-card-image`, {
      method: "POST",
      headers,
      body: file,
    })
      .then(async (response) => {
        const body = await response.json() as { media_ref?: string; errors?: DraftError[] };
        if (!response.ok || !body.media_ref) throw new Error(body.errors?.[0]?.message || "The image could not be uploaded. Try again.");
        setField("background_image_ref", body.media_ref);
      })
      .catch((error: Error) => setImageUploadError(error.message || "The image could not be uploaded. Try again."))
      .finally(() => setImageUploadState("idle"));
  }
  return (
    <div className="dataset-admin-tab-workspace">
      <div className="dataset-admin-metadata-layout">
        <div className="dataset-admin-metadata-layout__controls">
          <Card className="dataset-admin-config-card">
            <div aria-label="Home card icon" className="dataset-admin-icon-grid" role="group">
              {HOME_CARD_ICON_OPTIONS.map(({ value, label }) => {
                const selected = form.home_card_icon === value;
                return (
                  <button
                    aria-pressed={selected}
                    className={["dataset-admin-icon-card", selected ? "is-selected" : ""].filter(Boolean).join(" ")}
                    key={value}
                    onClick={() => setField("home_card_icon", value)}
                    type="button"
                  >
                    <span aria-hidden="true" className="dataset-admin-icon-card__glyph"><DatasetIcon name={value} /></span>
                    <span>{label}</span>
                  </button>
                );
              })}
              <label className="dataset-admin-icon-card dataset-admin-image-upload-tile">
                <span aria-hidden="true" className="dataset-admin-image-upload-tile__glyph">↑</span>
                <span>{imageUploadState === "uploading" ? "Uploading…" : "Upload image"}</span>
                <input
                  accept="image/png,image/jpeg,image/webp,image/avif"
                  disabled={!selectedSlug || imageUploadState === "uploading"}
                  onChange={(event) => {
                    uploadHomeCardImage(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                  type="file"
                />
              </label>
            </div>
            {imageUploadError ? <p className="dataset-admin-image-upload-error" role="alert">{imageUploadError}</p> : null}
            {form.background_image_ref ? (
              <button className="dataset-admin-clear-image" onClick={() => { setField("background_image_ref", ""); setImageUploadError(""); }} type="button">
                Remove image
              </button>
            ) : null}
          </Card>

          <Card className="dataset-admin-config-card">
            <FormRow htmlFor="performance-focus" label="Performance focus">
              <select
                id="performance-focus"
                onChange={(event) => setField("performance_focus", defaultPerformanceFocus(event.target.value as PerformanceFocusId))}
                style={inputStyle}
                value={form.performance_focus.focus_id}
              >
                {PERFORMANCE_FOCUS_OPTIONS.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </FormRow>
            <PerformanceFocusBuilder focus={form.performance_focus} onChange={(focus) => setField("performance_focus", focus)} />
          </Card>
        </div>

        <div className="dataset-admin-metadata-layout__preview">
          <Card className="dataset-admin-preview-card">
            <div className="dataset-admin-card-heading">
              <h2>Home card preview</h2>
            </div>
            <DatasetCard
              {...projectHomeCardPreview(
                previewDataset,
                {
                  ...form,
                  home_card_icon: form.home_card_icon as "" | "telecom" | "bank" | "generic",
                },
                context
                  ? { ...context, problem_type: lockedProblemType.machineId }
                  : { problem_type: lockedProblemType.machineId },
              )}
              mediaRef={form.background_image_ref}
              summary={form.short_description}
              themePreset={form.theme_preset}
            />
            <TextField label="Home card description" multiline onChange={(value) => setField("short_description", value)} rows={3} value={form.short_description} />
          </Card>

          <Card className="dataset-admin-config-card dataset-admin-problem-type-card">
            <div className="dataset-admin-card-heading">
              <h2>Problem type display</h2>
            </div>
            <div aria-label="Problem type display" className="dataset-admin-problem-type-options" role="radiogroup">
              {[
                [lockedProblemType.optionValue, lockedProblemType.label, ""],
                ["regression", "Regression", "Locked"],
                ["multiclass-classification", "Multiclass Classification", "Locked"],
                ["time-series", "Time Series", "Locked"],
              ].map(([value, label, status], index) => (
                <label className={["dataset-admin-problem-type-option", index === 0 ? "is-selected" : ""].filter(Boolean).join(" ")} key={value}>
                  <input checked={index === 0} disabled name="problem-type-display" readOnly type="radio" value={value} />
                  <span>
                    <strong>{label}</strong>
                    {status ? <small>{status}</small> : null}
                  </span>
                </label>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function PerformanceFocusBuilder({ focus, onChange }: { focus: PerformanceFocusDraft; onChange: (focus: PerformanceFocusDraft) => void }) {
  const visibleScores = focus.scores.filter((score) => score.visible);
  const highlighted = visibleScores.find((score) => score.score_id === focus.highlighted_score_id);

  function updateScore(scoreId: string, update: Partial<PerformanceScoreDraft>) {
    const scores = focus.scores.map((score) => score.score_id === scoreId ? { ...score, ...update } : score);
    const nextVisible = scores.filter((score) => score.visible);
    const highlightedStillVisible = nextVisible.some((score) => score.score_id === focus.highlighted_score_id);
    onChange({ ...focus, scores, highlighted_score_id: highlightedStillVisible ? focus.highlighted_score_id : nextVisible[0]?.score_id ?? "" });
  }

  return (
    <div className="performance-focus-builder">
      <div className="performance-focus-builder__highlight">
        <FormRow htmlFor="highlighted-score" label="Highlighted score">
          <select
            disabled={!visibleScores.length}
            id="highlighted-score"
            onChange={(event) => onChange({ ...focus, highlighted_score_id: event.target.value })}
            style={inputStyle}
            value={highlighted?.score_id ?? ""}
          >
            {!visibleScores.length && <option value="">No visible scores</option>}
            {visibleScores.map((score) => <option key={score.score_id} value={score.score_id}>{score.display_label}</option>)}
          </select>
        </FormRow>
        <FormRow htmlFor="highlighted-score-value" label="Highlighted score value">
          <input
            disabled={!highlighted}
            id="highlighted-score-value"
            inputMode="decimal"
            maxLength={32}
            onChange={(event) => highlighted && updateScore(highlighted.score_id, { value: event.target.value, value_source: "manual" })}
            style={inputStyle}
            value={highlighted?.value ?? ""}
          />
        </FormRow>
      </div>
      <div className="performance-focus-builder__heading">
        <strong>Scores shown on Dataset Detail</strong>
      </div>
      <div className="performance-focus-builder__scores">
        {focus.scores.map((score) => (
          <div className={`performance-focus-builder__score${score.visible ? " is-selected" : ""}`} key={score.score_id}>
            <label>
              <input
                aria-label={`Show ${score.display_label}`}
                checked={score.visible}
                onChange={(event) => updateScore(score.score_id, { visible: event.target.checked })}
                type="checkbox"
              />
              <strong>{score.display_label}</strong>
            </label>
            <input
              aria-label={`${score.display_label} value`}
              disabled={!score.visible}
              inputMode="decimal"
              maxLength={32}
              onChange={(event) => updateScore(score.score_id, { value: event.target.value, value_source: "manual" })}
              pattern="[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:%|[eE][+-]?[0-9]+)?"
              style={inputStyle}
              value={score.value}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function ThemePresetTab({
  form,
  setField,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
}) {
  return (
    <div className="dataset-admin-tab-workspace">
      <div className="dataset-admin-theme-grid">
        {DATASET_THEME_PRESETS.map((preset) => {
          const selected = form.theme_preset === preset.id;
          return (
            <button
              aria-pressed={selected}
              className={["dataset-admin-theme-card", selected ? "is-selected" : ""].filter(Boolean).join(" ")}
              key={preset.id}
              onClick={() => setField("theme_preset", preset.id)}
              type="button"
            >
              <span className="dataset-admin-theme-card__swatches" aria-hidden="true">
                {preset.swatches.map((color) => (
                  <span key={color} style={{ background: color }} />
                ))}
              </span>
              <strong>{preset.label}</strong>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CustomizationStatusPanel({
  state,
  onRetry,
  hasEligibleViews,
}: {
  state: CustomizationEditorState;
  onRetry: () => void;
  hasEligibleViews: boolean;
}) {
  if (state.status === "no_view_bound") {
    return (
      <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--warning" role="status">
        <strong>No predict view bound</strong>
        <p className="dataset-admin-exceptional-notice__text">
          {hasEligibleViews
            ? "Choose a predict view above to build its Inference Form."
            : "No predict views are available for this dataset yet."}
        </p>
      </article>
    );
  }
  if (state.status === "contract_unavailable") {
    return (
      <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--warning" role="status">
        <strong>Public contract unavailable</strong>
        <p className="dataset-admin-exceptional-notice__text">
          The active release public contract could not be loaded, so a form cannot be built yet.
        </p>
      </article>
    );
  }
  // Project Spec S0103: "ready_base"/"ready_overlaid" (no customization yet /
  // a compatible overlay loaded) and "saving"/"saved" are normal lifecycle
  // states now that persistence goes through the shared workspace toolbar
  // Publish changes action -- their progress/success feedback renders there
  // instead, so this panel intentionally renders nothing for them, and no
  // fixed-height wrapper is left behind since InferenceFormTab calls this
  // component directly with no reserved-space container around it.
  if (state.status === "ready_base" || state.status === "ready_overlaid") {
    return null;
  }
  if (state.status === "incompatible_overlay_ignored") {
    return (
      <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--warning" role="status">
        <strong>Historical customization not applied</strong>
        <p className="dataset-admin-exceptional-notice__text">
          A previously saved customization no longer matches the current public contract, so it was not applied.
          Showing the default form built from the current contract instead. Saving here replaces the historical
          record.
        </p>
      </article>
    );
  }
  if (state.status === "saving" || state.status === "saved") {
    return null;
  }
  if (state.status === "invalid") {
    return (
      <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--danger" role="status">
        <strong>Customization rejected by backend validation</strong>
        <ul className="dataset-admin-exceptional-notice__list">
          {state.errors.map((error, index) => (
            <li key={`${error.code ?? "error"}-${error.field ?? "field"}-${index}`}>
              {[error.field, error.code, error.message].filter(Boolean).join(" - ")}
            </li>
          ))}
        </ul>
      </article>
    );
  }
  if (state.status === "unavailable") {
    return (
      <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--danger" role="status">
        <strong>Customization unavailable</strong>
        <p className="dataset-admin-exceptional-notice__text">{state.message}</p>
        <button onClick={onRetry} style={secondaryButtonStyle} type="button">
          Retry
        </button>
      </article>
    );
  }
  return <p className="dataset-admin-inline-status">Loading customization...</p>;
}

function FieldEditModal({
  contractField,
  field,
  onCancel,
  onSave,
}: {
  contractField: ContractField | undefined;
  field: FieldHintDraft;
  onCancel: () => void;
  onSave: (patch: { display_label: string; explanatory_copy: string }) => void;
}) {
  const [displayLabel, setDisplayLabel] = useState(field.display_label);
  const [explanatoryCopy, setExplanatoryCopy] = useState(field.explanatory_copy);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    containerRef.current?.querySelector<HTMLElement>("input, textarea")?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      event.preventDefault();
      onCancel();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  return (
    <div style={modalBackdropStyle}>
      <div
        aria-labelledby="field-edit-modal-title"
        aria-modal="true"
        className="atlas-card"
        ref={containerRef}
        role="dialog"
        style={modalCardStyle}
      >
        <h2 id="field-edit-modal-title" style={cardTitleStyle}>
          Edit field
        </h2>
        <div style={twoColumnGridStyle}>
          <ReadOnlyField label="Contract field name" value={field.field_name} />
          <ReadOnlyField label="Input type" value={contractField?.input_type ?? "Unknown"} />
        </div>
        <ReadOnlyField label="Required state" value={field.required ? "Required" : "Optional"} />
        <TextField label="Display label" onChange={setDisplayLabel} value={displayLabel} />
        <TextField label="Explanatory copy" multiline onChange={setExplanatoryCopy} value={explanatoryCopy} />
        <div style={modalActionsStyle}>
          <button onClick={onCancel} style={secondaryButtonStyle} type="button">
            Cancel
          </button>
          <button
            onClick={() => onSave({ display_label: displayLabel, explanatory_copy: explanatoryCopy })}
            style={actionButtonStyle}
            type="button"
          >
            Save field
          </button>
        </div>
      </div>
    </div>
  );
}

function CustomizationEditor({
  contractFieldsByName,
  draft,
  onUpdateDraft,
}: {
  contractFieldsByName: Map<string, ContractField>;
  draft: CustomizationEditorDraft;
  onUpdateDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void;
}) {
  const [groupDragState, setGroupDragState] = useState<CustomizationGroupDragState | null>(null);
  const [fieldDragState, setFieldDragState] = useState<CustomizationFieldDragState | null>(null);
  const [fieldModalState, setFieldModalState] = useState<{ status: "closed" } | { status: "open"; fieldName: string }>(
    { status: "closed" },
  );
  const chipRefs = useRef(new Map<string, HTMLDivElement>());
  // Project Spec S0104: pointerdown now starts a field drag from anywhere
  // on the chip (not just the six-dot handle), so a completed drag (real
  // pointer movement) must suppress the double-click that would otherwise
  // follow it and reopen the field-edit modal. Consumed (and reset) by the
  // very next chip double-click, so it never suppresses an unrelated one.
  const suppressChipInteractionRef = useRef(false);
  // Local-only, non-schema-persisted expand/collapse affordance for group
  // cards (mirrors the executable prototype's collapse-button pattern).
  // Never read by customizationDraftToRecord and never added to
  // CustomizationEditorDraft/GroupDraft, so it cannot leak into saved state.
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(new Set());
  // On-demand subgroup metadata editing (Project Spec S0100): closed by
  // default, buffered in local state so Cancel can restore the pre-edit
  // values without ever having mutated the shared draft, and Save subgroup
  // is the only path that commits via updateGroup.
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [groupEditDraft, setGroupEditDraft] = useState<GroupDraft | null>(null);

  function toggleGroupCollapsed(groupId: string) {
    setCollapsedGroupIds((current) => {
      const next = new Set(current);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }

  function openGroupEdit(group: GroupDraft) {
    setEditingGroupId(group.group_id);
    setGroupEditDraft({ ...group });
  }

  function cancelGroupEdit() {
    setEditingGroupId(null);
    setGroupEditDraft(null);
  }

  function saveGroupEdit() {
    if (!groupEditDraft || !editingGroupId) return;
    updateGroup(
      draft.groups.findIndex((group) => group.group_id === editingGroupId),
      groupEditDraft,
    );
    cancelGroupEdit();
  }

  function updateGroup(index: number, patch: Partial<GroupDraft>) {
    onUpdateDraft((current) => ({
      ...current,
      groups: current.groups.map((group, i) => (i === index ? { ...group, ...patch } : group)),
    }));
  }

  // Computed inside the updater (against the true latest current.groups)
  // rather than the draft prop, so two rapid Add subgroup activations
  // before a re-render still each get a distinct collision-safe identity.
  function handleAddSubgroup() {
    onUpdateDraft((current) => {
      const { group_id, label } = nextGroupIdentity(current.groups);
      return { ...current, groups: [...current.groups, { group_id, label, description: "" }] };
    });
  }

  function removeGroup(groupId: string) {
    onUpdateDraft((current) => {
      const nextGroups = current.groups.filter((group) => group.group_id !== groupId);
      const clearedFieldHints = current.fieldHints.map((field) =>
        field.group === groupId ? { ...field, group: "" } : field,
      );
      return { ...current, groups: nextGroups, fieldHints: reflowFieldHints(clearedFieldHints, nextGroups) };
    });
  }

  function moveSubgroup(index: number, direction: -1 | 1) {
    onUpdateDraft((current) => {
      const nextGroups = moveItem(current.groups, index, direction);
      return { ...current, groups: nextGroups, fieldHints: reflowFieldHints(current.fieldHints, nextGroups) };
    });
  }

  function getGroupTargetIndex(clientX: number, clientY: number, fallbackIndex: number) {
    const element = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>("[data-customization-group-index]");
    if (!element) return fallbackIndex;
    const targetIndex = Number(element.dataset.customizationGroupIndex);
    return Number.isInteger(targetIndex) ? targetIndex : fallbackIndex;
  }

  function startGroupDrag(event: ReactPointerEvent<HTMLButtonElement>, sourceIndex: number, label: string) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setGroupDragState({ sourceIndex, targetIndex: sourceIndex, pointerX: event.clientX, pointerY: event.clientY, label });
  }

  function updateGroupDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!groupDragState) return;
    event.preventDefault();
    const targetIndex = getGroupTargetIndex(event.clientX, event.clientY, groupDragState.targetIndex);
    setGroupDragState({ ...groupDragState, targetIndex, pointerX: event.clientX, pointerY: event.clientY });
  }

  function finishGroupDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!groupDragState) return;
    event.preventDefault();
    const finalTargetIndex = getGroupTargetIndex(event.clientX, event.clientY, groupDragState.targetIndex);
    const { sourceIndex } = groupDragState;
    setGroupDragState(null);
    onUpdateDraft((current) => {
      const nextGroups = moveItemToIndex(current.groups, sourceIndex, finalTargetIndex);
      return { ...current, groups: nextGroups, fieldHints: reflowFieldHints(current.fieldHints, nextGroups) };
    });
  }

  function cancelGroupDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!groupDragState) return;
    event.preventDefault();
    setGroupDragState(null);
  }

  function getGroupCardStyle(index: number): CSSProperties {
    const isSource = groupDragState?.sourceIndex === index;
    const isTarget = groupDragState !== null && groupDragState.targetIndex === index && groupDragState.sourceIndex !== index;
    return {
      ...panelStyle,
      padding: "var(--atlas-space-3)",
      ...(isSource ? dragSourceStyle : {}),
      ...(isTarget ? dragTargetStyle : {}),
    };
  }

  function resolveFieldDropTarget(
    clientX: number,
    clientY: number,
    fallbackZone: FieldZoneKey,
    fallbackIndex: number,
  ): { zone: FieldZoneKey; index: number } {
    const element = document.elementFromPoint(clientX, clientY);
    const chipElement = element?.closest<HTMLElement>(
      "[data-customization-field-zone][data-customization-field-index]",
    );
    if (chipElement) {
      const zone = chipElement.dataset.customizationFieldZone ?? fallbackZone;
      const index = Number(chipElement.dataset.customizationFieldIndex);
      return { zone, index: Number.isInteger(index) ? index : fallbackIndex };
    }
    const zoneElement = element?.closest<HTMLElement>("[data-customization-drop-zone]");
    if (zoneElement) {
      const zone = zoneElement.dataset.customizationDropZone ?? fallbackZone;
      return { zone, index: zoneFieldEntries(draft, zone).length };
    }
    return { zone: fallbackZone, index: fallbackIndex };
  }

  function startFieldDrag(
    event: ReactPointerEvent<HTMLDivElement>,
    fieldName: string,
    sourceZone: FieldZoneKey,
    sourceIndex: number,
    label: string,
  ) {
    if (isChipDragExcluded(event.target)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setFieldDragState({
      fieldName,
      sourceZone,
      targetZone: sourceZone,
      targetIndex: sourceIndex,
      pointerX: event.clientX,
      pointerY: event.clientY,
      label,
      startX: event.clientX,
      startY: event.clientY,
      didMove: false,
    });
  }

  function updateFieldDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!fieldDragState) return;
    event.preventDefault();
    const { zone, index } = resolveFieldDropTarget(
      event.clientX,
      event.clientY,
      fieldDragState.targetZone,
      fieldDragState.targetIndex,
    );
    const movedDistance = Math.hypot(event.clientX - fieldDragState.startX, event.clientY - fieldDragState.startY);
    setFieldDragState({
      ...fieldDragState,
      targetZone: zone,
      targetIndex: index,
      pointerX: event.clientX,
      pointerY: event.clientY,
      didMove: fieldDragState.didMove || movedDistance > FIELD_DRAG_THRESHOLD_PX,
    });
  }

  function finishFieldDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!fieldDragState) return;
    event.preventDefault();
    const { zone, index } = resolveFieldDropTarget(
      event.clientX,
      event.clientY,
      fieldDragState.targetZone,
      fieldDragState.targetIndex,
    );
    const { fieldName, didMove } = fieldDragState;
    setFieldDragState(null);
    if (didMove) {
      suppressChipInteractionRef.current = true;
    }
    onUpdateDraft((current) => moveFieldToZone(current, fieldName, zone, index));
  }

  function cancelFieldDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!fieldDragState) return;
    event.preventDefault();
    setFieldDragState(null);
  }

  function openFieldModal(fieldName: string) {
    setFieldModalState({ status: "open", fieldName });
  }

  function closeFieldModal(fieldName: string) {
    setFieldModalState({ status: "closed" });
    chipRefs.current.get(fieldName)?.focus();
  }

  function saveFieldModal(fieldName: string, patch: { display_label: string; explanatory_copy: string }) {
    onUpdateDraft((current) => ({
      ...current,
      fieldHints: current.fieldHints.map((field) => (field.field_name === fieldName ? { ...field, ...patch } : field)),
    }));
    closeFieldModal(fieldName);
  }

  function renderFieldZone(zone: FieldZoneKey, ariaLabel: string, emptyHint: string) {
    const entries = zoneFieldEntries(draft, zone);
    const isActiveZone = fieldDragState !== null && fieldDragState.targetZone === zone;
    return (
      <div
        aria-label={ariaLabel}
        className={["dataset-admin-field-zone", isActiveZone ? "is-drop-target" : ""].filter(Boolean).join(" ")}
        data-customization-drop-zone={zone}
      >
        {entries.length === 0 ? (
          <p className="dataset-admin-field-zone__empty-hint">{emptyHint}</p>
        ) : (
          entries.map((field, index) => {
            const isSource = fieldDragState?.fieldName === field.field_name;
            const isInsertionTarget =
              fieldDragState !== null &&
              fieldDragState.fieldName !== field.field_name &&
              fieldDragState.targetZone === zone &&
              fieldDragState.targetIndex === index;
            const attentionActive = zone === FIELD_BANK_ZONE && field.required;
            return (
              <div
                className={[
                  "dataset-admin-field-chip",
                  attentionActive ? "is-required-attention" : "",
                  isSource ? "is-dragging" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                data-customization-field-index={index}
                data-customization-field-zone={zone}
                key={field.field_name}
                onDoubleClick={() => {
                  if (suppressChipInteractionRef.current) {
                    suppressChipInteractionRef.current = false;
                    return;
                  }
                  openFieldModal(field.field_name);
                }}
                onLostPointerCapture={cancelFieldDrag}
                onPointerCancel={cancelFieldDrag}
                onPointerDown={(event) =>
                  startFieldDrag(event, field.field_name, zone, index, field.display_label || field.field_name)
                }
                onPointerMove={updateFieldDrag}
                onPointerUp={finishFieldDrag}
                ref={(element) => {
                  if (element) {
                    chipRefs.current.set(field.field_name, element);
                  } else {
                    chipRefs.current.delete(field.field_name);
                  }
                }}
                style={{
                  ...(isSource ? fieldChipSourceStyle : {}),
                  ...(isInsertionTarget ? fieldChipInsertionTargetStyle : {}),
                }}
                tabIndex={-1}
              >
                <button
                  aria-label={`Drag field ${field.display_label || field.field_name}`}
                  className="dataset-admin-field-chip__drag"
                  type="button"
                >
                  ⋮⋮
                </button>
                <span className="dataset-admin-field-chip__name">{field.field_name}</span>
                {field.required && <span className="dataset-admin-field-chip__tag">Required</span>}
              </div>
            );
          })
        )}
      </div>
    );
  }

  const requiredInBankCount = draft.fieldHints.filter((field) => field.required && field.hidden).length;
  const bankCount = zoneFieldEntries(draft, FIELD_BANK_ZONE).length;
  const visibleCount = draft.fieldHints.length - bankCount;
  const noSubgroupCount = zoneFieldEntries(draft, NO_SUBGROUP_ZONE).length;
  const editingField =
    fieldModalState.status === "open"
      ? draft.fieldHints.find((field) => field.field_name === fieldModalState.fieldName)
      : undefined;

  return (
    <div className="dataset-admin-builder">
      <section aria-label="Field bank" className="dataset-admin-builder__bank">
        <div className="dataset-admin-builder__heading">
          <div className="dataset-admin-builder__heading-text">
            <span className="dataset-admin-builder__title">Field bank</span>
          </div>
          <Badge>
            {bankCount} available
          </Badge>
        </div>
        {requiredInBankCount > 0 && (
          <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--danger" role="status">
            <strong>
              {requiredInBankCount} required field{requiredInBankCount === 1 ? "" : "s"} still in the bank
            </strong>
            <p className="dataset-admin-exceptional-notice__text">
              Move every required field into the public form layout before saving. The backend rejects a saved
              customization that hides a required field.
            </p>
          </article>
        )}
        {renderFieldZone(FIELD_BANK_ZONE, "Field bank fields", "Drag fields here to remove them from the public form.")}
      </section>

      <section aria-label="Public form layout" className="dataset-admin-builder__canvas">
        <div className="dataset-admin-builder__heading">
          <div className="dataset-admin-builder__heading-text">
            <span className="dataset-admin-builder__title">Public form layout</span>
          </div>
          <div className="dataset-admin-builder__heading-actions">
            <Badge>
              {visibleCount} visible
            </Badge>
            <button className="atlas-button atlas-button--secondary" onClick={handleAddSubgroup} type="button">
              Add subgroup
            </button>
          </div>
        </div>
        {draft.groups.length === 0 ? (
          <p className="dataset-admin-builder__subtitle">
            No subgroups defined. Visible fields without a subgroup render in No subgroup below.
          </p>
        ) : (
          <div className="dataset-admin-builder__stack">
            {draft.groups.map((group, index) => {
              const groupLabel = group.label.trim() ? group.label : deterministicGroupLabel(index);
              const isEditing = editingGroupId === group.group_id;
              return (
                <div
                  className="dataset-admin-builder-card"
                  data-customization-group-index={index}
                  key={group.group_id}
                  style={getGroupCardStyle(index)}
                >
                  <div className="dataset-admin-builder-card__head">
                    <div className="dataset-admin-subgroup-header__stack">
                      <button
                        aria-label={`Move subgroup ${groupLabel} up`}
                        className="dataset-admin-subgroup-header__stack-btn"
                        disabled={index === 0}
                        onClick={() => moveSubgroup(index, -1)}
                        type="button"
                      >
                        ▲
                      </button>
                      <button
                        aria-label={`Move subgroup ${groupLabel} down`}
                        className="dataset-admin-subgroup-header__stack-btn"
                        disabled={index === draft.groups.length - 1}
                        onClick={() => moveSubgroup(index, 1)}
                        type="button"
                      >
                        ▼
                      </button>
                    </div>
                    <button
                      aria-label={`Drag group ${groupLabel}`}
                      className="dataset-admin-subgroup-header__drag"
                      onPointerCancel={cancelGroupDrag}
                      onPointerDown={(event) => startGroupDrag(event, index, groupLabel)}
                      onPointerMove={updateGroupDrag}
                      onPointerUp={finishGroupDrag}
                      type="button"
                    >
                      ⋮⋮
                    </button>
                    <div className="dataset-admin-subgroup-header__title">
                      <strong>{groupLabel}</strong>
                      {group.description && (
                        <span className="dataset-admin-subgroup-header__helper">{group.description}</span>
                      )}
                    </div>
                    <Badge>{zoneFieldEntries(draft, group.group_id).length} fields</Badge>
                    <button
                      className="atlas-button atlas-button--secondary"
                      onClick={() => (isEditing ? cancelGroupEdit() : openGroupEdit(group))}
                      type="button"
                    >
                      Edit
                    </button>
                    <button
                      aria-expanded={!collapsedGroupIds.has(group.group_id)}
                      className="atlas-button atlas-button--secondary"
                      onClick={() => toggleGroupCollapsed(group.group_id)}
                      type="button"
                    >
                      {collapsedGroupIds.has(group.group_id) ? "Expand" : "Collapse"}
                    </button>
                  </div>
                  {isEditing && groupEditDraft && (
                    <div className="dataset-admin-subgroup-edit-panel">
                      <TextField
                        label="Label"
                        onChange={(value) => setGroupEditDraft((current) => (current ? { ...current, label: value } : current))}
                        value={groupEditDraft.label}
                      />
                      <TextField
                        label="Description"
                        onChange={(value) => setGroupEditDraft((current) => (current ? { ...current, description: value } : current))}
                        value={groupEditDraft.description}
                      />
                      <div className="dataset-admin-subgroup-edit-panel__actions">
                        <button className="atlas-button atlas-button--secondary" onClick={cancelGroupEdit} type="button">
                          Cancel
                        </button>
                        <button className="atlas-button" onClick={saveGroupEdit} type="button">
                          Save subgroup
                        </button>
                        <button
                          className="dataset-admin-subgroup-edit-panel__remove"
                          onClick={() => {
                            removeGroup(group.group_id);
                            cancelGroupEdit();
                          }}
                          type="button"
                        >
                          Remove subgroup
                        </button>
                      </div>
                    </div>
                  )}
                  {!collapsedGroupIds.has(group.group_id) &&
                    renderFieldZone(group.group_id, groupLabel, "Drag fields here to add them to this subgroup.")}
                </div>
              );
            })}
          </div>
        )}

        <div aria-label="No subgroup" className="dataset-admin-no-group-zone">
          <div className="dataset-admin-builder__heading">
            <div className="dataset-admin-builder__heading-text">
              <strong>No subgroup</strong>
            </div>
            <Badge>{noSubgroupCount} fields</Badge>
          </div>
          {renderFieldZone(NO_SUBGROUP_ZONE, "No subgroup fields", "Drag fields here to show them without a subgroup.")}
        </div>
      </section>

      {fieldDragState && (
        <div
          aria-hidden="true"
          style={{ ...dragGhostStyle, left: fieldDragState.pointerX, top: fieldDragState.pointerY }}
        >
          {fieldDragState.label}
        </div>
      )}
      {groupDragState && (
        <div
          aria-hidden="true"
          style={{ ...dragGhostStyle, left: groupDragState.pointerX, top: groupDragState.pointerY }}
        >
          {groupDragState.label}
        </div>
      )}

      {editingField && (
        <FieldEditModal
          contractField={contractFieldsByName.get(editingField.field_name)}
          field={editingField}
          onCancel={() => closeFieldModal(editingField.field_name)}
          onSave={(patch) => saveFieldModal(editingField.field_name, patch)}
        />
      )}
    </div>
  );
}

function InferenceFormTab({
  form,
  setField,
  readOnlyData,
  customizationEditorState,
  onRetryCustomization,
  onRetryAuthoringContext,
  onUpdateDraft,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  readOnlyData: ReadOnlyData;
  customizationEditorState: CustomizationEditorState;
  onRetryCustomization: () => void;
  onRetryAuthoringContext: () => void;
  onUpdateDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void;
}) {
  const viewsState = readOnlyData.views;
  const draft = customizationDraftOf(customizationEditorState);
  const contractFieldsByName = useMemo(
    () => new Map(contractFields(stateValue(readOnlyData.contract)).map((field) => [field.name, field])),
    [readOnlyData.contract],
  );

  // Project Spec S0121: semantic availability must be classified from
  // viewsState.status directly -- never `stateValue(readOnlyData.views) ?? []`
  // -- so a genuine zero-view result (status "ready", data []) renders the
  // true empty state below, while a private authoring-context/views-resource
  // failure (status "unavailable") renders a distinct unavailable message
  // with Retry, and an in-flight request (status "idle"/"loading") renders
  // neither.
  if (viewsState.status === "unavailable") {
    return (
      <div className="dataset-admin-tab-workspace dataset-admin-inference-workspace">
        <article className="dataset-admin-exceptional-notice dataset-admin-exceptional-notice--danger" role="status">
          <strong>Predict views unavailable</strong>
          <p className="dataset-admin-exceptional-notice__text">
            The private authoring context could not load the eligible Predict Views for this dataset.
          </p>
          <button onClick={onRetryAuthoringContext} style={secondaryButtonStyle} type="button">
            Retry
          </button>
        </article>
      </div>
    );
  }
  if (viewsState.status !== "ready") {
    return (
      <div className="dataset-admin-tab-workspace dataset-admin-inference-workspace">
        <p className="dataset-admin-inline-status">Loading predict views...</p>
      </div>
    );
  }

  const views = viewsState.data;

  // Project Spec S0100: the normal path (the common, single-eligible-view
  // dataset shape every current fixture and real dataset uses) never shows a
  // manual predict-view selector -- the resolved view is bound silently
  // instead. The select only reappears for the genuine governed multi-view
  // choice S0099 already defines; S0100 does not invent a second selection
  // flow or a normal-path rebind control. Project Spec S0104 removes the
  // single-view read-only badge that used to render here for the normal
  // path, without any replacement tag/pill/card/status label.
  const showBoundViewSelect = views.length > 1;

  return (
    <div className="dataset-admin-tab-workspace dataset-admin-inference-workspace">
      {showBoundViewSelect && (
        <FormRow
          helpText="Multiple predict views are eligible for this dataset. Choose one to build its Inference Form."
          htmlFor="bound-predict-view"
          label="Bound predict view"
        >
          <select
            id="bound-predict-view"
            onChange={(event) => setField("bound_predict_view_id", event.target.value)}
            style={inputStyle}
            value={form.bound_predict_view_id}
          >
            <option value="">No bound view</option>
            {views.map((view) => (
              <option key={view.view_id} value={view.view_id}>
                {view.display?.title || view.view_id}
              </option>
            ))}
          </select>
        </FormRow>
      )}
      <CustomizationStatusPanel
        hasEligibleViews={views.length > 0}
        onRetry={onRetryCustomization}
        state={customizationEditorState}
      />
      {
        // Project Spec S0110: submit-action copy now belongs to the
        // Inference Form customization surface, view-scoped like every
        // other field/group edit here -- disabled (rather than hidden) when
        // no view is bound so the field's presence never implies an
        // editable state that persistCustomizationDraft has nowhere to send.
      }
      <TextField
        disabled={!draft}
        label="Submit button label"
        onChange={(value) =>
          onUpdateDraft((current) => ({
            ...current,
            viewCopy: { ...current.viewCopy, submit_button_label: value },
          }))
        }
        value={draft?.viewCopy.submit_button_label ?? ""}
      />
      {draft && <CustomizationEditor contractFieldsByName={contractFieldsByName} draft={draft} onUpdateDraft={onUpdateDraft} />}
    </div>
  );
}

function ResultCardTab({
  form,
  readOnlyData,
  selectedSlug,
  setField,
}: {
  form: DraftForm;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
}) {
  const resultContract = readOnlyData.resultContract;
  const semantics = resultContract.status === "available" ? resultContract.semantics : null;
  return (
    <TabWorkspace eyebrow="Result Card" helper="Edit public presentation labels only; model behavior remains read-only Atlas state.">
      <Card className="dataset-admin-technical-summary">
        <div className="dataset-admin-card-heading">
          <h2>Technical result contract</h2>
          <p>Release-governed values are read-only. Performance focus is presentation/evaluation context only.</p>
        </div>
        {resultContract.status === "loading" || resultContract.status === "idle" ? <p role="status">Loading result contract…</p> : null}
        {resultContract.status === "unavailable" || resultContract.status === "incompatible" || resultContract.status === "transport_failure" ? (
          <p className="dataset-admin-contract-warning" role="alert">{resultContract.message}</p>
        ) : null}
        <div className="dataset-admin-technical-grid">
          <ReadOnlyField label="Problem type" value={semantics?.problem_type ?? "Unavailable"} />
          <ReadOnlyField label="Performance focus (context only)" value={form.performance_focus.focus_id || "Unavailable"} />
          <ReadOnlyField label="Positive class" value={semantics ? `${semantics.positive_class.class_id} — ${semantics.positive_class.event_label}` : "Unavailable"} />
          <ReadOnlyField label="Primary output" value={semantics?.primary_output ?? "Unavailable"} />
          <ReadOnlyField label="Decision threshold" value={semantics ? `${Math.round(semantics.decision.threshold * 1000) / 10}%` : "Unavailable"} />
          <ReadOnlyField label="Model descriptor" value={semantics ? `${semantics.model_descriptor.display_name} (${semantics.model_descriptor.model_family})` : "Unavailable"} />
        </div>
        {semantics ? (
          <div className="dataset-admin-boundaries" aria-label="Governed risk band boundaries">
            {semantics.interpretation.bands.map((band) => <span key={band.band_id}><strong>{band.band_id}</strong> {Math.round(band.lower_bound * 1000) / 10}%–{Math.round(band.upper_bound * 1000) / 10}%</span>)}
          </div>
        ) : null}
      </Card>
      <div className="dataset-admin-card-grid dataset-admin-card-grid--split">
        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Configuration</h2>
            <p>Risk is enabled only by a compatible technical contract; other interpretations show their requirements.</p>
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="Positive-class probability label" onChange={(value) => setField("positive_class_probability_label", value)} value={form.positive_class_probability_label} />
            <TextField label="Predicted outcome label" onChange={(value) => setField("predicted_outcome_label", value)} value={form.predicted_outcome_label} />
            <TextField label="Positive outcome copy" onChange={(value) => setField("positive_outcome_copy", value)} value={form.positive_outcome_copy} />
            <TextField label="Negative outcome copy" onChange={(value) => setField("negative_outcome_copy", value)} value={form.negative_outcome_copy} />
            <TextField label="Model section label" onChange={(value) => setField("model_section_label", value)} value={form.model_section_label} />
          </div>
          <label className="dataset-admin-native-select">
            <span style={labelStyle}>Badge preset</span>
            <select
              disabled={!semantics}
              onChange={() => setField("interpretation_preset", "risk")}
              style={inputStyle}
              value={semantics ? "risk" : ""}
            >
              <option value="">Risk unavailable</option>
              <option value="risk">Risk</option>
            </select>
          </label>
          <div className="dataset-admin-result-preset-grid">
            {RESULT_PRESET_CARDS.map((preset) => {
              const available = preset.value === "risk" && Boolean(semantics);
              const selected = available && form.interpretation_preset === "risk";
              return (
                <button
                  aria-disabled={!available}
                  aria-pressed={available ? selected : undefined}
                  className={[
                    "dataset-admin-result-preset-card",
                    selected ? "is-selected" : "",
                    !available ? "is-locked" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  disabled={!available}
                  key={preset.value}
                  onClick={() => {
                    if (available) {
                      setField("interpretation_preset", "risk");
                    }
                  }}
                  type="button"
                >
                  <strong>{preset.label}</strong>
                  <span>{preset.requirement}</span>
                  {!available ? <Badge>Locked</Badge> : null}
                </button>
              );
            })}
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="High label" onChange={(value) => setField("interpretation_high", value)} value={form.interpretation_high} />
            <TextField label="Medium label" onChange={(value) => setField("interpretation_medium", value)} value={form.interpretation_medium} />
            <TextField label="Low label" onChange={(value) => setField("interpretation_low", value)} value={form.interpretation_low} />
          </div>
        </Card>

        <Card className="dataset-admin-preview-card">
          <div className="dataset-admin-card-heading">
            <h2>Example result</h2>
            <p>Compact preview fed by the current label fields.</p>
          </div>
          <ResultCardLivePreview form={form} resultContract={resultContract} resetKey={selectedSlug} />
        </Card>
      </div>
    </TabWorkspace>
  );
}

// The workspace toolbar keeps successful publish feedback intentionally
// compact.
function toolbarPublicationFeedback(publicationState: PublicationState): string | null {
  if (publicationState.status !== "published") {
    return null;
  }
  return "Changes saved.";
}

// Project Spec S0116: canonical console severities. Color is never the only
// signal -- every line's bracketed text (e.g. "[BLOCKED]") is always present.
type ConsoleSeverity = "OK" | "INFO" | "WARN" | "BLOCKED" | "ERROR";
type ConsoleLine = { id: string; severity: ConsoleSeverity; text: string };

// Canonical S0115 blocker codes -> operational console text. An unrecognized
// code renders a bounded generic line instead of the raw code (Section 4,
// "Render backend blockers").
// Project Spec S0125: snapshot_missing/stale/invalid moved here from
// KNOWN_OBSERVATION_LINES below -- the backend now reports them as blockers
// whenever they prevent public reachability, never as non-blocking
// observations.
const KNOWN_BLOCKER_LINES: Record<string, string> = {
  visibility_disabled: "Public access is disabled by the effective visibility policy.",
  review_pending: "Dataset review state prevents public access.",
  snapshot_missing: "No published snapshot is available.",
  snapshot_stale: "Published snapshot belongs to a different active release.",
  snapshot_invalid: "Published snapshot metadata is invalid.",
};

// Canonical S0115 observation codes -> operational console severity/text. An
// unrecognized code renders a bounded generic INFO line (Section 4, "Render
// backend observations").
const KNOWN_OBSERVATION_LINES: Record<string, { severity: "INFO" | "WARN"; text: string }> = {
  visibility_default_applied: { severity: "INFO", text: "Default visibility fallback is active." },
  visibility_record_invalid: { severity: "WARN", text: "Visibility record is invalid; the backend fallback is active." },
  configured_hidden_but_effectively_visible_without_snapshot: {
    severity: "WARN",
    text: "Configured visibility is hidden, but current no-snapshot policy still leaves the public route effectively visible.",
  },
};

function snapshotStatusLabel(status: AdminPublicationStateProjection["snapshot"]["status"]): string {
  switch (status) {
    case "current_release":
      return "current release";
    case "stale_release":
      return "stale release";
    case "invalid":
      return "invalid";
    case "missing":
    default:
      return "missing";
  }
}

function snapshotAlignmentLabel(snapshot: AdminPublicationStateProjection["snapshot"]): string {
  if (snapshot.matches_active_release === true) {
    return "current";
  }
  if (snapshot.matches_active_release === false) {
    return "stale";
  }
  return "not available";
}

// Project Spec S0125: review-approval blocker codes -> the operator-facing
// "required next action" text. An unrecognized/absent blocker falls back to
// a bounded generic line rather than a raw code.
const REVIEW_APPROVAL_BLOCKER_ACTIONS: Record<string, string> = {
  snapshot_missing: "Publish a current release snapshot before approving review.",
  snapshot_stale: "Publish a snapshot for the current active release before approving review.",
  snapshot_invalid: "Publish a valid snapshot before approving review.",
};

// The Publishing tab's review-approval action is enabled only when a
// confirmed "ready" projection reports needs_review + approval_allowed, and
// no unpublished profile/customization workspace changes are pending --
// mirrors reviewApprovalRequiredNextAction below so the button's enabled
// state and its own explanatory text never disagree.
function reviewApprovalEnabled(projectionState: PublicationProjectionState, hasUnpublishedChanges: boolean): boolean {
  return (
    projectionState.status === "ready" &&
    projectionState.projection.review.status === "needs_review" &&
    projectionState.projection.review.approval_allowed &&
    !hasUnpublishedChanges
  );
}

function reviewApprovalRequiredNextAction(
  projectionState: PublicationProjectionState,
  hasUnpublishedChanges: boolean,
): string {
  if (projectionState.status === "idle" || projectionState.status === "loading") {
    return "Select a dataset to check review approval eligibility.";
  }
  if (projectionState.status === "unavailable") {
    return "Review approval is unavailable until publication state can be checked.";
  }
  const { review } = projectionState.projection;
  if (review.status === "ready") {
    return "This Dataset Detail's review is already approved.";
  }
  if (hasUnpublishedChanges) {
    return "Use Publish changes to publish the current workspace before approving review.";
  }
  if (!review.approval_allowed) {
    const [firstBlocker] = review.approval_blockers;
    return (
      (firstBlocker && REVIEW_APPROVAL_BLOCKER_ACTIONS[firstBlocker]) ??
      "Review approval is not currently available for this Dataset Detail."
    );
  }
  return "Ready to approve this Dataset Detail's review.";
}

// The deterministic, ordered set of console lines derived from one loaded
// S0115 projection -- core facts first (Section 4, "Render core console
// lines"), then backend blockers, then backend observations, both in the
// same order the backend already returned them.
function projectionConsoleLines(projection: AdminPublicationStateProjection): ConsoleLine[] {
  const lines: ConsoleLine[] = [
    { id: "dataset", severity: "OK", text: `Dataset selected: ${projection.dataset_slug}` },
    {
      id: "configured-visibility",
      severity: projection.visibility.configured_visible ? "OK" : "INFO",
      text: `Configured visibility: ${projection.visibility.configured_visible ? "visible" : "hidden"}`,
    },
    {
      id: "visibility-source",
      severity: projection.visibility.source === "explicit_record" ? "OK" : "WARN",
      text: `Visibility source: ${projection.visibility.source === "explicit_record" ? "explicit record" : "default fallback"}`,
    },
    {
      id: "visibility-record",
      severity: projection.visibility.record_status === "valid" ? "OK" : "WARN",
      text: `Visibility record: ${projection.visibility.record_status}`,
    },
    {
      id: "effective-visibility",
      severity: projection.visibility.effective_visible ? "OK" : "WARN",
      text: `Effective visibility: ${projection.visibility.effective_visible ? "visible" : "hidden"}`,
    },
    {
      id: "review-state",
      severity: projection.review.status === "ready" ? "OK" : "BLOCKED",
      text: `Review state: ${projection.review.status === "ready" ? "ready" : "needs review"}`,
    },
    {
      id: "published-snapshot",
      severity: projection.snapshot.status === "current_release" ? "OK" : "WARN",
      text: `Published snapshot: ${snapshotStatusLabel(projection.snapshot.status)}`,
    },
    {
      id: "snapshot-alignment",
      severity: projection.snapshot.matches_active_release === true ? "OK" : "WARN",
      text: `Snapshot release alignment: ${snapshotAlignmentLabel(projection.snapshot)}`,
    },
    {
      id: "public-route",
      severity: projection.public_access.reachable ? "OK" : "BLOCKED",
      text: `Public Dataset Detail route: ${projection.public_access.reachable ? "reachable" : "not reachable"}`,
    },
  ];

  projection.public_access.blockers.forEach((code, index) => {
    lines.push({
      id: `blocker-${index}-${code}`,
      severity: "BLOCKED",
      text: KNOWN_BLOCKER_LINES[code] ?? "Public access is blocked by an unrecognized backend condition.",
    });
  });

  projection.public_access.observations.forEach((code, index) => {
    const known = KNOWN_OBSERVATION_LINES[code];
    lines.push({
      id: `observation-${index}-${code}`,
      severity: known?.severity ?? "INFO",
      text: known?.text ?? "An additional backend operational observation is present.",
    });
  });

  return lines;
}

// Project Spec S0144: the private frontend-only audit model backing the
// Publishing console's Live Preview inference session history. Each record
// carries only what console projection needs -- a local event id, the
// monotonic attempt sequence, which lifecycle kind occurred, and (for a
// successful terminal event) a bounded safe result summary already derived
// from the same validated binary-classification-result.v1 shape the shared
// Result Card renders. No submitted field value, raw payload, raw response,
// exception object, or wall-clock timestamp is ever carried.
export type LiveInferenceAuditEventKind = "started" | "succeeded" | "validation_failed" | "execution_failed";

export type LiveInferenceAuditSuccessSummary = {
  predictedPositive: boolean;
  positiveClassProbability: number;
  modelDisplayName?: string;
};

// Project Spec S0147: retention bound for a single validation_failed
// record's nested issue list -- independent of, and much smaller than,
// LIVE_INFERENCE_AUDIT_RETENTION_LIMIT below (which bounds the number of
// lifecycle *records*, not the issues nested inside one of them).
const LIVE_INFERENCE_AUDIT_ISSUE_LIMIT = 20;

export type LiveInferenceAuditRecord = {
  id: string;
  attemptSequence: number;
  kind: LiveInferenceAuditEventKind;
  successSummary?: LiveInferenceAuditSuccessSummary;
  // Project Spec S0147: present only for kind "validation_failed", and only
  // when at least one contract-filtered, label-resolved issue survived
  // normalization -- absent/empty falls back to the existing generic
  // console line. Never present for "started", "succeeded" or
  // "execution_failed".
  issues?: InferenceLifecycleValidationIssue[];
  // Project Spec S0151: present only for kind "execution_failed", and only
  // when the backend safely classified the failure through a controlled
  // typed boundary. Never present for "started", "succeeded" or
  // "validation_failed".
  runtimeDiagnosticCode?: InferenceRuntimeDiagnosticCode;
};

// Owned by DatasetAdminPage (Section "Keep the history above top-level tab
// ownership"), scoped to exactly one selected dataset identity at a time.
// activeAttemptSequence correlates the next terminal event to the attempt
// currently outstanding -- null whenever no started event is awaiting a
// terminal one, which is also how a duplicate or unmatched terminal
// callback is safely ignored (see reduceLiveInferenceAuditEvent).
export type LiveInferenceAuditState = {
  datasetSlug: string;
  records: LiveInferenceAuditRecord[];
  nextAttemptSequence: number;
  nextEventId: number;
  activeAttemptSequence: number | null;
};

const LIVE_INFERENCE_AUDIT_RETENTION_LIMIT = 50;

export function emptyLiveInferenceAuditState(datasetSlug: string): LiveInferenceAuditState {
  return { datasetSlug, records: [], nextAttemptSequence: 1, nextEventId: 1, activeAttemptSequence: null };
}

function appendBoundedLiveInferenceAuditRecord(
  state: LiveInferenceAuditState,
  record: LiveInferenceAuditRecord,
): LiveInferenceAuditState {
  const records = [...state.records, record];
  return {
    ...state,
    records:
      records.length > LIVE_INFERENCE_AUDIT_RETENTION_LIMIT
        ? records.slice(records.length - LIVE_INFERENCE_AUDIT_RETENTION_LIMIT)
        : records,
  };
}

// Project Spec S0144: the sole correlation authority for one Live Preview
// inference lifecycle event. datasetSlugAtCapture is the selected-dataset
// identity the calling callback closed over at the moment InferenceForm
// invoked it -- if that no longer matches the current audit session's
// dataset (the operator switched datasets while the callback was still in
// flight), the event is ignored entirely rather than fabricating or
// misattributing a record. A terminal event (anything but "started") is
// likewise ignored whenever there is no currently active attempt to
// correlate it to, which safely absorbs both a duplicate terminal callback
// for an attempt already closed and a terminal callback with no matching
// start.
export function reduceLiveInferenceAuditEvent(
  state: LiveInferenceAuditState,
  datasetSlugAtCapture: string,
  kind: LiveInferenceAuditEventKind,
  successSummary?: LiveInferenceAuditSuccessSummary,
  validationIssues?: InferenceLifecycleValidationIssue[],
  runtimeDiagnosticCode?: InferenceRuntimeDiagnosticCode,
): LiveInferenceAuditState {
  if (datasetSlugAtCapture !== state.datasetSlug) {
    return state;
  }

  if (kind === "started") {
    const attemptSequence = state.nextAttemptSequence;
    return appendBoundedLiveInferenceAuditRecord(
      {
        ...state,
        nextAttemptSequence: attemptSequence + 1,
        nextEventId: state.nextEventId + 1,
        activeAttemptSequence: attemptSequence,
      },
      { id: `live-inference-audit-${state.nextEventId}`, attemptSequence, kind: "started" },
    );
  }

  if (state.activeAttemptSequence === null) {
    return state;
  }

  const attemptSequence = state.activeAttemptSequence;
  // Project Spec S0147: defensively re-bounded here (in addition to
  // InferenceForm's own normalizer bound) so this reducer's own retention
  // guarantee never depends on an upstream caller having already bounded
  // the list.
  const boundedIssues =
    kind === "validation_failed" && validationIssues && validationIssues.length > 0
      ? validationIssues.slice(0, LIVE_INFERENCE_AUDIT_ISSUE_LIMIT)
      : undefined;
  // Project Spec S0151: retained only for "execution_failed" -- never for
  // "succeeded" or "validation_failed", even if a caller passes one.
  const retainedRuntimeDiagnosticCode = kind === "execution_failed" ? runtimeDiagnosticCode : undefined;
  return appendBoundedLiveInferenceAuditRecord(
    { ...state, nextEventId: state.nextEventId + 1, activeAttemptSequence: null },
    {
      id: `live-inference-audit-${state.nextEventId}`,
      attemptSequence,
      kind,
      successSummary: kind === "succeeded" ? successSummary : undefined,
      issues: boundedIssues,
      runtimeDiagnosticCode: retainedRuntimeDiagnosticCode,
    },
  );
}

// One deterministic formatting helper for the bounded [0, 1] positive-class
// probability -- mirrors BinaryClassificationResult.tsx's own
// formatProbability precision (percentage, at most one decimal place,
// rounded) so the console's number reads consistent with the Result Card. A
// non-finite or out-of-domain value is never interpolated -- the whole
// probability clause is omitted instead.
function formatLiveInferenceAuditProbability(value: number): string | null {
  if (!Number.isFinite(value) || value < 0 || value > 1) return null;
  const rounded = Math.round(value * 1000) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${text}%`;
}

// Project Spec S0147: the bounded, frontend-owned copy for each allowlisted
// violation. Deliberately never interpolates the backend's own `message`
// property -- console copy is owned entirely by this mapping.
const VALIDATION_VIOLATION_LINE_COPY: Record<InferenceValidationViolation, string> = {
  missing_required_field: "a required value was not submitted.",
  type_mismatch: "the submitted value has the wrong type.",
  domain_violation: "the submitted value is outside the accepted domain.",
};

// Project Spec S0151/S0152: the bounded, frontend-owned copy for each
// allowlisted runtime diagnostic code. Deliberately never interpolates a
// backend message, field name, submitted value, package name, path, or
// exception -- console copy is owned entirely by this mapping.
const RUNTIME_DIAGNOSTIC_LINE_COPY: Record<InferenceRuntimeDiagnosticCode, string> = {
  INFERENCE_BUNDLE_UNAVAILABLE: "Runtime diagnostic: the active release inference bundle is unavailable.",
  MODEL_ARTIFACT_UNAVAILABLE: "Runtime diagnostic: the active release model artifact is unavailable.",
  MODEL_ARTIFACT_HASH_MISMATCH:
    "Runtime diagnostic: the active release model artifact failed integrity verification.",
  RUNTIME_DEPENDENCY_UNAVAILABLE: "Runtime diagnostic: a required inference runtime dependency is unavailable.",
  MODEL_DESERIALIZATION_FAILED: "Runtime diagnostic: the active release model could not be loaded.",
  PREDICTION_EXECUTION_FAILED: "Runtime diagnostic: the model could not complete prediction execution.",
  RESULT_VALIDATION_FAILED: "Runtime diagnostic: the inference result failed governed result validation.",
  RUNTIME_INPUT_CONTRACT_INCONSISTENT:
    "Runtime diagnostic: the active release input contract is inconsistent with the inference bundle.",
};

// Project Spec S0144: renders the required bounded, explicit console text
// for each retained audit record. Only ever built from the record's own
// bounded fields -- never a raw payload, response, or exception message. An
// absent optional success-summary field is omitted cleanly rather than
// rendered as undefined/null/an object.
//
// Project Spec S0147: a validation_failed record with at least one retained
// issue renders one bounded attempt-level summary line (singular/plural)
// followed by one bounded field-level detail line per issue, in original
// normalized order; each detail line's id is derived from the parent
// record's own event id plus its issue position, so repeated attempts with
// identical field failures still produce distinct line ids (their parent
// record ids always differ). A record with no valid retained issue falls
// back to the existing generic line.
export function liveInferenceAuditConsoleLines(records: LiveInferenceAuditRecord[]): ConsoleLine[] {
  const lines: ConsoleLine[] = [];

  for (const record of records) {
    if (record.kind === "started") {
      lines.push({
        id: record.id,
        severity: "INFO",
        text: `Live Preview inference attempt #${record.attemptSequence} started.`,
      });
      continue;
    }

    if (record.kind === "validation_failed") {
      if (record.issues && record.issues.length > 0) {
        const count = record.issues.length;
        lines.push({
          id: record.id,
          severity: "ERROR",
          text: `Live Preview inference attempt #${record.attemptSequence} was rejected with ${count} invalid ${
            count === 1 ? "input" : "inputs"
          }.`,
        });
        record.issues.forEach((issue, index) => {
          lines.push({
            id: `${record.id}-issue-${index}`,
            severity: "ERROR",
            text: `${issue.fieldLabel}: ${VALIDATION_VIOLATION_LINE_COPY[issue.violation]}`,
          });
        });
      } else {
        lines.push({
          id: record.id,
          severity: "ERROR",
          text: `Live Preview inference attempt #${record.attemptSequence} was rejected because the submitted fields were invalid.`,
        });
      }
      continue;
    }

    if (record.kind === "execution_failed") {
      lines.push({
        id: record.id,
        severity: "ERROR",
        text: `Live Preview inference attempt #${record.attemptSequence} could not be completed.`,
      });
      // Project Spec S0151: at most one additional bounded runtime-diagnostic
      // line, immediately following the generic line above, only when the
      // backend safely classified the failure through a controlled typed
      // boundary. No diagnostic line is added when the code is absent,
      // malformed, or unknown (normalizeInferenceRuntimeDiagnostic already
      // dropped anything outside the closed allowlist before this record was
      // ever created).
      if (record.runtimeDiagnosticCode) {
        lines.push({
          id: `${record.id}-runtime-diagnostic`,
          severity: "ERROR",
          text: RUNTIME_DIAGNOSTIC_LINE_COPY[record.runtimeDiagnosticCode],
        });
      }
      continue;
    }

    const clauses: string[] = [];
    if (record.successSummary) {
      clauses.push(record.successSummary.predictedPositive ? "positive outcome" : "negative outcome");
      const probabilityText = formatLiveInferenceAuditProbability(record.successSummary.positiveClassProbability);
      if (probabilityText) {
        clauses.push(`positive-class probability ${probabilityText}`);
      }
      if (record.successSummary.modelDisplayName) {
        clauses.push(`model ${record.successSummary.modelDisplayName}`);
      }
    }
    const summarySuffix = clauses.length > 0 ? `: ${clauses.join(", ")}` : "";
    lines.push({
      id: record.id,
      severity: "OK",
      text: `Live Preview inference attempt #${record.attemptSequence} completed successfully${summarySuffix}.`,
    });
  }

  return lines;
}

// Translates the bounded publication-state request machine, plus local
// visibility-write failure, into the console's full deterministic line set
// (Section 4, "Render local request states" and "Avoid duplicate or stale
// lines"). Never renders raw response bodies, stack traces, or paths.
// Project Spec S0144: liveInferenceAuditLines are appended after every
// branch (including the idle/loading/unavailable early returns, so the
// history is never silently discarded while publication projection isn't
// ready) and are deliberately excluded from the publication-line by-text
// dedup below -- two attempts with identical safe summaries must remain two
// distinct lines.
function buildOperationalConsoleLines(
  projectionState: PublicationProjectionState,
  visibilityWriteFailed: boolean,
  reviewApprovalWriteFailed: boolean,
  liveInferenceAuditLines: ConsoleLine[] = [],
): ConsoleLine[] {
  if (projectionState.status === "idle") {
    return [
      { id: "no-dataset", severity: "INFO", text: "Select a dataset to inspect publication state." },
      ...liveInferenceAuditLines,
    ];
  }
  if (projectionState.status === "loading") {
    return [{ id: "loading", severity: "INFO", text: "Checking publication state..." }, ...liveInferenceAuditLines];
  }
  if (projectionState.status === "unavailable") {
    return [
      { id: "unavailable", severity: "ERROR", text: "Publication state could not be loaded from the private Admin API." },
      ...liveInferenceAuditLines,
    ];
  }

  const lines = projectionConsoleLines(projectionState.projection);

  if (projectionState.status === "saving") {
    lines.push({ id: "saving", severity: "INFO", text: "Saving configured visibility..." });
  } else if (visibilityWriteFailed) {
    lines.push({
      id: "visibility-write-error",
      severity: "ERROR",
      text: "Configured visibility could not be saved. The previous confirmed value remains active.",
    });
  }

  if (projectionState.status === "approving") {
    lines.push({ id: "approving", severity: "INFO", text: "Approving Dataset Detail review..." });
  } else if (reviewApprovalWriteFailed) {
    lines.push({
      id: "review-approval-write-error",
      severity: "ERROR",
      text: "Review approval could not be saved. The previous confirmed state remains active.",
    });
  }

  const seen = new Set<string>();
  const dedupedLines = lines.filter((line) => {
    if (seen.has(line.text)) {
      return false;
    }
    seen.add(line.text);
    return true;
  });

  return [...dedupedLines, ...liveInferenceAuditLines];
}

// Read-only operational status surface (Section 4, "Create the operational
// console"): no input, no command prompt, only the bounded deterministic
// lines computed above.
// Fractional layout values and sub-pixel rounding can make an exact
// scrollHeight equality unstable. Within this fixed distance the operator
// is treated as following the live tail; farther away preserves deliberate
// historical inspection.
export const OPERATIONAL_CONSOLE_BOTTOM_TOLERANCE_PX = 24;

export function OperationalConsole({
  latestInferenceLineId,
  lines,
}: {
  latestInferenceLineId: string | null;
  lines: ConsoleLine[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const previousInferenceLineIdRef = useRef<string | null>(null);
  const followsLiveTailRef = useRef(true);

  useLayoutEffect(() => {
    if (!latestInferenceLineId || latestInferenceLineId === previousInferenceLineIdRef.current) return;

    const container = containerRef.current;
    const isInitialInferenceMount = previousInferenceLineIdRef.current === null;
    previousInferenceLineIdRef.current = latestInferenceLineId;
    if (!container || (!isInitialInferenceMount && !followsLiveTailRef.current)) return;

    container.scrollTop = container.scrollHeight;
    followsLiveTailRef.current = true;
  }, [latestInferenceLineId]);

  function trackOperatorScroll() {
    const container = containerRef.current;
    if (!container) return;
    const bottomDistance = container.scrollHeight - container.clientHeight - container.scrollTop;
    followsLiveTailRef.current = bottomDistance <= OPERATIONAL_CONSOLE_BOTTOM_TOLERANCE_PX;
  }

  return (
    <div
      aria-label="Dataset publication operational status"
      aria-live="polite"
      className="dataset-admin-console"
      onScroll={trackOperatorScroll}
      ref={containerRef}
      role="log"
    >
      {lines.map((line) => (
        <p className={`dataset-admin-console-line dataset-admin-console-line--${line.severity.toLowerCase()}`} key={line.id}>
          <span className="dataset-admin-console-severity">[{line.severity}]</span> {line.text}
        </p>
      ))}
    </div>
  );
}

// Authority for the header badge (Section 4, "Replace the header badge
// authority") -- reachability-based, unchanged by Project Spec S0123.
function publicationBadgeLabel(
  projectionState: PublicationProjectionState,
): "No dataset selected" | "Checking..." | "Public" | "Private" {
  if (projectionState.status === "idle") {
    return "No dataset selected";
  }
  if (projectionState.status === "loading") {
    return "Checking...";
  }
  if (projectionState.status === "unavailable") {
    return "Private";
  }
  return projectionState.projection.public_access.reachable ? "Public" : "Private";
}

// Project Spec S0123: the "Open public Dataset Detail page" action's sole
// authority. Deliberately follows configured visibility, not effective
// reachability -- a dataset can be configured visible but still blocked from
// public reachability (e.g. review_pending), and the action must stay
// enabled in that case since it only opens the route, it does not bypass
// S0117's own access-state rendering. Only the "ready" status counts: a
// "saving" projection's own retained prior projection must never keep the
// action interactive while a visibility write is unresolved, and no other
// status carries a confirmed value at all.
function publicPageActionAvailable(projectionState: PublicationProjectionState): boolean {
  return projectionState.status === "ready" && projectionState.projection.visibility.configured_visible;
}

// Project Spec S0116: the tab's core surfaces are the Visible publicly
// switch and the read-only operational console. The switch is controlled by
// visibility.configured_visible (never effective_visible) and is disabled
// only for no-dataset/loading/saving/approving/unavailable, never merely
// because a snapshot is missing or stale.
//
// Project Spec S0125 minimally supersedes the prior "exactly two surfaces"
// restriction only to add the missing review-approval control -- the
// removed duplicated publication cards and tab-local content-publish
// actions stay removed; the global toolbar remains the sole Publish changes
// action.
function PublishingTab({
  hasUnpublishedChanges,
  liveInferenceAuditRecords,
  onApproveReview,
  onToggleVisibility,
  projectionState,
  reviewApprovalWriteFailed,
  selectedSlug,
  visibilityWriteFailed,
}: {
  hasUnpublishedChanges: boolean;
  liveInferenceAuditRecords: LiveInferenceAuditRecord[];
  onApproveReview: () => void;
  onToggleVisibility: (visible: boolean) => void;
  projectionState: PublicationProjectionState;
  reviewApprovalWriteFailed: boolean;
  selectedSlug: string;
  visibilityWriteFailed: boolean;
}) {
  const switchChecked =
    projectionState.status === "saving"
      ? projectionState.pendingVisible
      : projectionState.status === "ready" || projectionState.status === "approving"
      ? projectionState.projection.visibility.configured_visible
      : false;
  const switchDisabled =
    !selectedSlug ||
    projectionState.status === "idle" ||
    projectionState.status === "loading" ||
    projectionState.status === "saving" ||
    projectionState.status === "approving" ||
    projectionState.status === "unavailable";
  const switchStatusText =
    projectionState.status === "saving"
      ? "Saving..."
      : projectionState.status === "loading"
      ? "Checking..."
      : visibilityWriteFailed
      ? "Save failed. Previous value restored."
      : null;
  const liveInferenceLines = liveInferenceAuditConsoleLines(liveInferenceAuditRecords);
  const latestInferenceLineId = liveInferenceLines.at(-1)?.id ?? null;
  const consoleLines = buildOperationalConsoleLines(
    projectionState,
    visibilityWriteFailed,
    reviewApprovalWriteFailed,
    liveInferenceLines,
  );

  const reviewStatusText =
    projectionState.status === "ready" || projectionState.status === "approving"
      ? projectionState.projection.review.status === "ready"
        ? "ready"
        : "needs review"
      : "unknown";
  const snapshotReadinessText =
    projectionState.status === "ready" || projectionState.status === "approving"
      ? snapshotStatusLabel(projectionState.projection.snapshot.status)
      : "unknown";
  const approveEnabled = reviewApprovalEnabled(projectionState, hasUnpublishedChanges);
  const requiredNextAction = reviewApprovalRequiredNextAction(projectionState, hasUnpublishedChanges);
  const approveStatusText =
    projectionState.status === "approving"
      ? "Approving..."
      : reviewApprovalWriteFailed
      ? "Approval failed. Previous state retained."
      : null;

  return (
    <div className="dataset-admin-publishing-panel">
      <Card className="dataset-admin-config-card dataset-admin-publishing-panel__card">
        <span className="dataset-admin-tab-workspace__eyebrow">Public visibility</span>
        <div className="dataset-admin-visibility-row">
          <div>
            <strong>Visible publicly</strong>
            {switchStatusText && <p role="status">{switchStatusText}</p>}
          </div>
          <label aria-label="Visible Publicly" className="dataset-admin-switch">
            <input
              checked={switchChecked}
              disabled={switchDisabled}
              onChange={(event) => onToggleVisibility(event.target.checked)}
              type="checkbox"
            />
            <span aria-hidden="true" />
          </label>
        </div>
      </Card>
      <Card className="dataset-admin-config-card dataset-admin-publishing-panel__card">
        <span className="dataset-admin-tab-workspace__eyebrow">Review approval</span>
        <p style={mutedTextStyle}>Review status: {reviewStatusText}</p>
        <p style={mutedTextStyle}>Snapshot readiness: {snapshotReadinessText}</p>
        <p style={mutedTextStyle}>{requiredNextAction}</p>
        {approveStatusText && <p role="status">{approveStatusText}</p>}
        <button
          disabled={!approveEnabled}
          onClick={onApproveReview}
          style={approveEnabled ? actionButtonStyle : disabledButtonStyle}
          type="button"
        >
          Approve Dataset Detail
        </button>
      </Card>
      <OperationalConsole latestInferenceLineId={latestInferenceLineId} lines={consoleLines} />
    </div>
  );
}

// Project Spec S0120: renders the same shared public DatasetDetailSurface
// (S0119) used by /dataset/:slug, fed entirely by the current Admin draft
// and already-loaded read-only technical context. This component owns only
// data adaptation -- contract shape, metric/visualization selection, and the
// Admin-only Inference/Result composition -- while the shared surface owns
// header/metadata/tabs/Overview/Inference/Documentation placement and its
// own theme scope.
function DatasetDetailLivePreview({
  dataset,
  form,
  readOnlyData,
  selectedSlug,
  customizationEditorState,
  liveInferenceExecutor,
  onLiveInferenceLifecycleEvent,
}: {
  dataset?: DatasetListing;
  form: DraftForm;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  customizationEditorState: CustomizationEditorState;
  liveInferenceExecutor: InferenceExecutor;
  onLiveInferenceLifecycleEvent: (event: InferenceLifecycleEvent) => void;
}) {
  const context = stateValue(readOnlyData.context);
  const contract = stateValue(readOnlyData.contract);
  const metrics = stateValue(readOnlyData.metrics);
  const visualizations = toVisualizationsPayload(stateValue(readOnlyData.visualizations));

  // livePreviewProjection.ts's projectDatasetDetailPreview expects its own
  // locally-declared {fields?} shape (out of this issue's edit scope); adapt
  // the real {features} contract shape into that shape here rather than
  // modifying livePreviewProjection.ts.
  const previewContract = contract ? { fields: contract.features } : null;
  // Project Spec S0154: feeds the currently loaded, dataset-bound private
  // result-contract state into the shared Target projection -- no
  // additional request, and never a public-endpoint read for this preview.
  const preview = projectDatasetDetailPreview(
    dataset,
    form,
    context,
    previewContract,
    metrics,
    readOnlyData.resultContract,
  );

  const performanceContent = (
    <PerformanceSummary
      metrics={metrics ?? {}}
      performanceFocus={projectPerformanceFocusPreview(form.performance_focus)}
    />
  );
  const targetDistributionContent = <TargetDistribution visualizations={visualizations} />;
  const featureImportanceContent = <FeatureImportance visualizations={visualizations} />;

  // Project Spec S0143: the Dataset Detail Live Preview Inference tab now
  // owns one real, executable InferenceForm lifecycle -- the same
  // public-inference-surface layout DatasetPage.tsx renders -- instead of a
  // non-submitting preview form plus a separate synthetic ResultCardLivePreview.
  // The private Admin executeAdminInference executor replaces the public
  // fetch target; the technical feature contract, result contract and
  // presentation still come from the same private authoring context and
  // draft this preview already loads.
  const customizationDraft = customizationDraftOf(customizationEditorState);
  const liveInferenceCustomization: PredictViewCustomization | undefined = customizationDraft
    ? (() => {
        const { field_hints, groups, view_copy } = customizationDraftToRecord(customizationDraft);
        return { field_hints, groups, view_copy };
      })()
    : undefined;

  const inferenceContent = contract ? (
    <InferenceForm
      adminInferenceGuidance={
        readOnlyData.inferenceGuidance.status === "ready"
          ? normalizeAdminInferenceGuidance(readOnlyData.inferenceGuidance.data, contract.features)
          : undefined
      }
      contract={contract}
      customization={liveInferenceCustomization}
      executeInference={liveInferenceExecutor}
      initialResultProbability={0}
      // Project Spec S0144: the bounded lifecycle observer feeding the
      // Publishing console's Live Preview inference session audit history.
      onLifecycleEvent={onLiveInferenceLifecycleEvent}
      // Project Spec S0143: resets (and stale-response-guards) the Live
      // Preview result whenever the selected dataset or its bound Predict
      // View/customization identity changes -- never on unrelated re-renders.
      resetKey={`${selectedSlug}::${form.bound_predict_view_id}`}
      resultContract={toInferenceResultContract(readOnlyData.resultContract)}
      resultPresentation={presentationFromForm(form)}
      slug={selectedSlug}
      submitButtonLabel={customizationDraft?.viewCopy.submit_button_label.trim() || undefined}
    />
  ) : (
    <p style={mutedTextStyle}>Contract fields are unavailable for this dataset.</p>
  );

  // Project Spec S0196: Live Preview reflects the committed workspace
  // Markdown (form.documentation) -- never the Documentation tab's unsaved
  // editing buffer, which stays local to DocumentationTab until Save.
  const documentationContent = <DatasetDocumentation content={form.documentation} />;

  return (
    <DatasetDetailSurface
      analysisType={preview.analysisType}
      datasetSubtitle={preview.subtitle}
      datasetTitle={preview.datasetTitle}
      documentationContent={documentationContent}
      featureImportanceContent={featureImportanceContent}
      inferenceContent={inferenceContent}
      metadata={preview.metadata}
      performanceContent={performanceContent}
      problemSummaryBody={preview.problemSummaryBody}
      problemSummaryTitle={preview.problemSummaryTitle}
      targetDistributionContent={targetDistributionContent}
      themePresetId={form.theme_preset}
    />
  );
}

function ResultCardLivePreview({ form, resetKey, resultContract }: { form: DraftForm; resetKey: string; resultContract: ResultContractState }) {
  const semantics = resultContract.status === "available" ? resultContract.semantics : null;
  const threshold = semantics?.decision.threshold ?? 0;
  const [probability, setProbability] = useState(() => semantics ? positiveScenarioProbability(threshold) : 0);

  useEffect(() => {
    setProbability(semantics ? positiveScenarioProbability(semantics.decision.threshold) : 0);
  }, [resetKey, semantics]);

  const presentation = presentationFromForm(form);
  const result = semantics ? projectBinaryResultPreview(semantics, presentation, probability) : null;
  const negativeProbability = semantics ? negativeScenarioProbability(threshold) : null;

  return (
    <div className="dataset-admin-result-preview">
      <p style={mutedTextStyle}>Preview only — no inference request is executed.</p>
      {semantics ? (
        <div className="dataset-admin-preview-controls">
          <div className="dataset-admin-scenario-controls" role="group" aria-label="Preview scenario">
            <button aria-pressed={probability >= threshold} onClick={() => setProbability(positiveScenarioProbability(threshold))} type="button">Positive scenario</button>
            <button aria-pressed={probability < threshold} disabled={negativeProbability === null} onClick={() => negativeProbability !== null && setProbability(negativeProbability)} title={negativeProbability === null ? "Unavailable when the decision threshold is zero" : undefined} type="button">Negative scenario</button>
          </div>
          <label className="dataset-admin-probability-control">
            <span>Preview positive-class probability: {Math.round(probability * 1000) / 10}%</span>
            <input aria-valuetext={`${Math.round(probability * 1000) / 10}%; decision threshold ${Math.round(threshold * 1000) / 10}%`} max="1" min="0" onChange={(event) => setProbability(Number(event.target.value))} step="0.001" type="range" value={probability} />
            <small>Governed threshold: {Math.round(threshold * 1000) / 10}%</small>
          </label>
        </div>
      ) : null}
      {result ? (
        <ResultCardShell state="success">
          <BinaryClassificationResult presentation={presentation} result={result} />
        </ResultCardShell>
      ) : <ResultCardShell state="unavailable" />}
    </div>
  );
}

// Mirrors the comparison already used for Publishing's own status pill
// (publishingStatusLabel) so Live Preview never invents a second, divergent
// notion of "matches published" -- it just states which side of that same
// comparison the fed draft is currently on.
function livePreviewDraftStateNote(hasPublishedSnapshot: boolean, hasUnpublishedChanges: boolean): string {
  if (!hasPublishedSnapshot) {
    return "Previewing the private draft. No public snapshot has been published yet, so nothing below is live on the public site.";
  }
  if (hasUnpublishedChanges) {
    return "Previewing the private draft, which differs from the currently published public snapshot. Publish changes to make the public site match this preview.";
  }
  return "Previewing the private draft, which matches the currently published public snapshot.";
}

function LivePreviewTab({
  dataset,
  form,
  hasPublishedSnapshot,
  hasUnpublishedChanges,
  readOnlyData,
  selectedSlug,
  customizationEditorState,
  liveInferenceExecutor,
  onLiveInferenceLifecycleEvent,
}: {
  dataset?: DatasetListing;
  form: DraftForm;
  hasPublishedSnapshot: boolean;
  hasUnpublishedChanges: boolean;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  customizationEditorState: CustomizationEditorState;
  liveInferenceExecutor: InferenceExecutor;
  onLiveInferenceLifecycleEvent: (event: InferenceLifecycleEvent) => void;
}) {
  const [previewMode, setPreviewMode] = useState<"detail" | "card">("detail");

  const previewModeLabels: Record<"detail" | "card", string> = {
    detail: "Dataset Detail",
    card: "Home Card",
  };

  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Live Preview</h2>
        <p style={mutedTextStyle}>
          Preview renders the same shared public Home card and Dataset Detail components used on the public site,
          fed by the current draft and the read-only Atlas context already loaded above. Inference form layout
          reuses the real InferenceForm rendering logic in a non-submitting preview mode.
        </p>
        <p role="status" style={mutedTextStyle}>
          <strong>{hasPublishedSnapshot && !hasUnpublishedChanges ? "Draft matches public site: " : "Draft preview: "}</strong>
          {livePreviewDraftStateNote(hasPublishedSnapshot, hasUnpublishedChanges)}
        </p>
      </div>
      <div className="dataset-admin-preview-switcher" role="tablist" aria-label="Live preview modes">
        {(["detail", "card"] as const).map((mode) => (
          <button
            aria-selected={previewMode === mode}
            className={`dataset-admin-preview-tab${previewMode === mode ? " is-active" : ""}`}
            key={mode}
            onClick={() => setPreviewMode(mode)}
            role="tab"
            type="button"
          >
            {previewModeLabels[mode]}
          </button>
        ))}
      </div>
      <div
        className={`dataset-admin-preview-stage${previewMode === "detail" ? " dataset-admin-preview-stage--detail" : ""}`}
      >
        {previewMode === "card" && (
          <article className="dataset-admin-preview-panel dataset-admin-preview-panel--card" aria-label="Home Card preview">
            <DatasetCard
              {...projectHomeCardPreview(
                dataset,
                {
                  ...form,
                  // projectHomeCardPreview's own parameter type still declares
                  // home_card_icon as the legacy closed union (out of this
                  // issue's edit scope), but its body only ever forwards the
                  // value unchanged as HomeCardPreviewProps.iconOverride, whose
                  // type is already the full widened DatasetIconName -- and
                  // DatasetCard now renders any curated value safely (see
                  // DATASET_ICONS's Partial fallback). Casting here preserves
                  // an accurate Home card preview for every curated icon
                  // instead of only the original three.
                  home_card_icon: form.home_card_icon as "" | "telecom" | "bank" | "generic",
                },
                stateValue(readOnlyData.context),
              )}
              mediaRef={form.background_image_ref}
              themePreset={form.theme_preset}
            />
          </article>
        )}
        {previewMode === "detail" && (
          <article
            aria-label="Dataset Detail preview"
            className="dataset-admin-preview-panel dataset-admin-preview-panel--detail"
          >
            {/*
              Project Spec S0145: the shared DatasetDetailSurface renders
              directly inside this panel, which itself sits flush against
              `.dataset-admin-preview-stage`'s inner border via the stage's
              own `--detail` mode (no Admin-only frame/page wrapper, no
              simulated public navigation rail, PublicShell or iframe).
            */}
            <DatasetDetailLivePreview
              customizationEditorState={customizationEditorState}
              dataset={dataset}
              form={form}
              liveInferenceExecutor={liveInferenceExecutor}
              onLiveInferenceLifecycleEvent={onLiveInferenceLifecycleEvent}
              readOnlyData={readOnlyData}
              selectedSlug={selectedSlug}
            />
          </article>
        )}
      </div>
    </>
  );
}

// Project Spec S0196: the Admin Documentation tab's Save/Edit authoring
// workflow. Keeps an editing buffer local to this component, separate from
// the committed `form.documentation` workspace value, so typing alone never
// masquerades as a Save action and never reaches Live Preview or the
// workspace dirty-state until Save commits it. Re-derives its local
// mode/buffer from the committed value whenever the selected dataset or its
// committed documentation changes (dataset switch, or a backend draft
// hydration completing) -- never leaking a prior dataset's unsaved buffer.
function DocumentationTab({
  form,
  setField,
  selectedSlug,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  selectedSlug: string;
}) {
  const [mode, setMode] = useState<"edit" | "preview">(form.documentation.trim() ? "preview" : "edit");
  const [buffer, setBuffer] = useState(form.documentation);

  useEffect(() => {
    setBuffer(form.documentation);
    setMode(form.documentation.trim() ? "preview" : "edit");
  }, [selectedSlug, form.documentation]);

  function handleSave() {
    setField("documentation", buffer);
    setMode(buffer.trim() ? "preview" : "edit");
  }

  function handleEdit() {
    setBuffer(form.documentation);
    setMode("edit");
  }

  return (
    <div className="dataset-admin-tab-workspace dataset-admin-documentation-tab">
      <h2 style={{ marginTop: 0 }}>Documentation</h2>
      <p style={mutedTextStyle}>
        Author Markdown documentation for this Dataset Detail. Save commits it to the workspace draft --
        Publish changes still governs when it becomes public.
      </p>
      {mode === "edit" ? (
        <>
          <textarea
            aria-label="Documentation Markdown"
            className="dataset-admin-documentation-textarea"
            onChange={(event) => setBuffer(event.target.value)}
            rows={16}
            value={buffer}
          />
          <div className="dataset-admin-documentation-actions">
            <button onClick={handleSave} style={actionButtonStyle} type="button">
              Save
            </button>
          </div>
        </>
      ) : (
        <>
          <DatasetDocumentation content={form.documentation} />
          <div className="dataset-admin-documentation-actions">
            <button onClick={handleEdit} style={secondaryButtonStyle} type="button">
              Edit
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function renderSelectedTab(
  selectedTab: string,
  dataset: DatasetListing | undefined,
  form: DraftForm,
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void,
  readOnlyData: ReadOnlyData,
  draftState: DraftState,
  selectedSlug: string,
  customizationEditorState: CustomizationEditorState,
  onRetryCustomization: () => void,
  onToggleVisibility: (visible: boolean) => void,
  onUpdateCustomizationDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void,
  publicationState: PublicationState,
  projectionState: PublicationProjectionState,
  visibilityWriteFailed: boolean,
  onRetryAuthoringContext: () => void,
  onApproveReview: () => void,
  reviewApprovalWriteFailed: boolean,
  liveInferenceAuditRecords: LiveInferenceAuditRecord[],
  liveInferenceExecutor: InferenceExecutor,
  onLiveInferenceLifecycleEvent: (event: InferenceLifecycleEvent) => void,
) {
  // Shared by the Live Preview case below so it can classify its own
  // draft-vs-published state (S0009) using the same comparison Publishing
  // used to derive, instead of a second, divergent notion of "matches
  // published".
  const currentProfile = selectedSlug ? profileFromForm(form, selectedSlug) : null;
  const publishedProfile = publicationState.publishedProfile;
  const hasPublishedSnapshot = Boolean(publishedProfile);
  const hasUnpublishedChanges = Boolean(currentProfile && publishedProfile && !sameProfile(currentProfile, publishedProfile));

  switch (selectedTab) {
    case "metadata-card":
      return <MetadataCardTab form={form} readOnlyData={readOnlyData} selectedSlug={selectedSlug} setField={setField} />;
    case "theme-preset":
      return <ThemePresetTab form={form} setField={setField} />;
    case "inference-form":
      return (
        <InferenceFormTab
          customizationEditorState={customizationEditorState}
          form={form}
          onRetryAuthoringContext={onRetryAuthoringContext}
          onRetryCustomization={onRetryCustomization}
          onUpdateDraft={onUpdateCustomizationDraft}
          readOnlyData={readOnlyData}
          setField={setField}
        />
      );
    case "result-card":
      return <ResultCardTab form={form} readOnlyData={readOnlyData} selectedSlug={selectedSlug} setField={setField} />;
    case "documentation":
      return <DocumentationTab form={form} selectedSlug={selectedSlug} setField={setField} />;
    case "publishing":
      return (
        <PublishingTab
          hasUnpublishedChanges={hasUnpublishedChanges}
          liveInferenceAuditRecords={liveInferenceAuditRecords}
          onApproveReview={onApproveReview}
          onToggleVisibility={onToggleVisibility}
          projectionState={projectionState}
          reviewApprovalWriteFailed={reviewApprovalWriteFailed}
          selectedSlug={selectedSlug}
          visibilityWriteFailed={visibilityWriteFailed}
        />
      );
    case "live-preview":
      return (
        <LivePreviewTab
          customizationEditorState={customizationEditorState}
          dataset={dataset}
          form={form}
          hasPublishedSnapshot={hasPublishedSnapshot}
          hasUnpublishedChanges={hasUnpublishedChanges}
          liveInferenceExecutor={liveInferenceExecutor}
          onLiveInferenceLifecycleEvent={onLiveInferenceLifecycleEvent}
          readOnlyData={readOnlyData}
          selectedSlug={selectedSlug}
        />
      );
    case "public-content":
    default:
      return <PublicContentTab form={form} setField={setField} />;
  }
}

export default function DatasetAdminPage() {
  const [state, setState] = useState<DatasetState>({ status: "loading" });
  const [adminDatasetsState, setAdminDatasetsState] = useState<AdminDatasetState>({ status: "loading" });
  const [selectedSlug, setSelectedSlug] = useState("");
  const [datasetQuery, setDatasetQuery] = useState("");
  const [selectedTab, setSelectedTab] = useState(adminTabs[0].id);
  const [draftState, setDraftState] = useState<DraftState>({
    status: "idle",
    message: "Select a Dataset Detail to load its content for editing.",
  });
  const [draftForm, setDraftForm] = useState<DraftForm>(emptyDraftForm());
  const [readOnlyData, setReadOnlyData] = useState<ReadOnlyData>(emptyReadOnlyData);
  const [customizationEditorState, setCustomizationEditorState] = useState<CustomizationEditorState>(
    emptyCustomizationEditorState,
  );
  // Project Spec S0103: the normalized customization baseline the workspace
  // dirty-state compares the current builder draft against. null means no
  // baseline has been established yet for the current dataset/view/contract
  // identity (see isCustomizationRecordDirty).
  const [customizationBaseline, setCustomizationBaseline] = useState<string | null>(null);
  // Project Spec S0110: true when the currently loaded/rendered customization
  // draft's submit_button_label was seeded from the legacy published profile
  // value rather than an already-persisted customization value. This is
  // deliberately tracked separately from the normal dirty-state baseline
  // above (the baseline is computed from the migrated draft too, so loading
  // a legacy-only dataset never spuriously enables Publish changes by
  // itself) -- publishChanges below still forces a customization persist
  // ahead of profile publication whenever this is true and a profile
  // publish is about to happen, satisfying "persist customization first"
  // even when the operator only changed an unrelated profile field.
  const [submitLabelMigrationPending, setSubmitLabelMigrationPending] = useState(false);
  const [publicationState, setPublicationState] = useState<PublicationState>(emptyPublicationState);
  // Project Spec S0103: the shared toolbar message area's own feedback for
  // the combined customization+profile Publish changes orchestration --
  // distinct from PublicationState, which only ever describes the profile
  // publish/visibility boundary and is left otherwise untouched so the
  // Publishing tab's existing status text keeps working unchanged.
  const [workspacePublishFeedback, setWorkspacePublishFeedback] = useState<
    { tone: "success" | "error"; text: string } | null
  >(null);
  const [refreshRevision, setRefreshRevision] = useState(0);
  // Project Spec S0116: the sole authority for the Publishing tab's switch,
  // the header Public/Private badge, the "Open public Dataset Detail page"
  // action, and the operational console -- hydrated from GET
  // /admin/datasets/{slug}/publication-state, never reconstructed from
  // PublicationState or the public dataset listing.
  const [publicationProjection, setPublicationProjection] = useState<PublicationProjectionState>(
    emptyPublicationProjectionState,
  );
  // Set only by a failed visibility PUT and cleared by the next dataset
  // switch or the next toggle attempt -- drives the console's transient
  // "[ERROR] Configured visibility could not be saved..." line without
  // needing a raw error message from the backend.
  const [visibilityWriteFailed, setVisibilityWriteFailed] = useState(false);
  // Project Spec S0125: mirrors visibilityWriteFailed for the review-
  // approval write -- set only by a failed approval PUT and cleared by the
  // next dataset switch or the next approval attempt.
  const [reviewApprovalWriteFailed, setReviewApprovalWriteFailed] = useState(false);
  // Project Spec S0144: the Publishing console's Live Preview inference
  // session audit history, owned here alongside publicationProjection and
  // the transient write-failure state above -- never by a child tab, a
  // module-global store, or browser storage. Scoped to selectedSlug and
  // reset at the exact same points visibilityWriteFailed/
  // reviewApprovalWriteFailed already reset below, so a top-level Admin tab
  // switch never clears it but a dataset switch always does.
  const [liveInferenceAudit, setLiveInferenceAudit] = useState<LiveInferenceAuditState>(() =>
    emptyLiveInferenceAuditState(""),
  );
  // Bridges executeAdminInference's validated success result to the
  // subsequent onLifecycleEvent("succeeded") callback InferenceForm invokes
  // immediately afterward -- InferenceForm's own lifecycle event carries no
  // result data by design (Project Spec S0143), so this is the only bounded
  // channel the safe result summary travels through. Never holds a raw
  // payload, raw response, or exception.
  const pendingLiveInferenceSuccessSummaryRef = useRef<LiveInferenceAuditSuccessSummary | null>(null);
  // Guards a superseded publication-state response from ever applying itself
  // (mirrors customizationRequestRef below): AbortController alone is not
  // sufficient because this repo's test fetch mocks do not honor
  // AbortSignal.
  const publicationProjectionRequestRef = useRef(0);
  const loadedDatasetSlugRef = useRef("");
  // Project Spec S0121: own request-id/background-refresh tracking for the
  // dedicated authoring-context effect below, kept separate from
  // loadedDatasetSlugRef (owned by the profile-draft/publication-projection
  // effect) so bumping authoringContextRetryNonce re-requests only the
  // authoring context, never those other reads.
  const authoringContextRequestRef = useRef(0);
  const authoringContextLoadedSlugRef = useRef("");
  const [authoringContextRetryNonce, setAuthoringContextRetryNonce] = useState(0);
  const canonicalDateBySlugRef = useRef<Record<string, string>>({});
  // Project Spec S0098: tracks which selectedSlug the deterministic
  // predict-view rebind default has already been applied for, so it runs
  // exactly once per dataset selection rather than fighting a later manual
  // unbind/rebind edit on every background refresh.
  const predictViewRebindAppliedSlugRef = useRef<string | null>(null);
  const draftFormRef = useRef(draftForm);
  const draftStateRef = useRef(draftState);
  // Project Spec S0116: read by setConfiguredVisibility's async callbacks to
  // detect a dataset switch that raced an in-flight visibility PUT.
  const selectedSlugRef = useRef(selectedSlug);
  draftFormRef.current = draftForm;
  draftStateRef.current = draftState;
  selectedSlugRef.current = selectedSlug;

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          setState({ status: "error", message: "Dataset listing unavailable." });
          return null;
        }

        return res.json() as Promise<DatasetListingResponse>;
      })
      .then((data) => {
        if (!data) {
          return;
        }

        if (!Array.isArray(data.datasets)) {
          setState({ status: "error", message: "Dataset listing returned an unexpected shape." });
          return;
        }

        setState({ status: "ready", datasets: data.datasets });
        setSelectedSlug((current) => current || data.datasets[0]?.dataset_slug || "");
        setDatasetQuery(getDatasetSelectorValue(data.datasets[0]));
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error", message: "Dataset listing could not be loaded." });
        }
      });

    return () => controller.abort();
  }, [refreshRevision]);

  // GET /admin/datasets (registry/list.py's list_admin_datasets, Project Spec
  // S0052): every registry-backed Dataset Detail Admin can see, including
  // drafts never publicly listed above. Powers the header Dataset Detail
  // selector so an operator can pick any registry-backed dataset, not only
  // ones already public; kept independent from the public listing effect
  // above so the rest of the page's data-loading (Live Preview projection,
  // Public Content tab) keeps relying on the real public DatasetListing shape
  // unchanged.
  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/admin/datasets`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          setAdminDatasetsState({ status: "error", message: "Admin dataset listing unavailable." });
          return null;
        }

        return res.json() as Promise<AdminDatasetListingResponse>;
      })
      .then((data) => {
        if (!data) {
          return;
        }

        if (!Array.isArray(data.datasets)) {
          setAdminDatasetsState({ status: "error", message: "Admin dataset listing returned an unexpected shape." });
          return;
        }

        canonicalDateBySlugRef.current = Object.fromEntries(
          data.datasets.map((dataset) => [dataset.dataset_slug, dateFromLastUpdated(dataset.last_updated)]),
        );
        setAdminDatasetsState({ status: "ready", datasets: data.datasets });
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setAdminDatasetsState({ status: "error", message: "Admin dataset listing could not be loaded." });
        }
      });

    return () => controller.abort();
  }, [refreshRevision]);

  useEffect(() => {
    if (!selectedSlug) {
      setDraftForm(emptyDraftForm());
      setCustomizationEditorState(emptyCustomizationEditorState);
      setCustomizationBaseline(null);
      setPublicationState(emptyPublicationState);
      setWorkspacePublishFeedback(null);
      // Project Spec S0116: no request is issued and no prior dataset's
      // projection can leak through when nothing is selected.
      publicationProjectionRequestRef.current += 1;
      setPublicationProjection(emptyPublicationProjectionState);
      setVisibilityWriteFailed(false);
      setReviewApprovalWriteFailed(false);
      // Project Spec S0144: transitioning to no selected dataset clears the
      // inference audit history the same way it clears every other
      // per-dataset console state above.
      setLiveInferenceAudit(emptyLiveInferenceAuditState(""));
      return;
    }

    const isBackgroundRefresh = loadedDatasetSlugRef.current === selectedSlug;
    if (!isBackgroundRefresh) {
      setDraftForm((current) => ({ ...emptyDraftForm(selectedSlug), schema_version: current.schema_version || "1.0.0" }));
      setDraftState({ status: "loading" });
      setCustomizationEditorState(emptyCustomizationEditorState);
      setCustomizationBaseline(null);
      setPublicationState(emptyPublicationState);
      setWorkspacePublishFeedback(null);
      // Project Spec S0116: a dataset switch must never retain the previous
      // dataset's publication projection, even for one frame -- reset
      // synchronously here (same pattern as the sibling resets above) rather
      // than waiting on the async fetch below to overwrite it.
      setPublicationProjection({ status: "loading", datasetSlug: selectedSlug });
      setVisibilityWriteFailed(false);
      setReviewApprovalWriteFailed(false);
      // Project Spec S0144: a real dataset switch clears all inference audit
      // records, resets the attempt sequence, and clears active attempt
      // correlation -- never retained across a changed selection, and never
      // cleared merely by isBackgroundRefresh re-running this effect for the
      // same dataset.
      setLiveInferenceAudit(emptyLiveInferenceAuditState(selectedSlug));
      // Project Spec S0098: the deterministic predict-view rebind default
      // below applies at most once per dataset selection; switching to a
      // different (or reselecting the same) Dataset Detail must be able to
      // re-evaluate it.
      predictViewRebindAppliedSlugRef.current = null;
    }
    loadedDatasetSlugRef.current = selectedSlug;

    const controller = new AbortController();

    // Automatically load the private/admin profile draft for the selected
    // Dataset Detail (Project Spec S0058 removes the manual "Load draft"
    // action) so the workspace toolbar's Publish changes dirty-state
    // comparison always has a real snapshot -- the existing backend draft if
    // one exists, or (via the canonicalDisplayTitle seed effect below, once
    // draftState resolves with draftExists: false) the established S0056
    // blank-form-with-seeded-title baseline otherwise.
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/profile-draft`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (response.status === 404) {
          setDraftState({
            status: "unavailable",
            message: "Content is unavailable for this admin session. Confirm API configuration.",
          });
          return null;
        }
        if (!response.ok) {
          setDraftState({ status: "unavailable", message: "Content could not be loaded from the admin API." });
          return null;
        }
        return response.json() as Promise<{
          draft_exists: boolean;
          profile: ProfileDraft | null;
          published_snapshot?: PublishSnapshot | null;
          profile_hydration?: ProfileHydration;
        }>;
      })
      .then((data) => {
        if (!data) {
          return;
        }
        const canonicalDate = canonicalDateBySlugRef.current[selectedSlug] ?? "";
        const publishedProfile = profileWithCanonicalReleaseDate(
          profileFromSnapshot(data.published_snapshot, selectedSlug),
          canonicalDate,
        );
        // S0084 responses explicitly bind hydration to the live release. A
        // fresh baseline must not fall back to a same-slug private draft,
        // which may also be residue from an older Dataset Detail lifecycle.
        // The legacy fallback remains only for older backend responses that
        // do not yet expose profile_hydration.
        const hydrationProfile = profileWithCanonicalReleaseDate(data.profile_hydration
          ? data.profile_hydration.source === "current_release_snapshot"
            ? publishedProfile
            : null
          : publishedProfile ?? data.profile, canonicalDate);
        const previousProfile = backendDraftProfile(draftStateRef.current);
        const currentProfile = profileFromForm(draftFormRef.current, selectedSlug);
        const hasDirtyFields = Boolean(previousProfile && !sameProfile(currentProfile, previousProfile));
        if (!isBackgroundRefresh || !hasDirtyFields) {
          setDraftForm(formFromProfile(hydrationProfile, selectedSlug));
        }
        setDraftState({ status: "ready", draftExists: data.draft_exists, profile: hydrationProfile });
        if (publishedProfile) {
          setPublicationState(() => ({
            status: "idle",
            publishedProfile,
            message: "Latest published snapshot loaded.",
          }));
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setDraftState({ status: "unavailable", message: "Content could not be loaded. Check API reachability." });
        }
      });

    // Project Spec S0116: the sole authority for the switch/badge/console --
    // re-fetched on dataset switch and on every refreshRevision bump
    // (already the established signal for "a successful profile publish
    // happened," e.g. performPublish below), on top of the dedicated
    // re-fetch performPublicVisibilityWrite triggers directly after a
    // successful visibility PUT.
    loadPublicationProjection(selectedSlug, controller.signal);

    return () => controller.abort();
  }, [selectedSlug, refreshRevision]);

  // Project Spec S0121: GET /admin/datasets/{slug}/authoring-context is now
  // the sole technical read-model source for Dataset Admin authoring,
  // replacing the six separate public-technical-read fetches
  // (/datasets/{slug}, .../context, .../contract, .../metrics,
  // .../visualizations, .../views) the sibling effect above used to issue --
  // none of those public routes may be requested for ReadOnlyData anymore.
  // Kept as its own effect (own AbortController, request-id ref, and retry
  // nonce) so retryAuthoringContext below re-requests only this endpoint,
  // never the profile-draft/publication-projection reads the sibling effect
  // still owns. requestId guards a late response from a superseded
  // slug/retry identity (mirrors customizationRequestRef's established
  // pattern) since this repo's test fetch mocks do not honor AbortSignal.
  useEffect(() => {
    if (!selectedSlug) {
      authoringContextLoadedSlugRef.current = "";
      setReadOnlyData(emptyReadOnlyData);
      return;
    }

    const requestId = authoringContextRequestRef.current + 1;
    authoringContextRequestRef.current = requestId;

    const isBackgroundRefresh = authoringContextLoadedSlugRef.current === selectedSlug;
    authoringContextLoadedSlugRef.current = selectedSlug;

    const controller = new AbortController();
    if (!isBackgroundRefresh) {
      setReadOnlyData({
        dataset: { status: "loading" },
        context: { status: "loading" },
        contract: { status: "loading" },
        inferenceGuidance: { status: "loading" },
        resultContract: { status: "loading" },
        metrics: { status: "loading" },
        visualizations: { status: "loading" },
        views: { status: "loading" },
      });
    }

    async function loadAuthoringContext() {
      const encoded = encodeURIComponent(selectedSlug);
      const authoring = await fetchJson<AuthoringContextEnvelope>(
        `/admin/datasets/${encoded}/authoring-context`,
        controller.signal,
      );
      if (authoringContextRequestRef.current !== requestId) {
        return;
      }

      if (authoring.status !== "ready") {
        const message = "message" in authoring ? authoring.message : "The authoring context could not be loaded.";
        setReadOnlyData({
          dataset: { status: "unavailable", message },
          context: { status: "unavailable", message },
          contract: { status: "unavailable", message },
          inferenceGuidance: { status: "unavailable", message },
          resultContract: { status: "transport_failure", message },
          metrics: { status: "unavailable", message },
          visualizations: { status: "unavailable", message },
          views: { status: "unavailable", message },
        });
        return;
      }

      const envelope = authoring.data;
      const contractResource = authoringResourceState<ContractEnvelope>(envelope.contract);
      const resultContract: ResultContractState = contractResource.status === "ready"
        ? classifyResultContract(contractResource.data)
        : {
            status: "transport_failure",
            message: "message" in contractResource ? contractResource.message : "Result contract request did not complete.",
          };

      setReadOnlyData({
        dataset: authoringResourceState<AuthoringDatasetProjection>(envelope.dataset),
        context: authoringResourceState<ContextPayload>(envelope.context),
        contract: mapSection(contractResource, (data) => data.contract),
        inferenceGuidance: authoringResourceState<unknown>(envelope.inference_guidance),
        resultContract,
        metrics: authoringResourceState<MetricsPayload>(envelope.metrics),
        visualizations: authoringResourceState<unknown>(envelope.visualizations),
        views: authoringResourceState<PredictView[]>(envelope.views),
      });
    }

    void loadAuthoringContext();

    return () => controller.abort();
  }, [selectedSlug, refreshRevision, authoringContextRetryNonce]);

  // Project Spec S0098: deterministic Dataset Admin authoring rebinding.
  // Runs only after hydration has resolved bound_predict_view_id from the
  // real profile (draftState.status === "ready", set by the effect above)
  // and the dataset-owned eligible views list has arrived
  // (readOnlyData.views.status === "ready"), so this never races or
  // overwrites the profile-driven setDraftForm(formFromProfile(...)) call.
  // Eligible views come only from this dataset's own GET /datasets/{slug}/views
  // response, so a view belonging to another dataset is never selectable
  // here. Applies at most once per dataset selection (see
  // predictViewRebindAppliedSlugRef, reset on dataset switch above) so it
  // never re-fights a later manual unbind/rebind edit on a background
  // refresh. This only ever adjusts bound_predict_view_id in the editable
  // draft form state -- it never calls the API and never touches the
  // published snapshot, so it participates in the existing dirty-state and
  // Publish changes flow exactly like any other manual field edit.
  useEffect(() => {
    if (!selectedSlug || draftState.status !== "ready") {
      return;
    }
    if (readOnlyData.views.status !== "ready") {
      return;
    }
    if (predictViewRebindAppliedSlugRef.current === selectedSlug) {
      return;
    }
    predictViewRebindAppliedSlugRef.current = selectedSlug;

    const eligibleViewIds = (stateValue(readOnlyData.views) ?? [])
      .map((view) => view.view_id)
      .filter((viewId): viewId is string => Boolean(viewId));

    setDraftForm((current) => {
      if (current.bound_predict_view_id && eligibleViewIds.includes(current.bound_predict_view_id)) {
        return current;
      }
      const nextBinding = eligibleViewIds.length === 1 ? eligibleViewIds[0] : "";
      if (current.bound_predict_view_id === nextBinding) {
        return current;
      }
      return { ...current, bound_predict_view_id: nextBinding };
    });
  }, [selectedSlug, draftState.status, readOnlyData.views]);

  const datasets = state.status === "ready" ? state.datasets : [];
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.dataset_slug === selectedSlug),
    [datasets, selectedSlug],
  );
  const adminDatasets = adminDatasetsState.status === "ready" ? adminDatasetsState.datasets : [];
  const selectedAdminDataset = useMemo(
    () => adminDatasets.find((dataset) => dataset.dataset_slug === selectedSlug),
    [adminDatasets, selectedSlug],
  );
  // Project Spec S0116: the header badge reads the S0115-projected
  // reachability authority -- public_access.reachable -- never the public
  // dataset listing. Project Spec S0123: the "Open public Dataset Detail
  // page" action reads the same projection's configured-visibility
  // authority instead (publicPageActionAvailable), so the two can disagree
  // by design (e.g. a review-blocked-but-configured-visible dataset shows
  // "Private" while the action stays enabled).
  const registryVisibilityLabel = publicationBadgeLabel(publicationProjection);
  const selectedDatasetIsPublic = registryVisibilityLabel === "Public";
  const publicPageActionEnabled = publicPageActionAvailable(publicationProjection);
  const lastBackendDraft = backendDraftProfile(draftState);
  const hasBackendDraftProfile = Boolean(lastBackendDraft);
  // Dataset Detail display title shown in Admin/Dashboard (registry/list.py's
  // AdminListedDataset, falling back to the registry/public title if the
  // display-title projection is not available) -- Project Spec S0056 requires
  // seeding Display title from this value while the Public Content tab is
  // still in its blank authoring state (no real backend draft profile
  // tracked yet), without auto-filling any other public-content field.
  const canonicalDisplayTitle = selectedAdminDataset?.display_title?.trim() || selectedAdminDataset?.title || selectedDataset?.title || "";
  const lastUpdatedDate = dateFromLastUpdated(selectedAdminDataset?.last_updated);
  useEffect(() => {
    if (!selectedSlug || !canonicalDisplayTitle || hasBackendDraftProfile) {
      return;
    }
    setDraftForm((current) => (current.display_title ? current : { ...current, display_title: canonicalDisplayTitle }));
  }, [selectedSlug, canonicalDisplayTitle, hasBackendDraftProfile, draftState.status]);
  useEffect(() => {
    if (!selectedSlug || !lastUpdatedDate || draftState.status === "loading") {
      return;
    }
    setDraftForm((current) => {
      if (current.release_date_label === lastUpdatedDate) {
        return current;
      }
      return { ...current, release_date_label: lastUpdatedDate };
    });
  }, [selectedSlug, lastUpdatedDate, draftState.status]);
  // Project Spec S0103: bound_predict_view_id now participates in
  // workspacePublishFields (see the type above), so this baseline must also
  // reflect the same deterministic single-eligible-view default the S0098
  // rebind effect below applies to draftForm -- otherwise that automatic
  // default (not a real operator edit) would immediately, falsely enable
  // Publish changes the instant the eligible views list resolves.
  const eligibleBoundPredictViewIds = (stateValue(readOnlyData.views) ?? [])
    .map((view) => view.view_id)
    .filter((viewId): viewId is string => Boolean(viewId));
  function resolvedBoundPredictViewIdDefault(rawBoundPredictViewId: string): string {
    if (rawBoundPredictViewId && eligibleBoundPredictViewIds.includes(rawBoundPredictViewId)) {
      return rawBoundPredictViewId;
    }
    return eligibleBoundPredictViewIds.length === 1 ? eligibleBoundPredictViewIds[0] : "";
  }
  // The workspace toolbar's Publish changes snapshot (Project Spec S0058):
  // the normalized current saved/published form state for the selected
  // Dataset Detail's workspace-publishable fields, or -- when no backend draft/
  // profile exists yet -- the same blank-form-with-seeded-title baseline the
  // canonicalDisplayTitle effect above establishes. The Publishing tab keeps
  // using the whole-profile comparison above for its own lifecycle.
  const workspacePublishSnapshotForm: DraftForm =
    hasBackendDraftProfile && lastBackendDraft
      ? {
          ...formFromProfile(lastBackendDraft, selectedSlug),
          release_date_label: lastUpdatedDate,
          bound_predict_view_id: resolvedBoundPredictViewIdDefault(
            formFromProfile(lastBackendDraft, selectedSlug).bound_predict_view_id,
          ),
        }
      : {
          ...emptyDraftForm(selectedSlug),
          display_title: canonicalDisplayTitle,
          release_date_label: lastUpdatedDate,
          bound_predict_view_id: resolvedBoundPredictViewIdDefault(""),
        };
  const hasUnpublishedWorkspaceChanges =
    Boolean(selectedSlug) && !sameWorkspacePublishFields(draftForm, workspacePublishSnapshotForm);
  // Project Spec S0103: the Inference Form customization now participates in
  // the same shared workspace dirty-state as every other Dataset Detail tab.
  const hasUnpublishedCustomizationChanges = isCustomizationRecordDirty(customizationEditorState, customizationBaseline);
  const toolbarPublishBusy =
    draftState.status === "loading" ||
    publicationState.status === "publishing" ||
    customizationEditorState.status === "saving";
  const toolbarPublishDisabled =
    !selectedSlug || (!hasUnpublishedWorkspaceChanges && !hasUnpublishedCustomizationChanges) || toolbarPublishBusy;
  // Progress/result feedback beside the shared Publish changes button:
  // "Saving changes..." always wins while busy; otherwise the S0103
  // orchestrator's own workspacePublishFeedback (covering customization-only
  // and combined customization+profile outcomes) takes precedence over the
  // pre-existing profile-only publish/visibility feedback derived from
  // publicationState, which is left completely unchanged for the
  // profile-only path.
  const toolbarPublishProgress = toolbarPublishBusy ? "Saving changes..." : null;
  const toolbarPublishError = toolbarPublishProgress
    ? null
    : workspacePublishFeedback?.tone === "error"
    ? workspacePublishFeedback.text
    : draftState.status === "invalid"
    ? "Public Content changes could not be saved. Open the Publishing tab for details."
    : publicationState.status === "invalid"
    ? "Public Content changes could not be published. Open the Publishing tab for details."
    : publicationState.status === "unavailable"
    ? publicationState.message
    : null;
  const toolbarPublishFeedback = toolbarPublishProgress
    ? null
    : workspacePublishFeedback?.tone === "success"
    ? workspacePublishFeedback.text
    : toolbarPublicationFeedback(publicationState);

  function selectDatasetFromQuery(value: string) {
    setDatasetQuery(value);
    const match = adminDatasets.find(
      (dataset) => dataset.dataset_slug === value || getDatasetSelectorValue(dataset).toLowerCase() === value.trim().toLowerCase(),
    );
    if (match && match.dataset_slug !== selectedSlug) {
      setSelectedSlug(match.dataset_slug);
    }
  }

  function normalizeDatasetQuery() {
    setDatasetQuery(getDatasetSelectorValue(selectedAdminDataset));
  }

  function setField<K extends keyof DraftForm>(key: K, value: DraftForm[K]) {
    setDraftForm((current) => ({ ...current, [key]: value }));
  }

  const boundPredictViewId = draftForm.bound_predict_view_id;

  // Project Spec S0061: Publish changes sends the current form payload
  // directly to the direct publish boundary -- no persisted profile-draft is
  // read or required by the backend along this path. Shared by publishChanges
  // (Publishing tab) and the workspace toolbar's own Publish changes button,
  // both of which call this with profileFromForm(draftForm, selectedSlug)
  // and nothing else. Project Spec S0103: an optional callbacks argument lets
  // the shared orchestrator below layer its own combined-outcome toolbar
  // feedback on top, without changing any existing publicationState
  // transition this function already performs for the profile-only path.
  function performPublish(profileToPublish: ProfileDraft, callbacks?: { onSuccess?: () => void; onFailure?: () => void }) {
    setPublicationState((current) => ({
      status: "publishing",
      publishedProfile: current.publishedProfile,
    }));
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/publish`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...profileToPublish,
        dataset_detail_time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    })
      .then((response) => {
        if (response.status === 404) {
          setPublicationState((current) => ({
            status: "unavailable",
            publishedProfile: current.publishedProfile,
            message: "Publish endpoint unavailable for this private admin session. Confirm API configuration.",
          }));
          callbacks?.onFailure?.();
          return null;
        }
        return response.json().then((body: { published?: boolean; display_title?: string | null; snapshot?: PublishSnapshot | null; errors?: DraftError[] }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (!result) {
          return;
        }
        if (!result.ok || !result.body.published) {
          setPublicationState((current) => ({
            status: "invalid",
            publishedProfile: current.publishedProfile,
            errors: result.body.errors ?? [{ message: "Profile publish failed validation." }],
          }));
          callbacks?.onFailure?.();
          return;
        }
        const publishedProfile = profileFromSnapshot(result.body.snapshot, selectedSlug) ?? profileToPublish;
        // A successful publish also becomes the new local dirty-state
        // baseline (Project Spec S0061 acceptance criteria), reusing the
        // same draftState/lastBackendDraft plumbing the workspace toolbar's
        // own Public-Content-scoped comparison already keys off, so Publish
        // changes disables again immediately until the form changes further
        // -- without requiring an explicit Save draft call.
        setDraftForm(formFromProfile(publishedProfile, selectedSlug));
        setDraftState({ status: "saved", profile: publishedProfile });
        setPublicationState(() => ({
          status: "published",
          publishedProfile,
          publishedAt: result.body.snapshot?.published_at,
        }));
        const nextDisplayTitle = result.body.display_title?.trim() || publishedProfile.display?.title?.trim() || "";
        if (nextDisplayTitle) {
          setAdminDatasetsState((current) =>
            current.status === "ready"
              ? {
                  ...current,
                  datasets: current.datasets.map((dataset) =>
                    dataset.dataset_slug === selectedSlug ? { ...dataset, display_title: nextDisplayTitle } : dataset,
                  ),
                }
              : current,
          );
          setDatasetQuery((current) => (current === getDatasetSelectorValue(selectedAdminDataset) ? nextDisplayTitle : current));
        }
        // Project Spec S0116: a successful content publish can change
        // review/snapshot/reachability, so the publication-state projection
        // (badge/console/switch authority) is reconciled too -- refreshRevision
        // already re-triggers the dataset-switch effect's loadPublicationProjection
        // call for the current selectedSlug.
        setRefreshRevision((current) => current + 1);
        callbacks?.onSuccess?.();
      })
      .catch(() => {
        setPublicationState((current) => ({
          status: "unavailable",
          publishedProfile: current.publishedProfile,
          message: "Profile could not be published. Check private admin API reachability.",
        }));
        callbacks?.onFailure?.();
      });
  }

  // Used by the workspace toolbar's Publish changes button (Project Spec
  // S0061/S0103; the Publishing tab's own former Publish changes button was
  // removed by Project Spec S0116): determines which of the two resources
  // (Inference Form customization, Dataset Detail profile) are actually
  // dirty and orchestrates them -- customization always precedes profile
  // publication so a known-invalid form layout can never be accompanied by a
  // newly published profile in the same action, only dirty resources are
  // mutated, and a resource's baseline only updates once its own operation
  // actually succeeds. profileDirty is the toolbar's own
  // hasUnpublishedWorkspaceChanges (differs from the last loaded draft).
  function publishChanges(profileDirty: boolean) {
    if (!selectedSlug) {
      return;
    }

    const customizationDraft = customizationDraftOf(customizationEditorState);
    const customizationDirty = isCustomizationRecordDirty(customizationEditorState, customizationBaseline);
    // Project Spec S0110: a pending legacy submit-label migration forces the
    // same "customization persists before profile" ordering as an explicit
    // customization edit whenever a profile publish is about to happen --
    // otherwise the about-to-be-dropped legacy value would be lost with
    // nowhere it was ever actually persisted to.
    const migrationMustPersistFirst = submitLabelMigrationPending && profileDirty && !customizationDirty;
    const currentProfileForPublish = profileFromForm(draftForm, selectedSlug);

    if (!customizationDirty && !migrationMustPersistFirst && !profileDirty) {
      return;
    }

    if ((customizationDirty || migrationMustPersistFirst) && customizationDraft) {
      const validationErrors = requiredFieldHiddenErrors(customizationDraft);
      if (validationErrors.length > 0) {
        // Local validation failure: neither request is sent, the resource
        // stays dirty, and Publish changes remains enabled.
        setCustomizationEditorState({ status: "invalid", draft: customizationDraft, errors: validationErrors });
        setWorkspacePublishFeedback({ tone: "error", text: validationErrors[0].message ?? "Inference Form could not be saved." });
        return;
      }

      setWorkspacePublishFeedback(null);
      persistCustomizationDraft(customizationDraft).then((customizationSaved) => {
        if (!customizationSaved) {
          // Customization request failed: profile publication is not
          // attempted, the customization baseline is left unchanged, and
          // Publish changes remains enabled.
          setWorkspacePublishFeedback({ tone: "error", text: "Inference Form could not be saved." });
          return;
        }
        if (!profileDirty) {
          setWorkspacePublishFeedback({ tone: "success", text: "Changes saved." });
          return;
        }
        performPublish(currentProfileForPublish, {
          onSuccess: () => setWorkspacePublishFeedback({ tone: "success", text: "Changes saved." }),
          onFailure: () =>
            setWorkspacePublishFeedback({
              tone: "error",
              text: "Inference Form saved; Dataset Detail publication failed.",
            }),
        });
      });
      return;
    }

    // Only the Dataset Detail profile is dirty: existing profile publication
    // flow, unchanged from Project Spec S0061.
    setWorkspacePublishFeedback(null);
    performPublish(currentProfileForPublish);
  }

  // Project Spec S0116: the sole loader for GET
  // /admin/datasets/{slug}/publication-state. Guarded by
  // publicationProjectionRequestRef (incremented on every call) rather than
  // relying solely on AbortSignal, since this repo's test fetch mocks do not
  // honor abort -- a response is only ever applied when it is still the most
  // recent request AND its own dataset_slug matches what was asked for.
  function loadPublicationProjection(slug: string, signal?: AbortSignal) {
    const requestId = publicationProjectionRequestRef.current + 1;
    publicationProjectionRequestRef.current = requestId;

    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(slug)}/publication-state`, signal ? { signal } : undefined)
      .then((response): Promise<{ ok: boolean; body: unknown }> => {
        if (response.status === 404) {
          return Promise.resolve({ ok: false, body: null });
        }
        return response.json().then((body: unknown) => ({ ok: response.ok, body }));
      })
      .then((result) => {
        if (publicationProjectionRequestRef.current !== requestId) {
          return;
        }
        if (!result.ok) {
          setPublicationProjection({
            status: "unavailable",
            datasetSlug: slug,
            message: "Publication state could not be loaded from the private Admin API.",
          });
          return;
        }
        const projection = parseAdminPublicationStateProjection(result.body);
        if (!projection || projection.dataset_slug !== slug) {
          setPublicationProjection({
            status: "unavailable",
            datasetSlug: slug,
            message: "Publication state response was not in the expected shape.",
          });
          return;
        }
        setPublicationProjection({ status: "ready", datasetSlug: slug, projection });
      })
      .catch((err: Error) => {
        if (err.name === "AbortError" || publicationProjectionRequestRef.current !== requestId) {
          return;
        }
        setPublicationProjection({
          status: "unavailable",
          datasetSlug: slug,
          message: "Publication state could not be loaded. Check private admin API reachability.",
        });
      });
  }

  // Project Spec S0116: the switch's only write path -- unchanged PUT
  // route/payload. Only usable from the "ready" projection state (the switch
  // itself is disabled otherwise), so a prior authoritative projection is
  // always available to roll back to on failure. selectedSlugRef guards
  // against a dataset switch racing an in-flight write: neither the success
  // nor the failure branch may touch state once the operator has moved on to
  // a different dataset -- that dataset's own effect-driven fetch already
  // owns its state by then.
  function setConfiguredVisibility(visible: boolean) {
    if (publicationProjection.status !== "ready") {
      return;
    }
    const slug = publicationProjection.datasetSlug;
    const priorProjection = publicationProjection.projection;

    setVisibilityWriteFailed(false);
    setPublicationProjection({ status: "saving", datasetSlug: slug, projection: priorProjection, pendingVisible: visible });

    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(slug)}/visibility`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible }),
    })
      .then((response): Promise<{ ok: boolean; body: { visible?: boolean; error_code?: string; message?: string; errors?: DraftError[] } | null }> => {
        if (response.status === 404) {
          return Promise.resolve({ ok: false, body: null });
        }
        return response.json().then((body: { visible?: boolean; error_code?: string; message?: string; errors?: DraftError[] }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (selectedSlugRef.current !== slug) {
          return;
        }
        if (!result.ok || typeof result.body?.visible !== "boolean") {
          setVisibilityWriteFailed(true);
          setPublicationProjection({ status: "ready", datasetSlug: slug, projection: priorProjection });
          return;
        }
        // Authoritative reconciliation: re-fetch rather than trust the PUT's
        // own echoed value, so configured/effective/reachable and every
        // console fact stay consistent with the read projection.
        loadPublicationProjection(slug);
      })
      .catch(() => {
        if (selectedSlugRef.current !== slug) {
          return;
        }
        setVisibilityWriteFailed(true);
        setPublicationProjection({ status: "ready", datasetSlug: slug, projection: priorProjection });
      });
  }

  // Project Spec S0125: the review-approval action's sole write path.
  // Mirrors setConfiguredVisibility's guard/race-protection shape exactly
  // (only usable from "ready", selectedSlugRef-guarded against a dataset
  // switch racing an in-flight write) but PUTs review-status instead of
  // visibility, and never sends a profile body, visibility mutation, or
  // public-route override.
  function approveDatasetReview() {
    if (publicationProjection.status !== "ready") {
      return;
    }
    const slug = publicationProjection.datasetSlug;
    const priorProjection = publicationProjection.projection;

    setReviewApprovalWriteFailed(false);
    setPublicationProjection({ status: "approving", datasetSlug: slug, projection: priorProjection });

    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(slug)}/review-status`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "ready" }),
    })
      .then((response): Promise<{ ok: boolean; body: { review_status?: string; error_code?: string } | null }> => {
        if (response.status === 404) {
          return Promise.resolve({ ok: false, body: null });
        }
        return response.json().then((body: { review_status?: string; error_code?: string }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (selectedSlugRef.current !== slug) {
          return;
        }
        if (!result.ok || typeof result.body?.review_status !== "string") {
          setReviewApprovalWriteFailed(true);
          setPublicationProjection({ status: "ready", datasetSlug: slug, projection: priorProjection });
          return;
        }
        // Authoritative reconciliation: re-fetch the publication-state
        // projection (badge/console/switch/approval authority) and bump
        // refreshRevision so the Admin dataset listing's publication_status
        // is reconciled too, rather than trusting only the PUT's own echoed
        // fields.
        loadPublicationProjection(slug);
        setRefreshRevision((current) => current + 1);
      })
      .catch(() => {
        if (selectedSlugRef.current !== slug) {
          return;
        }
        setReviewApprovalWriteFailed(true);
        setPublicationProjection({ status: "ready", datasetSlug: slug, projection: priorProjection });
      });
  }

  // Project Spec S0099: contract-driven automatic bootstrap, replacing the
  // former manual "Load customization" gate. Keyed on the request identity
  // (selected dataset slug + resolved bound predict view id) and the
  // already-loaded public contract's own readiness. An AbortController
  // cancels a real in-flight request on cleanup; customizationRequestRef is
  // a second, independent guard against a late response from a superseded
  // identity applying itself (real fetch mocks in tests do not honor
  // AbortSignal, so this ref is the operative protection there). Bumping
  // customizationRetryNonce re-runs this effect without any identity
  // actually changing, powering the unavailable-state Retry control.
  const customizationRequestRef = useRef(0);
  const [customizationRetryNonce, setCustomizationRetryNonce] = useState(0);

  useEffect(() => {
    // Bump the request identity on every effect run, regardless of which
    // branch below is taken -- this invalidates any still-in-flight
    // previous request's requestId comparison even when the new state is
    // "no_view_bound"/"contract_unavailable" rather than a fresh fetch, so
    // a late response from a superseded selection can never apply itself
    // after the identity has already moved on.
    const requestId = customizationRequestRef.current + 1;
    customizationRequestRef.current = requestId;

    if (!selectedSlug || !boundPredictViewId) {
      setCustomizationEditorState({ status: "no_view_bound" });
      setCustomizationBaseline(null);
      setSubmitLabelMigrationPending(false);
      return;
    }

    const contractState = readOnlyData.contract;
    if (contractState.status === "unavailable") {
      setCustomizationEditorState({ status: "contract_unavailable" });
      setCustomizationBaseline(null);
      setSubmitLabelMigrationPending(false);
      return;
    }
    if (contractState.status !== "ready") {
      setCustomizationEditorState({ status: "loading" });
      setCustomizationBaseline(null);
      setSubmitLabelMigrationPending(false);
      return;
    }

    const fields = contractFields(contractState.data);
    const controller = new AbortController();

    setCustomizationEditorState({ status: "loading" });
    setCustomizationBaseline(null);

    type CustomizationReadResponse = {
      customization_exists: boolean;
      compatibility_status: "absent" | "compatible" | "incompatible";
      customization: PredictViewCustomization | null;
      errors?: CustomizationError[];
    };
    type CustomizationLoadResult = { data: CustomizationReadResponse } | { transportFailed: true } | null;

    fetch(
      `${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/views/${encodeURIComponent(boundPredictViewId)}/customization`,
      { signal: controller.signal },
    )
      .then((response): Promise<CustomizationLoadResult> => {
        if (customizationRequestRef.current !== requestId) {
          return Promise.resolve(null);
        }
        if (!response.ok) {
          return Promise.resolve({ transportFailed: true });
        }
        return response.json().then((data: CustomizationReadResponse) => ({ data }));
      })
      .then((result) => {
        if (!result || customizationRequestRef.current !== requestId) {
          return;
        }
        if ("transportFailed" in result) {
          setCustomizationEditorState({
            status: "unavailable",
            message: "Customization could not be loaded from the private admin API.",
          });
          return;
        }
        const { data } = result;
        // Project Spec S0110: legacy migration candidate. Read only from the
        // currently loaded profile draft (never mutates storage) and applied
        // to both the rendered draft and its dirty-state baseline, so
        // loading a legacy-only dataset shows the pre-filled value without
        // spuriously enabling Publish changes by itself.
        // submitLabelMigrationPending tracks the pending migration
        // separately -- publishChanges below still forces a customization
        // persist ahead of profile publication whenever it is true and a
        // profile publish is about to happen, even when only an unrelated
        // profile field changed.
        const legacySubmitButtonLabel = draftFormRef.current.legacy_submit_button_label;
        if (data.compatibility_status === "compatible" && data.customization) {
          const overlaidDraft = customizationDraftFromRecord(data.customization, fields);
          const migratedDraft = withMigratedSubmitLabel(overlaidDraft, legacySubmitButtonLabel);
          setCustomizationEditorState({
            status: "ready_overlaid",
            draft: migratedDraft,
            recordExists: true,
          });
          setCustomizationBaseline(normalizedCustomizationDraft(migratedDraft));
          setSubmitLabelMigrationPending(migratedDraft !== overlaidDraft);
          return;
        }
        // Project Spec S0103: an ignored incompatible historical
        // customization must never become the active baseline -- the
        // baseline below is always the clean contract-derived draft, the
        // same one this state renders from.
        if (data.compatibility_status === "incompatible") {
          const ignoredBaseDraft = emptyCustomizationDraft(fields);
          const migratedDraft = withMigratedSubmitLabel(ignoredBaseDraft, legacySubmitButtonLabel);
          setCustomizationEditorState({
            status: "incompatible_overlay_ignored",
            draft: migratedDraft,
            recordExists: data.customization_exists,
            errors: data.errors ?? [],
          });
          setCustomizationBaseline(normalizedCustomizationDraft(migratedDraft));
          setSubmitLabelMigrationPending(migratedDraft !== ignoredBaseDraft);
          return;
        }
        const baseDraft = emptyCustomizationDraft(fields);
        const migratedDraft = withMigratedSubmitLabel(baseDraft, legacySubmitButtonLabel);
        setCustomizationEditorState({
          status: "ready_base",
          draft: migratedDraft,
          recordExists: false,
        });
        setCustomizationBaseline(normalizedCustomizationDraft(migratedDraft));
        setSubmitLabelMigrationPending(migratedDraft !== baseDraft);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError" || customizationRequestRef.current !== requestId) {
          return;
        }
        setCustomizationEditorState({
          status: "unavailable",
          message: "Customization could not be loaded. Check private admin API reachability.",
        });
      });

    return () => controller.abort();
  }, [selectedSlug, boundPredictViewId, readOnlyData.contract, customizationRetryNonce]);

  // Shown only by CustomizationStatusPanel's "unavailable" branch (an actual
  // load failure) -- never a required normal-path action.
  function retryCustomization() {
    setCustomizationRetryNonce((current) => current + 1);
  }

  // Project Spec S0121: shown only by InferenceFormTab's views-unavailable
  // branch. Re-requests only the current selected dataset's private
  // authoring context (bumping authoringContextRetryNonce, which the
  // dedicated authoring-context effect above depends on) -- never a profile
  // publish, customization save, visibility change, review-status change, or
  // registry mutation.
  function retryAuthoringContext() {
    setAuthoringContextRetryNonce((current) => current + 1);
  }

  // Project Spec S0144: wraps executeAdminInference (Project Spec S0143's
  // private Admin executor) purely to capture the bounded safe result
  // summary a successful response carries, for the Publishing console's
  // audit line -- the request/response behavior itself, and everything
  // InferenceForm does with the returned InferenceExecutionResult, is
  // unchanged. Never stores a raw payload or raw response; only the same
  // validated binary-classification-result.v1 fields the shared Result Card
  // already renders.
  async function liveInferenceExecutor(
    slug: string,
    payload: Record<string, string | number | boolean>,
  ): Promise<InferenceExecutionResult> {
    const outcome = await executeAdminInference(slug, payload);
    pendingLiveInferenceSuccessSummaryRef.current =
      outcome.ok && isBinaryClassificationResult(outcome.result)
        ? {
            predictedPositive: outcome.result.decision.predicted_positive,
            positiveClassProbability: outcome.result.positive_class_probability,
            modelDisplayName: outcome.result.model_descriptor.display_name,
          }
        : null;
    return outcome;
  }

  // Project Spec S0144: the bounded lifecycle handler passed to the S0143
  // Live Preview inference flow. datasetSlugAtCapture is selectedSlug as
  // closed over by the specific render that created this callback instance
  // -- if InferenceForm's own stale-response guard is ever bypassed (e.g. an
  // in-flight request outliving a remount around a dataset switch), that
  // captured identity, not the live selectedSlug variable, is what
  // reduceLiveInferenceAuditEvent checks against the current audit session,
  // so a callback captured for a previous dataset can never append a line
  // after the selection changes.
  function handleLiveInferenceLifecycleEvent(datasetSlugAtCapture: string, event: InferenceLifecycleEvent) {
    const successSummary =
      event.type === "succeeded" ? pendingLiveInferenceSuccessSummaryRef.current ?? undefined : undefined;
    // Project Spec S0147: InferenceForm has already contract-filtered and
    // label-resolved these issues before this callback ever runs -- this
    // handler only forwards them into the reducer, it does not inspect or
    // re-derive them.
    const validationIssues = event.type === "validation_failed" ? event.issues : undefined;
    // Project Spec S0151: InferenceForm has already normalized this
    // diagnostic (or dropped it) before this callback ever runs -- this
    // handler only forwards it into the reducer, it does not inspect or
    // re-derive it.
    const runtimeDiagnosticCode = event.type === "execution_failed" ? event.runtimeDiagnostic?.code : undefined;
    setLiveInferenceAudit((current) =>
      reduceLiveInferenceAuditEvent(
        current,
        datasetSlugAtCapture,
        event.type,
        successSummary,
        validationIssues,
        runtimeDiagnosticCode,
      ),
    );
  }

  // Client-side mirror of the backend's REQUIRED_FIELD_HIDDEN rejection
  // (registry/predict_view_customization_validate.py): lets the shared
  // Publish changes orchestrator below block the request entirely rather
  // than round-tripping a save the backend is guaranteed to reject. This
  // does not weaken or replace that backend validation -- it only avoids
  // relying on it as the sole enforcement point.
  function requiredFieldHiddenErrors(draft: CustomizationEditorDraft): CustomizationError[] {
    return draft.fieldHints.some((field) => field.required && field.hidden)
      ? [
          {
            code: "REQUIRED_FIELD_HIDDEN",
            field: null,
            message: "Move every required field out of the field bank before saving.",
          },
        ]
      : [];
  }

  // Project Spec S0103: persists the Inference Form customization through
  // the existing customization endpoint, now called only from the shared
  // Publish changes orchestrator below (the dedicated "Save customization"
  // action no longer exists). Resolves to whether the persist succeeded so
  // the orchestrator can decide whether to proceed to profile publication.
  function persistCustomizationDraft(draft: CustomizationEditorDraft): Promise<boolean> {
    const { field_hints, groups, view_copy } = customizationDraftToRecord(draft);
    const payload = {
      schema_version: "1.0.0",
      view_id: boundPredictViewId,
      dataset_slug: selectedSlug,
      field_hints,
      groups,
      ...(view_copy ? { view_copy } : {}),
      contract_precedence: {
        canonical_contracts_are_source_of_truth: true,
        customization_defines_runtime_validation: false,
        customization_duplicates_contract: false,
      },
    };

    setCustomizationEditorState({ status: "saving", draft });

    return fetch(
      `${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/views/${encodeURIComponent(boundPredictViewId)}/customization`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    )
      .then((response) => {
        if (response.status === 404) {
          setCustomizationEditorState({
            status: "unavailable",
            message: "Customization endpoint unavailable for this private admin session. Confirm API configuration.",
          });
          return false;
        }
        return response.json().then((body: { saved?: boolean; customization?: PredictViewCustomization; errors?: CustomizationError[] }) => {
          if (!response.ok || !body.saved) {
            setCustomizationEditorState({
              status: "invalid",
              draft,
              errors: body.errors ?? [{ message: "Customization failed validation." }],
            });
            return false;
          }
          const contractState = stateValue(readOnlyData.contract);
          const fields = contractFields(contractState);
          const savedDraft = body.customization ? customizationDraftFromRecord(body.customization, fields) : draft;
          setCustomizationEditorState({ status: "saved", draft: savedDraft });
          // The new baseline is the exact persisted normalized payload
          // (Project Spec S0103), derived from whatever the backend actually
          // stored (falling back to the sent draft when it echoes nothing
          // back), never the pre-save draft alone.
          setCustomizationBaseline(normalizedCustomizationDraft(savedDraft));
          // Project Spec S0110: a successful persist always resolves any
          // pending legacy migration -- the value (whatever it now is) is
          // freshly confirmed as actually stored.
          setSubmitLabelMigrationPending(false);
          return true;
        });
      })
      .catch(() => {
        setCustomizationEditorState({ status: "unavailable", message: "Customization could not be saved. Check private admin API reachability." });
        return false;
      });
  }

  function updateCustomizationDraft(updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) {
    setCustomizationEditorState((current) => {
      if (current.status === "ready_base" || current.status === "ready_overlaid") {
        return { status: current.status, draft: updater(current.draft), recordExists: current.recordExists };
      }
      if (current.status === "incompatible_overlay_ignored") {
        return { ...current, draft: updater(current.draft) };
      }
      if (current.status === "saved" || current.status === "invalid") {
        return { status: "ready_overlaid", draft: updater(current.draft), recordExists: true };
      }
      return current;
    });
  }

  return (
    <section aria-labelledby="dataset-admin-title" className="dataset-admin-page" style={pageStyle}>
      <header style={headerStyle}>
        <div>
          <h1 id="dataset-admin-title">Dataset — {getDatasetLabel(selectedAdminDataset)}</h1>
          <p className="summary">
            Curate the selected dataset's public presentation profile while Atlas technical values stay read-only.
          </p>
        </div>

        <div className="dataset-admin-header-actions">
          <StatusPill
            aria-label="Dataset Detail visibility"
            className="dataset-admin-registry-visibility-pill"
            tone={registryVisibilityTone(selectedDatasetIsPublic)}
            variant={registryVisibilityVariant(selectedDatasetIsPublic)}
          >
            {registryVisibilityLabel}
          </StatusPill>
          <button
            className="dataset-admin-public-page-action"
            aria-label="Open public Dataset Detail page"
            disabled={!publicPageActionEnabled}
            onClick={() => window.open(`/dataset/${encodeURIComponent(selectedSlug)}`, "_blank", "noopener,noreferrer")}
            style={!publicPageActionEnabled ? iconActionButtonDisabledStyle : iconActionButtonStyle}
            type="button"
          >
            <svg aria-hidden="true" style={actionIconStyle} viewBox="0 0 24 24">
              <path d="M14 4h6v6" />
              <path d="M20 4 10 14" />
              <path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" />
            </svg>
          </button>
        </div>
      </header>

      {state.status === "error" && (
        <article role="status" style={alertStyle}>
          <strong>Dataset listing unavailable</strong>
          <p style={mutedTextStyle}>{state.message}</p>
        </article>
      )}

      {adminDatasetsState.status === "error" && (
        <article role="status" style={alertStyle}>
          <strong>Admin dataset listing unavailable</strong>
          <p style={mutedTextStyle}>{adminDatasetsState.message}</p>
        </article>
      )}

      <section aria-label="Dataset profile workspace" style={panelStyle}>
        <div aria-label="Dataset Detail workspace toolbar" role="toolbar" style={workspaceToolbarStyle}>
          <DatasetComboBox
            datasets={adminDatasets}
            disabled={adminDatasetsState.status !== "ready" || adminDatasets.length === 0}
            onNormalize={normalizeDatasetQuery}
            onQueryChange={selectDatasetFromQuery}
            query={datasetQuery}
            selectedDataset={selectedAdminDataset}
            stateStatus={adminDatasetsState.status}
          />
          <button
            disabled={toolbarPublishDisabled}
            onClick={() => publishChanges(hasUnpublishedWorkspaceChanges)}
            style={toolbarPublishDisabled ? disabledButtonStyle : actionButtonStyle}
            type="button"
          >
            Publish changes
          </button>
          {toolbarPublishProgress ? (
            <span className="dataset-admin-toolbar-progress" role="status">
              {toolbarPublishProgress}
            </span>
          ) : toolbarPublishFeedback ? (
            <span className="dataset-admin-toolbar-success" role="status">
              {toolbarPublishFeedback}
            </span>
          ) : null}
        </div>
        {toolbarPublishError ? (
          <p role="status" style={mutedTextStyle}>
            {toolbarPublishError}
          </p>
        ) : null}
        <DraftStatusPanel draftState={draftState} />
        <Tabs ariaLabel="Dataset admin tabs" items={adminTabs} onSelect={setSelectedTab} selectedId={selectedTab} />
        <div
          aria-label={`${adminTabs.find((tab) => tab.id === selectedTab)?.label ?? "Selected"} tab panel`}
          role="tabpanel"
          style={tabPanelStyle}
        >
          {renderSelectedTab(
            selectedTab,
            selectedDataset,
            draftForm,
            setField,
            readOnlyData,
            draftState,
            selectedSlug,
            customizationEditorState,
            retryCustomization,
            setConfiguredVisibility,
            updateCustomizationDraft,
            publicationState,
            publicationProjection,
            visibilityWriteFailed,
            retryAuthoringContext,
            approveDatasetReview,
            reviewApprovalWriteFailed,
            liveInferenceAudit.records,
            liveInferenceExecutor,
            (event) => handleLiveInferenceLifecycleEvent(selectedSlug, event),
          )}
        </div>
      </section>
    </section>
  );
}
