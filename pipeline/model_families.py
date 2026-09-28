"""Generic model-family registry for Atlas tabular estimators.

One declarative table maps an Atlas model-family identifier to the concrete
scikit-learn estimator class for each task type it supports. Native training
(``pipeline.training``) and scientific reproduction
(``pipeline.scientific_reproduction``) both resolve estimator classes here, so
adding a family is a registry change rather than a dataset-specific branch.

The registry only resolves classes and validates hyperparameter names against
the estimator's real ``get_params()`` surface. It never chooses defaults for a
caller: native training keeps its own governed constructor arguments, and a
scientific reproduction passes exactly the parameters its study contract
declares.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping


CLASSIFICATION = "classification"
REGRESSION = "regression"


class ModelFamilyError(ValueError):
    """Raised for an unknown family, unsupported task, or invalid parameter."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ModelFamily:
    family_id: str
    estimators: Mapping[str, str]
    baseline_only: bool = False
    scale_sensitive: bool = False
    description: str = ""

    def supports(self, task_type: str) -> bool:
        return task_type in self.estimators

    def estimator_path(self, task_type: str) -> str:
        if task_type not in self.estimators:
            raise ModelFamilyError(
                "unsupported_task_type",
                f"model family {self.family_id!r} does not support task type {task_type!r}",
            )
        return self.estimators[task_type]


MODEL_FAMILIES: Mapping[str, ModelFamily] = {
    family.family_id: family
    for family in (
        ModelFamily(
            family_id="dummy_prior",
            estimators={
                CLASSIFICATION: "sklearn.dummy.DummyClassifier",
                REGRESSION: "sklearn.dummy.DummyRegressor",
            },
            baseline_only=True,
            description="Non-learning reference baseline; never selectable as a final model.",
        ),
        ModelFamily(
            family_id="logistic_regression",
            estimators={CLASSIFICATION: "sklearn.linear_model.LogisticRegression"},
            scale_sensitive=True,
        ),
        ModelFamily(
            family_id="decision_tree",
            estimators={
                CLASSIFICATION: "sklearn.tree.DecisionTreeClassifier",
                REGRESSION: "sklearn.tree.DecisionTreeRegressor",
            },
        ),
        ModelFamily(
            family_id="random_forest",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.RandomForestClassifier",
                REGRESSION: "sklearn.ensemble.RandomForestRegressor",
            },
        ),
        ModelFamily(
            family_id="gradient_boosting",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.GradientBoostingClassifier",
                REGRESSION: "sklearn.ensemble.GradientBoostingRegressor",
            },
        ),
        ModelFamily(
            family_id="hist_gradient_boosting",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.HistGradientBoostingClassifier",
                REGRESSION: "sklearn.ensemble.HistGradientBoostingRegressor",
            },
        ),
    )
}


def get_family(family_id: str) -> ModelFamily:
    family = MODEL_FAMILIES.get(family_id)
    if family is None:
        raise ModelFamilyError(
            "unsupported_model_family",
            f"model family {family_id!r} is not registered in pipeline.model_families",
        )
    return family


def supported_family_ids(task_type: str) -> list[str]:
    return sorted(fid for fid, family in MODEL_FAMILIES.items() if family.supports(task_type))


def family_for_estimator_class(class_name: str) -> str | None:
    """Return the registered family whose estimator class name matches."""
    for family_id, family in MODEL_FAMILIES.items():
        for path in family.estimators.values():
            if path.rsplit(".", 1)[1] == class_name:
                return family_id
    return None


def estimator_class(family_id: str, task_type: str) -> type:
    module_name, class_name = get_family(family_id).estimator_path(task_type).rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ModelFamilyError(
            "missing_training_dependency",
            f"{module_name} is required for model family {family_id!r}",
        ) from exc
    return getattr(module, class_name)


def build_estimator(
    family_id: str,
    task_type: str,
    params: Mapping[str, Any] | None = None,
) -> Any:
    """Instantiate the family estimator with exactly the declared parameters.

    Unknown parameter names fail closed instead of being silently ignored.
    """
    cls = estimator_class(family_id, task_type)
    declared = dict(params or {})
    accepted = set(cls().get_params(deep=False))
    unknown = sorted(set(declared) - accepted)
    if unknown:
        raise ModelFamilyError(
            "unsupported_hyperparameter",
            f"{cls.__name__} does not accept hyperparameter(s): {unknown}",
        )
    return cls(**declared)


def accepted_hyperparameters(family_id: str, task_type: str) -> frozenset[str]:
    return frozenset(estimator_class(family_id, task_type)().get_params(deep=False))
