"""Focused tests for Atlas-native binary fixed-configuration training
(Project Spec S0258, corrective supersession of the blocked Project Spec
S0257 implementation intent).

All fixtures are synthetic and dataset-neutral -- no UCI fetch, no GitHub
access, no dataset-study-* path, no external model bytes, and no
Telco-specific names/values, matching the boundary already established by
tests/test_native_multiclass_training.py and
tests/test_native_continuous_regression_training.py.
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
    ANALYTICAL_VISUALIZATIONS_FILENAME,
    MODEL_ARTIFACT_FILENAME,
    MODEL_CARD_FILENAME,
    MODEL_CARD_INPUT_FILENAME,
    METRICS_ARTIFACT_FILENAME,
    NATIVE_BINARY_FIXED_ANALYTICAL_VISUALIZATIONS_VERSION,
    NATIVE_BINARY_FIXED_HGB_PERMUTATION_IMPORTANCE_N_REPEATS,
    NATIVE_BINARY_FIXED_HGB_PERMUTATION_IMPORTANCE_SCORING,
    NATIVE_BINARY_FIXED_METRIC_NAMES,
    NATIVE_BINARY_FIXED_RESULT_SEMANTICS_SCHEMA_VERSION,
    NATIVE_BINARY_FIXED_TRAINING_METRICS_VERSION,
    NATIVE_BINARY_FIXED_TRAINING_PARAMETER_RECORD_VERSION,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _native_binary_fixed_metric_values,
    _require_binary_result_semantics,
    _validate_fixed_model_configuration,
    train_from_paths,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


REPO_ROOT = Path(__file__).parent.parent
TRAINING_PARAMETER_RECORD_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-parameter-record.schema.json"
TRAINING_METRICS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "training-metrics.schema.json"
ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = REPO_ROOT / "pipeline" / "analytical-visualizations.schema.json"


# ---------------------------------------------------------------------------
# Fixtures -- synthetic dataset-neutral binary fixed HGB contract/rows
# ---------------------------------------------------------------------------


def _hgb_hyperparameters(**overrides) -> dict:
    base = {
        "class_weight": None,
        "l2_regularization": 0.0,
        "learning_rate": 0.1,
        "max_iter": 60,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 5,
    }
    base.update(overrides)
    return base


def _binary_result_semantics(*, positive_class_id: str = "yes", threshold: float = 0.5) -> dict:
    return {
        "schema_version": NATIVE_BINARY_FIXED_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": "binary_classification",
        "positive_class": {"class_id": positive_class_id, "event_label": "Responded"},
        "primary_output": "positive_class_probability",
        "decision": {"threshold": threshold},
        "interpretation": {
            "preset": "risk",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
    }


def _fixed_binary_contract(
    *,
    hyperparameters: dict | None = None,
    split_policy: dict | None = None,
    positive_class_id: str = "yes",
    threshold: float = 0.5,
) -> dict:
    if hyperparameters is None:
        hyperparameters = _hgb_hyperparameters()
    if split_policy is None:
        split_policy = {"strategy": "stratified", "train_ratio": 0.6, "val_ratio": 0.2, "test_ratio": 0.2}
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "synthetic-binary-fixture",
        "target_column": "outcome",
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
        "allowed_transformations": [],
        "split_policy": split_policy,
        "random_seed": 13,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "accuracy", "log_loss", "pr_auc"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": hyperparameters,
            },
        },
        "result_semantics": _binary_result_semantics(positive_class_id=positive_class_id, threshold=threshold),
    }


def _legacy_binary_contract() -> dict:
    """Historical evaluate_allowed_families binary contract -- no
    selection_mode/fixed_model_configuration declared at all."""
    contract = _fixed_binary_contract()
    contract["modeling_constraints"] = {
        "allowed_model_families": ["logistic_regression", "gradient_boosting"],
        "no_automl": True,
        "max_training_time_seconds": 3600,
    }
    return contract


def _synthetic_binary_dataset(row_count: int = 200, seed: int = 0) -> dict:
    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        input_a = rng.uniform(0, 100)
        input_b = rng.uniform(0, 50)
        score = 0.05 * input_a - 0.03 * input_b + rng.uniform(-2, 2)
        label = "yes" if score > 2 else "no"
        rows.append(
            {
                "dataset_id": "synthetic-binary-fixture",
                "record_ref": f"row-{index:04d}",
                "input_a": round(input_a, 4),
                "input_b": round(input_b, 4),
                "outcome": label,
            }
        )
    return {"dataset_id": "synthetic-binary-fixture", "rows": rows}


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    return repo_root


def _write_valid_inputs(
    tmp_path: Path,
    *,
    contract: dict | None = None,
    dataset: dict | None = None,
) -> tuple[Path, Path]:
    contract_path = _write_json(tmp_path / "execution-contract.json", contract or _fixed_binary_contract())
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset or _synthetic_binary_dataset())
    return contract_path, dataset_path


def _run(
    fixed_training_environment: Path,
    tmp_path: Path,
    *,
    contract: dict | None = None,
    dataset: dict | None = None,
    run_id: str = "train-20260819T000000Z",
):
    contract_path, dataset_path = _write_valid_inputs(tmp_path, contract=contract, dataset=dataset)
    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="synthetic-binary-fixture",
        run_id=run_id,
    )
    output_directory = fixed_training_environment / result.output_directory
    return result, output_directory


# ---------------------------------------------------------------------------
# End-to-end fixed-configuration binary runs
# ---------------------------------------------------------------------------


def test_binary_fixed_hgb_training_succeeds_and_produces_expected_artifacts(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)

    assert result.status == "trained"
    assert result.model_family == "hist_gradient_boosting"
    assert result.task_type == "classification"
    for artifact_name in (
        MODEL_ARTIFACT_FILENAME,
        TRAINING_PARAMETER_RECORD_FILENAME,
        METRICS_ARTIFACT_FILENAME,
        MODEL_CARD_INPUT_FILENAME,
        MODEL_CARD_FILENAME,
        ANALYTICAL_VISUALIZATIONS_FILENAME,
    ):
        artifact_path = output_directory / artifact_name
        assert artifact_path.exists(), artifact_name
        assert artifact_path.stat().st_size > 0, artifact_name

    estimator = result.model.named_steps["model"]
    assert type(estimator).__name__ == "HistGradientBoostingClassifier"
    assert estimator.random_state == 13  # governed by execution-contract random_seed, not a hyperparameter

    assert set(result.metrics) == set(NATIVE_BINARY_FIXED_METRIC_NAMES)
    for value in result.metrics.values():
        assert value == value  # not NaN
        assert value not in (float("inf"), float("-inf"))

    # Model artifact is genuinely serialized (Desired Change item 12).
    import joblib

    loaded = joblib.load(output_directory / MODEL_ARTIFACT_FILENAME)
    assert type(loaded.named_steps["model"]).__name__ == "HistGradientBoostingClassifier"


def test_model_selection_evidence_is_absent(fixed_training_environment: Path, tmp_path: Path) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    assert result.model_selection_evidence_path is None
    assert result.model_selection_evidence_produced is False
    assert not (output_directory / "model-selection-evidence.json").exists()


def test_final_test_evaluated_exactly_once(fixed_training_environment: Path, tmp_path: Path) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    final_test = metrics_artifact["final_test_evaluation"]
    assert final_test["evaluation_count"] == 1
    assert final_test["completed"] is True
    assert final_test["sealed_before_finalization"] is True
    assert final_test["used_for_fitting"] is False
    assert final_test["used_for_model_selection"] is False
    assert final_test["used_for_hyperparameter_selection"] is False
    assert final_test["used_for_threshold_selection"] is False


def test_validation_is_descriptive_only(fixed_training_environment: Path, tmp_path: Path) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    validation = metrics_artifact["validation_evaluation"]
    assert validation["used_for_fitting"] is False
    assert validation["used_for_model_selection"] is False
    assert validation["used_for_hyperparameter_selection"] is False
    assert validation["used_for_threshold_selection"] is False
    assert validation["sealed_before_finalization"] is False


def test_fresh_final_fit_uses_train_plus_validation(fixed_training_environment: Path, tmp_path: Path) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    training_parameters = parameter_record["training_parameters"]
    assert training_parameters["final_fit"]["fit_partitions"] == ["train", "validation"]
    split_sizes = training_parameters["split_sizes"]
    assert split_sizes["final_fit_rows"] == split_sizes["training_rows"] + split_sizes["validation_rows"]
    assert training_parameters["initial_fit"]["fit_partition"] == "train"
    assert training_parameters["model_selection_performed"] is False
    assert training_parameters["selection_mode"] == "fixed_configuration"


def test_threshold_is_never_selected_or_tuned(fixed_training_environment: Path, tmp_path: Path) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    training_parameters = parameter_record["training_parameters"]
    assert training_parameters["validation_evaluation"]["used_for_threshold_selection"] is False
    assert training_parameters["final_test"]["used_for_threshold_selection"] is False
    assert parameter_record["classification_evidence"]["threshold"] == 0.5


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_parameter_record_v5_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert parameter_record["schema_version"] == NATIVE_BINARY_FIXED_TRAINING_PARAMETER_RECORD_VERSION
    schema = json.loads(TRAINING_PARAMETER_RECORD_SCHEMA_PATH.read_text())
    jsonschema.validate(parameter_record, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_training_metrics_v5_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    metrics_artifact = json.loads((output_directory / METRICS_ARTIFACT_FILENAME).read_text())
    assert metrics_artifact["schema_version"] == NATIVE_BINARY_FIXED_TRAINING_METRICS_VERSION
    schema = json.loads(TRAINING_METRICS_SCHEMA_PATH.read_text())
    jsonschema.validate(metrics_artifact, schema)


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
def test_analytical_visualizations_v5_validates_against_real_schema(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    assert artifact["schema_version"] == NATIVE_BINARY_FIXED_ANALYTICAL_VISUALIZATIONS_VERSION
    schema = json.loads(ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text())
    jsonschema.validate(artifact, schema)


def test_visual_feature_importance_declares_hgb_permutation_importance_never_final_test(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    _, output_directory = _run(fixed_training_environment, tmp_path)
    artifact = json.loads((output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())

    method = artifact["feature_importance_method"]
    assert method["model_family"] == "hist_gradient_boosting"
    assert method["method"] == "permutation_importance"
    assert method["population_kind"] == "finalized_fit_population"
    assert method["scoring"] == NATIVE_BINARY_FIXED_HGB_PERMUTATION_IMPORTANCE_SCORING
    assert method["scoring"] == "roc_auc"
    assert method["n_repeats"] == NATIVE_BINARY_FIXED_HGB_PERMUTATION_IMPORTANCE_N_REPEATS
    assert method["n_repeats"] == 5
    assert method["random_seed_source"] == "execution_contract.random_seed"

    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    final_fit_rows = parameter_record["training_parameters"]["split_sizes"]["final_fit_rows"]
    test_rows = parameter_record["training_parameters"]["split_sizes"]["test_rows"]
    assert final_fit_rows + test_rows == sum(
        parameter_record["training_parameters"]["split_sizes"][key]
        for key in ("training_rows", "validation_rows", "test_rows")
    )

    feature_importance_chart = next(c for c in artifact["charts"] if c["id"] == "feature_importance")
    values = [point["value"] for point in feature_importance_chart["data"]]
    assert len(values) <= 10
    assert all(value >= 0 for value in values)
    assert abs(sum(values) - 1.0) < 1e-9


def test_permutation_importance_population_is_final_fit_only_never_final_test(
    fixed_training_environment: Path, tmp_path: Path, monkeypatch,
) -> None:
    """Acceptance criteria 17/41: permutation importance must receive only
    the finalized-fit (train+validation) population -- never the sealed
    final-test partition."""
    captured: dict = {}
    from sklearn.inspection import permutation_importance as real_permutation_importance

    def _capturing_permutation_importance(estimator, X, y, **kwargs):
        captured["row_count"] = len(X)
        captured["scoring"] = kwargs.get("scoring")
        captured["n_repeats"] = kwargs.get("n_repeats")
        captured["random_state"] = kwargs.get("random_state")
        return real_permutation_importance(estimator, X, y, **kwargs)

    monkeypatch.setattr(training, "permutation_importance", _capturing_permutation_importance, raising=False)
    import sklearn.inspection

    monkeypatch.setattr(sklearn.inspection, "permutation_importance", _capturing_permutation_importance)

    result, output_directory = _run(fixed_training_environment, tmp_path)
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    final_fit_rows = parameter_record["training_parameters"]["split_sizes"]["final_fit_rows"]

    assert captured["row_count"] == final_fit_rows
    assert captured["scoring"] == "roc_auc"
    assert captured["n_repeats"] == 5
    assert captured["random_state"] == 13


# ---------------------------------------------------------------------------
# Governed positive-class/threshold authority
# ---------------------------------------------------------------------------


def test_positive_class_mismatch_fails_closed(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(positive_class_id="not-a-real-label")
    with pytest.raises(TrainingInputError) as excinfo:
        _run(fixed_training_environment, tmp_path, contract=contract)
    assert excinfo.value.code == "positive_class_not_in_model_classes"


def test_probability_metrics_use_governed_positive_class_probability(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result_yes, output_directory_yes = _run(
        fixed_training_environment, tmp_path, contract=_fixed_binary_contract(positive_class_id="yes"),
        run_id="train-20260819T000001Z",
    )
    parameter_record = json.loads((output_directory_yes / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    evidence = parameter_record["classification_evidence"]
    assert evidence["positive_class_id"] == "yes"
    assert evidence["ordered_class_labels"][evidence["positive_class_probability_index"]] == "yes"


def test_threshold_sensitive_metrics_use_governed_threshold_not_default_decision_boundary() -> None:
    """Desired Change item 41 (unit-level): accuracy/f1 must be computed
    from the governed result_semantics.decision.threshold applied to the
    positive-class probability, never the estimator's own implicit 0.5
    decision boundary baked into predict()."""
    y_true = ["no", "no", "no", "yes", "yes", "yes"]
    positive_scores = [0.10, 0.20, 0.55, 0.60, 0.80, 0.90]
    probabilities = [[1 - score, score] for score in positive_scores]
    classes = ["no", "yes"]

    low_threshold = _native_binary_fixed_metric_values(
        y_true=y_true,
        probabilities=probabilities,
        positive_scores=positive_scores,
        positive_class="yes",
        threshold=0.3,
        classes=classes,
        metric_names=["accuracy", "f1", "roc_auc"],
    )
    high_threshold = _native_binary_fixed_metric_values(
        y_true=y_true,
        probabilities=probabilities,
        positive_scores=positive_scores,
        positive_class="yes",
        threshold=0.85,
        classes=classes,
        metric_names=["accuracy", "f1", "roc_auc"],
    )

    # roc_auc is threshold-independent (uses raw probabilities only).
    assert low_threshold["roc_auc"] == high_threshold["roc_auc"]
    # accuracy/f1 are threshold-sensitive and must differ across thresholds
    # for this fixture (threshold=0.3 predicts 4 positives, threshold=0.85
    # predicts 1 positive).
    assert low_threshold["accuracy"] != high_threshold["accuracy"]
    assert low_threshold["f1"] != high_threshold["f1"]


def test_repeated_deterministic_run_produces_identical_metrics_and_feature_importance(
    fixed_training_environment: Path, tmp_path_factory,
) -> None:
    first_dir = tmp_path_factory.mktemp("first-run")
    second_dir = tmp_path_factory.mktemp("second-run")

    first_result, first_output = _run(fixed_training_environment, first_dir, run_id="train-20260819T000002Z")
    second_result, second_output = _run(fixed_training_environment, second_dir, run_id="train-20260819T000003Z")

    assert first_result.metrics == second_result.metrics

    first_artifact = json.loads((first_output / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    second_artifact = json.loads((second_output / ANALYTICAL_VISUALIZATIONS_FILENAME).read_text())
    first_chart = next(c for c in first_artifact["charts"] if c["id"] == "feature_importance")
    second_chart = next(c for c in second_artifact["charts"] if c["id"] == "feature_importance")
    assert first_chart["data"] == second_chart["data"]


# ---------------------------------------------------------------------------
# Project Spec S0259: optional max_depth reaches the fitted estimator, and
# omission remains backward compatible.
# ---------------------------------------------------------------------------


def test_max_depth_hyperparameter_reaches_estimator(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=4))
    result, _ = _run(fixed_training_environment, tmp_path, contract=contract)

    estimator = result.model.named_steps["model"]
    assert estimator.max_depth == 4


def test_omitted_max_depth_remains_backward_compatible(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, _ = _run(fixed_training_environment, tmp_path, contract=_fixed_binary_contract())

    estimator = result.model.named_steps["model"]
    assert estimator.max_depth is None
    assert result.status == "trained"


def test_null_max_depth_remains_backward_compatible(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=None))
    result, _ = _run(fixed_training_environment, tmp_path, contract=contract)

    estimator = result.model.named_steps["model"]
    assert estimator.max_depth is None
    assert result.status == "trained"


def test_max_depth_configuration_deterministic_across_repeated_runs(
    fixed_training_environment: Path, tmp_path_factory,
) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=3))
    first_dir = tmp_path_factory.mktemp("max-depth-first-run")
    second_dir = tmp_path_factory.mktemp("max-depth-second-run")

    first_result, _ = _run(
        fixed_training_environment, first_dir, contract=contract, run_id="train-20260819T000004Z",
    )
    second_result, _ = _run(
        fixed_training_environment, second_dir, contract=contract, run_id="train-20260819T000005Z",
    )

    assert first_result.metrics == second_result.metrics
    assert first_result.model.named_steps["model"].max_depth == 3
    assert second_result.model.named_steps["model"].max_depth == 3


# ---------------------------------------------------------------------------
# Fail-closed validation before any fit
# ---------------------------------------------------------------------------


def test_invalid_max_depth_zero_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=0))
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_invalid_max_depth_negative_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=-1))
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_invalid_max_depth_boolean_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=True))
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_invalid_max_depth_non_integer_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters(max_depth=2.5))
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_invalid_configuration_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract()
    contract["modeling_constraints"]["allowed_model_families"] = ["gradient_boosting"]
    contract["modeling_constraints"]["fixed_model_configuration"]["model_family"] = "gradient_boosting"
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_missing_hgb_hyperparameter_fails_before_fit(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(hyperparameters=_hgb_hyperparameters())
    del contract["modeling_constraints"]["fixed_model_configuration"]["hyperparameters"]["max_iter"]
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_missing_result_semantics_fails_closed(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract()
    del contract["result_semantics"]
    with pytest.raises(TrainingInputError):
        _run(fixed_training_environment, tmp_path, contract=contract)


def test_non_stratified_split_strategy_rejected(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(
        split_policy={"strategy": "random", "train_ratio": 0.6, "val_ratio": 0.2, "test_ratio": 0.2},
    )
    with pytest.raises(TrainingInputError) as excinfo:
        _run(fixed_training_environment, tmp_path, contract=contract)
    assert excinfo.value.code == "invalid_split_policy"


def test_empty_validation_partition_rejected(fixed_training_environment: Path, tmp_path: Path) -> None:
    contract = _fixed_binary_contract(
        split_policy={"strategy": "stratified", "train_ratio": 0.8, "val_ratio": 0.0, "test_ratio": 0.2},
    )
    with pytest.raises(TrainingInputError) as excinfo:
        _run(fixed_training_environment, tmp_path, contract=contract)
    assert excinfo.value.code == "invalid_split_policy"


def test_empty_test_partition_from_a_tiny_dataset_fails_closed(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    tiny_dataset = {
        "dataset_id": "synthetic-binary-fixture",
        "rows": [
            {"dataset_id": "synthetic-binary-fixture", "record_ref": "r0", "input_a": 1.0, "input_b": 2.0, "outcome": "yes"},
            {"dataset_id": "synthetic-binary-fixture", "record_ref": "r1", "input_a": 3.0, "input_b": 4.0, "outcome": "yes"},
            {"dataset_id": "synthetic-binary-fixture", "record_ref": "r2", "input_a": 5.0, "input_b": 6.0, "outcome": "no"},
            {"dataset_id": "synthetic-binary-fixture", "record_ref": "r3", "input_a": 7.0, "input_b": 8.0, "outcome": "no"},
        ],
    }
    with pytest.raises(TrainingInputError) as excinfo:
        _run(fixed_training_environment, tmp_path, dataset=tiny_dataset)
    assert excinfo.value.code == "invalid_prepared_dataset"


def test_require_binary_result_semantics_rejects_wrong_schema_version() -> None:
    with pytest.raises(TrainingInputError):
        _require_binary_result_semantics({
            "result_semantics": {
                "schema_version": "multiclass-result-semantics.v1",
                "problem_type": "binary_classification",
            }
        })


def test_require_binary_result_semantics_rejects_missing_threshold() -> None:
    bad = _binary_result_semantics()
    del bad["decision"]["threshold"]
    with pytest.raises(TrainingInputError):
        _require_binary_result_semantics({"result_semantics": bad})


def test_validate_fixed_model_configuration_rejects_non_hgb_family() -> None:
    with pytest.raises(TrainingInputError):
        _validate_fixed_model_configuration({
            "allowed_model_families": ["gradient_boosting"],
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "gradient_boosting",
                "hyperparameters": {},
            },
        })


# ---------------------------------------------------------------------------
# Historical binary evaluate_allowed_families path remains callable
# ---------------------------------------------------------------------------


def test_legacy_binary_evaluate_allowed_families_path_remains_callable(
    fixed_training_environment: Path, tmp_path: Path,
) -> None:
    result, output_directory = _run(fixed_training_environment, tmp_path, contract=_legacy_binary_contract())

    assert result.status == "trained"
    assert result.task_type == "classification"
    assert result.model_family in ("logistic_regression", "gradient_boosting")
    assert (output_directory / MODEL_ARTIFACT_FILENAME).exists()
    # The legacy path never emits training-parameter-record.v5/training-metrics.v5.
    parameter_record = json.loads((output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text())
    assert parameter_record["schema_version"] == "training-parameter-record.v1"
