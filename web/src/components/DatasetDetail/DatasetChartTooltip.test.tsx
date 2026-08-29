import "@testing-library/jest-dom/vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// This project has no @types/node dependency; readFileSync resolves fine at
// test runtime via Node/Vite, so the missing ambient types are suppressed
// here rather than pulling in a new devDependency for one CSS-contract test.
// @ts-expect-error -- no @types/node in this project
import { readFileSync } from "node:fs";
declare const process: { cwd(): string };

import {
  DatasetChartTooltipContent,
  DatasetChartTooltipPanel,
  datasetChartTooltipProps,
  formatTooltipCount,
  formatTooltipNumber,
  resolveChartInteractionMode,
  useChartInteractionMode,
  type ChartTooltipResolver,
} from "./DatasetChartTooltip";

const HOVER_CAPABLE_MEDIA_QUERY = "(hover: hover) and (pointer: fine)";

type Listener = (event: MediaQueryListEvent) => void;

const originalMatchMedia = window.matchMedia;

/**
 * A controllable matchMedia double: it records every media string queried,
 * exposes whichever add/remove listener pair the test wants to allow, and can
 * flip `matches` and notify subscribers to simulate a real capability change.
 */
function installMatchMedia(
  initialMatches: boolean,
  options: { modernListeners?: boolean; legacyListeners?: boolean } = {},
) {
  const { modernListeners = true, legacyListeners = true } = options;
  const listeners = new Set<Listener>();
  const state = { matches: initialMatches };
  const queried: string[] = [];

  const mql: Record<string, unknown> = {
    get matches() {
      return state.matches;
    },
    media: HOVER_CAPABLE_MEDIA_QUERY,
    onchange: null,
    dispatchEvent: vi.fn(),
  };
  if (modernListeners) {
    mql.addEventListener = vi.fn((_type: string, cb: Listener) => listeners.add(cb));
    mql.removeEventListener = vi.fn((_type: string, cb: Listener) => listeners.delete(cb));
  }
  if (legacyListeners) {
    mql.addListener = vi.fn((cb: Listener) => listeners.add(cb));
    mql.removeListener = vi.fn((cb: Listener) => listeners.delete(cb));
  }

  const matchMedia = vi.fn((query: string) => {
    queried.push(query);
    return mql as unknown as MediaQueryList;
  });
  window.matchMedia = matchMedia as unknown as typeof window.matchMedia;

  return {
    mql,
    matchMedia,
    listeners,
    queried,
    setMatches(next: boolean) {
      act(() => {
        state.matches = next;
        for (const cb of [...listeners]) {
          cb({ matches: next } as MediaQueryListEvent);
        }
      });
    },
  };
}

afterEach(() => {
  window.matchMedia = originalMatchMedia;
  vi.restoreAllMocks();
});

describe("useChartInteractionMode / resolveChartInteractionMode capability resolution (S0277)", () => {
  it("resolves hover interaction for a fine pointer that can hover", () => {
    installMatchMedia(true);
    expect(resolveChartInteractionMode()).toBe("hover");
    const { result } = renderHook(() => useChartInteractionMode());
    expect(result.current).toBe("hover");
  });

  it("resolves click/tap interaction for a coarse or non-hover primary pointer", () => {
    const media = installMatchMedia(false);
    expect(resolveChartInteractionMode()).toBe("click");
    const { result } = renderHook(() => useChartInteractionMode());
    expect(result.current).toBe("click");
    // The capability query is used, never a viewport-width breakpoint.
    expect(media.queried).toContain(HOVER_CAPABLE_MEDIA_QUERY);
    expect(media.queried.join(" ")).not.toMatch(/width/);
  });

  it("falls back deterministically to click interaction when matchMedia is unavailable, without crashing", () => {
    // @ts-expect-error -- deliberately removing the API under test
    delete window.matchMedia;
    expect(resolveChartInteractionMode()).toBe("click");
    const { result } = renderHook(() => useChartInteractionMode());
    expect(result.current).toBe("click");
  });

  it("falls back to click interaction when matchMedia throws", () => {
    window.matchMedia = vi.fn(() => {
      throw new Error("matchMedia not supported in this context");
    }) as unknown as typeof window.matchMedia;
    expect(resolveChartInteractionMode()).toBe("click");
    const { result } = renderHook(() => useChartInteractionMode());
    expect(result.current).toBe("click");
  });

  it("updates the interaction mode when the media query changes, without remounting", () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useChartInteractionMode());
    expect(result.current).toBe("click");

    media.setMatches(true);
    expect(result.current).toBe("hover");

    media.setMatches(false);
    expect(result.current).toBe("click");
  });

  it("cleans up its media-query listener on unmount", () => {
    const media = installMatchMedia(true);
    const { unmount } = renderHook(() => useChartInteractionMode());
    expect(media.listeners.size).toBeGreaterThan(0);

    unmount();
    expect(media.listeners.size).toBe(0);
    expect(media.mql.removeEventListener).toHaveBeenCalled();
  });

  it("subscribes through the legacy addListener pair when the modern one is absent", () => {
    const media = installMatchMedia(false, { modernListeners: false });
    const { result, unmount } = renderHook(() => useChartInteractionMode());
    expect(media.mql.addListener).toHaveBeenCalled();

    media.setMatches(true);
    expect(result.current).toBe("hover");

    unmount();
    expect(media.mql.removeListener).toHaveBeenCalled();
    expect(media.listeners.size).toBe(0);
  });
});

