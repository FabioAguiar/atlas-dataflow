"""M51-02: composed Admin access boundary.

Every /admin/* route is guarded by two independent, mandatory gates composed
in the single shared predicate ``main._admin_request_authorized``:

1. the ATLAS_ADMIN_ENABLED runtime flag (checked first, short-circuiting), and
2. the M51-01 verified-operator decision, reached through the single seam
   ``main._admin_auth_decision_from_request``.

This module proves, per route (exhaustively, from the live route table), that
any failed gate yields the exact response of an unmatched path, and that only
both gates together let a request through. The predicate itself is never
patched; only the identity seam (or ``admin_auth._DEFAULT_VERIFIER`` in the
real-verifier section) is replaced. All tokens, keys and identifiers below
are synthetic and generated locally; nothing touches the network.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_NOT_FOUND_BODY = {"detail": "Not Found"}

# The complete, explicit /admin route inventory. A newly added /admin route
# that is not listed here (and therefore not covered by the denial matrix
# below) fails test_admin_route_inventory_is_exactly_the_guarded_set.
_EXPECTED_ADMIN_ROUTES = [
    ("POST", "/admin/datasets/{dataset_slug}/inference"),
    ("GET", "/admin/runs"),
    ("DELETE", "/admin/runs/{run_id}"),
    ("POST", "/admin/runs/{run_id}/promote"),
    ("GET", "/admin/settings"),
    ("PUT", "/admin/settings"),
    ("GET", "/admin/datasets"),
    ("DELETE", "/admin/datasets/{dataset_slug}"),
    ("PUT", "/admin/datasets/{dataset_slug}/slug"),
    ("GET", "/admin/datasets/{dataset_slug}/profile-draft"),
    ("PUT", "/admin/datasets/{dataset_slug}/profile-draft"),
    ("PUT", "/admin/datasets/{dataset_slug}/publish"),
    ("POST", "/admin/datasets/{dataset_slug}/home-card-image"),
    ("PUT", "/admin/datasets/{dataset_slug}/visibility"),
    ("GET", "/admin/datasets/{dataset_slug}/publication-state"),
    ("PUT", "/admin/datasets/{dataset_slug}/review-status"),
    ("GET", "/admin/datasets/{dataset_slug}/views/{view_id}/customization"),
    ("PUT", "/admin/datasets/{dataset_slug}/views/{view_id}/customization"),
    ("GET", "/admin/datasets/{dataset_slug}/authoring-context"),
]

_HOME_CARD_ROUTE = ("POST", "/admin/datasets/{dataset_slug}/home-card-image")


def _live_admin_routes() -> list[tuple[str, str]]:
    found = []
    for route in api_main.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/admin"):
            for method in sorted(route.methods - {"HEAD"}):
                found.append((method, path))
    return found


def _concrete_path(template: str) -> str:
    return template.replace("{dataset_slug}", "sample-dataset").replace("{run_id}", "run-1").replace(
        "{view_id}", "view-1"
    )


def _send(client: TestClient, method: str, template: str, headers: dict | None = None):
    """Minimal well-formed request: valid JSON bodies so FastAPI body
    validation cannot pre-empt the in-handler guard."""
    path = _concrete_path(template)
    if (method, template) == _HOME_CARD_ROUTE:
        return client.request(
            method, path, content=b"x", headers={"content-type": "image/png", "x-file-name": "a.png", **(headers or {})}
        )
    if method in ("POST", "PUT"):
        return client.request(method, path, json={}, headers=headers)
    return client.request(method, path, headers=headers)


def _seam(monkeypatch, behavior):
    calls = {"count": 0}

    def _fake(request):
        calls["count"] += 1
        return behavior(request)

    monkeypatch.setattr(api_main, "_admin_auth_decision_from_request", _fake)
    return calls


def _raise(exc):
    def _behavior(request):
        raise exc

    return _behavior


def _decision(authorized):
    return lambda request: SimpleNamespace(authorized=authorized, reason="test")


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


def _unmatched_response(client: TestClient):
    return client.get("/definitely-not-a-route")


# --- Route inventory ---------------------------------------------------


def test_admin_route_inventory_is_exactly_the_guarded_set():
    live = _live_admin_routes()
    assert len(live) == 19
    assert sorted(live) == sorted(_EXPECTED_ADMIN_ROUTES)


# --- Denial matrix (exhaustive per route) ------------------------------

_DENIAL_MODES = ["runtime_off", "unauthorized", "seam_exception", "seam_import_error", "authorized_not_exactly_true"]


def _arrange_denial(monkeypatch, mode: str):
    if mode == "runtime_off":
        monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
        return _seam(monkeypatch, _decision(True))
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    if mode == "unauthorized":
        return _seam(monkeypatch, _decision(False))
    if mode == "seam_exception":
        return _seam(monkeypatch, _raise(RuntimeError("boom")))
    if mode == "seam_import_error":
        return _seam(monkeypatch, _raise(ImportError("No module named 'jwt'")))
    if mode == "authorized_not_exactly_true":
        return _seam(monkeypatch, _decision("yes"))
    raise AssertionError(mode)


@pytest.mark.parametrize("mode", _DENIAL_MODES)
@pytest.mark.parametrize("method,template", _EXPECTED_ADMIN_ROUTES)
def test_every_admin_route_denies_with_the_unmatched_route_response(monkeypatch, client, mode, method, template):
    _arrange_denial(monkeypatch, mode)
    unmatched = _unmatched_response(client)
    response = _send(client, method, template)
    assert response.status_code == 404
    assert response.json() == _NOT_FOUND_BODY
    assert response.status_code == unmatched.status_code
    assert response.content == unmatched.content


@pytest.mark.parametrize("value", ["false", "0", "off", "", "no"])
def test_runtime_flag_values_other_than_enabled_deny_even_with_valid_identity(monkeypatch, client, value):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", value)
    _seam(monkeypatch, _decision(True))
    for method, template in _EXPECTED_ADMIN_ROUTES:
        response = _send(client, method, template)
        assert response.status_code == 404
        assert response.json() == _NOT_FOUND_BODY


@pytest.mark.parametrize("method,template", _EXPECTED_ADMIN_ROUTES)
def test_verifier_seam_is_never_called_when_runtime_is_disabled(monkeypatch, client, method, template):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    calls = _seam(monkeypatch, _decision(True))
    _send(client, method, template)
    assert calls["count"] == 0


@pytest.mark.parametrize("method,template", _EXPECTED_ADMIN_ROUTES)
def test_both_gates_together_let_every_route_past_the_guard(monkeypatch, client, method, template):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    calls = _seam(monkeypatch, _decision(True))
    _send(client, method, template)
    assert calls["count"] == 1


# --- Predicate composition ---------------------------------------------


def test_predicate_short_circuits_on_runtime_flag(monkeypatch):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    calls = _seam(monkeypatch, _decision(True))
    assert api_main._admin_request_authorized(object()) is False
    assert calls["count"] == 0


def test_predicate_requires_authorized_to_be_exactly_true(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    for value, expected in [(True, True), (False, False), (1, False), ("true", False), (None, False)]:
        _seam(monkeypatch, _decision(value))
        assert api_main._admin_request_authorized(object()) is expected


def test_predicate_fails_closed_on_any_exception(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    for exc in (RuntimeError("x"), ImportError("jwt"), ValueError("y")):
        _seam(monkeypatch, _raise(exc))
        assert api_main._admin_request_authorized(object()) is False


def test_predicate_fails_closed_when_decision_lacks_authorized_attribute(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    _seam(monkeypatch, lambda request: object())
    assert api_main._admin_request_authorized(object()) is False


# --- Async home-card-image ordering ------------------------------------


def _drive_asgi(headers: list[tuple[bytes, bytes]], chunks: list[bytes]):
    state = {"receive_calls": 0, "sent": []}
    queue = list(chunks)

    async def receive():
        state["receive_calls"] += 1
        if queue:
            body = queue.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(queue)}
        return {"type": "http.disconnect"}

    async def send(message):
        state["sent"].append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/admin/datasets/sample-dataset/home-card-image",
        "raw_path": b"/admin/datasets/sample-dataset/home-card-image",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    asyncio.run(api_main.app(scope, receive, send))
    start = next(m for m in state["sent"] if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in state["sent"] if m["type"] == "http.response.body")
    return state, start["status"], body


def test_home_card_image_denial_precedes_any_body_read(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    _seam(monkeypatch, _decision(False))
    state, status, body = _drive_asgi(
        [(b"content-type", b"image/png"), (b"x-file-name", b"a.png")],
        [b"x" * 1024, b"y" * 1024],
    )
    assert status == 404
    assert json.loads(body) == _NOT_FOUND_BODY
    assert state["receive_calls"] == 0


def test_home_card_image_predicate_is_evaluated_in_a_worker_thread(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    observed = {}

    def _behavior(request):
        try:
            asyncio.get_running_loop()
            observed["on_event_loop"] = True
        except RuntimeError:
            observed["on_event_loop"] = False
        return SimpleNamespace(authorized=False, reason="test")

    _seam(monkeypatch, _behavior)
    _drive_asgi([(b"content-type", b"image/png")], [b"x"])
    assert observed == {"on_event_loop": False}


# --- Public routes unchanged -------------------------------------------


def test_public_routes_need_no_authorization_and_never_consult_the_verifier(monkeypatch, client):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    calls = _seam(monkeypatch, _decision(False))

    assert client.get("/health").status_code == 200
    datasets = client.get("/datasets")
    assert datasets.status_code == 200
    # /media/home-cards/* keeps using the same not-found helper for an
    # unknown file, with no Authorization header involved.
    media = client.get("/media/home-cards/does-not-exist.png")
    assert media.status_code == 404
    assert media.json() == _NOT_FOUND_BODY
    assert calls["count"] == 0


# --- Real verifier integration (needs PyJWT + cryptography) ------------


def _real_verifier_fixtures():
    pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from jwt.algorithms import ECAlgorithm

    import admin_auth

    issuer = "https://example-project.supabase.co/auth/v1"
    audience = "authenticated"
    jwks_url = "https://example-project.supabase.co/auth/v1/.well-known/jwks.json"
    operator_id = "00000000-0000-4000-8000-000000000000"
    other_id = "11111111-1111-4111-8111-111111111111"

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "boundary-kid", "alg": "ES256", "use": "sig"})

    def make_token(**overrides):
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": operator_id,
            "exp": now + 3600,
            "iat": now,
            "is_anonymous": False,
            "app_metadata": {"atlas_role": "admin"},
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "boundary-kid"})

    env = {
        "ATLAS_SUPABASE_JWT_ISSUER": issuer,
        "ATLAS_SUPABASE_JWT_AUDIENCE": audience,
        "ATLAS_SUPABASE_JWKS_URL": jwks_url,
        "ATLAS_ADMIN_USER_ID": operator_id,
    }
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=lambda url: {"boundary-kid": public_jwk}, clock=lambda: 0.0)
    return admin_auth, env, verifier, make_token, other_id, issuer


def _install_real_verifier(monkeypatch):
    admin_auth, env, verifier, make_token, other_id, issuer = _real_verifier_fixtures()
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(admin_auth, "_DEFAULT_VERIFIER", verifier)
    return make_token, other_id, issuer


def test_real_verifier_valid_operator_token_passes_only_with_runtime_enabled(monkeypatch, client):
    make_token, _, _ = _install_real_verifier(monkeypatch)
    headers = {"Authorization": f"Bearer {make_token()}"}

    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    allowed = client.get("/admin/settings", headers=headers)
    assert allowed.json() != _NOT_FOUND_BODY

    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    denied = client.get("/admin/settings", headers=headers)
    assert denied.status_code == 404
    assert denied.json() == _NOT_FOUND_BODY


def test_real_verifier_denies_wrong_sub_wrong_issuer_and_missing_authorization(monkeypatch, client):
    make_token, other_id, _ = _install_real_verifier(monkeypatch)
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")

    cases = [
        {"Authorization": f"Bearer {make_token(sub=other_id)}"},
        {"Authorization": f"Bearer {make_token(iss='https://other.example.invalid/auth/v1')}"},
        {"Authorization": "Bearer not-a-jwt"},
        {},
    ]
    unmatched = _unmatched_response(client)
    for headers in cases:
        response = client.get("/admin/settings", headers=headers)
        assert response.status_code == 404
        assert response.content == unmatched.content
