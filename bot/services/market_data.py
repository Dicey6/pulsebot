"""
Market data fetching: DexScreener, Helius, pump.fun.
All calls are async using httpx.
"""
import asyncio
import re
import time
from typing import Optional

import httpx

from config import DEXSCREENER_BASE_URL, HELIUS_API_KEY, PUMPFUN_FRONTEND_API

# In-memory price cache: {token_address: (data, timestamp)}
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 5  # seconds


async def _get(url: str, **kwargs) -> dict | list | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, **kwargs)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ─── SOL/USD price ─────────────────────────────────────────────────────────────

_sol_price_cache: tuple[float, float] = (0.0, 0.0)  # (price, ts)


async def get_sol_price_usd() -> float:
    global _sol_price_cache
    if time.time() - _sol_price_cache[1] < 15:
        return _sol_price_cache[0]
    # SOL/USDC pair on DexScreener
    data = await _get(
        f"{DEXSCREENER_BASE_URL}/latest/dex/tokens/So11111111111111111111111111111111111111112"
    )
    try:
        pairs = data.get("pairs") or []
        for p in pairs:
            if p.get("quoteToken", {}).get("symbol") == "USDC":
                price = float(p["priceUsd"])
                _sol_price_cache = (price, time.time())
                return price
        # fallback: first pair
        price = float(pairs[0]["priceUsd"])
        _sol_price_cache = (price, time.time())
        return price
    except Exception:
        return _sol_price_cache[0] or 150.0


# ─── Token data from DexScreener ───────────────────────────────────────────────


async def get_token_data(address: str) -> dict | None:
    now = time.time()
    if address in _cache and now - _cache[address][1] < CACHE_TTL:
        return _cache[address][0]

    data = await _get(f"{DEXSCREENER_BASE_URL}/latest/dex/tokens/{address}")
    if not data:
        return None

    pairs = data.get("pairs") or []
    if not pairs:
        return None

    # Pick the highest-liquidity pair
    pairs.sort(key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
    pair = pairs[0]

    base = pair.get("baseToken", {})
    result = {
        "address": address,
        "symbol": base.get("symbol", "???"),
        "name": base.get("name", "Unknown"),
        "price_usd": float(pair.get("priceUsd") or 0),
        "price_native": float(pair.get("priceNative") or 0),
        "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or 0),
        "market_cap": float(pair.get("fdv") or pair.get("marketCap") or 0),
        "price_change_5m": float((pair.get("priceChange") or {}).get("m5") or 0),
        "price_change_1h": float((pair.get("priceChange") or {}).get("h1") or 0),
        "price_change_6h": float((pair.get("priceChange") or {}).get("h6") or 0),
        "price_change_24h": float((pair.get("priceChange") or {}).get("h24") or 0),
        "pair_address": pair.get("pairAddress", ""),
        "dex_id": pair.get("dexId", ""),
    }
    _cache[address] = (result, now)
    return result


async def search_token(query: str) -> dict | None:
    """Search by ticker symbol; return the best match."""
    data = await _get(
        f"{DEXSCREENER_BASE_URL}/latest/dex/search", params={"q": query}
    )
    pairs = (data or {}).get("pairs") or []
    if not pairs:
        return None
    pairs.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
    p = pairs[0]
    return await get_token_data(p["baseToken"]["address"])


# ─── Helius metadata + authority check ─────────────────────────────────────────


async def get_token_metadata(address: str) -> dict:
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": "pulse",
        "method": "getAsset",
        "params": {"id": address},
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            result = r.json().get("result", {})
    except Exception:
        return {"renounced": False, "symbol": None, "name": None}

    authorities = result.get("authorities") or []
    mint_authority = None
    for auth in authorities:
        if "mint" in (auth.get("scopes") or []):
            mint_authority = auth.get("address")
            break

    content = result.get("content") or {}
    meta = content.get("metadata") or {}

    return {
        "renounced": mint_authority is None,
        "symbol": meta.get("symbol"),
        "name": meta.get("name"),
        "mint_authority": mint_authority,
    }


# ─── pump.fun bonding curve ─────────────────────────────────────────────────────


async def get_pumpfun_bonding_curve(address: str) -> float | None:
    """Returns bonding curve completion % or None if graduated/not found."""
    data = await _get(f"{PUMPFUN_FRONTEND_API}/coins/{address}")
    if not data:
        return None
    # If the token has graduated to a DEX, bonding curve is irrelevant
    if data.get("raydium_pool") or data.get("complete"):
        return None
    virtual_sol = float(data.get("virtual_sol_reserves") or 0)
    total_sol_target = 85.0  # ~85 SOL to graduate on pump.fun
    if total_sol_target == 0:
        return None
    pct = min((virtual_sol / total_sol_target) * 100, 100)
    return round(pct, 1)


# ─── Address extraction from various URL formats ────────────────────────────────

_SOLANA_ADDR_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def extract_mint_address(text: str) -> str | None:
    """Extract a Solana mint address from raw text, URL, or direct address."""
    # pump.fun: https://pump.fun/<address>
    # Birdeye: https://birdeye.so/token/<address>
    # DexScreener: https://dexscreener.com/solana/<pair_address> — we get pair, not mint; handle below
    # Meteora: https://app.meteora.ag/pools/<address>
    patterns = [
        r"pump\.fun/([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"birdeye\.so/token/([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"meteora\.ag/pools/([1-9A-HJ-NP-Za-km-z]{32,44})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    # Raw address
    m = _SOLANA_ADDR_RE.search(text.strip())
    if m:
        return m.group(0)
    return None


def format_number(n: float) -> str:
    """Format large numbers as $1.2K, $3.4M etc."""
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.2f}K"
    return f"${n:.2f}"


# Alias used by handlers
fmt_mcap = format_number


def format_price(p: float) -> str:
    if p == 0:
        return "$0"
    if p < 0.000001:
        return f"${p:.2e}"
    if p < 0.001:
        return f"${p:.8f}"
    if p < 1:
        return f"${p:.6f}"
    return f"${p:.4f}"


def progress_bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)
