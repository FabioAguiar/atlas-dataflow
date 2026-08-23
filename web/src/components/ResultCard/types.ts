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

export type MulticlassClassProbability = {
  class_id: string;
  display_label: string;
  probability: number;
};

export type MulticlassClassificationResult = {
  schema_version: "multiclass-classification-result.v1";
  problem_type: "multiclass_classification";
  predicted_class: MulticlassClassIdentity;
  class_probabilities: MulticlassClassProbability[];
  decision: { strategy: "argmax" };
  model_descriptor: BinaryModelDescriptor;
};

/** Matches runtime/inference.py's continuous-regression-result.v1 exactly (S0223/S0229). */
export type ContinuousRegressionResult = {
  schema_version: "continuous-regression-result.v1";
  problem_type: "continuous_regression";
  predicted_value: number;
  model_descriptor: BinaryModelDescriptor;
};

export type ResultData = BinaryClassificationResult | MulticlassClassificationResult | ContinuousRegressionResult;

/** Matches GET /datasets/{slug}/contract's result_contract.semantics (no band_id selection yet). */
export type BinaryResultSemantics = {
  schema_version: string;
  problem_type: "binary_classification";
  result_schema_version: "binary-classification-result.v1";
  primary_output: "positive_class_probability";
  positive_class: BinaryPositiveClass;
  negative_class: BinaryClassIdentity;
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

export type MulticlassClassIdentity = { class_id: string; display_label: string };
export type MulticlassResultSemantics = {
  schema_version: "multiclass-result-semantics.v1";
  problem_type: "multiclass_classification";
  result_schema_version: "multiclass-classification-result.v1";
  classes: MulticlassClassIdentity[];
  primary_output: "predicted_class";
  probability_output: "class_probabilities";
  decision: { strategy: "argmax" };
  model_descriptor: BinaryModelDescriptor;
};
export type AvailableMulticlassResultContract = { status: "available"; semantics: MulticlassResultSemantics };

/** Matches GET /datasets/{slug}/contract's result_contract.semantics for continuous_regression (S0223/S0229). */
export type ContinuousRegressionResultSemantics = {
  schema_version: string;
  problem_type: "continuous_regression";
  result_schema_version: "continuous-regression-result.v1";
  primary_output: "predicted_value";
  output_value_kind: "continuous_numeric";
  model_descriptor: BinaryModelDescriptor;
};
export type AvailableContinuousRegressionResultContract = { status: "available"; semantics: ContinuousRegressionResultSemantics };

/**
 * Matches GET /datasets/{slug}/contract's result_contract.semantics for
 * univariate_forecasting (S0245/S0247). Mirrors the S0245 governed
 * inference_bundle.v2 result-semantics shape. This is a strict availability/
 * identity guard only -- no Result Card rendering component or forecasting
 * presentation contract is defined here.
 */
export type ForecastingResultSemantics = {
  schema_version: "univariate-forecasting-result-semantics.v1";
  problem_type: "univariate_forecasting";
  result_schema_version: "univariate-forecasting-result.v1";
  primary_output: "forecast_series";
  output_structure: "ordered_forecast_points";
  forecast_value_kind: "continuous_numeric";
  forecast_count_source: "forecast_horizon";
  model_descriptor: BinaryModelDescriptor;
};
export type AvailableForecastingResultContract = { status: "available"; semantics: ForecastingResultSemantics };

export type ResultContract =
  | AvailableBinaryResultContract
  | AvailableMulticlassResultContract
  | AvailableContinuousRegressionResultContract
  | AvailableForecastingResultContract
  | UnavailableBinaryResultContract;

/** Bounded guard for the executable public binary result-contract capability. */
export function isAvailableBinaryResultContract(value: unknown): value is AvailableBinaryResultContract {
  if (!isRecord(value) || value.status !== "available" || !isRecord(value.semantics)) return false;

  const semantics = value.semantics;
  if (semantics.schema_version !== "binary-result-semantics.v1") return false;
  if (semantics.problem_type !== "binary_classification") return false;
  if (semantics.result_schema_version !== "binary-classification-result.v1") return false;
  if (semantics.primary_output !== "positive_class_probability") return false;
  if (!isPositiveClass(semantics.positive_class) || !isClassIdentity(semantics.negative_class)) return false;
  if (semantics.positive_class.class_id.trim() === semantics.negative_class.class_id.trim()) return false;

  const decision = semantics.decision;
  if (!isRecord(decision) || !isUnitInterval(decision.threshold)) return false;
  const interpretation = semantics.interpretation;
  if (!isRecord(interpretation) || interpretation.preset !== SUPPORTED_INTERPRETATION_PRESET) return false;
  if (!Array.isArray(interpretation.bands) || !interpretation.bands.every(isRiskBand)) return false;
  return isModelDescriptor(semantics.model_descriptor);
}

export function isAvailableMulticlassResultContract(value: unknown): value is AvailableMulticlassResultContract {
  if (!isRecord(value) || value.status !== "available" || !isRecord(value.semantics)) return false;
  const semantics = value.semantics;
  if (semantics.schema_version !== "multiclass-result-semantics.v1" || semantics.problem_type !== "multiclass_classification") return false;
  if (semantics.result_schema_version !== "multiclass-classification-result.v1" || semantics.primary_output !== "predicted_class") return false;
  if (semantics.probability_output !== "class_probabilities" || !Array.isArray(semantics.classes) || semantics.classes.length < 3) return false;
  if (!semantics.classes.every(isMulticlassClassIdentity)) return false;
  const ids = semantics.classes.map((item) => item.class_id.trim());
  if (new Set(ids).size !== ids.length) return false;
  if (!isRecord(semantics.decision) || semantics.decision.strategy !== "argmax") return false;
  return isModelDescriptor(semantics.model_descriptor);
}

export function isAvailableContinuousRegressionResultContract(value: unknown): value is AvailableContinuousRegressionResultContract {
  if (!isRecord(value) || value.status !== "available" || !isRecord(value.semantics)) return false;
  const semantics = value.semantics;
  if (semantics.problem_type !== "continuous_regression") return false;
  if (semantics.result_schema_version !== "continuous-regression-result.v1") return false;
  if (semantics.primary_output !== "predicted_value") return false;
  if (semantics.output_value_kind !== "continuous_numeric") return false;
  return isModelDescriptor(semantics.model_descriptor);
}

export function isAvailableForecastingResultContract(value: unknown): value is AvailableForecastingResultContract {
  if (!isRecord(value) || value.status !== "available" || !isRecord(value.semantics)) return false;
  const semantics = value.semantics;
  if (semantics.schema_version !== "univariate-forecasting-result-semantics.v1") return false;
  if (semantics.problem_type !== "univariate_forecasting") return false;
  if (semantics.result_schema_version !== "univariate-forecasting-result.v1") return false;
  if (semantics.primary_output !== "forecast_series") return false;
  if (semantics.output_structure !== "ordered_forecast_points") return false;
  if (semantics.forecast_value_kind !== "continuous_numeric") return false;
  if (semantics.forecast_count_source !== "forecast_horizon") return false;
  return isModelDescriptor(semantics.model_descriptor);
}

export function availableResultProblemType(
  value: unknown,
): "binary_classification" | "multiclass_classification" | "continuous_regression" | "univariate_forecasting" | null {
  if (isAvailableBinaryResultContract(value)) return "binary_classification";
  if (isAvailableMulticlassResultContract(value)) return "multiclass_classification";
  if (isAvailableContinuousRegressionResultContract(value)) return "continuous_regression";
  if (isAvailableForecastingResultContract(value)) return "univariate_forecasting";
  return null;
}

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

export type MulticlassResultPresentation = {
  schema_version: "multiclass-result-presentation.v1";
  predicted_class_label: string;
  class_probability_distribution_label: string;
  model_section_label: string;
};
/** Matches GET /datasets/{slug}/context's result_card (continuous-regression-result-presentation.v1). */
export type ContinuousRegressionResultPresentation = {
  schema_version: "continuous-regression-result-presentation.v1";
  predicted_value_label: string;
  model_section_label: string;
  decimal_places: number;
  value_unit_label?: string;
};

export type ResultPresentation = BinaryResultPresentation | MulticlassResultPresentation | ContinuousRegressionResultPresentation;

export const GENERIC_MULTICLASS_RESULT_PRESENTATION: MulticlassResultPresentation = {
  schema_version: "multiclass-result-presentation.v1",
  predicted_class_label: "Predicted class",
  class_probability_distribution_label: "Class probability distribution",
  model_section_label: "Model",
};

export const GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION: ContinuousRegressionResultPresentation = {
  schema_version: "continuous-regression-result-presentation.v1",
  predicted_value_label: "Predicted value",
  model_section_label: "Model",
  decimal_places: 2,
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

function isMulticlassClassIdentity(value: unknown): value is MulticlassClassIdentity {
  return isRecord(value) && isNonEmptyString(value.class_id) && isNonEmptyString(value.display_label);
}

function isMulticlassClassProbability(value: unknown): value is MulticlassClassProbability {
  return isRecord(value)
    && isNonEmptyString(value.class_id)
    && isNonEmptyString(value.display_label)
    && isUnitInterval(value.probability);
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

function selectRiskBand(bands: BinaryRiskBand[], probability: number): BinaryRiskBand | null {
  const matches = bands.filter((band, index) =>
    probability >= band.lower_bound &&
    (probability < band.upper_bound || (index === bands.length - 1 && probability === 1 && band.upper_bound === 1)),
  );
  return matches.length === 1 ? matches[0] : null;
}

/**
 * Project Spec S0141: the single shared, side-effect-free binary result
 * projection boundary. Accepts validated governed semantics and a
 * probability in [0, 1] and derives the full technical
 * BinaryClassificationResult -- decision, complementary class
 * probabilities, the selected interpretation band, and model descriptor --
 * with no network, storage, registry, route or DOM access. Both the Dataset
 * Admin scenario preview (via livePreviewProjection.ts's
 * projectBinaryResultPreview) and the public Dataset Detail
 * zero-probability initial card construct their technical result through
 * this one function, so no second result-construction implementation
 * exists. Presentation copy is deliberately not an input: it is not part of
 * the technical result and must never be copied into the result payload.
 */
export function projectBinaryClassificationResult(
  semantics: BinaryResultSemantics,
  probability: number,
): BinaryClassificationResult | null {
  if (!isUnitInterval(probability)) return null;
  if (semantics.interpretation.preset !== SUPPORTED_INTERPRETATION_PRESET) return null;
  if (semantics.interpretation.bands.length !== 3) return null;
  if (semantics.positive_class.class_id === semantics.negative_class.class_id) return null;

  const band = selectRiskBand(semantics.interpretation.bands, probability);
  if (!band) return null;
  const predictedPositive = probability >= semantics.decision.threshold;

  return {
    schema_version: "binary-classification-result.v1",
    problem_type: "binary_classification",
    predicted_class: predictedPositive ? { class_id: semantics.positive_class.class_id } : semantics.negative_class,
    positive_class: semantics.positive_class,
    positive_class_probability: probability,
    class_probabilities: [
      { class_id: semantics.negative_class.class_id, probability: 1 - probability },
      { class_id: semantics.positive_class.class_id, probability },
    ],
    decision: { threshold: semantics.decision.threshold, predicted_positive: predictedPositive },
    interpretation: {
      preset: semantics.interpretation.preset,
      band_id: band.band_id,
      bands: semantics.interpretation.bands,
    },
    model_descriptor: semantics.model_descriptor,
  };
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

const MULTICLASS_SUM_TOLERANCE = 1e-6;

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
}

export function isMulticlassClassificationResult(value: unknown): value is MulticlassClassificationResult {
  if (!isRecord(value) || !hasExactKeys(value, [
    "schema_version", "problem_type", "predicted_class", "class_probabilities", "decision", "model_descriptor",
  ])) return false;
  if (value.schema_version !== "multiclass-classification-result.v1" || value.problem_type !== "multiclass_classification") return false;
  if (!isRecord(value.predicted_class) || !hasExactKeys(value.predicted_class, ["class_id", "display_label"]) || !isMulticlassClassIdentity(value.predicted_class)) return false;
  if (!Array.isArray(value.class_probabilities) || value.class_probabilities.length < 3) return false;

  const probabilities = value.class_probabilities;
  if (!probabilities.every((entry) =>
    isRecord(entry)
    && hasExactKeys(entry, ["class_id", "display_label", "probability"])
    && isMulticlassClassProbability(entry)
  )) return false;
  const ids = probabilities.map((entry) => entry.class_id.trim());
  if (new Set(ids).size !== ids.length) return false;
  if (Math.abs(probabilities.reduce((sum, entry) => sum + entry.probability, 0) - 1) > MULTICLASS_SUM_TOLERANCE) return false;
  if (!isRecord(value.decision) || !hasExactKeys(value.decision, ["strategy"]) || value.decision.strategy !== "argmax") return false;
  if (!isRecord(value.model_descriptor) || !hasExactKeys(value.model_descriptor, ["model_family", "display_name"]) || !isModelDescriptor(value.model_descriptor)) return false;

  const predictedClass = value.predicted_class as MulticlassClassIdentity;
  const predictedMatches = probabilities.filter((entry) => entry.class_id === predictedClass.class_id);
  if (predictedMatches.length !== 1 || predictedMatches[0].display_label !== predictedClass.display_label) return false;
  const maximum = Math.max(...probabilities.map((entry) => entry.probability));
  return probabilities.find((entry) => entry.probability === maximum)?.class_id === predictedClass.class_id;
}

/**
 * Bounded runtime transport guard for a successful /inference response's
 * `result` field when the active problem type is continuous_regression.
 * Rejects NaN/Infinity/-Infinity, boolean-as-number, a missing
 * predicted_value, extra/unknown keys, the wrong schema version/problem
 * type, and a malformed model descriptor. Never accepts classification
 * fields (class, probability, threshold, band).
 */
export function isContinuousRegressionResult(value: unknown): value is ContinuousRegressionResult {
  if (!isRecord(value) || !hasExactKeys(value, [
    "schema_version", "problem_type", "predicted_value", "model_descriptor",
  ])) return false;
  if (value.schema_version !== "continuous-regression-result.v1") return false;
  if (value.problem_type !== "continuous_regression") return false;
  if (!isFiniteNumber(value.predicted_value)) return false;
  if (!isRecord(value.model_descriptor) || !hasExactKeys(value.model_descriptor, ["model_family", "display_name"]) || !isModelDescriptor(value.model_descriptor)) return false;
  return true;
}

export function resultForContract(resultContract: unknown, result: unknown): ResultData | null {
  if (isAvailableBinaryResultContract(resultContract)) {
    return isBinaryClassificationResult(result) ? result : null;
  }
  if (isAvailableContinuousRegressionResultContract(resultContract)) {
    if (!isContinuousRegressionResult(result)) return null;
    const expectedModel = resultContract.semantics.model_descriptor;
    return expectedModel.model_family === result.model_descriptor.model_family
      && expectedModel.display_name === result.model_descriptor.display_name
      ? result
      : null;
  }
  if (!isAvailableMulticlassResultContract(resultContract) || !isMulticlassClassificationResult(result)) return null;
  const classes = resultContract.semantics.classes;
  if (classes.length !== result.class_probabilities.length) return null;
  if (!classes.every((classIdentity, index) =>
    classIdentity.class_id === result.class_probabilities[index].class_id
    && classIdentity.display_label === result.class_probabilities[index].display_label
  )) return null;
  const expectedModel = resultContract.semantics.model_descriptor;
  return expectedModel.model_family === result.model_descriptor.model_family
    && expectedModel.display_name === result.model_descriptor.display_name
    ? result
    : null;
}
