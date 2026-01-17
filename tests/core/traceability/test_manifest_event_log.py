import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        add_event,
    )
except Exception as e:
    create_manifest = None
    add_event = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing event log APIs. Implement:\n"
            "- add_event(manifest, event_type, ts, step_id=None, payload=None)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_event_log_appends_ordered_events():
    _require_imports()
    m = create_manifest(
        run_id="run-003",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    t0 = datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 16, 12, 0, 1, tzinfo=timezone.utc)

    add_event(m, event_type="run_started", ts=t0, payload={"note": "begin"})
    add_event(m, event_type="step_started", ts=t1, step_id="a", payload={"kind": "diagnostic"})

    data = m.to_dict() if hasattr(m, "to_dict") else m
    assert len(data["events"]) == 2
    assert data["events"][0]["event_type"] == "run_started"
    assert data["events"][1]["event_type"] == "step_started"
    assert data["events"][1]["step_id"] == "a"
