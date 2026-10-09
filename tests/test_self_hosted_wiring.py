"""M53 corrective: static contracts for the self-hosted Atlas/Supabase wiring.

Offline and stdlib/yaml only. Locks the optional shared-network override, the
env-example classification, the absence of privileged values from the web
build, (S0294) the narrowed public CSP connect-src contract rendered at
image build time from the public VITE_SUPABASE_URL input, and (S0316) the exact
Cloudflare Web Analytics beacon/ingestion origins of the public CSP. These are static
source/configuration contracts: live Coolify/Supabase behavior, live HTTP
headers and live Traefik routing are explicitly out of scope here.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT / "docker-compose.yml"
PROD = REPO_ROOT / "docker-compose.prod.yml"
TRAEFIK = REPO_ROOT / "docker-compose.traefik.yml"
PUBLIC_NGINX = REPO_ROOT / "web" / "nginx.conf"
WEB_DOCKERFILE = REPO_ROOT / "web" / "Dockerfile"
OVERRIDE = REPO_ROOT / "docker-compose.self-hosted-network.yml"
ENV_EXAMPLES = (REPO_ROOT / ".env.example", REPO_ROOT / "api" / ".env.example")
# The public nginx serve stage, pinned to an immutable SHA-256 index digest (S0302).
PINNED_NGINX_SERVE_FROM = re.compile(
    r"^(?i:FROM)[ \t]+nginx:alpine@sha256:[0-9a-f]{64}[ \t]+(?i:AS)[ \t]+serve[ \t]*$",
    flags=re.MULTILINE,
)

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


def test_public_prod_disables_fastapi_docs_without_exposing_the_flag_to_web():
    data = _load(PROD)
    assert data["services"]["api"]["environment"]["ATLAS_API_DOCS_ENABLED"] == (
        "${ATLAS_API_DOCS_ENABLED:-false}"
    )
    web_args = data["services"]["web"]["build"]["args"]
    assert "ATLAS_API_DOCS_ENABLED" not in web_args
    assert "VITE_ATLAS_API_DOCS_ENABLED" not in web_args


def test_public_prod_requires_the_publishable_turnstile_site_key():
    web_args = _load(PROD)["services"]["web"]["build"]["args"]
    interpolation = web_args["VITE_TURNSTILE_SITE_KEY"]

    assert interpolation == (
        "${VITE_TURNSTILE_SITE_KEY:?Set VITE_TURNSTILE_SITE_KEY for the "
        "production public web build}"
    )
    assert "${VITE_TURNSTILE_SITE_KEY:-" not in interpolation


def test_public_nginx_denies_docs_and_keeps_admin_and_api_boundaries():
    text = PUBLIC_NGINX.read_text(encoding="utf-8")
    denied_locations = (
        ("=", "/api/docs"),
        ("^~", "/api/docs/"),
        ("=", "/api/redoc"),
        ("^~", "/api/redoc/"),
        ("=", "/api/openapi.json"),
        ("=", "/api/admin"),
        ("^~", "/api/admin/"),
        ("=", "/admin"),
        ("^~", "/admin/"),
    )
    for modifier, path in denied_locations:
        pattern = rf"location\s+{re.escape(modifier)}\s+{re.escape(path)}\s*\{{\s*return\s+404;\s*\}}"
        assert re.search(pattern, text), path
    assert re.search(
        r"location\s+/api/\s*\{[^}]*proxy_pass\s+http://api:8000/;",
        text,
        flags=re.DOTALL,
    )


def test_public_nginx_owns_the_required_security_header_policy():
    text = PUBLIC_NGINX.read_text(encoding="utf-8")
    assert re.search(r"\bserver_tokens\s+off;", text)
    for header in (
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "X-Frame-Options",
        "Content-Security-Policy",
    ):
        assert re.search(rf"add_header\s+{header}\s+.+\s+always;", text), header

    csp_match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"\s+always;', text)
    assert csp_match is not None
    csp = csp_match.group(1)
    for directive in (
        "default-src",
        "base-uri",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "script-src",
        "style-src",
        "img-src",
        "connect-src",
        "frame-src",
        "form-action",
    ):
        assert directive in csp
    assert "unsafe-eval" not in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "https://challenges.cloudflare.com" in csp
    assert "https://raw.githubusercontent.com" in csp
    assert not re.search(r"(?:default|script|connect|frame)-src\s+\*", csp)


# --- S0294: narrowed public CSP connect-src contract -------------------------

SUPABASE_MARKER = "__ATLAS_SUPABASE_CONNECT_SRC__"
TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"
# S0316: exact Cloudflare Web Analytics origins, public CSP only.
WEB_ANALYTICS_SCRIPT_ORIGIN = "https://static.cloudflareinsights.com"
WEB_ANALYTICS_CONNECT_ORIGIN = "https://cloudflareinsights.com"
SCHEME_WIDE_OR_WILDCARD = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|\*.*|.*://\*.*)$", re.IGNORECASE)


def _csp(text: str) -> str:
    match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"\s+always;', text)
    assert match is not None
    return match.group(1)


def _directives(csp: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            assert tokens[0] not in directives, f"duplicate CSP directive {tokens[0]}"
            directives[tokens[0]] = tokens[1:]
    return directives


def _assert_bounded_connect_src(sources: list[str]) -> None:
    for source in sources:
        assert not SCHEME_WIDE_OR_WILDCARD.match(source), f"scheme-wide connect-src {source!r}"
        # No WebSocket requirement exists in the public frontend, so no
        # ws:/wss: source of any shape is part of the contract.
        assert not source.lower().startswith(("ws:", "wss:")), source


def _dockerfile_csp_renderer() -> str:
    """Return the node renderer script exactly as Docker joins the RUN lines."""
    joined = WEB_DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", "")
    match = re.search(r"RUN node -e '([^']*)'\s*\n", joined)
    assert match is not None, "web/Dockerfile has no CSP renderer"
    return match.group(1)


def _render(tmp_path: Path, supabase_url: str) -> subprocess.CompletedProcess:
    shutil.copyfile(PUBLIC_NGINX, tmp_path / "nginx.conf.template")
    env = {key: value for key, value in os.environ.items() if not key.startswith("VITE_")}
    env["VITE_SUPABASE_URL"] = supabase_url
    return subprocess.run(
        ["node", "-e", _dockerfile_csp_renderer()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _rendered_connect_src(tmp_path: Path, supabase_url: str) -> list[str]:
    result = _render(tmp_path, supabase_url)
    assert result.returncode == 0, result.stderr
    rendered = (tmp_path / "nginx.default.conf").read_text(encoding="utf-8")
    assert SUPABASE_MARKER not in rendered
    return _directives(_csp(rendered))["connect-src"]


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_public_csp_connect_src_is_bounded_to_explicit_origins():
    directives = _directives(_csp(PUBLIC_NGINX.read_text(encoding="utf-8")))
    connect_src = directives["connect-src"]

    # The marker is the only build-time insertion point and it lives inside
    # connect-src, appended to the last explicit source.
    assert PUBLIC_NGINX.read_text(encoding="utf-8").count(SUPABASE_MARKER) == 1
    assert connect_src[-1].endswith(SUPABASE_MARKER)
    template_sources = [source.replace(SUPABASE_MARKER, "") for source in connect_src]
    assert template_sources == ["'self'", TURNSTILE_ORIGIN, WEB_ANALYTICS_CONNECT_ORIGIN]
    _assert_bounded_connect_src(template_sources)
    for name, sources in directives.items():
        if name != "connect-src":
            assert not any(SUPABASE_MARKER in source for source in sources), name


def test_public_csp_keeps_turnstile_and_strict_non_connect_directives():
    directives = _directives(_csp(PUBLIC_NGINX.read_text(encoding="utf-8")))
    assert directives["default-src"] == ["'self'"]
    assert directives["base-uri"] == ["'self'"]
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["form-action"] == ["'self'"]
    assert directives["script-src"] == ["'self'", TURNSTILE_ORIGIN, WEB_ANALYTICS_SCRIPT_ORIGIN]
    assert directives["style-src"] == ["'self'", "'unsafe-inline'"]
    assert directives["img-src"] == ["'self'", "data:", "blob:", "https://raw.githubusercontent.com"]
    assert directives["frame-src"] == [TURNSTILE_ORIGIN]
    assert directives["connect-src"][1] == TURNSTILE_ORIGIN
    assert set(directives) == {
        "default-src",
        "base-uri",
        "object-src",
        "frame-ancestors",
        "script-src",
        "style-src",
        "img-src",
        "connect-src",
        "frame-src",
        "form-action",
    }


def test_bounded_connect_src_guard_rejects_scheme_wide_sources():
    for broad in (["'self'", "https:"], ["'self'", "wss:"], ["*"], ["https://*.supabase.co"], ["ws:"]):
        with pytest.raises(AssertionError):
            _assert_bounded_connect_src(broad)
    with pytest.raises(AssertionError):
        _assert_bounded_connect_src(["'self'", "wss://example.supabase.co"])
    _assert_bounded_connect_src(["'self'", TURNSTILE_ORIGIN, "https://example.supabase.co"])


def _split_at_pinned_nginx_serve_stage(text: str) -> tuple[str, str]:
    """Split web/Dockerfile at its nginx serve stage, which must stay digest-pinned (S0302)."""
    matches = list(PINNED_NGINX_SERVE_FROM.finditer(text))
    assert len(matches) == 1, "web/Dockerfile needs exactly one sha256-pinned nginx:alpine serve stage"
    return text[: matches[0].start()], text[matches[0].end() :]


def test_nginx_serve_stage_discovery_requires_an_immutable_sha256_digest():
    digest = "0" * 63 + "a"
    build, serve = _split_at_pinned_nginx_serve_stage(
        f"FROM node AS build\nRUN true\nFROM  nginx:alpine@sha256:{digest}  as  serve\nCOPY x y\n"
    )
    assert build.endswith("RUN true\n") and serve == "\nCOPY x y\n"
    for unpinned in (
        "FROM nginx:alpine AS serve",
        "FROM nginx:alpine@sha256:abc AS serve",
        f"FROM nginx:alpine@sha256:{digest.upper()} AS serve",
        f"FROM nginx:alpine@sha256:{digest}0 AS serve",
        f"FROM nginx:alpine@sha512:{digest} AS serve",
        f"FROM nginx:alpine@sha256:{digest}-evil AS serve",
        f"FROM nginx:alpine@sha256:{digest} AS server",
        f"FROM nginx:latest@sha256:{digest} AS serve",
    ):
        with pytest.raises(AssertionError):
            _split_at_pinned_nginx_serve_stage(f"FROM node AS build\n{unpinned}\nCOPY x y\n")


def test_web_image_serves_the_rendered_config_from_the_public_supabase_input():
    text = WEB_DOCKERFILE.read_text(encoding="utf-8")
    build_stage, serve_stage = _split_at_pinned_nginx_serve_stage(text)
    assert serve_stage.strip(), "web/Dockerfile has no nginx serve stage"
    assert "COPY nginx.conf ./nginx.conf.template" in build_stage
    assert re.search(
        r"^COPY\s+--from=build\s+/app/nginx\.default\.conf\s+/etc/nginx/conf\.d/default\.conf$",
        serve_stage,
        flags=re.MULTILINE,
    )
    assert not re.search(r"^COPY\s+nginx\.conf\s", serve_stage, flags=re.MULTILINE)

    renderer = _dockerfile_csp_renderer()
    assert "process.env.VITE_SUPABASE_URL" in renderer
    assert "url.origin" in renderer
    assert SUPABASE_MARKER in renderer
    # The renderer reads no other environment input (no second config source).
    assert re.findall(r"process\.env\.(\w+)", renderer) == ["VITE_SUPABASE_URL"]
    assert not any(token in renderer for token in PRIVILEGED)


@needs_node
def test_rendered_csp_without_supabase_url_stays_same_origin_and_turnstile(tmp_path):
    assert _rendered_connect_src(tmp_path, "") == ["'self'", TURNSTILE_ORIGIN, WEB_ANALYTICS_CONNECT_ORIGIN]


@needs_node
@pytest.mark.parametrize(
    ("supabase_url", "expected_origin"),
    (
        ("https://example-ref.supabase.co", "https://example-ref.supabase.co"),
        ("  https://Example-Ref.Supabase.co/  ", "https://example-ref.supabase.co"),
        ("https://auth.example.test:8443/base/path?x=1#y", "https://auth.example.test:8443"),
        ("http://localhost:54321", "http://localhost:54321"),
    ),
)
def test_rendered_csp_adds_only_the_exact_supabase_origin(tmp_path, supabase_url, expected_origin):
    connect_src = _rendered_connect_src(tmp_path, supabase_url)
    assert connect_src == ["'self'", TURNSTILE_ORIGIN, WEB_ANALYTICS_CONNECT_ORIGIN, expected_origin]
    _assert_bounded_connect_src(connect_src)


@needs_node
@pytest.mark.parametrize("supabase_url", ("", "https://example-ref.supabase.co"))
def test_rendered_csp_keeps_exact_web_analytics_script_source(tmp_path, supabase_url):
    result = _render(tmp_path, supabase_url)
    assert result.returncode == 0, result.stderr
    directives = _directives(_csp((tmp_path / "nginx.default.conf").read_text(encoding="utf-8")))
    assert directives["script-src"] == ["'self'", TURNSTILE_ORIGIN, WEB_ANALYTICS_SCRIPT_ORIGIN]
    assert directives["frame-src"] == [TURNSTILE_ORIGIN]
    for name, sources in directives.items():
        if name not in ("script-src", "connect-src"):
            assert not any("cloudflareinsights" in source for source in sources), name


@needs_node
@pytest.mark.parametrize(
    "supabase_url",
    (
        "not a url",
        "example-ref.supabase.co",
        "ftp://example-ref.supabase.co",
        "wss://example-ref.supabase.co",
        "javascript:alert(1)",
        "https://user:password@example-ref.supabase.co",
        "https://example;ref.supabase.co",
        "https://example\"ref.supabase.co",
        "https://*.supabase.co",
    ),
)
def test_unusable_supabase_url_fails_the_build_instead_of_broadening_csp(tmp_path, supabase_url):
    result = _render(tmp_path, supabase_url)
    assert result.returncode != 0
    assert "VITE_SUPABASE_URL rejected for CSP" in result.stderr
    assert not (tmp_path / "nginx.default.conf").exists()


def test_traefik_applies_atlas_hsts_only_to_the_https_router():
    labels = _load(TRAEFIK)["services"]["web"]["labels"]
    middleware = "atlas-dataflow-hsts"
    assert labels[f"traefik.http.middlewares.{middleware}.headers.stsSeconds"] == "31536000"
    assert labels["traefik.http.routers.atlas-dataflow-https.middlewares"] == middleware
    assert labels["traefik.http.routers.atlas-dataflow-http.middlewares"] == "atlas-dataflow-redirect-https"
    assert not any(
        key in labels
        for key in (
            f"traefik.http.middlewares.{middleware}.headers.stsIncludeSubdomains",
            f"traefik.http.middlewares.{middleware}.headers.stsPreload",
        )
    )


def test_privileged_values_never_become_web_build_args():
    for path in (BASE, PROD):
        args = _load(path)["services"]["web"]["build"]["args"]
        assert all(name.startswith("VITE_") for name in args), path.name
        assert set(args) == {
            "VITE_API_BASE_URL",
            "VITE_ENABLE_ADMIN",
            "VITE_SUPABASE_URL",
            "VITE_SUPABASE_PUBLISHABLE_KEY",
            "VITE_TURNSTILE_SITE_KEY",
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
