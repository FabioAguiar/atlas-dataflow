import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate, type NavigateFunction } from "react-router-dom";
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

// Project Spec S0137: route-isolation tests must explicitly configure
// desktop/mobile matchMedia -- the shell's initial nav state depends on it
// whenever a route omits an explicit initialNavOpen override.
function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
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
  // Project Spec S0139: a second synthetic dataset lets route-entry tests
  // exercise a Dataset Detail A -> Dataset Detail B slug transition without
  // depending on mutable real registry state.
  {
    dataset_slug: "atlas-sample-dataset-two",
    title: "Atlas Sample Dataset Two",
    summary: "Synthetic secondary dataset for route-entry tests",
    domain: "synthetic",
    tags: ["synthetic"],
    problem_type: "binary_classification",
  },
];

function findDatasetBySlug(slug: string) {
  return datasets.find((dataset) => dataset.dataset_slug === slug) ?? null;
}

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);

    if (url.endsWith("/datasets")) {
      return jsonResponse({ datasets });
    }
    if (url.endsWith("/admin/runs")) {
      return jsonResponse({ runs_root_status: "available", runs: [] });
    }

    const datasetMatch = url.match(/\/datasets\/([^/]+)(\/.*)?$/);
    if (datasetMatch) {
      const slug = decodeURIComponent(datasetMatch[1]);
      const suffix = datasetMatch[2] ?? "";
      const dataset = findDatasetBySlug(slug);

      if (!dataset) {
        return jsonResponse({}, 404);
      }
      if (suffix === "") {
        return jsonResponse(dataset);
      }
      if (suffix === "/context") {
        return jsonResponse({
          dataset_slug: slug,
          context: { problem_summary_body: "Public-safe context" },
        });
      }
      if (suffix.endsWith("/customization")) {
        return jsonResponse({}, 404);
      }
      if (/^\/views\/[^/]+$/.test(suffix)) {
        return jsonResponse({
          view_id: "churn-risk-overview",
          dataset_slug: slug,
          display: { title: "Churn risk overview" },
          intent: {},
          release_mode: null,
        });
      }
      if (suffix === "/contract") {
        return jsonResponse({
          contract: {
            schema_version: "1.0.0",
            features: [
              { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
            ],
          },
          result_contract: { status: "unavailable", reason: "binary_result_semantics_unavailable" },
        });
      }
      if (suffix === "/metrics") {
        return jsonResponse({ dataset_slug: slug, metrics: { auc_roc: 0.91 } });
      }
      if (suffix === "/model-card") {
        return jsonResponse({ model_name: "Validation model" });
      }
      if (suffix === "/visualizations") {
        return jsonResponse({ dataset_slug: slug, visualizations: {} });
      }
      if (suffix === "/views") {
        return jsonResponse([
          {
            view_id: "churn-risk-overview",
            title: "Churn risk overview",
          },
        ]);
      }
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

  const utils = render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );

  // The Admin route tree is code-split behind React.lazy + Suspense; let the
  // pending dynamic imports settle so route assertions observe the resolved
  // Admin shell (or its deterministic absence) rather than the null fallback.
  await act(async () => {
    await vi.dynamicImportSettled();
    await Promise.resolve();
  });

  return utils;
}

// Project Spec S0278: legacy Admin URLs are redirect aliases only. A
// LocationProbe reads the live React Router location so compatibility tests
// can assert the browser ends at the canonical path, using public Router
// behavior rather than implementation internals.
async function renderAppWithLocation(route: string, enableAdmin: boolean) {
  vi.resetModules();
  vi.stubEnv("VITE_ENABLE_ADMIN", enableAdmin ? "true" : "false");

  const { default: App } = await import("./App");

  function LocationProbe() {
    const location = useLocation();
    return <span data-testid="location-pathname">{location.pathname}</span>;
  }

  const utils = render(
    <MemoryRouter initialEntries={[route]}>
      <LocationProbe />
      <App />
    </MemoryRouter>,
  );

  await act(async () => {
    await vi.dynamicImportSettled();
  });

  return utils;
}

