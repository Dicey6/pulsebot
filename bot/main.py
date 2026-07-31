"""
Pulse Trading Bot — entry point.
Runs long-polling in a background thread alongside a lightweight HTTP server
so Render Web Service health checks and Uptime Robot pings succeed.
"""
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN
from handlers.buy import get_buy_handlers
from handlers.help import get_help_handlers
from handlers.menu import get_menu_handlers
from handlers.positions import get_positions_handlers
from handlers.settings import get_settings_handlers
from handlers.start import get_start_handler
from handlers.wallet import get_wallet_handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Minimal HTTP health server for Render / Uptime Robot ──────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # Silence access logs


def _start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info("Health server listening on port %d", port)
    server.serve_forever()


# ──────────────────────────────────────────────────────────────────────────────


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
    for h in get_buy_handlers():
        app.add_handler(h)

    return app


def main() -> None:
    # Start health server in a daemon thread — dies when main thread exits
    t = threading.Thread(target=_start_health_server, daemon=True)
    t.start()

    logger.info("Starting Pulse Trading Bot (polling)…")
    app = build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
