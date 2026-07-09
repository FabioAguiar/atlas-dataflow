"""
Governed training entrypoint for atlas-dataflow M24.

This module consumes only explicit execution contract and prepared dataset
paths. It performs deterministic splitting, model training, evaluation metric
production, model-card input production, and reduced artifact persistence.

Out of scope for this module:
- compatibility report production;
- publisher, registry, runtime inference, release, or GitHub operations.

This module also exposes `prepare_training_invocation_readiness` (Project
Spec S0015): a deterministic governed training bridge that validates
explicit execution-contract and prepared-dataset path references and
reports whether `train_from_paths` is ready to be invoked, without training
a model. It distinguishes an execution-ready `execution_contract.v1` from an
`execution_contract_draft.v1` candidate (Project Spec S0014,
`pipeline/contract_derivation.py.project_execution_contract_draft`) and
never treats the latter as training-ready.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PERMITTED_EXECUTION_CONTRACT_FIELDS = frozenset({
    "contract_version",
    "dataset_id",
    "target_column",
    "feature_columns",
    "feature_definitions",
    "missing_value_policy",
    "categorical_encoding_policy",
    "numeric_handling",
    "allowed_transformations",
    "split_policy",
    "random_seed",
    "primary_metric",
    "secondary_metrics",
    "modeling_constraints",
})

SUPPORTED_MODEL_FAMILIES = (
    "logistic_regression",
    "gradient_boosting",
    "random_forest",
)

SERIALIZER_NAME = "joblib"
MODEL_ARTIFACT_FILENAME = "model.pkl"
TRAINING_PARAMETER_RECORD_FILENAME = "training-parameter-record.json"
METRICS_ARTIFACT_FILENAME = "metrics.json"
MODEL_SELECTION_EVIDENCE_FILENAME = "model-selection-evidence.json"
MODEL_CARD_INPUT_FILENAME = "model-card-input.json"
MODEL_CARD_FILENAME = "model-card.json"
CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION = "controlled-entrypoint-provenance.v1"

# Columns that must never enter training as a model feature, regardless of
# what a given execution contract declares (Project Spec S0026). customerID
# is a raw record identifier, never a predictive feature, for every dataset
# this entrypoint has been asked to govern so far.
PROHIBITED_TRAINING_FEATURE_COLUMNS = frozenset({"customerID"})

# Accepted on-disk encodings for an execution-contract `boolean` feature type
# (Project Spec S0026). Telco's own raw CSV alone uses two different
# conventions for boolean-typed columns: SeniorCitizen as "0"/"1" and
# Partner/Dependents as "Yes"/"No" (confirmed via discovery-evidence.json).
_BOOLEAN_ENCODED_VALUES = frozenset({"0", "1", "true", "false", "yes", "no", "t", "f", "y", "n"})

_LOWER_IS_BETTER_METRICS = frozenset({"log_loss"})


class TrainingInputError(ValueError):
    """Structured, actionable validation error raised before training starts."""

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


@dataclass(frozen=True)
class TrainingResult:
    """Reduced result for a governed training run."""

    status: str
    model: Any
    model_family: str
    task_type: str
    train_indices: list[int]
    evaluation_indices: list[int]
    dataset_id: str
    target_column: str
    feature_columns: list[str]
    primary_metric: str
    output_directory: str
    serialized_model_path: str
    training_parameter_record_path: str
    metrics_path: str
    model_selection_evidence_path: str | None
    model_card_input_path: str
    model_card_path: str
    serializer_name: str
    serializer_version: str
    serialization_format_version: str
    training_timestamp: str
    hashes: dict[str, str]
    metrics: dict[str, float]
    model_selection_evidence_produced: bool

    def to_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_family": self.model_family,
            "task_type": self.task_type,
            "dataset_id": self.dataset_id,
            "target_column": self.target_column,
            "feature_columns": self.feature_columns,
            "primary_metric": self.primary_metric,
            "split": {
                "training_rows": len(self.train_indices),
                "evaluation_rows": len(self.evaluation_indices),
            },
            "model_object_returned": self.model is not None,
            "model_serialized": True,
            "output_directory": self.output_directory,
            "serialized_model_path": self.serialized_model_path,
            "training_parameter_record_path": self.training_parameter_record_path,
            "metrics_path": self.metrics_path,
            "model_selection_evidence_path": self.model_selection_evidence_path,
            "model_card_input_path": self.model_card_input_path,
            "model_card_path": self.model_card_path,
            "serializer": {
                "name": self.serializer_name,
                "installed_version": self.serializer_version,
                "serialization_format_version": self.serialization_format_version,
            },
            "training_timestamp": self.training_timestamp,
            "hashes": self.hashes,
            "metrics_artifact_produced": True,
            "metrics": self.metrics,
            "model_selection_evidence_produced": self.model_selection_evidence_produced,
            "model_card_input_produced": True,
            "model_card_produced": True,
            "training_parameter_record_persisted": True,
        }


def _load_json_file(path: Path, field_name: str) -> dict[str, Any]:
    if not path:
        raise TrainingInputError(
            "missing_required_input",
            f"{field_name} is required.",
            field=field_name,
        )
    if not path.exists():
        raise TrainingInputError(
            "missing_required_input",
            f"{field_name} does not exist: {path}",
            field=field_name,
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrainingInputError(
            "invalid_json",
            f"{field_name} is not valid JSON: {exc}",
            field=field_name,
        ) from exc
    if not isinstance(loaded, dict):
        raise TrainingInputError(
            "invalid_json",
            f"{field_name} must be a JSON object.",
            field=field_name,
        )
    return loaded


def _require_contract_field(contract: dict[str, Any], field: str) -> Any:
    if field not in contract or contract[field] in (None, ""):
        raise TrainingInputError(
            "missing_contract_field",
            f"execution contract is missing required field: {field}",
            field=field,
        )
    return contract[field]


def _load_execution_contract(path: Path) -> dict[str, Any]:
    contract = _load_json_file(path, "execution_contract_path")
    reduced = {
        field: contract[field]
        for field in PERMITTED_EXECUTION_CONTRACT_FIELDS
        if field in contract
    }
    for required in (
        "dataset_id",
        "target_column",
        "feature_columns",
        "split_policy",
        "primary_metric",
        "modeling_constraints",
    ):
        _require_contract_field(reduced, required)
    if "random_seed" not in reduced or reduced["random_seed"] == "":
        raise TrainingInputError(
            "missing_contract_field",
            "execution contract is missing required field: random_seed",
            field="random_seed",
        )
    if reduced["random_seed"] is not None and (
        not isinstance(reduced["random_seed"], int)
        or isinstance(reduced["random_seed"], bool)
    ):
        raise TrainingInputError(
            "invalid_contract_field",
            "execution contract random_seed must be an integer or null.",
            field="random_seed",
        )
    if not isinstance(reduced["feature_columns"], list) or not reduced["feature_columns"]:
        raise TrainingInputError(
            "invalid_contract_field",
            "execution contract feature_columns must be a non-empty array.",
            field="feature_columns",
        )
    prohibited = PROHIBITED_TRAINING_FEATURE_COLUMNS.intersection(reduced["feature_columns"])
    if prohibited:
        raise TrainingInputError(
            "prohibited_training_feature",
            (
                "execution contract feature_columns must not include prohibited "
                f"columns: {sorted(prohibited)}."
            ),
            field="feature_columns",
        )
    return reduced


def _is_missing_dataset_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _is_numeric_dataset_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        try:
            return math.isfinite(float(value.strip()))
        except ValueError:
            return False
    return False


def _is_boolean_dataset_value(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return float(value) in (0.0, 1.0)
    if isinstance(value, str):
        return value.strip().lower() in _BOOLEAN_ENCODED_VALUES
    return False


def _validate_contract_dataset_type_compatibility(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> None:
    feature_definitions = contract.get("feature_definitions")
    if feature_definitions in (None, ""):
        return
    if not isinstance(feature_definitions, dict):
        raise TrainingInputError(
            "invalid_contract_field",
            "execution contract feature_definitions must be an object when declared.",
            field="feature_definitions",
        )

    for column in contract["feature_columns"]:
        definition = feature_definitions.get(column)
        if definition is None:
            continue
        if not isinstance(definition, dict):
            raise TrainingInputError(
                "invalid_contract_field",
                f"feature_definitions.{column} must be an object.",
                field=f"feature_definitions.{column}",
            )
        declared_type = definition.get("type")
        if declared_type == "numeric":
            for row in rows:
                value = row.get(column)
                if _is_missing_dataset_value(value):
                    continue
                if not _is_numeric_dataset_value(value):
                    raise TrainingInputError(
                        "contract_dataset_type_mismatch",
                        (
                            f"dataset column {column} contains a value that is not "
                            "compatible with declared numeric feature type."
                        ),
                        field=f"feature_definitions.{column}",
                    )
        elif declared_type == "boolean":
            for row in rows:
                value = row.get(column)
                if _is_missing_dataset_value(value):
                    continue
                if not _is_boolean_dataset_value(value):
                    raise TrainingInputError(
                        "contract_dataset_type_mismatch",
                        (
                            f"dataset column {column} contains a value that is not "
                            "compatible with declared boolean feature type; boolean "
                            "semantics must not be silently generalized during training."
                        ),
                        field=f"feature_definitions.{column}",
                    )


def _validate_missing_value_policy(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> None:
    """Block training on any feature column with unresolved missing values.

    A blank/missing value in a feature column is only acceptable when the
    execution contract's `missing_value_policy` carries an explicit entry
    naming how that column's missing values are handled (Project Spec
    S0026) — for example Telco's own `TotalCharges` blanks, which are
    single-space strings in the raw CSV, not empty strings. Silent
    acceptance without a recorded policy decision is never permitted.
    """
    missing_value_policy = contract.get("missing_value_policy")
    missing_value_policy = missing_value_policy if isinstance(missing_value_policy, dict) else {}
    for column in contract["feature_columns"]:
        if column in missing_value_policy:
            continue
        if any(_is_missing_dataset_value(row.get(column)) for row in rows):
            raise TrainingInputError(
                "unresolved_missing_value_policy",
                (
                    f"dataset column {column} contains missing values but execution "
                    "contract missing_value_policy has no explicit entry for it; "
                    "unresolved missing-value handling must not be silently accepted."
                ),
                field=f"missing_value_policy.{column}",
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _repo_relative_path(path: Path) -> str:
    return path.resolve().relative_to(_repo_root()).as_posix()


def _reduced_path_reference(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return _repo_relative_path(path)
    except ValueError:
        return path.name


def _dataset_slug_from_dataset_id(dataset_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", dataset_id.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise TrainingInputError(
            "invalid_contract_field",
            "execution contract dataset_id cannot produce a valid dataset_slug.",
            field="dataset_id",
        )
    return slug


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"train-{timestamp}Z"


def _training_output_directory(dataset_slug: str, run_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_slug):
        raise TrainingInputError(
            "invalid_run_identity",
            "dataset_slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$.",
            field="dataset_slug",
        )
    if not re.fullmatch(r"train-[0-9]{8}T[0-9]{6}Z", run_id):
        raise TrainingInputError(
            "invalid_run_identity",
            "run_id must match train-{timestamp}Z, for example train-20260625T120000Z.",
            field="run_id",
        )
    return _repo_root() / "pipeline" / "training-runs" / dataset_slug / run_id


def _load_csv_dataset(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
    dataset_ids = {
        row.get("dataset_id")
        for row in rows
        if row.get("dataset_id") not in (None, "")
    }
    if len(dataset_ids) > 1:
        raise TrainingInputError(
            "invalid_prepared_dataset",
            "prepared dataset contains multiple dataset_id values.",
            field="dataset_path",
        )
    return rows, next(iter(dataset_ids), None)


def _load_json_dataset(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrainingInputError(
            "invalid_json",
            f"dataset_path is not valid JSON: {exc}",
            field="dataset_path",
        ) from exc

    dataset_id: str | None = None
    if isinstance(loaded, list):
        rows = loaded
    elif isinstance(loaded, dict):
        dataset_id = loaded.get("dataset_id")
        rows = loaded.get("rows", loaded.get("records", loaded.get("data")))
    else:
        raise TrainingInputError(
            "invalid_prepared_dataset",
            "prepared dataset JSON must be an array or object with rows, records, or data.",
            field="dataset_path",
        )

    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TrainingInputError(
            "invalid_prepared_dataset",
            "prepared dataset rows must be an array of objects.",
            field="dataset_path",
        )
    return [dict(row) for row in rows], dataset_id


def _load_prepared_dataset(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not path:
        raise TrainingInputError(
            "missing_required_input",
            "dataset_path is required.",
            field="dataset_path",
        )
    if not path.exists():
        raise TrainingInputError(
            "missing_required_input",
            f"dataset_path does not exist: {path}",
            field="dataset_path",
        )
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv_dataset(path)
    if suffix == ".json":
        return _load_json_dataset(path)
    raise TrainingInputError(
        "unsupported_dataset_format",
        "dataset_path must reference a supported prepared dataset format: .csv or .json.",
        field="dataset_path",
    )


def _validate_dataset(
    rows: list[dict[str, Any]],
    prepared_dataset_id: str | None,
    contract: dict[str, Any],
) -> None:
    if not rows:
        raise TrainingInputError(
            "invalid_prepared_dataset",
            "prepared dataset must contain at least one row.",
            field="dataset_path",
        )
    contract_dataset_id = str(contract["dataset_id"])
    if prepared_dataset_id is not None and str(prepared_dataset_id) != contract_dataset_id:
        raise TrainingInputError(
            "dataset_id_mismatch",
            "prepared dataset dataset_id does not match execution contract dataset_id.",
            field="dataset_id",
        )
    required_columns = [contract["target_column"], *contract["feature_columns"]]
    missing = [column for column in required_columns if column not in rows[0]]
    if missing:
        raise TrainingInputError(
            "missing_dataset_column",
            f"prepared dataset is missing required columns: {missing}",
            field="dataset_path",
        )
    _validate_contract_dataset_type_compatibility(rows, contract)
    _validate_missing_value_policy(rows, contract)


def _split_indices(
    rows: list[dict[str, Any]],
    target_column: str,
    split_policy: dict[str, Any],
    random_seed: int | None,
) -> tuple[list[int], list[int]]:
    strategy = split_policy.get("strategy")
    train_ratio = split_policy.get("train_ratio")
    val_ratio = split_policy.get("val_ratio", 0)
    test_ratio = split_policy.get("test_ratio")
    if strategy not in {"random", "stratified"}:
        raise TrainingInputError(
            "invalid_split_policy",
            "split_policy.strategy must be 'random' or 'stratified'.",
            field="split_policy",
        )
    if not isinstance(train_ratio, (int, float)) or not 0 < train_ratio < 1:
        raise TrainingInputError(
            "invalid_split_policy",
            "split_policy.train_ratio must be greater than 0 and less than 1.",
            field="split_policy.train_ratio",
        )
    if not isinstance(test_ratio, (int, float)) or not 0 < test_ratio <= 1:
        raise TrainingInputError(
            "invalid_split_policy",
            "split_policy.test_ratio must be greater than 0 and at most 1.",
            field="split_policy.test_ratio",
        )
    if not math.isclose(float(train_ratio) + float(val_ratio) + float(test_ratio), 1.0):
        raise TrainingInputError(
            "invalid_split_policy",
            "split_policy train_ratio, val_ratio, and test_ratio must sum to 1.0.",
            field="split_policy",
        )

    if len(rows) < 2:
        raise TrainingInputError(
            "invalid_prepared_dataset",
            "prepared dataset must contain at least two rows for train/evaluation split.",
            field="dataset_path",
        )

    if strategy == "stratified":
        try:
            return _stratified_split_indices(rows, target_column, float(train_ratio), random_seed)
        except TrainingInputError:
            raise
        except ValueError:
            return _random_split_indices(len(rows), float(train_ratio), random_seed)
    return _random_split_indices(len(rows), float(train_ratio), random_seed)


def _random_split_indices(
    row_count: int,
    train_ratio: float,
    random_seed: int | None,
) -> tuple[list[int], list[int]]:
    import random

    indices = list(range(row_count))
    rng = random.Random(random_seed)
    rng.shuffle(indices)
    train_count = min(max(1, math.floor(row_count * train_ratio)), row_count - 1)
    return sorted(indices[:train_count]), sorted(indices[train_count:])


def _stratified_split_indices(
    rows: list[dict[str, Any]],
    target_column: str,
    train_ratio: float,
    random_seed: int | None,
) -> tuple[list[int], list[int]]:
    import random

    by_class: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_class.setdefault(str(row[target_column]), []).append(index)
    if len(by_class) < 2:
        raise ValueError("stratified split requires at least two target classes")
    rng = random.Random(random_seed)
    train_indices: list[int] = []
    eval_indices: list[int] = []
    for label in sorted(by_class):
        class_indices = list(by_class[label])
        rng.shuffle(class_indices)
        if len(class_indices) == 1:
            eval_indices.extend(class_indices)
            continue
        train_count = min(
            max(1, math.floor(len(class_indices) * train_ratio)),
            len(class_indices) - 1,
        )
        train_indices.extend(class_indices[:train_count])
        eval_indices.extend(class_indices[train_count:])
    if not train_indices or not eval_indices:
        raise ValueError("stratified split produced an empty split")
    return sorted(train_indices), sorted(eval_indices)


def _rows_to_training_frame(
    rows: list[dict[str, Any]],
    feature_columns: list[str],
    target_column: str,
):
    try:
        import pandas as pd
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "pandas is required for governed training. Install pandas in the training environment.",
            field="dataset_path",
        ) from exc

    frame = pd.DataFrame(rows)
    features = frame[feature_columns].copy()
    target = frame[target_column].copy()
    for column in feature_columns:
        numeric = pd.to_numeric(features[column], errors="coerce")
        if numeric.notna().all():
            features[column] = numeric
        else:
            features[column] = features[column].astype("string").fillna("")
    return features, target


def _infer_task_type(target_values: Any) -> str:
    try:
        import pandas as pd
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "pandas is required for task type inference. "
            "Install pandas in the training environment.",
            field="dataset_path",
        ) from exc

    series = pd.Series(target_values)
    numeric = pd.to_numeric(series, errors="coerce")
    unique_count = series.nunique(dropna=True)
    if numeric.notna().all() and unique_count > max(10, int(len(series) * 0.2)):
        return "regression"
    return "classification"


def _build_preprocessor(features: Any):
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "scikit-learn is required for governed training. "
            "Install scikit-learn in the training environment.",
            field="modeling_constraints.allowed_model_families",
        ) from exc

    numeric_columns = [
        column
        for column in features.columns
        if str(features[column].dtype).startswith(("int", "float"))
    ]
    categorical_columns = [column for column in features.columns if column not in numeric_columns]
    transformers = []
    if numeric_columns:
        transformers.append((
            "numeric",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]),
            numeric_columns,
        ))
    if categorical_columns:
        transformers.append((
            "categorical",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OneHotEncoder(handle_unknown="ignore")),
            ]),
            categorical_columns,
        ))
    return ColumnTransformer(transformers)


def _supported_model_families(contract: dict[str, Any], task_type: str) -> list[str]:
    constraints = contract["modeling_constraints"]
    families = constraints.get("allowed_model_families")
    if not isinstance(families, list) or not families:
        raise TrainingInputError(
            "invalid_contract_field",
            "modeling_constraints.allowed_model_families must be a non-empty array.",
            field="modeling_constraints.allowed_model_families",
        )
    supported: list[str] = []
    for family in families:
        if family == "logistic_regression" and task_type != "classification":
            continue
        if family in SUPPORTED_MODEL_FAMILIES:
            supported.append(str(family))
    if supported:
        return supported
    raise TrainingInputError(
        "unsupported_model_family",
        "no locally supported model family found for the inferred tabular task type.",
        field="modeling_constraints.allowed_model_families",
    )


def _select_model_family(contract: dict[str, Any], task_type: str) -> str:
    return _supported_model_families(contract, task_type)[0]


def _build_estimator(model_family: str, task_type: str, random_seed: int | None):
    try:
        from sklearn.ensemble import (
            GradientBoostingClassifier,
            GradientBoostingRegressor,
            RandomForestClassifier,
            RandomForestRegressor,
        )
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "scikit-learn is required for governed training. "
            "Install scikit-learn in the training environment.",
            field="modeling_constraints.allowed_model_families",
        ) from exc

    if model_family == "logistic_regression":
        estimator = LogisticRegression(max_iter=1000, random_state=random_seed)
    elif model_family == "gradient_boosting":
        estimator = (
            GradientBoostingClassifier(random_state=random_seed)
            if task_type == "classification"
            else GradientBoostingRegressor(random_state=random_seed)
        )
    elif model_family == "random_forest":
        estimator = (
            RandomForestClassifier(random_state=random_seed)
            if task_type == "classification"
            else RandomForestRegressor(random_state=random_seed)
        )
    else:
        raise TrainingInputError(
            "unsupported_model_family",
            f"unsupported model family selected: {model_family}",
            field="modeling_constraints.allowed_model_families",
        )

    return Pipeline([
        ("preprocess", None),
        ("model", estimator),
    ])


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _explicit_absence(reason: str) -> dict[str, Any]:
    return {
        "declared": False,
        "value": None,
        "absence_reason": reason,
    }


def _declared_or_absent(source: dict[str, Any], field: str, reason: str) -> dict[str, Any]:
    value = source.get(field)
    if value in (None, ""):
        return _explicit_absence(reason)
    return {
        "declared": True,
        "value": _json_safe(value),
        "absence_reason": None,
    }


def _class_distribution(rows: list[dict[str, Any]], target_column: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(target_column))
        counts[label] = counts.get(label, 0) + 1
    return [
        {
            "label": label,
            "row_count": counts[label],
        }
        for label in sorted(counts)
    ]


def _estimator_hyperparameters(model: Any) -> dict[str, Any]:
    estimator = model.named_steps.get("model") if hasattr(model, "named_steps") else model
    if hasattr(estimator, "get_params"):
        return {
            str(key): _json_safe(value)
            for key, value in sorted(estimator.get_params(deep=False).items())
        }
    return {}


def _serializer_version() -> str:
    try:
        import joblib
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "joblib is required for model artifact serialization. Install joblib in the training environment.",
            field="serializer",
        ) from exc
    return str(joblib.__version__)


def _serialize_model(model: Any, model_path: Path) -> str:
    try:
        import joblib
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "joblib is required for model artifact serialization. Install joblib in the training environment.",
            field="serializer",
        ) from exc
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    return _sha256_file(model_path)


def _require_model_interface_attribute(
    *,
    model: Any,
    attribute: str,
    contract_field: str,
    expectation: str,
) -> Any:
    if not hasattr(model, attribute):
        raise TrainingInputError(
            "contract_model_compatibility_failed",
            (
                f"execution contract field {contract_field} requires model interface "
                f"{attribute}: {expectation}."
            ),
            field=f"{contract_field}:{attribute}",
        )
    return getattr(model, attribute)


def _validate_contract_model_compatibility(
    *,
    contract: dict[str, Any],
    model: Any,
    task_type: str,
) -> None:
    """Validate the fitted model against contract-level interface expectations."""
    feature_columns = [str(column) for column in contract["feature_columns"]]
    n_features_in = _require_model_interface_attribute(
        model=model,
        attribute="n_features_in_",
        contract_field="feature_columns",
        expectation="fitted model must declare the number of input features it accepts",
    )
    if int(n_features_in) != len(feature_columns):
        raise TrainingInputError(
            "contract_model_compatibility_failed",
            (
                "execution contract field feature_columns is incompatible with model "
                f"attribute n_features_in_: expected {len(feature_columns)}, got {n_features_in}."
            ),
            field="feature_columns:n_features_in_",
        )

    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is not None:
        model_feature_names = [str(name) for name in list(feature_names)]
        if model_feature_names != feature_columns:
            raise TrainingInputError(
                "contract_model_compatibility_failed",
                (
                    "execution contract field feature_columns is incompatible with model "
                    "attribute feature_names_in_: expected the same ordered feature names."
                ),
                field="feature_columns:feature_names_in_",
            )

    if not hasattr(model, "predict"):
        raise TrainingInputError(
            "contract_model_compatibility_failed",
            "execution contract requires a model interface with predict support.",
            field="modeling_constraints:predict",
        )

    if task_type == "classification":
        classes = _require_model_interface_attribute(
            model=model,
            attribute="classes_",
            contract_field="target_column",
            expectation="classification model must expose fitted target classes",
        )
        if len(list(classes)) < 2:
            raise TrainingInputError(
                "contract_model_compatibility_failed",
                (
                    "execution contract field target_column requires model attribute "
                    "classes_ to contain at least two fitted classes."
                ),
                field="target_column:classes_",
            )


def _controlled_entrypoint_provenance_marker(
    *,
    contract_path: Path,
    dataset_path: Path,
    output_directory: Path,
    training_timestamp: str,
) -> dict[str, Any]:
    marker_inputs = {
        "version": CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION,
        "entrypoint": "pipeline.training.train_from_paths",
        "run_id": output_directory.name,
        "output_directory": f"{_repo_relative_path(output_directory)}/",
        "execution_contract_sha256": _sha256_file(contract_path),
        "prepared_dataset_sha256": _sha256_file(dataset_path),
        "training_timestamp": training_timestamp,
    }
    marker_id = hashlib.sha256(
        json.dumps(marker_inputs, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "marker_version": CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION,
        "marker_kind": "controlled_training_entrypoint",
        "entrypoint": "pipeline.training.train_from_paths",
        "generated_at": training_timestamp,
        "run_id": output_directory.name,
        "output_directory": marker_inputs["output_directory"],
        "execution_contract_sha256": marker_inputs["execution_contract_sha256"],
        "prepared_dataset_sha256": marker_inputs["prepared_dataset_sha256"],
        "marker_id": marker_id,
    }


def _require_valid_controlled_entrypoint_provenance(
    parameter_record: dict[str, Any],
) -> dict[str, Any]:
    marker = parameter_record.get("controlled_entrypoint_provenance")
    if not isinstance(marker, dict):
        raise TrainingInputError(
            "missing_controlled_entrypoint_provenance",
            (
                "training_parameter_record controlled_entrypoint_provenance is required "
                "before downstream pipeline artifact acceptance."
            ),
            field="controlled_entrypoint_provenance",
        )
    required = {
        "marker_version",
        "marker_kind",
        "entrypoint",
        "generated_at",
        "run_id",
        "output_directory",
        "execution_contract_sha256",
        "prepared_dataset_sha256",
        "marker_id",
    }
    missing = sorted(required - set(marker))
    if missing:
        raise TrainingInputError(
            "invalid_controlled_entrypoint_provenance",
            (
                "training_parameter_record controlled_entrypoint_provenance is missing "
                f"required marker fields: {missing}."
            ),
            field="controlled_entrypoint_provenance",
        )
    if marker["marker_version"] != CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION:
        raise TrainingInputError(
            "invalid_controlled_entrypoint_provenance",
            (
                "training_parameter_record controlled_entrypoint_provenance marker_version "
                f"is incompatible: {marker['marker_version']}."
            ),
            field="controlled_entrypoint_provenance.marker_version",
        )
    if marker["marker_kind"] != "controlled_training_entrypoint":
        raise TrainingInputError(
            "invalid_controlled_entrypoint_provenance",
            "training_parameter_record controlled_entrypoint_provenance marker_kind is invalid.",
            field="controlled_entrypoint_provenance.marker_kind",
        )
    if marker["entrypoint"] != "pipeline.training.train_from_paths":
        raise TrainingInputError(
            "invalid_controlled_entrypoint_provenance",
            "training_parameter_record controlled_entrypoint_provenance entrypoint is invalid.",
            field="controlled_entrypoint_provenance.entrypoint",
        )
    if not re.fullmatch(r"[a-f0-9]{64}", str(marker["marker_id"])):
        raise TrainingInputError(
            "invalid_controlled_entrypoint_provenance",
            "training_parameter_record controlled_entrypoint_provenance marker_id must be a SHA-256 hex digest.",
            field="controlled_entrypoint_provenance.marker_id",
        )
    return marker


def _write_parameter_record(record_path: Path, record: dict[str, Any]) -> str:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha256_file(record_path)


def _write_reduced_json_artifact(path: Path, artifact: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha256_file(path)


def _metric_names(contract: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for metric in [contract["primary_metric"], *(contract.get("secondary_metrics") or [])]:
        metric_name = str(metric)
        if metric_name not in names:
            names.append(metric_name)
    return names


def _positive_class_label(model: Any) -> Any:
    classes = list(getattr(model, "classes_", []))
    if len(classes) != 2:
        raise TrainingInputError(
            "unsupported_metric",
            "roc_auc and pr_auc require binary classification probabilities.",
            field="primary_metric",
        )
    return classes[1]


def _classification_probabilities(model: Any, evaluation_features: Any) -> Any:
    if not hasattr(model, "predict_proba"):
        raise TrainingInputError(
            "unsupported_metric",
            "probability metrics require an estimator with predict_proba support.",
            field="primary_metric",
        )
    return model.predict_proba(evaluation_features)


def _finite_metric_value(metric_name: str, value: Any) -> float:
    metric_value = float(value)
    if not math.isfinite(metric_value):
        raise TrainingInputError(
            "invalid_metric_value",
            f"{metric_name} produced a non-finite value.",
            field=metric_name,
        )
    return metric_value


def _compute_metrics(
    *,
    model: Any,
    task_type: str,
    evaluation_features: Any,
    evaluation_target: Any,
    metric_names: list[str],
) -> dict[str, float]:
    if task_type != "classification":
        raise TrainingInputError(
            "unsupported_metric",
            "M24 execution-contract metrics are scoped to classification use cases.",
            field="primary_metric",
        )

    try:
        from sklearn.metrics import (
            accuracy_score,
            average_precision_score,
            f1_score,
            log_loss,
            roc_auc_score,
        )
    except ImportError as exc:
        raise TrainingInputError(
            "missing_training_dependency",
            "scikit-learn metrics are required for governed training metrics.",
            field="primary_metric",
        ) from exc

    predictions = model.predict(evaluation_features)
    probabilities = None
    values: dict[str, float] = {}
    for metric_name in metric_names:
        try:
            if metric_name == "accuracy":
                values[metric_name] = _finite_metric_value(
                    metric_name,
                    accuracy_score(evaluation_target, predictions),
                )
            elif metric_name == "f1":
                values[metric_name] = _finite_metric_value(
                    metric_name,
                    f1_score(evaluation_target, predictions, average="weighted", zero_division=0),
                )
            elif metric_name == "log_loss":
                if probabilities is None:
                    probabilities = _classification_probabilities(model, evaluation_features)
                values[metric_name] = _finite_metric_value(
                    metric_name,
                    log_loss(evaluation_target, probabilities, labels=list(model.classes_)),
                )
            elif metric_name in {"roc_auc", "pr_auc"}:
                if probabilities is None:
                    probabilities = _classification_probabilities(model, evaluation_features)
                positive_label = _positive_class_label(model)
                positive_scores = probabilities[:, list(model.classes_).index(positive_label)]
                binary_target = [value == positive_label for value in evaluation_target]
                if metric_name == "roc_auc":
                    values[metric_name] = _finite_metric_value(
                        metric_name,
                        roc_auc_score(binary_target, positive_scores),
                    )
                else:
                    values[metric_name] = _finite_metric_value(
                        metric_name,
                        average_precision_score(binary_target, positive_scores),
                    )
            else:
                raise TrainingInputError(
                    "unsupported_metric",
                    f"unsupported execution-contract metric: {metric_name}",
                    field=metric_name,
                )
        except ValueError as exc:
            raise TrainingInputError(
                "metric_computation_failed",
                f"{metric_name} could not be computed on the controlled evaluation split: {exc}",
                field=metric_name,
            ) from exc
    return values


def _primary_metric_sort_value(primary_metric: str, metrics: dict[str, float]) -> float:
    value = metrics[primary_metric]
    return -value if primary_metric in _LOWER_IS_BETTER_METRICS else value


def _train_candidate_models(
    *,
    contract: dict[str, Any],
    task_type: str,
    features: Any,
    target: Any,
    train_indices: list[int],
    evaluation_indices: list[int],
) -> tuple[Any, str, list[dict[str, Any]], bool]:
    metric_names = _metric_names(contract)
    supported_families = _supported_model_families(contract, task_type)
    candidates: list[dict[str, Any]] = []
    for model_family in supported_families:
        model = _build_estimator(model_family, task_type, contract.get("random_seed"))
        model.set_params(preprocess=_build_preprocessor(features))
        model.fit(features.iloc[train_indices], target.iloc[train_indices])
        metric_values = _compute_metrics(
            model=model,
            task_type=task_type,
            evaluation_features=features.iloc[evaluation_indices],
            evaluation_target=target.iloc[evaluation_indices],
            metric_names=metric_names,
        )
        candidates.append({
            "candidate_id": model_family,
            "model_family": model_family,
            "model": model,
            "metrics": metric_values,
        })

    primary_metric = str(contract["primary_metric"])
    selected = max(
        candidates,
        key=lambda candidate: (
            _primary_metric_sort_value(primary_metric, candidate["metrics"]),
            str(candidate["candidate_id"]),
        ),
    )
    multiple_candidates_evaluated = len(candidates) > 1
    return (
        selected["model"],
        str(selected["model_family"]),
        candidates,
        multiple_candidates_evaluated,
    )


def _build_metrics_artifact(
    *,
    contract: dict[str, Any],
    contract_path: Path,
    dataset_path: Path,
    output_directory: Path,
    metrics_path: Path,
    parameter_record_path: Path,
    metric_values: dict[str, float],
    evaluation_indices: list[int],
    training_timestamp: str,
) -> dict[str, Any]:
    return {
        "schema_version": "training-metrics.v1",
        "artifact_kind": "training_metrics",
        "created_at": training_timestamp,
        "training_run_identity": {
            "dataset_slug": output_directory.parent.name,
            "run_id": output_directory.name,
            "output_directory": f"{_repo_relative_path(output_directory)}/",
        },
        "metric_source": {
            "split_name": "evaluation",
            "split_size": len(evaluation_indices),
            "random_seed": contract.get("random_seed"),
            "computed_from_training_split": False,
            "computed_from_mixed_split": False,
        },
        "metrics": {
            "primary_metric": {
                "name": str(contract["primary_metric"]),
                "value": metric_values[str(contract["primary_metric"])],
            },
            "secondary_metrics": [
                {
                    "name": metric_name,
                    "value": metric_values[metric_name],
                }
                for metric_name in _metric_names(contract)
                if metric_name != str(contract["primary_metric"])
            ],
        },
        "path_references": {
            "metrics_path": _repo_relative_path(metrics_path),
            "training_parameter_record_path": _repo_relative_path(parameter_record_path),
            "execution_contract_path": _reduced_path_reference(contract_path),
            "dataset_path": _reduced_path_reference(dataset_path),
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": _sha256_file(contract_path),
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


def _build_model_selection_evidence(
    *,
    contract: dict[str, Any],
    contract_path: Path,
    output_directory: Path,
    evidence_path: Path,
    parameter_record_path: Path,
    candidates: list[dict[str, Any]],
    selected_model_family: str,
    training_timestamp: str,
) -> dict[str, Any]:
    primary_metric = str(contract["primary_metric"])
    ranking_direction = (
        "lower_is_better" if primary_metric in _LOWER_IS_BETTER_METRICS else "higher_is_better"
    )
    return {
        "schema_version": "model-selection-evidence.v1",
        "artifact_kind": "model_selection_evidence",
        "created_at": training_timestamp,
        "training_run_identity": {
            "dataset_slug": output_directory.parent.name,
            "run_id": output_directory.name,
            "output_directory": f"{_repo_relative_path(output_directory)}/",
        },
        "selection_policy": {
            "primary_metric": primary_metric,
            "ranking_direction": ranking_direction,
            "condition": "produced_only_when_multiple_model_candidates_are_evaluated",
        },
        "candidates": [
            {
                "candidate_id": str(candidate["candidate_id"]),
                "model_family": str(candidate["model_family"]),
                "primary_metric": {
                    "name": primary_metric,
                    "value": candidate["metrics"][primary_metric],
                },
                "secondary_metrics": [
                    {
                        "name": metric_name,
                        "value": candidate["metrics"][metric_name],
                    }
                    for metric_name in _metric_names(contract)
                    if metric_name != primary_metric
                ],
            }
            for candidate in candidates
        ],
        "selected_model": {
            "candidate_id": selected_model_family,
            "model_family": selected_model_family,
            "selected_model_reference": _repo_relative_path(parameter_record_path),
            "reference_kind": "training_parameter_record_path",
        },
        "selection_rationale": (
            f"Selected {selected_model_family} by {primary_metric} "
            f"using {ranking_direction} comparison on the controlled evaluation split."
        ),
        "path_references": {
            "model_selection_evidence_path": _repo_relative_path(evidence_path),
            "training_parameter_record_path": _repo_relative_path(parameter_record_path),
            "execution_contract_path": _reduced_path_reference(contract_path),
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": _sha256_file(contract_path),
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


def _build_training_parameter_record(
    *,
    contract: dict[str, Any],
    contract_path: Path,
    dataset_path: Path,
    prepared_dataset_id: str | None,
    result: dict[str, Any],
    output_directory: Path,
    model_artifact_path: Path,
    parameter_record_path: Path,
    metrics_path: Path | None,
    model_selection_evidence_path: Path | None,
    model_card_input_path: Path,
    model_artifact_sha256: str,
    metrics_sha256: str | None,
    controlled_entrypoint_provenance: dict[str, Any],
    serializer_version: str,
    training_timestamp: str,
) -> dict[str, Any]:
    split_policy = dict(contract["split_policy"])
    serialization_format_version = f"{SERIALIZER_NAME}-{serializer_version}"
    return {
        "schema_version": "training-parameter-record.v1",
        "record_kind": "training_parameter_record",
        "training_timestamp": training_timestamp,
        "training_run_identity": {
            "dataset_slug": output_directory.parent.name,
            "run_id": output_directory.name,
            "output_directory": f"{_repo_relative_path(output_directory)}/",
        },
        "consumed_inputs": {
            "execution_contract_path": _reduced_path_reference(contract_path),
            "dataset_path": _reduced_path_reference(dataset_path),
            "execution_contract_dataset_id": str(contract["dataset_id"]),
            "prepared_dataset_dataset_id": str(prepared_dataset_id or contract["dataset_id"]),
        },
        "produced_outputs": {
            "serialized_model_path": _repo_relative_path(model_artifact_path),
            "training_parameter_record_path": _repo_relative_path(parameter_record_path),
            "metrics_path": _repo_relative_path(metrics_path) if metrics_path else None,
            "model_selection_evidence_path": (
                _repo_relative_path(model_selection_evidence_path)
                if model_selection_evidence_path
                else None
            ),
            "model_card_input_path": _repo_relative_path(model_card_input_path),
        },
        "serializer": {
            "name": SERIALIZER_NAME,
            "installed_version": serializer_version,
            "serialization_format_version": serialization_format_version,
        },
        "controlled_entrypoint_provenance": controlled_entrypoint_provenance,
        "permitted_execution_contract_fields": sorted(PERMITTED_EXECUTION_CONTRACT_FIELDS),
        "training_parameters": {
            "model_family": str(result["model_family"]),
            "hyperparameters": _estimator_hyperparameters(result["model"]),
            "target_column": str(contract["target_column"]),
            "feature_columns": [str(column) for column in contract["feature_columns"]],
            "split_policy": split_policy,
            "split_sizes": {
                "training_rows": len(result["train_indices"]),
                "evaluation_rows": len(result["evaluation_indices"]),
            },
            "random_seed": contract.get("random_seed"),
            "primary_metric": str(contract["primary_metric"]),
            "secondary_metrics": list(contract.get("secondary_metrics") or []),
            "modeling_constraints": dict(contract["modeling_constraints"]),
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": _sha256_file(contract_path),
            "prepared_dataset_sha256": _sha256_file(dataset_path),
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
        },
        "record_boundary_confirmations": {
            "is_metrics_artifact": False,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "unauthorized_contract_fields_consumed": False,
            "controlled_entrypoint_provenance_marker_present": True,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "raw_artifact_contents_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }


def _build_model_card_input_artifact(
    *,
    contract: dict[str, Any],
    full_contract: dict[str, Any],
    rows: list[dict[str, Any]],
    task_type: str,
    output_directory: Path,
    model_card_input_path: Path,
    parameter_record_path: Path,
    metrics_path: Path,
    training_timestamp: str,
) -> dict[str, Any]:
    parameter_record = _load_json_file(parameter_record_path, "training_parameter_record_path")
    _require_valid_controlled_entrypoint_provenance(parameter_record)
    metrics_artifact = _load_json_file(metrics_path, "metrics_path")
    training_parameters = parameter_record["training_parameters"]
    metric_source = metrics_artifact["metric_source"]
    primary_metric = metrics_artifact["metrics"]["primary_metric"]
    feature_columns = [str(column) for column in training_parameters["feature_columns"]]
    target_column = str(training_parameters["target_column"])
    intended_use = _declared_or_absent(
        full_contract,
        "intended_use_context",
        "execution contract does not declare intended_use_context",
    )
    target_description = _declared_or_absent(
        full_contract,
        "target_description",
        "execution contract does not declare target_description",
    )

    return {
        "schema_version": "model-card-input.v1",
        "artifact_kind": "model_card_input",
        "created_at": training_timestamp,
        "training_run_identity": {
            "dataset_slug": output_directory.parent.name,
            "run_id": output_directory.name,
            "output_directory": f"{_repo_relative_path(output_directory)}/",
        },
        "model": {
            "model_family": str(training_parameters["model_family"]),
            "task_type": task_type,
            "hyperparameters": _json_safe(training_parameters["hyperparameters"]),
        },
        "training": {
            "training_timestamp": training_timestamp,
            "seed": training_parameters.get("random_seed"),
            "split_policy": _json_safe(training_parameters["split_policy"]),
            "training_data_row_count": int(
                training_parameters["split_sizes"]["training_rows"]
            ),
            "evaluation_split_size": int(metric_source["split_size"]),
        },
        "evaluation": {
            "primary_metric_name": str(primary_metric["name"]),
            "primary_metric_value": primary_metric["value"],
            "secondary_metrics": _json_safe(metrics_artifact["metrics"]["secondary_metrics"]),
        },
        "dataset": {
            "dataset_id": str(contract["dataset_id"]),
            "target_column": target_column,
            "target_description": target_description,
            "feature_count": len(feature_columns),
            "feature_columns": feature_columns,
            "feature_definitions": _json_safe(contract.get("feature_definitions") or {}),
            "class_distribution": (
                _class_distribution(rows, target_column)
                if task_type == "classification"
                else []
            ),
        },
        "intended_use_context": intended_use,
        "path_references": {
            "model_card_input_path": _repo_relative_path(model_card_input_path),
            "training_parameter_record_path": _repo_relative_path(parameter_record_path),
            "metrics_path": _repo_relative_path(metrics_path),
            "execution_contract_path": parameter_record["consumed_inputs"]["execution_contract_path"],
            "dataset_path": parameter_record["consumed_inputs"]["dataset_path"],
        },
        "hashes": {
            "algorithm": "sha256",
            "execution_contract_sha256": parameter_record["hashes"]["execution_contract_sha256"],
            "prepared_dataset_sha256": parameter_record["hashes"]["prepared_dataset_sha256"],
            "training_parameter_record_sha256": _sha256_file(parameter_record_path),
            "metrics_sha256": parameter_record["hashes"]["metrics_sha256"],
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "full_training_parameter_record_embedded": False,
            "full_metrics_artifact_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


# ---------------------------------------------------------------------------
# Handoff-compatible model card (Project Spec S0026)
#
# `model-card.json` is a distinct role from `model-card-input.json` in the
# release-candidate handoff readiness gate (`pipeline/assemble_candidate.py`
# `model_card` role). This deterministically converts an already-produced
# `model-card-input.v1` artifact into that role, without embedding raw
# dataset rows, model bytes, or notebook state, and without performing any
# public release or profile publication step itself.
# ---------------------------------------------------------------------------

MODEL_CARD_SCHEMA_VERSION = "model-card.v1"


def _model_card_artifact_from_input(
    model_card_input: dict[str, Any],
    *,
    model_card_input_path_ref: str,
    model_card_path_ref: str,
    model_card_input_sha256: str,
    created_at: str,
) -> dict[str, Any]:
    training_run_identity = model_card_input["training_run_identity"]
    model = model_card_input["model"]
    evaluation = model_card_input["evaluation"]
    dataset = model_card_input["dataset"]
    return {
        "schema_version": MODEL_CARD_SCHEMA_VERSION,
        "artifact_kind": "model_card",
        "created_at": created_at,
        "training_run_identity": dict(training_run_identity),
        "model_summary": (
            f"{model['model_family']} model trained for dataset "
            f"{dataset['dataset_id']} to predict {dataset['target_column']}."
        ),
        "problem_type": model["task_type"],
        "prediction_target": dataset["target_column"],
        "intended_use": (
            "Governed training-run output for internal review. Not yet reviewed "
            "or approved for public release, profile publication, or production "
            "decisioning."
        ),
        "input_features": list(dataset["feature_columns"]),
        "evaluation": {
            "primary_metric_name": evaluation["primary_metric_name"],
            "primary_metric_value": evaluation["primary_metric_value"],
            "secondary_metrics": _json_safe(evaluation["secondary_metrics"]),
        },
        "limitations": [
            "Generated directly from a governed training run; not reviewed for "
            "public release, profile publication, or production decisioning.",
            "Reflects patterns in the prepared training dataset only; independent "
            "validation is required before any downstream use.",
        ],
        "data_notes": (
            "Reduced, deterministic training-run model card. No raw dataset rows, "
            "model bytes, raw logs, raw runtime data, secrets, or notebook state "
            "are included."
        ),
        "path_references": {
            "model_card_path": model_card_path_ref,
            "model_card_input_path": model_card_input_path_ref,
        },
        "hashes": {
            "algorithm": "sha256",
            "model_card_input_sha256": model_card_input_sha256,
        },
        "model_card_boundary_confirmations": {
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "release_publication_performed": False,
            "profile_publication_performed": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }


def convert_model_card_input_to_model_card(
    model_card_input_path: str | Path,
    model_card_path: str | Path,
) -> str:
    """Deterministically convert an existing `model-card-input.v1` artifact
    into a handoff-compatible `model-card.json` (Project Spec S0026), without
    training a model, mutating the input artifact, or performing any public
    release/profile publication step. Returns the written file's SHA-256.
    """
    input_path = Path(model_card_input_path)
    output_path = Path(model_card_path)
    model_card_input = _load_json_file(input_path, "model_card_input_path")
    if model_card_input.get("schema_version") != "model-card-input.v1":
        raise TrainingInputError(
            "invalid_model_card_input",
            "model_card_input_path does not declare schema_version model-card-input.v1.",
            field="model_card_input_path",
        )
    artifact = _model_card_artifact_from_input(
        model_card_input,
        model_card_input_path_ref=_reduced_path_reference(input_path),
        model_card_path_ref=_reduced_path_reference(output_path),
        model_card_input_sha256=_sha256_file(input_path),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return _write_reduced_json_artifact(output_path, artifact)


def _require_execution_ready_contract(full_contract: dict[str, Any]) -> None:
    """Reject any execution-contract input that is not execution-ready.

    An `execution_contract_draft.v1` (Project Spec S0014) must never be
    treated as training-ready by the actual training entrypoint (Project
    Spec S0026) — not only by the `prepare_training_invocation_readiness`
    bridge (Project Spec S0015), which is only an advisory pre-check that a
    caller could bypass by invoking `train_from_paths` directly.
    """
    identity = _execution_contract_identity(full_contract)
    if identity == "execution_ready":
        return
    blocking_reasons = (
        _draft_review_blocking_reasons(full_contract)
        if identity == "execution_contract_draft"
        else []
    )
    detail = f" Unresolved review items: {blocking_reasons}" if blocking_reasons else ""
    raise TrainingInputError(
        "execution_contract_not_training_ready",
        (
            "execution_contract_path does not reference an execution-ready "
            f"{EXECUTION_READY_CONTRACT_VERSION} contract (identity: {identity})."
            f"{detail}"
        ),
        field="execution_contract_path",
    )


def train_from_paths(
    execution_contract_path: str | Path,
    dataset_path: str | Path,
    *,
    dataset_slug: str | None = None,
    run_id: str | None = None,
) -> TrainingResult:
    """Train from explicit governed inputs and persist M24 training artifacts."""
    contract_path = Path(execution_contract_path)
    prepared_dataset_path = Path(dataset_path)
    full_contract = _load_json_file(contract_path, "execution_contract_path")
    _require_execution_ready_contract(full_contract)
    contract = _load_execution_contract(contract_path)
    rows, prepared_dataset_id = _load_prepared_dataset(prepared_dataset_path)
    _validate_dataset(rows, prepared_dataset_id, contract)

    train_indices, evaluation_indices = _split_indices(
        rows,
        str(contract["target_column"]),
        contract["split_policy"],
        contract.get("random_seed"),
    )
    feature_columns = [str(column) for column in contract["feature_columns"]]
    features, target = _rows_to_training_frame(
        rows,
        feature_columns,
        str(contract["target_column"]),
    )
    task_type = _infer_task_type(target)
    model, model_family, candidates, multiple_candidates_evaluated = _train_candidate_models(
        contract=contract,
        task_type=task_type,
        features=features,
        target=target,
        train_indices=train_indices,
        evaluation_indices=evaluation_indices,
    )

    selected_dataset_slug = dataset_slug or _dataset_slug_from_dataset_id(str(contract["dataset_id"]))
    selected_run_id = run_id or _new_run_id()
    output_directory = _training_output_directory(selected_dataset_slug, selected_run_id)
    model_artifact_path = output_directory / MODEL_ARTIFACT_FILENAME
    parameter_record_path = output_directory / TRAINING_PARAMETER_RECORD_FILENAME
    metrics_path = output_directory / METRICS_ARTIFACT_FILENAME
    model_card_input_path = output_directory / MODEL_CARD_INPUT_FILENAME
    model_selection_evidence_path = (
        output_directory / MODEL_SELECTION_EVIDENCE_FILENAME
        if multiple_candidates_evaluated
        else None
    )
    serializer_version = _serializer_version()
    training_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _validate_contract_model_compatibility(
        contract=contract,
        model=model,
        task_type=task_type,
    )
    controlled_entrypoint_provenance = _controlled_entrypoint_provenance_marker(
        contract_path=contract_path,
        dataset_path=prepared_dataset_path,
        output_directory=output_directory,
        training_timestamp=training_timestamp,
    )
    model_artifact_sha256 = _serialize_model(model, model_artifact_path)
    selected_candidate = next(
        candidate for candidate in candidates if candidate["model_family"] == model_family
    )
    metric_values = selected_candidate["metrics"]
    metrics_artifact = _build_metrics_artifact(
        contract=contract,
        contract_path=contract_path,
        dataset_path=prepared_dataset_path,
        output_directory=output_directory,
        metrics_path=metrics_path,
        parameter_record_path=parameter_record_path,
        metric_values=metric_values,
        evaluation_indices=evaluation_indices,
        training_timestamp=training_timestamp,
    )
    metrics_sha256 = _write_reduced_json_artifact(metrics_path, metrics_artifact)
    model_selection_evidence_sha256 = None
    if model_selection_evidence_path is not None:
        selection_artifact = _build_model_selection_evidence(
            contract=contract,
            contract_path=contract_path,
            output_directory=output_directory,
            evidence_path=model_selection_evidence_path,
            parameter_record_path=parameter_record_path,
            candidates=candidates,
            selected_model_family=model_family,
            training_timestamp=training_timestamp,
        )
        model_selection_evidence_sha256 = _write_reduced_json_artifact(
            model_selection_evidence_path,
            selection_artifact,
        )

    result_payload = {
        "model": model,
        "model_family": model_family,
        "train_indices": train_indices,
        "evaluation_indices": evaluation_indices,
    }
    parameter_record = _build_training_parameter_record(
        contract=contract,
        contract_path=contract_path,
        dataset_path=prepared_dataset_path,
        prepared_dataset_id=prepared_dataset_id,
        result=result_payload,
        output_directory=output_directory,
        model_artifact_path=model_artifact_path,
        parameter_record_path=parameter_record_path,
        metrics_path=metrics_path,
        model_selection_evidence_path=model_selection_evidence_path,
        model_card_input_path=model_card_input_path,
        model_artifact_sha256=model_artifact_sha256,
        metrics_sha256=metrics_sha256,
        controlled_entrypoint_provenance=controlled_entrypoint_provenance,
        serializer_version=serializer_version,
        training_timestamp=training_timestamp,
    )
    parameter_record_sha256 = _write_parameter_record(parameter_record_path, parameter_record)
    model_card_input_artifact = _build_model_card_input_artifact(
        contract=contract,
        full_contract=full_contract,
        rows=rows,
        task_type=task_type,
        output_directory=output_directory,
        model_card_input_path=model_card_input_path,
        parameter_record_path=parameter_record_path,
        metrics_path=metrics_path,
        training_timestamp=training_timestamp,
    )
    model_card_input_sha256 = _write_reduced_json_artifact(
        model_card_input_path,
        model_card_input_artifact,
    )
    model_card_path = output_directory / MODEL_CARD_FILENAME
    model_card_artifact = _model_card_artifact_from_input(
        model_card_input_artifact,
        model_card_input_path_ref=_repo_relative_path(model_card_input_path),
        model_card_path_ref=_repo_relative_path(model_card_path),
        model_card_input_sha256=model_card_input_sha256,
        created_at=training_timestamp,
    )
    model_card_sha256 = _write_reduced_json_artifact(model_card_path, model_card_artifact)

    return TrainingResult(
        status="trained",
        model=model,
        model_family=model_family,
        task_type=task_type,
        train_indices=train_indices,
        evaluation_indices=evaluation_indices,
        dataset_id=str(contract["dataset_id"]),
        target_column=str(contract["target_column"]),
        feature_columns=feature_columns,
        primary_metric=str(contract["primary_metric"]),
        output_directory=f"{_repo_relative_path(output_directory)}/",
        serialized_model_path=_repo_relative_path(model_artifact_path),
        training_parameter_record_path=_repo_relative_path(parameter_record_path),
        metrics_path=_repo_relative_path(metrics_path),
        model_selection_evidence_path=(
            _repo_relative_path(model_selection_evidence_path)
            if model_selection_evidence_path
            else None
        ),
        model_card_input_path=_repo_relative_path(model_card_input_path),
        model_card_path=_repo_relative_path(model_card_path),
        serializer_name=SERIALIZER_NAME,
        serializer_version=serializer_version,
        serialization_format_version=f"{SERIALIZER_NAME}-{serializer_version}",
        training_timestamp=training_timestamp,
        hashes={
            "execution_contract_sha256": parameter_record["hashes"]["execution_contract_sha256"],
            "prepared_dataset_sha256": parameter_record["hashes"]["prepared_dataset_sha256"],
            "model_artifact_sha256": model_artifact_sha256,
            "metrics_sha256": metrics_sha256,
            "training_parameter_record_sha256": parameter_record_sha256,
            "model_card_input_sha256": model_card_input_sha256,
            "model_card_sha256": model_card_sha256,
            "model_selection_evidence_sha256": model_selection_evidence_sha256,
        },
        metrics=metric_values,
        model_selection_evidence_produced=multiple_candidates_evaluated,
    )


# ---------------------------------------------------------------------------
# Governed training bridge (Project Spec S0015)
#
# Bridges dataset-authoring artifacts to this governed training entrypoint
# without letting notebooks, execution-contract drafts, or raw dataset
# references become training authority. `prepare_training_invocation_readiness`
# never trains a model and never infers a path — it only reports, from two
# explicit path references, whether `train_from_paths` is ready to be
# invoked. An execution-contract draft (Project Spec S0014,
# `execution_contract_draft.v1`) is always reported as not training-ready,
# and any unresolved review items it already carries (for example
# `TotalCharges` blank-value handling) are surfaced rather than silently
# accepted.
# ---------------------------------------------------------------------------

TRAINING_INVOCATION_READINESS_CONTRACT_VERSION = "training_invocation_readiness.v1"
EXECUTION_READY_CONTRACT_VERSION = "execution_contract.v1"
EXECUTION_CONTRACT_DRAFT_VERSION = "execution_contract_draft.v1"


def _execution_contract_identity(contract: dict[str, Any]) -> str:
    """Distinguish an execution-ready contract from an execution-contract draft.

    An `execution_contract_draft.v1` (Project Spec S0014) reuses some
    `execution_contract.v1` vocabulary but must never be mistaken for an
    execution-ready contract.
    """
    contract_version = contract.get("contract_version")
    if contract_version == EXECUTION_READY_CONTRACT_VERSION:
        return "execution_ready"
    if (
        contract_version == EXECUTION_CONTRACT_DRAFT_VERSION
        or contract.get("artifact_type") == "execution_contract_draft"
    ):
        return "execution_contract_draft"
    return "unrecognized_contract_identity"


def _draft_review_blocking_reasons(contract: dict[str, Any]) -> list[str]:
    readiness = contract.get("execution_readiness")
    if isinstance(readiness, dict) and isinstance(readiness.get("blocking_reasons"), list):
        return [str(reason) for reason in readiness["blocking_reasons"]]
    return []


def _draft_dataset_slug(contract: dict[str, Any]) -> str | None:
    dataset_identity = contract.get("dataset_identity")
    if isinstance(dataset_identity, dict):
        return dataset_identity.get("dataset_slug")
    return None


def _draft_target_column(contract: dict[str, Any]) -> str | None:
    target_intent = contract.get("target_intent")
    if isinstance(target_intent, dict):
        return target_intent.get("target_column")
    return None


def prepare_training_invocation_readiness(
    execution_contract_path: str | Path,
    dataset_path: str | Path,
) -> dict[str, Any]:
    """Governed training bridge: report whether `train_from_paths` is training-ready.

    Both `execution_contract_path` and `dataset_path` are required, explicit
    path references — never notebook-held DataFrames, notebook variables, or
    a hidden current working directory. Missing or unreadable inputs raise
    `TrainingInputError`, matching `train_from_paths`'s own input validation.
    An `execution_contract_draft.v1` (Project Spec S0014) is always reported
    as not training-ready, with its own unresolved review items (if any)
    carried into `blocking_reasons` rather than silently accepted. This
    function never trains a model and never mutates its inputs.
    """
    contract_path = Path(execution_contract_path)
    prepared_dataset_path = Path(dataset_path)

    full_contract = _load_json_file(contract_path, "execution_contract_path")
    if not prepared_dataset_path.exists():
        raise TrainingInputError(
            "missing_required_input",
            f"dataset_path does not exist: {prepared_dataset_path}",
            field="dataset_path",
        )
    if prepared_dataset_path.suffix.lower() not in (".csv", ".json"):
        raise TrainingInputError(
            "unsupported_dataset_format",
            "dataset_path must reference a supported prepared dataset format: .csv or .json.",
            field="dataset_path",
        )

    contract_identity = _execution_contract_identity(full_contract)
    blocking_reasons: list[str] = []
    dataset_id: str | None = None
    target_column: str | None = None

    if contract_identity == "execution_ready":
        reduced_contract = _load_execution_contract(contract_path)
        dataset_id = str(reduced_contract["dataset_id"])
        target_column = str(reduced_contract["target_column"])
    elif contract_identity == "execution_contract_draft":
        blocking_reasons.append(
            "execution_contract_path references an execution_contract_draft.v1 "
            "candidate (Project Spec S0014), not an execution-ready "
            f"{EXECUTION_READY_CONTRACT_VERSION} contract; a draft must never be "
            "treated as execution-ready training input."
        )
        blocking_reasons.extend(_draft_review_blocking_reasons(full_contract))
        dataset_id = _draft_dataset_slug(full_contract)
        target_column = _draft_target_column(full_contract)
    else:
        blocking_reasons.append(
            "execution_contract_path does not declare a recognized contract_version "
            f"({EXECUTION_READY_CONTRACT_VERSION!r} or "
            f"{EXECUTION_CONTRACT_DRAFT_VERSION!r})."
        )

    is_training_ready = contract_identity == "execution_ready" and not blocking_reasons

    return {
        "artifact_type": "training_invocation_readiness",
        "contract_version": TRAINING_INVOCATION_READINESS_CONTRACT_VERSION,
        "execution_contract_path": _reduced_path_reference(contract_path),
        "dataset_path": _reduced_path_reference(prepared_dataset_path),
        "execution_contract_identity": contract_identity,
        "dataset_id": dataset_id,
        "target_column": target_column,
        "is_training_ready": is_training_ready,
        "blocking_reasons": blocking_reasons,
        "governed_entrypoint": "pipeline.training.train_from_paths",
        "training_invocation_readiness_boundary_confirmations": {
            "is_execution_contract": False,
            "is_training_result": False,
            "model_trained": False,
            "training_invoked": False,
            "execution_contract_draft_promoted_to_official_contract": False,
        },
    }


# ---------------------------------------------------------------------------
# Governed training run materialization from prepared-data-metadata
# (Project Spec S0026)
#
# `materialize_training_run_from_prepared_metadata` bridges a
# `prepared-data-metadata.v1` artifact (`pipeline/prepare_candidate.py`) to
# this module's own `train_from_paths`. It never trains from the raw CSV, a
# notebook-held DataFrame, or notebook memory: the only dataset input it
# will ever pass to `train_from_paths` is the explicit repository-relative
# `prepared_candidate.reference` path recorded by that metadata artifact,
# and only once the metadata itself declares both
# `prepared_candidate.produced` and `training_readiness.is_training_ready`
# true. An `execution_contract_draft.v1` (Project Spec S0014) is rejected
# here up front, in addition to `train_from_paths`'s own rejection, so a
# blocked result can report a clear reason instead of surfacing as a raised
# exception.
# ---------------------------------------------------------------------------

TRAINING_RUN_MATERIALIZATION_CONTRACT_VERSION = "training_run_materialization_result.v1"
PREPARED_DATASET_METADATA_SCHEMA_VERSION = "prepared-data-metadata.v1"


def _metadata_reference_path_and_checks(
    reference: Any,
    dataset_slug: str | None = None,
) -> tuple[str | None, dict[str, Any], str | None]:
    if isinstance(reference, str):
        reference_path = reference.strip()
        reference_checks: dict[str, Any] = {}
    elif isinstance(reference, dict):
        path_value = reference.get("path")
        reference_path = path_value.strip() if isinstance(path_value, str) else ""
        reference_checks = {
            key: reference[key]
            for key in ("row_count", "column_count", "content_sha256")
            if key in reference
        }
    else:
        reference_path = ""
        reference_checks = {}

    if not reference_path:
        return None, reference_checks, (
            "prepared_data_metadata.prepared_candidate.reference is not an explicit "
            "prepared dataset artifact/payload path; raw CSV inference and notebook "
            "memory are never accepted as training input."
        )

    reference_parts = Path(reference_path).parts
    if Path(reference_path).is_absolute() or ".." in reference_parts:
        return None, reference_checks, (
            "prepared_data_metadata.prepared_candidate.reference must be a safe "
            "repository-relative prepared dataset artifact path."
        )

    expected_prefix = ("pipeline", "prepared")
    if reference_parts[:2] != expected_prefix:
        return None, reference_checks, (
            "prepared_data_metadata.prepared_candidate.reference is outside the "
            "expected prepared dataset artifact boundary: pipeline/prepared/."
        )
    if dataset_slug and reference_parts[:3] != (*expected_prefix, dataset_slug):
        return None, reference_checks, (
            "prepared_data_metadata.prepared_candidate.reference is outside the "
            f"expected prepared dataset artifact boundary: pipeline/prepared/{dataset_slug}/."
        )

    return Path(reference_path).as_posix(), reference_checks, None


def _validate_prepared_dataset_reference_file(
    reference: str,
    reference_checks: dict[str, Any],
) -> str | None:
    resolved_path = (_repo_root() / reference).resolve()
    try:
        resolved_reference = resolved_path.relative_to(_repo_root().resolve()).as_posix()
    except ValueError:
        return "prepared dataset reference path resolves outside the repository."

    if resolved_reference != reference:
        return (
            "prepared dataset reference path is not normalized to the resolved "
            "repository-relative artifact path."
        )
    if not resolved_path.exists():
        return f"prepared dataset reference path does not exist: {reference}"
    if not resolved_path.is_file():
        return f"prepared dataset reference path is not a file: {reference}"
    try:
        with resolved_path.open("rb"):
            pass
    except OSError as exc:
        return f"prepared dataset reference path is not readable: {reference} ({exc})"

    if any(key in reference_checks for key in ("row_count", "column_count")):
        try:
            rows, _ = _load_prepared_dataset(resolved_path)
        except TrainingInputError as exc:
            return str(exc)
        if "row_count" in reference_checks and len(rows) != reference_checks["row_count"]:
            return (
                "prepared dataset reference row_count mismatch: metadata declares "
                f"{reference_checks['row_count']}, actual file has {len(rows)}."
            )
        if "column_count" in reference_checks:
            actual_columns = len(rows[0]) if rows else 0
            if actual_columns != reference_checks["column_count"]:
                return (
                    "prepared dataset reference column_count mismatch: metadata declares "
                    f"{reference_checks['column_count']}, actual file has {actual_columns}."
                )

    if "content_sha256" in reference_checks:
        actual_sha256 = _sha256_file(resolved_path)
        if actual_sha256 != reference_checks["content_sha256"]:
            return (
                "prepared dataset reference content_sha256 mismatch: metadata declares "
                f"{reference_checks['content_sha256']}, actual file has {actual_sha256}."
            )

    return None


def _prepared_dataset_metadata_blocking_reasons(
    metadata: dict[str, Any],
) -> tuple[list[str], str | None]:
    blocking_reasons: list[str] = []
    if metadata.get("schema_version") != PREPARED_DATASET_METADATA_SCHEMA_VERSION:
        blocking_reasons.append(
            "prepared_data_metadata_path does not declare schema_version "
            f"{PREPARED_DATASET_METADATA_SCHEMA_VERSION!r}."
        )

    prepared_candidate = metadata.get("prepared_candidate")
    prepared_candidate = prepared_candidate if isinstance(prepared_candidate, dict) else {}
    if prepared_candidate.get("produced") is not True:
        blocking_reasons.append(
            "prepared_data_metadata.prepared_candidate.produced is not true: "
            f"{prepared_candidate.get('reason_not_produced') or 'no reason recorded'}"
        )

    dataset_identity = metadata.get("dataset_identity")
    dataset_identity = dataset_identity if isinstance(dataset_identity, dict) else {}
    dataset_slug = dataset_identity.get("dataset_slug")
    reference, reference_checks, reference_block_reason = (
        _metadata_reference_path_and_checks(
            prepared_candidate.get("reference"),
            dataset_slug if isinstance(dataset_slug, str) else None,
        )
    )
    if reference_block_reason:
        blocking_reasons.append(reference_block_reason)

    training_readiness = metadata.get("training_readiness")
    training_readiness = training_readiness if isinstance(training_readiness, dict) else {}
    if training_readiness.get("is_training_ready") is not True:
        blocking_reasons.append(
            "prepared_data_metadata.training_readiness.is_training_ready is not true: "
            f"{training_readiness.get('reason') or 'no reason recorded'}"
        )

    for item in metadata.get("unresolved_review_items") or []:
        if isinstance(item, dict) and item.get("review_status") != "explicit":
            description = item.get("description") or "unresolved review item"
            blocking_reasons.append(f"unresolved_review_item: {description}")

    if reference is not None:
        reference_file_block_reason = _validate_prepared_dataset_reference_file(
            reference,
            reference_checks,
        )
        if reference_file_block_reason:
            blocking_reasons.append(reference_file_block_reason)

    return blocking_reasons, reference


def materialize_training_run_from_prepared_metadata(
    execution_contract_path: str | Path,
    prepared_data_metadata_path: str | Path,
    *,
    dataset_slug: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Materialize a governed training run from explicit path references only.

    Requires an execution-ready `execution_contract.v1` (never an
    `execution_contract_draft.v1`) and a `prepared-data-metadata.v1`
    artifact whose `prepared_candidate.produced` and
    `training_readiness.is_training_ready` are both true, with an explicit
    `prepared_candidate.reference` path. When any of that is not yet true,
    returns a `status: "blocked"` result with `blocking_reasons` instead of
    training. Never reads the raw dataset CSV directly and never accepts a
    notebook-held DataFrame.
    """
    contract_path = Path(execution_contract_path)
    metadata_path = Path(prepared_data_metadata_path)
    full_contract = _load_json_file(contract_path, "execution_contract_path")
    metadata = _load_json_file(metadata_path, "prepared_data_metadata_path")

    contract_identity = _execution_contract_identity(full_contract)
    blocking_reasons: list[str] = []
    if contract_identity != "execution_ready":
        blocking_reasons.append(
            "execution_contract_path does not reference an execution-ready "
            f"{EXECUTION_READY_CONTRACT_VERSION} contract (identity: {contract_identity})."
        )
        blocking_reasons.extend(_draft_review_blocking_reasons(full_contract))

    dataset_blocking_reasons, reference = _prepared_dataset_metadata_blocking_reasons(metadata)
    blocking_reasons.extend(dataset_blocking_reasons)

    if blocking_reasons:
        return {
            "artifact_type": "training_run_materialization_result",
            "contract_version": TRAINING_RUN_MATERIALIZATION_CONTRACT_VERSION,
            "status": "blocked",
            "execution_contract_identity": contract_identity,
            "prepared_dataset_reference": reference,
            "blocking_reasons": blocking_reasons,
            "governed_entrypoint": "pipeline.training.train_from_paths",
            "materialization_boundary_confirmations": {
                "model_training_performed": False,
                "training_run_materialized": False,
            },
        }

    resolved_dataset_path = _repo_root() / reference
    result = train_from_paths(
        contract_path,
        resolved_dataset_path,
        dataset_slug=dataset_slug,
        run_id=run_id,
    )
    return {
        "artifact_type": "training_run_materialization_result",
        "contract_version": TRAINING_RUN_MATERIALIZATION_CONTRACT_VERSION,
        "status": "trained",
        "execution_contract_identity": contract_identity,
        "prepared_dataset_reference": reference,
        "blocking_reasons": [],
        "governed_entrypoint": "pipeline.training.train_from_paths",
        "materialization_boundary_confirmations": {
            "model_training_performed": True,
            "training_run_materialized": True,
        },
        "training_result": result.to_summary(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train a governed Atlas model from an execution contract and prepared dataset."
    )
    parser.add_argument(
        "--execution-contract-path",
        required=True,
        help="Explicit path to the execution_contract.v1 JSON file.",
    )
    parser.add_argument(
        "--dataset-path",
        required=True,
        help="Explicit path to the prepared dataset file (.csv or .json).",
    )
    parser.add_argument(
        "--dataset-slug",
        help="Optional dataset slug for pipeline/training-runs/{dataset_slug}/{run_id}/. Defaults to a slug derived from execution_contract.dataset_id.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional run identifier matching train-{timestamp}Z. Defaults to the current UTC timestamp.",
    )
    args = parser.parse_args(argv)

    try:
        result = train_from_paths(
            args.execution_contract_path,
            args.dataset_path,
            dataset_slug=args.dataset_slug,
            run_id=args.run_id,
        )
    except TrainingInputError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result.to_summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
