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
