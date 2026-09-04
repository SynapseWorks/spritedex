BEGIN;

CREATE OR REPLACE FUNCTION calculate_region_encounter_tiers(
    p_region_id BIGINT,
    p_as_of_date DATE DEFAULT CURRENT_DATE,
    p_lookback_years INT DEFAULT 5
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_month INT := EXTRACT(MONTH FROM p_as_of_date)::INT;
    v_prev_month INT;
    v_next_month INT;
    v_start_year INT;
BEGIN
    IF p_lookback_years < 1 OR p_lookback_years > 20 THEN
        RAISE EXCEPTION 'lookback years must be between 1 and 20';
    END IF;

    v_prev_month := CASE WHEN v_month = 1 THEN 12 ELSE v_month - 1 END;
    v_next_month := CASE WHEN v_month = 12 THEN 1 ELSE v_month + 1 END;
    v_start_year := EXTRACT(YEAR FROM p_as_of_date)::INT - p_lookback_years + 1;

    -- Snapshot the current evidence first.
    INSERT INTO region_species_metric_snapshots (
        region_id,
        species_id,
        as_of_date,
        season_month,
        lookback_years,
        observation_count,
        taxon_observer_days,
        cohort_observer_days,
        unique_observers,
        sampled_years,
        years_observed,
        first_observed_on,
        last_observed_on,
        encounter_rate,
        evidence_confidence,
        candidate_tier,
        dex_eligible_auto,
        seasonal_active_auto,
        calculated_at
    )
    WITH regional AS (
        SELECT
            eo.external_observation_id,
            eo.species_id,
            eo.observer_source_user_id,
            eo.observed_on,
            COALESCE(NULLIF(s.iconic_taxon_name, ''), NULLIF(s.kingdom, ''), 'Other')
                AS cohort_name
        FROM external_observations eo
        JOIN external_observation_regions eor
          ON eor.external_observation_id = eo.external_observation_id
         AND eor.region_id = p_region_id
         AND eor.membership_status = 'confirmed'
        JOIN species s
          ON s.species_id = eo.species_id
        WHERE eo.species_id IS NOT NULL
          AND eo.observer_source_user_id IS NOT NULL
          AND eo.observed_on <= p_as_of_date
          AND EXTRACT(YEAR FROM eo.observed_on)::INT >= v_start_year
          AND EXTRACT(MONTH FROM eo.observed_on)::INT IN (
                v_prev_month, v_month, v_next_month
          )
          AND eo.quality_grade = 'research'
          AND COALESCE(eo.captive_cultivated, FALSE) = FALSE
          AND COALESCE(eo.geoprivacy, 'open') = 'open'
          AND COALESCE(eo.taxon_geoprivacy, 'open') = 'open'
    ),
    cohort AS (
        SELECT
            cohort_name,
            COUNT(DISTINCT (observer_source_user_id, observed_on)) AS cohort_observer_days,
            COUNT(DISTINCT EXTRACT(YEAR FROM observed_on))::SMALLINT AS sampled_years
        FROM regional
        GROUP BY cohort_name
    ),
    taxon AS (
        SELECT
            r.species_id,
            r.cohort_name,
            COUNT(*) AS observation_count,
            COUNT(DISTINCT (r.observer_source_user_id, r.observed_on)) AS taxon_observer_days,
            COUNT(DISTINCT r.observer_source_user_id) AS unique_observers,
            COUNT(DISTINCT EXTRACT(YEAR FROM r.observed_on))::SMALLINT AS years_observed,
            MIN(r.observed_on) AS first_observed_on,
            MAX(r.observed_on) AS last_observed_on
        FROM regional r
        GROUP BY r.species_id, r.cohort_name
    ),
    scored AS (
        SELECT
            t.*,
            c.cohort_observer_days,
            c.sampled_years,
            CASE
                WHEN c.cohort_observer_days = 0 THEN NULL
                ELSE t.taxon_observer_days::NUMERIC / c.cohort_observer_days
            END AS encounter_rate,
            CASE
                WHEN c.cohort_observer_days >= 300 AND c.sampled_years >= 3 THEN 'high'
                WHEN c.cohort_observer_days >= 100 AND c.sampled_years >= 2 THEN 'medium'
                ELSE 'low'
            END AS evidence_confidence
        FROM taxon t
        JOIN cohort c USING (cohort_name)
    ),
    classified AS (
        SELECT
            s.*,
            CASE
                WHEN s.evidence_confidence = 'low' THEN NULL
                WHEN s.encounter_rate >= 0.20 THEN 'familiar'
                WHEN s.encounter_rate >= 0.07 THEN 'notable'
                WHEN s.encounter_rate >= 0.02 THEN 'uncommon'
                WHEN s.encounter_rate >= 0.005 THEN 'elusive'
                ELSE 'exceptional'
            END AS candidate_tier,
            (
                s.taxon_observer_days >= 2
                AND s.unique_observers >= 2
                AND s.last_observed_on >= (p_as_of_date - INTERVAL '3 years')::DATE
            ) AS dex_eligible_auto
        FROM scored s
    )
    SELECT
        p_region_id,
        c.species_id,
        p_as_of_date,
        v_month,
        p_lookback_years,
        c.observation_count,
        c.taxon_observer_days,
        c.cohort_observer_days,
        c.unique_observers,
        c.sampled_years,
        c.years_observed,
        c.first_observed_on,
        c.last_observed_on,
        c.encounter_rate,
        c.evidence_confidence,
        c.candidate_tier,
        c.dex_eligible_auto,
        c.dex_eligible_auto,
        NOW()
    FROM classified c
    ON CONFLICT (region_id, species_id, as_of_date) DO UPDATE
    SET season_month = EXCLUDED.season_month,
        lookback_years = EXCLUDED.lookback_years,
        observation_count = EXCLUDED.observation_count,
        taxon_observer_days = EXCLUDED.taxon_observer_days,
        cohort_observer_days = EXCLUDED.cohort_observer_days,
        unique_observers = EXCLUDED.unique_observers,
        sampled_years = EXCLUDED.sampled_years,
        years_observed = EXCLUDED.years_observed,
        first_observed_on = EXCLUDED.first_observed_on,
        last_observed_on = EXCLUDED.last_observed_on,
        encounter_rate = EXCLUDED.encounter_rate,
        evidence_confidence = EXCLUDED.evidence_confidence,
        candidate_tier = EXCLUDED.candidate_tier,
        dex_eligible_auto = EXCLUDED.dex_eligible_auto,
        seasonal_active_auto = EXCLUDED.seasonal_active_auto,
        calculated_at = NOW();

    -- Seed newly documented Region/species pairs.
    INSERT INTO region_species (
        region_id,
        species_id,
        observation_count,
        unique_observer_count,
        observer_day_count,
        first_observed_at,
        last_observed_at,
        encounter_rate,
        cohort_observer_days,
        sampled_years,
        years_observed,
        tier_confidence,
        seasonal_active,
        encounter_tier,
        public_tier,
        encounter_score,
        dex_eligible,
        stats_as_of,
        calculated_at,
        tier_updated_at
    )
    SELECT
        m.region_id,
        m.species_id,
        m.observation_count,
        m.unique_observers,
        m.taxon_observer_days,
        m.first_observed_on::TIMESTAMPTZ,
        m.last_observed_on::TIMESTAMPTZ,
        m.encounter_rate,
        m.cohort_observer_days,
        m.sampled_years,
        m.years_observed,
        m.evidence_confidence,
        m.seasonal_active_auto,
        m.candidate_tier,
        CASE
            WHEN m.candidate_tier IS NULL THEN 'unranked'
            ELSE m.candidate_tier
        END,
        CASE m.candidate_tier
            WHEN 'familiar' THEN 10
            WHEN 'notable' THEN 20
            WHEN 'uncommon' THEN 40
            WHEN 'elusive' THEN 70
            WHEN 'exceptional' THEN 100
            ELSE 10
        END,
        m.dex_eligible_auto,
        p_as_of_date::TIMESTAMPTZ,
        NOW(),
        CASE WHEN m.candidate_tier IS NULL THEN NULL ELSE NOW() END
    FROM region_species_metric_snapshots m
    WHERE m.region_id = p_region_id
      AND m.as_of_date = p_as_of_date
    ON CONFLICT (region_id, species_id) DO NOTHING;

    -- Update evidence and candidate state for existing rows.
    WITH latest AS (
        SELECT *
        FROM region_species_metric_snapshots
        WHERE region_id = p_region_id
          AND as_of_date = p_as_of_date
    )
    UPDATE region_species rs
    SET observation_count = l.observation_count,
        unique_observer_count = l.unique_observers,
        observer_day_count = l.taxon_observer_days,
        first_observed_at = l.first_observed_on::TIMESTAMPTZ,
        last_observed_at = l.last_observed_on::TIMESTAMPTZ,
        encounter_rate = l.encounter_rate,
        cohort_observer_days = l.cohort_observer_days,
        sampled_years = l.sampled_years,
        years_observed = l.years_observed,
        tier_confidence = l.evidence_confidence,
        seasonal_active = COALESCE(rs.dex_eligible_override, l.seasonal_active_auto),
        dex_eligible = COALESCE(rs.dex_eligible_override, l.dex_eligible_auto),
        candidate_encounter_tier = CASE
            WHEN rs.encounter_tier_override IS NOT NULL THEN NULL
            WHEN l.candidate_tier IS NULL THEN NULL
            WHEN rs.encounter_tier IS NULL THEN NULL
            WHEN rs.encounter_tier = l.candidate_tier THEN NULL
            WHEN rs.candidate_encounter_tier = l.candidate_tier THEN l.candidate_tier
            ELSE l.candidate_tier
        END,
        candidate_tier_streak = CASE
            WHEN rs.encounter_tier_override IS NOT NULL THEN 0
            WHEN l.candidate_tier IS NULL THEN 0
            WHEN rs.encounter_tier IS NULL THEN 0
            WHEN rs.encounter_tier = l.candidate_tier THEN 0
            WHEN rs.candidate_encounter_tier = l.candidate_tier
                THEN rs.candidate_tier_streak + 1
            ELSE 1
        END,
        encounter_tier = CASE
            WHEN rs.encounter_tier_override IS NOT NULL
                THEN rs.encounter_tier_override
            WHEN rs.encounter_tier IS NULL AND l.candidate_tier IS NOT NULL
                THEN l.candidate_tier
            WHEN rs.encounter_tier = l.candidate_tier
                THEN rs.encounter_tier
            WHEN rs.candidate_encounter_tier = l.candidate_tier
                 AND rs.candidate_tier_streak + 1 >= 2
                THEN l.candidate_tier
            ELSE rs.encounter_tier
        END,
        tier_updated_at = CASE
            WHEN rs.encounter_tier_override IS NOT NULL
                 AND rs.encounter_tier IS DISTINCT FROM rs.encounter_tier_override
                THEN NOW()
            WHEN rs.encounter_tier IS NULL AND l.candidate_tier IS NOT NULL
                THEN NOW()
            WHEN rs.candidate_encounter_tier = l.candidate_tier
                 AND rs.candidate_tier_streak + 1 >= 2
                 AND rs.encounter_tier IS DISTINCT FROM l.candidate_tier
                THEN NOW()
            ELSE rs.tier_updated_at
        END,
        stats_as_of = p_as_of_date::TIMESTAMPTZ,
        calculated_at = NOW()
    FROM latest l
    WHERE rs.region_id = l.region_id
      AND rs.species_id = l.species_id;

    -- Public presentation and game points are derived from the stable tier.
    -- Sensitive taxa never advertise a rarity-like public tier and never receive
    -- a high-value rarity incentive.
    UPDATE region_species rs
    SET public_tier = CASE
            WHEN rs.sensitive_location THEN 'protected'
            WHEN rs.encounter_tier IS NULL THEN 'unranked'
            ELSE rs.encounter_tier
        END,
        encounter_score = CASE
            WHEN rs.sensitive_location THEN 20
            WHEN rs.encounter_tier = 'familiar' THEN 10
            WHEN rs.encounter_tier = 'notable' THEN 20
            WHEN rs.encounter_tier = 'uncommon' THEN 40
            WHEN rs.encounter_tier = 'elusive' THEN 70
            WHEN rs.encounter_tier = 'exceptional' THEN 100
            ELSE 10
        END
    WHERE rs.region_id = p_region_id;

    -- Record the stable post-hysteresis state in this week's snapshot so WORLD UPDATE
    -- can compare applied changes rather than noisy candidate values.
    UPDATE region_species_metric_snapshots m
    SET applied_tier = rs.encounter_tier,
        applied_public_tier = rs.public_tier
    FROM region_species rs
    WHERE m.region_id = p_region_id
      AND m.as_of_date = p_as_of_date
      AND rs.region_id = m.region_id
      AND rs.species_id = m.species_id;
END;
$$;

COMMIT;
