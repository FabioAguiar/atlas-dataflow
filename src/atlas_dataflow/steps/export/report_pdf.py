"""
src/atlas_dataflow/steps/export/report_pdf.py

Step canonico: export.report_pdf (v1)
Milestone: M7 — Reporting (MD/PDF)
Issue: M7-02 — Export report.md -> report.pdf (engine pluggable)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.export.report_pdf import convert_md_to_pdf


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _get_run_dir(ctx: RunContext) -> Path:
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    run_dir = md.get("run_dir") or md.get("tmp_path")
    if run_dir is None:
        raise ValueError("Missing required meta: run_dir (or tmp_path)")
    return Path(str(run_dir))


def _require_engine_cfg(cfg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    engine = cfg.get("engine")
    if not isinstance(engine, str) or not engine.strip():
        raise ValueError("Missing required config: steps.export.report_pdf.engine")
    engine_opts = cfg.get("engine_opts", {})
    if engine_opts is None:
        engine_opts = {}
    if not isinstance(engine_opts, dict):
        raise ValueError("Invalid config: steps.export.report_pdf.engine_opts must be a dict")
    return engine, engine_opts


@dataclass
class ExportReportPdfStep(Step):
    id: str = "export.report_pdf"
    kind: StepKind = StepKind.EXPORT
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", ["export.report_md"])

    def run(self, ctx: RunContext) -> StepResult:
        cfg = _get_step_cfg(ctx, self.id)

        # capture config for failure payload as well
        engine_cfg = cfg.get("engine") if isinstance(cfg, dict) else None
        engine_opts_cfg = cfg.get("engine_opts", {}) if isinstance(cfg, dict) else {}

        try:
            engine_name, engine_opts = _require_engine_cfg(cfg)

            run_dir = _get_run_dir(ctx)

            md_rel = "artifacts/report.md"
            pdf_rel = "artifacts/report.pdf"

            md_path = run_dir / md_rel
            pdf_path = run_dir / pdf_rel

            convert_md_to_pdf(
                md_path=md_path,
                pdf_path=pdf_path,
                engine_name=engine_name,
                engine_opts=engine_opts,
            )

            if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
                raise RuntimeError("PDF generation failed: report.pdf is empty")

            payload = {
                "source_step": "export.report_md",
                "source_md": md_rel,
                "engine": engine_name,
                "engine_opts": engine_opts,
                "bytes": pdf_path.stat().st_size,
            }

            ctx.set_artifact(self.id, payload)
            ctx.log(
                step_id=self.id,
                level="info",
                message="export.report_pdf completed",
                report_pdf_path=pdf_rel,
                bytes=payload["bytes"],
                engine=engine_name,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="export.report_pdf completed",
                metrics={},
                warnings=[],
                artifacts={"report_pdf": pdf_rel},
                payload=payload,
            )

        except Exception as e:
            fail_payload = {
                "engine": engine_cfg,
                "engine_opts": engine_opts_cfg if isinstance(engine_opts_cfg, dict) else {},
                "error": {"type": e.__class__.__name__, "message": str(e) or "error"},
            }
            ctx.log(
                step_id=self.id,
                level="error",
                message="export.report_pdf failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
                engine=engine_cfg,
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "export.report_pdf failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload=fail_payload,
            )


__all__ = ["ExportReportPdfStep"]
