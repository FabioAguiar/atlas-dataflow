"""Canonical metric identity for the API and registry layers.

Reads the single metric authority ``contracts/metric-identity-registry.json``
(the same file ``pipeline/metric_identity.py`` reads -- the API image ships
``contracts/`` and ``registry/`` but not ``pipeline/``). This module keeps no
metric table of its own; tests assert both readers stay in agreement with the
registry.

The registry file is resolved from this module's own location (code
authority), never from a per-request or per-test repository root.
"""

import json
from functools import lru_cache
from pathlib import Path

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "contracts" / "metric-identity-registry.json"
_REGISTRY_SCHEMA_VERSION = "metric-identity-registry.v1"


@lru_cache(maxsize=1)
def _registry_metrics() -> tuple[dict, ...]:
    payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _REGISTRY_SCHEMA_VERSION:
        raise RuntimeError(
            f"metric identity registry must declare schema_version {_REGISTRY_SCHEMA_VERSION!r}"
        )
    return tuple(payload["metrics"])


@lru_cache(maxsize=1)
def public_metric_aliases() -> dict[str, str]:
    """{raw metric name -> published public metric key}.

    A metric is published only when the registry assigns it a public key.
    Accepted raw names are the public key itself, the native training
    aliases, and the declared extra public input aliases -- never the
    scientific-reproduction aliases, and never an unknown name.
    """
    aliases: dict[str, str] = {}
    for entry in _registry_metrics():
        public_key = entry["aliases"]["public"]
        if public_key is None:
            continue
        for raw_name in (
            public_key,
            *entry["aliases"]["training"],
            *entry["aliases"]["public_input"],
        ):
            aliases[raw_name] = public_key
    return aliases


def public_metric_key(metric_name: object) -> str | None:
    """Published public key for a contract/training/public metric name, or
    None when the metric is unknown or never published."""
    if not isinstance(metric_name, str):
        return None
    return public_metric_aliases().get(metric_name.strip().lower())
