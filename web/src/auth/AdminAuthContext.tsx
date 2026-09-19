import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet } from "react-router-dom";

import { registerAdminSessionSource } from "./adminFetch";

// M51-03: private Admin browser-session boundary. This module is reached only
// through the conditional lazy() imports in App.tsx (VITE_ENABLE_ADMIN build),
// so the Supabase client never enters the public bundle. The Supabase client
// owns session persistence and token refresh; this module only exposes a small
// session state machine and generic-only failure surfaces.

export type AdminAuthStatus = "loading" | "authenticated" | "unauthenticated" | "unrecoverable";

export type AdminAuthContextValue = {
  email: string | null;
  status: AdminAuthStatus;
  signInWithEmailPassword: (email: string, password: string) => Promise<boolean>;
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

function constructClient(): SupabaseClient | null {
  const config = readSupabaseConfig();
  if (!config) {
    return null;
  }
  try {
    return createClient(config.url, config.publishableKey, {
      auth: { autoRefreshToken: true, detectSessionInUrl: false, persistSession: true },
    });
  } catch {
    return null;
  }
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [client] = useState<SupabaseClient | null>(constructClient);
  const [status, setStatus] = useState<AdminAuthStatus>(client ? "loading" : "unrecoverable");
  // Live, in-memory projection of the signed-in user; never persisted or logged.
  const [email, setEmail] = useState<string | null>(null);

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

  const signInWithEmailPassword = useCallback(
    async (email: string, password: string): Promise<boolean> => {
      if (!client) {
        return false;
      }
      try {
        const { data, error } = await client.auth.signInWithPassword({ email, password });
        if (error || !data?.session) {
          return false;
        }
        setStatus("authenticated");
        setEmail(data.session.user?.email ?? null);
        return true;
      } catch {
        return false;
      }
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
