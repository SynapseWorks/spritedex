BEGIN;

-- OAuth tokens are encrypted by the application before storage. The encryption
-- key must live outside PostgreSQL and outside Git.
CREATE TABLE IF NOT EXISTS inaturalist_accounts (
    user_id BIGINT PRIMARY KEY
        REFERENCES app_users(user_id) ON DELETE CASCADE,
    inat_user_id BIGINT NOT NULL UNIQUE,
    inat_login TEXT NOT NULL,
    oauth_access_token_encrypted TEXT NOT NULL,
    api_jwt_encrypted TEXT,
    api_jwt_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- OAuth state is server-side, single-use and short-lived. Only a digest is stored.
CREATE TABLE IF NOT EXISTS inaturalist_oauth_states (
    state_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inaturalist_oauth_states_expiry
ON inaturalist_oauth_states(expires_at);

ALTER TABLE encounters
    ADD COLUMN IF NOT EXISTS inat_observation_id BIGINT,
    ADD COLUMN IF NOT EXISTS inat_sync_status TEXT NOT NULL DEFAULT 'not_requested'
        CHECK (inat_sync_status IN ('not_requested', 'pending', 'synced', 'failed')),
    ADD COLUMN IF NOT EXISTS inat_sync_error TEXT,
    ADD COLUMN IF NOT EXISTS inat_quality_grade TEXT,
    ADD COLUMN IF NOT EXISTS inat_synced_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS inat_last_reconciled_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_encounters_inat_observation_id
ON encounters(inat_observation_id)
WHERE inat_observation_id IS NOT NULL;

COMMIT;
