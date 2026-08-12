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
    e.g. `pipeline.materialize_external_fitted_model.materialize_external_fitted_model`
    reduced to `materialize_external_fitted_model.materialize_external_fitted_model`."""
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


def test_notebook_has_the_seventeen_orchestration_stages_in_order():
    markdown = _source("markdown")
    stages = [
        "1. Orchestration boundary declaration and responsibility",
        "2. Dataset/source input identity",
        "3. Atlas-owned source verification and drift checks",
        "4. External evidence discovery",
        "5. External evidence integrity and provenance verification",
        "6. Dataset-specific semantic interpretation",
        "7. Capability-profile resolution",
        "8. Deterministic preparation/input policy",
        "9. Atlas authoring artifact materialization",
        "10. Cross-artifact authoring validation",
        "11. Capability-aware source/projection handoff",
        "12. External fitted-model governed materialization",
        "13. Governed inference-bundle generation",
        "14. Release-candidate assembly from compatible governed roles",
        "15. Publisher structural validation and conditional manifest generation",
        "16. Validated-run terminal result",
        "17. Orchestration stop confirmation",
    ]
    offsets = [markdown.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_notebook_declares_extended_orchestration_boundary_not_authoring_only():
    code = _source("code")
    assert "ORCHESTRATION_BOUNDARY" in code
    assert "AUTHORING_BOUNDARY" not in code
    for allowed in (
        "external_fitted_model_governed_materialization",
        "inference_bundle_materialization",
        "release_candidate_assembly",
        "publisher_structural_validation",
        "manifest_generation_when_structurally_permitted",
        "validated_run_terminal_outcome",
    ):
        assert allowed in code
    for forbidden in (
        "external_eda_rerun",
        "model_fitting_or_retraining",
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


def test_notebook_converges_on_real_external_evidence_index_contract():
    code = _source("code")
    assert 'external_evidence_index_relative_path = "artifacts/telco-customer-churn/external-evidence-index.json"' in code
    assert 'external_evidence_index.get("schema_version") == "external-evidence-index.v1"' in code
    assert 'external_evidence_index.get("artifact_type") == "external_evidence_index"' in code
    assert 'external_evidence_index.get("dataset_slug") == dataset_slug' in code
    assert 'provenance.get("logical_producer_project_id")' in code
    assert "evidence_inventory = external_evidence_index.get(\"evidence_inventory\")" in code
    assert 'missing_artifacts = external_evidence_index.get("missing_artifacts", [])' in code
    assert "required_missing" in code


def test_external_evidence_is_hash_verified_and_only_reduced_provenance_is_durable():
    code = _source("code")
    assert "safe_external_relative_path" in code
    assert "sha256_file(evidence_path) == reference[\"sha256\"]" in code
    assert '"relative_path": relative_path' in code
    assert '"producer_revision_known"' in code
    manifest_source = code[code.index("manifest = {"):code.index("manifest_ref =")]
    assert "external_scientific_analysis_root" not in manifest_source
    assert '"external_root"' not in manifest_source
    assert (
        'assert all("external_scientific_analysis_root" not in json.dumps(item) '
        'for item in selected_external_evidence)'
    ) in code


def test_notebook_materializes_and_validates_authoring_contracts():
    code = _source("code")
    assert '"dataset-semantic-intent.v1"' in code
    assert '"dataset-integration-authoring-manifest.v1"' in code
    assert '"binary-predictive-classification"' in code
    assert '"current_supported"' in code
    assert "write_governed_json" in code
    assert "validate_authoring_contracts" in code


def test_notebook_uses_preparation_recipe_role_and_filename_not_preparation_policy():
    code = _source("code")
    assert '"role": "preparation_recipe"' in code
    assert "preparation-recipe.json" in code
    assert '"role": "preparation_policy"' not in code
    assert "preparation-policy.json" not in code


def test_notebook_manifest_does_not_predeclare_model_artifact_before_materialization():
    code = _source("code")
    manifest_source = code[code.index("manifest = {"):code.index("manifest_ref =")]
    assert "model_artifact" not in manifest_source


def test_notebook_authoring_validation_precedes_external_fitted_model_materialization():
    code = _source("code")
    assert code.index("validate_authoring_contracts(") < code.index("materialize_external_fitted_model(")


def test_notebook_keeps_authoring_validation_assert():
    code = _source("code")
    assert "assert authoring_validation.valid, authoring_validation.failures" in code


def test_notebook_constructs_the_capability_aware_boundary_with_canonical_ref():
    code = _source("code")
    for field in (
        "authoring_generation_id",
        "authoring_manifest_ref",
        "capability_profile_id",
        "capability_profile_version",
        "capability_profile_ref",
    ):
        assert field in code
    assert "project_capability_aware_source_contract" in code
    assert '"source_notebook_ref": canonical_notebook_ref' in code
    assert (
        'canonical_notebook_ref = "notebooks/datasets/telco-customer-churn/dataset_integration.ipynb"'
        in code
    )


def test_notebook_orchestrates_external_fitted_model_materialization():
    code = _source("code")
    assert "from pipeline.materialize_external_fitted_model import materialize_external_fitted_model" in code
    assert "materialize_external_fitted_model(" in _called_names() or "materialize_external_fitted_model" in code
    assert 'external_materialization_result["status"] == "materialized"' in code
    assert "for reason in external_materialization_result[\"blocking_reasons\"]" in code
    assert "record_block(reason[\"code\"], reason[\"message\"], reason.get(\"field\"))" in code


def test_external_materialization_never_trains_or_deserializes():
    code = _source("code")
    for forbidden in (
        "train_from_paths",
        "joblib.load",
        "pickle.load",
        ".fit(",
        ".predict(",
        ".predict_proba(",
    ):
        assert forbidden not in code
    # The notebook is allowed to reuse pipeline.training's governed,
    # side-effect-free prepared-dataset metadata resolver -- the same one
    # pipeline/generate_inference_bundle.py already imports for its own
    # internal-training branch -- but never the real training entrypoint.
    assert "from pipeline.training import _prepared_dataset_metadata_blocking_reasons" in code
    assert "pipeline.training.train_from_paths" not in code


def test_notebook_orchestrates_governed_inference_bundle_generation():
    code = _source("code")
    assert "generate_inference_bundle.materialize_governed_inference_bundle(" in code
    assert "external_fitted_model_materialization_result=external_materialization_result" in code
    assert '"training_evidence"' not in code
    assert 'inference_bundle_result["status"] != "generated"' in code


# --- prepared-dataset / inference-bundle blocker fix -------------------------


def test_notebook_resolves_prepared_dataset_from_atlas_owned_metadata():
    code = _source("code")
    assert "from pipeline.training import _prepared_dataset_metadata_blocking_reasons" in code
    assert "prepared_dataset_metadata_full_path = repo_root / prepared_data_metadata_relative_path" in code
    assert (
        'prepared_dataset_metadata = json.loads(\n'
        "            prepared_dataset_metadata_full_path.read_text(encoding=\"utf-8\")\n"
        "        )"
    ) in code
    assert "governed_reasons, governed_reference = _prepared_dataset_metadata_blocking_reasons(" in code


def test_notebook_verifies_prepared_dataset_existence_and_integrity_before_bundle_call():
    code = _source("code")
    # Existence/integrity (including governed content_sha256) is enforced by
    # the same reused `_prepared_dataset_metadata_blocking_reasons` boundary
    # -- the notebook must not skip or duplicate that check, and must fail
    # closed (via the existing record_block mechanism) rather than continue
    # with an unresolved/invalid prepared dataset.
    assert "prepared_dataset_blocking_reasons.extend(governed_reasons)" in code
    assert 'record_block("prepared_dataset_unresolved", reason)' in code
    resolution_index = code.index(
        "_prepared_dataset_metadata_blocking_reasons(\n            prepared_dataset_metadata"
    )
    bundle_call_index = code.index("materialize_governed_inference_bundle(")
    assert resolution_index < bundle_call_index


def test_notebook_checks_prepared_dataset_metadata_dataset_identity():
    code = _source("code")
    assert (
        '(prepared_dataset_metadata.get("dataset_identity") or {}).get(\n'
        '            "dataset_slug"\n'
        "        )"
    ) in code
    assert "if metadata_dataset_slug != dataset_slug:" in code


def test_notebook_passes_resolved_prepared_dataset_path_and_ref_to_bundle_call():
    code = _source("code")
    assert "prepared_dataset_path=prepared_dataset_path," in code
    assert "prepared_dataset_ref=prepared_dataset_ref," in code
    resolution_index = code.index("prepared_dataset_path = None\nprepared_dataset_ref = None")
    bundle_call_index = code.index("materialize_governed_inference_bundle(")
    assert resolution_index < bundle_call_index


def test_notebook_does_not_use_raw_dataset_as_prepared_dataset():
    code = _source("code")
    bundle_section_start = code.index("prepared_dataset_path = None\nprepared_dataset_ref = None")
    bundle_call_end = code.index("materialize_governed_inference_bundle(")
    bundle_section = code[bundle_section_start:bundle_call_end]
    assert "dataset_relative_path" not in bundle_section
    assert "data/raw" not in bundle_section


def test_notebook_never_persists_absolute_prepared_dataset_path():
    code = _source("code")
    # The resolved reference used for the durable bundle artifact is always
    # the governed repository-relative string returned by
    # _prepared_dataset_metadata_blocking_reasons -- never str(repo_root) or
    # any other absolute-path construction.
    assert "prepared_dataset_ref = governed_reference" in code
    assert "str(repo_root / governed_reference)" not in code
    assert "str(prepared_dataset_path)" not in code


# --- Project Spec S0193: external analytical-visualization evidence and
# release materialization ---
# --- Project Spec S0194: Atlas-owned derivation fallback when the external
# analytical_visualizations role is absent ---


def test_notebook_consumes_analytical_visualizations_external_evidence_role():
    code = _source("code")
    assert (
        "from pipeline.materialize_external_analytical_visualizations import "
        "materialize_external_analytical_visualizations" in code
    )
    assert '"analytical_visualizations" in evidence_by_role' in code
    assert 'load_verified_external_evidence(\n            "analytical_visualizations"\n        )' in code
    assert "materialize_external_analytical_visualizations" in _called_names()


def test_notebook_imports_and_calls_the_generic_derivation_module():
    code = _source("code")
    assert (
        "from pipeline.derive_external_analytical_visualization_evidence import "
        "derive_external_analytical_visualization_evidence" in code
    )
    assert "derive_external_analytical_visualization_evidence" in _called_names()


def test_notebook_direct_role_has_precedence_and_role_absence_selects_derivation():
    code = _source("code")
    visualizations_section_start = code.index('analytical_visualizations_relative_path = ""')
    candidate_assembly_index = code.index("assemble_candidate.build_release_candidate_handoff_readiness(")
    visualizations_section = code[visualizations_section_start:candidate_assembly_index]
    # Role absence no longer terminates unconditionally with
    # external_visual_evidence_role_missing -- it selects the Atlas-owned
    # derivation fallback instead, and the direct external role (when
    # present) still takes precedence over ever attempting derivation.
    assert '"external_visual_evidence_role_missing"' not in visualizations_section
    if_present_index = visualizations_section.index('if "analytical_visualizations" in evidence_by_role:')
    else_index = visualizations_section.index("\n    else:\n")
    derivation_call_index = visualizations_section.index("derive_external_analytical_visualization_evidence(")
    assert if_present_index < else_index < derivation_call_index


def test_notebook_calls_visualizations_materializer_only_after_external_model_materialization_succeeds():
    code = _source("code")
    materialization_call_index = code.index("materialize_external_fitted_model(\n")
    visualizations_call_index = code.index("materialize_external_analytical_visualizations(\n")
    candidate_assembly_index = code.index("assemble_candidate.build_release_candidate_handoff_readiness(")
    assert materialization_call_index < visualizations_call_index < candidate_assembly_index
    # Gated by the same run_state["blocked"] boundary every other
    # post-materialization stage uses -- never an unconditional call.
    visualizations_section_start = code.index(
        "analytical_visualizations_relative_path = \"\""
    )
    visualizations_section = code[visualizations_section_start:visualizations_call_index]
    assert 'if not run_state["blocked"]:' in visualizations_section


def test_notebook_direct_path_visualizations_materializer_receives_external_materialization_result():
    code = _source("code")
    assert "materialization_result=external_materialization_result," in code
    assert "external_visual_evidence=analytical_visual_evidence," in code
    assert 'external_evidence_reference=analytical_visual_evidence_ref["relative_path"],' in code
    assert 'external_evidence_sha256=analytical_visual_evidence_ref["sha256"],' in code
    assert 'visual_evidence_origin="external_evidence_index",' in code


def test_notebook_visualizations_materializer_writes_beneath_external_fitted_model_run_directory():
    code = _source("code")
    assert (
        'analytical_visualizations_output_relative_path = (\n'
        '        f"{external_fitted_model_run_relative_path}/analytical-visualizations.json"\n'
        "    )"
    ) in code
    assert "output_visualizations_path=analytical_visualizations_output_relative_path," in code


def test_notebook_split_identity_is_hash_verified_before_derivation():
    code = _source("code")
    assert 'split_manifest, split_manifest_ref = load_verified_external_evidence("split_identity")' in code
    split_load_index = code.index('load_verified_external_evidence("split_identity")')
    derivation_call_index = code.index("derive_external_analytical_visualization_evidence(\n")
    assert split_load_index < derivation_call_index


def test_notebook_derivation_receives_governed_inputs_without_absolute_external_root_in_output():
    code = _source("code")
    section_start = code.index("visual_evidence_derivation_result = derive_external_analytical_visualization_evidence(")
    section_end = code.index("if visual_evidence_derivation_result[\"status\"] == \"derived\":")
    section = code[section_start:section_end]
    assert "dataset_slug=dataset_slug," in section
    assert "external_root=external_root," in section
    assert "split_manifest=split_manifest," in section
    assert 'split_manifest_reference=split_manifest_ref["relative_path"],' in section
    assert 'split_manifest_sha256=split_manifest_ref["sha256"],' in section
    assert "final_model_manifest=final_model_manifest," in section
    assert 'final_model_manifest_reference=final_model_manifest_ref["relative_path"],' in section
    assert 'final_model_manifest_sha256=final_model_manifest_ref["sha256"],' in section
    assert "materialization_result=external_materialization_result," in section
    assert "output_derivation_evidence_path=derived_evidence_output_relative_path," in section


def test_notebook_derived_evidence_path_and_hash_feed_the_materializer():
    code = _source("code")
    assert 'external_evidence_reference=visual_evidence_derivation_result["derivation_evidence_path"],' in code
    assert 'external_evidence_sha256=visual_evidence_derivation_result["derivation_evidence_sha256"],' in code
    assert 'visual_evidence_origin="atlas_reference_derivation",' in code
    # The materializer's external_visual_evidence for the derived path is
    # built only from the derivation result's own reduced fields -- never a
    # different, re-guessed shape.
    payload_start = code.index('external_visual_evidence={\n                    "dataset_slug"')
    payload_end = code.index("},\n                external_evidence_reference=visual_evidence_derivation_result")
    payload_section = code[payload_start:payload_end]
    assert 'visual_evidence_derivation_result["dataset_slug"]' in payload_section
    assert 'visual_evidence_derivation_result["model_family"]' in payload_section
    assert 'visual_evidence_derivation_result["target_distribution"]' in payload_section
    assert 'visual_evidence_derivation_result["feature_importance"]' in payload_section
    assert 'visual_evidence_derivation_result["feature_importance_method"]' in payload_section


def test_notebook_derivation_block_is_recorded_and_stops_before_candidate_assembly():
    code = _source("code")
    section_start = code.index('if visual_evidence_derivation_result["status"] == "derived":')
    section_end = code.index("if visual_evidence_materialization_result is not None:")
    section = code[section_start:section_end]
    assert "else:" in section
    assert 'for reason in visual_evidence_derivation_result["blocking_reasons"]:' in section
    assert 'record_block(reason["code"], reason["message"], reason.get("field"))' in section
    block_else_index = code.index('for reason in visual_evidence_derivation_result["blocking_reasons"]:')
    candidate_assembly_index = code.index("assemble_candidate.build_release_candidate_handoff_readiness(")
    assert block_else_index < candidate_assembly_index


def test_notebook_records_block_and_leaves_visualizations_path_unresolved_when_materializer_blocks():
    code = _source("code")
    section_start = code.index("if visual_evidence_materialization_result is not None:")
    section_end = code.index("candidate_release_id = provisional_release_id")
    section = code[section_start:section_end]
    assert 'if visual_evidence_materialization_result["status"] == "materialized":' in section
    assert (
        'analytical_visualizations_relative_path = visual_evidence_materialization_result["visualizations_path"]'
        in section
    )
    assert 'for reason in visual_evidence_materialization_result["blocking_reasons"]:' in section
    assert 'record_block(reason["code"], reason["message"], reason.get("field"))' in section
    # A present-but-invalid external role is never silently bypassed: the
    # direct-path materializer call result flows into this exact same
    # blocked-vs-materialized branch, whether it came from the direct
    # external_evidence_index path or the atlas_reference_derivation
    # fallback path.
    assert section.startswith("if visual_evidence_materialization_result is not None:")


def test_notebook_does_not_mutate_the_external_evidence_index_or_write_into_the_external_project():
    code = _source("code")
    visualizations_section_start = code.index('analytical_visualizations_relative_path = ""')
    candidate_assembly_index = code.index("assemble_candidate.build_release_candidate_handoff_readiness(")
    visualizations_section = code[visualizations_section_start:candidate_assembly_index]
    # "external_evidence_index" appears only inside the
    # visual_evidence_origin="external_evidence_index" provenance-label
    # string literal, never as a mutation of the actual index artifact.
    assert 'external_evidence_index_relative_path' not in visualizations_section
    assert "external_evidence_index.json" not in visualizations_section
    assert ".write_text(" not in visualizations_section
    assert "write_governed_json" not in visualizations_section
    assert "external_root /" not in visualizations_section
    assert "external_root.write" not in visualizations_section


def test_notebook_orchestrates_release_candidate_assembly_from_compatible_roles():
    code = _source("code")
    assert "assemble_candidate.build_release_candidate_handoff_readiness(" in code
    assert "assemble_candidate.build_release_candidate_input(" in code
    assert "assemble_candidate.assemble_release_candidate(" in code
    assert "publisher.validate.materialize_telco_validation_run" not in code
    # Project Spec S0188: model_card is materialized via the generic external
    # candidate-support materializer and public_context references the
    # governed dataset-context document directly -- neither is left as an
    # unresolved "" placeholder. Project Spec S0193: visualizations is now
    # resolved the same way, via the external analytical-visualizations
    # materializer, rather than left unresolved.
    assert '"model_card": model_card_relative_path' in code
    assert '"public_context": dataset_context_relative_path' in code
    assert '"visualizations": analytical_visualizations_relative_path' in code
    assert "model-card.json" in code
    assert "candidate_handoff_readiness[\"is_release_candidate_input_ready\"]" in code


def test_notebook_materializes_external_model_card_via_generic_support_materializer():
    code = _source("code")
    assert (
        "from pipeline.materialize_external_candidate_support import "
        "materialize_external_candidate_support" in code
    )
    assert "materialize_external_candidate_support" in _called_names()
    assert 'external_candidate_support_result["status"] == "materialized"' in code
    assert (
        "model_card_relative_path = external_candidate_support_result[\"model_card_path\"]"
        in code
    )
    materializer_call_index = code.index("materialize_external_candidate_support(\n")
    candidate_references_index = code.index("candidate_artifact_references = {")
    assert materializer_call_index < candidate_references_index


def test_notebook_candidate_block_reasons_use_scalar_field_per_missing_role():
    code = _source("code")
    # Project Spec S0188: one record_block() call per unready role, each
    # with a scalar string field -- never the whole not_ready_roles list
    # passed as a single field value (that collapses the terminal
    # validated-run artifact to terminal_result_schema_invalid).
    assert 'candidate_handoff_readiness["not_ready_roles"],' not in code
    assert "for unready_role in candidate_handoff_readiness[\"not_ready_roles\"]:" in code
    assert (
        'record_block(\n                "candidate_role_unavailable",'
    ) in code
    block_section_start = code.index("for unready_role in candidate_handoff_readiness")
    block_section = code[block_section_start:block_section_start + 900]
    assert "unready_role,\n            )" in block_section


def test_notebook_does_not_borrow_historical_model_card_or_visualizations():
    code = _source("code")
    candidate_section_start = code.index("candidate_artifact_references = {")
    candidate_section_end = code.index("candidate_handoff_readiness = assemble_candidate")
    candidate_section = code[candidate_section_start:candidate_section_end]
    assert "pipeline/training-runs" not in candidate_section
    assert "releases/candidates" not in candidate_section
    assert "releases/release-" not in candidate_section


def test_notebook_orchestrates_publisher_structural_validation_and_conditional_manifest():
    code = _source("code")
    assert "publisher_validate.run(" in code
    assert "publisher_manifest.run(" in code
    assert "publisher_validation_result.get(\"validation_outcome\") == \"accepted\"" in code
    assert "new_run_dirs = sorted(" in code
    assert "assert len(new_run_dirs) == 1" in code
    assert "materialize_telco_validation_run" not in code


def test_notebook_materializes_one_validated_run_terminal_result():
    code = _source("code")
    assert "from pipeline import validated_run" in code
    assert "validated_run.materialize_validated_run_terminal_result(" in code
    assert 'terminal_status = "blocked" if run_state["blocked"] else "completed"' in code
    assert "write_governed_json(terminal_result_relative_path, validated_run_terminal_result)" in code


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


def test_notebook_now_requires_the_extended_orchestration_calls():
    code = _source("code")
    calls = _called_names()
    referenced = _referenced_attribute_paths()
    assert "materialize_external_fitted_model" in calls
    required_paths = {
        "generate_inference_bundle.materialize_governed_inference_bundle",
        "assemble_candidate.build_release_candidate_input",
        "assemble_candidate.assemble_release_candidate",
        "publisher_validate.run",
        "publisher_manifest.run",
        "validated_run.materialize_validated_run_terminal_result",
    }
    assert required_paths.issubset(referenced), required_paths - referenced
    assert "from pipeline.materialize_external_fitted_model import materialize_external_fitted_model" in code


def test_notebook_tests_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")


# --- Project Spec S0186: canonical tie-break projection ---------------------


def test_notebook_does_not_assign_raw_criteria_applied_to_tie_break_criteria():
    code = _source("code")
    assert '"tie_break_criteria": selection_choice["criteria_applied"]' not in code
    assert '"tie_break_criteria": canonical_tie_break_criteria' in code


def test_notebook_maps_producer_brier_score_criterion_to_canonical_criterion():
    code = _source("code")
    assert '"lower_validation_brier_score": "brier_score"' in code
    assert "CANONICAL_TIE_BREAK_CRITERION_MAP" in code


def test_notebook_tie_break_projection_produces_order_and_observed_values():
    code = _source("code")
    assert '"order": order,' in code
    assert '"observed_values": [' in code
    assert '{"candidate_id": first_candidate_id, "value": first_value}' in code
    assert '{"candidate_id": second_candidate_id, "value": second_value}' in code


def test_notebook_resolves_tie_break_candidate_identities_from_verified_candidate_evidence():
    code = _source("code")
    assert "def project_tie_break_criteria(criteria_applied, candidates):" in code
    assert "def _resolve_candidate_id_by_validation_metric(value, metric_name, candidates):" in code
    assert (
        'project_tie_break_criteria(\n        selection_choice["criteria_applied"], '
        'model_selection_candidates["candidates"]\n    )'
    ) in code


def test_notebook_retains_all_four_scientific_selection_candidates():
    code = _source("code")
    assert (
        '"candidates": [{"candidate_id": c["model_id"], "model_family": c["model_id"], '
        '"estimator_identity": {"library": "scikit-learn", "class_name": c["family"]}} '
        'for c in model_selection_candidates["candidates"]]'
    ) in code
    # No HGB-only filter applied before this list comprehension consumes the
    # full verified candidates array.
    assert "if c[\"model_id\"] == \"hist_gradient_boosting\"" not in code


def test_notebook_blocks_unsupported_or_ambiguous_tie_break_projection():
    code = _source("code")
    assert "class TieBreakProjectionBlocked(Exception):" in code
    for reason_code in (
        "unsupported_tie_break_criterion",
        "ambiguous_tie_break_candidate_match",
        "tie_break_winner_not_declared_candidate",
        "tie_break_winner_inconsistent_with_canonical_observation",
    ):
        assert reason_code in code
    assert "except TieBreakProjectionBlocked as exc:" in code
    assert "tie_break_projection_blocked_reason = {" in code
    assert "if tie_break_projection_blocked_reason is None:" in code


def test_notebook_invokes_materializer_only_after_staging_evidence_is_built():
    code = _source("code")
    staged_index = code.index('staged_selection_path = _write_staged_json("model-selection-evidence.json"')
    materializer_call_index = code.index("external_materialization_result = materialize_external_fitted_model(")
    assert staged_index < materializer_call_index
    projection_index = code.index("canonical_tie_break_criteria = project_tie_break_criteria(")
    assert projection_index < staged_index < materializer_call_index


# --- Project Spec S0187: execution-contract source-mode precondition -------


def test_notebook_checks_execution_contract_source_mode_before_bundle_generation():
    code = _source("code")
    precondition_index = code.index(
        "execution_contract_precondition_full = json.loads(\n"
        "        (repo_root / execution_contract_relative_path).read_text(encoding=\"utf-8\")\n"
        "    )"
    )
    bundle_call_index = code.index(
        "generate_inference_bundle.materialize_governed_inference_bundle("
    )
    assert precondition_index < bundle_call_index
    assert 'execution_contract_precondition_full.get("contract_version") != "execution_contract.v1"' in code
    assert (
        'execution_contract_precondition_full.get("model_source_mode") != '
        '"validated_external_fitted_model"'
    ) in code


def test_notebook_records_block_and_skips_bundle_generation_on_precondition_failure():
    code = _source("code")
    assert 'record_block(\n            "execution_contract_version_invalid",' in code
    assert 'record_block(\n            "execution_contract_model_source_mode_invalid",' in code
    # The bundle-generation block is reguarded by its own `if not
    # run_state["blocked"]:` after the precondition check, so a block
    # recorded there skips the producer call entirely.
    precondition_block_index = code.index('if not run_state["blocked"]:\n    execution_contract_precondition_full')
    reguard_index = code.index(
        'if not run_state["blocked"]:\n    inference_bundle_output_relative_path'
    )
    assert precondition_block_index < reguard_index


def test_notebook_precondition_does_not_mutate_execution_contract():
    code = _source("code")
    precondition_section_start = code.index("execution_contract_precondition_full = json.loads(")
    bundle_call_index = code.index(
        "generate_inference_bundle.materialize_governed_inference_bundle("
    )
    precondition_section = code[precondition_section_start:bundle_call_index]
    assert "write_governed_json" not in precondition_section
    assert ".write_text(" not in precondition_section


def test_notebook_precondition_uses_repository_rooted_relative_path_not_hardcoded_absolute():
    code = _source("code")
    precondition_section_start = code.index("execution_contract_precondition_full = json.loads(")
    precondition_section_end = code.index("record_block(\n            \"execution_contract_model_source_mode_invalid\"")
    precondition_section = code[precondition_section_start:precondition_section_end]
    assert "repo_root / execution_contract_relative_path" in precondition_section
    assert "/home/" not in precondition_section
    assert "/workspace/" not in precondition_section


def test_notebook_never_requires_real_telco_checkout_or_model_bytes_to_be_parsed():
    # The notebook is valid, parseable Python source in every code cell --
    # this test itself never executes the notebook or touches the external
    # Telco project, matching the static/synthetic requirement for S0184.
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))
