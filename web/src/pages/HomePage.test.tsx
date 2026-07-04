import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
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
  vi.unstubAllGlobals();
});

describe("HomePage dataset-count states", () => {
  it("renders the empty state for zero published datasets", async () => {
    installDatasetsFetchMock([]);

    renderHomePage();

    expect(await screen.findByText("Nenhum dataset disponível")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Explorar dataset/ })).not.toBeInTheDocument();
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
    expect(screen.getAllByRole("link", { name: /Explorar dataset/ })).toHaveLength(1);
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
    expect(screen.getAllByRole("link", { name: /Explorar dataset/ })).toHaveLength(3);
  });
});

// Mirrors DatasetCard.tsx's DATASET_ICONS path data so tests can prove which
// icon actually rendered -- this component has no test-id convention
// distinguishing TelecomIcon/BankIcon/GenericDatasetIcon in the DOM today.
const TELECOM_ICON_PATH_D =
  "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a4.5 4.5 0 0 1 9 0m-1.5-5.5A5.5 5.5 0 0 1 20.5 19";
const BANK_ICON_PATH_D = "M4 10h16L12 5 4 10Zm2 0v8m4-8v8m4-8v8m4-8v8M4 19h16";

describe("HomePage problem_type and curated icon rendering", () => {
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

    expect(await screen.findByText("Classificação binária")).toBeInTheDocument();
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

    expect(await screen.findByText("Análise preditiva")).toBeInTheDocument();
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
});
