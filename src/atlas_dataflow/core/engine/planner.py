# src/atlas_dataflow/core/engine/planner.py
"""
Planejador de execução do pipeline (DAG).

Este módulo é responsável por validar a estrutura do pipeline e produzir
uma ordem de execução topológica determinística dos Steps declarados.

O planner opera exclusivamente em nível estrutural, analisando:
    - identificadores de Steps
    - dependências declaradas
    - formação de ciclos
    - consistência do grafo

A saída do planner é uma sequência linear de Steps pronta para execução
pelo Engine, respeitando integralmente as dependências explícitas.

Princípios fundamentais:
    - O pipeline deve formar um DAG válido
    - A ordenação é determinística para a mesma entrada
    - Nenhuma decisão silenciosa ou heurística implícita
    - Validação estrutural ocorre antes da execução

Decisões arquiteturais:
    - Utiliza ordenação topológica determinística (Kahn modificado)
    - Empates são resolvidos por ordem lexicográfica de `step.id`
    - Erros estruturais são tratados como falhas fatais

Invariantes:
    - Nenhum Step é executado antes de suas dependências
    - Todos os Steps válidos aparecem exatamente uma vez
    - A mesma definição de pipeline produz sempre a mesma ordem

Limites explícitos:
    - Não executa Steps
    - Não interage com RunContext
    - Não registra eventos de rastreabilidade
    - Não decide políticas de execução

Este módulo existe para garantir correção estrutural,
determinismo e previsibilidade na execução de pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

from atlas_dataflow.core.pipeline.step import Step


class UnknownDependencyError(ValueError):
    """
    Exceção levantada quando um Step referencia uma dependência inexistente.

    Esta exceção indica que um Step declarou em `depends_on` um `step.id`
    que não corresponde a nenhum Step registrado no pipeline.

    Decisões arquiteturais:
        - Todas as dependências devem ser explícitas e resolvíveis
        - Dependências inexistentes são tratadas como erro estrutural
        - A validação ocorre antes de qualquer execução

    Invariantes:
        - Um Step não pode depender de um Step inexistente
        - O pipeline é considerado inválido nesta condição

    Limites explícitos:
        - Não tenta inferir ou criar Steps ausentes
        - Não executa Steps
        - Não interage com RunContext ou Manifest

    Esta exceção existe para garantir integridade estrutural,
    clareza declarativa e segurança no planejamento do pipeline.
    """


class CycleDetectedError(ValueError):
    """
    Exceção levantada quando o grafo de dependências contém um ciclo.

    Esta exceção indica que o conjunto de Steps declarados forma um
    grafo cíclico, violando a exigência de um DAG para execução
    determinística do pipeline.

    Decisões arquiteturais:
        - Pipelines devem ser acíclicos
        - Ciclos são tratados como erro estrutural fatal
        - Nenhuma execução parcial é permitida em presença de ciclos

    Invariantes:
        - A existência de um ciclo invalida o planejamento do pipeline
        - Nenhuma ordem topológica válida pode ser produzida

    Limites explícitos:
        - Não tenta resolver ou quebrar ciclos automaticamente
        - Não modifica Steps ou dependências
        - Não interage com RunContext ou Engine

    Esta exceção existe para garantir correção estrutural,
    determinismo e previsibilidade na execução do pipeline.
    """


def plan_execution(steps: Iterable[Step]) -> List[Step]:
    """
    Valida e produz uma ordem de execução topológica determinística de Steps.

    Esta função recebe um conjunto de Steps declarativos e constrói uma
    ordem de execução válida com base em suas dependências explícitas,
    garantindo que o pipeline forme um DAG correto.

    A ordenação é determinística: sempre que múltiplos Steps estiverem
    prontos para execução, a escolha é feita por ordem lexicográfica
    do `step.id`.

    Decisões arquiteturais:
        - O pipeline deve formar um DAG acíclico
        - Dependências inexistentes são tratadas como erro estrutural
        - Identificadores de Step devem ser únicos e válidos
        - O algoritmo utilizado é uma variação determinística do algoritmo de Kahn

    Invariantes:
        - Nenhum Step aparece antes de suas dependências
        - Todos os Steps válidos aparecem exatamente uma vez na ordem final
        - A mesma entrada sempre produz a mesma ordem de execução

    Limites explícitos:
        - Não executa Steps
        - Não interage com RunContext
        - Não decide políticas de execução
        - Não registra eventos de rastreabilidade

    Args:
        steps (Iterable[Step]): Coleção de Steps declarativos do pipeline.

    Returns:
        List[Step]: Lista de Steps em ordem topológica determinística de execução.

    Raises:
        ValueError: Se algum Step possuir `id` inválido ou duplicado.
        UnknownDependencyError: Se um Step declarar dependência inexistente.
        CycleDetectedError: Se houver ciclo no grafo de dependências.

    Este método existe para garantir correção estrutural,
    determinismo e segurança no planejamento do pipeline.
    """
    step_list = list(steps)
    by_id: Dict[str, Step] = {}
    for s in step_list:
        sid = getattr(s, "id", None)
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("step.id must be a non-empty string")
        if sid in by_id:
            raise ValueError(f"Duplicate step id: {sid}")
        by_id[sid] = s

    # Validate dependencies exist
    deps: Dict[str, List[str]] = {}
    for sid, s in by_id.items():
        d = list(getattr(s, "depends_on", []) or [])
        for dep in d:
            if dep not in by_id:
                raise UnknownDependencyError(f"Step '{sid}' depends on unknown step '{dep}'")
        deps[sid] = d

    # Kahn's algorithm (deterministic)
    incoming_count: Dict[str, int] = {sid: 0 for sid in by_id}
    outgoing: Dict[str, Set[str]] = {sid: set() for sid in by_id}

    for sid, dlist in deps.items():
        incoming_count[sid] = len(dlist)
        for dep in dlist:
            outgoing[dep].add(sid)

    ready: List[str] = sorted([sid for sid, c in incoming_count.items() if c == 0])
    order_ids: List[str] = []

    while ready:
        sid = ready.pop(0)  # smallest lexicographic
        order_ids.append(sid)
        for child in sorted(outgoing[sid]):
            incoming_count[child] -= 1
            if incoming_count[child] == 0:
                # insert and keep list sorted for determinism
                ready.append(child)
                ready.sort()

    if len(order_ids) != len(by_id):
        raise CycleDetectedError("Cycle detected in step dependency graph")

    return [by_id[sid] for sid in order_ids]
