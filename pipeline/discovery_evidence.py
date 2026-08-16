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

It also exposes `materialize_dataset_modeling_intent` (Project Spec S0023),
which persists an already-built `dataset_modeling_intent.v1` object to a
repository-relative path, enriched with explicit upstream artifact
traceability (discovery evidence, preparation recipe, prepared dataset
metadata, public context references) and the reduced evidence policy. It
reads only those named upstream artifacts, only when their relative path is
supplied and the file exists on disk, and never treats a preparation
recipe's `inferred_pending_review` transformation as resolved.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


_GENERATOR_VERSION = "discovery-evidence.v1"
_CATEGORICAL_MAX_CARDINALITY = 20
_NULL_LIKE_TOKENS = {"na", "n/a", "nan", "null", "none"}
_REDUCED_SAMPLE_BOUND = 5

# Canonical dataset-integration notebook selected by S0162/S0169/S0179/S0184.
# This is traceability metadata only: discovery remains dataset-agnostic and
# never imports or executes the notebook.
CANONICAL_DATASET_INTEGRATION_AUTHORING_NOTEBOOK = (
    "notebooks/datasets/telco-customer-churn/"
    "dataset_integration.ipynb"
)

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


def canonical_dataset_integration_authoring_notebook_ref() -> str:
    """Return the current Telco authoring entrypoint as a portable repo ref.

    Keeping this path in discovery traceability does not make the generic
    discovery or projection pipeline branch on a dataset name.
    """
    return CANONICAL_DATASET_INTEGRATION_AUTHORING_NOTEBOOK


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _reduced_path(path: Path) -> str:
    return path.name


def _repository_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _is_blank_value(value: str) -> bool:
    return value.strip() == ""


def _infer_type(values: list[str]) -> str:
    non_null = [v.strip() for v in values if not _is_blank_value(v)]
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
    null_count = sum(1 for v in values if _is_blank_value(v))
    non_null = [v.strip() for v in values if not _is_blank_value(v)]
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
        if f["inferred_type"] in {"boolean", "string"}
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


