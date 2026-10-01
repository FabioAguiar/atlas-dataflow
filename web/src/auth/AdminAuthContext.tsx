import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet } from "react-router-dom";

import { registerAdminSessionSource } from "./adminFetch";
import { getTurnstileToken } from "./turnstile";

// M51-03: private Admin browser-session boundary. This module is reached only
// through the conditional lazy() imports in App.tsx (VITE_ENABLE_ADMIN build),
// so the Supabase client never enters the public bundle. The Supabase client
// owns session persistence and token refresh; this module only exposes a small
// session state machine and generic-only failure surfaces.
//
// Supabase Auth CAPTCHA is global per route: once enabled it also covers
// /token?grant_type=password. A new password sign-in therefore obtains a
// Turnstile token through the shared lazy helper first. An empty
// VITE_TURNSTILE_SITE_KEY keeps the previous behaviour; refresh, restore,
// API calls and sign-out never run a challenge.

export type AdminAuthStatus = "loading" | "authenticated" | "unauthenticated" | "unrecoverable";

// "verification_failed": the Turnstile challenge did not produce a token, so
// Supabase was never called. "failed": any other sign-in failure.
export type AdminSignInResult = "authenticated" | "failed" | "verification_failed";

export type AdminAuthContextValue = {
  email: string | null;
  status: AdminAuthStatus;
  signInWithEmailPassword: (email: string, password: string) => Promise<AdminSignInResult>;
  signOut: () => Promise<void>;
};

const ADMIN_LOGIN_PATH = "/admin/login";

type SupabaseConfig = { publishableKey: string; url: string };

// Invalid means missing, blank after trim, or a URL that is not a parseable
// http(s) URL. Read at call time (never at module top level).
function readSupabaseConfig(): SupabaseConfig | null {
  const url = String(import.meta.env.VITE_SUPABASE_URL ?? "").trim();
  const publishableKey = String(import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "").trim();
  if (!url || !publishableKey) {
    return null;
  }
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
  } catch {
    return null;
  }
  return { publishableKey, url };
}

function constructClient(config: SupabaseConfig): SupabaseClient | null {
  try {
    return createClient(config.url, config.publishableKey, {
      auth: { autoRefreshToken: true, detectSessionInUrl: false, persistSession: true },
    });
  } catch {
    return null;
  }
}

// One logical Admin client per provider lifecycle. React StrictMode invokes
// state initializers (and effects) twice; without sharing, that would build two
// clients that each own a token-refresh timer and storage listener. The shared
// slot is keyed by config, retained by mounted providers, and released one
// microtask after the last provider unmounts (StrictMode's synchronous
// unmount/remount therefore keeps the same client). It lives only inside this
// lazily imported module, so it never enters the public build and is unrelated
// to the visitor session client.
let sharedClient: { client: SupabaseClient; key: string } | null = null;
let clientHolders = 0;

function acquireClient(): SupabaseClient | null {
  const config = readSupabaseConfig();
  if (!config) {
    return null;
  }
  const key = `${config.url}\n${config.publishableKey}`;
  if (sharedClient && sharedClient.key === key) {
    return sharedClient.client;
  }
  // A failed construction is not shared, so a later mount can retry.
  const client = constructClient(config);
  sharedClient = client ? { client, key } : null;
  return client;
}

