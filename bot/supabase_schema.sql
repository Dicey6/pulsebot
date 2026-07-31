-- Pulse Trading Bot — Supabase / Postgres schema
-- Run this in the Supabase SQL editor before first deploy.

-- ──────────────────────────────────────────────────────────────
-- invitation_codes
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invitation_codes (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                 TEXT UNIQUE NOT NULL,
    status               TEXT NOT NULL DEFAULT 'unused'
                         CHECK (status IN ('unused', 'used', 'revoked')),
    starting_balance_sol NUMERIC NOT NULL DEFAULT 5,
    assigned_telegram_id BIGINT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at              TIMESTAMPTZ
);

-- ──────────────────────────────────────────────────────────────
-- users
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id                   BIGINT UNIQUE NOT NULL,
    telegram_username             TEXT NOT NULL DEFAULT '',
    wallet_address                TEXT NOT NULL,
    wallet_encrypted_seed         TEXT NOT NULL,
    sol_balance                   NUMERIC NOT NULL DEFAULT 0,
    starting_balance_sol          NUMERIC NOT NULL DEFAULT 5,
    starting_balance_usd_snapshot NUMERIC NOT NULL DEFAULT 0,
    status                        TEXT NOT NULL DEFAULT 'active'
                                  CHECK (status IN ('active', 'paused', 'restricted', 'banned')),
    quick_buy_amounts             NUMERIC[] NOT NULL DEFAULT '{0.1, 0.5, 1}',
    quick_sell_percents           NUMERIC[] NOT NULL DEFAULT '{25, 50, 100}',
    invitation_code_id            UUID REFERENCES invitation_codes(id),
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────
-- positions
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS positions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_address      TEXT NOT NULL,
    token_symbol       TEXT NOT NULL,
    token_name         TEXT NOT NULL DEFAULT '',
    amount_tokens      NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price_usd NUMERIC NOT NULL DEFAULT 0,
    total_sol_invested  NUMERIC NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'closed')),
    opened_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS positions_user_status ON positions(user_id, status);

-- ──────────────────────────────────────────────────────────────
-- transactions
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id      UUID REFERENCES positions(id),
    type             TEXT NOT NULL CHECK (type IN ('buy', 'sell')),
    token_address    TEXT NOT NULL,
    token_symbol     TEXT NOT NULL,
    sol_amount       NUMERIC NOT NULL,
    token_amount     NUMERIC NOT NULL,
    price_usd        NUMERIC NOT NULL,
    gas_fee_sol      NUMERIC NOT NULL DEFAULT 0.0001,
    mcap_at_trade    NUMERIC NOT NULL DEFAULT 0,
    price_impact_pct NUMERIC NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS transactions_user ON transactions(user_id);

-- ──────────────────────────────────────────────────────────────
-- admin_users
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────
-- admin_audit_log
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_username TEXT NOT NULL,
    action         TEXT NOT NULL,
    target_user_id UUID REFERENCES users(id),
    details        JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_log_created ON admin_audit_log(created_at DESC);
