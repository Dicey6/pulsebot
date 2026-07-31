"""
PnL card generator — overlays trade data onto the Pulse Trading Bot template.
All coordinates are configurable constants at the top of this file.
Template canvas: ~1672×941 (the provided template image).
Content zone: left ~55% of image, avoiding logo bottom-right and shards right side.
"""
import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ─── Coordinate / style constants — adjust to match your template ──────────────

TEMPLATE_PATH = Path(__file__).parent.parent / "assets" / "pnl_template.png"

# Fonts — bundled DejaVu or system fallback
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in _FONT_PATHS:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── Field positions (x, y) and font sizes ─────────────────────────────────────

TICKER_POS = (80, 140)
TICKER_FONT_SIZE = 56
TICKER_COLOR = (255, 255, 255)

PNL_BOX_POS = (80, 210)        # top-left corner of PnL box
PNL_BOX_SIZE = (760, 110)      # width × height
PNL_BOX_FONT_SIZE = 64
PNL_BOX_TEXT_COLOR = (10, 10, 10)
PNL_BOX_POSITIVE_COLOR = (74, 222, 128)   # #4ADE80
PNL_BOX_NEGATIVE_COLOR = (248, 113, 113)  # #F87171

# Row: label left, value right
LABEL_X = 80
VALUE_X = 480
ROW_FONT_SIZE = 30
LABEL_COLOR = (180, 180, 200)
VALUE_COLOR_DEFAULT = (255, 255, 255)
VALUE_COLOR_POSITIVE = (74, 222, 128)
VALUE_COLOR_NEGATIVE = (248, 113, 113)

PNL_PCT_ROW_Y = 380
INVESTED_ROW_Y = 438
POSITION_ROW_Y = 496
HOLDING_ROW_Y = 554

HANDLE_POS = (80, 650)
HANDLE_FONT_SIZE = 34
HANDLE_DOT_COLOR = (138, 43, 226)   # purple accent
HANDLE_TEXT_COLOR = (200, 200, 220)

TIMESTAMP_POS = (80, 720)
TIMESTAMP_FONT_SIZE = 22
TIMESTAMP_COLOR = (120, 120, 140)

# ──────────────────────────────────────────────────────────────────────────────


def _format_pnl_usd(pnl_usd: float) -> str:
    sign = "+" if pnl_usd >= 0 else ""
    if abs(pnl_usd) >= 1_000:
        return f"{sign}${abs(pnl_usd)/1000:.2f}K" if pnl_usd >= 0 else f"-${abs(pnl_usd)/1000:.2f}K"
    return f"{sign}${pnl_usd:.2f}"


def generate_pnl_card(
    ticker: str,
    pnl_usd: float,
    pnl_pct: float,
    sol_invested: float,
    current_value_usd: float,
    holding_duration: str,
    telegram_handle: str | None = None,
) -> bytes:
    """
    Render a PnL card on the template and return PNG bytes.

    Args:
        ticker: e.g. "$BONK"
        pnl_usd: net PnL in USD (negative for loss)
        pnl_pct: net PnL percent
        sol_invested: total SOL put in
        current_value_usd: current USD value of position
        holding_duration: human-readable e.g. "2h 14m"
        telegram_handle: optional e.g. "@pulse_user"
    """
    if not TEMPLATE_PATH.exists():
        # Create a plain dark background if template is missing
        img = Image.new("RGB", (1672, 941), color=(8, 8, 20))
    else:
        img = Image.open(TEMPLATE_PATH).convert("RGB")

    draw = ImageDraw.Draw(img)

    font_ticker = _load_font(TICKER_FONT_SIZE)
    font_pnl = _load_font(PNL_BOX_FONT_SIZE)
    font_row = _load_font(ROW_FONT_SIZE)
    font_handle = _load_font(HANDLE_FONT_SIZE)
    font_ts = _load_font(TIMESTAMP_FONT_SIZE)

    is_positive = pnl_usd >= 0
    pnl_color = PNL_BOX_POSITIVE_COLOR if is_positive else PNL_BOX_NEGATIVE_COLOR
    value_color = VALUE_COLOR_POSITIVE if is_positive else VALUE_COLOR_NEGATIVE

    # ── Ticker ──────────────────────────────────────────────────────────────────
    ticker_text = f"${ticker.lstrip('$')}"
    draw.text(TICKER_POS, ticker_text, font=font_ticker, fill=TICKER_COLOR)

    # ── PnL box ──────────────────────────────────────────────────────────────────
    bx, by = PNL_BOX_POS
    bw, bh = PNL_BOX_SIZE
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill=pnl_color)
    pnl_text = _format_pnl_usd(pnl_usd)
    # Centre text in box
    bbox = draw.textbbox((0, 0), pnl_text, font=font_pnl)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = bx + (bw - tw) // 2
    ty = by + (bh - th) // 2
    draw.text((tx, ty), pnl_text, font=font_pnl, fill=PNL_BOX_TEXT_COLOR)

    # ── PnL % row ────────────────────────────────────────────────────────────────
    draw.text((LABEL_X, PNL_PCT_ROW_Y), "PnL %", font=font_row, fill=LABEL_COLOR)
    pnl_pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
    draw.text((VALUE_X, PNL_PCT_ROW_Y), pnl_pct_str, font=font_row, fill=value_color)

    # ── Invested row ─────────────────────────────────────────────────────────────
    draw.text((LABEL_X, INVESTED_ROW_Y), "Invested", font=font_row, fill=LABEL_COLOR)
    draw.text(
        (VALUE_X, INVESTED_ROW_Y),
        f"{sol_invested:.4f} SOL",
        font=font_row,
        fill=VALUE_COLOR_DEFAULT,
    )

    # ── Position (current value) row ─────────────────────────────────────────────
    draw.text((LABEL_X, POSITION_ROW_Y), "Position", font=font_row, fill=LABEL_COLOR)
    draw.text(
        (VALUE_X, POSITION_ROW_Y),
        f"${current_value_usd:,.2f}",
        font=font_row,
        fill=VALUE_COLOR_DEFAULT,
    )

    # ── Holding Time row ─────────────────────────────────────────────────────────
    draw.text((LABEL_X, HOLDING_ROW_Y), "Holding Time", font=font_row, fill=LABEL_COLOR)
    draw.text(
        (VALUE_X, HOLDING_ROW_Y),
        holding_duration,
        font=font_row,
        fill=VALUE_COLOR_DEFAULT,
    )

    # ── Handle ───────────────────────────────────────────────────────────────────
    if telegram_handle:
        hx, hy = HANDLE_POS
        # Small colored square as accent
        draw.rectangle([hx, hy + 4, hx + 18, hy + 22], fill=HANDLE_DOT_COLOR)
        draw.text((hx + 28, hy), telegram_handle, font=font_handle, fill=HANDLE_TEXT_COLOR)

    # ── Timestamp ────────────────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    draw.text(TIMESTAMP_POS, ts, font=font_ts, fill=TIMESTAMP_COLOR)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