function retainClient(): () => void {
  clientHolders += 1;
  return () => {
    clientHolders -= 1;
    if (clientHolders === 0) {
      queueMicrotask(() => {
        if (clientHolders === 0) {
          sharedClient = null;
        }
      });
    }
  };
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [client] = useState<SupabaseClient | null>(acquireClient);
  const [status, setStatus] = useState<AdminAuthStatus>(client ? "loading" : "unrecoverable");
  // Live, in-memory projection of the signed-in user; never persisted or logged.
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => (client ? retainClient() : undefined), [client]);

  useEffect(() => {
    if (!client) {
      return undefined;
    }
    let cancelled = false;

    const { data } = client.auth.onAuthStateChange((_event, session) => {
      if (!cancelled) {
        setStatus(session ? "authenticated" : "unauthenticated");
        setEmail(session?.user?.email ?? null);
      }
    });

    // A getSession() result only settles the initial loading state; a newer
    // auth event (for example SIGNED_OUT) is never overwritten by a late result.
    const settle = (next: AdminAuthStatus) => {
      if (!cancelled) {
        setStatus((current) => (current === "loading" ? next : current));
      }
    };
    client.auth
      .getSession()
      .then(({ data: sessionData, error }) => {
        if (!cancelled && !error && sessionData.session) {
          setEmail((current) => current ?? sessionData.session?.user?.email ?? null);
        }
        settle(error ? "unrecoverable" : sessionData.session ? "authenticated" : "unauthenticated");
      })
      .catch(() => settle("unrecoverable"));

    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, [client]);

  // Single-flight: a submit while a sign-in is pending joins it instead of
  // starting a second challenge and a second password grant.
  const pendingSignIn = useRef<Promise<AdminSignInResult> | null>(null);

  const signInWithEmailPassword = useCallback(
    (email: string, password: string): Promise<AdminSignInResult> => {
      if (pendingSignIn.current) {
        return pendingSignIn.current;
      }

      const attempt = (async (): Promise<AdminSignInResult> => {
        if (!client) {
          return "failed";
        }

        let verification: Awaited<ReturnType<typeof getTurnstileToken>>;
        try {
          verification = await getTurnstileToken();
        } catch {
          // Any verification-mechanism failure fails closed: no sign-in without it.
          return "verification_failed";
        }

        // Only an explicit "disabled" (rollout off) or a verified non-empty
        // token may proceed; "failed" or any unexpected shape fails closed.
        const captchaToken =
          verification?.status === "verified" && typeof verification.token === "string"
            ? verification.token.trim()
            : "";
        if (!captchaToken && verification?.status !== "disabled") {
          return "verification_failed";
        }

        try {
          // Each token is used for exactly one password grant.
          const { data, error } = captchaToken
            ? await client.auth.signInWithPassword({ email, password, options: { captchaToken } })
            : await client.auth.signInWithPassword({ email, password });
          if (error || !data?.session) {
            return "failed";
          }
          setStatus("authenticated");
          setEmail(data.session.user?.email ?? null);
          return "authenticated";
        } catch {
          return "failed";
        }
      })();

      pendingSignIn.current = attempt;
      void attempt.finally(() => {
        if (pendingSignIn.current === attempt) {
          pendingSignIn.current = null;
        }
      });
      return attempt;
    },
    [client],
  );

  const signOut = useCallback(async (): Promise<void> => {
    try {
      await client?.auth.signOut({ scope: "local" });
    } catch {
      // The local session is always cleared, even if the remote call fails.
    } finally {
      setStatus((current) => (current === "unrecoverable" ? current : "unauthenticated"));
      setEmail(null);
    }
  }, [client]);

  // Single terminal path for adminFetch: same local cleanup as Sign out.
  const terminateSession = useCallback((): void => {
    void signOut();
  }, [signOut]);

  useEffect(() => {
    if (!client) {
      return undefined;
    }
    // The token is read from the Supabase client at every call, never cached.
    return registerAdminSessionSource({
      getAccessToken: async () => {
        const { data, error } = await client.auth.getSession();
        return error ? null : (data.session?.access_token ?? null);
      },
      terminateSession,
    });
  }, [client, terminateSession]);

  const value = useMemo<AdminAuthContextValue>(
    () => ({ email, signInWithEmailPassword, signOut, status }),
    [email, signInWithEmailPassword, signOut, status],
  );

  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

export function useAdminAuth(): AdminAuthContextValue {
  const value = useContext(AdminAuthContext);
  if (!value) {
    throw new Error("useAdminAuth must be used within AdminAuthProvider");
  }
  return value;
}

// Non-throwing variant for AdminShell so stand-alone renders keep working.
export function useOptionalAdminAuth(): AdminAuthContextValue | null {
  return useContext(AdminAuthContext);
}

export function AdminAuthRoot() {
  return (
    <AdminAuthProvider>
      <Outlet />
    </AdminAuthProvider>
  );
}

export function AdminSessionGuard() {
  const { status } = useAdminAuth();

  if (status === "loading") {
    return null;
  }
  if (status === "authenticated") {
    return <Outlet />;
  }
  return <Navigate replace to={ADMIN_LOGIN_PATH} />;
}
