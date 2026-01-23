from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.traceability.manifest import create_manifest
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _contract_minimal() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "demo", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {"name": "age", "role": "numerical", "dtype": "int", "required": True, "allowed_null": False},
            {"name": "income", "role": "numerical", "dtype": "float", "required": True, "allowed_null": False},
            {"name": "country", "role": "categorical", "dtype": "category", "required": True, "allowed_null": False},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }


def _config_minimal() -> dict:
    return {
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["age", "income"], "scaler": "standard"},
                "categorical": {"columns": ["country"], "encoder": "onehot", "handle_unknown": "ignore", "drop": None},
            }
        }
    }


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [10, 20, 30, 40],
            "income": [100.0, 200.0, 150.0, 300.0],
            "country": ["BR", "US", "BR", "CA"],
        }
    )


def test_preprocess_persist_and_round_trip_transform_is_identical(tmp_path):
    contract = _contract_minimal()
    config = _config_minimal()
    df = _dataset()

    pre = build_representation_preprocess(contract=contract, config=config)

    # fit only on "train" (primeiras 3 linhas) e transforma um conjunto fixo
    X_train = df.iloc[:3]
    X_fixed = df.iloc[1:4]

    pre.fit(X_train)
    y1 = pre.transform(X_fixed)

    manifest = create_manifest(
        run_id="r1",
        started_at=datetime.now(timezone.utc),
        atlas_version="0.0",
        config_hash="",
        contract_hash="",
    )

    store = PreprocessStore(run_dir=tmp_path)
    meta = store.save(preprocess=pre, manifest=manifest)

    # metadata registrada
    assert meta["type"] == "preprocess"
    assert meta["format"] == "joblib"
    assert meta["path"] == "artifacts/preprocess.joblib"
    assert meta["builder"] == "representation.preprocess"
    assert meta["version"] == "v1"

    # Manifest registra evento explícito
    ev = [e for e in manifest.events if e.get("event_type") == "artifact_saved"]
    assert len(ev) == 1
    assert ev[0]["payload"]["artifact"]["path"] == "artifacts/preprocess.joblib"

    # Round-trip: load + transform deve ser idêntico
    loaded = store.load()
    y2 = loaded.transform(X_fixed)

    assert isinstance(y1, np.ndarray)
    assert isinstance(y2, np.ndarray)
    assert y1.shape == y2.shape
    assert np.allclose(y1, y2)


def test_preprocess_load_fails_when_artifact_missing(tmp_path):
    store = PreprocessStore(run_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        _ = store.load()
