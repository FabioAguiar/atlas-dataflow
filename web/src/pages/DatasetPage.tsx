import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetAccessState, { classifyDatasetAccessError } from "../components/DatasetDetail/DatasetAccessState";
import DatasetDetailSurface, {
  type DatasetDetailMetadataItem,
} from "../components/DatasetDetail/DatasetDetailSurface";
import FeatureImportance from "../components/DatasetDetail/FeatureImportance";
import PerformanceSummary, { type PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";
import TargetDistribution, { type VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import InferenceForm, { ContractPayload, PredictViewCustomization } from "../components/InferenceForm/InferenceForm";
import type { BinaryResultContract, BinaryResultPresentation } from "../components/ResultCard/types";
import LoadingState from "../components/LoadingState/LoadingState";
import ErrorState from "../components/ErrorState/ErrorState";
import {
  presentDatasetDateOnly,
  safePublicSourceUrl,
} from "../lib/datasetPresentation";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetMetadata = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
  display_title?: string | null;
  display_subtitle?: string | null;
  short_description?: string | null;
};

type PublicContextPayload = {
  title?: string;
  summary?: string;
  description?: string;
  domain?: string;
  tags?: string[];
  use_case?: string;
  problem_type?: string;
  prediction_target_description?: string;
  display_title?: string | null;
  display_subtitle?: string | null;
  short_description?: string | null;
  problem_summary_title?: string | null;
  problem_summary_body?: string | null;
  source_name?: string | null;
  source_url?: string | null;
  release_date_label?: string | null;
  date_format?: "dd/mm/yyyy" | "mm/dd/yyyy" | "yyyy-mm-dd" | null;
  canonical_name_fallback?: boolean | null;
  primary_metric_key?: string | null;
  performance_focus?: PerformanceFocus | null;
  theme_preset?: string | null;
  bound_predict_view_id?: string | null;
  legacy_submit_button_label?: string | null;
  result_card?: BinaryResultPresentation | null;
};

type ContractEnvelope = {
  contract: ContractPayload;
  result_contract: BinaryResultContract;
};

type MetricsData = Record<string, unknown>;

type PageState =
  | { status: "loading" }
  | { status: "ready"; data: DatasetMetadata }
  | { status: "maintenance" }
  | { status: "not_found" }
  | { status: "unavailable" };

type SectionState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable" };

function nonBlank(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed || null;
}

function getProblemSummaryText(context: PublicContextPayload | null): string | null {
  return nonBlank(context?.problem_summary_body)
    || nonBlank(context?.description)
    || nonBlank(context?.use_case)
    || nonBlank(context?.summary);
}

function extractInstanceCount(metrics: MetricsData): string | null {
  const evaluation = metrics["evaluation"];
  if (evaluation && typeof evaluation === "object") {
    const sampleSize = (evaluation as Record<string, unknown>)["sample_size"];
    if (typeof sampleSize === "number" && Number.isFinite(sampleSize)) {
      return sampleSize.toLocaleString();
    }
  }
  return null;
}

export default function DatasetPage() {
  const { slug } = useParams<{ slug: string }>();
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [metricsState, setMetricsState] = useState<SectionState<MetricsData>>({ status: "loading" });
  const [visualizationsState, setVisualizationsState] = useState<SectionState<VisualizationsPayload>>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractEnvelope>>({ status: "loading" });
  const [contextState, setContextState] = useState<SectionState<PublicContextPayload>>({ status: "loading" });
  const [boundViewCustomizationState, setBoundViewCustomizationState] = useState<
    SectionState<PredictViewCustomization | null>
  >({ status: "loading" });

  useEffect(() => {
    if (!slug) {
      setState({ status: "not_found" });
      return;
    }

    // Project Spec S0117: reset to loading immediately on every slug
    // change so a slug switch never briefly shows the previous dataset's
    // content or a premature not-found state before the new response
    // arrives.
    setState({ status: "loading" });

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}`, {
      signal: controller.signal,
    })
      .then(async (res) => {
        if (res.ok) {
          const data = (await res.json()) as DatasetMetadata;
          setState({ status: "ready", data });
          return;
        }
        let body: unknown = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        setState({ status: classifyDatasetAccessError(body) });
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  // Project Spec S0117: every auxiliary request below is gated behind the
  // primary route request reaching "ready" -- no context/contract/metrics/
  // visualizations/bound-view-customization request is ever sent while the
  // primary state is loading, maintenance, not_found, or unavailable.
  const primaryReady = state.status === "ready";

  useEffect(() => {
    if (!slug) {
      setContextState({ status: "unavailable" });
      return;
    }
    if (!primaryReady) {
      setContextState({ status: "loading" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/context`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setContextState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<{ dataset_slug: string; context: PublicContextPayload }>;
      })
      .then((data) => {
        if (data) {
          setContextState({ status: "ready", data: data.context });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setContextState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, primaryReady]);

  // Project Spec S0110: resolves the published bound predict view's
  // customization for the default route's submit-button copy. Never
  // auto-selects an arbitrary first view -- only fetches when the published
  // context actually names a bound_predict_view_id. A transport failure or
  // missing customization falls through to the legacy/"Submit" fallback
  // instead of removing the form.
  const boundPredictViewId = contextState.status === "ready" ? contextState.data.bound_predict_view_id : null;

  useEffect(() => {
    if (!slug || !primaryReady || !boundPredictViewId) {
      setBoundViewCustomizationState({ status: "ready", data: null });
      return;
    }

    const controller = new AbortController();

    fetch(
      `${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/views/${encodeURIComponent(boundPredictViewId)}/customization`,
      { signal: controller.signal },
    )
      .then((res) => {
        if (res.status === 404) {
          setBoundViewCustomizationState({ status: "ready", data: null });
          return null;
        }
        if (!res.ok) {
          setBoundViewCustomizationState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<PredictViewCustomization>;
      })
      .then((data) => {
        if (data) {
          setBoundViewCustomizationState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setBoundViewCustomizationState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, primaryReady, boundPredictViewId]);

  useEffect(() => {
    if (!slug) {
      setMetricsState({ status: "unavailable" });
      return;
    }
    if (!primaryReady) {
      setMetricsState({ status: "loading" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/metrics`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setMetricsState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<{ dataset_slug: string; metrics: MetricsData }>;
      })
      .then((data) => {
        if (data) {
          setMetricsState({ status: "ready", data: data.metrics });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setMetricsState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, primaryReady]);

  useEffect(() => {
    if (!slug) {
      setVisualizationsState({ status: "unavailable" });
      return;
    }
    if (!primaryReady) {
      setVisualizationsState({ status: "loading" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/visualizations`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setVisualizationsState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<{ dataset_slug: string; visualizations: VisualizationsPayload }>;
      })
      .then((data) => {
        if (data) {
          setVisualizationsState({ status: "ready", data: data.visualizations });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setVisualizationsState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, primaryReady]);

  useEffect(() => {
    if (!slug) {
      setContractState({ status: "unavailable" });
      return;
    }
    if (!primaryReady) {
      setContractState({ status: "loading" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/contract`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setContractState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<{
          dataset_slug: string;
          contract: ContractPayload;
          result_contract: BinaryResultContract;
        }>;
      })
      .then((data) => {
        if (data) {
          setContractState({
            status: "ready",
            data: { contract: data.contract, result_contract: data.result_contract },
          });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setContractState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, primaryReady]);

  if (state.status === "loading") {
    return (
      <>
        <p>Loading…</p>
      </>
    );
  }

  if (state.status !== "ready") {
    return <DatasetAccessState kind={state.status} />;
  }

  const context = contextState.status === "ready" ? contextState.data : null;

  const datasetTitle = nonBlank(context?.display_title)
    || nonBlank(state.data.display_title)
    || nonBlank(context?.title)
    || state.data.title;
  const datasetSubtitle = nonBlank(context?.display_subtitle)
    || nonBlank(state.data.display_subtitle)
    || nonBlank(context?.summary)
    || nonBlank(context?.description)
    || nonBlank(state.data.summary)
    || undefined;
  const analysisType = context?.problem_type;
  const sourceName = nonBlank(context?.source_name);
  const sourceHref = sourceName ? safePublicSourceUrl(context?.source_url) : null;
  const release = presentDatasetDateOnly(context?.release_date_label, context?.date_format);

  const metadataItems: DatasetDetailMetadataItem[] = [
    { label: "Source", value: sourceName, href: sourceHref ?? undefined },
    {
      label: "Instances",
      value: metricsState.status === "ready" ? extractInstanceCount(metricsState.data) : null,
    },
    {
      label: "Features",
      value: contractState.status === "ready" ? String(contractState.data.contract.features.length) : null,
    },
    {
      label: "Target",
      value: context?.prediction_target_description || context?.problem_type || null,
    },
    {
      label: "Release",
      value: release?.value ?? null,
      hint: release ? `Format: ${release.effectiveFormat}` : undefined,
    },
  ];

  // Project Spec S0110: same precedence rule DatasetViewPage.tsx applies --
  // customization always wins, blank strings are treated as absent, legacy
  // is a read-only fallback, and "Submit" is InferenceForm's own UI-only
  // default (never persisted here).
  const boundViewCustomization =
    boundViewCustomizationState.status === "ready" ? boundViewCustomizationState.data : null;
  const resolvedSubmitButtonLabel =
    boundViewCustomization?.view_copy?.submit_button_label?.trim() ||
    context?.legacy_submit_button_label?.trim() ||
    undefined;

  const inferenceContent = (
    <>
      {contractState.status === "loading" && <LoadingState />}
      {contractState.status === "ready" && (
        <InferenceForm
          contract={contractState.data.contract}
          slug={slug!}
          submitButtonLabel={resolvedSubmitButtonLabel}
          resultContract={contractState.data.result_contract}
          resultPresentation={context?.result_card ?? undefined}
        />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </>
  );

  const problemSummaryText = getProblemSummaryText(context);
  const problemSummaryTitle = nonBlank(context?.problem_summary_title) || "Problem summary";

  const performanceContent = (
    <>
      {metricsState.status === "loading" && <LoadingState />}
      {metricsState.status === "ready" && (
        <PerformanceSummary
          metrics={metricsState.data}
          emphasizedMetricKey={context?.primary_metric_key}
          performanceFocus={context?.performance_focus}
        />
      )}
      {metricsState.status === "unavailable" && (
        <ErrorState message="Metrics are temporarily unavailable." />
      )}
    </>
  );

  const targetDistributionContent = (
    <>
      {visualizationsState.status === "loading" && <LoadingState />}
      {visualizationsState.status !== "loading" && (
        <TargetDistribution
          visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
        />
      )}
    </>
  );

  const featureImportanceContent = (
    <>
      {visualizationsState.status === "loading" && <LoadingState />}
      {visualizationsState.status !== "loading" && (
        <FeatureImportance
          visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
        />
      )}
    </>
  );

  return (
    <DatasetDetailSurface
      analysisType={analysisType}
      datasetSubtitle={datasetSubtitle}
      datasetTitle={datasetTitle}
      featureImportanceContent={featureImportanceContent}
      inferenceContent={inferenceContent}
      metadata={metadataItems}
      performanceContent={performanceContent}
      problemSummaryBody={problemSummaryText}
      problemSummaryTitle={problemSummaryTitle}
      targetDistributionContent={targetDistributionContent}
      themePresetId={context?.theme_preset}
    />
  );
}
