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

## Data Workbench boundary

Atlas is about to add dataset-specific notebooks and reusable data-authoring
procedures. Before that work begins, this section defines the minimum
repository-facing boundary for it, so dataset authoring stays disciplined and
does not blur into the existing `pipeline/`, `contracts/`, `releases/`,
`publisher/`, `registry/`, `api/`, and `web/` responsibilities.

- **Notebooks** (`notebooks/`) are the human-facing authoring surface for
  dataset-specific exploration and decisions (see
  `notebooks/m22_discovery_entrypoint.ipynb`). A notebook may orchestrate
  authoring work, but it must not be the only durable record of a dataset
  decision — decisions that feed training, contracts, releases, or UI
  data-fill must be externalized into explicit files before those downstream
  steps consume them.
- **Reusable authoring helpers** are logic that more than one notebook or
  authoring run needs. They belong in a dedicated workbench-owned location,
  separate from notebooks and separate from runtime `api/`/`web/` code — never
  copied ad hoc between notebook cells. No such helpers exist yet; introducing
  them is out of scope for this bootstrap and requires its own implementation
  request.
- **Dataset-local configuration and modeling-intent files** are the explicit,
  reviewable files a dataset author writes to record scope, source, and
  modeling intent for one dataset, distinct from a notebook's exploratory
  cells and distinct from the generated pipeline/contract/release artifacts
  those decisions eventually produce.
- **Local authoring runs vs. publisher runs:** a local authoring/workbench run
  is exploratory and disposable — it supports a human deciding what a dataset
  needs. A publisher run (`publisher/validate.py`, `publisher/promote.py`) is
  the official validation/promotion path and only ever consumes already
  externalized, committed inputs (schemas under `contracts/`, pipeline
  artifacts under `pipeline/`), never a notebook's in-memory or local-only
  state.
- **Promotion boundary:** exploratory/authoring artifacts stay local (ignored
  by Git, see below) until a dataset author turns a decision into an explicit,
  committed file — a discovery-evidence document, a source-contract input, a
  release-candidate input, or a training-interface input matching the
  existing `pipeline/*.schema.json` contracts. Only committed files are
  eligible for `pipeline/`, `contracts/`, `releases/`, or `publisher/`
  processing; nothing generated during a local run is promoted automatically.
- **Ignored by default:** local workbench generated outputs, caches,
  exploratory run artifacts, temporary/intermediate dataset dumps, model
  binaries, and notebook checkpoints — see the Data Workbench section of
  `.gitignore`. Promotion of any such output requires a later, explicit
  implementation request; this bootstrap does not itself promote any file.

This is a bootstrap boundary only. It does not create a workbench folder
tree, reusable helper modules, dataset-specific notebooks, or training/
release/publisher behavior changes — those require their own, later
implementation requests that explicitly list their concrete edit paths.

## Runtime mode operator note

Atlas currently has two Compose entry points with different exposure
expectations:

- `docker-compose.yml` is the private/full-access stack for local operator use.
  It enables backend admin APIs with `ATLAS_ADMIN_ENABLED=true` by default,
  builds the web UI with `VITE_ENABLE_ADMIN=true` by default, and binds the web
  service to `127.0.0.1:${ATLAS_PREVIEW_PORT:-15174}`. Use this mode for
  operator configuration and publication work through loopback or an SSH tunnel.
- `docker-compose.prod.yml` is the public/prod runtime stack. It disables
  backend admin APIs with `ATLAS_ADMIN_ENABLED=false` by default, builds the web
  UI with `VITE_ENABLE_ADMIN=false` by default, and exposes only the public
  Atlas surface. Public/prod must deny admin UI routes `/admin` and `/admin/*`
  and admin API routes `/api/admin` and `/api/admin/*`.

When the private stack runs on a VPS or another host, reach it through a private
network path such as SSH tunneling to the loopback-bound preview port. That
tunnel is only an operational access path to the private runtime; it is not
application authentication, an admin feature for public exposure, or a
replacement for the runtime boundary. Do not expose the private stack publicly;
public/prod admin denial is enforced by the runtime configuration that disables
admin routes and the admin UI outside the private stack.

The first-version model does not introduce login, sessions, OAuth, admin access
available to public users, or a browser-entered operator token as the admin UX.
M49 readiness and evidence validation should validate this runtime mode
separation after S0001 through S0005 are complete; M49 is not expected to add
new runtime behavior.
