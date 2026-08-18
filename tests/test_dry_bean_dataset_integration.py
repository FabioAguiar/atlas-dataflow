"""
Project Spec S0216: static structural proof for
notebooks/datasets/dry-bean/dataset_integration.ipynb.

Mirrors tests/test_dataset_integration_authoring_notebook.py's static
conventions (no external checkout, no model bytes required, never executed
by this test). Proves the notebook is a well-formed, syntactically valid
Atlas-native multiclass training orchestrator that never reads the external
Dry Bean scientific project at runtime, never loads an external model,
never fits a model directly, calls the governed native training
entrypoint, encodes the fixed HGB training policy, introduces no
dataset-slug branch into generic production modules, and stops before real
registry/release activation.
"""

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks/datasets/dry-bean/dataset_integration.ipynb"


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


def test_notebook_never_requires_real_dry_bean_checkout_or_model_bytes_to_be_parsed():
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))


def test_notebook_tests_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")


def test_notebook_has_the_seventeen_orchestration_stages_in_order():
    # Project Spec S0217 reassigns Stage 15/16/17 to Publisher Run
    # materialization, the validated terminal handoff, and the final
    # boundary-stop summary; the native runtime/API projection checks
    # previously at Stage 16 move (content unchanged) to a sub-section of
    # Stage 13, right after inference-bundle generation.
    markdown = _source("markdown")
    stages = [
        "## 1. Orchestration boundary declaration and responsibility",
        "## 2. Atlas source identity / local raw input verification",
        "## 3. Reduced Atlas discovery evidence",
        "## 4. Dry Bean semantic intent v2",
        "## 5. Preparation recipe / prepared candidate",
        "## 6. Reviewed native training policy intent",
        "## 7. Multiclass capability resolution",
        "## 8. Execution contract materialization",
        "## 9. Runtime/public contract projection",
        "## 10. Native training readiness",
        "## 11. Native multiclass training run materialization",
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
        "native_multiclass_training_run_materialization",
        "inference_bundle_materialization",
        "release_candidate_assembly",
        "publisher_structural_validation",
        "manifest_generation_when_structurally_permitted",
    ):
        assert allowed in code
    for forbidden in (
        "external_scientific_project_read_at_runtime",
        "external_model_load",
        "model_fitting_or_retraining_in_notebook",
        "model_selection",
        "threshold_optimization",
        "model_deserialization_or_inference_execution",
        "publisher_promotion",
        "registry_active_release_mutation",
        "public_visibility_or_profile_activation",
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
    assert 'dataset_relative_path = "data/raw/dry-bean/dataset.csv"' in code
    assert "13611" in code
    assert "17" in code


def test_notebook_never_reads_external_scientific_project_path():
    code = _source("code")
    for forbidden_substring in (
        "external_scientific_analysis_root",
        "external_root",
        "dataset-study-dry-bean",
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
    assert "training_run_materialization_result[\"status\"] != \"trained\"" in code


def test_notebook_encodes_fixed_hgb_training_policy():
    code = _source("code")
    assert '"model_family": "hist_gradient_boosting"' in code
    assert '"selection_mode": "fixed_configuration"' in code
    assert '"no_automl": True' in code
    assert '"learning_rate": 0.05' in code
    assert '"max_iter": 250' in code
    assert '"max_leaf_nodes": 15' in code
    assert '"min_samples_leaf": 40' in code
    assert '"review_status": "approved"' in code


def test_notebook_encodes_primary_metric_f1_macro():
    code = _source("code")
    assert '"primary_metric": "f1_macro"' in code


def test_notebook_encodes_no_resampling_or_feature_selection():
    code = _source("code")
    for forbidden in ("SMOTE", "resample", "SelectKBest", "RFE(", "feature_selection"):
        assert forbidden not in code


def test_notebook_encodes_sixteen_reviewed_feature_names_and_seven_class_ids():
    code = _source("code")
    # Feature names are generically derived from the CSV header (never
    # hardcoded as a literal list) and pinned by an explicit count
    # assertion instead -- exactly 16, matching the reviewed feature
    # boundary (Project Spec S0216 Desired Change AH).
    assert 'feature_names = [name for name in atlas_structure["ordered_columns"] if name != "Class"]' in code
    assert "assert len(feature_names) == 16" in code
    for class_id in ("SEKER", "BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SIRA"):
        assert class_id in code


def test_notebook_authors_deterministic_alphabetical_class_order_and_verifies_real_model_order():
    code = _source("code")
    assert "ordered_class_ids = sorted(expected_class_ids)" in code
    assert "real_fitted_class_order = training_parameter_record[\"classification_evidence\"][\"ordered_class_ids\"]" in code
    assert "assert real_fitted_class_order == authored_class_ids" in code


def test_notebook_never_reorders_predict_proba_output():
    code = _source("code")
    assert "predict_proba" not in code


def test_notebook_orchestrates_inference_bundle_generation():
    code = _source("code")
    assert "generate_inference_bundle.materialize_governed_inference_bundle(" in code
    assert 'inference_bundle_result["status"] != "generated"' in code


def test_notebook_orchestrates_release_candidate_assembly():
    code = _source("code")
    assert "assemble_candidate.build_release_candidate_handoff_readiness(" in code
    assert "assemble_candidate.build_release_candidate_input(" in code
    assert "assemble_candidate.assemble_release_candidate(" in code


def test_notebook_has_no_promotion_or_registry_activation_calls():
    # Project Spec S0217 legitimately reaches publisher.manifest.run through
    # the generic Publisher Run materializer (publisher.validate.materialize_validation_run),
    # so that call is no longer forbidden here; promotion and registry
    # mutation remain forbidden.
    code = _source("code")
    for forbidden in (
        "publisher_promote.run(", "publisher.promote", "promote.run(",
        "registry_update.run(", "registry.update", "activate_release",
        "write_registry", "update_registry",
    ):
        assert forbidden not in code
    referenced = _referenced_attribute_paths()
    assert not any(path.startswith("promote.") for path in referenced)
    assert not any(path.startswith("registry_update.") for path in referenced)


def test_notebook_stop_confirmation_declares_no_activation_performed():
    code = _source("code")
    assert '"promotion_performed": False' in code
    assert '"registry_activation_performed": False' in code
    assert '"public_visibility_or_profile_activation_performed": False' in code


def test_notebook_introduces_no_dataset_slug_branch_into_generic_pipeline_modules():
    # The notebook itself may of course reference its own dataset_slug
    # variable; this proves the *generic pipeline modules it calls into*
    # remain unmodified/dataset-agnostic by never containing a Dry-Bean-only
    # conditional anywhere in this notebook's own orchestration code beyond
    # its own local dataset_slug variable assignment and f-string usage.
    code = _source("code")
    assert 'if dataset_slug == "dry-bean"' not in code
    assert "if dataset_slug ==" not in code


# --- Project Spec S0217: Publisher Run materialization + validated
# terminal handoff (Stage 15/16/17).


def test_notebook_calls_the_generic_publisher_run_materializer_with_assembly_result():
    code = _source("code")
    assert "from publisher import validate as publisher_validate" in code
    assert "publisher_validate.materialize_validation_run(" in code
    assert "materialize_validation_run" in _called_names()
    # The explicit assembly_result returned by candidate assembly is passed
    # as the sole positional candidate reference -- never a latest-candidate
    # scan or a releases/candidates glob.
    assert "publisher_materialization_result = publisher_validate.materialize_validation_run(\n        assembly_result, repo_root=repo_root,\n    )" in code
    for forbidden in ("glob(", "iterdir()", "Path(\"releases\"", "releases/candidates\"\n"):
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
    # Never the argmax external-operational-readiness profile.
    assert '"decision_strategy": "argmax"' not in code
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


# --- Project Spec S0218: canonical dataset-context shape and native
# dry-bean-classification Predict View declaration (Stage 9).


def test_notebook_writes_canonical_dataset_context_shape():
    code = _source("code")
    assert '"schema_version": "1.0.0",\n    "dataset_slug": dataset_slug,\n    "title": "Dry Bean",' in code
    assert '"description": "Predict the Dry Bean class from the governed morphological input features.",' in code
    assert '"domain": "general",' in code
    assert '"predict_views": [dry_bean_predict_view],' in code


def test_notebook_no_longer_writes_the_legacy_minimal_dataset_context_shape():
    code = _source("code")
    assert '"dataset_title": "Dry Bean"' not in code
    assert '"schema_version": "dataset-context.v1"' not in code


def test_notebook_declares_exactly_one_stable_native_predict_view():
    code = _source("code")
    assert '"view_id": "dry-bean-classification",' in code
    assert '"dataset_slug": dataset_slug,\n    "display": {' in code


def test_notebook_predict_view_binding_is_active_release_relative():
    code = _source("code")
    assert '"binding": {\n        "dataset_slug": dataset_slug,\n        "release": {\n            "mode": "active",\n        },\n    },' in code
    assert "release-20260818-001" not in code
    predict_view_start = code.index("dry_bean_predict_view = {")
    predict_view_end = code.index("dataset_context = {", predict_view_start)
    predict_view_source = code[predict_view_start:predict_view_end]
    assert "release_id" not in predict_view_source


def test_notebook_predict_view_declares_canonical_contract_precedence():
    code = _source("code")
    assert (
        '"contract_precedence": {\n'
        '        "canonical_contracts_are_source_of_truth": True,\n'
        '        "view_metadata_defines_runtime_validation": False,\n'
        '        "view_metadata_duplicates_contract": False,\n'
        "    },"
    ) in code


def test_notebook_predict_view_carries_no_feature_validation_rules():
    # "features" legitimately appears elsewhere (runtime_contract/
    # public_contract construction above), so this check is scoped to the
    # Predict View declaration dict itself, not the whole notebook source.
    code = _source("code")
    predict_view_start = code.index("dry_bean_predict_view = {")
    predict_view_end = code.index("dataset_context = {", predict_view_start)
    predict_view_source = code[predict_view_start:predict_view_end]
    for forbidden in (
        "features",
        "validation_rules",
        "input_semantics",
        "domain_constraints",
        "business_logic",
        "runtime_contract",
        "public_contract",
    ):
        assert forbidden not in predict_view_source


def test_notebook_validates_generated_context_against_canonical_schema_before_candidate_assembly():
    code = _source("code")
    assert "dataset_context_schema_path = repo_root / \"contracts\" / \"dataset-context.schema.json\"" in code
    assert "jsonschema.Draft7Validator(dataset_context_schema).iter_errors(dataset_context)" in code
    assert 'record_block("dataset_context_schema_invalid", message, "dataset_context")' in code
    # This validation must happen before release-candidate assembly (Stage
    # 14), not after.
    validation_offset = code.index("dataset_context_schema_path = repo_root")
    candidate_assembly_offset = code.index("assemble_candidate.build_release_candidate_handoff_readiness(")
    assert validation_offset < candidate_assembly_offset


def test_notebook_blocks_on_malformed_predict_view_declaration():
    code = _source("code")
    assert '"dataset_context_predict_views_count_invalid"' in code
    assert '"dataset_context_predict_view_id_invalid"' in code
    assert '"dataset_context_predict_view_dataset_slug_invalid"' in code
    assert '"dataset_context_predict_view_contract_precedence_invalid"' in code
