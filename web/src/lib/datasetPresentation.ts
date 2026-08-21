// "telecom", "bank", and "generic" are the original deterministic-fallback
// values (kept for backward compatibility with already-published data). The
// remaining values are Atlas's controlled curated icon bank
// (contracts/dataset-public-profile.schema.json's home_card.icon enum),
// selectable by an authoring curator regardless of dataset domain.
export type DatasetIconName =
  | "telecom"
  | "bank"
  | "generic"
  | "telecom-users"
  | "bank-building"
  | "chart-line"
  | "heart"
  | "shopping-cart"
  | "airplane"
  | "shield"
  | "education-cap"
  | "energy-bolt"
  | "home-house"
  | "agro-leaf"
  | "logistics-truck"
  | "factory"
  | "weather-cloud"
  | "database"
  | "money-dollar"
  | "globe"
  | "flask"
  | "cpu-chip";

export const DATASET_THEME_TOKEN_NAMES = [
  "canvas", "surface", "surface_muted", "text", "text_muted", "border", "border_strong",
  "accent", "accent_strong", "accent_muted", "chart_primary", "chart_secondary", "chart_grid", "focus_ring",
] as const;

export type DatasetThemeTokenName = (typeof DATASET_THEME_TOKEN_NAMES)[number];
export type DatasetThemeTokens = Readonly<Record<DatasetThemeTokenName, string>>;

const tokens = (value: DatasetThemeTokens): DatasetThemeTokens => Object.freeze(value);

