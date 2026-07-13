import {
  useEffect,
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
import DatasetDetailHeader from "../../components/DatasetDetail/DatasetDetailHeader";
import PerformanceSummary from "../../components/DatasetDetail/PerformanceSummary";
import TargetDistribution from "../../components/DatasetDetail/TargetDistribution";
import FeatureImportance from "../../components/DatasetDetail/FeatureImportance";
import ModelCard from "../../components/ModelCard/ModelCard";
import InferenceResult from "../../components/InferenceResult/InferenceResult";
import InferenceForm, {
  type FieldHint,
  type GroupDef,
  type PredictViewCustomization,
} from "../../components/InferenceForm/InferenceForm";
import {
  projectDatasetDetailPreview,
  projectHomeCardPreview,
  projectPerformanceFocusPreview,
  projectModelCardPreview,
  projectResultCardPreview,
  toVisualizationsPayload,
} from "../../lib/livePreviewProjection";
import {
  DATASET_THEME_PRESETS,
  DEFAULT_DATASET_THEME_PRESET,
  datasetThemeStyle,
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
// livePreviewProjection.ts's PreviewDraftForm.home_card_icon is still
// declared as the original closed "" | "telecom" | "bank" | "generic" union
// (out of this issue's edit scope, same as projectDatasetDetailPreview's
// {fields?} shape below). projectDatasetDetailPreview's own body never
// actually reads home_card_icon (Dataset Detail preview has no icon), so
// this narrowing only satisfies that stale parameter type and has no
// effect on what's rendered; adapt the shape here rather than modifying
// livePreviewProjection.ts.
function toLegacyPreviewIcon(
  icon: DraftForm["home_card_icon"],
): "" | "telecom" | "bank" | "generic" {
  return icon === "telecom" || icon === "bank" || icon === "generic" ? icon : "";
}

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
  { label: "Risk", value: "risk", samples: ["High risk", "Medium risk", "Low risk"], available: true },
  { label: "Value band", value: "value-band", samples: ["High value", "Medium value", "Low value"], available: false },
  { label: "Target status", value: "target-status", samples: ["Above target", "On target", "Below target"], available: false },
  { label: "Severity", value: "severity", samples: ["Critical", "Moderate", "Low"], available: false },
  { label: "Custom", value: "custom", samples: ["Dataset high", "Dataset medium", "Dataset low"], available: false },
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

type SectionState<T> =
  | { status: "idle" | "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable"; message: string };

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
    probability_label?: string;
    submit_button_label?: string;
    model_label?: string;
    badge_preset?: "risk";
    badge_labels?: {
      high?: string;
      medium?: string;
      low?: string;
    };
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
  probability_label: string;
  submit_button_label: string;
  model_label: string;
  badge_preset: "" | "risk";
  badge_high: string;
  badge_medium: string;
  badge_low: string;
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

type PublicationState =
  | { status: "idle"; visible: boolean; publishedProfile: ProfileDraft | null; message: string }
  | { status: "publishing"; visible: boolean; publishedProfile: ProfileDraft | null }
  | { status: "saving_visibility"; visible: boolean; publishedProfile: ProfileDraft | null }
  | { status: "published"; visible: boolean; publishedProfile: ProfileDraft; publishedAt?: string }
  | { status: "visibility_saved"; visible: boolean; publishedProfile: ProfileDraft | null; updatedAt?: string }
  | { status: "invalid"; visible: boolean; publishedProfile: ProfileDraft | null; errors: DraftError[] }
  | { status: "unavailable"; visible: boolean; publishedProfile: ProfileDraft | null; message: string };

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

type ModelCardPayload = {
  content?: string;
  format?: string;
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

type ReadOnlyData = {
  dataset: SectionState<DatasetListing>;
  context: SectionState<ContextPayload>;
  contract: SectionState<ContractPayload>;
  metrics: SectionState<MetricsPayload>;
  modelCard: SectionState<ModelCardPayload>;
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

type CustomizationEditorDraft = {
  fieldHints: FieldHintDraft[];
  groups: GroupDraft[];
};

type CustomizationError = {
  code?: string;
  field?: string | null;
  message?: string;
};

type CustomizationEditorState =
  | { status: "no_view_bound" }
  | { status: "idle"; message: string }
  | { status: "loading" }
  | { status: "ready"; draft: CustomizationEditorDraft; recordExists: boolean }
  | { status: "saved"; draft: CustomizationEditorDraft }
  | { status: "invalid"; draft: CustomizationEditorDraft; errors: CustomizationError[] }
  | { status: "unavailable"; message: string };

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
};

const emptyCustomizationEditorState: CustomizationEditorState = { status: "no_view_bound" };

function emptyCustomizationDraft(fields: ContractField[]): CustomizationEditorDraft {
  return {
    fieldHints: fields.map((field) => ({
      field_name: field.name,
      display_label: "",
      explanatory_copy: "",
      group: "",
      hidden: false,
      required: !field.optional,
    })),
    groups: [],
  };
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

  const groups = record.groups.map((group) => ({
    group_id: group.group_id,
    label: group.label,
    description: group.description ?? "",
  }));

  const fieldHints = sortedFields.map((field) => {
    const hint = hintMap.get(field.name);
    return {
      field_name: field.name,
      display_label: hint?.display_label ?? "",
      explanatory_copy: hint?.explanatory_copy ?? "",
      group: hint?.group ?? "",
      hidden: hint?.hidden ?? false,
      required: requiredMap.get(field.name) ?? false,
    };
  });

  // A previously saved record may not already satisfy the deterministic
  // flattening rule below (e.g. it predates this builder) -- reflow on load
  // so every loaded draft starts from the canonical macro order.
  return { fieldHints: reflowFieldHints(fieldHints, groups), groups };
}

function customizationDraftToRecord(draft: CustomizationEditorDraft): {
  field_hints: FieldHint[];
  groups: GroupDef[];
} {
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
  };
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
  metrics: { status: "idle" },
  modelCard: { status: "idle" },
  visualizations: { status: "idle" },
  views: { status: "idle" },
};

const emptyPublicationState: PublicationState = {
  status: "idle",
  visible: true,
  publishedProfile: null,
  message: "No published snapshot is known in this admin session.",
};

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

const buttonRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
  alignItems: "center",
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

const dragHandleStyle: CSSProperties = {
  ...secondaryButtonStyle,
  cursor: "grab",
  touchAction: "none",
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

const tagStyle: CSSProperties = {
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "999px",
  padding: "0.25rem 0.65rem",
  color: "var(--atlas-color-text-muted)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  background: "var(--atlas-color-surface)",
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

const subgroupControlsStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "2px",
};

const stackedIconActionButtonStyle: CSSProperties = {
  ...iconActionButtonStyle,
  width: "1.9rem",
  minWidth: "1.9rem",
  height: "1.35rem",
  fontSize: "0.65rem",
  lineHeight: 1,
};

const stackedIconActionButtonDisabledStyle: CSSProperties = {
  ...stackedIconActionButtonStyle,
  color: "var(--atlas-color-text-subtle)",
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
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
    probability_label: "",
    submit_button_label: "",
    model_label: "",
    badge_preset: "risk",
    badge_high: "",
    badge_medium: "",
    badge_low: "",
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
    probability_label: profile.result_card?.probability_label ?? "",
    submit_button_label: profile.result_card?.submit_button_label ?? "",
    model_label: profile.result_card?.model_label ?? "",
    badge_preset: profile.result_card?.badge_preset ?? "risk",
    badge_high: profile.result_card?.badge_labels?.high ?? "",
    badge_medium: profile.result_card?.badge_labels?.medium ?? "",
    badge_low: profile.result_card?.badge_labels?.low ?? "",
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

  const resultCard: NonNullable<ProfileDraft["result_card"]> = {};
  resultCard.probability_label = textValue(form.probability_label);
  resultCard.submit_button_label = textValue(form.submit_button_label);
  resultCard.model_label = textValue(form.model_label);
  if (form.badge_preset) {
    resultCard.badge_preset = form.badge_preset;
  }
  const badgeLabels: NonNullable<NonNullable<ProfileDraft["result_card"]>["badge_labels"]> = {};
  badgeLabels.high = textValue(form.badge_high);
  badgeLabels.medium = textValue(form.badge_medium);
  badgeLabels.low = textValue(form.badge_low);
  if (Object.keys(badgeLabels).length > 0) {
    resultCard.badge_labels = badgeLabels;
  }
  if (Object.keys(resultCard).length > 0) {
    profile.result_card = resultCard;
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  required?: boolean;
  maxLength?: number;
  type?: "text" | "url" | "date";
  rows?: number;
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
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          rows={rows}
          style={hasCounter ? { ...textareaStyle, ...counterPaddingStyle } : textareaStyle}
          value={value}
        />
      ) : (
        <input
          aria-label={label}
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

function metricKeys(metrics: MetricsPayload | null): string[] {
  const values = metrics?.evaluation?.metrics;
  return values && typeof values === "object" ? Object.keys(values) : [];
}

function contractFields(contract: ContractPayload | null): ContractField[] {
  return contract?.features ?? [];
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

function ErrorList({ errors }: { errors: DraftError[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: "var(--atlas-space-5)" }}>
      {errors.map((error, index) => (
        <li key={`${error.code ?? "error"}-${error.field ?? "field"}-${index}`}>
          {[error.field, error.code, error.message].filter(Boolean).join(" - ")}
        </li>
      ))}
    </ul>
  );
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
                stateValue(readOnlyData.dataset) ?? undefined,
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

function CustomizationStatusPanel({ state }: { state: CustomizationEditorState }) {
  if (state.status === "no_view_bound") {
    return (
      <article role="status" style={alertStyle}>
        <strong>No predict view bound</strong>
        <p style={mutedTextStyle}>Bind a predict view above, then load its customization.</p>
      </article>
    );
  }
  if (state.status === "ready") {
    return (
      <article style={readOnlyFieldStyle}>
        <strong>{state.recordExists ? "Customization loaded" : "No customization yet"}</strong>
        <p style={mutedTextStyle}>
          {state.recordExists
            ? "Editable fields were populated from the existing customization record."
            : "Saving will create a customization record for this predict view."}
        </p>
      </article>
    );
  }
  if (state.status === "saved") {
    return (
      <article className="atlas-status-pill atlas-status-pill--success" role="status">
        Customization saved.
      </article>
    );
  }
  if (state.status === "invalid") {
    return (
      <article role="status" style={alertStyle}>
        <strong>Customization rejected by backend validation</strong>
        <ul style={{ margin: 0, paddingLeft: "var(--atlas-space-5)" }}>
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
      <article role="status" style={alertStyle}>
        <strong>Customization unavailable</strong>
        <p style={mutedTextStyle}>{state.message}</p>
      </article>
    );
  }
  if (state.status === "loading") {
    return <p style={mutedTextStyle}>Loading customization...</p>;
  }
  return <p style={mutedTextStyle}>{state.message}</p>;
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
  // Local-only, non-schema-persisted expand/collapse affordance for group
  // cards (mirrors the executable prototype's collapse-button pattern).
  // Never read by customizationDraftToRecord and never added to
  // CustomizationEditorDraft/GroupDraft, so it cannot leak into saved state.
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(new Set());

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

  function addGroup() {
    onUpdateDraft((current) => ({
      ...current,
      groups: [...current.groups, { group_id: `group-${current.groups.length + 1}`, label: "", description: "" }],
    }));
  }

  function updateGroup(index: number, patch: Partial<GroupDraft>) {
    onUpdateDraft((current) => ({
      ...current,
      groups: current.groups.map((group, i) => (i === index ? { ...group, ...patch } : group)),
    }));
  }

  function removeGroup(groupId: string) {
    onUpdateDraft((current) => {
      const nextGroups = current.groups.filter((group) => group.group_id !== groupId);
      const clearedFieldHints = current.fieldHints.map((field) =>
        field.group === groupId ? { ...field, group: "" } : field,
      );
      return { groups: nextGroups, fieldHints: reflowFieldHints(clearedFieldHints, nextGroups) };
    });
  }

  function moveSubgroup(index: number, direction: -1 | 1) {
    onUpdateDraft((current) => {
      const nextGroups = moveItem(current.groups, index, direction);
      return { groups: nextGroups, fieldHints: reflowFieldHints(current.fieldHints, nextGroups) };
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
      return { groups: nextGroups, fieldHints: reflowFieldHints(current.fieldHints, nextGroups) };
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
    event: ReactPointerEvent<HTMLButtonElement>,
    fieldName: string,
    sourceZone: FieldZoneKey,
    sourceIndex: number,
    label: string,
  ) {
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
    });
  }

  function updateFieldDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!fieldDragState) return;
    event.preventDefault();
    const { zone, index } = resolveFieldDropTarget(
      event.clientX,
      event.clientY,
      fieldDragState.targetZone,
      fieldDragState.targetIndex,
    );
    setFieldDragState({ ...fieldDragState, targetZone: zone, targetIndex: index, pointerX: event.clientX, pointerY: event.clientY });
  }

  function finishFieldDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!fieldDragState) return;
    event.preventDefault();
    const { zone, index } = resolveFieldDropTarget(
      event.clientX,
      event.clientY,
      fieldDragState.targetZone,
      fieldDragState.targetIndex,
    );
    const { fieldName } = fieldDragState;
    setFieldDragState(null);
    onUpdateDraft((current) => moveFieldToZone(current, fieldName, zone, index));
  }

  function cancelFieldDrag(event: ReactPointerEvent<HTMLButtonElement>) {
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
                className={["dataset-admin-field-chip", attentionActive ? "is-required-attention" : ""]
                  .filter(Boolean)
                  .join(" ")}
                data-customization-field-index={index}
                data-customization-field-zone={zone}
                key={field.field_name}
                onDoubleClick={() => openFieldModal(field.field_name)}
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
                  onPointerCancel={cancelFieldDrag}
                  onPointerDown={(event) =>
                    startFieldDrag(event, field.field_name, zone, index, field.display_label || field.field_name)
                  }
                  onPointerMove={updateFieldDrag}
                  onPointerUp={finishFieldDrag}
                  style={dragHandleStyle}
                  type="button"
                >
                  ⋮⋮
                </button>
                <span className="dataset-admin-field-chip__name">{field.field_name}</span>
                {field.required && <span style={tagStyle}>Required</span>}
              </div>
            );
          })
        )}
      </div>
    );
  }

  const requiredInBankCount = draft.fieldHints.filter((field) => field.required && field.hidden).length;
  const editingField =
    fieldModalState.status === "open"
      ? draft.fieldHints.find((field) => field.field_name === fieldModalState.fieldName)
      : undefined;

  return (
    <div className="dataset-admin-builder">
      <section aria-label="Field bank" className="dataset-admin-builder__bank">
        <div>
          <span style={labelStyle}>Field bank</span>
          <p style={mutedTextStyle}>
            Fields outside the public form. Drag a chip into the public form layout to make it visible, or
            double-click a chip to edit its presentation.
          </p>
        </div>
        {requiredInBankCount > 0 && (
          <article role="status" style={alertStyle}>
            <strong>
              {requiredInBankCount} required field{requiredInBankCount === 1 ? "" : "s"} still in the bank
            </strong>
            <p style={mutedTextStyle}>
              Move every required field into the public form layout before saving. The backend rejects a saved
              customization that hides a required field.
            </p>
          </article>
        )}
        {renderFieldZone(FIELD_BANK_ZONE, "Field bank fields", "Drag fields here to remove them from the public form.")}
      </section>

      <section aria-label="Public form layout" className="dataset-admin-builder__canvas">
        <div className="dataset-admin-builder__toolbar">
          <div>
            <span style={labelStyle}>Public form layout</span>
            <p style={mutedTextStyle}>Subgroup cards and the explicit No subgroup area define presentation order.</p>
          </div>
          <button onClick={addGroup} style={secondaryButtonStyle} type="button">
            Add group
          </button>
        </div>
        {draft.groups.length === 0 ? (
          <p style={mutedTextStyle}>No subgroups defined. Visible fields without a subgroup render in No subgroup below.</p>
        ) : (
          <div className="dataset-admin-builder__stack">
            {draft.groups.map((group, index) => {
              const groupLabel = group.label || group.group_id || `Group ${index + 1}`;
              return (
                <div
                  className="dataset-admin-builder-card"
                  data-customization-group-index={index}
                  key={group.group_id}
                  style={getGroupCardStyle(index)}
                >
                  <div className="dataset-admin-builder-card__head">
                    <div style={subgroupControlsStyle}>
                      <button
                        aria-label={`Move subgroup ${groupLabel} up`}
                        disabled={index === 0}
                        onClick={() => moveSubgroup(index, -1)}
                        style={index === 0 ? stackedIconActionButtonDisabledStyle : stackedIconActionButtonStyle}
                        type="button"
                      >
                        ▲
                      </button>
                      <button
                        aria-label={`Move subgroup ${groupLabel} down`}
                        disabled={index === draft.groups.length - 1}
                        onClick={() => moveSubgroup(index, 1)}
                        style={
                          index === draft.groups.length - 1
                            ? stackedIconActionButtonDisabledStyle
                            : stackedIconActionButtonStyle
                        }
                        type="button"
                      >
                        ▼
                      </button>
                    </div>
                    <button
                      aria-label={`Drag group ${groupLabel}`}
                      onPointerCancel={cancelGroupDrag}
                      onPointerDown={(event) => startGroupDrag(event, index, groupLabel)}
                      onPointerMove={updateGroupDrag}
                      onPointerUp={finishGroupDrag}
                      style={dragHandleStyle}
                      type="button"
                    >
                      Drag
                    </button>
                    <button onClick={() => removeGroup(group.group_id)} style={secondaryButtonStyle} type="button">
                      Remove
                    </button>
                    <Badge>{zoneFieldEntries(draft, group.group_id).length} fields</Badge>
                    <button
                      aria-expanded={!collapsedGroupIds.has(group.group_id)}
                      onClick={() => toggleGroupCollapsed(group.group_id)}
                      style={secondaryButtonStyle}
                      type="button"
                    >
                      {collapsedGroupIds.has(group.group_id) ? "Expand" : "Collapse"}
                    </button>
                  </div>
                  {!collapsedGroupIds.has(group.group_id) && (
                    <>
                      <div style={twoColumnGridStyle}>
                        <TextField label="Group ID" onChange={(value) => updateGroup(index, { group_id: value })} value={group.group_id} />
                        <TextField label="Label" onChange={(value) => updateGroup(index, { label: value })} value={group.label} />
                      </div>
                      <TextField
                        label="Description"
                        onChange={(value) => updateGroup(index, { description: value })}
                        value={group.description}
                      />
                      {renderFieldZone(group.group_id, groupLabel, "Drag fields here to add them to this subgroup.")}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div aria-label="No subgroup" className="dataset-admin-no-group-zone">
          <strong>No subgroup</strong>
          <span>Visible fields with no subgroup render here, below every subgroup card.</span>
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
  onLoadCustomization,
  onSaveCustomization,
  onUpdateDraft,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  readOnlyData: ReadOnlyData;
  customizationEditorState: CustomizationEditorState;
  onLoadCustomization: () => void;
  onSaveCustomization: () => void;
  onUpdateDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void;
}) {
  const views = stateValue(readOnlyData.views) ?? [];
  const draft =
    customizationEditorState.status === "ready" ||
    customizationEditorState.status === "saved" ||
    customizationEditorState.status === "invalid"
      ? customizationEditorState.draft
      : null;
  const contractFieldsByName = useMemo(
    () => new Map(contractFields(stateValue(readOnlyData.contract)).map((field) => [field.name, field])),
    [readOnlyData.contract],
  );
  const requiredInBank = draft ? draft.fieldHints.some((field) => field.required && field.hidden) : false;
  const saveDisabled = !draft || requiredInBank;

  return (
    <TabWorkspace
      eyebrow="Inference Form"
      helper="Organize presentation for the bound predict view while contract fields and validation stay authoritative."
    >
      <Card className="dataset-admin-config-card dataset-admin-builder-shell">
        <div className="dataset-admin-builder-actions">
          <FormRow helpText="Load a predict view before editing its public form layout." htmlFor="bound-predict-view" label="Bound predict view">
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
          <div style={buttonRowStyle}>
            <button
              disabled={!form.bound_predict_view_id}
              onClick={onLoadCustomization}
              style={!form.bound_predict_view_id ? disabledButtonStyle : secondaryButtonStyle}
              type="button"
            >
              Load customization
            </button>
            <button
              disabled={saveDisabled}
              onClick={onSaveCustomization}
              style={saveDisabled ? disabledButtonStyle : actionButtonStyle}
              title={requiredInBank ? "Move every required field out of the field bank before saving." : undefined}
              type="button"
            >
              Save customization
            </button>
          </div>
        </div>

        <CustomizationStatusPanel state={customizationEditorState} />

        {draft && <CustomizationEditor contractFieldsByName={contractFieldsByName} draft={draft} onUpdateDraft={onUpdateDraft} />}
      </Card>
    </TabWorkspace>
  );
}

function ResultCardTab({
  form,
  setField,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
}) {
  return (
    <TabWorkspace eyebrow="Result Card" helper="Edit public presentation labels only; model behavior remains read-only Atlas state.">
      <div className="dataset-admin-card-grid dataset-admin-card-grid--split">
        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Configuration</h2>
            <p>Risk is the only schema-supported badge preset; the other documented interpretations remain locked.</p>
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="Probability label" onChange={(value) => setField("probability_label", value)} value={form.probability_label} />
            <TextField label="Submit button label" onChange={(value) => setField("submit_button_label", value)} value={form.submit_button_label} />
            <TextField label="Model label" onChange={(value) => setField("model_label", value)} value={form.model_label} />
          </div>
          <label className="dataset-admin-native-select">
            <span style={labelStyle}>Badge preset</span>
            <select
              onChange={(event) => setField("badge_preset", event.target.value as DraftForm["badge_preset"])}
              style={inputStyle}
              value={form.badge_preset}
            >
              <option value="">No badge preset</option>
              <option value="risk">Risk</option>
            </select>
          </label>
          <div className="dataset-admin-result-preset-grid">
            {RESULT_PRESET_CARDS.map((preset) => {
              const selected = String(form.badge_preset) === preset.value;
              return (
                <button
                  aria-disabled={!preset.available}
                  aria-pressed={preset.available ? selected : undefined}
                  className={[
                    "dataset-admin-result-preset-card",
                    selected ? "is-selected" : "",
                    !preset.available ? "is-locked" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  disabled={!preset.available}
                  key={preset.value}
                  onClick={() => {
                    if (preset.available) {
                      setField("badge_preset", preset.value as DraftForm["badge_preset"]);
                    }
                  }}
                  type="button"
                >
                  <strong>{preset.label}</strong>
                  <span>{preset.samples.join(" / ")}</span>
                  {!preset.available ? <Badge>Locked</Badge> : null}
                </button>
              );
            })}
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="High badge label" onChange={(value) => setField("badge_high", value)} value={form.badge_high} />
            <TextField label="Medium badge label" onChange={(value) => setField("badge_medium", value)} value={form.badge_medium} />
            <TextField label="Low badge label" onChange={(value) => setField("badge_low", value)} value={form.badge_low} />
          </div>
        </Card>

        <Card className="dataset-admin-preview-card">
          <div className="dataset-admin-card-heading">
            <h2>Example result</h2>
            <p>Compact preview fed by the current label fields.</p>
          </div>
          <ResultCardLivePreview form={form} />
        </Card>
      </div>
    </TabWorkspace>
  );
}

function publishingStatusLabel({
  draftState,
  hasPublishedSnapshot,
  hasUnpublishedChanges,
  hasUnsavedDraftChanges,
  visible,
}: {
  draftState: DraftState;
  hasPublishedSnapshot: boolean;
  hasUnpublishedChanges: boolean;
  hasUnsavedDraftChanges: boolean;
  visible: boolean;
}) {
  if (hasPublishedSnapshot && !visible) {
    return "Hidden";
  }
  if (hasPublishedSnapshot && hasUnpublishedChanges) {
    return "Unpublished Changes";
  }
  if (hasPublishedSnapshot) {
    return "Published";
  }
  if (hasUnsavedDraftChanges || draftState.status === "ready" || draftState.status === "saved" || draftState.status === "invalid") {
    return "Draft";
  }
  return "Not Published";
}

// Project Spec S0060: publish-first, visibility-aware feedback for a
// successful Publish changes. Phrased distinctly from
// toolbarPublicationFeedback below (which reuses the same publicationState)
// so the two can render at the same time -- this tab panel and the
// always-visible workspace toolbar line -- without colliding on identical
// text when the Publishing tab happens to be selected.
function publicationMessage(publicationState: PublicationState): string {
  switch (publicationState.status) {
    case "published": {
      const timestamp = publicationState.publishedAt ? `Published at ${publicationState.publishedAt}. ` : "Published. ";
      return publicationState.visible ? `${timestamp}Public content is live.` : `${timestamp}Public visibility is currently off.`;
    }
    case "visibility_saved":
      return publicationState.visible ? "Latest published snapshot is visible publicly." : "Latest published snapshot is hidden publicly.";
    case "publishing":
      return "Publishing changes...";
    case "saving_visibility":
      return "Saving public exposure setting...";
    case "invalid":
      return "Publishing action rejected by backend validation.";
    case "unavailable":
      return publicationState.message;
    case "idle":
    default:
      return publicationState.message;
  }
}

// The workspace toolbar keeps successful publish feedback intentionally
// compact. Visibility detail remains available in the Publishing tab, while
// the toolbar only confirms that the requested changes were saved.
function toolbarPublicationFeedback(publicationState: PublicationState): string | null {
  if (publicationState.status !== "published") {
    return null;
  }
  return "Changes saved.";
}

function visibilityCopy(publicationState: PublicationState, hasPublishedSnapshot: boolean): string {
  if (!hasPublishedSnapshot) {
    return "Public access is locked until a first published snapshot exists.";
  }
  if (publicationState.visible) {
    return "The latest published snapshot is accessible from the public Dataset Detail page and Home card.";
  }
  return "The latest published snapshot exists, but public access is hidden.";
}

function draftStateSummary(draftState: DraftState, hasUnsavedDraftChanges: boolean, hasUnpublishedChanges: boolean): string {
  if (hasUnsavedDraftChanges) {
    return "Unsaved local changes.";
  }
  if (hasUnpublishedChanges) {
    return "Saved with unpublished changes.";
  }
  if (draftState.status === "saved") {
    return "Saved and matches public snapshot.";
  }
  if (draftState.status === "ready") {
    return "Loaded private draft.";
  }
  if (draftState.status === "invalid") {
    return "Validation needs attention.";
  }
  return "Editable draft.";
}

function publicSnapshotSummary(hasPublishedSnapshot: boolean): string {
  return hasPublishedSnapshot ? "Available." : "Not published yet.";
}

function visibilitySummary(publicationState: PublicationState, hasPublishedSnapshot: boolean): string {
  if (!hasPublishedSnapshot) {
    return "Locked until first publish.";
  }
  return publicationState.visible ? "Public." : "Hidden.";
}

function PublishingTab({
  draftState,
  hasPublishedSnapshot,
  hasUnpublishedChanges,
  hasUnsavedDraftChanges,
  lastPublishedAt,
  onPreviewDraft,
  onPublish,
  onSaveDraft,
  onSetVisibility,
  publicationState,
  publishDisabledReason,
  selectedSlug,
}: {
  draftState: DraftState;
  hasPublishedSnapshot: boolean;
  hasUnpublishedChanges: boolean;
  hasUnsavedDraftChanges: boolean;
  lastPublishedAt: string | undefined;
  onPreviewDraft: () => void;
  onPublish: () => void;
  onSaveDraft: () => void;
  onSetVisibility: (visible: boolean) => void;
  publicationState: PublicationState;
  publishDisabledReason: string | null;
  selectedSlug: string;
}) {
  const busy = publicationState.status === "publishing" || publicationState.status === "saving_visibility";
  const publishDisabled = Boolean(publishDisabledReason) || busy;
  const visibilityDisabled = !selectedSlug || !hasPublishedSnapshot || busy;
  const statusLabel = publishingStatusLabel({
    draftState,
    hasPublishedSnapshot,
    hasUnpublishedChanges,
    hasUnsavedDraftChanges,
    visible: publicationState.visible,
  });

  return (
    <>
      <div className="dataset-admin-publishing-layout">
        <Card className="dataset-admin-config-card dataset-admin-publishing-card">
          <span className="dataset-admin-tab-workspace__eyebrow">Public visibility</span>
          <div className="dataset-admin-visibility-row">
            <div>
              <strong>Visible publicly</strong>
              <p>{visibilityCopy(publicationState, hasPublishedSnapshot)}</p>
            </div>
            <label className="dataset-admin-switch" aria-label="Visible Publicly">
              <input
                checked={publicationState.visible}
                disabled={visibilityDisabled}
                onChange={(event) => onSetVisibility(event.target.checked)}
                type="checkbox"
              />
              <span aria-hidden="true" />
            </label>
          </div>
          <p className="dataset-admin-visibility-note">
            {hasPublishedSnapshot && publicationState.visible
              ? "Public access is enabled for the latest published snapshot."
              : hasPublishedSnapshot
              ? "Public access is disabled; the published snapshot is preserved."
              : "Publish changes before enabling public access."}
          </p>
          <div className="dataset-admin-last-published">
            <span>Last published</span>
            <strong>{lastPublishedAt ? `${lastPublishedAt} (this session)` : "Not published in this session"}</strong>
          </div>
          <div className="dataset-admin-publish-rule-card" aria-label="Publishing rule summary">
            <strong>Content and access are separate</strong>
            <p>
              <b>Publish changes</b> updates the public snapshot. <b>Visible publicly</b> only controls whether that
              snapshot can be accessed.
            </p>
          </div>
        </Card>

        <Card className="dataset-admin-config-card dataset-admin-publishing-card">
          <span className="dataset-admin-tab-workspace__eyebrow">Actions</span>
          <div className="dataset-admin-publishing-actions">
            <button disabled={!selectedSlug || draftState.status === "loading"} onClick={onSaveDraft} style={selectedSlug ? secondaryButtonStyle : disabledButtonStyle} type="button">
              Save draft
            </button>
            <button disabled={!selectedSlug} onClick={onPreviewDraft} style={selectedSlug ? secondaryButtonStyle : disabledButtonStyle} type="button">
              Preview
            </button>
            <button disabled={publishDisabled} onClick={onPublish} style={publishDisabled ? disabledButtonStyle : actionButtonStyle} type="button">
              Publish changes
            </button>
          </div>
          <p className="dataset-admin-publishing-rule-text">
            Draft changes are private until published. Preview uses the current draft. Publishing creates the public snapshot.
          </p>
          <div className="dataset-admin-current-state-card" aria-label="Current publication state">
            <span className="dataset-admin-tab-workspace__eyebrow">Current state</span>
            <ul className="dataset-admin-state-list">
              <li>
                <strong>Draft</strong>
                <span>{draftStateSummary(draftState, hasUnsavedDraftChanges, hasUnpublishedChanges)}</span>
              </li>
              <li>
                <strong>Public snapshot</strong>
                <span>{publicSnapshotSummary(hasPublishedSnapshot)}</span>
              </li>
              <li>
                <strong>Visibility</strong>
                <span>{visibilitySummary(publicationState, hasPublishedSnapshot)}</span>
              </li>
            </ul>
          </div>
          <ul className="dataset-admin-state-list dataset-admin-state-list--rules" aria-label="Documented publication states">
            <li>
              <strong>Save draft</strong>
              <span>Persists admin edits without changing the public version.</span>
            </li>
            <li>
              <strong>Preview</strong>
              <span>Simulates the current draft without changing public state.</span>
            </li>
            <li>
              <strong>Publish changes</strong>
              <span>Creates or replaces the public snapshot from the draft.</span>
            </li>
            <li>
              <strong>Visible publicly</strong>
              <span>Controls access to the latest published snapshot only.</span>
            </li>
          </ul>
        </Card>
      </div>
      {publishDisabledReason && <p style={mutedTextStyle}>{publishDisabledReason}</p>}
      <article
        className={publicationState.status === "published" || publicationState.status === "visibility_saved" ? "atlas-status-pill atlas-status-pill--success" : undefined}
        role="status"
        style={publicationState.status === "invalid" || publicationState.status === "unavailable" ? alertStyle : undefined}
      >
        <strong>{publicationMessage(publicationState)}</strong>
        {publicationState.status === "invalid" && <ErrorList errors={publicationState.errors} />}
      </article>
    </>
  );
}

function DatasetDetailLivePreview({
  dataset,
  form,
  readOnlyData,
}: {
  dataset?: DatasetListing;
  form: DraftForm;
  readOnlyData: ReadOnlyData;
}) {
  const context = stateValue(readOnlyData.context);
  const contract = stateValue(readOnlyData.contract);
  const metrics = stateValue(readOnlyData.metrics);
  const modelCard = stateValue(readOnlyData.modelCard);
  const visualizations = toVisualizationsPayload(stateValue(readOnlyData.visualizations));

  // livePreviewProjection.ts's projectDatasetDetailPreview expects its own
  // locally-declared {fields?} shape (out of this issue's edit scope); adapt
  // the real {features} contract shape into that shape here rather than
  // modifying livePreviewProjection.ts.
  const previewContract = contract ? { fields: contract.features } : null;
  // Force the Release hint to the same fixed "dd/mm/yyyy" wording the public
  // Dataset Detail page currently and always renders (web/src/pages/DatasetPage.tsx
  // hardcodes this; its PublicContextPayload type never declares a date_format
  // field), instead of exposing per-dataset precision the public page does not
  // yet honor. Clamped here rather than in livePreviewProjection.ts because
  // that module's colocated unit test (livePreviewProjection.test.ts) asserts
  // the general date_format-forwarding contract in isolation and is outside
  // this issue's declared edit scope.
  const previewForm = {
    ...form,
    date_format: "" as DraftForm["date_format"],
    home_card_icon: toLegacyPreviewIcon(form.home_card_icon),
  };
  const preview = projectDatasetDetailPreview(dataset, previewForm, context, previewContract, metrics);
  const modelCardPreview = projectModelCardPreview(modelCard);

  return (
    <div style={{ display: "grid", gap: "var(--atlas-space-4)" }}>
      <DatasetDetailHeader
        analysisType={preview.analysisType}
        datasetTitle={preview.datasetTitle}
        metadata={preview.metadata}
        subtitle={preview.subtitle}
      />
      <PerformanceSummary
        metrics={metrics ?? {}}
        performanceFocus={projectPerformanceFocusPreview(form.performance_focus)}
      />
      <TargetDistribution visualizations={visualizations} />
      <FeatureImportance visualizations={visualizations} />
      {modelCardPreview && <ModelCard modelCard={modelCardPreview} />}
    </div>
  );
}

function ResultCardLivePreview({ form }: { form: DraftForm }) {
  const { result, previewLabels } = projectResultCardPreview(form);

  return (
    <div style={{ display: "grid", gap: "var(--atlas-space-4)" }}>
      <p style={mutedTextStyle}>
        Placeholder preview only, not a real prediction. Submit button will read:{" "}
        <strong>{form.submit_button_label.trim() || "Submit"}</strong>
      </p>
      <InferenceResult result={result} previewLabels={previewLabels} />
    </div>
  );
}

function FormLayoutLivePreview({
  readOnlyData,
  selectedSlug,
  customizationEditorState,
}: {
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  customizationEditorState: CustomizationEditorState;
}) {
  const contract = stateValue(readOnlyData.contract);
  const draft =
    customizationEditorState.status === "ready" ||
    customizationEditorState.status === "saved" ||
    customizationEditorState.status === "invalid"
      ? customizationEditorState.draft
      : null;

  if (!contract) {
    return <p style={mutedTextStyle}>Contract fields are unavailable for this dataset.</p>;
  }
  if (!draft) {
    return (
      <p style={mutedTextStyle}>
        Load a predict view's customization in the Inference Form tab to preview its layout here.
      </p>
    );
  }

  const { field_hints, groups } = customizationDraftToRecord(draft);
  const customization: PredictViewCustomization = { field_hints, groups };

  return <InferenceForm contract={contract} customization={customization} previewMode slug={selectedSlug} />;
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
}: {
  dataset?: DatasetListing;
  form: DraftForm;
  hasPublishedSnapshot: boolean;
  hasUnpublishedChanges: boolean;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  customizationEditorState: CustomizationEditorState;
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
        className="dataset-admin-preview-stage dataset-theme-scope"
        data-theme-preset={form.theme_preset}
        style={datasetThemeStyle(form.theme_preset)}
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
          <article className="dataset-admin-preview-panel dataset-admin-preview-panel--detail" aria-label="Dataset Detail preview">
            <DatasetDetailLivePreview dataset={dataset} form={form} readOnlyData={readOnlyData} />
            <div className="dataset-admin-detail-preview-grid">
              <ResultCardLivePreview form={form} />
              <FormLayoutLivePreview
                customizationEditorState={customizationEditorState}
                readOnlyData={readOnlyData}
                selectedSlug={selectedSlug}
              />
            </div>
          </article>
        )}
      </div>
    </>
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
  onLoadCustomization: () => void,
  onPreviewDraft: () => void,
  onPublish: () => void,
  onSaveDraft: () => void,
  onSetVisibility: (visible: boolean) => void,
  onSaveCustomization: () => void,
  onUpdateCustomizationDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void,
  publicationState: PublicationState,
  lastPublishedAt: string | undefined,
) {
  // Shared by the Publishing and Live Preview cases below so Live Preview can
  // classify its own draft-vs-published state (S0009) using the same
  // comparison Publishing already derives, instead of a second, divergent
  // notion of "matches published".
  const currentProfile = selectedSlug ? profileFromForm(form, selectedSlug) : null;
  const lastBackendDraft = backendDraftProfile(draftState);
  const hasUnsavedDraftChanges = Boolean(currentProfile && lastBackendDraft && !sameProfile(currentProfile, lastBackendDraft));
  const publishedProfile = publicationState.publishedProfile;
  const hasPublishedSnapshot = Boolean(publishedProfile);
  const hasUnpublishedChanges = Boolean(currentProfile && publishedProfile && !sameProfile(currentProfile, publishedProfile));
  // Project Spec S0061: Publish changes no longer requires a prior saved
  // profile-draft, so its own enablement is judged only against the last
  // successfully published snapshot (or "nothing published yet this
  // session", which is always publishable) -- distinct from
  // hasUnpublishedChanges above, which stays gated on a real published
  // snapshot existing so the "Unpublished Changes" status label (and
  // draftStateSummary's "Loaded private draft."/"Saved and matches public
  // snapshot." wording) are unaffected by this change.
  const hasPublishableChanges = Boolean(currentProfile) && (!publishedProfile || !sameProfile(currentProfile, publishedProfile));

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
          onLoadCustomization={onLoadCustomization}
          onSaveCustomization={onSaveCustomization}
          onUpdateDraft={onUpdateCustomizationDraft}
          readOnlyData={readOnlyData}
          setField={setField}
        />
      );
    case "result-card":
      return <ResultCardTab form={form} setField={setField} />;
    case "documentation":
      return <div aria-label="Documentation placeholder" />;
    case "publishing":
      {
        const publishDisabledReason = !selectedSlug
          ? "Select a dataset before publishing."
          : !hasPublishableChanges
          ? "No changes to publish."
          : null;

        return (
          <PublishingTab
            draftState={draftState}
            hasPublishedSnapshot={hasPublishedSnapshot}
            hasUnpublishedChanges={hasUnpublishedChanges}
            hasUnsavedDraftChanges={hasUnsavedDraftChanges}
            lastPublishedAt={lastPublishedAt}
            onPreviewDraft={onPreviewDraft}
            onPublish={onPublish}
            onSaveDraft={onSaveDraft}
            onSetVisibility={onSetVisibility}
            publicationState={publicationState}
            publishDisabledReason={publishDisabledReason}
            selectedSlug={selectedSlug}
          />
        );
      }
    case "live-preview":
      return (
        <LivePreviewTab
          customizationEditorState={customizationEditorState}
          dataset={dataset}
          form={form}
          hasPublishedSnapshot={hasPublishedSnapshot}
          hasUnpublishedChanges={hasUnpublishedChanges}
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
  const [publicationState, setPublicationState] = useState<PublicationState>(emptyPublicationState);
  const [lastPublishedAt, setLastPublishedAt] = useState<string | undefined>(undefined);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const loadedDatasetSlugRef = useRef("");
  const canonicalDateBySlugRef = useRef<Record<string, string>>({});
  const draftFormRef = useRef(draftForm);
  const draftStateRef = useRef(draftState);
  draftFormRef.current = draftForm;
  draftStateRef.current = draftState;

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
      setReadOnlyData(emptyReadOnlyData);
      setDraftForm(emptyDraftForm());
      setCustomizationEditorState(emptyCustomizationEditorState);
      setPublicationState(emptyPublicationState);
      setLastPublishedAt(undefined);
      return;
    }

    const isBackgroundRefresh = loadedDatasetSlugRef.current === selectedSlug;
    if (!isBackgroundRefresh) {
      setDraftForm((current) => ({ ...emptyDraftForm(selectedSlug), schema_version: current.schema_version || "1.0.0" }));
      setDraftState({ status: "loading" });
      setCustomizationEditorState(emptyCustomizationEditorState);
      setPublicationState(emptyPublicationState);
      setLastPublishedAt(undefined);
    }
    loadedDatasetSlugRef.current = selectedSlug;

    const controller = new AbortController();
    if (!isBackgroundRefresh) {
      setReadOnlyData({
        dataset: { status: "loading" },
        context: { status: "loading" },
        contract: { status: "loading" },
        metrics: { status: "loading" },
        modelCard: { status: "loading" },
        visualizations: { status: "loading" },
        views: { status: "loading" },
      });
    }

    async function loadReadOnlyAtlasValues() {
      const encoded = encodeURIComponent(selectedSlug);
      const [dataset, context, contract, metrics, modelCard, visualizations, viewsResponse] = await Promise.all([
        fetchJson<DatasetListing>(`/datasets/${encoded}`, controller.signal),
        fetchJson<{ context: ContextPayload }>(`/datasets/${encoded}/context`, controller.signal),
        fetchJson<{ contract: ContractPayload }>(`/datasets/${encoded}/contract`, controller.signal),
        fetchJson<{ metrics: MetricsPayload }>(`/datasets/${encoded}/metrics`, controller.signal),
        fetchJson<{ model_card: ModelCardPayload }>(`/datasets/${encoded}/model-card`, controller.signal),
        fetchJson<{ visualizations: unknown }>(`/datasets/${encoded}/visualizations`, controller.signal),
        fetchJson<{ views: PredictView[] }>(`/datasets/${encoded}/views`, controller.signal),
      ]);

      setReadOnlyData({
        dataset,
        context: mapSection(context, (data) => data.context),
        contract: mapSection(contract, (data) => data.contract),
        metrics: mapSection(metrics, (data) => data.metrics),
        modelCard: mapSection(modelCard, (data) => data.model_card),
        visualizations: mapSection(visualizations, (data) => data.visualizations),
        views: mapSection(viewsResponse, (data) => data.views),
      });
    }

    void loadReadOnlyAtlasValues();

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
          setPublicationState((current) => ({
            status: "idle",
            visible: current.visible,
            publishedProfile,
            message: "Latest published snapshot loaded.",
          }));
          setLastPublishedAt(data.published_snapshot?.published_at);
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setDraftState({ status: "unavailable", message: "Content could not be loaded. Check API reachability." });
        }
      });

    return () => controller.abort();
  }, [selectedSlug, refreshRevision]);

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
  // A Dataset Detail is genuinely public only when it is both reviewed
  // ("ready", not "needs_review") and Visible Publicly -- exactly the two
  // gates GET /datasets composes server-side (resolve_dataset_visibility +
  // is_dataset_needs_review, api/main.py's list_datasets_endpoint). Rather
  // than duplicating that boundary client-side, a dataset is treated as
  // publicly reachable here iff its slug is present in the already-fetched
  // public listing -- the same source of truth the public site itself uses.
  const publicDatasetSlugsKnown = state.status === "ready";
  const selectedDatasetIsPublic = Boolean(selectedSlug) && datasets.some((dataset) => dataset.dataset_slug === selectedSlug);
  const registryVisibilityLabel = !selectedSlug
    ? "No dataset selected"
    : !publicDatasetSlugsKnown
    ? "Checking..."
    : selectedDatasetIsPublic
    ? "Published"
    : "Private";
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
  // The workspace toolbar's Publish changes snapshot (Project Spec S0058):
  // the normalized current saved/published form state for the selected
  // Dataset Detail's workspace-publishable fields, or -- when no backend draft/
  // profile exists yet -- the same blank-form-with-seeded-title baseline the
  // canonicalDisplayTitle effect above establishes. The Publishing tab keeps
  // using the whole-profile comparison above for its own lifecycle.
  const workspacePublishSnapshotForm: DraftForm =
    hasBackendDraftProfile && lastBackendDraft
      ? { ...formFromProfile(lastBackendDraft, selectedSlug), release_date_label: lastUpdatedDate }
      : {
          ...emptyDraftForm(selectedSlug),
          display_title: canonicalDisplayTitle,
          release_date_label: lastUpdatedDate,
        };
  const hasUnpublishedWorkspaceChanges =
    Boolean(selectedSlug) && !sameWorkspacePublishFields(draftForm, workspacePublishSnapshotForm);
  const toolbarPublishBusy =
    draftState.status === "loading" ||
    publicationState.status === "publishing" ||
    publicationState.status === "saving_visibility";
  const toolbarPublishDisabled = !selectedSlug || !hasUnpublishedWorkspaceChanges || toolbarPublishBusy;
  const toolbarPublishError =
    draftState.status === "invalid"
      ? "Public Content changes could not be saved. Open the Publishing tab for details."
      : publicationState.status === "invalid"
      ? "Public Content changes could not be published. Open the Publishing tab for details."
      : publicationState.status === "unavailable"
      ? publicationState.message
      : null;
  const toolbarPublishFeedback = toolbarPublicationFeedback(publicationState);

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

  // Save draft remains available for operators who still want to persist an
  // in-progress edit privately without publishing it (Project Spec S0061
  // keeps legacy draft endpoint behavior for compatibility), but is no
  // longer a precondition of Publish changes below.
  function saveDraft() {
    if (!selectedSlug) {
      return;
    }

    const profile = profileFromForm(draftForm, selectedSlug);
    setDraftState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/profile-draft`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(profile),
    })
      .then((response) => {
        if (response.status === 404) {
          setDraftState({
            status: "unavailable",
            message: "Content saving is unavailable for this admin session. Confirm API configuration.",
          });
          return null;
        }
        return response.json().then((body: { saved?: boolean; profile?: ProfileDraft; errors?: DraftError[] }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (!result) {
          return;
        }
        if (!result.ok || !result.body.saved) {
          setDraftState({ status: "invalid", errors: result.body.errors ?? [{ message: "Content failed validation." }] });
          return;
        }
        const savedProfile = result.body.profile ?? profile;
        setDraftForm(formFromProfile(savedProfile, selectedSlug));
        setDraftState({ status: "saved", profile: savedProfile });
      })
      .catch(() => {
        setDraftState({ status: "unavailable", message: "Content could not be saved. Check API reachability." });
      });
  }

  const boundPredictViewId = draftForm.bound_predict_view_id;

  // Project Spec S0061: Publish changes sends the current form payload
  // directly to the direct publish boundary -- no persisted profile-draft is
  // read or required by the backend along this path. Shared by publishChanges
  // (Publishing tab) and the workspace toolbar's own Publish changes button,
  // both of which call this with profileFromForm(draftForm, selectedSlug)
  // and nothing else.
  function performPublish(profileToPublish: ProfileDraft) {
    setPublicationState((current) => ({
      status: "publishing",
      visible: current.visible,
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
            visible: current.visible,
            publishedProfile: current.publishedProfile,
            message: "Publish endpoint unavailable for this private admin session. Confirm API configuration.",
          }));
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
            visible: current.visible,
            publishedProfile: current.publishedProfile,
            errors: result.body.errors ?? [{ message: "Profile publish failed validation." }],
          }));
          return;
        }
        const publishedProfile = profileFromSnapshot(result.body.snapshot, selectedSlug) ?? profileToPublish;
        // A successful publish also becomes the new local dirty-state
        // baseline (Project Spec S0061 acceptance criteria), reusing the
        // same draftState/lastBackendDraft plumbing draftStateSummary and
        // the workspace toolbar's own Public-Content-scoped comparison
        // already key off, so Publish changes disables again immediately
        // until the form changes further -- without requiring an explicit
        // Save draft call.
        setDraftForm(formFromProfile(publishedProfile, selectedSlug));
        setDraftState({ status: "saved", profile: publishedProfile });
        setPublicationState((current) => ({
          status: "published",
          visible: current.visible,
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
        setLastPublishedAt(result.body.snapshot?.published_at);
        setRefreshRevision((current) => current + 1);
      })
      .catch(() => {
        setPublicationState((current) => ({
          status: "unavailable",
          visible: current.visible,
          publishedProfile: current.publishedProfile,
          message: "Profile could not be published. Check private admin API reachability.",
        }));
      });
  }

  // Shared by the Publishing tab's own Publish changes button and the
  // workspace toolbar's Publish changes button (Project Spec S0061): both
  // publish the current form payload directly, with no save-profile-draft
  // precondition.
  function publishChanges() {
    if (!selectedSlug) {
      return;
    }

    performPublish(profileFromForm(draftForm, selectedSlug));
  }

  function setPublicVisibility(visible: boolean) {
    if (!selectedSlug) {
      return;
    }

    setPublicationState((current) => ({
      status: "saving_visibility",
      visible: current.visible,
      publishedProfile: current.publishedProfile,
    }));
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/visibility`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible }),
    })
      .then((response) => {
        if (response.status === 404) {
          setPublicationState((current) => ({
            status: "unavailable",
            visible: current.visible,
            publishedProfile: current.publishedProfile,
            message: "Visibility endpoint unavailable for this private admin session. Confirm API configuration.",
          }));
          return null;
        }
        return response.json().then((body: { visible?: boolean; updated_at?: string; error_code?: string; message?: string; errors?: DraftError[] }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (!result) {
          return;
        }
        if (!result.ok || typeof result.body.visible !== "boolean") {
          setPublicationState((current) => ({
            status: "invalid",
            visible: current.visible,
            publishedProfile: current.publishedProfile,
            errors:
              result.body.errors ??
              [{ code: result.body.error_code, message: result.body.message ?? "Visibility change failed validation." }],
          }));
          return;
        }
        setPublicationState((current) => ({
          status: "visibility_saved",
          visible: result.body.visible ?? visible,
          publishedProfile: current.publishedProfile,
          updatedAt: result.body.updated_at,
        }));
      })
      .catch(() => {
        setPublicationState((current) => ({
          status: "unavailable",
          visible: current.visible,
          publishedProfile: current.publishedProfile,
          message: "Public exposure could not be saved. Check private admin API reachability.",
        }));
      });
  }

  useEffect(() => {
    if (!boundPredictViewId) {
      setCustomizationEditorState({ status: "no_view_bound" });
      return;
    }
    setCustomizationEditorState({
      status: "idle",
      message: "Load the customization for the bound predict view from the private admin API.",
    });
  }, [boundPredictViewId]);

  function loadCustomization() {
    if (!selectedSlug || !boundPredictViewId) {
      return;
    }

    const contractState = stateValue(readOnlyData.contract);
    const fields = contractFields(contractState);

    setCustomizationEditorState({ status: "loading" });
    fetch(
      `${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/views/${encodeURIComponent(boundPredictViewId)}/customization`,
    )
      .then((response) => {
        if (response.status === 404) {
          setCustomizationEditorState({
            status: "unavailable",
            message: "Customization endpoint unavailable for this private admin session. Confirm API configuration.",
          });
          return null;
        }
        if (!response.ok) {
          setCustomizationEditorState({ status: "unavailable", message: "Customization could not be loaded from the private admin API." });
          return null;
        }
        return response.json() as Promise<{
          customization_exists: boolean;
          customization: PredictViewCustomization | null;
        }>;
      })
      .then((data) => {
        if (!data) {
          return;
        }
        const draft = data.customization
          ? customizationDraftFromRecord(data.customization, fields)
          : emptyCustomizationDraft(fields);
        setCustomizationEditorState({ status: "ready", draft, recordExists: data.customization_exists });
      })
      .catch(() => {
        setCustomizationEditorState({ status: "unavailable", message: "Customization could not be loaded. Check private admin API reachability." });
      });
  }

  function saveCustomization() {
    if (!selectedSlug || !boundPredictViewId) {
      return;
    }
    if (customizationEditorState.status !== "ready" && customizationEditorState.status !== "saved" && customizationEditorState.status !== "invalid") {
      return;
    }

    const draft = customizationEditorState.draft;
    // Client-side mirror of the backend's REQUIRED_FIELD_HIDDEN rejection
    // (registry/predict_view_customization_validate.py): block the request
    // entirely rather than round-tripping a save the backend is guaranteed
    // to reject. This does not weaken or replace that backend validation --
    // it only avoids relying on it as the sole enforcement point.
    if (draft.fieldHints.some((field) => field.required && field.hidden)) {
      setCustomizationEditorState({
        status: "invalid",
        draft,
        errors: [
          {
            code: "REQUIRED_FIELD_HIDDEN",
            field: null,
            message: "Move every required field out of the field bank before saving.",
          },
        ],
      });
      return;
    }
    const { field_hints, groups } = customizationDraftToRecord(draft);
    const payload = {
      schema_version: "1.0.0",
      view_id: boundPredictViewId,
      dataset_slug: selectedSlug,
      field_hints,
      groups,
      contract_precedence: {
        canonical_contracts_are_source_of_truth: true,
        customization_defines_runtime_validation: false,
        customization_duplicates_contract: false,
      },
    };

    fetch(
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
          return null;
        }
        return response.json().then((body: { saved?: boolean; customization?: PredictViewCustomization; errors?: CustomizationError[] }) => ({
          ok: response.ok,
          body,
        }));
      })
      .then((result) => {
        if (!result) {
          return;
        }
        if (!result.ok || !result.body.saved) {
          setCustomizationEditorState({
            status: "invalid",
            draft,
            errors: result.body.errors ?? [{ message: "Customization failed validation." }],
          });
          return;
        }
        const contractState = stateValue(readOnlyData.contract);
        const fields = contractFields(contractState);
        const savedDraft = result.body.customization
          ? customizationDraftFromRecord(result.body.customization, fields)
          : draft;
        setCustomizationEditorState({ status: "saved", draft: savedDraft });
      })
      .catch(() => {
        setCustomizationEditorState({ status: "unavailable", message: "Customization could not be saved. Check private admin API reachability." });
      });
  }

  function updateCustomizationDraft(updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) {
    setCustomizationEditorState((current) => {
      if (current.status === "ready") {
        return { status: "ready", draft: updater(current.draft), recordExists: current.recordExists };
      }
      if (current.status === "saved" || current.status === "invalid") {
        return { status: "ready", draft: updater(current.draft), recordExists: true };
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
            disabled={!selectedSlug || !publicDatasetSlugsKnown || !selectedDatasetIsPublic}
            onClick={() => window.open(`/dataset/${encodeURIComponent(selectedSlug)}`, "_blank", "noopener,noreferrer")}
            style={!selectedSlug || !publicDatasetSlugsKnown || !selectedDatasetIsPublic ? iconActionButtonDisabledStyle : iconActionButtonStyle}
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
            onClick={publishChanges}
            style={toolbarPublishDisabled ? disabledButtonStyle : actionButtonStyle}
            type="button"
          >
            Publish changes
          </button>
          {toolbarPublishFeedback ? (
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
            loadCustomization,
            () => setSelectedTab("live-preview"),
            publishChanges,
            // Publishing tab's own Save draft button passes its onClick
            // SyntheticEvent straight through as this callback's first
            // argument -- wrap so it never reaches saveDraft.
            () => saveDraft(),
            setPublicVisibility,
            saveCustomization,
            updateCustomizationDraft,
            publicationState,
            lastPublishedAt,
          )}
        </div>
      </section>
    </section>
  );
}
