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


class FailingStep:
    id = "fail"
    kind = None
    depends_on = []

    def run(self, ctx):
        raise RuntimeError("boom")


def test_fail_fast_stops_execution(dummy_ctx):
    if Engine is None:
        pytest.fail(f"""Missing Engine. Import error: {_IMPORT_ERR}""")

    dummy_ctx.config["engine"] = {"fail_fast": True}
    steps = [FailingStep()]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["fail"].status == StepStatus.FAILED
