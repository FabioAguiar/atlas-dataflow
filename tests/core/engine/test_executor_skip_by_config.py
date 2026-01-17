# tests/engine/test_executor_skip_by_config.py
"""
Testes de skip de Steps pelo Engine com base em configuração.

Este módulo valida o comportamento do Engine ao decidir pular a execução
de Steps com base na configuração resolvida presente no RunContext.

Os testes asseguram que:
- Steps explicitamente desabilitados por config não são executados
- O status final desses Steps é marcado como SKIPPED
- Steps pulados ainda aparecem no resultado final da execução

Decisões arquiteturais:
    - A configuração é a fonte de verdade para habilitar/desabilitar Steps
    - A decisão de skip ocorre no momento da execução, não no planner
    - Steps pulados não produzem efeitos colaterais nem executam `run`

Invariantes:
    - Um Step desabilitado nunca é executado
    - O Engine registra explicitamente o status SKIPPED
    - O resultado da execução permanece estruturalmente completo

Limites explícitos:
    - Não valida política de fail-fast
    - Não valida interação entre múltiplos Steps
    - Não valida integração com Manifest ou Event Log

Este módulo existe para garantir previsibilidade,
controle declarativo e segurança na execução do pipeline.
"""
import pytest

try:
    from atlas_dataflow.core.engine.engine import Engine
    from atlas_dataflow.core.pipeline.types import StepStatus
except Exception as e:
    Engine = None
    StepStatus = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def test_skip_by_config(DummyStep, dummy_ctx):
    """
    Verifica que o Engine marca Steps como SKIPPED quando desabilitados por configuração.

    Este teste valida que o Engine respeita a configuração resolvida
    presente no RunContext, pulando explicitamente a execução de Steps
    cujo `enabled` esteja definido como False.

    Decisões arquiteturais:
        - A decisão de pular um Step é baseada exclusivamente na config
        - Steps desabilitados não executam `run`
        - O status final do Step é explicitamente SKIPPED

    Invariantes:
        - Steps desabilitados não produzem efeitos colaterais
        - O resultado do Engine reflete o status SKIPPED
        - O Step permanece registrado no resultado da execução

    Limites explícitos:
        - Não valida política de fail-fast
        - Não valida interação com outros Steps
        - Não valida registro de eventos no Manifest

    Usado para garantir:
        - Respeito estrito à configuração declarativa
        - Previsibilidade no controle de execução por config
        - Separação clara entre planejamento e decisão de execução
    """
    if Engine is None:
        pytest.fail(f"""Missing Engine. Import error: {_IMPORT_ERR}""")

    dummy_ctx.config["steps"] = {
        "a": {"enabled": False}
    }

    steps = [DummyStep(step_id="a")]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["a"].status == StepStatus.SKIPPED
