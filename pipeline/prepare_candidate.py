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
_PREPARED_DATA_METADATA_SCHEMA_VERSION = "prepared-data-metadata.v1"
_APPLICABLE_STATUSES = ("explicit", "inferred_approved")
_REVIEW_STATUSES = ("explicit", "inferred_pending_review", "inferred_approved")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path(path: Path) -> str:
    return path.name


def _repository_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
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


def _normalize_transformation_record(record: dict[str, Any]) -> dict[str, Any]:
    required = {
        "transformation_type",
        "description",
        "source_columns",
        "target_columns",
        "reason",
        "review_status",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"Preparation transformation missing required fields: {missing}")

    review_status = record["review_status"]
    if review_status not in _REVIEW_STATUSES:
        raise ValueError(
            "Preparation transformation review_status must be one of "
            f"{list(_REVIEW_STATUSES)}; got {review_status!r}."
        )

    return {
        "transformation_type": record["transformation_type"],
        "description": record["description"],
        "source_columns": list(record["source_columns"]),
        "target_columns": list(record["target_columns"]),
        "reason": record["reason"],
        "review_status": review_status,
    }


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


def build_review_only_preparation_recipe(
    discovery_evidence_path: str | Path,
    dataset_input_path: str | Path,
    transformations: list[dict[str, Any]],
    preparation_rules_source: str,
    generated_at: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a schema-aligned recipe that records review rules without applying them.

    This helper is intended for authoring/materialization stages where inferred
    concerns need durable evidence but no transformation has been approved. It
    never writes a prepared candidate and never mutates the input rows.
    """
    discovery_evidence_path = Path(discovery_evidence_path)
    dataset_input_path = Path(dataset_input_path)
    resolved_repo_root = Path(repo_root).resolve() if repo_root is not None else None

    if not discovery_evidence_path.exists():
        raise FileNotFoundError(f"Discovery evidence not found: {discovery_evidence_path}")
    if not dataset_input_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_input_path}")
    if not preparation_rules_source or Path(preparation_rules_source).is_absolute():
        raise ValueError("preparation_rules_source must be a non-empty reduced path reference.")

    discovery_evidence = json.loads(
        discovery_evidence_path.read_text(encoding="utf-8")
    )
    columns, rows = _read_csv(dataset_input_path)
    normalized_transformations = [
        _normalize_transformation_record(record) for record in transformations
    ]
    applicable_count = sum(
        1
        for transformation in normalized_transformations
        if transformation["review_status"] in _APPLICABLE_STATUSES
    )

    if applicable_count:
        reason_not_produced = (
            "Review-only recipe materialization does not apply transformations. "
            f"{applicable_count} approved rule(s) were supplied but no candidate output "
            "was produced by this authoring boundary."
        )
    else:
        pending_count = sum(
            1
            for transformation in normalized_transformations
            if transformation["review_status"] == "inferred_pending_review"
        )
        reason_not_produced = (
            "No transformation rules with review_status 'explicit' or "
            f"'inferred_approved' were applied. {pending_count} inferred rule(s) "
            "are pending human review and cannot be applied without explicit approval."
        )

    discovery_ref_path = _reduced_path(discovery_evidence_path)
    dataset_name = _reduced_path(dataset_input_path)
    if resolved_repo_root is not None:
        discovery_ref_path = _repository_relative_path(
            discovery_evidence_path,
            resolved_repo_root,
        )
        dataset_name = _repository_relative_path(dataset_input_path, resolved_repo_root)

    return {
        "schema_version": _SCHEMA_VERSION,
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {
            "name": dataset_name,
            "row_count_before": len(rows),
            "column_count_before": len(columns),
        },
        "discovery_evidence_ref": {
            "path": discovery_ref_path,
            "schema_version": discovery_evidence.get("schema_version", "unknown"),
        },
        "transformations": normalized_transformations,
        "candidate_output": {
            "produced": False,
            "reason_not_produced": reason_not_produced,
            "row_count_after": None,
            "column_count_after": None,
        },
        "candidate_status": {
            "is_final_training_input": False,
            "requires_m23_validation": True,
            "authorized_for": "candidate_only",
        },
        "generation_settings": {
            "generator_version": _GENERATOR_VERSION,
            "preparation_rules_source": preparation_rules_source,
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


def materialize_review_only_preparation_recipe(
    discovery_evidence_relative_path: str | Path,
    dataset_relative_path: str | Path,
    output_relative_path: str | Path,
    transformations: list[dict[str, Any]],
    preparation_rules_source: str,
    repo_root: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build, validate, and write a review-only preparation recipe."""
    resolved_repo_root = Path(repo_root).expanduser().resolve()
    discovery_evidence_path = (resolved_repo_root / discovery_evidence_relative_path).resolve()
    dataset_input_path = (resolved_repo_root / dataset_relative_path).resolve()
    output_path = (resolved_repo_root / output_relative_path).resolve()

    recipe = build_review_only_preparation_recipe(
        discovery_evidence_path=discovery_evidence_path,
        dataset_input_path=dataset_input_path,
        transformations=transformations,
        preparation_rules_source=preparation_rules_source,
        generated_at=generated_at,
        repo_root=resolved_repo_root,
    )
    write_preparation_recipe(output_path, recipe, resolved_repo_root)
    return recipe


def _is_blank_value(value: str | None) -> bool:
    """True for null, empty-string, or whitespace-only values."""
    return value is None or str(value).strip() == ""


def verify_and_apply_conditional_fill(
    rows: list[dict[str, str]],
    column: str,
    verification_column: str,
    verification_value: str,
    fill_value: str,
) -> tuple[list[dict[str, str]] | None, bool, int]:
    """Fill blank/whitespace-only `column` values with `fill_value`, but only
    when every row with a blank `column` value has `verification_column`
    numerically equal to `verification_value`.

    This never drops rows, never applies a broad imputation strategy (mean,
    median, mode, or model-based), and never creates a missing-value
    indicator column. Non-blank `column` values are also normalized to a
    float string representation, since this rule's transformation type is
    missing-value handling plus numeric normalization.

    Returns `(filled_rows, True, 0)` when verification passes for every
    blank row, or `(None, False, failing_row_count)` when at least one blank
    row fails verification (a non-matching or non-numeric
    `verification_column` value). The caller must treat a failed
    verification as a block: no candidate rows, no partial fill.
    """
    failing_row_count = 0
    for row in rows:
        if not _is_blank_value(row.get(column)):
            continue
        verify_cell = row.get(verification_column)
        try:
            verify_ok = verify_cell is not None and float(verify_cell) == float(verification_value)
        except (TypeError, ValueError):
            verify_ok = False
        if not verify_ok:
            failing_row_count += 1

    if failing_row_count:
        return None, False, failing_row_count

    filled_rows: list[dict[str, str]] = []
    for row in rows:
        row = dict(row)
        if _is_blank_value(row.get(column)):
            row[column] = str(float(fill_value))
        else:
            row[column] = str(float(row[column]))
        filled_rows.append(row)
    return filled_rows, True, 0


def build_verified_conditional_fill_preparation_recipe(
    discovery_evidence_path: str | Path,
    dataset_input_path: str | Path,
    column: str,
    verification_column: str,
    verification_value: str,
    fill_value: str,
    description: str,
    reason: str,
    preparation_rules_source: str,
    generated_at: str | None = None,
    repo_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str] | None, list[dict[str, str]] | None]:
    """Build a schema-aligned recipe for an explicit, approved missing-value
    policy that requires cross-column verification before any fill is
    applied (for example: Project Spec S0028's TotalCharges policy).

    Unlike `build_review_only_preparation_recipe`, the recorded
    transformation carries `review_status: "inferred_approved"` (the closest
    existing accepted status for a rule that was originally inferred from
    discovery evidence and has since been approved) and, when verification
    passes, `candidate_output.produced` is `True` with the filled rows
    returned to the caller. Writing those rows to a prepared-candidate CSV
    on disk is a separate, explicit step (`write_candidate_output`) left to
    the caller, so this function never persists a prepared dataset file by
    itself.

    When verification fails for any blank row, no rows are dropped, imputed,
    or partially filled -- `candidate_output.produced` is `False`, the
    reason names only the count of failing rows (never raw row content), and
    the returned columns/rows are `None`.
    """
    discovery_evidence_path = Path(discovery_evidence_path)
    dataset_input_path = Path(dataset_input_path)
    resolved_repo_root = Path(repo_root).resolve() if repo_root is not None else None

    if not discovery_evidence_path.exists():
        raise FileNotFoundError(f"Discovery evidence not found: {discovery_evidence_path}")
    if not dataset_input_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_input_path}")
    if not preparation_rules_source or Path(preparation_rules_source).is_absolute():
        raise ValueError("preparation_rules_source must be a non-empty reduced path reference.")

    discovery_evidence = json.loads(discovery_evidence_path.read_text(encoding="utf-8"))
    columns, rows = _read_csv(dataset_input_path)
    row_count_before = len(rows)
    col_count_before = len(columns)

    filled_rows, verification_passed, failing_row_count = verify_and_apply_conditional_fill(
        rows,
        column=column,
        verification_column=verification_column,
        verification_value=verification_value,
        fill_value=fill_value,
    )

    transformation = _normalize_transformation_record({
        "transformation_type": "missing_value_handling",
        "description": description,
        "source_columns": [column],
        "target_columns": [column],
        "reason": reason,
        "review_status": "inferred_approved",
    })

    output_columns: list[str] | None = None
    output_rows: list[dict[str, str]] | None = None

    if verification_passed:
        candidate_produced = True
        reason_not_produced = None
        row_count_after = row_count_before
        column_count_after = col_count_before
        output_columns = columns
        output_rows = filled_rows
    else:
        candidate_produced = False
        reason_not_produced = (
            f"Preparation blocked: {failing_row_count} row(s) with a blank or "
            f"whitespace-only '{column}' value failed verification against "
            f"'{verification_column}' == {verification_value}. The approved policy "
            f"requires every blank '{column}' row to satisfy this verification before "
            "any fill is applied; no rows were dropped, imputed, or filled, and no "
            "prepared candidate was produced."
        )
        row_count_after = None
        column_count_after = None

    discovery_ref_path = _reduced_path(discovery_evidence_path)
    dataset_name = _reduced_path(dataset_input_path)
    if resolved_repo_root is not None:
        discovery_ref_path = _repository_relative_path(discovery_evidence_path, resolved_repo_root)
        dataset_name = _repository_relative_path(dataset_input_path, resolved_repo_root)

    recipe: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {
            "name": dataset_name,
            "row_count_before": row_count_before,
            "column_count_before": col_count_before,
        },
        "discovery_evidence_ref": {
            "path": discovery_ref_path,
            "schema_version": discovery_evidence.get("schema_version", "unknown"),
        },
        "transformations": [transformation],
        "candidate_output": {
            "produced": candidate_produced,
            "reason_not_produced": reason_not_produced,
            "row_count_after": row_count_after,
            "column_count_after": column_count_after,
        },
        "candidate_status": {
            "is_final_training_input": False,
            "requires_m23_validation": True,
            "authorized_for": "candidate_only",
        },
        "generation_settings": {
            "generator_version": _GENERATOR_VERSION,
            "preparation_rules_source": preparation_rules_source,
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

    return recipe, output_columns, output_rows


def materialize_verified_conditional_fill_preparation_recipe(
    discovery_evidence_relative_path: str | Path,
    dataset_relative_path: str | Path,
    output_relative_path: str | Path,
    column: str,
    verification_column: str,
    verification_value: str,
    fill_value: str,
    description: str,
    reason: str,
    preparation_rules_source: str,
    repo_root: str | Path,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], list[str] | None, list[dict[str, str]] | None]:
    """Build, validate, and write a verified-conditional-fill preparation
    recipe from explicit repository-relative inputs. Resolves every path
    against `repo_root`, so the call is correct regardless of the caller's
    working directory (for example a notebook running from a nested dataset
    directory). Never writes a prepared-candidate CSV -- see
    `write_candidate_output` for that separate, explicit step."""
    resolved_repo_root = Path(repo_root).expanduser().resolve()
    discovery_evidence_path = (resolved_repo_root / discovery_evidence_relative_path).resolve()
    dataset_input_path = (resolved_repo_root / dataset_relative_path).resolve()
    output_path = (resolved_repo_root / output_relative_path).resolve()

    recipe, output_columns, output_rows = build_verified_conditional_fill_preparation_recipe(
        discovery_evidence_path=discovery_evidence_path,
        dataset_input_path=dataset_input_path,
        column=column,
        verification_column=verification_column,
        verification_value=verification_value,
        fill_value=fill_value,
        description=description,
        reason=reason,
        preparation_rules_source=preparation_rules_source,
        generated_at=generated_at,
        repo_root=resolved_repo_root,
    )
    write_preparation_recipe(output_path, recipe, resolved_repo_root)
    return recipe, output_columns, output_rows


