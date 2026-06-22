"""
Predict view customization loader for M19-03.

Loads and returns a validated predict view customization record from the
authoritative registry (registry/predict-view-customizations.json) for a
given dataset slug and view identifier. The record is validated through the
M19-02 validator before being returned; invalid records are treated as absent.
"""

import json
import logging
from pathlib import Path

from public_contract_loader import load_public_contract, PublicContractUnavailableError

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_PREDICT_VIEW_CUSTOMIZATIONS_PATH = (
    _REPO_ROOT / "registry" / "predict-view-customizations.json"
)

logger = logging.getLogger(__name__)


class CustomizationNotFoundError(Exception):
    """No validated customization record exists for the given view_id and dataset_slug."""

    code = "CUSTOMIZATION_NOT_FOUND"


def load_public_predict_view_customization(
    dataset_slug: str,
    view_id: str,
    customizations_path: Path | None = None,
) -> dict:
    """
    Load a validated predict view customization record.

    Resolution steps:
    1. Read registry/predict-view-customizations.json.
    2. Find the record where view_id and dataset_slug both match.
    3. Load the public contract for dataset_slug via load_public_contract.
    4. Call validate_customization(record, public_contract) from the M19-02 validator.
    5. If validation fails, treat the record as absent (raise CustomizationNotFoundError).
    6. Return the matching record.

    Raises CustomizationNotFoundError if no matching record exists, if the registry
    is unavailable, or if the matched record fails validation.
    """
    from registry.predict_view_customization_validate import validate_customization  # noqa: PLC0415

    path = (
        customizations_path
        if customizations_path is not None
        else _DEFAULT_PREDICT_VIEW_CUSTOMIZATIONS_PATH
    )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise CustomizationNotFoundError(
            "Predict view customization registry is not available."
        )

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        raise CustomizationNotFoundError(
            "Predict view customization registry is not available."
        )

    entries = registry.get("predict_view_customizations")
    if not isinstance(entries, list):
        raise CustomizationNotFoundError(
            "Predict view customization registry is not available."
        )

    matched = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("view_id") == view_id and entry.get("dataset_slug") == dataset_slug:
            matched = entry
            break

    if matched is None:
        raise CustomizationNotFoundError(
            "No customization record exists for this predict view."
        )

    try:
        public_contract = load_public_contract(dataset_slug)
    except PublicContractUnavailableError:
        logger.warning(
            "Public contract unavailable for dataset_slug=%r; treating customization as absent.",
            dataset_slug,
        )
        raise CustomizationNotFoundError(
            "Customization record cannot be validated: public contract unavailable."
        )

    validation_result = validate_customization(matched, public_contract)
    if not validation_result.get("valid"):
        logger.warning(
            "Customization record for view_id=%r dataset_slug=%r failed validation: %r",
            view_id,
            dataset_slug,
            validation_result.get("errors"),
        )
        raise CustomizationNotFoundError("Customization record is invalid.")

    return matched
