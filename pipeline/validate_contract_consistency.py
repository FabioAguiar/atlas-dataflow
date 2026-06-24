"""
Execution contract consistency validator for atlas-dataflow M23-03.

Cross-checks a validated execution contract (execution_contract.v1) against
M22 dataset discovery evidence. Verifies that declared feature columns and the
target column exist in the discovered schema, that declared types are compatible
with inferred types from discovery, and that the split policy is compatible with
the observed dataset row count.

Constraints:
- Reads both inputs as read-only; never modifies them.
- Does not invoke pipeline/discovery_evidence.py or re-run dataset discovery.
- Raises ConsistencyCheckFailed with field-level errors on any inconsistency.
- Requires no internet access; uses only local repository files.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    print("ERROR: jsonschema is required. Install with: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

# Type compatibility matrix (decision-04):
# Maps execution field_type -> set of compatible discovery inferred_types.
_COMPAT: dict[str, frozenset[str]] = {
    "numeric": frozenset({"integer", "float"}),
    "categorical": frozenset({"string"}),
    "boolean": frozenset({"boolean"}),
}

_KNOWN_INFERRED_TYPES = frozenset({"integer", "float", "boolean", "string", "empty"})


class ConsistencyCheckFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(errors))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConsistencyCheckFailed([f"file not found: {path}"])
    except json.JSONDecodeError as exc:
        raise ConsistencyCheckFailed([f"invalid JSON in {path}: {exc}"])


def _find_repo_root(start: Path) -> Path:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / "contracts" / "execution-contract.schema.json").exists():
            return candidate
    raise FileNotFoundError(
        "Cannot locate contracts/execution-contract.schema.json from "
        f"{start}. Run from the repository root or pass repo_root explicitly."
    )


def check(
    contract_path: Path,
    evidence_path: Path,
    *,
    repo_root: Path | None = None,
) -> None:
    """
    Cross-check a validated execution contract against discovery evidence.

    Returns None on success.
    Raises ConsistencyCheckFailed with a list of field-level error messages on
    any inconsistency. Neither input file is modified.
    """
    if repo_root is None:
        repo_root = _find_repo_root(contract_path.parent)

    contract_schema_path = repo_root / "contracts" / "execution-contract.schema.json"
    evidence_schema_path = repo_root / "pipeline" / "dataset-discovery-evidence.schema.json"

    if not contract_schema_path.exists():
        raise ConsistencyCheckFailed([
            f"execution contract schema not found: {contract_schema_path}"
        ])
    if not evidence_schema_path.exists():
        raise ConsistencyCheckFailed([
            f"discovery evidence schema not found: {evidence_schema_path}"
        ])

    contract_schema = _load_json(contract_schema_path)
    evidence_schema = _load_json(evidence_schema_path)
    contract = _load_json(contract_path)
    evidence = _load_json(evidence_path)

    # Pre-validate execution contract against its schema (decision-06).
    contract_validator = jsonschema.Draft7Validator(contract_schema)
    contract_schema_errors = sorted(
        contract_validator.iter_errors(contract), key=lambda e: list(e.path)
    )
    if contract_schema_errors:
        errs = []
        for e in contract_schema_errors:
            loc = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "<root>"
            errs.append(f"contract schema validation failed at '{loc}': {e.message}")
        raise ConsistencyCheckFailed(errs)

    # Pre-validate discovery evidence against its schema (decision-06).
    evidence_validator = jsonschema.Draft7Validator(evidence_schema)
    evidence_schema_errors = sorted(
        evidence_validator.iter_errors(evidence), key=lambda e: list(e.path)
    )
    if evidence_schema_errors:
        errs = []
        for e in evidence_schema_errors:
            loc = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "<root>"
            errs.append(f"evidence schema validation failed at '{loc}': {e.message}")
        raise ConsistencyCheckFailed(errs)

    # Index field_observations by name (constraint-06, fact-02).
    # field_observations is an array — must not be assumed to be a dict.
    obs_by_name: dict[str, dict] = {
        o["name"]: o for o in evidence["field_observations"]
    }

    errors: list[str] = []

    feature_columns: list[str] = contract["feature_columns"]
    feature_definitions: dict[str, dict] = contract.get("feature_definitions", {})

    # Check each feature column exists in discovery and has a compatible type.
    for col_name in feature_columns:
        if col_name not in obs_by_name:
            errors.append(
                f"feature column '{col_name}': declared column absent from "
                "discovery field_observations"
            )
            continue  # type check requires presence; skip if absent

        obs = obs_by_name[col_name]
        inferred = obs["inferred_type"]
        field_def = feature_definitions.get(col_name, {})
        declared_type = field_def.get("type")

        if inferred == "empty":
            # No non-null values observed — no empirical contradiction possible
            # (decision-04). Pass unconditionally.
            pass
        elif inferred not in _KNOWN_INFERRED_TYPES:
            errors.append(
                f"field '{col_name}': discovery inferred_type '{inferred}' is "
                "not a recognised type in the compatibility matrix"
            )
        elif declared_type is not None:
            compatible = _COMPAT.get(declared_type, frozenset())
            if inferred not in compatible:
                errors.append(
                    f"field '{col_name}': declared type {declared_type} "
                    f"incompatible with discovered type {inferred}"
                )

    # Check target_column exists in discovery (decision-07).
    target_column: str = contract["target_column"]
    if target_column not in obs_by_name:
        errors.append(
            f"target_column '{target_column}': declared column absent from "
            "discovery field_observations"
        )

    # Check split policy compatibility with dataset size (decision-05).
    # Reject if floor(row_count * train_ratio) < 50.
    row_count: int = evidence["dataset_metadata"]["row_count"]
    split_policy: dict = contract["split_policy"]
    train_ratio: float = split_policy["train_ratio"]
    training_rows = math.floor(row_count * train_ratio)
    if training_rows < 50:
        errors.append(
            f"split policy incompatible with dataset size: "
            f"floor({row_count} * {train_ratio}) = {training_rows} < 50 minimum training rows"
        )

    if errors:
        raise ConsistencyCheckFailed(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check an execution contract against dataset discovery evidence."
    )
    parser.add_argument(
        "--contract", required=True,
        help="Path to the validated execution contract JSON file."
    )
    parser.add_argument(
        "--evidence", required=True,
        help="Path to the dataset discovery evidence JSON file."
    )
    parser.add_argument(
        "--repo-root",
        help="Repository root directory. Defaults to auto-detected from contract path.",
    )
    args = parser.parse_args(argv)

    contract_path = Path(args.contract)
    evidence_path = Path(args.evidence)
    repo_root = Path(args.repo_root) if args.repo_root else None

    try:
        check(contract_path, evidence_path, repo_root=repo_root)
    except ConsistencyCheckFailed as exc:
        print("CONSISTENCY CHECK FAILED", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Consistency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
