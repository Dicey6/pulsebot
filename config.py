import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8638344989:AAH3bfBni5GN3oWUBoVerKIMzND0-8goi3I")
BOT_USERNAME: str = "@pulsesolanabot"

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# ── APIs ──────────────────────────────────────────────────────────────────────
HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "d5381285-5b00-4ad2-9255-581b5e55e2cc")
HELIUS_RPC_URL: str = "https://mainnet.helius-rpc.com/"
JUPITER_PRICE_URL: str = "https://api.jup.ag/price/v2"
DEXSCREENER_URL: str = "https://api.dexscreener.com/latest/dex/tokens/{}"
SOL_MINT: str = "So11111111111111111111111111111111111111112"

# ── Trading ───────────────────────────────────────────────────────────────────
STARTING_BALANCE_SOL: float = 5.0
TRADE_FEE_SOL: float = 0.0001
BUY_PRESETS: list[float] = [0.1, 0.5, 1.0]
SELL_FRACTIONS: list[float] = [0.25, 0.50, 0.75, 1.00]

# ── Cache ─────────────────────────────────────────────────────────────────────
TOKEN_CACHE_TTL: int = 30   # seconds
SOL_PRICE_CACHE_TTL: int = 60

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent
ASSETS_DIR: Path = BASE_DIR / "assets"
FONTS_DIR: Path = BASE_DIR / "fonts"
