"""Erros canônicos do domínio de Contract (Atlas DataFlow).

O contrato interno é uma entrada semântica crítica do pipeline.
Falhas de carregamento/validação devem produzir erros explícitos e estáveis.
"""


class ContractError(Exception):
    """Erro base do domínio de contrato."""


class ContractPathMissingError(ContractError):
    """Config não possui `contract.path`."""


class ContractFileNotFoundError(ContractError):
    """Arquivo de contrato não existe no caminho informado."""


class UnsupportedContractFormatError(ContractError):
    """Formato de contrato não suportado (v1: YAML/JSON)."""


class ContractParseError(ContractError):
    """Falha ao parsear YAML/JSON."""


class ContractValidationError(ContractError):
    """Contrato não é estruturalmente válido segundo o schema canônico."""
