"""
Project Spec S0254: focused tests for the generic Atlas-owned Rdatasets
source acquisition helper, `pipeline.dataset_acquisition`.

Uses temporary repository fixtures and monkeypatched
`urllib.request.urlopen` only. No real network call is permitted; no
third-party HTTP dependency is used or required.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from pipeline import dataset_acquisition
from pipeline.dataset_acquisition import DatasetAcquisitionError, acquire_rdataset_csv


_SOURCE_MODULE_TEXT = Path(dataset_acquisition.__file__).read_text(encoding="utf-8")


class _FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._data


def _rdatasets_csv_bytes(rows: list[tuple[str, str]]) -> bytes:
    lines = ['"","time","value"']
    for index, (time_value, value) in enumerate(rows, start=1):
        lines.append(f'"{index}",{time_value},{value}')
    return ("\n".join(lines) + "\n").encode("utf-8")


def _valid_response_bytes(row_count: int = 3) -> bytes:
    return _rdatasets_csv_bytes(
        [(f"1920.{i:03d}", f"{40 + i}.5") for i in range(row_count)]
    )


def _no_network_urlopen(*_args, **_kwargs):
    raise AssertionError("network must not be called for this test")


def _acquire(repo_root: Path, destination_relative_path: str = "data/raw/nottem/dataset.csv", **overrides):
    kwargs = dict(
        dataset_name="nottem",
        package="datasets",
        destination_relative_path=destination_relative_path,
        expected_columns=["time", "value"],
        expected_row_count=3,
        repo_root=repo_root,
    )
    kwargs.update(overrides)
    return acquire_rdataset_csv(**kwargs)


def test_valid_response_materializes_normalized_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes()),
    )
    result = _acquire(tmp_path)

    destination = tmp_path / "data/raw/nottem/dataset.csv"
    assert destination.is_file()
    assert destination.read_text(encoding="utf-8").splitlines()[0] == "time,value"
    assert result["materialization_status"] == "materialized"


def test_rdatasets_transport_index_column_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes()),
    )
    _acquire(tmp_path)
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    header = destination.read_text(encoding="utf-8").splitlines()[0]
    assert header == "time,value"
    assert "1," not in header


def test_ordered_expected_columns_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes()),
    )
    result = _acquire(tmp_path)
    assert result["ordered_columns"] == ["time", "value"]


def test_expected_row_count_is_enforced_on_materialization(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes(row_count=5)),
    )
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)


def test_source_reference_is_derived_as_package_dataset_name(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes()),
    )
    result = _acquire(tmp_path)
    assert result["source_reference"] == "datasets::nottem"


def test_relative_path_and_sha256_are_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes()),
    )
    result = _acquire(tmp_path)
    assert result["relative_path"] == "data/raw/nottem/dataset.csv"
    assert isinstance(result["sha256"], str)
    assert len(result["sha256"]) == 64
    int(result["sha256"], 16)


def test_valid_existing_destination_is_reused_with_zero_network_calls(tmp_path, monkeypatch):
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    destination.parent.mkdir(parents=True)
    destination.write_text("time,value\n1920.0,40.5\n1920.1,41.5\n1920.2,42.5\n", encoding="utf-8")

    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _no_network_urlopen)
    result = _acquire(tmp_path)
    assert result["materialization_status"] == "reused"
    assert result["row_count"] == 3


def test_malformed_existing_destination_fails_closed_and_is_not_overwritten(tmp_path, monkeypatch):
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    destination.parent.mkdir(parents=True)
    original_bytes = b"time,value\n1920.0,40.5\n"
    destination.write_bytes(original_bytes)

    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _no_network_urlopen)
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)
    assert destination.read_bytes() == original_bytes


def test_path_traversal_destination_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _no_network_urlopen)
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path, destination_relative_path="../outside/dataset.csv")


def test_path_traversal_absolute_destination_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _no_network_urlopen)
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path, destination_relative_path="/etc/passwd")


@pytest.mark.parametrize(
    "field, value",
    [
        ("dataset_name", "../nottem"),
        ("dataset_name", "foo/bar"),
        ("dataset_name", "https://example.invalid/file.csv"),
        ("package", "../datasets"),
        ("package", "foo/bar"),
        ("package", ""),
    ],
)
def test_path_like_dataset_or_package_identifiers_are_rejected(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _no_network_urlopen)
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path, **{field: value})


def test_http_network_failure_raises_bounded_acquisition_error(tmp_path, monkeypatch):
    def _raise_url_error(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dataset_acquisition.urllib.request, "urlopen", _raise_url_error)
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)


def test_invalid_utf8_response_raises_bounded_acquisition_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(b"\xff\xfe\x00invalid"),
    )
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)


def test_invalid_csv_source_shape_raises_bounded_acquisition_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(b"only_one_column\n1\n2\n"),
    )
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)


def test_wrong_source_columns_fail_before_final_file_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_rdatasets_csv_bytes([("1920.0", "40.5")]).replace(b"value", b"other")),
    )
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)
    assert not destination.exists()


def test_wrong_row_count_fails_before_final_file_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes(row_count=1)),
    )
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)
    assert not destination.exists()


def test_failed_materialization_leaves_no_partial_final_dataset_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dataset_acquisition.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_valid_response_bytes(row_count=99)),
    )
    destination = tmp_path / "data/raw/nottem/dataset.csv"
    with pytest.raises(DatasetAcquisitionError):
        _acquire(tmp_path)
    assert not destination.exists()
    if destination.parent.exists():
        assert list(destination.parent.glob("*")) == []


def test_no_external_study_path_is_read():
    for forbidden in (
        "dataset-study",
        "/home/",
        "/workspace/",
        "statsmodels",
        "get_rdataset",
    ):
        assert forbidden not in _SOURCE_MODULE_TEXT


def test_no_third_party_network_or_download_dependency_is_required():
    for forbidden in ("import requests", "import httpx", "from requests", "from httpx"):
        assert forbidden not in _SOURCE_MODULE_TEXT
    assert "import urllib.request" in _SOURCE_MODULE_TEXT


def test_helper_is_generic_and_contains_no_nottingham_conditional():
    assert "nottem" not in _SOURCE_MODULE_TEXT
    assert 'dataset_slug == "nottem"' not in _SOURCE_MODULE_TEXT
