"""DefaultSearchGrids v1 — grids canônicos de busca por hiperparâmetros.

No Atlas DataFlow, grids de busca não devem ser ad-hoc nem implícitos.
Este componente centraliza:
- param_grid por model_id (conservador e seguro)
- scoring padrão (explícito)
- configuração canônica de cross-validation (explícita e reprodutível)

Invariantes:
- determinístico (sem acessar dados)
- sem execução de busca / treino
- falha explícita para model_id inválido
- valida que parâmetros do grid existem no estimador
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sklearn.model_selection import StratifiedKFold

from .model_registry import ModelRegistry


@dataclass(frozen=True)
class CvConfig:
    """Configuração serializável de CV (v1).

    Nota sobre determinismo:
    - O DefaultSearchGrids define um random_state canônico.
    - Steps de treino/search podem sobrescrever esse valor via seed explícita,
      sem alterar a spec (apenas no objeto CV construído em runtime).
    """

    kind: str
    n_splits: int
    shuffle: bool
    random_state: int

    def build(self, *, seed: Optional[int] = None) -> Any:
        """Constrói o objeto de CV.

        Args:
            seed: seed explícita opcional. Se fornecida, sobrescreve o random_state
                  do CV para garantir reprodutibilidade em execução.

        Returns:
            Objeto de CV do scikit-learn.
        """
        if self.kind != "StratifiedKFold":
            raise ValueError(f"unsupported cv kind: {self.kind}")
        rs = self.random_state if seed is None else int(seed)
        return StratifiedKFold(
            n_splits=self.n_splits,
            shuffle=self.shuffle,
            random_state=rs,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "n_splits": self.n_splits,
            "shuffle": self.shuffle,
            "random_state": self.random_state,
        }


@dataclass(frozen=True)
class SearchGridSpec:
    """Especificação completa de busca para um model_id."""

    model_id: str
    param_grid: Dict[str, List[Any]]
    scoring: str
    cv: CvConfig
    version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "param_grid": {k: list(v) for k, v in self.param_grid.items()},
            "scoring": self.scoring,
            "cv": self.cv.to_dict(),
            "version": self.version,
        }


class DefaultSearchGrids:
    """Catálogo canônico de grids padrão por modelo (v1)."""

    def __init__(self, specs: Dict[str, SearchGridSpec]) -> None:
        self._specs = dict(specs)

    @classmethod
    def v1(cls, model_registry: Optional[ModelRegistry] = None) -> "DefaultSearchGrids":
        """Constrói o catálogo v1 para os modelos do ModelRegistry v1."""
        mr = model_registry or ModelRegistry.v1()

        cv = CvConfig(kind="StratifiedKFold", n_splits=5, shuffle=True, random_state=42)
        scoring = "f1"

        specs: Dict[str, SearchGridSpec] = {
            "logistic_regression": SearchGridSpec(
                model_id="logistic_regression",
                param_grid={
                    "C": [0.1, 1.0, 10.0],
                    "penalty": ["l2"],
                    "solver": ["lbfgs"],
                    "class_weight": [None, "balanced"],
                    "max_iter": [1000],
                },
                scoring=scoring,
                cv=cv,
            ),
            "random_forest": SearchGridSpec(
                model_id="random_forest",
                param_grid={
                    "n_estimators": [100, 200],
                    "max_depth": [None, 10, 20],
                    "min_samples_split": [2, 5],
                    "min_samples_leaf": [1, 2],
                },
                scoring=scoring,
                cv=cv,
            ),
            "knn": SearchGridSpec(
                model_id="knn",
                param_grid={
                    "n_neighbors": [3, 5, 7, 11],
                    "weights": ["uniform", "distance"],
                    "p": [1, 2],
                },
                scoring=scoring,
                cv=cv,
            ),
        }

        # Valida que cobrimos todos os modelos suportados (v1)
        for mid in mr.list_ids():
            if mid not in specs:
                raise ValueError(f"missing default grid for model_id: {mid}")

        # Valida que todos os params existem no estimador
        for mid, spec in specs.items():
            estimator = mr.build(mid)
            est_params = estimator.get_params(deep=True)
            for p in spec.param_grid.keys():
                if p not in est_params:
                    raise ValueError(f"grid param '{p}' not found in estimator params for model_id '{mid}'")

        return cls(specs)

    def list(self) -> List[str]:
        return sorted(self._specs.keys())

    def get(self, model_id: str) -> SearchGridSpec:
        if model_id not in self._specs:
            raise KeyError(f"unknown model_id: {model_id}")
        return self._specs[model_id]
