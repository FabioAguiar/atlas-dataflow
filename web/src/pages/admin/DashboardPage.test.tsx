import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { presentDatasetOperationalTimestamp } from "../../lib/datasetPresentation";
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

// Project Spec S0053: the Dashboard now loads its data automatically on
// mount, so this helper waits for that in-flight auto-load to settle instead
// of triggering it by clicking -- the Load runs button only functions as an
// explicit refresh trigger from this point onward (see the dedicated auto-load
// and refresh tests below for that distinction).
async function loadRuns() {
  await screen.findByRole("button", { name: "Load runs" });
}

describe("DashboardPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("projects Last updated through the shared America/Recife calendar contract (Project Spec S0092)", () => {
    expect(
      presentDatasetOperationalTimestamp("2026-07-13T00:41:21Z", {
        locale: "en-US",
        timeZone: "America/Recife",
      }),
    ).toEqual({
      localizedDateTime: "Jul 12, 2026, 9:41 PM",
      localCalendarDate: "2026-07-12",
    });
  });

  it("renders the design-aligned Dashboard identity before private data is loaded", () => {
    // Project Spec S0053: the Dashboard now auto-loads on mount, so a fetch
    // mock is installed even though this test only asserts on markup that is
    // always rendered regardless of load state.
    installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [] }));
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/no raw filesystem, draft, runtime, or log inspection/i)).toBeInTheDocument();
  });

  it("renders tokenless private Dashboard controls before data loads", () => {
    installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [] }));
    render(<DashboardPage />);

    const controls = screen.getByLabelText("Dashboard controls");
    expect(within(controls).getByLabelText("Search runs and datasets")).toBeInTheDocument();
    // Project Spec S0053: auto-load means the button may already read
    // "Loading..." by the time this synchronous assertion runs.
    expect(within(controls).getByRole("button", { name: /^(Load runs|Loading\.\.\.)$/ })).toBeInTheDocument();
    expect(within(controls).queryByLabelText("Operator token")).not.toBeInTheDocument();
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
  });

  it("keeps the desktop metrics strip and header controls present at the compact 1360x768 desktop viewport baseline (Project Spec S0057)", async () => {
    // jsdom has no CSS layout engine, so this cannot assert pixel-level
    // overflow -- it asserts the acceptance criterion that matters at the
    // DOM level: at the compact desktop baseline the same desktop metrics
    // strip and search controls still render (no mobile fallback markup),
    // matching how the compact-desktop CSS in App.css narrows spacing
    // without changing structure.
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    window.innerWidth = 1360;
    window.innerHeight = 768;

    try {
      installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [] }));
      render(<DashboardPage />);
      await loadRuns();

      const controls = screen.getByLabelText("Dashboard controls");
      expect(within(controls).getByLabelText("Search runs and datasets")).toBeInTheDocument();
      expect(await screen.findByLabelText("Runs available")).toBeInTheDocument();
      expect(screen.getByLabelText("Promoted runs")).toBeInTheDocument();
      expect(screen.getByLabelText("Published datasets")).toBeInTheDocument();
      expect(screen.getByLabelText("Draft datasets")).toBeInTheDocument();
    } finally {
      window.innerWidth = originalWidth;
      window.innerHeight = originalHeight;
    }
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
    expect(within(table).getByRole("columnheader", { name: "Display title" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Display name" })).not.toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Slug" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Problem type" })).not.toBeInTheDocument();
    expect(within(table).queryByText(/problem type/i)).not.toBeInTheDocument();
    expect(within(table).getByRole("textbox", { name: "Synthetic Retail Forecast display title" })).toHaveValue(
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
      within(datasetsTable).queryByRole("textbox", { name: "Synthetic Retail Forecast display title" }),
    ).not.toBeInTheDocument();
    expect(
      within(datasetsTable).getByRole("textbox", { name: "Synthetic Energy Usage display title" }),
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

  it("does not render a decorative ⌘K keyboard hint next to the search input", () => {
    render(<DashboardPage />);

    const controls = screen.getByLabelText("Dashboard controls");
    expect(within(controls).queryByText("⌘K")).not.toBeInTheDocument();
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
    expect(within(datasetsTable).getByRole("textbox", { name: "Café Forecast display title" })).toHaveValue(
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
                publication_status: "ready",
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

    it("does not render a promotion mode selector or offer an update/create Dataset Detail option, and its consequence copy describes create-new Dataset Detail semantics", async () => {
      installSoleEligibleRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(
        within(table).queryByRole("combobox", { name: "run-agnostic-solo promotion mode" }),
      ).not.toBeInTheDocument();
      expect(within(table).queryByRole("combobox")).not.toBeInTheDocument();
      expect(screen.queryByText("Update existing Dataset Detail")).not.toBeInTheDocument();
      expect(screen.queryByText("Create new Dataset Detail")).not.toBeInTheDocument();

      // Project Spec S0283: the operator-facing consequence copy (Promote
      // button title) describes create-new Dataset Detail semantics plus
      // collision-safe numeric slug allocation, and never promises a specific
      // suffix or claims uniqueness beyond what the backend returns.
      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      const consequence = promoteButton.getAttribute("title") ?? "";
      expect(consequence).toMatch(/its own Dataset Detail/i);
      expect(consequence).toMatch(/next available numeric slug/i);
      expect(consequence).toMatch(/without replacing the existing Dataset Detail/i);
      expect(consequence).not.toMatch(/rollback|rebind/i);
    });

    it("sends the generic Promote request mode-free and lets the backend apply create-new semantics", async () => {
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

      const promoteCall = fetchMock.mock.calls[callCountAfterLoad];
      expect(promoteCall[0]).toContain("/admin/runs/run-agnostic-solo/promote");
      const requestInit = promoteCall[1] as RequestInit;
      expect((requestInit.method ?? "").toUpperCase()).toBe("POST");

      // Project Spec S0283: the generic Promote request stays mode-free -- the
      // backend route is the sole create-new authority. No promotion-mode body
      // is sent at all.
      const rawBody = requestInit.body == null ? "" : String(requestInit.body);
      expect(rawBody).not.toContain("create_new_dataset_detail");
      expect(rawBody).not.toContain("update_existing_or_create");
      expect(rawBody).toBe("");
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

  describe("Admin run direct promotion and unavailable-run removal (Project Spec S0190)", () => {
    it("shows only Promote and Remove actions for a normal promotable run", async () => {
      installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-agnostic-solo",
              status: "available",
              dataset_candidate: "telco-customer-churn",
              created_at: "2026-08-11T21:44:24Z",
              trace_reference: "trace/run-agnostic-solo",
              validation_summary: { outcome: "accepted" },
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      expect(promoteButton).not.toBeDisabled();
      expect(within(table).getByRole("button", { name: "Remove" })).toBeInTheDocument();
      expect(within(table).queryByRole("button", { name: "Review readiness" })).not.toBeInTheDocument();
    });

    it("enables Remove for a run reported as unavailable", async () => {
      installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "validate-20260811t214347z",
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
      const removeButton = within(table).getByRole("button", { name: "Remove" });
      expect(removeButton).not.toBeDisabled();
      expect(removeButton).toHaveAttribute("data-run-action", "remove");
    });

    it("removes an unavailable run through the normal Admin removal flow", async () => {
      const fetchMock = installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "validate-20260811t214347z",
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
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/validate-20260811t214347z") && init?.method === "DELETE") {
          return jsonResponse({ run_id: "validate-20260811t214347z", removed: true, errors: [] });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
            runs_root_status: "available",
            runs: [
              {
                schema_version: "admin-run-summary.v1",
                run_id: "validate-20260811t214347z",
                status: "unavailable",
                dataset_candidate: null,
                created_at: null,
                trace_reference: null,
                validation_summary: null,
                unavailable_reason: "source_run_evidence_missing",
              },
            ],
          });
        }
        return jsonResponse({}, 404);
      });

      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Remove" }));
      const dialog = await screen.findByRole("dialog");
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove run" }));

      await screen.findByRole("heading", { name: "No runs found" });
      expect(screen.queryByText("validate-20260811t214347z")).not.toBeInTheDocument();
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
                registry_state: "active",
                public_dataset_slug: "synthetic-retail-forecast",
                registry_action: "reused",
                registry_bound: true,
                can_promote: false,
                can_remove: true,
                reason: "This run has already been promoted as a Dataset Detail.",
              },
            },
          ],
        }),
      );
    }

    it("renders a promoted run visually distinct from an available run and keeps its Promoted button clickable", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);

      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-already-promoted")).toBeInTheDocument();
      // Both the status badge and the relabeled Promote button read "Promoted".
      expect(within(table).getAllByText("Promoted")).toHaveLength(2);

      // Project Spec S0048: a registry-bound promoted run's Promoted action
      // remains clickable -- it is informational only, never disabled.
      const promoteButton = within(table).getByRole("button", { name: "Promoted" });
      expect(promoteButton).not.toBeDisabled();
      expect(within(table).queryByRole("button", { name: "Promote" })).not.toBeInTheDocument();
    });

    it("does not trigger any network request when the clickable Promoted button is clicked", async () => {
      const fetchMock = installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const callCountAfterLoad = fetchMock.mock.calls.length;

      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      expect(fetchMock).toHaveBeenCalledTimes(callCountAfterLoad);
      // Clicking Promoted never calls the promotion endpoint specifically.
      const promoteCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes("/promote"));
      expect(promoteCalls).toHaveLength(0);
    });

    it("does not render a persistent promoted legend below the run row", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(
        within(table).queryByText(/This run has already been promoted as a Dataset Detail\./),
      ).not.toBeInTheDocument();
    });

    it("opens an informational modal stating the run was already promoted when Promoted is clicked", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      const dialog = await screen.findByRole("dialog", { name: /promotion status/i });
      expect(
        within(dialog).getByText(/This run has already been promoted as a Dataset Detail\./),
      ).toBeInTheDocument();
    });

    it("keeps the Remove button enabled for a registry-bound promoted run", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByRole("button", { name: "Remove" })).not.toBeDisabled();
    });

    it("includes the promoted release id in the informational modal when available", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      const dialog = await screen.findByRole("dialog", { name: /promotion status/i });
      expect(within(dialog).getByText(/release-20260701-001/)).toBeInTheDocument();
    });

    it("does not repeat the public slug in the informational modal when it matches the dataset slug", async () => {
      installPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      const dialog = await screen.findByRole("dialog", { name: /promotion status/i });
      expect(within(dialog).queryByText(/Public Dataset Detail slug/)).not.toBeInTheDocument();
    });

    it("shows the final public dataset slug in the informational modal when it differs from the candidate dataset slug", async () => {
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
                registry_state: "active",
                public_dataset_slug: "telco-customer-churn1",
                registry_action: "created",
                registry_bound: true,
                can_promote: false,
                can_remove: true,
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Promoted" }));

      const dialog = await screen.findByRole("dialog", { name: /promotion status/i });
      expect(within(dialog).getByText(/telco-customer-churn1/)).toBeInTheDocument();
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
                registry_state: "missing",
                registry_bound: false,
                can_promote: true,
                can_remove: true,
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);

      await loadRuns();
      await screen.findByRole("table", { name: "Run summaries" });

      // Project Spec S0050: Runs available counts every run presented in the
      // Runs card, promoted or not -- not just runs with status "available".
      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "2");
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
    });

    it("uses the shared search instead of a Run status filter to isolate promoted runs (Project Spec S0053)", async () => {
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
                registry_state: "missing",
                registry_bound: false,
                can_promote: true,
                can_remove: true,
              },
            },
          ],
        }),
      );
      render(<DashboardPage />);

      await loadRuns();
      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(table).toHaveAttribute("data-filtered-run-count", "2");

      // No Run status select exists anymore -- isolating a run relies on the
      // shared search input instead.
      expect(screen.queryByLabelText("Run status")).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "promoted-002" } });

      expect(table).toHaveAttribute("data-filtered-run-count", "1");
      expect(within(table).getByText("run-promoted-002")).toBeInTheDocument();
      expect(within(table).queryByText("run-available-002")).not.toBeInTheDocument();
    });
  });

  describe("Registry-missing re-promotable run reflection (Project Spec S0048)", () => {
    function installOrphanedPromotedRunFetchMock() {
      return installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "run-orphaned-promotion",
              status: "promoted",
              dataset_candidate: "synthetic-retail-forecast",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/run-orphaned-promotion",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260701-001",
                dataset_slug: "synthetic-retail-forecast",
                registry_state: "missing",
                registry_bound: false,
                can_promote: true,
                can_remove: true,
                reason:
                  "The Dataset Detail associated with this run's promoted release is no longer in the registry, so this run can be promoted again.",
              },
            },
          ],
        }),
      );
    }

    it("renders a functional Promote action instead of an informational Promoted action when the Dataset Detail is no longer registry-bound", async () => {
      installOrphanedPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      expect(promoteButton).not.toBeDisabled();
      expect(within(table).queryByRole("button", { name: "Promoted" })).not.toBeInTheDocument();
    });

    it("calls the promotion endpoint when Promote is clicked for a registry-missing re-promotable run", async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/run-orphaned-promotion/promote") && init?.method === "POST") {
          return jsonResponse({
            run_id: "run-orphaned-promotion",
            promoted: true,
            dataset_slug: "synthetic-retail-forecast",
            release_id: "release-20260710t101438z",
            registry_action: "created",
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
                run_id: "run-orphaned-promotion",
                status: "promoted",
                dataset_candidate: "synthetic-retail-forecast",
                created_at: "2026-06-01T12:00:00Z",
                trace_reference: "trace/run-orphaned-promotion",
                validation_summary: { outcome: "accepted" },
                promotion_summary: {
                  promotion_outcome: "promoted",
                  release_id: "release-20260701-001",
                  dataset_slug: "synthetic-retail-forecast",
                  registry_state: "missing",
                  registry_bound: false,
                  can_promote: true,
                  can_remove: true,
                },
              },
            ],
          });
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);

      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const callCountAfterLoad = fetchMock.mock.calls.length;

      fireEvent.click(within(table).getByRole("button", { name: "Promote" }));

      await screen.findByText(/reused the already-promoted registry entry|created a new registry entry/i);

      const promoteCalls = fetchMock.mock.calls
        .slice(callCountAfterLoad)
        .filter(([input]) => String(input).includes("/promote"));
      expect(promoteCalls).toHaveLength(1);
    });

    it("keeps the Remove button enabled for a registry-missing re-promotable run", async () => {
      installOrphanedPromotedRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByRole("button", { name: "Remove" })).not.toBeDisabled();
    });
  });

  describe("Registry-unapplied provisional promotion Dashboard consistency (Project Spec S0262)", () => {
    // Project Spec S0262: the Admin API now only ever projects status ==
    // "promoted" once registry activation has genuine completion evidence
    // (a live registry binding or proven historical applied evidence). A
    // release-materialized / registry-unapplied run whose registry
    // activation never completed keeps surfacing as an ordinary "available"
    // run -- production DashboardPage.tsx is unmodified by S0262 (it already
    // derives every counter/badge/action from run.status), so this suite
    // proves that existing status-driven contract stays consistent for the
    // exact run across both states.
    function runFixture(status: "available" | "promoted") {
      return status === "available"
        ? {
            schema_version: "admin-run-summary.v1" as const,
            run_id: "run-registry-unapplied",
            status: "available" as const,
            dataset_candidate: "synthetic-telco-churn",
            created_at: "2026-08-25T13:08:41Z",
            trace_reference: "trace/run-registry-unapplied",
            validation_summary: { outcome: "accepted" as const },
          }
        : {
            schema_version: "admin-run-summary.v1" as const,
            run_id: "run-registry-unapplied",
            status: "promoted" as const,
            dataset_candidate: "synthetic-telco-churn",
            created_at: "2026-08-25T13:08:41Z",
            trace_reference: "trace/run-registry-unapplied",
            validation_summary: { outcome: "accepted" as const },
            promotion_summary: {
              promotion_outcome: "promoted" as const,
              release_id: "release-20260825-001",
              dataset_slug: "synthetic-telco-churn",
              registry_state: "active" as const,
              public_dataset_slug: "synthetic-telco-churn",
              registry_action: "reused" as const,
              registry_bound: true,
              can_promote: false,
              can_remove: true,
              reason: "This run has already been promoted as a Dataset Detail.",
            },
          };
    }

    it("does not count, badge, or informationalize a retryable registry-unapplied run as promoted", async () => {
      installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [runFixture("available")] }));
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });

      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "0");
      expect(within(table).queryByText("Promoted")).not.toBeInTheDocument();

      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      expect(promoteButton).not.toBeDisabled();
    });

    it("counts, badges, and informationalizes the same run once the API projects it as registry-completed", async () => {
      installRunsFetchMock(jsonResponse({ runs_root_status: "available", runs: [runFixture("promoted")] }));
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });

      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
      // Both the status badge and the relabeled Promote button read "Promoted".
      expect(within(table).getAllByText("Promoted")).toHaveLength(2);

      const promotedButton = within(table).getByRole("button", { name: "Promoted" });
      expect(promotedButton).not.toBeDisabled();
      expect(within(table).queryByRole("button", { name: "Promote" })).not.toBeInTheDocument();
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
              display_title: "Retail Demand Display",
              publication_status: "ready",
            },
            {
              dataset_slug: "synthetic-energy-usage",
              title: "Synthetic Energy Usage",
              display_title: null,
              publication_status: "ready",
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
        within(datasetTable).getByRole("textbox", { name: "Retail Demand Display display title" }),
      ).toHaveValue("Retail Demand Display");
      expect(
        within(datasetTable).getByRole("textbox", { name: "Synthetic Energy Usage display title" }),
      ).toBeInTheDocument();
    });

    it("uses the Dataset Detail profile date instead of a historical run date for Last updated", async () => {
      installRunsAndRegistryFetchMock(
        jsonResponse({
          datasets: [
            {
              dataset_slug: "synthetic-retail-forecast",
              title: "Synthetic Retail Forecast",
              display_title: "Retail Demand Display",
              publication_status: "ready",
              last_updated: "2026-07-13",
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(datasetTable).getByText(/Jul 13, 2026/)).toBeInTheDocument();
      expect(within(datasetTable).queryByText(/Jun 1, 2026/)).not.toBeInTheDocument();
    });

    it("shows Needs review (yellow) and Ready (green) status labels and derives the Published/Draft counts from them (Project Spec S0052)", async () => {
      installRunsAndRegistryFetchMock(
        jsonResponse({
          datasets: [
            {
              dataset_slug: "synthetic-retail-forecast",
              title: "Synthetic Retail Forecast",
              display_title: "Synthetic Retail Forecast",
              publication_status: "ready",
            },
            {
              dataset_slug: "synthetic-energy-usage",
              title: "Synthetic Energy Usage",
              display_title: null,
              publication_status: "needs_review",
            },
          ],
        }),
      );
      render(<DashboardPage />);
      await loadRuns();

      expect(await screen.findByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "1");
      expect(await screen.findByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "1");

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      const readyRow = within(datasetTable)
        .getByRole("textbox", { name: "Synthetic Retail Forecast display title" })
        .closest('[data-dataset-publication-status]');
      const draftRow = within(datasetTable)
        .getByRole("textbox", { name: "Synthetic Energy Usage display title" })
        .closest('[data-dataset-publication-status]');

      expect(readyRow).toHaveAttribute("data-dataset-publication-status", "ready");
      expect(draftRow).toHaveAttribute("data-dataset-publication-status", "needs_review");

      const readyPill = within(readyRow as HTMLElement).getByText("Ready");
      const draftPill = within(draftRow as HTMLElement).getByText("Needs review");
      expect(readyPill).toHaveClass("atlas-status-pill--success");
      expect(draftPill).toHaveClass("atlas-status-pill--warning");
      // Distinct status treatments: Ready and Needs review must never share a tone class.
      expect(readyPill.className).not.toBe(draftPill.className);
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

  describe("Dataset Detail safe removal lifecycle (Project Spec S0049)", () => {
    function installDatasetRemovalFetchMock(options: {
      initialDatasets: Array<{ dataset_slug: string; title: string; display_title?: string | null; publication_status: "needs_review" | "ready" }>;
      deleteResponse: MockResponse;
      datasetsAfterRemoval?: Array<{ dataset_slug: string; title: string; display_title?: string | null; publication_status: "needs_review" | "ready" }>;
    }) {
      let datasets = options.initialDatasets;
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (/\/admin\/datasets\/[^/]+$/.test(url) && init?.method === "DELETE") {
          if (options.deleteResponse.ok && options.datasetsAfterRemoval) {
            datasets = options.datasetsAfterRemoval;
          }
          return options.deleteResponse;
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({ datasets });
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

    it("disables Dataset Detail Remove for run-derived placeholder rows when the registry listing is unavailable", async () => {
      installDatasetRemovalFetchMock({
        initialDatasets: [],
        deleteResponse: jsonResponse({}),
      }).mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/datasets")) {
          return jsonResponse({ error_type: "registry_unavailable" }, 503);
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

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(datasetTable).getByRole("button", { name: "Remove" })).toBeDisabled();
    });

    it("enables Remove for a registry-backed Dataset Detail row", async () => {
      installDatasetRemovalFetchMock({
        initialDatasets: [
          { dataset_slug: "synthetic-retail-forecast", title: "Synthetic Retail Forecast", display_title: "Synthetic Retail Forecast", publication_status: "ready" },
        ],
        deleteResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(datasetTable).getByRole("button", { name: "Remove" })).not.toBeDisabled();
    });

    it("uses copy that distinguishes Dataset Detail removal from run removal and requires explicit confirmation", async () => {
      installDatasetRemovalFetchMock({
        initialDatasets: [
          { dataset_slug: "synthetic-retail-forecast", title: "Synthetic Retail Forecast", display_title: "Synthetic Retail Forecast", publication_status: "ready" },
        ],
        deleteResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      fireEvent.click(within(datasetTable).getByRole("button", { name: "Remove" }));

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getAllByText(/synthetic-retail-forecast/i).length).toBeGreaterThan(0);
      expect(within(dialog).getByText(/active registry and public listing only/i)).toBeInTheDocument();
      expect(within(dialog).getByText(/preserved/i)).toBeInTheDocument();
      expect(within(dialog).queryByText(/publisher validation run record/i)).not.toBeInTheDocument();
    });

    it("calls the owned Dataset Detail removal route only after confirmation and refreshes the registry listing afterward", async () => {
      const fetchMock = installDatasetRemovalFetchMock({
        initialDatasets: [
          { dataset_slug: "synthetic-retail-forecast", title: "Synthetic Retail Forecast", display_title: "Synthetic Retail Forecast", publication_status: "ready" },
        ],
        deleteResponse: jsonResponse({
          dataset_slug: "synthetic-retail-forecast",
          removed: true,
          previous_active_release: "release-20260701-001",
          errors: [],
        }),
        datasetsAfterRemoval: [],
      });

      render(<DashboardPage />);
      await loadRuns();

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      fireEvent.click(within(datasetTable).getByRole("button", { name: "Remove" }));

      const dialog = await screen.findByRole("dialog");

      function deleteCalls() {
        return fetchMock.mock.calls.filter(
          ([input, init]) =>
            /\/admin\/datasets\/synthetic-retail-forecast$/.test(String(input)) &&
            (init as RequestInit | undefined)?.method === "DELETE",
        );
      }

      // Opening the confirmation must never call the removal route by itself.
      expect(deleteCalls()).toHaveLength(0);

      fireEvent.click(within(dialog).getByRole("button", { name: "Remove Dataset Detail" }));

      await screen.findByRole("heading", { name: "Dataset Details unavailable" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(deleteCalls()).toHaveLength(1);

      const datasetsCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/datasets"));
      // Initial load plus a post-removal refresh.
      expect(datasetsCalls.length).toBeGreaterThanOrEqual(2);
    });

    it("shows an accessible error and keeps the confirmation open when Dataset Detail removal fails", async () => {
      installDatasetRemovalFetchMock({
        initialDatasets: [
          { dataset_slug: "synthetic-retail-forecast", title: "Synthetic Retail Forecast", display_title: "Synthetic Retail Forecast", publication_status: "ready" },
        ],
        deleteResponse: jsonResponse({ error_code: "ADMIN_DATASET_DETAIL_REMOVAL_FAILED", errors: [] }, 422),
      });

      render(<DashboardPage />);
      await loadRuns();

      const datasetTable = await screen.findByRole("table", { name: "Dataset details" });
      fireEvent.click(within(datasetTable).getByRole("button", { name: "Remove" }));

      const dialog = await screen.findByRole("dialog");
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove Dataset Detail" }));

      expect(await within(dialog).findByRole("alert")).toHaveTextContent(/could not be removed/i);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  describe("Dataset Detail slug editing and validation lifecycle (Project Spec S0051)", () => {
    function installDatasetSlugFetchMock(options: {
      initialDatasets: Array<{ dataset_slug: string; title: string; display_title?: string | null; publication_status: "needs_review" | "ready" }>;
      putResponse: MockResponse;
      datasetsAfterSave?: Array<{ dataset_slug: string; title: string; display_title?: string | null; publication_status: "needs_review" | "ready" }>;
    }) {
      let datasets = options.initialDatasets;
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (/\/admin\/datasets\/[^/]+\/slug$/.test(url) && init?.method === "PUT") {
          if (options.putResponse.ok && options.datasetsAfterSave) {
            datasets = options.datasetsAfterSave;
          }
          return options.putResponse;
        }
        if (url.endsWith("/datasets")) {
          return jsonResponse({ datasets });
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

    const TELCO_DATASET = { dataset_slug: "telco-customer-churn", title: "Telco Customer Churn", display_title: "Telco Customer Churn", publication_status: "ready" as const };
    const BANK_DATASET = { dataset_slug: "bank-marketing", title: "Bank Marketing", display_title: "Bank Marketing", publication_status: "ready" as const };

    function rowFor(input: HTMLElement) {
      return within(input.closest('[role="row"]') as HTMLElement);
    }

    it("keeps only the slug input editable for a registry-backed Dataset Detail row", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(table).getByRole("textbox", { name: "Telco Customer Churn display title" })).toBeDisabled();
      expect(within(table).getByRole("textbox", { name: "Telco Customer Churn slug" })).not.toBeDisabled();
    });

    it("keeps the slug input disabled for a run-derived placeholder row", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [],
        putResponse: jsonResponse({}),
      }).mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/datasets")) {
          return jsonResponse({ error_type: "registry_unavailable" }, 503);
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

      const table = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(table).getByRole("textbox", { name: "Synthetic Retail Forecast slug" })).toBeDisabled();
    });

    it("keeps Save disabled while the slug is unchanged", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      expect(within(table).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("keeps Save disabled and flags an invalid slug", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "Not A Valid Slug!" } });

      expect(slugInput).toHaveValue("Not A Valid Slug!");
      expect(slugInput).toHaveAttribute("aria-invalid", "true");
      expect(within(table).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("reverts an edit that would duplicate another Dataset Detail's slug and keeps Save disabled", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET, BANK_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "bank-marketing" } });

      // The exact-duplicate edit is reverted, not committed.
      expect(slugInput).toHaveValue("telco-customer-churn");
      expect(rowFor(slugInput).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("enables Save for a valid, changed, non-duplicate slug", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "telco-churn-renamed" } });

      expect(within(table).getByRole("button", { name: "Save" })).not.toBeDisabled();
    });

    it("sends only the slug rename intent and refreshes Dataset Details after a successful save", async () => {
      const fetchMock = installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({
          dataset_slug: "telco-customer-churn",
          new_dataset_slug: "telco-churn-renamed",
          renamed: true,
          errors: [],
        }),
        datasetsAfterSave: [
          { dataset_slug: "telco-churn-renamed", title: "Telco Customer Churn", display_title: "Telco Customer Churn", publication_status: "ready" as const },
        ],
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "telco-churn-renamed" } });
      fireEvent.click(within(table).getByRole("button", { name: "Save" }));

      await screen.findByDisplayValue("telco-churn-renamed");

      const putCalls = fetchMock.mock.calls.filter(
        ([input, init]) =>
          /\/admin\/datasets\/telco-customer-churn\/slug$/.test(String(input)) &&
          (init as RequestInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      const [, putInit] = putCalls[0];
      expect(JSON.parse(String((putInit as RequestInit).body))).toEqual({ new_dataset_slug: "telco-churn-renamed" });

      const datasetsCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/datasets"));
      // Initial load plus a post-save refresh.
      expect(datasetsCalls.length).toBeGreaterThanOrEqual(2);
    });

    it("shows a duplicate-slug-specific modal when the save fails with a duplicate target", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET, BANK_DATASET],
        putResponse: jsonResponse(
          {
            dataset_slug: "telco-customer-churn",
            new_dataset_slug: "telco-churn-renamed",
            renamed: false,
            errors: [{ code: "DATASET_SLUG_ALREADY_EXISTS", field: "new_dataset_slug", message: "x" }],
          },
          422,
        ),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "telco-churn-renamed" } });
      fireEvent.click(rowFor(slugInput).getByRole("button", { name: "Save" }));

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(/already in use/i)).toBeInTheDocument();
      expect(within(dialog).getByText(/cannot use the same slug/i)).toBeInTheDocument();
    });

    it("shows invalid-slug-specific feedback when the save fails with an invalid target", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse(
          {
            dataset_slug: "telco-customer-churn",
            new_dataset_slug: "telco-churn-renamed",
            renamed: false,
            errors: [{ code: "NEW_DATASET_SLUG_INVALID", field: "new_dataset_slug", message: "x" }],
          },
          422,
        ),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const slugInput = within(table).getByRole("textbox", { name: "Telco Customer Churn slug" });
      fireEvent.change(slugInput, { target: { value: "telco-churn-renamed" } });
      fireEvent.click(within(table).getByRole("button", { name: "Save" }));

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(/is not valid/i)).toBeInTheDocument();
      expect(within(dialog).getByText(/lowercase letters, numbers/i)).toBeInTheDocument();
    });

    it("gives Save and Remove the same width in the Dataset Details card", async () => {
      installDatasetSlugFetchMock({
        initialDatasets: [TELCO_DATASET],
        putResponse: jsonResponse({}),
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Dataset details" });
      const saveButton = within(table).getByRole("button", { name: "Save" });
      const removeButton = within(table).getByRole("button", { name: "Remove" });

      expect(saveButton.style.width).not.toBe("");
      expect(saveButton.style.width).toBe(removeButton.style.width);
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

    // Project Spec S0050: Runs available counts every run presented in the
    // Runs card (available, invalid, and unavailable alike), not just runs
    // with status "available".
    expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "3");
    expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "0");
    expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "0");
    expect(screen.getByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "0");
  });

  describe("Compact metrics, search-synchronized counts, auto-load, refresh, and stacked run actions (Project Spec S0053)", () => {
    function installMixedFetchMock() {
      const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: "synthetic-retail-forecast",
                title: "Synthetic Retail Forecast",
                display_title: "Synthetic Retail Forecast",
                publication_status: "ready",
              },
              {
                dataset_slug: "synthetic-energy-usage",
                title: "Synthetic Energy Usage",
                display_title: "Synthetic Energy Usage",
                publication_status: "needs_review",
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
                status: "promoted",
                dataset_candidate: "synthetic-energy-usage",
                created_at: "2026-06-02T12:00:00Z",
                trace_reference: "trace/run-agnostic-002",
                validation_summary: { outcome: "accepted" },
                promotion_summary: {
                  promotion_outcome: "promoted",
                  release_id: "release-20260702-001",
                  dataset_slug: "synthetic-energy-usage",
                  registry_state: "missing",
                  registry_bound: false,
                  can_promote: true,
                  can_remove: true,
                },
              },
            ],
          });
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    it("loads Dashboard data automatically when the page mounts, without needing to click Load runs", async () => {
      installMixedFetchMock();
      render(<DashboardPage />);

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("run-agnostic-001")).toBeInTheDocument();
      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "2");
    });

    it("refreshes Dashboard data via Load runs after the initial auto-load, re-fetching without mutating state", async () => {
      const fetchMock = installMixedFetchMock();
      render(<DashboardPage />);

      await loadRuns();
      const callCountAfterAutoLoad = fetchMock.mock.calls.length;

      fireEvent.click(screen.getByRole("button", { name: "Load runs" }));
      // A refresh keeps the already-rendered rows mounted while the new GET
      // is in flight instead of replacing the Dashboard with a loading card.
      expect(screen.getByRole("table", { name: "Run summaries" })).toBeInTheDocument();
      expect(screen.getByText("run-agnostic-001")).toBeInTheDocument();
      await loadRuns();

      const runsCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/admin/runs"));
      expect(runsCalls.length).toBeGreaterThan(0);
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callCountAfterAutoLoad);
      // Refresh only ever issues GET requests -- never a mutating method.
      for (const call of fetchMock.mock.calls.slice(callCountAfterAutoLoad)) {
        const init = call[1] as RequestInit | undefined;
        expect(init?.method ?? "GET").toBe("GET");
      }
    });

    it("removes the Run status filter card and select entirely", async () => {
      installMixedFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      expect(screen.queryByLabelText("Run status")).not.toBeInTheDocument();
      expect(screen.queryByText("Run status")).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });

    it("renders the four metric cards as a compact horizontal strip instead of the prior stacked layout", async () => {
      installMixedFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      for (const label of ["Runs available", "Promoted runs", "Published datasets", "Draft datasets"]) {
        const card = screen.getByLabelText(label);
        expect(card.style.flexDirection).toBe("row");
        expect(card.style.padding).not.toBe("");
        expect(card.style.padding).not.toContain("var(--atlas-space-5)");
      }
    });

    it("synchronizes all four metric counts with the shared search filter, and restores them when the search is cleared", async () => {
      installMixedFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "2");
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "1");

      fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "energy" } });

      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "0");
      expect(screen.getByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "1");

      fireEvent.change(screen.getByLabelText("Search runs and datasets"), { target: { value: "" } });

      expect(screen.getByLabelText("Runs available")).toHaveAttribute("data-summary-count", "2");
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "1");
      expect(screen.getByLabelText("Draft datasets")).toHaveAttribute("data-summary-count", "1");
    });

    it("stacks Promote/Promoted above Remove in the Runs card", async () => {
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
      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      const actionsContainer = promoteButton.parentElement as HTMLElement;

      expect(actionsContainer.style.flexDirection).toBe("column");
      expect(within(actionsContainer).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    });
  });

  describe("Runs card promoted interaction and display refinement (Project Spec S0050)", () => {
    function installPromotedRemovableRunFetchMock() {
      return installRunsFetchMock(
        jsonResponse({
          runs_root_status: "available",
          runs: [
            {
              schema_version: "admin-run-summary.v1",
              run_id: "validate-20260710T191735Z",
              status: "promoted",
              dataset_candidate: "synthetic-retail-forecast",
              created_at: "2026-06-01T12:00:00Z",
              trace_reference: "trace/validate-20260710T191735Z",
              validation_summary: { outcome: "accepted" },
              promotion_summary: {
                promotion_outcome: "promoted",
                release_id: "release-20260710t191735z",
                dataset_slug: "synthetic-retail-forecast",
                registry_state: "active",
                public_dataset_slug: "synthetic-retail-forecast",
                registry_action: "reused",
                registry_bound: true,
                can_promote: false,
                can_remove: true,
                reason: "This run has already been promoted as a Dataset Detail.",
              },
            },
          ],
        }),
      );
    }

    it("displays the Run ID without the validate- prefix for a validate-{timestamp} run id", async () => {
      installPromotedRemovableRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      expect(within(table).getByText("20260710T191735Z")).toBeInTheDocument();
      expect(within(table).queryByText("validate-20260710T191735Z")).not.toBeInTheDocument();
    });

    it("shows a stronger confirmation modal distinguishing promoted-run removal from normal run removal", async () => {
      installPromotedRemovableRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Remove" }));

      const dialog = await screen.findByRole("dialog", { name: /Remove promoted run/ });
      expect(
        within(dialog).getByText(
          /does not remove the\s*Dataset Detail, release, registry entry, model artifacts, notebooks, contracts, or public\s*dataset state/i,
        ),
      ).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: "Remove promoted run" })).toBeInTheDocument();
    });

    it("confirms removal of a promoted run using the original full run id against the existing removal endpoint", async () => {
      const fetchMock = installPromotedRemovableRunFetchMock();
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs/validate-20260710T191735Z") && init?.method === "DELETE") {
          return jsonResponse({ run_id: "validate-20260710T191735Z", removed: true, errors: [] });
        }
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
            runs_root_status: "available",
            runs: [
              {
                schema_version: "admin-run-summary.v1",
                run_id: "validate-20260710T191735Z",
                status: "promoted",
                dataset_candidate: "synthetic-retail-forecast",
                created_at: "2026-06-01T12:00:00Z",
                trace_reference: "trace/validate-20260710T191735Z",
                validation_summary: { outcome: "accepted" },
                promotion_summary: {
                  promotion_outcome: "promoted",
                  release_id: "release-20260710t191735z",
                  dataset_slug: "synthetic-retail-forecast",
                  registry_state: "active",
                  public_dataset_slug: "synthetic-retail-forecast",
                  registry_action: "reused",
                  registry_bound: true,
                  can_promote: false,
                  can_remove: true,
                },
              },
            ],
          });
        }
        return jsonResponse({}, 404);
      });
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      fireEvent.click(within(table).getByRole("button", { name: "Remove" }));

      const dialog = await screen.findByRole("dialog", { name: /Remove promoted run/ });
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove promoted run" }));

      await screen.findByRole("heading", { name: "No runs found" });

      const deleteCall = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input).endsWith("/admin/runs/validate-20260710T191735Z") &&
          (init as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });

    it("gives the Promoted and Remove buttons the same width in the Runs card", async () => {
      installPromotedRemovableRunFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const promotedButton = within(table).getByRole("button", { name: "Promoted" });
      const removeButton = within(table).getByRole("button", { name: "Remove" });

      expect(promotedButton.style.width).toBe(removeButton.style.width);
    });

    it("keeps the Promote and Remove buttons aligned for a non-promoted eligible run", async () => {
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
      const promoteButton = within(table).getByRole("button", { name: "Promote" });
      const removeButton = within(table).getByRole("button", { name: "Remove" });

      expect(promoteButton.style.width).toBe(removeButton.style.width);
    });
  });

  describe("Superseded run create-new recovery (Project Spec S0283)", () => {
    const supersededRun = {
      schema_version: "admin-run-summary.v1",
      run_id: "validate-20260829T113112Z",
      status: "promoted",
      dataset_candidate: "telco-customer-churn",
      created_at: "2026-08-29T11:31:12Z",
      trace_reference: "trace/validate-20260829T113112Z",
      validation_summary: { outcome: "accepted" },
      promotion_summary: {
        promotion_outcome: "promoted",
        release_id: "release-20260829-002",
        dataset_slug: "telco-customer-churn",
        registry_state: "superseded",
        public_dataset_slug: "telco-customer-churn",
        current_active_release_id: "release-20260829-003",
        registry_bound: false,
        can_promote: true,
        can_remove: true,
        reason:
          'This run was promoted to release "release-20260829-002". That historical release is preserved; release "release-20260829-003" is currently active for "telco-customer-churn". Promote may create a new Dataset Detail for this historical release without replacing the current binding.',
      },
    };
    const activeRun = {
      schema_version: "admin-run-summary.v1",
      run_id: "validate-20260829T144328Z",
      status: "promoted",
      dataset_candidate: "telco-customer-churn",
      created_at: "2026-08-29T14:43:28Z",
      trace_reference: "trace/validate-20260829T144328Z",
      validation_summary: { outcome: "accepted" },
      promotion_summary: {
        promotion_outcome: "promoted",
        release_id: "release-20260829-003",
        dataset_slug: "telco-customer-churn",
        registry_state: "active",
        public_dataset_slug: "telco-customer-churn",
        registry_action: "reused",
        registry_bound: true,
        can_promote: false,
        can_remove: true,
      },
    };
    const missingRun = {
      schema_version: "admin-run-summary.v1",
      run_id: "validate-20260101T000000Z",
      status: "promoted",
      dataset_candidate: "retired-dataset",
      created_at: "2026-01-01T00:00:00Z",
      trace_reference: "trace/validate-20260101T000000Z",
      validation_summary: { outcome: "accepted" },
      promotion_summary: {
        promotion_outcome: "promoted",
        release_id: "release-20260101-001",
        dataset_slug: "retired-dataset",
        registry_state: "missing",
        registry_bound: false,
        can_promote: true,
        can_remove: true,
      },
    };

    function installFetchMock() {
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
            runs_root_status: "available",
            runs: [activeRun, supersededRun, missingRun],
          });
        }
        if (url.endsWith("/admin/datasets")) {
          return jsonResponse({
            datasets: [
              {
                dataset_slug: "telco-customer-churn",
                title: "Telco Customer Churn",
                publication_status: "ready",
                last_updated: "2026-08-29T14:43:28Z",
              },
            ],
          });
        }
        if (init?.method === "POST" && url.includes("/promote")) {
          return jsonResponse({ run_id: "x", promoted: true, dataset_slug: null, release_id: null, registry_action: null, public_dataset_slug: null, errors: [] });
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    function supersededRowActionButton(table: HTMLElement): HTMLElement {
      const rows = within(table).getAllByRole("row");
      const row = rows.find((candidate) => within(candidate).queryByText("20260829T113112Z"));
      expect(row).toBeDefined();
      return within(row as HTMLElement).getByRole("button", { name: /Promote|Promoted|Superseded/ });
    }

    it("keeps the Superseded status visible while exposing a functional Promote action", async () => {
      installFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      // The historical Superseded status pill stays visible -- history is not hidden.
      expect(within(table).getAllByText("Superseded").length).toBeGreaterThanOrEqual(1);
      expect(within(table).queryByRole("button", { name: "Superseded" })).not.toBeInTheDocument();

      // Project Spec S0283: the superseded run's action button is a functional
      // "Promote", not an informational "Superseded" button.
      const supersededAction = supersededRowActionButton(table);
      expect(supersededAction).toHaveTextContent("Promote");
      expect(supersededAction).toHaveAttribute("data-run-action", "promote");
      expect(supersededAction).not.toBeDisabled();
      expect(supersededAction.getAttribute("title") ?? "").toMatch(/next available numeric slug/i);

      // The active Telco run keeps its informational "Promoted" action.
      expect(within(table).getByRole("button", { name: "Promoted" })).toHaveAttribute(
        "data-run-action",
        "promoted",
      );

      // No promotion-mode selector, no rollback/rebind wording anywhere.
      expect(within(table).queryByRole("combobox")).not.toBeInTheDocument();
      expect(within(table).queryByText(/rollback|rebind/i)).not.toBeInTheDocument();
    });

    it("still counts the superseded run in Promoted runs and coexists with an increased Published datasets count", async () => {
      installFetchMock();
      render(<DashboardPage />);
      await loadRuns();
      await screen.findByRole("table", { name: "Run summaries" });

      // active + superseded + missing == 3 promoted runs, unchanged by recovery.
      expect(screen.getByLabelText("Promoted runs")).toHaveAttribute("data-summary-count", "3");
      // Published datasets stays registry-backed and independent -- a recovery
      // that adds a Dataset Detail lifts this counter without touching the
      // Promoted runs count.
      expect(screen.getByLabelText("Published datasets")).toHaveAttribute("data-summary-count", "1");
    });

    it("POSTs to the generic promote endpoint exactly once when the superseded Promote action is clicked", async () => {
      const fetchMock = installFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const callsBefore = fetchMock.mock.calls.length;
      fireEvent.click(supersededRowActionButton(table));

      const promoteCalls = fetchMock.mock.calls
        .slice(callsBefore)
        .filter(([input, init]) => String(input).includes("/admin/runs/validate-20260829T113112Z/promote") && (init as RequestInit | undefined)?.method === "POST");
      expect(promoteCalls).toHaveLength(1);
      const rawBody = (promoteCalls[0][1] as RequestInit).body;
      expect(rawBody == null ? "" : String(rawBody)).toBe("");

      // No informational modal is opened for a superseded run.
      expect(screen.queryByRole("dialog", { name: /promotion status/i })).not.toBeInTheDocument();
    });

    it("keeps Remove available for the superseded run", async () => {
      installFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      const rows = within(table).getAllByRole("row");
      const supersededRow = rows.find((row) => within(row).queryByText("20260829T113112Z"));
      expect(supersededRow).toBeDefined();
      expect(within(supersededRow as HTMLElement).getByRole("button", { name: "Remove" })).not.toBeDisabled();
    });

    it("keeps the missing promoted run's functional Promote action alongside the superseded one", async () => {
      installFetchMock();
      render(<DashboardPage />);
      await loadRuns();

      const table = await screen.findByRole("table", { name: "Run summaries" });
      // Both the superseded and missing runs expose a functional Promote.
      const promoteButtons = within(table).getAllByRole("button", { name: "Promote" });
      expect(promoteButtons).toHaveLength(2);
      for (const button of promoteButtons) {
        expect(button).toHaveAttribute("data-run-action", "promote");
        expect(button).not.toBeDisabled();
      }
    });

    it("rejects a superseded payload with can_promote=false rather than rendering an unsafe action", async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/runs")) {
          return jsonResponse({
            runs_root_status: "available",
            runs: [
              {
                ...supersededRun,
                promotion_summary: { ...supersededRun.promotion_summary, can_promote: false },
              },
            ],
          });
        }
        return jsonResponse({}, 404);
      });
      vi.stubGlobal("fetch", fetchMock);
      render(<DashboardPage />);
      await loadRuns();

      expect(await screen.findByRole("alert", { name: "Invalid run summary response" })).toBeInTheDocument();
    });
  });
});
