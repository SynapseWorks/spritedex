BEGIN;

-- Pin SpriteDex function resolution so callers cannot influence object lookup via a
-- mutable search_path. PostGIS is installed in public on the Supabase V1 project,
-- so public must remain ahead of pg_temp for spatial functions/types.
ALTER FUNCTION public.refresh_user_region_progress(BIGINT)
SET search_path = public, pg_temp;

ALTER FUNCTION public.process_encounter_regions(INT)
SET search_path = public, pg_temp;

ALTER FUNCTION public.refresh_external_observation_regions(BIGINT)
SET search_path = public, pg_temp;

ALTER FUNCTION public.calculate_region_encounter_tiers(BIGINT, DATE, INT)
SET search_path = public, pg_temp;

ALTER FUNCTION public.refresh_region_game_state(BIGINT)
SET search_path = public, pg_temp;

COMMIT;
