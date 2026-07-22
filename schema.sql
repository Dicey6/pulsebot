-- Pulse Bot — Supabase schema
-- Run this in your Supabase SQL editor

-- Invite codes (created from admin panel)
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT PRIMARY KEY,
    label       TEXT,
    is_used     BOOLEAN DEFAULT FALSE,
    used_by     BIGINT,
    used_at     DOUBLE PRECISION,
    created_at  DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
);

-- Users (created on first /start with valid invite code)
CREATE TABLE IF NOT EXISTS users (
    id                BIGINT PRIMARY KEY,   -- Telegram user ID
    username          TEXT,
    first_name        TEXT,
    balance_sol       DOUBLE PRECISION DEFAULT 5.0,
    realized_pnl_sol  DOUBLE PRECISION DEFAULT 0.0,
    invite_code       TEXT REFERENCES invite_codes(code),
    created_at        DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
);

-- Open positions
CREATE TABLE IF NOT EXISTS positions (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id           BIGINT REFERENCES users(id) ON DELETE CASCADE,
    contract_address  TEXT NOT NULL,
    name              TEXT,
    symbol            TEXT,
    quantity          DOUBLE PRECISION,
    entry_price       DOUBLE PRECISION,
    entry_mcap        DOUBLE PRECISION,
    invested_sol      DOUBLE PRECISION,
    entry_time        DOUBLE PRECISION,
    UNIQUE (user_id, contract_address)
);

-- Trade history
CREATE TABLE IF NOT EXISTS trades (
    id                TEXT PRIMARY KEY,
    user_id           BIGINT REFERENCES users(id) ON DELETE CASCADE,
    type              TEXT,
    contract_address  TEXT,
    symbol            TEXT,
    name              TEXT,
    quantity          DOUBLE PRECISION,
    price             DOUBLE PRECISION,
    mcap              DOUBLE PRECISION,
    sol_amount        DOUBLE PRECISION,
    pnl_pct           DOUBLE PRECISION,
    pnl_sol           DOUBLE PRECISION,
    timestamp         DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE INDEX IF NOT EXISTS positions_user_idx ON positions (user_id);
CREATE INDEX IF NOT EXISTS trades_user_idx    ON trades (user_id);
CREATE INDEX IF NOT EXISTS trades_ts_idx      ON trades (timestamp DESC);

-- Disable RLS — bot uses service role key
ALTER TABLE invite_codes DISABLE ROW LEVEL SECURITY;
ALTER TABLE users        DISABLE ROW LEVEL SECURITY;
ALTER TABLE positions    DISABLE ROW LEVEL SECURITY;
ALTER TABLE trades       DISABLE ROW LEVEL SECURITY;
