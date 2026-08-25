"""Focused tests for Atlas-native univariate forecasting inference_bundle.v2
generation (Project Spec S0245).

All fixtures are synthetic, dataset-neutral, and use only temporary
repository paths -- no UCI/GitHub fetch, no dataset-study-* path, no
external model bytes, and no Nottingham-specific slug/path/target/frequency/
horizon/seasonal-period constant, matching the boundary already established
by tests/test_native_univariate_forecasting_training.py.

The v4/v4/v2/v2 artifact chain (training-parameter-record.v4,
training-metrics.v4, candidate-preparation-recipe.v2,
execution_contract.v2) is produced by the real, already-authorized
pipeline.training.train_from_paths entrypoint rather than hand-rolled --
this module only exercises the new inference_bundle.v2 generation/schema
layer on top of that authentic chain.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.generate_inference_bundle as gib
import pipeline.training as training

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REPO_ROOT = Path(__file__).parent.parent
INFERENCE_BUNDLE_SCHEMA_PATH = REPO_ROOT / "contracts" / "inference-bundle.schema.json"

SEASONAL_PERIOD = 4
DEV_OBSERVATIONS = 20
HOLDOUT_OBSERVATIONS = 4
FORECAST_HORIZON = 4
SEASONAL_EFFECT = [0.0, 2.0, -1.0, 3.0]


# ---------------------------------------------------------------------------
# Synthetic fixture builders (mirrors test_native_univariate_forecasting_training.py)
# ---------------------------------------------------------------------------


def _series_value(index: int, *, seasonal_period: int = SEASONAL_PERIOD) -> float:
    return 10.0 + 0.5 * index + SEASONAL_EFFECT[index % seasonal_period]


def _synthetic_rows(
    *, total: int = DEV_OBSERVATIONS + HOLDOUT_OBSERVATIONS, seasonal_period: int = SEASONAL_PERIOD
) -> list[dict]:
    return [
        {"period": str(i), "value": f"{_series_value(i, seasonal_period=seasonal_period):.6f}"}
        for i in range(total)
    ]


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["period", "value"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixed_model_configuration(**overrides) -> dict:
    base = dict(
        include_intercept=True,
        linear_time_trend=True,
        seasonal_effects="additive_indicators",
        seasonal_period=SEASONAL_PERIOD,
        reference_season_position=0,
        trend_origin="development_start",
    )
    base.update(overrides)
    return base


def _finalization_policy(**overrides) -> dict:
    base = dict(
        backtesting_refit_each_fold=True,
        final_fit_scope="full_development",
        freeze_before_final_holdout_open=True,
        final_holdout_evaluation_count=1,
        final_holdout_used_for_adjustment=False,
        final_holdout_used_for_model_selection=False,
        no_retuning_after_final_holdout=True,
    )
    base.update(overrides)
    return base


def _fold_schedule() -> list[dict]:
    return [
        {
            "fold_index": 1, "training_observations": 12, "forecast_origin": "11",
            "validation_start": "12", "validation_end": "15", "validation_observations": 4,
        },
        {
            "fold_index": 2, "training_observations": 16, "forecast_origin": "15",
            "validation_start": "16", "validation_end": "19", "validation_observations": 4,
        },
    ]


def _execution_contract(**overrides) -> dict:
    primary_metric = overrides.pop(
        "primary_metric", {"metric_id": "mae", "direction": "lower_is_better"}
    )
    secondary_metrics = overrides.pop(
        "secondary_metrics",
        [
            {"metric_id": "rmse", "direction": "lower_is_better"},
            {"metric_id": "seasonal_mase", "direction": "lower_is_better", "seasonal_period": SEASONAL_PERIOD},
        ],
    )
    fixed_model_configuration = overrides.pop("fixed_model_configuration", _fixed_model_configuration())
    contract = {
        "contract_version": "execution_contract.v2",
        "dataset_id": "synth-series",
        "problem_type": "univariate_forecasting",
        "target_column": "value",
        "time_index_column": "period",
        "index_value_kind": "ordinal_time",
        "frequency": "synthetic-step",
        "source_exogenous_predictors": "forbidden",
        "forecast_horizon": FORECAST_HORIZON,
        "temporal_evaluation": {
            "preparation_schema_version": "candidate-preparation-recipe.v2",
            "backtesting_mode": "expanding_window",
            "fold_count": 2,
            "final_holdout_prospectively_sealed": True,
            "final_holdout_used_for_backtesting": False,
            "final_holdout_used_for_model_selection": False,
            "random_shuffle_performed": False,
            "future_targets_used_for_fold_fit": False,
            "validation_targets_fed_back_within_fold": False,
            "preprocessing_fit_on_validation_or_future": False,
        },
        "evaluation_policy": {
            "primary_metric": primary_metric,
            "secondary_metrics": secondary_metrics,
        },
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1",
            "problem_type": "univariate_forecasting",
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
        },
        "training_policy": {
            "schema_version": "univariate-forecasting-training-policy.v1",
            "selection_mode": "fixed_configuration",
            "model_selection_performed": False,
            "model_family": "deterministic_seasonal_trend_ols",
            "fixed_model_configuration": fixed_model_configuration,
            "finalization_policy": _finalization_policy(),
        },
        "random_seed": None,
    }
    contract.update(overrides)
    return contract


def _preparation_recipe(**overrides) -> dict:
    fold_schedule = overrides.pop("fold_schedule", _fold_schedule())
    partitions = overrides.pop(
        "partitions",
        {
            "development": {
                "start_index_value": "0", "end_index_value": "19", "observation_count": DEV_OBSERVATIONS,
            },
            "sealed_final_holdout": {
                "start_index_value": "20", "end_index_value": "23",
                "observation_count": HOLDOUT_OBSERVATIONS,
                "prospectively_sealed": True, "used_for_backtesting": False,
                "used_for_model_selection": False,
            },
        },
    )
    recipe = {
        "schema_version": "candidate-preparation-recipe.v2",
        "producer": "test-fixture",
        "problem_type": "univariate_forecasting",
        "discovery_evidence_ref": {"path": "discovery.json", "schema_version": "dataset-discovery-evidence.v1"},
        "semantic_intent_ref": {
            "path": "semantic-intent.json", "schema_version": "dataset-semantic-intent.v4", "sha256": "a" * 64,
        },
        "semantic_identity_mirror": {
            "time_index_field_name": "period", "target_field_name": "value",
            "index_value_kind": "ordinal_time", "frequency": "synthetic-step",
        },
        "temporal_integrity": {
            "strictly_increasing_index": True, "unique_index": True, "frequency_contiguous": True,
            "target_missing_values_absent": True, "target_values_finite": True,
        },
        "forecast_horizon": FORECAST_HORIZON,
        "partitions": partitions,
        "backtesting": {
            "mode": "expanding_window", "initial_training_observations": 12,
            "forecast_horizon": FORECAST_HORIZON, "origin_step_observations": 4,
            "fold_count": 2, "validation_targets_overlap": False,
        },
        "fold_schedule": fold_schedule,
        "leakage_controls": {
            "random_shuffle_performed": False, "future_targets_used_for_fold_fit": False,
            "final_holdout_used_for_backtesting": False, "final_holdout_used_for_model_selection": False,
            "validation_targets_fed_back_within_fold": False,
            "preprocessing_fit_on_validation_or_future": False,
        },
        "preparation_boundary_confirmations": {
            "model_training_performed": False, "release_publication_performed": False,
            "hidden_notebook_transformations": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True, "raw_runtime_prohibited": True, "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True, "private_source_paths_prohibited": True, "reduced_and_sanitized": True,
        },
        "generated_at": "2026-01-01T00:00:00Z",
    }
    recipe.update(overrides)
    return recipe


# ---------------------------------------------------------------------------
# Repo-root fixture and training/generation helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo-root"
    root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: root)
    return root


def _write_inputs(
    root: Path,
    *,
    rows: list[dict] | None = None,
    contract_overrides: dict | None = None,
    recipe_overrides: dict | None = None,
) -> tuple[Path, Path, Path]:
    inputs_dir = root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = _write_csv(inputs_dir / "series.csv", rows if rows is not None else _synthetic_rows())
    contract_path = _write_json(
        inputs_dir / "execution-contract.json", _execution_contract(**(contract_overrides or {}))
    )
    recipe_path = _write_json(
        inputs_dir / "preparation-recipe.json", _preparation_recipe(**(recipe_overrides or {}))
    )
    return contract_path, recipe_path, dataset_path


def _train(
    contract_path: Path, recipe_path: Path, dataset_path: Path, run_id: str
) -> training.TrainingResult:
    return training.train_from_paths(
        contract_path,
        dataset_path,
        preparation_recipe_path=recipe_path,
        dataset_slug="synth-series",
        run_id=run_id,
    )


def _runtime_and_public_contracts(root: Path) -> tuple[Path, Path]:
    inputs_dir = root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = _write_json(
        inputs_dir / "runtime-contract.json", {"contract_version": "runtime_contract.v1", "note": "synthetic"}
    )
    public_path = _write_json(
        inputs_dir / "public-contract.json", {"contract_version": "public_contract.v1", "note": "synthetic"}
    )
    return runtime_path, public_path


def _training_run_materialization_result(result: training.TrainingResult) -> dict:
    return {
        "status": "trained",
        "training_result": {
            "output_directory": result.output_directory,
            "training_parameter_record_path": result.training_parameter_record_path,
            "metrics_path": result.metrics_path,
            "serialized_model_path": result.serialized_model_path,
            "model_selection_evidence_path": result.model_selection_evidence_path,
        },
    }


@pytest.fixture
def valid_chain(repo_root: Path):
    contract_path, recipe_path, dataset_path = _write_inputs(repo_root)
    result = _train(contract_path, recipe_path, dataset_path, "train-20260101T000000Z")
    return repo_root, contract_path, recipe_path, dataset_path, result


def _generate(
    root: Path,
    result: training.TrainingResult,
    *,
    execution_contract_path: Path,
    output_path: Path | None = None,
    **overrides,
) -> dict:
    runtime_path, public_path = _runtime_and_public_contracts(root)
    output_path = output_path or (root / "output" / "inference-bundle.json")
    training_run_materialization_result = overrides.pop(
        "training_run_materialization_result", _training_run_materialization_result(result)
    )

    def _rel(path: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()

    kwargs = dict(
        training_run_materialization_result=training_run_materialization_result,
        execution_contract_path=str(execution_contract_path),
        runtime_contract_path=str(runtime_path),
        public_contract_path=str(public_path),
        dataset_context_path=str(root / "inputs" / "series.csv"),
        output_path=str(output_path),
        repo_root=str(root),
        dataset_slug="synth-series",
        execution_contract_ref=_rel(execution_contract_path),
        runtime_contract_ref=_rel(runtime_path),
        public_contract_ref=_rel(public_path),
        dataset_context_ref=_rel(root / "inputs" / "series.csv"),
    )
    kwargs.update(overrides)
    return gib.materialize_governed_inference_bundle(**kwargs)


def _assert_blocked(outcome: dict) -> None:
    assert outcome["status"] == "blocked"
    assert outcome.get("blocking_reasons")


def _load_bundle_schema() -> dict:
    return json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text())


def _mutate_execution_contract_and_repatch_hash(
    root: Path,
    training_parameter_record_path: Path,
    mutator,
    *,
    filename: str = "execution-contract-mutated.json",
) -> Path:
    """Write a still-structurally-valid but semantically mutated execution
    contract, then repatch training_parameter_record.hashes.execution_contract_sha256
    to match the mutated bytes -- isolating a cross-artifact semantic
    mismatch from an incidental hash mismatch."""
    base = _execution_contract()
    mutator(base)
    new_path = root / "inputs" / filename
    _write_json(new_path, base)
    record = json.loads(training_parameter_record_path.read_text())
    record["hashes"]["execution_contract_sha256"] = _sha256_of(new_path)
    training_parameter_record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return new_path


# ---------------------------------------------------------------------------
# End-to-end valid generation
# ---------------------------------------------------------------------------


def test_valid_v4_v4_v2_v2_chain_produces_inference_bundle_v2(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    assert outcome["status"] == "generated"
    assert outcome["bundle_contract_version"] == "inference_bundle.v2"
    assert outcome["training_run_id"] == "train-20260101T000000Z"
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    assert bundle["contract_version"] == "inference_bundle.v2"


def test_bundle_schema_valid(valid_chain):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    schema = _load_bundle_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema).validate(bundle)


def test_valid_bundle_field_values(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    bundle = json.loads(Path(outcome["output_path"]).read_text())

    assert bundle["model_provenance_origin"] == "atlas_internal_training"
    assert bundle["frozen_model"]["model_family"] == "deterministic_seasonal_trend_ols"
    assert bundle["frozen_model"]["state"] == "frozen"
    assert bundle["frozen_model"]["fixed_model_configuration"] == _fixed_model_configuration()
    assert bundle["frozen_model"]["temporal_identity"]["target_column"] == "value"
    assert bundle["frozen_model"]["temporal_identity"]["time_index_column"] == "period"
    assert bundle["frozen_model"]["temporal_identity"]["frequency"] == "synthetic-step"
    assert bundle["frozen_model"]["temporal_identity"]["forecast_horizon"] == FORECAST_HORIZON
    assert bundle["frozen_model"]["temporal_identity"]["source_exogenous_predictors"] == "forbidden"
    assert bundle["frozen_model"]["training_scope"] == {
        "start": "0", "end": "19", "observation_count": DEV_OBSERVATIONS,
    }
    assert bundle["frozen_model"]["finalization"]["selection_mode"] == "fixed_configuration"
    assert bundle["frozen_model"]["finalization"]["model_selection_performed"] is False
    assert bundle["frozen_model"]["finalization"]["frozen_before_final_holdout_open"] is True
    assert bundle["frozen_model"]["finalization"]["final_holdout_evaluation_count"] == 1
    assert bundle["frozen_model"]["finalization"]["final_holdout_used_for_adjustment"] is False
    assert bundle["frozen_model"]["finalization"]["final_holdout_used_for_model_selection"] is False
    assert bundle["frozen_model"]["finalization"]["no_retuning_after_final_holdout"] is True

    assert bundle["runtime_execution"]["serialization_format"] == "joblib"
    assert bundle["runtime_execution"]["loader_strategy"] == "joblib_sklearn_forecasting_adapter"
    assert bundle["runtime_execution"]["prediction_interface"] == "forecast_series"
    assert bundle["runtime_execution"]["model_family"] == "deterministic_seasonal_trend_ols"

    assert bundle["input_schema"]["payload_shape"] == "runtime_contract_history_series"
    assert bundle["input_schema"]["runtime_contract_reference"] == "contract_references.runtime_contract"

    assert bundle["output_schema"]["result_schema_version"] == "univariate-forecasting-result.v1"
    assert bundle["output_schema"]["forecast_count_source"] == "frozen_model.temporal_identity.forecast_horizon"

    assert bundle["compatibility_constraints"]["requires_frozen_model_specification_match"] is True
    assert bundle["compatibility_constraints"]["requires_temporal_identity_match"] is True
    assert "requires_feature_order_match" not in bundle["compatibility_constraints"]

    assert bundle["result_semantics"]["schema_version"] == "univariate-forecasting-result-semantics.v1"
    assert bundle["result_semantics"]["primary_output"] == "forecast_series"
    assert bundle["result_semantics"]["forecast_count_source"] == "forecast_horizon"
    assert bundle["result_semantics"]["model_descriptor"]["model_family"] == "deterministic_seasonal_trend_ols"

    assert bundle["boundary_confirmations"]["external_scientific_project_dependency"] is False
    assert bundle["boundary_confirmations"]["training_internals_required_at_runtime"] is False
    assert bundle["boundary_confirmations"]["final_model_frozen"] is True
    assert bundle["boundary_confirmations"]["final_holdout_used_for_adjustment"] is False


# ---------------------------------------------------------------------------
# Explicit release_id propagation (Project Spec S0263): the internal
# execution_contract.v2 -> inference_bundle.v2 branch honors an explicit,
# schema-valid caller-supplied release_id exactly; an invalid explicit
# release_id fails closed; omitting it preserves the existing deterministic
# provisional fallback unchanged.
# ---------------------------------------------------------------------------


def test_explicit_release_id_honored_in_v2_bundle(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(
        root, result, execution_contract_path=contract_path, release_id="release-20260101-002"
    )
    assert outcome["status"] == "generated"
    assert outcome["provisional_release_id"] == "release-20260101-002"
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    assert bundle["release_context"]["release_id"] == "release-20260101-002"


def test_invalid_explicit_release_id_fails_closed_for_v2_bundle(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(
        root, result, execution_contract_path=contract_path, release_id="not-a-release-id"
    )
    _assert_blocked(outcome)


def test_no_explicit_release_id_preserves_provisional_fallback_for_v2_bundle(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    assert outcome["status"] == "generated"
    assert outcome["provisional_release_id"] == "release-20260101-001"
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    assert bundle["release_context"]["release_id"] == "release-20260101-001"


def test_v2_has_no_feature_order_and_no_preprocessing(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    assert "feature_order" not in bundle
    assert "preprocessing" not in bundle
    assert "external_model_evidence" not in bundle
    assert "model_artifact" not in bundle  # only frozen_model.model_artifact exists on v2


def test_v2_result_semantics_contain_no_actual_forecast_values(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    for forbidden_key in ("forecast", "forecast_points", "period", "forecast_origin", "confidence_interval"):
        assert forbidden_key not in bundle["output_schema"]
        assert forbidden_key not in bundle["result_semantics"]


def test_v2_derives_prepared_and_preparation_paths_from_v4_provenance(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    outcome = _generate(root, result, execution_contract_path=contract_path)
    bundle = json.loads(Path(outcome["output_path"]).read_text())
    record = json.loads((root / result.training_parameter_record_path).read_text())
    consumed_inputs = record["consumed_inputs"]
    assert bundle["prepared_dataset"]["prepared_dataset_reference"]["path"] == consumed_inputs["dataset_path"]
    assert (
        bundle["preparation_evidence"]["preparation_recipe"]["path"]
        == consumed_inputs["preparation_recipe_path"]
    )
    assert outcome["prepared_dataset_reference"] == consumed_inputs["dataset_path"]


def test_v2_does_not_require_prepared_data_metadata_path(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    # prepared_data_metadata_path is never passed by _generate -- a
    # successful forecasting generation without it proves the v1-only
    # prepared_data_metadata.v1 requirement is not imposed on v2.
    outcome = _generate(root, result, execution_contract_path=contract_path)
    assert outcome["status"] == "generated"


def test_v2_never_deserializes_model_bytes(valid_chain, monkeypatch):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain

    import joblib

    def _forbidden_load(*args, **kwargs):
        raise AssertionError("joblib.load must never be called by forecasting bundle generation")

    monkeypatch.setattr(joblib, "load", _forbidden_load)
    outcome = _generate(root, result, execution_contract_path=contract_path)
    assert outcome["status"] == "generated"


def test_v2_source_never_calls_joblib_load_or_predict():
    source = inspect.getsource(gib._build_forecasting_bundle)
    assert "joblib.load" not in source
    assert ".predict(" not in source
    assert ".fit(" not in source


# ---------------------------------------------------------------------------
# Hash reconciliation (staleness) blocks generation
# ---------------------------------------------------------------------------


def test_preparation_recipe_hash_mismatch_blocks(valid_chain):
    root, contract_path, recipe_path, _dataset_path, result = valid_chain
    with recipe_path.open("a", encoding="utf-8") as f:
        f.write("\n")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_prepared_dataset_hash_mismatch_blocks(valid_chain):
    root, contract_path, _recipe_path, dataset_path, result = valid_chain
    with dataset_path.open("a", encoding="utf-8") as f:
        f.write("\n")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_model_artifact_hash_mismatch_blocks(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    model_path = root / result.serialized_model_path
    with model_path.open("ab") as f:
        f.write(b"\x00")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_metrics_hash_mismatch_blocks(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    metrics_path = root / result.metrics_path
    with metrics_path.open("a", encoding="utf-8") as f:
        f.write("\n")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_execution_contract_hash_mismatch_blocks(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    with contract_path.open("a", encoding="utf-8") as f:
        f.write("\n")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_same_training_run_mismatch_blocks(repo_root):
    contract_path, recipe_path, dataset_path = _write_inputs(repo_root)
    result_a = _train(contract_path, recipe_path, dataset_path, "train-20260101T000000Z")
    result_b = _train(contract_path, recipe_path, dataset_path, "train-20260101T000001Z")

    # Null out metrics_sha256 on run A's record (schema-optional) so the
    # substitution below is isolated to the training_run_identity check
    # rather than tripping the metrics hash check first.
    record_path = repo_root / result_a.training_parameter_record_path
    record = json.loads(record_path.read_text())
    record["hashes"]["metrics_sha256"] = None
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    hybrid_training_result = {
        "output_directory": result_a.output_directory,
        "training_parameter_record_path": result_a.training_parameter_record_path,
        "metrics_path": result_b.metrics_path,
        "serialized_model_path": result_a.serialized_model_path,
        "model_selection_evidence_path": None,
    }
    outcome = _generate(
        repo_root,
        result_a,
        execution_contract_path=contract_path,
        training_run_materialization_result={"status": "trained", "training_result": hybrid_training_result},
    )
    _assert_blocked(outcome)


# ---------------------------------------------------------------------------
# Version-family mismatches block generation
# ---------------------------------------------------------------------------


def test_wrong_execution_contract_version_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    tabular_contract = {
        "contract_version": "execution_contract.v1",
        "dataset_id": "synth-series",
        "target_column": "value",
        "feature_columns": ["value"],
        "ignored_columns": [],
        "required_columns": ["value"],
        "optional_columns": [],
        "feature_definitions": {"value": {"type": "numeric"}},
        "missing_value_policy": {"value": "mean"},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.8, "val_ratio": 0.0, "test_ratio": 0.2},
        "random_seed": None,
        "primary_metric": "roc_auc",
        "secondary_metrics": [],
        "modeling_constraints": {"allowed_model_families": ["logistic_regression"]},
    }
    wrong_version_path = root / "inputs" / "execution-contract-v1.json"
    _write_json(wrong_version_path, tabular_contract)
    _assert_blocked(_generate(root, result, execution_contract_path=wrong_version_path))


def test_wrong_problem_type_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    wrong_contract = _execution_contract(problem_type="something_else")
    wrong_path = root / "inputs" / "execution-contract-wrong-problem-type.json"
    _write_json(wrong_path, wrong_contract)
    _assert_blocked(_generate(root, result, execution_contract_path=wrong_path))


def test_wrong_training_record_version_blocks(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path
    record = json.loads(record_path.read_text())
    record["schema_version"] = "training-parameter-record.v1"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_wrong_metrics_version_blocks(valid_chain):
    root, contract_path, _recipe_path, _dataset_path, result = valid_chain
    metrics_path = root / result.metrics_path
    metrics_doc = json.loads(metrics_path.read_text())
    metrics_doc["schema_version"] = "training-metrics.v1"
    metrics_path.write_text(json.dumps(metrics_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Repatch the metrics hash so this is isolated to the version check.
    record_path = root / result.training_parameter_record_path
    record = json.loads(record_path.read_text())
    record["hashes"]["metrics_sha256"] = _sha256_of(metrics_path)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


def test_wrong_preparation_recipe_version_blocks(valid_chain):
    root, contract_path, recipe_path, _dataset_path, result = valid_chain
    recipe_doc = json.loads(recipe_path.read_text())
    recipe_doc["schema_version"] = "candidate-preparation-recipe.v1"
    recipe_path.write_text(json.dumps(recipe_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Repatch the preparation-recipe hash so this is isolated to the version check.
    record_path = root / result.training_parameter_record_path
    record = json.loads(record_path.read_text())
    record["hashes"]["preparation_recipe_sha256"] = _sha256_of(recipe_path)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _assert_blocked(_generate(root, result, execution_contract_path=contract_path))


# ---------------------------------------------------------------------------
# Cross-artifact temporal/horizon/model-configuration reconciliation
# ---------------------------------------------------------------------------


def test_target_column_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path
    mutated_path = _mutate_execution_contract_and_repatch_hash(
        root, record_path, lambda c: c.__setitem__("target_column", "other_value")
    )
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


def test_time_index_column_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path
    mutated_path = _mutate_execution_contract_and_repatch_hash(
        root, record_path, lambda c: c.__setitem__("time_index_column", "other_period")
    )
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


def test_frequency_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path
    mutated_path = _mutate_execution_contract_and_repatch_hash(
        root, record_path, lambda c: c.__setitem__("frequency", "other-frequency")
    )
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


def test_forecast_horizon_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path

    def _mutate(c: dict) -> None:
        c["forecast_horizon"] = 3
        c["temporal_evaluation"] = dict(c["temporal_evaluation"])

    mutated_path = _mutate_execution_contract_and_repatch_hash(root, record_path, _mutate)
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


def test_seasonal_configuration_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path

    def _mutate(c: dict) -> None:
        c["training_policy"] = dict(c["training_policy"])
        c["training_policy"]["fixed_model_configuration"] = _fixed_model_configuration(seasonal_period=5)

    mutated_path = _mutate_execution_contract_and_repatch_hash(root, record_path, _mutate)
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


def test_training_policy_mismatch_blocks(valid_chain):
    root, _contract_path, _recipe_path, _dataset_path, result = valid_chain
    record_path = root / result.training_parameter_record_path

    def _mutate(c: dict) -> None:
        c["training_policy"] = dict(c["training_policy"])
        c["training_policy"]["fixed_model_configuration"] = _fixed_model_configuration(
            reference_season_position=1
        )

    mutated_path = _mutate_execution_contract_and_repatch_hash(root, record_path, _mutate)
    _assert_blocked(_generate(root, result, execution_contract_path=mutated_path))


# ---------------------------------------------------------------------------
# v1/v2 schema-level union tests (pure schema, no generator involved)
# ---------------------------------------------------------------------------


def _minimal_v2_document() -> dict:
    return {
        "contract_version": "inference_bundle.v2",
        "bundle_identity": {
            "bundle_id": "synth-series-inference-bundle-20260101T000000Z",
            "artifact_kind": "inference_bundle",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "dataset_context": {
            "dataset_slug": "synth-series",
            "dataset_context_reference": {"path": "context.json", "sha256": "a" * 64},
        },
        "release_context": {
            "release_id": "release-20260101-001",
            "release_package_reference": "predictions/bundle.json",
        },
        "contract_references": {
            "execution_contract": {"path": "ec.json", "sha256": "a" * 64, "contract_version": "execution_contract.v2"},
            "runtime_contract": {"path": "rc.json", "sha256": "a" * 64, "contract_version": "runtime_contract.v1"},
            "public_contract": {"path": "pc.json", "sha256": "a" * 64, "contract_version": "public_contract.v1"},
        },
        "prepared_dataset": {
            "prepared_dataset_reference": {"path": "series.csv", "sha256": "a" * 64},
            "prepared_dataset_sha256": "a" * 64,
        },
        "preparation_evidence": {
            "preparation_recipe": {
                "path": "recipe.json", "sha256": "a" * 64, "contract_version": "candidate-preparation-recipe.v2",
            }
        },
        "training_evidence": {
            "training_run_identity": {"dataset_slug": "synth-series", "run_id": "train-20260101T000000Z"},
            "training_parameter_record": {
                "path": "tpr.json", "sha256": "a" * 64, "contract_version": "training-parameter-record.v4",
            },
            "training_metrics": {
                "path": "metrics.json", "sha256": "a" * 64, "contract_version": "training-metrics.v4",
            },
        },
        "frozen_model": {
            "state": "frozen",
            "model_artifact": {
                "path": "models/model.pkl", "sha256": "a" * 64,
                "source_training_parameter_record_path": "tpr.json",
            },
            "model_family": "deterministic_seasonal_trend_ols",
            "training_policy_schema_version": "univariate-forecasting-training-policy.v1",
            "fixed_model_configuration": _fixed_model_configuration(),
            "temporal_identity": {
                "target_column": "value", "time_index_column": "period", "index_value_kind": "ordinal_time",
                "frequency": "synthetic-step", "source_exogenous_predictors": "forbidden",
                "forecast_horizon": FORECAST_HORIZON,
            },
            "training_scope": {"start": "0", "end": "19", "observation_count": DEV_OBSERVATIONS},
            "finalization": {
                "selection_mode": "fixed_configuration", "model_selection_performed": False,
                "final_fit_scope": "full_development", "frozen_before_final_holdout_open": True,
                "final_holdout_evaluation_count": 1, "final_holdout_used_for_adjustment": False,
                "final_holdout_used_for_model_selection": False, "no_retuning_after_final_holdout": True,
            },
        },
        "runtime_execution": {
            "execution_strategy": "in_process", "serialization_format": "joblib",
            "loader_strategy": "joblib_sklearn_forecasting_adapter", "prediction_interface": "forecast_series",
            "model_family": "deterministic_seasonal_trend_ols",
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_history_series", "input_policy_source": "runtime_contract",
        },
        "output_schema": {
            "result_schema_version": "univariate-forecasting-result.v1", "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points", "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
        },
        "compatibility_constraints": {
            "requires_contract_versions": {
                "execution_contract": "execution_contract.v2",
                "runtime_contract": "runtime_contract.v1", "public_contract": "public_contract.v1",
            },
            "requires_hash_match": True, "requires_release_relative_paths": True,
            "requires_supported_loader": True, "requires_supported_serialization": True,
            "requires_temporal_identity_match": True, "requires_frozen_model_specification_match": True,
            "requires_forecast_horizon_match": True,
        },
        "result_semantics": {
            "schema_version": "univariate-forecasting-result-semantics.v1", "problem_type": "univariate_forecasting",
            "result_schema_version": "univariate-forecasting-result.v1", "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points", "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
            "model_descriptor": {
                "model_family": "deterministic_seasonal_trend_ols",
                "display_name": "Deterministic Seasonal-Trend OLS",
            },
        },
        "model_provenance_origin": "atlas_internal_training",
        "boundary_confirmations": {
            "release_relative_paths_only": True, "absolute_paths_embedded": False,
            "parent_traversal_embedded": False, "notebook_state_embedded": False,
            "raw_dataset_embedded": False, "model_bytes_embedded": False,
            "runtime_payload_validation_duplicated": False, "training_internals_required_at_runtime": False,
            "external_scientific_project_dependency": False, "external_model_artifact_used": False,
            "model_selection_performed": False, "final_model_frozen": True,
            "final_holdout_used_for_adjustment": False,
        },
    }


@pytest.fixture(scope="module")
def bundle_schema() -> dict:
    return _load_bundle_schema()


@pytest.fixture(scope="module")
def bundle_validator(bundle_schema):
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    return jsonschema.Draft202012Validator(bundle_schema)


def _is_valid(validator, doc: dict) -> bool:
    return not list(validator.iter_errors(doc))


def test_minimal_v2_document_schema_valid(bundle_validator):
    assert _is_valid(bundle_validator, _minimal_v2_document())


def test_v1_historical_schema_fixture_remains_valid(bundle_validator):
    fixture_path = REPO_ROOT / "pipeline" / "inference-bundles" / "concrete-compressive-strength" / "inference-bundle.json"
    doc = json.loads(fixture_path.read_text())
    assert doc["contract_version"] == "inference_bundle.v1"
    assert _is_valid(bundle_validator, doc)


def test_mixed_v1_v2_bundle_rejected(bundle_validator):
    doc = _minimal_v2_document()
    doc["contract_version"] = "inference_bundle.v1"
    assert not _is_valid(bundle_validator, doc)


def test_unknown_bundle_version_rejected(bundle_validator):
    doc = _minimal_v2_document()
    doc["contract_version"] = "inference_bundle.v3"
    assert not _is_valid(bundle_validator, doc)


def test_v2_with_feature_order_rejected(bundle_validator):
    doc = _minimal_v2_document()
    doc["feature_order"] = ["value"]
    assert not _is_valid(bundle_validator, doc)


def test_v2_with_preprocessing_rejected(bundle_validator):
    doc = _minimal_v2_document()
    doc["preprocessing"] = {"source": "execution_contract_and_training_parameter_record"}
    assert not _is_valid(bundle_validator, doc)


def test_v2_with_external_model_evidence_rejected(bundle_validator):
    doc = _minimal_v2_document()
    doc["model_provenance_origin"] = "validated_external_fitted_model"
    doc["external_model_evidence"] = {"origin": "validated_external_fitted_model"}
    assert not _is_valid(bundle_validator, doc)


def test_v2_with_wrong_training_evidence_versions_rejected(bundle_validator):
    doc = copy.deepcopy(_minimal_v2_document())
    doc["training_evidence"]["training_parameter_record"]["contract_version"] = "training-parameter-record.v1"
    assert not _is_valid(bundle_validator, doc)

    doc2 = copy.deepcopy(_minimal_v2_document())
    doc2["training_evidence"]["training_metrics"]["contract_version"] = "training-metrics.v1"
    assert not _is_valid(bundle_validator, doc2)


def test_v2_with_malformed_frozen_model_rejected(bundle_validator):
    doc = copy.deepcopy(_minimal_v2_document())
    doc["frozen_model"]["model_family"] = "gradient_boosting"
    assert not _is_valid(bundle_validator, doc)

    doc2 = copy.deepcopy(_minimal_v2_document())
    del doc2["frozen_model"]["temporal_identity"]
    assert not _is_valid(bundle_validator, doc2)


def test_v2_requires_feature_order_match_forbidden(bundle_validator):
    doc = copy.deepcopy(_minimal_v2_document())
    doc["compatibility_constraints"]["requires_feature_order_match"] = True
    assert not _is_valid(bundle_validator, doc)


def test_v2_output_schema_does_not_define_concrete_forecast_point_keys(bundle_validator):
    doc = copy.deepcopy(_minimal_v2_document())
    doc["output_schema"]["period"] = "2026-01"
    assert not _is_valid(bundle_validator, doc)
    doc2 = copy.deepcopy(_minimal_v2_document())
    doc2["output_schema"]["forecast"] = 1.0
    assert not _is_valid(bundle_validator, doc2)
