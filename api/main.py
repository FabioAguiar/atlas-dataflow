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
from public_context_loader import (  # noqa: E402
    PublicContextUnavailableError,
    load_public_context,
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
from public_predict_view_loader import (  # noqa: E402
    ViewNotFoundError,
    ViewBindingInvalidError,
    load_public_predict_view,
    load_public_predict_view_list,
)
from public_predict_view_customization_loader import (  # noqa: E402
    CustomizationNotFoundError,
    load_public_predict_view_customization,
)
from public_profile_visibility import (  # noqa: E402
    resolve_dataset_visibility,
    resolve_public_presentation_overlay,
)
from admin_runs import list_admin_run_summaries, promote_admin_run, remove_admin_run  # noqa: E402
from admin_profile_drafts import read_profile_draft, save_profile_draft  # noqa: E402
from admin_profile_publish import publish_profile, publish_profile_payload  # noqa: E402
from admin_profile_visibility import set_dataset_visibility  # noqa: E402
from admin_settings import read_admin_settings, write_admin_settings  # noqa: E402
from admin_predict_view_customizations import (  # noqa: E402
    read_predict_view_customization,
    save_predict_view_customization,
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

CONTEXT_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="context_unavailable",
    error_code="CONTEXT_UNAVAILABLE",
    message="The context for this dataset is temporarily unavailable.",
)

VIEW_NOT_FOUND = PublicError(
    status_code=404,
    error_type="view_not_found",
    error_code="VIEW_NOT_FOUND",
    message="The requested predict view is not available for this dataset.",
)

VIEW_BINDING_INVALID = PublicError(
    status_code=422,
    error_type="view_binding_invalid",
    error_code="VIEW_BINDING_INVALID",
    message="The predict view binding is not valid for this dataset.",
)

CUSTOMIZATION_NOT_FOUND = PublicError(
    status_code=404,
    error_type="customization_not_found",
    error_code="CUSTOMIZATION_NOT_FOUND",
    message="No customization is available for this predict view.",
)

PROFILE_DRAFT_DATASET_SLUG_INVALID = PublicError(
    status_code=422,
    error_type="profile_draft_dataset_slug_invalid",
    error_code="PROFILE_DRAFT_DATASET_SLUG_INVALID",
    message="The dataset_slug is missing or does not match the required pattern.",
)

PROFILE_DRAFT_INVALID = PublicError(
    status_code=422,
    error_type="profile_draft_invalid",
    error_code="PROFILE_DRAFT_INVALID",
    message="The profile draft failed validation.",
)

PROFILE_PUBLISH_DATASET_SLUG_INVALID = PublicError(
    status_code=422,
    error_type="profile_publish_dataset_slug_invalid",
    error_code="PROFILE_PUBLISH_DATASET_SLUG_INVALID",
    message="The dataset_slug is missing or does not match the required pattern.",
)

PROFILE_PUBLISH_FAILED = PublicError(
    status_code=422,
    error_type="profile_publish_failed",
    error_code="PROFILE_PUBLISH_FAILED",
    message="The profile could not be published.",
)

PROFILE_VISIBILITY_DATASET_SLUG_INVALID = PublicError(
    status_code=422,
    error_type="profile_visibility_dataset_slug_invalid",
    error_code="PROFILE_VISIBILITY_DATASET_SLUG_INVALID",
    message="The dataset_slug is missing or does not match the required pattern.",
)

PROFILE_VISIBILITY_PAYLOAD_INVALID = PublicError(
    status_code=422,
    error_type="profile_visibility_payload_invalid",
    error_code="PROFILE_VISIBILITY_PAYLOAD_INVALID",
    message="The visibility payload must be a JSON object with a boolean 'visible' field.",
)

ADMIN_RUN_REMOVAL_FAILED = PublicError(
    status_code=422,
    error_type="admin_run_removal_failed",
    error_code="ADMIN_RUN_REMOVAL_FAILED",
    message="The run could not be removed.",
)

ADMIN_RUN_PROMOTION_FAILED = PublicError(
    status_code=422,
    error_type="admin_run_promotion_failed",
    error_code="ADMIN_RUN_PROMOTION_FAILED",
    message="The run could not be promoted.",
)

ADMIN_SETTINGS_INVALID = PublicError(
    status_code=422,
    error_type="admin_settings_invalid",
    error_code="ADMIN_SETTINGS_INVALID",
    message="The admin settings payload failed validation.",
)

ADMIN_DATASET_DETAIL_REMOVAL_FAILED = PublicError(
    status_code=422,
    error_type="admin_dataset_detail_removal_failed",
    error_code="ADMIN_DATASET_DETAIL_REMOVAL_FAILED",
    message="The Dataset Detail could not be removed.",
)

ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED = PublicError(
    status_code=422,
    error_type="admin_dataset_detail_slug_rename_failed",
    error_code="ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED",
    message="The Dataset Detail slug could not be renamed.",
)

PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID = PublicError(
    status_code=422,
    error_type="predict_view_customization_identifier_invalid",
    error_code="PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID",
    message="The dataset_slug or view_id is missing or does not match the required pattern.",
)

PREDICT_VIEW_CUSTOMIZATION_INVALID = PublicError(
    status_code=422,
    error_type="predict_view_customization_invalid",
    error_code="PREDICT_VIEW_CUSTOMIZATION_INVALID",
    message="The predict view customization failed validation.",
)
from registry.list import list_datasets, list_admin_datasets, is_dataset_needs_review  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)
from registry.update import (  # noqa: E402
    MODE_CREATE_NEW_DATASET_DETAIL,
    remove_dataset_entry,
    rename_dataset_slug,
)


