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

Every metric set the engine emits carries provenance (producer lineage, run,
study revision, dataset hash, partition and its membership hash, model, the
threshold and the rule that produced it, and the protocol). Reference values
are only ever used on the *expected* side of a comparison; they are never
copied into the reproduced results.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pipeline import model_families, scientific_environment
from pipeline.scientific_study_contract import (
    ScientificStudyContract,
    assess_protocol_support,
    load_scientific_study_contract,
    verify_against_study_checkout,
)


REPORT_SCHEMA_VERSION = "scientific-reproduction-report.v1"
REPORT_SCHEMA_PATH = Path(__file__).resolve().parent / "scientific-reproduction-report.schema.json"
REPORT_FILENAME = "reproduction-report.json"
SEARCH_RESULTS_FILENAME = "search-results.json"
RUNS_ROOT_RELATIVE = "pipeline/scientific-reproduction-runs"
ENGINE_ID = "pipeline/scientific_reproduction.py"
ENGINE_VERSION = "1"

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


_PREPARATION_RULES = {"conditional_blank_numeric_fill": _apply_conditional_blank_numeric_fill}


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


def split_two_stage_stratified(frame: Any, split: Mapping[str, Any], identifier_columns: Sequence[str]) -> dict[str, Any]:
    """Identifier-ordered two-stage stratified holdout.

    Rows are ordered by their identifier key before splitting so membership
    does not depend on input row order; partitions are returned in source row
    order.
    """
    from sklearn.model_selection import train_test_split

    fractions = split["fractions"]
    stratify_by = split["stratify_by"]
    working = frame.copy(deep=True)
    working["__source_position__"] = range(len(working))
    if split.get("order_by_identifier", True):
        working["__membership_key__"] = _membership_keys(working, identifier_columns)
        if working["__membership_key__"].duplicated().any():
            raise ScientificReproductionError("duplicate_identifier", "identifier keys must be unique")
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
        stratify=canonical[stratify_by],
    )
    temporary = canonical.iloc[temporary_pos]
    validation_pos, test_pos = train_test_split(
        temporary_pos,
        test_size=fractions["test"] / temporary_fraction,
        random_state=split["seeds"]["validation_vs_test"],
        shuffle=split.get("shuffle", True),
        stratify=temporary[stratify_by],
    )

    def project(selected: Sequence[int]) -> Any:
        source_positions = sorted(int(v) for v in canonical.iloc[list(selected)]["__source_position__"])
        return frame.iloc[source_positions].copy(deep=True)

    return {"train": project(train_pos), "validation": project(validation_pos), "test": project(test_pos)}


_SPLITTERS = {"two_stage_stratified_holdout": split_two_stage_stratified}


def csv_roundtrip(frame: Any) -> Any:
    """Serialize and re-read a partition the way a file-based study handoff does."""
    import pandas as pd

    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n")
    buffer.seek(0)
    return pd.read_csv(buffer)


# --------------------------------------------------------------------------
# step 3: candidate pipelines, search, evaluation
# --------------------------------------------------------------------------


def build_candidate_pipeline(candidate: Mapping[str, Any], contract: Mapping[str, Any], task_type: str, extra_params: Mapping[str, Any] | None = None) -> Any:
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    preprocessing = contract["preprocessing"]
    categorical_spec = preprocessing.get("categorical", {})
    numerical = list(contract["features"]["numerical"])
    categorical = list(contract["features"]["categorical"])
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


def _cross_validator(spec: Mapping[str, Any]) -> Any:
    from sklearn.model_selection import StratifiedKFold

    if spec["kind"] != "stratified_k_fold":
        raise ScientificReproductionError("unsupported_cross_validation", spec["kind"])
    return StratifiedKFold(n_splits=int(spec["n_splits"]), shuffle=bool(spec["shuffle"]), random_state=spec["random_state"])


