#!/usr/bin/env python3
"""
=============================================================================
 PULSE BOT — Solana Paper Trading Simulator for Telegram
=============================================================================

Pulse Bot mimics the look, feel and UX of premium Solana trading bots
(Trojan, BullX, Maestro, Nova, Photon, Banana Gun) — but it is 100% a paper
trading simulator.

⚠️  IMPORTANT: This bot NEVER touches real funds.
    - No wallets are ever connected.
    - No transactions are ever signed.
    - No real SOL is ever spent.
    Every "trade" is a simulation that uses LIVE market data from
    Helius API (primary) and DexScreener (fallback) to calculate realistic
    hypothetical outcomes, tracked in a local JSON "demo wallet" per user.

Tech stack: python-telegram-bot (v21+), httpx, python-dotenv, Pillow, JSON
storage. Single file, designed to run as a Render background worker via
long-polling.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # add your BOT_TOKEN
    python bot.py
=============================================================================
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =============================================================================
# CONFIG
# =============================================================================

load_dotenv()

# -----------------------------------------------------------------------
# ⚠️ SECURITY NOTE ON THE BOT TOKEN
# -----------------------------------------------------------------------
# Per project instructions the token is hardcoded below as a fallback so
# the bot runs even without a .env file configured. HOWEVER: if this repo
# is ever pushed to a public GitHub repository (including for Render's
# git-based deploys), anyone can read this token and take control of
# @pulsesolanabot. The BOT_TOKEN environment variable always takes
# priority when set — on Render, set it in the service's Environment tab
# instead of relying on the hardcoded fallback, and keep the repo private.
# If this token is ever exposed, rotate it immediately via @BotFather
# (/revoke) and update it here or in your environment variables.
# -----------------------------------------------------------------------
_HARDCODED_FALLBACK_TOKEN = "8638344989:AAH3bfBni5GN3oWUBoVerKIMzND0-8goi3I"
BOT_TOKEN = os.getenv("BOT_TOKEN", "") or _HARDCODED_FALLBACK_TOKEN
BOT_USERNAME = "@pulsesolanabot"

# Helius API Key (hardcoded as requested)
_HELIUS_API_KEY = "d5381285-5b00-4ad2-9255-581b5e55e2cc"
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "") or _HELIUS_API_KEY

DB_PATH = Path(os.getenv("DB_PATH", "db.json"))

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "fonts"
ASSETS_DIR = BASE_DIR / "assets"

DEFAULT_BALANCE = 100.0
DEFAULT_BUY_AMOUNT = 0.25
POSITIONS_PER_PAGE = 3
HISTORY_PER_PAGE = 6

SOL_MINT = "So11111111111111111111111111111111111111112"
HELIUS_PRICE_URL = "https://api.helius.xyz/v0/token-price"
HELIUS_DAS_URL = "https://api.helius.xyz/v0/assets"
DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"

SOL_ADDRESS_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("pulsebot")
logging.getLogger("httpx").setLevel(logging.WARNING)

BRAND = "⚡ PULSE BOT"

# Neon purple palette (matches the PNL card branding)
NEON_PURPLE = (168, 85, 247)
NEON_PURPLE_DIM = (109, 40, 217)
PROFIT_GREEN = (34, 197, 94)
LOSS_RED = (239, 68, 68)

# =============================================================================
# STORAGE (JSON, no database)
# =============================================================================

_db_cache: dict[str, Any] | None = None


def load_db() -> dict[str, Any]:
    global _db_cache
    if _db_cache is not None:
        return _db_cache
    if DB_PATH.exists():
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                _db_cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("db.json corrupt or unreadable, starting fresh")
            _db_cache = {"users": {}}
    else:
        _db_cache = {"users": {}}
    _db_cache.setdefault("users", {})
    return _db_cache


def save_db(db: dict[str, Any]) -> None:
    global _db_cache
    _db_cache = db
    tmp = DB_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
        tmp.replace(DB_PATH)
    except OSError as e:
        logger.error("Failed to save db: %s", e)


def new_user() -> dict[str, Any]:
    return {
        "balance": DEFAULT_BALANCE,
        "default_buy": DEFAULT_BUY_AMOUNT,
        "positions": {},       # contract_address -> position dict
        "history": [],         # list of trade dicts, newest first
        "realized_pnl": 0.0,
        "created_at": now_ts(),
    }


def get_user(db: dict[str, Any], uid: str) -> dict[str, Any]:
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = new_user()
    user = db["users"][uid]
    user.setdefault("balance", DEFAULT_BALANCE)
    user.setdefault("default_buy", DEFAULT_BUY_AMOUNT)
    user.setdefault("positions", {})
    user.setdefault("history", [])
    user.setdefault("realized_pnl", 0.0)
    return user


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def now_ts() -> float:
    return time.time()


def fmt_num(n: float) -> str:
    """Compact number format: 1234 -> 1.23K, 1_500_000 -> 1.5M"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000_000:
        return f"{sign}${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{sign}${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{sign}${n / 1_000:.2f}K"
    return f"{sign}${n:,.2f}"


def fmt_num_plain(n: float) -> str:
    """Compact number without $ sign: 1234 -> 1.23K, 1_500_000 -> 1.5M"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000_000:
        return f"{sign}{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{sign}{n / 1_000:.2f}K"
    return f"{sign}{n:,.2f}"


def fmt_price(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    if n == 0:
        return "$0.00"
    if n >= 1:
        return f"${n:,.4f}"
    # Show more precision for very small caps, with leading-zero compression
    s = f"{n:.10f}".rstrip("0")
    decimal_part = s.split(".")[1] if "." in s else ""
    leading_zeros = len(decimal_part) - len(decimal_part.lstrip("0"))
    if leading_zeros >= 4:
        sig = decimal_part.lstrip("0")[:4]
        return f"$0.0{{{leading_zeros}}}{sig}"
    return f"${n:.8f}".rstrip("0").rstrip(".")


def fmt_sol(n: float, decimals: int = 4) -> str:
    try:
        return f"{float(n):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0.0000"


def fmt_pct(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"
    arrow = "🟢▲" if n > 0 else ("🔴▼" if n < 0 else "⚪")
    return f"{arrow} {n:+.2f}%"


def fmt_pct_plain(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    try:
        return f"{float(n):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def fmt_time_ago(ts: float) -> str:
    delta = now_ts() - ts
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def short_addr(addr: str) -> str:
    if not addr or len(addr) < 10:
        return addr or "N/A"
    return f"{addr[:4]}...{addr[-4:]}"


def md_escape(text: str) -> str:
    """Escape text for legacy Markdown (parse_mode=MARKDOWN)."""
    if text is None:
        return ""
    text = str(text)
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


# =============================================================================
# HELIUS API INTEGRATION
# =============================================================================

_sol_price_cache: dict[str, Any] = {"price": 150.0, "ts": 0.0}
_token_cache: dict[str, dict[str, Any]] = {}
_cache_ttl = 30  # seconds


async def fetch_token_helius(contract_address: str) -> dict[str, Any] | None:
    """Fetch token data from Helius API (price + metadata)."""
    try:
        # Get price data
        async with httpx.AsyncClient(timeout=10.0) as client:
            price_url = f"{HELIUS_PRICE_URL}?api-key={HELIUS_API_KEY}&mint={contract_address}"
            resp = await client.get(price_url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            price_data = resp.json()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning("Helius price fetch failed for %s: %s", contract_address, e)
        return None

    # Parse price response
    price_info = None
    if price_data.get("data") and len(price_data["data"]) > 0:
        price_info = price_data["data"][0]

    if not price_info:
        return None

    try:
        price_usd = float(price_info.get("price", 0))
        mc = float(price_info.get("marketCap", 0))
        volume_24h = float(price_info.get("volume24h", 0))
        change_24h = float(price_info.get("priceChange24h", 0))
    except (TypeError, ValueError):
        return None

    # Get metadata from DAS
    name, symbol, decimals, supply, created_at, logo_url = await fetch_token_metadata_helius(contract_address)

    return {
        "address": contract_address,
        "name": name or "Unknown",
        "symbol": symbol or "???",
        "price_usd": price_usd,
        "mc": mc,
        "volume_24h": volume_24h,
        "change_h24": change_24h,
        "liquidity_usd": None,  # Helius doesn't provide this
        "decimals": decimals,
        "total_supply": supply,
        "created_at": created_at,
        "logo_url": logo_url,
        "source": "helius",
        "fetched_at": now_ts(),
    }


async def fetch_token_metadata_helius(contract_address: str) -> tuple[Optional[str], Optional[str], Optional[int], Optional[float], Optional[float], Optional[str]]:
    """Fetch token metadata from Helius DAS API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{HELIUS_DAS_URL}?api-key={HELIUS_API_KEY}&ids={contract_address}"
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Helius DAS fetch failed for %s: %s", contract_address, e)
        return None, None, None, None, None, None

    if not data.get("data") or len(data["data"]) == 0:
        return None, None, None, None, None, None

    asset = data["data"][0]
    content = asset.get("content", {})
    metadata = content.get("metadata", {})
    
    name = metadata.get("name")
    symbol = metadata.get("symbol")
    
    # Get decimals from token_info
    token_info = asset.get("token_info", {})
    decimals = token_info.get("decimals")
    supply = token_info.get("supply")
    
    # Created at - try to parse from mint extensions or use current time
    created_at = None
    # Try to get from various possible fields
    if asset.get("created_at"):
        try:
            created_at = float(asset["created_at"])
        except (TypeError, ValueError):
            pass
    
    # Logo URL
    logo_url = None
    if content.get("links", {}).get("image"):
        logo_url = content["links"]["image"]
    elif metadata.get("image"):
        logo_url = metadata["image"]
    
    return name, symbol, decimals, supply, created_at, logo_url


