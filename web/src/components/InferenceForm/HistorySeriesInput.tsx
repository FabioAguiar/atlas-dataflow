import { useEffect, useState, type ReactElement } from "react";
import type { FieldHint } from "./InferenceForm";

/**
 * Project Spec S0250: presentation-safe projection of the active
 * public-contract v2 history_series block. Mirrors
 * contracts/public-contract.schema.json's public_history_series_v2 shape
 * exactly -- never carries runtime-only fields (minimum observation count,
 * ordering policy, uniqueness/frequency-contiguity requirements). The
 * runtime contract remains the sole payload-validation authority.
 */
export type HistoryTemporalField = {
  name: string;
  label: string;
  value_kind: "calendar_period" | "timestamp" | "ordinal_time";
  display_order: number;
};

export type HistoryTargetField = {
  name: string;
  label: string;
  value_kind: "number";
  display_order: number;
};

/**
 * Project Spec S0266: presentation-safe projection of a governed S0265
 * history-input policy. Mirrors public_history_input_guidance_v2 exactly --
 * never carries required_anchor.source, development_end, training_scope, or
 * any other runtime/training-only field name or value. Optional: absent on
 * a legacy public-contract v2 document that predates S0266.
 */
export type HistoryInputGuidance = {
  minimum_observation_count: number;
  required_anchor: { display_value: string };
  continuity: "consecutive_by_frequency";
};

/**
 * Project Spec S0267: strict, bounded, machine-actionable projection of a
 * temporal interaction profile for the current supported month-oriented UI
 * control. Mirrors public_temporal_interaction_v2 exactly -- never widened
 * to `any`/`Record<string, unknown>`/arbitrary control or step kinds.
 * Optional: absent on a legacy public-contract v2 document that predates
 * S0267, and absent whenever the governed temporal kind/frequency has no
 * supported machine interaction profile. `required_anchor.value` is the
 * canonical machine anchor, distinct from
 * HistoryInputGuidance.required_anchor.display_value -- the latter is never
 * parsed for builder logic.
 */
export type HistoryTemporalInteraction = {
  control_kind: "month";
  required_anchor: {
    value: string;
    inclusion: "required";
  };
  sequence: {
    step_kind: "calendar_month";
    continuity: "required";
  };
};

export type HistorySeriesGuidance = {
  time_index_field: HistoryTemporalField;
  target_field: HistoryTargetField;
  frequency: string;
  input_guidance?: HistoryInputGuidance;
  temporal_interaction?: HistoryTemporalInteraction;
};

export type ForecastGuidance = {
  forecast_horizon: number;
  horizon_user_editable: false;
  /**
   * Project Spec S0266: optional bounded presentation indication that the
   * forecast starts after the last validated/supplied history observation.
   * Absent on a legacy public-contract v2 document that predates S0266.
   */
  origin_behavior?: "starts_after_last_history_observation";
};

/**
 * One controlled, presentation-layer history row. Values are kept as raw
 * strings exactly as typed -- InferenceForm is responsible for the single
 * governed serialization pass (ordinal integer / calendar-period-or-
 * timestamp string / numeric target) at submit time; this component never
 * serializes or validates a row itself.
 */
export type HistoryRowInput = {
  timeIndexValue: string;
  targetValue: string;
};

function makeEmptyRow(): HistoryRowInput {
  return { timeIndexValue: "", targetValue: "" };
}

/**
 * Project Spec S0268: strict canonical calendar-month value, YYYY-MM with
 * month 01..12. Deliberately the same pattern the runtime/public-contract
 * schema enforces for temporal_interaction.required_anchor.value.
 */
const CANONICAL_MONTH_PATTERN = /^[0-9]{4}-(0[1-9]|1[0-2])$/;

/**
 * Project Spec S0268: bounded runtime-safe guided-profile discriminator.
 * Guided mode activates only for a coherent current S0267 month profile --
 * every field below is checked against its exact governed value rather than
 * trusted from the TypeScript type alone, since a malformed/incoherent
 * public contract must fall back to the legacy free-form row UX rather than
 * guessing a stepping profile. Never derived from frequency text, dataset
 * slug, or target field name.
 */
