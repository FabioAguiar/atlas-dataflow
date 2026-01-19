"""Step canônico: contract.load (v1).

Responsabilidades:
- carregar contrato (YAML/JSON) via `contract.path`
- validar contra Internal Contract v1
- injetar no RunContext (ctx.contract)
- produzir payload rastreável (path + hash + versão)

Alinhado a:
- `docs/spec/contract.load.v1.md`
- `docs/spec/internal_contract.v1.md`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from atlas_dataflow.core.contract.errors import ContractError
from atlas_dataflow.core.contract.hashing import compute_contract_hash
from atlas_dataflow.core.contract.loader import load_contract
from atlas_dataflow.core.contract.schema import validate_internal_contract_v1
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


@dataclass
class ContractLoadStep(Step):
    """Carrega e valida o Internal Contract v1."""

    id: str = "contract.load"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = []

    def run(self, ctx: RunContext) -> StepResult:
        cfg = ctx.config or {}
        contract_cfg = (cfg.get("contract") or {}) if isinstance(cfg, dict) else {}
        path = contract_cfg.get("path") if isinstance(contract_cfg, dict) else None

        try:
            data = load_contract(path=path)
            validated = validate_internal_contract_v1(data)
            effective = validated.to_dict()

            # Injeção no contexto
            ctx.contract = effective
            # Guardamos também o tipo interno (útil para consumo futuro)
            ctx.meta.setdefault("_internal", {})
            internal = ctx.meta.get("_internal") or {}
            if isinstance(internal, dict):
                internal["contract_model"] = validated
                ctx.meta["_internal"] = internal

            # Evidências rastreáveis
            p = Path(str(path))
            chash = compute_contract_hash(effective)

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="contract loaded and validated",
                metrics={
                    "features_count": len(effective.get("features", []) or []),
                },
                warnings=[],
                artifacts={},
                payload={
                    "contract": {
                        "path": str(p),
                        "hash": chash,
                        "contract_version": effective.get("contract_version"),
                    }
                },
            )
        except ContractError as e:
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "contract.load failed",
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
        except Exception as e:
            # fallback (evita perder contexto)
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "contract.load failed",
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
