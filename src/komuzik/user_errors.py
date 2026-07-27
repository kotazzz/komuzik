"""Map raw yt-dlp / platform errors to short user-facing Russian messages."""

from __future__ import annotations

import re

from .downloaders import DownloadTimeoutError, DownloadTooLargeError
from .i18n import t

# Substrings that mean login / age-gate / cookies rather than a bot bug.
_ACCESS_MARKERS = (
    "log in for access",
    "not be comfortable for some audiences",
    "--cookies",
    "cookies-from-browser",
    "sign in to confirm",
    "confirm your age",
    "login required",
    "please sign in",
    "private video",
    "this video is private",
    "video is private",
    "members-only",
    "members only",
    "join this channel",
)

# yt-dlp / HTTP style: "HTTP Error 403: Forbidden", "error 401", etc.
_HTTP_ACCESS_RE = re.compile(
    r"http\s*error\s*40[13]\b"
    r"|\b40[13]\s*[:\-–]\s*(?:forbidden|unauthorized)\b"
    r"|status\s*(?:code\s*)?40[13]\b"
    r"|(?:returned|got)\s*40[13]\b"
    r"|\berror\s*40[13]\b",
    flags=re.IGNORECASE,
)


def is_access_restricted_error(error: BaseException | str) -> bool:
    """True if the failure is login / age-gate / HTTP 401/403 style access denial."""
    text = str(error).lower()
    if any(marker in text for marker in _ACCESS_MARKERS):
        return True
    return _HTTP_ACCESS_RE.search(text) is not None


def format_download_error(error: BaseException | str, *, context: str | None = None) -> str:
    """Return a human-readable download error for Telegram replies.

    Access / 401 / 403 failures get a short standalone message (no raw yt-dlp dump).
    Other errors keep optional ``context`` prefix plus the original text.
    """
    if isinstance(error, DownloadTimeoutError):
        return t("errors.download_timeout")
    if isinstance(error, DownloadTooLargeError):
        return t("errors.download_too_large")
    if is_access_restricted_error(error):
        return t("errors.download_unavailable")
    detail = str(error)
    if context:
        return f"{context}\n{detail}"
    return detail
