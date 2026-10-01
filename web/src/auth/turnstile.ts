// Turnstile protection for creation of public anonymous visitor identities.
//
// The integration is intentionally lazy: no Cloudflare script is loaded at
// module import or page load. A challenge is requested only when the visitor
// session layer needs to create a new anonymous Supabase identity.
//
// An empty VITE_TURNSTILE_SITE_KEY keeps Turnstile disabled. This supports a
// staged rollout where the frontend can be deployed before CAPTCHA enforcement
// is enabled in the self-hosted Supabase Auth stack.

const TURNSTILE_SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

const SCRIPT_LOAD_TIMEOUT_MS = 15_000;
const CHALLENGE_TIMEOUT_MS = 120_000;

export type TurnstileTokenResult =
  | { status: "disabled" }
  | { status: "verified"; token: string }
  | { status: "failed" };

type TurnstileRenderOptions = {
  sitekey: string;
  appearance?: "always" | "execute" | "interaction-only";
  theme?: "auto" | "light" | "dark";
  callback?: (token: string) => void;
  "error-callback"?: (errorCode: string) => boolean | void;
  "expired-callback"?: () => void;
  "timeout-callback"?: () => void;
  "unsupported-callback"?: () => void;
};

type TurnstileApi = {
  render(container: HTMLElement | string, options: TurnstileRenderOptions): string;
  remove(widgetId: string): void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const MANAGED_SCRIPT_SELECTOR = 'script[data-atlas-turnstile="true"]';

type LoadAttempt = { abort: () => void };

// Only a load that is still pending is cached. Once it settles, a successful
// load is served from window.turnstile and a failed one leaves nothing behind,
// so the next call performs a real retry.
let scriptPromise: Promise<TurnstileApi> | null = null;
let activeAttempt: LoadAttempt | null = null;

function readSiteKey(): string {
  return String(import.meta.env.VITE_TURNSTILE_SITE_KEY ?? "").trim();
}

function getLoadedApi(): TurnstileApi | null {
  if (typeof window === "undefined") {
    return null;
  }

  return window.turnstile ?? null;
}

function loadTurnstile(): Promise<TurnstileApi> {
  const loaded = getLoadedApi();
  if (loaded) {
    return Promise.resolve(loaded);
  }

  if (scriptPromise) {
    return scriptPromise;
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    return Promise.reject(new Error("Turnstile requires a browser environment."));
  }

  const attempt: LoadAttempt = { abort: () => undefined };
  activeAttempt = attempt;

  const promise = new Promise<TurnstileApi>((resolve, reject) => {
    // No load is pending here, so any Atlas-managed script still in the DOM is
    // a leftover whose load/error events already fired (a failed attempt, or a
    // loaded script whose API has since disappeared). Waiting on it would
    // never complete; replace it. Scripts not marked as Atlas-managed are
    // never touched.
    document
      .querySelectorAll(MANAGED_SCRIPT_SELECTOR)
      .forEach((element) => element.remove());

    const script = document.createElement("script");
    let settled = false;
    let timeoutId: number | undefined;

    const settle = (api: TurnstileApi | null) => {
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(timeoutId);
      script.removeEventListener("load", handleLoad);
      script.removeEventListener("error", handleError);

      if (activeAttempt === attempt) {
        activeAttempt = null;
        scriptPromise = null;
      }

      if (api) {
        resolve(api);
        return;
      }

      script.remove();
      reject(new Error("Turnstile script failed to load."));
    };

    function handleLoad() {
      settle(getLoadedApi());
    }

    function handleError() {
      settle(null);
    }

    attempt.abort = () => settle(null);

    try {
      script.src = TURNSTILE_SCRIPT_URL;
      script.async = true;
      script.defer = true;
      script.dataset.atlasTurnstile = "true";
      script.addEventListener("load", handleLoad);
      script.addEventListener("error", handleError);

      timeoutId = window.setTimeout(() => {
        settle(null);
      }, SCRIPT_LOAD_TIMEOUT_MS);

      document.head.appendChild(script);
    } catch {
      settle(null);
    }
  });

  // A synchronous failure has already cleared the attempt; never cache it.
  if (activeAttempt === attempt) {
    scriptPromise = promise;
  }

  return promise;
}

function createContainer(): HTMLDivElement {
  const container = document.createElement("div");

  container.dataset.atlasTurnstileContainer = "true";
  container.style.position = "fixed";
  container.style.left = "50%";
  container.style.top = "50%";
  container.style.transform = "translate(-50%, -50%)";
  container.style.zIndex = "2147483647";

  document.body.appendChild(container);

  return container;
}

export async function getTurnstileToken(): Promise<TurnstileTokenResult> {
  const siteKey = readSiteKey();

  if (!siteKey) {
    return { status: "disabled" };
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    return { status: "failed" };
  }

  let api: TurnstileApi;

  try {
    api = await loadTurnstile();
  } catch {
    return { status: "failed" };
  }

  return new Promise<TurnstileTokenResult>((resolve) => {
    let container: HTMLDivElement | null = null;
    let widgetId: string | null = null;
    let challengeTimeoutId: number | undefined;
    let settled = false;

    const removeWidget = (id: string) => {
      try {
        api.remove(id);
      } catch {
        // Cleanup must never change the authentication result.
      }
    };

    const finish = (result: TurnstileTokenResult) => {
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(challengeTimeoutId);

      if (widgetId) {
        removeWidget(widgetId);
        widgetId = null;
      }

      try {
        container?.remove();
      } catch {
        // Cleanup must never change the authentication result.
      }
      container = null;

      resolve(result);
    };

    try {
      container = createContainer();

      challengeTimeoutId = window.setTimeout(() => {
        finish({ status: "failed" });
      }, CHALLENGE_TIMEOUT_MS);

      const renderedId = api.render(container, {
        sitekey: siteKey,
        appearance: "interaction-only",
        theme: "auto",

        callback: (token) => {
          const normalized = String(token ?? "").trim();

          if (!normalized) {
            finish({ status: "failed" });
            return;
          }

          finish({ status: "verified", token: normalized });
        },

        "error-callback": () => {
          finish({ status: "failed" });
          return true;
        },

        "expired-callback": () => {
          finish({ status: "failed" });
        },

        "timeout-callback": () => {
          finish({ status: "failed" });
        },

        "unsupported-callback": () => {
          finish({ status: "failed" });
        },
      });

      // A callback may settle the challenge synchronously inside render(),
      // before its widget id is known; remove that widget now.
      if (settled) {
        if (renderedId) {
          removeWidget(renderedId);
        }
      } else {
        widgetId = renderedId;
      }
    } catch {
      finish({ status: "failed" });
    }
  });
}

export function resetTurnstileForTests(): void {
  activeAttempt?.abort();
  activeAttempt = null;
  scriptPromise = null;
}
