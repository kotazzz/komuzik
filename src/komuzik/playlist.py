"""YouTube / YouTube Music playlist parsing, exclusions, and preview."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import yt_dlp

from .config import YDLP_BASE_OPTS

logger = logging.getLogger(__name__)

PLAYLIST_MAX_ENTRIES = 200
PLAYLIST_PAGE_SIZE = 10
PLAYLIST_BATCH_SIZE = 10

# Dedicated playlist pages only (not watch?v=&list= recommendations)
PLAYLIST_URL_REGEX = re.compile(
    r"(https?://)?(www\.)?youtube\.com/playlist\?list=([\w-]+)",
    re.IGNORECASE,
)
MUSIC_PLAYLIST_REGEX = re.compile(
    r"(https?://)?music\.youtube\.com/playlist\?list=([\w-]+)",
    re.IGNORECASE,
)


@dataclass
class PlaylistEntry:
    """Single playlist item."""

    video_id: str
    title: str
    url: str


@dataclass
class PlaylistSession:
    """In-memory DM playlist preview/download session."""

    user_id: int
    playlist_url: str
    title: str
    is_music: bool
    entries: list[PlaylistEntry]
    excluded: set[int] = field(default_factory=set)  # 1-based indices
    page: int = 0
    preview_msg_id: int | None = None
    truncated: bool = False
    cancel_requested: bool = False
    downloading: bool = False


EXCLUSION_HELP = (
    "**Как убрать треки из загрузки**\n"
    "Ответьте **reply** на это сообщение текстом:\n\n"
    "• `-5` — не качать 5-й трек\n"
    "• `-1,3,8` — не качать 1, 3 и 8\n"
    "• `-1-20` — не качать с 1 по 20 включительно\n"
    "• `-1-10,15,20-30` — диапазоны и отдельные номера\n"
    "• `+5` — вернуть 5-й обратно в загрузку\n"
    "• `+11,13,15` — вернуть 11, 13 и 15\n\n"
    "Номера — как в списке ниже. Можно несколько раз подряд."
)


def find_playlist_url(text: str) -> tuple[str, bool] | None:
    """Return (normalized_url, is_music) if text contains a playlist link."""
    music = MUSIC_PLAYLIST_REGEX.search(text)
    if music:
        list_id = music.group(2)
        return f"https://music.youtube.com/playlist?list={list_id}", True

    match = PLAYLIST_URL_REGEX.search(text)
    if not match:
        return None
    list_id = match.group(3)
    return f"https://www.youtube.com/playlist?list={list_id}", False


def _normalize_exclusion_text(ops: str) -> str:
    """Normalize punctuation users may type from mobile keyboards."""
    text = ops.strip()
    replacements = {
        "，": ",",  # fullwidth comma
        "､": ",",
        "；": ",",
        ";": ",",
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus sign
        "＋": "+",  # fullwidth plus
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def parse_exclusion_ops(ops: str, max_n: int, current: set[int]) -> set[int] | None:
    """Apply exclusion/inclusion ops. Returns new set or None if invalid.

    A leading ``+`` or ``-`` sets the mode for that item and for all following
    bare numbers/ranges until another sign appears.

    Examples::

        +11,13,15,18-20  → include 11, 13, 15, 18, 19, 20
        -1,3,8           → exclude 1, 3, 8
        +1,2,-4,5        → include 1, 2; exclude 4, 5
    """
    if not ops or not ops.strip():
        return None
    text = _normalize_exclusion_text(ops)
    if text.startswith("http") or text.startswith("/"):
        return None
    if not re.fullmatch(r"[+\-\d,\s]+", text):
        return None

    result = set(current)
    # None = no sign seen yet; bare items default to exclude
    include: bool | None = None

    for raw in text.split(","):
        token = raw.strip()
        if not token:
            continue

        if token.startswith("+"):
            include = True
            body = token[1:].strip()
        elif token.startswith("-"):
            include = False
            body = token[1:].strip()
        else:
            body = token

        if not body:
            return None

        do_include = bool(include) if include is not None else False

        try:
            if "-" in body:
                a_s, b_s = body.split("-", 1)
                if not a_s or not b_s:
                    return None
                start, end = int(a_s), int(b_s)
                if start > end:
                    start, end = end, start
                indices = range(start, end + 1)
            else:
                indices = [int(body)]
        except ValueError:
            return None

        for i in indices:
            if i < 1 or i > max_n:
                continue
            if do_include:
                result.discard(i)
            else:
                result.add(i)

    return result


def _watch_url(video_id: str, *, is_music: bool) -> str:
    if is_music:
        return f"https://music.youtube.com/watch?v={video_id}"
    return f"https://www.youtube.com/watch?v={video_id}"


async def extract_playlist(url: str, *, is_music: bool) -> tuple[str, list[PlaylistEntry], bool]:
    """Flat-extract playlist. Returns (title, entries, truncated)."""
    loop = asyncio.get_running_loop()

    def _run() -> tuple[str, list[PlaylistEntry], bool]:
        opts: dict[str, Any] = {
            **YDLP_BASE_OPTS,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "noplaylist": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise ValueError("Не удалось прочитать плейлист")

        title = str(info.get("title") or "Плейлист")
        raw_entries = list(info.get("entries") or [])
        entries: list[PlaylistEntry] = []
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            vid = item.get("id")
            if not vid:
                url_field = str(item.get("url") or "")
                m = re.search(r"(?:v=|/shorts/)([\w-]{11})", url_field)
                if m:
                    vid = m.group(1)
                else:
                    continue
            vid = str(vid)
            if len(vid) != 11:
                continue
            item_title = str(item.get("title") or vid)
            entries.append(
                PlaylistEntry(
                    video_id=vid,
                    title=item_title,
                    url=_watch_url(vid, is_music=is_music),
                )
            )

        truncated = len(entries) > PLAYLIST_MAX_ENTRIES
        if truncated:
            entries = entries[:PLAYLIST_MAX_ENTRIES]
        return title, entries, truncated

    return await loop.run_in_executor(None, _run)


def format_preview_page(session: PlaylistSession) -> str:
    """Build Telegram Markdown preview for current page."""
    total = len(session.entries)
    selected = total - len(session.excluded)
    pages = max(1, (total + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE)
    page = min(max(session.page, 0), pages - 1)
    session.page = page
    start = page * PLAYLIST_PAGE_SIZE
    end = min(start + PLAYLIST_PAGE_SIZE, total)

    lines = [
        f"📃 **{session.title}**",
        f"Треков: {total} · к загрузке: **{selected}** · стр. {page + 1}/{pages}",
    ]
    if session.truncated:
        lines.append(f"⚠️ Показаны первые {PLAYLIST_MAX_ENTRIES} треков.")
    lines.append("")
    lines.append(EXCLUSION_HELP)
    lines.append("")

    for i in range(start, end):
        entry = session.entries[i]
        num = i + 1
        mark = "❌ " if num in session.excluded else ""
        # Escape markdown special chars lightly in title
        safe_title = entry.title.replace("[", "(").replace("]", ")")[:80]
        lines.append(f"{mark}{num}. [{safe_title}]({entry.url})")

    return "\n".join(lines)


def selected_entries(session: PlaylistSession) -> list[PlaylistEntry]:
    """Entries not excluded, in order."""
    return [
        entry
        for i, entry in enumerate(session.entries, start=1)
        if i not in session.excluded
    ]
