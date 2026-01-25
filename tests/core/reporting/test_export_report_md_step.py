
"""
tests/core/reporting/test_export_report_md_step.py

Cobertura obrigatória (M7-01):
- Geração do arquivo report.md
- Presença das seções mínimas
- Determinismo (mesmo Manifest => mesmo report)
- Coerência com Manifest (decisão/métricas/artefatos) quando presentes
- Falha explícita quando Manifest estiver ausente
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.steps.export.report_md import ExportReportMdStep


def _minimal_manifest() -> dict:
    return {
        "run": {
            "run_id": "test-run-001",
            "started_at": "2026-01-01T00:00:00+00:00",
            "atlas_version": "0.1.0",
        },
        "inputs": {
            "config_hash": "cfg123",
            "contract_hash": "ctr456",
        },
        "steps": {
            "evaluate.metrics": {
                "step_id": "evaluate.metrics",
                "kind": "evaluate",
                "status": "success",
                "summary": "metrics computed",
                "metrics": {"accuracy": 0.91, "f1_score": 0.88},
                "warnings": [],
                "artifacts": {},
                "payload": {"metrics_version": "v1"},
            },
            "evaluate.model_selection": {
                "step_id": "evaluate.model_selection",
                "kind": "evaluate",
                "status": "success",
                "summary": "champion selected",
                "metrics": {},
                "warnings": [],
                "artifacts": {},
                "payload": {"champion_model": "logistic_regression"},
            },
            "export.model_card": {
                "step_id": "export.model_card",
                "kind": "export",
                "status": "success",
                "summary": "model card generated",
                "metrics": {},
                "warnings": [],
                "artifacts": {"model_card_md": "artifacts/model_card.md"},
                "payload": {"model_card_path": "artifacts/model_card.md"},
            },
        },
        "events": [],
    }


def _ctx(tmp_path: Path, manifest: dict | None) -> RunContext:
    ctx = RunContext(
        run_id="test-run-001",
        created_at=datetime.now(timezone.utc),
        config={"steps": {}},
        contract={},
        meta={"run_dir": str(tmp_path)},
    )
    if manifest is not None:
        ctx.meta["manifest"] = manifest
    return ctx


def test_report_md_is_generated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _minimal_manifest())
    step = ExportReportMdStep()

    result = step.run(ctx)
    assert result.status.value == "success"

    report_path = tmp_path / "artifacts" / "report.md"
    assert report_path.exists()

    content = report_path.read_text(encoding="utf-8")
    assert "# Execution Report" in content
    assert "## Executive Summary" in content
    assert "## Metrics" in content


def test_report_is_deterministic(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _minimal_manifest())
    step = ExportReportMdStep()

    step.run(ctx)
    first = (tmp_path / "artifacts" / "report.md").read_text(encoding="utf-8")

    step.run(ctx)
    second = (tmp_path / "artifacts" / "report.md").read_text(encoding="utf-8")

    assert first == second


def test_missing_manifest_returns_failed(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, manifest=None)
    step = ExportReportMdStep()

    result = step.run(ctx)
    assert result.status.value == "failed"
    assert "Missing required meta: manifest" in result.summary


def test_report_mentions_manifest_artifacts_and_decision(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _minimal_manifest())
    step = ExportReportMdStep()

    step.run(ctx)
    content = (tmp_path / "artifacts" / "report.md").read_text(encoding="utf-8")

    assert "artifacts/model_card.md" in content
    assert "evaluate.model_selection.payload" in content
    assert "champion_model" in content


def test_all_required_sections_present(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _minimal_manifest())
    step = ExportReportMdStep()

    step.run(ctx)
    content = (tmp_path / "artifacts" / "report.md").read_text(encoding="utf-8")

    required_sections = [
        "# Execution Report",
        "## Executive Summary",
        "## Pipeline Overview",
        "## Decisions & Outcomes",
        "## Metrics",
        "## Generated Artifacts",
        "## Traceability",
        "## Limitations",
        "## Execution Metadata",
    ]
    for section in required_sections:
        assert section in content
