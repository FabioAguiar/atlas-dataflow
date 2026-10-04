"""M52-03 / S0300: live PostgreSQL tests for the inference_usage reservation.

Requires a disposable PostgreSQL 15+ database reached through psycopg (v3)
using the superuser DSN in ATLAS_TEST_POSTGRES_DSN. The fixture creates the
NOLOGIN roles anon, authenticated and service_role when absent, drops the
quota objects, applies the historical M52 base migration and then the S0300
forward migration (in one transaction), and truncates the table between tests.
Upgrade tests rebuild the schema from the base migration with seeded
per-dataset rows before applying the forward migration.

Only synthetic subjects and dataset slugs are used. Never point the DSN at a
production database.

When psycopg or the DSN is missing these tests SKIP with an explicit reason;
a skip is NOT evidence that the acceptance criteria hold. Set
ATLAS_REQUIRE_POSTGRES_TESTS=1 to make missing prerequisites fail instead.
"""

import contextlib
import datetime as dt
import os
import threading
import time
from pathlib import Path

import pytest

REQUIRE_LIVE = os.environ.get("ATLAS_REQUIRE_POSTGRES_TESTS") == "1"
DSN = os.environ.get("ATLAS_TEST_POSTGRES_DSN")

if REQUIRE_LIVE:
    import psycopg
else:
    psycopg = pytest.importorskip(
        "psycopg", reason="psycopg (v3) is not installed; live reservation tests NOT PROVEN"
    )

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "supabase" / "migrations"
BASE_MIGRATION = MIGRATIONS_DIR / "20260920000000_create_inference_usage.sql"
GLOBAL_MIGRATION = MIGRATIONS_DIR / "20261004000000_globalize_inference_usage_quota.sql"
UTC = dt.timezone.utc
SUBJECT = "subject-placeholder-a"
OTHER_SUBJECT = "subject-placeholder-b"
SLUG = "dataset-placeholder-a"
SLUGS = [f"dataset-placeholder-{suffix}" for suffix in "abcde"]
PARALLEL_WORKERS = 40
RESERVE_SQL = (
    "SELECT allowed, request_count, retry_after_seconds "
    "FROM public.reserve_inference_usage(%s::text)"
)
RESERVE_COMPAT_SQL = (
    "SELECT allowed, request_count, retry_after_seconds "
    "FROM public.reserve_inference_usage(%s::text, %s::text)"
)
RESERVE_AT_SQL = (
    "SELECT allowed, request_count, retry_after_seconds "
    "FROM public.reserve_inference_usage_at(%s::text, %s::timestamptz)"
)
DROP_STATEMENTS = (
    "DROP FUNCTION IF EXISTS public.reserve_inference_usage(text, text)",
    "DROP FUNCTION IF EXISTS public.reserve_inference_usage(text)",
    "DROP FUNCTION IF EXISTS public.reserve_inference_usage_at(text, text, timestamptz)",
    "DROP FUNCTION IF EXISTS public.reserve_inference_usage_at(text, timestamptz)",
    "DROP FUNCTION IF EXISTS public.purge_inference_usage(interval)",
    "DROP TABLE IF EXISTS public.inference_usage",
)


def _at(hour, minute, second=0, micro=0):
    return dt.datetime(2026, 1, 1, hour, minute, second, micro, tzinfo=UTC)


def _drop_all(connection):
    for statement in DROP_STATEMENTS:
        connection.execute(statement)


