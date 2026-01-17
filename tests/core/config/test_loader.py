# tests/config/test_loader.py
"""
Testes do carregador de configuração (load_config).

Este módulo valida o comportamento do loader responsável por:
- carregar arquivos de configuração padrão (defaults)
- carregar arquivos de configuração local (override)
- validar estrutura mínima da configuração
- rejeitar formatos e estados inválidos

Os testes asseguram que:
- o arquivo defaults é obrigatório
- o arquivo local é opcional
- formatos não suportados são rejeitados
- estruturas inválidas são detectadas precocemente
- a configuração final é corretamente resolvida

Decisões arquiteturais:
    - A configuração é declarativa e baseada em arquivos
    - Defaults representam a base canônica do sistema
    - Configuração local atua apenas como override explícito
    - Erros estruturais são tratados como falhas fatais

Invariantes:
    - A configuração final é sempre um dicionário
    - Nenhuma configuração parcial é retornada em caso de erro
    - Overrides locais nunca silenciam erros de defaults ausentes

Limites explícitos:
    - Não valida hashing de configuração
    - Não valida semântica de domínio da configuração
    - Não valida integração com engine ou pipeline

Este módulo existe para garantir segurança,
previsibilidade e confiabilidade no carregamento de configuração.
"""

import pytest
from pathlib import Path

try:
    from atlas_dataflow.core.config.loader import load_config
    from atlas_dataflow.core.config.errors import (
        DefaultsNotFoundError,
        InvalidConfigRootTypeError,
        UnsupportedConfigFormatError,
    )