def materialize_discovery_evidence(
    dataset_relative_path: str | Path,
    output_relative_path: str | Path,
    repo_root: str | Path | None = None,
    dataset_slug: str | None = None,
    seed: int = 0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate, validate, and write discovery evidence using repo-relative paths."""
    resolved_repo_root = resolve_repository_root(repo_root)
    dataset_path = resolve_repository_path(dataset_relative_path, resolved_repo_root)
    output_path = resolve_repository_path(output_relative_path, resolved_repo_root)

    evidence = generate_discovery_evidence(
        dataset_path,
        seed=seed,
        generated_at=generated_at,
    )
    evidence["dataset_metadata"]["name"] = dataset_slug or Path(dataset_relative_path).stem
    evidence["dataset_metadata"]["source_path"] = _repository_relative_path(
        dataset_path,
        resolved_repo_root,
    )

    write_discovery_evidence(output_path, evidence, resolved_repo_root)
    return evidence


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

# Project Spec S0102: recognised review statuses for a single reviewed
# categorical-domain declaration. "approved" is the only status that may be
# promoted into execution policy by contract_derivation._build_execution_contract;
# "pending_review" keeps a declaration visible as an unresolved review item
# without ever silently becoming an accepted inference domain.
CATEGORICAL_DOMAIN_REVIEW_STATUSES = frozenset({"approved", "pending_review"})


def build_categorical_domain_declaration(
    name: str,
    accepted_values: Sequence[str],
    review_status: str,
    source_basis: str,
    closed_for_inference: bool = True,
) -> dict[str, Any]:
    """Build a single reviewed categorical-domain declaration entry (Project Spec S0102).

    This is deliberately not the same thing as an observed/reduced sample --
    `accepted_values` here is asserted by the caller as the explicitly
    reviewed, canonical accepted domain for `name`, not merely whatever was
    observed in a dataset sample. Raises ValueError on a malformed
    declaration (missing name, unrecognised review_status, empty/blank/
    non-string/duplicate accepted_values) rather than silently accepting an
    ambiguous one. Approval to actually promote this declaration into
    execution policy is decided later, at execution-contract materialization,
    from `review_status == "approved"` alone -- this builder does not decide
    approval itself.
    """
    if not name or not isinstance(name, str):
        raise ValueError(
            "categorical domain declaration requires a non-empty string feature name"
        )
    if review_status not in CATEGORICAL_DOMAIN_REVIEW_STATUSES:
        raise ValueError(
            f"{name}: review_status must be one of "
            f"{sorted(CATEGORICAL_DOMAIN_REVIEW_STATUSES)}, got {review_status!r}"
        )
    values = list(accepted_values)
    if not values:
        raise ValueError(f"{name}: accepted_values must be non-empty")
    if any(not isinstance(v, str) or v.strip() == "" for v in values):
        raise ValueError(f"{name}: accepted_values must be non-blank strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{name}: accepted_values must not contain duplicate values")

    return {
        "name": name,
        "accepted_values": values,
        "review_status": review_status,
        "source_basis": source_basis,
        "closed_for_inference": bool(closed_for_inference),
    }


# Project Spec S0108: a single reviewed binary-result semantics declaration.
# "approved" is the only status that may be promoted into execution policy by
# contract_derivation._build_execution_contract; "pending_review" keeps a
# declaration visible as an unresolved review item without ever silently
# materializing into executable policy.
BINARY_RESULT_SEMANTICS_INTENT_CONTRACT_VERSION = "binary_result_semantics_intent.v1"
BINARY_RESULT_SEMANTICS_REVIEW_STATUSES = frozenset({"approved", "pending_review"})
_BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS = ("low", "medium", "high")


def _validate_binary_result_semantics_bands(bands: Any) -> list[dict[str, Any]]:
    """Validate and normalize the three required interpretation bands.

    Enforces the interval semantics required by Project Spec S0108: bands
    are exactly {low, medium, high} once each, finite and within [0, 1], the
    first lower_bound is 0, the final upper_bound is 1, and the bands are
    ordered, contiguous, with no gap or overlap
    (`lower_bound <= probability < upper_bound`, except the final band's
    upper bound 1.0 is inclusive).
    """
    if not isinstance(bands, (list, tuple)):
        raise ValueError(
            "interpretation.bands must be a list of band objects"
        )
    bands = list(bands)
    if len(bands) != 3:
        raise ValueError("interpretation.bands must contain exactly 3 bands")

    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for band in bands:
        if not isinstance(band, dict):
            raise ValueError("each band must be an object")
        band_id = band.get("band_id")
        if band_id not in _BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS:
            raise ValueError(
                f"band_id must be one of {_BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS}, "
                f"got {band_id!r}"
            )
        if band_id in seen_ids:
            raise ValueError(f"duplicate band_id: {band_id!r}")
        seen_ids.add(band_id)

        lower_bound = band.get("lower_bound")
        upper_bound = band.get("upper_bound")
        for field_name, value in (("lower_bound", lower_bound), ("upper_bound", upper_bound)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{band_id}.{field_name} must be a finite number")
            if not math.isfinite(value):
                raise ValueError(f"{band_id}.{field_name} must be finite")
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{band_id}.{field_name} must be within [0, 1]")
        if not (lower_bound < upper_bound):
            raise ValueError(f"{band_id}: lower_bound must be less than upper_bound")

        normalized.append({
            "band_id": band_id,
            "lower_bound": float(lower_bound),
            "upper_bound": float(upper_bound),
        })

    if seen_ids != set(_BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS):
        raise ValueError(
            f"bands must include exactly {_BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS} once each"
        )

    ordered = sorted(
        normalized,
        key=lambda entry: _BINARY_RESULT_SEMANTICS_REQUIRED_BAND_IDS.index(entry["band_id"]),
    )
    if ordered[0]["lower_bound"] != 0.0:
        raise ValueError("the first band (low) lower_bound must be 0")
    if ordered[-1]["upper_bound"] != 1.0:
        raise ValueError("the final band (high) upper_bound must be 1")
    for previous, current in zip(ordered, ordered[1:]):
        if current["lower_bound"] != previous["upper_bound"]:
            raise ValueError(
                "bands must be ordered and contiguous with no gap or overlap: "
                f"{previous['band_id']} upper_bound {previous['upper_bound']} must "
                f"equal {current['band_id']} lower_bound {current['lower_bound']}"
            )
    return ordered


def build_binary_result_semantics_intent(
    review_status: str,
    problem_type: str,
    positive_class_id: str,
    event_label: str,
    primary_output: str,
    threshold: float,
    preset: str,
    bands: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build a `binary_result_semantics_intent.v1` reviewed declaration (Project Spec S0108).

    Every value is an explicit caller-supplied parameter with no defaults --
    this builder never inserts illustrative/prototype values (for example the
    design prototype's Churn/0.5/0.35/0.65) automatically. Only
    `review_status == "approved"` may later be promoted into executable
    execution-contract policy by
    `contract_derivation._build_execution_contract`; `"pending_review"` keeps
    the declaration visible as an unresolved review item and this builder
    still returns it rather than raising, since a pending declaration is a
    normal, reportable state, not a malformed one. Raises ValueError on a
    structurally malformed declaration (bad problem_type/primary_output/
    preset, non-finite or out-of-range threshold, or bands that are missing,
    duplicated, gapped, overlapping, unordered, or not covering [0, 1]).
    """
    if review_status not in BINARY_RESULT_SEMANTICS_REVIEW_STATUSES:
        raise ValueError(
            f"review_status must be one of {sorted(BINARY_RESULT_SEMANTICS_REVIEW_STATUSES)}, "
            f"got {review_status!r}"
        )
    if problem_type != "binary_classification":
        raise ValueError(
            f"problem_type must be exactly 'binary_classification', got {problem_type!r}"
        )
    if not isinstance(positive_class_id, str) or not positive_class_id.strip():
        raise ValueError("positive_class.class_id must be a non-empty string")
    if not isinstance(event_label, str) or not event_label.strip():
        raise ValueError(
            "positive_class.event_label must be a non-empty, presentation-safe string"
        )
    if primary_output != "positive_class_probability":
        raise ValueError(
            f"primary_output must be exactly 'positive_class_probability', got {primary_output!r}"
        )
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("decision.threshold must be a finite number")
    if not math.isfinite(threshold):
        raise ValueError("decision.threshold must be finite")
    if not (0.0 <= threshold <= 1.0):
        raise ValueError("decision.threshold must be within [0, 1]")
    if preset != "risk":
        raise ValueError(f"interpretation.preset must be exactly 'risk', got {preset!r}")
    normalized_bands = _validate_binary_result_semantics_bands(bands)

    return {
        "schema_version": BINARY_RESULT_SEMANTICS_INTENT_CONTRACT_VERSION,
        "review_status": review_status,
        "problem_type": problem_type,
        "positive_class": {
            "class_id": positive_class_id,
            "event_label": event_label,
        },
        "primary_output": primary_output,
        "decision": {"threshold": float(threshold)},
        "interpretation": {
            "preset": preset,
            "bands": normalized_bands,
        },
    }


# Project Spec S0207: a single reviewed multiclass-result semantics
# declaration. "approved" is the only status that may be promoted into
# execution policy by
# contract_derivation._materialize_multiclass_result_semantics;
# "pending_review" keeps a declaration visible as an unresolved review item
# without ever silently materializing into executable policy. Mirrors the
# binary_result_semantics_intent review-status vocabulary/conventions above,
# but never owns or accepts a class list, threshold, or risk-band parameter
# -- the governed, ordered class declaration remains exclusively owned by
# dataset-semantic-intent.v2 and is sourced only at materialization time.
MULTICLASS_RESULT_SEMANTICS_INTENT_CONTRACT_VERSION = "multiclass_result_semantics_intent.v1"
MULTICLASS_RESULT_SEMANTICS_REVIEW_STATUSES = frozenset({"approved", "pending_review"})
_MULTICLASS_RESULT_SEMANTICS_PROBLEM_TYPE = "multiclass_classification"
_MULTICLASS_RESULT_SEMANTICS_PRIMARY_OUTPUT = "predicted_class"
_MULTICLASS_RESULT_SEMANTICS_PROBABILITY_OUTPUT = "class_probabilities"
_MULTICLASS_RESULT_SEMANTICS_DECISION_STRATEGY = "argmax"


def build_multiclass_result_semantics_intent(
    review_status: str,
    problem_type: str,
    primary_output: str,
    probability_output: str,
    decision_strategy: str,
    review_notes: str | None = None,
) -> dict[str, Any]:
    """Build a `multiclass_result_semantics_intent.v1` reviewed declaration (Project Spec S0207).

    Deliberately owns only result-behavior semantics -- no class list,
    threshold, or risk-band parameter is ever accepted here; the governed,
    ordered class declaration remains exclusively owned by
    dataset-semantic-intent.v2 and is sourced only at materialization time
    (see contract_derivation._materialize_multiclass_result_semantics). Only
    `review_status == "approved"` may later be promoted into executable
    execution-contract policy; `"pending_review"` keeps the declaration
    visible as an unresolved review item and this builder still returns it
    rather than raising, mirroring build_binary_result_semantics_intent's
    convention. Raises ValueError on a structurally malformed declaration
    (unknown review_status, wrong problem_type/primary_output/
    probability_output, or a decision_strategy other than 'argmax').
    """
    if review_status not in MULTICLASS_RESULT_SEMANTICS_REVIEW_STATUSES:
        raise ValueError(
            f"review_status must be one of {sorted(MULTICLASS_RESULT_SEMANTICS_REVIEW_STATUSES)}, "
            f"got {review_status!r}"
        )
    if problem_type != _MULTICLASS_RESULT_SEMANTICS_PROBLEM_TYPE:
        raise ValueError(
            f"problem_type must be exactly {_MULTICLASS_RESULT_SEMANTICS_PROBLEM_TYPE!r}, "
            f"got {problem_type!r}"
        )
    if primary_output != _MULTICLASS_RESULT_SEMANTICS_PRIMARY_OUTPUT:
        raise ValueError(
            f"primary_output must be exactly {_MULTICLASS_RESULT_SEMANTICS_PRIMARY_OUTPUT!r}, "
            f"got {primary_output!r}"
        )
    if probability_output != _MULTICLASS_RESULT_SEMANTICS_PROBABILITY_OUTPUT:
        raise ValueError(
            f"probability_output must be exactly {_MULTICLASS_RESULT_SEMANTICS_PROBABILITY_OUTPUT!r}, "
            f"got {probability_output!r}"
        )
    if decision_strategy != _MULTICLASS_RESULT_SEMANTICS_DECISION_STRATEGY:
        raise ValueError(
            f"decision_strategy must be exactly {_MULTICLASS_RESULT_SEMANTICS_DECISION_STRATEGY!r}, "
            f"got {decision_strategy!r}"
        )

    return {
        "schema_version": MULTICLASS_RESULT_SEMANTICS_INTENT_CONTRACT_VERSION,
        "review_status": review_status,
        "problem_type": problem_type,
        "primary_output": primary_output,
        "probability_output": probability_output,
        "decision_strategy": decision_strategy,
        "review_notes": review_notes,
    }


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
    categorical_domain_intent: Sequence[dict[str, Any]] | None = None,
    binary_result_semantics_intent: dict[str, Any] | None = None,
    multiclass_result_semantics_intent: dict[str, Any] | None = None,
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

    `categorical_domain_intent` (Project Spec S0102) is an optional sequence
    of reviewed categorical-domain declarations, each built via
    `build_categorical_domain_declaration` above. Only entries with
    `review_status == "approved"` may later be promoted into execution
    policy by `contract_derivation._build_execution_contract` -- this builder
    only carries the declarations forward verbatim, it never approves or
    rejects one itself.
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
        "categorical_domain_intent": [dict(entry) for entry in (categorical_domain_intent or [])],
        "binary_result_semantics_intent": (
            dict(binary_result_semantics_intent)
            if binary_result_semantics_intent is not None
            else None
        ),
        "multiclass_result_semantics_intent": (
            dict(multiclass_result_semantics_intent)
            if multiclass_result_semantics_intent is not None
            else None
        ),
        "modeling_intent_boundary_confirmations": dict(
            MODELING_INTENT_BOUNDARY_CONFIRMATIONS
        ),
        "generated_at": generated_at or _utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Dataset modeling intent persistence (Project Spec S0023)
#
# `materialize_dataset_modeling_intent` persists an already-built
# `dataset_modeling_intent.v1` object (see `build_dataset_modeling_intent`
# above) to an explicit repository-relative path, enriched with upstream
# artifact traceability and the reduced evidence policy. It never derives
# target/feature/identifier decisions itself -- those remain explicit inputs
# to `build_dataset_modeling_intent` -- and it never treats a preparation
# recipe's `inferred_pending_review` transformation as resolved on its own
# authority.
# ---------------------------------------------------------------------------

DATASET_MODELING_INTENT_EVIDENCE_POLICY: dict[str, bool] = {
    "raw_logs_prohibited": True,
    "raw_runtime_prohibited": True,
    "raw_api_payloads_prohibited": True,
    "secrets_prohibited": True,
    "private_source_paths_prohibited": True,
    "reduced_and_sanitized": True,
}

_RESOLVED_TRANSFORMATION_REVIEW_STATUSES = frozenset({"explicit", "inferred_approved"})


def _repo_relative_ref_if_present(
    relative_path: str | Path | None, repo_root: Path
) -> str | None:
    """Return a repository-relative reference string, or None.

    Returns None when `relative_path` is not supplied or the referenced file
    does not exist on disk -- this never invents a reference.
    """
    if relative_path is None:
        return None
    candidate = (repo_root / relative_path).resolve()
    if not candidate.exists():
        return None
    return Path(relative_path).as_posix()


def _preparation_recipe_blank_value_policy_candidates(
    preparation_recipe: dict[str, Any],
) -> dict[str, str]:
    """Derive blank-value policy candidates from a preparation recipe's own
    missing-value-handling transformations, keyed by target column.

    A column is only ever reported with the recipe's own review_status when
    that status is 'explicit' or 'inferred_approved'; every other status
    (including the recipe's absence of an entry) is reported as
    'unresolved_pending_review'. This function never marks a column resolved
    on its own authority -- it only reads what the recipe already recorded.
    """
    candidates: dict[str, str] = {}
    for transformation in preparation_recipe.get("transformations", []):
        if transformation.get("transformation_type") != "missing_value_handling":
            continue
        review_status = transformation.get("review_status")
        resolved = review_status in _RESOLVED_TRANSFORMATION_REVIEW_STATUSES
        for column in transformation.get("target_columns", []):
            candidates[column] = review_status if resolved else "unresolved_pending_review"
    return candidates


def _preparation_recipe_unresolved_review_items(
    preparation_recipe: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return preparation recipe transformations still pending human review, verbatim."""
    return [
        dict(transformation)
        for transformation in preparation_recipe.get("transformations", [])
        if transformation.get("review_status") == "inferred_pending_review"
    ]


def materialize_dataset_modeling_intent(
    modeling_intent: dict[str, Any],
    output_relative_path: str | Path,
    repo_root: str | Path,
    discovery_evidence_relative_path: str | Path | None = None,
    preparation_recipe_relative_path: str | Path | None = None,
    prepared_data_metadata_relative_path: str | Path | None = None,
    public_context_relative_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist an already-built `dataset_modeling_intent.v1` object.

    `modeling_intent` must already be the return value of
    `build_dataset_modeling_intent` (or an equivalent object with the same
    shape). This function enriches a copy of it with:

    - `authoring_source` references to the discovery evidence, preparation
      recipe, prepared dataset metadata, and public context artifacts, each
      included only when its relative path argument is supplied and the file
      exists on disk;
    - `blank_value_policy_candidates` re-derived from the preparation
      recipe's own transformations when a preparation recipe is present and
      readable, so a column is never silently reported as resolved unless
      the recipe itself recorded an 'explicit' or 'inferred_approved'
      review_status;
    - `unresolved_review_items`, the preparation recipe's still-pending
      transformations, forwarded verbatim;
    - `evidence_policy`, the reduced evidence policy confirmation shared by
      this module's other materialized artifacts.

    Every path is resolved against `repo_root`, so the call is correct
    regardless of the caller's working directory (for example a notebook
    running from a nested dataset directory). Raises FileNotFoundError only
    if `repo_root` itself is not a usable path; missing upstream artifacts
    are recorded as absent references, not errors.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve()
    output_path = (resolved_repo_root / output_relative_path).resolve()

    discovery_evidence_ref = _repo_relative_ref_if_present(
        discovery_evidence_relative_path, resolved_repo_root
    )
    preparation_recipe_ref = _repo_relative_ref_if_present(
        preparation_recipe_relative_path, resolved_repo_root
    )
    prepared_data_metadata_ref = _repo_relative_ref_if_present(
        prepared_data_metadata_relative_path, resolved_repo_root
    )
    public_context_ref = _repo_relative_ref_if_present(
        public_context_relative_path, resolved_repo_root
    )

    materialized_intent = dict(modeling_intent)
    authoring_source = dict(materialized_intent.get("authoring_source") or {})
    if discovery_evidence_ref is not None:
        authoring_source["reduced_discovery_evidence_ref"] = discovery_evidence_ref
    authoring_source["preparation_recipe_ref"] = preparation_recipe_ref
    authoring_source["prepared_data_metadata_ref"] = prepared_data_metadata_ref
    authoring_source["public_context_ref"] = public_context_ref
    materialized_intent["authoring_source"] = authoring_source

    if preparation_recipe_ref is not None:
        preparation_recipe = json.loads(
            (resolved_repo_root / preparation_recipe_ref).read_text(encoding="utf-8")
        )
        blank_value_policy_candidates = dict(
            materialized_intent.get("blank_value_policy_candidates") or {}
        )
        blank_value_policy_candidates.update(
            _preparation_recipe_blank_value_policy_candidates(preparation_recipe)
        )
        materialized_intent["blank_value_policy_candidates"] = blank_value_policy_candidates
        materialized_intent["unresolved_review_items"] = (
            _preparation_recipe_unresolved_review_items(preparation_recipe)
        )
    else:
        materialized_intent.setdefault("unresolved_review_items", [])

    materialized_intent["evidence_policy"] = dict(DATASET_MODELING_INTENT_EVIDENCE_POLICY)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(materialized_intent, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return materialized_intent
