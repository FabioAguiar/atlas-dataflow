import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getTurnstileToken,
  resetTurnstileForTests,
} from "./turnstile";

// No test reaches Cloudflare: the API is a fake on window.turnstile and the
// script element's load/error events are dispatched by hand. Every key, token
// and widget id below is obviously fake.

type FakeRenderOptions = {
  sitekey: string;
  appearance?: string;
  theme?: string;
  callback?: (token: string) => void;
  "error-callback"?: (errorCode: string) => boolean | void;
  "expired-callback"?: () => void;
  "timeout-callback"?: () => void;
  "unsupported-callback"?: () => void;
};

type FakeApi = {
  render: ReturnType<typeof vi.fn<(container: HTMLElement | string, options: FakeRenderOptions) => string>>;
  remove: ReturnType<typeof vi.fn<(widgetId: string) => void>>;
  lastOptions: () => FakeRenderOptions;
};

const SCRIPT_SELECTOR = 'script[data-atlas-turnstile="true"]';
const CONTAINER_SELECTOR = '[data-atlas-turnstile-container="true"]';
const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const FAKE_SITE_KEY = "fake-site-key";

function removeTurnstileArtifacts(): void {
  document
    .querySelectorAll(`${SCRIPT_SELECTOR}, ${CONTAINER_SELECTOR}`)
    .forEach((element) => element.remove());
}

function managedScripts(): HTMLScriptElement[] {
  return Array.from(document.querySelectorAll<HTMLScriptElement>(SCRIPT_SELECTOR));
}

function containerCount(): number {
  return document.querySelectorAll(CONTAINER_SELECTOR).length;
}

// Builds a fake API. `onRender` runs inside render() and may fire callbacks
// synchronously; without it the widget stays pending until the test acts.
function fakeApi(
  onRender?: (options: FakeRenderOptions) => void,
  widgetId = "fake-widget-id",
): FakeApi {
  const render = vi.fn((_container: HTMLElement | string, options: FakeRenderOptions) => {
    onRender?.(options);
    return widgetId;
  });
  const remove = vi.fn((_widgetId: string) => undefined);
  return {
    lastOptions: () => render.mock.calls[render.mock.calls.length - 1][1],
    remove,
    render,
  };
}

function installApi(api: FakeApi): void {
  window.turnstile = { remove: api.remove, render: api.render };
}

// Lets the awaited loader hand off to the challenge (render is called).
async function flushMicrotasks(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
  }
}

