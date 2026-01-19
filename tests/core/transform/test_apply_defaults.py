"""
Tests: transform.apply_defaults
===============================

Testes unitários para o Step transform.apply_defaults.

Objetivo:
---------
Garantir que defaults sejam aplicados **somente** conforme declarado
no contrato (shape real do Internal Contract v1), de forma controlada,
auditável e sem violações de domínio.
"""

import pandas as pd
from datetime import datetime, timezone
from uuid import uuid4

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.steps.transform.apply_defaults import TransformApplyDefaultsStep


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def make_context(df: pd.DataFrame, contract: dict) -> RunContext:
    ctx = RunContext(
        run_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        config={},          # config vazia é válida
        contract=contract,  # contrato explícito (dict)
    )
    ctx.dataset = df
    return ctx


def get_impact(ctx: RunContext, step_id: str) -> dict:
    # O Step registra impacto em ctx.impacts[step_id]
    impacts = getattr(ctx, "impacts", {}) or {}
    if not isinstance(impacts, dict):
        return {}
    return impacts.get(step_id, {}) or {}


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

def test_default_applied_only_to_null_values():
    df = pd.DataFrame({"age": [10, None, 30]})

    contract = {
        "features": [{"name": "age", "required": True}],
        "defaults": {"age": 18},
    }

    ctx = make_context(df, contract)

    step = TransformApplyDefaultsStep()
    step.run(ctx)

    out = ctx.dataset
    assert out["age"].tolist() == [10, 18, 30]

    impact = get_impact(ctx, step.step_id)
    assert impact["age"]["default_value"] == 18
    assert impact["age"]["values_filled"] == 1
    assert impact["age"]["column_created"] is False


def test_valid_values_are_not_overwritten():
    df = pd.DataFrame({"score": [100, 200]})

    contract = {
        "features": [{"name": "score", "required": True}],
        "defaults": {"score": 0},
    }

    ctx = make_context(df, contract)

    step = TransformApplyDefaultsStep()
    step.run(ctx)

    out = ctx.dataset
    assert out["score"].tolist() == [100, 200]

    impact = get_impact(ctx, step.step_id)
    assert impact == {}


def test_missing_optional_column_is_created():
    df = pd.DataFrame({"x": [1, 2, 3]})

    contract = {
        "features": [{"name": "y", "required": False}],
        "defaults": {"y": 0},
    }

    ctx = make_context(df, contract)

    step = TransformApplyDefaultsStep()
    step.run(ctx)

    out = ctx.dataset
    assert "y" in out.columns
    assert out["y"].tolist() == [0, 0, 0]

    impact = get_impact(ctx, step.step_id)
    assert impact["y"]["default_value"] == 0
    assert impact["y"]["column_created"] is True
    assert impact["y"]["values_filled"] == 3


def test_no_application_outside_contract():
    df = pd.DataFrame({"a": [None, None]})

    contract = {
        "features": [],
        "defaults": {},
    }

    ctx = make_context(df, contract)

    step = TransformApplyDefaultsStep()
    step.run(ctx)

    out = ctx.dataset
    assert out["a"].isna().all()

    impact = get_impact(ctx, step.step_id)
    assert impact == {}
