# tests/test_smoke.py
"""
Testes de sanidade estrutural (smoke tests) do Atlas DataFlow.

Este módulo contém testes mínimos cujo único objetivo é garantir que:
- o repositório está estruturalmente válido
- o ambiente de testes (pytest) está funcional
- a descoberta e execução de testes ocorre sem erros

Durante o Milestone M0, estes testes não validam comportamento de domínio,
engine, pipeline ou contratos semânticos. Eles existem como sentinelas
iniciais de integridade do projeto.

Invariantes:
    - Estes testes devem sempre passar em um setup correto
    - Não dependem de configuração, contrato, filesystem ou I/O
    - Não importam módulos do core intencionalmente

Limites explícitos:
    - Não testar lógica de negócio
    - Não testar fluxo de execução
    - Não acumular asserts funcionais
    - Não evoluir para testes unitários ou de integração

Decisão arquitetural:
    Separar explicitamente testes de sanidade estrutural de testes
    de domínio evita falsos positivos e garante feedback imediato
    durante bootstrap, CI e refactors iniciais.
"""



def test_smoke():
    """
    Smoke test mínimo do repositório.

    Este teste existe exclusivamente para validar que:
    - o ambiente de testes está corretamente configurado
    - o pytest consegue descobrir e executar testes
    - o projeto pode ser importado sem falhas estruturais

    Ele **não valida comportamento de domínio**, lógica de pipeline,
    engine ou contratos. Sua função é servir como sentinela inicial
    de integridade do repositório durante M0.

    Invariantes:
        - Deve sempre passar enquanto o setup básico do projeto estiver correto
        - Não depende de config, contract, engine ou filesystem

    Limites explícitos:
        - Não testa nenhuma funcionalidade real
        - Não deve crescer nem acumular asserts adicionais
        - Não substitui testes unitários ou de integração

    Motivação arquitetural:
        Garante feedback imediato em CI/CD e durante bootstrap do projeto,
        antes mesmo da introdução de testes de domínio.
    """
    assert True
