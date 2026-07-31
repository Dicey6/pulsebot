"""Main menu display and refresh logic."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from db.positions import count_open_positions
from db.users import get_user_by_telegram_id, update_last_active
from services.market_data import get_sol_price_usd


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: dict | None = None,
) -> None:
    tg = update.effective_user

    if user is None:
        user = get_user_by_telegram_id(tg.id)
        if not user:
            return

    if user["status"] == "banned":
        msg = update.message or update.callback_query.message
        await msg.reply_text("Access revoked.")
        return

    update_last_active(user["id"])
    sol_price = await get_sol_price_usd()
    sol_balance = float(user["sol_balance"])
    usd_value = sol_balance * sol_price
    open_count = count_open_positions(user["id"])

    text = (
        f"Welcome back *{user['telegram_username']}* 👋\n\n"
        f"Balance: *{sol_balance:.4f} SOL* (${usd_value:,.2f})\n"
        f"SOL Price: ${sol_price:,.2f}\n\n"
        f"You have *{open_count}/4* open position(s).\n\n"
        "To buy a token: paste a ticker, token address, or a URL from pump.fun, "
        "Birdeye, DEX Screener, or Meteora."
    )

    keyboard = [
        [
            InlineKeyboardButton("💼 Wallet", callback_data="wallet"),
            InlineKeyboardButton("📊 Positions", callback_data="positions"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
            InlineKeyboardButton("🔄 Refresh", callback_data="main_refresh"),
        ],
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        msg = update.message
        await msg.reply_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def main_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await show_main_menu(update, context)


def get_menu_handlers():
    return [CallbackQueryHandler(main_refresh_callback, pattern="^main_refresh$")]
