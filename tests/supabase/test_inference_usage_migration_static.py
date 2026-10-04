"""M52-03 / S0300: static invariants for the inference_usage migrations.

Two migrations define the current quota contract:

* the historical M52 base migration (``MIGRATION``), which stays byte-for-byte
  unchanged and still creates the per-dataset table and functions; and
* the S0300 forward migration (``GLOBAL_MIGRATION``), which upgrades the key to
  (subject_id, window_start), adds the subject-only canonical reservation and
  keeps the two-argument signature as a global compatibility wrapper.

Reads the migrations as text only; no database and no driver is needed, so this
module always runs. Live behaviour is covered by the reservation live module.
"""

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
MIGRATION = MIGRATIONS_DIR / "20260920000000_create_inference_usage.sql"
GLOBAL_MIGRATION = MIGRATIONS_DIR / "20261004000000_globalize_inference_usage_quota.sql"
BASE_MIGRATION_SHA256 = "9a58d172762ac3ef387e672f7f7da4a6dbf97c08381655b170b0e5b9e19f9cd3"
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


GLOBAL_FUNCTION_SIGNATURES = {
    "seam": "public.reserve_inference_usage_at(text, timestamptz)",
    "canonical": "public.reserve_inference_usage(text)",
    "compatibility": "public.reserve_inference_usage(text, text)",
    "purge": "public.purge_inference_usage(interval)",
}


def _sql(path: Path = MIGRATION) -> str:
    """Migration text with `--` comments removed."""
    raw = path.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())


def _global_sql() -> str:
    return _sql(GLOBAL_MIGRATION)


def _global_function_chunks() -> dict[str, str]:
    """S0300 function bodies keyed by ``name(argument names)``."""
    chunks = {}
    for part in re.split(r"CREATE OR REPLACE FUNCTION ", _global_sql())[1:]:
        match = re.match(r"public\.(\w+)\((.*?)\)\s*RETURNS", part, re.DOTALL)
        args = ",".join(re.findall(r"(p_\w+)\s+\w+", match.group(2)))
        chunks[f"{match.group(1)}({args})"] = part
    return chunks


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


def test_migration_files_exist_at_supabase_cli_path_in_order():
    assert MIGRATION.is_file() and GLOBAL_MIGRATION.is_file()
    assert re.fullmatch(r"\d{14}_create_inference_usage\.sql", MIGRATION.name)
    assert re.fullmatch(r"\d{14}_globalize_inference_usage_quota\.sql", GLOBAL_MIGRATION.name)
    assert sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql")) == [
        MIGRATION.name,
        GLOBAL_MIGRATION.name,
    ]


def test_historical_base_migration_is_byte_for_byte_unchanged():
    assert hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == BASE_MIGRATION_SHA256


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


# --- S0300 forward migration: current quota contract ---


def test_forward_migration_locks_the_table_before_any_change():
    statements = [line for line in _global_sql().splitlines() if line.strip()]
    assert statements[0] == "LOCK TABLE public.inference_usage IN ACCESS EXCLUSIVE MODE;"
    for forbidden in ("BEGIN;", "COMMIT;", "ROLLBACK;", "CONCURRENTLY"):
        assert forbidden not in _global_sql()


def test_forward_migration_removes_the_dataset_dimension_from_the_key():
    sql = _global_sql()
    assert "DROP CONSTRAINT inference_usage_pkey" in sql
    assert "DROP CONSTRAINT inference_usage_dataset_slug_length_check" in sql
    assert "DROP COLUMN dataset_slug" in sql
    assert "ADD CONSTRAINT inference_usage_pkey PRIMARY KEY (subject_id, window_start)" in sql
    assert "ADD COLUMN" not in sql
    assert "TRUNCATE" not in sql
    assert re.findall(r"ON CONFLICT \(([^)]*)\)", sql) == ["subject_id, window_start"]
    assert "CREATE TABLE" not in sql and "CREATE INDEX" not in sql
    # The 1..10 and subject length checks from the base migration are kept.
    assert "inference_usage_request_count_check" not in sql
    assert "inference_usage_subject_id_length_check" not in sql


def test_forward_migration_collapses_existing_rows_by_subject_and_window_clamped_at_ten():
    sql = _global_sql()
    collapse = re.search(r"WITH per_dataset AS \((.*?)\)\s*INSERT INTO(.*?);", sql, re.DOTALL)
    assert collapse, "aggregation statement not found"
    assert "DELETE FROM public.inference_usage" in collapse.group(1)
    assert "least(sum(request_count), 10)" in collapse.group(2)
    assert "GROUP BY subject_id, window_start" in collapse.group(2)
    order = [
        sql.index("LOCK TABLE"),
        sql.index("DROP COLUMN dataset_slug"),
        sql.index("WITH per_dataset AS"),
        sql.index("PRIMARY KEY (subject_id, window_start)"),
    ]
    assert order == sorted(order)