def _rebuild(dsn, seed_rows=()):
    """Base migration, optional per-dataset seed rows, then the S0300 upgrade."""
    with psycopg.connect(dsn, autocommit=True) as connection:
        _drop_all(connection)
        with connection.transaction():
            connection.execute(BASE_MIGRATION.read_text(encoding="utf-8"))
        for row in seed_rows:
            connection.execute(
                "INSERT INTO public.inference_usage "
                "(subject_id, dataset_slug, window_start, request_count) VALUES (%s, %s, %s, %s)",
                row,
            )
        with connection.transaction():
            connection.execute(GLOBAL_MIGRATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dsn():
    if not DSN:
        message = "ATLAS_TEST_POSTGRES_DSN is not set; live reservation tests NOT PROVEN"
        if REQUIRE_LIVE:
            pytest.fail(message)
        pytest.skip(message)
    return DSN


@pytest.fixture(scope="module")
def migrated(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        for role in ("anon", "authenticated", "service_role"):
            conn.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
            )
        conn.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role")
    _rebuild(dsn)
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as conn:
        _drop_all(conn)


@pytest.fixture
def conn(migrated):
    with psycopg.connect(migrated, autocommit=True) as connection:
        connection.execute("TRUNCATE public.inference_usage")
        yield connection


@contextlib.contextmanager
def _as_role(connection, role):
    connection.execute(f"SET ROLE {role}")
    try:
        yield
    finally:
        connection.execute("RESET ROLE")


def _reserve_at(connection, subject, instant):
    return connection.execute(RESERVE_AT_SQL, (subject, instant)).fetchone()


def _rows(connection):
    return connection.execute(
        "SELECT subject_id, window_start, request_count FROM public.inference_usage "
        "ORDER BY subject_id, window_start"
    ).fetchall()


def _stored_count(connection, subject=SUBJECT):
    row = connection.execute(
        "SELECT COALESCE(sum(request_count), 0) FROM public.inference_usage WHERE subject_id = %s",
        (subject,),
    ).fetchone()
    return row[0]


def _wait_for_safe_window(margin_seconds=20):
    """Avoid a real 10-minute boundary passing while a wrapper test runs."""
    remaining = 600 - (time.time() % 600)
    if remaining < margin_seconds:
        time.sleep(remaining + 1)


def _run_parallel(dsn, sql, params_for_worker, workers=PARALLEL_WORKERS, role=None):
    barrier = threading.Barrier(workers)
    results = [None] * workers
    errors = []

    def worker(index):
        try:
            with psycopg.connect(dsn, autocommit=True) as connection:
                if role is not None:
                    connection.execute(f"SET ROLE {role}")
                barrier.wait(timeout=30)
                results[index] = connection.execute(sql, params_for_worker(index)).fetchone()
        except Exception as exc:  # surfaced below; never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    return results


# --- upgrade from the historical per-dataset schema ---


def test_upgrade_sums_per_dataset_rows_below_the_limit(migrated):
    window, next_window = _at(10, 0), _at(10, 10)
    _rebuild(
        migrated,
        [
            (SUBJECT, SLUGS[0], window, 4),
            (SUBJECT, SLUGS[1], window, 3),
            (SUBJECT, SLUGS[0], next_window, 5),
            (OTHER_SUBJECT, SLUGS[0], window, 2),
        ],
    )
    with psycopg.connect(migrated, autocommit=True) as connection:
        assert _rows(connection) == [
            (SUBJECT, window, 7),
            (SUBJECT, next_window, 5),
            (OTHER_SUBJECT, window, 2),
        ]
        # The consumed 7 carries over: three more fit, the fourth is rejected.
        for expected in (8, 9, 10):
            assert _reserve_at(connection, SUBJECT, _at(10, 5)) == (True, expected, 300)
        assert _reserve_at(connection, SUBJECT, _at(10, 5)) == (False, 10, 300)


def test_upgrade_clamps_summed_rows_to_ten_and_keeps_the_subject_blocked(migrated):
    window = _at(10, 0)
    _rebuild(
        migrated,
        [
            (SUBJECT, SLUGS[0], window, 7),
            (SUBJECT, SLUGS[1], window, 6),
            (OTHER_SUBJECT, SLUGS[0], window, 10),
            (OTHER_SUBJECT, SLUGS[1], window, 10),
            (OTHER_SUBJECT, SLUGS[2], window, 10),
        ],
    )
    with psycopg.connect(migrated, autocommit=True) as connection:
        assert _rows(connection) == [(SUBJECT, window, 10), (OTHER_SUBJECT, window, 10)]
        assert _reserve_at(connection, SUBJECT, _at(10, 9)) == (False, 10, 60)
        assert _reserve_at(connection, OTHER_SUBJECT, _at(10, 9)) == (False, 10, 60)
        assert _reserve_at(connection, SUBJECT, _at(10, 10)) == (True, 1, 600)


def test_upgrade_of_an_empty_table_yields_an_empty_table(migrated):
    _rebuild(migrated)
    with psycopg.connect(migrated, autocommit=True) as connection:
        assert _rows(connection) == []


# --- final schema contract ---


def test_final_table_has_exactly_subject_window_and_count(conn):
    columns = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'inference_usage' "
        "ORDER BY ordinal_position"
    ).fetchall()
    assert columns == [
        ("subject_id", "text"),
        ("window_start", "timestamp with time zone"),
        ("request_count", "integer"),
    ]


