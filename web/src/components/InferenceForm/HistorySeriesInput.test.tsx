import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HistorySeriesInput, {
  type ForecastGuidance,
  type HistoryInputGuidance,
  type HistorySeriesGuidance,
  type HistoryTemporalInteraction,
} from "./HistorySeriesInput";
import type { FieldHint } from "./InferenceForm";

afterEach(() => {
  cleanup();
});

const historySeries: HistorySeriesGuidance = {
  time_index_field: { name: "period", label: "Period", value_kind: "calendar_period", display_order: 1 },
  target_field: { name: "passengers", label: "Passengers", value_kind: "number", display_order: 2 },
  frequency: "Monthly",
};

const forecast: ForecastGuidance = {
  forecast_horizon: 12,
  horizon_user_editable: false,
};

function emptyHintMap(): Map<string, FieldHint> {
  return new Map();
}

describe("HistorySeriesInput (Project Spec S0250)", () => {
  it("renders exactly one initial row", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getAllByLabelText("Period")).toHaveLength(1);
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(1);
  });

  it("reports the initial single empty row to the caller", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    expect(onRowsChange).toHaveBeenLastCalledWith([{ timeIndexValue: "", targetValue: "" }]);
  });

  it("adds a row when Add row is clicked, preserving the first row's values", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    fireEvent.change(screen.getAllByLabelText("Period")[0], { target: { value: "2026-01" } });
    fireEvent.change(screen.getAllByLabelText("Passengers")[0], { target: { value: "112" } });
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));

    expect(screen.getAllByLabelText("Period")).toHaveLength(2);
    expect(onRowsChange).toHaveBeenLastCalledWith([
      { timeIndexValue: "2026-01", targetValue: "112" },
      { timeIndexValue: "", targetValue: "" },
    ]);
  });

  it("removes a row while retaining at least one renderable row", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(screen.getAllByLabelText("Period")).toHaveLength(2);

    fireEvent.click(screen.getAllByRole("button", { name: "Remove row" })[0]);
    expect(screen.getAllByLabelText("Period")).toHaveLength(1);
  });

  it("disables Remove row when only one row remains", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Remove row" })).toBeDisabled();
  });

  it("renders the governed time and target field labels", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Period")).toBeInTheDocument();
    expect(screen.getByLabelText("Passengers")).toBeInTheDocument();
  });

  it("prefers a field hint's display_label over the contract field label", () => {
    const hintMap = new Map<string, FieldHint>([
      ["period", { field_name: "period", display_label: "Month" }],
      ["passengers", { field_name: "passengers", display_label: "Ridership" }],
    ]);
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={hintMap}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Month")).toBeInTheDocument();
    expect(screen.getByLabelText("Ridership")).toBeInTheDocument();
    expect(screen.queryByLabelText("Period")).not.toBeInTheDocument();
  });

  it("renders explanatory copy from field hints", () => {
    const hintMap = new Map<string, FieldHint>([
      ["period", { field_name: "period", explanatory_copy: "Calendar month of the observation." }],
    ]);
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={hintMap}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Calendar month of the observation.")).toBeInTheDocument();
  });

  it("orders columns using field-hint display_order_hint, swapping the default contract order", () => {
    const hintMap = new Map<string, FieldHint>([
      ["period", { field_name: "period", display_order_hint: 2 }],
      ["passengers", { field_name: "passengers", display_order_hint: 1 }],
    ]);
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={hintMap}
        onRowsChange={vi.fn()}
      />,
    );

    const headers = screen.getAllByRole("columnheader").map((el) => el.textContent);
    expect(headers[0]).toBe("Passengers");
    expect(headers[1]).toBe("Period");
  });

  it("renders the governed frequency as guidance", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Monthly")).toBeInTheDocument();
  });

  it("renders the governed forecast horizon as read-only guidance", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText(/not editable/i)).toBeInTheDocument();
  });

  it("never renders a user-editable horizon input control", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    // Exactly two inputs exist for the single initial row -- time index and
    // target -- never a third, horizon-editing control.
    expect(document.querySelectorAll("input")).toHaveLength(2);
  });

  it("renders a text input for a calendar_period time-index field", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    const input = screen.getByLabelText("Period") as HTMLInputElement;
    expect(input.type).toBe("text");
  });

  it("renders a text input for a timestamp time-index field", () => {
    const timestampSeries: HistorySeriesGuidance = {
      ...historySeries,
      time_index_field: { ...historySeries.time_index_field, value_kind: "timestamp" },
    };
    render(
      <HistorySeriesInput
        historySeries={timestampSeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    const input = screen.getByLabelText("Period") as HTMLInputElement;
    expect(input.type).toBe("text");
  });

  it("renders a number input with an integer step for an ordinal_time time-index field", () => {
    const ordinalSeries: HistorySeriesGuidance = {
      ...historySeries,
      time_index_field: { ...historySeries.time_index_field, value_kind: "ordinal_time" },
    };
    render(
      <HistorySeriesInput
        historySeries={ordinalSeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    const input = screen.getByLabelText("Period") as HTMLInputElement;
    expect(input.type).toBe("number");
    expect(input.step).toBe("1");
  });

  it("renders a number input for the target field", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    const input = screen.getByLabelText("Passengers") as HTMLInputElement;
    expect(input.type).toBe("number");
  });

  it("preserves user row order when adding rows -- never auto-sorts", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    fireEvent.change(screen.getAllByLabelText("Period")[0], { target: { value: "2026-03" } });
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    fireEvent.change(screen.getAllByLabelText("Period")[1], { target: { value: "2026-01" } });

    expect(onRowsChange).toHaveBeenLastCalledWith([
      { timeIndexValue: "2026-03", targetValue: "" },
      { timeIndexValue: "2026-01", targetValue: "" },
    ]);
  });

  it("does not persist entered values after unmount/remount", () => {
    const { unmount } = render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getAllByLabelText("Period")[0], { target: { value: "2026-05" } });
    unmount();

    const onRowsChangeAfterRemount = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChangeAfterRemount}
      />,
    );

    expect((screen.getByLabelText("Period") as HTMLInputElement).value).toBe("");
    expect(onRowsChangeAfterRemount).toHaveBeenLastCalledWith([{ timeIndexValue: "", targetValue: "" }]);
  });
});

