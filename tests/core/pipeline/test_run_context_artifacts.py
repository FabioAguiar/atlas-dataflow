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
            "Missing RunContext. Implement:"
            "- src/atlas_dataflow/core/pipeline/context.py (RunContext with artifact store)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_artifact_set_get(dummy_ctx):
    _require_imports()
    dummy_ctx.set_artifact("dataset.raw", [1, 2, 3])
    assert dummy_ctx.has_artifact("dataset.raw") is True
    assert dummy_ctx.get_artifact("dataset.raw") == [1, 2, 3]


def test_artifact_missing_key_raises(dummy_ctx):
    _require_imports()
    with pytest.raises(KeyError):
        dummy_ctx.get_artifact("missing.key")


def test_context_isolation(dummy_config, dummy_contract):
    _require_imports()
    from datetime import datetime, timezone
    ctx1 = RunContext(run_id="r1", created_at=datetime(2026,1,16,tzinfo=timezone.utc), config=dummy_config, contract=dummy_contract, meta={})
    ctx2 = RunContext(run_id="r2", created_at=datetime(2026,1,16,tzinfo=timezone.utc), config=dummy_config, contract=dummy_contract, meta={})
    ctx1.set_artifact("x", 1)
    assert ctx2.has_artifact("x") is False
