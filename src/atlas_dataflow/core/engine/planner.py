from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

from atlas_dataflow.core.pipeline.step import Step


class UnknownDependencyError(ValueError):
    """Raised when a step depends_on references an unknown step id."""


class CycleDetectedError(ValueError):
    """Raised when the dependency graph contains a cycle."""


def plan_execution(steps: Iterable[Step]) -> List[Step]:
    """Validate and produce a deterministic topological execution order.

    Determinism policy (v1):
    - When multiple nodes are available, choose by lexicographic step id.
    """
    step_list = list(steps)
    by_id: Dict[str, Step] = {}
    for s in step_list:
        sid = getattr(s, "id", None)
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("step.id must be a non-empty string")
        if sid in by_id:
            raise ValueError(f"Duplicate step id: {sid}")
        by_id[sid] = s

    # Validate dependencies exist
    deps: Dict[str, List[str]] = {}
    for sid, s in by_id.items():
        d = list(getattr(s, "depends_on", []) or [])
        for dep in d:
            if dep not in by_id:
                raise UnknownDependencyError(f"Step '{sid}' depends on unknown step '{dep}'")
        deps[sid] = d

    # Kahn's algorithm (deterministic)
    incoming_count: Dict[str, int] = {sid: 0 for sid in by_id}
    outgoing: Dict[str, Set[str]] = {sid: set() for sid in by_id}

    for sid, dlist in deps.items():
        incoming_count[sid] = len(dlist)
        for dep in dlist:
            outgoing[dep].add(sid)

    ready: List[str] = sorted([sid for sid, c in incoming_count.items() if c == 0])
    order_ids: List[str] = []

    while ready:
        sid = ready.pop(0)  # smallest lexicographic
        order_ids.append(sid)
        for child in sorted(outgoing[sid]):
            incoming_count[child] -= 1
            if incoming_count[child] == 0:
                # insert and keep list sorted for determinism
                ready.append(child)
                ready.sort()

    if len(order_ids) != len(by_id):
        raise CycleDetectedError("Cycle detected in step dependency graph")

    return [by_id[sid] for sid in order_ids]
