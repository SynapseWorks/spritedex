BEGIN;

-- Rebuild cached regional progress for one user from canonical discovery rows.
CREATE OR REPLACE FUNCTION refresh_user_region_progress(p_user_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM user_region_progress
    WHERE user_id = p_user_id;

    WITH region_ids AS (
        SELECT DISTINCT region_id
        FROM user_region_species
        WHERE user_id = p_user_id
    ),
    eligible AS (
        SELECT
            region_id,
            COUNT(*) FILTER (WHERE dex_eligible) AS eligible_species_count
        FROM region_species
        GROUP BY region_id
    ),
    discovered AS (
        SELECT
            urs.region_id,
            COUNT(*) FILTER (WHERE COALESCE(rs.dex_eligible, FALSE))
                AS discovered_species_count,
            COALESCE(SUM(urs.regional_points), 0) AS regional_score
        FROM user_region_species urs
        LEFT JOIN region_species rs
          ON rs.region_id = urs.region_id
         AND rs.species_id = urs.species_id
        WHERE urs.user_id = p_user_id
        GROUP BY urs.region_id
    ),
    encounter_dates AS (
        SELECT
            er.region_id,
            MIN(e.encountered_at) AS first_encounter_at,
            MAX(e.encountered_at) AS last_encounter_at
        FROM encounters e
        JOIN encounter_regions er
          ON er.encounter_id = e.encounter_id
         AND er.membership_status = 'confirmed'
        WHERE e.user_id = p_user_id
        GROUP BY er.region_id
    )
    INSERT INTO user_region_progress (
        user_id,
        region_id,
        discovered_species_count,
        eligible_species_count,
        completion_percent,
        regional_score,
        first_encounter_at,
        last_encounter_at,
        leaderboard_rank,
        calculated_at
    )
    SELECT
        p_user_id,
        r.region_id,
        COALESCE(d.discovered_species_count, 0),
        COALESCE(e.eligible_species_count, 0),
        CASE
            WHEN COALESCE(e.eligible_species_count, 0) = 0 THEN 0
            ELSE ROUND(
                100.0 * COALESCE(d.discovered_species_count, 0)
                / e.eligible_species_count,
                3
            )
        END,
        COALESCE(d.regional_score, 0),
        ed.first_encounter_at,
        ed.last_encounter_at,
        NULL,
        NOW()
    FROM region_ids r
    LEFT JOIN eligible e ON e.region_id = r.region_id
    LEFT JOIN discovered d ON d.region_id = r.region_id
    LEFT JOIN encounter_dates ed ON ed.region_id = r.region_id;
END;
$$;

-- Core v1 processing function.
-- 1. Recalculates spatial Region membership for one encounter using ST_Covers.
-- 2. Rebuilds that user's discovery rows for the encounter's species.
-- 3. Rebuilds the user's cached Region progress.
--
-- This is intentionally idempotent: re-running it should produce the same state.
CREATE OR REPLACE FUNCTION process_encounter_regions(p_encounter_id INT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_user_id BIGINT;
    v_species_id INT;
BEGIN
    SELECT user_id, species_id
    INTO v_user_id, v_species_id
    FROM encounters
    WHERE encounter_id = p_encounter_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Encounter % does not exist', p_encounter_id;
    END IF;

    -- Only remove memberships computed spatially. Manual/imported decisions survive.
    DELETE FROM encounter_regions
    WHERE encounter_id = p_encounter_id
      AND membership_method = 'spatial';

    INSERT INTO encounter_regions (
        encounter_id,
        region_id,
        membership_status,
        membership_method,
        matched_at
    )
    SELECT
        e.encounter_id,
        r.region_id,
        'confirmed',
        'spatial',
        NOW()
    FROM encounters e
    JOIN regions r
      ON e.location IS NOT NULL
     AND ST_Covers(r.boundary, e.location::geometry)
    WHERE e.encounter_id = p_encounter_id
      AND r.status = 'active'
      AND r.is_playable = TRUE
    ON CONFLICT (encounter_id, region_id) DO NOTHING;

    -- Legacy / anonymous prototype encounters may still receive Region membership,
    -- but cannot participate in personal Dex progress until assigned to a user.
    IF v_user_id IS NULL OR v_species_id IS NULL THEN
        RETURN;
    END IF;

    -- Rebuild all Region discoveries for this user/species pair. Recalculation instead
    -- of incremental counters means moving/editing an encounter cannot double-count it.
    DELETE FROM user_region_species
    WHERE user_id = v_user_id
      AND species_id = v_species_id;

    INSERT INTO user_region_species (
        user_id,
        region_id,
        species_id,
        first_encounter_id,
        first_observed_at,
        last_observed_at,
        encounter_count,
        verified_encounter_count,
        regional_points,
        last_reconciled_at
    )
    SELECT
        e.user_id,
        er.region_id,
        e.species_id,
        (ARRAY_AGG(
            e.encounter_id
            ORDER BY e.encountered_at, e.encounter_id
        ))[1],
        MIN(e.encountered_at),
        MAX(e.encountered_at),
        COUNT(DISTINCT e.encounter_id),
        0,
        COALESCE(rs.encounter_score, 0),
        NOW()
    FROM encounters e
    JOIN encounter_regions er
      ON er.encounter_id = e.encounter_id
     AND er.membership_status = 'confirmed'
    LEFT JOIN region_species rs
      ON rs.region_id = er.region_id
     AND rs.species_id = e.species_id
    WHERE e.user_id = v_user_id
      AND e.species_id = v_species_id
    GROUP BY
        e.user_id,
        er.region_id,
        e.species_id,
        rs.encounter_score;

    PERFORM refresh_user_region_progress(v_user_id);
END;
$$;

COMMIT;
