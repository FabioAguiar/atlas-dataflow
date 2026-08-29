import { useEffect, useState } from "react";
import type { ReactElement } from "react";

// Project Spec S0277: one shared, device-adaptive chart-interaction layer for
// the existing Recharts-based Dataset Detail analytical renderers. This module
// is frontend presentation infrastructure only -- it never knows a dataset
// slug, analysis type, model id, release id, highlighted-score policy, or any
// API route. It owns three things:
//   1. the shared Atlas-styled tooltip panel;
//   2. the pointer/hover-capability-driven Recharts tooltip trigger selection;
//   3. bounded formatting helpers appropriate for tooltip display.
// It invents no data: a chart component hands it already-validated semantic
// rows and it renders exactly those.

export type ChartInteractionMode = "hover" | "click";

// The hover-capable primary-input case is exactly a fine pointer that can
// hover. Everything else -- coarse pointer, no-hover, or unknown -- uses
// click/tap. This is a capability query, never a viewport-width breakpoint.
const HOVER_CAPABLE_MEDIA_QUERY = "(hover: hover) and (pointer: fine)";

function safeMatchMedia(query: string): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  try {
    return window.matchMedia(query);
  } catch {
    return null;
  }
}

/**
 * Resolves the interaction mode from pointer/hover capability. Returns the
 * deterministic "click" fallback whenever capability cannot be established
 * (no window, no `matchMedia`, or a throwing `matchMedia`) -- a click/tap
 * affordance stays usable without hover, so it is the safe default. Never
 * touches `window` outside the guarded helper, so it is server/render safe.
 */
export function resolveChartInteractionMode(): ChartInteractionMode {
  const query = safeMatchMedia(HOVER_CAPABLE_MEDIA_QUERY);
  if (!query) {
    return "click";
  }
  return query.matches ? "hover" : "click";
}

/**
 * Subscribes to pointer/hover capability changes (a tablet gaining a mouse, a
 * laptop docking a trackpad) and re-resolves the interaction mode without
 * remounting the page. Cleans up its listener on unmount. Uses the deprecated
 * add/removeListener pair only where the modern add/removeEventListener pair
 * is unavailable.
 */
export function useChartInteractionMode(): ChartInteractionMode {
  const [mode, setMode] = useState<ChartInteractionMode>(resolveChartInteractionMode);

  useEffect(() => {
    const query = safeMatchMedia(HOVER_CAPABLE_MEDIA_QUERY);
    if (!query) {
      return;
    }
    const sync = () => setMode(query.matches ? "hover" : "click");
    sync();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", sync);
      return () => query.removeEventListener("change", sync);
    }
    if (typeof query.addListener === "function") {
      query.addListener(sync);
      return () => query.removeListener(sync);
    }
    return undefined;
  }, []);

  return mode;
}

// ---------------------------------------------------------------------------
// Shared tooltip panel
// ---------------------------------------------------------------------------

export type DatasetChartTooltipRow = {
  label: string;
  value: string;
};

export type DatasetChartTooltipModel = {
  title?: string;
  rows: DatasetChartTooltipRow[];
};

function isNonEmpty(value: string | undefined | null): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * The bounded Atlas-styled tooltip surface. Every semantic is carried as
 * readable label/value text -- never conveyed through color alone. Rows whose
 * label or value is empty/blank are omitted; when nothing readable remains the
 * panel renders nothing rather than an empty shell.
 */
export function DatasetChartTooltipPanel({ title, rows }: DatasetChartTooltipModel) {
  const safeRows = rows.filter((row) => isNonEmpty(row.label) && isNonEmpty(row.value));
  if (safeRows.length === 0) {
    return null;
  }
  return (
    <div className="dataset-chart-tooltip" role="status">
      {isNonEmpty(title) ? <p className="dataset-chart-tooltip__title">{title}</p> : null}
      <dl className="dataset-chart-tooltip__rows">
        {safeRows.map((row) => (
          <div className="dataset-chart-tooltip__row" key={row.label}>
            <dt className="dataset-chart-tooltip__row-label">{row.label}</dt>
            <dd className="dataset-chart-tooltip__row-value">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recharts adapter
// ---------------------------------------------------------------------------

type RechartsTooltipItem = {
  name?: string | number;
  value?: number | string;
  dataKey?: string | number;
  payload?: unknown;
};

export type ChartTooltipContext = {
  /** The primary hovered/selected datum (the first payload entry's row). */
  datum: Record<string, unknown>;
  /** The active category label, when the chart exposes one. */
  label: string | number | undefined;
  /** Every Recharts payload entry active at this point, in chart order. */
  items: RechartsTooltipItem[];
};

export type ChartTooltipResolver = (context: ChartTooltipContext) => DatasetChartTooltipModel | null;

type DatasetChartTooltipContentProps = {
  resolve: ChartTooltipResolver;
  active?: boolean;
  label?: string | number;
  payload?: RechartsTooltipItem[];
};

/**
 * The custom Recharts `content` renderer. Recharts clones this element with
 * `active`/`payload`/`label` injected. It hands the caller's resolver the
 * bounded datum context and renders whatever semantic rows the resolver
 * returns -- or nothing when the resolver declines (a non-observation point,
 * a malformed row).
 */
export function DatasetChartTooltipContent({ resolve, active, label, payload }: DatasetChartTooltipContentProps) {
  if (!active || !Array.isArray(payload) || payload.length === 0) {
    return null;
  }
  const primary = payload.find(
    (item) => item && typeof item.payload === "object" && item.payload !== null,
  );
  const datum = primary?.payload;
  if (!datum || typeof datum !== "object") {
    return null;
  }
  const model = resolve({ datum: datum as Record<string, unknown>, label, items: payload });
  if (!model) {
    return null;
  }
  return <DatasetChartTooltipPanel rows={model.rows} title={model.title} />;
}

export type DatasetChartTooltipProps = {
  trigger: "hover" | "click";
  isAnimationActive: false;
  content: ReactElement;
};

/**
 * Props to spread onto a Recharts `<Tooltip>` so it uses the shared Atlas
 * panel and the capability-resolved trigger. `<Tooltip>` must still be a
 * literal child of the chart for Recharts to wire it up -- this only supplies
 * its configuration.
 */
export function datasetChartTooltipProps(
  mode: ChartInteractionMode,
  resolve: ChartTooltipResolver,
): DatasetChartTooltipProps {
  return {
    trigger: mode === "hover" ? "hover" : "click",
    isAnimationActive: false,
    content: <DatasetChartTooltipContent resolve={resolve} />,
  };
}

// ---------------------------------------------------------------------------
// Bounded tooltip formatting helpers
// ---------------------------------------------------------------------------

/**
 * A finite numeric value for tooltip display, matching the shared
 * `maximumFractionDigits: 4` presentation the persistent legend lists already
 * use. Never rounds toward a different statistic -- it is display formatting
 * only.
 */
export function formatTooltipNumber(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/** An integer count for tooltip display, locale-grouped like the legends. */
export function formatTooltipCount(value: number): string {
  return value.toLocaleString();
}
