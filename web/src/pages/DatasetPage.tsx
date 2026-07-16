import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetDetailHeader, {
  type DatasetDetailMetadataItem,
} from "../components/DatasetDetail/DatasetDetailHeader";
import DatasetDetailTabs from "../components/DatasetDetail/DatasetDetailTabs";
import FeatureImportance from "../components/DatasetDetail/FeatureImportance";
import PerformanceSummary, { type PerformanceFocus } from "../components/DatasetDetail/PerformanceSummary";
import TargetDistribution, { type VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import ModelCard from "../components/ModelCard/ModelCard";
import InferenceForm, { ContractPayload, PredictViewCustomization } from "../components/InferenceForm/InferenceForm";
import LoadingState from "../components/LoadingState/LoadingState";
import ErrorState from "../components/ErrorState/ErrorState";
import PredictViewList, { PredictViewItem } from "../components/PredictViewList/PredictViewList";
import { datasetThemeStyle, resolveDatasetThemePreset } from "../lib/datasetPresentation";

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
  source_name?: string | null;
  release_date_label?: string | null;
  primary_metric_key?: string | null;
  performance_focus?: PerformanceFocus | null;
  theme_preset?: string | null;
  bound_predict_view_id?: string | null;
  legacy_submit_button_label?: string | null;
};

type MetricsData = Record<string, unknown>;

type ModelCardPayload = {
  content: string;
  format: "markdown";
};

type PageState =
  | { status: "loading" }
  | { status: "ready"; data: DatasetMetadata }
  | { status: "not_found" }
  | { status: "unavailable" };

type SectionState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable" };

type PredictViewListPayload = {
  dataset_slug: string;
  views: PredictViewItem[];
};

