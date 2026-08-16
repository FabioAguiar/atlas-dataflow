import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.materialize_external_analytical_visualizations import (  # noqa: E402
    materialize_external_analytical_visualizations,
)

DATASET_SLUG = "telco-customer-churn"
VALID_SHA256 = "a" * 64


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_training_parameter_record(
    repo_root: Path,
    *,
    dataset_slug: str = DATASET_SLUG,
    model_family: str = "hist_gradient_boosting",
    relative_path: str = "pipeline/external-fitted-model-runs/telco-customer-churn/run-001/training-parameter-record.json",
) -> tuple[str, str]:
    record = {
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "model_family": model_family,
    }
    full_path = repo_root / relative_path
    _write_json(full_path, record)
    record_sha256 = hashlib.sha256(full_path.read_bytes()).hexdigest()
    return relative_path, record_sha256


def _materialization_result(
    *,
    repo_root: Path,
    status: str = "materialized",
    model_source_mode: str = "validated_external_fitted_model",
    dataset_slug: str = DATASET_SLUG,
    model_family: str = "hist_gradient_boosting",
    record_relative_path: str | None = None,
    record_sha256: str | None = None,
) -> dict:
    if record_relative_path is None or record_sha256 is None:
        record_relative_path, record_sha256 = _write_training_parameter_record(
            repo_root, dataset_slug=dataset_slug, model_family=model_family
        )
    return {
        "status": status,
        "model_source_mode": model_source_mode,
        "dataset_identity": {"dataset_slug": dataset_slug},
        "evidence_references": {"training_parameter_record_path": record_relative_path},
        "evidence_hashes": {"training_parameter_record_sha256": record_sha256},
    }


