import pytest

try:
    from atlas_dataflow.core.engine.engine import Engine
    from atlas_dataflow.core.pipeline.types import StepStatus
except Exception as e:
    Engine = None
    StepStatus = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing Engine. Implement:
- src/atlas_dataflow/core/engine/engine.py (Engine)
Import error: {_IMPORT_ERR}
""")


def test_happy_path(DummyStep, dummy_ctx):
    _require_imports()
    steps = [
        DummyStep(step_id="a"),
        DummyStep(step_id="b", depends_on=["a"]),
    ]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["a"].status == StepStatus.SUCCESS
    assert result.steps["b"].status == StepStatus.SUCCESS
