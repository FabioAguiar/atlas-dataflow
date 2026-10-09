import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLOUDFLARE_WEB_ANALYTICS_HOSTNAME,
  CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL,
  CLOUDFLARE_WEB_ANALYTICS_TOKEN,
  currentCloudflareWebAnalyticsEnvironment,
  initCloudflareWebAnalytics,
  shouldLoadCloudflareWebAnalytics,
  type CloudflareWebAnalyticsEnvironment,
} from "./cloudflareWebAnalytics";

// S0316: synthetic jsdom only; jsdom does not download external scripts and
// network primitives are stubbed to fail the test if anything is sent.
const PUBLIC_PRODUCTION: CloudflareWebAnalyticsEnvironment = {
  production: true,
  adminFlag: "false",
  hostname: CLOUDFLARE_WEB_ANALYTICS_HOSTNAME,
};

function beaconScripts(): HTMLScriptElement[] {
  return Array.from(document.querySelectorAll("script")).filter(
    (script) => script.getAttribute("src") === CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL,
  );
}

describe("cloudflareWebAnalytics (S0316)", () => {
  const fetchSpy = vi.fn(() => {
    throw new Error("unexpected network request");
  });
  const sendBeaconSpy = vi.fn(() => {
    throw new Error("unexpected beacon request");
  });

  beforeEach(() => {
    document.head.innerHTML = "";
    document.body.innerHTML = "";
    fetchSpy.mockClear();
    sendBeaconSpy.mockClear();
    vi.stubGlobal("fetch", fetchSpy);
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: sendBeaconSpy });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    document.head.innerHTML = "";
    document.body.innerHTML = "";
  });

  it("injects exactly one module beacon with the Atlas token for the public production canonical host", () => {
    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document)).toBe(true);

    const scripts = beaconScripts();
    expect(scripts).toHaveLength(1);
    const [script] = scripts;
    expect(script.getAttribute("type")).toBe("module");
    expect(script.getAttribute("src")).toBe("https://static.cloudflareinsights.com/beacon.min.js");
    expect(JSON.parse(script.getAttribute("data-cf-beacon") ?? "")).toEqual({
      token: "c226d01187de48478c7d3acf6def5d35",
    });
    expect(CLOUDFLARE_WEB_ANALYTICS_TOKEN).toBe("c226d01187de48478c7d3acf6def5d35");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(sendBeaconSpy).not.toHaveBeenCalled();
  });

  it("is idempotent across repeated bootstrap activation", () => {
    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document)).toBe(true);
    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document)).toBe(false);
    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document)).toBe(false);
    expect(beaconScripts()).toHaveLength(1);
  });

  it("does not add a second tag when a matching beacon script already exists", () => {
    const existing = document.createElement("script");
    existing.setAttribute("src", CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL);
    document.head.appendChild(existing);

    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document)).toBe(false);
    expect(beaconScripts()).toHaveLength(1);
  });

  it.each<[string, Partial<CloudflareWebAnalyticsEnvironment>]>([
    ["development build", { production: false }],
    ["missing production flag", { production: undefined }],
    ["truthy non-boolean production flag", { production: "true" }],
    ["private Admin build", { adminFlag: "true" }],
    ["missing Admin flag", { adminFlag: undefined }],
    ["empty Admin flag", { adminFlag: "" }],
    ["malformed Admin flag", { adminFlag: "FALSE" }],
    ["boolean Admin flag", { adminFlag: false }],
    ["Admin flag with whitespace", { adminFlag: " false" }],
    ["localhost", { hostname: "localhost" }],
    ["loopback address", { hostname: "127.0.0.1" }],
    ["staging hostname", { hostname: "staging.atlas-dataflow.fabioaguiar.dev" }],
    ["Admin hostname", { hostname: "admin.atlas-dataflow.fabioaguiar.dev" }],
    ["subdomain of the canonical host", { hostname: "www.atlas-dataflow.fabioaguiar.dev" }],
    ["lookalike suffix hostname", { hostname: "atlas-dataflow.fabioaguiar.dev.evil.example" }],
    ["lookalike prefix hostname", { hostname: "evil-atlas-dataflow.fabioaguiar.dev" }],
    ["parent domain", { hostname: "fabioaguiar.dev" }],
    ["trailing-dot hostname", { hostname: "atlas-dataflow.fabioaguiar.dev." }],
    ["uppercase hostname", { hostname: "ATLAS-DATAFLOW.FABIOAGUIAR.DEV" }],
    ["missing hostname", { hostname: undefined }],
  ])("loads no beacon for %s", (_label, override) => {
    const environment = { ...PUBLIC_PRODUCTION, ...override };
    expect(shouldLoadCloudflareWebAnalytics(environment)).toBe(false);
    expect(initCloudflareWebAnalytics(environment, document)).toBe(false);
    expect(document.querySelectorAll("script")).toHaveLength(0);
  });

  it("loads nothing without a document", () => {
    expect(initCloudflareWebAnalytics(PUBLIC_PRODUCTION, null)).toBe(false);
  });

  it("stays disabled in the default test environment (non-production, non-canonical host)", () => {
    const environment = currentCloudflareWebAnalyticsEnvironment();
    expect(environment.production).toBe(false);
    expect(environment.hostname).toBe(window.location.hostname);
    expect(initCloudflareWebAnalytics()).toBe(false);
    expect(beaconScripts()).toHaveLength(0);
  });

  it("reads the Admin flag from the build environment and fails closed for Admin builds", () => {
    vi.stubEnv("VITE_ENABLE_ADMIN", "true");
    expect(currentCloudflareWebAnalyticsEnvironment().adminFlag).toBe("true");
    vi.stubEnv("VITE_ENABLE_ADMIN", "false");
    expect(currentCloudflareWebAnalyticsEnvironment().adminFlag).toBe("false");
  });

  it("passes no inference, authentication or Admin data to the beacon", () => {
    initCloudflareWebAnalytics(PUBLIC_PRODUCTION, document);

    const [script] = beaconScripts();
    const attributeNames = script.getAttributeNames().sort();
    expect(attributeNames).toEqual(["data-cf-beacon", "src", "type"]);
    const config = JSON.parse(script.getAttribute("data-cf-beacon") ?? "");
    expect(Object.keys(config)).toEqual(["token"]);
    const serialized = script.outerHTML;
    for (const forbidden of ["access_token", "bearer", "authorization", "inference", "/admin", "apikey"]) {
      expect(serialized.toLowerCase()).not.toContain(forbidden);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(sendBeaconSpy).not.toHaveBeenCalled();
  });
});
