"""
Registry validation for the M3 Published Dataset Registry.

Validates structural and semantic correctness of the file-based registry.
Does not load model bundles, inspect release packages, execute inference,
access a database, or infer state from local directories.
"""

import json
import re
from pathlib import Path

REGISTRY_SCHEMA_VERSION = "atlas.dataflow.registry.v1"
DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Accepts both the historical release-YYYYMMDD-NNN identifier and the
# deterministic release-YYYYMMDDtHHMMSSz identifier that
# pipeline/assemble_candidate.py.derive_deterministic_release_id() derives
# from a governed train-<timestamp>Z training run id (Project Spec S0036).
RELEASE_ID_PATTERN = re.compile(r"^release-(?:[0-9]{8}-[0-9]{3}|[0-9]{8}t[0-9]{6}z)$")

_SAFE_METADATA_FIELDS = {"title", "summary", "domain", "visibility", "tags"}
_REQUIRED_METADATA_FIELDS = ("title", "summary", "domain", "visibility", "tags")


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def validate_registry(registry: dict) -> dict:
    """
    Validate a registry dict.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    Errors are deterministic and sanitized: no filesystem paths, secrets, or
    internal operational details are included in any error message.
    """
    errors = []

    if not isinstance(registry, dict):
        errors.append(_err("REGISTRY_NOT_AN_OBJECT", None, "Registry must be a JSON object."))
        return {"valid": False, "errors": errors}

    schema_version = registry.get("schema_version")
    if schema_version is None:
        errors.append(_err(
            "MISSING_SCHEMA_VERSION",
            "schema_version",
            "Registry is missing required field 'schema_version'.",
        ))
    elif schema_version != REGISTRY_SCHEMA_VERSION:
        errors.append(_err(
            "INVALID_SCHEMA_VERSION",
            "schema_version",
            f"'schema_version' must be '{REGISTRY_SCHEMA_VERSION}'.",
        ))

    datasets = registry.get("datasets")
    if datasets is None:
        errors.append(_err(
            "MISSING_DATASETS",
            "datasets",
            "Registry is missing required field 'datasets'.",
        ))
    elif not isinstance(datasets, list):
        errors.append(_err(
            "INVALID_DATASETS_TYPE",
            "datasets",
            "'datasets' must be an array.",
        ))
    else:
        seen_slugs: set[str] = set()
        for i, entry in enumerate(datasets):
            prefix = f"datasets[{i}]"

            if not isinstance(entry, dict):
                errors.append(_err(
                    "INVALID_DATASET_ENTRY",
                    prefix,
                    f"Dataset entry at index {i} must be an object.",
                ))
                continue

            slug = entry.get("dataset_slug")
            if slug is None:
                errors.append(_err(
                    "MISSING_DATASET_SLUG",
                    f"{prefix}.dataset_slug",
                    f"Dataset entry at index {i} is missing required field 'dataset_slug'.",
                ))
            elif not isinstance(slug, str) or not DATASET_SLUG_PATTERN.match(slug):
                errors.append(_err(
                    "INVALID_DATASET_SLUG_FORMAT",
                    f"{prefix}.dataset_slug",
                    f"Dataset entry at index {i} has an invalid 'dataset_slug' format.",
                ))
            elif slug in seen_slugs:
                errors.append(_err(
                    "DUPLICATE_DATASET_SLUG",
                    f"{prefix}.dataset_slug",
                    f"Dataset entry at index {i} contains a duplicate 'dataset_slug' value.",
                ))
            else:
                seen_slugs.add(slug)

            active_release = entry.get("active_release")
            if active_release is None:
                errors.append(_err(
                    "MISSING_ACTIVE_RELEASE",
                    f"{prefix}.active_release",
                    f"Dataset entry at index {i} is missing required field 'active_release'.",
                ))
            elif not isinstance(active_release, str) or not RELEASE_ID_PATTERN.match(active_release):
                errors.append(_err(
                    "INVALID_ACTIVE_RELEASE_FORMAT",
                    f"{prefix}.active_release",
                    f"Dataset entry at index {i} 'active_release' must match the format "
                    "release-YYYYMMDD-NNN or release-YYYYMMDDtHHMMSSz.",
                ))

            metadata = entry.get("public_metadata")
            if metadata is None:
                errors.append(_err(
                    "MISSING_PUBLIC_METADATA",
                    f"{prefix}.public_metadata",
                    f"Dataset entry at index {i} is missing required field 'public_metadata'.",
                ))
            elif not isinstance(metadata, dict):
                errors.append(_err(
                    "INVALID_PUBLIC_METADATA_TYPE",
                    f"{prefix}.public_metadata",
                    f"Dataset entry at index {i} 'public_metadata' must be an object.",
                ))
            else:
                for field in _REQUIRED_METADATA_FIELDS:
                    if field not in metadata:
                        errors.append(_err(
                            "MISSING_METADATA_FIELD",
                            f"{prefix}.public_metadata.{field}",
                            f"Dataset entry at index {i} public_metadata is missing required field '{field}'.",
                        ))

                visibility = metadata.get("visibility")
                if visibility is not None and visibility != "public":
                    errors.append(_err(
                        "INVALID_METADATA_VISIBILITY",
                        f"{prefix}.public_metadata.visibility",
                        f"Dataset entry at index {i} public_metadata 'visibility' must be 'public'.",
                    ))

                extra_keys = set(metadata.keys()) - _SAFE_METADATA_FIELDS
                if extra_keys:
                    errors.append(_err(
                        "UNSAFE_METADATA_FIELDS",
                        f"{prefix}.public_metadata",
                        (
                            f"Dataset entry at index {i} public_metadata contains fields that are "
                            "not part of the safe public field set."
                        ),
                    ))

    return {"valid": len(errors) == 0, "errors": errors}


