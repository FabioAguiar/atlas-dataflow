"""
Governed training entrypoint for atlas-dataflow M24.

This module consumes only explicit execution contract and prepared dataset
paths. It performs deterministic splitting, model training, evaluation metric
production, model-card input production, and reduced artifact persistence.

Out of scope for this module:
- compatibility report production;
- publisher, registry, runtime inference, release, or GitHub operations.
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
            "serialized_model_path": self.serialized_model_path,
            "training_parameter_record_path": self.training_parameter_record_path,
            "metrics_path": self.metrics_path,
            "model_selection_evidence_path": self.model_selection_evidence_path,
            "model_card_input_path": self.model_card_input_path,
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
        "random_seed",
        "primary_metric",
        "modeling_constraints",
    ):
        _require_contract_field(reduced, required)
    if not isinstance(reduced["feature_columns"], list) or not reduced["feature_columns"]:
        raise TrainingInputError(
            "invalid_contract_field",
            "execution contract feature_columns must be a non-empty array.",
            field="feature_columns",
        )
    return reduced


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
            "model_selection_evidence_sha256": model_selection_evidence_sha256,
        },
        metrics=metric_values,
        model_selection_evidence_produced=multiple_candidates_evaluated,
    )


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
