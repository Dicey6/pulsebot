"""Help screen handler."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

HELP_TEXT = """
❓ *Pulse Trading Bot — Help*

*How to trade:*
Paste any of the following into the chat and the bot will pull up live market data:
• Token contract address (CA) — e.g. `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`
• Ticker symbol — e.g. `$BONK` or `BONK`
• pump.fun URL — e.g. `https://pump.fun/...`
• Birdeye URL — e.g. `https://birdeye.so/token/...`
• DEX Screener URL — e.g. `https://dexscreener.com/solana/...`
• Meteora URL — e.g. `https://app.meteora.ag/pools/...`

*Buying:*
After pasting a token, tap one of the quick-buy buttons or enter a custom SOL amount. You can hold up to 4 open positions at once.

*Selling:*
Go to *Positions* → tap the token → choose a quick-sell percentage or enter a custom one. Selling 100% closes the position.

*Wallet:*
View your Solana wallet address and balance. Your wallet is a real Solana address — you can export the seed phrase at any time (keep it safe).

*Settings:*
Customise your 3 quick-buy SOL amounts and 3 quick-sell percentages.

*PnL Card:*
Inside any open position, tap *🖼 Generate PnL Card* to get a shareable image with your trade stats.

*Need help?*
Contact the admin through the invite code that granted you access.
"""


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_refresh")]]
    await update.callback_query.edit_message_text(
        HELP_TEXT,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def get_help_handlers():
    return [CallbackQueryHandler(help_callback, pattern="^help$")]
