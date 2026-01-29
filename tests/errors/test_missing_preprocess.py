"""
Test — Missing Preprocess Artifact (Guardrail)

Cenário: etapa dependente tenta carregar preprocess persistido mas ele não existe.
Esperado: o Step falha com error.type="PREPROCESS_NOT_FOUND" (sem auto-correção).
"""

from pathlib import Path
import json
import pandas as pd

from tests.e2e._helpers import make_ctx, _build_registry_for_engine, _pushd
from atlas_dataflow.core.engine.engine import Engine

def _write_dataset(path: Path) -> None:
    df = pd.DataFrame({
        "age": [30, 31, 29, 28],
        "income": [1000.0, 1200.0, 900.0, 800.0],
        "churn": ["0", "1", "0", "0"],
    })
    df.to_csv(path, index=False)

def _write_contract(path: Path) -> None:
    contract = {
        "contract_version": "internal.v1",
        "dataset": {"name": "guardrails_missing_preprocess"},
        "target": {"name": "churn"},
        "features": {
            "required": [
                {"name": "age", "dtype": "int64"},
                {"name": "income", "dtype": "float64"},
            ],
            "optional": []
        },
        "conformity": {
            "allow_extra_columns": True
        }
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

def _write_config(path: Path) -> None:
    config = {
        "run": {"run_id": "missing_preprocess"},
        "contract": {"path": "contract.internal.v1.json"},
        "steps": {
            "ingest.load": {"path": "dataset.csv"},
            "train.single": {
                "enabled": True,
                "model_id": "logistic_regression",
                "seed": 42,
            },
        },
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")

def test_missing_preprocess(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_missing_preprocess"
    run_dir.mkdir()

    dataset = run_dir / "dataset.csv"
    contract_path = run_dir / "contract.internal.v1.json"
    config_path = run_dir / "config.pipeline.json"

    _write_dataset(dataset)
    _write_contract(contract_path)
    _write_config(config_path)

    ctx = make_ctx(run_dir=run_dir, config_path=config_path, contract_path=contract_path, run_id="missing_preprocess")

    # IMPORTANT: NÃO salvar preprocess.joblib aqui. O objetivo do teste é validar o guardrail.
    with _pushd(run_dir):
        registry = _build_registry_for_engine()
        rr = Engine(steps=registry.list(), ctx=ctx).run()

    sr = rr.steps.get("train.single")
    assert sr is not None
    err = (sr.payload or {}).get("error")
    assert isinstance(err, dict)
    assert err.get("type") == "PREPROCESS_NOT_FOUND"
