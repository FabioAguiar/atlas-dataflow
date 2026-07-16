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

// Project Spec S0110: only the minimum transitional legacy fallback field is
// read here -- api/public_profile_visibility.py's resolve_public_presentation_overlay
// projects legacy_submit_button_label from the published, deprecated
// result_card.submit_button_label only. No private draft is ever loaded by
// this public route.
type PublicContextOverlay = {
  legacy_submit_button_label?: string | null;
};

export default function DatasetViewPage() {
  const { slug, viewId } = useParams<{ slug: string; viewId: string }>();
  const [viewState, setViewState] = useState<ViewState>({ status: "loading" });
  const [contractState, setContractState] = useState<SectionState<ContractPayload>>({ status: "loading" });
  const [customizationState, setCustomizationState] = useState<SectionState<PredictViewCustomization | null>>({ status: "loading" });
  const [contextState, setContextState] = useState<SectionState<PublicContextOverlay>>({ status: "loading" });

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

  // Project Spec S0110: legacy fallback source for when this view's
  // customization has no submit_button_label yet. Loads only the safe
  // public context/presentation overlay -- never a private profile draft --
  // and never blocks the form on failure (falls through to "Submit").
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
        return res.json() as Promise<{ dataset_slug: string; context: PublicContextOverlay }>;
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

  // Project Spec S0110: deterministic resolution precedence -- customization
  // always wins, blank strings are treated as absent, legacy is a read-only
  // fallback, and "Submit" is InferenceForm's own UI-only default (never
  // persisted here).
  const legacySubmitButtonLabel =
    contextState.status === "ready" ? contextState.data.legacy_submit_button_label : null;
  const resolvedSubmitButtonLabel =
    customization?.view_copy?.submit_button_label?.trim() || legacySubmitButtonLabel?.trim() || undefined;

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
        <InferenceForm
          contract={contractState.data}
          slug={slug!}
          customization={customization}
          submitButtonLabel={resolvedSubmitButtonLabel}
        />
      )}
      {contractState.status === "unavailable" && (
        <ErrorState message="The prediction form is temporarily unavailable." />
      )}
    </>
  );
}
