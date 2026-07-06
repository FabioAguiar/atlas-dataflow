# atlas-dataflow

## M2 local container validation

The M2 local baseline runs only the public API and public web surfaces.

- API: FastAPI/Uvicorn from `api/`, exposed on port `8000`.
- Web: Vite/React/TypeScript from `web/`, exposed on port `5173`.
- Local orchestration: `docker-compose.yml` defines only `api` and `web`.

Safe local configuration is supplied through Compose environment values:

- `API_HOST=0.0.0.0`
- `API_PORT=8000`
- `VITE_API_BASE_URL=http://localhost:8000`

Run the minimum local validation with:

```sh
scripts/validate-m2.sh
```

The validation builds and starts the local containers, confirms that
`GET /health` returns the API health response, and confirms that the web root
page loads. It does not deploy anything and does not require secrets.

## Runtime modes and private access

Atlas currently has two Compose entry points with different exposure
expectations:

- `docker-compose.yml` is the private/full-access stack for local operator use.
  It enables backend admin APIs with `ATLAS_ADMIN_ENABLED=true` by default,
  builds the web UI with `VITE_ENABLE_ADMIN=true` by default, and binds the web
  service to `127.0.0.1:${ATLAS_PREVIEW_PORT:-15174}`.
- `docker-compose.prod.yml` is the public runtime stack. It disables backend
  admin APIs with `ATLAS_ADMIN_ENABLED=false` by default, builds the web UI with
  `VITE_ENABLE_ADMIN=false` by default, and does not publish the web container
  directly from Compose.

When the private stack runs on a VPS or another host, reach it through a private
network path such as SSH tunneling to the loopback-bound preview port. That
tunnel is only an operational access path to the private runtime; it is not
application authentication, a public admin feature, or a replacement for the
current operator-token behavior. Do not expose the private stack publicly, and
do not treat this note as authorization to remove token fields before the M46
runtime boundary is validated.
