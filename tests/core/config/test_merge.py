# tests/config/test_merge.py
"""
Testes da política de deep-merge de configuração.

Este módulo valida o comportamento da função `deep_merge`, responsável
por resolver a configuração final do Atlas DataFlow a partir de uma
configuração base (defaults) e um conjunto de overrides explícitos.

Os testes asseguram que:
- valores escalares são sobrescritos corretamente
- dicionários são mesclados de forma recursiva
- listas são sobrescritas integralmente
- conflitos de tipo são detectados e rejeitados explicitamente
- objetos de entrada não são mutados durante o merge

Decisões arquiteturais:
    - O merge é determinístico e puramente funcional
    - Não há heurísticas implícitas para listas ou tipos mistos
    - Conflitos estruturais são tratados como erro fatal
    - O comportamento é alinhado ao contrato definido em docs/config.md

Invariantes:
    - A estrutura resultante reflete exatamente a política declarada
    - Chaves não sobrescritas são preservadas
    - Nenhum merge parcial é produzido em caso de erro

Limites explícitos:
    - Não valida carregamento de arquivos YAML
    - Não valida hashing de configuração
    - Não valida integração com loader ou engine

Este módulo existe para garantir previsibilidade,
segurança estrutural e confiança na resolução de configuração.
"""

import pytest

try:
    from atlas_dataflow.core.config.merge import deep_merge
    from atlas_dataflow.core.config.errors import ConfigTypeConflictError
except Exception as e:  # noqa: BLE001
    deep_merge = None
    ConfigTypeConflictError = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def test_merge_simple_override():
    """
    Verifica o comportamento básico de override de valores escalares no deep-merge.

    Este teste valida que a função `deep_merge` substitui corretamente
    valores simples presentes no override, sem alterar chaves não
    sobrescritas e sem mutar os dicionários de entrada.

    Decisões arquiteturais:
        - Overrides de valores escalares substituem diretamente o valor base
        - O merge não altera os objetos de entrada (imutabilidade externa)
        - Apenas as chaves explicitamente presentes no override são afetadas

    Invariantes:
        - O valor sobrescrito reflete exatamente o override
        - Chaves não sobrescritas permanecem inalteradas
        - `base` e `override` não sofrem mutação

    Limites explícitos:
        - Não valida merge de estruturas aninhadas
        - Não valida conflitos de tipo
        - Não valida comportamento para valores None

    Usado para garantir:
        - Previsibilidade do merge em casos simples
        - Segurança contra efeitos colaterais
        - Base correta para merges mais complexos
    """

    _require_imports()
    base = {"a": 1, "b": 2}
    override = {"b": 99}
    out = deep_merge(base, override)
    assert out == {"a": 1, "b": 99}
    assert base == {"a": 1, "b": 2}
    assert override == {"b": 99}


def test_merge_nested_dict():
    """
    Verifica que dicionários aninhados são mesclados recursivamente no deep-merge.

    Este teste valida que a função `deep_merge` aplica merge recursivo
    quando ambos os valores associados a uma chave são dicionários,
    preservando chaves não sobrescritas e atualizando apenas as
    explicitamente definidas no override.

    Decisões arquiteturais:
        - Dicionários são mesclados de forma recursiva
        - Apenas as chaves presentes no override são atualizadas
        - Valores ausentes no override são preservados da base

    Invariantes:
        - Chaves não sobrescritas permanecem inalteradas
        - O valor sobrescrito reflete exatamente o override
        - A estrutura resultante mantém o mesmo shape do dicionário base

    Limites explícitos:
        - Não valida comportamento para conflitos de tipo
        - Não valida merge de listas
        - Não valida múltiplos níveis de override simultâneo

    Usado para garantir:
        - Comportamento previsível de merge hierárquico
        - Alinhamento com a política de configuração declarativa
        - Estabilidade da resolução de config no Atlas DataFlow
    """
    _require_imports()
    base = {"engine": {"fail_fast": True, "log_level": "INFO"}}
    override = {"engine": {"log_level": "DEBUG"}}
    out = deep_merge(base, override)
    assert out == {"engine": {"fail_fast": True, "log_level": "DEBUG"}}


def test_merge_list_override_total():
    """
    Verifica que listas são sobrescritas integralmente durante o deep-merge.

    Este teste valida a política explícita de merge para listas na função
    `deep_merge`, garantindo que valores do override substituem totalmente
    a lista existente na configuração base.

    Decisões arquiteturais:
        - Listas não são mescladas elemento a elemento
        - O override de lista é sempre total
        - Não há heurística implícita para merge de coleções ordenadas

    Invariantes:
        - A lista resultante corresponde exatamente à lista do override
        - Nenhum elemento da lista base é preservado implicitamente
        - A estrutura do dicionário é mantida fora da chave sobrescrita

    Limites explícitos:
        - Não valida merge de dicionários aninhados
        - Não valida comportamento para listas vazias ou None
        - Não valida conflitos de tipo fora do caso de lista

    Usado para garantir:
        - Previsibilidade no comportamento de override
        - Alinhamento com o contrato definido em docs/config.md
        - Ausência de merge implícito ou ambíguo de listas
    """
    _require_imports()
    base = {"steps": {"enabled": ["ingest", "train"]}}
    override = {"steps": {"enabled": ["ingest"]}}
    out = deep_merge(base, override)
    assert out == {"steps": {"enabled": ["ingest"]}}


def _require_imports():
    """
    Garante que os módulos de merge de config estejam disponíveis para os testes.

    Falha explicitamente com uma mensagem orientada quando `deep_merge`
    e/ou `ConfigTypeConflictError` não podem ser importados.
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing config merge modules. Implement:\n"
            "- src/atlas_dataflow/core/config/merge.py (deep_merge)\n"
            "- src/atlas_dataflow/core/config/errors.py (ConfigTypeConflictError)\n"
            f"Import error: {_IMPORT_ERR}"
        )



def test_merge_type_conflict_raises():
    """
    Verifica que conflitos de tipo durante o deep-merge são rejeitados explicitamente.

    Este teste valida que a função `deep_merge` detecta e rejeita
    conflitos estruturais quando uma mesma chave possui tipos
    incompatíveis entre a configuração base e o override.

    Decisões arquiteturais:
        - O deep-merge é estritamente tipado por chave
        - Um dicionário não pode ser sobrescrito por um tipo escalar
        - Conflitos de tipo são tratados como erro estrutural

    Invariantes:
        - A presença de tipos incompatíveis levanta exceção explícita
        - A exceção utilizada é específica (`ConfigTypeConflictError`)
        - Nenhum merge parcial é produzido em caso de conflito

    Limites explícitos:
        - Não valida mensagens detalhadas da exceção
        - Não valida conflitos em níveis múltiplos simultaneamente
        - Não valida comportamento para tipos compatíveis

    Usado para garantir:
        - Integridade estrutural da configuração
        - Previsibilidade do processo de merge
        - Segurança contra configurações ambíguas ou inválidas
    """
    _require_imports()
    if ConfigTypeConflictError is None:
        pytest.fail("ConfigTypeConflictError must be defined in errors.py")
    base = {"engine": {"fail_fast": True}}
    override = {"engine": "DEBUG"}  # dict vs str
    with pytest.raises(ConfigTypeConflictError):
        deep_merge(base, override)
