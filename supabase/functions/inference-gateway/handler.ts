// M52-04: runtime-agnostic inference gateway handler.
//
// Pure logic only: this module imports nothing and touches only web-standard
// Request/Response/Headers/fetch/AbortSignal so it runs unchanged under Deno,
// Node with native type stripping and the Supabase Edge runtime. All
// environment access, JWT verification and the reservation RPC are injected by
// index.ts (production) or by handler.test.ts (controlled fakes).
//
// Fixed order (never reordered):
//   route/method/slug -> config -> JWT -> anonymous check -> cheap
//   pre-reservation validation -> atomic reservation -> forward.
// The gateway never computes the quota window or limit and has no
// decrement/restore path: a consumed unit stays consumed.

export const FUNCTION_NAME = "inference-gateway";
export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const SLUG_MAX_LENGTH = 128;
export const SUBJECT_MAX_LENGTH = 128;
export const MAX_BODY_BYTES = 1_048_576;
export const UPSTREAM_TIMEOUT_MS = 15_000;
export const GATEWAY_TOKEN_HEADER = "x-atlas-gateway-token";
export const CORS_MAX_AGE_SECONDS = "86400";

const ALLOW_METHODS = "POST, OPTIONS";
const ALLOW_HEADERS = "authorization, content-type, apikey, x-client-info";
const PASS_THROUGH_RESPONSE_HEADERS = ["content-type", "cache-control"];
const BODYLESS_STATUSES = [204, 205, 304];

export interface GatewayConfig {
  // Value of the ATLAS_GATEWAY_TOKEN function secret.
  atlasToken?: string | null;
  // Value of ATLAS_GATEWAY_BASE_URL (includes the /api prefix).
  atlasBaseUrl?: string | null;
  // Comma-separated ATLAS_GATEWAY_ALLOWED_ORIGINS.
  allowedOrigins?: string | null;
  // False when SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing.
  platformConfigured: boolean;
}

export interface GatewayDeps {
  config: GatewayConfig;
  // Resolves to the verified JWT claims or rejects for any invalid token.
  verifyJwt: (token: string) => Promise<Record<string, unknown>>;
  // Resolves to the raw RPC data of public.reserve_inference_usage; rejects on
  // any RPC error. The handler validates the shape itself.
  reserve: (subjectId: string, datasetSlug: string) => Promise<unknown>;
  forward: (url: string, init: RequestInit) => Promise<Response>;
  // Receives exactly one JSON line per handled (non-preflight) request.
  log: (line: string) => void;
}

export type Outcome =
  | "accepted"
  | "rate_limited"
  | "rejected_auth"
  | "rejected_invalid"
  | "reservation_error"
  | "upstream_error"
  | "misconfigured";

type ErrorKind =
  | "NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "UNAUTHENTICATED"
  | "INVALID_REQUEST"
  | "PAYLOAD_TOO_LARGE"
  | "QUOTA_EXCEEDED"
  | "RESERVATION_UNAVAILABLE"
  | "MISCONFIGURED"
  | "UPSTREAM_UNAVAILABLE"
  | "UPSTREAM_TIMEOUT";

const ERROR_TABLE: Record<ErrorKind, { status: number; message: string }> = {
  NOT_FOUND: { status: 404, message: "Resource not found." },
  METHOD_NOT_ALLOWED: { status: 405, message: "Method not allowed." },
  UNAUTHENTICATED: { status: 401, message: "Authentication required." },
  INVALID_REQUEST: { status: 400, message: "Invalid request." },
  PAYLOAD_TOO_LARGE: { status: 413, message: "Request payload too large." },
  QUOTA_EXCEEDED: { status: 429, message: "Request limit reached. Try again later." },
  RESERVATION_UNAVAILABLE: { status: 503, message: "Service temporarily unavailable." },
  MISCONFIGURED: { status: 503, message: "Service temporarily unavailable." },
  UPSTREAM_UNAVAILABLE: { status: 502, message: "Upstream service unavailable." },
  UPSTREAM_TIMEOUT: { status: 504, message: "Upstream service timed out." },
};

interface ResolvedConfig {
  atlasToken: string;
  atlasBaseUrl: string;
}

interface Reservation {
  allowed: boolean;
  retryAfterSeconds: number;
}

function parseOrigins(raw: string | null | undefined): string[] {
  if (typeof raw !== "string") return [];
  return raw
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0 && entry !== "*");
}

function isLocalHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function isValidOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && url.origin === value;
  } catch {
    return false;
  }
}

