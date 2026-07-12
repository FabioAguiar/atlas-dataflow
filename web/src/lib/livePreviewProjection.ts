import type { DatasetDetailMetadataItem } from "../components/DatasetDetail/DatasetDetailHeader";
import type { VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import type { ResultPreviewLabels, PredictionResult } from "../components/InferenceResult/InferenceResult";
import type { DatasetIconName } from "./datasetPresentation";
import type { PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";

/**
 * Live Preview input shapes are declared locally (structurally compatible
 * with DatasetAdminPage.tsx's own types) so this module never imports from a
 * page, only from the shared public components/lib it projects data into.
 */

type PreviewDataset = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
};

type PreviewContext = {
  title?: string;
  summary?: string;
  description?: string;
  domain?: string;
  tags?: string[];
  use_case?: string;
  problem_type?: string;
  prediction_target_description?: string;
};

type PreviewContractField = {
  name?: string;
  type?: string;
  required?: boolean;
};

type PreviewContract = {
  fields?: PreviewContractField[];
  inputs?: PreviewContractField[];
  input_schema?: {
    fields?: PreviewContractField[];
  };
};

type PreviewMetrics = Record<string, unknown>;

type PreviewModelCard = {
  content?: string;
  format?: string;
};

type PreviewDraftForm = {
  display_title: string;
  display_subtitle: string;
  source_name: string;
  release_date_label: string;
  date_format: "" | "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd";
  home_card_icon: "" | "telecom" | "bank" | "generic";
  short_description: string;
};

type PreviewResultCardForm = {
  probability_label: string;
  model_label: string;
  badge_preset: "" | "risk";
  badge_high: string;
  badge_medium: string;
  badge_low: string;
};

type PreviewPerformanceFocusDraft = {
  focus_id: PerformanceFocus["focus_id"];
  highlighted_score_id: string;
  scores: Array<PerformanceFocus["visible_scores"][number] & { visible: boolean }>;
};

export type HomeCardPreviewProps = {
  slug: string;
  title: string;
  summary: string;
  domain?: string;
  tags?: string[];
  iconOverride?: DatasetIconName;
  problemType?: string;
};

export type ResultCardPreview = {
  result: PredictionResult;
  previewLabels: ResultPreviewLabels;
};

export type DatasetDetailPreview = {
  datasetTitle: string;
  subtitle?: string;
  analysisType?: string;
  metadata: DatasetDetailMetadataItem[];
};

export type ModelCardPreview = {
  content: string;
  format: "markdown";
};

function contractFields(contract: PreviewContract | null): PreviewContractField[] {
  return contract?.fields ?? contract?.inputs ?? contract?.input_schema?.fields ?? [];
}

function extractInstanceCount(metrics: PreviewMetrics | null): string | null {
  const evaluation = metrics?.["evaluation"];
  if (evaluation && typeof evaluation === "object") {
    const sampleSize = (evaluation as Record<string, unknown>)["sample_size"];
    if (typeof sampleSize === "number" && Number.isFinite(sampleSize)) {
      return sampleSize.toLocaleString();
    }
  }
  return null;
}

/**
 * Projects the draft Home card onto DatasetCard's public props. Draft display
 * fields win over dataset fallbacks, the curated icon is forwarded when set,
 * and problemType follows the read-only public context so Live Preview stays
 * aligned with HomePage's current DatasetCard contract while remaining
 * undefined when context is unavailable.
 */
export function projectHomeCardPreview(
  dataset: PreviewDataset | undefined,
  form: Pick<PreviewDraftForm, "display_title" | "display_subtitle" | "short_description" | "home_card_icon">,
  context: PreviewContext | null,
): HomeCardPreviewProps {
  const title = form.display_title.trim() || dataset?.title || dataset?.dataset_slug || "";
  const summary = form.short_description.trim() || form.display_subtitle.trim() || dataset?.summary || "";

  return {
    slug: dataset?.dataset_slug ?? "",
    title,
    summary,
    domain: dataset?.domain,
    tags: dataset?.tags ?? [],
    iconOverride: form.home_card_icon || undefined,
    problemType: context?.problem_type,
  };
}

/**
 * Projects the draft detail header onto DatasetDetailHeader's public props.
 * Draft title/subtitle fields win over context and dataset fallbacks, Source
 * and Release come from the editable draft display fields, and all other
 * metadata is derived from the read-only context, contract, and metrics
 * already loaded for the public Dataset Detail surface.
 */
export function projectDatasetDetailPreview(
  dataset: PreviewDataset | undefined,
  form: PreviewDraftForm,
  context: PreviewContext | null,
  contract: PreviewContract | null,
  metrics: PreviewMetrics | null,
): DatasetDetailPreview {
  const datasetTitle = form.display_title.trim() || context?.title || dataset?.title || dataset?.dataset_slug || "";
  const subtitle =
    form.short_description.trim() ||
    form.display_subtitle.trim() ||
    context?.summary ||
    context?.description ||
    dataset?.summary;

  const fields = contractFields(contract);

  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: form.source_name.trim() || null },
    { label: "Instances", value: extractInstanceCount(metrics) },
    { label: "Features", value: fields.length ? String(fields.length) : null },
    { label: "Target", value: context?.prediction_target_description || context?.problem_type || null },
    {
      label: "Release",
      value: form.release_date_label.trim() || null,
      hint: `Format: ${form.date_format || "dd/mm/yyyy"}`,
    },
  ];

  return {
    datasetTitle,
    subtitle,
    analysisType: context?.problem_type,
    metadata,
  };
}

