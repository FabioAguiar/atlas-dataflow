import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetCardProps } from "../DatasetCard/DatasetCard";
import HomeDatasetCarousel from "./HomeDatasetCarousel";

function mockMatchMedia(reducedMotion: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reducedMotion : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function buildDataset(slug: string, title = slug): DatasetCardProps {
  return { slug, title, summary: `${title} summary`, domain: "synthetic", tags: [] };
}

function renderCarousel(datasets: DatasetCardProps[]) {
  return render(
    <MemoryRouter>
      <HomeDatasetCarousel datasets={datasets} />
    </MemoryRouter>,
  );
}

// Project Spec S0286: HomeDatasetCarousel.test.tsx must use fake timers and
// deterministic geometry mocks, since jsdom performs no real layout --
// scrollWidth/clientWidth/offsetLeft are always 0 unless stubbed directly on
// the rendered elements, and window "resize" is the component's own hook for
// re-measuring after a stub changes (the same path a real ResizeObserver-less
// environment falls back to).
function stubGeometry(
  container: HTMLElement,
  { clientWidth, itemWidth }: { clientWidth: number; itemWidth: number },
) {
  const viewport = container.querySelector(".home-dataset-carousel__viewport") as HTMLElement;
  const items = Array.from(container.querySelectorAll<HTMLElement>(".home-dataset-carousel__item"));

  Object.defineProperty(viewport, "clientWidth", { configurable: true, value: clientWidth });
  Object.defineProperty(viewport, "scrollWidth", { configurable: true, value: itemWidth * items.length });
  items.forEach((item, index) => {
    Object.defineProperty(item, "offsetLeft", { configurable: true, value: index * itemWidth });
    Object.defineProperty(item, "offsetWidth", { configurable: true, value: itemWidth });
  });

  return { viewport, items };
}

function triggerResize() {
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

const THREE_DATASETS = [buildDataset("alpha"), buildDataset("beta"), buildDataset("gamma")];

describe("HomeDatasetCarousel overflow gate (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders no controls and schedules no autoplay timer when the track does not overflow", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 1000, itemWidth: 200 });
    triggerResize();

    expect(screen.queryByLabelText("Previous datasets")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Next datasets")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("renders no controls or autoplay for exactly one dataset, even if it measures as overflowing", () => {
    const { container } = renderCarousel([buildDataset("solo")]);
    const { viewport } = stubGeometry(container, { clientWidth: 100, itemWidth: 500 });
    triggerResize();

    expect(screen.queryByLabelText("Previous datasets")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Next datasets")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("shows Previous/Next controls once real overflow is measured", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    expect(screen.getByLabelText("Previous datasets")).toBeInTheDocument();
    expect(screen.getByLabelText("Next datasets")).toBeInTheDocument();
  });

  it("renders exactly one logical item per supplied dataset, never a clone", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    expect(container.querySelectorAll(".home-dataset-carousel__item")).toHaveLength(3);
  });
});

describe("HomeDatasetCarousel autoplay cadence and wrap (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("advances exactly one logical step every 6000ms while eligible", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(200);

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(400);
  });

  it("does not step before the 6000ms cadence elapses", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("wraps cyclically from the final logical position back to the first, without cloning cards", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(400);

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(0);
    expect(container.querySelectorAll(".home-dataset-carousel__item")).toHaveLength(3);
  });

  it("does not self-suspend from its own programmatic autoplay steps -- three consecutive ticks all fire", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    act(() => {
      vi.advanceTimersByTime(18000);
    });

    // Three eligible ticks over three cards land back at the start.
    expect(viewport.scrollLeft).toBe(0);
  });
});

describe("HomeDatasetCarousel manual navigation (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("steps forward and backward via the Next/Previous controls, wrapping cyclically", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.click(screen.getByLabelText("Next datasets"));
    expect(viewport.scrollLeft).toBe(200);

    fireEvent.click(screen.getByLabelText("Previous datasets"));
    expect(viewport.scrollLeft).toBe(0);

    fireEvent.click(screen.getByLabelText("Previous datasets"));
    expect(viewport.scrollLeft).toBe(400);
  });

  it("steps forward and backward via ArrowRight/ArrowLeft when the carousel region has focus", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    const region = screen.getByRole("region", { name: /carousel/i });
    fireEvent.keyDown(region, { key: "ArrowRight" });
    expect(viewport.scrollLeft).toBe(200);

    fireEvent.keyDown(region, { key: "ArrowLeft" });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("never moves keyboard focus during an automatic autoplay step", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    (document.activeElement as HTMLElement | null)?.blur();
    const activeBefore = document.activeElement;

    act(() => {
      vi.advanceTimersByTime(6000);
    });

    expect(document.activeElement).toBe(activeBefore);
  });
});

