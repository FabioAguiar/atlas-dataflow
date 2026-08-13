import json
import math
import os
import pickle
import re
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Ensure the repository root is on the Python path so registry/ is importable
# when main.py is invoked from the api/ subdirectory.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from contract_loader import ContractUnavailableError, load_contract  # noqa: E402
from payload_validator import (  # noqa: E402
    TYPE_MISMATCH,
    ValidationFailure,
    validate_and_normalize_payload,
)
from public_errors import (  # noqa: E402
    CONTRACT_UNAVAILABLE,
    DATASET_MAINTENANCE,
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
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    InferenceRuntimeError,
    JOBLIB_SKLEARN_PREDICT_STRATEGY,
    RUNTIME_DIAGNOSTIC_CODES,
    execute_prediction,
    load_inference_bundle,
    load_joblib_sklearn_model,
    project_result_contract,
    validate_binary_classification_result,
)
from external_inference_client import (  # noqa: E402
    execute_external_inference,
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
    SNAPSHOT_STATUS_CURRENT_RELEASE,
    resolve_dataset_snapshot_readiness,
    resolve_dataset_visibility,
    resolve_public_presentation_overlay,
)
from admin_runs import (  # noqa: E402
    list_admin_run_summaries,
    promote_admin_run,
    remove_admin_run,
)
from admin_profile_drafts import read_profile_draft, save_profile_draft  # noqa: E402
from admin_profile_publish import (  # noqa: E402
    HOME_CARD_IMAGE_MAX_BYTES,
    publish_profile,
    publish_profile_payload,
    read_published_profile_snapshot,
    remove_profile_artifacts,
    resolve_documentation_media_path,
    resolve_home_card_media_path,
    store_documentation_image,
    store_home_card_image,
)
from admin_profile_visibility import (  # noqa: E402
    approve_dataset_review,
    get_dataset_publication_state,
    set_dataset_visibility,
)
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

# Project Spec S0121: bounded per-resource error for the private authoring
# read model's `views` resource, distinct from REGISTRY_UNAVAILABLE (which is
# a top-level resolution failure) -- the dataset registry and active release
# are already confirmed readable by the time this resource is projected, so
# only the Predict View registry itself is in question here.
PREDICT_VIEW_REGISTRY_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="predict_view_registry_unavailable",
    error_code="PREDICT_VIEW_REGISTRY_UNAVAILABLE",
    message="The Predict View registry is temporarily unavailable.",
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

HOME_CARD_IMAGE_UPLOAD_FAILED = PublicError(
    status_code=422,
    error_type="home_card_image_upload_failed",
    error_code="HOME_CARD_IMAGE_UPLOAD_FAILED",
    message="The Home card image could not be uploaded.",
)

