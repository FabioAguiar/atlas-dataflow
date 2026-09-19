// M52-01: transparent Supabase Anonymous Auth identity for public visitors.
//
// Public API: `getVisitorAccess()` returns a `VisitorAccessResult` and never
// throws. `available` carries the anonymous access token; `unavailable` carries
// a closed reason code. There is no unauthenticated fallback of any kind, no
// UI, and nothing runs at page load or module import: the first call that needs
// an identity performs the (single, shared) anonymous sign-in.
//
// Isolation: this module owns its own Supabase client with a dedicated
// `storageKey`, distinct from the default key used by the Admin client, and it
// imports nothing from the Admin auth modules. It reads only the two
// publishable VITE_SUPABASE_* variables. Tokens, subjects, URLs, keys and error
// messages are never logged or persisted outside the Supabase client storage.
//
// External prerequisite (not verifiable from this repository): Anonymous Auth
// must be enabled on the hosted Supabase project, otherwise sign-in fails and
// the accessor reports `unavailable` / `sign_in_failed`.

import type { SupabaseClient } from "@supabase/supabase-js";

export type VisitorUnavailableReason =
  | "not_configured"
  | "sign_in_failed"
  | "session_invalid"
  | "client_error";

export type VisitorAccessResult =
  | { accessToken: string; isAnonymous: true; status: "available"; subject: string }
  | { reason: VisitorUnavailableReason; status: "unavailable" };

export const VISITOR_STORAGE_KEY = "atlas-visitor-auth";

// A persisted session is reused only while it is valid for longer than this.
const REUSE_MARGIN_MS = 30_000;

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

const unavailable = (reason: VisitorUnavailableReason): VisitorAccessResult => ({
  reason,
  status: "unavailable",
});

type VisitorSession = {
  access_token: string;
  expires_at?: number;
  user: { id: string; is_anonymous?: boolean };
};

function toResult(session: VisitorSession | null | undefined): VisitorAccessResult {
  if (!session || !session.access_token || !session.user?.id) {
    return unavailable("sign_in_failed");
  }
  if (session.user.is_anonymous !== true) {
    return unavailable("session_invalid");
  }
  return {
    accessToken: session.access_token,
    isAnonymous: true,
    status: "available",
    subject: session.user.id,
  };
}

let clientPromise: Promise<SupabaseClient | null> | null = null;
let inFlight: Promise<VisitorAccessResult> | null = null;

async function loadClient(): Promise<SupabaseClient | null> {
  const config = readSupabaseConfig();
  if (!config) {
    return null;
  }
  if (!clientPromise) {
    clientPromise = import("@supabase/supabase-js")
      .then(({ createClient }) =>
        createClient(config.url, config.publishableKey, {
          auth: {
            autoRefreshToken: true,
            detectSessionInUrl: false,
            persistSession: true,
            storageKey: VISITOR_STORAGE_KEY,
          },
        }),
      )
      .catch(() => {
        clientPromise = null;
        return null;
      });
  }
  return clientPromise;
}

async function signInAnonymously(client: SupabaseClient): Promise<VisitorAccessResult> {
  try {
    const { data, error } = await client.auth.signInAnonymously();
    if (error) {
      return unavailable("sign_in_failed");
    }
    return toResult(data?.session);
  } catch {
    return unavailable("sign_in_failed");
  }
}

async function resolveVisitorAccess(): Promise<VisitorAccessResult> {
  if (!readSupabaseConfig()) {
    return unavailable("not_configured");
  }
  const client = await loadClient();
  if (!client) {
    return unavailable("client_error");
  }

  let session: VisitorSession | null;
  try {
    const { data, error } = await client.auth.getSession();
    if (error) {
      return unavailable("client_error");
    }
    session = (data?.session as VisitorSession | null | undefined) ?? null;
  } catch {
    return unavailable("client_error");
  }

  if (!session) {
    return signInAnonymously(client);
  }
  // A stray non-anonymous session under this key is never reused or signed out.
  if (session.user?.is_anonymous !== true) {
    return unavailable("session_invalid");
  }
  if (session.expires_at !== undefined && session.expires_at * 1000 - Date.now() > REUSE_MARGIN_MS) {
    return toResult(session);
  }

  try {
    const { data, error } = await client.auth.refreshSession();
    if (!error && data?.session) {
      return toResult(data.session as VisitorSession);
    }
  } catch {
    // Fall through to replacement sign-in.
  }
  return signInAnonymously(client);
}

export function getVisitorAccess(): Promise<VisitorAccessResult> {
  if (!inFlight) {
    inFlight = resolveVisitorAccess()
      .catch(() => unavailable("client_error"))
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}

// Test-only: drops the cached client and any in-flight promise.
export function resetVisitorSessionForTests(): void {
  clientPromise = null;
  inFlight = null;
}
