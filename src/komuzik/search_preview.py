"""YouTube-like search preview collage (Pillow + Nerd Font)."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .stats_infographic import _font, _rounded_rect, _text_size

logger = logging.getLogger(__name__)

# YouTube-ish dark UI
BG = (15, 15, 15)
CARD = (33, 33, 33)
TEXT = (241, 241, 241)
MUTED = (170, 170, 170)
ACCENT = (255, 0, 0)
BADGE_BG = (0, 0, 0)

ICON_EYE = "\uf06e"
ICON_LIKE = "\uf164"
ICON_USER = "\uf007"
ICON_YT = "\uf167"

WIDTH = 1080
PAD = 28
THUMB_W = 320
THUMB_H = 180
ROW_H = 200
GAP = 16


def fmt_compact(n: int | float | None) -> str:
    """Format counts like YouTube (RU short)."""
    if n is None:
        return "—"
    try:
        value = int(n)
    except (TypeError, ValueError):
        return "—"
    if value < 0:
        return "—"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " млрд"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " млн"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " тыс."
    return str(value)


def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "0:00"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "0:00"
    if total < 0:
        return "0:00"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fetch_image(url: str, timeout: float = 8.0) -> Image.Image | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KomuzikBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        img = Image.open(BytesIO(data)).convert("RGB")
        return img
    except Exception as e:
        logger.debug(f"Failed to fetch thumb {url}: {e}")
        return None


def _fit_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(tw / src_w, th / src_h)
    nw, nh = int(src_w * scale), int(src_h * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int, max_lines: int
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if _text_size(draw, trial, font)[0] <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]
    joined = " ".join(lines)
    if joined != text and lines:
        last = lines[-1]
        while last and _text_size(draw, last + "…", font)[0] > max_width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
    return lines


def render_search_preview(results: list[dict], query: str) -> Path:
    """Render a YouTube-like vertical list of search hits into a PNG file."""
    n = max(len(results), 1)
    header_h = 90
    height = header_h + PAD + n * ROW_H + PAD
    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    title_font = _font(28, bold=True)
    meta_font = _font(20)
    small_font = _font(18)
    icon_font = _font(20)
    badge_font = _font(16, bold=True)
    num_font = _font(22, bold=True)

    draw.text((PAD, 24), f"{ICON_YT}  Поиск", font=_font(26, bold=True), fill=ACCENT)
    q = query.strip()
    if len(q) > 60:
        q = q[:57] + "…"
    draw.text((PAD + 160, 28), q, font=title_font, fill=TEXT)
    draw.text((PAD, 60), f"{len(results)} результатов", font=small_font, fill=MUTED)

    text_x = PAD + THUMB_W + 24
    text_max_w = WIDTH - text_x - PAD

    for i, item in enumerate(results):
        y = header_h + i * ROW_H
        _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + ROW_H - GAP), 14, CARD)

        # index
        draw.text((PAD + 10, y + 12), f"{i + 1}", font=num_font, fill=MUTED)

        thumb_x = PAD + 36
        thumb_y = y + (ROW_H - GAP - THUMB_H) // 2
        thumb_url = item.get("thumbnail")
        thumb_img = None
        if isinstance(thumb_url, str) and thumb_url:
            thumb_img = _fetch_image(thumb_url)
        if thumb_img is None:
            placeholder = Image.new("RGB", (THUMB_W, THUMB_H), (60, 60, 60))
            thumb_img = placeholder
        else:
            thumb_img = _fit_cover(thumb_img, THUMB_W, THUMB_H)
        img.paste(thumb_img, (thumb_x, thumb_y))

        # duration badge
        dur = fmt_duration(item.get("duration"))
        dw, dh = _text_size(draw, dur, badge_font)
        bx2 = thumb_x + THUMB_W - 10
        by2 = thumb_y + THUMB_H - 10
        bx1 = bx2 - dw - 14
        by1 = by2 - dh - 10
        _rounded_rect(draw, (bx1, by1, bx2, by2), 6, BADGE_BG)
        draw.text((bx1 + 7, by1 + 4), dur, font=badge_font, fill=TEXT)

        title = str(item.get("title") or "Без названия")
        lines = _wrap_text(draw, title, title_font, text_max_w, max_lines=2)
        ty = y + 22
        for line in lines:
            draw.text((text_x, ty), line, font=title_font, fill=TEXT)
            ty += 32

        channel = str(item.get("channel") or "Unknown")
        if len(channel) > 40:
            channel = channel[:37] + "…"
        draw.text((text_x, ty + 6), f"{ICON_USER}  {channel}", font=icon_font, fill=MUTED)

        views = fmt_compact(item.get("view_count"))
        likes = fmt_compact(item.get("like_count"))
        stats_y = ty + 40
        draw.text((text_x, stats_y), f"{ICON_EYE}  {views}", font=meta_font, fill=MUTED)
        vw, _ = _text_size(draw, f"{ICON_EYE}  {views}", meta_font)
        draw.text((text_x + vw + 28, stats_y), f"{ICON_LIKE}  {likes}", font=meta_font, fill=MUTED)

    out = Path(tempfile.mkdtemp(prefix="komuzik_search_")) / "preview.png"
    img.save(out, format="PNG", optimize=True)
    return out


async def render_search_preview_async(results: list[dict], query: str) -> Path:
    """Run collage render off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, render_search_preview, results, query)
