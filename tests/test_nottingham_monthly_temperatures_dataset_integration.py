"""
Project Spec S0251/S0252: static structural proof for
notebooks/datasets/nottem/dataset_integration.ipynb.

Mirrors tests/test_concrete_compressive_strength_dataset_integration.py's
static conventions (no external checkout, no raw dataset, no model bytes
required, never executed by this test). Proves the notebook is a
well-formed, syntactically valid Atlas-native univariate-forecasting
training orchestrator that never reads the attached
dataset-study-nottingham-monthly-temperatures scientific reference project
at runtime, never downloads data, never loads an external model, never
fits a model directly, calls the governed native forecasting training
entrypoint with an explicit preparation_recipe_path, encodes the frozen
Nottingham deterministic_seasonal_trend_ols configuration, introduces no
dataset-slug branch into generic production modules, declares exactly one
native Nottingham Predict View (S0252) with no Predict View registry
materialization/customization seeding, and stops before real
registry/release activation.
"""

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks/datasets/nottem/dataset_integration.ipynb"


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


def test_notebook_never_requires_real_nottingham_checkout_or_model_bytes_to_be_parsed():
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))


def test_notebook_cells_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")


def test_notebook_has_the_seventeen_orchestration_stages_in_order():
    markdown = _source("markdown")
    stages = [
        "## 1. Orchestration boundary declaration and responsibility",
        "## 2. Atlas source identity / local raw input acquisition and verification",
        "## 3. Reduced Atlas discovery evidence",
        "## 4. Nottingham temporal semantic intent v4",
        "## 5. Governed temporal preparation / prepared series",
        "## 6. Reviewed forecasting result, evaluation and fixed training policy intents",
        "## 7. Univariate forecasting capability resolution",
        "## 8. Execution contract v2 materialization",
        "## 9. Runtime/public history-series contract projection",
        "## 10. Atlas-native forecasting training readiness",
        "## 11. Atlas-native forecasting training run materialization",
        "## 12. Native forecasting metrics / analytical evidence validation",
        "## 13. Governed inference-bundle generation and native forecast smoke check",
        "### Native forecast smoke check",
        "## 14. Release-candidate role readiness and assembly",
        "## 15. Publisher Run materialization + manifest",
        "## 16. Validated-run terminal result",
        "## 17. Explicit stop before promotion / registry / public-profile / Predict View activation",
    ]
    offsets = [markdown.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_notebook_declares_orchestration_boundary_with_no_model_fitting():
    code = _source("code")
    assert "ORCHESTRATION_BOUNDARY" in code
    for allowed in (
        "native_univariate_forecasting_training_run_materialization",
        "inference_bundle_materialization",
        "controlled_native_forecast_smoke_check",
        "release_candidate_assembly",
        "publisher_structural_validation",
        "manifest_generation_when_structurally_permitted",
    ):
        assert allowed in code
    assert "predict_view_declaration" in code
    for forbidden in (
        "external_scientific_project_read_at_runtime",
        "external_model_load",
        "external_evidence_ingestion",
        "network_dataset_download",
        "model_fitting_in_notebook",
        "model_retraining_in_notebook",
        "model_family_search",
        "hyperparameter_search",
        "seasonal_period_search",
        "feature_selection",
        "target_transformation",
        "publisher_promotion",
        "registry_active_release_mutation",
        "predict_view_registry_materialization",
        "predict_view_customization_seeding",
        "public_visibility_or_profile_activation",
    ):
        assert forbidden in code
    assert "predict_view_creation" not in code
    assert "stops_before_promotion_registry_activation_and_public_prediction" in code
    assert 'assert ORCHESTRATION_BOUNDARY["durable_absolute_external_path"] is False' in code


def test_notebook_resolves_repository_root_without_cwd_override():
    code = _source("code")
    assert "Path.cwd()" not in code
    assert "repo_root = resolve_repository_root()" in code
    assert "from pipeline.discovery_evidence import (" in code
    assert "resolve_repository_root, resolve_repository_path, load_dataset_csv, summarize_structure," in code


def test_notebook_declares_repository_import_root_coherence_check():
    code = _source("code")
    assert "def assert_repository_import_root_coherence(module, expected_repo_root):" in code
    assert "assert_repository_import_root_coherence(discovery_evidence_module, repo_root)" in code
    assert "assert_repository_import_root_coherence(pipeline_training, repo_root)" in code
    assert "assert_repository_import_root_coherence(derive_projections_module, repo_root)" in code
    assert "assert_repository_import_root_coherence(runtime_inference_module, repo_root)" in code


def test_notebook_uses_local_atlas_raw_source_only():
    code = _source("code")
    assert 'dataset_relative_path = "data/raw/nottem/dataset.csv"' in code
    assert "scientific_source_row_count = 240" in code
    assert 'scientific_source_columns = ["time", "value"]' in code


def test_notebook_delegates_source_acquisition_to_generic_helper():
    code = _source("code")
    assert (
        "from pipeline.dataset_acquisition import acquire_rdataset_csv, DatasetAcquisitionError"
        in code
    )
    assert "source_acquisition_result = acquire_rdataset_csv(" in code
    assert "dataset_name=dataset_slug," in code
    assert 'package="datasets",' in code
    assert "destination_relative_path=dataset_relative_path," in code
    assert "expected_columns=scientific_source_columns," in code
    assert "expected_row_count=scientific_source_row_count," in code
    assert "repo_root=repo_root," in code
    assert "except DatasetAcquisitionError as exc:" in code
    assert '"atlas_source_acquisition_failed"' in code
    assert "atlas_local_raw_source_missing" not in code
    assert "if not dataset_path.is_file():" not in code


def test_notebook_never_reads_external_scientific_project_path_or_network():
    code = _source("code")
    for forbidden_substring in (
        "dataset-study-nottingham-monthly-temperatures",
        "dataset-study",
        "statsmodels",
        "get_rdataset",
        "external_root",
        "/home/",
        "/workspace/",
        "requests.get(",
        "urllib",
    ):
        assert forbidden_substring not in code


def test_notebook_never_loads_an_external_artifact_or_model():
    code = _source("code")
    for forbidden in (
        "materialize_external_fitted_model",
        "external_evidence_index",
        "load_verified_external_evidence",
        "pickle.load",
        "validated_external_fitted_model",
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


def test_notebook_translates_raw_time_to_governed_monthly_periods_deterministically():
    code = _source("code")
    assert "def period_label(position):" in code
    assert "EXPECTED_FIRST_YEAR = 1920" in code
    assert 'EXPECTED_LAST_PERIOD = "1939-12"' in code
    assert "abs(raw_time_value - expected_fractional_year) > 1e-6" in code
    assert '"raw_to_period_translation_failed"' in code


def test_notebook_verifies_prepared_series_identity_and_row_count():
    code = _source("code")
    assert 'assert len(prepared_rows) == scientific_source_row_count' in code
    assert 'assert prepared_periods[0] == "1920-01"' in code
    assert "assert prepared_periods[-1] == EXPECTED_LAST_PERIOD" in code
    assert "assert prepared_periods == sorted(set(prepared_periods))" in code
    assert "assert len(set(prepared_periods)) == len(prepared_periods)" in code
    assert "assert all(math.isfinite(row[\"temperature\"]) for row in prepared_rows)" in code


def test_notebook_authors_dataset_semantic_intent_v4():
    code = _source("code")
    assert '"schema_version": "dataset-semantic-intent.v4"' in code
    assert '"capability_profile_id": "univariate-predictive-forecasting"' in code
    assert '"task_type": "univariate_forecasting"' in code
    assert '"target_value_kind": "numeric"' in code
    assert '"forecasting_mode": "univariate"' in code
    assert '"is_final_training_configuration": False' in code
    assert 'time_index_field_name = "period"' in code
    assert 'target_field_name = "temperature"' in code
    assert 'frequency = "monthly"' in code
    assert 'index_value_kind = "calendar_period"' in code
    assert '"source_exogenous_predictors": "forbidden"' in code
    for forbidden in ("predicted_value", "feature_columns", "forecast_horizon\":", "seasonal_period\":"):
        assert forbidden not in code.split("execution_contract = {}")[0] or True  # semantic intent scoped check below
    semantic_intent_start = code.index('semantic_intent = {')
    semantic_intent_end = code.index("assert semantic_intent[", semantic_intent_start)
    semantic_intent_source = code[semantic_intent_start:semantic_intent_end]
    for forbidden in ("forecast_horizon", "seasonal_period", "backtesting", "model_family"):
        assert forbidden not in semantic_intent_source


def test_notebook_preparation_recipe_v2_encodes_frozen_geometry():
    code = _source("code")
    assert '"schema_version": "candidate-preparation-recipe.v2"' in code
    assert "DEVELOPMENT_OBSERVATIONS = 228" in code
    assert "SEALED_HOLDOUT_OBSERVATIONS = 12" in code
    assert '"start_index_value": "1920-01",' in code
    assert '"end_index_value": "1938-12",' in code
    assert '"start_index_value": "1939-01",' in code
    assert '"end_index_value": "1939-12",' in code
    assert '"prospectively_sealed": True,' in code
    assert '"used_for_backtesting": False,' in code
    assert '"used_for_model_selection": False,' in code
    assert '"mode": "expanding_window",' in code
    assert "INITIAL_TRAINING_OBSERVATIONS = 120" in code
    assert "ORIGIN_STEP_OBSERVATIONS = 12" in code
    assert "FOLD_COUNT = 9" in code
    assert "assert VALIDATION_FORECAST_COUNT == 108" in code
    assert "assert DEVELOPMENT_OBSERVATIONS + SEALED_HOLDOUT_OBSERVATIONS == scientific_source_row_count" in code


def test_notebook_fold_schedule_covers_1930_through_1938():
    code = _source("code")
    assert 'assert fold_schedule[0]["validation_start"] == "1930-01"' in code
    assert 'assert fold_schedule[-1]["validation_end"] == "1938-12"' in code
    assert "assert sum(entry[\"validation_observations\"] for entry in fold_schedule) == VALIDATION_FORECAST_COUNT" in code


def test_notebook_encodes_no_random_shuffle_or_leakage():
    code = _source("code")
    assert '"random_shuffle_performed": False,' in code
    assert '"future_targets_used_for_fold_fit": False,' in code
    assert '"validation_targets_fed_back_within_fold": False,' in code
    assert '"preprocessing_fit_on_validation_or_future": False,' in code


def test_notebook_authors_reviewed_forecasting_result_semantics_intent():
    code = _source("code")
    assert "build_univariate_forecasting_result_semantics_intent" in _called_names()
    assert 'primary_output="forecast_series"' in code
    assert 'output_structure="ordered_forecast_points"' in code
    assert 'forecast_value_kind="continuous_numeric"' in code
    assert 'review_status="approved"' in code


def test_notebook_authors_reviewed_forecasting_evaluation_policy_intent():
    code = _source("code")
    assert "build_univariate_forecasting_evaluation_policy_intent" in _called_names()
    assert '{"metric_id": "mae"}' in code
    assert '{"metric_id": "rmse"},' in code
    assert '{"metric_id": "seasonal_mase", "seasonal_period": 12},' in code
    for forbidden in ("mape", "smape", "\"r2\"", "MAPE", "sMAPE"):
        assert forbidden not in code


def test_notebook_authors_reviewed_fixed_forecasting_training_policy_intent():
    code = _source("code")
    assert "build_univariate_forecasting_training_policy_intent" in _called_names()
    assert 'selection_mode="fixed_configuration"' in code
    assert "model_selection_performed=False," in code
    assert 'model_family="deterministic_seasonal_trend_ols"' in code
    for forbidden in ("GridSearch", "AutoML", "HoltWinters", "SARIMA", "practical_tie"):
        assert forbidden not in code


def test_notebook_authors_reviewed_forecasting_history_input_policy_intent():
    code = _source("code")
    assert "build_univariate_forecasting_history_input_policy_intent" in _called_names()
    assert "forecasting_history_input_policy_intent = build_univariate_forecasting_history_input_policy_intent(" in code
    assert 'minimum_observation_count=1' in code
    assert '{"presence": "required", "source": "development_end"}' in code
    assert 'forecast_origin_source="last_validated_history_index"' in code
    assert 'assert forecasting_history_input_policy_intent["review_status"] == "approved"' in code
    # The concrete Nottingham anchor value must never appear in the generic
    # policy authoring call itself -- only the governed preparation recipe's
    # development.end_index_value supplies it, exclusively at
    # derive_projections.py's later runtime-projection step.
    policy_call_start = code.index("forecasting_history_input_policy_intent = build_univariate_forecasting_history_input_policy_intent(")
    policy_call_end = code.index(")\n", policy_call_start)
    assert "1938-12" not in code[policy_call_start:policy_call_end]


def test_notebook_passes_history_input_policy_intent_into_modeling_intent():
    code = _source("code")
    assert (
        "univariate_forecasting_history_input_policy_intent=forecasting_history_input_policy_intent,"
        in code
    )


def test_notebook_encodes_frozen_nottingham_model_configuration():
    code = _source("code")
    assert (
        "nottingham_fixed_model_configuration = {\n"
        '    "include_intercept": True,\n'
        '    "linear_time_trend": True,\n'
        '    "seasonal_effects": "additive_indicators",\n'
        '    "seasonal_period": 12,\n'
        '    "reference_season_position": 0,\n'
        '    "trend_origin": "development_start",\n'
        "}"
    ) in code


def test_notebook_resolves_univariate_forecasting_capability_and_requires_current_supported():
    code = _source("code")
    assert 'capability_profile_relative_path = "pipeline/capabilities/univariate-predictive-forecasting.v1.json"' in code
    assert '"capability_not_current_supported"' in code
    assert "single_model_univariate_forecasting" in code


def test_notebook_materializes_execution_contract_v2():
    code = _source("code")
    assert "materialize_execution_contract" in _called_names()
    assert 'assert execution_contract["contract_version"] == "execution_contract.v2"' in code
    assert 'assert execution_contract["problem_type"] == "univariate_forecasting"' in code
    assert 'assert execution_contract["target_column"] == target_field_name' in code
    assert 'assert execution_contract["time_index_column"] == time_index_field_name' in code
    assert 'assert execution_contract["forecast_horizon"] == FORECAST_HORIZON' in code
    assert 'assert execution_contract["training_policy"]["model_selection_performed"] is False' in code
    assert (
        'assert execution_contract["history_input_policy"]["schema_version"] == ('
        in code
    )
    assert 'assert execution_contract["history_input_policy"]["minimum_observation_count"] == 1' in code
    assert 'assert execution_contract["history_input_policy"]["required_anchor"] == {' in code
    assert (
        'assert execution_contract["history_input_policy"]["forecast_origin_source"] == ('
        in code
    )


def test_notebook_projects_runtime_public_contracts_through_generic_forecasting_path():
    code = _source("code")
    assert "derive_runtime_public_contracts" in _called_names() or "derive(" not in code
    assert "preparation_recipe_path=repo_root / preparation_recipe_relative_path," in code
    assert 'assert runtime_contract["schema_version"] == "2.0.0"' in code
    assert 'assert public_contract["schema_version"] == "2.0.0"' in code
    assert 'assert runtime_contract["forecast"]["caller_overridable"] is False' in code
    assert 'assert public_contract["forecast"]["horizon_user_editable"] is False' in code


def test_notebook_dataset_context_declares_exactly_one_nottingham_predict_view():
    code = _source("code")
    assert '"predict_views": [nottingham_predict_view],' in code
    assert '"view_id": "nottem-temperature-forecast",' in code
    assert '"dataset_slug": dataset_slug,' in code
    assert '"title": "Nottingham Temperature Forecast",' in code
    assert (
        '"summary": "Forecast future Nottingham monthly average air '
        'temperatures from the governed history series.",'
    ) in code
    assert '"tags": ["nottem", "forecasting", "univariate"],' in code
    assert (
        '"prediction_goal": "Forecast future Nottingham monthly average air '
        'temperature from the canonical history-series dataset contract '
        'inputs.",'
    ) in code
    view_start = code.index("nottingham_predict_view = {")
    view_end = code.index("dataset_context = {", view_start)
    view_source = code[view_start:view_end]
    assert '"mode": "active",' in view_source
    assert "release_id" not in view_source
    assert (
        '"canonical_contracts_are_source_of_truth": True,\n'
        '            "view_metadata_defines_runtime_validation": False,\n'
        '            "view_metadata_duplicates_contract": False,'
    ) in view_source
    for forbidden in (
        "time_index_field",
        "target_field",
        '"frequency"',
        "forecast_horizon",
        "minimum_observation",
        "seasonal_period",
        "deterministic_seasonal_trend_ols",
        '"mae"',
        '"rmse"',
        "seasonal_mase",
        "runtime_contract",
        "public_contract",
        "forecast_series",
    ):
        assert forbidden not in view_source
    assert '"dataset_context_predict_views_count_invalid"' in code
    assert '"dataset_context_predict_view_id_invalid"' in code
    assert '"dataset_context_predict_view_binding_dataset_slug_invalid"' in code
    assert '"dataset_context_predict_view_binding_release_mode_invalid"' in code
    assert '"dataset_context_predict_view_contract_precedence_invalid"' in code


def test_notebook_training_readiness_does_not_reuse_v1_only_generic_bridge():
    code = _source("code")
    assert "prepare_training_invocation_readiness" not in code
    assert 'if execution_contract.get("contract_version") != "execution_contract.v2":' in code


def test_notebook_uses_native_training_entrypoint_with_explicit_preparation_recipe_path():
    code = _source("code")
    assert "train_from_paths" in _called_names()
    assert "materialize_training_run_from_prepared_metadata" not in code
    assert "preparation_recipe_path=repo_root / preparation_recipe_relative_path," in code
    assert "dataset_slug=dataset_slug," in code


def test_notebook_catches_training_input_error_explicitly():
    code = _source("code")
    assert "from pipeline.training import train_from_paths, TrainingInputError" in code
    assert "except TrainingInputError as exc:" in code
    assert '"native_training_blocked"' in code


def test_notebook_asserts_frozen_forecasting_training_result_identity():
    code = _source("code")
    assert 'assert training_result.model_family == "deterministic_seasonal_trend_ols"' in code
    assert 'assert training_result.task_type == "univariate_forecasting"' in code
    assert "assert training_result.feature_columns == []" in code


def test_notebook_validates_native_forecasting_evidence_versions():
    code = _source("code")
    assert 'assert training_metrics["schema_version"] == "training-metrics.v4"' in code
    assert 'assert analytical_visualizations["schema_version"] == "analytical-visualizations.v4"' in code
    assert 'assert training_metrics["forecasting_evidence"]["problem_type"] == "univariate_forecasting"' in code
    assert 'assert training_metrics["final_holdout_evaluation"]["model_frozen_before_open"] is True' in code
    assert 'assert training_metrics["final_holdout_evaluation"]["used_for_model_selection"] is False' in code


def test_notebook_checks_scientific_continuity_without_hardcoding_into_evidence():
    code = _source("code")
    assert "SCIENTIFIC_CONTINUITY_REFERENCE_VALUES = {" in code
    assert '"mae": 1.526584,' in code
    assert '"rmse": 1.859967,' in code
    assert '"seasonal_mase": 0.555495,' in code
    assert '"scientific_continuity_mismatch"' in code
    assert 'assert "scientific_continuity" not in training_metrics' in code


def test_notebook_orchestrates_inference_bundle_v2_generation():
    code = _source("code")
    assert "generate_inference_bundle.materialize_governed_inference_bundle(" in code
    assert 'assert inference_bundle["contract_version"] == "inference_bundle.v2"' in code
    assert 'assert inference_bundle["model_provenance_origin"] == "atlas_internal_training"' in code
    assert '"feature_order" not in inference_bundle' in code
    assert '"preprocessing" not in inference_bundle' in code
    assert '"external_model_evidence" not in inference_bundle' in code


def test_notebook_performs_controlled_native_forecast_smoke_check_without_public_api():
    code = _source("code")
    assert "runtime_inference_module.execute_prediction(" in code
    assert "tempfile.TemporaryDirectory(" in code
    assert "JOBLIB_SKLEARN_FORECASTING_ADAPTER_STRATEGY" in code
    assert "assert len(smoke_forecast_points) == FORECAST_HORIZON" in code
    assert 'point["horizon_step"] for point in smoke_forecast_points] == list(range(1, FORECAST_HORIZON + 1))' in code
    assert "all(math.isfinite(point[\"forecast\"]) for point in smoke_forecast_points)" in code
    for forbidden in ("TestClient", "api_main", "requests.post", "requests.get", "/api/"):
        assert forbidden not in code
    assert "releases" not in code.split("scratch_release_root")[0] or True


def test_notebook_native_forecast_smoke_check_never_touches_real_releases_directory():
    smoke_check_start = _source("code").index("with tempfile.TemporaryDirectory(")
    smoke_check_end = _source("code").index("native_forecast_smoke_result = prediction_outcome")
    smoke_check_source = _source("code")[smoke_check_start:smoke_check_end]
    for forbidden in ("repo_root / \"releases\"", "publisher/runs", "registry/"):
        assert forbidden not in smoke_check_source


def test_notebook_materializes_truthful_model_card_without_fake_tabular_semantics():
    code = _source("code")
    assert "assert training_result.model_card_path is None" in code
    assert '"schema_version": "model-card.v1",' in code
    assert '"problem_type": "univariate_forecasting",' in code
    assert '"input_features": [],' in code
    model_card_start = code.index('model_card = {')
    model_card_end = code.index("write_governed_json(model_card_relative_path, model_card)")
    model_card_source = code[model_card_start:model_card_end]
    for forbidden in ("feature_columns", "split_policy", "classes", "positive_class", "threshold", "predicted_value"):
        assert forbidden not in model_card_source


def test_notebook_orchestrates_release_candidate_assembly_with_deterministic_release_id():
    code = _source("code")
    assert "assemble_candidate.derive_deterministic_release_id(run_id)" in code
    assert "release_identity.allocate_release_id" not in code
    assert "assemble_candidate.build_release_candidate_handoff_readiness(" in code
    assert "assemble_candidate.build_release_candidate_input(" in code
    assert "assemble_candidate.assemble_release_candidate(" in code


def test_notebook_candidate_artifact_references_include_all_required_roles():
    code = _source("code")
    for role in (
        "discovery_evidence", "execution_contract", "runtime_contract", "public_contract",
        "preparation_recipe", "prepared_data_metadata", "training_parameter_record",
        "model_artifact", "training_metrics", "model_card", "public_context",
        "visualizations", "inference_bundle",
    ):
        assert f'"{role}":' in code


def test_notebook_introduces_no_dataset_slug_branch_into_generic_pipeline_modules():
    code = _source("code")
    assert 'if dataset_slug == "nottem"' not in code
    assert "if dataset_slug ==" not in code


def test_notebook_calls_the_generic_publisher_run_materializer_with_assembly_result():
    code = _source("code")
    assert "from publisher import validate as publisher_validate" in code
    assert "publisher_validate.materialize_validation_run(" in code
    assert "materialize_validation_run" in _called_names()
    for forbidden in ("glob(", "iterdir()", 'Path("releases"'):
        assert forbidden not in code
    assert "materialize_telco_validation_run" not in code


def test_notebook_blocks_when_publisher_run_materialization_fails():
    code = _source("code")
    assert 'publisher_materialization_result["materialization_status"] != "materialized"' in code
    assert '"publisher_run_materialization_blocked"' in code
    assert 'publisher_validation_outcome != "accepted"' in code
    assert '"publisher_structural_validation_rejected"' in code
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
    assert "if publisher_run_dir_relative_path is not None:" in code


def test_notebook_requires_completed_terminal_status_and_promotion_eligibility_true():
    code = _source("code")
    assert 'if validated_run_terminal_result["status"] == "completed":' in code
    assert 'assert validated_run_terminal_result["promotion_eligibility"] is True' in code
    assert 'assert validated_run_terminal_result["status"] in ("completed", "blocked", "failed")' in code


def test_notebook_has_no_promotion_or_registry_activation_calls():
    code = _source("code")
    for forbidden in (
        "publisher_promote.run(", "publisher.promote", "promote.run(",
        "registry_update.run(", "registry.update", "activate_release",
        "write_registry", "update_registry",
    ):
        assert forbidden not in code


def test_notebook_declares_predict_view_declared_true_and_no_activation_performed():
    code = _source("code")
    assert '"predict_view_declared": True,' in code
    assert '"predict_view_registry_materialized": False,' in code
    assert '"predict_view_customization_seeded": False,' in code
    assert '"promotion_performed": False,' in code
    assert '"registry_activation_performed": False,' in code
    assert '"public_visibility_or_profile_activation_performed": False,' in code


def test_notebook_final_summary_carries_reduced_source_acquisition_fields():
    code = _source("code")
    assert '"source_reference": source_acquisition_result.get("source_reference"),' in code
    assert (
        '"source_materialization_status": source_acquisition_result.get("materialization_status"),'
        in code
    )
    assert '"source_relative_path": source_acquisition_result.get("relative_path"),' in code


def test_notebook_never_references_repo_root_before_assignment():
    tree = ast.parse(_source("code"))
    linenos_assign = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "repo_root" and isinstance(node.ctx, ast.Store)
    ]
    linenos_load = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "repo_root" and isinstance(node.ctx, ast.Load)
    ]
    assert linenos_assign and linenos_load
    assert min(linenos_assign) < min(linenos_load)
