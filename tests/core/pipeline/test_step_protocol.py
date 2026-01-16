import pytest

try:
    from atlas_dataflow.core.pipeline.step import Step
    from atlas_dataflow.core.pipeline.types import StepResult, StepKind
except Exception as e:  # noqa: BLE001
    Step = None
    StepResult = None
    StepKind = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing pipeline core modules. Implement:"
            "- src/atlas_dataflow/core/pipeline/types.py (StepKind, StepStatus, StepResult)"
            "- src/atlas_dataflow/core/pipeline/step.py (Step Protocol)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_dummy_step_satisfies_protocol(DummyStep, dummy_ctx):
    _require_imports()
    step = DummyStep(step_id="ingest.load", kind=StepKind.DIAGNOSTIC)
    assert isinstance(step, Step), "DummyStep must satisfy Step Protocol (@runtime_checkable expected)."
    result = step.run(dummy_ctx)
    assert isinstance(result, StepResult)
    assert result.step_id == "ingest.load"