except Exception as e:  # noqa: BLE001
    load_config = None
    DefaultsNotFoundError = None
    InvalidConfigRootTypeError = None
    UnsupportedConfigFormatError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _require_imports():
    """
    Garante que o loader de configuração e suas exceções tipadas estejam disponíveis para os testes.

    Esta função atua como uma pré-condição explícita para os testes do
    carregamento de configuração, falhando imediatamente quando o módulo
    `loader` ou as exceções canônicas de `errors` não podem ser importadas.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando contratos do loader estão ausentes
        - Mensagem de erro descreve exatamente os módulos e responsabilidades esperadas
        - Evita falhas indiretas ou mensagens pouco informativas nos testes

    Invariantes:
        - Se os módulos existem, a função não produz efeitos colaterais
        - Se algum módulo está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida comportamento do `load_config`
        - Não executa parse, merge ou hashing
        - Não substitui testes funcionais do loader

    Usado para garantir:
        - Alinhamento entre testes e contratos do loader de configuração
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito das regras de carregamento de config
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing loader/errors modules. Implement:\n"
            "- src/atlas_dataflow/core/config/loader.py (load_config)\n"
            "- src/atlas_dataflow/core/config/errors.py (typed exceptions)\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_missing_defaults_raises(tmp_path: Path):
    """
    Verifica que a ausência do arquivo de configuração defaults é tratada como erro fatal.

    Este teste valida que a função `load_config` exige a presença do
    arquivo de configuração padrão (defaults) e falha explicitamente
    quando esse arquivo não existe.

    Decisões arquiteturais:
        - O arquivo defaults é obrigatório
        - A ausência do defaults invalida o carregamento da configuração
        - A falha ocorre antes de qualquer tentativa de merge ou parse

    Invariantes:
        - A ausência do arquivo defaults levanta exceção explícita
        - A exceção utilizada é específica (`DefaultsNotFoundError`)
        - Nenhuma configuração parcial é retornada

    Limites explícitos:
        - Não valida mensagens detalhadas da exceção
        - Não valida comportamento para paths inválidos adicionais
        - Não valida logs ou warnings associados

    Usado para garantir:
        - Contrato explícito de obrigatoriedade do defaults
        - Segurança na inicialização do sistema
        - Previsibilidade no carregamento de configuração
    """
    _require_imports()
    if DefaultsNotFoundError is None:
        pytest.fail("DefaultsNotFoundError must be defined in errors.py")
    missing = tmp_path / "defaults.yaml"
    with pytest.raises(DefaultsNotFoundError):
        load_config(defaults_path=str(missing), local_path=None)


def test_missing_local_is_ok(tmp_path: Path, project_like_config_defaults_yaml):
    """
    Verifica que a ausência do arquivo de configuração local não é tratada como erro.

    Este teste valida que a função `load_config` tolera a inexistência
    do arquivo de configuração local quando um caminho é fornecido,
    utilizando apenas a configuração defaults disponível.

    Decisões arquiteturais:
        - A configuração local é opcional
        - A ausência do arquivo local não invalida o carregamento
        - Defaults permanecem como fonte única quando o local não existe

    Invariantes:
        - Valores definidos no defaults são preservados integralmente
        - Nenhuma exceção é levantada pela ausência do arquivo local
        - A configuração resultante é válida e utilizável

    Limites explícitos:
        - Não valida comportamento quando o defaults está ausente
        - Não valida hashing da configuração
        - Não valida logs ou avisos sobre arquivo local inexistente

    Usado para garantir:
        - Robustez do loader em ambientes parciais
        - Experiência previsível para usuários finais
        - Alinhamento com o contrato de config opcional
    """
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")

    missing_local = tmp_path / "local.yaml"
    out = load_config(defaults_path=str(defaults), local_path=str(missing_local))
    assert out["engine"]["fail_fast"] is True
    assert out["engine"]["log_level"] == "INFO"
    assert out["steps"]["train"]["enabled"] is True


def test_load_defaults_only(tmp_path: Path, project_like_config_defaults_yaml):
    """
    Verifica o carregamento correto apenas da configuração defaults.

    Este teste valida que a função `load_config` é capaz de carregar
    corretamente a configuração padrão quando nenhum arquivo de
    configuração local é fornecido.

    Decisões arquiteturais:
        - O arquivo defaults é a fonte única de configuração quando
          `local_path` é None
        - Nenhum merge adicional é aplicado na ausência de overrides
        - A estrutura carregada reflete exatamente o conteúdo do defaults

    Invariantes:
        - Valores definidos no defaults são preservados integralmente
        - Nenhuma chave é removida ou alterada implicitamente
        - A configuração resultante é um dicionário válido e utilizável

    Limites explícitos:
        - Não valida merge com configuração local
        - Não valida hashing da configuração
        - Não valida validações semânticas avançadas

    Usado para garantir:
        - Funcionamento correto do loader em cenários mínimos
        - Previsibilidade quando apenas defaults são utilizados
        - Base segura para projetos sem overrides locais
    """
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")

    out = load_config(defaults_path=str(defaults), local_path=None)
    assert out["engine"]["fail_fast"] is True
    assert out["engine"]["log_level"] == "INFO"
    assert out["steps"]["ingest"]["enabled"] is True


def test_load_defaults_and_local(tmp_path: Path, project_like_config_defaults_yaml, project_like_config_local_yaml):
    """
    Verifica o carregamento e merge correto de configuração defaults + local.

    Este teste valida que a função `load_config`:
    - carrega corretamente a configuração padrão (defaults)
    - carrega corretamente a configuração local (override)
    - aplica a política canônica de deep-merge entre ambas

    O resultado final deve refletir:
    - valores sobrescritos pelo arquivo local
    - valores preservados do arquivo defaults quando não sobrescritos

    Decisões arquiteturais:
        - Defaults representam a base canônica da configuração
        - Configuração local atua apenas como override explícito
        - O merge segue estritamente a política definida em `deep_merge`

    Invariantes:
        - Overrides locais têm precedência sobre defaults
        - Chaves não sobrescritas permanecem inalteradas
        - A configuração final é um dicionário resolvido e utilizável

    Limites explícitos:
        - Não valida hashing da configuração resultante
        - Não valida leitura de múltiplos arquivos locais
        - Não valida validações semânticas avançadas

    Usado para garantir:
        - Correta resolução de configuração em cenários reais
        - Previsibilidade no uso combinado de defaults e overrides
        - Alinhamento com o contrato definido em docs/config.md
    """
    _require_imports()
    defaults = tmp_path / "defaults.yaml"
    local = tmp_path / "local.yaml"
    defaults.write_text(project_like_config_defaults_yaml, encoding="utf-8")
    local.write_text(project_like_config_local_yaml, encoding="utf-8")

    out = load_config(defaults_path=str(defaults), local_path=str(local))
    assert out["engine"]["log_level"] == "DEBUG"
    assert out["steps"]["train"]["enabled"] is False
    assert out["engine"]["fail_fast"] is True
    assert out["steps"]["ingest"]["enabled"] is True


def test_invalid_root_type_raises(tmp_path: Path):
    """
    Verifica que o loader rejeita configurações com tipo raiz inválido.

    Este teste valida que a função `load_config` exige que o conteúdo
    da configuração carregada possua um tipo raiz compatível (dicionário),
    rejeitando estruturas incompatíveis como listas ou escalares.

    Decisões arquiteturais:
        - A configuração deve ter um dicionário como raiz
        - Tipos raiz inválidos são tratados como erro estrutural
        - A validação ocorre imediatamente após o parse do arquivo

    Invariantes:
        - Configurações com raiz não-dict levantam exceção explícita
        - A exceção utilizada é específica (`InvalidConfigRootTypeError`)
        - Nenhuma configuração parcial é retornada

    Limites explícitos:
        - Não valida conteúdo semântico da configuração
        - Não valida merge com configuração local
        - Não valida hashing da configuração

    Usado para garantir:
        - Integridade estrutural da configuração carregada
        - Previsibilidade do loader
        - Alinhamento com o contrato definido em docs/config.md
    """
    _require_imports()
    if InvalidConfigRootTypeError is None:
        pytest.fail("InvalidConfigRootTypeError must be defined in errors.py")

    defaults = tmp_path / "defaults.yaml"
    defaults.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(InvalidConfigRootTypeError):
        load_config(defaults_path=str(defaults), local_path=None)


def test_unsupported_extension_raises(tmp_path: Path):
    """
    Verifica que o loader rejeita formatos de configuração não suportados.

    Este teste valida que a função `load_config` falha explicitamente
    ao receber um arquivo de configuração com extensão não suportada,
    garantindo que apenas formatos declarados (ex.: YAML) sejam aceitos.

    Decisões arquiteturais:
        - O formato da configuração é determinado pela extensão do arquivo
        - Formatos não suportados não são inferidos nem convertidos
        - A falha ocorre antes de qualquer tentativa de parse ou merge

    Invariantes:
        - Arquivos com extensão inválida levantam exceção explícita
        - A exceção utilizada é específica (`UnsupportedConfigFormatError`)
        - Nenhuma configuração parcial é retornada

    Limites explícitos:
        - Não valida mensagens detalhadas da exceção
        - Não valida comportamento para arquivos inexistentes
        - Não valida merge de configuração local

    Usado para garantir:
        - Segurança na leitura de configuração
        - Conformidade com o contrato de formatos suportados
        - Previsibilidade no processo de carregamento de config
    """
    _require_imports()
    if UnsupportedConfigFormatError is None:
        pytest.fail("UnsupportedConfigFormatError must be defined in errors.py")

    defaults = tmp_path / "defaults.toml"
    defaults.write_text("engine = { fail_fast = true }\n", encoding="utf-8")
    with pytest.raises(UnsupportedConfigFormatError):
        load_config(defaults_path=str(defaults), local_path=None)
