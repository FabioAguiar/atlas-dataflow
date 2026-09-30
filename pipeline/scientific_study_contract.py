"""Scientific Study Contract loading, capability assessment, and source verification.

A scientific study contract pins one revision of an external Dataset Study:
its commit, the hashes of the files the protocol and reference evidence were
read from, the dataset identity, the scientific environment, the declarative
protocol, and the evidence the study published at that revision. Contracts
live under ``pipeline/scientific-studies/<dataset-slug>/<study-revision-label>/``
and are immutable: a changed study revision gets a new directory.

Three schema versions are accepted and never rewritten into each other:

* ``scientific-study-contract.v1`` -- binary classification only;
* ``scientific-study-contract.v2`` -- binary and multiclass classification,
  with problem-type conditional rules (a multiclass contract must declare
  ``positive_class`` and ``threshold_policy`` as explicitly not applicable and
  must declare estimator/public class orders and an argmax decision rule),
  technical row-occurrence membership, protocol gates, a family shortlist and
  a feature-policy selection stage;
* ``scientific-study-contract.v3`` -- the v2 contract plus
  ``continuous_regression``. A regression contract has no class concept at
  all: classes, positive class, class orders, decision rule and threshold
  policy are structurally absent and ``problem.classification_concepts``
  records that explicitly.
* ``scientific-study-contract.v4`` -- the v3 tabular contract (unchanged)
  plus ``univariate_forecasting``. A forecasting contract is temporal by
  construction: a translated period index, a development window, a sealed
  final holdout, an expanding-window backtest, a frozen specification catalog,
  failure/eligibility semantics, a pooled-metric selection rule and a
  finalization policy. It has no features, split fractions, cross-validation,
  class, positive class or threshold. The study's own problem vocabulary is
  preserved in ``problem.study_problem_identity`` and mapped to the Atlas
  capability through ``STUDY_PROBLEM_IDENTITIES``.

This module never executes a protocol. It answers four questions:

* is the contract structurally valid (JSON Schema of its declared version)?
* is it semantically coherent (``validate_contract_semantics``)?
* which protocol elements can Atlas execute (``assess_protocol_support``)?
* does a study checkout still match what the contract pins
  (``verify_against_study_checkout``)?
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline import model_families, preparation_rules


SCHEMA_VERSION_V1 = "scientific-study-contract.v1"
SCHEMA_VERSION_V2 = "scientific-study-contract.v2"
SCHEMA_VERSION_V3 = "scientific-study-contract.v3"
SCHEMA_VERSION_V4 = "scientific-study-contract.v4"
SCHEMA_VERSION = SCHEMA_VERSION_V4
CONTRACT_FILENAME = "scientific-study-contract.json"
_SCHEMA_DIR = Path(__file__).resolve().parent
SCHEMA_PATHS: Mapping[str, Path] = {
    SCHEMA_VERSION_V1: _SCHEMA_DIR / "scientific-study-contract.schema.json",
    SCHEMA_VERSION_V2: _SCHEMA_DIR / "scientific-study-contract.v2.schema.json",
    SCHEMA_VERSION_V3: _SCHEMA_DIR / "scientific-study-contract.v3.schema.json",
    SCHEMA_VERSION_V4: _SCHEMA_DIR / "scientific-study-contract.v4.schema.json",
}
SCHEMA_PATH = SCHEMA_PATHS[SCHEMA_VERSION_V1]
STUDIES_ROOT_RELATIVE = "pipeline/scientific-studies"

BINARY = "binary_classification"
MULTICLASS = "multiclass_classification"
REGRESSION = "continuous_regression"
FORECASTING = "univariate_forecasting"
CLASSIFICATION_PROBLEM_TYPES = frozenset({BINARY, MULTICLASS})
TABULAR_PROBLEM_TYPES = frozenset({BINARY, MULTICLASS, REGRESSION})

# The one explicit mapping from a Dataset Study's own problem vocabulary to the
# Atlas capability identity it dispatches through. A study keeps its terms in
# ``problem.study_problem_identity``; Atlas never rewrites them.
STUDY_PROBLEM_IDENTITIES: Mapping[tuple[str, str], str] = {
    ("time_series_forecasting", "univariate"): FORECASTING,
}


def atlas_problem_type_for(study_identity: Mapping[str, Any]) -> str | None:
    """The Atlas capability a study's ``(problem_type, forecasting_mode)`` maps to."""
    return STUDY_PROBLEM_IDENTITIES.get((study_identity.get("problem_type"), study_identity.get("forecasting_mode")))


def study_problem_identity(atlas_problem_type: str) -> dict[str, str]:
    """The study vocabulary that maps to an Atlas capability (inverse of the table)."""
    matches = [key for key, value in STUDY_PROBLEM_IDENTITIES.items() if value == atlas_problem_type]
    if len(matches) != 1:
        raise ScientificStudyContractError("ambiguous_study_problem_identity", atlas_problem_type)
    problem_type, mode = matches[0]
    return {"problem_type": problem_type, "forecasting_mode": mode}

# Metric vocabulary per problem type. Binary metrics need a positive class
# and (for threshold metrics) a threshold; multiclass and regression metrics
# need neither. Kept equal to the registry's scientific aliases by tests.
METRICS_BY_PROBLEM_TYPE: Mapping[str, frozenset[str]] = {
    BINARY: frozenset({
        "average_precision", "roc_auc", "precision", "recall", "f1", "f2",
        "balanced_accuracy", "accuracy", "log_loss", "brier_score",
    }),
    MULTICLASS: frozenset({
        "macro_f1", "balanced_accuracy", "macro_recall", "weighted_f1",
        "accuracy", "minimum_per_class_recall", "log_loss",
    }),
    REGRESSION: frozenset({"mae", "rmse", "r2", "medae"}),
    FORECASTING: frozenset({"mae", "rmse", "seasonal_mase"}),
}

