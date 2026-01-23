"""Step canônico: evaluate.model_selection (v1).

Seleção explícita e auditável do "modelo campeão" a partir de métricas já calculadas
(por exemplo, outputs do Step `evaluate.metrics`).

Responsabilidades (M5):
- Consumir métricas padronizadas já produzidas (não recalcular métricas).
- Selecionar um campeão com base em uma métrica alvo configurável.
- Produzir ranking determinístico e payload serializável.
- Registrar critério e decisão no RunContext (artifact) e via log.

Princípios do Atlas:
- Seleção nunca é implícita e não depende de efeitos colaterais do treino.
- Nenhuma métrica é inferida automaticamente.
- Empates são resolvidos de forma determinística e documentada.
- O Step não treina modelos e não recalcula preprocess.

Config esperada (exemplo):

steps:
  evaluate.model_selection:
    enabled: true
    target_metric: f1
    direction: maximize  # maximize | minimize

Entrada (artifacts esperados):
- Métricas de avaliação previamente calculadas.
  Este Step suporta as seguintes formas explícitas (sem descoberta automática):
  1) artifact: `eval.metrics` como LISTA de payloads (um por modelo), cada um contendo:
     - model_id: str  (obrigatório para seleção)
     - metrics: {<metric>: float, ...}
  2) artifact: `eval.metrics` como DICT (um único payload) contendo as mesmas chaves.
  3) artifact: `eval.metrics_list` como LISTA (mesma estrutura do item 1).

Saída (artifacts produzidos):
- `eval.model_selection`: payload serializável contendo critério, campeão e ranking.

Payload mínimo (v1):

payload:
  selection:
    metric: string
    direction: maximize|minimize
    champion_model_id: string
    champion_score: float
    ranking:
      - model_id: string
        score: float

Regra de desempate (determinística):
- Ordena primariamente por score (max/min conforme direction)
- Em empate, ordena por `model_id` (ordem lexicográfica crescente)

Referências:
- docs/spec/evaluate.model_selection.v1.md (pode ainda não existir)
- docs/traceability.md
- docs/manifest.schema.v1.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _require_str(x: Any, msg: str) -> str:
    if not isinstance(x, str) or not x.strip():
        raise ValueError(msg)
    return x.strip()


def _require_direction(x: Any) -> str:
    x = _require_str(x, "direction must be a non-empty string").lower()
    if x not in {"maximize", "minimize"}:
        raise ValueError("direction must be 'maximize' or 'minimize'")
    return x


def _as_float(x: Any, *, msg: str) -> float:
    if isinstance(x, bool):
        raise ValueError(msg)
    if isinstance(x, (int, float)):
        return float(x)
    raise ValueError(msg)


def _load_metrics_payloads(ctx: RunContext) -> List[Dict[str, Any]]:
    """Carrega payloads de métricas por fonte explícita.

    Não faz descoberta automática por prefixo de artifacts.
    """
    if ctx.has_artifact("eval.metrics_list"):
        payloads = ctx.get_artifact("eval.metrics_list")
        if not isinstance(payloads, list) or not all(isinstance(p, dict) for p in payloads):
            raise ValueError("Invalid artifact: eval.metrics_list must be a list[dict]")
        return payloads

    if not ctx.has_artifact("eval.metrics"):
        raise ValueError("Missing required artifact: eval.metrics (list[dict] or dict)")

    obj = ctx.get_artifact("eval.metrics")
    if isinstance(obj, list):
        if not all(isinstance(p, dict) for p in obj):
            raise ValueError("Invalid artifact: eval.metrics list must contain dict payloads")
        return obj

    if isinstance(obj, dict):
        return [obj]

    raise ValueError("Invalid artifact: eval.metrics must be list[dict] or dict")


def _extract_scores(payloads: List[Dict[str, Any]], target_metric: str) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for i, p in enumerate(payloads):
        mid = p.get("model_id")
        if mid is None:
            # Não inventa um model_id (não-inferência). Falha explícita.
            raise ValueError(f"Missing model_id in eval.metrics payload at index {i}")
        model_id = _require_str(mid, f"Invalid model_id in eval.metrics payload at index {i}")

        metrics = p.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"Invalid metrics for model_id={model_id}: expected mapping")

        if target_metric not in metrics:
            raise ValueError(f"target_metric '{target_metric}' not present for model_id={model_id}")

        score = _as_float(metrics.get(target_metric), msg=f"Invalid score for {model_id}.{target_metric}")
        out.append((model_id, score))
    return out


def _sort_ranking(scores: List[Tuple[str, float]], direction: str) -> List[Tuple[str, float]]:
    reverse = direction == "maximize"
    # Empate: model_id asc (sempre). Para manter isso, usamos key composta.
    # Para maximize: score desc -> usamos (-score, model_id)
    # Para minimize: score asc -> usamos (score, model_id)
    if reverse:
        return sorted(scores, key=lambda t: (-t[1], t[0]))
    return sorted(scores, key=lambda t: (t[1], t[0]))


@dataclass
class EvaluateModelSelectionStep(Step):
    """Seleciona o modelo campeão com base em métricas já computadas."""

    id: str = "evaluate.model_selection"
    kind: StepKind = StepKind.EVALUATE
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = [
                "evaluate.metrics",
            ]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            if cfg.get("enabled") is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="evaluate.model_selection skipped (disabled in config)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"skipped": True},
                )

            target_metric = _require_str(cfg.get("target_metric"), "target_metric is required")
            direction = _require_direction(cfg.get("direction", "maximize"))

            payloads = _load_metrics_payloads(ctx)
            scores = _extract_scores(payloads, target_metric)
            if len(scores) == 0:
                raise ValueError("No evaluated models found in eval.metrics")

            ranking_sorted = _sort_ranking(scores, direction)
            champion_model_id, champion_score = ranking_sorted[0]

            selection_payload: Dict[str, Any] = {
                "selection": {
                    "metric": target_metric,
                    "direction": direction,
                    "champion_model_id": champion_model_id,
                    "champion_score": float(champion_score),
                    "ranking": [
                        {"model_id": mid, "score": float(score)} for mid, score in ranking_sorted
                    ],
                }
            }

            ctx.set_artifact("eval.model_selection", selection_payload)

            ctx.log(
                step_id=self.id,
                level="info",
                message="evaluate.model_selection completed",
                target_metric=target_metric,
                direction=direction,
                champion_model_id=champion_model_id,
                champion_score=float(champion_score),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="evaluate.model_selection completed",
                metrics={},
                warnings=[],
                artifacts={"eval.model_selection": "eval.model_selection"},
                payload=selection_payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="evaluate.model_selection failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "evaluate.model_selection failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["EvaluateModelSelectionStep"]
