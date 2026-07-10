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
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/runs")) {
      return response;
    }
    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function loadRuns() {
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

  it("renders tokenless private Dashboard controls before data loads", () => {
    render(<DashboardPage />);

    const controls = screen.getByLabelText("Dashboard controls");
    expect(within(controls).getByLabelText("Search runs and datasets")).toBeInTheDocument();
    expect(within(controls).getByRole("button", { name: "Load runs" })).toBeInTheDocument();
    expect(within(controls).queryByLabelText("Operator token")).not.toBeInTheDocument();
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
  });

  it("renders the runs-root-unavailable state distinctly from an empty runs list", async () => {
    installRunsFetchMock(jsonResponse({ runs_root_status: "unavailable", runs: [] }));
    render(<DashboardPage />);

    await loadRuns();

    expect(await screen.findByRole("heading", { name: "Runs root unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/distinct from an empty runs list/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No runs found" })).not.toBeInTheDocument();
  });

  it("renders the no-runs-found state when the runs root is available but empty", async () => {
    installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [] }));
    render(<DashboardPage />);

    await loadRuns();

    expect(await screen.findByRole("heading", { name: "No runs found" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Runs root unavailable" })).not.toBeInTheDocument();
  });

  it("renders exactly one run row without a Status column or outcome tag", async () => {
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

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(table).toHaveAttribute("data-filtered-run-count", "1");
    expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
    expect(within(table).queryByText("accepted")).not.toBeInTheDocument();
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

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Dataset details" });
    expect(table).toHaveAttribute("data-filtered-dataset-count", "1");
    expect(within(table).getByRole("columnheader", { name: "Slug" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Problem type" })).not.toBeInTheDocument();
    expect(within(table).queryByText(/problem type/i)).not.toBeInTheDocument();
    expect(within(table).getByRole("textbox", { name: "Synthetic Retail Forecast display name" })).toHaveValue(
      "Synthetic Retail Forecast",
    );
    expect(within(table).getByRole("textbox", { name: "Synthetic Retail Forecast slug" })).toHaveValue(
      "synthetic-retail-forecast",
    );
    expect(within(table).queryByText(/source run summ/i)).not.toBeInTheDocument();

    expect(within(table).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(table).getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(within(table).queryByRole("button", { name: "Open admin" })).not.toBeInTheDocument();
    expect(within(table).queryByText(/open admin/i)).not.toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "Promote" })).not.toBeInTheDocument();
    expect(within(table).queryByText("Safe action owner unavailable")).not.toBeInTheDocument();
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

    await loadRuns();
    await screen.findByRole("table", { name: "Run summaries" });
    fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "energy" } });

    const runsTable = screen.getByRole("table", { name: "Run summaries" });
    const datasetsTable = screen.getByRole("table", { name: "Dataset details" });
    expect(runsTable).toHaveAttribute("data-filtered-run-count", "1");
    expect(datasetsTable).toHaveAttribute("data-filtered-dataset-count", "1");
    expect(within(runsTable).queryByText("run-agnostic-001")).not.toBeInTheDocument();
    expect(within(runsTable).getByText("run-agnostic-002")).toBeInTheDocument();
    expect(
      within(datasetsTable).queryByRole("textbox", { name: "Synthetic Retail Forecast display name" }),
    ).not.toBeInTheDocument();
    expect(
      within(datasetsTable).getByRole("textbox", { name: "Synthetic Energy Usage display name" }),
    ).toHaveValue("Synthetic Energy Usage");
  });

  it("focuses and selects the search input when Ctrl+K or Cmd+K is pressed", () => {
    render(<DashboardPage />);

    const searchInput = screen.getByLabelText("Search runs and datasets") as HTMLInputElement;
    searchInput.value = "existing text";

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });

    expect(searchInput).toHaveFocus();

    searchInput.blur();
    expect(searchInput).not.toHaveFocus();

    fireEvent.keyDown(document, { key: "k", metaKey: true });

    expect(searchInput).toHaveFocus();
  });

  it("renders a decorative ⌘K keyboard hint next to the search input without changing its accessible name", () => {
    render(<DashboardPage />);

    const controls = screen.getByLabelText("Dashboard controls");
    const hint = within(controls).getByText("⌘K");

    expect(hint).toHaveAttribute("aria-hidden", "true");
    expect(within(controls).getByLabelText("Search runs and datasets")).toBeInTheDocument();
  });

  it("matches accented run and dataset text against a diacritic-insensitive query", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-café-010",
            status: "available",
            dataset_candidate: "café-forecast",
            created_at: "2026-06-03T12:00:00Z",
            trace_reference: "trace/run-cafe-010",
            validation_summary: { outcome: "accepted" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await loadRuns();
    await screen.findByRole("table", { name: "Run summaries" });
    fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "cafe" } });

    const runsTable = screen.getByRole("table", { name: "Run summaries" });
    const datasetsTable = screen.getByRole("table", { name: "Dataset details" });
    expect(runsTable).toHaveAttribute("data-filtered-run-count", "1");
    expect(datasetsTable).toHaveAttribute("data-filtered-dataset-count", "1");
    expect(within(runsTable).getByText("run-café-010")).toBeInTheDocument();
    expect(within(datasetsTable).getByRole("textbox", { name: "Café Forecast display name" })).toHaveValue(
      "Café Forecast",
    );
  });

  it("renders an enabled Promote button and an enabled Remove button for an eligible available run", async () => {
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

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(within(table).getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Promote" })).not.toBeDisabled();
    expect(within(table).getByRole("button", { name: "Remove" })).not.toBeDisabled();
  });

  it("disables the Promote button for an available run whose validation outcome is not accepted", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-rejected",
            status: "available",
            dataset_candidate: "synthetic-retail-forecast",
            created_at: "2026-06-01T12:00:00Z",
            trace_reference: "trace/run-agnostic-rejected",
            validation_summary: { outcome: "rejected", reason: "metrics artifact missing" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(within(table).getByRole("button", { name: "Promote" })).toBeDisabled();
    expect(within(table).getByRole("button", { name: "Remove" })).not.toBeDisabled();
  });

  it("disables the Remove button for a run that is not in the available status", async () => {
    installRunsFetchMock(
      jsonResponse({
        runs_root_status: "available",
        runs: [
          {
            schema_version: "admin-run-summary.v1",
            run_id: "run-agnostic-invalid",
            status: "invalid",
            dataset_candidate: null,
            created_at: null,
            trace_reference: null,
            validation_summary: null,
            invalid_reason: "source_run_evidence_malformed",
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(within(table).getByRole("button", { name: "Remove" })).toBeDisabled();
  });

  it("does not trigger any network request or state change when a disabled Promote, Remove, or Save button is clicked", async () => {
    const fetchMock = installRunsFetchMock(
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
            validation_summary: { outcome: "rejected", reason: "metrics artifact missing" },
          },
        ],
      }),
    );
    render(<DashboardPage />);

    await loadRuns();

    const runsTable = await screen.findByRole("table", { name: "Run summaries" });
    const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
    const callCountAfterLoad = fetchMock.mock.calls.length;

    fireEvent.click(within(runsTable).getByRole("button", { name: "Promote" }));
    fireEvent.click(within(datasetTable).getByRole("button", { name: "Save" }));
    fireEvent.click(within(datasetTable).getByRole("button", { name: "Remove" }));

    expect(fetchMock).toHaveBeenCalledTimes(callCountAfterLoad);
    expect(within(runsTable).getByRole("button", { name: "Promote" })).toBeDisabled();
    expect(within(datasetTable).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(datasetTable).getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(within(datasetTable).queryByRole("button", { name: "Open admin" })).not.toBeInTheDocument();
    expect(datasetTable).toHaveAttribute("data-filtered-dataset-count", "1");
  });

  describe("Runs row removal", () => {
    function installSoleRunFetchMock() {
      return installRunsFetchMock(
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
    }

    async function openRunRemovalModal() {
      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Remove" }));
      return screen.findByRole("dialog", { name: /Remove run run-agnostic-solo\?/ });
    }

    it("opens an English confirmation modal identifying the run id when Remove is clicked", async () => {
      installSoleRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const dialog = await openRunRemovalModal();

      expect(within(dialog).getByText(/removes the publisher validation run record/i)).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: "Remove run" })).toBeInTheDocument();
    });

    it("performs no backend call and leaves the row unchanged when the modal is canceled", async () => {
      const fetchMock = installSoleRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();
      const callCountAfterLoad = fetchMock.mock.calls.length;

      const dialog = await openRunRemovalModal();
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(callCountAfterLoad);
      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
    });

    it("removes the row from the Dashboard after a successful confirmed removal", async () => {
      const fetchMock = installSoleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo") && init?.method === "DELETE") {
          return jsonResponse({ run_id: "run-agnostic-solo", removed: true, errors: [] });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const dialog = await openRunRemovalModal();
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove run" }));

      await screen.findByRole("heading", { name: "No runs found" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.queryByText("run-agnostic-solo")).not.toBeInTheDocument();
    });

    it("shows a sanitized English error and keeps the row visible when removal fails", async () => {
      const fetchMock = installSoleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo") && init?.method === "DELETE") {
          return jsonResponse({ error_type: "admin_run_removal_failed", message: "The run could not be removed." }, 422);
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const dialog = await openRunRemovalModal();
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove run" }));

      expect(await within(dialog).findByRole("heading", { name: "Run removal failed" })).toBeInTheDocument();
      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
    });
  });

  describe("Runs row promotion", () => {
    function installSoleEligibleRunFetchMock() {
      return installRunsFetchMock(
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
    }

    it("shows a loading label and disables the button while a promotion is in flight", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      let resolvePromote: (response: ReturnType<typeof jsonResponse>) => void = () => {};
      fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return new Promise((resolve) => {
            resolvePromote = resolve;
          });
        }
        if (url.endsWith("/admin/runs")) {
          return Promise.resolve(
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
        }
        return Promise.resolve(jsonResponse({}, 404));
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      expect(await within(table).findByRole("button", { name: "Promoting..." })).toBeDisabled();

      resolvePromote(
        jsonResponse({
          run_id: "run-agnostic-solo",
          promoted: true,
          dataset_slug: "synthetic-retail-forecast",
          release_id: "release-20260701-001",
          registry_action: "updated",
          errors: [],
        }),
      );

      await screen.findByRole("button", { name: "Promote" });
    });

    it("calls the owned promote endpoint and refreshes both the run summaries and the safe dataset listing after a successful promotion", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "synthetic-retail-forecast",
            release_id: "release-20260701-001",
            registry_action: "updated",
            errors: [],
          });
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: "synthetic-retail-forecast",
                title: "Synthetic Retail Forecast",
                display_title: "Synthetic Retail Forecast",
              },
            ],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();
      const callCountAfterLoad = fetchMock.mock.calls.length;

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent("synthetic-retail-forecast");
      expect(status).toHaveTextContent("release-20260701-001");
      expect(status).toHaveTextContent(/updated the existing registry entry/i);

      await screen.findByRole("button", { name: "Promote" });

      expect(fetchMock.mock.calls.length).toBe(callCountAfterLoad + 3);
      expect(fetchMock.mock.calls[callCountAfterLoad][0]).toContain("/admin/runs/run-agnostic-solo/promote");
      expect(fetchMock.mock.calls[callCountAfterLoad + 1][0]).toContain("/admin/runs");
      expect(fetchMock.mock.calls[callCountAfterLoad + 2][0]).toContain("/datasets");
      expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();

      // The success status must survive the subsequent run-summary refresh.
      expect(within(table).getByRole("status")).toHaveTextContent(/updated the existing registry entry/i);
    });

    it("renders a visible and accessible success status distinguishing a newly created registry entry", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "synthetic-retail-forecast",
            release_id: "release-20260701-002",
            registry_action: "created",
            errors: [],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent("synthetic-retail-forecast");
      expect(status).toHaveTextContent("release-20260701-002");
      expect(status).toHaveTextContent(/created a new registry entry/i);
    });

    it("shows a sanitized English error and keeps the run promotable when promotion fails", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse(
            {
              error_type: "admin_run_promotion_failed",
              error_code: "ADMIN_RUN_PROMOTION_FAILED",
              message: "The run could not be promoted.",
              errors: [
                {
                  code: "PROMOTION_NOT_ALLOWED",
                  field: "promotion_gate.promotion_allowed",
                  message: "This run is not eligible for promotion.",
                },
              ],
            },
            422,
          );
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      expect(await within(table).findByText("This run is not eligible for promotion.")).toBeInTheDocument();
      expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
      expect(within(table).getByRole("button", { name: "Promote" })).not.toBeDisabled();
    });

    it("does not render a promotion mode selector or offer Update existing Dataset Detail as an option", async () => {
      installSoleEligibleRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(
        within(table).queryByRole("combobox", { name: "run-agnostic-solo promotion mode" }),
      ).not.toBeInTheDocument();
      expect(within(table).queryByRole("combobox")).not.toBeInTheDocument();
      expect(screen.queryByText("Update existing Dataset Detail")).not.toBeInTheDocument();
    });

    it("always sends create_new_dataset_detail in the Promote request body, never update_existing_or_create", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "telco-customer-churn",
            release_id: "release-20260710t101438z",
            registry_action: "created",
            public_dataset_slug: "telco-customer-churn1",
            errors: [],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();
      const callCountAfterLoad = fetchMock.mock.calls.length;

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent(/created a new registry entry/i);
      expect(status).not.toHaveTextContent(/updated the existing registry entry/i);

      const promoteCall = fetchMock.mock.calls[callCountAfterLoad];
      expect(promoteCall[0]).toContain("/admin/runs/run-agnostic-solo/promote");
      const requestInit = promoteCall[1] as RequestInit;
      const sentBody = JSON.parse(requestInit.body as string);
      expect(sentBody).toEqual({ mode: "create_new_dataset_detail" });
      expect(sentBody.mode).not.toBe("update_existing_or_create");
    });

    it("displays the final public Dataset Detail slug when it differs from the candidate slug", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "telco-customer-churn",
            release_id: "release-20260710t101438z",
            registry_action: "created",
            public_dataset_slug: "telco-customer-churn1",
            errors: [],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent("telco-customer-churn1");
    });

    it("does not repeat the public slug in the success message when it matches the candidate slug", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "synthetic-retail-forecast",
            release_id: "release-20260701-001",
            registry_action: "updated",
            public_dataset_slug: "synthetic-retail-forecast",
            errors: [],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent(/updated the existing registry entry/i);
      expect(status).not.toHaveTextContent("Public Dataset Detail slug");
    });

    it("renders a visible and accessible success status distinguishing a reused idempotent outcome", async () => {
      const fetchMock = installSoleEligibleRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-agnostic-solo/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-agnostic-solo",
            promoted: true,
            dataset_slug: "synthetic-retail-forecast",
            release_id: "release-20260701-001",
            registry_action: "reused",
            public_dataset_slug: "synthetic-retail-forecast",
            errors: [],
          });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      const status = await within(table).findByRole("status");
      expect(status).toHaveTextContent(/reused the already-promoted registry entry/i);
    });
  });

  describe("Promoted run reflection", () => {
    function installPromotedRunFetchMock() {
      return installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-already-promoted",
              status: "promoted",
              dataset_candidate: "synthetic-retail-forecast",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/run-already-promoted",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260701-001",
                dataset_slug: "synthetic-retail-forecast",
                public_dataset_slug: "synthetic-retail-forecast",
                registry_action: "reused",
              },
            },
          ],
        }),
      );
    }

    it("renders a promoted run visually distinct from an available run and disables/relabels its Promote button", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);

      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-already-promoted")).toBeInTheDocument();
      // Both the status badge and the relabeled Promote button read "Promoted".
      expect(within(table).getAllByText("Promoted")).toHaveLength(2);

      const promoteButton = within(table).getByRole("button", { name: "Promoted" });
      expect(promoteButton).toBeDisabled();
      expect(within(table).queryByRole("button", { name: "Promote" })).not.toBeInTheDocument();
    });

    it("does not trigger any network request when the disabled Promoted button is clicked", async () => {
      const fetchMock = installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const callCountAfterLoad = fetchMock.mock.calls.length;

      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      expect(fetchMock).toHaveBeenCalledTimes(callCountAfterLoad);
    });

    it("displays promoted release id and public dataset slug metadata when available", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText(/release-20260701-001/)).toBeInTheDocument();
    });

    it("does not repeat the public slug in the promoted metadata when it matches the dataset slug", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).queryByText(/Public Dataset Detail slug/)).not.toBeInTheDocument();
    });

    it("shows the final public dataset slug when it differs from the candidate dataset slug", async () => {
      installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-promoted-numbered-slug",
              status: "promoted",
              dataset_candidate: "telco-customer-churn",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/run-promoted-numbered-slug",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260710t101438z",
                dataset_slug: "telco-customer-churn",
                public_dataset_slug: "telco-customer-churn1",
                registry_action: "created",
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText(/telco-customer-churn1/)).toBeInTheDocument();
    });

    it("counts promoted runs in the Promoted runs summary card alongside available and other statuses", async () => {
      installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-available-001",
              status: "available",
              dataset_candidate: "synthetic-retail-forecast",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/run-available-001",
              validation_summary: { outcome: "accepted" },
            },
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-promoted-001",
              status: "promoted",
              dataset_candidate: "synthetic-energy-usage",
              created_at: "2026-06-02T12:00:00Z",
              trace_reference: "trace/run-promoted-001",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260702-001",
                dataset_slug: "synthetic-energy-usage",
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);

      await loadRuns();
      await screen.findByRole("table", { name: "Run summaries" });

      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
    });

    it("filters the runs table to only promoted runs when the Promoted status filter is selected", async () => {
      installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-available-002",
              status: "available",
              dataset_candidate: "synthetic-retail-forecast",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/run-available-002",
              validation_summary: { outcome: "accepted" },
            },
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-promoted-002",
              status: "promoted",
              dataset_candidate: "synthetic-energy-usage",
              created_at: "2026-06-02T12:00:00Z",
              trace_reference: "trace/run-promoted-002",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260702-001",
                dataset_slug: "synthetic-energy-usage",
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);

      await loadRuns();
      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(table).toHaveAttribute("data-filtered-run-count", "2");

      fireEvent.change(screen.getByLabelText("Run status"), { target: { value: "promoted" } });

      expect(table).toHaveAttribute("data-filtered-run-count", "1");
      expect(within(table).getByText("run-promoted-002")).toBeInTheDocument();
      expect(within(table).queryByText("run-available-002")).not.toBeInTheDocument();
    });
  });

  describe("Dataset registry reflection", () => {
    function installRunsAndRegistryFetchMock(registryResponse: MockResponse) {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/datasets")) {
          return registryResponse;
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
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
          });
        }
        return jsonResponse({}, 404);
      });

      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    it("derives the Published datasets count and Dataset Details rows from the safe dataset listing when available", async () => {
      installRunsAndRegistryFetchMock(
        jsonResponse({
          datasets: [
            {
              dataset_slug: "synthetic-retail-forecast",
              title: "Synthetic Retail Forecast",
              display_title: "Synthetic Retail Forecast",
            },
            {
              dataset_slug: "synthetic-energy-usage",
              title: "Synthetic Energy Usage",
              display_title: null,
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      expect(await screen.findByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "2");
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-registry-status", "ready");

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      expect(datasetTable).toHaveAttribute("data-filtered-dataset-count", "2");
      expect(
        within(datasetTable).getByRole("textbox", { name: "Synthetic Retail Forecast display name" }),
      ).toBeInTheDocument();
      expect(
        within(datasetTable).getByRole("textbox", { name: "Synthetic Energy Usage display name" }),
      ).toBeInTheDocument();
    });

    it("shows a non-blocking reduced state and keeps promotion feedback and run actions working when the dataset listing is unavailable", async () => {
      installRunsAndRegistryFetchMock(jsonResponse({ error_type: "registry_unavailable" }, 503));
      render(<DashboardPage />);
      await loadRuns();

      expect(await screen.findByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "0");
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-registry-status", "unavailable");
      expect(screen.getByText(/dataset registry listing unavailable/i)).toBeInTheDocument();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByRole("button", { name: "Promote" })).not.toBeDisabled();
      expect(within(table).getByRole("button", { name: "Remove" })).not.toBeDisabled();
    });

    it("treats an invalid dataset listing shape as unavailable instead of crashing the Dashboard", async () => {
      installRunsAndRegistryFetchMock(jsonResponse({ datasets: [{ title: "Missing slug" }] }));
      render(<DashboardPage />);
      await loadRuns();

      expect(await screen.findByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "0");
      expect(screen.getByText(/dataset registry listing unavailable/i)).toBeInTheDocument();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-agnostic-solo")).toBeInTheDocument();
    });
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

    await loadRuns();

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

  it("filters the runs table by Run status when a specific status is selected", async () => {
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
        ],
      }),
    );
    render(<DashboardPage />);

    await loadRuns();

    const table = await screen.findByRole("table", { name: "Run summaries" });
    expect(table).toHaveAttribute("data-filtered-run-count", "2");

    fireEvent.change(screen.getByLabelText("Run status"), { target: { value: "invalid" } });

    expect(table).toHaveAttribute("data-filtered-run-count", "1");
    expect(within(table).queryByText("run-agnostic-001")).not.toBeInTheDocument();
    expect(within(table).getByText("run-agnostic-002")).toBeInTheDocument();
  });
});