def test_primary_key_is_subject_and_window_without_a_dataset_dimension(conn):
    key = conn.execute(
        "SELECT array_agg(a.attname ORDER BY k.ord) "
        "FROM pg_index i "
        "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
        "WHERE i.indrelid = 'public.inference_usage'::regclass AND i.indisprimary"
    ).fetchone()[0]
    assert key == ["subject_id", "window_start"]
    indexes = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
        "AND tablename = 'inference_usage' ORDER BY indexname"
    ).fetchall()
    assert len(indexes) == 2
    assert all("dataset_slug" not in row[0] for row in indexes)


def test_count_and_subject_checks_remain_and_the_slug_check_is_gone(conn):
    checks = dict(
        conn.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'public.inference_usage'::regclass AND contype = 'c'"
        ).fetchall()
    )
    assert set(checks) == {
        "inference_usage_request_count_check",
        "inference_usage_subject_id_length_check",
    }
    for value in (0, 11):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO public.inference_usage VALUES (%s, now(), %s)", (SUBJECT, value)
            )


def test_rls_enabled_without_policies(conn):
    assert conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.inference_usage'::regclass"
    ).fetchone()[0] is True
    assert conn.execute(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = 'inference_usage'"
    ).fetchone()[0] == 0


def test_only_the_expected_function_signatures_exist(conn):
    signatures = conn.execute(
        "SELECT p.oid::regprocedure::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname LIKE '%inference_usage%' ORDER BY 1"
    ).fetchall()
    assert [row[0] for row in signatures] == [
        "purge_inference_usage(interval)",
        "reserve_inference_usage(text)",
        "reserve_inference_usage(text,text)",
        "reserve_inference_usage_at(text,timestamp with time zone)",
    ]


# --- global reservation semantics ---


def test_parallel_reservations_never_exceed_limit_at_a_pinned_instant(migrated, conn):
    instant = _at(10, 5)
    results = _run_parallel(migrated, RESERVE_AT_SQL, lambda i: (SUBJECT, instant))
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert sum(1 for allowed, _, _ in results if not allowed) == PARALLEL_WORKERS - 10
    assert _rows(conn) == [(SUBJECT, _at(10, 0), 10)]


def test_parallel_canonical_wrapper_reservations(migrated, conn):
    _wait_for_safe_window()
    results = _run_parallel(migrated, RESERVE_SQL, lambda i: (SUBJECT,), role="service_role")
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert _stored_count(conn) == 10


def test_parallel_compatibility_reservations_across_five_datasets_accept_ten_total(migrated, conn):
    _wait_for_safe_window()
    results = _run_parallel(
        migrated,
        RESERVE_COMPAT_SQL,
        lambda i: (SUBJECT, SLUGS[i % len(SLUGS)]),
        role="service_role",
    )
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert sum(1 for allowed, _, _ in results if not allowed) == PARALLEL_WORKERS - 10
    rows = _rows(conn)
    assert len(rows) == 1 and rows[0][0] == SUBJECT and rows[0][2] == 10


def test_parallel_mixed_canonical_and_compatibility_share_one_budget(migrated, conn):
    _wait_for_safe_window()

    def params(i):
        return (SUBJECT,) if i % 2 == 0 else (SUBJECT, SLUGS[i % len(SLUGS)])

    sql_for = {True: RESERVE_SQL, False: RESERVE_COMPAT_SQL}
    results = [None] * PARALLEL_WORKERS
    errors = []
    barrier = threading.Barrier(PARALLEL_WORKERS)

    def worker(index):
        try:
            with psycopg.connect(migrated, autocommit=True) as connection:
                connection.execute("SET ROLE service_role")
                barrier.wait(timeout=30)
                results[index] = connection.execute(
                    sql_for[index % 2 == 0], params(index)
                ).fetchone()
        except Exception as exc:  # surfaced below; never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(PARALLEL_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert _stored_count(conn) == 10


