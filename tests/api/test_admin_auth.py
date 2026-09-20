import base64
import hashlib
import hmac
import http.server
import json
import sys
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, rsa  # noqa: E402

import jwt  # noqa: E402
from jwt.algorithms import ECAlgorithm, RSAAlgorithm  # noqa: E402

import admin_auth  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402

_ISSUER = "https://example-project.supabase.co/auth/v1"
_AUDIENCE = "authenticated"
_JWKS_URL = "https://example-project.supabase.co/auth/v1/.well-known/jwks.json"
_ADMIN_USER_ID = "00000000-0000-4000-8000-000000000000"

_CONFIG_VARS = (
    "ATLAS_SUPABASE_JWT_ISSUER",
    "ATLAS_SUPABASE_JWT_AUDIENCE",
    "ATLAS_SUPABASE_JWKS_URL",
    "ATLAS_ADMIN_USER_ID",
)
_PRIVATE_HTTP_ENV = "ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP"

_EC_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_EC_PUBLIC_JWK = ECAlgorithm.to_jwk(_EC_PRIVATE_KEY.public_key(), as_dict=True)
_EC_PUBLIC_JWK["kid"] = "test-ec-kid"
_EC_PUBLIC_JWK["alg"] = "ES256"
_EC_PUBLIC_JWK["use"] = "sig"

_EC_PRIVATE_KEY_OTHER = ec.generate_private_key(ec.SECP256R1())

_RSA_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_RSA_PUBLIC_JWK = RSAAlgorithm.to_jwk(_RSA_PRIVATE_KEY.public_key(), as_dict=True)
_RSA_PUBLIC_JWK["kid"] = "test-rsa-kid"
_RSA_PUBLIC_JWK["alg"] = "RS256"
_RSA_PUBLIC_JWK["use"] = "sig"


def _set_config(monkeypatch, **overrides) -> None:
    values = {
        "ATLAS_SUPABASE_JWT_ISSUER": _ISSUER,
        "ATLAS_SUPABASE_JWT_AUDIENCE": _AUDIENCE,
        "ATLAS_SUPABASE_JWKS_URL": _JWKS_URL,
        "ATLAS_ADMIN_USER_ID": _ADMIN_USER_ID,
    }
    values.update(overrides)
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _valid_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": _ADMIN_USER_ID,
        "exp": now + 3600,
        "iat": now,
        "is_anonymous": False,
        "app_metadata": {"atlas_role": "admin"},
    }
    claims.update(overrides)
    return claims


def _make_token(*, key, algorithm: str, kid: Optional[str], claims: dict) -> str:
    headers = {}
    if kid is not None:
        headers["kid"] = kid
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _forge_hs256_token(claims: dict, secret: bytes, *, kid: str) -> str:
    header = {"alg": "HS256", "typ": "JWT", "kid": kid}
    signing_input = (
        _b64url(json.dumps(header).encode()) + "." + _b64url(json.dumps(claims).encode())
    )
    signature = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
    return signing_input + "." + _b64url(signature)


def _verifier_with_jwks(jwks: dict, clock_value: float = 0.0) -> admin_auth.AdminAuthVerifier:
    return admin_auth.AdminAuthVerifier(fetch_jwks=lambda url: jwks, clock=lambda: clock_value)


class _FakeJWKSFetcher:
    def __init__(self, responses: Optional[dict] = None, error: Optional[Exception] = None):
        self.calls = 0
        self._responses = responses
        self._error = error

    def __call__(self, url: str) -> dict:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._responses


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _make_request(headers: dict) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": "GET", "path": "/admin/x", "headers": encoded_headers}
    return Request(scope)


# --- Positive matrix ---------------------------------------------------


