import pytest

try:
    from atlas_dataflow.core.engine.planner import plan_execution, CycleDetectedError, UnknownDependencyError
except Exception as e:
    plan_execution = None
    CycleDetectedError = None
    UnknownDependencyError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing planner errors. Implement:
- CycleDetectedError
- UnknownDependencyError
Import error: {_IMPORT_ERR}
""")


def test_cycle_detected(DummyStep):
    _require_imports()
    steps = [
        DummyStep(step_id="a", depends_on=["c"]),
        DummyStep(step_id="b", depends_on=["a"]),
        DummyStep(step_id="c", depends_on=["b"]),
    ]
    with pytest.raises(CycleDetectedError):
        plan_execution(steps)


def test_unknown_dependency(DummyStep):
    _require_imports()
    steps = [
        DummyStep(step_id="a", depends_on=["x"]),
    ]
    with pytest.raises(UnknownDependencyError):
        plan_execution(steps)