def test_compatibility_wrapper_is_global_across_dataset_slugs_sequentially(conn):
    _wait_for_safe_window()
    with _as_role(conn, "service_role"):
        for expected in range(1, 10):
            allowed, count, _ = conn.execute(RESERVE_COMPAT_SQL, (SUBJECT, SLUGS[0])).fetchone()
            assert (allowed, count) == (True, expected)
        assert conn.execute(RESERVE_COMPAT_SQL, (SUBJECT, SLUGS[1])).fetchone()[:2] == (True, 10)
        allowed, count, retry = conn.execute(RESERVE_COMPAT_SQL, (SUBJECT, SLUGS[2])).fetchone()
        assert (allowed, count) == (False, 10)
        assert 1 <= retry <= 600
        # The canonical wrapper sees the same exhausted budget.
        assert conn.execute(RESERVE_SQL, (SUBJECT,)).fetchone()[:2] == (False, 10)
    assert _rows(conn)[0][::2] == (SUBJECT, 10)
    assert len(_rows(conn)) == 1


def test_canonical_wrapper_reserves_then_rejects_at_ten(conn):
    _wait_for_safe_window()
    with _as_role(conn, "service_role"):
        for expected in range(1, 11):
            assert conn.execute(RESERVE_SQL, (SUBJECT,)).fetchone()[:2] == (True, expected)
        for _ in range(3):
            allowed, count, retry = conn.execute(RESERVE_SQL, (SUBJECT,)).fetchone()
            assert (allowed, count) == (False, 10)
            assert 1 <= retry <= 600
    assert _stored_count(conn) == 10


def test_rejection_reports_ten_and_never_increments(conn):
    instant = _at(10, 5)
    for expected in range(1, 11):
        assert _reserve_at(conn, SUBJECT, instant)[:2] == (True, expected)
    for _ in range(3):
        allowed, count, retry = _reserve_at(conn, SUBJECT, instant)
        assert (allowed, count) == (False, 10)
        assert 1 <= retry <= 600
    assert _stored_count(conn) == 10


def test_different_subjects_keep_independent_budgets(conn):
    instant = _at(10, 5)
    for _ in range(10):
        _reserve_at(conn, SUBJECT, instant)
    assert _reserve_at(conn, SUBJECT, instant)[0] is False
    assert _reserve_at(conn, OTHER_SUBJECT, instant) == (True, 1, 300)


def test_windows_roll_over_at_the_exact_boundary_instant(conn):
    last_instant_of_window = _at(9, 59, 59, 999000)
    for _ in range(10):
        assert _reserve_at(conn, SUBJECT, last_instant_of_window)[0] is True
    assert _reserve_at(conn, SUBJECT, last_instant_of_window)[0] is False
    assert _reserve_at(conn, SUBJECT, _at(10, 0)) == (True, 1, 600)
    assert _reserve_at(conn, SUBJECT, _at(10, 9, 59)) == (True, 2, 1)
    assert _reserve_at(conn, SUBJECT, _at(10, 10)) == (True, 1, 600)


def test_retry_after_is_ceiled_and_within_bounds(conn):
    assert _reserve_at(conn, SUBJECT, _at(9, 59, 59, 999000))[2] == 1
    assert _reserve_at(conn, SUBJECT, _at(10, 0))[2] == 600
    assert _reserve_at(conn, SUBJECT, _at(10, 4, 30))[2] == 330
    assert _reserve_at(conn, SUBJECT, _at(10, 4, 30, 1))[2] == 330


def test_window_alignment_ignores_session_time_zone(conn):
    conn.execute("SET TIME ZONE 'Asia/Kolkata'")
    try:
        assert _reserve_at(conn, SUBJECT, _at(10, 0)) == (True, 1, 600)
        starts = conn.execute("SELECT window_start FROM public.inference_usage").fetchall()
    finally:
        conn.execute("RESET TIME ZONE")
    assert starts == [(_at(10, 0),)]


# --- validation ---


@pytest.mark.parametrize("subject", [None, "", "x" * 129])
def test_invalid_subjects_raise_on_every_entry_point_and_write_nothing(conn, subject):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        _reserve_at(conn, subject, _at(10, 5))
    with _as_role(conn, "service_role"):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            conn.execute(RESERVE_SQL, (subject,))
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            conn.execute(RESERVE_COMPAT_SQL, (subject, SLUG))
    assert conn.execute("SELECT count(*) FROM public.inference_usage").fetchone()[0] == 0


