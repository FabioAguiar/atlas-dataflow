"""
ModelRegistry v1 — catálogo determinístico de modelos supervisionados.

No Atlas DataFlow, modelos suportados, parâmetros padrão e parâmetros expostos para UI
devem ser centralizados e explícitos — sem inferência dinâmica.

Este módulo fornece:
- ParamSpec: schema de parâmetros ajustáveis (UI)
- ModelSpec: especificação de um modelo suportado
- ModelRegistry: ponto único de verdade para modelos (v1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional, Type

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier


ParamDType = Literal["int", "float", "bool", "enum"]


@dataclass(frozen=True)
class ParamSpec:
    """Especifica um parâmetro permitido para UI/experimentação (não executa tuning)."""

    dtype: ParamDType
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[List[Any]] = None
    allow_none: bool = False
    description: str = ""


@dataclass(frozen=True)
class ModelSpec:
    """Especificação canônica de um modelo suportado pelo registry."""

    model_id: str
    estimator_cls: Type[Any]
    default_params: Dict[str, Any] = field(default_factory=dict)
    ui_params: Dict[str, ParamSpec] = field(default_factory=dict)
    version: str = "v1"

    def build(self, overrides: Optional[Dict[str, Any]] = None) -> Any:
        """Instancia o estimador com default_params + overrides.

        Não treina, não valida, não inspeciona dados.
        """
        params = dict(self.default_params)
        if overrides:
            params.update(overrides)
        return self.estimator_cls(**params)


class ModelRegistry:
    """Registry determinístico de ModelSpec.

    Extensibilidade é explícita: novos modelos podem ser registrados via `register()`.
    Não há discovery automático e não há inferência baseada em dados.
    """

    def __init__(self, specs: Optional[Iterable[ModelSpec]] = None):
        self._specs: Dict[str, ModelSpec] = {}
        if specs:
            for s in specs:
                self.register(s)

    @classmethod
    def v1(cls) -> "ModelRegistry":
        """Factory do catálogo v1 (LR, RF, KNN)."""
        return cls(specs=_default_specs_v1())

    def register(self, spec: ModelSpec) -> None:
        if not isinstance(spec, ModelSpec):
            raise TypeError("spec must be a ModelSpec")
        if not isinstance(spec.model_id, str) or not spec.model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        if spec.model_id in self._specs:
            raise ValueError(f"model_id already registered: {spec.model_id}")
        self._specs[spec.model_id] = spec

    def list_ids(self) -> List[str]:
        return sorted(self._specs.keys())

    def get(self, model_id: str) -> ModelSpec:
        if model_id not in self._specs:
            raise KeyError(f"unknown model_id: {model_id}")
        return self._specs[model_id]

    def build(self, model_id: str, overrides: Optional[Dict[str, Any]] = None) -> Any:
        """Instancia um estimador (sem treinar)."""
        return self.get(model_id).build(overrides=overrides)


def _default_specs_v1() -> List[ModelSpec]:
    """Catálogo v1: LogisticRegression, RandomForestClassifier, KNeighborsClassifier."""
    lr_ui = {
        "C": ParamSpec(dtype="float", default=1.0, min=1e-4, max=100.0, description="Inverse regularization strength"),
        "max_iter": ParamSpec(dtype="int", default=1000, min=50, max=10000, description="Max iterations"),
        "solver": ParamSpec(dtype="enum", default="lbfgs", choices=["lbfgs", "liblinear"], description="Solver"),
    }

    rf_ui = {
        "n_estimators": ParamSpec(dtype="int", default=200, min=10, max=1000, description="Number of trees"),
        "max_depth": ParamSpec(dtype="int", default=None, min=1, max=100, allow_none=True, description="Max depth"),
        "min_samples_split": ParamSpec(dtype="int", default=2, min=2, max=50, description="Min samples to split"),
        "min_samples_leaf": ParamSpec(dtype="int", default=1, min=1, max=50, description="Min samples per leaf"),
    }

    knn_ui = {
        "n_neighbors": ParamSpec(dtype="int", default=5, min=1, max=100, description="Number of neighbors"),
        "weights": ParamSpec(dtype="enum", default="uniform", choices=["uniform", "distance"], description="Weight function"),
        "p": ParamSpec(dtype="int", default=2, min=1, max=2, description="Minkowski distance power"),
    }

    lr = ModelSpec(
        model_id="logistic_regression",
        estimator_cls=LogisticRegression,
        default_params={
            "C": 1.0,
            "max_iter": 1000,
            "solver": "lbfgs",
        },
        ui_params=lr_ui,
    )

    rf = ModelSpec(
        model_id="random_forest",
        estimator_cls=RandomForestClassifier,
        default_params={
            "n_estimators": 200,
            "random_state": 42,
            "n_jobs": 1,
        },
        ui_params=rf_ui,
    )

    knn = ModelSpec(
        model_id="knn",
        estimator_cls=KNeighborsClassifier,
        default_params={
            "n_neighbors": 5,
        },
        ui_params=knn_ui,
    )

    return [lr, rf, knn]
