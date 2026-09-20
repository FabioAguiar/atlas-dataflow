// M52-04: offline tests for handler.ts using controlled fakes.
// Erasable-syntax-only TypeScript; runs with `node --test` (native type
// stripping) and `deno test`. No network, database or clock is used.
import test from "node:test";
import assert from "node:assert/strict";
import { handleRequest, MAX_BODY_BYTES, UPSTREAM_TIMEOUT_MS } from "./handler.ts";
import type { GatewayConfig, GatewayDeps } from "./handler.ts";

const ORIGIN = "https://atlas.example.test";
const ATLAS_TOKEN = "atlas-token-placeholder-value";
const BASE_URL = "https://atlas-origin.example.test/api";
const SUBJECT = "visitor-subject-1";
const SLUG = "telco-churn";
const VALID_BODY = JSON.stringify({ features: { tenure: 12 } });
const LIMIT = 10;
const RETRY_AFTER = 300;

const OUTCOMES = [
  "accepted",
  "rate_limited",
  "rejected_auth",
  "rejected_invalid",
  "reservation_error",
  "upstream_error",
  "misconfigured",
];

interface Harness {
  deps: GatewayDeps;
  calls: string[];
  reserveArgs: string[][];
  forwarded: { url: string; init: RequestInit }[];
  logs: string[];
}

interface Options {
  config?: Partial<GatewayConfig>;
  reserve?: (subjectId: string, datasetSlug: string) => Promise<unknown>;
  forward?: (url: string, init: RequestInit) => Promise<Response>;
}

function goodConfig(): GatewayConfig {
  return {
    atlasToken: ATLAS_TOKEN,
    atlasBaseUrl: BASE_URL,
    allowedOrigins: ORIGIN,
    platformConfigured: true,
  };
}

function harness(options: Options = {}): Harness {
  const calls: string[] = [];
  const reserveArgs: string[][] = [];
  const forwarded: { url: string; init: RequestInit }[] = [];
  const logs: string[] = [];
  const counts = new Map<string, number>();

  const fakeVerify = async (token: string): Promise<Record<string, unknown>> => {
    calls.push("verify");
    if (token === "valid-anonymous") return { sub: SUBJECT, is_anonymous: true, role: "authenticated" };
    if (token === "admin-like") return { sub: "admin-1", is_anonymous: false, role: "authenticated" };
    if (token === "marker-missing") return { sub: "no-marker-1", role: "authenticated" };
    if (token === "blank-sub") return { sub: "   ", is_anonymous: true };
    if (token === "long-sub") return { sub: "s".repeat(129), is_anonymous: true };
    if (token === "numeric-sub") return { sub: 42, is_anonymous: true };
    throw new Error("invalid token detail that must never be echoed");
  };

  const fakeReserve = async (subjectId: string, datasetSlug: string): Promise<unknown> => {
    calls.push("reserve");
    reserveArgs.push([subjectId, datasetSlug]);
    const key = `${subjectId}|${datasetSlug}`;
    const next = (counts.get(key) ?? 0) + 1;
    if (next > LIMIT) {
      return [{ allowed: false, request_count: LIMIT, retry_after_seconds: RETRY_AFTER }];
    }
    counts.set(key, next);
    return [{ allowed: true, request_count: next, retry_after_seconds: RETRY_AFTER }];
  };

  const fakeForward = async (url: string, init: RequestInit): Promise<Response> => {
    calls.push("forward");
    forwarded.push({ url, init });
    return new Response(JSON.stringify({ prediction: "no", probability: 0.12 }), {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "no-store",
        "x-atlas-internal": "must-not-leak",
      },
    });
  };

  const deps: GatewayDeps = {
    config: { ...goodConfig(), ...(options.config ?? {}) },
    verifyJwt: fakeVerify,
    reserve: async (subjectId, datasetSlug) => {
      if (options.reserve) {
        calls.push("reserve");
        reserveArgs.push([subjectId, datasetSlug]);
        return options.reserve(subjectId, datasetSlug);
      }
      return fakeReserve(subjectId, datasetSlug);
    },
    forward: async (url, init) => {
      if (options.forward) {
        calls.push("forward");
        forwarded.push({ url, init });
        return options.forward(url, init);
      }
      return fakeForward(url, init);
    },
    log: (line) => {
      logs.push(line);
    },
  };
  return { deps, calls, reserveArgs, forwarded, logs };
}

