"""Independent Atlas reproduction of a pinned Dataset Study protocol.

Evidence lineages kept strictly apart:

``scientific_study_run``          the external Dataset Study's own execution;
                                  its published numbers are *reference
                                  evidence* pinned in a scientific study
                                  contract.
``scientific_reproduction_run``   this module: Atlas re-executes the declared
                                  protocol from the hash-verified dataset and
                                  compares its own results against the
                                  reference. Its output is a write-once
                                  reproduction report.
``atlas_native_training_run``     ``pipeline.training``; unrelated to this
                                  module, never read or written here.
``atlas_release``                 publisher/registry state; a reproduction
                                  never creates, modifies, or activates one.

The engine is generic. Everything problem-specific is dispatched on the
contract's ``problem.problem_type`` through a task adapter
(``binary_classification``, ``multiclass_classification`` or
``continuous_regression``); nothing is dispatched on a dataset slug. The
adapter owns target representation, the cross-validation scorers, candidate
evaluation, the decision stage (a threshold policy for binary problems, an
explicit *not applicable* record and the argmax rule for multiclass problems,
and a point prediction with every class concept recorded as not applicable
for continuous regression), and the final test evaluation.
Protocol stages shared by every problem type (dataset identity, preparation,
split with membership evidence and gates, family search, family shortlist,
feature-policy stage, practical-tie selection, final fit, comparison,
status, descriptive group-overlap diagnostics) live once in this module.

Every metric set the engine emits carries provenance (producer lineage,
metric scope, run, study revision, dataset hash, partition and its membership
hash, model and feature policy, the threshold or its explicit
not-applicable record, class order, and the protocol). Reference values are
only ever used on the *expected* side of a comparison or as a protocol gate
(a precondition that stops execution); they are never copied into the
reproduced results.

Typical use (a thin notebook or an orchestrator task per step)::

    contract = load_scientific_study_contract(path, repo_root=root)
    reproduction = build_reproduction(contract, repo_root=root)
    result = reproduction.run()
    report = result.build_report()
    write_reproduction_report(report, repo_root=root, search_results=result.search_results)
"""

from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import io
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pipeline import metric_identity, model_families, preparation_rules, scientific_environment
from pipeline.scientific_study_contract import (
    BINARY,
    MULTICLASS,
    REGRESSION,
    SCHEMA_VERSION_V3 as CONTRACT_SCHEMA_VERSION_V3,
    ScientificStudyContract,
    assess_protocol_support,
    load_scientific_study_contract,
    verify_against_study_checkout,
)


REPORT_SCHEMA_VERSION_V1 = "scientific-reproduction-report.v1"
REPORT_SCHEMA_VERSION = "scientific-reproduction-report.v2"
REPORT_SCHEMA_VERSION_V3 = "scientific-reproduction-report.v3"
_SCHEMA_DIR = Path(__file__).resolve().parent
REPORT_SCHEMA_PATHS: Mapping[str, Path] = {
    REPORT_SCHEMA_VERSION_V1: _SCHEMA_DIR / "scientific-reproduction-report.schema.json",
    REPORT_SCHEMA_VERSION: _SCHEMA_DIR / "scientific-reproduction-report.v2.schema.json",
    REPORT_SCHEMA_VERSION_V3: _SCHEMA_DIR / "scientific-reproduction-report.v3.schema.json",
}
REPORT_SCHEMA_PATH = REPORT_SCHEMA_PATHS[REPORT_SCHEMA_VERSION]
REPORT_FILENAME = "reproduction-report.json"
SEARCH_RESULTS_FILENAME = "search-results.json"
RUNS_ROOT_RELATIVE = "pipeline/scientific-reproduction-runs"
ENGINE_ID = "pipeline/scientific_reproduction.py"
ENGINE_VERSION = "4"

RUN_KIND = "scientific_reproduction_run"
STUDY_RUN_KIND = "scientific_study_run"
NATIVE_TRAINING_RUN_KIND = "atlas_native_training_run"
RELEASE_KIND = "atlas_release"

# Reproduction outcome vocabulary.
STATUS_REPRODUCED_EXACT = "reproduced_exact"
STATUS_REPRODUCED_WITHIN_TOLERANCE = "reproduced_within_tolerance"
STATUS_CAPABILITY_MISSING = "atlas_capability_missing"
STATUS_ENVIRONMENT_INCOMPATIBLE = "environment_incompatible"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_scientific_evidence"
STATUS_DIVERGENT = "divergent"
STATUS_DATASET_MISMATCH = "dataset_identity_mismatch"
REPRODUCTION_STATUSES = (
    STATUS_REPRODUCED_EXACT,
    STATUS_REPRODUCED_WITHIN_TOLERANCE,
    STATUS_CAPABILITY_MISSING,
    STATUS_ENVIRONMENT_INCOMPATIBLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_DIVERGENT,
    STATUS_DATASET_MISMATCH,
)

# Comparison outcome vocabulary for one expected quantity.
OUTCOME_EXACT = "exact_at_reported_precision"
OUTCOME_WITHIN = "within_tolerance"
OUTCOME_OUTSIDE = "outside_tolerance"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_MISSING = "not_produced_by_reproduction"

# Metric-set scopes (lineage of every emitted metric set).
SCOPE_BASELINE_VALIDATION = "baseline_validation"
SCOPE_FAMILY_SEARCH_CV = "family_search_cv"
SCOPE_FEATURE_POLICY_CV = "feature_policy_cv"
SCOPE_CANDIDATE_VALIDATION = "candidate_validation"
SCOPE_FINAL_TEST = "scientific_final_test"
SCOPE_INTERPRETIVE_DIAGNOSTIC = "interpretive_diagnostic"

THRESHOLD_NOT_APPLICABLE_REASON = "multiclass_argmax_decision"

_FLOAT_EQUALITY_ABS_TOL = 1e-12


class ScientificReproductionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# small deterministic helpers
# --------------------------------------------------------------------------


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return scientific_environment.sha256_file(path)


def _key(label: Any) -> str:
    """Normalize a label into a quantity-path segment."""
    return re.sub(r"[^a-z0-9]+", "_", str(label).strip().lower()).strip("_")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)) and getattr(value, "ndim", 0) > 0:
        return _jsonable(value.tolist())
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def _normalize_scalar(value: Any) -> Any:
    try:
        import pandas as pd

        if value is pd.NA or value is None:
            return None
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def not_applicable(reason: str) -> dict[str, Any]:
    """Explicit not-applicable record (distinct from a missing value / null)."""
    return {"applicable": False, "reason": reason}


# --------------------------------------------------------------------------
# partition membership evidence
# --------------------------------------------------------------------------


def _membership_keys(frame: Any, identifier_columns: Sequence[str]) -> list[str]:
    return [
        json.dumps(
            [_normalize_scalar(v) for v in row],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        for row in frame.loc[:, list(identifier_columns)].itertuples(index=False, name=None)
    ]


def membership_sha256(frame: Any, identifier_columns: Sequence[str]) -> str:
    """SHA-256 of the sorted identifier keys of a partition (order independent)."""
    keys = sorted(_membership_keys(frame, identifier_columns))
    return _sha256_bytes("\n".join(keys).encode("utf-8"))


def _canonical_row_scalar(value: Any) -> dict[str, Any]:
    normalized = _normalize_scalar(value)
    if isinstance(normalized, bool):
        return {"type": "bool", "value": normalized}
    if isinstance(normalized, float):
        if not math.isfinite(normalized):
            raise ScientificReproductionError("non_finite_membership_value",
                                              "row-occurrence membership cannot fingerprint non-finite values")
        return {"type": "number", "value": format(normalized, ".15g")}
    if isinstance(normalized, int):
        return {"type": "number", "value": str(normalized)}
    if normalized is None:
        return {"type": "null", "value": None}
    return {"type": "string", "value": str(normalized)}


def row_occurrence_membership_keys(frame: Any) -> list[str]:
    """Technical membership tokens for sources without an identifier.

    Each row gets ``row-occurrence-v1:<sha256 of canonical row>:<ordinal>``
    where the ordinal counts earlier source rows with identical content. The
    token is partition evidence only; it neither becomes a predictor nor
    claims that equal rows are the same real-world entity.
    """
    occurrences: Counter[str] = Counter()
    keys: list[str] = []
    for row in frame.itertuples(index=False, name=None):
        payload = [_canonical_row_scalar(v) for v in row]
        digest = _sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":"), allow_nan=False).encode("utf-8"))
        ordinal = occurrences[digest]
        occurrences[digest] += 1
        keys.append(f"row-occurrence-v1:{digest}:{ordinal:08d}")
    return keys


