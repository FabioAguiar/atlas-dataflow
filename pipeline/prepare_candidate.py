"""
Dataset preparation pipeline for atlas-dataflow M22-04.

Reads M22-02 discovery evidence and explicitly declared preparation rules,
applies only authorized transformations, and writes a conditional prepared
dataset candidate and preparation recipe.

Boundaries enforced by this module:
- discovery_evidence_path, dataset_input_path, and rules_path are required.
- Preparation rules must be explicitly declared in a rules JSON file.
- Inferred rules (review_status 'inferred_pending_review') are recorded in the
  recipe but NOT applied; only 'explicit' and 'inferred_approved' rules are applied.
- A prepared candidate is produced only when at least one applicable rule exists.
- When no applicable rules exist, a no-candidate recipe is written; no output CSV is produced.
- No complex feature engineering, model training, or release publication is performed.
- Raw dataset content is not persisted beyond the candidate CSV output.
- The prepared candidate carries explicit candidate status (not final training input).
- All transformations are recorded in the recipe; hidden transformations are prohibited.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_GENERATOR_VERSION = "prepare-candidate.v1"
_SCHEMA_VERSION = "candidate-preparation-recipe.v1"
_APPLICABLE_STATUSES = ("explicit", "inferred_approved")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path(path: Path) -> str:
    return path.name


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    return columns, rows


def _load_rules(rules_path: Path) -> dict[str, Any]:
    if not rules_path.exists():
        raise FileNotFoundError(f"Preparation rules file not found: {rules_path}")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if not isinstance(rules, dict):
        raise ValueError("Preparation rules must be a JSON object.")
    return rules


def _apply_column_selection(
    columns: list[str],
    rows: list[dict[str, str]],
    selected: list[str],
) -> tuple[list[str], list[dict[str, str]]]:
    missing = [c for c in selected if c not in columns]
    if missing:
        raise ValueError(f"Column selection references columns not in dataset: {missing}")
    new_columns = [c for c in columns if c in selected]
    new_rows = [{c: row[c] for c in new_columns} for row in rows]
    return new_columns, new_rows


def _apply_row_filter(
    rows: list[dict[str, str]],
    column: str,
    operator: str,
    value: Any,
) -> list[dict[str, str]]:
    """Filter rows. Supports operators: eq, neq, gt, gte, lt, lte, in."""
    result = []
    for row in rows:
        cell = row.get(column, "")
        try:
            cell_num = float(cell)
            val_num = float(value)
            num_ok = True
        except (ValueError, TypeError):
            num_ok = False

        if operator == "eq":
            keep = str(cell) == str(value)
        elif operator == "neq":
            keep = str(cell) != str(value)
        elif operator == "in":
            keep = str(cell) in [str(v) for v in value]
        elif operator == "gte" and num_ok:
            keep = cell_num >= val_num
        elif operator == "lte" and num_ok:
            keep = cell_num <= val_num
        elif operator == "gt" and num_ok:
            keep = cell_num > val_num
        elif operator == "lt" and num_ok:
            keep = cell_num < val_num
        else:
            keep = True
        if keep:
            result.append(row)
    return result


def _apply_missing_value_rule(
    rows: list[dict[str, str]],
    column: str,
    action: str,
    fill_value: Any = None,
) -> list[dict[str, str]]:
    """Handle missing values: drop_row drops rows with empty column; fill_value replaces them."""
    result = []
    for row in rows:
        if row.get(column, "") == "":
            if action == "drop_row":
                continue
            elif action == "fill_value":
                row = dict(row)
                row[column] = str(fill_value) if fill_value is not None else ""
        result.append(row)
    return result


def _apply_type_normalization(
    rows: list[dict[str, str]],
    column: str,
    target_type: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Normalize column values to the declared type. Returns updated rows and non-fatal notes."""
    result = []
    notes: list[str] = []
    for i, row in enumerate(rows):
        cell = row.get(column, "")
        if cell == "":
            result.append(row)
            continue
        try:
            if target_type == "integer":
                normalized = str(int(float(cell)))
            elif target_type == "float":
                normalized = str(float(cell))
            elif target_type == "boolean":
                if cell.lower() in {"true", "1", "yes"}:
                    normalized = "true"
                elif cell.lower() in {"false", "0", "no"}:
                    normalized = "false"
                else:
                    raise ValueError(f"cannot normalize '{cell}' to boolean")
            elif target_type == "string":
                normalized = str(cell)
            else:
                notes.append(f"row {i}: unsupported target_type '{target_type}' for column '{column}'")
                result.append(row)
                continue
            row = dict(row)
            row[column] = normalized
        except (ValueError, TypeError) as exc:
            notes.append(f"row {i}, column '{column}': {exc}")
        result.append(row)
    return result, notes