def _valid_external_visual_evidence(
    *,
    dataset_slug: str = DATASET_SLUG,
    model_family: str = "hist_gradient_boosting",
    target_counts: list | None = None,
    feature_rows: list | None = None,
) -> dict:
    return {
        "dataset_slug": dataset_slug,
        "model_family": model_family,
        "target_distribution": {
            "target_column": "Churn",
            "source": "external_prepared_evaluation_population",
            "counts": target_counts
            or [{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
        },
        "feature_importance": {
            "source": "external_validated_fitted_model",
            "total_source_feature_count": 19,
            "omitted_source_feature_count": 9,
            "rows": feature_rows or [{"name": "tenure", "value": 0.23}, {"name": "Contract", "value": 0.18}],
        },
        "feature_importance_method": "permutation_importance",
    }


def _output_path() -> str:
    return "pipeline/external-fitted-model-runs/telco-customer-churn/run-001/analytical-visualizations.json"


def test_materialize_success_produces_schema_valid_artifact(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="artifacts/telco-customer-churn/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result
    assert result["visualizations_path"] == _output_path()
    assert result["visualizations_sha256"]

    artifact = json.loads((tmp_path / _output_path()).read_text())
    assert artifact["schema_version"] == "analytical-visualizations.external-fitted-model.v1"
    assert artifact["model_source_mode"] == "validated_external_fitted_model"
    assert artifact["dataset_identity"]["dataset_slug"] == DATASET_SLUG
    assert artifact["external_materialization_provenance"]["model_family"] == "hist_gradient_boosting"
    assert "training_run_identity" not in artifact

    schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(artifact)


def test_materialize_never_touches_model_bytes_or_sklearn(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    import pipeline.materialize_external_analytical_visualizations as module

    source_lines = Path(module.__file__).read_text(encoding="utf-8").splitlines()
    for forbidden in ("import sklearn", "from sklearn", "import joblib", "pickle.load", ".fit(", ".predict(", "permutation_importance("):
        assert not any(
            forbidden in line and not line.strip().startswith("#") for line in source_lines
        ), forbidden

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="artifacts/telco-customer-churn/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )
    assert result["status"] == "materialized"
    assert result["boundary_confirmations"]["model_bytes_imported_or_deserialized"] is False
    assert result["boundary_confirmations"]["feature_importance_computed_by_atlas"] is False
    assert result["boundary_confirmations"]["permutation_importance_computed"] is False
    assert result["boundary_confirmations"]["historical_visualization_reused"] is False


def test_materialize_blocks_when_materialization_result_not_materialized(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path, status="blocked")

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "materialization_not_materialized"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_dataset_identity_mismatch(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug="a-different-dataset",
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_evidence_dataset_slug_mismatch(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(dataset_slug="another-dataset"),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_materialize_blocks_on_model_family_mismatch(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path, model_family="hist_gradient_boosting")

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(model_family="logistic_regression"),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "model_identity_mismatch"


def test_materialize_blocks_on_referenced_training_record_hash_mismatch(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)
    materialization_result["evidence_hashes"]["training_parameter_record_sha256"] = "b" * 64

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "referenced_evidence_hash_mismatch"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_unsafe_output_path(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path="../outside-repo/analytical-visualizations.json",
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"


def test_materialize_blocks_on_unsafe_external_evidence_reference(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="/etc/passwd",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_invalid_external_evidence_sha256(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256="not-a-hash",
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_hash"


def test_materialize_blocks_on_missing_external_visual_evidence(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=None,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "missing_required_field"


def test_materialize_blocks_on_negative_chart_value(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)
    evidence = _valid_external_visual_evidence(
        target_counts=[{"name": "No", "value": -1}, {"name": "Yes", "value": 1869}]
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_chart_data"


def test_materialize_blocks_on_non_finite_chart_value(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)
    evidence = _valid_external_visual_evidence(
        feature_rows=[{"name": "tenure", "value": float("inf")}]
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_chart_data"


def test_materialize_blocks_when_feature_importance_rows_exceed_public_limit(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)
    evidence = _valid_external_visual_evidence(
        feature_rows=[{"name": f"feature-{i}", "value": 0.1} for i in range(11)]
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "chart_data_not_bounded"


def test_materialize_blocks_on_invalid_model_family(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path, model_family="not_a_real_family")

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(model_family=None),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_model_family"


def test_materialize_permits_hist_gradient_boosting(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path, model_family="hist_gradient_boosting")

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(model_family="hist_gradient_boosting"),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result


def test_materialize_never_reads_a_historical_release_visualization_file(tmp_path):
    # No releases/ directory exists anywhere under tmp_path -- a successful
    # materialization proves the module never touched one.
    materialization_result = _materialization_result(repo_root=tmp_path)
    assert not (tmp_path / "releases").exists()

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized"
    assert not (tmp_path / "releases").exists()


def test_materialize_output_never_contains_absolute_repo_root(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="artifacts/telco-customer-churn/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized"
    artifact_text = (tmp_path / _output_path()).read_text()
    assert str(tmp_path) not in artifact_text


def test_materialize_writes_beneath_current_external_fitted_model_run_directory(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized"
    assert result["visualizations_path"].startswith(
        "pipeline/external-fitted-model-runs/telco-customer-churn/run-001/"
    )


# --- Project Spec S0194: visual_evidence_origin provenance ------------------


def test_materialize_defaults_to_external_evidence_index_provenance(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="artifacts/telco-customer-churn/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result
    artifact = json.loads((tmp_path / _output_path()).read_text())
    assert artifact["external_materialization_provenance"]["visual_evidence_origin"] == "external_evidence_index"

    schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(artifact)


def test_materialize_accepts_atlas_reference_derivation_provenance(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)
    derived_reference = "pipeline/external-fitted-model-runs/telco-customer-churn/run-001/derived-analytical-visualization-evidence.json"
    derived_sha256 = "b" * 64

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference=derived_reference,
        external_evidence_sha256=derived_sha256,
        output_visualizations_path=_output_path(),
        visual_evidence_origin="atlas_reference_derivation",
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result
    artifact = json.loads((tmp_path / _output_path()).read_text())
    provenance = artifact["external_materialization_provenance"]
    assert provenance["visual_evidence_origin"] == "atlas_reference_derivation"
    # Atlas-derived evidence must bind to the derived-evidence Atlas
    # relative path and exact SHA-256 -- never described as producer-
    # authored external evidence -- while reusing the same reference/hash
    # fields the direct S0193 path already uses.
    assert provenance["external_evidence_reference"] == derived_reference
    assert provenance["external_evidence_sha256"] == derived_sha256

    schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(artifact)


def test_materialize_blocks_on_invalid_visual_evidence_origin(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        visual_evidence_origin="fabricated_origin",
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "invalid_visual_evidence_origin"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_unsafe_derived_evidence_reference(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="/etc/passwd",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        visual_evidence_origin="atlas_reference_derivation",
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"
    assert not (tmp_path / _output_path()).exists()


def test_materialize_blocks_on_invalid_derived_evidence_hash(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="pipeline/external-fitted-model-runs/telco-customer-churn/run-001/derived-analytical-visualization-evidence.json",
        external_evidence_sha256="not-a-hash",
        output_visualizations_path=_output_path(),
        visual_evidence_origin="atlas_reference_derivation",
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "invalid_hash"


def test_historical_external_evidence_index_only_provenance_remains_schema_valid():
    # Historical/S0193 fixture objects that carry only the original two
    # provenance fields (no visual_evidence_origin at all) must remain
    # schema-valid after the S0194 schema extension.
    historical_artifact = {
        "schema_version": "analytical-visualizations.external-fitted-model.v1",
        "artifact_kind": "analytical_visualizations",
        "model_source_mode": "validated_external_fitted_model",
        "created_at": "2026-01-01T00:00:00+00:00",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "external_materialization_provenance": {
            "model_family": "hist_gradient_boosting",
            "external_evidence_reference": "artifacts/telco-customer-churn/analytical-visual-evidence.json",
            "external_evidence_sha256": VALID_SHA256,
        },
        "charts": [
            {
                "id": "target_distribution",
                "title": "Target Distribution",
                "type": "bar",
                "x_label": "Churn",
                "y_label": "Count",
                "data": [{"name": "No", "value": 5174}, {"name": "Yes", "value": 1869}],
            },
            {
                "id": "feature_importance",
                "title": "Feature Importance",
                "type": "bar",
                "x_label": "Feature",
                "y_label": "Importance",
                "data": [{"name": "tenure", "value": 0.23}],
            },
        ],
        "target_distribution_method": {
            "population_kind": "external_prepared_dataset",
            "source": "external_prepared_evaluation_population",
            "target_column": "Churn",
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "external_validated_fitted_model",
            "method": "permutation_importance",
            "total_source_feature_count": 19,
            "omitted_source_feature_count": 18,
            "public_row_limit": 10,
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

    schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(historical_artifact)


# --- Project Spec S0215: multiclass (v2) external visualizations profile ---

MULTICLASS_ORDERED_CLASS_IDS = ["class-a", "class-b", "class-c"]


def _identity_confusion_matrix() -> list[list[float]]:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def _v2_materialization_result(
    *,
    repo_root: Path,
    status: str = "materialized",
    model_source_mode: str = "validated_external_fitted_model",
    dataset_slug: str = DATASET_SLUG,
    model_family: str = "decision_tree",
    ordered_class_ids: list | None = None,
) -> dict:
    record_relative_path, record_sha256 = _write_training_parameter_record(
        repo_root, dataset_slug=dataset_slug, model_family=model_family
    )
    return {
        "status": status,
        "schema_version": "external-fitted-model-materialization.v2",
        "model_source_mode": model_source_mode,
        "dataset_identity": {"dataset_slug": dataset_slug},
        "evidence_references": {"training_parameter_record_path": record_relative_path},
        "evidence_hashes": {"training_parameter_record_sha256": record_sha256},
        "classification_evidence": {
            "problem_type": "multiclass_classification",
            "ordered_class_ids": (
                ordered_class_ids if ordered_class_ids is not None else list(MULTICLASS_ORDERED_CLASS_IDS)
            ),
        },
    }


def _valid_v2_external_visual_evidence(
    *,
    dataset_slug: str = DATASET_SLUG,
    model_family: str = "decision_tree",
    confusion_matrix: dict | None = None,
) -> dict:
    evidence = _valid_external_visual_evidence(dataset_slug=dataset_slug, model_family=model_family)
    evidence["confusion_matrix"] = confusion_matrix or {
        "ordered_class_ids": list(MULTICLASS_ORDERED_CLASS_IDS),
        "matrix": _identity_confusion_matrix(),
    }
    return evidence


def test_v2_materialize_success_produces_schema_valid_artifact(tmp_path):
    materialization_result = _v2_materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_v2_external_visual_evidence(),
        external_evidence_reference="artifacts/multiclass-sample/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result

    artifact = json.loads((tmp_path / _output_path()).read_text())
    assert artifact["schema_version"] == "analytical-visualizations.external-fitted-model.v2"
    assert artifact["confusion_matrix"] == {
        "ordered_class_ids": MULTICLASS_ORDERED_CLASS_IDS,
        "matrix": _identity_confusion_matrix(),
        "row_axis": "true_class",
        "column_axis": "predicted_class",
    }

    schema = json.loads((REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(artifact)


def test_v1_materialization_result_still_produces_v1_artifact_without_confusion_matrix(tmp_path):
    materialization_result = _materialization_result(repo_root=tmp_path)

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_external_visual_evidence(),
        external_evidence_reference="artifacts/telco-customer-churn/analytical-visual-evidence.json",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "materialized", result
    artifact = json.loads((tmp_path / _output_path()).read_text())
    assert artifact["schema_version"] == "analytical-visualizations.external-fitted-model.v1"
    assert "confusion_matrix" not in artifact


def test_v2_materialize_blocks_on_missing_confusion_matrix(tmp_path):
    evidence = _valid_v2_external_visual_evidence()
    del evidence["confusion_matrix"]

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=_v2_materialization_result(repo_root=tmp_path),
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "missing_required_field"


def test_v2_materialize_blocks_on_confusion_matrix_class_order_mismatch(tmp_path):
    evidence = _valid_v2_external_visual_evidence(
        confusion_matrix={
            "ordered_class_ids": ["class-b", "class-a", "class-c"],
            "matrix": _identity_confusion_matrix(),
        }
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=_v2_materialization_result(repo_root=tmp_path),
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "confusion_matrix_class_order_mismatch"
    assert not (tmp_path / _output_path()).exists()


def test_v2_materialize_blocks_on_confusion_matrix_wrong_shape(tmp_path):
    evidence = _valid_v2_external_visual_evidence(
        confusion_matrix={
            "ordered_class_ids": list(MULTICLASS_ORDERED_CLASS_IDS),
            "matrix": [[1.0, 0.0], [0.0, 1.0]],
        }
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=_v2_materialization_result(repo_root=tmp_path),
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "confusion_matrix_shape_invalid"


def test_v2_materialize_blocks_on_confusion_matrix_row_not_summing_to_one(tmp_path):
    evidence = _valid_v2_external_visual_evidence(
        confusion_matrix={
            "ordered_class_ids": list(MULTICLASS_ORDERED_CLASS_IDS),
            "matrix": [[0.5, 0.2, 0.2], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=_v2_materialization_result(repo_root=tmp_path),
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "confusion_matrix_row_not_normalized"


def test_v2_materialize_blocks_on_non_finite_confusion_matrix_cell(tmp_path):
    evidence = _valid_v2_external_visual_evidence(
        confusion_matrix={
            "ordered_class_ids": list(MULTICLASS_ORDERED_CLASS_IDS),
            "matrix": [[float("nan"), 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
    )

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=_v2_materialization_result(repo_root=tmp_path),
        external_visual_evidence=evidence,
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "confusion_matrix_cell_invalid"


def test_v2_materialize_blocks_on_invalid_model_family_gradient_boosting_not_in_v2_vocabulary(tmp_path):
    """gradient_boosting is the v1-only family name; the v2 (multiclass)
    profile uses decision_tree in its place (Project Spec S0208)."""
    materialization_result = _v2_materialization_result(repo_root=tmp_path, model_family="gradient_boosting")

    result = materialize_external_analytical_visualizations(
        dataset_slug=DATASET_SLUG,
        materialization_result=materialization_result,
        external_visual_evidence=_valid_v2_external_visual_evidence(model_family=None),
        external_evidence_reference="x",
        external_evidence_sha256=VALID_SHA256,
        output_visualizations_path=_output_path(),
        repo_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_model_family"


def test_v2_materializer_never_deserializes_model():
    import pipeline.materialize_external_analytical_visualizations as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("import joblib", "import sklearn", "from sklearn", "pickle.load"):
        assert forbidden not in source


def test_materializer_module_still_has_no_sklearn_joblib_or_permutation_implementation():
    import pipeline.materialize_external_analytical_visualizations as module

    source_lines = Path(module.__file__).read_text(encoding="utf-8").splitlines()
    for forbidden in (
        "import sklearn",
        "from sklearn",
        "import joblib",
        "pickle.load",
        ".fit(",
        ".predict(",
        "permutation_importance(",
    ):
        assert not any(
            forbidden in line and not line.strip().startswith("#") for line in source_lines
        ), forbidden
