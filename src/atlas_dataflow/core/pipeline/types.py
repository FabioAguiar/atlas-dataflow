
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class StepKind(str, Enum):
    DIAGNOSTIC = "diagnostic"
    TRANSFORM = "transform"
    TRAIN = "train"
    EVALUATE = "evaluate"
    EXPORT = "export"


class StepStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class StepResult:
    step_id: str
    kind: StepKind
    status: StepStatus
    summary: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    artifacts: Dict[str, str] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)