def run_candidate_search(candidate: Mapping[str, Any], contract: Mapping[str, Any], x_train: Any, y_train: Any, *, n_jobs: int, task_type: str) -> dict[str, Any]:
    from sklearn.model_selection import GridSearchCV, ParameterGrid, RandomizedSearchCV

    search = candidate["search"]
    space = {f"model__{name}": list(values) for name, values in search.get("space", {}).items()}
    pipeline = build_candidate_pipeline(candidate, contract, task_type)
    cv_spec = contract["cross_validation"]
    common = dict(
        estimator=pipeline,
        scoring=_scoring(int(contract["problem"]["target"]["encoding"][str(contract["problem"]["target"]["positive_class"])])),
        refit=contract["metrics"].get("refit", contract["metrics"]["primary"]),
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
    mean_ap = float(results["mean_test_average_precision"][best])
    std_ap = float(results["std_test_average_precision"][best])
    half = z_value * std_ap / math.sqrt(n_splits)
    summary = {
        "candidate_count_executed": executed,
        "candidate_count_expected": expected,
        "best_index": best,
        "best_params": {name.removeprefix("model__"): _jsonable(value) for name, value in searcher.best_params_.items()},
        "average_precision_mean": mean_ap,
        "average_precision_std": std_ap,
        "average_precision_ci_lower": mean_ap - half,
        "average_precision_ci_upper": mean_ap + half,
        "roc_auc_mean": float(results["mean_test_roc_auc"][best]),
        "log_loss_mean": float(-results["mean_test_neg_log_loss"][best]),
        "brier_score_mean": float(-results["mean_test_neg_brier_score"][best]),
        "search_duration_seconds": round(duration, 3),
    }
    table = [
        {
            "candidate_index": index,
            "params": {k.removeprefix("model__"): _jsonable(v) for k, v in params.items()},
            "rank_average_precision": int(results["rank_test_average_precision"][index]),
            "mean_average_precision": float(results["mean_test_average_precision"][index]),
            "std_average_precision": float(results["std_test_average_precision"][index]),
            "mean_roc_auc": float(results["mean_test_roc_auc"][index]),
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
# step 4: selection and threshold rules
# --------------------------------------------------------------------------


def select_leader_anchored_practical_tie(records: Sequence[Mapping[str, Any]], baseline_value: float, rule: Mapping[str, Any]) -> dict[str, Any]:
    """Eligibility over a baseline, leader by a validation metric, a
    leader-anchored practical-tie group, then ordered tie-breakers applied to
    the whole group until one candidate remains."""
    eligibility = rule["eligibility"]
    metric_field = f"validation_{eligibility['metric']}"
    rows = []
    for record in records:
        margin = float(record[metric_field]) - baseline_value
        eligible = margin > eligibility["margin"] if eligibility.get("strict", True) else margin >= eligibility["margin"]
        rows.append({**record, "margin_over_baseline": margin, "eligible": bool(eligible)})
    eligible_rows = sorted(
        (r for r in rows if r["eligible"]),
        key=lambda r: (-float(r[f"validation_{rule['leader']['metric']}"]), r["model_id"]),
    )
    if not eligible_rows:
        return {"eligible_model_ids": [], "practical_tie_group": [], "selected_model_id": None,
                "criteria_applied": [], "records": rows, "outcome": "no_eligible_candidate"}
    leader = eligible_rows[0]
    tie = rule["practical_tie"]
    leader_field = f"validation_{tie['metric']}"

    def tied(other: Mapping[str, Any]) -> bool:
        difference = abs(float(leader[leader_field]) - float(other[leader_field]))
        overlap = max(leader["cv_average_precision_ci_lower"], other["cv_average_precision_ci_lower"]) <= min(
            leader["cv_average_precision_ci_upper"], other["cv_average_precision_ci_upper"]
        )
        return difference <= tie["tolerance"] and (overlap or not tie.get("requires_cv_interval_overlap", True))

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
    return {
        "eligible_model_ids": [r["model_id"] for r in eligible_rows],
        "practical_tie_group": [r["model_id"] for r in group],
        "practical_tie": len(group) > 1,
        "selected_model_id": remaining[0]["model_id"],
        "deciding_criterion": criteria[-1]["criterion"] if criteria else "highest_validation_metric",
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
    return {
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


def compute_reproduction_status(
    *,
    protocol_gaps: Sequence[Mapping[str, Any]],
    environment_classification: str,
    dataset_verified: bool,
    executed: bool,
    comparison: Mapping[str, Any] | None,
    evidence_gaps: Sequence[Mapping[str, Any]],
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
    if environment_classification == scientific_environment.EXACT and comparison["all_exact_at_reported_precision"]:
        return {"status": STATUS_REPRODUCED_EXACT, "reasons": []}
    if environment_classification != scientific_environment.EXACT:
        reasons.append(f"environment classified as {environment_classification}")
    if not comparison["all_exact_at_reported_precision"]:
        reasons.append("some quantities differ beyond reported precision but within the declared tolerance")
    return {"status": STATUS_REPRODUCED_WITHIN_TOLERANCE, "reasons": reasons}


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def _task_type(problem_type: str) -> str:
    return model_families.CLASSIFICATION if problem_type.endswith("classification") else model_families.REGRESSION


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
        )
        reference_threshold = next(
            (i for i in payload["expected_evidence"]["values"] if i["quantity"] == "threshold.value"), None
        )
        candidates_expected = [c["model_id"] for c in payload["candidates"]]
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
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
            },
            "protocol_support": {
                "status": "fully_supported" if not self.plan.protocol_gaps else "unsupported_elements_present",
                "gaps": self.plan.protocol_gaps,
            },
            "source_verification": self.plan.source_verification,
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
            "selection": {
                "rule": payload["selection"],
                "executed": self.actuals.get("selection_trace"),
            },
            "thresholds": {
                "scientific_policy": {
                    "provenance": "scientific_study_contract",
                    "rule": payload["threshold_policy"],
                },
                "scientific_reference": {
                    "provenance": STUDY_RUN_KIND,
                    "value": reference_threshold["expected"] if reference_threshold else None,
                    "source": reference_threshold["source"] if reference_threshold else None,
                },
                "scientific_reproduced": {
                    "provenance": RUN_KIND,
                    "run_id": self.run_id,
                    "value": self.actuals.get("threshold", {}).get("value"),
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
            },
            "metric_sets": self.metric_sets,
            "comparison": comparison,
            "evidence_gaps": payload["evidence_gaps"],
            "study_observations": payload.get("study_observations", []),
            "execution_notes": self.execution_notes,
            "limitations": payload["limitations"],
            "reproduction_status": status,
            "immutability": {
                "write_once": True,
                "historical_artifacts_modified": False,
                "supersedes": None,
            },
        }
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
        self._execute(result, n_jobs=n_jobs)
        result.executed = True
        return result

    def _metric_set(self, result: ReproductionResult, *, metric_set_id: str, partition: str, membership: str | None, model_id: str, threshold: Mapping[str, Any] | None, metrics: Mapping[str, Any]) -> dict[str, Any]:
        payload = self.contract.payload
        return {
            "metric_set_id": metric_set_id,
            "provenance": {
                "producer_lineage": RUN_KIND,
                "run_id": result.run_id,
                "study_revision": self.contract.study_revision,
                "study_contract_sha256": self.contract.sha256,
                "dataset_sha256": payload["dataset_identity"]["sha256"],
                "partition": partition,
                "partition_membership_sha256": membership,
                "model_id": model_id,
                "threshold": dict(threshold) if threshold else None,
                "protocol_kind": payload["study_identity"]["protocol_kind"],
            },
            "metrics": _jsonable(dict(metrics)),
        }

    def _execute(self, result: ReproductionResult, *, n_jobs: int | None) -> None:
        import pandas as pd

        payload = self.contract.payload
        task_type = _task_type(payload["problem"]["problem_type"])
        target = payload["problem"]["target"]
        encoding = {str(k): int(v) for k, v in target["encoding"].items()}
        positive_label = encoding[str(target["positive_class"])]
        identifiers = payload["problem"]["identifier_columns"]
        features = payload["features"]["feature_columns"]
        jobs = n_jobs if n_jobs is not None else int(payload.get("search_execution", {}).get("n_jobs", 1))
        if n_jobs is not None and n_jobs != payload.get("search_execution", {}).get("n_jobs"):
            result.execution_notes.append(
                f"search n_jobs={n_jobs} (study used {payload.get('search_execution', {}).get('n_jobs')}); "
                "parallelism does not change search results"
            )
        actuals = result.actuals

        raw = load_dataset(self.dataset_path, payload["dataset_identity"])
        prepared, preparation_evidence = apply_preparation(raw, payload["preparation"])
        actuals["preparation"] = preparation_evidence

        splitter = _SPLITTERS[payload["split"]["kind"]]
        partitions = splitter(prepared, payload["split"], identifiers)
        if payload["split"].get("partition_handoff") == "csv_roundtrip":
            partitions = {name: csv_roundtrip(frame) for name, frame in partitions.items()}
        memberships = {name: membership_sha256(frame, identifiers) for name, frame in partitions.items()}
        actuals["partitions"] = {
            name: {
                "rows": len(frame),
                "class_counts": {_key(k): int(v) for k, v in frame[target["column"]].value_counts().items()},
                "membership_sha256": memberships[name],
            }
            for name, frame in partitions.items()
        }

        def xy(frame: Any) -> tuple[Any, Any]:
            return frame.loc[:, features].copy(deep=True), frame[target["column"]].map(encoding).astype("int64")

        x_train, y_train = xy(partitions["train"])
        x_val, y_val = xy(partitions["validation"])
        x_test, y_test = xy(partitions["test"])
        default_threshold = float(payload["metrics"].get("default_threshold", 0.5))

        # Baseline (reference only, never selectable).
        baseline = payload.get("baseline")
        baseline_value = None
        if baseline:
            base_pipeline = build_candidate_pipeline(baseline, payload, task_type).fit(x_train, y_train)
            base_prob = _positive_probabilities(base_pipeline, x_val, positive_label)
            base_metrics = {**probability_metrics(y_val, base_prob), **threshold_metrics(y_val, base_prob, default_threshold)}
            actuals["baseline"] = {"validation": base_metrics}
            baseline_value = base_metrics[payload["selection"]["eligibility"]["metric"]]
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"validation.{baseline['model_id']}", partition="validation",
                membership=memberships["validation"], model_id=baseline["model_id"],
                threshold={"value": default_threshold, "rule": "fixed_default_threshold", "provenance": "scientific_study_contract"},
                metrics=base_metrics,
            ))

        # Candidate searches on train only, one validation evaluation each.
        actuals["search"], actuals["cv"], actuals["validation"] = {}, {}, {}
        best_estimators: dict[str, Any] = {}
        validation_probabilities: dict[str, list[float]] = {}
        records = []
        simplicity = payload["selection"].get("simplicity_order", [])
        for candidate in payload["candidates"]:
            model_id = candidate["model_id"]
            outcome = run_candidate_search(candidate, payload, x_train, y_train, n_jobs=jobs, task_type=task_type)
            result.candidate_models_executed.append(model_id)
            summary = outcome["summary"]
            actuals["search"][model_id] = {
                "candidate_count_expected": summary["candidate_count_expected"],
                "candidate_count_executed": summary["candidate_count_executed"],
                "best_params": summary["best_params"],
                "search_duration_seconds": summary["search_duration_seconds"],
            }
            actuals["cv"][model_id] = {k: summary[k] for k in (
                "average_precision_mean", "average_precision_std", "average_precision_ci_lower",
                "average_precision_ci_upper", "roc_auc_mean", "log_loss_mean", "brier_score_mean")}
            result.search_results[model_id] = outcome["table"]
            best_estimators[model_id] = outcome["best_estimator"]
            probabilities = _positive_probabilities(outcome["best_estimator"], x_val, positive_label)
            validation_probabilities[model_id] = probabilities
            metrics = {**probability_metrics(y_val, probabilities), **threshold_metrics(y_val, probabilities, default_threshold)}
            actuals["validation"][model_id] = metrics
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"cross_validation.{model_id}", partition="train_cross_validation",
                membership=memberships["train"], model_id=model_id, threshold=None, metrics=actuals["cv"][model_id],
            ))
            result.metric_sets.append(self._metric_set(
                result, metric_set_id=f"validation.{model_id}", partition="validation",
                membership=memberships["validation"], model_id=model_id,
                threshold={"value": default_threshold, "rule": "fixed_default_threshold", "provenance": "scientific_study_contract"},
                metrics=metrics,
            ))
            records.append({
                "model_id": model_id,
                "family": candidate["family"],
                **{f"validation_{k}": v for k, v in metrics.items() if isinstance(v, float)},
                "cv_average_precision_std": summary["average_precision_std"],
                "cv_average_precision_ci_lower": summary["average_precision_ci_lower"],
                "cv_average_precision_ci_upper": summary["average_precision_ci_upper"],
                "simplicity_rank": simplicity.index(candidate["family"]) if candidate["family"] in simplicity else len(simplicity),
            })

        # Selection.
        selection_rule = _SELECTION_RULES[payload["selection"]["kind"]]
        selection = selection_rule(records, float(baseline_value) if baseline_value is not None else 0.0, payload["selection"])
        actuals["selection_trace"] = _jsonable(selection)
        actuals["selection"] = {
            "eligible_model_ids": selection["eligible_model_ids"],
            "practical_tie_group": selection["practical_tie_group"],
            "selected_model_id": selection["selected_model_id"],
            "deciding_criterion": selection.get("deciding_criterion"),
        }
        selected_id = selection["selected_model_id"]
        if selected_id is None:
            result.execution_notes.append("no candidate satisfied the eligibility rule")
            return
        actuals["selection"]["selected_best_params"] = actuals["search"][selected_id]["best_params"]

        # Threshold policy on validation only.
        policy = payload["threshold_policy"]
        threshold_outcome = _THRESHOLD_POLICIES[policy["kind"]](y_val, validation_probabilities[selected_id], policy)
        if not threshold_outcome["satisfied"]:
            result.execution_notes.append("threshold policy could not be satisfied on validation")
            return
        policy_threshold = threshold_outcome["threshold"]
        actuals["threshold"] = {
            "value": policy_threshold,
            "validation": threshold_metrics(y_val, validation_probabilities[selected_id], policy_threshold),
        }
        reproduced_threshold = {"value": policy_threshold, "rule": policy["kind"], "provenance": RUN_KIND,
                                 "selected_on_partition": policy["partition"]}

        # Final fit on train + validation and a single test evaluation.
        selected = next(c for c in payload["candidates"] if c["model_id"] == selected_id)
        final_pipeline = build_candidate_pipeline(selected, payload, task_type, extra_params=actuals["search"][selected_id]["best_params"])
        final_x = pd.concat([x_train, x_val], axis=0, ignore_index=True)
        final_y = pd.concat([y_train, y_val], axis=0, ignore_index=True)
        final_pipeline.fit(final_x, final_y)
        test_probabilities = _positive_probabilities(final_pipeline, x_test, positive_label)
        actuals["final_test"] = {
            "evaluation_count": 1,
            "fit_rows": len(final_x),
            "probability": probability_metrics(y_test, test_probabilities),
            "at_default_threshold": threshold_metrics(y_test, test_probabilities, default_threshold),
            "at_policy_threshold": threshold_metrics(y_test, test_probabilities, policy_threshold),
        }
        final_membership = memberships["test"]
        result.metric_sets.append(self._metric_set(
            result, metric_set_id=f"final_test.{selected_id}.probability", partition="test",
            membership=final_membership, model_id=selected_id, threshold=None,
            metrics=actuals["final_test"]["probability"],
        ))
        result.metric_sets.append(self._metric_set(
            result, metric_set_id=f"final_test.{selected_id}.at_default_threshold", partition="test",
            membership=final_membership, model_id=selected_id,
            threshold={"value": default_threshold, "rule": "fixed_default_threshold", "provenance": "scientific_study_contract"},
            metrics=actuals["final_test"]["at_default_threshold"],
        ))
        result.metric_sets.append(self._metric_set(
            result, metric_set_id=f"final_test.{selected_id}.at_policy_threshold", partition="test",
            membership=final_membership, model_id=selected_id, threshold=reproduced_threshold,
            metrics=actuals["final_test"]["at_policy_threshold"],
        ))


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
    import jsonschema

    schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
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
    return {
        "which_scientific_revision_was_reproduced": study["study_revision"],
        "which_dataset_revision_was_used": {
            "sha256": report["dataset"].get("observed_sha256"),
            "matches_pinned_identity": report["dataset"]["verified"],
        },
        "which_scientific_environment_produced_the_reference": report["environment"]["scientific_reference"],
        "which_models_were_expected": report["candidate_models"]["expected"],
        "which_models_were_executed": report["candidate_models"]["executed"],
        "which_search_spaces_were_reproduced": {
            model_id: {"search_kind": s["search_kind"], "candidate_count_executed": s["candidate_count_executed"]}
            for model_id, s in report["candidate_models"]["search_spaces"].items()
        },
        "which_selection_rule_was_executed": report["selection"]["rule"]["kind"] if report["selection"]["executed"] else None,
        "which_threshold_rule_was_executed": report["thresholds"]["scientific_reproduced"]["rule_kind"]
        if report["thresholds"]["scientific_reproduced"]["value"] is not None else None,
        "scientific_expected_metrics": {c["quantity"]: c["expected"] for c in compared},
        "atlas_reproduced_metrics": {c["quantity"]: c["actual"] for c in compared},
        "deltas": {c["quantity"]: c["delta"] for c in compared if c.get("delta") is not None},
        "all_within_tolerance": comparison.get("all_within_tolerance"),
        "unsupported": report["protocol_support"]["gaps"],
        "final_reproduction_status": report["reproduction_status"]["status"],
        "unanswered": unanswered,
    }