# Protocol vocabulary the reproduction engine implements. A contract element
# outside this vocabulary is an Atlas capability gap, never silently skipped.
REPRODUCTION_CAPABILITIES: Mapping[str, Any] = {
    "problem_types": {BINARY, MULTICLASS, REGRESSION},
    "protocol_kinds": {"tabular_holdout_model_selection.v1", "tabular_holdout_model_selection.v2"},
    "preparation_rule_kinds": set(preparation_rules.PREPARATION_RULE_KINDS),
    "split_kinds": {"two_stage_stratified_holdout", "two_stage_random_holdout"},
    "membership_kinds": {"identifier", "technical_row_occurrence"},
    "preprocessing_kinds": {"column_transformer_onehot_plus_numeric"},
    "cross_validation_kinds": {"stratified_k_fold", "k_fold"},
    "search_kinds": {"grid", "randomized", "none"},
    "selection_kinds": {"leader_anchored_practical_tie"},
    "threshold_policy_kinds": {"max_precision_subject_to_min_recall", "not_applicable"},
    "decision_rule_kinds": {"probability_threshold", "argmax_class_probability"},
    "interpretive_evidence_kinds": {"non_destructive_group_overlap_diagnostic"},
    "family_shortlist_kinds": {"top_k_by_cv_metric"},
    "feature_policy_kinds": {"frozen_family_params_feature_projection"},
    "final_evaluation_kinds": {"refit_on_train_plus_validation_single_test_evaluation"},
    "metrics": METRICS_BY_PROBLEM_TYPE,
    "tie_breaker_fields": {"simplicity_rank", "model_id"},
}

# Temporal protocol vocabulary of the forecasting runner (pipeline.scientific_forecasting).
FORECASTING_CAPABILITIES: Mapping[str, Any] = {
    "problem_types": {FORECASTING},
    "protocol_kinds": {"univariate_forecasting_expanding_window_model_selection.v1"},
    "temporal_source_kinds": {"fractional_year_monthly"},
    "frequencies": {"M"},
    "partition_fingerprint_kinds": {"period_value_csv_sha256"},
    "backtesting_modes": {"expanding_window"},
    "refit_policies": {"fit_from_scratch_per_fold"},
    "selection_kinds": {"forecasting_pooled_metric_practical_tie"},
    "practical_tie_bounds": {"leader_plus_tolerance", "absolute_difference"},
    "tie_break_modes": {"lexicographic_tuple"},
    "tie_breaker_directions": {"min", "max", "lexical_min"},
    "ranking_kinds": {"selected_first_then_leader_field_then_candidate_id"},
    "finalization_kinds": {"refit_selected_on_development_single_holdout_forecast"},
    "diagnostic_kinds": {"fold_metric_population_std", "horizon_window_metric"},
    "candidate_roles": {"primary_baseline", "secondary_baseline", "candidate"},
    "failure_actions": {"abort_backtest", "mark_ineligible"},
    "fixed_record_fields": {"complexity_rank", "candidate_id"},
}


def problem_type_of(payload: Mapping[str, Any]) -> str:
    return payload["problem"]["problem_type"]


def is_forecasting_contract(payload: Mapping[str, Any]) -> bool:
    return payload.get("schema_version") == SCHEMA_VERSION_V4 and problem_type_of(payload) == FORECASTING


def metric_vocabulary(problem_type: str) -> frozenset[str]:
    return METRICS_BY_PROBLEM_TYPE.get(problem_type, frozenset())


def _is_supported_tie_breaker_field(field: Any, problem_type: str = BINARY) -> bool:
    """``validation_<metric>``, ``cv_<metric>_mean``/``_std``, or a fixed field."""
    if field in REPRODUCTION_CAPABILITIES["tie_breaker_fields"]:
        return True
    if not isinstance(field, str):
        return False
    metrics = metric_vocabulary(problem_type)
    if field.startswith("validation_"):
        return field.removeprefix("validation_") in metrics
    if field.startswith("cv_"):
        for suffix in ("_mean", "_std"):
            if field.endswith(suffix):
                return field.removeprefix("cv_").removesuffix(suffix) in metrics
    return False


class ScientificStudyContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScientificStudyContract:
    payload: Mapping[str, Any]
    relative_path: str
    sha256: str

    @property
    def dataset_slug(self) -> str:
        return self.payload["study_identity"]["dataset_slug"]

    @property
    def study_revision(self) -> str:
        return self.payload["source_repository"]["revision"]

    def reference(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "schema_version": self.payload["schema_version"],
            "study_id": self.payload["study_identity"]["study_id"],
            "study_revision": self.study_revision,
            "study_revision_label": self.payload["study_identity"]["study_revision_label"],
        }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_contract_schema(payload: Mapping[str, Any]) -> list[str]:
    """Validate against the JSON Schema of the contract's own declared version."""
    import jsonschema

    version = payload.get("schema_version") if isinstance(payload, Mapping) else None
    schema_path = SCHEMA_PATHS.get(version)
    if schema_path is None:
        return [f"schema_version: unsupported scientific study contract version {version!r} "
                f"(supported: {sorted(SCHEMA_PATHS)})"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(payload)
    )


def load_scientific_study_contract(path: Path, *, repo_root: Path) -> ScientificStudyContract:
    """Load, schema-validate, and hash a contract stored inside the repository."""
    resolved = Path(path).resolve()
    root = Path(repo_root).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ScientificStudyContractError(
            "contract_outside_repository", f"contract must live inside the Atlas repository: {path}"
        ) from exc
    content = resolved.read_bytes()
    payload = json.loads(content.decode("utf-8"))
    errors = validate_contract_schema(payload)
    if errors:
        raise ScientificStudyContractError("invalid_contract_schema", "; ".join(errors))
    semantic_errors = validate_contract_semantics(payload)
    if semantic_errors:
        raise ScientificStudyContractError("invalid_contract_semantics", "; ".join(semantic_errors))
    expected_dir = (
        f"{STUDIES_ROOT_RELATIVE}/{payload['study_identity']['dataset_slug']}/"
        f"{payload['study_identity']['study_revision_label']}/{CONTRACT_FILENAME}"
    )
    if relative != expected_dir:
        raise ScientificStudyContractError(
            "contract_location_mismatch",
            f"contract identity requires location {expected_dir!r}, found {relative!r}",
        )
    if not payload["study_identity"]["study_revision_label"].endswith(payload["source_repository"]["revision"][:12]):
        raise ScientificStudyContractError(
            "revision_label_mismatch",
            "study_revision_label must end with the first 12 characters of the pinned revision",
        )
    return ScientificStudyContract(payload=payload, relative_path=relative, sha256=_sha256_bytes(content))


