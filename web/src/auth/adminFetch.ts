// M51-04: single authenticated transport for /admin/* browser requests.
//
// The Admin pages issue requests from module-level functions that cannot call
// hooks, so AdminAuthProvider registers a session source here. The access token
// is read from that source on every call and is never stored in this module.
// The helper never navigates: unrecoverable session loss is reported through
// the registered terminateSession(), and the existing session guard redirects.

export type AdminSessionSource = {
  getAccessToken: () => Promise<string | null>;
  terminateSession: () => void;
};

// Generic on purpose: never carries token, header or URL-query material.
export class AdminSessionError extends Error {
  constructor(message = "Admin session is not available.") {
    super(message);
    this.name = "AdminSessionError";
  }
}

let currentSource: AdminSessionSource | null = null;

// Returns a function that restores the previously registered source only if
// this registration is still the active one (StrictMode-idempotent cleanup).
export function registerAdminSessionSource(source: AdminSessionSource | null): () => void {
  const previous = currentSource;
  currentSource = source;
  return () => {
    if (currentSource === source) {
      currentSource = previous === source ? null : previous;
    }
  };
}

const PARSE_BASE = "http://admin-fetch.invalid";

function configuredBasePath(): string {
  const base = String(import.meta.env.VITE_API_BASE_URL ?? "").trim();
  if (!base) {
    return "";
  }
  try {
    return new URL(base, PARSE_BASE).pathname.replace(/\/+$/, "");
  } catch {
    return "";
  }
}

function isAdminTarget(input: string): boolean {
  let pathname: string;
  try {
    pathname = new URL(input, PARSE_BASE).pathname;
  } catch {
    return false;
  }
  const basePath = configuredBasePath();
  if (basePath && pathname.startsWith(`${basePath}/`)) {
    pathname = pathname.slice(basePath.length);
  }
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

function terminate(source: AdminSessionSource): void {
  try {
    source.terminateSession();
  } catch {
    // Termination is best effort; the caller still fails closed.
  }
}

export async function adminFetch(input: string, init?: RequestInit): Promise<Response> {
  if (!isAdminTarget(input)) {
    throw new AdminSessionError("adminFetch only serves /admin/ requests.");
  }
  const source = currentSource;
  if (!source) {
    throw new AdminSessionError();
  }
  let token: string | null;
  try {
    token = await source.getAccessToken();
  } catch {
    token = null;
  }
  if (!token) {
    terminate(source);
    throw new AdminSessionError();
  }
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}
