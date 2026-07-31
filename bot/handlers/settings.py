"""Settings handler — quick buy amounts and quick sell %."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from db.users import get_user_by_telegram_id, update_quick_buy_amounts, update_quick_sell_percents


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    qb = user.get("quick_buy_amounts") or [0.1, 0.5, 1.0]
    qs = user.get("quick_sell_percents") or [25, 50, 100]

    qb_str = " / ".join(f"{x} SOL" for x in qb)
    qs_str = " / ".join(f"{int(x)}%" for x in qs)

    text = (
        "⚙️ *Settings*\n\n"
        f"Quick Buy Amounts: *{qb_str}*\n"
        f"Quick Sell %: *{qs_str}*"
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Edit Quick Buy Amounts", callback_data="settings_edit_buy")],
        [InlineKeyboardButton("✏️ Edit Quick Sell %", callback_data="settings_edit_sell")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")],
    ]

    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def settings_edit_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    context.user_data["awaiting_setting"] = "buy"
    keyboard = [[InlineKeyboardButton("⬅️ Cancel", callback_data="settings")]]
    await update.callback_query.edit_message_text(
        "Enter 3 quick-buy amounts in SOL, comma-separated.\n\nExample: `0.1, 0.5, 1`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def settings_edit_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    context.user_data["awaiting_setting"] = "sell"
    keyboard = [[InlineKeyboardButton("⬅️ Cancel", callback_data="settings")]]
    await update.callback_query.edit_message_text(
        "Enter 3 quick-sell percentages (1-100), comma-separated.\n\nExample: `25, 50, 100`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    setting = context.user_data.get("awaiting_setting")
    if not setting:
        return  # Let other handlers deal with it

    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    raw = update.message.text.strip()

    try:
        values = [float(v.strip()) for v in raw.split(",")]
        if len(values) != 3:
            raise ValueError("Need exactly 3 values")
        if setting == "sell" and any(v <= 0 or v > 100 for v in values):
            raise ValueError("Sell % must be 1-100")
        if setting == "buy" and any(v <= 0 for v in values):
            raise ValueError("Buy amounts must be positive")
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid input: {e}\n\nPlease try again.")
        return

    context.user_data.pop("awaiting_setting", None)

    if setting == "buy":
        update_quick_buy_amounts(user["id"], values)
        await update.message.reply_text(
            f"✅ Quick buy amounts updated: {' / '.join(f'{v} SOL' for v in values)}"
        )
    else:
        update_quick_sell_percents(user["id"], values)
        await update.message.reply_text(
            f"✅ Quick sell percentages updated: {' / '.join(f'{int(v)}%' for v in values)}"
        )


def get_settings_handlers():
    return [
        CallbackQueryHandler(settings_callback, pattern="^settings$"),
        CallbackQueryHandler(settings_edit_buy_callback, pattern="^settings_edit_buy$"),
        CallbackQueryHandler(settings_edit_sell_callback, pattern="^settings_edit_sell$"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_input),
    ]
