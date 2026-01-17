# src/atlas_dataflow/core/config/merge.py
"""
Utilitário canônico de deep-merge de configuração.

Este módulo implementa a política oficial de deep-merge utilizada pelo
Atlas DataFlow para resolver a configuração final a partir de uma
configuração base (defaults) e overrides explícitos.

Política de merge (v1):
    - dict → merge recursivo por chave
    - list → sobrescrita total (sem merge elemento a elemento)
    - escalar → sobrescrita direta
    - conflito de tipos → erro estrutural explícito

Princípios fundamentais:
    - O merge é determinístico e puramente funcional
    - Nenhum input é mutado durante o processo
    - Não existem heurísticas implícitas ou mágicas

Invariantes:
    - A mesma entrada sempre produz a mesma saída
    - Chaves não sobrescritas são preservadas
    - Conflitos estruturais interrompem o merge

Limites explícitos:
    - Não carrega arquivos de configuração
    - Não valida semântica de domínio
    - Não realiza coerção de tipos
    - Não interage com Engine ou Pipeline

Este módulo existe para garantir previsibilidade,
segurança estrutural e rastreabilidade na resolução de configuração.
"""

from copy import deepcopy
from typing import Any, Dict

from .errors import ConfigTypeConflictError


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Realiza um deep-merge determinístico entre dois dicionários de configuração.

    Esta função combina uma configuração base com um conjunto de overrides
    explícitos, produzindo uma nova estrutura resultante sem mutar
    nenhum dos inputs.

    Política de merge (v1):
        - dict + dict → merge recursivo por chave
        - list        → sobrescrita total (sem merge elemento a elemento)
        - escalar     → sobrescrita direta pelo override
        - conflito de tipos → erro estrutural explícito

    Decisões arquiteturais:
        - O merge é puramente funcional (inputs não são mutados)
        - Não existem heurísticas implícitas para listas
        - Conflitos estruturais são tratados como falha fatal
        - A política é simples, previsível e documentada

    Invariantes:
        - A estrutura retornada é sempre um novo dicionário
        - Chaves não presentes no override são preservadas da base
        - O mesmo par (base, override) sempre produz o mesmo resultado

    Limites explícitos:
        - Não valida semântica de domínio
        - Não resolve conflitos automaticamente
        - Não realiza coerção de tipos
        - Não carrega arquivos ou fontes externas

    Args:
        base (Dict[str, Any]): Configuração base (ex.: defaults).
        override (Dict[str, Any]): Overrides explícitos da configuração.

    Returns:
        Dict[str, Any]: Nova configuração resultante do deep-merge.

    Raises:
        ConfigTypeConflictError: Se ocorrer conflito de tipo entre base e override.

    Esta função existe para garantir previsibilidade,
    segurança estrutural e rastreabilidade na resolução de configuração.
    """

    if not isinstance(base, dict) or not isinstance(override, dict):
        raise ConfigTypeConflictError(
            f"Deep-merge requer dicts no nível raiz, recebido: "
            f"{type(base).__name__} vs {type(override).__name__}"
        )

    result: Dict[str, Any] = deepcopy(base)

    for key, override_value in override.items():
        if key not in result:
            result[key] = deepcopy(override_value)
            continue

        base_value = result[key]

        # dict -> merge recursivo
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = deep_merge(base_value, override_value)
            continue

        # list -> sobrescrita total
        if isinstance(override_value, list):
            result[key] = deepcopy(override_value)
            continue

        # conflito de tipo
        if type(base_value) is not type(override_value):
            raise ConfigTypeConflictError(
                f"Conflito de tipo na chave '{key}': "
                f"{type(base_value).__name__} vs {type(override_value).__name__}"
            )

        # escalar -> sobrescrita
        result[key] = deepcopy(override_value)

    return result
