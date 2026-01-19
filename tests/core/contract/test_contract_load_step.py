from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.contract.load import ContractLoadStep


def _minimal_contract_v1() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "churn", "type": "classification"},
        "target": {"name": "target", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "age",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            }
        ],
    }


def test_contract_load_success(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        """
contract_version: '1.0'
problem:
  name: churn
  type: classification
target:
  name: target
  dtype: int
  allowed_null: false
features:
  - name: age
    role: numerical
    dtype: int
    required: true
    allowed_null: false
""".lstrip(),
        encoding="utf-8",
    )

    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={"contract": {"path": str(contract_path)}},
        contract={},
        meta={},
    )

    step = ContractLoadStep()
    sr = step.run(ctx)

    assert sr.status == StepStatus.SUCCESS
    assert isinstance(ctx.contract, dict)
    assert ctx.contract.get("contract_version") == "1.0"
    assert sr.payload["contract"]["path"].endswith("contract.yaml")
    assert len(sr.payload["contract"]["hash"]) == 64


def test_contract_load_missing_path() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract={},
        meta={},
    )

    sr = ContractLoadStep().run(ctx)
    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "ContractPathMissingError"


def test_contract_load_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={"contract": {"path": str(missing)}},
        contract={},
        meta={},
    )

    sr = ContractLoadStep().run(ctx)
    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "ContractFileNotFoundError"


def test_contract_load_invalid_parse(tmp_path: Path) -> None:
    contract_path = tmp_path / "bad.yaml"
    contract_path.write_text("contract_version: [", encoding="utf-8")

    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={"contract": {"path": str(contract_path)}},
        contract={},
        meta={},
    )

    sr = ContractLoadStep().run(ctx)
    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "ContractParseError"


def test_contract_load_invalid_schema(tmp_path: Path) -> None:
    # missing problem.name
    contract = {
        "contract_version": "1.0",
        "problem": {"type": "classification"},
        "target": {"name": "target", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "age",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            }
        ],
    }

    contract_path = tmp_path / "contract.json"
    import json

    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={"contract": {"path": str(contract_path)}},
        contract={},
        meta={},
    )

    sr = ContractLoadStep().run(ctx)
    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "ContractValidationError"
