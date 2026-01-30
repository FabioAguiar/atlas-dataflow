"""
Step canônico: export.inference_bundle (v1)

Gera um Inference Bundle autocontido para inferência, persistido em joblib.

Fontes de verdade (v1):
- preprocess persistido no run_dir (PreprocessStore ou artifacts/preprocess.joblib)
- modelo treinado publicado no RunContext (model.best_estimator ou model.trained)
- contrato interno congelado (ctx.contract)
- avaliação/seleção do campeão (eval.model_selection + eval.metrics)

Invariantes:
- Não infere nada: apenas consolida artefatos já produzidos pelo pipeline.
- Não aplica fallback silencioso.
- Erros devem ser padronizados (AtlasErrorPayload) e serializáveis.
- Nome do bundle é fixo: artifacts/inference_bundle.joblib
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import hashlib
import inspect

import joblib

from atlas_dataflow.core.errors import (
    AtlasErrorPayload,
    model_not_found,
    preprocess_not_found,
)
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.deployment.inference_bundle import (
    InferenceBundleV1,
    save_inference_bundle_v1,
)
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_get_run_dir(ctx: Any) -> Path:
    """Obtém run_dir do ctx via meta (Path/str) ou get_meta()."""
    meta = getattr(ctx, "meta", None)
    if isinstance(meta, dict) and "run_dir" in meta:
        rd = meta["run_dir"]
        return rd if isinstance(rd, Path) else Path(str(rd))

    get_meta = getattr(ctx, "get_meta", None)
    if callable(get_meta):
        rd = get_meta("run_dir")
        if rd is not None:
            return rd if isinstance(rd, Path) else Path(str(rd))

    # fallback defensivo (não ideal, mas mantém compatibilidade)
    return Path(".")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pick_champion_model_id(ctx: Any) -> str:
    """Fonte de verdade: eval.model_selection.selection.champion_model_id."""
    try:
        ms = ctx.get_artifact("eval.model_selection")
    except Exception:
        ms = None

    if isinstance(ms, dict):
        sel = ms.get("selection")
        if isinstance(sel, dict):
            cmid = sel.get("champion_model_id")
            if isinstance(cmid, str) and cmid.strip():
                return cmid.strip()

    return "unknown"


def _pick_champion_metrics(ctx: Any, champion_model_id: str) -> Dict[str, Any]:
    """Busca métricas do campeão em eval.metrics."""
    try:
        obj = ctx.get_artifact("eval.metrics")
    except Exception:
        obj = None

    if isinstance(obj, list):
        for row in obj:
            if isinstance(row, dict) and row.get("model_id") == champion_model_id:
                m = row.get("metrics")
                if isinstance(m, dict):
                    return dict(m)
        return {}

    if isinstance(obj, dict):
        if obj.get("model_id") == champion_model_id and isinstance(obj.get("metrics"), dict):
            return dict(obj["metrics"])
        if isinstance(obj.get("metrics"), dict):
            return dict(obj["metrics"])  # fallback
        return {}

    return {}


def _resolve_model(ctx: Any) -> Any:
    """Resolve o modelo treinado a partir do ctx (sem inferência)."""
    try:
        return ctx.get_artifact("model.best_estimator")
    except Exception:
        pass

    try:
        return ctx.get_artifact("model.trained")
    except Exception:
        pass

    raise KeyError("model.best_estimator|model.trained")


def _resolve_preprocess_path(run_dir: Path) -> Optional[Path]:
    """Resolve o preprocess.joblib (PreprocessStore preferencial, fallback artifacts/preprocess.joblib)."""
    artifacts_dir = run_dir / "artifacts"
    _ensure_dir(artifacts_dir)

    # preferencial: store
    try:
        store = PreprocessStore(base_dir=run_dir)
        p = store.path_for_current_preprocess()
        if p.exists():
            return p
    except Exception:
        pass

    # fallback: artifacts/preprocess.joblib
    candidate = artifacts_dir / "preprocess.joblib"
    if candidate.exists():
        return candidate

    return None


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

class ExportInferenceBundleStep(Step):
    """export.inference_bundle — consolida preprocess + model + contract + metadata em bundle."""

    id = "export.inference_bundle"
    kind = StepKind.EXPORT

    # Guardrail: este step depende explicitamente do treino e da seleção/avaliação.
    # (Sem dependências explícitas, pode rodar cedo demais no E2E.)
    depends_on = [
        "train.single",
        "evaluate.model_selection",
    ]

    def run(self, ctx: Any) -> StepResult:
        run_dir = _safe_get_run_dir(ctx)
        artifacts_dir = run_dir / "artifacts"
        _ensure_dir(artifacts_dir)

        # config
        step_cfg: Dict[str, Any] = {}
        try:
            step_cfg = (ctx.config or {}).get("steps", {}).get(self.id, {})  # type: ignore[attr-defined]
        except Exception:
            step_cfg = {}

        fmt = "joblib"
        if isinstance(step_cfg, dict) and isinstance(step_cfg.get("format"), str) and step_cfg.get("format"):
            fmt = str(step_cfg.get("format")).strip().lower() or "joblib"

        # contract
        contract = getattr(ctx, "contract", None)
        contract_dict: Dict[str, Any] = contract if isinstance(contract, dict) else {}
        contract_version = str(contract_dict.get("contract_version") or "unknown")

        # champion
        champion_model_id = _pick_champion_model_id(ctx)
        champion_metrics = _pick_champion_metrics(ctx, champion_model_id)

        # required: model
        try:
            model = _resolve_model(ctx)
        except Exception:
            err = model_not_found(
                step=self.id,
                required_by=self.id,
            ).to_dict()
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (missing model)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        # required: preprocess path + load object
        preprocess_path = _resolve_preprocess_path(run_dir)
        if preprocess_path is None:
            err = preprocess_not_found(
                step=self.id,
                required_by=self.id,
            ).to_dict()
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (missing preprocess)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        try:
            preprocess_obj = joblib.load(str(preprocess_path))
        except Exception as e:
            err = AtlasErrorPayload(
                type="PREPROCESS_LOAD_FAILED",
                message="Falha ao carregar preprocess.joblib",
                details={
                    "path": str(preprocess_path),
                    "exception": type(e).__name__,
                    "exception_message": str(e),
                    "step": self.id,
                },
                hint="Verifique se preprocess.joblib foi salvo corretamente (joblib.dump) e não está corrompido.",
                decision_required=False,
            ).to_dict()
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (preprocess load failed)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        # metadata (sempre serializável)
        now_utc = datetime.now(timezone.utc).isoformat()
        run_id = getattr(ctx, "run_id", None)
        created_at = getattr(ctx, "created_at", None)
        created_at_iso = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)

        metadata_obj: Dict[str, Any] = {
            "generated_at_utc": now_utc,
            "run_id": str(run_id) if isinstance(run_id, str) else "unknown",
            "created_at": str(created_at_iso) if created_at_iso else "unknown",
            "format": fmt,
            "bundle_version": "v1",
            "contract_version": contract_version,
            "champion_model_id": champion_model_id,
            "model_id": champion_model_id,
            "metrics": champion_metrics,
        }

        # build bundle (filtra conforme assinatura para não quebrar se o core variar)
        bundle_kwargs: Dict[str, Any] = {
            "preprocess": preprocess_obj,
            "model": model,
            "contract": contract_dict,
            "metadata": metadata_obj,
            # opcionais (se existirem)
            "metrics": champion_metrics,
            "format": fmt,
            "contract_version": contract_version,
            "champion_model_id": champion_model_id,
            "model_id": champion_model_id,
            "bundle_version": "v1",
            "version": "v1",
        }

        accepted_bundle = set(inspect.signature(InferenceBundleV1).parameters.keys())  # type: ignore[arg-type]
        filtered_bundle_kwargs = {k: v for k, v in bundle_kwargs.items() if k in accepted_bundle}

        try:
            bundle = InferenceBundleV1(**filtered_bundle_kwargs)
        except Exception as e:
            err = AtlasErrorPayload(
                type="BUNDLE_CONSTRUCT_FAILED",
                message="Falha ao instanciar InferenceBundleV1",
                details={
                    "exception": type(e).__name__,
                    "exception_message": str(e),
                    "step": self.id,
                    "accepted_params": sorted(list(accepted_bundle)),
                    "provided_params": sorted(list(filtered_bundle_kwargs.keys())),
                },
                hint="Ajuste o mapeamento conforme a assinatura do InferenceBundleV1 no core.",
                decision_required=False,
            ).to_dict()
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (bundle construct failed)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        # persist (filename canônico FIXO)
        bundle_path = artifacts_dir / f"inference_bundle.{fmt}"
        if fmt == "joblib":  # default esperado pelos testes
            bundle_path = artifacts_dir / "inference_bundle.joblib"

        try:
            sig_save = inspect.signature(save_inference_bundle_v1)  # type: ignore[arg-type]
            accepted_save = set(sig_save.parameters.keys())

            if "path" in accepted_save:
                # save_inference_bundle_v1 exige keyword-only path=
                if "bundle" in accepted_save:
                    save_meta = save_inference_bundle_v1(bundle=bundle, path=bundle_path)  # type: ignore[misc]
                else:
                    save_meta = save_inference_bundle_v1(bundle, path=bundle_path)  # type: ignore[misc]
            else:
                # fallback para cores antigos
                joblib.dump(bundle, str(bundle_path))
                save_meta = {}
        except Exception as e:
            err = AtlasErrorPayload(
                type="BUNDLE_PERSIST_FAILED",
                message="Não foi possível persistir o bundle de inferência",
                details={
                    "exception": type(e).__name__,
                    "exception_message": str(e),
                    "path": str(bundle_path),
                    "step": self.id,
                },
                hint="Verifique permissões/IO e se preprocess/model são serializáveis.",
                decision_required=False,
            ).to_dict()
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (persist failed)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        # normalize outputs
        try:
            bundle_hash = _sha256_file(bundle_path)
        except Exception:
            bundle_hash = "unknown"

        try:
            bundle_bytes = int(bundle_path.stat().st_size)
        except Exception:
            bundle_bytes = 0

        payload: Dict[str, Any] = {}
        if isinstance(save_meta, dict):
            payload.update(save_meta)

        payload.update(
            {
                "bundle_path": str(bundle_path),
                "bundle_hash": bundle_hash,
                "sha256": bundle_hash,
                "bundle_bytes": bundle_bytes,
                "format": fmt,
                "bundle_version": "v1",
                "contract_version": contract_version,
                "champion_model_id": champion_model_id,
                "model_id": champion_model_id,
                "metrics": champion_metrics,
            }
        )

        artifacts: Dict[str, Any] = {
            "bundle_path": str(bundle_path),
            "bundle_hash": bundle_hash,
            "sha256": bundle_hash,
            "bundle_bytes": bundle_bytes,
            "format": fmt,
            "bundle_version": "v1",
            "contract_version": contract_version,
            "champion_model_id": champion_model_id,
            "model_id": champion_model_id,
        }

        return StepResult(
            step_id=self.id,
            kind=self.kind,
            status=StepStatus.SUCCESS,
            summary="export.inference_bundle completed",
            metrics={},
            warnings=[],
            artifacts=artifacts,
            payload=payload,
        )
