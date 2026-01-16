"""
Atlas DataFlow — Config Hashing

Geração de hash determinístico do config efetivo para:
- rastreabilidade
- auditoria
- persistência em manifest
"""

import json
import hashlib
from typing import Dict, Any


def compute_config_hash(config: Dict[str, Any]) -> str:
    """
    Gera um hash SHA-256 determinístico a partir do config efetivo.

    Política:
    - serialização JSON canônica
    - chaves ordenadas
    - sem espaços supérfluos
    - UTF-8
    """

    if not isinstance(config, dict):
        raise TypeError(
            f"Config para hashing deve ser dict, recebido: {type(config).__name__}"
        )

    canonical_json = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
