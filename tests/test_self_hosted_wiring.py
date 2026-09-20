"""M53 corrective: static contracts for the self-hosted Atlas/Supabase wiring.

Offline and stdlib/yaml only. Locks the optional shared-network override, the
env-example classification, and the absence of privileged values from the web
build. Live Coolify/Supabase behavior is explicitly out of scope here.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT / "docker-compose.yml"
PROD = REPO_ROOT / "docker-compose.prod.yml"
OVERRIDE = REPO_ROOT / "docker-compose.self-hosted-network.yml"
ENV_EXAMPLES = (REPO_ROOT / ".env.example", REPO_ROOT / "api" / ".env.example")

PRIVILEGED = (
    "ATLAS_INFERENCE_GATEWAY_TOKEN",
    "ATLAS_GATEWAY_TOKEN",
    "ATLAS_ADMIN_USER_ID",
    "ATLAS_SUPABASE_JWT_ISSUER",
    "ATLAS_SUPABASE_JWKS_URL",
    "ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP",
    "SERVICE_ROLE",
    "service_role",
    "SUPABASE_SERVICE",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_override_joins_only_the_api_to_an_external_named_network():
    data = _load(OVERRIDE)
    assert set(data["services"]) == {"api"}
    networks = data["services"]["api"]["networks"]
    assert set(networks) == {"default", "supabase_shared"}
    shared = data["networks"]["supabase_shared"]
    assert shared["external"] is True
    assert "ATLAS_SUPABASE_SHARED_NETWORK" in shared["name"]


def test_override_alias_is_configurable_required_and_not_generic():
    data = _load(OVERRIDE)
    aliases = data["services"]["api"]["networks"]["supabase_shared"]["aliases"]
    assert len(aliases) == 1
    assert "${ATLAS_PRIVATE_API_ALIAS:?" in aliases[0]
    assert aliases[0] != "api"


def test_override_does_not_publish_ports_or_touch_web():
    data = _load(OVERRIDE)
    assert "ports" not in data["services"]["api"]
    assert "web" not in data["services"]
    text = OVERRIDE.read_text(encoding="utf-8")
    assert "8000:8000" not in text


def test_base_compose_files_stay_free_of_the_cross_project_network():
    for path in (BASE, PROD):
        data = _load(path)
        assert "networks" not in data, path.name
        for name, service in data["services"].items():
            assert "networks" not in service, f"{path.name}:{name}"
            assert not any(
                ":8000" in str(port) for port in (service.get("ports") or [])
            ), f"{path.name}:{name} publishes 8000"
        assert "8000" in [str(p) for p in data["services"]["api"]["expose"]]


def test_web_to_api_default_networking_is_preserved():
    # With no networks key anywhere in the bases, both services share the
    # project default network, so web -> http://api:8000 keeps resolving; the
    # override keeps `default` on the API explicitly.
    text = BASE.read_text(encoding="utf-8")
    assert "http://api:8000" in text
    assert "default" in _load(OVERRIDE)["services"]["api"]["networks"]


def test_private_compose_passes_jwks_private_http_opt_in_default_off():
    env = _load(BASE)["services"]["api"]["environment"]
    assert env["ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP"] == "${ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP:-false}"


def test_privileged_values_never_become_web_build_args():
    for path in (BASE, PROD):
        args = _load(path)["services"]["web"]["build"]["args"]
        assert all(name.startswith("VITE_") for name in args), path.name
        assert set(args) == {
            "VITE_API_BASE_URL",
            "VITE_ENABLE_ADMIN",
            "VITE_SUPABASE_URL",
            "VITE_SUPABASE_PUBLISHABLE_KEY",
        }
        for value in args.values():
            assert not any(token in str(value) for token in PRIVILEGED)
        assert not any("environment" in _load(path)["services"]["web"] for _ in [0]), path.name


def test_web_dockerfile_declares_only_vite_publishable_args():
    text = (REPO_ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert not any(token in text for token in PRIVILEGED)


def test_env_examples_document_the_current_variables():
    text = ENV_EXAMPLES[0].read_text(encoding="utf-8")
    for name in (
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
        "VITE_ENABLE_ADMIN",
        "ATLAS_ADMIN_ENABLED",
        "ATLAS_SUPABASE_JWT_ISSUER",
        "ATLAS_SUPABASE_JWT_AUDIENCE",
        "ATLAS_SUPABASE_JWKS_URL",
        "ATLAS_SUPABASE_JWKS_ALLOW_PRIVATE_HTTP",
        "ATLAS_ADMIN_USER_ID",
        "ATLAS_INFERENCE_GATEWAY_TOKEN",
        "ATLAS_GATEWAY_BASE_URL",
        "ATLAS_GATEWAY_TOKEN",
        "ATLAS_GATEWAY_ALLOWED_ORIGINS",
        "ATLAS_GATEWAY_ALLOW_PRIVATE_HTTP",
        "ATLAS_SUPABASE_SHARED_NETWORK",
        "ATLAS_PRIVATE_API_ALIAS",
    ):
        assert name in text, name


def test_env_examples_contain_only_neutral_placeholders():
    secret_shapes = (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}"),  # JWT-looking
        re.compile(r"\b(sb_secret|sb_publishable)_[A-Za-z0-9]{8,}"),
        re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
        re.compile(r"[A-Za-z0-9+/_-]{40,}"),
    )
    for path in ENV_EXAMPLES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") and "=" not in line:
                continue
            for shape in secret_shapes:
                assert not shape.search(line), f"{path.name}: {line!r}"
    for path in ENV_EXAMPLES:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(?:#\s*)?(ATLAS_\w*(?:TOKEN|USER_ID))=(.*)$", line)
            if match:
                assert match.group(2).strip().startswith("<"), line