DOCUMENTATION_IMAGE_UPLOAD_FAILED = PublicError(
    status_code=422,
    error_type="documentation_image_upload_failed",
    error_code="DOCUMENTATION_IMAGE_UPLOAD_FAILED",
    message="The Documentation image could not be uploaded.",
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

# Project Spec S0125: review-approval route errors.
DATASET_REVIEW_STATUS_INVALID = PublicError(
    status_code=422,
    error_type="dataset_review_status_invalid",
    error_code="DATASET_REVIEW_STATUS_INVALID",
    message="The review-status payload must be a JSON object with status set to 'ready'.",
)

DATASET_REVIEW_APPROVAL_BLOCKED = PublicError(
    status_code=409,
    error_type="dataset_review_approval_blocked",
    error_code="DATASET_REVIEW_APPROVAL_BLOCKED",
    message="The Dataset Detail is not currently eligible for review approval.",
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


def _resolve_public_dataset_detail_access(dataset_slug: str):
    """
    Resolve dataset_slug and classify public Dataset Detail access in one
    place, so every guarded route enforces the same order: resolve the
    registered dataset and its active release, classify public access,
    only then let endpoint-specific loading proceed. Project Spec S0117;
    extended by Project Spec S0125 to also require a published profile
    snapshot currently bound to the resolved active release -- complete
    public readiness is visibility + review + snapshot alignment together.

    Returns the resolved dataset (registry.resolve.ResolvedDataset) when
    access is ready. Returns a bounded JSONResponse
    (DATASET_NOT_FOUND / DATASET_MAINTENANCE / RELEASE_UNAVAILABLE /
    REGISTRY_UNAVAILABLE) otherwise -- callers must check the return type
    before using it. A hidden, needs_review, or snapshot-misaligned dataset
    always maps to the same generic DATASET_MAINTENANCE response; the
    private reason is never exposed here.
    """
    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    if not resolve_dataset_visibility(dataset_slug) or is_dataset_needs_review(dataset_slug):
        return public_error_response(DATASET_MAINTENANCE)

    snapshot = resolve_dataset_snapshot_readiness(dataset_slug, resolved.active_release)
    if snapshot["status"] != SNAPSHOT_STATUS_CURRENT_RELEASE:
        return public_error_response(DATASET_MAINTENANCE)

    return resolved


def _dataset_publicly_ready(dataset_slug: str) -> bool:
    """
    Complete public-list readiness classification for one dataset_slug,
    reused by GET /datasets so the list applies the exact same visibility +
    review + snapshot-alignment decision as every guarded Dataset Detail
    route (Project Spec S0125). A dataset whose active release cannot be
    resolved at all is excluded rather than raising, mirroring
    _resolve_problem_type's fail-open-per-dataset behavior for this same
    per-listing-item loop.
    """
    if not resolve_dataset_visibility(dataset_slug) or is_dataset_needs_review(dataset_slug):
        return False
    try:
        resolved = resolve_dataset(dataset_slug)
    except (DatasetUnavailableError, ReleaseUnavailableError, RegistryInvalidError):
        return False
    snapshot = resolve_dataset_snapshot_readiness(dataset_slug, resolved.active_release)
    return snapshot["status"] == SNAPSHOT_STATUS_CURRENT_RELEASE


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


def _remove_predict_views_for_dataset(dataset_slug: str, repo_root: Path) -> dict:
    """Remove only predict-view records owned by dataset_slug."""
    path = repo_root / "registry" / "predict-views.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"removed": False, "original": None}

    views = registry.get("predict_views") if isinstance(registry, dict) else None
    if not isinstance(views, list):
        return {"removed": False, "original": None}

    retained = [
        record
        for record in views
        if not isinstance(record, dict) or record.get("dataset_slug") != dataset_slug
    ]
    original = json.dumps(registry, indent=2) + "\n"
    if len(retained) == len(views):
        return {"removed": True, "original": original}

    registry["predict_views"] = retained
    try:
        path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return {"removed": False, "original": None}
    return {"removed": True, "original": original}


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


# S0109: the only production loader strategy allowlist. Loader implementation
# lives in runtime/inference.py; this is the single place the allowlist
# selection is made, per the spec's "keep the public allowlist selection in
# api/main.py, do not introduce a plugin registry" requirement.
_INFERENCE_LOADER_STRATEGIES = {JOBLIB_SKLEARN_PREDICT_STRATEGY: load_joblib_sklearn_model}
_INFERENCE_SUPPORTED_SERIALIZATION_FORMATS = ("joblib",)


def _read_active_release_manifest(active_release: str) -> tuple[Path, dict] | None:
    release_dir = _inference_releases_root() / active_release
    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return release_dir, manifest


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
    visible_datasets = [d for d in datasets if _dataset_publicly_ready(d.dataset_slug)]
    return {
        "datasets": [
            {**d._asdict(), "problem_type": _resolve_problem_type(d.dataset_slug)}
            for d in visible_datasets
        ]
    }


@app.get("/datasets/{dataset_slug}")
def get_dataset(dataset_slug: str):
    guard = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(guard, JSONResponse):
        return guard

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
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

    try:
        public_contract = load_public_contract(resolved.active_release)
    except PublicContractUnavailableError:
        return public_error_response(PUBLIC_CONTRACT_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "contract": public_contract,
        "result_contract": _project_result_contract_safely(resolved.active_release),
    }


def _project_result_contract_safely(active_release: str) -> dict:
    """Read-only result-contract projection: never loads the model or executes inference."""

    unavailable = {"status": "unavailable", "reason": "binary_result_semantics_unavailable"}

    resolved_manifest = _read_active_release_manifest(active_release)
    if resolved_manifest is None:
        return unavailable
    release_dir, manifest = resolved_manifest

    try:
        loaded = load_inference_bundle(
            {"path": str(release_dir), "artifacts": manifest.get("artifacts", [])},
            manifest=manifest,
            bundle_loader=_load_bundle,
        )
    except InferenceRuntimeError:
        return unavailable
    except Exception:
        return unavailable

    declaration = loaded.bundle if isinstance(loaded.bundle, dict) else manifest
    try:
        return project_result_contract(declaration)
    except Exception:
        return unavailable


def _inference_failure_response(
    *, diagnostic_code: str | None, include_runtime_diagnostic: bool
) -> JSONResponse:
    """
    Project Spec S0151: the single place a bounded, allowlisted
    ``runtime_diagnostic`` may be attached to the existing generic
    INFERENCE_FAILURE response. ``include_runtime_diagnostic`` is an explicit
    caller decision (the private Admin route opts in; the public route never
    does) -- route privacy is never inferred here from anything about the
    request itself. ``diagnostic_code`` must be a member of the closed
    RUNTIME_DIAGNOSTIC_CODES vocabulary or the response stays generic; this
    never reads public_errors.py's INFERENCE_FAILURE.response() `errors` path,
    only its status/type/code/message fields, so the extra key can be added
    without modifying public_errors.py (outside this request's edit scope).
    """
    if include_runtime_diagnostic and diagnostic_code in RUNTIME_DIAGNOSTIC_CODES:
        return JSONResponse(
            status_code=INFERENCE_FAILURE.status_code,
            content={
                "error_type": INFERENCE_FAILURE.error_type,
                "error_code": INFERENCE_FAILURE.error_code,
                "message": INFERENCE_FAILURE.message,
                "runtime_diagnostic": {"code": diagnostic_code},
            },
        )
    return public_error_response(INFERENCE_FAILURE)


def _execute_via_external_inference_service(
    dataset_slug: str,
    active_release: str,
    normalized_payload: dict,
    *,
    bundle_identity: dict,
    runtime_profile: dict,
    include_runtime_diagnostic: bool,
):
    """S0161: delegates to the isolated external-inference service.

    Reuses the exact same failure-response shaping as the local
    joblib_sklearn_predict path (_inference_failure_response), so a caller
    of _execute_governed_inference cannot tell which loader strategy served
    a given release from the response shape alone.
    """

    try:
        result = execute_external_inference(
            normalized_payload,
            release_id=active_release,
            bundle_identity=bundle_identity,
            runtime_profile=runtime_profile,
        )
    except InferenceRuntimeError as exc:
        return _inference_failure_response(
            diagnostic_code=exc.diagnostic_code,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )
    except Exception:
        return _inference_failure_response(
            diagnostic_code=None,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    return {
        "dataset_slug": dataset_slug,
        "result": result,
    }


class RuntimeDispatchError(InferenceRuntimeError):
    """Deterministic failure raised while resolving governed runtime dispatch."""

    def __init__(self, category: str, message: str, *, diagnostic_code: str) -> None:
        super().__init__(message, diagnostic_code=diagnostic_code)
        self.category = category


def _resolve_runtime_dispatch(declaration: dict) -> tuple[str, dict | None, dict]:
    runtime_execution = declaration.get("runtime_execution")
    if not isinstance(runtime_execution, dict):
        raise RuntimeDispatchError(
            "runtime_profile_invalid",
            "Governed runtime execution metadata is missing.",
            diagnostic_code="INFERENCE_BUNDLE_UNAVAILABLE",
        )

    strategy = runtime_execution.get("execution_strategy", "in_process")
    if strategy == "in_process":
        return strategy, None, runtime_execution
    if strategy != "isolated_service":
        raise RuntimeDispatchError(
            "unsupported_execution_strategy",
            "Governed runtime execution strategy is unsupported.",
            diagnostic_code="INFERENCE_BUNDLE_UNAVAILABLE",
        )

    profile = runtime_execution.get("runtime_profile")
    if not isinstance(profile, dict):
        raise RuntimeDispatchError(
            "runtime_profile_invalid",
            "Governed isolated runtime profile is missing.",
            diagnostic_code="INFERENCE_BUNDLE_UNAVAILABLE",
        )
    required = profile.get("required_consumer_runtime")
    producer = profile.get("producer_runtime")
    if not isinstance(required, dict) or not isinstance(required.get("dependencies"), dict):
        raise RuntimeDispatchError(
            "runtime_profile_invalid",
            "Governed isolated runtime identity cannot be resolved.",
            diagnostic_code="RUNTIME_DEPENDENCY_UNAVAILABLE",
        )
    if profile.get("compatibility_policy") == "exact" and producer != required:
        raise RuntimeDispatchError(
            "runtime_profile_mismatch",
            "Governed producer and required runtime identities do not match.",
            diagnostic_code="RUNTIME_DEPENDENCY_UNAVAILABLE",
        )
    if profile.get("trusted_source_required") is not True:
        raise RuntimeDispatchError(
            "untrusted_artifact",
            "Governed isolated runtime requires a trusted artifact.",
            diagnostic_code="INFERENCE_BUNDLE_UNAVAILABLE",
        )
    if profile.get("load_safe") is not True:
        raise RuntimeDispatchError(
            "load_not_safe",
            "Governed isolated runtime is not declared load-safe.",
            diagnostic_code="MODEL_DESERIALIZATION_FAILED",
        )
    integrity = profile.get("artifact_integrity")
    model_artifact = declaration.get("model_artifact")
    if (
        not isinstance(integrity, dict)
        or not isinstance(model_artifact, dict)
        or integrity.get("model_sha256") != model_artifact.get("sha256")
    ):
        raise RuntimeDispatchError(
            "artifact_integrity_mismatch",
            "Governed isolated runtime integrity identity does not match the bundle artifact.",
            diagnostic_code="MODEL_ARTIFACT_HASH_MISMATCH",
        )
    return strategy, profile, runtime_execution


def _execute_governed_inference(
    dataset_slug: str,
    active_release: str,
    payload,
    *,
    include_runtime_diagnostic: bool = False,
):
    """
    Project Spec S0143: the shared post-resolution inference execution
    boundary used by both the public inference route and the private Admin
    Live Preview inference route. Callers are responsible for their own
    route-specific access resolution first -- the public readiness guard for
    the public route, Admin authorization plus direct registered-dataset
    resolution for the private route -- this function performs no access
    classification of its own and must not be reachable before that
    resolution has already succeeded.

    Project Spec S0151: ``include_runtime_diagnostic`` is the caller's
    explicit, route-level decision to allow one bounded allowlisted
    ``runtime_diagnostic.code`` onto an otherwise-unchanged generic
    INFERENCE_FAILURE response -- the public route always omits it.
    """
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
        runtime_contract = load_contract(active_release)
    except ContractUnavailableError:
        return public_error_response(CONTRACT_UNAVAILABLE)

    # Project Spec S0156: validate_and_normalize_payload is the governed
    # entry point -- its normalized_payload (never the raw caller payload)
    # is what reaches execute_prediction, so a conditional blank-input
    # policy's materialized value is what the model actually sees.
    validation_report = validate_and_normalize_payload(payload, runtime_contract)
    if validation_report.failures:
        return validation_error_response(validation_report.failures)

    resolved_manifest = _read_active_release_manifest(active_release)
    if resolved_manifest is None:
        return public_error_response(INFERENCE_FAILURE)
    release_dir, manifest = resolved_manifest

    try:
        loaded_bundle = load_inference_bundle(
            {"path": str(release_dir), "artifacts": manifest.get("artifacts", [])},
            manifest=manifest,
            bundle_loader=_load_bundle,
        )
        declaration = loaded_bundle.bundle if isinstance(loaded_bundle.bundle, dict) else manifest
        strategy, runtime_profile, _runtime_execution = _resolve_runtime_dispatch(declaration)
    except InferenceRuntimeError as exc:
        return _inference_failure_response(
            diagnostic_code=exc.diagnostic_code,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )
    except Exception:
        return _inference_failure_response(
            diagnostic_code=None,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    if strategy == "isolated_service" and runtime_profile is not None:
        bundle_identity = declaration.get("bundle_identity")
        dataset_context = declaration.get("dataset_context")
        if not isinstance(bundle_identity, dict) or not isinstance(dataset_context, dict):
            return _inference_failure_response(
                diagnostic_code="INFERENCE_BUNDLE_UNAVAILABLE",
                include_runtime_diagnostic=include_runtime_diagnostic,
            )
        return _execute_via_external_inference_service(
            dataset_slug,
            active_release,
            dict(validation_report.normalized_payload),
            bundle_identity={
                "bundle_id": bundle_identity.get("bundle_id"),
                "dataset_slug": dataset_context.get("dataset_slug"),
            },
            runtime_profile=runtime_profile,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    try:
        prediction_result = execute_prediction(
            {"path": str(release_dir), "artifacts": manifest.get("artifacts", [])},
            dict(validation_report.normalized_payload),
            manifest=manifest,
            bundle_loader=_load_bundle,
            loader_strategies=_INFERENCE_LOADER_STRATEGIES,
            supported_serialization_formats=_INFERENCE_SUPPORTED_SERIALIZATION_FORMATS,
            runtime_feature_metadata=_runtime_feature_metadata(runtime_contract),
        )
    except InferenceRuntimeError as exc:
        return _inference_failure_response(
            diagnostic_code=exc.diagnostic_code,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )
    except Exception:
        return _inference_failure_response(
            diagnostic_code=None,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    result = prediction_result.get("result") if isinstance(prediction_result, dict) else None
    if not isinstance(result, dict):
        return _inference_failure_response(
            diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    try:
        validate_binary_classification_result(result)
    except InferenceRuntimeError as exc:
        return _inference_failure_response(
            diagnostic_code=exc.diagnostic_code,
            include_runtime_diagnostic=include_runtime_diagnostic,
        )

    return {
        "dataset_slug": dataset_slug,
        "result": result,
    }


@app.post("/datasets/{dataset_slug}/inference")
def validate_dataset_inference_payload(
    dataset_slug: str,
    payload=Body(...),
):
    # Project Spec S0117: access classification must run before payload
    # type/schema validation, contract loading, bundle loading, model
    # loading, or prediction -- a malformed body must never leak whether a
    # hidden/needs_review dataset exists, and no runtime work should happen
    # for a dataset that is not ready.
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

    return _execute_governed_inference(resolved.dataset_slug, resolved.active_release, payload)


@app.post("/admin/datasets/{dataset_slug}/inference")
def post_admin_dataset_inference(
    dataset_slug: str,
    request: Request,
    payload=Body(...),
):
    """
    Project Spec S0143: private, read-only-w.r.t.-registry Admin execution
    route for the Dataset Detail Live Preview Inference tab. Deliberately
    resolves the registered dataset and active release via resolve_dataset()
    directly -- never via _resolve_public_dataset_detail_access(),
    resolve_dataset_visibility(), or resolve_dataset_snapshot_readiness() --
    so a hidden or needs_review dataset with a valid active release can
    still execute inference here, exactly like the S0121 private authoring
    read model. Shares the same post-resolution payload validation, runtime
    execution and binary-result validation as the public route through
    _execute_governed_inference; performs no registry, profile, publication,
    release or artifact mutation.
    """
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    return _execute_governed_inference(
        resolved.dataset_slug,
        resolved.active_release,
        payload,
        include_runtime_diagnostic=True,
    )


@app.get("/datasets/{dataset_slug}/metrics")
def get_public_metrics(dataset_slug: str):
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

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
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

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
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

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
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

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
    guard = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(guard, JSONResponse):
        return guard

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
    # Project Spec S0117: access must be classified before the view itself
    # is looked up, so a maintenance dataset with an unknown view_id still
    # returns DATASET_MAINTENANCE, never VIEW_NOT_FOUND -- this must not
    # reveal whether a hidden dataset contains a requested view.
    guard = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(guard, JSONResponse):
        return guard

    try:
        view = load_public_predict_view(dataset_slug, view_id)
    except ViewBindingInvalidError:
        return public_error_response(VIEW_BINDING_INVALID)
    except ViewNotFoundError:
        return public_error_response(VIEW_NOT_FOUND)

    return view


@app.get("/datasets/{dataset_slug}/views/{view_id}/customization")
def get_predict_view_customization(dataset_slug: str, view_id: str):
    resolved = _resolve_public_dataset_detail_access(dataset_slug)
    if isinstance(resolved, JSONResponse):
        return resolved

    try:
        customization = load_public_predict_view_customization(
            dataset_slug, view_id, resolved.active_release
        )
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

    # Project Specs S0089/S0091: the mutable registry timestamp is the
    # canonical operational source. Historical runs remain only a legacy
    # fallback for entries created before that field existed.
    last_updated_by_slug: dict[str, str] = {}
    run_listing = list_admin_run_summaries()
    runs = run_listing.get("runs", []) if isinstance(run_listing, dict) else []
    for run in runs:
        if not isinstance(run, dict):
            continue
        slug = run.get("dataset_candidate")
        created_at = run.get("created_at")
        if not isinstance(slug, str) or not isinstance(created_at, str):
            continue
        current = last_updated_by_slug.get(slug)
        try:
            if current is None or datetime.fromisoformat(created_at.replace("Z", "+00:00")) > datetime.fromisoformat(current.replace("Z", "+00:00")):
                last_updated_by_slug[slug] = created_at
        except (TypeError, ValueError):
            continue

    projected = []
    for dataset in datasets:
        item = dataset._asdict()
        last_updated = dataset.dataset_detail_updated_at

        # Both supported release-id families carry a deterministic UTC date.
        # Derive it without reading or modifying immutable release artifacts.
        if last_updated is None and isinstance(dataset.active_release, str):
            release_match = re.fullmatch(
                r"release-(\d{4})(\d{2})(\d{2})(?:-\d{3}|t\d{6}z)",
                dataset.active_release,
            )
            if release_match:
                candidate = "-".join(release_match.groups())
                try:
                    last_updated = datetime.fromisoformat(candidate).date().isoformat()
                except ValueError:
                    pass

        if last_updated is None:
            last_updated = last_updated_by_slug.get(dataset.dataset_slug)
        item["last_updated"] = last_updated
        projected.append(item)
    return {"datasets": projected}


@app.delete("/admin/datasets/{dataset_slug}")
def delete_admin_dataset_detail(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # Project Specs S0049/S0082/S0083: remove the matching Dataset Detail,
    # predict views bound to its slug, and its mutable public-profile lifecycle.
    # Releases, runs, contracts, notebooks, and model artifacts are never
    # touched. Distinct from DELETE /admin/runs/{run_id}, which only
    # ever removes a run artifact/directory and never mutates the registry.
    predict_view_cleanup = _remove_predict_views_for_dataset(dataset_slug, _REPO_ROOT)
    if not predict_view_cleanup["removed"]:
        return ADMIN_DATASET_DETAIL_REMOVAL_FAILED.response(
            errors=[{"code": "PREDICT_VIEW_CLEANUP_FAILED", "message": "Associated predict views could not be removed."}]
        )

    result = remove_dataset_entry(dataset_slug, repo_root=_REPO_ROOT)
    if not result["removed"]:
        original_predict_views = predict_view_cleanup.get("original")
        if isinstance(original_predict_views, str):
            try:
                (_REPO_ROOT / "registry" / "predict-views.json").write_text(
                    original_predict_views, encoding="utf-8"
                )
            except OSError:
                pass
        return ADMIN_DATASET_DETAIL_REMOVAL_FAILED.response(errors=result["errors"])

    profile_cleanup = remove_profile_artifacts(dataset_slug, repo_root=_REPO_ROOT)
    if not profile_cleanup["completed"]:
        return ADMIN_DATASET_DETAIL_REMOVAL_FAILED.response(errors=profile_cleanup["errors"])

    result["profile_cleanup"] = {
        "completed": True,
        "artifacts_removed": profile_cleanup["artifacts_removed"],
        "media_removed": profile_cleanup["media_removed"],
    }
    return result


@app.put("/admin/datasets/{dataset_slug}/slug")
def put_admin_dataset_detail_slug(
    dataset_slug: str, request: Request, payload: dict = Body(...)
):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    # S0088 extends the S0051 rename boundary: the matching registry entry and
    # its slug-keyed profile/predict-view state are rebound together, while
    # active_release, media, releases/, publisher/runs/, contracts, notebooks,
    # model artifacts, and support-root files remain untouched.
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
        result = read_profile_draft(dataset_slug)
        # S0077/S0084: a direct-publish snapshot is authoritative only for
        # the Dataset Detail lifecycle whose live active_release it records.
        # Keep the private draft in the response for compatibility, while
        # explicitly telling current clients to use a clean baseline when a
        # same-slug snapshot is missing, unbound, or belongs to an old release.
        current_active_release = None
        try:
            current_active_release = resolve_dataset(dataset_slug).active_release
        except (DatasetUnavailableError, RegistryInvalidError, ReleaseUnavailableError):
            pass
        published_snapshot = read_published_profile_snapshot(dataset_slug)
        snapshot_release = (
            published_snapshot.get("active_release_at_publish_time")
            if isinstance(published_snapshot, dict)
            else None
        )
        if (
            isinstance(current_active_release, str)
            and current_active_release
            and snapshot_release == current_active_release
        ):
            result["published_snapshot"] = published_snapshot
            result["profile_hydration"] = {
                "source": "current_release_snapshot",
                "active_release": current_active_release,
            }
        elif isinstance(current_active_release, str) and current_active_release:
            result["profile_hydration"] = {
                "source": "fresh_promotion_baseline",
                "active_release": current_active_release,
            }
        return result
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


@app.post("/admin/datasets/{dataset_slug}/home-card-image")
async def post_admin_home_card_image(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_slug):
        return public_error_response(PROFILE_PUBLISH_DATASET_SLUG_INVALID)
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > HOME_CARD_IMAGE_MAX_BYTES:
        return HOME_CARD_IMAGE_UPLOAD_FAILED.response(errors=[{"message": "Choose an image smaller than 10 MB."}])
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > HOME_CARD_IMAGE_MAX_BYTES:
            return HOME_CARD_IMAGE_UPLOAD_FAILED.response(errors=[{"message": "Choose an image smaller than 10 MB."}])
    result = store_home_card_image(
        request.headers.get("x-file-name"), request.headers.get("content-type"), bytes(chunks), _REPO_ROOT
    )
    if not result["uploaded"]:
        return HOME_CARD_IMAGE_UPLOAD_FAILED.response(errors=[{"message": result["error"]}])
    return result


@app.get("/media/home-cards/{filename}")
def get_home_card_image(filename: str):
    path = resolve_home_card_media_path(filename, _REPO_ROOT)
    if path is None:
        return _admin_route_not_found_response()
    return FileResponse(path)


@app.post("/admin/datasets/{dataset_slug}/documentation-image")
async def post_admin_documentation_image(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_slug):
        return public_error_response(PROFILE_PUBLISH_DATASET_SLUG_INVALID)
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > HOME_CARD_IMAGE_MAX_BYTES:
        return DOCUMENTATION_IMAGE_UPLOAD_FAILED.response(errors=[{"message": "Choose an image smaller than 10 MB."}])
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > HOME_CARD_IMAGE_MAX_BYTES:
            return DOCUMENTATION_IMAGE_UPLOAD_FAILED.response(errors=[{"message": "Choose an image smaller than 10 MB."}])
    result = store_documentation_image(
        dataset_slug,
        request.headers.get("x-file-name"),
        request.headers.get("content-type"),
        bytes(chunks),
        _REPO_ROOT,
    )
    if not result["uploaded"]:
        return DOCUMENTATION_IMAGE_UPLOAD_FAILED.response(errors=[{"message": result["error"]}])
    return result


@app.get("/media/documentation/{dataset_slug}/{filename}")
def get_documentation_image(dataset_slug: str, filename: str):
    path = resolve_documentation_media_path(dataset_slug, filename, _REPO_ROOT)
    if path is None:
        return _admin_route_not_found_response()
    return FileResponse(path)


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


@app.get("/admin/datasets/{dataset_slug}/publication-state")
def get_admin_profile_publication_state(dataset_slug: str, request: Request):
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()
    try:
        return get_dataset_publication_state(dataset_slug)
    except ValueError:
        return public_error_response(PROFILE_VISIBILITY_DATASET_SLUG_INVALID)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)


@app.put("/admin/datasets/{dataset_slug}/review-status")
def put_admin_dataset_review_status(
    dataset_slug: str, request: Request, payload: dict = Body(...)
):
    """
    Project Spec S0125: the sole controlled Admin route that approves review
    for one registered Dataset Detail. Accepts only the transition to
    "ready" -- there is no reverse transition through this route. Approval
    readiness (a needs_review dataset with a current-release snapshot, or an
    already-ready dataset whose snapshot is still current) is delegated
    entirely to admin_profile_visibility.approve_dataset_review(), which
    also enforces that approval never depends on configured visibility.
    """
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    status = payload.get("status") if isinstance(payload, dict) else None
    if status != "ready":
        return public_error_response(DATASET_REVIEW_STATUS_INVALID)

    try:
        result = approve_dataset_review(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    if not result["approved"]:
        return DATASET_REVIEW_APPROVAL_BLOCKED.response(errors=result["errors"])

    return {
        "dataset_slug": result["dataset_slug"],
        "review_status": result["review_status"],
        "changed": result["changed"],
        "publication_state": result["publication_state"],
    }


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


def _authoring_resource_ready(data) -> dict:
    return {"status": "ready", "data": data}


def _authoring_resource_unavailable(public_error: PublicError) -> dict:
    return {
        "status": "unavailable",
        "error": {
            "type": public_error.error_type,
            "code": public_error.error_code,
            "message": public_error.message,
        },
    }


def _runtime_feature_metadata(runtime_contract: dict) -> dict[str, dict[str, bool]]:
    """
    Project Spec S0152: normalized ``{feature_name: {"required": bool}}`` map
    built from the same already-loaded, already-validated-against runtime
    contract used by ``validate_payload`` -- carried into ``execute_prediction``
    so the post-validation row-construction boundary can distinguish a
    contractually optional omission (materialize a missing sentinel) from a
    genuine runtime input-contract inconsistency. Mirrors the exact
    ``required`` convention already used by
    ``_project_admin_inference_guidance`` below (default True unless the
    feature explicitly declares ``required: false``).
    """
    features = runtime_contract.get("features")
    if not isinstance(features, list):
        return {}

    metadata: dict[str, dict[str, bool]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        name = feature.get("name")
        if not isinstance(name, str) or not name:
            continue
        metadata[name] = {"required": feature.get("required", True) is not False}
    return metadata


def _project_admin_inference_guidance(runtime_contract: dict) -> list[dict]:
    """Project the bounded, private form guidance needed by Dataset Admin."""
    features = runtime_contract.get("features")
    if not isinstance(features, list):
        return []

    guidance: list[dict] = []
    seen_names: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        name = feature.get("name")
        if not isinstance(name, str) or not name.strip() or name in seen_names:
            continue
        seen_names.add(name)

        entry = {
            "field_name": name,
            "required": feature.get("required", True) is not False,
        }
        if feature.get("type") == "numeric":
            constraints = feature.get("domain_constraints")
            if isinstance(constraints, dict):
                numeric_domain = {}
                minimum = constraints.get("min")
                maximum = constraints.get("max")
                if (
                    isinstance(minimum, (int, float))
                    and not isinstance(minimum, bool)
                    and math.isfinite(minimum)
                ):
                    numeric_domain["min"] = minimum
                if (
                    isinstance(maximum, (int, float))
                    and not isinstance(maximum, bool)
                    and math.isfinite(maximum)
                ):
                    numeric_domain["max"] = maximum
                if not (
                    "min" in numeric_domain
                    and "max" in numeric_domain
                    and numeric_domain["min"] > numeric_domain["max"]
                ) and numeric_domain:
                    entry["numeric_domain"] = numeric_domain
        guidance.append(entry)

    return guidance


def _project_admin_authoring_dataset_identity(dataset_slug: str) -> dict | None:
    """
    Admin-safe `dataset` resource projection for the private authoring read
    model. Reuses the existing Admin dataset listing projection (Project
    Spec S0052) rather than the public dataset route, so this never depends
    on _resolve_public_dataset_detail_access() or public visibility/review
    state. Returns None only when the registry itself cannot be read --
    which resolve_dataset() above has already ruled out in practice, but this
    stays defensively bounded rather than assuming that can never change.
    """
    try:
        admin_datasets = list_admin_datasets()
    except RegistryInvalidError:
        return None
    for dataset in admin_datasets:
        if dataset.dataset_slug == dataset_slug:
            return dataset._asdict()
    return None


@app.get("/admin/datasets/{dataset_slug}/authoring-context")
def get_admin_dataset_authoring_context(dataset_slug: str, request: Request):
    """
    Project Spec S0121: private, read-only Admin authoring read model.

    Deliberately resolves the registered dataset and active release via
    resolve_dataset() directly -- never via
    _resolve_public_dataset_detail_access() -- so configured visibility and
    review_status never gate this route; a hidden or needs_review dataset
    must still be authorable in Dataset Admin. Every resource below is
    projected independently into an explicit ready/unavailable state so one
    unavailable optional resource never erases the others.
    """
    if not _admin_request_authorized(request):
        return _admin_route_not_found_response()

    try:
        resolved = resolve_dataset(dataset_slug)
    except DatasetUnavailableError:
        return public_error_response(DATASET_NOT_FOUND)
    except ReleaseUnavailableError:
        return public_error_response(RELEASE_UNAVAILABLE)
    except RegistryInvalidError:
        return public_error_response(REGISTRY_UNAVAILABLE)

    dataset_projection = _project_admin_authoring_dataset_identity(resolved.dataset_slug)
    dataset_resource = (
        _authoring_resource_ready(dataset_projection)
        if dataset_projection is not None
        else _authoring_resource_unavailable(REGISTRY_UNAVAILABLE)
    )

    try:
        context = load_public_context(resolved.active_release)
        context_resource = _authoring_resource_ready(context)
    except PublicContextUnavailableError:
        context_resource = _authoring_resource_unavailable(CONTEXT_UNAVAILABLE)

    try:
        public_contract = load_public_contract(resolved.active_release)
        contract_resource = _authoring_resource_ready(
            {
                "contract": public_contract,
                "result_contract": _project_result_contract_safely(resolved.active_release),
            }
        )
    except PublicContractUnavailableError:
        contract_resource = _authoring_resource_unavailable(PUBLIC_CONTRACT_UNAVAILABLE)

    try:
        runtime_contract = load_contract(resolved.active_release)
        inference_guidance_resource = _authoring_resource_ready(
            _project_admin_inference_guidance(runtime_contract)
        )
    except ContractUnavailableError:
        inference_guidance_resource = _authoring_resource_unavailable(CONTRACT_UNAVAILABLE)

    try:
        metrics = load_public_metrics(resolved.active_release)
        metrics_resource = _authoring_resource_ready(metrics)
    except PublicMetricsUnavailableError:
        metrics_resource = _authoring_resource_unavailable(METRICS_UNAVAILABLE)

    try:
        visualizations = load_public_visualizations(resolved.active_release)
        visualizations_resource = _authoring_resource_ready(visualizations)
    except PublicVisualizationsUnavailableError:
        visualizations_resource = _authoring_resource_unavailable(VISUALIZATIONS_UNAVAILABLE)

    try:
        views = load_public_predict_view_list(resolved.dataset_slug)
        views_resource = _authoring_resource_ready(views)
    except ViewNotFoundError:
        views_resource = _authoring_resource_unavailable(PREDICT_VIEW_REGISTRY_UNAVAILABLE)

    return {
        "dataset_slug": resolved.dataset_slug,
        "active_release": resolved.active_release,
        "dataset": dataset_resource,
        "context": context_resource,
        "contract": contract_resource,
        "inference_guidance": inference_guidance_resource,
        "metrics": metrics_resource,
        "visualizations": visualizations_resource,
        "views": views_resource,
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
