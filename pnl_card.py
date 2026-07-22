"""Aesthetic PnL card generator — dark navy gradient, Pulse Bot branding."""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import ASSETS_DIR, FONTS_DIR

W, H = 1200, 680

# ── Palette ───────────────────────────────────────────────────────────────────
BG_TOP     = (8,  10, 36)
BG_BOT     = (2,   2, 10)
PURPLE     = (124, 58, 237)
PURPLE_LO  = (70,  30, 150)
WHITE      = (255, 255, 255)
GREY       = (150, 150, 175)
DIM        = (55,  55,  75)
GREEN      = (0,   212, 160)
RED        = (255,  60,  60)
GOLD       = (255, 195,  60)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _gradient(w: int, h: int, top: tuple, bot: tuple) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _glow_overlay(w: int, h: int, colour: tuple, radius: int, cx: int, cy: int, max_alpha: int = 22) -> Image.Image:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    for r in range(radius, 0, -6):
        a = int(max_alpha * (1 - r / radius))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*colour, a))
    return layer.filter(ImageFilter.GaussianBlur(32))


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates = [
            FONTS_DIR / "bold.ttf",
            FONTS_DIR / "Inter-Bold.ttf",
            FONTS_DIR / "Roboto-Bold.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ]
    else:
        candidates = [
            FONTS_DIR / "regular.ttf",
            FONTS_DIR / "Inter-Regular.ttf",
            FONTS_DIR / "Roboto-Regular.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
    for p in candidates:
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fmt_usd(v: Optional[float]) -> str:
    if v is None: return "—"
    if abs(v) >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if abs(v) >= 1_000_000:     return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:         return f"${v/1_000:.1f}K"
    if abs(v) >= 1:             return f"${v:.2f}"
    if abs(v) >= 0.00001:       return f"${v:.6f}"
    return f"${v:.10f}"


def _fmt_sol(v: Optional[float]) -> str:
    if v is None: return "—"
    return f"{v:.4f} SOL"


def _short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}" if addr and len(addr) > 10 else addr or "—"


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pnl_card(
    *,
    token_name: str,
    token_symbol: str,
    contract_address: str,
    entry_price: float,
    current_price: float,
    entry_mcap: Optional[float] = None,
    current_mcap: Optional[float] = None,
    invested_sol: float,
    sol_price_usd: float,
    # Sell-card fields (only for realized cards)
    sold_sol: Optional[float] = None,
    sold_fraction: Optional[float] = None,
    remaining_sol_value: Optional[float] = None,
    is_unrealized: bool = False,
) -> bytes:
    """Return PNG bytes of the aesthetic PnL card."""

    # ── Background + glow ────────────────────────────────────────────────────
    img  = _gradient(W, H, BG_TOP, BG_BOT)
    glow = _glow_overlay(W, H, PURPLE, 520, W // 2, -60, max_alpha=28)
    img  = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_huge  = _font(116, bold=True)
    f_h2    = _font(46,  bold=True)
    f_h3    = _font(30,  bold=True)
    f_body  = _font(24)
    f_small = _font(19)

    # ── Logo ──────────────────────────────────────────────────────────────────
    PAD = 48
    logo_sz = 58
    logo_path = ASSETS_DIR / "pulse_logo.png"
    try:
        logo = Image.open(logo_path).convert("RGBA").resize((logo_sz, logo_sz), Image.LANCZOS)
        img.paste(logo, (PAD, 32), logo)
    except Exception:
        pass

    # Brand name next to logo
    draw.text((PAD + logo_sz + 14, 42), "PULSE BOT", font=f_h3, fill=PURPLE)

    # Timestamp top-right
    ts = time.strftime("%d %b %Y  %H:%M UTC", time.gmtime())
    draw.text((W - PAD, 46), ts, font=f_small, fill=GREY, anchor="ra")

    # ── Top divider ───────────────────────────────────────────────────────────
    y0 = 108
    draw.rectangle([PAD, y0, W - PAD, y0 + 1], fill=(*PURPLE, 70))

    # ── Token name + symbol ───────────────────────────────────────────────────
    y1 = y0 + 18
    name_w = draw.textlength(token_name, font=f_h2)
    draw.text((PAD, y1), token_name, font=f_h2, fill=WHITE)
    draw.text((PAD + name_w + 16, y1 + 8), f"${token_symbol.upper()}", font=f_h3, fill=PURPLE)
    draw.text((PAD, y1 + 52), _short(contract_address), font=f_small, fill=DIM)

    # ── PnL % (massive) ───────────────────────────────────────────────────────
    pnl_pct = ((current_price / entry_price) - 1) * 100 if entry_price and entry_price > 0 else 0.0
    pnl_col  = GREEN if pnl_pct >= 0 else RED
    sign     = "+" if pnl_pct >= 0 else ""
    pnl_txt  = f"{sign}{pnl_pct:.1f}%"

    pnl_w  = draw.textlength(pnl_txt, font=f_huge)
    pnl_x  = (W - pnl_w) / 2
    y_pnl  = 200

    # Glow behind the number
    glow2 = _glow_overlay(W, H, pnl_col, 300, W // 2, y_pnl + 55, max_alpha=18)
    img   = Image.alpha_composite(img.convert("RGBA"), glow2).convert("RGB")
    draw  = ImageDraw.Draw(img)

    draw.text((pnl_x, y_pnl), pnl_txt, font=f_huge, fill=pnl_col)

    # ── Mid divider ───────────────────────────────────────────────────────────
    y_mid = 375
    draw.rectangle([PAD, y_mid, W - PAD, y_mid + 1], fill=(*PURPLE, 55))

    # ── Stats grid (2 columns) ────────────────────────────────────────────────
    ys   = y_mid + 22
    lh   = 48          # row height
    col1 = PAD
    col2 = W // 2 + 12

    def label(x, y, txt):
        draw.text((x, y), txt, font=f_small, fill=GREY)

    def value(x, y, txt, colour=WHITE):
        draw.text((x, y + 19), txt, font=f_body, fill=colour)

    def stat(col, row, lbl, val, colour=WHITE):
        x = col1 if col == 0 else col2
        y = ys + row * lh
        label(x, y, lbl)
        value(x, y, val, colour)

    stat(0, 0, "ENTRY MCAP",    _fmt_usd(entry_mcap))
    stat(1, 0, "CURRENT MCAP",  _fmt_usd(current_mcap))
    stat(0, 1, "ENTRY PRICE",   _fmt_usd(entry_price))
    stat(1, 1, "CURRENT PRICE", _fmt_usd(current_price))

    invested_usd = invested_sol * sol_price_usd
    stat(0, 2, "INVESTED", f"{_fmt_sol(invested_sol)}  ·  {_fmt_usd(invested_usd)}")

    if is_unrealized:
        ratio     = (current_price / entry_price) if entry_price else 1.0
        cur_sol   = invested_sol * ratio
        cur_usd   = cur_sol * sol_price_usd
        dp_sol    = cur_sol - invested_sol
        dp_usd    = dp_sol * sol_price_usd
        s2        = "+" if dp_sol >= 0 else ""
        stat(1, 2, "CURRENT VALUE", f"{_fmt_sol(cur_sol)}  ·  {_fmt_usd(cur_usd)}")
        stat(0, 3, "UNREALIZED P&L",
             f"{s2}{_fmt_sol(dp_sol)}  ·  {s2}{_fmt_usd(dp_usd)}",
             colour=pnl_col)
    else:
        if sold_sol is not None:
            sold_usd = sold_sol * sol_price_usd
            stat(1, 2, "RECEIVED", f"{_fmt_sol(sold_sol)}  ·  {_fmt_usd(sold_usd)}")
        frac = sold_fraction or 1.0
        dp_sol = invested_sol * (pnl_pct / 100)
        dp_usd = dp_sol * sol_price_usd
        s2     = "+" if dp_sol >= 0 else ""
        stat(0, 3, "REALIZED P&L",
             f"{s2}{_fmt_sol(dp_sol)}  ·  {s2}{_fmt_usd(dp_usd)}",
             colour=pnl_col)
        if remaining_sol_value and remaining_sol_value > 0:
            rem_usd = remaining_sol_value * sol_price_usd
            stat(1, 3, "STILL HOLDING",
                 f"{_fmt_sol(remaining_sol_value)}  ·  {_fmt_usd(rem_usd)}",
                 colour=GOLD)

    # ── Footer ────────────────────────────────────────────────────────────────
    yf = H - 36
    draw.rectangle([PAD, yf - 1, W - PAD, yf], fill=(*PURPLE, 35))
    draw.text((PAD, yf + 6), "pulsebot.io", font=f_small, fill=(*PURPLE, 170))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
