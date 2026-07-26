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
CACHE_VERSION = "v3"
CACHE_DIR = Path("data/stats_cache")

# Landscape canvas
WIDTH = 1600
HEIGHT = 980
PADDING = 40
GAP = 20
COL_GAP = 28

BG = (18, 22, 28)
CARD = (28, 34, 44)
CARD_BORDER = (45, 54, 68)
TEXT = (236, 240, 245)
MUTED = (148, 163, 184)
TEAL = (45, 212, 191)
AMBER = (251, 146, 60)
CORAL = (248, 113, 113)
BLUE = (96, 165, 250)
PINK = (232, 121, 249)
GREEN = (52, 211, 153)
TRACK = (38, 45, 58)

# Nerd Font / Font Awesome codepoints (work in JetBrainsMono Nerd Font)
ICON_USERS = "\uf0c0"
ICON_SEARCH = "\uf002"
ICON_DOWNLOAD = "\uf019"
ICON_CHECK = "\uf00c"
ICON_TIMES = "\uf00d"
ICON_YOUTUBE = "\uf167"
ICON_MUSIC = "\uf001"
ICON_BOLT = "\uf0e7"
ICON_PIN = "\uf08d"
ICON_TWITTER = "\uf099"
ICON_COMMENT = "\uf075"
ICON_FILM = "\uf008"
ICON_HEADPHONES = "\uf025"
ICON_CHART = "\uf080"
ICON_GROUP = "\uf86d"

FORMAT_COLORS = [BLUE, TEAL, AMBER, PINK, CORAL, (129, 140, 248), (251, 113, 133)]

_locks: dict[str, asyncio.Lock] = {}
_font_cache: dict[tuple[int, bool], Any] = {}


def _lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _font(size: int, bold: bool = False) -> Any:
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    root = Path(__file__).resolve().parents[2]
    candidates = [
        "/usr/local/share/fonts/nerd/JetBrainsMonoNerdFont-Bold.ttf" if bold else None,
        "/usr/local/share/fonts/nerd/JetBrainsMonoNerdFont-Regular.ttf",
        "/usr/share/fonts/truetype/nerd/JetBrainsMonoNerdFont-Bold.ttf" if bold else None,
        "/usr/share/fonts/truetype/nerd/JetBrainsMonoNerdFont-Regular.ttf",
        str(root / ".fonts/JetBrainsMonoNerdFont-Bold.ttf") if bold else None,
        str(root / ".fonts/JetBrainsMonoNerdFont-Regular.ttf"),
        str(Path.home() / "Library/Fonts/JetBrainsMonoNerdFont-Bold.ttf") if bold else None,
        str(Path.home() / "Library/Fonts/JetBrainsMonoNerdFont-Regular.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else None,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    font: Any = ImageFont.load_default()
    for path in candidates:
        if not path:
            continue
        try:
            font = ImageFont.truetype(path, size=size)
            break
        except OSError:
            continue
    _font_cache[key] = font
    return font


def _tint(color: tuple[int, int, int], strength: float = 0.22) -> tuple[int, int, int]:
    """Dark tinted background from accent color."""
    return tuple(int(c * strength + b * (1 - strength)) for c, b in zip(color, BG, strict=True))


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=1)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: Any) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0]), int(box[3] - box[1])


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _draw_kpi_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    icon: str,
    label: str,
    value: str,
    color: tuple[int, int, int],
) -> None:
    _rounded_rect(draw, (x, y, x + w, y + h), 18, _tint(color, 0.28), _tint(color, 0.45))
    icon_font = _font(28)
    label_font = _font(20)
    value_font = _font(34, bold=True)
    draw.text((x + 22, y + 18), icon, font=icon_font, fill=color)
    draw.text((x + 58, y + 22), label, font=label_font, fill=MUTED)
    draw.text((x + 22, y + 58), value, font=value_font, fill=TEXT)


