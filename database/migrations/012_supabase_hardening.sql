BEGIN;

-- Supabase production hardening for SpriteDex.
-- SpriteDex does not use Supabase's public Data API for application access; all
-- application reads/writes flow through the authenticated FastAPI service using a
-- direct PostgreSQL connection. Lock the exposed public schema down accordingly.

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tableowner = current_user
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', r.tablename);
    END LOOP;
END;
$$;

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
          AND sequence_owner = current_user
    LOOP
        EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM anon, authenticated', r.sequence_name);
    END LOOP;
END;
$$;

-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default. These are
-- SpriteDex-internal server operations rather than Supabase RPC endpoints.
REVOKE EXECUTE ON FUNCTION public.refresh_user_region_progress(BIGINT)
FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.process_encounter_regions(INT)
FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.refresh_external_observation_regions(BIGINT)
FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.calculate_region_encounter_tiers(BIGINT, DATE, INT)
FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.refresh_region_game_state(BIGINT)
FROM PUBLIC, anon, authenticated;

COMMIT;
