"""
Step: transform.apply_defaults
=============================

Este Step implementa a aplicação **controlada e auditável de defaults**
conforme declarado explicitamente no **Internal Contract v1**.

Contexto de execução:
---------------------
Este Step deve ser executado **após**:
- contract.load
- contract.conformity_report
- transform.cast_types_safe

Responsabilidade:
-----------------
- Aplicar defaults **somente** quando declarados no contrato
- Preencher apenas valores nulos (null / NaN)
- Criar colunas ausentes **apenas** se explicitamente permitido (required: false)
- Nunca sobrescrever valores válidos
- Nunca inferir defaults
- Nunca realizar imputação estatística
- Produzir auditoria clara, serializável e rastreável

Shape real do contrato (Internal Contract v1):
----------------------------------------------
O contrato carregado no RunContext (`ctx.contract`) é um dict, contendo:

- features: list[dict]  (cada item possui ao menos: {name: str, required: bool, ...})
- defaults: dict[str, any]  (mapeamento coluna -> default_value)

Exemplo:
    contract = {
        "features": [
            {"name": "age", "required": True,  "dtype": "int", ...},
            {"name": "vip", "required": False, "dtype": "bool", ...},
        ],
        "defaults": {
            "vip": False,
            "age": 18
        }
    }

Auditoria:
----------
Para cada coluna afetada, deve ser registrado no RunContext um impacto no formato:

impact = {
    "<column_name>": {
        "default_value": <any>,
        "values_filled": <int>,
        "column_created": <bool>
    }
}

Regras:
- Auditoria é obrigatória quando houver mutação
- Nenhuma mutação pode ocorrer sem auditoria
- Impacto deve refletir **exatamente** o que foi alterado

Invariantes do domínio:
----------------------
- Defaults são decisões contratuais, não heurísticas
- Nenhuma correção silenciosa é permitida
- Qualquer default implícito viola o Atlas DataFlow

Spec de referência:
-------------------
docs/spec/transform.apply_defaults.v1.md
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


class TransformApplyDefaultsStep(Step):
    """
    Step canônico de transformação responsável por aplicar defaults
    explicitamente declarados no contrato, de forma controlada e auditável.
    """

    kind = StepKind.TRANSFORM
    step_id = "transform.apply_defaults"

    def run(self, ctx: RunContext) -> StepResult:
        """
        Executa a aplicação de defaults conforme o contrato.

        Regras:
        - Nunca sobrescreve valores não nulos
        - Nunca cria colunas fora do contrato
        - Nunca aplica defaults implícitos
        - Sempre registra impacto quando houver mutação
        """

        # ------------------------------------------------------------------
        # Dataset (fonte de mutação explícita)
        # ------------------------------------------------------------------
        df = getattr(ctx, "dataset", None)
        if df is None:
            raise ValueError("RunContext não possui dataset carregado (ctx.dataset)")

        if not isinstance(df, pd.DataFrame):
            raise TypeError("ctx.dataset deve ser um pandas.DataFrame")

        # ------------------------------------------------------------------
        # Contrato (shape real: features list + defaults mapping)
        # ------------------------------------------------------------------
        contract = ctx.contract or {}
        if not isinstance(contract, dict):
            raise TypeError("ctx.contract deve ser um dict (Internal Contract v1)")

        features = contract.get("features") or []
        defaults = contract.get("defaults") or {}

        if not isinstance(features, list):
            raise TypeError("contract['features'] deve ser uma lista (list[dict])")
        if not isinstance(defaults, dict):
            raise TypeError("contract['defaults'] deve ser um dict (mapping coluna -> default)")

        # Index rápido: nome -> required
        required_by_name: Dict[str, bool] = {}
        for f in features:
            if not isinstance(f, dict):
                continue
            name = f.get("name")
            if isinstance(name, str) and name:
                required_by_name[name] = bool(f.get("required", True))

        # ------------------------------------------------------------------
        # Auditoria de impacto (apenas quando houver mutação real)
        # ------------------------------------------------------------------
        impact: Dict[str, Dict[str, Any]] = {}

        # ------------------------------------------------------------------
        # Aplicação controlada de defaults (somente o que está em contract.defaults)
        # ------------------------------------------------------------------
        for col, default_value in defaults.items():
            if not isinstance(col, str) or not col:
                continue  # chave inválida: ignora (contrato deveria validar isso antes)

            if col in df.columns:
                # Preencher apenas onde é null/NaN
                mask = df[col].isna()
                values_filled = int(mask.sum())
                if values_filled > 0:
                    df.loc[mask, col] = default_value
                    impact[col] = {
                        "default_value": default_value,
                        "values_filled": values_filled,
                        "column_created": False,
                    }
            else:
                # Coluna ausente: criar apenas se explicitamente permitido (required == false)
                required = required_by_name.get(col, True)  # safe default: se não souber, trate como required
                if required is False:
                    df[col] = default_value
                    impact[col] = {
                        "default_value": default_value,
                        "values_filled": int(len(df)),
                        "column_created": True,
                    }

        # ------------------------------------------------------------------
        # Registrar impacto no RunContext (Engine irá incorporar no payload/manifest)
        # ------------------------------------------------------------------
        if impact:
            impacts = getattr(ctx, "impacts", None)
            if not isinstance(impacts, dict):
                impacts = {}
                setattr(ctx, "impacts", impacts)
            impacts[self.step_id] = impact

        # Atualiza dataset no contexto
        ctx.dataset = df

        return StepResult(
            step_id=self.step_id,
            kind=StepKind.TRANSFORM,
            status=StepStatus.SUCCESS,
            summary="defaults applied (contract-driven)",
            metrics={},
            warnings=[],
            artifacts={},
            payload={},
        )
