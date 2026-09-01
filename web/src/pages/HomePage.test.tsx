import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DATASET_THEME_PRESETS,
  DATASET_THEME_TOKEN_NAMES,
  datasetThemeStyle,
  resolveDatasetThemePreset,
} from "../lib/datasetPresentation";
import HomePage from "./HomePage";

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

type DatasetListingFixture = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
  problem_type?: string | null;
  model_display_name?: string | null;
  home_card_icon?: string | null;
  home_card_media_ref?: string | null;
  short_description?: string | null;
  theme_preset?: string | null;
  performance_focus_id?: string | null;
};

// Mirrors the real GET /datasets response envelope confirmed at
// api/main.py's list_datasets_endpoint ({"datasets": [...]}) -- not
// App.test.tsx's own /datasets mock, which returns a bare array and is
// never exercised through HomePage.
function installDatasetsFetchMock(datasets: DatasetListingFixture[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith("/datasets")) {
      return jsonResponse({ datasets });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderHomePage() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <HomePage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// Project Spec S0286: the obsolete Portuguese eyebrow and hero actions are
// gone; the exact new English hero/featured copy renders in their place.
describe("HomePage editorial presentation (Project Spec S0286)", () => {
  it("renders the exact English hero copy without the obsolete eyebrow or hero actions", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();

    expect(await screen.findByRole("heading", { name: /Atlas DataFlow/i, level: 1 })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Explore governed dataset studies that bring together models, evaluation metrics, interactive visualizations, technical documentation, and capability-specific prediction or evaluation experiences.",
      ),
    ).toBeInTheDocument();

    expect(screen.queryByText(/DEMONSTRAÇÕES PÚBLICAS/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Repositório/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Voltar ao Portfólio/)).not.toBeInTheDocument();
  });

  it("renders the exact English featured heading and paragraph", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();

    expect(await screen.findByRole("heading", { name: "Dataset studies" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Browse the public studies currently available in Atlas. Each card opens a release-backed view of the dataset, its analytical evidence, and the experience supported by its predictive capability.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Datasets em destaque")).not.toBeInTheDocument();
  });

  it("renders English loading, error and empty state copy", async () => {
    let resolveFetch: (() => void) | null = null;
    const pending = new Promise<void>((resolve) => {
      resolveFetch = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await pending;
        return jsonResponse({ datasets: [] });
      }),
    );

    renderHomePage();

    expect(screen.getByLabelText("Loading datasets")).toBeInTheDocument();
    expect(screen.getByText("Loading datasets...")).toBeInTheDocument();
    expect(screen.queryByText("Carregando datasets...")).not.toBeInTheDocument();

    resolveFetch!();
    expect(await screen.findByText("No datasets available")).toBeInTheDocument();
    expect(screen.getByText("Published datasets will appear here.")).toBeInTheDocument();
    expect(screen.queryByText("Nenhum dataset disponível")).not.toBeInTheDocument();
  });

  it("renders English error state copy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({}, 500)),
    );

    renderHomePage();

    expect(await screen.findByText("Datasets unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("The dataset catalog could not be loaded. Please try again later."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Datasets indisponíveis")).not.toBeInTheDocument();
  });

  it("renders English footer copy", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();
    await screen.findByText("No datasets available");

    expect(screen.getByText(/Atlas DataFlow is a project by/)).toBeInTheDocument();
    expect(screen.getByText("Fábio Aguiar")).toBeInTheDocument();
  });
});

