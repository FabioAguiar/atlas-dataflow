import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import InferenceForm, { ContractPayload, PredictViewCustomization } from "../components/InferenceForm/InferenceForm";
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
  const [customizationState, setCustomizationState] = useState<SectionState<PredictViewCustomization | null>>({ status: "loading" });

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

  useEffect(() => {
    if (!slug || !viewId) {
      setCustomizationState({ status: "ready", data: null });
      return;
    }

    const controller = new AbortController();

    fetch(
      `${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/views/${encodeURIComponent(viewId)}/customization`,
      { signal: controller.signal }
    )
      .then((res) => {
        if (res.status === 404) {
          setCustomizationState({ status: "ready", data: null });
          return null;
        }
        if (!res.ok) {
          setCustomizationState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<PredictViewCustomization>;
      })
      .then((data) => {
        if (data) {
          setCustomizationState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setCustomizationState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug, viewId]);

  if (viewState.status === "loading") {
    return (
      <>
        <LoadingState />
      </>
    );
  }

  if (viewState.status === "not_found") {
    return (
      <>
        <p>This predict view is not available.</p>
      </>
    );
  }

  if (viewState.status === "unavailable") {
    return (
      <>
        <ErrorState message="This predict view is temporarily unavailable. Please try again later." />
      </>
    );
  }

  const view = viewState.data;
  const customization =
    customizationState.status === "ready" && customizationState.data
      ? customizationState.data
      : undefined;

  const displayHeading =
    customization?.view_copy?.heading ?? view.display.title ?? view.view_id;

  return (
    <>
      <section aria-labelledby="view-title">
        <h1 id="view-title">{displayHeading}</h1>
        {customization?.view_copy?.description && (
          <p>{customization.view_copy.description}</p>
        )}
        {customization?.view_copy?.usage_guidance && (
          <p>{customization.view_copy.usage_guidance}</p>
        )}
        {!customization?.view_copy?.description && view.display.summary && (
          <p>{view.display.summary}</p>
        )}
        {view.intent.prediction_goal && (
          <p><strong>Goal:</strong> {view.intent.prediction_goal}</p>
        )}
        {view.intent.audience && (
          <p><strong>Audience:</strong> {view.intent.audience}</p>
        )}
      </section>

      {contractState.status === "loading" && <LoadingState />}
      {contractState.status === "ready" && (
        <InferenceForm contract={contractState.data} slug={slug!} customization={customization} />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </>
  );
}
