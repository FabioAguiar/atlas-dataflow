/**
 * Project Spec S0112: strict frontend result types for the shared public
 * binary Result Card. These mirror the backend's binary-classification-result.v1
 * (runtime/inference.py), binary-result-semantics.v1 (the /contract
 * result_contract projection), and binary-result-presentation.v1 (the
 * /context result_card projection) contracts. No second frontend result
 * vocabulary (e.g. legacy label + confidence) is defined here.
 */

export type BinaryClassIdentity = {
  class_id: string;
};

export type BinaryPositiveClass = {
  class_id: string;
  event_label: string;
};

export type BinaryClassProbability = {
  class_id: string;
  probability: number;
};

export type BinaryDecision = {
  threshold: number;
  predicted_positive: boolean;
};

export type BinaryRiskBand = {
  band_id: string;
  lower_bound: number;
  upper_bound: number;
};

export type BinaryInterpretation = {
  preset: string;
  band_id: string;
  bands: BinaryRiskBand[];
};

export type BinaryModelDescriptor = {
  model_family: string;
  display_name: string;
};

/** Matches runtime/inference.py's binary-classification-result.v1 exactly. */
export type BinaryClassificationResult = {
  schema_version: "binary-classification-result.v1";
  problem_type: "binary_classification";
  predicted_class: BinaryClassIdentity;
  positive_class: BinaryPositiveClass;
  positive_class_probability: number;
  class_probabilities: BinaryClassProbability[];
  decision: BinaryDecision;
  interpretation: BinaryInterpretation;
  model_descriptor: BinaryModelDescriptor;
};

/** Matches GET /datasets/{slug}/contract's result_contract.semantics (no band_id selection yet). */
export type BinaryResultSemantics = {
  schema_version: string;
  problem_type: "binary_classification";
  result_schema_version: "binary-classification-result.v1";
  primary_output: "positive_class_probability";
  positive_class: BinaryPositiveClass;
  decision: {
    threshold: number;
  };
  interpretation: {
    preset: string;
    bands: BinaryRiskBand[];
  };
  model_descriptor: BinaryModelDescriptor;
};

export type AvailableBinaryResultContract = {
  status: "available";
  semantics: BinaryResultSemantics;
};

export type UnavailableBinaryResultContract = {
  status: "unavailable";
  reason: string;
};

export type BinaryResultContract = AvailableBinaryResultContract | UnavailableBinaryResultContract;

/** Matches GET /datasets/{slug}/context's result_card (binary-result-presentation.v1). */
export type BinaryResultPresentation = {
  schema_version: "binary-result-presentation.v1";
  positive_class_probability_label: string;
  predicted_outcome_label: string;
  positive_outcome_copy: string;
  negative_outcome_copy: string;
  model_section_label: string;
  interpretation: {
    preset: string;
    labels: {
      high: string;
      medium: string;
      low: string;
    };
  };
};

/**
 * Bounded, presentation-only generic fallback matching the S0111 vocabulary.
 * Used when context.result_card is missing or malformed so the input form
 * never has to disappear. Must never invent positive class, model name,
 * threshold, boundaries, or outcome decision -- it carries copy only.
 */
export const GENERIC_RESULT_PRESENTATION: BinaryResultPresentation = {
  schema_version: "binary-result-presentation.v1",
  positive_class_probability_label: "Positive class probability",
  predicted_outcome_label: "Predicted outcome",
  positive_outcome_copy: "Positive outcome",
  negative_outcome_copy: "Negative outcome",
  model_section_label: "Model",
  interpretation: {
    preset: "risk",
    labels: {
      high: "High",
      medium: "Medium",
      low: "Low",
    },
  },
};

const SUPPORTED_INTERPRETATION_PRESET = "risk";

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isUnitInterval(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isClassIdentity(value: unknown): value is BinaryClassIdentity {
  return isRecord(value) && isNonEmptyString(value.class_id);
}

function isPositiveClass(value: unknown): value is BinaryPositiveClass {
  return isRecord(value) && isNonEmptyString(value.class_id) && isNonEmptyString(value.event_label);
}

function isClassProbability(value: unknown): value is BinaryClassProbability {
  return isRecord(value) && isNonEmptyString(value.class_id) && isUnitInterval(value.probability);
}

function isRiskBand(value: unknown): value is BinaryRiskBand {
  return (
    isRecord(value) &&
    isNonEmptyString(value.band_id) &&
    isFiniteNumber(value.lower_bound) &&
    isFiniteNumber(value.upper_bound)
  );
}

function isModelDescriptor(value: unknown): value is BinaryModelDescriptor {
  return isRecord(value) && isNonEmptyString(value.display_name) && isNonEmptyString(value.model_family);
}

/**
 * Bounded runtime transport guard for a successful /inference response's
 * `result` field. Confirms enough structure to render safely -- schema/
 * problem-type identity, finite bounded probabilities/threshold, required
 * nested objects/arrays, a supported interpretation preset, and a band_id
 * that actually resolves against the returned bands -- without duplicating
 * the full backend JSON Schema or recomputing decision/band semantics.
 * Never accepts a legacy `{ label, confidence }` shape.
 */
export function isBinaryClassificationResult(value: unknown): value is BinaryClassificationResult {
  if (!isRecord(value)) return false;

  if (value.schema_version !== "binary-classification-result.v1") return false;
  if (value.problem_type !== "binary_classification") return false;

  if (!isClassIdentity(value.predicted_class)) return false;
  if (!isPositiveClass(value.positive_class)) return false;
  if (!isUnitInterval(value.positive_class_probability)) return false;

  if (!Array.isArray(value.class_probabilities) || value.class_probabilities.length === 0) return false;
  if (!value.class_probabilities.every(isClassProbability)) return false;

  const decision = value.decision;
  if (!isRecord(decision) || !isUnitInterval(decision.threshold) || typeof decision.predicted_positive !== "boolean") {
    return false;
  }

  const interpretation = value.interpretation;
  if (!isRecord(interpretation)) return false;
  if (interpretation.preset !== SUPPORTED_INTERPRETATION_PRESET) return false;
  if (!isNonEmptyString(interpretation.band_id)) return false;
  if (!Array.isArray(interpretation.bands) || interpretation.bands.length === 0) return false;
  if (!interpretation.bands.every(isRiskBand)) return false;
  const bands = interpretation.bands as BinaryRiskBand[];
  if (!bands.some((band) => band.band_id === interpretation.band_id)) return false;

  if (!isModelDescriptor(value.model_descriptor)) return false;

  return true;
}
