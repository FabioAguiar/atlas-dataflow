import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetAccessState, { classifyDatasetAccessError } from "../components/DatasetDetail/DatasetAccessState";
import DatasetDetailSurface, {
  type DatasetDetailMetadataItem,
} from "../components/DatasetDetail/DatasetDetailSurface";
import DatasetDocumentation from "../components/DatasetDetail/DatasetDocumentation";
import ConfusionMatrix from "../components/DatasetDetail/ConfusionMatrix";
import FeatureImportance from "../components/DatasetDetail/FeatureImportance";
import ForecastingDiagnostics from "../components/DatasetDetail/ForecastingDiagnostics";
import PerformanceSummary, { type PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";
import RegressionDiagnostics from "../components/DatasetDetail/RegressionDiagnostics";
import TargetDistribution, { type VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import InferenceForm, {
  ContractPayload,
  isForecastingContractPayload,
  PredictViewCustomization,
} from "../components/InferenceForm/InferenceForm";
import {
  availableResultProblemType,
  isAvailableBinaryResultContract,
  isAvailableContinuousRegressionResultContract,
  isAvailableForecastingResultContract,
  type ResultContract,
  type ResultPresentation,
} from "../components/ResultCard/types";
import LoadingState from "../components/LoadingState/LoadingState";
import ErrorState from "../components/ErrorState/ErrorState";
import {
  datasetThemeStyle,
  presentDatasetDateOnly,
  resolveDatasetTargetDescription,
  resolveDatasetThemePreset,
  resolveModelDisplayName,
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
  result_card?: ResultPresentation | null;
  documentation?: { format: "markdown"; content: string } | null;
};

type ContractEnvelope = {
  contract: ContractPayload;
  result_contract: ResultContract;
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

/**
 * Project Spec S0205: Instances now reads the bounded prepared-dataset
 * population the public visualizations projection derived
 * (visualizations.dataset_statistics.instance_count) instead of
 * metrics.evaluation.sample_size (a held-out evaluation split size, not the
 * full dataset population). This extractor only verifies the already-derived
 * count's shape and formats it for display -- it never sums chart values
 * itself.
 */
function extractInstanceCount(visualizations: VisualizationsPayload | null): string | null {
  const count = visualizations?.dataset_statistics?.instance_count;
  if (typeof count === "number" && Number.isFinite(count) && Number.isInteger(count) && count > 0) {
    return count.toLocaleString();
  }
  return null;
}

/**
 * Project Spec S0250: source predictive/exogenous feature count for the
 * "Features" metadata item. A scalar v1 contract reports its existing
 * features.length unchanged. A univariate-forecasting v2 contract always
 * reports 0 -- the capability forbids source exogenous predictors, and the
 * two governed history-series row fields (time index, target) are never
 * counted as predictive features.
 */
function resolveFeatureCount(contract: ContractPayload | null): string | null {
  if (!contract) return null;
  return isForecastingContractPayload(contract) ? "0" : String(contract.features.length);
}

/** "binary_classification" -> "Binary Classification"; never exposes the raw technical identifier. */
function humanizeProblemType(problemType: string | null | undefined): string | null {
  const trimmed = problemType?.trim();
  if (!trimmed) {
    return null;
  }
  return trimmed
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Project Spec S0127: release-bound result semantics stay authoritative for
 * inference-capable datasets; public context's own problem_type is only a
 * fallback for historical releases without result semantics.
 */
function resolveAnalysisType(
  resultContract: ResultContract | null,
  context: PublicContextPayload | null,
): string | null {
  const releaseBoundProblemType = availableResultProblemType(resultContract);
  return humanizeProblemType(releaseBoundProblemType) ?? humanizeProblemType(context?.problem_type) ?? null;
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
          result_contract: ResultContract;
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
  const resultContract = contractState.status === "ready" ? contractState.data.result_contract : null;
  const analysisType = resolveAnalysisType(resultContract, context) ?? undefined;
  const modelDisplayName = resolveModelDisplayName(resultContract);
  const sourceName = nonBlank(context?.source_name);
  const sourceHref = sourceName ? safePublicSourceUrl(context?.source_url) : null;
  const release = presentDatasetDateOnly(context?.release_date_label, context?.date_format);
  const instanceCount =
    visualizationsState.status === "ready" ? extractInstanceCount(visualizationsState.data) : null;

  const metadataItems: DatasetDetailMetadataItem[] = [
    { label: "Source", value: sourceName, href: sourceHref ?? undefined },
    {
      label: "Instances",
      value: instanceCount,
    },
    {
      label: "Features",
      value: contractState.status === "ready" ? resolveFeatureCount(contractState.data.contract) : null,
    },
    {
      label: "Target",
      value: resolveDatasetTargetDescription(
        isAvailableBinaryResultContract(resultContract) ? resultContract : null,
        context?.prediction_target_description,
      ),
    },
    {
      label: "Release",
      value: release?.value ?? null,
      hint: release ? release.effectiveFormat : undefined,
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
          customization={boundViewCustomization ?? undefined}
          submitButtonLabel={resolvedSubmitButtonLabel}
          resultContract={contractState.data.result_contract}
          resultPresentation={context?.result_card ?? undefined}
          // Project Spec S0141: only the public Dataset Detail route opts
          // into the zero-probability initial Result Card projection -- the
          // bound Predict View route (DatasetViewPage.tsx) intentionally
          // omits this prop and keeps its existing idle-placeholder behavior.
          initialResultProbability={0}
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
          // Project Spec S0215: the same release-derived problem type
          // already established by S0213 -- never dataset slug or
          // editable profile fields.
          problemType={availableResultProblemType(resultContract)}
        />
      )}
      {metricsState.status === "unavailable" && (
        <ErrorState message="Metrics are temporarily unavailable." />
      )}
    </>
  );

  // Project Spec S0248: gated on the same release-bound result contract
  // authority as Performance Summary/RegressionDiagnostics below -- a
  // forecasting release omits Target Distribution/Feature Importance
  // entirely (never a placeholder empty state) rather than rendering charts
  // a v4 visualizations payload never carries.
  const isForecastingRelease = isAvailableForecastingResultContract(resultContract);

  const targetDistributionContent = isForecastingRelease ? null : (
    <>
      {visualizationsState.status === "loading" && <LoadingState />}
      {visualizationsState.status !== "loading" && (
        <TargetDistribution
          visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
        />
      )}
    </>
  );

  const featureImportanceContent = isForecastingRelease ? null : (
    <>
      {visualizationsState.status === "loading" && <LoadingState />}
      {visualizationsState.status !== "loading" && (
        <FeatureImportance
          visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
        />
      )}
    </>
  );

  // Project Spec S0215: ConfusionMatrix renders nothing on its own whenever
  // the visualizations payload carries no valid confusion_matrix (every
  // binary/forecasting release), so no additional problem-type gating is
  // needed here -- Dataset Detail stays visually unchanged for those releases.
  const confusionMatrixContent =
    visualizationsState.status === "ready" ? (
      <ConfusionMatrix visualizations={visualizationsState.data} />
    ) : null;

  // Project Spec S0228: RegressionDiagnostics renders only for an available
  // continuous-regression release, gated on the same release-bound result
  // contract authority as Performance Summary above -- never a second
  // /visualizations request, and never rendered alongside binary/multiclass
  // Confusion Matrix content or a forecasting release.
  const regressionDiagnosticsContent =
    visualizationsState.status === "ready" && isAvailableContinuousRegressionResultContract(resultContract) ? (
      <RegressionDiagnostics visualizations={visualizationsState.data} />
    ) : null;

  // Project Spec S0248: ForecastingDiagnostics renders only for an available
  // univariate-forecasting release, gated on the same release-bound result
  // contract authority above -- never a second /visualizations request.
  const forecastingDiagnosticsContent =
    visualizationsState.status === "ready" && isForecastingRelease ? (
      <ForecastingDiagnostics visualizations={visualizationsState.data} />
    ) : null;

  // Project Spec S0196: the public Documentation tab renders only the
  // published snapshot's documentation (context.documentation), through the
  // same shared renderer the Admin Documentation tab and Live Preview use --
  // never a second, private Admin request.
  const documentationContent = <DatasetDocumentation content={context?.documentation} />;

  // Project Spec S0130: the route-level canvas resolves the same theme
  // authority/tokens DatasetDetailSurface itself applies -- never a second,
  // divergent theme mapping -- so the full-bleed public main region is
  // themed edge to edge while the inner content column stays constrained.
  const routeTheme = resolveDatasetThemePreset(context?.theme_preset);

  return (
    <div
      className="dataset-detail-page-canvas dataset-theme-scope"
      data-theme-preset={routeTheme.id}
      style={datasetThemeStyle(context?.theme_preset)}
    >
      <div className="dataset-detail-page-content app-shell public-shell__main">
        <DatasetDetailSurface
          analysisType={analysisType}
          confusionMatrixContent={confusionMatrixContent}
          datasetSubtitle={datasetSubtitle}
          datasetTitle={datasetTitle}
          documentationContent={documentationContent}
          featureImportanceContent={featureImportanceContent}
          forecastingDiagnosticsContent={forecastingDiagnosticsContent}
          inferenceContent={inferenceContent}
          metadata={metadataItems}
          modelDisplayName={modelDisplayName}
          performanceContent={performanceContent}
          performanceFocusId={context?.performance_focus?.focus_id}
          problemSummaryBody={problemSummaryText}
          problemSummaryTitle={problemSummaryTitle}
          regressionDiagnosticsContent={regressionDiagnosticsContent}
          targetDistributionContent={targetDistributionContent}
          themePresetId={context?.theme_preset}
        />
      </div>
    </div>
  );
}
