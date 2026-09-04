BEGIN;

-- SpriteDex v1 user identity.
-- Authentication providers remain external to this core record.
CREATE TABLE app_users (
    user_id BIGSERIAL PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Existing prototype encounters may remain NULL until legacy data is assigned.
ALTER TABLE encounters
ADD COLUMN user_id BIGINT REFERENCES app_users(user_id);

CREATE INDEX idx_encounters_user_id
ON encounters(user_id);

COMMIT;
