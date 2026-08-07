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

Atlas dataset integration authoring converts reviewed, dataset-specific
analysis into governed Atlas inputs without making the analysis environment a
runtime dependency. Scientific analysis may occur in a separate external
project. Lumen inspects that project and the Atlas repository during authoring
only, then translates reviewed conclusions into dataset-specific Atlas intent.
Atlas does not mount or resolve the external project after authoring.

- **Dataset integration authoring notebooks** (`notebooks/`) are the
  human-facing Atlas authoring surface. The target Telco naming convention is
  `notebooks/datasets/telco-customer-churn/01_dataset_integration_authoring.ipynb`;
  its implementation is future work. This dataset-specific notebook verifies
  the exact Atlas-owned input, records semantic intent, and invokes generic
  Atlas materializers. Input identity, drift, and authored-assumption checks
  are distinct from re-performing scientific exploration, model training, or
  model selection already established by authoritative external analysis.
- **Durable authoring state** is a governed Atlas-native artifact suite rather
  than notebook memory or an external filesystem layout. Notebook state alone
  is never sufficient: generic core consumes validated, integrity-bound Atlas
  artifacts. Release assembly, publisher validation, registry activation, and
  runtime remain separate downstream governed stages.
- **Current support boundary:** binary predictive classification is the only
  currently evidenced operational capability. Capability-aware authoring and
  publication are architectural direction implemented progressively by later
  work; other analytical or prediction families must not be presented as
  current functionality.
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

This documentation does not create or refactor a notebook, define schemas, or
change training, release, publisher, registry, or runtime behavior. See
[`docs/architecture.md`](docs/architecture.md#dataset-integration-authoring-architecture)
for the normative authoring, capability, integrity, and compatibility rules.

### Notebook runtime import contract

Atlas notebook work uses three separate boundaries:

- `atlas` is the main Atlas runtime environment. Do not install exploratory
  notebook dependencies into it.
- `atlas-notebooks` is the isolated Conda environment for Jupyter and
  Data Workbench authoring. Select this kernel for notebook work; using `base`
  or `atlas` is a setup error for this workflow.
- `atlas-dataflow` is the source tree. Internal imports such as
  `pipeline.discovery_evidence` resolve only after Python can see this
  repository root.

Jupyter for notebook authoring is expected to remain private on the VPS,
bound to `127.0.0.1:8888`, and reached from an operator machine through an
SSH tunnel such as:

```sh
ssh -L 18888:127.0.0.1:8888 <vps-host>
```

Then open the local tunnel endpoint at `http://127.0.0.1:18888`. This access
pattern does not change Jupyter configuration and does not authorize exposing
Jupyter on `0.0.0.0` or any public interface.

Install the repository in editable mode from the dedicated notebook
environment before starting notebook work:

```sh
conda activate atlas-notebooks
cd ~/Projetos/N8N/atlas-dataflow
pip install -e .
```

The editable install intentionally exposes only the repository's `pipeline`
Python boundary for notebook helpers. It does not package API, web,
notebooks, data, release, publisher, registry, support-root, generated
evidence, runtime, cache, secret, or credential paths.

After editable installation, notebooks can import Atlas helpers directly:

```python
from pipeline.discovery_evidence import (
    load_dataset_csv,
    resolve_repository_path,
    summarize_structure,
)
```

Do not use notebook `sys.path` cells, global Python startup files, hidden
`.pth` files, Jupyter server state, or Conda site customization as the primary
import mechanism. If the import fails after editable installation, verify that
the notebook kernel is `atlas-notebooks` and not `base` or the main `atlas`
runtime.

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