export function toVisualizationsPayload(value: unknown): VisualizationsPayload | null {
  if (value && typeof value === "object" && "charts" in value) {
    return value as VisualizationsPayload;
  }
  return null;
}

export function projectModelCardPreview(modelCard: PreviewModelCard | null): ModelCardPreview | null {
  if (modelCard?.content) {
    return { content: modelCard.content, format: "markdown" };
  }
  return null;
}

/**
 * Fixed, explicitly-labeled placeholder outcome -- never a real /inference
 * response -- so result_card settings can be previewed without implying a
 * genuine prediction was made.
 */
const RESULT_CARD_PLACEHOLDER_RESULT: PredictionResult = {
  label: "sample_outcome",
  confidence: 0.72,
};

/**
 * Projects result-card draft labels onto InferenceResult's preview override
 * contract. The result is always a fixed placeholder, probability/model labels
 * fall back to InferenceResult defaults when blank, and the risk preset maps
 * high/medium/low draft labels onto the component's danger/warning/success
 * tone labels.
 */
export function projectResultCardPreview(form: PreviewResultCardForm): ResultCardPreview {
  const toneLabels: ResultPreviewLabels["toneLabels"] = {};
  if (form.badge_preset === "risk") {
    if (form.badge_high.trim()) toneLabels.danger = form.badge_high.trim();
    if (form.badge_medium.trim()) toneLabels.warning = form.badge_medium.trim();
    if (form.badge_low.trim()) toneLabels.success = form.badge_low.trim();
  }

  return {
    result: RESULT_CARD_PLACEHOLDER_RESULT,
    previewLabels: {
      confidenceLabel: form.probability_label.trim() || undefined,
      modelLabel: form.model_label.trim() || undefined,
      toneLabels: Object.keys(toneLabels).length ? toneLabels : undefined,
    },
  };
}

/** Projects only checked presentation scores into the public S0069 shape. */
export function projectPerformanceFocusPreview(draft: PreviewPerformanceFocusDraft): PerformanceFocus | null {
  const visibleScores = draft.scores
    .filter((score) => score.visible)
    .map(({ visible: _visible, ...score }, order) => ({ ...score, order }));
  if (!visibleScores.some((score) => score.score_id === draft.highlighted_score_id)) {
    return null;
  }
  return {
    focus_id: draft.focus_id,
    highlighted_score_id: draft.highlighted_score_id,
    visible_scores: visibleScores,
  };
}