describe("HomePage dataset-count states", () => {
  it("renders the empty state for zero published datasets", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();

    expect(await screen.findByText("No datasets available")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Explore dataset/ })).not.toBeInTheDocument();
  });

  it("renders a single dataset card for exactly one published dataset", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-demo-dataset",
        title: "Synthetic Demo Dataset",
        summary: "A synthetic, non-Telco/Bank dataset used only for this proof test.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Synthetic Demo Dataset")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Explore dataset/ })).toHaveLength(1);
    expect(screen.queryByText("No datasets available")).not.toBeInTheDocument();
  });

  it("renders every card with no hardcoded upper bound for multiple published datasets, each represented exactly once", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-demo-dataset-one",
        title: "Synthetic Demo Dataset One",
        summary: "First synthetic dataset for the many-dataset proof.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
      },
      {
        dataset_slug: "synthetic-demo-dataset-two",
        title: "Synthetic Demo Dataset Two",
        summary: "Second synthetic dataset for the many-dataset proof.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
      },
      {
        dataset_slug: "synthetic-demo-dataset-three",
        title: "Synthetic Demo Dataset Three",
        summary: "Third synthetic dataset for the many-dataset proof.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Synthetic Demo Dataset One")).toBeInTheDocument();
    expect(screen.getByText("Synthetic Demo Dataset Two")).toBeInTheDocument();
    expect(screen.getByText("Synthetic Demo Dataset Three")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Explore dataset/ })).toHaveLength(3);
  });
});

// Project Spec S0286: shuffle exactly once per Home mount, on a copied
// array, using Math.random as the stubbed randomness source -- ordinary
// rerenders never reshuffle an already-ready mount.
describe("HomePage dataset order randomization (Project Spec S0286)", () => {
  const orderedDatasets: DatasetListingFixture[] = [
    { dataset_slug: "alpha", title: "Alpha", summary: "Alpha summary", domain: "synthetic", visibility: "public", tags: [] },
    { dataset_slug: "beta", title: "Beta", summary: "Beta summary", domain: "synthetic", visibility: "public", tags: [] },
    { dataset_slug: "gamma", title: "Gamma", summary: "Gamma summary", domain: "synthetic", visibility: "public", tags: [] },
    { dataset_slug: "delta", title: "Delta", summary: "Delta summary", domain: "synthetic", visibility: "public", tags: [] },
  ];

  function readSlugOrder(container: HTMLElement) {
    return Array.from(container.querySelectorAll<HTMLElement>(".dataset-card__link-overlay")).map((link) =>
      link.getAttribute("href")?.replace("/dataset/", ""),
    );
  }

  it("represents every dataset exactly once regardless of shuffle order", async () => {
    installDatasetsFetchMock(orderedDatasets);
    vi.spyOn(Math, "random").mockReturnValue(0.999);

    const { container } = renderHomePage();
    await screen.findByText("Alpha");

    expect(readSlugOrder(container).slice().sort()).toEqual(["alpha", "beta", "delta", "gamma"]);
  });

  it("applies a deterministic stubbed permutation, proving the order actually changed from source order", async () => {
    installDatasetsFetchMock(orderedDatasets);
    // Fisher-Yates with a constant Math.random() of 0 always picks j=0, so
    // each pass swaps the current index i with index 0 -- a real,
    // deterministic permutation distinct from the source
    // ["alpha","beta","gamma","delta"] order.
    vi.spyOn(Math, "random").mockReturnValue(0);

    const { container } = renderHomePage();
    await screen.findByText("Alpha");

    expect(readSlugOrder(container)).toEqual(["beta", "gamma", "delta", "alpha"]);
  });

  it("does not mutate the source fetch response array", async () => {
    const datasets = orderedDatasets.map((ds) => ({ ...ds }));
    const originalOrder = datasets.map((ds) => ds.dataset_slug);
    installDatasetsFetchMock(datasets);
    vi.spyOn(Math, "random").mockReturnValue(0);

    renderHomePage();
    await screen.findByText("Alpha");

    expect(datasets.map((ds) => ds.dataset_slug)).toEqual(originalOrder);
  });

  it("keeps a stable order through ordinary rerenders of the same mount", async () => {
    installDatasetsFetchMock(orderedDatasets);
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0);

    const { container, rerender } = renderHomePage();
    await screen.findByText("Alpha");
    const firstOrder = readSlugOrder(container);

    randomSpy.mockReturnValue(0.999);
    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <HomePage />
      </MemoryRouter>,
    );

    // Rerendering the same HomePage instance must not reshuffle -- the
    // shuffle only ever runs once, inside the fetch resolution, not in the
    // render body.
    expect(readSlugOrder(container)).toEqual(firstOrder);
  });
});

