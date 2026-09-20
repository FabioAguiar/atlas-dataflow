# Inference Gateway Operations

This note owns operator guidance for the public inference gateway: quota window, limits, retention, deployment ordering, and credential rotation. It uses placeholders only; never commit real values. It covers only this gateway; see `supabase/functions/inference-gateway/README.md` for the request contract.

Public inference requests reach Atlas through the Supabase Edge Function `inference-gateway`. Home and Dataset Detail read endpoints go directly to the public API and are not gated. The M50 containment (payload size limit, process-local concurrency limiter, runtime hardening) remains beneath the gateway and is not replaced by it.

## Quota, window, and retention

| Setting | Value | Source of truth |
| --- | --- | --- |
| Window | fixed 10-minute UTC window | `public.reserve_inference_usage` in `supabase/migrations/20260920000000_create_inference_usage.sql` |
| Limit | 10 requests per subject per dataset per window | same migration |
| Retention | 7 days | `public.purge_inference_usage(p_retention)` default |

- Both window and limit are hard-coded in the migration; the gateway never computes them and only relays `Retry-After` (1 to 600 seconds) from the reservation.
- A consumed unit is never restored, including when Atlas rejects the payload or is unreachable.
- Purge scheduling: the migration schedules `purge-inference-usage` daily through `pg_cron` only when that extension is already installed. Without `pg_cron`, the operator must invoke `public.purge_inference_usage()` on a schedule using `service_role`, otherwise usage storage is unbounded.
- The usage table holds only subject id, dataset slug, window start, and request count.

## Environments and network model

Atlas DEV pairs with the Atlas DEV Supabase project/stack, and Atlas PROD with the Atlas PROD stack. Secrets, users, quota state and signing keys are never shared between environments. "Supabase" here means the Atlas-specific project/stack, hosted or self-hosted.

Self-hosted DEV model (SSH-forwarded ports):

| Actor | Reaches | Address kind |
| --- | --- | --- |
| Browser | Atlas web | SSH-forwarded `localhost` port (browser-visible) |
| Browser | Supabase gateway/Auth | SSH-forwarded `localhost` port (browser-visible; this is the token issuer origin) |
| Atlas API container | Supabase JWKS | container-private URL, e.g. `http://<supabase-kong>:8000/auth/v1/.well-known/jwks.json` |
| Edge Function container | Atlas API | container-private alias, e.g. `http://atlas-dataflow-dev-api:8000` (service root, no `/api` prefix) |
| Edge Function container | Supabase internal API | `SUPABASE_URL` (container-private) |

`localhost` inside the Edge Function or Atlas API container is that container, not the VPS host and not the other stack. Do not use it for container-to-container hops.

The private hops use plain HTTP and carry the gateway credential, so they are valid only on a dedicated trusted Docker network shared by this Atlas API and this Supabase stack. Attach only the Atlas API to it with `docker-compose.self-hosted-network.yml` (variables `ATLAS_SUPABASE_SHARED_NETWORK`, `ATLAS_PRIVATE_API_ALIAS`); the alias must be environment-unique (`atlas-dataflow-dev-api`, `atlas-dataflow-prod-api`), never the generic `api`. The API port is never published to the host and the Atlas web container never joins that network.

The public frontend intentionally contains `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`, and never the `service_role` key, a Supabase secret key, JWT signing secrets, the Atlas gateway token, or Admin backend secrets.

## Configuration

| Where | Name | Notes |
| --- | --- | --- |
| Gateway secret | `ATLAS_GATEWAY_TOKEN` | Sent to Atlas in the `x-atlas-gateway-token` header. |
| Gateway secret | `ATLAS_GATEWAY_BASE_URL` | Public: `https://<atlas-host>/api` (Caddy prefix). Private hop: FastAPI service root such as `http://<atlas-api-alias>:8000`, **without** `/api`. No trailing slash. |
| Gateway secret | `ATLAS_GATEWAY_ALLOW_PRIVATE_HTTP` | Optional, default off; only `true` enables plain HTTP to loopback, RFC1918, IPv6 ULA/loopback or dotless service names. |
| Gateway secret | `ATLAS_GATEWAY_ALLOWED_ORIGINS` | Exact web origins, comma-separated, no wildcard. Must include the web origin so the browser can read `Retry-After`. |
| Gateway secret | `ATLAS_SUPABASE_JWT_ISSUER` | Optional; exact browser-visible issuer. Default `<SUPABASE_URL>/auth/v1`. |
| Gateway secret | `ATLAS_SUPABASE_JWKS_URL` | Optional; container-reachable JWKS address. Default derived from `SUPABASE_URL`. |
| Atlas `api` environment | `ATLAS_INFERENCE_GATEWAY_TOKEN` | Must equal `ATLAS_GATEWAY_TOKEN`. The names differ on purpose. Passed through `docker-compose.yml` and `docker-compose.prod.yml` with an empty default. |