export const DATASET_THEME_PRESETS = [
  { id: "atlas-green", label: "Atlas Green", swatches: ["#2f6f4e", "#e8f2ec", "#ffffff"], tokens: tokens({ canvas: "#f5f8f4", surface: "#ffffff", surface_muted: "#eef5f0", text: "#18241d", text_muted: "#526158", border: "#d5e2d8", border_strong: "#9fbea8", accent: "#2f6f4e", accent_strong: "#1f573b", accent_muted: "#e8f2ec", chart_primary: "#2f6f4e", chart_secondary: "#3d7f8b", chart_grid: "#c7d7cc", focus_ring: "#5b9272" }) },
  { id: "ocean-blue", label: "Ocean Blue", swatches: ["#2563eb", "#dbeafe", "#ffffff"], tokens: tokens({ canvas: "#f3f7ff", surface: "#ffffff", surface_muted: "#eaf2ff", text: "#17223b", text_muted: "#53627d", border: "#cfddf4", border_strong: "#91addb", accent: "#2563eb", accent_strong: "#1d4ed8", accent_muted: "#dbeafe", chart_primary: "#2563eb", chart_secondary: "#0891b2", chart_grid: "#bfd0ea", focus_ring: "#60a5fa" }) },
  { id: "violet-insight", label: "Violet Insight", swatches: ["#6d28d9", "#ede9fe", "#ffffff"], tokens: tokens({ canvas: "#f8f6ff", surface: "#ffffff", surface_muted: "#f1edff", text: "#281b3d", text_muted: "#675978", border: "#ddd4f2", border_strong: "#aa94d5", accent: "#6d28d9", accent_strong: "#581cba", accent_muted: "#ede9fe", chart_primary: "#6d28d9", chart_secondary: "#c026d3", chart_grid: "#d2c7e8", focus_ring: "#8b5cf6" }) },
  { id: "amber-signal", label: "Amber Signal", swatches: ["#b45309", "#fef3c7", "#ffffff"], tokens: tokens({ canvas: "#fffbeb", surface: "#ffffff", surface_muted: "#fef6d8", text: "#352512", text_muted: "#74634d", border: "#ead9a9", border_strong: "#c9a85e", accent: "#b45309", accent_strong: "#92400e", accent_muted: "#fef3c7", chart_primary: "#b45309", chart_secondary: "#ca8a04", chart_grid: "#dfcc98", focus_ring: "#d97706" }) },
  { id: "slate-ops", label: "Slate Ops", swatches: ["#334155", "#e2e8f0", "#ffffff"], tokens: tokens({ canvas: "#f4f6f8", surface: "#ffffff", surface_muted: "#edf1f5", text: "#1e293b", text_muted: "#5b6879", border: "#d4dce5", border_strong: "#9aa8b8", accent: "#475569", accent_strong: "#334155", accent_muted: "#e2e8f0", chart_primary: "#334155", chart_secondary: "#64748b", chart_grid: "#c5cfda", focus_ring: "#64748b" }) },
  { id: "rose-review", label: "Rose Review", swatches: ["#be123c", "#ffe4e6", "#ffffff"], tokens: tokens({ canvas: "#fff7f8", surface: "#ffffff", surface_muted: "#fff0f1", text: "#351a22", text_muted: "#76545d", border: "#f1cdd2", border_strong: "#d68d9b", accent: "#be123c", accent_strong: "#9f1239", accent_muted: "#ffe4e6", chart_primary: "#be123c", chart_secondary: "#db2777", chart_grid: "#e7bdc5", focus_ring: "#e11d48" }) },
  { id: "teal-flow", label: "Teal Flow", swatches: ["#0f766e", "#ccfbf1", "#ffffff"], tokens: tokens({ canvas: "#f1fbf9", surface: "#ffffff", surface_muted: "#e4f8f3", text: "#14312e", text_muted: "#4c6b67", border: "#c5e6df", border_strong: "#82bdb2", accent: "#0f766e", accent_strong: "#115e59", accent_muted: "#ccfbf1", chart_primary: "#0f766e", chart_secondary: "#0284c7", chart_grid: "#b7dcd4", focus_ring: "#14b8a6" }) },
  { id: "indigo-lab", label: "Indigo Lab", swatches: ["#4338ca", "#e0e7ff", "#ffffff"], tokens: tokens({ canvas: "#f5f6ff", surface: "#ffffff", surface_muted: "#ebedff", text: "#202044", text_muted: "#5c5c7d", border: "#d2d5f1", border_strong: "#999ed4", accent: "#4338ca", accent_strong: "#3730a3", accent_muted: "#e0e7ff", chart_primary: "#4338ca", chart_secondary: "#7c3aed", chart_grid: "#c4c7e6", focus_ring: "#6366f1" }) },
  { id: "graphite", label: "Graphite", swatches: ["#27272a", "#e4e4e7", "#ffffff"], tokens: tokens({ canvas: "#f4f4f5", surface: "#ffffff", surface_muted: "#ededee", text: "#27272a", text_muted: "#646469", border: "#d4d4d8", border_strong: "#a1a1aa", accent: "#3f3f46", accent_strong: "#27272a", accent_muted: "#e4e4e7", chart_primary: "#27272a", chart_secondary: "#71717a", chart_grid: "#c4c4c9", focus_ring: "#52525b" }) },
  { id: "citrus", label: "Citrus", swatches: ["#65a30d", "#ecfccb", "#ffffff"], tokens: tokens({ canvas: "#f8fdeb", surface: "#ffffff", surface_muted: "#f1fad9", text: "#25340f", text_muted: "#617044", border: "#dbeab6", border_strong: "#accb69", accent: "#65a30d", accent_strong: "#4d7c0f", accent_muted: "#ecfccb", chart_primary: "#65a30d", chart_secondary: "#ca8a04", chart_grid: "#cfdfa6", focus_ring: "#84cc16" }) },
  { id: "coral", label: "Coral", swatches: ["#c2410c", "#ffedd5", "#ffffff"], tokens: tokens({ canvas: "#fff8f2", surface: "#ffffff", surface_muted: "#fff0e2", text: "#3a2015", text_muted: "#795b4f", border: "#f0d2bf", border_strong: "#d49673", accent: "#c2410c", accent_strong: "#9a3412", accent_muted: "#ffedd5", chart_primary: "#c2410c", chart_secondary: "#dc2626", chart_grid: "#e5c4af", focus_ring: "#ea580c" }) },
  { id: "skyline", label: "Skyline", swatches: ["#0284c7", "#e0f2fe", "#ffffff"], tokens: tokens({ canvas: "#f3faff", surface: "#ffffff", surface_muted: "#eaf6fd", text: "#153044", text_muted: "#506b7e", border: "#cde5f2", border_strong: "#8abbd3", accent: "#0284c7", accent_strong: "#0369a1", accent_muted: "#e0f2fe", chart_primary: "#0284c7", chart_secondary: "#0d9488", chart_grid: "#bfdae8", focus_ring: "#0ea5e9" }) },
  { id: "plum", label: "Plum", swatches: ["#86198f", "#fae8ff", "#ffffff"], tokens: tokens({ canvas: "#fff6ff", surface: "#ffffff", surface_muted: "#fbedfd", text: "#351938", text_muted: "#765379", border: "#ebcfed", border_strong: "#c38bc7", accent: "#86198f", accent_strong: "#701a75", accent_muted: "#fae8ff", chart_primary: "#86198f", chart_secondary: "#be185d", chart_grid: "#dfbee2", focus_ring: "#a21caf" }) },
  { id: "neutral-light", label: "Neutral Light", swatches: ["#525252", "#f5f5f5", "#ffffff"], tokens: tokens({ canvas: "#fafafa", surface: "#ffffff", surface_muted: "#f5f5f5", text: "#262626", text_muted: "#686868", border: "#dedede", border_strong: "#a3a3a3", accent: "#525252", accent_strong: "#404040", accent_muted: "#eeeeee", chart_primary: "#525252", chart_secondary: "#737373", chart_grid: "#d4d4d4", focus_ring: "#737373" }) },
  { id: "midnight-cyan", label: "Midnight Cyan", swatches: ["#0891b2", "#083344", "#ecfeff"], tokens: tokens({ canvas: "#061f2a", surface: "#0b2e3b", surface_muted: "#103b49", text: "#ecfeff", text_muted: "#a5d8df", border: "#245464", border_strong: "#3b7a8c", accent: "#22d3ee", accent_strong: "#67e8f9", accent_muted: "#164e63", chart_primary: "#22d3ee", chart_secondary: "#38bdf8", chart_grid: "#356170", focus_ring: "#67e8f9" }) },
  { id: "emerald-noir", label: "Emerald Noir", swatches: ["#10b981", "#052e2b", "#d1fae5"], tokens: tokens({ canvas: "#041f1d", surface: "#082d29", surface_muted: "#0c3b35", text: "#d1fae5", text_muted: "#9bd5bc", border: "#24594d", border_strong: "#3b806d", accent: "#10b981", accent_strong: "#6ee7b7", accent_muted: "#064e3b", chart_primary: "#10b981", chart_secondary: "#2dd4bf", chart_grid: "#326459", focus_ring: "#6ee7b7" }) },
  { id: "solar-flare", label: "Solar Flare", swatches: ["#ea580c", "#7c2d12", "#ffedd5"], tokens: tokens({ canvas: "#431407", surface: "#64200c", surface_muted: "#7c2d12", text: "#ffedd5", text_muted: "#fdba74", border: "#9a451d", border_strong: "#c9652a", accent: "#fb923c", accent_strong: "#fed7aa", accent_muted: "#7c2d12", chart_primary: "#fb923c", chart_secondary: "#facc15", chart_grid: "#a65428", focus_ring: "#fdba74" }) },
  { id: "electric-magenta", label: "Electric Magenta", swatches: ["#db2777", "#500724", "#fce7f3"], tokens: tokens({ canvas: "#310416", surface: "#48071f", surface_muted: "#5d0a2b", text: "#fce7f3", text_muted: "#f5b6d2", border: "#7e2448", border_strong: "#ad3565", accent: "#f472b6", accent_strong: "#fbcfe8", accent_muted: "#831843", chart_primary: "#f472b6", chart_secondary: "#c084fc", chart_grid: "#8d3659", focus_ring: "#f9a8d4" }) },
  { id: "neon-lime", label: "Neon Lime", swatches: ["#84cc16", "#1a2e05", "#ecfccb"], tokens: tokens({ canvas: "#111f04", surface: "#1a2e05", surface_muted: "#263d0b", text: "#ecfccb", text_muted: "#c4e58a", border: "#46631c", border_strong: "#698d2b", accent: "#a3e635", accent_strong: "#d9f99d", accent_muted: "#365314", chart_primary: "#a3e635", chart_secondary: "#facc15", chart_grid: "#536d27", focus_ring: "#bef264" }) },
  { id: "aurora", label: "Aurora", swatches: ["#14b8a6", "#4c1d95", "#ccfbf1"], tokens: tokens({ canvas: "#24104d", surface: "#321665", surface_muted: "#402079", text: "#e9fffb", text_muted: "#c3d8dd", border: "#65439a", border_strong: "#8470ba", accent: "#2dd4bf", accent_strong: "#99f6e4", accent_muted: "#134e4a", chart_primary: "#2dd4bf", chart_secondary: "#c084fc", chart_grid: "#7259a0", focus_ring: "#5eead4" }) },
  { id: "deep-sea", label: "Deep Sea", swatches: ["#0e7490", "#082f49", "#cffafe"], tokens: tokens({ canvas: "#051f31", surface: "#082f49", surface_muted: "#0b3d5c", text: "#cffafe", text_muted: "#9ed8e4", border: "#245b74", border_strong: "#397f99", accent: "#22d3ee", accent_strong: "#a5f3fc", accent_muted: "#164e63", chart_primary: "#22d3ee", chart_secondary: "#38bdf8", chart_grid: "#32677d", focus_ring: "#67e8f9" }) },
  { id: "desert-sand", label: "Desert Sand", swatches: ["#a16207", "#fef3c7", "#fffbeb"], tokens: tokens({ canvas: "#fff8e1", surface: "#fffbeb", surface_muted: "#f8edcd", text: "#3b2a14", text_muted: "#78664c", border: "#e6d3a6", border_strong: "#bf9e61", accent: "#a16207", accent_strong: "#854d0e", accent_muted: "#fef3c7", chart_primary: "#a16207", chart_secondary: "#c2410c", chart_grid: "#d8c394", focus_ring: "#ca8a04" }) },
  { id: "forest-moss", label: "Forest Moss", swatches: ["#3f6212", "#ecfccb", "#f7fee7"], tokens: tokens({ canvas: "#f3f9e7", surface: "#fafff3", surface_muted: "#eaf4d8", text: "#243410", text_muted: "#627048", border: "#d4e3b8", border_strong: "#9fbc6f", accent: "#3f6212", accent_strong: "#365314", accent_muted: "#ecfccb", chart_primary: "#3f6212", chart_secondary: "#0f766e", chart_grid: "#c5d7a6", focus_ring: "#65a30d" }) },
  { id: "ice-blue", label: "Ice Blue", swatches: ["#0ea5e9", "#e0f2fe", "#f8fafc"], tokens: tokens({ canvas: "#f0f9ff", surface: "#f8fcff", surface_muted: "#e7f5fd", text: "#173247", text_muted: "#557085", border: "#cae5f3", border_strong: "#83bad4", accent: "#0ea5e9", accent_strong: "#0369a1", accent_muted: "#e0f2fe", chart_primary: "#0ea5e9", chart_secondary: "#06b6d4", chart_grid: "#badbe9", focus_ring: "#38bdf8" }) },
  { id: "crimson-night", label: "Crimson Night", swatches: ["#e11d48", "#1f1020", "#ffe4e6"], tokens: tokens({ canvas: "#160b17", surface: "#241225", surface_muted: "#32172f", text: "#ffe4e6", text_muted: "#ddb5bd", border: "#593047", border_strong: "#80405d", accent: "#fb7185", accent_strong: "#fecdd3", accent_muted: "#4c0519", chart_primary: "#fb7185", chart_secondary: "#e879f9", chart_grid: "#66384f", focus_ring: "#fda4af" }) },
  { id: "copper-circuit", label: "Copper Circuit", swatches: ["#b45309", "#292524", "#fed7aa"], tokens: tokens({ canvas: "#1c1917", surface: "#292524", surface_muted: "#3a312d", text: "#ffedd5", text_muted: "#d6bda7", border: "#5b4b42", border_strong: "#846554", accent: "#d97706", accent_strong: "#fed7aa", accent_muted: "#5c2d0c", chart_primary: "#f59e0b", chart_secondary: "#fb7185", chart_grid: "#6c5548", focus_ring: "#fbbf24" }) },
  { id: "lavender-mist", label: "Lavender Mist", swatches: ["#7c3aed", "#f3e8ff", "#faf5ff"], tokens: tokens({ canvas: "#faf5ff", surface: "#fffaff", surface_muted: "#f3e8ff", text: "#302044", text_muted: "#705d82", border: "#e2d1ef", border_strong: "#b596d0", accent: "#7c3aed", accent_strong: "#6d28d9", accent_muted: "#ede9fe", chart_primary: "#7c3aed", chart_secondary: "#db2777", chart_grid: "#d5c3e5", focus_ring: "#8b5cf6" }) },
  { id: "monochrome-dark", label: "Monochrome Dark", swatches: ["#d4d4d8", "#18181b", "#3f3f46"], tokens: tokens({ canvas: "#111113", surface: "#18181b", surface_muted: "#27272a", text: "#f4f4f5", text_muted: "#b8b8bf", border: "#3f3f46", border_strong: "#71717a", accent: "#d4d4d8", accent_strong: "#fafafa", accent_muted: "#3f3f46", chart_primary: "#e4e4e7", chart_secondary: "#a1a1aa", chart_grid: "#52525b", focus_ring: "#d4d4d8" }) },
  { id: "retro-terminal", label: "Retro Terminal", swatches: ["#22c55e", "#020617", "#14532d"], tokens: tokens({ canvas: "#010409", surface: "#020617", surface_muted: "#07130d", text: "#bbf7d0", text_muted: "#86c99e", border: "#14532d", border_strong: "#22c55e", accent: "#22c55e", accent_strong: "#86efac", accent_muted: "#123b23", chart_primary: "#4ade80", chart_secondary: "#facc15", chart_grid: "#1f6338", focus_ring: "#4ade80" }) },
  { id: "cyber-neon", label: "Cyber Neon", swatches: ["#22d3ee", "#f472b6", "#111827"], tokens: tokens({ canvas: "#080d1a", surface: "#111827", surface_muted: "#1a2235", text: "#ecfeff", text_muted: "#b4c1d6", border: "#33445f", border_strong: "#596d8c", accent: "#22d3ee", accent_strong: "#a5f3fc", accent_muted: "#164e63", chart_primary: "#22d3ee", chart_secondary: "#f472b6", chart_grid: "#40536e", focus_ring: "#f472b6" }) },
] as const;