function post(
  token: string | null,
  body: BodyInit | null = VALID_BODY,
  slug: string = SLUG,
  extraHeaders: Record<string, string> = {},
): Request {
  const headers: Record<string, string> = { "content-type": "application/json", ...extraHeaders };
  if (token !== null) headers.authorization = `Bearer ${token}`;
  return new Request(`https://project.example.test/inference-gateway/${slug}`, {
    method: "POST",
    headers,
    body,
  });
}

async function errorCode(response: Response): Promise<string> {
  const parsed = await response.json() as { error: { code: string } };
  return parsed.error.code;
}

test("under-quota request is forwarded with the gateway credential and Atlas response passes through", async () => {
  const h = harness();
  const response = await handleRequest(post("valid-anonymous", VALID_BODY, SLUG, { origin: ORIGIN }), h.deps);

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { prediction: "no", probability: 0.12 });
  assert.deepEqual(h.calls, ["verify", "reserve", "forward"]);
  assert.deepEqual(h.reserveArgs, [[SUBJECT, SLUG]]);

  const { url, init } = h.forwarded[0];
  assert.equal(url, `${BASE_URL}/datasets/${SLUG}/inference`);
  assert.equal(init.method, "POST");
  assert.equal(init.redirect, "manual");
  assert.ok(init.signal instanceof AbortSignal);
  assert.equal(UPSTREAM_TIMEOUT_MS, 15_000);
  const sent = init.headers as Headers;
  assert.equal(sent.get("x-atlas-gateway-token"), ATLAS_TOKEN);
  assert.equal(sent.get("content-type"), "application/json");
  assert.equal(sent.get("authorization"), null);
  assert.equal(new TextDecoder().decode(init.body as Uint8Array), VALID_BODY);

  assert.equal(response.headers.get("content-type"), "application/json");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("x-atlas-internal"), null);
  assert.equal(response.headers.get("access-control-allow-origin"), ORIGIN);
});

test("eleventh request in a window returns 429 with integer Retry-After and never calls Atlas", async () => {
  const h = harness();
  for (let i = 0; i < LIMIT; i += 1) {
    const ok = await handleRequest(post("valid-anonymous"), h.deps);
    assert.equal(ok.status, 200);
  }
  const limited = await handleRequest(post("valid-anonymous", VALID_BODY, SLUG, { origin: ORIGIN }), h.deps);

  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("retry-after"), String(RETRY_AFTER));
  assert.equal(await errorCode(limited), "GATEWAY_QUOTA_EXCEEDED");
  assert.equal(h.forwarded.length, LIMIT);
  assert.equal(h.calls.filter((c) => c === "reserve").length, LIMIT + 1);
  assert.equal(h.calls[h.calls.length - 1], "reserve");
});

test("burst of concurrent requests forwards at most the limit", async () => {
  const h = harness();
  const responses = await Promise.all(
    Array.from({ length: 15 }, () => handleRequest(post("valid-anonymous"), h.deps)),
  );
  const statuses = responses.map((r) => r.status);
  assert.equal(statuses.filter((s) => s === 200).length, LIMIT);
  assert.equal(statuses.filter((s) => s === 429).length, 5);
  assert.equal(h.forwarded.length, LIMIT);
});

test("quota is keyed per verified subject and dataset slug", async () => {
  const h = harness();
  for (let i = 0; i < LIMIT; i += 1) await handleRequest(post("valid-anonymous"), h.deps);
  const otherDataset = await handleRequest(post("valid-anonymous", VALID_BODY, "other-dataset"), h.deps);
  assert.equal(otherDataset.status, 200);
  assert.deepEqual(h.reserveArgs[h.reserveArgs.length - 1], [SUBJECT, "other-dataset"]);
});