def _build_transformations_record(rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the ordered transformations list for the recipe."""
    transformations: list[dict[str, Any]] = []

    col_sel = rules.get("column_selection")
    if col_sel:
        transformations.append({
            "transformation_type": "column_selection",
            "description": f"Select columns: {col_sel}",
            "source_columns": list(col_sel),
            "target_columns": list(col_sel),
            "reason": rules.get("column_selection_reason", "Declared by preparation rules."),
            "review_status": "explicit",
        })

    for rule in rules.get("type_normalizations", []):
        transformations.append({
            "transformation_type": "type_normalization",
            "description": f"Normalize '{rule['column']}' to {rule['target_type']}",
            "source_columns": [rule["column"]],
            "target_columns": [rule["column"]],
            "reason": rule.get("reason", "Declared by preparation rules."),
            "review_status": rule.get("review_status", "explicit"),
        })

    for rule in rules.get("row_filters", []):
        transformations.append({
            "transformation_type": "row_filtering",
            "description": f"Filter rows: {rule['column']} {rule['operator']} {rule['value']}",
            "source_columns": [rule["column"]],
            "target_columns": [],
            "reason": rule.get("reason", "Declared by preparation rules."),
            "review_status": rule.get("review_status", "explicit"),
        })

    for rule in rules.get("missing_value_rules", []):
        transformations.append({
            "transformation_type": "missing_value_handling",
            "description": f"Handle missing in '{rule['column']}': {rule['action']}",
            "source_columns": [rule["column"]],
            "target_columns": [rule["column"]],
            "reason": rule.get("reason", "Declared by preparation rules."),
            "review_status": rule.get("review_status", "explicit"),
        })

    for rule in rules.get("categorical_columns", []):
        transformations.append({
            "transformation_type": "categorical_treatment",
            "description": f"Record '{rule['column']}' as categorical",
            "source_columns": [rule["column"]],
            "target_columns": [rule["column"]],
            "reason": rule.get("reason", "Declared by preparation rules."),
            "review_status": rule.get("review_status", "explicit"),
        })

    return transformations


def _has_applicable_rules(rules: dict[str, Any]) -> bool:
    """Return True if rules contain at least one explicitly declared or approved transformation."""
    if rules.get("column_selection"):
        return True
    for section in ("type_normalizations", "row_filters", "missing_value_rules", "categorical_columns"):
        for rule in rules.get(section, []):
            if rule.get("review_status", "explicit") in _APPLICABLE_STATUSES:
                return True
    return False


def prepare_candidate(
    discovery_evidence_path: str | Path,
    dataset_input_path: str | Path,
    rules_path: str | Path,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], list[str] | None, list[dict[str, str]] | None]:
    """Run the preparation pipeline.

    Returns (recipe, output_columns, output_rows).
    output_columns and output_rows are None when no candidate was produced.
    """
    discovery_evidence_path = Path(discovery_evidence_path)
    dataset_input_path = Path(dataset_input_path)
    rules_path = Path(rules_path)

    if not discovery_evidence_path.exists():
        raise FileNotFoundError(f"Discovery evidence not found: {discovery_evidence_path}")
    if not dataset_input_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_input_path}")

    discovery_evidence = json.loads(
        discovery_evidence_path.read_text(encoding="utf-8")
    )
    rules = _load_rules(rules_path)

    columns, rows = _read_csv(dataset_input_path)
    row_count_before = len(rows)
    col_count_before = len(columns)

    transformations = _build_transformations_record(rules)

    candidate_produced = False
    output_columns: list[str] | None = None
    output_rows: list[dict[str, str]] | None = None
    candidate_not_produced_reason: str | None = None
    normalization_notes: list[str] = []

    pending_review_count = sum(
        1 for t in transformations if t["review_status"] == "inferred_pending_review"
    )

    if not _has_applicable_rules(rules):
        candidate_not_produced_reason = (
            "No transformation rules with review_status 'explicit' or 'inferred_approved' "
            f"were found. {pending_review_count} rule(s) are pending human review and cannot "
            "be applied without explicit approval."
        )
    else:
        cur_columns = list(columns)
        cur_rows = list(rows)

        col_sel = rules.get("column_selection")
        if col_sel:
            cur_columns, cur_rows = _apply_column_selection(cur_columns, cur_rows, col_sel)

        for rule in rules.get("type_normalizations", []):
            if rule.get("review_status", "explicit") in _APPLICABLE_STATUSES:
                cur_rows, notes = _apply_type_normalization(
                    cur_rows, rule["column"], rule["target_type"]
                )
                normalization_notes.extend(notes)

        for rule in rules.get("row_filters", []):
            if rule.get("review_status", "explicit") in _APPLICABLE_STATUSES:
                cur_rows = _apply_row_filter(
                    cur_rows, rule["column"], rule["operator"], rule["value"]
                )

        for rule in rules.get("missing_value_rules", []):
            if rule.get("review_status", "explicit") in _APPLICABLE_STATUSES:
                cur_rows = _apply_missing_value_rule(
                    cur_rows, rule["column"], rule["action"], rule.get("fill_value")
                )

        candidate_produced = True
        output_columns = cur_columns
        output_rows = cur_rows

    recipe: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {
            "name": _reduced_path(dataset_input_path),
            "row_count_before": row_count_before,
            "column_count_before": col_count_before,
        },
        "discovery_evidence_ref": {
            "path": _reduced_path(discovery_evidence_path),
            "schema_version": discovery_evidence.get("schema_version", "unknown"),
        },
        "transformations": transformations,
        "candidate_output": {
            "produced": candidate_produced,
            "reason_not_produced": candidate_not_produced_reason,
            "row_count_after": len(output_rows) if output_rows is not None else None,
            "column_count_after": len(output_columns) if output_columns is not None else None,
        },
        "candidate_status": {
            "is_final_training_input": False,
            "requires_m23_validation": True,
            "authorized_for": "candidate_only",
        },
        "generation_settings": {
            "generator_version": _GENERATOR_VERSION,
            "preparation_rules_source": _reduced_path(rules_path),
        },
        "generated_at": generated_at or _utc_now_iso(),
        "preparation_boundary_confirmations": {
            "complex_feature_engineering_performed": False,
            "model_training_performed": False,
            "release_publication_performed": False,
            "hidden_notebook_transformations": False,
            "inferred_rules_applied_without_approval": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }

    if normalization_notes:
        recipe["normalization_notes"] = normalization_notes

    return recipe, output_columns, output_rows


def write_candidate_output(
    candidate_path: str | Path,
    columns: list[str],
    rows: list[dict[str, str]],
) -> None:
    """Write the prepared dataset candidate to a CSV file."""
    out = Path(candidate_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_preparation_recipe(
    output_path: str | Path,
    recipe: dict[str, Any],
    repo_root: str | Path,
) -> None:
    """Validate recipe against schema (when jsonschema is available) and write to JSON."""
    schema_path = (
        Path(repo_root) / "pipeline" / "candidate-preparation-recipe.schema.json"
    )
    try:
        import jsonschema

        if schema_path.exists():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(recipe, schema)
    except ImportError:
        pass

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recipe, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="M22-04 dataset preparation pipeline for atlas-dataflow.",
    )
    p.add_argument(
        "--discovery-evidence",
        required=True,
        help="Path to M22-02 discovery evidence JSON.",
    )
    p.add_argument(
        "--dataset",
        required=True,
        help="Path to the raw input CSV dataset.",
    )
    p.add_argument(
        "--rules",
        required=True,
        help="Path to preparation rules JSON.",
    )
    p.add_argument(
        "--output-recipe",
        required=True,
        help="Path to write the preparation recipe JSON.",
    )
    p.add_argument(
        "--output-candidate",
        default=None,
        help="Path to write the prepared dataset candidate CSV (when produced).",
    )
    p.add_argument(
        "--repo-root",
        default=".",
        help="Repository root for schema resolution (default: current directory).",
    )
    return p


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    recipe, columns, rows = prepare_candidate(
        discovery_evidence_path=args.discovery_evidence,
        dataset_input_path=args.dataset,
        rules_path=args.rules,
    )

    write_preparation_recipe(args.output_recipe, recipe, args.repo_root)

    if recipe["candidate_output"]["produced"]:
        if args.output_candidate:
            write_candidate_output(args.output_candidate, columns, rows)
        else:
            print(
                "WARNING: Candidate was produced but --output-candidate was not specified. "
                "The prepared candidate was not written to disk.",
                file=sys.stderr,
            )
    else:
        print(
            f"No prepared candidate produced: {recipe['candidate_output']['reason_not_produced']}",
            file=sys.stderr,
        )

    print(json.dumps(recipe, indent=2, ensure_ascii=False))
