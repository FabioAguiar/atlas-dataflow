# src/atlas_dataflow/core/config/hashing.py
"""
Hashing canônico de configuração do Atlas DataFlow.

Este módulo implementa a geração de hash determinístico da configuração
efetiva utilizada na execução de pipelines do Atlas DataFlow.

O hash gerado representa a **identidade estrutural** da configuração e é
utilizado para:
    - rastreabilidade de execuções
    - auditoria forense
    - associação com Manifest e Event Log

Princípios fundamentais:
    - Hashing determinístico e reprodutível
    - Independente da ordem original das chaves
    - Baseado em serialização JSON canônica
    - Algoritmo criptográfico estável (SHA-256)

Decisões arquiteturais:
    - Apenas a configuração efetiva participa do hash
    - Nenhuma informação de runtime é incluída
    - O hash não é persistido neste módulo

Invariantes:
    - Configurações estruturalmente equivalentes produzem o mesmo hash
    - O valor gerado é sempre uma string hexadecimal de 64 caracteres

Limites explícitos:
    - Não valida semântica de domínio
    - Não carrega ou resolve configuração
    - Não registra eventos ou persiste Manifest
    - Não depende de Engine ou Pipeline

Este módulo existe para garantir rastreabilidade,
auditoria e reprodutibilidade das execuções.
"""


import json
import hashlib
from typing import Dict, Any


def compute_config_hash(config: Dict[str, Any]) -> str:
    """
    Gera um hash determinístico da configuração efetiva do pipeline.

    Esta função calcula um hash SHA-256 a partir da configuração resolvida,
    utilizando uma serialização JSON canônica para garantir estabilidade
    e reprodutibilidade.

    Política de hashing (v1):
        - Serialização JSON canônica
        - Ordenação estável de chaves
        - Separadores compactos (sem espaços supérfluos)
        - Codificação UTF-8
        - Algoritmo SHA-256

    Decisões arquiteturais:
        - O hash representa a identidade estrutural da configuração
        - A mesma configuração sempre produz o mesmo hash
        - O hash é independente da ordem original das chaves
        - O resultado é adequado para uso em Manifest e auditoria

    Invariantes:
        - O valor retornado é uma string hexadecimal de 64 caracteres
        - Configurações estruturalmente equivalentes produzem o mesmo hash
        - Nenhuma mutação ocorre sobre o input

    Limites explícitos:
        - Não valida semântica de domínio
        - Não persiste o hash
        - Não inclui informações de ambiente ou runtime
        - Não depende de estado externo

    Args:
        config (Dict[str, Any]): Configuração efetiva do pipeline.

    Returns:
        str: Hash SHA-256 hexadecimal da configuração.

    Raises:
        TypeError: Se o objeto fornecido não for um dicionário.

    Esta função existe para garantir rastreabilidade,
    auditoria e reprodutibilidade de execuções.
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
