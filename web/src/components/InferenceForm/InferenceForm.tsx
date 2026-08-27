import { FormEvent, useEffect, useRef, useState } from "react";
import ResultCardShell from "../ResultCard/ResultCardShell";
import BinaryClassificationResult from "../ResultCard/BinaryClassificationResult";
import MulticlassClassificationResult from "../ResultCard/MulticlassClassificationResult";
import ContinuousRegressionResult from "../ResultCard/ContinuousRegressionResult";
import UnivariateForecastingResult from "../ResultCard/UnivariateForecastingResult";
import {
  GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION,
  GENERIC_MULTICLASS_RESULT_PRESENTATION,
  GENERIC_RESULT_PRESENTATION,
  GENERIC_UNIVARIATE_FORECASTING_RESULT_PRESENTATION,
  isAvailableBinaryResultContract,
  isAvailableContinuousRegressionResultContract,
  isAvailableForecastingResultContract,
  isAvailableMulticlassResultContract,
  projectBinaryClassificationResult,
  resultForContract,
  type ResultData,
  type ResultContract,
  type ResultPresentation,
} from "../ResultCard/types";
import HistorySeriesInput, {
  type ForecastGuidance,
  type HistoryRowInput,
  type HistorySeriesGuidance,
} from "./HistorySeriesInput";

export type FeatureOption = {
  value: string | number;
  label: string;
};

/**
 * Project Spec S0156: presentation-only confirmation that this field has a
 * contract-declared conditional blank-input policy. Never carries the
 * condition field/operator/comparison value or the materialized value -- the
 * backend runtime contract remains the sole evaluator of the cross-field
 * condition.
 */
export type ConditionalBlankPolicy = {
  accepted_representation: "blank_string_after_trim";
};

export type Feature = {
  name: string;
  label: string;
  input_type: "number" | "select" | "checkbox";
  optional: boolean;
  display_order: number;
  description?: string;
  options?: FeatureOption[];
  /**
   * Project Spec S0156: present only for input_type "select". A bounded
   * scalar serialization hint copied from the runtime categorical scalar
   * type -- string categorical selects submit a JSON string, integer
   * categorical selects submit a JSON integer. Never inferred from the
   * selected option's text or the field name.
   */
  select_value_type?: "string" | "integer";
  /**
   * Project Spec S0156: present only when the runtime contract declares a
   * conditional blank-input normalization policy for this field. When
   * present and the field is left blank, the form submits the declared
   * blank representation instead of omitting the key, so the backend can
   * evaluate the condition. Ordinary required number/select behavior and
   * S0152 optional-omission behavior are unchanged when absent.
   */
  conditional_blank_policy?: ConditionalBlankPolicy;
};

/** Project Spec S0246/S0250: strict univariate-forecasting history-series public contract branch. */
export type ScalarContractPayload = {
  schema_version: string;
  features: Feature[];
};

/**
 * Project Spec S0269 / S0271: the optional, additive public projection of the
 * reviewed predictive-interaction policy. Historical `public-contract` 2.0.0
 * forecasting documents materialized before S0269 omit this entirely and stay
 * valid; when present, `public_prediction.applicability` is the single
 * release-bound authority for public prediction-surface availability
 * (`history_target_values.affect_forecast` describes model behavior only and
 * is never a surface-availability decision input).
 */
export type PredictiveInteractionProjection = {
  history_target_values: {
    affect_forecast: boolean;
  };
  public_prediction: {
    applicability: "available" | "not_applicable";
  };
};

export type ForecastingContractPayload = {
  schema_version: "2.0.0";
  problem_type: "univariate_forecasting";
  input_kind: "history_series";
  history_series: HistorySeriesGuidance;
  forecast: ForecastGuidance;
  predictive_interaction?: PredictiveInteractionProjection;
};

/**
 * Project Spec S0250: an additive strict discriminated union -- the
 * historical scalar branch (ScalarContractPayload) is unchanged and remains
 * compatible with every existing caller; ForecastingContractPayload is a
 * new, exact branch. The active branch is never inferred from dataset slug,
 * field names, frequency, result presentation, or performance focus -- only
 * from this contract's own schema_version/problem_type/input_kind
 * discriminants (see isForecastingContractPayload below).
 */
export type ContractPayload = ScalarContractPayload | ForecastingContractPayload;

export function isForecastingContractPayload(
  contract: ContractPayload,
): contract is ForecastingContractPayload {
  return (
    contract.schema_version === "2.0.0" &&
    (contract as ForecastingContractPayload).problem_type === "univariate_forecasting" &&
    (contract as ForecastingContractPayload).input_kind === "history_series"
  );
}

