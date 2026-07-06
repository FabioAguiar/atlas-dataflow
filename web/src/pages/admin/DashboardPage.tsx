import { useEffect, useMemo, useRef, useState } from "react";
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

type DatasetDetailRow = {
  displayName: string;
  problemType: string;
  visibilityStatus: "unavailable";
  lastUpdated: string | null;
  sourceRunCount: number;
};

const validationOutcomes: ValidationOutcome[] = ["accepted", "rejected", "failed", "unknown"];
const unavailableReasons: Array<NonNullable<AdminRunSummary["unavailable_reason"]>> = [
  "source_run_evidence_missing",
  "source_run_evidence_unreadable",
];
const invalidReasons: Array<NonNullable<AdminRunSummary["invalid_reason"]>> = [
  "source_run_evidence_malformed",
  "source_run_evidence_incomplete",
  "source_run_evidence_schema_invalid",
];

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
  gridTemplateColumns: "repeat(4, minmax(9.5rem, 1fr))",
  gap: "var(--atlas-space-3)",
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

const runsTableHeaderStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.1fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(11rem, 0.85fr)",
  gap: "var(--atlas-space-3)",
  borderBottom: "1px solid var(--atlas-color-border-strong)",
  paddingBottom: "var(--atlas-space-3)",
  color: "var(--atlas-color-text-subtle)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  textTransform: "uppercase",
};

const runRowContentStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.1fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(11rem, 0.85fr)",
  gap: "var(--atlas-space-3)",
  alignItems: "center",
};

const datasetTableHeaderStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.15fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(14rem, 1fr)",
  gap: "var(--atlas-space-3)",
  borderBottom: "1px solid var(--atlas-color-border-strong)",
  paddingBottom: "var(--atlas-space-3)",
  color: "var(--atlas-color-text-subtle)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  textTransform: "uppercase",
};

const datasetRowContentStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.15fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(8rem, 0.75fr) minmax(14rem, 1fr)",
  gap: "var(--atlas-space-3)",
  alignItems: "center",
};

const sectionGridStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
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

const actionGroupStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
};

const actionIconStyle: CSSProperties = {
  display: "inline-flex",
  width: "1rem",
  height: "1rem",
};

function RunsAvailableIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M7.5 5.5 18 12 7.5 18.5z" />
    </svg>
  );
}

function PromotedRunsIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M12 3.8 14 6l3-.2 1.1 2.8 2.3 1.8-1.4 2.6.5 3-2.8 1.1-1.8 2.3-2.9-1.4-2.9 1.4-1.8-2.3-2.8-1.1.5-3-1.4-2.6 2.3-1.8L7 5.8l3 .2 2-2.2Z" />
      <path d="m8.8 12 2.2 2.2 4.4-4.6" />
    </svg>
  );
}

function PublishedDatasetsIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="8" />
      <path d="M4 12h16M12 4c2 2.2 3 4.8 3 8s-1 5.8-3 8M12 4c-2 2.2-3 4.8-3 8s1 5.8 3 8" />
    </svg>
  );
}

function DraftDatasetsIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M7 3.5h7l3 3V20H7z" />
      <path d="M14 3.5V7h3" />
      <path d="M10 12h4M10 15h5" />
    </svg>
  );
}

function PromoteActionIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M7.5 5.5 18 12 7.5 18.5z" />
    </svg>
  );
}

function RemoveActionIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7l1-3h4l1 3" />
    </svg>
  );
}

function OpenAdminActionIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M14 4h6v6" />
      <path d="m20 4-9 9" />
      <path d="M10 6H6v12h12v-4" />
    </svg>
  );
}

function isSafeTraceReference(value: string | null): boolean {
  if (value === null) {
    return true;
  }

  return !value.startsWith("/") && !/^[A-Za-z]:[\\/]/.test(value) && !value.includes("..");
}

function isValidationSummary(value: unknown): value is AdminRunSummary["validation_summary"] {
  if (value === null) {
    return true;
  }

  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<NonNullable<AdminRunSummary["validation_summary"]>>;
  return (
    typeof record.outcome === "string" &&
    validationOutcomes.includes(record.outcome as ValidationOutcome) &&
    (record.reason === undefined || typeof record.reason === "string")
  );
}

