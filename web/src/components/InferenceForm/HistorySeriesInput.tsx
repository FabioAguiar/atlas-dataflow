import { useEffect, useState } from "react";
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

export type HistorySeriesGuidance = {
  time_index_field: HistoryTemporalField;
  target_field: HistoryTargetField;
  frequency: string;
};

export type ForecastGuidance = {
  forecast_horizon: number;
  horizon_user_editable: false;
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

export default function HistorySeriesInput({ historySeries, forecast, hintMap, onRowsChange }: Props) {
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

  const timeInputType = timeField.value_kind === "ordinal_time" ? "number" : "text";
  const timeInputMode = timeField.value_kind === "ordinal_time" ? "numeric" : "text";

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
      </div>

      {(timeCopy || targetCopy) && (
        <div className="history-series-input__copy">
          {timeCopy && <p className="history-series-input__helper">{timeCopy}</p>}
          {targetCopy && <p className="history-series-input__helper">{targetCopy}</p>}
        </div>
      )}

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
    </div>
  );
}
