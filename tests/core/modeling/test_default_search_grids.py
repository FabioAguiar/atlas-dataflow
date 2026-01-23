"""Testes unitários — DefaultSearchGrids v1.

Cobre:
- existência de grids para todos os modelos do ModelRegistry v1
- validação de parâmetros do grid contra get_params() do estimador
- scoring explícito
- cv explícito e reprodutível (StratifiedKFold com seed)
- falha explícita para model_id inválido
- payload serializável via to_dict()
"""

from __future__ import annotations

import pytest

from atlas_dataflow.modeling.model_registry import ModelRegistry
from atlas_dataflow.modeling.default_search_grids import DefaultSearchGrids


def test_grids_exist_for_all_models():
    mr = ModelRegistry.v1()
    grids = DefaultSearchGrids.v1(model_registry=mr)

    assert set(grids.list()) == set(mr.list_ids())


def test_grid_params_exist_in_estimators():
    mr = ModelRegistry.v1()
    grids = DefaultSearchGrids.v1(model_registry=mr)

    for model_id in grids.list():
        spec = grids.get(model_id)
        est = mr.build(model_id)
        params = est.get_params(deep=True)
        for p in spec.param_grid.keys():
            assert p in params, f"param '{p}' missing for model_id '{model_id}'"


def test_scoring_and_cv_are_explicit_and_deterministic():
    grids = DefaultSearchGrids.v1()

    for model_id in grids.list():
        spec = grids.get(model_id)
        assert spec.scoring in {"f1", "roc_auc", "accuracy"}
        cv = spec.cv.build()
        assert cv.n_splits == 5
        assert cv.shuffle is True
        assert cv.random_state == 42


def test_invalid_model_id_fails_explicitly():
    grids = DefaultSearchGrids.v1()
    with pytest.raises(KeyError):
        grids.get("does_not_exist")


def test_to_dict_is_serializable_structure():
    grids = DefaultSearchGrids.v1()
    d = grids.get("logistic_regression").to_dict()

    assert isinstance(d, dict)
    assert d["model_id"] == "logistic_regression"
    assert isinstance(d["param_grid"], dict)
    assert isinstance(d["cv"], dict)
    assert d["version"] == "v1"