/**
 * Project Spec S0271: the single bounded consumer of the S0269 release-bound
 * public predictive-interaction applicability. Answers exactly one question --
 * "is the public prediction surface (Inference tab / Predict View routes /
 * public inference POST) available for this active-release contract?" -- and
 * is shared by the public Dataset Page and Admin Live Preview so the two can
 * never diverge.
 *
 * Rules:
 *   scalar contract                                    -> true
 *   forecasting v2 + predictive_interaction absent      -> true (historical)
 *   forecasting v2 + applicability = "available"        -> true
 *   forecasting v2 + applicability = "not_applicable"   -> false
 *
 * It never derives availability from problem type alone, dataset slug, model
 * name/family, result/Predict View/profile state, `required_anchor`,
 * `frequency`, or `history_target_values.affect_forecast`. A present but
 * malformed `predictive_interaction` shape fails closed (false) rather than
 * silently resolving to available.
 */
export function isPublicPredictionSurfaceAvailable(contract: ContractPayload): boolean {
  if (!isForecastingContractPayload(contract)) {
    return true;
  }

  const projection = contract.predictive_interaction;
  if (projection === undefined || projection === null) {
    return true;
  }
  if (typeof projection !== "object") {
    return false;
  }

  const applicability = (projection as PredictiveInteractionProjection).public_prediction?.applicability;
  if (applicability === "available") {
    return true;
  }
  if (applicability === "not_applicable") {
    return false;
  }
  return false;
}

export type AdminInferenceFieldGuidance = {
  field_name: string;
  required: boolean;
  numeric_domain?: {
    min?: number;
    max?: number;
  };
};

/**
 * Bounded parser for the private Admin projection. It retains only exact
 * canonical fields in the active public form contract, accepts finite bounds
 * for numeric controls only, and resolves duplicates by first occurrence.
 */
export function normalizeAdminInferenceGuidance(
  value: unknown,
  features: Feature[],
): AdminInferenceFieldGuidance[] {
  if (!Array.isArray(value)) return [];

  const featureByName = new Map(features.map((feature) => [feature.name, feature]));
  const seen = new Set<string>();
  const normalized: AdminInferenceFieldGuidance[] = [];

  for (const raw of value) {
    if (normalized.length >= features.length) break;
    if (typeof raw !== "object" || raw === null) continue;
    const record = raw as Record<string, unknown>;
    const name = record.field_name;
    if (typeof name !== "string" || seen.has(name)) continue;
    const feature = featureByName.get(name);
    if (!feature || typeof record.required !== "boolean") continue;
    seen.add(name);

    const entry: AdminInferenceFieldGuidance = { field_name: name, required: record.required };
    const domain = record.numeric_domain;
    if (feature.input_type === "number" && typeof domain === "object" && domain !== null) {
      const domainRecord = domain as Record<string, unknown>;
      const minimum = domainRecord.min;
      const maximum = domainRecord.max;
      const numericDomain: { min?: number; max?: number } = {};
      if (typeof minimum === "number" && Number.isFinite(minimum)) numericDomain.min = minimum;
      if (typeof maximum === "number" && Number.isFinite(maximum)) numericDomain.max = maximum;
      if (!(
        numericDomain.min !== undefined
        && numericDomain.max !== undefined
        && numericDomain.min > numericDomain.max
      ) && (numericDomain.min !== undefined || numericDomain.max !== undefined)) {
        entry.numeric_domain = numericDomain;
      }
    }
    normalized.push(entry);
  }

  return normalized;
}

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
  | { status: "success"; data: ResultData }
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
 * Project Spec S0266: for a forecasting INVALID_PAYLOAD failure whose
 * normalized validationIssues include forecasting_minimum_history_not_met,
 * and whose active forecasting public contract carries valid S0266
 * input_guidance, resolves a bounded, contract-derived explanation built
 * only from public-contract presentation values -- never the backend's raw
 * message, training/development terminology, runtime diagnostics, or
 * submitted values. The backend violation is what authorizes this
 * explanation; the browser never infers payload invalidity on its own.
 * Falls back to the existing safe generic INVALID_PAYLOAD message for a
 * legacy contract without guidance, a malformed guidance shape, a
 * non-forecasting contract, or any other violation.
 */
function resolveInvalidPayloadMessage(
  errorCode: string | undefined,
  validationIssues: InferenceValidationIssue[] | undefined,
  contract: ContractPayload,
): string {
  const fallback = mapErrorCode(errorCode);
  if (errorCode !== "INVALID_PAYLOAD" || !isForecastingContractPayload(contract)) {
    return fallback;
  }
  const guidance = contract.history_series.input_guidance;
  if (!guidance) return fallback;
  const hasMinimumHistoryViolation = validationIssues?.some(
    (issue) => issue.violation === "forecasting_minimum_history_not_met",
  );
  if (!hasMinimumHistoryViolation) return fallback;
  return (
    `History must include ${guidance.required_anchor.display_value} and contain ` +
    `at least ${guidance.minimum_observation_count} observation(s).`
  );
}

