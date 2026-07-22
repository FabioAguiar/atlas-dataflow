import { FormEvent, useEffect, useRef, useState } from "react";
import ResultCardShell from "../ResultCard/ResultCardShell";
import BinaryClassificationResult from "../ResultCard/BinaryClassificationResult";
import {
  GENERIC_RESULT_PRESENTATION,
  isAvailableBinaryResultContract,
  isBinaryClassificationResult,
  projectBinaryClassificationResult,
  type BinaryClassificationResult as BinaryClassificationResultData,
  type BinaryResultContract,
  type BinaryResultPresentation,
} from "../ResultCard/types";

export type FeatureOption = {
  value: string;
  label: string;
};

export type Feature = {
  name: string;
  label: string;
  input_type: "number" | "select" | "checkbox";
  optional: boolean;
  display_order: number;
  description?: string;
  options?: FeatureOption[];
};

export type ContractPayload = {
  schema_version: string;
  features: Feature[];
};

export type FieldHint = {
  field_name: string;
  display_label?: string;
  explanatory_copy?: string;
  display_order_hint?: number;
  group?: string;
  hidden?: boolean;
};

export type GroupDef = {
  group_id: string;
  label: string;
  description?: string;
};

export type PredictViewCustomization = {
  field_hints: FieldHint[];
  groups: GroupDef[];
  view_copy?: {
    heading?: string;
    description?: string;
    usage_guidance?: string;
    submit_button_label?: string;
  };
};

type SubmissionState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; data: BinaryClassificationResultData }
  | { status: "error"; message: string };

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

const ERROR_MESSAGES: Record<string, string> = {
  INVALID_PAYLOAD: "Some inputs are invalid. Please check your answers and try again.",
  INFERENCE_FAILURE: "The prediction service is temporarily unavailable. Please try again later.",
  DATASET_NOT_FOUND: "This dataset is no longer available.",
  RELEASE_UNAVAILABLE: "A prediction is not currently available for this dataset.",
  REGISTRY_UNAVAILABLE: "The prediction service is temporarily unavailable. Please try again later.",
  CONTRACT_UNAVAILABLE: "The prediction service is temporarily unavailable. Please try again later.",
};

const FALLBACK_ERROR = "Something went wrong. Please try again later.";

function mapErrorCode(errorCode: string | undefined): string {
  if (!errorCode) return FALLBACK_ERROR;
  return ERROR_MESSAGES[errorCode] ?? FALLBACK_ERROR;
}

/**
 * Project Spec S0143: the bounded typed outcome every inference executor
 * resolves to, whether it POSTs to the public route or a private Admin
 * route. Callers never see a raw Response/exception -- only this shape --
 * so no executor can smuggle a caller-supplied raw URL, header, or
 * transport detail through this boundary.
 */
export type InferenceExecutionResult =
  | { ok: true; result: unknown }
  | { ok: false; errorCode?: string };

/**
 * Project Spec S0143: an injectable execution boundary so InferenceForm can
 * own one visual/state lifecycle while the caller chooses the authorized
 * route. DatasetPage/DatasetViewPage omit this prop and keep the default
 * public POST /datasets/{slug}/inference behavior; Dataset Admin Live
 * Preview supplies an executor that calls the private
 * POST /admin/datasets/{slug}/inference route instead. Never a raw URL --
 * only a bounded (slug, payload) -> typed-result contract.
 */
export type InferenceExecutor = (
  slug: string,
  payload: Record<string, string | number | boolean>,
) => Promise<InferenceExecutionResult>;

async function defaultExecuteInference(
  slug: string,
  payload: Record<string, string | number | boolean>,
): Promise<InferenceExecutionResult> {
  try {
    const res = await fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/inference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = (await res.json()) as { result?: unknown; error_code?: string };
    if (res.ok) {
      return { ok: true, result: body?.result };
    }
    return { ok: false, errorCode: body?.error_code };
  } catch {
    return { ok: false };
  }
}

/**
 * Project Spec S0143: a bounded lifecycle seam consumers may observe without
 * this component implementing Publishing-console audit itself (that
 * consumption belongs to S0144). Never carries submitted field values, raw
 * payloads, headers, raw responses, stack traces, secrets or internal
 * paths -- only which phase of one submission just occurred.
 */
export type InferenceLifecycleEvent =
  | { type: "started" }
  | { type: "succeeded" }
  | { type: "validation_failed" }
  | { type: "execution_failed" };

