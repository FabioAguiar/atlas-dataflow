"""
tests/core/reporting/test_export_report_pdf_step.py

Cobertura obrigatoria — M7-02:
- Geracao do report.pdf
- Arquivo PDF com tamanho > 0 bytes
- Registro correto no StepResult / Manifest (via payload)
- Falha explicita quando report.md estiver ausente
- Falha explicita quando engine nao estiver configurada
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.steps.export.report_pdf import ExportReportPdfStep


def _ctx(tmp_path: Path, *, with_engine: bool = True, engine_name: str = "simple") -> RunContext:
    cfg = (
        {
            "steps": {
                "export.report_pdf": {
                    "engine": engine_name,
                    "engine_opts": {},
                }
            }
        }
        if with_engine
        else {"steps": {}}
    )

    return RunContext(
        run_id="test-run-pdf-001",
        created_at=datetime.now(timezone.utc),
        config=cfg,
        contract={},
        meta={"run_dir": str(tmp_path)},
    )


def _write_report_md(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "report.md").write_text(
        "# Execution Report\n\n## Executive Summary\nDummy report\n\n- item 1\n- item 2\n",
        encoding="utf-8",
    )


def test_pdf_is_generated(tmp_path: Path) -> None:
    _write_report_md(tmp_path)
    ctx = _ctx(tmp_path, engine_name="simple")

    step = ExportReportPdfStep()
    result = step.run(ctx)

    assert result.status.value == "success"

    pdf_path = tmp_path / "artifacts" / "report.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_pdf_payload_is_registered(tmp_path: Path) -> None:
    _write_report_md(tmp_path)
    ctx = _ctx(tmp_path, engine_name="simple")

    step = ExportReportPdfStep()
    result = step.run(ctx)

    payload = result.payload
    assert payload["engine"] == "simple"
    assert payload["bytes"] > 0
    assert payload["source_step"] == "export.report_md"


def test_missing_report_md_fails(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, engine_name="simple")

    step = ExportReportPdfStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "report.md" in result.summary.lower() or "not found" in result.summary.lower()


def test_missing_engine_config_fails(tmp_path: Path) -> None:
    _write_report_md(tmp_path)
    ctx = _ctx(tmp_path, with_engine=False)

    step = ExportReportPdfStep()
    result = step.run(ctx)

    assert result.status.value == "failed"
    assert "engine" in result.summary.lower()
