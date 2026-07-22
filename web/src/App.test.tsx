import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
      return jsonResponse({ datasets });
    }
    if (url.endsWith(`/datasets/${datasets[0].dataset_slug}`)) {
      return jsonResponse(datasets[0]);
    }
    if (url.endsWith("/admin/runs")) {
      return jsonResponse({ runs_root_status: "available", runs: [] });
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

async function renderApp(route: string, enableAdmin: boolean) {
  vi.resetModules();
  vi.stubEnv("VITE_ENABLE_ADMIN", enableAdmin ? "true" : "false");

  const { default: App } = await import("./App");

  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App admin routing", () => {
  beforeEach(() => {
    installFetchMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("renders Dataset Admin only inside the private admin shell", async () => {
    await renderApp("/admin/dataset-admin", true);

    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute(
      "href",
      "/admin/dataset-admin",
    );
    expect(screen.getByRole("button", { name: "Publishing unavailable" })).toBeDisabled();
    expect(
      await screen.findByRole("heading", { name: "Dataset -- Telco Customer Churn" }),
    ).toBeInTheDocument();
  });

  it("renders Settings only inside the private admin shell", async () => {
    await renderApp("/admin/settings", true);

    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
    expect(screen.getByRole("heading", { name: /Admin settings/i })).toBeInTheDocument();
  });

  it("renders Help only inside the private admin shell", async () => {
    await renderApp("/admin/help", true);

    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/admin/help");
    expect(screen.getByRole("heading", { name: /Admin help/i })).toBeInTheDocument();
  });

  it("renders the Dashboard only inside the private admin shell", async () => {
    await renderApp("/admin", true);

    expect(screen.getByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("renders the public Dataset Detail page for /dataset/:slug", async () => {
    await renderApp("/dataset/telco-customer-churn", false);

    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 }),
    ).toBeInTheDocument();
  });

  // Project Spec S0130: /dataset/:slug requests the explicit full-bleed
  // public-shell main mode; / stays on the existing constrained mode. Route
  // isolation -- neither route leaks the other's main mode.
  it("uses the full-bleed public-shell main mode for /dataset/:slug and the constrained mode for /", async () => {
    const { container: datasetContainer } = await renderApp("/dataset/telco-customer-churn", false);
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });

    const datasetMain = datasetContainer.querySelector(".public-shell__main");
    expect(datasetMain).toHaveClass("public-shell__main--full-bleed");
    expect(datasetMain).not.toHaveClass("app-shell");
    expect(datasetMain).toHaveAttribute("data-main-mode", "full_bleed");
    expect(datasetContainer.querySelector(".dataset-detail-page-canvas")).toBeInTheDocument();

    const { container: homeContainer } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    const homeMain = homeContainer.querySelector(".public-shell__main");
    expect(homeMain).toHaveClass("app-shell");
    expect(homeMain).not.toHaveClass("public-shell__main--full-bleed");
    expect(homeMain).toHaveAttribute("data-main-mode", "constrained");
  });

  it("does not render admin shell or admin navigation for direct admin URLs when admin is disabled", async () => {
    const { container } = await renderApp("/admin/dataset-admin", false);

    expect(screen.queryByRole("navigation", { name: "Admin sections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Admin utilities" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dataset -- Telco Customer Churn" })).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("does not render admin shell or admin navigation for the bare /admin route when admin is disabled", async () => {
    const { container } = await renderApp("/admin", false);

    expect(screen.queryByRole("navigation", { name: "Admin sections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps public routes available when admin is disabled", async () => {
    await renderApp("/", false);

    expect(await screen.findByRole("heading", { name: /Atlas DataFlow/i })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Admin sections" })).not.toBeInTheDocument();
  });
});
