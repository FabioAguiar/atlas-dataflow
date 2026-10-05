"""Multiclass Scientific Reproduction: contract v2, engine stages, and the Dry Bean evidence.

Synthetic multiclass studies are built inside ``tmp_path`` (no identifier
column, string labels, two-stage split with row-occurrence membership, a
family shortlist and a feature-policy stage) so every protocol stage runs in
seconds. The real Dry Bean contract and its committed reproduction report
are checked structurally; they need neither the dataset nor the study
checkout.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import pytest

from pipeline import scientific_environment as env
from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc


REPO_ROOT = Path(__file__).resolve().parents[2]
DRY_BEAN_REVISION = "e3e697c1b60f7b11f4ccb7e82447a6680bc2bfaf"
DRY_BEAN_CONTRACT = (
    REPO_ROOT / "pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/scientific-study-contract.json"
)
DRY_BEAN_RUNS = REPO_ROOT / "pipeline/scientific-reproduction-runs/dry-bean"
TELCO_CONTRACT = (
    REPO_ROOT / "pipeline/scientific-studies/telco-customer-churn/study-43ced1fbb76f/scientific-study-contract.json"
)
REVISION = "fedcba9876543210fedcba9876543210fedcba98"
LABEL = f"study-{REVISION[:12]}"
PUBLIC = ["ROUND", "LONG", "FLAT"]
ESTIMATOR_ORDER = sorted(PUBLIC)  # scikit-learn classes_ order
FEATURES = ["width", "height", "ratio", "noise"]


# --------------------------------------------------------------------------
# synthetic multiclass study
# --------------------------------------------------------------------------


def _synthetic_csv(path: Path, rows: int = 420) -> None:
    rng = random.Random(11)
    lines = ["width,height,ratio,noise,Kind"]
    for index in range(rows):
        kind = PUBLIC[index % 3]
        width = {"ROUND": 10.0, "LONG": 6.0, "FLAT": 14.0}[kind] + rng.gauss(0, 1.6)
        height = {"ROUND": 10.0, "LONG": 15.0, "FLAT": 5.0}[kind] + rng.gauss(0, 1.6)
        noise = round(rng.uniform(0, 1), 3)
        lines.append(f"{width:.4f},{height:.4f},{width / height:.6f},{noise},{kind}")
    # an exact repeated row exercises the occurrence ordinal of the membership key
    lines.append(lines[1])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate(model_id, family, fixed, scaling, search):
    return {"model_id": model_id, "family": family, "fixed_params": fixed, "numerical_scaling": scaling,
            "search": search, "eligible_for_selection": True}


def _contract(dataset_sha: str, size: int, rows: int) -> dict:
    source = {"path": "reproducibility/canonical-run.json", "locator": "json_pointer:/x", "rendered_text": "x"}
    return {
        "schema_version": "scientific-study-contract.v2",
        "artifact_kind": "scientific_study_contract",
        "study_identity": {"study_id": "dataset-study-synthetic-multiclass", "dataset_slug": "synthetic-multiclass",
                           "protocol_kind": "tabular_holdout_model_selection.v2", "study_revision_label": LABEL},
        "source_repository": {"url": "https://example.invalid/study", "revision": REVISION,
                              "pinned_files": [{"path": "README.md", "sha256": "0" * 64, "role": "narrative"}]},
        "dataset_identity": {"file_name": "synthetic.csv", "sha256": dataset_sha, "size_bytes": size,
                             "row_count": rows, "column_count": 5, "read_format": "csv", "read_options": {},
                             "atlas_local_path": "data/scientific-studies/synthetic-multiclass/synthetic.csv"},
        "scientific_environment": {"python": "3.13.0", "platform": None, "core_packages": {"scikit-learn": "1.9.0"},
                                   "lock": {"path": "pylock.toml", "sha256": "1" * 64, "format": "pep751"},
                                   "compatibility_policy": {"python": "same_major", "core_packages": "same_major"}},
        "problem": {
            "problem_type": "multiclass_classification",
            "target": {"column": "Kind", "classes": list(PUBLIC), "label_representation": "string_labels",
                       "positive_class": {"applicable": False, "reason": "multiclass_problem_has_no_positive_class"},
                       "estimator_class_order": list(ESTIMATOR_ORDER), "public_class_order": list(PUBLIC)},
            "decision_rule": {"kind": "argmax_class_probability", "tie_resolution": "first_in_public_class_order"},
            "identifier_columns": [],
        },
        "features": {"feature_columns": list(FEATURES), "numerical": list(FEATURES), "categorical": []},
        "preparation": {"rules": [], "row_removal": "none"},
        "split": {"kind": "two_stage_stratified_holdout",
                  "membership": {"kind": "technical_row_occurrence", "digest_order": "source_position"},
                  "fractions": {"train": 0.6, "validation": 0.2, "test": 0.2}, "stratify_by": "Kind",
                  "shuffle": True, "seeds": {"train_vs_temporary": 3, "validation_vs_test": 4},
                  "partition_handoff": {"kind": "csv_roundtrip", "float_format": "%.15g"},
                  "partition_fingerprint": {"kind": "csv_bytes_sha256", "float_format": "%.15g"}},
        "preprocessing": {"kind": "column_transformer_onehot_plus_numeric"},
        "cross_validation": {"kind": "stratified_k_fold", "n_splits": 3, "shuffle": True, "random_state": 5},
        "metrics": {"primary": "macro_f1", "refit": "macro_f1",
                    "evaluated": ["macro_f1", "balanced_accuracy", "macro_recall", "weighted_f1", "accuracy",
                                  "minimum_per_class_recall", "log_loss"],
                    "cv_scorers": ["macro_f1", "balanced_accuracy", "weighted_f1", "log_loss"]},
        "baseline": {"model_id": "dummy_prior", "family": "dummy_prior", "fixed_params": {"strategy": "prior"},
                     "numerical_scaling": "passthrough", "search": {"kind": "none"}, "eligible_for_selection": False},
        "candidates": [
            _candidate("logistic_regression", "logistic_regression", {"max_iter": 500, "random_state": 1}, "standard",
                       {"kind": "grid", "space": {"C": [0.1, 1.0]}, "expected_candidate_count": 2}),
            _candidate("decision_tree", "decision_tree", {"random_state": 1}, "passthrough",
                       {"kind": "grid", "space": {"max_depth": [2, 4]}}),
            _candidate("random_forest", "random_forest", {"random_state": 1, "n_estimators": 15}, "passthrough",
                       {"kind": "randomized", "n_iter": 2, "random_state": 1, "space": {"max_depth": [3, 5, None]}}),
        ],
        "search_execution": {"n_jobs": 1},
        "family_shortlist": {"kind": "top_k_by_cv_metric", "metric": "macro_f1", "k": 2, "direction": "max",
                             "tie_order": "model_id"},
        "feature_policies": {"kind": "frozen_family_params_feature_projection",
                             "candidate_id_pattern": "{model_id}__{policy_id}",
                             "policies": [{"policy_id": "all_features", "exclude": []},
                                          {"policy_id": "without_noise", "exclude": ["noise"]},
                                          {"policy_id": "without_ratio", "exclude": ["ratio"]}]},
        "selection": {
            "kind": "leader_anchored_practical_tie", "partition": "validation",
            "eligibility": {"metric": "macro_f1", "margin": 0.02, "strict": True},
            "leader": {"metric": "macro_f1", "direction": "max"},
            "practical_tie": {"metric": "macro_f1", "tolerance": 0.02, "requires_cv_interval_overlap": False},
            "tie_breakers": [
                {"criterion": "higher_validation_balanced_accuracy", "field": "validation_balanced_accuracy", "direction": "max"},
                {"criterion": "higher_minimum_per_class_recall", "field": "validation_minimum_per_class_recall", "direction": "max"},
                {"criterion": "lower_cv_macro_f1_std", "field": "cv_macro_f1_std", "direction": "min"},
                {"criterion": "lower_validation_log_loss_when_comparable", "field": "validation_log_loss", "direction": "min"},
                {"criterion": "simpler_pipeline_or_model", "field": "simplicity_rank", "direction": "min"},
                {"criterion": "stable_model_id", "field": "model_id", "direction": "min"},
            ],
            "simplicity_order": ["logistic_regression", "decision_tree", "random_forest"],
        },
        "threshold_policy": {"kind": "not_applicable", "applicable": False, "reason": "multiclass_argmax_decision"},
        "final_evaluation": {"kind": "refit_on_train_plus_validation_single_test_evaluation",
                             "fit_partitions": ["train", "validation"], "evaluation_partition": "test",
                             "evaluation_count": 1},
        "interpretive_evidence": {"confusion_pairs": {"top_k": 2, "focal_pairs": [["ROUND", "LONG"]]},
                                  "repeated_profile_sensitivity": {
                                      "kind": "non_destructive_repeated_feature_profile_sensitivity",
                                      "reference_partitions": ["train", "validation"]}},
        "tolerance_policy": {"numeric_absolute": 1e-6, "count_absolute": 0, "rationale": "synthetic"},
        "expected_evidence": {
            "values": [{"quantity": "partitions.train.rows", "expected": 252, "comparison": "count",
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


@pytest.fixture()
def study(tmp_path: Path):
    dataset = tmp_path / "data/scientific-studies/synthetic-multiclass/synthetic.csv"
    dataset.parent.mkdir(parents=True)
    _synthetic_csv(dataset)
    rows = len(dataset.read_text().splitlines()) - 1
    payload = _contract(hashlib.sha256(dataset.read_bytes()).hexdigest(), dataset.stat().st_size, rows)
    contract_path = tmp_path / ssc.STUDIES_ROOT_RELATIVE / "synthetic-multiclass" / LABEL / ssc.CONTRACT_FILENAME

    def write(data: dict) -> ssc.ScientificStudyContract:
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(json.dumps(data), encoding="utf-8")
        return ssc.load_scientific_study_contract(contract_path, repo_root=tmp_path)

    runtime = {"python": "3.13.1", "platform": "linux-x86_64", "core_packages": {"scikit-learn": "1.9.0"}}
    return {"root": tmp_path, "payload": payload, "write": write, "runtime": runtime, "dataset": dataset}


def _run(study, payload=None, **kwargs):
    contract = study["write"](payload or study["payload"])
    reproduction = sr.build_reproduction(contract, repo_root=study["root"], runtime=study["runtime"])
    return reproduction.run(run_id="repro-mc", n_jobs=1, **kwargs)


@pytest.fixture(scope="module")
def baseline_run(tmp_path_factory):
    """One full synthetic run shared by read-only assertions."""
    root = tmp_path_factory.mktemp("mc")
    dataset = root / "data/scientific-studies/synthetic-multiclass/synthetic.csv"
    dataset.parent.mkdir(parents=True)
    _synthetic_csv(dataset)
    rows = len(dataset.read_text().splitlines()) - 1
    payload = _contract(hashlib.sha256(dataset.read_bytes()).hexdigest(), dataset.stat().st_size, rows)
    path = root / ssc.STUDIES_ROOT_RELATIVE / "synthetic-multiclass" / LABEL / ssc.CONTRACT_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    contract = ssc.load_scientific_study_contract(path, repo_root=root)
    runtime = {"python": "3.13.1", "platform": "linux-x86_64", "core_packages": {"scikit-learn": "1.9.0"}}
    result = sr.build_reproduction(contract, repo_root=root, runtime=runtime).run(run_id="repro-mc", n_jobs=1)
    return {"result": result, "report": result.build_report(), "payload": payload}


# --------------------------------------------------------------------------
# contract v2: problem-type conditional schema and semantics
# --------------------------------------------------------------------------


def test_real_dry_bean_contract_is_valid_pinned_and_fully_supported():
    contract = ssc.load_scientific_study_contract(DRY_BEAN_CONTRACT, repo_root=REPO_ROOT)
    payload = contract.payload
    assert contract.study_revision == DRY_BEAN_REVISION
    assert payload["schema_version"] == "scientific-study-contract.v2"
    assert ssc.assess_protocol_support(payload) == []
    assert payload["problem"]["problem_type"] == "multiclass_classification"
    assert payload["problem"]["target"]["positive_class"] == {"applicable": False,
                                                              "reason": "multiclass_problem_has_no_positive_class"}
    assert payload["threshold_policy"] == {"kind": "not_applicable", "applicable": False,
                                           "reason": "multiclass_argmax_decision"}
    assert payload["problem"]["decision_rule"]["kind"] == "argmax_class_probability"
    assert payload["problem"]["target"]["estimator_class_order"] == [
        "BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SEKER", "SIRA"]
    assert payload["problem"]["target"]["public_class_order"] == [
        "SEKER", "BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SIRA"]
    assert payload["split"]["seeds"] == {"train_vs_temporary": 42, "validation_vs_test": 43}
    assert {c["family"] for c in payload["candidates"]} == {
        "logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting"}
    assert {c["model_id"]: c["search"]["kind"] for c in payload["candidates"]} == {
        "logistic_regression": "grid", "decision_tree": "grid", "random_forest": "randomized",
        "hist_gradient_boosting": "randomized"}
    assert [p["policy_id"] for p in payload["feature_policies"]["policies"]] == [
        "all_features", "without_shape_factor_2", "without_confirmed_derived"]
    assert payload["selection"]["practical_tie"]["tolerance"] == 0.002
    assert "default_threshold" not in payload["metrics"]


def test_dry_bean_contract_pins_canonical_run_lock_and_interpreter():
    payload = json.loads(DRY_BEAN_CONTRACT.read_text(encoding="utf-8"))
    pinned = {f["path"] for f in payload["source_repository"]["pinned_files"]}
    assert {"reproducibility/canonical-run.json", ".python-version", "pyproject.toml", "pylock.toml",
            "scripts/select_models.py", "notebooks/03_model_selection_and_evaluation.ipynb"} <= pinned
    assert payload["canonical_run"]["path"] == "reproducibility/canonical-run.json"
    assert payload["dataset_identity"]["sha256"] == "1330e4ccc5c54a925e43daf60d1409ac62dad2a21de9a25213765bee4b655787"
    assert payload["split"]["membership_gate"]["expected_membership_sha256"]["train"] == (
        "34e9cb09dc42d27a53ced3ef811868b9b926a8f435999ab16e817b50a612609e")
    # Expected values are materialized from the canonical run by pointer, never typed by hand.
    pointer_items = [i for g in ("values", "decisions") for i in payload["expected_evidence"][g]
                     if i["source"]["locator"].startswith("json_pointer:")]
    assert len(pointer_items) >= 200
    assert all(i["source"]["path"] == "reproducibility/canonical-run.json" for i in pointer_items)
    text = DRY_BEAN_CONTRACT.read_text(encoding="utf-8")
    assert "/home/" not in text and "/main/" not in text


def test_dry_bean_contract_preserves_historical_exposure_limitation():
    payload = json.loads(DRY_BEAN_CONTRACT.read_text(encoding="utf-8"))
    integrity = payload["protocol_integrity"]
    assert integrity["test_procedurally_isolated_in_canonical_run"] is True
    assert integrity["historical_test_exposure"]["exposed"] is True
    assert "superseded" in integrity["historical_test_exposure"]["description"]
    assert "never seen" not in integrity["statement"].replace("must not be described as never seen", "")


def test_multiclass_schema_valid_for_synthetic_contract(study):
    assert ssc.validate_contract_schema(study["payload"]) == []
    assert ssc.validate_contract_semantics(study["payload"]) == []


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p["problem"]["target"].update(positive_class="ROUND"), "positive_class"),
        (lambda p: p["problem"]["target"].update(positive_class=None), "positive_class"),
        (lambda p: p.update(threshold_policy={"kind": "max_precision_subject_to_min_recall", "partition": "validation",
                                              "min_recall": 0.8}), "threshold_policy"),
        (lambda p: p.update(threshold_policy=None), "threshold_policy"),
        (lambda p: p["metrics"].update(default_threshold=0.5), "metrics"),
        (lambda p: p["problem"]["target"].pop("estimator_class_order"), "estimator_class_order"),
        (lambda p: p["problem"]["target"].pop("public_class_order"), "public_class_order"),
        (lambda p: p["problem"]["decision_rule"].update(kind="probability_threshold"), "decision_rule"),
        (lambda p: p.pop("family_shortlist"), "family_shortlist"),
    ],
)
def test_multiclass_schema_rejects_binary_only_or_missing_concepts(study, mutate, needle):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    errors = ssc.validate_contract_schema(payload)
    assert errors, "a multiclass contract must not accept binary-only or missing concepts"
    assert any(needle in error or "<root>" in error or "problem" in error for error in errors)


def test_binary_v2_contract_requires_threshold_policy_and_positive_class(study):
    payload = copy.deepcopy(study["payload"])
    payload["problem"]["problem_type"] = "binary_classification"
    payload["problem"]["target"] = {"column": "Kind", "classes": ["A", "B"], "positive_class": "B",
                                    "encoding": {"A": 0, "B": 1}}
    payload["problem"]["decision_rule"] = {"kind": "probability_threshold"}
    assert any("threshold_policy" in e for e in ssc.validate_contract_schema(payload))
    payload["problem"]["target"]["positive_class"] = {"applicable": False, "reason": "x"}
    assert ssc.validate_contract_schema(payload)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p["problem"]["target"].update(public_class_order=["ROUND", "LONG", "OVAL"]), "public_class_order"),
        (lambda p: p["problem"]["target"].update(estimator_class_order=["FLAT", "LONG"]), "estimator_class_order"),
        (lambda p: p["feature_policies"]["policies"][1].update(exclude=["not_a_feature"]), "unknown features"),
        (lambda p: p["feature_policies"]["policies"].append({"policy_id": "all_features", "exclude": []}), "duplicate"),
        (lambda p: p["features"].update(categorical=["noise"]), "disjoint"),
    ],
)
def test_contract_semantics_reject_incoherent_orders_and_policies(study, mutate, needle):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    errors = ssc.validate_contract_semantics(payload)
    assert any(needle in e for e in errors), errors
    with pytest.raises(ssc.ScientificStudyContractError) as error:
        study["write"](payload)
    assert error.value.code in ("invalid_contract_semantics", "invalid_contract_schema")


def test_unsupported_contract_version_is_refused():
    assert ssc.validate_contract_schema({"schema_version": "scientific-study-contract.v9"})


# --------------------------------------------------------------------------
# dispatch by problem type (never by dataset)
# --------------------------------------------------------------------------


def test_problem_type_dispatch_selects_task_adapters(study):
    telco = json.loads(TELCO_CONTRACT.read_text(encoding="utf-8"))
    assert isinstance(sr.task_adapter(telco), sr.BinaryClassificationTask)
    assert isinstance(sr.task_adapter(study["payload"]), sr.MulticlassClassificationTask)
    bogus = copy.deepcopy(study["payload"])
    bogus["problem"]["problem_type"] = "univariate_forecasting"
    with pytest.raises(sr.ScientificReproductionError):
        sr.task_adapter(bogus)


def test_metric_vocabulary_is_problem_type_specific(study):
    payload = copy.deepcopy(study["payload"])
    payload["metrics"]["evaluated"].append("average_precision")
    payload["selection"]["tie_breakers"].insert(0, {"criterion": "x", "field": "validation_brier_score", "direction": "min"})
    gaps = {(g["element"], g["value"]) for g in ssc.assess_protocol_support(payload)}
    assert ("metrics.evaluated", "average_precision") in gaps
    assert ("selection.tie_breakers.field", "validation_brier_score") in gaps
    assert ssc.assess_protocol_support(study["payload"]) == []


def test_engine_sources_contain_no_dataset_specific_branches():
    for module in ("pipeline/scientific_reproduction.py", "pipeline/scientific_study_contract.py",
                   "pipeline/scientific_environment.py", "pipeline/model_families.py"):
        text = (REPO_ROOT / module).read_text(encoding="utf-8").lower()
        for forbidden in ("dry-bean", "dry_bean", "drybean", "telco", "seker", "dermason", "shapefactor"):
            assert forbidden not in text, (module, forbidden)


# --------------------------------------------------------------------------
# class order, probability alignment, argmax and multiclass log loss
# --------------------------------------------------------------------------


class _FakeEstimator:
    """Minimal fitted estimator whose classes_ order is chosen by the test."""

    def __init__(self, classes, probabilities):
        self.classes_ = np.asarray(classes, dtype=object)
        self._probabilities = np.asarray(probabilities, dtype=float)

    def predict_proba(self, x):
        return self._probabilities


Y_TRUE = ["SEKER", "BARBUNYA", "SIRA", "SEKER"]
CLASSES_PUBLIC = ["SEKER", "BARBUNYA", "SIRA"]
CLASSES_ESTIMATOR = ["BARBUNYA", "SEKER", "SIRA"]
# Rows in estimator order: BARBUNYA, SEKER, SIRA.
RAW = [[0.1, 0.8, 0.1], [0.7, 0.2, 0.1], [0.2, 0.2, 0.6], [0.3, 0.6, 0.1]]


def test_probabilities_are_aligned_through_estimator_classes():
    aligned = sr.align_probabilities_to_class_order(RAW, CLASSES_ESTIMATOR, CLASSES_PUBLIC,
                                                    expected_estimator_order=CLASSES_ESTIMATOR)
    assert aligned[0].tolist() == [0.8, 0.1, 0.1]  # SEKER, BARBUNYA, SIRA
    assert aligned[1].tolist() == [0.2, 0.7, 0.1]


def test_multiclass_log_loss_uses_estimator_class_order_not_public_or_lexicographic():
    aligned = sr.align_probabilities_to_class_order(RAW, CLASSES_ESTIMATOR, CLASSES_PUBLIC)
    correct = sr.multiclass_log_loss(Y_TRUE, aligned, CLASSES_PUBLIC)
    manual = -np.mean(np.log([0.8, 0.7, 0.6, 0.6]))
    assert correct == pytest.approx(manual, abs=1e-15)
    # Regression guard: treating raw estimator columns as if they were in public order is wrong.
    misaligned = sr.multiclass_log_loss(Y_TRUE, np.asarray(RAW), CLASSES_PUBLIC)
    assert abs(misaligned - correct) > 0.5


def test_reordered_probability_columns_do_not_change_evaluation():
    public = ["SEKER", "BARBUNYA", "SIRA"]
    permuted_classes = ["SIRA", "BARBUNYA", "SEKER"]
    permuted = np.asarray(RAW)[:, [2, 0, 1]]
    a = sr.align_probabilities_to_class_order(RAW, CLASSES_ESTIMATOR, public)
    b = sr.align_probabilities_to_class_order(permuted, permuted_classes, public)
    assert np.array_equal(a, b)


def test_missing_probability_class_fails_explicitly():
    with pytest.raises(sr.ScientificReproductionError) as error:
        sr.align_probabilities_to_class_order([[0.5, 0.5]], ["BARBUNYA", "SEKER"], CLASSES_PUBLIC)
    assert error.value.code == "probability_shape_mismatch" or error.value.code == "probability_class_mismatch"
    with pytest.raises(sr.ScientificReproductionError) as error:
        sr.align_probabilities_to_class_order([[0.4, 0.3, 0.3]], ["BARBUNYA", "SEKER", "OTHER"], CLASSES_PUBLIC)
    assert error.value.code == "probability_class_mismatch"


def test_estimator_class_order_different_from_contract_fails():
    with pytest.raises(sr.ScientificReproductionError) as error:
        sr.align_probabilities_to_class_order(RAW, CLASSES_ESTIMATOR, CLASSES_PUBLIC,
                                              expected_estimator_order=CLASSES_PUBLIC)
    assert error.value.code == "estimator_class_order_mismatch"


def test_argmax_decision_and_tie_resolution():
    probabilities = [[0.2, 0.5, 0.3], [0.4, 0.4, 0.2]]  # public order SEKER, BARBUNYA, SIRA
    labels, ties = sr.argmax_decisions(probabilities, CLASSES_PUBLIC, CLASSES_ESTIMATOR, "first_in_public_class_order")
    assert labels == ["BARBUNYA", "SEKER"] and ties == 1
    labels, _ = sr.argmax_decisions(probabilities, CLASSES_PUBLIC, CLASSES_ESTIMATOR, "first_in_estimator_class_order")
    assert labels == ["BARBUNYA", "BARBUNYA"]


def test_task_evaluation_matches_sklearn_metrics_with_public_confusion_order(study):
    from sklearn.metrics import balanced_accuracy_score, f1_score, recall_score

    task = sr.task_adapter({**study["payload"], "problem": {
        **study["payload"]["problem"],
        "target": {**study["payload"]["problem"]["target"], "classes": CLASSES_PUBLIC,
                   "estimator_class_order": CLASSES_ESTIMATOR, "public_class_order": CLASSES_PUBLIC}}})
    evaluation = task.evaluate(_FakeEstimator(CLASSES_ESTIMATOR, RAW), None, Y_TRUE)
    predicted = ["SEKER", "BARBUNYA", "SIRA", "SEKER"]
    metrics = evaluation.flat_metrics
    assert metrics["macro_f1"] == pytest.approx(f1_score(Y_TRUE, predicted, average="macro"))
    assert metrics["weighted_f1"] == pytest.approx(f1_score(Y_TRUE, predicted, average="weighted"))
    assert metrics["balanced_accuracy"] == pytest.approx(balanced_accuracy_score(Y_TRUE, predicted))
    assert metrics["minimum_per_class_recall"] == pytest.approx(min(recall_score(Y_TRUE, predicted, average=None)))
    assert evaluation.detail["confusion_matrix"]["class_order"] == CLASSES_PUBLIC
    assert evaluation.detail["estimator_class_order"] == CLASSES_ESTIMATOR
    assert set(evaluation.detail["per_class"]) == {"seker", "barbunya", "sira"}
    assert evaluation.detail["per_class"]["seker"]["support"] == 2


def test_confusion_pairs_rank_by_mutual_errors():
    confusion = {"class_order": ["A", "B", "C"], "counts": [[5, 3, 0], [4, 6, 1], [0, 2, 9]]}
    ranked = sr.rank_confusion_pairs(confusion)
    assert ranked[0] == {"class_pair": ["A", "B"], "mutual_errors": 7}
    assert ranked[1] == {"class_pair": ["B", "C"], "mutual_errors": 3}


# --------------------------------------------------------------------------
# split: two stages, second seed, row-occurrence membership
# --------------------------------------------------------------------------


def test_row_occurrence_keys_distinguish_repeated_rows():
    import pandas as pd

    frame = pd.DataFrame({"a": [1.5, 1.5, 2.0], "b": ["x", "x", "y"]})
    keys = sr.row_occurrence_membership_keys(frame)
    assert keys[0].endswith(":00000000") and keys[1].endswith(":00000001")
    assert keys[0].rsplit(":", 1)[0] == keys[1].rsplit(":", 1)[0]
    assert len(set(keys)) == 3


def test_split_is_deterministic_and_depends_on_the_second_stage_seed(study):
    import pandas as pd

    frame = pd.read_csv(study["dataset"])
    split = study["payload"]["split"]
    first, keys_a = sr.split_two_stage_stratified_with_membership(frame, split, [])
    again, keys_b = sr.split_two_stage_stratified_with_membership(frame.sample(frac=1, random_state=0).reset_index(drop=True), split, [])
    digest = lambda keys: {n: sr.membership_digest(sorted(v), "sorted_keys") for n, v in keys.items()}
    assert digest(keys_a) == digest(keys_b), "membership must not depend on input row order"
    assert [len(first[n]) for n in ("train", "validation", "test")] == [252, 84, 85]
    other = {**split, "seeds": {"train_vs_temporary": 3, "validation_vs_test": 3}}
    _, keys_c = sr.split_two_stage_stratified_with_membership(frame, other, [])
    assert digest(keys_c)["train"] == digest(keys_a)["train"]
    assert digest(keys_c)["validation"] != digest(keys_a)["validation"]


def test_membership_gate_blocks_execution_on_mismatch(study, baseline_run):
    observed = {n: baseline_run["result"].actuals["partitions"][n]["membership_sha256"] for n in ("train", "validation", "test")}
    payload = copy.deepcopy(study["payload"])
    source = {"path": "reproducibility/canonical-run.json", "locator": "json_pointer:/split/membership_sha256", "rendered_text": "x"}
    payload["split"]["membership_gate"] = {"required": True, "expected_membership_sha256": observed, "source": source}
    passed = _run(study, payload)
    assert passed.gate_failures == [] and passed.executed
    # wrong second-stage seed -> different validation/test membership -> explicit stop
    payload["split"]["seeds"]["validation_vs_test"] = 99
    failed = _run(study, payload)
    report = failed.build_report()
    assert failed.executed is False
    assert report["reproduction_status"]["status"] == sr.STATUS_DIVERGENT
    assert any("split.membership_sha256" in r for r in report["reproduction_status"]["reasons"])
    assert report["candidate_models"]["executed"] == [], "no model may be fitted after a failed membership gate"
    assert sr.validate_report_schema(report) == []


def test_wrong_partition_membership_digest_blocks(study, baseline_run):
    observed = {n: baseline_run["result"].actuals["partitions"][n]["membership_sha256"] for n in ("train", "validation", "test")}
    observed["test"] = "f" * 64
    payload = copy.deepcopy(study["payload"])
    payload["split"]["membership_gate"] = {"required": True, "expected_membership_sha256": observed, "source": {
        "path": "reproducibility/canonical-run.json", "locator": "json_pointer:/split/membership_sha256", "rendered_text": "x"}}
    result = _run(study, payload)
    assert result.executed is False and result.gate_failures


# --------------------------------------------------------------------------
# search, shortlist, feature policies, selection, final fit
# --------------------------------------------------------------------------


def test_end_to_end_multiclass_reproduction_executes_every_stage(baseline_run):
    result, report = baseline_run["result"], baseline_run["report"]
    assert result.executed
    assert sr.validate_report_schema(report) == []
    families = {row["model_id"]: row for row in report["family_search"]}
    assert families["logistic_regression"]["search_strategy"] == "GridSearchCV"
    assert families["random_forest"]["search_strategy"] == "RandomizedSearchCV"
    assert families["random_forest"]["random_seed"] == 1
    assert families["logistic_regression"]["candidate_count_executed"] == 2
    assert families["random_forest"]["candidate_count_executed"] == 2
    shortlist = report["family_shortlist"]
    assert len(shortlist["model_ids"]) == 2
    ranking = [r["model_id"] for r in shortlist["ranking"]]
    assert shortlist["model_ids"] == ranking[:2]
    stage = report["feature_policy_stage"]
    assert len(stage["candidates"]) == 6
    assert {c["feature_policy"] for c in stage["candidates"]} == {"all_features", "without_noise", "without_ratio"}
    assert all(c["base_model_id"] in shortlist["model_ids"] for c in stage["candidates"])
    counts = {c["feature_policy"]: c["feature_count"] for c in stage["candidates"]}
    assert counts == {"all_features": 4, "without_noise": 3, "without_ratio": 3}
    selection = report["selection"]["executed"]
    assert selection["selected_model_id"] in {c["model_id"] for c in stage["candidates"]}
    assert result.actuals["final_fit"]["rows"] == 252 + 84
    assert result.actuals["final_fit"]["partitions"] == ["train", "validation"]


def test_validation_is_only_used_for_shortlisted_variants(baseline_run):
    validation_sets = [m for m in baseline_run["report"]["metric_sets"] if m["provenance"]["partition"] == "validation"]
    ids = {m["provenance"]["model_id"] for m in validation_sets}
    variants = {c["model_id"] for c in baseline_run["report"]["feature_policy_stage"]["candidates"]}
    assert ids == variants | {"dummy_prior"}
    shortlisted = set(baseline_run["report"]["family_shortlist"]["model_ids"])
    excluded = {"logistic_regression", "decision_tree", "random_forest"} - shortlisted
    assert not any(m["provenance"]["model_id"].startswith(tuple(excluded)) for m in validation_sets)


def test_threshold_is_explicitly_not_applicable_everywhere(baseline_run):
    report = baseline_run["report"]
    assert report["thresholds"]["applicable"] is False
    assert report["thresholds"]["reason"] == "multiclass_argmax_decision"
    assert report["problem"]["positive_class"]["applicable"] is False
    for metric_set in report["metric_sets"]:
        provenance = metric_set["provenance"]
        if provenance["partition"] in ("validation", "test"):
            assert provenance["threshold"] == {"applicable": False, "reason": "multiclass_argmax_decision"}
            assert provenance["class_order"] == PUBLIC


def test_metric_sets_carry_scope_lineage(baseline_run):
    scopes = {m["provenance"]["metric_scope"] for m in baseline_run["report"]["metric_sets"]}
    assert scopes == {"baseline_validation", "family_search_cv", "feature_policy_cv", "candidate_validation",
                      "scientific_final_test"}
    final = [m for m in baseline_run["report"]["metric_sets"] if m["provenance"]["metric_scope"] == "scientific_final_test"]
    assert len(final) == 1 and final[0]["provenance"]["fit_partitions"] == ["train", "validation"]
    assert final[0]["metrics"]["confusion_matrix"]["class_order"] == PUBLIC


def test_final_test_evidence_is_complete_and_non_destructive(baseline_run):
    final = baseline_run["result"].actuals["final_test"]
    assert final["evaluation_count"] == 1 and final["row_count"] == 85
    assert final["estimator_class_order"] == ESTIMATOR_ORDER
    assert final["confusion_matrix"]["class_order"] == PUBLIC
    assert sum(map(sum, final["confusion_matrix"]["counts"])) == 85
    assert len(final["top_confusion_pairs"]) == 2
    assert final["focal_confusion_pairs"][0]["class_pair"] == ["ROUND", "LONG"]
    sensitivity = final["repeated_profile_sensitivity"]
    assert sensitivity["official_full_test_row_count"] == 85
    assert sensitivity["official_test_rows_removed"] == 0
    assert "does not prove" in sensitivity["interpretation"] or "do not prove" in sensitivity["interpretation"]
    assert len(final["probability_matrix_sha256"]) == 64


def test_declared_candidate_count_mismatch_fails(study):
    payload = copy.deepcopy(study["payload"])
    payload["candidates"][0]["search"]["expected_candidate_count"] = 3
    with pytest.raises(sr.ScientificReproductionError) as error:
        _run(study, payload)
    assert error.value.code == "declared_candidate_count_mismatch"


@pytest.mark.parametrize(
    "mutate, element",
    [
        (lambda p: p["candidates"][0].update(family="xgboost"), "candidates[logistic_regression].family"),
        (lambda p: p["candidates"][2]["search"]["space"].update(bogus=[1]), "candidates[random_forest].hyperparameter"),
        (lambda p: p["family_shortlist"].update(kind="top_percentile"), "family_shortlist.kind"),
        (lambda p: p["feature_policies"].update(kind="recursive_elimination"), "feature_policies.kind"),
    ],
)
def test_unsupported_family_hyperparameter_or_stage_is_capability_missing(study, mutate, element):
    payload = copy.deepcopy(study["payload"])
    mutate(payload)
    gaps = ssc.assess_protocol_support(payload)
    assert element in {g["element"] for g in gaps}


def test_missing_model_family_blocks_execution(study):
    payload = copy.deepcopy(study["payload"])
    payload["candidates"][1]["family"] = "catboost"
    result = _run(study, payload)
    assert result.executed is False
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_CAPABILITY_MISSING


def test_wrong_final_fit_row_count_gate_stops_before_test(study):
    payload = copy.deepcopy(study["payload"])
    payload["final_evaluation"]["fit_row_count_gate"] = {"expected_rows": 999, "source": {
        "path": "reproducibility/canonical-run.json", "locator": "json_pointer:/final_model/fit_row_count", "rendered_text": "999"}}
    result = _run(study, payload)
    report = result.build_report()
    assert "final_test" not in result.actuals
    assert report["reproduction_status"]["status"] == sr.STATUS_DIVERGENT
    assert any("final_evaluation.fit_row_count" in r for r in report["reproduction_status"]["reasons"])


def test_wrong_contract_class_order_fails_explicitly(study):
    payload = copy.deepcopy(study["payload"])
    payload["problem"]["target"]["estimator_class_order"] = list(PUBLIC)  # not scikit-learn's order
    with pytest.raises(sr.ScientificReproductionError) as error:
        _run(study, payload)
    assert error.value.code == "estimator_class_order_mismatch"


def _with_expected(study, baseline_run, items, group="values"):
    payload = copy.deepcopy(study["payload"])
    source = {"path": "reproducibility/canonical-run.json", "locator": "json_pointer:/x", "rendered_text": "x"}
    payload["expected_evidence"][group] = payload["expected_evidence"].get(group, []) + [
        {"reported_decimal_places": None, "source": source, **item} for item in items]
    return payload


def test_reproduced_values_match_their_own_actuals_and_status_is_within_tolerance(study, baseline_run):
    actuals = baseline_run["result"].actuals
    selection = actuals["selection"]
    payload = _with_expected(study, baseline_run, [
        {"quantity": "final_test.metrics.macro_f1", "expected": actuals["final_test"]["metrics"]["macro_f1"], "comparison": "numeric"},
        {"quantity": "final_test.confusion_matrix", "expected": actuals["final_test"]["confusion_matrix"], "comparison": "exact"},
    ])
    decisions = _with_expected(study, baseline_run, [
        {"quantity": "selection.selected_model_id", "expected": selection["selected_model_id"], "comparison": "exact"},
        {"quantity": "selection.practical_tie", "expected": selection["practical_tie"], "comparison": "exact"},
    ], group="decisions")["expected_evidence"]["decisions"]
    payload["expected_evidence"]["decisions"] = decisions
    report = _run(study, payload).build_report()
    assert report["comparison"]["all_exact_at_reported_precision"]
    # environment differs in patch level -> compatible, never "exact"
    assert report["reproduction_status"]["status"] == sr.STATUS_REPRODUCED_WITHIN_TOLERANCE
    tiers = report["reproduction_status"]["evidence_tiers"]
    assert tiers["structural_exact"] is True and tiers["scientific_mismatches"] == 0


@pytest.mark.parametrize(
    "item",
    [
        {"quantity": "selection.selected_model_id", "expected": "decision_tree__all_features", "comparison": "exact"},
        {"quantity": "selection.practical_tie", "expected": "flip", "comparison": "exact"},
        {"quantity": "final_test.metrics.macro_f1", "expected": 0.123456, "comparison": "numeric"},
    ],
)
def test_wrong_decisions_or_metrics_are_divergent(study, baseline_run, item):
    actual_tie = baseline_run["result"].actuals["selection"]["practical_tie"]
    if item["expected"] == "flip":
        item = {**item, "expected": not actual_tie}
    payload = _with_expected(study, baseline_run, [item], group="decisions" if item["comparison"] == "exact" else "values")
    report = _run(study, payload).build_report()
    assert report["reproduction_status"]["status"] == sr.STATUS_DIVERGENT


def test_confusion_matrix_with_wrong_class_order_is_a_mismatch(study, baseline_run):
    confusion = baseline_run["result"].actuals["final_test"]["confusion_matrix"]
    reordered = {"class_order": list(reversed(confusion["class_order"])), "counts": confusion["counts"]}
    payload = _with_expected(study, baseline_run, [
        {"quantity": "final_test.confusion_matrix", "expected": reordered, "comparison": "exact"}], group="decisions")
    report = _run(study, payload).build_report()
    compared = next(c for c in report["comparison"]["decisions"] if c["quantity"] == "final_test.confusion_matrix")
    assert compared["outcome"] == sr.OUTCOME_MISMATCH
    assert report["reproduction_status"]["status"] == sr.STATUS_DIVERGENT


def test_runtime_identity_difference_never_makes_a_reproduction_divergent(study, baseline_run):
    payload = _with_expected(study, baseline_run, [
        {"quantity": "final_test.probability_matrix_sha256", "expected": "0" * 64, "comparison": "exact"}],
        group="runtime_identity")
    report = _run(study, payload).build_report()
    assert report["comparison"]["byte_identical_runtime"] is False
    assert report["reproduction_status"]["status"] == sr.STATUS_REPRODUCED_WITHIN_TOLERANCE
    assert report["reproduction_status"]["evidence_tiers"]["byte_identical_runtime"] is False


def test_reference_values_are_not_copied_into_actuals(study, baseline_run):
    payload = _with_expected(study, baseline_run, [
        {"quantity": "final_test.metrics.log_loss", "expected": 12.5, "comparison": "numeric"}])
    report = _run(study, payload).build_report()
    compared = next(c for c in report["comparison"]["values"] if c["quantity"] == "final_test.metrics.log_loss")
    assert compared["actual"] != 12.5


def test_dataset_sha_mismatch_blocks(study):
    study["dataset"].write_text(study["dataset"].read_text() + "1,1,1,1,ROUND\n")
    result = _run(study)
    assert result.executed is False
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_DATASET_MISMATCH


def test_incompatible_environment_is_not_executed(study):
    study["runtime"]["core_packages"]["scikit-learn"] = "0.24.2"
    result = _run(study)
    assert result.executed is False
    assert result.build_report()["reproduction_status"]["status"] == sr.STATUS_ENVIRONMENT_INCOMPATIBLE


# --------------------------------------------------------------------------
# shortlist and practical-tie rules (study semantics)
# --------------------------------------------------------------------------


def test_shortlist_top_k_breaks_ties_by_model_id():
    summaries = {"b": {"macro_f1_mean": 0.9}, "a": {"macro_f1_mean": 0.9}, "c": {"macro_f1_mean": 0.95}}
    shortlist = sr.shortlist_top_k(summaries, {"kind": "top_k_by_cv_metric", "metric": "macro_f1", "k": 2})
    assert shortlist["model_ids"] == ["c", "a"]


def _study_lexicographic_selection(records, dummy, margin, tolerance, simplicity):
    """Independent transcription of the study's select_multiclass_candidate_model key."""
    eligible = [r for r in records if r["validation_macro_f1"] - dummy > margin]
    eligible.sort(key=lambda r: (-r["validation_macro_f1"], r["model_id"]))
    first = eligible[0]
    group = [r for r in eligible if first["validation_macro_f1"] - r["validation_macro_f1"] <= tolerance]
    if len(group) == 1:
        return first["model_id"], False
    key = lambda r: (-r["validation_balanced_accuracy"], -r["validation_minimum_per_class_recall"], r["cv_macro_f1_std"],
                     r["validation_log_loss"], r["simplicity_rank"], r["model_id"])
    return min(group, key=key)["model_id"], True