@pytest.mark.parametrize("slug", [None, "", "x" * 129])
def test_compatibility_wrapper_rejects_invalid_slugs_and_writes_nothing(conn, slug):
    with _as_role(conn, "service_role"):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            conn.execute(RESERVE_COMPAT_SQL, (SUBJECT, slug))
    assert conn.execute("SELECT count(*) FROM public.inference_usage").fetchone()[0] == 0


def test_null_instant_raises(conn):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        _reserve_at(conn, SUBJECT, None)


# --- privileges ---


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_visitor_roles_are_denied_the_table_and_every_function(conn, role):
    statements = [
        "SELECT count(*) FROM public.inference_usage",
        "INSERT INTO public.inference_usage VALUES ('s', now(), 1)",
        "UPDATE public.inference_usage SET request_count = 1",
        "DELETE FROM public.inference_usage",
        RESERVE_SQL.replace("%s", "'s'"),
        RESERVE_COMPAT_SQL.replace("%s", "'s'"),
        RESERVE_AT_SQL.replace("%s::text", "'s'").replace("%s::timestamptz", "now()"),
        "SELECT public.purge_inference_usage()",
    ]
    with _as_role(conn, role):
        for statement in statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_service_role_reaches_the_table_only_through_the_granted_functions(conn):
    with _as_role(conn, "service_role"):
        for statement in (
            "SELECT count(*) FROM public.inference_usage",
            "INSERT INTO public.inference_usage VALUES ('s', now(), 1)",
            "DELETE FROM public.inference_usage",
            RESERVE_AT_SQL.replace("%s::text", "'s'").replace("%s::timestamptz", "now()"),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
        allowed, count, retry = conn.execute(RESERVE_SQL, (SUBJECT,)).fetchone()
        assert (allowed, count) == (True, 1)
        assert 1 <= retry <= 600
        assert conn.execute(RESERVE_COMPAT_SQL, (SUBJECT, SLUG)).fetchone()[:2] == (True, 2)
        assert conn.execute("SELECT public.purge_inference_usage()").fetchone()[0] == 0


def test_function_privilege_matrix(conn):
    functions = {
        "public.reserve_inference_usage(text)": {"service_role"},
        "public.reserve_inference_usage(text, text)": {"service_role"},
        "public.reserve_inference_usage_at(text, timestamptz)": set(),
        "public.purge_inference_usage(interval)": {"service_role"},
    }
    for signature, allowed_roles in functions.items():
        for role in ("anon", "authenticated", "service_role"):
            granted = conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, signature)
            ).fetchone()[0]
            assert granted is (role in allowed_roles), (signature, role)
    for role in ("anon", "authenticated", "service_role"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert conn.execute(
                "SELECT has_table_privilege(%s, 'public.inference_usage', %s)", (role, privilege)
            ).fetchone()[0] is False, (role, privilege)


# --- retention ---


def test_purge_deletes_rows_older_than_seven_days_and_keeps_newer(conn):
    conn.execute(
        "INSERT INTO public.inference_usage VALUES "
        "('old-a', now() - interval '8 days', 3), "
        "('old-b', now() - interval '7 days 1 hour', 1), "
        "('new-a', now() - interval '6 days', 2), "
        "('new-b', now(), 1)"
    )
    with _as_role(conn, "service_role"):
        assert conn.execute("SELECT public.purge_inference_usage()").fetchone()[0] == 2
    remaining = conn.execute(
        "SELECT subject_id FROM public.inference_usage ORDER BY subject_id"
    ).fetchall()
    assert remaining == [("new-a",), ("new-b",)]


def test_purge_rejects_non_positive_retention(conn):
    for value in (None, "0 seconds", "-1 day"):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            conn.execute("SELECT public.purge_inference_usage(%s::interval)", (value,))


def test_stored_row_contains_only_subject_window_and_count(conn):
    _reserve_at(conn, SUBJECT, _at(10, 5))
    assert conn.execute("SELECT * FROM public.inference_usage").fetchall() == [
        (SUBJECT, _at(10, 0), 1)
    ]
