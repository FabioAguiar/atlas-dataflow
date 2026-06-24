"""
Contract promotion validator for atlas-dataflow M23-02.

Reads a human-facing contract JSON, validates and maps reviewed fields to
execution_contract.v1, and produces a validated execution contract or a
field-level rejection report.

Scope boundary (M23-02): All checks are schema-structural only. This module
does NOT invoke the discovery pipeline, does NOT read discovery evidence, and
does NOT validate actual null rates or cardinality (M23-03 scope).

Constraints:
- Reads the human-facing contract as a read-only input; never modifies it.
- Requires no internet access or external services; uses only local repo files.
- Every accepted field is explicitly mapped; no silent inference.
- On rejection, produces a field-level error report and stops; does not
  attempt to correct or infer valid values.
- The mapping output is validated against contracts/execution-contract.schema.json
  using jsonschema; the schema is the canonical enforcement layer.
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

_VALID_FIELD_TYPES = frozenset({"numeric", "categorical", "boolean"})
_VALID_TRANSFORMATIONS = frozenset({"log1p", "sqrt", "clip", "passthrough"})
_VALID_MISSING_STRATEGIES = frozenset({"mean", "median", "mode", "constant", "drop_row"})
_VALID_ENCODING_POLICIES = frozenset({"onehot", "ordinal", "target_encode", "binary"})
_VALID_NUMERIC_HANDLING = frozenset({"standardize", "normalize", "passthrough"})
_VALID_METRICS = frozenset({"roc_auc", "f1", "accuracy", "log_loss", "pr_auc"})

_DEFAULTS: dict[str, Any] = {
    "random_seed": None,
    "secondary_metrics": [],
    "categorical_encoding_policy": "onehot",
    "numeric_handling": "standardize",
    "allowed_transformations": ["passthrough"],
    "split_policy": {
        "strategy": "stratified",
        "train_ratio": 0.7,
        "val_ratio": 0.15,
        "test_ratio": 0.15,
    },
    "primary_metric": "roc_auc",
    "modeling_constraints": {
        "no_automl": True,
        "max_training_time_seconds": None,
        "allowed_model_families": ["logistic_regression", "gradient_boosting"],
    },
}

_MISSING_VALUE_TYPE_DEFAULTS: dict[str, str] = {
    "numeric": "median",
    "categorical": "mode",
    "boolean": "mode",
}


class PromotionRejected(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(errors))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_repo_root(start: Path) -> Path:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / "contracts" / "execution-contract.schema.json").exists():
            return candidate
    raise FileNotFoundError(
        "Cannot locate contracts/execution-contract.schema.json from "
        f"{start}. Run from the repository root or pass --repo-root."
    )


def promote(contract_path: Path, *, repo_root: Path | None = None) -> dict:
    """
    Promote a human-facing contract to execution_contract.v1.

    Returns the validated execution contract dict on success.
    Raises PromotionRejected with a list of field-level error messages on failure.
    The input contract file is never modified.
    """
    if repo_root is None:
        repo_root = _find_repo_root(contract_path.parent)

    schema_path = repo_root / "contracts" / "execution-contract.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Execution contract schema not found: {schema_path}")

    schema = _load_json(schema_path)
    contract = _load_json(contract_path)

    errors: list[str] = []

    # Gate: promotion_boundary.promotion_authorized
    promotion_boundary = contract.get("promotion_boundary") or {}
    if not promotion_boundary.get("promotion_authorized", False):
        raise PromotionRejected([
            "promotion_boundary.promotion_authorized is false: "
            "this contract has not been authorized for promotion. "
            "Set promotion_authorized: true after completing human review."
        ])

    # Extract dataset_id (field mapping decision-04-d)
    dataset_id = (
        contract.get("dataset_id")
        or contract.get("dataset_slug")
        or (contract.get("dataset_metadata") or {}).get("name")
    )
    if not dataset_id:
        errors.append(
            "dataset_id: absent or empty. "
            "The human-facing contract must declare dataset_id."
        )

    # Extract target_column (field mapping decision-04-c)
    target_field = contract.get("target_field") or {}
    target_column: str | None = (
        target_field.get("name") if isinstance(target_field, dict) else None
    )
    if not target_column:
        errors.append(
            "target_column: absent or empty (target_field.name). "
            "The human-facing contract must declare target_field.name."
        )

    # Partition candidate_fields into approved and ignored (decision-04-a, -f, -g)
    candidate_fields: list[dict] = contract.get("candidate_fields") or []
    approved_fields: list[dict] = []
    ignored_field_names: list[str] = []

    for field in candidate_fields:
        name = field.get("name", "")
        status = field.get("review_status", "")
        if status == "approved":
            approved_fields.append(field)
        elif name and name != target_column:
            ignored_field_names.append(name)

    # Validate approved field types (rejection-a)
    for field in approved_fields:
        name = field.get("name", "<unnamed>")
        field_type = field.get("field_type")
        if field_type not in _VALID_FIELD_TYPES:
            errors.append(
                f"field '{name}': field_type '{field_type}' is not one of "
                f"{sorted(_VALID_FIELD_TYPES)}. "
                "Policy: field_type must be one of numeric, categorical, boolean."
            )

    # Validate approved field missing_value_strategy values (rejection-c)
    for field in approved_fields:
        name = field.get("name", "<unnamed>")
        mvs = field.get("missing_value_strategy")
        if mvs is not None and mvs not in _VALID_MISSING_STRATEGIES:
            errors.append(
                f"field '{name}': missing_value_strategy '{mvs}' is not one of "
                f"{sorted(_VALID_MISSING_STRATEGIES)}. "
                "Policy: must be one of mean, median, mode, constant, drop_row."
            )

    # Extract top-level policy block (optional in human-facing contract)
    policy: dict = contract.get("policy") or {}

    # Validate categorical_encoding_policy (rejection-d)
    encoding_policy: str | None = policy.get("categorical_encoding_policy")
    if encoding_policy is not None and encoding_policy not in _VALID_ENCODING_POLICIES:
        errors.append(
            f"categorical_encoding_policy: '{encoding_policy}' is not one of "
            f"{sorted(_VALID_ENCODING_POLICIES)}. "
            "Policy: must be one of onehot, ordinal, target_encode, binary."
        )

    # Validate numeric_handling (rejection-e)
    numeric_handling: str | None = policy.get("numeric_handling")
    if numeric_handling is not None and numeric_handling not in _VALID_NUMERIC_HANDLING:
        errors.append(
            f"numeric_handling: '{numeric_handling}' is not one of "
            f"{sorted(_VALID_NUMERIC_HANDLING)}. "
            "Policy: must be one of standardize, normalize, passthrough."
        )

    # Validate allowed_transformations (rejection-b)
    allowed_transformations: list[str] | None = policy.get("allowed_transformations")
    if allowed_transformations is not None:
        for t in allowed_transformations:
            if t not in _VALID_TRANSFORMATIONS:
                errors.append(
                    f"allowed_transformations: '{t}' is not one of "
                    f"{sorted(_VALID_TRANSFORMATIONS)}. "
                    "Policy: must be one of log1p, sqrt, clip, passthrough."
                )

    # Validate primary_metric (rejection-f)
    primary_metric: str | None = policy.get("primary_metric")
    if primary_metric is not None and primary_metric not in _VALID_METRICS:
        errors.append(
            f"primary_metric: '{primary_metric}' is not one of "
            f"{sorted(_VALID_METRICS)}. "
            "Policy: must be one of roc_auc, f1, accuracy, log_loss, pr_auc."
        )

    # Validate secondary_metrics (rejection-f)
    secondary_metrics: list[str] | None = policy.get("secondary_metrics")
    if secondary_metrics is not None:
        for m in secondary_metrics:
            if m not in _VALID_METRICS:
                errors.append(
                    f"secondary_metrics: '{m}' is not one of "
                    f"{sorted(_VALID_METRICS)}. "
                    "Policy: must be one of roc_auc, f1, accuracy, log_loss, pr_auc."
                )

    # Validate split_policy ratios sum to 1.0 (gap-02)
    split_policy: dict | None = policy.get("split_policy")
    if split_policy is not None:
        tr = split_policy.get("train_ratio", 0)
        vr = split_policy.get("val_ratio", 0)
        te = split_policy.get("test_ratio", 0)
        total = round(tr + vr + te, 10)
        if abs(total - 1.0) > 1e-9:
            errors.append(
                f"split_policy: train_ratio ({tr}) + val_ratio ({vr}) + "
                f"test_ratio ({te}) = {total}, must sum to 1.0. "
                "Policy: declare ratios that sum exactly to 1.0 or omit "
                "split_policy to use the documented default."
            )

    # Validate modeling_constraints if declared (rejection-i)
    modeling_constraints_declared: dict | None = policy.get("modeling_constraints")
    if modeling_constraints_declared is not None:
        aml = modeling_constraints_declared.get("allowed_model_families")
        if aml is not None and len(aml) == 0:
            errors.append(
                "modeling_constraints.allowed_model_families: must not be empty. "
                "Policy: at least one model family must be permitted."
            )

    # feature_columns empty check (rejection-h)
    feature_column_names = [f["name"] for f in approved_fields if f.get("name")]
    if not feature_column_names and not errors:
        errors.append(
            "feature_columns: resolves to an empty list — no candidate_fields "
            "entries have review_status 'approved'. "
            "At least one approved field is required for promotion."
        )

    if errors:
        raise PromotionRejected(errors)

    # Build feature_definitions and missing_value_policy (decision-04-b, -h)
    feature_definitions: dict[str, dict] = {}
    missing_value_policy: dict[str, str] = {}
    required_columns: list[str] = []
    optional_columns: list[str] = []

    for field in approved_fields:
        name: str = field["name"]
        field_type: str = field["field_type"]

        fd: dict[str, Any] = {"type": field_type}
        known_values = field.get("known_values")
        sample_min = field.get("sample_min")
        sample_max = field.get("sample_max")

        if field_type == "categorical" and isinstance(known_values, list):
            fd["domain_constraints"] = {"values": [str(v) for v in known_values]}
        elif field_type == "numeric":
            dc: dict[str, Any] = {}
            if sample_min is not None:
                dc["min"] = sample_min
            if sample_max is not None:
                dc["max"] = sample_max
            if dc:
                fd["domain_constraints"] = dc
        # boolean: no domain_constraints per schema

        feature_definitions[name] = fd

        # missing_value_policy: per-field value or type-based default (decision-04-h)
        mvs = field.get("missing_value_strategy")
        if mvs is None:
            mvs = _MISSING_VALUE_TYPE_DEFAULTS.get(field_type, "mode")
        missing_value_policy[name] = mvs

        # required vs optional (decision-04-e, -f)
        if field.get("optional", False):
            optional_columns.append(name)
        else:
            required_columns.append(name)

    # Apply defaults for policy fields not declared in the human-facing contract (decision-05)
    exec_encoding = encoding_policy if encoding_policy is not None else _DEFAULTS["categorical_encoding_policy"]
    exec_numeric = numeric_handling if numeric_handling is not None else _DEFAULTS["numeric_handling"]
    exec_transforms = allowed_transformations if allowed_transformations is not None else _DEFAULTS["allowed_transformations"]
    exec_split = split_policy if split_policy is not None else _DEFAULTS["split_policy"]
    exec_primary = primary_metric if primary_metric is not None else _DEFAULTS["primary_metric"]
    exec_secondary = secondary_metrics if secondary_metrics is not None else _DEFAULTS["secondary_metrics"]
    exec_random_seed = policy.get("random_seed", _DEFAULTS["random_seed"])

    if modeling_constraints_declared is not None:
        mc_families = modeling_constraints_declared.get(
            "allowed_model_families", _DEFAULTS["modeling_constraints"]["allowed_model_families"]
        )
        mc_no_automl = modeling_constraints_declared.get(
            "no_automl", _DEFAULTS["modeling_constraints"]["no_automl"]
        )
        mc_max_time = modeling_constraints_declared.get(
            "max_training_time_seconds", _DEFAULTS["modeling_constraints"]["max_training_time_seconds"]
        )
    else:
        mc_families = _DEFAULTS["modeling_constraints"]["allowed_model_families"]
        mc_no_automl = _DEFAULTS["modeling_constraints"]["no_automl"]
        mc_max_time = _DEFAULTS["modeling_constraints"]["max_training_time_seconds"]

    # modeling_constraints.allowed_model_families empty check after defaults (rejection-i)
    if not mc_families:
        raise PromotionRejected([
            "modeling_constraints.allowed_model_families: resolves to an empty list. "
            "At least one model family must be permitted."
        ])

    execution_contract: dict[str, Any] = {
        "contract_version": "execution_contract.v1",
        "dataset_id": dataset_id,
        "target_column": target_column,
        "feature_columns": feature_column_names,
        "ignored_columns": ignored_field_names,
        "required_columns": required_columns,
        "optional_columns": optional_columns,
        "feature_definitions": feature_definitions,
        "missing_value_policy": missing_value_policy,
        "categorical_encoding_policy": exec_encoding,
        "numeric_handling": exec_numeric,
        "allowed_transformations": exec_transforms,
        "split_policy": exec_split,
        "random_seed": exec_random_seed,
        "primary_metric": exec_primary,
        "secondary_metrics": exec_secondary,
        "modeling_constraints": {
            "allowed_model_families": mc_families,
            "no_automl": mc_no_automl,
            "max_training_time_seconds": mc_max_time,
        },
    }

    # Canonical schema enforcement (constraint-05)
    validator = jsonschema.Draft7Validator(schema)
    schema_errors = sorted(
        validator.iter_errors(execution_contract), key=lambda e: list(e.path)
    )
    if schema_errors:
        field_errors = []
        for e in schema_errors:
            path = (
                ".".join(str(p) for p in e.absolute_path)
                if e.absolute_path
                else "<root>"
            )
            rule = e.schema_path[-1] if e.schema_path else "unknown"
            field_errors.append(
                f"schema validation failed at '{path}': {e.message} "
                f"(schema rule: {rule})"
            )
        raise PromotionRejected(field_errors)

    return execution_contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote a human-facing contract to execution_contract.v1."
    )
    parser.add_argument("contract", help="Path to the human-facing contract JSON file.")
    parser.add_argument(
        "--output", "-o",
        help="Write the validated execution contract to this path. "
             "Defaults to stdout.",
    )
    parser.add_argument(
        "--repo-root",
        help="Repository root directory. Defaults to auto-detected from contract path.",
    )
    args = parser.parse_args(argv)

    contract_path = Path(args.contract)
    repo_root = Path(args.repo_root) if args.repo_root else None

    try:
        result = promote(contract_path, repo_root=repo_root)
    except PromotionRejected as exc:
        print("PROMOTION REJECTED", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output, encoding="utf-8")
        print(f"Execution contract written to {out_path}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
