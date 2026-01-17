# src/atlas_dataflow/core/engine/engine.py
"""
Engine de execução do pipeline do Atlas DataFlow.

Este módulo contém a implementação do Engine responsável por coordenar
o planejamento e a execução de pipelines declarativos compostos por Steps.

O Engine atua como o orquestrador central da execução, integrando:
    - o planner (ordenação topológica determinística)
    - a aplicação de políticas explícitas de execução
    - a consolidação do resultado final da run

Responsabilidades do módulo:
    - Planejar a execução dos Steps (DAG)
    - Executar Steps em ordem determinística
    - Aplicar políticas de execução definidas por configuração
    - Produzir um `RunResult` consolidado

Políticas de execução (v1):
    - Skip por configuração (`steps.<step_id>.enabled`)
    - Fail-fast (`engine.fail_fast`)
    - Gate por dependência falha (dependência FAILED ⇒ SKIPPED)

Invariantes:
    - Cada Step é avaliado no máximo uma vez por run
    - Nenhum Step executa antes de suas dependências
    - Exceções de Steps são convertidas em `StepResult` FAILED
    - A ordem de execução é estável e determinística

Limites explícitos:
    - Não paraleliza execução
    - Não implementa retries ou recovery
    - Não persiste artefatos ou resultados
    - Não registra eventos de rastreabilidade
    - Não depende de UI, notebooks ou frameworks externos

Este módulo existe para garantir execução previsível,
determinística e testável de pipelines no Atlas DataFlow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus

from .planner import plan_execution


@dataclass(frozen=True)
class RunResult:
    """
    Resultado agregado de uma execução de pipeline (RunResult v1).

    Esta estrutura representa o resultado final produzido pelo Engine
    após a execução (ou interrupção) de um pipeline.

    O `RunResult` consolida:
        - o estado final de cada Step avaliado
        - o `StepResult` correspondente a cada `step_id`

    Decisões arquiteturais:
        - O resultado é imutável (frozen=True)
        - Cada Step aparece no máximo uma vez
        - Apenas Steps processados pelo Engine são incluídos

    Invariantes:
        - A chave do dicionário corresponde ao `step_id`
        - O valor associado é sempre um `StepResult`
        - O conteúdo reflete exatamente o que foi executado ou avaliado

    Limites explícitos:
        - Não contém métricas globais agregadas
        - Não registra eventos de rastreabilidade
        - Não persiste resultados automaticamente
        - Não reexecuta ou altera Steps

    Esta classe existe para fornecer uma representação
    simples, estável e testável do resultado de uma run.
    """
    steps: Dict[str, StepResult] = field(default_factory=dict)


class Engine:
    """
    Engine canônico do Atlas DataFlow (planner + executor) — versão mínima (M0).

    Esta classe coordena a execução de um pipeline declarado como um conjunto
    de Steps, delegando o planejamento de ordem ao `plan_execution` (DAG planner)
    e executando os Steps em sequência determinística.

    Responsabilidades:
        - Planejar a execução via ordenação topológica determinística (planner)
        - Executar Steps respeitando dependências declaradas
        - Aplicar políticas explícitas de execução definidas por configuração:
            - skip por config (`steps.<step_id>.enabled`)
            - fail-fast (`engine.fail_fast`)
            - gate por dependência falha (v1): se qualquer dependência falhar,
              o Step é marcado como SKIPPED

    Decisões arquiteturais (v1):
        - O Engine opera apenas com o contrato `Step` e `RunContext`
        - A ordem é determinística para o mesmo grafo de dependências
        - `Step.run(ctx)` deve retornar um `StepResult`
        - Exceções de Steps são capturadas e convertidas em `StepResult` FAILED
        - O Engine não executa Steps desabilitados por configuração

    Invariantes:
        - Cada Step é avaliado no máximo uma vez por run
        - Nenhum Step executa antes de suas dependências (garantido pelo planner)
        - Um Step com dependência FAILED não executa (v1: SKIPPED)
        - O resultado final consolida um `StepResult` por Step processado

    Limites explícitos:
        - Não paraleliza execução
        - Não implementa retries, backoff ou recover
        - Não persiste resultados ou artefatos automaticamente
        - Não registra eventos no Manifest (traceability é camada separada)
        - Não valida semântica de config/contract (apenas consumo estrutural)

    Esta classe existe para garantir execução determinística,
    previsível e testável de pipelines no Atlas DataFlow.
    """

    def __init__(self, *, steps: Sequence[Step], ctx: RunContext):
        self.steps: List[Step] = list(steps)
        self.ctx: RunContext = ctx

    def _is_enabled(self, step_id: str) -> bool:
        steps_cfg = (self.ctx.config or {}).get("steps", {}) or {}
        step_cfg = steps_cfg.get(step_id, {}) or {}
        enabled = step_cfg.get("enabled", True)
        return bool(enabled)

    def _fail_fast(self) -> bool:
        engine_cfg = (self.ctx.config or {}).get("engine", {}) or {}
        return bool(engine_cfg.get("fail_fast", True))

    def run(self) -> RunResult:
        ordered = plan_execution(self.steps)

        results: Dict[str, StepResult] = {}
        for step in ordered:
            sid = step.id

            # Skip by config
            if not self._is_enabled(sid):
                kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.SKIPPED,
                    summary="skipped by config",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                continue

            # Dependency gate (v1): if any dependency FAILED => SKIPPED
            deps = list(getattr(step, "depends_on", []) or [])
            if any(results.get(d) and results[d].status == StepStatus.FAILED for d in deps):
                kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.SKIPPED,
                    summary="skipped due to failed dependency",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                continue

            kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
            try:
                step_result = step.run(self.ctx)
                # Minimal normalization
                if not isinstance(step_result, StepResult):
                    raise TypeError("Step.run(ctx) must return StepResult")
                results[sid] = step_result
            except Exception as e:
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.FAILED,
                    summary=str(e) or "failed",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                if self._fail_fast():
                    break

        return RunResult(steps=results)
