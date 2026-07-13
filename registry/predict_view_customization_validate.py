"""
Predict view customization metadata validator for M19-02.

Validates customization metadata against a loaded public contract projection.
The public contract is injected by the caller; this module does not import
from api/ or load the public contract internally.

Validates:
  - All field_hints[].field_name values reference a feature in the public contract.
  - No field_name appears more than once in field_hints.
  - No group_id appears more than once in the groups array.
  - All field_hints[].group values reference a group_id defined in groups.
  - Required fields (optional: false in the public contract) assigned to
    non-existent groups produce a REQUIRED_FIELD_HIDDEN rejection.
  - contract_precedence declares the correct boundary values.

Validation is deterministic: identical inputs always produce identical output.
Error messages are sanitized: field path and error code only — no filesystem
paths, release IDs, feature counts, or raw contract data.
"""

import json
from pathlib import Path


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def validate_customization(customization: dict, public_contract: dict) -> dict:
    """
    Validate a customization metadata dict against a public contract dict.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    Accumulates all errors before returning — does not short-circuit on the first error.

    public_contract must contain a "features" list; each feature must have a
    "name" (str) field. Features with "optional": False are required fields.
    The caller is responsible for loading public_contract via
    api/public_contract_loader.load_public_contract(active_release) before
    invoking this function.
    """
    errors: list[dict] = []

    if not isinstance(customization, dict):
        errors.append(_err(
            "CUSTOMIZATION_NOT_AN_OBJECT",
            None,
            "Customization must be a JSON object.",
        ))
        return {"valid": False, "errors": errors}

    features = public_contract.get("features") if isinstance(public_contract, dict) else []
    if not isinstance(features, list):
        features = []
    known_field_names: set[str] = set()
    required_field_names: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        name = feature.get("name")
        if isinstance(name, str) and name:
            known_field_names.add(name)
            if feature.get("optional") is False:
                required_field_names.add(name)

    field_hints = customization.get("field_hints")
    groups = customization.get("groups")
    contract_precedence = customization.get("contract_precedence")

    # groups: duplicate group_id check
    known_group_ids: set[str] = set()
    if isinstance(groups, list):
        for i, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            gid = group.get("group_id")
            if not isinstance(gid, str) or not gid:
                continue
            if gid in known_group_ids:
                errors.append(_err(
                    "DUPLICATE_GROUP_ID",
                    f"groups[{i}].group_id",
                    f"groups[{i}].group_id is a duplicate; each group_id must be unique.",
                ))
            else:
                known_group_ids.add(gid)

    # field_hints: unknown reference, duplicate, and broken group ref checks
    if isinstance(field_hints, list):
        seen_field_names: set[str] = set()
        for i, hint in enumerate(field_hints):
            if not isinstance(hint, dict):
                continue

            field_name = hint.get("field_name")
            if not isinstance(field_name, str) or not field_name:
                continue

            if field_name not in known_field_names:
                errors.append(_err(
                    "UNKNOWN_FIELD_REFERENCE",
                    f"field_hints[{i}].field_name",
                    f"field_hints[{i}].field_name references a field not present in the public contract.",
                ))

            if field_name in seen_field_names:
                errors.append(_err(
                    "DUPLICATE_FIELD_REFERENCE",
                    f"field_hints[{i}].field_name",
                    f"field_hints[{i}].field_name appears more than once in field_hints.",
                ))
            else:
                seen_field_names.add(field_name)

            group_ref = hint.get("group")
            if isinstance(group_ref, str) and group_ref:
                if group_ref not in known_group_ids:
                    if field_name in required_field_names:
                        errors.append(_err(
                            "REQUIRED_FIELD_HIDDEN",
                            f"field_hints[{i}].group",
                            f"field_hints[{i}].group references an undefined group_id, hiding a required field.",
                        ))
                    else:
                        errors.append(_err(
                            "BROKEN_GROUP_REFERENCE",
                            f"field_hints[{i}].group",
                            f"field_hints[{i}].group references a group_id not defined in groups.",
                        ))

            if hint.get("hidden") is True:
                if field_name in required_field_names:
                    errors.append(_err(
                        "REQUIRED_FIELD_HIDDEN",
                        f"field_hints[{i}].hidden",
                        f"field_hints[{i}].hidden is true for required field {field_name!r}; required fields cannot be hidden.",
                    ))

    # contract_precedence semantic check
    if contract_precedence is not None:
        if not isinstance(contract_precedence, dict):
            errors.append(_err(
                "INVALID_CONTRACT_PRECEDENCE_TYPE",
                "contract_precedence",
                "'contract_precedence' must be an object.",
            ))
        else:
            if contract_precedence.get("canonical_contracts_are_source_of_truth") is not True:
                errors.append(_err(
                    "CONTRACT_PRECEDENCE_VIOLATION",
                    "contract_precedence.canonical_contracts_are_source_of_truth",
                    "'contract_precedence.canonical_contracts_are_source_of_truth' must be true.",
                ))
            if contract_precedence.get("customization_defines_runtime_validation") is not False:
                errors.append(_err(
                    "CONTRACT_PRECEDENCE_VIOLATION",
                    "contract_precedence.customization_defines_runtime_validation",
                    "'contract_precedence.customization_defines_runtime_validation' must be false.",
                ))
            if contract_precedence.get("customization_duplicates_contract") is not False:
                errors.append(_err(
                    "CONTRACT_PRECEDENCE_VIOLATION",
                    "contract_precedence.customization_duplicates_contract",
                    "'contract_precedence.customization_duplicates_contract' must be false.",
                ))

    return {"valid": len(errors) == 0, "errors": errors}


