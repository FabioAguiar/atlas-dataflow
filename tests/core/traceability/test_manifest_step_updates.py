import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        step_started,
        step_finished,
        step_failed,
    )
    from atlas_dataflow.core.pipeline.types import StepStatus
except Exception as e:
    create_manifest = None
    step_started = None
    step_finished = None
    step_failed = None
    StepStatus = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing traceability step update APIs. Implement:\n"
            "- create_manifest(...)\n"
            "- step_started(manifest, step_id, kind, ts)\n"
            "- step_finished(manifest, step_id, ts, result)\n"
            "- step_failed(manifest, step_id, ts, error)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_incremental_step_update_records_status_and_timestamps():
    _require_imports()
    started = datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc)

    m = create_manifest(
        run_id="run-001",
        started_at=started,
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )

    t0 = datetime(2026, 1, 16, 12, 0, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 16, 12, 0, 3, tzinfo=timezone.utc)

    step_started(m, step_id="ingest.load", kind="diagnostic", ts=t0)
    step_finished(
        m,
        step_id="ingest.load",
        ts=t1,
        result={
            "status": StepStatus.SUCCESS.value if hasattr(StepStatus, "SUCCESS") else "success",
            "summary": "ok",
            "warnings": ["w1"],
            "artifacts": {"df": "mem://df"},
            "metrics": {"rows": 10},
        },
    )

    data = m.to_dict() if hasattr(m, "to_dict") else m
    s = data["steps"]["ingest.load"]

    assert s["status"] in (StepStatus.SUCCESS.value if hasattr(StepStatus, "SUCCESS") else "success", "success")
    assert s["started_at"]
    assert s["finished_at"]
    assert s["duration_ms"] >= 0
    assert s["warnings"] == ["w1"]
    assert s["artifacts"]["df"] == "mem://df"
    assert s["metrics"]["rows"] == 10


def test_failed_step_is_recorded():
    _require_imports()
    m = create_manifest(
        run_id="run-002",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    t0 = datetime(2026, 1, 16, 12, 1, 0, tzinfo=timezone.utc)
    step_started(m, step_id="train.fit", kind="train", ts=t0)
    step_failed(m, step_id="train.fit", ts=t0, error="boom")

    data = m.to_dict() if hasattr(m, "to_dict") else m
    s = data["steps"]["train.fit"]
    assert s["status"] in ("failed", getattr(StepStatus, "FAILED", type("X",(object,),{"value":"failed"})) .value)
    assert "error" in s
