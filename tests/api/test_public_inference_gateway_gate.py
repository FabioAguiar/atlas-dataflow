"""M52-02: dedicated shared gateway credential on the public inference route.

Proves, over the real ASGI app, that POST /datasets/{slug}/inference accepts
only requests carrying X-Atlas-Gateway-Token equal to
ATLAS_INFERENCE_GATEWAY_TOKEN, that every failure is one byte-identical
payload-independent 401, and that no inference work runs before the gate.
All credentials below are synthetic placeholders.
"""

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402

TOKEN_ENV = "ATLAS_INFERENCE_GATEWAY_TOKEN"
HEADER = "X-Atlas-Gateway-Token"
GOOD = "synthetic-gateway-credential-alpha"
GENERIC_BODY = {
    "error_type": "unauthorized",
    "error_code": "GATEWAY_UNAUTHORIZED",
    "message": "The request could not be authorized.",
}
PUBLIC_PATH = "/datasets/example-dataset/inference"
OK_RESULT = {"prediction": "synthetic-ok"}


@pytest.fixture(autouse=True)
def _valid_operator_identity(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_admin_auth_decision_from_request",
        lambda request: SimpleNamespace(authorized=True, reason="test_operator"),
    )


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def tripwires(monkeypatch):
    """Make every downstream stage raise if reached; return the call log."""
    calls = []

    def _trip(name):
        def _raiser(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} reached")

        return _raiser

    for name in (
        "_resolve_public_dataset_detail_access",
        "_resolve_public_prediction_capability",
        "_execute_governed_inference",
    ):
        monkeypatch.setattr(api_main, name, _trip(name))
    return calls


@pytest.fixture
def open_route(monkeypatch):
    """Let an authorized request through to a stubbed governed execution."""
    monkeypatch.setattr(
        api_main,
        "_resolve_public_dataset_detail_access",
        lambda slug: SimpleNamespace(dataset_slug=slug, active_release="rel-1"),
    )
    monkeypatch.setattr(api_main, "_resolve_public_prediction_capability", lambda release: True)
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda slug, release, payload: OK_RESULT)


def _post(client, path=PUBLIC_PATH, headers=None, **kwargs):
    return client.post(path, headers=headers, **kwargs)


# ---------------------------------------------------------------------------
# Accepted credential
# ---------------------------------------------------------------------------

def test_valid_credential_reaches_route_and_returns_route_result(client, monkeypatch, open_route):
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    response = _post(client, headers={HEADER: GOOD}, json={"x": 1})
    assert response.status_code == 200
    assert response.json() == OK_RESULT


def test_configured_value_is_stripped_and_read_at_request_time(client, monkeypatch, open_route):
    monkeypatch.setenv(TOKEN_ENV, f"  {GOOD}  ")
    assert _post(client, headers={HEADER: GOOD}, json={}).status_code == 200
    monkeypatch.setenv(TOKEN_ENV, "synthetic-rotated-credential")
    assert _post(client, headers={HEADER: GOOD}, json={}).status_code == 401
    assert _post(client, headers={HEADER: "synthetic-rotated-credential"}, json={}).status_code == 200


def test_trailing_slash_variant_is_gated(client, monkeypatch, tripwires):
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    response = _post(client, path="/datasets/x/inference/", json={})
    assert response.status_code == 401
    assert response.json() == GENERIC_BODY
    assert tripwires == []


# ---------------------------------------------------------------------------
# Failure matrix: identical status and byte-identical body
# ---------------------------------------------------------------------------

def _failure_cases():
    return {
        "missing": (GOOD, []),
        "empty_header": (GOOD, [(HEADER, "")]),
        "wrong": (GOOD, [(HEADER, "synthetic-wrong")]),
        "wrong_longer": (GOOD, [(HEADER, GOOD + "-extra")]),
        "duplicate": (GOOD, [(HEADER, GOOD), (HEADER, GOOD)]),
        "unconfigured": (None, [(HEADER, GOOD)]),
        "configured_empty": ("", [(HEADER, GOOD)]),
        "configured_whitespace": ("   ", [(HEADER, GOOD)]),
        "configured_empty_header_empty": ("", [(HEADER, "")]),
    }


PAYLOADS = {
    "valid_json": {"json": {"feature": 1}},
    "malformed_json": {"content": b"{not json", "headers_extra": {"Content-Type": "application/json"}},
    "empty_body": {"content": b""},
    "non_object_json": {"json": [1, 2, 3]},
    "oversized": {
        "content": b"x" * (api_main._PAYLOAD_SIZE_LIMIT + 1024),
        "headers_extra": {"Content-Type": "application/json"},
    },
}


