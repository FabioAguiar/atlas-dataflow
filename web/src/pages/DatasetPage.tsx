import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetDetailHeader, {
  type DatasetDetailMetadataItem,
} from "../components/DatasetDetail/DatasetDetailHeader";
import DatasetDetailTabs from "../components/DatasetDetail/DatasetDetailTabs";
import FeatureImportance from "../components/DatasetDetail/FeatureImportance";
import PerformanceSummary from "../components/DatasetDetail/PerformanceSummary";
import TargetDistribution, { type VisualizationsPayload } from "../components/DatasetDetail/TargetDistribution";
import ModelCard from "../components/ModelCard/ModelCard";
import InferenceForm, { ContractPayload } from "../components/InferenceForm/InferenceForm";
import LoadingState from "../components/LoadingState/LoadingState";
import ErrorState from "../components/ErrorState/ErrorState";
import PredictViewList, { PredictViewItem } from "../components/PredictViewList/PredictViewList";

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
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [metricsState, setMetricsState] = useState<SectionState<MetricsData>>({ status: "loading" });
  const [modelCardState, setModelCardState] = useState<SectionState<ModelCardPayload>>({ status: "loading" });
  const [visualizationsState, setVisualizationsState] = useState<SectionState<VisualizationsPayload>>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractPayload>>({ status: "loading" });
  const [contextState, setContextState] = useState<SectionState<PublicContextPayload>>({ status: "loading" });
  const [viewsState, setViewsState] = useState<SectionState<PredictViewListPayload>>({ status: "loading" });

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
    { label: "Source", value: null },
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
    { label: "Release", value: null, hint: "Format: dd/mm/yyyy" },
  ];

  const inferenceContent = (
    <>
      {contractState.status === "loading" && <LoadingState />}
      {contractState.status === "ready" && (
        <InferenceForm contract={contractState.data} slug={slug!} />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </>
  );

  const problemSummaryText = getProblemSummaryText(context);

  const overviewContent = (
    <>
      {contextState.status === "loading" && <LoadingState />}
      {contextState.status === "ready" && problemSummaryText && (
        <section className="dataset-detail-overview__problem-summary">
          <h3>Problem summary</h3>
          <p>{problemSummaryText}</p>
        </section>
      )}

      {metricsState.status === "loading" && <LoadingState />}
      {metricsState.status === "ready" && (
        <PerformanceSummary metrics={metricsState.data} />
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
    </>
  );

  return (
    <div className="dataset-detail">
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
