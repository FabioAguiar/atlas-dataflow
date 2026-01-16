"""
Atlas DataFlow — Deep Merge Utility

Implementa a política canônica de deep-merge para configurações:
- dict: merge recursivo
- list: sobrescrita total
- conflito de tipos: erro explícito
"""

from copy import deepcopy
from typing import Any, Dict

from .errors import ConfigTypeConflictError


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge profundo determinístico entre dois dicionários.

    Regras:
    - dict + dict -> merge recursivo
    - list -> sobrescrita total
    - conflito de tipos -> ConfigTypeConflictError
    - inputs nunca são mutados
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
