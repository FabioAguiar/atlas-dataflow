# src/atlas_dataflow/core/run_context.py
"""
RunContext — Compat layer definitivo (M9-02)

📌 Problema
O projeto tinha dois caminhos de import para RunContext:

- `atlas_dataflow.core.pipeline.context.RunContext` ✅ (canônico; usado pelo Engine/E2E)
- `atlas_dataflow.core.run_context.RunContext`      ⚠️ (legado; usado em alguns testes)

Isso gerou divergências de assinatura, especialmente no suporte a `meta=...`
e no tipo de `created_at`, causando erros como:

    TypeError: RunContext.__init__() got an unexpected keyword argument 'meta'

✅ Decisão
Este módulo passa a ser **apenas uma camada de compatibilidade**, cujo objetivo é:
- expor uma API estável para imports legados
- garantir que **a implementação canônica** continue sendo a do pipeline
- aceitar o estilo antigo de construção (ex.: created_at como str) e normalizar

Fonte de verdade (canônico):
    `atlas_dataflow.core.pipeline.context.RunContext`
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union, overload

from atlas_dataflow.core.pipeline.context import RunContext as _CanonicalRunContext


# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------

CreatedAt = Union[datetime, str, None]


def _normalize_created_at(created_at: CreatedAt) -> datetime:
    """Normaliza `created_at` (compat).

    - datetime: usado diretamente
    - str: tenta parse ISO; aceita valores como "now"
    - None: usa now() UTC
    """
    if created_at is None:
        return datetime.now(timezone.utc)
    if isinstance(created_at, datetime):
        # Garante timezone (UTC) por segurança
        return created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    if isinstance(created_at, str):
        if created_at.strip().lower() in {"now", "utcnow"}:
            return datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(created_at)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            # Compat pragmática: em testes antigos, `created_at` era texto livre.
            return datetime.now(timezone.utc)
    # Fallback defensivo
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# API pública (compat)
# ---------------------------------------------------------------------------
@overload
def RunContext(
    *,
    run_id: str,
    created_at: CreatedAt = None,
    config: Dict[str, Any],
    contract: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> _CanonicalRunContext: ...


def RunContext(  # noqa: N802  (compat mantém nome público)
    *,
    run_id: str,
    created_at: CreatedAt = None,
    config: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> _CanonicalRunContext:
    """Factory compatível para construir o RunContext canônico.

    Este símbolo existe para manter compatibilidade com imports antigos como:
        `from atlas_dataflow.core.run_context import RunContext`

    Ele retorna **uma instância** do RunContext canônico do pipeline, após normalizar
    parâmetros legados (ex.: created_at como str).

    Observação:
    - `**_` ignora kwargs legados que não fazem mais parte do contrato público.
    """
    return _CanonicalRunContext(
        run_id=run_id,
        created_at=_normalize_created_at(created_at),
        config=config or {},
        contract=contract or {},
        meta=meta or {},
    )


# Para quem precisar do tipo/classe canônica (typing, isinstance, etc.)
RunContextClass = _CanonicalRunContext


__all__ = [
    "RunContext",
    "RunContextClass",
]
