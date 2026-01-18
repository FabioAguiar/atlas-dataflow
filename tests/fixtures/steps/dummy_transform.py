"""
Dummy Transform Step — Atlas DataFlow (Issue #6)

Transformação determinística baseada no contrato:
- primeira feature numérica em contract.features.numeric
- cria coluna derivada '<feature>_x2' = 2 * feature
"""

from __future__ import annotations

from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


class DummyTransformStep:
    id = "dummy.transform"
    kind = StepKind.TRANSFORM
    depends_on = ["dummy.ingest"]

    def run(self, ctx) -> StepResult:
        rows = ctx.get_artifact("data.raw_rows")

        numeric = (ctx.contract.get("features", {}) or {}).get("numeric", []) or []
        if not numeric:
            raise ValueError("contract.features.numeric must contain at least one feature")

        base = numeric[0]
        derived = f"{base}_x2"

        out = []
        for r in rows:
            nr = dict(r)
            try:
                v = float(r.get(base, 0))
            except Exception:
                v = 0.0
            nr[derived] = v * 2
            out.append(nr)

        ctx.set_artifact("data.transformed_rows", out)
        ctx.set_artifact("data.derived_feature", derived)
        ctx.log(step_id=self.id, level="info", message="transform applied", rows=len(out), derived=derived)

        return StepResult(
            step_id=self.id,
            kind=self.kind,
            status=StepStatus.SUCCESS,
            summary=f"transformed {len(out)} rows",
            metrics={"rows": len(out), "derived_feature": derived},
            warnings=[],
            artifacts={},
            payload={},
        )
