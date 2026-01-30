"""
Test — Missing Preprocess Artifact (Guardrail)

Cenário:
- O pipeline executa ingest + split + train.single
- Porém o artefato de preprocess persistido NÃO existe
- O step dependente deve falhar explicitamente com erro canônico

Esperado:
- train.single falha com error.type = "PREPROCESS_NOT_FOUND"
- payload["error"] segue o schema canônico (AtlasErrorPayload)
- Snapshot valida estrutura + conteúdo mínimo determinístico

Observação:
Este teste inclui config de split.train_test para evitar que o split bloqueie
a execução do train.single (guardrail alvo).
"""

from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

from atlas_dataflow.core.engine.engine import Engine
from tests.e2e._helpers import make_ctx, _build_registry_for_engine, _pushd
from tests.errors._snapshot_helpers import assert_error_snapshot


def _write_dataset(path: Path) -> None:
    df = pd.DataFrame(
        {
            "age": [30, 31, 29, 28],
            "income": [1000.0, 1200.0, 900.0, 800.0],
            "churn": ["0", "1", "0", "0"],
        }
    )
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
            "optional": [],
        },
        "conformity": {"allow_extra_columns": True},
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")


def _write_config(path: Path) -> None:
    # IMPORTANTE:
    # Inclui split.train_test com seed determinístico para que o split não falhe
    # e o train.single seja executado (guardrail alvo: preprocess ausente).
    config = {
        "run": {"run_id": "missing_preprocess"},
        "contract": {"path": "contract.internal.v1.json"},
        "steps": {
            "ingest.load": {"path": "dataset.csv"},
            "split.train_test": {
                "enabled": True,
                "seed": 42,
                "test_size": 0.2,
            },
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

    ctx = make_ctx(
        run_dir=run_dir,
        config_path=config_path,
        contract_path=contract_path,
        run_id="missing_preprocess",
    )

    # IMPORTANT: NÃO salvar preprocess.joblib aqui. O objetivo do teste é validar o guardrail.
    with _pushd(run_dir):
        registry = _build_registry_for_engine()
        rr = Engine(steps=registry.list(), ctx=ctx).run()

    sr = rr.steps.get("train.single")
    assert sr is not None

    err = (sr.payload or {}).get("error")
    assert isinstance(err, dict)

    # Snapshot canônico (schema + conteúdo determinístico mínimo)
    assert_error_snapshot("missing_preprocess.error.json", err)