def validate_contract_semantics(payload: Mapping[str, Any]) -> list[str]:
    """Cross-field coherence rules a JSON Schema cannot express.

    v1 contracts predate these rules and are binary by construction; v2 and
    v3 contracts are checked here, class rules only for classification.
    """
    if payload.get("schema_version") not in (SCHEMA_VERSION_V2, SCHEMA_VERSION_V3, SCHEMA_VERSION_V4):
        return []
    if is_forecasting_contract(payload):
        return validate_forecasting_semantics(payload)
    errors: list[str] = []
    problem = payload["problem"]
    target = problem["target"]
    classes = list(target.get("classes", []))
    features = list(payload["features"]["feature_columns"])
    if set(payload["features"]["numerical"]) | set(payload["features"]["categorical"]) != set(features):
        errors.append("features.numerical + features.categorical must cover exactly features.feature_columns")
    if set(payload["features"]["numerical"]) & set(payload["features"]["categorical"]):
        errors.append("features.numerical and features.categorical must be disjoint")
    if target["column"] in features:
        errors.append("the target column cannot be a feature")
    if problem["problem_type"] == MULTICLASS:
        for order_name in ("estimator_class_order", "public_class_order"):
            order = list(target.get(order_name, []))
            if sorted(map(str, order)) != sorted(map(str, classes)) or len(order) != len(classes):
                errors.append(f"problem.target.{order_name} must be a permutation of problem.target.classes")
    if problem["problem_type"] == BINARY:
        encoding = target.get("encoding") or {}
        if str(target.get("positive_class")) not in {str(k) for k in encoding}:
            errors.append("problem.target.positive_class must be one of the encoded classes")
    split = payload["split"]
    if split["kind"] == "two_stage_random_holdout" and split.get("stratify_by") is not None:
        errors.append("split.kind two_stage_random_holdout requires split.stratify_by = null")
    if split["kind"] == "two_stage_stratified_holdout" and not split.get("stratify_by"):
        errors.append("split.kind two_stage_stratified_holdout requires a split.stratify_by column")
    overlap = (payload.get("interpretive_evidence") or {}).get("group_overlap_diagnostic")
    if overlap:
        unknown = sorted(set(overlap["group_columns"]) - set(features))
        if unknown:
            errors.append(f"group_overlap_diagnostic.group_columns names non-features {unknown}")
        if set(overlap["group_columns"]) == set(features):
            errors.append("group_overlap_diagnostic.group_columns must be a strict subset of the features")
        for evaluation in overlap["evaluations"]:
            if evaluation["evaluated_partition"] in evaluation["reference_partitions"]:
                errors.append("a group-overlap evaluation cannot use its evaluated partition as reference")
    policies = payload.get("feature_policies")
    if policies:
        seen: set[str] = set()
        for policy in policies["policies"]:
            if policy["policy_id"] in seen:
                errors.append(f"duplicate feature policy {policy['policy_id']!r}")
            seen.add(policy["policy_id"])
            unknown = sorted(set(policy["exclude"]) - set(features))
            if unknown:
                errors.append(f"feature policy {policy['policy_id']!r} excludes unknown features {unknown}")
            if len(set(policy["exclude"])) >= len(features):
                errors.append(f"feature policy {policy['policy_id']!r} excludes every feature")
        shortlist = payload.get("family_shortlist") or {}
        if shortlist.get("k", 0) > len(payload["candidates"]):
            errors.append("family_shortlist.k exceeds the number of candidate families")
    ids = [c["model_id"] for c in payload["candidates"]]
    if len(set(ids)) != len(ids):
        errors.append("candidate model_id values must be unique")
    canonical = payload.get("canonical_run")
    if canonical:
        pinned = {f["path"]: f["sha256"] for f in payload["source_repository"]["pinned_files"]}
        if pinned.get(canonical["path"]) != canonical["sha256"]:
            errors.append("canonical_run must be pinned in source_repository.pinned_files with the same SHA-256")
    for group in ("values", "decisions", "runtime_identity"):
        quantities = [item["quantity"] for item in payload["expected_evidence"].get(group, [])]
        duplicated = sorted({q for q in quantities if quantities.count(q) > 1})
        if duplicated:
            errors.append(f"expected_evidence.{group} repeats quantities {duplicated}")
    return errors


def _canonical_run_and_evidence_errors(payload: Mapping[str, Any]) -> list[str]:
    errors = []
    canonical = payload.get("canonical_run")
    if canonical:
        pinned = {f["path"]: f["sha256"] for f in payload["source_repository"]["pinned_files"]}
        if pinned.get(canonical["path"]) != canonical["sha256"]:
            errors.append("canonical_run must be pinned in source_repository.pinned_files with the same SHA-256")
    for group in ("values", "decisions", "runtime_identity"):
        quantities = [item["quantity"] for item in payload["expected_evidence"].get(group, [])]
        duplicated = sorted({q for q in quantities if quantities.count(q) > 1})
        if duplicated:
            errors.append(f"expected_evidence.{group} repeats quantities {duplicated}")
    return errors


def _month_offset(start: str, months: int) -> str:
    year, month = (int(part) for part in start.split("-"))
    position = year * 12 + (month - 1) + months
    return f"{position // 12:04d}-{position % 12 + 1:02d}"


def _month_distance(start: str, end: str) -> int:
    (y1, m1), (y2, m2) = ((int(p) for p in value.split("-")) for value in (start, end))
    return (y2 * 12 + m2) - (y1 * 12 + m1)


