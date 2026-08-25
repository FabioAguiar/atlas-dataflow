"""Focused tests for Atlas-native binary v5 inference-bundle generation
(Project Spec S0259).

Covers `pipeline/generate_inference_bundle.py`'s explicit closed dispatch on
the internal binary training-parameter-record schema version:
`training-parameter-record.v1` (legacy, unchanged `binary_classification_evidence`
logic) versus `training-parameter-record.v5` (Atlas-native fixed-configuration,
governed `classification_evidence` logic). All fixtures are synthetic and
temporary -- no UCI fetch, no GitHub access, no Telco-specific names/values.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.generate_inference_bundle import (  # noqa: E402
    BundleGenerationError,
    _build_bundle,
    _build_parser,
)

_FEATURE_COLUMNS = ["input_a", "input_b"]


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    return path


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic_execution_contract(
    *, positive_class_id: str = "yes", threshold: float = 0.5,
) -> dict[str, Any]:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "synthetic-binary-fixture",
        "feature_columns": list(_FEATURE_COLUMNS),
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
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
        },
    }


def _synthetic_runtime_contract() -> dict[str, Any]:
    return {"schema_version": "1.0.0", "features": [{"name": name, "required": True} for name in _FEATURE_COLUMNS]}


def _synthetic_public_contract() -> dict[str, Any]:
    return {"schema_version": "1.0.0", "features": [{"name": name, "label": name} for name in _FEATURE_COLUMNS]}


def _synthetic_prepared_dataset_metadata() -> dict[str, Any]:
    return {
        "schema_version": "prepared-data-metadata.v1",
        "dataset_identity": {"dataset_slug": "synthetic-binary-fixture"},
    }


def _synthetic_metrics() -> dict[str, Any]:
    return {
        "schema_version": "training-metrics.v1",
        "training_run_identity": {
            "dataset_slug": "synthetic-binary-fixture",
            "run_id": "train-20260819T000000Z",
        },
    }


def _v1_training_record(
    *,
    execution_contract_sha256: str,
    prepared_dataset_sha256: str,
    model_artifact_sha256: str,
    metrics_sha256: str,
    positive_class_id: str = "yes",
    model_family: str = "gradient_boosting",
) -> dict[str, Any]:
    return {
        "schema_version": "training-parameter-record.v1",
        "training_run_identity": {
            "dataset_slug": "synthetic-binary-fixture",
            "run_id": "train-20260819T000000Z",
        },
        "produced_outputs": {
            "serialized_model_path": "models/model.pkl",
            "training_parameter_record_path": "training/training-parameter-record.json",
        },
        "serializer": {"name": "joblib", "installed_version": "1.4.0"},
        "training_parameters": {"model_family": model_family, "feature_columns": list(_FEATURE_COLUMNS)},
        "binary_classification_evidence": {"positive_class_id": positive_class_id},
        "hashes": {
            "execution_contract_sha256": execution_contract_sha256,
            "prepared_dataset_sha256": prepared_dataset_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
    }


def _v5_training_record(
    *,
    execution_contract_sha256: str,
    prepared_dataset_sha256: str,
    model_artifact_sha256: str,
    metrics_sha256: str,
    positive_class_id: str = "yes",
    threshold: float = 0.5,
    ordered_class_labels: list[str] | None = None,
    positive_class_probability_index: int = 1,
    result_semantics_schema_version: str = "binary-result-semantics.v1",
    problem_type: str = "binary_classification",
    schema_version: str = "training-parameter-record.v5",
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "training_run_identity": {
            "dataset_slug": "synthetic-binary-fixture",
            "run_id": "train-20260819T000000Z",
        },
        "produced_outputs": {
            "serialized_model_path": "models/model.pkl",
            "training_parameter_record_path": "training/training-parameter-record.json",
        },
        "serializer": {"name": "joblib", "installed_version": "1.4.0"},
        "training_parameters": {
            "model_family": "hist_gradient_boosting",
            "feature_columns": list(_FEATURE_COLUMNS),
        },
        "classification_evidence": {
            "problem_type": problem_type,
            "result_semantics_schema_version": result_semantics_schema_version,
            "ordered_class_labels": list(ordered_class_labels) if ordered_class_labels is not None else ["no", "yes"],
            "positive_class_id": positive_class_id,
            "positive_class_probability_index": positive_class_probability_index,
            "threshold": threshold,
        },
        "hashes": {
            "execution_contract_sha256": execution_contract_sha256,
            "prepared_dataset_sha256": prepared_dataset_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
    }


def _write_fixtures(
    tmp_path: Path,
    *,
    training_record_builder,
    training_record_overrides: dict[str, Any] | None = None,
    execution_contract_positive_class_id: str = "yes",
    execution_contract_threshold: float = 0.5,
    class_labels: tuple[str, ...] = ("no", "yes"),
) -> list[str]:
    execution_contract = _synthetic_execution_contract(
        positive_class_id=execution_contract_positive_class_id, threshold=execution_contract_threshold,
    )
    execution_contract_path = _write_json(tmp_path / "execution-contract.json", execution_contract)
    runtime_contract_path = _write_json(tmp_path / "runtime-contract.json", _synthetic_runtime_contract())
    public_contract_path = _write_json(tmp_path / "public-contract.json", _synthetic_public_contract())
    prepared_dataset_path = _write_json(
        tmp_path / "prepared-data-metadata.json", _synthetic_prepared_dataset_metadata()
    )
    model_artifact_path = _write_bytes(tmp_path / "model.pkl", b"synthetic-joblib-model-bytes")
    metrics_path = _write_json(tmp_path / "metrics.json", _synthetic_metrics())

    training_record_kwargs = dict(
        execution_contract_sha256=_sha256_bytes(execution_contract_path.read_bytes()),
        prepared_dataset_sha256=_sha256_bytes(prepared_dataset_path.read_bytes()),
        model_artifact_sha256=_sha256_bytes(model_artifact_path.read_bytes()),
        metrics_sha256=_sha256_bytes(metrics_path.read_bytes()),
    )
    training_record_kwargs.update(training_record_overrides or {})
    training_record = training_record_builder(**training_record_kwargs)
    training_record_path = _write_json(tmp_path / "training-parameter-record.json", training_record)

    output_path = tmp_path / "inference-bundle.json"
    argv = [
        "--execution-contract", str(execution_contract_path),
        "--runtime-contract", str(runtime_contract_path),
        "--public-contract", str(public_contract_path),
        "--prepared-dataset", str(prepared_dataset_path),
        "--training-parameter-record", str(training_record_path),
        "--training-metrics", str(metrics_path),
        "--model-artifact", str(model_artifact_path),
        "--output", str(output_path),
        "--release-package-reference", "predictions/bundle.json",
        "--prediction-type", "string",
        "--release-id", "release-20260819-001",
        "--dataset-slug", "synthetic-binary-fixture",
        "--execution-contract-ref", "contracts/synthetic-binary-fixture/execution-contract.json",
        "--runtime-contract-ref", "contracts/synthetic-binary-fixture/runtime-contract.json",
        "--public-contract-ref", "contracts/synthetic-binary-fixture/public-contract.json",
        "--prepared-dataset-ref",
        "pipeline/prepared/synthetic-binary-fixture/prepared-data-metadata.json",
        "--dataset-context-ref",
        "pipeline/prepared/synthetic-binary-fixture/prepared-data-metadata.json",
        "--training-parameter-record-ref", "training/training-parameter-record.json",
        "--training-metrics-ref", "training/metrics.json",
        "--model-artifact-ref", "models/model.pkl",
        "--probability-output", "true",
    ]
    for label in class_labels:
        argv.extend(["--class-label", label])
    return argv


def _build(tmp_path: Path, **kwargs) -> dict[str, Any]:
    argv = _write_fixtures(tmp_path, **kwargs)
    args = _build_parser().parse_args(argv)
    return _build_bundle(args)


# ---------------------------------------------------------------------------
# v5 training evidence -> valid inference_bundle.v1, sourced from
# classification_evidence (never binary_classification_evidence, never
# fabricated).
# ---------------------------------------------------------------------------


def test_v5_training_evidence_generates_valid_bundle(tmp_path: Path) -> None:
    bundle = _build(tmp_path, training_record_builder=_v5_training_record)

    result_semantics = bundle["result_semantics"]
    assert result_semantics["schema_version"] == "binary-result-semantics.v1"
    assert result_semantics["problem_type"] == "binary_classification"
    assert result_semantics["positive_class"] == {"class_id": "yes", "event_label": "Responded"}
    assert result_semantics["decision"] == {"threshold": 0.5}
    assert result_semantics["model_descriptor"] == {
        "model_family": "hist_gradient_boosting",
        "display_name": "HistGradientBoosting",
    }


def test_v5_classification_evidence_is_used_never_binary_classification_evidence(tmp_path: Path) -> None:
    # A v5 record with no binary_classification_evidence key at all must
    # still generate a valid bundle -- the resolver never looks for it.
    bundle = _build(tmp_path, training_record_builder=_v5_training_record)
    assert "result_semantics" in bundle


def test_v5_positive_class_mismatch_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"positive_class_id": "no", "positive_class_probability_index": 0},
        )


def test_v5_threshold_mismatch_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"threshold": 0.7},
            execution_contract_threshold=0.5,
        )


def test_v5_class_order_mismatch_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"ordered_class_labels": ["maybe", "yes"]},
        )


def test_v5_positive_class_probability_index_out_of_range_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"positive_class_probability_index": 2},
        )


def test_v5_result_semantics_schema_version_mismatch_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"result_semantics_schema_version": "binary-result-semantics.v0"},
        )


def test_v5_wrong_model_family_rejected(tmp_path: Path) -> None:
    argv = _write_fixtures(tmp_path, training_record_builder=_v5_training_record)
    args = _build_parser().parse_args(argv)
    # Corrupt the already-written training record's model_family in place.
    training_record_path = Path(args.training_parameter_record)
    record = json.loads(training_record_path.read_text(encoding="utf-8"))
    record["training_parameters"]["model_family"] = "gradient_boosting"
    training_record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(BundleGenerationError):
        _build_bundle(args)


# ---------------------------------------------------------------------------
# Legacy v1 internal bundle fixture remains valid (unchanged behavior).
# ---------------------------------------------------------------------------


def test_legacy_v1_internal_bundle_fixture_remains_valid(tmp_path: Path) -> None:
    bundle = _build(tmp_path, training_record_builder=_v1_training_record)

    result_semantics = bundle["result_semantics"]
    assert result_semantics["schema_version"] == "binary-result-semantics.v1"
    assert result_semantics["positive_class"] == {"class_id": "yes", "event_label": "Responded"}
    assert result_semantics["model_descriptor"] == {
        "model_family": "gradient_boosting",
        "display_name": "Gradient Boosting",
    }


def test_legacy_v1_positive_class_mismatch_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v1_training_record,
            training_record_overrides={"positive_class_id": "no"},
        )


# ---------------------------------------------------------------------------
# Unknown internal binary training-record version fails closed instead of
# being silently treated as v1.
# ---------------------------------------------------------------------------


def test_unknown_internal_binary_training_record_version_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"schema_version": "training-parameter-record.v99"},
        )


def test_multiclass_internal_training_record_version_never_silently_treated_as_binary_v1(
    tmp_path: Path,
) -> None:
    # A v2 (multiclass) internal schema_version must never fall through to
    # the legacy v1 binary_classification_evidence path just because it is
    # neither the external profile nor v5.
    with pytest.raises(BundleGenerationError):
        _build(
            tmp_path,
            training_record_builder=_v5_training_record,
            training_record_overrides={"schema_version": "training-parameter-record.v2"},
        )
