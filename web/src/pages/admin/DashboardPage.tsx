import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, StatusPill, TableRow } from "../../components/ui";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type RunStatus = "available" | "unavailable" | "invalid" | "promoted";
type RunsRootStatus = "available" | "unavailable";
type ValidationOutcome = "accepted" | "rejected" | "failed" | "unknown";
type FilterStatus = "all" | RunStatus;

type PromotionSummary = {
  promotion_outcome: "promoted";
  release_id: string;
  dataset_slug: string;
  public_dataset_slug?: string;
  registry_action?: "created" | "updated" | "reused";
  registry_bound: boolean;
  can_promote: boolean;
  can_remove: boolean;
  reason?: string;
};

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
  promotion_summary?: PromotionSummary;
};

type AdminRunsResponse = {
  runs_root_status: RunsRootStatus;
  runs: AdminRunSummary[];
};

type DatasetDetailRow = {
  displayName: string;
  slug: string;
  visibilityStatus: "unavailable";
  lastUpdated: string | null;
  // Project Spec S0049: true only when this row was sourced from the real
  // dataset registry listing (GET /datasets), never for a run-derived
  // placeholder row shown while the registry listing is unavailable --
  // removal must only ever be offered for a row backed by a real
  // registry/datasets.json entry.
  isRegistryBacked: boolean;
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

type RunRemovalState =
  | { status: "idle" }
  | { status: "confirming"; runId: string }
  | { status: "removing"; runId: string }
  | { status: "error"; runId: string; message: string };

type DatasetDetailRemovalState =
  | { status: "idle" }
  | { status: "confirming"; slug: string }
  | { status: "removing"; slug: string }
  | { status: "error"; slug: string; message: string };

type RunPromotionEntry =
  | { status: "promoting" }
  | {
      status: "success";
      dataset_slug: string | null;
      release_id: string | null;
      registry_action: "created" | "updated" | "reused" | null;
      public_dataset_slug: string | null;
    }
  | { status: "error"; message: string };

type RunPromotionState = Record<string, RunPromotionEntry>;

type AdminRunPromotionResponse = {
  run_id: string;
  promoted: boolean;
  dataset_slug: string | null;
  release_id: string | null;
  registry_action: "created" | "updated" | "reused" | null;
  public_dataset_slug: string | null;
  errors: Array<{ code: string; field: string | null; message: string }>;
};

type DatasetRegistryEntry = {
  dataset_slug: string;
  title: string;
  display_title?: string | null;
};

type DatasetRegistryResponse = {
  datasets: DatasetRegistryEntry[];
};

type DatasetRegistryState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetRegistryEntry[] }
  | { status: "unavailable" };

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

const stickyTableHeaderStyle: CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 1,
  background: "var(--atlas-color-surface)",
};

const runsTableHeaderStyle: CSSProperties = {
  ...stickyTableHeaderStyle,
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.2fr) minmax(9rem, 0.9fr) minmax(9rem, 0.9fr) minmax(14rem, 1.1fr)",
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
  gridTemplateColumns: "minmax(0, 1.2fr) minmax(9rem, 0.9fr) minmax(9rem, 0.9fr) minmax(14rem, 1.1fr)",
  gap: "var(--atlas-space-3)",
  alignItems: "center",
};

const datasetTableHeaderStyle: CSSProperties = {
  ...stickyTableHeaderStyle,
  display: "grid",
  gridTemplateColumns:
    "minmax(0, 1.15fr) minmax(11rem, 1.05fr) minmax(7rem, 0.6fr) minmax(9rem, 0.85fr) minmax(6.5rem, 0.55fr)",
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
    "minmax(0, 1.15fr) minmax(11rem, 1.05fr) minmax(7rem, 0.6fr) minmax(9rem, 0.85fr) minmax(6.5rem, 0.55fr)",
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

const cardTitleStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text)",
  fontSize: "var(--atlas-text-xl)",
  fontWeight: 800,
};

const slugInputStyle: CSSProperties = {
  minHeight: "2.25rem",
  width: "100%",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  fontSize: "var(--atlas-text-sm)",
  background: "var(--atlas-color-surface)",
};