export type DatasetThemePresetId = (typeof DATASET_THEME_PRESETS)[number]["id"];

export const DEFAULT_DATASET_THEME_PRESET: DatasetThemePresetId = "atlas-green";

export function isDatasetThemePresetId(value: unknown): value is DatasetThemePresetId {
  return DATASET_THEME_PRESETS.some((preset) => preset.id === value);
}

export function resolveDatasetThemePreset(value: unknown) {
  return DATASET_THEME_PRESETS.find((preset) => preset.id === value) ?? DATASET_THEME_PRESETS[0];
}

export type DatasetThemeStyle = Record<`--dataset-theme-${string}`, string>;

export function datasetThemeStyle(value: unknown): DatasetThemeStyle {
  const { tokens: resolvedTokens } = resolveDatasetThemePreset(value);
  return Object.fromEntries(
    DATASET_THEME_TOKEN_NAMES.map((name) => [`--dataset-theme-${name.replaceAll("_", "-")}`, resolvedTokens[name]]),
  ) as DatasetThemeStyle;
}

const PROBLEM_TYPE_LABELS: Record<string, string> = {
  binary_classification: "Binary Classification",
  multiclass_classification: "Multiclass Classification",
  continuous_regression: "Continuous Regression",
  regression: "Regression",
  clustering: "Clustering",
  anomaly_detection: "Anomaly Detection",
  time_series_forecasting: "Time Series Forecasting",
};