def _send(client, case, payload_name, slug="example-dataset"):
    configured, header_items = _failure_cases()[case]
    spec = dict(PAYLOADS[payload_name])
    extra = spec.pop("headers_extra", {})
    headers = [(k.encode(), v.encode()) for k, v in extra.items()]
    headers += [(k.lower().encode(), v.encode()) for k, v in header_items]
    return client.post(f"/datasets/{slug}/inference", headers=headers, **spec)


@pytest.mark.parametrize("payload_name", list(PAYLOADS))
@pytest.mark.parametrize("case", list(_failure_cases()))
def test_every_failure_is_identical_and_payload_independent(client, monkeypatch, tripwires, case, payload_name):
    configured, _ = _failure_cases()[case]
    if configured is None:
        monkeypatch.delenv(TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(TOKEN_ENV, configured)

    response = _send(client, case, payload_name)

    assert response.status_code == 401
    assert response.json() == GENERIC_BODY
    assert "www-authenticate" not in {k.lower() for k in response.headers}
    assert tripwires == []


def test_failure_bodies_are_byte_identical_across_all_causes_and_slugs(client, monkeypatch, tripwires):
    seen = set()
    for case, (configured, _items) in _failure_cases().items():
        if configured is None:
            monkeypatch.delenv(TOKEN_ENV, raising=False)
        else:
            monkeypatch.setenv(TOKEN_ENV, configured)
        for payload_name in PAYLOADS:
            for slug in ("example-dataset", "does-not-exist", "hidden-one"):
                response = _send(client, case, payload_name, slug=slug)
                seen.add((response.status_code, response.content))
    assert len(seen) == 1
    assert tripwires == []


def test_different_length_credentials_yield_same_body(client, monkeypatch, tripwires):
    bodies = set()
    for configured in ("a", GOOD, GOOD * 5):
        monkeypatch.setenv(TOKEN_ENV, configured)
        bodies.add(_post(client, headers={HEADER: "nope"}, json={}).content)
    assert len(bodies) == 1


def test_gate_rejects_oversized_unauthenticated_with_401_not_413(client, monkeypatch, tripwires):
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    response = _post(
        client,
        content=b"x" * (api_main._PAYLOAD_SIZE_LIMIT + 10),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_authenticated_oversized_still_gets_payload_limit(client, monkeypatch, tripwires):
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    response = _post(
        client,
        content=b"x" * (api_main._PAYLOAD_SIZE_LIMIT + 10),
        headers={"Content-Type": "application/json", HEADER: GOOD},
    )
    assert response.status_code == 413
    assert tripwires == []


# ---------------------------------------------------------------------------
# Scope: nothing else is gated
# ---------------------------------------------------------------------------

def test_admin_inference_route_ignores_gateway_credential(client, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "false")
    without_header = client.post("/admin/datasets/example-dataset/inference", json={})
    with_header = client.post("/admin/datasets/example-dataset/inference", json={}, headers={HEADER: GOOD})
    for response in (without_header, with_header):
        assert response.json() != GENERIC_BODY
        assert response.status_code != 401
    assert without_header.status_code == with_header.status_code
    assert without_header.content == with_header.content


def test_other_routes_are_not_gated(client, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/datasets").json() != GENERIC_BODY
    preflight = client.options(
        PUBLIC_PATH,
        headers={"Origin": "http://localhost", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code != 401


def test_cors_allow_headers_stay_content_type_only(client, monkeypatch):
    cors = next(m for m in api_main.app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_headers"] == ["Content-Type"]
    monkeypatch.setenv("CORS_ALLOWED_ORIGIN", "http://localhost")
    preflight = client.options(
        PUBLIC_PATH,
        headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": HEADER,
        },
    )
    advertised = preflight.headers.get("access-control-allow-headers", "").lower()
    assert "x-atlas-gateway-token" not in advertised


def test_middleware_registration_order_is_cors_gate_size_limit():
    order = [m.cls.__name__ for m in api_main.app.user_middleware]
    assert order.index("CORSMiddleware") < order.index("InferenceGatewayCredentialMiddleware")
    assert order.index("InferenceGatewayCredentialMiddleware") < order.index("PayloadSizeLimitMiddleware")


# ---------------------------------------------------------------------------
# No leakage
# ---------------------------------------------------------------------------

def test_values_never_appear_in_responses_or_logs(client, monkeypatch, caplog, open_route):
    presented = "synthetic-presented-credential-beta"
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    caplog.set_level(logging.DEBUG)

    failure = _post(client, headers={HEADER: presented}, json={})
    success = _post(client, headers={HEADER: GOOD}, json={})

    for response in (failure, success):
        text = response.text + repr(dict(response.headers))
        assert GOOD not in text
        assert presented not in text
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert GOOD not in logged
    assert presented not in logged