describe("shared dataset theme rendering contract", () => {
  it("defines every semantic token for all 30 controlled presets and falls back closed", () => {
    expect(DATASET_THEME_PRESETS).toHaveLength(30);
    for (const preset of DATASET_THEME_PRESETS) {
      expect(Object.keys(preset.tokens).sort()).toEqual([...DATASET_THEME_TOKEN_NAMES].sort());
      expect(Object.values(preset.tokens).every(Boolean)).toBe(true);
    }

    expect(resolveDatasetThemePreset(undefined).id).toBe("atlas-green");
    expect(resolveDatasetThemePreset("").id).toBe("atlas-green");
    expect(resolveDatasetThemePreset("custom-rainbow").id).toBe("atlas-green");
    expect(datasetThemeStyle("monochrome-dark")["--dataset-theme-canvas"])
      .not.toBe(datasetThemeStyle("atlas-green")["--dataset-theme-canvas"]);
    expect(datasetThemeStyle("cyber-neon")["--dataset-theme-chart-secondary"])
      .not.toBe(datasetThemeStyle("ice-blue")["--dataset-theme-chart-secondary"]);
  });

  it("scopes different published themes to sibling Home cards without leaking to the carousel track", async () => {
    installDatasetsFetchMock([
      { dataset_slug: "ocean", title: "Ocean dataset", summary: "Ocean", domain: "demo", visibility: "public", tags: [], theme_preset: "ocean-blue" },
      { dataset_slug: "terminal", title: "Terminal dataset", summary: "Terminal", domain: "demo", visibility: "public", tags: [], theme_preset: "retro-terminal" },
      { dataset_slug: "fallback", title: "Fallback dataset", summary: "Fallback", domain: "demo", visibility: "public", tags: [], theme_preset: "unsupported" },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Ocean dataset");
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".dataset-card"));

    expect(cards.map((card) => card.dataset.themePreset).sort()).toEqual(["atlas-green", "ocean-blue", "retro-terminal"]);
    expect(cards[0].style.getPropertyValue("--dataset-theme-canvas"))
      .not.toBe(cards[1].style.getPropertyValue("--dataset-theme-canvas"));
    expect(container.querySelector(".home-dataset-carousel")).not.toHaveAttribute("data-theme-preset");
  });
});

// Mirrors DatasetCard.tsx's DATASET_ICONS path data so tests can prove which
// icon actually rendered -- this component has no test-id convention
// distinguishing TelecomIcon/BankIcon/GenericDatasetIcon in the DOM today.
const TELECOM_ICON_PATH_D =
  "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a4.5 4.5 0 0 1 9 0m-1.5-5.5A5.5 5.5 0 0 1 20.5 19";
const BANK_ICON_PATH_D = "M4 10h16L12 5 4 10Zm2 0v8m4-8v8m4-8v8m4-8v8M4 19h16";
const NEW_ICON_PATHS: Record<string, string> = {
  "money-dollar": "M15 8.5c-.7-.7-1.7-1-3-1-1.7 0-3 .9-3 2.2 0 3.5 6 1.4 6 4.8 0 1.4-1.3 2.3-3 2.3-1.3 0-2.5-.4-3.3-1.2M12 5.5v13",
  globe: "M3 12h18M12 3c2.4 2.5 3.5 5.5 3.5 9S14.4 18.5 12 21c-2.4-2.5-3.5-5.5-3.5-9S9.6 5.5 12 3Z",
  flask: "M9 3h6m-5 0v6l-5.5 9.2A1.8 1.8 0 0 0 6 21h12a1.8 1.8 0 0 0 1.5-2.8L14 9V3M7 15h10",
  "cpu-chip": "M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4",
};

