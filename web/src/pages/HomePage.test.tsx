import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  home_card_icon?: string | null;
  home_card_media_ref?: string | null;
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
      screen.getByText("Customer churn prediction dataset for a telecommunications provider."),
    ).toBeInTheDocument();
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
});
