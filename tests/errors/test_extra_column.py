"""
Test — Extra Column Forbidden (Guardrail)

Cenário: dataset contém coluna extra e o contrato proíbe extras.
Esperado: contract.load falha explicitamente com payload["error"] canônico.
"""

from pathlib import Path
import json
import pandas as pd


from tests.e2e._helpers import make_ctx, _build_registry_for_engine, _pushd, write_json
from atlas_dataflow.core.engine.engine import Engine
from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _write_dataset(path: Path) -> None:
    df = pd.DataFrame({
        "age": [30, 31, 29],
        "income": [1000.0, 1200.0, 900.0],
        "unexpected": ["x", "y", "z"],  # extra
        "churn": ["0", "1", "0"],
    })
    df.to_csv(path, index=False)

def _write_contract(path: Path) -> None:
    contract = {
        "contract_version": "internal.v1",
        "dataset": {"name": "guardrails_extra_column"},
        "target": {"name": "churn"},
        "features": {
            "required": [
                {"name": "age", "dtype": "int64"},
                {"name": "income", "dtype": "float64"},
            ],
            "optional": []
        },
        "conformity": {
            "allow_extra_columns": False
        }
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

def _write_config(path: Path) -> None:
    config = {
        "run": {"run_id": "extra_column"},
        "contract": {"path": "contract.internal.v1.json"},
        "steps": {
            "ingest.load": {"path": "dataset.csv"},
            "contract.load": {"enabled": True},
        },
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")

def test_extra_column_forbidden(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_extra_column"
    run_dir.mkdir()

    dataset = run_dir / "dataset.csv"
    contract_path = run_dir / "contract.internal.v1.json"
    config_path = run_dir / "config.pipeline.json"

    _write_dataset(dataset)
    _write_contract(contract_path)
    _write_config(config_path)

    ctx = make_ctx(run_dir=run_dir, config_path=config_path, contract_path=contract_path, run_id="extra_column")
    preprocess = build_representation_preprocess(contract=ctx.contract, config=ctx.config)
    PreprocessStore(run_dir=run_dir).save(preprocess=preprocess)

    with _pushd(run_dir):
        registry = _build_registry_for_engine()
        rr = Engine(steps=registry.list(), ctx=ctx).run()

    sr = rr.steps.get("contract.load")
    assert sr is not None
    err = (sr.payload or {}).get("error")
    assert isinstance(err, dict)
    assert "type" in err and "message" in err and "details" in err
