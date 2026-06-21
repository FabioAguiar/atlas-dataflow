"""
Predict view registry binding validator for M18-02.

Validates that each predict view record in registry/predict-views.json:
  - Has the required structure fields (view_id, dataset_slug, display, intent,
    binding, contract_precedence).
  - Binds to a dataset_slug that exists in the canonical dataset registry.
  - Uses valid release binding: active mode carries no release_id; compatible mode
    requires a valid release_id matching release-YYYYMMDD-NNN.
  - Does not contain prohibited fields that would override canonical contract semantics.
  - Declares correct contract_precedence values (canonical contracts are source of truth).

Does not execute inference, load model bundles, access a database, or duplicate
canonical dataset contract validation semantics.
"""

import json
import re
from pathlib import Path

PREDICT_VIEWS_SCHEMA_VERSION = "atlas.dataflow.predict-views.v1"
RELEASE_ID_PATTERN = re.compile(r"^release-[0-9]{8}-[0-9]{3}$")

PREDICT_VIEWS_PATH = Path(__file__).parent / "predict-views.json"
_DEFAULT_DATASETS_PATH = Path(__file__).parent / "datasets.json"

_PROHIBITED_FIELDS = frozenset({
    "features",
    "validation_rules",
    "input_semantics",
    "domain_constraints",
    "business_logic",
    "runtime_contract",
    "public_contract",
})

_REQUIRED_VIEW_FIELDS = (
    "view_id",
    "dataset_slug",
    "display",
    "intent",
    "binding",
    "contract_precedence",
)


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _load_known_dataset_slugs(datasets_path: Path) -> set[str] | None:
    """
    Read the canonical dataset registry and return the set of known dataset slugs.
    Returns None if the file cannot be read or is not valid JSON.
    """
    try:
        content = datasets_path.read_text(encoding="utf-8")
        registry = json.loads(content)
    except (OSError, json.JSONDecodeError):
        return None
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        return None
    slugs: set[str] = set()
    for entry in datasets:
        if isinstance(entry, dict):
            slug = entry.get("dataset_slug")
            if isinstance(slug, str) and slug:
                slugs.add(slug)
    return slugs


