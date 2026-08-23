import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HistorySeriesInput, {
  type ForecastGuidance,
  type HistorySeriesGuidance,
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
