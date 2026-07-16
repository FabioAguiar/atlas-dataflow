"""
Inference bundle generator for atlas-dataflow M25-02.

Builds an inference_bundle.v1 artifact from governed contract, prepared
dataset, model, and training evidence files. The generator only consumes
explicit file paths and release-relative references supplied by the caller or
derived from repository-relative paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.training import _prepared_dataset_metadata_blocking_reasons


INFERENCE_BUNDLE_SCHEMA = "contracts/inference-bundle.schema.json"
INFERENCE_BUNDLE_VERSION = "inference_bundle.v1"
DEFAULT_MODEL_PACKAGE_REFERENCE = "models/model.pkl"
SUPPORTED_SERIALIZATION_FORMAT = "joblib"
SUPPORTED_LOADER_STRATEGY = "joblib_sklearn_predict"
SUPPORTED_PREDICTION_INTERFACE = "predict"
SUPPORTED_MODEL_FAMILIES = frozenset({
    "logistic_regression",
    "gradient_boosting",
    "random_forest",
})
# Project Spec S0108: deterministic code mapping from model-family ID to a
# safe display descriptor. Never looked up any other way (e.g. from editable
# profile copy) -- the design prototype's "Logistic Regression" placeholder
# must never be hardcoded as a default; this dict is keyed and looked up by
# whatever model_family the actual training evidence recorded.
MODEL_FAMILY_DISPLAY_NAMES: dict[str, str] = {
    "logistic_regression": "Logistic Regression",
    "gradient_boosting": "Gradient Boosting",
    "random_forest": "Random Forest",
}
BINARY_RESULT_SEMANTICS_SCHEMA_VERSION = "binary-result-semantics.v1"
BINARY_CLASSIFICATION_RESULT_SCHEMA_VERSION = "binary-classification-result.v1"
SUPPORTED_PREDICTION_TYPES = frozenset({"number", "integer", "string", "boolean"})
SUPPORTED_ENCODINGS = frozenset({"onehot", "ordinal", "target_encode", "binary"})
SUPPORTED_NUMERIC_HANDLING = frozenset({"standardize", "normalize", "passthrough"})
SUPPORTED_TRANSFORMATIONS = frozenset({"log1p", "sqrt", "clip", "passthrough"})
SUPPORTED_MISSING_POLICIES = frozenset({"mean", "median", "mode", "constant", "drop_row"})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DATASET_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RELEASE_ID_RE = re.compile(r"^release-[0-9]{8}-[0-9]{3}$")
RUN_ID_RE = re.compile(r"^train-[0-9]{8}T[0-9]{6}Z$")
FEATURE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RELEASE_RELATIVE_RE = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*//)[A-Za-z0-9][A-Za-z0-9._/-]*$"
)


class BundleGenerationError(ValueError):
    """Actionable generation failure raised before a bundle is published."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "rejected",
            "error": {
                "code": self.code,
                "field": self.field,
                "message": str(self),
            },
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json_file(path: Path, field_name: str) -> dict[str, Any]:
    if not path.exists():
        raise BundleGenerationError(
            "missing_required_artifact",
            f"{field_name} does not exist: {path}",
            field=field_name,
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleGenerationError(
            "invalid_json",
            f"{field_name} is not valid JSON: {exc}",
            field=field_name,
        ) from exc
    if not isinstance(loaded, dict):
        raise BundleGenerationError(
            "invalid_json",
            f"{field_name} must be a JSON object.",
            field=field_name,
        )
    return loaded


def _sha256_file(path: Path) -> str:
    if not path.exists():
        raise BundleGenerationError(
            "missing_required_artifact",
            f"cannot hash missing artifact: {path}",
        )
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(data: dict[str, Any], field: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        raise BundleGenerationError(
            "missing_required_field",
            f"{field} must be present as an object.",
            field=field,
        )
    return value


def _require_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise BundleGenerationError(
            "missing_required_field",
            f"{field} must be present as a non-empty string.",
            field=field,
        )
    return value


def _optional_version(data: dict[str, Any], field_name: str) -> str:
    for key in ("contract_version", "schema_version"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    raise BundleGenerationError(
        "missing_required_field",
        f"{field_name} must declare contract_version or schema_version.",
        field=field_name,
    )


def _validate_release_relative(value: str, field: str, *, file_path: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise BundleGenerationError(
            "invalid_release_reference",
            f"{field} must be a non-empty release-relative path.",
            field=field,
        )
    if not RELEASE_RELATIVE_RE.fullmatch(value) or re.search(r"(^|/)\.\.(/|$)", value):
        raise BundleGenerationError(
            "invalid_release_reference",
            f"{field} must be release-relative and must not be absolute, contain parent traversal, or repeated separators.",
            field=field,
        )
    if ":" in value or "\\" in value:
        raise BundleGenerationError(
            "invalid_release_reference",
            f"{field} must not contain URI schemes, drive letters, or backslashes.",
            field=field,
        )
    if file_path and value.endswith("/"):
        raise BundleGenerationError(
            "invalid_release_reference",
            f"{field} must reference a file, not a directory.",
            field=field,
        )
    return value


def _reference_for_path(path: Path, explicit_ref: str | None, field: str) -> str:
    if explicit_ref:
        return _validate_release_relative(explicit_ref, field, file_path=True)
    try:
        relative = path.resolve().relative_to(_repo_root())
    except ValueError as exc:
        raise BundleGenerationError(
            "missing_release_reference",
            f"{field} requires an explicit release-relative reference because the source path is outside the repository root.",
            field=field,
        ) from exc
    return _validate_release_relative(relative.as_posix(), field, file_path=True)


def _artifact_ref(path: Path, explicit_ref: str | None, field: str) -> dict[str, str]:
    return {
        "path": _reference_for_path(path, explicit_ref, field),
        "sha256": _sha256_file(path),
    }


def _versioned_ref(
    path: Path,
    explicit_ref: str | None,
    source: dict[str, Any],
    field: str,
) -> dict[str, str]:
    ref = _artifact_ref(path, explicit_ref, field)
    ref["contract_version"] = _optional_version(source, field)
    return ref


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise BundleGenerationError(
            "invalid_hash",
            f"{field} must be a lowercase SHA-256 hex digest.",
            field=field,
        )
    return value


def _verify_hash(recorded: Any, actual: str, field: str) -> None:
    recorded_hash = _require_sha(recorded, field)
    if recorded_hash != actual:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            f"{field} does not match the referenced artifact bytes.",
            field=field,
        )


def _slugify_dataset_id(dataset_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", dataset_id.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not DATASET_SLUG_RE.fullmatch(slug):
        raise BundleGenerationError(
            "invalid_dataset_identity",
            "dataset_id cannot produce a valid dataset_slug.",
            field="dataset_id",
        )
    return slug


def _training_identity(record: dict[str, Any]) -> dict[str, str]:
    identity = _require_mapping(record, "training_run_identity")
    dataset_slug = _require_string(identity, "dataset_slug")
    run_id = _require_string(identity, "run_id")
    if not DATASET_SLUG_RE.fullmatch(dataset_slug):
        raise BundleGenerationError(
            "invalid_dataset_identity",
            "training_run_identity.dataset_slug is not valid.",
            field="training_run_identity.dataset_slug",
        )
    if not RUN_ID_RE.fullmatch(run_id):
        raise BundleGenerationError(
            "invalid_training_run_identity",
            "training_run_identity.run_id is not valid.",
            field="training_run_identity.run_id",
        )
    return {"dataset_slug": dataset_slug, "run_id": run_id}


def _resolve_dataset_slug(
    args: argparse.Namespace,
    execution_contract: dict[str, Any],
    training_record: dict[str, Any],
) -> str:
    if args.dataset_slug:
        dataset_slug = args.dataset_slug
    else:
        identity = _training_identity(training_record)
        dataset_slug = identity["dataset_slug"]
    if not DATASET_SLUG_RE.fullmatch(dataset_slug):
        raise BundleGenerationError(
            "invalid_dataset_identity",
            "dataset_slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$.",
            field="dataset_slug",
        )
    dataset_id = execution_contract.get("dataset_id")
    if isinstance(dataset_id, str) and _slugify_dataset_id(dataset_id) != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "execution contract dataset_id does not match the training dataset_slug.",
            field="dataset_id",
        )
    return dataset_slug


def _resolve_release_id(args: argparse.Namespace, metrics: dict[str, Any]) -> str:
    release_id = args.release_id or metrics.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise BundleGenerationError(
            "missing_required_field",
            "release_id must be provided by --release-id or training metrics.",
            field="release_id",
        )
    return release_id


def _resolve_feature_order(
    execution_contract: dict[str, Any],
    training_record: dict[str, Any],
) -> list[str]:
    training_parameters = _require_mapping(training_record, "training_parameters")
    feature_columns = training_parameters.get("feature_columns")
    if not isinstance(feature_columns, list) or not feature_columns:
        raise BundleGenerationError(
            "missing_required_field",
            "training_parameters.feature_columns must be a non-empty array.",
            field="training_parameters.feature_columns",
        )
    if any(not isinstance(feature, str) or not FEATURE_RE.fullmatch(feature) for feature in feature_columns):
        raise BundleGenerationError(
            "invalid_feature_order",
            "all feature names must be valid runtime feature identifiers.",
            field="training_parameters.feature_columns",
        )
    contract_features = execution_contract.get("feature_columns")
    if isinstance(contract_features, list) and contract_features != feature_columns:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "execution contract feature_columns do not match training parameter record feature_columns.",
            field="feature_columns",
        )
    if len(set(feature_columns)) != len(feature_columns):
        raise BundleGenerationError(
            "invalid_feature_order",
            "feature_order must not contain duplicates.",
            field="feature_order",
        )
    return feature_columns


def _resolve_preprocessing(execution_contract: dict[str, Any]) -> dict[str, Any]:
    missing_policy = execution_contract.get("missing_value_policy")
    if not isinstance(missing_policy, dict):
        raise BundleGenerationError(
            "missing_required_field",
            "execution contract missing_value_policy must be present as an object.",
            field="missing_value_policy",
        )
    invalid_policies = {
        key: value
        for key, value in missing_policy.items()
        if not isinstance(value, str) or value not in SUPPORTED_MISSING_POLICIES
    }
    if invalid_policies:
        raise BundleGenerationError(
            "invalid_preprocessing",
            "missing_value_policy contains unsupported values.",
            field="missing_value_policy",
        )

    encoding = execution_contract.get("categorical_encoding_policy")
    if encoding not in SUPPORTED_ENCODINGS:
        raise BundleGenerationError(
            "invalid_preprocessing",
            "categorical_encoding_policy is missing or unsupported.",
            field="categorical_encoding_policy",
        )

    numeric_handling = execution_contract.get("numeric_handling")
    if numeric_handling not in SUPPORTED_NUMERIC_HANDLING:
        raise BundleGenerationError(
            "invalid_preprocessing",
            "numeric_handling is missing or unsupported.",
            field="numeric_handling",
        )

    transformations = execution_contract.get("allowed_transformations")
    if not isinstance(transformations, list) or not transformations:
        raise BundleGenerationError(
            "missing_required_field",
            "allowed_transformations must be a non-empty array.",
            field="allowed_transformations",
        )
    if any(item not in SUPPORTED_TRANSFORMATIONS for item in transformations):
        raise BundleGenerationError(
            "invalid_preprocessing",
            "allowed_transformations contains unsupported values.",
            field="allowed_transformations",
        )

    return {
        "source": "execution_contract_and_training_parameter_record",
        "missing_value_policy": missing_policy,
        "categorical_encoding_policy": encoding,
        "numeric_handling": numeric_handling,
        "transformations": transformations,
    }


def _resolve_runtime_execution(training_record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    training_parameters = _require_mapping(training_record, "training_parameters")
    model_family = _require_string(training_parameters, "model_family")
    if model_family not in SUPPORTED_MODEL_FAMILIES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by inference_bundle.v1.",
            field="training_parameters.model_family",
        )
    serializer = _require_mapping(training_record, "serializer")
    serializer_name = _require_string(serializer, "name")
    if serializer_name != SUPPORTED_SERIALIZATION_FORMAT:
        raise BundleGenerationError(
            "unsupported_serializer",
            "only joblib serialization is supported.",
            field="serializer.name",
        )
    runtime = {
        "serialization_format": SUPPORTED_SERIALIZATION_FORMAT,
        "loader_strategy": SUPPORTED_LOADER_STRATEGY,
        "prediction_interface": SUPPORTED_PREDICTION_INTERFACE,
        "model_family": model_family,
    }
    if args.runtime_adapter_version:
        runtime["runtime_adapter_version"] = args.runtime_adapter_version
    return runtime


def _resolve_result_semantics(
    execution_contract: dict[str, Any],
    training_record: dict[str, Any],
    output_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Project the execution contract's result_semantics into the bundle, or None.

    Returns None (never null-but-present, never invented defaults) when the
    execution contract carries no `result_semantics` at all -- this is the
    historical-compatibility path: the bundle is generated exactly as
    before. When `result_semantics` is present, validates cross-artifact
    consistency against the bundle's own output_schema and the training
    parameter record's governed `binary_classification_evidence`, blocking
    (raising, never writing a partial bundle) on any mismatch.
    """
    result_semantics_source = execution_contract.get("result_semantics")
    if result_semantics_source is None:
        return None
    if not isinstance(result_semantics_source, dict):
        raise BundleGenerationError(
            "invalid_result_semantics",
            "execution contract result_semantics must be an object when present.",
            field="result_semantics",
        )
    if execution_contract.get("contract_version") != "execution_contract.v1":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics is only valid on an execution_contract.v1 contract.",
            field="result_semantics",
        )
    if result_semantics_source.get("problem_type") != "binary_classification":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.problem_type must be exactly binary_classification.",
            field="result_semantics.problem_type",
        )

    positive_class = _require_mapping(result_semantics_source, "positive_class")
    positive_class_id = _require_string(positive_class, "class_id")
    event_label = _require_string(positive_class, "event_label")

    class_labels = output_schema.get("class_labels")
    if not isinstance(class_labels, list) or len(set(class_labels)) != 2:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "output_schema.class_labels must declare exactly two unique values "
            "when result_semantics is present.",
            field="output_schema.class_labels",
        )
    if positive_class_id not in class_labels:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "result_semantics.positive_class.class_id is not one of output_schema.class_labels.",
            field="result_semantics.positive_class.class_id",
        )
    if output_schema.get("probability_output") is not True:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "output_schema.probability_output must be true when result_semantics is present.",
            field="output_schema.probability_output",
        )

    training_parameters = _require_mapping(training_record, "training_parameters")
    model_family = _require_string(training_parameters, "model_family")
    if model_family not in MODEL_FAMILY_DISPLAY_NAMES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by the result_semantics model_descriptor mapping.",
            field="training_parameters.model_family",
        )

    binary_classification_evidence = training_record.get("binary_classification_evidence")
    if not isinstance(binary_classification_evidence, dict):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameter_record.binary_classification_evidence is required when "
            "result_semantics is present.",
            field="binary_classification_evidence",
        )
    if binary_classification_evidence.get("positive_class_id") != positive_class_id:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training evidence positive_class_id does not match "
            "result_semantics.positive_class.class_id.",
            field="binary_classification_evidence.positive_class_id",
        )

    decision = _require_mapping(result_semantics_source, "decision")
    threshold = decision.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.decision.threshold must be a number within [0, 1].",
            field="result_semantics.decision.threshold",
        )

    interpretation = _require_mapping(result_semantics_source, "interpretation")
    bands = interpretation.get("bands")
    if not isinstance(bands, list) or len(bands) != 3:
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.interpretation.bands must contain exactly 3 bands.",
            field="result_semantics.interpretation.bands",
        )

    return {
        "schema_version": BINARY_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": "binary_classification",
        "result_schema_version": BINARY_CLASSIFICATION_RESULT_SCHEMA_VERSION,
        "primary_output": _require_string(result_semantics_source, "primary_output"),
        "positive_class": {
            "class_id": positive_class_id,
            "event_label": event_label,
        },
        "decision": {"threshold": threshold},
        "interpretation": {
            "preset": _require_string(interpretation, "preset"),
            "bands": [dict(band) for band in bands],
        },
        "model_descriptor": {
            "model_family": model_family,
            "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
        },
    }


def _resolve_output_schema(args: argparse.Namespace) -> dict[str, Any]:
    if args.prediction_type not in SUPPORTED_PREDICTION_TYPES:
        raise BundleGenerationError(
            "invalid_output_schema",
            "prediction_type must be one of number, integer, string, or boolean.",
            field="prediction_type",
        )
    output_schema: dict[str, Any] = {
        "prediction_key": "prediction",
        "prediction_type": args.prediction_type,
    }
    if args.class_label:
        output_schema["class_labels"] = args.class_label
    if args.probability_output is not None:
        output_schema["probability_output"] = args.probability_output
    return output_schema


def _verify_source_hashes(
    training_record: dict[str, Any],
    execution_contract_path: Path,
    prepared_dataset_path: Path,
    model_artifact_path: Path,
    metrics_path: Path,
) -> None:
    hashes = _require_mapping(training_record, "hashes")
    execution_sha = _sha256_file(execution_contract_path)
    prepared_sha = _sha256_file(prepared_dataset_path)
    model_sha = _sha256_file(model_artifact_path)
    metrics_sha = _sha256_file(metrics_path)
    _verify_hash(hashes.get("execution_contract_sha256"), execution_sha, "hashes.execution_contract_sha256")
    _verify_hash(hashes.get("prepared_dataset_sha256"), prepared_sha, "hashes.prepared_dataset_sha256")
    _verify_hash(hashes.get("model_artifact_sha256"), model_sha, "hashes.model_artifact_sha256")
    if hashes.get("metrics_sha256") is not None:
        _verify_hash(hashes.get("metrics_sha256"), metrics_sha, "hashes.metrics_sha256")


def _validate_same_training_run(
    training_record: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, str]:
    record_identity = _training_identity(training_record)
    metrics_identity = metrics.get("training_run_identity")
    if isinstance(metrics_identity, dict):
        for key in ("dataset_slug", "run_id"):
            if metrics_identity.get(key) != record_identity[key]:
                raise BundleGenerationError(
                    "stale_or_inconsistent_artifact",
                    "training metrics do not match the training parameter record run identity.",
                    field=f"training_run_identity.{key}",
                )
    return record_identity


def _validate_model_paths(
    training_record: dict[str, Any],
    model_artifact_ref: str,
    training_record_ref: str,
) -> None:
    produced_outputs = _require_mapping(training_record, "produced_outputs")
    recorded_model = produced_outputs.get("serialized_model_path")
    recorded_parameter_record = produced_outputs.get("training_parameter_record_path")
    if isinstance(recorded_model, str) and recorded_model != model_artifact_ref:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "model artifact reference does not match produced_outputs.serialized_model_path.",
            field="produced_outputs.serialized_model_path",
        )
    if isinstance(recorded_parameter_record, str) and recorded_parameter_record != training_record_ref:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "training parameter record reference does not match produced_outputs.training_parameter_record_path.",
            field="produced_outputs.training_parameter_record_path",
        )


def _validate_bundle_schema(bundle: dict[str, Any], schema_path: Path) -> None:
    schema = _load_json_file(schema_path, "inference_bundle_schema_path")
    try:
        import jsonschema
    except ImportError as exc:
        raise BundleGenerationError(
            "schema_validation_unavailable",
            "jsonschema is required to validate the generated inference bundle.",
            field="jsonschema",
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(bundle), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise BundleGenerationError(
            "generated_bundle_schema_invalid",
            f"{path}: {first.message}",
            field=path,
        )


def _build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    execution_contract_path = Path(args.execution_contract)
    runtime_contract_path = Path(args.runtime_contract)
    public_contract_path = Path(args.public_contract)
    prepared_dataset_path = Path(args.prepared_dataset)
    training_record_path = Path(args.training_parameter_record)
    metrics_path = Path(args.training_metrics)
    model_artifact_path = Path(args.model_artifact)
    dataset_context_path = Path(args.dataset_context) if args.dataset_context else prepared_dataset_path
    schema_path = Path(args.inference_bundle_schema)

    execution_contract = _load_json_file(execution_contract_path, "execution_contract_path")
    runtime_contract = _load_json_file(runtime_contract_path, "runtime_contract_path")
    public_contract = _load_json_file(public_contract_path, "public_contract_path")
    training_record = _load_json_file(training_record_path, "training_parameter_record_path")
    metrics = _load_json_file(metrics_path, "training_metrics_path")

    if execution_contract.get("contract_version") != "execution_contract.v1":
        raise BundleGenerationError(
            "invalid_contract_version",
            "execution contract must declare contract_version execution_contract.v1.",
            field="execution_contract.contract_version",
        )

    _verify_source_hashes(
        training_record,
        execution_contract_path,
        prepared_dataset_path,
        model_artifact_path,
        metrics_path,
    )
    training_identity = _validate_same_training_run(training_record, metrics)
    dataset_slug = _resolve_dataset_slug(args, execution_contract, training_record)
    release_id = _resolve_release_id(args, metrics)
    release_package_reference = _validate_release_relative(
        args.release_package_reference,
        "release_package_reference",
    )
    model_package_reference = _validate_release_relative(
        args.model_package_reference,
        "model_package_reference",
        file_path=True,
    )
    generated_at = _utc_now_iso()
    bundle_id = f"{dataset_slug}-inference-bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    execution_contract_ref = _versioned_ref(
        execution_contract_path,
        args.execution_contract_ref,
        execution_contract,
        "execution_contract_ref",
    )
    runtime_contract_ref = _versioned_ref(
        runtime_contract_path,
        args.runtime_contract_ref,
        runtime_contract,
        "runtime_contract_ref",
    )
    public_contract_ref = _versioned_ref(
        public_contract_path,
        args.public_contract_ref,
        public_contract,
        "public_contract_ref",
    )
    training_record_ref = _versioned_ref(
        training_record_path,
        args.training_parameter_record_ref,
        training_record,
        "training_parameter_record_ref",
    )
    metrics_ref = _versioned_ref(
        metrics_path,
        args.training_metrics_ref,
        metrics,
        "training_metrics_ref",
    )
    model_ref = _artifact_ref(model_artifact_path, args.model_artifact_ref, "model_artifact_ref")

    model_selection_ref = None
    if args.model_selection_evidence:
        model_selection_path = Path(args.model_selection_evidence)
        model_selection = _load_json_file(model_selection_path, "model_selection_evidence_path")
        model_selection_ref = _versioned_ref(
            model_selection_path,
            args.model_selection_evidence_ref,
            model_selection,
            "model_selection_evidence_ref",
        )

    _validate_model_paths(training_record, model_ref["path"], training_record_ref["path"])

    bundle: dict[str, Any] = {
        "contract_version": INFERENCE_BUNDLE_VERSION,
        "bundle_identity": {
            "bundle_id": bundle_id,
            "artifact_kind": "inference_bundle",
            "created_at": generated_at,
        },
        "dataset_context": {
            "dataset_slug": dataset_slug,
            "dataset_context_reference": _artifact_ref(
                dataset_context_path,
                args.dataset_context_ref,
                "dataset_context_ref",
            ),
        },
        "release_context": {
            "release_id": release_id,
            "release_package_reference": release_package_reference,
        },
        "contract_references": {
            "execution_contract": execution_contract_ref,
            "runtime_contract": runtime_contract_ref,
            "public_contract": public_contract_ref,
        },
        "prepared_dataset": {
            "prepared_dataset_reference": _artifact_ref(
                prepared_dataset_path,
                args.prepared_dataset_ref,
                "prepared_dataset_ref",
            ),
            "prepared_dataset_sha256": _sha256_file(prepared_dataset_path),
        },
        "training_evidence": {
            "training_run_identity": training_identity,
            "training_parameter_record": training_record_ref,
            "training_metrics": metrics_ref,
            "model_selection_evidence": model_selection_ref,
        },
        "model_artifact": {
            # Release package reference (e.g. "models/model.pkl"), distinct
            # from model_ref["path"] (the source training-run reference used
            # only for build-time provenance verification below).
            "path": model_package_reference,
            "sha256": model_ref["sha256"],
            "source_training_parameter_record_path": training_record_ref["path"],
        },
        "runtime_execution": _resolve_runtime_execution(training_record, args),
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_features_object",
        },
        "feature_order": _resolve_feature_order(execution_contract, training_record),
        "preprocessing": _resolve_preprocessing(execution_contract),
        "output_schema": _resolve_output_schema(args),
        "compatibility_constraints": {
            "requires_contract_versions": {
                "execution_contract": "execution_contract.v1",
                "runtime_contract": runtime_contract_ref["contract_version"],
                "public_contract": public_contract_ref["contract_version"],
            },
            "requires_hash_match": True,
            "requires_feature_order_match": True,
            "requires_release_relative_paths": True,
            "requires_supported_loader": True,
            "requires_supported_serialization": True,
        },
        "boundary_confirmations": {
            "release_relative_paths_only": True,
            "absolute_paths_embedded": False,
            "parent_traversal_embedded": False,
            "notebook_state_embedded": False,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "runtime_payload_validation_duplicated": False,
            "training_internals_required_at_runtime": False,
        },
    }

    if args.description:
        bundle["bundle_identity"]["description"] = args.description
    if args.candidate_id:
        bundle["release_context"]["candidate_id"] = args.candidate_id
    if args.minimum_runtime_adapter_version:
        bundle["compatibility_constraints"]["minimum_runtime_adapter_version"] = (
            args.minimum_runtime_adapter_version
        )

    result_semantics = _resolve_result_semantics(
        execution_contract, training_record, bundle["output_schema"]
    )
    if result_semantics is not None:
        bundle["result_semantics"] = result_semantics

    _validate_bundle_schema(bundle, schema_path)
    return bundle


def _write_bundle(bundle: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# Governed inference-bundle materialization boundary (Project Spec S0033).
#
# Bridges a governed training run materialization result
# (`pipeline.training.materialize_training_run_from_prepared_metadata`) and a
# `prepared-data-metadata.v1` artifact to this module's own `_build_bundle`
# generation boundary. The governed training run is only ever resolved from
# the caller-supplied materialization result's own `status`/`training_result`
# fields -- never a hardcoded `train-pending` placeholder, a glob over
# `pipeline/training-runs/`, or a notebook-held DataFrame. The prepared
# dataset reference is only ever resolved via the same
# `_prepared_dataset_metadata_blocking_reasons` boundary
# `pipeline.training` itself uses, so it always matches the exact prepared
# dataset the training run was produced from.
GOVERNED_INFERENCE_BUNDLE_RELEASE_PACKAGE_REFERENCE = "predictions/bundle.json"


def _derive_provisional_release_id(run_id: str) -> str:
    """Derive a schema-safe, deterministic placeholder ``release_id``.

    ``inference-bundle.schema.json`` requires ``release_context.release_id``
    to match ``release-YYYYMMDD-NNN``, but this spec must not assemble a real
    release candidate, so no real release_id has been allocated yet. This
    derives a value tied only to the governed training run's own date --
    never a milestone tag, notebook counter, or reused fixture value -- with
    a fixed ``-001`` sequence; a later, separately authorized
    release-candidate assembly is free to supersede it with a real allocated
    release_id.
    """
    match = RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise BundleGenerationError(
            "invalid_training_run_identity",
            f"training run id does not match train-{{timestamp}}Z: {run_id}",
            field="training_run_identity.run_id",
        )
    date_part = run_id[len("train-"):len("train-") + 8]
    return f"release-{date_part}-001"


def materialize_governed_inference_bundle(
    *,
    training_run_materialization_result: dict[str, Any],
    execution_contract_path: str | Path,
    runtime_contract_path: str | Path,
    public_contract_path: str | Path,
    dataset_context_path: str | Path,
    prepared_data_metadata_path: str | Path,
    output_path: str | Path,
    prediction_type: str,
    repo_root: str | Path | None = None,
    dataset_slug: str | None = None,
    class_labels: list[str] | None = None,
    probability_output: bool | None = None,
    execution_contract_ref: str | None = None,
    runtime_contract_ref: str | None = None,
    public_contract_ref: str | None = None,
    dataset_context_ref: str | None = None,
    inference_bundle_schema_path: str | Path | None = None,
    model_package_reference: str | None = None,
) -> dict[str, Any]:
    """Materialize ``inference_bundle.v1`` from a governed training run.

    Only proceeds when ``training_run_materialization_result["status"] ==
    "trained"`` (the same governed
    ``materialize_training_run_from_prepared_metadata`` result the calling
    notebook already computed) and when the prepared-data-metadata.v1
    artifact's own ``prepared_candidate`` is produced and training-ready.
    Any other state returns a ``status: "blocked"`` result with
    ``blocking_reasons`` instead of generating a bundle. Never accepts
    hidden notebook memory -- only explicit path references and the
    already-computed governed result object.
    """
    resolved_repo_root = Path(repo_root or _repo_root()).expanduser().resolve()

    if (
        not isinstance(training_run_materialization_result, dict)
        or training_run_materialization_result.get("status") != "trained"
    ):
        status = (
            training_run_materialization_result.get("status")
            if isinstance(training_run_materialization_result, dict)
            else "malformed_training_run_materialization_result"
        )
        return {
            "status": "blocked",
            "blocking_reasons": [
                f"training_run_materialization_result.status is not 'trained': {status}.",
            ],
        }

    training_result = training_run_materialization_result.get("training_result")
    if not isinstance(training_result, dict):
        return {
            "status": "blocked",
            "blocking_reasons": [
                "training_run_materialization_result.training_result is missing.",
            ],
        }

    metadata_path = Path(prepared_data_metadata_path)
    metadata = _load_json_file(metadata_path, "prepared_data_metadata_path")
    blocking_reasons, prepared_reference = _prepared_dataset_metadata_blocking_reasons(metadata)
    if blocking_reasons:
        return {"status": "blocked", "blocking_reasons": blocking_reasons}

    run_id = Path(training_result["output_directory"]).name
    try:
        provisional_release_id = _derive_provisional_release_id(run_id)
    except BundleGenerationError as exc:
        return {"status": "blocked", "blocking_reasons": [str(exc)]}

    model_selection_evidence_path = training_result.get("model_selection_evidence_path")

    namespace = argparse.Namespace(
        execution_contract=str(Path(execution_contract_path)),
        runtime_contract=str(Path(runtime_contract_path)),
        public_contract=str(Path(public_contract_path)),
        prepared_dataset=str(resolved_repo_root / prepared_reference),
        training_parameter_record=str(
            resolved_repo_root / training_result["training_parameter_record_path"]
        ),
        training_metrics=str(resolved_repo_root / training_result["metrics_path"]),
        model_artifact=str(resolved_repo_root / training_result["serialized_model_path"]),
        output=str(Path(output_path)),
        release_package_reference=GOVERNED_INFERENCE_BUNDLE_RELEASE_PACKAGE_REFERENCE,
        model_package_reference=model_package_reference or DEFAULT_MODEL_PACKAGE_REFERENCE,
        prediction_type=prediction_type,
        release_id=provisional_release_id,
        dataset_slug=dataset_slug,
        dataset_context=str(Path(dataset_context_path)),
        model_selection_evidence=(
            str(resolved_repo_root / model_selection_evidence_path)
            if model_selection_evidence_path
            else None
        ),
        candidate_id=None,
        description=None,
        runtime_adapter_version=None,
        minimum_runtime_adapter_version=None,
        class_label=list(class_labels) if class_labels else None,
        probability_output=probability_output,
        execution_contract_ref=execution_contract_ref,
        runtime_contract_ref=runtime_contract_ref,
        public_contract_ref=public_contract_ref,
        prepared_dataset_ref=prepared_reference,
        dataset_context_ref=dataset_context_ref,
        training_parameter_record_ref=training_result["training_parameter_record_path"],
        training_metrics_ref=training_result["metrics_path"],
        model_artifact_ref=training_result["serialized_model_path"],
        model_selection_evidence_ref=model_selection_evidence_path,
        inference_bundle_schema=(
            str(Path(inference_bundle_schema_path))
            if inference_bundle_schema_path
            else str(_repo_root() / INFERENCE_BUNDLE_SCHEMA)
        ),
    )

    try:
        bundle = _build_bundle(namespace)
        _write_bundle(bundle, Path(output_path))
    except BundleGenerationError as exc:
        return {
            "status": "blocked",
            "blocking_reasons": [str(exc)],
            "error": exc.to_dict()["error"],
        }

    return {
        "status": "generated",
        "output_path": str(output_path),
        "bundle_id": bundle["bundle_identity"]["bundle_id"],
        "training_run_id": run_id,
        "provisional_release_id": provisional_release_id,
        "prepared_dataset_reference": prepared_reference,
    }


def _parse_bool(value: str) -> bool:
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a schema-valid inference bundle from governed artifacts.",
    )
    parser.add_argument("--execution-contract", required=True)
    parser.add_argument("--runtime-contract", required=True)
    parser.add_argument("--public-contract", required=True)
    parser.add_argument("--prepared-dataset", required=True)
    parser.add_argument("--training-parameter-record", required=True)
    parser.add_argument("--training-metrics", required=True)
    parser.add_argument("--model-artifact", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-package-reference", required=True)
    parser.add_argument(
        "--model-package-reference",
        default=DEFAULT_MODEL_PACKAGE_REFERENCE,
        help="Release-relative package reference for the model artifact (default: models/model.pkl).",
    )
    parser.add_argument("--prediction-type", required=True)

    parser.add_argument("--release-id")
    parser.add_argument("--dataset-slug")
    parser.add_argument("--dataset-context")
    parser.add_argument("--model-selection-evidence")
    parser.add_argument("--candidate-id")
    parser.add_argument("--description")
    parser.add_argument("--runtime-adapter-version")
    parser.add_argument("--minimum-runtime-adapter-version")
    parser.add_argument("--class-label", action="append")
    parser.add_argument("--probability-output", type=_parse_bool)

    parser.add_argument("--execution-contract-ref")
    parser.add_argument("--runtime-contract-ref")
    parser.add_argument("--public-contract-ref")
    parser.add_argument("--prepared-dataset-ref")
    parser.add_argument("--dataset-context-ref")
    parser.add_argument("--training-parameter-record-ref")
    parser.add_argument("--training-metrics-ref")
    parser.add_argument("--model-artifact-ref")
    parser.add_argument("--model-selection-evidence-ref")
    parser.add_argument(
        "--inference-bundle-schema",
        default=str(_repo_root() / INFERENCE_BUNDLE_SCHEMA),
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        bundle = _build_bundle(args)
        _write_bundle(bundle, Path(args.output))
    except BundleGenerationError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "generated",
        "output_path": args.output,
        "bundle_id": bundle["bundle_identity"]["bundle_id"],
        "schema": INFERENCE_BUNDLE_SCHEMA,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