const DEFAULT_PROBLEM_TYPE_LABEL = "Predictive Analysis";

const LEGACY_HOME_CARD_DESCRIPTION_FALLBACKS = new Set([
  "Customer churn prediction dataset for a telecommunications provider.",
  "Customer churn prediction dataset for a telecommunications provider. Predicts whether a customer will churn based on service usage and account features.",
]);

export function presentHomeCardDescription(description?: string | null): string {
  const trimmed = description?.trim() ?? "";
  return LEGACY_HOME_CARD_DESCRIPTION_FALLBACKS.has(trimmed) ? "" : trimmed;
}

export type DatasetOperationalTimestampPresentation = {
  localizedDateTime: string;
  localCalendarDate: string;
};

type DatasetOperationalTimestampPresentationOptions = {
  locale?: string | string[];
  timeZone?: string;
};

/**
 * Projects the canonical UTC Dataset Detail mutation timestamp into the two
 * admin-facing values that must share one local calendar interpretation.
 * The optional timezone keeps this contract deterministic in tests; runtime
 * callers omit it to use the browser's configured local timezone.
 */
export function presentDatasetOperationalTimestamp(
  value: string | null | undefined,
  options: DatasetOperationalTimestampPresentationOptions = {},
): DatasetOperationalTimestampPresentation | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  const timeZoneOptions = options.timeZone ? { timeZone: options.timeZone } : {};
  const calendarParts = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
    ...timeZoneOptions,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parsed);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    calendarParts.find((candidate) => candidate.type === type)?.value;
  const year = part("year");
  const month = part("month");
  const day = part("day");

  if (!year || !month || !day) {
    return null;
  }

  return {
    localizedDateTime: parsed.toLocaleString(options.locale, {
      ...timeZoneOptions,
      calendar: "gregory",
      dateStyle: "medium",
      timeStyle: "short",
    }),
    localCalendarDate: `${year}-${month}-${day}`,
  };
}

