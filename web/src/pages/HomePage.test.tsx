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
  render(
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
