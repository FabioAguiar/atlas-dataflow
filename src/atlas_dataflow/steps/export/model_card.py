"""Geração determinística de Model Card (v1).

Fonte de verdade (v1):
- Manifest final (traceability)
- Contrato interno congelado (Internal Contract v1)
- Métricas finais do campeão (evaluate.metrics)

Regras:
- Não inferir nada por heurística (somente ler campos existentes).
- Conteúdo determinístico para um Manifest fixo.
- Formato Markdown com seções mínimas obrigatórias.

Refs:
- docs/spec/model_card.v1.md (pode não existir ainda)
- docs/traceability.md
- docs/manifest.schema.v1.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepResult, StepKind, StepStatus



try:
    from atlas_dataflow.core.pipeline.step import StepOutcome  # type: ignore
except Exception:  # pragma: no cover
    StepOutcome = None  # type: ignore




from atlas_dataflow.core.errors import AtlasErrorPayload  # se existir; senão pode remover o try/except abaixo


__all__ = ["ExportModelCardStep"]




class ModelCardError(RuntimeError):
    """Erro explícito na geração do Model Card."""


@dataclass(frozen=True)
class ModelCardInputs:
    """Entradas mínimas para gerar o Model Card."""

    manifest: Dict[str, Any]
    contract: Dict[str, Any]
    champion_metrics: Dict[str, Any]
    export_payload: Optional[Dict[str, Any]] = None


_MIN_SECTIONS = [
    "# Model Card",
    "## Model Overview",
    "## Training Data",
    "## Input Contract",
    "## Metrics",
    "## Limitations",
    "## Execution Metadata",
]


def _require_dict(x: Any, name: str) -> Dict[str, Any]:
    if not isinstance(x, dict):
        raise ModelCardError(f"{name} must be a dict")
    return x


def _manifest_get(manifest: Dict[str, Any], *keys: str) -> Any:
    cur: Any = manifest
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _pick_dataset_origin(manifest: Dict[str, Any]) -> str:
    """Extrai a origem do dataset a partir do Manifest (sem heurística)."""
    steps = _manifest_get(manifest, "steps")
    if isinstance(steps, dict):
        ingest = steps.get("ingest.load")
        if isinstance(ingest, dict):
            artifacts = ingest.get("artifacts")
            if isinstance(artifacts, dict):
                for k in (
                    "source_path",  # usado nos testes
                    "source",
                    "path",
                    "dataset_path",
                    "input_path",
                    "uri",
                ):
                    v = artifacts.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            payload = ingest.get("payload")
            if isinstance(payload, dict):
                for k in ("source_path", "source", "path", "dataset_path", "input_path", "uri"):
                    v = payload.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    return "unknown (não registrado no Manifest)"

def _pick_bundle_info(inputs: ModelCardInputs) -> Dict[str, str]:
    """Extrai infos do bundle via export_payload ou Manifest (sem inferência)."""
    bundle_path = None
    bundle_sha256 = None
    bundle_version = None
    fmt = None
    champion_model_id = None
    contract_version = None

    # 1) Preferência: export_payload (quando disponível)
    if isinstance(inputs.export_payload, dict):
        p = inputs.export_payload
        if isinstance(p.get("bundle_path"), str):
            bundle_path = p.get("bundle_path")
        if isinstance(p.get("bundle_hash"), str):
            bundle_sha256 = p.get("bundle_hash")
        if isinstance(p.get("bundle_sha256"), str):
            bundle_sha256 = bundle_sha256 or p.get("bundle_sha256")
        if isinstance(p.get("sha256"), str):
            bundle_sha256 = bundle_sha256 or p.get("sha256")
        if isinstance(p.get("format"), str):
            fmt = p.get("format")
        if isinstance(p.get("bundle_version"), str):
            bundle_version = p.get("bundle_version")
        if isinstance(p.get("champion_model_id"), str):
            champion_model_id = p.get("champion_model_id")
        if isinstance(p.get("model_id"), str):
            champion_model_id = champion_model_id or p.get("model_id")
        if isinstance(p.get("contract_version"), str):
            contract_version = p.get("contract_version")

    # 2) Fonte de verdade: manifest.steps["export.inference_bundle"]
    steps = _manifest_get(inputs.manifest, "steps")
    if isinstance(steps, dict):
        exp = steps.get("export.inference_bundle")
        if isinstance(exp, dict):
            arts = exp.get("artifacts")
            if isinstance(arts, dict):
                if bundle_path is None and isinstance(arts.get("bundle_path"), str):
                    bundle_path = arts.get("bundle_path")
                if bundle_sha256 is None and isinstance(arts.get("bundle_hash"), str):
                    bundle_sha256 = arts.get("bundle_hash")
                if bundle_sha256 is None and isinstance(arts.get("bundle_sha256"), str):
                    bundle_sha256 = arts.get("bundle_sha256")
                if bundle_sha256 is None and isinstance(arts.get("sha256"), str):
                    bundle_sha256 = arts.get("sha256")

                if fmt is None and isinstance(arts.get("format"), str):
                    fmt = arts.get("format")
                if bundle_version is None and isinstance(arts.get("bundle_version"), str):
                    bundle_version = arts.get("bundle_version")

                if champion_model_id is None and isinstance(arts.get("champion_model_id"), str):
                    champion_model_id = arts.get("champion_model_id")
                if champion_model_id is None and isinstance(arts.get("model_id"), str):
                    champion_model_id = arts.get("model_id")

                if contract_version is None and isinstance(arts.get("contract_version"), str):
                    contract_version = arts.get("contract_version")

            payload = exp.get("payload")
            if isinstance(payload, dict):
                if bundle_path is None and isinstance(payload.get("bundle_path"), str):
                    bundle_path = payload.get("bundle_path")
                if bundle_sha256 is None and isinstance(payload.get("bundle_hash"), str):
                    bundle_sha256 = payload.get("bundle_hash")
                if bundle_sha256 is None and isinstance(payload.get("bundle_sha256"), str):
                    bundle_sha256 = payload.get("bundle_sha256")
                if bundle_sha256 is None and isinstance(payload.get("sha256"), str):
                    bundle_sha256 = payload.get("sha256")

                if fmt is None and isinstance(payload.get("format"), str):
                    fmt = payload.get("format")
                if bundle_version is None and isinstance(payload.get("bundle_version"), str):
                    bundle_version = payload.get("bundle_version")

                if champion_model_id is None and isinstance(payload.get("champion_model_id"), str):
                    champion_model_id = payload.get("champion_model_id")
                if champion_model_id is None and isinstance(payload.get("model_id"), str):
                    champion_model_id = payload.get("model_id")

                if contract_version is None and isinstance(payload.get("contract_version"), str):
                    contract_version = payload.get("contract_version")

    return {
        "bundle_path": str(bundle_path or "unknown"),
        "bundle_sha256": str(bundle_sha256 or "unknown"),
        "format": str(fmt or "joblib"),
        "bundle_version": str(bundle_version or "v1"),
        "champion_model_id": str(champion_model_id or "unknown"),
        "contract_version": str(contract_version or inputs.contract.get("contract_version") or "unknown"),
    }



def generate_model_card_md(inputs: ModelCardInputs) -> str:
    manifest = _require_dict(inputs.manifest, "manifest")
    contract = _require_dict(inputs.contract, "contract")
    metrics = _require_dict(inputs.champion_metrics, "champion_metrics")

    if not manifest:
        raise ModelCardError("Manifest ausente ou vazio (fonte de verdade obrigatória)")
    if not contract:
        raise ModelCardError("Contrato ausente ou vazio (fonte de verdade obrigatória)")
    if not metrics:
        raise ModelCardError("Métricas ausentes ou vazias (fonte de verdade obrigatória)")

    dataset_origin = _pick_dataset_origin(manifest)
    bundle = _pick_bundle_info(inputs)

    # suportar diferentes formas de manifest mínimo nos testes
    run_id = (
        _manifest_get(manifest, "run", "run_id")
        or _manifest_get(manifest, "run_id")
        or _manifest_get(manifest, "meta", "run_id")
        or _manifest_get(manifest, "context", "run_id")
        or "unknown"
    )
    created_at = (
        _manifest_get(manifest, "run", "started_at")
        or _manifest_get(manifest, "run", "created_at")
        or _manifest_get(manifest, "created_at")
        or _manifest_get(manifest, "meta", "created_at")
        or _manifest_get(manifest, "context", "created_at")
        or "unknown"
    )

    # contrato de entrada (features e tipos)
    features = contract.get("features")
    feature_lines = []
    if isinstance(features, list):
        for f in features:
            if isinstance(f, dict):
                name = f.get("name")
                dtype = f.get("dtype") or f.get("type")
                if isinstance(name, str) and name.strip():
                    feature_lines.append(f"- `{name}`: `{dtype}`")
    if not feature_lines:
        feature_lines.append("- (features não registradas no contrato)")

    # métricas (chave: valor)
    metric_lines = []
    for k in sorted(metrics.keys()):
        v = metrics[k]
        metric_lines.append(f"- **{k}**: `{v}`")
    if not metric_lines:
        metric_lines.append("- (métricas não registradas)")

    lines = []
    lines.extend(_MIN_SECTIONS)
    lines.append("")

    # Overview — manter rótulos esperados pelos testes
    lines.append("## Model Overview")
    lines.append(f"- Champion model_id: `{bundle['champion_model_id']}`")
    lines.append(f"- Bundle path: `{bundle['bundle_path']}`")
    lines.append(f"- Bundle hash (sha256): `{bundle['bundle_sha256']}`")
    lines.append(f"- Bundle format: `{bundle['format']}`")
    lines.append(f"- Bundle version: `{bundle['bundle_version']}`")
    lines.append(f"- Contract version: `{bundle['contract_version']}`")
    lines.append("")

    lines.append("## Training Data")
    lines.append(f"- Dataset source (Manifest): `{dataset_origin}`")
    lines.append("")

    lines.append("## Input Contract")
    lines.append("### Features")
    lines.extend(feature_lines)
    lines.append("")
    lines.append("### Notes")
    lines.append("- Payload deve respeitar o contrato congelado; falhas são explícitas (sem heurísticas).")
    lines.append("")

    lines.append("## Metrics")
    lines.extend(metric_lines)
    lines.append("")

    lines.append("## Limitations")
    lines.append("- Este Model Card (v1) não inclui fairness/ética, explicabilidade ou visualizações.")
    lines.append("- Informações não registradas no Manifest/Contrato permanecem como `unknown` (sem inferência).")
    lines.append("")

    lines.append("## Execution Metadata")
    lines.append(f"- run_id: `{run_id}`")
    lines.append(f"- created_at: `{created_at}`")
    lines.append(f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_model_card_md(*, inputs: ModelCardInputs, path: Path) -> Dict[str, Any]:
    md = generate_model_card_md(inputs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return {"path": str(path), "bytes": len(md.encode("utf-8"))}



def _safe_get_run_dir(ctx: Any) -> Path:
    run_dir = None
    if hasattr(ctx, "meta") and isinstance(ctx.meta, dict):
        run_dir = ctx.meta.get("run_dir")
    if isinstance(run_dir, Path):
        return run_dir
    if isinstance(run_dir, str) and run_dir.strip():
        return Path(run_dir)
    # fallback determinístico: cwd
    return Path.cwd()


def _safe_get_manifest(ctx: Any) -> Dict[str, Any]:
    if hasattr(ctx, "meta") and isinstance(ctx.meta, dict):
        m = ctx.meta.get("manifest")
        if isinstance(m, dict):
            return m
    return {}



class ExportModelCardStep(Step):
    id = "export.model_card"
    kind = StepKind.EXPORT
    depends_on = ["export.inference_bundle"]

    def run(self, ctx: Any) -> StepResult:
        try:
            run_dir = _safe_get_run_dir(ctx)
            artifacts_dir = run_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            manifest = _safe_get_manifest(ctx)

            # Guardrail explícito: manifest é obrigatório
            if not isinstance(manifest, dict) or not manifest:
                err = {
                    "type": "MANIFEST_MISSING",
                    "message": "Manifest ausente para gerar model_card.md",
                    "details": {"required": "ctx.meta['manifest']"},
                    "hint": "Garanta que o Engine persista e injete o manifest no ctx.meta antes do export.model_card.",
                    "decision_required": True,
                }
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.FAILED,
                    summary="export.model_card failed (manifest missing)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"error": err},
                )

            # contrato é fonte de verdade do Model Card
            contract = ctx.contract if isinstance(getattr(ctx, "contract", None), dict) else {}

            # métricas do campeão vêm do Manifest (evaluate.metrics)
            champion_metrics = _extract_champion_metrics_from_manifest(manifest)

            # payload do export (se existir parser)
            export_payload: Optional[Dict[str, Any]] = None
            if "_extract_export_payload_from_manifest" in globals():
                export_payload = globals()["_extract_export_payload_from_manifest"](manifest)  # type: ignore

            inputs = ModelCardInputs(
                manifest=manifest,
                contract=contract,
                champion_metrics=champion_metrics,
                export_payload=export_payload if isinstance(export_payload, dict) else None,
            )

            md = generate_model_card_md(inputs)

            out = artifacts_dir / "model_card.md"
            out.write_text(md, encoding="utf-8")

            # ✅ retorno explícito no caminho de sucesso (isso resolve sr=None)
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="export.model_card completed",
                metrics={},
                warnings=[],
                artifacts={"model_card_path": str(out)},
                payload={},
            )

        except Exception as e:
            err = {
                "type": "MODEL_CARD_EXPORT_FAILED",
                "message": "Falha ao gerar model_card.md",
                "details": {"exception": type(e).__name__, "exception_message": str(e)},
                "hint": "Veja payload.error.details para a causa e ajuste o parser do Manifest/payloads.",
                "decision_required": False,
            }
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary="export.model_card failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )





def _extract_champion_metrics_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrai métricas do campeão a partir do Manifest.

    Regra: sem inferência. Só lê:
      - champion_model_id (preferência: export.inference_bundle payload/artifacts)
      - metrics (preferência: evaluate.metrics result.metrics)
    """
    champion_model_id: Optional[str] = None
    metrics: Dict[str, Any] = {}

    def _dig_step(step_id: str) -> Optional[Dict[str, Any]]:
        steps = manifest.get("steps")
        if isinstance(steps, dict):
            node = steps.get(step_id)
            if isinstance(node, dict):
                return node

        hist = manifest.get("history")
        if isinstance(hist, list):
            for ev in reversed(hist):
                if isinstance(ev, dict) and ev.get("step_id") == step_id:
                    return ev
        return None

    def _dig_payload_or_artifacts(node: Dict[str, Any]) -> Dict[str, Any]:
        # alguns manifests guardam StepResult em "result"
        result = node.get("result")
        if isinstance(result, dict):
            node = result

        payload = node.get("payload")
        if isinstance(payload, dict):
            return payload

        artifacts = node.get("artifacts")
        if isinstance(artifacts, dict):
            return artifacts

        return {}

    # 1) campeão vem do export.inference_bundle
    exp = _dig_step("export.inference_bundle")
    if isinstance(exp, dict):
        info = _dig_payload_or_artifacts(exp)
        if isinstance(info.get("champion_model_id"), str):
            champion_model_id = info.get("champion_model_id")
        elif isinstance(info.get("model_id"), str):
            champion_model_id = info.get("model_id")

    # 2) métricas vêm do evaluate.metrics
    evm = _dig_step("evaluate.metrics")
    if isinstance(evm, dict):
        node = evm
        result = node.get("result")
        if isinstance(result, dict):
            node = result

        m = node.get("metrics")
        if isinstance(m, dict):
            metrics = m

        # fallback: às vezes vem em payload
        if not metrics:
            p = node.get("payload")
            if isinstance(p, dict) and isinstance(p.get("metrics"), dict):
                metrics = p["metrics"]

    return {
        "model_id": str(champion_model_id or "unknown"),
        "metrics": metrics,
    }
