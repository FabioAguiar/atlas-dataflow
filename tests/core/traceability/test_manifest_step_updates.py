# tests/traceability/test_manifest_step_updates.py
"""
Testes de atualização incremental de Steps no Manifest (traceability).

Este módulo valida o comportamento do sistema de rastreabilidade do
Atlas DataFlow quando eventos explícitos de execução de Steps são
aplicados incrementalmente a um Manifest existente.

Os testes garantem que:
- Steps são registrados no Manifest apenas quando eventos explícitos ocorrem
- Transições de status (STARTED, SUCCESS, FAILED) são consolidadas corretamente
- Timestamps, duração e metadados de execução são preservados
- Informações de erro são registradas em caso de falha

Decisões arquiteturais:
    - O Manifest não emite eventos implicitamente
    - Atualizações de estado ocorrem apenas via APIs explícitas
      (`step_started`, `step_finished`, `step_failed`)
    - O Manifest pode ser representado como objeto ou dict,
      preservando compatibilidade de acesso nos testes

Invariantes:
    - O estado final do Step reflete fielmente a sequência de eventos aplicada
    - Campos temporais são fornecidos externamente e não inferidos
    - A ausência de eventos implica ausência de estado no Manifest

Limites explícitos:
    - Não valida persistência em disco do Manifest
    - Não valida ordenação global do Event Log
    - Não valida integração com engine ou pipeline

Este módulo existe para garantir rastreabilidade forense precisa e
determinística dos estados de execução de Steps.
"""

import pytest
from datetime import datetime, timezone

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        step_started,
        step_finished,
        step_failed,
    )
    from atlas_dataflow.core.pipeline.types import StepStatus
except Exception as e:
    create_manifest = None
    step_started = None
    step_finished = None
    step_failed = None
    StepStatus = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que as APIs de traceability necessárias estejam disponíveis para os testes.

    Esta função atua como um guardião de pré-condição para os testes de
    atualização incremental do Manifest, falhando explicitamente quando
    as funções canônicas de traceability ainda não foram implementadas
    ou não podem ser importadas.

    Decisões arquiteturais:
        - A falha ocorre de forma explícita e antecipada
        - A mensagem de erro orienta exatamente quais APIs faltam
        - Evita falsos negativos causados por ImportError silencioso

    Invariantes:
        - Se as APIs existem, a função não produz efeitos colaterais
        - Se alguma API estiver ausente, o teste falha imediatamente
        - Não tenta fallback ou implementação alternativa

    Limites explícitos:
        - Não valida comportamento das APIs
        - Não executa lógica de traceability
        - Não substitui testes funcionais das funções importadas

    Usado para garantir:
        - Clareza de falhas durante desenvolvimento incremental
        - Alinhamento entre testes e milestones implementadas
        - Feedback imediato quando contratos de traceability não são atendidos
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing traceability step update APIs. Implement:\n"
            "- create_manifest(...)\n"
            "- step_started(manifest, step_id, kind, ts)\n"
            "- step_finished(manifest, step_id, ts, result)\n"
            "- step_failed(manifest, step_id, ts, error)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_incremental_step_update_records_status_and_timestamps():
    """
    Verifica que atualizações incrementais de Step registram status, timestamps e metadados corretamente.

    Este teste valida o comportamento do Manifest ao receber uma sequência
    explícita de eventos de um Step (`step_started` → `step_finished`),
    garantindo que o estado final consolide corretamente:

    - status de execução
    - timestamps de início e fim
    - duração calculada
    - warnings, artefatos e métricas

    Decisões arquiteturais:
        - O Manifest é atualizado de forma incremental e determinística
        - Campos temporais são fornecidos externamente (não gerados implicitamente)
        - O resultado do Step é tratado como payload estruturado, não como evento implícito

    Invariantes:
        - `started_at` e `finished_at` são registrados quando fornecidos
        - `duration_ms` é derivado dos timestamps
        - Metadados do resultado (warnings, artifacts, metrics) são preservados
        - O status final reflete o valor reportado pelo Step

    Limites explícitos:
        - Não valida ordenação global de eventos
        - Não valida serialização em disco
        - Não valida semântica de métricas ou artefatos

    Usado para garantir:
        - Consistência temporal no Manifest
        - Integridade dos dados derivados de execução
        - Rastreabilidade forense fiel ao fluxo real de execução
    """
    _require_imports()
    started = datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc)

    m = create_manifest(
        run_id="run-001",
        started_at=started,
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )

    t0 = datetime(2026, 1, 16, 12, 0, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 16, 12, 0, 3, tzinfo=timezone.utc)

    step_started(m, step_id="ingest.load", kind="diagnostic", ts=t0)
    step_finished(
        m,
        step_id="ingest.load",
        ts=t1,
        result={
            "status": StepStatus.SUCCESS.value if hasattr(StepStatus, "SUCCESS") else "success",
            "summary": "ok",
            "warnings": ["w1"],
            "artifacts": {"df": "mem://df"},
            "metrics": {"rows": 10},
        },
    )

    data = m.to_dict() if hasattr(m, "to_dict") else m
    s = data["steps"]["ingest.load"]

    assert s["status"] in (StepStatus.SUCCESS.value if hasattr(StepStatus, "SUCCESS") else "success", "success")
    assert s["started_at"]
    assert s["finished_at"]
    assert s["duration_ms"] >= 0
    assert s["warnings"] == ["w1"]
    assert s["artifacts"]["df"] == "mem://df"
    assert s["metrics"]["rows"] == 10


def test_failed_step_is_recorded():
    """
    Verifica que a falha de um Step é registrada corretamente no Manifest.

    Este teste valida o comportamento incremental do sistema de traceability
    quando um Step transita para o estado de falha, garantindo que:
    - o Step exista no Manifest após `step_started`
    - a transição para FAILED seja registrada por `step_failed`
    - informações de erro sejam persistidas no estado do Step

    Decisões arquiteturais:
        - O Manifest não cria eventos implicitamente
        - Atualizações de Step ocorrem apenas via chamadas explícitas
          (`step_started`, `step_failed`)
        - A representação final do Manifest pode ser objeto ou dict
          (compatibilidade de API preservada)

    Invariantes:
        - A falha não remove o Step do Manifest
        - O status final do Step reflete FAILED
        - O campo de erro está presente quando ocorre falha

    Limites explícitos:
        - Não valida ordenação global de eventos
        - Não valida persistência em disco
        - Não valida conteúdo detalhado do erro além de sua presença

    Usado para garantir:
        - Rastreabilidade forense de falhas
        - Confiabilidade do estado final do Manifest
        - Consistência entre status de execução e registro histórico
    """
    _require_imports()
    m = create_manifest(
        run_id="run-002",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    t0 = datetime(2026, 1, 16, 12, 1, 0, tzinfo=timezone.utc)
    step_started(m, step_id="train.fit", kind="train", ts=t0)
    step_failed(m, step_id="train.fit", ts=t0, error="boom")

    data = m.to_dict() if hasattr(m, "to_dict") else m
    s = data["steps"]["train.fit"]
    assert s["status"] in ("failed", getattr(StepStatus, "FAILED", type("X",(object,),{"value":"failed"})) .value)
    assert "error" in s