function resolveGuidedAnchor(historySeries: HistorySeriesGuidance): string | null {
  const interaction = historySeries.temporal_interaction;
  if (!interaction || typeof interaction !== "object") return null;
  if (historySeries.time_index_field.value_kind !== "calendar_period") return null;
  if (interaction.control_kind !== "month") return null;
  if (!interaction.required_anchor || interaction.required_anchor.inclusion !== "required") return null;
  if (!interaction.sequence || interaction.sequence.step_kind !== "calendar_month") return null;
  if (interaction.sequence.continuity !== "required") return null;
  const anchor = interaction.required_anchor.value;
  if (typeof anchor !== "string" || !CANONICAL_MONTH_PATTERN.test(anchor)) return null;
  return anchor;
}

/**
 * Project Spec S0268: deterministic calendar-month arithmetic on canonical
 * YYYY-MM strings, implemented as pure integer month-index math -- never
 * locale/timezone-sensitive Date parsing, so results never depend on
 * browser timezone, local DST, or Date string parsing differences.
 */
function toMonthIndex(value: string): number | null {
  const match = CANONICAL_MONTH_PATTERN.exec(value);
  if (!match) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  return year * 12 + (month - 1);
}

function fromMonthIndex(index: number): string {
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}`;
}

function stepMonth(value: string, delta: number): string {
  const index = toMonthIndex(value);
  return index === null ? value : fromMonthIndex(index + delta);
}

function compareCanonicalMonth(a: string, b: string): number {
  const indexA = toMonthIndex(a);
  const indexB = toMonthIndex(b);
  if (indexA === null || indexB === null) return 0;
  return indexA - indexB;
}

function generateMonthRange(from: string, through: string): string[] {
  const start = toMonthIndex(from);
  const end = toMonthIndex(through);
  if (start === null || end === null || start > end) return [];
  const months: string[] = [];
  for (let index = start; index <= end; index += 1) {
    months.push(fromMonthIndex(index));
  }
  return months;
}

type Props = {
  historySeries: HistorySeriesGuidance;
  forecast: ForecastGuidance;
  hintMap: Map<string, FieldHint>;
  /**
   * Called with the full current row array on every add/remove/edit, so
   * InferenceForm can read the latest rows synchronously at submit time
   * (via a ref) without this component exposing imperative handles or
   * InferenceForm re-deriving/duplicating this state itself.
   */
  onRowsChange: (rows: HistoryRowInput[]) => void;
};

type SharedRowLayout = {
  timeLabel: string;
  targetLabel: string;
  timeFirst: boolean;
  timeHeader: ReactElement;
  targetHeader: ReactElement;
};

/**
 * Project Spec S0250: the pre-S0268 free-form row editor, unchanged in
 * behavior/markup. Active whenever resolveGuidedAnchor cannot resolve a
 * coherent S0267 month profile -- a legacy public-contract v2 document
 * without temporal_interaction, or an unsupported/incoherent one.
 */
function LegacyHistoryRows({
  timeField,
  targetField,
  layout,
  onRowsChange,
}: {
  timeField: HistoryTemporalField;
  targetField: HistoryTargetField;
  layout: SharedRowLayout;
  onRowsChange: (rows: HistoryRowInput[]) => void;
}) {
  const [rows, setRows] = useState<HistoryRowInput[]>(() => [makeEmptyRow()]);

  // Project Spec S0250: reports the current rows to the caller after every
  // commit (including the initial mount) -- never during render itself, so
  // this never fires a parent state update while HistorySeriesInput is
  // still rendering.
  useEffect(() => {
    onRowsChange(rows);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  function handleAddRow() {
    // Project Spec S0250: appended to the end -- never sorted, never
    // inserted at an inferred chronological position.
    setRows((current) => [...current, makeEmptyRow()]);
  }

  function handleRemoveRow(index: number) {
    // At least one row must always remain renderable.
    setRows((current) => (current.length <= 1 ? current : current.filter((_, i) => i !== index)));
  }

  function handleChangeRow(index: number, key: keyof HistoryRowInput, value: string) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  }

  const timeInputType = timeField.value_kind === "ordinal_time" ? "number" : "text";
  const timeInputMode = timeField.value_kind === "ordinal_time" ? "numeric" : "text";
  const { timeLabel, targetLabel, timeFirst, timeHeader, targetHeader } = layout;

  function renderRow(row: HistoryRowInput, index: number) {
    const timeCell = (
      <td key="time" className="history-series-input__cell">
        <label className="history-series-input__sr-label" htmlFor={`history-row-${index}-time`}>
          {timeLabel}
        </label>
        <input
          id={`history-row-${index}-time`}
          className="history-series-input__control"
          type={timeInputType}
          inputMode={timeInputMode}
          step={timeField.value_kind === "ordinal_time" ? "1" : undefined}
          required
          value={row.timeIndexValue}
          onChange={(event) => handleChangeRow(index, "timeIndexValue", event.target.value)}
        />
      </td>
    );
    const targetCell = (
      <td key="target" className="history-series-input__cell">
        <label className="history-series-input__sr-label" htmlFor={`history-row-${index}-target`}>
          {targetLabel}
        </label>
        <input
          id={`history-row-${index}-target`}
          className="history-series-input__control"
          type="number"
          inputMode="decimal"
          step="any"
          required
          value={row.targetValue}
          onChange={(event) => handleChangeRow(index, "targetValue", event.target.value)}
        />
      </td>
    );
    return timeFirst ? [timeCell, targetCell] : [targetCell, timeCell];
  }

  return (
    <>
      <div className="history-series-input__table-scroll">
        <table className="history-series-input__table">
          <thead>
            <tr>
              {timeFirst ? [timeHeader, targetHeader] : [targetHeader, timeHeader]}
              <th scope="col" className="history-series-input__column-header history-series-input__column-header--actions">
                <span className="history-series-input__sr-label">Row actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="history-series-input__row">
                {renderRow(row, index)}
                <td className="history-series-input__row-actions">
                  <button
                    type="button"
                    className="history-series-input__remove-row"
                    onClick={() => handleRemoveRow(index)}
                    disabled={rows.length <= 1}
                  >
                    Remove row
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button type="button" className="history-series-input__add-row" onClick={handleAddRow}>
        Add row
      </button>
    </>
  );
}

/**
 * Project Spec S0268: contract-driven guided month-range builder. Active
 * only when resolveGuidedAnchor resolves a coherent S0267 month profile.
 * Initializes an anchor-inclusive range from the machine anchor (never
 * input_guidance.required_anchor.display_value), generates every calendar
 * month in the inclusive [historyFrom, historyThrough] range, and replaces
 * arbitrary Add row/Remove row mutation with bounded
 * Add previous observation / Add next observation range-extension
 * shortcuts. The required anchor can never leave the generated range
 * because both boundaries are constrained to remain on opposite sides of
 * (or equal to) the anchor.
 */
function GuidedHistoryBuilder({
  anchor,
  layout,
  forecast,
  onRowsChange,
}: {
  anchor: string;
  layout: SharedRowLayout;
  forecast: ForecastGuidance;
  onRowsChange: (rows: HistoryRowInput[]) => void;
}) {
  const [historyFrom, setHistoryFrom] = useState(anchor);
  const [historyThrough, setHistoryThrough] = useState(anchor);
  const [targetValues, setTargetValues] = useState<Record<string, string>>({});

  const periods = generateMonthRange(historyFrom, historyThrough);

  // Project Spec S0268: reports the complete chronological generated row
  // list to the caller after every commit (including the initial mount),
  // mirroring the same after-commit reporting discipline LegacyHistoryRows
  // already uses.
  useEffect(() => {
    onRowsChange(periods.map((period) => ({ timeIndexValue: period, targetValue: targetValues[period] ?? "" })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyFrom, historyThrough, targetValues]);

  // Project Spec S0268 Section G: a boundary change may shrink the visible
  // range -- pruning here means a period that later re-enters the range
  // (via a different boundary change) is treated as newly generated (empty
  // target), rather than resurrecting a stale value from before the shrink.
  function pruneTargetValues(periodsToKeep: string[]) {
    const keepSet = new Set(periodsToKeep);
    setTargetValues((current) => {
      let changed = false;
      const next: Record<string, string> = {};
      for (const [period, value] of Object.entries(current)) {
        if (keepSet.has(period)) {
          next[period] = value;
        } else {
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }

  function handleHistoryFromChange(value: string) {
    // Project Spec S0268 Section E: an invalid/incoherent programmatic
    // event (malformed value, or one that would move History from later
    // than the anchor) keeps the last coherent range rather than
    // generating an anchor-free sequence.
    if (!CANONICAL_MONTH_PATTERN.test(value)) return;
    if (compareCanonicalMonth(value, anchor) > 0) return;
    pruneTargetValues(generateMonthRange(value, historyThrough));
    setHistoryFrom(value);
  }

  function handleHistoryThroughChange(value: string) {
    if (!CANONICAL_MONTH_PATTERN.test(value)) return;
    if (compareCanonicalMonth(value, anchor) < 0) return;
    pruneTargetValues(generateMonthRange(historyFrom, value));
    setHistoryThrough(value);
  }

  function handleTargetChange(period: string, value: string) {
    setTargetValues((current) => ({ ...current, [period]: value }));
  }

  const { timeLabel, targetLabel, timeFirst, timeHeader, targetHeader } = layout;

  // Project Spec S0268 Section J: a bounded, explanatory-only forecast
  // range preview, rendered only for the declared starts-after-last-
  // history-observation origin behavior. Never fabricated when that origin
  // behavior is absent/unsupported, and never alters the submitted payload
  // or horizon.
  const showForecastPreview = forecast.origin_behavior === "starts_after_last_history_observation";
  const forecastPreviewStart = showForecastPreview ? stepMonth(historyThrough, 1) : null;
  const forecastPreviewEnd = showForecastPreview ? stepMonth(historyThrough, forecast.forecast_horizon) : null;

  return (
    <>
      <div className="history-series-input__guided-controls">
        <div className="history-series-input__range-field">
          <label className="history-series-input__range-label" htmlFor="history-series-history-from">
            History from
          </label>
          <input
            id="history-series-history-from"
            className="history-series-input__control history-series-input__range-input"
            type="month"
            value={historyFrom}
            max={anchor}
            onChange={(event) => handleHistoryFromChange(event.target.value)}
          />
        </div>
        <div className="history-series-input__range-field">
          <label className="history-series-input__range-label" htmlFor="history-series-history-through">
            History through
          </label>
          <input
            id="history-series-history-through"
            className="history-series-input__control history-series-input__range-input"
            type="month"
            value={historyThrough}
            min={anchor}
            onChange={(event) => handleHistoryThroughChange(event.target.value)}
          />
        </div>
      </div>

      <div className="history-series-input__range-actions">
        <button
          type="button"
          className="history-series-input__range-action"
          onClick={() => setHistoryFrom((current) => stepMonth(current, -1))}
        >
          Add previous observation
        </button>
        <button
          type="button"
          className="history-series-input__range-action"
          onClick={() => setHistoryThrough((current) => stepMonth(current, 1))}
        >
          Add next observation
        </button>
      </div>

      <div className="history-series-input__table-scroll">
        <table className="history-series-input__table">
          <thead>
            <tr>{timeFirst ? [timeHeader, targetHeader] : [targetHeader, timeHeader]}</tr>
          </thead>
          <tbody>
            {periods.map((period) => {
              const periodCell = (
                <td key="time" className="history-series-input__cell">
                  <span className="history-series-input__sr-label">{timeLabel}</span>
                  <span className="history-series-input__period-value">{period}</span>
                </td>
              );
              const targetCell = (
                <td key="target" className="history-series-input__cell">
                  <label className="history-series-input__sr-label" htmlFor={`history-guided-${period}-target`}>
                    {targetLabel}
                  </label>
                  <input
                    id={`history-guided-${period}-target`}
                    className="history-series-input__control"
                    type="number"
                    inputMode="decimal"
                    step="any"
                    required
                    value={targetValues[period] ?? ""}
                    onChange={(event) => handleTargetChange(period, event.target.value)}
                  />
                </td>
              );
              return (
                <tr key={period} className="history-series-input__row">
                  {timeFirst ? [periodCell, targetCell] : [targetCell, periodCell]}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {forecastPreviewStart !== null && forecastPreviewEnd !== null && (
        <p className="history-series-input__forecast-preview">
          Forecast range: {forecastPreviewStart} → {forecastPreviewEnd}
        </p>
      )}
    </>
  );
}

export default function HistorySeriesInput({ historySeries, forecast, hintMap, onRowsChange }: Props) {
  const timeField = historySeries.time_index_field;
  const targetField = historySeries.target_field;
  const timeHint = hintMap.get(timeField.name);
  const targetHint = hintMap.get(targetField.name);

  const timeLabel = timeHint?.display_label?.trim() || timeField.label;
  const targetLabel = targetHint?.display_label?.trim() || targetField.label;
  const timeCopy = timeHint?.explanatory_copy;
  const targetCopy = targetHint?.explanatory_copy;

  // Project Spec S0250: field-hint display_order_hint, falling back to the
  // contract's own display_order -- the same presentation-sort precedence
  // the scalar form already applies -- decides which column renders first.
  const timeOrder = timeHint?.display_order_hint ?? timeField.display_order;
  const targetOrder = targetHint?.display_order_hint ?? targetField.display_order;
  const timeFirst = timeOrder <= targetOrder;

  const timeHeader = (
    <th key="time" scope="col" className="history-series-input__column-header">
      {timeLabel}
    </th>
  );
  const targetHeader = (
    <th key="target" scope="col" className="history-series-input__column-header">
      {targetLabel}
    </th>
  );

  const layout: SharedRowLayout = { timeLabel, targetLabel, timeFirst, timeHeader, targetHeader };

  // Project Spec S0268 Section B: the sole guided-mode discriminator --
  // never re-derived from frequency text, dataset slug, or field name
  // anywhere else in this component.
  const guidedAnchor = resolveGuidedAnchor(historySeries);

  return (
    <div className="history-series-input" aria-label="Historical observations">
      <div className="history-series-input__guidance">
        <p className="history-series-input__guidance-item">
          <span className="history-series-input__guidance-label">Frequency</span>
          <span className="history-series-input__guidance-value">{historySeries.frequency}</span>
        </p>
        <p className="history-series-input__guidance-item">
          <span className="history-series-input__guidance-label">Forecast horizon</span>
          <span className="history-series-input__guidance-value">{forecast.forecast_horizon}</span>
          <span className="history-series-input__guidance-note"> (fixed, not editable)</span>
        </p>
        {historySeries.input_guidance && (
          <>
            <p className="history-series-input__guidance-item">
              <span className="history-series-input__guidance-label">Minimum observations</span>
              <span className="history-series-input__guidance-value">
                {historySeries.input_guidance.minimum_observation_count}
              </span>
            </p>
            <p className="history-series-input__guidance-item">
              <span className="history-series-input__guidance-label">Required history anchor</span>
              <span className="history-series-input__guidance-value">
                {historySeries.input_guidance.required_anchor.display_value}
              </span>
            </p>
            <p className="history-series-input__guidance-note">
              Add later observations consecutively at the governed {historySeries.frequency} frequency.
            </p>
          </>
        )}
        {forecast.origin_behavior === "starts_after_last_history_observation" && (
          <p className="history-series-input__guidance-note">
            The forecast starts after the last valid history observation.
          </p>
        )}
      </div>

      {(timeCopy || targetCopy) && (
        <div className="history-series-input__copy">
          {timeCopy && <p className="history-series-input__helper">{timeCopy}</p>}
          {targetCopy && <p className="history-series-input__helper">{targetCopy}</p>}
        </div>
      )}

      {guidedAnchor !== null ? (
        <GuidedHistoryBuilder anchor={guidedAnchor} layout={layout} forecast={forecast} onRowsChange={onRowsChange} />
      ) : (
        <LegacyHistoryRows timeField={timeField} targetField={targetField} layout={layout} onRowsChange={onRowsChange} />
      )}
    </div>
  );
}
