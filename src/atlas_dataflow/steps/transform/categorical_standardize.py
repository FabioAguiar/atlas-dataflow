"""
Step canônico: transform.categorical_standardize (v1).

Responsabilidades (M3):
- Consumir dataset do RunContext (preferencialmente `data.raw_rows`; se existirem `data.train`/`data.test`,
  aplica em ambos para consistência).
- Aplicar normalização categórica APENAS por regras explícitas de contrato:
  - mapeamentos (alias -> canônico)
  - casing (upper/lower) quando configurado
- Detectar e reportar categorias fora do domínio esperado (quando `allowed` estiver presente em contrato).
- Registrar auditoria de impacto (payload) e só então atualizar os artifacts.

Princípios:
- Nada implícito: não inferir categorias, não aplicar fuzzy matching.
- Mutação controlada: só altera colunas explicitamente declaradas no contrato.
- Auditoria obrigatória: sempre emite payload, mesmo quando não há mudanças.

Compatibilidade de contrato:
- Suporta o formato canônico do Internal Contract v1:
  categories:
    <col>:
      allowed: [...]
      normalization:
        type: map | lower | upper | none
        mapping: {alias: canonical}
- Suporta (fallback) o formato legado da spec v1 gerada no projeto:
  categorical_standardization:
    <col>:
      casing: upper|lower
      mappings: {alias: canonical}

Referências:
- docs/spec/transform.categorical_standardize.v1.md
- docs/spec/internal_contract.v1.md
- docs/pipeline_elements.md
- docs/engine.md
- docs/traceability.md
- docs/manifest.schema.v1.md
- docs/testing.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    try:
        import pandas as pd  # type: ignore

        return bool(pd.isna(v))
    except Exception:
        return False


def _coerce_str(v: Any) -> Optional[str]:
    if _is_missing(v):
        return None
    if isinstance(v, str):
        return v
    # Não inferimos semântica; apenas tornamos serializável para comparação/mapping explícito
    return str(v)


def _apply_casing(s: str, casing: Optional[str]) -> str:
    if casing is None:
        return s
    if casing == "upper":
        return s.upper()
    if casing == "lower":
        return s.lower()
    raise ValueError(f"Invalid casing: {casing}")


def _extract_rules(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Retorna um dict por coluna contendo:
      - allowed: Optional[list]
      - mappings: dict
      - casing: Optional[str]  # upper|lower|None
    """
    rules: Dict[str, Dict[str, Any]] = {}

    # 1) Internal Contract v1: categories.<col>.normalization
    cats = contract.get("categories", {})
    if isinstance(cats, dict):
        for col, spec in cats.items():
            if not isinstance(col, str) or not isinstance(spec, dict):
                continue
            allowed = spec.get("allowed")
            allowed_list = allowed if isinstance(allowed, list) else None

            norm = spec.get("normalization", {})
            if not isinstance(norm, dict):
                norm = {}
            ntype = norm.get("type")
            mapping = norm.get("mapping", {})
            mappings = mapping if isinstance(mapping, dict) else {}

            casing: Optional[str] = None
            if ntype in ("upper", "lower"):
                casing = str(ntype)
                mappings = {}  # sem mapeamento quando o tipo é casing-only
            elif ntype == "map":
                casing = None
            elif ntype in (None, "none"):
                casing = None
                mappings = {}
            else:
                # tipo desconhecido: falha explícita (contrato inconsistente)
                raise ValueError(f"Invalid normalization.type for column '{col}': {ntype}")

            rules[col] = {
                "allowed": allowed_list,
                "mappings": {str(k): str(v) for k, v in mappings.items()},
                "casing": casing,
                "source": "contract.categories",
            }

    # 2) Fallback: categorical_standardization (spec v1 "legada")
    legacy = contract.get("categorical_standardization", {})
    if isinstance(legacy, dict):
        for col, spec in legacy.items():
            if col in rules:
                continue
            if not isinstance(col, str) or not isinstance(spec, dict):
                continue
            casing = spec.get("casing")
            if casing is not None:
                casing = str(casing)
                if casing not in ("upper", "lower"):
                    raise ValueError(f"Invalid casing for column '{col}': {casing}")
            mappings = spec.get("mappings", {})
            if mappings is None:
                mappings = {}
            if not isinstance(mappings, dict):
                raise ValueError(f"Invalid mappings for column '{col}': must be a dict")
            rules[col] = {
                "allowed": None,
                "mappings": {str(k): str(v) for k, v in mappings.items()},
                "casing": casing,
                "source": "contract.categorical_standardization",
            }

    return rules


