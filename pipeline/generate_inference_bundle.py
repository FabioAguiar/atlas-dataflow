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
# Project Spec S0245: strict, disjoint Atlas-native univariate-forecasting
# inference-bundle branch. Never routed through the v1 tabular builder --
# see _build_forecasting_bundle and materialize_governed_inference_bundle's
# explicit execution_contract.contract_version/problem_type dispatch.
INFERENCE_BUNDLE_VERSION_V2 = "inference_bundle.v2"
FORECASTING_EXECUTION_CONTRACT_VERSION = "execution_contract.v2"
FORECASTING_PROBLEM_TYPE = "univariate_forecasting"
FORECASTING_TRAINING_PARAMETER_RECORD_VERSION = "training-parameter-record.v4"
FORECASTING_TRAINING_METRICS_VERSION = "training-metrics.v4"
FORECASTING_PREPARATION_RECIPE_VERSION = "candidate-preparation-recipe.v2"
FORECASTING_MODEL_FAMILY = "deterministic_seasonal_trend_ols"
FORECASTING_TRAINING_POLICY_SCHEMA_VERSION = "univariate-forecasting-training-policy.v1"
FORECASTING_RESULT_SEMANTICS_SCHEMA_VERSION = "univariate-forecasting-result-semantics.v1"
FORECASTING_RESULT_SCHEMA_VERSION = "univariate-forecasting-result.v1"
FORECASTING_LOADER_STRATEGY = "joblib_sklearn_forecasting_adapter"
FORECASTING_PREDICTION_INTERFACE = "forecast_series"
DEFAULT_MODEL_PACKAGE_REFERENCE = "models/model.pkl"
SUPPORTED_SERIALIZATION_FORMAT = "joblib"
SUPPORTED_LOADER_STRATEGY = "joblib_sklearn_predict"
SUPPORTED_PREDICTION_INTERFACE = "predict"
SUPPORTED_MODEL_FAMILIES = frozenset({
    "logistic_regression",
    "gradient_boosting",
    "random_forest",
    # Project Spec S0216: internal Atlas-native fixed-configuration
    # multiclass training now fits hist_gradient_boosting (see
    # pipeline/training.py's NATIVE_MULTICLASS_* fixed-configuration
    # pipeline) -- runtime_execution.model_family already accepted this
    # value at the schema level (contracts/inference-bundle.schema.json,
    # added for the external path by Project Spec S0209).
    "hist_gradient_boosting",
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
    # Project Spec S0191: originally the only external public-result model
    # family (training-parameter-record.external-fitted-model.v1 restricts
    # model_family to exactly this one enum value). Project Spec S0232
    # additionally reaches this entry from internal Atlas-native
    # continuous-regression bundle generation (CONTINUOUS_REGRESSION_MODEL_FAMILIES
    # above); binary/multiclass internal training records still cannot reach
    # it via SUPPORTED_MODEL_FAMILIES.
    "hist_gradient_boosting": "HistGradientBoosting",
    # Project Spec S0208/S0209: the fourth bounded external multiclass (v2)
    # estimator family -- an internal training record can never reach this
    # entry either, for the same reason as hist_gradient_boosting above.
    "decision_tree": "Decision Tree",
    # Project Spec S0245: the sole inference_bundle.v2 forecasting model
    # family. Deterministic projection only -- never editable profile copy.
    "deterministic_seasonal_trend_ols": "Deterministic Seasonal-Trend OLS",
}
# Project Spec S0191: bounded governed pairing of external public-result
# model_family to its required estimator_identity, mirroring
# training-parameter-record.schema.json's external profile enums. Never
# open-ended -- a family not present here is never accepted.
_EXTERNAL_GOVERNED_ESTIMATOR_IDENTITIES: dict[str, dict[str, str]] = {
    "hist_gradient_boosting": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
}
BINARY_RESULT_SEMANTICS_SCHEMA_VERSION = "binary-result-semantics.v1"
BINARY_CLASSIFICATION_RESULT_SCHEMA_VERSION = "binary-classification-result.v1"
# Project Spec S0225/S0232: Atlas-native fixed-configuration continuous-regression
# bundle generation. Bounded to exactly the S0224 v3 regression families plus
# the S0231 native hist_gradient_boosting regression family -- never widened
# just because another classification/external family already exists
# elsewhere in this module.
CONTINUOUS_REGRESSION_MODEL_FAMILIES = frozenset({
    "gradient_boosting",
    "random_forest",
    "hist_gradient_boosting",
})
CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION = "continuous-regression-result-semantics.v1"
CONTINUOUS_REGRESSION_RESULT_SCHEMA_VERSION = "continuous-regression-result.v1"
TRAINING_PARAMETER_RECORD_V3_SCHEMA_VERSION = "training-parameter-record.v3"
TRAINING_METRICS_V3_SCHEMA_VERSION = "training-metrics.v3"
SUPPORTED_PREDICTION_TYPES = frozenset({"number", "integer", "string", "boolean"})
SUPPORTED_ENCODINGS = frozenset({"onehot", "ordinal", "target_encode", "binary"})
SUPPORTED_NUMERIC_HANDLING = frozenset({"standardize", "normalize", "passthrough"})
SUPPORTED_TRANSFORMATIONS = frozenset({"log1p", "sqrt", "clip", "passthrough"})
SUPPORTED_MISSING_POLICIES = frozenset({"mean", "median", "mode", "constant", "drop_row"})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DATASET_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RELEASE_ID_RE = re.compile(r"^release-[0-9]{8}-[0-9]{3}$")
RUN_ID_RE = re.compile(r"^train-[0-9]{8}T[0-9]{6}Z$")
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
    if any(not isinstance(feature, str) or not feature for feature in feature_columns):
        raise BundleGenerationError(
            "invalid_feature_order",
            "all feature names must be non-empty strings.",
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


def _resolve_internal_result_semantics_model_descriptor(
    training_record: dict[str, Any], positive_class_id: str
) -> dict[str, str]:
    """training-parameter-record.v1 (internal) model_descriptor resolution.

    Unchanged from the pre-S0191 behavior: validates
    training_parameters.model_family and
    binary_classification_evidence.positive_class_id.
    """
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
    return {
        "model_family": model_family,
        "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
    }


_INTERNAL_BINARY_V1_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION = "training-parameter-record.v1"
_INTERNAL_BINARY_V5_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION = "training-parameter-record.v5"


def _resolve_internal_binary_v5_result_semantics_model_descriptor(
    training_record: dict[str, Any],
    positive_class_id: str,
    class_labels: list[str],
    effective_threshold: float,
) -> dict[str, str]:
    """training-parameter-record.v5 (internal Atlas-native binary
    fixed-configuration) model_descriptor resolution (Project Spec S0259).

    Never trusts legacy binary_classification_evidence -- that field does
    not exist on the v5 profile. Instead cross-checks the record's own
    governed classification_evidence: positive class, decision threshold,
    ordered class labels against output_schema.class_labels, and model
    family, all fail-closed on any mismatch. Never fabricates
    binary_classification_evidence for a v5 record.
    """
    training_parameters = _require_mapping(training_record, "training_parameters")
    model_family = _require_string(training_parameters, "model_family")
    if model_family != "hist_gradient_boosting":
        raise BundleGenerationError(
            "unsupported_model_family",
            "training-parameter-record.v5 model_family must be hist_gradient_boosting.",
            field="training_parameters.model_family",
        )

    classification_evidence = training_record.get("classification_evidence")
    if not isinstance(classification_evidence, dict):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameter_record.classification_evidence is required when "
            "result_semantics is present on a training-parameter-record.v5 record.",
            field="classification_evidence",
        )
    if classification_evidence.get("problem_type") != "binary_classification":
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "classification_evidence.problem_type must be exactly binary_classification.",
            field="classification_evidence.problem_type",
        )
    if classification_evidence.get("result_semantics_schema_version") != BINARY_RESULT_SEMANTICS_SCHEMA_VERSION:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "classification_evidence.result_semantics_schema_version must equal "
            f"{BINARY_RESULT_SEMANTICS_SCHEMA_VERSION!r}.",
            field="classification_evidence.result_semantics_schema_version",
        )
    if classification_evidence.get("positive_class_id") != positive_class_id:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training evidence classification_evidence.positive_class_id does not match "
            "result_semantics.positive_class.class_id.",
            field="classification_evidence.positive_class_id",
        )
    threshold_value = classification_evidence.get("threshold")
    if (
        isinstance(threshold_value, bool)
        or not isinstance(threshold_value, (int, float))
        or threshold_value != effective_threshold
    ):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training evidence classification_evidence.threshold does not match "
            "result_semantics.decision.threshold.",
            field="classification_evidence.threshold",
        )
    ordered_class_labels = classification_evidence.get("ordered_class_labels")
    if not isinstance(ordered_class_labels, list) or sorted(ordered_class_labels) != sorted(class_labels):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "classification_evidence.ordered_class_labels does not agree with "
            "output_schema.class_labels.",
            field="classification_evidence.ordered_class_labels",
        )
    positive_class_probability_index = classification_evidence.get("positive_class_probability_index")
    if (
        not isinstance(positive_class_probability_index, int)
        or isinstance(positive_class_probability_index, bool)
        or positive_class_probability_index not in (0, 1)
        or ordered_class_labels[positive_class_probability_index] != positive_class_id
    ):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "classification_evidence.positive_class_probability_index does not resolve to "
            "positive_class_id within ordered_class_labels.",
            field="classification_evidence.positive_class_probability_index",
        )

    return {
        "model_family": model_family,
        "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
    }


