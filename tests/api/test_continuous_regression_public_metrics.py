"""Project Spec S0227: continuous-regression public metrics projection.

Covers `api/public_metrics_loader.py`'s new explicit `training-metrics.v3`
schema-version dispatch (mirroring the existing native multiclass
`training-metrics.v2` dispatch pattern): partition selection (completed
final test preferred, else validation), bounded r2/mae/rmse projection,
unknown/non-finite/boolean metric omission, deterministic metric order, no
`primary_metric_id` fabrication, and no private evidence leakage. All
fixtures are synthetic, written under `tmp_path`-backed temporary release
directories -- never the real repository `releases/` tree.

Existing binary (training-metrics.v1) and multiclass (training-metrics.v2)
public metrics behavior is exercised too, to prove this addition is purely
additive.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
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

DATASET_SLUG = "example-continuous-dataset"
RUN_ID = "train-20260819T000000Z"


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


def _v3_metrics_payload(
    *,
    final_test_completed: bool = True,
    final_test_metrics: list | None = None,
    validation_metrics: list | None = None,
    final_test_split_name: str = "test",
    validation_split_name: str = "validation",
    final_test_row_count: int = 50,
    validation_row_count: int = 40,
    include_final_test: bool = True,
) -> dict:
    if final_test_metrics is None:
        final_test_metrics = [
            {"name": "r2", "value": 0.81},
            {"name": "mae", "value": 3.2},
            {"name": "rmse", "value": 4.5},
        ]
    if validation_metrics is None:
        validation_metrics = [
            {"name": "r2", "value": 0.77},
            {"name": "mae", "value": 3.6},
            {"name": "rmse", "value": 4.9},
        ]
    payload = {
        "schema_version": "training-metrics.v3",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": RUN_ID,
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/",
        },
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "validation_evaluation": {
            "partition_role": validation_split_name,
            "row_count": validation_row_count,
            "used_for_fitting": False,
            "used_for_model_selection": False,
            "used_for_hyperparameter_selection": False,
            "sealed_before_finalization": False,
            "evaluation_count": 1,
            "metrics": validation_metrics,
        },
        "path_references": {
            "metrics_path": f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/metrics.json",
            "training_parameter_record_path": (
                f"pipeline/training-runs/{DATASET_SLUG}/{RUN_ID}/training-parameter-record.json"
            ),
            "execution_contract_path": f"contracts/{DATASET_SLUG}/execution-contract.json",
            "dataset_path": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.csv",
        },
        "hashes": {"algorithm": "sha256", "execution_contract_sha256": "0" * 64},
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "raw_artifact_contents_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }
    if include_final_test:
        payload["final_test_evaluation"] = {
            "partition_role": final_test_split_name,
            "row_count": final_test_row_count,
            "used_for_fitting": False,
            "used_for_model_selection": False,
            "used_for_decision_rule_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": True,
            "completed": final_test_completed,
            "evaluation_count": 1 if final_test_completed else 0,
            "metrics": final_test_metrics if final_test_completed else [],
        }
    return payload


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
        "regression_evidence",
        "execution_contract_sha256",
        "raw_logs",
        "raw_api_payload",
        "/home/",
        "/workspace/",
    ):
        assert marker not in serialized, marker


# ---------------------------------------------------------------------------
# Explicit dispatch
# ---------------------------------------------------------------------------


def test_training_metrics_v3_explicit_dispatch_not_flat_fallback(tmp_path):
    """A v3 payload must be recognized by its own schema_version dispatch,
    never mis-projected via the generic flat/legacy fallback shapes (which
    would yield an empty metrics dict/None split_name for this payload
    shape, since none of its top-level keys are a recognized flat metric
    name)."""
    metrics = _load(tmp_path, "release-v3-001", _v3_metrics_payload())

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["sample_size"] == 50
    assert evaluation["metrics"] == {"r2": 0.81, "mae": 3.2, "rmse": 4.5}
    assert evaluation["metric_order"] == ["r2", "mae", "rmse"]


# ---------------------------------------------------------------------------
# Partition selection
# ---------------------------------------------------------------------------


def test_completed_final_test_preferred_over_validation(tmp_path):
    metrics = _load(tmp_path, "release-v3-002", _v3_metrics_payload(final_test_completed=True))

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["sample_size"] == 50
    assert evaluation["metrics"]["r2"] == 0.81


def test_validation_fallback_when_final_test_incomplete(tmp_path):
    metrics = _load(tmp_path, "release-v3-003", _v3_metrics_payload(final_test_completed=False))

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "validation"
    assert evaluation["sample_size"] == 40
    assert evaluation["metrics"]["r2"] == 0.77


def test_validation_fallback_when_final_test_absent(tmp_path):
    metrics = _load(
        tmp_path, "release-v3-004", _v3_metrics_payload(include_final_test=False)
    )

    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "validation"
    assert evaluation["metrics"]["mae"] == 3.6


# ---------------------------------------------------------------------------
# r2/mae/rmse 1:1 projection
# ---------------------------------------------------------------------------


def test_r2_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-005",
        _v3_metrics_payload(final_test_metrics=[{"name": "r2", "value": 0.5}]),
    )
    assert metrics["evaluation"]["metrics"] == {"r2": 0.5}


def test_mae_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-006",
        _v3_metrics_payload(final_test_metrics=[{"name": "mae", "value": 1.25}]),
    )
    assert metrics["evaluation"]["metrics"] == {"mae": 1.25}


def test_rmse_projects_1_to_1(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-007",
        _v3_metrics_payload(final_test_metrics=[{"name": "rmse", "value": 2.75}]),
    )
    assert metrics["evaluation"]["metrics"] == {"rmse": 2.75}


# ---------------------------------------------------------------------------
# Omission behavior
# ---------------------------------------------------------------------------


def test_unknown_metric_name_is_omitted(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-008",
        _v3_metrics_payload(
            final_test_metrics=[
                {"name": "r2", "value": 0.6},
                {"name": "mape", "value": 12.0},
                {"name": "explained_variance", "value": 0.6},
            ]
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {"r2": 0.6}
    assert evaluation["metric_order"] == ["r2"]


def test_non_finite_metric_values_are_omitted(tmp_path):
    # Written via json.dumps default (allow_nan=True) -- NaN/Infinity are
    # not standard JSON but Python's json module both emits and parses them
    # by default, exercising the exact malformed-value boundary a
    # hand-authored or buggy upstream v3 artifact could still produce.
    metrics = _load(
        tmp_path,
        "release-v3-009",
        _v3_metrics_payload(
            final_test_metrics=[
                {"name": "r2", "value": float("nan")},
                {"name": "mae", "value": float("inf")},
                {"name": "rmse", "value": float("-inf")},
            ]
        ),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []


def test_boolean_metric_values_are_omitted(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-010",
        _v3_metrics_payload(final_test_metrics=[{"name": "r2", "value": True}]),
    )
    evaluation = metrics["evaluation"]
    assert evaluation["metrics"] == {}
    assert evaluation["metric_order"] == []


# ---------------------------------------------------------------------------
# Deterministic order / no primary-metric fabrication / no leakage
# ---------------------------------------------------------------------------


def test_metric_order_is_deterministic_first_seen(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-011",
        _v3_metrics_payload(
            final_test_metrics=[
                {"name": "rmse", "value": 4.0},
                {"name": "r2", "value": 0.7},
                {"name": "mae", "value": 2.0},
            ]
        ),
    )
    assert metrics["evaluation"]["metric_order"] == ["rmse", "r2", "mae"]


def test_no_primary_metric_id_fabrication(tmp_path):
    metrics = _load(tmp_path, "release-v3-012", _v3_metrics_payload())
    assert metrics["evaluation"]["primary_metric_id"] is None


def test_no_private_evidence_or_path_leakage(tmp_path):
    metrics = _load(tmp_path, "release-v3-013", _v3_metrics_payload())
    _assert_no_internal_leakage({"metrics": metrics})


def test_zero_value_metric_preserved_as_valid(tmp_path):
    metrics = _load(
        tmp_path,
        "release-v3-014",
        _v3_metrics_payload(final_test_metrics=[{"name": "mae", "value": 0.0}]),
    )
    assert metrics["evaluation"]["metrics"] == {"mae": 0.0}


# ---------------------------------------------------------------------------
# Existing binary (training-metrics.v1) and multiclass (training-metrics.v2)
# behavior is unaffected by the new v3 dispatch branch.
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
    assert evaluation["metric_order"] == ["roc_auc", "f1_score"]


def test_existing_multiclass_training_metrics_v2_behavior_unchanged(tmp_path):
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
    metrics = _load(tmp_path, "release-multiclass-001", payload)
    evaluation = metrics["evaluation"]
    assert evaluation["split_name"] == "test"
    assert evaluation["metrics"] == {"f1_macro": 0.9}
    assert evaluation["primary_metric_id"] is None
