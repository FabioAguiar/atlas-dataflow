
"""
Atlas DataFlow — Canonical Error Structures (v1)

Este módulo define o padrão canônico de erros do Atlas DataFlow.
Erros são considerados artefatos de domínio e fazem parte do contrato operacional
do sistema, devendo ser:

- explícitos
- serializáveis
- rastreáveis
- acionáveis

Nenhuma decisão implícita é permitida.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AtlasErrorPayload:
    """
    Payload canônico de erro do Atlas DataFlow.

    Campos:
    - type: código estável do erro (não é texto livre)
    - message: mensagem curta, humana e objetiva
    - details: dados estruturados relevantes para diagnóstico
    - hint: ação sugerida ao operador (onde corrigir)
    - decision_required: indica se o pipeline está bloqueado aguardando decisão humana
    """

    type: str
    message: str
    details: Dict[str, Any]
    hint: Optional[str] = None
    decision_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Retorna representação serializável do erro."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Catálogo canônico de tipos de erro (v1)
# ---------------------------------------------------------------------------

# Contrato / Conformidade
CONTRACT_MISSING_COLUMN = "CONTRACT_MISSING_COLUMN"
CONTRACT_EXTRA_COLUMN = "CONTRACT_EXTRA_COLUMN"
CONTRACT_INVALID_DTYPE = "CONTRACT_INVALID_DTYPE"
CONTRACT_CATEGORY_OUT_OF_DOMAIN = "CONTRACT_CATEGORY_OUT_OF_DOMAIN"

# Artefatos obrigatórios
PREPROCESS_NOT_FOUND = "PREPROCESS_NOT_FOUND"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"

# Engine / Execução
ENGINE_EXECUTION_ERROR = "ENGINE_EXECUTION_ERROR"
ENGINE_CONFIGURATION_ERROR = "ENGINE_CONFIGURATION_ERROR"


# ---------------------------------------------------------------------------
# Helpers de fábrica (opcional, mas recomendado)
# ---------------------------------------------------------------------------

def contract_missing_column(
    *,
    column: str,
    location: str = "dataset",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_MISSING_COLUMN,
        message="Coluna obrigatória ausente",
        details={
            "column": column,
            "location": location,
        },
        hint="Declare a coluna no contrato ou ajuste o dataset",
        decision_required=True,
    )


def contract_extra_column(
    *,
    column: str,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_EXTRA_COLUMN,
        message="Coluna não declarada no contrato",
        details={
            "column": column,
        },
        hint="Declare a coluna no contrato ou remova do dataset",
        decision_required=True,
    )


def contract_invalid_dtype(
    *,
    column: str,
    expected: str,
    received: str,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_INVALID_DTYPE,
        message="Tipo de dado incompatível com o contrato",
        details={
            "column": column,
            "expected": expected,
            "received": received,
        },
        hint="Ajuste o tipo no dataset ou no contrato",
        decision_required=True,
    )


def contract_category_out_of_domain(
    *,
    column: str,
    value: Any,
    allowed: list[Any],
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_CATEGORY_OUT_OF_DOMAIN,
        message="Valor categórico fora do domínio permitido",
        details={
            "column": column,
            "value": value,
            "allowed": allowed,
        },
        hint="Atualize o domínio permitido no contrato ou corrija o dataset",
        decision_required=True,
    )


def preprocess_not_found(
    *,
    expected_path: Optional[str] = None,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=PREPROCESS_NOT_FOUND,
        message="Preprocess não encontrado para a etapa dependente",
        details={
            "expected_path": expected_path,
        },
        hint="Execute a etapa de preprocess antes do treino",
        decision_required=False,
    )


def model_not_found(
    *,
    expected_path: Optional[str] = None,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=MODEL_NOT_FOUND,
        message="Modelo treinado não encontrado",
        details={
            "expected_path": expected_path,
        },
        hint="Execute a etapa de treino antes da avaliação ou export",
        decision_required=False,
    )


def manifest_not_found(
    *,
    expected_path: Optional[str] = None,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=MANIFEST_NOT_FOUND,
        message="Manifest não encontrado",
        details={
            "expected_path": expected_path,
        },
        hint="Verifique se o run foi inicializado corretamente",
        decision_required=False,
    )
