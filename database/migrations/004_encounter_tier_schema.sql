BEGIN;

-- SpriteDex Encounter Tier v1
--
-- This migration deliberately separates:
--   1. biodiversity evidence imported from external sources,
--   2. the current Region/species game state,
--   3. a weekly history of calculated metrics.
--
-- Encounter tiers are GAMEPLAY descriptors based on community reporting patterns.
-- They are not claims about biological abundance or conservation rarity.

-- Minimal iNaturalist identifiers without performing the later full species -> taxa migration.
ALTER TABLE species
    ADD COLUMN IF NOT EXISTS inat_taxon_id BIGINT,
    ADD COLUMN IF NOT EXISTS iconic_taxon_name TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_species_inat_taxon_id
ON species(inat_taxon_id)
WHERE inat_taxon_id IS NOT NULL;

-- Region-level controls for whether public external records are suitable for fine-scale metrics.
ALTER TABLE regions
    ADD COLUMN IF NOT EXISTS external_metrics_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS max_external_accuracy_m INTEGER NOT NULL DEFAULT 1000
        CHECK (max_external_accuracy_m >= 0);

-- Current Region/species metrics and stability controls.
ALTER TABLE region_species
    ADD COLUMN IF NOT EXISTS encounter_rate NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS cohort_observer_days BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sampled_years SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS years_observed SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tier_confidence TEXT
        CHECK (tier_confidence IN ('low', 'medium', 'high')),
    ADD COLUMN IF NOT EXISTS seasonal_active BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS candidate_encounter_tier TEXT
        CHECK (candidate_encounter_tier IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional'
        )),
    ADD COLUMN IF NOT EXISTS candidate_tier_streak SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS encounter_tier_override TEXT
        CHECK (encounter_tier_override IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional'
        )),
    ADD COLUMN IF NOT EXISTS dex_eligible_override BOOLEAN,
    ADD COLUMN IF NOT EXISTS occurrence_status TEXT,
    ADD COLUMN IF NOT EXISTS occurrence_source TEXT,
    ADD COLUMN IF NOT EXISTS public_tier TEXT
        CHECK (public_tier IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional',
            'protected', 'unranked'
        )),
    ADD COLUMN IF NOT EXISTS tier_updated_at TIMESTAMPTZ;

-- encounter_score is the points awarded for the FIRST regional discovery.
-- It is intentionally separate from encounter_rate.
ALTER TABLE region_species
    ALTER COLUMN encounter_score SET DEFAULT 10;

-- Normalized public external observations. V1 is iNaturalist-first but source is explicit
-- so the table can later receive other licensed biodiversity sources.
CREATE TABLE IF NOT EXISTS external_observations (
    external_observation_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'inaturalist',
    source_observation_id BIGINT NOT NULL,
    species_id INT REFERENCES species(species_id) ON DELETE SET NULL,
    source_taxon_id BIGINT,
    observer_source_user_id BIGINT,
    observed_on DATE NOT NULL,
    created_at_source TIMESTAMPTZ,
    location GEOGRAPHY(Point, 4326),
    positional_accuracy_m NUMERIC(12,2),
    quality_grade TEXT,
    geoprivacy TEXT,
    taxon_geoprivacy TEXT,
    captive_cultivated BOOLEAN NOT NULL DEFAULT FALSE,
    source_uri TEXT,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_observation_id)
);

CREATE INDEX IF NOT EXISTS idx_external_observations_species_date
ON external_observations(species_id, observed_on);

CREATE INDEX IF NOT EXISTS idx_external_observations_location
ON external_observations USING GIST(location);

CREATE INDEX IF NOT EXISTS idx_external_observations_observer_date
ON external_observations(observer_source_user_id, observed_on);

-- Precomputed membership keeps weekly aggregation inexpensive.
CREATE TABLE IF NOT EXISTS external_observation_regions (
    external_observation_id BIGINT NOT NULL
        REFERENCES external_observations(external_observation_id) ON DELETE CASCADE,
    region_id BIGINT NOT NULL
        REFERENCES regions(region_id) ON DELETE CASCADE,
    membership_status TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (membership_status IN ('confirmed', 'uncertain', 'excluded')),
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (external_observation_id, region_id)
);

CREATE INDEX IF NOT EXISTS idx_external_observation_regions_region
ON external_observation_regions(region_id, external_observation_id);

-- Immutable-ish weekly history. This is what WORLD UPDATE compares from run to run.
CREATE TABLE IF NOT EXISTS region_species_metric_snapshots (
    metric_snapshot_id BIGSERIAL PRIMARY KEY,
    region_id BIGINT NOT NULL REFERENCES regions(region_id) ON DELETE CASCADE,
    species_id INT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
    as_of_date DATE NOT NULL,
    season_month SMALLINT NOT NULL CHECK (season_month BETWEEN 1 AND 12),
    lookback_years SMALLINT NOT NULL CHECK (lookback_years BETWEEN 1 AND 20),
    observation_count BIGINT NOT NULL DEFAULT 0,
    taxon_observer_days BIGINT NOT NULL DEFAULT 0,
    cohort_observer_days BIGINT NOT NULL DEFAULT 0,
    unique_observers BIGINT NOT NULL DEFAULT 0,
    sampled_years SMALLINT NOT NULL DEFAULT 0,
    years_observed SMALLINT NOT NULL DEFAULT 0,
    first_observed_on DATE,
    last_observed_on DATE,
    encounter_rate NUMERIC(12,8),
    evidence_confidence TEXT NOT NULL
        CHECK (evidence_confidence IN ('low', 'medium', 'high')),
    candidate_tier TEXT
        CHECK (candidate_tier IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional'
        )),
    applied_tier TEXT
        CHECK (applied_tier IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional'
        )),
    applied_public_tier TEXT
        CHECK (applied_public_tier IN (
            'familiar', 'notable', 'uncommon', 'elusive', 'exceptional',
            'protected', 'unranked'
        )),
    dex_eligible_auto BOOLEAN NOT NULL DEFAULT FALSE,
    seasonal_active_auto BOOLEAN NOT NULL DEFAULT FALSE,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (region_id, species_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_region_species_metric_snapshots_region_date
ON region_species_metric_snapshots(region_id, as_of_date DESC);

COMMIT;
