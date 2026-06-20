import json
import os
import pickle
import sys
import tarfile
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    INFERENCE_FAILURE,
    PUBLIC_CONTRACT_UNAVAILABLE,
    PublicError,
    REGISTRY_UNAVAILABLE,
    RELEASE_UNAVAILABLE,
    UNEXPECTED_ERROR,
    public_error_response,
    validation_error_response,
)
from runtime.inference import (  # noqa: E402
    BundleUnavailableError,
    InferenceRuntimeError,
    execute_prediction,
)
from public_contract_loader import (  # noqa: E402
    PublicContractUnavailableError,
    load_public_contract,
)
from public_metrics_loader import (  # noqa: E402
    PublicMetricsUnavailableError,
    load_public_metrics,
)
from public_model_card_loader import (  # noqa: E402
    PublicModelCardUnavailableError,
    load_public_model_card,
)
from public_visualizations_loader import (  # noqa: E402
    PublicVisualizationsUnavailableError,
    load_public_visualizations,
)

METRICS_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="metrics_unavailable",
    error_code="METRICS_UNAVAILABLE",
    message="The metrics for this dataset are temporarily unavailable.",
)

MODEL_CARD_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="model_card_unavailable",
    error_code="MODEL_CARD_UNAVAILABLE",
    message="The model card for this dataset is temporarily unavailable.",
)

VISUALIZATIONS_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="visualizations_unavailable",
    error_code="VISUALIZATIONS_UNAVAILABLE",
    message="The visualizations for this dataset are temporarily unavailable.",
)
from registry.list import list_datasets  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)


def _inference_releases_root() -> Path:
    env_root = os.environ.get("RELEASES_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT / "releases"


def _load_bundle(bundle_path: Path):
    name = bundle_path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(bundle_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.lower().endswith((".pkl", ".pickle")):
                    f = tar.extractfile(member)
                    if f is not None:
                        return pickle.load(f)  # noqa: S301
        raise BundleUnavailableError("Inference bundle could not be loaded.")
    if name.endswith((".pkl", ".pickle")):
        with open(bundle_path, "rb") as f:
            return pickle.load(f)  # noqa: S301
    if name.endswith(".json"):
        with open(bundle_path, encoding="utf-8") as f:
            return json.load(f)
    raise BundleUnavailableError("Inference bundle could not be loaded.")


_PAYLOAD_SIZE_LIMIT = 1_048_576  # 1 MB


class PayloadSizeLimitMiddleware:
    def __init__(self, app, max_size: int = _PAYLOAD_SIZE_LIMIT) -> None:
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"content-length":
                    try:
                        if int(value) > self.max_size:
                            response = JSONResponse(
                                status_code=413,
                                content={
                                    "error_type": "invalid_payload",
                                    "error_code": "PAYLOAD_TOO_LARGE",
                                    "message": "The request payload exceeds the maximum allowed size.",
                                },
                            )
                            await response(scope, receive, send)
                            return
                    except ValueError:
                        pass
                    break
        await self.app(scope, receive, send)


app = FastAPI()
app.add_middleware(PayloadSizeLimitMiddleware, max_size=_PAYLOAD_SIZE_LIMIT)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("CORS_ALLOWED_ORIGIN", "")],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


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

    release_dir = _inference_releases_root() / resolved.active_release
    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return public_error_response(INFERENCE_FAILURE)

    try:
        result = execute_prediction(
            {"path": str(release_dir), "artifacts": manifest.get("artifacts", [])},
            dict(payload),
            manifest=manifest,
            bundle_loader=_load_bundle,
        )
    except InferenceRuntimeError:
        return public_error_response(INFERENCE_FAILURE)
    except Exception:
        return public_error_response(INFERENCE_FAILURE)

    raw = result.get("prediction") if isinstance(result, dict) else None
    if isinstance(raw, dict):
        label = raw.get("label")
        confidence = raw.get("confidence")
    elif raw is not None:
        label = getattr(raw, "label", None)
        confidence = getattr(raw, "confidence", None)
    else:
        label = confidence = None

    if not isinstance(label, str) or not isinstance(confidence, (int, float)):
        return public_error_response(INFERENCE_FAILURE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "prediction": {"label": label, "confidence": float(confidence)},
    }


@app.get("/datasets/{dataset_slug}/metrics")
def get_public_metrics(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        metrics = load_public_metrics(resolved.active_release)
    except PublicMetricsUnavailableError:
        return public_error_response(METRICS_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "metrics": metrics,
    }


@app.get("/datasets/{dataset_slug}/model-card")
def get_public_model_card(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        model_card = load_public_model_card(resolved.active_release)
    except PublicModelCardUnavailableError:
        return public_error_response(MODEL_CARD_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "model_card": model_card,
    }


@app.get("/datasets/{dataset_slug}/visualizations")
def get_public_visualizations(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        visualizations = load_public_visualizations(resolved.active_release)
    except PublicVisualizationsUnavailableError:
        return public_error_response(VISUALIZATIONS_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "visualizations": visualizations,
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
