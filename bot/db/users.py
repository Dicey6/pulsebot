from datetime import datetime, timezone
from db.client import get_client


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    resp = (
        get_client()
        .table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .single()
        .execute()
    )
    return resp.data


def create_user(
    telegram_id: int,
    telegram_username: str,
    wallet_address: str,
    wallet_encrypted_seed: str,
    sol_balance: float,
    starting_balance_sol: float,
    starting_balance_usd_snapshot: float,
    invitation_code_id: str,
) -> dict:
    resp = (
        get_client()
        .table("users")
        .insert(
            {
                "telegram_id": telegram_id,
                "telegram_username": telegram_username,
                "wallet_address": wallet_address,
                "wallet_encrypted_seed": wallet_encrypted_seed,
                "sol_balance": sol_balance,
                "starting_balance_sol": starting_balance_sol,
                "starting_balance_usd_snapshot": starting_balance_usd_snapshot,
                "status": "active",
                "quick_buy_amounts": [0.1, 0.5, 1.0],
                "quick_sell_percents": [25, 50, 100],
                "invitation_code_id": invitation_code_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .single()
        .execute()
    )
    return resp.data


def update_user_balance(user_id: str, new_balance: float) -> None:
    get_client().table("users").update(
        {
            "sol_balance": new_balance,
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", user_id).execute()


def update_last_active(user_id: str) -> None:
    get_client().table("users").update(
        {"last_active_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", user_id).execute()


def update_quick_buy_amounts(user_id: str, amounts: list[float]) -> None:
    get_client().table("users").update({"quick_buy_amounts": amounts}).eq(
        "id", user_id
    ).execute()


def update_quick_sell_percents(user_id: str, percents: list[float]) -> None:
    get_client().table("users").update({"quick_sell_percents": percents}).eq(
        "id", user_id
    ).execute()
