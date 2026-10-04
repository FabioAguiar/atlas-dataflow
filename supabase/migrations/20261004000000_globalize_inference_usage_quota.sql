-- S0300: one global anonymous inference budget per subject across datasets.
--
-- Forward-only upgrade of the M52-03 quota contract created by
-- 20260920000000_create_inference_usage.sql (kept byte-for-byte unchanged).
--
-- Before: 10 accepted units per (subject_id, dataset_slug) per window.
-- After:  10 accepted units per subject_id per fixed 10-minute UTC window,
--         across every dataset. The dataset slug is no longer quota state.
--
-- Contract after this migration:
--   public.reserve_inference_usage(p_subject_id text)
--     Canonical gateway entry point.
--   public.reserve_inference_usage(p_subject_id text, p_dataset_slug text)
--     COMPATIBILITY ONLY, so the pre-S0300 gateway keeps working between this
--     migration and the Edge Function update, and after an immediate Edge
--     Function rollback. It validates the slug as a bounded argument and then
--     reserves from the same global subject budget; the slug is never stored
--     and never part of a conflict key, so it cannot restore a per-dataset
--     budget.
--   Both return TABLE(allowed boolean, request_count integer,
--   retry_after_seconds integer) with unchanged semantics: allowed = false
--   means "rejected because of the limit" (no error, no increment), invalid
--   keys raise 22023, retry_after_seconds is ceil'd in [1, 600], and there is
--   no restoration or decrement path.
--   public.reserve_inference_usage_at(p_subject_id text, p_now timestamptz)
--     Owner-only controllable-clock seam for tests; replaces the
--     (text, text, timestamptz) seam.
--
-- Upgrade: the table is locked ACCESS EXCLUSIVE for the whole migration, so no
-- reservation can interleave between aggregation and the new primary key. A
-- reservation already waiting on the lock errors after commit (fail closed in
-- the gateway) instead of being counted against the removed key. Existing rows
-- are collapsed per (subject_id, window_start) to least(sum, 10): consumed
-- usage is never reduced and nothing is reset. The migration must run inside
-- one transaction (Supabase CLI, or psql --single-transaction); LOCK TABLE
-- refuses to run outside a transaction block.
--
-- Unchanged: RLS enabled with no policies, the 1..10 request_count and
-- 1..128 subject_id checks, the window_start index, the 7-day
-- public.purge_inference_usage() retention and its pg_cron schedule.

LOCK TABLE public.inference_usage IN ACCESS EXCLUSIVE MODE;

ALTER TABLE public.inference_usage DROP CONSTRAINT inference_usage_pkey;
ALTER TABLE public.inference_usage DROP CONSTRAINT inference_usage_dataset_slug_length_check;
ALTER TABLE public.inference_usage DROP COLUMN dataset_slug;

WITH per_dataset AS (
    DELETE FROM public.inference_usage
    RETURNING subject_id, window_start, request_count
)
INSERT INTO public.inference_usage (subject_id, window_start, request_count)
SELECT subject_id, window_start, least(sum(request_count), 10)::integer
  FROM per_dataset
 GROUP BY subject_id, window_start;

ALTER TABLE public.inference_usage
    ADD CONSTRAINT inference_usage_pkey PRIMARY KEY (subject_id, window_start);

DROP FUNCTION public.reserve_inference_usage_at(text, text, timestamptz);

CREATE OR REPLACE FUNCTION public.reserve_inference_usage_at(
    p_subject_id text,
    p_now timestamptz
)
RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_window timestamptz;
    v_count integer;
    v_allowed boolean;
BEGIN
    IF p_subject_id IS NULL OR pg_catalog.char_length(p_subject_id) NOT BETWEEN 1 AND 128 THEN
        RAISE EXCEPTION 'invalid subject_id' USING ERRCODE = '22023';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'invalid instant' USING ERRCODE = '22023';
    END IF;

    v_window := pg_catalog.date_bin(
        interval '10 minutes', p_now, timestamptz '1970-01-01 00:00:00+00'
    );

    INSERT INTO public.inference_usage AS u (subject_id, window_start, request_count)
    VALUES (p_subject_id, v_window, 1)
    ON CONFLICT (subject_id, window_start)
    DO UPDATE SET request_count = u.request_count + 1
    WHERE u.request_count < 10
    RETURNING u.request_count INTO v_count;

    IF FOUND THEN
        v_allowed := true;
    ELSE
        v_allowed := false;
        SELECT u.request_count INTO v_count
          FROM public.inference_usage AS u
         WHERE u.subject_id = p_subject_id
           AND u.window_start = v_window;
        v_count := COALESCE(v_count, 10);
    END IF;

    RETURN QUERY SELECT
        v_allowed,
        v_count,
        greatest(
            1,
            pg_catalog.ceil(
                extract(epoch FROM (v_window + interval '10 minutes' - p_now))
            )::integer
        );
END;
$fn$;

CREATE OR REPLACE FUNCTION public.reserve_inference_usage(
    p_subject_id text
)
RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $fn$
    SELECT r.allowed, r.request_count, r.retry_after_seconds
      FROM public.reserve_inference_usage_at(p_subject_id, pg_catalog.now()) AS r;
$fn$;

CREATE OR REPLACE FUNCTION public.reserve_inference_usage(
    p_subject_id text,
    p_dataset_slug text
)
RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $fn$
BEGIN
    -- Compatibility only: the slug is validated and then ignored; the subject
    -- is validated by reserve_inference_usage_at.
    IF p_dataset_slug IS NULL OR pg_catalog.char_length(p_dataset_slug) NOT BETWEEN 1 AND 128 THEN
        RAISE EXCEPTION 'invalid dataset_slug' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT r.allowed, r.request_count, r.retry_after_seconds
      FROM public.reserve_inference_usage_at(p_subject_id, pg_catalog.now()) AS r;
END;
$fn$;

COMMENT ON FUNCTION public.reserve_inference_usage(text) IS
    'Canonical S0300 reservation: 10 per subject per fixed 10-minute UTC window across all datasets.';
COMMENT ON FUNCTION public.reserve_inference_usage(text, text) IS
    'Compatibility only (pre-S0300 gateway signature): validates the slug, then reserves from the same global subject budget.';

REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, timestamptz) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.purge_inference_usage(interval) FROM PUBLIC;
REVOKE ALL ON TABLE public.inference_usage FROM PUBLIC;

-- Grants are re-evaluated for the replaced signatures. Role-dependent
-- statements are guarded so the same file applies to hosted Supabase and to a
-- plain disposable PostgreSQL that lacks these roles.
DO $roles$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format('REVOKE ALL ON TABLE public.inference_usage FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, timestamptz) FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text) FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.purge_inference_usage(interval) FROM %I', v_role);
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'service_role') THEN
        -- service_role reaches the table only through the definer wrappers and
        -- never through the controllable-clock seam.
        REVOKE ALL ON TABLE public.inference_usage FROM service_role;
        REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, timestamptz) FROM service_role;
        GRANT EXECUTE ON FUNCTION public.reserve_inference_usage(text) TO service_role;
        GRANT EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION public.purge_inference_usage(interval) TO service_role;
    END IF;
END
$roles$;
