BEGIN;

-- Cover foreign-key columns that are used by joins/cascades but were not indexed
-- by the original prototype schema. These keep maintenance and reconciliation from
-- degrading into table scans as V1 data grows.
CREATE INDEX IF NOT EXISTS idx_encounters_species_id
ON encounters(species_id);

CREATE INDEX IF NOT EXISTS idx_identification_candidates_encounter_id
ON identification_candidates(encounter_id);

CREATE INDEX IF NOT EXISTS idx_inaturalist_oauth_states_user_id
ON inaturalist_oauth_states(user_id);

CREATE INDEX IF NOT EXISTS idx_region_species_metric_snapshots_species_id
ON region_species_metric_snapshots(species_id);

CREATE INDEX IF NOT EXISTS idx_species_notes_species_id
ON species_notes(species_id);

CREATE INDEX IF NOT EXISTS idx_user_region_species_first_encounter_id
ON user_region_species(first_encounter_id)
WHERE first_encounter_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_region_species_species_id
ON user_region_species(species_id);

COMMIT;