async def fetch_token_dexscreener(contract_address: str) -> dict[str, Any] | None:
    """Fetch token data from DexScreener (fallback)."""
    url = DEXSCREENER_TOKENS_URL.format(contract_address)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("DexScreener fetch failed for %s: %s", contract_address, e)
        return None
    
    pairs = data.get("pairs") or []
    sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
    pairs = sol_pairs or pairs
    if not pairs:
        return None
    
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    
    price_change = best.get("priceChange") or {}
    volume = best.get("volume") or {}
    liquidity = best.get("liquidity") or {}
    base = best.get("baseToken") or {}
    
    try:
        price_usd = float(best.get("priceUsd") or 0)
    except (TypeError, ValueError):
        price_usd = 0.0
    
    return {
        "address": base.get("address", contract_address),
        "name": base.get("name", "Unknown"),
        "symbol": base.get("symbol", "???"),
        "price_usd": price_usd,
        "mc": best.get("marketCap") or best.get("fdv"),
        "volume_24h": volume.get("h24", 0) or 0,
        "change_h24": price_change.get("h24"),
        "liquidity_usd": liquidity.get("usd", 0) or 0,
        "decimals": None,
        "total_supply": None,
        "created_at": None,
        "logo_url": None,
        "source": "dexscreener",
        "fetched_at": now_ts(),
    }


async def fetch_token(contract_address: str, force_refresh: bool = False) -> dict[str, Any] | None:
    """Fetch token data: try Helius first, fallback to DexScreener."""
    # Check cache
    cache_key = contract_address
    if not force_refresh and cache_key in _token_cache:
        cached = _token_cache[cache_key]
        if now_ts() - cached.get("fetched_at", 0) < _cache_ttl:
            return cached
    
    # Try Helius
    token = await fetch_token_helius(contract_address)
    if token:
        _token_cache[cache_key] = token
        return token
    
    # Fallback to DexScreener
    logger.info("Helius failed for %s, falling back to DexScreener", contract_address)
    token = await fetch_token_dexscreener(contract_address)
    if token:
        _token_cache[cache_key] = token
        return token
    
    return None


async def get_sol_price_usd() -> float:
    """Cached SOL/USD price, refreshed every 60s."""
    if now_ts() - _sol_price_cache["ts"] < 60:
        return _sol_price_cache["price"]
    
    # Try Helius first
    token = await fetch_token_helius(SOL_MINT)
    if token and token["price_usd"]:
        _sol_price_cache["price"] = token["price_usd"]
        _sol_price_cache["ts"] = now_ts()
        return _sol_price_cache["price"]
    
    # Fallback to DexScreener
    token = await fetch_token_dexscreener(SOL_MINT)
    if token and token["price_usd"]:
        _sol_price_cache["price"] = token["price_usd"]
        _sol_price_cache["ts"] = now_ts()
    
    return _sol_price_cache["price"]


# =============================================================================
# PNL CARD IMAGE GENERATION (Pillow)
# =============================================================================

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_LOGO_CACHE: dict[int, Optional[Image.Image]] = {}


def _load_logo(target_size: int) -> Optional[Image.Image]:
    """Loads assets/pulse_logo.png resized to a square of target_size px."""
    if target_size in _LOGO_CACHE:
        return _LOGO_CACHE[target_size]
    path = ASSETS_DIR / "pulse_logo.png"
    logo = None
    try:
        if path.exists():
            logo = Image.open(path).convert("RGBA")
            logo = logo.resize((target_size, target_size), Image.LANCZOS)
    except (OSError, IOError) as e:
        logger.warning("Could not load logo asset: %s", e)
        logo = None
    _LOGO_CACHE[target_size] = logo
    return logo