test("missing, malformed and invalid tokens yield a generic 401 before reservation", async () => {
  const h = harness();
  const cases: (string | null)[] = [null, "not-a-real-token"];
  for (const token of cases) {
    const response = await handleRequest(post(token), h.deps);
    assert.equal(response.status, 401);
    assert.equal(await errorCode(response), "GATEWAY_UNAUTHENTICATED");
  }
  const notBearer = new Request(`https://project.example.test/inference-gateway/${SLUG}`, {
    method: "POST",
    headers: { authorization: "Basic abc", "content-type": "application/json" },
    body: VALID_BODY,
  });
  assert.equal((await handleRequest(notBearer, h.deps)).status, 401);
  assert.equal(h.calls.includes("reserve"), false);
  assert.equal(h.calls.includes("forward"), false);
});

test("non-anonymous, marker-missing and bad-subject tokens are rejected identically", async () => {
  const bodies = new Set<string>();
  for (const token of ["admin-like", "marker-missing", "blank-sub", "long-sub", "numeric-sub", "not-a-real-token"]) {
    const h = harness();
    const response = await handleRequest(post(token), h.deps);
    assert.equal(response.status, 401, token);
    bodies.add(await response.text());
    assert.equal(h.calls.includes("reserve"), false, token);
    assert.equal(h.calls.includes("forward"), false, token);
  }
  assert.equal(bodies.size, 1);
});

test("pre-reservation rejections do not consume a unit or call Atlas", async () => {
  const h = harness();

  const notJson = await handleRequest(post("valid-anonymous", "not json"), h.deps);
  assert.equal(notJson.status, 400);
  assert.equal(await errorCode(notJson), "GATEWAY_INVALID_REQUEST");

  const empty = await handleRequest(post("valid-anonymous", ""), h.deps);
  assert.equal(empty.status, 400);

  const oversized = await handleRequest(
    post("valid-anonymous", "{\"pad\":\"" + "a".repeat(MAX_BODY_BYTES) + "\"}"),
    h.deps,
  );
  assert.equal(oversized.status, 413);
  assert.equal(await errorCode(oversized), "GATEWAY_PAYLOAD_TOO_LARGE");

  const declared = {
    method: "POST",
    url: `https://project.example.test/inference-gateway/${SLUG}`,
    headers: new Headers({ authorization: "Bearer valid-anonymous", "content-length": String(MAX_BODY_BYTES + 1) }),
    body: null,
  } as unknown as Request;
  assert.equal((await handleRequest(declared, h.deps)).status, 413);

  const badLength = {
    method: "POST",
    url: `https://project.example.test/inference-gateway/${SLUG}`,
    headers: new Headers({ authorization: "Bearer valid-anonymous", "content-length": "abc" }),
    body: null,
  } as unknown as Request;
  assert.equal((await handleRequest(badLength, h.deps)).status, 400);

  assert.equal(h.calls.includes("reserve"), false);
  assert.equal(h.calls.includes("forward"), false);
});

test("a body exactly at the cap is accepted", async () => {
  const h = harness();
  const prefix = "{\"pad\":\"";
  const suffix = "\"}";
  const pad = "a".repeat(MAX_BODY_BYTES - prefix.length - suffix.length);
  const response = await handleRequest(post("valid-anonymous", prefix + pad + suffix), h.deps);
  assert.equal(response.status, 200);
  assert.equal((h.forwarded[0].init.body as Uint8Array).byteLength, MAX_BODY_BYTES);
});