def test_valid_es256_token_is_authorized(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(True, "ok")


def test_valid_rs256_token_is_authorized(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_RSA_PRIVATE_KEY, algorithm="RS256", kid="test-rsa-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-rsa-kid": _RSA_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(True, "ok")


def test_audience_as_list_containing_expected_value_is_authorized(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(aud=[_AUDIENCE, "other-audience"])
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(True, "ok")


def test_admin_enabled_env_does_not_affect_verifier_decision(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})

    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    assert verifier.evaluate(f"Bearer {token}").authorized is True

    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    assert verifier.evaluate(f"Bearer {token}").authorized is True

    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "false")
    assert verifier.evaluate(f"Bearer {token}").authorized is True


# --- Configuration failures ---------------------------------------------


def test_each_individual_config_variable_absent_denies(monkeypatch):
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    for missing in _CONFIG_VARS:
        _set_config(monkeypatch)
        monkeypatch.delenv(missing, raising=False)
        decision = verifier.evaluate(f"Bearer {token}")
        assert decision.authorized is False, f"expected denial with {missing} absent"
        assert decision.reason == "configuration_missing"


def test_all_config_absent_denies(monkeypatch):
    for name in _CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "configuration_missing")


def test_whitespace_or_empty_config_denies(monkeypatch):
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})

    _set_config(monkeypatch, ATLAS_SUPABASE_JWT_ISSUER="   ")
    assert verifier.evaluate(f"Bearer {token}").authorized is False

    _set_config(monkeypatch, ATLAS_ADMIN_USER_ID="")
    assert verifier.evaluate(f"Bearer {token}").authorized is False


def test_non_https_jwks_url_denies(monkeypatch):
    _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL="http://example-project.supabase.co/jwks.json")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision.authorized is False


_PRIVATE_HTTP_URLS = (
    "http://kong:8000/auth/v1/.well-known/jwks.json",
    "http://atlas-supabase-dev-kong/jwks.json",
    "http://10.0.0.5:8000/jwks.json",
    "http://172.18.0.5:8000/jwks.json",
    "http://192.168.1.30:8000/jwks.json",
    "http://127.0.0.1:8000/jwks.json",
    "http://localhost:8000/jwks.json",
    "http://[::1]:8000/jwks.json",
    "http://[fd12:3456::5]:8000/jwks.json",
)
_REJECTED_HTTP_URLS = (
    "http://example.com/jwks.json",
    "http://atlas.example.internal/jwks.json",
    "http://8.8.8.8/jwks.json",
    "http://172.32.0.1/jwks.json",
    "http://169.254.169.254/jwks.json",
    "http://[2001:db8::1]/jwks.json",
    "http://user:pass@kong:8000/jwks.json",
    "http://kong:8000/jwks.json?x=1",
    "http://kong:8000/jwks.json#frag",
    "http://kong:notaport/jwks.json",
    "ftp://kong/jwks.json",
    "http:///jwks.json",
)


def test_private_http_jwks_url_rejected_by_default(monkeypatch):
    monkeypatch.delenv(_PRIVATE_HTTP_ENV, raising=False)
    for url in _PRIVATE_HTTP_URLS:
        _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL=url)
        assert admin_auth._load_configuration() is None, url
    for value in ("", "false", "1", "yes"):
        monkeypatch.setenv(_PRIVATE_HTTP_ENV, value)
        _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL=_PRIVATE_HTTP_URLS[0])
        assert admin_auth._load_configuration() is None, value


def test_private_http_opt_in_accepts_closed_private_host_class(monkeypatch):
    monkeypatch.setenv(_PRIVATE_HTTP_ENV, "true")
    for url in _PRIVATE_HTTP_URLS:
        _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL=url)
        config = admin_auth._load_configuration()
        assert config is not None and config.jwks_url == url, url


def test_private_http_opt_in_rejects_public_and_malformed_urls(monkeypatch):
    monkeypatch.setenv(_PRIVATE_HTTP_ENV, "true")
    for url in _REJECTED_HTTP_URLS:
        _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL=url)
        assert admin_auth._load_configuration() is None, url