Placeholder shape (self-hosted DEV):

```text
ATLAS_GATEWAY_TOKEN=<gateway-credential>
ATLAS_GATEWAY_BASE_URL=<http://atlas-dataflow-dev-api:8000>
ATLAS_GATEWAY_ALLOW_PRIVATE_HTTP=<true>
ATLAS_GATEWAY_ALLOWED_ORIGINS=<http://localhost:forwarded-web-port>
ATLAS_SUPABASE_JWT_ISSUER=<http://localhost:forwarded-supabase-port/auth/v1>
ATLAS_SUPABASE_JWKS_URL=<http://supabase-kong:8000/auth/v1/.well-known/jwks.json>
ATLAS_INFERENCE_GATEWAY_TOKEN=<gateway-credential>
```

The platform injects `SUPABASE_URL` and the service-role key into the function; do not copy the service-role value anywhere else. Use different gateway credentials for DEV and PROD.

## Prerequisites and deployment order

1. Ensure the Atlas-specific Supabase project/stack exposes **asymmetric signing keys** (ES256/RS256/EdDSA). A legacy HS256-only stack rejects every token (fail closed); there is no HS256 fallback.
2. Enable Anonymous Auth. Provision the Admin operator first (see [admin-operator-provisioning](admin-operator-provisioning.md)), then disable email signup.
3. Apply the migration `supabase/migrations/20260920000000_create_inference_usage.sql` and confirm purge scheduling (see above): `pg_cron` where installed, otherwise an external scheduler calling `public.purge_inference_usage()` with `service_role`.
4. Provision the function secrets listed above.
5. Deploy the `inference-gateway` function.
6. Set `ATLAS_INFERENCE_GATEWAY_TOKEN` for the Atlas `api` service, attach it to the shared network (self-hosted) and recreate it.
7. Ensure the web origin is in `ATLAS_GATEWAY_ALLOWED_ORIGINS`.

Steps 1 to 2 and 3 to 5 happen in the Supabase stack and are operator-verified; the repository cannot prove them.

## Resource limits (M50) — pending measurement

No CPU, memory or PID limit value is defined by this repository and none is invented here. M53 must measure the real deployment and then choose either Compose-enforced or Coolify-enforced limits; the authoritative mechanism and the measured values are pending live evidence. This note does not make M50 or M53 ready.

## Credential rotation

Atlas accepts exactly one configured credential value (`ATLAS_INFERENCE_GATEWAY_TOKEN`, whitespace-stripped, read at request time). There is no overlap window, so zero-downtime rotation is unavailable. A brief mismatch window in which public predictions receive an Atlas 401 (shown to visitors as gateway unavailable) is expected.

To keep that window short:

1. Generate the new value out of band; never paste it into chat, tickets, or the repository.
2. Set the new `ATLAS_GATEWAY_TOKEN` gateway secret and the new `ATLAS_INFERENCE_GATEWAY_TOKEN` value back to back.
3. Recreate the `api` container. Compose passes the variable at container creation, so a running container keeps the old value until it is recreated.
4. Verify with one permitted request through the gateway and one request with a wrong credential that is rejected.

## Verification

- Repository evidence comes from the gateway, usage-store, and API gate test suites, recorded per layer.
- Atomic concurrency proof needs the live PostgreSQL reservation test with a disposable database; a skipped run is not evidence.
- Live checks (Anonymous Auth, deployed function, secrets, allowed origins, signing-key mode, shared-network reachability) are recorded only when the operator supplies evidence; otherwise they stay unverified, never assumed passed.
