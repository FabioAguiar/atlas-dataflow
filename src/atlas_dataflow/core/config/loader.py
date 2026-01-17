# src/atlas_dataflow/core/config/loader.py
"""
Loader canônico de configuração do Atlas DataFlow.

Este módulo é responsável por carregar, validar estruturalmente e resolver
a configuração efetiva utilizada na execução de pipelines do Atlas DataFlow.

A configuração é resolvida a partir de:
    - um arquivo de defaults (obrigatório)
    - um arquivo local de overrides (opcional)

Responsabilidades do módulo:
    - Carregar arquivos de configuração em YAML ou JSON
    - Validar requisitos estruturais mínimos (tipo raiz)
    - Resolver a configuração final via deep-merge determinístico
    - Garantir precedência explícita do override local sobre defaults

Princípios fundamentais:
    - Configuração é declarativa e explícita
    - Nenhuma heurística implícita é aplicada
    - Erros estruturais são tratados como falhas fatais
    - A mesma entrada sempre produz a mesma configuração final

Invariantes:
    - O arquivo de defaults é obrigatório
    - O resultado é sempre um dicionário puro (`dict`)
    - Overrides nunca mutam os defaults

Limites explícitos:
    - Não valida semântica de domínio
    - Não persiste configuração ou hash
    - Não interage com Engine ou Steps
    - Não depende de UI ou notebooks

Este módulo existe para garantir resolução previsível,
determinística e segura da configuração.
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
    """
    Carrega um arquivo de configuração e valida sua estrutura básica.

    Esta função é um utilitário interno responsável por ler um arquivo
    de configuração a partir do disco e validar requisitos estruturais
    mínimos antes que a configuração seja resolvida via deep-merge.

    Formatos suportados (v1):
        - YAML (.yaml, .yml)
        - JSON (.json)

    Decisões arquiteturais:
        - O arquivo deve existir no momento do carregamento
        - O conteúdo raiz deve ser um dicionário (`dict`)
        - Arquivos vazios são interpretados como dicionários vazios
        - Formatos não suportados geram erro explícito

    Invariantes:
        - O retorno é sempre um dicionário
        - Nenhuma mutação ocorre fora do escopo da função
        - Erros estruturais interrompem o carregamento

    Limites explícitos:
        - Não realiza merge de configuração
        - Não valida semântica de domínio
        - Não aplica defaults implícitos
        - Não calcula hash de configuração

    Args:
        path (Path): Caminho para o arquivo de configuração.

    Returns:
        Dict[str, Any]: Conteúdo do arquivo carregado como dicionário.

    Raises:
        DefaultsNotFoundError: Se o arquivo não existir.
        UnsupportedConfigFormatError: Se o formato do arquivo não for suportado.
        InvalidConfigRootTypeError: Se o conteúdo raiz não for um dicionário.

    Esta função existe para garantir carregamento seguro,
    previsível e estruturalmente válido de configurações.
    """
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
    Carrega e resolve a configuração efetiva do pipeline.

    Esta função é responsável por carregar a configuração base obrigatória
    (defaults) e, opcionalmente, um arquivo de configuração local,
    produzindo a configuração final resolvida do Atlas DataFlow.

    Política de resolução:
        - O arquivo de defaults é obrigatório
        - O arquivo local é opcional
        - Quando presente, o local sempre tem prioridade sobre defaults
        - A resolução utiliza `deep_merge` com política determinística

    Decisões arquiteturais:
        - A configuração final é um dicionário puro (`dict`)
        - Nenhum estado global é mantido
        - O hash da configuração é calculado para fins de rastreabilidade,
          mas não é persistido neste estágio
        - Erros estruturais são tratados como falhas fatais

    Invariantes:
        - A mesma entrada sempre produz a mesma configuração final
        - Defaults nunca são ignorados
        - Overrides locais nunca mutam os defaults

    Limites explícitos:
        - Não valida semântica de domínio
        - Não aplica defaults implícitos
        - Não persiste configuração ou hash
        - Não interage com Engine ou Pipeline

    Args:
        defaults_path (str): Caminho para o arquivo de configuração base.
        local_path (Optional[str]): Caminho opcional para overrides locais.

    Returns:
        Dict[str, Any]: Configuração final resolvida do pipeline.

    Raises:
        DefaultsNotFoundError: Se o arquivo de defaults não existir.
        UnsupportedConfigFormatError: Se o formato do arquivo não for suportado.
        InvalidConfigRootTypeError: Se o conteúdo não for um dicionário.
        ConfigTypeConflictError: Se ocorrer conflito estrutural durante o merge.

    Esta função existe para garantir resolução previsível,
    determinística e rastreável da configuração.
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
