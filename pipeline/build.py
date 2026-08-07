"""
Build pipeline entrypoint for atlas-dataflow (M13-02).

Validates the source contract input before candidate artifact generation begins.
Scope: input validation, capability-aware source-boundary resolution, and
generic contract-derivation invocation only. Does not execute notebooks, load
or deserialize a model, train or select a model, assemble a release
candidate, invoke publisher behavior, or mutate registry state.

Project Spec S0167: when a validated source-contract-input instance carries
the additive capability-aware fields (authoring_manifest_ref plus
capability_profile_id/version/ref -- see
pipeline/source-contract-input.schema.json), this entrypoint resolves those
repository-local governed artifacts and invokes
pipeline.contract_derivation.project_capability_aware_source_contract, which
reuses the Project Spec S0166 authoring boundary
(pipeline.authoring_contracts.validate_authoring_contracts) and fails closed
for a capability profile that is not currently, operationally supported.
An instance using only the original v1 fields is unaffected: it is
schema-validated exactly as before and never reaches capability resolution.
"""

import json
import sys
from pathlib import Path

from pipeline.contract_derivation import project_capability_aware_source_contract


SCHEMA_PATH = Path(__file__).parent / "source-contract-input.schema.json"
REPO_ROOT = Path(__file__).parent.parent


def _load_json(path: str) -> tuple:
    """Load and parse a JSON file. Returns (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"


def _validate(data: dict, schema: dict) -> list:
    """Validate data against schema. Returns list of error messages."""
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        return [e.message for e in errors]
    except ImportError:
        required = schema.get("required", [])
        missing = [f for f in required if f not in data]
        return [f"missing required field: '{f}'" for f in missing]


def _rejection(reason: str, input_path: str, missing: list, invalid: list) -> dict:
    return {
        "status": "rejected",
        "reason": reason,
        "missing_fields": missing,
        "invalid_fields": invalid,
        "input_path": input_path,
    }


def _acceptance(data: dict, input_path: str) -> dict:
    return {
        "status": "accepted",
        "dataset_slug": data.get("dataset_slug"),
        "release_id": data.get("release_id"),
        "input_path": input_path,
    }


def _is_capability_aware(data: dict) -> bool:
    """True when the already schema-valid source input carries the
    additive capability-aware fields (Project Spec S0167). The schema's own
    `dependentRequired` guarantees authoring_manifest_ref,
    authoring_generation_id, capability_profile_id, capability_profile_version,
    and capability_profile_ref are present together or entirely absent
    once schema validation has already passed, so checking for one is
    sufficient here."""
    return "authoring_manifest_ref" in data


def _capability_rejection(result, input_path: str) -> dict:
    return {
        "status": "rejected",
        "reason": result.rejection_reason,
        "rejection_phase": result.rejection_phase,
        "dataset_slug": result.dataset_slug,
        "capability_profile_id": result.capability_profile_id,
        "capability_profile_version": result.capability_profile_version,
        "capability_support_status": result.capability_support_status,
        "input_path": input_path,
    }


def _capability_acceptance(result, input_path: str) -> dict:
    return {
        "status": "accepted",
        "dataset_slug": result.dataset_slug,
        "capability_profile_id": result.capability_profile_id,
        "capability_profile_version": result.capability_profile_version,
        "capability_support_status": result.capability_support_status,
        "input_path": input_path,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps(_rejection(
            "usage: python pipeline/build.py <source-input-json-path>",
            None, [], [],
        ), indent=2))
        return 1

    input_path = sys.argv[1]

    schema, schema_err = _load_json(str(SCHEMA_PATH))
    if schema_err:
        print(json.dumps(_rejection(
            f"build schema unavailable: {schema_err}", input_path, [], [],
        ), indent=2))
        return 1

    data, load_err = _load_json(input_path)
    if load_err:
        print(json.dumps(_rejection(load_err, input_path, [], []), indent=2))
        return 1

    errors = _validate(data, schema)
    if errors:
        required_fields = schema.get("required", [])
        missing = [f for f in required_fields if f not in data]
        invalid = [
            f for f in required_fields
            if f in data and any(f in e for e in errors)
        ]
        reason = errors[0] if len(errors) == 1 else f"{len(errors)} validation errors"
        print(json.dumps(_rejection(reason, input_path, missing, invalid), indent=2))
        return 1

    if _is_capability_aware(data):
        result = project_capability_aware_source_contract(data, repo_root=REPO_ROOT)
        if result.status != "accepted":
            print(json.dumps(_capability_rejection(result, input_path), indent=2))
            return 1
        print(json.dumps(_capability_acceptance(result, input_path), indent=2))
        return 0

    print(json.dumps(_acceptance(data, input_path), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
