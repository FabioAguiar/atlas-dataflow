import pytest

try:
    from atlas_dataflow.core.config.merge import deep_merge
    from atlas_dataflow.core.config.errors import ConfigTypeConflictError
except Exception as e:  # noqa: BLE001
    deep_merge = None
    ConfigTypeConflictError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing core config modules. Implement:\n"
            "- src/atlas_dataflow/core/config/merge.py (deep_merge)\n"
            "- src/atlas_dataflow/core/config/errors.py (ConfigTypeConflictError)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_merge_simple_override():
    _require_imports()
    base = {"a": 1, "b": 2}
    override = {"b": 99}
    out = deep_merge(base, override)
    assert out == {"a": 1, "b": 99}
    assert base == {"a": 1, "b": 2}
    assert override == {"b": 99}


def test_merge_nested_dict():
    _require_imports()
    base = {"engine": {"fail_fast": True, "log_level": "INFO"}}
    override = {"engine": {"log_level": "DEBUG"}}
    out = deep_merge(base, override)
    assert out == {"engine": {"fail_fast": True, "log_level": "DEBUG"}}


def test_merge_list_override_total():
    _require_imports()
    base = {"steps": {"enabled": ["ingest", "train"]}}
    override = {"steps": {"enabled": ["ingest"]}}
    out = deep_merge(base, override)
    assert out == {"steps": {"enabled": ["ingest"]}}


def test_merge_type_conflict_raises():
    _require_imports()
    if ConfigTypeConflictError is None:
        pytest.fail("ConfigTypeConflictError must be defined in errors.py")
    base = {"engine": {"fail_fast": True}}
    override = {"engine": "DEBUG"}  # dict vs str
    with pytest.raises(ConfigTypeConflictError):
        deep_merge(base, override)
