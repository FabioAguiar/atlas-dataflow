"""M52-03: static invariants for the inference_usage migration.

Reads the migration as text only; no database and no driver is needed, so this
module always runs. Live behaviour is covered by the reservation live module.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20260920000000_create_inference_usage.sql"
TESTS_DIR = Path(__file__).resolve().parent

EXPECTED_COLUMNS = [
    ("subject_id", "text"),
    ("dataset_slug", "text"),
    ("window_start", "timestamptz"),
    ("request_count", "integer"),
]
SENSITIVE_TOKENS = {
    "payload", "output", "token", "jwt", "credential", "secret", "ip", "email", "password", "body",
}
FUNCTION_SIGNATURES = {
    "reserve_inference_usage_at": "public.reserve_inference_usage_at(text, text, timestamptz)",
    "reserve_inference_usage": "public.reserve_inference_usage(text, text)",
    "purge_inference_usage": "public.purge_inference_usage(interval)",
}


def _sql() -> str:
    """Migration text with `--` comments removed."""
    raw = MIGRATION.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())


def _table_columns() -> list[tuple[str, str]]:
    match = re.search(r"CREATE TABLE public\.inference_usage \((.*?)\n\);", _sql(), re.DOTALL)
    assert match, "CREATE TABLE public.inference_usage block not found"
    columns = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("CONSTRAINT"):
            continue
        name, type_name = re.match(r"(\w+)\s+(\w+)", line).groups()
        columns.append((name, type_name))
    return columns


def _function_chunks() -> dict[str, str]:
    sql = _sql()
    parts = re.split(r"CREATE OR REPLACE FUNCTION ", sql)[1:]
    chunks = {}
    for part in parts:
        name = re.match(r"public\.(\w+)\(", part).group(1)
        chunks[name] = part
    return chunks


def test_migration_file_exists_at_supabase_cli_path():
    assert MIGRATION.is_file()
    assert re.fullmatch(r"\d{14}_create_inference_usage\.sql", MIGRATION.name)
    assert [p.name for p in MIGRATION.parent.glob("*.sql")] == [MIGRATION.name]


def test_table_has_exactly_the_four_columns():
    assert _table_columns() == EXPECTED_COLUMNS


def test_no_sensitive_column_names_or_types():
    for name, type_name in _table_columns():
        tokens = set(name.split("_")) | {type_name}
        assert not tokens & SENSITIVE_TOKENS, name
        assert type_name != "uuid", name


def test_primary_key_and_checks_present():
    sql = _sql()
    assert "PRIMARY KEY (subject_id, dataset_slug, window_start)" in sql
    assert "CHECK (request_count BETWEEN 1 AND 10)" in sql
    assert "CHECK (char_length(subject_id) BETWEEN 1 AND 128)" in sql
    assert "CHECK (char_length(dataset_slug) BETWEEN 1 AND 128)" in sql


def test_only_the_primary_key_and_window_start_indexes_exist():
    sql = _sql()
    assert re.findall(r"CREATE INDEX \w+ ON (\S+) \((\w+)\)", sql) == [
        ("public.inference_usage", "window_start")
    ]


def test_rls_enabled_without_visitor_policies():
    sql = _sql()
    assert "ALTER TABLE public.inference_usage ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY" not in sql


def test_table_privileges_revoked_from_public_and_visitor_roles():
    sql = _sql()
    assert "REVOKE ALL ON TABLE public.inference_usage FROM PUBLIC" in sql
    assert "ARRAY['anon', 'authenticated']" in sql
    assert "REVOKE ALL ON TABLE public.inference_usage FROM %I" in sql
    assert "REVOKE ALL ON TABLE public.inference_usage FROM service_role" in sql


def test_function_execute_revoked_from_public_and_visitor_roles():
    sql = _sql()
    for signature in FUNCTION_SIGNATURES.values():
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC" in sql
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM %I" in sql


def test_grants_go_to_service_role_only_and_never_to_the_clock_seam():
    sql = _sql()
    grants = re.findall(r"GRANT\s+(.*?)\s+TO\s+(\w+)", sql, re.DOTALL)
    assert sorted(grants) == sorted(
        [
            (f"EXECUTE ON FUNCTION {FUNCTION_SIGNATURES['reserve_inference_usage']}", "service_role"),
            (f"EXECUTE ON FUNCTION {FUNCTION_SIGNATURES['purge_inference_usage']}", "service_role"),
        ]
    )
    assert (
        f"REVOKE EXECUTE ON FUNCTION {FUNCTION_SIGNATURES['reserve_inference_usage_at']} FROM service_role"
        in sql
    )


def test_every_function_is_security_definer_with_pinned_search_path():
    chunks = _function_chunks()
    assert set(chunks) == set(FUNCTION_SIGNATURES)
    for name, chunk in chunks.items():
        header = chunk.split("AS $fn$")[0]
        assert "SECURITY DEFINER" in header, name
        assert "SET search_path = ''" in header, name
    sql = _sql()
    assert sql.count("SECURITY DEFINER") == sql.count("SET search_path = ''") == 3


def test_reservation_is_a_single_atomic_upsert_with_hard_coded_constants():
    sql = _sql()
    assert "ON CONFLICT (subject_id, dataset_slug, window_start)" in sql
    assert "DO UPDATE SET request_count = u.request_count + 1" in sql
    assert "WHERE u.request_count < 10" in sql
    assert "date_bin(" in sql
    assert "interval '10 minutes'" in sql
    assert "timestamptz '1970-01-01 00:00:00+00'" in sql
    assert "interval '7 days'" in sql
    assert "RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)" in sql
    for forbidden in ("pg_advisory", "SERIALIZABLE", "EXCEPTION WHEN"):
        assert forbidden not in sql


def test_public_wrapper_passes_statement_time_not_a_caller_clock():
    chunk = _function_chunks()["reserve_inference_usage"]
    assert "pg_catalog.now()" in chunk
    assert re.search(r"reserve_inference_usage\(\s*p_subject_id text,\s*p_dataset_slug text\s*\)", chunk)


def test_migration_touches_nothing_outside_the_table_and_three_functions():
    sql = _sql()
    assert "auth.users" not in sql
    assert not re.search(r"\bauth\.", sql)
    assert "CREATE EXTENSION" not in sql
    created = re.findall(r"^CREATE (?:OR REPLACE )?(\w+)", sql, re.MULTILINE)
    assert created == ["TABLE", "INDEX", "FUNCTION", "FUNCTION", "FUNCTION"]
    assert re.findall(r"^ALTER\s+(\w+)\s+(\S+)", sql, re.MULTILINE) == [
        ("TABLE", "public.inference_usage")
    ]
    assert not re.search(r"^DROP\b", sql, re.MULTILINE)


def test_cron_schedule_only_inside_a_pg_extension_guard():
    sql = _sql()
    total = sql.count("cron.schedule")
    assert total >= 1
    guarded = 0
    for tag, body in re.findall(r"DO \$(\w+)\$(.*?)\$\1\$", sql, re.DOTALL):
        if "cron.schedule" in body:
            assert "pg_extension" in body
            assert body.index("pg_extension") < body.index("cron.schedule")
            guarded += body.count("cron.schedule")
    assert guarded == total
    assert "RAISE NOTICE" in sql


def test_no_application_layer_reference():
    sql = MIGRATION.read_text(encoding="utf-8")
    for needle in ("web/", "api/", "import "):
        assert needle not in sql


def test_supabase_test_dir_cannot_shadow_the_supabase_library():
    assert not (TESTS_DIR / "__init__.py").exists()
    assert not (TESTS_DIR / "conftest.py").exists()
