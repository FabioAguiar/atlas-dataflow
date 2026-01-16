"""
Atlas DataFlow — Config Loader

Loader canônico de configuração baseado em:
- defaults.yaml (obrigatório)
- local.yaml (opcional, override)

Responsabilidades:
- carregar arquivos YAML/JSON
- validar tipos básicos
- aplicar deep-merge determinístico
- retornar config efetivo
"""

from pathlib import Path
from typing import Any, Dict, Optional
import json

import yaml  # PyYAML

from .merge import deep_merge
from .hashing import compute_config_hash
from .errors import (
    DefaultsNotFoundError,
    InvalidConfigRootTypeError,
    UnsupportedConfigFormatError,
)


def _load_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise DefaultsNotFoundError(f"Arquivo de defaults não encontrado: {path}")

    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    elif suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

    else:
        raise UnsupportedConfigFormatError(f"Formato não suportado: {path.suffix}")

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise InvalidConfigRootTypeError(
            f"Config root deve ser dict, recebido: {type(data).__name__}"
        )

    return data


def load_config(
    *,
    defaults_path: str,
    local_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Carrega e resolve o config efetivo do pipeline.

    Regras:
    - defaults é obrigatório
    - local é opcional
    - prioridade sempre do local sobre defaults
    """

    defaults_file = Path(defaults_path)
    defaults = _load_file(defaults_file)

    effective = defaults

    if local_path is not None:
        local_file = Path(local_path)
        if local_file.exists():
            local = _load_file(local_file)
            effective = deep_merge(defaults, local)

    # hash calculado mas não persistido aqui (manifest é responsabilidade futura)
    _ = compute_config_hash(effective)

    return effective