function getProblemSummaryText(context: PublicContextPayload | null): string | null {
  return context?.description || context?.use_case || context?.summary || null;
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
  const inferenceLayoutRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [metricsState, setMetricsState] = useState<SectionState<MetricsData>>({ status: "loading" });
  const [modelCardState, setModelCardState] = useState<SectionState<ModelCardPayload>>({ status: "loading" });
  const [visualizationsState, setVisualizationsState] = useState<SectionState<VisualizationsPayload>>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractPayload>>({ status: "loading" });
  const [contextState, setContextState] = useState<SectionState<PublicContextPayload>>({ status: "loading" });
  const [viewsState, setViewsState] = useState<SectionState<PredictViewListPayload>>({ status: "loading" });
  const [boundViewCustomizationState, setBoundViewCustomizationState] = useState<
    SectionState<PredictViewCustomization | null>
  >({ status: "loading" });

  useEffect(() => {
    if (!slug) {
      setState({ status: "not_found" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (res.status === 404) {
          setState({ status: "not_found" });
          return null;
        }
        if (!res.ok) {
          setState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<DatasetMetadata>;
      })
      .then((data) => {
        if (data) {
          setState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  useEffect(() => {
    if (!slug) {
      setContextState({ status: "unavailable" });
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
  }, [slug]);

  // Project Spec S0110: resolves the published bound predict view's
  // customization for the default route's submit-button copy. Never
  // auto-selects an arbitrary first view -- only fetches when the published
  // context actually names a bound_predict_view_id. A transport failure or
  // missing customization falls through to the legacy/"Submit" fallback
  // instead of removing the form.
  const boundPredictViewId = contextState.status === "ready" ? contextState.data.bound_predict_view_id : null;

  useEffect(() => {
    if (!slug || !boundPredictViewId) {
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
  }, [slug, boundPredictViewId]);

  useEffect(() => {
    if (!slug) {
      setMetricsState({ status: "unavailable" });
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
  }, [slug]);

  useEffect(() => {
    if (!slug) {
      setModelCardState({ status: "unavailable" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/model-card`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setModelCardState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<{ dataset_slug: string; model_card: ModelCardPayload }>;
      })
      .then((data) => {
        if (data) {
          setModelCardState({ status: "ready", data: data.model_card });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setModelCardState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  useEffect(() => {
    if (!slug) {
      setVisualizationsState({ status: "unavailable" });
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
  }, [slug]);

  useEffect(() => {
    if (!slug) {
      setContractState({ status: "unavailable" });
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
        return res.json() as Promise<{ dataset_slug: string; contract: ContractPayload }>;
      })
      .then((data) => {
        if (data) {
          setContractState({ status: "ready", data: data.contract });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setContractState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  useEffect(() => {
    if (!slug) {
      setViewsState({ status: "unavailable" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/views`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          setViewsState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<PredictViewListPayload>;
      })
      .then((data) => {
        if (data) {
          setViewsState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setViewsState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  useEffect(() => {
    const layout = inferenceLayoutRef.current;
    if (!layout || contractState.status !== "ready") {
      return;
    }

    const findResultElement = () =>
      layout.querySelector<HTMLElement>(
        ".inference-result, .result-panel, [class*='result' i], [data-testid*='result' i]",
      );

    const updateStickyState = () => {
      const form = layout.querySelector<HTMLElement>("form");
      const result = findResultElement();
      const onlyChild = layout.children.length === 1 ? layout.firstElementChild : null;
      const bridge =
        onlyChild instanceof HTMLElement &&
        form &&
        result &&
        onlyChild !== form &&
        onlyChild !== result &&
        onlyChild.contains(form) &&
        onlyChild.contains(result)
          ? onlyChild
          : null;
      const shouldStick = Boolean(form && result && form.offsetHeight > result.offsetHeight);

      layout.querySelectorAll(".dataset-detail-inference__flow").forEach((element) => {
        if (element !== bridge) {
          element.classList.remove("dataset-detail-inference__flow");
        }
      });
      bridge?.classList.add("dataset-detail-inference__flow");
      layout.classList.toggle("dataset-detail-inference__layout--result-sticky", shouldStick);
    };

    updateStickyState();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateStickyState);
      return () => {
        layout.classList.remove("dataset-detail-inference__layout--result-sticky");
        layout.querySelectorAll(".dataset-detail-inference__flow").forEach((element) => {
          element.classList.remove("dataset-detail-inference__flow");
        });
        window.removeEventListener("resize", updateStickyState);
      };
    }

    const observer = new ResizeObserver(updateStickyState);
    observer.observe(layout);

    const form = layout.querySelector<HTMLElement>("form");
    const result = findResultElement();

    if (form) {
      observer.observe(form);
    }

    if (result) {
      observer.observe(result);
    }

    window.addEventListener("resize", updateStickyState);

    return () => {
      layout.classList.remove("dataset-detail-inference__layout--result-sticky");
      layout.querySelectorAll(".dataset-detail-inference__flow").forEach((element) => {
        element.classList.remove("dataset-detail-inference__flow");
      });
      observer.disconnect();
      window.removeEventListener("resize", updateStickyState);
    };
  }, [contractState.status]);

  if (state.status === "loading") {
    return (
      <>
        <p>Loading…</p>
      </>
    );
  }

  if (state.status === "not_found") {
    return (
      <>
        <p>Dataset not found.</p>
      </>
    );
  }

  if (state.status === "unavailable") {
    return (
      <>
        <p>Dataset information is currently unavailable. Please try again later.</p>
      </>
    );
  }

  const context = contextState.status === "ready" ? contextState.data : null;
  const resolvedTheme = resolveDatasetThemePreset(context?.theme_preset);

  const curatedTitle = context?.display_title || state.data.display_title;
  const datasetTitle = curatedTitle || context?.title || state.data.title;
  const curatedSubtitle =
    context?.short_description ||
    context?.display_subtitle ||
    state.data.short_description ||
    state.data.display_subtitle;
  const datasetSubtitle = curatedSubtitle || context?.summary || context?.description || state.data.summary;
  const analysisType = context?.problem_type;

  const metadataItems: DatasetDetailMetadataItem[] = [
    { label: "Source", value: context?.source_name || null },
    {
      label: "Instances",
      value: metricsState.status === "ready" ? extractInstanceCount(metricsState.data) : null,
    },
    {
      label: "Features",
      value: contractState.status === "ready" ? String(contractState.data.features.length) : null,
    },
    {
      label: "Target",
      value: context?.prediction_target_description || context?.problem_type || null,
    },
    { label: "Release", value: context?.release_date_label || null, hint: "Format: dd/mm/yyyy" },
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
    <div className="dataset-detail-inference__layout" ref={inferenceLayoutRef}>
      {contractState.status === "loading" && <LoadingState />}
      {contractState.status === "ready" && (
        <InferenceForm contract={contractState.data} slug={slug!} submitButtonLabel={resolvedSubmitButtonLabel} />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </div>
  );

  const problemSummaryText = getProblemSummaryText(context);

  const overviewContent = (
    <div className="dataset-detail-overview">
      {contextState.status === "loading" && <LoadingState />}
      {contextState.status === "ready" && problemSummaryText && (
        <section className="dataset-detail-overview__problem-summary">
          <h3>Problem summary</h3>
          <p>{problemSummaryText}</p>
        </section>
      )}

      <div className="dataset-detail-overview__analytics">
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

        {visualizationsState.status === "loading" && <LoadingState />}
        {visualizationsState.status !== "loading" && (
          <>
            <TargetDistribution
              visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
            />
            <FeatureImportance
              visualizations={visualizationsState.status === "ready" ? visualizationsState.data : null}
            />
          </>
        )}
      </div>
    </div>
  );

  return (
    <div
      className="dataset-detail dataset-theme-scope"
      data-theme-preset={resolvedTheme.id}
      style={datasetThemeStyle(resolvedTheme.id)}
    >
      <DatasetDetailHeader
        analysisType={analysisType}
        datasetTitle={datasetTitle}
        metadata={metadataItems}
        subtitle={datasetSubtitle}
      />

      <DatasetDetailTabs overviewContent={overviewContent} inferenceContent={inferenceContent} />

      {modelCardState.status === "loading" && <LoadingState />}
      {modelCardState.status === "ready" && (
        <ModelCard modelCard={modelCardState.data} />
      )}
      {modelCardState.status === "unavailable" && (
        <ErrorState message="The model card is temporarily unavailable." />
      )}

      {viewsState.status === "loading" && <LoadingState />}
      {viewsState.status === "ready" && (
        <PredictViewList views={viewsState.data.views} slug={slug!} />
      )}
      {viewsState.status === "unavailable" && (
        <ErrorState message="Predict views are temporarily unavailable." />
      )}
    </div>
  );
}
