# tests/engine/test_executor_happy_path.py
"""
Testes do fluxo de execução bem-sucedido do Engine (happy path).

Este módulo valida o comportamento do Engine quando o pipeline está
estruturalmente correto, todas as dependências são resolvidas e
nenhum Step falha durante a execução.

Os testes asseguram que:
- Steps são executados na ordem planejada
- Steps executados com sucesso recebem status SUCCESS
- O resultado final consolida corretamente o estado de todos os Steps

Decisões arquiteturais:
    - O Engine coordena planejamento e execução de forma determinística
    - A execução respeita as dependências declaradas entre Steps
    - O estado final reflete fielmente o resultado de cada Step

Invariantes:
    - Steps executados sem erro resultam em SUCCESS
    - Todos os Steps aparecem no resultado final
    - A execução não introduz estados implícitos

Limites explícitos:
    - Não valida política de fail-fast
    - Não valida persistência de resultados
    - Não valida integração com Manifest ou Event Log

Este módulo existe para garantir a base funcional do Engine
em cenários ideais de execução.
"""

import pytest

try:
    from atlas_dataflow.core.engine.engine import Engine
    from atlas_dataflow.core.pipeline.types import StepStatus
except Exception as e:
    Engine = None
    StepStatus = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que a implementação do Engine esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    execução do Engine, falhando imediatamente quando a classe canônica
    responsável pela execução do pipeline não pode ser importada.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando o contrato do Engine está ausente
        - Mensagem de erro aponta diretamente para o módulo e classe esperados
        - Evita falhas indiretas ou erros pouco informativos nos testes

    Invariantes:
        - Se o Engine existe, a função não produz efeitos colaterais
        - Se o Engine está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento do Engine
        - Não executa pipeline
        - Não substitui testes funcionais de execução

    Usado para garantir:
        - Alinhamento entre testes e o contrato do Engine
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito da responsabilidade de execução do pipeline
    """
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing Engine. Implement:
- src/atlas_dataflow/core/engine/engine.py (Engine)
Import error: {_IMPORT_ERR}
""")


def test_happy_path(DummyStep, dummy_ctx):
    """
    Verifica o fluxo de execução bem-sucedido do Engine em um pipeline válido.

    Este teste valida o comportamento do Engine quando todos os Steps
    estão corretamente configurados, possuem dependências resolvidas
    e executam sem falhas.

    Decisões arquiteturais:
        - Steps são executados na ordem planejada pelo planner
        - Cada Step executado com sucesso recebe status SUCCESS
        - O Engine consolida o resultado final de todos os Steps executados

    Invariantes:
        - Steps sem falha resultam em status SUCCESS
        - Dependências são respeitadas durante a execução
        - Todos os Steps aparecem no resultado final

    Limites explícitos:
        - Não valida ordenação detalhada do planner
        - Não valida registro de eventos ou Manifest
        - Não valida comportamento de fail-fast

    Usado para garantir:
        - Funcionamento básico do Engine em condições ideais
        - Integração correta entre planner, execução e RunContext
        - Base de confiança para testes de cenários de falha
    """
    _require_imports()
    steps = [
        DummyStep(step_id="a"),
        DummyStep(step_id="b", depends_on=["a"]),
    ]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["a"].status == StepStatus.SUCCESS
    assert result.steps["b"].status == StepStatus.SUCCESS
