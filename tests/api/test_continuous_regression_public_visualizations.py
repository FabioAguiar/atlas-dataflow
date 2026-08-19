"""Dedicated Project Spec S0228 tests for the public visualizations loader's
`analytical-visualizations.v3` continuous-regression projection
(`api/public_visualizations_loader.py`).

Covers, using only synthetic temporary release packages (never a real
release, never `dataset-study-*`):

  * a bounded, well-formed public v3 projection -- charts, dataset_statistics
    derived from the continuous target histogram, the explicit
    `target_distribution_kind` discriminator, and a bounded
    `regression_diagnostics` shape containing only what the UI needs;
  * malformed v3 evidence fails closed to the existing bounded unavailable
    state, never a partial/unsafe projection;
  * classification (v1/v2) public projection remains fully backward
    compatible and never carries the v3-only discriminator/diagnostics
    fields.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import public_visualizations_loader as loader  # noqa: E402

DATASET_SLUG = "synthetic-regression-release"


def _write_release(releases_root: Path, release_name: str, visualizations_artifact: dict) -> Path:
    release_dir = releases_root / release_name
    artifact_path = release_dir / "visualizations" / "visualizations.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(visualizations_artifact), encoding="utf-8")

    manifest = {
        "artifacts": [{"role": "visualizations", "reference": "visualizations/visualizations.json"}],
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return release_dir


def _valid_v3_artifact(**overrides) -> dict:
    payload = {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "training_run_identity": {
            "dataset_slug": DATASET_SLUG,
            "run_id": "train-20260819T000000Z",
            "output_directory": f"pipeline/training-runs/{DATASET_SLUG}/train-20260819T000000Z/",
        },
        "regression_evidence": {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        },
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "outcome", "y_label": "Rows",
                "data": [
                    {"name": "0 to 10", "value": 6},
                    {"name": "10 to 20", "value": 4},
                ],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "feature_a", "value": 0.9}, {"name": "feature_b", "value": 0.1}],
            },
        ],
        "target_distribution_method": {
            "distribution_kind": "continuous_histogram",
            "population_kind": "prepared_dataset",
            "binning_method": "deterministic_equal_width",
            "row_count": 10,
            "target_column": "outcome",
            "bin_count": 2,
            "min_value": 1.0,
            "max_value": 19.0,
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 2,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "actual_vs_predicted": {
            "partition_role": "test",
            "evaluation_count": 1,
            "aggregation_method": "deterministic_equal_width_actual_bins",
            "reference_line": "identity",
            "points": [
                {"actual_mean": 5.0, "predicted_mean": 5.4, "count": 3, "bin_lower": 0.0, "bin_upper": 10.0},
                {"actual_mean": 15.0, "predicted_mean": 14.2, "count": 2, "bin_lower": 10.0, "bin_upper": 20.0},
            ],
        },
        "residual_distribution": {
            "partition_role": "test",
            "evaluation_count": 1,
            "residual_definition": "actual_minus_predicted",
            "binning_method": "deterministic_equal_width",
            "bins": [
                {"label": "-2 to 0", "lower_bound": -2.0, "upper_bound": 0.0, "count": 2},
                {"label": "0 to 2", "lower_bound": 0.0, "upper_bound": 2.0, "count": 3},
            ],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bounded, well-formed public v3 projection
# ---------------------------------------------------------------------------


def test_v3_projection_contains_charts_dataset_statistics_and_discriminator():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-001", _valid_v3_artifact())

        projection = loader.load_public_visualizations("release-v3-001", releases_root=releases_root)

        assert [chart["id"] for chart in projection["charts"]] == ["target_distribution", "feature_importance"]
        assert projection["dataset_statistics"] == {"instance_count": 10}
        assert projection["target_distribution_kind"] == "continuous_histogram"
        assert "confusion_matrix" not in projection


def test_v3_projection_regression_diagnostics_is_bounded_and_count_complete():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-002", _valid_v3_artifact())

        projection = loader.load_public_visualizations("release-v3-002", releases_root=releases_root)

        diagnostics = projection["regression_diagnostics"]
        assert set(diagnostics) == {"actual_vs_predicted", "residual_distribution"}

        actual_vs_predicted = diagnostics["actual_vs_predicted"]
        assert set(actual_vs_predicted) == {"points"}
        for point in actual_vs_predicted["points"]:
            assert set(point) == {"actual_mean", "predicted_mean", "count"}

        residual_distribution = diagnostics["residual_distribution"]
        assert set(residual_distribution) == {"bins"}
        for bin_ in residual_distribution["bins"]:
            assert set(bin_) == {"label", "count"}


def test_v3_projection_never_leaks_training_run_identity_or_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-003", _valid_v3_artifact())

        projection = loader.load_public_visualizations("release-v3-003", releases_root=releases_root)
        serialized = json.dumps(projection)

        for forbidden in ("training_run_identity", "output_directory", "run_id", "aggregation_method", "bin_lower", "bin_upper", "lower_bound", "upper_bound"):
            assert forbidden not in serialized


# ---------------------------------------------------------------------------
# Malformed v3 evidence fails closed
# ---------------------------------------------------------------------------


def test_v3_missing_actual_vs_predicted_fails_closed():
    artifact = _valid_v3_artifact()
    del artifact["actual_vs_predicted"]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-004", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-004", releases_root=releases_root)


def test_v3_wrong_partition_role_fails_closed():
    artifact = _valid_v3_artifact()
    artifact["actual_vs_predicted"]["partition_role"] = "validation"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-005", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-005", releases_root=releases_root)


def test_v3_non_finite_diagnostic_value_fails_closed():
    # Python's json module emits/parses bare Infinity/NaN tokens by default
    # (a non-standard JSON extension), so writing float("inf") through the
    # same _write_release helper still round-trips into a real non-finite
    # float the loader must reject.
    artifact = _valid_v3_artifact()
    artifact["actual_vs_predicted"]["points"][0]["actual_mean"] = float("inf")
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-006", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-006", releases_root=releases_root)


def test_v3_zero_count_point_fails_closed():
    artifact = _valid_v3_artifact()
    artifact["actual_vs_predicted"]["points"][0]["count"] = 0
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-007", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-007", releases_root=releases_root)


def test_v3_negative_residual_count_fails_closed():
    artifact = _valid_v3_artifact()
    artifact["residual_distribution"]["bins"][0]["count"] = -1
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-008", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-008", releases_root=releases_root)


def test_v3_wrong_residual_definition_fails_closed():
    artifact = _valid_v3_artifact()
    artifact["residual_distribution"]["residual_definition"] = "predicted_minus_actual"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-009", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-009", releases_root=releases_root)


def test_v3_empty_points_fails_closed():
    artifact = _valid_v3_artifact()
    artifact["actual_vs_predicted"]["points"] = []
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-010", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            loader.load_public_visualizations("release-v3-010", releases_root=releases_root)


# ---------------------------------------------------------------------------
# Classification (v1/v2) public projection regression safety
# ---------------------------------------------------------------------------


def _classification_v1_artifact() -> dict:
    return {
        "schema_version": "analytical-visualizations.v1",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "Churn", "y_label": "Customers",
                "data": [{"name": "No", "value": 7}, {"name": "Yes", "value": 3}],
            },
            {
                "id": "feature_importance", "title": "Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "tenure", "value": 0.5}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset", "row_count": 10, "target_column": "Churn",
        },
        "feature_importance_method": {
            "model_family": "gradient_boosting",
            "source": "estimator.feature_importances_",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }


def test_classification_v1_projection_remains_backward_compatible():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v1-001", _classification_v1_artifact())

        projection = loader.load_public_visualizations("release-v1-001", releases_root=releases_root)

        assert [chart["id"] for chart in projection["charts"]] == ["target_distribution", "feature_importance"]
        assert projection["dataset_statistics"] == {"instance_count": 10}


def test_classification_v1_projection_never_carries_v3_only_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v1-002", _classification_v1_artifact())

        projection = loader.load_public_visualizations("release-v1-002", releases_root=releases_root)

        assert "target_distribution_kind" not in projection
        assert "regression_diagnostics" not in projection


def test_classification_v2_multiclass_projection_never_carries_v3_only_fields():
    ordered_class_ids = ["setosa", "versicolor", "virginica"]
    artifact = {
        "schema_version": "analytical-visualizations.v2",
        "artifact_kind": "analytical_visualizations",
        "created_at": "2026-08-19T00:00:00Z",
        "classification_evidence": {"problem_type": "multiclass_classification", "ordered_class_ids": ordered_class_ids},
        "charts": [
            {
                "id": "target_distribution", "title": "Target Distribution", "type": "bar",
                "x_label": "Class", "y_label": "Rows",
                "data": [{"name": cid, "value": 10} for cid in ordered_class_ids],
            },
            {
                "id": "feature_importance", "title": "HGB Feature Importance", "type": "bar",
                "x_label": "Feature", "y_label": "Importance",
                "data": [{"name": "petal_length", "value": 1.0}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset", "row_count": 30, "target_column": "Class",
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "sklearn.inspection.permutation_importance",
            "method": "permutation_importance",
            "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10,
        },
        "confusion_matrix": {
            "ordered_class_ids": ordered_class_ids,
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "row_axis": "true_class",
            "column_axis": "predicted_class",
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True, "secrets_prohibited": True,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v2-001", artifact)

        projection = loader.load_public_visualizations("release-v2-001", releases_root=releases_root)

        assert "target_distribution_kind" not in projection
        assert "regression_diagnostics" not in projection
        assert projection["confusion_matrix"]["ordered_class_ids"] == ordered_class_ids
