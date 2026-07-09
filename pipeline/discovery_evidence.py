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

It also exposes `build_dataset_modeling_intent` (Project Spec S0013), a
deterministic builder for a narrow `dataset_modeling_intent.v1` authoring
contract assembled from already-observed values. This is an authoring-intent
object only, not an execution contract, runtime contract, public contract,
release candidate input, publisher input, registry artifact, API fixture, or
UI fixture.
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

_REPOSITORY_ROOT_MARKERS = (
    "README.md",
    "pipeline/discovery_evidence.py",
)


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


def _looks_like_repository_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in _REPOSITORY_ROOT_MARKERS)


def resolve_repository_root(start_path: str | Path | None = None) -> Path:
    """Resolve the Atlas repository root from an explicit path or the cwd.

    This helper is intentionally local and deterministic: it walks upward from
    `start_path`, the current working directory, and finally this module's
    installed/editable file location, requiring repository-local marker files.
    It does not inspect Jupyter server state, environment names, kernels, or
    global Python configuration.
    """
    start = Path(start_path).expanduser() if start_path is not None else Path.cwd()
    cursor = start.resolve()
    if cursor.is_file():
        cursor = cursor.parent

    module_cursor = Path(__file__).resolve().parent
    search_roots = (cursor, module_cursor)
    seen: set[Path] = set()
    for root in search_roots:
        for candidate in (root, *root.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _looks_like_repository_root(candidate):
                return candidate

    markers = ", ".join(_REPOSITORY_ROOT_MARKERS)
    raise FileNotFoundError(
        "Atlas repository root could not be resolved from "
        f"{cursor}. Expected to find repository markers: {markers}. "
        "Pass an explicit repo_root from a notebook first cell after locating "
        "the atlas-dataflow checkout."
    )


def resolve_repository_path(relative_path: str | Path, repo_root: str | Path | None = None) -> Path:
    """Resolve a repository-relative path against an explicit or default repo root.

    `repo_root` defaults to the resolved Atlas repository root, including when
    this module is imported through an editable install from a neutral current
    working directory. Pass an explicit `repo_root` to override that behavior.
    """
    base = Path(repo_root) if repo_root else resolve_repository_root()
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


# ---------------------------------------------------------------------------
# Dataset modeling intent (Project Spec S0013)
#
# A narrow authoring-level `dataset_modeling_intent.v1` contract, built from
# already-computed authoring observations (see the S0012 helpers above). This
# is deliberately not an execution contract, runtime contract, public
# contract, release candidate input, publisher input, registry artifact, API
# fixture, or UI fixture — it only records reviewed authoring intent for a
# later, separately authorized execution-contract draft projection spec.
# ---------------------------------------------------------------------------

_MODELING_INTENT_CONTRACT_VERSION = "dataset_modeling_intent.v1"
_MODELING_INTENT_DEFAULT_TYPE_INTENT = "requires_review"

MODELING_INTENT_BOUNDARY_CONFIRMATIONS: dict[str, bool] = {
    "is_execution_contract": False,
    "is_runtime_contract": False,
    "is_public_contract": False,
    "is_release_candidate_input": False,
    "is_publisher_input": False,
    "is_registry_artifact": False,
    "is_api_fixture": False,
    "is_ui_fixture": False,
    "model_training_performed": False,
}


def build_dataset_modeling_intent(
    dataset_slug: str,
    dataset_source_ref: str,
    authoring_notebook_ref: str,
    columns: Sequence[str],
    target_column: str,
    task_type: str,
    observed_labels: Iterable[str],
    positive_label_candidate: str,
    observed_target_distribution: dict[str, int],
    identifier_columns: Sequence[str],
    feature_review_notes: dict[str, str] | None = None,
    feature_type_intent_overrides: dict[str, str] | None = None,
    blank_value_policy_candidates: dict[str, str] | None = None,
    metric_candidates: Sequence[str] | None = None,
    split_policy_candidate: dict[str, Any] | None = None,
    open_questions: Sequence[str] | None = None,
    reduced_discovery_evidence_ref: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a `dataset_modeling_intent.v1` authoring-intent object.

    Deterministic and notebook-callable without requiring Jupyter execution:
    every input is an explicit, already-observed value (for example from the
    `summarize_target_column`/`summarize_identifier_columns`/
    `derive_feature_candidates` helpers above), not raw dataset rows. Initial
    feature candidates are always derived as non-target, non-identifier
    columns via `derive_feature_candidates`; a column's coarse type intent
    defaults to `"requires_review"` unless explicitly overridden, so ambiguous
    fields are never silently coerced.
    """
    feature_candidates = derive_feature_candidates(
        columns, target_column=target_column, identifier_columns=identifier_columns
    )

    feature_type_intent_overrides = dict(feature_type_intent_overrides or {})
    feature_type_intent = [
        {
            "name": name,
            "type_intent": feature_type_intent_overrides.get(
                name, _MODELING_INTENT_DEFAULT_TYPE_INTENT
            ),
        }
        for name in feature_candidates
    ]

    return {
        "artifact_type": "dataset_modeling_intent",
        "contract_version": _MODELING_INTENT_CONTRACT_VERSION,
        "dataset_identity": {
            "dataset_slug": dataset_slug,
            "dataset_source_ref": dataset_source_ref,
        },
        "authoring_source": {
            "authoring_notebook_ref": authoring_notebook_ref,
            "reduced_discovery_evidence_ref": reduced_discovery_evidence_ref,
        },
        "target_intent": {
            "target_column": target_column,
            "task_type": task_type,
            "observed_labels": sorted(observed_labels),
            "positive_label_candidate": positive_label_candidate,
            "observed_target_distribution": dict(observed_target_distribution),
            "is_final_training_configuration": False,
        },
        "identifier_and_ignored_columns": [
            {"name": name, "reason": "identifier_candidate_excluded_from_features"}
            for name in identifier_columns
        ],
        "initial_feature_candidates": feature_candidates,
        "feature_review_notes": dict(feature_review_notes or {}),
        "feature_type_intent": feature_type_intent,
        "blank_value_policy_candidates": dict(blank_value_policy_candidates or {}),
        "metric_candidates": list(metric_candidates or []),
        "split_policy_candidate": split_policy_candidate,
        "open_questions": list(open_questions or []),
        "modeling_intent_boundary_confirmations": dict(
            MODELING_INTENT_BOUNDARY_CONFIRMATIONS
        ),
        "generated_at": generated_at or _utc_now_iso(),
    }
