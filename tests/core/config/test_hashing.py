import json
import hashlib
import pytest

try:
    from atlas_dataflow.core.config.hashing import compute_config_hash
except Exception as e:  # noqa: BLE001
    compute_config_hash = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _canonical_json_bytes(obj: dict) -> bytes:
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing hashing module. Implement:\n"
            "- src/atlas_dataflow/core/config/hashing.py (compute_config_hash)\n"
            "Policy expected: SHA-256 of canonical JSON serialization.\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_hash_is_deterministic():
    _require_imports()
    cfg = {"b": 2, "a": 1}
    h1 = compute_config_hash(cfg)
    h2 = compute_config_hash({"a": 1, "b": 2})
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64


def test_hash_matches_sha256_of_canonical_json():
    _require_imports()
    cfg = {"engine": {"fail_fast": True, "log_level": "INFO"}, "steps": {"train": {"enabled": True}}}
    expected = hashlib.sha256(_canonical_json_bytes(cfg)).hexdigest()
    got = compute_config_hash(cfg)
    assert got == expected


def test_hash_changes_on_override():
    _require_imports()
    base = {"a": 1, "b": 2}
    changed = {"a": 1, "b": 3}
    assert compute_config_hash(base) != compute_config_hash(changed)
