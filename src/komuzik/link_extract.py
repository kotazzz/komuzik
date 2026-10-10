"""Extract ordered media URLs from free-form message text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import (
    HLS_HOST_REGEX,
    PINTEREST_REGEX,
    TIKTOK_REGEX,
    TWITCH_CLIP_REGEX,
    TWITCH_VOD_REGEX,
    TWITTER_REGEX,
    VK_VIDEO_REGEX,
    YANDEX_MUSIC_REGEX,
)

# Trailing junk users often paste after a URL.
_TRAILING_PUNCT = re.compile(r"[),.;:!?>\"'\]]+$")

# Tighter than config.YOUTUBE_REGEX: the shared pattern allows `.+\?v=` which
# greedily spans spaces and swallows a following watch URL after a playlist page.
_YOUTUBE_EXTRACT = re.compile(
    r"(https?://)?(www\.)?youtu\.be/([\w-]{11})"
    r"|"
    r"(https?://)?(www\.)?(youtube|youtube-nocookie)\.com/"
    r"(watch\?v=|embed/|v/|shorts/)([\w-]{11})",
    re.IGNORECASE,
)

_PLAYLIST_PAGE = re.compile(
    r"(https?://)?(www\.)?youtube\.com/playlist\?list=([\w-]+)",
    re.IGNORECASE,
)
_MUSIC_PLAYLIST_PAGE = re.compile(
    r"(https?://)?music\.youtube\.com/playlist\?list=([\w-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedLink:
    """One media URL found in user text."""

    url: str
    platform: str  # youtube | tiktok | twitter | pinterest | hls_host | twitch | vk | yandex


_PLATFORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("youtube", _YOUTUBE_EXTRACT),
    ("tiktok", TIKTOK_REGEX),
    ("twitter", TWITTER_REGEX),
    ("pinterest", PINTEREST_REGEX),
    ("hls_host", HLS_HOST_REGEX),
    ("twitch", TWITCH_CLIP_REGEX),
    ("twitch", TWITCH_VOD_REGEX),
    ("vk", VK_VIDEO_REGEX),
    ("yandex", YANDEX_MUSIC_REGEX),
)


def ensure_http_url(raw: str) -> str:
    """Strip trailing punctuation and add https:// when the scheme is missing."""
    cleaned = _TRAILING_PUNCT.sub("", raw.strip())
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def _normalize_url(raw: str, _platform: str) -> str:
    return ensure_http_url(raw)


def _is_native_playlist_url(url: str) -> bool:
    """True for youtube.com/playlist?list=… / music.youtube.com/playlist?list=…"""
    return bool(_PLAYLIST_PAGE.search(url) or _MUSIC_PLAYLIST_PAGE.search(url))


def extract_media_urls(text: str) -> list[ParsedLink]:
    """Find media links in ``text``, ordered by appearance, de-duplicated.

    Native YouTube playlist page URLs are skipped — those still go through the
    dedicated playlist path. Overlapping matches prefer the earliest start; if
    two patterns claim the same span, the first registered platform wins.
    """
    if not text:
        return []

    hits: list[tuple[int, int, str, str]] = []  # start, end, platform, raw
    for platform, pattern in _PLATFORM_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0)
            if any(ch.isspace() for ch in raw):
                continue
            hits.append((match.start(), match.end(), platform, raw))

    hits.sort(key=lambda h: (h[0], h[1]))

    result: list[ParsedLink] = []
    seen: set[str] = set()
    occupied_until = -1

    for start, end, platform, raw in hits:
        if start < occupied_until:
            continue
        url = _normalize_url(raw, platform)
        if _is_native_playlist_url(url):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            occupied_until = end
            continue
        seen.add(key)
        result.append(ParsedLink(url=url, platform=platform))
        occupied_until = end

    return result
