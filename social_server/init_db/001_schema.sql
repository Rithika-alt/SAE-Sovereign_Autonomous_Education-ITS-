-- SAE Social Server — PostgreSQL schema
-- Runs automatically on first container start via docker-entrypoint-initdb.d
--
-- This is a separate database from the student's local sae_db — it holds
-- ONLY social data (accounts, friendships, messages). No lesson content,
-- progress, test results, or knowledge-graph data ever lives here.

CREATE TABLE IF NOT EXISTS social_accounts (
    social_id       TEXT PRIMARY KEY,          -- UUID string
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,              -- pbkdf2 hash:salt, same scheme as sae_system/auth
    discoverable    BOOLEAN NOT NULL DEFAULT FALSE,
    current_domain  TEXT NOT NULL DEFAULT '',    -- only populated if discoverable
    current_module  TEXT NOT NULL DEFAULT '',
    last_seen       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    social_id   TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS friendships (
    id              SERIAL PRIMARY KEY,
    requester_id    TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    addressee_id    TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (requester_id, addressee_id)
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id     TEXT PRIMARY KEY,               -- UUID string
    name        TEXT NOT NULL,
    created_by  TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id     TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    social_id   TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    PRIMARY KEY (room_id, social_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    sender_id       TEXT NOT NULL REFERENCES social_accounts(social_id) ON DELETE CASCADE,
    recipient_id    TEXT REFERENCES social_accounts(social_id) ON DELETE CASCADE,  -- 1:1 messages
    room_id         TEXT REFERENCES rooms(room_id) ON DELETE CASCADE,              -- group messages
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((recipient_id IS NOT NULL) OR (room_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_sessions_social      ON sessions(social_id);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id, status);
CREATE INDEX IF NOT EXISTS idx_friendships_requester ON friendships(requester_id, status);
CREATE INDEX IF NOT EXISTS idx_messages_dm          ON messages(sender_id, recipient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_dm_inverse   ON messages(recipient_id, sender_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_room         ON messages(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_accounts_discoverable ON social_accounts(discoverable, current_domain);
