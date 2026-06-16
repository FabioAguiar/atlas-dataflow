import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Ensure the repository root is on the Python path so registry/ is importable
# when main.py is invoked from the api/ subdirectory.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/datasets/{dataset_slug}")
def get_dataset(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return JSONResponse(
            status_code=404,
            content={
                "error": "DATASET_UNAVAILABLE",
                "message": "The requested dataset is not available.",
            },
        )
    except ReleaseUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "error": "RELEASE_UNAVAILABLE",
                "message": "The active release for this dataset is not available.",
            },
        )
    except RegistryInvalidError:
        return JSONResponse(
            status_code=503,
            content={
                "error": "REGISTRY_UNAVAILABLE",
                "message": "The registry is not currently available.",
            },
        )
    return {"dataset_slug": resolved.dataset_slug, "active_release": resolved.active_release}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
