"""Scientific Study Contract / scientific reproduction layer.

Most tests build a small synthetic study inside ``tmp_path`` so they run in
seconds and never depend on the real Telco dataset. The real Telco contract
and the committed reproduction report are checked structurally.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

import pytest

from pipeline import model_families, scientific_environment as env
from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc


REPO_ROOT = Path(__file__).resolve().parents[2]
TELCO_CONTRACT = (
    REPO_ROOT / "pipeline/scientific-studies/telco-customer-churn/study-43ced1fbb76f/scientific-study-contract.json"
)
TELCO_RUNS = REPO_ROOT / "pipeline/scientific-reproduction-runs/telco-customer-churn"
REVISION = "0123456789abcdef0123456789abcdef01234567"
LABEL = f"study-{REVISION[:12]}"


# --------------------------------------------------------------------------
# synthetic study fixture
# --------------------------------------------------------------------------


def _synthetic_csv(path: Path, rows: int = 320) -> None:
    rng = random.Random(7)
    lines = ["account_id,segment,plan,usage,months,total,Outcome"]
    for index in range(rows):
        segment = rng.choice(["a", "b", "c"])
        plan = rng.choice(["basic", "plus"])
        usage = round(rng.uniform(0, 100), 2)
        months = 0 if index % 40 == 0 else rng.randint(1, 60)
        total = " " if months == 0 else f"{usage * months:.2f}"
        score = usage / 100 + (0.35 if segment == "a" else 0) + (0.2 if plan == "plus" else 0)
        outcome = "Yes" if score + rng.uniform(-0.35, 0.35) > 0.8 else "No"
        lines.append(f"acct-{index:04d},{segment},{plan},{usage},{months},{total},{outcome}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _contract(dataset_sha: str, size: int, rows: int = 320) -> dict:
    return {
        "schema_version": "scientific-study-contract.v1",
        "artifact_kind": "scientific_study_contract",
        "study_identity": {
            "study_id": "dataset-study-synthetic",
            "dataset_slug": "synthetic-study",
            "protocol_kind": "tabular_holdout_model_selection.v1",
            "study_revision_label": LABEL,
        },
        "source_repository": {
            "url": "https://example.invalid/dataset-study-synthetic",
            "revision": REVISION,
            "pinned_files": [{"path": "README.md", "sha256": "0" * 64, "role": "narrative"}],
        },
        "dataset_identity": {
            "file_name": "synthetic.csv",
            "sha256": dataset_sha,
            "size_bytes": size,
            "row_count": rows,
            "column_count": 7,
            "read_format": "csv",
            "read_options": {},
            "atlas_local_path": "data/scientific-studies/synthetic-study/synthetic.csv",
        },
        "scientific_environment": {
            "python": "3.13.0",
            "platform": None,
            "core_packages": {"scikit-learn": "1.9.1"},
            "lock": {"path": "pylock.toml", "sha256": "1" * 64, "format": "pep751"},
            "compatibility_policy": {"python": "same_major", "core_packages": "same_major"},
        },
        "problem": {
            "problem_type": "binary_classification",
            "target": {"column": "Outcome", "classes": ["No", "Yes"], "positive_class": "Yes",
                       "encoding": {"No": 0, "Yes": 1}},
            "identifier_columns": ["account_id"],
        },
        "features": {
            "feature_columns": ["segment", "plan", "usage", "months", "total"],
            "numerical": ["usage", "months", "total"],
            "categorical": ["segment", "plan"],
        },
        "preparation": {
            "rules": [{"rule_id": "fill-total", "kind": "conditional_blank_numeric_fill", "column": "total",
                       "condition_column": "months", "condition_value": 0, "replacement": 0.0,
                       "strip_strings": True}],
            "row_removal": "none",
        },
        "split": {"kind": "two_stage_stratified_holdout", "order_by_identifier": True,
                  "fractions": {"train": 0.6, "validation": 0.2, "test": 0.2}, "stratify_by": "Outcome",
                  "shuffle": True, "seeds": {"train_vs_temporary": 3, "validation_vs_test": 4},
                  "partition_handoff": "csv_roundtrip"},
        "preprocessing": {"kind": "column_transformer_onehot_plus_numeric",
                          "categorical": {"handle_unknown": "ignore", "drop": None, "dense": True}},
        "cross_validation": {"kind": "stratified_k_fold", "n_splits": 3, "shuffle": True, "random_state": 5},
        "metrics": {"primary": "average_precision", "refit": "average_precision",
                    "evaluated": ["average_precision", "roc_auc", "brier_score", "log_loss", "f1"],
                    "default_threshold": 0.5},
        "baseline": {"model_id": "dummy_prior", "family": "dummy_prior", "fixed_params": {"strategy": "prior"},
                     "numerical_scaling": "passthrough", "search": {"kind": "none"}},
        "candidates": [
            {"model_id": "logistic_regression", "family": "logistic_regression",
             "fixed_params": {"solver": "liblinear", "random_state": 1}, "numerical_scaling": "standard",
             "search": {"kind": "grid", "space": {"C": [0.1, 1.0]}}},
            {"model_id": "random_forest", "family": "random_forest",
             "fixed_params": {"random_state": 1, "n_estimators": 25}, "numerical_scaling": "passthrough",
             "search": {"kind": "randomized", "n_iter": 2, "random_state": 1,
                        "space": {"max_depth": [3, 5, None]}}},
        ],
        "search_execution": {"n_jobs": 1},
        "selection": {
            "kind": "leader_anchored_practical_tie",
            "eligibility": {"metric": "average_precision", "margin": 0.01, "strict": True},
            "leader": {"metric": "average_precision"},
            "practical_tie": {"metric": "average_precision", "tolerance": 0.01, "cv_interval_z": 1.96},
            "tie_breakers": [
                {"criterion": "lower_validation_brier_score", "field": "validation_brier_score", "direction": "min"},
                {"criterion": "stable_model_id", "field": "model_id", "direction": "min"},
            ],
            "simplicity_order": ["logistic_regression", "random_forest"],
        },
        "threshold_policy": {"kind": "max_precision_subject_to_min_recall", "partition": "validation",
                             "min_recall": 0.6, "ordering": ["precision", "f2", "threshold"]},
        "final_evaluation": {"kind": "refit_on_train_plus_validation_single_test_evaluation"},
        "tolerance_policy": {"numeric_absolute": 0.0001, "count_absolute": 0, "rationale": "synthetic"},
        "expected_evidence": {
            "values": [
                {"quantity": "partitions.train.rows", "expected": 192, "comparison": "count",
                 "source": {"path": "README.md", "locator": "file_text", "rendered_text": "192"}},
            ],
            "decisions": [],
        },
        "evidence_gaps": [],
        "limitations": ["synthetic"],
        "authoring": {"authored_by": "test", "authored_at": "2026-01-01T00:00:00Z", "method": "fixture"},
    }


@pytest.fixture()
def synthetic(tmp_path: Path):
    dataset = tmp_path / "data/scientific-studies/synthetic-study/synthetic.csv"
    dataset.parent.mkdir(parents=True)
    _synthetic_csv(dataset)
    payload = _contract(hashlib.sha256(dataset.read_bytes()).hexdigest(), dataset.stat().st_size)
    contract_path = tmp_path / ssc.STUDIES_ROOT_RELATIVE / "synthetic-study" / LABEL / ssc.CONTRACT_FILENAME

    def write(data: dict) -> ssc.ScientificStudyContract:
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(json.dumps(data), encoding="utf-8")
        return ssc.load_scientific_study_contract(contract_path, repo_root=tmp_path)

    runtime = {"python": "3.13.1", "platform": "linux-x86_64", "core_packages": {"scikit-learn": "1.9.1"}}
    return {"root": tmp_path, "payload": payload, "write": write, "runtime": runtime, "dataset": dataset}


def _run(synthetic, payload=None, **run_kwargs):
    contract = synthetic["write"](payload or synthetic["payload"])
    reproduction = sr.build_reproduction(contract, repo_root=synthetic["root"], runtime=synthetic["runtime"])
    return reproduction.run(run_id="repro-test", n_jobs=1, **run_kwargs)


# --------------------------------------------------------------------------
# model-family registry
# --------------------------------------------------------------------------


def test_registry_resolves_every_family_needed_by_the_telco_study():
    for family in ("dummy_prior", "logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting"):
        assert model_families.get_family(family).supports(model_families.CLASSIFICATION)
    assert model_families.estimator_class("random_forest", "classification").__name__ == "RandomForestClassifier"
    assert model_families.family_for_estimator_class("HistGradientBoostingClassifier") == "hist_gradient_boosting"


def test_registry_covers_every_native_training_family():
    from pipeline import training

    for family in training.SUPPORTED_MODEL_FAMILIES:
        assert family in model_families.MODEL_FAMILIES


def test_registry_rejects_unknown_family_task_and_hyperparameter():
    with pytest.raises(model_families.ModelFamilyError) as unknown:
        model_families.get_family("xgboost")
    assert unknown.value.code == "unsupported_model_family"
    with pytest.raises(model_families.ModelFamilyError) as task:
        model_families.estimator_class("logistic_regression", model_families.REGRESSION)
    assert task.value.code == "unsupported_task_type"
    with pytest.raises(model_families.ModelFamilyError) as param:
        model_families.build_estimator("random_forest", "classification", {"not_a_param": 1})
    assert param.value.code == "unsupported_hyperparameter"


def test_registry_builds_estimator_with_exactly_declared_params():
    estimator = model_families.build_estimator("random_forest", "classification", {"n_estimators": 7, "random_state": 3})
    assert estimator.n_estimators == 7 and estimator.random_state == 3


def test_native_training_estimator_arguments_are_unchanged():
    from pipeline import training

    lr = training._build_estimator("logistic_regression", "classification", 11).named_steps["model"]
    assert type(lr).__name__ == "LogisticRegression" and lr.max_iter == 1000 and lr.random_state == 11
    rf = training._build_estimator("random_forest", "regression", 5).named_steps["model"]
    assert type(rf).__name__ == "RandomForestRegressor" and rf.random_state == 5
    with pytest.raises(training.TrainingInputError):
        training._build_estimator("hist_gradient_boosting", "classification", 0)


# --------------------------------------------------------------------------
# contract schema and loading
# --------------------------------------------------------------------------


def test_real_telco_contract_is_schema_valid_and_fully_supported():
    contract = ssc.load_scientific_study_contract(TELCO_CONTRACT, repo_root=REPO_ROOT)
    assert contract.study_revision == "43ced1fbb76f55ad156e133ee421e756b1921df1"
    assert ssc.assess_protocol_support(contract.payload) == []
    families = {c["family"] for c in contract.payload["candidates"]}
    assert families == {"logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting"}


def test_contract_carries_no_absolute_or_dataset_specific_code_paths():
    text = TELCO_CONTRACT.read_text(encoding="utf-8")
    assert "/home/" not in text and "C:\\" not in text


def test_schema_rejects_missing_sections_and_absolute_paths(synthetic):
    broken = copy.deepcopy(synthetic["payload"])
    del broken["selection"]
    assert any("selection" in error for error in ssc.validate_contract_schema(broken))
    absolute = copy.deepcopy(synthetic["payload"])
    absolute["source_repository"]["pinned_files"][0]["path"] = "/etc/passwd"
    assert ssc.validate_contract_schema(absolute)
    traversal = copy.deepcopy(synthetic["payload"])
    traversal["dataset_identity"]["atlas_local_path"] = "../outside.csv"
    assert ssc.validate_contract_schema(traversal)


def test_contract_location_must_match_its_identity(synthetic):
    wrong = copy.deepcopy(synthetic["payload"])
    wrong["study_identity"]["study_revision_label"] = "study-ffffffffffff"
    with pytest.raises(ssc.ScientificStudyContractError) as error:
        synthetic["write"](wrong)
    assert error.value.code == "contract_location_mismatch"


# --------------------------------------------------------------------------
# unsupported capability detection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, element",
    [
        (lambda p: p["candidates"][0].update(family="xgboost"), "candidates[logistic_regression].family"),
        (lambda p: p["candidates"][1]["search"].update(kind="bayesian"), "candidates[random_forest].search.kind"),
        (lambda p: p["candidates"][1]["search"]["space"].update(bogus=[1]), "candidates[random_forest].hyperparameter"),
        (lambda p: p["selection"].update(kind="pareto_front"), "selection.kind"),
        (lambda p: p["problem"].update(problem_type="univariate_forecasting"), "problem.problem_type"),
        (lambda p: p["threshold_policy"].update(kind="cost_sensitive"), "threshold_policy.kind"),
        (lambda p: p["metrics"]["evaluated"].append("mase"), "metrics.evaluated"),
    ],
)
def test_unsupported_protocol_elements_are_reported(synthetic, mutate, element):
    payload = copy.deepcopy(synthetic["payload"])
    mutate(payload)
    gaps = ssc.assess_protocol_support(payload)
    assert element in {gap["element"] for gap in gaps}


def test_unsupported_capability_blocks_execution_with_capability_missing_status(synthetic):
    payload = copy.deepcopy(synthetic["payload"])
    payload["candidates"][0]["family"] = "xgboost"
    result = _run(synthetic, payload)
    assert result.executed is False
    report = result.build_report()
    assert report["reproduction_status"]["status"] == sr.STATUS_CAPABILITY_MISSING
    assert report["candidate_models"]["executed"] == []


# --------------------------------------------------------------------------
# environment compatibility
# --------------------------------------------------------------------------


REFERENCE_ENV = {
    "python": "3.13.13",
    "platform": "linux-aarch64",
    "core_packages": {"scikit-learn": "1.9.1", "pandas": "3.0.6"},
    "compatibility_policy": {"python": "same_minor", "core_packages": "same_minor"},
}


def _runtime(python="3.13.13", platform="linux-aarch64", sklearn="1.9.1", pandas="3.0.6"):
    return {"python": python, "platform": platform, "core_packages": {"scikit-learn": sklearn, "pandas": pandas}}


@pytest.mark.parametrize(
    "runtime, expected",
    [
        (_runtime(), env.EXACT),
        (_runtime(python="3.13.12"), env.COMPATIBLE),
        (_runtime(platform="linux-x86_64"), env.COMPATIBLE),
        (_runtime(sklearn="1.9.0"), env.COMPATIBLE),
        (_runtime(sklearn="1.8.0"), env.INCOMPATIBLE),
        (_runtime(python="3.12.9"), env.INCOMPATIBLE),
        (_runtime(pandas=None), env.INCOMPATIBLE),
    ],
)
def test_environment_classification(runtime, expected):
    result = env.classify_environment(REFERENCE_ENV, runtime)
    assert result["classification"] == expected
    if expected != env.EXACT:
        assert result["differences"], "a difference must never be silently ignored"


def test_environment_without_evidence_is_unknown():
    assert env.classify_environment({}, _runtime())["classification"] == env.UNKNOWN


def test_platform_policy_can_declare_difference_incompatible():
    strict = {**REFERENCE_ENV, "compatibility_policy": {**REFERENCE_ENV["compatibility_policy"],
                                                         "platform": "difference_is_incompatible"}}
    assert env.classify_environment(strict, _runtime(platform="linux-x86_64"))["classification"] == env.INCOMPATIBLE


def test_pylock_core_pin_extraction(tmp_path):
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\n[[packages]]\nname = "scikit-learn"\nversion = "1.9.1"\n'
        '[[packages]]\nname = "Pandas"\nversion = "3.0.6"\n',
        encoding="utf-8",
    )
    assert env.extract_core_pins_from_pylock(lock, ["scikit-learn", "pandas"]) == {"scikit-learn": "1.9.1", "pandas": "3.0.6"}
    with pytest.raises(env.EnvironmentEvidenceError):
        env.extract_core_pins_from_pylock(lock, ["numpy"])


def test_incompatible_environment_is_not_executed_by_default(synthetic):
    synthetic["runtime"]["core_packages"]["scikit-learn"] = "0.24.2"
    result = _run(synthetic)
    assert result.executed is False
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_ENVIRONMENT_INCOMPATIBLE


# --------------------------------------------------------------------------
# comparison, tolerance, and status
# --------------------------------------------------------------------------


POLICY = {"numeric_absolute": 0.0001, "count_absolute": 0, "rationale": "t"}
SOURCE = {"path": "README.md", "locator": "file_text", "rendered_text": "x"}


def _item(quantity, expected, comparison="numeric", places=6):
    return {"quantity": quantity, "expected": expected, "comparison": comparison,
            "reported_decimal_places": places, "source": SOURCE}


@pytest.mark.parametrize(
    "expected, actual, outcome",
    [
        (0.641283, 0.64128312, sr.OUTCOME_EXACT),
        (0.641283, 0.64133, sr.OUTCOME_WITHIN),
        (0.641283, 0.6425, sr.OUTCOME_OUTSIDE),
    ],
)
def test_numeric_comparison_tiers(expected, actual, outcome):
    compared = sr.compare_item(_item("m.v", expected), {"m": {"v": actual}}, POLICY)
    assert compared["outcome"] == outcome
    assert compared["delta"] == pytest.approx(actual - expected)
    assert compared["tolerance"] == POLICY["numeric_absolute"]


def test_full_precision_values_use_the_declared_tolerance_only():
    compared = sr.compare_item(_item("t", 0.2577809673219062, places=None), {"t": 0.2577809673219062}, POLICY)
    assert compared["outcome"] == sr.OUTCOME_EXACT
    shifted = sr.compare_item(_item("t", 0.2577809673219062, places=None), {"t": 0.25779}, POLICY)
    assert shifted["outcome"] == sr.OUTCOME_WITHIN


def test_counts_and_decisions_require_exact_agreement():
    assert sr.compare_item(_item("c", 140, "count"), {"c": 141}, POLICY)["outcome"] == sr.OUTCOME_OUTSIDE
    assert sr.compare_item(_item("s", "hgb", "exact"), {"s": "rf"}, POLICY)["outcome"] == sr.OUTCOME_MISMATCH
    assert sr.compare_item(_item("s", ["a", "b"], "exact"), {"s": ["a", "b"]}, POLICY)["outcome"] == sr.OUTCOME_EXACT
    assert sr.compare_item(_item("absent", 1, "count"), {}, POLICY)["outcome"] == sr.OUTCOME_MISSING


def _comparison(*outcomes):
    items = [{"quantity": f"q{i}", "outcome": o} for i, o in enumerate(outcomes)]
    return {"values": items, "decisions": [],
            "all_exact_at_reported_precision": all(o == sr.OUTCOME_EXACT for o in outcomes)}


@pytest.mark.parametrize(
    "kwargs, status",
    [
        (dict(dataset_verified=False), sr.STATUS_DATASET_MISMATCH),
        (dict(protocol_gaps=[{"element": "e", "value": "v", "reason": "r"}]), sr.STATUS_CAPABILITY_MISSING),
        (dict(environment_classification=env.INCOMPATIBLE), sr.STATUS_ENVIRONMENT_INCOMPATIBLE),
        (dict(executed=False, comparison=None), sr.STATUS_INSUFFICIENT_EVIDENCE),
        (dict(comparison=_comparison(sr.OUTCOME_EXACT, sr.OUTCOME_OUTSIDE)), sr.STATUS_DIVERGENT),
        (dict(comparison=_comparison(sr.OUTCOME_MISMATCH)), sr.STATUS_DIVERGENT),
        (dict(comparison=_comparison(sr.OUTCOME_MISSING)), sr.STATUS_INSUFFICIENT_EVIDENCE),
        (dict(evidence_gaps=[{"gap_id": "g", "severity": "blocking", "description": "d"}]), sr.STATUS_INSUFFICIENT_EVIDENCE),
        (dict(), sr.STATUS_REPRODUCED_EXACT),
        (dict(environment_classification=env.COMPATIBLE), sr.STATUS_REPRODUCED_WITHIN_TOLERANCE),
        (dict(comparison=_comparison(sr.OUTCOME_WITHIN)), sr.STATUS_REPRODUCED_WITHIN_TOLERANCE),
    ],
)
def test_reproduction_status_calculation(kwargs, status):
    base = dict(protocol_gaps=[], environment_classification=env.EXACT, dataset_verified=True, executed=True,
                comparison=_comparison(sr.OUTCOME_EXACT), evidence_gaps=[])
    base.update(kwargs)
    assert sr.compute_reproduction_status(**base)["status"] == status


def test_divergence_outranks_evidence_gaps_and_is_never_masked():
    status = sr.compute_reproduction_status(
        protocol_gaps=[], environment_classification=env.COMPATIBLE, dataset_verified=True, executed=True,
        comparison=_comparison(sr.OUTCOME_OUTSIDE, sr.OUTCOME_MISSING),
        evidence_gaps=[{"gap_id": "g", "severity": "blocking", "description": "d"}],
    )
    assert status["status"] == sr.STATUS_DIVERGENT


# --------------------------------------------------------------------------
# selection and threshold rules
# --------------------------------------------------------------------------


def _record(model_id, ap, brier, lo, hi, std=0.01, rank=0):
    return {"model_id": model_id, "validation_average_precision": ap, "validation_brier_score": brier,
            "cv_average_precision_std": std, "cv_average_precision_ci_lower": lo,
            "cv_average_precision_ci_upper": hi, "simplicity_rank": rank}


RULE = {
    "eligibility": {"metric": "average_precision", "margin": 0.01, "strict": True},
    "leader": {"metric": "average_precision"},
    "practical_tie": {"metric": "average_precision", "tolerance": 0.01},
    "tie_breakers": [
        {"criterion": "lower_validation_brier_score", "field": "validation_brier_score", "direction": "min"},
        {"criterion": "stable_model_id", "field": "model_id", "direction": "min"},
    ],
}


def test_leader_anchored_multi_way_tie_is_resolved_by_ordered_breakers():
    records = [
        _record("hgb", 0.6708, 0.1332, 0.658, 0.686),
        _record("lr", 0.6688, 0.1339, 0.647, 0.670),
        _record("rf", 0.6679, 0.1593, 0.655, 0.676),
        _record("dt", 0.6134, 0.1461, 0.598, 0.639),
        _record("weak", 0.27, 0.19, 0.2, 0.3),
    ]
    selection = sr.select_leader_anchored_practical_tie(records, 0.265, RULE)
    assert selection["eligible_model_ids"] == ["hgb", "lr", "rf", "dt"]
    assert selection["practical_tie_group"] == ["hgb", "lr", "rf"]
    assert selection["selected_model_id"] == "hgb"
    assert selection["deciding_criterion"] == "lower_validation_brier_score"


def test_selection_without_tie_and_without_eligible_candidates():
    records = [_record("a", 0.70, 0.2, 0.69, 0.71), _record("b", 0.60, 0.1, 0.59, 0.61)]
    selection = sr.select_leader_anchored_practical_tie(records, 0.2, RULE)
    assert selection["practical_tie"] is False and selection["selected_model_id"] == "a"
    none = sr.select_leader_anchored_practical_tie(records, 0.695, RULE)
    assert none["selected_model_id"] is None and none["outcome"] == "no_eligible_candidate"


def test_threshold_policy_maximizes_precision_subject_to_min_recall():
    y = [0, 0, 1, 1, 1, 0, 1]
    p = [0.1, 0.4, 0.35, 0.8, 0.7, 0.2, 0.9]
    policy = {"min_recall": 0.75, "ordering": ["precision", "f2", "threshold"]}
    outcome = sr.threshold_max_precision_subject_to_min_recall(y, p, policy)
    assert outcome["satisfied"] and outcome["threshold"] == 0.7
    assert sr.threshold_max_precision_subject_to_min_recall(y, p, {**policy, "min_recall": 1.01})["satisfied"] is False


# --------------------------------------------------------------------------
# end-to-end synthetic reproduction: provenance, separation, immutability
# --------------------------------------------------------------------------


def test_end_to_end_reproduction_report_carries_provenance_and_lineage_separation(synthetic):
    result = _run(synthetic)
    assert result.executed
    report = result.build_report()
    assert sr.validate_report_schema(report) == []
    assert report["candidate_models"]["expected"] == report["candidate_models"]["executed"] == [
        "logistic_regression", "random_forest"]
    lineage = report["evidence_lineage"]
    assert lineage["atlas_native_training_run"]["referenced"] is False
    assert lineage["atlas_release"]["referenced"] is False
    for metric_set in report["metric_sets"]:
        provenance = metric_set["provenance"]
        assert provenance["producer_lineage"] == sr.RUN_KIND
        assert provenance["run_id"] == "repro-test"
        assert provenance["study_revision"] == REVISION
        assert provenance["dataset_sha256"] == synthetic["payload"]["dataset_identity"]["sha256"]
        assert provenance["partition_membership_sha256"] or provenance["partition"] == "train_cross_validation"
    thresholds = report["thresholds"]
    provenances = {thresholds[k]["provenance"] for k in thresholds}
    assert provenances == {"scientific_study_contract", sr.STUDY_RUN_KIND, sr.RUN_KIND, sr.NATIVE_TRAINING_RUN_KIND}
    assert thresholds["atlas_native_operational"]["value"] is None
    policy_set = next(m for m in report["metric_sets"] if m["metric_set_id"].endswith("at_policy_threshold"))
    assert policy_set["provenance"]["threshold"]["provenance"] == sr.RUN_KIND
    assert policy_set["provenance"]["threshold"]["rule"] == "max_precision_subject_to_min_recall"
    assert report["reproduction_status"]["status"] == sr.STATUS_REPRODUCED_WITHIN_TOLERANCE


def test_reference_values_are_never_copied_into_reproduced_results(synthetic):
    payload = copy.deepcopy(synthetic["payload"])
    payload["expected_evidence"]["values"].append(
        {"quantity": "final_test.probability.average_precision", "expected": 0.123456, "comparison": "numeric",
         "reported_decimal_places": 6, "source": SOURCE})
    report = _run(synthetic, payload).build_report()
    compared = next(c for c in report["comparison"]["values"] if c["quantity"] == "final_test.probability.average_precision")
    assert compared["actual"] != 0.123456
    assert report["reproduction_status"]["status"] == sr.STATUS_DIVERGENT


def test_dataset_hash_mismatch_is_detected(synthetic):
    synthetic["dataset"].write_text(synthetic["dataset"].read_text() + "extra,a,basic,1,1,1,No\n")
    result = _run(synthetic)
    assert result.executed is False
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_DATASET_MISMATCH


def test_answers_cover_every_success_criterion_question(synthetic):
    answers = sr.answer_reproduction_questions(_run(synthetic).build_report())
    for key in (
        "which_scientific_revision_was_reproduced", "which_dataset_revision_was_used",
        "which_scientific_environment_produced_the_reference", "which_models_were_expected",
        "which_models_were_executed", "which_search_spaces_were_reproduced",
        "which_selection_rule_was_executed", "which_threshold_rule_was_executed",
        "scientific_expected_metrics", "atlas_reproduced_metrics", "deltas", "all_within_tolerance",
        "unsupported", "final_reproduction_status", "unanswered",
    ):
        assert key in answers
    assert answers["which_selection_rule_was_executed"] == "leader_anchored_practical_tie"


def test_report_is_write_once_and_confined_to_its_run_directory(synthetic):
    result = _run(synthetic)
    root = synthetic["root"]
    before = {p for p in root.rglob("*")}
    written = sr.write_reproduction_report(result.build_report(), repo_root=root, search_results=result.search_results)
    created = {p for p in root.rglob("*")} - before
    run_dir = root / written["run_directory"]
    assert all(p == run_dir or run_dir in p.parents or p in run_dir.parents for p in created)
    stored = json.loads((root / written["report_path"]).read_text(encoding="utf-8"))
    assert hashlib.sha256((root / written["report_path"]).read_bytes()).hexdigest() == written["report_sha256"]
    assert stored["search_results_reference"]["path"].startswith(written["run_directory"])
    with pytest.raises(sr.ScientificReproductionError) as error:
        sr.write_reproduction_report(result.build_report(), repo_root=root)
    assert error.value.code == "run_directory_exists"


def test_invalid_report_is_refused(synthetic):
    report = _run(synthetic).build_report()
    report["metric_sets"][0]["provenance"]["producer_lineage"] = "atlas_release"
    with pytest.raises(sr.ScientificReproductionError) as error:
        sr.write_reproduction_report(report, repo_root=synthetic["root"])
    assert error.value.code == "invalid_report_schema"


# --------------------------------------------------------------------------
# historical immutability and committed Telco evidence
# --------------------------------------------------------------------------


def test_historical_external_materializations_remain_self_consistent():
    runs = REPO_ROOT / "pipeline/external-fitted-model-runs/telco-customer-churn"
    checked = 0
    for result_path in sorted(runs.glob("*/materialization-result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key, recorded in result.get("evidence_hashes", {}).items():
            relative = result["evidence_references"][key.replace("_sha256", "_path")]
            observed = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            assert observed == recorded, relative
            checked += 1
    assert checked > 0


def test_committed_telco_reproduction_reports_are_valid_and_separated():
    reports = sorted(TELCO_RUNS.glob("*/reproduction-report.json"))
    if not reports:
        pytest.skip("no committed Telco reproduction run")
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert sr.validate_report_schema(report) == []
        assert report["evidence_lineage"]["scientific_study_run"]["study_revision"] == (
            "43ced1fbb76f55ad156e133ee421e756b1921df1")
        assert report["run_identity"]["run_kind"] == "scientific_reproduction_run"
        assert report["reproduction_status"]["status"] in sr.REPRODUCTION_STATUSES
        assert all(m["provenance"]["producer_lineage"] == sr.RUN_KIND for m in report["metric_sets"])
        reference = report.get("search_results_reference")
        if reference:
            assert hashlib.sha256((REPO_ROOT / reference["path"]).read_bytes()).hexdigest() == reference["sha256"]


def test_lineage_separation_view_is_read_only_and_normalizes_native_metric_names(synthetic):
    root = synthetic["root"]
    (root / "registry").mkdir()
    (root / "registry/datasets.json").write_text(json.dumps({"datasets": [
        {"dataset_slug": "synthetic-study", "active_release": "release-20260101-001"}]}), encoding="utf-8")
    metrics_dir = root / "releases/release-20260101-001/metrics"
    metrics_dir.mkdir(parents=True)
    (metrics_dir / "metrics.json").write_text(json.dumps({
        "training_run_identity": {"run_id": "train-x"},
        "final_test_evaluation": {"metrics": [{"name": "pr_auc", "value": 0.5}, {"name": "roc_auc", "value": 0.6}]},
    }), encoding="utf-8")
    contract_dir = root / "contracts/synthetic-study"
    contract_dir.mkdir(parents=True)
    (contract_dir / "execution-contract.json").write_text(json.dumps({
        "split_policy": {"strategy": "stratified"}, "random_seed": 0, "primary_metric": "roc_auc",
        "result_semantics": {"decision": {"threshold": 0.5}},
        "modeling_constraints": {"selection_mode": "fixed_configuration"},
    }), encoding="utf-8")
    report = _run(synthetic).build_report()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    view = sr.describe_lineage_separation(report, repo_root=root)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    ap_row = next(r for r in view["rows"] if r["canonical_metric"] == "average_precision")
    assert ap_row["atlas_native_release"]["native_metric_name"] == "pr_auc"
    assert ap_row["atlas_native_release"]["provenance"]["lineage"] == sr.RELEASE_KIND
    assert ap_row["scientific_reproduction"]["provenance"]["lineage"] == sr.RUN_KIND
    assert all(row["directly_comparable"] is False for row in view["rows"])
    facts = {d["fact"]: d for d in view["protocol_differences"]}
    assert facts["decision_threshold"]["atlas_native"] == 0.5
    assert facts["model_selection"]["scientific_reproduction"] == "leader_anchored_practical_tie"


# --------------------------------------------------------------------------
# source verification against a (read-only) study checkout
# --------------------------------------------------------------------------


def _checkout(tmp_path: Path) -> tuple[Path, dict]:
    checkout = tmp_path / "study-checkout"
    (checkout / "reproducibility").mkdir(parents=True)
    (checkout / "README.md").write_text("| Train | 192 |\n", encoding="utf-8")
    (checkout / "reproducibility/canonical-run.json").write_text(
        json.dumps({"final_test": {"metrics": {"macro_f1": 0.9418}}}), encoding="utf-8")
    payload = _contract("0" * 64, 1)
    payload["source_repository"]["pinned_files"] = [
        {"path": "README.md", "sha256": hashlib.sha256((checkout / "README.md").read_bytes()).hexdigest(),
         "role": "narrative"},
    ]
    payload["expected_evidence"]["values"] = [
        {"quantity": "partitions.train.rows", "expected": 192, "comparison": "count",
         "source": {"path": "README.md", "locator": "file_text", "rendered_text": "| Train | 192 |"}},
        {"quantity": "final_test.probability.macro_f1", "expected": 0.9418, "comparison": "numeric",
         "source": {"path": "reproducibility/canonical-run.json",
                    "locator": "json_pointer:/final_test/metrics/macro_f1", "rendered_text": "0.9418"}},
    ]
    return checkout, payload


def test_source_verification_checks_pins_text_and_json_pointer_locators(tmp_path):
    checkout, payload = _checkout(tmp_path)
    result = ssc.verify_against_study_checkout(payload, checkout)
    assert all(check["rendered_text_found"] for check in result["expected_evidence_locators"])
    assert all(check["matches"] for check in result["pinned_files"])
    # No git metadata in the fixture: content matches but the revision cannot be confirmed.
    assert result["status"] == "revision_differs_but_pinned_content_unchanged"
    assert result["checkout_location_recorded"] is False
    assert str(tmp_path) not in json.dumps(result)


def test_source_verification_detects_study_drift(tmp_path):
    checkout, payload = _checkout(tmp_path)
    (checkout / "README.md").write_text("| Train | 193 |\n", encoding="utf-8")
    (checkout / "reproducibility/canonical-run.json").write_text(
        json.dumps({"final_test": {"metrics": {"macro_f1": 0.95}}}), encoding="utf-8")
    result = ssc.verify_against_study_checkout(payload, checkout)
    assert result["status"] == "study_revision_drift"
    assert not any(check["rendered_text_found"] for check in result["expected_evidence_locators"])
