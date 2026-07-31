"""
Pulse Trading Bot — entry point.
Runs in long-polling mode (suitable for Render Background Worker).
"""
import logging
import sys

from telegram.ext import Application, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN
from handlers.buy import get_buy_handlers, handle_custom_buy_amount
from handlers.help import get_help_handlers
from handlers.menu import get_menu_handlers
from handlers.positions import get_positions_handlers, handle_custom_sell_amount
from handlers.settings import get_settings_handlers, handle_settings_input
from handlers.start import get_start_handler
from handlers.wallet import get_wallet_handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Onboarding (handles /start + invite code flow) ──────────────────────────
    app.add_handler(get_start_handler())

    # ── Menu refresh ────────────────────────────────────────────────────────────
    for h in get_menu_handlers():
        app.add_handler(h)

    # ── Wallet ──────────────────────────────────────────────────────────────────
    for h in get_wallet_handlers():
        app.add_handler(h)

    # ── Positions (list + manage + sell + PnL card) ──────────────────────────────
    for h in get_positions_handlers():
        app.add_handler(h)

    # ── Settings ────────────────────────────────────────────────────────────────
    for h in get_settings_handlers():
        app.add_handler(h)

    # ── Help ────────────────────────────────────────────────────────────────────
    for h in get_help_handlers():
        app.add_handler(h)

    # ── Buy / text input (catch-all for token pastes, custom amounts, etc.) ─────
    # Priority matters: specific handlers (custom sell, custom buy, settings) run
    # before the generic buy handler that parses arbitrary text as a token paste.
    for h in get_buy_handlers():
        app.add_handler(h)

    return app


def main() -> None:
    logger.info("Starting Pulse Trading Bot…")
    app = build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
