"""
Execution-to-runtime-to-public contract projection pipeline for atlas-dataflow M23-04.

Takes a promoted execution contract (execution_contract.v1) as input and
deterministically produces two contract projections:
  - runtime-contract.json: inference-ready feature list, types, domain constraints
  - public-contract.json: safe field list, interface hints, labels

Runtime projection rules (execution → runtime):
  CARRIED:          name (from feature_columns order), type (from feature_definitions[name].type),
                    domain_constraints (verbatim, only if present in feature_definitions[name])
  OPTIONAL-CARRIED: description (from feature_definitions[name].description, only if key present)
  DERIVED:          required — True if name in required_columns; False if name in optional_columns;
                    True (default) if name in neither list
  FRESH:            schema_version = RUNTIME_CONTRACT_SCHEMA_VERSION = '1.0.0'
  EXCLUDED:         names in ignored_columns do not appear in feature_columns (schema contract);
                    all execution-only top-level fields are absent from the runtime contract

Public projection (runtime → public) is delegated entirely to
pipeline/contract_derivation.py: _derive_public_contract() and _check_safety().
These symbols must not be redeclared here (constraint-05).

RUNTIME_CONTRACT_SCHEMA_VERSION is parallel to PUBLIC_CONTRACT_SCHEMA_VERSION in
pipeline/contract_derivation.py, both fixed to '1.0.0' (decision-03, first-cycle
versioning assumption consistent with contracts/bank-marketing/runtime-contract.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    print("ERROR: jsonschema is required. Install with: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

from pipeline.contract_derivation import (
    PUBLIC_CONTRACT_SCHEMA_VERSION,  # noqa: F401 — imported for completeness; used by tests
    _INPUT_TYPE_MAP,  # noqa: F401 — re-exported for downstream consumers
    _RUNTIME_ONLY_KEYS,  # noqa: F401 — re-exported for downstream consumers
    _check_safety,
    _derive_public_contract,
    _fresh_label,  # noqa: F401 — re-exported for downstream consumers
    unresolved_select_features,
)

RUNTIME_CONTRACT_SCHEMA_VERSION = "1.0.0"
PROJECTION_EVIDENCE_SCHEMA_VERSION = "1.0.0"


class DerivationFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(errors))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DerivationFailed([f"file not found: {path}"])
    except json.JSONDecodeError as exc:
        raise DerivationFailed([f"invalid JSON in {path}: {exc}"])


def _find_repo_root(start: Path) -> Path:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / "contracts" / "execution-contract.schema.json").exists():
            return candidate
    raise FileNotFoundError(
        "Cannot locate contracts/execution-contract.schema.json from "
        f"{start}. Run from the repository root or pass --repo-root explicitly."
    )


def derive(
    contract_path: Path,
    output_dir: Path,
    *,
    repo_root: Path | None = None,
) -> None:
    """
    Derive runtime-contract.json and public-contract.json from a promoted execution contract.

    Returns None on success.
    Raises DerivationFailed with a list of error messages on any failure.
    Neither the contract nor any existing file is modified.
    """
    if repo_root is None:
        repo_root = _find_repo_root(contract_path.parent)

    execution_schema_path = repo_root / "contracts" / "execution-contract.schema.json"
    runtime_schema_path = repo_root / "contracts" / "runtime-contract.schema.json"
    public_schema_path = repo_root / "contracts" / "public-contract.schema.json"

    for schema_path in (execution_schema_path, runtime_schema_path, public_schema_path):
        if not schema_path.exists():
            raise DerivationFailed([f"schema not found: {schema_path}"])

    execution_schema = _load_json(execution_schema_path)
    contract = _load_json(contract_path)

    # Step 1 — pre-validate execution contract against its schema (constraint-06).
    validator = jsonschema.Draft7Validator(execution_schema)
    schema_errors = sorted(validator.iter_errors(contract), key=lambda e: list(e.path))
    if schema_errors:
        first = schema_errors[0].message
        raise DerivationFailed([f"execution contract schema validation failed: {first}"])

    # Step 2 — runtime check: every feature_columns entry must have a feature_definitions entry (decision-06).
    feature_columns: list[str] = contract["feature_columns"]
    feature_definitions: dict[str, dict] = contract.get("feature_definitions", {})
    required_columns: list[str] = contract.get("required_columns", [])
    optional_columns: list[str] = contract.get("optional_columns", [])

    missing_errors: list[str] = []
    for name in feature_columns:
        if name not in feature_definitions:
            missing_errors.append(
                f'feature "{name}" in feature_columns has no entry in feature_definitions'
            )
    if missing_errors:
        raise DerivationFailed(missing_errors)

    # Step 3 — derive runtime contract (decision-08).
    runtime_features: list[dict] = []
    for name in feature_columns:
        defn = feature_definitions[name]
        feature: dict[str, Any] = {
            "name": name,
            "type": defn["type"],
        }
        if name in required_columns:
            feature["required"] = True
        elif name in optional_columns:
            feature["required"] = False
        # else: omit required; schema default is True
        if "domain_constraints" in defn:
            feature["domain_constraints"] = defn["domain_constraints"]
        if "description" in defn:
            feature["description"] = defn["description"]
        runtime_features.append(feature)

    runtime_contract: dict[str, Any] = {
        "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
        "features": runtime_features,
    }

    # Step 4 — validate derived runtime contract against its schema.
    runtime_schema = _load_json(runtime_schema_path)
    runtime_validator = jsonschema.Draft7Validator(runtime_schema)
    runtime_errors = sorted(runtime_validator.iter_errors(runtime_contract), key=lambda e: list(e.path))
    if runtime_errors:
        msgs = [e.message for e in runtime_errors]
        raise DerivationFailed([f"derived runtime contract failed schema validation: {m}" for m in msgs])

    # Step 5 — derive public contract by importing from contract_derivation (decision-09, constraint-05).
    public_contract = _derive_public_contract(runtime_contract)

    # Step 6 — safety check: no _RUNTIME_ONLY_KEYS in any public feature.
    safety_errors = _check_safety(public_contract)
    if safety_errors:
        raise DerivationFailed(safety_errors)

    # Step 7 — validate derived public contract against its schema.
    public_schema = _load_json(public_schema_path)
    public_validator = jsonschema.Draft7Validator(public_schema)
    public_errors = sorted(public_validator.iter_errors(public_contract), key=lambda e: list(e.path))
    if public_errors:
        msgs = [e.message for e in public_errors]
        raise DerivationFailed([f"derived public contract failed schema validation (pipeline bug): {m}" for m in msgs])

    # Step 8 — write outputs.
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_out = output_dir / "runtime-contract.json"
    public_out = output_dir / "public-contract.json"
    evidence_out = output_dir / "projection-evidence.json"

    runtime_out.write_text(json.dumps(runtime_contract, indent=2), encoding="utf-8")
    public_out.write_text(json.dumps(public_contract, indent=2), encoding="utf-8")

    # Project Spec S0099: explicit, deterministic evidence of projection
    # sufficiency -- never silently discarded. runtime_feature_names/
    # public_feature_names prove feature-identity parity across all three
    # contract layers (execution feature_columns -> runtime -> public) by
    # construction of the projection above, not by a separate re-check.
    # unresolved_select_features names every select field this derivation
    # could not attach safe canonical options to, so a select-without-options
    # is a reported, explicitly supported condition rather than a silently
    # incomplete control.
    evidence = {
        "schema_version": PROJECTION_EVIDENCE_SCHEMA_VERSION,
        "execution_feature_columns": list(feature_columns),
        "runtime_feature_names": [f["name"] for f in runtime_features],
        "public_feature_names": [f["name"] for f in public_contract["features"]],
        "unresolved_select_features": unresolved_select_features(public_contract),
    }
    evidence_out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive runtime and public contract projections from a promoted execution contract."
    )
    parser.add_argument(
        "--contract", required=True,
        help="Path to the promoted execution contract JSON file."
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory where runtime-contract.json and public-contract.json are written."
    )
    parser.add_argument(
        "--repo-root",
        help="Repository root directory. Defaults to auto-detected from contract path.",
    )
    args = parser.parse_args(argv)

    contract_path = Path(args.contract)
    output_dir = Path(args.output_dir)
    repo_root = Path(args.repo_root) if args.repo_root else None

    try:
        derive(contract_path, output_dir, repo_root=repo_root)
    except DerivationFailed as exc:
        print("DERIVATION FAILED", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Projection derivation succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
