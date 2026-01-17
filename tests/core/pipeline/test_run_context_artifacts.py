# tests/pipeline/test_run_context_artifacts.py
"""
Testes de armazenamento e isolamento de artefatos no RunContext.

Este módulo valida o comportamento do RunContext como store
determinístico e isolado de artefatos produzidos durante a
execução de um pipeline no Atlas DataFlow.

Os testes asseguram que:
- artefatos são registrados explicitamente por chave
- artefatos podem ser consultados e recuperados de forma previsível
- a ausência de artefatos gera erro explícito
- múltiplos contextos permanecem isolados entre si

Decisões arquiteturais:
    - O RunContext não compartilha estado entre instâncias
    - Artefatos não são criados implicitamente
    - A ausência de artefato é tratada como erro
    - O RunContext atua como fonte única de verdade para dados em memória

Invariantes:
    - Cada RunContext possui seu próprio store interno
    - `set_artifact` e `get_artifact` operam de forma determinística
    - `has_artifact` reflete fielmente o estado interno

Limites explícitos:
    - Não valida persistência de artefatos
    - Não valida integração com engine ou Manifest
    - Não valida concorrência ou sincronização entre threads

Este módulo existe para garantir previsibilidade,
isolamento e clareza no fluxo de dados entre Steps.
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
    Garante que a implementação do RunContext esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes
    relacionados ao armazenamento e recuperação de artefatos no
    RunContext, falhando imediatamente quando a classe canônica
    não pode ser importada.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando o contrato do RunContext está ausente
        - Mensagem de erro descreve exatamente o módulo e a responsabilidade esperada
        - Evita falhas indiretas ou erros menos informativos durante os testes

    Invariantes:
        - Se o RunContext existe, a função não produz efeitos colaterais
        - Se o RunContext está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento dos métodos do RunContext
        - Não cria instâncias de contexto
        - Não substitui testes funcionais de artefatos

    Usado para garantir:
        - Alinhamento entre testes e contratos de artefatos do pipeline
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do contrato de isolamento e armazenamento
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing RunContext. Implement:"
            "- src/atlas_dataflow/core/pipeline/context.py (RunContext with artifact store)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_artifact_set_get(dummy_ctx):
    """
    Verifica o ciclo básico de registro e recuperação de artefatos no RunContext.

    Este teste valida que artefatos podem ser:
    - registrados explicitamente via `set_artifact`
    - verificados via `has_artifact`
    - recuperados integralmente via `get_artifact`

    Decisões arquiteturais:
        - Artefatos são armazenados por chave explícita
        - Não há transformação, cópia ou validação implícita do valor
        - O RunContext atua como store simples e determinístico de artefatos

    Invariantes:
        - Um artefato registrado é imediatamente acessível
        - O valor recuperado é idêntico ao valor armazenado
        - `has_artifact` reflete corretamente o estado interno

    Limites explícitos:
        - Não valida persistência de artefatos
        - Não valida concorrência ou acesso paralelo
        - Não valida integração com engine ou pipeline

    Usado para garantir:
        - Contrato básico de armazenamento de artefatos
        - Previsibilidade no fluxo de dados entre Steps
        - Ausência de comportamento implícito no RunContext
    """
    _require_imports()
    dummy_ctx.set_artifact("dataset.raw", [1, 2, 3])
    assert dummy_ctx.has_artifact("dataset.raw") is True
    assert dummy_ctx.get_artifact("dataset.raw") == [1, 2, 3]


def test_artifact_missing_key_raises(dummy_ctx):
    """
    Verifica que acessar um artefato inexistente levanta exceção explícita.

    Este teste valida que o RunContext falha de forma clara e imediata
    ao tentar recuperar um artefato que não foi registrado, evitando
    retornos silenciosos ou valores implícitos.

    Decisões arquiteturais:
        - A ausência de artefato é tratada como erro explícito
        - `get_artifact` não retorna valores default
        - A exceção utilizada é `KeyError`, coerente com acesso por chave

    Invariantes:
        - Nenhum artefato é criado implicitamente
        - O estado interno do contexto não é modificado pela falha
        - A exceção é sempre levantada para chaves inexistentes

    Limites explícitos:
        - Não valida mensagens de erro
        - Não valida comportamento de `has_artifact`
        - Não valida integração com engine ou Manifest

    Usado para garantir:
        - Contrato explícito de acesso a artefatos
        - Detecção precoce de erros de pipeline
        - Ausência de comportamento silencioso ou ambíguo
    """
    _require_imports()
    with pytest.raises(KeyError):
        dummy_ctx.get_artifact("missing.key")


def test_context_isolation(dummy_config, dummy_contract):
    """
    Verifica que instâncias de RunContext são isoladas entre si.

    Este teste valida que artefatos registrados em um RunContext
    não vazam para outras instâncias, garantindo isolamento total
    entre execuções distintas de pipeline.

    Decisões arquiteturais:
        - Cada RunContext mantém seu próprio store interno de artefatos
        - Não existe estado global compartilhado entre contextos
        - O isolamento é garantido por instância, não por run_id apenas

    Invariantes:
        - Artefatos adicionados em um contexto não aparecem em outro
        - Métodos de leitura (`has_artifact`) refletem apenas o estado local
        - A criação de múltiplos contextos é segura e independente

    Limites explícitos:
        - Não valida persistência de artefatos
        - Não valida integração com engine ou pipeline
        - Não valida conteúdo ou tipo dos artefatos

    Usado para garantir:
        - Segurança de execução concorrente
        - Reprodutibilidade de runs
        - Ausência de efeitos colaterais entre pipelines
    """
    _require_imports()
    from datetime import datetime, timezone
    ctx1 = RunContext(run_id="r1", created_at=datetime(2026,1,16,tzinfo=timezone.utc), config=dummy_config, contract=dummy_contract, meta={})
    ctx2 = RunContext(run_id="r2", created_at=datetime(2026,1,16,tzinfo=timezone.utc), config=dummy_config, contract=dummy_contract, meta={})
    ctx1.set_artifact("x", 1)
    assert ctx2.has_artifact("x") is False
