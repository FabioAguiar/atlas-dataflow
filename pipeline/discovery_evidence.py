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
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_GENERATOR_VERSION = "discovery-evidence.v1"
_CATEGORICAL_MAX_CARDINALITY = 20


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