describe("turnstile", () => {
  beforeEach(() => {
    resetTurnstileForTests();
    delete window.turnstile;
    removeTurnstileArtifacts();
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "");
  });

  afterEach(() => {
    resetTurnstileForTests();
    delete window.turnstile;
    removeTurnstileArtifacts();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe("disabled rollout", () => {
    it("stays disabled without a site key and loads no script", async () => {
      await expect(getTurnstileToken()).resolves.toEqual({ status: "disabled" });
      expect(managedScripts()).toHaveLength(0);
      expect(containerCount()).toBe(0);
    });

    it("treats a whitespace-only site key as disabled and touches neither DOM nor API", async () => {
      vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "   \t  ");
      const api = fakeApi();
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "disabled" });
      expect(api.render).not.toHaveBeenCalled();
      expect(managedScripts()).toHaveLength(0);
      expect(containerCount()).toBe(0);
    });
  });

  describe("script loading", () => {
    beforeEach(() => {
      vi.stubEnv("VITE_TURNSTILE_SITE_KEY", FAKE_SITE_KEY);
    });

    it("loads nothing at module import", () => {
      expect(managedScripts()).toHaveLength(0);
    });

    it("uses an API already present on window without inserting a script", async () => {
      const api = fakeApi((options) => queueMicrotask(() => options.callback?.("fake-token")));
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "verified", token: "fake-token" });
      expect(managedScripts()).toHaveLength(0);
      expect(api.render).toHaveBeenCalledTimes(1);
    });

    it("loads the official script lazily when the API is not already present", async () => {
      const tokenPromise = getTurnstileToken();

      const scripts = managedScripts();
      expect(scripts).toHaveLength(1);
      expect(scripts[0].src).toBe(SCRIPT_URL);
      expect(scripts[0].async).toBe(true);

      const api = fakeApi((options) => queueMicrotask(() => options.callback?.("fake-lazy-token")), "fake-lazy-widget");
      installApi(api);
      scripts[0].dispatchEvent(new Event("load"));

      await expect(tokenPromise).resolves.toEqual({ status: "verified", token: "fake-lazy-token" });
      expect(api.remove).toHaveBeenCalledWith("fake-lazy-widget");
      // A successfully loaded library stays in place for later challenges.
      expect(managedScripts()).toHaveLength(1);
    });

    it("shares one script between concurrent calls while it is still loading", async () => {
      const first = getTurnstileToken();
      const second = getTurnstileToken();

      expect(managedScripts()).toHaveLength(1);

      let n = 0;
      const api = fakeApi((options) => {
        n += 1;
        const token = `fake-shared-token-${n}`;
        queueMicrotask(() => options.callback?.(token));
      });
      installApi(api);
      managedScripts()[0].dispatchEvent(new Event("load"));

      const results = await Promise.all([first, second]);
      expect(results.every((r) => r.status === "verified")).toBe(true);
      expect(managedScripts()).toHaveLength(1);
      expect(api.render).toHaveBeenCalledTimes(2);
    });

    it("fails closed on a script error event and removes the failed script", async () => {
      const tokenPromise = getTurnstileToken();
      const [script] = managedScripts();

      script.dispatchEvent(new Event("error"));

      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(managedScripts()).toHaveLength(0);
      expect(containerCount()).toBe(0);
    });

    it("fails closed when the script loads without exposing the API", async () => {
      const tokenPromise = getTurnstileToken();
      managedScripts()[0].dispatchEvent(new Event("load"));

      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(managedScripts()).toHaveLength(0);
    });

    it("fails closed on the load timeout and clears the timer and the script", async () => {
      vi.useFakeTimers();
      const tokenPromise = getTurnstileToken();
      expect(managedScripts()).toHaveLength(1);
      expect(vi.getTimerCount()).toBe(1);

      await vi.advanceTimersByTimeAsync(15_000);

      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(managedScripts()).toHaveLength(0);
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("clears the load timeout and listeners once the script loads", async () => {
      vi.useFakeTimers();
      const tokenPromise = getTurnstileToken();
      const [script] = managedScripts();
      const removeListener = vi.spyOn(script, "removeEventListener");

      installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-token"))));
      script.dispatchEvent(new Event("load"));

      await expect(tokenPromise).resolves.toEqual({ status: "verified", token: "fake-token" });
      expect(removeListener).toHaveBeenCalledWith("load", expect.any(Function));
      expect(removeListener).toHaveBeenCalledWith("error", expect.any(Function));
      expect(vi.getTimerCount()).toBe(0);
    });

    it("retries for real after a load error by inserting a fresh script", async () => {
      const failed = getTurnstileToken();
      const [firstScript] = managedScripts();
      firstScript.dispatchEvent(new Event("error"));
      await expect(failed).resolves.toEqual({ status: "failed" });

      const retried = getTurnstileToken();
      const scripts = managedScripts();
      expect(scripts).toHaveLength(1);
      expect(scripts[0]).not.toBe(firstScript);

      installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-retry-token"))));
      scripts[0].dispatchEvent(new Event("load"));

      await expect(retried).resolves.toEqual({ status: "verified", token: "fake-retry-token" });
    });

    it("retries for real after a load timeout without waiting on the timed-out script", async () => {
      vi.useFakeTimers();
      const timedOut = getTurnstileToken();
      const [firstScript] = managedScripts();
      await vi.advanceTimersByTimeAsync(15_000);
      await expect(timedOut).resolves.toEqual({ status: "failed" });

      const retried = getTurnstileToken();
      const [secondScript] = managedScripts();
      expect(secondScript).not.toBe(firstScript);

      installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-retry-token"))));
      secondScript.dispatchEvent(new Event("load"));

      await expect(retried).resolves.toEqual({ status: "verified", token: "fake-retry-token" });
      expect(vi.getTimerCount()).toBe(0);
    });

    it("ignores late events from a superseded script", async () => {
      const failed = getTurnstileToken();
      const [staleScript] = managedScripts();
      staleScript.dispatchEvent(new Event("error"));
      await expect(failed).resolves.toEqual({ status: "failed" });

      const retried = getTurnstileToken();
      const [currentScript] = managedScripts();

      // A late event on the detached old element must not settle the retry.
      staleScript.dispatchEvent(new Event("error"));
      staleScript.dispatchEvent(new Event("load"));
      await flushMicrotasks();
      expect(managedScripts()).toEqual([currentScript]);

      installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-current-token"))));
      currentScript.dispatchEvent(new Event("load"));
      await expect(retried).resolves.toEqual({ status: "verified", token: "fake-current-token" });
    });

    it("replaces a stale managed script without the API instead of waiting on it", async () => {
      vi.useFakeTimers();
      const stale = document.createElement("script");
      stale.dataset.atlasTurnstile = "true";
      stale.src = SCRIPT_URL;
      document.head.appendChild(stale);

      const tokenPromise = getTurnstileToken();
      const scripts = managedScripts();
      expect(scripts).toHaveLength(1);
      expect(scripts[0]).not.toBe(stale);
      expect(stale.isConnected).toBe(false);

      installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-token"))));
      scripts[0].dispatchEvent(new Event("load"));

      await expect(tokenPromise).resolves.toEqual({ status: "verified", token: "fake-token" });
      expect(vi.getTimerCount()).toBe(0);
    });

    it("never removes a script that is not Atlas-managed", async () => {
      const foreign = document.createElement("script");
      foreign.src = SCRIPT_URL;
      document.head.appendChild(foreign);

      const tokenPromise = getTurnstileToken();
      managedScripts()[0].dispatchEvent(new Event("error"));

      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(foreign.isConnected).toBe(true);
      foreign.remove();
    });

    it("fails closed when inserting the script throws", async () => {
      vi.spyOn(document.head, "appendChild").mockImplementationOnce(() => {
        throw new Error("fake-dom-failure");
      });

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(managedScripts()).toHaveLength(0);

      // The synchronous failure is not cached: the next call loads again.
      const retried = getTurnstileToken();
      expect(managedScripts()).toHaveLength(1);
      managedScripts()[0].dispatchEvent(new Event("error"));
      await expect(retried).resolves.toEqual({ status: "failed" });
    });
  });

  describe("challenge", () => {
    beforeEach(() => {
      vi.stubEnv("VITE_TURNSTILE_SITE_KEY", FAKE_SITE_KEY);
    });

    it("returns a verified normalized token and cleans up the widget", async () => {
      const api = fakeApi((options) => queueMicrotask(() => options.callback?.("  fake-turnstile-token  ")));
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({
        status: "verified",
        token: "fake-turnstile-token",
      });

      expect(api.render).toHaveBeenCalledTimes(1);
      const [container, options] = api.render.mock.calls[0];
      expect(container).toBeInstanceOf(HTMLElement);
      expect(options).toMatchObject({
        sitekey: FAKE_SITE_KEY,
        appearance: "interaction-only",
        theme: "auto",
      });
      expect(api.remove).toHaveBeenCalledTimes(1);
      expect(api.remove).toHaveBeenCalledWith("fake-widget-id");
      expect(containerCount()).toBe(0);
    });

    it("passes the trimmed site key to render", async () => {
      vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "  fake-site-key  ");
      const api = fakeApi((options) => queueMicrotask(() => options.callback?.("fake-token")));
      installApi(api);

      await getTurnstileToken();
      expect(api.lastOptions().sitekey).toBe(FAKE_SITE_KEY);
    });

    it.each([
      ["empty", ""],
      ["whitespace-only", "   "],
    ])("fails closed on an %s token and removes the widget", async (_label, token) => {
      const api = fakeApi((options) => queueMicrotask(() => options.callback?.(token)));
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(api.remove).toHaveBeenCalledWith("fake-widget-id");
      expect(containerCount()).toBe(0);
    });

    it.each([
      ["error-callback", (o: FakeRenderOptions) => o["error-callback"]?.("fake-error")],
      ["expired-callback", (o: FakeRenderOptions) => o["expired-callback"]?.()],
      ["timeout-callback", (o: FakeRenderOptions) => o["timeout-callback"]?.()],
      ["unsupported-callback", (o: FakeRenderOptions) => o["unsupported-callback"]?.()],
    ])("fails closed on %s and cleans up widget, container and timer", async (_name, fire) => {
      vi.useFakeTimers();
      const api = fakeApi();
      installApi(api);

      const tokenPromise = getTurnstileToken();
      await flushMicrotasks();
      expect(containerCount()).toBe(1);
      expect(vi.getTimerCount()).toBe(1);

      fire(api.lastOptions());

      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(api.remove).toHaveBeenCalledTimes(1);
      expect(api.remove).toHaveBeenCalledWith("fake-widget-id");
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("asks Turnstile to handle the error itself (error-callback returns true)", async () => {
      const api = fakeApi();
      installApi(api);
      const tokenPromise = getTurnstileToken();
      await flushMicrotasks();

      expect(api.lastOptions()["error-callback"]?.("fake-error")).toBe(true);
      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
    });

    it("fails closed at the local challenge deadline and cleans up", async () => {
      vi.useFakeTimers();
      const api = fakeApi();
      installApi(api);

      const tokenPromise = getTurnstileToken();
      await flushMicrotasks();

      await vi.advanceTimersByTimeAsync(119_999);
      expect(containerCount()).toBe(1);

      await vi.advanceTimersByTimeAsync(1);
      await expect(tokenPromise).resolves.toEqual({ status: "failed" });
      expect(api.remove).toHaveBeenCalledWith("fake-widget-id");
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("fails closed when rendering throws and removes the container", async () => {
      vi.useFakeTimers();
      const api = fakeApi();
      api.render.mockImplementation(() => {
        throw new Error("fake-render-failure");
      });
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(api.remove).not.toHaveBeenCalled();
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("removes the widget when a success callback fires synchronously inside render", async () => {
      vi.useFakeTimers();
      const api = fakeApi((options) => options.callback?.("fake-sync-token"), "fake-sync-widget");
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "verified", token: "fake-sync-token" });
      expect(api.remove).toHaveBeenCalledTimes(1);
      expect(api.remove).toHaveBeenCalledWith("fake-sync-widget");
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("removes the widget when an error callback fires synchronously inside render", async () => {
      vi.useFakeTimers();
      const api = fakeApi((options) => options["error-callback"]?.("fake-error"), "fake-sync-widget");
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(api.remove).toHaveBeenCalledTimes(1);
      expect(api.remove).toHaveBeenCalledWith("fake-sync-widget");
      expect(containerCount()).toBe(0);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("keeps the result when removing the widget throws", async () => {
      const api = fakeApi((options) => queueMicrotask(() => options.callback?.("fake-token")));
      api.remove.mockImplementation(() => {
        throw new Error("fake-remove-failure");
      });
      installApi(api);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "verified", token: "fake-token" });
      expect(containerCount()).toBe(0);
    });

    it("ignores callbacks that arrive after the challenge settled", async () => {
      vi.useFakeTimers();
      const api = fakeApi();
      installApi(api);

      const tokenPromise = getTurnstileToken();
      await flushMicrotasks();
      const options = api.lastOptions();

      options.callback?.("fake-first-token");
      options["error-callback"]?.("fake-late-error");
      options["expired-callback"]?.();
      options["timeout-callback"]?.();
      options["unsupported-callback"]?.();
      options.callback?.("fake-late-token");
      await vi.advanceTimersByTimeAsync(120_000);

      await expect(tokenPromise).resolves.toEqual({ status: "verified", token: "fake-first-token" });
      expect(api.remove).toHaveBeenCalledTimes(1);
      expect(containerCount()).toBe(0);
    });

    it("fails closed instead of throwing when creating the container fails", async () => {
      const api = fakeApi();
      installApi(api);
      vi.spyOn(document.body, "appendChild").mockImplementationOnce(() => {
        throw new Error("fake-dom-failure");
      });

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(api.render).not.toHaveBeenCalled();
      expect(containerCount()).toBe(0);
    });

    it("fails closed instead of throwing when document.body is unavailable", async () => {
      const api = fakeApi();
      installApi(api);
      vi.spyOn(document, "body", "get").mockReturnValue(null as unknown as HTMLElement);

      await expect(getTurnstileToken()).resolves.toEqual({ status: "failed" });
      expect(api.render).not.toHaveBeenCalled();
    });
  });

  it("never logs the site key or the token on any path", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", FAKE_SITE_KEY);
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );

    installApi(fakeApi((options) => queueMicrotask(() => options.callback?.("fake-secret-looking-token"))));
    await getTurnstileToken();

    installApi(fakeApi((options) => queueMicrotask(() => options["error-callback"]?.("fake-error"))));
    await getTurnstileToken();

    installApi(fakeApi((options) => queueMicrotask(() => options["expired-callback"]?.())));
    await getTurnstileToken();

    delete window.turnstile;
    const loadFailure = getTurnstileToken();
    managedScripts()[0].dispatchEvent(new Event("error"));
    await loadFailure;

    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled();
    }
  });
});
