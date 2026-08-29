"""Project Spec S0279: native binary v5 public visualizations projection.

Covers `api/public_visualizations_loader.py`'s new explicit admission of
`analytical-visualizations.v5` (Atlas-native binary fixed-configuration,
Project Specs S0258/S0259) to the existing canonical classification-chart
path -- no separate public chart shape is introduced.

Proves, using only synthetic temporary release packages (never a real
release, never the checked-in Telco release):

  * a valid v5 artifact projects exactly the canonical two-chart shape
    (Target Distribution, Feature Importance) with the identical bounded
    fields as v1/v2/v3;
  * `dataset_statistics.instance_count` is derived by the existing S0205
    prepared-dataset authority (Target Distribution total == row_count),
    never from metrics or another source;
  * a row-count / chart-total contradiction does not fabricate an instance
    count;
  * v5-only internal evidence/provenance (classification_evidence,
    target_distribution_method, feature_importance_method,
    training_run_identity, evidence_policy, created_at, model family,
    permutation-importance source, random-seed source, internal paths) is
    never exposed;
  * no confusion_matrix, target_distribution_kind, regression_diagnostics,
    forecasting_diagnostics, or forecasting_evaluation is fabricated for a
    binary v5 artifact;
  * a malformed canonical chart structure / unsupported artifact_kind fails
    closed to the existing bounded unavailable state;
  * historical v1 / external v1 / internal v2 / v3 projections remain
    unchanged.
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

DATASET_SLUG = "synthetic-native-binary-release"
RUN_ID = "train-20260829T113102Z"


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


def _valid_v5_artifact(**overrides) -> dict:
    payload = {
        "schema_version": "analytical-visualizations.v5",
        "artifact_kind": "analytical_visualizations",
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
        "charts": [
            {
                "id": "target_distribution",
                "title": "Target Distribution",
                "type": "bar",
                "x_label": "Churn",
                "y_label": "Rows",
                "data": [
                    {"name": "No", "value": 40},
                    {"name": "Yes", "value": 10},
                ],
            },
            {
                "id": "feature_importance",
                "title": "Feature Importance",
                "type": "bar",
                "x_label": "Feature",
                "y_label": "Importance",
                "data": [
                    {"name": "Contract", "value": 0.4176368604181857},
                    {"name": "tenure", "value": 0.2514942159613379},
                    {"name": "MonthlyCharges", "value": 0.09452636800431503},
                ],
            },
        ],
        "target_distribution_method": {
            "population_kind": "prepared_dataset",
            "row_count": 50,
            "target_column": "Churn",
        },
        "feature_importance_method": {
            "method": "permutation_importance",
            "model_family": "hist_gradient_boosting",
            "n_repeats": 5,
            "omitted_source_feature_count": 9,
            "population_kind": "finalized_fit_population",
            "public_row_limit": 10,
            "random_seed_source": "execution_contract.random_seed",
            "scoring": "roc_auc",
            "source": "sklearn.inspection.permutation_importance",
            "total_source_feature_count": 19,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False,
            "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }
    payload.update(overrides)
    return payload


def _load_viz(releases_root: Path, release_id: str) -> dict:
    return loader.load_public_visualizations(release_id, releases_root=releases_root)


# ---------------------------------------------------------------------------
# Valid v5 -> canonical two-chart projection + S0205 instance count
# ---------------------------------------------------------------------------


def test_valid_v5_returns_canonical_two_chart_projection():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-001", _valid_v5_artifact())

        projection = _load_viz(releases_root, "release-v5-001")

        assert [chart["id"] for chart in projection["charts"]] == [
            "target_distribution",
            "feature_importance",
        ]
        for chart in projection["charts"]:
            assert set(chart) == {"id", "title", "type", "x_label", "y_label", "data"}
            for point in chart["data"]:
                assert set(point) == {"name", "value"}


def test_valid_v5_dataset_statistics_instance_count_is_derived_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-002", _valid_v5_artifact())

        projection = _load_viz(releases_root, "release-v5-002")

        assert projection["dataset_statistics"] == {"instance_count": 50}


def test_row_count_chart_total_contradiction_does_not_fabricate_dataset_statistics():
    artifact = _valid_v5_artifact()
    # Chart total is 50; declare a contradictory row_count.
    artifact["target_distribution_method"]["row_count"] = 7043
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-003", artifact)

        projection = _load_viz(releases_root, "release-v5-003")

        assert "dataset_statistics" not in projection
        assert [chart["id"] for chart in projection["charts"]] == [
            "target_distribution",
            "feature_importance",
        ]


def test_instance_count_is_not_derived_from_metrics_when_population_kind_missing():
    artifact = _valid_v5_artifact()
    del artifact["target_distribution_method"]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-004", artifact)

        projection = _load_viz(releases_root, "release-v5-004")

        assert "dataset_statistics" not in projection


# ---------------------------------------------------------------------------
# No v5 internal evidence / provenance leakage
# ---------------------------------------------------------------------------


def test_valid_v5_projection_never_leaks_internal_evidence_or_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-005", _valid_v5_artifact())

        projection = _load_viz(releases_root, "release-v5-005")
        serialized = json.dumps(projection)

        for forbidden in (
            "classification_evidence",
            "positive_class_id",
            "target_distribution_method",
            "feature_importance_method",
            "training_run_identity",
            "evidence_policy",
            "created_at",
            "hist_gradient_boosting",
            "permutation_importance",
            "sklearn.inspection.permutation_importance",
            "random_seed_source",
            "execution_contract.random_seed",
            "output_directory",
            "run_id",
            "pipeline/training-runs",
        ):
            assert forbidden not in serialized, forbidden

        assert set(projection) == {"charts", "dataset_statistics"}


def test_valid_v5_projection_carries_no_problem_specific_extra_fields():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-006", _valid_v5_artifact())

        projection = _load_viz(releases_root, "release-v5-006")

        assert "confusion_matrix" not in projection
        assert "target_distribution_kind" not in projection
        assert "regression_diagnostics" not in projection
        assert "forecasting_diagnostics" not in projection
        assert "forecasting_evaluation" not in projection


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------


def test_v5_missing_feature_importance_chart_fails_closed():
    artifact = _valid_v5_artifact()
    artifact["charts"] = [artifact["charts"][0]]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-007", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            _load_viz(releases_root, "release-v5-007")


def test_v5_malformed_chart_data_point_fails_closed():
    artifact = _valid_v5_artifact()
    artifact["charts"][0]["data"][0]["value"] = -1
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-008", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            _load_viz(releases_root, "release-v5-008")


def test_v5_unsupported_artifact_kind_fails_closed():
    artifact = _valid_v5_artifact()
    artifact["artifact_kind"] = "native_binary_visual_evidence"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-009", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            _load_viz(releases_root, "release-v5-009")


def test_v5_missing_chart_axis_label_fails_closed():
    artifact = _valid_v5_artifact()
    del artifact["charts"][1]["y_label"]
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v5-010", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            _load_viz(releases_root, "release-v5-010")


# ---------------------------------------------------------------------------
# Historical profiles remain unchanged (purely additive schema admission)
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
        "evidence_policy": {"reduced_and_sanitized": True},
    }


def test_historical_classification_v1_projection_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v1-001", _classification_v1_artifact())

        projection = _load_viz(releases_root, "release-v1-001")

        assert [chart["id"] for chart in projection["charts"]] == [
            "target_distribution", "feature_importance",
        ]
        assert projection["dataset_statistics"] == {"instance_count": 10}
        assert "confusion_matrix" not in projection
        assert "regression_diagnostics" not in projection


def test_historical_external_fitted_model_v1_projection_unchanged():
    artifact = _classification_v1_artifact()
    artifact["schema_version"] = "analytical-visualizations.external-fitted-model.v1"
    artifact["target_distribution_method"]["population_kind"] = "external_prepared_dataset"
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-ext-v1-001", artifact)

        projection = _load_viz(releases_root, "release-ext-v1-001")

        assert [chart["id"] for chart in projection["charts"]] == [
            "target_distribution", "feature_importance",
        ]
        assert projection["dataset_statistics"] == {"instance_count": 10}


def test_historical_multiclass_v2_projection_unchanged():
    ordered_class_ids = ["setosa", "versicolor", "virginica"]
    artifact = {
        "schema_version": "analytical-visualizations.v2",
        "artifact_kind": "analytical_visualizations",
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": ordered_class_ids,
        },
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
        "evidence_policy": {"reduced_and_sanitized": True},
    }
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v2-001", artifact)

        projection = _load_viz(releases_root, "release-v2-001")

        assert projection["confusion_matrix"]["ordered_class_ids"] == ordered_class_ids
        assert "regression_diagnostics" not in projection


def test_historical_regression_v3_still_requires_its_diagnostics():
    """A v3 artifact with no regression diagnostics still fails closed -- the
    new v5 admission must not accidentally route v3 through the plain
    canonical-only path."""
    artifact = {
        "schema_version": "analytical-visualizations.v3",
        "artifact_kind": "analytical_visualizations",
        "charts": _classification_v1_artifact()["charts"],
        "target_distribution_method": {
            "population_kind": "prepared_dataset", "row_count": 10, "target_column": "outcome",
        },
        "evidence_policy": {"reduced_and_sanitized": True},
    }
    with tempfile.TemporaryDirectory() as tmp:
        releases_root = Path(tmp)
        _write_release(releases_root, "release-v3-001", artifact)
        with pytest.raises(loader.PublicVisualizationsUnavailableError):
            _load_viz(releases_root, "release-v3-001")
