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
});

describe("HomePage dataset-count states", () => {
  it("renders the empty state for zero published datasets", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();

    expect(await screen.findByText("Nenhum dataset disponível")).toBeInTheDocument();
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
    expect(screen.queryByText("Nenhum dataset disponível")).not.toBeInTheDocument();
  });

  it("renders every card with no hardcoded upper bound for multiple published datasets", async () => {
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

  it("scopes different published themes to sibling Home cards without leaking to the grid", async () => {
    installDatasetsFetchMock([
      { dataset_slug: "ocean", title: "Ocean dataset", summary: "Ocean", domain: "demo", visibility: "public", tags: [], theme_preset: "ocean-blue" },
      { dataset_slug: "terminal", title: "Terminal dataset", summary: "Terminal", domain: "demo", visibility: "public", tags: [], theme_preset: "retro-terminal" },
      { dataset_slug: "fallback", title: "Fallback dataset", summary: "Fallback", domain: "demo", visibility: "public", tags: [], theme_preset: "unsupported" },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Ocean dataset");
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".dataset-card"));

    expect(cards.map((card) => card.dataset.themePreset)).toEqual(["ocean-blue", "retro-terminal", "atlas-green"]);
    expect(cards[0].style.getPropertyValue("--dataset-theme-canvas"))
      .not.toBe(cards[1].style.getPropertyValue("--dataset-theme-canvas"));
    expect(container.querySelector(".featured-datasets__grid")).not.toHaveAttribute("data-theme-preset");
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

  it("renders the real analysis-type label when problem_type is present", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-classification-dataset",
        title: "Synthetic Classification Dataset",
        summary: "Synthetic dataset with a curated problem_type.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
        problem_type: "binary_classification",
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
  });

  it("falls back to the default analysis-type label when problem_type is absent", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "synthetic-no-problem-type-dataset",
        title: "Synthetic No Problem Type Dataset",
        summary: "Synthetic dataset with no curated problem_type.",
        domain: "synthetic",
        visibility: "public",
        tags: ["synthetic"],
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Predictive Analysis")).toBeInTheDocument();
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
    expect(screen.getByText("Binary Classification")).toBeInTheDocument();
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

// Project Spec S0204: public Home Card badge projection for
// performance_focus_id, sourced only from the /datasets listing (never
// derived from tags or problem_type).
describe("HomePage Performance focus badge (Project Spec S0204)", () => {
  it("renders both the problem-type and Performance focus badges when both are known", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "focused-dataset",
        title: "Focused Dataset",
        summary: "Dataset with both problem_type and performance_focus_id.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
        performance_focus_id: "overall_discrimination",
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Binary Classification")).toBeInTheDocument();
    expect(screen.getByText("Overall discrimination")).toBeInTheDocument();
  });

  it("preserves the original single problem-type badge when performance_focus_id is missing", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "no-focus-dataset",
        title: "No Focus Dataset",
        summary: "Dataset with problem_type but no performance_focus_id.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("No Focus Dataset");

    expect(screen.getByText("Binary Classification")).toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-card__badges .atlas-badge")).toHaveLength(1);
  });

  it("renders no invented second badge for an unknown performance_focus_id", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "unknown-focus-dataset",
        title: "Unknown Focus Dataset",
        summary: "Dataset with an unrecognized performance_focus_id.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
        performance_focus_id: "not_a_real_focus",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Unknown Focus Dataset");

    expect(screen.getByText("Binary Classification")).toBeInTheDocument();
    expect(container.querySelectorAll(".dataset-card__badges .atlas-badge")).toHaveLength(1);
  });

  it("leaves other Home Card content unchanged alongside the new badge", async () => {
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

// Project Spec S0238: the release-bound Model badge joins the existing
// problem/focus pair into a fixed three-role triad, sourced only from the
// API's own bounded model_display_name field -- never a per-card /contract
// or /model-card request.
describe("HomePage Dataset identity badge triad (Project Spec S0238)", () => {
  it("renders the problem, focus, and model badges in that exact order when all three authorities are available", async () => {
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

    const badges = Array.from(container.querySelectorAll(".dataset-card__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual([
      "Continuous Regression",
      "Regression performance",
      "HistGradientBoosting",
    ]);
    expect(badges.map((badge) => badge.className)).toEqual([
      expect.stringContaining("dataset-identity-badge--problem"),
      expect.stringContaining("dataset-identity-badge--focus"),
      expect.stringContaining("dataset-identity-badge--model"),
    ]);
  });

  it('maps continuous_regression to exactly "Continuous Regression" (closing the prior Predictive Analysis drift)', async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "regression-dataset",
        title: "Regression Dataset",
        summary: "Continuous regression dataset.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "continuous_regression",
      },
    ]);

    renderHomePage();

    expect(await screen.findByText("Continuous Regression")).toBeInTheDocument();
    expect(screen.queryByText("Predictive Analysis")).not.toBeInTheDocument();
  });

  it("omits only the Model badge when model_display_name is missing", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "no-model-dataset",
        title: "No Model Dataset",
        summary: "Dataset with a problem type but no release-bound model name.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
        performance_focus_id: "overall_discrimination",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("No Model Dataset");

    const badges = Array.from(container.querySelectorAll(".dataset-card__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual(["Binary Classification", "Overall discrimination"]);
  });

  it("omits only the Model badge when model_display_name is blank", async () => {
    installDatasetsFetchMock([
      {
        dataset_slug: "blank-model-dataset",
        title: "Blank Model Dataset",
        summary: "Dataset with a blank model_display_name.",
        domain: "synthetic",
        visibility: "public",
        tags: [],
        problem_type: "binary_classification",
        model_display_name: "   ",
      },
    ]);

    const { container } = renderHomePage();
    await screen.findByText("Blank Model Dataset");

    const badges = Array.from(container.querySelectorAll(".dataset-card__badges .atlas-badge"));
    expect(badges.map((badge) => badge.textContent)).toEqual(["Binary Classification"]);
  });

  it("never issues a per-card /contract or /model-card request to obtain the model badge", async () => {
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
    await screen.findByText("Model A");
    await screen.findByText("Model B");

    expect(fetchMock.mock.calls).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/datasets$/);
  });
});
