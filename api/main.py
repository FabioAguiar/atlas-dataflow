import os
import sys
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Request

# Ensure the repository root is on the Python path so registry/ is importable
# when main.py is invoked from the api/ subdirectory.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from contract_loader import ContractUnavailableError, load_contract  # noqa: E402
from payload_validator import TYPE_MISMATCH, ValidationFailure, validate_payload  # noqa: E402
from public_errors import (  # noqa: E402
    CONTRACT_UNAVAILABLE,
    DATASET_NOT_FOUND,
    PUBLIC_CONTRACT_UNAVAILABLE,
    REGISTRY_UNAVAILABLE,
    RELEASE_UNAVAILABLE,
    UNEXPECTED_ERROR,
    public_error_response,
    validation_error_response,
)
from public_contract_loader import (  # noqa: E402
    PublicContractUnavailableError,
    load_public_contract,
)
from registry.list import list_datasets  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

app = FastAPI()


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, _exc: Exception):
    return public_error_response(UNEXPECTED_ERROR)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/datasets")
def list_datasets_endpoint():
    try:
        datasets = list_datasets()
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)
    return {"datasets": [d._asdict() for d in datasets]}


@app.get("/datasets/{dataset_slug}")
def get_dataset(dataset_slug: str):
    try:
        resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)
    try:
        all_listed = list_datasets()
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)
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
    return public_error_response(DATASET_NOT_FOUND)


@app.get("/datasets/{dataset_slug}/contract")
def get_public_contract(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        public_contract = load_public_contract(resolved.active_release)
    except PublicContractUnavailableError:
        return public_error_response(PUBLIC_CONTRACT_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "contract": public_contract,
    }


@app.post("/datasets/{dataset_slug}/inference")
def validate_dataset_inference_payload(
    dataset_slug: str,
    payload=Body(...),
):
    if not isinstance(payload, dict):
        return validation_error_response(
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
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        runtime_contract = load_contract(resolved.active_release)
    except ContractUnavailableError:
        return public_error_response(CONTRACT_UNAVAILABLE)

    validation_failures = validate_payload(payload, runtime_contract)
    if validation_failures:
        return validation_error_response(validation_failures)

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