def test_engine_tie_breaking_equals_the_study_lexicographic_rule():
    payload = json.loads(DRY_BEAN_CONTRACT.read_text(encoding="utf-8"))
    rule = payload["selection"]
    rng = random.Random(3)
    for _ in range(300):
        records = []
        for index in range(6):
            base = 0.93 + rng.choice([0.0, 0.0005, 0.001, 0.0015, 0.003])
            records.append({
                "model_id": f"m{index}",
                "validation_macro_f1": base,
                "validation_balanced_accuracy": rng.choice([0.93, 0.94, 0.94]),
                "validation_minimum_per_class_recall": rng.choice([0.86, 0.87]),
                "cv_macro_f1_std": rng.choice([0.001, 0.002]),
                "validation_log_loss": rng.choice([0.2, 0.3]),
                "simplicity_rank": rng.choice([0, 3]),
            })
        expected, tie = _study_lexicographic_selection(records, 0.06, 0.02, 0.002, rule["simplicity_order"])
        selection = sr.select_leader_anchored_practical_tie(records, 0.06, rule)
        assert selection["selected_model_id"] == expected
        assert selection["practical_tie"] is tie


def test_dry_bean_published_candidates_reproduce_the_practical_tie_decision():
    """Selection rule applied to the study's own published validation evidence."""
    payload = json.loads(DRY_BEAN_CONTRACT.read_text(encoding="utf-8"))
    values = {i["quantity"]: i["expected"] for i in payload["expected_evidence"]["values"]}
    simplicity = payload["selection"]["simplicity_order"]
    records = []
    for policy in ("all_features", "without_shape_factor_2", "without_confirmed_derived"):
        for base in ("hist_gradient_boosting", "logistic_regression"):
            model_id = f"{base}__{policy}"
            records.append({
                "model_id": model_id,
                **{f"validation_{m}": values[f"validation.{model_id}.{m}"] for m in
                   ("macro_f1", "balanced_accuracy", "minimum_per_class_recall", "log_loss")},
                "cv_macro_f1_std": values[f"feature_policy.{model_id}.cv.macro_f1_std"],
                "simplicity_rank": simplicity.index(base),
            })
    selection = sr.select_leader_anchored_practical_tie(records, values["baseline.validation.macro_f1"], payload["selection"])
    assert selection["practical_tie"] is True
    assert selection["practical_tie_group"] == ["hist_gradient_boosting__all_features",
                                                "hist_gradient_boosting__without_shape_factor_2"]
    assert selection["leader_minus_runner_up"] == pytest.approx(0.001204, abs=1e-6)
    assert selection["deciding_criterion"] == "higher_validation_balanced_accuracy"
    assert selection["selected_model_id"] == "hist_gradient_boosting__all_features"


