BEGIN;

CREATE OR REPLACE FUNCTION refresh_region_game_state(p_region_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_user_id BIGINT;
BEGIN
    UPDATE user_region_species urs
    SET regional_points = COALESCE(rs.encounter_score, 10),
        last_reconciled_at = NOW()
    FROM region_species rs
    WHERE urs.region_id = p_region_id
      AND rs.region_id = urs.region_id
      AND rs.species_id = urs.species_id;

    FOR v_user_id IN
        SELECT DISTINCT user_id
        FROM user_region_species
        WHERE region_id = p_region_id
    LOOP
        PERFORM refresh_user_region_progress(v_user_id);
    END LOOP;
END;
$$;

COMMIT;
