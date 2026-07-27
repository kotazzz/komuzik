"""Event handlers for Telegram bot commands and callbacks."""

from ..config import DOWNLOAD_TIMEOUT_SECONDS
from .admin import AdminMixin
from .base import BotHandlersBase
from .callbacks import CallbacksMixin
from .common import (
    ACTIVE_BROADCASTS,
    ADMIN_PENDING,
    BOT_GROUPS_CACHE,
    CALLBACK_URLS,
    INLINE_JOBS,
    INLINE_SEARCH_MAX,
    PLAYLIST_STATES,
    REPORT_STATES,
    SEARCH_SESSIONS,
    CallbackHandler,
    format_ban_message,
)
from .downloads import DownloadsMixin
from .inline import InlineMixin
from .playlist import PlaylistMixin
from .user_commands import UserCommandsMixin

__all__ = [
    "ACTIVE_BROADCASTS",
    "ADMIN_PENDING",
    "BOT_GROUPS_CACHE",
    "CALLBACK_URLS",
    "DOWNLOAD_TIMEOUT_SECONDS",
    "INLINE_JOBS",
    "INLINE_SEARCH_MAX",
    "PLAYLIST_STATES",
    "REPORT_STATES",
    "SEARCH_SESSIONS",
    "BotHandlers",
    "CallbackHandler",
    "format_ban_message",
]


class BotHandlers(
    AdminMixin,
    UserCommandsMixin,
    CallbacksMixin,
    DownloadsMixin,
    PlaylistMixin,
    InlineMixin,
    BotHandlersBase,
):
    """Handles all bot commands and callbacks."""
