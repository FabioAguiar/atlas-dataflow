# src/atlas_dataflow/core/pipeline/step.py
"""
Contrato canônico de Step do Atlas DataFlow.

Este módulo define o protocolo formal que qualquer Step deve satisfazer
para ser executável dentro do pipeline do Atlas DataFlow.

Um Step é a menor unidade executável do pipeline e representa uma
operação atômica e autocontida, responsável apenas por sua própria
lógica de execução.

Responsabilidades de um Step:
    - executar sua lógica de forma determinística
    - interagir exclusivamente via RunContext
    - produzir um StepResult imutável

Princípios fundamentais:
    - Steps não conhecem o Engine nem o planner
    - Steps não controlam ordem de execução
    - Comunicação entre Steps é mediada pelo RunContext
    - Conformidade é garantida por duck typing (@runtime_checkable)

Invariantes:
    - Cada Step possui um `step_id` único
    - Cada Step declara explicitamente suas dependências
    - O método `run` é chamado no máximo uma vez por execução

Limites explícitos:
    - Não contém lógica de planejamento
    - Não contém lógica de execução global
    - Não registra eventos de rastreabilidade
    - Não define políticas de execução

Este módulo existe para garantir desacoplamento,
clareza contratual e testabilidade dos Steps.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, List

from .context import RunContext
from .types import StepKind, StepResult


@runtime_checkable
class Step(Protocol):
    """
    Contrato canônico de um Step do Atlas DataFlow.

    Este protocolo define a interface mínima que qualquer Step deve
    implementar para ser executável pelo Engine do Atlas DataFlow.

    Um Step representa uma unidade atômica de execução dentro do pipeline,
    sendo responsável apenas por:
        - executar sua lógica específica
        - produzir um `StepResult`
        - interagir exclusivamente via `RunContext`

    A validação do protocolo ocorre em runtime (`@runtime_checkable`),
    permitindo verificação por duck typing durante testes e execução.

    Atributos obrigatórios:
        - id: identificador único e estável do Step
        - kind: classificação semântica do Step (`StepKind`)
        - depends_on: lista de `step_id` dos Steps dos quais depende

    Decisões arquiteturais:
        - Steps não conhecem o Engine nem o planner
        - Steps não controlam ordem de execução
        - Comunicação entre Steps ocorre apenas via `RunContext`
        - O protocolo não impõe herança, apenas conformidade estrutural

    Invariantes:
        - `id` é único no contexto de um pipeline
        - `run` é executado no máximo uma vez por execução
        - O retorno de `run` é sempre um `StepResult`

    Limites explícitos:
        - Não define lógica de retry ou tratamento de exceções
        - Não registra eventos no Manifest diretamente
        - Não decide políticas de execução (fail-fast, skip)

    Este protocolo existe para garantir desacoplamento,
    testabilidade e clareza contratual entre Steps e o Engine.
    """
    id: str
    kind: StepKind
    depends_on: List[str]

    def run(self, ctx: RunContext) -> StepResult:
        """Executa a etapa uma única vez usando exclusivamente o RunContext."""
        ...
