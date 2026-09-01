import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import DatasetCard, { type DatasetCardProps } from "../DatasetCard/DatasetCard";

export type HomeDatasetCarouselProps = {
  datasets: DatasetCardProps[];
};

// Project Spec S0286: one named autoplay cadence constant, not a magic
// number scattered across the scheduling effect and its tests.
const AUTOPLAY_INTERVAL_MS = 6000;

// Only absorbs browser sub-pixel rounding between scrollWidth/clientWidth --
// never a semantic threshold for "how much" overflow is real.
const OVERFLOW_TOLERANCE_PX = 1;

function getReducedMotionPreference(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Project Spec S0286: a small, Atlas-owned horizontal carousel for the Home
 * featured-dataset track. Owns only presentation/interaction -- it never
 * fetches `/datasets`, inspects registry/releases, or resolves capability
 * semantics; every `DatasetCardProps` entry arrives already governed by its
 * caller (HomePage). Exactly one `DatasetCard` renders per supplied dataset
 * -- looping wraps scroll position over that single logical track, it never
 * clones cards.
 */
export default function HomeDatasetCarousel({ datasets }: HomeDatasetCarouselProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Array<HTMLDivElement | null>>([]);
  const currentIndexRef = useRef(0);
  const autoplayTimerRef = useRef<number | null>(null);
  const userSuspendedRef = useRef(false);
  const reducedMotionRef = useRef(false);

  const [overflow, setOverflow] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(getReducedMotionPreference);

  const count = datasets.length;
  const showControls = overflow && count >= 2;

  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
  }, [reducedMotion]);

  // Reset bookkeeping whenever the logical dataset set itself changes
  // identity (a genuinely new Home mount/order), never on an unrelated
  // rerender -- `count` only changes across Home mounts in practice.
  useEffect(() => {
    currentIndexRef.current = 0;
  }, [count]);

  function measureOverflow() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const isOverflowing = viewport.scrollWidth > viewport.clientWidth + OVERFLOW_TOLERANCE_PX;
    setOverflow((previous) => (previous === isOverflowing ? previous : isOverflowing));
  }

  useEffect(() => {
    measureOverflow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    window.addEventListener("resize", measureOverflow);

    let resizeObserver: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined" && viewportRef.current) {
      resizeObserver = new ResizeObserver(() => measureOverflow());
      resizeObserver.observe(viewportRef.current);
    }

    return () => {
      window.removeEventListener("resize", measureOverflow);
      resizeObserver?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = (event: MediaQueryListEvent) => setReducedMotion(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  function clearAutoplayTimer() {
    if (autoplayTimerRef.current !== null) {
      window.clearInterval(autoplayTimerRef.current);
      autoplayTimerRef.current = null;
    }
  }

  function suspendAutoplay() {
    if (userSuspendedRef.current) {
      return;
    }
    userSuspendedRef.current = true;
    clearAutoplayTimer();
  }

  function scrollToIndex(index: number) {
    const viewport = viewportRef.current;
    const card = cardRefs.current[index];
    if (!viewport || !card) {
      return;
    }
    const left = card.offsetLeft;
    if (typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ left, behavior: reducedMotionRef.current ? "auto" : "smooth" });
    } else {
      // jsdom (the test DOM) does not implement Element.prototype.scrollTo.
      viewport.scrollLeft = left;
    }
  }

  function goToIndex(rawIndex: number) {
    if (count === 0) {
      return;
    }
    const normalized = ((rawIndex % count) + count) % count;
    currentIndexRef.current = normalized;
    scrollToIndex(normalized);
  }

  function stepForward() {
    goToIndex(currentIndexRef.current + 1);
  }

  function stepBackward() {
    goToIndex(currentIndexRef.current - 1);
  }

  // Project Spec S0286 Section 4.9: only ever schedule the timer while every
  // gate holds; unmount, losing overflow, gaining reduced motion, or the
  // first qualifying interaction (via suspendAutoplay's own immediate
  // clearAutoplayTimer call) each stop it -- no orphan interval survives.
  useEffect(() => {
    if (userSuspendedRef.current || !overflow || reducedMotion || count < 2) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      stepForward();
    }, AUTOPLAY_INTERVAL_MS);
    autoplayTimerRef.current = timer;

    return () => {
      window.clearInterval(timer);
      if (autoplayTimerRef.current === timer) {
        autoplayTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overflow, reducedMotion, count]);

  useEffect(() => clearAutoplayTimer, []);

  function handlePreviousClick() {
    suspendAutoplay();
    stepBackward();
  }

  function handleNextClick() {
    suspendAutoplay();
    stepForward();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      suspendAutoplay();
      stepBackward();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      suspendAutoplay();
      stepForward();
    }
  }

  // Any qualifying user-originated interaction (Section 1.O) permanently
  // suspends autoplay for this mount. Programmatic autoplay/manual-step
  // scrollTo calls never dispatch these DOM events themselves, so they never
  // self-suspend.
  function handleUserInteractionStart() {
    suspendAutoplay();
  }

  return (
    <div
      className="home-dataset-carousel"
      role="region"
      aria-roledescription="carousel"
      aria-label="Dataset studies carousel"
      onKeyDown={handleKeyDown}
      onFocusCapture={handleUserInteractionStart}
    >
      <div
        className="home-dataset-carousel__viewport"
        ref={viewportRef}
        onPointerDown={handleUserInteractionStart}
        onTouchStart={handleUserInteractionStart}
        onWheel={handleUserInteractionStart}
      >
        <div className="home-dataset-carousel__track" aria-live="off">
          {datasets.map((dataset, index) => (
            <div
              className="home-dataset-carousel__item"
              key={dataset.slug}
              ref={(element) => {
                cardRefs.current[index] = element;
              }}
            >
              <DatasetCard {...dataset} />
            </div>
          ))}
        </div>
      </div>

      {showControls && (
        <div className="home-dataset-carousel__controls">
          <button
            type="button"
            className="home-dataset-carousel__control home-dataset-carousel__control--prev"
            aria-label="Previous datasets"
            onClick={handlePreviousClick}
          >
            <span aria-hidden="true">‹</span>
          </button>
          <button
            type="button"
            className="home-dataset-carousel__control home-dataset-carousel__control--next"
            aria-label="Next datasets"
            onClick={handleNextClick}
          >
            <span aria-hidden="true">›</span>
          </button>
        </div>
      )}
    </div>
  );
}
