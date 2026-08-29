"""Project Spec S0279: native binary v5 public metrics projection.

Covers `api/public_metrics_loader.py`'s new explicit `training-metrics.v5`
schema-version dispatch (mirroring the existing native multiclass
`training-metrics.v2` / continuous-regression `training-metrics.v3`
dispatch pattern): partition selection (completed final test preferred,
else validation), bounded roc_auc/f1/pr_auc projection through the existing
public metric normalization, unknown/non-finite/boolean metric omission,
deterministic metric order, no `primary_metric_id` fabrication, and no
private classification/path/hash/evidence leakage.

All fixtures are synthetic, written under `tmp_path`-backed temporary
release directories -- never the checked-in Telco release, never the real
repository `releases/` tree. Synthetic validation and final-test values
differ so a partition-selection mistake is observable.

Existing external binary (training-metrics.external-fitted-model.v1),
native multiclass (v2), continuous regression (v3), and univariate
forecasting (v4) public metrics behavior is exercised too, to prove this
addition is purely additive.
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
# from within this test package -- importing the module directly (the same
# convention the neighboring public-loader tests already use) avoids that.
import public_metrics_loader  # noqa: E402

DATASET_SLUG = "example-native-binary-dataset"
RUN_ID = "train-20260829T113102Z"


def _write_release(release_dir: Path, *, artifacts: list) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "release-manifest.v1",
        "manifest_kind": "release_manifest",
        "artifacts": artifacts,
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_metrics_release(releases_root: Path, release_id: str, metrics_payload) -> None:
    release_dir = releases_root / release_id
    _write_release(
        release_dir,
        artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
    )
    path = release_dir / "metrics" / "metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics_payload), encoding="utf-8")


def _v5_metrics_payload(
    *,
    final_test_completed: bool = True,
    include_final_test: bool = True,
    final_test_metrics: list | None = None,
    validation_metrics: list | None = None,
    final_test_partition_role: str = "test",
    validation_partition_role: str = "validation",
    final_test_row_count: int = 1057,
    validation_row_count: int = 1056,
) -> dict:
    if final_test_metrics is None:
        final_test_metrics = [
            {"name": "roc_auc", "value": 0.8544777488351616},
            {"name": "f1", "value": 0.6129666011787819},
            {"name": "pr_auc", "value": 0.6768447384115979},
        ]
    if validation_metrics is None:
        # Deliberately different values from the final-test partition so a
        # selection mistake is observable in an assertion.
        validation_metrics = [
            {"name": "roc_auc", "value": 0.8385240243004419},
            {"name": "f1", "value": 0.5702479338842975},
            {"name": "pr_auc", "value": 0.6516513774293536},
        ]
    payload = {
        "schema_version": "training-metrics.v5",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-29T11:31:02.420472Z",
        "classification_evidence": {
            "positive_class_id": "Yes",
            "problem_type": "binary_classification",
            "result_semantics_schema_version": "binary-result-semantics.v1",
        },
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": RUN_ID,
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/",
        },
        "path_references": {
            "dataset_path": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.csv",
            "execution_contract_path": f"contracts/{DATASET_SLUG}/execution-contract.json",
            "metrics_path": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/metrics.json",
            "training_parameter_record_path": (
                f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/training-parameter-record.json"
            ),
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": "60aa94d814cfff1d08a6db0a3fad32b25d4a7453d8c15200d6e370abca5d0635",
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "reduced_and_sanitized": True,
        },
        "validation_evaluation": {
            "partition_role": validation_partition_role,
            "row_count": validation_row_count,
            "evaluation_count": 1,
            "sealed_before_finalization": False,
            "used_for_fitting": False,
            "used_for_hyperparameter_selection": False,
            "used_for_model_selection": False,
            "used_for_threshold_selection": False,
            "metrics": validation_metrics,
        },
    }
    if include_final_test:
        payload["final_test_evaluation"] = {
            "partition_role": final_test_partition_role,
            "row_count": final_test_row_count,
            "completed": final_test_completed,
            "evaluation_count": 1 if final_test_completed else 0,
            "sealed_before_finalization": True,
            "used_for_fitting": False,
            "used_for_hyperparameter_selection": False,
            "used_for_model_selection": False,
            "used_for_threshold_selection": False,
            "metrics": final_test_metrics if final_test_completed else [],
        }
    return payload


def _load_metrics(tmp_path: Path, release_id: str, payload) -> dict:
    releases_root = tmp_path / "releases"
    _write_metrics_release(releases_root, release_id, payload)
    return public_metrics_loader.load_public_metrics(release_id, releases_root=releases_root)


def _assert_no_internal_leakage(payload) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    for marker in (
        "classification_evidence",
        "positive_class_id",
        "training_run_identity",
        "path_references",
        "hashes",
        "execution_contract_sha256",
        "evidence_policy",
        "output_directory",
        "run_id",
        "raw_logs",
        "/home/",
        "/workspace/",
        "pipeline/training-runs",
    ):
        assert marker not in serialized, marker


# ---------------------------------------------------------------------------
# Explicit dispatch
# ---------------------------------------------------------------------------


def test_training_metrics_v5_explicit_dispatch_not_flat_fallback(tmp_path):
    """A v5 payload must be recognized by its own schema_version dispatch,
    never mis-projected via the generic flat/legacy fallback shapes (which
    would yield an empty metrics dict and a None split_name for this payload
    shape)."""
    metrics = _load_metrics(tmp_path, "release-v5-001", _v5_metrics_payload())

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["sample_size"] == 1057
    assert evaluation["metrics"] == {
        "roc_auc": 0.8544777488351616,
        "f1_score": 0.6129666011787819,
        "pr_auc": 0.6768447384115979,
    }
    assert evaluation["metric_order"] == ["roc_auc", "f1_score", "pr_auc"]


# ---------------------------------------------------------------------------
# Partition selection
# ---------------------------------------------------------------------------


def test_completed_final_test_preferred_over_validation(tmp_path):
    metrics = _load_metrics(
        tmp_path, "release-v5-002", _v5_metrics_payload(final_test_completed=True)
    )
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["sample_size"] == 1057
    assert evaluation["metrics"]["roc_auc"] == 0.8544777488351616


def test_final_test_split_name_is_test(tmp_path):
    metrics = _load_metrics(tmp_path, "release-v5-003", _v5_metrics_payload())
    assert metrics["evaluation"]["split_name"] == "test"


def test_sample_size_comes_from_selected_row_count(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-004",
        _v5_metrics_payload(final_test_row_count=812, validation_row_count=640),
    )
    assert metrics["evaluation"]["sample_size"] == 812


def test_validation_fallback_when_final_test_not_completed(tmp_path):
    metrics = _load_metrics(
        tmp_path, "release-v5-005", _v5_metrics_payload(final_test_completed=False)
    )
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "validation"
    assert evaluation["sample_size"] == 1056
    assert evaluation["metrics"]["roc_auc"] == 0.8385240243004419


def test_validation_fallback_when_final_test_absent(tmp_path):
    metrics = _load_metrics(
        tmp_path, "release-v5-006", _v5_metrics_payload(include_final_test=False)
    )
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "validation"
    assert evaluation["metrics"]["f1_score"] == 0.5702479338842975


def test_completed_flag_must_be_exactly_true(tmp_path):
    """A truthy-but-not-True `completed` (e.g. the string "true") is not the
    sealed completion signal and must fall back to validation."""
    payload = _v5_metrics_payload()
    payload["final_test_evaluation"]["completed"] = "true"
    metrics = _load_metrics(tmp_path, "release-v5-007", payload)
    assert metrics["evaluation"]["split_name"] == "validation"


# ---------------------------------------------------------------------------
# Bounded roc_auc/f1/pr_auc projection + omission behavior
# ---------------------------------------------------------------------------


def test_roc_auc_f1_pr_auc_project_with_deterministic_order(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-008",
        _v5_metrics_payload(
            final_test_metrics=[
                {"name": "pr_auc", "value": 0.61},
                {"name": "roc_auc", "value": 0.85},
                {"name": "f1", "value": 0.62},
            ]
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {"pr_auc": 0.61, "roc_auc": 0.85, "f1_score": 0.62}
    assert evaluation["metric_order"] == ["pr_auc", "roc_auc", "f1_score"]


def test_unknown_metric_name_is_omitted(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-009",
        _v5_metrics_payload(
            final_test_metrics=[
                {"name": "roc_auc", "value": 0.85},
                {"name": "brier_score", "value": 0.12},
                {"name": "ks_statistic", "value": 0.44},
            ]
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {"roc_auc": 0.85}
    assert evaluation["metric_order"] == ["roc_auc"]


def test_boolean_metric_value_is_omitted(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-010",
        _v5_metrics_payload(final_test_metrics=[{"name": "roc_auc", "value": True}]),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []


def test_non_finite_metric_values_are_omitted(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-011",
        _v5_metrics_payload(
            final_test_metrics=[
                {"name": "roc_auc", "value": float("nan")},
                {"name": "f1", "value": float("inf")},
                {"name": "pr_auc", "value": float("-inf")},
            ]
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []


def test_zero_value_metric_preserved_as_valid(tmp_path):
    metrics = _load_metrics(
        tmp_path,
        "release-v5-012",
        _v5_metrics_payload(final_test_metrics=[{"name": "f1", "value": 0.0}]),
    )
    assert metrics["evaluation"]["metrics"] == {"f1_score": 0.0}


# ---------------------------------------------------------------------------
# No primary-metric fabrication / no private evidence leakage
# ---------------------------------------------------------------------------


def test_primary_metric_id_remains_null(tmp_path):
    metrics = _load_metrics(tmp_path, "release-v5-013", _v5_metrics_payload())
    assert metrics["evaluation"]["primary_metric_id"] is None


def test_private_classification_path_hash_evidence_fields_do_not_appear(tmp_path):
    metrics = _load_metrics(tmp_path, "release-v5-014", _v5_metrics_payload())
    _assert_no_internal_leakage(metrics)
    assert set(metrics["evaluation"]) == {
        "split_name",
        "sample_size",
        "primary_metric_id",
        "metrics",
        "metric_order",
    }


def test_v5_evaluation_never_carries_per_class_metrics(tmp_path):
    metrics = _load_metrics(tmp_path, "release-v5-015", _v5_metrics_payload())
    assert "per_class_metrics" not in metrics["evaluation"]


# ---------------------------------------------------------------------------
# Historical profiles remain unchanged (purely additive dispatch branch)
# ---------------------------------------------------------------------------


def test_existing_external_binary_v1_public_metrics_still_work(tmp_path):
    payload = {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "final_test_evaluation": {
            "partition_role": "final_test",
            "row_count": 200,
            "completed": True,
            "metrics": [
                {"name": "roc_auc", "value": 0.91},
                {"name": "f1", "value": 0.83},
            ],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "row_count": 150,
            "metrics": [{"name": "roc_auc", "value": 0.88}],
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "metrics": [{"name": "roc_auc", "value": 0.99}],
        },
    }
    metrics = _load_metrics(tmp_path, "release-ext-v1-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "final_test"
    assert evaluation["metrics"] == {"roc_auc": 0.91, "f1_score": 0.83}
    assert evaluation["primary_metric_id"] is None


def test_existing_native_multiclass_v2_public_metrics_still_work(tmp_path):
    payload = {
        "schema_version": "training-metrics.v2",
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": ["a", "b", "c"],
        },
        "final_test_evaluation": {
            "partition_role": "test",
            "completed": True,
            "metrics": [{"name": "f1_macro", "value": 0.9}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "metrics": [{"name": "f1_macro", "value": 0.85}],
        },
    }
    metrics = _load_metrics(tmp_path, "release-mc-v2-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["metrics"] == {"f1_macro": 0.9}
    assert evaluation["primary_metric_id"] is None


def test_existing_continuous_regression_v3_public_metrics_still_work(tmp_path):
    payload = {
        "schema_version": "training-metrics.v3",
        "final_test_evaluation": {
            "partition_role": "test",
            "row_count": 50,
            "completed": True,
            "metrics": [
                {"name": "r2", "value": 0.81},
                {"name": "mae", "value": 3.2},
                {"name": "rmse", "value": 4.5},
            ],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "row_count": 40,
            "metrics": [{"name": "r2", "value": 0.77}],
        },
    }
    metrics = _load_metrics(tmp_path, "release-reg-v3-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["metrics"] == {"r2": 0.81, "mae": 3.2, "rmse": 4.5}
    assert evaluation["metric_order"] == ["r2", "mae", "rmse"]


def test_existing_forecasting_v4_public_metrics_still_work(tmp_path):
    payload = {
        "schema_version": "training-metrics.v4",
        "final_holdout_evaluation": {
            "observation_count": 24,
            "metrics": [
                {"name": "mae", "value": 12.0},
                {"name": "rmse", "value": 15.0},
                {"name": "seasonal_mase", "value": 0.8},
            ],
        },
        "evaluation_policy": {
            "primary_metric": {"metric_id": "seasonal_mase"},
            "secondary_metrics": [{"metric_id": "mae"}, {"metric_id": "rmse"}],
        },
    }
    metrics = _load_metrics(tmp_path, "release-fc-v4-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "final_holdout"
    assert evaluation["sample_size"] == 24
    assert evaluation["primary_metric_id"] == "seasonal_mase"
    assert evaluation["metric_order"] == ["seasonal_mase", "mae", "rmse"]
