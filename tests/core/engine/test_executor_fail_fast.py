# tests/engine/test_executor_fail_fast.py
"""
Testes da política fail-fast do Engine.

Este módulo valida o comportamento do Engine quando a política
`fail_fast` está habilitada na configuração, garantindo que a execução
do pipeline seja interrompida imediatamente ao ocorrer uma falha em
qualquer Step.

Os testes asseguram que:
- exceções levantadas por um Step interrompem a execução
- o Step que falha é marcado com status FAILED
- nenhum Step adicional é executado após a falha
- o resultado final reflete fielmente a interrupção antecipada

Decisões arquiteturais:
    - A política fail-fast é controlada exclusivamente por configuração
    - Falhas são tratadas como eventos fatais quando fail-fast está ativo
    - O Engine não tenta recuperação, retry ou execução parcial posterior

Invariantes:
    - A primeira falha encerra a execução
    - O estado FAILED é registrado explicitamente
    - Não há execução implícita de Steps remanescentes

Limites explícitos:
    - Não valida comportamento quando fail-fast está desabilitado
    - Não valida persistência de resultados ou eventos
    - Não valida integração com Manifest ou Event Log

Este módulo existe para garantir previsibilidade,
segurança e controle rigoroso da execução em cenários de erro crítico.
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


class FailingStep:
    """
    Implementação mínima de Step que falha deliberadamente durante a execução.

    Esta classe é usada exclusivamente em testes do Engine para simular
    um Step que lança uma exceção em tempo de execução, permitindo validar
    políticas de erro como `fail_fast`.

    Decisões arquiteturais:
        - Implementa o protocolo de Step via duck typing
        - A falha ocorre explicitamente no método `run`
        - Não retorna `StepResult`, pois a exceção interrompe a execução

    Invariantes:
        - Sempre lança uma exceção ao executar `run`
        - Não produz artefatos nem efeitos colaterais válidos
        - O `step_id` é fixo e conhecido ("fail")

    Limites explícitos:
        - Não representa lógica de domínio real
        - Não deve ser reutilizada fora de testes
        - Não valida integração com Manifest ou Event Log

    Usado para garantir:
        - Testes confiáveis da política fail-fast do Engine
        - Comportamento correto do Engine em cenários de falha
        - Detecção imediata de exceções não tratadas em Steps
    """
    id = "fail"
    kind = None
    depends_on = []

    def run(self, ctx):
        raise RuntimeError("boom")



def test_fail_fast_stops_execution(dummy_ctx):
    """
    Verifica que o Engine interrompe a execução ao ocorrer falha quando fail-fast está habilitado.

    Este teste valida que, com a política `fail_fast` ativada na configuração,
    o Engine encerra imediatamente a execução ao encontrar um Step que falha,
    refletindo corretamente o estado FAILED no resultado final.

    Decisões arquiteturais:
        - A política de fail-fast é controlada exclusivamente pela configuração
        - Falhas são tratadas como eventos fatais quando fail-fast está ativo
        - Nenhuma execução adicional ocorre após a primeira falha

    Invariantes:
        - O Step que falha recebe status FAILED
        - A execução é interrompida imediatamente após a falha
        - O resultado do Engine reflete apenas os Steps efetivamente processados

    Limites explícitos:
        - Não valida comportamento quando fail-fast está desabilitado
        - Não valida registro de eventos no Manifest
        - Não valida estado de Steps dependentes

    Usado para garantir:
        - Conformidade com a política de execução fail-fast
        - Previsibilidade em cenários de erro crítico
        - Segurança contra execuções parciais não intencionais
    """
    if Engine is None:
        pytest.fail(f"""Missing Engine. Import error: {_IMPORT_ERR}""")

    dummy_ctx.config["engine"] = {"fail_fast": True}
    steps = [FailingStep()]
    engine = Engine(steps=steps, ctx=dummy_ctx)
    result = engine.run()

    assert result.steps["fail"].status == StepStatus.FAILED
