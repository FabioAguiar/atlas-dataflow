import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetHeader from "../components/DatasetHeader";
import MetricsDisplay from "../components/MetricsDisplay/MetricsDisplay";
import ModelCard from "../components/ModelCard/ModelCard";
import DatasetVisualizations, { VisualizationsPayload } from "../components/DatasetVisualizations/DatasetVisualizations";
import InferenceForm, { ContractPayload } from "../components/InferenceForm/InferenceForm";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetMetadata = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
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

export default function DatasetPage() {
  const { slug } = useParams<{ slug: string }>();
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [metricsState, setMetricsState] = useState<SectionState<MetricsData>>({ status: "loading" });
  const [modelCardState, setModelCardState] = useState<SectionState<ModelCardPayload>>({ status: "loading" });
  const [visualizationsState, setVisualizationsState] = useState<SectionState<VisualizationsPayload>>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractPayload>>({ status: "loading" });

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

  if (state.status === "loading") {
    return (
      <main className="app-shell">
        <p>Loading…</p>
      </main>
    );
  }

  if (state.status === "not_found") {
    return (
      <main className="app-shell">
        <p>Dataset not found.</p>
      </main>
    );
  }

  if (state.status === "unavailable") {
    return (
      <main className="app-shell">
        <p>Dataset information is currently unavailable. Please try again later.</p>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <DatasetHeader title={state.data.title} summary={state.data.summary} />

      {metricsState.status === "ready" && (
        <MetricsDisplay metrics={metricsState.data} />
      )}
      {metricsState.status === "unavailable" && (
        <p>Metrics are currently unavailable.</p>
      )}

      {modelCardState.status === "ready" && (
        <ModelCard modelCard={modelCardState.data} />
      )}
      {modelCardState.status === "unavailable" && (
        <p>Model card is currently unavailable.</p>
      )}

      {visualizationsState.status === "ready" && (
        <DatasetVisualizations visualizations={visualizationsState.data} />
      )}
      {visualizationsState.status === "unavailable" && (
        <p>Visualizations are currently unavailable.</p>
      )}

      {contractState.status === "ready" && (
        <InferenceForm contract={contractState.data} slug={slug!} />
      )}
      {contractState.status === "unavailable" && (
        <p>Form inputs are currently unavailable.</p>
      )}
    </main>
  );
}