/** Validates editorial date-only content without applying timestamp semantics. */
export function normalizeDatasetDateOnly(value: string | null | undefined): string {
  if (typeof value !== "string") {
    return "";
  }

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return "";
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth[month - 1]
    ? value
    : "";
}

export type DatasetDateFormat = "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";

export type DatasetDateOnlyPresentation = {
  value: string;
  effectiveFormat: DatasetDateFormat;
};

/** Formats date-only editorial content without constructing a timestamp. */
export function presentDatasetDateOnly(
  value: string | null | undefined,
  format: DatasetDateFormat | null | undefined,
): DatasetDateOnlyPresentation | null {
  const effectiveFormat: DatasetDateFormat =
    format === "mm/dd/yyyy" || format === "yyyy-mm-dd" ? format : "dd/mm/yyyy";
  const canonical = normalizeDatasetDateOnly(value);

  if (canonical) {
    const [year, month, day] = canonical.split("-");
    if (effectiveFormat === "dd/mm/yyyy") return { value: `${day}/${month}/${year}`, effectiveFormat };
    if (effectiveFormat === "mm/dd/yyyy") return { value: `${month}/${day}/${year}`, effectiveFormat };
    return { value: canonical, effectiveFormat };
  }

  // Preserve valid legacy DD/MM/YYYY display content without reinterpreting
  // it as a timestamp. Canonical snapshot values continue to use YYYY-MM-DD.
  const legacyMatch = typeof value === "string" ? /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value) : null;
  if (legacyMatch) {
    const [, day, month, year] = legacyMatch;
    if (normalizeDatasetDateOnly(`${year}-${month}-${day}`)) {
      return { value: legacyMatch[0], effectiveFormat: "dd/mm/yyyy" };
    }
  }

  return null;
}

