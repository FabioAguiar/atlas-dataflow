"""
Dataset discovery evidence generator for atlas-dataflow M22-02.

Reads a CSV dataset from an explicit input path and computes objective observations:
schema, inferred types, null counts, cardinality, sample bounds, duplicated rows,
candidate categorical fields, and candidate target columns.

Boundaries enforced by this module:
- dataset_input_path is required; no implicit local paths or notebook state.
- Output is deterministic for the same input and seed.
- No contract promotion, model training, or release publication is performed.
- Raw dataset content is not persisted; only aggregate statistics are recorded.
- Candidate target columns are flagged non-authoritative; no automatic selection occurs.

This module also exposes a small reusable helper surface (Project Spec S0012) for
dataset-authoring notebooks: repository-relative path resolution, explicit CSV
loading, structural summaries, per-field authoring observations, target/identifier
column summaries, and feature-candidate derivation. These helpers are independent
of the schema-governed `generate_discovery_evidence`/`write_discovery_evidence`
pair above and do not persist raw rows, secrets, logs, API payloads, model
binaries, release artifacts, or publisher artifacts.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


_GENERATOR_VERSION = "discovery-evidence.v1"
_CATEGORICAL_MAX_CARDINALITY = 20
_NULL_LIKE_TOKENS = {"na", "n/a", "nan", "null", "none"}
_REDUCED_SAMPLE_BOUND = 5

AUTHORING_HELPER_EVIDENCE_POLICY: dict[str, bool] = {
    "raw_rows_persisted": False,
    "secrets_persisted": False,
    "raw_runtime_logs_persisted": False,
    "raw_api_payloads_persisted": False,
    "model_binaries_persisted": False,
    "release_artifacts_persisted": False,
    "publisher_artifacts_persisted": False,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path(path: Path) -> str:
    return path.name


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _infer_type(values: list[str]) -> str:
    non_null = [v for v in values if v != ""]
    if not non_null:
        return "empty"

    def _is_bool(v: str) -> bool:
        return v.lower() in {"true", "false", "1", "0", "yes", "no"}

    def _is_int(v: str) -> bool:
        try:
            int(v)
            return True
        except (ValueError, TypeError):
            return False

    def _is_float(v: str) -> bool:
        try:
            float(v)
            return True
        except (ValueError, TypeError):
            return False

    if all(_is_bool(v) for v in non_null):
        return "boolean"
    if all(_is_int(v) for v in non_null):
        return "integer"
    if all(_is_float(v) for v in non_null):
        return "float"
    return "string"


def _observe_field(name: str, values: list[str], total_rows: int) -> dict[str, Any]:
    null_count = sum(1 for v in values if v == "")
    non_null = [v for v in values if v != ""]
    null_rate = null_count / total_rows if total_rows > 0 else 0.0
    cardinality = len(set(non_null))
    inferred_type = _infer_type(values)

    if not non_null:
        sample_min: Any = None
        sample_max: Any = None
    elif inferred_type == "integer":
        int_vals = [int(v) for v in non_null]
        sample_min = min(int_vals)
        sample_max = max(int_vals)
    elif inferred_type == "float":
        float_vals = [float(v) for v in non_null]
        sample_min = min(float_vals)
        sample_max = max(float_vals)
    else:
        sample_min = min(non_null)
        sample_max = max(non_null)

    return {
        "name": name,
        "inferred_type": inferred_type,
        "null_count": null_count,
        "null_rate": round(null_rate, 6),
        "cardinality": cardinality,
        "sample_min": sample_min,
        "sample_max": sample_max,
    }


def _count_duplicated_rows(rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    counts: dict[tuple, int] = {}
    for row in rows:
        key = tuple(sorted(row.items()))
        counts[key] = counts.get(key, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def generate_discovery_evidence(
    dataset_input_path: str | Path,
    seed: int = 0,
    generator_version: str = _GENERATOR_VERSION,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate a discovery evidence artifact from the specified CSV dataset.

    Parameters
    ----------
    dataset_input_path:
        Explicit path to the CSV dataset. Required; must not be None or empty.
    seed:
        Determinism seed embedded in generation_settings for traceability.
    generator_version:
        Version string embedded in generation_settings.
    generated_at:
        ISO 8601 timestamp override. Supply a fixed value to produce byte-identical
        output across runs. Defaults to UTC now when not supplied.
    """
    if not dataset_input_path:
        raise ValueError(
            "dataset_input_path is required and must not be empty or None."
        )

    path = Path(dataset_input_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found at the specified path: {path}"
        )

    rows = _read_csv(path)
    columns: list[str] = list(rows[0].keys()) if rows else []
    row_count = len(rows)
    col_count = len(columns)

    field_obs = [
        _observe_field(col, [r[col] for r in rows], row_count)
        for col in columns
    ]

    duplicated = _count_duplicated_rows(rows)

    candidate_categorical = [
        f["name"] for f in field_obs
        if f["inferred_type"] == "string"
        and 0 < f["cardinality"] <= _CATEGORICAL_MAX_CARDINALITY
    ]

    candidate_target_columns = [
        {
            "name": name,
            "is_authoritative": False,
            "candidate_reason": "low_cardinality_categorical_candidate",
        }
        for name in candidate_categorical
    ]

    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "producer": "pipeline/discovery_evidence.py",
        "dataset_metadata": {
            "name": path.stem,
            "row_count": row_count,
            "column_count": col_count,
            "source_path": _reduced_path(path),
        },
        "field_observations": field_obs,
        "duplicated_rows_count": duplicated,
        "candidate_categorical_fields": candidate_categorical,
        "candidate_target_columns": candidate_target_columns,
        "generation_settings": {
            "seed": seed,
            "generator_version": generator_version,
        },
        "generated_at": generated_at or _utc_now_iso(),
        "discovery_boundary_confirmations": {
            "contract_promotion_occurred": False,
            "model_training_occurred": False,
            "release_publication_occurred": False,
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


def write_discovery_evidence(
    output_path: str | Path,
    evidence: dict[str, Any],
    repo_root: str | Path,
) -> None:
    """Validate evidence against schema and write it to a JSON file."""
    schema_path = Path(repo_root) / "pipeline" / "dataset-discovery-evidence.schema.json"
    try:
        import jsonschema
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(evidence, schema)
    except ImportError:
        pass
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Discovery evidence schema not found: {schema_path}"
        ) from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Reusable dataset-authoring helpers (Project Spec S0012)
