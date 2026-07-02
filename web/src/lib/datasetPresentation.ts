export type DatasetIconName = "telecom" | "bank" | "generic";

const PROBLEM_TYPE_LABELS: Record<string, string> = {
  binary_classification: "Classificação binária",
  multiclass_classification: "Classificação multiclasse",
  regression: "Regressão",
  clustering: "Agrupamento",
  anomaly_detection: "Detecção de anomalias",
  time_series_forecasting: "Previsão de série temporal",
};

const DEFAULT_PROBLEM_TYPE_LABEL = "Análise preditiva";

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

const DOMAIN_ICON_RULES: Array<{ icon: DatasetIconName; keywords: string[] }> = [
  { icon: "telecom", keywords: ["telecom", "telco"] },
  { icon: "bank", keywords: ["bank", "financ"] },
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
