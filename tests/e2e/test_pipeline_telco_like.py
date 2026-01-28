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


def _write_telco_dataset(path: Path) -> None:
    df = pd.DataFrame(
        {
            "customer_id": [f"C{i:03d}" for i in range(1, 21)],
            "tenure": list(range(1, 21)),
            "monthly_charges": [50.0 + i for i in range(20)],
            "contract_type": ["month-to-month", "one-year"] * 10,
            "internet_service": ["dsl", "fiber"] * 10,
            "churn": [0, 1] * 10,
        }
    )
    df.to_csv(path, index=False)


def _write_telco_contract(path: Path) -> None:
    contract = {
        "contract_version": "1.0",
        "problem": {"name": "telco_churn", "type": "classification"},
        "target": {"name": "churn", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "tenure",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "monthly_charges",
                "role": "numerical",
                "dtype": "float",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "contract_type",
                "role": "categorical",
                "dtype": "category",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "internet_service",
                "role": "categorical",
                "dtype": "category",
                "required": True,
                "allowed_null": False,
            },
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")


def _write_telco_config(path: Path, dataset_path: Path, contract_path: Path) -> None:
    """Config E2E mínima alinhada ao core real, com determinismo.

    Regras:
    - Paths devem ser RELATIVOS ao run_dir para evitar diferença de hash/config/report entre Run A e Run B.
    - SplitTrainTestStep exige steps.split.train_test.seed (não lê run.seed).
    - TrainSingleStep exige model_id e seed em steps.train.single (determinismo).
    - EvaluateModelSelectionStep exige target_metric.
    """
    # IMPORTANTE: paths relativos ao run_dir (onde config.yml está)
    rel_dataset = dataset_path.name  # "telco_like.csv"
    rel_contract = contract_path.name  # "contract.internal.v1.json"

    config = {
        "run": {"run_id": "telco_like_e2e"},
        "contract": {"path": rel_contract},
        "steps": {
            # Ingest (path relativo)
            "ingest.load": {"path": rel_dataset},
            # Split (determinismo explícito via seed; stratify explícito)
            "split.train_test": {
                "test_size": 0.25,
                "seed": 42,
                "stratify": {"enabled": True, "column": "churn"},
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
                "numeric": {"columns": ["tenure", "monthly_charges"], "scaler": "standard"},
                "categorical": {
                    "columns": ["contract_type", "internet_service"],
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


def test_pipeline_telco_like_e2e(tmp_path: Path) -> None:
    # Run A
    run_dir_a = create_run_dir(tmp_path, "run_telco_like_a")
    dataset_a = run_dir_a / "telco_like.csv"
    contract_a = run_dir_a / "contract.internal.v1.json"
    config_a = run_dir_a / "config.pipeline.yml"

    _write_telco_dataset(dataset_a)
    _write_telco_contract(contract_a)
    _write_telco_config(config_a, dataset_a, contract_a)

    run_pipeline(run_dir=run_dir_a, config_path=config_a, contract_path=contract_a, run_id="telco_like_e2e")
    assert_core_artifacts(run_dir_a)

    # Run B (determinismo)
    run_dir_b = create_run_dir(tmp_path, "run_telco_like_b")
    dataset_b = run_dir_b / "telco_like.csv"
    contract_b = run_dir_b / "contract.internal.v1.json"
    config_b = run_dir_b / "config.pipeline.yml"

    _write_telco_dataset(dataset_b)
    _write_telco_contract(contract_b)
    _write_telco_config(config_b, dataset_b, contract_b)

    run_pipeline(run_dir=run_dir_b, config_path=config_b, contract_path=contract_b, run_id="telco_like_e2e")
    assert_core_artifacts(run_dir_b)

    # report.md precisa ser determinístico (após normalização no helper)
    assert_reports_equal(run_dir_a, run_dir_b)
