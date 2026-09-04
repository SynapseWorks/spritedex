BEGIN;

-- A SpriteDex Region is a playable geographic area owned by SpriteDex.
-- It may optionally reference an iNaturalist Place, but iNaturalist Places do not
-- define the Region model.
CREATE TABLE regions (
    region_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    region_type TEXT NOT NULL CHECK (
        region_type IN (
            'country',
            'province_state',
            'municipality',
            'conservation_area',
            'park',
            'protected_area',
            'watershed',
            'ecoregion',
            'trail_system',
            'campus',
            'partner_property',
            'custom'
        )
    ),
    description TEXT,
    boundary GEOMETRY(MultiPolygon, 4326) NOT NULL,
    boundary_source TEXT,
    boundary_source_ref TEXT,
    boundary_updated_at TIMESTAMPTZ,
    inat_place_id BIGINT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft', 'active', 'retired')),
    visibility TEXT NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'unlisted', 'private', 'hidden')),
    is_playable BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_regions_boundary
ON regions USING GIST (boundary);

CREATE INDEX idx_regions_inat_place
ON regions(inat_place_id)
WHERE inat_place_id IS NOT NULL;

CREATE INDEX idx_regions_type
ON regions(region_type);

-- Region relationships form a graph rather than forcing all geography into one tree.
CREATE TABLE region_relationships (
    parent_region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    child_region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL CHECK (
        relationship_type IN (
            'contained_by',
            'administratively_within',
            'watershed_within',
            'ecologically_within',
            'managed_within',
            'related_to'
        )
    ),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (parent_region_id, child_region_id, relationship_type),
    CHECK (parent_region_id <> child_region_id)
);

CREATE INDEX idx_region_relationships_child
ON region_relationships(child_region_id);

-- One optional primary display parent keeps breadcrumbs simple without pretending
-- all region relationships are hierarchical.
CREATE UNIQUE INDEX idx_region_relationships_primary_parent
ON region_relationships(child_region_id)
WHERE is_primary = TRUE;

-- One encounter may belong to many overlapping/nested Regions.
CREATE TABLE encounter_regions (
    encounter_id INT NOT NULL
        REFERENCES encounters(encounter_id) ON DELETE CASCADE,
    region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    membership_status TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (membership_status IN ('confirmed', 'uncertain', 'excluded')),
    membership_method TEXT NOT NULL DEFAULT 'spatial'
        CHECK (membership_method IN ('spatial', 'manual', 'imported')),
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (encounter_id, region_id)
);

CREATE INDEX idx_encounter_regions_region
ON encounter_regions(region_id);

-- What a species means inside one Region. Encounter tier is a gameplay concept,
-- distinct from scientific conservation status.
CREATE TABLE region_species (
    region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    species_id INT NOT NULL
        REFERENCES species(species_id) ON DELETE CASCADE,
    observation_count BIGINT NOT NULL DEFAULT 0,
    unique_observer_count BIGINT NOT NULL DEFAULT 0,
    observer_day_count BIGINT NOT NULL DEFAULT 0,
    recent_observation_count BIGINT NOT NULL DEFAULT 0,
    first_observed_at TIMESTAMPTZ,
    last_observed_at TIMESTAMPTZ,
    encounter_score NUMERIC(10,4),
    encounter_tier TEXT CHECK (
        encounter_tier IN (
            'familiar',
            'notable',
            'uncommon',
            'elusive',
            'exceptional'
        )
    ),
    dex_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    establishment_status TEXT,
    conservation_status TEXT,
    sensitive_location BOOLEAN NOT NULL DEFAULT FALSE,
    stats_as_of TIMESTAMPTZ,
    calculated_at TIMESTAMPTZ,
    PRIMARY KEY (region_id, species_id)
);

CREATE INDEX idx_region_species_species
ON region_species(species_id);

CREATE INDEX idx_region_species_dex
ON region_species(region_id, dex_eligible);

CREATE INDEX idx_region_species_tier
ON region_species(region_id, encounter_tier);

-- A row means the user has discovered this species in this Region.
CREATE TABLE user_region_species (
    user_id BIGINT NOT NULL
        REFERENCES app_users(user_id) ON DELETE CASCADE,
    region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    species_id INT NOT NULL
        REFERENCES species(species_id) ON DELETE CASCADE,
    first_encounter_id INT
        REFERENCES encounters(encounter_id) ON DELETE SET NULL,
    first_observed_at TIMESTAMPTZ,
    last_observed_at TIMESTAMPTZ,
    encounter_count BIGINT NOT NULL DEFAULT 0,
    verified_encounter_count BIGINT NOT NULL DEFAULT 0,
    regional_points NUMERIC(12,2) NOT NULL DEFAULT 0,
    last_reconciled_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, region_id, species_id)
);

CREATE INDEX idx_user_region_species_region
ON user_region_species(region_id, user_id);

CREATE INDEX idx_user_region_species_user
ON user_region_species(user_id);

-- Cached progress prevents expensive aggregate queries on every page load.
CREATE TABLE user_region_progress (
    user_id BIGINT NOT NULL
        REFERENCES app_users(user_id) ON DELETE CASCADE,
    region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    discovered_species_count BIGINT NOT NULL DEFAULT 0,
    eligible_species_count BIGINT NOT NULL DEFAULT 0,
    completion_percent NUMERIC(6,3) NOT NULL DEFAULT 0,
    regional_score NUMERIC(14,2) NOT NULL DEFAULT 0,
    first_encounter_at TIMESTAMPTZ,
    last_encounter_at TIMESTAMPTZ,
    leaderboard_rank BIGINT,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, region_id)
);

CREATE INDEX idx_user_region_progress_region_score
ON user_region_progress(region_id, regional_score DESC);

COMMIT;
