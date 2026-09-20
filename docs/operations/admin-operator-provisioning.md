# Admin Operator Provisioning

This note is the single owner of operator provisioning, rotation, sign-out, and recovery guidance for the private Admin identity boundary. It uses placeholders only; never commit real values.

## Two independent gates

Admin access requires both:

1. **Runtime mode** — `ATLAS_ADMIN_ENABLED=true`, set only in the private deployment (`docker-compose.yml`). The public deployment (`docker-compose.prod.yml`) keeps it `false`, receives none of the values below, and returns 404 for `/admin` and `/api/admin`.
2. **Operator identity** — the backend accepts a valid Supabase session token only for the single provisioned operator, and fails closed when configuration is missing or invalid.

## Variable classes

| Class | Variables | Where they go |
| --- | --- | --- |
| Trusted (backend only) | `ATLAS_SUPABASE_JWT_ISSUER`, `ATLAS_SUPABASE_JWT_AUDIENCE`, `ATLAS_SUPABASE_JWKS_URL`, `ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP` (optional), `ATLAS_ADMIN_USER_ID` | Private `api` service environment |
| Publishable (build time) | `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Private `web` build args; inlined into the private bundle |
| Provisioning only | Supabase secret/service key, dashboard credentials | Operator's own tooling only; never in compose, the web build, Settings, or the repository |

Placeholder shape for the private deployment environment:

```text
ATLAS_SUPABASE_JWT_ISSUER=<https://project-ref.supabase.co/auth/v1>
ATLAS_SUPABASE_JWT_AUDIENCE=<authenticated>
ATLAS_SUPABASE_JWKS_URL=<https://project-ref.supabase.co/auth/v1/.well-known/jwks.json>
ATLAS_ADMIN_USER_ID=<operator-user-uuid>
VITE_SUPABASE_URL=<https://project-ref.supabase.co>
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

## Environment model

Use the Atlas-specific Supabase project/stack for each environment: Atlas DEV uses the Atlas DEV stack and Atlas PROD the Atlas PROD stack, hosted or self-hosted, with separate operators and secrets. The verifier requires **asymmetric signing keys** (ES256/RS256); HS256-only projects fail closed and there is no HS256 fallback.

The issuer and the JWKS address are independent. `ATLAS_SUPABASE_JWT_ISSUER` is the exact browser-visible `iss` (in DEV, the SSH-forwarded `localhost` Supabase origin plus `/auth/v1`), while `ATLAS_SUPABASE_JWKS_URL` is only the key-fetch address the API container can reach (in self-hosted DEV, a private service URL such as `http://<supabase-kong>:8000/auth/v1/.well-known/jwks.json`). `localhost` inside the API container is the API container itself, not the VPS host or the Supabase stack.

Plain-HTTP JWKS is denied by default. Setting `ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP=true` permits HTTP only for loopback, RFC1918, IPv6 ULA/loopback or dotless single-label service hosts, with no credentials, query or fragment, and only on the dedicated trusted Atlas/Supabase Docker network (attach the API with `docker-compose.self-hosted-network.yml`). Redirects are never followed. The browser-visible values `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` are the only Supabase values in the web build.

## Provisioning

1. In this environment's Atlas-specific Supabase project/stack, create the single operator user (before anything else).
2. Set `app_metadata.atlas_role` to `admin` for that user (server-side only; user-editable metadata is not trusted).
3. Record the operator's user UUID as `ATLAS_ADMIN_USER_ID`.
4. Only after the operator exists, disable email signup so no other account can be created (Anonymous Auth remains enabled for the public visitor session).
5. Supply the values above to the private deployment only, then rebuild the private web image so the publishable values are inlined.

## Rotation and sign-out

- Rotate the publishable key in the Supabase project, update `VITE_SUPABASE_PUBLISHABLE_KEY`, and rebuild the private web image.
- Signing out ends the browser session. To invalidate existing sessions, sign the operator out globally from the Supabase project.
- Changing the operator means updating `app_metadata.atlas_role` and `ATLAS_ADMIN_USER_ID` together, then restarting the private `api` service.

## Administrative password recovery

Reset the operator's password from the Supabase project (administrative reset or recovery email). No password or recovery flow exists in Atlas itself.

## Verification

- Private: unauthenticated Admin API calls are rejected; only the provisioned operator is admitted.
- Public: the built bundle contains no Supabase configuration, and `/admin` and `/api/admin` return 404.
- Live Supabase checks require operator-supplied access; when unavailable they are recorded as blocked, not passed.