describe("HomePage problem_type and curated icon rendering", () => {
  it("renders a published Home card media reference instead of icon mode", async () => {
    installDatasetsFetchMock([{
      dataset_slug: "media-card-dataset",
      title: "Media Card Dataset",
      summary: "Published media card",
      domain: "synthetic",
      visibility: "public",
      tags: [],
      home_card_icon: "heart",
      home_card_media_ref: "/media/home-cards/published.webp",
    }]);

    const { container } = renderHomePage();
    await screen.findByText("Media Card Dataset");

    expect(screen.getByTestId("home-card-media")).toHaveStyle({ backgroundImage: 'url("/media/home-cards/published.webp")' });
    expect(screen.getByTestId("home-card-media-gradient")).toBeInTheDocument();
    expect(screen.getByTestId("home-card-frame")).toBeInTheDocument();
    expect(screen.getByTestId("home-card-media").closest(".dataset-card")).toHaveClass("dataset-card--image");
    expect(container.querySelector(".dataset-card__icon")).not.toBeInTheDocument();
  });

  it("prefers a curated home_card_icon over the domain/tags keyword-derived fallback", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-curated-icon-dataset",
        title: "Synthetic Curated Icon Dataset",
        summary: "Domain keywords would suggest telecom, but home_card_icon is curated as bank.",
        domain: "telecom",
        visibility: "public",
        tags: ["telecom"],
        home_card_icon: "bank",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Synthetic Curated Icon Dataset");

    const iconPath = container.querySelector(".dataset-card__icon path");
    expect(iconPath?.getAttribute("d")).toBe(BANK_ICON_PATH_D);
  });

  it("falls back to the domain/tags keyword-derived icon when no curated home_card_icon is present", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-fallback-icon-dataset",
        title: "Synthetic Fallback Icon Dataset",
        summary: "No curated home_card_icon; domain keywords should drive the fallback.",
        domain: "telecom",
        visibility: "public",
        tags: ["telecom"],
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Synthetic Fallback Icon Dataset");

    const iconPath = container.querySelector(".dataset-card__icon path");
    expect(iconPath?.getAttribute("d")).toBe(TELECOM_ICON_PATH_D);
  });

  it.each(Object.entries(NEW_ICON_PATHS))("renders the new %s icon without the generic fallback", async (icon, expectedPath) => {
    installDatasetsFetchMock([{
      dataset_slug: `${icon}-dataset`,
      title: `${icon} dataset`,
      summary: "New curated icon",
      domain: "synthetic",
      visibility: "public",
      tags: [],
      home_card_icon: icon,
    }]);

    const { container } = renderHomePage();
    await screen.findByText(`${icon} dataset`);
    const paths = Array.from(container.querySelectorAll(".dataset-card__icon path"));
    expect(paths.some((path) => path.getAttribute("d") === expectedPath)).toBe(true);
  });

  it("falls back safely when a published icon ID is unknown", async () => {
    installDatasetsFetchMock([{
      dataset_slug: "unknown-icon-dataset",
      title: "Unknown icon dataset",
      summary: "Unknown curated icon",
      domain: "telecom",
      visibility: "public",
      tags: [],
      home_card_icon: "not-a-controlled-icon",
    }]);

    const { container } = renderHomePage();
    await screen.findByText("Unknown icon dataset");
    expect(container.querySelector(".dataset-card__icon path")?.getAttribute("d")).toBe(TELECOM_ICON_PATH_D);
  });
});

