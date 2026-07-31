"""Formatting helpers shared across handlers."""
from datetime import datetime, timezone


def fmt_sol(n: float) -> str:
    return f"{n:.4f} SOL"


def fmt_usd(n: float) -> str:
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"${n/1_000:.2f}K"
    return f"${n:.2f}"


def fmt_price(p: float) -> str:
    if p == 0:
        return "$0"
    if p < 0.000001:
        return f"${p:.2e}"
    if p < 0.001:
        return f"${p:.8f}"
    if p < 1:
        return f"${p:.6f}"
    return f"${p:.4f}"


def fmt_mcap(n: float) -> str:
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.2f}K"
    return f"${n:.0f}"


def fmt_pct(p: float) -> str:
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def pnl_emoji(pnl: float) -> str:
    return "🟢" if pnl >= 0 else "🔴"


def holding_duration(opened_at_iso: str) -> str:
    """Return a human-readable holding duration from an ISO timestamp."""
    try:
        opened = datetime.fromisoformat(opened_at_iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - opened
        total_seconds = int(delta.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return "—"


def compute_pnl(
    amount_tokens: float,
    avg_entry_price_usd: float,
    current_price_usd: float,
) -> tuple[float, float]:
    """Returns (pnl_usd, pnl_pct)."""
    current_value = amount_tokens * current_price_usd
    cost_basis = amount_tokens * avg_entry_price_usd
    pnl_usd = current_value - cost_basis
    pnl_pct = (pnl_usd / cost_basis * 100) if cost_basis > 0 else 0.0
    return pnl_usd, pnl_pct
