BEGIN;

CREATE OR REPLACE FUNCTION refresh_external_observation_regions(
    p_region_id BIGINT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM external_observation_regions eor
    WHERE p_region_id IS NULL OR eor.region_id = p_region_id;

    INSERT INTO external_observation_regions (
        external_observation_id,
        region_id,
        membership_status,
        matched_at
    )
    SELECT
        eo.external_observation_id,
        r.region_id,
        'confirmed',
        NOW()
    FROM external_observations eo
    JOIN regions r
      ON r.status = 'active'
     AND r.external_metrics_enabled = TRUE
     AND (p_region_id IS NULL OR r.region_id = p_region_id)
     AND eo.location IS NOT NULL
     AND ST_Covers(r.boundary, eo.location::geometry)
    WHERE COALESCE(eo.geoprivacy, 'open') = 'open'
      AND COALESCE(eo.taxon_geoprivacy, 'open') = 'open'
      AND COALESCE(eo.captive_cultivated, FALSE) = FALSE
      AND eo.positional_accuracy_m IS NOT NULL
      AND eo.positional_accuracy_m <= r.max_external_accuracy_m
    ON CONFLICT (external_observation_id, region_id) DO UPDATE
    SET membership_status = EXCLUDED.membership_status,
        matched_at = EXCLUDED.matched_at;
END;
$$;

COMMIT;
