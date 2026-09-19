"""Fail-closed Supabase JWT verification for the single Atlas Admin operator.

Establishes the backend identity-verification boundary described by M51-01:
given a bearer token, prove it was issued by the configured Supabase project
for the provisioned non-anonymous operator (``sub`` equal to
``ATLAS_ADMIN_USER_ID``) whose ``app_metadata.atlas_role`` claim is
``"admin"``. Every failure path -- absent or malformed configuration, an
unusable or unreachable JWKS, an unsupported algorithm, a bad signature, a
wrong issuer/audience, an expired token, an anonymous subject, a wrong
subject, or a missing/wrong Atlas role -- denies authorization. Nothing here
is composed with a route or with the independent ``ATLAS_ADMIN_ENABLED``
runtime gate; that composition belongs to M51-02.

Backend configuration is read fresh on every call (never cached at import
time, so callers -- including tests -- can change ``os.environ`` freely):

- ``ATLAS_SUPABASE_JWT_ISSUER``   -- expected ``iss`` claim.
- ``ATLAS_SUPABASE_JWT_AUDIENCE`` -- expected ``aud`` claim.
- ``ATLAS_SUPABASE_JWKS_URL``     -- https-only public JWKS endpoint.
- ``ATLAS_ADMIN_USER_ID``         -- the provisioned operator's Supabase
  user id; the only ``sub`` value that can ever be authorized.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

import jwt

_ALLOWED_ALGORITHMS = ("ES256", "RS256")
_REQUIRED_CLAIMS = ("exp", "iss", "aud", "sub")

_JWKS_TIMEOUT_SECONDS = 3.0
_JWKS_TTL_SECONDS = 600.0
_JWKS_UNKNOWN_KID_COOLDOWN_SECONDS = 60.0
_JWKS_MAX_RESPONSE_BYTES = 1_000_000

_CONFIG_VARS = (
    "ATLAS_SUPABASE_JWT_ISSUER",
    "ATLAS_SUPABASE_JWT_AUDIENCE",
    "ATLAS_SUPABASE_JWKS_URL",
    "ATLAS_ADMIN_USER_ID",
)


@dataclass(frozen=True)
class AdminAuthDecision:
    """A verification outcome. ``reason`` is always one of a fixed,
    sanitized set of category strings -- never a token, claim value, JWKS
    payload, or raw exception message."""

    authorized: bool
    reason: str


@dataclass(frozen=True)
class _AdminAuthConfig:
    issuer: str
    audience: str
    jwks_url: str
    admin_user_id: str


def _load_configuration() -> Optional[_AdminAuthConfig]:
    values: dict[str, str] = {}
    for name in _CONFIG_VARS:
        raw = os.environ.get(name)
        if raw is None:
            return None
        value = raw.strip()
        if not value:
            return None
        values[name] = value

    jwks_url = values["ATLAS_SUPABASE_JWKS_URL"]
    if not jwks_url.lower().startswith("https://"):
        return None

    return _AdminAuthConfig(
        issuer=values["ATLAS_SUPABASE_JWT_ISSUER"],
        audience=values["ATLAS_SUPABASE_JWT_AUDIENCE"],
        jwks_url=jwks_url,
        admin_user_id=values["ATLAS_ADMIN_USER_ID"],
    )


def _parse_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    if not authorization_header:
        return None
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        return None
    token = parts[1].strip()
    return token or None


def _fetch_jwks_via_urllib(jwks_url: str) -> dict[str, Any]:
    if not jwks_url.lower().startswith("https://"):
        raise ValueError("jwks url must use https")
    request = urllib.request.Request(jwks_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_JWKS_TIMEOUT_SECONDS) as response:
        raw = response.read(_JWKS_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _JWKS_MAX_RESPONSE_BYTES:
        raise ValueError("jwks response exceeds size limit")
    payload = json.loads(raw.decode("utf-8"))
    keys = payload.get("keys") if isinstance(payload, dict) else None
    if not isinstance(keys, list) or not keys:
        raise ValueError("jwks response missing usable keys list")
    by_kid: dict[str, Any] = {}
    for jwk in keys:
        if isinstance(jwk, dict):
            kid = jwk.get("kid")
            if isinstance(kid, str) and kid:
                by_kid[kid] = jwk
    if not by_kid:
        raise ValueError("jwks response has no keys with a usable kid")
    return by_kid


class AdminAuthVerifier:
    """Verifies bearer tokens against the M51-01 claim contract.

    ``fetch_jwks`` and ``clock`` are injectable so tests can exercise TTL
    expiry and the unknown-kid refresh cooldown deterministically, without
    real network access or wall-clock sleeps. Production callers use the
    module-level default instance (stdlib ``urllib`` fetch, real
    ``time.monotonic`` clock).
    """

    def __init__(
        self,
        *,
        fetch_jwks: Optional[Callable[[str], dict[str, Any]]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._fetch_jwks = fetch_jwks or _fetch_jwks_via_urllib
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._raw_keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._last_refresh_attempt_at = 0.0

    def evaluate(self, authorization_header: Optional[str]) -> AdminAuthDecision:
        try:
            return self._evaluate(authorization_header)
        except Exception:
            return AdminAuthDecision(False, "verification_error")

    def _evaluate(self, authorization_header: Optional[str]) -> AdminAuthDecision:
        config = _load_configuration()
        if config is None:
            return AdminAuthDecision(False, "configuration_missing")

        token = _parse_bearer_token(authorization_header)
        if token is None:
            return AdminAuthDecision(False, "authorization_header_missing")

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception:
            return AdminAuthDecision(False, "token_malformed")

        algorithm = unverified_header.get("alg")
        if algorithm not in _ALLOWED_ALGORITHMS:
            return AdminAuthDecision(False, "algorithm_not_allowed")

        kid = unverified_header.get("kid")
        if not kid or not isinstance(kid, str):
            return AdminAuthDecision(False, "kid_missing")

        key = self._resolve_key(kid, config.jwks_url, algorithm)
        if key is None:
            return AdminAuthDecision(False, "key_unavailable")

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                issuer=config.issuer,
                audience=config.audience,
                leeway=0,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError:
            return AdminAuthDecision(False, "token_expired")
        except jwt.InvalidIssuerError:
            return AdminAuthDecision(False, "issuer_mismatch")
        except jwt.InvalidAudienceError:
            return AdminAuthDecision(False, "audience_mismatch")
        except jwt.MissingRequiredClaimError:
            return AdminAuthDecision(False, "claims_missing")
        except jwt.InvalidSignatureError:
            return AdminAuthDecision(False, "signature_invalid")
        except jwt.InvalidTokenError:
            return AdminAuthDecision(False, "token_invalid")

        is_anonymous = claims.get("is_anonymous")
        if not isinstance(is_anonymous, bool) or is_anonymous:
            return AdminAuthDecision(False, "anonymous_subject")

        subject = claims.get("sub")
        if not isinstance(subject, str) or subject != config.admin_user_id:
            return AdminAuthDecision(False, "subject_mismatch")

        app_metadata = claims.get("app_metadata")
        if not isinstance(app_metadata, dict) or app_metadata.get("atlas_role") != "admin":
            return AdminAuthDecision(False, "role_mismatch")

        return AdminAuthDecision(True, "ok")

    def _resolve_key(self, kid: str, jwks_url: str, algorithm: str) -> Any:
        with self._lock:
            now = self._clock()
            fresh = bool(self._raw_keys) and (now - self._fetched_at) < _JWKS_TTL_SECONDS
            if not fresh:
                if not self._refresh(jwks_url, now):
                    return None
            elif kid not in self._raw_keys:
                if (now - self._last_refresh_attempt_at) < _JWKS_UNKNOWN_KID_COOLDOWN_SECONDS:
                    return None
                if not self._refresh(jwks_url, now):
                    return None

            raw_jwk = self._raw_keys.get(kid)

        if raw_jwk is None:
            return None
        try:
            return jwt.PyJWK(raw_jwk, algorithm=algorithm).key
        except Exception:
            return None

    def _refresh(self, jwks_url: str, now: float) -> bool:
        self._last_refresh_attempt_at = now
        try:
            keys = self._fetch_jwks(jwks_url)
        except Exception:
            return False
        if not keys:
            return False
        self._raw_keys = keys
        self._fetched_at = now
        return True


_DEFAULT_VERIFIER: Optional[AdminAuthVerifier] = None


def _default_verifier() -> AdminAuthVerifier:
    global _DEFAULT_VERIFIER
    if _DEFAULT_VERIFIER is None:
        _DEFAULT_VERIFIER = AdminAuthVerifier()
    return _DEFAULT_VERIFIER


def evaluate_admin_authorization(authorization_header: Optional[str]) -> AdminAuthDecision:
    """Verify a raw ``Authorization`` header value using the process-wide
    default verifier (real JWKS fetch, real clock)."""
    return _default_verifier().evaluate(authorization_header)