// S0017: a ready, real-shaped telco-customer-churn listing entry (matching
// registry/datasets.json's actual seeded dataset) must render from the
// listing payload/presentation helpers alone, not from hardcoded Telco
// mock copy in HomePage.tsx itself.
describe("HomePage Telco-like ready dataset listing (S0017)", () => {
  it("renders the telco-customer-churn dataset card from the listing payload with no curated overrides", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "telco-customer-churn",
        title: "Telco Customer Churn",
        summary: "Customer churn prediction dataset for a telecommunications provider.",
        domain: "telco",
        visibility: "public",
        tags: ["telco", "churn", "classification"],
        problem_type: "binary_classification",
      },
    ]);

    const { container } = renderHomePage();

    expect(await screen.findByText("Telco Customer Churn")).toBeInTheDocument();
    expect(
      screen.queryByText("Customer churn prediction dataset for a telecommunications provider."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Explore dataset/ })).toHaveAttribute(
      "href",
      "/dataset/telco-customer-churn",
    );

    // domain "telco" is not in DOMAIN_ICON_RULES' keyword list ("telecom"/
    // "telco" both match "telco" today via datasetPresentation.ts's keyword
    // substring check), and there is no curated home_card_icon in this
    // payload, so the icon must come from the deterministic domain/tags
    // fallback, not an invented per-dataset value.
    const iconPath = container.querySelector(".dataset-card__icon path");
    expect(iconPath?.getAttribute("d")).toBe(TELECOM_ICON_PATH_D);
  });

  it("renders a published Home card description but not the legacy long fallback", async () => {
    const legacyFallback = "Customer churn prediction dataset for a telecommunications provider. Predicts whether a customer will churn based on service usage and account features.";
    installDatasetsFetchMock([
      {
        dataset_slug: "telco-customer-churn",
        title: "Telco Customer Churn",
        summary: legacyFallback,
        domain: "telco",
        visibility: "public",
        tags: ["telco"],
      },
      {
        dataset_slug: "curated-description",
        title: "Curated description",
        summary: "Canonical summary that must not replace curated copy",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        short_description: "Explicitly published Home card description",
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Explicitly published Home card description")).toBeInTheDocument();
    expect(screen.queryByText(legacyFallback)).not.toBeInTheDocument();
  });
});

// Project Spec S0286: DatasetCard no longer renders the Problem / Performance
// Focus / Model badge triad on Home -- governed projection stays intact
// (proven by livePreviewProjection's own untouched tests), only the Home
// Card's own presentation of it is gone.
describe("HomePage Dataset identity badge removal (Project Spec S0286)", () => {
  it("renders no Problem, Performance focus, or Model badge even when every value is known", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "triad-dataset",
        title: "Triad Dataset",
        summary: "Dataset with problem_type, performance_focus_id, and model_display_name.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "continuous_regression",
        performance_focus_id: "regression_performance",
        model_display_name: "HistGradientBoosting",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Triad Dataset");

    expect(screen.queryByText("Continuous Regression")).not.toBeInTheDocument();
    expect(screen.queryByText("Regression performance")).not.toBeInTheDocument();
    expect(screen.queryByText("HistGradientBoosting")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-card__badges")).not.toBeInTheDocument();
    expect(container.querySelector(".dataset-identity-badges")).not.toBeInTheDocument();
  });

  it("never issues a per-card /contract or /model-card request now that no badge needs a model name", async () => {
    const fetchMock = installDatasetsFetchMock([
      {
        dataset_slug: "triad-dataset-a",
        title: "Triad Dataset A",
        summary: "First dataset.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        model_display_name: "Model A",
      },
      {
        dataset_slug: "triad-dataset-b",
        title: "Triad Dataset B",
        summary: "Second dataset.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        model_display_name: "Model B",
      },
    ]);

    renderHomePage();
    await screen.findByText("Triad Dataset A");
    await screen.findByText("Triad Dataset B");

    expect(fetchMock.mock.calls).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/datasets$/);
  });

  it("leaves other Home Card content unchanged now that badges are gone", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "focused-dataset-content",
        title: "Focused Dataset Content",
        summary: "Regression-proof summary text.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
        performance_focus_id: "overall_discrimination",
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Focused Dataset Content")).toBeInTheDocument();
    expect(screen.getByText("Regression-proof summary text.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Explore dataset/ })).toHaveAttribute(
      "href",
      "/dataset/focused-dataset-content",
    );
  });
});

// Project Spec S0286: featured datasets render through HomeDatasetCarousel,
// not the retired static featured-datasets__grid.
describe("HomePage carousel wiring (Project Spec S0286)", () => {
  it("renders ready nonempty datasets through HomeDatasetCarousel", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "carousel-dataset",
        title: "Carousel Dataset",
        summary: "Rendered through the carousel.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Carousel Dataset");

    expect(container.querySelector(".home-dataset-carousel")).toBeInTheDocument();
    expect(container.querySelector(".featured-datasets__grid")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: /carousel/i })).toBeInTheDocument();
  });
});