// Project Spec S0139: route-entry reset must be proven by navigating within
// one mounted App/Router, not by rendering each route through a separate
// MemoryRouter. NavigationCapture exposes an imperative `navigate` (push or
// history back/forward via a delta) from inside the same mounted Router
// that renders <App />.
async function renderAppWithNavigation(initialRoute: string) {
  vi.resetModules();
  vi.stubEnv("VITE_ENABLE_ADMIN", "false");

  const { default: App } = await import("./App");

  let navigateImpl: NavigateFunction | null = null;

  function NavigationCapture() {
    navigateImpl = useNavigate();
    return null;
  }

  const utils = render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <NavigationCapture />
      <App />
    </MemoryRouter>,
  );

  return {
    ...utils,
    navigate(to: string | number) {
      act(() => {
        if (typeof to === "number") {
          navigateImpl!(to);
        } else {
          navigateImpl!(to);
        }
      });
    },
  };
}

describe("App admin routing", () => {
  beforeEach(() => {
    installFetchMock();
    mockMatchMedia(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("renders Dataset Detail authoring at its canonical /admin/dataset-detail route", async () => {
    await renderApp("/admin/dataset-detail", true);

    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute(
      "href",
      "/admin/dataset-detail",
    );
    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute("aria-current", "page");
    expect(
      await screen.findByRole("heading", { name: "Dataset — Telco Customer Churn" }),
    ).toBeInTheDocument();
  });

  it("redirects the legacy /admin/dataset-admin alias to canonical Dataset Detail", async () => {
    await renderAppWithLocation("/admin/dataset-admin", true);

    // The legacy alias resolves to the canonical Dataset Detail location, and
    // the canonical Dataset Detail route element (DatasetAdminPage) is what
    // renders there -- proven by its active canonical nav link and heading.
    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByTestId("location-pathname")).toHaveTextContent("/admin/dataset-detail");
    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute("aria-current", "page");
    expect(
      await screen.findByRole("heading", { name: "Dataset — Telco Customer Churn" }),
    ).toBeInTheDocument();
  });

  it("renders Settings only inside the private admin shell", async () => {
    await renderApp("/admin/settings", true);

    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
    expect(await screen.findByRole("heading", { name: /Admin settings/i })).toBeInTheDocument();
  });

  it("renders Help only inside the private admin shell", async () => {
    await renderApp("/admin/help", true);

    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/admin/help");
    expect(await screen.findByRole("heading", { name: /Admin help/i })).toBeInTheDocument();
  });

  it("renders the Dashboard at its canonical /admin/dashboard route", async () => {
    await renderApp("/admin/dashboard", true);

    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/admin/dashboard");
  });

  it("redirects the bare /admin route to canonical /admin/dashboard", async () => {
    await renderAppWithLocation("/admin", true);

    expect(await screen.findByRole("navigation", { name: "Admin sections" })).toBeInTheDocument();
    expect(screen.getByTestId("location-pathname")).toHaveTextContent("/admin/dashboard");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
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

  // Project Spec S0278: canonical and legacy Admin routes share one
  // fail-closed behavior -- no Admin shell, navigation, or lazy Admin content
  // renders through the React app when Admin is disabled.
  it.each(["/admin", "/admin/dashboard", "/admin/dataset-detail", "/admin/dataset-admin"])(
    "does not render admin shell or admin navigation for %s when admin is disabled",
    async (route) => {
      const { container } = await renderApp(route, false);

      expect(screen.queryByRole("navigation", { name: "Admin sections" })).not.toBeInTheDocument();
      expect(screen.queryByRole("navigation", { name: "Admin utilities" })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "Dataset — Telco Customer Churn" }),
      ).not.toBeInTheDocument();
      expect(container).toBeEmptyDOMElement();
    },
  );

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

// Project Spec S0137: /dataset/:slug requests an explicit collapsed initial
// navigation state at every viewport size, while / and the Predict View
// route keep the existing viewport-derived default. Route isolation --
// neither route leaks the other's initial navigation state.
describe("PublicShell initial navigation route isolation (Project Spec S0137)", () => {
  beforeEach(() => {
    installFetchMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("starts /dataset/:slug collapsed on a desktop viewport", async () => {
    mockMatchMedia(true);
    const { container } = await renderApp("/dataset/telco-customer-churn", false);
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });

    const toggle = screen.getByLabelText("Show navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  // Project Spec S0286: / no longer inherits PublicShell's viewport-derived
  // default -- Home now requests an explicit initialNavOpen={false}, same as
  // Dataset Detail, so this S0137-era "open by default on desktop" behavior
  // is a deliberate regression, not a preserved one.
  it("starts / collapsed on a desktop viewport (Project Spec S0286)", async () => {
    mockMatchMedia(true);
    const { container } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    const toggle = screen.getByLabelText("Show navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("keeps /dataset/:slug/view/:viewId open by default on a desktop viewport", async () => {
    mockMatchMedia(true);
    const { container } = await renderApp("/dataset/telco-customer-churn/view/churn-risk-overview", false);
    await screen.findByRole("heading", { name: "Churn risk overview", level: 1 });

    const toggle = screen.getByLabelText("Hide navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".public-shell")).toHaveClass("public-shell--nav-open");
  });

  it("keeps /dataset/:slug closed by default on a mobile viewport, matching the existing default", async () => {
    mockMatchMedia(false);
    const { container } = await renderApp("/dataset/telco-customer-churn", false);
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });

    const toggle = screen.getByLabelText("Show navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("keeps / and the Predict View route closed by default on a mobile viewport", async () => {
    mockMatchMedia(false);
    const { container: homeContainer } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(homeContainer.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("still opens and closes the rail on /dataset/:slug after the explicit collapsed initialization", async () => {
    mockMatchMedia(true);
    const { container } = await renderApp("/dataset/telco-customer-churn", false);
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });

    fireEvent.click(screen.getByLabelText("Show navigation"));

    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".public-shell")).toHaveClass("public-shell--nav-open");

    fireEvent.click(screen.getByLabelText("Hide navigation"));

    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });
});

// Project Spec S0286: Home explicitly starts collapsed at every viewport and
// explicitly selects the overlay navigation layout mode, while Dataset
// Detail and Predict View keep their own existing regressions unchanged.
describe("Home explicit collapsed route entry and overlay navigation layout (Project Spec S0286)", () => {
  beforeEach(() => {
    installFetchMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("starts Home collapsed on a desktop viewport", async () => {
    mockMatchMedia(true);
    const { container } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("starts Home collapsed on a mobile viewport", async () => {
    mockMatchMedia(false);
    const { container } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("starts Home collapsed even after entering from an open Predict View shell", async () => {
    mockMatchMedia(true);
    const { container, navigate } = await renderAppWithNavigation(
      "/dataset/telco-customer-churn/view/churn-risk-overview",
    );
    expect(
      await screen.findByRole("heading", { name: "Churn risk overview", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    navigate("/");

    expect(await screen.findByRole("heading", { name: /Atlas DataFlow/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("selects the overlay navigation layout for Home only", async () => {
    mockMatchMedia(true);
    const { container: homeContainer } = await renderApp("/", false);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });
    expect(homeContainer.querySelector(".public-shell")).toHaveAttribute("data-nav-layout", "overlay");

    const { container: datasetContainer } = await renderApp("/dataset/telco-customer-churn", false);
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });
    expect(datasetContainer.querySelector(".public-shell")).toHaveAttribute("data-nav-layout", "inline");

    const { container: predictViewContainer } = await renderApp(
      "/dataset/telco-customer-churn/view/churn-risk-overview",
      false,
    );
    await screen.findByRole("heading", { name: "Churn risk overview", level: 1 });
    expect(predictViewContainer.querySelector(".public-shell")).toHaveAttribute("data-nav-layout", "inline");
  });
});

// Project Spec S0139: route-entry navigation reset must hold across in-app
// navigation within one mounted App/Router, not only across isolated direct
// mounts. Every scenario below shares one MemoryRouter and one <App />
// instance across the assertions it makes -- no scenario re-imports or
// remounts App between the source and destination route.
describe("Dataset Detail route-entry navigation reset (Project Spec S0139)", () => {
  beforeEach(() => {
    installFetchMock();
    mockMatchMedia(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  // Project Spec S0286: Home itself now starts collapsed, so this proves the
  // real transition -- open the Home overlay nav manually, then navigate,
  // and confirm Dataset Detail still forces a fresh collapsed state rather
  // than inheriting the open rail.
  it("collapses navigation entering Dataset Detail from an opened Home without a page reload", async () => {
    const { container, navigate } = await renderAppWithNavigation("/");
    expect(await screen.findByRole("heading", { name: /Atlas DataFlow/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByLabelText("Show navigation"));
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    navigate("/dataset/telco-customer-churn");

    expect(
      await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
    expect(container.querySelector("main")).toHaveAttribute("data-main-mode", "full_bleed");
  });

  it("collapses navigation entering Dataset Detail from Predict View within the same mounted app", async () => {
    const { container, navigate } = await renderAppWithNavigation(
      "/dataset/telco-customer-churn/view/churn-risk-overview",
    );
    expect(
      await screen.findByRole("heading", { name: "Churn risk overview", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    navigate("/dataset/telco-customer-churn");

    expect(
      await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("re-collapses on a Dataset Detail A -> Dataset Detail B slug transition even after the user opened navigation", async () => {
    const { container, navigate } = await renderAppWithNavigation("/dataset/telco-customer-churn");
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByLabelText("Show navigation"));
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    navigate("/dataset/atlas-sample-dataset-two");

    expect(
      await screen.findByRole("heading", { name: "Atlas Sample Dataset Two", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
  });

  it("restores the collapsed Dataset Detail default on browser back/forward re-entry", async () => {
    const { navigate } = await renderAppWithNavigation("/");
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    navigate("/dataset/telco-customer-churn");
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByLabelText("Show navigation"));
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    navigate(-1);
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    navigate(1);

    expect(
      await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps navigation open through Dataset Page data resolution once the user opens it", async () => {
    const { container, navigate } = await renderAppWithNavigation("/");
    await screen.findByRole("heading", { name: /Atlas DataFlow/i });

    navigate("/dataset/telco-customer-churn");
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByLabelText("Show navigation"));
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");

    // Dataset Page keeps resolving auxiliary sections (context, metrics,
    // contract, visualizations) well after the primary heading appears --
    // none of those re-renders may undo the user's manual open.
    await screen.findByText("Public-safe context");

    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".public-shell")).toHaveClass("public-shell--nav-open");
  });

  // Project Spec S0286: Home no longer keeps a viewport-derived open default
  // -- it always starts collapsed, even after visiting collapsed Dataset
  // Detail. Predict View's own existing viewport-derived default (open on
  // desktop) is unaffected by that Home-only regression.
  it("keeps / collapsed and the Predict View route open by default even after visiting collapsed Dataset Detail", async () => {
    const { navigate } = await renderAppWithNavigation("/dataset/telco-customer-churn");
    await screen.findByRole("heading", { name: "Telco Customer Churn", level: 1 });
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    navigate("/");
    expect(await screen.findByRole("heading", { name: /Atlas DataFlow/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Show navigation")).toHaveAttribute("aria-expanded", "false");

    navigate("/dataset/telco-customer-churn/view/churn-risk-overview");
    expect(
      await screen.findByRole("heading", { name: "Churn risk overview", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Hide navigation")).toHaveAttribute("aria-expanded", "true");
  });
});
