"""
Step canônico: export.inference_bundle (v1).

Gera um Inference Bundle autocontido para inferência, persistido (por padrão) em joblib.

Fontes de verdade (v1):
- preprocess persistido no run_dir (PreprocessStore ou artifacts/preprocess.joblib)
- modelo treinado em memória no RunContext (model.best_estimator ou model.trained)
- contrato interno congelado (ctx.contract)
- avaliação e seleção do campeão (eval.metrics + eval.model_selection)

Invariantes:
- Não infere nada: apenas consolida artefatos já produzidos pelo pipeline.
- IDs/referências vêm de artefatos/manifest (fonte de verdade).
- Deve produzir payload/artifacts compatíveis com consumidores (ex.: export.model_card).

Compatibilidade:
- payload inclui `champion_model_id` e `model_id` (alias do campeão)
- hash é exposto como `bundle_hash` e também `sha256` (alias comum)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import hashlib
import inspect

import joblib

from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.deployment.inference_bundle import InferenceBundleV1, save_inference_bundle_v1
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _safe_get_run_dir(ctx: Any) -> Path:
    """
    Obtém run_dir do ctx.
    Suporta:
      - ctx.meta["run_dir"] (Path ou str)
      - ctx.get_meta("run_dir") (se existir)
    """
    meta = getattr(ctx, "meta", None)
    if isinstance(meta, dict) and "run_dir" in meta:
        rd = meta["run_dir"]
        return rd if isinstance(rd, Path) else Path(str(rd))

    get_meta = getattr(ctx, "get_meta", None)
    if callable(get_meta):
        rd = get_meta("run_dir")
        if rd is not None:
            return rd if isinstance(rd, Path) else Path(str(rd))

    # fallback (não ideal)
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
    """
    Fonte de verdade: ctx.get_artifact("eval.model_selection")["selection"]["champion_model_id"]
    """
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
    """
    Busca em eval.metrics uma entrada para o model_id campeão.
    Formatos aceitos (conforme testes):
      - list[{"model_id": "...", "metrics": {...}}]
      - {"model_id": "...", "metrics": {...}} ou {"metrics": {...}}
    """
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
            return dict(obj["metrics"])
        return {}

    return {}


def _resolve_model(ctx: Any) -> Any:
    """
    Preferência:
      - model.best_estimator (train.search / seleção)
      - model.trained (train.single)
    """
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
    """
    Resolve preprocess.joblib:
      - PreprocessStore (preferencial)
      - artifacts/preprocess.joblib (fallback)
    """
    artifacts_dir = run_dir / "artifacts"
    _ensure_dir(artifacts_dir)

    preprocess_path: Optional[Path] = None
    try:
        store = PreprocessStore(base_dir=run_dir)
        preprocess_path = store.path_for_current_preprocess()
        if not preprocess_path.exists():
            preprocess_path = None
    except Exception:
        preprocess_path = None

    if preprocess_path is None:
        candidate = artifacts_dir / "preprocess.joblib"
        if candidate.exists():
            preprocess_path = candidate

    return preprocess_path


class ExportInferenceBundleStep(Step):
    """
    Step canônico: export.inference_bundle

    Entrega:
      - artifacts/payload: bundle_path, bundle_hash, format, bundle_version, contract_version,
        champion_model_id e model_id
    """

    id = "export.inference_bundle"
    kind = StepKind.EXPORT

    def run(self, ctx: Any) -> StepResult:
        run_dir = _safe_get_run_dir(ctx)
        artifacts_dir = run_dir / "artifacts"
        _ensure_dir(artifacts_dir)

        # --- config
        step_cfg: Dict[str, Any] = {}
        try:
            step_cfg = (ctx.config or {}).get("steps", {}).get(self.id, {})  # type: ignore[attr-defined]
        except Exception:
            step_cfg = {}

        fmt = "joblib"
        if isinstance(step_cfg, dict) and isinstance(step_cfg.get("format"), str) and step_cfg.get("format"):
            fmt = str(step_cfg.get("format")).strip().lower() or "joblib"

        # --- contract
        contract = getattr(ctx, "contract", None)
        contract_dict: Dict[str, Any] = contract if isinstance(contract, dict) else {}
        contract_version = "unknown"
        if isinstance(contract_dict.get("contract_version"), str):
            contract_version = str(contract_dict.get("contract_version"))

        # --- champion
        champion_model_id = _pick_champion_model_id(ctx)
        champion_metrics = _pick_champion_metrics(ctx, champion_model_id)

        # --- required: model
        try:
            model = _resolve_model(ctx)
        except Exception as e:
            err = {
                "type": "MODEL_MISSING",
                "message": "Artifact obrigatório ausente: model.best_estimator|model.trained",
                "details": {"artifact": "model.best_estimator|model.trained", "exception_message": str(e)},
                "decision_required": True,
                "hint": "Garanta que o treino publique ctx.set_artifact('model.best_estimator', model) "
                        "ou ctx.set_artifact('model.trained', model).",
            }
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

        # --- required: preprocess path + load object
        preprocess_path = _resolve_preprocess_path(run_dir)
        if preprocess_path is None:
            err = {
                "type": "PREPROCESS_MISSING",
                "message": "Preprocess ausente: preprocess.joblib não encontrado",
                "details": {"expected": str(artifacts_dir / "preprocess.joblib")},
                "decision_required": True,
                "hint": "Garanta que o pipeline persista preprocess.joblib antes do export.inference_bundle.",
            }
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
            err = {
                "type": "PREPROCESS_LOAD_FAILED",
                "message": "Falha ao carregar preprocess.joblib",
                "details": {
                    "path": str(preprocess_path),
                    "exception": type(e).__name__,
                    "exception_message": str(e),
                },
                "decision_required": True,
                "hint": "Verifique se preprocess.joblib foi salvo corretamente (joblib.dump) e não está corrompido.",
            }
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

        # --- metadata (sempre serializável)
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

        # --- build bundle (filtra conforme assinatura para não quebrar se o core variar)
        bundle_kwargs: Dict[str, Any] = {
            "preprocess": preprocess_obj,
            "model": model,
            "contract": contract_dict,
            "metadata": metadata_obj,
            # campos opcionais (se existirem no InferenceBundleV1 do seu core)
            "metrics": champion_metrics,
            "format": fmt,
            "contract_version": contract_version,
            "champion_model_id": champion_model_id,
            "model_id": champion_model_id,
            "bundle_version": "v1",
            "version": "v1",
        }

        sig_bundle = inspect.signature(InferenceBundleV1)  # type: ignore[arg-type]
        accepted_bundle = set(sig_bundle.parameters.keys())
        filtered_bundle_kwargs = {k: v for k, v in bundle_kwargs.items() if k in accepted_bundle}

        try:
            bundle = InferenceBundleV1(**filtered_bundle_kwargs)
        except Exception as e:
            err = {
                "type": "BUNDLE_CONSTRUCT_FAILED",
                "message": "Falha ao instanciar InferenceBundleV1",
                "details": {
                    "exception": type(e).__name__,
                    "exception_message": str(e),
                    "accepted_params": sorted(list(accepted_bundle)),
                    "provided_params": sorted(list(filtered_bundle_kwargs.keys())),
                },
                "decision_required": True,
                "hint": "Ajuste o mapeamento conforme a assinatura do InferenceBundleV1 no seu core.",
            }
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

        # --- persist
        safe_model_id = (champion_model_id or "unknown").replace("/", "_").replace("\\", "_")
        bundle_path = artifacts_dir / f"inference_bundle.{safe_model_id}.{fmt}"

        try:
            # ✅ CORREÇÃO CRÍTICA: save_inference_bundle_v1 exige keyword-only `path=`
            sig_save = inspect.signature(save_inference_bundle_v1)  # type: ignore[arg-type]
            accepted_save = set(sig_save.parameters.keys())

            if "path" in accepted_save:
                if "bundle" in accepted_save:
                    save_meta = save_inference_bundle_v1(bundle=bundle, path=bundle_path)  # type: ignore[misc]
                else:
                    save_meta = save_inference_bundle_v1(bundle, path=bundle_path)  # type: ignore[misc]
            else:
                # fallback para cores antigos
                joblib.dump(bundle, str(bundle_path))
                save_meta = {}
        except Exception as e:
            err = {
                "type": type(e).__name__,
                "message": "Não foi possível persistir o bundle de inferência (decision required)",
                "details": {"exception_message": str(e)},
                "decision_required": True,
                "hint": "Verifique permissões/IO e se preprocess/model são serializáveis.",
            }
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.inference_bundle failed (decision required)",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

        # --- normalize outputs
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
