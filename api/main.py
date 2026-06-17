import os
import sys
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

# Ensure the repository root is on the Python path so registry/ is importable
# when main.py is invoked from the api/ subdirectory.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from contract_loader import ContractUnavailableError, load_contract  # noqa: E402
from payload_validator import TYPE_MISMATCH, ValidationFailure, validate_payload  # noqa: E402
from registry.list import list_datasets  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

app = FastAPI()


def _public_error(
    status_code: int,
    error_code: str,
    message: str,
    error_type: str = "contract_error",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_type": error_type,
            "error_code": error_code,
            "message": message,
        },
    )


def _validation_error_response(failures: list[ValidationFailure]) -> JSONResponse:
    first = failures[0]
    content = first.as_public_error()
    content["errors"] = [failure.as_public_error() for failure in failures]
    return JSONResponse(status_code=422, content=content)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/datasets")
def list_datasets_endpoint():
    try:
        datasets = list_datasets()
    except RegistryInvalidError:
        return _public_error(
            status_code=503,
            error_code="REGISTRY_UNAVAILABLE",
            message="The registry is not currently available.",
        )
    return {"datasets": [d._asdict() for d in datasets]}


@app.get("/datasets/{dataset_slug}")
def get_dataset(dataset_slug: str):
    try:
        resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return _public_error(
            status_code=404,
            error_code="DATASET_UNAVAILABLE",
            message="The requested dataset is not available.",
        )
    except ReleaseUnavailableError:
        return _public_error(
            status_code=503,
            error_code="NO_ACTIVE_RELEASE",
            message="No active release is available for this dataset.",
        )
    except RegistryInvalidError:
        return _public_error(
            status_code=503,
            error_code="REGISTRY_UNAVAILABLE",
            message="The registry is not currently available.",
        )
    try:
        all_listed = list_datasets()
    except RegistryInvalidError:
        return _public_error(
            status_code=503,
            error_code="REGISTRY_UNAVAILABLE",
            message="The registry is not currently available.",
        )
    for listed in all_listed:
        if listed.dataset_slug == dataset_slug:
            return {
                "dataset_slug": listed.dataset_slug,
                "title": listed.title,
                "summary": listed.summary,
                "domain": listed.domain,
                "visibility": listed.visibility,
                "tags": listed.tags,
            }
    return _public_error(
        status_code=404,
        error_code="DATASET_UNAVAILABLE",
        message="The requested dataset is not available.",
    )


@app.post("/datasets/{dataset_slug}/inference")
def validate_dataset_inference_payload(
    dataset_slug: str,
    payload=Body(...),
):
    if not isinstance(payload, dict):
        return _validation_error_response(
            [
                ValidationFailure(
                    error_code=TYPE_MISMATCH,
                    message="The inference payload must be a JSON object.",
                    field="payload",
                    violation="type_mismatch",
                )
            ]
        )

    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return _public_error(
            status_code=404,
            error_code="DATASET_UNAVAILABLE",
            message="The requested dataset is not available.",
        )
    except ReleaseUnavailableError:
        return _public_error(
            status_code=503,
            error_code="NO_ACTIVE_RELEASE",
            message="No active release is available for this dataset.",
        )
    except RegistryInvalidError:
        return _public_error(
            status_code=503,
            error_code="REGISTRY_UNAVAILABLE",
            message="The registry is not currently available.",
        )

    try:
        runtime_contract = load_contract(resolved.active_release)
    except ContractUnavailableError:
        return _public_error(
            status_code=503,
            error_code="CONTRACT_UNAVAILABLE",
            message="The active contract for this dataset is temporarily unavailable.",
        )

    validation_failures = validate_payload(payload, runtime_contract)
    if validation_failures:
        return _validation_error_response(validation_failures)

    return {
        "status": "validated",
        "dataset_slug": resolved.dataset_slug,
        "next_step": "inference_execution",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
