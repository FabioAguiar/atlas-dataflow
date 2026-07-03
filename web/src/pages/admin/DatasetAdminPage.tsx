import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Tabs, type TabItem } from "../../components/ui";
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
    icon?: "telecom" | "bank" | "generic";
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
  home_card_icon: "" | "telecom" | "bank" | "generic";
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

const adminTabs: TabItem[] = [
  { id: "public-content", label: "Public Content" },
  { id: "metadata-card", label: "Metadata & Card" },
  { id: "theme-preset", label: "Theme Preset" },
  { id: "inference-form", label: "Inference Form" },
  { id: "result-card", label: "Result Card" },
  { id: "publishing", label: "Publishing" },
  { id: "live-preview", label: "Live Preview" },
];

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-5)",
};

const headerStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
};

const headerControlsStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))",
  alignItems: "end",
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
  gap: "var(--atlas-space-4)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-5)",
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

const previewCardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  background: "var(--atlas-color-canvas)",
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

function getDatasetLabel(dataset?: DatasetListing) {
  return dataset?.title || dataset?.dataset_slug || "No dataset selected";
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

async function fetchJson<T>(path: string, signal: AbortSignal, headers?: HeadersInit): Promise<SectionState<T>> {
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, { headers, signal });
    if (!response.ok) {
      return { status: "unavailable", message: `Unavailable (${response.status})` };
    }
    const data = (await response.json()) as T;
    return { status: "ready", data };
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      return { status: "unavailable", message: "Request cancelled." };
    }
    return { status: "unavailable", message: "Request failed." };
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
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Public Content</h2>
        <p style={mutedTextStyle}>Edit only schema-backed presentation copy. Canonical dataset values remain read-only.</p>
      </div>
      <div style={twoColumnGridStyle}>
        <TextField label="Display title" onChange={(value) => setField("display_title", value)} value={form.display_title} />
        <TextField label="Subtitle" onChange={(value) => setField("display_subtitle", value)} value={form.display_subtitle} />
        <TextField label="Problem summary title" onChange={(value) => setField("problem_summary_title", value)} value={form.problem_summary_title} />
        <TextField label="Source name" onChange={(value) => setField("source_name", value)} value={form.source_name} />
        <TextField label="Source URL" onChange={(value) => setField("source_url", value)} value={form.source_url} />
        <TextField label="Release date label" onChange={(value) => setField("release_date_label", value)} value={form.release_date_label} />
      </div>
      <TextField
        label="Problem summary body"
        multiline
        onChange={(value) => setField("problem_summary_body", value)}
        value={form.problem_summary_body}
      />
      <div style={sectionGridStyle}>
        <label style={fieldStyle}>
          <span style={labelStyle}>Date format</span>
          <select
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
        <label style={{ ...readOnlyFieldStyle, alignContent: "center" }}>
          <span style={labelStyle}>Canonical fallback</span>
          <span style={buttonRowStyle}>
            <input
              checked={form.canonical_name_fallback}
              onChange={(event) => setField("canonical_name_fallback", event.target.checked)}
              type="checkbox"
            />
            Use {getDatasetLabel(dataset)} when no curated title is set
          </span>
        </label>
      </div>
    </>
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
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Metadata & Card</h2>
        <p style={mutedTextStyle}>Editable Home card fields store references and presentation copy only.</p>
      </div>
      <div style={sectionGridStyle}>
        <label style={fieldStyle}>
          <span style={labelStyle}>Home card icon</span>
          <select
            onChange={(event) => setField("home_card_icon", event.target.value as DraftForm["home_card_icon"])}
            style={inputStyle}
            value={form.home_card_icon}
          >
            <option value="">No curated icon</option>
            <option value="telecom">Telecom</option>
            <option value="bank">Bank</option>
            <option value="generic">Generic</option>
          </select>
        </label>
        <label style={fieldStyle}>
          <span style={labelStyle}>Primary metric key</span>
          <select
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
        </label>
      </div>
      <div style={twoColumnGridStyle}>
        <TextField label="Background image reference" onChange={(value) => setField("background_image_ref", value)} value={form.background_image_ref} />
        <TextField label="Short Home card description" onChange={(value) => setField("short_description", value)} value={form.short_description} />
      </div>
    </>
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
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Theme Preset</h2>
        <p style={mutedTextStyle}>The current schema supports only the bounded Atlas Green preset.</p>
      </div>
      <label style={fieldStyle}>
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
    </>
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
    <div style={{ display: "grid", gap: "var(--atlas-space-4)" }}>
      <section aria-label="Groups" style={readOnlyFieldStyle}>
        <div style={buttonRowStyle}>
          <span style={labelStyle}>Groups</span>
          <button onClick={addGroup} style={secondaryButtonStyle} type="button">
            Add group
          </button>
        </div>
        {draft.groups.length === 0 ? (
          <p style={mutedTextStyle}>No groups defined. Fields without a group render ungrouped.</p>
        ) : (
          <div style={{ display: "grid", gap: "var(--atlas-space-3)" }}>
            {draft.groups.map((group, index) => (
              <div
                data-customization-drag-index={index}
                data-customization-drag-kind="group"
                key={group.group_id}
                style={getDragItemStyle("group", index)}
              >
                <div style={buttonRowStyle}>
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
                </div>
                <div style={twoColumnGridStyle}>
                  <TextField label="Group ID" onChange={(value) => updateGroup(index, { group_id: value })} value={group.group_id} />
                  <TextField label="Label" onChange={(value) => updateGroup(index, { label: value })} value={group.label} />
                </div>
                <TextField
                  label="Description"
                  onChange={(value) => updateGroup(index, { description: value })}
                  value={group.description}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <section aria-label="Field presentation" style={readOnlyFieldStyle}>
        <span style={labelStyle}>Fields</span>
        {draft.fieldHints.length === 0 ? (
          <p style={mutedTextStyle}>Contract field list unavailable.</p>
        ) : (
          <div style={{ display: "grid", gap: "var(--atlas-space-3)" }}>
            {draft.fieldHints.map((field, index) => (
              <div
                data-customization-drag-index={index}
                data-customization-drag-kind="field"
                key={field.field_name}
                style={getDragItemStyle("field", index)}
              >
                <div style={buttonRowStyle}>
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
                    onChange={(event) => updateFieldHint(index, { hidden: event.target.checked })}
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
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Inference Form</h2>
        <p style={mutedTextStyle}>
          Edit the grouping, ordering, and visibility of the bound predict view's fields. Contracts remain the
          source of truth for field existence and validation; this editor can only organize presentation.
        </p>
      </div>
      <label style={fieldStyle}>
        <span style={labelStyle}>Bound predict view</span>
        <select
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
      </label>

      <CustomizationStatusPanel state={customizationEditorState} />

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

      {draft && <CustomizationEditor draft={draft} onUpdateDraft={onUpdateDraft} />}
    </>
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
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Result Card</h2>
        <p style={mutedTextStyle}>Edit public presentation labels only; model behavior remains read-only Atlas state.</p>
      </div>
      <div style={twoColumnGridStyle}>
        <TextField label="Probability label" onChange={(value) => setField("probability_label", value)} value={form.probability_label} />
        <TextField label="Submit button label" onChange={(value) => setField("submit_button_label", value)} value={form.submit_button_label} />
        <TextField label="Model label" onChange={(value) => setField("model_label", value)} value={form.model_label} />
        <label style={fieldStyle}>
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
        <TextField label="High badge label" onChange={(value) => setField("badge_high", value)} value={form.badge_high} />
        <TextField label="Medium badge label" onChange={(value) => setField("badge_medium", value)} value={form.badge_medium} />
        <TextField label="Low badge label" onChange={(value) => setField("badge_low", value)} value={form.badge_low} />
      </div>
    </>
  );
}

function PublishingTab({ draftState }: { draftState: DraftState }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Publishing</h2>
        <p style={mutedTextStyle}>
          M35-02 saves a draft only. Publishing, snapshots, release mutation and visibility changes remain unavailable.
        </p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Profile draft" value={draftState.status === "saved" ? "Saved" : "Editable draft"} />
        <ReadOnlyField label="Public visibility" value="No semantic change from this screen" />
        <ReadOnlyField label="Release artifacts" value="Read-only" />
      </div>
      <div style={buttonRowStyle}>
        <button disabled style={disabledButtonStyle} type="button">
          Publish disabled
        </button>
        <button disabled style={disabledButtonStyle} type="button">
          Snapshot disabled
        </button>
      </div>
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
  const preview = projectDatasetDetailPreview(dataset, form, context, previewContract, metrics);
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

function LivePreviewTab({
  dataset,
  form,
  readOnlyData,
  selectedSlug,
  customizationEditorState,
}: {
  dataset?: DatasetListing;
  form: DraftForm;
  readOnlyData: ReadOnlyData;
  selectedSlug: string;
  customizationEditorState: CustomizationEditorState;
}) {
  const [previewMode, setPreviewMode] = useState<"detail" | "card" | "result" | "form">("detail");

  const previewModeLabels: Record<"detail" | "card" | "result" | "form", string> = {
    detail: "Dataset detail",
    card: "Home card",
    result: "Result card",
    form: "Inference form layout",
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
      </div>
      <div aria-label="Preview mode" style={buttonRowStyle}>
        {(["detail", "card", "result", "form"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setPreviewMode(mode)}
            style={previewMode === mode ? secondaryButtonStyle : disabledButtonStyle}
            type="button"
          >
            {previewModeLabels[mode]}
          </button>
        ))}
      </div>
      <div style={previewCardStyle} data-theme-preset={form.theme_preset || "atlas-green"}>
        {previewMode === "card" && (
          <div style={{ maxWidth: "22rem" }}>
            <DatasetCard {...projectHomeCardPreview(dataset, form)} />
          </div>
        )}
        {previewMode === "detail" && (
          <DatasetDetailLivePreview dataset={dataset} form={form} readOnlyData={readOnlyData} />
        )}
        {previewMode === "result" && <ResultCardLivePreview form={form} />}
        {previewMode === "form" && (
          <FormLayoutLivePreview
            customizationEditorState={customizationEditorState}
            readOnlyData={readOnlyData}
            selectedSlug={selectedSlug}
          />
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
  onSaveCustomization: () => void,
  onUpdateCustomizationDraft: (updater: (draft: CustomizationEditorDraft) => CustomizationEditorDraft) => void,
) {
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
      return <PublishingTab draftState={draftState} />;
    case "live-preview":
      return (
        <LivePreviewTab
          customizationEditorState={customizationEditorState}
          dataset={dataset}
          form={form}
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
  const [selectedTab, setSelectedTab] = useState(adminTabs[0].id);
  const [adminToken, setAdminToken] = useState("");
  const [draftState, setDraftState] = useState<DraftState>({
    status: "idle",
    message: "Enter an operator token and load a draft to edit profile fields.",
  });
  const [draftForm, setDraftForm] = useState<DraftForm>(emptyDraftForm());
  const [readOnlyData, setReadOnlyData] = useState<ReadOnlyData>(emptyReadOnlyData);
  const [customizationEditorState, setCustomizationEditorState] = useState<CustomizationEditorState>(
    emptyCustomizationEditorState,
  );

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
      return;
    }

    setDraftForm((current) => ({ ...emptyDraftForm(selectedSlug), schema_version: current.schema_version || "1.0.0" }));
    setDraftState({
      status: "idle",
      message: "Load the private/admin draft before saving profile edits.",
    });
    setCustomizationEditorState(emptyCustomizationEditorState);

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
    () => datasets.find((dataset) => dataset.dataset_slug === selectedSlug) ?? datasets[0],
    [datasets, selectedSlug],
  );

  function setField<K extends keyof DraftForm>(key: K, value: DraftForm[K]) {
    setDraftForm((current) => ({ ...current, [key]: value }));
  }

  function loadDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSlug) {
      return;
    }
    const token = adminToken.trim();
    if (!token) {
      setDraftState({ status: "unavailable", message: "Enter the operator token to request the private profile draft." });
      return;
    }

    const controller = new AbortController();
    setDraftState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/profile-draft`, {
      headers: { "X-Admin-Token": token },
      signal: controller.signal,
    })
      .then((response) => {
        if (response.status === 404) {
          setDraftState({
            status: "unavailable",
            message: "Draft endpoint unavailable for this session. Confirm the operator token and API configuration.",
          });
          return null;
        }
        if (!response.ok) {
          setDraftState({ status: "unavailable", message: "Profile draft could not be loaded from the admin API." });
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
          setDraftState({ status: "unavailable", message: "Profile draft could not be loaded. Check API reachability." });
        }
      });
  }

  function saveDraft() {
    if (!selectedSlug) {
      return;
    }
    const token = adminToken.trim();
    if (!token) {
      setDraftState({ status: "unavailable", message: "Enter the operator token before saving the profile draft." });
      return;
    }

    const profile = profileFromForm(draftForm, selectedSlug);
    setDraftState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/profile-draft`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": token,
      },
      body: JSON.stringify(profile),
    })
      .then((response) => {
        if (response.status === 404) {
          setDraftState({
            status: "unavailable",
            message: "Draft endpoint unavailable for this session. Confirm the operator token and API configuration.",
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
        setDraftState({ status: "unavailable", message: "Profile draft could not be saved. Check API reachability." });
      });
  }

  const boundPredictViewId = draftForm.bound_predict_view_id;

  useEffect(() => {
    if (!boundPredictViewId) {
      setCustomizationEditorState({ status: "no_view_bound" });
      return;
    }
    setCustomizationEditorState({
      status: "idle",
      message: "Enter an operator token and load the customization for the bound predict view.",
    });
  }, [boundPredictViewId]);

  function loadCustomization() {
    if (!selectedSlug || !boundPredictViewId) {
      return;
    }
    const token = adminToken.trim();
    if (!token) {
      setCustomizationEditorState({
        status: "unavailable",
        message: "Enter the operator token to request the predict view customization.",
      });
      return;
    }

    const contractState = stateValue(readOnlyData.contract);
    const fields = contractFields(contractState);

    setCustomizationEditorState({ status: "loading" });
    fetch(
      `${apiBaseUrl}/admin/datasets/${encodeURIComponent(selectedSlug)}/views/${encodeURIComponent(boundPredictViewId)}/customization`,
      { headers: { "X-Admin-Token": token } },
    )
      .then((response) => {
        if (response.status === 404) {
          setCustomizationEditorState({
            status: "unavailable",
            message: "Customization endpoint unavailable for this session. Confirm the operator token and API configuration.",
          });
          return null;
        }
        if (!response.ok) {
          setCustomizationEditorState({ status: "unavailable", message: "Customization could not be loaded from the admin API." });
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
        setCustomizationEditorState({ status: "unavailable", message: "Customization could not be loaded. Check API reachability." });
      });
  }

  function saveCustomization() {
    if (!selectedSlug || !boundPredictViewId) {
      return;
    }
    if (customizationEditorState.status !== "ready" && customizationEditorState.status !== "saved" && customizationEditorState.status !== "invalid") {
      return;
    }
    const token = adminToken.trim();
    if (!token) {
      setCustomizationEditorState({
        status: "unavailable",
        message: "Enter the operator token before saving the customization.",
      });
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
        headers: { "Content-Type": "application/json", "X-Admin-Token": token },
        body: JSON.stringify(payload),
      },
    )
      .then((response) => {
        if (response.status === 404) {
          setCustomizationEditorState({
            status: "unavailable",
            message: "Customization endpoint unavailable for this session. Confirm the operator token and API configuration.",
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
        setCustomizationEditorState({ status: "unavailable", message: "Customization could not be saved. Check API reachability." });
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
    <section aria-labelledby="dataset-admin-title" style={pageStyle}>
      <header style={headerStyle}>
        <div>
          <p className="eyebrow">Dataset Admin</p>
          <h1 id="dataset-admin-title">Dataset administration</h1>
          <p className="summary">
            Private workspace for editing validated public profile drafts while keeping Atlas technical values read-only.
          </p>
        </div>

        <div style={headerControlsStyle}>
          <label style={fieldStyle}>
            <span style={labelStyle}>Dataset</span>
            <select
              disabled={state.status !== "ready" || datasets.length === 0}
              onChange={(event) => setSelectedSlug(event.target.value)}
              style={inputStyle}
              value={selectedDataset?.dataset_slug ?? ""}
            >
              {state.status === "loading" && <option value="">Loading datasets...</option>}
              {state.status === "error" && <option value="">Datasets unavailable</option>}
              {state.status === "ready" && datasets.length === 0 && <option value="">No datasets available</option>}
              {datasets.map((dataset) => (
                <option key={dataset.dataset_slug} value={dataset.dataset_slug}>
                  {dataset.title || dataset.dataset_slug}
                </option>
              ))}
            </select>
          </label>

          <form onSubmit={loadDraft} style={fieldStyle}>
            <span style={labelStyle}>Operator token</span>
            <div style={buttonRowStyle}>
              <input
                aria-label="Operator token"
                onChange={(event) => setAdminToken(event.target.value)}
                style={{ ...inputStyle, minWidth: "min(16rem, 100%)" }}
                type="password"
                value={adminToken}
              />
              <button style={secondaryButtonStyle} type="submit">
                Load draft
              </button>
            </div>
          </form>

          <span className="atlas-status-pill atlas-status-pill--info">Private draft editing</span>
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
          <span style={mutedTextStyle}>Saves only the schema-backed draft; publishing remains disabled.</span>
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
            saveCustomization,
            updateCustomizationDraft,
          )}
        </div>
      </section>
    </section>
  );
}
