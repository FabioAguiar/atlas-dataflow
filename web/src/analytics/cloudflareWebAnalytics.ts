// S0316: Cloudflare Web Analytics for the production public Atlas UI only.
//
// The beacon is inserted at bootstrap (web/src/main.tsx) instead of in the
// shared web/index.html, because the private Admin and staging images are built
// from the same sources. The guard is fail-closed: it loads only for a
// production build whose VITE_ENABLE_ADMIN is exactly "false", served from
// exactly the canonical public hostname. Cloudflare Web Analytics reports SPA
// soft navigations by itself, so no history listener or custom pageview
// dispatch is added here, and no Atlas data is ever passed to the beacon.

export const CLOUDFLARE_WEB_ANALYTICS_HOSTNAME = "atlas-dataflow.fabioaguiar.dev";
export const CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL = "https://static.cloudflareinsights.com/beacon.min.js";
// Public measurement identifier of the registered Atlas site, not a credential.
export const CLOUDFLARE_WEB_ANALYTICS_TOKEN = "c226d01187de48478c7d3acf6def5d35";

export interface CloudflareWebAnalyticsEnvironment {
  production: unknown;
  adminFlag: unknown;
  hostname: unknown;
}

export function currentCloudflareWebAnalyticsEnvironment(): CloudflareWebAnalyticsEnvironment {
  return {
    production: import.meta.env.PROD,
    adminFlag: import.meta.env.VITE_ENABLE_ADMIN,
    hostname: typeof window === "undefined" ? undefined : window.location.hostname,
  };
}

export function shouldLoadCloudflareWebAnalytics(environment: CloudflareWebAnalyticsEnvironment): boolean {
  return (
    environment.production === true &&
    environment.adminFlag === "false" &&
    environment.hostname === CLOUDFLARE_WEB_ANALYTICS_HOSTNAME
  );
}

function hasBeaconScript(doc: Document): boolean {
  return Array.from(doc.getElementsByTagName("script")).some(
    (script) => script.getAttribute("src") === CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL,
  );
}

// Returns true only when this call inserted the beacon script.
export function initCloudflareWebAnalytics(
  environment: CloudflareWebAnalyticsEnvironment = currentCloudflareWebAnalyticsEnvironment(),
  doc: Document | null = typeof document === "undefined" ? null : document,
): boolean {
  if (!doc || !shouldLoadCloudflareWebAnalytics(environment) || hasBeaconScript(doc)) {
    return false;
  }
  const parent = doc.body ?? doc.head;
  if (!parent) {
    return false;
  }
  const script = doc.createElement("script");
  script.type = "module";
  script.src = CLOUDFLARE_WEB_ANALYTICS_SCRIPT_URL;
  script.setAttribute("data-cf-beacon", JSON.stringify({ token: CLOUDFLARE_WEB_ANALYTICS_TOKEN }));
  parent.appendChild(script);
  return true;
}
