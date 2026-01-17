# tests/pipeline/test_step_protocol.py
"""
Testes do protocolo de Step do pipeline.

Este módulo valida o contrato canônico de Step definido no core do
Atlas DataFlow, garantindo que implementações baseadas em duck typing
sejam compatíveis com o pipeline e o engine.

Os testes asseguram que:
- Steps não precisam herdar de uma classe base concreta
- A conformidade é verificada via protocolo (`typing.Protocol`)
  com checagem em tempo de execução (`@runtime_checkable`)
- A execução de um Step retorna obrigatoriamente um StepResult

Decisões arquiteturais:
    - Steps são definidos por contrato estrutural, não por herança
    - O protocolo define apenas o mínimo necessário para execução
    - A verificação em runtime é intencional e suportada

Invariantes:
    - Um Step válido expõe atributos mínimos (`id`, `kind`, `depends_on`)
    - Um Step válido implementa `run(ctx)`
    - A execução retorna um `StepResult` bem formado

Limites explícitos:
    - Não valida lógica de domínio dos Steps
    - Não valida integração com engine ou planner
    - Não valida registro ou ordenação de Steps
    - Não valida efeitos colaterais além do retorno

Este módulo existe para garantir extensibilidade, desacoplamento
e estabilidade do contrato de execução do pipeline.
"""

import pytest

try:
    from atlas_dataflow.core.pipeline.step import Step
    from atlas_dataflow.core.pipeline.types import StepResult, StepKind
except Exception as e:  # noqa: BLE001
    Step = None
    StepResult = None
    StepKind = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que os módulos centrais do pipeline estejam disponíveis para os testes.

    Esta função atua como uma pré-condição explícita para os testes do
    protocolo de Step, falhando imediatamente quando os módulos
    canônicos do pipeline ou seus tipos fundamentais não podem ser
    importados.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando contratos do pipeline estão ausentes
        - Mensagem de erro lista exatamente os módulos e símbolos esperados
        - Evita erros indiretos ou falhas menos informativas nos testes

    Invariantes:
        - Se os módulos existem, a função não produz efeitos colaterais
        - Se algum módulo está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento dos tipos importados
        - Não instancia Steps ou executa pipeline
        - Não substitui testes funcionais do core de pipeline

    Usado para garantir:
        - Alinhamento entre testes e contratos do pipeline
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do protocolo de Step
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing pipeline core modules. Implement:"
            "- src/atlas_dataflow/core/pipeline/types.py (StepKind, StepStatus, StepResult)"
            "- src/atlas_dataflow/core/pipeline/step.py (Step Protocol)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_dummy_step_satisfies_protocol(DummyStep, dummy_ctx):
    """
    Verifica que um Step duck-typed satisfaz o protocolo canônico de Step.

    Este teste valida que uma implementação mínima de Step, fornecida
    por fixture, é compatível com o protocolo `Step` definido no core,
    utilizando verificação em tempo de execução (`@runtime_checkable`).

    Decisões arquiteturais:
        - Steps são definidos por protocolo, não por herança concreta
        - Compatibilidade é verificada via `isinstance(step, Step)`
        - A execução do Step retorna obrigatoriamente um `StepResult`

    Invariantes:
        - Um Step válido expõe os atributos mínimos exigidos pelo protocolo
        - O método `run(ctx)` é executável com um RunContext válido
        - O resultado da execução é sempre um `StepResult`

    Limites explícitos:
        - Não valida lógica de domínio do Step
        - Não valida efeitos colaterais além do retorno
        - Não valida integração com engine ou registry

    Usado para garantir:
        - Flexibilidade de implementação de Steps
        - Contrato estável entre pipeline e engine
        - Adoção correta de duck typing no core
    """
    _require_imports()
    step = DummyStep(step_id="ingest.load", kind=StepKind.DIAGNOSTIC)
    assert isinstance(step, Step), "DummyStep must satisfy Step Protocol (@runtime_checkable expected)."
    result = step.run(dummy_ctx)
    assert isinstance(result, StepResult)
    assert result.step_id == "ingest.load"
