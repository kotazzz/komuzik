"""Event handlers for Telegram bot commands and callbacks."""

import logging
import os
import re
import shutil
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from telethon import Button, events
from telethon.tl.custom import Message
from telethon.tl.types import UpdateBotInlineSend

from .config import (
    MSG_HELP,
    MSG_START,
    PINTEREST_REGEX,
    TIKTOK_REGEX,
    TWITTER_REGEX,
    YOUTUBE_REGEX,
)
from .download_limiter import DownloadLimiter
from .downloaders import (
    download_pinterest_content,
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    get_available_formats,
    get_media_title,
    search_youtube,
    send_audio_content,
    send_image_content,
    send_playlist_album,
    send_video_content,
)
from .inline_media import (
    PM_UNAVAILABLE_MESSAGE,
    delete_staging_message,
    edit_inline_text,
    edit_inline_with_media,
    is_pm_unavailable_error,
    stage_media_to_user,
)
from .inline_query import ParsedInlineQuery, parse_inline_query
from .playlist import (
    PLAYLIST_BATCH_SIZE,
    PLAYLIST_PAGE_SIZE,
    PlaylistSession,
    extract_playlist,
    find_playlist_url,
    format_preview_page,
    parse_exclusion_ops,
    selected_entries,
)
from .repository import StatsRepository, format_download_history_line, format_user_label
from .stats_infographic import get_stats_image
from .storage import PartialCopyError, copy_messages_to_chat, delete_staging, stage_media

logger = logging.getLogger(__name__)

# States for /report command state machine
REPORT_STATES = {}
ADMIN_PENDING: dict[int, str] = {}
ADMIN_USERS_PAGE_SIZE = 15
ADMIN_HISTORY_PAGE_SIZE = 10
ADMIN_HISTORY_MAX = 50
ADMIN_USERS_KIND_KNOWN = "known"
ADMIN_USERS_KIND_ANON = "anon"
PLAYLIST_STATES: dict[int, PlaylistSession] = {}
CALLBACK_URLS: dict[str, str] = {}
INLINE_JOBS: dict[str, ParsedInlineQuery] = {}
CallbackHandler = Callable[[Any, str], Awaitable[None]]


def format_ban_message(reason: str) -> str:
    return (
        "🚫 Вы заблокированы.\n"
        f"Причина: {reason}\n"
        "Если ошибка — /report"
    )


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


