import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        save_manifest,
        load_manifest,
    )
except Exception as e:
    create_manifest = None
    save_manifest = None
    load_manifest = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing manifest persistence APIs. Implement:\n"
            "- save_manifest(manifest, path: Path) -> None  (JSON)\n"
            "- load_manifest(path: Path) -> manifest\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_round_trip_save_load(tmp_path: Path):
    _require_imports()
    m = create_manifest(
        run_id="run-004",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    out = tmp_path / "manifest.json"
    save_manifest(m, out)

    assert out.exists()
    loaded = load_manifest(out)

    d1 = m.to_dict() if hasattr(m, "to_dict") else m
    d2 = loaded.to_dict() if hasattr(loaded, "to_dict") else loaded

    assert d2["run"]["run_id"] == d1["run"]["run_id"]
    assert d2["inputs"]["config_hash"] == d1["inputs"]["config_hash"]
    assert isinstance(d2["events"], list)
    assert isinstance(d2["steps"], dict)