#
# Callable from dataset-authoring notebooks, including notebooks nested under
# notebooks/datasets/<slug>/. These helpers are deliberately independent of
# the schema-governed generate_discovery_evidence()/write_discovery_evidence()
# artifact above: they return plain dicts/lists for notebook-side use and are
# not validated against dataset-discovery-evidence.schema.json.
# ---------------------------------------------------------------------------


def resolve_repository_path(relative_path: str | Path, repo_root: str | Path | None = None) -> Path:
    """Resolve a repository-relative path against an explicit or default repo root.

    `repo_root` defaults to the current working directory, which is the
    expected convention for notebooks run from the repository root. Pass an
    explicit `repo_root` when the caller (for example a nested notebook, or
    papermill) cannot rely on the current working directory.
    """
    base = Path(repo_root) if repo_root else Path.cwd()
    return (base / relative_path).resolve()


def load_dataset_csv(path: str | Path) -> list[dict[str, str]]:
    """Load a CSV dataset from an explicit path.

    Raises FileNotFoundError if the path does not exist. Does not persist or
    return raw rows anywhere other than the caller's own memory.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset not found at: {csv_path}")
    return _read_csv(csv_path)


def summarize_structure(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    """Return row count, column count, and the ordered column list for rows."""
    ordered_columns = list(rows[0].keys()) if rows else []
    return {
        "row_count": len(rows),
        "column_count": len(ordered_columns),
        "ordered_columns": ordered_columns,
    }


def _is_null_like(value: str) -> bool:
    return value.strip().lower() in _NULL_LIKE_TOKENS


def observe_authoring_field(
    name: str,
    values: Sequence[str],
    sample_bound: int = _REDUCED_SAMPLE_BOUND,
) -> dict[str, Any]:
    """Return an authoring-time observation for a single field's raw string values.

    Distinguishes blank strings (empty or whitespace-only, e.g. "" or " ")
    from other null-like tokens (e.g. "NA", "N/A", "NaN", "null", "None") and
    reports a reduced, bounded sample of distinct observed values rather than
    the full column.
    """
    non_blank = [v for v in values if v.strip() != ""]
    blank_string_count = len(values) - len(non_blank)
    null_like_count = sum(1 for v in non_blank if _is_null_like(v))
    non_null_like = [v for v in non_blank if not _is_null_like(v)]
    cardinality = len(set(non_null_like))
    reduced_sample_values = sorted(set(non_null_like))[:sample_bound]

    return {
        "name": name,
        "inferred_type": _infer_type(non_blank),
        "blank_string_count": blank_string_count,
        "null_like_count": null_like_count,
        "cardinality": cardinality,
        "reduced_sample_values": reduced_sample_values,
    }


def observe_authoring_fields(
    rows: Sequence[dict[str, str]],
    columns: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return authoring-time field observations for the given rows and columns."""
    if columns is None:
        columns = list(rows[0].keys()) if rows else []
    return [
        observe_authoring_field(column, [row[column] for row in rows])
        for column in columns
    ]


def summarize_target_column(rows: Sequence[dict[str, str]], target_column: str) -> dict[str, Any]:
    """Return an explicit, non-authoritative summary of a supplied target column."""
    values = [row[target_column] for row in rows]
    return {
        "target_column": target_column,
        "observed_labels": sorted(set(values)),
        "observed_distribution": dict(Counter(values)),
        "is_authoritative": False,
    }


def summarize_identifier_columns(
    rows: Sequence[dict[str, str]],
    identifier_columns: Iterable[str],
) -> list[dict[str, Any]]:
    """Return an explicit summary of supplied identifier candidate columns."""
    summaries = []
    for column in identifier_columns:
        values = [row[column] for row in rows]
        unique_count = len(set(values))
        summaries.append({
            "name": column,
            "row_count": len(values),
            "unique_count": unique_count,
            "is_unique_per_row": unique_count == len(values),
        })
    return summaries


def derive_feature_candidates(
    columns: Iterable[str],
    target_column: str | None = None,
    identifier_columns: Iterable[str] | None = None,
) -> list[str]:
    """Return feature-candidate columns, excluding the target and identifier columns."""
    excluded = set(identifier_columns or [])
    if target_column:
        excluded.add(target_column)
    return [column for column in columns if column not in excluded]


def authoring_helper_evidence_policy() -> dict[str, bool]:
    """Return the reduced evidence policy confirmation for the authoring helpers.

    All flags are False: these helpers never persist raw rows, secrets, raw
    runtime logs, raw API payloads, model binaries, release artifacts, or
    publisher artifacts.
    """
    return dict(AUTHORING_HELPER_EVIDENCE_POLICY)
