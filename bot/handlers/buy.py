"""
Buy flow handler.
Users paste a CA / ticker / URL in any chat state.
"""
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import FIXED_GAS_FEE_SOL, MAX_OPEN_POSITIONS
from db.positions import (
    add_to_position,
    count_open_positions,
    get_open_position_for_token,
    open_position,
)
from db.transactions import insert_transaction
from db.users import get_user_by_telegram_id, update_user_balance
from services.market_data import (
    extract_mint_address,
    format_price,
    fmt_mcap,
    get_pumpfun_bonding_curve,
    get_sol_price_usd,
    get_token_data,
    get_token_metadata,
    progress_bar,
    search_token,
)

AWAITING_CUSTOM_AMOUNT = "buy_custom_amount"


def _is_ticker(text: str) -> bool:
    """Heuristic: short word that looks like a ticker, not a URL or address."""
    stripped = text.strip().lstrip("$")
    return bool(re.match(r"^[A-Za-z]{1,10}$", stripped)) and len(text) < 15


async def handle_potential_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called for any non-command text message. Try to parse as token input."""
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    if user["status"] == "banned":
        await update.message.reply_text("Access revoked.")
        return
    if user["status"] == "paused":
        await update.message.reply_text("Your account is temporarily paused. Contact the admin.")
        return

    text = update.message.text.strip()

    # Try to extract a mint address
    mint_address = extract_mint_address(text)
    if not mint_address and _is_ticker(text):
        token_data = await search_token(text.lstrip("$"))
        if token_data:
            mint_address = token_data["address"]

    if not mint_address:
        # Not a recognisable token input — ignore silently or show hint
        return

    await _show_buy_card(update, context, user, mint_address)


async def _show_buy_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: dict,
    mint_address: str,
    edit: bool = False,
) -> None:
    token = await get_token_data(mint_address)
    if not token:
        msg = "❌ Token not found. Please check the address or try again."
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    meta = await get_token_metadata(mint_address)
    bonding_pct = await get_pumpfun_bonding_curve(mint_address)
    sol_price = await get_sol_price_usd()

    symbol = token["symbol"]
    name = token["name"]
    price_usd = token["price_usd"]
    liquidity = token["liquidity_usd"]
    mcap = token["market_cap"]
    sol_balance = float(user["sol_balance"])

    renounced_line = "Renounced ✅" if meta.get("renounced") else "Mint Authority Active ⚠️"

    quick_buys = user.get("quick_buy_amounts") or [0.1, 0.5, 1.0]
    default_buy = quick_buys[0]
    # Estimate price impact (simple: SOL value / liquidity * 100)
    price_impact = (default_buy * sol_price / liquidity * 100) if liquidity > 0 else 0

    text = (
        f"Buy *${symbol}* — {name} 📈\n"
        f"`{mint_address}`\n\n"
        f"Balance: *{sol_balance:.4f} SOL* — Pulse Wallet\n"
        f"Price: {format_price(price_usd)} — LIQ: {fmt_mcap(liquidity)} — MC: {fmt_mcap(mcap)}\n"
        f"{renounced_line}\n"
    )

    if bonding_pct is not None:
        text += (
            f"\n💊 Bonding Curve Progression: *{bonding_pct}%*\n"
            f"`{progress_bar(bonding_pct)}`\n"
        )

    text += (
        f"\nPrice Impact ({default_buy} SOL): {price_impact:.2f}%\n"
        f"Wallet Balance: *{sol_balance:.4f} SOL*\n\n"
        "To buy press one of the buttons below."
    )

    # Store mint address in context for callback
    context.user_data["pending_mint"] = mint_address
    context.user_data["pending_symbol"] = symbol
    context.user_data["pending_name"] = name

    buy_buttons = [
        InlineKeyboardButton(f"Buy {amt} SOL", callback_data=f"buy_exec:{mint_address}:{amt}")
        for amt in quick_buys
    ]
    keyboard = [
        buy_buttons,
        [InlineKeyboardButton("Buy X SOL", callback_data=f"buy_custom:{mint_address}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"buy_refresh:{mint_address}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")],
    ]

    markup = InlineKeyboardMarkup(keyboard)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        target = update.message or (update.callback_query.message if update.callback_query else None)
        await target.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def buy_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("Refreshing…")
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    mint_address = update.callback_query.data.split(":", 1)[1]
    await _show_buy_card(update, context, user, mint_address, edit=True)


async def buy_exec_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    parts = update.callback_query.data.split(":")
    mint_address = parts[1]
    sol_amount = float(parts[2])
    await _execute_buy(update, context, mint_address, sol_amount)


async def buy_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    mint_address = update.callback_query.data.split(":", 1)[1]
    context.user_data["pending_mint"] = mint_address
    keyboard = [[InlineKeyboardButton("⬅️ Cancel", callback_data=f"buy_refresh:{mint_address}")]]
    await update.callback_query.edit_message_text(
        "Enter the amount of SOL you want to buy:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    # We rely on the next text message from the user
    context.user_data["awaiting_custom_buy"] = True


async def handle_custom_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_custom_buy"):
        # Fall through to normal buy handler
        await handle_potential_buy(update, context)
        return

    context.user_data.pop("awaiting_custom_buy", None)
    text = update.message.text.strip()
    try:
        sol_amount = float(text)
        if sol_amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a positive number.")
        return

    mint_address = context.user_data.get("pending_mint")
    if not mint_address:
        return

    await _execute_buy(update, context, mint_address, sol_amount)


async def _execute_buy(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mint_address: str,
    sol_amount: float,
) -> None:
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    if user["status"] in ("paused",):
        target = update.message or update.callback_query.message
        await target.reply_text("Your account is temporarily paused. Contact the admin.")
        return

    if user["status"] == "restricted":
        target = update.message or update.callback_query.message
        await target.reply_text("Your account is restricted. New buys are not allowed.")
        return

    total_cost = sol_amount + FIXED_GAS_FEE_SOL
    sol_balance = float(user["sol_balance"])

    if total_cost > sol_balance:
        target = update.message or update.callback_query.message
        await target.reply_text(
            f"❌ Insufficient balance. You need *{total_cost:.4f} SOL* but only have *{sol_balance:.4f} SOL*.",
            parse_mode="Markdown",
        )
        return

    # Re-fetch live price
    token = await get_token_data(mint_address)
    if not token:
        target = update.message or update.callback_query.message
        await target.reply_text("❌ Could not fetch live price. Please try again.")
        return

    price_usd = token["price_usd"]
    symbol = token["symbol"]
    name = token["name"]
    sol_price = await get_sol_price_usd()
    sol_usd_value = sol_amount * sol_price

    # Tokens received = SOL amount (in USD) / token price
    if price_usd > 0:
        tokens_received = sol_usd_value / price_usd
    else:
        tokens_received = 0

    # Check / update positions
    existing_pos = get_open_position_for_token(user["id"], mint_address)

    if existing_pos:
        pos = add_to_position(
            existing_pos["id"],
            existing_pos,
            tokens_received,
            sol_amount,
            price_usd,
        )
        position_id = existing_pos["id"]
    else:
        open_count = count_open_positions(user["id"])
        if open_count >= MAX_OPEN_POSITIONS:
            target = update.message or update.callback_query.message
            await target.reply_text(
                f"❌ You already have {MAX_OPEN_POSITIONS} open positions — the max allowed. "
                "Close one before opening another."
            )
            return

        pos = open_position(
            user_id=user["id"],
            token_address=mint_address,
            token_symbol=symbol,
            token_name=name,
            amount_tokens=tokens_received,
            entry_price_usd=price_usd,
            sol_invested=sol_amount,
        )
        position_id = pos["id"]

    # Deduct balance
    new_balance = sol_balance - total_cost
    update_user_balance(user["id"], new_balance)

    # Record transaction
    liquidity = token.get("liquidity_usd", 0)
    price_impact = (sol_usd_value / liquidity * 100) if liquidity > 0 else 0
    insert_transaction(
        user_id=user["id"],
        position_id=position_id,
        tx_type="buy",
        token_address=mint_address,
        token_symbol=symbol,
        sol_amount=sol_amount,
        token_amount=tokens_received,
        price_usd=price_usd,
        gas_fee_sol=FIXED_GAS_FEE_SOL,
        mcap_at_trade=token.get("market_cap", 0),
        price_impact_pct=price_impact,
    )

    keyboard = [
        [
            InlineKeyboardButton("📊 View Position", callback_data=f"pos_manage:{position_id}"),
            InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_refresh"),
        ]
    ]

    text = (
        f"✅ *Buy successful*\n\n"
        f"Bought *{tokens_received:,.2f} {symbol}* for *{sol_amount} SOL* (${sol_usd_value:,.2f})\n"
        f"Entry price: {format_price(price_usd)}\n"
        f"Remaining balance: *{new_balance:.4f} SOL*"
    )

    target = update.message or update.callback_query.message
    await target.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


def get_buy_handlers():
    return [
        CallbackQueryHandler(buy_refresh_callback, pattern=r"^buy_refresh:"),
        CallbackQueryHandler(buy_exec_callback, pattern=r"^buy_exec:"),
        CallbackQueryHandler(buy_custom_callback, pattern=r"^buy_custom:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_buy_amount),
    ]