def validate_predict_views(
    predict_views_registry: dict,
    known_dataset_slugs: set[str] | None = None,
) -> dict:
    """
    Validate a predict views registry dict.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    Errors are deterministic and sanitized: no filesystem paths, secrets, or
    internal operational details are included in any error message.

    When known_dataset_slugs is None, dataset existence checks are skipped.
    """
    errors: list[dict] = []

    if not isinstance(predict_views_registry, dict):
        errors.append(_err(
            "REGISTRY_NOT_AN_OBJECT",
            None,
            "Predict views registry must be a JSON object.",
        ))
        return {"valid": False, "errors": errors}

    schema_version = predict_views_registry.get("schema_version")
    if schema_version is None:
        errors.append(_err(
            "MISSING_SCHEMA_VERSION",
            "schema_version",
            "Predict views registry is missing required field 'schema_version'.",
        ))
    elif schema_version != PREDICT_VIEWS_SCHEMA_VERSION:
        errors.append(_err(
            "INVALID_SCHEMA_VERSION",
            "schema_version",
            f"'schema_version' must be '{PREDICT_VIEWS_SCHEMA_VERSION}'.",
        ))

    predict_views = predict_views_registry.get("predict_views")
    if predict_views is None:
        errors.append(_err(
            "MISSING_PREDICT_VIEWS",
            "predict_views",
            "Predict views registry is missing required field 'predict_views'.",
        ))
        return {"valid": len(errors) == 0, "errors": errors}

    if not isinstance(predict_views, list):
        errors.append(_err(
            "INVALID_PREDICT_VIEWS_TYPE",
            "predict_views",
            "'predict_views' must be an array.",
        ))
        return {"valid": len(errors) == 0, "errors": errors}

    seen_view_ids: set[str] = set()

    for i, record in enumerate(predict_views):
        prefix = f"predict_views[{i}]"

        if not isinstance(record, dict):
            errors.append(_err(
                "INVALID_VIEW_RECORD",
                prefix,
                f"Predict view record at index {i} must be an object.",
            ))
            continue

        found_prohibited = _PROHIBITED_FIELDS & record.keys()
        if found_prohibited:
            errors.append(_err(
                "CONTRACT_BINDING_INVALID",
                prefix,
                (
                    f"Predict view record at index {i} contains fields that override "
                    "canonical contract semantics and are not permitted."
                ),
            ))

        for field in _REQUIRED_VIEW_FIELDS:
            if field not in record:
                errors.append(_err(
                    "MISSING_REQUIRED_FIELD",
                    f"{prefix}.{field}",
                    f"Predict view record at index {i} is missing required field '{field}'.",
                ))

        view_id = record.get("view_id")
        if isinstance(view_id, str) and view_id:
            if view_id in seen_view_ids:
                errors.append(_err(
                    "DUPLICATE_VIEW_ID",
                    f"{prefix}.view_id",
                    f"Predict view record at index {i} contains a duplicate 'view_id' value.",
                ))
            else:
                seen_view_ids.add(view_id)

        dataset_slug = record.get("dataset_slug")
        if isinstance(dataset_slug, str) and dataset_slug:
            if known_dataset_slugs is not None and dataset_slug not in known_dataset_slugs:
                errors.append(_err(
                    "DATASET_NOT_FOUND",
                    f"{prefix}.dataset_slug",
                    f"Predict view record at index {i} references a dataset that is not registered.",
                ))

        binding = record.get("binding")
        if binding is not None:
            if not isinstance(binding, dict):
                errors.append(_err(
                    "INVALID_BINDING_TYPE",
                    f"{prefix}.binding",
                    f"Predict view record at index {i} 'binding' must be an object.",
                ))
            else:
                binding_slug = binding.get("dataset_slug")
                if isinstance(binding_slug, str) and isinstance(dataset_slug, str):
                    if binding_slug != dataset_slug:
                        errors.append(_err(
                            "BINDING_DATASET_MISMATCH",
                            f"{prefix}.binding.dataset_slug",
                            (
                                f"Predict view record at index {i} 'binding.dataset_slug' "
                                "must match the record's top-level 'dataset_slug'."
                            ),
                        ))

                release = binding.get("release")
                if release is None:
                    errors.append(_err(
                        "MISSING_RELEASE_BINDING",
                        f"{prefix}.binding.release",
                        (
                            f"Predict view record at index {i} 'binding' is missing "
                            "required field 'release'."
                        ),
                    ))
                elif not isinstance(release, dict):
                    errors.append(_err(
                        "INVALID_RELEASE_BINDING_TYPE",
                        f"{prefix}.binding.release",
                        f"Predict view record at index {i} 'binding.release' must be an object.",
                    ))
                else:
                    mode = release.get("mode")
                    if mode not in ("active", "compatible"):
                        errors.append(_err(
                            "INVALID_RELEASE_MODE",
                            f"{prefix}.binding.release.mode",
                            (
                                f"Predict view record at index {i} 'binding.release.mode' "
                                "must be 'active' or 'compatible'."
                            ),
                        ))
                    elif mode == "compatible":
                        release_id = release.get("release_id")
                        if release_id is None:
                            errors.append(_err(
                                "RELEASE_REFERENCE_INVALID",
                                f"{prefix}.binding.release.release_id",
                                (
                                    f"Predict view record at index {i} uses compatible mode but "
                                    "is missing required field 'binding.release.release_id'."
                                ),
                            ))
                        elif not isinstance(release_id, str) or not RELEASE_ID_PATTERN.match(release_id):
                            errors.append(_err(
                                "RELEASE_REFERENCE_INVALID",
                                f"{prefix}.binding.release.release_id",
                                (
                                    f"Predict view record at index {i} "
                                    "'binding.release.release_id' must match the format "
                                    "release-YYYYMMDD-NNN."
                                ),
                            ))
                    elif mode == "active" and "release_id" in release:
                        errors.append(_err(
                            "RELEASE_REFERENCE_INVALID",
                            f"{prefix}.binding.release.release_id",
                            (
                                f"Predict view record at index {i} uses active mode but "
                                "must not carry a 'binding.release.release_id' field."
                            ),
                        ))

        cp = record.get("contract_precedence")
        if cp is not None:
            if not isinstance(cp, dict):
                errors.append(_err(
                    "INVALID_CONTRACT_PRECEDENCE_TYPE",
                    f"{prefix}.contract_precedence",
                    f"Predict view record at index {i} 'contract_precedence' must be an object.",
                ))
            else:
                if cp.get("canonical_contracts_are_source_of_truth") is not True:
                    errors.append(_err(
                        "CONTRACT_PRECEDENCE_VIOLATION",
                        f"{prefix}.contract_precedence.canonical_contracts_are_source_of_truth",
                        (
                            f"Predict view record at index {i} must declare "
                            "'contract_precedence.canonical_contracts_are_source_of_truth' "
                            "as true."
                        ),
                    ))
                if cp.get("view_metadata_defines_runtime_validation") is not False:
                    errors.append(_err(
                        "CONTRACT_PRECEDENCE_VIOLATION",
                        f"{prefix}.contract_precedence.view_metadata_defines_runtime_validation",
                        (
                            f"Predict view record at index {i} must declare "
                            "'contract_precedence.view_metadata_defines_runtime_validation' "
                            "as false."
                        ),
                    ))
                if cp.get("view_metadata_duplicates_contract") is not False:
                    errors.append(_err(
                        "CONTRACT_PRECEDENCE_VIOLATION",
                        f"{prefix}.contract_precedence.view_metadata_duplicates_contract",
                        (
                            f"Predict view record at index {i} must declare "
                            "'contract_precedence.view_metadata_duplicates_contract' as false."
                        ),
                    ))

    return {"valid": len(errors) == 0, "errors": errors}


def validate_predict_views_file(
    predict_views_path: Path,
    datasets_path: Path | None = None,
) -> dict:
    """
    Load a predict views registry JSON file and validate it.

    When datasets_path is None, the default registry/datasets.json is used for
    dataset existence checks.
    """
    effective_datasets_path = (
        datasets_path if datasets_path is not None else _DEFAULT_DATASETS_PATH
    )

    try:
        content = predict_views_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "valid": False,
            "errors": [_err(
                "PREDICT_VIEWS_FILE_UNREADABLE",
                None,
                "Predict views registry file could not be read.",
            )],
        }

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        return {
            "valid": False,
            "errors": [_err(
                "PREDICT_VIEWS_INVALID_JSON",
                None,
                "Predict views registry file is not valid JSON.",
            )],
        }

    known_slugs = _load_known_dataset_slugs(effective_datasets_path)
    return validate_predict_views(registry, known_dataset_slugs=known_slugs)
