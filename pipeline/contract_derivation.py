"""
Contract derivation pipeline for atlas-dataflow (M13-03).

Validates the runtime contract at source_contract_ref against the runtime contract schema,
then derives a safe public contract artifact by applying projection rules.

Scope: contract validation (runtime) and derivation (public) only. Does not perform
candidate assembly, publisher calls, registry mutation, or public contract editing.

FRESH field defaults are deterministic and reproducible:
- label: feature name with underscores/hyphens replaced by spaces, converted to title case.
- display_order: 1-based positional index of the feature in the runtime features array.
- schema_version (public): fixed constant "1.0.0" (first-cycle versioning assumption).

Feature order in the runtime contract is the authoritative source for display_order.
Study authors must order features intentionally in the runtime contract document.

Pipeline-derived labels are templates for study-author refinement, not production-ready
UI strings.

_RUNTIME_ONLY_KEYS mirrors api/public_contract_loader.py._RUNTIME_ONLY_KEYS.
If that module's constant changes, this constant must be updated to match.
"""

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
RUNTIME_SCHEMA_PATH = REPO_ROOT / "contracts" / "runtime-contract.schema.json"
PUBLIC_SCHEMA_PATH = REPO_ROOT / "contracts" / "public-contract.schema.json"

# Source: api/public_contract_loader.py._RUNTIME_ONLY_KEYS
# Must be kept in sync with that module manually — no automatic synchronization.
_RUNTIME_ONLY_KEYS = frozenset({
    "artifact",
    "artifacts",
    "constraints",
    "domain_constraints",
    "hidden_constraints",
    "implementation",
    "internal",
    "path",
    "reference",
    "release",
    "required",
    "schema",
    "validation",
    "validators",
})

_INPUT_TYPE_MAP = {
    "numeric": "number",
    "categorical": "select",
    "boolean": "checkbox",
}

PUBLIC_CONTRACT_SCHEMA_VERSION = "1.0.0"


