"""Common helpers for Atlas DataFlow end-to-end tests.

This module centralizes boilerplate required by E2E scenarios:
- run_dir creation
- config / contract / dataset materialization
- engine execution
- artifact assertions

It intentionally uses ONLY public APIs from the core.

NOTE:
- O Atlas DataFlow atual NÃO expõe `RunContext.from_config()`.
  Nos E2E, construímos o RunContext a partir de:
    - config efetiva: `load_config(defaults_path=..., local_path=None)`
    - contrato: JSON (contract.internal.v1.json)
  e executamos o pipeline via `ctx.build_steps()` + `Engine`.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.config.loader import load_config
from atlas_dataflow.core.engine.engine import Engine
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def create_run_dir(base_tmp: Path, name: str) -> Path:
    run_dir = base_tmp / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def make_ctx(*, run_dir: Path, config_path: Path, contract_path: Path, run_id: str) -> RunContext:
    config = load_config(defaults_path=str(config_path), local_path=None)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    return RunContext(
        run_id=run_id,
        created_at=datetime.now(timezone.utc),
        run_dir=run_dir,
        config=config,
        contract=contract,
        meta={},
    )


def run_pipeline(*, run_dir: Path, config_path: Path, contract_path: Path, run_id: str) -> RunContext:
    ctx = make_ctx(run_dir=run_dir, config_path=config_path, contract_path=contract_path, run_id=run_id)
    preprocess = build_representation_preprocess(ctx=ctx)
    PreprocessStore(run_dir=run_dir).save(preprocess)
    steps = ctx.build_steps()
    Engine(steps=steps, ctx=ctx).run()
    return ctx


def assert_core_artifacts(run_dir: Path) -> None:
    artifacts_dir = run_dir / "artifacts"
    assert artifacts_dir.exists()
    assert (artifacts_dir / "preprocess.joblib").exists()
    assert (artifacts_dir / "report.md").exists()
    assert (artifacts_dir / "inference_bundle").exists() or (artifacts_dir / "inference_bundle.joblib").exists()


def assert_reports_equal(run_dir_a: Path, run_dir_b: Path) -> None:
    report_a = (run_dir_a / "artifacts" / "report.md").read_text(encoding="utf-8")
    report_b = (run_dir_b / "artifacts" / "report.md").read_text(encoding="utf-8")
    assert report_a == report_b
