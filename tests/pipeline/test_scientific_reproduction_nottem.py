"""Nottingham Scientific Study Contract, committed reproduction evidence and notebook section.

Dataset-specific values live only here, in the pinned contract, in the
write-once reproduction report and in the notebook. The live re-execution test
runs only when the SHA-verified source is present at the contract's gitignored
``atlas_local_path`` and statsmodels is installed.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from pipeline import metric_identity, model_families, scientific_environment
from pipeline import scientific_reproduction as sr
from pipeline import scientific_study_contract as ssc

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "79c6abccbf65bb622fd013288182bedf5aaf7f52"
CONTRACT = f"pipeline/scientific-studies/nottem/study-{REVISION[:12]}/scientific-study-contract.json"
DRAFT = f"pipeline/scientific-studies/nottem/study-{REVISION[:12]}/authoring/contract-draft.json"
REPORT = "pipeline/scientific-reproduction-runs/nottem/repro-20260930T125644Z/reproduction-report.json"
NOTEBOOK = REPO_ROOT / "notebooks/datasets/nottem/dataset_integration.ipynb"
CATALOG = ["seasonal_naive_12", "naive_last_value", "seasonal_trend_ols", "holt_winters_additive_no_trend",
           "holt_winters_additive_damped_trend", "holt_winters_additive_trend", "autoreg_lag_1_12_ct",
           "autoreg_lag_1_2_12_ct", "sarima_100_100_12", "sarima_100_011_12"]
FINALISTS = ["seasonal_trend_ols", "holt_winters_additive_no_trend", "sarima_100_011_12",
             "holt_winters_additive_damped_trend", "holt_winters_additive_trend"]
RANKING = FINALISTS + ["autoreg_lag_1_2_12_ct", "autoreg_lag_1_12_ct", "seasonal_naive_12", "naive_last_value"]


@pytest.fixture(scope="module")
def contract():
    return ssc.load_scientific_study_contract(REPO_ROOT / CONTRACT, repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def payload(contract):
    return contract.payload


@pytest.fixture(scope="module")
def report():
    return json.loads((REPO_ROOT / REPORT).read_text(encoding="utf-8"))


def _compared(report):
    return {item["quantity"]: item for item in report["comparison"]["values"] + report["comparison"]["decisions"]}


# --------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------


def test_contract_is_a_valid_pinned_v4_forecasting_contract(contract, payload):
    assert payload["schema_version"] == "scientific-study-contract.v4"
    assert ssc.validate_contract_schema(payload) == [] and ssc.validate_contract_semantics(payload) == []
    assert ssc.assess_protocol_support(payload) == []
    assert contract.study_revision == REVISION and contract.relative_path == CONTRACT
    assert payload["study_identity"]["protocol_kind"] == "univariate_forecasting_expanding_window_model_selection.v1"


def test_contract_pins_the_study_files_by_relative_path(payload):
    pinned = {f["path"]: f for f in payload["source_repository"]["pinned_files"]}
    for required in ("reproducibility/canonical-run.json", ".python-version", "pyproject.toml", "pylock.toml",
                     "scripts/forecasting_preparation.py", "scripts/forecasting_model_selection.py",
                     "scripts/forecasting_finalization.py", "scripts/forecasting_inference.py",
                     "scripts/canonical_run.py", "README.md"):
        assert required in pinned
    assert sum(path.startswith("notebooks/0") for path in pinned) == 5
    assert all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in pinned.values())
    assert all(not path.startswith("/") and ".." not in path.split("/") for path in pinned)
    assert pinned[payload["canonical_run"]["path"]]["sha256"] == payload["canonical_run"]["sha256"]
    text = (REPO_ROOT / CONTRACT).read_text(encoding="utf-8")
    assert "/home/" not in text and "/tmp/" not in text


def test_dataset_identity_is_the_pinned_scientific_boundary(payload):
    identity = payload["dataset_identity"]
    assert identity["sha256"] == "2908bd6f8235992fefffe4040266c3242e624eb372f2684b4acf54a9e434ca8b"
    assert (identity["row_count"], identity["column_count"], identity["source_columns"]) == (240, 2, ["time", "value"])
    assert identity["source_reference"] == "datasets::nottem" and identity["source_repository"] == "Rdatasets"
    assert identity["source_provider"] == "statsmodels.datasets.get_rdataset"
    assert identity["atlas_local_path"] == "data/scientific-studies/nottem/dataset.csv"
    assert identity["atlas_local_path"] != "data/raw/nottem/dataset.csv"


def test_study_vocabulary_is_preserved_and_mapped(payload):
    problem = payload["problem"]
    assert problem["study_problem_identity"] == {"problem_type": "time_series_forecasting", "forecasting_mode": "univariate"}
    assert problem["problem_type"] == ssc.atlas_problem_type_for(problem["study_problem_identity"]) == "univariate_forecasting"
    seasonal = next(m for m in payload["metrics"]["evaluated"] if m["study_name"] == "seasonal_mase_12")
    assert seasonal["metric_id"] == "seasonal_mase" and seasonal["parameters"] == {"seasonal_period": 12}
    metric_identity.resolve_parameterized_scientific_metric(seasonal["metric_id"], seasonal["parameters"],
                                                            problem_type=problem["problem_type"])


def test_temporal_protocol_and_fold_schedule(payload):
    protocol = payload["temporal_protocol"]
    assert (protocol["development"]["start"], protocol["development"]["end"], protocol["development"]["observations"]) == (
        "1920-01", "1938-12", 228)
    assert (protocol["final_holdout"]["start"], protocol["final_holdout"]["end"], protocol["final_holdout"]["observations"]) == (
        "1939-01", "1939-12", 12)
    backtesting = protocol["backtesting"]
    assert (backtesting["initial_training_observations"], backtesting["forecast_horizon"],
            backtesting["origin_step_observations"], backtesting["fold_count"],
            backtesting["validation_forecast_count"]) == (120, 12, 12, 9, 108)
    assert backtesting["validation_targets_overlap"] is False and backtesting["shuffle"] is False
    schedule = backtesting["fold_schedule"]
    assert (schedule[0]["training_observations"], schedule[0]["forecast_origin"], schedule[0]["validation_start"],
            schedule[0]["validation_end"]) == (120, "1929-12", "1930-01", "1930-12")
    assert (schedule[-1]["training_observations"], schedule[-1]["forecast_origin"], schedule[-1]["validation_start"],
            schedule[-1]["validation_end"]) == (216, "1937-12", "1938-01", "1938-12")


def test_frozen_catalog_is_complete_and_generic(payload):
    candidates = payload["candidates"]
    assert [c["candidate_id"] for c in candidates] == CATALOG
    assert [c["complexity_rank"] for c in candidates] == list(range(10))
    assert [c["role"] for c in candidates][:2] == ["primary_baseline", "secondary_baseline"]
    assert {c["family"] for c in candidates} == {"seasonal_naive", "naive_last_value", "deterministic_seasonal_trend_ols",
                                                 "exponential_smoothing", "autoreg", "sarimax"}
    sarima = next(c for c in candidates if c["candidate_id"] == "sarima_100_100_12")
    assert sarima["fixed_params"] == {"order": [1, 0, 0], "seasonal_order": [1, 0, 0, 12], "trend": "ct",
                                      "enforce_stationarity": True, "enforce_invertibility": True}
    # candidate_id stays distinct from family: no study candidate id is special-cased in generic code
    # (an id that coincides with a generic family id, such as naive_last_value, is the family's own name).
    study_only = [cid for cid in CATALOG if cid not in model_families.MODEL_FAMILIES]
    for module in ("pipeline/scientific_forecasting.py", "pipeline/forecasting_models.py",
                   "pipeline/scientific_reproduction.py", "pipeline/scientific_study_contract.py"):
        text = (REPO_ROOT / module).read_text(encoding="utf-8")
        assert not any(re.search(rf"\b{cid}\b", text) for cid in study_only), module


def test_selection_rule_and_tolerance_come_from_the_study(payload):
    selection = payload["selection"]
    assert selection["practical_tie"]["tolerance"] == 0.05 and selection["practical_tie"]["bound"] == "leader_plus_tolerance"
    assert [b["field"] for b in selection["tie_breakers"]] == [
        "pooled_seasonal_mase", "pooled_rmse", "fold_mae_std", "long_horizon_mae_h7_h12", "complexity_rank", "candidate_id"]
    assert selection["eligibility"]["baseline_margin_required"] is False
    assert selection["eligibility"]["baselines_rankable"] is True
    assert payload["tolerance_policy"]["numeric_absolute"] == 1e-9 and payload["tolerance_policy"]["count_absolute"] == 0
    assert payload["tolerance_policy"]["declared_before_first_reproduction"] is True


def test_holdout_exposure_and_superseded_reference_are_preserved(payload):
    exposure = payload["protocol_integrity"]["holdout_exposure"]
    assert exposure["final_holdout_exploration_blind"] is False
    assert exposure["final_holdout_exposure_review"] == "REV-001"
    assert exposure["used_for_scoring_tuning_or_selection"] is False and exposure["holdout_evaluation_count"] == 1
    assert payload["superseded_reference"]["status"] == "superseded_not_canonical"
    assert payload["superseded_reference"]["reproduction_target"] is False


def test_expected_evidence_is_read_by_pointer_from_the_canonical_run(payload):
    items = payload["expected_evidence"]["values"] + payload["expected_evidence"]["decisions"]
    assert len(items) == 189
    locators = {item["source"]["locator"].split(":")[0] for item in items}
    assert locators == {"json_pointer", "file_text"}
    file_text = [item for item in items if item["source"]["locator"] == "file_text"]
    assert len(file_text) == 10 and all(item["source"]["path"] == "scripts/forecasting_model_selection.py"
                                        for item in file_text)
    forecasts = [item for item in items if item["quantity"].startswith("final_holdout.forecasts.")]
    assert len(forecasts) == 24


def test_contract_matches_its_authoring_draft(payload):
    draft = json.loads((REPO_ROOT / DRAFT).read_text(encoding="utf-8"))
    for key in ("temporal_protocol", "candidates", "selection", "finalization", "failure_policy", "metrics",
                "protocol_integrity"):
        assert draft[key] == payload[key]


# --------------------------------------------------------------------------
# committed write-once reproduction evidence
# --------------------------------------------------------------------------


def test_report_is_a_valid_v4_forecasting_report_bound_to_the_contract(report, contract):
    assert sr.validate_report_schema(report) == []
    assert report["schema_version"] == "scientific-reproduction-report.v4"
    study = report["evidence_lineage"]["scientific_study_run"]
    assert study["study_revision"] == REVISION and study["study_contract"]["sha256"] == contract.sha256
    assert report["dataset"]["verified"] is True
    assert report["dataset"]["observed_sha256"] == contract.payload["dataset_identity"]["sha256"]
    sidecar = report["backtest_forecasts_reference"]
    assert hashlib.sha256((REPO_ROOT / sidecar["path"]).read_bytes()).hexdigest() == sidecar["sha256"]


def test_report_keeps_the_lineages_separate(report):
    lineage = report["evidence_lineage"]
    assert lineage["atlas_native_training_run"]["referenced"] is False
    assert lineage["atlas_release"]["referenced"] is False
    assert report["immutability"] == {"write_once": True, "historical_artifacts_modified": False, "supersedes": None}
    text = (REPO_ROOT / REPORT).read_text(encoding="utf-8")
    assert "training-runs/" not in text and "releases/" not in text and "/home/" not in text


def test_every_specification_was_executed_and_failures_follow_the_semantics(report):
    results = {r["candidate_id"]: r for r in report["candidate_results"]}
    assert list(results) == CATALOG
    for cid, record in results.items():
        if cid == "sarima_100_100_12":
            assert record["eligible"] is False and record["failure_count"] > 0
            assert record["failure_kinds"] == ["ForecastingModelSelectionError"]
            assert record["failure_categories"] == ["explicit_optimizer_non_convergence"]
        else:
            assert record["eligible"] is True and record["forecast_rows"] == 108 and record["failure_count"] == 0


def test_the_selection_is_reproduced_independently(report):
    selection = report["selection"]["executed"]
    assert selection["selected_candidate_id"] == "seasonal_trend_ols"
    assert selection["finalists"] == FINALISTS and selection["ranking"] == RANKING
    compared = _compared(report)
    for quantity in ("model_selection.catalog", "model_selection.finalists", "model_selection.ranking",
                     "model_selection.selected_candidate_id", "model_selection.selected_family",
                     "model_selection.selected_specification", "model_selection.tie_break_order",
                     "model_selection.practical_tie_tolerance", "model_selection.best_leader_value"):
        assert compared[quantity]["outcome"] == sr.OUTCOME_EXACT, quantity


def test_final_fit_and_the_twelve_point_forecast_match_the_canonical_evidence(report):
    fit, final = report["final_fit"], report["final_evaluation"]
    assert fit["observations"] == 228 and fit["start"] == "1920-01" and fit["end"] == "1938-12"
    assert fit["constructor"] == "statsmodels.regression.linear_model.OLS"
    assert report["final_forecast"]["forecast_origin"] == "1938-12" and final["evaluation_count"] == 1
    compared = _compared(report)
    points = [q for q in compared if q.startswith("final_holdout.")]
    assert len(points) == 1 + 3 + 3 + 24
    assert all(compared[q]["outcome"] in (sr.OUTCOME_EXACT, sr.OUTCOME_WITHIN) for q in points)
    assert [compared[f"final_holdout.forecasts.h{h:02d}.forecast_period"]["actual"] for h in range(1, 13)] == [
        f"1939-{m:02d}" for m in range(1, 13)]
    for metric in ("mae", "rmse", "seasonal_mase"):
        assert abs(compared[f"final_holdout.metrics.{metric}"]["delta"]) <= 1e-9
        assert abs(compared[f"selected_backtest.{metric}"]["delta"]) <= 1e-9


def test_status_is_reported_without_relaxing_the_tolerance(report):
    status = report["reproduction_status"]
    compared = _compared(report)
    diverging = [q for q, c in compared.items() if c["outcome"] in (sr.OUTCOME_OUTSIDE, sr.OUTCOME_MISMATCH)]
    if diverging:
        assert status["status"] == sr.STATUS_DIVERGENT
        scope = report["divergence_scope"]
        assert scope["selection_decisions_agree"] is True
        assert scope["selected_specification_evidence_agrees"] is True
        assert scope["final_holdout_evidence_agrees"] is True
        assert set(scope["diverging_quantities_by_specification"]) <= {
            "holt_winters_additive_no_trend", "holt_winters_additive_damped_trend", "holt_winters_additive_trend",
            "sarima_100_100_12", "sarima_100_011_12"}
    assert report["comparison"]["tolerance_policy"]["numeric_absolute"] == 1e-9
    assert report["environment"]["compatibility"]["classification"] != scientific_environment.EXACT or (
        report["environment"]["reproduction_runtime"]["platform"] == "linux-aarch64")


def test_report_records_the_holdout_exposure_limitation(report):
    exposure = report["holdout_exposure"]
    assert exposure["final_holdout_exploration_blind"] is False and exposure["final_holdout_exposure_review"] == "REV-001"
    assert "not an exploration-blind" in exposure["reproduction_consequence"]


def test_committed_nottem_evidence_is_byte_intact():
    for relative in (CONTRACT, DRAFT, REPORT, str(Path(REPORT).parent / "backtest-forecasts.json")):
        committed = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"HEAD:{relative}"], capture_output=True,
                                   check=False)
        if committed.returncode != 0:
            pytest.skip("not committed yet")
        assert (REPO_ROOT / relative).read_bytes() == committed.stdout


def test_lineage_view_reads_native_evidence_without_writing(report):
    view = sr.describe_lineage_separation(report, repo_root=REPO_ROOT)
    assert view["active_release"] and view["rows"]
    assert all(row["directly_comparable"] is False for row in view["rows"])
    assert {(r["scope"], r["canonical_metric"]) for r in view["rows"]} == {
        (scope, metric) for scope in ("expanding_window_backtest", "final_holdout")
        for metric in ("mae", "rmse", "seasonal_mase")}
    # Same geometry and model form: the lineages nearly coincide, yet stay separate.
    assert all(row["absolute_difference"] < 1e-9 for row in view["rows"])
    assert any(d["fact"] == "model_selection" for d in view["protocol_differences"])


def test_live_reexecution_reproduces_the_committed_decisions(report, contract):
    pytest.importorskip("statsmodels")
    dataset = REPO_ROOT / contract.payload["dataset_identity"]["atlas_local_path"]
    if not dataset.is_file():
        pytest.skip("SHA-verified scientific source is not materialized (gitignored)")
    result = sr.build_reproduction(contract, repo_root=REPO_ROOT).run(run_id="repro-live-check")
    live = result.build_report()
    assert live["selection"]["executed"]["ranking"] == report["selection"]["executed"]["ranking"]
    assert live["final_forecast"]["values"] == pytest.approx(report["final_forecast"]["values"], abs=1e-12)
    if live["environment"]["reproduction_runtime"] == report["environment"]["reproduction_runtime"]:
        assert live["comparison"]["counts"] == report["comparison"]["counts"]


# --------------------------------------------------------------------------
# notebook integration
# --------------------------------------------------------------------------


def _cells():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def _scientific_code():
    cells = _cells()
    start = next(i for i, c in enumerate(cells) if "".join(c["source"]).startswith("## 18. Scientific Reproduction"))
    return start, "\n".join("".join(c["source"]) for c in cells[start:] if c["cell_type"] == "code")


def test_notebook_appends_scientific_reproduction_after_the_native_boundary():
    cells = _cells()
    start, code = _scientific_code()
    native_stop = next(i for i, c in enumerate(cells) if "".join(c["source"]).startswith("## 17. Explicit stop"))
    assert start > native_stop
    assert "RUN_SCIENTIFIC_REPRODUCTION = False" in code
    assert REPORT in code and (REPO_ROOT / REPORT).is_file()
    assert "build_reproduction(" in code and "write_reproduction_report(" in code


def test_notebook_holds_no_forecasting_implementation():
    _, code = _scientific_code()
    for forbidden in ("OLS(", "ExponentialSmoothing(", "AutoReg(", "SARIMAX(", ".fit(", "statsmodels", "period_range",
                      ".diff(", "np.mean", "sorted(", "dataset-study", "/home/"):
        assert forbidden not in code, forbidden
