import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

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

const datasets = [
  {
    dataset_slug: "telco-customer-churn",
    title: "Telco Customer Churn",
    summary: "Customer churn prediction dataset",
    domain: "telecom",
    tags: ["telecom"],
    problem_type: "binary_classification",
  },
];

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith("/datasets")) {
      return jsonResponse(datasets);
    }
    if (url.includes("/context")) {
      return jsonResponse({ problem_summary: "Public-safe context" });
    }
    if (url.includes("/contract")) {
      return jsonResponse({ features: [{ name: "tenure", optional: true }] });
    }
    if (url.includes("/metrics")) {
      return jsonResponse({ auc_roc: 0.91 });
    }
    if (url.includes("/model-card")) {
      return jsonResponse({ model_name: "Validation model" });
    }
    if (url.includes("/visualizations")) {
      return jsonResponse({});
    }
    if (url.includes("/views")) {
      return jsonResponse([
        {
          view_id: "churn-risk-overview",
          title: "Churn risk overview",
        },
      ]);
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("App admin routing", () => {
  beforeEach(() => {
    installFetchMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders Dataset Admin only inside the private admin shell", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dataset-admin"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Private administration")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dataset Admin" })).toHaveAttribute(
      "href",
      "/admin/dataset-admin",
    );
    expect(screen.getByRole("button", { name: "Publishing unavailable" })).toBeDisabled();
    expect(screen.getByRole("heading", { name: /Dataset Admin/i })).toBeInTheDocument();
  });

  it("renders Settings only inside the private admin shell", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/settings"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Private administration")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
    expect(screen.getByRole("heading", { name: /Admin settings/i })).toBeInTheDocument();
  });

  it("renders Help only inside the private admin shell", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/help"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Private administration")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/admin/help");
    expect(screen.getByRole("heading", { name: /Admin help/i })).toBeInTheDocument();
  });
});
