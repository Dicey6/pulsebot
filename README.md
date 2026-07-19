# ⚡ Pulse Bot

A **paper trading simulator** for Solana tokens on Telegram (**@pulsesolanabot**),
styled after premium trading bots like Trojan, BullX, Maestro, Nova, Photon
and Banana Gun.

> ⚠️ **This bot never touches real funds.** No wallets are connected, no
> transactions are signed, no real SOL is ever spent. Every "trade" is a
> simulation against a local demo wallet, priced using **live** market data
> pulled from [DexScreener](https://docs.dexscreener.com/).

## Features

- Paste any Solana contract address to instantly pull live price, market
  cap, liquidity, FDV, volume, and multi-timeframe price change.
- Simulated Buy / Sell (25% / 50% / 100%) against a demo SOL balance.
- Positions terminal, full portfolio analytics (win rate, best/worst token,
  daily/weekly/monthly PnL, average hold time, etc.), and paginated trade history.
- Editable settings: demo balance, default buy size, reset portfolio/balance.
- **Premium shareable PNL cards** (1920×1080, dark background, purple neon
  glassmorphism), auto-generated after every closed position and available
  on demand via "📤 Share PNL Card" — sized and styled for posting on X.
- Entirely inline-keyboard driven; every action edits the existing message.
- JSON file storage — no database required.

## The PNL Card

Generated with Pillow at **1920×1080**, dark background with purple neon
accents, a glassmorphism panel (soft drop shadow, top sheen, neon glow
border), and a green/red trend triangle next to the headline percentage.

Shows only:
- Token name & symbol
- Contract address (shortened)
- Buy market cap / Sell market cap (mcap, not raw token price)
- Hold time
- Amount invested (SOL)
- Amount returned (SOL)
- PnL % and PnL (SOL)

🟩 green styling for profitable trades, 🟥 red for losing trades.

Fonts (DejaVu Sans/Mono, bundled in `fonts/`) and the brand mark
(`assets/pulse_logo.png`) ship with the project so the card renders
identically on Render regardless of what's installed on the host.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and set BOT_TOKEN if you don't want to rely on the hardcoded fallback
python bot.py
```

### ⚠️ About the bot token

`bot.py` hardcodes a fallback token for **@pulsesolanabot** so it runs even
without a `.env` file. The `BOT_TOKEN` environment variable, when set,
always takes priority over that fallback.

**Before pushing this to a public GitHub repository, remove or rotate the
hardcoded token.** Anyone who can read the source can control the bot.
Recommended: keep the repo private, or delete the hardcoded fallback in
`bot.py` and set `BOT_TOKEN` only via Render's Environment tab. If the
token is ever exposed, revoke and reissue it via @BotFather (`/revoke`).

## Deploying to Render

This repo includes a `render.yaml` for one-click deployment:

1. Push this project to a GitHub repo (private recommended — see above).
2. In Render, choose **New → Blueprint** and point it at the repo (or
   manually create a **Background Worker** — not a Web Service, since this
   bot uses long-polling, not webhooks).
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Set `BOT_TOKEN` in the service's Environment tab.
6. (Optional) Attach a persistent disk if you want `db.json` (demo wallets,
   positions, trade history) to survive redeploys — see the commented-out
   `disk:` block in `render.yaml`.

## Notes on the simulation math

- Quantity received on buy is estimated using a cached SOL/USD rate
  (refreshed every 60s from DexScreener) so demo balances stay in SOL while
  token prices are read in USD.
- PnL % and PnL (SOL) are calculated purely from the token's price ratio
  between entry and exit, applied to the SOL amount invested — this keeps
  results consistent and avoids compounding errors from SOL/USD drift.
- Market cap is tracked separately (weighted-averaged across multiple buys
  into the same position) purely for display on the PNL card, matching how
  most Solana traders actually think about a position's size.
- Price impact on the token screen is a rough estimate
  (`buy size in USD ÷ pool liquidity`), not a real AMM curve calculation.

## Project structure

```
bot.py              — the entire bot (single file)
requirements.txt     — dependencies
render.yaml           — Render Blueprint (background worker)
.env.example          — copy to .env and fill in BOT_TOKEN
fonts/                 — bundled DejaVu fonts used by the PNL card generator
assets/                — bundled brand logo used on the PNL card
db.json                — created automatically on first run
```
