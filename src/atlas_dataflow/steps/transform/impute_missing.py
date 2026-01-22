"""\
Step canônico: transform.impute_missing (v1).

Responsabilidades (M3 — Preparação Supervisionada):
- Consumir dataset do RunContext (preferencialmente `data.train`/`data.test` se existirem;
  caso contrário, `data.raw_rows`).
- Aplicar imputação de valores ausentes SOMENTE onde explicitamente configurado no contrato.
- Suportar estratégias distintas para colunas numéricas e categóricas, sem inferência automática.
- Garantir que colunas marcadas como mandatórias não permaneçam com valores ausentes.
- Produzir auditoria detalhada e serializável de impacto e só então atualizar os artifacts.

Princípios:
- Nada implícito: não inferir estratégia, não aplicar imputação global.
- Mutação controlada: só atua em colunas explicitamente configuradas.
- Auditoria obrigatória: sempre emite payload, mesmo quando não há mudanças.

Contrato esperado (v1):

contract:
  imputation:
    age:
      strategy: median
      mandatory: true
    country:
      strategy: most_frequent
      mandatory: false

Estratégias suportadas (v1):
- Numéricas: mean | median | constant
- Categóricas: most_frequent | constant

Para `constant`, o contrato deve fornecer `value`.

Referências:
- docs/spec/transform.impute_missing.v1.md
- docs/spec/internal_contract.v1.md
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _targets_in_ctx(ctx: RunContext) -> List[str]:
    # Preferimos atuar em train/test se existirem (pós split).
    if ctx.has_artifact("data.train") and ctx.has_artifact("data.test"):
        return ["data.train", "data.test"]
    return ["data.raw_rows"]


def _is_missing_series(s: Any) -> Any:
    """Wrapper para `pd.isna` com fallback seguro."""
    import pandas as pd  # type: ignore

    return pd.isna(s)


def _feature_role(contract: Dict[str, Any], col: str) -> Optional[str]:
    features = contract.get("features")
    if isinstance(features, list):
        for f in features:
            if isinstance(f, dict) and f.get("name") == col:
                role = f.get("role")
                return str(role) if role is not None else None
    return None


def _extract_rules(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extrai regras de imputação por coluna.

    Retorna um dict por coluna contendo:
      - strategy: str
      - mandatory: bool
      - value: Any | None  (quando strategy == constant)

    Notas de compatibilidade:
      - Se a coluna estiver presente em `contract.imputation` mas só tiver
        `allowed: true/false` (formato legado do Internal Contract v1), ela NÃO
        é considerada configurada para imputação (noop).
      - Se `mandatory: true` aparecer sem `strategy`, falha explícita.
    """
    raw = contract.get("imputation") or {}
    if not isinstance(raw, dict):
        raise ValueError("contract.imputation must be a mapping/dict")

    rules: Dict[str, Dict[str, Any]] = {}
    for col, spec in raw.items():
        if not isinstance(col, str):
            continue
        if not isinstance(spec, dict):
            raise ValueError(f"imputation.{col} must be a mapping")

        # legado: apenas allowed bool -> não configura estratégia
        if "strategy" not in spec:
            mandatory = spec.get("mandatory")
            if mandatory is True:
                raise ValueError(f"imputation.{col}.strategy is required when mandatory=true")
            continue

        strategy = spec.get("strategy")
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError(f"imputation.{col}.strategy must be a non-empty string")

        mandatory = spec.get("mandatory")
        if not isinstance(mandatory, bool):
            raise ValueError(f"imputation.{col}.mandatory must be boolean")

        value = spec.get("value")
        rules[col] = {"strategy": strategy.strip(), "mandatory": mandatory, "value": value}

    return rules