/** Returns only absolute public HTTP(S) links suitable for source metadata. */
export function safePublicSourceUrl(value: string | null | undefined): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * GET /datasets (registry/list.py ListedDataset) returns only dataset_slug,
 * title, summary, domain, visibility and tags today, never problem_type. This
 * always falls back to a generic public label instead of inventing a
 * specific analysis type per dataset; if problem_type is added to the API
 * later, known values resolve to their documented public label.
 */
export function getProblemTypeLabel(problemType?: string | null): string {
  if (!problemType) {
    return DEFAULT_PROBLEM_TYPE_LABEL;
  }
  return PROBLEM_TYPE_LABELS[problemType] ?? DEFAULT_PROBLEM_TYPE_LABEL;
}

/**
 * Structurally accepts any bounded result-contract state carrying the
 * governed model_descriptor.display_name (binary, multiclass, and
 * continuous-regression result contracts all share this shape) without
 * importing a concrete ResultContract type, so both the public Dataset
 * Detail route and Dataset Admin Live Preview's locally-declared preview
 * result-contract type can reuse this one authority (Project Spec S0238).
 */
export type DatasetModelDisplayNameResultInput =
  | { status: string; semantics?: { model_descriptor?: { display_name?: unknown } | null } | null }
  | null
  | undefined;