test("reservation errors and malformed RPC results fail closed with 503 and never forward", async () => {
  const good = { allowed: true, request_count: 1, retry_after_seconds: 60 };
  const malformed: unknown[] = [
    undefined,
    null,
    [],
    {},
    [good, good],
    [null],
    [{ ...good, allowed: "true" }],
    [{ ...good, request_count: "1" }],
    [{ ...good, request_count: 1.5 }],
    [{ ...good, retry_after_seconds: 0 }],
    [{ ...good, retry_after_seconds: 601 }],
    [{ ...good, retry_after_seconds: 1.5 }],
    [{ allowed: true, request_count: 1 }],
  ];
  for (const data of malformed) {
    const h = harness({ reserve: async () => data });
    const response = await handleRequest(post("valid-anonymous"), h.deps);
    assert.equal(response.status, 503, JSON.stringify(data));
    assert.equal(await errorCode(response), "GATEWAY_RESERVATION_UNAVAILABLE");
    assert.equal(h.forwarded.length, 0);
  }

  const failing = harness({
    reserve: async () => {
      throw new Error("rpc failure detail that must never be echoed");
    },
  });
  const response = await handleRequest(post("valid-anonymous"), failing.deps);
  assert.equal(response.status, 503);
  assert.equal(failing.forwarded.length, 0);
  assert.equal((await response.text()).includes("rpc failure detail"), false);
});

test("Atlas failure maps to 502, timeout to 504, and the unit is never restored", async () => {
  const failing = harness({
    forward: async () => {
      throw new TypeError("connection detail that must never be echoed");
    },
  });
  const failed = await handleRequest(post("valid-anonymous"), failing.deps);
  assert.equal(failed.status, 502);
  assert.equal(await errorCode(failed), "GATEWAY_UPSTREAM_UNAVAILABLE");
  assert.deepEqual(failing.calls, ["verify", "reserve", "forward"]);

  const timing = harness({
    forward: async () => {
      throw new DOMException("timed out", "TimeoutError");
    },
  });
  const timedOut = await handleRequest(post("valid-anonymous"), timing.deps);
  assert.equal(timedOut.status, 504);
  assert.equal(await errorCode(timedOut), "GATEWAY_UPSTREAM_TIMEOUT");
  assert.deepEqual(timing.calls, ["verify", "reserve", "forward"]);
});

