# tests/traceability/test_manifest_round_trip.py
"""
Testes de persistência e round-trip do Manifest (traceability).

Este módulo valida que o Manifest do Atlas DataFlow pode ser
serializado, persistido e recarregado sem perda estrutural,
garantindo rastreabilidade forense entre execuções.

Os testes asseguram que:
- o Manifest pode ser salvo em formato JSON
- a estrutura semântica principal é preservada após reload
- campos críticos de identificação e inputs permanecem intactos
- o Manifest carregado é estruturalmente utilizável

Decisões arquiteturais:
    - A persistência do Manifest é explícita e controlada
    - O formato de armazenamento é JSON determinístico
    - APIs de persistência são separadas da lógica de execução
    - O Manifest pode existir como objeto ou representação dict

Invariantes:
    - `run_id` é preservado entre save/load
    - `config_hash` e `contract_hash` não sofrem mutação
    - `events` é sempre uma lista após reload
    - `steps` é sempre um dicionário após reload

Limites explícitos:
    - Não valida compatibilidade entre versões diferentes de schema
    - Não valida ordenação detalhada de eventos
    - Não valida integração com engine ou pipeline

Este módulo existe para garantir que a rastreabilidade
forense do Atlas DataFlow sobreviva à persistência em disco.
"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

try:
    from atlas_dataflow.core.traceability.manifest import (
        create_manifest,
        save_manifest,
        load_manifest,
    )
except Exception as e:
    create_manifest = None
    save_manifest = None
    load_manifest = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que as APIs de persistência do Manifest estejam disponíveis para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    round-trip do Manifest, falhando imediatamente quando as funções
    canônicas de persistência (`save_manifest`, `load_manifest`) não
    estão implementadas ou não podem ser importadas.

    Decisões arquiteturais:
        - Falha antecipada e explícita em caso de APIs ausentes
        - Mensagem de erro orienta exatamente quais contratos precisam
          ser implementados
        - Evita que testes falhem de forma indireta ou ambígua

    Invariantes:
        - Se as APIs existem, a função não produz efeitos colaterais
        - Se alguma API estiver ausente, o teste falha imediatamente
        - Não realiza fallback nem lógica alternativa

    Limites explícitos:
        - Não valida comportamento das APIs
        - Não executa serialização ou desserialização
        - Não substitui testes funcionais de persistência

    Usado para garantir:
        - Alinhamento entre testes e Issue de persistência do Manifest
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito do contrato de traceability
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing manifest persistence APIs. Implement:\n"
            "- save_manifest(manifest, path: Path) -> None  (JSON)\n"
            "- load_manifest(path: Path) -> manifest\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_round_trip_save_load(tmp_path: Path):
    """
    Verifica a integridade do round-trip de persistência do Manifest.

    Este teste valida que um Manifest pode ser:
    - serializado em JSON via `save_manifest`
    - persistido em disco
    - recarregado via `load_manifest`
    sem perda estrutural ou corrupção de dados essenciais.

    Decisões arquiteturais:
        - A persistência do Manifest é determinística
        - A representação em disco é JSON canônico
        - A API de load preserva a estrutura semântica do Manifest
          (run, inputs, events, steps)

    Invariantes:
        - `run_id` permanece idêntico após save/load
        - `config_hash` é preservado integralmente
        - `events` é sempre uma lista
        - `steps` é sempre um dicionário

    Limites explícitos:
        - Não valida conteúdo detalhado dos events
        - Não valida ordenação interna além da estrutura
        - Não valida compatibilidade entre versões diferentes de schema

    Usado para garantir:
        - Confiabilidade da persistência forense
        - Segurança contra regressões em serialização
        - Reprodutibilidade de execuções a partir de Manifest salvo
    """
    _require_imports()
    m = create_manifest(
        run_id="run-004",
        started_at=datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        atlas_version="0.0.0",
        config_hash="c" * 64,
        contract_hash="d" * 64,
    )
    out = tmp_path / "manifest.json"
    save_manifest(m, out)

    assert out.exists()
    loaded = load_manifest(out)

    d1 = m.to_dict() if hasattr(m, "to_dict") else m
    d2 = loaded.to_dict() if hasattr(loaded, "to_dict") else loaded

    assert d2["run"]["run_id"] == d1["run"]["run_id"]
    assert d2["inputs"]["config_hash"] == d1["inputs"]["config_hash"]
    assert isinstance(d2["events"], list)
    assert isinstance(d2["steps"], dict)
