import copy
import hashlib
import json
from pathlib import Path

import jsonschema

from pipeline.analytical_visual_evidence import validate_analytical_visual_evidence


REPO_ROOT = Path(__file__).parent.parent.parent


def _artifact(asset_bytes: bytes = b"visual-bytes") -> dict:
    return {
        "schema_version": "analytical-visual-evidence.v2",
        "artifact_type": "analytical_visual_evidence",
        "dataset_identity": {"dataset_slug": "example-dataset"},
        "authoring_generation": {"authoring_generation_id": "generation-001", "immutable": True},
        "capability_profile": {
            "capability_profile_id": "binary-predictive-classification",
            "capability_profile_version": "v1",
        },
        "visual_collection_id": "example-visuals-001",
        "visuals": [{
            "visual_id": "target-overview",
            "logical_role": "target_distribution",
            "chart_kind": "bar",
            "title": "Target distribution",
            "caption": "Distribution across the prepared population.",
            "source_evidence": {
                "source_artifact_role": "discovery_evidence",
                "source_evidence_id": "target-counts",
                "source_fields": ["target"],
            },
            "method": {"summary": "Count rows by target value.", "aggregation": "count"},
            "relative_asset_path": "visuals/target-overview.png",
            "sha256": hashlib.sha256(asset_bytes).hexdigest(),
            "public_suitability": True,
            "public_suitability_reason": "Contains aggregate counts and no row-level data.",
            "provenance": {
                "logical_producer_project_id": "example-analysis",
                "producer_revision_known": False,
                "producer_revision": None,
            },
        }],
        "provenance": {
            "logical_producer_project_id": "atlas-dataflow",
            "producer_revision_known": True,
            "producer_revision": "revision-001",
        },
        "boundary_confirmations": {
            "public_suitability_authorizes_publication": False,
            "release_activation_performed": False,
            "absolute_external_project_root_present": False,
            "visual_assets_embedded": False,
            "notebook_execution_required": False,
        },
        "generated_at": "2026-08-07T00:00:00Z",
    }


def _profile(applicability: str = "required") -> dict:
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "binary-predictive-classification",
        "capability_profile_version": "v1",
        "support_status": "current_supported",
        "semantic_requirements": {
            "target_semantics_applicability": "required",
            "split_semantics_applicability": "required",
        },
        "artifact_roles": [{"role_name": "analytical_visual_evidence", "applicability": applicability}],
        "prediction_runtime": {"applicable": True, "mode": "single_model_binary_classification"},
        "publication": {"public_prediction_capability_applicability": "required"},
        "capability_boundary_confirmations": {
            "dataset_specific_selector_used": False,
            "dataset_specific_feature_names_present": False,
            "concrete_model_hashes_present": False,
            "model_bytes_embedded": False,
            "release_instance_metadata_embedded": False,
            "absolute_external_path_present": False,
            "training_result_values_embedded": False,
        },
        "generated_at": "2026-08-07T00:00:00Z",
    }


def _codes(result) -> set[str]:
    return {failure.code for failure in result.failures}


def test_valid_governed_collection_and_asset_hash(tmp_path):
    asset = tmp_path / "visuals" / "target-overview.png"
    asset.parent.mkdir()
    asset.write_bytes(b"visual-bytes")
    result = validate_analytical_visual_evidence(_artifact(), capability_profile=_profile(), asset_root=tmp_path, expected_dataset_slug="example-dataset")
    assert result.valid