def _resolve_external_result_semantics_model_descriptor(
    training_record: dict[str, Any],
    model_selection: dict[str, Any] | None,
    positive_class_id: str,
) -> dict[str, str]:
    """training-parameter-record.external-fitted-model.v1 (external)
    model_descriptor resolution (Project Spec S0191).

    Never trusts training_parameters/binary_classification_evidence -- those
    fields do not exist on the external profile and are never fabricated.
    Instead validates the actual external fields: origin, model_family,
    selected_model_id, and estimator_identity, fail-closed on any mismatch.
    """
    if training_record.get("origin") != EXTERNAL_MODEL_SOURCE_MODE:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            f"training_parameter_record.origin must be {EXTERNAL_MODEL_SOURCE_MODE!r} "
            "when result_semantics is present on an external training record.",
            field="origin",
        )

    model_family = _require_string(training_record, "model_family")
    if model_family not in MODEL_FAMILY_DISPLAY_NAMES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by the result_semantics model_descriptor mapping.",
            field="model_family",
        )

    selected_model_id = _require_string(training_record, "selected_model_id")

    estimator_identity = _require_mapping(training_record, "estimator_identity")
    estimator_identity_value = {
        "library": _require_string(estimator_identity, "library"),
        "class_name": _require_string(estimator_identity, "class_name"),
    }
    if estimator_identity_value != _EXTERNAL_GOVERNED_ESTIMATOR_IDENTITIES.get(model_family):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "estimator_identity is not compatible with the governed external model_family.",
            field="estimator_identity",
        )

    if isinstance(model_selection, dict):
        selected_candidate_ref = model_selection.get("selected_candidate")
        candidate_id = (
            selected_candidate_ref.get("candidate_id")
            if isinstance(selected_candidate_ref, dict)
            else None
        )
        candidates = model_selection.get("candidates")
        matching_candidates = (
            [
                candidate
                for candidate in candidates
                if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id
            ]
            if isinstance(candidates, list)
            else []
        )
        selected_candidate_entry = matching_candidates[0] if len(matching_candidates) == 1 else None
        if (
            candidate_id != selected_model_id
            or selected_candidate_entry is None
            or selected_candidate_entry.get("model_family") != model_family
            or selected_candidate_entry.get("estimator_identity") != estimator_identity_value
        ):
            raise BundleGenerationError(
                "result_semantics_cross_artifact_mismatch",
                "selected_model_id is not consistent with model_family in "
                "model_selection_evidence's selected candidate.",
                field="selected_model_id",
            )

    if training_record.get("positive_class_id") != positive_class_id:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training evidence positive_class_id does not match "
            "result_semantics.positive_class.class_id.",
            field="positive_class_id",
        )

    return {
        "model_family": model_family,
        "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
    }


_INTERNAL_MULTICLASS_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION = "training-parameter-record.v2"


def _resolve_internal_multiclass_model_descriptor(
    training_record: dict[str, Any], ordered_class_ids: list[str]
) -> dict[str, str]:
    """training-parameter-record.v2 (internal Atlas-native multiclass)
    model_descriptor resolution (Project Spec S0216).

    Never trusts a positive-class concept -- multiclass has none. Instead
    cross-checks the training evidence's own governed
    classification_evidence.ordered_class_ids against the bundle's
    result_semantics.classes order, so a reversed/mismatched class order
    fails closed rather than being silently accepted.
    """
    if training_record.get("schema_version") != _INTERNAL_MULTICLASS_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "internal multiclass result_semantics requires a "
            f"{_INTERNAL_MULTICLASS_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION!r} training parameter record.",
            field="schema_version",
        )
    training_parameters = _require_mapping(training_record, "training_parameters")
    model_family = _require_string(training_parameters, "model_family")
    if model_family not in MODEL_FAMILY_DISPLAY_NAMES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by the result_semantics model_descriptor mapping.",
            field="training_parameters.model_family",
        )
    classification_evidence = training_record.get("classification_evidence")
    evidence_class_ids = (
        classification_evidence.get("ordered_class_ids")
        if isinstance(classification_evidence, dict)
        else None
    )
    if evidence_class_ids != ordered_class_ids:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training evidence classification_evidence.ordered_class_ids does not match "
            "result_semantics.classes order.",
            field="classification_evidence.ordered_class_ids",
        )
    return {
        "model_family": model_family,
        "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
    }


def _resolve_internal_multiclass_result_semantics(
    training_record: dict[str, Any],
    output_schema: dict[str, Any],
    result_semantics_source: dict[str, Any],
) -> dict[str, Any]:
    """Project an internal (Atlas-native) multiclass execution contract
    result_semantics into the bundle (Project Spec S0216). Mirrors
    `_resolve_multiclass_result_semantics`'s external validation
    discipline, but is unconditionally sourced from the training parameter
    record's own governed classification_evidence rather than a validated
    external materialization result.
    """
    if result_semantics_source.get("schema_version") != MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION:
        raise BundleGenerationError(
            "invalid_result_semantics",
            f"result_semantics.schema_version must equal {MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION!r}.",
            field="result_semantics.schema_version",
        )
    if result_semantics_source.get("primary_output") != "predicted_class":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.primary_output must be exactly predicted_class.",
            field="result_semantics.primary_output",
        )
    if result_semantics_source.get("probability_output") != "class_probabilities":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.probability_output must be exactly class_probabilities.",
            field="result_semantics.probability_output",
        )
    decision = _require_mapping(result_semantics_source, "decision")
    if decision.get("strategy") != "argmax":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.decision.strategy must be exactly argmax.",
            field="result_semantics.decision.strategy",
        )

    classes = result_semantics_source.get("classes")
    if not isinstance(classes, list) or len(classes) < 3:
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.classes must contain at least 3 ordered class entries.",
            field="result_semantics.classes",
        )
    ordered_class_ids: list[str] = []
    for entry in classes:
        if not isinstance(entry, dict):
            raise BundleGenerationError(
                "invalid_result_semantics",
                "result_semantics.classes entries must be objects.",
                field="result_semantics.classes",
            )
        ordered_class_ids.append(_require_string(entry, "class_id"))

    class_labels = output_schema.get("class_labels")
    if not isinstance(class_labels, list) or class_labels != ordered_class_ids:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "output_schema.class_labels must equal result_semantics.classes order exactly.",
            field="output_schema.class_labels",
        )
    if output_schema.get("probability_output") is not True:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "output_schema.probability_output must be true when result_semantics is present.",
            field="output_schema.probability_output",
        )

    model_descriptor = _resolve_internal_multiclass_model_descriptor(training_record, ordered_class_ids)

    return {
        "schema_version": MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": "multiclass_classification",
        "result_schema_version": MULTICLASS_CLASSIFICATION_RESULT_SCHEMA_VERSION,
        "classes": [dict(entry) for entry in classes],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
        "model_descriptor": model_descriptor,
    }


def _validate_continuous_regression_evidence_v3(evidence: Any, field_prefix: str) -> None:
    """Cross-check a training-parameter-record.v3 or training-metrics.v3
    `regression_evidence` block (Project Spec S0224) before it is trusted.

    Never invents defaults -- a missing block, or any field disagreeing
    with the governed continuous-regression identity, blocks before a
    bundle is written.
    """
    if not isinstance(evidence, dict):
        raise BundleGenerationError(
            "missing_required_field",
            f"{field_prefix} must be present as an object.",
            field=field_prefix,
        )
    if evidence.get("problem_type") != "continuous_regression":
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            f"{field_prefix}.problem_type must be exactly continuous_regression.",
            field=f"{field_prefix}.problem_type",
        )
    if evidence.get("result_semantics_schema_version") != CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            f"{field_prefix}.result_semantics_schema_version must equal "
            f"{CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION!r}.",
            field=f"{field_prefix}.result_semantics_schema_version",
        )
    if evidence.get("output_value_kind") != "continuous_numeric":
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            f"{field_prefix}.output_value_kind must be exactly continuous_numeric.",
            field=f"{field_prefix}.output_value_kind",
        )


def _resolve_internal_continuous_regression_model_descriptor(
    training_record: dict[str, Any],
) -> dict[str, str]:
    """training-parameter-record.v3 (Project Spec S0224, Atlas-native
    fixed-configuration continuous regression) model_descriptor resolution.

    Never trusts a positive-class or ordered-class concept -- continuous
    regression has neither. Bounded to exactly the S0224 fixed-configuration
    families and requires the fixed-finalization protocol evidence (no
    model selection ever occurred) before the model_family is trusted.
    """
    training_parameters = _require_mapping(training_record, "training_parameters")
    model_family = _require_string(training_parameters, "model_family")
    if model_family not in CONTINUOUS_REGRESSION_MODEL_FAMILIES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by the continuous-regression "
            "result_semantics model_descriptor mapping.",
            field="training_parameters.model_family",
        )
    if training_parameters.get("selection_mode") != "fixed_configuration":
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameters.selection_mode must be fixed_configuration "
            "for a continuous-regression bundle.",
            field="training_parameters.selection_mode",
        )
    if training_parameters.get("model_selection_performed") is not False:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameters.model_selection_performed must be false "
            "for a continuous-regression bundle.",
            field="training_parameters.model_selection_performed",
        )
    return {
        "model_family": model_family,
        "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
    }


def _resolve_internal_continuous_regression_result_semantics(
    training_record: dict[str, Any],
    metrics: dict[str, Any] | None,
    output_schema: dict[str, Any],
    result_semantics_source: dict[str, Any],
) -> dict[str, Any]:
    """Project an internal (Atlas-native) continuous-regression execution
    contract result_semantics into the bundle (Project Spec S0225). Mirrors
    `_resolve_internal_multiclass_result_semantics`'s validation discipline,
    but is sourced from the training-parameter-record.v3 /
    training-metrics.v3 pair (Project Spec S0224) rather than a governed
    classification_evidence claim -- there is no positive class, no ordered
    class set, and no probability output for continuous regression.
    """
    if result_semantics_source.get("schema_version") != CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION:
        raise BundleGenerationError(
            "invalid_result_semantics",
            f"result_semantics.schema_version must equal "
            f"{CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION!r}.",
            field="result_semantics.schema_version",
        )
    if result_semantics_source.get("primary_output") != "predicted_value":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.primary_output must be exactly predicted_value.",
            field="result_semantics.primary_output",
        )
    if result_semantics_source.get("output_value_kind") != "continuous_numeric":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.output_value_kind must be exactly continuous_numeric.",
            field="result_semantics.output_value_kind",
        )

    if training_record.get("schema_version") != TRAINING_PARAMETER_RECORD_V3_SCHEMA_VERSION:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "internal continuous-regression result_semantics requires a "
            f"{TRAINING_PARAMETER_RECORD_V3_SCHEMA_VERSION!r} training parameter record.",
            field="schema_version",
        )
    if training_record.get("problem_type") != "continuous_regression":
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameter_record.problem_type must be exactly continuous_regression.",
            field="problem_type",
        )
    _validate_continuous_regression_evidence_v3(
        training_record.get("regression_evidence"), "training_parameter_record.regression_evidence"
    )

    if not isinstance(metrics, dict) or metrics.get("schema_version") != TRAINING_METRICS_V3_SCHEMA_VERSION:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "internal continuous-regression result_semantics requires a "
            f"{TRAINING_METRICS_V3_SCHEMA_VERSION!r} training metrics artifact.",
            field="training_metrics.schema_version",
        )
    _validate_continuous_regression_evidence_v3(
        metrics.get("regression_evidence"), "training_metrics.regression_evidence"
    )

    if output_schema.get("prediction_type") != "number":
        raise BundleGenerationError(
            "invalid_output_schema",
            "output_schema.prediction_type must be exactly number for continuous regression.",
            field="output_schema.prediction_type",
        )
    if "class_labels" in output_schema:
        raise BundleGenerationError(
            "invalid_output_schema",
            "output_schema.class_labels must be absent for continuous regression.",
            field="output_schema.class_labels",
        )
    if "probability_output" in output_schema:
        raise BundleGenerationError(
            "invalid_output_schema",
            "output_schema.probability_output must be absent for continuous regression.",
            field="output_schema.probability_output",
        )

    model_descriptor = _resolve_internal_continuous_regression_model_descriptor(training_record)

    return {
        "schema_version": CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": "continuous_regression",
        "result_schema_version": CONTINUOUS_REGRESSION_RESULT_SCHEMA_VERSION,
        "primary_output": "predicted_value",
        "output_value_kind": "continuous_numeric",
        "model_descriptor": model_descriptor,
    }


