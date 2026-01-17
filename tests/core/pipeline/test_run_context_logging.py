# tests/pipeline/test_run_context_logging.py
"""
Testes de logging estruturado e coleta de warnings no RunContext.

Este módulo valida o comportamento do RunContext como ponto central
de observabilidade durante a execução de um pipeline no Atlas DataFlow.

Os testes asseguram que:
- warnings são coletados e agrupados por Step
- eventos de log são registrados de forma estruturada
- cada evento contém metadados mínimos de rastreabilidade
- campos adicionais são preservados sem perda

Decisões arquiteturais:
    - Logs não são tratados como strings livres, mas como eventos estruturados
    - Warnings são sinais não fatais e não interrompem execução
    - O RunContext atua como agregador de sinais de execução

Invariantes:
    - A coleção de warnings é indexada por `step_id`
    - A coleção de eventos cresce de forma incremental
    - `run_id` está presente em todos os eventos de log

Limites explícitos:
    - Não valida persistência dos logs
    - Não valida integração direta com Manifest
    - Não valida políticas de nível de log
    - Não valida impacto dos warnings no Engine

Este módulo existe para garantir observabilidade clara,
estruturada e rastreável durante a execução do pipeline.
"""

import pytest

try:
    from atlas_dataflow.core.pipeline.context import RunContext
except Exception as e:  # noqa: BLE001
    RunContext = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que a API de logging e warnings do RunContext esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes
    relacionados à observabilidade do RunContext, falhando
    imediatamente quando os métodos e atributos canônicos de logging
    e coleta de warnings não podem ser importados.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando contratos do RunContext estão ausentes
        - Mensagem de erro lista exatamente os métodos e atributos esperados
        - Evita falhas indiretas ou mensagens ambíguas nos testes

    Invariantes:
        - Se a API existe, a função não produz efeitos colaterais
        - Se a API está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento dos métodos de logging
        - Não adiciona eventos nem warnings
        - Não substitui testes funcionais do RunContext

    Usado para garantir:
        - Alinhamento entre testes e contratos de observabilidade
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do contrato de logging estruturado
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing RunContext logging/warnings API. Implement:"
            "- src/atlas_dataflow/core/pipeline/context.py (log, add_warning, events, warnings)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_structured_log_event(dummy_ctx):
    """
    Verifica que o RunContext registra eventos de log estruturados.

    Este teste valida que chamadas ao método de logging do RunContext
    produzem eventos estruturados, contendo informações essenciais
    de rastreabilidade e quaisquer campos adicionais fornecidos.

    Decisões arquiteturais:
        - Logs são tratados como eventos estruturados, não como texto livre
        - Cada evento de log inclui `run_id` e `step_id` explicitamente
        - Campos extras são aceitos e preservados sem filtragem implícita

    Invariantes:
        - Cada chamada a `log` adiciona um novo evento à coleção de eventos
        - O evento contém nível (`level`) e mensagem (`message`)
        - Metadados adicionais são mantidos no payload do evento

    Limites explícitos:
        - Não valida persistência dos eventos de log
        - Não valida integração com Manifest
        - Não valida política de níveis de log

    Usado para garantir:
        - Observabilidade estruturada durante execução do pipeline
        - Rastreabilidade de ações e mensagens por Step
        - Consistência do formato de eventos gerados pelo RunContext
    """
    _require_imports()
    dummy_ctx.log(step_id="ingest.load", level="INFO", message="hello", foo=1)
    assert len(dummy_ctx.events) >= 1
    ev = dummy_ctx.events[-1]
    assert ev["run_id"] == dummy_ctx.run_id
    assert ev["step_id"] == "ingest.load"
    assert ev["level"] == "INFO"
    assert ev["message"] == "hello"
    assert ev["foo"] == 1


def test_warning_collection(dummy_ctx):
    """
    Verifica que o RunContext coleta e organiza warnings por Step.

    Este teste valida que avisos emitidos durante a execução de Steps
    são registrados no RunContext de forma estruturada, permitindo
    rastreabilidade e inspeção posterior sem interromper o fluxo
    de execução.

    Decisões arquiteturais:
        - Warnings são associados explicitamente a um `step_id`
        - A coleta de warnings não altera o status de execução
        - O RunContext atua como repositório central de sinais não fatais

    Invariantes:
        - Warnings são agrupados por `step_id`
        - A ordem de inserção das mensagens é preservada
        - A adição de warnings não lança exceções

    Limites explícitos:
        - Não valida persistência de warnings
        - Não valida integração com Manifest
        - Não valida impacto dos warnings no Engine

    Usado para garantir:
        - Observabilidade de problemas não críticos
        - Separação entre erros fatais e avisos
        - Transparência durante execução do pipeline
    """
    _require_imports()
    dummy_ctx.add_warning(step_id="audit.schema", message="missing column")
    assert "audit.schema" in dummy_ctx.warnings
    assert dummy_ctx.warnings["audit.schema"] == ["missing column"]