const disabledIntentButtonStyle: CSSProperties = {
  cursor: "not-allowed",
  opacity: 0.75,
  width: "fit-content",
};

const actionButtonStyle: CSSProperties = {
  width: "fit-content",
};

const modalBackdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "var(--atlas-space-5)",
  background: "rgba(15, 23, 42, 0.55)",
  zIndex: 10,
};

const modalCardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  width: "min(28rem, 100%)",
};

const modalActionsStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "var(--atlas-space-3)",
};

const actionGroupStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
};

const stackedActionGroupStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
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

function SaveActionIcon() {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M5 4h11l3 3v13H5z" />
      <path d="M8 4v5h7V4" />
      <path d="M8 14h8v6H8z" />
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

const promotionRegistryActions: Array<NonNullable<PromotionSummary["registry_action"]>> = ["created", "updated", "reused"];

function isPromotionSummary(value: unknown): value is PromotionSummary {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<PromotionSummary>;
  const validRegistryAction =
    record.registry_action === undefined ||
    promotionRegistryActions.includes(record.registry_action as NonNullable<PromotionSummary["registry_action"]>);

  return (
    record.promotion_outcome === "promoted" &&
    typeof record.release_id === "string" &&
    record.release_id.length > 0 &&
    typeof record.dataset_slug === "string" &&
    record.dataset_slug.length > 0 &&
    (record.public_dataset_slug === undefined || typeof record.public_dataset_slug === "string") &&
    validRegistryAction &&
    typeof record.registry_bound === "boolean" &&
    typeof record.can_promote === "boolean" &&
    typeof record.can_remove === "boolean" &&
    (record.reason === undefined || typeof record.reason === "string")
  );
}

function isAdminRunSummary(value: unknown): value is AdminRunSummary {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<AdminRunSummary>;
  const validStatus =
    record.status === "available" ||
    record.status === "unavailable" ||
    record.status === "invalid" ||
    record.status === "promoted";
  const validUnavailableReason =
    record.unavailable_reason === undefined ||
    unavailableReasons.includes(record.unavailable_reason as NonNullable<AdminRunSummary["unavailable_reason"]>);
  const validInvalidReason =
    record.invalid_reason === undefined ||
    invalidReasons.includes(record.invalid_reason as NonNullable<AdminRunSummary["invalid_reason"]>);
  const validPromotionSummary = record.status !== "promoted" || isPromotionSummary(record.promotion_summary);

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
    validInvalidReason &&
    validPromotionSummary
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

function isDatasetRegistryEntry(value: unknown): value is DatasetRegistryEntry {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<DatasetRegistryEntry>;
  return (
    typeof record.dataset_slug === "string" &&
    record.dataset_slug.length > 0 &&
    typeof record.title === "string" &&
    (record.display_title === undefined || record.display_title === null || typeof record.display_title === "string")
  );
}

function isDatasetRegistryResponse(value: unknown): value is DatasetRegistryResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const record = value as Partial<DatasetRegistryResponse>;
  return Array.isArray(record.datasets) && record.datasets.every(isDatasetRegistryEntry);
}

function promotionOutcomeMessage(entry: {
  dataset_slug: string | null;
  release_id: string | null;
  registry_action: "created" | "updated" | "reused" | null;
  public_dataset_slug: string | null;
}): string {
  const datasetPart = entry.dataset_slug ? `dataset "${entry.dataset_slug}"` : "the dataset";
  const releasePart = entry.release_id ? ` to release "${entry.release_id}"` : "";
  const actionPart =
    entry.registry_action === "created"
      ? "created a new registry entry"
      : entry.registry_action === "reused"
        ? "reused the already-promoted registry entry (idempotent, no changes made)"
        : entry.registry_action === "updated"
          ? "updated the existing registry entry"
          : "updated the dataset registry";

  const slugPart =
    entry.public_dataset_slug && entry.public_dataset_slug !== entry.dataset_slug
      ? ` Public Dataset Detail slug: "${entry.public_dataset_slug}".`
      : "";

  return `Promoted ${datasetPart}${releasePart} — ${actionPart}.${slugPart}`;
}

const PROMOTION_CONSEQUENCE =
  "Creates a new Dataset Detail entry with a deterministic unique public slug, leaving any existing entry untouched.";

function canPromoteRun(run: AdminRunSummary): boolean {
  if (run.status === "available") {
    return run.validation_summary?.outcome === "accepted";
  }

  // Project Spec S0048: a promoted run whose Dataset Detail is no longer
  // bound to the current registry (promotion_result_orphaned) is promotable
  // again -- can_promote is the backend's own re-derived signal for this,
  // never guessed from status alone.
  if (run.status === "promoted") {
    return run.promotion_summary?.can_promote === true;
  }

  return false;
}

function canRemoveRun(run: AdminRunSummary): boolean {
  if (run.status === "available") {
    return true;
  }

  // Project Spec S0048: Remove must remain available for promoted runs --
  // it only ever deletes the run artifact/directory, never the registry
  // entry, release, or Dataset Detail it may still be bound to.
  if (run.status === "promoted") {
    return run.promotion_summary?.can_remove === true;
  }

  return false;
}

function isRegistryBoundPromoted(run: AdminRunSummary): boolean {
  return run.status === "promoted" && run.promotion_summary?.registry_bound === true;
}

function promotedStateMessage(run: AdminRunSummary): string | null {
  if (run.status !== "promoted" || !run.promotion_summary) {
    return null;
  }

  const { release_id, dataset_slug, public_dataset_slug, reason } = run.promotion_summary;
  const slugPart =
    public_dataset_slug && public_dataset_slug !== dataset_slug
      ? ` Public Dataset Detail slug: "${public_dataset_slug}".`
      : "";
  const detailPart = release_id ? ` Promoted to release "${release_id}".${slugPart}` : "";

  return `${reason ?? "Already promoted."}${detailPart}`;
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

function datasetDisplayName(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function buildRunDerivedDatasetDetailRows(runs: AdminRunSummary[]): Map<string, DatasetDetailRow> {
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
      slug: run.dataset_candidate,
      visibilityStatus: "unavailable",
      lastUpdated: nextLastUpdated ?? null,
      isRegistryBacked: false,
    });
  }

  return rows;
}

