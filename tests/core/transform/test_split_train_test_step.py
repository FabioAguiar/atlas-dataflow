from __future__ import annotations

import copy

import pytest

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.transform.split_train_test import SplitTrainTestStep


def _set_cfg(ctx, cfg: dict) -> None:
    # Dummy config do projeto contém outros itens; ajustamos apenas a seção steps.
    ctx.config.setdefault("steps", {})
    ctx.config["steps"]["split.train_test"] = cfg


def test_split_train_test_deterministic_with_seed(dummy_ctx):
    rows = [{"id": i, "target": 0 if i < 10 else 1} for i in range(20)]
    rows_before = copy.deepcopy(rows)
    dummy_ctx.set_artifact("data.raw_rows", rows)

    _set_cfg(
        dummy_ctx,
        {
            "enabled": True,
            "test_size": 0.25,
            "seed": 42,
            "stratify": {"enabled": False},
        },
    )

    step = SplitTrainTestStep()
    r1 = step.run(dummy_ctx)
    assert r1.status == StepStatus.SUCCESS

    train1 = copy.deepcopy(dummy_ctx.get_artifact("data.train"))
    test1 = copy.deepcopy(dummy_ctx.get_artifact("data.test"))

    # re-run in a fresh context with same inputs/config: must match
    dummy_ctx2 = copy.deepcopy(dummy_ctx)
    dummy_ctx2._artifacts = {}  # reset artifacts (private field in tests only)
    dummy_ctx2.events = []
    dummy_ctx2.set_artifact("data.raw_rows", copy.deepcopy(rows))
    _set_cfg(dummy_ctx2, dummy_ctx.config["steps"]["split.train_test"])

    r2 = step.run(dummy_ctx2)
    assert r2.status == StepStatus.SUCCESS
    assert dummy_ctx2.get_artifact("data.train") == train1
    assert dummy_ctx2.get_artifact("data.test") == test1

    # no mutation of original rows
    assert rows == rows_before


def test_split_train_test_without_stratify(dummy_ctx):
    rows = [{"id": i, "target": i % 2} for i in range(11)]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    _set_cfg(dummy_ctx, {"enabled": True, "test_size": 0.2, "seed": 7, "stratify": {"enabled": False}})

    step = SplitTrainTestStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    payload = result.payload
    impact = payload["impact"]
    assert impact["rows_total"] == 11
    assert impact["rows_train"] + impact["rows_test"] == 11
    assert impact["stratified"] is False
    assert impact["stratify_column"] is None
    assert impact["seed"] == 7

    assert isinstance(dummy_ctx.get_artifact("data.train"), list)
    assert isinstance(dummy_ctx.get_artifact("data.test"), list)


def test_split_train_test_with_stratify_preserves_ratio_approx(dummy_ctx):
    # 80% class 0, 20% class 1
    rows = [{"id": i, "target": 0} for i in range(80)] + [{"id": i + 100, "target": 1} for i in range(20)]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    _set_cfg(
        dummy_ctx,
        {
            "enabled": True,
            "test_size": 0.25,
            "seed": 123,
            "stratify": {"enabled": True, "column": "target"},
        },
    )

    step = SplitTrainTestStep()
    result = step.run(dummy_ctx)
    assert result.status == StepStatus.SUCCESS

    train = dummy_ctx.get_artifact("data.train")
    test = dummy_ctx.get_artifact("data.test")

    def ratio(data):
        ones = sum(1 for r in data if r["target"] == 1)
        return ones / len(data)

    # aproximação: tolerância razoável para split pequeno
    assert abs(ratio(train) - 0.2) <= 0.05
    assert abs(ratio(test) - 0.2) <= 0.05

    impact = result.payload["impact"]
    assert impact["stratified"] is True
    assert impact["stratify_column"] == "target"


def test_split_train_test_invalid_config_missing_seed(dummy_ctx):
    dummy_ctx.set_artifact("data.raw_rows", [{"id": 1, "target": 0}, {"id": 2, "target": 1}])
    _set_cfg(dummy_ctx, {"enabled": True, "test_size": 0.5})  # seed missing

    step = SplitTrainTestStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "seed" in (result.summary or "").lower()


def test_split_train_test_stratify_not_possible_fails(dummy_ctx):
    # only one sample of class 1 -> stratify should fail in sklearn
    rows = [{"id": i, "target": 0} for i in range(10)] + [{"id": 999, "target": 1}]
    dummy_ctx.set_artifact("data.raw_rows", rows)

    _set_cfg(
        dummy_ctx,
        {
            "enabled": True,
            "test_size": 0.3,
            "seed": 1,
            "stratify": {"enabled": True, "column": "target"},
        },
    )

    step = SplitTrainTestStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "stratified" in (result.summary or "").lower() or "stratif" in (result.summary or "").lower()


def test_split_train_test_missing_artifact(dummy_ctx):
    _set_cfg(dummy_ctx, {"enabled": True, "test_size": 0.2, "seed": 42})

    step = SplitTrainTestStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "data.raw_rows" in (result.summary or "")
