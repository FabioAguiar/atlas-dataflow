import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// M51-03: provider state-machine tests against a fake Supabase browser client.
// Every value below is obviously fake and non-secret.
const fake = vi.hoisted(() => ({
  createClient: vi.fn(),
  getSession: vi.fn(),
  getTurnstileToken: vi.fn(),
  listener: null as null | ((event: string, session: unknown) => void),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  unsubscribe: vi.fn(),
}));

vi.mock("@supabase/supabase-js", () => ({ createClient: fake.createClient }));
vi.mock("./turnstile", () => ({ getTurnstileToken: fake.getTurnstileToken }));

import {
  AdminAuthProvider,
  AdminAuthRoot,
  AdminSessionGuard,
  useAdminAuth,
  useOptionalAdminAuth,
} from "./AdminAuthContext";
import { adminFetch, AdminSessionError } from "./adminFetch";

const SESSION = { access_token: "fake-access-token", user: { email: "fake-operator@example.test", id: "fake-user" } };

function StatusProbe() {
  const { email, signInWithEmailPassword, signOut, status } = useAdminAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="email">{email ?? "none"}</span>
      <button onClick={() => void signInWithEmailPassword("a@example.test", "fake-password")} type="button">
        sign-in
      </button>
      <button onClick={() => void signOut()} type="button">
        sign-out
      </button>
    </div>
  );
}

