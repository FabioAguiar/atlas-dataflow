import pytest

try:
    from atlas_dataflow.core.pipeline.registry import StepRegistry, DuplicateStepIdError
except Exception as e:  # noqa: BLE001
    StepRegistry = None
    DuplicateStepIdError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing StepRegistry. Implement:"
            "- src/atlas_dataflow/core/pipeline/registry.py (StepRegistry, DuplicateStepIdError)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_registry_rejects_duplicate_step_id(DummyStep):
    _require_imports()
    reg = StepRegistry()
    reg.add(DummyStep(step_id="ingest.load"))
    with pytest.raises(DuplicateStepIdError):
        reg.add(DummyStep(step_id="ingest.load"))


def test_registry_accepts_unique_ids(DummyStep):
    _require_imports()
    reg = StepRegistry()
    reg.add(DummyStep(step_id="ingest.load"))
    reg.add(DummyStep(step_id="audit.schema_types"))
    assert [s.id for s in reg.list()] == ["ingest.load", "audit.schema_types"]