// Returns null for any missing, blank or invalid value (fail closed).
function resolveConfig(config: GatewayConfig): ResolvedConfig | null {
  if (config.platformConfigured !== true) return null;

  const token = typeof config.atlasToken === "string" ? config.atlasToken.trim() : "";
  if (token.length === 0 || !/^[\x21-\x7e]+$/.test(token)) return null;

  const origins = parseOrigins(config.allowedOrigins);
  if (origins.length === 0 || !origins.every(isValidOrigin)) return null;
  if (typeof config.allowedOrigins === "string" && config.allowedOrigins.includes("*")) return null;

  const rawBase = typeof config.atlasBaseUrl === "string" ? config.atlasBaseUrl.trim() : "";
  if (rawBase.length === 0) return null;
  let base: URL;
  try {
    base = new URL(rawBase);
  } catch {
    return null;
  }
  const secure = base.protocol === "https:";
  const localPlain = base.protocol === "http:" && isLocalHost(base.hostname);
  if (!secure && !localPlain) return null;
  if (base.username || base.password || base.search || base.hash) return null;

  return {
    atlasToken: token,
    atlasBaseUrl: `${base.origin}${base.pathname.replace(/\/+$/, "")}`,
  };
}

function corsHeaders(request: Request, origins: string[], preflight: boolean): Headers {
  const headers = new Headers();
  headers.set("vary", "Origin");
  const origin = request.headers.get("origin");
  if (origin !== null && origins.includes(origin)) {
    headers.set("access-control-allow-origin", origin);
    headers.set("access-control-expose-headers", "Retry-After");
    if (preflight) {
      headers.set("access-control-allow-methods", ALLOW_METHODS);
      headers.set("access-control-allow-headers", ALLOW_HEADERS);
      headers.set("access-control-max-age", CORS_MAX_AGE_SECONDS);
    }
  }
  return headers;
}

function errorResponse(kind: ErrorKind, cors: Headers, extra?: Record<string, string>): Response {
  const { status, message } = ERROR_TABLE[kind];
  const headers = new Headers(cors);
  headers.set("content-type", "application/json");
  headers.set("cache-control", "no-store");
  if (extra) {
    for (const [name, value] of Object.entries(extra)) headers.set(name, value);
  }
  return new Response(JSON.stringify({ error: { code: `GATEWAY_${kind}`, message } }), {
    status,
    headers,
  });
}