/**
 * Project Spec S0147: the exhaustive allowlisted violation vocabulary the
 * shared governed inference boundary can report for an INVALID_PAYLOAD
 * response. An unrecognized value is never retained -- see
 * normalizeInferenceValidationIssues below.
 */
export type InferenceValidationViolation =
  | "missing_required_field"
  | "type_mismatch"
  | "domain_violation"
  | "forecasting_unknown_top_level_field"
  | "forecasting_invalid_history_shape"
  | "forecasting_invalid_history_row"
  | "forecasting_invalid_time_index"
  | "forecasting_invalid_target_value"
  | "forecasting_minimum_history_not_met";

/**
 * Project Spec S0147: one normalized, execution-level validation issue.
 * Deliberately narrower than the backend's own error entry -- carries only
 * the canonical field name and the allowlisted violation, never the
 * backend's raw message, error_code, submitted value, or any other
 * property.
 */
export type InferenceValidationIssue = {
  field: string;
  violation: InferenceValidationViolation;
};

const VALIDATION_ISSUE_VIOLATIONS: ReadonlySet<string> = new Set<InferenceValidationViolation>([
  "missing_required_field",
  "type_mismatch",
  "domain_violation",
  "forecasting_unknown_top_level_field",
  "forecasting_invalid_history_shape",
  "forecasting_invalid_history_row",
  "forecasting_invalid_time_index",
  "forecasting_invalid_target_value",
  "forecasting_minimum_history_not_met",
]);

const MAX_VALIDATION_ISSUE_FIELD_LENGTH = 200;
const MAX_VALIDATION_ISSUES = 20;

/**
 * Project Spec S0147: the sole boundary that may turn an unknown backend
 * `errors` value into a bounded, safe InferenceValidationIssue list. Every
 * retained entry must be a plain object carrying a non-empty, bounded-length
 * string `field` and an allowlisted `violation`; no other entry property is
 * ever retained (never the backend's `message`, `error_code`, or anything
 * else). Malformed records, unknown violation values, and oversized field
 * strings are dropped rather than surfaced. Duplicate canonical
 * field+violation pairs collapse to their first occurrence, preserving
 * backend order, and at most MAX_VALIDATION_ISSUES unique issues are
 * retained.
 */
export function normalizeInferenceValidationIssues(errors: unknown): InferenceValidationIssue[] | undefined {
  if (!Array.isArray(errors)) return undefined;

  const seen = new Set<string>();
  const issues: InferenceValidationIssue[] = [];

  for (const entry of errors) {
    if (issues.length >= MAX_VALIDATION_ISSUES) break;
    if (typeof entry !== "object" || entry === null) continue;

    const field = (entry as Record<string, unknown>).field;
    const violation = (entry as Record<string, unknown>).violation;

    if (typeof field !== "string") continue;
    const trimmedField = field.trim();
    if (!trimmedField || trimmedField.length > MAX_VALIDATION_ISSUE_FIELD_LENGTH) continue;
    if (typeof violation !== "string" || !VALIDATION_ISSUE_VIOLATIONS.has(violation)) continue;

    const key = `${trimmedField}::${violation}`;
    if (seen.has(key)) continue;
    seen.add(key);
    issues.push({ field: trimmedField, violation: violation as InferenceValidationViolation });
  }

  return issues.length > 0 ? issues : undefined;
}

/**
 * Project Spec S0151/S0152: the closed runtime diagnostic vocabulary the
 * private Admin route may attach to an otherwise-generic execution failure.
 * No free-form or dynamically constructed code is ever accepted -- see
 * normalizeInferenceRuntimeDiagnostic below.
 */
export type InferenceRuntimeDiagnosticCode =
  | "INFERENCE_BUNDLE_UNAVAILABLE"
  | "MODEL_ARTIFACT_UNAVAILABLE"
  | "MODEL_ARTIFACT_HASH_MISMATCH"
  | "RUNTIME_DEPENDENCY_UNAVAILABLE"
  | "MODEL_DESERIALIZATION_FAILED"
  | "PREDICTION_EXECUTION_FAILED"
  | "RESULT_VALIDATION_FAILED"
  | "RUNTIME_INPUT_CONTRACT_INCONSISTENT";

export type InferenceRuntimeDiagnostic = {
  code: InferenceRuntimeDiagnosticCode;
};

