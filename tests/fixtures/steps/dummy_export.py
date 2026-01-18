"""
Dummy Export Step — Atlas DataFlow (Issue #6)

Exporta para export.csv em tmp_path (ctx.meta['tmp_path']).
"""

from __future__ import annotations

import csv
from pathlib import Path

from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


class DummyExportStep:
    id = "dummy.export"
    kind = StepKind.EXPORT
    depends_on = ["dummy.transform"]

    def run(self, ctx) -> StepResult:
        tmp_path = ctx.meta.get("tmp_path")
        if not isinstance(tmp_path, Path):
            raise ValueError("ctx.meta['tmp_path'] must be a pathlib.Path")

        rows = ctx.get_artifact("data.transformed_rows")
        out_path = tmp_path / "export.csv"

        if rows:
            fieldnames = list(rows[0].keys())
            with out_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
        else:
            with out_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["empty"])

        ctx.log(step_id=self.id, level="info", message="export written", path=str(out_path), rows=len(rows))

        return StepResult(
            step_id=self.id,
            kind=self.kind,
            status=StepStatus.SUCCESS,
            summary=f"exported {len(rows)} rows",
            metrics={"rows": len(rows)},
            warnings=[],
            artifacts={"export_path": str(out_path)},
            payload={},
        )
