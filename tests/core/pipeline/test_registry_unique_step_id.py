# tests/pipeline/test_registry_unique_step_id.py
"""
Testes de unicidade de identificadores no StepRegistry.

Este módulo valida o comportamento do StepRegistry em relação ao
registro de Steps, garantindo que cada Step possua um identificador
único dentro do pipeline.

Os testes asseguram que:
- Steps com `step_id` distintos são aceitos normalmente
- Steps com `step_id` duplicados são rejeitados explicitamente
- A violação de unicidade resulta em exceção específica

Decisões arquiteturais:
    - `step_id` é a chave primária de um Step no registry
    - A unicidade é estritamente imposta no momento do registro
    - Exceções específicas são usadas para sinalizar erro estrutural

Invariantes:
    - O registry nunca contém dois Steps com o mesmo `step_id`
    - A tentativa de duplicidade não corrompe o estado interno
    - A ordem de registro é preservada para Steps válidos

Limites explícitos:
    - Não valida ordenação topológica
    - Não valida execução de Steps
    - Não valida integração com planner ou engine

Este módulo existe para garantir integridade estrutural,
previsibilidade e segurança no gerenciamento de Steps do pipeline.
"""
import pytest

try:
    from atlas_dataflow.core.pipeline.registry import StepRegistry, DuplicateStepIdError
except Exception as e:  # noqa: BLE001
    StepRegistry = None
    DuplicateStepIdError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que a implementação do StepRegistry esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes
    relacionados ao registro e validação de unicidade de Steps,
    falhando imediatamente quando o registry canônico ou suas exceções
    associadas não podem ser importados.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando o contrato do StepRegistry está ausente
        - Mensagem de erro descreve exatamente os símbolos públicos esperados
        - Evita falhas indiretas ou erros pouco informativos durante os testes

    Invariantes:
        - Se o StepRegistry existe, a função não produz efeitos colaterais
        - Se o StepRegistry está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento interno do registry
        - Não adiciona Steps
        - Não substitui testes funcionais de unicidade

    Usado para garantir:
        - Alinhamento entre testes e contratos do registry
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito da regra de unicidade de `step_id`
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing StepRegistry. Implement:"
            "- src/atlas_dataflow/core/pipeline/registry.py (StepRegistry, DuplicateStepIdError)"
            f"Import error: {_IMPORT_ERR}"
        )


def test_registry_rejects_duplicate_step_id(DummyStep):
    """
    Verifica que o StepRegistry rejeita Steps com identificadores duplicados.

    Este teste valida que o StepRegistry impõe unicidade estrita de `step_id`,
    levantando uma exceção explícita quando um Step com identificador já
    registrado é adicionado novamente.

    Decisões arquiteturais:
        - `step_id` é a chave primária e imutável de um Step no registry
        - Duplicidade é considerada erro estrutural, não comportamento aceitável
        - A exceção utilizada é específica (`DuplicateStepIdError`)

    Invariantes:
        - O primeiro Step com um dado `step_id` é aceito
        - O segundo Step com o mesmo `step_id` é rejeitado
        - O estado interno do registry não é alterado após a falha

    Limites explícitos:
        - Não valida mensagem da exceção
        - Não valida comportamento do registry após múltiplas falhas
        - Não valida integração com planner ou engine

    Usado para garantir:
        - Integridade estrutural do pipeline
        - Previsibilidade no registro de Steps
        - Detecção precoce de erros de configuração do pipeline
    """
    _require_imports()
    reg = StepRegistry()
    reg.add(DummyStep(step_id="ingest.load"))
    with pytest.raises(DuplicateStepIdError):
        reg.add(DummyStep(step_id="ingest.load"))


def test_registry_accepts_unique_ids(DummyStep):
    """
    Verifica que o StepRegistry aceita Steps com identificadores únicos.

    Este teste valida que o StepRegistry permite o registro de múltiplos
    Steps desde que cada um possua um `step_id` distinto, preservando
    todos eles na coleção interna.

    Decisões arquiteturais:
        - A unicidade de Steps é definida exclusivamente por `step_id`
        - O registry não normaliza nem transforma identificadores
        - A ordem de listagem reflete a ordem de inserção

    Invariantes:
        - Steps com IDs distintos são aceitos sem erro
        - Todos os Steps registrados permanecem acessíveis via `list()`
        - Os IDs retornados correspondem exatamente aos IDs fornecidos

    Limites explícitos:
        - Não valida comportamento em caso de IDs duplicados
        - Não valida integração com planner ou engine
        - Não valida ordenação topológica

    Usado para garantir:
        - Contrato básico de registro de Steps
        - Previsibilidade no gerenciamento de identificadores
        - Base correta para validações de duplicidade
    """
    _require_imports()
    reg = StepRegistry()
    reg.add(DummyStep(step_id="ingest.load"))
    reg.add(DummyStep(step_id="audit.schema_types"))
    assert [s.id for s in reg.list()] == ["ingest.load", "audit.schema_types"]
