"""Continuous-regression Scientific Reproduction: contract v3, engine stages, report v3.

Dataset-agnostic. A synthetic study of grouped measurements (three group
columns identify a "recipe"; ``age`` varies inside a recipe) is built inside
``tmp_path`` with no identifier column, a shuffled non-stratified two-stage
split with row-occurrence membership, KFold search over Dummy/Ridge/tree
families, a leader-anchored practical-tie rule on a lower-is-better metric,
and a descriptive group-overlap diagnostic, so every stage runs in seconds.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pipeline import metric_identity, model_families
from pipeline import scientific_environment as env
from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc


REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "0123456789abcdef0123456789abcdef01234567"
LABEL = f"study-{REVISION[:12]}"
SLUG = "synthetic-regression"
FEATURES = ["alpha", "beta", "gamma", "age"]
GROUP_COLUMNS = ["alpha", "beta", "gamma"]
TARGET = "Measured strength"


# --------------------------------------------------------------------------
# synthetic continuous-regression study
# --------------------------------------------------------------------------


def _synthetic_csv(path: Path, recipes: int = 70) -> None:
    rng = random.Random(7)
    lines = [",".join(FEATURES + [TARGET])]
    for _ in range(recipes):
        alpha, beta, gamma = round(rng.uniform(100, 500), 1), round(rng.uniform(0, 200), 1), round(rng.uniform(0, 30), 1)
        for age in rng.sample([3, 7, 14, 28, 56, 90], k=rng.randint(1, 5)):
            strength = 0.08 * alpha + 0.03 * beta - 0.4 * gamma + 9.0 * np.log(age) + rng.gauss(0, 2.5)
            lines.append(f"{alpha},{beta},{gamma},{age},{strength:.2f}")
    lines.append(lines[1])  # exact repeated row: exercises the occurrence ordinal
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate(model_id, family, fixed, scaling, space, count):
    return {"model_id": model_id, "family": family, "fixed_params": fixed, "numerical_scaling": scaling,
            "search": {"kind": "grid", "space": space, "expected_candidate_count": count},
            "eligible_for_selection": True}


def _contract(dataset_sha: str, size: int, rows: int) -> dict:
    source = {"path": "reproducibility/canonical-run.json", "locator": "json_pointer:/x", "rendered_text": "x"}
    return {
        "schema_version": "scientific-study-contract.v3",
        "artifact_kind": "scientific_study_contract",
        "study_identity": {"study_id": "dataset-study-synthetic-regression", "dataset_slug": SLUG,
                           "protocol_kind": "tabular_holdout_model_selection.v2", "study_revision_label": LABEL},
        "source_repository": {"url": "https://example.invalid/study", "revision": REVISION,
                              "pinned_files": [{"path": "README.md", "sha256": "0" * 64, "role": "narrative"}]},
        "dataset_identity": {"file_name": "synthetic.csv", "sha256": dataset_sha, "size_bytes": size,
                             "row_count": rows, "column_count": 5, "read_format": "csv", "read_options": {},
                             "atlas_local_path": f"data/scientific-studies/{SLUG}/synthetic.csv"},
        "scientific_environment": {"python": "3.12.0", "platform": None, "core_packages": {"scikit-learn": "1.9.0"},
                                   "lock": {"path": "pylock.toml", "sha256": "1" * 64, "format": "pep751"},
                                   "compatibility_policy": {"python": "same_major", "core_packages": "same_major"}},
        "problem": {
            "problem_type": "continuous_regression",
            "target": {"column": TARGET, "semantics": "continuous_quantitative", "unit": "MPa",
                       "value_representation": "float", "value_validation": "numeric_complete_finite"},
            "identifier_columns": [],
            "classification_concepts": {"applicable": False, "reason": "continuous_regression_has_no_class_concepts"},
        },
        "features": {"feature_columns": list(FEATURES), "numerical": list(FEATURES), "categorical": []},
        "preparation": {"rules": [], "row_removal": "none"},
        "split": {"kind": "two_stage_random_holdout",
                  "membership": {"kind": "technical_row_occurrence", "digest_order": "source_position"},
                  "order_by_identifier": False,
                  "fractions": {"train": 0.7, "validation": 0.15, "test": 0.15}, "stratify_by": None,
                  "shuffle": True, "seeds": {"train_vs_temporary": 42, "validation_vs_test": 43},
                  "partition_handoff": {"kind": "csv_roundtrip", "float_format": "%.15g"},
                  "partition_fingerprint": {"kind": "csv_bytes_sha256", "float_format": "%.15g"}},
        "preprocessing": {"kind": "column_transformer_onehot_plus_numeric"},
        "cross_validation": {"kind": "k_fold", "n_splits": 3, "shuffle": True, "random_state": 42, "partition": "train"},
        "metrics": {"primary": "mae", "refit": "mae", "evaluated": ["mae", "rmse", "r2", "medae"],
                    "cv_scorers": ["mae", "rmse", "r2", "medae"]},
        "baseline": {"model_id": "dummy_median", "family": "dummy_prior", "fixed_params": {"strategy": "median"},
                     "numerical_scaling": "passthrough", "search": {"kind": "none"}, "eligible_for_selection": False},
        "candidates": [
            _candidate("ridge", "ridge", {}, "standard", {"alpha": [0.1, 10.0]}, 2),
            _candidate("decision_tree", "decision_tree", {"random_state": 42}, "passthrough",
                       {"max_depth": [3, None], "min_samples_leaf": [1, 5]}, 4),
            _candidate("random_forest", "random_forest", {"n_estimators": 20, "random_state": 42, "n_jobs": 1},
                       "passthrough", {"max_features": [1.0, "sqrt"]}, 2),
            _candidate("hist_gradient_boosting", "hist_gradient_boosting", {"max_iter": 60, "random_state": 42},
                       "passthrough", {"learning_rate": [0.1], "max_leaf_nodes": [15]}, 1),
        ],
        "search_execution": {"n_jobs": 1, "search_partition": "train", "validation_in_search": False,
                             "test_in_search": False},
        "selection": {
            "kind": "leader_anchored_practical_tie", "partition": "validation", "candidate_space": "searched_families",
            "eligibility": {"metric": "mae", "margin": 0.0, "strict": True, "baseline_model_id": "dummy_median"},
            "leader": {"metric": "mae", "direction": "min"},
            "practical_tie": {"metric": "mae", "tolerance": 0.10, "requires_cv_interval_overlap": False,
                              "bound": "leader_plus_tolerance"},
            "tie_breakers": [
                {"criterion": "lower_validation_rmse", "field": "validation_rmse", "direction": "min"},
                {"criterion": "lower_validation_medae", "field": "validation_medae", "direction": "min"},
                {"criterion": "lower_cv_mae_std", "field": "cv_mae_std", "direction": "min"},
                {"criterion": "higher_validation_r2", "field": "validation_r2", "direction": "max"},
                {"criterion": "stable_model_id", "field": "model_id", "direction": "min"},
            ],
        },
        "final_evaluation": {"kind": "refit_on_train_plus_validation_single_test_evaluation",
                             "fit_partitions": ["train", "validation"], "evaluation_partition": "test",
                             "evaluation_count": 1},
        "interpretive_evidence": {"group_overlap_diagnostic": {
            "kind": "non_destructive_group_overlap_diagnostic", "group_label": "recipe",
            "group_columns": list(GROUP_COLUMNS),
            "evaluations": [
                {"evaluated_partition": "validation", "reference_partitions": ["train"],
                 "model": "selected_candidate_fitted_on_train"},
                {"evaluated_partition": "test", "reference_partitions": ["train", "validation"],
                 "model": "final_model_fitted_on_fit_partitions"}],
            "minimum_subset_rows": 2, "used_for_selection": False,
            "interpretation": ["A repeated group does not prove duplicate entity identity."]}},
        "tolerance_policy": {"numeric_absolute": 1e-9, "count_absolute": 0, "rationale": "synthetic"},
        "expected_evidence": {
            "values": [{"quantity": "partitions.train.rows", "expected": 0, "comparison": "count",
                        "reported_decimal_places": None, "source": source}],
            "decisions": [],
            "runtime_identity": [],
        },
        "evidence_gaps": [],
        "protocol_integrity": {"test_procedurally_isolated_in_canonical_run": True,
                               "historical_test_exposure": {"exposed": False, "description": "none"},
                               "statement": "synthetic"},
        "limitations": ["synthetic"],
        "authoring": {"authored_by": "test", "authored_at": "2026-01-01T00:00:00Z", "method": "fixture"},
    }


def _materialize(root: Path) -> tuple[dict, Path]:
    dataset = root / f"data/scientific-studies/{SLUG}/synthetic.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    _synthetic_csv(dataset)
    rows = len(dataset.read_text().splitlines()) - 1
    payload = _contract(hashlib.sha256(dataset.read_bytes()).hexdigest(), dataset.stat().st_size, rows)
    payload["expected_evidence"]["values"][0]["expected"] = _train_rows(rows)
    return payload, dataset


RUNTIME = {"python": "3.12.1", "platform": "linux-x86_64", "core_packages": {"scikit-learn": "1.9.0"}}


def _write(root: Path, payload: dict) -> ssc.ScientificStudyContract:
    path = root / ssc.STUDIES_ROOT_RELATIVE / SLUG / LABEL / ssc.CONTRACT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return ssc.load_scientific_study_contract(path, repo_root=root)


def _train_rows(rows: int) -> int:
    from sklearn.model_selection import train_test_split

    return len(train_test_split(list(range(rows)), test_size=0.3, random_state=42)[0])


@pytest.fixture()
def study(tmp_path: Path):
    payload, dataset = _materialize(tmp_path)
    return {"root": tmp_path, "payload": payload, "dataset": dataset,
            "write": lambda data: _write(tmp_path, data)}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """One full synthetic run shared by read-only assertions."""
    root = tmp_path_factory.mktemp("regression")
    payload, dataset = _materialize(root)
    contract = _write(root, payload)
    result = sr.build_reproduction(contract, repo_root=root, runtime=RUNTIME).run(run_id="repro-reg", n_jobs=1)
    return {"root": root, "result": result, "report": result.build_report(), "payload": payload,
            "contract": contract, "dataset": dataset}


# --------------------------------------------------------------------------
# contract v3 schema and semantics
# --------------------------------------------------------------------------


def test_regression_contract_v3_is_schema_and_semantically_valid(study):
    assert ssc.validate_contract_schema(study["payload"]) == []
    assert ssc.validate_contract_semantics(study["payload"]) == []
    assert ssc.assess_protocol_support(study["payload"]) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["problem"]["target"].update(positive_class="high"),
        lambda p: p["problem"]["target"].update(classes=["low", "high"]),
        lambda p: p["problem"]["target"].update(public_class_order=["a", "b"]),
        lambda p: p["problem"]["target"].update(encoding={"a": 0}),
        lambda p: p["problem"].update(decision_rule={"kind": "probability_threshold"}),
        lambda p: p["problem"].pop("classification_concepts"),
        lambda p: p.update(threshold_policy={"kind": "not_applicable", "applicable": False, "reason": "x"}),
        lambda p: p["metrics"].update(default_threshold=0.5),
        lambda p: p["split"].update(stratify_by=TARGET),
        lambda p: p["problem"]["target"].pop("value_representation"),
    ],
)
def test_regression_contract_rejects_classification_concepts(study, mutate):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    assert ssc.validate_contract_schema(payload), "class concepts must be structurally absent for regression"


def test_classification_contract_v3_cannot_carry_regression_only_fields(study):
    payload = json.loads((REPO_ROOT / "pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/"
                          "scientific-study-contract.json").read_text(encoding="utf-8"))
    payload["schema_version"] = "scientific-study-contract.v3"
    assert ssc.validate_contract_schema(payload) == []  # v3 is a superset of v2 for classification
    payload["problem"]["classification_concepts"] = {"applicable": False, "reason": "x"}
    assert ssc.validate_contract_schema(payload)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p["interpretive_evidence"]["group_overlap_diagnostic"].update(group_columns=["nope"]), "non-features"),
        (lambda p: p["interpretive_evidence"]["group_overlap_diagnostic"].update(group_columns=list(FEATURES)),
         "strict subset"),
        (lambda p: p["interpretive_evidence"]["group_overlap_diagnostic"]["evaluations"][0].update(
            reference_partitions=["validation"]), "evaluated partition"),
        (lambda p: p["split"].update(kind="two_stage_stratified_holdout"), "stratify_by"),
    ],
)
def test_regression_contract_semantics(study, mutate, needle):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    assert any(needle in e for e in ssc.validate_contract_semantics(payload))


@pytest.mark.parametrize(
    "mutate, element",
    [
        (lambda p: p["cross_validation"].update(kind="stratified_k_fold"), "cross_validation.kind"),
        (lambda p: p["metrics"].update(evaluated=["mae", "macro_f1"]), "metrics.evaluated"),
        (lambda p: p["candidates"].append(_candidate("lr", "logistic_regression", {}, "standard", {"C": [1.0]}, 1)),
         "candidates[lr].family"),
    ],
)
def test_regression_protocol_support_gaps_are_explicit(study, mutate, element):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    assert element in {gap["element"] for gap in ssc.assess_protocol_support(payload)}


def test_group_overlap_diagnostic_is_unsupported_for_classification():
    payload = json.loads((REPO_ROOT / "pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/"
                          "scientific-study-contract.json").read_text(encoding="utf-8"))
    payload.setdefault("interpretive_evidence", {})["group_overlap_diagnostic"] = {
        "kind": "non_destructive_group_overlap_diagnostic"}
    assert "interpretive_evidence.group_overlap_diagnostic" in {
        g["element"] for g in ssc.assess_protocol_support(payload)}


# --------------------------------------------------------------------------
# backward compatibility of historical contracts and reports
# --------------------------------------------------------------------------


HISTORICAL = sorted(p.relative_to(REPO_ROOT).as_posix() for p in
                    list((REPO_ROOT / "pipeline/scientific-studies").rglob("scientific-study-contract.json"))
                    + list((REPO_ROOT / "pipeline/scientific-reproduction-runs").rglob("reproduction-report.json")))


@pytest.mark.parametrize("relative", [p for p in HISTORICAL if "concrete" not in p])
def test_historical_contracts_and_reports_keep_their_version_and_validate(relative):
    payload = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    if relative.endswith("scientific-study-contract.json"):
        assert payload["schema_version"] in ("scientific-study-contract.v1", "scientific-study-contract.v2")
        assert ssc.validate_contract_schema(payload) == []
        assert ssc.validate_contract_semantics(payload) == []
        assert ssc.assess_protocol_support(payload) == []
    else:
        assert payload["schema_version"] in ("scientific-reproduction-report.v1", "scientific-reproduction-report.v2")
        assert sr.validate_report_schema(payload) == []


@pytest.mark.parametrize("relative", [p for p in HISTORICAL if "concrete" not in p])
def test_historical_scientific_artifacts_are_byte_intact(relative):
    """Committed contracts/reports are write-once: the working tree equals the committed blob."""
    committed = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"HEAD:{relative}"],
                               capture_output=True, check=False)
    if committed.returncode != 0:
        pytest.skip("not committed yet")
    assert (REPO_ROOT / relative).read_bytes() == committed.stdout


# --------------------------------------------------------------------------
# metric identity and model families
# --------------------------------------------------------------------------


def test_medae_is_a_canonical_regression_identity():
    identity = metric_identity.resolve_scientific_metric("medae")
    assert identity.metric_id == "medae"
    assert identity.direction == metric_identity.LOWER_IS_BETTER
    assert identity.problem_types == {"continuous_regression"}
    assert identity.sklearn_scorer == "neg_median_absolute_error"
    assert identity.display_label == "MedAE"
    # Scientific only: native training and the public projection are not widened.
    assert identity.training_aliases == () and identity.public_key is None
    with pytest.raises(metric_identity.MetricIdentityError):
        metric_identity.resolve_training_metric("medae")


def test_regression_scorers_are_derived_from_the_registry():
    assert sr.REGRESSION_CV_SCORERS == {
        "mae": ("neg_mae", "neg_mean_absolute_error"),
        "rmse": ("neg_rmse", "neg_root_mean_squared_error"),
        "r2": ("r2", "r2"),
        "medae": ("neg_medae", "neg_median_absolute_error"),
    }
    for metric in ("mae", "rmse", "medae"):
        assert sr.metric_direction(metric) == "min"
    assert sr.metric_direction("r2") == "max"


def test_ridge_family_is_regression_only_and_scientific_only():
    family = model_families.get_family("ridge")
    assert family.estimators == {model_families.REGRESSION: "sklearn.linear_model.Ridge"}
    assert family.scale_sensitive
    estimator = model_families.build_estimator("ridge", model_families.REGRESSION, {"alpha": 10.0})
    assert type(estimator).__name__ == "Ridge" and estimator.alpha == 10.0
    with pytest.raises(model_families.ModelFamilyError):
        model_families.build_estimator("ridge", model_families.CLASSIFICATION, {})
    for problem_type in model_families.TABULAR_PROBLEM_TYPES:
        assert "ridge" not in model_families.native_trainable_family_ids(problem_type)
        assert "ridge" not in model_families.governed_result_family_ids(problem_type)


def test_dummy_prior_resolves_a_median_regressor_only_through_the_declared_strategy():
    regressor = model_families.build_estimator("dummy_prior", model_families.REGRESSION, {"strategy": "median"})
    assert type(regressor).__name__ == "DummyRegressor" and regressor.strategy == "median"
    classifier = model_families.build_estimator("dummy_prior", model_families.CLASSIFICATION, {"strategy": "prior"})
    assert type(classifier).__name__ == "DummyClassifier"
    # The family never implies a strategy: sklearn's regressor default is "mean".
    assert model_families.build_estimator("dummy_prior", model_families.REGRESSION).strategy == "mean"
    assert model_families.MODEL_FAMILIES["dummy_prior"].baseline_only


@pytest.mark.parametrize("family, name", [("decision_tree", "DecisionTreeRegressor"),
                                          ("random_forest", "RandomForestRegressor"),
                                          ("hist_gradient_boosting", "HistGradientBoostingRegressor")])
def test_tree_families_resolve_regressors(family, name):
    assert type(model_families.build_estimator(family, model_families.REGRESSION, {"random_state": 42})).__name__ == name


def test_ridge_scaling_lives_inside_the_pipeline(study):
    payload = study["payload"]
    ridge = next(c for c in payload["candidates"] if c["model_id"] == "ridge")
    tree = next(c for c in payload["candidates"] if c["model_id"] == "decision_tree")
    pipeline = sr.build_candidate_pipeline(ridge, payload, model_families.REGRESSION)
    numerical = pipeline.named_steps["preprocess"].transformers[0]
    assert type(numerical[1]).__name__ == "StandardScaler" and not hasattr(numerical[1], "mean_")
    assert numerical[2] == FEATURES
    assert sr.build_candidate_pipeline(tree, payload, model_families.REGRESSION).named_steps[
        "preprocess"].transformers[0][1] == "passthrough"


# --------------------------------------------------------------------------
# task adapter and metrics
# --------------------------------------------------------------------------


def _task(payload):
    return sr.task_adapter(payload)


def test_task_dispatch_is_by_problem_type(study):
    assert isinstance(_task(study["payload"]), sr.ContinuousRegressionTask)
    assert sr.TASK_ADAPTERS[ssc.REGRESSION] is sr.ContinuousRegressionTask


@pytest.mark.parametrize("values", [["1.0", "x"], [1.0, float("nan")], [1.0, float("inf")], [True, False]])
def test_regression_target_must_be_numeric_complete_and_finite(study, values):
    import pandas as pd

    with pytest.raises(sr.ScientificReproductionError):
        _task(study["payload"]).labels(pd.DataFrame({"y": values}), "y")


def test_regression_target_is_float(study):
    import pandas as pd

    labels = _task(study["payload"]).labels(pd.DataFrame({"y": [1, 2, 3]}), "y")
    assert str(labels.dtype) == "float64"


def test_regression_metrics_match_definitions():
    from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error, r2_score

    truth = np.array([3.0, 5.0, 2.5, 7.0, 4.0])
    predicted = np.array([2.5, 5.0, 4.0, 8.0, 3.0])
    metrics = sr.regression_metrics(truth, predicted)
    residuals = truth - predicted
    assert metrics["mae"] == pytest.approx(mean_absolute_error(truth, predicted))
    assert metrics["rmse"] == pytest.approx(mean_squared_error(truth, predicted) ** 0.5)
    assert metrics["r2"] == pytest.approx(r2_score(truth, predicted))
    assert metrics["medae"] == pytest.approx(median_absolute_error(truth, predicted)) == 1.0
    assert metrics["residual_mean"] == pytest.approx(residuals.mean())
    assert metrics["residual_standard_deviation"] == pytest.approx(residuals.std(ddof=1))
    assert metrics["max_absolute_error"] == 1.5
    assert metrics["absolute_error_p90"] == pytest.approx(np.quantile(np.abs(residuals), 0.9))
    assert metrics["row_count"] == 5
    with pytest.raises(sr.ScientificReproductionError):
        sr.regression_metrics([1.0, 2.0], [1.0])


def test_regression_has_no_threshold_positive_class_or_class_order(study):
    task = _task(study["payload"])
    assert task.validation_threshold() == {"applicable": False, "reason": sr.CONTINUOUS_NOT_APPLICABLE_REASON}
    assert task.class_order_evidence() is None
    section = task.thresholds_section(None)
    assert section["applicable"] is False
    assert section["positive_class"]["applicable"] is False and section["class_order"]["applicable"] is False
    assert section["scientific_policy"]["rule"]["applicable"] is False


# --------------------------------------------------------------------------
# split and cross-validation
# --------------------------------------------------------------------------


def _prepared(study):
    return sr.load_dataset(study["dataset"], study["payload"]["dataset_identity"])


def test_two_stage_random_holdout_equals_two_sklearn_stages(study):
    from sklearn.model_selection import train_test_split

    frame = _prepared(study)
    split = study["payload"]["split"]
    partitions, keys = sr._SPLITTERS["two_stage_random_holdout"](frame, split, [])
    positions = list(range(len(frame)))
    train, temporary = train_test_split(positions, test_size=0.30, random_state=42, shuffle=True, stratify=None)
    validation, test = train_test_split(temporary, test_size=0.15 / 0.30, random_state=43, shuffle=True, stratify=None)
    for name, expected in (("train", train), ("validation", validation), ("test", test)):
        assert list(partitions[name].index) == sorted(expected)  # source order preserved
        assert len(keys[name]) == len(expected)
    assert sum(len(p) for p in partitions.values()) == len(frame)


def test_random_holdout_never_reads_the_target(study):
    frame = _prepared(study)
    shuffled = frame.copy()
    shuffled[TARGET] = shuffled[TARGET].sample(frac=1.0, random_state=0).to_numpy()
    split = study["payload"]["split"]
    first = sr._SPLITTERS["two_stage_random_holdout"](frame, split, [])[0]
    second = sr._SPLITTERS["two_stage_random_holdout"](shuffled, split, [])[0]
    assert all(list(first[n].index) == list(second[n].index) for n in first)


def test_split_seed_semantics(study):
    frame = _prepared(study)
    split = copy.deepcopy(study["payload"]["split"])
    base = sr._SPLITTERS["two_stage_random_holdout"](frame, split, [])[0]
    split["seeds"]["validation_vs_test"] = 44
    moved = sr._SPLITTERS["two_stage_random_holdout"](frame, split, [])[0]
    assert list(base["train"].index) == list(moved["train"].index)  # stage 2 seed never moves train
    assert list(base["test"].index) != list(moved["test"].index)


def test_random_holdout_refuses_stratification(study):
    split = dict(study["payload"]["split"], stratify_by=TARGET)
    with pytest.raises(sr.ScientificReproductionError):
        sr._SPLITTERS["two_stage_random_holdout"](_prepared(study), split, [])


def test_membership_fingerprints_follow_source_position_tokens(study):
    frame = _prepared(study)
    partitions, keys = sr._SPLITTERS["two_stage_random_holdout"](frame, study["payload"]["split"], [])
    tokens = sr.row_occurrence_membership_keys(frame)
    for name, part in partitions.items():
        assert keys[name] == [tokens[i] for i in part.index]
        assert sr.membership_digest(keys[name], "source_position") == hashlib.sha256(
            "\n".join(tokens[i] for i in part.index).encode()).hexdigest()
    assert len(set(tokens)) == len(tokens)  # the repeated row gets a distinct occurrence ordinal


def test_k_fold_cross_validator():
    folds = sr._cross_validator({"kind": "k_fold", "n_splits": 5, "shuffle": True, "random_state": 42})
    assert type(folds).__name__ == "KFold"
    assert (folds.n_splits, folds.shuffle, folds.random_state) == (5, True, 42)
    assert type(sr._cross_validator({"kind": "stratified_k_fold", "n_splits": 3, "shuffle": True,
                                     "random_state": 1})).__name__ == "StratifiedKFold"


# --------------------------------------------------------------------------
# selection rule on a lower-is-better metric
# --------------------------------------------------------------------------


def _record(model_id, mae, rmse=5.0, medae=3.0, cv_std=0.3, r2=0.8):
    return {"model_id": model_id, "validation_mae": mae, "validation_rmse": rmse, "validation_medae": medae,
            "cv_mae_std": cv_std, "validation_r2": r2}


def _select(records, baseline=10.0, study_payload=None):
    rule = _contract("0" * 64, 1, 1)["selection"]
    return sr.select_leader_anchored_practical_tie(records, baseline, rule)


def test_lowest_mae_leads_without_tie():
    outcome = _select([_record("b", 3.0), _record("a", 2.0)])
    assert outcome["selected_model_id"] == "a" and outcome["practical_tie"] is False
    assert outcome["deciding_criterion"] == "lowest_validation_metric"


def test_eligibility_requires_strict_improvement_over_baseline():
    outcome = _select([_record("equal", 10.0), _record("worse", 11.0), _record("better", 9.99)])
    assert outcome["eligible_model_ids"] == ["better"]
    assert _select([_record("equal", 10.0)])["outcome"] == "no_eligible_candidate"


def test_absolute_difference_bound_keeps_the_historical_float_semantics():
    rule = copy.deepcopy(_contract("0" * 64, 1, 1)["selection"])
    rule["practical_tie"].pop("bound")
    outcome = sr.select_leader_anchored_practical_tie([_record("a", 2.0), _record("b", 2.10)], 10.0, rule)
    assert outcome["practical_tie_group"] == ["a"]  # abs(2.10 - 2.0) == 0.10000000000000009 > 0.10


def test_practical_tie_tolerance_is_inclusive_and_leader_anchored():
    inside = _select([_record("a", 2.0, rmse=5.0), _record("b", 2.10, rmse=4.0), _record("c", 2.1001, rmse=1.0)])
    assert inside["practical_tie_group"] == ["a", "b"]
    assert inside["selected_model_id"] == "b"
    assert inside["deciding_criterion"] == "lower_validation_rmse"


@pytest.mark.parametrize(
    "records, winner, criterion",
    [
        ([_record("a", 2.0, medae=2.0), _record("b", 2.05, medae=1.0)], "b", "lower_validation_medae"),
        ([_record("a", 2.0, cv_std=0.5), _record("b", 2.05, cv_std=0.2)], "b", "lower_cv_mae_std"),
        ([_record("a", 2.0, r2=0.7), _record("b", 2.05, r2=0.9)], "b", "higher_validation_r2"),
        ([_record("b", 2.0), _record("a", 2.05)], "a", "stable_model_id"),
    ],
)
def test_ordered_tie_breakers(records, winner, criterion):
    outcome = _select(records)
    assert outcome["selected_model_id"] == winner and outcome["deciding_criterion"] == criterion


# --------------------------------------------------------------------------
# full synthetic run
# --------------------------------------------------------------------------


def test_full_run_executes_every_family_and_reports_v3(run):
    result, report = run["result"], run["report"]
    assert result.executed, result.execution_notes
    assert report["schema_version"] == "scientific-reproduction-report.v3"
    assert sr.validate_report_schema(report) == []
    assert result.candidate_models_executed == ["ridge", "decision_tree", "random_forest", "hist_gradient_boosting"]
    assert {m: s["candidate_count_executed"] for m, s in result.actuals["search"].items()} == {
        "ridge": 2, "decision_tree": 4, "random_forest": 2, "hist_gradient_boosting": 1}
    assert report["reproduction_status"]["status"] == "reproduced_within_tolerance"


def test_scientific_values_are_in_natural_orientation(run):
    for row in run["report"]["family_search"]:
        assert row["best_score"]["metric"] == "mae" and row["best_score"]["value"] > 0
        assert row["cv_metrics"]["mae_mean"] > 0 and "neg_mae_mean" not in row["cv_metrics"]
        assert row["cv_metrics"]["mae_mean"] == pytest.approx(row["best_score"]["value"])
    for metric_set in run["report"]["metric_sets"]:
        assert not any(key.startswith("neg_") for key in metric_set["metrics"])


def test_comparable_evidence_keeps_pipeline_names_eligibility_and_effective_parameters(run):
    actuals = run["result"].actuals
    for model_id, search in actuals["search"].items():
        assert search["pipeline_best_params"] == {f"model__{k}": v for k, v in search["best_params"].items()}
    selection = actuals["selection"]
    assert selection["selected_pipeline_params"] == actuals["search"][selection["selected_model_id"]]["pipeline_best_params"]
    assert selection["eligibility"] == {m: m in selection["eligible_model_ids"] for m in actuals["validation"]}
    effective = actuals["final_fit"]["estimator_effective_parameters"]
    assert all(value is not None for value in effective.values())
    for name, value in selection["selected_best_params"].items():
        assert effective[name] == value


def test_search_refits_on_the_best_cv_mae(run):
    table = run["result"].search_results["decision_tree"]
    best = min(table, key=lambda row: (row["mean_mae"], row["candidate_index"]))
    assert run["result"].actuals["search"]["decision_tree"]["best_params"] == best["params"]


def test_cross_validation_uses_only_the_training_partition(run):
    report = run["report"]
    train_rows = report["split"]["observed"]["train"]["rows"]
    for row in report["family_search"]:
        assert row["fit_partition"] == "train"
    cv_sets = [m for m in report["metric_sets"] if m["provenance"]["metric_scope"] == "family_search_cv"]
    assert cv_sets and all(m["provenance"]["partition"] == "train_cross_validation" for m in cv_sets)
    assert all(m["provenance"]["partition_membership_sha256"] == report["split"]["observed"]["train"]["membership_sha256"]
               for m in cv_sets)
    assert train_rows == run["payload"]["expected_evidence"]["values"][0]["expected"]


def test_selection_follows_the_declared_rule(run):
    actuals = run["result"].actuals
    validation = actuals["validation"]
    baseline = actuals["baseline"]["validation"]["mae"]
    eligible = sorted((m for m, v in validation.items() if v["mae"] < baseline), key=lambda m: validation[m]["mae"])
    assert actuals["selection"]["eligible_model_ids"] == eligible
    leader = eligible[0]
    group = [m for m in eligible if validation[m]["mae"] <= validation[leader]["mae"] + 0.10]
    assert actuals["selection"]["practical_tie_group"][0] == leader
    assert set(actuals["selection"]["practical_tie_group"]) == set(group)


def test_final_fit_uses_train_plus_validation_and_test_is_evaluated_once(run):
    report, actuals = run["report"], run["result"].actuals
    observed = report["split"]["observed"]
    assert report["final_fit"]["partitions"] == ["train", "validation"]
    assert report["final_fit"]["rows"] == observed["train"]["rows"] + observed["validation"]["rows"]
    assert actuals["final_test"]["evaluation_count"] == 1 and actuals["final_test"]["prediction_call_count"] == 1
    assert actuals["final_test"]["row_count"] == observed["test"]["rows"]
    finals = [m for m in report["metric_sets"] if m["provenance"]["metric_scope"] == "scientific_final_test"]
    assert len(finals) == 1 and finals[0]["provenance"]["fit_partitions"] == ["train", "validation"]


def test_test_partition_is_predicted_exactly_once(study, monkeypatch):
    contract = study["write"](study["payload"])
    reproduction = sr.build_reproduction(contract, repo_root=study["root"], runtime=RUNTIME)
    test_rows: list[int] = []
    original = sr.ContinuousRegressionTask.evaluate

    def counting(self, estimator, x, y):
        test_rows.append(len(x))
        return original(self, estimator, x, y)

    monkeypatch.setattr(sr.ContinuousRegressionTask, "evaluate", counting)
    result = reproduction.run(run_id="repro-count", n_jobs=1)
    n_test = result.actuals["partitions"]["test"]["rows"]
    n_validation = result.actuals["partitions"]["validation"]["rows"]
    # baseline + 4 candidates on validation, then exactly one test evaluation
    assert test_rows == [n_validation] * 5 + [n_test]


def test_regression_report_records_class_concepts_as_not_applicable(run):
    report = run["report"]
    problem = report["problem"]
    assert problem["problem_type"] == "continuous_regression"
    assert problem["classes"] is None and problem["class_order"] is None
    assert problem["positive_class"]["applicable"] is False
    assert problem["decision_rule"] == {"kind": "continuous_point_prediction"}
    assert report["thresholds"]["applicable"] is False
    for metric_set in report["metric_sets"]:
        provenance = metric_set["provenance"]
        assert provenance["class_order"] is None
        if provenance["partition"] in ("validation", "test"):
            assert provenance["threshold"]["applicable"] is False
    assert "class_counts" not in report["split"]["observed"]["train"]
    assert report["split"]["observed"]["train"]["target_summary"]["diagnostic_only"] is True


def test_group_overlap_diagnostic_is_descriptive_only(run, study):
    report = run["report"]
    diagnostics = report["interpretive_diagnostics"]
    assert diagnostics["diagnostic_only"] is True and diagnostics["used_for_selection"] is False
    assert diagnostics["executed_after"] == "final_test_evaluation"
    by_partition = {e["evaluated_partition"]: e for e in diagnostics["evaluations"]}
    observed = report["split"]["observed"]
    for name in ("validation", "test"):
        evaluation = by_partition[name]
        assert evaluation["seen_group_row_count"] + evaluation["unseen_group_row_count"] == observed[name]["rows"]
    assert by_partition["test"]["reference_partitions"] == ["train", "validation"]
    # The test "full" subset re-describes the single test prediction.
    assert by_partition["test"]["full"]["metrics"]["mae"] == run["result"].actuals["final_test"]["metrics"]["mae"]
    selected = run["result"].actuals["selection"]["selected_model_id"]
    assert by_partition["validation"]["full"]["metrics"]["mae"] == run["result"].actuals["validation"][selected]["mae"]

    # Removing the diagnostic changes nothing upstream of it.
    payload = copy.deepcopy(study["payload"])
    payload.pop("interpretive_evidence")
    other = sr.build_reproduction(study["write"](payload), repo_root=study["root"], runtime=RUNTIME).run(
        run_id="repro-no-diag", n_jobs=1)
    def timing_free(value):
        if isinstance(value, dict):
            return {k: timing_free(v) for k, v in value.items() if k != "search_duration_seconds"}
        return value

    for key in ("partitions", "search", "validation", "selection", "final_fit", "final_test"):
        assert json.dumps(timing_free(sr._jsonable(other.actuals[key])), sort_keys=True) == json.dumps(
            timing_free(sr._jsonable(run["result"].actuals[key])), sort_keys=True), key
    assert other.build_report()["interpretive_diagnostics"] is None


def test_expected_evidence_comparison_on_regression_quantities(run):
    actuals = run["result"].actuals
    selected = actuals["selection"]["selected_model_id"]
    mae = actuals["final_test"]["metrics"]["mae"]
    source = {"path": "x", "locator": "file_text", "rendered_text": "x"}
    evidence = {"values": [
        {"quantity": "final_test.metrics.mae", "expected": mae, "comparison": "numeric", "source": source},
        {"quantity": "final_test.metrics.rmse", "expected": round(actuals["final_test"]["metrics"]["rmse"], 4),
         "comparison": "numeric", "reported_decimal_places": 4, "source": source},
        {"quantity": "final_test.metrics.r2", "expected": actuals["final_test"]["metrics"]["r2"] + 1e-7,
         "comparison": "numeric", "source": source},
        {"quantity": "final_test.metrics.medae", "expected": 0.0, "comparison": "numeric", "source": source},
        {"quantity": "final_test.metrics.no_such_metric", "expected": 1.0, "comparison": "numeric", "source": source},
    ], "decisions": [
        {"quantity": "selection.selected_model_id", "expected": selected, "comparison": "exact", "source": source},
    ]}
    comparison = sr.compare_with_expected_evidence(evidence, actuals, {"numeric_absolute": 1e-6, "count_absolute": 0})
    outcomes = [c["outcome"] for c in comparison["values"] + comparison["decisions"]]
    assert outcomes == [sr.OUTCOME_EXACT, sr.OUTCOME_EXACT, sr.OUTCOME_WITHIN, sr.OUTCOME_OUTSIDE,
                        sr.OUTCOME_MISSING, sr.OUTCOME_EXACT]


def test_environment_classification_is_independent_of_scientific_agreement(study):
    reference = {"python": "3.12.13", "platform": "linux-aarch64",
                 "core_packages": {"scikit-learn": "1.9.0", "pandas": "3.0.3"},
                 "compatibility_policy": {"python": "same_minor", "core_packages": "same_minor",
                                          "platform": "difference_is_compatible"}}
    same = {"python": "3.12.13", "platform": "linux-aarch64", "core_packages": {"scikit-learn": "1.9.0", "pandas": "3.0.3"}}
    assert env.classify_environment(reference, same)["classification"] == env.EXACT
    other_arch = dict(same, platform="linux-x86_64")
    assert env.classify_environment(reference, other_arch)["classification"] == env.COMPATIBLE
    other_minor = dict(same, python="3.13.1")
    assert env.classify_environment(reference, other_minor)["classification"] == env.INCOMPATIBLE
    missing = dict(same, core_packages={"scikit-learn": "1.9.0"})
    assert env.classify_environment(reference, missing)["classification"] == env.INCOMPATIBLE
    assert env.classify_environment({}, same)["classification"] == env.UNKNOWN


def test_dataset_identity_is_fail_closed(study):
    payload = copy.deepcopy(study["payload"])
    study["dataset"].write_bytes(study["dataset"].read_bytes().replace(b"\n", b"\r\n", 1))
    result = sr.build_reproduction(study["write"](payload), repo_root=study["root"], runtime=RUNTIME).run(
        run_id="repro-bytes", n_jobs=1)
    assert result.executed is False
    report = result.build_report()
    assert report["reproduction_status"]["status"] == sr.STATUS_DATASET_MISMATCH
    assert sr.validate_report_schema(report) == []


def test_report_is_write_once_and_answers_regression_questions(run, tmp_path):
    written = sr.write_reproduction_report(run["report"], repo_root=tmp_path, search_results=run["result"].search_results)
    with pytest.raises(sr.ScientificReproductionError):
        sr.write_reproduction_report(run["report"], repo_root=tmp_path)
    stored = json.loads((tmp_path / written["report_path"]).read_text(encoding="utf-8"))
    answers = sr.answer_reproduction_questions(stored)
    assert answers["problem_type"] == "continuous_regression"
    assert answers["threshold"] == {"applicable": False, "reason": sr.CONTINUOUS_NOT_APPLICABLE_REASON}
    assert answers["were_diagnostics_used_for_selection"] is False
    assert answers["final_fit_partitions_and_rows"]["partitions"] == ["train", "validation"]
    assert {d["evaluated_partition"] for d in answers["which_diagnostics_were_reproduced"]} == {"validation", "test"}


def test_lineage_separation_marks_regression_metrics_not_comparable(run, tmp_path):
    report = copy.deepcopy(run["report"])
    slug = report["run_identity"]["dataset_slug"]
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/datasets.json").write_text(json.dumps(
        {"datasets": [{"dataset_slug": slug, "active_release": "release-x"}]}), encoding="utf-8")
    (tmp_path / f"contracts/{slug}").mkdir(parents=True)
    (tmp_path / f"contracts/{slug}/execution-contract.json").write_text(json.dumps(
        {"split_policy": {"strategy": "random"}, "random_seed": 42, "primary_metric": "mae",
         "result_semantics": {}, "modeling_constraints": {"selection_mode": "fixed_configuration"}}), encoding="utf-8")
    (tmp_path / "releases/release-x/metrics").mkdir(parents=True)
    (tmp_path / "releases/release-x/metrics/metrics.json").write_text(json.dumps(
        {"training_run_identity": {"run_id": "train-x"},
         "final_test_evaluation": {"row_count": 99, "metrics": [{"name": "mae", "value": 1.0},
                                                                {"name": "rmse", "value": 2.0},
                                                                {"name": "r2", "value": 0.9}]}}), encoding="utf-8")
    view = sr.describe_lineage_separation(report, repo_root=tmp_path)
    assert {row["canonical_metric"] for row in view["rows"]} == {"mae", "rmse", "r2"}
    assert all(row["directly_comparable"] is False for row in view["rows"])
    assert all(row["scientific_reproduction"]["value"] is not None for row in view["rows"])
    facts = {d["fact"]: d for d in view["protocol_differences"]}
    assert facts["split"]["scientific_reproduction"].startswith("two_stage_random_holdout")
    assert facts["partition_membership"]["scientific_reproduction"]["test"]
    assert facts["decision_threshold"]["scientific_reproduction"]["applicable"] is False
    assert "neither replaces the other" in view["interpretation"]
    assert not (tmp_path / "releases/release-x/metrics").joinpath("other").exists()


# --------------------------------------------------------------------------
# dataset-agnostic engine guard
# --------------------------------------------------------------------------


GENERIC_MODULES = ["pipeline/scientific_reproduction.py", "pipeline/scientific_study_contract.py",
                   "pipeline/scientific_environment.py", "pipeline/model_families.py", "pipeline/metric_identity.py"]


@pytest.mark.parametrize("module", GENERIC_MODULES)
def test_generic_engine_has_no_dataset_specific_literals(module):
    text = (REPO_ROOT / module).read_text(encoding="utf-8").lower()
    for literal in ("concrete-compressive", "concrete compressive", "cement", "blast furnace", "fly ash", "superplasticizer", "coarse aggregate",
                    "fine aggregate", "telco", "dry-bean", "dry bean", "churn"):
        assert not re.search(rf"\b{re.escape(literal)}\b", text), f"{module} contains {literal!r}"
