# src/atlas_dataflow/core/config/errors.py
"""
Exceções canônicas da camada de configuração do Atlas DataFlow.

Este módulo define a hierarquia oficial de exceções utilizadas durante
o carregamento, validação estrutural e resolução de configuração.

As exceções aqui definidas representam **violações arquiteturais
explícitas**, e não erros genéricos de execução.

Princípios fundamentais:
    - Exceções são tipadas e semânticas
    - Erros estruturais são tratados como falhas fatais
    - Mensagens de erro são claras e direcionadas ao usuário

Responsabilidades do módulo:
    - Expressar falhas estruturais de configuração
    - Diferenciar tipos de erro durante load e merge
    - Fornecer exceções reutilizáveis para core, APIs e testes

Invariantes:
    - Todas as exceções de configuração herdam de `ConfigError`
    - Nenhuma exceção representa erro de domínio ou execução de Step

Limites explícitos:
    - Não executa pipeline
    - Não realiza fallback ou recovery
    - Não depende de Engine, Pipeline ou UI

Este módulo existe para garantir clareza,
consistência e previsibilidade no tratamento de erros de configuração.
"""


class ConfigError(Exception):
    """
    Exceção base para erros relacionados à configuração do Atlas DataFlow.

    Todas as exceções levantadas durante carregamento, validação estrutural
    e resolução de configuração devem herdar desta classe.

    Esta hierarquia permite:
        - captura genérica de erros de configuração
        - distinção clara entre falhas estruturais e falhas de execução

    Limites explícitos:
        - Não representa erro de domínio
        - Não representa erro de execução do pipeline
    """


class DefaultsNotFoundError(ConfigError):
    """
    Exceção levantada quando o arquivo de configuração base (defaults)
    não é encontrado no caminho especificado.

    Decisões arquiteturais:
        - O arquivo de defaults é obrigatório
        - A ausência de defaults invalida a execução do pipeline

    Invariantes:
        - Sem defaults não existe configuração efetiva válida

    Limites explícitos:
        - Não tenta inferir ou criar defaults automaticamente
    """


class UnsupportedConfigFormatError(ConfigError):
    """
    Exceção levantada quando o formato do arquivo de configuração
    não é suportado pelo loader.

    Formatos suportados (v1):
        - YAML (.yaml, .yml)
        - JSON (.json)

    Decisões arquiteturais:
        - Apenas formatos explícitos são aceitos
        - Extensões desconhecidas são rejeitadas imediatamente

    Limites explícitos:
        - Não tenta inferir formato por conteúdo
        - Não converte automaticamente formatos
    """


class InvalidConfigRootTypeError(ConfigError):
    """
    Exceção levantada quando o conteúdo raiz da configuração
    não é um dicionário (`dict`).

    Decisões arquiteturais:
        - A configuração efetiva deve ser sempre um mapa chave-valor
        - Listas ou valores escalares no root são inválidos

    Invariantes:
        - O loader só opera sobre estruturas do tipo dicionário

    Limites explícitos:
        - Não tenta normalizar ou encapsular estruturas inválidas
    """


class ConfigTypeConflictError(ConfigError):
    """
    Exceção levantada quando ocorre conflito de tipos durante o deep-merge.

    Este erro indica que uma mesma chave possui tipos incompatíveis
    entre a configuração base e o override.

    Exemplo de conflito:
        - base:     {"engine": {"fail_fast": true}}
        - override: {"engine": "DEBUG"}

    Decisões arquiteturais:
        - O deep-merge é estritamente tipado por chave
        - Conflitos estruturais são tratados como erro fatal

    Invariantes:
        - Nenhum merge parcial é produzido em caso de conflito

    Limites explícitos:
        - Não realiza coerção ou conversão de tipos
        - Não tenta resolver conflitos automaticamente
    """