test("Atlas error statuses pass through unmodified and still consume the unit; redirects are not followed", async () => {
  const rejecting = harness({
    forward: async () =>
      new Response(JSON.stringify({ error: { code: "INVALID_INFERENCE_PAYLOAD" } }), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
  });
  const rejected = await handleRequest(post("valid-anonymous"), rejecting.deps);
  assert.equal(rejected.status, 422);
  assert.deepEqual(await rejected.json(), { error: { code: "INVALID_INFERENCE_PAYLOAD" } });
  assert.equal(rejecting.reserveArgs.length, 1);

  const redirecting = harness({
    forward: async () => new Response(null, { status: 302, headers: { location: "https://elsewhere.example.test/" } }),
  });
  const redirected = await handleRequest(post("valid-anonymous"), redirecting.deps);
  assert.equal(redirected.status, 502);
  assert.equal(redirected.headers.get("location"), null);
});

test("misconfiguration returns 503 before any verification or reservation", async () => {
  const bad: Partial<GatewayConfig>[] = [
    { atlasToken: "" },
    { atlasToken: null },
    { atlasToken: "has space" },
    { atlasBaseUrl: "" },
    { atlasBaseUrl: "not a url" },
    { atlasBaseUrl: "http://atlas-origin.example.test/api" },
    { atlasBaseUrl: "https://user:pass@atlas-origin.example.test/api" },
    { atlasBaseUrl: "https://atlas-origin.example.test/api?x=1" },
    { allowedOrigins: "" },
    { allowedOrigins: null },
    { allowedOrigins: "*" },
    { allowedOrigins: `${ORIGIN},not-an-origin` },
    { platformConfigured: false },
  ];
  for (const config of bad) {
    const h = harness({ config });
    const response = await handleRequest(post("valid-anonymous"), h.deps);
    assert.equal(response.status, 503, JSON.stringify(config));
    assert.equal(await errorCode(response), "GATEWAY_MISCONFIGURED");
    assert.deepEqual(h.calls, []);
  }
});

test("base URL accepts localhost over http and normalizes a trailing slash", async () => {
  const local = harness({ config: { atlasBaseUrl: "http://localhost:8000/api/" } });
  assert.equal((await handleRequest(post("valid-anonymous"), local.deps)).status, 200);
  assert.equal(local.forwarded[0].url, `http://localhost:8000/api/datasets/${SLUG}/inference`);
});

test("unknown paths and invalid slugs return 404, other methods 405, nothing is called", async () => {
  const h = harness();
  const paths = ["", "/other-function/x", `/inference-gateway`, `/inference-gateway/${SLUG}/extra`];
  for (const path of paths) {
    const response = await handleRequest(
      new Request(`https://project.example.test${path === "" ? "/" : path}`, { method: "POST", body: VALID_BODY }),
      h.deps,
    );
    assert.equal(response.status, 404, path);
    assert.equal(await errorCode(response), "GATEWAY_NOT_FOUND");
  }
  for (const slug of ["Telco", "telco_churn", "-telco", "telco-", "telco--churn", "a".repeat(129)]) {
    const response = await handleRequest(post("valid-anonymous", VALID_BODY, slug), h.deps);
    assert.equal(response.status, 404, slug);
  }
  const get = await handleRequest(
    new Request(`https://project.example.test/inference-gateway/${SLUG}`, { method: "GET" }),
    h.deps,
  );
  assert.equal(get.status, 405);
  assert.equal(get.headers.get("allow"), "POST, OPTIONS");
  assert.equal(await errorCode(get), "GATEWAY_METHOD_NOT_ALLOWED");
  assert.deepEqual(h.calls, []);
});

test("a 128-character slug is accepted", async () => {
  const h = harness();
  const response = await handleRequest(post("valid-anonymous", VALID_BODY, "a".repeat(128)), h.deps);
  assert.equal(response.status, 200);
});

test("CORS: preflight echoes only allow-listed origins, never a wildcard", async () => {
  const h = harness();
  const preflight = (origin: string | null) =>
    handleRequest(
      new Request(`https://project.example.test/inference-gateway/${SLUG}`, {
        method: "OPTIONS",
        headers: origin === null ? {} : { origin },
      }),
      h.deps,
    );

  const allowed = await preflight(ORIGIN);
  assert.equal(allowed.status, 204);
  assert.equal(allowed.headers.get("access-control-allow-origin"), ORIGIN);
  assert.equal(allowed.headers.get("access-control-allow-methods"), "POST, OPTIONS");
  assert.equal(allowed.headers.get("access-control-allow-headers"), "authorization, content-type, apikey, x-client-info");
  assert.ok(allowed.headers.get("access-control-max-age"));
  assert.equal(allowed.headers.get("vary"), "Origin");

  for (const origin of ["https://evil.example.test", "https://atlas.example.test.evil.test", null]) {
    const denied = await preflight(origin);
    assert.equal(denied.status, 204);
    assert.equal(denied.headers.get("access-control-allow-origin"), null);
    assert.equal(denied.headers.get("access-control-allow-methods"), null);
    assert.equal(denied.headers.get("vary"), "Origin");
  }
  assert.deepEqual(h.calls, []);
});

test("CORS headers accompany gateway errors and 429 so the browser can read Retry-After", async () => {
  const h = harness();
  const unauthenticated = await handleRequest(post("not-a-real-token", VALID_BODY, SLUG, { origin: ORIGIN }), h.deps);
  assert.equal(unauthenticated.status, 401);
  assert.equal(unauthenticated.headers.get("access-control-allow-origin"), ORIGIN);

  for (let i = 0; i < LIMIT; i += 1) await handleRequest(post("valid-anonymous"), h.deps);
  const limited = await handleRequest(post("valid-anonymous", VALID_BODY, SLUG, { origin: ORIGIN }), h.deps);
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("access-control-allow-origin"), ORIGIN);
  assert.match(limited.headers.get("access-control-expose-headers") ?? "", /Retry-After/);

  const foreign = await handleRequest(post("valid-anonymous", VALID_BODY, SLUG, { origin: "https://evil.example.test" }), h.deps);
  assert.equal(foreign.headers.get("access-control-allow-origin"), null);
});

