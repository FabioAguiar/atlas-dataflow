from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.steps.evaluate.model_selection import EvaluateModelSelectionStep


def _mk_ctx(*, config: dict) -> RunContext:
    return RunContext(
        run_id="r-ms-1",
        created_at=datetime.now(timezone.utc),
        config=config,
        contract={},
        meta={},
    )


def _config(*, metric: str = "f1", direction: str = "maximize", enabled: bool = True) -> dict:
    return {
        "steps": {
            "evaluate.model_selection": {
                "enabled": enabled,
                "target_metric": metric,
                "direction": direction,
            }
        }
    }


def test_model_selection_selects_champion_maximize_from_eval_metrics_list():
    ctx = _mk_ctx(config=_config(metric="f1", direction="maximize"))
    ctx.set_artifact(
        "eval.metrics",
        [
            {"model_id": "logistic_regression", "metrics": {"f1": 0.70, "accuracy": 0.80}},
            {"model_id": "random_forest", "metrics": {"f1": 0.83, "accuracy": 0.78}},
            {"model_id": "knn", "metrics": {"f1": 0.81, "accuracy": 0.79}},
        ],
    )

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    sel = result.payload["selection"]
    assert sel["metric"] == "f1"
    assert sel["direction"] == "maximize"
    assert sel["champion_model_id"] == "random_forest"
    assert sel["champion_score"] == pytest.approx(0.83)
    assert [r["model_id"] for r in sel["ranking"]] == ["random_forest", "knn", "logistic_regression"]
    assert ctx.has_artifact("eval.model_selection")


def test_model_selection_selects_champion_minimize():
    ctx = _mk_ctx(config=_config(metric="loss", direction="minimize"))
    ctx.set_artifact(
        "eval.metrics",
        [
            {"model_id": "a", "metrics": {"loss": 0.40}},
            {"model_id": "b", "metrics": {"loss": 0.35}},
            {"model_id": "c", "metrics": {"loss": 0.36}},
        ],
    )

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    sel = result.payload["selection"]
    assert sel["champion_model_id"] == "b"
    assert sel["champion_score"] == pytest.approx(0.35)
    assert [r["model_id"] for r in sel["ranking"]] == ["b", "c", "a"]


def test_model_selection_tie_break_is_deterministic_by_model_id():
    # Empate no score: desempata por model_id (lexicográfico asc)
    ctx = _mk_ctx(config=_config(metric="f1", direction="maximize"))
    ctx.set_artifact(
        "eval.metrics",
        [
            {"model_id": "z_model", "metrics": {"f1": 0.90}},
            {"model_id": "a_model", "metrics": {"f1": 0.90}},
            {"model_id": "m_model", "metrics": {"f1": 0.85}},
        ],
    )

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    sel = result.payload["selection"]
    assert sel["champion_model_id"] == "a_model"
    assert [r["model_id"] for r in sel["ranking"]] == ["a_model", "z_model", "m_model"]


def test_model_selection_supports_single_payload_dict_eval_metrics():
    ctx = _mk_ctx(config=_config(metric="accuracy", direction="maximize"))
    ctx.set_artifact("eval.metrics", {"model_id": "only", "metrics": {"accuracy": 0.5}})

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "success", result.summary
    assert result.payload["selection"]["champion_model_id"] == "only"


def test_model_selection_fails_when_target_metric_missing():
    ctx = _mk_ctx(config=_config(metric="roc_auc", direction="maximize"))
    ctx.set_artifact("eval.metrics", [{"model_id": "lr", "metrics": {"f1": 0.7}}])

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "target_metric" in (result.summary or "").lower() or "not present" in (result.summary or "").lower()


def test_model_selection_fails_for_invalid_direction():
    ctx = _mk_ctx(config=_config(metric="f1", direction="upwards"))  # inválido
    ctx.set_artifact("eval.metrics", [{"model_id": "lr", "metrics": {"f1": 0.7}}])

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "direction" in (result.summary or "").lower()


def test_model_selection_fails_without_eval_metrics_artifact():
    ctx = _mk_ctx(config=_config(metric="f1", direction="maximize"))

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "eval.metrics" in (result.summary or "").lower()


def test_model_selection_skips_when_disabled():
    ctx = _mk_ctx(config=_config(enabled=False))
    ctx.set_artifact("eval.metrics", [{"model_id": "lr", "metrics": {"f1": 0.7}}])

    step = EvaluateModelSelectionStep()
    result = step.run(ctx)

    assert result.status.value == "success"
    assert result.payload.get("skipped") is True
