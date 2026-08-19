"""Project Spec S0225: continuous-regression governed inference bundle.

Covers the closed binary/multiclass/continuous-regression result_semantics
union added to contracts/inference-bundle.schema.json and the dedicated
Atlas-native continuous-regression resolver added to
pipeline/generate_inference_bundle.py. All fixtures are synthetic and
temporary -- no Concrete release or dataset-study repository dependency.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.generate_inference_bundle import (  # noqa: E402
    BundleGenerationError,
    _build_bundle,
    _build_parser,
    _write_bundle,
)

_REGRESSION_FEATURE_COLUMNS = ["feature_a", "feature_b", "feature_c"]
_INFERENCE_BUNDLE_SCHEMA_PATH = REPO_ROOT / "contracts" / "inference-bundle.schema.json"
_EXAMPLE_BUNDLE_PATH = REPO_ROOT / "contracts" / "examples" / "inference-bundle.example.json"
_TELCO_BUNDLE_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "inference-bundle.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _bundle_schema_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(_INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def _base_example_bundle() -> dict[str, Any]:
    return json.loads(_EXAMPLE_BUNDLE_PATH.read_text(encoding="utf-8"))


def _continuous_result_semantics_fragment(**overrides: Any) -> dict[str, Any]:
    fragment = {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "result_schema_version": "continuous-regression-result.v1",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }
    fragment.update(overrides)
    return fragment


# ---------------------------------------------------------------------------
# Schema-level tests (contracts/inference-bundle.schema.json)
# ---------------------------------------------------------------------------


def test_schema_accepts_strict_continuous_regression_result_semantics() -> None:
    validator = _bundle_schema_validator()
    bundle = _base_example_bundle()
    bundle["output_schema"] = {"prediction_key": "prediction", "prediction_type": "number"}
    bundle["result_semantics"] = _continuous_result_semantics_fragment()
    bundle["model_provenance_origin"] = "atlas_internal_training"
    assert list(validator.iter_errors(bundle)) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("positive_class", {"class_id": "x", "event_label": "y"}),
        ("classes", []),
        ("class_labels", ["a", "b"]),
        ("probability_output", True),
        ("threshold", 0.5),
        ("decision", {"threshold": 0.5}),
        ("interpretation", {"preset": "risk", "bands": []}),
    ],
)
def test_schema_rejects_classification_fields_in_continuous_regression_result_semantics(
    field: str, value: Any
) -> None:
    validator = _bundle_schema_validator()
    bundle = _base_example_bundle()
    bundle["output_schema"] = {"prediction_key": "prediction", "prediction_type": "number"}
    result_semantics = _continuous_result_semantics_fragment()
    result_semantics[field] = value
    bundle["result_semantics"] = result_semantics
    bundle["model_provenance_origin"] = "atlas_internal_training"
    assert list(validator.iter_errors(bundle)) != []


def test_existing_binary_bundle_fixture_remains_valid() -> None:
    validator = _bundle_schema_validator()
    bundle = json.loads(_TELCO_BUNDLE_PATH.read_text(encoding="utf-8"))
    assert list(validator.iter_errors(bundle)) == []


def test_existing_multiclass_bundle_shape_remains_valid() -> None:
    validator = _bundle_schema_validator()
    bundle = _base_example_bundle()
    bundle["output_schema"] = {
        "prediction_key": "prediction",
        "prediction_type": "string",
        "class_labels": ["a", "b", "c"],
        "probability_output": True,
    }
    bundle["result_semantics"] = {
        "schema_version": "multiclass-result-semantics.v1",
        "problem_type": "multiclass_classification",
        "result_schema_version": "multiclass-classification-result.v1",
        "classes": [
            {"class_id": "a", "display_label": "A"},
            {"class_id": "b", "display_label": "B"},
            {"class_id": "c", "display_label": "C"},
        ],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
        "model_descriptor": {"model_family": "random_forest", "display_name": "Random Forest"},
    }
    assert list(validator.iter_errors(bundle)) == []


# ---------------------------------------------------------------------------
# Generator-level tests (pipeline/generate_inference_bundle.py)
# ---------------------------------------------------------------------------


def _continuous_execution_contract(
    *,
    contract_version: str = "execution_contract.v1",
    result_semantics_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_semantics = {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
    }
    if result_semantics_overrides:
        result_semantics.update(result_semantics_overrides)
    return {
        "contract_version": contract_version,
        "dataset_id": "synthetic-regression",
        "feature_columns": list(_REGRESSION_FEATURE_COLUMNS),
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "result_semantics": result_semantics,
    }


def _continuous_training_record(
    *,
    schema_version: str = "training-parameter-record.v3",
    problem_type: str = "continuous_regression",
    model_family: str = "gradient_boosting",
    selection_mode: str = "fixed_configuration",
    model_selection_performed: bool = False,
    regression_evidence: dict[str, Any] | None = None,
    execution_contract_sha256: str,
    prepared_dataset_sha256: str,
    model_artifact_sha256: str,
    metrics_sha256: str,
    dataset_slug: str = "synthetic-regression",
    run_id: str = "train-20260819T000000Z",
) -> dict[str, Any]:
    if regression_evidence is None:
        regression_evidence = {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        }
    return {
        "schema_version": schema_version,
        "problem_type": problem_type,
        "training_run_identity": {"dataset_slug": dataset_slug, "run_id": run_id},
        "produced_outputs": {
            "serialized_model_path": "models/model.joblib",
            "training_parameter_record_path": "training/training-parameter-record.json",
        },
        "serializer": {"name": "joblib", "installed_version": "1.4.0"},
        "training_parameters": {
            "model_family": model_family,
            "feature_columns": list(_REGRESSION_FEATURE_COLUMNS),
            "selection_mode": selection_mode,
            "model_selection_performed": model_selection_performed,
        },
        "regression_evidence": regression_evidence,
        "hashes": {
            "execution_contract_sha256": execution_contract_sha256,
            "prepared_dataset_sha256": prepared_dataset_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
    }


def _continuous_metrics(
    *,
    schema_version: str = "training-metrics.v3",
    regression_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if regression_evidence is None:
        regression_evidence = {
            "problem_type": "continuous_regression",
            "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
            "output_value_kind": "continuous_numeric",
        }
    return {"schema_version": schema_version, "regression_evidence": regression_evidence}


def _continuous_argv(
    tmp_path: Path,
    *,
    model_family: str = "gradient_boosting",
    prediction_type: str = "number",
    class_labels: list[str] | None = None,
    probability_output: bool | None = None,
    execution_contract_result_semantics_overrides: dict[str, Any] | None = None,
    training_record_overrides: dict[str, Any] | None = None,
    metrics_overrides: dict[str, Any] | None = None,
) -> list[str]:
    execution_contract_path = tmp_path / "execution-contract.json"
    _write_json(
        execution_contract_path,
        _continuous_execution_contract(
            result_semantics_overrides=execution_contract_result_semantics_overrides
        ),
    )
    runtime_contract_path = tmp_path / "runtime-contract.json"
    _write_json(runtime_contract_path, {"schema_version": "1.0.0"})
    public_contract_path = tmp_path / "public-contract.json"
    _write_json(public_contract_path, {"schema_version": "1.0.0"})
    prepared_dataset_path = tmp_path / "prepared-data-metadata.json"
    _write_json(prepared_dataset_path, {"schema_version": "prepared-data-metadata.v1"})
    model_artifact_path = tmp_path / "model.joblib"
    model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    model_artifact_path.write_bytes(b"synthetic-joblib-regression-model-bytes")
    metrics_path = tmp_path / "metrics.json"
    _write_json(metrics_path, _continuous_metrics(**(metrics_overrides or {})))

    execution_contract_sha256 = hashlib.sha256(execution_contract_path.read_bytes()).hexdigest()
    prepared_dataset_sha256 = hashlib.sha256(prepared_dataset_path.read_bytes()).hexdigest()
    model_artifact_sha256 = hashlib.sha256(model_artifact_path.read_bytes()).hexdigest()
    metrics_sha256 = hashlib.sha256(metrics_path.read_bytes()).hexdigest()

    training_record_kwargs: dict[str, Any] = {
        "model_family": model_family,
        "execution_contract_sha256": execution_contract_sha256,
        "prepared_dataset_sha256": prepared_dataset_sha256,
        "model_artifact_sha256": model_artifact_sha256,
        "metrics_sha256": metrics_sha256,
    }
    training_record_kwargs.update(training_record_overrides or {})
    training_record_path = tmp_path / "training-parameter-record.json"
    _write_json(training_record_path, _continuous_training_record(**training_record_kwargs))

    argv = [
        "--execution-contract", str(execution_contract_path),
        "--runtime-contract", str(runtime_contract_path),
        "--public-contract", str(public_contract_path),
        "--prepared-dataset", str(prepared_dataset_path),
        "--training-parameter-record", str(training_record_path),
        "--training-metrics", str(metrics_path),
        "--model-artifact", str(model_artifact_path),
        "--output", str(tmp_path / "inference-bundle.json"),
        "--release-package-reference", "predictions/bundle.json",
        "--prediction-type", prediction_type,
        "--release-id", "release-20260819-001",
        "--dataset-slug", "synthetic-regression",
        "--execution-contract-ref", "contracts/synthetic-regression/execution-contract.json",
        "--runtime-contract-ref", "contracts/synthetic-regression/runtime-contract.json",
        "--public-contract-ref", "contracts/synthetic-regression/public-contract.json",
        "--prepared-dataset-ref",
        "pipeline/prepared/synthetic-regression/prepared-data-metadata.json",
        "--dataset-context-ref",
        "pipeline/prepared/synthetic-regression/prepared-data-metadata.json",
        "--training-parameter-record-ref", "training/training-parameter-record.json",
        "--training-metrics-ref", "training/metrics.json",
        "--model-artifact-ref", "models/model.joblib",
    ]
    if class_labels:
        for label in class_labels:
            argv += ["--class-label", label]
    if probability_output is not None:
        argv += ["--probability-output", "true" if probability_output else "false"]
    return argv


def _build_from_argv(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    argv = _continuous_argv(tmp_path, **overrides)
    args = _build_parser().parse_args(argv)
    return _build_bundle(args)


def test_generator_projects_v3_training_and_metrics_into_valid_bundle(tmp_path: Path) -> None:
    bundle = _build_from_argv(tmp_path)

    assert bundle["result_semantics"] == {
        "schema_version": "continuous-regression-result-semantics.v1",
        "problem_type": "continuous_regression",
        "result_schema_version": "continuous-regression-result.v1",
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
        "model_descriptor": {"model_family": "gradient_boosting", "display_name": "Gradient Boosting"},
    }
    assert bundle["output_schema"] == {"prediction_key": "prediction", "prediction_type": "number"}
    assert bundle["model_provenance_origin"] == "atlas_internal_training"
    assert "external_model_evidence" not in bundle
    assert "training_evidence" in bundle
    assert bundle["training_evidence"]["model_selection_evidence"] is None

    validator = _bundle_schema_validator()
    assert list(validator.iter_errors(bundle)) == []


def test_prediction_type_not_number_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, prediction_type="string")
    assert exc_info.value.field == "output_schema.prediction_type"


def test_class_labels_on_continuous_regression_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, class_labels=["low", "high"])
    assert exc_info.value.field == "output_schema.class_labels"


def test_probability_output_on_continuous_regression_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, probability_output=True)
    assert exc_info.value.field == "output_schema.probability_output"


def test_wrong_training_parameter_record_version_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path, training_record_overrides={"schema_version": "training-parameter-record.v1"}
        )
    assert exc_info.value.field == "schema_version"


def test_wrong_training_record_problem_type_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, training_record_overrides={"problem_type": "binary_classification"})
    assert exc_info.value.field == "problem_type"


def test_wrong_training_record_regression_evidence_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path,
            training_record_overrides={
                "regression_evidence": {
                    "problem_type": "continuous_regression",
                    "result_semantics_schema_version": "continuous-regression-result-semantics.v0",
                    "output_value_kind": "continuous_numeric",
                }
            },
        )
    assert exc_info.value.field == "training_parameter_record.regression_evidence.result_semantics_schema_version"


def test_wrong_training_metrics_version_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, metrics_overrides={"schema_version": "training-metrics.v1"})
    assert exc_info.value.field == "training_metrics.schema_version"


def test_wrong_metrics_regression_evidence_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path,
            metrics_overrides={
                "regression_evidence": {
                    "problem_type": "continuous_regression",
                    "result_semantics_schema_version": "continuous-regression-result-semantics.v1",
                    "output_value_kind": "discrete_numeric",
                }
            },
        )
    assert exc_info.value.field == "training_metrics.regression_evidence.output_value_kind"


def test_unsupported_model_family_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(tmp_path, model_family="logistic_regression")
    assert exc_info.value.code == "unsupported_model_family"
    assert exc_info.value.field == "training_parameters.model_family"


@pytest.mark.parametrize(
    "model_family,expected_display_name",
    [
        ("gradient_boosting", "Gradient Boosting"),
        ("random_forest", "Random Forest"),
    ],
)
def test_model_descriptor_display_name_is_deterministic(
    tmp_path: Path, model_family: str, expected_display_name: str
) -> None:
    bundle = _build_from_argv(tmp_path, model_family=model_family)
    assert bundle["result_semantics"]["model_descriptor"] == {
        "model_family": model_family,
        "display_name": expected_display_name,
    }


def test_unknown_result_semantics_problem_type_blocks(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError) as exc_info:
        _build_from_argv(
            tmp_path,
            execution_contract_result_semantics_overrides={"problem_type": "count_regression"},
        )
    assert exc_info.value.field == "result_semantics.problem_type"


def test_no_partial_bundle_written_after_blocking_error(tmp_path: Path) -> None:
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    argv = _continuous_argv(blocked_dir, prediction_type="string")
    args = _build_parser().parse_args(argv)
    output_path = Path(args.output)

    with pytest.raises(BundleGenerationError):
        bundle = _build_bundle(args)
        _write_bundle(bundle, output_path)
    assert not output_path.exists()

    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    argv_ok = _continuous_argv(ok_dir)
    args_ok = _build_parser().parse_args(argv_ok)
    output_path_ok = Path(args_ok.output)
    bundle_ok = _build_bundle(args_ok)
    _write_bundle(bundle_ok, output_path_ok)
    assert output_path_ok.exists()