# --------------------------------------------------------------------------
# committed Dry Bean reproduction evidence
# --------------------------------------------------------------------------


def _dry_bean_reports():
    return sorted(DRY_BEAN_RUNS.glob("*/reproduction-report.json"))


def test_committed_dry_bean_reproduction_report_answers_the_success_questions():
    reports = _dry_bean_reports()
    assert reports, "the real Dry Bean scientific reproduction run must be committed"
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert sr.validate_report_schema(report) == []
        assert report["evidence_lineage"]["scientific_study_run"]["study_revision"] == DRY_BEAN_REVISION
        assert report["dataset"]["verified"] is True
        answers = sr.answer_reproduction_questions(report)
        assert answers["did_partition_memberships_match"] is True
        assert answers["partition_row_counts"] == {"train": 9527, "validation": 2042, "test": 2042}
        assert answers["which_split_seeds_were_used"] == {"train_vs_temporary": 42, "validation_vs_test": 43}
        assert answers["which_families_were_searched"] == [
            "logistic_regression", "decision_tree", "random_forest", "hist_gradient_boosting"]
        assert answers["which_search_strategy_per_family"] == {
            "logistic_regression": "GridSearchCV", "decision_tree": "GridSearchCV",
            "random_forest": "RandomizedSearchCV", "hist_gradient_boosting": "RandomizedSearchCV"}
        assert answers["how_many_candidates_per_family"] == {
            "logistic_regression": 4, "decision_tree": 8, "random_forest": 8, "hist_gradient_boosting": 8}
        assert answers["which_families_entered_the_shortlist"] == ["hist_gradient_boosting", "logistic_regression"]
        assert len(answers["which_feature_policy_candidates_were_evaluated"]) == 6
        assert answers["was_there_a_practical_tie"] is True
        assert answers["which_model_was_selected"] == "hist_gradient_boosting__all_features"
        assert answers["final_fit_partitions_and_rows"] == {"partitions": ["train", "validation"], "rows": 11569}
        assert answers["threshold"] == {"applicable": False, "reason": "multiclass_argmax_decision"}
        assert answers["decision_rule"]["kind"] == "argmax_class_probability"
        assert answers["class_order_preserved"] is True
        assert answers["did_confusion_matrix_match"] is True
        assert answers["did_per_class_metrics_match"] is True
        assert answers["historical_test_exposure"]["exposed"] is True
        assert answers["final_reproduction_status"] in (sr.STATUS_REPRODUCED_EXACT, sr.STATUS_REPRODUCED_WITHIN_TOLERANCE)
        assert answers["exceeded_tolerance_or_mismatched"] == []
        assert answers["not_produced"] == []
        assert all(m["provenance"]["producer_lineage"] == sr.RUN_KIND for m in report["metric_sets"])
        reference = report["search_results_reference"]
        assert hashlib.sha256((REPO_ROOT / reference["path"]).read_bytes()).hexdigest() == reference["sha256"]


