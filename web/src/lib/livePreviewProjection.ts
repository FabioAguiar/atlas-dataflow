import type { DatasetDetailMetadataItem } from "../components/DatasetDetail/DatasetDetailHeader";
import type { VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import {
  projectBinaryClassificationResult,
  type BinaryClassificationResult,
  type BinaryResultPresentation,
  type BinaryResultSemantics,
} from "../components/ResultCard/types";
import type { DatasetIconName } from "./datasetPresentation";
import type { PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";
import {
  presentDatasetDateOnly,
  resolveDatasetTargetDescription,
  safePublicSourceUrl,
  type DatasetDateFormat,
} from "./datasetPresentation";

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

// Project Spec S0154: structurally compatible with DatasetAdminPage.tsx's
// own private ResultContractState (idle/loading/available/unavailable/
// transport_failure/incompatible) -- declared locally, per this module's
// existing convention, so it never imports a page type.
type PreviewResultContract =
  | { status: "idle" | "loading" }
  | { status: "available"; semantics: BinaryResultSemantics }
  | { status: "unavailable" | "transport_failure" | "incompatible"; message?: string };

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
  // Project Spec S0204: the draft's current Performance focus selection --
  // only focus_id participates in Live Preview projection here; scores and
  // the highlighted score id remain owned by projectPerformanceFocusPreview.
  performance_focus: { focus_id: PerformanceFocus["focus_id"] };
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
  performanceFocusId?: string | null;
};

export type DatasetDetailPreview = {
  datasetTitle: string;
  subtitle?: string;
  analysisType?: string;
  metadata: DatasetDetailMetadataItem[];
  problemSummaryTitle: string;
  problemSummaryBody: string | null;
  performanceFocusId?: string | null;
};

function contractFields(contract: PreviewContract | null): PreviewContractField[] {
  return contract?.fields ?? contract?.inputs ?? contract?.input_schema?.fields ?? [];
}

/**
 * Project Spec S0205: mirrors DatasetPage.tsx's own bounded extractor --
 * Instances reads the already-loaded visualizations projection's
 * dataset_statistics.instance_count, never metrics.evaluation.sample_size
 * and never a sum over chart values.
 */
function extractInstanceCount(visualizations: VisualizationsPayload | null): string | null {
  const count = visualizations?.dataset_statistics?.instance_count;
  if (typeof count === "number" && Number.isFinite(count) && Number.isInteger(count) && count > 0) {
    return count.toLocaleString();
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
  form: Pick<
    PreviewDraftForm,
    "display_title" | "display_subtitle" | "short_description" | "home_card_icon" | "performance_focus"
  >,
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
    performanceFocusId: form.performance_focus.focus_id,
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
 * a JavaScript-timestamp-derived date. Project Spec S0154: Target reuses the
 * same shared datasetPresentation.resolveDatasetTargetDescription helper
 * DatasetPage.tsx calls, fed from the currently loaded, dataset-bound
 * resultContract (the private authoring context's result-contract state,
 * never an extra request), so both surfaces share one Target authority.
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
    | "performance_focus"
  >,
  context: PreviewContext | null,
  contract: PreviewContract | null,
  metrics: PreviewMetrics | null,
  resultContract?: PreviewResultContract | null,
  visualizations?: VisualizationsPayload | null,
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
    { label: "Instances", value: extractInstanceCount(visualizations ?? null) },
    { label: "Features", value: fields.length ? String(fields.length) : null },
    {
      label: "Target",
      value: resolveDatasetTargetDescription(resultContract, context?.prediction_target_description),
    },
    {
      label: "Release",
      value: release?.value ?? null,
      hint: release ? release.effectiveFormat : undefined,
    },
  ];

  return {
    datasetTitle,
    subtitle,
    analysisType: context?.problem_type,
    metadata,
    problemSummaryTitle,
    problemSummaryBody,
    performanceFocusId: form.performance_focus.focus_id,
  };
}

export function toVisualizationsPayload(value: unknown): VisualizationsPayload | null {
  if (value && typeof value === "object" && "charts" in value) {
    return value as VisualizationsPayload;
  }
  return null;
}

/**
 * Creates an Admin-only synthetic result from governed release semantics
 * for the interactive scenario preview. The technical result itself is
 * constructed entirely through the shared projectBinaryClassificationResult
 * boundary (Project Spec S0141) -- this wrapper only adds the Admin
 * preview's own presentation-preset compatibility guard on top. This helper
 * is deliberately separate from real inference consumption: it accepts no
 * API result and performs no I/O.
 */
export function projectBinaryResultPreview(
  semantics: BinaryResultSemantics,
  presentation: BinaryResultPresentation,
  probability: number,
): BinaryClassificationResult | null {
  if (presentation.interpretation.preset !== "risk") return null;
  return projectBinaryClassificationResult(semantics, probability);
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
