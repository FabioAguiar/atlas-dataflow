import json
from pathlib import Path

import pandas as pd
import yaml

from tests.e2e._helpers import (
    assert_core_artifacts,
    assert_reports_equal,
    create_run_dir,
    run_pipeline,
)


def _write_bank_dataset(path: Path) -> None:
    df = pd.DataFrame(
        {
            "customer_id": [f"B{i:03d}" for i in range(1, 21)],
            "age": [30 + i for i in range(20)],
            "balance": [1000.0 + i * 250.0 for i in range(20)],
            "num_products": [1, 2] * 10,
            # Mantém como numérico 0/1 (representation.preprocess v1 só trata numerical/categorical)
            "is_active_member": [0, 1] * 10,
            "exited": [0, 1] * 10,
        }
    )
    df.to_csv(path, index=False)


def _write_bank_contract(path: Path) -> None:
    contract = {
        "contract_version": "1.0",
        "problem": {"name": "bank_churn", "type": "classification"},
        "target": {"name": "exited", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "age",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "balance",
                "role": "numerical",
                "dtype": "float",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "num_products",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "is_active_member",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            },
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")


def _write_bank_config(path: Path, dataset_path: Path, contract_path: Path) -> None:
    """Config E2E mínima alinhada ao core real, com determinismo.

    Regras (mesmas do Telco-like):
    - Paths devem ser RELATIVOS ao run_dir para evitar diferença entre Run A e Run B.
    - SplitTrainTestStep exige steps.split.train_test.seed.
    - TrainSingleStep exige model_id e seed.
    - EvaluateModelSelectionStep exige target_metric.
    """
    # IMPORTANTE: paths relativos ao run_dir (onde config.yml está)
    rel_dataset = dataset_path.name  # "bank_like.csv"
    rel_contract = contract_path.name  # "contract.internal.v1.json"

    config = {
        "run": {"run_id": "bank_like_e2e"},
        "contract": {"path": rel_contract},
        "steps": {
            # Ingest (path relativo)
            "ingest.load": {"path": rel_dataset},
            # Split (determinismo explícito via seed; stratify explícito)
            "split.train_test": {
                "test_size": 0.25,
                "seed": 42,
                "stratify": {"enabled": True, "column": "exited"},
            },
            # Train (model_id e seed explícitos)
            "train.single": {
                "enabled": True,
                "model_id": "logistic_regression",
                "seed": 42,
                "params": {"max_iter": 200},
            },
            # Evaluate (model_selection exige target_metric)
            "evaluate.model_selection": {
                "enabled": True,
                "target_metric": "f1",
                "mode": "max",
            },
        },
        # Obrigatório para o builder representation.preprocess (sem inferência)
        "representation": {
            "preprocess": {
                "numeric": {
                    "columns": ["age", "balance", "num_products", "is_active_member"],
                    "scaler": "standard",
                },
                # Sem categóricas neste cenário (válido; ColumnTransformer usa apenas numeric)
                "categorical": {
                    "columns": [],
                    "encoder": "onehot",
                    "handle_unknown": "ignore",
                    "drop": None,
                },
            }
        },
        # Mantém compatibilidade com export/reporting quando existir no core
        "export": {"pdf_engine": "reportlab"},
    }

    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_pipeline_bank_like_e2e(tmp_path: Path) -> None:
    # Run A
    run_dir_a = create_run_dir(tmp_path, "run_bank_like_a")
    dataset_a = run_dir_a / "bank_like.csv"
    contract_a = run_dir_a / "contract.internal.v1.json"
    config_a = run_dir_a / "config.pipeline.yml"

    _write_bank_dataset(dataset_a)
    _write_bank_contract(contract_a)
    _write_bank_config(config_a, dataset_a, contract_a)

    run_pipeline(run_dir=run_dir_a, config_path=config_a, contract_path=contract_a, run_id="bank_like_e2e")
    assert_core_artifacts(run_dir_a)

    # Run B (determinismo)
    run_dir_b = create_run_dir(tmp_path, "run_bank_like_b")
    dataset_b = run_dir_b / "bank_like.csv"
    contract_b = run_dir_b / "contract.internal.v1.json"
    config_b = run_dir_b / "config.pipeline.yml"

    _write_bank_dataset(dataset_b)
    _write_bank_contract(contract_b)
    _write_bank_config(config_b, dataset_b, contract_b)

    run_pipeline(run_dir=run_dir_b, config_path=config_b, contract_path=contract_b, run_id="bank_like_e2e")
    assert_core_artifacts(run_dir_b)

    # report.md precisa ser determinístico (após normalização no helper)
    assert_reports_equal(run_dir_a, run_dir_b)
