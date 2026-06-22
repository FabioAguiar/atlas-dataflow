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

export type FieldHint = {
  field_name: string;
  display_label?: string;
  explanatory_copy?: string;
  display_order_hint?: number;
  group?: string;
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
  };
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
  customization?: PredictViewCustomization;
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

  return (
    <div key={feature.name}>
      <label htmlFor={`field-${feature.name}`}>
        {displayLabel}
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
      {explanatoryCopy && <p>{explanatoryCopy}</p>}
      {!explanatoryCopy && feature.description && <p>{feature.description}</p>}
    </div>
  );
}

export default function InferenceForm({ contract, slug, customization }: Props) {
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });

  const hintMap = buildHintMap(customization);

  const sortedForPresentation = [...contract.features].sort((a, b) => {
    const hintA = hintMap.get(a.name);
    const hintB = hintMap.get(b.name);
    return presentationSortKey(a, hintA) - presentationSortKey(b, hintB);
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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

  function renderFields(features: Feature[]) {
    return features.map((feature) => (
      <FieldInput key={feature.name} feature={feature} hint={hintMap.get(feature.name)} />
    ));
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
            <fieldset key={group.group_id}>
              <legend>{group.label}</legend>
              {group.description && <p>{group.description}</p>}
              {renderFields(members)}
            </fieldset>
          );
        })}
        {ungrouped.length > 0 && (
          <div>
            {renderFields(ungrouped)}
          </div>
        )}
      </>
    );
  }

  const hasGroups = customization && customization.groups.length > 0;

  return (
    <section aria-label="Inference Form">
      <h2>Make a Prediction</h2>
      <form onSubmit={handleSubmit}>
        {hasGroups ? renderGrouped() : renderFields(sortedForPresentation)}
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
