"""Wallet screen handler."""
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import DEV_DONATION_WALLET
from db.users import get_user_by_telegram_id
from services.market_data import get_sol_price_usd


async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    sol_price = await get_sol_price_usd()
    sol_balance = float(user["sol_balance"])
    usd_value = sol_balance * sol_price

    addr = user["wallet_address"]
    masked = f"{addr[:6]}...{addr[-4:]}"

    text = (
        "💼 *Wallet*\n\n"
        f"Address: `{masked}`\n"
        f"Balance: *{sol_balance:.4f} SOL* (${usd_value:,.2f})\n\n"
        "_Your wallet address and seed phrase are real Solana credentials._"
    )

    keyboard = [
        [InlineKeyboardButton("👁 Export Seed Phrase", callback_data="wallet_export_confirm")],
        [InlineKeyboardButton("💙 Support the Dev", callback_data="wallet_donate")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")],
    ]

    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def wallet_export_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    keyboard = [
        [InlineKeyboardButton("⚠️ Yes, reveal my seed phrase", callback_data="wallet_export_reveal")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="wallet")],
    ]
    await update.callback_query.edit_message_text(
        "⚠️ *Security Warning*\n\n"
        "Never share your seed phrase with anyone.\n\n"
        "Your seed phrase gives *full access* to your wallet. "
        "The message will self-delete in 60 seconds.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def wallet_export_reveal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)
    if not user:
        return

    phrase = user["wallet_encrypted_seed"]  # stored as plaintext

    msg = await update.callback_query.message.reply_text(
        f"🔑 *Your Seed Phrase*\n\n`{phrase}`\n\n"
        "⚠️ _Never share this with anyone. This message will be deleted in 60 seconds._",
        parse_mode="Markdown",
    )

    # Auto-delete after 60 seconds
    async def delete_later():
        await asyncio.sleep(60)
        try:
            await msg.delete()
        except Exception:
            pass

    asyncio.create_task(delete_later())

    # Return user to wallet screen
    keyboard = [[InlineKeyboardButton("⬅️ Back to Wallet", callback_data="wallet")]]
    await update.callback_query.edit_message_text(
        "Seed phrase sent above. It will be deleted in 60 seconds.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def wallet_donate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]
    await update.callback_query.edit_message_text(
        "💙 *Support Development*\n\n"
        "If you'd like to support development, donations are welcome — never required.\n\n"
        f"`{DEV_DONATION_WALLET}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def get_wallet_handlers():
    return [
        CallbackQueryHandler(wallet_callback, pattern="^wallet$"),
        CallbackQueryHandler(wallet_export_confirm_callback, pattern="^wallet_export_confirm$"),
        CallbackQueryHandler(wallet_export_reveal_callback, pattern="^wallet_export_reveal$"),
        CallbackQueryHandler(wallet_donate_callback, pattern="^wallet_donate$"),
    ]