def _validate_context_files(registry: dict, contracts_root: Path) -> dict:
    """
    Check per-dataset context files using the canonical path convention
    contracts/<dataset_slug>/dataset-context.json.

    Absent context → non-blocking warning (valid=true is preserved).
    Present but unparseable or schema-invalid context → hard error.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    try:
        import jsonschema as _jss
    except ImportError:
        _jss = None

    context_schema_path = contracts_root / "contracts" / "dataset-context.schema.json"
    try:
        context_schema = json.loads(context_schema_path.read_text(encoding="utf-8"))
    except OSError:
        errors.append(_err(
            "CONTEXT_SCHEMA_UNREADABLE",
            None,
            "Context schema file could not be read.",
        ))
        return {"errors": errors, "warnings": warnings}
    except json.JSONDecodeError:
        errors.append(_err(
            "CONTEXT_SCHEMA_INVALID_JSON",
            None,
            "Context schema file is not valid JSON.",
        ))
        return {"errors": errors, "warnings": warnings}

    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        return {"errors": errors, "warnings": warnings}

    for i, entry in enumerate(datasets):
        if not isinstance(entry, dict):
            continue
        slug = entry.get("dataset_slug")
        if not isinstance(slug, str) or not DATASET_SLUG_PATTERN.match(slug):
            continue

        context_path = contracts_root / "contracts" / slug / "dataset-context.json"
        field = f"datasets[{i}].dataset_slug"

        if not context_path.exists():
            warnings.append({
                "code": "CONTEXT_FILE_ABSENT",
                "field": field,
                "message": (
                    f"Dataset '{slug}' has no context file at the canonical path. "
                    "Context is optional and its absence does not affect registry validity."
                ),
            })
            continue

        try:
            context_text = context_path.read_text(encoding="utf-8")
        except OSError:
            errors.append(_err(
                "CONTEXT_FILE_UNREADABLE",
                field,
                f"Context file for dataset '{slug}' could not be read.",
            ))
            continue

        try:
            context_data = json.loads(context_text)
        except json.JSONDecodeError:
            errors.append(_err(
                "CONTEXT_FILE_INVALID_JSON",
                field,
                f"Context file for dataset '{slug}' is not valid JSON.",
            ))
            continue

        if _jss is not None:
            try:
                _jss.validate(context_data, context_schema)
            except _jss.ValidationError as exc:
                errors.append(_err(
                    "CONTEXT_FILE_SCHEMA_INVALID",
                    field,
                    f"Context file for dataset '{slug}' failed schema validation: {exc.message}",
                ))
        else:
            for required_field in ("schema_version", "dataset_slug", "title", "description", "domain"):
                if required_field not in context_data:
                    errors.append(_err(
                        "CONTEXT_FILE_SCHEMA_INVALID",
                        f"{field}.{required_field}",
                        f"Context file for dataset '{slug}' is missing required field '{required_field}'.",
                    ))

    return {"errors": errors, "warnings": warnings}


def validate_registry_file(registry_path: Path, contracts_root: Path | None = None) -> dict:
    """Load a registry JSON file and validate it.

    When *contracts_root* is provided, also validate per-dataset context files
    at the canonical path contracts/<dataset_slug>/dataset-context.json.
    Absent context files produce a non-blocking warning; present but invalid
    files produce a hard error.
    """
    try:
        content = registry_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "valid": False,
            "errors": [_err("REGISTRY_FILE_UNREADABLE", None, "Registry file could not be read.")],
            "warnings": [],
        }

    try:
        registry = json.loads(content)
    except json.JSONDecodeError:
        return {
            "valid": False,
            "errors": [_err("REGISTRY_INVALID_JSON", None, "Registry file is not valid JSON.")],
            "warnings": [],
        }

    result = validate_registry(registry)
    result.setdefault("warnings", [])

    if contracts_root is not None:
        context_result = _validate_context_files(registry, contracts_root)
        result["warnings"].extend(context_result["warnings"])
        result["errors"].extend(context_result["errors"])
        if context_result["errors"]:
            result["valid"] = False

    return result