const RUNTIME_DIAGNOSTIC_CODES: ReadonlySet<string> = new Set<InferenceRuntimeDiagnosticCode>([
  "INFERENCE_BUNDLE_UNAVAILABLE",
  "MODEL_ARTIFACT_UNAVAILABLE",
  "MODEL_ARTIFACT_HASH_MISMATCH",
  "RUNTIME_DEPENDENCY_UNAVAILABLE",
  "MODEL_DESERIALIZATION_FAILED",
  "PREDICTION_EXECUTION_FAILED",
  "RESULT_VALIDATION_FAILED",
  "RUNTIME_INPUT_CONTRACT_INCONSISTENT",
]);

/**
 * Project Spec S0151: the sole boundary that may turn an unknown backend
 * `runtime_diagnostic` value into a bounded, safe InferenceRuntimeDiagnostic.
 * The backend response is always treated as untrusted input -- a non-object,
 * an array, a missing/unknown/malformed `code`, or any other shape is
 * dropped entirely. The returned value never carries any property beyond the
 * allowlisted `code`, so no backend message or additional property can ever
 * be retained.
 */
export function normalizeInferenceRuntimeDiagnostic(value: unknown): InferenceRuntimeDiagnostic | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const code = (value as Record<string, unknown>).code;
  if (typeof code !== "string" || !RUNTIME_DIAGNOSTIC_CODES.has(code)) return undefined;
  return { code: code as InferenceRuntimeDiagnosticCode };
}

/**
 * Project Spec S0143: the bounded typed outcome every inference executor
 * resolves to, whether it POSTs to the public route or a private Admin
 * route. Callers never see a raw Response/exception -- only this shape --
 * so no executor can smuggle a caller-supplied raw URL, header, or
 * transport detail through this boundary.
 *
 * Project Spec S0147: a failed outcome may additionally carry a bounded,
 * already-normalized validationIssues list (see
 * normalizeInferenceValidationIssues) -- never the raw backend `errors`
 * value, and never present on a successful outcome.
 *
 * Project Spec S0151: a failed outcome may additionally carry a bounded,
 * already-normalized runtimeDiagnostic (see
 * normalizeInferenceRuntimeDiagnostic) -- the public executor never reads or
 * sets this field, even if a malformed/misconfigured public response
 * includes one.
 */
export type InferenceExecutionResult =
  | { ok: true; result: unknown }
  | {
      ok: false;
      errorCode?: string;
      validationIssues?: InferenceValidationIssue[];
      runtimeDiagnostic?: InferenceRuntimeDiagnostic;
    };

/** Project Spec S0143: the historical scalar-feature payload shape, unchanged. */
export type ScalarInferencePayload = Record<string, string | number | boolean>;

/**
 * Project Spec S0250: a single history row carries exactly the governed
 * time-index and target keys (sourced from the active forecasting contract,
 * never caller-invented). The container key ("history") is fixed by the
 * governed runtime/public contract relationship already established by
 * S0246.
 */
export type ForecastingHistoryPayload = {
  history: Array<Record<string, string | number>>;
};

/**
 * Project Spec S0250: the closed executor payload union -- never widened to
 * unconstrained `any`. A caller never invents an arbitrary top-level key
 * beyond these two shapes.
 */
export type InferenceExecutorPayload = ScalarInferencePayload | ForecastingHistoryPayload;

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
  payload: InferenceExecutorPayload,
) => Promise<InferenceExecutionResult>;

async function defaultExecuteInference(
  slug: string,
  payload: InferenceExecutorPayload,
): Promise<InferenceExecutionResult> {
  try {
    const res = await fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}/inference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = (await res.json()) as { result?: unknown; error_code?: string; errors?: unknown };
    if (res.ok) {
      return { ok: true, result: body?.result };
    }
    // Project Spec S0147: normalized for type consistency with the private
    // Admin executor -- the public InferenceForm rendering path never reads
    // validationIssues, so no public UI begins showing field-level
    // diagnostics merely because this executor now carries them.
    return {
      ok: false,
      errorCode: body?.error_code,
      validationIssues: normalizeInferenceValidationIssues(body?.errors),
    };
  } catch {
    return { ok: false };
  }
}

/**
 * Project Spec S0147: one contract-filtered, label-resolved validation issue
 * captured into a validation_failed lifecycle event. The display label is
 * resolved once, at failure-capture time, using the same
 * customization-hint/feature-label/canonical-name precedence FieldInput
 * already renders with, so a later customization-draft edit can never
 * rewrite the meaning of a previously emitted session line. Never carries a
 * submitted value.
 */
export type InferenceLifecycleValidationIssue = {
  field: string;
  fieldLabel: string;
  violation: InferenceValidationViolation;
};