describe("AdminAuthProvider (M51-03)", () => {
  beforeEach(() => {
    fake.listener = null;
    fake.unsubscribe.mockReset();
    fake.getSession.mockReset();
    fake.getSession.mockResolvedValue({ data: { session: SESSION }, error: null });
    fake.signInWithPassword.mockReset();
    fake.signInWithPassword.mockResolvedValue({ data: { session: SESSION }, error: null });
    fake.signOut.mockReset();
    fake.signOut.mockResolvedValue({ error: null });
    fake.getTurnstileToken.mockReset();
    fake.getTurnstileToken.mockResolvedValue({ status: "disabled" });
    fake.createClient.mockReset();
    fake.createClient.mockImplementation(() => ({
      auth: {
        getSession: fake.getSession,
        onAuthStateChange: (callback: (event: string, session: unknown) => void) => {
          fake.listener = callback;
          return { data: { subscription: { unsubscribe: fake.unsubscribe } } };
        },
        signInWithPassword: fake.signInWithPassword,
        signOut: fake.signOut,
      },
    }));
    vi.stubEnv("VITE_SUPABASE_URL", "https://fake-project.example.test");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "fake-publishable-key");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  function renderProvider(strict = false) {
    const tree = (
      <AdminAuthProvider>
        <StatusProbe />
      </AdminAuthProvider>
    );
    return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
  }

  it("is loading until getSession resolves, then authenticated", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    fake.getSession.mockImplementation(() => new Promise((r) => (resolve = r)));
    renderProvider();

    expect(screen.getByTestId("status")).toHaveTextContent("loading");
    await act(async () => resolve({ data: { session: SESSION }, error: null }));
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  });

  it("is unauthenticated when no session is persisted", async () => {
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });
    renderProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });

  it.each([
    ["rejects", () => fake.getSession.mockRejectedValue(new Error("provider-internal-detail"))],
    ["returns an error", () => fake.getSession.mockResolvedValue({ data: { session: null }, error: { message: "x" } })],
  ])("is unrecoverable when getSession %s", async (_label, arrange) => {
    arrange();
    renderProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unrecoverable"));
  });

  it.each([
    ["missing", "", ""],
    ["blank", "   ", "fake-publishable-key"],
    ["non-URL", "not a url", "fake-publishable-key"],
    ["non-http(s)", "ftp://fake-project.example.test", "fake-publishable-key"],
    ["missing key", "https://fake-project.example.test", "  "],
  ])("is unrecoverable and never constructs a client for %s config", (_label, url, key) => {
    vi.stubEnv("VITE_SUPABASE_URL", url);
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", key);
    renderProvider();

    expect(screen.getByTestId("status")).toHaveTextContent("unrecoverable");
    expect(fake.createClient).not.toHaveBeenCalled();
  });

  it("is unrecoverable when client construction throws", () => {
    fake.createClient.mockImplementation(() => {
      throw new Error("provider-internal-detail");
    });
    renderProvider();

    expect(screen.getByTestId("status")).toHaveTextContent("unrecoverable");
  });

  it("moves to unauthenticated on SIGNED_OUT or a null session (refresh failure)", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    act(() => fake.listener?.("SIGNED_OUT", null));
    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");

    act(() => fake.listener?.("TOKEN_REFRESHED", SESSION));
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");

    act(() => fake.listener?.("TOKEN_REFRESHED", null));
    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
  });

  it("does not let a late getSession result override a newer SIGNED_OUT event", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    fake.getSession.mockImplementation(() => new Promise((r) => (resolve = r)));
    renderProvider();

    act(() => fake.listener?.("SIGNED_OUT", null));
    await act(async () => resolve({ data: { session: SESSION }, error: null }));

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
  });

  it("keeps one logical subscription under StrictMode and unsubscribes on cleanup", async () => {
    const { unmount } = renderProvider(true);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    expect(fake.createClient).toHaveBeenCalledTimes(1);
    // Effects mount, clean up and mount again under StrictMode: every
    // subscription that was opened is closed except the live one.
    const subscribed = fake.unsubscribe.mock.calls.length;
    unmount();
    expect(fake.unsubscribe.mock.calls.length).toBe(subscribed + 1);
  });

  it("ignores session results that arrive after unmount", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    fake.getSession.mockImplementation(() => new Promise((r) => (resolve = r)));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { unmount } = renderProvider();

    unmount();
    await act(async () => resolve({ data: { session: SESSION }, error: null }));

    expect(errorSpy).not.toHaveBeenCalled();
    expect(fake.unsubscribe).toHaveBeenCalled();
  });

  it("signs in with the Supabase client and becomes authenticated", async () => {
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    fireEvent.click(screen.getByRole("button", { name: "sign-in" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(fake.signInWithPassword).toHaveBeenCalledWith({ email: "a@example.test", password: "fake-password" });
  });

  it("returns a bare failure for rejected or errored sign-in, with no provider text or logging", async () => {
    const logSpies = [
      vi.spyOn(console, "error").mockImplementation(() => undefined),
      vi.spyOn(console, "warn").mockImplementation(() => undefined),
      vi.spyOn(console, "log").mockImplementation(() => undefined),
    ];
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });
    let result: unknown;
    function Capture() {
      const { signInWithEmailPassword } = useAdminAuth();
      return (
        <button
          onClick={async () => {
            result = await signInWithEmailPassword("a@example.test", "fake-password");
          }}
          type="button"
        >
          go
        </button>
      );
    }
    render(
      <AdminAuthProvider>
        <Capture />
      </AdminAuthProvider>,
    );

    fake.signInWithPassword.mockResolvedValue({ data: { session: null }, error: { message: "provider-internal-detail" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "go" })));
    expect(result).toBe("failed");

    fake.signInWithPassword.mockRejectedValue(new Error("provider-internal-detail"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "go" })));
    expect(result).toBe("failed");

    for (const spy of logSpies) {
      expect(spy).not.toHaveBeenCalled();
    }
    expect(document.body.textContent ?? "").not.toContain("provider-internal-detail");
  });

  it("signOut always ends unauthenticated, even if the remote call rejects", async () => {
    fake.signOut.mockRejectedValue(new Error("provider-internal-detail"));
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    fireEvent.click(screen.getByRole("button", { name: "sign-out" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(fake.signOut).toHaveBeenCalledTimes(1);
  });

  it("registers the session source, reading the token per call, and clears it on unmount (M51-04)", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    const view = renderProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    fake.getSession.mockClear();

    await adminFetch("/admin/datasets");
    fake.getSession.mockResolvedValue({ data: { session: { ...SESSION, access_token: "fake-rotated-token" } }, error: null });
    await adminFetch("/admin/datasets");

    expect(fake.getSession).toHaveBeenCalledTimes(2);
    const auth = (i: number) => new Headers((fetchMock.mock.calls[i] as unknown as [string, RequestInit])[1].headers);
    expect(auth(0).get("Authorization")).toBe("Bearer fake-access-token");
    expect(auth(1).get("Authorization")).toBe("Bearer fake-rotated-token");

    view.unmount();
    await expect(adminFetch("/admin/datasets")).rejects.toBeInstanceOf(AdminSessionError);
    vi.unstubAllGlobals();
  });

  it("keeps a single working registration under StrictMode (M51-04)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    renderProvider(true);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await expect(adminFetch("/admin/datasets")).resolves.toBeInstanceOf(Response);
    vi.unstubAllGlobals();
  });

  it("terminates the session locally when the token is unavailable (M51-04)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });

    await expect(adminFetch("/admin/datasets")).rejects.toBeInstanceOf(AdminSessionError);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(fake.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("exposes a live email that is null after sign-out and never exposes the token (M51-04)", async () => {
    const view = renderProvider();
    await waitFor(() => expect(screen.getByTestId("email")).toHaveTextContent("fake-operator@example.test"));
    expect(view.container.innerHTML).not.toContain("fake-access-token");

    fireEvent.click(screen.getByRole("button", { name: "sign-out" }));
    await waitFor(() => expect(screen.getByTestId("email")).toHaveTextContent("none"));
  });

  it("useAdminAuth throws outside a provider while useOptionalAdminAuth returns null", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Optional() {
      return <span data-testid="optional">{String(useOptionalAdminAuth())}</span>;
    }

    render(<Optional />);
    expect(screen.getByTestId("optional")).toHaveTextContent("null");
    expect(() => render(<StatusProbe />)).toThrow();
  });
});

