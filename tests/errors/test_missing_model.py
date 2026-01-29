"""
Test — Missing Model Artifact (Guardrail)

Cenário: export.inference_bundle exige um modelo treinado no RunContext, mas não há.
Esperado: o Step falha com error.type="MODEL_NOT_FOUND".
"""

from pathlib import Path
import json

import pandas as pd

from atlas_dataflow.core.run_context import RunContext
from atlas_dataflow.steps.export.inference_bundle import ExportInferenceBundleStep
from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.persistence.preprocess_store import PreprocessStore

def _write_dataset(path: Path) -> None:
    df = pd.DataFrame({
        "age": [30, 31, 29, 28],
        "income": [1000.0, 1200.0, 900.0, 800.0],
        "churn": ["0", "1", "0", "0"],
    })
    df.to_csv(path, index=False)

def test_missing_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_missing_model"
    run_dir.mkdir()
    (run_dir / "artifacts").mkdir()

    dataset = run_dir / "dataset.csv"
    _write_dataset(dataset)

    contract = {
        "contract_version": "internal.v1",
        "dataset": {"name": "guardrails_missing_model"},
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

    config = {
        "run": {"run_id": "missing_model"},
        "steps": {
            "export.inference_bundle": {"enabled": True, "format": "joblib"}
        },
    }

    ctx = RunContext(run_id="missing_model", created_at="now", config=config, contract=contract, meta={"run_dir": str(run_dir)})

    # Preprocess existe (para não falhar antes)
    preprocess = build_representation_preprocess(contract=contract, config={"steps": {"preprocess": {"type": "standard_onehot"}}})
    PreprocessStore(run_dir=run_dir).save(preprocess=preprocess)

    # Artifacts mínimos exigidos por export.inference_bundle
    ctx.set_artifact("eval.model_selection", {"selection": {"champion_model_id": "logistic_regression"}})
    ctx.set_artifact("eval.metrics", {"model_id": "logistic_regression", "metrics": {"accuracy": 0.5}})

    step = ExportInferenceBundleStep()
    sr = step.run(ctx)
    err = (sr.payload or {}).get("error")
    assert isinstance(err, dict)
    assert err.get("type") == "MODEL_NOT_FOUND"
