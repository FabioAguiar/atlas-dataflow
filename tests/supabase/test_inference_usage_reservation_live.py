"""M52-03: live PostgreSQL tests for the inference_usage reservation.

Requires a disposable PostgreSQL 15+ database reached through psycopg (v3)
using the superuser DSN in ATLAS_TEST_POSTGRES_DSN. The fixture creates the
NOLOGIN roles anon, authenticated and service_role when absent, drops and
re-applies the migration, and truncates the table between tests.

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

MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "supabase"
    / "migrations"
    / "20260920000000_create_inference_usage.sql"
)
UTC = dt.timezone.utc
SUBJECT = "subject-placeholder-a"
SLUG = "dataset-placeholder-a"
PARALLEL_WORKERS = 40
RESERVE_SQL = (
    "SELECT allowed, request_count, retry_after_seconds "
    "FROM public.reserve_inference_usage(%s::text, %s::text)"
)
RESERVE_AT_SQL = (
    "SELECT allowed, request_count, retry_after_seconds "
    "FROM public.reserve_inference_usage_at(%s::text, %s::text, %s::timestamptz)"
)


def _at(hour, minute, second=0, micro=0):
    return dt.datetime(2026, 1, 1, hour, minute, second, micro, tzinfo=UTC)


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
        conn.execute("DROP FUNCTION IF EXISTS public.reserve_inference_usage(text, text)")
        conn.execute("DROP FUNCTION IF EXISTS public.reserve_inference_usage_at(text, text, timestamptz)")
        conn.execute("DROP FUNCTION IF EXISTS public.purge_inference_usage(interval)")
        conn.execute("DROP TABLE IF EXISTS public.inference_usage")
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP FUNCTION IF EXISTS public.reserve_inference_usage(text, text)")
        conn.execute("DROP FUNCTION IF EXISTS public.reserve_inference_usage_at(text, text, timestamptz)")
        conn.execute("DROP FUNCTION IF EXISTS public.purge_inference_usage(interval)")
        conn.execute("DROP TABLE IF EXISTS public.inference_usage")


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


def _reserve_at(connection, subject, slug, instant):
    return connection.execute(RESERVE_AT_SQL, (subject, slug, instant)).fetchone()


def _stored_count(connection, subject=SUBJECT, slug=SLUG):
    row = connection.execute(
        "SELECT COALESCE(sum(request_count), 0) FROM public.inference_usage "
        "WHERE subject_id = %s AND dataset_slug = %s",
        (subject, slug),
    ).fetchone()
    return row[0]


def _wait_for_safe_window(margin_seconds=20):
    """Avoid a real 10-minute boundary passing while a wrapper test runs."""
    remaining = 600 - (time.time() % 600)
    if remaining < margin_seconds:
        time.sleep(remaining + 1)


def _run_parallel(dsn, sql, params_for_worker, workers=PARALLEL_WORKERS):
    barrier = threading.Barrier(workers)
    results = [None] * workers
    errors = []

    def worker(index):
        try:
            with psycopg.connect(dsn, autocommit=True) as connection:
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


def test_parallel_reservations_never_exceed_limit_at_a_pinned_instant(migrated, conn):
    instant = _at(10, 5)
    results = _run_parallel(migrated, RESERVE_AT_SQL, lambda i: (SUBJECT, SLUG, instant))
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert sum(1 for allowed, _, _ in results if not allowed) == PARALLEL_WORKERS - 10
    assert _stored_count(conn) == 10


def test_parallel_reservations_through_the_public_wrapper(migrated, conn):
    _wait_for_safe_window()
    results = _run_parallel(migrated, RESERVE_SQL, lambda i: (SUBJECT, SLUG), workers=32)
    assert sum(1 for allowed, _, _ in results if allowed) == 10
    assert _stored_count(conn) == 10


def test_rejection_reports_ten_and_never_increments(conn):
    instant = _at(10, 5)
    for expected in range(1, 11):
        allowed, count, retry = _reserve_at(conn, SUBJECT, SLUG, instant)
        assert (allowed, count) == (True, expected)
    for _ in range(3):
        allowed, count, retry = _reserve_at(conn, SUBJECT, SLUG, instant)
        assert (allowed, count) == (False, 10)
        assert 1 <= retry <= 600
    assert _stored_count(conn) == 10


def test_subjects_and_datasets_are_counted_independently(conn):
    instant = _at(10, 5)
    for _ in range(10):
        _reserve_at(conn, SUBJECT, SLUG, instant)
    assert _reserve_at(conn, SUBJECT, SLUG, instant)[0] is False
    assert _reserve_at(conn, "subject-placeholder-b", SLUG, instant) == (True, 1, 300)
    assert _reserve_at(conn, SUBJECT, "dataset-placeholder-b", instant) == (True, 1, 300)


def test_windows_roll_over_at_the_exact_boundary_instant(conn):
    last_instant_of_window = _at(9, 59, 59, 999000)
    for _ in range(10):
        assert _reserve_at(conn, SUBJECT, SLUG, last_instant_of_window)[0] is True
    assert _reserve_at(conn, SUBJECT, SLUG, last_instant_of_window)[0] is False
    boundary = _at(10, 0)
    assert _reserve_at(conn, SUBJECT, SLUG, boundary) == (True, 1, 600)
    next_boundary = _at(10, 10)
    assert _reserve_at(conn, SUBJECT, SLUG, _at(10, 9, 59)) == (True, 2, 1)
    assert _reserve_at(conn, SUBJECT, SLUG, next_boundary) == (True, 1, 600)


def test_retry_after_is_ceiled_and_within_bounds(conn):
    assert _reserve_at(conn, SUBJECT, SLUG, _at(9, 59, 59, 999000))[2] == 1
    assert _reserve_at(conn, SUBJECT, SLUG, _at(10, 0))[2] == 600
    assert _reserve_at(conn, SUBJECT, SLUG, _at(10, 4, 30))[2] == 330
    assert _reserve_at(conn, SUBJECT, SLUG, _at(10, 4, 30, 1))[2] == 330


def test_window_alignment_ignores_session_time_zone(conn):
    conn.execute("SET TIME ZONE 'Asia/Kolkata'")
    try:
        assert _reserve_at(conn, SUBJECT, SLUG, _at(10, 0)) == (True, 1, 600)
        starts = conn.execute("SELECT window_start FROM public.inference_usage").fetchall()
    finally:
        conn.execute("RESET TIME ZONE")
    assert starts == [(_at(10, 0),)]


@pytest.mark.parametrize(
    "subject, slug",
    [
        (None, SLUG),
        ("", SLUG),
        (SUBJECT, None),
        (SUBJECT, ""),
        ("x" * 129, SLUG),
        (SUBJECT, "x" * 129),
    ],
)
def test_invalid_keys_raise_and_write_nothing(conn, subject, slug):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        _reserve_at(conn, subject, slug, _at(10, 5))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        conn.execute("SET ROLE service_role")
        try:
            conn.execute(RESERVE_SQL, (subject, slug))
        finally:
            conn.execute("RESET ROLE")
    assert conn.execute("SELECT count(*) FROM public.inference_usage").fetchone()[0] == 0


def test_null_instant_raises(conn):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        _reserve_at(conn, SUBJECT, SLUG, None)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_visitor_roles_are_denied_the_table_and_every_function(conn, role):
    statements = [
        "SELECT count(*) FROM public.inference_usage",
        "INSERT INTO public.inference_usage VALUES ('s', 'd', now(), 1)",
        "UPDATE public.inference_usage SET request_count = 1",
        "DELETE FROM public.inference_usage",
        RESERVE_SQL.replace("%s", "'s'", 2),
        RESERVE_AT_SQL.replace("%s::text", "'s'", 2).replace("%s::timestamptz", "now()"),
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
            "DELETE FROM public.inference_usage",
            RESERVE_AT_SQL.replace("%s::text", "'s'", 2).replace("%s::timestamptz", "now()"),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
        allowed, count, retry = conn.execute(RESERVE_SQL, (SUBJECT, SLUG)).fetchone()
        assert (allowed, count) == (True, 1)
        assert 1 <= retry <= 600
        assert conn.execute("SELECT public.purge_inference_usage()").fetchone()[0] == 0


def test_purge_deletes_rows_older_than_seven_days_and_keeps_newer(conn):
    conn.execute(
        "INSERT INTO public.inference_usage VALUES "
        "('old-a', 'd', now() - interval '8 days', 3), "
        "('old-b', 'd', now() - interval '7 days 1 hour', 1), "
        "('new-a', 'd', now() - interval '6 days', 2), "
        "('new-b', 'd', now(), 1)"
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


def test_stored_row_contains_only_the_four_columns(conn):
    _reserve_at(conn, SUBJECT, SLUG, _at(10, 5))
    columns = [
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'inference_usage' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    assert columns == ["subject_id", "dataset_slug", "window_start", "request_count"]
    assert conn.execute("SELECT * FROM public.inference_usage").fetchall() == [
        (SUBJECT, SLUG, _at(10, 0), 1)
    ]