/**
 * Project Spec S0238: the single shared release-bound Model badge authority
 * -- available-status result-contract semantics only. Never falls back to
 * registry tags/domain/title, profile/result-card copy, or a dataset/model-
 * family guess; a missing/blank/non-string display_name resolves to null so
 * callers omit the Model badge instead of inventing one.
 */
export function resolveModelDisplayName(resultContract: DatasetModelDisplayNameResultInput): string | null {
  if (!resultContract || resultContract.status !== "available") {
    return null;
  }
  const displayName = resultContract.semantics?.model_descriptor?.display_name;
  if (typeof displayName !== "string") {
    return null;
  }
  const trimmed = displayName.trim();
  return trimmed || null;
}

// Not exhaustive of DatasetIconName's full curated icon bank -- only the
// domains this function can confidently infer automatically from
// domain/tags. A domain matching none of these keyword families falls back
// to "generic", a normal renderable value, never a rejection; this
// automatic fallback never requires telecom or bank to exist. An authoring
// curator may still hand-select any other icon from the full bank via
// web/src/pages/admin/DatasetAdminPage.tsx. Kept in lockstep with
// api/public_profile_fallback.py's _DOMAIN_ICON_RULES.
const DOMAIN_ICON_RULES: Array<{ icon: DatasetIconName; keywords: string[] }> = [
  { icon: "telecom", keywords: ["telecom", "telco"] },
  { icon: "bank", keywords: ["bank", "financ"] },
  { icon: "heart", keywords: ["health", "medical", "clinic", "hospital"] },
  { icon: "shopping-cart", keywords: ["retail", "commerce", "shop"] },
  { icon: "education-cap", keywords: ["education", "school", "university"] },
  { icon: "energy-bolt", keywords: ["energy", "utility", "power"] },
  { icon: "logistics-truck", keywords: ["logistics", "shipping", "freight"] },
  { icon: "shield", keywords: ["insurance", "security"] },
];

/**
 * GET /datasets never returns theme_icon today, so the theme icon is derived
 * deterministically from domain/tags (fields the API does provide) instead
 * of being invented per dataset, per the documented fallback rule in
 * design/screens/home/content.md.
 */
export function getDatasetIcon(domain?: string | null, tags: string[] = []): DatasetIconName {
  const haystack = [domain ?? "", ...tags].join(" ").toLowerCase();

  for (const rule of DOMAIN_ICON_RULES) {
    if (rule.keywords.some((keyword) => haystack.includes(keyword))) {
      return rule.icon;
    }
  }

  return "generic";
}

