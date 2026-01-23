"""Step canônico: export.inference_bundle (v1).

Gera um **bundle de inferência autocontido** a partir do resultado do pipeline
de treino/avaliação (M5), congelando decisões relevantes:

- preprocess (persistido via PreprocessStore)
- modelo campeão (objeto treinado no RunContext)
- contrato interno congelado (Internal Contract v1)
- métricas finais do campeão
- metadados forenses (run_id, timestamps, hashes)

Alinhado a:
- docs/spec/export.inference_bundle.v1.md
- docs/spec/evaluate.model_selection.v1.md
- docs/spec/evaluate.metrics.v1.md
- docs/spec/representation.preprocess.v1.md
- docs/spec/internal_contract.v1.md
- docs/traceability.md

Limites explícitos (v1):
- NÃO treina modelos
- NÃO recalcula preprocess
- NÃO reconstrói contrato
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import hashlib
import json

from atlas_dataflow.core.contract.schema import validate_internal_contract_v1
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.persistence.preprocess_store import PreprocessStore
from atlas_dataflow.deployment.inference_bundle import (
    InferenceBundleV1,
    save_inference_bundle_v1,
)

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None  # type: ignore


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


def _sha256_json(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_artifact(ctx: RunContext, key: str) -> Any:
    if not ctx.has_artifact(key):
        raise ValueError(f"Missing required artifact: {key}")
    return ctx.get_artifact(key)


def _require_model(ctx: RunContext) -> Any:
    # v1: usa o último estimador treinado presente no RunContext.
    if ctx.has_artifact("model.champion"):
        return ctx.get_artifact("model.champion")
    if ctx.has_artifact("model.best_estimator"):
        return ctx.get_artifact("model.best_estimator")
    if ctx.has_artifact("model.trained"):
        return ctx.get_artifact("model.trained")
    raise ValueError("Missing required artifact: model.best_estimator (or model.trained / model.champion)")


def _require_selection(ctx: RunContext) -> Dict[str, Any]:
    obj = _require_artifact(ctx, "eval.model_selection")
    if not isinstance(obj, dict):
        raise ValueError("Invalid artifact: eval.model_selection must be a dict payload")
    sel = obj.get("selection")
    if not isinstance(sel, dict):
        raise ValueError("Invalid eval.model_selection payload: missing selection")
    mid = sel.get("champion_model_id")
    if not isinstance(mid, str) or not mid.strip():
        raise ValueError("Invalid eval.model_selection payload: champion_model_id is required")
    return obj


def _extract_champion_metrics(*, ctx: RunContext, champion_model_id: str) -> Dict[str, Any]:
    obj = _require_artifact(ctx, "eval.metrics")
    payloads: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        payloads = [obj]
    elif isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        payloads = obj
    else:
        raise ValueError("Invalid artifact: eval.metrics must be dict or list[dict]")

    # v1: exige model_id explícito (sem inferência).
    for p in payloads:
        mid = p.get("model_id")
        if mid == champion_model_id:
            metrics = p.get("metrics")
            if isinstance(metrics, dict):
                return metrics
            raise ValueError(f"Invalid eval.metrics payload for model_id={champion_model_id}: metrics must be a dict")

    raise ValueError(f"Champion metrics not found in eval.metrics for model_id={champion_model_id}")


@dataclass
class ExportInferenceBundleStep(Step):
    """Exporta um bundle autocontido para inferência (joblib, v1)."""

    id: str = "export.inference_bundle"
    kind: StepKind = StepKind.EXPORT
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", ["evaluate.model_selection"])

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            fmt = cfg.get("format", "joblib")
            if fmt != "joblib":
                raise ValueError("Invalid config: export.inference_bundle.format must be 'joblib' in v1")

            run_dir = _get_run_dir(ctx)
            run_dir_p = Path(run_dir)

            # ---- contrato (congelado) ----
            contract_dict = ctx.contract
            validate_internal_contract_v1(contract_dict)  # falha explícita se inválido

            # ---- decisão do campeão ----
            sel_payload = _require_selection(ctx)
            champion_model_id = sel_payload["selection"]["champion_model_id"]

            # ---- métricas do campeão ----
            champion_metrics = _extract_champion_metrics(ctx=ctx, champion_model_id=champion_model_id)

            # ---- preprocess (persistido) ----
            preprocess = PreprocessStore(run_dir=run_dir_p).load()

            # ---- modelo (objeto treinado) ----
            model = _require_model(ctx)

            # ---- bundle paths ----
            bundle_path = run_dir_p / "artifacts" / "inference_bundle.joblib"
            bundle_rel_path = "artifacts/inference_bundle.joblib"

            # ---- metadata forense ----
            created_at = ctx.created_at.isoformat() if hasattr(ctx.created_at, "isoformat") else str(ctx.created_at)
            exported_at = datetime.now(timezone.utc).isoformat()

            meta: Dict[str, Any] = {
                "run_id": ctx.run_id,
                "created_at": created_at,
                "exported_at": exported_at,
                "format": "joblib",
                "bundle_version": "v1",
                "champion_model_id": champion_model_id,
                "contract_version": str(contract_dict.get("contract_version", "")),
                "hashes": {
                    "contract_sha256": _sha256_json(contract_dict),
                },
            }

            bundle = InferenceBundleV1(
                preprocess=preprocess,
                model=model,
                contract=dict(contract_dict),
                metrics=dict(champion_metrics),
                metadata=meta,
            )

            save_meta = save_inference_bundle_v1(bundle=bundle, path=bundle_path)
            meta["hashes"]["bundle_sha256"] = save_meta["bundle_hash"]

            payload: Dict[str, Any] = {
                "bundle_path": bundle_rel_path,
                "bundle_hash": save_meta["bundle_hash"],
                "model_id": champion_model_id,
                "contract_version": str(contract_dict.get("contract_version", "")),
            }

            ctx.set_artifact("export.inference_bundle", payload)

            ctx.log(
                step_id=self.id,
                level="info",
                message="export.inference_bundle completed",
                bundle_path=bundle_rel_path,
                bundle_hash=save_meta["bundle_hash"],
                model_id=champion_model_id,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="export.inference_bundle completed",
                metrics={},
                warnings=[],
                artifacts={
                    "bundle": bundle_rel_path,
                },
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="export.inference_bundle failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "export.inference_bundle failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["ExportInferenceBundleStep"]
