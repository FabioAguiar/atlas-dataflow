import { useEffect, useState } from "react";
import type { DatasetCardProps } from "../components/DatasetCard/DatasetCard";
import HomeDatasetCarousel from "../components/HomeDatasetCarousel";
import { Card, EmptyState, ErrorState } from "../components/ui";
import { resolveDatasetIcon } from "../lib/datasetPresentation";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetListing = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
  display_title?: string | null;
  display_subtitle?: string | null;
  home_card_icon?: string | null;
  home_card_media_ref?: string | null;
  short_description?: string | null;
  problem_type?: string | null;
  model_display_name?: string | null;
  theme_preset?: string | null;
  performance_focus_id?: string | null;
};

type DatasetListingResponse = {
  datasets: DatasetListing[];
};

type HomeState =
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetListing[] }
  | { status: "error" };

// Project Spec S0286: one Fisher-Yates permutation over a copied array,
// applied exactly once at fetch-resolution time -- the source response array
// is never mutated in place, and this never re-runs from a rerender (nav
// toggle, resize, carousel autoplay ticks) because it only executes inside
// the fetch `.then` below, not in the render body.
function shuffleDatasets(datasets: DatasetListing[]): DatasetListing[] {
  const shuffled = [...datasets];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

function toCarouselCardProps(ds: DatasetListing): DatasetCardProps {
  return {
    slug: ds.dataset_slug,
    title: ds.display_title || ds.title || ds.dataset_slug,
    summary: ds.short_description || ds.display_subtitle || ds.summary,
    domain: ds.domain,
    tags: ds.tags,
    problemType: ds.problem_type ?? undefined,
    performanceFocusId: ds.performance_focus_id,
    modelDisplayName: ds.model_display_name,
    iconOverride: resolveDatasetIcon(ds.home_card_icon, ds.domain, ds.tags),
    mediaRef: ds.home_card_media_ref,
    themePreset: ds.theme_preset,
  };
}

export default function HomePage() {
  const [state, setState] = useState<HomeState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          setState({ status: "error" });
          return;
        }
        return res.json() as Promise<DatasetListingResponse>;
      })
      .then((data) => {
        if (data && Array.isArray(data.datasets)) {
          setState({ status: "ready", datasets: shuffleDatasets(data.datasets) });
          return;
        }
        if (data) {
          setState({ status: "error" });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <h1 id="home-title" className="hero__title">
          Atlas DataFlow<span className="hero__title-mark">.</span>
        </h1>
        <p className="hero__description">
          Explore governed dataset studies that bring together models, evaluation metrics, interactive
          visualizations, technical documentation, and capability-specific prediction or evaluation experiences.
        </p>
      </section>

      <section className="featured-datasets" aria-labelledby="featured-title">
        <div className="featured-datasets__heading">
          <h2 id="featured-title">Dataset studies</h2>
          <p>
            Browse the public studies currently available in Atlas. Each card opens a release-backed view of the
            dataset, its analytical evidence, and the experience supported by its predictive capability.
          </p>
        </div>

        {state.status === "loading" && (
          <Card aria-label="Loading datasets">
            <p>Loading datasets...</p>
          </Card>
        )}

        {state.status === "error" && (
          <ErrorState
            title="Datasets unavailable"
            message="The dataset catalog could not be loaded. Please try again later."
          />
        )}

        {state.status === "ready" &&
          (state.datasets.length === 0 ? (
            <EmptyState title="No datasets available" message="Published datasets will appear here." />
          ) : (
            <HomeDatasetCarousel datasets={state.datasets.map(toCarouselCardProps)} />
          ))}
      </section>

      <footer className="site-footer">
        Atlas DataFlow is a project by <strong className="site-footer__highlight">Fábio Aguiar</strong>.
      </footer>
    </>
  );
}
