"""Supabase data layer for Pulse Bot."""
from __future__ import annotations

import time
import uuid
import logging
from typing import Optional

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, STARTING_BALANCE_SOL

log = logging.getLogger("pulsebot.db")
_client: Optional[Client] = None


def db() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Invite codes ──────────────────────────────────────────────────────────────

def get_invite_code(code: str) -> Optional[dict]:
    try:
        r = db().table("invite_codes").select("*").eq("code", code.strip().upper()).eq("is_used", False).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        log.error("get_invite_code: %s", e)
        return None


def mark_invite_used(code: str, telegram_id: int) -> None:
    try:
        db().table("invite_codes").update({
            "is_used": True,
            "used_by": telegram_id,
            "used_at": time.time(),
        }).eq("code", code.strip().upper()).execute()
    except Exception as e:
        log.error("mark_invite_used: %s", e)


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> Optional[dict]:
    try:
        r = db().table("users").select("*").eq("id", telegram_id).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        log.error("get_user: %s", e)
        return None


def create_user(telegram_id: int, username: str, first_name: str, invite_code: str) -> dict:
    data = {
        "id": telegram_id,
        "username": username or "",
        "first_name": first_name or "",
        "balance_sol": STARTING_BALANCE_SOL,
        "realized_pnl_sol": 0.0,
        "invite_code": invite_code,
        "created_at": time.time(),
    }
    r = db().table("users").insert(data).execute()
    return r.data[0]


def update_user_balance(telegram_id: int, balance_sol: float) -> None:
    try:
        db().table("users").update({"balance_sol": round(balance_sol, 6)}).eq("id", telegram_id).execute()
    except Exception as e:
        log.error("update_user_balance: %s", e)


def add_realized_pnl(telegram_id: int, pnl_sol: float) -> None:
    user = get_user(telegram_id)
    if not user:
        return
    new_pnl = round((user.get("realized_pnl_sol") or 0.0) + pnl_sol, 6)
    try:
        db().table("users").update({"realized_pnl_sol": new_pnl}).eq("id", telegram_id).execute()
    except Exception as e:
        log.error("add_realized_pnl: %s", e)


# ── Positions ─────────────────────────────────────────────────────────────────

def get_positions(telegram_id: int) -> list[dict]:
    try:
        r = db().table("positions").select("*").eq("user_id", telegram_id).order("entry_time").execute()
        return r.data or []
    except Exception as e:
        log.error("get_positions: %s", e)
        return []


def get_position(telegram_id: int, ca: str) -> Optional[dict]:
    try:
        r = db().table("positions").select("*").eq("user_id", telegram_id).eq("contract_address", ca).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        log.error("get_position: %s", e)
        return None


def upsert_position(telegram_id: int, pos: dict) -> None:
    try:
        record = {**pos, "user_id": telegram_id}
        db().table("positions").upsert(record, on_conflict="user_id,contract_address").execute()
    except Exception as e:
        log.error("upsert_position: %s", e)


def delete_position(telegram_id: int, ca: str) -> None:
    try:
        db().table("positions").delete().eq("user_id", telegram_id).eq("contract_address", ca).execute()
    except Exception as e:
        log.error("delete_position: %s", e)


# ── Trades ────────────────────────────────────────────────────────────────────

def save_trade(telegram_id: int, trade: dict) -> None:
    try:
        record = {**trade, "user_id": telegram_id, "id": trade.get("id") or uuid.uuid4().hex[:12]}
        db().table("trades").insert(record).execute()
    except Exception as e:
        log.error("save_trade: %s", e)


def get_trades(telegram_id: int, limit: int = 50) -> list[dict]:
    try:
        r = (
            db().table("trades").select("*")
            .eq("user_id", telegram_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return r.data or []
    except Exception as e:
        log.error("get_trades: %s", e)
        return []
