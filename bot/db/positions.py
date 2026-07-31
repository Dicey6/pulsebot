from datetime import datetime, timezone
from db.client import get_client


def get_open_positions(user_id: str) -> list[dict]:
    resp = (
        get_client()
        .table("positions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "open")
        .order("opened_at", desc=False)
        .execute()
    )
    return resp.data or []


def count_open_positions(user_id: str) -> int:
    return len(get_open_positions(user_id))


def get_position(position_id: str) -> dict | None:
    resp = (
        get_client()
        .table("positions")
        .select("*")
        .eq("id", position_id)
        .single()
        .execute()
    )
    return resp.data


def get_open_position_for_token(user_id: str, token_address: str) -> dict | None:
    resp = (
        get_client()
        .table("positions")
        .select("*")
        .eq("user_id", user_id)
        .eq("token_address", token_address)
        .eq("status", "open")
        .single()
        .execute()
    )
    return resp.data


def open_position(
    user_id: str,
    token_address: str,
    token_symbol: str,
    token_name: str,
    amount_tokens: float,
    entry_price_usd: float,
    sol_invested: float,
) -> dict:
    resp = (
        get_client()
        .table("positions")
        .insert(
            {
                "user_id": user_id,
                "token_address": token_address,
                "token_symbol": token_symbol,
                "token_name": token_name,
                "amount_tokens": amount_tokens,
                "avg_entry_price_usd": entry_price_usd,
                "total_sol_invested": sol_invested,
                "status": "open",
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .single()
        .execute()
    )
    return resp.data


def add_to_position(
    position_id: str,
    existing: dict,
    new_token_amount: float,
    new_sol_invested: float,
    current_price_usd: float,
) -> dict:
    """Add to an existing position, recalculating weighted average entry price."""
    total_tokens = existing["amount_tokens"] + new_token_amount
    total_sol = existing["total_sol_invested"] + new_sol_invested

    # Weighted average: existing cost basis + new cost basis
    existing_cost = existing["amount_tokens"] * existing["avg_entry_price_usd"]
    new_cost = new_token_amount * current_price_usd
    new_avg = (existing_cost + new_cost) / total_tokens if total_tokens > 0 else current_price_usd

    resp = (
        get_client()
        .table("positions")
        .update(
            {
                "amount_tokens": total_tokens,
                "avg_entry_price_usd": new_avg,
                "total_sol_invested": total_sol,
            }
        )
        .eq("id", position_id)
        .single()
        .execute()
    )
    return resp.data


def reduce_position(
    position_id: str,
    existing: dict,
    tokens_sold: float,
    sol_returned: float,
) -> dict:
    """Reduce tokens held after a partial sell."""
    remaining = existing["amount_tokens"] - tokens_sold
    new_sol_invested = existing["total_sol_invested"] - sol_returned
    resp = (
        get_client()
        .table("positions")
        .update(
            {
                "amount_tokens": max(remaining, 0),
                "total_sol_invested": max(new_sol_invested, 0),
            }
        )
        .eq("id", position_id)
        .single()
        .execute()
    )
    return resp.data


def close_position(position_id: str) -> None:
    get_client().table("positions").update(
        {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "amount_tokens": 0,
        }
    ).eq("id", position_id).execute()