type Props = {
  contract: ContractPayload;
  slug: string;
  customization?: PredictViewCustomization;
  /**
   * When true, disables the real POST /datasets/{slug}/inference submit
   * path (and every public ResultCardShell state) so this component can be
   * reused as a non-executing Live Preview of the current
   * grouping/ordering/visibility layout. All rendering logic (buildHintMap,
   * presentationSortKey, renderGrouped, renderFields, hidden-field
   * suppression) is reused unchanged. Defaults to false, so existing real
   * callers (e.g. DatasetViewPage.tsx) are unaffected.
   */
  previewMode?: boolean;
  /**
   * Project Spec S0110: resolved idle submit-button copy, presentation only.
   * The caller (DatasetPage/DatasetViewPage/Dataset Admin Live Preview) is
   * responsible for resolving this via the
   * customization -> legacy profile -> "Submit" precedence; this component
   * never re-derives or infers a label itself, and this prop never changes
   * endpoint selection, validation, payload, or submission behavior. Falls
   * back to "Submit" when absent or blank.
   */
  submitButtonLabel?: string;
  /**
   * Project Spec S0112: the release-bound technical result capability from
   * GET /datasets/{slug}/contract's result_contract. Required for real
   * public execution (DatasetPage/DatasetViewPage always pass it); omitted
   * for Dataset Admin Live Preview, which never performs public execution.
   * An absent or "unavailable" contract disables submission -- this
   * component never assumes availability by default.
   */
  resultContract?: BinaryResultContract;
  /**
   * Project Spec S0112: the published Result Card presentation copy from
   * GET /datasets/{slug}/context's canonical result_card. A missing or
   * malformed value safely falls back to GENERIC_RESULT_PRESENTATION rather
   * than removing the form.
   */
  resultPresentation?: BinaryResultPresentation;
  /**
   * Project Spec S0141: probability in the inclusive interval [0, 1] for a
   * local, presentation-only initial Result Card projection rendered before
   * any submission -- currently only DatasetPage.tsx (public Dataset
   * Detail) passes 0 to request the zero-probability card. The projection
   * is built through the shared projectBinaryClassificationResult boundary
   * from the current resultContract's governed semantics, never sent to the
   * inference endpoint, and only shown while submission remains idle.
   * Omitted by every other caller (Predict View, Dataset Admin Live
   * Preview) so their existing idle-placeholder behavior is unchanged.
   */
  initialResultProbability?: number;
  /**
   * Project Spec S0143: overrides the default public
   * POST /datasets/{slug}/inference submission with a bounded injected
   * executor (e.g. the private Admin route). Omitted by every public
   * caller (DatasetPage/DatasetViewPage), which keeps the default public
   * fetch behavior unchanged.
   */
  executeInference?: InferenceExecutor;
  /**
   * Project Spec S0143: an explicit identity (e.g. dataset slug + bound
   * view id) that, when it changes, resets the submission lifecycle back
   * to idle/initial and marks any in-flight request for that previous
   * identity as stale so its response can never overwrite the current
   * identity's state. Omitted by callers that never reuse one mounted
   * instance across a changing identity.
   */
  resetKey?: string;
  /**
   * Project Spec S0143: an optional bounded lifecycle observer -- started,
   * succeeded, validation_failed, execution_failed -- carrying no raw
   * payload/response data. Dataset Admin does not yet consume this to
   * append Publishing-console audit history (S0144).
   */
  onLifecycleEvent?: (event: InferenceLifecycleEvent) => void;
};

function buildHintMap(customization: PredictViewCustomization | undefined): Map<string, FieldHint> {
  const map = new Map<string, FieldHint>();
  if (!customization) return map;
  for (const hint of customization.field_hints) {
    map.set(hint.field_name, hint);
  }
  return map;
}

function presentationSortKey(feature: Feature, hint: FieldHint | undefined): number {
  if (hint?.display_order_hint !== undefined) return hint.display_order_hint;
  return feature.display_order;
}

