import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// M52-01: visitor session tests against a fake Supabase client; no live call.
// Every value below is obviously fake and non-secret.
const fake = vi.hoisted(() => ({
  createClient: vi.fn(),
  getSession: vi.fn(),
  refreshSession: vi.fn(),
  signInAnonymously: vi.fn(),
}));

vi.mock("@supabase/supabase-js", () => ({ createClient: fake.createClient }));

import {
  getVisitorAccess,
  resetVisitorSessionForTests,
  VISITOR_STORAGE_KEY,
} from "./visitorSession";

const NOW_S = Math.floor(Date.now() / 1000);

function anonSession(overrides: Record<string, unknown> = {}, token = "fake-visitor-token") {
  return {
    access_token: token,
    expires_at: NOW_S + 3600,
    user: { id: "fake-visitor-subject", is_anonymous: true },
    ...overrides,
  };
}

describe("visitorSession (M52-01)", () => {
  beforeEach(() => {
    resetVisitorSessionForTests();
    fake.createClient.mockReset();
    fake.getSession.mockReset();
    fake.refreshSession.mockReset();
    fake.signInAnonymously.mockReset();
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });
    fake.refreshSession.mockResolvedValue({ data: { session: null }, error: { message: "fake" } });
    fake.signInAnonymously.mockResolvedValue({ data: { session: anonSession() }, error: null });
    fake.createClient.mockImplementation(() => ({
      auth: {
        getSession: fake.getSession,
        refreshSession: fake.refreshSession,
        signInAnonymously: fake.signInAnonymously,
      },
    }));
    vi.stubEnv("VITE_SUPABASE_URL", "https://fake-project.example.test");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "fake-publishable-key");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("does not create a client on module import", () => {
    expect(fake.createClient).not.toHaveBeenCalled();
  });

  it.each([
    ["missing url", { VITE_SUPABASE_URL: "" }],
    ["blank key", { VITE_SUPABASE_PUBLISHABLE_KEY: "   " }],
    ["invalid scheme", { VITE_SUPABASE_URL: "ftp://fake-project.example.test" }],
    ["unparseable url", { VITE_SUPABASE_URL: "not a url" }],
  ])("reports not_configured for %s without creating a client", async (_label, env) => {
    for (const [name, value] of Object.entries(env)) {
      vi.stubEnv(name, value);
    }
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "not_configured", status: "unavailable" });
    expect(fake.createClient).not.toHaveBeenCalled();
  });

  it("signs in anonymously on first call and returns an available result", async () => {
    await expect(getVisitorAccess()).resolves.toEqual({
      accessToken: "fake-visitor-token",
      isAnonymous: true,
      status: "available",
      subject: "fake-visitor-subject",
    });
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(1);
  });

  it("creates the client with the distinct storageKey and no URL session detection", async () => {
    await getVisitorAccess();
    expect(fake.createClient).toHaveBeenCalledTimes(1);
    expect(fake.createClient).toHaveBeenCalledWith("https://fake-project.example.test", "fake-publishable-key", {
      auth: {
        autoRefreshToken: true,
        detectSessionInUrl: false,
        persistSession: true,
        storageKey: VISITOR_STORAGE_KEY,
      },
    });
    expect(VISITOR_STORAGE_KEY).toBe("atlas-visitor-auth");
    expect(VISITOR_STORAGE_KEY).not.toMatch(/^sb-.*-auth-token$/);
  });

  it("reuses a persisted anonymous session without a new sign-in", async () => {
    fake.getSession.mockResolvedValue({ data: { session: anonSession() }, error: null });
    const first = await getVisitorAccess();
    const second = await getVisitorAccess();
    expect(first).toMatchObject({ status: "available", subject: "fake-visitor-subject" });
    expect(second).toEqual(first);
    expect(fake.signInAnonymously).not.toHaveBeenCalled();
    expect(fake.refreshSession).not.toHaveBeenCalled();
    expect(fake.createClient).toHaveBeenCalledTimes(1);
  });

  it("shares one sign-in between concurrent first callers", async () => {
    const results = await Promise.all([getVisitorAccess(), getVisitorAccess(), getVisitorAccess()]);
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(new Set(results.map((r) => JSON.stringify(r))).size).toBe(1);
    expect(results[0]).toMatchObject({ status: "available" });
  });

  it("refreshes a near-expiry session", async () => {
    fake.getSession.mockResolvedValue({
      data: { session: anonSession({ expires_at: NOW_S + 5 }, "fake-old-token") },
      error: null,
    });
    fake.refreshSession.mockResolvedValue({
      data: { session: anonSession({}, "fake-refreshed-token") },
      error: null,
    });
    await expect(getVisitorAccess()).resolves.toMatchObject({
      accessToken: "fake-refreshed-token",
      status: "available",
    });
    expect(fake.refreshSession).toHaveBeenCalledTimes(1);
    expect(fake.signInAnonymously).not.toHaveBeenCalled();
  });

  it("replaces the session with a new anonymous sign-in when refresh fails", async () => {
    fake.getSession.mockResolvedValue({
      data: { session: anonSession({ expires_at: NOW_S - 10 }, "fake-old-token") },
      error: null,
    });
    fake.signInAnonymously.mockResolvedValue({
      data: { session: anonSession({ user: { id: "fake-new-subject", is_anonymous: true } }, "fake-new-token") },
      error: null,
    });
    await expect(getVisitorAccess()).resolves.toMatchObject({
      accessToken: "fake-new-token",
      status: "available",
      subject: "fake-new-subject",
    });
    expect(fake.refreshSession).toHaveBeenCalledTimes(1);
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(1);
  });

  it("replaces the session when refresh throws", async () => {
    fake.getSession.mockResolvedValue({ data: { session: anonSession({ expires_at: NOW_S - 10 }) }, error: null });
    fake.refreshSession.mockRejectedValue(new Error("fake-network"));
    await expect(getVisitorAccess()).resolves.toMatchObject({ status: "available" });
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(1);
  });

  it("reports sign_in_failed when sign-in fails and retries on the next call", async () => {
    fake.signInAnonymously.mockResolvedValueOnce({ data: { session: null }, error: { message: "fake" } });
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "sign_in_failed", status: "unavailable" });
    await expect(getVisitorAccess()).resolves.toMatchObject({ status: "available" });
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(2);
  });

  it("reports sign_in_failed when sign-in throws, and never throws itself", async () => {
    fake.signInAnonymously.mockRejectedValue(new Error("fake-network"));
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "sign_in_failed", status: "unavailable" });
  });

  it("rejects a persisted non-anonymous session as session_invalid", async () => {
    fake.getSession.mockResolvedValue({
      data: { session: anonSession({ user: { id: "fake-admin", is_anonymous: false } }) },
      error: null,
    });
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "session_invalid", status: "unavailable" });
    expect(fake.signInAnonymously).not.toHaveBeenCalled();
    expect(fake.refreshSession).not.toHaveBeenCalled();
  });

  it("rejects a non-anonymous user returned by sign-in", async () => {
    fake.signInAnonymously.mockResolvedValue({
      data: { session: anonSession({ user: { id: "fake-user" } }) },
      error: null,
    });
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "session_invalid", status: "unavailable" });
  });

  it("reports client_error when the client cannot be constructed", async () => {
    fake.createClient.mockImplementation(() => {
      throw new Error("fake-construct");
    });
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "client_error", status: "unavailable" });
  });

  it("reports client_error when reading the session fails", async () => {
    fake.getSession.mockRejectedValue(new Error("fake-storage"));
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "client_error", status: "unavailable" });
    fake.getSession.mockResolvedValue({ data: { session: null }, error: { message: "fake" } });
    await expect(getVisitorAccess()).resolves.toEqual({ reason: "client_error", status: "unavailable" });
  });

  it("never logs the token or subject on success or failure paths", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    await getVisitorAccess();
    resetVisitorSessionForTests();
    fake.signInAnonymously.mockRejectedValue(new Error("fake-visitor-token"));
    await getVisitorAccess();
    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled();
    }
  });
});
