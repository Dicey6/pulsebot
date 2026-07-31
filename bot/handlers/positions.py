"""Positions list and individual position management (sell, PnL card)."""
import io

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import FIXED_GAS_FEE_SOL
from db.positions import (
    close_position,
    get_open_positions,
    get_position,
    reduce_position,
)
from db.transactions import insert_transaction
from db.users import get_user_by_telegram_id, update_user_balance
from services.market_data import format_price, fmt_mcap, get_sol_price_usd, get_token_data
from services.pnl_generator import generate_pnl_card
from utils.formatters import (
    compute_pnl,
    fmt_pct,
    fmt_sol,
    holding_duration,
    pnl_emoji,
)


# ─── Positions list ─────────────────────────────────────────────────────────────


async def positions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    positions = get_open_positions(user["id"])

    if not positions:
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")]]
        await update.callback_query.edit_message_text(
            "📊 *Your Positions*\n\nYou have no open positions.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = [f"📊 *Your Open Positions ({len(positions)}/4)*\n"]
    buttons = []

    for i, pos in enumerate(positions, 1):
        token = await get_token_data(pos["token_address"])
        current_price = token["price_usd"] if token else float(pos["avg_entry_price_usd"])
        pnl_usd, pnl_pct = compute_pnl(
            float(pos["amount_tokens"]),
            float(pos["avg_entry_price_usd"]),
            current_price,
        )
        emoji = pnl_emoji(pnl_usd)
        lines.append(f"{i}. *{pos['token_symbol']}* {fmt_pct(pnl_pct)} {emoji}")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Manage {pos['token_symbol']} ({fmt_pct(pnl_pct)})",
                    callback_data=f"pos_manage:{pos['id']}",
                )
            ]
        )

    buttons += [
        [InlineKeyboardButton("🔄 Refresh All", callback_data="positions")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")],
    ]

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ─── Individual position card ────────────────────────────────────────────────────


async def pos_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    position_id = update.callback_query.data.split(":", 1)[1]
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    await _show_position_card(update, context, user, position_id)


async def _show_position_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: dict,
    position_id: str,
) -> None:
    pos = get_position(position_id)
    if not pos or pos["status"] != "open":
        await update.callback_query.edit_message_text("Position not found or already closed.")
        return

    token = await get_token_data(pos["token_address"])
    if not token:
        await update.callback_query.edit_message_text(
            "❌ Could not fetch token data. Try refreshing."
        )
        return

    sol_price = await get_sol_price_usd()
    current_price = token["price_usd"]
    amount_tokens = float(pos["amount_tokens"])
    avg_entry = float(pos["avg_entry_price_usd"])
    current_value_usd = amount_tokens * current_price
    pnl_usd, pnl_pct = compute_pnl(amount_tokens, avg_entry, current_price)
    sol_balance = float(user["sol_balance"])
    duration = holding_duration(pos["opened_at"])

    symbol = pos["token_symbol"]
    name = pos["token_name"]
    addr = pos["token_address"]

    text = (
        f"*{symbol}* | {name}\n"
        f"`{addr}`\n\n"
        f"Price: {format_price(current_price)}\n"
        f"5m: {fmt_pct(token['price_change_5m'])}  "
        f"1h: {fmt_pct(token['price_change_1h'])}  "
        f"6h: {fmt_pct(token['price_change_6h'])}  "
        f"24h: {fmt_pct(token['price_change_24h'])}\n"
        f"Market Cap: {fmt_mcap(token['market_cap'])}\n\n"
        f"*Your Position:*\n"
        f"Holding: {amount_tokens:,.2f} {symbol} (${current_value_usd:,.2f})\n"
        f"Avg Entry: {format_price(avg_entry)}\n"
        f"PnL: ${pnl_usd:,.2f} ({fmt_pct(pnl_pct)}) {pnl_emoji(pnl_usd)}\n"
        f"Held for: {duration}\n\n"
        f"Wallet Balance: *{sol_balance:.4f} SOL*"
    )

    quick_buys = user.get("quick_buy_amounts") or [0.1, 0.5, 1.0]
    quick_sells = user.get("quick_sell_percents") or [25, 50, 100]
    pid = position_id

    # Build sell buttons from user preferences (up to 3 + custom)
    sell_row1 = [
        InlineKeyboardButton(f"Sell {int(p)}%", callback_data=f"pos_sell:{pid}:{p}")
        for p in quick_sells[:3]
    ]
    sell_row2 = [
        InlineKeyboardButton("Sell X %", callback_data=f"pos_sell_custom:{pid}"),
    ]

    keyboard = [
        [
            InlineKeyboardButton(f"Buy {amt} SOL", callback_data=f"buy_exec:{addr}:{amt}")
            for amt in quick_buys[:3]
        ],
        sell_row1,
        sell_row2,
        [InlineKeyboardButton("🖼 Generate PnL Card", callback_data=f"pos_pnl_card:{pid}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"pos_manage:{pid}")],
        [InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions")],
    ]

    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─── Sell ────────────────────────────────────────────────────────────────────────


async def pos_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    parts = update.callback_query.data.split(":")
    position_id = parts[1]
    sell_pct = float(parts[2])
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    await _execute_sell(update, context, user, position_id, sell_pct)


async def pos_sell_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    position_id = update.callback_query.data.split(":", 1)[1]
    context.user_data["awaiting_custom_sell_pid"] = position_id
    keyboard = [[InlineKeyboardButton("⬅️ Cancel", callback_data=f"pos_manage:{position_id}")]]
    await update.callback_query.edit_message_text(
        "Enter the percentage to sell (1-100):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_custom_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pid = context.user_data.get("awaiting_custom_sell_pid")
    if not pid:
        return  # Not waiting for a sell %
    context.user_data.pop("awaiting_custom_sell_pid", None)
    try:
        pct = float(update.message.text.strip())
        if not (0 < pct <= 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid percentage. Enter a number between 1 and 100.")
        return

    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return
    await _execute_sell_msg(update, context, user, pid, pct)


async def _execute_sell(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: dict,
    position_id: str,
    sell_pct: float,
) -> None:
    pos = get_position(position_id)
    if not pos or pos["status"] != "open":
        await update.callback_query.edit_message_text("Position already closed.")
        return

    token = await get_token_data(pos["token_address"])
    if not token:
        await update.callback_query.edit_message_text("❌ Could not fetch live price. Try again.")
        return

    current_price = token["price_usd"]
    sol_price = await get_sol_price_usd()
    amount_tokens = float(pos["amount_tokens"])
    tokens_to_sell = amount_tokens * (sell_pct / 100)
    proceeds_usd = tokens_to_sell * current_price
    proceeds_sol = proceeds_usd / sol_price if sol_price > 0 else 0
    net_sol = proceeds_sol - FIXED_GAS_FEE_SOL

    avg_entry = float(pos["avg_entry_price_usd"])
    cost_basis_usd = tokens_to_sell * avg_entry
    pnl_usd = proceeds_usd - cost_basis_usd
    pnl_pct = (pnl_usd / cost_basis_usd * 100) if cost_basis_usd > 0 else 0

    symbol = pos["token_symbol"]
    is_full = sell_pct >= 100

    if is_full:
        close_position(position_id)
    else:
        reduce_position(position_id, pos, tokens_to_sell, proceeds_sol)

    new_balance = float(user["sol_balance"]) + net_sol
    update_user_balance(user["id"], new_balance)

    liquidity = token.get("liquidity_usd", 0)
    price_impact = (proceeds_usd / liquidity * 100) if liquidity > 0 else 0
    insert_transaction(
        user_id=user["id"],
        position_id=position_id,
        tx_type="sell",
        token_address=pos["token_address"],
        token_symbol=symbol,
        sol_amount=proceeds_sol,
        token_amount=tokens_to_sell,
        price_usd=current_price,
        gas_fee_sol=FIXED_GAS_FEE_SOL,
        mcap_at_trade=token.get("market_cap", 0),
        price_impact_pct=price_impact,
    )

    keyboard = [[InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions")]]
    await update.callback_query.edit_message_text(
        f"✅ Sold *{int(sell_pct)}%* of *{symbol}* for *{proceeds_sol:.4f} SOL* (${proceeds_usd:,.2f})\n"
        f"PnL: ${pnl_usd:,.2f} ({fmt_pct(pnl_pct)})\n"
        f"New balance: *{new_balance:.4f} SOL*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _execute_sell_msg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: dict,
    position_id: str,
    sell_pct: float,
) -> None:
    """Same logic but triggered from a text message (custom sell %)."""
    pos = get_position(position_id)
    if not pos or pos["status"] != "open":
        await update.message.reply_text("Position already closed.")
        return

    token = await get_token_data(pos["token_address"])
    if not token:
        await update.message.reply_text("❌ Could not fetch live price. Try again.")
        return

    current_price = token["price_usd"]
    sol_price = await get_sol_price_usd()
    amount_tokens = float(pos["amount_tokens"])
    tokens_to_sell = amount_tokens * (sell_pct / 100)
    proceeds_usd = tokens_to_sell * current_price
    proceeds_sol = proceeds_usd / sol_price if sol_price > 0 else 0
    net_sol = proceeds_sol - FIXED_GAS_FEE_SOL

    avg_entry = float(pos["avg_entry_price_usd"])
    cost_basis_usd = tokens_to_sell * avg_entry
    pnl_usd = proceeds_usd - cost_basis_usd
    pnl_pct = (pnl_usd / cost_basis_usd * 100) if cost_basis_usd > 0 else 0

    symbol = pos["token_symbol"]

    if sell_pct >= 100:
        close_position(position_id)
    else:
        reduce_position(position_id, pos, tokens_to_sell, proceeds_sol)

    new_balance = float(user["sol_balance"]) + net_sol
    update_user_balance(user["id"], new_balance)

    liquidity = token.get("liquidity_usd", 0)
    price_impact = (proceeds_usd / liquidity * 100) if liquidity > 0 else 0
    insert_transaction(
        user_id=user["id"],
        position_id=position_id,
        tx_type="sell",
        token_address=pos["token_address"],
        token_symbol=symbol,
        sol_amount=proceeds_sol,
        token_amount=tokens_to_sell,
        price_usd=current_price,
        gas_fee_sol=FIXED_GAS_FEE_SOL,
        mcap_at_trade=token.get("market_cap", 0),
        price_impact_pct=price_impact,
    )

    keyboard = [[InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions")]]
    await update.message.reply_text(
        f"✅ Sold *{int(sell_pct)}%* of *{symbol}* for *{proceeds_sol:.4f} SOL* (${proceeds_usd:,.2f})\n"
        f"PnL: ${pnl_usd:,.2f} ({fmt_pct(pnl_pct)})\n"
        f"New balance: *{new_balance:.4f} SOL*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── PnL Card ────────────────────────────────────────────────────────────────────


async def pos_pnl_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("Generating card…")
    position_id = update.callback_query.data.split(":", 1)[1]
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    pos = get_position(position_id)
    if not pos:
        return

    token = await get_token_data(pos["token_address"])
    if not token:
        return

    current_price = token["price_usd"]
    sol_price = await get_sol_price_usd()
    amount_tokens = float(pos["amount_tokens"])
    avg_entry = float(pos["avg_entry_price_usd"])
    pnl_usd, pnl_pct = compute_pnl(amount_tokens, avg_entry, current_price)
    current_value_usd = amount_tokens * current_price
    duration = holding_duration(pos["opened_at"])
    handle = f"@{user['telegram_username']}" if user.get("telegram_username") else None

    png_bytes = generate_pnl_card(
        ticker=pos["token_symbol"],
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        sol_invested=float(pos["total_sol_invested"]),
        current_value_usd=current_value_usd,
        holding_duration=duration,
        telegram_handle=handle,
    )

    await update.callback_query.message.reply_photo(
        photo=io.BytesIO(png_bytes),
        caption=f"*{pos['token_symbol']}* PnL Card | {fmt_pct(pnl_pct)}",
        parse_mode="Markdown",
    )


def get_positions_handlers():
    return [
        CallbackQueryHandler(positions_callback, pattern="^positions$"),
        CallbackQueryHandler(pos_manage_callback, pattern=r"^pos_manage:"),
        CallbackQueryHandler(pos_sell_callback, pattern=r"^pos_sell:[^_]"),
        CallbackQueryHandler(pos_sell_custom_callback, pattern=r"^pos_sell_custom:"),
        CallbackQueryHandler(pos_pnl_card_callback, pattern=r"^pos_pnl_card:"),
    ]
