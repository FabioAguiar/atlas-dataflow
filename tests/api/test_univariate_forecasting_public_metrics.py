"""Project Spec S0247: univariate-forecasting public metrics projection.

Covers `api/public_metrics_loader.py`'s new explicit `training-metrics.v4`
schema-version dispatch (mirroring the existing native continuous-regression
`training-metrics.v3` dispatch pattern): explicit dispatch, exclusive
selection of the sealed `final_holdout_evaluation` (pooled backtesting
metrics are never projected), deterministic `split_name="final_holdout"`,
`sample_size` from `observation_count`, bounded mae/rmse/seasonal_mase
projection, `primary_metric_id`/`metric_order` derived from the governed
`evaluation_policy` (never dict/declaration order), unknown/non-finite/
boolean metric omission, and no private evidence leakage. All fixtures are
synthetic, written under `tmp_path`-backed temporary release directories --
never the real repository `releases/` tree.

Existing binary (training-metrics.v1), multiclass (training-metrics.v2), and
continuous-regression (training-metrics.v3) public metrics behavior is
exercised too, to prove this addition is purely additive.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

# `tests/api/__init__.py` makes `api` ambiguous as a dotted package path
# from within this test package (it would resolve to `tests.api`, not the
# real repository `api/` directory) -- importing the module directly (the
# same convention `tests/api/test_public_endpoints.py` already uses for
# `main`/`public_predict_view_customization_loader`) avoids that collision.
import public_metrics_loader  # noqa: E402

DATASET_SLUG = "example-forecasting-dataset"
RUN_ID = "train-20260823T000000Z"


def _write_release(release_dir: Path, *, artifacts: list) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "release-manifest.v1",
        "manifest_kind": "release_manifest",
        "artifacts": artifacts,
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_artifact_file(release_dir: Path, relative_path: str, data) -> None:
    path = release_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_metrics_release(releases_root: Path, release_id: str, metrics_payload) -> None:
    release_dir = releases_root / release_id
    _write_release(
        release_dir,
        artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
    )
    _write_artifact_file(release_dir, "metrics/metrics.json", metrics_payload)


def _v4_metrics_payload(
    *,
    final_holdout_metrics: list | None = None,
    backtesting_pooled_metrics: list | None = None,
    final_holdout_observation_count: int = 12,
    primary_metric_id: str = "mae",
    secondary_metric_ids: list | None = None,
    seasonal_period: int = 12,
) -> dict:
    if final_holdout_metrics is None:
        final_holdout_metrics = [
            {"name": "mae", "value": 3.1},
            {"name": "rmse", "value": 4.25},
            {"name": "seasonal_mase", "value": 0.87},
        ]
    if backtesting_pooled_metrics is None:
        backtesting_pooled_metrics = [
            {"name": "mae", "value": 5.4},
            {"name": "rmse", "value": 6.9},
            {"name": "seasonal_mase", "value": 1.10},
        ]
    if secondary_metric_ids is None:
        secondary_metric_ids = ["rmse", "seasonal_mase"]

    secondary_metrics = []
    for metric_id in secondary_metric_ids:
        entry = {"metric_id": metric_id, "direction": "lower_is_better"}
        if metric_id == "seasonal_mase":
            entry["seasonal_period"] = seasonal_period
        secondary_metrics.append(entry)

    primary_entry = {"metric_id": primary_metric_id, "direction": "lower_is_better"}
    if primary_metric_id == "seasonal_mase":
        primary_entry["seasonal_period"] = seasonal_period

    return {
        "schema_version": "training-metrics.v4",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-23T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": RUN_ID,
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/",
        },
        "forecasting_evidence": {
            "problem_type": "univariate_forecasting",
            "result_semantics_schema_version": "univariate-forecasting-result-semantics.v1",
            "forecast_horizon": 6,
        },
        "evaluation_policy": {
            "primary_metric": primary_entry,
            "secondary_metrics": secondary_metrics,
        },
        "backtesting_evaluation": {
            "fold_count": 5,
            "forecast_count": 30,
            "pooled_metrics": backtesting_pooled_metrics,
            "fold_summaries": [
                {
                    "fold_index": 0,
                    "forecast_origin": "2026-01-01",
                    "validation_observations": 6,
                    "metrics": [{"name": "mae", "value": 5.0}],
                }
            ],
            "horizon_mae": [],
        },
        "final_holdout_evaluation": {
            "evaluation_count": 1,
            "observation_count": final_holdout_observation_count,
            "metrics": final_holdout_metrics,
            "model_frozen_before_open": True,
            "used_for_adjustment": False,
            "used_for_retuning": False,
            "used_for_model_selection": False,
        },
        "path_references": {
            "metrics_path": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/metrics.json",
            "training_parameter_record_path": (
                f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/training-parameter-record.json"
            ),
            "execution_contract_path": f"contracts/{DATASET_SLUG}/execution-contract.json",
            "preparation_recipe_path": f"contracts/{DATASET_SLUG}/preparation-recipe.json",
            "dataset_path": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.csv",
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": "0" * 64,
            "preparation_recipe_sha256": "1" * 64,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


def _load(tmp_path: Path, release_id: str, payload) -> dict:
    releases_root = tmp_path / "releases"
    _write_metrics_release(releases_root, release_id, payload)
    return public_metrics_loader.load_public_metrics(release_id, releases_root=releases_root)


def _assert_no_internal_leakage(payload) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    for marker in (
        "training_run_identity",
        "path_references",
        "hashes",
        "forecasting_evidence",
        "backtesting_evaluation",
        "fold_summaries",
        "horizon_mae",
        "execution_contract_sha256",
        "preparation_recipe_sha256",
        "seasonal_period",
        "raw_logs",
        "raw_api_payload",
        "/home/",
        "/workspace/",
    ):
        assert marker not in serialized, marker


# ---------------------------------------------------------------------------
# Explicit dispatch
# ---------------------------------------------------------------------------


def test_training_metrics_v4_explicit_dispatch_not_flat_fallback(tmp_path):
    """A v4 payload must be recognized by its own schema_version dispatch,
    never mis-projected via the generic flat/legacy fallback shapes."""
    metrics = _load(tmp_path, "release-v4-001", _v4_metrics_payload())

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "final_holdout"
    assert evaluation["sample_size"] == 12
    assert evaluation["metrics"] == {"mae": 3.1, "rmse": 4.25, "seasonal_mase": 0.87}


# ---------------------------------------------------------------------------
# final_holdout_evaluation is the sole public evaluation source
# ---------------------------------------------------------------------------


def test_final_holdout_selected_never_backtesting_pooled_metrics(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-002",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "mae", "value": 3.1}],
            backtesting_pooled_metrics=[{"name": "mae", "value": 99.9}],
        ),
    )
    assert metrics["evaluation"]["metrics"] == {"mae": 3.1}


def test_split_name_is_deterministic_final_holdout_literal(tmp_path):
    metrics = _load(tmp_path, "release-v4-003", _v4_metrics_payload())
    assert metrics["evaluation"]["split_name"] == "final_holdout"


def test_sample_size_equals_final_holdout_observation_count(tmp_path):
    metrics = _load(
        tmp_path, "release-v4-004", _v4_metrics_payload(final_holdout_observation_count=48)
    )
    assert metrics["evaluation"]["sample_size"] == 48


# ---------------------------------------------------------------------------
# mae/rmse/seasonal_mase 1:1 projection
# ---------------------------------------------------------------------------


def test_mae_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-005",
        _v4_metrics_payload(final_holdout_metrics=[{"name": "mae", "value": 1.25}], primary_metric_id="mae", secondary_metric_ids=[]),
    )
    assert metrics["evaluation"]["metrics"] == {"mae": 1.25}


def test_rmse_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-006",
        _v4_metrics_payload(final_holdout_metrics=[{"name": "rmse", "value": 2.75}], primary_metric_id="rmse", secondary_metric_ids=[]),
    )
    assert metrics["evaluation"]["metrics"] == {"rmse": 2.75}


def test_seasonal_mase_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-007",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "seasonal_mase", "value": 0.65}],
            primary_metric_id="seasonal_mase",
            secondary_metric_ids=[],
        ),
    )
    assert metrics["evaluation"]["metrics"] == {"seasonal_mase": 0.65}


# ---------------------------------------------------------------------------
# primary_metric_id / metric_order: derived from evaluation_policy, never
# dict/declaration order
# ---------------------------------------------------------------------------


def test_primary_metric_id_from_evaluation_policy(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-008",
        _v4_metrics_payload(primary_metric_id="rmse", secondary_metric_ids=["mae", "seasonal_mase"]),
    )
    assert metrics["evaluation"]["primary_metric_id"] == "rmse"


def test_metric_order_follows_policy_primary_then_secondaries_not_declaration_order(tmp_path):
    # final_holdout_metrics are declared rmse/seasonal_mase/mae (deliberately
    # not policy order), proving metric_order is policy-derived, not
    # first-seen-in-list order.
    metrics = _load(
        tmp_path,
        "release-v4-009",
        _v4_metrics_payload(
            final_holdout_metrics=[
                {"name": "rmse", "value": 4.0},
                {"name": "seasonal_mase", "value": 0.9},
                {"name": "mae", "value": 2.0},
            ],
            primary_metric_id="mae",
            secondary_metric_ids=["rmse", "seasonal_mase"],
        ),
    )
    assert metrics["evaluation"]["metric_order"] == ["mae", "rmse", "seasonal_mase"]


def test_metric_order_drops_a_policy_metric_absent_from_final_holdout(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-010",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "mae", "value": 2.0}, {"name": "rmse", "value": 3.0}],
            primary_metric_id="mae",
            secondary_metric_ids=["rmse", "seasonal_mase"],
        ),
    )
    # seasonal_mase is declared in the policy's secondary_metrics but never
    # appears in final_holdout_evaluation.metrics -- it must be dropped, not
    # fabricated as a public metric.
    assert metrics["evaluation"]["metric_order"] == ["mae", "rmse"]
    assert "seasonal_mase" not in metrics["evaluation"]["metrics"]


def test_no_primary_metric_id_when_policy_primary_not_projectable(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-011",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "rmse", "value": 3.0}],
            primary_metric_id="mae",
            secondary_metric_ids=["rmse"],
        ),
    )
    assert metrics["evaluation"]["primary_metric_id"] is None
    assert metrics["evaluation"]["metric_order"] == ["rmse"]


# ---------------------------------------------------------------------------
# Omission behavior
# ---------------------------------------------------------------------------


def test_unknown_metric_name_is_omitted(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-012",
        _v4_metrics_payload(
            final_holdout_metrics=[
                {"name": "mae", "value": 2.0},
                {"name": "mape", "value": 12.0},
                {"name": "smape", "value": 8.0},
            ],
            primary_metric_id="mae",
            secondary_metric_ids=[],
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {"mae": 2.0}
    assert evaluation["metric_order"] == ["mae"]


def test_non_finite_metric_values_are_omitted(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-013",
        _v4_metrics_payload(
            final_holdout_metrics=[
                {"name": "mae", "value": float("nan")},
                {"name": "rmse", "value": float("inf")},
                {"name": "seasonal_mase", "value": float("-inf")},
            ],
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []
    assert evaluation["primary_metric_id"] is None


def test_boolean_metric_values_are_omitted(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-014",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "mae", "value": True}],
            primary_metric_id="mae",
            secondary_metric_ids=[],
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []


def test_zero_value_metric_preserved_as_valid(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v4-015",
        _v4_metrics_payload(
            final_holdout_metrics=[{"name": "mae", "value": 0.0}],
            primary_metric_id="mae",
            secondary_metric_ids=[],
        ),
    )
    assert metrics["evaluation"]["metrics"] == {"mae": 0.0}


# ---------------------------------------------------------------------------
# No private evidence/seasonal-period/fold/horizon leakage
# ---------------------------------------------------------------------------


def test_no_private_evidence_or_path_leakage(tmp_path):
    metrics = _load(tmp_path, "release-v4-016", _v4_metrics_payload())
    _assert_no_internal_leakage({"metrics": metrics})
    evaluation = metrics["evaluation"]
    assert "seasonal_period" not in json.dumps(evaluation)
    assert "backtesting_evaluation" not in json.dumps(evaluation)
    assert "fold_summaries" not in json.dumps(evaluation)
    assert "horizon_mae" not in json.dumps(evaluation)


# ---------------------------------------------------------------------------
# Existing binary (v1), multiclass (v2), and continuous-regression (v3)
# behavior is unaffected by the new v4 dispatch branch.
# ---------------------------------------------------------------------------


def test_existing_binary_training_metrics_v1_behavior_unchanged(tmp_path):
    payload = {
        "schema_version": "training-metrics.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-07-21T12:47:21Z",
        "evidence_policy": {"secrets_prohibited": True},
        "hashes": {"algorithm": "sha256", "execution_contract_sha256": "deadbeef"},
        "metric_source": {"split_name": "evaluation", "split_size": 500, "random_seed": 0},
        "metrics": {
            "primary_metric": {"name": "roc_auc", "value": 0.9},
            "secondary_metrics": [{"name": "f1", "value": 0.8}],
        },
        "path_references": {"dataset_path": "pipeline/prepared/x/prepared-data.csv"},
        "training_run_identity": {"run_id": "train-20260101T000000Z"},
    }
    metrics = _load(tmp_path, "release-binary-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["primary_metric_id"] == "roc_auc"
    assert evaluation["metrics"] == {"roc_auc": 0.9, "f1_score": 0.8}


def test_existing_continuous_regression_training_metrics_v3_behavior_unchanged(tmp_path):
    payload = {
        "schema_version": "training-metrics.v3",
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "final_test_evaluation": {
            "partition_role": "test",
            "completed": True,
            "row_count": 50,
            "metrics": [{"name": "r2", "value": 0.81}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "metrics": [{"name": "r2", "value": 0.77}],
        },
    }
    metrics = _load(tmp_path, "release-regression-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["metrics"] == {"r2": 0.81}
    assert evaluation["primary_metric_id"] is None
