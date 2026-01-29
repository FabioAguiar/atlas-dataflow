
"""
Atlas DataFlow — Canonical Exceptions (v1)

Este módulo define exceções tipadas internas do Atlas DataFlow.

Objetivo:
- Permitir que Steps/Engine levantem exceções semânticas tipadas
- Facilitar o mapeamento determinístico para AtlasErrorPayload
- Evitar ValueError/RuntimeError genéricos em guardrails críticos

Regras:
- Não contém lógica de domínio específica de dataset.
- Exceções devem carregar apenas dados estruturados (serializáveis).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AtlasException(Exception):
    """Base class para exceções internas do Atlas.

    Importante:
    - Sempre carregar dados estruturados em `details`
    - Não embedar stack trace em payloads de erro
    - Mensagem deve ser curta e humana
    """

    message: str
    details: Dict[str, Any]
    hint: Optional[str] = None
    decision_required: bool = False

    def __str__(self) -> str:  # pragma: no cover
        return self.message


# ---------------------------------------------------------------------------
# Contrato / Conformidade
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContractMissingColumn(AtlasException):
    """Coluna requerida pelo contrato não existe no dataset."""


@dataclass(frozen=True)
class ContractExtraColumn(AtlasException):
    """Coluna existe no dataset, mas não está declarada no contrato."""


@dataclass(frozen=True)
class ContractInvalidDtype(AtlasException):
    """Tipo de dado no dataset não bate com o dtype esperado pelo contrato."""


@dataclass(frozen=True)
class ContractCategoryOutOfDomain(AtlasException):
    """Valor categórico está fora do domínio declarado no contrato."""


# ---------------------------------------------------------------------------
# Artefatos obrigatórios
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PreprocessNotFound(AtlasException):
    """Preprocess obrigatório não foi encontrado."""


@dataclass(frozen=True)
class ModelNotFound(AtlasException):
    """Modelo obrigatório não foi encontrado."""


@dataclass(frozen=True)
class ManifestNotFound(AtlasException):
    """Manifest obrigatório não foi encontrado."""


# ---------------------------------------------------------------------------
# Engine / Configuração
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineConfigurationError(AtlasException):
    """Configuração inválida ou inconsistente para execução."""


@dataclass(frozen=True)
class EngineExecutionError(AtlasException):
    """Erro inesperado durante execução do Engine (encapsulado)."""
