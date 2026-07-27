"""Parse inline query text into download job parameters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import HLS_HOST_REGEX, PINTEREST_REGEX, TIKTOK_REGEX, TWITTER_REGEX, YOUTUBE_REGEX
from .i18n import t

ALLOWED_HEIGHTS = {360, 480, 720, 1080}
DEFAULT_YOUTUBE_QUALITY = "720p"
AUDIO_PREFIXES = {"music", "audio"}


@dataclass(frozen=True)
class ParsedInlineQuery:
    """Parsed inline query for a media download."""

    url: str
    platform: str
    mode: str  # video | audio
    quality: str
    description: str


def _normalize_url(raw: str) -> str:
    url = raw.strip().rstrip(").,]>")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def parse_inline_query(
    text: str,
    *,
    default_quality: str = DEFAULT_YOUTUBE_QUALITY,
) -> ParsedInlineQuery | None:
    """Parse inline query into URL, platform, mode and quality.

    Supports YouTube prefixes: music/audio, 360/480/720/1080.
    Other platforms ignore prefixes.
    ``default_quality`` is used for YouTube video when no height/audio prefix is set.
    """
    if not text or not text.strip():
        return None

    if default_quality not in {f"{h}p" for h in ALLOWED_HEIGHTS}:
        default_quality = DEFAULT_YOUTUBE_QUALITY

    tokens = text.strip().split()
    prefixes: list[str] = []
    url_token: str | None = None

    for token in tokens:
        candidate = _normalize_url(token)
        if (
            YOUTUBE_REGEX.search(candidate)
            or TIKTOK_REGEX.search(candidate)
            or TWITTER_REGEX.search(candidate)
            or PINTEREST_REGEX.search(candidate)
            or HLS_HOST_REGEX.search(candidate)
        ):
            url_token = candidate
            break
        prefixes.append(token.lower())

    if not url_token:
        # Fallback: search whole text for a URL-like match
        for regex in (YOUTUBE_REGEX, TIKTOK_REGEX, TWITTER_REGEX, PINTEREST_REGEX, HLS_HOST_REGEX):
            match = regex.search(text)
            if match:
                url_token = _normalize_url(match.group(0))
                break

    if not url_token:
        return None

    if TIKTOK_REGEX.search(url_token):
        return ParsedInlineQuery(
            url=url_token,
            platform="tiktok",
            mode="video",
            quality="auto",
            description=t("inline.job.tiktok"),
        )

    if TWITTER_REGEX.search(url_token):
        return ParsedInlineQuery(
            url=url_token,
            platform="twitter",
            mode="video",
            quality="auto",
            description=t("inline.job.twitter"),
        )

    if PINTEREST_REGEX.search(url_token):
        return ParsedInlineQuery(
            url=url_token,
            platform="pinterest",
            mode="video",
            quality="auto",
            description=t("inline.job.pinterest"),
        )

    if HLS_HOST_REGEX.search(url_token):
        return ParsedInlineQuery(
            url=url_token,
            platform="hls_host",
            mode="video",
            quality="best",
            description=t("inline.job.hls_host"),
        )

    yt_match = YOUTUBE_REGEX.search(url_token)
    if not yt_match:
        return None

    if "/shorts/" in url_token:
        return ParsedInlineQuery(
            url=url_token,
            platform="youtube_shorts",
            mode="video",
            quality="best",
            description=t("inline.job.youtube_shorts"),
        )

    mode = "video"
    quality = default_quality

    for prefix in prefixes:
        if prefix in AUDIO_PREFIXES:
            mode = "audio"
            quality = "high"
            continue
        height_match = re.fullmatch(r"(\d{3,4})p?", prefix)
        if height_match:
            height = int(height_match.group(1))
            if height in ALLOWED_HEIGHTS:
                mode = "video"
                quality = f"{height}p"

    description = (
        t("inline.job.youtube_audio")
        if mode == "audio"
        else t("inline.job.youtube_video", quality=quality)
    )

    return ParsedInlineQuery(
        url=url_token,
        platform="youtube",
        mode=mode,
        quality=quality,
        description=description,
    )