def classify_customization_compatibility(
    view_id: str,
    dataset_slug: str,
    customization: dict,
    public_contract: dict | None,
) -> dict:
    """
    Classify one stored predict-view customization record's compatibility
    with a materialized predict view and the current active release public
    contract (Project Spec S0098).

    Returns {"status": "compatible" | "incompatible", "errors": [...]}.
    "compatible" only when the customization's own view_id and dataset_slug
    match the materialized view exactly, public_contract was resolvable,
    and validate_customization() reports no errors against it. Any identity
    mismatch, an unresolved public_contract (None -- the caller could not
    load the current active release's public contract), or a
    validate_customization() failure is classified "incompatible" instead.

    This function only classifies -- an "incompatible" result never causes
    the stored customization to be deleted, have its fields renamed, or be
    migrated; the caller is responsible for preserving it unchanged and
    simply not describing it as valid current customization.
    """
    errors: list[dict] = []

    if not isinstance(customization, dict):
        errors.append(_err(
            "CUSTOMIZATION_NOT_AN_OBJECT",
            None,
            "Customization must be a JSON object.",
        ))
        return {"status": "incompatible", "errors": errors}

    if customization.get("view_id") != view_id:
        errors.append(_err(
            "CUSTOMIZATION_VIEW_ID_MISMATCH",
            "view_id",
            "Customization view_id does not match the materialized predict view.",
        ))

    if customization.get("dataset_slug") != dataset_slug:
        errors.append(_err(
            "CUSTOMIZATION_DATASET_SLUG_MISMATCH",
            "dataset_slug",
            "Customization dataset_slug does not match the materialized predict view's dataset.",
        ))

    if public_contract is None:
        errors.append(_err(
            "PUBLIC_CONTRACT_UNAVAILABLE",
            None,
            "The current active release public contract could not be resolved for compatibility validation.",
        ))
    else:
        contract_result = validate_customization(customization, public_contract)
        errors.extend(contract_result["errors"])

    return {"status": "incompatible" if errors else "compatible", "errors": errors}


def validate_customization_file(
    customization_path: Path,
    public_contract: dict,
) -> dict:
    """
    Load a customization JSON file and validate it against public_contract.

    Convenience wrapper around validate_customization for file-based callers.
    """
    try:
        content = customization_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "valid": False,
            "errors": [_err(
                "CUSTOMIZATION_FILE_UNREADABLE",
                None,
                "Customization file could not be read.",
            )],
        }

    try:
        customization = json.loads(content)
    except json.JSONDecodeError:
        return {
            "valid": False,
            "errors": [_err(
                "CUSTOMIZATION_INVALID_JSON",
                None,
                "Customization file is not valid JSON.",
            )],
        }

    return validate_customization(customization, public_contract)