def test_scientific_reproduction_stays_separate_from_dry_bean_native_training():
    reports = _dry_bean_reports()
    assert reports
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    before = {p: p.stat().st_mtime_ns for p in (REPO_ROOT / "releases").rglob("*") if p.is_file()}
    view = sr.describe_lineage_separation(report, repo_root=REPO_ROOT)
    assert {p: p.stat().st_mtime_ns for p in (REPO_ROOT / "releases").rglob("*") if p.is_file()} == before
    assert view["rows"] and all(row["directly_comparable"] is False for row in view["rows"])
    macro = next(r for r in view["rows"] if r["canonical_metric"] == "macro_f1")
    assert macro["atlas_native_release"]["native_metric_name"] == "f1_macro"
    assert macro["atlas_native_release"]["provenance"]["lineage"] == sr.RELEASE_KIND
    assert macro["scientific_reproduction"]["provenance"]["lineage"] == sr.RUN_KIND
    assert macro["atlas_native_release"]["value"] != macro["scientific_reproduction"]["value"]
    facts = {d["fact"]: d for d in view["protocol_differences"]}
    assert facts["test_partition_rows"]["scientific_reproduction"] == 2042
    assert facts["test_partition_rows"]["atlas_native"] != 2042
    assert facts["model_selection"]["atlas_native"] == "fixed_configuration"
    assert facts["decision_threshold"]["scientific_reproduction"] == {"applicable": False,
                                                                      "reason": "multiclass_argmax_decision"}


