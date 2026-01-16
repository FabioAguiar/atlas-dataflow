
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from datetime import timezone


@dataclass
class RunContext:
    run_id: str
    created_at: datetime
    config: Dict[str, Any]
    contract: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)

    _artifacts: Dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    events: List[Dict[str, Any]] = field(default_factory=list, init=False)
    warnings: Dict[str, List[str]] = field(default_factory=dict, init=False)

    # -----------------------------
    # Artifact store
    # -----------------------------
    def set_artifact(self, key: str, value: Any) -> None:
        self._artifacts[key] = value

    def has_artifact(self, key: str) -> bool:
        return key in self._artifacts

    def get_artifact(self, key: str) -> Any:
        if key not in self._artifacts:
            raise KeyError(key)
        return self._artifacts[key]

    # -----------------------------
    # Logging & warnings
    # -----------------------------
    def log(self, *, step_id: str, level: str, message: str, **extra: Any) -> None:
        event = {
            "run_id": self.run_id,
            "step_id": step_id,
            "level": level,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        event.update(extra)
        self.events.append(event)

    def add_warning(self, *, step_id: str, message: str) -> None:
        if step_id not in self.warnings:
            self.warnings[step_id] = []
        self.warnings[step_id].append(message)
