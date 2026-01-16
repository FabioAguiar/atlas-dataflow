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


def test_skip_by_config(DummyStep, dummy_ctx):
    if Engine is None:
        pytest.fail(f"""Missing Engine. Import error: {_IMPORT_ERR}""")

    dummy_ctx.config["steps"] = {
        "a": {"enabled": False}
    }

    steps = [DummyStep(step_id="a")]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["a"].status == StepStatus.SKIPPED
