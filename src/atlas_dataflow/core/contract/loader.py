"""Loader canônico de contrato (YAML/JSON).

Alinhado a `docs/spec/contract.load.v1.md`.

Notas:
- YAML é preferencial, JSON é alternativo.
- O formato é inferido pela extensão do arquivo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .errors import (
    ContractFileNotFoundError,
    ContractParseError,
    ContractPathMissingError,
    UnsupportedContractFormatError,
)


def load_contract(*, path: Optional[str]) -> Dict[str, Any]:
    """Carrega contrato a partir de YAML/JSON.

    Args:
        path: caminho para arquivo do contrato.

    Raises:
        ContractPathMissingError: se path estiver ausente.
        ContractFileNotFoundError: se arquivo não existir.
        UnsupportedContractFormatError: se extensão não suportada.
        ContractParseError: se parsing falhar.
    """
    if not path or not str(path).strip():
        raise ContractPathMissingError("config must define contract.path")

    p = Path(path)
    if not p.exists():
        raise ContractFileNotFoundError(f"contract file not found: {p}")

    suffix = p.suffix.lower()
    raw = p.read_text(encoding="utf-8")

    try:
        if suffix in {".yml", ".yaml"}:
            data = yaml.safe_load(raw)
        elif suffix == ".json":
            data = json.loads(raw)
        else:
            raise UnsupportedContractFormatError(f"unsupported contract format: {suffix}")
    except UnsupportedContractFormatError:
        raise
    except Exception as e:
        raise ContractParseError(str(e) or "failed to parse contract") from e

    if data is None:
        # YAML vazio -> None
        raise ContractParseError("contract file is empty")

    if not isinstance(data, dict):
        raise ContractParseError("contract root must be a mapping/dict")

    return data