def _targets_in_ctx(ctx: RunContext) -> List[str]:
    # Prefer trabalhar em train/test se existirem (pós split).
    if ctx.has_artifact("data.train") and ctx.has_artifact("data.test"):
        return ["data.train", "data.test"]
    return ["data.raw_rows"]


@dataclass
class TransformCategoricalStandardizeStep(Step):
    """Normalização categórica declarativa guiada por contrato."""

    id: str = "transform.categorical_standardize"
    kind: StepKind = StepKind.TRANSFORM
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            # Em M3, normalmente após split (mas funciona também antes).
            self.depends_on = ["split.train_test"]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            if not isinstance(ctx.contract, dict):
                raise ValueError("Missing or invalid contract in RunContext")

            rules = _extract_rules(ctx.contract)
            if not rules:
                # Sem configuração: não normaliza, mas registra auditoria explícita.
                payload = {
                    "impact": {
                        "columns_affected": [],
                        "mappings_applied": {},
                        "new_categories": {},
                        "note": "no categorical normalization rules found in contract",
                    }
                }
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="no categorical normalization rules found (noop)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload=payload,
                )

            targets = _targets_in_ctx(ctx)
            for key in targets:
                if not ctx.has_artifact(key):
                    raise ValueError(f"Missing required artifact: {key}")

            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for transform.categorical_standardize") from e

            columns_affected: List[str] = []
            mappings_applied: Dict[str, List[Dict[str, Any]]] = {}
            new_categories: Dict[str, List[str]] = {}

            # Aplicação por artifact
            for artifact_key in targets:
                rows = ctx.get_artifact(artifact_key)
                if rows is None:
                    raise ValueError(f"Artifact {artifact_key} is None")
                if not isinstance(rows, list):
                    raise ValueError(f"Invalid artifact: {artifact_key} must be a list of rows (dict)")

                df = pd.DataFrame(rows)

                # Aplicar por coluna declarada
                for col, r in rules.items():
                    if col not in df.columns:
                        # contrato declarou coluna, mas dataset não tem -> falha explícita (conforme spec)
                        raise ValueError(f"Column declared for normalization not found: {col}")

                    allowed = r.get("allowed")
                    allowed_set = set(str(x) for x in allowed) if isinstance(allowed, list) else None
                    mappings: Dict[str, str] = r.get("mappings", {}) or {}
                    casing: Optional[str] = r.get("casing")

                    changed = False
                    applied_records: Dict[Tuple[str, str], int] = {}
                    new_vals: set = set()

                    def transform_value(v: Any) -> Any:
                        nonlocal changed
                        s = _coerce_str(v)
                        if s is None:
                            return v
                        original = s
                        # 1) mapeamento explícito (alias -> canonical)
                        if original in mappings:
                            s2 = mappings[original]
                        else:
                            s2 = original

                        # 2) casing explícito (se houver)
                        s3 = _apply_casing(s2, casing)

                        if str(s3) != str(original):
                            changed = True
                            applied_records[(str(original), str(s3))] = applied_records.get((str(original), str(s3)), 0) + 1

                        # 3) detecção de categoria fora do domínio (se allowed existir)
                        if allowed_set is not None and str(s3) not in allowed_set:
                            new_vals.add(str(s3))

                        return s3

                    df[col] = df[col].apply(transform_value)

                    if changed:
                        if col not in columns_affected:
                            columns_affected.append(col)

                    if applied_records:
                        mappings_applied.setdefault(col, [])
                        for (f, t), cnt in sorted(applied_records.items(), key=lambda x: (x[0][0], x[0][1])):
                            mappings_applied[col].append({"from": f, "to": t, "count": int(cnt)})

                    if new_vals:
                        # ordenação determinística
                        new_categories[col] = sorted(new_vals)

                # Persistir de volta em formato serializável
                ctx.set_artifact(artifact_key, df.to_dict(orient="records"))

            payload = {
                "impact": {
                    "columns_affected": columns_affected,
                    "mappings_applied": mappings_applied,
                    "new_categories": new_categories,
                }
            }

            ctx.log(
                step_id=self.id,
                level="info",
                message="categorical standardization applied",
                targets=targets,
                columns_affected=len(columns_affected),
                new_categories_cols=len(new_categories),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="categorical standardization applied",
                metrics={
                    "targets": len(targets),
                    "columns_affected": len(columns_affected),
                    "new_categories_cols": len(new_categories),
                },
                warnings=[],
                artifacts={k: k for k in targets},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="transform.categorical_standardize failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "transform.categorical_standardize failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )
