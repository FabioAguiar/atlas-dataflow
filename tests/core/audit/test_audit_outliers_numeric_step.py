"""Testes unitários — Step audit.outliers_numeric (v1)."""

from __future__ import annotations

import pandas as pd
import pytest

from atlas_dataflow.steps.audit.outliers_numeric import AuditOutliersNumericStep


def _set_step_cfg(ctx, cfg: dict) -> None:
    # Mantém padrão do projeto: ctx.config['steps'][step_id] controla comportamento.
    if not isinstance(ctx.config, dict):
        ctx.config = {}
    steps = ctx.config.get("steps")
    if not isinstance(steps, dict):
        steps = {}
        ctx.config["steps"] = steps
    steps["audit.outliers_numeric"] = cfg


def test_detect_outliers_iqr(dummy_ctx):
    df = pd.DataFrame({"x": [1, 2, 3, 4, 100], "y": [10, 10, 10, 10, 10], "cat": ["a", "b", "c", "d", "e"]})
    df_before = df.copy(deep=True)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", df)
    _set_step_cfg(ctx, {"enabled": True, "methods": {"iqr": True, "zscore": False}})

    step = AuditOutliersNumericStep()
    result = step.run(ctx)

    assert result.status.name == "SUCCESS"
    out = result.payload["outliers"]

    assert "x" in out
    recs = out["x"]
    assert isinstance(recs, list) and len(recs) == 1
    rec = recs[0]
    assert rec["method"] == "iqr"
    assert rec["count"] == 1
    assert rec["ratio"] == pytest.approx(1 / 5)

    # y constante -> count 0
    assert "y" in out
    yrec = out["y"][0]
    assert yrec["method"] == "iqr"
    assert yrec["count"] == 0

    # não numérica ignorada
    assert "cat" not in out

    # dataset não mutado
    pd.testing.assert_frame_equal(df, df_before)


def test_detect_outliers_zscore_threshold(dummy_ctx):
    df = pd.DataFrame({"x": [0, 0, 0, 10]})
    df_before = df.copy(deep=True)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", df)
    _set_step_cfg(ctx, {"enabled": True, "methods": {"iqr": False, "zscore": True}, "zscore_threshold": 1.0})

    step = AuditOutliersNumericStep()
    result = step.run(ctx)

    assert result.status.name == "SUCCESS"
    out = result.payload["outliers"]

    assert "x" in out
    rec = out["x"][0]
    assert rec["method"] == "zscore"
    assert rec["count"] == 1
    assert rec["ratio"] == pytest.approx(1 / 4)
    assert rec["bounds"]["lower"] is not None
    assert rec["bounds"]["upper"] is not None

    pd.testing.assert_frame_equal(df, df_before)


def test_methods_disabled_results_in_empty_payload(dummy_ctx):
    df = pd.DataFrame({"x": [1, 2, None]})
    df_before = df.copy(deep=True)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", df)
    _set_step_cfg(ctx, {"enabled": True, "methods": {"iqr": False, "zscore": False}})

    step = AuditOutliersNumericStep()
    result = step.run(ctx)

    assert result.status.name == "SUCCESS"
    assert result.payload["outliers"] == {}

    pd.testing.assert_frame_equal(df, df_before)


def test_ignores_non_numeric_columns(dummy_ctx):
    df = pd.DataFrame({"cat": ["a", None, "b"], "txt": ["x", "y", None]})
    df_before = df.copy(deep=True)

    ctx = dummy_ctx
    ctx.set_artifact("data.raw_rows", df)
    _set_step_cfg(ctx, {"enabled": True, "methods": {"iqr": True, "zscore": True}})

    step = AuditOutliersNumericStep()
    result = step.run(ctx)

    assert result.status.name == "SUCCESS"
    assert result.payload["outliers"] == {}

    pd.testing.assert_frame_equal(df, df_before)
