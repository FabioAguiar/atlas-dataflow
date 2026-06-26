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


INFERENCE_BUNDLE_SCHEMA = "contracts/inference-bundle.schema.json"
INFERENCE_BUNDLE_VERSION = "inference_bundle.v1"
SUPPORTED_SERIALIZATION_FORMAT = "joblib"
SUPPORTED_LOADER_STRATEGY = "joblib_sklearn_predict"
SUPPORTED_PREDICTION_INTERFACE = "predict"
SUPPORTED_MODEL_FAMILIES = frozenset({
    "logistic_regression",
    "gradient_boosting",
    "random_forest",
})
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
    if not isinstance(missing_policy, dict) or not missing_policy:
        raise BundleGenerationError(
            "missing_required_field",
            "execution contract missing_value_policy must be a non-empty object.",
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
            "path": model_ref["path"],
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

    _validate_bundle_schema(bundle, schema_path)
    return bundle


def _write_bundle(bundle: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
