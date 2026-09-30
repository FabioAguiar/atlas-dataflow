"""Concrete Compressive Strength: pinned study contract, committed reproduction, notebook section.

Concrete-specific by design (the engine tests stay dataset-agnostic). Needs
neither the gitignored dataset nor the study checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc


REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "b223370e0f4490d620ecd16aad5b30120a538c8f"
CONTRACT = REPO_ROOT / "pipeline/scientific-studies/concrete-compressive-strength/study-b223370e0f44/scientific-study-contract.json"
REPORT = REPO_ROOT / "pipeline/scientific-reproduction-runs/concrete-compressive-strength/repro-20260930T102822Z/reproduction-report.json"
NOTEBOOK = REPO_ROOT / "notebooks/datasets/concrete-compressive-strength/dataset_integration.ipynb"
FEATURES = ["Cement", "Blast Furnace Slag", "Fly Ash", "Water", "Superplasticizer", "Coarse Aggregate",
            "Fine Aggregate", "Age"]


@pytest.fixture(scope="module")
def contract() -> ssc.ScientificStudyContract:
    return ssc.load_scientific_study_contract(CONTRACT, repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _expected(payload: dict, quantity: str):
    return next(i["expected"] for g in ("values", "decisions") for i in payload["expected_evidence"][g]
                if i["quantity"] == quantity)


# --------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------


def test_contract_is_v3_pinned_to_the_real_revision_and_fully_supported(contract):
    payload = contract.payload
    assert payload["schema_version"] == "scientific-study-contract.v3"
    assert contract.study_revision == REVISION
    assert ssc.assess_protocol_support(payload) == []
    assert payload["canonical_run"]["path"] == "evidence/canonical-run.json"
    pinned = {f["path"] for f in payload["source_repository"]["pinned_files"]}
    assert {"evidence/canonical-run.json", "README.md", ".python-version", "pyproject.toml", "pylock.toml",
            "contracts/source.json", "scripts/prepare_data.py", "scripts/select_models.py",
            "scripts/finalize_model.py", "notebooks/03_model_selection_and_evaluation.ipynb"} <= pinned
    text = CONTRACT.read_text(encoding="utf-8")
    assert "/home/" not in text and "/tmp/" not in text and "/main/" not in text


def test_dataset_identity_is_pinned_beyond_row_and_column_counts(contract):
    identity = contract.payload["dataset_identity"]
    assert identity["sha256"] == "2f6e632031e655e2344153e4d84bbebcfc7d53f91cad3ab8130076a8e1d4e1be"
    assert (identity["size_bytes"], identity["row_count"], identity["column_count"]) == (48501, 1030, 9)
    assert identity["atlas_local_path"] == "data/scientific-studies/concrete-compressive-strength/dataset.csv"
    assert contract.payload["features"]["feature_columns"] == FEATURES
    assert contract.payload["problem"]["target"]["column"] == "Concrete compressive strength"


def test_regression_protocol_has_no_classification_concepts(contract):
    payload = contract.payload
    assert "threshold_policy" not in payload and "decision_rule" not in payload["problem"]
    assert not {"classes", "positive_class", "estimator_class_order", "public_class_order"} & set(payload["problem"]["target"])
    assert payload["problem"]["classification_concepts"]["applicable"] is False


def test_contract_declares_the_full_experimental_space(contract):
    payload = contract.payload
    split = payload["split"]
    assert split["kind"] == "two_stage_random_holdout" and split["stratify_by"] is None
    assert split["seeds"] == {"train_vs_temporary": 42, "validation_vs_test": 43}
    assert split["fractions"] == {"train": 0.7, "validation": 0.15, "test": 0.15}
    assert payload["cross_validation"] == {"kind": "k_fold", "n_splits": 5, "shuffle": True, "random_state": 42,
                                           "partition": "train"}
    assert payload["baseline"]["fixed_params"] == {"strategy": "median"}
    assert payload["baseline"]["eligible_for_selection"] is False
    candidates = {c["model_id"]: c for c in payload["candidates"]}
    assert {m: c["search"]["expected_candidate_count"] for m, c in candidates.items()} == {
        "ridge": 4, "decision_tree": 12, "random_forest": 12, "hist_gradient_boosting": 24}
    assert sum(c["search"]["expected_candidate_count"] for c in candidates.values()) == 52
    assert {m: c["numerical_scaling"] for m, c in candidates.items()} == {
        "ridge": "standard", "decision_tree": "passthrough", "random_forest": "passthrough",
        "hist_gradient_boosting": "passthrough"}
    assert candidates["random_forest"]["fixed_params"] == {"n_estimators": 300, "random_state": 42, "n_jobs": 1}
    assert candidates["hist_gradient_boosting"]["fixed_params"] == {"max_iter": 300, "random_state": 42}
    assert payload["metrics"]["primary"] == "mae" and payload["metrics"]["evaluated"] == ["mae", "rmse", "r2", "medae"]
    selection = payload["selection"]
    assert selection["eligibility"] == {"metric": "mae", "margin": 0.0, "strict": True, "baseline_model_id": "dummy_median"}
    assert selection["practical_tie"] == {"metric": "mae", "tolerance": 0.10, "requires_cv_interval_overlap": False,
                                          "bound": "leader_plus_tolerance"}
    assert [b["field"] for b in selection["tie_breakers"]] == [
        "validation_rmse", "validation_medae", "cv_mae_std", "validation_r2", "model_id"]
    assert payload["final_evaluation"]["fit_row_count_gate"]["expected_rows"] == 875
    overlap = payload["interpretive_evidence"]["group_overlap_diagnostic"]
    assert overlap["group_columns"] == FEATURES[:7] and "Age" not in overlap["group_columns"]


def test_expected_evidence_is_materialized_from_the_canonical_run(contract):
    payload = contract.payload
    items = [i for g in ("values", "decisions") for i in payload["expected_evidence"][g]]
    assert len(items) == 160
    assert all(i["source"]["path"] == "evidence/canonical-run.json" and i["source"]["locator"].startswith("json_pointer:")
               for i in items)
    assert _expected(payload, "validation.hist_gradient_boosting.mae") == 2.741655333532888
    assert _expected(payload, "cv.hist_gradient_boosting.mae_std") == 0.28291333949152325
    assert _expected(payload, "selection.selected_pipeline_params") == {
        "model__l2_regularization": 1.0, "model__learning_rate": 0.1, "model__max_leaf_nodes": 15,
        "model__min_samples_leaf": 10}
    assert round(_expected(payload, "final_test.metrics.mae"), 4) == 2.5822
    assert _expected(payload, "mixture_overlap.test.unseen.row_count") == 39
    tolerance = payload["tolerance_policy"]
    assert tolerance["numeric_absolute"] == 1e-9 and tolerance["count_absolute"] == 0
    assert tolerance["declared_before_first_reproduction"] is True


# --------------------------------------------------------------------------
# committed reproduction report
# --------------------------------------------------------------------------


def test_committed_report_is_valid_v3_and_reproduced(report, contract):
    assert sr.validate_report_schema(report) == []
    assert report["schema_version"] == "scientific-reproduction-report.v3"
    assert report["evidence_lineage"]["scientific_study_run"]["study_contract"]["sha256"] == contract.sha256
    assert report["reproduction_status"]["status"] == sr.STATUS_REPRODUCED_EXACT
    assert report["comparison"]["counts"][sr.OUTCOME_EXACT] == 160
    assert sum(report["comparison"]["counts"].values()) == 160
    tiers = report["reproduction_status"]["evidence_tiers"]
    assert tiers["scientific_mismatches"] == 0 and tiers["unsupported_capabilities"] == 0
    assert tiers["byte_identical_runtime"] is None  # never claimed from matching package versions
    assert report["source_verification"]["status"] == "synchronized"
    assert all(gate["passed"] for gate in report["gate_checks"]) and len(report["gate_checks"]) == 2


def test_report_executed_the_whole_space_and_the_study_rule(report):
    assert sum(row["candidate_count_executed"] for row in report["family_search"]) == 52
    selection = report["selection"]["executed"]
    assert selection["selected_model_id"] == "hist_gradient_boosting"
    assert selection["practical_tie"] is False and selection["practical_tie_group"] == ["hist_gradient_boosting"]
    assert selection["eligible_model_ids"] == ["hist_gradient_boosting", "random_forest", "decision_tree", "ridge"]
    assert report["final_fit"]["rows"] == 875 and report["final_fit"]["partitions"] == ["train", "validation"]
    assert {name: part["rows"] for name, part in report["split"]["observed"].items()} == {
        "train": 721, "validation": 154, "test": 155}
    finals = [m for m in report["metric_sets"] if m["provenance"]["metric_scope"] == "scientific_final_test"]
    assert len(finals) == 1 and finals[0]["metrics"]["row_count"] == 155


def test_report_keeps_lineages_and_class_concepts_separate(report):
    lineage = report["evidence_lineage"]
    assert lineage["atlas_native_training_run"]["referenced"] is False
    assert lineage["atlas_release"]["referenced"] is False
    assert report["thresholds"]["applicable"] is False
    assert report["problem"]["positive_class"]["applicable"] is False and report["problem"]["class_order"] is None
    diagnostics = report["interpretive_diagnostics"]
    assert diagnostics["used_for_selection"] is False
    assert {e["evaluated_partition"]: (e["seen_group_row_count"], e["unseen_group_row_count"])
            for e in diagnostics["evaluations"]} == {"validation": (111, 43), "test": (116, 39)}


def test_lineage_view_against_the_real_native_release(report):
    view = sr.describe_lineage_separation(report, repo_root=REPO_ROOT)
    assert view["active_release"] == "release-20260820-001"
    rows = {row["canonical_metric"]: row for row in view["rows"]}
    assert set(rows) == {"mae", "rmse", "r2"}
    assert all(row["directly_comparable"] is False for row in rows.values())
    assert rows["mae"]["atlas_native_release"]["value"] == pytest.approx(2.045284911051866)
    assert rows["mae"]["scientific_reproduction"]["value"] == pytest.approx(2.58215985944, abs=1e-9)
    facts = {d["fact"] for d in view["protocol_differences"]}
    assert {"split", "partition_membership", "model_selection"} <= facts


# --------------------------------------------------------------------------
# notebook section
# --------------------------------------------------------------------------


def _cells() -> list[dict]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def test_notebook_appends_the_scientific_section_after_the_native_stop():
    markdown = [("".join(c["source"]), i) for i, c in enumerate(_cells()) if c["cell_type"] == "markdown"]
    stop = next(i for text, i in markdown if text.startswith("## 17. Explicit stop"))
    science = next(i for text, i in markdown if text.startswith("## 18. Scientific Reproduction lineage"))
    assert science > stop
    code = "\n".join("".join(c["source"]) for c in _cells()[science:] if c["cell_type"] == "code")
    assert "RUN_SCIENTIFIC_REPRODUCTION = False" in code
    assert "study-b223370e0f44/scientific-study-contract.json" in code
    assert REPORT.relative_to(REPO_ROOT).as_posix() in code
    for call in ("load_scientific_study_contract(", "build_reproduction(", "write_reproduction_report(",
                 "answer_reproduction_questions(", "describe_lineage_separation("):
        assert call in code
    assert "dataset-study-concrete" not in code and "/home/" not in code


def test_notebook_is_committed_clean():
    for cell in _cells():
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