function isAdminRunSummary(value: unknown): value is AdminRunSummary {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<AdminRunSummary>;
  const validStatus = record.status === "available" || record.status === "unavailable" || record.status === "invalid";
  const validUnavailableReason =
    record.unavailable_reason === undefined ||
    unavailableReasons.includes(record.unavailable_reason as NonNullable<AdminRunSummary["unavailable_reason"]>);
  const validInvalidReason =
    record.invalid_reason === undefined ||
    invalidReasons.includes(record.invalid_reason as NonNullable<AdminRunSummary["invalid_reason"]>);

  return (
    record.schema_version === "admin-run-summary.v1" &&
    typeof record.run_id === "string" &&
    record.run_id.length > 0 &&
    validStatus &&
    (typeof record.dataset_candidate === "string" || record.dataset_candidate === null) &&
    (typeof record.created_at === "string" || record.created_at === null) &&
    (typeof record.trace_reference === "string" || record.trace_reference === null) &&
    isSafeTraceReference(record.trace_reference) &&
    isValidationSummary(record.validation_summary) &&
    validUnavailableReason &&
    validInvalidReason
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

function datasetDisplayName(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function buildDatasetDetailRows(runs: AdminRunSummary[]): DatasetDetailRow[] {
  const rows = new Map<string, DatasetDetailRow>();

  for (const run of runs) {
    if (!run.dataset_candidate) {
      continue;
    }

    const existing = rows.get(run.dataset_candidate);
    const nextLastUpdated =
      existing?.lastUpdated && run.created_at
        ? new Date(existing.lastUpdated).getTime() >= new Date(run.created_at).getTime()
          ? existing.lastUpdated
          : run.created_at
        : existing?.lastUpdated ?? run.created_at;

    rows.set(run.dataset_candidate, {
      displayName: datasetDisplayName(run.dataset_candidate),
      problemType: "Pending safe profile source",
      visibilityStatus: "unavailable",
      lastUpdated: nextLastUpdated ?? null,
      sourceRunCount: (existing?.sourceRunCount ?? 0) + 1,
    });
  }

  return Array.from(rows.values()).sort((first, second) => first.displayName.localeCompare(second.displayName));
}

function normalizeSearchText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function datasetMatchesQuery(row: DatasetDetailRow, query: string): boolean {
  if (query.length === 0) {
    return true;
  }

  return (
    normalizeSearchText(row.displayName).includes(query) ||
    normalizeSearchText(row.problemType).includes(query) ||
    normalizeSearchText(row.visibilityStatus).includes(query)
  );
}

export default function DashboardPage() {
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [state, setState] = useState<DashboardState>({ status: "idle" });

  useEffect(() => {
    function handleSearchShortcut(event: KeyboardEvent) {
      const isMacShortcut = event.metaKey && event.key.toLowerCase() === "k";
      const isWinShortcut = event.ctrlKey && event.key.toLowerCase() === "k";
      if (!isMacShortcut && !isWinShortcut) {
        return;
      }

      event.preventDefault();
      searchInputRef.current?.focus();
      searchInputRef.current?.select();
    }

    document.addEventListener("keydown", handleSearchShortcut);
    return () => document.removeEventListener("keydown", handleSearchShortcut);
  }, []);

  const runs = state.status === "ready" ? state.data.runs : [];
  const datasetRows = useMemo(() => buildDatasetDetailRows(runs), [runs]);

  const counters = useMemo(
    () => ({
      runsAvailable: runs.filter((run) => run.status === "available").length,
      promotedRuns: 0,
      publishedDatasets: 0,
      draftDatasets: 0,
    }),
    [runs],
  );

  const normalizedQuery = normalizeSearchText(query.trim());

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      const matchesStatus = statusFilter === "all" || run.status === statusFilter;
      const matchesQuery =
        normalizedQuery.length === 0 ||
        normalizeSearchText(run.run_id).includes(normalizedQuery) ||
        normalizeSearchText(run.dataset_candidate ?? "").includes(normalizedQuery) ||
        normalizeSearchText(run.validation_summary?.outcome ?? "").includes(normalizedQuery);

      return matchesStatus && matchesQuery;
    });
  }, [normalizedQuery, runs, statusFilter]);

  const filteredDatasetRows = useMemo(
    () => datasetRows.filter((row) => datasetMatchesQuery(row, normalizedQuery)),
    [datasetRows, normalizedQuery],
  );

  function loadRuns() {
    const controller = new AbortController();
    setState({ status: "loading" });

    fetch(`${apiBaseUrl}/admin/runs`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (res.status === 404) {
          setState({
            status: "unavailable",
            message: "Run summaries are unavailable in this private admin runtime. Confirm the admin API configuration.",
          });
          return null;
        }

        if (!res.ok) {
          setState({ status: "error", message: "Run summaries could not be loaded from the private admin API." });
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
          setState({ status: "error", message: "Run summaries could not be loaded. Check private admin API reachability." });
        }
      });
  }

  return (
    <section
      aria-labelledby="admin-dashboard-title"
      className="admin-dashboard"
      data-dashboard-state={state.status}
      style={pageStyle}
    >
      <div className="admin-dashboard__header" style={headerStyle}>
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1 id="admin-dashboard-title">Dashboard</h1>
          <p className="summary">
            Private run and dataset readiness from safe admin projections. Statuses come from the backend; no raw
            filesystem, draft, runtime, or log inspection is performed in the browser.
          </p>
        </div>

        <div aria-label="Dashboard controls" className="admin-dashboard__header-controls">
          <label className="admin-dashboard__search-control" style={fieldStyle}>
            <span style={labelStyle}>Search runs and datasets</span>
            <input
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search runs or datasets..."
              ref={searchInputRef}
              style={inputStyle}
              type="search"
              value={query}
            />
          </label>

          <Button disabled={state.status === "loading"} onClick={loadRuns} type="button">
            {state.status === "loading" ? "Loading..." : "Load runs"}
          </Button>
        </div>
      </div>

      {state.status === "idle" && (
        <EmptyState title="Run summaries not loaded" message="Load the private admin summary projection when the admin API is available." />
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
          <Card aria-label="Run status filter" muted>
            <label style={fieldStyle}>
              <span style={labelStyle}>Run status</span>
              <select
                onChange={(event) => setStatusFilter(event.target.value as FilterStatus)}
                style={{ ...inputStyle, width: "min(18rem, 100%)" }}
                value={statusFilter}
              >
                <option value="all">All statuses</option>
                <option value="available">Available</option>
                <option value="invalid">Invalid</option>
                <option value="unavailable">Unavailable</option>
              </select>
            </label>
          </Card>

          <div data-runs-root-status={state.data.runs_root_status} style={statusGridStyle}>
            <Card aria-label="Runs available" data-summary-count={counters.runsAvailable}>
              <span aria-hidden="true" className="admin-dashboard__summary-icon admin-dashboard__summary-icon--green">
                <RunsAvailableIcon />
              </span>
              <Badge>{rootStatusMessage(state.data.runs_root_status)}</Badge>
              <strong style={counterValueStyle}>{counters.runsAvailable}</strong>
              <span style={mutedTextStyle}>Runs available</span>
            </Card>
            <Card aria-label="Promoted runs" data-summary-count={counters.promotedRuns}>
              <span aria-hidden="true" className="admin-dashboard__summary-icon admin-dashboard__summary-icon--green">
                <PromotedRunsIcon />
              </span>
              <StatusPill tone="warning">Unavailable</StatusPill>
              <strong style={counterValueStyle}>{counters.promotedRuns}</strong>
              <span style={mutedTextStyle}>Promotion source not owned</span>
            </Card>
            <Card aria-label="Published datasets" data-summary-count={counters.publishedDatasets}>
              <span aria-hidden="true" className="admin-dashboard__summary-icon admin-dashboard__summary-icon--green">
                <PublishedDatasetsIcon />
              </span>
              <StatusPill tone="warning">Unavailable</StatusPill>
              <strong style={counterValueStyle}>{counters.publishedDatasets}</strong>
              <span style={mutedTextStyle}>Publication source not owned</span>
            </Card>
            <Card aria-label="Draft datasets" data-summary-count={counters.draftDatasets}>
              <span aria-hidden="true" className="admin-dashboard__summary-icon admin-dashboard__summary-icon--amber">
                <DraftDatasetsIcon />
              </span>
              <StatusPill tone="warning">Unavailable</StatusPill>
              <strong style={counterValueStyle}>{counters.draftDatasets}</strong>
              <span style={mutedTextStyle}>Draft source not owned</span>
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

          <div style={sectionGridStyle}>
            <Card aria-labelledby="admin-runs-table-title">
              <div>
                <p className="eyebrow">Runs</p>
                <h2 id="admin-runs-table-title" style={{ margin: 0 }}>
                  Safe run summaries
                </h2>
              </div>

              <div aria-label="Promotion boundary" role="status" style={intentBoundaryStyle}>
                <StatusPill tone="warning">Promotion intent disabled</StatusPill>
                <p style={{ ...mutedTextStyle, margin: 0 }}>
                  Dashboard promotion is a future workflow entry point only. It does not create drafts, release
                  candidates, publications, published snapshot visibility changes, registry updates, or release artifact
                  mutations.
                </p>
              </div>

              <div aria-label="Run filter summary" style={filterBarStyle}>
                <Badge>{statusFilter === "all" ? "All run statuses" : `${statusLabel(statusFilter)} runs`}</Badge>
                <span style={mutedTextStyle}>{filteredRuns.length} matching run summaries</span>
              </div>

              {filteredRuns.length === 0 ? (
                <EmptyState title="No matching runs" message="Adjust the Dashboard filters to view returned summaries." />
              ) : (
                <div className="admin-dashboard__table-wrap">
                  <div role="table" aria-label="Run summaries" data-filtered-run-count={filteredRuns.length} style={tableStyle}>
                    <div role="row" style={runsTableHeaderStyle}>
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
                        <div data-run-status={run.status} style={runRowContentStyle}>
                          <strong>{run.run_id}</strong>
                          <span>{run.dataset_candidate ?? "Not resolved"}</span>
                          <span>{formatCreatedAt(run.created_at)}</span>
                          <StatusPill tone={statusTone(run.status)}>{statusLabel(run.status)}</StatusPill>
                          <span style={promotionIntentStyle}>
                            <Button
                              data-promotion-intent="disabled"
                              disabled
                              style={disabledIntentButtonStyle}
                              title="Promotion remains disabled until a later publisher/profile workflow owns validation."
                              variant="secondary"
                            >
                              <span aria-hidden="true" style={actionIconStyle}>
                                <PromoteActionIcon />
                              </span>
                              Future workflow
                            </Button>
                            <span style={mutedTextStyle}>{promotionIntentMessage(run)}</span>
                          </span>
                        </div>
                      </TableRow>
                    ))}
                  </div>
                </div>
              )}
            </Card>

            <Card aria-labelledby="dataset-details-table-title">
              <div>
                <p className="eyebrow">Dataset Details</p>
                <h2 id="dataset-details-table-title" style={{ margin: 0 }}>
                  Safe dataset readiness
                </h2>
                <p style={{ ...mutedTextStyle, margin: 0 }}>
                  Dataset rows are derived only from validated run summaries until a safe profile, publication, or
                  visibility projection is owned.
                </p>
              </div>

              <div aria-label="Safe action boundary" role="status" style={intentBoundaryStyle}>
                <StatusPill tone="warning">Dataset actions disabled</StatusPill>
                <p style={{ ...mutedTextStyle, margin: 0 }}>
                  Promote, Remove, and Open admin remain disabled until a safe, owned backend API exists for dataset
                  promotion, removal, or admin navigation.
                </p>
              </div>

              {datasetRows.length === 0 ? (
                <EmptyState
                  title="Dataset Details unavailable"
                  message="No safe dataset-detail rows are available from the current admin run summaries."
                />
              ) : filteredDatasetRows.length === 0 ? (
                <EmptyState title="No matching datasets" message="Adjust the Dashboard search to view dataset rows." />
              ) : (
                <div className="admin-dashboard__table-wrap">
                  <div
                    role="table"
                    aria-label="Dataset details"
                    data-filtered-dataset-count={filteredDatasetRows.length}
                    style={tableStyle}
                  >
                    <div role="row" style={datasetTableHeaderStyle}>
                      <span role="columnheader">Display name</span>
                      <span role="columnheader">Problem type</span>
                      <span role="columnheader">Visibility status</span>
                      <span role="columnheader">Last updated</span>
                      <span role="columnheader">Actions</span>
                    </div>

                    {filteredDatasetRows.map((row) => (
                      <TableRow
                        key={row.displayName}
                        meta={<span style={mutedTextStyle}>{row.sourceRunCount} source run summaries</span>}
                      >
                        <div data-dataset-visibility={row.visibilityStatus} style={datasetRowContentStyle}>
                          <strong>{row.displayName}</strong>
                          <span>{row.problemType}</span>
                          <StatusPill tone="warning">Unavailable</StatusPill>
                          <span>{formatCreatedAt(row.lastUpdated)}</span>
                          <span style={promotionIntentStyle}>
                            <span style={actionGroupStyle}>
                              <Button
                                data-dataset-action="promote-disabled"
                                disabled
                                style={disabledIntentButtonStyle}
                                title="Promote remains disabled until a safe owned API exists."
                                variant="secondary"
                              >
                                <span aria-hidden="true" style={actionIconStyle}>
                                  <PromoteActionIcon />
                                </span>
                                Promote
                              </Button>
                              <Button
                                data-dataset-action="remove-disabled"
                                disabled
                                style={disabledIntentButtonStyle}
                                title="Remove remains disabled until a safe owned API exists."
                                variant="secondary"
                              >
                                <span aria-hidden="true" style={actionIconStyle}>
                                  <RemoveActionIcon />
                                </span>
                                Remove
                              </Button>
                              <Button
                                data-dataset-action="open-admin-disabled"
                                disabled
                                style={disabledIntentButtonStyle}
                                title="Open admin requires a safe route and identifier."
                                variant="secondary"
                              >
                                <span aria-hidden="true" style={actionIconStyle}>
                                  <OpenAdminActionIcon />
                                </span>
                                Open admin
                              </Button>
                            </span>
                            <span style={mutedTextStyle}>Safe action owner unavailable</span>
                          </span>
                        </div>
                      </TableRow>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}
