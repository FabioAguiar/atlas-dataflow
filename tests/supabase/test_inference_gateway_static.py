"""M52-04: static invariants for the inference gateway Edge Function.

The static tests read files as text only and always run. The final test runs
the TypeScript suite through a subprocess when a suitable runtime (node with
native type stripping, else deno) is installed and skips with an explicit
reason otherwise.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FUNCTION_DIR = REPO_ROOT / "supabase" / "functions" / "inference-gateway"
HANDLER = FUNCTION_DIR / "handler.ts"
ENTRYPOINT = FUNCTION_DIR / "index.ts"
TS_TEST = FUNCTION_DIR / "handler.test.ts"
README = FUNCTION_DIR / "README.md"
CONFIG = REPO_ROOT / "supabase" / "config.toml"
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
MIGRATION = MIGRATIONS_DIR / "20260920000000_create_inference_usage.sql"

IP_HEADER_NAMES = [
    "x-forwarded-for",
    "x-real-ip",
    "cf-connecting-ip",
    "true-client-ip",
    "x-client-ip",
]
FORBIDDEN_SOURCE_TOKENS = [
    "joblib",
    "pickle",
    "onnx",
    "sklearn",
    "artifact",
    "model_bundle",
    "inference_bundle",
]
ALLOWED_INDEX_IMPORTS = {
    "npm:@supabase/supabase-js@2",
    "npm:jose@5",
    "./handler.ts",
}
GATEWAY_ERROR_CODES = [
    "NOT_FOUND",
    "METHOD_NOT_ALLOWED",
    "UNAUTHENTICATED",
    "INVALID_REQUEST",
    "PAYLOAD_TOO_LARGE",
    "QUOTA_EXCEEDED",
    "RESERVATION_UNAVAILABLE",
    "MISCONFIGURED",
    "UPSTREAM_UNAVAILABLE",
    "UPSTREAM_TIMEOUT",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    return "\n".join(re.sub(r"^\s*//.*$", "", line) for line in source.splitlines())


def test_gateway_files_exist():
    for path in (HANDLER, ENTRYPOINT, TS_TEST, README, CONFIG):
        assert path.is_file(), f"missing {path.relative_to(REPO_ROOT)}"


def test_config_disables_platform_jwt_verification_for_the_gateway():
    config = _text(CONFIG)
    match = re.search(
        r"^\[functions\.inference-gateway\]\s*$(.*?)(?=^\[|\Z)", config, re.DOTALL | re.MULTILINE
    )
    assert match, "[functions.inference-gateway] table not found"
    assert re.search(r"^verify_jwt\s*=\s*false\s*$", match.group(1), re.MULTILINE)


def test_handler_has_no_imports_and_no_console_output():
    source = _strip_comments(_text(HANDLER))
    assert not re.search(r"^\s*import\b", source, re.MULTILINE)
    assert "require(" not in source
    assert "console." not in source


def test_index_imports_only_allowed_modules_and_logs_only_console_log():
    source = _strip_comments(_text(ENTRYPOINT))
    imported = set(re.findall(r"^\s*import\b[^;]*?from\s+\"([^\"]+)\"", source, re.MULTILINE | re.DOTALL))
    assert imported == ALLOWED_INDEX_IMPORTS
    assert set(re.findall(r"console\.(\w+)", source)) == {"log"}


def test_gateway_credential_header_and_atlas_path_shape():
    handler = _text(HANDLER)
    assert 'GATEWAY_TOKEN_HEADER = "x-atlas-gateway-token"' in handler
    assert "/datasets/${slug}/inference" in handler
    assert 'redirect: "manual"' in handler
    assert "AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)" in handler
    assert "UPSTREAM_TIMEOUT_MS = 15_000" in handler
    assert "MAX_BODY_BYTES = 1_048_576" in handler


def test_verification_uses_jwks_and_service_role_reservation_only():
    index = _text(ENTRYPOINT)
    assert "/auth/v1/.well-known/jwks.json" in index
    assert 'audience: "authenticated"' in index
    assert "algorithms:" in index
    assert '"reserve_inference_usage"' in index
    assert "SUPABASE_SERVICE_ROLE_KEY" in index
    assert "persistSession: false" in index and "autoRefreshToken: false" in index


def test_fixed_gateway_error_codes_are_declared():
    handler = _text(HANDLER)
    for code in GATEWAY_ERROR_CODES:
        assert f"{code}:" in handler, code
    assert "`GATEWAY_${kind}`" in handler


def test_handler_reserves_before_forwarding_and_has_no_restore_path():
    source = _strip_comments(_text(HANDLER))
    assert source.index("deps.verifyJwt(") < source.index("deps.reserve(") < source.index("deps.forward(")
    lowered = source.lower()
    for word in ("decrement", "restore", "refund", "rollback"):
        assert word not in lowered, word


def test_no_ip_derived_quota_headers_are_referenced():
    for path in (HANDLER, ENTRYPOINT, README):
        lowered = _text(path).lower()
        for name in IP_HEADER_NAMES:
            assert name not in lowered, f"{name} referenced in {path.name}"


def test_no_model_or_artifact_logic_and_no_secret_literals():
    for path in (HANDLER, ENTRYPOINT):
        source = _strip_comments(_text(path))
        lowered = source.lower()
        for token in FORBIDDEN_SOURCE_TOKENS:
            assert token not in lowered, f"{token} in {path.name}"
        assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", source), "JWT-like literal"
        assert not re.search(r"sb_secret_|sbp_[A-Za-z0-9]{10,}", source), "key-like literal"


def test_readme_documents_secrets_with_placeholders_only():
    readme = _text(README)
    for name in (
        "ATLAS_GATEWAY_TOKEN",
        "ATLAS_INFERENCE_GATEWAY_TOKEN",
        "ATLAS_GATEWAY_BASE_URL",
        "ATLAS_GATEWAY_ALLOWED_ORIGINS",
        "/api",
    ):
        assert name in readme, name
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", readme)


def test_supabase_migrations_are_untouched():
    assert sorted(p.name for p in MIGRATIONS_DIR.iterdir()) == [MIGRATION.name]
    assert "public.reserve_inference_usage(" in _text(MIGRATION)
    if shutil.which("git") is None:
        return
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "supabase/migrations"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=60,
    )
    if result.returncode not in (0, 1):
        return  # not a git checkout or HEAD unavailable; static checks above still ran
    assert result.returncode == 0, "supabase/migrations differs from HEAD"


def _node_supports_type_stripping(node: str) -> bool:
    try:
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    match = re.match(r"v(\d+)\.(\d+)\.", version)
    if not match:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    return major > 22 or (major == 22 and minor >= 18)


def test_typescript_suite_passes_under_available_runtime():
    node = shutil.which("node")
    deno = shutil.which("deno")
    if node and _node_supports_type_stripping(node):
        command = [node, "--test", str(TS_TEST)]
    elif deno:
        command = [deno, "test", "--no-check", str(TS_TEST)]
    else:
        pytest.skip("no runtime for handler.test.ts (need node >= 22.18 with type stripping, or deno)")
    result = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
