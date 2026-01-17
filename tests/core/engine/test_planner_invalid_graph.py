# tests/engine/test_planner_invalid_graph.py
"""
Testes de validação de grafos inválidos no planner do engine.

Este módulo valida o comportamento do planner ao lidar com grafos de
dependência inválidos, garantindo que apenas DAGs estruturais corretos
sejam aceitos para planejamento e execução.

Os testes asseguram que:
- dependências inexistentes são detectadas e rejeitadas
- ciclos explícitos entre Steps são identificados
- nenhuma ordenação parcial é produzida em grafos inválidos

Decisões arquiteturais:
    - O pipeline deve formar um DAG válido
    - Erros estruturais são tratados como falhas fatais
    - Exceções específicas são utilizadas para cada tipo de erro

Invariantes:
    - Qualquer erro estrutural invalida o plano de execução
    - O planner nunca retorna um plano parcial em caso de erro
    - A detecção de erro ocorre antes de qualquer execução

Limites explícitos:
    - Não valida mensagens detalhadas das exceções
    - Não valida integração com engine ou RunContext
    - Não valida políticas de execução (fail-fast, skip)

Este módulo existe para garantir segurança estrutural,
previsibilidade e correção no planejamento do pipeline.
"""

import pytest

try:
    from atlas_dataflow.core.engine.planner import plan_execution, CycleDetectedError, UnknownDependencyError
except Exception as e:
    plan_execution = None
    CycleDetectedError = None
    UnknownDependencyError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que as exceções do planner estejam disponíveis para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    validação estrutural do grafo de execução, falhando imediatamente
    quando as exceções canônicas do planner não podem ser importadas.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando contratos de erro do planner estão ausentes
        - Mensagem de erro lista exatamente as exceções esperadas
        - Evita falsos negativos causados por ImportError silencioso

    Invariantes:
        - Se as exceções existem, a função não produz efeitos colaterais
        - Se alguma exceção está ausente, o teste falha imediatamente
        - Não tenta fallback nem substituição por exceções genéricas

    Limites explícitos:
        - Não valida comportamento do planner
        - Não executa ordenação topológica
        - Não substitui testes funcionais de detecção de erro

    Usado para garantir:
        - Alinhamento entre testes e contratos de erro do planner
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito das regras de integridade do DAG
    """
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing planner errors. Implement:
- CycleDetectedError
- UnknownDependencyError
Import error: {_IMPORT_ERR}
""")


def test_cycle_detected(DummyStep):
    """
    Verifica que o planner detecta ciclos no grafo de dependências.

    Este teste valida que o planner do engine identifica corretamente
    ciclos explícitos entre Steps, rejeitando grafos que não são DAGs
    válidos para execução.

    Decisões arquiteturais:
        - O pipeline deve formar um DAG acíclico
        - Ciclos não são quebrados nem resolvidos automaticamente
        - A detecção de ciclo ocorre antes da geração do plano de execução

    Invariantes:
        - Qualquer ciclo invalida o grafo inteiro
        - A exceção levantada é específica (`CycleDetectedError`)
        - Nenhuma ordenação parcial é retornada

    Limites explícitos:
        - Não valida identificação do ciclo específico
        - Não valida múltiplos ciclos simultâneos
        - Não valida mensagens detalhadas da exceção

    Usado para garantir:
        - Correção estrutural do pipeline
        - Segurança contra deadlocks de execução
        - Conformidade com o modelo DAG do Atlas DataFlow
    """
    _require_imports()
    steps = [
        DummyStep(step_id="a", depends_on=["c"]),
        DummyStep(step_id="b", depends_on=["a"]),
        DummyStep(step_id="c", depends_on=["b"]),
    ]
    with pytest.raises(CycleDetectedError):
        plan_execution(steps)


def test_unknown_dependency(DummyStep):
    """
    Verifica que o planner rejeita Steps com dependências inexistentes.

    Este teste valida que o planner do engine detecta referências a
    dependências que não fazem parte do conjunto de Steps fornecido,
    tratando essa condição como erro estrutural.

    Decisões arquiteturais:
        - Todas as dependências declaradas em `depends_on` devem existir
        - Dependências desconhecidas não são ignoradas nem inferidas
        - A falha ocorre antes de qualquer ordenação ou execução

    Invariantes:
        - Um Step com dependência inexistente invalida o grafo inteiro
        - A exceção levantada é específica (`UnknownDependencyError`)
        - Nenhum plano parcial é produzido

    Limites explícitos:
        - Não valida mensagens da exceção
        - Não valida múltiplas dependências inválidas simultâneas
        - Não valida detecção de ciclos

    Usado para garantir:
        - Integridade estrutural do grafo de execução
        - Detecção precoce de erros de configuração
        - Segurança no planejamento do pipeline
    """
    _require_imports()
    steps = [
        DummyStep(step_id="a", depends_on=["x"]),
    ]
    with pytest.raises(UnknownDependencyError):
        plan_execution(steps)
