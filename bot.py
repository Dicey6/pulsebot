"""Pulse Bot — complete rebuild. Trojan-style Solana paper-trading bot."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

from config import (
    BOT_TOKEN,
    BUY_PRESETS,
    DEXSCREENER_URL,
    HELIUS_API_KEY,
    HELIUS_RPC_URL,
    JUPITER_PRICE_URL,
    SELL_FRACTIONS,
    SOL_MINT,
    TOKEN_CACHE_TTL,
    TRADE_FEE_SOL,
)
import database as db_mod
from pnl_card import generate_pnl_card

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("pulsebot")
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Regex — Solana base-58 address ───────────────────────────────────────────
SOL_ADDR_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

# ── In-memory caches ──────────────────────────────────────────────────────────
_token_cache: dict[str, dict] = {}
_sol_cache:   dict            = {"price": 178.0, "ts": 0.0}

# ── user_data state keys ──────────────────────────────────────────────────────
S_INVITE     = "INVITE_CODE"
S_CUSTOM_BUY = "CUSTOM_BUY"


# =============================================================================
# TOKEN / PRICE API
# =============================================================================

async def _jupiter_price(mint: str) -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(JUPITER_PRICE_URL, params={"ids": mint})
            r.raise_for_status()
            info = (r.json().get("data") or {}).get(mint)
            if info:
                v = float(info.get("price") or 0)
                return v if v else None
    except Exception as e:
        log.debug("Jupiter %s: %s", mint[:8], e)
    return None


async def _dex_data(ca: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(DEXSCREENER_URL.format(ca))
            r.raise_for_status()
            data = r.json()
        pairs = [p for p in (data.get("pairs") or []) if p.get("chainId") == "solana"]
        if not pairs:
            pairs = data.get("pairs") or []
        if not pairs:
            return None
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        base = best.get("baseToken") or {}
        return {
            "name":         base.get("name", "Unknown"),
            "symbol":       base.get("symbol", "???"),
            "price_usd":    float(best.get("priceUsd") or 0),
            "mc":           best.get("marketCap") or best.get("fdv"),
            "volume_24h":   (best.get("volume") or {}).get("h24"),
            "change_h24":   (best.get("priceChange") or {}).get("h24"),
            "liquidity_usd": (best.get("liquidity") or {}).get("usd"),
        }
    except Exception as e:
        log.debug("DexScreener %s: %s", ca[:8], e)
    return None


async def _helius_meta(ca: str) -> dict:
    try:
        payload = {"jsonrpc": "2.0", "id": "pb", "method": "getAsset", "params": {"id": ca}}
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(f"{HELIUS_RPC_URL}?api-key={HELIUS_API_KEY}", json=payload)
            r.raise_for_status()
        asset = r.json().get("result") or {}
        content = asset.get("content", {})
        meta    = content.get("metadata", {})
        ti      = asset.get("token_info", {})
        logo    = content.get("links", {}).get("image") or meta.get("image")
        return {"name": meta.get("name"), "symbol": meta.get("symbol"),
                "decimals": ti.get("decimals"), "logo_url": logo}
    except Exception:
        return {}


async def fetch_token(ca: str, force: bool = False) -> Optional[dict]:
    now = time.time()
    if not force and ca in _token_cache:
        cached = _token_cache[ca]
        if now - cached.get("fetched_at", 0) < TOKEN_CACHE_TTL:
            return cached

    jup, dex = await asyncio.gather(
        _jupiter_price(ca), _dex_data(ca), return_exceptions=True
    )
    if isinstance(jup, Exception): jup = None
    if isinstance(dex, Exception): dex = None

    price = jup or (dex.get("price_usd") if dex else None)
    if not price:
        return None

    meta = await _helius_meta(ca)

    token = {
        "address":       ca,
        "name":          meta.get("name") or (dex.get("name") if dex else "Unknown") or "Unknown",
        "symbol":        meta.get("symbol") or (dex.get("symbol") if dex else "???") or "???",
        "price_usd":     price,
        "mc":            dex.get("mc") if dex else None,
        "volume_24h":    dex.get("volume_24h") if dex else None,
        "change_h24":    dex.get("change_h24") if dex else None,
        "liquidity_usd": dex.get("liquidity_usd") if dex else None,
        "logo_url":      meta.get("logo_url"),
        "fetched_at":    now,
    }
    _token_cache[ca] = token
    return token


async def sol_price() -> float:
    now = time.time()
    if now - _sol_cache["ts"] < 60:
        return _sol_cache["price"]
    p = await _jupiter_price(SOL_MINT)
    if not p:
        d = await _dex_data(SOL_MINT)
        p = (d.get("price_usd") if d else None)
    if p:
        _sol_cache["price"] = p
        _sol_cache["ts"]    = now
    return _sol_cache["price"]


# =============================================================================
# FORMAT HELPERS
# =============================================================================

def fu(v: Optional[float]) -> str:
    if v is None: return "—"
    if abs(v) >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if abs(v) >= 1_000_000:     return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:         return f"${v/1_000:.1f}K"
    if abs(v) >= 1:             return f"${v:.4f}"
    if abs(v) >= 0.00001:       return f"${v:.6f}"
    return f"${v:.10f}"


def fs(v: float) -> str:
    return f"{v:.4f} SOL"


def fp(v: Optional[float]) -> str:
    if v is None: return "—"
    s = "+" if v >= 0 else ""
    return f"{s}{v:.2f}%"


def pe(v: Optional[float]) -> str:
    if v is None: return "⚪"
    return "🟢" if v >= 0 else "🔴"


def short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}" if addr and len(addr) > 10 else addr or "—"


def age(ts: float) -> str:
    d = time.time() - ts
    if d < 60:    return f"{int(d)}s"
    if d < 3600:  return f"{int(d//60)}m"
    if d < 86400: return f"{int(d//3600)}h {int((d%3600)//60)}m"
    return f"{int(d//86400)}d"


# =============================================================================
# KEYBOARD / SCREEN BUILDERS
# =============================================================================

def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(list(rows))

def btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


async def screen_main(user: dict, sol_usd: float) -> tuple[str, InlineKeyboardMarkup]:
    bal     = user.get("balance_sol", 0.0)
    pnl     = user.get("realized_pnl_sol", 0.0)
    n_pos   = len(db_mod.get_positions(user["id"]))
    sign    = "+" if pnl >= 0 else ""
    col     = "🟢" if pnl >= 0 else "🔴"
    text = (
        f"⚡ <b>PULSE BOT</b>\n\n"
        f"💰 <b>{fs(bal)}</b>  ·  <i>{fu(bal * sol_usd)}</i>\n"
        f"{col} Realized P&amp;L: <b>{sign}{fs(pnl)}</b>  ·  <i>{sign}{fu(pnl * sol_usd)}</i>\n\n"
        f"<code>───────────────────────</code>\n"
        f"<i>Paste a contract address to trade</i>"
    )
    return text, kb(
        [btn(f"💼 Positions ({n_pos})", "pos_list"), btn("📊 Portfolio", "portfolio")],
        [btn("⚙️ Settings", "settings")],
    )


def screen_token(tok: dict, user: dict) -> tuple[str, InlineKeyboardMarkup]:
    ca     = tok["address"]
    owned  = db_mod.get_position(user["id"], ca) is not None
    change = tok.get("change_h24")
    chg    = f"  {pe(change)} <b>{fp(change)}</b>" if change is not None else ""
    text = (
        f"📍 <b>{tok['name']}</b>  <code>${tok['symbol'].upper()}</code>\n"
        f"<code>{short(ca)}</code>\n\n"
        f"💲 Price:    <b>{fu(tok['price_usd'])}</b>{chg}\n"
        f"📊 MCap:     <b>{fu(tok.get('mc'))}</b>\n"
        f"💧 Liq:      <b>{fu(tok.get('liquidity_usd'))}</b>\n"
        f"📈 Vol 24h:  <b>{fu(tok.get('volume_24h'))}</b>\n"
    )
    if owned:
        text += "\n<i>✅ You already hold this token — buying adds to position</i>"

    buy_row = [btn(f"Buy {p} SOL", f"buy:{ca}:{p}") for p in BUY_PRESETS]
    return text, kb(
        buy_row,
        [btn("✏️ Custom Amount", f"buy:{ca}:custom")],
        [btn("🔄 Refresh", f"tokref:{ca}"), btn("↩️ Back", "main")],
    )


async def screen_positions(user: dict, sol_usd: float) -> tuple[str, InlineKeyboardMarkup]:
    positions = db_mod.get_positions(user["id"])
    if not positions:
        return (
            "💼 <b>Positions</b>\n\n<i>No open positions.\nPaste a contract address to start trading.</i>",
            kb([btn("↩️ Back", "main")])
        )

    prices = await asyncio.gather(*[fetch_token(p["contract_address"]) for p in positions])
    rows   = []
    lines  = ["💼 <b>Positions</b>\n"]
    for pos, tok in zip(positions, prices):
        ep  = pos.get("entry_price", 0)
        sym = pos.get("symbol", "???")
        inv = pos.get("invested_sol", 0)
        if tok and ep and ep > 0:
            pct = ((tok["price_usd"] / ep) - 1) * 100
        else:
            pct = None
        s   = "+" if (pct or 0) >= 0 else ""
        ps  = f"{s}{pct:.1f}%" if pct is not None else "—"
        lines.append(f"  {pe(pct)} <b>{sym}</b>  {ps}  ·  {fs(inv)}")
        rows.append([btn(f"{sym}  {ps}", f"pos:{pos['contract_address']}")])

    rows.append([btn("↩️ Back", "main")])
    return "\n".join(lines), kb(*rows)


async def screen_position(user: dict, ca: str, sol_usd: float) -> tuple[str, InlineKeyboardMarkup]:
    pos = db_mod.get_position(user["id"], ca)
    if not pos:
        return "❌ Position not found.", kb([btn("↩️ Positions", "pos_list")])

    tok       = await fetch_token(ca, force=True)
    cur_price = tok["price_usd"] if tok else pos.get("entry_price", 0)
    cur_mc    = tok.get("mc") if tok else None
    ep        = pos.get("entry_price", 0)
    em        = pos.get("entry_mcap")
    inv       = pos.get("invested_sol", 0)

    if ep and ep > 0:
        pct     = ((cur_price / ep) - 1) * 100
        cur_sol = inv * (cur_price / ep)
    else:
        pct     = 0.0
        cur_sol = inv

    pnl_sol = cur_sol - inv
    sign    = "+" if pnl_sol >= 0 else ""
    col     = pe(pct)
    mc_was  = f"  <i>was {fu(em)}</i>" if em else ""

    text = (
        f"📍 <b>{pos.get('name','Unknown')}</b>  <code>${(pos.get('symbol') or '???').upper()}</code>\n"
        f"<code>{short(ca)}</code>\n"
        f"<code>───────────────────────</code>\n\n"
        f"💲 Price:     <b>{fu(cur_price)}</b>  {col} <b>{fp(pct)}</b>\n"
        f"📊 MCap:      <b>{fu(cur_mc)}</b>{mc_was}\n\n"
        f"📥 Invested:  <b>{fs(inv)}</b>  ·  <i>{fu(inv * sol_usd)}</i>\n"
        f"💼 Value:     <b>{fs(cur_sol)}</b>  ·  <i>{fu(cur_sol * sol_usd)}</i>\n"
        f"{'🟢' if pnl_sol >= 0 else '🔴'} P&amp;L:      <b>{sign}{fs(pnl_sol)}</b>  ·  <i>{sign}{fu(pnl_sol * sol_usd)}</i>\n\n"
        f"<i>Held for {age(pos.get('entry_time', time.time()))}</i>"
    )
    return text, kb(
        [btn("Sell 25%", f"sell:{ca}:0.25"),  btn("Sell 50%",  f"sell:{ca}:0.50")],
        [btn("Sell 75%", f"sell:{ca}:0.75"),  btn("Sell 100%", f"sell:{ca}:1.00")],
        [btn("📊 PnL Card", f"pnlcard:{ca}")],
        [btn("🔄 Refresh", f"pos:{ca}"), btn("↩️ Positions", "pos_list")],
    )


async def screen_portfolio(user: dict, sol_usd: float) -> tuple[str, InlineKeyboardMarkup]:
    positions = db_mod.get_positions(user["id"])
    trades    = db_mod.get_trades(user["id"])
    bal       = user.get("balance_sol", 0.0)
    realized  = user.get("realized_pnl_sol", 0.0)
    buys      = [t for t in trades if t["type"] == "BUY"]
    sells     = [t for t in trades if t["type"] == "SELL"]
    wins      = [t for t in sells if (t.get("pnl_sol") or 0) > 0]
    wr        = int(len(wins) / len(sells) * 100) if sells else 0
    rs        = "+" if realized >= 0 else ""
    rc        = "🟢" if realized >= 0 else "🔴"
    text = (
        f"📊 <b>Portfolio</b>\n"
        f"<code>───────────────────────</code>\n\n"
        f"💰 Balance:        <b>{fs(bal)}</b>  ·  <i>{fu(bal * sol_usd)}</i>\n"
        f"{rc} Realized P&amp;L:  <b>{rs}{fs(realized)}</b>  ·  <i>{rs}{fu(realized * sol_usd)}</i>\n\n"
        f"<code>───────────────────────</code>\n\n"
        f"📂 Open Positions: <b>{len(positions)}</b>\n"
        f"📋 Total Trades:   <b>{len(trades)}</b>  <i>({len(buys)} buys · {len(sells)} sells)</i>\n"
        f"🏆 Win Rate:       <b>{wr}%</b>\n"
    )
    return text, kb([btn("↩️ Back", "main")])


def screen_settings(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"⚙️ <b>Settings</b>\n"
        f"<code>───────────────────────</code>\n\n"
        f"👤 Username:    @{user.get('username') or '—'}\n"
        f"🔑 Telegram ID: <code>{user['id']}</code>\n\n"
        f"⚡ Trade Fee:   <b>{TRADE_FEE_SOL} SOL</b> per trade\n"
        f"📥 Buy Presets: <b>{' / '.join(str(p) + ' SOL' for p in BUY_PRESETS)}</b>\n"
    )
    return text, kb([btn("↩️ Back", "main")])


# =============================================================================
# CORE MESSAGE HELPER
# =============================================================================

async def show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    photo: Optional[bytes] = None,
    force_new: bool = False,
):
    cid = update.effective_chat.id
    mid = context.user_data.get("mid")

    if photo:
        if mid:
            try: await context.bot.delete_message(cid, mid)
            except: pass
        msg = await context.bot.send_photo(
            cid, photo=photo, caption=text[:1024],
            reply_markup=keyboard, parse_mode=ParseMode.HTML,
        )
        context.user_data["mid"] = msg.message_id
        return

    if update.callback_query and not force_new:
        try:
            await update.callback_query.message.edit_text(
                text, reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
            context.user_data["mid"] = update.callback_query.message.message_id
            return
        except BadRequest:
            pass  # identical content — fine

    if mid:
        try: await context.bot.delete_message(cid, mid)
        except: pass
    msg = await context.bot.send_message(
        cid, text, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    context.user_data["mid"] = msg.message_id


async def del_user_msg(update: Update):
    try: await update.message.delete()
    except: pass


# =============================================================================
# HANDLERS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = db_mod.get_user(uid)
    if user:
        sp = await sol_price()
        t, k = await screen_main(user, sp)
        await show(update, context, t, k, force_new=True)
        return

    context.user_data["state"] = S_INVITE
    await show(update, context,
        "⚡ <b>Welcome to Pulse Bot</b>\n\n"
        "Enter your <b>invite code</b> to get started.\n"
        "<i>Contact the admin if you don't have one.</i>",
        InlineKeyboardMarkup([]), force_new=True,
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = db_mod.get_user(uid)
    if not user:
        await cmd_start(update, context)
        return
    sp = await sol_price()
    t, k = await screen_main(user, sp)
    await show(update, context, t, k, force_new=True)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid   = update.effective_user.id
    text  = update.message.text.strip()
    state = context.user_data.get("state")

    # ── Invite code ───────────────────────────────────────────────────────────
    if state == S_INVITE:
        await del_user_msg(update)
        code   = text.upper()
        invite = db_mod.get_invite_code(code)
        if not invite:
            await show(update, context,
                "⚡ <b>Welcome to Pulse Bot</b>\n\n"
                "❌ Invalid or already-used invite code.\n"
                "<i>Try again or contact the admin.</i>",
                InlineKeyboardMarkup([]),
            )
            return
        u    = update.effective_user
        user = db_mod.create_user(uid, u.username or "", u.first_name or "", code)
        db_mod.mark_invite_used(code, uid)
        context.user_data.pop("state", None)
        sp = await sol_price()
        t, k = await screen_main(user, sp)
        await show(update, context, t, k)
        return

    # ── Custom buy amount ─────────────────────────────────────────────────────
    if state == S_CUSTOM_BUY:
        await del_user_msg(update)
        ca = context.user_data.pop("buy_ca", None)
        context.user_data.pop("state", None)
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0: raise ValueError
        except ValueError:
            user = db_mod.get_user(uid)
            tok  = await fetch_token(ca) if ca else None
            if tok and user:
                t, k = screen_token(tok, user)
                await show(update, context, f"❌ Invalid amount. Enter a positive number.\n\n{t}", k)
            return
        await _buy(update, context, uid, ca, amount)
        return

    # ── Solana CA detection ───────────────────────────────────────────────────
    user = db_mod.get_user(uid)
    if not user:
        await cmd_start(update, context)
        return

    match = SOL_ADDR_RE.search(text)
    if not match:
        return

    ca = match.group(0)
    await del_user_msg(update)
    await show(update, context,
        f"🔍 <b>Looking up token…</b>\n\n<code>{short(ca)}</code>",
        InlineKeyboardMarkup([]),
    )
    tok = await fetch_token(ca)
    if not tok:
        sp = await sol_price()
        t, k = await screen_main(user, sp)
        await show(update, context,
            f"❌ <b>Token not found</b>\n\nNo price data for:\n<code>{ca}</code>\n\n{t}", k,
        )
        return

    context.user_data["last_ca"] = ca
    t, k = screen_token(tok, user)
    await show(update, context, t, k)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    uid  = update.effective_user.id
    user = db_mod.get_user(uid)
    if not user:
        await cmd_start(update, context)
        return

    sp = await sol_price()

    if data == "main":
        t, k = await screen_main(user, sp)
        await show(update, context, t, k)

    elif data == "pos_list":
        t, k = await screen_positions(user, sp)
        await show(update, context, t, k)

    elif data == "portfolio":
        t, k = await screen_portfolio(user, sp)
        await show(update, context, t, k)

    elif data == "settings":
        t, k = screen_settings(user)
        await show(update, context, t, k)

    elif data.startswith("pos:"):
        ca = data[4:]
        t, k = await screen_position(user, ca, sp)
        await show(update, context, t, k)

    elif data.startswith("tokref:"):
        ca  = data[7:]
        tok = await fetch_token(ca, force=True)
        if tok:
            t, k = screen_token(tok, user)
            await show(update, context, t, k)

    elif data.startswith("buy:"):
        _, ca, amt_s = data.split(":", 2)
        if amt_s == "custom":
            context.user_data["state"]  = S_CUSTOM_BUY
            context.user_data["buy_ca"] = ca
            await show(update, context,
                f"✏️ <b>Custom Buy Amount</b>\n\n"
                f"Token: <code>{short(ca)}</code>\n\n"
                f"<i>Reply with the SOL amount (e.g. <code>0.25</code>):</i>",
                kb([btn("↩️ Cancel", f"tokref:{ca}")]),
            )
            return
        await _buy(update, context, uid, ca, float(amt_s))

    elif data.startswith("sell:"):
        _, ca, frac_s = data.split(":", 2)
        await _sell(update, context, uid, ca, float(frac_s), sp)

    elif data.startswith("pnlcard:"):
        await _pnlcard_unrealized(update, context, uid, data[8:], sp)


# =============================================================================
# TRADING LOGIC
# =============================================================================

async def _buy(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    uid: int,
    ca: str,
    amount: float,
):
    sp   = await sol_price()
    user = db_mod.get_user(uid)
    tok  = await fetch_token(ca)

    if not tok:
        t, k = await screen_main(user, sp)
        await show(update, context, f"❌ Could not fetch token data.\n\n{t}", k)
        return

    total = amount + TRADE_FEE_SOL
    if user["balance_sol"] < total:
        t, k = screen_token(tok, user)
        await show(update, context,
            f"❌ <b>Insufficient balance</b>\n\n"
            f"Need: <b>{fs(total)}</b>  (incl. fee)\n"
            f"Have: <b>{fs(user['balance_sol'])}</b>\n\n{t}", k,
        )
        return

    price = tok["price_usd"]
    qty   = (amount * sp) / price
    mc    = tok.get("mc")
    pos   = db_mod.get_position(uid, ca)

    if pos:
        tq = pos["quantity"] + qty
        ti = pos["invested_sol"] + amount
        ne = (pos["entry_price"] * pos["quantity"] + price * qty) / tq if tq else price
        nm = None
        if mc and pos.get("entry_mcap"):
            nm = (pos["entry_mcap"] * pos["quantity"] + mc * qty) / tq
        db_mod.upsert_position(uid, {
            "contract_address": ca,
            "name":             pos["name"],
            "symbol":           pos["symbol"],
            "quantity":         tq,
            "entry_price":      ne,
            "entry_mcap":       nm or pos.get("entry_mcap"),
            "invested_sol":     ti,
            "entry_time":       pos.get("entry_time", time.time()),
        })
    else:
        db_mod.upsert_position(uid, {
            "contract_address": ca,
            "name":             tok["name"],
            "symbol":           tok["symbol"],
            "quantity":         qty,
            "entry_price":      price,
            "entry_mcap":       mc,
            "invested_sol":     amount,
            "entry_time":       time.time(),
        })

    db_mod.update_user_balance(uid, user["balance_sol"] - total)
    db_mod.save_trade(uid, {
        "id": uuid.uuid4().hex[:12], "type": "BUY",
        "contract_address": ca, "symbol": tok["symbol"], "name": tok["name"],
        "quantity": qty, "price": price, "mcap": mc,
        "sol_amount": amount, "pnl_pct": None, "pnl_sol": None, "timestamp": time.time(),
    })

    user = db_mod.get_user(uid)
    sym  = tok["symbol"].upper()
    await show(update, context,
        f"✅ <b>Buy Executed</b>\n\n"
        f"<b>${sym}</b>  ·  {fs(amount)}\n"
        f"Price:    <b>{fu(price)}</b>\n"
        f"MCap:     <b>{fu(mc)}</b>\n"
        f"Fee:      <b>{fs(TRADE_FEE_SOL)}</b>\n\n"
        f"Balance:  <b>{fs(user['balance_sol'])}</b>",
        kb([btn(f"💼 View Position", f"pos:{ca}"), btn("↩️ Main Menu", "main")]),
    )


async def _sell(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    uid: int,
    ca: str,
    fraction: float,
    sol_usd: float,
):
    user = db_mod.get_user(uid)
    pos  = db_mod.get_position(uid, ca)
    if not pos:
        await show(update, context, "❌ Position not found.", kb([btn("↩️ Back", "pos_list")]))
        return

    tok = await fetch_token(ca, force=True)
    if not tok:
        t, k = await screen_position(user, ca, sol_usd)
        await show(update, context, f"❌ Could not fetch price.\n\n{t}", k)
        return

    exit_p  = tok["price_usd"]
    exit_mc = tok.get("mc")
    ep      = pos["entry_price"]
    inv     = pos["invested_sol"]
    qty     = pos["quantity"]

    qty_sold  = qty * fraction
    inv_part  = inv * fraction
    pnl_pct   = ((exit_p / ep) - 1) * 100 if ep > 0 else 0.0
    pnl_sol   = inv_part * (pnl_pct / 100)
    recv_sol  = max(0.0, inv_part + pnl_sol - TRADE_FEE_SOL)

    rem_qty = qty - qty_sold
    rem_inv = inv - inv_part

    if rem_qty < 1e-9 or fraction >= 1.0:
        db_mod.delete_position(uid, ca)
        rem_qty = 0
        rem_inv = 0
    else:
        db_mod.upsert_position(uid, {
            "contract_address": ca,
            "name":             pos["name"],
            "symbol":           pos["symbol"],
            "quantity":         rem_qty,
            "entry_price":      ep,
            "entry_mcap":       pos.get("entry_mcap"),
            "invested_sol":     rem_inv,
            "entry_time":       pos.get("entry_time", time.time()),
        })

    db_mod.update_user_balance(uid, user["balance_sol"] + recv_sol)
    db_mod.add_realized_pnl(uid, pnl_sol)
    db_mod.save_trade(uid, {
        "id": uuid.uuid4().hex[:12], "type": "SELL",
        "contract_address": ca, "symbol": pos.get("symbol"), "name": pos.get("name"),
        "quantity": qty_sold, "price": exit_p, "mcap": exit_mc,
        "sol_amount": recv_sol, "pnl_pct": pnl_pct, "pnl_sol": pnl_sol, "timestamp": time.time(),
    })

    user    = db_mod.get_user(uid)
    sym     = (pos.get("symbol") or "???").upper()
    sign    = "+" if pnl_sol >= 0 else ""
    em      = "🟢" if pnl_sol >= 0 else "🔴"
    pct_lbl = int(fraction * 100)
    rem_val = rem_inv * (exit_p / ep) if ep and rem_inv else 0.0

    caption = (
        f"{em} <b>Sold {pct_lbl}% of ${sym}</b>\n\n"
        f"Received:  <b>{fs(recv_sol)}</b>  ·  <i>{fu(recv_sol * sol_usd)}</i>\n"
        f"P&amp;L:   <b>{sign}{fp(pnl_pct)}</b>  ·  <i>{sign}{fs(pnl_sol)}</i>\n"
    )
    if fraction < 1.0 and rem_val > 0:
        caption += f"Holding:   <b>{fs(rem_val)}</b>  ·  <i>{fu(rem_val * sol_usd)}</i>\n"
    caption += f"\nBalance:   <b>{fs(user['balance_sol'])}</b>"

    sell_kb = kb([btn("💼 Positions", "pos_list"), btn("↩️ Main Menu", "main")])

    # Generate PnL card
    try:
        card = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_pnl_card(
            token_name=pos.get("name", "Unknown"),
            token_symbol=pos.get("symbol", "???"),
            contract_address=ca,
            entry_price=ep,
            current_price=exit_p,
            entry_mcap=pos.get("entry_mcap"),
            current_mcap=exit_mc,
            invested_sol=inv_part,
            sol_price_usd=sol_usd,
            sold_sol=recv_sol,
            sold_fraction=fraction,
            remaining_sol_value=rem_val if fraction < 1.0 else None,
            is_unrealized=False,
        ))
        await show(update, context, caption, sell_kb, photo=card)
    except Exception as e:
        log.error("PnL card failed: %s", e)
        await show(update, context, caption, sell_kb)


async def _pnlcard_unrealized(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    uid: int,
    ca: str,
    sol_usd: float,
):
    pos = db_mod.get_position(uid, ca)
    if not pos:
        return
    tok       = await fetch_token(ca, force=True)
    cur_price = tok["price_usd"] if tok else pos.get("entry_price", 0)
    cur_mc    = tok.get("mc") if tok else None
    ep        = pos.get("entry_price", 0)
    sym       = (pos.get("symbol") or "???").upper()
    pnl_pct   = ((cur_price / ep) - 1) * 100 if ep else 0.0
    sign      = "+" if pnl_pct >= 0 else ""

    try:
        card = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_pnl_card(
            token_name=pos.get("name", "Unknown"),
            token_symbol=pos.get("symbol", "???"),
            contract_address=ca,
            entry_price=ep,
            current_price=cur_price,
            entry_mcap=pos.get("entry_mcap"),
            current_mcap=cur_mc,
            invested_sol=pos.get("invested_sol", 0),
            sol_price_usd=sol_usd,
            is_unrealized=True,
        ))
    except Exception as e:
        log.error("PnL card error: %s", e)
        return

    caption = (
        f"📊 <b>${sym} — P&amp;L</b>\n\n"
        f"Entry:    <b>{fu(ep)}</b>\n"
        f"Current:  <b>{fu(cur_price)}</b>\n"
        f"P&amp;L:  <b>{sign}{fp(pnl_pct)}</b>"
    )
    await show(update, context, caption, kb([btn("↩️ Position", f"pos:{ca}")]), photo=card)


# ── Error handler ─────────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Error: %s", context.error, exc_info=context.error)


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(20)
        .read_timeout(20)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    # ── Health server for Render Web Service ──────────────────────────────────
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass

    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever(),
        daemon=True,
    ).start()
    # ─────────────────────────────────────────────────────────────────────────

    log.info("Pulse Bot started.")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