function FieldInput({ feature, hint }: { feature: Feature; hint: FieldHint | undefined }) {
  const displayLabel = hint?.display_label ?? feature.label;
  const explanatoryCopy = hint?.explanatory_copy;
  const helperText = explanatoryCopy || feature.description;
  const isCheckbox = feature.input_type === "checkbox";

  const label = (
    <label className="public-inference-form__label" htmlFor={`field-${feature.name}`}>
      {displayLabel}
      {feature.input_type === "select" && " (categorical field)"}
      {!feature.optional && <span className="public-inference-form__required" aria-hidden="true"> *</span>}
    </label>
  );

  const control = isCheckbox ? (
    <input
      className="public-inference-form__control public-inference-form__control--checkbox"
      type="checkbox"
      id={`field-${feature.name}`}
      name={feature.name}
      required={!feature.optional}
    />
  ) : feature.input_type === "select" && feature.options && feature.options.length > 0 ? (
    <select
      className="public-inference-form__control"
      id={`field-${feature.name}`}
      name={feature.name}
      required={!feature.optional}
    >
      {feature.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ) : (
    <input
      className="public-inference-form__control"
      type={feature.input_type === "number" ? "number" : "text"}
      id={`field-${feature.name}`}
      name={feature.name}
      required={!feature.optional}
    />
  );

  return (
    <div
      className={
        isCheckbox
          ? "public-inference-form__field public-inference-form__field--checkbox"
          : "public-inference-form__field"
      }
      key={feature.name}
    >
      {isCheckbox ? control : label}
      {isCheckbox ? label : control}
      {helperText && <p className="public-inference-form__helper">{helperText}</p>}
    </div>
  );
}

export default function InferenceForm({
  contract,
  slug,
  customization,
  previewMode = false,
  submitButtonLabel,
  resultContract,
  resultPresentation,
  initialResultProbability,
  executeInference,
  resetKey,
  onLifecycleEvent,
}: Props) {
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });

  // Project Spec S0143: identifies the current dataset/bound-view identity
  // generation. Bumped whenever resetKey changes so a response that started
  // for a previous identity can detect (via the closure-captured generation
  // it read before awaiting) that it is now stale and must never overwrite
  // the current identity's submission state.
  const requestGenerationRef = useRef(0);
  const isFirstResetKeyRender = useRef(true);

  useEffect(() => {
    if (isFirstResetKeyRender.current) {
      isFirstResetKeyRender.current = false;
      return;
    }
    requestGenerationRef.current += 1;
    setSubmission({ status: "idle" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const hintMap = buildHintMap(customization);
  const contractAvailable = !previewMode && isAvailableBinaryResultContract(resultContract);
  const effectivePresentation = resultPresentation ?? GENERIC_RESULT_PRESENTATION;

  // Project Spec S0141: the local zero-probability initial projection is
  // built through the same shared technical-result boundary the real
  // inference response is validated against -- never a second result
  // vocabulary -- and only ever computed while contractAvailable (so it can
  // never be requested for an unavailable/malformed contract).
  const initialResult =
    contractAvailable && typeof initialResultProbability === "number" && resultContract?.status === "available"
      ? projectBinaryClassificationResult(resultContract.semantics, initialResultProbability)
      : null;

  const sortedForPresentation = [...contract.features].sort((a, b) => {
    const hintA = hintMap.get(a.name);
    const hintB = hintMap.get(b.name);
    return presentationSortKey(a, hintA) - presentationSortKey(b, hintB);
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (previewMode) {
      return;
    }

    // Project Spec S0112: a result-contract-unavailable release must not
    // issue the POST request at all (not just disable the button -- an
    // Enter keypress in a text input can still submit the <form> even when
    // the submit button itself is disabled).
    if (!contractAvailable) {
      return;
    }

    const generation = requestGenerationRef.current;
    onLifecycleEvent?.({ type: "started" });
    setSubmission({ status: "submitting" });

    const form = event.currentTarget;
    const payload: Record<string, string | number | boolean> = {};

    for (const feature of sortedForPresentation) {
      if (feature.input_type === "checkbox") {
        const el = form.elements.namedItem(feature.name) as HTMLInputElement | null;
        payload[feature.name] = el ? el.checked : false;
      } else if (feature.input_type === "number") {
        const el = form.elements.namedItem(feature.name) as HTMLInputElement | null;
        const raw = el ? el.value : "";
        if (raw !== "") {
          payload[feature.name] = Number(raw);
        }
      } else {
        const el = form.elements.namedItem(feature.name) as HTMLInputElement | null;
        if (el && el.value !== "") {
          payload[feature.name] = el.value;
        }
      }
    }

    const executor = executeInference ?? defaultExecuteInference;
    let outcome: InferenceExecutionResult;
    try {
      outcome = await executor(slug, payload);
    } catch {
      outcome = { ok: false };
    }

    // Project Spec S0143: the selected dataset/bound-view identity changed
    // while this request was in flight -- this response belongs to a
    // previous identity and must never overwrite the current one.
    if (requestGenerationRef.current !== generation) {
      return;
    }

    if (outcome.ok) {
      if (isBinaryClassificationResult(outcome.result)) {
        setSubmission({ status: "success", data: outcome.result });
        onLifecycleEvent?.({ type: "succeeded" });
      } else {
        // Malformed success payload: never falls back to a legacy
        // body.prediction field, always becomes the existing safe error state.
        setSubmission({ status: "error", message: FALLBACK_ERROR });
        onLifecycleEvent?.({ type: "execution_failed" });
      }
    } else {
      setSubmission({ status: "error", message: mapErrorCode(outcome.errorCode) });
      onLifecycleEvent?.({
        type: outcome.errorCode === "INVALID_PAYLOAD" ? "validation_failed" : "execution_failed",
      });
    }
  }

  function renderFields(features: Feature[]) {
    return features.map((feature) => {
      const hint = hintMap.get(feature.name);
      if (hint?.hidden === true) return null;
      return <FieldInput key={feature.name} feature={feature} hint={hint} />;
    });
  }

  function renderGrouped() {
    const groups = customization!.groups;
    const groupIds = new Set(groups.map((g) => g.group_id));

    const grouped = new Map<string, Feature[]>();
    for (const g of groups) grouped.set(g.group_id, []);

    const ungrouped: Feature[] = [];

    for (const feature of sortedForPresentation) {
      const hint = hintMap.get(feature.name);
      const groupId = hint?.group;
      if (groupId && groupIds.has(groupId)) {
        grouped.get(groupId)!.push(feature);
      } else {
        ungrouped.push(feature);
      }
    }

    return (
      <>
        {groups.map((group) => {
          const members = grouped.get(group.group_id) ?? [];
          if (members.length === 0) return null;
          return (
            <fieldset className="public-inference-form__group" key={group.group_id}>
              <legend className="public-inference-form__legend">{group.label}</legend>
              {group.description && (
                <p className="public-inference-form__group-description">{group.description}</p>
              )}
              <div className="public-inference-form__field-grid">{renderFields(members)}</div>
            </fieldset>
          );
        })}
        {ungrouped.length > 0 && (
          <div className="public-inference-form__field-grid">{renderFields(ungrouped)}</div>
        )}
      </>
    );
  }

  const hasGroups = customization && customization.groups.length > 0;
  const idleLabel = submitButtonLabel?.trim() || "Submit";
  const submitDisabled = previewMode || submission.status === "submitting" || (!previewMode && !contractAvailable);

  return (
    <section
      aria-label="Inference Form"
      className={previewMode ? undefined : "public-inference-surface"}
    >
      <div className="public-inference-surface__form-panel public-inference-form">
        <h2 className="public-inference-form__heading">Inference</h2>
        <form className="public-inference-form__form" onSubmit={handleSubmit}>
          {hasGroups ? (
            renderGrouped()
          ) : (
            <div className="public-inference-form__field-grid">
              {renderFields(sortedForPresentation)}
            </div>
          )}
          <button type="submit" className="public-inference-form__submit" disabled={submitDisabled}>
            {submission.status === "submitting" ? "Submitting…" : idleLabel}
          </button>
        </form>
      </div>

      {!previewMode && !contractAvailable && <ResultCardShell state="unavailable" />}
      {!previewMode && contractAvailable && submission.status === "idle" && initialResult && (
        <ResultCardShell state="initial">
          <BinaryClassificationResult result={initialResult} presentation={effectivePresentation} />
        </ResultCardShell>
      )}
      {!previewMode && contractAvailable && submission.status === "idle" && !initialResult && (
        <ResultCardShell state="idle" />
      )}
      {!previewMode && contractAvailable && submission.status === "submitting" && (
        <ResultCardShell state="submitting" />
      )}
      {!previewMode && contractAvailable && submission.status === "error" && (
        <ResultCardShell state="error" message={submission.message} />
      )}
      {!previewMode && contractAvailable && submission.status === "success" && (
        <ResultCardShell state="success">
          <BinaryClassificationResult result={submission.data} presentation={effectivePresentation} />
        </ResultCardShell>
      )}
    </section>
  );
}