def _load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    key = (f"{'mono' if mono else 'sans'}-{'bold' if bold else 'reg'}", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    filename = (
        "DejaVuSansMono-Bold.ttf" if (mono and bold) else
        "DejaVuSansMono.ttf" if mono else
        "DejaVuSans-Bold.ttf" if bold else
        "DejaVuSans.ttf"
    )
    candidates = [
        FONTS_DIR / filename,
        Path("/usr/share/fonts/truetype/dejavu") / filename,
    ]
    font = None
    for path in candidates:
        try:
            font = ImageFont.truetype(str(path), size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_centered(draw: ImageDraw.ImageDraw, cx: float, y: float, text: str, font, fill) -> int:
    w = _text_w(draw, text, font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)
    return w


def generate_pnl_card(
    symbol: str,
    name: str,
    contract_address: str,
    buy_mcap: Optional[float],
    sell_mcap: Optional[float],
    invested_sol: float,
    returned_sol: float,
    pnl_pct: float,
    pnl_sol: float,
    hold_seconds: float,
    is_unrealized: bool = False,
) -> io.BytesIO:
    """
    Renders a premium, shareable PNL card (1920x1080) — dark background,
    purple neon accents, glassmorphism panel — for a closed position
    (or an open one, if is_unrealized=True, used by the Share button).
    """
    W, H = 1920, 1080
    win = pnl_pct >= 0
    accent = PROFIT_GREEN if win else LOSS_RED
    accent_soft = tuple(min(255, c + 40) for c in accent)

    # ---- Base: dark vertical gradient ----
    base = Image.new("RGBA", (W, H), (10, 8, 18, 255))
    draw = ImageDraw.Draw(base)
    top_color, bottom_color = (9, 7, 16), (17, 9, 24)
    for y in range(H):
        t = y / H
        draw.line(
            [(0, y), (W, y)],
            fill=(_lerp(top_color[0], bottom_color[0], t),
                  _lerp(top_color[1], bottom_color[1], t),
                  _lerp(top_color[2], bottom_color[2], t), 255),
        )

    # ---- Ambient neon glow blobs ----
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.ellipse([-260, -340, 780, 480], fill=NEON_PURPLE + (70,))
    gd.ellipse([W - 740, H - 640, W + 300, H + 300], fill=accent + (55,))
    gd.ellipse([W // 2 - 500, H // 2 - 250, W // 2 + 500, H // 2 + 250], fill=NEON_PURPLE_DIM + (25,))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(180))
    base.alpha_composite(glow_layer)

    # ---- Soft vignette ----
    vignette = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(220))
    vignette_layer = Image.new("RGBA", (W, H), (0, 0, 0, 130))
    vignette_layer.putalpha(Image.eval(vignette, lambda p: 130 - int(p / 255 * 130)))
    base.alpha_composite(vignette_layer)

    # ---- Faint grid texture ----
    grid_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(grid_layer)
    for gx in range(0, W, 64):
        gd2.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 4))
    for gy in range(0, H, 64):
        gd2.line([(0, gy), (W, gy)], fill=(255, 255, 255, 4))
    base.alpha_composite(grid_layer)

    draw = ImageDraw.Draw(base)
    pad = 90

    # ---- Fonts ----
    f_brand = _load_font(30, bold=True)
    f_handle = _load_font(24)
    f_badge = _load_font(26, bold=True)
    f_symbol = _load_font(96, bold=True)
    f_name = _load_font(30)
    f_ca = _load_font(26, mono=True)
    f_pnl_pct = _load_font(190, bold=True)
    f_pnl_sol = _load_font(52, bold=True)
    f_label = _load_font(21, bold=True)
    f_value = _load_font(32, bold=True)
    f_footer = _load_font(22)

    # ---- Header: logo + brand ----
    logo = _load_logo(46)
    brand_x = pad
    if logo is not None:
        base.alpha_composite(logo, (pad, 52))
        brand_x = pad + 46 + 16
    draw.text((brand_x, 56), BRAND.replace("⚡ ", ""), font=f_brand, fill=(235, 230, 245))
    handle_w = _text_w(draw, BOT_USERNAME, f_handle)
    draw.text((W - pad - handle_w, 62), BOT_USERNAME, font=f_handle, fill=(150, 145, 165))

    # ---- Status badge ----
    if is_unrealized:
        badge_text = "🟩 UNREALIZED PROFIT" if win else "🟥 UNREALIZED LOSS"
    else:
        badge_text = "🟩 PROFIT" if win else "🟥 LOSS"
    bw = _text_w(draw, badge_text, f_badge) + 64
    bx1, by0, by1 = W - pad, 108, 160
    bx0 = bx1 - bw
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge_layer)
    bd.rounded_rectangle([bx0, by0, bx1, by1], radius=26, fill=accent + (40,), outline=accent + (255,), width=2)
    base.alpha_composite(badge_layer)
    draw = ImageDraw.Draw(base)
    draw.text(((bx0 + bx1) / 2, (by0 + by1) / 2), badge_text, font=f_badge, fill=accent, anchor="mm")

    # ---- Main glassmorphism panel ----
    panel_box = [pad, 190, W - pad, H - 90]
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.rounded_rectangle(
        [panel_box[0] + 10, panel_box[1] + 22, panel_box[2] - 10, panel_box[3] + 22],
        radius=40, fill=(0, 0, 0, 160),
    )
    base.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(28)))

    panel_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel_layer)
    pd.rounded_rectangle(panel_box, radius=40, fill=(255, 255, 255, 14))
    base.alpha_composite(panel_layer)

    # Subtle top-lit sheen
    sheen_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shd = ImageDraw.Draw(sheen_layer)
    shd.rounded_rectangle(panel_box, radius=40, fill=(255, 255, 255, 0))
    shd.rectangle([panel_box[0], panel_box[1], panel_box[2], panel_box[1] + 220], fill=(255, 255, 255, 10))
    sheen_mask = Image.new("L", (W, H), 0)
    smd = ImageDraw.Draw(sheen_mask)
    smd.rounded_rectangle(panel_box, radius=40, fill=255)
    sheen_layer.putalpha(Image.composite(sheen_layer.split()[3], Image.new("L", (W, H), 0), sheen_mask))
    base.alpha_composite(sheen_layer)

    # Glowing neon border
    border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bgd = ImageDraw.Draw(border_layer)
    bgd.rounded_rectangle(panel_box, radius=40, outline=accent + (220,), width=3)
    base.alpha_composite(border_layer.filter(ImageFilter.GaussianBlur(10)))
    base.alpha_composite(border_layer)

    draw = ImageDraw.Draw(base)

    # ---- Token identity ----
    ix, iy = pad + 60, 240
    draw.text((ix, iy), f"${symbol.upper()}", font=f_symbol, fill=(255, 255, 255))
    iy += 110
    draw.text((ix, iy), (name or "Unknown Token")[:44], font=f_name, fill=(170, 165, 185))
    iy += 44
    draw.text((ix, iy), f"CA: {short_addr(contract_address)}", font=f_ca, fill=NEON_PURPLE)

    # ---- Big centered PnL % ----
    pct_text = f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%"
    cy = 470
    glow_text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gtd = ImageDraw.Draw(glow_text)
    w_pct = _text_w(gtd, pct_text, f_pnl_pct)
    px0 = W / 2 - w_pct / 2
    gtd.text((px0, cy), pct_text, font=f_pnl_pct, fill=accent + (255,))
    base.alpha_composite(glow_text.filter(ImageFilter.GaussianBlur(26)))
    draw = ImageDraw.Draw(base)
    draw.text((px0, cy), pct_text, font=f_pnl_pct, fill=accent_soft)

    # Small trend triangle
    tri_cx, tri_cy = px0 - 55, cy + 95
    tri_size = 34
    if win:
        triangle = [(tri_cx, tri_cy + tri_size / 2), (tri_cx - tri_size / 2, tri_cy - tri_size / 2),
                    (tri_cx + tri_size / 2, tri_cy - tri_size / 2)]
    else:
        triangle = [(tri_cx, tri_cy - tri_size / 2), (tri_cx - tri_size / 2, tri_cy + tri_size / 2),
                    (tri_cx + tri_size / 2, tri_cy + tri_size / 2)]
    draw.polygon(triangle, fill=accent)

    # ---- PnL in SOL ----
    sol_text = f"{'+' if pnl_sol >= 0 else ''}{pnl_sol:.4f} SOL"
    _draw_centered(draw, W / 2, 700, sol_text, f_pnl_sol, (232, 230, 240))

    # ---- Divider ----
    div_y = 800
    draw.line([(pad + 60, div_y), (W - pad - 60, div_y)], fill=(255, 255, 255, 35), width=2)

    # ---- Stat chips ----
    stats = [
        ("BUY MCAP", fmt_num(buy_mcap) if buy_mcap else "N/A"),
        ("CURRENT MCAP" if is_unrealized else "SELL MCAP", fmt_num(sell_mcap) if sell_mcap else "N/A"),
        ("HOLD TIME", fmt_duration(hold_seconds)),
        ("INVESTED (SOL)", f"{invested_sol:.4f}"),
        ("CURRENT VALUE (SOL)" if is_unrealized else "RETURNED (SOL)", f"{returned_sol:.4f}"),
    ]
    grid_top, grid_bottom = 836, 950
    inner_left, inner_right = pad + 50, W - pad - 50
    gap = 20
    n = len(stats)
    chip_w = (inner_right - inner_left - gap * (n - 1)) / n

    chips_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cld = ImageDraw.Draw(chips_layer)
    for i in range(n):
        cx0 = inner_left + i * (chip_w + gap)
        cld.rounded_rectangle([cx0, grid_top, cx0 + chip_w, grid_bottom], radius=20,
                               fill=(255, 255, 255, 10), outline=(255, 255, 255, 28), width=1)
    base.alpha_composite(chips_layer)
    draw = ImageDraw.Draw(base)

    for i, (label, value) in enumerate(stats):
        cx0 = inner_left + i * (chip_w + gap)
        ccx = cx0 + chip_w / 2
        _draw_centered(draw, ccx, grid_top + 26, label, f_label, (155, 150, 172))
        _draw_centered(draw, ccx, grid_top + 60, value, f_value, (247, 246, 251))

    # ---- Footer ----
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    draw.text((pad, H - 55), f"{ts}  •  Paper Trading Simulation — No Real Funds",
              font=f_footer, fill=(140, 135, 155))
    footer_brand = f"Generated by {BRAND}"
    fw = _text_w(draw, footer_brand, f_footer)
    draw.text((W - pad - fw, H - 55), footer_brand, font=f_footer, fill=(140, 135, 155))

    final = base.convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    buf.name = "pulse_pnl_card.png"
    return buf


# =============================================================================
# KEYBOARDS
# =============================================================================

def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
         InlineKeyboardButton("💼 Portfolio", callback_data="portfolio")],
        [InlineKeyboardButton("📜 Trade History", callback_data="history:0"),
         InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("🔍 Track Token", callback_data="track")],
    ])


