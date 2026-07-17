import type { DatasetDetailMetadataItem } from "../components/DatasetDetail/DatasetDetailHeader";
import type { VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import type {
  BinaryClassificationResult,
  BinaryResultPresentation,
  BinaryResultSemantics,
  BinaryRiskBand,
} from "../components/ResultCard/types";
import type { DatasetIconName } from "./datasetPresentation";
import type { PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";
import { presentDatasetDateOnly, safePublicSourceUrl, type DatasetDateFormat } from "./datasetPresentation";

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

// Project Spec S0120: the draft fields required to feed the shared public
// Dataset Detail surface (title/subtitle/Problem Summary/Source/Release) plus
// the pre-existing Home card draft fields, kept in one type so both
// projection functions below draw from the same real Admin draft shape via
// Pick<> rather than each declaring an overlapping, drift-prone subset.
type PreviewDraftForm = {
  display_title: string;
  display_subtitle: string;
  problem_summary_title: string;
  problem_summary_body: string;
  source_name: string;
  source_url: string;
  release_date_label: string;
  date_format: "" | DatasetDateFormat;
  canonical_name_fallback: boolean;
  home_card_icon: "" | "telecom" | "bank" | "generic";
  short_description: string;
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

export type DatasetDetailPreview = {
  datasetTitle: string;
  subtitle?: string;
  analysisType?: string;
  metadata: DatasetDetailMetadataItem[];
  problemSummaryTitle: string;
  problemSummaryBody: string | null;
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

/** Trims a draft/context string field, treating whitespace-only content as absent. */
function nonBlank(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed || null;
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
 * Projects the draft Dataset Detail fields onto DatasetDetailSurfaceProps'
 * (Project Spec S0119) semantic shape. Title, subtitle and Problem Summary
 * each follow their own documented precedence (Project Spec S0120) --
 * short_description never participates, since it remains Home Card-only.
 * Source and Release reuse the same shared public safety/date-only
 * contracts DatasetPage.tsx applies (safePublicSourceUrl,
 * presentDatasetDateOnly) so Live Preview can never render an unsafe link or
 * a JavaScript-timestamp-derived date.
 */
export function projectDatasetDetailPreview(
  dataset: PreviewDataset | undefined,
  form: Pick<
    PreviewDraftForm,
    | "display_title"
    | "display_subtitle"
    | "problem_summary_title"
    | "problem_summary_body"
    | "source_name"
    | "source_url"
    | "release_date_label"
    | "date_format"
  >,
  context: PreviewContext | null,
  contract: PreviewContract | null,
  metrics: PreviewMetrics | null,
): DatasetDetailPreview {
  const datasetTitle =
    nonBlank(form.display_title) ||
    nonBlank(context?.title) ||
    nonBlank(dataset?.title) ||
    nonBlank(dataset?.dataset_slug) ||
    "";
  const subtitle =
    nonBlank(form.display_subtitle) ||
    nonBlank(context?.summary) ||
    nonBlank(context?.description) ||
    nonBlank(dataset?.summary) ||
    undefined;

  const problemSummaryTitle = nonBlank(form.problem_summary_title) || "Problem summary";
  const problemSummaryBody =
    nonBlank(form.problem_summary_body) ||
    nonBlank(context?.description) ||
    nonBlank(context?.use_case) ||
    nonBlank(context?.summary) ||
    null;

  const fields = contractFields(contract);

  const sourceName = nonBlank(form.source_name);
  const sourceHref = sourceName ? safePublicSourceUrl(form.source_url) : null;
  const release = presentDatasetDateOnly(form.release_date_label, form.date_format || undefined);

  const metadata: DatasetDetailMetadataItem[] = [
    { label: "Source", value: sourceName, href: sourceHref ?? undefined },
    { label: "Instances", value: extractInstanceCount(metrics) },
    { label: "Features", value: fields.length ? String(fields.length) : null },
    { label: "Target", value: context?.prediction_target_description || context?.problem_type || null },
    {
      label: "Release",
      value: release?.value ?? null,
      hint: release ? `Format: ${release.effectiveFormat}` : undefined,
    },
  ];

  return {
    datasetTitle,
    subtitle,
    analysisType: context?.problem_type,
    metadata,
    problemSummaryTitle,
    problemSummaryBody,
  };
}

export function toVisualizationsPayload(value: unknown): VisualizationsPayload | null {
  if (value && typeof value === "object" && "charts" in value) {
    return value as VisualizationsPayload;
  }
  return null;
}

function selectedBand(bands: BinaryRiskBand[], probability: number): BinaryRiskBand | null {
  const matches = bands.filter((band, index) =>
    probability >= band.lower_bound &&
    (probability < band.upper_bound || (index === bands.length - 1 && probability === 1 && band.upper_bound === 1)),
  );
  return matches.length === 1 ? matches[0] : null;
}

/**
 * Creates an Admin-only synthetic result from governed release semantics.
 * This helper is deliberately separate from real inference consumption: it
 * accepts no API result and performs no I/O.
 */
export function projectBinaryResultPreview(
  semantics: BinaryResultSemantics,
  presentation: BinaryResultPresentation,
  probability: number,
): BinaryClassificationResult | null {
  if (!Number.isFinite(probability) || probability < 0 || probability > 1) return null;
  if (semantics.interpretation.preset !== "risk" || presentation.interpretation.preset !== "risk") return null;
  if (semantics.interpretation.bands.length !== 3) return null;
  if (semantics.positive_class.class_id === semantics.negative_class.class_id) return null;

  const band = selectedBand(semantics.interpretation.bands, probability);
  if (!band) return null;
  const predictedPositive = probability >= semantics.decision.threshold;

  return {
    schema_version: "binary-classification-result.v1",
    problem_type: "binary_classification",
    predicted_class: predictedPositive ? { class_id: semantics.positive_class.class_id } : semantics.negative_class,
    positive_class: semantics.positive_class,
    positive_class_probability: probability,
    class_probabilities: [
      { class_id: semantics.negative_class.class_id, probability: 1 - probability },
      { class_id: semantics.positive_class.class_id, probability },
    ],
    decision: { threshold: semantics.decision.threshold, predicted_positive: predictedPositive },
    interpretation: {
      preset: semantics.interpretation.preset,
      band_id: band.band_id,
      bands: semantics.interpretation.bands,
    },
    model_descriptor: semantics.model_descriptor,
  };
}

export function positiveScenarioProbability(threshold: number): number {
  return threshold + (1 - threshold) / 2;
}

export function negativeScenarioProbability(threshold: number): number | null {
  return threshold > 0 ? threshold / 2 : null;
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