def _draw_segmented_bar(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    parts: list[tuple[str, int, tuple[int, int, int]]],
) -> None:
    """Thick rounded progress bar with colored segments (like success/fail)."""
    _rounded_rect(draw, (x, y, x + w, y + h), h // 2, TRACK)
    total = sum(v for _, v, _ in parts) or 1
    if total <= 0 or not any(v > 0 for _, v, _ in parts):
        return

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    cursor = 0
    positive = [(name, value, color) for name, value, color in parts if value > 0]
    for i, (_, value, color) in enumerate(positive):
        seg_w = int(round(w * value / total))
        if i == len(positive) - 1:
            seg_w = w - cursor
        seg_w = max(seg_w, 1)
        layer_draw.rectangle((cursor, 0, cursor + seg_w, h), fill=(*color, 255))
        cursor += seg_w

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=255)
    layer.putalpha(mask)
    img.paste(layer, (x, y), layer)


def _draw_hbar_compact(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    icon: str,
    label: str,
    value: int,
    max_value: int,
    color: tuple[int, int, int],
) -> int:
    font = _font(22)
    icon_font = _font(20)
    draw.text((x, y + 2), icon, font=icon_font, fill=color)
    draw.text((x + 28, y), label, font=font, fill=TEXT)
    count = _fmt_int(value)
    tw, _ = _text_size(draw, count, font)
    draw.text((x + w - tw, y), count, font=font, fill=MUTED)
    bar_y = y + 30
    bar_h = 16
    _rounded_rect(draw, (x, bar_y, x + w, bar_y + bar_h), 8, TRACK)
    fill_w = int(w * (value / max_value)) if max_value > 0 else 0
    fill_w = max(fill_w, 6 if value > 0 else 0)
    if fill_w:
        _rounded_rect(draw, (x, bar_y, x + fill_w, bar_y + bar_h), 8, color)
    return bar_y + bar_h + 18


def _draw_donut(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    parts: list[tuple[str, int, tuple[int, int, int]]],
    hole_fill: tuple[int, int, int],
) -> None:
    total = sum(v for _, v, _ in parts) or 1
    start = -90.0
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    for _, value, color in parts:
        extent = 360.0 * value / total
        if value > 0:
            draw.pieslice(bbox, start=start, end=start + max(extent, 0.5), fill=color)
        start += extent
    inner = radius - 26
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=hole_fill)