describe("HomeDatasetCarousel interaction suspension (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("permanently suspends autoplay after Next/Previous activation", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.click(screen.getByLabelText("Next datasets"));
    expect(viewport.scrollLeft).toBe(200);

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(200);
  });

  it("permanently suspends autoplay after ArrowLeft/ArrowRight activation", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.keyDown(screen.getByRole("region", { name: /carousel/i }), { key: "ArrowRight" });
    expect(viewport.scrollLeft).toBe(200);

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(200);
  });

  it("permanently suspends autoplay on pointerdown over the track", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.pointerDown(viewport);

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("permanently suspends autoplay on wheel interaction over the track", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.wheel(viewport);

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("permanently suspends autoplay when focus enters an interactive carousel control", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.focus(screen.getByLabelText("Next datasets"));

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("does not reset the suspension flag on resize", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.click(screen.getByLabelText("Next datasets"));
    expect(viewport.scrollLeft).toBe(200);

    triggerResize();

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(200);
  });
});

describe("HomeDatasetCarousel reduced motion (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("schedules no autoplay timer under prefers-reduced-motion: reduce", () => {
    mockMatchMedia(true);
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    act(() => {
      vi.advanceTimersByTime(24000);
    });
    expect(viewport.scrollLeft).toBe(0);
  });

  it("keeps manual Previous/Next controls available under reduced motion when overflow exists", () => {
    mockMatchMedia(true);
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    expect(screen.getByLabelText("Previous datasets")).toBeInTheDocument();
    expect(screen.getByLabelText("Next datasets")).toBeInTheDocument();
  });

  it("still steps manually under reduced motion", () => {
    mockMatchMedia(true);
    const { container } = renderCarousel(THREE_DATASETS);
    const { viewport } = stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    fireEvent.click(screen.getByLabelText("Next datasets"));
    expect(viewport.scrollLeft).toBe(200);
  });
});

describe("HomeDatasetCarousel resize reconciliation (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows controls and resumes eligible autoplay when resize enters overflow, and clears both when resize leaves overflow", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    const viewport = container.querySelector(".home-dataset-carousel__viewport") as HTMLElement;
    const items = Array.from(container.querySelectorAll<HTMLElement>(".home-dataset-carousel__item"));
    items.forEach((item, index) => {
      Object.defineProperty(item, "offsetLeft", { configurable: true, value: index * 200 });
    });

    Object.defineProperty(viewport, "clientWidth", { configurable: true, value: 1000 });
    Object.defineProperty(viewport, "scrollWidth", { configurable: true, value: 600 });
    triggerResize();
    expect(screen.queryByLabelText("Next datasets")).not.toBeInTheDocument();

    Object.defineProperty(viewport, "clientWidth", { configurable: true, value: 300 });
    triggerResize();
    expect(screen.getByLabelText("Next datasets")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(viewport.scrollLeft).toBe(200);

    Object.defineProperty(viewport, "clientWidth", { configurable: true, value: 1000 });
    triggerResize();
    expect(screen.queryByLabelText("Next datasets")).not.toBeInTheDocument();

    const scrollLeftAfterLosingOverflow = viewport.scrollLeft;
    act(() => {
      vi.advanceTimersByTime(12000);
    });
    expect(viewport.scrollLeft).toBe(scrollLeftAfterLosingOverflow);
  });
});

describe("HomeDatasetCarousel unmount cleanup (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("clears the autoplay timer on unmount, leaving no orphan interval", () => {
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const { container, unmount } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(24000);
      });
    }).not.toThrow();
  });

  it("removes its window resize listener on unmount", () => {
    const removeEventListenerSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderCarousel(THREE_DATASETS);

    unmount();

    expect(removeEventListenerSpy.mock.calls.some(([eventName]) => eventName === "resize")).toBe(true);
  });
});

describe("HomeDatasetCarousel accessibility (Project Spec S0286)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("exposes an accessible carousel region name and English control labels", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    expect(screen.getByRole("region", { name: /carousel/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Previous datasets")).toBeInTheDocument();
    expect(screen.getByLabelText("Next datasets")).toBeInTheDocument();
  });

  it("keeps every dataset card's link individually keyboard reachable", () => {
    const { container } = renderCarousel(THREE_DATASETS);
    stubGeometry(container, { clientWidth: 300, itemWidth: 200 });
    triggerResize();

    for (const dataset of THREE_DATASETS) {
      expect(screen.getByRole("link", { name: `Explore dataset ${dataset.title}` })).toHaveAttribute(
        "href",
        `/dataset/${dataset.slug}`,
      );
    }
  });
});
