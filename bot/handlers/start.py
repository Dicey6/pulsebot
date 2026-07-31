"""
/start handler and invitation-code onboarding flow.
"""
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

from db.invite_codes import get_unused_code, mark_code_used
from db.users import create_user, get_user_by_telegram_id
from services.market_data import get_sol_price_usd
from services.wallet_gen import generate_wallet

AWAITING_CODE = 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg = update.effective_user
    user = get_user_by_telegram_id(tg.id)

    if user:
        if user["status"] == "banned":
            await update.message.reply_text("Access revoked.")
            return ConversationHandler.END

        await _show_main_menu(update, context, user)
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Welcome to *Pulse Trading Bot*\n\n"
        "Enter your invitation code to continue.",
        parse_mode="Markdown",
    )
    return AWAITING_CODE


async def handle_invite_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code_input = update.message.text.strip()
    tg = update.effective_user

    code_row = get_unused_code(code_input)
    if not code_row:
        await update.message.reply_text(
            "❌ Invalid or already-used invitation code.\n\nPlease try again or contact the admin."
        )
        return AWAITING_CODE

    # Mark code used
    mark_code_used(code_row["id"], tg.id)

    # Generate wallet
    wallet_address, phrase = generate_wallet()
    encrypted_seed = phrase  # stored as-is

    # Snapshot SOL price at account creation
    sol_price = await get_sol_price_usd()
    starting_balance = float(code_row["starting_balance_sol"])
    starting_usd_snapshot = starting_balance * sol_price

    user = create_user(
        telegram_id=tg.id,
        telegram_username=tg.username or tg.first_name or str(tg.id),
        wallet_address=wallet_address,
        wallet_encrypted_seed=encrypted_seed,
        sol_balance=starting_balance,
        starting_balance_sol=starting_balance,
        starting_balance_usd_snapshot=starting_usd_snapshot,
        invitation_code_id=code_row["id"],
    )

    await update.message.reply_text(
        f"✅ *Welcome to Pulse Trading Bot!*\n\n"
        f"Your account has been activated with *{starting_balance} SOL*.\n\n"
        "The fastest and most secure bot for trading any token on Solana.\n\n"
        "Paste any token address, ticker, or URL to get started.",
        parse_mode="Markdown",
    )
    await _show_main_menu(update, context, user)
    return ConversationHandler.END


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """Import here to avoid circular import."""
    from handlers.menu import show_main_menu
    await show_main_menu(update, context, user)


def get_start_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AWAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_invite_code)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="onboarding",
        persistent=False,
    )
