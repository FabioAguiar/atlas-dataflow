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

const PROBLEM_TYPE_LABELS: Record<string, string> = {
  binary_classification: "Binary Classification",
  multiclass_classification: "Multiclass Classification",
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