// Project Spec S0266: optional bounded history-input guidance and forecast
// origin-behavior presentation. Exercised independently of the S0250
// coverage above, which must remain unaffected by a legacy contract with no
// guidance.
describe("HistorySeriesInput history-input guidance (Project Spec S0266)", () => {
  const inputGuidance: HistoryInputGuidance = {
    minimum_observation_count: 1,
    required_anchor: { display_value: "1938-12" },
    continuity: "consecutive_by_frequency",
  };

  const historySeriesWithGuidance: HistorySeriesGuidance = {
    ...historySeries,
    input_guidance: inputGuidance,
  };

  const forecastWithOriginBehavior: ForecastGuidance = {
    ...forecast,
    origin_behavior: "starts_after_last_history_observation",
  };

  it("renders exactly the existing usable form for a legacy contract without guidance", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.queryByText("Minimum observations")).not.toBeInTheDocument();
    expect(screen.queryByText("Required history anchor")).not.toBeInTheDocument();
    expect(screen.queryByText(/consecutively/)).not.toBeInTheDocument();
    expect(screen.queryByText(/starts after the last valid history observation/)).not.toBeInTheDocument();
    // Existing Frequency/Forecast horizon guidance is unaffected.
    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders the minimum observation count dynamically", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeriesWithGuidance}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Minimum observations")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders the required anchor display value dynamically", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeriesWithGuidance}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Required history anchor")).toBeInTheDocument();
    expect(screen.getByText("1938-12")).toBeInTheDocument();
  });

  it("renders a consecutive-by-frequency explanation using the contract frequency, with no dataset-specific literal", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeriesWithGuidance}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/consecutively at the governed Monthly frequency/)).toBeInTheDocument();
  });

  it("renders the after-last-observation forecast origin explanation when declared", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecastWithOriginBehavior}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("The forecast starts after the last valid history observation.")).toBeInTheDocument();
  });

  it("does not render the forecast origin explanation when origin_behavior is absent", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.queryByText(/starts after the last valid history observation/)).not.toBeInTheDocument();
  });

  it("still renders exactly one initial row and never auto-inserts/sorts/gap-fills when guidance is present", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeriesWithGuidance}
        forecast={forecastWithOriginBehavior}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    expect(screen.getAllByLabelText("Period")).toHaveLength(1);
    expect(onRowsChange).toHaveBeenLastCalledWith([{ timeIndexValue: "", targetValue: "" }]);
  });

  it("never renders a local minimum-count/anchor validation control -- guidance is display-only", () => {
    render(
      <HistorySeriesInput
        historySeries={historySeriesWithGuidance}
        forecast={forecastWithOriginBehavior}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    // Exactly two inputs exist for the single initial row -- time index and
    // target -- guidance never adds an editable/validating control.
    expect(document.querySelectorAll("input")).toHaveLength(2);
  });
});

