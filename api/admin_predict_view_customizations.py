"""
Private/admin service module for predict-view-customizations (M35-05).

Wraps registry/predict_view_customization_store.py's get_customization/
create_customization/update_customization for the private/admin HTTP surface
in api/main.py. This module has no public caller; the routes that use it are
gated by api/main.py's existing ADMIN_API_TOKEN convention.

The store module's validate_customization call requires an already-loaded
public contract; this module is responsible for resolving dataset_slug to its
active_release via registry.resolve.resolve_dataset and loading the contract
via api/public_contract_loader.load_public_contract(active_release) before
every create/update -- mirroring the resolve-then-load sequence
GET /datasets/{dataset_slug}/contract already uses in api/main.py, not
api/public_predict_view_customization_loader.py's own call (which passes
dataset_slug directly to load_public_contract's active_release parameter).

On read, a missing customization record is reported as a deterministic
absence signal (customization_exists: false, customization: None) -- never a
synthesized fallback record, and never HTTP 404, which api/main.py reserves
for admin-auth denial. On save, when no record exists yet for the
(view_id, dataset_slug) pair, this module transparently creates one instead
of surfacing the persistence module's create/update distinction to the admin
caller.

Project Spec S0099: the read path also resolves the selected dataset's active
release public contract and classifies any stored customization against it
via registry.predict_view_customization_validate.classify_customization_compatibility,
so the caller (the Dataset Admin Inference Form automatic bootstrap) can build
a contract-driven base draft without an explicit "Load customization" action.
The reduced compatibility_status ("absent" | "compatible" | "incompatible")
never exposes the classifier's own field-level errors for an absent record,
and an incompatible record is never returned as "customization" -- it stays
persisted in the registry unchanged, only its sanitized errors are surfaced.

All three functions propagate ValueError from the persistence module's
view_id/dataset_slug validation unchanged; the calling route is responsible
for translating it into a sanitized HTTP response.
"""

from public_contract_loader import PublicContractUnavailableError, load_public_contract
from registry.predict_view_customization_store import (
    CustomizationNotFoundError,
    create_customization,
    get_customization,
    update_customization,
    validate_identifiers,
)
from registry.predict_view_customization_validate import classify_customization_compatibility
from registry.resolve import (
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

_UPDATE_NOT_FOUND_FOR_UPDATE_CODE = "CUSTOMIZATION_NOT_FOUND_FOR_UPDATE"
_PUBLIC_CONTRACT_UNAVAILABLE_CODE = "PUBLIC_CONTRACT_UNAVAILABLE"


def _resolved_public_contract(dataset_slug: str) -> dict | None:
    """Resolve dataset_slug's active release public contract, or None if it
    cannot be resolved right now. Never raises -- an unresolved contract is a
    legitimate, reportable compatibility outcome, not a caller error."""
    try:
        resolved = resolve_dataset(dataset_slug)
        return load_public_contract(resolved.active_release)
    except (DatasetUnavailableError, ReleaseUnavailableError, RegistryInvalidError, PublicContractUnavailableError):
        return None


def read_predict_view_customization(dataset_slug: str, view_id: str) -> dict:
    """
    Return {"dataset_slug": str, "view_id": str, "customization_exists": bool,
    "compatibility_status": "absent"|"compatible"|"incompatible",
    "customization": dict|None, "errors": [...]}.

    "customization" is populated only when compatibility_status is
    "compatible" -- an "incompatible" stored record is classified but never
    returned as an applicable overlay, and its errors (the classifier's own
    sanitized {code, field, message} entries, or a single
    PUBLIC_CONTRACT_UNAVAILABLE entry when the active release public contract
    itself could not be resolved) are returned instead. An absent record
    returns compatibility_status "absent" with no errors, distinguishing it
    from every incompatible-record outcome.

    Raises ValueError if view_id or dataset_slug is missing or does not match
    the required pattern.
    """
    try:
        customization = get_customization(view_id, dataset_slug)
    except CustomizationNotFoundError:
        return {
            "dataset_slug": dataset_slug,
            "view_id": view_id,
            "customization_exists": False,
            "compatibility_status": "absent",
            "customization": None,
            "errors": [],
        }

    public_contract = _resolved_public_contract(dataset_slug)
    classification = classify_customization_compatibility(
        view_id, dataset_slug, customization, public_contract
    )

    if classification["status"] != "compatible":
        return {
            "dataset_slug": dataset_slug,
            "view_id": view_id,
            "customization_exists": True,
            "compatibility_status": "incompatible",
            "customization": None,
            "errors": classification["errors"],
        }

    return {
        "dataset_slug": dataset_slug,
        "view_id": view_id,
        "customization_exists": True,
        "compatibility_status": "compatible",
        "customization": customization,
        "errors": [],
    }


def save_predict_view_customization(dataset_slug: str, view_id: str, customization: dict) -> dict:
    """
    Persist a predict-view-customization record, creating it transparently if
    none exists yet for this (view_id, dataset_slug).

    Returns {"dataset_slug": str, "view_id": str, "saved": bool,
    "customization": dict|None, "errors": [...]}, where errors is the
    persistence module's own {code, field, message} list, passed through
    unmodified, or a single PUBLIC_CONTRACT_UNAVAILABLE error if the dataset
    cannot be resolved to an active release or the public contract for that
    release cannot be loaded. Raises ValueError if view_id or dataset_slug is
    missing or does not match the required pattern.
    """
    validate_identifiers(view_id, dataset_slug)

    try:
        resolved = resolve_dataset(dataset_slug)
        public_contract = load_public_contract(resolved.active_release)
    except (DatasetUnavailableError, ReleaseUnavailableError, RegistryInvalidError, PublicContractUnavailableError):
        return {
            "dataset_slug": dataset_slug,
            "view_id": view_id,
            "saved": False,
            "customization": None,
            "errors": [{
                "code": _PUBLIC_CONTRACT_UNAVAILABLE_CODE,
                "field": None,
                "message": "The public contract for this dataset is temporarily unavailable.",
            }],
        }

    result = update_customization(view_id, dataset_slug, customization, public_contract)

    update_rejected_for_missing_record = not result["updated"] and any(
        error.get("code") == _UPDATE_NOT_FOUND_FOR_UPDATE_CODE
        for error in result["errors"]
    )
    if update_rejected_for_missing_record:
        result = create_customization(view_id, dataset_slug, customization, public_contract)
        saved = result["created"]
    else:
        saved = result["updated"]

    return {
        "dataset_slug": dataset_slug,
        "view_id": view_id,
        "saved": saved,
        "customization": customization if saved else None,
        "errors": result["errors"],
    }