/**
 * Project Spec S0143: a bounded lifecycle seam consumers may observe without
 * this component implementing Publishing-console audit itself (that
 * consumption belongs to S0144). Never carries submitted field values, raw
 * payloads, headers, raw responses, stack traces, secrets or internal
 * paths -- only which phase of one submission just occurred.
 *
 * Project Spec S0147: a validation_failed event may additionally carry a
 * bounded, contract-filtered, label-resolved issues list. Absent or empty
 * when no valid issue remains, so the existing generic Publishing-console
 * fallback line stays available.
 *
 * Project Spec S0151: an execution_failed event may additionally carry a
 * bounded, already-normalized runtimeDiagnostic -- never present on any
 * other event type, even if a caller's outcome carries one.
 */
export type InferenceLifecycleEvent =
  | { type: "started" }
  | { type: "succeeded" }
  | { type: "validation_failed"; issues?: InferenceLifecycleValidationIssue[] }
  | { type: "execution_failed"; runtimeDiagnostic?: InferenceRuntimeDiagnostic };

type Props = {
  contract: ContractPayload;
  slug: string;
  customization?: PredictViewCustomization;
  adminInferenceGuidance?: unknown;
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
  resultContract?: ResultContract;
  /**
   * Project Spec S0112: the published Result Card presentation copy from
   * GET /datasets/{slug}/context's canonical result_card. A missing or
   * malformed value safely falls back to GENERIC_RESULT_PRESENTATION rather
   * than removing the form.
   */
  resultPresentation?: ResultPresentation;
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

const MAX_VALIDATION_FIELD_LABEL_LENGTH = 200;
const RESERVED_PAYLOAD_VALIDATION_FIELD = "payload";
const RESERVED_PAYLOAD_VALIDATION_FIELD_LABEL = "Inference payload";

function boundValidationFieldLabel(label: string): string {
  const trimmed = label.trim();
  return trimmed.length > MAX_VALIDATION_FIELD_LABEL_LENGTH
    ? trimmed.slice(0, MAX_VALIDATION_FIELD_LABEL_LENGTH)
    : trimmed;
}

// Project Spec S0147: the same display-label precedence FieldInput already
// renders with (customization display_label -> contract feature label ->
// canonical feature name), reused so a Publishing-console audit line always
// names a field the way the operator currently sees it in the form.
function resolveValidationFieldLabel(feature: Feature, hint: FieldHint | undefined): string {
  const custom = hint?.display_label?.trim();
  if (custom) return boundValidationFieldLabel(custom);
  const label = feature.label?.trim();
  if (label) return boundValidationFieldLabel(label);
  return boundValidationFieldLabel(feature.name);
}

/**
 * Project Spec S0147: filters a bounded normalized execution-level issue
 * list down to only fields the active form contract currently knows about
 * (or the reserved "payload" field, retained only for a payload-level
 * type_mismatch), resolving each retained issue's safe display label at
 * capture time. Never inspects the submitted field value -- filtering is by
 * field name only.
 */
function resolveLifecycleValidationIssues(
  issues: InferenceValidationIssue[] | undefined,
  features: Feature[],
  hintMap: Map<string, FieldHint>,
): InferenceLifecycleValidationIssue[] | undefined {
  if (!issues || issues.length === 0) return undefined;

  const featureMap = new Map(features.map((feature) => [feature.name, feature]));
  const resolved: InferenceLifecycleValidationIssue[] = [];

  for (const issue of issues) {
    if (issue.field === RESERVED_PAYLOAD_VALIDATION_FIELD) {
      if (issue.violation === "type_mismatch") {
        resolved.push({
          field: RESERVED_PAYLOAD_VALIDATION_FIELD,
          fieldLabel: RESERVED_PAYLOAD_VALIDATION_FIELD_LABEL,
          violation: issue.violation,
        });
      }
      continue;
    }

    const feature = featureMap.get(issue.field);
    if (!feature) continue;

    resolved.push({
      field: issue.field,
      fieldLabel: resolveValidationFieldLabel(feature, hintMap.get(issue.field)),
      violation: issue.violation,
    });
  }

  return resolved.length > 0 ? resolved : undefined;
}

const HISTORY_ROOT_FIELD = "history";
const HISTORY_ROW_PATH_PATTERN = /^history\[\d+\]$/;
const HISTORY_ROW_FIELD_PATH_PATTERN = /^history\[\d+\]\.(.+)$/;

// Project Spec S0250: deterministic field-path -> safe label mapping for
// forecasting validation issues. "history" -> "History"; "history[n]" ->
// "History row"; "history[n].<time field>"/"history[n].<target field>" ->
// the effective (customization-hint-aware) label for that governed field.
// Unlike resolveLifecycleValidationIssues above (which drops an issue for
// an unrecognized field name), an unrecognized/malformed forecasting path
// falls back to a generic safe label rather than being dropped -- every
// forecasting validation issue reaching this form was already scoped to a
// forecasting submission, so it is always plausibly this form's own.
function resolveForecastingValidationFieldLabel(
  fieldName: string,
  historySeries: HistorySeriesGuidance,
  hintMap: Map<string, FieldHint>,
): string {
  const custom = hintMap.get(fieldName)?.display_label?.trim();
  if (custom) return boundValidationFieldLabel(custom);
  if (fieldName === historySeries.time_index_field.name) {
    return boundValidationFieldLabel(historySeries.time_index_field.label);
  }
  if (fieldName === historySeries.target_field.name) {
    return boundValidationFieldLabel(historySeries.target_field.label);
  }
  return boundValidationFieldLabel(fieldName);
}

function resolveForecastingLifecycleValidationIssues(
  issues: InferenceValidationIssue[] | undefined,
  historySeries: HistorySeriesGuidance,
  hintMap: Map<string, FieldHint>,
): InferenceLifecycleValidationIssue[] | undefined {
  if (!issues || issues.length === 0) return undefined;

  const resolved: InferenceLifecycleValidationIssue[] = [];

  for (const issue of issues) {
    if (issue.field === HISTORY_ROOT_FIELD) {
      resolved.push({ field: issue.field, fieldLabel: "History", violation: issue.violation });
      continue;
    }

    if (HISTORY_ROW_PATH_PATTERN.test(issue.field)) {
      resolved.push({ field: issue.field, fieldLabel: "History row", violation: issue.violation });
      continue;
    }

    const rowFieldMatch = issue.field.match(HISTORY_ROW_FIELD_PATH_PATTERN);
    if (rowFieldMatch) {
      resolved.push({
        field: issue.field,
        fieldLabel: resolveForecastingValidationFieldLabel(rowFieldMatch[1], historySeries, hintMap),
        violation: issue.violation,
      });
      continue;
    }

    resolved.push({ field: issue.field, fieldLabel: "Field", violation: issue.violation });
  }

  return resolved.length > 0 ? resolved : undefined;
}

function FieldInput({
  feature,
  hint,
  guidance,
}: {
  feature: Feature;
  hint: FieldHint | undefined;
  guidance: AdminInferenceFieldGuidance | undefined;
}) {
  const displayLabel = hint?.display_label ?? feature.label;
  const explanatoryCopy = hint?.explanatory_copy;
  const helperText = explanatoryCopy || feature.description;
  const isCheckbox = feature.input_type === "checkbox";
  const isNumber = feature.input_type === "number";
  const numericDomain = isNumber ? guidance?.numeric_domain : undefined;
  const rangeText = numericDomain?.min !== undefined && numericDomain.max !== undefined
    ? `Accepted range: ${numericDomain.min} to ${numericDomain.max}.`
    : numericDomain?.min !== undefined
      ? `Minimum accepted value: ${numericDomain.min}.`
      : numericDomain?.max !== undefined
        ? `Maximum accepted value: ${numericDomain.max}.`
        : undefined;
  const helperId = `field-${feature.name}-helper`;
  const rangeId = `field-${feature.name}-range`;
  const describedBy = [helperText ? helperId : undefined, rangeText ? rangeId : undefined]
    .filter(Boolean)
    .join(" ") || undefined;

  const label = (
    <label className="public-inference-form__label" htmlFor={`field-${feature.name}`}>
      {displayLabel}
      {/* Project Spec S0146: a checkbox always represents a complete
          two-state boolean, so the required marker (which implies the
          checked state is mandatory) is scoped to non-boolean controls. */}
      {!feature.optional && !isCheckbox && (
        <span className="public-inference-form__required" aria-hidden="true"> *</span>
      )}
    </label>
  );

  // Project Spec S0156: a contract-declared conditional blank policy means
  // the backend must be allowed to evaluate the cross-field condition on a
  // blank submission -- native HTML5 required-field validation would block
  // form submission entirely before that value ever reaches handleSubmit,
  // so it is relaxed for exactly this case. The visual required marker
  // above is unaffected: the field remains logically required.
  const nativeRequired = !feature.optional && !feature.conditional_blank_policy;

  const control = isCheckbox ? (
    <input
      className="public-inference-form__control public-inference-form__control--checkbox"
      type="checkbox"
      id={`field-${feature.name}`}
      name={feature.name}
      aria-describedby={describedBy}
    />
  ) : feature.input_type === "select" && feature.options && feature.options.length > 0 ? (
    <select
      className="public-inference-form__control"
      id={`field-${feature.name}`}
      name={feature.name}
      required={nativeRequired}
      aria-describedby={describedBy}
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
      required={nativeRequired}
      aria-describedby={describedBy}
      min={isNumber ? numericDomain?.min : undefined}
      max={isNumber ? numericDomain?.max : undefined}
      step={isNumber ? "any" : undefined}
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
      {helperText && <p className="public-inference-form__helper" id={helperId}>{helperText}</p>}
      {rangeText && <p className="public-inference-form__helper" id={rangeId}>{rangeText}</p>}
    </div>
  );
}

export default function InferenceForm({
  contract,
  slug,
  customization,
  adminInferenceGuidance,
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

  // Project Spec S0250: the active branch is decided once, here, purely
  // from the contract's own discriminants -- every subsequent branch below
  // (guidance, sorting, submit dispatch, rendering) reuses this single
  // decision rather than re-deriving it from dataset slug, field names, or
  // any other signal.
  const isForecastingContract = isForecastingContractPayload(contract);

  // Project Spec S0250 Section W: the scalar Admin numeric-domain guidance
  // projection is never invoked for a forecasting contract -- history-series
  // fields have no per-field numeric_domain guidance concept.
  const guidanceMap = new Map(
    isForecastingContract
      ? []
      : normalizeAdminInferenceGuidance(adminInferenceGuidance, contract.features)
        .map((entry) => [entry.field_name, entry]),
  );

  const binaryContractAvailable = isAvailableBinaryResultContract(resultContract);
  const multiclassContractAvailable = isAvailableMulticlassResultContract(resultContract);
  const continuousRegressionContractAvailable = isAvailableContinuousRegressionResultContract(resultContract);
  const forecastingContractAvailable = isAvailableForecastingResultContract(resultContract);

  // Project Spec S0250: submission is enabled only when the active input
  // contract family and the active result-contract family agree exactly --
  // a forecasting input contract paired with a non-forecasting result
  // contract (or vice versa) never satisfies either branch below, so a
  // mismatched pairing fails closed automatically rather than needing a
  // second explicit check.
  const contractAvailable = !previewMode && (
    isForecastingContract
      ? forecastingContractAvailable
      : (binaryContractAvailable || multiclassContractAvailable || continuousRegressionContractAvailable)
  );

  const effectiveBinaryPresentation = resultPresentation?.schema_version === "binary-result-presentation.v1"
    ? resultPresentation : GENERIC_RESULT_PRESENTATION;
  const effectiveMulticlassPresentation = resultPresentation?.schema_version === "multiclass-result-presentation.v1"
    ? resultPresentation : GENERIC_MULTICLASS_RESULT_PRESENTATION;
  const effectiveContinuousRegressionPresentation = resultPresentation?.schema_version === "continuous-regression-result-presentation.v1"
    ? resultPresentation : GENERIC_CONTINUOUS_REGRESSION_RESULT_PRESENTATION;
  const effectiveForecastingPresentation = resultPresentation?.schema_version === "univariate-forecasting-result-presentation.v1"
    ? resultPresentation : GENERIC_UNIVARIATE_FORECASTING_RESULT_PRESENTATION;

  // Project Spec S0141: the local zero-probability initial projection is
  // built through the same shared technical-result boundary the real
  // inference response is validated against -- never a second result
  // vocabulary -- and only ever computed while contractAvailable (so it can
  // never be requested for an unavailable/malformed contract).
  const initialResult =
    binaryContractAvailable && typeof initialResultProbability === "number"
      ? projectBinaryClassificationResult(resultContract.semantics, initialResultProbability)
      : null;

  const sortedForPresentation = isForecastingContract
    ? []
    : [...contract.features].sort((a, b) => {
      const hintA = hintMap.get(a.name);
      const hintB = hintMap.get(b.name);
      return presentationSortKey(a, hintA) - presentationSortKey(b, hintB);
    });

  // Project Spec S0250: HistorySeriesInput owns its own controlled row
  // state and reports every change here via onRowsChange, so handleSubmit
  // can read the current rows synchronously (a ref, not React state, so no
  // stale-closure risk across re-renders) and serialize them exactly once
  // at submit time -- InferenceForm never re-derives or duplicates that
  // state itself.
  const historyRowsRef = useRef<HistoryRowInput[]>([]);

  // Project Spec S0143: shared submit-outcome handling for both the scalar
  // and forecasting branches -- executor invocation, stale-response
  // detection, success/error state, and lifecycle event emission are never
  // duplicated between the two branches.
  async function submitAndHandle(
    payload: InferenceExecutorPayload,
    generation: number,
    resolveIssues: (issues: InferenceValidationIssue[] | undefined) => InferenceLifecycleValidationIssue[] | undefined,
  ) {
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
      const normalizedResult = resultForContract(resultContract, outcome.result);
      if (normalizedResult) {
        setSubmission({ status: "success", data: normalizedResult });
        onLifecycleEvent?.({ type: "succeeded" });
      } else {
        // Malformed success payload: never falls back to a legacy
        // body.prediction field, always becomes the existing safe error state.
        setSubmission({ status: "error", message: FALLBACK_ERROR });
        onLifecycleEvent?.({ type: "execution_failed" });
      }
    } else {
      setSubmission({
        status: "error",
        message: resolveInvalidPayloadMessage(outcome.errorCode, outcome.validationIssues, contract),
      });
      if (outcome.errorCode === "INVALID_PAYLOAD") {
        const issues = resolveIssues(outcome.validationIssues);
        onLifecycleEvent?.(issues ? { type: "validation_failed", issues } : { type: "validation_failed" });
      } else {
        onLifecycleEvent?.({ type: "execution_failed", runtimeDiagnostic: outcome.runtimeDiagnostic });
      }
    }
  }

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

    if (isForecastingContractPayload(contract)) {
      // Project Spec S0250 Section L: read controlled rows in
      // rendered/user order, serialize exactly once, using only the exact
      // governed field names -- never sorted, deduplicated, gap-filled, or
      // extended with an invented row/horizon/frequency/model metadata.
      const { time_index_field, target_field } = contract.history_series;
      const history = historyRowsRef.current.map((row) => ({
        [time_index_field.name]:
          time_index_field.value_kind === "ordinal_time"
            ? Number(row.timeIndexValue)
            : row.timeIndexValue,
        [target_field.name]: Number(row.targetValue),
      }));

      await submitAndHandle(
        { history },
        generation,
        (issues) => resolveForecastingLifecycleValidationIssues(issues, contract.history_series, hintMap),
      );
      return;
    }

    const form = event.currentTarget;
    const payload: ScalarInferencePayload = {};

    for (const feature of sortedForPresentation) {
      if (feature.input_type === "checkbox") {
        const el = form.elements.namedItem(feature.name) as HTMLInputElement | null;
        payload[feature.name] = el ? el.checked : false;
      } else if (feature.input_type === "number") {
        const el = form.elements.namedItem(feature.name) as HTMLInputElement | null;
        const raw = el ? el.value : "";
        if (raw !== "") {
          payload[feature.name] = Number(raw);
        } else if (feature.conditional_blank_policy) {
          // Project Spec S0156: a contract-declared conditional blank field
          // must reach backend validation with its declared blank
          // representation instead of being silently omitted -- the
          // backend evaluates the cross-field condition, never the browser.
          payload[feature.name] = "";
        }
        // else: S0152 behavior unchanged -- an ordinary optional empty
        // numeric input with no conditional policy is omitted entirely.
      } else {
        // "select" (rendered as a native <select> when options are
        // available, or an unguided text input otherwise).
        const el = form.elements.namedItem(feature.name) as
          | HTMLInputElement
          | HTMLSelectElement
          | null;
        if (el && el.value !== "") {
          // Project Spec S0156: serialize strictly from the contract's
          // select_value_type hint, never from the selected text/label or
          // the field name.
          payload[feature.name] =
            feature.input_type === "select" && feature.select_value_type === "integer"
              ? Number(el.value)
              : el.value;
        } else if (feature.conditional_blank_policy) {
          payload[feature.name] = "";
        }
      }
    }

    await submitAndHandle(
      payload,
      generation,
      (issues) => resolveLifecycleValidationIssues(issues, contract.features, hintMap),
    );
  }

  function renderFields(features: Feature[]) {
    return features.map((feature) => {
      const hint = hintMap.get(feature.name);
      if (hint?.hidden === true) return null;
      return <FieldInput key={feature.name} feature={feature} hint={hint} guidance={guidanceMap.get(feature.name)} />;
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
          {isForecastingContract ? (
            <HistorySeriesInput
              historySeries={contract.history_series}
              forecast={contract.forecast}
              hintMap={hintMap}
              onRowsChange={(rows) => {
                historyRowsRef.current = rows;
              }}
            />
          ) : hasGroups ? (
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
          <BinaryClassificationResult result={initialResult} presentation={effectiveBinaryPresentation} />
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
          {submission.data.problem_type === "binary_classification" ? (
            <BinaryClassificationResult result={submission.data} presentation={effectiveBinaryPresentation} />
          ) : submission.data.problem_type === "multiclass_classification" ? (
            <MulticlassClassificationResult result={submission.data} presentation={effectiveMulticlassPresentation} />
          ) : submission.data.problem_type === "univariate_forecasting" ? (
            <UnivariateForecastingResult result={submission.data} presentation={effectiveForecastingPresentation} />
          ) : (
            <ContinuousRegressionResult result={submission.data} presentation={effectiveContinuousRegressionPresentation} />
          )}
        </ResultCardShell>
      )}
    </section>
  );
}
