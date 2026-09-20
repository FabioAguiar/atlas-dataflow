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

## Configuration

| Where | Name | Notes |
| --- | --- | --- |
| Gateway secret | `ATLAS_GATEWAY_TOKEN` | Sent to Atlas in the `x-atlas-gateway-token` header. |
| Gateway secret | `ATLAS_GATEWAY_BASE_URL` | Atlas base URL including the `/api` prefix, no trailing slash, `https`. |
| Gateway secret | `ATLAS_GATEWAY_ALLOWED_ORIGINS` | Exact web origins, comma-separated, no wildcard. Must include the web origin so the browser can read `Retry-After`. |
| Atlas `api` environment | `ATLAS_INFERENCE_GATEWAY_TOKEN` | Must equal `ATLAS_GATEWAY_TOKEN`. The names differ on purpose. Passed through `docker-compose.yml` and `docker-compose.prod.yml` with an empty default. |

Placeholder shape:

```text
ATLAS_GATEWAY_TOKEN=<gateway-credential>
ATLAS_GATEWAY_BASE_URL=<https://atlas-host/api>
ATLAS_GATEWAY_ALLOWED_ORIGINS=<https://web-origin>
ATLAS_INFERENCE_GATEWAY_TOKEN=<gateway-credential>
```

The platform injects `SUPABASE_URL` and the service-role key into the function; do not copy the service-role value anywhere else.

## Prerequisites and deployment order

1. Enable Anonymous Auth in the hosted Supabase project.
2. Confirm the project exposes asymmetric signing keys. A legacy HS256-only project rejects every token (fail closed).
3. Apply the migration and confirm purge scheduling (see above).
4. Set the three gateway secrets.
5. Deploy the `inference-gateway` function.
6. Set `ATLAS_INFERENCE_GATEWAY_TOKEN` for the Atlas `api` service and recreate it.
7. Ensure the web origin is in `ATLAS_GATEWAY_ALLOWED_ORIGINS`.

Steps 1 to 2 and 4 to 5 happen in the hosted project and are operator-verified; the repository cannot prove them.

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
- Hosted checks (Anonymous Auth, deployed function, secrets, allowed origins, signing-key mode) are recorded only when the operator supplies evidence; otherwise they stay unverified, never assumed passed.