def test_forward_migration_defines_exactly_the_canonical_compatibility_and_seam_functions():
    chunks = _global_function_chunks()
    assert set(chunks) == {
        "reserve_inference_usage_at(p_subject_id,p_now)",
        "reserve_inference_usage(p_subject_id)",
        "reserve_inference_usage(p_subject_id,p_dataset_slug)",
    }
    assert "DROP FUNCTION public.reserve_inference_usage_at(text, text, timestamptz);" in _global_sql()
    assert re.findall(r"^DROP FUNCTION (.*);$", _global_sql(), re.MULTILINE) == [
        "public.reserve_inference_usage_at(text, text, timestamptz)"
    ]
    for name, chunk in chunks.items():
        header = chunk.split("AS $fn$")[0]
        assert "RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)" in header, name
        assert "SECURITY DEFINER" in header, name
        assert "SET search_path = ''" in header, name


def test_seam_is_a_single_atomic_subject_only_upsert_with_hard_coded_constants():
    seam = _global_function_chunks()["reserve_inference_usage_at(p_subject_id,p_now)"]
    assert "dataset_slug" not in seam
    assert "INSERT INTO public.inference_usage AS u (subject_id, window_start, request_count)" in seam
    assert "ON CONFLICT (subject_id, window_start)" in seam
    assert "DO UPDATE SET request_count = u.request_count + 1" in seam
    assert "WHERE u.request_count < 10" in seam
    assert "interval '10 minutes', p_now, timestamptz '1970-01-01 00:00:00+00'" in seam
    assert "NOT BETWEEN 1 AND 128" in seam and "ERRCODE = '22023'" in seam
    for forbidden in ("pg_advisory", "SERIALIZABLE", "EXCEPTION WHEN"):
        assert forbidden not in _global_sql()


def test_canonical_wrapper_takes_the_subject_only_and_statement_time():
    chunk = _global_function_chunks()["reserve_inference_usage(p_subject_id)"]
    assert "dataset" not in chunk
    assert "reserve_inference_usage_at(p_subject_id, pg_catalog.now())" in chunk


def test_compatibility_wrapper_validates_the_slug_and_delegates_to_the_global_budget():
    chunk = _global_function_chunks()["reserve_inference_usage(p_subject_id,p_dataset_slug)"]
    assert "pg_catalog.char_length(p_dataset_slug) NOT BETWEEN 1 AND 128" in chunk
    assert "ERRCODE = '22023'" in chunk
    assert "reserve_inference_usage_at(p_subject_id, pg_catalog.now())" in chunk
    body = chunk.split("AS $fn$")[1]
    # The slug is only validated: never inserted, keyed or forwarded.
    assert body.count("p_dataset_slug") == 2
    assert "INSERT" not in body and "ON CONFLICT" not in body
    raw = GLOBAL_MIGRATION.read_text(encoding="utf-8")
    assert "COMMENT ON FUNCTION public.reserve_inference_usage(text, text) IS\n    'Compatibility only" in raw


def test_forward_migration_re_evaluates_grants_for_every_signature():
    sql = _global_sql()
    for signature in GLOBAL_FUNCTION_SIGNATURES.values():
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC" in sql, signature
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM %I" in sql, signature
    assert "REVOKE ALL ON TABLE public.inference_usage FROM PUBLIC" in sql
    assert "ARRAY['anon', 'authenticated']" in sql
    assert "REVOKE ALL ON TABLE public.inference_usage FROM %I" in sql
    assert "REVOKE ALL ON TABLE public.inference_usage FROM service_role" in sql
    assert f"REVOKE EXECUTE ON FUNCTION {GLOBAL_FUNCTION_SIGNATURES['seam']} FROM service_role" in sql
    grants = re.findall(r"GRANT\s+(.*?)\s+TO\s+(\w+)", sql, re.DOTALL)
    assert sorted(grants) == sorted(
        (f"EXECUTE ON FUNCTION {GLOBAL_FUNCTION_SIGNATURES[key]}", "service_role")
        for key in ("canonical", "compatibility", "purge")
    )
    assert "CREATE POLICY" not in sql
    assert "DISABLE ROW LEVEL SECURITY" not in sql
    assert "GRANT USAGE" not in sql and "ON SCHEMA" not in sql


def test_forward_migration_keeps_retention_and_touches_nothing_else():
    sql = _global_sql()
    assert "purge_inference_usage" in sql
    assert "CREATE OR REPLACE FUNCTION public.purge_inference_usage" not in sql
    assert "cron." not in sql
    assert "CREATE EXTENSION" not in sql
    assert not re.search(r"\bauth\.", sql)
    created = re.findall(r"^CREATE (?:OR REPLACE )?(\w+)", sql, re.MULTILINE)
    assert created == ["FUNCTION", "FUNCTION", "FUNCTION"]
    assert {table for table in re.findall(r"^(?:ALTER|LOCK) TABLE (\S+)", sql, re.MULTILINE)} == {
        "public.inference_usage"
    }
    for needle in ("web/", "api/", "import "):
        assert needle not in GLOBAL_MIGRATION.read_text(encoding="utf-8")
    for token in ("payload", "jwt", "email", "prediction", "ip_address"):
        assert token not in sql.lower()
