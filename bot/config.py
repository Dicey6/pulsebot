import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HELIUS_API_KEY = os.environ["HELIUS_API_KEY"]
FERNET_SECRET = os.environ["FERNET_SECRET"]  # base64-encoded 32-byte key

DEXSCREENER_BASE_URL = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
PUMPFUN_FRONTEND_API = os.getenv("PUMPFUN_FRONTEND_API", "https://frontend-api.pump.fun")
DEV_DONATION_WALLET = os.getenv(
    "DEV_DONATION_WALLET", "6uz2L1XGVArpADTdC3P1DX7S9BrxfPtKYgHkcBJQs23v"
)

DEFAULT_STARTING_BALANCE_SOL = float(os.getenv("DEFAULT_STARTING_BALANCE_SOL", "5"))
FIXED_GAS_FEE_SOL = float(os.getenv("FIXED_GAS_FEE_SOL", "0.0001"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "4"))

# PnL card template path
PNL_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "assets", "pnl_template.png")
