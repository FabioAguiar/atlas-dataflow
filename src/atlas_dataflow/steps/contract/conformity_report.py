"""Step canônico: contract.conformity_report (v1).

Responsabilidades:
  - comparar dataset efetivo (tabular) com o Internal Contract v1 já injetado no RunContext
  - produzir um relatório diagnóstico explícito (sem mutar dados)
  - padronizar o campo `decisions_required`

Alinhado a:
  - `docs/spec/contract.conformity_report.v1.md`
  - `docs/spec/internal_contract.v1.md`

Notas de implementação (v1):
  - Este Step é **diagnóstico** e não aplica coerções ou defaults.
  - O Atlas DataFlow (M0/M1) não assume dependências pesadas (ex.: pandas).
    Portanto, este Step opera sobre um dataset tabular representado como:
      - list[dict[str, Any]] (ex.: CSV carregado como dict rows)
    armazenado no artifact store do RunContext.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _infer_observed_dtype(values: List[Any]) -> str:
    """Inferência leve de dtype observado (v1).

    Objetivo: gerar um rótulo estável para diagnóstico.

    Regras:
      - ignora nulos/strings vazias
      - tenta identificar int/float/bool; fallback: string
    """

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
        # Aceita formatos simples: 12.3, -0.5, 1, 1.0
        try:
            float(s)
            return True
        except Exception:
            return False

    if all(_is_float(s) for s in clean):
        return "float"

    return "string"


def _count_parse_failures(expected: str, values: List[Any]) -> int:
    """Conta falhas ao tentar interpretar valores para um dtype esperado (sem coerção efetiva)."""

    failures = 0

    def _iter_clean() -> List[str]:
        out: List[str] = []
        for v in values:
            if v is None:
                continue
            s = str(v).strip()
            if s == "":
                continue
            out.append(s)
        return out

    clean = _iter_clean()
    if not clean:
        return 0

    exp = expected.lower()
    for s in clean:
        try:
            if exp == "int":
                # float("1.0") não é int. Mantemos estrito.
                if s.startswith(("+", "-")):
                    ss = s[1:]
                else:
                    ss = s
                if not ss.isdigit():
                    raise ValueError("not int")
            elif exp == "float":
                float(s)
            elif exp == "bool":
                if s.lower() not in {"true", "false"}:
                    raise ValueError("not bool")
            elif exp in {"string", "category"}:
                # sempre interpretável
                pass
            else:
                # dtype desconhecido no v1
                pass
        except Exception:
            failures += 1

    return failures


def _dataset_columns(rows: List[Dict[str, Any]]) -> Set[str]:
    cols: Set[str] = set()
    for r in rows:
        if isinstance(r, dict):
            cols.update(str(k) for k in r.keys())
    return cols


def _get_effective_rows(ctx: RunContext) -> List[Dict[str, Any]]:
    """Obtém dataset efetivo para diagnóstico.

    Convenção v1:
      - preferir `data.raw_rows`
      - fallback: `data.transformed_rows`
    """

    for key in ("data.raw_rows", "data.transformed_rows"):
        if ctx.has_artifact(key):
            rows = ctx.get_artifact(key)
            if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
                return rows  # type: ignore[return-value]
    raise ValueError("No tabular dataset found in RunContext artifacts (expected data.raw_rows or data.transformed_rows)")


def _contract_feature_map(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    feats = contract.get("features") or []
    if not isinstance(feats, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for f in feats:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            out[f["name"]] = f
    return out


@dataclass
class ContractConformityReportStep(Step):
    """Diagnóstico de conformidade entre dataset efetivo e Internal Contract v1."""

    id: str = "contract.conformity_report"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = ["contract.load"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            contract = ctx.contract
            if not isinstance(contract, dict) or not contract:
                raise ValueError("RunContext.contract is missing or invalid; ensure contract.load ran successfully")

            rows = _get_effective_rows(ctx)
            cols = _dataset_columns(rows)

            target = contract.get("target") or {}
            target_name = target.get("name") if isinstance(target, dict) else None
            if not isinstance(target_name, str) or not target_name:
                # contrato deveria garantir, mas mantemos defesa
                raise ValueError("Contract target.name is missing")

            feat_map = _contract_feature_map(contract)
            feature_names = set(feat_map.keys())
            declared_cols = set(feature_names)
            declared_cols.add(target_name)

            # ------------------------
            # 1) Colunas faltantes / extras
            # ------------------------
            missing_required: List[str] = []
            for name, spec in feat_map.items():
                required = bool(spec.get("required"))
                if required and name not in cols:
                    missing_required.append(name)

            # target sempre requerido
            if target_name not in cols:
                missing_required.append(target_name)

            extra_columns = sorted([c for c in cols if c not in declared_cols])

            # ------------------------
            # 2) Divergências de dtype
            # ------------------------
            dtype_issues: List[Dict[str, Any]] = []
            blocking_dtype_cols: Set[str] = set()

            def _collect_values(col: str) -> List[Any]:
                return [r.get(col) for r in rows if isinstance(r, dict)]

            # features
            for name, spec in feat_map.items():
                if name not in cols:
                    continue
                expected = spec.get("dtype")
                if not isinstance(expected, str) or not expected:
                    continue
                values = _collect_values(name)
                observed = _infer_observed_dtype(values)
                if observed == "unknown":
                    # sem dados suficientes; não sinalizamos mismatch
                    continue
                # Normalização simples do dtype esperado
                exp_norm = expected.lower()
                if exp_norm == "category":
                    exp_norm = "category"
                if exp_norm != observed:
                    parse_failures = _count_parse_failures(exp_norm, values)
                    dtype_issues.append(
                        {
                            "column": name,
                            "expected": exp_norm,
                            "observed": observed,
                            "parse_failures": parse_failures,
                        }
                    )
                    if parse_failures > 0 and exp_norm in {"int", "float", "bool"}:
                        blocking_dtype_cols.add(name)

            # target
            if target_name in cols:
                expected_t = target.get("dtype") if isinstance(target, dict) else None
                if isinstance(expected_t, str) and expected_t:
                    values_t = _collect_values(target_name)
                    observed_t = _infer_observed_dtype(values_t)
                    exp_t = expected_t.lower()
                    if observed_t != "unknown" and exp_t != observed_t:
                        parse_failures = _count_parse_failures(exp_t, values_t)
                        dtype_issues.append(
                            {
                                "column": target_name,
                                "expected": exp_t,
                                "observed": observed_t,
                                "parse_failures": parse_failures,
                            }
                        )
                        if parse_failures > 0 and exp_t in {"int", "float", "bool"}:
                            blocking_dtype_cols.add(target_name)

            # ------------------------
            # 3) Divergências de categorias
            # ------------------------
            category_issues: List[Dict[str, Any]] = []
            categories = contract.get("categories") or {}
            if isinstance(categories, dict):
                for col, spec in categories.items():
                    if col not in cols:
                        continue
                    if not isinstance(spec, dict):
                        continue
                    allowed = spec.get("allowed")
                    if not isinstance(allowed, list):
                        continue
                    allowed_set = set(str(v) for v in allowed)
                    values = [str(v).strip() for v in _collect_values(col) if v is not None and str(v).strip() != ""]
                    invalid = sorted(set(values) - allowed_set)
                    if invalid:
                        category_issues.append({"column": col, "invalid_values": invalid})

            # ------------------------
            # decisions_required
            # ------------------------
            decisions_required: List[Dict[str, Any]] = []

            if missing_required:
                decisions_required.append(
                    {
                        "code": "MISSING_REQUIRED_COLUMNS",
                        "severity": "error",
                        "description": "Dataset is missing required columns declared in the contract.",
                        "affected_columns": sorted(set(missing_required)),
                        "suggested_actions": [
                            "Provide required columns in the dataset",
                            "Mark columns as required=false only if semantically acceptable",
                        ],
                    }
                )

            if extra_columns:
                decisions_required.append(
                    {
                        "code": "EXTRA_COLUMNS",
                        "severity": "warning",
                        "description": "Dataset contains extra columns not declared in the contract.",
                        "affected_columns": extra_columns,
                        "suggested_actions": [
                            "Update contract to include the columns if relevant",
                            "Drop columns in a later transform step if they are irrelevant",
                        ],
                    }
                )

            if dtype_issues:
                severity = "warning" if not blocking_dtype_cols else "error"
                decisions_required.append(
                    {
                        "code": "DTYPE_MISMATCH",
                        "severity": severity,
                        "description": "Observed dtypes differ from contract expectations; safe coercion may be required.",
                        "affected_columns": sorted({d["column"] for d in dtype_issues}),
                        "suggested_actions": [
                            "Run transform.cast_types_safe",
                            "Fix upstream data typing if coercion would be unsafe",
                        ],
                    }
                )

            if category_issues:
                decisions_required.append(
                    {
                        "code": "CATEGORY_OUT_OF_DOMAIN",
                        "severity": "warning",
                        "description": "Dataset contains categorical values outside the allowed domain declared in the contract.",
                        "affected_columns": sorted({c["column"] for c in category_issues}),
                        "suggested_actions": [
                            "Update allowed categories in contract if values are legitimate",
                            "Add normalization/mapping rules in a later transform step",
                        ],
                    }
                )

            total_issues = 0
            total_issues += len(set(missing_required))
            total_issues += len(extra_columns)
            total_issues += len(dtype_issues)
            total_issues += len(category_issues)
            blocking_issues = 0
            blocking_issues += len(set(missing_required))
            blocking_issues += len(blocking_dtype_cols)

            payload = {
                "summary": {"total_issues": int(total_issues), "blocking_issues": int(blocking_issues)},
                "missing_columns": sorted(set(missing_required)),
                "extra_columns": extra_columns,
                "dtype_issues": dtype_issues,
                "category_issues": category_issues,
                "decisions_required": decisions_required,
            }

            ctx.log(step_id=self.id, level="info", message="conformity report generated", total_issues=total_issues)

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="conformity report generated",
                metrics={
                    "total_issues": int(total_issues),
                    "blocking_issues": int(blocking_issues),
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
                summary=str(e) or "contract.conformity_report failed",
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
