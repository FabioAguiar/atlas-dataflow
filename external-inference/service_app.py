"""FastAPI application for the isolated external-inference service.

Owns exactly three internal routes (POST /predict, GET /live, GET /ready).
Never public-facing, never reached by web, and never a startup dependency of
the Atlas api service -- see docker-compose.yml/docker-compose.prod.yml. The
Atlas api service (api/external_inference_client.py) is the sole caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import runtime_loader as rl

app = FastAPI()

_CONTRACTS_DIR = Path(__file__).parent / "contracts"
_REQUEST_SCHEMA = json.loads((_CONTRACTS_DIR / "external-inference-request.schema.json").read_text(encoding="utf-8"))
_RESULT_SCHEMA = json.loads((_CONTRACTS_DIR / "external-inference-result.schema.json").read_text(encoding="utf-8"))


def _result_envelope(
    *,
    status: str,
    runtime_compatibility_status: str | None,
    diagnostic_code: str | None,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    envelope = {
        "contract_version": "external_inference_result.v1",
        "status": status,
        "runtime_compatibility_status": runtime_compatibility_status,
        "diagnostic_code": diagnostic_code,
        "result": result,
    }
    jsonschema.validate(envelope, _RESULT_SCHEMA)
    return envelope


@app.get("/live")
def live() -> dict:
    """Proves only process/event-loop responsiveness.

    Never imports or invokes release/model loading.
    """

    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Checks packaged release topology and runtime. Never calls joblib.load."""

    try:
        rl.check_releases_root_ready()
    except rl.LoadSafeGateError as exc:
        return {
            "status": "not_ready",
            "runtime_compatibility_status": exc.runtime_compatibility_status,
            "diagnostic_code": exc.diagnostic_code,
        }

    return {
        "status": "ready",
        "runtime_compatibility_status": "compatible",
        "diagnostic_code": None,
    }


@app.post("/predict")
async def predict(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content=_result_envelope(
                status="failed",
                runtime_compatibility_status=None,
                diagnostic_code=rl.DIAGNOSTIC_RESULT_VALIDATION_FAILED,
                result=None,
            ),
        )

    try:
        jsonschema.validate(body, _REQUEST_SCHEMA)
    except jsonschema.ValidationError:
        return JSONResponse(
            status_code=422,
            content=_result_envelope(
                status="failed",
                runtime_compatibility_status=None,
                diagnostic_code=rl.DIAGNOSTIC_RESULT_VALIDATION_FAILED,
                result=None,
            ),
        )

    try:
        result_payload = rl.execute_governed_external_prediction(body)
    except rl.LoadSafeGateError as exc:
        return JSONResponse(
            status_code=200,
            content=_result_envelope(
                status="failed",
                runtime_compatibility_status=exc.runtime_compatibility_status,
                diagnostic_code=exc.diagnostic_code,
                result=None,
            ),
        )

    return JSONResponse(
        status_code=200,
        content=_result_envelope(
            status="ok",
            runtime_compatibility_status="compatible",
            diagnostic_code=None,
            result=result_payload,
        ),
    )
