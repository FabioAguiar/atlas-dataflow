import { FormEvent, useState } from "react";
import InferenceResult, { PredictionResult } from "../InferenceResult/InferenceResult";
import ErrorState from "../ErrorState/ErrorState";

export type Feature = {
  name: string;
  label: string;
  input_type: "number" | "select" | "checkbox";
  optional: boolean;
  display_order: number;
  description?: string;
};

export type ContractPayload = {
  schema_version: string;
  features: Feature[];
};

type SubmissionState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "result"; data: PredictionResult }
  | { status: "error"; message: string };

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

type Props = {
  contract: ContractPayload;
  slug: string;
};

export default function InferenceForm({ contract, slug }: Props) {
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });

  const sorted = [...contract.features].sort(
    (a, b) => a.display_order - b.display_order
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmission({ status: "submitting" });

    const form = event.currentTarget;
    const payload: Record<string, string | number | boolean> = {};

    for (const feature of sorted) {
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

    try {
      const res = await fetch(
        `/datasets/${encodeURIComponent(slug)}/inference`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (res.ok) {
        const body = await res.json() as { prediction: PredictionResult };
        setSubmission({ status: "result", data: body.prediction });
      } else {
        const body = await res.json() as { error_code?: string };
        setSubmission({ status: "error", message: mapErrorCode(body.error_code) });
      }
    } catch {
      setSubmission({ status: "error", message: FALLBACK_ERROR });
    }
  }

  return (
    <section aria-label="Inference Form">
      <h2>Make a Prediction</h2>
      <form onSubmit={handleSubmit}>
        {sorted.map((feature) => (
          <div key={feature.name}>
            <label htmlFor={`field-${feature.name}`}>
              {feature.label}
              {feature.input_type === "select" && " (categorical field)"}
              {!feature.optional && <span aria-hidden="true"> *</span>}
            </label>
            {feature.input_type === "checkbox" ? (
              <input
                type="checkbox"
                id={`field-${feature.name}`}
                name={feature.name}
                required={!feature.optional}
              />
            ) : (
              <input
                type={feature.input_type === "number" ? "number" : "text"}
                id={`field-${feature.name}`}
                name={feature.name}
                required={!feature.optional}
              />
            )}
            {feature.description && <p>{feature.description}</p>}
          </div>
        ))}
        <button type="submit" disabled={submission.status === "submitting"}>
          {submission.status === "submitting" ? "Submitting…" : "Submit"}
        </button>
      </form>

      {submission.status === "result" && (
        <InferenceResult result={submission.data} />
      )}
      {submission.status === "error" && (
        <ErrorState message={submission.message} />
      )}
    </section>
  );
}
