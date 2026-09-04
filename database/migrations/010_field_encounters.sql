BEGIN;

-- Field encounter support for V1.
-- Taxon metadata remains on the legacy `species` table until the later species -> taxa migration.
ALTER TABLE species
    ADD COLUMN IF NOT EXISTS inat_rank TEXT,
    ADD COLUMN IF NOT EXISTS inat_default_photo_url TEXT,
    ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ;

-- v2 iNaturalist write APIs identify observations by UUID for media operations.
ALTER TABLE encounters
    ADD COLUMN IF NOT EXISTS inat_observation_uuid UUID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_encounters_inat_observation_uuid
ON encounters(inat_observation_uuid)
WHERE inat_observation_uuid IS NOT NULL;

-- Keep storage metadata separate from storage implementation. `file_path` is treated as
-- a provider-specific storage key rather than a public filesystem path.
ALTER TABLE encounter_media
    ADD COLUMN IF NOT EXISTS storage_provider TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS original_filename TEXT,
    ADD COLUMN IF NOT EXISTS content_type TEXT,
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT CHECK (size_bytes IS NULL OR size_bytes >= 0),
    ADD COLUMN IF NOT EXISTS sha256 TEXT,
    ADD COLUMN IF NOT EXISTS inat_observation_photo_id BIGINT,
    ADD COLUMN IF NOT EXISTS inat_sync_status TEXT NOT NULL DEFAULT 'not_requested'
        CHECK (inat_sync_status IN ('not_requested', 'pending', 'synced', 'failed')),
    ADD COLUMN IF NOT EXISTS inat_sync_error TEXT,
    ADD COLUMN IF NOT EXISTS inat_synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_encounter_media_encounter_type
ON encounter_media(encounter_id, media_type);

CREATE UNIQUE INDEX IF NOT EXISTS idx_encounter_media_inat_observation_photo_id
ON encounter_media(inat_observation_photo_id)
WHERE inat_observation_photo_id IS NOT NULL;

COMMIT;