describe("datasetChartTooltipProps trigger selection (S0277)", () => {
  it("maps hover capability to the Recharts hover trigger and click capability to the click trigger", () => {
    const resolve: ChartTooltipResolver = () => null;
    expect(datasetChartTooltipProps("hover", resolve).trigger).toBe("hover");
    expect(datasetChartTooltipProps("click", resolve).trigger).toBe("click");
    expect(datasetChartTooltipProps("hover", resolve).isAnimationActive).toBe(false);
  });
});

describe("DatasetChartTooltipPanel semantic rendering (S0277)", () => {
  it("renders a semantic title and label/value rows as readable text, not color-only", () => {
    render(
      <DatasetChartTooltipPanel
        rows={[
          { label: "Actual", value: "12.5" },
          { label: "Predicted", value: "11.8" },
          { label: "Observations", value: "1,024" },
        ]}
        title="Observation"
      />,
    );

    expect(screen.getByText("Observation")).toBeInTheDocument();
    for (const label of ["Actual", "Predicted", "Observations"]) {
      const term = screen.getByText(label);
      expect(term.tagName).toBe("DT");
      // Every semantic is carried by its own text label -- the value alone
      // (or a swatch color) is never the only signal.
      expect(term.nextElementSibling?.tagName).toBe("DD");
    }
    expect(screen.getByText("1,024")).toBeInTheDocument();
  });

  it("omits rows with an empty label or value", () => {
    render(
      <DatasetChartTooltipPanel
        rows={[
          { label: "Bin", value: "[0, 10)" },
          { label: "Count", value: "  " },
          { label: "", value: "orphaned" },
        ]}
      />,
    );

    expect(screen.getByText("Bin")).toBeInTheDocument();
    expect(screen.queryByText("Count")).not.toBeInTheDocument();
    expect(screen.queryByText("orphaned")).not.toBeInTheDocument();
  });

  it("renders nothing when no readable row survives", () => {
    const { container } = render(
      <DatasetChartTooltipPanel rows={[{ label: "Count", value: "" }]} title="   " />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DatasetChartTooltipContent Recharts adapter (S0277)", () => {
  const resolve: ChartTooltipResolver = ({ datum }) => {
    const name = typeof datum.name === "string" ? datum.name : null;
    const value = typeof datum.value === "number" ? datum.value : null;
    if (name === null || value === null) {
      return null;
    }
    return { title: name, rows: [{ label: "Count", value: String(value) }] };
  };

  it("renders nothing while inactive", () => {
    const { container } = render(
      <DatasetChartTooltipContent
        active={false}
        payload={[{ payload: { name: "Yes", value: 10 } }]}
        resolve={resolve}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the payload is empty", () => {
    const { container } = render(<DatasetChartTooltipContent active payload={[]} resolve={resolve} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the resolver's rows for an active datum", () => {
    render(
      <DatasetChartTooltipContent
        active
        payload={[{ payload: { name: "Yes", value: 10 } }]}
        resolve={resolve}
      />,
    );
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("Count")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("renders nothing when the resolver declines the datum", () => {
    const { container } = render(
      <DatasetChartTooltipContent
        active
        payload={[{ payload: { name: "Yes" } }]}
        resolve={resolve}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("bounded tooltip formatting helpers (S0277)", () => {
  it("formats numbers with the shared 4-fraction-digit presentation and counts as grouped integers", () => {
    expect(formatTooltipNumber(2.184712)).toBe("2.1847");
    expect(formatTooltipNumber(12)).toBe("12");
    expect(formatTooltipCount(1024)).toBe("1,024");
  });
});

// jsdom cannot compute the cascade of an external stylesheet, so the tooltip
// styling contract is asserted directly against the App.css source, matching
// the existing Dataset Detail CSS-contract tests in DatasetDetail.test.tsx.
describe("Dataset Detail chart tooltip CSS token contract (S0277)", () => {
  const appCss = readFileSync(`${process.cwd()}/src/App.css`, "utf8");

  function ruleBody(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = appCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for selector "${selector}"`).not.toBeNull();
    return match![1];
  }

  it("styles the tooltip surface entirely from existing Atlas tokens", () => {
    const body = ruleBody(".dataset-chart-tooltip");
    expect(body).toMatch(/var\(--atlas-color-surface\)/);
    expect(body).toMatch(/var\(--atlas-color-border-strong\)/);
    expect(body).toMatch(/var\(--atlas-radius-/);
    expect(body).toMatch(/var\(--atlas-shadow-/);
  });

  it("never hardcodes a hex/rgb/hsl color literal or a dataset-specific chart color", () => {
    for (const selector of [
      ".dataset-chart-tooltip",
      ".dataset-chart-tooltip__title",
      ".dataset-chart-tooltip__row-label",
      ".dataset-chart-tooltip__row-value",
    ]) {
      const body = ruleBody(selector);
      expect(body).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(body).not.toMatch(/\brgb\(|\brgba\(|\bhsl\(|\bhsla\(/);
      expect(body).not.toMatch(/--dataset-theme-chart-/);
    }
  });

  it("wraps long labels and bounds its width instead of overflowing the card", () => {
    const body = ruleBody(".dataset-chart-tooltip");
    expect(body).toMatch(/max-width:/);
    expect(ruleBody(".dataset-chart-tooltip__row-label")).toMatch(/overflow-wrap:\s*anywhere/);
  });
});
