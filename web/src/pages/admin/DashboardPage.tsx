import { FormEvent, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, StatusPill, TableRow } from "../../components/ui";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type RunStatus = "available" | "unavailable" | "invalid";
type RunsRootStatus = "available" | "unavailable";
type ValidationOutcome = "accepted" | "rejected" | "failed" | "unknown";
type FilterStatus = "all" | RunStatus;

type AdminRunSummary = {
  schema_version: "admin-run-summary.v1";
  run_id: string;
  status: RunStatus;
  dataset_candidate: string | null;
  created_at: string | null;
  trace_reference: string | null;
  validation_summary: { outcome: ValidationOutcome; reason?: string } | null;
  unavailable_reason?: "source_run_evidence_missing" | "source_run_evidence_unreadable";
  invalid_reason?: "source_run_evidence_malformed" | "source_run_evidence_incomplete" | "source_run_evidence_schema_invalid";
};

type AdminRunsResponse = {
  runs_root_status: RunsRootStatus;
  runs: AdminRunSummary[];
};

type DashboardState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: AdminRunsResponse }
  | { status: "unavailable"; message: string }
  | { status: "invalid"; message: string }
  | { status: "error"; message: string };

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-6)",
};

const headerStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "end",
  justifyContent: "space-between",
  gap: "var(--atlas-space-5)",
};

const controlPanelStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
};

const formStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-3)",
  alignItems: "end",
};

const fieldStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const labelStyle: CSSProperties = {
  color: "var(--atlas-color-text)",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 800,
};

const inputStyle: CSSProperties = {
  minHeight: "2.5rem",
  minWidth: "min(18rem, 100%)",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  background: "var(--atlas-color-surface)",
};

const filterBarStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-3)",
};

const statusGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))",
  gap: "var(--atlas-space-4)",
};

const counterValueStyle: CSSProperties = {
  color: "var(--atlas-color-text)",
  fontSize: "var(--atlas-text-2xl)",
  lineHeight: "var(--atlas-line-tight)",
};

const tableStyle: CSSProperties = {
  display: "grid",
  gap: 0,
};

const tableHeaderStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.1fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(11rem, 0.85fr)",
  gap: "var(--atlas-space-4)",
  borderBottom: "1px solid var(--atlas-color-border-strong)",
  paddingBottom: "var(--atlas-space-3)",
  color: "var(--atlas-color-text-subtle)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  textTransform: "uppercase",
};

const rowContentStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.1fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(11rem, 0.85fr)",
  gap: "var(--atlas-space-4)",
  alignItems: "center",
};

const mutedTextStyle: CSSProperties = {
  color: "var(--atlas-color-text-muted)",
};

const intentBoundaryStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  background: "var(--atlas-color-surface-muted)",
};

const promotionIntentStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const disabledIntentButtonStyle: CSSProperties = {
  cursor: "not-allowed",
  opacity: 0.75,
  width: "fit-content",
};

function isAdminRunSummary(value: unknown): value is AdminRunSummary {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<AdminRunSummary>;
  const validStatus = record.status === "available" || record.status === "unavailable" || record.status === "invalid";

  return (
    record.schema_version === "admin-run-summary.v1" &&
    typeof record.run_id === "string" &&
    record.run_id.length > 0 &&
    validStatus &&
    (typeof record.dataset_candidate === "string" || record.dataset_candidate === null) &&
    (typeof record.created_at === "string" || record.created_at === null) &&
    (typeof record.trace_reference === "string" || record.trace_reference === null) &&
    (typeof record.validation_summary === "object" || record.validation_summary === null)
  );
}

function isAdminRunsResponse(value: unknown): value is AdminRunsResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<AdminRunsResponse>;

  return (
    (record.runs_root_status === "available" || record.runs_root_status === "unavailable") &&
    Array.isArray(record.runs) &&
    record.runs.every(isAdminRunSummary)
  );
}

function statusTone(status: RunStatus): "success" | "warning" | "danger" {
  if (status === "available") {
    return "success";
  }
  if (status === "invalid") {
    return "danger";
  }
  return "warning";
}

function statusLabel(status: RunStatus): string {
  if (status === "available") {
    return "Available";
  }
  if (status === "invalid") {
    return "Invalid";
  }
  return "Unavailable";
}

function reasonLabel(run: AdminRunSummary): string | null {
  if (run.status === "invalid") {
    return run.invalid_reason?.replaceAll("_", " ") ?? "Invalid source evidence";
  }
  if (run.status === "unavailable") {
    return run.unavailable_reason?.replaceAll("_", " ") ?? "Source evidence unavailable";
  }
  return run.validation_summary?.reason ?? null;
}

