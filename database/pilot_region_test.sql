-- SpriteDex Region v1 smoke test
--
-- Run after schema.sql and migrations 001-003.
-- The transaction is rolled back, so this test leaves no permanent rows.

BEGIN;

DO $$
DECLARE
    v_user_id BIGINT;
    v_species_id INT;
    v_region_id BIGINT;
    v_encounter_id INT;
    v_membership_count BIGINT;
    v_discovered BIGINT;
    v_eligible BIGINT;
    v_completion NUMERIC(6,3);
    v_score NUMERIC(14,2);
BEGIN
    INSERT INTO app_users (display_name)
    VALUES ('SpriteDex Pilot Explorer')
    RETURNING user_id INTO v_user_id;

    INSERT INTO species (
        common_name,
        scientific_name,
        kingdom,
        category,
        description
    )
    VALUES (
        'American Robin',
        'Turdus migratorius',
        'Animalia',
        'Bird',
        'Temporary test species for the Region v1 smoke test.'
    )
    RETURNING species_id INTO v_species_id;

    -- Small artificial square used only to prove the spatial/game-state pipeline.
    INSERT INTO regions (
        name,
        slug,
        region_type,
        description,
        boundary,
        boundary_source,
        status,
        visibility,
        is_playable
    )
    VALUES (
        'SpriteDex Pilot Test Region',
        'spritedex-pilot-test-region',
        'custom',
        'Rollback-only test polygon for Region v1.',
        ST_Multi(
            ST_GeomFromText(
                'POLYGON((-78.51 44.08, -78.49 44.08, -78.49 44.10, -78.51 44.10, -78.51 44.08))',
                4326
            )
        ),
        'synthetic-test-fixture',
        'active',
        'private',
        TRUE
    )
    RETURNING region_id INTO v_region_id;

    INSERT INTO region_species (
        region_id,
        species_id,
        observation_count,
        unique_observer_count,
        observer_day_count,
        encounter_score,
        encounter_tier,
        dex_eligible,
        calculated_at
    )
    VALUES (
        v_region_id,
        v_species_id,
        100,
        25,
        50,
        10,
        'familiar',
        TRUE,
        NOW()
    );

    INSERT INTO encounters (
        species_id,
        user_id,
        encountered_at,
        location,
        location_description,
        confidence_level,
        notes
    )
    VALUES (
        v_species_id,
        v_user_id,
        NOW(),
        ST_SetSRID(ST_MakePoint(-78.50, 44.09), 4326)::geography,
        'Inside SpriteDex Pilot Test Region',
        'Confirmed',
        'Rollback-only Region v1 smoke test.'
    )
    RETURNING encounter_id INTO v_encounter_id;

    PERFORM process_encounter_regions(v_encounter_id);

    SELECT COUNT(*)
    INTO v_membership_count
    FROM encounter_regions
    WHERE encounter_id = v_encounter_id
      AND region_id = v_region_id
      AND membership_status = 'confirmed';

    IF v_membership_count <> 1 THEN
        RAISE EXCEPTION
            'Region membership test failed. Expected 1, got %',
            v_membership_count;
    END IF;

    SELECT
        discovered_species_count,
        eligible_species_count,
        completion_percent,
        regional_score
    INTO
        v_discovered,
        v_eligible,
        v_completion,
        v_score
    FROM user_region_progress
    WHERE user_id = v_user_id
      AND region_id = v_region_id;

    IF v_discovered <> 1
       OR v_eligible <> 1
       OR v_completion <> 100.000
       OR v_score <> 10.00 THEN
        RAISE EXCEPTION
            'Progress test failed. discovered=%, eligible=%, completion=%, score=%',
            v_discovered,
            v_eligible,
            v_completion,
            v_score;
    END IF;

    RAISE NOTICE 'SpriteDex Region v1 smoke test PASSED';
    RAISE NOTICE 'Encounter % matched Region %', v_encounter_id, v_region_id;
    RAISE NOTICE 'Regional Dex: %/% (% percent), score=%',
        v_discovered, v_eligible, v_completion, v_score;
END;
$$;

ROLLBACK;
