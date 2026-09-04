-- SpriteDex Encounter Tier v1 smoke test
-- Requires schema.sql + migrations 001-007.
-- Runs inside a transaction and rolls back all test data.

BEGIN;

DO $$
DECLARE
    v_region BIGINT;
    v_robin INT;
    v_maple INT;
    v_i BIGINT;
    v_rate NUMERIC;
    v_tier TEXT;
BEGIN
    INSERT INTO regions (
        name, slug, region_type, boundary, boundary_source,
        status, visibility, is_playable, max_external_accuracy_m
    ) VALUES (
        'Tier Test Region',
        'tier-test-region',
        'custom',
        ST_Multi(ST_GeomFromText(
            'POLYGON((-78.1 43.9,-77.9 43.9,-77.9 44.1,-78.1 44.1,-78.1 43.9))',
            4326
        )),
        'test', 'active', 'private', TRUE, 1000
    ) RETURNING region_id INTO v_region;

    INSERT INTO species (
        common_name, scientific_name, kingdom, category, inat_taxon_id, iconic_taxon_name
    ) VALUES (
        'American Robin', 'Turdus migratorius', 'Animalia', 'Bird', 12727, 'Aves'
    ) RETURNING species_id INTO v_robin;

    INSERT INTO species (
        common_name, scientific_name, kingdom, category, inat_taxon_id, iconic_taxon_name
    ) VALUES (
        'Test Maple', 'Acer testii', 'Plantae', 'Plant', 999999991, 'Plantae'
    ) RETURNING species_id INTO v_maple;

    -- Create 120 bird observer-days across historical September windows.
    -- Robin is recorded on 30 of them => encounter_rate = 0.25 => Familiar.
    FOR v_i IN 1..120 LOOP
        INSERT INTO external_observations (
            source_observation_id,
            species_id,
            source_taxon_id,
            observer_source_user_id,
            observed_on,
            location,
            positional_accuracy_m,
            quality_grade,
            geoprivacy,
            taxon_geoprivacy
        ) VALUES (
            900000000 + v_i,
            CASE WHEN v_i <= 30 THEN v_robin ELSE v_maple END,
            CASE WHEN v_i <= 30 THEN 12727 ELSE 999999991 END,
            v_i,
            CASE WHEN v_i <= 60 THEN DATE '2024-09-15' ELSE DATE '2025-09-15' END,
            ST_SetSRID(ST_MakePoint(-78.0, 44.0), 4326)::geography,
            10,
            'research',
            'open',
            'open'
        );
    END LOOP;

    -- The 90 non-robin rows must be in the same cohort to form a bird denominator.
    UPDATE species
    SET iconic_taxon_name = 'Aves'
    WHERE species_id = v_maple;

    PERFORM refresh_external_observation_regions(v_region);
    PERFORM calculate_region_encounter_tiers(v_region, DATE '2026-09-02', 5);

    SELECT encounter_rate, encounter_tier
    INTO v_rate, v_tier
    FROM region_species
    WHERE region_id = v_region
      AND species_id = v_robin;

    IF ABS(v_rate - 0.25) > 0.000001 THEN
        RAISE EXCEPTION 'Expected robin encounter rate 0.25, got %', v_rate;
    END IF;

    IF v_tier <> 'familiar' THEN
        RAISE EXCEPTION 'Expected familiar tier, got %', v_tier;
    END IF;

    RAISE NOTICE 'SpriteDex Encounter Tier v1 smoke test PASSED';
END;
$$;

ROLLBACK;
