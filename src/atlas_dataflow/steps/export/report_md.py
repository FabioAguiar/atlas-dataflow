
"""
src/atlas_dataflow/steps/export/report_md.py

Step canônico: export.report_md (v1)

Gera `report.md` de forma determinística e auditável,
usando exclusivamente fontes de verdade:
- Manifest final (meta["manifest"])

Não faz:
- treino
- recalcular métricas
- inferir decisões ausentes
- acessar artefatos fora do Manifest
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.report.report_md import generate_report_md


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _get_run_dir(ctx: RunContext) -> str:
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    run_dir = md.get("run_dir") or md.get("tmp_path")
    if run_dir is None:
        raise ValueError("Missing required meta: run_dir (or tmp_path)")
    return str(run_dir)


def _require_manifest(ctx: RunContext) -> Dict[str, Any]:
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    manifest = md.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Missing required meta: manifest (final Manifest dict)")
    return manifest


@dataclass
class ExportReportMdStep(Step):
    """Gera `report.md` a partir do Manifest (v1)."""

    id: str = "export.report_md"
    kind: StepKind = StepKind.EXPORT
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # v1: deve rodar após export/model_card e métricas estarem consolidadas no Manifest
        object.__setattr__(self, "depends_on", ["export.model_card", "evaluate.metrics", "evaluate.model_selection"])

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            filename = cfg.get("filename", "report.md")
            if not isinstance(filename, str) or not filename.strip():
                raise ValueError("Invalid config: export.report_md.filename must be a non-empty string")

            run_dir = Path(_get_run_dir(ctx))
            out_path = run_dir / "artifacts" / filename
            rel_path = f"artifacts/{filename}"

            manifest = _require_manifest(ctx)

            content = generate_report_md(manifest)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")

            payload = {"report_md_path": rel_path, "bytes": out_path.stat().st_size}

            ctx.set_artifact(self.id, payload)
            ctx.log(step_id=self.id, level="info", message="export.report_md completed", report_md_path=rel_path, bytes=payload["bytes"])

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="export.report_md completed",
                metrics={},
                warnings=[],
                artifacts={"report_md": rel_path},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="export.report_md failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "export.report_md failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["ExportReportMdStep"]
