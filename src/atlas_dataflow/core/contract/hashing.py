"""Hashing canônico do Internal Contract.

O hashing do contrato serve para:
- rastreabilidade no Manifest/EventLog
- detecção de divergência entre execuções

Decisão: o hash é calculado a partir de JSON canônico (sort_keys, separators).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def compute_contract_hash(contract: Dict[str, Any]) -> str:
    """Computa SHA-256 do contrato em formato canônico."""
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