def _resolve_result_semantics(
    execution_contract: dict[str, Any],
    training_record: dict[str, Any],
    output_schema: dict[str, Any],
    *,
    model_selection: dict[str, Any] | None = None,
    decision_threshold_override: Any = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Project the execution contract's result_semantics into the bundle, or None.

    Returns None (never null-but-present, never invented defaults) when the
    execution contract carries no `result_semantics` at all -- this is the
    historical-compatibility path: the bundle is generated exactly as
    before. When `result_semantics` is present, validates cross-artifact
    consistency against the bundle's own output_schema and the training
    parameter record's governed identity fields, blocking (raising, never
    writing a partial bundle) on any mismatch.

    Supports exactly the three known binary training-parameter-record
    profiles, dispatched on `training_record["schema_version"]` via an
    explicit closed dispatch (Project Spec S0259) -- an unrecognized
    version fails closed rather than being silently treated as v1:
    `training-parameter-record.v1` (internal, Project Spec S0191,
    unchanged validation against `training_parameters.model_family` /
    `binary_classification_evidence.positive_class_id`),
    `training-parameter-record.v5` (internal, Project Spec S0259, Atlas-
    native fixed-configuration binary training, validated against its own
    governed `classification_evidence` -- see
    `_resolve_internal_binary_v5_result_semantics_model_descriptor`), and
    `training-parameter-record.external-fitted-model.v1` (external,
    validated against its own governed identity fields -- see
    `_resolve_external_result_semantics_model_descriptor`).

    `model_selection` is only consulted for the external profile, as an
    extra fail-closed cross-check that `selected_model_id` matches the
    governed selected candidate; ignored for the internal profile.

    `decision_threshold_override`, when not None, replaces the execution
    contract's own `result_semantics.decision.threshold` value in the
    returned bundle -- used only by the external path (Project Spec S0191
    Desired Change B) to synchronize the projected threshold with the
    already-validated external threshold evidence instead of treating the
    execution contract's older threshold as runtime truth. The execution
    contract's threshold is still structurally validated either way.
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

    # Project Spec S0216: an internal (Atlas-native) multiclass bundle
    # dispatches to its own dedicated resolver -- never the binary path
    # below, and never the external multiclass path
    # (_resolve_multiclass_result_semantics), which is reserved for a
    # validated_external_fitted_model materialization result shape this
    # function never receives.
    if result_semantics_source.get("problem_type") == "multiclass_classification":
        return _resolve_internal_multiclass_result_semantics(
            training_record, output_schema, result_semantics_source
        )

    # Project Spec S0225: an internal (Atlas-native) continuous-regression
    # bundle dispatches to its own dedicated resolver, sourced from a
    # training-parameter-record.v3 / training-metrics.v3 pair. There is no
    # external fitted-model continuous-regression path -- `metrics` is only
    # ever supplied by the internal build path, so a caller reaching here
    # without it (i.e. the external path) fails closed inside the resolver
    # rather than fabricating regression evidence.
    if result_semantics_source.get("problem_type") == "continuous_regression":
        return _resolve_internal_continuous_regression_result_semantics(
            training_record, metrics, output_schema, result_semantics_source
        )

    # Explicit closed dispatch (Project Spec S0225): any problem_type other
    # than the three governed families above -- including a future
    # count_regression, multi_output_regression, forecasting, survival,
    # anomaly, or ranking value -- fails closed here rather than being
    # silently accepted or misrouted into the binary path below.
    if result_semantics_source.get("problem_type") != "binary_classification":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.problem_type must be exactly binary_classification, "
            "multiclass_classification, or continuous_regression.",
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

    decision = _require_mapping(result_semantics_source, "decision")
    threshold = decision.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.decision.threshold must be a number within [0, 1].",
            field="result_semantics.decision.threshold",
        )

    effective_threshold = threshold
    if decision_threshold_override is not None:
        if (
            isinstance(decision_threshold_override, bool)
            or not isinstance(decision_threshold_override, (int, float))
            or not (0.0 <= decision_threshold_override <= 1.0)
        ):
            raise BundleGenerationError(
                "invalid_result_semantics",
                "external_model_evidence.educational_threshold.value must be a number "
                "within [0, 1] to synchronize result_semantics.decision.threshold.",
                field="external_model_evidence.educational_threshold.value",
            )
        effective_threshold = decision_threshold_override

    # Project Spec S0259: explicit closed dispatch on the internal binary
    # training-parameter-record schema version. Unknown internal binary
    # record versions fail closed here instead of silently being treated
    # as v1 -- v5 is never classified as external/manual provenance, and a
    # future unrecognized internal version is never silently accepted.
    internal_binary_schema_version = training_record.get("schema_version")
    if internal_binary_schema_version == _EXTERNAL_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION:
        model_descriptor = _resolve_external_result_semantics_model_descriptor(
            training_record, model_selection, positive_class_id
        )
    elif internal_binary_schema_version == _INTERNAL_BINARY_V1_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION:
        model_descriptor = _resolve_internal_result_semantics_model_descriptor(
            training_record, positive_class_id
        )
    elif internal_binary_schema_version == _INTERNAL_BINARY_V5_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION:
        model_descriptor = _resolve_internal_binary_v5_result_semantics_model_descriptor(
            training_record, positive_class_id, class_labels, effective_threshold
        )
    else:
        raise BundleGenerationError(
            "unsupported_training_parameter_record_schema_version",
            "internal binary result_semantics requires a "
            f"{_INTERNAL_BINARY_V1_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION!r} or "
            f"{_INTERNAL_BINARY_V5_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION!r} training parameter "
            f"record, got {internal_binary_schema_version!r}.",
            field="training_parameter_record.schema_version",
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
        "decision": {"threshold": effective_threshold},
        "interpretation": {
            "preset": _require_string(interpretation, "preset"),
            "bands": [dict(band) for band in bands],
        },
        "model_descriptor": model_descriptor,
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


# Project Spec S0180: reused to structurally validate an external fitted-model
# evidence artifact (training-parameter-record.schema.json,
# training-metrics.schema.json, model-selection-evidence.schema.json) before
# any of its fields are trusted. Never used to validate model bytes -- these
# schemas describe reduced JSON evidence only.
def _validate_against_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json_file(schema_path, f"{label}_schema_path")
    try:
        import jsonschema
    except ImportError as exc:
        raise BundleGenerationError(
            "schema_validation_unavailable",
            "jsonschema is required to validate external fitted-model evidence.",
            field="jsonschema",
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise BundleGenerationError(
            "external_evidence_schema_invalid",
            f"{label}.{path}: {first.message}",
            field=f"{label}.{path}",
        )


# Project Spec S0245 Desired Change L: reused to structurally validate
# execution_contract.v2, training-parameter-record.v4, training-metrics.v4,
# and candidate-preparation-recipe.v2 against their canonical repository
# schemas before any forecasting field is trusted. Distinct from
# _validate_against_schema (reserved for the S0180 external fitted-model
# evidence family) only in its error code, so a forecasting schema failure
# is never mistaken for an external-evidence failure.
def _validate_forecasting_artifact_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json_file(schema_path, f"{label}_schema_path")
    try:
        import jsonschema
    except ImportError as exc:
        raise BundleGenerationError(
            "schema_validation_unavailable",
            "jsonschema is required to validate forecasting evidence.",
            field="jsonschema",
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise BundleGenerationError(
            "forecasting_evidence_schema_invalid",
            f"{label}.{path}: {first.message}",
            field=f"{label}.{path}",
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
        execution_contract, training_record, bundle["output_schema"], metrics=metrics
    )
    if result_semantics is not None:
        bundle["result_semantics"] = result_semantics
        # Project Spec S0225 Desired Change H: a generated continuous-
        # regression bundle explicitly declares atlas_internal_training
        # provenance. Historical binary/multiclass bundles keep omitting
        # model_provenance_origin -- unchanged backward-compatible default
        # behavior (contracts/inference-bundle.schema.json's schema
        # condition already treats omission the same as
        # atlas_internal_training).
        if result_semantics.get("problem_type") == "continuous_regression":
            bundle["model_provenance_origin"] = "atlas_internal_training"

    _validate_bundle_schema(bundle, schema_path)
    return bundle


# Governed external fitted-model bundle materialization (Project Spec
# S0180, Desired Change B). Consumes an already-verified
# "external fitted-model materialization result" describing a validated
# external fitted model (Project Spec S0157 profiles) and projects it into
# the same inference_bundle.v1 shape the internal-training path produces,
# using model_provenance_origin/external_model_evidence instead of
# training_evidence. This module never imports, deserializes, fits, or
# predicts with the referenced model -- only its bytes are hashed. The
# governed external evidence contract itself (Project Spec S0180 Desired
# Change A: a dedicated pipeline.materialize_external_fitted_model module
# and schema) is a separate, not-yet-authorized repository change; this
# function only defines and validates the minimal input shape it needs as a
# plain caller-supplied dict, informed by the existing S0157 schemas.
EXTERNAL_MODEL_SOURCE_MODE = "validated_external_fitted_model"
_EXTERNAL_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION = "training-parameter-record.external-fitted-model.v1"
_EXTERNAL_TRAINING_METRICS_SCHEMA_VERSION = "training-metrics.external-fitted-model.v1"
_EXTERNAL_MODEL_SELECTION_EVIDENCE_SCHEMA_VERSION = "model-selection-evidence.external-fitted-model.v1"

# Project Spec S0209: multiclass (v2) external fitted-model bundle profile.
_EXTERNAL_MATERIALIZATION_SCHEMA_VERSION_V2 = "external-fitted-model-materialization.v2"
_EXTERNAL_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION_V2 = "training-parameter-record.external-fitted-model.v2"
_EXTERNAL_MODEL_SELECTION_EVIDENCE_SCHEMA_VERSION_V2 = "model-selection-evidence.external-fitted-model.v2"
# Project Spec S0215: training_metrics now also carries a v2 (multiclass)
# profile, required alongside a v2 materialization result -- never mixed
# with the v1 binary metrics profile.
_EXTERNAL_TRAINING_METRICS_SCHEMA_VERSION_V2 = "training-metrics.external-fitted-model.v2"
MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION = "multiclass-result-semantics.v1"
MULTICLASS_CLASSIFICATION_RESULT_SCHEMA_VERSION = "multiclass-classification-result.v1"
# Project Spec S0208's bounded v2 external estimator identity vocabulary --
# never open-ended, never cross-paired (also enforced structurally by
# contracts/inference-bundle.schema.json's external_family_estimator_pair_v2).
_EXTERNAL_V2_GOVERNED_ESTIMATOR_IDENTITIES: dict[str, dict[str, str]] = {
    "logistic_regression": {"library": "scikit-learn", "class_name": "LogisticRegression"},
    "decision_tree": {"library": "scikit-learn", "class_name": "DecisionTreeClassifier"},
    "random_forest": {"library": "scikit-learn", "class_name": "RandomForestClassifier"},
    "hist_gradient_boosting": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
}


def _external_dataset_slug(materialization_result: dict[str, Any]) -> str:
    identity = _require_mapping(materialization_result, "dataset_identity")
    slug = _require_string(identity, "dataset_slug")
    if not DATASET_SLUG_RE.fullmatch(slug):
        raise BundleGenerationError(
            "invalid_dataset_identity",
            "dataset_identity.dataset_slug is not valid.",
            field="dataset_identity.dataset_slug",
        )
    return slug


# Project Spec S0209 Desired Change I: cross-check all multiclass class
# authorities. Requires exact ordered equality between the training
# parameter record's, model selection evidence's, and the materialization
# result's own classification_evidence (ordered_class_ids +
# probability_columns) -- never sorted or re-derived. A mismatch (missing
# class, extra class, different order, different probability index mapping)
# blocks before a bundle is written.
def _cross_check_multiclass_class_authorities(
    training_record: dict[str, Any],
    model_selection: dict[str, Any],
    materialization_classification_evidence: dict[str, Any],
) -> None:
    record_evidence = training_record.get("classification_evidence")
    selection_evidence = model_selection.get("classification_evidence")
    if not isinstance(record_evidence, dict) or not isinstance(selection_evidence, dict):
        raise BundleGenerationError(
            "missing_required_field",
            "training_parameter_record and model_selection_evidence must both declare "
            "classification_evidence for a multiclass external bundle.",
            field="classification_evidence",
        )
    if (
        record_evidence != materialization_classification_evidence
        or selection_evidence != materialization_classification_evidence
    ):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "training_parameter_record, model_selection_evidence, and the materialization "
            "result must declare identical multiclass classification_evidence "
            "(ordered_class_ids and probability_columns).",
            field="classification_evidence",
        )


# Project Spec S0209 Desired Change J: multiclass external output schema is
# governed, not caller-defined. prediction_type must be 'string',
# probability_output must be true, and class_labels must equal the governed
# ordered class ids exactly -- a disagreeing caller-supplied value fails
# closed rather than being silently reordered or overwritten.
def _resolve_multiclass_output_schema(
    args: argparse.Namespace, ordered_class_ids: list[str]
) -> dict[str, Any]:
    if args.prediction_type != "string":
        raise BundleGenerationError(
            "invalid_output_schema",
            "prediction_type must be 'string' for a multiclass external bundle.",
            field="prediction_type",
        )
    if args.probability_output is False:
        raise BundleGenerationError(
            "invalid_output_schema",
            "probability_output must be true for a multiclass external bundle.",
            field="probability_output",
        )
    if args.class_label and list(args.class_label) != list(ordered_class_ids):
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "caller-supplied class_labels do not match the governed ordered class ids.",
            field="class_labels",
        )
    return {
        "prediction_key": "prediction",
        "prediction_type": "string",
        "class_labels": list(ordered_class_ids),
        "probability_output": True,
    }


# Project Spec S0209 Desired Change H: project the execution contract's
# governed multiclass result_semantics into the bundle. Unlike the binary
# path (_resolve_result_semantics), this is unconditionally required for a
# multiclass external bundle -- there is no historical multiclass bundle to
# stay backward-compatible with.
def _resolve_multiclass_result_semantics(
    execution_contract: dict[str, Any],
    classification_evidence: dict[str, Any],
    model_family: str,
) -> dict[str, Any]:
    result_semantics_source = execution_contract.get("result_semantics")
    if not isinstance(result_semantics_source, dict):
        raise BundleGenerationError(
            "missing_required_field",
            "execution contract result_semantics is required for a multiclass external bundle.",
            field="result_semantics",
        )
    if result_semantics_source.get("schema_version") != MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION:
        raise BundleGenerationError(
            "invalid_result_semantics",
            f"result_semantics.schema_version must equal {MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION!r}.",
            field="result_semantics.schema_version",
        )
    if result_semantics_source.get("problem_type") != "multiclass_classification":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.problem_type must be exactly multiclass_classification.",
            field="result_semantics.problem_type",
        )
    if result_semantics_source.get("primary_output") != "predicted_class":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.primary_output must be exactly predicted_class.",
            field="result_semantics.primary_output",
        )
    if result_semantics_source.get("probability_output") != "class_probabilities":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.probability_output must be exactly class_probabilities.",
            field="result_semantics.probability_output",
        )
    decision = _require_mapping(result_semantics_source, "decision")
    if decision.get("strategy") != "argmax":
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.decision.strategy must be exactly argmax.",
            field="result_semantics.decision.strategy",
        )

    classes = result_semantics_source.get("classes")
    if not isinstance(classes, list) or len(classes) < 3:
        raise BundleGenerationError(
            "invalid_result_semantics",
            "result_semantics.classes must contain at least 3 ordered class entries.",
            field="result_semantics.classes",
        )
    class_ids: list[str] = []
    for entry in classes:
        if not isinstance(entry, dict):
            raise BundleGenerationError(
                "invalid_result_semantics",
                "result_semantics.classes entries must be objects.",
                field="result_semantics.classes",
            )
        class_ids.append(_require_string(entry, "class_id"))
        _require_string(entry, "display_label")

    ordered_class_ids = classification_evidence.get("ordered_class_ids")
    if class_ids != ordered_class_ids:
        raise BundleGenerationError(
            "result_semantics_cross_artifact_mismatch",
            "result_semantics.classes order does not match the materialization "
            "classification_evidence.ordered_class_ids.",
            field="result_semantics.classes",
        )

    if model_family not in MODEL_FAMILY_DISPLAY_NAMES:
        raise BundleGenerationError(
            "unsupported_model_family",
            "model_family is not supported by the result_semantics model_descriptor mapping.",
            field="model_family",
        )

    return {
        "schema_version": MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": "multiclass_classification",
        "result_schema_version": MULTICLASS_CLASSIFICATION_RESULT_SCHEMA_VERSION,
        "classes": [dict(entry) for entry in classes],
        "primary_output": "predicted_class",
        "probability_output": "class_probabilities",
        "decision": {"strategy": "argmax"},
        "model_descriptor": {
            "model_family": model_family,
            "display_name": MODEL_FAMILY_DISPLAY_NAMES[model_family],
        },
    }


