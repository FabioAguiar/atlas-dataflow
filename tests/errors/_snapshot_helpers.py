"""
Snapshot helpers for standardized Atlas error payloads.

Goal: keep guardrail snapshots stable while still validating the *canonical minimum*.

Features:
- Deterministic normalization (sorted dict keys)
- Sanitizes volatile values (absolute temp paths)
- Small compatibility mapping for legacy error.type codes
- **Subset matching**: snapshot is treated as a minimum contract; extra fields in
  the runtime payload are allowed. This matches the issue requirement that snapshots
  validate structure + minimum content without overfitting to incidental details.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Any

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# Heuristics for path-like values (Windows / Unix)
_WIN_ABS_RE = re.compile(r"^[A-Za-z]:\\")
_UNIX_ABS_RE = re.compile(r"^/")
_HAS_SEP_RE = re.compile(r"[\\/]")

# Legacy -> canonical error type aliases
_TYPE_ALIASES = {
    # preprocess
    "PREPROCESS_MISSING": "PREPROCESS_NOT_FOUND",
    "MISSING_PREPROCESS": "PREPROCESS_NOT_FOUND",
    "PREPROCESS_NOT_AVAILABLE": "PREPROCESS_NOT_FOUND",
    # model
    "MODEL_MISSING": "MODEL_NOT_FOUND",
    "MISSING_MODEL": "MODEL_NOT_FOUND",
    "MODEL_NOT_AVAILABLE": "MODEL_NOT_FOUND",
}


def _is_path_like(s: str) -> bool:
    if _WIN_ABS_RE.match(s) or _UNIX_ABS_RE.match(s):
        return True
    if _HAS_SEP_RE.search(s) and ("." in s or "artifacts" in s or "run" in s):
        return True
    return False


def _sanitize_string(s: str) -> str:
    if _is_path_like(s):
        if s.startswith("artifacts/") or s.startswith("artifacts\\"):
            return s.replace("\\", "/")
        return "<path>"
    return s


def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {k: _normalize(obj[k]) for k in sorted(obj.keys())}
        if "type" in out and isinstance(out["type"], str):
            out["type"] = _TYPE_ALIASES.get(out["type"], out["type"])
        return out
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    if isinstance(obj, str):
        return _sanitize_string(obj)
    return obj


def _load_snapshot(snapshot_name: str) -> Dict[str, Any]:
    path = SNAPSHOT_DIR / snapshot_name
    if not path.exists():
        raise AssertionError(f"Snapshot not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_snapshot(snapshot_name: str, data: Dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / snapshot_name
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


def _assert_subset(expected: Any, actual: Any, path: str = "$") -> None:
    """Assert that `expected` is a subset of `actual` (recursive)."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        for k, v in expected.items():
            assert k in actual, f"{path}: missing key '{k}'"
            _assert_subset(v, actual[k], f"{path}.{k}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual)}"
        assert len(actual) >= len(expected), f"{path}: expected list len >= {len(expected)}, got {len(actual)}"
        for i, v in enumerate(expected):
            _assert_subset(v, actual[i], f"{path}[{i}]")
        return

    assert expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


def assert_error_snapshot(snapshot_name: str, error_payload: Dict[str, Any], *, update: bool = False) -> None:
    """Assert that an error payload matches a stored snapshot (minimum contract)."""
    assert isinstance(error_payload, dict), "error_payload must be a dict"
    for field in ("type", "message", "details"):
        assert field in error_payload, f"Missing required error field: {field}"

    normalized_actual = _normalize(error_payload)

    if update:
        _save_snapshot(snapshot_name, normalized_actual)
        return

    normalized_expected = _normalize(_load_snapshot(snapshot_name))

    # Expected is the minimum contract; actual may include extra keys.
    _assert_subset(normalized_expected, normalized_actual, "$error")