def kb_token(ca: str, has_position: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🟢 Buy", callback_data=f"buy:{ca}"),
         InlineKeyboardButton("💰 Custom Buy", callback_data=f"cbuy:{ca}")],
    ]
    if has_position:
        rows.append([
            InlineKeyboardButton("🟥 Sell 25%", callback_data=f"s25:{ca}"),
            InlineKeyboardButton("🟥 Sell 50%", callback_data=f"s50:{ca}"),
            InlineKeyboardButton("🟥 Sell All", callback_data=f"s100:{ca}"),
        ])
        rows.append([InlineKeyboardButton("📤 Share PNL Card", callback_data=f"shr:{ca}")])
    rows.append([
        InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
        InlineKeyboardButton("💼 Portfolio", callback_data="portfolio"),
    ])
    rows.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=f"tok:{ca}"),
        InlineKeyboardButton("📊 DexScreener", url=f"https://dexscreener.com/solana/{ca}"),
        InlineKeyboardButton("📋 Copy CA", callback_data=f"copy:{ca}"),
    ])
    rows.append([
        InlineKeyboardButton("🌐 Solscan", url=f"https://solscan.io/token/{ca}"),
        InlineKeyboardButton("🔎 Rugcheck", url=f"https://rugcheck.xyz/tokens/{ca}"),
        InlineKeyboardButton("🦅 Birdeye", url=f"https://birdeye.so/token/{ca}?chain=solana"),
    ])
    rows.append([
        InlineKeyboardButton("📡 Photon", url=f"https://photon-sol.trade/token/{ca}"),
        InlineKeyboardButton("📈 GMGN", url=f"https://gmgn.ai/sol/token/{ca}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def kb_positions(page: int, total_pages: int, cas_on_page: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for ca in cas_on_page:
        rows.append([
            InlineKeyboardButton(f"📂 {short_addr(ca)}", callback_data=f"tok:{ca}"),
            InlineKeyboardButton("🔄", callback_data=f"refpos:{ca}"),
            InlineKeyboardButton("📤", callback_data=f"shr:{ca}"),
        ])
        rows.append([
            InlineKeyboardButton("25%", callback_data=f"s25:{ca}"),
            InlineKeyboardButton("50%", callback_data=f"s50:{ca}"),
            InlineKeyboardButton("All", callback_data=f"s100:{ca}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"positions:{page - 1}"))
    nav.append(InlineKeyboardButton("🔄 Refresh All", callback_data=f"positions:{page}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"positions:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def kb_portfolio() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
         InlineKeyboardButton("📜 History", callback_data="history:0")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="portfolio")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])


def kb_history(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"history:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"history:{page + 1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Set Demo Balance", callback_data="set_balance")],
        [InlineKeyboardButton("🎯 Set Default Buy", callback_data="set_buy")],
        [InlineKeyboardButton("♻️ Reset Portfolio", callback_data="reset_portfolio")],
        [InlineKeyboardButton("🔁 Reset Balance", callback_data="reset_balance")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])


def kb_confirm(yes_cb: str, no_cb: str = "settings") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=yes_cb),
         InlineKeyboardButton("❌ Cancel", callback_data=no_cb)],
    ])


def kb_back(target: str = "home", label: str = "⬅️ Back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])


# =============================================================================
# TRADING LOGIC
# =============================================================================

class TradeError(Exception):
    pass


async def execute_buy(user: dict, ca: str, token: dict, sol_amount: float) -> dict:
    if sol_amount <= 0:
        raise TradeError("Buy amount must be greater than 0.")
    if sol_amount > user["balance"]:
        raise TradeError(f"Insufficient balance. You have {fmt_sol(user['balance'])} SOL.")
    if not token or not token.get("price_usd"):
        raise TradeError("Could not fetch a valid price for this token.")

    entry_price = token["price_usd"]
    entry_mcap = token.get("mc")
    sol_usd = await get_sol_price_usd()
    usd_amount = sol_amount * sol_usd
    qty = usd_amount / entry_price if entry_price > 0 else 0

    pos = user["positions"].get(ca)
    if pos:
        total_qty = pos["quantity"] + qty
        total_invested = pos["invested_sol"] + sol_amount
        pos["entry_price"] = (
            (pos["entry_price"] * pos["quantity"] + entry_price * qty) / total_qty
            if total_qty > 0 else entry_price
        )
        if entry_mcap and pos.get("entry_mcap"):
            pos["entry_mcap"] = (
                (pos["entry_mcap"] * pos["quantity"] + entry_mcap * qty) / total_qty
                if total_qty > 0 else entry_mcap
            )
        elif entry_mcap:
            pos["entry_mcap"] = entry_mcap
        pos["quantity"] = total_qty
        pos["invested_sol"] = total_invested
    else:
        pos = {
            "contract_address": ca,
            "name": token["name"],
            "symbol": token["symbol"],
            "quantity": qty,
            "entry_price": entry_price,
            "entry_mcap": entry_mcap,
            "invested_sol": sol_amount,
            "entry_time": now_ts(),
        }
        user["positions"][ca] = pos

    user["balance"] -= sol_amount

    trade = {
        "id": uuid.uuid4().hex[:10],
        "type": "BUY",
        "contract_address": ca,
        "symbol": token["symbol"],
        "name": token["name"],
        "quantity": qty,
        "price": entry_price,
        "mcap": entry_mcap,
        "sol_amount": sol_amount,
        "pnl_pct": None,
        "pnl_sol": None,
        "timestamp": now_ts(),
    }
    user["history"].insert(0, trade)
    return trade


async def execute_sell(user: dict, ca: str, token: dict, fraction: float) -> dict:
    pos = user["positions"].get(ca)
    if not pos:
        raise TradeError("You don't own a position in this token.")
    if not token or not token.get("price_usd"):
        raise TradeError("Could not fetch a valid price for this token.")

    fraction = max(0.0, min(1.0, fraction))
    exit_price = token["price_usd"]
    exit_mcap = token.get("mc")
    entry_price = pos["entry_price"]
    entry_mcap = pos.get("entry_mcap")

    qty_sold = pos["quantity"] * fraction
    invested_portion = pos["invested_sol"] * fraction
    pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0.0
    pnl_sol = invested_portion * (pnl_pct / 100)
    returned_sol = invested_portion + pnl_sol

    user["balance"] += returned_sol
    user["realized_pnl"] = user.get("realized_pnl", 0.0) + pnl_sol

    pos["quantity"] -= qty_sold
    pos["invested_sol"] -= invested_portion

    fully_closed = fraction >= 0.999 or pos["quantity"] <= 1e-12
    if fully_closed:
        del user["positions"][ca]

    sell_ts = now_ts()
    trade = {
        "id": uuid.uuid4().hex[:10],
        "type": "SELL",
        "contract_address": ca,
        "symbol": pos["symbol"],
        "name": pos["name"],
        "quantity": qty_sold,
        "entry_price": entry_price,
        "entry_mcap": entry_mcap,
        "exit_mcap": exit_mcap,
        "entry_time": pos.get("entry_time", sell_ts),
        "price": exit_price,
        "sol_amount": returned_sol,
        "invested_sol": invested_portion,
        "pnl_pct": pnl_pct,
        "pnl_sol": pnl_sol,
        "hold_seconds": sell_ts - pos.get("entry_time", sell_ts),
        "timestamp": sell_ts,
    }
    user["history"].insert(0, trade)
    return trade


def portfolio_stats(user: dict, current_prices: dict[str, float]) -> dict:
    """current_prices: ca -> current price_usd, for open positions."""
    invested_capital = sum(p["invested_sol"] for p in user["positions"].values())
    unrealized = 0.0
    positions_value = 0.0
    for ca, pos in user["positions"].items():
        price = current_prices.get(ca)
        if price and pos["entry_price"] > 0:
            ratio = price / pos["entry_price"]
        else:
            ratio = 1.0
        val = pos["invested_sol"] * ratio
        positions_value += val
        unrealized += val - pos["invested_sol"]

    portfolio_value = user["balance"] + positions_value

    sells = [t for t in user["history"] if t["type"] == "SELL"]
    buys = [t for t in user["history"] if t["type"] == "BUY"]
    wins = [t for t in sells if (t.get("pnl_sol") or 0) > 0]
    losses = [t for t in sells if (t.get("pnl_sol") or 0) <= 0]
    win_rate = (len(wins) / len(sells) * 100) if sells else 0.0

    now = now_ts()
    daily = sum(t["pnl_sol"] for t in sells if now - t["timestamp"] <= 86400)
    weekly = sum(t["pnl_sol"] for t in sells if now - t["timestamp"] <= 7 * 86400)
    monthly = sum(t["pnl_sol"] for t in sells if now - t["timestamp"] <= 30 * 86400)

    largest_win = max((t["pnl_sol"] for t in sells), default=0.0)
    largest_loss = min((t["pnl_sol"] for t in sells), default=0.0)

    by_token: dict[str, float] = {}
    for t in sells:
        by_token[t["symbol"]] = by_token.get(t["symbol"], 0.0) + t["pnl_sol"]
    best_token = max(by_token.items(), key=lambda kv: kv[1]) if by_token else None
    worst_token = min(by_token.items(), key=lambda kv: kv[1]) if by_token else None

    hold_times = []
    for t in sells:
        buy_match = next((b for b in buys if b["contract_address"] == t["contract_address"]
                           and b["timestamp"] <= t["timestamp"]), None)
        if buy_match:
            hold_times.append(t["timestamp"] - buy_match["timestamp"])
    avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0.0

    avg_return = sum(t["pnl_pct"] for t in sells) / len(sells) if sells else 0.0
    
    total_pnl = user.get("realized_pnl", 0.0) + unrealized
    total_pnl_pct = (total_pnl / invested_capital * 100) if invested_capital > 0 else 0.0

    return {
        "portfolio_value": portfolio_value,
        "available_balance": user["balance"],
        "invested_capital": invested_capital,
        "open_positions": len(user["positions"]),
        "unrealized_pnl": unrealized,
        "realized_pnl": user.get("realized_pnl", 0.0),
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "daily_profit": daily,
        "weekly_profit": weekly,
        "monthly_profit": monthly,
        "total_trades": len(sells),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "best_token": best_token,
        "worst_token": worst_token,
        "avg_hold_seconds": avg_hold,
        "avg_return_pct": avg_return,
    }


# =============================================================================
# SCREEN BUILDERS
# =============================================================================

async def build_home_text(user: dict) -> str:
    prices = {}
    for ca in user["positions"]:
        t = await fetch_token(ca)
        if t:
            prices[ca] = t["price_usd"]
    stats = portfolio_stats(user, prices)

    lines = [
        f"{BRAND}",
        "🏠 *Demo Solana Trading Dashboard*",
        "",
        f"💰 Demo Balance: `{fmt_sol(user['balance'])} SOL`",
        f"📊 Portfolio Value: `{fmt_sol(stats['portfolio_value'])} SOL`",
        f"📂 Open Positions: `{stats['open_positions']}`",
        f"📈 Unrealized PnL: `{'+' if stats['unrealized_pnl'] >= 0 else ''}{fmt_sol(stats['unrealized_pnl'])} SOL`",
        f"✅ Realized PnL: `{'+' if stats['realized_pnl'] >= 0 else ''}{fmt_sol(stats['realized_pnl'])} SOL`",
        f"📊 Total PnL: `{'+' if stats['total_pnl'] >= 0 else ''}{fmt_sol(stats['total_pnl'])} SOL` ({stats['total_pnl_pct']:+.2f}%)",
        f"🏆 Win Rate: `{stats['win_rate']:.1f}%`",
        "",
        "_Paste any Solana contract address to instantly pull up a token._",
    ]
    return "\n".join(lines)


async def build_token_text(ca: str, token: dict, user: dict) -> str:
    pos = user["positions"].get(ca)
    default_buy = user.get("default_buy", DEFAULT_BUY_AMOUNT)

    # Calculate max buy based on liquidity (if available)
    max_buy = "N/A"
    if token.get("liquidity_usd"):
        sol_usd = await get_sol_price_usd()
        max_buy_sol = (token["liquidity_usd"] * 0.01) / sol_usd if sol_usd > 0 else 0
        max_buy = fmt_sol(max_buy_sol)

    lines = [
        f"🟢 *Buy* `${md_escape(token['symbol'])}`",
        f"_{md_escape(token['name'])}_",
        "",
        f"📄 `{ca}`",
        f"[Solscan](https://solscan.io/token/{ca}) • [DexScreener](https://dexscreener.com/solana/{ca}) • [Rugcheck](https://rugcheck.xyz/tokens/{ca})",
        "",
        f"💵 Price: `{fmt_price(token['price_usd'])}`",
        f"🏦 Market Cap: `{fmt_num(token['mc'])}`",
        f"📈 Volume 24h: `{fmt_num(token['volume_24h'])}`",
        f"⏱ 24h Change: {fmt_pct(token['change_h24'])}",
    ]
    
    # Add metadata from Helius if available
    if token.get("decimals") is not None:
        lines.append(f"🔢 Decimals: `{token['decimals']}`")
    if token.get("total_supply"):
        lines.append(f"📊 Total Supply: `{fmt_num_plain(token['total_supply'])}`")
    if token.get("created_at"):
        created = datetime.fromtimestamp(token['created_at'], tz=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - created).days
        lines.append(f"📅 Created: `{created.strftime('%Y-%m-%d')}` ({days_ago}d ago)")
    if token.get("liquidity_usd"):
        lines.append(f"💧 Liquidity: `{fmt_num(token['liquidity_usd'])}`")
        if max_buy != "N/A":
            lines.append(f"⚡ Max Buy (1% slip): `{max_buy} SOL`")
    
    lines.extend([
        "",
        f"👛 Demo Wallet Balance: `{fmt_sol(user['balance'])} SOL`",
    ])

    if pos:
        cur_ratio = (token["price_usd"] / pos["entry_price"]) if pos["entry_price"] else 1.0
        cur_val = pos["invested_sol"] * cur_ratio
        pnl_sol = cur_val - pos["invested_sol"]
        pnl_pct = (cur_ratio - 1) * 100
        emoji = "🟩" if pnl_pct >= 0 else "🟥"
        lines += [
            "",
            f"{emoji} *Current Position*",
            f"Quantity: `{pos['quantity']:,.2f}`",
            f"Entry Price: `{fmt_price(pos['entry_price'])}`",
            f"Entry MCAP: `{fmt_num(pos.get('entry_mcap'))}`",
            f"Invested: `{fmt_sol(pos['invested_sol'])} SOL`",
            f"Current Value: `{fmt_sol(cur_val)} SOL`",
            f"PnL: {fmt_pct(pnl_pct)} (`{'+' if pnl_sol >= 0 else ''}{fmt_sol(pnl_sol)} SOL`)",
        ]

    lines += ["", f"🕒 Data Source: `{token.get('source', 'unknown')}`"]
    return "\n".join(lines)


def build_positions_text(user: dict, page: int, prices: dict[str, float], mcaps: dict[str, float]) -> tuple[str, list[str], int]:
    cas = list(user["positions"].keys())
    total_pages = max(1, (len(cas) + POSITIONS_PER_PAGE - 1) // POSITIONS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_cas = cas[page * POSITIONS_PER_PAGE:(page + 1) * POSITIONS_PER_PAGE]

    # Calculate total PnL for header
    total_unrealized = 0.0
    total_invested = 0.0
    for ca in cas:
        pos = user["positions"][ca]
        price = prices.get(ca)
        if price and pos["entry_price"]:
            ratio = price / pos["entry_price"]
        else:
            ratio = 1.0
        total_unrealized += pos["invested_sol"] * ratio - pos["invested_sol"]
        total_invested += pos["invested_sol"]
    
    total_pnl_pct = (total_unrealized / total_invested * 100) if total_invested > 0 else 0.0

    header = [
        f"{BRAND}",
        "📈 *Open Positions* — Trading Terminal",
        f"📊 Total Unrealized: `{'+' if total_unrealized >= 0 else ''}{fmt_sol(total_unrealized)} SOL` ({total_pnl_pct:+.2f}%)",
        f"📂 Positions: `{len(cas)}`",
        "",
    ]
    
    if not cas:
        header.append("_You have no open positions. Paste a contract address to get started._")
        return "\n".join(header), [], total_pages

    body = []
    # Sort by PnL % (highest first)
    sorted_cas = sorted(page_cas, key=lambda ca: (
        ((prices.get(ca, 0) / user["positions"][ca]["entry_price"]) - 1) if user["positions"][ca]["entry_price"] else -999,
    ), reverse=True)
    
    for ca in sorted_cas:
        pos = user["positions"][ca]
        price = prices.get(ca)
        mcap = mcaps.get(ca)
        
        if price and pos["entry_price"]:
            ratio = price / pos["entry_price"]
        else:
            ratio = 1.0
        cur_val = pos["invested_sol"] * ratio
        pnl_sol = cur_val - pos["invested_sol"]
        pnl_pct = (ratio - 1) * 100
        emoji = "🟩" if pnl_pct >= 0 else "🟥"
        hold = fmt_duration(now_ts() - pos["entry_time"])
        
        entry_mcap = pos.get("entry_mcap")
        current_mcap = mcap

        block = [
            f"{emoji} *${md_escape(pos['symbol'])}* — {md_escape(pos['name'])}",
            f"📄 `{short_addr(ca)}`",
            "",
            f"📊 MCAP: {fmt_num(entry_mcap) if entry_mcap else 'N/A'} → {fmt_num(current_mcap) if current_mcap else 'N/A'}  ({pnl_pct:+.2f}%)",
            f"💰 Invested: `{fmt_sol(pos['invested_sol'])} SOL`  💰 Value: `{fmt_sol(cur_val)} SOL`",
            f"📦 Qty: `{pos['quantity']:,.2f}`  ⏱ Hold: `{hold}`",
            "",
            f"📈 PnL: {fmt_pct(pnl_pct)} (`{'+' if pnl_sol >= 0 else ''}{fmt_sol(pnl_sol)} SOL`)",
            "──────────────────────",
        ]
        body.extend(block)

    footer = [f"_Page {page + 1}/{total_pages}_"]
    return "\n".join(header + body + footer), page_cas, total_pages


def build_portfolio_text(user: dict, stats: dict) -> str:
    best = f"${stats['best_token'][0]} ({'+' if stats['best_token'][1]>=0 else ''}{fmt_sol(stats['best_token'][1])} SOL)" if stats["best_token"] else "N/A"
    worst = f"${stats['worst_token'][0]} ({'+' if stats['worst_token'][1]>=0 else ''}{fmt_sol(stats['worst_token'][1])} SOL)" if stats["worst_token"] else "N/A"

    lines = [
        f"{BRAND}",
        "💼 *Portfolio Overview*",
        "",
        f"💰 Demo Balance: `{fmt_sol(user['balance'])} SOL`",
        f"📊 Portfolio Value: `{fmt_sol(stats['portfolio_value'])} SOL`",
        f"✅ Available Balance: `{fmt_sol(stats['available_balance'])} SOL`",
        f"🏦 Invested Capital: `{fmt_sol(stats['invested_capital'])} SOL`",
        f"📂 Open Positions: `{stats['open_positions']}`",
        "",
        f"📈 Unrealized Profit: `{'+' if stats['unrealized_pnl']>=0 else ''}{fmt_sol(stats['unrealized_pnl'])} SOL`",
        f"✅ Realized Profit: `{'+' if stats['realized_pnl']>=0 else ''}{fmt_sol(stats['realized_pnl'])} SOL`",
        f"📊 Total PnL: `{'+' if stats['total_pnl']>=0 else ''}{fmt_sol(stats['total_pnl'])} SOL` ({stats['total_pnl_pct']:+.2f}%)",
        f"🗓 Daily Profit: `{'+' if stats['daily_profit']>=0 else ''}{fmt_sol(stats['daily_profit'])} SOL`",
        f"🗓 Weekly Profit: `{'+' if stats['weekly_profit']>=0 else ''}{fmt_sol(stats['weekly_profit'])} SOL`",
        f"🗓 Monthly Profit: `{'+' if stats['monthly_profit']>=0 else ''}{fmt_sol(stats['monthly_profit'])} SOL`",
        "",
        f"🔢 Total Trades: `{stats['total_trades']}`",
        f"✅ Winning Trades: `{stats['winning_trades']}`",
        f"❌ Losing Trades: `{stats['losing_trades']}`",
        f"🏆 Win Rate: `{stats['win_rate']:.1f}%`",
        "",
        f"🚀 Largest Win: `{'+' if stats['largest_win']>=0 else ''}{fmt_sol(stats['largest_win'])} SOL`",
        f"💥 Largest Loss: `{fmt_sol(stats['largest_loss'])} SOL`",
        f"🥇 Best Token: {md_escape(best)}",
        f"🥈 Worst Token: {md_escape(worst)}",
        f"⏱ Avg Hold Time: `{fmt_duration(stats['avg_hold_seconds'])}`",
        f"📉 Avg Return: `{stats['avg_return_pct']:+.2f}%`",
    ]
    return "\n".join(lines)


def build_history_text(user: dict, page: int) -> tuple[str, int]:
    trades = user["history"]
    total_pages = max(1, (len(trades) + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_trades = trades[page * HISTORY_PER_PAGE:(page + 1) * HISTORY_PER_PAGE]

    lines = [f"{BRAND}", "📜 *Trade History*", ""]
    if not trades:
        lines.append("_No trades yet. Start by pasting a contract address._")
        return "\n".join(lines), total_pages

    for t in page_trades:
        ts = datetime.fromtimestamp(t["timestamp"], tz=timezone.utc).strftime("%m/%d %H:%M UTC")
        if t["type"] == "BUY":
            lines.append(
                f"🟩 *BUY* `${md_escape(t['symbol'])}`\n"
                f"Entry: `{fmt_price(t['price'])}`  Spent: `{fmt_sol(t['sol_amount'])} SOL`\n"
                f"🕒 {ts}"
            )
        else:
            pnl_sol = t.get("pnl_sol") or 0
            emoji = "🟩" if pnl_sol >= 0 else "🟥"
            lines.append(
                f"{emoji} *SELL* `${md_escape(t['symbol'])}`\n"
                f"Entry: `{fmt_price(t.get('entry_price'))}`  Exit: `{fmt_price(t['price'])}`\n"
                f"PnL: {fmt_pct(t.get('pnl_pct'))} (`{'+' if pnl_sol>=0 else ''}{fmt_sol(pnl_sol)} SOL`)\n"
                f"🕒 {ts}"
            )
        lines.append("─" * 24)

    lines.append(f"_Page {page + 1}/{total_pages}_")
    return "\n".join(lines), total_pages


def build_settings_text(user: dict) -> str:
    return (
        f"{BRAND}\n"
        "⚙️ *Settings*\n\n"
        f"💵 Demo Balance: `{fmt_sol(user['balance'])} SOL`\n"
        f"🎯 Default Buy Amount: `{fmt_sol(user.get('default_buy', DEFAULT_BUY_AMOUNT))} SOL`\n\n"
        "_Choose an option below to update your settings._"
    )


# =============================================================================
# SAFE MESSAGE EDIT HELPER
# =============================================================================

async def safe_edit(query, text: str, reply_markup=None, disable_preview=True):
    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_preview,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("Edit failed: %s", e)
            try:
                await query.answer("⚠️ Could not update — try refreshing.", show_alert=False)
            except Exception:
                pass


async def send_token_logo(context: ContextTypes.DEFAULT_TYPE, chat_id: int, token: dict):
    """Send token logo as a photo if available."""
    logo_url = token.get("logo_url")
    if not logo_url:
        return
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(logo_url)
            resp.raise_for_status()
            photo = io.BytesIO(resp.content)
            photo.name = f"{token['symbol']}_logo.png"
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=f"🪙 *{md_escape(token['symbol'])}* logo",
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception as e:
        logger.warning("Failed to send token logo: %s", e)


# =============================================================================
# HANDLERS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id)
    save_db(db)
    text = await build_home_text(user)
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_home(),
        disable_web_page_preview=True,
    )


async def show_token_screen(query, context, ca: str, force_refresh: bool = False):
    db = load_db()
    user = get_user(db, query.from_user.id)
    token = await fetch_token(ca, force_refresh=force_refresh)
    if not token:
        await safe_edit(
            query,
            f"{BRAND}\n\n⚠️ Could not fetch data for this token.\n"
            f"`{ca}`\n\nIt may be invalid, unlisted, or both Helius and DexScreener are temporarily unavailable.",
            reply_markup=kb_back("home"),
        )
        return
    context.user_data["last_ca"] = ca
    text = await build_token_text(ca, token, user)
    has_pos = ca in user["positions"]
    
    # Send logo if available
    if token.get("logo_url"):
        await send_token_logo(context, query.message.chat_id, token)
    
    await safe_edit(query, text, reply_markup=kb_token(ca, has_pos))


async def show_positions_screen(query, context, page: int):
    db = load_db()
    user = get_user(db, query.from_user.id)
    prices = {}
    mcaps = {}
    for ca in user["positions"]:
        t = await fetch_token(ca)
        if t:
            prices[ca] = t["price_usd"]
            mcaps[ca] = t.get("mc")
    text, page_cas, total_pages = build_positions_text(user, page, prices, mcaps)
    await safe_edit(query, text, reply_markup=kb_positions(page, total_pages, page_cas))


async def show_portfolio_screen(query, context):
    db = load_db()
    user = get_user(db, query.from_user.id)
    prices = {}
    for ca in user["positions"]:
        t = await fetch_token(ca)
        if t:
            prices[ca] = t["price_usd"]
    stats = portfolio_stats(user, prices)
    text = build_portfolio_text(user, stats)
    await safe_edit(query, text, reply_markup=kb_portfolio())


async def show_history_screen(query, context, page: int):
    db = load_db()
    user = get_user(db, query.from_user.id)
    text, total_pages = build_history_text(user, page)
    await safe_edit(query, text, reply_markup=kb_history(page, total_pages))


async def show_settings_screen(query, context):
    db = load_db()
    user = get_user(db, query.from_user.id)
    await safe_edit(query, build_settings_text(user), reply_markup=kb_settings())


async def do_buy(query, context, ca: str, sol_amount: float):
    db = load_db()
    user = get_user(db, query.from_user.id)
    token = await fetch_token(ca)
    if not token:
        await query.answer("⚠️ Could not fetch token price.", show_alert=True)
        return
    try:
        trade = await execute_buy(user, ca, token, sol_amount)
    except TradeError as e:
        await query.answer(str(e), show_alert=True)
        return
    save_db(db)

    stats = portfolio_stats(user, {ca: token["price_usd"]})
    ts = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"🟩 *BUY EXECUTED*\n\n"
        f"Token: `${md_escape(token['symbol'])}` — {md_escape(token['name'])}\n"
        f"Quantity: `{trade['quantity']:,.2f}`\n"
        f"Entry Price: `{fmt_price(trade['price'])}`\n"
        f"Entry MCAP: `{fmt_num(trade.get('mcap'))}`\n"
        f"Invested: `{fmt_sol(trade['sol_amount'])} SOL`\n\n"
        f"👛 Remaining Balance: `{fmt_sol(user['balance'])} SOL`\n"
        f"📊 Portfolio Value: `{fmt_sol(stats['portfolio_value'])} SOL`\n"
        f"🕒 {ts}"
    )
    rows = [
        [InlineKeyboardButton("📊 View Token", callback_data=f"tok:{ca}")],
        [InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
         InlineKeyboardButton("🏠 Home", callback_data="home")],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))
    await query.answer("✅ Buy executed")


async def do_sell(query, context, ca: str, fraction: float):
    db = load_db()
    user = get_user(db, query.from_user.id)
    token = await fetch_token(ca)
    if not token:
        await query.answer("⚠️ Could not fetch token price.", show_alert=True)
        return
    try:
        trade = await execute_sell(user, ca, token, fraction)
    except TradeError as e:
        await query.answer(str(e), show_alert=True)
        return
    save_db(db)

    remaining_prices = {}
    remaining_mcaps = {}
    for c in user["positions"]:
        t = await fetch_token(c)
        if t:
            remaining_prices[c] = t["price_usd"]
            remaining_mcaps[c] = t.get("mc")
    stats = portfolio_stats(user, remaining_prices)
    ts = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pnl_sol = trade["pnl_sol"]
    emoji = "🟩" if pnl_sol >= 0 else "🟥"
    text = (
        f"{emoji} *SELL EXECUTED*\n\n"
        f"Token: `${md_escape(token['symbol'])}` — {md_escape(token['name'])}\n"
        f"Quantity Sold: `{trade['quantity']:,.2f}`\n"
        f"Exit Price: `{fmt_price(trade['price'])}`\n"
        f"Exit MCAP: `{fmt_num(trade.get('exit_mcap'))}`\n"
        f"PnL: {fmt_pct(trade['pnl_pct'])} (`{'+' if pnl_sol>=0 else ''}{fmt_sol(pnl_sol)} SOL`)\n\n"
        f"👛 Remaining Balance: `{fmt_sol(user['balance'])} SOL`\n"
        f"📊 Portfolio Value: `{fmt_sol(stats['portfolio_value'])} SOL`\n"
        f"🕒 {ts}"
    )
    rows = [
        [InlineKeyboardButton("📊 View Token", callback_data=f"tok:{ca}")],
        [InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
         InlineKeyboardButton("🏠 Home", callback_data="home")],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(rows))
    await query.answer("✅ Sell executed")

    # Generate + send the shareable PNL card image automatically
    try:
        card = generate_pnl_card(
            symbol=token["symbol"],
            name=token["name"],
            contract_address=ca,
            buy_mcap=trade.get("entry_mcap"),
            sell_mcap=trade.get("exit_mcap"),
            invested_sol=trade["invested_sol"],
            returned_sol=trade["sol_amount"],
            pnl_pct=trade["pnl_pct"],
            pnl_sol=trade["pnl_sol"],
            hold_seconds=trade["hold_seconds"],
            is_unrealized=False,
        )
        caption = (
            f"{'🟢' if pnl_sol >= 0 else '🔴'} *${md_escape(token['symbol'])}* "
            f"{fmt_pct_plain(trade['pnl_pct'])} — Paper trade via Pulse Bot ⚡"
        )
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=card,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning("Failed to generate/send PNL card: %s", e)


async def do_share(query, context, ca: str):
    db = load_db()
    user = get_user(db, query.from_user.id)
    pos = user["positions"].get(ca)
    token = await fetch_token(ca)
    if not token:
        await query.answer("⚠️ Could not fetch token price.", show_alert=True)
        return

    if pos:
        ratio = (token["price_usd"] / pos["entry_price"]) if pos["entry_price"] else 1.0
        pnl_pct = (ratio - 1) * 100
        pnl_sol = pos["invested_sol"] * (pnl_pct / 100)
        value_sol = pos["invested_sol"] + pnl_sol
        buy_mcap = pos.get("entry_mcap")
        sell_mcap = token.get("mc")
        invested_sol = pos["invested_sol"]
        hold_seconds = now_ts() - pos.get("entry_time", now_ts())
        is_unrealized = True
    else:
        # fall back to most recent closed trade for this token
        last_sell = next((t for t in user["history"] if t["type"] == "SELL" and t["contract_address"] == ca), None)
        if not last_sell:
            await query.answer("No position or trade history found for this token.", show_alert=True)
            return
        pnl_pct = last_sell["pnl_pct"]
        pnl_sol = last_sell["pnl_sol"]
        buy_mcap = last_sell.get("entry_mcap")
        sell_mcap = last_sell.get("exit_mcap")
        invested_sol = last_sell["invested_sol"]
        value_sol = last_sell["sol_amount"]
        hold_seconds = last_sell.get("hold_seconds", 0)
        is_unrealized = False

    try:
        card = generate_pnl_card(
            symbol=token["symbol"],
            name=token["name"],
            contract_address=ca,
            buy_mcap=buy_mcap,
            sell_mcap=sell_mcap,
            invested_sol=invested_sol,
            returned_sol=value_sol,
            pnl_pct=pnl_pct,
            pnl_sol=pnl_sol,
            hold_seconds=hold_seconds,
            is_unrealized=is_unrealized,
        )
        caption = (
            f"{'🟢' if pnl_sol >= 0 else '🔴'} *${md_escape(token['symbol'])}* "
            f"{fmt_pct_plain(pnl_pct)} — Shared from Pulse Bot ⚡"
        )
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=card,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
        )
        await query.answer("📤 PNL card sent")
    except Exception as e:
        logger.warning("Failed to generate/send PNL card: %s", e)
        await query.answer("⚠️ Could not generate card.", show_alert=True)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    await query.answer()

    try:
        if data == "home":
            db = load_db()
            user = get_user(db, query.from_user.id)
            text = await build_home_text(user)
            await safe_edit(query, text, reply_markup=kb_home())

        elif data.startswith("positions:"):
            await show_positions_screen(query, context, int(data.split(":")[1]))

        elif data == "portfolio":
            await show_portfolio_screen(query, context)

        elif data.startswith("history:"):
            await show_history_screen(query, context, int(data.split(":")[1]))

        elif data == "settings":
            await show_settings_screen(query, context)

        elif data == "track":
            await safe_edit(
                query,
                f"{BRAND}\n\n🔍 *Track a Token*\n\n"
                "Paste any Solana token contract address in the chat and I'll pull up "
                "live price, market cap, volume and metadata instantly.\n\n"
                "_Data sourced from Helius API (primary) with DexScreener fallback._",
                reply_markup=kb_back("home"),
            )

        elif data.startswith("tok:"):
            ca = data.split(":", 1)[1]
            await show_token_screen(query, context, ca)

        elif data.startswith("refpos:"):
            ca = data.split(":", 1)[1]
            # Refresh just this position and go back to positions
            await show_positions_screen(query, context, 0)

        elif data.startswith("buy:"):
            ca = data.split(":", 1)[1]
            db = load_db()
            user = get_user(db, query.from_user.id)
            await do_buy(query, context, ca, user.get("default_buy", DEFAULT_BUY_AMOUNT))

        elif data.startswith("cbuy:"):
            ca = data.split(":", 1)[1]
            context.user_data["awaiting"] = "custom_buy"
            context.user_data["awaiting_ca"] = ca
            await safe_edit(
                query,
                f"{BRAND}\n\n💰 *Custom Buy*\n\n"
                "Reply with the amount of SOL you'd like to spend (e.g. `0.5`).",
                reply_markup=kb_back(f"tok:{ca}", "❌ Cancel"),
            )

        elif data.startswith("s25:"):
            await do_sell(query, context, data.split(":", 1)[1], 0.25)
        elif data.startswith("s50:"):
            await do_sell(query, context, data.split(":", 1)[1], 0.50)
        elif data.startswith("s100:"):
            await do_sell(query, context, data.split(":", 1)[1], 1.0)

        elif data.startswith("shr:"):
            await do_share(query, context, data.split(":", 1)[1])

        elif data.startswith("copy:"):
            ca = data.split(":", 1)[1]
            await query.answer(f"📋 Copied: {ca}", show_alert=False)
            # Copy to clipboard via Telegram's copy feature
            await safe_edit(
                query,
                f"{BRAND}\n\n📋 *Contract Address Copied*\n\n"
                f"`{ca}`\n\n_Paste this anywhere to share or track._",
                reply_markup=kb_back("home"),
            )

        elif data == "set_balance":
            context.user_data["awaiting"] = "set_balance"
            await safe_edit(
                query,
                f"{BRAND}\n\n💵 *Set Demo Balance*\n\nReply with the new balance in SOL (e.g. `100`).",
                reply_markup=kb_back("settings", "❌ Cancel"),
            )

        elif data == "set_buy":
            context.user_data["awaiting"] = "set_buy"
            await safe_edit(
                query,
                f"{BRAND}\n\n🎯 *Set Default Buy Amount*\n\nReply with the new default buy amount in SOL (e.g. `0.25`).",
                reply_markup=kb_back("settings", "❌ Cancel"),
            )

        elif data == "reset_portfolio":
            await safe_edit(
                query,
                f"{BRAND}\n\n♻️ *Reset Portfolio*\n\n"
                "This will close all open positions and clear your trade history. "
                "Your balance will not change. This cannot be undone.",
                reply_markup=kb_confirm("reset_portfolio_yes"),
            )

        elif data == "reset_portfolio_yes":
            db = load_db()
            user = get_user(db, query.from_user.id)
            user["positions"] = {}
            user["history"] = []
            user["realized_pnl"] = 0.0
            save_db(db)
            await safe_edit(
                query,
                f"{BRAND}\n\n✅ Portfolio reset. All positions and history cleared.",
                reply_markup=kb_back("settings"),
            )

        elif data == "reset_balance":
            await safe_edit(
                query,
                f"{BRAND}\n\n🔁 *Reset Balance*\n\n"
                f"This will reset your demo balance to `{fmt_sol(DEFAULT_BALANCE)} SOL`. "
                "Positions and history are not affected.",
                reply_markup=kb_confirm("reset_balance_yes"),
            )

        elif data == "reset_balance_yes":
            db = load_db()
            user = get_user(db, query.from_user.id)
            user["balance"] = DEFAULT_BALANCE
            save_db(db)
            await safe_edit(
                query,
                f"{BRAND}\n\n✅ Balance reset to `{fmt_sol(DEFAULT_BALANCE)} SOL`.",
                reply_markup=kb_back("settings"),
            )

        else:
            await query.answer("Unknown action.", show_alert=False)

    except Exception as e:
        logger.exception("Error handling callback %s: %s", data, e)
        try:
            await query.answer("⚠️ Something went wrong. Please try again.", show_alert=True)
        except Exception:
            pass


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    awaiting = context.user_data.get("awaiting")

    db = load_db()
    user = get_user(db, update.effective_user.id)

    if awaiting in ("set_balance", "set_buy", "custom_buy"):
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0 or amount > 1_000_000:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "⚠️ Please enter a valid positive number.", parse_mode=ParseMode.MARKDOWN
            )
            return

        context.user_data["awaiting"] = None

        if awaiting == "set_balance":
            user["balance"] = amount
            save_db(db)
            await update.message.reply_text(
                f"✅ Demo balance set to `{fmt_sol(amount)} SOL`.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back("settings"),
            )
        elif awaiting == "set_buy":
            user["default_buy"] = amount
            save_db(db)
            await update.message.reply_text(
                f"✅ Default buy amount set to `{fmt_sol(amount)} SOL`.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back("settings"),
            )
        elif awaiting == "custom_buy":
            ca = context.user_data.get("awaiting_ca")
            token = await fetch_token(ca) if ca else None
            if not ca or not token:
                await update.message.reply_text("⚠️ Lost track of that token — please paste the contract address again.")
                return
            try:
                trade = await execute_buy(user, ca, token, amount)
            except TradeError as e:
                await update.message.reply_text(f"⚠️ {e}")
                return
            save_db(db)
            stats = portfolio_stats(user, {ca: token["price_usd"]})
            ts = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            reply = (
                f"🟩 *BUY EXECUTED*\n\n"
                f"Token: `${md_escape(token['symbol'])}` — {md_escape(token['name'])}\n"
                f"Quantity: `{trade['quantity']:,.2f}`\n"
                f"Entry Price: `{fmt_price(trade['price'])}`\n"
                f"Entry MCAP: `{fmt_num(trade.get('mcap'))}`\n"
                f"Invested: `{fmt_sol(trade['sol_amount'])} SOL`\n\n"
                f"👛 Remaining Balance: `{fmt_sol(user['balance'])} SOL`\n"
                f"📊 Portfolio Value: `{fmt_sol(stats['portfolio_value'])} SOL`\n"
                f"🕒 {ts}"
            )
            rows = [
                [InlineKeyboardButton("📊 View Token", callback_data=f"tok:{ca}")],
                [InlineKeyboardButton("📈 Positions", callback_data="positions:0"),
                 InlineKeyboardButton("🏠 Home", callback_data="home")],
            ]
            await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
        return

    # Otherwise, look for a Solana contract address
    match = SOL_ADDRESS_RE.search(text)
    if not match:
        await update.message.reply_text(
            "🔍 Paste a valid Solana token contract address to pull up live data, "
            "or use /start to open the dashboard.",
        )
        return

    ca = match.group(0)
    token = await fetch_token(ca)
    if not token:
        await update.message.reply_text(
            f"⚠️ Could not find market data for:\n`{ca}`\n\n"
            "It may be invalid, not indexed by Helius, or not found on DexScreener.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    save_db(db)
    context.user_data["last_ca"] = ca
    
    # Send logo if available
    if token.get("logo_url"):
        await send_token_logo(context, update.message.chat_id, token)
    
    msg_text = await build_token_text(ca, token, user)
    has_pos = ca in user["positions"]
    await update.message.reply_text(
        msg_text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_token(ca, has_pos),
        disable_web_page_preview=True,
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and add your Telegram bot token."
        )

    if not HELIUS_API_KEY:
        logger.warning("HELIUS_API_KEY not set. Will rely on DexScreener fallback.")

    # Python 3.14 compatibility shim
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)

    logger.info("Pulse Bot starting (long-polling)...")
    logger.info("Data sources: Helius (primary) + DexScreener (fallback)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()