def _build_external_bundle(
    materialization_result: dict[str, Any],
    args: argparse.Namespace,
    resolved_repo_root: Path,
) -> dict[str, Any]:
    if materialization_result.get("model_source_mode") != EXTERNAL_MODEL_SOURCE_MODE:
        raise BundleGenerationError(
            "invalid_model_source_mode",
            "external_fitted_model_materialization_result.model_source_mode must be "
            f"{EXTERNAL_MODEL_SOURCE_MODE!r}.",
            field="model_source_mode",
        )

    dataset_slug = _external_dataset_slug(materialization_result)

    evidence_refs = _require_mapping(materialization_result, "evidence_references")
    training_record_ref_path = _require_string(evidence_refs, "training_parameter_record_path")
    training_metrics_ref_path = _require_string(evidence_refs, "training_metrics_path")
    model_selection_ref_path = evidence_refs.get("model_selection_evidence_path")

    training_record_path = resolved_repo_root / training_record_ref_path
    training_metrics_path = resolved_repo_root / training_metrics_ref_path
    training_record = _load_json_file(
        training_record_path, "evidence_references.training_parameter_record_path"
    )
    training_metrics = _load_json_file(
        training_metrics_path, "evidence_references.training_metrics_path"
    )

    _validate_against_schema(
        training_record,
        resolved_repo_root / "pipeline" / "training-parameter-record.schema.json",
        "evidence_references.training_parameter_record_path",
    )
    _validate_against_schema(
        training_metrics,
        resolved_repo_root / "pipeline" / "training-metrics.schema.json",
        "evidence_references.training_metrics_path",
    )
    # Project Spec S0209: closed external materialization/evidence version
    # dispatch. The materialization result's own schema_version is the sole
    # source of truth for whether this is the historical v1 (binary) path or
    # the new v2 (multiclass) path -- never dataset_slug, class labels,
    # model family alone, or feature names. Every other combination
    # (including a v2 materialization paired with v1-shaped training
    # evidence, or vice versa) fails closed below as mixed evidence.
    is_v2 = materialization_result.get("schema_version") == _EXTERNAL_MATERIALIZATION_SCHEMA_VERSION_V2
    expected_record_version = (
        _EXTERNAL_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION_V2
        if is_v2
        else _EXTERNAL_TRAINING_PARAMETER_RECORD_SCHEMA_VERSION
    )
    if training_record.get("schema_version") != expected_record_version:
        raise BundleGenerationError(
            "invalid_external_evidence_profile",
            f"training_parameter_record must declare {expected_record_version!r}.",
            field="evidence_references.training_parameter_record_path",
        )
    expected_training_metrics_version = (
        _EXTERNAL_TRAINING_METRICS_SCHEMA_VERSION_V2 if is_v2 else _EXTERNAL_TRAINING_METRICS_SCHEMA_VERSION
    )
    if training_metrics.get("schema_version") != expected_training_metrics_version:
        raise BundleGenerationError(
            "invalid_external_evidence_profile",
            f"training_metrics must declare {expected_training_metrics_version!r}.",
            field="evidence_references.training_metrics_path",
        )

    model_selection: dict[str, Any] | None = None
    if model_selection_ref_path:
        model_selection_path = resolved_repo_root / model_selection_ref_path
        model_selection = _load_json_file(
            model_selection_path, "evidence_references.model_selection_evidence_path"
        )
        _validate_against_schema(
            model_selection,
            resolved_repo_root / "pipeline" / "model-selection-evidence.schema.json",
            "evidence_references.model_selection_evidence_path",
        )
        expected_selection_version = (
            _EXTERNAL_MODEL_SELECTION_EVIDENCE_SCHEMA_VERSION_V2
            if is_v2
            else _EXTERNAL_MODEL_SELECTION_EVIDENCE_SCHEMA_VERSION
        )
        if model_selection.get("schema_version") != expected_selection_version:
            raise BundleGenerationError(
                "invalid_external_evidence_profile",
                f"model_selection_evidence must declare {expected_selection_version!r}.",
                field="evidence_references.model_selection_evidence_path",
            )

    # contracts/inference-bundle.schema.json's external_model_evidence.evidence_references
    # requires model_selection_evidence_reference unconditionally (unlike the
    # internal training_evidence.model_selection_evidence, which is nullable)
    # -- so an external submission without selection evidence can never
    # become a schema-valid bundle and must block deterministically here
    # rather than emit a bundle guaranteed to fail schema validation with a
    # less specific error.
    if model_selection is None:
        raise BundleGenerationError(
            "missing_required_field",
            "external fitted-model bundles require evidence_references.model_selection_evidence_path; "
            "contracts/inference-bundle.schema.json's external_model_evidence shape does not allow "
            "omitting model_selection_evidence_reference.",
            field="evidence_references.model_selection_evidence_path",
        )

    record_dataset_slug = _require_mapping(training_record, "dataset_identity").get("dataset_slug")
    if record_dataset_slug != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "training_parameter_record dataset_identity does not match the "
            "materialization result dataset identity.",
            field="dataset_identity.dataset_slug",
        )
    metrics_dataset_slug = _require_mapping(training_metrics, "evidence_identity").get("dataset_slug")
    if metrics_dataset_slug != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "training_metrics evidence_identity does not match the materialization "
            "result dataset identity.",
            field="dataset_identity.dataset_slug",
        )

    model_state_fingerprint = _require_sha(
        training_record.get("model_state_fingerprint"), "training_parameter_record.model_state_fingerprint"
    )
    selection_fingerprint = _require_mapping(model_selection, "hashes").get("model_state_fingerprint")
    if selection_fingerprint != model_state_fingerprint:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "model_selection_evidence model_state_fingerprint does not match "
            "training_parameter_record.model_state_fingerprint.",
            field="model_state_fingerprint",
        )

    model_family = _require_string(training_record, "model_family")
    estimator_identity_source = _require_mapping(training_record, "estimator_identity")

    model_artifact_ref_path = _require_string(materialization_result, "model_artifact_path")
    model_artifact_path = resolved_repo_root / model_artifact_ref_path
    record_model_artifact_ref = _require_mapping(training_record, "model_artifact_reference")
    expected_source_sha256 = _require_sha(
        record_model_artifact_ref.get("sha256"), "model_artifact_reference.sha256"
    )
    actual_source_sha256 = _sha256_file(model_artifact_path)
    if actual_source_sha256 != expected_source_sha256:
        raise BundleGenerationError(
            "invalid_hash",
            "model artifact bytes do not match the governed training_parameter_record "
            "model_artifact_reference.sha256.",
            field="model_artifact_path",
        )

    if is_v2:
        classification_evidence_source = _require_mapping(materialization_result, "classification_evidence")
        decision_semantics_source = _require_mapping(materialization_result, "decision_semantics")
        _cross_check_multiclass_class_authorities(
            training_record, model_selection, classification_evidence_source
        )
    else:
        educational_threshold_source = _require_mapping(materialization_result, "educational_threshold")
    operational_readiness = _require_mapping(materialization_result, "operational_readiness")
    final_test_completion_source = _require_mapping(materialization_result, "final_test_completion")

    execution_contract_path = Path(args.execution_contract)
    runtime_contract_path = Path(args.runtime_contract)
    public_contract_path = Path(args.public_contract)
    if not args.prepared_dataset:
        raise BundleGenerationError(
            "missing_required_field",
            "prepared_dataset_path is required for an external fitted-model bundle "
            "(contracts/inference-bundle.schema.json requires prepared_dataset "
            "unconditionally); it is never fabricated or substituted with the raw dataset.",
            field="prepared_dataset_path",
        )
    prepared_dataset_path = Path(args.prepared_dataset)
    dataset_context_path = Path(args.dataset_context) if args.dataset_context else prepared_dataset_path
    schema_path = Path(args.inference_bundle_schema)

    execution_contract = _load_json_file(execution_contract_path, "execution_contract_path")
    runtime_contract = _load_json_file(runtime_contract_path, "runtime_contract_path")
    public_contract = _load_json_file(public_contract_path, "public_contract_path")

    if execution_contract.get("contract_version") != "execution_contract.v1":
        raise BundleGenerationError(
            "invalid_contract_version",
            "execution contract must declare contract_version execution_contract.v1.",
            field="execution_contract.contract_version",
        )
    if execution_contract.get("model_source_mode") != EXTERNAL_MODEL_SOURCE_MODE:
        raise BundleGenerationError(
            "invalid_model_source_mode",
            f"execution contract model_source_mode must be {EXTERNAL_MODEL_SOURCE_MODE!r} "
            "for an external fitted-model bundle.",
            field="execution_contract.model_source_mode",
        )

    contract_dataset_id = execution_contract.get("dataset_id")
    if isinstance(contract_dataset_id, str) and _slugify_dataset_id(contract_dataset_id) != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "execution contract dataset_id does not match the materialization result "
            "dataset identity.",
            field="dataset_id",
        )

    if not args.release_id:
        raise BundleGenerationError(
            "missing_required_field",
            "release_id must be provided by --release-id for an external fitted-model bundle "
            "(external training metrics carry no release_id fallback).",
            field="release_id",
        )
    release_id = _resolve_release_id(args, {})
    release_package_reference = _validate_release_relative(
        args.release_package_reference, "release_package_reference"
    )
    model_package_reference = _validate_release_relative(
        args.model_package_reference, "model_package_reference", file_path=True
    )

    generated_at = _utc_now_iso()
    bundle_id = f"{dataset_slug}-inference-bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    execution_contract_ref = _versioned_ref(
        execution_contract_path, args.execution_contract_ref, execution_contract, "execution_contract_ref"
    )
    runtime_contract_ref = _versioned_ref(
        runtime_contract_path, args.runtime_contract_ref, runtime_contract, "runtime_contract_ref"
    )
    public_contract_ref = _versioned_ref(
        public_contract_path, args.public_contract_ref, public_contract, "public_contract_ref"
    )
    training_parameter_record_ref = _versioned_ref(
        training_record_path, training_record_ref_path, training_record, "training_parameter_record_reference"
    )
    training_metrics_ref = _versioned_ref(
        training_metrics_path, training_metrics_ref_path, training_metrics, "training_metrics_reference"
    )
    model_selection_evidence_reference = _versioned_ref(
        resolved_repo_root / model_selection_ref_path,
        model_selection_ref_path,
        model_selection,
        "model_selection_evidence_reference",
    )

    feature_order = training_record.get("feature_order")
    if (
        not isinstance(feature_order, list)
        or not feature_order
        or any(not isinstance(feature, str) or not feature for feature in feature_order)
    ):
        raise BundleGenerationError(
            "invalid_feature_order",
            "training_parameter_record.feature_order must be a non-empty array of "
            "non-empty strings.",
            field="feature_order",
        )
    if len(set(feature_order)) != len(feature_order):
        raise BundleGenerationError(
            "invalid_feature_order",
            "feature_order must not contain duplicates.",
            field="feature_order",
        )
    contract_features = execution_contract.get("feature_columns")
    if isinstance(contract_features, list) and contract_features != feature_order:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "execution contract feature_columns do not match "
            "training_parameter_record.feature_order.",
            field="feature_columns",
        )

    preprocessing = _resolve_preprocessing(execution_contract)
    estimator_identity_value = {
        "library": _require_string(estimator_identity_source, "library"),
        "class_name": _require_string(estimator_identity_source, "class_name"),
    }

    if is_v2:
        ordered_class_ids = classification_evidence_source.get("ordered_class_ids")
        output_schema = _resolve_multiclass_output_schema(args, ordered_class_ids)

        # Project Spec S0209 Desired Change H: project the execution
        # contract's governed multiclass result_semantics into the bundle,
        # unconditionally (there is no historical multiclass bundle to stay
        # backward-compatible with, unlike the binary path below).
        result_semantics = _resolve_multiclass_result_semantics(
            execution_contract, classification_evidence_source, model_family
        )

        if decision_semantics_source.get("strategy") != "argmax":
            raise BundleGenerationError(
                "invalid_external_evidence_profile",
                "materialization result decision_semantics.strategy must be argmax for a "
                "multiclass external bundle.",
                field="decision_semantics.strategy",
            )

        external_model_evidence = {
            "origin": EXTERNAL_MODEL_SOURCE_MODE,
            "evidence_references": {
                "model_selection_evidence_reference": model_selection_evidence_reference,
                "training_parameter_record_reference": training_parameter_record_ref,
                "training_metrics_reference": training_metrics_ref,
            },
            "model_family": model_family,
            "estimator_identity": estimator_identity_value,
            "model_state_fingerprint": model_state_fingerprint,
            "classification_evidence": dict(classification_evidence_source),
            "decision_semantics": {"strategy": "argmax"},
            "final_test_completion": {
                "evaluation_count": final_test_completion_source.get("evaluation_count"),
                "used_for_decision_rule_selection": bool(
                    final_test_completion_source.get("used_for_decision_rule_selection", False)
                ),
            },
            "readiness": {
                "educational_final_model_complete": bool(
                    operational_readiness.get("educational_final_model_complete")
                ),
                "educational_inference_demo_ready": bool(
                    operational_readiness.get("educational_inference_demo_ready")
                ),
                "operational_validity": operational_readiness.get("operational_validity"),
                "decision_strategy": operational_readiness.get("decision_strategy"),
                "operational_prediction_available": bool(
                    operational_readiness.get("operational_prediction_available")
                ),
            },
        }
    else:
        output_schema = _resolve_output_schema(args)

        # Project Spec S0191 Desired Change B: when the execution contract
        # carries governed binary result_semantics, project it into the
        # external bundle too, synchronizing decision.threshold to the
        # already-validated external threshold evidence (never the execution
        # contract's older threshold, never re-run threshold selection). When
        # the execution contract carries no result_semantics, this preserves
        # historical absence behavior identically to the internal path.
        result_semantics = _resolve_result_semantics(
            execution_contract,
            training_record,
            output_schema,
            model_selection=model_selection,
            decision_threshold_override=educational_threshold_source.get("value"),
        )

        external_model_evidence = {
            "origin": EXTERNAL_MODEL_SOURCE_MODE,
            "evidence_references": {
                "model_selection_evidence_reference": model_selection_evidence_reference,
                "training_parameter_record_reference": training_parameter_record_ref,
                "training_metrics_reference": training_metrics_ref,
            },
            "model_family": model_family,
            "estimator_identity": estimator_identity_value,
            "model_state_fingerprint": model_state_fingerprint,
            "educational_threshold": {
                "value": educational_threshold_source.get("value"),
                "label": "educational",
                "selection_partition": "validation",
                "scenario": _require_string(educational_threshold_source, "scenario"),
            },
            "final_test_completion": {
                "used_for_threshold_selection": bool(
                    final_test_completion_source.get("used_for_threshold_selection", False)
                ),
                "evaluation_count": final_test_completion_source.get("evaluation_count"),
            },
            "readiness": {
                "educational_final_model_complete": bool(
                    operational_readiness.get("educational_final_model_complete")
                ),
                "educational_inference_demo_ready": bool(
                    operational_readiness.get("educational_inference_demo_ready")
                ),
                "operational_modeling_ready": False,
                "operational_validity": operational_readiness.get("operational_validity"),
                "operational_threshold": operational_readiness.get("operational_threshold"),
                "operational_prediction_available": bool(
                    operational_readiness.get("operational_prediction_available")
                ),
            },
        }

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
                dataset_context_path, args.dataset_context_ref, "dataset_context_ref"
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
                prepared_dataset_path, args.prepared_dataset_ref, "prepared_dataset_ref"
            ),
            "prepared_dataset_sha256": _sha256_file(prepared_dataset_path),
        },
        "model_artifact": {
            "path": model_package_reference,
            "sha256": actual_source_sha256,
            "source_training_parameter_record_path": training_parameter_record_ref["path"],
        },
        "runtime_execution": {
            "serialization_format": SUPPORTED_SERIALIZATION_FORMAT,
            "loader_strategy": SUPPORTED_LOADER_STRATEGY,
            "prediction_interface": SUPPORTED_PREDICTION_INTERFACE,
            "model_family": model_family,
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_features_object",
        },
        "feature_order": feature_order,
        "preprocessing": preprocessing,
        "output_schema": output_schema,
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
        "model_provenance_origin": EXTERNAL_MODEL_SOURCE_MODE,
        "external_model_evidence": external_model_evidence,
    }

    if result_semantics is not None:
        bundle["result_semantics"] = result_semantics

    if args.description:
        bundle["bundle_identity"]["description"] = args.description
    if args.candidate_id:
        bundle["release_context"]["candidate_id"] = args.candidate_id
    if args.minimum_runtime_adapter_version:
        bundle["compatibility_constraints"]["minimum_runtime_adapter_version"] = (
            args.minimum_runtime_adapter_version
        )

    # Never weakened: this is the same schema-validation call the internal
    # path uses (contracts/inference-bundle.schema.json, byte-identical for
    # S0180). It is the authoritative pass/fail signal for this bundle, not
    # a formality -- see materialize_governed_inference_bundle's docstring
    # for the known current gap this can legitimately fail on.
    _validate_bundle_schema(bundle, schema_path)
    return bundle


