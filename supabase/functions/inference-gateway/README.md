# inference-gateway

Supabase Edge Function that sits between the public web client and Atlas
`POST /datasets/{dataset_slug}/inference`. It verifies an anonymous visitor JWT,
atomically reserves one quota unit through `public.reserve_inference_usage`
(M52-03), and only then forwards the request to Atlas with the dedicated
gateway credential header. When the limit is reached it answers `429` with an
integer `Retry-After` and never calls Atlas.

Files:

- `handler.ts` - pure, import-free request handler (all gateway logic).
- `index.ts` - Deno entrypoint: reads env, builds the JWKS verifier and the
  `service_role` reservation client, calls `Deno.serve`. No business logic.
- `handler.test.ts` - offline `node:test` suite using controlled fakes.

## Request contract

- `POST /functions/v1/inference-gateway/<dataset_slug>` and `OPTIONS` only.
  `<dataset_slug>` must match `^[a-z0-9]+(?:-[a-z0-9]+)*$` (max 128 chars).
  Other paths return 404, other methods 405 with `Allow`.
- `Authorization: Bearer <anonymous visitor JWT>` is required. The visitor
  `Authorization` header is never forwarded to Atlas.
- The body is forwarded byte-for-byte. Before reserving, the gateway only
  checks size (max 1,048,576 bytes, 413) and that the body is JSON (400).
  Those rejections do not consume a unit.

Fixed order: route/method/slug, configuration, JWT, anonymous check,
pre-reservation validation, atomic reservation, forward.

## Function secrets

Set with `supabase secrets set` (placeholders only below; never commit values):

| Secret | Purpose |
| --- | --- |
| `ATLAS_GATEWAY_TOKEN` | Credential sent to Atlas in `x-atlas-gateway-token`. Must equal the Atlas-side `ATLAS_INFERENCE_GATEWAY_TOKEN`; the two names differ on purpose. |
| `ATLAS_GATEWAY_BASE_URL` | Atlas base URL **including the `/api` prefix** used by Caddy, no trailing slash, `https` required (plain `http` only for localhost). Example: `https://<atlas-host>/api`. |
| `ATLAS_GATEWAY_ALLOWED_ORIGINS` | Comma-separated exact browser origins allowed by CORS, for example `https://<web-origin>`. No wildcard. |

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected by the platform.
A missing, blank or invalid value returns `503 GATEWAY_MISCONFIGURED` before
any reservation.

## JWT verification

`config.toml` sets `verify_jwt = false` for this function on purpose. The
function verifies the token itself with `jose` against
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json` (issuer
`<SUPABASE_URL>/auth/v1`, audience `authenticated`, asymmetric algorithm
allowlist) and then requires `is_anonymous === true` and a non-empty `sub` of at
most 128 characters. Any other outcome is the same generic `401`.

Prerequisite: the hosted project must expose asymmetric signing keys. A legacy
HS256-only project rejects every token (fail closed); confirming the
signing-key mode is an operator check.

## Quota and failure semantics

- The subject is the verified `sub`; no client IP is ever read.
- The reservation runs with the `service_role` key, never the visitor token. An
  RPC error, exception or malformed result returns `503
  GATEWAY_RESERVATION_UNAVAILABLE` and is never treated as allowed.
- `allowed = false` returns `429 GATEWAY_QUOTA_EXCEEDED` with `Retry-After`
  taken from the RPC (`1..600`). The gateway never computes the window or the
  limit.
- There is no decrement or restore path. A unit stays consumed when Atlas
  rejects the payload, is unreachable (`502 GATEWAY_UPSTREAM_UNAVAILABLE`) or
  exceeds the 15 s forward timeout (`504 GATEWAY_UPSTREAM_TIMEOUT`; Atlas' own
  deadline is 10 s). Redirects are not followed.
- Atlas status and body pass through unmodified. Only `content-type` and
  `cache-control` response headers are relayed, plus CORS headers.

Gateway-originated errors are JSON `{"error":{"code":"GATEWAY_*","message":"..."}}`
with fixed generic messages, distinct from Atlas error codes.

## CORS

`Access-Control-Allow-Origin` is echoed only when the request `Origin` exactly
matches an allowed origin; otherwise no CORS allow headers are emitted.
`Vary: Origin` is always set, and `Access-Control-Expose-Headers` includes
`Retry-After` so the browser can read a 429.

## Observability

One JSON line per handled request via `console.log`, containing only
`{"event":"inference_gateway","dataset_slug":"<slug>","outcome":"<outcome>"}`.
`dataset_slug` appears only after slug validation. `outcome` is one of
`accepted`, `rate_limited`, `rejected_auth`, `rejected_invalid`,
`reservation_error`, `upstream_error`, `misconfigured`. Payloads, tokens,
credentials, subjects, predictions and error objects are never logged. CORS
preflight requests are not logged.

## Tests

```
node --test supabase/functions/inference-gateway/handler.test.ts
python -m pytest tests/supabase/test_inference_gateway_static.py -q
```

The suite needs Node with native TypeScript type stripping (22.18+) or Deno.

Deployment, secret provisioning and hosted verification are operator work
tracked under M52-06; nothing here claims hosted behavior.
