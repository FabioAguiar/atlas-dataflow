import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Badge, Card, FormRow, StatusPill, Tabs, type TabItem } from "../../components/ui";
import DatasetCard from "../../components/DatasetCard";
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
  projectModelCardPreview,
  projectResultCardPreview,
  toVisualizationsPayload,
} from "../../lib/livePreviewProjection";
import type { DatasetIconName } from "../../lib/datasetPresentation";

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
  { value: "telecom", label: "Telecom" },
  { value: "bank", label: "Bank" },
  { value: "generic", label: "Generic" },
  { value: "telecom-users", label: "Telecom (Users)" },
  { value: "bank-building", label: "Bank (Building)" },
  { value: "chart-line", label: "Chart Line" },
  { value: "heart", label: "Heart" },
  { value: "shopping-cart", label: "Shopping Cart" },
  { value: "airplane", label: "Airplane" },
  { value: "shield", label: "Shield" },
  { value: "education-cap", label: "Education Cap" },
  { value: "energy-bolt", label: "Energy Bolt" },
  { value: "home-house", label: "Home / House" },
  { value: "agro-leaf", label: "Agriculture Leaf" },
  { value: "logistics-truck", label: "Logistics Truck" },
  { value: "factory", label: "Factory" },
  { value: "weather-cloud", label: "Weather Cloud" },
  { value: "database", label: "Database" },
];

const THEME_PRESET_CARDS = [
  { label: "Atlas Green", value: "atlas-green", swatches: ["#2f6f4e", "#e8f2ec", "#ffffff"], available: true },
  { label: "Ocean Blue", value: "ocean-blue", swatches: ["#2563eb", "#dbeafe", "#ffffff"], available: false },
  { label: "Violet Insight", value: "violet-insight", swatches: ["#6d28d9", "#ede9fe", "#ffffff"], available: false },
  { label: "Amber Signal", value: "amber-signal", swatches: ["#b45309", "#fef3c7", "#ffffff"], available: false },
  { label: "Slate Ops", value: "slate-ops", swatches: ["#334155", "#e2e8f0", "#ffffff"], available: false },
  { label: "Rose Review", value: "rose-review", swatches: ["#be123c", "#ffe4e6", "#ffffff"], available: false },
  { label: "Teal Flow", value: "teal-flow", swatches: ["#0f766e", "#ccfbf1", "#ffffff"], available: false },
  { label: "Indigo Lab", value: "indigo-lab", swatches: ["#4338ca", "#e0e7ff", "#ffffff"], available: false },
  { label: "Graphite", value: "graphite", swatches: ["#27272a", "#e4e4e7", "#ffffff"], available: false },
  { label: "Citrus", value: "citrus", swatches: ["#65a30d", "#ecfccb", "#ffffff"], available: false },
  { label: "Coral", value: "coral", swatches: ["#c2410c", "#ffedd5", "#ffffff"], available: false },
  { label: "Skyline", value: "skyline", swatches: ["#0284c7", "#e0f2fe", "#ffffff"], available: false },
  { label: "Plum", value: "plum", swatches: ["#86198f", "#fae8ff", "#ffffff"], available: false },
  { label: "Neutral Light", value: "neutral-light", swatches: ["#525252", "#f5f5f5", "#ffffff"], available: false },
] as const;

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
    date_format?: "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";
    canonical_name_fallback?: boolean;
  };
  home_card?: {
    icon?: DatasetIconName;
    background_image_ref?: string | null;
    short_description?: string;
    primary_metric_key?: string | null;
  };
  theme?: {
    preset?: "atlas-green";
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
  theme_preset: "" | "atlas-green";
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
  profile?: Partial<ProfileDraft>;
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

type DragItemKind = "field" | "group";

type CustomizationDragState = {
  kind: DragItemKind;
  sourceIndex: number;
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

  return {
    fieldHints: sortedFields.map((field) => {
      const hint = hintMap.get(field.name);
      return {
        field_name: field.name,
        display_label: hint?.display_label ?? "",
        explanatory_copy: hint?.explanatory_copy ?? "",
        group: hint?.group ?? "",
        hidden: hint?.hidden ?? false,
        required: requiredMap.get(field.name) ?? false,
      };
    }),
    groups: record.groups.map((group) => ({
      group_id: group.group_id,
      label: group.label,
      description: group.description ?? "",
    })),
  };
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

const sectionGridStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))",
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

const tagListStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
  margin: 0,
  padding: 0,
  listStyle: "none",
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

function getDatasetLabel(dataset?: DatasetListing) {
  return dataset?.title || dataset?.dataset_slug || "No dataset selected";
}