def test_https_jwks_url_accepted_with_and_without_opt_in(monkeypatch):
    for value in (None, "true"):
        if value is None:
            monkeypatch.delenv(_PRIVATE_HTTP_ENV, raising=False)
        else:
            monkeypatch.setenv(_PRIVATE_HTTP_ENV, value)
        _set_config(monkeypatch)
        assert admin_auth._load_configuration() is not None
    _set_config(monkeypatch, ATLAS_SUPABASE_JWKS_URL="https://u:p@example.com/jwks.json")
    assert admin_auth._load_configuration() is None


def test_issuer_is_independent_of_jwks_transport_host(monkeypatch):
    monkeypatch.setenv(_PRIVATE_HTTP_ENV, "true")
    _set_config(
        monkeypatch,
        ATLAS_SUPABASE_JWT_ISSUER="http://localhost:18000/auth/v1",
        ATLAS_SUPABASE_JWKS_URL="http://kong:8000/auth/v1/.well-known/jwks.json",
    )
    urls = []

    def fetch(url):
        urls.append(url)
        return {"test-ec-kid": _EC_PUBLIC_JWK}

    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetch, clock=lambda: 0.0)
    good = _make_token(
        key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid",
        claims=_valid_claims(iss="http://localhost:18000/auth/v1"),
    )
    assert verifier.evaluate(f"Bearer {good}").authorized is True
    assert urls == ["http://kong:8000/auth/v1/.well-known/jwks.json"]
    # The JWKS host is not accepted as an issuer.
    bad = _make_token(
        key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid",
        claims=_valid_claims(iss="http://kong:8000/auth/v1"),
    )
    assert verifier.evaluate(f"Bearer {bad}") == admin_auth.AdminAuthDecision(False, "issuer_mismatch")


def test_fetch_jwks_via_urllib_refuses_private_http_without_opt_in(monkeypatch):
    monkeypatch.delenv(_PRIVATE_HTTP_ENV, raising=False)
    try:
        admin_auth._fetch_jwks_via_urllib("http://127.0.0.1:1/jwks.json")
        assert False, "expected ValueError"
    except ValueError:
        pass


class _JwksServer:
    def __init__(self, handler_cls):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def _send_jwks(handler) -> None:
    body = json.dumps({"keys": [_EC_PUBLIC_JWK]}).encode()
    handler.send_response(200)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def test_fetch_jwks_via_urllib_fetches_over_opted_in_private_http(monkeypatch):
    monkeypatch.setenv(_PRIVATE_HTTP_ENV, "true")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            _send_jwks(self)

        def log_message(self, *args):
            pass

    with _JwksServer(Handler) as base:
        assert set(admin_auth._fetch_jwks_via_urllib(f"{base}/jwks.json")) == {"test-ec-kid"}


def test_fetch_jwks_via_urllib_refuses_redirects(monkeypatch):
    monkeypatch.setenv(_PRIVATE_HTTP_ENV, "true")
    hits = {"target": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/target":
                hits["target"] += 1
                _send_jwks(self)
            else:
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()

        def log_message(self, *args):
            pass

    with _JwksServer(Handler) as base:
        try:
            admin_auth._fetch_jwks_via_urllib(f"{base}/jwks.json")
            assert False, "expected the redirect to fail closed"
        except urllib.error.HTTPError:
            pass
    assert hits["target"] == 0


def test_cold_cache_fetch_does_not_consume_unknown_kid_refresh_allowance(monkeypatch):
    _set_config(monkeypatch)
    clock = _FakeClock(0.0)
    fetcher = _FakeJWKSFetcher(responses={"test-ec-kid": _EC_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=clock)
    unknown = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="rotated-kid", claims=_valid_claims())
    assert verifier.evaluate(f"Bearer {unknown}").authorized is False
    assert fetcher.calls == 1  # cold-cache fetch
    assert verifier.evaluate(f"Bearer {unknown}").authorized is False
    assert fetcher.calls == 2  # the one immediate unknown-kid refresh
    for _ in range(20):
        verifier.evaluate(f"Bearer {unknown}")
    assert fetcher.calls == 2  # bounded within the cooldown


def test_unknown_kid_refresh_picks_up_rotated_key_immediately(monkeypatch):
    _set_config(monkeypatch)
    state = {"jwks": {"test-ec-kid": _EC_PUBLIC_JWK}}
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=lambda url: state["jwks"], clock=_FakeClock(0.0))
    old = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    assert verifier.evaluate(f"Bearer {old}").authorized is True
    state["jwks"] = {"test-ec-kid": _EC_PUBLIC_JWK, "test-rsa-kid": _RSA_PUBLIC_JWK}
    new = _make_token(key=_RSA_PRIVATE_KEY, algorithm="RS256", kid="test-rsa-kid", claims=_valid_claims())
    assert verifier.evaluate(f"Bearer {new}").authorized is True


