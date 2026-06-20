"""
Build pipeline entrypoint for atlas-dataflow (M13-02).

Validates the source contract input before candidate artifact generation begins.
Scope: input validation and rejection only. Does not perform contract derivation,
candidate assembly, publisher calls, or registry mutation.
"""

import json
import sys
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent / "source-contract-input.schema.json"


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

    print(json.dumps(_acceptance(data, input_path), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