# Project Spec S0245: Atlas-native univariate forecasting inference_bundle.v2
# generation. Never routes through the v1 helpers above (which require
# feature columns/preprocessing) -- the forecasting branch carries a reduced
# frozen-model descriptor instead. Never deserializes the model artifact
# (joblib.load is never called here -- only hashlib.sha256 over its bytes),
# never retrains/refits, and never opens/evaluates the final holdout. All
# required upstream evidence (execution_contract.v2, training-parameter-
# record.v4, training-metrics.v4, candidate-preparation-recipe.v2) is
# structurally schema-validated and cross-checked before any field is
# projected into the bundle.
def _resolve_forecasting_dataset_slug(
    args: argparse.Namespace,
    execution_contract: dict[str, Any],
    training_parameter_record: dict[str, Any],
) -> str:
    identity = _require_mapping(training_parameter_record, "training_run_identity")
    record_dataset_slug = _require_string(identity, "dataset_slug")
    dataset_slug = args.dataset_slug or record_dataset_slug
    if not DATASET_SLUG_RE.fullmatch(dataset_slug):
        raise BundleGenerationError(
            "invalid_dataset_identity",
            "dataset_slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$.",
            field="dataset_slug",
        )
    if record_dataset_slug != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "training_parameter_record.training_run_identity.dataset_slug does not match dataset_slug.",
            field="training_run_identity.dataset_slug",
        )
    dataset_id = execution_contract.get("dataset_id")
    if isinstance(dataset_id, str) and _slugify_dataset_id(dataset_id) != dataset_slug:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "execution contract dataset_id does not match the training dataset_slug.",
            field="dataset_id",
        )
    return dataset_slug


