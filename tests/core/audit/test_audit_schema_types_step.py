from __future__ import annotations

import copy
from typing import Any, Dict, List

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.audit.schema_types import AuditSchemaTypesStep


def _make_rows() -> List[Dict[str, Any]]:
    return [
        {"id": 1, "cat": "A", "val": None, "ts": "2026-01-01"},
        {"id": 2, "cat": "A", "val": 10, "ts": "2026-01-02"},
        {"id": 3, "cat": None, "val": 10, "ts": None},
        {"id": 4, "cat": "B", "val": 10, "ts": "2026-01-04"},
    ]


def test_audit_schema_types_happy_path(dummy_ctx):
    rows = _make_rows()
    dummy_ctx.set_artifact("data.raw_rows", rows)

    before = copy.deepcopy(dummy_ctx.get_artifact("data.raw_rows"))

    step = AuditSchemaTypesStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    assert result.step_id == "audit.schema_types"
    assert "columns" in result.payload

    cols = result.payload["columns"]
    assert set(cols.keys()) == {"id", "cat", "val", "ts"}

    # dtype é string
    assert isinstance(cols["id"]["dtype"], str)
    assert cols["id"]["semantic_type"] in {"numeric", "categorical", "temporal", "other"}

    # nulls
    assert cols["cat"]["nulls"]["count"] == 1
    assert 0.0 <= cols["cat"]["nulls"]["ratio"] <= 1.0

    # cardinalidade
    assert cols["val"]["cardinality"]["unique_values"] == 1
    assert cols["val"]["cardinality"]["is_constant"] is True

    # exemplos: serializáveis, sem None quando possível, até 5
    ex = cols["val"]["examples"]
    assert isinstance(ex, list)
    assert len(ex) <= 5
    assert None not in ex

    # não muta dataset
    after = dummy_ctx.get_artifact("data.raw_rows")
    assert after == before


def test_audit_schema_types_all_null_column(dummy_ctx):
    rows = [
        {"a": None, "b": 1},
        {"a": None, "b": 2},
        {"a": None, "b": 3},
    ]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    step = AuditSchemaTypesStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    cols = result.payload["columns"]

    assert cols["a"]["nulls"]["count"] == 3
    assert cols["a"]["cardinality"]["unique_values"] == 0
    assert cols["a"]["cardinality"]["is_constant"] is False
    assert cols["a"]["examples"] == []


def test_audit_schema_types_missing_dataset(dummy_ctx):
    # do NOT set data.raw_rows
    step = AuditSchemaTypesStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "error" in result.payload
    assert result.payload["error"]["type"] == "ValueError"
    assert "data.raw_rows" in result.payload["error"]["message"]
