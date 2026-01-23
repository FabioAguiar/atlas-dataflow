from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess


def _contract_v1() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "x", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "float", "required": True, "allowed_null": True},
            {"name": "income", "role": "numerical", "dtype": "float", "required": False, "allowed_null": True},
            {"name": "country", "role": "categorical", "dtype": "string", "required": False, "allowed_null": True},
            {"name": "gender", "role": "categorical", "dtype": "string", "required": False, "allowed_null": True},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }


def _config_preprocess_standard_onehot() -> dict:
    return {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["age", "income"], "scaler": "standard"},
                "categorical": {
                    "columns": ["country", "gender"],
                    "encoder": "onehot",
                    "handle_unknown": "ignore",
                    "drop": None,
                },
            }
        }
    }


def test_builder_constructs_columntransformer_with_declared_columns():
    ct = build_representation_preprocess(contract=_contract_v1(), config=_config_preprocess_standard_onehot())

    # nomes dos transformers são canônicos e ordem é determinística
    names = [t[0] for t in ct.transformers]
    assert names == ["numeric", "categorical"]

    # colunas são respeitadas exatamente como declaradas
    assert list(ct.transformers[0][2]) == ["age", "income"]
    assert list(ct.transformers[1][2]) == ["country", "gender"]


def test_fit_transform_train_and_transform_test_have_consistent_shape():
    ct = build_representation_preprocess(contract=_contract_v1(), config=_config_preprocess_standard_onehot())

    X_train = pd.DataFrame(
        {
            "age": [10.0, 20.0, 30.0],
            "income": [1000.0, 2000.0, 3000.0],
            "country": ["BR", "US", "BR"],
            "gender": ["M", "F", "F"],
        }
    )
    X_test = pd.DataFrame(
        {
            "age": [40.0, 50.0],
            "income": [4000.0, 5000.0],
            "country": ["BR", "CA"],  # unseen (handle_unknown=ignore)
            "gender": ["M", "F"],
        }
    )

    Xt_train = ct.fit_transform(X_train)
    Xt_test = ct.transform(X_test)

    assert Xt_train.shape[1] == Xt_test.shape[1]
    assert Xt_train.shape[0] == 3
    assert Xt_test.shape[0] == 2

    # saída numérica finita (scaler) + onehot denso
    assert np.isfinite(Xt_train).all()
    assert np.isfinite(Xt_test).all()


def test_fail_when_column_not_in_contract():
    cfg = _config_preprocess_standard_onehot()
    cfg["representation"]["preprocess"]["numeric"]["columns"] = ["age", "unknown_col"]

    with pytest.raises(ValueError):
        build_representation_preprocess(contract=_contract_v1(), config=cfg)


def test_fail_when_role_mismatch_between_contract_and_config():
    cfg = _config_preprocess_standard_onehot()
    # 'country' é categórica no contrato, não pode entrar como numérica
    cfg["representation"]["preprocess"]["numeric"]["columns"] = ["age", "country"]

    with pytest.raises(ValueError):
        build_representation_preprocess(contract=_contract_v1(), config=cfg)


def test_fail_when_invalid_scaler_or_encoder():
    cfg = _config_preprocess_standard_onehot()
    cfg["representation"]["preprocess"]["numeric"]["scaler"] = "robust"  # não suportado (v1)
    with pytest.raises(ValueError):
        build_representation_preprocess(contract=_contract_v1(), config=cfg)