# Canonical metric identities: the native binary vocabulary names Average
# Precision "pr_auc" (it is computed with average_precision_score).
NATIVE_METRIC_ALIASES = {"pr_auc": "average_precision"}


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
    reproduced_final = next(
        (m for m in report["metric_sets"] if m["metric_set_id"] == f"final_test.{selected}.probability"), None
    )
    rows = []
    if release_metrics is not None:
        for metric in release_metrics.get("final_test_evaluation", {}).get("metrics", []):
            canonical = NATIVE_METRIC_ALIASES.get(metric["name"], metric["name"])
            rows.append({
                "canonical_metric": canonical,
                "partition": "test",
                "atlas_native_release": {
                    "value": metric["value"],
                    "native_metric_name": metric["name"],
                    "provenance": {"lineage": RELEASE_KIND, "release_id": entry["active_release"],
                                   "training_run_id": release_metrics.get("training_run_identity", {}).get("run_id")},
                },
                "scientific_reproduction": {
                    "value": (reproduced_final or {}).get("metrics", {}).get(canonical),
                    "provenance": {"lineage": RUN_KIND, "run_id": report["run_identity"]["run_id"], "model_id": selected},
                },
                "directly_comparable": False,
            })

    differences = []
    if native_contract is not None:
        scientific_split = "two_stage_stratified_holdout (identifier-ordered, seeds from the study contract)"
        differences.append({
            "fact": "split",
            "atlas_native": f"{native_contract.get('split_policy', {}).get('strategy')} with random_seed="
                            f"{native_contract.get('random_seed')}",
            "scientific_reproduction": scientific_split,
        })
        differences.append({
            "fact": "primary_metric",
            "atlas_native": native_contract.get("primary_metric"),
            "scientific_reproduction": report["selection"]["rule"].get("eligibility", {}).get("metric"),
        })
        differences.append({
            "fact": "decision_threshold",
            "atlas_native": (native_contract.get("result_semantics") or {}).get("decision", {}).get("threshold"),
            "scientific_reproduction": report["thresholds"]["scientific_reproduced"]["value"],
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
            "The two lineages use different partitions, seeds, selection procedures, and thresholds. "
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
    print(json.dumps({"report": written, "status": report["reproduction_status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