def membership_spec(split: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the membership declaration (v1 contracts imply identifier keys)."""
    declared = split.get("membership")
    if declared:
        return dict(declared)
    return {"kind": "identifier", "digest_order": "sorted_keys"}


def source_membership_keys(frame: Any, spec: Mapping[str, Any], identifier_columns: Sequence[str]) -> list[str]:
    if spec["kind"] == "identifier":
        if not identifier_columns:
            raise ScientificReproductionError("identifier_membership_without_identifier",
                                              "identifier membership requires identifier columns")
        return _membership_keys(frame, identifier_columns)
    if spec["kind"] == "technical_row_occurrence":
        return row_occurrence_membership_keys(frame)
    raise ScientificReproductionError("unsupported_membership_kind", str(spec["kind"]))


def membership_digest(keys: Sequence[str], digest_order: str) -> str:
    ordered = sorted(keys) if digest_order == "sorted_keys" else list(keys)
    return _sha256_bytes("\n".join(ordered).encode("utf-8"))


def partition_csv_sha256(frame: Any, float_format: str | None = None) -> str:
    buffer = io.StringIO(newline="")
    frame.to_csv(buffer, index=False, lineterminator="\n", float_format=float_format)
    return _sha256_bytes(buffer.getvalue().encode("utf-8"))


# --------------------------------------------------------------------------
# step 1: dataset identity and preparation
# --------------------------------------------------------------------------


def verify_dataset_identity(dataset_path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(dataset_path)
    if not path.is_file():
        return {"verified": False, "reason": "dataset file is absent", "observed_sha256": None,
                "expected_sha256": identity["sha256"]}
    observed_sha = _sha256_file(path)
    observed_size = path.stat().st_size
    verified = observed_sha == identity["sha256"] and observed_size == identity["size_bytes"]
    return {
        "verified": verified,
        "reason": None if verified else "dataset bytes differ from the pinned identity",
        "expected_sha256": identity["sha256"],
        "observed_sha256": observed_sha,
        "expected_size_bytes": identity["size_bytes"],
        "observed_size_bytes": observed_size,
    }


def load_dataset(dataset_path: Path, identity: Mapping[str, Any]) -> Any:
    import pandas as pd

    frame = pd.read_csv(dataset_path, **dict(identity.get("read_options") or {}))
    if frame.shape != (identity["row_count"], identity["column_count"]):
        raise ScientificReproductionError(
            "dataset_shape_mismatch",
            f"dataset shape {frame.shape} differs from the pinned "
            f"({identity['row_count']}, {identity['column_count']})",
        )
    return frame


def _apply_conditional_blank_numeric_fill(frame: Any, rule: Mapping[str, Any]) -> tuple[Any, int]:
    import pandas as pd

    column, condition_column = rule["column"], rule["condition_column"]
    source = frame[column]
    if source.isna().any():
        raise ScientificReproductionError(
            "preparation_rule_violation", f"{column} contains null values; only explicit blanks may be filled"
        )
    normalized = source.map(lambda v: v.strip() if rule.get("strip_strings") and isinstance(v, str) else v)
    blank = normalized.map(lambda v: isinstance(v, str) and v == "")
    condition = frame[condition_column].eq(rule["condition_value"])
    if (blank & ~condition).any():
        raise ScientificReproductionError(
            "preparation_rule_violation",
            f"{column} has blanks where {condition_column} != {rule['condition_value']!r}",
        )
    fill = blank & condition
    converted = pd.to_numeric(normalized.mask(fill, pd.NA), errors="coerce")
    if (converted.isna() & ~fill).any():
        raise ScientificReproductionError(
            "preparation_rule_violation", f"{column} has non-convertible values"
        )
    converted = converted.astype("float64")
    converted.loc[fill] = float(rule["replacement"])
    prepared = frame.copy(deep=True)
    prepared[column] = converted
    return prepared, int(fill.sum())


_PREPARATION_RULES = {preparation_rules.CONDITIONAL_BLANK_NUMERIC_FILL: _apply_conditional_blank_numeric_fill}


def apply_preparation(frame: Any, preparation: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    prepared = frame.copy(deep=True)
    evidence: dict[str, Any] = {}
    for rule in preparation["rules"]:
        handler = _PREPARATION_RULES.get(rule["kind"])
        if handler is None:
            raise ScientificReproductionError("unsupported_preparation_rule", rule["kind"])
        prepared, count = handler(prepared, rule)
        evidence[_key(rule["rule_id"])] = {"kind": rule["kind"], "materialized_count": count}
    if len(prepared) != len(frame):
        raise ScientificReproductionError("preparation_row_count_changed", "preparation changed the row count")
    return prepared, evidence


# --------------------------------------------------------------------------
# step 2: split
# --------------------------------------------------------------------------


def _split_two_stage_with_membership(
    frame: Any, split: Mapping[str, Any], identifier_columns: Sequence[str], *, stratify_by: str | None
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Two-stage ``train_test_split`` holdout with partition membership evidence.

    Membership keys (identifier tuples, or technical row-occurrence tokens
    when the source has no identifier) are computed on the whole source. With
    ``order_by_identifier`` (the default) rows are ordered by key before
    splitting so membership does not depend on input row order; otherwise
    source positions are split directly. The second stage splits the
    temporary partition with ``test / (validation + test)``. Each partition is
    returned in source row order together with the keys of its rows in that
    order. ``stratify_by=None`` splits without stratification.
    """
    from sklearn.model_selection import train_test_split

    fractions = split["fractions"]
    spec = membership_spec(split)
    working = frame.copy(deep=True)
    working["__source_position__"] = range(len(working))
    ordered = split.get("order_by_identifier", True)
    keys: list[str] | None = None
    if ordered or "membership" in split:
        keys = source_membership_keys(frame, spec, identifier_columns)
    if ordered:
        working["__membership_key__"] = keys
        if working["__membership_key__"].duplicated().any():
            raise ScientificReproductionError("duplicate_identifier", "membership keys must be unique")
        canonical = working.sort_values("__membership_key__", kind="stable").reset_index(drop=True)
    else:
        canonical = working.reset_index(drop=True)
    positions = list(range(len(canonical)))
    temporary_fraction = fractions["validation"] + fractions["test"]
    train_pos, temporary_pos = train_test_split(
        positions,
        test_size=temporary_fraction,
        random_state=split["seeds"]["train_vs_temporary"],
        shuffle=split.get("shuffle", True),
        stratify=canonical[stratify_by] if stratify_by is not None else None,
    )
    temporary = canonical.iloc[temporary_pos]
    validation_pos, test_pos = train_test_split(
        temporary_pos,
        test_size=fractions["test"] / temporary_fraction,
        random_state=split["seeds"]["validation_vs_test"],
        shuffle=split.get("shuffle", True),
        stratify=temporary[stratify_by] if stratify_by is not None else None,
    )

    partitions: dict[str, Any] = {}
    partition_keys: dict[str, list[str]] = {}
    for name, selected in (("train", train_pos), ("validation", validation_pos), ("test", test_pos)):
        source_positions = sorted(int(v) for v in canonical.iloc[list(selected)]["__source_position__"])
        partitions[name] = frame.iloc[source_positions].copy(deep=True)
        partition_keys[name] = [keys[p] for p in source_positions] if keys is not None else []
    return partitions, partition_keys


def split_two_stage_stratified_with_membership(
    frame: Any, split: Mapping[str, Any], identifier_columns: Sequence[str]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Two-stage holdout stratified on ``split.stratify_by`` in both stages."""
    return _split_two_stage_with_membership(frame, split, identifier_columns, stratify_by=split["stratify_by"])


def split_two_stage_random_with_membership(
    frame: Any, split: Mapping[str, Any], identifier_columns: Sequence[str]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Two-stage shuffled holdout without stratification (``stratify=None``).

    Row assignment never reads the target, so it serves continuous targets.
    """
    if split.get("stratify_by") is not None:
        raise ScientificReproductionError("stratified_random_holdout",
                                          "two_stage_random_holdout requires stratify_by = null")
    return _split_two_stage_with_membership(frame, split, identifier_columns, stratify_by=None)


def split_two_stage_stratified(frame: Any, split: Mapping[str, Any], identifier_columns: Sequence[str]) -> dict[str, Any]:
    """Backward-compatible splitter returning only the partitions."""
    return split_two_stage_stratified_with_membership(frame, split, identifier_columns)[0]


_SPLITTERS = {
    "two_stage_stratified_holdout": split_two_stage_stratified_with_membership,
    "two_stage_random_holdout": split_two_stage_random_with_membership,
}
_SPLIT_ALGORITHMS = {
    "two_stage_stratified_holdout": "sklearn.model_selection.train_test_split (two stages, stratified)",
    "two_stage_random_holdout": "sklearn.model_selection.train_test_split (two stages, shuffled, stratify=None)",
}


def _handoff_spec(split: Mapping[str, Any]) -> dict[str, Any]:
    declared = split.get("partition_handoff")
    if declared is None:
        return {"kind": "in_memory"}
    if isinstance(declared, str):
        return {"kind": declared}
    return dict(declared)


def csv_roundtrip(frame: Any, float_format: str | None = None) -> Any:
    """Serialize and re-read a partition the way a file-based study handoff does."""
    import pandas as pd

    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n", float_format=float_format)
    buffer.seek(0)
    return pd.read_csv(buffer)


# --------------------------------------------------------------------------
# step 3: candidate pipelines, search, evaluation
# --------------------------------------------------------------------------


def build_candidate_pipeline(
    candidate: Mapping[str, Any],
    contract: Mapping[str, Any],
    task_type: str,
    extra_params: Mapping[str, Any] | None = None,
    feature_columns: Sequence[str] | None = None,
) -> Any:
    """Preprocessing + registry estimator; ``feature_columns`` projects features.

    A projection keeps the contract's feature order and roles; it never
    reorders or re-types columns.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    preprocessing = contract["preprocessing"]
    categorical_spec = preprocessing.get("categorical", {})
    selected = set(feature_columns) if feature_columns is not None else None
    numerical = [c for c in contract["features"]["numerical"] if selected is None or c in selected]
    categorical = [c for c in contract["features"]["categorical"] if selected is None or c in selected]
    if feature_columns is not None and len(numerical) + len(categorical) != len(set(feature_columns)):
        raise ScientificReproductionError("unknown_projected_feature", "feature projection names unknown features")
    transformers: list[tuple[str, Any, list[str]]] = []
    if numerical:
        scaler: Any = StandardScaler() if candidate["numerical_scaling"] == "standard" else "passthrough"
        transformers.append(("numerical", scaler, numerical))
    if categorical:
        transformers.append((
            "categorical",
            OneHotEncoder(
                handle_unknown=categorical_spec.get("handle_unknown", "ignore"),
                drop=categorical_spec.get("drop"),
                sparse_output=not categorical_spec.get("dense", True),
            ),
            categorical,
        ))
    preprocess = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        sparse_threshold=0.0 if categorical_spec.get("dense", True) else 0.3,
        verbose_feature_names_out=True,
    )
    params = dict(candidate["fixed_params"])
    params.update(extra_params or {})
    estimator = model_families.build_estimator(candidate["family"], task_type, params)
    return Pipeline(steps=[("preprocess", preprocess), ("model", estimator)])


def _scoring(positive_label: int) -> dict[str, Any]:
    from sklearn.metrics import f1_score, fbeta_score, make_scorer, precision_score, recall_score

    return {
        "average_precision": "average_precision",
        "roc_auc": "roc_auc",
        "precision": make_scorer(precision_score, pos_label=positive_label, zero_division=0),
        "recall": make_scorer(recall_score, pos_label=positive_label, zero_division=0),
        "f1": make_scorer(f1_score, pos_label=positive_label, zero_division=0),
        "f2": make_scorer(fbeta_score, beta=2, pos_label=positive_label, zero_division=0),
        "balanced_accuracy": "balanced_accuracy",
        "accuracy": "accuracy",
        "neg_log_loss": "neg_log_loss",
        "neg_brier_score": "neg_brier_score",
    }


# Multiclass metric name -> (scorer key, sklearn scorer string).
MULTICLASS_CV_SCORERS: Mapping[str, tuple[str, str]] = {
    "macro_f1": ("macro_f1", "f1_macro"),
    "balanced_accuracy": ("balanced_accuracy", "balanced_accuracy"),
    "macro_recall": ("macro_recall", "recall_macro"),
    "weighted_f1": ("weighted_f1", "f1_weighted"),
    "accuracy": ("accuracy", "accuracy"),
    "log_loss": ("neg_log_loss", "neg_log_loss"),
}


def multiclass_scoring(metrics: Sequence[str]) -> dict[str, str]:
    scoring = {}
    for metric in metrics:
        if metric not in MULTICLASS_CV_SCORERS:
            raise ScientificReproductionError("unsupported_cv_scorer", metric)
        key, scorer = MULTICLASS_CV_SCORERS[metric]
        scoring[key] = scorer
    return scoring


# Continuous-regression metric name -> (scorer key, sklearn scorer string),
# derived from the canonical metric identity registry. A ``neg_`` key marks a
# loss that scikit-learn scores negated; every reported value is flipped back
# to its natural orientation (see ``_cv_summary``).
REGRESSION_CV_SCORERS: Mapping[str, tuple[str, str]] = {
    metric: (f"neg_{metric}" if scorer.startswith("neg_") else metric, scorer)
    for metric, scorer in (
        (name, metric_identity.resolve_scientific_metric(name).sklearn_scorer)
        for name in ("mae", "rmse", "r2", "medae")
    )
}


def regression_scoring(metrics: Sequence[str]) -> dict[str, str]:
    scoring = {}
    for metric in metrics:
        if metric not in REGRESSION_CV_SCORERS:
            raise ScientificReproductionError("unsupported_cv_scorer", metric)
        key, scorer = REGRESSION_CV_SCORERS[metric]
        scoring[key] = scorer
    return scoring


def _cross_validator(spec: Mapping[str, Any]) -> Any:
    from sklearn.model_selection import KFold, StratifiedKFold

    folds = {"stratified_k_fold": StratifiedKFold, "k_fold": KFold}.get(spec["kind"])
    if folds is None:
        raise ScientificReproductionError("unsupported_cross_validation", spec["kind"])
    return folds(n_splits=int(spec["n_splits"]), shuffle=bool(spec["shuffle"]), random_state=spec["random_state"])


def _cv_summary(results: Mapping[str, Any], scoring: Mapping[str, Any], refit: str, index: int | None,
                n_splits: int, z_value: float) -> dict[str, float]:
    """Natural-orientation CV means for every scorer; std and CI for the refit metric.

    ``index`` selects a row of ``cv_results_``; ``None`` reads a
    ``cross_validate`` result (population standard deviation, as scikit-learn
    reports for searches).
    """
    import numpy as np

    summary: dict[str, float] = {}
    for scorer in scoring:
        sign = -1.0 if scorer.startswith("neg_") else 1.0
        name = scorer.removeprefix("neg_")
        if index is None:
            values = np.asarray(results[f"test_{scorer}"], dtype=float)
            mean, std = float(sign * values.mean()), float(values.std(ddof=0))
        else:
            mean, std = sign * float(results[f"mean_test_{scorer}"][index]), float(results[f"std_test_{scorer}"][index])
        summary[f"{name}_mean"] = mean
        if scorer == refit:
            half = z_value * std / math.sqrt(n_splits)
            summary[f"{name}_std"] = std
            summary[f"{name}_ci_lower"] = mean - half
            summary[f"{name}_ci_upper"] = mean + half
    return summary


def run_candidate_search(candidate: Mapping[str, Any], contract: Mapping[str, Any], x_train: Any, y_train: Any, *,
                         n_jobs: int, task_type: str, scoring: Mapping[str, Any] | None = None,
                         refit: str | None = None) -> dict[str, Any]:
    """Search one family on the training partition only.

    ``refit`` is the scorer key the search refits on (default: the contract's
    refit metric name, which is its own key for score-oriented metrics).
    """
    from sklearn.model_selection import GridSearchCV, ParameterGrid, RandomizedSearchCV

    search = candidate["search"]
    space = {f"model__{name}": list(values) for name, values in search.get("space", {}).items()}
    pipeline = build_candidate_pipeline(candidate, contract, task_type)
    cv_spec = contract["cross_validation"]
    if scoring is None:
        target = contract["problem"]["target"]
        scoring = _scoring(int(target["encoding"][str(target["positive_class"])]))
    common = dict(
        estimator=pipeline,
        scoring=dict(scoring),
        refit=refit or contract["metrics"].get("refit", contract["metrics"]["primary"]),
        cv=_cross_validator(cv_spec),
        n_jobs=n_jobs,
        return_train_score=False,
        error_score="raise",
    )
    if search["kind"] == "grid":
        searcher = GridSearchCV(param_grid=space, **common)
        expected = len(ParameterGrid(space))
    elif search["kind"] == "randomized":
        searcher = RandomizedSearchCV(param_distributions=space, n_iter=int(search["n_iter"]), random_state=search["random_state"], **common)
        expected = min(int(search["n_iter"]), len(ParameterGrid(space)))
    else:
        raise ScientificReproductionError("unsupported_search_kind", search["kind"])
    declared = search.get("expected_candidate_count")
    if declared is not None and int(declared) != expected:
        raise ScientificReproductionError(
            "declared_candidate_count_mismatch",
            f"{candidate['model_id']}: contract declares {declared} candidates, the declared space yields {expected}",
        )
    started = time.perf_counter()
    searcher.fit(x_train, y_train)
    duration = time.perf_counter() - started
    results = searcher.cv_results_
    executed = len(results["params"])
    if executed != expected:
        raise ScientificReproductionError(
            "search_candidate_count_mismatch", f"{candidate['model_id']}: expected {expected}, executed {executed}"
        )
    best = int(searcher.best_index_)
    n_splits = int(cv_spec["n_splits"])
    z_value = float(contract["selection"].get("practical_tie", {}).get("cv_interval_z", 1.96))
    refit = common["refit"]

    def natural(scorer: str, index: int) -> tuple[str, float]:
        sign = -1.0 if scorer.startswith("neg_") else 1.0
        return scorer.removeprefix("neg_"), sign * float(results[f"mean_test_{scorer}"][index])

    # Report the refit metric in its natural orientation; ``neg_`` is only
    # scikit-learn's scoring convention.
    refit_name, best_score = natural(refit, best)
    summary: dict[str, Any] = {
        "candidate_count_executed": executed,
        "candidate_count_expected": expected,
        "best_index": best,
        "best_params": {name.removeprefix("model__"): _jsonable(value) for name, value in searcher.best_params_.items()},
        "pipeline_best_params": {name: _jsonable(value) for name, value in searcher.best_params_.items()},
        "refit_metric": refit_name,
        "search_strategy": type(searcher).__name__,
        "search_random_state": search.get("random_state") if search["kind"] == "randomized" else None,
        "search_duration_seconds": round(duration, 3),
        "best_score": best_score,
    }
    summary.update(_cv_summary(results, common["scoring"], refit, best, n_splits, z_value))
    table = [
        {
            "candidate_index": index,
            "params": {k.removeprefix("model__"): _jsonable(v) for k, v in params.items()},
            f"rank_{refit_name}": int(results[f"rank_test_{refit}"][index]),
            **{f"mean_{natural(s, index)[0]}": natural(s, index)[1] for s in common["scoring"]},
            f"std_{refit_name}": float(results[f"std_test_{refit}"][index]),
        }
        for index, params in enumerate(results["params"])
    ]
    return {"summary": summary, "table": table, "best_estimator": searcher.best_estimator_}


def _positive_probabilities(estimator: Any, x: Any, positive_label: int) -> list[float]:
    classes = list(estimator.classes_)
    if positive_label not in classes:
        raise ScientificReproductionError("positive_class_absent", "fitted estimator lacks the positive label")
    return [float(v) for v in estimator.predict_proba(x)[:, classes.index(positive_label)]]


def threshold_metrics(y_true: Sequence[int], probabilities: Sequence[float], threshold: float) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, fbeta_score, precision_score, recall_score

    y = [int(v) for v in y_true]
    predicted = [int(p >= threshold) for p in probabilities]
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y, predicted, pos_label=1, zero_division=0)),
        "recall": float(recall_score(y, predicted, pos_label=1, zero_division=0)),
        "f1": float(f1_score(y, predicted, pos_label=1, zero_division=0)),
        "f2": float(fbeta_score(y, predicted, beta=2, pos_label=1, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
        "accuracy": float(accuracy_score(y, predicted)),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "true_negatives": int(tn),
        "false_negatives": int(fn),
        "predicted_positive_count": int(sum(predicted)),
    }


def probability_metrics(y_true: Sequence[int], probabilities: Sequence[float]) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

    y = [int(v) for v in y_true]
    return {
        "average_precision": float(average_precision_score(y, probabilities)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
        "log_loss": float(log_loss(y, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y, probabilities)),
    }


# --------------------------------------------------------------------------
# multiclass evaluation with explicit class-order provenance
# --------------------------------------------------------------------------


def align_probabilities_to_class_order(
    raw_probabilities: Any,
    estimator_classes: Sequence[Any],
    target_order: Sequence[Any],
    *,
    expected_estimator_order: Sequence[Any] | None = None,
) -> Any:
    """Map probability columns to classes through ``estimator.classes_``.

    Column ``j`` of ``raw_probabilities`` belongs to ``estimator_classes[j]``
    -- never to the j-th class of any other order. The result has one column
    per class of ``target_order``, in that order. A missing class, an extra
    class, a shape mismatch, or (when declared) an estimator order different
    from the contract's fails explicitly.
    """
    import numpy as np

    matrix = np.asarray(raw_probabilities, dtype=float)
    fitted = [str(c) for c in estimator_classes]
    wanted = [str(c) for c in target_order]
    if matrix.ndim != 2 or matrix.shape[1] != len(fitted):
        raise ScientificReproductionError("probability_shape_mismatch",
                                          f"probability matrix shape {matrix.shape} does not match {len(fitted)} estimator classes")
    missing = [c for c in wanted if c not in fitted]
    extra = [c for c in fitted if c not in wanted]
    if missing or extra or len(set(fitted)) != len(fitted):
        raise ScientificReproductionError("probability_class_mismatch",
                                          f"estimator classes differ from the class contract (missing={missing}, extra={extra})")
    if expected_estimator_order is not None and fitted != [str(c) for c in expected_estimator_order]:
        raise ScientificReproductionError("estimator_class_order_mismatch",
                                          f"fitted estimator class order {fitted} differs from the contract's "
                                          f"{[str(c) for c in expected_estimator_order]}")
    index = {label: position for position, label in enumerate(fitted)}
    return matrix[:, [index[c] for c in wanted]].copy()


def multiclass_log_loss(y_true: Sequence[Any], probabilities: Any, class_order: Sequence[Any]) -> float:
    """Mean negative log probability of the observed class (clipped at float eps).

    ``probabilities`` columns must already be in ``class_order``; the
    observed class is located by label, never by lexicographic position.
    """
    import numpy as np

    matrix = np.asarray(probabilities, dtype=float)
    classes = [str(c) for c in class_order]
    if matrix.shape != (len(y_true), len(classes)):
        raise ScientificReproductionError("probability_shape_mismatch", "probability matrix shape differs from class contract")
    if not np.isfinite(matrix).all() or not np.allclose(matrix.sum(axis=1), 1.0, atol=1e-8):
        raise ScientificReproductionError("invalid_probabilities", "class probabilities must be finite and sum to one")
    position = {label: i for i, label in enumerate(classes)}
    observed = matrix[np.arange(len(y_true)), [position[str(label)] for label in y_true]]
    return float(-np.mean(np.log(np.clip(observed, np.finfo(float).eps, 1.0))))


def argmax_decisions(probabilities: Any, public_order: Sequence[Any], estimator_order: Sequence[Any],
                     tie_resolution: str) -> tuple[list[str], int]:
    """Argmax decision rule; returns labels and the count of exact-probability ties."""
    import numpy as np

    matrix = np.asarray(probabilities, dtype=float)
    public = [str(c) for c in public_order]
    order = public if tie_resolution == "first_in_public_class_order" else [str(c) for c in estimator_order]
    permuted = matrix[:, [public.index(c) for c in order]]
    winners = np.argmax(permuted, axis=1)
    maxima = permuted.max(axis=1, keepdims=True)
    ties = int(((permuted == maxima).sum(axis=1) > 1).sum())
    return [order[i] for i in winners], ties


def multiclass_metrics(y_true: Sequence[Any], predictions: Sequence[Any], probabilities: Any,
                       class_order: Sequence[Any]) -> dict[str, Any]:
    """Aggregate, per-class and fixed-order confusion evidence for a multiclass evaluation."""
    import numpy as np
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score,
                                 precision_recall_fscore_support, recall_score)

    classes = [str(c) for c in class_order]
    y = [str(v) for v in y_true]
    predicted = [str(v) for v in predictions]
    if not set(y) <= set(classes) or not set(predicted) <= set(classes):
        raise ScientificReproductionError("label_outside_class_contract", "observed labels differ from the class contract")
    precision, recall, f1_values, support = precision_recall_fscore_support(y, predicted, labels=classes, zero_division=0)
    matrix = confusion_matrix(y, predicted, labels=classes)
    metrics = {
        "macro_f1": float(f1_score(y, predicted, labels=classes, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
        "macro_recall": float(recall_score(y, predicted, labels=classes, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, predicted, labels=classes, average="weighted", zero_division=0)),
        "accuracy": float(accuracy_score(y, predicted)),
        "minimum_per_class_recall": float(np.min(recall)),
        "log_loss": multiclass_log_loss(y, probabilities, classes) if probabilities is not None else None,
        "row_count": len(y),
    }
    per_class = {
        _key(label): {
            "class": label,
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1_values[i]),
            "support": int(support[i]),
        }
        for i, label in enumerate(classes)
    }
    return {
        "metrics": metrics,
        "per_class": per_class,
        "confusion_matrix": {"class_order": classes, "counts": matrix.astype(int).tolist()},
    }


def rank_confusion_pairs(confusion: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Unordered class pairs ranked by mutual errors (then row-normalized rate, then pair)."""
    import numpy as np

    classes = list(confusion["class_order"])
    counts = np.asarray(confusion["counts"], dtype=int)
    totals = counts.sum(axis=1, keepdims=True)
    normalized = np.divide(counts, totals, out=np.zeros_like(counts, dtype=float), where=totals != 0)
    pairs = []
    for i, left in enumerate(classes):
        for j in range(i + 1, len(classes)):
            pairs.append({
                "class_pair": [left, classes[j]],
                "mutual_errors": int(counts[i, j] + counts[j, i]),
                "_rate": float(normalized[i, j] + normalized[j, i]),
            })
    pairs.sort(key=lambda p: (-p["mutual_errors"], -p["_rate"], tuple(p["class_pair"])))
    return [{"class_pair": p["class_pair"], "mutual_errors": p["mutual_errors"]} for p in pairs]


def repeated_profile_sensitivity(reference_features: Any, test_features: Any, y_test: Sequence[Any],
                                 predictions: Sequence[Any], probabilities: Any, class_order: Sequence[Any],
                                 official_macro_f1: float) -> dict[str, Any]:
    """Non-destructive sensitivity: metrics without test rows whose feature profile
    also occurs in the final-fit rows. The official test stays complete."""
    import numpy as np
    import pandas as pd

    reference = pd.MultiIndex.from_frame(reference_features.reset_index(drop=True))
    test = pd.MultiIndex.from_frame(test_features.reset_index(drop=True))
    repeated = np.asarray(test.isin(reference))
    keep = ~repeated
    delta = None
    if keep.any():
        kept = multiclass_metrics([v for v, k in zip(y_test, keep) if k], [v for v, k in zip(predictions, keep) if k],
                                  np.asarray(probabilities)[keep], class_order)["metrics"]
        delta = float(kept["macro_f1"] - official_macro_f1)
    return {
        "analysis_type": "non_destructive_repeated_feature_profile_sensitivity",
        "official_full_test_row_count": int(len(test_features)),
        "repeated_profile_test_row_count": int(repeated.sum()),
        "sensitivity_row_count": int(keep.sum()),
        "macro_f1_delta_excluding_minus_full": delta,
        "official_test_rows_removed": 0,
        "interpretation": "Sensitivity only: the official test remains complete; repeated feature profiles do not "
                          "prove duplicate identity or leakage.",
    }


# --------------------------------------------------------------------------
# step 4: shortlist, selection and threshold rules
# --------------------------------------------------------------------------


LOWER_IS_BETTER_METRICS = frozenset({"log_loss", "brier_score", "mae", "rmse", "medae"})


def metric_direction(metric: str) -> str:
    return "min" if metric in LOWER_IS_BETTER_METRICS else "max"


def shortlist_top_k(summaries: Mapping[str, Mapping[str, Any]], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Top-k families by a cross-validation metric, ties broken by model_id."""
    metric_field = f"{rule['metric']}_mean"
    direction = rule.get("direction", metric_direction(rule["metric"]))
    sign = -1.0 if direction == "max" else 1.0
    ranking = sorted(summaries, key=lambda m: (sign * float(summaries[m][metric_field]), m))
    k = int(rule["k"])
    return {
        "rule": dict(rule),
        "ranking": [{"model_id": m, f"cv_{metric_field}": float(summaries[m][metric_field]),
                     "rank": i + 1, "shortlisted": i < k} for i, m in enumerate(ranking)],
        "model_ids": ranking[:k],
    }


def select_leader_anchored_practical_tie(records: Sequence[Mapping[str, Any]], baseline_value: float, rule: Mapping[str, Any]) -> dict[str, Any]:
    """Eligibility over a baseline, leader by a validation metric, a
    leader-anchored practical-tie group, then ordered tie-breakers applied to
    the whole group until one candidate remains."""
    eligibility = rule["eligibility"]
    metric_field = f"validation_{eligibility['metric']}"
    # Orientation comes from the declared metric: improvement over the
    # baseline and the leader are "higher" for scores and "lower" for losses.
    eligibility_sign = -1.0 if metric_direction(eligibility["metric"]) == "min" else 1.0
    rows = []
    for record in records:
        margin = eligibility_sign * (float(record[metric_field]) - baseline_value)
        eligible = margin > eligibility["margin"] if eligibility.get("strict", True) else margin >= eligibility["margin"]
        rows.append({**record, "margin_over_baseline": margin, "eligible": bool(eligible)})
    leader_metric = rule["leader"]["metric"]
    leader_sign = -1.0 if rule["leader"].get("direction", metric_direction(leader_metric)) == "max" else 1.0
    eligible_rows = sorted(
        (r for r in rows if r["eligible"]),
        key=lambda r: (leader_sign * float(r[f"validation_{leader_metric}"]), r["model_id"]),
    )
    if not eligible_rows:
        return {"eligible_model_ids": [], "practical_tie_group": [], "practical_tie": False, "selected_model_id": None,
                "criteria_applied": [], "records": rows, "outcome": "no_eligible_candidate"}
    leader = eligible_rows[0]
    tie = rule["practical_tie"]
    leader_field = f"validation_{tie['metric']}"
    interval_metric = tie.get("cv_interval_metric", tie["metric"])
    lower_field, upper_field = f"cv_{interval_metric}_ci_lower", f"cv_{interval_metric}_ci_upper"

    tie_sign = -1.0 if metric_direction(tie["metric"]) == "min" else 1.0

    def within_tolerance(other: Mapping[str, Any]) -> bool:
        # Two float formulations a study may use; they can disagree at the
        # boundary (abs(2.1 - 2.0) > 0.1 while 2.1 <= 2.0 + 0.1), so the
        # contract declares which one it reproduces.
        if tie.get("bound", "absolute_difference") == "leader_plus_tolerance":
            if tie_sign < 0:
                return float(other[leader_field]) <= float(leader[leader_field]) + tie["tolerance"]
            return float(other[leader_field]) >= float(leader[leader_field]) - tie["tolerance"]
        return abs(float(leader[leader_field]) - float(other[leader_field])) <= tie["tolerance"]

    def tied(other: Mapping[str, Any]) -> bool:
        if not tie.get("requires_cv_interval_overlap", True):
            return within_tolerance(other)
        overlap = max(leader[lower_field], other[lower_field]) <= min(leader[upper_field], other[upper_field])
        return within_tolerance(other) and overlap

    group = [leader] + [r for r in eligible_rows[1:] if tied(r)]
    remaining = list(group)
    criteria = []
    if len(group) > 1:
        for breaker in rule["tie_breakers"]:
            values = {r["model_id"]: r[breaker["field"]] for r in remaining}
            if all(isinstance(v, (int, float)) for v in values.values()):
                best = (min if breaker["direction"] == "min" else max)(float(v) for v in values.values())
                survivors = [r for r in remaining if math.isclose(float(r[breaker["field"]]), best, rel_tol=0.0, abs_tol=_FLOAT_EQUALITY_ABS_TOL)]
            else:
                best_text = min(str(v) for v in values.values())
                survivors = [r for r in remaining if str(r[breaker["field"]]) == best_text]
            criteria.append({
                "criterion": breaker["criterion"],
                "values": _jsonable(values),
                "survivors": [r["model_id"] for r in survivors],
            })
            remaining = survivors
            if len(remaining) == 1:
                break
    runner_up = group[1] if len(group) > 1 else (eligible_rows[1] if len(eligible_rows) > 1 else None)
    return {
        "eligible_model_ids": [r["model_id"] for r in eligible_rows],
        "practical_tie_group": [r["model_id"] for r in group],
        "practical_tie": len(group) > 1,
        "leader_model_id": leader["model_id"],
        "leader_minus_runner_up": (float(leader[leader_field]) - float(runner_up[leader_field])) if runner_up else None,
        "selected_model_id": remaining[0]["model_id"],
        "deciding_criterion": criteria[-1]["criterion"] if criteria else (
            "lowest_validation_metric" if leader_sign > 0 else "highest_validation_metric"),
        "criteria_applied": criteria,
        "records": rows,
        "outcome": "selected",
    }


_SELECTION_RULES = {"leader_anchored_practical_tie": select_leader_anchored_practical_tie}


def threshold_max_precision_subject_to_min_recall(y_true: Sequence[int], probabilities: Sequence[float], policy: Mapping[str, Any]) -> dict[str, Any]:
    labels = [int(v) for v in y_true]
    candidates = sorted(set([0.0, 0.5, 1.0, *[float(p) for p in probabilities]]))
    pairs = sorted(zip((float(p) for p in probabilities), labels), key=lambda item: item[0])
    scores = [score for score, _ in pairs]
    prefix = [0]
    for _, label in pairs:
        prefix.append(prefix[-1] + int(label == 1))
    total, positives = len(pairs), prefix[-1]
    rows = []
    for threshold in candidates:
        index = bisect.bisect_left(scores, threshold)
        predicted = total - index
        tp = positives - prefix[index]
        precision = tp / predicted if predicted else 0.0
        recall = tp / positives if positives else 0.0
        f2_denominator = 4 * precision + recall
        rows.append({
            "threshold": float(threshold),
            "precision": float(precision),
            "recall": float(recall),
            "f2": float(5 * precision * recall / f2_denominator) if f2_denominator else 0.0,
        })
    satisfying = [r for r in rows if r["recall"] >= policy["min_recall"]]
    if not satisfying:
        return {"satisfied": False, "threshold": None, "candidate_threshold_count": len(rows)}
    order = policy.get("ordering", ["precision", "f2", "threshold"])
    chosen = max(satisfying, key=lambda r: tuple(float(r[f]) for f in order))
    return {"satisfied": True, "threshold": chosen["threshold"], "candidate_threshold_count": len(rows), "chosen_row": chosen}


_THRESHOLD_POLICIES = {"max_precision_subject_to_min_recall": threshold_max_precision_subject_to_min_recall}


# --------------------------------------------------------------------------
# task adapters (dispatch by problem_type, never by dataset)
# --------------------------------------------------------------------------


@dataclass
class Evaluation:
    """One evaluation of a fitted pipeline on one partition."""

    flat_metrics: dict[str, Any]
    detail: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)


class BinaryClassificationTask:
    """Positive-class probability, fixed default threshold and a threshold policy."""

    problem_type = BINARY

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        target = payload["problem"]["target"]
        self.encoding = {str(k): int(v) for k, v in target["encoding"].items()}
        self.positive_label = self.encoding[str(target["positive_class"])]
        self.default_threshold = float(payload["metrics"].get("default_threshold", 0.5))

    def labels(self, frame: Any, column: str) -> Any:
        return frame[column].map(self.encoding).astype("int64")

    def scoring(self) -> dict[str, Any]:
        return _scoring(self.positive_label)

    def class_order_evidence(self) -> dict[str, Any] | None:
        return None

    def validation_threshold(self) -> dict[str, Any]:
        return {"value": self.default_threshold, "rule": "fixed_default_threshold", "provenance": "scientific_study_contract"}

    def evaluate(self, estimator: Any, x: Any, y: Any) -> Evaluation:
        probabilities = _positive_probabilities(estimator, x, self.positive_label)
        metrics = {**probability_metrics(y, probabilities), **threshold_metrics(y, probabilities, self.default_threshold)}
        return Evaluation(flat_metrics=metrics, state={"probabilities": probabilities})

    def decide(self, engine: "Reproduction", result: "ReproductionResult", selected_id: str,
               validation: Evaluation, y_val: Any) -> dict[str, Any] | None:
        policy = self.payload["threshold_policy"]
        outcome = _THRESHOLD_POLICIES[policy["kind"]](y_val, validation.state["probabilities"], policy)
        if not outcome["satisfied"]:
            result.execution_notes.append("threshold policy could not be satisfied on validation")
            return None
        value = outcome["threshold"]
        result.actuals["threshold"] = {"value": value,
                                       "validation": threshold_metrics(y_val, validation.state["probabilities"], value)}
        return {"value": value, "rule": policy["kind"], "provenance": RUN_KIND, "selected_on_partition": policy["partition"]}

    def final_evaluation(self, engine: "Reproduction", result: "ReproductionResult", *, selected_id: str,
                         pipeline: Any, x_test: Any, y_test: Any, decision: Mapping[str, Any],
                         fit_rows: int, test_membership: str, context: Mapping[str, Any]) -> None:
        probabilities = _positive_probabilities(pipeline, x_test, self.positive_label)
        final = {
            "evaluation_count": 1,
            "fit_rows": fit_rows,
            "probability": probability_metrics(y_test, probabilities),
            "at_default_threshold": threshold_metrics(y_test, probabilities, self.default_threshold),
            "at_policy_threshold": threshold_metrics(y_test, probabilities, decision["value"]),
        }
        result.actuals["final_test"] = final
        for suffix, threshold in (("probability", None), ("at_default_threshold", self.validation_threshold()),
                                  ("at_policy_threshold", dict(decision))):
            result.metric_sets.append(engine._metric_set(
                result, metric_set_id=f"final_test.{selected_id}.{suffix}", scope=SCOPE_FINAL_TEST,
                partition="test", membership=test_membership, model_id=selected_id, threshold=threshold,
                metrics=final[suffix], feature_policy=context.get("feature_policy"),
                fit_partitions=context.get("fit_partitions"),
            ))

    def thresholds_section(self, result: "ReproductionResult") -> dict[str, Any]:
        payload = self.payload
        reference = next((i for i in payload["expected_evidence"]["values"] if i["quantity"] == "threshold.value"), None)
        return {
            "scientific_policy": {"provenance": "scientific_study_contract", "rule": payload["threshold_policy"]},
            "scientific_reference": {
                "provenance": STUDY_RUN_KIND,
                "value": reference["expected"] if reference else None,
                "source": reference["source"] if reference else None,
            },
            "scientific_reproduced": {
                "provenance": RUN_KIND,
                "run_id": result.run_id,
                "value": result.actuals.get("threshold", {}).get("value"),
                "rule_kind": payload["threshold_policy"]["kind"],
                "partition": payload["threshold_policy"]["partition"],
            },
            "atlas_native_operational": {
                "provenance": NATIVE_TRAINING_RUN_KIND,
                "value": None,
                "note": "Not part of this run. The Atlas-native operational threshold is governed by the "
                        "native execution contract's result_semantics and is never equated with a "
                        "scientific threshold.",
            },
        }


class MulticlassClassificationTask:
    """String labels, estimator-order -> public-order probability alignment, argmax decision."""

    problem_type = MULTICLASS

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        target = payload["problem"]["target"]
        self.classes = [str(c) for c in target["classes"]]
        self.estimator_order = [str(c) for c in target["estimator_class_order"]]
        self.public_order = [str(c) for c in target["public_class_order"]]
        self.decision_rule = dict(payload["problem"]["decision_rule"])
        self.tie_resolution = self.decision_rule.get("tie_resolution", "first_in_public_class_order")

    def labels(self, frame: Any, column: str) -> Any:
        labels = frame[column].astype(str)
        unexpected = sorted(set(labels) - set(self.classes))
        if unexpected:
            raise ScientificReproductionError("label_outside_class_contract", f"unexpected target labels {unexpected}")
        return labels

    def scoring(self) -> dict[str, Any]:
        metrics = self.payload["metrics"]
        return multiclass_scoring(metrics.get("cv_scorers") or [m for m in metrics["evaluated"] if m in MULTICLASS_CV_SCORERS])

    def class_order_evidence(self) -> dict[str, Any]:
        return {"estimator_class_order": self.estimator_order, "public_class_order": self.public_order}

    def validation_threshold(self) -> dict[str, Any]:
        return not_applicable(THRESHOLD_NOT_APPLICABLE_REASON)

    def evaluate(self, estimator: Any, x: Any, y: Any) -> Evaluation:
        raw = estimator.predict_proba(x)
        fitted = [str(c) for c in estimator.classes_]
        probabilities = align_probabilities_to_class_order(raw, fitted, self.public_order,
                                                           expected_estimator_order=self.estimator_order)
        predictions, ties = argmax_decisions(probabilities, self.public_order, fitted, self.tie_resolution)
        computed = multiclass_metrics(list(y), predictions, probabilities, self.public_order)
        return Evaluation(
            flat_metrics=computed["metrics"],
            detail={"per_class": computed["per_class"], "confusion_matrix": computed["confusion_matrix"],
                    "estimator_class_order": fitted, "argmax_ties": ties},
            state={"probabilities": probabilities, "predictions": predictions},
        )

    def decide(self, engine: "Reproduction", result: "ReproductionResult", selected_id: str,
               validation: Evaluation, y_val: Any) -> dict[str, Any]:
        decision = {"rule": self.decision_rule["kind"], "tie_resolution": self.tie_resolution,
                    "threshold": not_applicable(THRESHOLD_NOT_APPLICABLE_REASON), "provenance": RUN_KIND}
        result.actuals["decision"] = {"rule": self.decision_rule["kind"], "threshold_applicable": False,
                                      "positive_class_applicable": False}
        return decision

    def final_evaluation(self, engine: "Reproduction", result: "ReproductionResult", *, selected_id: str,
                         pipeline: Any, x_test: Any, y_test: Any, decision: Mapping[str, Any],
                         fit_rows: int, test_membership: str, context: Mapping[str, Any]) -> None:
        import pandas as pd

        evaluation = self.evaluate(pipeline, x_test, y_test)
        probabilities = evaluation.state["probabilities"]
        probability_bytes = pd.DataFrame(probabilities, columns=self.public_order).to_csv(
            index=False, lineterminator="\n").encode("utf-8")
        final = {
            "evaluation_count": 1,
            "fit_rows": fit_rows,
            "row_count": int(len(y_test)),
            "metrics": evaluation.flat_metrics,
            "per_class": evaluation.detail["per_class"],
            "confusion_matrix": evaluation.detail["confusion_matrix"],
            "estimator_class_order": evaluation.detail["estimator_class_order"],
            "public_class_order": list(self.public_order),
            "argmax_ties": evaluation.detail["argmax_ties"],
            "probability_matrix_sha256": _sha256_bytes(probability_bytes),
        }
        interpretive = self.payload.get("interpretive_evidence") or {}
        pairs_spec = interpretive.get("confusion_pairs")
        if pairs_spec:
            ranked = rank_confusion_pairs(final["confusion_matrix"])
            final["top_confusion_pairs"] = ranked[: int(pairs_spec["top_k"])]
            validation_confusion = context.get("selected_validation_confusion")
            if pairs_spec.get("focal_pairs") and validation_confusion is not None:
                validation_ranked = rank_confusion_pairs(validation_confusion)

                def mutual(rows: Sequence[Mapping[str, Any]], pair: Sequence[str]) -> int:
                    return next(r["mutual_errors"] for r in rows if set(r["class_pair"]) == set(pair))

                final["focal_confusion_pairs"] = [
                    {"class_pair": list(pair), "test_mutual_errors": mutual(ranked, pair),
                     "validation_mutual_errors": mutual(validation_ranked, pair)}
                    for pair in pairs_spec["focal_pairs"]
                ]
        if interpretive.get("repeated_profile_sensitivity"):
            final["repeated_profile_sensitivity"] = repeated_profile_sensitivity(
                context["final_features"], x_test, list(y_test), evaluation.state["predictions"],
                probabilities, self.public_order, evaluation.flat_metrics["macro_f1"],
            )
        result.actuals["final_test"] = final
        result.metric_sets.append(engine._metric_set(
            result, metric_set_id=f"final_test.{selected_id}", scope=SCOPE_FINAL_TEST, partition="test",
            membership=test_membership, model_id=selected_id, threshold=decision["threshold"],
            metrics={**evaluation.flat_metrics, "per_class": evaluation.detail["per_class"],
                     "confusion_matrix": evaluation.detail["confusion_matrix"]},
            feature_policy=context.get("feature_policy"), fit_partitions=context.get("fit_partitions"),
        ))

    def thresholds_section(self, result: "ReproductionResult") -> dict[str, Any]:
        return {
            "applicable": False,
            "reason": THRESHOLD_NOT_APPLICABLE_REASON,
            "decision_rule": dict(self.decision_rule),
            "positive_class": not_applicable("multiclass_problem_has_no_positive_class"),
            "scientific_policy": {"provenance": "scientific_study_contract", "rule": dict(self.payload["threshold_policy"])},
            "atlas_native_operational": {
                "provenance": NATIVE_TRAINING_RUN_KIND,
                "value": None,
                "note": "Not part of this run. The native multiclass decision is governed by the native execution "
                        "contract's result_semantics.",
            },
        }


def regression_metrics(y_true: Sequence[float], predictions: Sequence[float]) -> dict[str, float]:
    """Point-error metrics and aggregate residual diagnostics, natural orientation.

    Residual = observed - predicted; the residual standard deviation uses
    ``ddof=1``; absolute-error percentiles use ``numpy.quantile`` (linear).
    """
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error, r2_score

    truth, predicted = np.asarray(y_true, dtype=float), np.asarray(predictions, dtype=float)
    if truth.shape != predicted.shape or truth.ndim != 1 or not len(truth):
        raise ScientificReproductionError("misaligned_regression_vectors", "truth and predictions must be aligned 1-D vectors")
    if not np.isfinite(truth).all() or not np.isfinite(predicted).all():
        raise ScientificReproductionError("non_finite_regression_values", "truth and predictions must be finite")
    residuals = truth - predicted
    absolute = np.abs(residuals)
    return {
        "mae": float(mean_absolute_error(truth, predicted)),
        "rmse": float(mean_squared_error(truth, predicted) ** 0.5),
        "r2": float(r2_score(truth, predicted)),
        "medae": float(median_absolute_error(truth, predicted)),
        "residual_mean": float(residuals.mean()),
        "residual_standard_deviation": float(residuals.std(ddof=1)) if len(residuals) > 1 else 0.0,
        "max_absolute_error": float(absolute.max()),
        "absolute_error_p50": float(np.quantile(absolute, 0.5)),
        "absolute_error_p90": float(np.quantile(absolute, 0.9)),
        "absolute_error_p95": float(np.quantile(absolute, 0.95)),
        "row_count": int(len(truth)),
    }


def group_overlap_mask(reference_features: Any, evaluated_features: Any, group_columns: Sequence[str]) -> Any:
    """Per evaluated row: does its group key (declared columns) occur in the reference rows?"""
    import numpy as np
    import pandas as pd

    columns = list(group_columns)
    reference = pd.MultiIndex.from_frame(reference_features.loc[:, columns].reset_index(drop=True))
    evaluated = pd.MultiIndex.from_frame(evaluated_features.loc[:, columns].reset_index(drop=True))
    return np.asarray(evaluated.isin(reference), dtype=bool)


def group_overlap_diagnostic(reference_features: Any, evaluated_features: Any, y_true: Sequence[float],
                             predictions: Sequence[float], spec: Mapping[str, Any], evaluation: Mapping[str, Any],
                             subset_metrics: Any) -> dict[str, Any]:
    """Descriptive split of one existing prediction by group overlap with the fitting rows.

    It reuses predictions that were already made; it never fits, predicts,
    selects or alters a partition. Subsets smaller than
    ``minimum_subset_rows`` report their size without metrics.
    """
    import numpy as np

    seen = group_overlap_mask(reference_features, evaluated_features, spec["group_columns"])
    truth, predicted = np.asarray(y_true, dtype=float), np.asarray(predictions, dtype=float)
    minimum = int(spec["minimum_subset_rows"])

    def subset(mask: Any) -> dict[str, Any]:
        rows = int(mask.sum())
        if rows < minimum:
            return {"status": "insufficient_rows_for_stable_subset_metric", "row_count": rows}
        return {"status": "computed", "row_count": rows, "metrics": subset_metrics(truth[mask], predicted[mask])}

    return {
        "group_label": spec["group_label"],
        "group_columns": list(spec["group_columns"]),
        "evaluated_partition": evaluation["evaluated_partition"],
        "reference_partitions": list(evaluation["reference_partitions"]),
        "model": evaluation["model"],
        "evaluated_row_count": int(len(seen)),
        "seen_group_row_count": int(seen.sum()),
        "unseen_group_row_count": int((~seen).sum()),
        "seen_group_row_share": float(seen.mean()) if len(seen) else 0.0,
        "full": {"status": "computed", "row_count": int(len(seen)), "metrics": subset_metrics(truth, predicted)},
        "seen": subset(seen),
        "unseen": subset(~seen),
        "diagnostic_only": True,
        "used_for_selection": False,
    }


CONTINUOUS_NOT_APPLICABLE_REASON = "continuous_regression_point_prediction"


class ContinuousRegressionTask:
    """Continuous numeric target: point prediction, error metrics, no class concept.

    The target must be numeric, complete and finite and is kept as float64.
    There is no class order, positive class or decision threshold; every place
    a classification report carries one records an explicit not-applicable
    entry instead.
    """

    problem_type = REGRESSION

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.target = dict(payload["problem"]["target"])
        metrics = payload["metrics"]
        self.cv_metrics = list(metrics.get("cv_scorers") or [m for m in metrics["evaluated"] if m in REGRESSION_CV_SCORERS])
        self.refit_metric = metrics.get("refit", metrics["primary"])

    def labels(self, frame: Any, column: str) -> Any:
        import numpy as np
        import pandas as pd

        values = frame[column]
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            raise ScientificReproductionError("non_numeric_regression_target", f"{column} must be numeric")
        converted = values.astype("float64")
        if converted.isna().any() or not np.isfinite(converted.to_numpy()).all():
            raise ScientificReproductionError("incomplete_regression_target", f"{column} must be complete and finite")
        return converted

    def scoring(self) -> dict[str, Any]:
        return regression_scoring(self.cv_metrics)

    def refit_key(self) -> str:
        if self.refit_metric not in REGRESSION_CV_SCORERS:
            raise ScientificReproductionError("unsupported_cv_scorer", self.refit_metric)
        return REGRESSION_CV_SCORERS[self.refit_metric][0]

    def class_order_evidence(self) -> None:
        return None

    def partition_evidence(self, y: Any) -> dict[str, Any]:
        y = self.labels(y.to_frame(name="target"), "target")
        return {"target_summary": {"count": int(len(y)), "minimum": float(y.min()), "maximum": float(y.max()),
                                   "mean": float(y.mean()), "median": float(y.median()),
                                   "standard_deviation": float(y.std(ddof=1)) if len(y) > 1 else 0.0,
                                   "diagnostic_only": True}}

    def validation_threshold(self) -> dict[str, Any]:
        return not_applicable(CONTINUOUS_NOT_APPLICABLE_REASON)

    def subset_metrics(self, y_true: Any, predictions: Any) -> dict[str, float]:
        return regression_metrics(y_true, predictions)

    def evaluate(self, estimator: Any, x: Any, y: Any) -> Evaluation:
        import numpy as np

        predictions = np.asarray(estimator.predict(x), dtype=float)
        return Evaluation(flat_metrics=regression_metrics(list(y), predictions), state={"predictions": predictions})

    def decide(self, engine: "Reproduction", result: "ReproductionResult", selected_id: str,
               validation: Evaluation, y_val: Any) -> dict[str, Any]:
        result.actuals["decision"] = {"rule": "continuous_point_prediction", "threshold_applicable": False,
                                      "positive_class_applicable": False, "class_order_applicable": False}
        return {"rule": "continuous_point_prediction", "threshold": not_applicable(CONTINUOUS_NOT_APPLICABLE_REASON),
                "provenance": RUN_KIND}

    def final_evaluation(self, engine: "Reproduction", result: "ReproductionResult", *, selected_id: str,
                         pipeline: Any, x_test: Any, y_test: Any, decision: Mapping[str, Any],
                         fit_rows: int, test_membership: str, context: Mapping[str, Any]) -> None:
        # Exactly one prediction on the test partition; every test quantity,
        # including the descriptive diagnostics, derives from it.
        evaluation = self.evaluate(pipeline, x_test, y_test)
        result.actuals["final_test"] = {"evaluation_count": 1, "prediction_call_count": 1, "fit_rows": fit_rows,
                                        "row_count": int(len(y_test)), "metrics": evaluation.flat_metrics}
        result.stages["final_test_predictions"] = evaluation.state["predictions"]
        result.metric_sets.append(engine._metric_set(
            result, metric_set_id=f"final_test.{selected_id}", scope=SCOPE_FINAL_TEST, partition="test",
            membership=test_membership, model_id=selected_id, threshold=decision["threshold"],
            metrics=evaluation.flat_metrics, feature_policy=context.get("feature_policy"),
            fit_partitions=context.get("fit_partitions"),
        ))

    def problem_section(self) -> dict[str, Any]:
        problem = self.payload["problem"]
        return {
            "problem_type": self.problem_type,
            "target_column": self.target["column"],
            "target": {key: self.target[key] for key in ("semantics", "unit", "value_representation", "value_validation")
                       if key in self.target},
            "classes": None,
            "positive_class": not_applicable("continuous_regression_has_no_positive_class"),
            "decision_rule": {"kind": "continuous_point_prediction"},
            "class_order": None,
            "classification_concepts": dict(problem["classification_concepts"]),
        }

    def thresholds_section(self, result: "ReproductionResult") -> dict[str, Any]:
        return {
            "applicable": False,
            "reason": CONTINUOUS_NOT_APPLICABLE_REASON,
            "decision_rule": {"kind": "continuous_point_prediction"},
            "positive_class": not_applicable("continuous_regression_has_no_positive_class"),
            "class_order": not_applicable("continuous_regression_has_no_class_order"),
            "scientific_policy": {"provenance": "scientific_study_contract",
                                  "rule": not_applicable("continuous_regression_has_no_classification_threshold")},
            "atlas_native_operational": {
                "provenance": NATIVE_TRAINING_RUN_KIND,
                "value": None,
                "note": "Not part of this run. A native continuous-regression release has no decision threshold.",
            },
        }


TASK_ADAPTERS = {BINARY: BinaryClassificationTask, MULTICLASS: MulticlassClassificationTask,
                 REGRESSION: ContinuousRegressionTask}


def task_adapter(payload: Mapping[str, Any]) -> Any:
    problem_type = payload["problem"]["problem_type"]
    adapter = TASK_ADAPTERS.get(problem_type)
    if adapter is None:
        raise ScientificReproductionError("unsupported_problem_type", problem_type)
    return adapter(payload)


# --------------------------------------------------------------------------
# comparison and status
# --------------------------------------------------------------------------


def _lookup(tree: Mapping[str, Any], quantity: str) -> tuple[bool, Any]:
    node: Any = tree
    for part in quantity.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False, None
        node = node[part]
    return True, node


def compare_item(item: Mapping[str, Any], actuals: Mapping[str, Any], tolerance_policy: Mapping[str, Any]) -> dict[str, Any]:
    found, actual = _lookup(actuals, item["quantity"])
    expected = item["expected"]
    base = {"quantity": item["quantity"], "comparison": item["comparison"], "expected": expected,
            "actual": _jsonable(actual) if found else None, "source": item["source"]}
    if not found:
        return {**base, "delta": None, "tolerance": None, "outcome": OUTCOME_MISSING}
    if item["comparison"] == "exact":
        return {**base, "delta": None, "tolerance": None, "outcome": OUTCOME_EXACT if _jsonable(actual) == expected else OUTCOME_MISMATCH}
    if actual is None or expected is None:
        return {**base, "delta": None, "tolerance": None, "outcome": OUTCOME_EXACT if actual == expected else OUTCOME_MISMATCH}
    delta = float(actual) - float(expected)
    if item["comparison"] == "count":
        tolerance = float(tolerance_policy["count_absolute"])
        outcome = OUTCOME_EXACT if delta == 0 else (OUTCOME_WITHIN if abs(delta) <= tolerance else OUTCOME_OUTSIDE)
        return {**base, "delta": delta, "tolerance": tolerance, "outcome": outcome}
    places = item.get("reported_decimal_places")
    quantization = 0.5 * 10 ** (-places) if places is not None else 0.0
    tolerance = max(float(tolerance_policy["numeric_absolute"]), quantization)
    rounding_matches = places is not None and round(float(actual), places) == round(float(expected), places)
    if abs(delta) <= quantization + _FLOAT_EQUALITY_ABS_TOL or rounding_matches:
        outcome = OUTCOME_EXACT
    elif abs(delta) <= tolerance:
        outcome = OUTCOME_WITHIN
    else:
        outcome = OUTCOME_OUTSIDE
    return {**base, "delta": delta, "reported_precision_half_unit": quantization, "tolerance": tolerance, "outcome": outcome}


def compare_with_expected_evidence(expected_evidence: Mapping[str, Any], actuals: Mapping[str, Any], tolerance_policy: Mapping[str, Any]) -> dict[str, Any]:
    values = [compare_item(item, actuals, tolerance_policy) for item in expected_evidence["values"]]
    decisions = [compare_item(item, actuals, tolerance_policy) for item in expected_evidence["decisions"]]
    everything = values + decisions
    comparison = {
        "tolerance_policy": dict(tolerance_policy),
        "values": values,
        "decisions": decisions,
        "counts": {
            outcome: sum(1 for c in everything if c["outcome"] == outcome)
            for outcome in (OUTCOME_EXACT, OUTCOME_WITHIN, OUTCOME_OUTSIDE, OUTCOME_MISMATCH, OUTCOME_MISSING)
        },
        "all_within_tolerance": all(c["outcome"] in (OUTCOME_EXACT, OUTCOME_WITHIN) for c in everything),
        "all_exact_at_reported_precision": all(c["outcome"] == OUTCOME_EXACT for c in everything),
    }
    runtime_items = expected_evidence.get("runtime_identity")
    if runtime_items is not None:
        # Byte-level runtime identity never decides scientific agreement.
        runtime = [compare_item(item, actuals, tolerance_policy) for item in runtime_items]
        comparison["runtime_identity"] = runtime
        comparison["byte_identical_runtime"] = all(c["outcome"] == OUTCOME_EXACT for c in runtime) if runtime else None
    return comparison


def evidence_tiers(comparison: Mapping[str, Any] | None, environment_classification: str,
                   protocol_gaps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Separate the kinds of agreement a reproduction can establish."""
    if comparison is None:
        return {"structural_exact": None, "numeric_exact_at_reported_precision": None,
                "numeric_within_tolerance": None, "environment": environment_classification,
                "byte_identical_runtime": None, "unsupported_capabilities": len(protocol_gaps),
                "scientific_mismatches": None}
    compared = comparison["values"] + comparison["decisions"]
    structural = [c for c in compared if c["comparison"] in ("exact", "count")]
    numeric = [c for c in compared if c["comparison"] == "numeric"]
    return {
        "structural_exact": all(c["outcome"] == OUTCOME_EXACT for c in structural),
        "numeric_exact_at_reported_precision": all(c["outcome"] == OUTCOME_EXACT for c in numeric),
        "numeric_within_tolerance": all(c["outcome"] in (OUTCOME_EXACT, OUTCOME_WITHIN) for c in numeric),
        "environment": environment_classification,
        "byte_identical_runtime": comparison.get("byte_identical_runtime"),
        "unsupported_capabilities": len(protocol_gaps),
        "scientific_mismatches": sum(1 for c in compared if c["outcome"] in (OUTCOME_OUTSIDE, OUTCOME_MISMATCH)),
    }


def compute_reproduction_status(
    *,
    protocol_gaps: Sequence[Mapping[str, Any]],
    environment_classification: str,
    dataset_verified: bool,
    executed: bool,
    comparison: Mapping[str, Any] | None,
    evidence_gaps: Sequence[Mapping[str, Any]],
    gate_failures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Map run facts to exactly one reproduction status (divergence is never masked)."""
    reasons: list[str] = []
    if not dataset_verified:
        return {"status": STATUS_DATASET_MISMATCH, "reasons": ["dataset bytes do not match the pinned identity"]}
    if protocol_gaps:
        return {"status": STATUS_CAPABILITY_MISSING,
                "reasons": [f"{g['element']}={g['value']!r}: {g['reason']}" for g in protocol_gaps]}
    if environment_classification == scientific_environment.INCOMPATIBLE:
        return {"status": STATUS_ENVIRONMENT_INCOMPATIBLE,
                "reasons": ["the reproduction runtime crosses a declared environment compatibility boundary"]}
    if gate_failures:
        return {"status": STATUS_DIVERGENT,
                "reasons": [f"protocol gate failed: {g['gate']}: {g['detail']}" for g in gate_failures]}
    if not executed or comparison is None:
        return {"status": STATUS_INSUFFICIENT_EVIDENCE, "reasons": ["the reproduction did not execute"]}
    diverging = [c["quantity"] for c in comparison["values"] + comparison["decisions"] if c["outcome"] in (OUTCOME_OUTSIDE, OUTCOME_MISMATCH)]
    if diverging:
        return {"status": STATUS_DIVERGENT, "reasons": [f"outside tolerance or mismatched: {q}" for q in diverging]}
    missing = [c["quantity"] for c in comparison["values"] + comparison["decisions"] if c["outcome"] == OUTCOME_MISSING]
    blocking = [g for g in evidence_gaps if g["severity"] == "blocking"]
    if missing or blocking or not comparison["values"]:
        reasons = [f"reproduction produced no value for expected quantity {q}" for q in missing]
        reasons += [f"blocking evidence gap {g['gap_id']}: {g['description']}" for g in blocking]
        if not comparison["values"]:
            reasons.append("the study contract declares no expected numeric evidence")
        return {"status": STATUS_INSUFFICIENT_EVIDENCE, "reasons": reasons}
    runtime_note = None
    if comparison.get("byte_identical_runtime") is False:
        runtime_note = ("runtime byte identity differs (e.g. probability-matrix bytes); the scientific protocol "
                        "agreement is unaffected")
    if (environment_classification == scientific_environment.EXACT and comparison["all_exact_at_reported_precision"]
            and comparison.get("byte_identical_runtime") is not False):
        return {"status": STATUS_REPRODUCED_EXACT, "reasons": []}
    if environment_classification != scientific_environment.EXACT:
        reasons.append(f"environment classified as {environment_classification}")
    if not comparison["all_exact_at_reported_precision"]:
        reasons.append("some quantities differ beyond reported precision but within the declared tolerance")
    if runtime_note:
        reasons.append(runtime_note)
    return {"status": STATUS_REPRODUCED_WITHIN_TOLERANCE, "reasons": reasons}


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def _task_type(problem_type: str) -> str:
    return model_families.CLASSIFICATION if problem_type.endswith("classification") else model_families.REGRESSION


def _class_counts(series: Any) -> dict[str, int]:
    return {_key(k): int(v) for k, v in series.value_counts().items()}


def _target_evidence(task: Any, y: Any) -> dict[str, Any]:
    """Per-partition target evidence: class counts, or a continuous-target summary."""
    if hasattr(task, "partition_evidence"):
        return task.partition_evidence(y)
    return {"class_counts": _class_counts(y)}


@dataclass
class ReproductionResult:
    plan: "Reproduction"
    run_id: str
    created_at: str
    dataset_verification: dict[str, Any]
    executed: bool
    actuals: dict[str, Any] = field(default_factory=dict)
    metric_sets: list[dict[str, Any]] = field(default_factory=list)
    search_results: dict[str, Any] = field(default_factory=dict)
    candidate_models_executed: list[str] = field(default_factory=list)
    execution_notes: list[str] = field(default_factory=list)
    gate_failures: list[dict[str, Any]] = field(default_factory=list)
    gate_checks: list[dict[str, Any]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)

    def compare_with_reference(self) -> dict[str, Any] | None:
        if not self.executed:
            return None
        payload = self.plan.contract.payload
        return compare_with_expected_evidence(payload["expected_evidence"], self.actuals, payload["tolerance_policy"])

    def build_report(self) -> dict[str, Any]:
        contract = self.plan.contract
        payload = contract.payload
        comparison = self.compare_with_reference()
        status = compute_reproduction_status(
            protocol_gaps=self.plan.protocol_gaps,
            environment_classification=self.plan.environment["classification"],
            dataset_verified=self.dataset_verification["verified"],
            executed=self.executed,
            comparison=comparison,
            evidence_gaps=payload["evidence_gaps"],
            gate_failures=self.gate_failures,
        )
        status["evidence_tiers"] = evidence_tiers(comparison, self.plan.environment["classification"], self.plan.protocol_gaps)
        problem = payload["problem"]
        try:
            task = task_adapter(payload)
        except ScientificReproductionError:
            task = None
        candidates_expected = [c["model_id"] for c in payload["candidates"]]
        split = payload["split"]
        membership = membership_spec(split)
        report_version = (REPORT_SCHEMA_VERSION_V3 if payload["schema_version"] == CONTRACT_SCHEMA_VERSION_V3
                          else REPORT_SCHEMA_VERSION)
        if task is not None and hasattr(task, "problem_section"):
            problem_section = task.problem_section()
        else:
            problem_section = {
                "problem_type": problem["problem_type"],
                "target_column": problem["target"]["column"],
                "classes": problem["target"].get("classes"),
                "positive_class": problem["target"].get("positive_class"),
                "decision_rule": problem.get("decision_rule") or {"kind": "probability_threshold"},
                "class_order": ({**task.class_order_evidence(),
                                 "fitted_estimator_class_order": self.actuals.get("final_test", {}).get("estimator_class_order")}
                                if task is not None and task.class_order_evidence() else None),
            }
        report = {
            "schema_version": report_version,
            "artifact_kind": "scientific_reproduction_report",
            "run_identity": {
                "run_kind": RUN_KIND,
                "run_id": self.run_id,
                "dataset_slug": contract.dataset_slug,
                "created_at": self.created_at,
                "producer": ENGINE_ID,
                "engine_version": ENGINE_VERSION,
            },
            "evidence_lineage": {
                STUDY_RUN_KIND: {
                    "role": "reference_evidence",
                    "study_id": payload["study_identity"]["study_id"],
                    "source_repository": payload["source_repository"]["url"],
                    "study_revision": contract.study_revision,
                    "study_contract": contract.reference(),
                    "canonical_run": payload.get("canonical_run"),
                },
                RUN_KIND: {"role": "independent_atlas_reproduction", "run_id": self.run_id},
                NATIVE_TRAINING_RUN_KIND: {
                    "role": "separate_lineage",
                    "referenced": False,
                    "relationship": "not an input to and not an output of this reproduction",
                },
                RELEASE_KIND: {
                    "role": "separate_lineage",
                    "referenced": False,
                    "relationship": "a scientific reproduction never creates, modifies, replaces, or activates an Atlas release",
                },
            },
            "dataset": {
                "dataset_slug": contract.dataset_slug,
                "atlas_local_path": payload["dataset_identity"]["atlas_local_path"],
                **self.dataset_verification,
            },
            "environment": {
                "scientific_reference": {
                    "python": payload["scientific_environment"]["python"],
                    "platform": payload["scientific_environment"].get("platform"),
                    "core_packages": payload["scientific_environment"]["core_packages"],
                    "lock": payload["scientific_environment"]["lock"],
                },
                "reproduction_runtime": self.plan.runtime,
                "compatibility": self.plan.environment,
                "interpretation": ("'same scientific protocol' is established by the comparison; 'byte-identical "
                                   "runtime' only by an exact environment and matching runtime-identity evidence."),
            },
            "protocol_support": {
                "status": "fully_supported" if not self.plan.protocol_gaps else "unsupported_elements_present",
                "gaps": self.plan.protocol_gaps,
            },
            "source_verification": self.plan.source_verification,
            "problem": problem_section,
            "split": {
                "kind": split["kind"],
                "algorithm": _SPLIT_ALGORITHMS.get(split["kind"], split["kind"]),
                "fractions": split["fractions"],
                "stratify_by": split["stratify_by"],
                "seeds_used": dict(split["seeds"]),
                "membership": membership,
                "observed": self.actuals.get("partitions"),
                "gate": self.stages.get("membership_gate"),
            },
            "candidate_models": {
                "expected": candidates_expected,
                "executed": list(self.candidate_models_executed),
                "baseline": payload.get("baseline", {}).get("model_id"),
                "search_spaces": {
                    c["model_id"]: {
                        "family": c["family"],
                        "search_kind": c["search"]["kind"],
                        "space": c["search"].get("space", {}),
                        "fixed_params": c["fixed_params"],
                        "numerical_scaling": c["numerical_scaling"],
                        "candidate_count_expected": self.actuals.get("search", {}).get(c["model_id"], {}).get("candidate_count_expected"),
                        "candidate_count_executed": self.actuals.get("search", {}).get(c["model_id"], {}).get("candidate_count_executed"),
                    }
                    for c in payload["candidates"]
                },
            },
            "family_search": self.stages.get("family_search", []),
            "family_shortlist": self.stages.get("family_shortlist"),
            "feature_policy_stage": self.stages.get("feature_policy_stage"),
            "selection": {
                "rule": payload["selection"],
                "candidate_space": self.stages.get("selection_candidate_space"),
                "executed": self.actuals.get("selection_trace"),
            },
            "final_fit": self.stages.get("final_fit"),
            "thresholds": task.thresholds_section(self) if task is not None else None,
            "metric_sets": self.metric_sets,
            "comparison": comparison,
            "gate_checks": self.gate_checks,
            "evidence_gaps": payload["evidence_gaps"],
            "study_observations": payload.get("study_observations", []),
            "protocol_integrity": payload.get("protocol_integrity"),
            "execution_notes": self.execution_notes,
            "limitations": payload["limitations"],
            "reproduction_status": status,
            "immutability": {
                "write_once": True,
                "historical_artifacts_modified": False,
                "supersedes": None,
            },
        }
        if report_version == REPORT_SCHEMA_VERSION_V3:
            report["interpretive_diagnostics"] = _jsonable(self.stages.get("interpretive_diagnostics"))
        return report


@dataclass
class Reproduction:
    contract: ScientificStudyContract
    repo_root: Path
    dataset_path: Path
    runtime: dict[str, Any]
    environment: dict[str, Any]
    protocol_gaps: list[dict[str, Any]]
    source_verification: dict[str, Any]

    def run(self, *, run_id: str | None = None, n_jobs: int | None = None, allow_incompatible_environment: bool = False) -> ReproductionResult:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = run_id or "repro-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload = self.contract.payload
        verification = verify_dataset_identity(self.dataset_path, payload["dataset_identity"])
        result = ReproductionResult(plan=self, run_id=run_id, created_at=created_at, dataset_verification=verification, executed=False)
        if not verification["verified"]:
            return result
        if self.protocol_gaps:
            result.execution_notes.append("not executed: the protocol contains elements Atlas cannot execute")
            return result
        if self.environment["classification"] == scientific_environment.INCOMPATIBLE and not allow_incompatible_environment:
            result.execution_notes.append("not executed: incompatible environment")
            return result
        completed = self._execute(result, n_jobs=n_jobs)
        result.executed = bool(completed)
        return result

    def _metric_set(self, result: ReproductionResult, *, metric_set_id: str, partition: str, membership: str | None,
                    model_id: str, threshold: Mapping[str, Any] | None, metrics: Mapping[str, Any],
                    scope: str | None = None, feature_policy: str | None = None,
                    fit_partitions: Sequence[str] | None = None) -> dict[str, Any]:
        payload = self.contract.payload
        task = task_adapter(payload)
        class_order = task.class_order_evidence()
        return {
            "metric_set_id": metric_set_id,
            "provenance": {
                "producer_lineage": RUN_KIND,
                "metric_scope": scope,
                "problem_type": payload["problem"]["problem_type"],
                "run_id": result.run_id,
                "study_revision": self.contract.study_revision,
                "study_contract_sha256": self.contract.sha256,
                "dataset_sha256": payload["dataset_identity"]["sha256"],
                "partition": partition,
                "partition_membership_sha256": membership,
                "model_id": model_id,
                "feature_policy": feature_policy,
                "fit_partitions": list(fit_partitions) if fit_partitions else None,
                "threshold": dict(threshold) if threshold else None,
                "class_order": class_order["public_class_order"] if class_order else None,
                "protocol_kind": payload["study_identity"]["protocol_kind"],
            },
            "metrics": _jsonable(dict(metrics)),
        }

    def _gate(self, result: ReproductionResult, gate: str, expected: Any, observed: Any, source: Any = None) -> bool:
        passed = _jsonable(expected) == _jsonable(observed)
        check = {"gate": gate, "expected": _jsonable(expected), "observed": _jsonable(observed), "passed": passed,
                 "expected_provenance": "reference evidence used as a protocol precondition", "source": source}
        result.gate_checks.append(check)
        if not passed:
            result.gate_failures.append({"gate": gate, "detail": f"expected {expected!r}, observed {observed!r}"})
            result.execution_notes.append(f"stopped: protocol gate {gate} failed; no later stage was executed")
        return passed

    def _execute(self, result: ReproductionResult, *, n_jobs: int | None) -> bool:
        import pandas as pd

        payload = self.contract.payload
        task = task_adapter(payload)
        task_type = _task_type(payload["problem"]["problem_type"])
        target_column = payload["problem"]["target"]["column"]
        identifiers = payload["problem"]["identifier_columns"]
        features = list(payload["features"]["feature_columns"])
        search_execution = payload.get("search_execution", {})
        jobs = n_jobs if n_jobs is not None else int(search_execution.get("n_jobs", 1))
        if n_jobs is not None and n_jobs != search_execution.get("n_jobs"):
            result.execution_notes.append(
                f"search n_jobs={n_jobs} (study used {search_execution.get('n_jobs')}); "
                "parallelism does not change search results"
            )
        actuals = result.actuals
        scoring = task.scoring()
        refit_key = task.refit_key() if hasattr(task, "refit_key") else None

        raw = load_dataset(self.dataset_path, payload["dataset_identity"])
        actuals["dataset"] = {"sha256": result.dataset_verification["observed_sha256"],
                              "rows": int(raw.shape[0]), "columns": int(raw.shape[1])}
        prepared, preparation_evidence = apply_preparation(raw, payload["preparation"])
        actuals["preparation"] = preparation_evidence

        # Split, membership evidence, and the membership gate.
        split = payload["split"]
        spec = membership_spec(split)
        partitions, partition_keys = _SPLITTERS[split["kind"]](prepared, split, identifiers)
        fingerprint = split.get("partition_fingerprint")
        partition_hashes = ({name: partition_csv_sha256(frame, fingerprint.get("float_format"))
                             for name, frame in partitions.items()} if fingerprint else {})
        handoff = _handoff_spec(split)
        if handoff["kind"] == "csv_roundtrip":
            partitions = {name: csv_roundtrip(frame, handoff.get("float_format")) for name, frame in partitions.items()}
        if spec["kind"] == "identifier" and "membership" not in split:
            # v1 behaviour: digest of sorted identifier keys of the handed-off partition.
            memberships = {name: membership_sha256(frame, identifiers) for name, frame in partitions.items()}
        else:
            memberships = {name: membership_digest(partition_keys[name], spec["digest_order"]) for name in partitions}
        actuals["partitions"] = {
            name: {
                "rows": len(frame),
                **_target_evidence(task, frame[target_column]),
                "membership_sha256": memberships[name],
                **({"partition_sha256": partition_hashes[name]} if partition_hashes else {}),
            }
            for name, frame in partitions.items()
        }
        gate = split.get("membership_gate")
        if gate and gate.get("required", True):
            passed = self._gate(result, "split.membership_sha256", gate["expected_membership_sha256"],
                                {name: memberships[name] for name in ("train", "validation", "test")}, gate["source"])
            result.stages["membership_gate"] = {"required": True, "passed": passed}
            if not passed:
                return False

        def xy(frame: Any, columns: Sequence[str] = features) -> tuple[Any, Any]:
            return frame.loc[:, list(columns)].copy(deep=True), task.labels(frame, target_column)

        x_train, y_train = xy(partitions["train"])
        x_val, y_val = xy(partitions["validation"])

        # Baseline (reference only, never selectable).
        baseline = payload.get("baseline")
        baseline_value = None
        if baseline:
            base_pipeline = build_candidate_pipeline(baseline, payload, task_type).fit(x_train, y_train)
            base_eval = task.evaluate(base_pipeline, x_val, y_val)
            actuals["baseline"] = {"validation": base_eval.flat_metrics}
            baseline_value = base_eval.flat_metrics[payload["selection"]["eligibility"]["metric"]]
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"validation.{baseline['model_id']}", partition="validation",
                scope=SCOPE_BASELINE_VALIDATION, membership=memberships["validation"], model_id=baseline["model_id"],
                threshold=task.validation_threshold(), metrics=base_eval.flat_metrics,
            ))

        # Family search on train only.
        actuals["search"], actuals["cv"], actuals["validation"] = {}, {}, {}
        simplicity = payload["selection"].get("simplicity_order", [])
        candidates = {c["model_id"]: c for c in payload["candidates"]}
        search_outcomes: dict[str, Any] = {}
        family_stage = []
        for candidate in payload["candidates"]:
            model_id = candidate["model_id"]
            outcome = run_candidate_search(candidate, payload, x_train, y_train, n_jobs=jobs,
                                           task_type=task_type, scoring=scoring, refit=refit_key)
            result.candidate_models_executed.append(model_id)
            summary = outcome["summary"]
            search_outcomes[model_id] = outcome
            actuals["search"][model_id] = {
                "candidate_count_expected": summary["candidate_count_expected"],
                "candidate_count_executed": summary["candidate_count_executed"],
                "best_params": summary["best_params"],
                "pipeline_best_params": summary["pipeline_best_params"],
                "search_strategy": summary["search_strategy"],
                "search_random_state": summary["search_random_state"],
                "search_duration_seconds": summary["search_duration_seconds"],
            }
            actuals["cv"][model_id] = {
                k: v for k, v in summary.items() if k.endswith(("_mean", "_std", "_ci_lower", "_ci_upper"))
            }
            result.search_results[model_id] = outcome["table"]
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"cross_validation.{model_id}", partition="train_cross_validation",
                scope=SCOPE_FAMILY_SEARCH_CV, membership=memberships["train"], model_id=model_id, threshold=None,
                metrics=actuals["cv"][model_id], feature_policy=None,
            ))
            family_stage.append({
                "model_id": model_id,
                "family": candidate["family"],
                "study_estimator_class": candidate.get("study_estimator_class"),
                "search_strategy": summary["search_strategy"],
                "declared_search_space": candidate["search"].get("space", {}),
                "fixed_params": candidate["fixed_params"],
                "candidate_count_expected": summary["candidate_count_expected"],
                "candidate_count_executed": summary["candidate_count_executed"],
                "random_seed": summary["search_random_state"],
                "best_params": summary["best_params"],
                "best_score": {"metric": summary["refit_metric"], "value": summary["best_score"]},
                "cv_metrics": actuals["cv"][model_id],
                "fit_partition": "train",
            })
        result.stages["family_search"] = family_stage

        # Candidate variants evaluated on validation: either the searched
        # families themselves, or shortlist x feature policies.
        variants: list[dict[str, Any]] = []
        policies_spec = payload.get("feature_policies")
        if policies_spec:
            shortlist = shortlist_top_k(actuals["cv"], payload["family_shortlist"])
            actuals["shortlist"] = {"model_ids": shortlist["model_ids"]}
            result.stages["family_shortlist"] = shortlist
            actuals["feature_policy"] = {}
            for base_id in shortlist["model_ids"]:
                for policy in policies_spec["policies"]:
                    columns = [c for c in features if c not in set(policy["exclude"])]
                    variant_id = policies_spec["candidate_id_pattern"].format(model_id=base_id, policy_id=policy["policy_id"])
                    variants.append({"model_id": variant_id, "base_model_id": base_id,
                                     "feature_policy": policy["policy_id"], "feature_columns": columns})
            result.stages["selection_candidate_space"] = "family_shortlist_x_feature_policies"
        else:
            for model_id in candidates:
                variants.append({"model_id": model_id, "base_model_id": model_id, "feature_policy": None,
                                 "feature_columns": features})
            result.stages["selection_candidate_space"] = "searched_families"

        cv_folds = _cross_validator(payload["cross_validation"])
        refit = refit_key or payload["metrics"].get("refit", payload["metrics"]["primary"])
        z_value = float(payload["selection"].get("practical_tie", {}).get("cv_interval_z", 1.96))
        validation_evals: dict[str, Evaluation] = {}
        variant_cv: dict[str, dict[str, float]] = {}
        records = []
        for variant in variants:
            model_id, base_id = variant["model_id"], variant["base_model_id"]
            candidate = candidates[base_id]
            best_params = actuals["search"][base_id]["best_params"]
            if variant["feature_policy"] is None:
                fitted = search_outcomes[base_id]["best_estimator"]
                cv_summary = actuals["cv"][base_id]
            else:
                from sklearn.base import clone
                from sklearn.model_selection import cross_validate

                columns = variant["feature_columns"]
                pipeline = build_candidate_pipeline(candidate, payload, task_type, extra_params=best_params,
                                                    feature_columns=columns)
                cv_results = cross_validate(clone(pipeline), x_train.loc[:, columns].copy(deep=True), y_train.copy(deep=True),
                                            scoring=dict(scoring), cv=cv_folds, n_jobs=jobs,
                                            return_train_score=False, error_score="raise")
                cv_summary = _cv_summary(cv_results, scoring, refit, None, int(payload["cross_validation"]["n_splits"]), z_value)
                fitted = pipeline.fit(x_train.loc[:, columns], y_train)
                result.metric_sets.append(self._metric_set(
                    result, metric_set_id=f"cross_validation.{model_id}", partition="train_cross_validation",
                    scope=SCOPE_FEATURE_POLICY_CV, membership=memberships["train"], model_id=model_id, threshold=None,
                    metrics=cv_summary, feature_policy=variant["feature_policy"],
                ))
            variant_cv[model_id] = cv_summary
            evaluation = task.evaluate(fitted, x_val.loc[:, variant["feature_columns"]], y_val)
            validation_evals[model_id] = evaluation
            actuals["validation"][model_id] = evaluation.flat_metrics
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"validation.{model_id}", partition="validation",
                scope=SCOPE_CANDIDATE_VALIDATION, membership=memberships["validation"], model_id=model_id,
                threshold=task.validation_threshold(), metrics=evaluation.flat_metrics,
                feature_policy=variant["feature_policy"],
            ))
            records.append({
                "model_id": model_id,
                "family": candidate["family"],
                **{f"validation_{k}": v for k, v in evaluation.flat_metrics.items() if isinstance(v, float)},
                **{f"cv_{k}": v for k, v in cv_summary.items()},
                "simplicity_rank": simplicity.index(candidate["family"]) if candidate["family"] in simplicity else len(simplicity),
            })

        # Selection.
        selection_rule = _SELECTION_RULES[payload["selection"]["kind"]]
        selection = selection_rule(records, float(baseline_value) if baseline_value is not None else 0.0, payload["selection"])
        actuals["selection_trace"] = _jsonable(selection)
        eligibility = {r["model_id"]: r["eligible"] for r in selection["records"]}
        if policies_spec:
            stage_rows = []
            for variant in variants:
                model_id = variant["model_id"]
                cv_summary = variant_cv[model_id]
                row = {
                    "model_id": model_id,
                    "base_model_id": variant["base_model_id"],
                    "family": candidates[variant["base_model_id"]]["family"],
                    "feature_policy": variant["feature_policy"],
                    "feature_count": len(variant["feature_columns"]),
                    "feature_columns": list(variant["feature_columns"]),
                    "frozen_params": actuals["search"][variant["base_model_id"]]["best_params"],
                    "cv_reference": f"cross_validation.{model_id}",
                    "cv": cv_summary,
                    "validation_metrics": actuals["validation"][model_id],
                    "selection_eligible": eligibility.get(model_id),
                }
                stage_rows.append(row)
                actuals["feature_policy"][model_id] = {
                    "base_model_id": row["base_model_id"],
                    "feature_policy": row["feature_policy"],
                    "feature_count": row["feature_count"],
                    "feature_columns": row["feature_columns"],
                    "cv": cv_summary,
                    "eligible": row["selection_eligible"],
                }
            result.stages["feature_policy_stage"] = {
                "policies": policies_spec["policies"],
                "applies_to": shortlist["model_ids"],
                "candidates": stage_rows,
            }
        actuals["selection"] = {
            "eligible_model_ids": selection["eligible_model_ids"],
            "practical_tie_group": selection["practical_tie_group"],
            "practical_tie": selection.get("practical_tie", False),
            "selected_model_id": selection["selected_model_id"],
            "deciding_criterion": selection.get("deciding_criterion"),
            "eligibility": {r["model_id"]: r["eligible"] for r in selection["records"]},
        }
        selected_id = selection["selected_model_id"]
        if selected_id is None:
            result.execution_notes.append("no candidate satisfied the eligibility rule")
            return True
        selected_variant = next(v for v in variants if v["model_id"] == selected_id)
        base_id = selected_variant["base_model_id"]
        selected_candidate = candidates[base_id]
        actuals["selection"]["selected_best_params"] = actuals["search"][base_id]["best_params"]
        actuals["selection"]["selected_pipeline_params"] = actuals["search"][base_id]["pipeline_best_params"]
        actuals["selection"]["selected_base_model_id"] = base_id
        actuals["selection"]["selected_family"] = selected_candidate["family"]
        actuals["selection"]["selected_feature_policy"] = selected_variant["feature_policy"]
        actuals["selection"]["selected_feature_columns"] = list(selected_variant["feature_columns"])
        selected_eval = validation_evals[selected_id]
        actuals["selected_validation"] = {"metrics": selected_eval.flat_metrics,
                                          **({"per_class": selected_eval.detail["per_class"],
                                              "confusion_matrix": selected_eval.detail["confusion_matrix"]}
                                             if selected_eval.detail else {})}

        # Decision stage (binary threshold policy, or explicit N/A for argmax).
        decision = task.decide(self, result, selected_id, selected_eval, y_val)
        if decision is None:
            return True

        # Final fit on train + validation (declared order) and a single test evaluation.
        columns = selected_variant["feature_columns"]
        fit_partitions = list(payload["final_evaluation"].get("fit_partitions", ["train", "validation"]))
        final_x = pd.concat([partitions[p].loc[:, columns] for p in fit_partitions], axis=0, ignore_index=True)
        final_y = pd.concat([task.labels(partitions[p], target_column) for p in fit_partitions], axis=0, ignore_index=True)
        result.stages["final_fit"] = {"partitions": fit_partitions, "rows": len(final_x),
                                      **_target_evidence(task, final_y), "feature_policy": selected_variant["feature_policy"],
                                      "feature_count": len(columns)}
        actuals["final_fit"] = {"rows": len(final_x), **_target_evidence(task, final_y), "partitions": fit_partitions}
        row_gate = payload["final_evaluation"].get("fit_row_count_gate")
        if row_gate and not self._gate(result, "final_evaluation.fit_row_count", row_gate["expected_rows"], len(final_x),
                                       row_gate["source"]):
            return False
        final_pipeline = build_candidate_pipeline(selected_candidate, payload, task_type,
                                                  extra_params=actuals["search"][base_id]["best_params"],
                                                  feature_columns=columns if policies_spec else None)
        final_pipeline.fit(final_x, final_y)
        final_estimator = final_pipeline.named_steps["model"]
        actuals["selection"]["selected_estimator_class"] = type(final_estimator).__name__
        actuals["final_fit"]["estimator_effective_parameters"] = {
            name: _jsonable(value) for name, value in final_estimator.get_params(deep=False).items() if value is not None}
        x_test, y_test = xy(partitions["test"], columns)
        task.final_evaluation(
            self, result, selected_id=selected_id, pipeline=final_pipeline, x_test=x_test, y_test=y_test,
            decision=decision, fit_rows=len(final_x), test_membership=memberships["test"],
            context={"feature_policy": selected_variant["feature_policy"], "fit_partitions": fit_partitions,
                     "final_features": final_x,
                     "selected_validation_confusion": selected_eval.detail.get("confusion_matrix")},
        )
        self._interpretive_diagnostics(result, task, partitions=partitions, columns=columns,
                                       selected_id=selected_id, selected_eval=selected_eval,
                                       final_x=final_x, fit_partitions=fit_partitions, memberships=memberships)
        return True

    def _interpretive_diagnostics(self, result: ReproductionResult, task: Any, *, partitions: Mapping[str, Any],
                                  columns: Sequence[str], selected_id: str, selected_eval: Evaluation, final_x: Any,
                                  fit_partitions: Sequence[str], memberships: Mapping[str, str]) -> None:
        """Descriptive group-overlap diagnostics over predictions already made.

        Runs after the final test evaluation and consumes only the selected
        candidate's validation prediction and the single test prediction, so it
        cannot influence the split, search, selection, or any fit.
        """
        spec = (self.contract.payload.get("interpretive_evidence") or {}).get("group_overlap_diagnostic")
        if not spec:
            return
        target_column = self.contract.payload["problem"]["target"]["column"]
        evaluations = []
        for evaluation in spec["evaluations"]:
            name = evaluation["evaluated_partition"]
            if evaluation["model"] == "selected_candidate_fitted_on_train":
                predictions = selected_eval.state["predictions"]
            else:
                predictions = result.stages["final_test_predictions"]
            if list(evaluation["reference_partitions"]) == list(fit_partitions):
                reference = final_x
            else:
                import pandas as pd

                reference = pd.concat([partitions[p].loc[:, list(columns)] for p in evaluation["reference_partitions"]],
                                      axis=0, ignore_index=True)
            evaluated = partitions[name].loc[:, list(columns)]
            outcome = group_overlap_diagnostic(reference, evaluated, task.labels(partitions[name], target_column),
                                               predictions, spec, evaluation, task.subset_metrics)
            evaluations.append(outcome)
            label = f"{spec['group_label']}_overlap"
            result.actuals.setdefault(label, {})[name] = {
                "evaluated_row_count": outcome["evaluated_row_count"],
                "seen": outcome["seen"], "unseen": outcome["unseen"]}
            for subset in ("seen", "unseen"):
                if outcome[subset]["status"] == "computed":
                    result.metric_sets.append(self._metric_set(
                        result, metric_set_id=f"diagnostic.{label}.{name}.{subset}", scope=SCOPE_INTERPRETIVE_DIAGNOSTIC,
                        partition=name, membership=memberships[name], model_id=selected_id,
                        threshold=task.validation_threshold(), metrics=outcome[subset]["metrics"],
                        fit_partitions=list(evaluation["reference_partitions"]),
                    ))
        result.stages["interpretive_diagnostics"] = {
            "diagnostic_only": True,
            "used_for_selection": False,
            "kind": spec["kind"],
            "executed_after": "final_test_evaluation",
            "evaluations": evaluations,
            "interpretation": list(spec["interpretation"]),
        }


def build_reproduction(
    contract: ScientificStudyContract,
    *,
    repo_root: Path,
    dataset_path: Path | None = None,
    study_checkout: Path | None = None,
    runtime: Mapping[str, Any] | None = None,
) -> Reproduction:
    payload = contract.payload
    env = payload["scientific_environment"]
    captured = dict(runtime) if runtime is not None else scientific_environment.capture_runtime_environment(sorted(env["core_packages"]))
    if study_checkout is not None:
        source_verification = verify_against_study_checkout(payload, study_checkout)
    else:
        source_verification = {
            "status": "not_performed",
            "reason": "no study checkout was supplied; the contract's pinned hashes were not re-checked in this run",
        }
    return Reproduction(
        contract=contract,
        repo_root=Path(repo_root),
        dataset_path=Path(dataset_path) if dataset_path else Path(repo_root) / payload["dataset_identity"]["atlas_local_path"],
        runtime=captured,
        environment=scientific_environment.classify_environment(env, captured),
        protocol_gaps=assess_protocol_support(payload),
        source_verification=source_verification,
    )


# --------------------------------------------------------------------------
# persistence and answers
# --------------------------------------------------------------------------


def validate_report_schema(report: Mapping[str, Any]) -> list[str]:
    """Validate a report against the schema of its own declared version."""
    import jsonschema

    version = report.get("schema_version") if isinstance(report, Mapping) else None
    path = REPORT_SCHEMA_PATHS.get(version)
    if path is None:
        return [f"schema_version: unsupported reproduction report version {version!r}"]
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(report)
    )


def _dump(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_reproduction_report(report: Mapping[str, Any], *, repo_root: Path, search_results: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Persist a reproduction run as write-once evidence.

    The run directory must not exist; nothing outside it is written, and an
    existing run is never overwritten.
    """
    errors = validate_report_schema(report)
    if errors:
        raise ScientificReproductionError("invalid_report_schema", "; ".join(errors))
    slug = report["run_identity"]["dataset_slug"]
    run_id = report["run_identity"]["run_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ScientificReproductionError("invalid_run_id", run_id)
    relative_dir = f"{RUNS_ROOT_RELATIVE}/{slug}/{run_id}"
    run_dir = Path(repo_root) / relative_dir
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ScientificReproductionError(
            "run_directory_exists", f"{relative_dir} already exists; reproduction evidence is write-once"
        ) from exc
    final_report = copy.deepcopy(dict(report))
    if search_results is not None:
        search_bytes = _dump({"run_id": run_id, "search_results": _jsonable(search_results)})
        (run_dir / SEARCH_RESULTS_FILENAME).write_bytes(search_bytes)
        final_report["search_results_reference"] = {
            "path": f"{relative_dir}/{SEARCH_RESULTS_FILENAME}",
            "sha256": _sha256_bytes(search_bytes),
        }
    report_bytes = _dump(final_report)
    (run_dir / REPORT_FILENAME).write_bytes(report_bytes)
    return {"run_directory": relative_dir, "report_path": f"{relative_dir}/{REPORT_FILENAME}", "report_sha256": _sha256_bytes(report_bytes)}


def _comparison_lookup(report: Mapping[str, Any], quantity: str) -> Mapping[str, Any] | None:
    comparison = report.get("comparison") or {}
    for group in ("values", "decisions", "runtime_identity"):
        for item in comparison.get(group, []) or []:
            if item["quantity"] == quantity:
                return item
    return None


def answer_reproduction_questions(report: Mapping[str, Any]) -> dict[str, Any]:
    """Answer the reproduction success-criterion questions from a report.

    Any question the report cannot answer is listed under ``unanswered``
    rather than guessed.
    """
    comparison = report.get("comparison") or {"values": [], "decisions": []}
    compared = comparison["values"] + comparison["decisions"]
    unanswered = [
        {"gap_id": g["gap_id"], "description": g["description"]} for g in report.get("evidence_gaps", [])
    ]
    study = report["evidence_lineage"][STUDY_RUN_KIND]
    thresholds = report.get("thresholds") or {}
    if "applicable" in thresholds and thresholds["applicable"] is False:
        threshold_answer = {"applicable": False, "reason": thresholds["reason"]}
        threshold_rule = None
    else:
        reproduced = thresholds.get("scientific_reproduced", {})
        threshold_rule = reproduced.get("rule_kind") if reproduced.get("value") is not None else None
        threshold_answer = {"applicable": True, "value": reproduced.get("value")}
    answers = {
        "which_scientific_revision_was_reproduced": study["study_revision"],
        "which_canonical_run_artifact_was_used": study.get("canonical_run"),
        "which_dataset_revision_was_used": {
            "sha256": report["dataset"].get("observed_sha256"),
            "matches_pinned_identity": report["dataset"]["verified"],
        },
        "which_scientific_environment_produced_the_reference": report["environment"]["scientific_reference"],
        "did_the_environment_match": report["environment"]["compatibility"]["classification"],
        "which_models_were_expected": report["candidate_models"]["expected"],
        "which_models_were_executed": report["candidate_models"]["executed"],
        "which_search_spaces_were_reproduced": {
            model_id: {"search_kind": s["search_kind"], "candidate_count_executed": s["candidate_count_executed"]}
            for model_id, s in report["candidate_models"]["search_spaces"].items()
        },
        "which_selection_rule_was_executed": report["selection"]["rule"]["kind"] if report["selection"]["executed"] else None,
        "which_threshold_rule_was_executed": threshold_rule,
        "threshold": threshold_answer,
        "scientific_expected_metrics": {c["quantity"]: c["expected"] for c in compared},
        "atlas_reproduced_metrics": {c["quantity"]: c["actual"] for c in compared},
        "deltas": {c["quantity"]: c["delta"] for c in compared if c.get("delta") is not None},
        "matched": [c["quantity"] for c in compared if c["outcome"] == OUTCOME_EXACT],
        "within_tolerance_only": [c["quantity"] for c in compared if c["outcome"] == OUTCOME_WITHIN],
        "exceeded_tolerance_or_mismatched": [c["quantity"] for c in compared if c["outcome"] in (OUTCOME_OUTSIDE, OUTCOME_MISMATCH)],
        "not_produced": [c["quantity"] for c in compared if c["outcome"] == OUTCOME_MISSING],
        "all_within_tolerance": comparison.get("all_within_tolerance"),
        "unsupported": report["protocol_support"]["gaps"],
        "final_reproduction_status": report["reproduction_status"]["status"],
        "unanswered": unanswered,
    }
    if report.get("schema_version") in (REPORT_SCHEMA_VERSION, REPORT_SCHEMA_VERSION_V3):
        answers.update(_answer_v2_questions(report))
    if report.get("schema_version") == REPORT_SCHEMA_VERSION_V3:
        answers.update(_answer_v3_questions(report))
    return answers


def _answer_v2_questions(report: Mapping[str, Any]) -> dict[str, Any]:
    split = report.get("split") or {}
    observed = split.get("observed") or {}
    gate = split.get("gate") or {}
    selection = (report.get("selection") or {}).get("executed") or {}
    final_fit = report.get("final_fit") or {}
    problem = report.get("problem") or {}
    class_order = problem.get("class_order") or {}

    def expected_match(quantity: str) -> bool | None:
        item = _comparison_lookup(report, quantity)
        return None if item is None else item["outcome"] == OUTCOME_EXACT

    confusion = _comparison_lookup(report, "final_test.confusion_matrix")
    per_class = [c for c in (report.get("comparison") or {}).get("values", []) if c["quantity"].startswith("final_test.per_class.")]
    return {
        "did_partition_memberships_match": gate.get("passed") if gate else None,
        "partition_row_counts": {name: part.get("rows") for name, part in observed.items()} or None,
        "which_split_seeds_were_used": split.get("seeds_used"),
        "cross_validation": (report.get("selection") or {}).get("rule", {}).get("partition"),
        "which_families_were_searched": [row["model_id"] for row in report.get("family_search", [])],
        "which_search_strategy_per_family": {row["model_id"]: row["search_strategy"] for row in report.get("family_search", [])},
        "how_many_candidates_per_family": {row["model_id"]: row["candidate_count_executed"] for row in report.get("family_search", [])},
        "which_best_params_emerged": {row["model_id"]: row["best_params"] for row in report.get("family_search", [])},
        "which_families_entered_the_shortlist": (report.get("family_shortlist") or {}).get("model_ids"),
        "which_feature_policy_candidates_were_evaluated": [
            row["model_id"] for row in ((report.get("feature_policy_stage") or {}).get("candidates") or [])],
        "was_there_a_practical_tie": selection.get("practical_tie"),
        "which_tie_break_rules_executed": [c["criterion"] for c in selection.get("criteria_applied", [])],
        "which_model_was_selected": selection.get("selected_model_id"),
        "final_fit_partitions_and_rows": {"partitions": final_fit.get("partitions"), "rows": final_fit.get("rows")},
        "decision_rule": problem.get("decision_rule"),
        "class_order_preserved": (class_order.get("fitted_estimator_class_order") == class_order.get("estimator_class_order")
                                  if class_order else None),
        "did_confusion_matrix_match": None if confusion is None else confusion["outcome"] == OUTCOME_EXACT,
        "did_per_class_metrics_match": (all(c["outcome"] in (OUTCOME_EXACT, OUTCOME_WITHIN) for c in per_class)
                                        if per_class else None),
        "did_dataset_sha_match": expected_match("dataset.sha256"),
        "evidence_tiers": report["reproduction_status"].get("evidence_tiers"),
        "historical_test_exposure": (report.get("protocol_integrity") or {}).get("historical_test_exposure"),
    }


def _answer_v3_questions(report: Mapping[str, Any]) -> dict[str, Any]:
    problem = report.get("problem") or {}
    diagnostics = report.get("interpretive_diagnostics") or {}
    return {
        "problem_type": problem.get("problem_type"),
        "classification_concepts": problem.get("classification_concepts"),
        "which_diagnostics_were_reproduced": [
            {"group_label": e["group_label"], "evaluated_partition": e["evaluated_partition"],
             "reference_partitions": e["reference_partitions"], "seen_rows": e["seen_group_row_count"],
             "unseen_rows": e["unseen_group_row_count"]}
            for e in diagnostics.get("evaluations", [])
        ],
        "were_diagnostics_used_for_selection": diagnostics.get("used_for_selection") if diagnostics else None,
    }


# Native Atlas metric names mapped to the scientific vocabulary, derived from
# the canonical metric identity registry (binary "pr_auc" is computed with
# average_precision_score; multiclass native names use sklearn's suffix style).
NATIVE_METRIC_ALIASES = metric_identity.native_to_scientific_metric_aliases()


def describe_lineage_separation(report: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Read-only side-by-side view of a reproduction and the Atlas-native lineage.

    Reads the dataset's governed native execution contract and the registry's
    active release metrics; writes nothing. Every value keeps its own
    provenance, and the view states which protocol facts differ so values are
    never presented as interchangeable.
    """
    root = Path(repo_root)
    slug = report["run_identity"]["dataset_slug"]
    registry = json.loads((root / "registry/datasets.json").read_text(encoding="utf-8"))
    entry = next((d for d in registry["datasets"] if d["dataset_slug"] == slug), None)
    native_contract_path = root / "contracts" / slug / "execution-contract.json"
    native_contract = json.loads(native_contract_path.read_text(encoding="utf-8")) if native_contract_path.is_file() else None
    release_metrics = None
    if entry is not None:
        metrics_path = root / "releases" / entry["active_release"] / "metrics" / "metrics.json"
        if metrics_path.is_file():
            release_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    selected = (report.get("selection", {}).get("executed") or {}).get("selected_model_id")
    # Final-test metric sets of the reproduction; threshold-free sets first so a
    # threshold-dependent metric is taken from the default-threshold set.
    final_sets = [m for m in report["metric_sets"]
                  if m["metric_set_id"] == f"final_test.{selected}"
                  or m["metric_set_id"] in (f"final_test.{selected}.probability", f"final_test.{selected}.at_default_threshold")]
    rows = []
    if release_metrics is not None:
        for metric in release_metrics.get("final_test_evaluation", {}).get("metrics", []):
            canonical = NATIVE_METRIC_ALIASES.get(metric["name"], metric["name"])
            reproduced_set = next((s for s in final_sets if canonical in s["metrics"]), None)
            rows.append({
                "canonical_metric": canonical,
                "partition": "test",
                "atlas_native_release": {
                    "value": metric["value"],
                    "native_metric_name": metric["name"],
                    "provenance": {
                        "lineage": RELEASE_KIND,
                        "release_id": entry["active_release"],
                        "training_run_id": release_metrics.get("training_run_identity", {}).get("run_id"),
                        "test_row_count": release_metrics.get("final_test_evaluation", {}).get("row_count"),
                        "decision_threshold": ((native_contract or {}).get("result_semantics") or {})
                        .get("decision", {}).get("threshold"),
                        "decision_threshold_provenance": "native execution contract result_semantics",
                    },
                },
                "scientific_reproduction": {
                    "value": reproduced_set["metrics"][canonical] if reproduced_set else None,
                    "provenance": {
                        "lineage": RUN_KIND,
                        "run_id": report["run_identity"]["run_id"],
                        "model_id": selected,
                        "metric_set_id": reproduced_set["metric_set_id"] if reproduced_set else None,
                        "threshold": reproduced_set["provenance"]["threshold"] if reproduced_set else None,
                        "test_row_count": ((report.get("split") or {}).get("observed") or {}).get("test", {}).get("rows"),
                    },
                },
                "directly_comparable": False,
            })

    differences = []
    if native_contract is not None:
        membership = (report.get("split") or {}).get("membership") or {"kind": "identifier"}
        seeds = (report.get("split") or {}).get("seeds_used")
        split_kind = (report.get("split") or {}).get("kind", "two_stage_stratified_holdout")
        scientific_split = (f"{split_kind} ({membership.get('kind')} membership, seeds "
                            f"{seeds if seeds else 'from the study contract'})")
        differences.append({
            "fact": "split",
            "atlas_native": f"{native_contract.get('split_policy', {}).get('strategy')} with random_seed="
                            f"{native_contract.get('random_seed')}",
            "scientific_reproduction": scientific_split,
        })
        observed = ((report.get("split") or {}).get("observed") or {})
        if observed and release_metrics is not None:
            differences.append({
                "fact": "test_partition_rows",
                "atlas_native": release_metrics.get("final_test_evaluation", {}).get("row_count"),
                "scientific_reproduction": observed.get("test", {}).get("rows"),
            })
        differences.append({
            "fact": "partition_membership",
            "atlas_native": "assigned by the native splitter of pipeline.training; not recorded by this reproduction",
            "scientific_reproduction": {name: part.get("membership_sha256") for name, part in observed.items()} or None,
            "consequence": "different row memberships: the two test metrics are measured on different rows",
        })
        differences.append({
            "fact": "primary_metric",
            "atlas_native": native_contract.get("primary_metric"),
            "scientific_reproduction": report["selection"]["rule"].get("eligibility", {}).get("metric"),
        })
        thresholds = report.get("thresholds") or {}
        differences.append({
            "fact": "decision_threshold",
            "atlas_native": (native_contract.get("result_semantics") or {}).get("decision", {}).get("threshold"),
            "scientific_reproduction": (not_applicable(thresholds["reason"]) if thresholds.get("applicable") is False
                                        else thresholds.get("scientific_reproduced", {}).get("value")),
        })
        differences.append({
            "fact": "model_selection",
            "atlas_native": (native_contract.get("modeling_constraints") or {}).get("selection_mode"),
            "scientific_reproduction": report["selection"]["rule"]["kind"],
        })
    return {
        "dataset_slug": slug,
        "active_release": entry["active_release"] if entry else None,
        "native_execution_contract_sha256": _sha256_file(native_contract_path) if native_contract else None,
        "rows": rows,
        "protocol_differences": differences,
        "interpretation": (
            "The two lineages use different partitions, seeds, selection procedures, and decision rules. "
            "Their metrics describe different experiments and are shown side by side only with their own "
            "provenance; neither replaces the other."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Atlas scientific reproduction for one study contract.")
    parser.add_argument("--contract", required=True, help="Repository-relative study contract path.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--dataset", default=None, help="Dataset path override (defaults to the contract's atlas_local_path).")
    parser.add_argument("--study-checkout", default=None, help="Optional read-only study checkout to verify pins against.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--n-jobs", type=int, default=None)
    parser.add_argument("--allow-incompatible-environment", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    contract = load_scientific_study_contract(root / args.contract, repo_root=root)
    reproduction = build_reproduction(
        contract, repo_root=root,
        dataset_path=Path(args.dataset) if args.dataset else None,
        study_checkout=Path(args.study_checkout) if args.study_checkout else None,
    )
    result = reproduction.run(run_id=args.run_id, n_jobs=args.n_jobs, allow_incompatible_environment=args.allow_incompatible_environment)
    written = write_reproduction_report(result.build_report(), repo_root=root, search_results=result.search_results or None)
    report = json.loads((root / written["report_path"]).read_text(encoding="utf-8"))
    print(json.dumps({"report": written, "status": report["reproduction_status"]["status"],
                      "reasons": report["reproduction_status"]["reasons"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
