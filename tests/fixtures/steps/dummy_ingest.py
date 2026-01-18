"""
Dummy Ingest Step — Atlas DataFlow (Issue #6)

Carrega um CSV sintético (path via ctx.meta['dataset_path']) e coloca
as linhas no artifact store do RunContext.
"""

from __future__ import annotations

import csv
from pathlib import Path

from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


class DummyIngestStep:
    id = "dummy.ingest"
    kind = StepKind.DIAGNOSTIC
    depends_on = []

    def run(self, ctx) -> StepResult:
        dataset_path = ctx.meta.get("dataset_path")
        if not isinstance(dataset_path, Path):
            raise ValueError("ctx.meta['dataset_path'] must be a pathlib.Path")

        with dataset_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]

        ctx.set_artifact("data.raw_rows", rows)
        ctx.log(step_id=self.id, level="info", message="dataset loaded", rows=len(rows))

        return StepResult(
            step_id=self.id,
            kind=self.kind,
            status=StepStatus.SUCCESS,
            summary=f"ingested {len(rows)} rows",
            metrics={"rows": len(rows)},
            warnings=[],
            artifacts={"dataset_path": str(dataset_path)},
            payload={},
        )
