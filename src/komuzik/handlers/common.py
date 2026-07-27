"""Shared handler constants, caches and helpers."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..broadcast import BroadcastControl
from ..i18n import t
from ..inline_query import ParsedInlineQuery
from ..playlist import PlaylistSession
from ..state import TTLCache

logger = logging.getLogger(__name__)

ADMIN_USERS_PAGE_SIZE = 15
ADMIN_HISTORY_PAGE_SIZE = 10
ADMIN_HISTORY_MAX = 50
ADMIN_USERS_KIND_KNOWN = "known"
ADMIN_USERS_KIND_ANON = "anon"
INLINE_SEARCH_MAX = 5

# Ephemeral per-user state. All of these are bounded and self-expiring: they are
# populated far more often than they are consumed (an inline search writes one
# entry per shown result per keystroke, of which the user picks at most one), so
# a plain dict here leaks for the lifetime of the process.
REPORT_STATES: TTLCache[int, bool] = TTLCache(
    maxsize=1_000, ttl=30 * 60, name="report_states"
)
ADMIN_PENDING: TTLCache[int, str] = TTLCache(
    maxsize=100, ttl=10 * 60, name="admin_pending"
)
PLAYLIST_STATES: TTLCache[int, PlaylistSession] = TTLCache(
    maxsize=200, ttl=2 * 60 * 60, name="playlist_states"
)
CALLBACK_URLS: TTLCache[str, str] = TTLCache(
    maxsize=20_000, ttl=60 * 60, name="callback_urls"
)
INLINE_JOBS: TTLCache[str, ParsedInlineQuery] = TTLCache(
    maxsize=5_000, ttl=15 * 60, name="inline_jobs"
)
SEARCH_SESSIONS: TTLCache[str, dict[str, Any]] = TTLCache(
    maxsize=1_000, ttl=30 * 60, name="search_sessions"
)
# Active /post broadcasts keyed by admin user id — allows the cancel button
# to flip cancel_requested without racing a second concurrent broadcast.
ACTIVE_BROADCASTS: dict[int, BroadcastControl] = {}
# Counting groups walks every dialog; cache for the same TTL as the infographic.
BOT_GROUPS_CACHE: TTLCache[str, int] = TTLCache(
    maxsize=1, ttl=5 * 60, sliding=False, name="bot_groups"
)
CallbackHandler = Callable[[Any, str], Awaitable[None]]


def format_ban_message(reason: str) -> str:
    return t("ban.message", reason=reason)


def _sender_display_name(sender) -> str | None:
    if sender is None:
        return None
    parts = [
        getattr(sender, "first_name", None),
        getattr(sender, "last_name", None),
    ]
    cleaned = [str(part).strip() for part in parts if part and str(part).strip()]
    return " ".join(cleaned) if cleaned else None


def _entity_display_name(entity) -> str | None:
    return _sender_display_name(entity)


def media_title(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    title = metadata.get("title") or metadata.get("track")
    if not title:
        return None
    text = str(title).strip()
    return text or None