def test_failed_refresh_backs_off_without_stale_authorization(monkeypatch):
    _set_config(monkeypatch)
    clock = _FakeClock(0.0)
    calls = {"n": 0}

    def fetch(_url):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"test-ec-kid": _EC_PUBLIC_JWK}
        raise TimeoutError("jwks unreachable")

    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetch, clock=clock)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    assert verifier.evaluate(f"Bearer {token}").authorized is True
    clock.advance(601.0)
    for _ in range(5):
        assert verifier.evaluate(f"Bearer {token}").authorized is False
    assert calls["n"] == 2  # one failed attempt, the rest throttled
    clock.advance(admin_auth._JWKS_FAILED_REFRESH_COOLDOWN_SECONDS)
    assert verifier.evaluate(f"Bearer {token}").authorized is False
    assert calls["n"] == 3


# --- Header / token structural failures ----------------------------------


def test_absent_authorization_header_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(None)
    assert decision == admin_auth.AdminAuthDecision(False, "authorization_header_missing")


def test_non_bearer_scheme_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate("Basic dXNlcjpwYXNz")
    assert decision.authorized is False


def test_empty_bearer_token_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate("Bearer ")
    assert decision.authorized is False


def test_authorization_header_with_extra_parts_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate("Bearer abc.def.ghi extra-part")
    assert decision.authorized is False


def test_malformed_jwt_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate("Bearer not-a-jwt")
    assert decision == admin_auth.AdminAuthDecision(False, "token_malformed")


