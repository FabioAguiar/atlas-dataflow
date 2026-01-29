"""Step canônico: contract.load (v1).

Responsabilidades:
- carregar contrato (YAML/JSON) via `contract.path`
- validar contra Internal Contract v1
- injetar no RunContext (ctx.contract)
- produzir payload rastreável (path + hash + versão)

Alinhado a:
- `docs/spec/contract.load.v1.md`
- `docs/spec/internal_contract.v1.md`

Guardrails (M9-02 — Quality/Guardrails):
- Substituir erros implícitos por AtlasErrorPayload (serializável e acionável)
- Marcar decision_required=True quando aplicável (ex.: contrato inválido / path ausente)
- Incluir details estruturado para diagnóstico e snapshots
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from atlas_dataflow.core.contract.errors import ContractError
from atlas_dataflow.core.contract.hashing import compute_contract_hash
from atlas_dataflow.core.contract.loader import load_contract
from atlas_dataflow.core.contract.schema import validate_internal_contract_v1
from atlas_dataflow.core.errors import AtlasErrorPayload
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

    def _mk_error(
        self,
        *,
        error_type: str,
        message: str,
        details: Dict[str, Any],
        hint: Optional[str],
        decision_required: bool,
    ) -> Dict[str, Any]:
        return AtlasErrorPayload(
            type=error_type,
            message=message,
            details=details,
            hint=hint,
            decision_required=decision_required,
        ).to_dict()

    def run(self, ctx: RunContext) -> StepResult:
        cfg = ctx.config or {}
        contract_cfg = (cfg.get("contract") or {}) if isinstance(cfg, dict) else {}
        path = contract_cfg.get("path") if isinstance(contract_cfg, dict) else None

        # Guardrail explícito: path ausente (decisão requerida)
        if not path:
            err = self._mk_error(
                error_type="CONTRACT_PATH_MISSING",
                message="Caminho do contrato ausente na configuração",
                details={
                    "expected_config_key": "contract.path",
                    "received": path,
                },
                hint="Declare `contract.path` na config (ex.: contract.internal.v1.json)",
                decision_required=True,
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=err.get("message") or "contract.load failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )

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
            # Conflito de contrato é sempre "decision required":
            # o operador deve corrigir contrato/config/dados — nunca autocorreção.
            err = self._mk_error(
                error_type=e.__class__.__name__,
                message=str(e) or "Contrato inválido",
                details={
                    "contract_path": str(path),
                    "exception_class": e.__class__.__name__,
                },
                hint="Corrija o contrato para aderir ao Internal Contract v1",
                decision_required=True,
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=err.get("message") or "contract.load failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )
        except Exception as e:
            # fallback controlado (não vazar stack trace cru para o operador)
            err = self._mk_error(
                error_type=e.__class__.__name__,
                message="Falha inesperada ao carregar/validar contrato",
                details={
                    "contract_path": str(path),
                    "exception_class": e.__class__.__name__,
                },
                hint="Verifique o path do contrato e o formato do arquivo (JSON/YAML)",
                decision_required=False,
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=err.get("message") or "contract.load failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": err},
            )
