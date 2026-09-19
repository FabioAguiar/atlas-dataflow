"""M51-05: static deployment invariants for the private Admin identity boundary.

Reads Compose/Dockerfile/nginx/docs as static files; nothing is executed.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
WEB_DOCKERFILE = REPO_ROOT / "web" / "Dockerfile"
NGINX_CONF = REPO_ROOT / "web" / "nginx.conf"
OPERATOR_NOTE = REPO_ROOT / "docs" / "operations" / "admin-operator-provisioning.md"
SETTINGS_CONTRACT = REPO_ROOT / "contracts" / "admin-settings.schema.json"

TRUSTED_VARS = (
    "ATLAS_SUPABASE_JWT_ISSUER",
    "ATLAS_SUPABASE_JWT_AUDIENCE",
    "ATLAS_SUPABASE_JWKS_URL",
    "ATLAS_ADMIN_USER_ID",
)
PUBLISHABLE_VARS = ("VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_private_api_passes_trusted_vars_as_optional_passthrough():
    env = _load(PRIVATE_COMPOSE)["services"]["api"]["environment"]
    for name in TRUSTED_VARS:
        assert env[name] == f"${{{name}:-}}"


def test_private_web_passes_exactly_the_two_publishable_build_args():
    args = _load(PRIVATE_COMPOSE)["services"]["web"]["build"]["args"]
    supabase_args = {k: v for k, v in args.items() if "SUPABASE" in k}
    assert supabase_args == {name: f"${{{name}:-}}" for name in PUBLISHABLE_VARS}


def test_trusted_vars_never_reach_the_web_build():
    args = _load(PRIVATE_COMPOSE)["services"]["web"]["build"]["args"]
    assert not set(TRUSTED_VARS) & set(args)
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    for name in TRUSTED_VARS:
        assert name not in dockerfile


def test_legacy_admin_token_passthrough_is_removed():
    assert "ADMIN_API_TOKEN" not in PRIVATE_COMPOSE.read_text(encoding="utf-8")


def test_dockerfile_declares_publishable_args_with_empty_defaults():
    text = WEB_DOCKERFILE.read_text(encoding="utf-8")
    for name in PUBLISHABLE_VARS:
        assert f'ARG {name}=""' in text
        assert f"ENV {name}=${{{name}}}" in text


def test_public_compose_gains_no_auth_configuration():
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    for name in TRUSTED_VARS + PUBLISHABLE_VARS:
        assert name not in text
    assert "SUPABASE" not in text.upper()
    services = _load(PROD_COMPOSE)["services"]
    assert services["api"]["environment"]["ATLAS_ADMIN_ENABLED"] == "${ATLAS_ADMIN_ENABLED:-false}"
    assert services["web"]["build"]["args"]["VITE_ENABLE_ADMIN"] == "${VITE_ENABLE_ADMIN:-false}"


def test_public_nginx_keeps_admin_paths_blocked():
    text = NGINX_CONF.read_text(encoding="utf-8")
    for needle in ("location = /api/admin", "location ^~ /api/admin/", "location = /admin", "location ^~ /admin/"):
        assert needle in text
    assert "return 404" in text


def test_admin_settings_contract_carries_no_identity_or_deployment_fields():
    text = SETTINGS_CONTRACT.read_text(encoding="utf-8").lower()
    for needle in ("supabase", "jwt", "admin_user_id", "atlas_role"):
        assert needle not in text


def test_operator_note_exists_and_uses_placeholders_only():
    text = OPERATOR_NOTE.read_text(encoding="utf-8")
    for name in TRUSTED_VARS + PUBLISHABLE_VARS:
        assert name in text
    assert "atlas_role" in text
    assert "SUPABASE_SECRET_KEY" not in text
    assert "eyJ" not in text
