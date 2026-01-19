"""Step canônico: transform.cast_types_safe (v1).

Responsabilidades (v1):
  - aplicar coerções de tipos **seguras**, guiadas pelo Internal Contract v1
  - preservar a estrutura do dataset (não remove colunas)
  - converter falhas de coerção em null/None (sem descartar linhas)
  - produzir auditoria explícita de impacto por coluna

Este Step **não**:
  - remove colunas
  - cria colunas não declaradas
  - aplica defaults
  - altera categorias (normalização/mapping)

Notas de implementação (v1):
  - Para manter o core leve nos milestones iniciais, o dataset tabular é
    representado como `list[dict[str, Any]]`.
  - A coerção ocorre apenas para colunas declaradas no contrato (features + target).

Referências:
  - `docs/spec/transform.cast_types_safe.v1.md`
  - `docs/spec/internal_contract.v1.md`
  - `docs/spec/contract.conformity_report.v1.md`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


# -----------------------------
# Helpers — dataset access
# -----------------------------

def _get_effective_rows(ctx: RunContext) -> List[Dict[str, Any]]:
    """Obtém o dataset efetivo para transformação.

    Convenção v1:
      - preferir `data.raw_rows`
      - fallback: `data.transformed_rows`

    Retorna sempre uma lista de dicts.
    """

    for key in ("data.raw_rows", "data.transformed_rows"):
        if ctx.has_artifact(key):
            rows = ctx.get_artifact(key)
            if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
                return rows  # type: ignore[return-value]
    raise ValueError(
        "No tabular dataset found in RunContext artifacts (expected data.raw_rows or data.transformed_rows)"
    )


def _contract_feature_map(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    feats = contract.get("features") or []
    if not isinstance(feats, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for f in feats:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            out[f["name"]] = f
    return out


# -----------------------------
# Helpers — coercions
# -----------------------------

def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _coerce_int(v: Any) -> Optional[int]:
    if _is_blank(v):
        return None
    if isinstance(v, bool):
        # evita True/False virar 1/0
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s.startswith(("+", "-")):
        sign = s[0]
        digits = s[1:]
    else:
        sign = ""
        digits = s
    if not digits.isdigit():
        return None
    try:
        return int(f"{sign}{digits}")
    except Exception:
        return None


def _coerce_float(v: Any) -> Optional[float]:
    if _is_blank(v):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except Exception:
        return None


def _coerce_bool(v: Any) -> Optional[bool]:
    if _is_blank(v):
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _coerce_string(v: Any) -> Optional[str]:
    if _is_blank(v):
        return None
    return str(v)


def _coerce_category(v: Any) -> Optional[str]:
    # no v1, "category" é representado internamente como string estável
    if _is_blank(v):
        return None
    return str(v).strip()


def _infer_observed_dtype(values: List[Any]) -> str:
    """Inferência leve de dtype observado (mesma lógica do report v1)."""

    clean: List[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                continue
            clean.append(s)
        else:
            clean.append(str(v))

    if not clean:
        return "unknown"

    lowered = [s.lower() for s in clean]
    if all(s in {"true", "false"} for s in lowered):
        return "bool"

    def _is_int(s: str) -> bool:
        if s.startswith(("+", "-")):
            s = s[1:]
        return s.isdigit()

    if all(_is_int(s) for s in clean):
        return "int"

    def _is_float(s: str) -> bool:
        try:
            float(s)
            return True
        except Exception:
            return False

    if all(_is_float(s) for s in clean):
        return "float"

    return "string"


def _coerce_value(expected: str, v: Any) -> Tuple[Any, bool, bool]:
    """Coerce um valor conforme dtype esperado.

    Returns:
      (new_value, coerced, became_null)
    """

    exp = expected.lower()

    # "string" e "category" são sempre semanticamente seguras como strings.
    if exp == "string":
        nv = _coerce_string(v)
    elif exp == "category":
        nv = _coerce_category(v)
    elif exp == "int":
        nv = _coerce_int(v)
    elif exp == "float":
        nv = _coerce_float(v)
    elif exp == "bool":
        nv = _coerce_bool(v)
    else:
        # dtype desconhecido no v1: não toca
        return v, False, False

    # coerced: houve tentativa efetiva e o resultado não é o mesmo "valor bruto"
    # Regras simples e estáveis (v1):
    #  - se entrada era blank -> não conta coerção
    #  - se saída é None e entrada era não-blank -> conta coerção (falha)
    #  - se saída != entrada ou tipo mudou -> conta coerção
    if _is_blank(v):
        coerced = False
    else:
        if nv is None:
            coerced = True
        else:
            coerced = (type(nv) is not type(v)) or (nv != v)

    became_null = (nv is None) and (not _is_blank(v))

    return nv, coerced, became_null


# -----------------------------
# Step
# -----------------------------


@dataclass
class CastTypesSafeStep(Step):
    """Aplica coerções seguras de tipos guiadas pelo contrato."""

    id: str = "transform.cast_types_safe"
    kind: StepKind = StepKind.TRANSFORM
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = ["contract.conformity_report"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            contract = ctx.contract
            if not isinstance(contract, dict) or not contract:
                raise ValueError("RunContext.contract is missing or invalid; ensure contract.load ran successfully")

            rows = _get_effective_rows(ctx)

            feat_map = _contract_feature_map(contract)

            target = contract.get("target") or {}
            target_name = target.get("name") if isinstance(target, dict) else None
            target_dtype = target.get("dtype") if isinstance(target, dict) else None

            if not isinstance(target_name, str) or not target_name:
                raise ValueError("Contract target.name is missing")
            if not isinstance(target_dtype, str) or not target_dtype:
                raise ValueError("Contract target.dtype is missing")

            declared: Dict[str, str] = {}
            for name, spec in feat_map.items():
                dtype = spec.get("dtype")
                if isinstance(dtype, str) and dtype:
                    declared[name] = dtype
            declared[target_name] = target_dtype

            # auditoria
            impact: Dict[str, Dict[str, Any]] = {}

            # coleta de valores por coluna (antes)
            def _col_values(col: str, rows_: List[Dict[str, Any]]) -> List[Any]:
                return [r.get(col) for r in rows_ if isinstance(r, dict)]

            for col, exp in declared.items():
                values_before = _col_values(col, rows)
                impact[col] = {
                    "total_values": int(len(values_before)),
                    "coerced_values": 0,
                    "null_after_cast": 0,
                    "before_dtype": _infer_observed_dtype(values_before),
                    "after_dtype": exp.lower(),
                }

            # transformação (preservando estrutura)
            new_rows: List[Dict[str, Any]] = []
            total_coerced = 0
            total_nulls = 0

            for r in rows:
                if not isinstance(r, dict):
                    continue
                nr = dict(r)
                for col, exp in declared.items():
                    if col not in nr:
                        # preserva ausência (não cria coluna)
                        continue
                    old = nr.get(col)
                    nv, coerced, became_null = _coerce_value(exp, old)

                    # política v1: coerções proibidas
                    #  - não convertemos category -> numeric de forma implícita
                    #  - isso é garantido pelo direcionamento do contrato
                    #    (se o contrato pede numeric e o dado é category não numérica, vira None)

                    nr[col] = nv
                    if coerced:
                        impact[col]["coerced_values"] += 1
                        total_coerced += 1
                    if became_null:
                        impact[col]["null_after_cast"] += 1
                        total_nulls += 1

                new_rows.append(nr)

            # Persistimos o dataset transformado como artefato canônico
            ctx.set_artifact("data.transformed_rows", new_rows)

            payload = {"impact": impact}
            ctx.log(
                step_id=self.id,
                level="info",
                message="types coerced safely",
                total_coerced=total_coerced,
                total_null_after_cast=total_nulls,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="types coerced safely",
                metrics={
                    "total_coerced": int(total_coerced),
                    "total_null_after_cast": int(total_nulls),
                },
                warnings=[],
                artifacts={},
                payload=payload,
            )

        except Exception as e:
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "transform.cast_types_safe failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={
                    "error": {
                        "type": e.__class__.__name__,
                        "message": str(e) or "error",
                    }
                },
            )
