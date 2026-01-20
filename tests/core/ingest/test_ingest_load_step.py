from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.ingest.load import IngestLoadStep


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_ctx(path: Path) -> RunContext:
    return RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={"steps": {"ingest.load": {"enabled": True, "path": str(path)}}},
        contract={},
        meta={},
    )


def _make_csv(tmp_path: Path) -> Path:
    path = tmp_path / "dataset.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "value"])
        writer.writeheader()
        writer.writerow({"id": 1, "value": "A"})
        writer.writerow({"id": 2, "value": "B"})
    return path


@pytest.mark.parametrize("suffix", [".xlsx", ".txt", ".json"])
def test_ingest_load_unsupported_extension(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"dataset{suffix}"
    path.write_text("dummy", encoding="utf-8")

    ctx = _make_ctx(path)
    sr = IngestLoadStep().run(ctx)

    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "ValueError"
    assert "Unsupported file extension" in sr.payload["error"]["message"]


def test_ingest_load_file_not_found(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    ctx = _make_ctx(path)

    sr = IngestLoadStep().run(ctx)

    assert sr.status == StepStatus.FAILED
    assert sr.payload["error"]["type"] == "FileNotFoundError"


def test_ingest_load_csv_success(tmp_path: Path) -> None:
    path = _make_csv(tmp_path)
    ctx = _make_ctx(path)

    sr = IngestLoadStep().run(ctx)

    assert sr.status == StepStatus.SUCCESS
    assert ctx.has_artifact("data.raw_rows")

    rows = ctx.get_artifact("data.raw_rows")
    assert isinstance(rows, list)
    assert len(rows) == 2

    assert sr.artifacts["source_type"] == "csv"
    assert sr.artifacts["source_path"] == str(path.resolve())
    assert sr.artifacts["source_sha256"] == _sha256_of_file(path)
    assert sr.artifacts["source_bytes"] > 0


def test_ingest_load_registers_origin_and_hash(tmp_path: Path) -> None:
    path = _make_csv(tmp_path)
    ctx = _make_ctx(path)

    sr = IngestLoadStep().run(ctx)

    assert sr.status == StepStatus.SUCCESS

    artifacts = sr.artifacts
    assert artifacts["source_path"] == str(path.resolve())
    assert artifacts["source_type"] == "csv"
    assert artifacts["source_sha256"] == _sha256_of_file(path)
    assert artifacts["source_bytes"] > 0


def test_ingest_load_parquet_success(tmp_path: Path) -> None:
    # Skip automaticamente se dependências de parquet não existirem no ambiente
    pd = pytest.importorskip("pandas")

    path = tmp_path / "dataset.parquet"
    df = pd.DataFrame([{"id": 1, "value": "A"}, {"id": 2, "value": "B"}])

    try:
        df.to_parquet(path)
    except Exception as e:
        pytest.skip(f"Parquet engine not available: {e}")

    ctx = _make_ctx(path)
    sr = IngestLoadStep().run(ctx)

    assert sr.status == StepStatus.SUCCESS
    assert ctx.has_artifact("data.raw_rows")

    rows = ctx.get_artifact("data.raw_rows")
    assert isinstance(rows, list)
    assert len(rows) == 2

    assert sr.artifacts["source_type"] == "parquet"
    assert sr.artifacts["source_path"] == str(path.resolve())
    assert sr.artifacts["source_sha256"] == _sha256_of_file(path)
    assert sr.artifacts["source_bytes"] > 0