def _media_title(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    title = metadata.get("title") or metadata.get("track")
    if not title:
        return None
    text = str(title).strip()
    return text or None


class BotHandlers:
    """Handles all bot commands and callbacks."""

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

    def _register_handlers(self):
        """Register all event handlers."""
        self.client.on(events.NewMessage(pattern="/start"))(self.start_handler)
        self.client.on(events.NewMessage(pattern="/help"))(self.help_handler)
        self.client.on(events.NewMessage(pattern="/settings"))(self.settings_handler)
        self.client.on(events.NewMessage(pattern="/stats"))(self.stats_handler)
        self.client.on(events.NewMessage(pattern="/post"))(self.post_handler)
        self.client.on(events.NewMessage(pattern=r"^/setstorage(?:@\w+)?"))(self.setstorage_handler)
        self.client.on(events.NewMessage(pattern=r"^/unsetstorage(?:@\w+)?"))(
            self.unsetstorage_handler
        )
        self.client.on(events.NewMessage(pattern=r"^/admin(?:@\w+)?"))(self.admin_handler)
        self.client.on(events.NewMessage(pattern=r"^/ban(?:@\w+)?(?:\s+(.+))?"))(self.ban_handler)
        self.client.on(events.NewMessage(pattern=r"^/unban(?:@\w+)?(?:\s+(.+))?"))(self.unban_handler)
        self.client.on(events.NewMessage(pattern=r"^/setconcurrent(?:@\w+)?(?:\s+(.+))?"))(
            self.setconcurrent_handler
        )
        self.client.on(events.NewMessage(pattern=r"^/setplaylistlimit(?:@\w+)?(?:\s+(.+))?"))(
            self.setplaylistlimit_handler
        )
        self.client.on(events.NewMessage(pattern=r"^/setuserlimit(?:@\w+)?(?:\s+(.+))?"))(
            self.setuserlimit_handler
        )
        self.client.on(events.NewMessage(pattern=r"^/unsetuserlimit(?:@\w+)?(?:\s+(.+))?"))(
            self.unsetuserlimit_handler
        )
        self.client.on(events.NewMessage(pattern=r"^/users(?:@\w+)?"))(self.users_handler)
        self.client.on(events.NewMessage(pattern=r"^/user(?:@\w+)?(?:\s+(.+))?"))(self.user_handler)
        self.client.on(events.NewMessage(pattern="/report"))(self.report_handler)
        self.client.on(events.NewMessage(pattern=r"^/search(?:\s+(.+))?"))(self.search_handler)
        self.client.on(events.NewMessage())(self.message_handler)
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
        """Remove the temporary directory that contains a downloaded file."""
        directory = os.path.dirname(file_path)
        if os.path.exists(directory):
            shutil.rmtree(directory)

    async def _check_download_limit(self, event: Message, user_id: int, download_id: str) -> bool:
        """Check if user can start a new download.

        Returns:
            True if download can proceed, False if limit reached

        """
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await event.respond(
                f"⚠️ У вас уже есть активная загрузка ({active_count}/{self.download_limiter.MAX_DOWNLOADS_PER_USER}). "
                f"Пожалуйста, дождитесь завершения текущей загрузки."
            )
            return False
        return True

    async def _download_and_send_content(
        self,
        event: Message,
        url: str,
        quality: str,
        content_type: str,
        download_func: Callable,
        send_func: Callable,
        track_func: Callable,
        action: str,
    ):
        """Generic function to download and send content (video/audio).

        Args:
            event: Telegram event
            url: Content URL
            quality: Quality setting
            content_type: 'video' or 'audio' for logging
            download_func: Function to download content
            send_func: Function to send content
            track_func: Function to track download stats
            action: Telegram action type ('video' or 'audio')

        """
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        # Check download limit
        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, action):
                try:
                    processing_msg = await event.respond(
                        f"Загрузка {content_type}... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading {content_type}: {url} with quality: {quality}")

                    file_path, metadata = await download_func(url, quality)
                    logger.info(f"{content_type.capitalize()} downloaded successfully: {file_path}")

                    await send_func(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    # Track successful download
                    track_func(
                        user_id,
                        quality,
                        username,
                        success=True,
                        url=url,
                        title=_media_title(metadata),
                    )

                except Exception as e:
                    logger.error(f"Error sending {content_type}: {e}")
                    # Track failed download
                    track_func(
                        user_id,
                        quality,
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(f"Произошла ошибка при обработке {content_type}: {e!s}")
        finally:
            # Always release the download slot
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def start_handler(self, event: Message):
        """Handle /start command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(MSG_START)

    async def help_handler(self, event: Message):
        """Handle /help command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(MSG_HELP)

    async def _count_bot_groups(self) -> int:
        """Count groups/supergroups the bot is currently in."""
        count = 0
        try:
            async for dialog in self.client.iter_dialogs():
                if bool(getattr(dialog, "is_group", False)):
                    count += 1
        except Exception as e:
            logger.error(f"Failed to count bot groups: {e}")
        return count

    async def settings_handler(self, event: Message):
        """Handle /settings — personal in DM, chat settings in groups (admins only)."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        if bool(getattr(event, "is_group", False)):
            if not await self._is_chat_admin(event):
                await event.respond("❌ Только администраторы могут менять настройки чата.")
                return
            chat_id = int(event.chat_id)
            settings = self.stats.get_chat_settings(chat_id)
            await event.respond(
                self._format_chat_settings_message(settings),
                buttons=self._chat_settings_buttons(settings),
            )
            return

        settings = self.stats.get_user_settings(user_id)
        await event.respond(
            self._format_settings_message(settings),
            buttons=self._settings_buttons(settings),
        )

    async def _is_chat_admin(self, event: Message) -> bool:
        """Return True if the sender is any admin/creator of the chat."""
        sender_id = cast("int | None", event.sender_id)
        if sender_id is None:
            return False
        try:
            perms = await self.client.get_permissions(event.chat_id, sender_id)
            return bool(getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False))
        except Exception as e:
            logger.error(f"Failed to check admin rights: {e}")
            return False

    def _format_settings_message(self, settings) -> str:
        bot_state = "✅ Вкл" if settings.show_bot_caption else "❌ Выкл"
        title_state = "✅ Вкл" if settings.show_title else "❌ Выкл"
        return (
            "⚙️ **Личные настройки**\n\n"
            f"🤖 Подпись бота (@{self.bot_username or 'bot'}): {bot_state}\n"
            f"📝 Название видео: {title_state}\n"
            f"📺 Качество (инлайн): **{settings.default_quality}**\n\n"
            "Качество влияет на инлайн без префикса. "
            "В ЛС по ссылке выбор формата как раньше."
        )

    def _settings_buttons(self, settings):
        bot_label = (
            "🤖 Подпись бота: выключить"
            if settings.show_bot_caption
            else "🤖 Подпись бота: включить"
        )
        title_label = "📝 Название: выключить" if settings.show_title else "📝 Название: включить"
        return [
            [Button.inline(bot_label, data="settings_bot")],
            [Button.inline(title_label, data="settings_title")],
            [Button.inline("📺 Качество по умолчанию", data="settings_quality")],
        ]

    def _format_quality_settings_message(self, current_quality: str, *, scope: str) -> str:
        scope_line = (
            "для **инлайна** (личные настройки)"
            if scope == "user"
            else "для **этой группы** (автозагрузка)"
        )
        return (
            f"📺 **Качество по умолчанию** {scope_line}\n\n"
            "Сейчас: **"
            f"{current_quality}**\n\n"
            "Ориентир размера (ролик ~3–5 мин):\n"
            "• 360p — ~5–15 МБ\n"
            "• 480p — ~15–30 МБ\n"
            "• 720p — ~30–60 МБ\n"
            "• 1080p — ~60–120+ МБ\n\n"
            "⚠️ Не ставьте высокое качество без нужды — "
            "файлы быстро забивают память телефона.\n\n"
            "Префикс в запросе (`480`, `music`…) всегда важнее этого дефолта."
        )

    def _quality_settings_buttons(self, current_quality: str, *, prefix: str) -> list:
        """Build quality picker. prefix is 'settings_q_' or 'chatset_q_'."""
        row: list = []
        buttons: list = []
        for q in ("360p", "480p", "720p", "1080p"):
            mark = "✅ " if q == current_quality else ""
            row.append(Button.inline(f"{mark}{q}", data=f"{prefix}{q}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        back = "settings_back" if prefix.startswith("settings_") else "chatset_back"
        buttons.append([Button.inline("← Назад", data=back)])
        return buttons

    def _format_chat_settings_message(self, settings) -> str:
        def state(on: bool) -> str:
            return "✅ Вкл" if on else "❌ Выкл"

        return (
            "⚙️ **Настройки чата**\n\n"
            f"▶ YouTube: {state(settings.allow_youtube)}\n"
            f"♪ TikTok: {state(settings.allow_tiktok)}\n"
            f"𝕏 Twitter/X: {state(settings.allow_twitter)}\n"
            f"📌 Pinterest: {state(settings.allow_pinterest)}\n\n"
            f"🤖 Подпись бота: {state(settings.show_bot_caption)}\n"
            f"📝 Название видео: {state(settings.show_title)}\n"
            f"📺 Качество YouTube: **{settings.default_quality}**\n\n"
            "Выключенные платформы бот игнорирует. Только для этой группы."
        )

    def _chat_settings_buttons(self, settings):
        def label(name: str, on: bool) -> str:
            mark = "✅" if on else "❌"
            return f"{mark} {name}"

        return [
            [
                Button.inline(
                    label("YouTube", settings.allow_youtube), data="chatset_allow_youtube"
                ),
                Button.inline(label("TikTok", settings.allow_tiktok), data="chatset_allow_tiktok"),
            ],
            [
                Button.inline(
                    label("Twitter/X", settings.allow_twitter), data="chatset_allow_twitter"
                ),
                Button.inline(
                    label("Pinterest", settings.allow_pinterest), data="chatset_allow_pinterest"
                ),
            ],
            [
                Button.inline(
                    label("Подпись бота", settings.show_bot_caption),
                    data="chatset_show_bot_caption",
                ),
            ],
            [
                Button.inline(
                    label("Название", settings.show_title),
                    data="chatset_show_title",
                ),
            ],
            [Button.inline("📺 Качество по умолчанию", data="chatset_quality")],
        ]

    async def stats_handler(self, event: Message):
        """Handle /stats command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        buttons = [
            [
                Button.inline("📊 За день", data="stats_day"),
                Button.inline("📅 За месяц", data="stats_month"),
            ],
            [Button.inline("📈 За все время", data="stats_all")],
        ]

        await event.respond(
            "📊 Статистика бота Komuzik\n\nВыберите период для просмотра статистики:",
            buttons=buttons,
        )

    async def search_handler(self, event: Message):
        """Handle /search command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        text = getattr(event.message, "text", None)
        if not isinstance(text, str):
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        match = re.match(r"^/search(?:\s+(.+))?", text)
        query = match.group(1) if match else None

        if not query:
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        # Track search
        user_id, username = self._get_user_info(event)
        self.stats.track_search(user_id, username)

        searching_msg = await event.respond(f"🔍 Поиск: {query}...")
        results = await search_youtube(query, max_results=5)

        if not results:
            if searching_msg is not None:
                await searching_msg.edit("Ничего не найдено. Попробуйте изменить запрос.")
            return

        buttons = []
        for i, result in enumerate(results, 1):
            duration = int(result["duration"]) if result["duration"] else 0
            duration_min = duration // 60
            duration_sec = duration % 60
            button_text = f"{i}. {result['title'][:50]}{'...' if len(result['title']) > 50 else ''} ({duration_min}:{duration_sec:02d})"
            buttons.append(
                [
                    Button.inline(
                        button_text, data=f"select_{self._store_callback_url(result['url'])}"
                    )
                ]
            )

        if searching_msg is not None:
            await searching_msg.edit("Выберите видео из результатов поиска:", buttons=buttons)

    async def message_handler(self, event: Message):
        """Handle incoming messages with YouTube, TikTok, Twitter and Pinterest links."""
        message_obj = event.message
        user_id, username = self._get_user_info(event)
        chat_is_group = bool(getattr(event, "is_group", False))

        # Admin reply to a report → copy 1:1 to the reporter (quote their report)
        if await self._maybe_handle_report_reply(event, message_obj, user_id):
            return

        if await self._maybe_handle_admin_pending(event, message_obj, user_id):
            return

        # Check if user is in report state
        if REPORT_STATES.get(user_id):
            raw_report_text = (
                getattr(message_obj, "text", None) if message_obj is not None else None
            )
            report_text = raw_report_text if isinstance(raw_report_text, str) else ""

            # Ignore if user sends another command while in report state
            if report_text.startswith("/"):
                # Handle /cancel command
                if report_text.strip() == "/cancel":
                    del REPORT_STATES[user_id]
                    await event.respond("❌ Отправка отчета отменена.")
                return

            # Save report to database
            db_text = report_text or "[Медиафайл]"
            self.stats.save_user_report(user_id, username, db_text)

            # Send report to admins (header + 1:1 copy without "forwarded from")
            header_text = (
                f"📋 **Новый отчет**\nОт: @{username or user_id} (номер: {user_id})"
            )
            user_report_msg_id = int(message_obj.id) if message_obj is not None else 0

            for admin_id in self.download_limiter.ADMIN_USER_IDS:
                try:
                    header = await self.client.send_message(admin_id, header_text)
                    if message_obj is None:
                        continue
                    body = await self.client.send_message(admin_id, message_obj)
                    self.stats.save_report_thread(
                        admin_id=int(admin_id),
                        header_msg_id=int(header.id),
                        body_msg_id=int(body.id),
                        user_id=user_id,
                        user_report_msg_id=user_report_msg_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to send report to admin {admin_id}: {e}")

            # Confirm to user
            await event.respond("✅ Спасибо! Ваш отчет отправлен администраторам.")

            # Clear state
            del REPORT_STATES[user_id]
            return

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if isinstance(text, str) and re.match(r"^/report(?:@\w+)?(?:\s|$)", text):
            pass
        elif await self._reject_if_banned(event, user_id, chat_is_group=chat_is_group):
            return

        # Playlist exclusion reply (must reply to preview message)
        if await self._maybe_handle_playlist_exclusion_reply(event, message_obj, user_id):
            return

        if not isinstance(text, str) or not text:
            return

        if text.startswith("/"):
            return

        # Groups/supergroups: auto-download links (silent if no URL)
        if bool(getattr(event, "is_group", False)):
            await self._handle_group_link_message(event, text)
            return

        self._track_user(event)

        # Playlists (DM only) — before single-video YouTube match
        playlist_hit = find_playlist_url(text)
        if playlist_hit is not None:
            await self._start_playlist_session(event, user_id, playlist_hit[0], playlist_hit[1])
            return

        # Check for Twitter/X
        twitter_match = TWITTER_REGEX.search(text)
        if twitter_match:
            await self._handle_twitter(event, twitter_match.group(0))
            return

        # Check for Pinterest
        pinterest_match = PINTEREST_REGEX.search(text)
        if pinterest_match:
            await self._handle_pinterest(event, pinterest_match.group(0))
            return

        # Check for TikTok
        tiktok_match = TIKTOK_REGEX.search(text)
        if tiktok_match:
            await self._handle_tiktok(event, tiktok_match.group(0))
            return

        # Check for YouTube (including Shorts)
        youtube_match = YOUTUBE_REGEX.search(text)
        if not youtube_match:
            await event.respond(
                "Пожалуйста, отправьте корректную ссылку на видео YouTube, YouTube Shorts, "
                "плейлист YouTube / Music, TikTok, Twitter/X или Pinterest."
            )
            return

        matched_url = youtube_match.group(0)

        # Check if it's a YouTube Shorts
        if "/shorts/" in matched_url:
            await self._handle_youtube_shorts(event, matched_url)
        else:
            await self._show_content_type_selection(event, matched_url)

    def _playlist_buttons(self, session: PlaylistSession) -> list:
        total = len(session.entries)
        pages = max(1, (total + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE)
        selected = total - len(session.excluded)
        nav: list = []
        if session.page > 0:
            nav.append(Button.inline("⬅️", data="pl_prev"))
        if session.page < pages - 1:
            nav.append(Button.inline("➡️", data="pl_next"))
        rows: list = []
        if nav:
            rows.append(nav)
        rows.append(
            [
                Button.inline("🎬 Видео", data="pl_video"),
                Button.inline("🎵 Аудио", data="pl_audio"),
            ]
        )
        rows.append(
            [Button.inline(f"✅ Скачать выбранное ({selected})", data="pl_hint")]
        )
        return rows

    async def _start_playlist_session(
        self, event: Message, user_id: int, url: str, is_music: bool
    ) -> None:
        """Load playlist and show first preview page."""
        status = await event.respond("📃 Читаю плейлист…")
        try:
            title, entries, truncated = await extract_playlist(url, is_music=is_music)
        except Exception as e:
            logger.error(f"Playlist extract failed: {e}")
            await event.respond(f"❌ Не удалось открыть плейлист: {e!s}")
            try:
                await status.delete()
            except Exception:
                pass
            return

        if not entries:
            await event.respond("Плейлист пуст или недоступен.")
            try:
                await status.delete()
            except Exception:
                pass
            return

        session = PlaylistSession(
            user_id=user_id,
            playlist_url=url,
            title=title,
            is_music=is_music,
            entries=entries,
            truncated=truncated,
        )
        PLAYLIST_STATES[user_id] = session
        text = format_preview_page(session)
        try:
            await status.edit(text, buttons=self._playlist_buttons(session), link_preview=False)
            session.preview_msg_id = int(status.id)
        except Exception:
            msg = await event.respond(
                text, buttons=self._playlist_buttons(session), link_preview=False
            )
            session.preview_msg_id = int(msg.id)

    async def _maybe_handle_playlist_exclusion_reply(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """If user replies to playlist preview with exclusion ops, apply them."""
        session = PLAYLIST_STATES.get(user_id)
        if session is None or session.preview_msg_id is None:
            return False
        if bool(getattr(event, "is_group", False)):
            return False

        reply = getattr(message_obj, "reply_to", None) if message_obj is not None else None
        reply_id = getattr(reply, "reply_to_msg_id", None) if reply is not None else None
        if reply_id != session.preview_msg_id:
            return False

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if not isinstance(text, str):
            return False

        new_excluded = parse_exclusion_ops(text, len(session.entries), session.excluded)
        if new_excluded is None:
            await event.respond(
                "Не понял команду.\n\n"
                "Ответьте **reply** на превью плейлиста, например:\n"
                "• `-5` — убрать 5-й\n"
                "• `-1,3,8` — убрать несколько\n"
                "• `-1-20` — убрать диапазон\n"
                "• `+5` — вернуть 5-й",
                reply_to=session.preview_msg_id,
            )
            return True

        session.excluded = new_excluded
        try:
            await self.client.edit_message(
                event.chat_id,
                session.preview_msg_id,
                format_preview_page(session),
                buttons=self._playlist_buttons(session),
                link_preview=False,
            )
        except Exception as e:
            logger.error(f"Failed to update playlist preview: {e}")
        try:
            await message_obj.delete()
        except Exception:
            pass
        return True

    async def _refresh_playlist_preview(self, event, session: PlaylistSession) -> None:
        text = format_preview_page(session)
        buttons = self._playlist_buttons(session)
        try:
            await event.edit(text, buttons=buttons, link_preview=False)
        except Exception as e:
            logger.error(f"Failed to refresh playlist preview: {e}")

    async def _handle_playlist_callback(self, event, data: str) -> None:
        """Pagination / type / quality / download for playlist session."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            await event.answer()
            return
        session = PLAYLIST_STATES.get(user_id)
        if session is None:
            await event.answer("Сессия плейлиста истекла. Пришлите ссылку снова.", alert=True)
            return

        if data == "pl_hint":
            await event.answer(
                "Сначала Видео или Аудио → качество. "
                "Чтобы убрать треки — reply на превью (см. инструкцию в сообщении).",
                alert=True,
            )
            return

        if data == "pl_stop":
            session.cancel_requested = True
            await event.answer("⏹ Останавливаю… дошлю уже скачанное.")
            return

        if data == "pl_prev":
            session.page = max(0, session.page - 1)
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data == "pl_next":
            pages = max(
                1, (len(session.entries) + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE
            )
            session.page = min(pages - 1, session.page + 1)
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data == "pl_video":
            buttons = [
                [
                    Button.inline("360p", data="pl_vq_360p"),
                    Button.inline("480p", data="pl_vq_480p"),
                ],
                [
                    Button.inline("720p", data="pl_vq_720p"),
                    Button.inline("1080p", data="pl_vq_1080p"),
                ],
                [Button.inline("← Назад", data="pl_back")],
            ]
            await event.edit(
                f"📃 **{session.title}**\n\n"
                f"К загрузке: **{len(selected_entries(session))}**\n"
                "Выберите качество видео для всего плейлиста:",
                buttons=buttons,
            )
            await event.answer()
            return

        if data == "pl_audio":
            buttons = [
                [
                    Button.inline("Высокое", data="pl_aq_high"),
                    Button.inline("Среднее", data="pl_aq_medium"),
                ],
                [Button.inline("Низкое", data="pl_aq_low")],
                [Button.inline("← Назад", data="pl_back")],
            ]
            await event.edit(
                f"📃 **{session.title}**\n\n"
                f"К загрузке: **{len(selected_entries(session))}**\n"
                "Выберите качество аудио для всего плейлиста:",
                buttons=buttons,
            )
            await event.answer()
            return

        if data == "pl_back":
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data.startswith("pl_vq_"):
            quality = data.removeprefix("pl_vq_")
            await event.answer(f"Качаю видео {quality}…")
            await self._download_playlist(event, session, mode="video", quality=quality)
            return

        if data.startswith("pl_aq_"):
            quality = data.removeprefix("pl_aq_")
            await event.answer(f"Качаю аудио {quality}…")
            await self._download_playlist(event, session, mode="audio", quality=quality)
            return

        await event.answer()

    async def _download_playlist(
        self, event, session: PlaylistSession, *, mode: str, quality: str
    ) -> None:
        """Download in batches of 10; progress per file; video albums / audio singles."""
        user_id = session.user_id
        username = None
        try:
            sender = await event.get_sender()
            username = getattr(sender, "username", None)
        except Exception:
            pass

        entries = selected_entries(session)
        if not entries:
            await event.edit("Нечего скачивать — всё исключено.")
            return

        is_admin = user_id in self.download_limiter.ADMIN_USER_IDS
        remaining = self.stats.remaining_playlist_quota(user_id, is_admin=is_admin)
        if remaining is not None and len(entries) > remaining:
            await event.edit(
                f"⚠️ Выбрано {len(entries)}, доступно {remaining} до конца дня (МСК). "
                "Уменьши выбор (исключения) или подожди завтра."
            )
            return

        download_id = str(uuid.uuid4())
        if not await self._check_download_limit(event, user_id, download_id):
            return

        session.downloading = True
        session.cancel_requested = False
        total = len(entries)
        done = 0
        fail = 0
        sent = 0
        caption_kw = self._caption_kwargs(user_id)
        stop_btn = [[Button.inline("⏹ Стоп", data="pl_stop")]]

        def quota_status() -> str:
            if is_admin:
                return ""
            limit = self.stats.effective_playlist_limit(user_id, is_admin=False)
            if limit is None:
                return ""
            used = self.stats.get_playlist_usage(user_id)
            return f" · лимит: {used}/{limit}"

        async def update_progress(text: str) -> None:
            try:
                await event.edit(text, buttons=stop_btn, link_preview=False)
            except Exception:
                try:
                    await event.respond(text, buttons=stop_btn, link_preview=False)
                except Exception:
                    pass

        await update_progress(
            f"⏳ Плейлист **{session.title}**\n"
            f"Готово: **0/{total}** · отправлено: 0{quota_status()}\n"
            f"Режим: {mode} {quality}\n\n"
            "Начинаю…"
        )

        batch: list[tuple[str, dict]] = []
        cancelled = False
        storage_chat_id = self.stats.get_storage_chat_id() if mode == "audio" else None
        use_storage = mode == "audio" and storage_chat_id is not None

        async def flush_batch() -> None:
            nonlocal sent, batch
            if not batch:
                return
            paths = [p for p, _ in batch]
            if use_storage:
                staging: list = []
                try:
                    for path, metadata in batch:
                        msg = await stage_media(
                            self.client,
                            storage_chat_id,
                            path,
                            "audio",
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )
                        staging.append(msg)
                    remaining = [
                        m
                        for m in staging
                        if m is not None and getattr(m, "media", None) is not None
                    ]
                    delivered = 0
                    try:
                        delivered += await copy_messages_to_chat(
                            self.client, event.chat_id, remaining
                        )
                        remaining = []
                    except PartialCopyError as e:
                        delivered += e.sent
                        remaining = remaining[e.sent:]
                        try:
                            delivered += await copy_messages_to_chat(
                                self.client, event.chat_id, remaining
                            )
                            remaining = []
                        except PartialCopyError as e2:
                            delivered += e2.sent
                            remaining = remaining[e2.sent:]
                            for msg in remaining:
                                try:
                                    delivered += await copy_messages_to_chat(
                                        self.client, event.chat_id, [msg]
                                    )
                                except PartialCopyError as e3:
                                    if e3.sent:
                                        delivered += e3.sent
                                    logger.error(
                                        "Playlist track delivery failed after retries: %s",
                                        e3.__cause__,
                                    )
                    if delivered:
                        sent += delivered
                        self.stats.set_user_last_format(user_id, "audio", quality)
                        if not is_admin:
                            self.stats.increment_playlist_usage(user_id, delivered)
                except Exception as e:
                    logger.error(f"Playlist batch send failed: {e}")
                    try:
                        await event.respond(f"⚠️ Не удалось отправить пачку ({len(batch)}): {e!s}")
                    except Exception:
                        pass
                finally:
                    await delete_staging(self.client, storage_chat_id, staging)
                    for path in paths:
                        self._cleanup_download_file(path)
                    batch = []
                return
            try:
                await send_playlist_album(
                    self.client,
                    event.chat_id,
                    batch,
                    mode=mode,
                    bot_username=self.bot_username,
                    **caption_kw,
                )
                sent += len(batch)
                if not is_admin:
                    self.stats.increment_playlist_usage(user_id, len(batch))
                if mode == "audio":
                    self.stats.set_user_last_format(user_id, "audio", quality)
                else:
                    self.stats.set_user_last_format(user_id, "video", quality)
            except Exception as e:
                logger.error(f"Playlist batch send failed: {e}")
                try:
                    await event.respond(f"⚠️ Не удалось отправить пачку ({len(batch)}): {e!s}")
                except Exception:
                    pass
            finally:
                for path in paths:
                    self._cleanup_download_file(path)
                batch = []

        try:
            for i, entry in enumerate(entries, start=1):
                if session.cancel_requested:
                    cancelled = True
                    break

                safe_title = entry.title.replace("[", "(").replace("]", ")")[:70]
                await update_progress(
                    f"⏳ Плейлист **{session.title}**\n"
                    f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                    f"Режим: {mode} {quality}\n\n"
                    f"Сейчас: [{safe_title}]({entry.url})\n"
                    f"({i}/{total})"
                )

                file_path = None
                try:
                    if mode == "audio":
                        file_path, metadata = await download_youtube_audio(entry.url, quality)
                        self.stats.track_audio_download(
                            user_id,
                            quality,
                            username,
                            success=True,
                            source="dm",
                            url=entry.url,
                            title=entry.title or _media_title(metadata),
                        )
                    else:
                        file_path, metadata = await download_youtube_video(entry.url, quality)
                        self.stats.track_video_download(
                            user_id,
                            quality,
                            "youtube",
                            username,
                            success=True,
                            source="dm",
                            url=entry.url,
                            title=entry.title or _media_title(metadata),
                        )
                    batch.append((file_path, metadata))
                    done += 1
                    file_path = None

                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                        f"Режим: {mode} {quality}\n\n"
                        f"✅ Скачан: [{safe_title}]({entry.url})\n"
                        f"В пачке: {len(batch)}/{PLAYLIST_BATCH_SIZE}"
                    )
                except Exception as e:
                    fail += 1
                    logger.error(f"Playlist item failed {entry.url}: {e}")
                    if mode == "audio":
                        self.stats.track_audio_download(
                            user_id,
                            quality,
                            username,
                            success=False,
                            error_message=str(e),
                            source="dm",
                            url=entry.url,
                            title=entry.title,
                        )
                    else:
                        self.stats.track_video_download(
                            user_id,
                            quality,
                            "youtube",
                            username,
                            success=False,
                            error_message=str(e),
                            source="dm",
                            url=entry.url,
                            title=entry.title,
                        )
                    try:
                        await event.respond(
                            f"⚠️ Пропуск {i}/{total}: {entry.title[:60]} — {e!s}"
                        )
                    except Exception:
                        pass
                finally:
                    if file_path:
                        self._cleanup_download_file(file_path)

                if len(batch) >= PLAYLIST_BATCH_SIZE:
                    batch_progress = (
                        f"отправляю пачку {len(batch)} из хранилища…"
                        if use_storage
                        else f"отправляю пачку {len(batch)}…"
                    )
                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · {batch_progress}"
                    )
                    await flush_batch()
                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                        f"Режим: {mode} {quality}"
                    )

                if session.cancel_requested:
                    cancelled = True
                    break

            if batch:
                remainder_progress = (
                    f"отправляю остаток ({len(batch)}) из хранилища…"
                    if use_storage
                    else f"отправляю остаток ({len(batch)})…"
                )
                await update_progress(
                    f"⏳ Плейлист **{session.title}**\n"
                    f"Готово: **{done}/{total}** · {remainder_progress}"
                )
                await flush_batch()

            if cancelled:
                summary = (
                    f"⏹ Остановлено.\n"
                    f"Скачано: {done}/{total} · отправлено: {sent} · ошибок: {fail}"
                )
            else:
                summary = f"✅ Плейлист готов: отправлено {sent}/{total}"
                if fail:
                    summary += f" (ошибок: {fail})"
            try:
                await event.edit(summary)
            except Exception:
                await event.respond(summary)
        finally:
            session.downloading = False
            await self.download_limiter.finish_download(user_id, download_id)
            PLAYLIST_STATES.pop(user_id, None)

    async def _handle_group_link_message(self, event: Message, text: str) -> None:
        """Auto-download a supported link in a group (reply to the link message)."""
        if bool(getattr(event, "out", False)):
            return

        chat_id = int(event.chat_id)
        chat_settings = self.stats.get_chat_settings(chat_id)
        parsed = parse_inline_query(text, default_quality=chat_settings.default_quality)
        if parsed is None:
            return

        if not chat_settings.allows_platform(parsed.platform):
            return

        user_id, username = self._get_user_info(event)
        self._track_user(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        reply_to = int(event.message.id) if event.message is not None else None
        processing_msg = None
        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond(
                    "Произошла ошибка: клиент Telegram недоступен.",
                    reply_to=reply_to,
                )
                return

            action = "audio" if parsed.mode == "audio" else "video"
            async with client.action(event.chat_id, action):
                processing_msg = await event.respond(
                    f"Загрузка ({parsed.description})…",
                    reply_to=reply_to,
                )
                file_path, metadata, media_kind = await self._download_for_inline(parsed)
                caption_kwargs = {
                    "show_bot_caption": chat_settings.show_bot_caption,
                    "show_title": chat_settings.show_title,
                    "reply_to": reply_to,
                }
                if media_kind == "audio":
                    await send_audio_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                elif media_kind == "photo":
                    await send_image_content(
                        event,
                        file_path,
                        self.bot_username,
                        metadata=metadata,
                        **caption_kwargs,
                    )
                else:
                    await send_video_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                self._track_parsed_download(
                    parsed,
                    user_id,
                    username,
                    success=True,
                    source="group",
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"Group download failed for {parsed.url}: {e}")
            self._track_parsed_download(
                parsed,
                user_id,
                username,
                success=False,
                error_message=str(e),
                source="group",
            )
            try:
                await event.respond(
                    f"❌ Не удалось загрузить: {e!s}",
                    reply_to=reply_to,
                )
            except Exception as send_error:
                logger.error(f"Failed to send group error reply: {send_error}")
        finally:
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_tiktok(self, event: Message, url: str):
        """Handle TikTok video download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        # Check download limit
        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка TikTok видео... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading TikTok video: {url}")

                    file_path, metadata = await download_tiktok_video(url)
                    logger.info(f"TikTok video downloaded successfully: {file_path}")

                    await send_video_content(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    # Track successful TikTok download
                    self.stats.track_tiktok_download(
                        user_id,
                        username,
                        success=True,
                        url=url,
                        title=_media_title(metadata),
                    )

                except Exception as e:
                    logger.error(f"Error sending TikTok video: {e}")
                    # Track failed TikTok download
                    self.stats.track_tiktok_download(
                        user_id,
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(f"Произошла ошибка при обработке TikTok видео: {e!s}")
        finally:
            # Always release the download slot
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _show_content_type_selection(self, event: Message, url: str):
        """Show content type selection buttons for YouTube (+ last format repeat)."""
        token = self._store_callback_url(url)
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{token}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{token}"),
            ]
        ]
        user_id = cast("int | None", event.sender_id)
        if user_id is not None:
            settings = self.stats.get_user_settings(user_id)
            if settings.last_mode and settings.last_quality:
                if settings.last_mode == "audio":
                    label = f"🔄 Аудио {settings.last_quality}"
                else:
                    label = f"🔄 Видео {settings.last_quality}"
                buttons.append([Button.inline(label, data=f"content_repeat_{token}")])
        await event.respond("Выберите тип контента для загрузки:", buttons=buttons)

    async def _handle_youtube_shorts(self, event: Message, url: str):
        """Handle YouTube Shorts download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка YouTube Short... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading YouTube Short: {url}")

                    file_path, metadata = await download_youtube_video(url, quality="best")
                    logger.info(f"YouTube Short downloaded successfully: {file_path}")

                    await send_video_content(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_video_download(
                        user_id,
                        "auto",
                        "youtube_shorts",
                        username,
                        success=True,
                        url=url,
                        title=_media_title(metadata),
                    )

                except Exception as e:
                    logger.error(f"Error sending YouTube Short: {e}")
                    self.stats.track_video_download(
                        user_id,
                        "auto",
                        "youtube_shorts",
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(f"Произошла ошибка при обработке YouTube Short: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_select_callback(self, event, data: str):
        """Handle video selection from search results."""
        token = data[7:]  # Remove 'select_' prefix
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого результата больше недоступна. Повторите поиск.")
            return
        CALLBACK_URLS.pop(token, None)
        await self._show_content_type_selection(event, url)

    async def _handle_content_callback(self, event, data: str):
        """Handle content type selection (video/audio/repeat last)."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        content_type, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        if content_type == "repeat":
            user_id = cast("int | None", event.sender_id)
            if user_id is None:
                await event.answer("Не удалось определить пользователя.", alert=True)
                return
            settings = self.stats.get_user_settings(user_id)
            if not settings.last_mode or not settings.last_quality:
                await event.answer("Нет сохранённого формата — выберите вручную.", alert=True)
                return
            mode = settings.last_mode
            quality = settings.last_quality
            await event.answer(
                f"Повтор: {'аудио' if mode == 'audio' else 'видео'} {quality}..."
            )
            try:
                if mode == "audio":
                    await self._download_and_send_audio(event, url, quality)
                else:
                    await self._download_and_send_video(event, url, quality)
            finally:
                CALLBACK_URLS.pop(token, None)
            return

        if content_type == "video":
            await self._show_video_quality_selection(event, token)
        elif content_type == "audio":
            await self._show_audio_quality_selection(event, token)

    async def _show_video_quality_selection(self, event, token: str):
        """Show video quality selection buttons."""
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        await event.answer("Проверка доступных форматов...")
        logger.info(f"Getting available formats for: {url}")

        available_heights = await get_available_formats(url)
        logger.info(f"Available heights: {available_heights}")

        buttons = []
        row = []

        for height in available_heights:
            # Create label based on height
            if height >= 2160:
                label = f"{height}p 4K"
            elif height >= 1440:
                label = f"{height}p 2K"
            elif height >= 720:
                label = f"{height}p HD"
            else:
                label = f"{height}p"

            quality_id = f"{height}p"
            row.append(Button.inline(label, data=f"quality_{quality_id}_{token}"))

            # Two buttons per row
            if len(row) == 2:
                buttons.append(row)
                row = []

        # Add remaining buttons
        if row:
            buttons.append(row)

        if not buttons:
            logger.warning(f"No buttons created for available heights: {available_heights}")
            await event.edit(
                "К сожалению, для этого видео нет доступных форматов. Попробуйте другое видео."
            )
            return

        await event.edit("Выберите качество видео:", buttons=buttons)

    async def _show_audio_quality_selection(self, event, token: str):
        """Show audio quality selection buttons."""
        buttons = [
            [
                Button.inline("Высокое качество", data=f"audio_high_{token}"),
                Button.inline("Среднее качество", data=f"audio_medium_{token}"),
            ],
            [Button.inline("Низкое качество", data=f"audio_low_{token}")],
        ]
        await event.edit("Выберите качество аудио:", buttons=buttons)

    async def _handle_quality_callback(self, event, data: str):
        """Handle video quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка видео в качестве {quality}...")

        try:
            await self._download_and_send_video(event, url, quality)
        finally:
            CALLBACK_URLS.pop(token, None)

    async def _handle_audio_callback(self, event, data: str):
        """Handle audio quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка аудио в качестве {quality}...")

        try:
            await self._download_and_send_audio(event, url, quality)
        finally:
            CALLBACK_URLS.pop(token, None)

    async def _download_and_send_video(self, event, url: str, quality: str):
        """Download and send YouTube video."""

        def track_video(
            user_id,
            quality,
            username,
            success,
            error_message=None,
            url=None,
            title=None,
        ):
            self.stats.track_video_download(
                user_id,
                quality,
                "youtube",
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )
            if success and not bool(getattr(event, "is_group", False)):
                try:
                    self.stats.set_user_last_format(user_id, "video", quality)
                except Exception as e:
                    logger.error(f"Failed to save last format: {e}")

        await self._download_and_send_content(
            event=event,
            url=url,
            quality=quality,
            content_type="видео",
            download_func=download_youtube_video,
            send_func=send_video_content,
            track_func=track_video,
            action="video",
        )

    async def _download_and_send_audio(self, event, url: str, quality: str):
        """Download and send YouTube audio."""

        def track_audio(
            user_id,
            quality,
            username,
            success=True,
            error_message=None,
            url=None,
            title=None,
        ):
            self.stats.track_audio_download(
                user_id,
                quality,
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )
            if success and not bool(getattr(event, "is_group", False)):
                try:
                    self.stats.set_user_last_format(user_id, "audio", quality)
                except Exception as e:
                    logger.error(f"Failed to save last format: {e}")

        await self._download_and_send_content(
            event=event,
            url=url,
            quality=quality,
            content_type="аудио",
            download_func=download_youtube_audio,
            send_func=send_audio_content,
            track_func=track_audio,
            action="audio",
        )

    async def _handle_stats_callback(self, event, data: str):
        """Handle statistics view callback — send infographic image."""
        period = data.split("_")[1]  # Extract period (day, month, all)

        await event.answer("Рисую инфографику...")

        try:
            stats = self.stats.get_statistics(period)
            stats["total_groups"] = await self._count_bot_groups()
            period_names = {"day": "за день", "month": "за месяц", "all": "за всё время"}
            period_name = period_names.get(period, period)

            image_path = await get_stats_image(stats, period)

            total = int(stats.get("total_downloads") or 0)
            ok = int(stats.get("successful_downloads") or 0)
            success_pct = round(100 * ok / total) if total else 0
            by_source = stats.get("by_source") or {}
            caption = (
                f"📊 Komuzik {period_name}\n"
                f"👥 {stats.get('total_users', 0)} · "
                f"💬 {stats.get('total_groups', 0)} · "
                f"📥 {total} · "
                f"✅ {success_pct}%\n"
                f"ЛС {by_source.get('dm', 0)} · "
                f"Inline {by_source.get('inline', 0)} · "
                f"Группы {by_source.get('group', 0)}"
            )

            buttons = [
                [
                    Button.inline("📊 За день", data="stats_day"),
                    Button.inline("📅 За месяц", data="stats_month"),
                ],
                [Button.inline("📈 За все время", data="stats_all")],
            ]

            # Prefer editing current message into a photo; fall back to new message.
            try:
                await event.edit(caption, file=str(image_path), buttons=buttons)
            except Exception:
                await event.respond(caption, file=str(image_path), buttons=buttons)
                try:
                    await event.delete()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            await event.edit(f"Произошла ошибка при получении статистики: {e!s}")

    async def _handle_twitter(self, event: Message, url: str):
        """Handle Twitter/X video and photo download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка с Twitter... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading Twitter content: {url}")

                    file_path, metadata = await download_twitter_video(url)
                    logger.info(f"Twitter content downloaded successfully: {file_path}")

                    # Send appropriate content type
                    caption_kw = self._caption_kwargs(user_id)
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
                            event,
                            file_path,
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )

                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_tiktok_download(
                        user_id,
                        username,
                        success=True,
                        url=url,
                        title=_media_title(metadata),
                    )

                except Exception as e:
                    logger.error(f"Error sending Twitter content: {e}")
                    self.stats.track_tiktok_download(
                        user_id,
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(f"Произошла ошибка при обработке контента: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_pinterest(self, event: Message, url: str):
        """Handle Pinterest video and photo download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "document"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка с Pinterest... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading Pinterest content: {url}")

                    file_path, metadata = await download_pinterest_content(url)
                    logger.info(f"Pinterest content downloaded successfully: {file_path}")

                    caption_kw = self._caption_kwargs(user_id)
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
                            event,
                            file_path,
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )

                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_pinterest_download(
                        user_id,
                        username,
                        success=True,
                        url=url,
                        title=_media_title(metadata),
                    )

                except Exception as e:
                    logger.error(f"Error sending Pinterest content: {e}")
                    self.stats.track_pinterest_download(
                        user_id,
                        username,
                        success=False,
                        error_message=str(e),
                        url=url,
                    )
                    await event.respond(f"Произошла ошибка при обработке Pinterest: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def post_handler(self, event: Message):
        """Handle /post command for admin broadcast."""
        user_id, _username = self._get_user_info(event)

        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            await event.respond("❌ У вас нет доступа к этой команде.")
            return

        message_obj = cast("Message", event.message)

        # Check if it's a reply
        if not message_obj or not getattr(message_obj, "is_reply", False):
            await event.respond(
                "ℹ️ Используйте команду /post в ответе на сообщение, которое нужно переслать всем пользователям."
            )
            return

        try:
            reply_msg = await message_obj.get_reply_message()

            processing_msg = await event.respond("📢 Отправляю сообщение всем пользователям...")

            # Get all users from database
            users = self.stats.get_all_users()
            sent_count = 0
            failed_count = 0

            for user_id_target, _ in users:
                try:
                    await self.client.send_message(user_id_target, reply_msg)
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send message to user {user_id_target}: {e}")
                    failed_count += 1

            result = f"✅ Сообщение отправлено {sent_count} пользователям"
            if failed_count > 0:
                result += f"\n⚠️ Не удалось отправить {failed_count} пользователям"

            if processing_msg is not None:
                await processing_msg.edit(result)

        except Exception as e:
            logger.error(f"Error in post handler: {e}")
            await event.respond(f"Произошла ошибка: {e!s}")

    def _is_bot_admin(self, user_id: int) -> bool:
        return user_id in self.download_limiter.ADMIN_USER_IDS

    async def _reject_if_banned(
        self, event: Any, user_id: int, *, chat_is_group: bool
    ) -> bool:
        """Return True if the handler should stop (user is banned)."""
        if self._is_bot_admin(user_id):
            return False
        reason = self.stats.get_ban(user_id)
        if reason is None:
            return False
        if chat_is_group:
            return True
        msg = format_ban_message(reason)
        try:
            if hasattr(event, "respond"):
                await event.respond(msg)
            elif hasattr(event, "edit"):
                await event.edit(msg)
            else:
                logger.warning("Cannot notify banned user: unsupported event type")
        except Exception as e:
            logger.error(f"Failed to send ban message to {user_id}: {e}")
        return True

    def _parse_positive_int(self, text: str | None) -> int | None:
        if text is None:
            return None
        raw = text.strip()
        if not re.fullmatch(r"\d+", raw):
            return None
        value = int(raw)
        if value < 1:
            return None
        return value

    def _format_admin_panel(self) -> str:
        concurrent = self.stats.get_max_concurrent(
            default=self.download_limiter._yaml_concurrent
        )
        playlist_limit = self.stats.get_playlist_daily_limit()
        ban_count = self.stats.count_bans()
        return (
            "🛠 **Админ-панель**\n\n"
            f"Одновременных загрузок: **{concurrent}**\n"
            f"Плейлист / сутки (глобально): **{playlist_limit}**\n"
            f"Блокировок: **{ban_count}**\n\n"
            "Персональный лимит: `/setuserlimit <айди> <число>`\n"
            "Сброс лимита: `/unsetuserlimit <айди>`\n"
            "Блок: `/ban <айди> причина` · `/unban <айди>`"
        )

    def _admin_panel_buttons(self) -> list:
        return [
            [
                Button.inline("⚙️ Одновременные", data="admin_set_concurrent"),
                Button.inline("📺 Лимит плейлиста", data="admin_set_playlist"),
            ],
            [Button.inline("👥 Пользователи", data="admin_users_known_p_0")],
        ]

    def _admin_user_profile_link(self, user_id: int) -> str:
        return f"[открыть профиль](tg://user?id={user_id})"

    def _truncate_button_label(self, label: str, max_len: int = 60) -> str:
        if len(label) <= max_len:
            return label
        return label[: max_len - 3] + "..."

    def _format_admin_users_page(
        self, page: int, *, kind: str = ADMIN_USERS_KIND_KNOWN
    ) -> tuple[str, list]:
        if kind not in {ADMIN_USERS_KIND_KNOWN, ADMIN_USERS_KIND_ANON}:
            kind = ADMIN_USERS_KIND_KNOWN

        offset = page * ADMIN_USERS_PAGE_SIZE
        users = self.stats.list_users(offset=offset, limit=ADMIN_USERS_PAGE_SIZE, kind=kind)
        total = self.stats.count_users(kind=kind)
        known_total = self.stats.count_users(kind=ADMIN_USERS_KIND_KNOWN)
        anon_total = self.stats.count_users(kind=ADMIN_USERS_KIND_ANON)

        tab_title = "Известные" if kind == ADMIN_USERS_KIND_KNOWN else "Анонимы"
        if total == 0:
            lines = [
                f"👥 **Пользователи → {tab_title}**\n",
                "Список пуст.",
            ]
        else:
            end = offset + len(users)
            lines = [f"👥 **Пользователи → {tab_title}** ({offset + 1}–{end} из {total})\n"]
            for user in users:
                lines.append(f"• {format_user_label(user)}")

        known_mark = "✅ " if kind == ADMIN_USERS_KIND_KNOWN else ""
        anon_mark = "✅ " if kind == ADMIN_USERS_KIND_ANON else ""
        buttons: list[list] = [
            [
                Button.inline(
                    f"{known_mark}Известные ({known_total})",
                    data="admin_users_known_p_0",
                ),
                Button.inline(
                    f"{anon_mark}Анонимы ({anon_total})",
                    data="admin_users_anon_p_0",
                ),
            ]
        ]

        for user in users:
            btn_label = self._truncate_button_label(format_user_label(user))
            buttons.append([Button.inline(btn_label, data=f"admin_user_{user['id']}")])

        nav: list = []
        if page > 0:
            nav.append(Button.inline("◀️", data=f"admin_users_{kind}_p_{page - 1}"))
        if total > 0 and (offset + len(users)) < total:
            nav.append(Button.inline("▶️", data=f"admin_users_{kind}_p_{page + 1}"))
        if nav:
            buttons.append(nav)

        return "\n".join(lines), buttons

    def _format_admin_history_page(self, target_user_id: int, page: int) -> tuple[str | None, list]:
        user = self.stats.get_user(target_user_id)
        total_raw = self.stats.count_user_downloads(target_user_id)
        total = min(total_raw, ADMIN_HISTORY_MAX)

        if total == 0 and user is None:
            return None, []

        max_page = max(0, (total - 1) // ADMIN_HISTORY_PAGE_SIZE) if total > 0 else 0
        page = min(max(page, 0), max_page)
        offset = page * ADMIN_HISTORY_PAGE_SIZE
        remaining = max(0, total - offset)
        limit = min(ADMIN_HISTORY_PAGE_SIZE, remaining)
        downloads = (
            self.stats.list_user_downloads(target_user_id, offset=offset, limit=limit)
            if limit > 0
            else []
        )

        user_record = user or {"id": target_user_id}
        back_kind = (
            ADMIN_USERS_KIND_ANON
            if format_user_label(user_record) == "аноним"
            else ADMIN_USERS_KIND_KNOWN
        )
        lines = [
            "📥 **История загрузок**\n",
            f"👤 {format_user_label(user_record)}",
            f"Номер: `{target_user_id}`",
            self._admin_user_profile_link(target_user_id),
        ]

        ban_reason = self.stats.get_ban(target_user_id)
        if ban_reason:
            lines.append(f"🚫 **Заблокирован:** {ban_reason}")

        if total == 0:
            lines.append("\nНет загрузок.")
        else:
            lines.append(f"\nЗаписи {offset + 1}–{offset + len(downloads)} из {total}:\n")
            lines.extend(format_download_history_line(row) for row in downloads)

        buttons: list[list] = []
        nav: list = []
        if page > 0:
            nav.append(
                Button.inline("◀️", data=f"admin_hist_{target_user_id}_p_{page - 1}")
            )
        if offset + len(downloads) < total:
            nav.append(
                Button.inline("▶️", data=f"admin_hist_{target_user_id}_p_{page + 1}")
            )
        if nav:
            buttons.append(nav)
        buttons.append(
            [Button.inline("← К списку", data=f"admin_users_{back_kind}_p_0")]
        )

        return "\n".join(lines), buttons

    async def _send_admin_users_page(
        self, event, page: int, *, kind: str = ADMIN_USERS_KIND_KNOWN, edit: bool = False
    ) -> None:
        text, buttons = self._format_admin_users_page(page, kind=kind)
        kwargs: dict[str, Any] = {"link_preview": False}
        if buttons:
            kwargs["buttons"] = buttons
        if edit:
            await event.edit(text, **kwargs)
        else:
            await event.respond(text, **kwargs)

    async def _send_admin_history_page(
        self, event, target_user_id: int, page: int, *, edit: bool = False
    ) -> bool:
        text, buttons = self._format_admin_history_page(target_user_id, page)
        if text is None:
            return False
        kwargs: dict[str, Any] = {"link_preview": False}
        if buttons:
            kwargs["buttons"] = buttons
        if edit:
            await event.edit(text, **kwargs)
        else:
            await event.respond(text, **kwargs)
        return True

    async def users_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        await self._send_admin_users_page(event, 0, kind=ADMIN_USERS_KIND_KNOWN)

    async def user_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None) or ""
        match = re.match(r"^/user(?:@\w+)?(?:\s+(.+))?", text)
        target_id = self._parse_positive_int((match.group(1) or "").strip() if match else None)
        if target_id is None:
            await event.respond("Пример: `/user 123456789`")
            return
        if not await self._send_admin_history_page(event, target_id, 0):
            await event.respond("Нет данных")

    async def admin_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        await event.respond(
            self._format_admin_panel(),
            buttons=self._admin_panel_buttons(),
        )

    async def ban_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None) or ""
        match = re.match(r"^/ban(?:@\w+)?\s+(\d+)\s+(.+)", text, re.DOTALL)
        if not match:
            await event.respond("Пример: `/ban 123456789 причина`")
            return
        target_id = int(match.group(1))
        reason = match.group(2).strip()
        if not reason:
            await event.respond("Пример: `/ban 123456789 причина`")
            return
        if target_id in self.download_limiter.ADMIN_USER_IDS:
            await event.respond("❌ Нельзя заблокировать администратора бота.")
            return
        self.stats.ban_user(target_id, reason, banned_by=user_id)
        await event.respond(f"✅ Пользователь `{target_id}` заблокирован.\nПричина: {reason}")

    async def unban_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None) or ""
        match = re.match(r"^/unban(?:@\w+)?\s+(\d+)", text)
        if not match:
            await event.respond("Пример: `/unban 123456789`")
            return
        target_id = int(match.group(1))
        if self.stats.unban_user(target_id):
            await event.respond(f"✅ Пользователь `{target_id}` разблокирован.")
        else:
            await event.respond(f"ℹ️ Пользователь `{target_id}` не был в блокировке.")

    async def setconcurrent_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None)
        match = re.match(r"^/setconcurrent(?:@\w+)?(?:\s+(.+))?", text or "")
        n = self._parse_positive_int(match.group(1) if match else None)
        if n is None:
            await event.respond("Пример: `/setconcurrent 3` (число ≥ 1)")
            return
        self.stats.set_max_concurrent(n)
        _ = self.download_limiter.get_max_per_user()
        await event.respond(f"✅ Одновременных загрузок: **{n}**")

    async def setplaylistlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None)
        match = re.match(r"^/setplaylistlimit(?:@\w+)?(?:\s+(.+))?", text or "")
        n = self._parse_positive_int(match.group(1) if match else None)
        if n is None:
            await event.respond("Пример: `/setplaylistlimit 50` (число ≥ 1)")
            return
        self.stats.set_playlist_daily_limit(n)
        await event.respond(f"✅ Плейлист / сутки (глобально): **{n}**")

    async def setuserlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None)
        match = re.match(r"^/setuserlimit(?:@\w+)?(?:\s+(.+))?", text or "")
        args = (match.group(1) or "").strip() if match else ""
        parts = args.split()
        if len(parts) != 2:
            await event.respond("Пример: `/setuserlimit 123456789 100` (число ≥ 1)")
            return
        target_id = self._parse_positive_int(parts[0])
        n = self._parse_positive_int(parts[1])
        if target_id is None or n is None:
            await event.respond("Пример: `/setuserlimit 123456789 100` (число ≥ 1)")
            return
        self.stats.set_user_playlist_limit(target_id, n)
        limit = self.stats.get_user_playlist_limit(target_id)
        await event.respond(f"✅ Персональный лимит для `{target_id}`: **{limit}**")

    async def unsetuserlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None)
        match = re.match(r"^/unsetuserlimit(?:@\w+)?(?:\s+(.+))?", text or "")
        target_id = self._parse_positive_int((match.group(1) or "").strip() if match else None)
        if target_id is None:
            await event.respond("Пример: `/unsetuserlimit 123456789`")
            return
        self.stats.clear_user_playlist_limit(target_id)
        await event.respond(f"✅ Персональный лимит для `{target_id}` сброшен.")

    async def _maybe_handle_admin_pending(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """Apply pending admin limit edit when admin sends a pure integer in DM."""
        if not self._is_bot_admin(user_id):
            return False
        pending = ADMIN_PENDING.get(user_id)
        if pending is None:
            return False
        if bool(getattr(event, "is_group", False)):
            return False

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if not isinstance(text, str):
            return False
        stripped = text.strip()
        if stripped.startswith("/"):
            ADMIN_PENDING.pop(user_id, None)
            return False
        if not re.fullmatch(r"\d+", stripped):
            return False

        n = int(stripped)
        if n < 1:
            await event.respond("❌ Число должно быть ≥ 1.")
            return True

        ADMIN_PENDING.pop(user_id, None)
        if pending == "concurrent":
            self.stats.set_max_concurrent(n)
            _ = self.download_limiter.get_max_per_user()
            await event.respond(f"✅ Одновременных загрузок: **{n}**")
        elif pending == "playlist":
            self.stats.set_playlist_daily_limit(n)
            await event.respond(f"✅ Плейлист / сутки (глобально): **{n}**")
        return True

    async def setstorage_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return
        if not event.is_group:
            await event.respond("⚠️ Команду нужно вызвать в группе-хранилище.")
            return
        chat_id = event.chat_id
        probe = await event.respond("⏳ Проверяю права…")
        try:
            await self.client.delete_messages(chat_id, [probe.id])
        except Exception as e:
            try:
                await self.client.delete_messages(chat_id, [probe.id])
            except Exception:
                pass
            await event.respond(
                f"❌ Не могу удалять сообщения в этой группе ({e!s}). "
                "Дай боту право удалять сообщения и повтори /setstorage."
            )
            return
        self.stats.set_storage_chat_id(int(chat_id))
        await event.respond(f"✅ Эта группа — хранилище бота.\nНомер чата: `{chat_id}`")

    async def unsetstorage_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return
        prev = self.stats.get_storage_chat_id()
        self.stats.clear_storage_chat_id()
        if prev is None:
            await event.respond("ℹ️ Хранилище и так не задано.")
        else:
            await event.respond(f"✅ Хранилище сброшено (было `{prev}`).")

    async def report_handler(self, event: Message):
        """Handle /report command for user reports."""
        user_id, username = self._get_user_info(event)

        REPORT_STATES[user_id] = True

        await event.respond(
            "📝 Опишите проблему (или отправьте /cancel для отмены):",
            buttons=[[Button.inline("❌ Отмена", data="report_cancel")]],
        )

    async def _maybe_handle_report_reply(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """If admin replies to a report message, copy the reply to the reporter.

        Returns True when the event was handled as a report reply.
        """
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return False
        if message_obj is None:
            return False

        reply = getattr(message_obj, "reply_to", None)
        reply_msg_id = getattr(reply, "reply_to_msg_id", None) if reply is not None else None
        if not isinstance(reply_msg_id, int):
            return False

        thread = self.stats.get_report_thread_by_admin_msg(user_id, reply_msg_id)
        if thread is None:
            return False

        reporter_id, user_report_msg_id = thread
        try:
            await self.client.send_message(
                reporter_id,
                message_obj,
                reply_to=user_report_msg_id,
            )
            await event.respond("✅ Ответ отправлен пользователю.")
        except Exception as e:
            logger.error(f"Failed to deliver report reply to {reporter_id}: {e}")
            await event.respond(f"❌ Не удалось отправить ответ: {e!s}")
        return True

    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode("utf-8")
        user_id = cast("int | None", event.sender_id)

        # Dummy keyboard on inline placeholder — needed for inline_message_id
        if data == "noop":
            await event.answer()
            return

        # Handle report cancel (allowlist for banned users)
        if data == "report_cancel":
            if user_id is None:
                await event.edit("❌ Не удалось определить пользователя.")
                return
            REPORT_STATES.pop(user_id, None)
            await event.edit("❌ Отправка отчета отменена.")
            return

        if user_id is not None and await self._reject_if_banned(
            event, user_id, chat_is_group=not bool(getattr(event, "is_private", True))
        ):
            await event.answer()
            return

        if data.startswith("settings_"):
            await self._handle_settings_callback(event, data)
            return

        if data.startswith("chatset_"):
            await self._handle_chat_settings_callback(event, data)
            return

        if data.startswith("pl_"):
            await self._handle_playlist_callback(event, data)
            return

        if data in {"admin_set_concurrent", "admin_set_playlist"}:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer("Нет доступа.", alert=True)
                return
            ADMIN_PENDING[user_id] = "concurrent" if data == "admin_set_concurrent" else "playlist"
            label = (
                "одновременных загрузок"
                if data == "admin_set_concurrent"
                else "плейлист / сутки"
            )
            await event.answer()
            await event.respond(f"Введите новое значение ({label}), целое число ≥ 1:")
            return

        users_page_match = re.fullmatch(r"admin_users_(known|anon)_p_(\d+)", data)
        if users_page_match or data.startswith("admin_users_p_"):
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer("Нет доступа.", alert=True)
                return
            if users_page_match:
                kind = users_page_match.group(1)
                page = int(users_page_match.group(2))
            else:
                # legacy callback from older messages
                kind = ADMIN_USERS_KIND_KNOWN
                page = int(data.removeprefix("admin_users_p_"))
            text, buttons = self._format_admin_users_page(page, kind=kind)
            kwargs: dict[str, Any] = {"link_preview": False}
            if buttons:
                kwargs["buttons"] = buttons
            await event.edit(text, **kwargs)
            await event.answer()
            return

        admin_user_match = re.fullmatch(r"admin_user_(\d+)", data)
        if admin_user_match:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer("Нет доступа.", alert=True)
                return
            target_id = int(admin_user_match.group(1))
            if not await self._send_admin_history_page(event, target_id, 0, edit=True):
                await event.answer("Нет данных", alert=True)
                return
            await event.answer()
            return

        admin_hist_match = re.fullmatch(r"admin_hist_(\d+)_p_(\d+)", data)
        if admin_hist_match:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer("Нет доступа.", alert=True)
                return
            target_id = int(admin_hist_match.group(1))
            page = int(admin_hist_match.group(2))
            if not await self._send_admin_history_page(event, target_id, page, edit=True):
                await event.answer("Нет данных", alert=True)
                return
            await event.answer()
            return

        # Route callbacks using dictionary
        handlers: dict[str, CallbackHandler] = {
            "select_": self._handle_select_callback,
            "content_": self._handle_content_callback,
            "quality_": self._handle_quality_callback,
            "audio_": self._handle_audio_callback,
            "stats_": self._handle_stats_callback,
        }

        for prefix, handler in handlers.items():
            if data.startswith(prefix):
                await handler(event, data)
                return

        logger.warning(f"Unknown callback data: {data}")

    async def _handle_settings_callback(self, event, data: str):
        """Toggle personal settings / open quality screen."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            await event.answer("Не удалось определить пользователя.", alert=True)
            return

        if data == "settings_quality":
            settings = self.stats.get_user_settings(user_id)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="user"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="settings_q_"),
            )
            await event.answer()
            return

        if data == "settings_back":
            settings = self.stats.get_user_settings(user_id)
            await event.edit(
                self._format_settings_message(settings),
                buttons=self._settings_buttons(settings),
            )
            await event.answer()
            return

        if data.startswith("settings_q_"):
            quality = data.removeprefix("settings_q_")
            settings = self.stats.set_user_default_quality(user_id, quality)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="user"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="settings_q_"),
            )
            await event.answer(f"Качество: {settings.default_quality}")
            return

        key = "show_bot_caption" if data == "settings_bot" else None
        if data == "settings_title":
            key = "show_title"
        if key is None:
            await event.answer()
            return

        settings = self.stats.toggle_user_setting(user_id, key)
        await event.edit(
            self._format_settings_message(settings),
            buttons=self._settings_buttons(settings),
        )
        await event.answer("Сохранено")

    async def _handle_chat_settings_callback(self, event, data: str):
        """Toggle group chat settings (admins only)."""
        if not await self._is_chat_admin(event):
            await event.answer("Только администраторы могут менять настройки.", alert=True)
            return

        chat_id = int(event.chat_id)

        if data == "chatset_quality":
            settings = self.stats.get_chat_settings(chat_id)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="chat"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="chatset_q_"),
            )
            await event.answer()
            return

        if data == "chatset_back":
            settings = self.stats.get_chat_settings(chat_id)
            await event.edit(
                self._format_chat_settings_message(settings),
                buttons=self._chat_settings_buttons(settings),
            )
            await event.answer()
            return

        if data.startswith("chatset_q_"):
            quality = data.removeprefix("chatset_q_")
            settings = self.stats.set_chat_default_quality(chat_id, quality)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="chat"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="chatset_q_"),
            )
            await event.answer(f"Качество: {settings.default_quality}")
            return

        key = data.removeprefix("chatset_")
        if key not in {
            "allow_youtube",
            "allow_tiktok",
            "allow_twitter",
            "allow_pinterest",
            "show_bot_caption",
            "show_title",
        }:
            await event.answer()
            return

        settings = self.stats.toggle_chat_setting(chat_id, key)
        await event.edit(
            self._format_chat_settings_message(settings),
            buttons=self._chat_settings_buttons(settings),
        )
        await event.answer("Сохранено")

    async def inline_query_handler(self, event):
        """Answer inline queries with a placeholder article for supported links."""
        query_text = event.text or ""
        user_id = cast("int | None", event.sender_id)
        if user_id is not None and not self._is_bot_admin(user_id):
            reason = self.stats.get_ban(user_id)
            if reason is not None:
                builder = event.builder
                blocked = await builder.article(
                    title="🚫 Доступ ограничен",
                    description=reason[:64],
                    text=format_ban_message(reason),
                    id="banned",
                )
                await event.answer([blocked], cache_time=0)
                return

        default_quality = "720p"
        if user_id is not None:
            default_quality = self.stats.get_user_settings(user_id).default_quality
        parsed = parse_inline_query(query_text, default_quality=default_quality)
        builder = event.builder

        if not parsed:
            hint = await builder.article(
                title="Кинь ссылку YouTube / TikTok / X / Pinterest",
                description="Для YouTube: music или 360/480/720/1080 + ссылка",
                text=(
                    "Отправьте ссылку после @бота.\n"
                    "YouTube: `music` / `480` + ссылка. Остальные платформы — просто ссылка.\n"
                    "Сначала напишите боту /start в ЛС."
                ),
                buttons=[Button.inline("⏳", b"noop")],
                id="hint",
            )
            await event.answer([hint], cache_time=0)
            return

        title = await get_media_title(parsed.url, fallback=parsed.description)
        token = uuid.uuid4().hex[:16]
        INLINE_JOBS[token] = parsed

        result = await builder.article(
            title=title,
            description=parsed.description,
            text="⏳ Загрузка…",
            buttons=[Button.inline("⏳", b"noop")],
            id=token,
        )
        await event.answer([result], cache_time=0)

    async def chosen_inline_handler(self, event: UpdateBotInlineSend):
        """Download media after user picks an inline result and edit the via-message."""
        token = event.id
        inline_msg_id = event.msg_id
        user_id = event.user_id

        if not self._is_bot_admin(user_id):
            reason = self.stats.get_ban(user_id)
            if reason is not None and inline_msg_id is not None:
                await edit_inline_text(
                    self.client, inline_msg_id, format_ban_message(reason)
                )
                return

        parsed = INLINE_JOBS.pop(token, None)

        if parsed is None:
            logger.warning(f"Unknown inline job token: {token}")
            return

        if inline_msg_id is None:
            logger.warning("Chosen inline result without msg_id (enable /setinlinefeedback)")
            return

        username = None
        display_name = None
        try:
            user = await self.client.get_entity(user_id)
            username = getattr(user, "username", None)
            display_name = _entity_display_name(user)
        except Exception:
            pass

        self.stats.track_user(user_id, username, display_name=display_name)

        download_id = str(uuid.uuid4())
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await edit_inline_text(
                self.client,
                inline_msg_id,
                f"⚠️ Уже есть активная загрузка ({active_count}/"
                f"{self.download_limiter.MAX_DOWNLOADS_PER_USER}). Подождите.",
            )
            return

        file_path = None
        try:
            await edit_inline_text(self.client, inline_msg_id, "⏳ Загрузка…")
            file_path, metadata, media_kind = await self._download_for_inline(parsed)
            storage_chat_id = self.stats.get_storage_chat_id()
            if storage_chat_id is not None:
                staging_msg = await stage_media(
                    self.client,
                    storage_chat_id,
                    file_path,
                    media_kind,
                    metadata,
                    self.bot_username,
                    **self._caption_kwargs(user_id),
                )
                try:
                    await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
                    self._track_inline_download(
                        parsed, user_id, username, success=True, metadata=metadata
                    )
                finally:
                    await delete_staging(self.client, storage_chat_id, [staging_msg])
            else:
                try:
                    staging_msg = await stage_media_to_user(
                        self.client,
                        user_id,
                        file_path,
                        media_kind,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                except Exception as e:
                    if is_pm_unavailable_error(e):
                        await edit_inline_text(self.client, inline_msg_id, PM_UNAVAILABLE_MESSAGE)
                        self._track_inline_download(
                            parsed,
                            user_id,
                            username,
                            success=False,
                            error_message=str(e),
                        )
                        return
                    raise

                await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
                await delete_staging_message(self.client, user_id, staging_msg)
                self._track_inline_download(
                    parsed, user_id, username, success=True, metadata=metadata
                )

        except Exception as e:
            logger.error(f"Inline download failed for {parsed.url}: {e}")
            try:
                await edit_inline_text(
                    self.client,
                    inline_msg_id,
                    f"❌ Не удалось загрузить: {e!s}",
                )
            except Exception as edit_error:
                logger.error(f"Failed to edit inline error text: {edit_error}")
            self._track_inline_download(
                parsed, user_id, username, success=False, error_message=str(e)
            )
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _download_for_inline(self, parsed: ParsedInlineQuery) -> tuple[str, dict, str]:
        """Download media for an inline job. Returns (path, metadata, media_kind)."""
        if parsed.platform == "youtube" and parsed.mode == "audio":
            file_path, metadata = await download_youtube_audio(parsed.url, parsed.quality)
            return file_path, metadata, "audio"

        if parsed.platform in {"youtube", "youtube_shorts"}:
            quality = parsed.quality if parsed.platform == "youtube" else "best"
            file_path, metadata = await download_youtube_video(parsed.url, quality)
            return file_path, metadata, "video"

        if parsed.platform == "tiktok":
            file_path, metadata = await download_tiktok_video(parsed.url)
            return file_path, metadata, "video"

        if parsed.platform == "twitter":
            file_path, metadata = await download_twitter_video(parsed.url)
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        if parsed.platform == "pinterest":
            file_path, metadata = await download_pinterest_content(parsed.url)
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        raise ValueError(f"Unsupported platform: {parsed.platform}")

    def _track_inline_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        error_message: str | None = None,
        metadata: dict | None = None,
    ):
        """Record inline download stats with source=inline."""
        self._track_parsed_download(
            parsed,
            user_id,
            username,
            success=success,
            error_message=error_message,
            source="inline",
            metadata=metadata,
        )

    def _track_parsed_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        source: str,
        error_message: str | None = None,
        metadata: dict | None = None,
    ):
        """Record download stats for a parsed media link."""
        title = _media_title(metadata) or parsed.description
        if parsed.platform == "youtube" and parsed.mode == "audio":
            self.stats.track_audio_download(
                user_id,
                parsed.quality,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform in {"youtube", "youtube_shorts"}:
            platform = "youtube_shorts" if parsed.platform == "youtube_shorts" else "youtube"
            self.stats.track_video_download(
                user_id,
                parsed.quality,
                platform,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform == "pinterest":
            self.stats.track_pinterest_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        else:
            # tiktok + twitter (existing DM path also uses tiktok tracker for twitter)
            self.stats.track_tiktok_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
