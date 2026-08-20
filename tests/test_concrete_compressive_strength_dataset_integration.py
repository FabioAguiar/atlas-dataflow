"""
Project Spec S0233: static structural proof for
notebooks/datasets/concrete-compressive-strength/dataset_integration.ipynb.

Mirrors tests/test_dry_bean_dataset_integration.py's static conventions (no
external checkout, no model bytes required, never executed by this test).
Proves the notebook is a well-formed, syntactically valid Atlas-native
continuous-regression training orchestrator that never reads the attached
dataset-study-concrete-compressives-strength scientific reference project at
runtime, never loads an external model, never fits a model directly, calls
the governed native training entrypoint, encodes the fixed HGB
continuous-regression training policy, introduces no dataset-slug branch
into generic production modules, creates no Predict View, and stops before
real registry/release activation.
"""

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks/datasets/concrete-compressive-strength/dataset_integration.ipynb"


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source(cell_type: str | None = None) -> str:
    return "\n".join(
        "".join(cell["source"])
        for cell in _notebook()["cells"]
        if cell_type is None or cell["cell_type"] == cell_type
    )


def _called_names() -> set[str]:
    names: set[str] = set()
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def test_notebook_is_valid_nbformat_json():
    notebook = _notebook()
    assert notebook.get("nbformat") == 4
    assert notebook["cells"]


def test_notebook_never_requires_real_concrete_checkout_or_model_bytes_to_be_parsed():
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))


def test_notebook_tests_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")