describe("AdminSessionGuard (M51-03)", () => {
  beforeEach(() => {
    fake.listener = null;
    fake.unsubscribe.mockReset();
    fake.getSession.mockReset();
    fake.createClient.mockReset();
    fake.createClient.mockImplementation(() => ({
      auth: {
        getSession: fake.getSession,
        onAuthStateChange: (callback: (event: string, session: unknown) => void) => {
          fake.listener = callback;
          return { data: { subscription: { unsubscribe: fake.unsubscribe } } };
        },
        signInWithPassword: fake.signInWithPassword,
        signOut: fake.signOut,
      },
    }));
    vi.stubEnv("VITE_SUPABASE_URL", "https://fake-project.example.test");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "fake-publishable-key");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  function renderGuarded() {
    return render(
      <MemoryRouter initialEntries={["/admin/private"]}>
        <Routes>
          <Route element={<AdminAuthRoot />}>
            <Route element={<div>Login route</div>} path="/admin/login" />
            <Route element={<AdminSessionGuard />}>
              <Route element={<div>Protected content</div>} path="/admin/private" />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  it("renders nothing protected while loading, then the protected route when authenticated", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    fake.getSession.mockImplementation(() => new Promise((r) => (resolve = r)));
    const { container } = renderGuarded();

    expect(container).toBeEmptyDOMElement();
    await act(async () => resolve({ data: { session: SESSION }, error: null }));
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it.each([
    ["unauthenticated", () => fake.getSession.mockResolvedValue({ data: { session: null }, error: null })],
    ["unrecoverable", () => fake.getSession.mockRejectedValue(new Error("provider-internal-detail"))],
  ])("redirects once to /admin/login when %s", async (_label, arrange) => {
    arrange();
    renderGuarded();

    expect(await screen.findByText("Login route")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});

describe("AdminAuthProvider Turnstile compatibility", () => {
  // Fake values only: they are never valid credentials, keys or tokens.
  const FAKE_TOKEN = "fake-admin-turnstile-token";
  const FAKE_SITE_KEY = "fake-admin-turnstile-site-key";
  const FAKE_PASSWORD = "fake-admin-password";

  let results: unknown[];
  let logSpies: ReturnType<typeof vi.spyOn>[];
  let signIn: (email: string, password: string) => Promise<unknown>;

  function Capture() {
    const { signInWithEmailPassword, status } = useAdminAuth();
    signIn = signInWithEmailPassword;
    return (
      <div>
        <span data-testid="status">{status}</span>
        <button
          onClick={async () => {
            results.push(await signInWithEmailPassword("a@example.test", FAKE_PASSWORD));
          }}
          type="button"
        >
          go
        </button>
      </div>
    );
  }

  async function renderSignedOut() {
    render(
      <AdminAuthProvider>
        <Capture />
      </AdminAuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  }

  async function clickSignIn() {
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "go" })));
  }

  beforeEach(() => {
    results = [];
    fake.listener = null;
    fake.unsubscribe.mockReset();
    fake.getSession.mockReset();
    fake.getSession.mockResolvedValue({ data: { session: null }, error: null });
    fake.signInWithPassword.mockReset();
    fake.signInWithPassword.mockResolvedValue({ data: { session: SESSION }, error: null });
    fake.signOut.mockReset();
    fake.signOut.mockResolvedValue({ error: null });
    fake.getTurnstileToken.mockReset();
    fake.getTurnstileToken.mockResolvedValue({ status: "disabled" });
    fake.createClient.mockReset();
    fake.createClient.mockImplementation(() => ({
      auth: {
        getSession: fake.getSession,
        onAuthStateChange: (callback: (event: string, session: unknown) => void) => {
          fake.listener = callback;
          return { data: { subscription: { unsubscribe: fake.unsubscribe } } };
        },
        signInWithPassword: fake.signInWithPassword,
        signOut: fake.signOut,
      },
    }));
    vi.stubEnv("VITE_SUPABASE_URL", "https://fake-project.example.test");
    vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "fake-publishable-key");
    logSpies = (["log", "info", "warn", "error", "debug"] as const).map((method) =>
      vi.spyOn(console, method).mockImplementation(() => undefined),
    );
  });

  afterEach(() => {
    // Nothing sensitive may reach the console on any path.
    const logged = JSON.stringify(logSpies.flatMap((spy) => spy.mock.calls));
    for (const secret of [FAKE_TOKEN, FAKE_SITE_KEY, FAKE_PASSWORD, "fake-access-token", "fake-refresh-token"]) {
      expect(logged).not.toContain(secret);
    }
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("with an empty site key, uses the real helper and signs in exactly as before (no captchaToken)", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "");
    const actual = await vi.importActual<typeof import("./turnstile")>("./turnstile");
    fake.getTurnstileToken.mockImplementation(actual.getTurnstileToken);
    await renderSignedOut();

    await clickSignIn();

    expect(results).toEqual(["authenticated"]);
    expect(fake.getTurnstileToken).toHaveBeenCalledTimes(1);
    expect(fake.signInWithPassword).toHaveBeenCalledTimes(1);
    expect(fake.signInWithPassword.mock.calls[0]).toEqual([{ email: "a@example.test", password: FAKE_PASSWORD }]);
    expect(document.querySelector("script[data-atlas-turnstile]")).toBeNull();
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  });

  it("sends the verified token as options.captchaToken in exactly one password grant", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", FAKE_SITE_KEY);
    fake.getTurnstileToken.mockResolvedValue({ status: "verified", token: FAKE_TOKEN });
    await renderSignedOut();

    await clickSignIn();

    expect(results).toEqual(["authenticated"]);
    expect(fake.getTurnstileToken).toHaveBeenCalledTimes(1);
    expect(fake.signInWithPassword).toHaveBeenCalledTimes(1);
    expect(fake.signInWithPassword).toHaveBeenCalledWith({
      email: "a@example.test",
      password: FAKE_PASSWORD,
      options: { captchaToken: FAKE_TOKEN },
    });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(document.body.textContent ?? "").not.toContain(FAKE_TOKEN);
    // The Admin client keeps its own default storage, isolated from the visitor key.
    const clientOptions = fake.createClient.mock.calls[0][2] as { auth: Record<string, unknown> };
    expect(clientOptions.auth.storageKey).toBeUndefined();
  });

  it.each([
    ["failed", () => fake.getTurnstileToken.mockResolvedValue({ status: "failed" })],
    ["rejected", () => fake.getTurnstileToken.mockRejectedValue(new Error(`${FAKE_TOKEN} ${FAKE_SITE_KEY}`))],
    ["empty token", () => fake.getTurnstileToken.mockResolvedValue({ status: "verified", token: "" })],
    ["whitespace token", () => fake.getTurnstileToken.mockResolvedValue({ status: "verified", token: "   " })],
    ["non-string token", () => fake.getTurnstileToken.mockResolvedValue({ status: "verified", token: 42 })],
    ["unknown status", () => fake.getTurnstileToken.mockResolvedValue({ status: "unexpected" })],
    ["undefined result", () => fake.getTurnstileToken.mockResolvedValue(undefined)],
    ["null result", () => fake.getTurnstileToken.mockResolvedValue(null)],
  ])("fails closed without calling Supabase when verification is %s", async (_label, arrange) => {
    arrange();
    await renderSignedOut();

    await clickSignIn();

    expect(results).toEqual(["verification_failed"]);
    expect(fake.signInWithPassword).not.toHaveBeenCalled();
    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    expect(document.body.textContent ?? "").not.toContain(FAKE_TOKEN);
  });

  it("does not mask a legitimate Auth failure after a verified challenge", async () => {
    fake.getTurnstileToken.mockResolvedValue({ status: "verified", token: FAKE_TOKEN });
    fake.signInWithPassword.mockResolvedValue({ data: { session: null }, error: { message: "Invalid login credentials" } });
    await renderSignedOut();

    await clickSignIn();

    expect(results).toEqual(["failed"]);
    expect(fake.signInWithPassword).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");

    fake.signInWithPassword.mockRejectedValue(new Error("provider-internal-detail"));
    await clickSignIn();
    expect(results).toEqual(["failed", "failed"]);
  });

  it("requests a fresh token for every attempt and never reuses one", async () => {
    fake.getTurnstileToken
      .mockResolvedValueOnce({ status: "verified", token: "fake-admin-turnstile-token-1" })
      .mockResolvedValueOnce({ status: "verified", token: "fake-admin-turnstile-token-2" });
    fake.signInWithPassword.mockResolvedValueOnce({ data: { session: null }, error: { message: "x" } });
    await renderSignedOut();

    await clickSignIn();
    await clickSignIn();

    expect(fake.getTurnstileToken).toHaveBeenCalledTimes(2);
    const tokens = fake.signInWithPassword.mock.calls.map(
      (call) => (call[0] as { options?: { captchaToken?: string } }).options?.captchaToken,
    );
    expect(tokens).toEqual(["fake-admin-turnstile-token-1", "fake-admin-turnstile-token-2"]);
    expect(results).toEqual(["failed", "authenticated"]);
  });

  it("retries after a failed verification with a new challenge", async () => {
    fake.getTurnstileToken
      .mockResolvedValueOnce({ status: "failed" })
      .mockResolvedValueOnce({ status: "verified", token: FAKE_TOKEN });
    await renderSignedOut();

    await clickSignIn();
    await clickSignIn();

    expect(results).toEqual(["verification_failed", "authenticated"]);
    expect(fake.getTurnstileToken).toHaveBeenCalledTimes(2);
    expect(fake.signInWithPassword).toHaveBeenCalledTimes(1);
  });

  it("joins concurrent submits into one challenge and one password grant", async () => {
    let release: (value: unknown) => void = () => undefined;
    fake.getTurnstileToken.mockImplementation(() => new Promise((r) => (release = r)));
    await renderSignedOut();

    let first: Promise<unknown> = Promise.resolve();
    let second: Promise<unknown> = Promise.resolve();
    act(() => {
      first = signIn("a@example.test", FAKE_PASSWORD);
      second = signIn("a@example.test", FAKE_PASSWORD);
    });
    expect(second).toBe(first);

    await act(async () => release({ status: "verified", token: FAKE_TOKEN }));
    await expect(first).resolves.toBe("authenticated");
    await expect(second).resolves.toBe("authenticated");

    expect(fake.getTurnstileToken).toHaveBeenCalledTimes(1);
    expect(fake.signInWithPassword).toHaveBeenCalledTimes(1);
  });

  it("never runs a challenge on import, bootstrap, restore, refresh, API calls or sign-out", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", FAKE_SITE_KEY);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    fake.getSession.mockResolvedValue({ data: { session: SESSION }, error: null });
    render(
      <AdminAuthProvider>
        <StatusProbe />
      </AdminAuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    act(() => fake.listener?.("TOKEN_REFRESHED", { ...SESSION, refresh_token: "fake-refresh-token" }));
    await adminFetch("/admin/datasets");
    fireEvent.click(screen.getByRole("button", { name: "sign-out" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    expect(fake.getTurnstileToken).not.toHaveBeenCalled();
    expect(fake.signInWithPassword).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("fails without a challenge when the Admin client is unavailable", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "");
    render(
      <AdminAuthProvider>
        <Capture />
      </AdminAuthProvider>,
    );

    await clickSignIn();

    expect(results).toEqual(["failed"]);
    expect(fake.getTurnstileToken).not.toHaveBeenCalled();
    expect(fake.signInWithPassword).not.toHaveBeenCalled();
  });
});
