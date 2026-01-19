from __future__ import annotations

from datetime import datetime, timezone


from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.transform.cast_types_safe import CastTypesSafeStep


def _contract_v1() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "churn", "type": "classification"},
        "target": {"name": "target", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "age",
                "role": "numerical",
                "dtype": "int",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "income",
                "role": "numerical",
                "dtype": "float",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "segment",
                "role": "categorical",
                "dtype": "category",
                "required": True,
                "allowed_null": False,
            },
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }


def test_cast_types_safe_success_and_audit() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1(),
        meta={},
    )

    raw_rows = [
        {"age": "10", "income": "12.5", "segment": "A", "target": "1", "extra": "7"},
        {"age": "x", "income": 3, "segment": " B ", "target": 0, "extra": 1},
    ]
    ctx.set_artifact("data.raw_rows", raw_rows)

    sr = CastTypesSafeStep().run(ctx)

    assert sr.status == StepStatus.SUCCESS
    assert ctx.has_artifact("data.transformed_rows")

    # raw preserved
    assert ctx.get_artifact("data.raw_rows") == raw_rows

    out = ctx.get_artifact("data.transformed_rows")
    assert isinstance(out, list)
    assert len(out) == 2

    # coercions
    assert out[0]["age"] == 10
    assert out[0]["income"] == 12.5
    assert out[0]["segment"] == "A"
    assert out[0]["target"] == 1

    # failures become null
    assert out[1]["age"] is None

    # extra column preserved and not coerced
    assert out[0]["extra"] == "7"
    assert out[1]["extra"] == 1

    impact = sr.payload["impact"]
    assert impact["age"]["after_dtype"] == "int"
    assert impact["age"]["null_after_cast"] == 1
    assert impact["income"]["after_dtype"] == "float"
    assert impact["segment"]["after_dtype"] == "category"


def test_cast_types_safe_does_not_create_missing_columns() -> None:
    ctx = RunContext(
        run_id="test",
        created_at=datetime.now(timezone.utc),
        config={},
        contract=_contract_v1(),
        meta={},
    )

    # income ausente numa linha: step não deve criar a coluna
    ctx.set_artifact("data.raw_rows", [{"age": "1", "segment": "A", "target": "0"}])

    sr = CastTypesSafeStep().run(ctx)
    assert sr.status == StepStatus.SUCCESS

    out = ctx.get_artifact("data.transformed_rows")
    assert "income" not in out[0]