def validate_forecasting_semantics(payload: Mapping[str, Any]) -> list[str]:
    """Temporal coherence rules of a v4 forecasting contract."""
    errors: list[str] = []
    problem = payload["problem"]
    if atlas_problem_type_for(problem["study_problem_identity"]) != problem["problem_type"]:
        errors.append("problem.study_problem_identity does not map to problem.problem_type through "
                      "STUDY_PROBLEM_IDENTITIES")
    if problem["forecasting_mode"] != problem["study_problem_identity"].get("forecasting_mode"):
        errors.append("problem.forecasting_mode differs from the study's forecasting_mode")
    source = payload["temporal_source"]
    identity = payload["dataset_identity"]
    if [source["time_column"], source["value_column"]] != list(identity["source_columns"]):
        errors.append("temporal_source time/value columns must be exactly dataset_identity.source_columns")
    if len(identity["source_columns"]) != identity["column_count"]:
        errors.append("dataset_identity.column_count must equal the number of source_columns")
    if source["observations"] != identity["row_count"]:
        errors.append("temporal_source.observations must equal dataset_identity.row_count")
    if source["target_column"] != problem["target"]["column"]:
        errors.append("temporal_source.target_column must be problem.target.column")
    forecast = payload["forecast"]
    if forecast["frequency"] != source["frequency"]:
        errors.append("forecast.frequency must equal temporal_source.frequency")
    protocol = payload["temporal_protocol"]
    development, holdout = protocol["development"], protocol["final_holdout"]
    if source["frequency"] == "M":
        if development["start"] != source["start"] or holdout["end"] != source["end"]:
            errors.append("development must start and the final holdout must end at the source boundaries")
        if _month_offset(development["end"], 1) != holdout["start"]:
            errors.append("the final holdout must start directly after the development window")
        for name, window in (("development", development), ("final_holdout", holdout)):
            if _month_distance(window["start"], window["end"]) + 1 != window["observations"]:
                errors.append(f"temporal_protocol.{name} observations do not match its start/end")
    if development["observations"] + holdout["observations"] != source["observations"]:
        errors.append("development + final_holdout observations must cover the source")
    backtesting = protocol["backtesting"]
    if backtesting["forecast_horizon"] != forecast["horizon"]:
        errors.append("backtesting.forecast_horizon must equal forecast.horizon")
    if backtesting["validation_forecast_count"] != backtesting["fold_count"] * backtesting["forecast_horizon"]:
        errors.append("validation_forecast_count must equal fold_count * forecast_horizon")
    overlapping = backtesting["origin_step_observations"] < backtesting["forecast_horizon"]
    if backtesting["validation_targets_overlap"] is not overlapping:
        errors.append("backtesting.validation_targets_overlap contradicts origin_step_observations vs forecast_horizon")
    last_end = (backtesting["initial_training_observations"]
                + (backtesting["fold_count"] - 1) * backtesting["origin_step_observations"]
                + backtesting["forecast_horizon"])
    if last_end > development["observations"]:
        errors.append("the last backtesting fold reaches beyond the development window")
    schedule = backtesting["fold_schedule"]
    if len(schedule) != backtesting["fold_count"]:
        errors.append("backtesting.fold_schedule must declare fold_count folds")
    elif source["frequency"] == "M":
        for index, fold in enumerate(schedule):
            size = backtesting["initial_training_observations"] + index * backtesting["origin_step_observations"]
            origin = _month_offset(development["start"], size - 1)
            expected = {"fold": index + 1, "train_start": development["start"], "training_observations": size,
                        "forecast_origin": origin, "validation_start": _month_offset(origin, 1),
                        "validation_end": _month_offset(origin, backtesting["forecast_horizon"]),
                        "validation_observations": backtesting["forecast_horizon"]}
            if dict(fold) != expected:
                errors.append(f"backtesting.fold_schedule[{index}] does not follow the declared parameters")
    finalization = payload["finalization"]
    if finalization["forecast_periods"] != holdout["observations"]:
        errors.append("finalization.forecast_periods must equal the final holdout observations")
    if finalization["forecast_origin"] != development["end"]:
        errors.append("finalization.forecast_origin must be the last development period")
    ids = [c["candidate_id"] for c in payload["candidates"]]
    if len(set(ids)) != len(ids):
        errors.append("candidate_id values must be unique")
    ranks = [c["complexity_rank"] for c in payload["candidates"]]
    if len(set(ranks)) != len(ranks):
        errors.append("complexity_rank values must be unique")
    roles = [c["role"] for c in payload["candidates"]]
    if roles.count("primary_baseline") != 1:
        errors.append("exactly one candidate must be the primary_baseline")
    if finalization["primary_baseline_reference"]["role"] != "primary_baseline":
        errors.append("finalization.primary_baseline_reference must reference the primary_baseline role")
    for candidate in payload["candidates"]:
        if candidate["seasonal_period"] != forecast["seasonal_period"]:
            errors.append(f"candidate {candidate['candidate_id']} seasonal_period differs from forecast.seasonal_period")
    metrics = payload["metrics"]
    declared = [m["metric_id"] for m in metrics["evaluated"]]
    if metrics["primary"] not in declared:
        errors.append("metrics.primary must be an evaluated metric")
    for metric in metrics["evaluated"]:
        period = (metric.get("parameters") or {}).get("seasonal_period")
        if period is not None and period != forecast["seasonal_period"]:
            errors.append(f"metric {metric['metric_id']} seasonal_period differs from forecast.seasonal_period")
    diagnostics = {d["field"] for d in metrics["diagnostics"]}
    record_fields = {f"pooled_{m}" for m in declared} | diagnostics | FORECASTING_CAPABILITIES["fixed_record_fields"]
    selection = payload["selection"]
    for label, field in ([("leader", selection["leader"]["field"]), ("practical_tie", selection["practical_tie"]["field"])]
                         + [("tie_breakers", b["field"]) for b in selection["tie_breakers"]]
                         + [("eligibility", f) for f in selection["eligibility"]["required_finite_fields"]]):
        if field not in record_fields:
            errors.append(f"selection.{label} field {field!r} is not a pooled metric, diagnostic or fixed field")
    if selection["leader"]["field"] != f"pooled_{metrics['primary']}":
        errors.append("selection.leader.field must be the pooled primary metric")
    return errors + _canonical_run_and_evidence_errors(payload)


