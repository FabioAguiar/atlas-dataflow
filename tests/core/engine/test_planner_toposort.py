import pytest

try:
    from atlas_dataflow.core.engine.planner import plan_execution
except Exception as e:
    plan_execution = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing planner. Implement:
- src/atlas_dataflow/core/engine/planner.py (plan_execution)
Import error: {_IMPORT_ERR}
""")


def test_toposort_linear(DummyStep):
    _require_imports()
    steps = [
        DummyStep(step_id="a"),
        DummyStep(step_id="b", depends_on=["a"]),
        DummyStep(step_id="c", depends_on=["b"]),
    ]
    order = plan_execution(steps)
    assert [s.id for s in order] == ["a", "b", "c"]
