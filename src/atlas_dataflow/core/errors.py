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

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, List


# ---------------------------------------------------------------------------
# Payload canônico
# ---------------------------------------------------------------------------

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
      (padrão “decision required”: sem auto-correção, sem fallback silencioso).
    """

    type: str
    message: str
    details: Dict[str, Any]
    hint: Optional[str] = None
    decision_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Retorna representação serializável do erro."""
        # asdict garante serialização de dataclass -> dict
        # (o chamador deve garantir que details seja serializável)
        return asdict(self)


# ---------------------------------------------------------------------------
# Catálogo canônico de tipos de erro (v1)
# ---------------------------------------------------------------------------

# Contrato / Conformidade
CONTRACT_MISSING_COLUMN = "CONTRACT_MISSING_COLUMN"
CONTRACT_EXTRA_COLUMN = "CONTRACT_EXTRA_COLUMN"
CONTRACT_INVALID_DTYPE = "CONTRACT_INVALID_DTYPE"
CONTRACT_CATEGORY_OUT_OF_DOMAIN = "CONTRACT_CATEGORY_OUT_OF_DOMAIN"
CONTRACT_DECISION_REQUIRED = "CONTRACT_DECISION_REQUIRED"

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
    missing_columns: List[str],
    step: Optional[str] = None,
    contract_section: str = "features.required",
    hint: str = "Declare a coluna ausente no contrato ou ajuste o dataset para conter a feature obrigatória.",
    decision_required: bool = False,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_MISSING_COLUMN,
        message="Coluna obrigatória ausente no dataset",
        details={
            "missing_columns": missing_columns,
            "step": step,
            "contract_section": contract_section,
        },
        hint=hint,
        decision_required=decision_required,
    )


def contract_extra_column(
    *,
    extra_columns: List[str],
    step: Optional[str] = None,
    contract_section: str = "features.forbidden",
    hint: str = "Remova a coluna extra do dataset ou ajuste o contrato para permitir explicitamente essa feature.",
    decision_required: bool = False,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_EXTRA_COLUMN,
        message="Coluna não permitida presente no dataset",
        details={
            "extra_columns": extra_columns,
            "step": step,
            "contract_section": contract_section,
        },
        hint=hint,
        decision_required=decision_required,
    )


def contract_invalid_dtype(
    *,
    column: str,
    expected_dtype: str,
    actual_dtype: str,
    step: Optional[str] = None,
    contract_section: str = "features.dtypes",
    hint: str = "Ajuste o tipo da coluna no dataset ou atualize o contrato para refletir o dtype correto.",
    decision_required: bool = False,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_INVALID_DTYPE,
        message="Tipo de dado incompatível com o contrato",
        details={
            "column": column,
            "expected_dtype": expected_dtype,
            "actual_dtype": actual_dtype,
            "step": step,
            "contract_section": contract_section,
        },
        hint=hint,
        decision_required=decision_required,
    )


def contract_category_out_of_domain(
    *,
    column: str,
    invalid_categories: List[Any],
    allowed_categories: List[Any],
    step: Optional[str] = None,
    contract_section: str = "features.domain",
    hint: str = "Ajuste os valores categóricos no dataset ou atualize o domínio permitido no contrato.",
    decision_required: bool = False,
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_CATEGORY_OUT_OF_DOMAIN,
        message="Categoria fora do domínio permitido pelo contrato",
        details={
            "column": column,
            "invalid_categories": invalid_categories,
            "allowed_categories": allowed_categories,
            "step": step,
            "contract_section": contract_section,
        },
        hint=hint,
        decision_required=decision_required,
    )


def contract_decision_required(
    *,
    conflict: str,
    options: List[str],
    step: Optional[str] = None,
    contract_section: Optional[str] = None,
    hint: str = "Declare explicitamente a decisão no contrato ou configuração indicada antes de reexecutar o pipeline.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=CONTRACT_DECISION_REQUIRED,
        message="Conflito de contrato requer decisão explícita",
        details={
            "conflict": conflict,
            "options": options,
            "step": step,
            "contract_section": contract_section,
        },
        hint=hint,
        decision_required=True,
    )


def preprocess_not_found(
    *,
    expected_artifact: str = "preprocess.pipeline",
    step: Optional[str] = None,
    required_by: Optional[str] = None,
    artifact_namespace: str = "artifacts",
    hint: str = "Execute o Step de preprocessamento correspondente ou ajuste o pipeline para não depender desse artefato.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=PREPROCESS_NOT_FOUND,
        message="Artefato de preprocessamento não encontrado",
        details={
            "expected_artifact": expected_artifact,
            "step": step,
            "required_by": required_by,
            "artifact_namespace": artifact_namespace,
        },
        hint=hint,
        decision_required=False,
    )


def model_not_found(
    *,
    expected_artifact: str = "model.best_estimator",
    step: Optional[str] = None,
    required_by: Optional[str] = None,
    artifact_namespace: str = "artifacts",
    hint: str = "Execute o Step de treino/seleção de modelo ou ajuste o pipeline para produzir o artefato esperado antes da inferência.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=MODEL_NOT_FOUND,
        message="Modelo treinado não encontrado para inferência",
        details={
            "expected_artifact": expected_artifact,
            "step": step,
            "required_by": required_by,
            "artifact_namespace": artifact_namespace,
        },
        hint=hint,
        decision_required=False,
    )


def manifest_not_found(
    *,
    expected_artifact: str = "manifest",
    step: Optional[str] = None,
    required_by: Optional[str] = None,
    artifact_namespace: str = "run_dir",
    hint: str = "Garanta que o pipeline foi inicializado corretamente e que o manifest foi gerado antes da execução deste Step.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=MANIFEST_NOT_FOUND,
        message="Manifest canônico não encontrado para execução",
        details={
            "expected_artifact": expected_artifact,
            "step": step,
            "required_by": required_by,
            "artifact_namespace": artifact_namespace,
        },
        hint=hint,
        decision_required=False,
    )


def engine_execution_error(
    *,
    step: Optional[str] = None,
    exc_type: Optional[str] = None,
    exc_message: Optional[str] = None,
    hint: str = "Verifique o stacktrace e os artefatos do run para diagnosticar a falha. Nenhum fallback é aplicado automaticamente.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=ENGINE_EXECUTION_ERROR,
        message="Falha inesperada durante a execução do pipeline",
        details={
            "step": step,
            "exc_type": exc_type,
            "exc_message": exc_message,
        },
        hint=hint,
        decision_required=False,
    )


def engine_configuration_error(
    *,
    message: str = "Configuração inválida para execução do pipeline",
    details: Optional[Dict[str, Any]] = None,
    hint: str = "Revise a configuração do run/steps e declare explicitamente as opções necessárias antes de reexecutar.",
) -> AtlasErrorPayload:
    return AtlasErrorPayload(
        type=ENGINE_CONFIGURATION_ERROR,
        message=message,
        details=details or {},
        hint=hint,
        decision_required=False,
    )