def test_notebook_has_the_seventeen_orchestration_stages_in_order():
    markdown = _source("markdown")
    stages = [
        "## 1. Orchestration boundary declaration and responsibility",
        "## 2. Atlas source identity / local raw input verification",
        "## 3. Reduced Atlas discovery evidence",
        "## 4. Concrete Compressive Strength semantic intent v3",
        "## 5. Preparation recipe / prepared candidate",
        "## 6. Reviewed native continuous-regression training policy intent",
        "## 7. Continuous-regression capability resolution",
        "## 8. Execution contract materialization",
        "## 9. Runtime/public contract projection",
        "## 10. Native training readiness",
        "## 11. Native continuous-regression training run materialization",
        "## 12. Native metrics/visualization evidence validation",
        "## 13. Governed inference-bundle generation",
        "### Native runtime/API projection checks",
        "## 14. Release-candidate assembly",
        "## 15. Publisher Run materialization + manifest",
        "## 16. Validated-run terminal result",
        "## 17. Explicit stop before real registry/release activation",
    ]
    offsets = [markdown.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_notebook_declares_orchestration_boundary_with_no_model_fitting():
    code = _source("code")
    assert "ORCHESTRATION_BOUNDARY" in code
    for allowed in (
        "native_continuous_regression_training_run_materialization",
        "inference_bundle_materialization",
        "release_candidate_assembly",
        "publisher_structural_validation",
        "manifest_generation_when_structurally_permitted",
    ):
        assert allowed in code
    for forbidden in (
        "external_scientific_project_read_at_runtime",
        "external_model_load",
        "external_evidence_ingestion",
        "model_fitting_in_notebook",
        "model_retraining_in_notebook",
        "model_family_search",
        "hyperparameter_search",
        "feature_selection",
        "target_transformation",
        "model_deserialization_or_inference_execution",
        "publisher_promotion",
        "registry_active_release_mutation",
        "public_visibility_or_profile_activation",
        "predict_view_creation",
    ):
        assert forbidden in code
    assert "stops_before_promotion_registry_activation_and_runtime_prediction" in code
    assert 'assert ORCHESTRATION_BOUNDARY["durable_absolute_external_path"] is False' in code


def test_notebook_resolves_repository_root_without_cwd_override():
    code = _source("code")
    assert "Path.cwd()" not in code
    assert "repo_root = resolve_repository_root()" in code
    assert "from pipeline.discovery_evidence import resolve_repository_root, resolve_repository_path" in code


def test_notebook_uses_local_raw_source_only():
    code = _source("code")
    assert 'dataset_relative_path = "data/raw/concrete-compressive-strength/dataset.csv"' in code
    assert "1030" in code
    assert "uci_dataset_id = 165" in code


def test_notebook_verifies_expected_row_and_column_counts():
    code = _source("code")
    assert 'assert atlas_structure["row_count"] == 1030' in code
    assert 'assert atlas_structure["column_count"] == 9' in code


def test_notebook_never_reads_external_scientific_project_path():
    code = _source("code")
    for forbidden_substring in (
        "external_scientific_analysis_root",
        "external_root",
        "dataset-study-concrete-compressives-strength",
        "DATASET-ANALISYS",
        "/home/",
        "/workspace/",
    ):
        assert forbidden_substring not in code


def test_notebook_never_loads_an_external_artifact_or_model():
    code = _source("code")
    for forbidden in (
        "materialize_external_fitted_model",
        "external_evidence_index",
        "load_verified_external_evidence",
        "joblib.load",
        "pickle.load",
        ".predict(",
        ".predict_proba(",
    ):
        assert forbidden not in code


def test_notebook_contains_no_direct_model_fit_call():
    calls = _called_names()
    forbidden = {
        "fit", "fit_transform", "cross_validate", "cross_val_score",
        "GridSearchCV", "RandomizedSearchCV",
    }
    assert calls.isdisjoint(forbidden), calls & forbidden
    code = _source("code")
    assert ".fit(" not in code
    assert "fit_transform(" not in code


def test_notebook_uses_native_training_entrypoint():
    code = _source("code")
    assert "materialize_training_run_from_prepared_metadata" in code
    assert "materialize_training_run_from_prepared_metadata" in _called_names()
    assert 'training_run_materialization_result["status"] != "trained"' in code


def test_notebook_encodes_fixed_hgb_training_policy():
    code = _source("code")
    assert '"model_family": "hist_gradient_boosting"' in code
    assert '"selection_mode": "fixed_configuration"' in code
    assert '"no_automl": True' in code
    assert '"l2_regularization": 1.0' in code
    assert '"learning_rate": 0.1' in code
    assert '"max_iter": 300' in code
    assert '"max_leaf_nodes": 15' in code
    assert '"min_samples_leaf": 10' in code
    assert '"review_status": "approved"' in code
    assert "random_state" not in code


def test_notebook_encodes_random_seed_42_through_execution_contract_not_hyperparameters():
    code = _source("code")
    assert "discovery_evidence_seed = 42" in code
    assert 'assert execution_contract["random_seed"] == 42' in code
    assert 'assert training_parameter_record["training_parameters"]["random_seed"] == 42' in code


def test_notebook_encodes_random_split_70_15_15():
    code = _source("code")
    assert '"strategy": "random"' in code
    assert '"train_ratio": 0.70' in code
    assert '"val_ratio": 0.15' in code
    assert '"test_ratio": 0.15' in code
    assert '"strategy": "stratified"' not in code


def test_notebook_encodes_mae_rmse_r2_metrics_and_no_medae():
    code = _source("code")
    assert '"primary_metric": "mae"' in code
    assert '"secondary_metrics": ["rmse", "r2"]' in code
    assert "medae" not in code.lower()


def test_notebook_encodes_no_resampling_or_feature_selection():
    code = _source("code")
    for forbidden in ("SMOTE", "resample", "SelectKBest", "RFE("):
        assert forbidden not in code


def test_notebook_encodes_eight_reviewed_feature_names_in_exact_order():
    code = _source("code")
    assert (
        "expected_feature_order = [\n"
        '    "Cement",\n'
        '    "Blast Furnace Slag",\n'
        '    "Fly Ash",\n'
        '    "Water",\n'
        '    "Superplasticizer",\n'
        '    "Coarse Aggregate",\n'
        '    "Fine Aggregate",\n'
        '    "Age",\n'
        "]"
    ) in code
    assert "assert feature_names == expected_feature_order" in code
    assert 'target_field_name = "Concrete compressive strength"' in code


def test_notebook_preserves_blast_furnace_slag_decimal_values():
    code = _source("code")
    assert 'blast_furnace_slag_observation["inferred_type"] == "float"' in code
    assert 'any("." in value for value in blast_furnace_slag_observation["reduced_sample_values"])' in code


def test_notebook_authors_dataset_semantic_intent_v3_for_continuous_regression():
    code = _source("code")
    assert '"schema_version": "dataset-semantic-intent.v3"' in code
    assert '"capability_profile_id": "continuous-predictive-regression"' in code
    assert '"capability_profile_version": "v1"' in code
    assert '"task_type": "continuous_regression"' in code
    assert '"target_value_kind": "continuous_numeric"' in code
    assert '"is_final_training_configuration": False' in code
    for forbidden in ("classes", "positive_class", "negative_class", "threshold", "probability_output"):
        assert f'"{forbidden}"' not in code


def test_notebook_authors_continuous_regression_result_semantics_intent():
    code = _source("code")
    assert "build_continuous_regression_result_semantics_intent" in code
    assert "build_continuous_regression_result_semantics_intent" in _called_names()
    assert 'primary_output="predicted_value"' in code
    assert 'output_value_kind="continuous_numeric"' in code


def test_notebook_asserts_materialized_result_semantics_shape():
    code = _source("code")
    assert 'execution_contract["result_semantics"]["schema_version"] == "continuous-regression-result-semantics.v1"' in code
    assert 'execution_contract["result_semantics"]["problem_type"] == "continuous_regression"' in code
    assert 'execution_contract["result_semantics"]["primary_output"] == "predicted_value"' in code
    assert 'execution_contract["result_semantics"]["output_value_kind"] == "continuous_numeric"' in code


def test_notebook_validates_native_evidence_versions():
    code = _source("code")
    assert 'training_metrics["schema_version"] == "training-metrics.v3"' in code
    assert 'analytical_visualizations["schema_version"] == "analytical-visualizations.v3"' in code
    assert 'training_metrics["regression_evidence"]["problem_type"] == "continuous_regression"' in code
    assert 'analytical_visualizations["regression_evidence"]["problem_type"] == "continuous_regression"' in code


def test_notebook_validates_hgb_permutation_feature_importance():
    code = _source("code")
    assert 'analytical_visualizations["feature_importance_method"]["source"] == "sklearn.inspection.permutation_importance"' in code
    assert "feature_importances_" not in code


def test_notebook_orchestrates_inference_bundle_generation_with_number_prediction_type():
    code = _source("code")
    assert "generate_inference_bundle.materialize_governed_inference_bundle(" in code
    assert 'inference_bundle_result["status"] != "generated"' in code
    assert 'prediction_type="number"' in code
    assert "class_labels=" not in code
    assert "probability_output=" not in code


def test_notebook_asserts_native_provenance_and_bundle_schema_shape():
    code = _source("code")
    assert 'inference_bundle["model_provenance_origin"] == "atlas_internal_training"' in code
    assert 'inference_bundle["result_semantics"]["result_schema_version"] == "continuous-regression-result.v1"' in code
    assert 'inference_bundle["output_schema"]["prediction_type"] == "number"' in code


def test_notebook_orchestrates_release_candidate_assembly():
    code = _source("code")
    assert "assemble_candidate.build_release_candidate_handoff_readiness(" in code
    assert "assemble_candidate.build_release_candidate_input(" in code
    assert "assemble_candidate.assemble_release_candidate(" in code


def test_notebook_uses_generic_release_identity_allocator():
    code = _source("code")
    assert "from pipeline import generate_inference_bundle, release_identity" in code
    assert "release_identity.allocate_release_id(run_id, repo_root)" in code
    assert "allocate_release_id" in _called_names()
    assert "_derive_provisional_release_id" not in code
    assert code.count("allocate_release_id(") == 1


def test_notebook_creates_no_predict_view():
    code = _source("code")
    for forbidden in ("view_id", "contract_precedence", "_predict_view = {", "declared_predict_view"):
        assert forbidden not in code
    assert '"predict_views": []' in code
    assert 'dataset_context.get("predict_views") != []' in code
    assert '"predict_view_created": False' in code


def test_notebook_has_no_promotion_or_registry_activation_calls():
    code = _source("code")
    for forbidden in (
        "publisher_promote.run(", "publisher.promote", "promote.run(",
        "registry_update.run(", "registry.update", "activate_release",
        "write_registry", "update_registry",
    ):
        assert forbidden not in code


def test_notebook_stop_confirmation_declares_no_activation_performed():
    code = _source("code")
    assert '"promotion_performed": False' in code
    assert '"registry_activation_performed": False' in code
    assert '"public_visibility_or_profile_activation_performed": False' in code
    assert '"predict_view_created": False' in code


def test_notebook_introduces_no_dataset_slug_branch_into_generic_pipeline_modules():
    code = _source("code")
    assert 'if dataset_slug == "concrete-compressive-strength"' not in code
    assert "if dataset_slug ==" not in code


def test_notebook_calls_the_generic_publisher_run_materializer_with_assembly_result():
    code = _source("code")
    assert "from publisher import validate as publisher_validate" in code
    assert "publisher_validate.materialize_validation_run(" in code
    assert "materialize_validation_run" in _called_names()
    assert (
        "publisher_materialization_result = publisher_validate.materialize_validation_run(\n"
        "        assembly_result, repo_root=repo_root,\n    )"
    ) in code
    for forbidden in ("glob(", "iterdir()", 'Path("releases"', 'releases/candidates"\n'):
        assert forbidden not in code
    assert "materialize_telco_validation_run" not in code


def test_notebook_blocks_when_publisher_run_materialization_fails():
    code = _source("code")
    assert 'publisher_materialization_result["materialization_status"] != "materialized"' in code
    assert '"publisher_run_materialization_blocked"' in code
    assert 'publisher_validation_outcome != "accepted"' in code
    assert '"publisher_structural_validation_rejected"' in code
    assert 'not publisher_materialization_result["manifest_generated"]' in code
    assert '"publisher_manifest_not_generated"' in code


def test_notebook_materializes_validated_terminal_result_with_atlas_internal_training():
    code = _source("code")
    assert "from pipeline import validated_run" in code
    assert "validated_run.materialize_validated_run_terminal_result(" in code
    assert "materialize_validated_run_terminal_result" in _called_names()
    assert 'model_source_mode="atlas_internal_training"' in code
    assert '"operational_validity": "not_applicable"' in code


def test_notebook_writes_validated_run_terminal_result_under_publisher_runs():
    code = _source("code")
    assert (
        'terminal_result_relative_path = f"{publisher_run_dir_relative_path}/validated-run-terminal-result.json"'
        in code
    )
    assert "write_governed_json(terminal_result_relative_path, validated_run_terminal_result)" in code
    assert "pipeline/training-runs/" not in code
    assert 'terminal_result_relative_path = f"releases/candidates' not in code
    assert "if publisher_run_dir_relative_path is not None:" in code


def test_notebook_requires_completed_terminal_status_and_promotion_eligibility_true():
    code = _source("code")
    assert 'if validated_run_terminal_result["status"] == "completed":' in code
    assert 'assert validated_run_terminal_result["promotion_eligibility"] is True' in code
    assert 'assert validated_run_terminal_result["status"] in ("completed", "blocked", "failed")' in code


def test_notebook_summary_exposes_publisher_run_and_terminal_result_identity():
    code = _source("code")
    assert '"publisher_run_id": publisher_run_id' in code
    assert '"publisher_run_dir": publisher_run_dir_relative_path' in code
    assert '"terminal_status": validated_run_terminal_result["status"] if validated_run_terminal_result else None' in code
    assert '"promotion_eligibility": (' in code