def test_jwt_with_too_many_segments_denies(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate("Bearer a.b.c.d")
    assert decision.authorized is False


# --- Algorithm failures ---------------------------------------------------


def test_alg_none_denies(monkeypatch):
    _set_config(monkeypatch)
    header_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT", "kid": "test-ec-kid"}).encode("utf-8")
    ).rstrip(b"=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(_valid_claims()).encode("utf-8")).rstrip(b"=")
    token = (header_b64 + b"." + payload_b64 + b".").decode("ascii")
    fetcher = _FakeJWKSFetcher(responses={"test-ec-kid": _EC_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "algorithm_not_allowed")
    assert fetcher.calls == 0


def test_algorithm_outside_allowlist_denies(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_RSA_PRIVATE_KEY, algorithm="PS256", kid="test-rsa-kid", claims=_valid_claims())
    fetcher = _FakeJWKSFetcher(responses={"test-rsa-kid": _RSA_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "algorithm_not_allowed")
    assert fetcher.calls == 0


def test_hs256_signed_with_public_key_material_denies_algorithm_confusion(monkeypatch):
    _set_config(monkeypatch)
    public_pem = _RSA_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # Hand-built: PyJWT >= 2.14 refuses PEM public material as an HMAC secret,
    # so the malicious HS256-shaped token is assembled without PyJWT.
    token = _forge_hs256_token(_valid_claims(), public_pem, kid="test-rsa-kid")
    fetcher = _FakeJWKSFetcher(responses={"test-rsa-kid": _RSA_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "algorithm_not_allowed")
    assert fetcher.calls == 0


# --- kid / JWKS failures ---------------------------------------------------


def test_missing_kid_denies(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid=None, claims=_valid_claims())
    fetcher = _FakeJWKSFetcher(responses={"test-ec-kid": _EC_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "kid_missing")
    assert fetcher.calls == 0


def test_jwks_fetch_raising_denies(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    fetcher = _FakeJWKSFetcher(error=TimeoutError("jwks unreachable"))
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "key_unavailable")


def test_jwks_response_missing_keys_denies(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    fetcher = _FakeJWKSFetcher(responses={})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=lambda: 0.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision.authorized is False


def test_unknown_kid_refreshes_once_then_cooldown_blocks_further_refresh(monkeypatch):
    _set_config(monkeypatch)
    clock = _FakeClock(0.0)
    fetcher = _FakeJWKSFetcher(responses={"test-ec-kid": _EC_PUBLIC_JWK})
    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetcher, clock=clock)

    known_token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    assert verifier.evaluate(f"Bearer {known_token}").authorized is True
    assert fetcher.calls == 1

    unknown_token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="unknown-kid", claims=_valid_claims())
    decision_unknown = verifier.evaluate(f"Bearer {unknown_token}")
    assert decision_unknown.authorized is False
    assert fetcher.calls == 2

    decision_unknown_again = verifier.evaluate(f"Bearer {unknown_token}")
    assert decision_unknown_again.authorized is False
    assert fetcher.calls == 2

    clock.advance(60.0)
    decision_after_cooldown = verifier.evaluate(f"Bearer {unknown_token}")
    assert decision_after_cooldown.authorized is False
    assert fetcher.calls == 3


def test_expired_cache_with_failed_refresh_denies(monkeypatch):
    _set_config(monkeypatch)
    clock = _FakeClock(0.0)
    call_count = {"n": 0}

    def fetch(_url):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"test-ec-kid": _EC_PUBLIC_JWK}
        raise TimeoutError("jwks unreachable")

    verifier = admin_auth.AdminAuthVerifier(fetch_jwks=fetch, clock=clock)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())

    assert verifier.evaluate(f"Bearer {token}").authorized is True

    clock.advance(601.0)
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision.authorized is False


def test_fetch_jwks_via_urllib_rejects_non_https_url():
    try:
        admin_auth._fetch_jwks_via_urllib("http://example-project.supabase.co/jwks.json")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fetch_jwks_via_urllib_raises_on_non_json_response(monkeypatch):
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n):
            return b"not json"

    monkeypatch.setattr(admin_auth._JWKS_OPENER, "open", lambda *a, **k: _FakeResponse())
    try:
        admin_auth._fetch_jwks_via_urllib(_JWKS_URL)
        assert False, "expected an exception for non-JSON response"
    except Exception:
        pass


def test_fetch_jwks_via_urllib_raises_when_keys_list_missing(monkeypatch):
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n):
            return json.dumps({"not_keys": []}).encode("utf-8")

    monkeypatch.setattr(admin_auth._JWKS_OPENER, "open", lambda *a, **k: _FakeResponse())
    try:
        admin_auth._fetch_jwks_via_urllib(_JWKS_URL)
        assert False, "expected ValueError for missing keys list"
    except ValueError:
        pass


def test_fetch_jwks_via_urllib_raises_when_response_oversized(monkeypatch):
    oversized = json.dumps({"keys": [{"kid": "x", "kty": "EC", "pad": "a" * admin_auth._JWKS_MAX_RESPONSE_BYTES}]}).encode("utf-8")

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n):
            return oversized[:n]

    monkeypatch.setattr(admin_auth._JWKS_OPENER, "open", lambda *a, **k: _FakeResponse())
    try:
        admin_auth._fetch_jwks_via_urllib(_JWKS_URL)
        assert False, "expected ValueError for oversized response"
    except ValueError:
        pass


# --- Signature / claim failures -------------------------------------------


def test_bad_signature_denies(monkeypatch):
    _set_config(monkeypatch)
    token = _make_token(key=_EC_PRIVATE_KEY_OTHER, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "signature_invalid")


def test_wrong_issuer_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(iss="https://not-the-configured-project.supabase.co/auth/v1")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "issuer_mismatch")


