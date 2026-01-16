
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .step import Step


class DuplicateStepIdError(ValueError):
    """Raised when attempting to register two steps with the same id."""


@dataclass
class StepRegistry:
    """Registry mínimo para validar unicidade de step.id antes do Engine."""

    _steps: Dict[str, Step] = field(default_factory=dict, init=False, repr=False)
    _order: List[str] = field(default_factory=list, init=False, repr=False)

    def add(self, step: Step) -> None:
        step_id = getattr(step, "id", None)
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("step.id must be a non-empty string")

        if step_id in self._steps:
            raise DuplicateStepIdError(f"Duplicate step id: {step_id}")

        self._steps[step_id] = step
        self._order.append(step_id)

    def get(self, step_id: str) -> Step:
        return self._steps[step_id]

    def list(self) -> List[Step]:
        return [self._steps[sid] for sid in self._order]
