"""Step canônico: export.model_card (v1).

Gera o arquivo `model_card.md` de forma determinística e auditável,
usando exclusivamente fontes de verdade:

- Manifest final (meta["manifest"])
- Contrato interno congelado (ctx.contract)
- Métricas finais do campeão (via Manifest: steps["evaluate.metrics"].metrics)

Não faz:
- treino
- recalcular métricas
- inferência de informações não registradas
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from atlas_dataflow.core.contract.schema import validate_internal_contract_v1
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.export.model_card import ModelCardInputs, ModelCardError, save_model_card_md


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


def _extract_champion_metrics_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    steps = manifest.get("steps")
    if not isinstance(steps, dict):
        raise ValueError("Invalid manifest: missing steps")
    ev = steps.get("evaluate.metrics")
    if not isinstance(ev, dict):
        raise ValueError("Invalid manifest: missing evaluate.metrics step")
    metrics = ev.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("Invalid manifest: evaluate.metrics.metrics must be a non-empty dict")
    return metrics


@dataclass
class ExportModelCardStep(Step):
    """Gera `model_card.md` a partir do Manifest (v1)."""

    id: str = "export.model_card"
    kind: StepKind = StepKind.EXPORT
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", ["export.inference_bundle", "evaluate.metrics"])

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            filename = cfg.get("filename", "model_card.md")
            if not isinstance(filename, str) or not filename.strip():
                raise ValueError("Invalid config: export.model_card.filename must be a non-empty string")

            run_dir = Path(_get_run_dir(ctx))
            out_path = run_dir / "artifacts" / filename
            rel_path = f"artifacts/{filename}"

            # fontes de verdade
            manifest = _require_manifest(ctx)
            contract = ctx.contract
            validate_internal_contract_v1(contract)

            champion_metrics = _extract_champion_metrics_from_manifest(manifest)

            inputs = ModelCardInputs(
                manifest=manifest,
                contract=dict(contract),
                champion_metrics=dict(champion_metrics),
                export_payload=None,
            )

            save_meta = save_model_card_md(inputs=inputs, path=out_path)

            payload = {"model_card_path": rel_path, "bytes": save_meta["bytes"]}

            ctx.set_artifact("export.model_card", payload)
            ctx.log(
                step_id=self.id,
                level="info",
                message="export.model_card completed",
                model_card_path=rel_path,
                bytes=save_meta["bytes"],
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="export.model_card completed",
                metrics={},
                warnings=[],
                artifacts={"model_card_md": rel_path},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="export.model_card failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "export.model_card failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["ExportModelCardStep"]
