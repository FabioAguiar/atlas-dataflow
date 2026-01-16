from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus

from .planner import plan_execution


@dataclass(frozen=True)
class RunResult:
    """Resultado global do run (v1 mínimo)."""
    steps: Dict[str, StepResult] = field(default_factory=dict)


class Engine:
    """Engine DAG (planner + executor) — v1 mínimo para M0-04."""

    def __init__(self, *, steps: Sequence[Step], ctx: RunContext):
        self.steps: List[Step] = list(steps)
        self.ctx: RunContext = ctx

    def _is_enabled(self, step_id: str) -> bool:
        steps_cfg = (self.ctx.config or {}).get("steps", {}) or {}
        step_cfg = steps_cfg.get(step_id, {}) or {}
        enabled = step_cfg.get("enabled", True)
        return bool(enabled)

    def _fail_fast(self) -> bool:
        engine_cfg = (self.ctx.config or {}).get("engine", {}) or {}
        return bool(engine_cfg.get("fail_fast", True))

    def run(self) -> RunResult:
        ordered = plan_execution(self.steps)

        results: Dict[str, StepResult] = {}
        for step in ordered:
            sid = step.id

            # Skip by config
            if not self._is_enabled(sid):
                kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.SKIPPED,
                    summary="skipped by config",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                continue

            # Dependency gate (v1): if any dependency FAILED => SKIPPED
            deps = list(getattr(step, "depends_on", []) or [])
            if any(results.get(d) and results[d].status == StepStatus.FAILED for d in deps):
                kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.SKIPPED,
                    summary="skipped due to failed dependency",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                continue

            kind = getattr(step, "kind", StepKind.DIAGNOSTIC) or StepKind.DIAGNOSTIC
            try:
                step_result = step.run(self.ctx)
                # Minimal normalization
                if not isinstance(step_result, StepResult):
                    raise TypeError("Step.run(ctx) must return StepResult")
                results[sid] = step_result
            except Exception as e:
                results[sid] = StepResult(
                    step_id=sid,
                    kind=kind,
                    status=StepStatus.FAILED,
                    summary=str(e) or "failed",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={},
                )
                if self._fail_fast():
                    break

        return RunResult(steps=results)
