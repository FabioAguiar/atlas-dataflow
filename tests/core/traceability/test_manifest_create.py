import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        AtlasManifest,
    )
except Exception as e:
    create_manifest = None
    AtlasManifest = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing manifest module. Implement:\n"
            "- src/atlas_dataflow/core/traceability/manifest.py\n"
            "Expected exports: create_manifest, AtlasManifest\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_create_manifest_has_minimum_fields():
    _require_imports()

    m = create_manifest(
        run_id="run-001",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )

    # Must be serializable-friendly (dataclass or plain dict)
    data = m.to_dict() if hasattr(m, "to_dict") else m

    assert data["run"]["run_id"] == "run-001"
    assert data["run"]["started_at"]  # iso string expected
    assert data["run"]["atlas_version"] == "0.0.0"
    assert data["inputs"]["config_hash"] == "c" * 64
    assert data["inputs"]["contract_hash"] == "d" * 64

    assert "steps" in data
    assert isinstance(data["steps"], dict)
    assert "events" in data
    assert isinstance(data["events"], list)
