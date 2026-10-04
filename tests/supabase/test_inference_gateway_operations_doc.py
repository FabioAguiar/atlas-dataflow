"""M52-06 / S0300: static checks for the inference gateway operator note.

Stdlib only and offline, so these tests never skip. They keep the operator
note aligned with the current migration constants (the S0300 global subject
budget on top of the historical M52 base migration) and the gateway README,
and keep secret-shaped content out of it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPERATIONS_DOC = REPO_ROOT / "docs" / "operations" / "inference-gateway-operations.md"
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20260920000000_create_inference_usage.sql"
GLOBAL_MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261004000000_globalize_inference_usage_quota.sql"
OVERVIEW = REPO_ROOT / "docs" / "current-architecture-overview.md"
README = REPO_ROOT / "supabase" / "functions" / "inference-gateway" / "README.md"

CREDENTIAL_NAMES = [
    "ATLAS_GATEWAY_TOKEN",
    "ATLAS_GATEWAY_BASE_URL",
    "ATLAS_GATEWAY_ALLOWED_ORIGINS",
    "ATLAS_INFERENCE_GATEWAY_TOKEN",
]
GATEWAY_HEADER = "x-atlas-gateway-token"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _migration_constants() -> dict:
    base = _text(MIGRATION)
    current = _text(GLOBAL_MIGRATION)
    window = re.search(r"interval '(\d+) minutes', p_now", current)
    limit = re.search(r"WHERE u\.request_count < (\d+)", current)
    check = re.search(r"request_count BETWEEN 1 AND (\d+)", base)
    retention = re.search(r"p_retention interval DEFAULT interval '(\d+) days'", base)
    assert window and limit and check and retention, "migration constants not found"
    assert limit.group(1) == check.group(1)
    return {
        "window_minutes": int(window.group(1)),
        "limit": int(limit.group(1)),
        "retention_days": int(retention.group(1)),
    }


def _architecture_responsibilities() -> str:
    text = _text(ARCHITECTURE)
    match = re.search(
        r"^### Public Runtime API\s*\n\s*Responsibilities:\s*\n(.*?)(?=^### )",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "Public Runtime API responsibilities list not found"
    return match.group(1)


def test_operator_note_exists_under_docs_operations():
    assert OPERATIONS_DOC.is_file()
    assert OPERATIONS_DOC.parent.name == "operations"


def test_operator_note_values_match_migration_constants():
    constants = _migration_constants()
    doc = _text(OPERATIONS_DOC)
    assert f"fixed {constants['window_minutes']}-minute UTC window" in doc
    assert f"{constants['limit']} requests per subject per window across all datasets" in doc
    assert re.search(rf"\|\s*Retention\s*\|\s*{constants['retention_days']} days\s*\|", doc)


def test_gateway_readme_states_the_same_window_and_limit_sources():
    constants = _migration_constants()
    readme = _text(README)
    assert "1,048,576" in readme  # sanity: the README is the gateway contract
    assert "Retry-After" in readme
    assert "reserve_inference_usage" in readme
    assert (constants["window_minutes"], constants["limit"]) == (10, 10)
    assert "across all datasets" in readme
    assert "reserve_inference_usage(p_subject_id)" in readme


def test_operator_note_states_the_global_subject_budget_and_its_limits():
    doc = _text(OPERATIONS_DOC)
    assert "10 accepted inference reservations per verified anonymous subject per fixed 10-minute window, across all datasets" in doc
    assert "Changing datasets does not reset the budget" in doc
    assert "another anonymous subject still creates another subject budget" in doc
    assert "does not claim person-level identity" in doc
    assert "S0305" in doc
    assert "routing context" in doc and "reduced-observability context" in doc
    assert "never restored or refunded" in doc
    assert "**compatibility only**" in doc
    assert GLOBAL_MIGRATION.name in doc
    # M52 history stays visible instead of being rewritten.
    assert "M52 shipped the quota as 10 requests per subject per dataset per window" in doc


def test_current_architecture_documents_describe_the_global_budget():
    overview = _text(OVERVIEW)
    assert "todos os datasets" in overview and "S0305" in overview
    responsibilities = _architecture_responsibilities()
    assert "per-dataset quota" not in responsibilities
    assert "across all datasets" in responsibilities


def test_operator_note_states_pg_cron_purge_story():
    doc = _text(OPERATIONS_DOC)
    assert "pg_cron" in doc
    assert "purge_inference_usage" in doc
    assert "unbounded" in doc


def test_operator_note_states_m50_containment_remains_beneath_gateway():
    doc = _text(OPERATIONS_DOC)
    assert "M50 containment" in doc
    assert "beneath the gateway" in doc


def test_operator_note_states_zero_downtime_rotation_is_unavailable():
    doc = _text(OPERATIONS_DOC)
    assert "zero-downtime rotation is unavailable" in doc
    assert "no overlap window" in doc
    assert "Recreate the `api` container" in doc


def test_operator_note_names_credential_variables_and_header():
    doc = _text(OPERATIONS_DOC)
    for name in CREDENTIAL_NAMES:
        assert name in doc, name
    assert GATEWAY_HEADER in doc


def test_operator_note_contains_no_secret_shaped_content():
    doc = _text(OPERATIONS_DOC)
    assert not re.search(r"eyJ[A-Za-z0-9_-]{5,}", doc)
    assert "sb_secret_" not in doc
    assert not re.search(r"https?://[^\s<>`]*\.supabase\.co", doc)
    assert not re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", doc)
    # Migration file names are long identifiers by convention, not secrets.
    assert not re.search(r"\b[A-Za-z0-9_-]{40,}\b", re.sub(r"\b\d{14}_[a-z_]+\.sql\b", "", doc))
    for line in doc.splitlines():
        assert not re.search(r"service_role\w*\s*[=:]\s*\S", line, re.IGNORECASE), line


def test_architecture_public_runtime_responsibilities_mention_the_gateway():
    responsibilities = _architecture_responsibilities().lower()
    assert "gateway" in responsibilities
    assert "quota" in responsibilities
    assert "jwt" in responsibilities
    assert "gateway credential" in responsibilities
    assert "m50 containment" in responsibilities
