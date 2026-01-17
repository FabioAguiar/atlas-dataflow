# tests/conftest.py
"""
Fixtures compartilhados para testes do Atlas DataFlow.

Este módulo define fixtures reutilizáveis que fornecem:
- configurações mínimas e determinísticas
- contratos semânticos reduzidos
- contexto de execução controlado (RunContext)
- Steps dummy para testes estruturais

O objetivo destas fixtures é permitir testes do core
(config, pipeline, engine e traceability) sem depender de:
- filesystem
- variáveis de ambiente
- notebooks ou adapters de UI
- implementações reais de Steps

Decisões arquiteturais:
    - Fixtures são mantidas simples e explícitas
    - Dados retornados são determinísticos e isolados
    - Steps dummy utilizam duck typing em vez de herança
    - Imports do core são realizados de forma lazy para
      melhorar a clareza de erros durante falhas

Invariantes:
    - Nenhuma fixture executa pipeline real
    - Nenhuma fixture realiza I/O
    - Nenhuma fixture contém lógica de domínio
    - Todas as fixtures são seguras para execução em paralelo

Limites explícitos:
    - Não substituir testes de integração
    - Não validar semântica completa de config ou contract
    - Não conter lógica condicional complexa
    - Não acoplar testes a implementações concretas do projeto

Este módulo existe como infraestrutura de teste e não
como validação funcional do framework.
"""

import pytest
from datetime import datetime, timezone


# =====================================================
# Issue #2 — Config Loader fixtures
# =====================================================

@pytest.fixture
def project_like_config_defaults_yaml() -> str:
    """
    Fixture que fornece um YAML de configuração padrão (defaults) semelhante ao uso real do projeto.

    Este fixture representa o conteúdo típico de um arquivo `config.defaults.yaml`,
    servindo como base canônica sobre a qual configurações locais são aplicadas
    via deep-merge.

    Ele é utilizado para validar:
    - leitura de configuração padrão em formato YAML
    - comportamento correto do merge com overrides locais
    - preservação de valores não sobrescritos

    Decisões arquiteturais:
        - Configuração fornecida como string para evitar I/O
        - Estrutura alinhada ao contrato descrito em docs/config.md
        - Defaults sempre representam a base completa e estável

    Invariantes:
        - YAML sintaticamente válido
        - Contém configuração base suficiente para o engine
        - Pode ser combinado com config local sem ambiguidade

    Limites explícitos:
        - Não testa leitura de arquivo
        - Não testa validação semântica profunda
        - Não representa necessariamente configuração final de produção

    Usado por:
        - Testes do loader de config
        - Testes de deep-merge (defaults + local)
        - Testes de hashing de config resolvida

    Returns:
        str: Conteúdo YAML representando configuração padrão (defaults).
    """

    return """\
engine:
  fail_fast: true
  log_level: INFO
steps:
  ingest:
    enabled: true
  train:
    enabled: true
"""


@pytest.fixture
def project_like_config_local_yaml() -> str:
    """
    Fixture que fornece um YAML de configuração local semelhante ao uso real do projeto.

    Este fixture representa uma configuração *local* (override) em formato YAML,
    simulando o conteúdo típico de um arquivo `config.local.yaml` em projetos
    baseados no Atlas DataFlow.

    Ele é usado para testar:
    - carregamento de configuração a partir de string YAML
    - aplicação de overrides sobre defaults
    - políticas de deep-merge definidas pelo core de config

    Decisões arquiteturais:
        - A configuração é fornecida como string, não como arquivo físico
        - Estrutura alinhada com docs/config.md
        - Foco em comportamento de override, não em valores absolutos

    Invariantes:
        - YAML sintaticamente válido
        - Representa apenas overrides locais
        - Não contém configuração completa do projeto

    Limites explícitos:
        - Não testa acesso a filesystem
        - Não testa variáveis de ambiente
        - Não representa config final resolvida

    Usado por:
        - Testes do loader de config
        - Testes de deep-merge (defaults + local)
        - Testes de hashing pós-merge

    Returns:
        str: Conteúdo YAML representando configuração local de override.
    """

    return """\
engine:
  log_level: DEBUG
steps:
  train:
    enabled: false
"""


# =====================================================
# Issue #3 — Pipeline fixtures (Step + RunContext)
# =====================================================

@pytest.fixture
def dummy_config() -> dict:
    """
    Fixture que fornece uma configuração mínima e válida para testes.

    Esta configuração representa o menor subconjunto necessário do
    sistema de config para exercitar o engine e o pipeline durante
    testes, sem depender de arquivos YAML ou merge de múltiplas fontes.

    Decisões arquiteturais:
        - Config é representada como dicionário já resolvido
        - Apenas chaves efetivamente utilizadas pelo core são incluídas
        - Estrutura compatível com o schema definido em docs/config.md

    Invariantes:
        - Estrutura determinística e estável
        - `fail_fast` explicitamente habilitado
        - Não depende de filesystem, env vars ou defaults externos

    Limites explícitos:
        - Não testa loader de config
        - Não testa deep-merge
        - Não representa uma configuração real de produção

    Usado por:
        - Testes do engine (fail-fast, execução)
        - Testes de RunContext
        - Testes que exigem config já materializada

    Returns:
        dict: Configuração mínima e válida para execução de testes.
    """
    return {
        "engine": {"fail_fast": True, "log_level": "INFO"},
        "steps": {"ingest": {"enabled": True}},
    }


