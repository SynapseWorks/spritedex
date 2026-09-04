BEGIN;

-- The first real SpriteDex pilot exposed an important distinction: Ganaraska Forest
-- is a publicly accessible, conservation-authority-owned managed forest, not a park
-- and not accurately described as a strictly protected area.
ALTER TABLE regions
    DROP CONSTRAINT IF EXISTS regions_region_type_check;

ALTER TABLE regions
    ADD CONSTRAINT regions_region_type_check CHECK (
        region_type IN (
            'country',
            'province_state',
            'municipality',
            'conservation_area',
            'park',
            'protected_area',
            'managed_forest',
            'watershed',
            'ecoregion',
            'trail_system',
            'campus',
            'partner_property',
            'custom'
        )
    );

COMMIT;