// Project Spec S0268: contract-driven guided month-range builder, active
// only for a coherent S0267 month profile. Exercised independently of the
// S0250/S0266 coverage above, which must remain unaffected -- a legacy
// contract without temporal_interaction (or one with an
// unsupported/incoherent profile) keeps the exact historical free-form row
// UX.
describe("HistorySeriesInput guided month-range builder (Project Spec S0268)", () => {
  const temporalInteraction: HistoryTemporalInteraction = {
    control_kind: "month",
    required_anchor: { value: "1938-12", inclusion: "required" },
    sequence: { step_kind: "calendar_month", continuity: "required" },
  };

  const guidedHistorySeries: HistorySeriesGuidance = {
    ...historySeries,
    temporal_interaction: temporalInteraction,
  };

  const forecastWithOrigin: ForecastGuidance = {
    forecast_horizon: 3,
    horizon_user_editable: false,
    origin_behavior: "starts_after_last_history_observation",
  };

  it("keeps a legacy contract without temporal_interaction on the historical free-form row UX", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={historySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
    expect(screen.queryByLabelText("History from")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("History through")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add previous observation" })).not.toBeInTheDocument();
    expect(onRowsChange).toHaveBeenLastCalledWith([{ timeIndexValue: "", targetValue: "" }]);
  });

  it("activates guided mode and initializes exactly at the machine anchor with an empty target", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    expect(screen.queryByRole("button", { name: "Add row" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove row" })).not.toBeInTheDocument();
    expect((screen.getByLabelText("History from") as HTMLInputElement).value).toBe("1938-12");
    expect((screen.getByLabelText("History through") as HTMLInputElement).value).toBe("1938-12");
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(1);
    expect(onRowsChange).toHaveBeenLastCalledWith([{ timeIndexValue: "1938-12", targetValue: "" }]);
  });

  it("renders History from and History through as native month inputs with no fabricated global min/max, and rejects a move past the anchor", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    const historyFrom = screen.getByLabelText("History from") as HTMLInputElement;
    const historyThrough = screen.getByLabelText("History through") as HTMLInputElement;

    expect(historyFrom.type).toBe("month");
    expect(historyThrough.type).toBe("month");
    expect(historyFrom.min).toBe("");
    expect(historyThrough.max).toBe("");

    fireEvent.change(historyFrom, { target: { value: "1939-01" } });
    expect(historyFrom.value).toBe("1938-12");

    fireEvent.change(historyThrough, { target: { value: "1938-11" } });
    expect(historyThrough.value).toBe("1938-12");
  });

  it("supports periods earlier than the anchor through History from", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("History from"), { target: { value: "1938-10" } });

    expect(screen.getByText("1938-10")).toBeInTheDocument();
    expect(screen.getByText("1938-11")).toBeInTheDocument();
    expect(screen.getByText("1938-12")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(3);
  });

  it("supports periods later than the anchor through History through, crossing December into January", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("History through"), { target: { value: "1939-02" } });

    expect(onRowsChange).toHaveBeenLastCalledWith([
      { timeIndexValue: "1938-12", targetValue: "" },
      { timeIndexValue: "1939-01", targetValue: "" },
      { timeIndexValue: "1939-02", targetValue: "" },
    ]);
  });

  it("Add previous observation moves the start back exactly one calendar month, crossing a year boundary", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add previous observation" }));

    expect((screen.getByLabelText("History from") as HTMLInputElement).value).toBe("1938-11");
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(2);
  });

  it("Add next observation moves the end forward exactly one calendar month, crossing a year boundary", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add next observation" }));

    expect((screen.getByLabelText("History through") as HTMLInputElement).value).toBe("1939-01");
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(2);
  });

  it("renders generated period values as read-only presentation, never an editable per-row time-index control", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add next observation" }));

    // History from, History through, and one target input per generated
    // period (two periods) -- never a third per-row input for the period
    // itself.
    expect(document.querySelectorAll("input")).toHaveLength(4);
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(2);
  });

  it("preserves existing target values for periods that remain in range and leaves newly generated periods empty", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Passengers"), { target: { value: "42.2" } });
    fireEvent.change(screen.getByLabelText("History through"), { target: { value: "1939-01" } });

    expect(onRowsChange).toHaveBeenLastCalledWith([
      { timeIndexValue: "1938-12", targetValue: "42.2" },
      { timeIndexValue: "1939-01", targetValue: "" },
    ]);
  });

  it("keeps the required anchor present after a supported range change on either boundary", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("History from"), { target: { value: "1938-09" } });
    fireEvent.change(screen.getByLabelText("History through"), { target: { value: "1939-03" } });

    expect(screen.getByText("1938-12")).toBeInTheDocument();
  });

  it("reports onRowsChange in strict chronological order after both boundaries move", () => {
    const onRowsChange = vi.fn();
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={onRowsChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("History from"), { target: { value: "1938-10" } });
    fireEvent.change(screen.getByLabelText("History through"), { target: { value: "1939-02" } });

    const lastRows = onRowsChange.mock.calls[onRowsChange.mock.calls.length - 1][0] as Array<{ timeIndexValue: string }>;
    expect(lastRows.map((row) => row.timeIndexValue)).toEqual([
      "1938-10",
      "1938-11",
      "1938-12",
      "1939-01",
      "1939-02",
    ]);
  });

  it("initializes guided mode from temporal_interaction.required_anchor.value, never input_guidance.required_anchor.display_value", () => {
    const historySeriesWithDivergingGuidance: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      input_guidance: {
        minimum_observation_count: 1,
        required_anchor: { display_value: "December 1938" },
        continuity: "consecutive_by_frequency",
      },
    };

    render(
      <HistorySeriesInput
        historySeries={historySeriesWithDivergingGuidance}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("History from") as HTMLInputElement).value).toBe("1938-12");
    expect((screen.getByLabelText("History through") as HTMLInputElement).value).toBe("1938-12");
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(1);
  });

  it("never uses input_guidance.minimum_observation_count to auto-create additional guided rows", () => {
    const historySeriesWithHighMinimum: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      input_guidance: {
        minimum_observation_count: 6,
        required_anchor: { display_value: "1938-12" },
        continuity: "consecutive_by_frequency",
      },
    };

    render(
      <HistorySeriesInput
        historySeries={historySeriesWithHighMinimum}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getAllByLabelText("Passengers")).toHaveLength(1);
  });

  it("activates guided stepping without parsing free-form frequency text", () => {
    const historySeriesWithOddFrequency: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      frequency: "Some Unusual Frequency Description",
    };

    render(
      <HistorySeriesInput
        historySeries={historySeriesWithOddFrequency}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("History from")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Passengers")).toHaveLength(1);
  });

  it("shows a bounded forecast-range preview only for the declared starts-after-last-history-observation origin behavior, updating as History through changes and crossing a year boundary", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecastWithOrigin}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Forecast range: 1939-01 → 1939-03")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("History through"), { target: { value: "1939-03" } });

    expect(screen.getByText("Forecast range: 1939-04 → 1939-06")).toBeInTheDocument();
  });

  it("omits the forecast-range preview when origin_behavior is absent", () => {
    render(
      <HistorySeriesInput
        historySeries={guidedHistorySeries}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Forecast range:/)).not.toBeInTheDocument();
  });

  it("falls back to the legacy free-form row UX for a non-calendar_period time-index field", () => {
    const timestampGuided: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      time_index_field: { ...historySeries.time_index_field, value_kind: "timestamp" },
    };

    render(
      <HistorySeriesInput
        historySeries={timestampGuided}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
  });

  it("falls back to the legacy free-form row UX for an unsupported control_kind", () => {
    const unsupportedControlKind: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      temporal_interaction: {
        ...temporalInteraction,
        control_kind: "week" as unknown as "month",
      },
    };

    render(
      <HistorySeriesInput
        historySeries={unsupportedControlKind}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
  });

  it("falls back to the legacy free-form row UX for a malformed machine anchor value", () => {
    const malformedAnchor: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      temporal_interaction: {
        ...temporalInteraction,
        required_anchor: { value: "December 1938", inclusion: "required" },
      },
    };

    render(
      <HistorySeriesInput
        historySeries={malformedAnchor}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
  });

  it("falls back to the legacy free-form row UX when sequence continuity is not required", () => {
    const incoherentSequence: HistorySeriesGuidance = {
      ...guidedHistorySeries,
      temporal_interaction: {
        ...temporalInteraction,
        sequence: { step_kind: "calendar_month", continuity: "optional" as unknown as "required" },
      },
    };

    render(
      <HistorySeriesInput
        historySeries={incoherentSequence}
        forecast={forecast}
        hintMap={emptyHintMap()}
        onRowsChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
  });
});