@dataclass
class TransformImputeMissingStep(Step):
    """Imputa valores ausentes de forma declarativa e auditável (v1)."""

    id: str = "transform.impute_missing"
    kind: StepKind = StepKind.TRANSFORM
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # Em M3, após normalização categórica (se configurada) e tipagem segura.
            self.depends_on = ["transform.categorical_standardize"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            if not isinstance(ctx.contract, dict):
                raise ValueError("Missing or invalid contract in RunContext")

            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for transform.impute_missing") from e

            rules = _extract_rules(ctx.contract)
            if not rules:
                payload = {
                    "impact": {
                        "columns_affected": [],
                        "strategy_by_column": {},
                        "values_imputed": {},
                        "note": "no imputation rules found in contract",
                    }
                }
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="no imputation rules found (noop)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload=payload,
                )

            targets = _targets_in_ctx(ctx)
            for key in targets:
                if not ctx.has_artifact(key):
                    raise ValueError(f"Missing required artifact: {key}")

            columns_affected: List[str] = []
            strategy_by_column: Dict[str, str] = {}
            values_imputed: Dict[str, int] = {}
            warnings: List[str] = []

            for artifact_key in targets:
                rows = ctx.get_artifact(artifact_key)
                if rows is None:
                    raise ValueError(f"Artifact {artifact_key} is None")
                if not isinstance(rows, list):
                    raise ValueError(f"Invalid artifact: {artifact_key} must be a list of rows (dict)")

                df = pd.DataFrame(rows)

                # staging por artifact: aplicamos em df e só persistimos ao final
                for col, r in rules.items():
                    if col not in df.columns:
                        raise ValueError(f"Column declared for imputation not found: {col}")

                    strategy = r["strategy"]
                    mandatory = bool(r["mandatory"])
                    value = r.get("value")

                    role = _feature_role(ctx.contract, col)

                    missing_mask = _is_missing_series(df[col])
                    missing_before = int(missing_mask.sum())
                    strategy_by_column[col] = strategy
                    if missing_before == 0:
                        values_imputed.setdefault(col, 0)
                        continue

                    # decide tipo de estratégia permitido pela role
                    numeric_strats = {"mean", "median", "constant"}
                    cat_strats = {"most_frequent", "constant"}

                    # Se role é conhecida, validamos coerência (sem inferir)
                    if role in ("numerical", "boolean", "text", "other"):
                        # boolean/text não têm estratégia padrão no v1; exigimos contract coerente
                        if role != "numerical" and strategy in ("mean", "median"):
                            raise ValueError(f"Strategy '{strategy}' not allowed for role '{role}' (column '{col}')")
                    if role == "categorical" and strategy in ("mean", "median"):
                        raise ValueError(f"Strategy '{strategy}' not allowed for categorical column '{col}'")

                    if strategy in ("mean", "median"):
                        if strategy not in numeric_strats:
                            raise ValueError(f"Invalid numeric strategy for '{col}': {strategy}")

                        non_missing = df.loc[~missing_mask, col]
                        if len(non_missing) == 0:
                            if mandatory:
                                raise ValueError(f"Cannot impute mandatory column '{col}': no observed values")
                            warnings.append(f"Cannot impute column '{col}' (no observed values); leaving as-is")
                            values_imputed[col] = 0
                            continue

                        # força numérico (sem inferir semântica): se não for convertível, falha
                        try:
                            series_num = pd.to_numeric(non_missing)
                        except Exception as e:
                            raise ValueError(f"Column '{col}' is not numeric for strategy '{strategy}'") from e

                        fill_value = float(series_num.mean()) if strategy == "mean" else float(series_num.median())
                        df.loc[missing_mask, col] = fill_value

                    elif strategy == "most_frequent":
                        if strategy not in cat_strats:
                            raise ValueError(f"Invalid categorical strategy for '{col}': {strategy}")
                        non_missing = df.loc[~missing_mask, col]
                        if len(non_missing) == 0:
                            if mandatory:
                                raise ValueError(f"Cannot impute mandatory column '{col}': no observed values")
                            warnings.append(f"Cannot impute column '{col}' (no observed values); leaving as-is")
                            values_imputed[col] = 0
                            continue
                        mode = non_missing.mode(dropna=True)
                        if mode is None or len(mode) == 0:
                            if mandatory:
                                raise ValueError(f"Cannot impute mandatory column '{col}': mode undefined")
                            warnings.append(f"Cannot impute column '{col}' (mode undefined); leaving as-is")
                            values_imputed[col] = 0
                            continue
                        fill_value = mode.iloc[0]
                        df.loc[missing_mask, col] = fill_value

                    elif strategy == "constant":
                        if "value" not in r:
                            raise ValueError(f"imputation.{col}.value is required when strategy=constant")
                        df.loc[missing_mask, col] = value

                    else:
                        raise ValueError(f"Invalid imputation strategy for column '{col}': {strategy}")

                    # contagem pós imputação
                    missing_after = int(_is_missing_series(df[col]).sum())
                    imputed = max(0, missing_before - missing_after)
                    values_imputed[col] = values_imputed.get(col, 0) + int(imputed)
                    if imputed > 0 and col not in columns_affected:
                        columns_affected.append(col)

                    if mandatory and missing_after > 0:
                        raise ValueError(f"Mandatory column '{col}' still contains missing values after imputation")

                # Persistir somente após auditoria e validações por artifact
                ctx.set_artifact(artifact_key, df.to_dict(orient="records"))

            payload = {
                "impact": {
                    "columns_affected": columns_affected,
                    "strategy_by_column": strategy_by_column,
                    "values_imputed": values_imputed,
                }
            }

            # warnings explícitos no StepResult e no ctx
            for w in warnings:
                ctx.add_warning(step_id=self.id, message=w)

            ctx.log(
                step_id=self.id,
                level="info",
                message="imputation applied",
                targets=targets,
                columns_affected=len(columns_affected),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="imputation applied",
                metrics={
                    "targets": len(targets),
                    "columns_affected": len(columns_affected),
                    "values_imputed_total": int(sum(values_imputed.values())),
                },
                warnings=warnings,
                artifacts={k: k for k in targets},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="transform.impute_missing failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "transform.impute_missing failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
