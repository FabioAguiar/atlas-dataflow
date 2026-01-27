import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.config.loader import load_config
from atlas_dataflow.core.engine.engine import Engine
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _write_bank_dataset(path: Path) -> None:
    df = pd.DataFrame(
        {
            "customer_id": [f"B{i:03d}" for i in range(1, 21)],
            "age": [30 + i for i in range(20)],
            "balance": [1000 + i * 250 for i in range(20)],
            "num_products": [1, 2] * 10,
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
            {"name": "age", "role": "numerical", "dtype": "int", "required": True, "allowed_null": False},
            {"name": "balance", "role": "numerical", "dtype": "float", "required": True, "allowed_null": False},
            {"name": "num_products", "role": "numerical", "dtype": "int", "required": True, "allowed_null": False},
            {"name": "is_active_member", "role": "boolean", "dtype": "bool", "required": True, "allowed_null": False},
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")


def _write_bank_config(path: Path, dataset_path: Path, contract_path: Path) -> None:
    config = {
        "run": {"run_id": "bank_like_e2e", "seed": 42},
        "dataset": {"path": str(dataset_path), "format": "csv"},
        "contract": {"path": str(contract_path)},
        "pipeline": {
            "steps": [
                "ingest.load",
                "contract.load",
                "contract.conformity_report",
                "transform.apply_defaults",
                "transform.cast_types_safe",
                "transform.categorical_standardize",
                "transform.impute_missing",
                "transform.split_train_test",
                "train.single",
                "evaluate.metrics",
                "export.inference_bundle",
                "export.report_md",
            ]
        },
        "train": {"mode": "single", "estimator": {"name": "logistic_regression", "params": {"max_iter": 200}}},
        "split": {"test_size": 0.25, "random_state": 42, "stratify": True},
        "export": {"pdf_engine": "reportlab"},
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _make_ctx(*, run_dir: Path, config_path: Path, contract_path: Path, run_id: str) -> RunContext:
    config = load_config(defaults_path=str(config_path), local_path=None)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    return RunContext(
        run_id=run_id,
        created_at=datetime.now(timezone.utc),
        config=config,
        contract=contract,
        meta={"run_dir": str(run_dir)},
    )


def test_pipeline_bank_like_e2e(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_bank_like"
    run_dir.mkdir()

    dataset_path = run_dir / "bank_like.csv"
    contract_path = run_dir / "contract.internal.v1.json"
    config_path = run_dir / "config.pipeline.yml"

    _write_bank_dataset(dataset_path)
    _write_bank_contract(contract_path)
    _write_bank_config(config_path, dataset_path, contract_path)

    ctx = _make_ctx(
        run_dir=run_dir,
        config_path=config_path,
        contract_path=contract_path,
        run_id="bank_like_e2e",
    )

    preprocess = build_representation_preprocess(ctx=ctx)
    PreprocessStore(run_dir=run_dir).save(preprocess)

    steps = ctx.build_steps()
    result = Engine(steps=steps, ctx=ctx).run()

    assert result is not None

    artifacts_dir = run_dir / "artifacts"
    assert artifacts_dir.exists()
    assert (artifacts_dir / "report.md").exists()

    bundle_dir = artifacts_dir / "inference_bundle"
    bundle_file = artifacts_dir / "inference_bundle.joblib"
    assert bundle_dir.exists() or bundle_file.exists()