function getDatasetSelectorValue(dataset?: DatasetListing) {
  if (!dataset) {
    return "";
  }
  if (dataset.title && dataset.title !== dataset.dataset_slug) {
    return `${dataset.title} -- ${dataset.dataset_slug}`;
  }
  return dataset.dataset_slug;
}

function publicationStatusVariant(status: string): "published" | "pending" | "hidden" | "draft" | "not-published" {
  switch (status) {
    case "Published":
      return "published";
    case "Unpublished Changes":
      return "pending";
    case "Hidden":
      return "hidden";
    case "Draft":
      return "draft";
    case "Not Published":
    default:
      return "not-published";
  }
}

function publicationStatusTone(status: string): "success" | "warning" | "neutral" {
  switch (publicationStatusVariant(status)) {
    case "published":
      return "success";
    case "pending":
      return "warning";
    case "hidden":
    case "draft":
    case "not-published":
    default:
      return "neutral";
  }
}

type DatasetComboBoxProps = {
  datasets: DatasetListing[];
  disabled: boolean;
  query: string;
  selectedDataset?: DatasetListing;
  stateStatus: DatasetState["status"];
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

  function selectDataset(dataset: DatasetListing) {
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
    theme_preset: "atlas-green",
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

  return {
    ...form,
    schema_version: profile.schema_version || form.schema_version,
    display_title: profile.display?.title ?? "",
    display_subtitle: profile.display?.subtitle ?? "",
    problem_summary_title: profile.display?.problem_summary_title ?? "",
    problem_summary_body: profile.display?.problem_summary_body ?? "",
    source_name: profile.display?.source_name ?? "",
    source_url: profile.display?.source_url ?? "",
    release_date_label: profile.display?.release_date_label ?? "",
    date_format: profile.display?.date_format ?? "",
    canonical_name_fallback: profile.display?.canonical_name_fallback ?? true,
    home_card_icon: profile.home_card?.icon ?? "",
    background_image_ref: profile.home_card?.background_image_ref ?? "",
    short_description: profile.home_card?.short_description ?? "",
    primary_metric_key: profile.home_card?.primary_metric_key ?? "",
    theme_preset: profile.theme?.preset ?? "atlas-green",
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
}) {
  return (
    <label style={fieldStyle}>
      <span style={labelStyle}>{label}</span>
      {multiline ? (
        <textarea onChange={(event) => onChange(event.target.value)} style={textareaStyle} value={value} />
      ) : (
        <input onChange={(event) => onChange(event.target.value)} style={inputStyle} type="text" value={value} />
      )}
    </label>
  );
}

function DatasetTags({ tags }: { tags: string[] }) {
  if (tags.length === 0) {
    return <p style={mutedTextStyle}>No tags available.</p>;
  }

  return (
    <ul style={tagListStyle}>
      {tags.map((tag) => (
        <li key={tag} style={tagStyle}>
          {tag}
        </li>
      ))}
    </ul>
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

function extractModelCardText(modelCard: ModelCardPayload | null): string {
  if (!modelCard?.content) {
    return "";
  }
  try {
    const parsed = JSON.parse(modelCard.content) as Record<string, unknown>;
    const problemType = typeof parsed.problem_type === "string" ? parsed.problem_type : "";
    const target = typeof parsed.prediction_target === "string" ? parsed.prediction_target : "";
    const summary = typeof parsed.model_summary === "string" ? parsed.model_summary : "";
    return [problemType, target, summary].filter(Boolean).join(" | ");
  } catch {
    return modelCard.content.slice(0, 220);
  }
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

function ReadOnlyAtlasPanel({ readOnlyData }: { readOnlyData: ReadOnlyData }) {
  const dataset = stateValue(readOnlyData.dataset);
  const context = stateValue(readOnlyData.context);
  const metrics = stateValue(readOnlyData.metrics);
  const contract = stateValue(readOnlyData.contract);
  const modelCard = stateValue(readOnlyData.modelCard);
  const views = stateValue(readOnlyData.views) ?? [];
  const fields = contractFields(contract);
  const metricsList = metricKeys(metrics);

  return (
    <section aria-label="Read-only Atlas values" style={panelStyle}>
      <div>
        <h2 style={{ marginTop: 0 }}>Read-only Atlas context</h2>
        <p style={mutedTextStyle}>
          These values come from existing public endpoints and are not editable profile draft fields.
        </p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Dataset slug" value={dataset?.dataset_slug ?? ""} />
        <ReadOnlyField label="Canonical title" value={context?.title || dataset?.title || ""} />
        <ReadOnlyField label="Domain" value={context?.domain || dataset?.domain || ""} />
        <ReadOnlyField label="Visibility" value={dataset?.visibility ?? ""} />
        <ReadOnlyField label="Problem type" value={context?.problem_type ?? ""} />
        <ReadOnlyField label="Prediction target" value={context?.prediction_target_description ?? ""} />
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Contract fields" value={fields.length ? String(fields.length) : "Unavailable"} />
        <ReadOnlyField label="Metric keys" value={metricsList.length ? metricsList.join(", ") : "Unavailable"} />
        <ReadOnlyField label="Predict views" value={views.length ? views.map((view) => view.view_id).join(", ") : "Unavailable"} />
      </div>
      <ReadOnlyField label="Model card" value={extractModelCardText(modelCard) || "Unavailable"} />
      <div>
        <span style={labelStyle}>Tags</span>
        <DatasetTags tags={context?.tags ?? dataset?.tags ?? []} />
      </div>
    </section>
  );
}

function DraftStatusPanel({ draftState }: { draftState: DraftState }) {
  if (draftState.status === "ready") {
    return (
      <article style={readOnlyFieldStyle}>
        <strong>{draftState.draftExists ? "Draft loaded" : "No draft yet"}</strong>
        <p style={mutedTextStyle}>
          {draftState.draftExists
            ? "Editable fields were populated from the private/admin draft endpoint."
            : "Saving will create a draft through the private/admin endpoint."}
        </p>
      </article>
    );
  }
  if (draftState.status === "saved") {
    return (
      <article className="atlas-status-pill atlas-status-pill--success" role="status">
        Draft saved through the profile draft model.
      </article>
    );
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
        <strong>Draft unavailable</strong>
        <p style={mutedTextStyle}>{draftState.message}</p>
      </article>
    );
  }
  if (draftState.status === "loading") {
    return <p style={mutedTextStyle}>Loading draft profile...</p>;
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
  dataset,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  dataset?: DatasetListing;
}) {
  return (
    <TabWorkspace
      eyebrow="Public Content"
      helper="Edit only schema-backed presentation copy. Canonical dataset values remain read-only."
    >
      <div className="dataset-admin-card-grid dataset-admin-card-grid--two">
        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Public copy</h2>
            <p>Title, summary, and public explanation shown on Home and Dataset Detail.</p>
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="Display title" onChange={(value) => setField("display_title", value)} value={form.display_title} />
            <TextField label="Subtitle" onChange={(value) => setField("display_subtitle", value)} value={form.display_subtitle} />
            <TextField label="Problem summary title" onChange={(value) => setField("problem_summary_title", value)} value={form.problem_summary_title} />
          </div>
          <TextField
            label="Problem summary body"
            multiline
            onChange={(value) => setField("problem_summary_body", value)}
            value={form.problem_summary_body}
          />
        </Card>

        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Source and release</h2>
            <p>Public provenance labels without changing Atlas technical metadata.</p>
          </div>
          <div className="dataset-admin-form-grid">
            <TextField label="Source name" onChange={(value) => setField("source_name", value)} value={form.source_name} />
            <TextField label="Source URL" onChange={(value) => setField("source_url", value)} value={form.source_url} />
            <TextField label="Release date label" onChange={(value) => setField("release_date_label", value)} value={form.release_date_label} />
          </div>
          <FormRow helpText="Controls public date label rendering only." htmlFor="date-format" label="Date format">
            <select
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
          </FormRow>
          <label className="dataset-admin-toggle-row">
            <span className="dataset-admin-toggle-row__copy">
              <span>Canonical fallback</span>
              <small>Use {getDatasetLabel(dataset)} when no curated title is set.</small>
            </span>
            <span style={buttonRowStyle}>
              <input
                checked={form.canonical_name_fallback}
                onChange={(event) => setField("canonical_name_fallback", event.target.checked)}
                type="checkbox"
              />
            </span>
          </label>
        </Card>
      </div>
    </TabWorkspace>
  );
}

function MetadataCardTab({
  form,
  setField,
  readOnlyData,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  readOnlyData: ReadOnlyData;
}) {
  const metrics = stateValue(readOnlyData.metrics);
  const keys = metricKeys(metrics);
  const context = stateValue(readOnlyData.context);
  return (
    <TabWorkspace eyebrow="Metadata & Card" helper="Editable Home card fields store references and presentation copy only.">
      <div className="dataset-admin-card-grid dataset-admin-card-grid--split">
        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Icon bank</h2>
            <p>Select a controlled icon for the public Home card.</p>
          </div>
          <label className="sr-only" htmlFor="home-card-icon">
            Home card icon
          </label>
          <select
            id="home-card-icon"
            onChange={(event) => setField("home_card_icon", event.target.value as DraftForm["home_card_icon"])}
            style={inputStyle}
            value={form.home_card_icon}
          >
            <option value="">No curated icon</option>
            {HOME_CARD_ICON_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <div className="dataset-admin-icon-grid" role="list">
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
                  <span className="dataset-admin-icon-card__glyph">{label.slice(0, 1)}</span>
                  <span>{label}</span>
                </button>
              );
            })}
          </div>
        </Card>

        <Card className="dataset-admin-config-card">
          <div className="dataset-admin-card-heading">
            <h2>Home card controls</h2>
            <p>Curate preview copy and the score highlight while technical metadata stays locked.</p>
          </div>
          <FormRow helpText="Available keys come from Atlas metrics." htmlFor="primary-metric-key" label="Primary metric key">
            <select
              id="primary-metric-key"
              onChange={(event) => setField("primary_metric_key", event.target.value)}
              style={inputStyle}
              value={form.primary_metric_key}
            >
              <option value="">No highlighted metric</option>
              {keys.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </FormRow>
          <TextField label="Background image reference" onChange={(value) => setField("background_image_ref", value)} value={form.background_image_ref} />
          <TextField label="Short Home card description" onChange={(value) => setField("short_description", value)} value={form.short_description} />
          <div className="dataset-admin-locked-grid">
            <ReadOnlyField label="Problem type" value={context?.problem_type ?? ""} />
            <div className="dataset-admin-locked-card" aria-disabled="true">
              <Badge>Locked</Badge>
              <strong>Technical metadata</strong>
              <span>Problem type options are visible as read-only Atlas state.</span>
            </div>
          </div>
        </Card>

        <Card className="dataset-admin-preview-card">
          <div className="dataset-admin-card-heading">
            <h2>Home card preview</h2>
            <p>Uses the same shared card projection as Live Preview.</p>
          </div>
          <DatasetCard
            {...projectHomeCardPreview(
              stateValue(readOnlyData.dataset) ?? undefined,
              {
                ...form,
                home_card_icon: form.home_card_icon as "" | "telecom" | "bank" | "generic",
              },
              context,
            )}
          />
        </Card>
      </div>
    </TabWorkspace>
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
    <TabWorkspace eyebrow="Theme Preset" helper="The current schema supports only Atlas Green; other prototype presets are locked.">
      <Card className="dataset-admin-config-card">
        <label className="dataset-admin-native-select">
          <span style={labelStyle}>Theme preset</span>
        <select
          onChange={(event) => setField("theme_preset", event.target.value as DraftForm["theme_preset"])}
          style={inputStyle}
          value={form.theme_preset}
        >
          <option value="">No curated theme</option>
          <option value="atlas-green">Atlas Green</option>
        </select>
      </label>
        <div className="dataset-admin-theme-grid">
          {THEME_PRESET_CARDS.map((preset) => {
            const selected = String(form.theme_preset) === preset.value;
            return (
              <button
                aria-disabled={!preset.available}
                aria-pressed={preset.available ? selected : undefined}
                className={[
                  "dataset-admin-theme-card",
                  selected ? "is-selected" : "",
                  !preset.available ? "is-locked" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={!preset.available}
                key={preset.value}
                onClick={() => {
                  if (preset.available) {
                    setField("theme_preset", preset.value as DraftForm["theme_preset"]);
                  }
                }}
                type="button"
              >
                <span className="dataset-admin-theme-card__swatches" aria-hidden="true">
                  {preset.swatches.map((color) => (
                    <span key={color} style={{ background: color }} />
                  ))}
                </span>
                <strong>{preset.label}</strong>
                <span>{preset.available ? "Selectable schema preset" : "Locked until schema support exists"}</span>
                {!preset.available ? <Badge>Locked</Badge> : null}
              </button>
            );
          })}
        </div>
      </Card>
    </TabWorkspace>
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

function CustomizationEditor({
  draft,
  onUpdateDraft,
}: {
  draft: CustomizationEditorDraft;
  onUpdateDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void;
}) {
  const [dragState, setDragState] = useState<CustomizationDragState | null>(null);
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

  function updateFieldHint(index: number, patch: Partial<FieldHintDraft>) {
    onUpdateDraft((current) => ({
      ...current,
      fieldHints: current.fieldHints.map((field, i) => (i === index ? { ...field, ...patch } : field)),
    }));
  }

  function moveFieldHint(index: number, direction: -1 | 1) {
    onUpdateDraft((current) => ({ ...current, fieldHints: moveItem(current.fieldHints, index, direction) }));
  }

  function moveGroup(index: number, direction: -1 | 1) {
    onUpdateDraft((current) => ({ ...current, groups: moveItem(current.groups, index, direction) }));
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
    onUpdateDraft((current) => ({
      groups: current.groups.filter((group) => group.group_id !== groupId),
      fieldHints: current.fieldHints.map((field) => (field.group === groupId ? { ...field, group: "" } : field)),
    }));
  }

  function getTargetIndex(kind: DragItemKind, clientX: number, clientY: number, fallbackIndex: number) {
    const element = document
      .elementFromPoint(clientX, clientY)
      ?.closest<HTMLElement>("[data-customization-drag-kind][data-customization-drag-index]");
    if (!element || element.dataset.customizationDragKind !== kind) {
      return fallbackIndex;
    }
    const targetIndex = Number(element.dataset.customizationDragIndex);
    return Number.isInteger(targetIndex) ? targetIndex : fallbackIndex;
  }

  function startDrag(
    event: ReactPointerEvent<HTMLButtonElement>,
    kind: DragItemKind,
    sourceIndex: number,
    label: string,
  ) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragState({
      kind,
      sourceIndex,
      targetIndex: sourceIndex,
      pointerX: event.clientX,
      pointerY: event.clientY,
      label,
    });
  }

  function updateDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragState) return;
    event.preventDefault();
    const targetIndex = getTargetIndex(dragState.kind, event.clientX, event.clientY, dragState.targetIndex);
    setDragState({
      ...dragState,
      targetIndex,
      pointerX: event.clientX,
      pointerY: event.clientY,
    });
  }

  function finishDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragState) return;
    event.preventDefault();
    const finalTargetIndex = getTargetIndex(dragState.kind, event.clientX, event.clientY, dragState.targetIndex);
    const { kind, sourceIndex } = dragState;
    setDragState(null);

    onUpdateDraft((current) => {
      if (kind === "field") {
        return { ...current, fieldHints: moveItemToIndex(current.fieldHints, sourceIndex, finalTargetIndex) };
      }
      return { ...current, groups: moveItemToIndex(current.groups, sourceIndex, finalTargetIndex) };
    });
  }

  function cancelDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragState) return;
    event.preventDefault();
    setDragState(null);
  }

  function getDragItemStyle(kind: DragItemKind, index: number): CSSProperties {
    const isSource = dragState?.kind === kind && dragState.sourceIndex === index;
    const isTarget = dragState?.kind === kind && dragState.targetIndex === index && dragState.sourceIndex !== index;
    return {
      ...panelStyle,
      padding: "var(--atlas-space-3)",
      ...(isSource ? dragSourceStyle : {}),
      ...(isTarget ? dragTargetStyle : {}),
    };
  }

  return (
    <div className="dataset-admin-builder">
      <section aria-label="Groups" className="dataset-admin-builder__canvas">
        <div className="dataset-admin-builder__toolbar">
          <div>
            <span style={labelStyle}>Public form layout canvas</span>
            <p style={mutedTextStyle}>Group cards and the explicit No subgroup drop area define presentation order.</p>
          </div>
          <button onClick={addGroup} style={secondaryButtonStyle} type="button">
            Add group
          </button>
        </div>
        <div className="dataset-admin-no-group-zone">
          <strong>No subgroup</strong>
          <span>Fields with no selected group render in the ungrouped area.</span>
        </div>
        {draft.groups.length === 0 ? (
          <p style={mutedTextStyle}>No groups defined. Fields without a group render ungrouped.</p>
        ) : (
          <div className="dataset-admin-builder__stack">
            {draft.groups.map((group, index) => (
              <div
                className="dataset-admin-builder-card"
                data-customization-drag-index={index}
                data-customization-drag-kind="group"
                key={group.group_id}
                style={getDragItemStyle("group", index)}
              >
                <div className="dataset-admin-builder-card__head">
                  <button
                    aria-label={`Drag group ${group.label || group.group_id || index + 1}`}
                    onPointerCancel={cancelDrag}
                    onPointerDown={(event) => startDrag(event, "group", index, group.label || group.group_id || `Group ${index + 1}`)}
                    onPointerMove={updateDrag}
                    onPointerUp={finishDrag}
                    style={dragHandleStyle}
                    type="button"
                  >
                    Drag
                  </button>
                  <button
                    disabled={index === 0}
                    onClick={() => moveGroup(index, -1)}
                    style={index === 0 ? disabledButtonStyle : secondaryButtonStyle}
                    type="button"
                  >
                    Move up
                  </button>
                  <button
                    disabled={index === draft.groups.length - 1}
                    onClick={() => moveGroup(index, 1)}
                    style={index === draft.groups.length - 1 ? disabledButtonStyle : secondaryButtonStyle}
                    type="button"
                  >
                    Move down
                  </button>
                  <button onClick={() => removeGroup(group.group_id)} style={secondaryButtonStyle} type="button">
                    Remove
                  </button>
                  <Badge>{draft.fieldHints.filter((field) => field.group === group.group_id).length} fields</Badge>
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
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section aria-label="Field presentation" className="dataset-admin-builder__bank">
        <div>
          <span style={labelStyle}>Field bank</span>
          <p style={mutedTextStyle}>Each chip preserves its contract field and can only change public presentation metadata.</p>
        </div>
        {draft.fieldHints.length === 0 ? (
          <p style={mutedTextStyle}>Contract field list unavailable.</p>
        ) : (
          <div className="dataset-admin-builder__stack">
            {draft.fieldHints.map((field, index) => (
              <div
                className={["dataset-admin-builder-card", field.required ? "is-required" : ""].filter(Boolean).join(" ")}
                data-customization-drag-index={index}
                data-customization-drag-kind="field"
                key={field.field_name}
                style={getDragItemStyle("field", index)}
              >
                <div className="dataset-admin-builder-card__head">
                  <strong>{field.field_name}</strong>
                  {field.required && <span style={tagStyle}>required</span>}
                  <button
                    aria-label={`Drag field ${field.display_label || field.field_name}`}
                    onPointerCancel={cancelDrag}
                    onPointerDown={(event) => startDrag(event, "field", index, field.display_label || field.field_name)}
                    onPointerMove={updateDrag}
                    onPointerUp={finishDrag}
                    style={dragHandleStyle}
                    type="button"
                  >
                    Drag
                  </button>
                  <button
                    disabled={index === 0}
                    onClick={() => moveFieldHint(index, -1)}
                    style={index === 0 ? disabledButtonStyle : secondaryButtonStyle}
                    type="button"
                  >
                    Move up
                  </button>
                  <button
                    disabled={index === draft.fieldHints.length - 1}
                    onClick={() => moveFieldHint(index, 1)}
                    style={index === draft.fieldHints.length - 1 ? disabledButtonStyle : secondaryButtonStyle}
                    type="button"
                  >
                    Move down
                  </button>
                </div>
                <div style={twoColumnGridStyle}>
                  <TextField
                    label="Display label"
                    onChange={(value) => updateFieldHint(index, { display_label: value })}
                    value={field.display_label}
                  />
                  <label style={fieldStyle}>
                    <span style={labelStyle}>Group</span>
                    <select
                      onChange={(event) => updateFieldHint(index, { group: event.target.value })}
                      style={inputStyle}
                      value={field.group}
                    >
                      <option value="">No group</option>
                      {draft.groups.map((group) => (
                        <option key={group.group_id} value={group.group_id}>
                          {group.label || group.group_id}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label style={fieldStyle}>
                  <span style={labelStyle}>Explanatory copy</span>
                  <textarea
                    onChange={(event) => updateFieldHint(index, { explanatory_copy: event.target.value })}
                    style={textareaStyle}
                    value={field.explanatory_copy}
                  />
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "var(--atlas-space-2)" }}>
                  <input
                    checked={field.hidden}
                    disabled={field.required}
                    onChange={(event) => {
                      if (field.required) return;
                      updateFieldHint(index, { hidden: event.target.checked });
                    }}
                    type="checkbox"
                  />
                  <span style={mutedTextStyle}>
                    {field.required ? "Required fields cannot be hidden." : "Hidden"}
                  </span>
                </label>
              </div>
            ))}
          </div>
        )}
      </section>
      {dragState && (
        <div
          aria-hidden="true"
          style={{
            ...dragGhostStyle,
            left: dragState.pointerX,
            top: dragState.pointerY,
          }}
        >
          {dragState.label}
        </div>
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
            <button disabled={!draft} onClick={onSaveCustomization} style={!draft ? disabledButtonStyle : actionButtonStyle} type="button">
              Save customization
            </button>
          </div>
        </div>

        <CustomizationStatusPanel state={customizationEditorState} />

        {draft && <CustomizationEditor draft={draft} onUpdateDraft={onUpdateDraft} />}
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

function publicationMessage(publicationState: PublicationState): string {
  switch (publicationState.status) {
    case "published":
      return publicationState.publishedAt ? `Published at ${publicationState.publishedAt}.` : "Published snapshot updated.";
    case "visibility_saved":
      return publicationState.visible ? "Latest published snapshot is visible publicly." : "Latest published snapshot is hidden publicly.";
    case "publishing":
      return "Publishing saved draft snapshot...";
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
      <PerformanceSummary metrics={metrics ?? {}} emphasizedMetricKey={form.primary_metric_key} />
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
      <div className="dataset-admin-preview-stage" data-theme-preset={form.theme_preset || "atlas-green"}>
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

  switch (selectedTab) {
    case "metadata-card":
      return <MetadataCardTab form={form} readOnlyData={readOnlyData} setField={setField} />;
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
    case "publishing":
      {
        const publishDisabledReason = !selectedSlug
          ? "Select a dataset before publishing."
          : !lastBackendDraft
          ? "Load or save a private draft before publishing changes."
          : hasUnsavedDraftChanges
          ? "Save Draft before publishing; Publish Changes uses the saved backend draft, not unsaved form edits."
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
      return <PublicContentTab dataset={dataset} form={form} setField={setField} />;
  }
}

export default function DatasetAdminPage() {
  const [state, setState] = useState<DatasetState>({ status: "loading" });
  const [selectedSlug, setSelectedSlug] = useState("");
  const [datasetQuery, setDatasetQuery] = useState("");
  const [selectedTab, setSelectedTab] = useState(adminTabs[0].id);
  const [draftState, setDraftState] = useState<DraftState>({
    status: "idle",
    message: "Load the private/admin draft to edit profile fields.",
  });
  const [draftForm, setDraftForm] = useState<DraftForm>(emptyDraftForm());
  const [readOnlyData, setReadOnlyData] = useState<ReadOnlyData>(emptyReadOnlyData);
  const [customizationEditorState, setCustomizationEditorState] = useState<CustomizationEditorState>(
    emptyCustomizationEditorState,
  );
  const [publicationState, setPublicationState] = useState<PublicationState>(emptyPublicationState);
  const [lastPublishedAt, setLastPublishedAt] = useState<string | undefined>(undefined);

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
  }, []);

  useEffect(() => {
    if (!selectedSlug) {
      setReadOnlyData(emptyReadOnlyData);
      setDraftForm(emptyDraftForm());
      setCustomizationEditorState(emptyCustomizationEditorState);
      setPublicationState(emptyPublicationState);
      setLastPublishedAt(undefined);
      return;
    }

    setDraftForm((current) => ({ ...emptyDraftForm(selectedSlug), schema_version: current.schema_version || "1.0.0" }));
    setDraftState({
      status: "idle",
      message: "Load the private/admin draft before saving profile edits.",
    });
    setCustomizationEditorState(emptyCustomizationEditorState);
    setPublicationState(emptyPublicationState);
    setLastPublishedAt(undefined);

    const controller = new AbortController();
    setReadOnlyData({
      dataset: { status: "loading" },
      context: { status: "loading" },
      contract: { status: "loading" },
      metrics: { status: "loading" },
      modelCard: { status: "loading" },
      visualizations: { status: "loading" },
      views: { status: "loading" },
    });

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

    return () => controller.abort();
  }, [selectedSlug]);

  const datasets = state.status === "ready" ? state.datasets : [];
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.dataset_slug === selectedSlug),
    [datasets, selectedSlug],
  );
  const currentProfile = selectedSlug ? profileFromForm(draftForm, selectedSlug) : null;
  const lastBackendDraft = backendDraftProfile(draftState);
  const hasUnsavedDraftChanges = Boolean(currentProfile && lastBackendDraft && !sameProfile(currentProfile, lastBackendDraft));
  const publishedProfile = publicationState.publishedProfile;
  const hasPublishedSnapshot = Boolean(publishedProfile);
  const hasUnpublishedChanges = Boolean(currentProfile && publishedProfile && !sameProfile(currentProfile, publishedProfile));
  const headerPublicationStatus = publishingStatusLabel({
    draftState,
    hasPublishedSnapshot,
    hasUnpublishedChanges,
    hasUnsavedDraftChanges,
    visible: publicationState.visible,
  });

  function selectDatasetFromQuery(value: string) {
    setDatasetQuery(value);
    const match = datasets.find(
      (dataset) => dataset.dataset_slug === value || getDatasetSelectorValue(dataset).toLowerCase() === value.trim().toLowerCase(),
    );
    if (match && match.dataset_slug !== selectedSlug) {
      setSelectedSlug(match.dataset_slug);
    }
  }

  function normalizeDatasetQuery() {
    setDatasetQuery(getDatasetSelectorValue(selectedDataset));
  }

  function setField<K extends keyof DraftForm>(key: K, value: DraftForm[K]) {
    setDraftForm((current) => ({ ...current, [key]: value }));
  }

  function loadDraft() {
    if (!selectedSlug) {
      return;
    }

    const controller = new AbortController();
    setDraftState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/profile-draft`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (response.status === 404) {
          setDraftState({
            status: "unavailable",
            message: "Draft endpoint unavailable for this private admin session. Confirm API configuration.",
          });
          return null;
        }
        if (!response.ok) {
          setDraftState({ status: "unavailable", message: "Profile draft could not be loaded from the private admin API." });
          return null;
        }
        return response.json() as Promise<{ draft_exists: boolean; profile: ProfileDraft | null }>;
      })
      .then((data) => {
        if (!data) {
          return;
        }
        setDraftForm(formFromProfile(data.profile, selectedSlug));
        setDraftState({ status: "ready", draftExists: data.draft_exists, profile: data.profile });
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setDraftState({ status: "unavailable", message: "Profile draft could not be loaded. Check private admin API reachability." });
        }
      });
  }

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
            message: "Draft endpoint unavailable for this private admin session. Confirm API configuration.",
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
          setDraftState({ status: "invalid", errors: result.body.errors ?? [{ message: "Profile draft failed validation." }] });
          return;
        }
        const savedProfile = result.body.profile ?? profile;
        setDraftForm(formFromProfile(savedProfile, selectedSlug));
        setDraftState({ status: "saved", profile: savedProfile });
      })
      .catch(() => {
        setDraftState({ status: "unavailable", message: "Profile draft could not be saved. Check private admin API reachability." });
      });
  }

  const boundPredictViewId = draftForm.bound_predict_view_id;

  function publishChanges() {
    if (!selectedSlug) {
      return;
    }

    const lastBackendDraft = backendDraftProfile(draftState);
    const currentProfile = profileFromForm(draftForm, selectedSlug);
    if (!lastBackendDraft || !sameProfile(lastBackendDraft, currentProfile)) {
      setPublicationState((current) => ({
        status: "unavailable",
        visible: current.visible,
        publishedProfile: current.publishedProfile,
        message: "Save Draft before publishing; Publish Changes uses the saved backend draft.",
      }));
      return;
    }

    setPublicationState((current) => ({
      status: "publishing",
      visible: current.visible,
      publishedProfile: current.publishedProfile,
    }));
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/publish`, {
      method: "PUT",
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
        return response.json().then((body: { published?: boolean; snapshot?: PublishSnapshot | null; errors?: DraftError[] }) => ({
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
        const publishedProfile = profileFromSnapshot(result.body.snapshot, selectedSlug) ?? currentProfile;
        setPublicationState((current) => ({
          status: "published",
          visible: current.visible,
          publishedProfile,
          publishedAt: result.body.snapshot?.published_at,
        }));
        setLastPublishedAt(result.body.snapshot?.published_at);
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
          <h1 id="dataset-admin-title">Dataset — {getDatasetLabel(selectedDataset)}</h1>
          <p className="summary">
            Curate the selected dataset's public presentation profile while Atlas technical values stay read-only.
          </p>
        </div>

        <div className="dataset-admin-header-actions">
          <DatasetComboBox
            datasets={datasets}
            disabled={state.status !== "ready" || datasets.length === 0}
            onNormalize={normalizeDatasetQuery}
            onQueryChange={selectDatasetFromQuery}
            query={datasetQuery}
            selectedDataset={selectedDataset}
            stateStatus={state.status}
          />
          <StatusPill
            aria-label="Publication status"
            className="dataset-admin-status-pill"
            tone={publicationStatusTone(headerPublicationStatus)}
            variant={publicationStatusVariant(headerPublicationStatus)}
          >
            {headerPublicationStatus}
          </StatusPill>

          <button
            disabled={!selectedSlug || draftState.status === "loading"}
            onClick={loadDraft}
            style={secondaryButtonStyle}
            type="button"
          >
            Load draft
          </button>
        </div>
      </header>

      {state.status === "error" && (
        <article role="status" style={alertStyle}>
          <strong>Dataset listing unavailable</strong>
          <p style={mutedTextStyle}>{state.message}</p>
        </article>
      )}

      <ReadOnlyAtlasPanel readOnlyData={readOnlyData} />

      <section aria-label="Dataset profile workspace" style={panelStyle}>
        <DraftStatusPanel draftState={draftState} />
        <div style={buttonRowStyle}>
          <button
            disabled={!selectedSlug || draftState.status === "loading"}
            onClick={saveDraft}
            style={!selectedSlug || draftState.status === "loading" ? disabledButtonStyle : actionButtonStyle}
            type="button"
          >
            Save draft
          </button>
          <span style={mutedTextStyle}>Saves only the schema-backed draft; publishing controls are in the Publishing tab.</span>
        </div>
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
            saveDraft,
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
