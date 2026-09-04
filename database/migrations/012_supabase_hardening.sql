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
    LOOP
        EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM anon, authenticated', r.sequence_name);
    END LOOP;
END;
$$;

-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default. SpriteDex's
-- spatial/game-state functions are internal server operations, not public RPCs.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT p.oid::regprocedure AS signature
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prokind = 'f'
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated', r.signature);
    END LOOP;
END;
$$;

COMMIT;
