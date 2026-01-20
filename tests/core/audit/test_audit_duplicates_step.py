"""Testes unitários para o Step audit.duplicates.

Cobre:
- detecção correta de duplicados
- dataset sem duplicados
- dataset vazio
- nenhuma mutação do dataset original
- falha explícita quando artifact obrigatório está ausente
"""

from copy import deepcopy

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.audit.duplicates import AuditDuplicatesStep


def test_audit_duplicates_with_duplicates(dummy_ctx):
    rows = [
        {"a": 1, "b": "x"},
        {"a": 1, "b": "x"},  # duplicado
        {"a": 2, "b": "y"},
    ]
    original = deepcopy(rows)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)

    step = AuditDuplicatesStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SUCCESS

    dup = result.payload["duplicates"]
    assert dup["rows"] == 1
    assert dup["detected"] is True
    assert dup["ratio"] == 1 / 3
    assert isinstance(dup["treatment_policy"], str)

    # garante não mutação do dataset original
    assert rows == original


def test_audit_duplicates_without_duplicates(dummy_ctx):
    rows = [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "x"},
        {"a": 3, "b": "y"},
    ]
    original = deepcopy(rows)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)

    step = AuditDuplicatesStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SUCCESS

    dup = result.payload["duplicates"]
    assert dup["rows"] == 0
    assert dup["detected"] is False
    assert dup["ratio"] == 0.0

    assert rows == original


def test_audit_duplicates_empty_dataset(dummy_ctx):
    rows = []
    original = deepcopy(rows)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)

    step = AuditDuplicatesStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SUCCESS

    dup = result.payload["duplicates"]
    assert dup["rows"] == 0
    assert dup["detected"] is False
    assert dup["ratio"] == 0.0

    assert rows == original


def test_audit_duplicates_missing_artifact(dummy_ctx):
    ctx = dummy_ctx  # não injeta data.raw_rows

    step = AuditDuplicatesStep()
    result = step.run(ctx)

    assert result.status == StepStatus.FAILED
    assert "error" in result.payload
