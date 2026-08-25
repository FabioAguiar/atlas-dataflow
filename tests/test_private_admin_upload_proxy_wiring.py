"""S0264: proves the private Home Card upload proxy contract -- the web
service's generated private Nginx config still forwards /api/admin/ to the
Admin API, admits a finite effective body size on that boundary strictly
above the Atlas 10 MiB application limit, is never unlimited
(client_max_body_size 0), and the private preview host binding remains
loopback-scoped. Read-only against the repository's docker-compose.yml;
never starts a container or mutates Docker state.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

_TEN_MIB = 10 * 1024 * 1024


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _nginx_config_script() -> str:
    web_command = _load(PRIVATE_COMPOSE_PATH)["services"]["web"]["command"]
    return "\n".join(web_command) if isinstance(web_command, list) else str(web_command)


def _admin_prefix_location_block(script: str) -> str:
    match = re.search(r"location\s+\^~\s+/api/admin/\s*\{(?P<body>.*?)\n\s*\}", script, re.DOTALL)
    assert match, "location ^~ /api/admin/ block not found in generated Nginx config"
    return match.group("body")


def _client_max_body_size_bytes(value: str) -> int:
    normalized = value.strip().lower()
    multiplier = 1
    if normalized.endswith("k"):
        multiplier, normalized = 1024, normalized[:-1]
    elif normalized.endswith("m"):
        multiplier, normalized = 1024 * 1024, normalized[:-1]
    elif normalized.endswith("g"):
        multiplier, normalized = 1024 * 1024 * 1024, normalized[:-1]
    return int(normalized) * multiplier


def test_private_proxy_still_forwards_api_admin_prefix():
    script = _nginx_config_script()
    assert "location ^~ /api/admin/ {" in script
    assert "proxy_pass http://api:8000/admin/;" in script


def test_private_admin_boundary_has_a_finite_client_max_body_size_above_10_mib():
    block = _admin_prefix_location_block(_nginx_config_script())
    match = re.search(r"client_max_body_size\s+([^;]+);", block)
    assert match, "client_max_body_size not configured for /api/admin/"
    value = match.group(1).strip()
    assert value != "0"
    assert _client_max_body_size_bytes(value) > _TEN_MIB


def test_private_admin_boundary_is_not_unlimited():
    block = _admin_prefix_location_block(_nginx_config_script())
    assert not re.search(r"client_max_body_size\s+0\s*;", block)


def test_private_preview_host_binding_remains_loopback_scoped():
    service = _load(PRIVATE_COMPOSE_PATH)["services"]["web"]
    ports = service.get("ports") or []
    assert ports, "web service must publish a preview port"
    for port in ports:
        assert str(port).startswith("127.0.0.1:"), port
