# Pulse Trading Bot

A Solana memecoin trading Telegram bot with a Next.js admin dashboard, backed by Supabase.

## Repository structure

```
/bot        — Python Telegram bot (deploy to Render)
/admin      — Next.js admin dashboard (deploy to Vercel)
```

---

## Quick Start

### 1. Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. In the SQL editor, paste and run `bot/supabase_schema.sql` to create all tables.
3. Copy your **Project URL** and **service role key** from *Settings → API*.

### 2. Bot (Render)

```bash
cd bot
cp .env.example .env   # fill in your values
# Generate a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
pip install -r requirements.txt
python main.py
```

Deploy to Render as a **Background Worker** using `bot/render.yaml`. Set all env vars in the Render dashboard.

### 3. Admin Dashboard (Vercel)

```bash
cd admin
cp .env.example .env   # fill in your values
pnpm install
pnpm dev
```

Deploy to Vercel: import the `/admin` subdirectory, set env vars in the Vercel dashboard.

---

## Environment Variables

### Bot (`/bot`)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role secret |
| `HELIUS_API_KEY` | [helius.dev](https://helius.dev) API key |
| `FERNET_SECRET` | Symmetric encryption key for wallet seeds |
| `DEXSCREENER_BASE_URL` | `https://api.dexscreener.com` (default) |
| `PUMPFUN_FRONTEND_API` | `https://frontend-api.pump.fun` (default) |
| `DEV_DONATION_WALLET` | Solana address for the dev tip button |
| `DEFAULT_STARTING_BALANCE_SOL` | Starting SOL for new users (default `5`) |
| `FIXED_GAS_FEE_SOL` | Flat fee per trade (default `0.0001`) |
| `MAX_OPEN_POSITIONS` | Max concurrent positions per user (default `4`) |

### Admin (`/admin`)

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Same as bot |
| `SUPABASE_SERVICE_ROLE_KEY` | Same as bot |
| `NEXTAUTH_SECRET` | Random secret (`openssl rand -base64 32`) |
| `NEXTAUTH_URL` | Full URL of the deployed admin app |
| `ADMIN_USERNAME` | First admin account username |
| `ADMIN_PASSWORD` | First admin account password (bcrypt-hashed on first boot) |

---

## PnL Card Template

Put your template image at `bot/assets/pnl_template.png`.

All text field positions are configurable constants at the top of `bot/services/pnl_generator.py` — no logic changes needed when you adjust the layout.

---

## Features

### Bot
- Invite-code gated onboarding
- Real Solana wallet generation (valid keypairs, never used on-chain)
- Live token data: DexScreener, Helius, pump.fun bonding curve
- Buy / sell with live prices
- Up to 4 concurrent open positions
- Custom quick-buy SOL amounts and quick-sell percentages
- PnL card image generation (Pillow overlay on your template)
- User status enforcement (active / paused / restricted / banned)

### Admin Dashboard
- Overview stats (users, open positions, SOL in play)
- User management: search, view, pause, restrict, ban, set balance, force-close positions
- Invitation code generation with custom starting balances
- Full audit log for every admin action