def test_dry_bean_native_lineage_is_unchanged_by_the_reproduction():
    native = json.loads((REPO_ROOT / "contracts/dry-bean/execution-contract.json").read_text(encoding="utf-8"))
    assert native["modeling_constraints"]["selection_mode"] == "fixed_configuration"
    assert native["modeling_constraints"]["allowed_model_families"] == ["hist_gradient_boosting"]
    for report_path in _dry_bean_reports():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["evidence_lineage"]["atlas_native_training_run"]["referenced"] is False
        assert report["evidence_lineage"]["atlas_release"]["referenced"] is False
        assert report["immutability"]["historical_artifacts_modified"] is False


def test_v1_telco_reports_still_validate_and_telco_contract_stays_v1():
    telco = json.loads(TELCO_CONTRACT.read_text(encoding="utf-8"))
    assert telco["schema_version"] == "scientific-study-contract.v1"
    assert ssc.validate_contract_schema(telco) == []
    # The Telco run history is write-once evidence: the first runs were
    # recorded with report v1 and later runs with the engine's current binary/
    # multiclass report v2. Historical v1 reports must keep validating against
    # the v1 schema, and every later Telco report must be a governed binary
    # report version that validates against its own declared schema.
    governed_binary_report_versions = {sr.REPORT_SCHEMA_VERSION_V1, sr.REPORT_SCHEMA_VERSION}
    seen_versions = set()
    for path in sorted((REPO_ROOT / "pipeline/scientific-reproduction-runs/telco-customer-churn").glob("*/reproduction-report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["schema_version"] in governed_binary_report_versions, path
        assert sr.validate_report_schema(report) == [], path
        seen_versions.add(report["schema_version"])
    assert sr.REPORT_SCHEMA_VERSION_V1 in seen_versions


def test_environment_classification_for_dry_bean_reference():
    payload = json.loads(DRY_BEAN_CONTRACT.read_text(encoding="utf-8"))
    reference = payload["scientific_environment"]
    same = {"python": "3.13.13", "platform": "linux-aarch64", "core_packages": dict(reference["core_packages"])}
    assert env.classify_environment(reference, same)["classification"] == env.EXACT
    x86 = {**same, "platform": "linux-x86_64"}
    assert env.classify_environment(reference, x86)["classification"] == env.COMPATIBLE
    old = {**same, "core_packages": {**reference["core_packages"], "scikit-learn": "1.8.2"}}
    assert env.classify_environment(reference, old)["classification"] == env.INCOMPATIBLE