def _content_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_prepared_data_metadata(
    dataset_slug: str,
    raw_dataset_relative_path: str,
    discovery_evidence_path: str | Path,
    preparation_recipe_path: str | Path,
    prepared_candidate_path: str | Path | None = None,
    generated_at: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a reduced `prepared-data-metadata.v1` object from explicit inputs.

    Reads only the discovery evidence and preparation recipe artifacts (plus
    the prepared candidate file's header/row count, when a candidate file is
    supplied and exists) to describe the prepared-candidate boundary and its
    provenance. Never reads raw dataset rows beyond the prepared candidate's
    own header/row count, never depends on notebook variables or hidden
    global state, and never claims training readiness when unresolved
    preparation review items remain or no prepared candidate was produced.
    """
    discovery_evidence_path = Path(discovery_evidence_path)
    preparation_recipe_path = Path(preparation_recipe_path)
    resolved_repo_root = Path(repo_root).resolve() if repo_root is not None else None

    if not discovery_evidence_path.exists():
        raise FileNotFoundError(f"Discovery evidence not found: {discovery_evidence_path}")
    if not preparation_recipe_path.exists():
        raise FileNotFoundError(f"Preparation recipe not found: {preparation_recipe_path}")

    discovery_evidence = json.loads(discovery_evidence_path.read_text(encoding="utf-8"))
    preparation_recipe = json.loads(preparation_recipe_path.read_text(encoding="utf-8"))

    dataset_metadata = discovery_evidence.get("dataset_metadata", {})
    candidate_output = preparation_recipe.get("candidate_output", {})
    transformations = preparation_recipe.get("transformations", [])

    applied_transformations = [
        t for t in transformations if t.get("review_status") in _APPLICABLE_STATUSES
    ]
    unresolved_review_items = [
        t for t in transformations if t.get("review_status") == "inferred_pending_review"
    ]

    candidate_produced = bool(candidate_output.get("produced"))

    resolved_candidate_path = (
        Path(prepared_candidate_path) if prepared_candidate_path is not None else None
    )
    ordered_prepared_columns: list[str] | None = None
    prepared_candidate_ref: dict[str, Any] | None = None

    if candidate_produced and resolved_candidate_path is not None and resolved_candidate_path.exists():
        candidate_columns, candidate_rows = _read_csv(resolved_candidate_path)
        ordered_prepared_columns = candidate_columns
        candidate_ref_path = _reduced_path(resolved_candidate_path)
        if resolved_repo_root is not None:
            candidate_ref_path = _repository_relative_path(
                resolved_candidate_path, resolved_repo_root
            )
        prepared_candidate_ref = {
            "path": candidate_ref_path,
            "row_count": len(candidate_rows),
            "column_count": len(candidate_columns),
            "content_sha256": _content_sha256(resolved_candidate_path),
        }

    is_training_ready = bool(
        candidate_produced and not unresolved_review_items and prepared_candidate_ref is not None
    )
    if is_training_ready:
        training_readiness_reason = None
    elif not candidate_produced:
        training_readiness_reason = (
            "No prepared candidate has been produced yet: "
            f"{candidate_output.get('reason_not_produced') or 'no approved transformations exist.'}"
        )
    elif unresolved_review_items:
        training_readiness_reason = (
            f"{len(unresolved_review_items)} preparation review item(s) remain "
            "unresolved (review_status 'inferred_pending_review')."
        )
    else:
        training_readiness_reason = (
            "Prepared candidate output was marked produced but no readable candidate "
            "file reference was supplied."
        )

    discovery_ref_path = _reduced_path(discovery_evidence_path)
    recipe_ref_path = _reduced_path(preparation_recipe_path)
    if resolved_repo_root is not None:
        discovery_ref_path = _repository_relative_path(
            discovery_evidence_path, resolved_repo_root
        )
        recipe_ref_path = _repository_relative_path(preparation_recipe_path, resolved_repo_root)

    return {
        "schema_version": _PREPARED_DATA_METADATA_SCHEMA_VERSION,
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {
            "dataset_slug": dataset_slug,
            "raw_dataset_ref": {"path": raw_dataset_relative_path},
        },
        "source_references": {
            "discovery_evidence_ref": {
                "path": discovery_ref_path,
                "schema_version": discovery_evidence.get("schema_version", "unknown"),
            },
            "preparation_recipe_ref": {
                "path": recipe_ref_path,
                "schema_version": preparation_recipe.get("schema_version", "unknown"),
            },
        },
        "prepared_candidate": {
            "produced": candidate_produced,
            "reason_not_produced": candidate_output.get("reason_not_produced"),
            "reference": prepared_candidate_ref,
        },
        "row_column_counts": {
            "row_count_before": dataset_metadata.get("row_count"),
            "column_count_before": dataset_metadata.get("column_count"),
            "row_count_after": candidate_output.get("row_count_after"),
            "column_count_after": candidate_output.get("column_count_after"),
        },
        "ordered_prepared_columns": ordered_prepared_columns,
        "applied_transformations_summary": applied_transformations,
        "unresolved_review_items": unresolved_review_items,
        "training_readiness": {
            "is_final_training_input": False,
            "is_training_ready": is_training_ready,
            "reason": training_readiness_reason,
        },
        "generation_settings": {
            "generator_version": _GENERATOR_VERSION,
        },
        "generated_at": generated_at or _utc_now_iso(),
        "materialization_boundary_confirmations": {
            "model_training_performed": False,
            "release_candidate_assembly_performed": False,
            "publisher_operation_performed": False,
            "registry_mutation_performed": False,
            "api_mutation_performed": False,
            "ui_mutation_performed": False,
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


def materialize_prepared_data_metadata(
    dataset_slug: str,
    raw_dataset_relative_path: str,
    discovery_evidence_relative_path: str | Path,
    preparation_recipe_relative_path: str | Path,
    output_relative_path: str | Path,
    repo_root: str | Path,
    prepared_candidate_relative_path: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build, then write, a `prepared-data-metadata.v1` object from explicit
    repository-relative inputs. Resolves every path against `repo_root` so
    the call is correct regardless of the caller's working directory (e.g. a
    notebook running from a nested dataset directory)."""
    resolved_repo_root = Path(repo_root).expanduser().resolve()
    discovery_evidence_path = (resolved_repo_root / discovery_evidence_relative_path).resolve()
    preparation_recipe_path = (resolved_repo_root / preparation_recipe_relative_path).resolve()
    output_path = (resolved_repo_root / output_relative_path).resolve()

    prepared_candidate_path: Path | None = None
    if prepared_candidate_relative_path is not None:
        candidate_path = (resolved_repo_root / prepared_candidate_relative_path).resolve()
        if candidate_path.exists():
            prepared_candidate_path = candidate_path

    metadata = build_prepared_data_metadata(
        dataset_slug=dataset_slug,
        raw_dataset_relative_path=raw_dataset_relative_path,
        discovery_evidence_path=discovery_evidence_path,
        preparation_recipe_path=preparation_recipe_path,
        prepared_candidate_path=prepared_candidate_path,
        generated_at=generated_at,
        repo_root=resolved_repo_root,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


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
