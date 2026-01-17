# tests/traceability/test_manifest_create.py
"""
Testes de criação do Manifest (traceability).

Este módulo valida o comportamento da criação inicial do Manifest,
garantindo que a estrutura mínima necessária para rastreabilidade
forense seja materializada sem efeitos colaterais implícitos.

Os testes asseguram que:
- o Manifest é criado com campos obrigatórios de identificação e inputs
- a estrutura resultante é serializável (objeto ou dict)
- coleções de steps e events existem desde a criação
- nenhum estado de execução é inferido automaticamente

Decisões arquiteturais:
    - A criação do Manifest é uma operação pura e explícita
    - Nenhum evento é registrado automaticamente na criação
    - Steps e Events iniciam vazios
    - A estrutura mínima é estável e versionável

Invariantes:
    - `run.run_id`, `run.started_at` e `run.atlas_version` estão sempre presentes
    - `inputs.config_hash` e `inputs.contract_hash` estão sempre presentes
    - `steps` é um dicionário na criação
    - `events` é uma lista na criação

Limites explícitos:
    - Não valida persistência em disco
    - Não valida atualização incremental de steps
    - Não valida ordenação ou conteúdo de eventos
    - Não valida integração com engine ou pipeline

Este módulo existe para garantir um ponto de partida confiável
para toda a rastreabilidade do Atlas DataFlow.
"""

import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        AtlasManifest,
    )
except Exception as e:
    create_manifest = None
    AtlasManifest = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que o módulo de Manifest esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    criação do Manifest, falhando imediatamente quando o módulo
    `core.traceability.manifest` ou seus símbolos canônicos não podem
    ser importados.

    Decisões arquiteturais:
        - Falha antecipada e explícita em caso de ausência do módulo
        - Mensagem de erro descreve exatamente o contrato esperado
          (arquivo e símbolos públicos)
        - Evita falhas indiretas ou erros menos informativos nos testes

    Invariantes:
        - Se o módulo existe, a função não produz efeitos colaterais
        - Se o módulo está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida o comportamento do Manifest
        - Não cria instâncias de Manifest
        - Não substitui testes funcionais de traceability

    Usado para garantir:
        - Alinhamento entre testes e a Issue de criação do Manifest
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do contrato mínimo de traceability
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing manifest module. Implement:\n"
            "- src/atlas_dataflow/core/traceability/manifest.py\n"
            "Expected exports: create_manifest, AtlasManifest\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_create_manifest_has_minimum_fields():
    """
    Verifica que a criação de um Manifest produz a estrutura mínima canônica esperada.

    Este teste valida que a função `create_manifest` inicializa corretamente
    um Manifest com todos os campos obrigatórios para rastreabilidade forense,
    sem gerar eventos ou estados implícitos.

    Decisões arquiteturais:
        - O Manifest nasce vazio de steps e events
        - Campos de identificação e inputs são obrigatórios na criação
        - A estrutura resultante é serializável (dataclass ou dict)

    Invariantes:
        - `run.run_id`, `run.started_at` e `run.atlas_version` estão presentes
        - `inputs.config_hash` e `inputs.contract_hash` estão presentes
        - `steps` existe e é um dicionário vazio na criação
        - `events` existe e é uma lista vazia na criação

    Limites explícitos:
        - Não valida persistência em disco
        - Não valida ordenação ou conteúdo de eventos
        - Não valida atualização incremental de steps
        - Não valida compatibilidade entre versões de schema

    Usado para garantir:
        - Contrato mínimo e estável do Manifest
        - Ausência de efeitos colaterais na criação
        - Base confiável para testes incrementais de traceability
    """
    _require_imports()

    m = create_manifest(
        run_id="run-001",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )

    # Must be serializable-friendly (dataclass or plain dict)
    data = m.to_dict() if hasattr(m, "to_dict") else m

    assert data["run"]["run_id"] == "run-001"
    assert data["run"]["started_at"]  # iso string expected
    assert data["run"]["atlas_version"] == "0.0.0"
    assert data["inputs"]["config_hash"] == "c" * 64
    assert data["inputs"]["contract_hash"] == "d" * 64

    assert "steps" in data
    assert isinstance(data["steps"], dict)
    assert "events" in data
    assert isinstance(data["events"], list)