// contracts/dataset-public-profile-snapshot.schema.json's home_card.icon
// enum is restricted to exactly these three values today (a narrower set
// than DatasetIconName's full curated bank above), so a curated
// home_card_icon value from GET /datasets is only ever one of these.
export const CURATABLE_HOME_CARD_ICONS: readonly DatasetIconName[] = [
  "telecom", "bank", "generic", "telecom-users", "bank-building", "chart-line",
  "heart", "shopping-cart", "airplane", "shield", "education-cap", "energy-bolt",
  "home-house", "agro-leaf", "logistics-truck", "factory", "weather-cloud", "database",
  "money-dollar", "globe", "flask", "cpu-chip",
];

const SAFE_HOME_CARD_MEDIA_REFERENCE =
  /^\/media\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*\.(?:avif|gif|jpeg|jpg|png|webp)$/;

export function isSafeHomeCardMediaReference(value?: string | null): value is string {
  return typeof value === "string" && value.length <= 256 && SAFE_HOME_CARD_MEDIA_REFERENCE.test(value);
}

/**
 * Prefers a curated icon explicitly published on the dataset's profile
 * snapshot (surfaced by GET /datasets/GET /datasets/{slug} as
 * home_card_icon) over the domain/tags-derived fallback; the derived
 * fallback exists specifically for datasets with no curated icon set, so a
 * curated value always wins when present.
 */
export function resolveDatasetIcon(
  curatedIcon?: string | null,
  domain?: string | null,
  tags: string[] = [],
): DatasetIconName {
  if (curatedIcon && (CURATABLE_HOME_CARD_ICONS as readonly string[]).includes(curatedIcon)) {
    return curatedIcon as DatasetIconName;
  }
  return getDatasetIcon(domain, tags);
}

function nonBlankTargetValue(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed || null;
}

type DatasetTargetSemanticsLike = {
  positive_class?: { event_label?: string | null; class_id?: string | null } | null;
  negative_class?: { class_id?: string | null } | null;
};

/**
 * Structurally accepts either a bounded result-contract state (an object
 * with a `status` discriminant, e.g. this project's public
 * BinaryResultContract or the private admin authoring context's richer
 * idle/loading/available/unavailable/transport_failure/incompatible
 * ResultContractState) or bare result semantics passed directly.
 */
export type DatasetTargetResultInput =
  | { status: string; semantics?: DatasetTargetSemanticsLike | null }
  | DatasetTargetSemanticsLike
  | null
  | undefined;

function isDatasetTargetResultState(
  value: NonNullable<DatasetTargetResultInput>,
): value is { status: string; semantics?: DatasetTargetSemanticsLike | null } {
  return typeof (value as { status?: unknown }).status === "string";
}

/**
 * Project Spec S0154: the single shared Dataset Detail Target metadata
 * projection -- both the public Dataset Detail and the Dataset Admin Live
 * Preview must derive their Target row through this one function. Available
 * release-bound result semantics (event label + both class IDs) are always
 * the first authority; a nonblank published prediction_target_description is
 * the fallback; otherwise null (the shared header renders that as Pending).
 * Deterministic and side-effect free -- never inspects problem_type, model
 * display name, metric names, visualization labels, Predict View copy,
 * dataset title or dataset slug.
 */
export function resolveDatasetTargetDescription(
  resultContract: DatasetTargetResultInput,
  predictionTargetDescription?: string | null,
): string | null {
  const semantics: DatasetTargetSemanticsLike | null | undefined = resultContract
    ? isDatasetTargetResultState(resultContract)
      ? (resultContract.status === "available" ? resultContract.semantics : null)
      : resultContract
    : null;

  const eventLabel = nonBlankTargetValue(semantics?.positive_class?.event_label);
  const positiveClassId = nonBlankTargetValue(semantics?.positive_class?.class_id);
  const negativeClassId = nonBlankTargetValue(semantics?.negative_class?.class_id);

  if (eventLabel && positiveClassId && negativeClassId) {
    return `${eventLabel} (${positiveClassId}/${negativeClassId})`;
  }

  return nonBlankTargetValue(predictionTargetDescription);
}
