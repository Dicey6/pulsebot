from db.client import get_client


def get_unused_code(code: str) -> dict | None:
    """Return an unused invitation code row or None."""
    resp = (
        get_client()
        .table("invitation_codes")
        .select("*")
        .eq("code", code)
        .eq("status", "unused")
        .single()
        .execute()
    )
    return resp.data


def mark_code_used(code_id: str, telegram_id: int) -> None:
    from datetime import datetime, timezone

    get_client().table("invitation_codes").update(
        {
            "status": "used",
            "assigned_telegram_id": telegram_id,
            "used_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", code_id).execute()
