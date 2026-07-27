"""Base handler registration and shared download helpers."""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import shutil
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from telethon import events
from telethon.tl.custom import Message

from ..download_limiter import DownloadLimiter
from ..downloaders import DownloadTimeoutError, send_audio_content, send_image_content, send_video_content
from ..i18n import t
from ..repository import StatsRepository
from ..user_errors import format_download_error
from .common import CALLBACK_URLS, media_title

logger = logging.getLogger(__name__)

class BotHandlersBase:
    """Mixin for BotHandlers."""

    def __init__(
        self,
        client,
        stats_repo: StatsRepository,
        bot_username: str = "",
        download_limiter: DownloadLimiter | None = None,
    ):
        self.client = client
        self.bot_username = bot_username
        self.stats = stats_repo
        self.download_limiter = download_limiter or DownloadLimiter()
        self._register_handlers()

    @staticmethod
    def _requires_sender(
        handler: Callable[[Any], Awaitable[None]],
    ) -> Callable[[Any], Awaitable[None]]:
        """Skip message events that have no identifiable sender.

        ``event.sender_id`` is ``None`` for anonymous group admins and for
        service messages. Bans, download limits and statistics are all keyed by
        user id, so such messages cannot be processed — dropping them is the
        only correct option, and it keeps ``_get_user_info`` from raising.
        """

        @functools.wraps(handler)
        async def wrapper(event):
            if getattr(event, "sender_id", None) is None:
                logger.debug("Skipping message without sender_id in chat %s", event.chat_id)
                return
            await handler(event)

        return wrapper

    @staticmethod
    def command_pattern(command: str) -> str:
        r"""Build an anchored regex for ``/command`` with an optional @botname.

        The trailing lookahead is what keeps commands from bleeding into each
        other: without it ``^/user(?:@\w+)?(?:\s+(.+))?`` also matches
        ``/users`` (the argument group happily matches nothing), so Telethon --
        which dispatches to *every* matching handler -- fired both
        ``users_handler`` and ``user_handler`` on a single ``/users``.

        A lookahead is used rather than consuming the separator so multi-line
        arguments (``/ban 1 reason\ndetails``) still match.
        """
        return rf"^/{command}(?:@\w+)?(?=\s|$)"

    @staticmethod
    def command_args(text: str | None, command: str) -> str | None:
        """Return the argument tail of ``/command``, or None when absent."""
        if not text:
            return None
        match = re.match(rf"^/{command}(?:@\w+)?(?:\s+(.*))?$", text, re.DOTALL)
        if not match:
            return None
        args = (match.group(1) or "").strip()
        return args or None

    def _on_command(self, command: str):
        """Register a ``/command`` handler guarded by :meth:`_requires_sender`."""
        return self._on_message(self.command_pattern(command))

    def _on_message(self, pattern: str | None = None):
        """Register a NewMessage handler guarded by :meth:`_requires_sender`."""

        def register(handler):
            builder = events.NewMessage(pattern=pattern) if pattern else events.NewMessage()
            self.client.on(builder)(self._requires_sender(handler))
            return handler

        return register

    def _register_handlers(self):
        """Register all event handlers."""
        self._on_command("start")(self.start_handler)
        self._on_command("help")(self.help_handler)
        self._on_command("info")(self.info_handler)
        self._on_command("privacy")(self.privacy_handler)
        self._on_command("limits")(self.limits_handler)
        self._on_command("settings")(self.settings_handler)
        self._on_command("stats")(self.stats_handler)
        self._on_command("post")(self.post_handler)
        self._on_command("setstorage")(self.setstorage_handler)
        self._on_command("unsetstorage")(self.unsetstorage_handler)
        self._on_command("admin")(self.admin_handler)
        self._on_command("ban")(self.ban_handler)
        self._on_command("unban")(self.unban_handler)
        self._on_command("setconcurrent")(self.setconcurrent_handler)
        self._on_command("setplaylistlimit")(self.setplaylistlimit_handler)
        self._on_command("setuserlimit")(self.setuserlimit_handler)
        self._on_command("unsetuserlimit")(self.unsetuserlimit_handler)
        self._on_command("users")(self.users_handler)
        self._on_command("user")(self.user_handler)
        self._on_command("report")(self.report_handler)
        self._on_command("search")(self.search_handler)
        self._on_message()(self.message_handler)
        self.client.on(events.CallbackQuery())(self.callback_handler)
        self.client.on(events.InlineQuery())(self.inline_query_handler)
        self.client.on(events.Raw(UpdateBotInlineSend))(self.chosen_inline_handler)

    def _track_user(self, event: Message):
        """Track user activity."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            return
        username = event.sender.username if event.sender else None
        display_name = _sender_display_name(event.sender)
        self.stats.track_user(user_id, username, display_name=display_name)

    def _get_user_info(self, event: Message) -> tuple[int, str | None]:
        """Extract user ID and username from event."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            raise ValueError("Missing sender_id in Telegram event")
        username = event.sender.username if event.sender else None
        return user_id, username

    def _store_callback_url(self, url: str) -> str:
        """Store a URL behind a short callback token."""
        token = uuid.uuid4().hex
        CALLBACK_URLS[token] = url
        return token

    def _resolve_callback_url(self, token: str) -> str | None:
        """Resolve a callback token to its stored URL."""
        return CALLBACK_URLS.get(token)

    def _caption_kwargs(self, user_id: int) -> dict[str, bool]:
        """Load caption preferences for send_* helpers."""
        settings = self.stats.get_user_settings(user_id)
        return {
            "show_bot_caption": settings.show_bot_caption,
            "show_title": settings.show_title,
        }

    def _cleanup_download_file(self, file_path: str):
        """Remove the mkdtemp root that owns a downloaded file.

        gallery-dl may nest files under ``<tmp>/gallery-dl/...``; deleting only
        ``dirname(file)`` would leave the outer temp tree behind. We walk up to
        the direct child of the system temp directory (our ``mkdtemp`` folder)
        and remove that — never anything outside temp.
        """
        try:
            path = Path(file_path).resolve()
            temp_root = Path(tempfile.gettempdir()).resolve()
            path.relative_to(temp_root)
        except (OSError, ValueError):
            return

        cur = path if path.is_dir() else path.parent
        while cur.parent != temp_root and temp_root in cur.parents:
            cur = cur.parent
        if cur.parent == temp_root and cur.exists():
            shutil.rmtree(cur, ignore_errors=True)

    async def _bounded(self, awaitable):
        """Run a download under the configured wall-clock budget.

        Without this a stalled extractor holds the user's concurrency slot until
        the process restarts — ``download_timeout_seconds`` was read from config
        but never actually applied anywhere.

        Cancelling the coroutine does not stop the underlying worker thread
        (Python cannot kill threads); yt-dlp's ``socket_timeout`` is what bounds
        the thread. This bounds what the *user* experiences and frees the slot.
        """
        from komuzik.handlers import DOWNLOAD_TIMEOUT_SECONDS

        try:
            return await asyncio.wait_for(awaitable, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        except TimeoutError as e:
            raise DownloadTimeoutError(
                f"download exceeded {DOWNLOAD_TIMEOUT_SECONDS}s"
            ) from e

    @staticmethod
    async def _discard_status(message) -> None:
        """Delete a transient «Загрузка…» message, ignoring delete failures.

        Must run in ``finally``: on the error path the status message is just as
        stale as on the success path, and leaving it makes the bot look stuck.
        """
        if message is None:
            return
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete status message: {e}")

    async def _check_download_limit(self, event: Message, user_id: int, download_id: str) -> bool:
        """Check if user can start a new download.

        Returns:
            True if download can proceed, False if limit reached

        """
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await event.respond(
                t(
                    "download.active_limit",
                    active=active_count,
                    max=self.download_limiter.MAX_DOWNLOADS_PER_USER,
                )
            )
            return False
        return True

    async def _download_and_send_content(
        self,
        event: Message,
        url: str,
        *,
        status_text: str,
        error_context: str,
        download: Callable[[], Awaitable[tuple[str, dict]]],
        send: Callable[..., Awaitable[None]],
        track: Callable[..., None],
        action: str = "video",
        log_label: str = "content",
    ) -> None:
        """Shared download → send → track → cleanup pipeline.

        Platform handlers only differ in status text, the download coroutine,
        how media is sent, and which stats tracker is called — everything else
        (limiter, ``_bounded``, status discard, temp cleanup) lives here once.
        """
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        processing_msg = None
        try:
            client = event.client
            if client is None:
                await event.respond(t("common.telegram_client_unavailable"))
                return

            async with client.action(event.chat_id, action):
                try:
                    processing_msg = await event.respond(status_text)
                    logger.info("Downloading %s: %s", log_label, url)

                    file_path, metadata = await self._bounded(download())
                    logger.info("%s downloaded successfully: %s", log_label, file_path)

                    await send(
                        event,
                        file_path,
                        metadata,
                        **self._caption_kwargs(user_id),
                    )

                    track(
                        user_id,
                        username,
                        success=True,
                        url=url,
                        title=media_title(metadata),
                    )

                except Exception as e:
                    logger.error("Error sending %s: %s", log_label, e)
                    track(
                        user_id,
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(
                        format_download_error(e, context=error_context)
                    )
        finally:
            await self._discard_status(processing_msg)
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _send_video_media(
        self, event, file_path: str, metadata: dict, **caption_kw: Any
    ) -> None:
        await send_video_content(
            event, file_path, metadata, self.bot_username, **caption_kw
        )

    async def _send_audio_media(
        self, event, file_path: str, metadata: dict, **caption_kw: Any
    ) -> None:
        await send_audio_content(
            event, file_path, metadata, self.bot_username, **caption_kw
        )

    async def _send_media_by_content_type(
        self, event, file_path: str, metadata: dict, **caption_kw: Any
    ) -> None:
        """Send photo or video depending on downloader metadata."""
        if metadata.get("content_type") == "photo":
            await send_image_content(
                event,
                file_path,
                self.bot_username,
                metadata=metadata,
                **caption_kw,
            )
        else:
            await send_video_content(
                event, file_path, metadata, self.bot_username, **caption_kw
            )