def render_stats_infographic(stats: dict[str, Any], period: str) -> Path:
    """Render landscape 2-column stats PNG."""
    period_names = {"day": "за день", "month": "за месяц", "all": "за всё время"}
    period_label = period_names.get(period, period)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    total = int(stats.get("total_downloads") or 0)
    ok = int(stats.get("successful_downloads") or 0)
    fail = int(stats.get("failed_downloads") or 0)
    success_pct = round(100 * ok / total) if total else 0

    by_source = stats.get("by_source") or {}
    by_content = stats.get("by_content") or {}
    dm = int(by_source.get("dm") or 0)
    inline = int(by_source.get("inline") or 0)
    group = int(by_source.get("group") or 0)
    video_n = int(by_content.get("video") or 0)
    audio_n = int(by_content.get("audio") or 0)
    src_total = max(dm + inline + group, 1)
    cont_total = max(video_n + audio_n, 1)

    video_formats = list(stats.get("popular_video_formats") or [])[:5]
    audio_formats = list(stats.get("popular_audio_formats") or [])[:5]

    # Header
    y = PADDING
    draw.text((PADDING, y), f"{ICON_CHART}  KOMUZIK", font=_font(42, bold=True), fill=TEAL)
    draw.text(
        (PADDING + 320, y + 12),
        f"Статистика {period_label}",
        font=_font(26),
        fill=MUTED,
    )
    y += 64

    # KPI row (5 cards)
    card_w = (WIDTH - 2 * PADDING - 4 * GAP) // 5
    card_h = 100
    kpis = [
        (ICON_USERS, "Пользователи", _fmt_int(int(stats.get("total_users") or 0)), TEAL),
        (ICON_GROUP, "Группы", _fmt_int(int(stats.get("total_groups") or 0)), PINK),
        (ICON_SEARCH, "Поиски", _fmt_int(int(stats.get("total_searches") or 0)), BLUE),
        (ICON_DOWNLOAD, "Загрузки", _fmt_int(total), AMBER),
        (ICON_CHECK, "Успех", f"{success_pct}%", GREEN),
    ]
    for i, (icon, label, value, color) in enumerate(kpis):
        x = PADDING + i * (card_w + GAP)
        _draw_kpi_card(draw, x, y, card_w, card_h, icon, label, value, color)
    y += card_h + 24

    # Two columns
    col_w = (WIDTH - 2 * PADDING - COL_GAP) // 2
    left_x = PADDING
    right_x = PADDING + col_w + COL_GAP
    col_top = y

    # --- LEFT: result + platforms ---
    result_h = 190
    _rounded_rect(
        draw, (left_x, col_top, left_x + col_w, col_top + result_h), 20, CARD, CARD_BORDER
    )
    draw.text(
        (left_x + 24, col_top + 20),
        f"{ICON_DOWNLOAD}  Результат загрузок",
        font=_font(26, bold=True),
        fill=TEXT,
    )
    bar_x = left_x + 24
    bar_y = col_top + 68
    bar_w = col_w - 48
    bar_h = 40
    parts_result = [
        ("ok", ok, GREEN),
        ("fail", fail, CORAL),
    ]
    _draw_segmented_bar(img, draw, bar_x, bar_y, bar_w, bar_h, parts_result)
    legend_font = _font(22)
    draw.text(
        (bar_x, bar_y + bar_h + 22),
        f"{ICON_CHECK}  {_fmt_int(ok)}",
        font=legend_font,
        fill=GREEN,
    )
    draw.text(
        (bar_x + 200, bar_y + bar_h + 22),
        f"{ICON_TIMES}  {_fmt_int(fail)}",
        font=legend_font,
        fill=CORAL,
    )

    plat_top = col_top + result_h + 20
    plat_h = HEIGHT - PADDING - plat_top
    _rounded_rect(
        draw, (left_x, plat_top, left_x + col_w, plat_top + plat_h), 20, CARD, CARD_BORDER
    )
    draw.text(
        (left_x + 24, plat_top + 18),
        f"{ICON_BOLT}  Платформы",
        font=_font(26, bold=True),
        fill=TEXT,
    )
    platforms = [
        (ICON_YOUTUBE, "YouTube видео", int(stats.get("total_videos") or 0), BLUE),
        (ICON_MUSIC, "Аудио", int(stats.get("total_audio") or 0), AMBER),
        (ICON_BOLT, "TikTok", int(stats.get("total_tiktoks") or 0), TEAL),
        (ICON_TWITTER, "Twitter/X", int(stats.get("total_twitter") or 0), BLUE),
        (ICON_PIN, "Pinterest", int(stats.get("total_pinterest") or 0), PINK),
    ]
    max_plat = max((v for _, _, v, _ in platforms), default=1) or 1
    py = plat_top + 64
    inner_w = col_w - 48
    for icon, label, value, color in platforms:
        py = _draw_hbar_compact(
            draw, left_x + 24, py, inner_w, icon, label, value, max_plat, color
        )

    # --- RIGHT: donuts + formats ---
    donut_h = 300
    _rounded_rect(
        draw, (right_x, col_top, right_x + col_w, col_top + donut_h), 20, CARD, CARD_BORDER
    )
    draw.text(
        (right_x + 24, col_top + 18),
        f"{ICON_CHART}  Источник и тип",
        font=_font(26, bold=True),
        fill=TEXT,
    )
    left_cx = right_x + col_w // 4
    right_cx = right_x + 3 * col_w // 4
    cy = col_top + 145
    _draw_donut(
        draw,
        left_cx,
        cy,
        88,
        [("ЛС", dm, BLUE), ("Inline", inline, TEAL), ("Группы", group, PINK)],
        CARD,
    )
    _draw_donut(
        draw,
        right_cx,
        cy,
        88,
        [("Видео", video_n, AMBER), ("Аудио", audio_n, CORAL)],
        CARD,
    )
    # center icons
    draw.text(
        (left_cx - 12, cy - 14),
        ICON_COMMENT,
        font=_font(24),
        fill=BLUE,
    )
    draw.text(
        (right_cx - 12, cy - 14),
        ICON_FILM,
        font=_font(24),
        fill=AMBER,
    )
    small = _font(18)
    dm_pct = round(100 * dm / src_total)
    inline_pct = round(100 * inline / src_total)
    group_pct = round(100 * group / src_total)
    draw.text(
        (left_cx - 130, col_top + 248),
        f"ЛС {dm_pct}% · Inline {inline_pct}% · Группы {group_pct}%",
        font=small,
        fill=MUTED,
    )
    draw.text(
        (right_cx - 120, col_top + 248),
        f"Видео {round(100 * video_n / cont_total)}%  ·  "
        f"Аудио {round(100 * audio_n / cont_total)}%",
        font=small,
        fill=MUTED,
    )

    fmt_top = col_top + donut_h + 20
    fmt_h = HEIGHT - PADDING - fmt_top
    _rounded_rect(
        draw, (right_x, fmt_top, right_x + col_w, fmt_top + fmt_h), 20, CARD, CARD_BORDER
    )
    draw.text(
        (right_x + 24, fmt_top + 18),
        f"{ICON_HEADPHONES}  Популярные форматы",
        font=_font(26, bold=True),
        fill=TEXT,
    )

    # Video formats — one thick segmented bar
    fy = fmt_top + 70
    draw.text((right_x + 24, fy), f"{ICON_FILM}  Видео", font=_font(22, bold=True), fill=BLUE)
    fy += 36
    bar_w = col_w - 48
    if video_formats:
        vparts = [
            (str(name), int(count), FORMAT_COLORS[i % len(FORMAT_COLORS)])
            for i, (name, count) in enumerate(video_formats)
        ]
        _draw_segmented_bar(img, draw, right_x + 24, fy, bar_w, 34, vparts)
        fy += 48
        lx = right_x + 24
        for i, (name, count) in enumerate(video_formats):
            color = FORMAT_COLORS[i % len(FORMAT_COLORS)]
            chip = f"{name} {_fmt_int(int(count))}"
            draw.ellipse((lx, fy + 4, lx + 12, fy + 16), fill=color)
            draw.text((lx + 18, fy), chip, font=_font(18), fill=MUTED)
            tw, _ = _text_size(draw, chip, _font(18))
            lx += tw + 36
            if lx > right_x + col_w - 120:
                lx = right_x + 24
                fy += 26
        fy += 34
    else:
        draw.text((right_x + 24, fy), "нет данных", font=_font(20), fill=MUTED)
        fy += 50

    # Audio formats — one thick segmented bar
    draw.text((right_x + 24, fy), f"{ICON_MUSIC}  Аудио", font=_font(22, bold=True), fill=AMBER)
    fy += 36
    if audio_formats:
        aparts = [
            (str(name), int(count), FORMAT_COLORS[(i + 2) % len(FORMAT_COLORS)])
            for i, (name, count) in enumerate(audio_formats)
        ]
        _draw_segmented_bar(img, draw, right_x + 24, fy, bar_w, 34, aparts)
        fy += 48
        lx = right_x + 24
        for i, (name, count) in enumerate(audio_formats):
            color = FORMAT_COLORS[(i + 2) % len(FORMAT_COLORS)]
            chip = f"{name} {_fmt_int(int(count))}"
            draw.ellipse((lx, fy + 4, lx + 12, fy + 16), fill=color)
            draw.text((lx + 18, fy), chip, font=_font(18), fill=MUTED)
            tw, _ = _text_size(draw, chip, _font(18))
            lx += tw + 36
    else:
        draw.text((right_x + 24, fy), "нет данных", font=_font(20), fill=MUTED)

    # Footer
    draw.text(
        (PADDING, HEIGHT - 28),
        "komuzik · кэш 5 мин",
        font=_font(16),
        fill=(100, 116, 139),
    )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"stats_{period}_{int(time.time())}.png"
    img.save(out, format="PNG", optimize=True)
    return out


async def get_stats_image(stats: dict[str, Any], period: str) -> Path:
    """Return cached or freshly rendered stats image for period."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = f"stats_{CACHE_VERSION}_{period}"
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
        final = CACHE_DIR / f"{cache_key}.png"
        try:
            if final.exists():
                final.unlink()
            rendered.replace(final)
        except OSError:
            final = rendered
        meta_path.write_text(str(time.time()))
        for stale in CACHE_DIR.glob(f"stats_*_{period}_*.png"):
            if stale.name != final.name:
                try:
                    stale.unlink()
                except OSError:
                    pass
        return final
