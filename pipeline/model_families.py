"""Generic model-family registry for Atlas estimators -- the model-family
authority.

One declarative table maps an Atlas model-family identifier to:

* the concrete scikit-learn estimator class for each task type it supports
  (resolved here by native training and scientific reproduction);
* the display name used by inference bundles and result contracts;
* ``native_training``: the problem types Atlas-native training can fit the
  family for, and with which selection modes;
* ``governed_result_problem_types``: the problem types whose governed result
  contracts (inference bundle / runtime result semantics) accept the family,
  which also covers families that only reach a release through the external
  fitted-model lineage.

Every per-layer closed set (training's supported families, the training-
policy vocabulary, inference-bundle family sets, runtime result family sets,
and the JSON schema enums) is derived from, or tested against, these fields.
Support is never widened implicitly: a family is accepted for a problem type
only where this table says so.

The registry only resolves classes and validates hyperparameter names against
the estimator's real ``get_params()`` surface. It never chooses defaults for a
caller: native training keeps its own governed constructor arguments, and a
scientific reproduction passes exactly the parameters its study contract
declares.

A family with neither ``native_training`` nor ``governed_result_problem_types``
(``ridge``) is resolvable only by the scientific reproduction engine; it never
reaches native training, an inference bundle, or a release.

``dummy_prior`` is the historical identifier of the non-learning baseline
family, not of a strategy: it resolves ``DummyClassifier`` or
``DummyRegressor`` by task type, and the strategy (``prior`` for the
classification studies, ``median`` for a regression study) is always the
contract's declared ``fixed_params["strategy"]``. Reusing the identifier keeps
one family per estimator class (``family_for_estimator_class``) and every
historical contract valid.

Univariate forecasting families are not scikit-learn estimators. For them the
table records the *scientific forecasting* identity instead:

* ``forecasting_constructor``: the third-party constructor a scientific
  forecasting adapter (``pipeline.forecasting_models``) calls, or ``None`` for
  a closed-form rule (seasonal naive, last value);
* ``forecasting_family_names``: the family names a Dataset Study may use for
  the family in its own vocabulary. A family with names is resolvable by the
  scientific forecasting reproduction; ``pipeline.forecasting_models`` holds
  exactly one executable adapter per such family (tested).

Being resolvable by the scientific reproduction never makes a family natively
trainable or release-governed. ``deterministic_seasonal_trend_ols`` is both:
native training keeps its own implementation (``pipeline.training``), and the
scientific adapter executes the constructor a study declares.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


CLASSIFICATION = "classification"
REGRESSION = "regression"

BINARY_CLASSIFICATION = "binary_classification"
MULTICLASS_CLASSIFICATION = "multiclass_classification"
CONTINUOUS_REGRESSION = "continuous_regression"
UNIVARIATE_FORECASTING = "univariate_forecasting"
TABULAR_PROBLEM_TYPES = (BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION, CONTINUOUS_REGRESSION)

EVALUATE_ALLOWED_FAMILIES = "evaluate_allowed_families"
FIXED_CONFIGURATION = "fixed_configuration"


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
    display_name: str | None = None
    native_training: Mapping[str, frozenset[str]] = field(default_factory=dict)
    governed_result_problem_types: frozenset[str] = frozenset()
    forecasting_constructor: str | None = None
    forecasting_family_names: tuple[str, ...] = ()

    @property
    def scientific_forecasting(self) -> bool:
        return bool(self.forecasting_family_names)

    def natively_trainable(self, problem_type: str, selection_mode: str | None = None) -> bool:
        modes = self.native_training.get(problem_type)
        if not modes:
            return False
        return selection_mode is None or selection_mode in modes

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
            display_name="Logistic Regression",
            native_training={BINARY_CLASSIFICATION: frozenset({EVALUATE_ALLOWED_FAMILIES})},
            governed_result_problem_types=frozenset({BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION}),
        ),
        ModelFamily(
            family_id="gradient_boosting",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.GradientBoostingClassifier",
                REGRESSION: "sklearn.ensemble.GradientBoostingRegressor",
            },
            display_name="Gradient Boosting",
            native_training={
                BINARY_CLASSIFICATION: frozenset({EVALUATE_ALLOWED_FAMILIES}),
                CONTINUOUS_REGRESSION: frozenset({FIXED_CONFIGURATION}),
            },
            governed_result_problem_types=frozenset({BINARY_CLASSIFICATION, CONTINUOUS_REGRESSION}),
        ),
        ModelFamily(
            family_id="random_forest",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.RandomForestClassifier",
                REGRESSION: "sklearn.ensemble.RandomForestRegressor",
            },
            display_name="Random Forest",
            native_training={
                BINARY_CLASSIFICATION: frozenset({EVALUATE_ALLOWED_FAMILIES}),
                CONTINUOUS_REGRESSION: frozenset({FIXED_CONFIGURATION}),
            },
            governed_result_problem_types=frozenset(
                {BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION, CONTINUOUS_REGRESSION}
            ),
        ),
        ModelFamily(
            family_id="hist_gradient_boosting",
            estimators={
                CLASSIFICATION: "sklearn.ensemble.HistGradientBoostingClassifier",
                REGRESSION: "sklearn.ensemble.HistGradientBoostingRegressor",
            },
            display_name="HistGradientBoosting",
            native_training={
                BINARY_CLASSIFICATION: frozenset({FIXED_CONFIGURATION}),
                MULTICLASS_CLASSIFICATION: frozenset({FIXED_CONFIGURATION}),
                CONTINUOUS_REGRESSION: frozenset({FIXED_CONFIGURATION}),
            },
            governed_result_problem_types=frozenset(
                {BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION, CONTINUOUS_REGRESSION}
            ),
        ),
        ModelFamily(
            family_id="decision_tree",
            estimators={
                CLASSIFICATION: "sklearn.tree.DecisionTreeClassifier",
                REGRESSION: "sklearn.tree.DecisionTreeRegressor",
            },
            display_name="Decision Tree",
            # Reaches a release only through the external fitted-model
            # (multiclass v2) lineage; Atlas-native training never fits it.
            governed_result_problem_types=frozenset({MULTICLASS_CLASSIFICATION}),
        ),
        ModelFamily(
            family_id="ridge",
            estimators={REGRESSION: "sklearn.linear_model.Ridge"},
            scale_sensitive=True,
            description="L2-regularized linear regression; scientific reproduction only.",
        ),
        ModelFamily(
            family_id="deterministic_seasonal_trend_ols",
            # Atlas's own forecasting estimator (pipeline.training), not a
            # scikit-learn estimator class resolvable by task type.
            estimators={},
            display_name="Deterministic Seasonal-Trend OLS",
            native_training={UNIVARIATE_FORECASTING: frozenset({FIXED_CONFIGURATION})},
            governed_result_problem_types=frozenset({UNIVARIATE_FORECASTING}),
            forecasting_constructor="statsmodels.regression.linear_model.OLS",
            forecasting_family_names=("DeterministicSeasonalTrendOLS",),
        ),
        ModelFamily(
            family_id="seasonal_naive",
            estimators={},
            description="Closed-form seasonal naive forecast; scientific reproduction only.",
            forecasting_family_names=("SeasonalNaive",),
        ),
        ModelFamily(
            family_id="naive_last_value",
            estimators={},
            description="Closed-form last-value forecast; scientific reproduction only.",
            forecasting_family_names=("NaiveLastValue",),
        ),
        ModelFamily(
            family_id="exponential_smoothing",
            estimators={},
            description="Holt-Winters exponential smoothing; scientific reproduction only.",
            forecasting_constructor="statsmodels.tsa.holtwinters.ExponentialSmoothing",
            forecasting_family_names=("ExponentialSmoothing",),
        ),
        ModelFamily(
            family_id="autoreg",
            estimators={},
            description="Autoregression with deterministic terms; scientific reproduction only.",
            forecasting_constructor="statsmodels.tsa.ar_model.AutoReg",
            forecasting_family_names=("AutoReg",),
        ),
        ModelFamily(
            family_id="sarimax",
            estimators={},
            description="Seasonal ARIMA state-space model; scientific reproduction only.",
            forecasting_constructor="statsmodels.tsa.statespace.sarimax.SARIMAX",
            forecasting_family_names=("SARIMAX",),
        ),
    )
}


def native_trainable_family_ids(problem_type: str, selection_mode: str | None = None) -> tuple[str, ...]:
    """Families Atlas-native training fits for problem_type (optionally
    restricted to one selection mode), in registry order."""
    return tuple(
        family_id
        for family_id, family in MODEL_FAMILIES.items()
        if family.natively_trainable(problem_type, selection_mode)
    )


def native_trainable_family_ids_for_any(
    problem_types: Iterable[str], selection_mode: str | None = None,
) -> frozenset[str]:
    return frozenset(
        family_id
        for problem_type in problem_types
        for family_id in native_trainable_family_ids(problem_type, selection_mode)
    )


def governed_result_family_ids(problem_type: str) -> frozenset[str]:
    """Families a governed result contract accepts for problem_type."""
    return frozenset(
        family_id
        for family_id, family in MODEL_FAMILIES.items()
        if problem_type in family.governed_result_problem_types
    )


def display_names() -> dict[str, str]:
    return {
        family_id: family.display_name
        for family_id, family in MODEL_FAMILIES.items()
        if family.display_name is not None
    }


def get_family(family_id: str) -> ModelFamily:
    family = MODEL_FAMILIES.get(family_id)
    if family is None:
        raise ModelFamilyError(
            "unsupported_model_family",
            f"model family {family_id!r} is not registered in pipeline.model_families",
        )
    return family


def scientific_forecasting_family_ids() -> tuple[str, ...]:
    """Families the scientific forecasting reproduction can resolve, in registry order."""
    return tuple(family_id for family_id, family in MODEL_FAMILIES.items() if family.scientific_forecasting)


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