function buildDatasetDetailRows(
  runs: AdminRunSummary[],
  registryDatasets: DatasetRegistryEntry[] | null,
): DatasetDetailRow[] {
  const runDerivedRows = buildRunDerivedDatasetDetailRows(runs);

  if (registryDatasets) {
    return registryDatasets
      .map((dataset) => ({
        displayName: dataset.display_title?.trim() || dataset.title.trim() || datasetDisplayName(dataset.dataset_slug),
        slug: dataset.dataset_slug,
        visibilityStatus: "unavailable" as const,
        lastUpdated: runDerivedRows.get(dataset.dataset_slug)?.lastUpdated ?? null,
        isRegistryBacked: true,
      }))
      .sort((first, second) => first.displayName.localeCompare(second.displayName));
  }

  return Array.from(runDerivedRows.values()).sort((first, second) => first.displayName.localeCompare(second.displayName));
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
    normalizeSearchText(row.slug).includes(query) ||
    normalizeSearchText(row.visibilityStatus).includes(query)
  );
}

export default function DashboardPage() {
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [state, setState] = useState<DashboardState>({ status: "idle" });
  const [removalState, setRemovalState] = useState<RunRemovalState>({ status: "idle" });
  const [datasetRemovalState, setDatasetRemovalState] = useState<DatasetDetailRemovalState>({ status: "idle" });
  const [promotionState, setPromotionState] = useState<RunPromotionState>({});
  const [datasetRegistryState, setDatasetRegistryState] = useState<DatasetRegistryState>({ status: "idle" });

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
  const registryDatasets = datasetRegistryState.status === "ready" ? datasetRegistryState.datasets : null;
  const datasetRows = useMemo(() => buildDatasetDetailRows(runs, registryDatasets), [runs, registryDatasets]);

  const counters = useMemo(
    () => ({
      runsAvailable: runs.filter((run) => run.status === "available").length,
      promotedRuns: runs.filter((run) => run.status === "promoted").length,
      publishedDatasets: registryDatasets ? registryDatasets.length : 0,
      draftDatasets: 0,
    }),
    [runs, registryDatasets],
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

  function loadDatasetRegistry() {
    setDatasetRegistryState((previous) => (previous.status === "ready" ? previous : { status: "loading" }));

    fetch(`${apiBaseUrl}/datasets`)
      .then((res) => {
        if (!res.ok) {
          setDatasetRegistryState({ status: "unavailable" });
          return null;
        }

        return res.json() as Promise<unknown>;
      })
      .then((data) => {
        if (!data) {
          return;
        }

        if (!isDatasetRegistryResponse(data)) {
          setDatasetRegistryState({ status: "unavailable" });
          return;
        }

        setDatasetRegistryState({ status: "ready", datasets: data.datasets });
      })
      .catch(() => {
        setDatasetRegistryState({ status: "unavailable" });
      });
  }

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

    loadDatasetRegistry();
  }

  function openRemoveConfirmation(runId: string) {
    setRemovalState({ status: "confirming", runId });
  }

  function cancelRemoveConfirmation() {
    setRemovalState({ status: "idle" });
  }

  function confirmRemoveRun(runId: string) {
    setRemovalState({ status: "removing", runId });

    fetch(`${apiBaseUrl}/admin/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    })
      .then((res) => {
        if (!res.ok) {
          setRemovalState({
            status: "error",
            runId,
            message: "The run could not be removed. Confirm the run is still available and try again.",
          });
          return;
        }

        setState((previous) =>
          previous.status === "ready"
            ? {
                status: "ready",
                data: { ...previous.data, runs: previous.data.runs.filter((run) => run.run_id !== runId) },
              }
            : previous,
        );
        setRemovalState({ status: "idle" });
      })
      .catch(() => {
        setRemovalState({
          status: "error",
          runId,
          message: "The run could not be removed. Check private admin API reachability.",
        });
      });
  }

  function openRemoveDatasetConfirmation(slug: string) {
    setDatasetRemovalState({ status: "confirming", slug });
  }

  function cancelRemoveDatasetConfirmation() {
    setDatasetRemovalState({ status: "idle" });
  }

  function confirmRemoveDataset(slug: string) {
    setDatasetRemovalState({ status: "removing", slug });

    // Project Spec S0049: removes only the registry entry -- distinct from
    // confirmRemoveRun above, which only ever removes a run artifact.
    fetch(`${apiBaseUrl}/admin/datasets/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    })
      .then((res) => {
        if (!res.ok) {
          setDatasetRemovalState({
            status: "error",
            slug,
            message: "The Dataset Detail could not be removed. Confirm it is still registry-backed and try again.",
          });
          return;
        }

        setDatasetRemovalState({ status: "idle" });
        loadDatasetRegistry();
      })
      .catch(() => {
        setDatasetRemovalState({
          status: "error",
          slug,
          message: "The Dataset Detail could not be removed. Check private admin API reachability.",
        });
      });
  }

  function promoteRun(runId: string) {
    setPromotionState((previous) => ({ ...previous, [runId]: { status: "promoting" } }));

    // Project Spec S0047: Admin Dashboard promotion always requests
    // create_new_dataset_detail -- there is no operator-facing choice
    // between updating an existing Dataset Detail and creating a new one.
    fetch(`${apiBaseUrl}/admin/runs/${encodeURIComponent(runId)}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "create_new_dataset_detail" }),
    })
      .then(async (res) => {
        const body = (await res.json().catch(() => null)) as AdminRunPromotionResponse | null;

        if (!res.ok) {
          const detail = body?.errors?.[0]?.message;
          setPromotionState((previous) => ({
            ...previous,
            [runId]: {
              status: "error",
              message: detail ?? "The run could not be promoted. Confirm the run is still eligible and try again.",
            },
          }));
          return;
        }

        setPromotionState((previous) => ({
          ...previous,
          [runId]: {
            status: "success",
            dataset_slug: body?.dataset_slug ?? null,
            release_id: body?.release_id ?? null,
            registry_action: body?.registry_action ?? null,
            public_dataset_slug: body?.public_dataset_slug ?? null,
          },
        }));
        loadRuns();
      })
      .catch(() => {
        setPromotionState((previous) => ({
          ...previous,
          [runId]: { status: "error", message: "The run could not be promoted. Check private admin API reachability." },
        }));
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
          <h1 id="admin-dashboard-title">Dashboard</h1>
          <p className="summary">
            Private run and dataset readiness from safe admin projections. Statuses come from the backend; no raw
            filesystem, draft, runtime, or log inspection is performed in the browser.
          </p>
        </div>

        <div aria-label="Dashboard controls" className="admin-dashboard__header-controls">
          <span className="admin-dashboard__search-control-row">
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
            <span aria-hidden="true" className="admin-dashboard__search-hint">
              ⌘K
            </span>
          </span>

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
                <option value="promoted">Promoted</option>
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
              <StatusPill tone="success">Promoted</StatusPill>
              <strong style={counterValueStyle}>{counters.promotedRuns}</strong>
              <span style={mutedTextStyle}>Runs already promoted</span>
            </Card>
            <Card
              aria-label="Published datasets"
              data-registry-status={datasetRegistryState.status}
              data-summary-count={counters.publishedDatasets}
            >
              <span aria-hidden="true" className="admin-dashboard__summary-icon admin-dashboard__summary-icon--green">
                <PublishedDatasetsIcon />
              </span>
              {datasetRegistryState.status === "ready" ? (
                <StatusPill tone="success">Registry available</StatusPill>
              ) : (
                <StatusPill tone="warning">Unavailable</StatusPill>
              )}
              <strong style={counterValueStyle}>{counters.publishedDatasets}</strong>
              <span style={mutedTextStyle}>
                {datasetRegistryState.status === "ready"
                  ? "From the safe dataset registry listing"
                  : "Registry listing unavailable"}
              </span>
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
            <Card aria-labelledby="dataset-details-table-title">
              <div>
                <h2 id="dataset-details-table-title" style={cardTitleStyle}>
                  Dataset Details
                </h2>
              </div>

              {datasetRegistryState.status === "unavailable" && (
                <span role="status" style={mutedTextStyle}>
                  Dataset registry listing unavailable — showing run-derived placeholders instead.
                </span>
              )}

              {datasetRows.length === 0 ? (
                <EmptyState
                  title="Dataset Details unavailable"
                  message="No safe dataset-detail rows are available from the current admin run summaries."
                />
              ) : filteredDatasetRows.length === 0 ? (
                <EmptyState title="No matching datasets" message="Adjust the Dashboard search to view dataset rows." />
              ) : (
                <div className="admin-dashboard__table-wrap admin-dashboard__table-wrap--scrollable">
                  <div
                    role="table"
                    aria-label="Dataset details"
                    data-filtered-dataset-count={filteredDatasetRows.length}
                    style={tableStyle}
                  >
                    <div role="row" style={datasetTableHeaderStyle}>
                      <span role="columnheader">Display name</span>
                      <span role="columnheader">Slug</span>
                      <span role="columnheader">Status</span>
                      <span role="columnheader">Last updated</span>
                      <span role="columnheader">Actions</span>
                    </div>

                    {filteredDatasetRows.map((row) => (
                      <TableRow key={row.displayName}>
                        <div data-dataset-visibility={row.visibilityStatus} style={datasetRowContentStyle}>
                          <input
                            aria-label={`${row.displayName} display name`}
                            defaultValue={row.displayName}
                            style={slugInputStyle}
                            type="text"
                          />
                          <input
                            aria-label={`${row.displayName} slug`}
                            defaultValue={row.slug}
                            style={slugInputStyle}
                            type="text"
                          />
                          <StatusPill tone="warning">Unavailable</StatusPill>
                          <span>{formatCreatedAt(row.lastUpdated)}</span>
                          <span style={stackedActionGroupStyle}>
                            <Button
                              data-dataset-action="save-disabled"
                              disabled
                              style={disabledIntentButtonStyle}
                              title="Save remains disabled until a safe owned API exists."
                              variant="secondary"
                            >
                              <span aria-hidden="true" style={actionIconStyle}>
                                <SaveActionIcon />
                              </span>
                              Save
                            </Button>
                            <Button
                              data-dataset-action={row.isRegistryBacked ? "remove" : "remove-disabled"}
                              disabled={!row.isRegistryBacked}
                              onClick={() => openRemoveDatasetConfirmation(row.slug)}
                              style={row.isRegistryBacked ? actionButtonStyle : disabledIntentButtonStyle}
                              title={
                                row.isRegistryBacked
                                  ? "Remove this Dataset Detail from the active registry/public listing. Release artifacts and publisher run history are preserved."
                                  : "Remove is only available for registry-backed Dataset Details."
                              }
                              variant="secondary"
                            >
                              <span aria-hidden="true" style={actionIconStyle}>
                                <RemoveActionIcon />
                              </span>
                              Remove
                            </Button>
                          </span>
                        </div>
                      </TableRow>
                    ))}
                  </div>
                </div>
              )}
            </Card>

            <Card aria-labelledby="admin-runs-table-title">
              <div>
                <h2 id="admin-runs-table-title" style={cardTitleStyle}>
                  Runs
                </h2>
              </div>

              {filteredRuns.length === 0 ? (
                <EmptyState title="No matching runs" message="Adjust the Dashboard filters to view returned summaries." />
              ) : (
                <div className="admin-dashboard__table-wrap admin-dashboard__table-wrap--scrollable">
                  <div role="table" aria-label="Run summaries" data-filtered-run-count={filteredRuns.length} style={tableStyle}>
                    <div role="row" style={runsTableHeaderStyle}>
                      <span role="columnheader">Run ID</span>
                      <span role="columnheader">Dataset</span>
                      <span role="columnheader">Created at</span>
                      <span role="columnheader">Actions</span>
                    </div>

                    {filteredRuns.map((run) => {
                      const promotionEntry = promotionState[run.run_id];
                      const isPromoting = promotionEntry?.status === "promoting";
                      const promotionError = promotionEntry?.status === "error" ? promotionEntry.message : null;
                      const promotionSuccessMessage =
                        promotionEntry?.status === "success" ? promotionOutcomeMessage(promotionEntry) : null;
                      const promotionEligible = canPromoteRun(run);
                      const registryBoundPromoted = isRegistryBoundPromoted(run);
                      // Project Spec S0048: a registry-bound promoted run's
                      // Promote action remains clickable (never disabled) --
                      // it is just informational and never calls the
                      // promotion endpoint. Every other run's Promote action
                      // is disabled unless it is currently promotion-eligible.
                      const promoteDisabled = registryBoundPromoted ? false : !promotionEligible || isPromoting;
                      const removeEligible = canRemoveRun(run);
                      const alreadyPromoted = run.status === "promoted";
                      const metaMessage =
                        promotionSuccessMessage ?? promotionError ?? promotedStateMessage(run) ?? reasonLabel(run);

                      return (
                      <TableRow
                        key={run.run_id}
                        meta={
                          metaMessage && (
                            <span role={promotionSuccessMessage ? "status" : undefined} style={mutedTextStyle}>
                              {metaMessage}
                            </span>
                          )
                        }
                      >
                        <div data-run-status={run.status} style={runRowContentStyle}>
                          <span style={{ display: "flex", alignItems: "center", gap: "var(--atlas-space-2)" }}>
                            <strong>{run.run_id}</strong>
                            {alreadyPromoted && <StatusPill tone="success">Promoted</StatusPill>}
                          </span>
                          <span>{run.dataset_candidate ?? "Not resolved"}</span>
                          <span>{formatCreatedAt(run.created_at)}</span>
                          <span style={actionGroupStyle}>
                            <Button
                              data-run-action={
                                registryBoundPromoted
                                  ? "promoted"
                                  : !promotionEligible
                                    ? "promote-disabled"
                                    : isPromoting
                                      ? "promote-loading"
                                      : "promote"
                              }
                              disabled={promoteDisabled}
                              onClick={() => {
                                // Project Spec S0048: a registry-bound
                                // promoted run's Promote action stays
                                // clickable but is purely informational --
                                // the current promoted state is already
                                // shown via this row's meta message, and
                                // clicking must never call the promotion
                                // endpoint again.
                                if (registryBoundPromoted) {
                                  return;
                                }
                                promoteRun(run.run_id);
                              }}
                              style={promotionEligible || registryBoundPromoted ? actionButtonStyle : disabledIntentButtonStyle}
                              title={
                                registryBoundPromoted
                                  ? "This run has already been promoted as a Dataset Detail. Clicking shows the current promotion status and does not trigger another promotion."
                                  : promotionEligible
                                    ? PROMOTION_CONSEQUENCE
                                    : "Promote is only available for eligible runs."
                              }
                              variant="secondary"
                            >
                              <span aria-hidden="true" style={actionIconStyle}>
                                <PromoteActionIcon />
                              </span>
                              {isPromoting ? "Promoting..." : registryBoundPromoted ? "Promoted" : "Promote"}
                            </Button>
                            <Button
                              data-run-action={removeEligible ? "remove" : "remove-disabled"}
                              disabled={!removeEligible}
                              onClick={() => openRemoveConfirmation(run.run_id)}
                              style={removeEligible ? actionButtonStyle : disabledIntentButtonStyle}
                              title={
                                removeEligible
                                  ? "Remove this run from the Admin Dashboard after confirmation."
                                  : "Remove is only available for safe, available or promoted runs."
                              }
                              variant="secondary"
                            >
                              <span aria-hidden="true" style={actionIconStyle}>
                                <RemoveActionIcon />
                              </span>
                              Remove
                            </Button>
                          </span>
                        </div>
                      </TableRow>
                      );
                    })}
                  </div>
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      {removalState.status !== "idle" && (
        <div style={modalBackdropStyle}>
          <Card aria-labelledby="remove-run-modal-title" aria-modal="true" role="dialog" style={modalCardStyle}>
            <h2 id="remove-run-modal-title" style={cardTitleStyle}>
              Remove run {removalState.runId}?
            </h2>
            <p style={{ margin: 0 }}>
              This removes the publisher validation run record for <strong>{removalState.runId}</strong> from the
              Admin Dashboard. This action cannot be undone.
            </p>

            {removalState.status === "error" && (
              <ErrorState title="Run removal failed" message={removalState.message} />
            )}

            <div style={modalActionsStyle}>
              <Button
                disabled={removalState.status === "removing"}
                onClick={cancelRemoveConfirmation}
                variant="secondary"
              >
                Cancel
              </Button>
              <Button
                disabled={removalState.status === "removing"}
                onClick={() => confirmRemoveRun(removalState.runId)}
              >
                {removalState.status === "removing" ? "Removing..." : "Remove run"}
              </Button>
            </div>
          </Card>
        </div>
      )}

      {datasetRemovalState.status !== "idle" && (
        <div style={modalBackdropStyle}>
          <Card aria-labelledby="remove-dataset-modal-title" aria-modal="true" role="dialog" style={modalCardStyle}>
            <h2 id="remove-dataset-modal-title" style={cardTitleStyle}>
              Remove Dataset Detail "{datasetRemovalState.slug}"?
            </h2>
            <p style={{ margin: 0 }}>
              This removes <strong>{datasetRemovalState.slug}</strong> from the active registry and public listing
              only. Release artifacts, publisher run history, model artifacts, notebooks, and evidence are preserved
              and are not deleted. This is a different action from removing a run above. Once removed, this slug
              becomes available again for a new Create New promotion.
            </p>

            {datasetRemovalState.status === "error" && (
              <ErrorState title="Dataset Detail removal failed" message={datasetRemovalState.message} />
            )}

            <div style={modalActionsStyle}>
              <Button
                disabled={datasetRemovalState.status === "removing"}
                onClick={cancelRemoveDatasetConfirmation}
                variant="secondary"
              >
                Cancel
              </Button>
              <Button
                disabled={datasetRemovalState.status === "removing"}
                onClick={() => confirmRemoveDataset(datasetRemovalState.slug)}
              >
                {datasetRemovalState.status === "removing" ? "Removing..." : "Remove Dataset Detail"}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </section>
  );
}
