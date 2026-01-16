import pytest
from pathlib import Path

try:
    from atlas_dataflow.core.config.loader import load_config
    from atlas_dataflow.core.config.errors import (
        DefaultsNotFoundError,
        InvalidConfigRootTypeError,
        UnsupportedConfigFormatError,
    )
except Exception as e:  # noqa: BLE001
    load_config = None
    DefaultsNotFoundError = None
    InvalidConfigRootTypeError = None
    UnsupportedConfigFormatError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing loader/errors modules. Implement:\n"
            "- src/atlas_dataflow/core/config/loader.py (load_config)\n"
            "- src/atlas_dataflow/core/config/errors.py (typed exceptions)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_missing_defaults_raises(tmp_path: Path):
    _require_imports()
    if DefaultsNotFoundError is None:
        pytest.fail("DefaultsNotFoundError must be defined in errors.py")
    missing = tmp_path / "defaults.yaml"
    with pytest.raises(DefaultsNotFoundError):
        load_config(defaults_path=str(missing), local_path=None)


def test_missing_local_is_ok(tmp_path: Path, project_like_config_defaults_yaml):
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")

    missing_local = tmp_path / "local.yaml"
    out = load_config(defaults_path=str(defaults), local_path=str(missing_local))
    assert out["engine"]["fail_fast"] is True
    assert out["engine"]["log_level"] == "INFO"
    assert out["steps"]["train"]["enabled"] is True


def test_load_defaults_only(tmp_path: Path, project_like_config_defaults_yaml):
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")

    out = load_config(defaults_path=str(defaults), local_path=None)
    assert out["engine"]["fail_fast"] is True
    assert out["engine"]["log_level"] == "INFO"
    assert out["steps"]["ingest"]["enabled"] is True


def test_load_defaults_and_local(tmp_path: Path, project_like_config_defaults_yaml, project_like_config_local_yaml):
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    local = tmp_path / "local.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")
    local.write_text(project_like_config_local_yaml, encoding="utf-8")

    out = load_config(defaults_path=str(defaults), local_path=str(local))
    assert out["engine"]["log_level"] == "DEBUG"
    assert out["steps"]["train"]["enabled"] is False
    assert out["engine"]["fail_fast"] is True
    assert out["steps"]["ingest"]["enabled"] is True


def test_invalid_root_type_raises(tmp_path: Path):
    _require_imports()
    if InvalidConfigRootTypeError is None:
        pytest.fail("InvalidConfigRootTypeError must be defined in errors.py")

    defaults = tmp_path / "defaults.yaml"
    defaults.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(InvalidConfigRootTypeError):
        load_config(defaults_path=str(defaults), local_path=None)


def test_unsupported_extension_raises(tmp_path: Path):
    _require_imports()
    if UnsupportedConfigFormatError is None:
        pytest.fail("UnsupportedConfigFormatError must be defined in errors.py")

    defaults = tmp_path / "defaults.toml"
    defaults.write_text("engine = { fail_fast = true }\n", encoding="utf-8")
    with pytest.raises(UnsupportedConfigFormatError):
        load_config(defaults_path=str(defaults), local_path=None)
