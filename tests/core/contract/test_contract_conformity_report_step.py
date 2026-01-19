from __future__ import annotations

from datetime import datetime, timezone

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.contract.conformity_report import ContractConformityReportStep


def _contract_v1_with_categories() -> dict:
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
            },
            {
                "name": "segment",
                "role": "categorical",
                "dtype": "category",
                "required": False,
                "allowed_null": False,
            },
        ],
        "categories": {
            "segment": {
                "allowed": ["A", "B"],
                "normalization": {"type": "none"},
            }
        },
    }


def test_conformity_missing_required_column() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1_with_categories(),
        meta={},
    )
    # Dataset sem a coluna obrigatória "age" e sem target
    ctx.set_artifact("data.raw_rows", [{"segment": "A"}])

    sr = ContractConformityReportStep().run(ctx)
    assert sr.status == StepStatus.SUCCESS
    assert "age" in sr.payload["missing_columns"]
    assert "target" in sr.payload["missing_columns"]
    dr = sr.payload["decisions_required"]
    assert any(d["code"] == "MISSING_REQUIRED_COLUMNS" and d["severity"] == "error" for d in dr)


def test_conformity_extra_column_present() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1_with_categories(),
        meta={},
    )
    ctx.set_artifact("data.raw_rows", [{"age": "10", "segment": "A", "target": "1", "foo": "x"}])

    sr = ContractConformityReportStep().run(ctx)
    assert sr.status == StepStatus.SUCCESS
    assert "foo" in sr.payload["extra_columns"]
    assert any(d["code"] == "EXTRA_COLUMNS" for d in sr.payload["decisions_required"])


def test_conformity_dtype_divergent_and_blocking() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1_with_categories(),
        meta={},
    )
    # age esperado int, mas vem com valores não parseáveis
    ctx.set_artifact("data.raw_rows", [{"age": "abc", "segment": "A", "target": "1"}])

    sr = ContractConformityReportStep().run(ctx)
    assert sr.status == StepStatus.SUCCESS
    dtype_issues = sr.payload["dtype_issues"]
    assert any(i["column"] == "age" for i in dtype_issues)
    # Deve sinalizar mismatch com severidade error (parse_failures > 0)
    dr = sr.payload["decisions_required"]
    assert any(d["code"] == "DTYPE_MISMATCH" and d["severity"] == "error" for d in dr)


def test_conformity_category_out_of_domain() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1_with_categories(),
        meta={},
    )
    ctx.set_artifact("data.raw_rows", [{"age": "10", "segment": "X", "target": "1"}])

    sr = ContractConformityReportStep().run(ctx)
    assert sr.status == StepStatus.SUCCESS
    cat_issues = sr.payload["category_issues"]
    assert any(i["column"] == "segment" and "X" in i["invalid_values"] for i in cat_issues)
    dr = sr.payload["decisions_required"]
    assert any(d["code"] == "CATEGORY_OUT_OF_DOMAIN" for d in dr)