test("the subject comes only from the verified sub, never from request headers", async () => {
  const h = harness();
  const response = await handleRequest(
    post("valid-anonymous", VALID_BODY, SLUG, {
      "x-forwarded-for": "203.0.113.9",
      "x-real-ip": "203.0.113.10",
      "x-subject-id": "spoofed-subject",
    }),
    h.deps,
  );
  assert.equal(response.status, 200);
  assert.deepEqual(h.reserveArgs, [[SUBJECT, SLUG]]);
  const sent = h.forwarded[0].init.headers as Headers;
  assert.equal(sent.get("x-forwarded-for"), null);
  assert.equal(sent.get("x-subject-id"), null);
});

test("log hygiene: only count-only {event, dataset_slug, outcome} lines are emitted", async () => {
  const h = harness();
  const secretBody = JSON.stringify({ features: { secret_marker_value: "PAYLOAD-MARKER-123" } });

  await handleRequest(post("valid-anonymous", secretBody), h.deps);
  for (let i = 0; i < LIMIT; i += 1) await handleRequest(post("valid-anonymous", secretBody), h.deps);
  await handleRequest(post("not-a-real-token", secretBody), h.deps);
  await handleRequest(post("valid-anonymous", "not json"), h.deps);
  await handleRequest(post("valid-anonymous", secretBody, "Bad_Slug"), h.deps);
  await handleRequest(
    new Request(`https://project.example.test/inference-gateway/${SLUG}`, {
      method: "OPTIONS",
      headers: { origin: ORIGIN },
    }),
    h.deps,
  );

  const failing = harness({
    reserve: async () => {
      throw new Error("rpc failure");
    },
  });
  await handleRequest(post("valid-anonymous", secretBody), failing.deps);
  const upstream = harness({
    forward: async () => {
      throw new TypeError("network");
    },
  });
  await handleRequest(post("valid-anonymous", secretBody), upstream.deps);
  const misconfigured = harness({ config: { atlasToken: "" } });
  await handleRequest(post("valid-anonymous", secretBody), misconfigured.deps);

  const lines = [...h.logs, ...failing.logs, ...upstream.logs, ...misconfigured.logs];
  const seen = new Set<string>();
  for (const line of lines) {
    const entry = JSON.parse(line) as Record<string, string>;
    assert.equal(entry.event, "inference_gateway");
    assert.ok(OUTCOMES.includes(entry.outcome), line);
    for (const key of Object.keys(entry)) {
      assert.ok(["event", "dataset_slug", "outcome"].includes(key), key);
    }
    if ("dataset_slug" in entry) assert.equal(entry.dataset_slug, SLUG);
    seen.add(entry.outcome);
  }
  for (const outcome of OUTCOMES) assert.ok(seen.has(outcome), `outcome not exercised: ${outcome}`);

  const joined = lines.join("\n");
  for (const marker of [
    "valid-anonymous",
    "not-a-real-token",
    SUBJECT,
    ATLAS_TOKEN,
    "PAYLOAD-MARKER-123",
    "prediction",
    "probability",
    "Bad_Slug",
    "Bearer",
    "rpc failure",
    "network",
  ]) {
    assert.equal(joined.includes(marker), false, `log leaked ${marker}`);
  }
  // One line per handled request; the preflight is intentionally not logged.
  assert.equal(h.logs.length, 1 + LIMIT + 3);
});

test("gateway error bodies are fixed generic text without secrets, tokens or upstream detail", async () => {
  const h = harness({
    reserve: async () => {
      throw new Error("SECRET-RPC-DETAIL");
    },
  });
  const response = await handleRequest(post("valid-anonymous"), h.deps);
  const text = await response.text();
  for (const leaked of ["SECRET-RPC-DETAIL", "valid-anonymous", SUBJECT, ATLAS_TOKEN, BASE_URL, "ATLAS_GATEWAY"]) {
    assert.equal(text.includes(leaked), false, leaked);
  }
  assert.deepEqual(JSON.parse(text), {
    error: { code: "GATEWAY_RESERVATION_UNAVAILABLE", message: "Service temporarily unavailable." },
  });
});
