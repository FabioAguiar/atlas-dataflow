import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "./DashboardPage";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

function jsonResponse(body: unknown, status = 200): MockResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function installRunsFetchMock(response: MockResponse) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/admin/runs")) {
      return response;
    }
    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function enterTokenAndLoadRuns() {
  fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "run-agnostic-operator-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
}

describe("DashboardPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the design-aligned Dashboard identity before private data is loaded", () => {
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/no raw filesystem, draft, runtime, or log inspection/i)).toBeInTheDocument();
  });

  it("renders the header search control and the operator token control together in the header, before data loads", () => {
    render(<DashboardPage />);

    const controls = screen.getByLabelText("Dashboard controls");
    expect(within(controls).getByLabelText("Search runs and datasets")).toBeInTheDocument();
    expect(within(controls).getByLabelText("Operator token")).toBeInTheDocument();
    expect(within(controls).getByRole("button", { name: "Load runs" })).toBeInTheDocument();
  });

  it("renders the runs-root-unavailable state distinctly from an empty runs list", async () => {
    installRunsFetchMock(jsonResponse({ runs_root_status: "unavailable", runs: [] }));
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();

    expect(await screen.findByRole("heading", { name: "Runs root unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/distinct from an empty runs list/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No runs found" })).not.toBeInTheDocument();
  });

  it("renders the no-runs-found state when the runs root is available but empty", async () => {
    installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [] }));
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();

    expect(await screen.findByRole("heading", { name: "No runs found" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Runs root unavailable" })).not.toBeInTheDocument();
  });

  it("renders exactly one run row with its status pill", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-solo",
            status: "available",
            dataset_candidate: "synthetic-retail-forecast",
            created_at: "2026-06-01T12:00:00Z",
            trace_reference: "trace/run-agnostic-solo",
            validation_summary: { outcome: "accepted" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(table).toHaveAttribute("data-filtered-run-count", "1");
    expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
    expect(within(table).getByText("Available")).toBeInTheDocument();
  });

  it("renders Dataset Details from safe run-summary data with unavailable actions", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-solo",
            status: "available",
            dataset_candidate: "synthetic-retail-forecast",
            created_at: "2026-06-01T12:00:00Z",
            trace_reference: "trace/run-agnostic-solo",
            validation_summary: { outcome: "accepted" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();

    const table = await screen.findByRole("table", { name: "Dataset details" });
    expect(table).toHaveAttribute("data-filtered-dataset-count", "1");
    expect(within(table).getByText("Synthetic Retail Forecast")).toBeInTheDocument();
    expect(within(table).getByText("Pending safe profile source")).toBeInTheDocument();

    expect(within(table).getByRole("button", { name: "Promote" })).toBeDisabled();
    expect(within(table).getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(within(table).getByRole("button", { name: "Open admin" })).toBeDisabled();
    expect(within(table).getByText("Safe action owner unavailable")).toBeInTheDocument();
  });

  it("filters runs and Dataset Details from the shared Dashboard search", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-001",
            status: "available",
            dataset_candidate: "synthetic-retail-forecast",
            created_at: "2026-06-01T12:00:00Z",
            trace_reference: "trace/run-agnostic-001",
            validation_summary: { outcome: "accepted" },
          },
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-002",
            status: "available",
            dataset_candidate: "synthetic-energy-usage",
            created_at: "2026-06-02T12:00:00Z",
            trace_reference: "trace/run-agnostic-002",
            validation_summary: { outcome: "accepted" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();
    fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "energy" } });

    const runsTable = screen.getByRole("table", { name: "Run summaries" });
    const datasetsTable = screen.getByRole("table", { name: "Dataset details" });
    expect(runsTable).toHaveAttribute("data-filtered-run-count", "1");
    expect(datasetsTable).toHaveAttribute("data-filtered-dataset-count", "1");
    expect(within(runsTable).queryByText("run-agnostic-001")).not.toBeInTheDocument();
    expect(within(runsTable).getByText("run-agnostic-002")).toBeInTheDocument();
    expect(within(datasetsTable).queryByText("Synthetic Retail Forecast")).not.toBeInTheDocument();
    expect(within(datasetsTable).getByText("Synthetic Energy Usage")).toBeInTheDocument();
  });

  it("renders multiple runs with mixed statuses and no hardcoded upper bound on the counters", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-001",
            status: "available",
            dataset_candidate: "synthetic-retail-forecast",
            created_at: "2026-06-01T12:00:00Z",
            trace_reference: "trace/run-agnostic-001",
            validation_summary: { outcome: "accepted" },
          },
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-002",
            status: "invalid",
            dataset_candidate: "synthetic-energy-usage",
            created_at: "2026-06-02T12:00:00Z",
            trace_reference: "trace/run-agnostic-002",
            validation_summary: null,
            invalid_reason: "source_run_evidence_malformed",
          },
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-003",
            status: "unavailable",
            dataset_candidate: null,
            created_at: null,
            trace_reference: null,
            validation_summary: null,
            unavailable_reason: "source_run_evidence_missing",
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await enterTokenAndLoadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(table).toHaveAttribute("data-filtered-run-count", "3");
    expect(within(table).getByText("run-agnostic-001")).toBeInTheDocument();
    expect(within(table).getByText("run-agnostic-002")).toBeInTheDocument();
    expect(within(table).getByText("run-agnostic-003")).toBeInTheDocument();

    expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "1");
    expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "0");
    expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "0");
    expect(screen.getByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "0");
  });
});
