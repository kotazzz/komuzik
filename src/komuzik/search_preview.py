"""YouTube-like search preview collage (Pillow + Nerd Font)."""

from __future__ import annotations

import logging
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw

from .executors import run_render
from .i18n import t
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
NUM_COL_W = 52
THUMB_W = 320
THUMB_H = 180
TEXT_GAP = 28
ROW_H = 208
GAP = 16


def fmt_compact(n: float | None) -> str:
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
        num = f"{value / 1_000_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return t("search.compact.billion", value=num)
    if value >= 1_000_000:
        num = f"{value / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return t("search.compact.million", value=num)
    if value >= 1_000:
        num = f"{value / 1_000:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return t("search.compact.thousand", value=num)
    return str(value)


def fmt_duration(seconds: float | None) -> str:
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
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            logger.debug("Refusing non-http(s) thumb URL: %s", url)
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KomuzikBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception as e:
        logger.debug(f"Failed to fetch thumb {url}: {e}")
        return None


def _fit_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Scale+crop to exactly tw×th (cover)."""
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGB", (tw, th), (60, 60, 60))
    scale = max(tw / src_w, th / src_h)
    nw, nh = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    cropped = resized.crop((left, top, left + tw, top + th))
    if cropped.size != (tw, th):
        slot = Image.new("RGB", (tw, th), (40, 40, 40))
        slot.paste(cropped, (0, 0))
        return slot
    return cropped


def _thumb_slot(thumb_img: Image.Image | None) -> Image.Image:
    """Always return a THUMB_W×THUMB_H RGB image."""
    slot = Image.new("RGB", (THUMB_W, THUMB_H), (45, 45, 45))
    if thumb_img is None:
        return slot
    fitted = _fit_cover(thumb_img.convert("RGB"), THUMB_W, THUMB_H)
    slot.paste(fitted, (0, 0))
    return slot


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
        else:
            # Single word wider than the column — keep it and truncate later.
            current = word
        if len(lines) >= max_lines:
            # Fold the pending word into the last visible line so it is not dropped.
            if current:
                lines[-1] = f"{lines[-1]} {current}".strip()
                current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]
    # Truncation check against the original word list, not whitespace-collapsed text.
    joined = " ".join(lines)
    original = " ".join(words)
    if joined != original and lines:
        last = lines[-1]
        while last and _text_size(draw, last + "…", font)[0] > max_width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
    return lines


def render_search_preview(
    results: list[dict],
    query: str,
    *,
    start_index: int = 1,
) -> Path:
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

    draw.text((PAD, 24), f"{ICON_YT}  {t('search.preview_collage.header')}", font=_font(26, bold=True), fill=ACCENT)
    q = query.strip()
    if len(q) > 60:
        q = q[:57] + "…"
    draw.text((PAD + 160, 28), q, font=title_font, fill=TEXT)
    end_index = start_index + len(results) - 1 if results else start_index - 1
    draw.text(
        (PAD, 60),
        t(
            "search.preview_collage.results",
            start=start_index,
            end=max(end_index, start_index - 1),
            count=len(results),
        ),
        font=small_font,
        fill=MUTED,
    )

    thumb_x = PAD + NUM_COL_W
    text_x = thumb_x + THUMB_W + TEXT_GAP
    text_max_w = max(120, WIDTH - text_x - PAD)

    thumb_urls = [
        item.get("thumbnail") if isinstance(item.get("thumbnail"), str) else None
        for item in results
    ]
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(thumb_urls)))) as pool:
        raw_thumbs = list(
            pool.map(lambda u: _fetch_image(u) if u else None, thumb_urls)
        )

    for i, item in enumerate(results):
        y = header_h + i * ROW_H
        _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + ROW_H - GAP), 14, CARD)

        # index (left column, does not overlap thumb)
        num = str(start_index + i)
        nw, _ = _text_size(draw, num, num_font)
        draw.text(
            (PAD + (NUM_COL_W - nw) // 2, y + (ROW_H - GAP) // 2 - 12),
            num,
            font=num_font,
            fill=MUTED,
        )

        thumb_y = y + (ROW_H - GAP - THUMB_H) // 2
        thumb_img = _thumb_slot(raw_thumbs[i])
        img.paste(thumb_img, (thumb_x, thumb_y))

        # duration badge on thumb
        dur = fmt_duration(item.get("duration"))
        dw, dh = _text_size(draw, dur, badge_font)
        bx2 = thumb_x + THUMB_W - 8
        by2 = thumb_y + THUMB_H - 8
        bx1 = bx2 - dw - 14
        by1 = by2 - dh - 10
        _rounded_rect(draw, (bx1, by1, bx2, by2), 6, BADGE_BG)
        draw.text((bx1 + 7, by1 + 4), dur, font=badge_font, fill=TEXT)

        title = str(item.get("title") or t("common.untitled"))
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


async def render_search_preview_async(
    results: list[dict],
    query: str,
    *,
    start_index: int = 1,
) -> Path:
    """Run collage render off the event loop."""
    return await run_render(
        lambda: render_search_preview(results, query, start_index=start_index),
    )