function formatCreatedAt(value: string | null): string {
  if (!value) {
    return "Not available";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Invalid timestamp";
  }

  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function rootStatusMessage(status: RunsRootStatus): string {
  return status === "available"
    ? "Runs root available"
    : "Runs root unavailable";
}

function promotionIntentMessage(run: AdminRunSummary): string {
  if (run.status === "available") {
    return "Future publisher and profile validation required.";
  }

  return "Resolve run evidence before future promotion review.";
}

export default function DashboardPage() {
  const [adminToken, setAdminToken] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [state, setState] = useState<DashboardState>({ status: "idle" });

  const runs = state.status === "ready" ? state.data.runs : [];

  const counters = useMemo(
    () => ({
      total: runs.length,
      available: runs.filter((run) => run.status === "available").length,
      invalid: runs.filter((run) => run.status === "invalid").length,
      unavailable: runs.filter((run) => run.status === "unavailable").length,
    }),
    [runs],
  );

  const filteredRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return runs.filter((run) => {
      const matchesStatus = statusFilter === "all" || run.status === statusFilter;
      const matchesQuery =
        normalizedQuery.length === 0 ||
        run.run_id.toLowerCase().includes(normalizedQuery) ||
        (run.dataset_candidate ?? "").toLowerCase().includes(normalizedQuery) ||
        (run.validation_summary?.outcome ?? "").toLowerCase().includes(normalizedQuery);

      return matchesStatus && matchesQuery;
    });
  }, [query, runs, statusFilter]);

  function loadRuns(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const token = adminToken.trim();
    if (!token) {
      setState({ status: "unavailable", message: "Enter the operator token to request private run summaries." });
      return;
    }

    const controller = new AbortController();
    setState({ status: "loading" });

    fetch(`${apiBaseUrl}/admin/runs`, {
      headers: { "X-Admin-Token": token },
      signal: controller.signal,
    })
      .then((res) => {
        if (res.status === 404) {
          setState({
            status: "unavailable",
            message: "Run summaries are unavailable for this session. Confirm the operator token and API configuration.",
          });
          return null;
        }

        if (!res.ok) {
          setState({ status: "error", message: "Run summaries could not be loaded from the admin API." });
          return null;
        }

        return res.json() as Promise<unknown>;
      })
      .then((data) => {
        if (!data) {
          return;
        }

        if (!isAdminRunsResponse(data)) {
          setState({ status: "invalid", message: "The admin API returned an unexpected run summary shape." });
          return;
        }

        setState({ status: "ready", data });
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error", message: "Run summaries could not be loaded. Check that the API is reachable." });
        }
      });
  }

  return (
    <section aria-labelledby="admin-dashboard-title" style={pageStyle}>
      <div style={headerStyle}>
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1 id="admin-dashboard-title">Run discovery</h1>
          <p className="summary">
            Private run summaries from the admin projection. Statuses come from the backend; no filesystem inspection is
            performed in the browser.
          </p>
        </div>

        <Card aria-label="Admin token entry" muted style={controlPanelStyle}>
          <form onSubmit={loadRuns} style={formStyle}>
            <label style={fieldStyle}>
              <span style={labelStyle}>Operator token</span>
              <input
                autoComplete="off"
                onChange={(event) => setAdminToken(event.target.value)}
                placeholder="Enter token for this session"
                style={inputStyle}
                type="password"
                value={adminToken}
              />
            </label>
            <Button disabled={state.status === "loading"} type="submit">
              {state.status === "loading" ? "Loading..." : "Load runs"}
            </Button>
          </form>
          <p style={{ ...mutedTextStyle, margin: 0 }}>
            The token is held only in page state and sent as an X-Admin-Token header.
          </p>
        </Card>
      </div>

      {state.status === "idle" && (
        <EmptyState title="Run summaries not loaded" message="Enter the operator token to request the private summary projection." />
      )}

      {state.status === "loading" && (
        <Card aria-label="Loading run summaries">
          <p style={{ margin: 0 }}>Loading run summaries...</p>
        </Card>
      )}

      {state.status === "unavailable" && <EmptyState title="Run discovery unavailable" message={state.message} />}

      {state.status === "invalid" && <ErrorState title="Invalid run summary response" message={state.message} />}

      {state.status === "error" && <ErrorState title="Run discovery error" message={state.message} />}

      {state.status === "ready" && (
        <>
          <div style={statusGridStyle}>
            <Card aria-label="Total runs">
              <Badge>{rootStatusMessage(state.data.runs_root_status)}</Badge>
              <strong style={counterValueStyle}>{counters.total}</strong>
              <span style={mutedTextStyle}>Runs returned</span>
            </Card>
            <Card aria-label="Available runs">
              <StatusPill tone="success">Available</StatusPill>
              <strong style={counterValueStyle}>{counters.available}</strong>
              <span style={mutedTextStyle}>Ready for review</span>
            </Card>
            <Card aria-label="Invalid runs">
              <StatusPill tone="danger">Invalid</StatusPill>
              <strong style={counterValueStyle}>{counters.invalid}</strong>
              <span style={mutedTextStyle}>Incomplete source evidence</span>
            </Card>
            <Card aria-label="Unavailable runs">
              <StatusPill tone="warning">Unavailable</StatusPill>
              <strong style={counterValueStyle}>{counters.unavailable}</strong>
              <span style={mutedTextStyle}>Missing or unreadable evidence</span>
            </Card>
          </div>

          {state.data.runs_root_status === "unavailable" && (
            <EmptyState
              title="Runs root unavailable"
              message="The admin API could not read the configured runs root. This is distinct from an empty runs list."
            />
          )}

          {state.data.runs_root_status === "available" && runs.length === 0 && (
            <EmptyState title="No runs found" message="The runs root is available, but no run summaries were returned." />
          )}

          {runs.length > 0 && (
            <Card aria-labelledby="admin-runs-table-title">
              <div>
                <p className="eyebrow">Runs</p>
                <h2 id="admin-runs-table-title" style={{ margin: 0 }}>
                  Safe run summaries
                </h2>
              </div>

              <div aria-label="Promotion boundary" style={intentBoundaryStyle}>
                <StatusPill tone="warning">Promotion intent disabled</StatusPill>
                <p style={{ ...mutedTextStyle, margin: 0 }}>
                  Dashboard promotion is a future workflow entry point only. It does not create drafts, release
                  candidates, publications, published snapshot visibility changes, registry updates, or release artifact
                  mutations.
                </p>
              </div>

              <div aria-label="Run filters" style={filterBarStyle}>
                <label style={fieldStyle}>
                  <span style={labelStyle}>Search</span>
                  <input
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Run ID, dataset, outcome"
                    style={inputStyle}
                    type="search"
                    value={query}
                  />
                </label>
                <label style={fieldStyle}>
                  <span style={labelStyle}>Status</span>
                  <select
                    onChange={(event) => setStatusFilter(event.target.value as FilterStatus)}
                    style={inputStyle}
                    value={statusFilter}
                  >
                    <option value="all">All statuses</option>
                    <option value="available">Available</option>
                    <option value="invalid">Invalid</option>
                    <option value="unavailable">Unavailable</option>
                  </select>
                </label>
              </div>

              {filteredRuns.length === 0 ? (
                <EmptyState title="No matching runs" message="Adjust the Dashboard filters to view returned summaries." />
              ) : (
                <div role="table" aria-label="Run summaries" style={tableStyle}>
                  <div role="row" style={tableHeaderStyle}>
                    <span role="columnheader">Run ID</span>
                    <span role="columnheader">Dataset</span>
                    <span role="columnheader">Created at</span>
                    <span role="columnheader">Status</span>
                    <span role="columnheader">Promotion intent</span>
                  </div>

                  {filteredRuns.map((run) => (
                    <TableRow
                      key={run.run_id}
                      meta={
                        <>
                          {run.validation_summary && <Badge>{run.validation_summary.outcome}</Badge>}
                          {reasonLabel(run) && <span style={mutedTextStyle}>{reasonLabel(run)}</span>}
                        </>
                      }
                    >
                      <div style={rowContentStyle}>
                        <strong>{run.run_id}</strong>
                        <span>{run.dataset_candidate ?? "Not resolved"}</span>
                        <span>{formatCreatedAt(run.created_at)}</span>
                        <StatusPill tone={statusTone(run.status)}>{statusLabel(run.status)}</StatusPill>
                        <span style={promotionIntentStyle}>
                          <Button
                            disabled
                            style={disabledIntentButtonStyle}
                            title="Promotion remains disabled until a later publisher/profile workflow owns validation."
                            variant="secondary"
                          >
                            Future workflow
                          </Button>
                          <span style={mutedTextStyle}>{promotionIntentMessage(run)}</span>
                        </span>
                      </div>
                    </TableRow>
                  ))}
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </section>
  );
}