def test_schema_is_valid_and_legacy_v1_fixture_remains_valid():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    legacy = {
        "schema_version": "analytical-visualizations.v1", "artifact_kind": "analytical_visualizations", "created_at": "2026-01-01T00:00:00Z",
        "training_run_identity": {"dataset_slug": "example-dataset", "run_id": "train-20260101T000000Z", "output_directory": "pipeline/training-runs/example-dataset/train-20260101T000000Z/"},
        "charts": [
            {"id": "target_distribution", "title": "Target", "type": "bar", "x_label": "class", "y_label": "count", "data": [{"name": "no", "value": 1}]},
            {"id": "feature_importance", "title": "Importance", "type": "bar", "x_label": "feature", "y_label": "importance", "data": [{"name": "age", "value": 0.5}]},
        ],
        "target_distribution_method": {"population_kind": "prepared_dataset", "row_count": 1, "target_column": "target"},
        "feature_importance_method": {"model_family": "logistic_regression", "source": "coefficient_magnitude", "total_source_feature_count": 1, "omitted_source_feature_count": 0, "public_row_limit": 10},
        "evidence_policy": {"raw_logs_prohibited": True, "raw_runtime_prohibited": True, "raw_api_payloads_prohibited": True, "secrets_prohibited": True, "raw_dataset_embedded": False, "model_bytes_embedded": False, "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False, "notebook_state_embedded": False, "reduced_and_sanitized": True},
    }
    jsonschema.Draft202012Validator(schema).validate(legacy)


# --- S0193: analytical-visualizations.external-fitted-model.v1 profile
# (pipeline/analytical-visualizations.schema.json's new oneOf branch, added
# alongside legacy_v1 and governed_v2 without weakening either). These
# tests validate the raw schema branch directly with jsonschema -- the same
# convention test_schema_is_valid_and_legacy_v1_fixture_remains_valid uses
# above -- since pipeline.analytical_visual_evidence.validate_analytical_visual_evidence's
# non-legacy path is specific to the unrelated governed_v2 capability-aware
# family and is out of S0193's authorized scope.


def _external_fitted_model_v1_fixture() -> dict:
    return {
        "schema_version": "analytical-visualizations.external-fitted-model.v1",
        "artifact_kind": "analytical_visualizations",
        "model_source_mode": "validated_external_fitted_model",
        "created_at": "2026-08-12T00:00:00Z",
        "dataset_identity": {"dataset_slug": "telco-customer-churn"},
        "external_materialization_provenance": {
            "model_family": "hist_gradient_boosting",
            "external_evidence_reference": "artifacts/telco-customer-churn/analytical-visual-evidence.json",
            "external_evidence_sha256": "a" * 64,
        },
        "charts": [
            {"id": "target_distribution", "title": "Target", "type": "bar", "x_label": "class", "y_label": "count", "data": [{"name": "no", "value": 1}]},
            {"id": "feature_importance", "title": "Importance", "type": "bar", "x_label": "feature", "y_label": "importance", "data": [{"name": "age", "value": 0.5}]},
        ],
        "target_distribution_method": {
            "population_kind": "external_prepared_dataset",
            "source": "external_prepared_evaluation_population",
            "target_column": "target",
        },
        "feature_importance_method": {
            "model_family": "hist_gradient_boosting",
            "source": "external_validated_fitted_model",
            "method": "permutation_importance",
            "total_source_feature_count": 1,
            "omitted_source_feature_count": 0,
            "public_row_limit": 10,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True, "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True, "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "serialized_estimator_state_embedded": False, "raw_transformed_matrices_embedded": False,
            "notebook_state_embedded": False, "reduced_and_sanitized": True,
        },
    }


def test_external_fitted_model_v1_fixture_is_schema_valid():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(_external_fitted_model_v1_fixture())


def test_external_fitted_model_v1_permits_hist_gradient_boosting_model_family():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    assert artifact["external_materialization_provenance"]["model_family"] == "hist_gradient_boosting"
    jsonschema.Draft202012Validator(schema).validate(artifact)


def test_external_fitted_model_v1_rejects_fabricated_training_run_identity():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    # additionalProperties: false on every oneOf branch means an Atlas
    # training_run_identity (the fabricated-provenance shape this profile
    # exists to avoid) cannot be smuggled in alongside the external profile's
    # own required fields.
    artifact["training_run_identity"] = {
        "dataset_slug": "telco-customer-churn",
        "run_id": "train-20260812T000000Z",
        "output_directory": "pipeline/training-runs/telco-customer-churn/train-20260812T000000Z/",
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert not validator.is_valid(artifact)


def test_external_fitted_model_v1_missing_external_materialization_provenance_is_rejected():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    del artifact["external_materialization_provenance"]
    validator = jsonschema.Draft202012Validator(schema)
    assert not validator.is_valid(artifact)


def test_external_fitted_model_v1_requires_exactly_two_charts():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    artifact["charts"] = [artifact["charts"][0]]
    validator = jsonschema.Draft202012Validator(schema)
    assert not validator.is_valid(artifact)


def test_external_fitted_model_v1_bounds_feature_importance_rows_to_ten():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    for chart in artifact["charts"]:
        if chart["id"] == "feature_importance":
            chart["data"] = [{"name": f"feature-{i}", "value": 0.1} for i in range(11)]
    validator = jsonschema.Draft202012Validator(schema)
    assert not validator.is_valid(artifact)


def test_external_fitted_model_v1_rejects_negative_chart_values():
    schema = json.loads((REPO_ROOT / "pipeline/analytical-visualizations.schema.json").read_text())
    artifact = _external_fitted_model_v1_fixture()
    artifact["charts"][0]["data"][0]["value"] = -1
    validator = jsonschema.Draft202012Validator(schema)
    assert not validator.is_valid(artifact)


def test_duplicate_visual_id_is_rejected():
    artifact = _artifact()
    artifact["visuals"].append(copy.deepcopy(artifact["visuals"][0]))
    assert "duplicate_visual_id" in _codes(validate_analytical_visual_evidence(artifact))


def test_malformed_sha256_is_rejected():
    artifact = _artifact()
    artifact["visuals"][0]["sha256"] = "ABC"
    assert "schema_validation_failed" in _codes(validate_analytical_visual_evidence(artifact))


def test_unsafe_asset_paths_are_rejected():
    for path in ("/tmp/chart.png", "C:/charts/chart.png", "file://charts/chart.png", "../chart.png", "visuals/../../chart.png"):
        artifact = _artifact()
        artifact["visuals"][0]["relative_asset_path"] = path
        assert not validate_analytical_visual_evidence(artifact).valid


def test_missing_public_suitability_reason_is_rejected():
    artifact = _artifact()
    del artifact["visuals"][0]["public_suitability_reason"]
    assert "schema_validation_failed" in _codes(validate_analytical_visual_evidence(artifact))


def test_blank_public_suitability_reason_is_rejected():
    artifact = _artifact()
    artifact["visuals"][0]["public_suitability_reason"] = "   "
    assert "public_suitability_reason_missing" in _codes(validate_analytical_visual_evidence(artifact))


def test_asset_hash_mismatch_is_rejected(tmp_path):
    asset = tmp_path / "visuals" / "target-overview.png"
    asset.parent.mkdir()
    asset.write_bytes(b"different")
    assert "asset_hash_mismatch" in _codes(validate_analytical_visual_evidence(_artifact(), asset_root=tmp_path))


def test_dataset_and_capability_profile_mismatches_are_rejected():
    artifact = _artifact()
    result = validate_analytical_visual_evidence(artifact, capability_profile=_profile(), expected_dataset_slug="other", expected_capability_profile_id="other-capability", expected_capability_profile_version="v2")
    assert {"dataset_identity_mismatch", "capability_profile_id_mismatch", "capability_profile_version_mismatch"} <= _codes(result)


def test_supplied_profile_identity_mismatch_is_rejected():
    profile = _profile()
    profile["capability_profile_id"] = "other-capability"
    assert "capability_profile_id_mismatch" in _codes(validate_analytical_visual_evidence(_artifact(), capability_profile=profile))


def test_required_optional_and_forbidden_role_semantics():
    required = validate_analytical_visual_evidence(None, capability_profile=_profile("required"))
    optional = validate_analytical_visual_evidence(None, capability_profile=_profile("optional"))
    forbidden = validate_analytical_visual_evidence(_artifact(), capability_profile=_profile("forbidden"))
    assert "required_role_missing" in _codes(required)
    assert optional.valid
    assert "forbidden_role_present" in _codes(forbidden)


def test_public_unsuitable_visual_with_reason_is_representable():
    artifact = _artifact()
    artifact["visuals"][0]["public_suitability"] = False
    artifact["visuals"][0]["public_suitability_reason"] = "Contains an internal-only analytical annotation."
    assert validate_analytical_visual_evidence(artifact).valid
