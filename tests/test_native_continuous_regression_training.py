"""Focused tests for Atlas-native fixed-configuration continuous-regression
training (Project Spec S0224).

All fixtures are synthetic and dataset-neutral -- no UCI fetch, no GitHub
access, no dataset-study-* path, no external model bytes, and no
Concrete-specific names/values, matching the boundary already established by
tests/test_native_multiclass_training.py and
tests/test_contract_derivation.py's continuous-regression fixtures.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.training as training
from pipeline.training import (
    MODEL_ARTIFACT_FILENAME,
    MODEL_CARD_FILENAME,
    MODEL_CARD_INPUT_FILENAME,
    METRICS_ARTIFACT_FILENAME,
    NATIVE_CONTINUOUS_REGRESSION_METRIC_NAMES,
    NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_TRAINING_METRICS_VERSION,
    NATIVE_CONTINUOUS_REGRESSION_TRAINING_PARAMETER_RECORD_VERSION,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _continuous_regression_random_three_way_split_indices,
    _native_continuous_regression_metric_values,
    _validate_fixed_continuous_regression_configuration,
    train_from_paths,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REPO_ROOT = Path(__file__).parent.parent
TRAINING_PARAMETER_RECORD_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-parameter-record.schema.json"
TRAINING_METRICS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-metrics.schema.json"


# ---------------------------------------------------------------------------
# Fixtures -- synthetic dataset-neutral continuous-regression contract/rows
# ---------------------------------------------------------------------------


def _gbr_hyperparameters(**overrides) -> dict:
    base = {
        "n_estimators": 60,
        "learning_rate": 0.1,
        "max_depth": 3,
        "min_samples_leaf": 5,
        "subsample": 0.9,
        "loss": "squared_error",
    }
    base.update(overrides)
    return base


def _rfr_hyperparameters(**overrides) -> dict:
    base = {
        "n_estimators": 60,
        "max_depth": 4,
        "min_samples_leaf": 5,
        "max_features": "sqrt",
        "bootstrap": True,
    }
    base.update(overrides)
    return base


def _fixed_continuous_regression_contract(
    *, model_family: str = "gradient_boosting", hyperparameters: dict | None = None,
) -> dict:
    if hyperparameters is None:
        hyperparameters = _gbr_hyperparameters() if model_family == "gradient_boosting" else _rfr_hyperparameters()
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "synthetic-regression-fixture",
        "target_column": "outcome_measure",
        "feature_columns": ["input_a", "input_b"],
        "ignored_columns": ["record_ref"],
        "required_columns": ["input_a", "input_b"],
        "optional_columns": [],
        "feature_definitions": {
            "input_a": {"type": "numeric"},
            "input_b": {"type": "numeric"},
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "random", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "random_seed": 13,
        "primary_metric": "r2",
        "secondary_metrics": ["mae", "rmse"],
        "modeling_constraints": {
            "allowed_model_families": [model_family],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": model_family,
                "hyperparameters": hyperparameters,
            },
        },
        "result_semantics": {
            "schema_version": NATIVE_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
            "problem_type": "continuous_regression",
            "primary_output": "predicted_value",
            "output_value_kind": "continuous_numeric",
        },
    }


def _synthetic_regression_dataset(row_count: int = 150, seed: int = 0) -> dict:
    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        input_a = rng.uniform(0, 100)
        input_b = rng.uniform(0, 50)
        noise = rng.uniform(-2, 2)
        outcome = 2.0 * input_a - 1.5 * input_b + 10.0 + noise
        rows.append(
            {
                "dataset_id": "synthetic-regression-fixture",
                "record_ref": f"row-{index:04d}",
                "input_a": round(input_a, 4),
                "input_b": round(input_b, 4),
                "outcome_measure": round(outcome, 4),
            }
        )
    return {"dataset_id": "synthetic-regression-fixture", "rows": rows}


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    return repo_root


def _write_valid_inputs(tmp_path: Path, *, model_family: str = "gradient_boosting") -> tuple[Path, Path]:
    contract_path = _write_json(
        tmp_path / "execution-contract.json", _fixed_continuous_regression_contract(model_family=model_family)
    )
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())
    return contract_path, dataset_path


def _run(fixed_training_environment: Path, tmp_path: Path, *, model_family: str = "gradient_boosting"):
    contract_path, dataset_path = _write_valid_inputs(tmp_path, model_family=model_family)
    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="synthetic-regression-fixture",
        run_id="train-20260819T000000Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    return result, output_directory


# ---------------------------------------------------------------------------
# End-to-end fixed-configuration continuous-regression runs
# ---------------------------------------------------------------------------


def test_gradient_boosting_fixed_configuration_trains_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="gradient_boosting")

    assert result.status == "trained"
    assert result.model_family == "gradient_boosting"
    assert result.task_type == "continuous_regression"
    for artifact_name in (
        MODEL_ARTIFACT_FILENAME,
        TRAINING_PARAMETER_RECORD_FILENAME,
        METRICS_ARTIFACT_FILENAME,
        MODEL_CARD_INPUT_FILENAME,
        MODEL_CARD_FILENAME,
    ):
        artifact_path = output_directory / artifact_name
        assert artifact_path.exists(), artifact_name
        assert artifact_path.stat().st_size > 0, artifact_name


def test_random_forest_fixed_configuration_trains_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, model_family="random_forest")

    assert result.status == "trained"
    assert result.model_family == "random_forest"
    assert result.task_type == "continuous_regression"
    assert (output_directory / MODEL_ARTIFACT_FILENAME).exists()


def test_no_analytical_visualizations_artifact_is_produced(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    assert result.analytical_visualizations_path is None
    assert result.hashes["analytical_visualizations_sha256"] is None
    assert not (output_directory / "analytical-visualizations.json").exists()


def test_no_model_selection_evidence_artifact_is_produced(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    assert result.model_selection_evidence_path is None
    assert result.model_selection_evidence_produced is False
    assert result.hashes["model_selection_evidence_sha256"] is None
    assert not (output_directory / "model-selection-evidence.json").exists()


def test_r2_mae_rmse_are_finite_and_metrics_bounded_to_the_three(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, _ = _run(fixed_training_environment, tmp_path)

    assert set(result.metrics) == {"r2", "mae", "rmse"}
    for name, value in result.metrics.items():
        assert value == value  # not NaN
        assert value not in (float("inf"), float("-inf"))
        assert isinstance(value, float)


def test_final_fit_uses_train_plus_validation_and_test_evaluated_exactly_once(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    split_sizes = parameter_record["training_parameters"]["split_sizes"]
    assert split_sizes["final_fit_rows"] == split_sizes["training_rows"] + split_sizes["validation_rows"]
    assert parameter_record["training_parameters"]["validation_evaluation"]["used_for_model_selection"] is False
    assert (
        parameter_record["training_parameters"]["validation_evaluation"]["used_for_hyperparameter_selection"]
        is False
    )
    assert parameter_record["training_parameters"]["final_test"]["used_for_fitting"] is False
    assert parameter_record["training_parameters"]["final_test"]["used_for_model_selection"] is False
    assert parameter_record["training_parameters"]["final_test"]["evaluation_count"] == 1

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    final_test = metrics_artifact["final_test_evaluation"]
    assert final_test["sealed_before_finalization"] is True
    assert final_test["completed"] is True
    assert final_test["evaluation_count"] == 1
    assert final_test["used_for_fitting"] is False
    assert final_test["used_for_model_selection"] is False
    assert final_test["used_for_decision_rule_selection"] is False
    assert final_test["used_for_adjustment"] is False

    validation = metrics_artifact["validation_evaluation"]
    assert validation["used_for_model_selection"] is False
    assert validation["used_for_hyperparameter_selection"] is False
    assert validation["sealed_before_finalization"] is False


def test_no_classification_probability_or_threshold_fields_present(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    for forbidden in (
        "classification_evidence", "per_class_metrics", "confusion_matrix",
        "probability_columns", "threshold", "ordered_class_ids",
    ):
        assert forbidden not in metrics_artifact
        assert forbidden not in parameter_record
        assert forbidden not in metrics_artifact["validation_evaluation"]
        assert forbidden not in metrics_artifact["final_test_evaluation"]

    model_card_input = json.loads((output_directory / MODEL_CARD_INPUT_FILENAME).read_text())
    assert "class_distribution" not in model_card_input["dataset"]
    assert model_card_input["model"]["task_type"] == "continuous_regression"
    model_card = json.loads((output_directory / MODEL_CARD_FILENAME).read_text())
    assert model_card["problem_type"] == "continuous_regression"


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_parameter_record_v3_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert parameter_record["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_TRAINING_PARAMETER_RECORD_VERSION
    schema = json.loads(TRAINING_PARAMETER_RECORD_SCHEMA_PATH.read_text())
    jsonschema.validate(parameter_record, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_metrics_v3_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_artifact["schema_version"] == NATIVE_CONTINUOUS_REGRESSION_TRAINING_METRICS_VERSION
    schema = json.loads(TRAINING_METRICS_SCHEMA_PATH.read_text())
    jsonschema.validate(metrics_artifact, schema)


def test_same_inputs_and_seed_produce_deterministic_split_and_hashes(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    first = train_from_paths(
        contract_path, dataset_path, dataset_slug="synthetic-regression-fixture", run_id="train-20260819T000000Z",
    )
    second = train_from_paths(
        contract_path, dataset_path, dataset_slug="synthetic-regression-fixture", run_id="train-20260819T000001Z",
    )
    assert first.train_indices == second.train_indices
    assert first.evaluation_indices == second.evaluation_indices
    assert first.hashes["model_artifact_sha256"] == second.hashes["model_artifact_sha256"]
    assert first.metrics == second.metrics


# ---------------------------------------------------------------------------
# Unit-level split/metric helper coverage
# ---------------------------------------------------------------------------


def test_random_three_way_split_partitions_are_disjoint_and_cover_all_rows() -> None:
    train, val, test = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    assert set(train) & set(val) == set()
    assert set(train) & set(test) == set()
    assert set(val) & set(test) == set()
    assert set(train) | set(val) | set(test) == set(range(150))
    assert train and val and test


def test_random_three_way_split_is_deterministic_under_seed() -> None:
    first = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    second = _continuous_regression_random_three_way_split_indices(150, 0.7, 0.15, 0.15, 7)
    assert first == second


def test_native_continuous_regression_metric_names_are_the_bounded_three() -> None:
    assert set(NATIVE_CONTINUOUS_REGRESSION_METRIC_NAMES) == {"r2", "mae", "rmse"}


def test_native_continuous_regression_metric_values_computes_finite_r2_mae_rmse() -> None:
    y_true = [1.0, 2.0, 3.0, 4.0, 5.0]
    y_pred = [1.1, 1.9, 3.2, 3.8, 5.3]
    values = _native_continuous_regression_metric_values(
        y_true=y_true, y_pred=y_pred, metric_names=["r2", "mae", "rmse"],
    )
    assert set(values) == {"r2", "mae", "rmse"}
    for value in values.values():
        assert value == value and value not in (float("inf"), float("-inf"))


def test_native_continuous_regression_metric_values_never_calls_predict_proba(monkeypatch) -> None:
    class _NoProbaModel:
        def predict(self, _features):
            return [1.0, 2.0, 3.0]

    model = _NoProbaModel()
    assert not hasattr(model, "predict_proba")
    values = _native_continuous_regression_metric_values(
        y_true=[1.0, 2.0, 3.0], y_pred=model.predict(None), metric_names=["r2", "mae", "rmse"],
    )
    assert set(values) == {"r2", "mae", "rmse"}


def test_native_continuous_regression_metric_values_rejects_non_finite_predictions() -> None:
    with pytest.raises(TrainingInputError):
        _native_continuous_regression_metric_values(
            y_true=[1.0, 2.0, 3.0],
            y_pred=[1.0, float("nan"), 3.0],
            metric_names=["r2"],
        )


def test_validate_fixed_continuous_regression_configuration_accepts_gradient_boosting() -> None:
    model_family, hyperparameters = _validate_fixed_continuous_regression_configuration(
        {
            "allowed_model_families": ["gradient_boosting"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "gradient_boosting",
                "hyperparameters": _gbr_hyperparameters(),
            },
        }
    )
    assert model_family == "gradient_boosting"
    assert hyperparameters["n_estimators"] == 60


def test_validate_fixed_continuous_regression_configuration_accepts_random_forest() -> None:
    model_family, hyperparameters = _validate_fixed_continuous_regression_configuration(
        {
            "allowed_model_families": ["random_forest"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "random_forest",
                "hyperparameters": _rfr_hyperparameters(),
            },
        }
    )
    assert model_family == "random_forest"


def test_validate_fixed_continuous_regression_configuration_rejects_unsupported_family() -> None:
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["hist_gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "hist_gradient_boosting",
                    "hyperparameters": {},
                },
            }
        )
    assert excinfo.value.code == "unsupported_model_family"


def test_validate_fixed_continuous_regression_configuration_rejects_unknown_hyperparameter() -> None:
    hyperparameters = _gbr_hyperparameters()
    hyperparameters["random_state"] = 1
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_validate_fixed_continuous_regression_configuration_rejects_missing_required_field() -> None:
    hyperparameters = _gbr_hyperparameters()
    del hyperparameters["learning_rate"]
    with pytest.raises(TrainingInputError):
        _validate_fixed_continuous_regression_configuration(
            {
                "allowed_model_families": ["gradient_boosting"],
                "selection_mode": "fixed_configuration",
                "fixed_model_configuration": {
                    "model_family": "gradient_boosting",
                    "hyperparameters": hyperparameters,
                },
            }
        )


# ---------------------------------------------------------------------------
# Fail-closed coverage
# ---------------------------------------------------------------------------


def test_unsupported_result_semantics_fails_closed_for_fixed_configuration(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    del contract["result_semantics"]
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_fixed_configuration_result_semantics"


def test_evaluate_allowed_families_continuous_regression_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["modeling_constraints"] = {
        "allowed_model_families": ["gradient_boosting"],
        "no_automl": True,
    }
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_continuous_regression_model_selection"


def test_validated_external_fitted_model_fails_before_fitting(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["model_source_mode"] = "validated_external_fitted_model"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "external_fitted_model_not_trainable_by_atlas"


def test_non_numeric_target_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = "not-a-number"
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_missing_target_value_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = None
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_non_finite_target_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _fixed_continuous_regression_contract())
    dataset = _synthetic_regression_dataset()
    dataset["rows"][0]["outcome_measure"] = float("inf")
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_continuous_target"


def test_unknown_regression_hyperparameter_fails_closed_end_to_end(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    hyperparameters = _gbr_hyperparameters()
    hyperparameters["random_state"] = 5
    contract = _fixed_continuous_regression_contract(hyperparameters=hyperparameters)
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_zero_val_ratio_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["split_policy"] = {"strategy": "random", "train_ratio": 0.85, "val_ratio": 0.0, "test_ratio": 0.15}
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_split_policy"


def test_stratified_split_strategy_fails_closed_for_continuous_regression(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    contract = _fixed_continuous_regression_contract()
    contract["split_policy"] = {"strategy": "stratified", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15}
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _synthetic_regression_dataset())

    with pytest.raises(TrainingInputError) as excinfo:
        train_from_paths(contract_path, dataset_path, dataset_slug="synthetic-regression-fixture")
    assert excinfo.value.code == "invalid_split_policy"
