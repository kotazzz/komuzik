"""Render colorful Komuzik stats infographics with Pillow + file cache."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
CACHE_DIR = Path("data/stats_cache")
WIDTH = 1080
PADDING = 48

# Distinct palette (not purple-on-white AI default)
BG = (18, 22, 28)
CARD = (28, 34, 44)
CARD_BORDER = (45, 54, 68)
TEXT = (236, 240, 245)
MUTED = (148, 163, 184)
ACCENT = (45, 212, 191)  # teal
ACCENT_2 = (251, 146, 60)  # amber
ACCENT_3 = (248, 113, 113)  # coral
ACCENT_4 = (96, 165, 250)  # blue
ACCENT_5 = (232, 121, 249)  # soft magenta for variety in bars
SUCCESS = (52, 211, 153)
FAIL = (248, 113, 113)

PLATFORM_COLORS = {
    "youtube": ACCENT_4,
    "audio": ACCENT_2,
    "tiktok": ACCENT,
    "pinterest": ACCENT_5,
}

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _font(size: int, bold: bool = False) -> Any:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else None,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=2)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: Any) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0]), int(box[3] - box[1])


def _draw_kpi(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    value: str,
    color: tuple[int, int, int],
) -> None:
    _rounded_rect(draw, (x, y, x + w, y + h), 18, CARD, CARD_BORDER)
    draw.rectangle((x, y, x + 8, y + h), fill=color)
    font_label = _font(22)
    font_value = _font(36, bold=True)
    draw.text((x + 24, y + 18), label, font=font_label, fill=MUTED)
    draw.text((x + 24, y + 52), value, font=font_value, fill=TEXT)


def _draw_hbar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    label: str,
    value: int,
    max_value: int,
    color: tuple[int, int, int],
) -> int:
    font = _font(24)
    draw.text((x, y), f"{label}", font=font, fill=TEXT)
    count_text = str(value)
    tw, _ = _text_size(draw, count_text, font)
    draw.text((x + w - tw, y), count_text, font=font, fill=MUTED)
    bar_y = y + 34
    bar_h = 18
    _rounded_rect(draw, (x, bar_y, x + w, bar_y + bar_h), 9, (38, 45, 58))
    fill_w = int(w * (value / max_value)) if max_value > 0 else 0
    fill_w = max(fill_w, 8 if value > 0 else 0)
    if fill_w:
        _rounded_rect(draw, (x, bar_y, x + fill_w, bar_y + bar_h), 9, color)
    return bar_y + bar_h + 28


def _draw_donut(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    parts: list[tuple[str, int, tuple[int, int, int]]],
) -> None:
    total = sum(v for _, v, _ in parts) or 1
    start = -90.0
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    for _, value, color in parts:
        extent = 360.0 * value / total
        if value > 0:
            draw.pieslice(bbox, start=start, end=start + extent, fill=color)
        start += extent
    inner = radius - 28
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=CARD)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def render_stats_infographic(stats: dict[str, Any], period: str) -> Path:
    """Render stats dict into a PNG file and return its path."""
    period_names = {"day": "за день", "month": "за месяц", "all": "за всё время"}
    period_label = period_names.get(period, period)

    # Tall canvas; crop to content at the end.
    height = 2400
    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    y = PADDING
    title_font = _font(48, bold=True)
    subtitle_font = _font(28)
    section_font = _font(30, bold=True)

    draw.text((PADDING, y), "KOMUZIK", font=title_font, fill=ACCENT)
    y += 58
    draw.text((PADDING, y), f"Статистика {period_label}", font=subtitle_font, fill=MUTED)
    y += 56

    # KPI row
    total = int(stats.get("total_downloads") or 0)
    ok = int(stats.get("successful_downloads") or 0)
    fail = int(stats.get("failed_downloads") or 0)
    success_pct = round(100 * ok / total) if total else 0

    gap = 20
    card_w = (WIDTH - 2 * PADDING - 3 * gap) // 4
    card_h = 110
    kpis = [
        ("Пользователи", _fmt_int(int(stats.get("total_users") or 0)), ACCENT),
        ("Поиски", _fmt_int(int(stats.get("total_searches") or 0)), ACCENT_4),
        ("Загрузки", _fmt_int(total), ACCENT_2),
        ("Успех", f"{success_pct}%", SUCCESS),
    ]
    for i, (label, value, color) in enumerate(kpis):
        x = PADDING + i * (card_w + gap)
        _draw_kpi(draw, x, y, card_w, card_h, label, value, color)
    y += card_h + 36

    # Success / fail bar
    _rounded_rect(draw, (PADDING, y, WIDTH - PADDING, y + 120), 20, CARD, CARD_BORDER)
    draw.text((PADDING + 28, y + 18), "Результат загрузок", font=section_font, fill=TEXT)
    bar_x, bar_y, bar_w, bar_h = PADDING + 28, y + 62, WIDTH - 2 * PADDING - 56, 28
    _rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), 14, (38, 45, 58))
    ok_w = int(bar_w * ok / total) if total else 0
    if ok_w:
        _rounded_rect(draw, (bar_x, bar_y, bar_x + ok_w, bar_y + bar_h), 14, SUCCESS)
    if total and fail:
        fail_w = bar_w - ok_w
        if fail_w > 0:
            _rounded_rect(draw, (bar_x + ok_w, bar_y, bar_x + bar_w, bar_y + bar_h), 14, FAIL)
    small = _font(22)
    draw.text(
        (PADDING + 28, y + 96),
        f"✅ {_fmt_int(ok)}   ❌ {_fmt_int(fail)}",
        font=small,
        fill=MUTED,
    )
    y += 148

    # Platforms
    _rounded_rect(draw, (PADDING, y, WIDTH - PADDING, y + 320), 20, CARD, CARD_BORDER)
    draw.text((PADDING + 28, y + 20), "Платформы", font=section_font, fill=TEXT)
    plat_y = y + 70
    platforms = [
        ("YouTube видео", int(stats.get("total_videos") or 0), PLATFORM_COLORS["youtube"]),
        ("Аудио", int(stats.get("total_audio") or 0), PLATFORM_COLORS["audio"]),
        ("TikTok", int(stats.get("total_tiktoks") or 0), PLATFORM_COLORS["tiktok"]),
        ("Pinterest", int(stats.get("total_pinterest") or 0), PLATFORM_COLORS["pinterest"]),
    ]
    max_plat = max((v for _, v, _ in platforms), default=1) or 1
    inner_w = WIDTH - 2 * PADDING - 56
    for label, value, color in platforms:
        plat_y = _draw_hbar(draw, PADDING + 28, plat_y, inner_w, label, value, max_plat, color)
    y += 348

    # Source + content donuts
    by_source = stats.get("by_source") or {}
    by_content = stats.get("by_content") or {}
    dm = int(by_source.get("dm") or 0)
    inline = int(by_source.get("inline") or 0)
    video = int(by_content.get("video") or 0)
    audio = int(by_content.get("audio") or 0)

    _rounded_rect(draw, (PADDING, y, WIDTH - PADDING, y + 360), 20, CARD, CARD_BORDER)
    draw.text((PADDING + 28, y + 20), "Источник и тип", font=section_font, fill=TEXT)

    left_cx, right_cx = PADDING + 250, WIDTH - PADDING - 250
    cy = y + 170
    _draw_donut(
        draw,
        left_cx,
        cy,
        110,
        [("ЛС", dm, ACCENT_4), ("Inline", inline, ACCENT)],
    )
    _draw_donut(
        draw,
        right_cx,
        cy,
        110,
        [("Видео", video, ACCENT_2), ("Аудио", audio, ACCENT_5)],
    )

    legend = _font(24)
    src_total = max(dm + inline, 1)
    cont_total = max(video + audio, 1)
    draw.text(
        (left_cx - 120, y + 300),
        f"ЛС {round(100 * dm / src_total)}% · Inline {round(100 * inline / src_total)}%",
        font=legend,
        fill=MUTED,
    )
    draw.text(
        (right_cx - 130, y + 300),
        f"Видео {round(100 * video / cont_total)}% · Аудио {round(100 * audio / cont_total)}%",
        font=legend,
        fill=MUTED,
    )
    y += 388

    # Popular formats
    video_formats = list(stats.get("popular_video_formats") or [])[:5]
    audio_formats = list(stats.get("popular_audio_formats") or [])[:5]
    formats_h = 100 + max(len(video_formats), 1) * 80 + 50 + max(len(audio_formats), 1) * 80 + 40
    _rounded_rect(draw, (PADDING, y, WIDTH - PADDING, y + formats_h), 20, CARD, CARD_BORDER)
    draw.text((PADDING + 28, y + 20), "Популярные форматы", font=section_font, fill=TEXT)
    fy = y + 70
    draw.text((PADDING + 28, fy), "Видео", font=_font(26, bold=True), fill=ACCENT_4)
    fy += 40
    vmax = max((c for _, c in video_formats), default=1) or 1
    if not video_formats:
        draw.text((PADDING + 28, fy), "нет данных", font=_font(24), fill=MUTED)
        fy += 40
    else:
        for name, count in video_formats:
            fy = _draw_hbar(draw, PADDING + 28, fy, inner_w, str(name), int(count), vmax, ACCENT_4)
    fy += 8
    draw.text((PADDING + 28, fy), "Аудио", font=_font(26, bold=True), fill=ACCENT_2)
    fy += 40
    amax = max((c for _, c in audio_formats), default=1) or 1
    if not audio_formats:
        draw.text((PADDING + 28, fy), "нет данных", font=_font(24), fill=MUTED)
        fy += 40
    else:
        for name, count in audio_formats:
            fy = _draw_hbar(draw, PADDING + 28, fy, inner_w, str(name), int(count), amax, ACCENT_2)
    y = fy + 36

    # Footer
    draw.text(
        (PADDING, y),
        "komuzik · обновляется кэшем раз в 5 мин",
        font=_font(20),
        fill=(100, 116, 139),
    )
    y += 50

    cropped = img.crop((0, 0, WIDTH, min(y + PADDING, height)))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"stats_{period}_{int(time.time())}.png"
    cropped.save(out, format="PNG", optimize=True)
    return out


async def get_stats_image(stats: dict[str, Any], period: str) -> Path:
    """Return cached or freshly rendered stats image for period."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = f"stats_{period}"
    cache_path = CACHE_DIR / f"{cache_key}.png"
    meta_path = CACHE_DIR / f"{cache_key}.ts"

    async with _lock_for(cache_key):
        if cache_path.exists() and meta_path.exists():
            try:
                age = time.time() - float(meta_path.read_text().strip())
                if age < CACHE_TTL_SECONDS:
                    return cache_path
            except (ValueError, OSError):
                pass

        loop = asyncio.get_running_loop()
        rendered = await loop.run_in_executor(None, render_stats_infographic, stats, period)
        # Stable cache name
        final = CACHE_DIR / f"{cache_key}.png"
        try:
            if final.exists():
                final.unlink()
            rendered.replace(final)
        except OSError:
            final = rendered
        meta_path.write_text(str(time.time()))
        # cleanup old timestamped leftovers
        for stale in CACHE_DIR.glob(f"stats_{period}_*.png"):
            if stale.name != final.name:
                try:
                    stale.unlink()
                except OSError:
                    pass
        return final
