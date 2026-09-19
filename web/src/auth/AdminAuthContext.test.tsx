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
  listener: null as null | ((event: string, session: unknown) => void),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  unsubscribe: vi.fn(),
}));

vi.mock("@supabase/supabase-js", () => ({ createClient: fake.createClient }));

import {
  AdminAuthProvider,
  AdminAuthRoot,
  AdminSessionGuard,
  useAdminAuth,
  useOptionalAdminAuth,
} from "./AdminAuthContext";

const SESSION = { access_token: "fake-access-token", user: { id: "fake-user" } };

function StatusProbe() {
  const { signInWithEmailPassword, signOut, status } = useAdminAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
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
    expect(result).toBe(false);

    fake.signInWithPassword.mockRejectedValue(new Error("provider-internal-detail"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "go" })));
    expect(result).toBe(false);

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
