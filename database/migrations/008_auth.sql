BEGIN;

-- V1 local SpriteDex identity. Email remains nullable so legacy/prototype test users
-- created before authentication can continue to exist during migration.
ALTER TABLE app_users
    ADD COLUMN IF NOT EXISTS email TEXT,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email_lower
ON app_users (LOWER(email))
WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS auth_password_credentials (
    user_id BIGINT PRIMARY KEY
        REFERENCES app_users(user_id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Refresh sessions are server-revocable. Only a SHA-256 digest of the opaque
-- refresh token is stored, so a database leak does not expose usable refresh tokens.
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES app_users(user_id) ON DELETE CASCADE,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
ON auth_sessions(user_id, expires_at)
WHERE revoked_at IS NULL;

COMMIT;
