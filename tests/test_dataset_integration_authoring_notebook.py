import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = (
    REPO_ROOT
    / "notebooks/datasets/telco-customer-churn/dataset_integration.ipynb"
)


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


def _referenced_attribute_paths() -> set[str]:
    """Dotted attribute access chains anywhere in the notebook's code cells,
    e.g. `pipeline.validated_run.materialize_validated_run_terminal_result`
    reduced to `validated_run.materialize_validated_run_terminal_result`."""
    paths: set[str] = set()
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            parts = [node.attr]
            cursor = node.value
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)
            paths.add(".".join(reversed(parts)))
    return paths


def test_notebook_is_valid_nbformat_json():
    notebook = _notebook()
    assert notebook.get("nbformat") == 4
    assert notebook["cells"]


def test_notebook_has_the_orchestration_stages_in_order():
    markdown = _source("markdown")
    stages = [
        "1. Orchestration boundary declaration and responsibility",
        "2. Dataset/source input identity",
        "3. Atlas-owned source verification and drift checks",
        "4. Dataset-specific semantic interpretation",
        "5. Capability-profile resolution",
        "6. Deterministic preparation/input policy",
        "7. Reviewed native training-policy and binary result-semantics authoring",
        "8. Atlas authoring artifact materialization",
        "9. Cross-artifact authoring validation",
        "10. Capability-aware execution contract materialization",
        "11. Runtime/public contract and dataset-context compatibility confirmation",
        "12. Native training readiness",
        "13. Native binary fixed-configuration training run materialization",
        "14. Native metrics/visualization evidence validation",
        "15. Governed inference-bundle generation",
        "16. Release-candidate assembly from compatible governed roles",
        "17. Publisher Run materialization",
        "18. Validated-run terminal result",
        "19. Orchestration stop confirmation",
    ]
    offsets = [markdown.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_notebook_declares_native_orchestration_boundary():
    code = _source("code")
    assert "ORCHESTRATION_BOUNDARY" in code
    assert "AUTHORING_BOUNDARY" not in code
    for allowed in (
        "reviewed_native_training_policy_authoring",
        "execution_contract_materialization",
        "native_binary_fixed_configuration_training_run_materialization",
        "native_metrics_visualization_evidence_validation",
        "inference_bundle_materialization",
        "release_candidate_assembly",
        "publisher_structural_validation",
        "manifest_generation_when_structurally_permitted",
        "validated_run_terminal_outcome",
    ):
        assert allowed in code
    for forbidden in (
        "external_scientific_project_read_at_runtime",
        "external_model_load",
        "model_selection",
        "threshold_optimization",
        "model_deserialization_or_inference_execution",
        "publisher_promotion",
        "registry_active_release_mutation",
        "public_visibility_or_profile_activation",
    ):
        assert forbidden in code
    assert "stops_before_promotion_registry_activation_and_runtime_prediction" in code


def test_notebook_resolves_repository_root_without_cwd_override():
    code = _source("code")
    assert "Path.cwd()" not in code
    assert "repo_root = resolve_repository_root()" in code
    assert "from pipeline.discovery_evidence import resolve_repository_root, resolve_repository_path" in code


# --- Project Spec S0260: external study/evidence dependency removal --------


def test_notebook_no_longer_requires_external_scientific_analysis_root():
    code = _source("code")
    assert "external_scientific_analysis_root" not in code


def test_notebook_no_longer_reads_external_evidence_index():
    code = _source("code")
    assert "external_evidence_index" not in code
    assert "external-evidence-index.json" not in code
    assert "load_verified_external_evidence" not in code


def test_notebook_no_longer_imports_external_fitted_model_materializer():
    code = _source("code")
    assert "materialize_external_fitted_model" not in code
    assert "pipeline.materialize_external_fitted_model" not in code


def test_notebook_no_longer_imports_external_analytical_visualization_modules():
    code = _source("code")
    assert "materialize_external_analytical_visualizations" not in code
    assert "derive_external_analytical_visualization_evidence" not in code


def test_notebook_no_longer_imports_external_candidate_support_materializer():
    code = _source("code")
    assert "materialize_external_candidate_support" not in code


def test_notebook_never_loads_external_study_model_bytes():
    code = _source("code")
    for forbidden in ("joblib.load", "pickle.load", ".fit(", ".predict(", ".predict_proba(", "model_artifact_path"):
        assert forbidden not in code


def test_notebook_carries_no_absolute_external_study_path():
    code = _source("code")
    assert "dataset-study-telco-customer-churn" not in code
    assert "/home/" not in code
    assert "/workspace/" not in code


def test_notebook_no_longer_declares_external_run_root():
    code = _source("code")
    assert "external_fitted_model_run_root_relative_path" not in code
    assert "external_fitted_model_run_relative_path" not in code


# --- Atlas-local source is the only dataset input ---------------------------


def test_notebook_uses_only_atlas_local_raw_source():
    code = _source("code")
    assert 'dataset_relative_path = "data/raw/telco-customer-churn.csv"' in code
    assert "resolve_repository_path(dataset_relative_path, repo_root=repo_root)" in code


def test_notebook_source_verification_fails_closed_without_network_fallback():
    code = _source("code")
    for forbidden in ("requests.get", "urllib.request", "urlopen", "download"):
        assert forbidden not in code
    assert "load_dataset_csv(dataset_path)" in code


# --- fixed_configuration training policy authoring --------------------------


def test_notebook_authors_approved_fixed_configuration_training_policy():
    code = _source("code")
    assert '"review_status": "approved"' in code
    assert '"selection_mode": "fixed_configuration"' in code
    assert '"allowed_model_families": ["hist_gradient_boosting"]' in code
    assert '"model_family": "hist_gradient_boosting"' in code
    assert '"no_automl": True' in code


def test_notebook_freezes_the_historical_hgb_hyperparameters():
    code = _source("code")
    for fragment in (
        '"class_weight": None',
        '"l2_regularization": 1.0',
        '"learning_rate": 0.03',
        '"max_iter": 200',
        '"max_leaf_nodes": 7',
        '"min_samples_leaf": 40',
        '"max_depth": 3',
    ):
        assert fragment in code


def test_notebook_preserves_split_and_seed_identity():
    code = _source("code")
    assert '"strategy": "stratified"' in code
    assert '"train_ratio": 0.70' in code
    assert '"val_ratio": 0.15' in code
    assert '"test_ratio": 0.15' in code


def test_notebook_performs_no_model_selection_or_threshold_optimization():
    code = _source("code")
    for forbidden in (
        "GridSearchCV",
        "RandomizedSearchCV",
        "cross_val_score",
        "cross_validate",
        "model_selection_candidates",
        "practical_tie",
        "tie_break",
        "threshold_analysis",
        "educational_threshold",
    ):
        assert forbidden not in code
    calls = _called_names()
    assert calls.isdisjoint({"GridSearchCV", "RandomizedSearchCV", "cross_val_score", "cross_validate"})


def test_notebook_does_not_promote_the_educational_threshold():
    code = _source("code")
    assert "0.2577809673219062" not in code
    assert "threshold=0.5," in code
    assert 'execution_contract["result_semantics"]["decision"]["threshold"] == 0.5' in code


# --- binary result-semantics authoring --------------------------------------


def test_notebook_authors_binary_result_semantics_with_existing_governed_values():
    code = _source("code")
    assert "build_binary_result_semantics_intent" in code
    assert 'positive_class_id="Yes"' in code
    assert 'event_label="Churn"' in code
    assert 'primary_output="positive_class_probability"' in code
    assert "threshold=0.5" in code
    assert 'preset="risk"' in code
    for band in (
        '{"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35}',
        '{"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65}',
        '{"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0}',
    ):
        assert band in code


# --- authoring artifact materialization / cross-artifact validation --------


def test_notebook_materializes_and_validates_authoring_contracts():
    code = _source("code")
    assert '"dataset-semantic-intent.v1"' in code
    assert '"dataset-integration-authoring-manifest.v1"' in code
    assert '"binary-predictive-classification"' in code
    assert '"current_supported"' in code
    assert "write_governed_json" in code
    assert "validate_authoring_contracts" in code
    assert "assert authoring_validation.valid, authoring_validation.failures" in code


def test_notebook_manifest_carries_no_external_provenance():
    code = _source("code")
    manifest_source = code[code.index("manifest = {"):code.index("manifest_ref =")]
    assert '"provenance": []' in manifest_source
    assert "external_scientific_analysis_root" not in manifest_source
    assert "selected_external_evidence" not in manifest_source


def test_notebook_authoring_validation_precedes_execution_contract_materialization():
    code = _source("code")
    assert code.index("validate_authoring_contracts(") < code.index("materialize_execution_contract(")


# --- canonical execution-contract materialization ---------------------------


def test_notebook_materializes_execution_contract_via_canonical_derivation():
    code = _source("code")
    assert "from pipeline.contract_derivation import materialize_execution_contract" in code
    assert "materialize_execution_contract(" in code
    assert "from pipeline.discovery_evidence import build_dataset_modeling_intent" in code
    assert "build_dataset_modeling_intent(" in code
    assert "binary_result_semantics_intent=binary_result_semantics_intent," in code
    assert "training_policy_intent=training_policy_intent," in code
    assert "project_capability_aware_source_contract" not in code


def test_notebook_execution_contract_is_fixed_configuration_and_never_external():
    code = _source("code")
    assert 'execution_contract["modeling_constraints"]["selection_mode"] == "fixed_configuration"' in code
    assert (
        'execution_contract["modeling_constraints"]["fixed_model_configuration"]["model_family"] == '
        '"hist_gradient_boosting"'
    ) in code
    assert '"model_source_mode" not in execution_contract' in code
    assert '"validated_external_fitted_model"' not in code
    assert 'execution_contract["result_semantics"]["schema_version"] == "binary-result-semantics.v1"' in code


def test_notebook_confirms_runtime_public_contract_and_context_compatibility():
    code = _source("code")
    assert '[f["name"] for f in runtime_contract["features"]] == execution_contract["feature_columns"]' in code
    assert '[f["name"] for f in public_contract["features"]] == execution_contract["feature_columns"]' in code
    assert "dataset_context = json.loads((repo_root / dataset_context_relative_path).read_text" in code
    # This notebook never rewrites these three already-governed files.
    contract_section_start = code.index("runtime_contract = json.loads(")
    contract_section_end = code.index("prepare_training_invocation_readiness")
    contract_section = code[contract_section_start:contract_section_end]
    assert "write_governed_json(runtime_contract_relative_path" not in contract_section
    assert "write_governed_json(public_contract_relative_path" not in contract_section
    assert "write_governed_json(dataset_context_relative_path" not in contract_section


# --- native training run materialization ------------------------------------


def test_notebook_uses_train_from_paths_as_the_training_entrypoint():
    code = _source("code")
    referenced = _referenced_attribute_paths()
    assert "pipeline_training.materialize_training_run_from_prepared_metadata" in referenced
    assert "materialize_training_run_from_prepared_metadata(" in code
    assert "from pipeline import training as pipeline_training" in code


def test_notebook_never_hand_rolls_a_second_training_path():
    code = _source("code")
    for forbidden in (
        "HistGradientBoostingClassifier(",
        "from sklearn",
        "import sklearn",
    ):
        assert forbidden not in code


def test_notebook_training_call_is_gated_on_run_state():
    code = _source("code")
    section_start = code.index("from pipeline import training as pipeline_training")
    section_end = code.index("training_run_materialization_result[\"status\"] != \"trained\"")
    section = code[section_start:section_end]
    assert 'if not run_state["blocked"]:' in section


# --- v5 evidence validation ---------------------------------------------


def test_notebook_requires_v5_training_evidence():
    code = _source("code")
    assert 'training_parameter_record["schema_version"] == "training-parameter-record.v5"' in code
    assert 'training_metrics["schema_version"] == "training-metrics.v5"' in code
    assert 'analytical_visualizations["schema_version"] == "analytical-visualizations.v5"' in code


def test_notebook_verifies_positive_class_from_real_fitted_evidence():
    code = _source("code")
    assert 'real_fitted_classification_evidence = training_parameter_record["classification_evidence"]' in code
    assert 'real_fitted_classification_evidence["positive_class_id"] == "Yes"' in code
    assert 'analytical_visualizations["classification_evidence"]["positive_class_id"] == "Yes"' in code


def test_notebook_confirms_sealed_single_test_evaluation():
    code = _source("code")
    assert 'training_metrics["final_test_evaluation"]["completed"] is True' in code
    assert 'training_metrics["final_test_evaluation"]["evaluation_count"] == 1' in code


# --- inference-bundle materialization (internal-training branch only) ------


def test_notebook_orchestrates_governed_inference_bundle_generation_internally():
    code = _source("code")
    assert "generate_inference_bundle.materialize_governed_inference_bundle(" in code
    assert "training_run_materialization_result=training_run_materialization_result," in code
    assert "external_fitted_model_materialization_result" not in code
    assert 'inference_bundle_result["status"] != "generated"' in code


def test_notebook_bundle_call_passes_prepared_data_metadata_and_class_labels():
    code = _source("code")
    section_start = code.index("materialize_governed_inference_bundle(")
    section_end = code.index("if inference_bundle_result[\"status\"] != \"generated\":")
    section = code[section_start:section_end]
    assert "prepared_data_metadata_path=repo_root / prepared_data_metadata_relative_path," in section
    assert "class_labels=real_fitted_class_order," in section
    assert 'prediction_type="number",' in section
    assert "probability_output=True," in section


def test_notebook_confirms_bundle_result_semantics():
    code = _source("code")
    assert 'inference_bundle["result_semantics"]["schema_version"] == "binary-result-semantics.v1"' in code
    assert 'inference_bundle["result_semantics"]["positive_class"]["class_id"] == "Yes"' in code
    assert 'inference_bundle["result_semantics"]["decision"]["threshold"] == 0.5' in code
    assert 'inference_bundle["result_semantics"]["model_descriptor"]["model_family"] == "hist_gradient_boosting"' in code


# --- release-candidate assembly ---------------------------------------------


def test_notebook_orchestrates_release_candidate_assembly_from_compatible_roles():
    code = _source("code")
    assert "assemble_candidate.build_release_candidate_handoff_readiness(" in code
    assert "assemble_candidate.build_release_candidate_input(" in code
    assert "assemble_candidate.assemble_release_candidate(" in code
    assert "publisher.validate.materialize_telco_validation_run" not in code
    assert "materialize_telco_validation_run" not in code


def test_notebook_candidate_roles_use_current_native_run_artifacts():
    code = _source("code")
    candidate_section_start = code.index("candidate_artifact_references = {")
    candidate_section_end = code.index("candidate_handoff_readiness = assemble_candidate")
    candidate_section = code[candidate_section_start:candidate_section_end]
    assert '"training_parameter_record": training_result["training_parameter_record_path"],' in candidate_section
    assert '"model_artifact": training_result["serialized_model_path"],' in candidate_section
    assert '"training_metrics": training_result["metrics_path"],' in candidate_section
    assert '"model_card": training_result["model_card_path"],' in candidate_section
    assert '"visualizations": training_result["analytical_visualizations_path"],' in candidate_section
    assert '"inference_bundle": inference_bundle_relative_path,' in candidate_section
    assert '"public_context": dataset_context_relative_path,' in candidate_section
    # Never a borrowed historical external-fitted-model artifact.
    assert "external_materialization_result" not in candidate_section
    assert "external_fitted_model_run" not in candidate_section


def test_notebook_candidate_block_reasons_use_scalar_field_per_missing_role():
    code = _source("code")
    assert 'candidate_handoff_readiness["not_ready_roles"],' not in code
    assert "for unready_role in candidate_handoff_readiness[\"not_ready_roles\"]:" in code


# --- Publisher Run materialization (modern, dataset-agnostic path) ---------


def test_notebook_uses_materialize_validation_run_not_manual_filesystem_scanning():
    code = _source("code")
    assert "publisher_validate.materialize_validation_run(" in code
    assert "publisher_validate.run(" not in code
    assert "publisher_manifest.run(" not in code
    assert "new_run_dirs" not in code
    assert "existing_run_dirs" not in code


def test_notebook_publisher_materialization_checks_accepted_and_manifest_generated():
    code = _source("code")
    assert 'publisher_materialization_result["materialization_status"] != "materialized"' in code
    assert "publisher_validation_outcome != \"accepted\"" in code
    assert 'not publisher_materialization_result["manifest_generated"]' in code
    assert '(publisher_run_dir / "validation-result.json").is_file()' in code
    assert '(publisher_run_dir / "manifest.json").is_file()' in code


# --- validated-run terminal result ------------------------------------------


def test_notebook_materializes_one_validated_run_terminal_result_as_atlas_internal_training():
    code = _source("code")
    assert "from pipeline import validated_run" in code
    assert "validated_run.materialize_validated_run_terminal_result(" in code
    assert 'model_source_mode="atlas_internal_training",' in code
    assert 'terminal_status = "blocked" if run_state["blocked"] else "completed"' in code
    assert "write_governed_json(terminal_result_relative_path, validated_run_terminal_result)" in code


def test_notebook_completed_terminal_result_is_promotion_eligible():
    code = _source("code")
    assert (
        'if validated_run_terminal_result["status"] == "completed":\n'
        '        assert validated_run_terminal_result["promotion_eligibility"] is True'
    ) in code


# --- forbidden active behavior ----------------------------------------------


def test_notebook_has_no_active_modeling_or_runtime_calls():
    calls = _called_names()
    forbidden = {
        "fit", "fit_transform", "cross_validate", "cross_val_score", "GridSearchCV",
        "RandomizedSearchCV", "load_model", "predict", "predict_proba",
        "score", "classification_report", "confusion_matrix",
    }
    assert calls.isdisjoint(forbidden), calls & forbidden
    code = _source("code")
    assert "pickle" not in code
    assert "import joblib" not in code
    assert "joblib.load" not in code


def test_notebook_has_no_promotion_or_registry_activation_calls():
    code = _source("code")
    for forbidden in (
        "promote.run(",
        "publisher.promote",
        "registry_update.run(",
        "activate_release",
        "write_registry",
        "update_registry",
    ):
        assert forbidden not in code
    referenced = _referenced_attribute_paths()
    assert not any(path.startswith("promote.") for path in referenced)


def test_notebook_requires_the_native_orchestration_calls():
    code = _source("code")
    referenced = _referenced_attribute_paths()
    required_paths = {
        "pipeline_training.materialize_training_run_from_prepared_metadata",
        "generate_inference_bundle.materialize_governed_inference_bundle",
        "assemble_candidate.build_release_candidate_input",
        "assemble_candidate.assemble_release_candidate",
        "publisher_validate.materialize_validation_run",
        "validated_run.materialize_validated_run_terminal_result",
    }
    assert required_paths.issubset(referenced), required_paths - referenced
    assert "materialize_external_fitted_model" not in code


def test_notebook_tests_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")


def test_notebook_never_requires_real_telco_checkout_or_model_bytes_to_be_parsed():
    # The notebook is valid, parseable Python source in every code cell --
    # this test itself never executes the notebook or touches the external
    # Telco study project, matching the static/synthetic requirement for
    # S0260 (and, before it, S0184).
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))