def _forecasting_cross_check_equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            f"{field} disagrees across execution contract, training evidence, and preparation evidence.",
            field=field,
        )


def _build_forecasting_bundle(
    args: argparse.Namespace,
    resolved_repo_root: Path,
) -> dict[str, Any]:
    execution_contract_path = Path(args.execution_contract)
    runtime_contract_path = Path(args.runtime_contract)
    public_contract_path = Path(args.public_contract)
    training_record_path = Path(args.training_parameter_record)
    metrics_path = Path(args.training_metrics)
    model_artifact_path = Path(args.model_artifact)
    dataset_context_path = Path(args.dataset_context)
    schema_path = Path(args.inference_bundle_schema)

    execution_contract = _load_json_file(execution_contract_path, "execution_contract_path")
    runtime_contract = _load_json_file(runtime_contract_path, "runtime_contract_path")
    public_contract = _load_json_file(public_contract_path, "public_contract_path")
    training_record = _load_json_file(training_record_path, "training_parameter_record_path")
    metrics = _load_json_file(metrics_path, "training_metrics_path")

    if execution_contract.get("contract_version") != FORECASTING_EXECUTION_CONTRACT_VERSION:
        raise BundleGenerationError(
            "invalid_contract_version",
            f"execution contract must declare contract_version {FORECASTING_EXECUTION_CONTRACT_VERSION!r}.",
            field="execution_contract.contract_version",
        )
    if execution_contract.get("problem_type") != FORECASTING_PROBLEM_TYPE:
        raise BundleGenerationError(
            "invalid_problem_type",
            f"execution_contract.v2 problem_type must be {FORECASTING_PROBLEM_TYPE!r}.",
            field="execution_contract.problem_type",
        )
    _validate_forecasting_artifact_schema(
        execution_contract,
        _repo_root() / "contracts" / "execution-contract.schema.json",
        "execution_contract_path",
    )

    if training_record.get("schema_version") != FORECASTING_TRAINING_PARAMETER_RECORD_VERSION:
        raise BundleGenerationError(
            "invalid_forecasting_evidence_profile",
            f"training_parameter_record must declare schema_version {FORECASTING_TRAINING_PARAMETER_RECORD_VERSION!r}.",
            field="training_parameter_record_path",
        )
    if training_record.get("problem_type") != FORECASTING_PROBLEM_TYPE:
        raise BundleGenerationError(
            "invalid_problem_type",
            f"training_parameter_record.problem_type must be {FORECASTING_PROBLEM_TYPE!r}.",
            field="training_parameter_record.problem_type",
        )
    _validate_forecasting_artifact_schema(
        training_record,
        _repo_root() / "pipeline" / "training-parameter-record.schema.json",
        "training_parameter_record_path",
    )

    if metrics.get("schema_version") != FORECASTING_TRAINING_METRICS_VERSION:
        raise BundleGenerationError(
            "invalid_forecasting_evidence_profile",
            f"training_metrics must declare schema_version {FORECASTING_TRAINING_METRICS_VERSION!r}.",
            field="training_metrics_path",
        )
    _validate_forecasting_artifact_schema(
        metrics,
        _repo_root() / "pipeline" / "training-metrics.schema.json",
        "training_metrics_path",
    )

    # Project Spec S0245 Desired Change J: derive the preparation recipe and
    # prepared dataset paths from the authenticated v4 training record --
    # never from a prepared_data_metadata.v1 artifact (that requirement is
    # forecasting-specific and never imposed here).
    consumed_inputs = _require_mapping(training_record, "consumed_inputs")
    preparation_recipe_ref = _require_string(consumed_inputs, "preparation_recipe_path")
    dataset_ref = _require_string(consumed_inputs, "dataset_path")
    preparation_recipe_path = resolved_repo_root / preparation_recipe_ref
    prepared_dataset_path = resolved_repo_root / dataset_ref

    preparation_recipe = _load_json_file(preparation_recipe_path, "preparation_recipe_path")
    if preparation_recipe.get("schema_version") != FORECASTING_PREPARATION_RECIPE_VERSION:
        raise BundleGenerationError(
            "invalid_forecasting_evidence_profile",
            f"preparation_recipe must declare schema_version {FORECASTING_PREPARATION_RECIPE_VERSION!r}.",
            field="preparation_recipe_path",
        )
    _validate_forecasting_artifact_schema(
        preparation_recipe,
        _repo_root() / "pipeline" / "candidate-preparation-recipe.schema.json",
        "preparation_recipe_path",
    )

    # Hash reconciliation: never trust the training record's own hashes
    # without independently recomputing them from the referenced bytes.
    hashes = _require_mapping(training_record, "hashes")
    _verify_hash(
        hashes.get("execution_contract_sha256"),
        _sha256_file(execution_contract_path),
        "hashes.execution_contract_sha256",
    )
    _verify_hash(
        hashes.get("preparation_recipe_sha256"),
        _sha256_file(preparation_recipe_path),
        "hashes.preparation_recipe_sha256",
    )
    _verify_hash(
        hashes.get("prepared_dataset_sha256"),
        _sha256_file(prepared_dataset_path),
        "hashes.prepared_dataset_sha256",
    )
    _verify_hash(
        hashes.get("model_artifact_sha256"),
        _sha256_file(model_artifact_path),
        "hashes.model_artifact_sha256",
    )
    if hashes.get("metrics_sha256") is not None:
        _verify_hash(hashes.get("metrics_sha256"), _sha256_file(metrics_path), "hashes.metrics_sha256")

    # Same training-run identity across the parameter record and metrics.
    record_identity = _training_identity(training_record)
    metrics_identity = _training_identity(metrics)
    if record_identity != metrics_identity:
        raise BundleGenerationError(
            "stale_or_inconsistent_artifact",
            "training metrics training_run_identity does not match the training parameter record.",
            field="training_run_identity",
        )

    dataset_slug = _resolve_forecasting_dataset_slug(args, execution_contract, training_record)

    # Cross-artifact temporal/horizon identity reconciliation (Desired
    # Change I). Every field here is free-form in at least one of the three
    # artifacts (not already const-pinned identically by every schema), so
    # a real equality check is required -- schema validation alone cannot
    # catch a stale/mismatched combination.
    training_parameters = _require_mapping(training_record, "training_parameters")
    semantic_identity_mirror = _require_mapping(preparation_recipe, "semantic_identity_mirror")
    forecasting_evidence_metrics = _require_mapping(metrics, "forecasting_evidence")

    target_column = _require_string(execution_contract, "target_column")
    _forecasting_cross_check_equal(
        training_parameters.get("target_column"), target_column, "target_column"
    )
    _forecasting_cross_check_equal(
        semantic_identity_mirror.get("target_field_name"), target_column, "target_column"
    )

    time_index_column = _require_string(execution_contract, "time_index_column")
    _forecasting_cross_check_equal(
        training_parameters.get("time_index_column"), time_index_column, "time_index_column"
    )
    _forecasting_cross_check_equal(
        semantic_identity_mirror.get("time_index_field_name"), time_index_column, "time_index_column"
    )

    index_value_kind = _require_string(execution_contract, "index_value_kind")
    _forecasting_cross_check_equal(
        semantic_identity_mirror.get("index_value_kind"), index_value_kind, "index_value_kind"
    )

    frequency = _require_string(execution_contract, "frequency")
    _forecasting_cross_check_equal(training_parameters.get("frequency"), frequency, "frequency")
    _forecasting_cross_check_equal(semantic_identity_mirror.get("frequency"), frequency, "frequency")

    forecast_horizon = execution_contract.get("forecast_horizon")
    if not isinstance(forecast_horizon, int) or isinstance(forecast_horizon, bool) or forecast_horizon <= 0:
        raise BundleGenerationError(
            "invalid_forecasting_evidence_profile",
            "execution_contract.forecast_horizon must be a positive integer.",
            field="execution_contract.forecast_horizon",
        )
    _forecasting_cross_check_equal(
        training_parameters.get("forecast_horizon"), forecast_horizon, "forecast_horizon"
    )
    _forecasting_cross_check_equal(
        preparation_recipe.get("forecast_horizon"), forecast_horizon, "forecast_horizon"
    )
    _forecasting_cross_check_equal(
        forecasting_evidence_metrics.get("forecast_horizon"), forecast_horizon, "forecast_horizon"
    )

    training_policy = _require_mapping(execution_contract, "training_policy")
    contract_fixed_model_configuration = _require_mapping(training_policy, "fixed_model_configuration")
    record_fixed_model_configuration = _require_mapping(training_parameters, "fixed_model_configuration")
    _forecasting_cross_check_equal(
        record_fixed_model_configuration,
        contract_fixed_model_configuration,
        "training_policy.fixed_model_configuration",
    )

    development = _require_mapping(
        _require_mapping(preparation_recipe, "partitions"), "development"
    )
    backtesting_protocol = _require_mapping(training_parameters, "backtesting_protocol")
    _forecasting_cross_check_equal(
        backtesting_protocol.get("development_observations"),
        development.get("observation_count"),
        "backtesting_protocol.development_observations",
    )

    # Never deserialize model bytes, retrain/refit, or open/evaluate the
    # final holdout -- only hash the already-produced, already-evaluated
    # frozen model artifact.
    model_artifact_sha256 = _sha256_file(model_artifact_path)

    release_id = args.release_id
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise BundleGenerationError(
            "missing_required_field",
            "release_id must be provided by --release-id for a forecasting bundle "
            "(forecasting training metrics carry no release_id fallback).",
            field="release_id",
        )
    release_package_reference = _validate_release_relative(
        args.release_package_reference, "release_package_reference"
    )
    model_package_reference = _validate_release_relative(
        args.model_package_reference, "model_package_reference", file_path=True
    )

    generated_at = _utc_now_iso()
    bundle_id = f"{dataset_slug}-inference-bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    execution_contract_ref = _versioned_ref(
        execution_contract_path, args.execution_contract_ref, execution_contract, "execution_contract_ref"
    )
    runtime_contract_ref = _versioned_ref(
        runtime_contract_path, args.runtime_contract_ref, runtime_contract, "runtime_contract_ref"
    )
    public_contract_ref = _versioned_ref(
        public_contract_path, args.public_contract_ref, public_contract, "public_contract_ref"
    )
    training_parameter_record_ref = _versioned_ref(
        training_record_path, args.training_parameter_record_ref, training_record, "training_parameter_record_ref"
    )
    training_metrics_ref = _versioned_ref(
        metrics_path, args.training_metrics_ref, metrics, "training_metrics_ref"
    )
    preparation_recipe_ref_value = _versioned_ref(
        preparation_recipe_path, preparation_recipe_ref, preparation_recipe, "preparation_recipe_ref"
    )

    finalization_policy = _require_mapping(training_parameters, "finalization_policy")

    bundle: dict[str, Any] = {
        "contract_version": INFERENCE_BUNDLE_VERSION_V2,
        "bundle_identity": {
            "bundle_id": bundle_id,
            "artifact_kind": "inference_bundle",
            "created_at": generated_at,
        },
        "dataset_context": {
            "dataset_slug": dataset_slug,
            "dataset_context_reference": _artifact_ref(
                dataset_context_path, args.dataset_context_ref, "dataset_context_ref"
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
                prepared_dataset_path, dataset_ref, "prepared_dataset_ref"
            ),
            "prepared_dataset_sha256": _sha256_file(prepared_dataset_path),
        },
        "preparation_evidence": {
            "preparation_recipe": preparation_recipe_ref_value,
        },
        "training_evidence": {
            "training_run_identity": record_identity,
            "training_parameter_record": training_parameter_record_ref,
            "training_metrics": training_metrics_ref,
        },
        "frozen_model": {
            "state": "frozen",
            "model_artifact": {
                "path": model_package_reference,
                "sha256": model_artifact_sha256,
                "source_training_parameter_record_path": training_parameter_record_ref["path"],
            },
            "model_family": FORECASTING_MODEL_FAMILY,
            "training_policy_schema_version": FORECASTING_TRAINING_POLICY_SCHEMA_VERSION,
            "fixed_model_configuration": dict(record_fixed_model_configuration),
            "temporal_identity": {
                "target_column": target_column,
                "time_index_column": time_index_column,
                "index_value_kind": index_value_kind,
                "frequency": frequency,
                "source_exogenous_predictors": "forbidden",
                "forecast_horizon": forecast_horizon,
            },
            "training_scope": {
                "start": development.get("start_index_value"),
                "end": development.get("end_index_value"),
                "observation_count": development.get("observation_count"),
            },
            "finalization": {
                "selection_mode": training_parameters.get("selection_mode"),
                "model_selection_performed": training_parameters.get("model_selection_performed"),
                "final_fit_scope": finalization_policy.get("final_fit_scope"),
                "frozen_before_final_holdout_open": finalization_policy.get("freeze_before_final_holdout_open"),
                "final_holdout_evaluation_count": finalization_policy.get("final_holdout_evaluation_count"),
                "final_holdout_used_for_adjustment": finalization_policy.get("final_holdout_used_for_adjustment"),
                "final_holdout_used_for_model_selection": finalization_policy.get(
                    "final_holdout_used_for_model_selection"
                ),
                "no_retuning_after_final_holdout": finalization_policy.get("no_retuning_after_final_holdout"),
            },
        },
        "runtime_execution": {
            "execution_strategy": "in_process",
            "serialization_format": SUPPORTED_SERIALIZATION_FORMAT,
            "loader_strategy": FORECASTING_LOADER_STRATEGY,
            "prediction_interface": FORECASTING_PREDICTION_INTERFACE,
            "model_family": FORECASTING_MODEL_FAMILY,
        },
        "input_schema": {
            "runtime_contract_reference": "contract_references.runtime_contract",
            "payload_shape": "runtime_contract_history_series",
            "input_policy_source": "runtime_contract",
        },
        "output_schema": {
            "result_schema_version": FORECASTING_RESULT_SCHEMA_VERSION,
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "frozen_model.temporal_identity.forecast_horizon",
        },
        "compatibility_constraints": {
            "requires_contract_versions": {
                "execution_contract": FORECASTING_EXECUTION_CONTRACT_VERSION,
                "runtime_contract": runtime_contract_ref["contract_version"],
                "public_contract": public_contract_ref["contract_version"],
            },
            "requires_hash_match": True,
            "requires_release_relative_paths": True,
            "requires_supported_loader": True,
            "requires_supported_serialization": True,
            "requires_temporal_identity_match": True,
            "requires_frozen_model_specification_match": True,
            "requires_forecast_horizon_match": True,
        },
        "result_semantics": {
            "schema_version": FORECASTING_RESULT_SEMANTICS_SCHEMA_VERSION,
            "problem_type": FORECASTING_PROBLEM_TYPE,
            "result_schema_version": FORECASTING_RESULT_SCHEMA_VERSION,
            "primary_output": "forecast_series",
            "output_structure": "ordered_forecast_points",
            "forecast_value_kind": "continuous_numeric",
            "forecast_count_source": "forecast_horizon",
            "model_descriptor": {
                "model_family": FORECASTING_MODEL_FAMILY,
                "display_name": MODEL_FAMILY_DISPLAY_NAMES[FORECASTING_MODEL_FAMILY],
            },
        },
        "model_provenance_origin": "atlas_internal_training",
        "boundary_confirmations": {
            "release_relative_paths_only": True,
            "absolute_paths_embedded": False,
            "parent_traversal_embedded": False,
            "notebook_state_embedded": False,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "runtime_payload_validation_duplicated": False,
            "training_internals_required_at_runtime": False,
            "external_scientific_project_dependency": False,
            "external_model_artifact_used": False,
            "model_selection_performed": False,
            "final_model_frozen": True,
            "final_holdout_used_for_adjustment": False,
        },
    }

    if args.description:
        bundle["bundle_identity"]["description"] = args.description
    if args.candidate_id:
        bundle["release_context"]["candidate_id"] = args.candidate_id

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
    training_run_materialization_result: dict[str, Any] | None = None,
    external_fitted_model_materialization_result: dict[str, Any] | None = None,
    execution_contract_path: str | Path,
    runtime_contract_path: str | Path,
    public_contract_path: str | Path,
    dataset_context_path: str | Path,
    prepared_data_metadata_path: str | Path | None = None,
    output_path: str | Path,
    prediction_type: str | None = None,
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
    prepared_dataset_path: str | Path | None = None,
    prepared_dataset_ref: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Materialize ``inference_bundle.v1`` from exactly one governed
    materialization family (Project Spec S0180): the historical/internal
    ``training_run_materialization_result``, or the new
    ``external_fitted_model_materialization_result``. Exactly one of the two
    must be provided; providing both or neither returns a ``status:
    "blocked"`` result rather than guessing.

    The internal-training branch is unchanged from the original M25-02/S0033
    behavior: only proceeds when ``training_run_materialization_result["status"]
    == "trained"`` and the prepared-data-metadata.v1 artifact's own
    ``prepared_candidate`` is produced and training-ready.

    The external branch never imports, deserializes, fits, or predicts with
    the referenced model artifact -- it only hashes bytes -- and requires
    ``external_fitted_model_materialization_result["model_source_mode"] ==
    "validated_external_fitted_model"`` plus schema-valid S0157 evidence
    references (``pipeline/training-parameter-record.schema.json``,
    ``pipeline/training-metrics.schema.json``,
    ``pipeline/model-selection-evidence.schema.json``, all read-only and
    unmodified by S0180). It never weakens
    ``contracts/inference-bundle.schema.json`` (also unmodified): the
    produced bundle must independently pass that schema's validation before
    this function returns it, exactly like the internal path. As of S0180,
    the only external model family carried by the S0157 evidence profiles is
    ``hist_gradient_boosting``, which is not in
    ``contracts/inference-bundle.schema.json``'s ``runtime_execution.model_family``
    enum (``logistic_regression``/``gradient_boosting``/``random_forest``
    only) -- so a real external submission today deterministically returns
    ``status: "blocked"`` at that final schema check, disclosing the exact
    schema path/message rather than silently accepting or fabricating a
    different model family. This is a genuine, pre-existing schema gap this
    spec does not have edit authorization to close
    (``contracts/inference-bundle.schema.json`` is read-only for S0180); a
    later, separately authorized change to that schema's enum is required
    before any external bundle can be produced successfully.

    Any other state returns a ``status: "blocked"`` result with
    ``blocking_reasons`` instead of generating a bundle. Never accepts
    hidden notebook memory -- only explicit path references and the
    already-computed governed result object(s).
    """
    resolved_repo_root = Path(repo_root or _repo_root()).expanduser().resolve()

    provided_families = [
        value
        for value in (training_run_materialization_result, external_fitted_model_materialization_result)
        if value is not None
    ]
    if len(provided_families) != 1:
        return {
            "status": "blocked",
            "blocking_reasons": [
                "exactly one of training_run_materialization_result or "
                "external_fitted_model_materialization_result must be provided.",
            ],
        }

    if external_fitted_model_materialization_result is not None:
        if not isinstance(external_fitted_model_materialization_result, dict) or (
            external_fitted_model_materialization_result.get("status") != "materialized"
        ):
            status = (
                external_fitted_model_materialization_result.get("status")
                if isinstance(external_fitted_model_materialization_result, dict)
                else "malformed_external_fitted_model_materialization_result"
            )
            return {
                "status": "blocked",
                "blocking_reasons": [
                    "external_fitted_model_materialization_result.status is not "
                    f"'materialized': {status}.",
                ],
            }

        namespace = argparse.Namespace(
            execution_contract=str(Path(execution_contract_path)),
            runtime_contract=str(Path(runtime_contract_path)),
            public_contract=str(Path(public_contract_path)),
            prepared_dataset=str(Path(prepared_dataset_path)) if prepared_dataset_path else None,
            output=str(Path(output_path)),
            release_package_reference=GOVERNED_INFERENCE_BUNDLE_RELEASE_PACKAGE_REFERENCE,
            model_package_reference=model_package_reference or DEFAULT_MODEL_PACKAGE_REFERENCE,
            prediction_type=prediction_type,
            release_id=release_id,
            dataset_slug=dataset_slug,
            dataset_context=str(Path(dataset_context_path)),
            candidate_id=None,
            description=None,
            runtime_adapter_version=None,
            minimum_runtime_adapter_version=None,
            class_label=list(class_labels) if class_labels else None,
            probability_output=probability_output,
            execution_contract_ref=execution_contract_ref,
            runtime_contract_ref=runtime_contract_ref,
            public_contract_ref=public_contract_ref,
            dataset_context_ref=dataset_context_ref,
            prepared_dataset_ref=prepared_dataset_ref,
            inference_bundle_schema=(
                str(Path(inference_bundle_schema_path))
                if inference_bundle_schema_path
                else str(_repo_root() / INFERENCE_BUNDLE_SCHEMA)
            ),
        )

        try:
            bundle = _build_external_bundle(
                external_fitted_model_materialization_result, namespace, resolved_repo_root
            )
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
            "model_provenance_origin": EXTERNAL_MODEL_SOURCE_MODE,
        }

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

    # Project Spec S0245 Desired Change K: explicit bundle-version dispatch
    # from the execution contract's own contract_version/problem_type,
    # before either builder path is committed to. Anything other than
    # execution_contract.v1 or execution_contract.v2 + problem_type =
    # univariate_forecasting fails closed here rather than being routed to
    # the v1 tabular builder (which requires feature columns/preprocessing).
    try:
        execution_contract_for_dispatch = _load_json_file(
            Path(execution_contract_path), "execution_contract_path"
        )
    except BundleGenerationError as exc:
        return {"status": "blocked", "blocking_reasons": [str(exc)], "error": exc.to_dict()["error"]}

    dispatch_contract_version = execution_contract_for_dispatch.get("contract_version")

    if dispatch_contract_version == FORECASTING_EXECUTION_CONTRACT_VERSION:
        if execution_contract_for_dispatch.get("problem_type") != FORECASTING_PROBLEM_TYPE:
            return {
                "status": "blocked",
                "blocking_reasons": [
                    "execution_contract.v2 problem_type must be "
                    f"{FORECASTING_PROBLEM_TYPE!r}.",
                ],
            }

        run_id = Path(training_result["output_directory"]).name
        try:
            provisional_release_id = _derive_provisional_release_id(run_id)
        except BundleGenerationError as exc:
            return {"status": "blocked", "blocking_reasons": [str(exc)]}

        namespace = argparse.Namespace(
            execution_contract=str(Path(execution_contract_path)),
            runtime_contract=str(Path(runtime_contract_path)),
            public_contract=str(Path(public_contract_path)),
            training_parameter_record=str(
                resolved_repo_root / training_result["training_parameter_record_path"]
            ),
            training_metrics=str(resolved_repo_root / training_result["metrics_path"]),
            model_artifact=str(resolved_repo_root / training_result["serialized_model_path"]),
            output=str(Path(output_path)),
            release_package_reference=GOVERNED_INFERENCE_BUNDLE_RELEASE_PACKAGE_REFERENCE,
            model_package_reference=model_package_reference or DEFAULT_MODEL_PACKAGE_REFERENCE,
            release_id=provisional_release_id,
            dataset_slug=dataset_slug,
            dataset_context=str(Path(dataset_context_path)),
            candidate_id=None,
            description=None,
            execution_contract_ref=execution_contract_ref,
            runtime_contract_ref=runtime_contract_ref,
            public_contract_ref=public_contract_ref,
            dataset_context_ref=dataset_context_ref,
            training_parameter_record_ref=training_result["training_parameter_record_path"],
            training_metrics_ref=training_result["metrics_path"],
            inference_bundle_schema=(
                str(Path(inference_bundle_schema_path))
                if inference_bundle_schema_path
                else str(_repo_root() / INFERENCE_BUNDLE_SCHEMA)
            ),
        )

        try:
            bundle = _build_forecasting_bundle(namespace, resolved_repo_root)
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
            "bundle_contract_version": INFERENCE_BUNDLE_VERSION_V2,
            "training_run_id": run_id,
            "provisional_release_id": provisional_release_id,
            "prepared_dataset_reference": bundle["prepared_dataset"]["prepared_dataset_reference"]["path"],
        }

    if dispatch_contract_version != "execution_contract.v1":
        return {
            "status": "blocked",
            "blocking_reasons": [
                f"execution_contract.contract_version is not supported: {dispatch_contract_version!r}.",
            ],
        }

    if not prepared_data_metadata_path:
        return {
            "status": "blocked",
            "blocking_reasons": [
                "prepared_data_metadata_path is required for training_run_materialization_result.",
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
        "bundle_contract_version": INFERENCE_BUNDLE_VERSION,
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