def _resolve_problem_type(dataset_slug: str) -> str | None:
    """
    Resolve the real problem_type for dataset_slug via its active release's
    public context, defaulting to None (fail-open) whenever the dataset,
    release, or context is unavailable rather than raising or blocking the
    entire listing. Kept in the api layer (not registry/list.py) so it
    reuses load_public_context directly without introducing a registry ->
    api dependency.
    """
    try:
        resolved = resolve_dataset(dataset_slug)
        context = load_public_context(resolved.active_release)
    except (DatasetUnavailableError, ReleaseUnavailableError, RegistryInvalidError, PublicContextUnavailableError):
        return None
    problem_type = context.get("problem_type") if isinstance(context, dict) else None
    return problem_type if isinstance(problem_type, str) else None


def _inference_releases_root() -> Path:
    env_root = os.environ.get("RELEASES_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT / "releases"


_ADMIN_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _admin_runtime_enabled() -> bool:
    value = os.environ.get("ATLAS_ADMIN_ENABLED")
    return value is not None and value.strip().lower() in _ADMIN_ENABLED_VALUES


# Admin routes must not be reachable unless the backend admin runtime mode is
# explicitly enabled. M47 private admin operation relies on the private runtime
# boundary rather than browser-held operator token state.
def _admin_request_authorized(_request: Request) -> bool:
    return _admin_runtime_enabled()


# On an access-control failure this must be byte-for-byte the same response
# an unmatched route would produce (FastAPI/Starlette's default 404 body),
# so an unauthenticated caller cannot distinguish "route exists but token is
# wrong" from "route does not exist".
def _admin_route_not_found_response() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


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
    visible_datasets = [
        d
        for d in datasets
        if resolve_dataset_visibility(d.dataset_slug) and not is_dataset_needs_review(d.dataset_slug)
    ]
    return {
        "datasets": [
            {**d._asdict(), "problem_type": _resolve_problem_type(d.dataset_slug)}
            for d in visible_datasets
        ]
    }


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
    if not resolve_dataset_visibility(dataset_slug) or is_dataset_needs_review(dataset_slug):
        return public_error_response(DATASET_NOT_FOUND)
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
                "display_title": listed.display_title,
                "display_subtitle": listed.display_subtitle,
                "home_card_icon": listed.home_card_icon,
                "short_description": listed.short_description,
                "theme_preset": listed.theme_preset,
                "problem_type": _resolve_problem_type(listed.dataset_slug),
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


@app.get("/datasets/{dataset_slug}/context")
def get_public_context(dataset_slug: str):
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    if not resolve_dataset_visibility(dataset_slug):
        return public_error_response(DATASET_NOT_FOUND)

    try:
        context = load_public_context(resolved.active_release)
    except PublicContextUnavailableError:
        return public_error_response(CONTEXT_UNAVAILABLE)

    overlay = resolve_public_presentation_overlay(dataset_slug)
    context = {**context, **overlay}

    return {
        "dataset_slug": resolved.dataset_slug,
        "context": context,
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


@app.get("/datasets/{dataset_slug}/views")
def list_predict_views(dataset_slug: str):
    try:
        resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        views = load_public_predict_view_list(dataset_slug)
    except ViewNotFoundError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    return {
        "dataset_slug": dataset_slug,
        "views": views,
    }


@app.get("/datasets/{dataset_slug}/views/{view_id}")
def get_predict_view(dataset_slug: str, view_id: str):
    try:
        resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        view = load_public_predict_view(dataset_slug, view_id)
    except ViewBindingInvalidError:
        return public_error_response(VIEW_BINDING_INVALID)
    except ViewNotFoundError:
        return public_error_response(VIEW_NOT_FOUND)

    return view


@app.get("/datasets/{dataset_slug}/views/{view_id}/customization")
def get_predict_view_customization(dataset_slug: str, view_id: str):
    try:
        resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    try:
        customization = load_public_predict_view_customization(dataset_slug, view_id)
    except CustomizationNotFoundError:
        return public_error_response(CUSTOMIZATION_NOT_FOUND)

    return customization


@app.get("/admin/runs")
def list_admin_runs(request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    return list_admin_run_summaries()


@app.delete("/admin/runs/{run_id}")
def delete_admin_run(run_id: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    result = remove_admin_run(run_id)
    if not result["removed"]:
        return ADMIN_RUN_REMOVAL_FAILED.response(errors=result["errors"])

    return result


@app.post("/admin/runs/{run_id}/promote")
def promote_admin_run_route(run_id: str, request: Request, payload: dict | None = Body(default=None)):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # Project Spec S0047: Admin Dashboard promotion is create-new-only. A
    # colliding base dataset_slug must never silently (or explicitly, via a
    # legacy/unknown request body mode) update an existing Dataset Detail
    # through this route, so no request-body mode is read or forwarded here
    # -- this route always promotes with MODE_CREATE_NEW_DATASET_DETAIL,
    # regardless of what (if anything) the request body contains.
    # promote_admin_run's own `mode` parameter and PROMOTION_MODE_INVALID
    # validation remain reachable for direct/non-Admin callers (tests,
    # scripts), just never through this route.
    result = promote_admin_run(run_id, mode=MODE_CREATE_NEW_DATASET_DETAIL)
    if not result["promoted"]:
        return ADMIN_RUN_PROMOTION_FAILED.response(errors=result["errors"])

    return result


@app.get("/admin/settings")
def get_admin_settings_route(request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    return read_admin_settings()


@app.put("/admin/settings")
def put_admin_settings_route(request: Request, settings: dict = Body(...)):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    result = write_admin_settings(settings)
    if not result["saved"]:
        return ADMIN_SETTINGS_INVALID.response(errors=result["errors"])

    return result


@app.get("/admin/datasets")
def list_admin_datasets_route(request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # Project Spec S0052: Admin-only projection that includes both draft and
    # published registry-backed Dataset Details, regardless of public
    # "Visible Publicly" state -- distinct from GET /datasets above, which
    # only ever returns published, publicly visible Dataset Details.
    try:
        datasets = list_admin_datasets()
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    return {"datasets": [dataset._asdict() for dataset in datasets]}


@app.delete("/admin/datasets/{dataset_slug}")
def delete_admin_dataset_detail(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # Project Spec S0049: removes only the matching registry/datasets.json
    # entry -- releases/, publisher/runs/, contracts, notebooks, model
    # artifacts, profile artifacts, evidence, and support-root files are
    # never touched. Distinct from DELETE /admin/runs/{run_id}, which only
    # ever removes a run artifact/directory and never mutates the registry.
    result = remove_dataset_entry(dataset_slug, repo_root=_REPO_ROOT)
    if not result["removed"]:
        return ADMIN_DATASET_DETAIL_REMOVAL_FAILED.response(errors=result["errors"])

    return result


@app.put("/admin/datasets/{dataset_slug}/slug")
def put_admin_dataset_detail_slug(
    dataset_slug: str, request: Request, payload: dict = Body(...)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # Project Spec S0051: renames only the matching registry/datasets.json
    # entry's dataset_slug -- active_release, public_metadata, releases/,
    # publisher/runs/, contracts, notebooks, model artifacts, profile
    # artifacts, evidence, and support-root files are never touched.
    # Distinct from DELETE /admin/datasets/{dataset_slug}, which removes the
    # entry entirely rather than renaming it.
    new_dataset_slug = payload.get("new_dataset_slug") if isinstance(payload, dict) else None

    result = rename_dataset_slug(dataset_slug, new_dataset_slug, repo_root=_REPO_ROOT)
    if not result["renamed"]:
        return ADMIN_DATASET_DETAIL_SLUG_RENAME_FAILED.response(errors=result["errors"])

    return result


@app.get("/admin/datasets/{dataset_slug}/profile-draft")
def get_admin_profile_draft(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        return read_profile_draft(dataset_slug)
    except ValueError:
        return public_error_response(PROFILE_DRAFT_DATASET_SLUG_INVALID)


@app.put("/admin/datasets/{dataset_slug}/profile-draft")
def put_admin_profile_draft(
    dataset_slug: str, request: Request, profile: dict = Body(...)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        result = save_profile_draft(dataset_slug, profile)
    except ValueError:
        return public_error_response(PROFILE_DRAFT_DATASET_SLUG_INVALID)

    if not result["saved"]:
        return PROFILE_DRAFT_INVALID.response(errors=result["errors"])

    return result


@app.put("/admin/datasets/{dataset_slug}/publish")
def put_admin_profile_publish(
    dataset_slug: str, request: Request, profile: dict | None = Body(default=None)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        # Project Spec S0061: Dataset Admin's normal Publish Changes flow
        # sends the current form payload directly (no persisted profile-draft
        # required); a request with no body falls back to the legacy
        # publish-the-stored-draft behavior, kept only for backward
        # compatibility with any caller that still relies on it. Checked with
        # isinstance rather than "is not None" so direct (non-FastAPI-routed)
        # calls that omit the profile argument entirely -- which receive the
        # Body(default=None) marker object itself as the Python default, not
        # a real None -- still take the legacy branch, matching what FastAPI
        # itself passes (a real None) when an HTTP request omits the body.
        if isinstance(profile, dict):
            result = publish_profile_payload(dataset_slug, profile)
        else:
            result = publish_profile(dataset_slug)
    except ValueError:
        return public_error_response(PROFILE_PUBLISH_DATASET_SLUG_INVALID)

    if not result["published"]:
        return PROFILE_PUBLISH_FAILED.response(errors=result["errors"])

    return result


@app.put("/admin/datasets/{dataset_slug}/visibility")
def put_admin_profile_visibility(
    dataset_slug: str, request: Request, payload: dict = Body(...)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    visible = payload.get("visible") if isinstance(payload, dict) else None
    if not isinstance(visible, bool):
        return public_error_response(PROFILE_VISIBILITY_PAYLOAD_INVALID)

    try:
        return set_dataset_visibility(dataset_slug, visible)
    except ValueError:
        return public_error_response(PROFILE_VISIBILITY_DATASET_SLUG_INVALID)


@app.get("/admin/datasets/{dataset_slug}/views/{view_id}/customization")
def get_admin_predict_view_customization(dataset_slug: str, view_id: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        return read_predict_view_customization(dataset_slug, view_id)
    except ValueError:
        return public_error_response(PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID)


@app.put("/admin/datasets/{dataset_slug}/views/{view_id}/customization")
def put_admin_predict_view_customization(
    dataset_slug: str, view_id: str, request: Request, customization: dict = Body(...)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        result = save_predict_view_customization(dataset_slug, view_id, customization)
    except ValueError:
        return public_error_response(PREDICT_VIEW_CUSTOMIZATION_IDENTIFIER_INVALID)

    if not result["saved"]:
        return PREDICT_VIEW_CUSTOMIZATION_INVALID.response(errors=result["errors"])

    return result


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
