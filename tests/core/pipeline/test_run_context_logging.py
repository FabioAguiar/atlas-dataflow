import pytest

try:
    from atlas_dataflow.core.pipeline.context import RunContext
except Exception as e:  # noqa: BLE001
    RunContext = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing RunContext logging/warnings API. Implement:"
            "- src/atlas_dataflow/core/pipeline/context.py (log, add_warning, events, warnings)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_structured_log_event(dummy_ctx):
    _require_imports()
    dummy_ctx.log(step_id="ingest.load", level="INFO", message="hello", foo=1)
    assert len(dummy_ctx.events) >= 1
    ev = dummy_ctx.events[-1]
    assert ev["run_id"] == dummy_ctx.run_id
    assert ev["step_id"] == "ingest.load"
    assert ev["level"] == "INFO"
    assert ev["message"] == "hello"
    assert ev["foo"] == 1


def test_warning_collection(dummy_ctx):
    _require_imports()
    dummy_ctx.add_warning(step_id="audit.schema", message="missing column")
    assert "audit.schema" in dummy_ctx.warnings
    assert dummy_ctx.warnings["audit.schema"] == ["missing column"]
