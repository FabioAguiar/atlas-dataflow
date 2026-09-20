-- M52-03: inference_usage quota table with atomic fixed-window reservation.
--
-- Contract (reused verbatim by M52-04 and M52-06):
--   public.reserve_inference_usage(p_subject_id text, p_dataset_slug text)
--     RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)
--   * Fixed 10-minute UTC window, limit 10 accepted units per
--     (subject_id, dataset_slug) per window. Both constants are hard-coded.
--   * allowed = false means "rejected because of the limit" (no error, no
--     increment). Any database error propagates as an RPC error and callers
--     must fail closed; NULL, empty or over-128-character keys raise 22023.
--   * retry_after_seconds is already ceil'd, in [1, 600], and is returned for
--     both allowed and rejected outcomes.
--   * There is no restoration or decrement path.
--
-- Access model: RLS is enabled with no policies; anon, authenticated and
-- PUBLIC hold no table privilege. Anonymous-auth visitors hold the
-- authenticated role, so both roles are revoked explicitly. Only service_role
-- may execute reserve_inference_usage and purge_inference_usage. The
-- controllable-clock seam reserve_inference_usage_at is owner-only and exists
-- solely so tests can pin the instant.
--
-- Retention: 7 days via public.purge_inference_usage(), scheduled daily with
-- pg_cron only when that extension is already installed. Without pg_cron the
-- operator (or an external schedule using service_role) must invoke the purge
-- function, otherwise storage is unbounded; the operator note is owned by
-- M52-06. This migration never runs CREATE EXTENSION.

CREATE TABLE public.inference_usage (
    subject_id   text        NOT NULL,
    dataset_slug text        NOT NULL,
    window_start timestamptz NOT NULL,
    request_count integer    NOT NULL,
    CONSTRAINT inference_usage_pkey PRIMARY KEY (subject_id, dataset_slug, window_start),
    CONSTRAINT inference_usage_request_count_check CHECK (request_count BETWEEN 1 AND 10),
    CONSTRAINT inference_usage_subject_id_length_check CHECK (char_length(subject_id) BETWEEN 1 AND 128),
    CONSTRAINT inference_usage_dataset_slug_length_check CHECK (char_length(dataset_slug) BETWEEN 1 AND 128)
);

CREATE INDEX inference_usage_window_start_idx ON public.inference_usage (window_start);

ALTER TABLE public.inference_usage ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.inference_usage FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.reserve_inference_usage_at(
    p_subject_id text,
    p_dataset_slug text,
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
    IF p_dataset_slug IS NULL OR pg_catalog.char_length(p_dataset_slug) NOT BETWEEN 1 AND 128 THEN
        RAISE EXCEPTION 'invalid dataset_slug' USING ERRCODE = '22023';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'invalid instant' USING ERRCODE = '22023';
    END IF;

    v_window := pg_catalog.date_bin(
        interval '10 minutes', p_now, timestamptz '1970-01-01 00:00:00+00'
    );

    INSERT INTO public.inference_usage AS u (subject_id, dataset_slug, window_start, request_count)
    VALUES (p_subject_id, p_dataset_slug, v_window, 1)
    ON CONFLICT (subject_id, dataset_slug, window_start)
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
           AND u.dataset_slug = p_dataset_slug
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
    p_subject_id text,
    p_dataset_slug text
)
RETURNS TABLE(allowed boolean, request_count integer, retry_after_seconds integer)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $fn$
    SELECT r.allowed, r.request_count, r.retry_after_seconds
      FROM public.reserve_inference_usage_at(p_subject_id, p_dataset_slug, pg_catalog.now()) AS r;
$fn$;

CREATE OR REPLACE FUNCTION public.purge_inference_usage(
    p_retention interval DEFAULT interval '7 days'
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_deleted bigint;
BEGIN
    IF p_retention IS NULL OR p_retention <= interval '0' THEN
        RAISE EXCEPTION 'invalid retention' USING ERRCODE = '22023';
    END IF;

    DELETE FROM public.inference_usage
     WHERE window_start < pg_catalog.now() - p_retention;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$fn$;

REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, text, timestamptz) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.purge_inference_usage(interval) FROM PUBLIC;

-- Role-dependent statements are guarded so the same file applies to hosted
-- Supabase and to a plain disposable PostgreSQL that lacks these roles.
DO $roles$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format('REVOKE ALL ON TABLE public.inference_usage FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, text, timestamptz) FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) FROM %I', v_role);
            EXECUTE pg_catalog.format('REVOKE EXECUTE ON FUNCTION public.purge_inference_usage(interval) FROM %I', v_role);
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'service_role') THEN
        -- service_role bypasses RLS but reaches the table only through the
        -- definer functions; hosted default privileges are revoked here.
        REVOKE ALL ON TABLE public.inference_usage FROM service_role;
        REVOKE EXECUTE ON FUNCTION public.reserve_inference_usage_at(text, text, timestamptz) FROM service_role;
        GRANT EXECUTE ON FUNCTION public.reserve_inference_usage(text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION public.purge_inference_usage(interval) TO service_role;
    END IF;
END
$roles$;

DO $cron$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule(
            'purge-inference-usage',
            '17 3 * * *',
            $job$SELECT public.purge_inference_usage()$job$
        );
    ELSE
        RAISE NOTICE 'pg_cron is not installed; schedule public.purge_inference_usage() externally (service_role).';
    END IF;
END
$cron$;
