"""Testes unitários para o Step transform.deduplicate (v1).

Cobre:
- no-op quando desabilitado
- deduplicação por linha completa
- deduplicação por chave
- configuração inválida
- auditoria de impacto correta
"""

from copy import deepcopy

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.transform.deduplicate import TransformDeduplicateStep


def _base_rows():
    return [
        {"id": 1, "date": "2024-01-01", "value": 10},
        {"id": 1, "date": "2024-01-01", "value": 10},  # duplicado
        {"id": 2, "date": "2024-01-02", "value": 20},
    ]


def test_deduplicate_disabled_noop(dummy_ctx):
    rows = _base_rows()
    original = deepcopy(rows)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)
    ctx.config = {}  # step ausente

    step = TransformDeduplicateStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SKIPPED
    assert result.payload.get("disabled") is True

    # dataset não mutado
    assert ctx.get_artifact("data.raw_rows") == original


def test_deduplicate_full_row(dummy_ctx):
    rows = _base_rows()

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)
    ctx.config = {
        "steps": {
            "transform.deduplicate": {
                "enabled": True,
                "mode": "full_row",
            }
        }
    }

    step = TransformDeduplicateStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SUCCESS

    impact = result.payload["impact"]
    assert impact["mode"] == "full_row"
    assert impact["key_columns"] is None
    assert impact["rows_before"] == 3
    assert impact["rows_after"] == 2
    assert impact["rows_removed"] == 1

    data_after = ctx.get_artifact("data.raw_rows")
    assert len(data_after) == 2


def test_deduplicate_key_based(dummy_ctx):
    rows = _base_rows()

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)
    ctx.config = {
        "steps": {
            "transform.deduplicate": {
                "enabled": True,
                "mode": "key_based",
                "key_columns": ["id", "date"],
            }
        }
    }

    step = TransformDeduplicateStep()
    result = step.run(ctx)

    assert result.status == StepStatus.SUCCESS

    impact = result.payload["impact"]
    assert impact["mode"] == "key_based"
    assert impact["key_columns"] == ["id", "date"]
    assert impact["rows_before"] == 3
    assert impact["rows_after"] == 2
    assert impact["rows_removed"] == 1

    data_after = ctx.get_artifact("data.raw_rows")
    assert len(data_after) == 2


def test_deduplicate_invalid_config_missing_mode(dummy_ctx):
    rows = _base_rows()

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)
    ctx.config = {
        "steps": {
            "transform.deduplicate": {
                "enabled": True
            }
        }
    }

    step = TransformDeduplicateStep()
    result = step.run(ctx)

    assert result.status == StepStatus.FAILED
    assert "error" in result.payload


def test_deduplicate_invalid_key_columns(dummy_ctx):
    rows = _base_rows()

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", rows)
    ctx.config = {
        "steps": {
            "transform.deduplicate": {
                "enabled": True,
                "mode": "key_based",
                "key_columns": ["missing_col"],
            }
        }
    }

    step = TransformDeduplicateStep()
    result = step.run(ctx)

    assert result.status == StepStatus.FAILED
    assert "error" in result.payload
