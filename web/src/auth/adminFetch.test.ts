import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSessionError, adminFetch, registerAdminSessionSource } from "./adminFetch";

const FAKE_TOKEN = "fake-token-not-a-secret";

describe("adminFetch (M51-04)", () => {
  const fetchMock = vi.fn();
  let unregister: (() => void) | null = null;

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    unregister?.();
    unregister = null;
    vi.unstubAllGlobals();
  });

  function register(token: string | null | (() => Promise<string | null>)) {
    const terminateSession = vi.fn();
    const getAccessToken = typeof token === "function" ? vi.fn(token) : vi.fn(async () => token);
    unregister = registerAdminSessionSource({ getAccessToken, terminateSession });
    return { getAccessToken, terminateSession };
  }

  function sentHeaders(): Headers {
    return new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
  }

  it("attaches the bearer to a GET", async () => {
    register(FAKE_TOKEN);
    await adminFetch("/admin/datasets");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/admin/datasets");
    expect(sentHeaders().get("Authorization")).toBe(`Bearer ${FAKE_TOKEN}`);
  });

  it("preserves method, body, Content-Type and signal on JSON mutations", async () => {
    register(FAKE_TOKEN);
    const controller = new AbortController();
    await adminFetch("/admin/settings", {
      body: JSON.stringify({ display_name: "Ada" }),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
      signal: controller.signal,
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ display_name: "Ada" }));
    expect(init.signal).toBe(controller.signal);
    expect(sentHeaders().get("Content-Type")).toBe("application/json");
    expect(sentHeaders().get("Authorization")).toBe(`Bearer ${FAKE_TOKEN}`);
  });

  it("passes a raw File upload body and X-File-Name through untouched", async () => {
    register(FAKE_TOKEN);
    const file = new File(["x"], "card.png", { type: "image/png" });
    await adminFetch("/admin/datasets/demo/home-card-image", {
      body: file,
      headers: { "Content-Type": "image/png", "X-File-Name": "card.png" },
      method: "POST",
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(file);
    expect(sentHeaders().get("X-File-Name")).toBe("card.png");
  });

  it("does not mutate the caller's init or headers", async () => {
    register(FAKE_TOKEN);
    const init: RequestInit = { headers: { "Content-Type": "application/json" }, method: "POST" };
    await adminFetch("/admin/runs", init);

    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("re-reads the token on every call", async () => {
    let current = "fake-token-one";
    const { getAccessToken } = register(async () => current);
    await adminFetch("/admin/datasets");
    current = "fake-token-two";
    await adminFetch("/admin/datasets");

    expect(getAccessToken).toHaveBeenCalledTimes(2);
    expect(new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers).get("Authorization")).toBe(
      "Bearer fake-token-one",
    );
    expect(new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers).get("Authorization")).toBe(
      "Bearer fake-token-two",
    );
  });

  it("rejects non-/admin targets without sending a request", async () => {
    register(FAKE_TOKEN);

    await expect(adminFetch("/datasets")).rejects.toBeInstanceOf(AdminSessionError);
    await expect(adminFetch("/administrator")).rejects.toBeInstanceOf(AdminSessionError);
    await expect(adminFetch("https://example.test/datasets?x=/admin/")).rejects.toBeInstanceOf(AdminSessionError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts an absolute /admin/ URL", async () => {
    register(FAKE_TOKEN);
    await adminFetch("https://api.example.test/admin/runs");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("fails closed without a registered source", async () => {
    await expect(adminFetch("/admin/datasets")).rejects.toBeInstanceOf(AdminSessionError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("terminates the session once and never fetches when no token is available", async () => {
    const { terminateSession } = register(null);

    await expect(adminFetch("/admin/datasets")).rejects.toBeInstanceOf(AdminSessionError);
    expect(terminateSession).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("treats a throwing token source as session loss", async () => {
    const { terminateSession } = register(async () => {
      throw new Error(`boom ${FAKE_TOKEN}`);
    });

    const error = await adminFetch("/admin/datasets").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AdminSessionError);
    expect((error as Error).message).not.toContain(FAKE_TOKEN);
    expect(terminateSession).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the Response unconsumed, including server 401/404", async () => {
    register(FAKE_TOKEN);
    const response = new Response("nope", { status: 401 });
    fetchMock.mockResolvedValueOnce(response);

    const result = await adminFetch("/admin/datasets");
    expect(result).toBe(response);
    expect(result.bodyUsed).toBe(false);
  });

  it("restores the previous source when a registration is cleaned up", async () => {
    const first = register("fake-token-first");
    const second = registerAdminSessionSource({ getAccessToken: async () => "fake-token-second", terminateSession: vi.fn() });
    second();
    await adminFetch("/admin/datasets");

    expect(first.getAccessToken).toHaveBeenCalledTimes(1);
  });
});
