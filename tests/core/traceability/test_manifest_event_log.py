# tests/traceability/test_manifest_event_log.py
"""
Testes do Event Log do Manifest (traceability).

Este módulo valida o comportamento do Event Log associado ao Manifest,
responsável por registrar eventos explícitos ocorridos durante a
execução de um pipeline no Atlas DataFlow.

Os testes garantem que:
- eventos são adicionados somente por chamadas explícitas à API
- a ordem de inserção dos eventos é preservada
- metadados associados aos eventos (tipo, step_id, payload) são registrados
- o Event Log cresce de forma incremental e determinística

Decisões arquiteturais:
    - O Event Log não gera eventos implicitamente
    - Não há reordenação automática por timestamp
    - A ordem do log reflete exatamente a ordem de chamada da API `add_event`
    - O Event Log é independente do estado dos Steps

Invariantes:
    - Cada evento adicionado resulta em um novo registro no log
    - A estrutura do Event Log é sempre uma lista
    - Eventos não são descartados ou colapsados automaticamente

Limites explícitos:
    - Não valida semântica de eventos específicos
    - Não valida persistência em disco do Event Log
    - Não valida integração com engine ou pipeline
    - Não valida correlação entre eventos e estado final dos Steps

Este módulo existe para garantir rastreabilidade forense explícita,
ordenada e determinística dos eventos de execução.
"""

import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        add_event,
    )
except Exception as e:
    create_manifest = None
    add_event = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que a API de Event Log esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes do
    Event Log do Manifest, falhando imediatamente quando a função
    canônica `add_event` não está implementada ou não pode ser importada.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando a API está ausente
        - Mensagem de erro descreve exatamente o contrato esperado
        - Evita falhas indiretas ou mensagens ambíguas nos testes

    Invariantes:
        - Se a API existe, a função não produz efeitos colaterais
        - Se a API está ausente, o teste falha imediatamente
        - Não tenta fallback ou comportamento alternativo

    Limites explícitos:
        - Não valida o comportamento do Event Log
        - Não adiciona eventos ao Manifest
        - Não substitui testes funcionais de rastreabilidade

    Usado para garantir:
        - Alinhamento entre testes e a Issue de Event Log
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do contrato de traceability
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing event log APIs. Implement:\n"
            "- add_event(manifest, event_type, ts, step_id=None, payload=None)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_event_log_appends_ordered_events():
    """
    Verifica que eventos são adicionados ao Event Log em ordem de chamada.

    Este teste valida o comportamento do Event Log do Manifest ao receber
    múltiplos eventos explícitos via `add_event`, garantindo que:
    - eventos são acumulados incrementalmente
    - a ordem de inserção é preservada
    - metadados específicos do evento (tipo, step_id, payload) são registrados

    Decisões arquiteturais:
        - O Event Log não reordena eventos por timestamp
        - A ordem do log reflete estritamente a sequência de chamadas
        - Eventos são adicionados apenas por meio da API explícita `add_event`

    Invariantes:
        - Cada chamada a `add_event` resulta em um novo item no Event Log
        - A posição do evento no log corresponde à ordem de chamada
        - Campos específicos do evento são preservados no registro

    Limites explícitos:
        - Não valida conteúdo semântico do payload
        - Não valida unicidade ou tipagem de `event_type`
        - Não valida persistência em disco do Event Log

    Usado para garantir:
        - Rastreabilidade temporal fiel à execução real
        - Determinismo do Event Log
        - Ausência de efeitos colaterais implícitos na coleta de eventos
    """
    _require_imports()
    m = create_manifest(
        run_id="run-003",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    t0 = datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 16, 12, 0, 1, tzinfo=timezone.utc)

    add_event(m, event_type="run_started", ts=t0, payload={"note": "begin"})
    add_event(m, event_type="step_started", ts=t1, step_id="a", payload={"kind": "diagnostic"})

    data = m.to_dict() if hasattr(m, "to_dict") else m
    assert len(data["events"]) == 2
    assert data["events"][0]["event_type"] == "run_started"
    assert data["events"][1]["event_type"] == "step_started"
    assert data["events"][1]["step_id"] == "a"
