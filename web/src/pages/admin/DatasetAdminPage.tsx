import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { Tabs, type TabItem } from "../../components/ui";

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

type ContractField = {
  name?: string;
  type?: string;
  required?: boolean;
};

type ContractPayload = {
  fields?: ContractField[];
  inputs?: ContractField[];
  input_schema?: {
    fields?: ContractField[];
  };
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
  customization: SectionState<unknown>;
};

const emptyReadOnlyData: ReadOnlyData = {
  dataset: { status: "idle" },
  context: { status: "idle" },
  contract: { status: "idle" },
  metrics: { status: "idle" },
  modelCard: { status: "idle" },
  visualizations: { status: "idle" },
  views: { status: "idle" },
  customization: { status: "idle" },
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
  return contract?.fields ?? contract?.inputs ?? contract?.input_schema?.fields ?? [];
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

function InferenceFormTab({
  form,
  setField,
  readOnlyData,
}: {
  form: DraftForm;
  setField: <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => void;
  readOnlyData: ReadOnlyData;
}) {
  const contract = stateValue(readOnlyData.contract);
  const views = stateValue(readOnlyData.views) ?? [];
  const fields = contractFields(contract);
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Inference Form</h2>
        <p style={mutedTextStyle}>The draft stores only an optional predict view binding; contract fields are read-only.</p>
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
      <section aria-label="Read-only contract fields" style={readOnlyFieldStyle}>
        <span style={labelStyle}>Contract fields</span>
        {fields.length === 0 ? (
          <p style={mutedTextStyle}>Contract field list unavailable.</p>
        ) : (
          <ul style={{ ...tagListStyle, marginTop: "var(--atlas-space-2)" }}>
            {fields.slice(0, 20).map((field, index) => (
              <li key={`${field.name ?? "field"}-${index}`} style={tagStyle}>
                {field.name ?? "Unnamed"} {field.required ? "(required)" : ""}
              </li>
            ))}
          </ul>
        )}
      </section>
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

function DatasetPreview({ dataset, form, mode }: { dataset?: DatasetListing; form: DraftForm; mode: "card" | "detail" }) {
  const title = form.display_title.trim() || getDatasetLabel(dataset);
  const summary = form.short_description.trim() || form.display_subtitle.trim() || dataset?.summary;
  return (
    <article aria-label={`${mode === "detail" ? "Detail" : "Card"} preview`} style={previewCardStyle}>
      <span className="atlas-status-pill">{dataset?.visibility || "visibility unavailable"}</span>
      <h3 style={{ margin: 0 }}>{title}</h3>
      <p style={mutedTextStyle}>{summary || "Draft presentation appears here after editing."}</p>
      {mode === "detail" && (
        <div style={sectionGridStyle}>
          <ReadOnlyField label="Slug" value={dataset?.dataset_slug || ""} />
          <ReadOnlyField label="Read-only domain" value={dataset?.domain || ""} />
          <ReadOnlyField label="Primary metric reference" value={form.primary_metric_key || ""} />
        </div>
      )}
      <DatasetTags tags={dataset?.tags ?? []} />
    </article>
  );
}

function LivePreviewTab({ dataset, form }: { dataset?: DatasetListing; form: DraftForm }) {
  const [previewMode, setPreviewMode] = useState<"detail" | "card">("detail");

  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Live Preview</h2>
        <p style={mutedTextStyle}>Preview uses editable draft presentation fields over read-only dataset context.</p>
      </div>
      <div aria-label="Preview mode" style={buttonRowStyle}>
        {(["detail", "card"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setPreviewMode(mode)}
            style={previewMode === mode ? secondaryButtonStyle : disabledButtonStyle}
            type="button"
          >
            {mode === "detail" ? "Dataset detail" : "Home card"}
          </button>
        ))}
      </div>
      <DatasetPreview dataset={dataset} form={form} mode={previewMode} />
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
) {
  switch (selectedTab) {
    case "metadata-card":
      return <MetadataCardTab form={form} readOnlyData={readOnlyData} setField={setField} />;
    case "theme-preset":
      return <ThemePresetTab form={form} setField={setField} />;
    case "inference-form":
      return <InferenceFormTab form={form} readOnlyData={readOnlyData} setField={setField} />;
    case "result-card":
      return <ResultCardTab form={form} setField={setField} />;
    case "publishing":
      return <PublishingTab draftState={draftState} />;
    case "live-preview":
      return <LivePreviewTab dataset={dataset} form={form} />;
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
      return;
    }

    setDraftForm((current) => ({ ...emptyDraftForm(selectedSlug), schema_version: current.schema_version || "1.0.0" }));
    setDraftState({
      status: "idle",
      message: "Load the private/admin draft before saving profile edits.",
    });

    const controller = new AbortController();
    setReadOnlyData({
      dataset: { status: "loading" },
      context: { status: "loading" },
      contract: { status: "loading" },
      metrics: { status: "loading" },
      modelCard: { status: "loading" },
      visualizations: { status: "loading" },
      views: { status: "loading" },
      customization: { status: "idle" },
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
      const views = viewsResponse.status === "ready" ? viewsResponse.data.views : [];
      const firstView = views.find((view) => typeof view.view_id === "string");
      const customization = firstView?.view_id
        ? await fetchJson<unknown>(
            `/datasets/${encoded}/views/${encodeURIComponent(firstView.view_id)}/customization`,
            controller.signal,
          )
        : ({ status: "idle" } as SectionState<unknown>);

      setReadOnlyData({
        dataset,
        context: mapSection(context, (data) => data.context),
        contract: mapSection(contract, (data) => data.contract),
        metrics: mapSection(metrics, (data) => data.metrics),
        modelCard: mapSection(modelCard, (data) => data.model_card),
        visualizations: mapSection(visualizations, (data) => data.visualizations),
        views: mapSection(viewsResponse, (data) => data.views),
        customization,
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
          {renderSelectedTab(selectedTab, selectedDataset, draftForm, setField, readOnlyData, draftState)}
        </div>
      </section>
    </section>
  );
}