def test_wrong_audience_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(aud="some-other-audience")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "audience_mismatch")


def test_expired_token_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(exp=int(time.time()) - 10)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    decision = verifier.evaluate(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(False, "token_expired")


def test_missing_iss_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims()
    del claims["iss"]
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


def test_missing_aud_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims()
    del claims["aud"]
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


def test_missing_sub_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims()
    del claims["sub"]
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


def test_missing_exp_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims()
    del claims["exp"]
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


# --- Identity / role matrix -------------------------------------------------


def test_is_anonymous_true_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(is_anonymous=True)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "anonymous_subject")


def test_is_anonymous_non_boolean_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(is_anonymous="false")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "anonymous_subject")


def test_wrong_sub_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(sub="11111111-1111-4111-8111-111111111111")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "subject_mismatch")


def test_missing_app_metadata_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims()
    del claims["app_metadata"]
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "role_mismatch")


def test_app_metadata_atlas_role_missing_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(app_metadata={})
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "role_mismatch")


def test_app_metadata_atlas_role_wrong_value_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(app_metadata={"atlas_role": "viewer"})
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "role_mismatch")


def test_app_metadata_atlas_role_non_string_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(app_metadata={"atlas_role": 1})
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}") == admin_auth.AdminAuthDecision(False, "role_mismatch")


def test_user_metadata_atlas_role_admin_alone_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(app_metadata={}, user_metadata={"atlas_role": "admin"})
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


def test_top_level_role_admin_alone_denies(monkeypatch):
    _set_config(monkeypatch)
    claims = _valid_claims(app_metadata={}, role="admin")
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=claims)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})
    assert verifier.evaluate(f"Bearer {token}").authorized is False


# --- Sanitization -----------------------------------------------------------


def test_decision_never_exposes_token_or_claim_values(monkeypatch):
    _set_config(monkeypatch)
    verifier = _verifier_with_jwks({"test-ec-kid": _EC_PUBLIC_JWK})

    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    decision = verifier.evaluate(f"Bearer {token}")
    rendered = repr(decision) + decision.reason
    assert token not in rendered
    assert _ADMIN_USER_ID not in rendered

    wrong_sub_claims = _valid_claims(sub="not-the-admin-operator")
    wrong_sub_token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=wrong_sub_claims)
    denial = verifier.evaluate(f"Bearer {wrong_sub_token}")
    denial_rendered = repr(denial) + denial.reason
    assert wrong_sub_token not in denial_rendered
    assert "not-the-admin-operator" not in denial_rendered


# --- Module-level entrypoint and main.py adapter ---------------------------


def test_module_level_evaluate_admin_authorization_delegates_to_default_verifier(monkeypatch):
    _set_config(monkeypatch)
    fake_verifier = admin_auth.AdminAuthVerifier(
        fetch_jwks=lambda url: {"test-ec-kid": _EC_PUBLIC_JWK},
        clock=lambda: 0.0,
    )
    monkeypatch.setattr(admin_auth, "_DEFAULT_VERIFIER", fake_verifier)
    token = _make_token(key=_EC_PRIVATE_KEY, algorithm="ES256", kid="test-ec-kid", claims=_valid_claims())
    decision = admin_auth.evaluate_admin_authorization(f"Bearer {token}")
    assert decision == admin_auth.AdminAuthDecision(True, "ok")


def test_main_module_does_not_import_jwt_or_admin_auth_at_top_level():
    assert "jwt" not in vars(api_main)
    assert "admin_auth" not in vars(api_main)


def test_main_admin_auth_decision_from_request_denies_when_unconfigured(monkeypatch):
    for name in _CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    request = _make_request({})
    decision = api_main._admin_auth_decision_from_request(request)
    assert isinstance(decision, admin_auth.AdminAuthDecision)
    assert decision.authorized is False


def test_main_admin_auth_decision_from_request_is_not_wired_into_admin_request_authorized(monkeypatch):
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    request = _make_request({})
    assert api_main._admin_request_authorized(request) is False
