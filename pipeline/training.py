"""
Governed training entrypoint for atlas-dataflow M24-02.

This module consumes only explicit execution contract and prepared dataset
paths. It performs deterministic splitting and model training, then returns a
trained model object for the later M24-03 persistence step.

Out of scope for this module:
- model serialization or training parameter record persistence;
- metrics artifact, model-card input, or compatibility report production;
- publisher, registry, runtime inference, release, or GitHub operations.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
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
    """Reduced in-memory result. The model object is intentionally not persisted."""

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
            "model_serialized": False,
            "metrics_artifact_produced": False,
            "training_parameter_record_persisted": False,
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


def _select_model_family(contract: dict[str, Any], task_type: str) -> str:
    constraints = contract["modeling_constraints"]
    families = constraints.get("allowed_model_families")
    if not isinstance(families, list) or not families:
        raise TrainingInputError(
            "invalid_contract_field",
            "modeling_constraints.allowed_model_families must be a non-empty array.",
            field="modeling_constraints.allowed_model_families",
        )
    for family in families:
        if family == "logistic_regression" and task_type != "classification":
            continue
        if family in SUPPORTED_MODEL_FAMILIES:
            return family
    raise TrainingInputError(
        "unsupported_model_family",
        "no locally supported model family found for the inferred tabular task type.",
        field="modeling_constraints.allowed_model_families",
    )


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


def train_from_paths(
    execution_contract_path: str | Path,
    dataset_path: str | Path,
) -> TrainingResult:
    """
    Train from explicit governed inputs and return the in-memory model object.

    The returned model is not serialized here. Artifact persistence belongs to
    M24-03 and later pipeline steps.
    """
    contract_path = Path(execution_contract_path)
    prepared_dataset_path = Path(dataset_path)
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
    model_family = _select_model_family(contract, task_type)
    model = _build_estimator(model_family, task_type, contract.get("random_seed"))
    model.set_params(preprocess=_build_preprocessor(features))
    model.fit(features.iloc[train_indices], target.iloc[train_indices])

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
    args = parser.parse_args(argv)

    try:
        result = train_from_paths(args.execution_contract_path, args.dataset_path)
    except TrainingInputError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result.to_summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
