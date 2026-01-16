
from __future__ import annotations

from typing import Protocol, runtime_checkable, List

from .context import RunContext
from .types import StepKind, StepResult


@runtime_checkable
class Step(Protocol):
    """Contrato interno canônico de um Step do Atlas DataFlow."""

    id: str
    kind: StepKind
    depends_on: List[str]

    def run(self, ctx: RunContext) -> StepResult:
        """Executa a etapa uma única vez usando exclusivamente o RunContext."""
        ...
