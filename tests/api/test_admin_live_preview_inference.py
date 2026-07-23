import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import main as api_main  # noqa: E402


DATASET_SLUG = "controlled-private-dataset"
ACTIVE_RELEASE = "controlled-release"
SUBMITTED_INVALID_VALUE = 424242
SAFE_ISSUE_KEYS = {"error_code", "message", "field", "violation"}
SUPPORTED_VIOLATIONS = {"missing_required_field", "type_mismatch", "domain_violation"}


def _post_json(path: str, payload):
    """Exercise the real FastAPI ASGI router without an optional HTTP client dependency."""
    request_body = json.dumps(payload).encode("utf-8")
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": request_body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(request_body)).encode("ascii"))],
        "client": ("test-client", 50000),
        "server": ("test-server", 80),
    }
    asyncio.run(api_main.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(body), body.decode("utf-8")


def _install_controlled_read_only_dependencies(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda dataset_slug: SimpleNamespace(dataset_slug=dataset_slug, active_release=ACTIVE_RELEASE),
    )
    monkeypatch.setattr(
        api_main,
        "load_contract",
        lambda active_release: {
            "features": [
                {
                    "name": "MonthlyCharges",
                    "type": "numeric",
                    "required": True,
                    "domain_constraints": {"min": 0, "max": 100},
                }
            ]
        },
    )


def test_private_admin_route_returns_bounded_structured_invalid_payload(monkeypatch):
    _install_controlled_read_only_dependencies(monkeypatch)

    status_code, body, response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", {"MonthlyCharges": SUBMITTED_INVALID_VALUE}
    )

    assert status_code == 422
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert isinstance(body["errors"], list) and body["errors"]
    assert all(set(issue) == SAFE_ISSUE_KEYS for issue in body["errors"])
    assert all(issue["field"] == "MonthlyCharges" for issue in body["errors"])
    assert all(issue["violation"] in SUPPORTED_VIOLATIONS for issue in body["errors"])

    serialized = response_text
    assert str(SUBMITTED_INVALID_VALUE) not in serialized
    for forbidden in ("traceback", "exception", "active_release", ACTIVE_RELEASE, "bundle", "credential", "authorization"):
        assert forbidden not in serialized.lower()


def test_private_admin_route_bounds_a_malformed_top_level_payload(monkeypatch):
    _install_controlled_read_only_dependencies(monkeypatch)

    status_code, body, response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", [{"MonthlyCharges": SUBMITTED_INVALID_VALUE}]
    )

    assert status_code == 422
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert body["errors"] == [
        {
            "error_code": "TYPE_MISMATCH",
            "message": "The inference payload must be a JSON object.",
            "field": "payload",
            "violation": "type_mismatch",
        }
    ]
    assert str(SUBMITTED_INVALID_VALUE) not in response_text


def test_private_admin_route_preserves_not_found_concealment_when_unauthorized(monkeypatch):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    resolution_attempted = False

    def fail_if_resolved(_dataset_slug):
        nonlocal resolution_attempted
        resolution_attempted = True
        raise AssertionError("unauthorized requests must not resolve datasets")

    monkeypatch.setattr(api_main, "resolve_dataset", fail_if_resolved)

    status_code, body, _response_text = _post_json(
        f"/admin/datasets/{DATASET_SLUG}/inference", {"MonthlyCharges": SUBMITTED_INVALID_VALUE}
    )

    assert status_code == 404
    assert body == {"detail": "Not Found"}
    assert resolution_attempted is False