@pytest.fixture
def dummy_contract() -> dict:
    """
    Fixture que fornece um contrato semântico mínimo para testes.

    Este contrato representa a menor estrutura válida necessária para
    exercitar componentes do core que dependem de um contract, sem
    introduzir complexidade semântica ou variabilidade desnecessária.

    Decisões arquiteturais:
        - O contrato é representado como um dicionário simples
        - Estrutura compatível com o contrato canônico definido em docs/contract.md
        - Campos irrelevantes para M0 são omitidos intencionalmente

    Invariantes:
        - Estrutura estável e determinística
        - Tipos e nomes são coerentes entre features e target
        - Não depende de config ou estado externo

    Limites explícitos:
        - Não cobre validações semânticas avançadas
        - Não representa um caso de uso real
        - Não testa versionamento ou migração de contrato

    Usado por:
        - Testes de RunContext
        - Testes de engine e pipeline
        - Testes de manifest e rastreabilidade

    Returns:
        dict: Contrato semântico mínimo e válido para execução de testes.
    """
    return {
        "contract_version": "1.0",
        "problem": {"type": "classification"},
        "target": {"name": "y", "type": "binary"},
        "features": {"numeric": ["x1"], "categorical": []},
        "types": {"x1": "float", "y": "int"},
    }


@pytest.fixture
def dummy_ctx(dummy_config, dummy_contract):
    """
    Fixture que fornece um RunContext determinístico para testes.

    Este fixture cria uma instância de RunContext com valores fixos e
    controlados, permitindo que testes do core (pipeline, engine e
    traceability) sejam executados de forma reprodutível.

    Decisões arquiteturais:
        - O import de RunContext é feito de forma lazy para melhorar
          a legibilidade dos erros quando o core não está disponível
        - `run_id` e `created_at` são fixos para garantir determinismo
        - Config e contract são injetados explicitamente via fixtures

    Invariantes:
        - O contexto não depende de estado global
        - O timestamp é timezone-aware (UTC)
        - O RunContext inicia sem efeitos colaterais prévios

    Limites explícitos:
        - Não executa pipeline
        - Não persiste dados
        - Não valida semântica de config ou contract

    Usado por:
        - Testes de execução do engine
        - Testes de Steps e StepRegistry
        - Testes de Manifest e Event Log

    Args:
        dummy_config (dict): Configuração mínima válida para testes.
        dummy_contract (dict): Contrato semântico mínimo para testes.

    Returns:
        RunContext: Contexto de execução isolado e previsível para testes.
    """
    from atlas_dataflow.core.pipeline.context import RunContext

    return RunContext(
        run_id="run-test-001",
        created_at=datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc),
        config=dummy_config,
        contract=dummy_contract,
        meta={"source": "pytest"},
    )


@pytest.fixture
def DummyStep():
    """
    Fixture factory que fornece uma implementação mínima e duck-typed de um Step.

    Este fixture retorna uma *classe* (não uma instância) que simula um Step
    canônico do pipeline, implementando apenas o subconjunto estritamente
    necessário para testes estruturais e de engine.

    A implementação retornada:
    - respeita o protocolo de Step (duck typing, sem herança obrigatória)
    - expõe os atributos obrigatórios (`id`, `kind`, `depends_on`)
    - implementa `run(ctx)` com efeitos colaterais explícitos e determinísticos

    Decisões arquiteturais:
        - O Step é definido localmente para evitar acoplamento com Steps reais
        - O import de tipos é feito de forma lazy para falhar com mensagens
          mais informativas caso o core não esteja disponível
        - O comportamento é deliberadamente simples e previsível

    Invariantes:
        - Sempre retorna StepResult com status SUCCESS
        - Sempre registra um artefato no RunContext
        - Não executa I/O, não acessa filesystem, não depende de config

    Limites explícitos:
        - Não representa lógica de domínio real
        - Não valida regras semânticas de pipeline
        - Não deve ser estendido com comportamento adicional

    Usado por:
        - Testes de planner (ordenação, dependências)
        - Testes de engine (execução, status, transições)
        - Testes que exigem um Step válido sem custo cognitivo

    Returns:
        type: Classe _DummyStep que pode ser instanciada pelos testes.
    """
    from atlas_dataflow.core.pipeline.types import StepKind, StepStatus, StepResult

    class _DummyStep:
        def __init__(
            self,
            step_id: str = "ingest.load",
            kind: StepKind = StepKind.DIAGNOSTIC,
            depends_on=None,
        ):
            self.id = step_id
            self.kind = kind
            self.depends_on = depends_on or []

        def run(self, ctx):
            ctx.set_artifact(f"{self.id}.ok", True)
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="dummy ok",
                metrics={},
                warnings=[],
                artifacts={"ok": f"{self.id}.ok"},
                payload={"note": "dummy"},
            )

    return _DummyStep
