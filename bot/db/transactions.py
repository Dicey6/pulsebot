from datetime import datetime, timezone
from db.client import get_client


def insert_transaction(
    user_id: str,
    position_id: str | None,
    tx_type: str,  # "buy" or "sell"
    token_address: str,
    token_symbol: str,
    sol_amount: float,
    token_amount: float,
    price_usd: float,
    gas_fee_sol: float,
    mcap_at_trade: float,
    price_impact_pct: float,
) -> dict:
    resp = (
        get_client()
        .table("transactions")
        .insert(
            {
                "user_id": user_id,
                "position_id": position_id,
                "type": tx_type,
                "token_address": token_address,
                "token_symbol": token_symbol,
                "sol_amount": sol_amount,
                "token_amount": token_amount,
                "price_usd": price_usd,
                "gas_fee_sol": gas_fee_sol,
                "mcap_at_trade": mcap_at_trade,
                "price_impact_pct": price_impact_pct,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .single()
        .execute()
    )
    return resp.data
