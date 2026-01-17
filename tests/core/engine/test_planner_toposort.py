# tests/engine/test_planner_toposort.py
"""
Testes de ordenação topológica do planner do engine.

Este módulo valida o comportamento do planner responsável por
derivar uma ordem de execução determinística a partir das
dependências explícitas entre Steps.

Os testes asseguram que:
- a ordem de execução respeita rigorosamente `depends_on`
- Steps são planejados somente após todas as suas dependências
- o resultado do planejamento é determinístico para o mesmo grafo

Decisões arquiteturais:
    - O planner opera sobre um DAG explícito de Steps
    - A ordenação é puramente estrutural (não executa Steps)
    - Dependências inexistentes ou ciclos são tratados como erro
      (cobertos em testes específicos)

Invariantes:
    - Nenhum Step aparece antes de suas dependências
    - Todos os Steps válidos aparecem exatamente uma vez no plano
    - A ordem retornada é estável e previsível

Limites explícitos:
    - Não valida execução de Steps
    - Não valida políticas do engine (fail-fast, skip, status)
    - Não valida integração com RunContext ou Manifest

Este módulo existe para garantir correção estrutural,
determinismo e segurança no planejamento do pipeline.
"""

import pytest

try:
    from atlas_dataflow.core.engine.planner import plan_execution
except Exception as e:
    plan_execution = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que a implementação do planner esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    ordenação topológica do engine, falhando imediatamente quando a
    função canônica `plan_execution` não pode ser importada.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando o planner está ausente
        - Mensagem de erro aponta diretamente para o módulo e função esperados
        - Evita falhas indiretas ou erros pouco informativos nos testes

    Invariantes:
        - Se o planner existe, a função não produz efeitos colaterais
        - Se o planner está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida o comportamento do planner
        - Não executa ordenação topológica
        - Não substitui testes funcionais de planejamento

    Usado para garantir:
        - Alinhamento entre testes e o contrato do planner
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito da responsabilidade do engine planner
    """
    if _IMPORT_ERR is not None:
        pytest.fail(f"""Missing planner. Implement:
- src/atlas_dataflow/core/engine/planner.py (plan_execution)
Import error: {_IMPORT_ERR}
""")


def test_toposort_linear(DummyStep):
    """
    Verifica a ordenação topológica correta em um grafo linear de Steps.

    Este teste valida que o planner do engine produz uma ordem de execução
    determinística quando os Steps possuem dependências lineares simples
    (A → B → C).

    Decisões arquiteturais:
        - A ordem de execução é derivada exclusivamente de `depends_on`
        - O planner respeita dependências explícitas sem inferências implícitas
        - O resultado é uma lista ordenada de Steps prontos para execução

    Invariantes:
        - Um Step sempre aparece após todas as suas dependências
        - Nenhum Step é omitido do plano final
        - A ordem retornada é determinística para o mesmo conjunto de Steps

    Limites explícitos:
        - Não valida execução dos Steps
        - Não valida comportamento em grafos com múltiplas raízes
        - Não valida detecção de ciclos ou dependências inválidas

    Usado para garantir:
        - Correção básica do algoritmo de ordenação topológica
        - Base confiável para execução sequencial no engine
        - Previsibilidade no planejamento do pipeline
    """
    _require_imports()
    steps = [
        DummyStep(step_id="a"),
        DummyStep(step_id="b", depends_on=["a"]),
        DummyStep(step_id="c", depends_on=["b"]),
    ]
    order = plan_execution(steps)
    assert [s.id for s in order] == ["a", "b", "c"]