async function readBodyCapped(request: Request, cap: number): Promise<Uint8Array | null> {
  if (!request.body) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > cap) {
      try {
        await reader.cancel();
      } catch {
        // Nothing to recover; the request is rejected either way.
      }
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function isJson(bytes: Uint8Array): boolean {
  try {
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    return true;
  } catch {
    return false;
  }
}

function parseReservation(data: unknown): Reservation | null {
  if (!Array.isArray(data) || data.length !== 1) return null;
  const row = data[0];
  if (row === null || typeof row !== "object") return null;
  const { allowed, request_count, retry_after_seconds } = row as Record<string, unknown>;
  if (typeof allowed !== "boolean") return null;
  if (typeof request_count !== "number" || !Number.isInteger(request_count)) return null;
  if (
    typeof retry_after_seconds !== "number" ||
    !Number.isInteger(retry_after_seconds) ||
    retry_after_seconds < 1 ||
    retry_after_seconds > 600
  ) {
    return null;
  }
  return { allowed, retryAfterSeconds: retry_after_seconds };
}

function isTimeout(error: unknown): boolean {
  if (error === null || typeof error !== "object") return false;
  const name = (error as { name?: unknown }).name;
  return name === "TimeoutError" || name === "AbortError";
}

function emit(deps: GatewayDeps, outcome: Outcome, datasetSlug: string | null): void {
  const entry: Record<string, string> = { event: "inference_gateway" };
  if (datasetSlug !== null) entry.dataset_slug = datasetSlug;
  entry.outcome = outcome;
  try {
    deps.log(JSON.stringify(entry));
  } catch {
    // Observability must never change the response.
  }
}

export async function handleRequest(request: Request, deps: GatewayDeps): Promise<Response> {
  const origins = parseOrigins(deps.config.allowedOrigins);
  const cors = corsHeaders(request, origins, false);
  let datasetSlug: string | null = null;

  const finish = (response: Response, outcome: Outcome): Response => {
    emit(deps, outcome, datasetSlug);
    return response;
  };

  // 1. route / method / slug
  const match = /^\/inference-gateway\/([^/]+)\/?$/.exec(new URL(request.url).pathname);
  if (match === null) return finish(errorResponse("NOT_FOUND", cors), "rejected_invalid");

  if (request.method === "OPTIONS") {
    // Preflight: no outcome fits a preflight, so it is not logged.
    return new Response(null, { status: 204, headers: corsHeaders(request, origins, true) });
  }
  if (request.method !== "POST") {
    return finish(
      errorResponse("METHOD_NOT_ALLOWED", cors, { allow: ALLOW_METHODS }),
      "rejected_invalid",
    );
  }

  const slug = match[1];
  if (slug.length > SLUG_MAX_LENGTH || !SLUG_PATTERN.test(slug)) {
    return finish(errorResponse("NOT_FOUND", cors), "rejected_invalid");
  }
  datasetSlug = slug;

  // 2. secrets / configuration, before any verification or reservation
  const config = resolveConfig(deps.config);
  if (config === null) return finish(errorResponse("MISCONFIGURED", cors), "misconfigured");

  // 3. JWT verification
  const authorization = request.headers.get("authorization");
  const bearer = authorization === null ? null : /^Bearer\s+(\S+)$/i.exec(authorization.trim());
  if (bearer === null) return finish(errorResponse("UNAUTHENTICATED", cors), "rejected_auth");
  let claims: Record<string, unknown>;
  try {
    claims = await deps.verifyJwt(bearer[1]);
  } catch {
    return finish(errorResponse("UNAUTHENTICATED", cors), "rejected_auth");
  }

  // 4. anonymous check; the subject comes only from the verified sub claim
  const subject = claims === null || typeof claims !== "object" ? undefined : claims.sub;
  if (
    claims === null ||
    typeof claims !== "object" ||
    claims.is_anonymous !== true ||
    typeof subject !== "string" ||
    subject.trim().length === 0 ||
    subject.length > SUBJECT_MAX_LENGTH
  ) {
    return finish(errorResponse("UNAUTHENTICATED", cors), "rejected_auth");
  }

  // 5. cheap pre-reservation validation (does not consume a unit)
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    if (!/^\d+$/.test(declaredLength.trim())) {
      return finish(errorResponse("INVALID_REQUEST", cors), "rejected_invalid");
    }
    if (Number(declaredLength.trim()) > MAX_BODY_BYTES) {
      return finish(errorResponse("PAYLOAD_TOO_LARGE", cors), "rejected_invalid");
    }
  }
  let body: Uint8Array | null;
  try {
    body = await readBodyCapped(request, MAX_BODY_BYTES);
  } catch {
    return finish(errorResponse("INVALID_REQUEST", cors), "rejected_invalid");
  }
  if (body === null) return finish(errorResponse("PAYLOAD_TOO_LARGE", cors), "rejected_invalid");
  if (!isJson(body)) return finish(errorResponse("INVALID_REQUEST", cors), "rejected_invalid");

  // 6. atomic reservation; any failure or malformed result fails closed
  let reservation: Reservation | null;
  try {
    reservation = parseReservation(await deps.reserve(subject, slug));
  } catch {
    reservation = null;
  }
  if (reservation === null) {
    return finish(errorResponse("RESERVATION_UNAVAILABLE", cors), "reservation_error");
  }
  if (!reservation.allowed) {
    return finish(
      errorResponse("QUOTA_EXCEEDED", cors, { "retry-after": String(reservation.retryAfterSeconds) }),
      "rate_limited",
    );
  }

  // 7. forward; the unit stays consumed on any upstream failure
  const forwardHeaders = new Headers();
  forwardHeaders.set("content-type", request.headers.get("content-type") ?? "application/json");
  forwardHeaders.set(GATEWAY_TOKEN_HEADER, config.atlasToken);

  let upstream: Response;
  let upstreamBody: ArrayBuffer;
  try {
    upstream = await deps.forward(`${config.atlasBaseUrl}/datasets/${slug}/inference`, {
      method: "POST",
      headers: forwardHeaders,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    upstreamBody = await upstream.arrayBuffer();
  } catch (error) {
    return finish(
      errorResponse(isTimeout(error) ? "UPSTREAM_TIMEOUT" : "UPSTREAM_UNAVAILABLE", cors),
      "upstream_error",
    );
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    return finish(errorResponse("UPSTREAM_UNAVAILABLE", cors), "upstream_error");
  }

  const responseHeaders = new Headers(cors);
  for (const name of PASS_THROUGH_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  try {
    return finish(
      new Response(BODYLESS_STATUSES.includes(upstream.status) ? null : upstreamBody, {
        status: upstream.status,
        headers: responseHeaders,
      }),
      "accepted",
    );
  } catch {
    return finish(errorResponse("UPSTREAM_UNAVAILABLE", cors), "upstream_error");
  }
}