def _load_json(path):
    """Load and parse a JSON file. Returns (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except PermissionError:
        return None, f"file not readable: {path}"
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"


def _validate_schema(data, schema):
    """Validate data against schema. Returns list of error messages."""
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        return [e.message for e in errors]
    except ImportError:
        # Fail-safe: reject rather than accept if jsonschema is unavailable.
        required = schema.get("required", [])
        missing = [f for f in required if f not in data]
        if missing:
            return [f"missing required field: '{f}'" for f in missing]
        return ["jsonschema library unavailable — cannot perform full schema validation; rejecting as fail-safe"]


def _fresh_label(name):
    """Deterministic FRESH label default: replace _ and - with spaces, apply title case."""
    return name.replace("_", " ").replace("-", " ").title()


def _derive_public_feature(feature, display_order):
    """Apply projection rules to a single runtime feature to produce a public feature."""
    public = {}
    # CARRIED: name always; description if present
    public["name"] = feature["name"]
    if "description" in feature:
        public["description"] = feature["description"]
    # DERIVED: input_type from type
    public["input_type"] = _INPUT_TYPE_MAP[feature["type"]]
    # INVERTED: optional = not required (default required=True → optional=False)
    public["optional"] = not feature.get("required", True)
    # FRESH: label from title-cased name
    public["label"] = _fresh_label(feature["name"])
    # FRESH: display_order from 1-based position
    public["display_order"] = display_order
    return public


def _derive_public_contract(runtime_contract):
    """Derive a complete public contract from a validated runtime contract."""
    public_features = [
        _derive_public_feature(feature, i + 1)
        for i, feature in enumerate(runtime_contract["features"])
    ]
    return {
        "schema_version": PUBLIC_CONTRACT_SCHEMA_VERSION,
        "features": public_features,
    }


def _check_safety(public_contract):
    """Verify no _RUNTIME_ONLY_KEYS appear in any public feature object."""
    violations = []
    for i, feature in enumerate(public_contract.get("features", [])):
        leaked = _RUNTIME_ONLY_KEYS & set(feature.keys())
        if leaked:
            violations.append(
                f"feature[{i}] ({feature.get('name', '?')!r}) "
                f"contains runtime-only keys: {sorted(leaked)}"
            )
    return violations


def _rejection(reason, rejection_phase, source_contract_ref, input_path):
    return {
        "status": "rejected",
        "reason": reason,
        "rejection_phase": rejection_phase,
        "source_contract_ref": source_contract_ref,
        "input_path": str(input_path) if input_path else None,
    }


def _acceptance(dataset_slug, release_id, runtime_path, public_path):
    return {
        "status": "accepted",
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "runtime_contract_path": str(runtime_path),
        "public_contract_path": str(public_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate runtime contract and derive public contract artifacts."
    )
    parser.add_argument(
        "source_input_path",
        help="Path to validated source input JSON file (source-contract-input.v1).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where runtime-contract.json and public-contract.json are written.",
    )
    args = parser.parse_args()

    input_path = args.source_input_path
    output_dir = Path(args.output_dir)

    # Step 1: Load source input JSON and extract fields.
    source_input, load_err = _load_json(input_path)
    if load_err:
        print(json.dumps(_rejection(
            f"could not load source input: {load_err}",
            "source_input_read",
            None,
            input_path,
        ), indent=2))
        return 1

    source_contract_ref = source_input.get("source_contract_ref")
    dataset_slug = source_input.get("dataset_slug")
    release_id = source_input.get("release_id")

    # Step 2: Resolve source_contract_ref relative to working directory.
    if not source_contract_ref:
        print(json.dumps(_rejection(
            "source_contract_ref is missing from source input",
            "runtime_contract_read",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    runtime_ref_path = Path(source_contract_ref)
    if not runtime_ref_path.exists() or not runtime_ref_path.is_file():
        print(json.dumps(_rejection(
            f"runtime contract not found at source_contract_ref: {source_contract_ref}",
            "runtime_contract_read",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 3: Parse runtime contract JSON.
    runtime_contract, parse_err = _load_json(str(runtime_ref_path))
    if parse_err:
        print(json.dumps(_rejection(
            f"could not parse runtime contract: {parse_err}",
            "runtime_contract_parse",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 4: Load runtime schema and validate runtime contract against it.
    runtime_schema, schema_load_err = _load_json(str(RUNTIME_SCHEMA_PATH))
    if schema_load_err:
        print(json.dumps(_rejection(
            f"could not load runtime contract schema: {schema_load_err}",
            "runtime_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    runtime_errors = _validate_schema(runtime_contract, runtime_schema)
    if runtime_errors:
        first = runtime_errors[0]
        reason = first if len(runtime_errors) == 1 else f"{len(runtime_errors)} validation errors: {first}"
        print(json.dumps(_rejection(
            f"runtime contract fails schema validation: {reason}",
            "runtime_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 5: Derive public contract from the validated runtime contract.
    public_contract = _derive_public_contract(runtime_contract)

    # Step 6: Load public schema and validate the derived public contract.
    public_schema, pub_schema_err = _load_json(str(PUBLIC_SCHEMA_PATH))
    if pub_schema_err:
        print(json.dumps(_rejection(
            f"could not load public contract schema: {pub_schema_err}",
            "public_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    public_errors = _validate_schema(public_contract, public_schema)
    if public_errors:
        first = public_errors[0]
        reason = first if len(public_errors) == 1 else f"{len(public_errors)} validation errors: {first}"
        print(json.dumps(_rejection(
            f"derived public contract fails schema validation (pipeline bug): {reason}",
            "public_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 7: Safety check — no _RUNTIME_ONLY_KEYS in any derived public feature.
    violations = _check_safety(public_contract)
    if violations:
        print(json.dumps(_rejection(
            f"public contract safety check failed: {'; '.join(violations)}",
            "public_contract_safety",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 8: Assert distinct output paths (always true by construction).
    runtime_out = output_dir / "runtime-contract.json"
    public_out = output_dir / "public-contract.json"
    assert runtime_out != public_out, (
        "pipeline bug: runtime and public contract output paths must be distinct"
    )

    # Step 9: Write validated runtime contract to output directory.
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(runtime_out, "w", encoding="utf-8") as f:
        json.dump(runtime_contract, f, indent=2)

    # Step 10: Write derived public contract to output directory.
    with open(public_out, "w", encoding="utf-8") as f:
        json.dump(public_contract, f, indent=2)

    # Step 11: Emit acceptance result to stdout.
    print(json.dumps(_acceptance(dataset_slug, release_id, runtime_out, public_out), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