def assess_forecasting_protocol_support(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every element of a forecasting contract the forecasting runner cannot execute."""
    from pipeline import forecasting_models, metric_identity

    caps = FORECASTING_CAPABILITIES
    gaps: list[dict[str, Any]] = []

    def check(element: str, value: Any, allowed: Any) -> None:
        if value not in allowed:
            gaps.append({"element": element, "value": value,
                         "reason": f"not implemented by the Atlas forecasting runner (supported: {sorted(allowed)})"})

    check("problem.problem_type", problem_type_of(payload), caps["problem_types"])
    check("study_identity.protocol_kind", payload["study_identity"]["protocol_kind"], caps["protocol_kinds"])
    check("temporal_source.kind", payload["temporal_source"]["kind"], caps["temporal_source_kinds"])
    check("temporal_source.frequency", payload["temporal_source"]["frequency"], caps["frequencies"])
    protocol = payload["temporal_protocol"]
    check("temporal_protocol.partition_fingerprint.kind", protocol["partition_fingerprint"]["kind"],
          caps["partition_fingerprint_kinds"])
    check("temporal_protocol.backtesting.mode", protocol["backtesting"]["mode"], caps["backtesting_modes"])
    check("temporal_protocol.backtesting.refit_policy", protocol["backtesting"]["refit_policy"], caps["refit_policies"])
    if protocol["backtesting"]["shuffle"] is not False:
        gaps.append({"element": "temporal_protocol.backtesting.shuffle", "value": True,
                     "reason": "a temporal backtest never shuffles"})
    selection = payload["selection"]
    check("selection.kind", selection["kind"], caps["selection_kinds"])
    check("selection.practical_tie.bound", selection["practical_tie"]["bound"], caps["practical_tie_bounds"])
    check("selection.tie_break_mode", selection["tie_break_mode"], caps["tie_break_modes"])
    check("selection.ranking.kind", selection["ranking"]["kind"], caps["ranking_kinds"])
    for breaker in selection["tie_breakers"]:
        check("selection.tie_breakers.direction", breaker["direction"], caps["tie_breaker_directions"])
    check("finalization.kind", payload["finalization"]["kind"], caps["finalization_kinds"])
    for diagnostic in payload["metrics"]["diagnostics"]:
        check("metrics.diagnostics.kind", diagnostic["kind"], caps["diagnostic_kinds"])
    policy = payload["failure_policy"]
    for element in ("programming_error_action", "baseline_failure_action"):
        if policy[element] != "abort_backtest":
            gaps.append({"element": f"failure_policy.{element}", "value": policy[element],
                         "reason": "only abort_backtest is implemented"})
    if policy["specification_failure_action"] != "mark_ineligible":
        gaps.append({"element": "failure_policy.specification_failure_action",
                     "value": policy["specification_failure_action"], "reason": "only mark_ineligible is implemented"})
    import builtins

    for name in policy["programming_error_types"]:
        candidate = getattr(builtins, name, None)
        if not (isinstance(candidate, type) and issubclass(candidate, BaseException)):
            gaps.append({"element": "failure_policy.programming_error_types", "value": name,
                         "reason": "not a built-in exception type"})
    vocabulary = metric_vocabulary(FORECASTING)
    for metric in payload["metrics"]["evaluated"]:
        if metric["metric_id"] not in vocabulary:
            gaps.append({"element": "metrics.evaluated", "value": metric["metric_id"],
                         "reason": f"metric is not implemented for {FORECASTING!r}"})
            continue
        try:
            metric_identity.resolve_parameterized_scientific_metric(
                metric["metric_id"], metric.get("parameters"), problem_type=FORECASTING)
        except metric_identity.MetricIdentityError as exc:
            gaps.append({"element": "metrics.evaluated", "value": metric["metric_id"], "reason": str(exc)})
    for candidate in payload["candidates"]:
        prefix = f"candidates[{candidate['candidate_id']}]"
        check(f"{prefix}.role", candidate["role"], caps["candidate_roles"])
        family_id = candidate["family"]
        family = model_families.MODEL_FAMILIES.get(family_id)
        if family is None or not family.scientific_forecasting:
            gaps.append({"element": f"{prefix}.family", "value": family_id,
                         "reason": "not a scientific forecasting family in pipeline.model_families"})
            continue
        if candidate["study_family"] not in family.forecasting_family_names:
            gaps.append({"element": f"{prefix}.study_family", "value": candidate["study_family"],
                         "reason": f"not a recognized name of family {family_id!r}"})
        if family.forecasting_constructor is not None and candidate["constructor"] != family.forecasting_constructor:
            gaps.append({"element": f"{prefix}.constructor", "value": candidate["constructor"],
                         "reason": f"family {family_id!r} executes {family.forecasting_constructor!r}"})
        try:
            forecasting_models.get_adapter(family_id).validate_parameters(candidate["fixed_params"],
                                                                         candidate["seasonal_period"])
        except forecasting_models.ForecastingAdapterError as exc:
            gaps.append({"element": f"{prefix}.fixed_params", "value": exc.code, "reason": str(exc)})
    return gaps


def assess_protocol_support(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return every contract element the Atlas reproduction engine cannot execute.

    Dispatch is by ``problem.problem_type`` (never by dataset): the metric
    vocabulary, the admissible threshold policy, and the decision rule are
    problem-type specific; a forecasting contract goes to the temporal runner's
    own capability assessment.
    """
    if is_forecasting_contract(payload):
        return assess_forecasting_protocol_support(payload)
    caps = REPRODUCTION_CAPABILITIES
    gaps: list[dict[str, Any]] = []
    problem_type = problem_type_of(payload)

    def check(element: str, value: Any, allowed: Any) -> None:
        if value not in allowed:
            gaps.append({
                "element": element,
                "value": value,
                "reason": f"not implemented by the Atlas reproduction engine (supported: {sorted(allowed)})",
            })

    check("problem.problem_type", problem_type, caps["problem_types"])
    check("study_identity.protocol_kind", payload["study_identity"]["protocol_kind"], caps["protocol_kinds"])
    for index, rule in enumerate(payload["preparation"]["rules"]):
        check(f"preparation.rules[{index}].kind", rule["kind"], caps["preparation_rule_kinds"])
    check("split.kind", payload["split"]["kind"], caps["split_kinds"])
    membership = payload["split"].get("membership")
    if membership is not None:
        check("split.membership.kind", membership.get("kind"), caps["membership_kinds"])
    check("preprocessing.kind", payload["preprocessing"]["kind"], caps["preprocessing_kinds"])
    check("cross_validation.kind", payload["cross_validation"]["kind"], caps["cross_validation_kinds"])
    check("selection.kind", payload["selection"]["kind"], caps["selection_kinds"])
    threshold_policy = payload.get("threshold_policy")
    if threshold_policy is not None:
        check("threshold_policy.kind", threshold_policy["kind"], caps["threshold_policy_kinds"])
    decision_rule = payload["problem"].get("decision_rule")
    if decision_rule is not None:
        check("problem.decision_rule.kind", decision_rule.get("kind"), caps["decision_rule_kinds"])
    overlap = (payload.get("interpretive_evidence") or {}).get("group_overlap_diagnostic")
    if overlap is not None:
        check("interpretive_evidence.group_overlap_diagnostic.kind", overlap["kind"],
              caps["interpretive_evidence_kinds"])
    # Problem-type coherence: a regression protocol has no class concept, and
    # stratification needs a class label.
    if problem_type == REGRESSION:
        for element, present in (("threshold_policy", threshold_policy is not None),
                                 ("problem.decision_rule", decision_rule is not None)):
            if present:
                gaps.append({"element": element, "value": "declared",
                             "reason": "a continuous regression protocol has no classification decision concept"})
        for element, value in (("split.kind", payload["split"]["kind"]),
                               ("cross_validation.kind", payload["cross_validation"]["kind"])):
            if value.startswith(("stratified", "two_stage_stratified")):
                gaps.append({"element": element, "value": value,
                             "reason": "stratification requires class labels; a continuous target has none"})
    if overlap is not None and problem_type != REGRESSION:
        gaps.append({"element": "interpretive_evidence.group_overlap_diagnostic", "value": problem_type,
                     "reason": "group-overlap subset metrics are implemented for continuous_regression only"})
    threshold_kind = threshold_policy["kind"] if threshold_policy is not None else None
    if problem_type == MULTICLASS and threshold_kind != "not_applicable":
        gaps.append({"element": "threshold_policy.kind", "value": threshold_kind,
                     "reason": "a multiclass argmax protocol has no binary threshold; it must be declared not_applicable"})
    if problem_type == BINARY and threshold_kind in (None, "not_applicable"):
        gaps.append({"element": "threshold_policy.kind", "value": threshold_kind,
                     "reason": "the binary reproduction protocol requires a declared threshold policy"})
    if payload.get("family_shortlist"):
        check("family_shortlist.kind", payload["family_shortlist"]["kind"], caps["family_shortlist_kinds"])
    if payload.get("feature_policies"):
        check("feature_policies.kind", payload["feature_policies"]["kind"], caps["feature_policy_kinds"])
    check("final_evaluation.kind", payload["final_evaluation"]["kind"], caps["final_evaluation_kinds"])
    vocabulary = metric_vocabulary(problem_type)
    for metric in payload["metrics"]["evaluated"]:
        if metric not in vocabulary:
            gaps.append({"element": "metrics.evaluated", "value": metric,
                         "reason": f"metric is not implemented for {problem_type!r} (supported: {sorted(vocabulary)})"})
    for metric in payload["metrics"].get("cv_scorers", []):
        if metric not in vocabulary or metric == "minimum_per_class_recall":
            gaps.append({"element": "metrics.cv_scorers", "value": metric,
                         "reason": "no cross-validation scorer is implemented for this metric"})
    for field_name in ("primary", "refit"):
        metric = payload["metrics"].get(field_name)
        if metric is not None and metric not in vocabulary:
            gaps.append({"element": f"metrics.{field_name}", "value": metric,
                         "reason": f"metric is not implemented for {problem_type!r}"})
    for breaker in payload["selection"].get("tie_breakers", []):
        if not _is_supported_tie_breaker_field(breaker.get("field"), problem_type):
            gaps.append({"element": "selection.tie_breakers.field", "value": breaker.get("field"),
                         "reason": "tie-breaker field is not a validation/cv metric or a supported fixed field"})

    task_type = (
        model_families.CLASSIFICATION
        if payload["problem"]["problem_type"].endswith("classification")
        else model_families.REGRESSION
    )
    all_candidates = list(payload["candidates"])
    if payload.get("baseline"):
        all_candidates.append(payload["baseline"])
    for candidate in all_candidates:
        prefix = f"candidates[{candidate['model_id']}]"
        check(f"{prefix}.search.kind", candidate["search"]["kind"], caps["search_kinds"])
        family_id = candidate["family"]
        if family_id not in model_families.MODEL_FAMILIES:
            gaps.append({"element": f"{prefix}.family", "value": family_id,
                         "reason": "model family is not registered in pipeline.model_families"})
            continue
        family = model_families.get_family(family_id)
        if not family.supports(task_type):
            gaps.append({"element": f"{prefix}.family", "value": family_id,
                         "reason": f"model family does not support task type {task_type!r}"})
            continue
        try:
            accepted = model_families.accepted_hyperparameters(family_id, task_type)
        except model_families.ModelFamilyError as exc:
            gaps.append({"element": f"{prefix}.family", "value": family_id, "reason": str(exc)})
            continue
        declared = set(candidate["fixed_params"]) | set(candidate["search"].get("space", {}))
        for name in sorted(declared - accepted):
            gaps.append({"element": f"{prefix}.hyperparameter", "value": name,
                         "reason": "hyperparameter is not accepted by the registered estimator"})
    return gaps


def _notebook_output_text(notebook: Mapping[str, Any], cell_index: int) -> str:
    cells = notebook.get("cells", [])
    if not 0 <= cell_index < len(cells):
        return ""
    chunks: list[str] = []
    for output in cells[cell_index].get("outputs", []):
        if output.get("output_type") == "stream":
            text = output.get("text", "")
        else:
            text = output.get("data", {}).get("text/plain", "")
        chunks.append("".join(text) if isinstance(text, list) else str(text))
    return "\n".join(chunks)


def _resolve_json_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if pointer in ("", "/"):
        return True, document
    node = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        elif isinstance(node, Mapping) and token in node:
            node = node[token]
        else:
            return False, None
    return True, node


def _locate_rendered_text(checkout: Path, item: Mapping[str, Any], cache: dict[str, Any]) -> bool:
    """Check that an expected value is present at its source locator.

    Locators: ``notebook_cell_output:<index>`` and ``file_text`` search for
    the rendered text; ``json_pointer:<RFC 6901 pointer>`` resolves a value in
    a structured JSON artifact and requires it to equal the expected value.
    """
    source = item["source"]
    path = checkout / source["path"]
    if not path.is_file():
        return False
    locator = source["locator"]
    if locator.startswith("json_pointer:"):
        if source["path"] not in cache:
            cache[source["path"]] = json.loads(path.read_text(encoding="utf-8"))
        found, value = _resolve_json_pointer(cache[source["path"]], locator.split(":", 1)[1])
        return found and value == item["expected"]
    if locator.startswith("notebook_cell_output:"):
        if source["path"] not in cache:
            cache[source["path"]] = json.loads(path.read_text(encoding="utf-8"))
        text = _notebook_output_text(cache[source["path"]], int(locator.split(":", 1)[1]))
    elif locator == "file_text" or locator.startswith("file_text:"):
        text = path.read_text(encoding="utf-8")
    else:
        return False
    return source["rendered_text"] in text


def verify_against_study_checkout(payload: Mapping[str, Any], checkout_root: Path) -> dict[str, Any]:
    """Check a read-only study checkout against the contract's pins.

    Reports the checkout revision, every pinned-file hash comparison, and
    whether every expected value's rendered text is present at its locator.
    The checkout is only read; its absolute location is never returned.
    """
    checkout = Path(checkout_root).resolve()
    revision: str | None
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        revision = completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        revision = None
    pinned_revision = payload["source_repository"]["revision"]

    file_checks = []
    for pinned in payload["source_repository"]["pinned_files"]:
        target = checkout / pinned["path"]
        observed = _sha256_bytes(target.read_bytes()) if target.is_file() else None
        file_checks.append({
            "path": pinned["path"],
            "role": pinned["role"],
            "expected_sha256": pinned["sha256"],
            "observed_sha256": observed,
            "matches": observed == pinned["sha256"],
        })

    cache: dict[str, Any] = {}
    evidence_checks = []
    for group in ("values", "decisions", "runtime_identity"):
        for item in payload["expected_evidence"].get(group, []):
            evidence_checks.append({
                "quantity": item["quantity"],
                "source_path": item["source"]["path"],
                "locator": item["source"]["locator"],
                "rendered_text_found": _locate_rendered_text(checkout, item, cache),
            })

    revision_matches = revision == pinned_revision
    files_match = all(check["matches"] for check in file_checks)
    # Protocol gates (membership digests, final-fit row count) are reference
    # evidence too, so their sources are re-checked like expected values.
    gate_items = []
    gate = (payload.get("split") or {}).get("membership_gate")
    if gate:
        for partition, digest in gate["expected_membership_sha256"].items():
            pointer = gate["source"]["locator"].rstrip("/") + "/" + partition
            gate_items.append(("split.membership_gate." + partition, {"expected": digest, "source": {
                **gate["source"], "locator": pointer}}))
    row_gate = (payload.get("final_evaluation") or {}).get("fit_row_count_gate")
    if row_gate:
        gate_items.append(("final_evaluation.fit_row_count_gate", {"expected": row_gate["expected_rows"],
                                                                   "source": row_gate["source"]}))
    for quantity, item in gate_items:
        evidence_checks.append({
            "quantity": quantity,
            "source_path": item["source"]["path"],
            "locator": item["source"]["locator"],
            "rendered_text_found": _locate_rendered_text(checkout, item, cache),
        })
    parameter_checks = verify_protocol_parameter_sources(payload, checkout, cache)
    evidence_found = all(check["rendered_text_found"] for check in evidence_checks) and all(
        check["matches"] for check in parameter_checks)
    if revision_matches and files_match and evidence_found:
        status = "synchronized"
    elif files_match and evidence_found:
        status = "revision_differs_but_pinned_content_unchanged"
    else:
        status = "study_revision_drift"
    return {
        "status": status,
        "pinned_revision": pinned_revision,
        "checkout_revision": revision,
        "revision_matches": revision_matches,
        "pinned_files": file_checks,
        "expected_evidence_locators": evidence_checks,
        "protocol_parameter_sources": parameter_checks,
        "checkout_location_recorded": False,
    }


def verify_protocol_parameter_sources(payload: Mapping[str, Any], checkout: Path,
                                      cache: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Check declared protocol inputs (seeds, orders, tolerances...) against the study's own artifact.

    Each ``protocol_parameter_sources`` entry names a JSON pointer into this
    contract and a JSON pointer into a pinned study file; both must resolve to
    equal values, so a declared parameter cannot silently drift from the study.
    """
    cache = {} if cache is None else cache
    checks = []
    for entry in payload.get("protocol_parameter_sources", []):
        found_contract, declared = _resolve_json_pointer(payload, entry["contract_pointer"])
        path = Path(checkout) / entry["source"]["path"]
        observed = None
        found_source = False
        if path.is_file():
            if entry["source"]["path"] not in cache:
                cache[entry["source"]["path"]] = json.loads(path.read_text(encoding="utf-8"))
            found_source, observed = _resolve_json_pointer(cache[entry["source"]["path"]],
                                                           entry["source"]["locator"].split(":", 1)[1])
        checks.append({
            "contract_pointer": entry["contract_pointer"],
            "source_path": entry["source"]["path"],
            "locator": entry["source"]["locator"],
            "declared": declared if found_contract else None,
            "study_value": observed if found_source else None,
            "matches": bool(found_contract and found_source and declared == observed),
        })
    return checks


def author_contract_from_draft(draft: Mapping[str, Any], checkout_root: Path) -> dict[str, Any]:
    """Materialize a contract from an authoring draft and a read-only study checkout.

    Generic and deterministic: every ``json_pointer`` expected value, protocol
    gate and pinned-file hash is *read* from the pinned study checkout, never
    transcribed by hand. Draft conventions:

    * an expected item whose locator is ``json_pointer:...`` and which omits
      ``expected`` receives the pointed value (and a rendered text);
    * ``file_text`` items must carry their expected value and rendered text,
      which ``verify_against_study_checkout`` re-checks;
    * a pinned file (or the lock / canonical run) without ``sha256`` receives
      the hash of the checkout file;
    * a membership gate or fit-row gate without values receives them from its
      source pointer.
    """
    checkout = Path(checkout_root).resolve()
    contract = json.loads(json.dumps(draft))
    cache: dict[str, Any] = {}

    def pointed(source: Mapping[str, Any]) -> Any:
        if source["path"] not in cache:
            cache[source["path"]] = json.loads((checkout / source["path"]).read_text(encoding="utf-8"))
        found, value = _resolve_json_pointer(cache[source["path"]], source["locator"].split(":", 1)[1])
        if not found:
            raise ScientificStudyContractError("unresolved_json_pointer",
                                               f"{source['path']} {source['locator']} does not resolve")
        return value

    def file_hash(relative: str) -> str:
        return _sha256_bytes((checkout / relative).read_bytes())

    for pinned in contract["source_repository"]["pinned_files"]:
        pinned.setdefault("sha256", file_hash(pinned["path"]))
    if contract.get("canonical_run"):
        contract["canonical_run"].setdefault("sha256", file_hash(contract["canonical_run"]["path"]))
    lock = contract["scientific_environment"]["lock"]
    lock.setdefault("sha256", file_hash(lock["path"]))
    if lock.get("python_version_file"):
        lock.setdefault("python_version_file_sha256", file_hash(lock["python_version_file"]))
    for group in ("values", "decisions", "runtime_identity"):
        for item in contract["expected_evidence"].get(group, []):
            source = item["source"]
            if source["locator"].startswith("json_pointer:") and "expected" not in item:
                item["expected"] = pointed(source)
                source.setdefault("rendered_text", json.dumps(item["expected"], ensure_ascii=False, sort_keys=True))
            item.setdefault("reported_decimal_places", None)
    for entry in contract.get("protocol_parameter_sources", []):
        entry["source"].setdefault("rendered_text", json.dumps(pointed(entry["source"]), ensure_ascii=False, sort_keys=True))
    gate = (contract.get("split") or {}).get("membership_gate")
    if gate is not None and "expected_membership_sha256" not in gate:
        gate["expected_membership_sha256"] = pointed(gate["source"])
        gate["source"].setdefault("rendered_text", json.dumps(gate["expected_membership_sha256"], sort_keys=True))
    row_gate = (contract.get("final_evaluation") or {}).get("fit_row_count_gate")
    if row_gate is not None and "expected_rows" not in row_gate:
        row_gate["expected_rows"] = pointed(row_gate["source"])
        row_gate["source"].setdefault("rendered_text", json.dumps(row_gate["expected_rows"]))
    return contract


def main(argv: list[str] | None = None) -> int:
    """``author`` materializes a contract from a draft; ``verify`` re-checks one against a checkout."""
    import argparse

    parser = argparse.ArgumentParser(description="Author or verify a Scientific Study Contract.")
    sub = parser.add_subparsers(dest="command", required=True)
    author = sub.add_parser("author")
    author.add_argument("--draft", required=True)
    author.add_argument("--study-checkout", required=True)
    author.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--contract", required=True)
    verify.add_argument("--study-checkout", required=True)
    verify.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args(argv)
    if args.command == "author":
        draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
        contract = author_contract_from_draft(draft, Path(args.study_checkout))
        errors = validate_contract_schema(contract) + validate_contract_semantics(contract)
        if errors:
            raise ScientificStudyContractError("invalid_contract", "; ".join(errors))
        output = Path(args.output)
        if output.exists():
            raise ScientificStudyContractError("contract_exists", f"{output} exists; contracts are immutable per revision")
        output.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"written": str(output), "sha256": _sha256_bytes(output.read_bytes())}, indent=2))
        return 0
    root = Path(args.repo_root).resolve()
    contract = load_scientific_study_contract(root / args.contract, repo_root=root)
    result = verify_against_study_checkout(contract.payload, Path(args.study_checkout))
    summary = {
        "status": result["status"],
        "revision_matches": result["revision_matches"],
        "pinned_files_matching": sum(c["matches"] for c in result["pinned_files"]),
        "pinned_files_total": len(result["pinned_files"]),
        "evidence_locators_found": sum(c["rendered_text_found"] for c in result["expected_evidence_locators"]),
        "evidence_locators_total": len(result["expected_evidence_locators"]),
        "parameters_matching": sum(c["matches"] for c in result["protocol_parameter_sources"]),
        "parameters_total": len(result["protocol_parameter_sources"]),
        "failures": [c for c in result["expected_evidence_locators"] if not c["rendered_text_found"]]
        + [c for c in result["protocol_parameter_sources"] if not c["matches"]]
        + [c for c in result["pinned_files"] if not c["matches"]],
        "protocol_support_gaps": assess_protocol_support(contract.payload),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "synchronized" else 1


if __name__ == "__main__":
    raise SystemExit(main())
