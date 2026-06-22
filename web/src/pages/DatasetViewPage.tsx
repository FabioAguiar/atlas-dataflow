import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import InferenceForm, { ContractPayload } from "../components/InferenceForm/InferenceForm";
import LoadingState from "../components/LoadingState/LoadingState";
import ErrorState from "../components/ErrorState/ErrorState";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type ViewPayload = {
  view_id: string;
  dataset_slug: string;
  display: { title?: string; summary?: string; description?: string; tags?: string[] };
  intent: { prediction_goal?: string; audience?: string; usage_notes?: string };
  release_mode: string | null;
};

type ViewState =
  | { status: "loading" }
  | { status: "ready"; data: ViewPayload }
  | { status: "not_found" }
  | { status: "unavailable" };

type SectionState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable" };

export default function DatasetViewPage() {
  const { slug, viewId } = useParams<{ slug: string; viewId: string }>();
  const [viewState, setViewState] = useState<ViewState>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractPayload>>({ status: "loading" });

  useEffect(() => {
    if (!slug || !viewId) {
      setViewState({ status: "not_found" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/views/${encodeURIComponent(viewId)}`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (res.status === 404) {
          setViewState({ status: "not_found" });
          return null;
        }
        if (!res.ok) {
          setViewState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<ViewPayload>;
      })
      .then((data) => {
        if (data) {
          setViewState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setViewState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, viewId]);

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

  if (viewState.status === "loading") {
    return (
      <main className="app-shell">
        <LoadingState />
      </main>
    );
  }

  if (viewState.status === "not_found") {
    return (
      <main className="app-shell">
        <p>This predict view is not available.</p>
      </main>
    );
  }

  if (viewState.status === "unavailable") {
    return (
      <main className="app-shell">
        <ErrorState message="This predict view is temporarily unavailable. Please try again later." />
      </main>
    );
  }

  const view = viewState.data;

  return (
    <main className="app-shell">
      <section aria-labelledby="view-title">
        <h1 id="view-title">{view.display.title ?? view.view_id}</h1>
        {view.display.summary && <p>{view.display.summary}</p>}
        {view.intent.prediction_goal && (
          <p><strong>Goal:</strong> {view.intent.prediction_goal}</p>
        )}
        {view.intent.audience && (
          <p><strong>Audience:</strong> {view.intent.audience}</p>
        )}
      </section>

      {contractState.status === "loading" && <LoadingState />}
      {contractState.status === "ready" && (
        <InferenceForm contract={contractState.data} slug={slug!} />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </main>
  );
}
