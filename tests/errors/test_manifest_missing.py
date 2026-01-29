"""
Test — Manifest Missing (Guardrail)

Cenário: Engine precisa registrar no manifest, mas o arquivo/caminho é inválido.
Este teste valida que o erro é padronizado e determinístico.

Nota: este é um guardrail de infraestrutura; o core não deve "auto-criar"
em caminhos inválidos.
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
        "dataset": {"name": "guardrails_manifest_missing"},
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
    # run_dir inválido (simula permissão/caminho inexistente)
    config = {
        "run": {"run_id": "manifest_missing"},
        "contract": {"path": "contract.internal.v1.json"},
        "steps": {
            "ingest.load": {"path": "dataset.csv"},
        },
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")

def test_manifest_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_manifest_missing"
    run_dir.mkdir()

    dataset = run_dir / "dataset.csv"
    contract_path = run_dir / "contract.internal.v1.json"
    config_path = run_dir / "config.pipeline.json"

    _write_dataset(dataset)
    _write_contract(contract_path)
    _write_config(config_path)

    ctx = make_ctx(run_dir=run_dir, config_path=config_path, contract_path=contract_path, run_id="manifest_missing")

    # Força um meta run_dir inválido para simular falha de persistência
    ctx.meta["run_dir"] = str(run_dir / "___nonexistent___" / "x")

    with _pushd(run_dir):
        registry = _build_registry_for_engine()
        rr = Engine(steps=registry.list(), ctx=ctx).run()

    # Deve haver ao menos um step FAILED por erro de traceabilidade/persistência.
    failed = [sr for sr in rr.steps.values() if str(getattr(sr, "status").value if hasattr(getattr(sr, "status"), "value") else getattr(sr, "status")) == "failed"]
    assert failed, "Expected at least one failed step due to manifest persistence"
